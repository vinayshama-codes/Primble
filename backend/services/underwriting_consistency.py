"""underwriting_consistency.py

Core Underwriting Data Consistency (Beta Report §4.3).

Treats a small set of high-value underwriting fields — seeded with **Gross
Sales** (the ``total_revenue`` fact) — as *normalized data elements* that may
appear across multiple source documents (and, once stamped, across multiple
ACORD forms). For each such field this module:

  1. Extracts and NORMALIZES every value present across the uploaded documents.
  2. Groups the values by their normalized form and records WHICH document each
     raw value came from (source attribution).
  3. Flags a non-blocking review when two or more *materially different*
     (post-normalization) values are present.
  4. Lets the user confirm the correct value, which is then applied to the
     merged facts so it flows consistently into every relevant form and into
     SQS scoring.

Design notes
------------
* PURE module — takes already-extracted per-document facts + the merged facts
  and returns a verdict dict. No DB, no I/O, no network. Easy to unit-test.
  Mirrors ``submission_integrity.py``.
* REUSABLE ENGINE — every reconcilable field is one entry in
  ``RECONCILABLE_FIELDS``. Adding total_payroll / num_employees / FEIN later is
  a one-line config add, not new bespoke code (Beta Report §4.3:
  "Gross Sales and similar underwriting fields").
* EXACT MATCH AFTER NORMALIZATION — ``$1,000,000`` == ``1000000`` ==
  ``1,000,000.00`` (no conflict), but ``1,000,000`` vs ``1,200,000`` conflicts.
  No silent tolerance band that could hide a real underwriting difference.
* NON-BLOCKING — a discrepancy produces ``review_required`` on the field, NOT a
  hard stop. Consistent with §5 (avoid false hard stops); the §4.3 acceptance
  wording is "flagged for review".
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

# Workstream-2 normalization layer (leaf module — no cycle). "identity" fields
# (name/date/entity/address/carrier/fein) compare via this so the picker uses
# the exact same equivalence rules as the cross-document conflict detectors.
#
# DATE_FIELDS / FEIN_FIELDS / _infer_field_category are imported for
# ``_scan_shape`` below: deciding whether a field's value has a machine-
# checkable shape is the SAME question WS-2 already answers when it picks a
# normalizer, so it is answered from WS-2's own tables rather than a second
# copy of the "..._date means a date" convention living here. A local copy
# would be free to drift, and a field captured by one rule but validated by
# another is precisely the defect class this module has now hit three times.
from services.normalization import (
    normalize_value, DATE_FIELDS, FEIN_FIELDS, _infer_field_category,
)

logger = logging.getLogger(__name__)

UNDERWRITING_CONSISTENCY_MODEL_VERSION = "1.1.0"

# Confidence/source labels for a user-confirmed value applied to merged facts.
# "client_arq" scores 1.00 in sqs_service.CONFIDENCE_SCORE — a value the broker
# explicitly confirmed is producer-verified truth.
_CONFIRMED_CONFIDENCE = "client_arq"
_CONFIRMED_SOURCE = "user_confirmed"

# ── Text-scan patterns for reconcilable fields ────────────────────────────────
# When the LLM produces the same value from two documents that actually contain
# different numbers (e.g. because it anchors to the dec page value), these
# patterns scan the raw OCR text directly to surface ALL revenue/payroll figures
# associated with revenue-like labels. Used as a cross-check layer on top of
# the LLM extraction — if the text scan finds a materially different figure in
# a doc that the LLM reported as agreeing, the text-scan value is surfaced for
# review alongside the LLM-extracted value.
#
# Pattern design: label keyword(s) + optional whitespace/colon/dash + a VALUE
# SHAPE. Captures the value only (group 1).
#
# ── Value shapes ─────────────────────────────────────────────────────────────
# The single definition of what each type of value may look like in raw text.
# Shared by the bespoke patterns below AND by the generic fallback, so the two
# can never capture different things for the same kind of field — that
# divergence is exactly what let a prose sentence become a candidate Employee
# Count. Each is a single capture group.
_SCAN_SHAPE_CURRENCY = r"(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)"
_SCAN_SHAPE_INTEGER  = r"(\d[\d,]*)"
_SCAN_SHAPE_FEIN     = r"(\d{2}-?\d{7})"
# Date token shared by the effective/expiration scanners (MM/DD/YY[YY],
# MM-DD-YY[YY], YYYY-MM-DD, with '.' separators too).
_DATE_RX = r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"
_SCAN_SHAPE_DATE = _DATE_RX

_TEXT_SCAN_PATTERNS: Dict[str, List[str]] = {
    "total_revenue": [
        # Explicit "Annual Revenue" / "Gross Sales" / "Gross Revenue" labels
        r"(?:annual\s+(?:gross\s+)?(?:revenue|sales|receipts)|gross\s+(?:sales|revenue|receipts))"
        r"\s*[:\-–]?\s*" + _SCAN_SHAPE_CURRENCY,
        # "Revenue: $X" / "Total Revenue: $X"
        r"(?:total\s+)?revenue\s*[:\-–]\s*" + _SCAN_SHAPE_CURRENCY,
        # "Gross Sales: $X" / "Projected Gross Sales: $X" / "Current Year ... Sales: $X"
        r"(?:projected\s+|current\s+year\s+)?gross\s+sales\s*[:\-–]?\s*"
        + _SCAN_SHAPE_CURRENCY,
        # "Sales / Revenue: $X"
        r"sales\s*/\s*revenue\s*[:\-–]\s*" + _SCAN_SHAPE_CURRENCY,
    ],
    # Payroll — "(Total/Estimated/Annual) Payroll: $X" and "Remuneration: $X".
    "total_payroll": [
        r"(?:total\s+|estimated\s+|annual\s+){0,2}payroll\s*[:\-–]?\s*"
        + _SCAN_SHAPE_CURRENCY,
        r"(?:estimated\s+|annual\s+){0,2}remuneration\s*[:\-–]?\s*"
        + _SCAN_SHAPE_CURRENCY,
    ],
    # Building value — building-specific labels only (the word "building" must
    # precede the amount) so a contents/BPP figure can't masquerade as a conflict.
    #
    # `\b` ADDED 2026-09-06, and this is the highest-consequence boundary bug in
    # the codebase: `property_building_value` is the ONLY key in
    # GENERATION_BLOCKING_RECONCILABLE_KEYS, so a false conflict here does not
    # warn - it REFUSES TO GENERATE FORMS. Measured on an ordinary property
    # schedule:
    #     Building Value:      1,250,000
    #     Outbuilding Value:      45,000
    # Without the boundary the second line matches "building value" INSIDE
    # "Outbuilding", the document appears to state two different building
    # values, and the submission is held for review over a shed.
    "property_building_value": [
        r"\bbuilding\s+(?:value|limit|coverage|replacement\s+cost|amount)\s*[:\-–]?\s*"
        + _SCAN_SHAPE_CURRENCY,
    ],
    # ── Identity / policy fields (label-anchored; first labelled match wins) ──
    # These recover the real per-document value when the LLM collapsed it. Each
    # capture is validated/deduped through the field's WS-2 normalizer, so a
    # formatting-only difference (07/15/25 vs 7/15/2025) never surfaces a conflict.
    # Only BOUNDED-shape identity fields appear here — see ``_scan_shape``.
    "effective_date": [
        r"\b(?:policy\s+)?effective(?:\s+date)?\s*[:\-]?\s*" + _SCAN_SHAPE_DATE,
    ],
    "expiration_date": [
        r"\b(?:policy\s+)?expir\w*(?:\s+date)?\s*[:\-]?\s*" + _SCAN_SHAPE_DATE,
    ],
    "fein": [
        r"\b(?:fein|f\.e\.i\.n|ein|fed(?:eral)?\s*(?:employer\s*)?"
        r"(?:id|tax\s*id|identification)|tax\s*id(?:entification)?"
        r"(?:\s*(?:no|number|#))?)\b\s*[:#]?\s*" + _SCAN_SHAPE_FEIN,
    ],
    # Free-text identity fields (applicant/DBA/carrier name, mailing/physical
    # address, entity type) are DELIBERATELY absent — ``_scan_shape`` returns
    # None for them and they are never text-scanned at all. A bespoke pattern
    # here would be unreachable. See the comment above ``_scan_shape``.
}

# Fields with NO bespoke pattern above still get a text-scan safety net via this
# generic fallback: <field label words> + ":"/"-" + the field's OWN value shape.
# This is what makes the safety net apply to EVERY reconcilable field (current
# and future — adding a new entry to RECONCILABLE_FIELDS is enough), not just
# the fields the client happened to name as examples. Deliberately conservative
# (requires a colon/dash after the label) so it only fires on an explicitly
# labelled line, never a stray mention.
#
# The ``shape`` argument is mandatory and comes from ``_scan_shape``: there is
# no "default" capture, because a capture loose enough to fit any field is a
# capture loose enough to swallow a sentence. It is not anchored to end-of-line
# — the shape is self-delimiting, and requiring EOL would miss the very common
# "Employee Count: 47 full-time" form.
def _generic_label_pattern(label: str, shape: str) -> str:
    words = re.escape(label.strip()).replace(r"\ ", r"\s+")
    return rf"\b{words}\s*[:\-]\s*{shape}"


# ── A LABEL QUALIFIED BY A FOREIGN SUBJECT IS NOT THIS FIELD'S LABEL ─────────
# V1 H3-D, found on the first live WC run (2026-08-27). The bespoke pattern for
# `effective_date` is `\b(?:policy\s+)?effective(?:\s+date)?...`, and `\b` sits
# happily in the middle of
#
#     Experience Modification Effective Date: 07/13/2026
#
# so the X-Mod's effective date was scanned as a rival POLICY effective date.
# Measured live: a false "Policy Effective Date - values differ" card, an
# Important warning, and an SQS capped at 85 - on EVERY WC package that prints
# a mod effective date. Confirmed by the control: the one package with no mod
# date showed no conflict.
#
# This is the 2026-08-08 defect class again (a label regex capturing a
# different field's value) and it takes the same shape of fix as H1-K's payroll
# gate: a NECESSARY condition needs a STRUCTURAL second one. The label must not
# be owned by another subject standing immediately in front of it.
#
# Deny-list, not allow-list, and deliberately: it can only ever DROP a scanned
# rival candidate, never invent one. The worst case is that a genuine conflict
# phrased this way stops being detected - which is exactly the behaviour before
# this scanner existed - whereas the allow-list direction manufactures false
# conflicts, which is the live defect.
_FOREIGN_LABEL_QUALIFIERS = (
    "experience", "modification", "mod", "x-mod", "xmod", "emod", "merit",
    "rating", "anniversary", "retro", "retroactive", "audit", "birth",
    "hire", "hired", "termination", "inspection", "quote", "bind", "binder",
)
_QUALIFIER_TAIL_CHARS = 48


def _label_has_foreign_subject(text: str, start: int) -> bool:
    """Do the words immediately before this match name a DIFFERENT subject?

    Structural, never a distance window: only the text on the SAME line, and
    only the last two words before the label - "Experience Modification" in
    "Experience Modification Effective Date" - so a mod mentioned a sentence
    earlier can never suppress a genuine policy date.
    """
    head = text[max(0, start - _QUALIFIER_TAIL_CHARS):start]
    head = head.rsplit("\n", 1)[-1]          # same line only
    words = re.findall(r"[A-Za-z][\w\-]*", head)
    return any(w.lower() in _FOREIGN_LABEL_QUALIFIERS for w in words[-2:])

# ── Plausibility floor for a scanned numeric value ───────────────────────────
# The floor rejects a stray small number that happens to follow a label-ish
# word ("Sales: 5" inside a ratio table). What counts as "stray" depends on
# what the money MEANS, not on which field it is — so it is DERIVED from the
# field's money role, not listed per field. A per-field number would be one
# more thing to remember, and forgetting is how every defect in this module
# happened.
#
# EXPOSURE figures (revenue, payroll, property values, limits) are
# business-scale and are reached by LOOSE labels ("revenue", "sales"), so they
# keep a real floor.
#
# RETENTION figures (deductibles, SIRs, self-insured retentions) are small BY
# NATURE — $0, $250, $500 and $1,000 are all ordinary, and the client's own
# reported Auto case was a $1,000 deductible. Sharing the exposure floor meant
# every retention field silently failed the check on realistic values: their
# safety net had never once fired. They carry no magnitude floor, because
# their label anchor ("GL Deductible:", "Umbrella SIR:") is specific enough to
# be the entire check — unlike the bare word "revenue".
_SCAN_FLOOR_EXPOSURE  = 10_000
_SCAN_FLOOR_RETENTION = 0        # 0 == no magnitude filter; the label is the check

# Whole snake_case/label tokens that mark a money field as a RETENTION. Token
# matching (never substring) so "sir" cannot fire inside another word. A
# future property_deductible / cyber_retention / wc_sir is classified correctly
# on the day it is added, with no edit here.
_RETENTION_MONEY_TOKENS = frozenset({
    "deductible", "deductibles", "sir", "sirs", "retention", "retentions",
})


def _scan_min_amount(fact_key: str, cfg: dict) -> int:
    """Smallest value a text-scan may accept for this numeric field.

    Counts (``integer``) have no meaningful magnitude floor — "Employee Count:
    3" is an ordinary answer — so they return 0. Currency fields are floored
    by their money role (see the comment above). Reads BOTH the fact key and
    the human label, so an abbreviated key still classifies correctly if its
    label spells the role out.
    """
    cfg = cfg or {}
    if cfg.get("kind") != "currency":
        return 0
    tokens = set(re.split(r"[^a-z0-9]+", f"{fact_key} {cfg.get('label') or ''}".lower()))
    if tokens & _RETENTION_MONEY_TOKENS:
        return _SCAN_FLOOR_RETENTION
    return _SCAN_FLOOR_EXPOSURE


def _below_scan_floor(normalized_amount: str, floor: int) -> bool:
    """True when a normalized numeric string falls under an ACTIVE floor.

    An unparseable amount under an active floor is rejected — it cannot be
    shown to clear the bar. Callers skip this entirely when ``floor`` is 0.
    """
    try:
        return int(str(normalized_amount).split(".")[0]) < floor
    except (ValueError, IndexError):
        return True


def _scan_shape(fact_key: str, cfg: dict) -> Optional[str]:
    """The regex shape this field's value must match to be text-scannable, or
    ``None`` when the field has no machine-checkable shape (→ never scanned).

    THIS IS THE WHOLE SAFETY RULE, in one place, derived rather than listed.
    A text-scan is a context-blind regex reading raw policy prose. It is only
    ever safe when the field's value has a shape that ordinary prose cannot
    accidentally produce — digits, "$", a date separator. When the value is
    free text, ANY run of words matches, and insurance documents are wall-to-
    wall legal boilerplate using the same trigger words the labels do.

    FOUR incidents, one root cause: applicant_name captured "c. Any person or
    organization having proper..." (a CGL "WHO IS AN INSURED" list item), then
    "any architects, engineers or surveyors not..." (a professional-services
    exclusion); mailing_address captured "of such notice will be sufficient
    proof of notice. in compliance with laws, rules, or" (a notice-of-mailing
    clause); entity_type captured "not otherwise classified for rating
    purposes". Each outranked the real value because a sentence is longer than
    a name. Denylisting each clause's words is whack-a-mole against an
    unbounded set of legal prose — the FIELD, not the clause, is the bug.

    The same rule cuts the other way for numerics: a headcount or a dollar
    figure DOES have a checkable shape, so those keep their safety net (its
    original purpose — catching the LLM collapsing one document's number onto
    another's — is real and still needed). They were previously broken in the
    opposite direction: routed through the prose-shaped generic fallback, so
    "Employee Count - varies seasonally based on staffing needs" captured
    cleanly. Numeric fields now capture a numeric shape, which makes that
    match structurally impossible rather than filtered after the fact.

    Fail-safe by construction: anything not POSITIVELY identified as bounded
    returns None. A new field added to RECONCILABLE_FIELDS with an unforeseen
    type is exempted, never scanned with a guessed pattern — consistent with
    the standing blank-over-wrong rule. ``test_every_reconcilable_field_has_a_
    resolved_scan_shape`` fails the build if a new field lands here silently.

    Boundedness for identity fields is answered from WS-2's own field tables
    (see the import note at the top of this module), so "scannable" and
    "normalized as a bounded type" can never disagree.
    """
    kind = (cfg or {}).get("kind")
    # Numeric kinds are authoritative — their shape follows from the kind alone.
    if kind == "currency":
        return _SCAN_SHAPE_CURRENCY
    if kind == "integer":
        return _SCAN_SHAPE_INTEGER
    # Identity fields: only the bounded subtypes (FEIN, dates) are scannable.
    if fact_key in FEIN_FIELDS:
        return _SCAN_SHAPE_FEIN
    if fact_key in DATE_FIELDS or _infer_field_category(fact_key) == "date":
        return _SCAN_SHAPE_DATE
    # Everything else — names, addresses, entity type, carrier, kind "text",
    # and any future unrecognised field — is free text. Not scannable.
    return None


# Fields with NO structural completeness signal at all — a name is either
# longer or it isn't, with no way to tell "more descriptive" from "a longer
# garbage string" the way a ZIP+4 or a 9-digit FEIN can be checked. These
# fields rank candidates by DOCUMENT AGREEMENT first in _suggest_for_field
# (see there) rather than by raw length, so a single document's outlier can
# never outrank a value multiple real documents agree on.
#
# Deliberately NOT the same set as the text-scan exemption (``_scan_shape``
# returning None): addresses and entity type are also exempt from scanning,
# but addresses DO have a real completeness signal (ZIP+4, street number) and
# keep completeness-first ranking. Merging the two sets would silently change
# how address conflicts are ranked as a side effect of a scanning fix.
_NAME_LIKE_FIELDS = frozenset({"applicant_name", "dba_name", "carrier_name"})


def _text_scan_values(text: str, fact_key: str) -> List[str]:
    """Scan raw OCR text for values of ``fact_key`` directly.

    This is the safety net for the LLM COLLAPSING per-document values — it may
    extract the dec-page value for every document even when a document's own
    text clearly states a different one (observed for Gross Sales). Scanning
    each document's raw text recovers the real value regardless of what the
    LLM returned — so cross-document conflicts surface even when extraction
    (or its cache) flattened them.

    NUMERIC fields (currency/integer) return every distinct figure found — the
    whole point is to surface a second, different number the LLM missed —
    with a min-amount floor on currency. Date/FEIN fields return only the
    FIRST labelled match in the doc, so a prior/renewal date or a second
    mention can't manufacture an intra-document false conflict. Every value is
    validated through the field's OWN normalizer (never the loose text
    fallback), so a capture that isn't really a value of this type is dropped.

    Fields whose value has no machine-checkable shape are excluded entirely —
    ``_scan_shape`` returns None for them. See its docstring for why.
    """
    cfg = RECONCILABLE_FIELDS.get(fact_key, {})
    shape = _scan_shape(fact_key, cfg)
    if shape is None:
        return []
    patterns = _TEXT_SCAN_PATTERNS.get(fact_key)
    if not patterns and cfg.get("label"):
        # Generic safety net for any reconcilable field without a bespoke
        # pattern — keeps this module a "reusable engine" (see module docstring)
        # instead of only covering the fields called out by name. It uses the
        # field's own value shape, so it can never capture more loosely than a
        # bespoke pattern would.
        patterns = [_generic_label_pattern(cfg["label"], shape)]
    if not patterns or not text:
        return []
    kind = cfg.get("kind")
    is_numeric = kind in ("currency", "integer")
    floor = _scan_min_amount(fact_key, cfg)
    found: Dict[str, str] = {}   # normalized -> first raw match (insertion order)
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw = (m.group(1) or "").strip()
            if not raw:
                continue
            # This field's label, or another subject's? See the constant above.
            if _label_has_foreign_subject(text, m.start()):
                logger.debug(
                    "text scan: dropped %s=%r - label qualified by another "
                    "subject", fact_key, raw)
                continue
            if kind == "currency":
                norm = _normalize_currency(raw)
            elif kind == "integer":
                # NATIVE integer normalizer, not normalize_value's generic text
                # fallback — a count must be a number or it is not a count.
                norm = _normalize_integer(raw)
            else:
                # Date/FEIN → validate + dedupe via the WS-2 normalizer, which
                # returns '' for anything that isn't really a date/FEIN.
                norm = normalize_value(fact_key, raw)
            if not norm:
                continue
            if floor and _below_scan_floor(norm, floor):
                continue
            found.setdefault(norm, raw)
            if not is_numeric:
                # One labelled value per document for date/FEIN fields.
                return [raw]
    return list(found.values())


# ── Reconcilable field registry (the reusable engine) ─────────────────────────
#
# kind:  "currency" → money amounts (Gross Sales, payroll, ...)
#        "integer"  → whole-number counts (employee count, ...)
#        "text"     → fallback exact-match on normalized text
# forms: ACORD form ids that consume this fact (for the "applied to N forms"
#        message). Gross Sales stamps into 125/126/131 via the alias bridge
#        (alias_stamper.CANONICAL_TO_EXTRACTION:
#         business_information_annual_gross_receipts_amount -> total_revenue).

RECONCILABLE_FIELDS: Dict[str, Dict[str, Any]] = {
    "total_revenue": {
        "label": "Gross Sales / Annual Revenue",
        "kind":  "currency",
        # Fallback only — the live "applied to" list is derived dynamically from
        # the real stamping paths (rules + alias bridge) via pdf_service.
        # forms_consuming_fact, which also covers ACORD 160/186. ACORD 125 is
        # intentionally absent: its sole revenue field is the location-level
        # CommercialStructure_AnnualRevenueAmount, which is never stamped with
        # the business-level Gross Sales figure.
        "forms": ["ACORD_126", "ACORD_131", "ACORD_160", "ACORD_186"],
    },
    # Building Value duplication/inflation/inconsistency across documents (client
    # Property Integrity directive). Reconciled exactly like Gross Sales: when two
    # documents report MATERIALLY different building values the field is flagged
    # for review before forms are generated, with source attribution and a
    # confirmation path. Formatting-only differences ($500,000 == 500000) do not.
    "property_building_value": {
        "label": "Building Value",
        "kind":  "currency",
        # Fallback only — live list derived dynamically (see total_revenue note).
        # Building Value is stamped deterministically into ACORD 140's premises
        # limit rows; ACORD 141/28 have no deterministic building-value field.
        "forms": ["ACORD_140"],
    },
    # ── Identity / policy fields (Beta Report §5 picker) ─────────────────────
    # kind "identity" routes through the Workstream-2 normalization layer
    # (services.normalization.normalize_value) so formatting/synonym/alias-only
    # variants ("ORBIN CONTRACTING LLC" vs "Orbin Contracting, LLC", 07/15/25 vs
    # 7/15/2025, LLC vs Limited Liability Company, ST vs Street, EMC vs Employers
    # Mutual Casualty) collapse to ONE value and never surface as a picker
    # conflict — only MATERIALLY different values do. The picker lets the broker
    # choose (or type) the correct value, which is then applied across forms.
    "applicant_name":   {"label": "Applicant / Named Insured", "kind": "identity", "forms": []},
    "dba_name":         {"label": "DBA / Trade Name",          "kind": "identity", "forms": []},
    "fein":             {"label": "FEIN",                      "kind": "identity", "forms": []},
    "entity_type":      {"label": "Entity Type",               "kind": "identity", "forms": []},
    "mailing_address":  {"label": "Mailing Address",           "kind": "identity", "forms": []},
    "physical_address": {"label": "Physical Address",          "kind": "identity", "forms": []},
    "effective_date":   {"label": "Policy Effective Date",     "kind": "identity", "forms": []},
    "expiration_date":  {"label": "Policy Expiration Date",    "kind": "identity", "forms": []},
    "carrier_name":     {"label": "Carrier",                   "kind": "identity", "forms": []},
    # ── SYS-06: the rest of the client's chain ───────────────────────────────
    #   Line of Business -> Carrier -> NAIC -> Policy Number -> Effective Date
    #                    -> Expiration Date -> Source
    # `carrier_name`, `effective_date` and `expiration_date` were already
    # curated; `policy_number` and `carrier_naic` reached the picker only
    # through `ENABLE_FULL_FIELD_RECONCILIATION` auto-discovery, and an
    # auto-discovered field is DROPPED from the payload the moment its status
    # is "scoped". So on a healthy four-policy package the producer was shown
    # nothing at all about policy numbers, and on an unhealthy one a single
    # package-wide "pick one" list. Curating them makes the SCOPED row - the
    # per-line mapping the client asked to see - render like every other
    # curated field. A "consistent" row still renders nowhere (the panel draws
    # conflict / confirmed / scoped only), so a single-policy package gains no
    # new noise.
    "policy_number":    {"label": "Policy Number",             "kind": "identity", "forms": []},
    "carrier_naic":     {"label": "Carrier NAIC",              "kind": "identity", "forms": []},
    # ── Core underwriting numeric fields (Beta Report §4.3 "and similar fields") ─
    # Reconciled exactly like Gross Sales: cross-document conflicts are flagged
    # for review (non-blocking) with source attribution and a confirmation path,
    # and a confirmed value flows across forms + scoring. "forms" is a fallback
    # only — the live list is derived dynamically (see total_revenue note).
    "total_payroll": {
        "label": "Total Annual Payroll",
        "kind":  "currency",
        "forms": ["ACORD_131", "ACORD_160", "ACORD_186"],
    },
    "num_employees": {
        "label": "Employee Count",
        "kind":  "integer",
        "forms": ["ACORD_125", "ACORD_126", "ACORD_131", "ACORD_186"],
    },
    # ── Deductible / SIR consistency (Decision_Tree.txt lines 226-231: "Validate
    # deductibles and SIRs are consistent across ACORD 126/127, ACORD 131, and dec
    # page representations. Flag unexplained discrepancies.") — added 2026-08-07.
    # This is the ONLY correct reading of that spec line: it asks whether the SAME
    # figure agrees across its multiple mentions (dec page vs. the form it stamps),
    # not whether SIR and a deductible should be compared to EACH OTHER. That wrong
    # comparison was `cross_form_validator._check_umbrella_sir_vs_auto_deductible`
    # (removed the same day — GL deductible, Auto deductible, and Umbrella SIR cover
    # different coverage parts and are never compared to one another, here or
    # anywhere else in the codebase).
    #
    # ENABLE_FULL_FIELD_RECONCILIATION was already sweeping these fields in
    # generically (any scalar fact not curated here gets auto-discovered — see
    # `_auto_scalar_keys`), but only as a blanket "identity" kind. That silently
    # degrades them: identity's completeness scoring ranks candidates by raw
    # STRING LENGTH (`_value_completeness`), which is meaningless for a dollar
    # figure ("$1,000,000" isn't more "complete" than "1000000"); currency/integer
    # fields are deliberately excluded from that scoring for exactly this reason.
    # Auto-discovery also can't derive the real "applied to N forms" list
    # (`_forms_for_field` only does the dynamic lookup for kind in
    # currency/integer) and validates a confirmation with the loose text
    # normalizer instead of rejecting a non-numeric value outright. Curating
    # these properly as "currency" fixes all four at once - not a duplicate of
    # what auto-discovery was already doing, a correctly-typed replacement of it.
    #
    # Non-blocking by design, matching total_revenue/total_payroll/num_employees
    # above and the spec's own wording ("Flag unexplained discrepancies") - not
    # added to HARD_STOP_RECONCILABLE_KEYS or GENERATION_BLOCKING_RECONCILABLE_KEYS.
    "umbrella_sir": {
        "label": "Umbrella SIR",
        "kind":  "currency",
        "forms": ["ACORD_131"],
    },
    "gl_deductible": {
        "label": "GL Deductible",
        "kind":  "currency",
        "forms": ["ACORD_126"],
    },
    "auto_deductible_comp": {
        "label": "Auto Comprehensive Deductible",
        "kind":  "currency",
        "forms": ["ACORD_127"],
    },
    "auto_deductible_collision": {
        "label": "Auto Collision Deductible",
        "kind":  "currency",
        "forms": ["ACORD_127"],
    },
    # Client 2026-08-15 (Orbin): dec page $3,000,000, later COI $1,000,000 -
    # credible sources disagreeing on a LEGAL LIMIT. Curated as currency (the
    # auto-discovery sweep degraded it to identity kind: string-length ranking,
    # no forms list, loose text validation). Also in CONFLICT_WITHHOLD_KEYS
    # below: an unresolved conflict on it withholds the stamped value.
    "umbrella_limit": {
        "label": "Umbrella / Excess Limit",
        "kind":  "currency",
        "forms": ["ACORD_131"],
    },
    # ── Extend here (no other code change needed) ────────────────────────────
    # Add a one-line entry: {"label": ..., "kind": "currency"|"integer", "forms": [...]}.
}

# Fields whose conflict is a HARD STOP until the user resolves it (kept blocking
# in check_doc_consistency while unconfirmed; the picker is the resolution path).
# Informational only here — the gating still lives in sqs_service.check_doc_consistency.
HARD_STOP_RECONCILABLE_KEYS = frozenset({
    "applicant_name", "fein", "effective_date", "expiration_date",
})

# Of those, the ones that belong to a CONTRACT rather than to the APPLICANT.
# A package has one insured and one FEIN however many policies it carries, so
# a disagreement there is always worth blocking. It does NOT have one policy
# term: three policies legitimately carry three terms, and calling that a
# blocking error caps an ordinary account at 60 (probe run C, 2026-08-17).
#
# `check_doc_consistency` downgrades its OWN copy of this rule; this set is what
# lets the reconciler's hard-stop escalation in extraction_pipeline reach the
# same conclusion instead of keeping a second, divergent opinion. Two engines
# with one rule each is how the first cut of this fix shipped a warning and a
# hard stop for the same difference on the same screen.
CONTRACT_SCOPED_HARD_STOP_KEYS = frozenset({
    "effective_date", "expiration_date",
})

# Fields whose unresolved conflict must BLOCK form generation until the user
# confirms the correct value (client Property Integrity directive: "Building Value
# Duplication ... generate a warning and require review before forms are
# generated."). This is a generation-time gate only — scoring, recommendations,
# and the questionnaire still run; the confirmation picker is the resolution path.
GENERATION_BLOCKING_RECONCILABLE_KEYS = frozenset({
    "property_building_value",
})

# Fields whose unresolved conflict WITHHOLDS the stamped value (the box ships
# blank until the picker confirms) without blocking generation. Client
# 2026-08-15: "Unresolved conflicts must remain unresolved. When credible
# sources disagree, Primble should preserve that conflict and ask for
# confirmation rather than choosing whichever value seems most likely." A
# legal limit is exactly where the merge's most-frequent-wins ranking must
# never pick a winner silently. Extend by adding the key here - the stamping
# side (pdf_service._resolve_conflicted_fact_blank) is generic.
# BRENT DECISION 2026-08-21 (Q4), answering "when two documents disagree, do
# we leave the box empty on the form?" - **"we should patch the suggested
# value."** So this set is now EMPTY: a cross-document conflict stamps the
# merge's suggested value instead of shipping an owned blank.
#
# WHY THIS DOES NOT BREAK CLIENT RULE 1.4. The rule says *"do not arbitrarily
# select one ... the conflict should remain visible and route to the producer"*.
# Both halves still hold: the Data Consistency picker still shows every
# competing value with its source and a Confirm button, the fact is still
# `value_state: conflicting`, and confirming still re-applies across every
# form. What changed is only whether the BOX is empty while that is open -
# and the owner's point is that an empty box on a form he may want to send
# today is worse than a marked suggestion he can see and change.
#
# THE TENSION, recorded so nobody reverses this by accident: the 2026-08-15
# client note ("unresolved conflicts must remain unresolved ... rather than
# choosing whichever value seems most likely") is what put `umbrella_limit`
# here in the first place, over the $3,000,000-vs-$1,000,000 case. Brent has
# now answered the narrower question directly. To restore the old behaviour,
# put the key back in this set - nothing else needs to change.
#
# NOT AFFECTED: `extraction_service._flag_intra_document_limit_conflicts`
# writes `_uw_conflicted_keys` for a conflict INSIDE one document. Brent was
# asked about two documents disagreeing, and Principle 7 forbids extending a
# ruling past what was asked, so that path still blanks.
CONFLICT_WITHHOLD_KEYS: frozenset = frozenset()


def is_withheld(facts: Optional[dict], fact_key: str) -> bool:
    """True when this fact's value is UNRESOLVED and must not be published.

    THE ONE GATE. Client 2026-08-17: *"Data Consistency shows $3M vs $1M as
    unresolved ... Form Recommendation still references $3M ... an unresolved
    fact must remain unresolved downstream rather than another part of Primble
    independently selecting a value."*

    The withhold list has existed since 2026-08-15 and worked - but only two
    modules ever read it (``pdf_service._resolve_conflicted_fact_blank`` and
    ``alias_stamper``), both on the STAMPING side. Every other surface that
    renders a fact to a human read the merged value directly, so the form
    correctly shipped a blank umbrella limit while the recommendation panel
    printed "$3,000,000" on two forms. Reproduced in three lines on 2026-08-17.

    Any surface that shows a fact to a human must consult this. It is
    deliberately a plain read of the list the pipeline already computes - no new
    state, no new plumbing, and confirming in the picker clears it on the next
    pipeline run exactly as it does for stamping.
    """
    if not isinstance(facts, dict) or not fact_key:
        return False
    return fact_key in (facts.get("_uw_conflicted_keys") or ())


def unresolved_withheld_keys(uw_result: Optional[dict],
                             confirmations: Optional[dict]) -> List[str]:
    """Fact keys whose stamped value must be withheld right now.

    A key qualifies when the stored reconciliation flags it review_required,
    it is in CONFLICT_WITHHOLD_KEYS, and the user has not confirmed a value
    for it. Consumed at generation/re-stamp time to build
    facts["_uw_conflicted_keys"]; confirming in the picker clears it on the
    next recompute, which is what lets the confirmed value stamp.
    """
    confirmed = set(usable_confirmations(confirmations).keys())
    out = []
    for f in (uw_result or {}).get("fields") or []:
        if not isinstance(f, dict):
            continue
        key = f.get("fact_key")
        if (key in CONFLICT_WITHHOLD_KEYS and f.get("review_required")
                and key not in confirmed):
            out.append(key)
    return sorted(set(out))


def unresolved_conflict_keys(uw_result: Optional[dict],
                             confirmations: Optional[dict]) -> List[str]:
    """Fact keys the documents still disagree about and nobody has confirmed.

    The SUPERSET of `unresolved_withheld_keys`: same review_required test, same
    confirmation test, but WITHOUT the `CONFLICT_WITHHOLD_KEYS` membership
    filter - which is currently empty, because Brent ruled (Q4 / D16,
    2026-08-21) that a cross-document conflict STAMPS its suggested value
    rather than shipping an owned blank.

    That ruling settles what gets PRINTED. C3 3.8 asks a different question
    about the same fact: *"Conflicting fields should not receive full
    completed-field credit."* The two do not conflict - the value is stamped
    (D16) and its fill-rate weight is reduced (3.8) - but the withhold list
    cannot answer it, because it is deliberately empty. Hence this function.

    Never use it to decide whether to blank a field. That is D16's job and it
    says no.
    """
    confirmed = set(usable_confirmations(confirmations).keys())
    out = []
    for f in (uw_result or {}).get("fields") or []:
        if not isinstance(f, dict):
            continue
        key = f.get("fact_key")
        if key and f.get("review_required") and key not in confirmed:
            out.append(key)
    return sorted(set(out))

# Keys excluded from the crude cross-doc conflict detectors so this engine is
# the single source of truth for them (prevents un-normalized false positives).
RECONCILABLE_FIELD_KEYS = frozenset(RECONCILABLE_FIELDS.keys())

# Which curated fields are NOT text-scanned, DERIVED from _scan_shape rather
# than hand-listed — a hand-list is a thing to forget, which is how three of
# the four incidents happened. Introspection/documentation surface (and what
# the regression tests assert against); the live gate is _scan_shape itself,
# so this can never drift from real behaviour.
_TEXT_SCAN_EXEMPT_FIELDS = frozenset(
    k for k, c in RECONCILABLE_FIELDS.items() if _scan_shape(k, c) is None
)


# ── Value extraction (handles the {value, confidence} envelope) ───────────────

def _fv(facts: dict, key: str, default=None):
    """Extract a scalar fact, unwrapping the annotated {value, confidence} envelope."""
    if not isinstance(facts, dict):
        return default
    v = facts.get(key, default)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return default
    return v


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize_currency(value: Any) -> Optional[str]:
    """Canonical numeric string for a money amount, or None if not parseable.

    Strips currency symbols, commas, and whitespace; drops insignificant
    trailing zeros after the decimal point so 1000000, $1,000,000 and
    1,000,000.00 all collapse to '1000000'. Returns None when the value
    contains no parseable number (caller falls back to text comparison).
    """
    if value is None:
        return None
    s = str(value).strip()
    # Keep only digits and the decimal point (drop $, commas, spaces, etc.).
    cleaned = re.sub(r"[^\d.]", "", s)
    # Collapse accidental multiple dots ("1.000.000" -> first dot wins is risky;
    # treat as no-decimal thousands grouping → strip all dots if >1).
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    if not cleaned or cleaned == ".":
        return None
    try:
        dec = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    # Canonical string: plain integer when no fractional part; otherwise
    # fixed-point with trailing zeros stripped. Avoids Decimal.normalize()'s
    # scientific notation (1000000 -> '1E+6'), which would break equality.
    if dec == dec.to_integral_value():
        return str(int(dec))
    return format(dec, "f").rstrip("0").rstrip(".")


def _normalize_integer(value: Any) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    if not digits:
        return None
    return str(int(digits))


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _normalize(value: Any, kind: str, fact_key: Optional[str] = None) -> Optional[str]:
    # A MACHINE NON-VALUE IS NOT A CANDIDATE (V1 H7-D, live run 2026-08-27).
    #
    # `_normalize("null", "date")` used to return `'null'` - truthy, so the
    # string sailed through every `if not norm: continue` guard and became a
    # rival VALUE. On the H7 live fixture the extractor emitted a bare "null"
    # for a coverage line that prints no dates, and the picker then reported
    # *"Policy Effective Date: documents disagree (09/17/2026, null)"* plus the
    # same for the expiration - TWO false hard stops capping a perfectly
    # consistent package at 60.
    #
    # This module ALREADY knew the rule: `_fv` (line ~701) drops exactly
    # ""/"null"/"none" when reading a scalar fact. It was simply never applied
    # on the paths that build candidate groups (per-coverage-line and text
    # scan), so there were two copies of "what counts as a non-value" and only
    # one of them ran - the same one-rule-two-copies shape as C1's five
    # comparison sites and H1-C's phantom keys.
    #
    # Scope is deliberately narrow: only the MACHINE's own spellings of "no
    # value found". A human typing "None" is an ANSWER with no value and is
    # handled by `answer_semantics` on a different path (C2-G) - this function
    # only ever sees document-extracted candidates.
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in ("", "null", "none"):
        return None

    # "identity" routes through the Workstream-2 normalization layer so the
    # picker uses the SAME equivalence rules as the cross-document conflict
    # detectors. normalize_value() dispatches by fact_key (name/date/entity/
    # address/carrier/fein) and returns '' for no-signal → treated as absent.
    if kind == "identity":
        # ENTITY NAMES GROUP ON THE STRICT KEY, NEVER ON THE FAMILY MAP (D10).
        # `normalize_value` dispatches a carrier to `normalize_carrier`, whose
        # curated alias map folds "EMC Property & Casualty Company" and
        # "Employers Mutual Casualty Company" BOTH to "emc" - two real legal
        # entities pronounced one fact before the comparison door is ever
        # consulted. That is Round 10 fix 46, and D10 records the same rule for
        # the door's own first pass: *"the coarse normalisers fold two real
        # carriers into one token; that is Round 10 fix 46 and it must not come
        # back one layer up."* It had come back one layer up - here.
        #
        # Invisible until C1b made the per-line carriers candidates: with only
        # one carrier spelling on the package there was nothing to mis-merge.
        # With five, the merged group inherited BOTH the GL line and the Auto
        # line and collided with itself, producing a "two policies on the same
        # coverage line" conflict on a package that has no such thing.
        #
        # SPLITTING HERE IS SAFE: `_merge_equivalent_value_groups` runs after
        # this and re-merges through the door, which folds spelling variants
        # (including abbreviations) while keeping distinct entities apart.
        # Grouping too finely costs a merge pass; grouping too coarsely cannot
        # be undone.
        # A RATING BUREAU IS NEVER THE CARRIER (2026-09-05). Dropped here, beside
        # the machine non-values above, for the same reason they are: it is not
        # a rival answer, so it must not become a candidate group. The picker
        # builds its own groups before consulting the comparison door, so the
        # door's own filter is not reached from here.
        try:
            from services.normalization import (
                is_carrier_field as _is_carrier, is_insurance_bureau as _is_bureau,
            )
            if _is_carrier(fact_key or "") and _is_bureau(value):
                return None
        except Exception:                                     # noqa: BLE001
            pass
        try:
            from services.fact_comparison import _fe as _door
            if _door.value_kind(fact_key or "") == _door.KIND_NAME:
                from services.normalization import strict_entity_key
                return strict_entity_key(value) or None
        except Exception:                                     # noqa: BLE001
            pass
        norm = normalize_value(fact_key or "", value)
        return norm or None
    if kind == "currency":
        norm = _normalize_currency(value)
    elif kind == "integer":
        norm = _normalize_integer(value)
    else:
        norm = None
    # Fall back to text comparison when the numeric normalizer can't parse it
    # (e.g. "1.2 million") so we still detect genuinely different free-text.
    if norm is None and kind != "text":
        norm = _normalize_text(value)
    elif kind == "text":
        norm = _normalize_text(value)
    return norm


# ── Applied-to form list (derived dynamically) ───────────────────────────────

def _forms_for_field(fact_key: str, cfg: dict) -> List[str]:
    """The ACORD forms a confirmed value for this field flows into.

    For currency/integer fields the list is derived dynamically from the real
    stamping paths (deterministic rules + alias bridge) via
    ``pdf_service.forms_consuming_fact`` so the "applied to N forms" badge always
    names the true, complete set. Identity fields keep their declared list
    (empty) so their picker behaviour and UI stay unchanged. Any failure falls
    back to the static registry list — it never regresses.
    """
    static = list(cfg.get("forms") or [])
    if cfg.get("kind") not in ("currency", "integer"):
        return static
    try:
        from services.pdf_service import forms_consuming_fact
        dynamic = forms_consuming_fact(fact_key)
        return dynamic or static
    except Exception as exc:                              # pragma: no cover
        logger.warning("underwriting_consistency: dynamic form list failed for %s — %s", fact_key, exc)
        return static


# ── Suggested value + confidence (Beta Report §4.3 / Figure 3 feedback) ───────
# When documents disagree, recommend the value that looks the most complete /
# correct — NOT the value from a particular document type. Confidence is HIGH
# only when one value is CLEARLY more complete; a genuine tie is LOW. Pre-selection
# (frontend) is reserved for HIGH confidence on non-hard-stop fields, so a wrong
# default can never be silently rubber-stamped onto a legally significant field
# (named insured / FEIN / policy dates).

# A completeness lead of this much (roughly one full structural component such as
# a ZIP+4 or a state) is treated as a CLEAR winner → HIGH confidence.
_COMPLETENESS_MARGIN = 1.0


def _group_doc_count(group: dict) -> int:
    """Number of DISTINCT source documents backing a value group (the tiebreak)."""
    return len({s.get("doc_id") for s in group.get("sources", []) if s.get("doc_id")})


def _value_completeness(fact_key: str, kind: str, value: Any) -> float:
    """Structural completeness score for a candidate value.

    ADDRESS and FEIN carry a specific, hard-to-fake completeness signal (ZIP /
    ZIP+4 / state / street number for addresses; a full 9-digit FEIN) and are
    scored precisely. Every other IDENTITY field (name / entity type / carrier /
    date) falls back to a generic proxy: a longer, more descriptive raw string
    usually carries MORE information than a shorter one representing the same
    normalized value ("Limited Liability Company" vs "LLC", "EMC Property and
    Casualty Company" vs "EMC", "Orbin Contracting LLC" vs "Orbin Contracting") -
    so it is preferred both as the merged display value and as the suggestion.
    CURRENCY/INTEGER/TEXT fields are excluded from the length fallback: their raw
    formatting is arbitrary ("$2,500,000" vs "2500000" say the same thing at the
    same length-of-information), so length is not a genuine completeness signal
    there and scoring them would invent a preference with no basis - they stay at
    0.0, keeping their existing frequency-only tiebreak unchanged.
    """
    s = str(value or "").strip()
    if not s:
        return 0.0

    # WHICH fields get which scoring is now DERIVED from the value's kind, not
    # from a two-key list - an auto-discovered `premises_address` was getting
    # raw-length scoring where a curated `mailing_address` got the real ZIP/
    # state signal. Same rule for every address, however the key is spelled.
    try:
        from services.fact_equivalence import (
            value_kind, KIND_ADDRESS, KIND_FEIN, KIND_NAME, KIND_TEXT,
            KIND_NARRATIVE,
        )
        vk = value_kind(fact_key)
    except Exception:                                     # pragma: no cover
        vk = None
        KIND_ADDRESS = KIND_FEIN = KIND_NAME = KIND_TEXT = KIND_NARRATIVE = None

    if vk == KIND_ADDRESS or fact_key in ("mailing_address", "physical_address"):
        score = len(re.findall(r"\w+", s)) * 0.1          # mild fullness preference
        if re.search(r"\b\d{5}-\d{4}\b", s):
            score += 3.0                                  # ZIP+4 (most complete)
        elif re.search(r"\b\d{5}\b", s):
            score += 2.0                                  # 5-digit ZIP
        if re.search(r"[A-Za-z]{2}\.?\s+\d{5}", s) or re.search(r",\s*[A-Za-z]{2}\b", s):
            score += 1.0                                  # state present ("CO 80216")
        if re.match(r"\s*\d+\b", s):
            score += 0.5                                  # leading street number
        return score
    if vk == KIND_FEIN or fact_key == "fein":
        return 1.0 if len(re.sub(r"\D", "", s)) == 9 else 0.0

    # THE "SUGGESTED" DEFECT (probe run B, 2026-08-17). Raw length was applied
    # to every auto-discovered field, so the longest string won - and the
    # longest string is the one carrying an ANNOTATION or a mis-extraction.
    # Measured: the badge recommended "BUSINESS AUTO COVERAGE FORM" over
    # "Occurrence", "$2,000,000 (any one premises)" over "$2,000,000", and an
    # EXCLUSIONS clause over the real operations description. A false conflict
    # costs a click; a wrong recommendation puts a wrong value on a legal form.
    #
    # Length is only a completeness signal for genuinely descriptive text. A
    # typed value (money, a code, a date, an identifier, a yes/no) has no
    # "more complete" printing - those score 0.0 and ranking falls through to
    # DOCUMENT AGREEMENT, which is real evidence.
    if kind == "identity" and vk in (KIND_NAME, KIND_TEXT, KIND_NARRATIVE, None):
        return len(s) * 0.01
    return 0.0


def _submission_backed(group: dict) -> bool:
    """True when a SUBMISSION-role document backs this value.

    The role axis every source already carries and this picker never read.
    """
    try:
        from services.extraction_service import _SUBMISSION_ROLES
    except Exception:                                         # noqa: BLE001
        return False
    if not isinstance(group, dict):
        return False
    srcs = group.get("sources")
    if not isinstance(srcs, list):
        return False
    return any(isinstance(src, dict)
               and str(src.get("doc_type") or "").strip().lower() in _SUBMISSION_ROLES
               for src in srcs)


def _producer_role_separates(values: List[dict]) -> bool:
    """True when exactly one candidate is backed by the submission."""
    backed = [g for g in values if _submission_backed(g)]
    return len(backed) == 1 and len(backed) < len(values)


def _is_producer_identity_field(fact_key: str) -> bool:
    try:
        from services.extraction_service import _PRODUCER_IDENTITY_KEYS
        return str(fact_key) in _PRODUCER_IDENTITY_KEYS
    except Exception:                                         # noqa: BLE001
        return str(fact_key or "").startswith("producer_")


def _suggest_for_field(fact_key: str, kind: str, values: List[dict]) -> Optional[dict]:
    """Recommend the most complete/correct value for a conflicting field.

    Ranks candidate value groups by completeness (primary) then document
    frequency (tiebreak) — EXCEPT for name-like fields (``_NAME_LIKE_FIELDS``),
    which have no structural completeness signal (unlike addresses' ZIP+4 or
    FEIN's digit count), so document agreement is the primary signal there and
    raw string length is only the tiebreak. Every free-text field (names,
    addresses, entity type — see ``_scan_shape``) now takes its candidates
    exclusively from real Stage-1 LLM extractions, never from the text-scan
    regex. Returns ``{value, normalized, confidence, preselect}``, or None
    when there is nothing to suggest.
    """
    if not values or len(values) < 2:
        return None

    name_like = fact_key in _NAME_LIKE_FIELDS

    def _completeness(g: dict) -> float:
        return _value_completeness(fact_key, kind, g.get("display"))

    # ── THE PRODUCER HAS A ROLE, AND THE PICKER NEVER READ IT ───────────────
    # Client item 4, the half that survived three live runs. The FACT routes
    # correctly (`extraction_service._route_producer_identity`) and the forms
    # print the submitting agency - but this card kept badging the OTHER one
    # "Suggested":
    #
    #     Producer Name   ThinkSmith Agency          from the narrative
    #                     Commercial Risk Solutions  from the expiring dec  <- Suggested
    #
    # Because both appear in ONE document each, `_group_doc_count` ties and the
    # name-like tiebreak is RAW STRING LENGTH: 25 characters beats 17. The
    # picker was recommending the agency being replaced, on a submission whose
    # whole purpose is to replace it.
    #
    # The role is already on every source (`doc_type`); nothing here had to be
    # plumbed. A submission-role document IS the thing being filed, so the
    # agency it names is the one filing it - the same rule the merge applies,
    # read from the same axis, so the card and the form cannot disagree.
    #
    # Acts ONLY when the roles actually separate the candidates: exactly one
    # backed by the submission, at least one not. An incumbent broker who
    # appears in both roles ties as before and the old ranking stands.
    _role_decides = (_is_producer_identity_field(fact_key)
                     and _producer_role_separates(values))
    if _role_decides:
        ranked = sorted(values, key=lambda g: (_submission_backed(g),
                                               _group_doc_count(g),
                                               _completeness(g)), reverse=True)
    elif name_like:
        ranked = sorted(values, key=lambda g: (_group_doc_count(g), _completeness(g)), reverse=True)
    else:
        ranked = sorted(values, key=lambda g: (_completeness(g), _group_doc_count(g)), reverse=True)

    top, second = ranked[0], ranked[1]
    top_c, sec_c = _completeness(top), _completeness(second)
    top_docs, sec_docs = _group_doc_count(top), _group_doc_count(second)

    if _role_decides:
        # Not a tiebreak and not a guess: one document IS the submission and the
        # other documents the programme being replaced.
        confidence = "high"
    elif name_like:
        if top_docs > sec_docs:
            confidence = "high"                               # clearly more corroborated
        elif top_c > sec_c:
            confidence = "medium"                             # equally corroborated, more descriptive
        else:
            confidence = "low"                                # genuine tie — no clear winner
    else:
        if top_c - sec_c >= _COMPLETENESS_MARGIN:
            confidence = "high"                               # clearly more complete
        elif top_c > sec_c:
            confidence = "medium"                             # somewhat more complete
        elif top_docs > sec_docs:
            confidence = "medium"                             # equally complete, more docs agree
        else:
            confidence = "low"                                # genuine tie — no clear winner

    # A value found ONLY by the raw-text safety net (never LLM-extracted) is less
    # certain: never let text-scan-only evidence reach an auto-preselect HIGH.
    top_sources = top.get("sources") or []
    if confidence == "high" and top_sources and all(s.get("source_method") == "text_scan" for s in top_sources):
        confidence = "medium"

    # A GENUINE TIE GETS NO SUGGESTION (client-facing decision, 2026-08-17).
    # "low" means nothing separates the candidates: equal completeness, equal
    # document support. Probe run A showed every candidate appearing once at
    # the same confidence, and the merge's own winner was the first value twice
    # and the second value three times - no pattern, i.e. a coin flip. Badging
    # a coin flip as "Suggested" on a legal value is worse than saying nothing,
    # and C23 in improving-ll.md is the standing precedent: frequency ranking
    # once picked an UMBRELLA limit as the GL limit. The row still renders and
    # the producer still chooses - we just stop pretending we know.
    if confidence == "low":
        return None

    preselect = (confidence == "high") and (fact_key not in HARD_STOP_RECONCILABLE_KEYS)
    return {
        "value":      top.get("display"),
        "normalized": top.get("normalized"),
        "confidence": confidence,
        "preselect":  preselect,
    }


# ── Full-field reconciliation helpers (generic all-scalar-field picker) ───────

def _full_field_enabled() -> bool:
    """Whether generic all-field reconciliation is enabled (settings flag).

    Lazy import keeps this module import-pure (it otherwise imports only the
    normalization layer) and unit-testable in isolation. Default False -> only
    the curated RECONCILABLE_FIELDS are reconciled, exactly as before.
    """
    try:
        from config.settings import ENABLE_FULL_FIELD_RECONCILIATION
        return bool(ENABLE_FULL_FIELD_RECONCILIATION)
    except Exception:
        return False


def _humanize(fact_key: str) -> str:
    """Readable label for an auto-discovered fact key
    ('gl_each_occurrence_limit' -> 'Gl Each Occurrence Limit')."""
    return fact_key.replace("_", " ").strip().title() or fact_key


def _drop_declared_trade_names(fact_key: str, values: List[dict],
                               docs: List[dict]) -> List[dict]:
    """Remove candidates that are the insured's own DECLARED trade name.

    BRENT RULING 2026-08-24 (Q3a) - enforced here after the S6 live run
    (2026-08-25) showed a package asserting BOTH "Matched on: dba name, fein,
    policy number" AND an applicant-name hard stop, from two different engines.
    A loss run issued to the DBA the applicant declared is the same insured,
    not a rival answer.

    The rule itself lives in ``fact_comparison.is_declared_trade_name`` so this
    is not a second copy of it. Fail-open, and never returns an empty list.
    """
    if fact_key != "applicant_name" or len(values) < 2:
        return values
    try:
        from services.fact_comparison import is_declared_trade_name
        kept = [g for g in values
                if not is_declared_trade_name(g.get("display"), docs)]
        if kept and len(kept) < len(values):
            logger.info(
                "underwriting: %s - dropped %d candidate(s) that are the "
                "applicant's own declared trade name, not a rival identity",
                fact_key, len(values) - len(kept))
            return kept
        return values
    except Exception as exc:                                  # noqa: BLE001
        logger.warning(
            "underwriting: trade-name filter failed for %s - %s", fact_key, exc)
        return values


def _drop_foreign_line_values(fact_key: str, values: List[dict]) -> List[dict]:
    """Remove candidates that name a DIFFERENT coverage line than this fact.

    See ``fact_equivalence.names_a_foreign_line`` for the rule and its
    positive-evidence guards. Fail-open, and never returns an empty list.
    """
    if len(values) < 2:
        return values
    try:
        from services.fact_comparison import _fe as _door
        names_a_foreign_line = _door.names_a_foreign_line
        kept = [g for g in values
                if not names_a_foreign_line(fact_key, g.get("display"))]
        if kept and len(kept) < len(values):
            logger.info(
                "underwriting: %s - dropped %d candidate(s) naming another "
                "line of business; they are mis-extractions, not rival answers",
                fact_key, len(values) - len(kept))
            return kept
        return values
    except Exception as exc:                                  # noqa: BLE001
        logger.warning(
            "underwriting: foreign-line filter failed for %s - %s", fact_key, exc)
        return values


def _class_exposure_amounts(merged_facts: Optional[dict]) -> set:
    """Every per-class rating basis the package's own schedules state.

    Columns are SCHEMA-DERIVED, not hand-typed: `extraction_service.
    _CLASS_EXPOSURE_COLUMNS` is a class-code schedule's field name (the schema
    names both `gl_class_code_schedule` and `wc_class_codes` for exactly this
    reason) plus whichever of ITS columns are money-shaped. A future class
    schedule with a money column is picked up automatically; nothing outside
    a class schedule ever is - see that constant's own docstring in
    extraction_service.py for the false positives a looser scan produced
    (the primary declarations-index list, a line's own premium,
    `property_locations`, `inland_marine_items`) and why each was excluded.
    """
    out: set = set()
    if not isinstance(merged_facts, dict):
        return out
    try:
        from services.extraction_service import _CLASS_EXPOSURE_COLUMNS
    except Exception:                                         # noqa: BLE001
        return out
    for list_key, columns in _CLASS_EXPOSURE_COLUMNS.items():
        rows = merged_facts.get(list_key)
        if isinstance(rows, dict) and "value" in rows:
            rows = rows["value"]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for col in columns:
                norm = _normalize_currency(row.get(col))
                if norm:
                    out.add(norm)
    return out


def _drop_class_exposure_candidates(fact_key: str, values: List[dict],
                                    merged_facts: Optional[dict]) -> List[dict]:
    """A per-CLASS rating basis is not a rival to the package TOTAL.

    LIVE RUN A: the picker asked the producer to choose between `$1,880,000`
    Total Annual Payroll and `$285,000` / `$640,000` / `$95,000` - the payroll
    bases for GL classes 91580, 98305 and 91340 out of the package's own
    SCHEDULE OF HAZARDS. They are not rival totals; they do not even sum to one.

    THE SOURCE IS THE TEXT SCAN, not extraction. `_text_scan_values` looks for
    a "payroll" label followed by an amount, and a hazard schedule prints that
    phrase once per class. Measured on the live document: the scan returns all
    four amounts for `total_payroll`.

    TWO GUARDS, and both are needed:
      1. **Positive evidence.** The amount must literally appear as an
         `exposure_amount` / `payroll` on one of THIS package's class schedule
         rows. No schedule, no opinion.
      2. **Text-scan-only.** A candidate any document's EXTRACTION produced as
         this fact survives untouched. The extractor naming it `total_payroll`
         is independent evidence, and a single-class business can legitimately
         have a total equal to its one class basis.

    Never empties the list, and never raises.
    """
    if len(values) < 2:
        return values
    try:
        exposures = _class_exposure_amounts(merged_facts)
        if not exposures:
            return values
        kept = []
        for g in values:
            srcs = g.get("sources") or []
            scan_only = bool(srcs) and all(
                s.get("source_method") == "text_scan" for s in srcs)
            norm = _normalize_currency(g.get("display"))
            if scan_only and norm and norm in exposures:
                continue
            kept.append(g)
        if kept and len(kept) < len(values):
            logger.info(
                "underwriting: %s - dropped %d candidate(s) that this package's "
                "own class schedule states as a PER-CLASS rating basis, not a "
                "package total", fact_key, len(values) - len(kept))
            return kept
        return values
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: class-exposure filter failed for %s - %s",
                       fact_key, exc)
        return values


def _declared_domain_check(fact_key: str):
    """The fact's own definition of a legal value, or None when it has none.

    Two declarations already exist in this codebase and neither was ever read
    on this path: `FACT_REGISTRY[key]["validate"]` and the closed option list in
    `answer_options`. A fact with neither keeps today's behaviour exactly.
    """
    # A CLOSED LIST ONLY - deliberately NOT the registry validator.
    #
    # The live suite settled this (11 Sep). Reading `FACT_REGISTRY["validate"]`
    # as a domain fights a shipped design: SYS-07 / SYS-07c exist precisely
    # because documents express Yes/No in OPEN vocabulary - "Underwritten",
    # "X", a tick, "Incl." - and the lexicon learns those words instead of the
    # system deciding. Applying a boolean validator here deleted the very cards
    # that module raises, and `is_renewal` "Renewal of BBC7263 - 25" is the same
    # shape: the DOCUMENT'S way of saying yes, which belongs to normalisation,
    # not to this filter.
    #
    # An `answer_options` list is a different thing - a closed set someone
    # declared, with "Other" as its escape hatch. That is a real domain, and it
    # is what the client's example needs: `gl_form_type` is Occurrence or
    # Claims-Made, and a coverage-form NAME is neither.
    checks = []
    try:
        from services.answer_options import options_for, option_named_by
        # The document's own caption for an option ("OCCUR") names it - see
        # `option_named_by`. Exact match alone judged the certificate's correct
        # answer illegal, so a form number could never be dropped against it.
        if any(str(o).strip().lower() != "other"
               for o in (options_for(fact_key) or [])):
            checks.append(
                lambda v, _k=fact_key: option_named_by(_k, v) is not None)
    except Exception:                                         # noqa: BLE001
        pass
    if not checks:
        return None

    def _legal(value) -> bool:
        text = str(value or "").strip()
        if not text:
            return True                    # emptiness is not this rule's business
        for fn in checks:
            try:
                if fn(text):
                    return True
            except Exception:                                 # noqa: BLE001
                return True                # a validator that throws decides nothing
        return False
    return _legal


def _drop_values_outside_declared_domain(fact_key: str,
                                         values: List[dict]) -> List[dict]:
    """Candidates that cannot be a legal value for this field are not rivals.

    Client 2026-09-11 items 5 and 10: *"There are also SQS comparisons that
    should never happen - for example, comparing a $2M limit to a Per
    Location/Per Project yes/no field, or comparing a Claims Made indicator to
    the words 'Commercial Liability Umbrella Coverage Form'. Values should only
    be compared when they represent the same field."*

    ROOT CAUSE: every scalar fact not curated in `RECONCILABLE_FIELDS` is
    auto-registered as `identity` kind and compared as raw text, so whatever a
    document happened to put in a fact became a candidate answer for it. The
    fact's own domain was never consulted - `gl_form_type`'s validator accepts
    only "occurrence" / "claims-made" and would have refused a coverage-form
    name on sight.

    NEVER EMPTIES THE FIELD. If every candidate is illegal we have no basis to
    prefer one, so all are kept and the row renders exactly as it does today -
    the same rule `_drop_foreign_line_values` and `_partition_by_shape` use.
    Dropping is only ever the removal of a false rival.
    """
    legal = _declared_domain_check(fact_key)
    if legal is None or len(values) < 2:
        return values

    def _printings(group) -> List[str]:
        """Every way this candidate was printed.

        A GROUP, NOT A VALUE - and reading it as `group["value"]` is what made
        the first version of this function inert in production while every unit
        test passed (live run 11 Sep). The loop above builds
        `{normalized, display, sources: [{raw, ...}]}`; there is no `value` key,
        so the check received None for every candidate and let everything
        through. D22: the fixture was easier than reality.

        A candidate is legal if ANY of its printings is legal - one OCR-damaged
        source must not condemn a value the other documents print correctly.
        """
        out = [group.get("display"), group.get("normalized"), group.get("value")]
        for src in (group.get("sources") or []):
            if isinstance(src, dict):
                out.append(src.get("raw"))
        return [str(x) for x in out if str(x or "").strip()]

    def _asserts_something(text: str) -> bool:
        """Does this printing ASSERT a value, or is it an absence / non-answer?

        THE SECOND CONDITION, and the live suite found it missing (11 Sep): the
        first version dropped "N/A", "TBD", "Unknown" and "Not Applicable" from
        a boolean field because no validator accepts them - silently deleting
        the very card SYS-07c exists to raise. A non-answer is not a wrong
        answer; it is the producer's question, and hiding it is the unsafe
        direction.

        `answer_semantics` is the one door for exactly this split - "what is the
        value?" versus "did they answer?" - so it is asked rather than
        re-implemented. An absence yields an empty value; a real assertion does
        not. Unavailable door -> assume it asserts, i.e. today's behaviour.
        """
        try:
            from services.answer_semantics import interpret_answer
            interp = interpret_answer(fact_key, text)
            return bool(str(getattr(interp, "value", "") or "").strip())
        except Exception:                                     # noqa: BLE001
            return True

    keep = []
    for v in values:
        printings = _printings(v)
        if not printings:
            keep.append(v)
            continue
        if any(legal(p) for p in printings):
            keep.append(v)
            continue
        if not any(_asserts_something(p) for p in printings):
            keep.append(v)                 # an absence, not a wrong value

    if not keep:
        return values
    # TWO PRINTINGS OF ONE OPTION ARE ONE ANSWER. Once the certificate's
    # caption "OCCUR" is legal it must not become a rival to a declarations
    # page's "Occurrence" - the same choice, printed two ways. Merge-only:
    # groups fold together only when the fact's own closed list says they
    # name the SAME option, so this can never manufacture a disagreement.
    try:
        from services.answer_options import option_named_by
    except Exception:                                         # noqa: BLE001
        option_named_by = None                                # type: ignore
    folded: List[dict] = []
    by_option: Dict[str, dict] = {}
    for v in keep:
        named = ({option_named_by(fact_key, p) for p in _printings(v)} - {None}
                 if option_named_by else set())
        if len(named) != 1:
            folded.append(v)
            continue
        option = next(iter(named))
        keeper = by_option.get(option)
        if keeper is None:
            keeper = dict(v)
            keeper["sources"] = list(v.get("sources") or [])
            by_option[option] = keeper
            folded.append(keeper)
            continue
        keeper["sources"].extend(v.get("sources") or [])
        # The fuller printing reads better than a caption.
        if len(str(v.get("display") or "")) > len(str(keeper.get("display") or "")):
            keeper["display"] = v.get("display")
            keeper["normalized"] = v.get("normalized")
    if len(folded) == len(values):
        return values
    dropped = [str(v.get("display") or v.get("normalized"))[:40]
               for v in values if v not in keep]
    if dropped:
        logger.info(
            "underwriting: %s - %d candidate(s) are not a legal value for this "
            "field and are not rival answers: %s",
            fact_key, len(dropped), "; ".join(dropped[:3]))
    if len(folded) < len(keep):
        logger.info(
            "underwriting: %s - %d printing(s) of one option folded into one "
            "answer", fact_key, len(keep) - len(folded))
    return folded


def _merge_equivalent_value_groups(fact_key: str, values: List[dict],
                                   context=None) -> List[dict]:
    """Collapse value groups that are the SAME underlying fact.

    Pure list-in / list-out around ``fact_equivalence.equivalent_index``. The
    surviving group keeps every source from the groups folded into it, so
    attribution ("from X, from Y") is never lost - only the QUESTION goes away.
    The display value is chosen by the equivalence layer's own preference rule
    (bare for an amount, fuller for an identifier), NOT by raw string length.

    Fail-open: any problem returns the input untouched.
    """
    if len(values) < 2:
        return values
    try:
        from services.fact_comparison import _fe as _door
        mapping = _door.equivalent_index(
            fact_key, [g.get("display") for g in values], context)
        if not mapping:
            return values
        out: List[dict] = []
        for i, g in enumerate(values):
            if i in mapping:
                continue
            keeper = dict(g)
            keeper["sources"] = list(g.get("sources") or [])
            for j, k in mapping.items():
                if k == i:
                    keeper["sources"].extend(values[j].get("sources") or [])
            out.append(keeper)
        logger.info(
            "underwriting: %s - %d value group(s) folded as the same fact "
            "(%d remain); no question is asked about formatting",
            fact_key, len(values) - len(out), len(out))
        return out or values
    except Exception as exc:                                  # noqa: BLE001
        logger.warning(
            "underwriting: equivalence filter failed for %s - %s", fact_key, exc)
        return values


# Facts that carry ONE value per policy on a multi-policy package. Package-
# level identity (applicant, FEIN, addresses) is deliberately absent - one
# insured however many policies (client 1.2).
#
# EVERY MEMBER IS AN IDENTIFIER, A NAME OR A DATE. Money is deliberately
# excluded and that is not fussiness: `PackageContext.value_owner` keys on the
# value's own characters, so two facts that happen to share an AMOUNT share an
# owner. Live run 2026-08-21 proved the damage - the certificate's umbrella
# $1,000,000 inherited the GL policy's ownership purely because the dec page
# prints $1,000,000 as the GL Each Occurrence limit, and the $3M-vs-$1M
# umbrella conflict (the one the client praised) was scoped into silence.
# Identifiers, carrier names and dates do not collide that way; amounts do.
def _is_form_number_policy_value(fact_key: Any, value: Any) -> bool:
    """True when a POLICY-NUMBER fact holds an ISO/AAIS FORM number.

    Orbin, 14 Sep 2026: the card's only two "Policy Number" candidates were
    `IM 7100 06 04` and `IM 7201 10 02` - AAIS page footers - and the producer
    was made to pick one. A form number names coverage WORDING; it is never a
    contract, so it is never offered, confirmed or applied. One shape test, the
    extraction layer's own.
    """
    key = str(fact_key or "").strip().lower()
    if not (key == "policy_number" or key.endswith("_policy_number")):
        return False
    try:
        from services.extraction_service import _looks_like_a_form_number
    except Exception:                                         # noqa: BLE001
        return False
    return isinstance(value, str) and _looks_like_a_form_number(value)


def usable_confirmations(confirmations: Optional[dict]) -> dict:
    """The stored confirmations that may still be read as an answer.

    Orbin e7084347 (10 Sep 2026): the card offered only the AAIS form numbers
    `IM 7100 06 04` / `IM 7201 10 02` as policy-number candidates, and the
    producer confirmed one. `apply_confirmations` stopped applying such a value
    on 14 Sep, but every OTHER reader still took it at face value: the card
    kept rendering it as the confirmed answer, the conflict-key lists counted
    the field as resolved, and Field QA used it as the "source value" for the
    policy-number box on four forms - the client's "policy number vs form
    number" rows. One door, so no reader can disagree with another.

    The stored confirmation is NOT deleted: it is the record of what the
    producer clicked. It is only never read as an answer.
    """
    if not confirmations:
        return {}
    return {k: v for k, v in confirmations.items()
            if not _is_form_number_policy_value(parse_confirmation_key(k)[0], v)}


# ── A FORM REFERENCE IS NOT A POLICY NUMBER, EVEN A CARRIER'S OWN ────────────
# `_is_form_number_policy_value` reads the ISO/AAIS shape only. A carrier prints
# its OWN forms with the same edition-date tail - this very package prints
# `CU7001A(11/15)`, `IL 71 31A 04 01`, `CG 70 01A 10 12` - and every one of them
# passes that test as a POLICY number (measured 14 Sep). So on the card a
# candidate is set aside only when BOTH hold, never on either alone:
#   * it is shaped like a form reference: letters, a form series, an MM YY
#     edition at the end; AND
#   * no contract the package's VERIFIED declarations index prints matches it.
# The second condition is what keeps a real second carrier's policy - one only
# a certificate prints, `GL-4471102-26` beside EMC's `BBC7263-26` (defect D-1) -
# on the card. It never empties the field and never acts without an index.
# A form series never runs five digits together (`CU7001A`, `IL 71 31A`,
# `IM 7100`); a policy number usually does. Without that condition a real
# `BOP 7654321 01 26` read as a form reference (14 Sep break-it pass).
_FORM_REFERENCE_RE = re.compile(
    r"^(?!.*\d{5})[A-Za-z]{2,3}\s?\d[\w.\s-]*?[\s(](?:0[1-9]|1[0-2])[\s/-]\d{2}\)?$")


def _verified_contracts(merged_facts: Optional[dict],
                        docs: Optional[List[dict]]) -> List[str]:
    """Policy numbers the verified declarations index prints - merged and per
    document (the per-document copies survive the post-generation purge)."""
    try:
        from services.extraction_service import _looks_like_a_policy_number
    except Exception:                                         # noqa: BLE001
        return []
    out: List[str] = []
    sources = [merged_facts or {}] + [
        (d.get("facts") or {}) for d in (docs or []) if isinstance(d, dict)]
    for src in sources:
        entries = src.get("dec_page_entries") if isinstance(src, dict) else None
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            pn = str(e.get("policy_number") or "").strip()
            if pn and _looks_like_a_policy_number(pn) and pn not in out:
                out.append(pn)
    return out


def _drop_unknown_form_references(fact_key: str, values: List[dict],
                                  merged_facts: Optional[dict],
                                  docs: Optional[List[dict]]) -> List[dict]:
    """Policy-number candidates that are form references no verified contract
    names are not rival answers. See `_FORM_REFERENCE_RE` for both conditions."""
    try:
        from services.normalization import is_policy_number_field
        if not is_policy_number_field(fact_key) or len(values) < 2:
            return values
        contracts = _verified_contracts(merged_facts, docs)
        if not contracts:
            return values
        from services.fact_comparison import identifiers_match, same_policy_contract

        def _printings(g):
            raw = [g.get("display")] + [s.get("raw") for s in (g.get("sources") or [])]
            return [str(x) for x in raw if str(x or "").strip()]

        def _known(p):
            return any(identifiers_match(p, c) or same_policy_contract(p, c)
                       for c in contracts)

        keep = [g for g in values
                if any(_known(p) or not _FORM_REFERENCE_RE.match(p.strip())
                       for p in _printings(g))]
        if not keep or len(keep) == len(values):
            return values
        if not any(_known(p) for g in keep for p in _printings(g)):
            return values             # nothing proven to prefer - ask as today
        logger.info(
            "underwriting: %s - %d form reference(s) no verified contract names "
            "set aside: %s", fact_key, len(values) - len(keep),
            "; ".join(str(g.get("display"))[:30] for g in values if g not in keep))
        return keep
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: form-reference filter failed for %s - %s",
                       fact_key, exc)
        return values


def _dated_change_for_field(fact_key: str, values: List[dict],
                            docs: Optional[List[dict]],
                            merged_facts: Optional[dict],
                            statements: Optional[List[dict]]) -> Optional[dict]:
    """The documents' own dated change for this card, or None.

    The rule is `fact_comparison.dated_change` - the comparison door's time
    axis - so the merge (which stamps the current value) and this card cannot
    disagree about whether $3,000,000 -> $1,000,000 is a change or a conflict.
    This only reads the card's value groups into that rule's shape. A text-scan
    source is not a printing of the fact: in the document that states a change,
    it is the change sentence itself.
    """
    if len(values) != 2 or not statements:
        return None
    try:
        from services.fact_comparison import dated_change, document_as_of, fact_term
        docs = list(docs or [])
        index = {str(d.get("doc_id") or i): i for i, d in enumerate(docs)}
        printings = []
        for g in values:
            for s in g.get("sources") or []:
                if s.get("source_method") == "text_scan":
                    continue
                di = index.get(str(s.get("doc_id")))
                if di is None:
                    continue
                printings.append((s.get("raw"), document_as_of(docs[di], fact_key), di))
        verdict = dated_change(fact_key, printings, statements,
                               fact_term(fact_key, merged_facts))
        if verdict:
            verdict["document"] = docs[verdict["source_doc_index"]].get("filename")
            verdict["prior_documents"] = [
                docs[i].get("filename") for i in verdict.get("prior_doc_indices") or []]
        return verdict
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: dated-change check failed for %s - %s",
                       fact_key, exc)
        return None


LINE_SCOPED_FACT_KEYS = frozenset({
    "policy_number", "carrier_name", "carrier_naic", "effective_date",
    "expiration_date",
})

# Which column of a `coverage_lines` row states each of those facts. A
# declarations page for a package prints these PER COVERAGE PART, not once, so
# the per-line value is often the ONLY place the fact exists (D-1 Layer 1). The
# key set above is deliberately reused: a fact may only be raised per line if it
# is a fact that legitimately has one value per line.
_LINE_SCOPED_FACT_COLUMN: Dict[str, str] = {
    "policy_number":   "policy_number",
    "carrier_name":    "carrier",
    "carrier_naic":    "naic",
    "effective_date":  "effective_date",
    "expiration_date": "expiration_date",
}
assert set(_LINE_SCOPED_FACT_COLUMN) == set(LINE_SCOPED_FACT_KEYS), (
    "every line-scoped fact needs a coverage_lines column, and vice versa")

_SINGLE_LINE_CACHE: Optional[frozenset] = None


def _facts_pinned_to_one_line() -> frozenset:
    """Facts that belong to exactly ONE coverage line, by definition.

    These must NEVER be scoped across policies - `umbrella_limit` is the
    umbrella's limit and nothing else, so two different values for it are a
    real disagreement, not two policies' worth of legitimate difference.

    THIS IS THE INVERSE OF WHAT THE FIRST CUT DID. C1-C treated "the registry
    can place this fact on a line" as a reason to ALLOW scoping. It is a reason
    to FORBID it: a fact the registry can place already has its one scope.
    Getting this backwards silenced the client's umbrella conflict on the first
    live run (v1-20AUG C1-H).
    """
    global _SINGLE_LINE_CACHE
    if _SINGLE_LINE_CACHE is None:
        keys = set()
        try:
            from services.fact_registry import FACT_REGISTRY
            from services.fact_comparison import _fe as _door
            for k in FACT_REGISTRY:
                if _door.fact_line(k):
                    keys.add(k)
        except Exception:                                     # noqa: BLE001
            pass
        _SINGLE_LINE_CACHE = frozenset(keys)
    return _SINGLE_LINE_CACHE


def _scope_by_item(fact_key: str, values: List[dict], context) -> bool:
    """Client 1.2's LOCATION / VEHICLE / PROPERTY / ITEM scope.

    Two buildings legitimately have two years built; two vehicles legitimately
    have two costs new. Before this, every column where a package's own
    schedule rows differ raised a Data Consistency question, because the
    picker's only scope axis was the POLICY.

    Both of the context's gates must hold (see `PackageContext._build_item_index`
    for why each exists):
      1. the fact key is literally a column in one of this package's schedules,
         so the package's own data proves it varies per item;
      2. every value group maps to a NON-EMPTY set of rows and no two groups
         share one.

    A value that appears in no row at all fails gate 2, so a genuine
    cross-document disagreement about ONE item still surfaces - only values
    each attributable to a different row are separated. Returns False on
    anything it cannot prove, which is today's behaviour.
    """
    if context is None or len(values) < 2:
        return False
    try:
        if not context.is_item_scoped_fact(fact_key):
            return False
        items: List[set] = []
        for g in values:
            got: set = set(context.items_of(g.get("display")))
            for src in g.get("sources") or []:
                got |= set(context.items_of(src.get("raw")))
            items.append(got)
        if not all(items):
            return False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[i] & items[j]:
                    return False
        for g, own in zip(values, items):
            g["scope"] = sorted(own)
        logger.info(
            "underwriting: %s - %d value(s) retained under their own item "
            "scope (%s); different things, not a disagreement",
            fact_key, len(values),
            ", ".join(sorted({i for s_ in items for i in s_})[:4]))
        return True
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: item scope check failed for %s - %s",
                       fact_key, exc)
        return False


def _printings_by_line(fact_key: str, docs: Optional[List[dict]]) -> Dict[str, set]:
    """``{canonical line: {every printing any document states for it}}``.

    Read from each document's OWN `coverage_lines`, not the merged list, so it
    survives a line-scoped confirmation having already rewritten the merged
    row - which is exactly when it is needed.
    """
    out: Dict[str, set] = {}
    column = _LINE_SCOPED_FACT_COLUMN.get(fact_key)
    if not column:
        return out
    try:
        from services.extraction_service import _canon_line
    except Exception:                                         # noqa: BLE001
        return out
    for d in docs or []:
        for row in (_fv(d.get("facts") or {}, "coverage_lines") or []):
            if not isinstance(row, dict):
                continue
            canon = _canon_line(row.get("line"))
            val = str(row.get(column) or "").strip()
            if canon and val:
                out.setdefault(canon, set()).add(val)
    return out


def _drop_answered_line_candidates(
        fact_key: str, values: List[dict], scoped_conf: Dict[str, str],
        docs: Optional[List[dict]]) -> List[dict]:
    """Remove candidates the producer has already ruled out FOR THEIR LINE.

    SYS-06 / D-W. A line-scoped confirmation rewrites that line's row in
    `coverage_lines`, but the picker's candidates also come from each
    DOCUMENT's own facts - so without this the rejected value comes straight
    back and the producer is asked the same question forever.

    Narrow on purpose. A candidate is dropped only when it is stated on a line
    the producer has answered AND it disagrees with their answer AND it is
    stated on no OTHER line. A value that also belongs to an unanswered line is
    still that line's value and is never removed on another line's behalf.
    """
    if not scoped_conf or len(values) < 2:
        return values
    by_line = _printings_by_line(fact_key, docs)
    if not by_line:
        return values
    kept: List[dict] = []
    for g in values:
        printings = [g.get("display")] + [
            s.get("raw") for s in (g.get("sources") or [])]
        on_lines = {ln for ln, vals in by_line.items()
                    if any(p and any(_door_values_agree(fact_key, p, v) for v in vals)
                           for p in printings)}
        answered = {ln for ln in on_lines if ln in scoped_conf}
        if answered and answered == on_lines and not any(
                p and _door_values_agree(fact_key, p, scoped_conf[ln])
                for ln in answered for p in printings):
            logger.info(
                "underwriting: %s - dropping %r; the producer confirmed %r for "
                "%s", fact_key, g.get("display"),
                scoped_conf[sorted(answered)[0]], ", ".join(sorted(answered)))
            continue
        kept.append(g)
    return kept or values


def _restrict_to_conflicted_lines(
        fact_key: str, values: List[dict], collided: set,
        docs: Optional[List[dict]]) -> List[dict]:
    """Offer only the values that are actually stated on the disputed line(s).

    LIVE RUN B, 2026-09-04. A package with two General Liability policies and
    one clean Auto line asked *"two policies on the same coverage line (general
    liab) - confirm which applies"* and then listed THREE policy numbers,
    including the AUTO one - under a button reading **Confirm for general
    liab**. Picking it would have written the Auto policy number onto the
    General Liability line: the exact mis-assignment this whole item exists to
    prevent, offered as a one-click option.

    The client's criterion is *"compare values only within the same line/policy
    context"*. A value belonging to another line is not in this question's
    context and must not be a candidate for it.

    Nothing is hidden: every value still appears in "Policies in this
    submission" against its own line. Refuses to act unless at least two
    candidates survive, so it can never turn a real conflict into a silent
    single value.
    """
    if not collided or len(values) < 2:
        return values
    try:
        by_line = _printings_by_line(fact_key, docs)
        if not by_line:
            return values
        wanted: set = set()
        for ln in collided:
            wanted |= set(by_line.get(ln) or ())
        if not wanted:
            return values
        kept = [
            g for g in values
            if any(p and any(_door_values_agree(fact_key, p, w) for w in wanted)
                   for p in [g.get("display")] + [s.get("raw") for s in (g.get("sources") or [])])
        ]
        if len(kept) < 2 or len(kept) == len(values):
            return values
        logger.info(
            "underwriting: %s - %d candidate(s) dropped from the %s question; "
            "they belong to another coverage line",
            fact_key, len(values) - len(kept), ", ".join(sorted(collided)))
        return kept
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: line restriction failed for %s - %s",
                       fact_key, exc)
        return values


def _composite_children(fact_key: str) -> List[str]:
    """The scalar facts a composite display fact renders, or [].

    Read from `extraction_service._CURRENCY_COMPOSITE_PARENT` - the table that
    already declares this relationship for the merge's own reconciliation, so
    "which facts is this a rendering of?" keeps ONE owner.
    """
    try:
        from services.extraction_service import _CURRENCY_COMPOSITE_CHILDREN
        return list(_CURRENCY_COMPOSITE_CHILDREN.get(fact_key) or [])
    except Exception:                                         # noqa: BLE001
        return []


def _composite_is_reconciled_by_its_children(
        fact_key: str, effective_fields: dict,
        docs: Optional[List[dict]]) -> bool:
    """True when this fact is a COMPOSITE whose children this picker assesses.

    Both halves are required. Being a composite is not enough: on a package
    that states the block and none of its parts, the composite is the only
    evidence there is and suppressing it would hide a real disagreement.
    """
    children = _composite_children(fact_key)
    if not children:
        return False
    for child in children:
        if child not in effective_fields:
            continue
        for d in docs or []:
            val = _fv(d.get("facts") or {}, child)
            if val is not None and str(val).strip():
                return True
    return False


def _line_records(merged_facts: Optional[dict]) -> List[dict]:
    """The package's (line, contract) records, or []. See
    ``extraction_service._build_line_records`` - built at merge, read here.

    A record with nothing but a line name is not a policy (live run 7, 15 Sep
    2026: the common dec's "No Coverage" rows listed as three policies). The
    build drops them; this read drops them from sessions stored before that."""
    recs = (merged_facts or {}).get("_line_records")
    if not isinstance(recs, list):
        return []
    try:
        from services.extraction_service import policy_line_records
    except Exception:                                         # noqa: BLE001
        return [r for r in recs if isinstance(r, dict)]
    return policy_line_records(recs)


def _store_entries(fact_key: str, merged_facts: Optional[dict]) -> List[dict]:
    """The stored scope entries for ``fact_key``, deriving them when absent.

    A STORE THAT COVERS ONLY SOME OF THE CHAIN IS A HALF-SCOPED PACKAGE, and
    that is not a hypothetical: `carrier_naic` was invisible to the picker
    before SYS-06 (nothing wrote it as a scalar, so auto-discovery never saw
    it). Curating it made a legitimately three-carrier package report a NAIC
    conflict, purely because the session's store predated the key - the DATA
    said one NAIC per line the whole time.

    So when the store cannot speak for a fact, the records are rebuilt from
    `coverage_lines`, which is where the relationship lives anyway. Pure
    gap-filling: a stored entry is always preferred, so nothing that scopes
    today can start scoping differently.
    """
    stored = ((merged_facts or {}).get("_scoped") or {}).get(fact_key)
    if stored:
        return [e for e in stored if isinstance(e, dict)]
    if fact_key not in _LINE_SCOPED_FACT_COLUMN:
        return []
    try:
        from services.extraction_service import _build_line_records
        recs = _line_records(merged_facts) or _build_line_records(merged_facts or {})
        out: List[dict] = []
        for rec in recs:
            for val in (rec.get("printings") or {}).get(fact_key, []):
                out.append({"value": val, "scope": {
                    "line": rec.get("line"),
                    "line_printed": rec.get("line_printed"),
                    "policy_number": rec.get("policy_number"),
                    "record": rec.get("id"),
                }})
        if out:
            logger.info(
                "underwriting: %s - scope derived from %d line record(s); the "
                "stored scope predates this fact", fact_key, len(recs))
        return out
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: could not derive scope for %s - %s",
                       fact_key, exc)
        return []


def _line_records_for(fact_key: str, merged_facts: Optional[dict]) -> List[dict]:
    """The client's chain, for the rows that state THIS fact.

        Line of Business -> Carrier -> NAIC -> Policy Number
                         -> Effective Date -> Expiration Date -> Source

    Emitted on a line-scoped field so the producer can see the mapping rather
    than infer it from a list of values, and so the E&O export carries the
    relationship rather than a flat set of scalars. Read-only projection of
    the store; contains no decision.
    """
    if fact_key not in LINE_SCOPED_FACT_KEYS:
        return []
    out: List[dict] = []
    for rec in _line_records(merged_facts):
        out.append({
            "line":            rec.get("line"),
            "line_printed":    rec.get("line_printed"),
            "carrier_name":    rec.get("carrier_name"),
            "carrier_naic":    rec.get("carrier_naic"),
            "policy_number":   rec.get("policy_number"),
            "effective_date":  rec.get("effective_date"),
            "expiration_date": rec.get("expiration_date"),
            "sources":         list(rec.get("sources") or []),
        })
    return out


def _scope_of_group(fact_key: str, group: dict, store: List[dict]) -> tuple:
    """``(record_ids, lines)`` this value group is stated on.

    THE TWO SETS ARE NOT INTERCHANGEABLE, and conflating them silently folded
    two real carriers on one line into a single candidate (caught by
    `test_two_carriers_on_the_SAME_line_is_still_a_conflict`, which builds the
    pre-SYS-06 store shape by hand).

      * ``lines``   - always available, including on a legacy store.
      * ``record_ids`` - ONLY from an entry that actually carries one. A store
        written before SYS-06 has no record ids, and absence is not evidence
        that two values share a contract (Principle 3). A group with no record
        id can therefore never be merged, and the legacy behaviour stands.
    """
    printings = [group.get("display")] + [
        s.get("raw") for s in (group.get("sources") or [])]
    records: set = set()
    lines: set = set()
    for rec in store or []:
        if not isinstance(rec, dict):
            continue
        if any(p and _door_values_agree(fact_key, p, rec.get("value"))
               for p in printings):
            scope = rec.get("scope") or {}
            ln = scope.get("line")
            if ln:
                lines.add(ln)
            rid = scope.get("record")
            if rid:
                records.add(rid)
    return records, lines


def _merge_by_line_record(fact_key: str, values: List[dict],
                          merged_facts: Optional[dict]) -> List[dict]:
    """Fold groups the LINE RECORD store proves are ONE contract's one fact.

    SYS-06. The pure value comparator deliberately refuses to merge
    ``BBC7263`` into ``BBC7263 - 26``: proving they are one contract needs the
    package, and `fact_equivalence`'s identifier branch says so in as many
    words. The package is exactly what the line-record store holds, so the
    proof happens here instead of loosening the pure test.

    THE AMBIGUITY GUARD, same shape as `equivalent_index`'s: the two groups'
    record sets must be EQUAL and non-empty. Overlapping-but-different sets are
    not proof - they are a value that cannot be placed, and it stays put.

    Only ever MERGES, so it cannot manufacture a conflict; any failure returns
    the input untouched.
    """
    if len(values) < 2 or fact_key not in LINE_SCOPED_FACT_KEYS:
        return values
    try:
        store = _store_entries(fact_key, merged_facts)
        if not store:
            return values
        keys = [frozenset(_scope_of_group(fact_key, g, store)[0]) for g in values]
        out: List[dict] = []
        taken: Dict[frozenset, dict] = {}
        for g, k in zip(values, keys):
            if not k:
                # No record id: a legacy store, or a value the records cannot
                # place. Either way there is no PROOF of a shared contract, so
                # the group stands exactly as it does today.
                out.append(g)
                continue
            keeper = taken.get(k)
            if keeper is None:
                keeper = dict(g)
                keeper["sources"] = list(g.get("sources") or [])
                taken[k] = keeper
                out.append(keeper)
                continue
            # One contract, two printings. Keep the fuller one and every source.
            for s in (g.get("sources") or []):
                if s not in keeper["sources"]:
                    keeper["sources"].append(s)
            if _value_completeness(fact_key, "identity", str(g.get("display"))) > \
                    _value_completeness(fact_key, "identity", str(keeper.get("display"))):
                keeper["display"] = g.get("display")
                keeper["normalized"] = g.get("normalized")
        if len(out) < len(values):
            logger.info(
                "underwriting: %s - %d printing(s) folded into their own "
                "line/policy record (%d remain); one policy printed two ways "
                "is one policy", fact_key, len(values) - len(out), len(out))
        return out or values
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: line-record merge failed for %s - %s",
                       fact_key, exc)
        return values


def _scope_from_store(fact_key: str, values: List[dict],
                      merged_facts: Optional[dict]) -> tuple:
    """(scoped, reason, collided_lines) from the STORED scope, not from spelling.

    C1b / D19. `facts["_scoped"]` carries each line-scoped fact WITH the
    coverage line and policy it belongs to, written once at merge while the
    relationship still existed. Reading it here replaces
    `PackageContext.owners_of`, which attributes a value by its own
    CHARACTERS - the weakness behind B14, G3 and the reverted Pass 1b, where a
    carrier printed `EMC Prop & Cas Co` on one page and `EMC Property &
    Casualty Company` on another lost its scope and became a false conflict.

    THE RULE IS THE CLIENT'S, unchanged (1.2 / 1.5):
      * every surviving group maps to at least one coverage LINE   -> else no opinion
      * no two groups share a line                                 -> SCOPED, retain each
      * two groups on the SAME line                                -> CONFLICT, and say so

    Positive evidence only. A group the store cannot place returns
    ``(False, None)`` and the caller behaves exactly as it did before C1b.
    """
    if len(values) < 2 or not isinstance(merged_facts, dict):
        return False, None, set()
    try:
        store = _store_entries(fact_key, merged_facts)
        if not store:
            return False, None, set()
        # value -> the (line, contract) RECORDS that value is stated on,
        # matched through the ONE comparison door so a spelling variant still
        # finds its scope.
        #
        # ── SYS-06: THE UNIT IS THE RECORD, NOT THE LINE ────────────────────
        # The client's criterion is *"compare values only within the same
        # line/policy context"*. Comparing within the LINE alone was not the
        # same thing, and the difference was the whole defect: the dec page's
        # `BBC7263 - 26` and the certificate's `BBC7263` are ONE General
        # Liability policy printed two ways, so they share a RECORD - but as
        # bare line members they looked like two policies on one line and the
        # field was reported as a conflict on a package where nothing was
        # wrong. Groups that share a record are printings of one contract's one
        # fact; they can never be rivals.
        recs_for: List[set] = []
        lines_for: List[set] = []
        for g in values:
            r, l = _scope_of_group(fact_key, g, store)
            recs_for.append(r)
            lines_for.append(l)
        # ── ONE UNPLACEABLE VALUE MUST NOT UNSCOPE THE WHOLE FIELD ──────────
        # STRESS TEST, 2026-09-04. The all-or-nothing gate that used to live
        # here handed the entire field to `_scope_values`, the LEGACY path that
        # attributes a value by its own CHARACTERS. Two measured consequences on
        # shapes the client's real package actually carried:
        #
        #   * an ISO form number in `coverage_lines` -> the field still reported
        #     "scoped", but every chip printed a POLICY-NUMBER TOKEN instead of
        #     a coverage line ("bbc7263 / bbc726326"), and the form number was
        #     listed as a fifth policy;
        #   * a package-level `policy_number` scalar no line states -> the
        #     equivalence pass then folded four real policies into ONE candidate
        #     and asked the producer to choose between it and a scalar. Confirm
        #     the wrong one and the package scalar becomes the GL box's value -
        #     the client's original complaint, reproduced.
        #
        # So the store's knowledge is used for what it CAN place. A value it
        # cannot place is not evidence against the values it can.
        placed = [i for i, l in enumerate(lines_for) if l]
        if not placed:
            return False, None, set()             # no evidence at all - legacy path
        unplaced = [i for i, l in enumerate(lines_for) if not l]
        collided: set = set()
        for i in placed:
            for j in placed:
                if j <= i:
                    continue
                if recs_for[i] and recs_for[j] and (recs_for[i] & recs_for[j]):
                    # Same contract, two printings - not a disagreement, and
                    # never a reason to refuse the whole field. Requires a
                    # record id on BOTH sides: on a legacy store there is none,
                    # and a shared line then means what it always meant.
                    continue
                collided |= (lines_for[i] & lines_for[j])
        if collided:
            # A genuine second policy on one coverage line (defect D-1, and the
            # client's own review rule). Name the line so the producer knows
            # which one to look at instead of being handed the whole package.
            pretty = ", ".join(sorted(l.replace("_", " ") for l in collided))
            return False, (f"two policies on the same coverage line ({pretty}) "
                           "in one submission - confirm which applies"), collided
        for g, own in zip(values, lines_for):
            g["scope"] = sorted(own)              # [] when the store cannot place it
        if len(unplaced) >= 2:
            # Two or more values competing for a slot nothing can identify is
            # still a real question - but it is a question about THEM, not
            # about the lines the store placed correctly.
            logger.info(
                "underwriting: %s - %d value(s) scoped to their line; %d could "
                "not be placed and remain the question",
                fact_key, len(placed), len(unplaced))
            return False, ("these values could not be matched to a coverage "
                           "line - confirm which applies"), set()
        logger.info(
            "underwriting: %s - %d value(s) retained under their own STORED "
            "line/policy scope (%s)%s; not a conflict", fact_key, len(placed),
            ", ".join(sorted({l for s_ in lines_for for l in s_})),
            f"; {len(unplaced)} shown without a line" if unplaced else "")
        return True, None, set()
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: stored-scope check failed for %s - %s",
                       fact_key, exc)
        return False, None, set()


def _door_values_agree(fact_key: str, a, b) -> bool:
    """Two printings of one value, decided by the one door (D3)."""
    try:
        from services.fact_comparison import values_agree
        return bool(values_agree(fact_key, a, b))
    except Exception:                                         # noqa: BLE001
        return str(a or "").strip().lower() == str(b or "").strip().lower()


def _scope_values(fact_key: str, values: List[dict], context) -> tuple:
    """(scoped: bool, reason: Optional[str]) for the surviving value groups.

    Positive evidence only: every group must be attributed to at least one
    owner (contract or line) by the verified index, owners must be pairwise
    disjoint, and no two owners may resolve to the same coverage line. Any
    failure of those conditions returns (False, reason-or-None) and the
    caller treats the groups exactly as before. Mutates each group to carry
    its ``scope`` (sorted owner tokens) when scoped.
    """
    try:
        if len(values) < 2 or context is None:
            return False, None
        # ITEM axis first (client 1.2), and BEFORE the multi-contract gate.
        # `is_multi_contract` is a precondition of the POLICY axis - it asks
        # whether there are two contracts to tell apart. The item axis asks a
        # different question entirely, and its subject is a package with two
        # BUILDINGS or two VEHICLES, which is completely ordinary on ONE policy.
        # Requiring two contracts here would have made this branch unreachable
        # on exactly the packages it exists for.
        if _scope_by_item(fact_key, values, context):
            return True, None
        if not context.is_multi_contract:
            return False, None
        # Only an explicitly line-scoped fact may scope, and never one the
        # registry pins to a single line (see _facts_pinned_to_one_line).
        if fact_key not in LINE_SCOPED_FACT_KEYS:
            return False, None
        if fact_key in _facts_pinned_to_one_line():
            return False, None
        owners: List[set] = []
        for g in values:
            o: set = set(context.owners_of(g.get("display")))
            for src in g.get("sources") or []:
                o |= set(context.owners_of(src.get("raw")))
            owners.append(o)
        if not all(owners):
            return False, None
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                if owners[i] & owners[j]:
                    return False, None
        lines = [set().union(*(context.lines_of_owner(o) for o in os_)) for os_ in owners]
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                if lines[i] & lines[j]:
                    return False, ("two policies on the same coverage line in one "
                                   "submission - confirm which applies")
        for g, o in zip(values, owners):
            g["scope"] = sorted(o)
        logger.info("underwriting: %s - %d value(s) retained under their own "
                    "policy scope; not a conflict", fact_key, len(values))
        return True, None
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("underwriting: scope check failed for %s - %s", fact_key, exc)
        return False, None


def _conflict_reason(fact_key: str, kind: str, values: List[dict]) -> str:
    """Plain-language reason a conflict is a conflict (client 1.5 "reason for
    conflict"; persisted with the producer's resolution, F10)."""
    if kind in ("currency", "integer"):
        return "the documents state different amounts"
    try:
        from services.fact_comparison import _fe as _door
        k = _door.value_kind(fact_key)
    except Exception:                                         # noqa: BLE001
        k = ""
    # A CURATED field arrives with kind "currency"/"integer" and is answered
    # above. An AUTO-DISCOVERED one arrives as "identity" whatever it holds, so
    # the only thing that knows it is an amount is `value_kind` - and there was
    # no branch for it. Live 2026-08-23: `gl_each_occurrence`, `gl_aggregate`,
    # `gl_products_aggregate` and `total_policy_premium` all showed the generic
    # "materially different values remain after normalization and scope
    # matching" against two plain dollar figures.
    if k in ("money", "count", "percent"):
        return "the documents state different amounts"
    if k == "date":
        return "the documents state different dates"
    if k == "name":
        return "the documents name materially different entities"
    if k == "address":
        return "the documents point to materially different locations"
    if k in ("identifier", "fein", "code"):
        return "the documents carry different identifiers"
    return "materially different values remain after normalization and scope matching"


def unevidenced_boolean_negative(fact_key: str, value: Any) -> bool:
    """A two-way boolean's `false` is silence, not a No - see the definition in
    `extraction_service`, which owns the two declaration sets it reads. Re-
    exported here because this module is where it is applied, and both the
    picker and the merge must ask ONE function."""
    try:
        from services.extraction_service import (
            unevidenced_boolean_negative as _door,
        )
        return _door(fact_key, value)
    except Exception:                                        # noqa: BLE001
        return False


def _auto_scalar_keys(docs: List[dict], exclude: set) -> set:
    """Fact keys eligible for generic cross-document reconciliation.

    Any SCALAR fact (not list / dict / bool) present in the documents that is not
    already a curated reconcilable field and not a private/internal ('_'-prefixed)
    key. Determined from the actual values, so it needs no static schema and
    never trips over list/structured facts - those cannot use a two-value picker
    and are intentionally left to the existing detectors.

    A two-way boolean's ``false`` does not make a key eligible either - see
    ``unevidenced_boolean_negative``. A key whose ONLY appearance is such a
    value never opens a picker row at all.
    """
    keys: set = set()
    for d in docs or []:
        facts = d.get("facts") or {}
        if not isinstance(facts, dict):
            continue
        for k, v in facts.items():
            if not k or k.startswith("_") or k in exclude or k in keys:
                continue
            val = v["value"] if isinstance(v, dict) and "value" in v else v
            if val is None or isinstance(val, (list, dict, bool)):
                continue
            if unevidenced_boolean_negative(k, val):
                continue
            keys.add(k)
    return keys


# ── Public API ────────────────────────────────────────────────────────────────

def _fold_one_agency_printings(values: List[dict]) -> List[dict]:
    """One agency printed two ways is ONE answer, not a conflict.

    "CRS Insurance Brokerage" (the COI) and "COMMERCIAL RISK SOLUTIONS, INC."
    (the dec pages) are the same agency - same address, same phone - and the
    card asked the producer to choose between them as "materially different
    entities". The sameness decision is the door's (`fact_comparison.
    same_agency`); printings it cannot place stay separate, so two real
    agencies still conflict. Producer NAME only - never a carrier, whose
    affiliated legal entities must keep conflicting.
    """
    if len(values) < 2:
        return values
    try:
        from services.fact_comparison import same_agency
    except Exception:                                         # noqa: BLE001
        return values
    folded: List[dict] = []
    for g in values:
        home = next((f for f in folded
                     if same_agency(f.get("display"), g.get("display")) is True), None)
        if home is None:
            folded.append({**g, "sources": list(g.get("sources") or [])})
            continue
        home["sources"].extend(g.get("sources") or [])
        if len(str(g.get("display") or "")) > len(str(home.get("display") or "")):
            home["display"] = g.get("display")
            home["normalized"] = g.get("normalized")
    return folded


def _producer_block_separated(merged_facts: Optional[dict]) -> bool:
    """True once the merge has moved the documents' producer to the EXPIRING
    keys because a DIFFERENT agency is submitting (extraction_service.
    _route_producer_party). Every document's producer value is then the
    expiring agency's: there is no rival for the submitting producer, and a
    card offering one would let a click put the old agency back on the form.
    """
    try:
        from services.fact_comparison import same_agency
    except Exception:                                         # noqa: BLE001
        return False
    expiring = _fv(merged_facts or {}, "expiring_producer_name")
    if not isinstance(expiring, str) or not expiring.strip():
        return False
    current = _fv(merged_facts or {}, "producer_name")
    if not isinstance(current, str) or not current.strip():
        return True
    return same_agency(current, expiring) is False


def assess_underwriting_consistency(
    docs: List[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Assess cross-document consistency of the reconcilable underwriting fields.

    Parameters
    ----------
    docs : active (non-excluded) processed-document dicts, each exposing
           ``facts`` and ideally ``doc_id`` / ``filename`` / ``doc_type``.
    merged_facts : the post-merge fact dict (used to surface the value that will
           actually be stamped into forms).
    confirmations : {fact_key: confirmed_raw_value} — values the user has already
           confirmed. A confirmed field is reported as resolved (status
           "confirmed", review_required False).

    Returns
    -------
    {
      "fields": [ {fact_key, label, status, review_required, kind, forms,
                   merged_value, confirmed_value, values:[{normalized, display,
                   sources:[{doc_id, filename, doc_type, doc_type_label, raw}]}]},
                  ... ],
      "review_required": bool,    # any field in unresolved conflict
      "conflict_count": int,
      "model_version": str, "assessed_at": str,
    }
    """
    # Local import avoids a circular dependency at module load
    # (extraction_service imports nothing from here).
    try:
        from services.extraction_service import DOC_TYPE_LABELS
    except Exception:                                  # pragma: no cover
        DOC_TYPE_LABELS = {}

    now = datetime.now(timezone.utc).isoformat()
    docs = docs or []
    merged_facts = merged_facts or {}
    # A form number confirmed as a policy number is never an answer - see
    # `usable_confirmations`. Before this the card rendered it as CONFIRMED.
    confirmations = usable_confirmations(confirmations)

    # Beta Report §4.3 item 3: flag documents with no raw OCR text. For these the
    # raw-text safety-net scan cannot run, so their cross-document comparison is
    # AI-extraction only and may miss a value the LLM collapsed. Logged once per
    # assessment (only when there is more than one document to compare).
    if len(docs) > 1:
        _no_text = [
            (d.get("filename") or f"document_{i + 1}")
            for i, d in enumerate(docs)
            if not str(d.get("text") or "").strip()
        ]
        if _no_text:
            logger.warning(
                "underwriting_consistency: %d of %d document(s) have no raw text; "
                "their cross-document comparison is AI-extraction only and may be "
                "incomplete (text-scan skipped): %s",
                len(_no_text), len(docs), ", ".join(_no_text),
            )

    fields_out: List[dict] = []
    conflict_count = 0
    assessed_keys: set = set()

    # Package context for the equivalence filter, built ONCE from the verified
    # dec index. It is what lets three policy numbers on a three-policy account
    # stop being "a conflict" (client 2026-08-17 item 2: "...only be treated as
    # conflicting if Primble establishes that they belong to the same policy and
    # coverage context"). Positive evidence only - no index, no opinion, and the
    # behaviour is exactly what it is today.
    from services.fact_comparison import build_context, document_witnesses as _door_witnesses
    eq_context = build_context(merged_facts, docs)

    # Statements the submission's narrative fields make, mined ONCE. Read-only:
    # they annotate conflict rows and never become facts (see narrative_facts).
    try:
        from services.narrative_facts import statements_for_facts
        narrative_statements = statements_for_facts(merged_facts, eq_context, docs)
        if narrative_statements:
            logger.info("underwriting: %d statement(s) mined from the "
                        "submission's remarks", len(narrative_statements))
    except Exception as _nex:                                 # noqa: BLE001
        logger.warning("underwriting: narrative mining unavailable - %s", _nex)
        narrative_statements = []

    # Effective registry = the curated fields, plus (when full-field
    # reconciliation is enabled) every OTHER scalar fact present across the
    # documents. This closes the "silent-fill" gap for fields outside the curated
    # set: a cross-document disagreement on ANY scalar fact now gets a user
    # choice instead of a silent merge. Auto fields are identity-kind (routed
    # through the shared normalizer, so formatting-only differences never
    # conflict), never hard stops, never generation-blocking. Flag OFF ->
    # effective == RECONCILABLE_FIELDS and behavior is identical to before.
    effective_fields = dict(RECONCILABLE_FIELDS)
    if _full_field_enabled():
        for _k in _auto_scalar_keys(docs, exclude=set(RECONCILABLE_FIELDS)):
            effective_fields[_k] = {"label": _humanize(_k), "kind": "identity", "forms": [], "_auto": True}
    # V1 plan C1 F7 (client 1.5): a questionnaire answer that disagreed with
    # the documents was held as a CANDIDATE instead of overwriting the fact.
    # It joins the field here as one more source - "Client questionnaire" -
    # so the producer resolves it in the same picker, through the same
    # confirm endpoint, with the same audit row. No second screen.
    client_candidates: Dict[str, dict] = {
        k: v for k, v in ((merged_facts.get("_client_answer_conflicts") or {}).items())
        if isinstance(v, dict) and str(v.get("client_value") or "").strip()
        and k not in confirmations
    }
    for _k in client_candidates:
        if _k not in effective_fields:
            effective_fields[_k] = {"label": _humanize(_k), "kind": "identity", "forms": [], "_auto": True}

    # The producer card, once the merge has separated the submitting agency
    # from the expiring one: every document's producer value is the EXPIRING
    # agency's, so there is nothing to reconcile and nothing a click should be
    # able to put back. The key stays ASSESSED so `detect_source_conflicts`,
    # which skips exactly the keys assessed here, does not re-report it.
    _producer_separated = _producer_block_separated(merged_facts)
    for fact_key, cfg in effective_fields.items():
        kind = cfg["kind"]
        label = cfg["label"]
        is_auto = bool(cfg.get("_auto"))
        assessed_keys.add(fact_key)
        if _producer_separated and _is_producer_identity_field(fact_key):
            continue

        # Group raw values by their normalized form, recording every source doc.
        # Two-pass approach:
        #   Pass 1 — LLM-extracted facts (primary, high signal).
        #   Pass 2 — Text-scan of raw OCR text (supplementary: catches cases where
        #            the LLM anchored to one doc's value and reported the same number
        #            from a doc that actually contains a different figure).
        # Text-scan values are marked with source "text_scan" so they are visually
        # distinct in the UI from confirmed LLM-extracted values.
        groups: Dict[str, dict] = {}

        for idx, d in enumerate(docs):
            dt = d.get("doc_type") or "unknown"
            doc_id   = str(d.get("doc_id") or idx)
            filename = d.get("filename") or f"document_{idx + 1}"
            dt_label = DOC_TYPE_LABELS.get(dt, dt.replace("_", " ").title())

            # Pass 1: LLM-extracted fact value.
            # A document only testifies about what its ROLE covers (client 1.2).
            # A loss run's policy number / carrier / dates describe the CLAIMS,
            # not the policy being applied for - comparing them manufactured two
            # of the three conflicts on the 2026-08-21 live run.
            if not _door_witnesses(dt, fact_key):
                continue
            raw = _fv(d.get("facts") or {}, fact_key)
            # A TWO-WAY boolean's `false` is silence, not a rival answer. Owner
            # ruling, live run 1: "if any document indicates yes or no and there
            # is nothing related mentioned in another doc then take yes/no from
            # that doc, but if there is a conflict then show". This is the half
            # that decides what counts as "nothing mentioned" - see
            # `unevidenced_boolean_negative`. A tri-state fact keeps both
            # answers and still conflicts.
            if raw is not None and unevidenced_boolean_negative(fact_key, raw):
                continue
            # A FORM number is never a candidate policy number (see
            # `_is_form_number_policy_value`) - not from the scalar, not from a row.
            if _is_form_number_policy_value(fact_key, raw):
                raw = None
            llm_norm = None
            if raw is not None:
                llm_norm = _normalize(raw, kind, fact_key)
                if llm_norm:
                    src = {
                        "doc_id": doc_id, "filename": filename,
                        "doc_type": dt, "doc_type_label": dt_label,
                        "raw": str(raw), "source_method": "llm",
                    }
                    g = groups.setdefault(llm_norm, {"normalized": llm_norm, "display": str(raw), "sources": []})
                    g["sources"].append(src)
                    # Two raw strings collapsing to the SAME normalized value (e.g. a
                    # ZIP+4 address vs its ZIP5 form) are the same real-world fact -
                    # keep whichever raw string is more complete/descriptive as the
                    # display, not just whichever document happened to come first.
                    if _value_completeness(fact_key, kind, str(raw)) > _value_completeness(fact_key, kind, g["display"]):
                        g["display"] = str(raw)

            # ── Pass 1b: the fact stated PER COVERAGE LINE (C1b) ────────────
            # A multi-policy declarations page prints one carrier and one
            # policy number PER COVERAGE PART, so extraction correctly declines
            # to elect a package-level scalar - measured live, every dec page
            # had `carrier_name = None` while its `coverage_lines` named four
            # carriers. Reading only the scalar meant a rival GL carrier was
            # never a CANDIDATE, so no conflict row and no scoped row appeared.
            #
            # THIS IS SAFE ONLY BECAUSE OF THE SCOPED STORE. The first attempt
            # raised these values with no scope attached, and `_scope_values`
            # then had to recover it from the value's characters - which fails
            # on an abbreviated spelling and turned the client's own "GL carrier
            # and Auto carrier may legitimately differ" case into a false
            # conflict. `_scope_from_store` now supplies the line directly.
            _line_attr = _LINE_SCOPED_FACT_COLUMN.get(fact_key)
            if _line_attr:
                for _ln in (_fv(d.get("facts") or {}, "coverage_lines") or []):
                    if not isinstance(_ln, dict):
                        continue
                    _lv = _ln.get(_line_attr)
                    if _is_form_number_policy_value(fact_key, _lv):
                        continue
                    _ln_norm = _normalize(_lv, kind, fact_key) if _lv else None
                    if not _ln_norm:
                        continue
                    _g = groups.setdefault(
                        _ln_norm,
                        {"normalized": _ln_norm, "display": str(_lv), "sources": []})
                    if not any(s.get("raw") == str(_lv) and s.get("doc_id") == doc_id
                               for s in _g["sources"]):
                        _g["sources"].append({
                            "doc_id": doc_id, "filename": filename,
                            "doc_type": dt, "doc_type_label": dt_label,
                            "raw": str(_lv), "source_method": "coverage_line",
                            "line": _ln.get("line"),
                        })
                    if _value_completeness(fact_key, kind, str(_lv)) > \
                            _value_completeness(fact_key, kind, _g["display"]):
                        _g["display"] = str(_lv)

            # Pass 2: text-scan of raw OCR.
            # Only add a text-scan value if it is DIFFERENT from the LLM value,
            # so we don't double-report an agreed value. Skipped for auto-
            # discovered fields (they have no bespoke pattern and the generic
            # label scan adds cost without a reliable signal for arbitrary keys).
            raw_text = d.get("text") or ""
            if raw_text and not is_auto:
                for scanned_raw in _text_scan_values(raw_text, fact_key):
                    scanned_norm = _normalize(scanned_raw, kind, fact_key)
                    if not scanned_norm or scanned_norm == llm_norm:
                        continue
                    # A genuinely different value found directly in the text.
                    src = {
                        "doc_id": doc_id, "filename": filename,
                        "doc_type": dt, "doc_type_label": dt_label,
                        "raw": scanned_raw, "source_method": "text_scan",
                    }
                    g = groups.setdefault(scanned_norm, {"normalized": scanned_norm, "display": scanned_raw, "sources": []})
                    # Only add this source once per doc (avoid duplicate entries
                    # when multiple patterns match the same figure).
                    already = any(s["doc_id"] == doc_id and s["source_method"] == "text_scan" for s in g["sources"])
                    if not already:
                        g["sources"].append(src)
                    if _value_completeness(fact_key, kind, scanned_raw) > _value_completeness(fact_key, kind, g["display"]):
                        g["display"] = scanned_raw

        _cc = client_candidates.get(fact_key)
        if _cc:
            _c_raw = str(_cc.get("client_value"))
            _c_norm = _normalize(_c_raw, kind, fact_key)
            if _c_norm:
                src = {
                    "doc_id": "client_questionnaire", "filename": "Client questionnaire",
                    "doc_type": "client_questionnaire",
                    "doc_type_label": "Client Questionnaire",
                    "raw": _c_raw, "source_method": "client_answer",
                }
                g = groups.setdefault(_c_norm, {"normalized": _c_norm, "display": _c_raw, "sources": []})
                g["sources"].append(src)

        confirmed_raw = confirmations.get(fact_key)
        confirmed_value = str(confirmed_raw) if confirmed_raw is not None else None

        # Nothing extracted and nothing confirmed → field not present; skip it.
        if not groups and confirmed_value is None:
            continue

        # ── Strict entity promotion (audit 2026-08-15 round 10) ──────────────
        # The coarse normalizers are EQUIVALENCE tools and merge legally
        # different entities: normalize_carrier reduced EMC Property & Casualty
        # AND Employers Mutual Casualty to "emc", normalize_name reduced an
        # LLC and an Inc to the same base - so the two REAL carriers on the
        # client's package grouped as ONE candidate and the picker never
        # opened. When a name/carrier field's sources coarsely agree but name
        # materially different entities (each carrying a word the other
        # lacks), the group is RE-SPLIT on the strict key so the conflict
        # surfaces and the client is asked - "unresolved conflicts must remain
        # unresolved". Formatting/truncation/suffixless variants stay merged.
        # WIDENED FOR V1 H5 - the `len(groups) == 1` gate this used to carry was
        # the client's ACORD 25 multi-carrier complaint, one layer down.
        # `normalize_carrier` is a FAMILY key, so on the Orbin package it sorted
        # the same three printings like this:
        #
        #     EMC Property & Casualty Company    -> "emc"        <- two REAL
        #     Employers Mutual Casualty Company  -> "emc"        <- carriers, ONE group
        #     Employers Mutual Casualty Co       -> "employers"  <- one carrier, split off
        #
        # Two groups, so the re-split never ran, and the fused "emc" candidate
        # then carried printings belonging to BOTH the General Liability line and
        # the Auto/Umbrella lines. `_scope_from_store` saw one value straddling
        # two coverage lines, called it "two policies on the same coverage line"
        # and raised a conflict on a package where nothing was wrong - the
        # client's literal report, "two legitimate carriers were treated as a
        # Data Consistency problem merely because both names appeared".
        #
        # Re-keying on the strict entity key fixes BOTH directions at once: the
        # fused group comes apart, and the two printings of Employers Mutual
        # come back together. It cannot manufacture a conflict, because
        # `_merge_equivalent_value_groups` runs immediately below and re-folds
        # every genuine formatting/truncation variant; what it separates is only
        # what `entities_materially_differ` says are different legal entities.
        if kind == "identity" and groups:
            try:
                # The sameness decision comes from the ONE DOOR (D3); only the
                # key builder and the field tables come from `normalization`.
                # Importing `entity_identity_conflict` directly here was a
                # second opinion living outside the door - and it slipped past
                # `test_comparison_has_one_owner` for weeks because that guard
                # matched imports with a regex that could not see an indented
                # one inside a function body (fixed 2026-08-23).
                from services.fact_comparison import entities_materially_differ
                from services.normalization import (
                    strict_entity_key, NAME_FIELDS, CARRIER_FIELDS,
                )
                _is_entity_field = (
                    fact_key in NAME_FIELDS or fact_key in CARRIER_FIELDS
                    or _infer_field_category(fact_key) in ("name", "carrier"))
                if _is_entity_field:
                    _raws = [s["raw"] for g in groups.values()
                             for s in g["sources"]]
                    if entities_materially_differ(_raws):
                        _regrouped: Dict[str, dict] = {}
                        for g in groups.values():
                            for s in g["sources"]:
                                sk = strict_entity_key(s["raw"]) or g["normalized"]
                                ng = _regrouped.setdefault(
                                    sk, {"normalized": sk,
                                         "display": s["raw"], "sources": []})
                                ng["sources"].append(s)
                                # Keep the fullest printing as the display, the
                                # same rule the grouping passes above apply.
                                # Two printings of one insurer now land in one
                                # group, and "Casualty Company" is the name the
                                # producer should be shown, not "Casualty Co".
                                if _value_completeness(fact_key, kind, s["raw"]) > \
                                        _value_completeness(fact_key, kind, ng["display"]):
                                    ng["display"] = s["raw"]
                        groups = _regrouped
                        logger.info(
                            "underwriting: %s promoted to conflict - the "
                            "sources name materially different entities that "
                            "the coarse normalizer had merged", fact_key)
            except Exception as _pex:                     # noqa: BLE001
                logger.warning(
                    "underwriting: strict entity promotion failed for %s: %s",
                    fact_key, _pex)

        values = list(groups.values())
        # One producer agency printed two ways is one answer - see
        # `_fold_one_agency_printings`. Producer NAME only.
        if fact_key == "producer_name":
            values = _fold_one_agency_printings(values)

        # ── Foreign-line candidates are not candidates (client item 2) ───────
        # "GL Form Type: BUSINESS AUTO COVERAGE FORM vs Commercial General
        # Liability - those are different lines of business, not competing GL
        # values." A value naming somebody else's coverage line is a
        # mis-extraction, and asking a producer to choose between a
        # mis-extraction and the truth is worse than not asking. Never empties
        # the field: if EVERY candidate is foreign we have no basis to prefer
        # one, so all are kept and the row renders as it does today.
        values = _drop_foreign_line_values(fact_key, values)
        # A declared DBA is the insured's own name, never a rival one.
        values = _drop_declared_trade_names(fact_key, values, docs)
        # A per-class rating basis is not a rival to the package total. Runs
        # with the other mis-extraction filters, BEFORE any grouping decision:
        # these are not rival answers, so they must never reach the point where
        # something has to choose between them.
        values = _drop_class_exposure_candidates(fact_key, values, merged_facts)
        # A value that is not legal FOR THIS FIELD is not a rival answer.
        values = _drop_values_outside_declared_domain(fact_key, values)
        # Nor is a form reference no verified contract names, offered as a
        # policy number (see `_FORM_REFERENCE_RE` - both conditions).
        values = _drop_unknown_form_references(fact_key, values, merged_facts, docs)

        # ── Equivalence filter (client 2026-08-17) ───────────────────────────
        # "Primble should escalate judgment, not formatting." The grouping above
        # compares NORMALIZED TEXT, which cannot see that $2,000,000 and
        # "$2,000,000 General Aggregate" are one amount, that "Denver, Colorado"
        # is a COMPONENT of the full street address, that two remarks paragraphs
        # are not rival answers, or that three policy numbers on a three-policy
        # account are three contracts. Measured 2026-08-17: 24 of 42 realistic
        # "same fact, two printings" pairs were escalated, across eight shape
        # families - the client had reported two of them.
        #
        # It runs AFTER the grouping and only ever MERGES groups, so it cannot
        # manufacture a conflict; a failure inside it leaves the grouping
        # untouched (see services/fact_equivalence for the full argument).
        # Pass 1 - pure VALUE equivalence (formatting, containment, cliques),
        # no package context: two printings of one value fold here whatever
        # policy they belong to.
        values = _merge_equivalent_value_groups(fact_key, values, None)

        # ── Scope BEFORE conflict (V1 plan C1 F2b, client 1.2 / 1.5) ────────
        # "Different values with different valid scope: retain each under its
        # correct scope. Do not create a conflict." On a multi-policy package
        # a line-scoped fact (policy number, carrier, term) legitimately has
        # one value PER POLICY. Each surviving group is attributed to its
        # owner through the verified dec index; when every group has an owner
        # and no two owners share a coverage line, the field is SCOPED - every
        # value kept, each labelled, nothing to resolve. Two policies on the
        # SAME line in one period are NOT two scopes (a real GL twice) and
        # stay a conflict, with the reason saying so. An unattributed group
        # keeps today's behaviour - positive evidence only.
        # C1b: the STORED scope is consulted first. It is the only source that
        # knows which coverage line a value belongs to without inferring it
        # from the value's own characters, so it settles the case the
        # character-keyed path cannot (a carrier printed two ways). The legacy
        # path still runs when the store cannot place every group, which is
        # every pre-C1b session and any package with no `coverage_lines`.
        # SYS-06: one policy printed two ways is one policy. Runs BEFORE the
        # scope decision because two printings of one contract would otherwise
        # look like two policies on one coverage line - the client's literal
        # report. Merge-only, so it can never hide a disagreement.
        values = _merge_by_line_record(fact_key, values, merged_facts)
        # A question the producer has already answered FOR ITS LINE is not
        # asked again (SYS-06 "apply it only to the applicable line or lines").
        scoped_conf = {
            sc: str(v) for k, v in confirmations.items()
            for _fk, sc in [parse_confirmation_key(k)]
            if _fk == fact_key and sc and v is not None
        }
        if scoped_conf:
            values = _drop_answered_line_candidates(
                fact_key, values, scoped_conf, docs)
        scoped, conflict_reason, collided_lines = _scope_from_store(
            fact_key, values, merged_facts)
        # A question about ONE coverage line may only offer THAT line's values.
        # Live run B: a "Confirm for general liab" button listed the Auto policy
        # number as a choice.
        if collided_lines:
            values = _restrict_to_conflicted_lines(
                fact_key, values, collided_lines, docs)
        elif conflict_reason and any(v.get("scope") == [] for v in values):
            # The store placed some values and could not place others. Only the
            # unplaceable ones are in question; the placed ones keep their line
            # and must not be offered as answers to it.
            _unplaced = [v for v in values if v.get("scope") == []]
            if len(_unplaced) >= 2:
                values = _unplaced
        if not scoped and conflict_reason is None:
            scoped, conflict_reason = _scope_values(fact_key, values, eq_context)

        # Pass 2 - package-context equivalence (two printings of one contract,
        # a line premium inside the package total, values the index proves
        # belong to different contracts). Skipped when the field is SCOPED:
        # the client's rule is "retain each under its correct scope", and
        # merging three policies into one displayed number is the opposite.
        if not scoped and conflict_reason is None:
            values = _merge_equivalent_value_groups(fact_key, values, eq_context)

        distinct = len(values)

        # ── A DATED CHANGE IS NOT A CONFLICT (client 11 Sep, Orbin) ─────────
        # "The COI specifically states it was reduced from $3M to $1M effective
        # 7/25/25 ... Primble should understand that as a policy change over
        # time, not simply a $3M versus $1M conflict." Only when the documents
        # say so themselves, in words and with a date. The rule and every gate
        # live behind the comparison door (`fact_comparison.dated_change`),
        # which the merge reads too - so the value this card calls current is
        # the value that stamps.
        change = None
        if confirmed_value is None and distinct == 2 and not scoped:
            change = _dated_change_for_field(
                fact_key, values, docs, merged_facts, narrative_statements)

        if confirmed_value is not None:
            status = "confirmed"
            review_required = False
        elif change:
            status = "changed"
            review_required = False
        elif distinct >= 2 and scoped:
            status = "scoped"
            review_required = False
        elif distinct >= 2:
            status = "conflict"
            review_required = True
            conflict_count += 1
            conflict_reason = conflict_reason or _conflict_reason(fact_key, kind, values)
        elif distinct == 1:
            status = "consistent"
            review_required = False
        else:
            status = "confirmed"   # confirmed-only handled above; unreachable
            review_required = False

        # Auto-discovered fields only surface when actionable (conflict or a
        # stored confirmation). A consistent auto field adds nothing to review
        # and would only bloat the payload/UI - it stays OWNED (already recorded
        # in assessed_keys above, so the crude detector skips it) but is not
        # listed. Curated fields keep their existing behavior (consistent rows
        # are still emitted, unchanged).
        if is_auto and status in ("consistent", "scoped"):
            continue

        # ── A COMPOSITE IS A WITNESS, NOT A RIVAL ANSWER (Principle 2) ──────
        # Live run A: the dec page's `gl_limits` came back "$1,000,000 /
        # $2,000,000" and the certificate's "$1,000,000 Each Occurrence", and
        # the producer was told *"the documents state different amounts"*.
        # They do not. They agree on every amount BOTH state; one simply also
        # states the aggregate. Principle 2 names it: *"differing levels of
        # specificity should be normalized before deciding that two values
        # conflict."*
        #
        # The comparator is not wrong to refuse - an UNLABELLED single amount
        # against a composite really is ambiguous, and
        # `test_a_composite_amount_is_never_flattened` guards that. The QUESTION
        # is wrong. `gl_limits` is a rendering of four scalars
        # (`_CURRENCY_COMPOSITE_PARENT`), every one of which this picker
        # reconciles on its own. Asking a producer to choose between two
        # printings of the block is not a fact question, and whichever they
        # confirm REPLACES the other - a certificate's one row would overwrite
        # the dec page's six limits.
        #
        # POSITIVE EVIDENCE ONLY: suppressed solely when the package actually
        # carries a child this picker can assess, so nothing is ever silenced
        # without a better question already on screen in its place.
        if status == "conflict" and _composite_is_reconciled_by_its_children(
                fact_key, effective_fields, docs):
            logger.info(
                "underwriting: %s not asked - it renders %s, which are "
                "reconciled on their own (a composite is a witness, not a "
                "rival answer)", fact_key,
                ", ".join(_composite_children(fact_key)))
            conflict_count -= 1
            continue

        # Figure 3: recommend the most complete/correct value + a confidence level.
        # Only computed for an OPEN conflict — a confirmed/consistent field needs
        # no suggestion. ``preselect`` is True only for HIGH confidence on a
        # non-hard-stop field (the frontend pre-checks that radio).
        suggestion = _suggest_for_field(fact_key, kind, values) if status == "conflict" else None

        # ── What the submission's own remarks say about this disagreement ────
        # Client 2026-08-17: "A paragraph containing policy numbers, dates,
        # limits, premiums ... the individual facts within it need to be
        # interpreted in their appropriate context." Their own example is the
        # umbrella: the dec page says $3M, the COI says $1M, and the remarks
        # explain that it was REDUCED from one to the other on a stated date.
        #
        # This EXPLAINS the conflict; it never resolves it. The same client
        # required that "an unresolved fact remains unresolved downstream rather
        # than another part of Primble independently selecting a value", so no
        # value is chosen, pre-selected or written - the producer just gets the
        # evidence next to the question instead of having to find it.
        narrative_note = None
        if status == "conflict":
            try:
                from services.narrative_facts import explain_conflict
                narrative_note = explain_conflict(
                    fact_key, [v.get("display") for v in values],
                    narrative_statements)
            except Exception as _nex:                         # noqa: BLE001
                logger.warning("underwriting: narrative note failed for %s: %s",
                               fact_key, _nex)
        elif status == "changed" and change:
            # A changed row explains itself in the documents' own words.
            narrative_note = (
                f"{change.get('document') or 'The submission'} states this "
                f"changed from {change.get('prior')} to {change.get('current')} "
                f"effective {change.get('as_of')}"
                + (f": \"{change.get('quote')}\"" if change.get("quote") else "."))

        # A contract-scoped difference on a MULTI-POLICY package is not a
        # blocking error - each policy carries its own term. Decided here, ONCE,
        # so `extraction_pipeline`'s hard-stop escalation and
        # `sqs_service.check_doc_consistency` cannot disagree; the first cut
        # fixed only the latter and probe run C still showed a hard stop and a
        # warning for the same two dates.
        blocking_downgraded = bool(
            status == "conflict"
            and fact_key in CONTRACT_SCOPED_HARD_STOP_KEYS
            and eq_context is not None and eq_context.is_multi_contract
        )
        if blocking_downgraded:
            logger.info(
                "underwriting: %s conflict downgraded from blocking - this "
                "package evidences %d contracts and each carries its own term",
                fact_key, len(eq_context.contracts))

        fields_out.append({
            # Client 11 Sep: the dated change the documents state - current
            # value, prior value, date, the sentence and the documents. Present
            # only on a "changed" row.
            "change":           ({k: change.get(k) for k in (
                "current", "prior", "as_of", "quote", "document", "prior_documents")}
                if status == "changed" and change else None),
            # SYS-06: WHICH coverage line(s) this question is about, so a
            # confirmation can be applied to that line instead of the whole
            # submission. Empty when the disagreement is not line-specific -
            # the confirm then behaves exactly as it always has.
            "conflict_scope":   sorted(collided_lines) if status == "conflict" else [],
            "confirmed_scopes": dict(scoped_conf),
            "line_records":     _line_records_for(fact_key, merged_facts),
            "narrative_note":  narrative_note,
            "blocking_downgraded": blocking_downgraded,
            "fact_key":        fact_key,
            "label":           label,
            "kind":            kind,
            "forms":           _forms_for_field(fact_key, cfg),
            "status":          status,
            "conflict_reason": conflict_reason if status == "conflict" else None,
            "review_required": review_required,
            "merged_value":    _display(_fv(merged_facts, fact_key)),
            "confirmed_value": confirmed_value,
            "values":          values,
            "suggested_value":      suggestion["value"]      if suggestion else None,
            "suggested_normalized": suggestion["normalized"] if suggestion else None,
            "confidence":           suggestion["confidence"] if suggestion else None,
            "preselect":            bool(suggestion["preselect"]) if suggestion else False,
        })

    # ── Cross-field linking (Figure 3: "apply to all" across related fields) ──
    # Two OPEN conflicts are LINKED when they show the exact same set of
    # normalized values from the exact same set of source documents - the
    # strongest available signal that they are the same real-world fact entered
    # into two different form fields (e.g. mailing vs. physical address both
    # disagreeing between the identical two addresses from the identical two
    # documents). Matching on BOTH the value set AND the document set - not the
    # value set alone - is what makes this safe to apply generically to every
    # field pair instead of a hand-picked list: two unrelated fields (revenue vs.
    # payroll) would need to coincidentally disagree with the IDENTICAL numbers
    # from the IDENTICAL documents to false-link, which does not happen in
    # practice. Confirming a linked field auto-applies the same value to its
    # partner(s) too (see confirm_underwriting_value) instead of forcing the
    # producer to resolve the same conflict a second time.
    def _signature(f: dict):
        docs = frozenset(s["doc_id"] for v in f["values"] for s in v.get("sources", []))
        vals = frozenset(v["normalized"] for v in f["values"])
        return (vals, docs)

    conflict_fields = [f for f in fields_out if f["status"] == "conflict"]
    for f in fields_out:
        if f["status"] != "conflict":
            f["linked_fields"] = []
            continue
        sig = _signature(f)
        f["linked_fields"] = [
            {"fact_key": g["fact_key"], "label": g["label"]}
            for g in conflict_fields
            if g is not f and _signature(g) == sig
        ]

    return {
        "fields":          fields_out,
        "review_required": any(f["review_required"] for f in fields_out),
        "conflict_count":  conflict_count,
        # Every fact key this pass evaluated (curated + auto). The pipeline unions
        # this into detect_source_conflicts' skip set so an auto-reconciled field
        # is never ALSO reported as a raw-string source conflict (no double count).
        "assessed_keys":   sorted(assessed_keys),
        "model_version":   UNDERWRITING_CONSISTENCY_MODEL_VERSION,
        "assessed_at":     now,
    }


def _display(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _resolve_reconcilable_cfg(fact_key: str, docs: Optional[List[dict]] = None) -> Optional[dict]:
    """Field config for confirm/apply — must mirror what the DISPLAY path
    (``assess_underwriting_consistency``'s ``effective_fields``) considers
    reconcilable, or a field the UI is actively showing a "Confirm & apply to
    forms" button for gets rejected by the confirm endpoint every time.

    Curated fields use their own registry entry. Any other key is only
    accepted when full-field reconciliation is on AND ``docs`` is supplied AND
    the key is a genuine scalar fact actually present in one of those
    documents — the same discovery check the display path uses
    (``_auto_scalar_keys``). This deliberately does NOT accept an arbitrary
    fact_key just because the feature flag is on; without a real document
    backing it, it is rejected exactly as before. Returns None when the field
    is not confirmable.
    """
    cfg = RECONCILABLE_FIELDS.get(fact_key)
    if cfg is not None:
        return cfg
    if docs and _full_field_enabled():
        if fact_key in _auto_scalar_keys(docs, exclude=set(RECONCILABLE_FIELDS)):
            return {"kind": "identity"}
    return None


SCOPED_CONFIRM_SEPARATOR = "@"


def scoped_confirmation_key(fact_key: str, scope: Optional[str]) -> str:
    """The confirmations-map key for a value confirmed FOR ONE COVERAGE LINE.

    SYS-06: *"When the producer confirms a mapping, apply it only to the
    applicable line or lines."* A package-wide confirmation keeps its bare
    ``fact_key`` - so every stored confirmation written before this change
    still means exactly what it meant - and a line-scoped one is namespaced
    ``policy_number@general_liab``.

    Everything that iterates the map already skips a key it cannot resolve to
    a reconcilable field, so the namespaced entry is inert to every existing
    reader. That is the whole reason for encoding it in the key rather than
    changing the map's value shape, which would have had to be understood by
    the audit writer, the pipeline and five call sites at once.
    """
    s = str(scope or "").strip()
    return f"{fact_key}{SCOPED_CONFIRM_SEPARATOR}{s}" if s else fact_key


def parse_confirmation_key(key: Any) -> Tuple[str, Optional[str]]:
    """``("policy_number@auto")`` -> ``("policy_number", "auto")``."""
    s = str(key or "")
    if SCOPED_CONFIRM_SEPARATOR not in s:
        return s, None
    fact_key, _, scope = s.partition(SCOPED_CONFIRM_SEPARATOR)
    return fact_key, (scope.strip() or None)


def _pair_naic_with_its_carrier(
        rows: List[Any], scoped: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    """A carrier and its NAIC move as a MATCHED PAIR, or not at all.

    THE CLIENT'S OWN RULE, and a defect this codebase has already paid for once:
    *"Carrier name and NAIC should move through the system as a matched pair."*
    RC1 (2026-08-15) recorded `Employers Mutual Casualty Company` acquiring
    `EMC Property & Casualty`'s NAIC 25186 - *"a pair no document ever printed"*.

    The line-scoped confirm path reopened it. The producer answers three
    separate cards, so confirming carrier = `Redwood Basin` for General
    Liability while picking `36161` (Trinity Ridge's NAIC) on the NAIC card
    writes both onto the GL row and prints a company beside an identifier that
    belongs to a different company - on a signed application.

    So the confirmed CARRIER decides. Its NAIC is read from the rows that
    actually state that carrier on that line, and a contradicting NAIC answer
    is overridden rather than stamped.

    POSITIVE EVIDENCE ONLY. The pair is set only when the document states
    exactly ONE NAIC for the confirmed carrier on that line; a typed-in carrier
    the document does not name, or two NAICs for one carrier, leaves the NAIC
    untouched - blank or stale is recoverable, a wrong pair is not.
    """
    try:
        from services.extraction_service import _canon_line
    except Exception:                                         # noqa: BLE001
        return scoped
    carriers = {sc: val for fk, sc, val in scoped if fk == "carrier_name"}
    if not carriers:
        return scoped
    out = [e for e in scoped if e[0] != "carrier_naic" or e[1] not in carriers]
    for line, carrier in carriers.items():
        found: set = set()
        for row in rows:
            if not isinstance(row, dict) or _canon_line(row.get("line")) != line:
                continue
            if not _door_values_agree("carrier_name", row.get("carrier"), carrier):
                continue
            naic = str(row.get("naic") or "").strip()
            if naic:
                found.add(naic)
        dropped = next((v for fk, sc, v in scoped
                        if fk == "carrier_naic" and sc == line), None)
        if len(found) == 1:
            naic = next(iter(found))
            out.append(("carrier_naic", line, naic))
            if dropped and dropped != naic:
                logger.warning(
                    "underwriting: NAIC %r was answered for %s but %r is the "
                    "NAIC the documents print for %r - stamping the matched "
                    "pair, not the answer", dropped, line, naic, carrier)
        elif dropped is not None:
            # Cannot establish the pair. Refuse to stamp an NAIC that the
            # confirmed carrier may not own; the box stays as the documents
            # left it.
            logger.warning(
                "underwriting: NAIC %r for %s is not applied - the documents "
                "do not pair it with the confirmed carrier %r (%d candidate "
                "NAICs)", dropped, line, carrier, len(found))
    return out


def _apply_scoped_confirmations(out: dict, scoped: List[Tuple[str, str, str]]) -> bool:
    """Write each line-scoped confirmation onto ITS OWN `coverage_lines` rows.

    THE FORMS NEED NO CHANGE, and that is the point. Every per-line stamper -
    `_resolve_section_policy_identity`, `_resolve_current_policy_line_cell`,
    `_section_carrier_pair` - already reads this line's own row. Writing the
    producer's answer into the row it belongs to means "populate the
    corresponding forms from that line-specific record" is satisfied by the
    machinery that already exists, instead of by a second stamping path.

    Rows are COPIED before mutation: `merged_facts` is shallow-copied by the
    caller, so editing a row in place would reach back into the session's
    stored facts and silently rewrite history.
    """
    if not scoped:
        return False
    rows = out.get("coverage_lines")
    if not isinstance(rows, list) or not rows:
        return False
    try:
        from services.extraction_service import _canon_line
    except Exception:                                         # noqa: BLE001
        return False
    column = _LINE_SCOPED_FACT_COLUMN
    scoped = _pair_naic_with_its_carrier(rows, scoped)
    changed = False
    new_rows: List[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            new_rows.append(row)
            continue
        canon = _canon_line(row.get("line"))
        edit = {fk: val for fk, sc, val in scoped
                if canon and sc == canon and fk in column}
        if not edit:
            new_rows.append(row)
            continue
        copy = dict(row)
        for fk, val in edit.items():
            copy[column[fk]] = val
        new_rows.append(copy)
        changed = True
        logger.info(
            "underwriting: line-scoped confirmation applied to the %s row - %s",
            canon, {column[k]: v for k, v in edit.items()})
    if changed:
        # Rewriting two rival rows of one line to the producer's answer can
        # leave two rows that are now byte-identical. Only an EXACT duplicate
        # is dropped - two rows still differing in premium, limit or anything
        # else are both kept, because deciding which of those to discard is
        # not what the producer was asked (Principle 4 / "preserve the
        # information").
        seen: List[Any] = []
        deduped: List[Any] = []
        for row in new_rows:
            if isinstance(row, dict):
                key = sorted((k, str(v)) for k, v in row.items())
                if key in seen:
                    continue
                seen.append(key)
            deduped.append(row)
        out["coverage_lines"] = deduped
    return changed


def apply_confirmations(merged_facts: dict, confirmations: Optional[dict], docs: Optional[List[dict]] = None) -> dict:
    """Return a copy of ``merged_facts`` with every confirmed value applied.

    A confirmed value is stamped as a producer-verified envelope so it (a) flows
    into every form that consumes the fact and (b) is credited at full
    confidence by SQS — while remaining labelled as user-provided (source
    "user_confirmed"), distinct from source-document evidence (§6 evidence
    labelling). Mutates a shallow copy; the caller's dict is untouched.

    ``docs`` (the session's active documents) is required to accept a
    confirmation for an auto-discovered (non-curated) field — see
    ``_resolve_reconcilable_cfg``. Omitting it only affects those fields;
    curated fields are unaffected.
    """
    if not confirmations:
        return merged_facts
    # A stored confirmation of a FORM number (sessions confirmed before 14 Sep
    # 2026, when the card still offered them) is not applied: it would put an
    # AAIS form reference in the policy-number box of every form it reaches.
    # The rule lives in `usable_confirmations`, shared by every reader.
    _usable = usable_confirmations(confirmations)
    if len(_usable) != len(confirmations):
        logger.warning("underwriting: ignoring confirmed FORM number(s) as policy "
                       "number: %s", sorted(set(confirmations) - set(_usable)))
        confirmations = _usable
        if not confirmations:
            return merged_facts
    out = dict(merged_facts or {})
    # A producer confirmation made BEFORE the merge separated the submitting
    # agency from the expiring one could only choose between the EXPIRING
    # agency's printings - the card offered nothing else. Applied to
    # `producer_*` it would put the old agency back on the new application, so
    # it is kept where it belongs, on `expiring_producer_*`. A confirmation
    # naming the submitting agency itself still applies as before.
    if _producer_block_separated(out):
        from services.fact_comparison import same_agency as _same_agency
        _kept: Dict[str, Any] = {}
        for _key, _raw in confirmations.items():
            _fk, _scope = parse_confirmation_key(_key)
            if (not _scope and _raw is not None
                    and _is_producer_identity_field(_fk)
                    and not (_fk == "producer_name"
                             and _same_agency(_raw, _fv(out, "producer_name")) is True)):
                out[_fk.replace("producer_", "expiring_producer_", 1)] = {
                    "value": str(_raw), "confidence": _CONFIRMED_CONFIDENCE,
                    "source": _CONFIRMED_SOURCE}
                logger.info("underwriting: stored %s confirmation names the "
                            "EXPIRING agency - kept on the expiring keys", _fk)
                continue
            _kept[_key] = _raw
        confirmations = _kept
        if not confirmations:
            return out
    # SYS-06: line-scoped answers first. They never touch the package scalar -
    # confirming the Auto policy number must not make it the submission's
    # policy number, which is the client's "do not default a confirmed value to
    # the GL package policy".
    scoped_edits: List[Tuple[str, str, str]] = []
    for key, raw in confirmations.items():
        fk, scope = parse_confirmation_key(key)
        if not scope or raw is None:
            continue
        if _resolve_reconcilable_cfg(fk, docs) is None:
            continue
        if fk not in _LINE_SCOPED_FACT_COLUMN:
            # Only a fact that legitimately has ONE VALUE PER LINE may be
            # confirmed per line. Anything else scoped would invent a
            # relationship the package does not have.
            logger.warning(
                "underwriting: ignoring line-scoped confirmation for %s - it is "
                "not a line-scoped fact", fk)
            continue
        scoped_edits.append((fk, scope, str(raw)))
    if _apply_scoped_confirmations(out, scoped_edits):
        # The line records and `_scoped` are DERIVED from `coverage_lines`, so
        # they must be rebuilt or the picker would keep comparing against the
        # values the producer just corrected.
        try:
            from services.extraction_service import _build_scoped_fact_store
            _build_scoped_fact_store(out, docs)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("underwriting: scope store rebuild skipped - %s", exc)
    for fact_key, raw in confirmations.items():
        if SCOPED_CONFIRM_SEPARATOR in str(fact_key):
            continue                       # handled above; never a package scalar
        cfg = _resolve_reconcilable_cfg(fact_key, docs)
        if cfg is None or raw is None:
            continue
        envelope = {
            "value":      str(raw),
            "confidence": _CONFIRMED_CONFIDENCE,
            "source":     _CONFIRMED_SOURCE,
        }
        # Beta Report §4.3 item 5: store the normalized canonical alongside the
        # raw string as additive provenance, so any consumer that wants a clean
        # number has one without re-parsing. The raw ``value`` is preserved
        # unchanged — what gets stamped onto forms and read by scoring is
        # untouched (display fidelity); this key is metadata only.
        norm = _normalize(raw, cfg["kind"], fact_key)
        if norm:
            envelope["normalized"] = norm
        out[fact_key] = envelope
    # A confirmed key is resolved: its held client candidate (F7) is released.
    _cc = out.get("_client_answer_conflicts")
    if isinstance(_cc, dict):
        remaining = {k: v for k, v in _cc.items() if k not in confirmations}
        if remaining:
            out["_client_answer_conflicts"] = remaining
        else:
            out.pop("_client_answer_conflicts", None)
    return out


def validate_confirmation(fact_key: str, value: Any, docs: Optional[List[dict]] = None) -> Optional[str]:
    """Validate a confirm request. Returns a canonicalized display value, or
    raises ValueError with a stable code the route can translate.

    ``docs`` is required to validate an auto-discovered (non-curated) field —
    see ``_resolve_reconcilable_cfg``.
    """
    cfg = _resolve_reconcilable_cfg(fact_key, docs)
    if cfg is None:
        raise ValueError("underwriting_unknown_field")
    if value is None or str(value).strip() == "":
        raise ValueError("underwriting_empty_value")
    if _is_form_number_policy_value(fact_key, str(value).strip()):
        raise ValueError("underwriting_invalid_value")
    kind = cfg["kind"]
    # A confirmed value must parse with the field's NATIVE normalizer (no text
    # fallback): confirming Gross Sales requires a real number, not free text;
    # confirming an identity field must carry usable signal after WS-2
    # normalization (e.g. a bare "LLC" as an applicant name normalizes to '').
    if kind == "currency":
        norm = _normalize_currency(value)
    elif kind == "integer":
        norm = _normalize_integer(value)
    elif kind == "identity":
        norm = normalize_value(fact_key, value)
    else:
        norm = _normalize_text(value)
    if not norm:
        raise ValueError("underwriting_invalid_value")
    # A confirmed Yes/No is stored in ITS canonical printing (SYS-07). The
    # producer confirming the certificate's "X" is confirming the answer, not
    # the mark - and this value is what gets stamped onto every form.
    try:
        from services.normalization import is_yes_no_field, canonical_yes_no
        if is_yes_no_field(fact_key):
            canon = canonical_yes_no(value)
            if canon:
                return canon
    except Exception:                                        # noqa: BLE001
        pass
    return str(value).strip()


def verify_stamped_consistency(
    generated_forms: Optional[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Post-generation cross-form assertion (Beta Report §4.3 action item 2).

    After all selected forms are generated, read the value ACTUALLY stamped into
    every form for each reconcilable currency/integer field and confirm they all
    agree (after normalization) with the expected figure — the user-confirmed
    value when one exists, otherwise the merged-facts value.

    A disagreement is logged as a warning and returned; this check NEVER mutates
    a form, changes a value, or blocks the response — it is a safety assertion
    that the deterministic stamping stayed consistent with the confirmed figure.

    Only genuinely numeric stamped values are compared (the field's native
    normalizer must parse them), so a field shared with another rule that holds a
    non-numeric value can never raise a false mismatch.

    Returns
    -------
    {"checked": int, "mismatches": [ {fact_key, label, form_id, field,
     expected, stamped} ], "ok": bool}
    """
    generated_forms = generated_forms or {}
    merged_facts    = merged_facts or {}
    confirmations   = confirmations or {}

    try:
        from services.pdf_service import fact_to_form_fields, box_expectation
    except Exception as exc:                              # pragma: no cover
        logger.warning("verify_stamped_consistency: pdf_service unavailable — %s", exc)
        return {"checked": 0, "mismatches": [], "ok": True}

    def _norm_native(value: Any, kind: str) -> Optional[str]:
        if kind == "currency":
            return _normalize_currency(value)
        if kind == "integer":
            return _normalize_integer(value)
        return None

    mismatches: List[dict] = []
    checked = 0

    for fact_key, cfg in RECONCILABLE_FIELDS.items():
        kind = cfg["kind"]
        if kind not in ("currency", "integer"):
            continue

        # Expected = confirmed value if present, else the merged-facts value.
        expected_raw = confirmations.get(fact_key)
        if expected_raw is None:
            expected_raw = _fv(merged_facts, fact_key)
        if expected_raw is None:
            continue
        expected_norm = _norm_native(expected_raw, kind)
        if not expected_norm:
            continue

        form_fields = fact_to_form_fields(fact_key)
        if not form_fields:
            continue

        for form_id, form_result in generated_forms.items():
            # Prefer the CURRENT edited field_state (set by the post-generation
            # field-edit path) over the original generation mapping, so a manual
            # edit that diverges one form from the others is checked too. At
            # generation time there is no field_state, so this falls back to
            # mapped — identical to the original behaviour.
            fr     = form_result or {}
            mapped = fr.get("field_state") or fr.get("mapped") or {}
            for field in form_fields.get(form_id, ()):
                val = mapped.get(field)
                if val is None or str(val).strip() in ("", "null", "None"):
                    continue
                vnorm = _norm_native(val, kind)
                if not vnorm:
                    # Stamped value is not a number of this kind → not this
                    # fact's value; skip (no false mismatch).
                    continue
                # ONE DOOR, shared with Field QA (`pdf_service.box_expectation`):
                # a box its OWNER resolves - a section form's own line, a
                # per-vehicle cell - is compared with the owner's value, and an
                # owned blank with nothing. This compared every box with the
                # package figure alone.
                try:
                    exp = box_expectation(form_id, field, fact_key, expected_raw,
                                          merged_facts, fr.get("schema") or {})
                except Exception:                         # noqa: BLE001
                    exp = ("value", expected_raw)
                if not exp or exp[0] != "value":
                    continue
                want_norm = _norm_native(exp[1], kind)
                if not want_norm:
                    continue
                checked += 1
                if vnorm != want_norm:
                    mismatches.append({
                        "fact_key": fact_key, "label": cfg["label"],
                        "form_id":  form_id,   "field": field,
                        "expected": str(exp[1]), "stamped": str(val),
                    })

    if mismatches:
        logger.warning(
            "underwriting_consistency: post-generation stamp MISMATCH on %d field-value(s) — %s",
            len(mismatches),
            "; ".join(
                f"{m['label']} on {m['form_id']} stamped {m['stamped']!r} != expected {m['expected']!r}"
                for m in mismatches
            ),
        )
    else:
        logger.info(
            "underwriting_consistency: post-generation stamp check OK "
            "(%d field-value(s) verified across %d form(s))",
            checked, len(generated_forms),
        )

    return {"checked": checked, "mismatches": mismatches, "ok": not mismatches}


def stamp_mismatch_issues(stamp_check: Optional[dict]) -> List[dict]:
    """Translate a :func:`verify_stamped_consistency` result into cross-issue
    dicts (shape ``{type, code, message, forms}``) so a cross-form stamp
    discrepancy is surfaced to the user through the existing cross-issues channel
    on the generation screen (Beta Report §4.3 "…or forms").

    Returns ``[]`` when there are no mismatches, so the normal case adds nothing.
    One issue per field, listing the forms involved. Display only — callers must
    NOT feed these into SQS scoring.
    """
    if not stamp_check or stamp_check.get("ok", True):
        return []
    by_fact: Dict[tuple, set] = {}
    for m in stamp_check.get("mismatches") or []:
        by_fact.setdefault((m.get("fact_key"), m.get("label")), set()).add(m.get("form_id"))
    issues: List[dict] = []
    for (fact_key, label), forms in by_fact.items():
        flist = sorted(f for f in forms if f)
        pretty = ", ".join(f.replace("ACORD_", "ACORD ") for f in flist)
        issues.append({
            "type":    "soft_warning",
            "code":    "underwriting_stamp_mismatch",
            "message": (
                f"{label or fact_key} appears inconsistently across generated forms "
                f"({pretty}). Re-confirm the value so it applies uniformly."
            ),
            "forms":   flist,
        })
    return issues
