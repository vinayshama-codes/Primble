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
from typing import Any, Dict, List, Optional

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
    "property_building_value": [
        r"building\s+(?:value|limit|coverage|replacement\s+cost|amount)\s*[:\-–]?\s*"
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
    # ── Extend here (no other code change needed) ────────────────────────────
    # Add a one-line entry: {"label": ..., "kind": "currency"|"integer", "forms": [...]}.
}

# Fields whose conflict is a HARD STOP until the user resolves it (kept blocking
# in check_doc_consistency while unconfirmed; the picker is the resolution path).
# Informational only here — the gating still lives in sqs_service.check_doc_consistency.
HARD_STOP_RECONCILABLE_KEYS = frozenset({
    "applicant_name", "fein", "effective_date", "expiration_date",
})

# Fields whose unresolved conflict must BLOCK form generation until the user
# confirms the correct value (client Property Integrity directive: "Building Value
# Duplication ... generate a warning and require review before forms are
# generated."). This is a generation-time gate only — scoring, recommendations,
# and the questionnaire still run; the confirmation picker is the resolution path.
GENERATION_BLOCKING_RECONCILABLE_KEYS = frozenset({
    "property_building_value",
})

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
    # "identity" routes through the Workstream-2 normalization layer so the
    # picker uses the SAME equivalence rules as the cross-document conflict
    # detectors. normalize_value() dispatches by fact_key (name/date/entity/
    # address/carrier/fein) and returns '' for no-signal → treated as absent.
    if kind == "identity":
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
    if fact_key in ("mailing_address", "physical_address"):
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
    if fact_key == "fein":
        return 1.0 if len(re.sub(r"\D", "", s)) == 9 else 0.0
    if kind == "identity":
        return len(s) * 0.01                              # generic: longer = more descriptive
    return 0.0


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

    if name_like:
        ranked = sorted(values, key=lambda g: (_group_doc_count(g), _completeness(g)), reverse=True)
    else:
        ranked = sorted(values, key=lambda g: (_completeness(g), _group_doc_count(g)), reverse=True)

    top, second = ranked[0], ranked[1]
    top_c, sec_c = _completeness(top), _completeness(second)
    top_docs, sec_docs = _group_doc_count(top), _group_doc_count(second)

    if name_like:
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


def _auto_scalar_keys(docs: List[dict], exclude: set) -> set:
    """Fact keys eligible for generic cross-document reconciliation.

    Any SCALAR fact (not list / dict / bool) present in the documents that is not
    already a curated reconcilable field and not a private/internal ('_'-prefixed)
    key. Determined from the actual values, so it needs no static schema and
    never trips over list/structured facts - those cannot use a two-value picker
    and are intentionally left to the existing detectors.
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
            keys.add(k)
    return keys


# ── Public API ────────────────────────────────────────────────────────────────

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
    confirmations = confirmations or {}

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

    for fact_key, cfg in effective_fields.items():
        kind = cfg["kind"]
        label = cfg["label"]
        is_auto = bool(cfg.get("_auto"))
        assessed_keys.add(fact_key)

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
            raw = _fv(d.get("facts") or {}, fact_key)
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

        confirmed_raw = confirmations.get(fact_key)
        confirmed_value = str(confirmed_raw) if confirmed_raw is not None else None

        # Nothing extracted and nothing confirmed → field not present; skip it.
        if not groups and confirmed_value is None:
            continue

        values = list(groups.values())
        distinct = len(values)

        if confirmed_value is not None:
            status = "confirmed"
            review_required = False
        elif distinct >= 2:
            status = "conflict"
            review_required = True
            conflict_count += 1
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
        if is_auto and status == "consistent":
            continue

        # Figure 3: recommend the most complete/correct value + a confidence level.
        # Only computed for an OPEN conflict — a confirmed/consistent field needs
        # no suggestion. ``preselect`` is True only for HIGH confidence on a
        # non-hard-stop field (the frontend pre-checks that radio).
        suggestion = _suggest_for_field(fact_key, kind, values) if status == "conflict" else None

        fields_out.append({
            "fact_key":        fact_key,
            "label":           label,
            "kind":            kind,
            "forms":           _forms_for_field(fact_key, cfg),
            "status":          status,
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
    out = dict(merged_facts or {})
    for fact_key, raw in confirmations.items():
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
        from services.pdf_service import fact_to_form_fields
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
                checked += 1
                if vnorm != expected_norm:
                    mismatches.append({
                        "fact_key": fact_key, "label": cfg["label"],
                        "form_id":  form_id,   "field": field,
                        "expected": str(expected_raw), "stamped": str(val),
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
