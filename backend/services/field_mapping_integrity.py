"""field_mapping_integrity.py

Field-mapping integrity guard (Figure 33 client feedback).

The client flagged a specific, high-risk mapping bug on the auto forms: carrier
names ("EMCASCO Insurance Company", "Employers Mutual Casualty Company") were
being pulled into vehicle OWNER-name boxes, and asked that auto ownership, HNOA,
leasing, hazardous-materials and vehicle-maintenance questions be treated as
HIGH-IMPACT and never "inferred loosely" - plus:

    "Show a warning for carrier/policy data mapped into insured/owner fields,
    on both the pre-download SQS review screen and the post-download screen -
    never block the download itself."

This module is the generic, form-agnostic engine behind both asks. It is PURE
(no DB, no I/O, no network - easy to unit-test) and has three responsibilities:

1. CLASSIFY high-impact fields (:func:`is_high_impact_field`). ``field_qa`` uses
   this to surface a loosely-inferred high-impact field individually in the
   pre-download review instead of rolling it into the generic summary.

2. DETECT contamination (:func:`detect_field_mapping_contamination`) - a
   carrier/policy value stamped into an insured/owner field.

3. PRESENT findings as warning rows (:func:`to_recommendation_rows`) in the same
   shape/channel ``field_qa`` already uses. ``audit_service.run_and_log_field_mapping_check``
   runs this unconditionally (no feature flag) right after form generation and
   writes the rows into ``sqs_recommendation_audit``, so they appear automatically
   on both the pre-download preflight modal and the post-download checklist - the
   same rows, no separate download-time check needed. Always advisory: the
   producer can always proceed via "Download Anyway"; nothing here ever blocks.

Design notes
------------
* Comparison uses the SHARED normalizer (services.normalization.normalize_value /
  normalize_carrier / normalize_name), so a formatting-only difference is never a
  match - only a genuine one is. This is the same equivalence used everywhere
  else, so behaviour is consistent with the cross-document detectors.
* GENERIC - the field roles are inferred from the ACORD field-NAME shape rather
  than hardcoded per form. Every one of the 17 forms in forms_schemas/*.json was
  swept (not sampled) for name-bearing identity fields and Yes/No high-impact
  questions; coverage is verified against the REAL field names and REAL tooltip
  text (not assumed):
    Owner/insured identity - ACORD 125/126/127/140/160/28
    (AdditionalInterest_FullName_*), 130 (WorkersCompensation_Individual_FullName_*,
    the officer/partner/owner schedule), 133
    (WorkersCompensationNoticeOfAssignment_EmployerOrganization_FullName_*,
    Location_FullName_*), 131 (CommercialStructure_Location_FullName_*), and 25
    (CertificateHolder_FullName_*).
    High-impact questions - ownership/HNOA/leasing/hazmat/maintenance phrasing
    verified on 125/126/127/130/131/133/137_CA/137_CO/138_CA/138_CO/141/160/25/186
    (11+ forms use "leasing" language, 7 use hired/non-owned, 6 use hazardous
    material). Three ACORD synonyms for the same HNOA concept are recognized:
    "hired and non-owned" (131), "hired auto[s]"/"non-owned auto[s]" (25/137/
    138/160 - note SINGULAR "auto", which the original phrases copied from 131
    did not match), and "hired / borrowed" (137_CA/137_CO).
  Deliberately excluded after the same evidence-based check: driver names,
  employee names, auditor names, parent/subsidiary organization names - present
  on several forms, but none of them define WHO the coverage is for or WHO owns
  the covered property, so a mismapped carrier name there is a different (lower-
  severity) risk than the one this module targets.
  A field role NOT on this list (e.g. a future ACORD revision's own naming
  convention for an owner-equivalent slot) will silently NOT be covered until its
  real field name is checked and added here - this module does not discover new
  patterns on its own.
* PRECISE - an insured field that correctly holds the applicant name is exempt
  even if that name happens to look carrier-ish, so a real insured is never
  flagged. A finding fires only when the value is carrier/policy data that does
  NOT belong in that slot.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from services.normalization import normalize_carrier, normalize_name

logger = logging.getLogger(__name__)

FIELD_MAPPING_INTEGRITY_MODEL_VERSION = "1.0.0"

# Extraction fact keys that hold CARRIER names. A value equal (after
# normalization) to one of these must never sit in an insured/owner field.
# "wc_prior_carrier" is the Workers Comp prior-carrier fact (ACORD 130) - a
# real fact_registry key that fed the same class of bleed risk into the WC
# officer/owner schedule but was missing from this list (found in audit).
_CARRIER_FACT_KEYS = ("carrier_name", "prior_carrier", "current_carrier", "wc_prior_carrier")

# Extraction fact keys that hold POLICY identifiers.
_POLICY_FACT_KEYS = ("policy_number", "prior_policy_number")

# A stamped value is treated as a plausible policy-number match only when it is
# reasonably distinctive, so a short coincidental token can never manufacture a
# false warning.
_MIN_POLICY_TOKEN_LEN = 5

# Carrier-defining words + a company/entity token = a value SHAPED like a carrier
# name, caught even when no extracted carrier fact matches it (the Figure 33
# owner boxes held raw carrier strings the LLM read straight from the document).
_CARRIER_WORD_RX = re.compile(
    r"\b(insurance|casualty|mutual|indemnity|assurance|reinsurance|underwriters|surety)\b",
    re.IGNORECASE,
)
_COMPANY_WORD_RX = re.compile(
    r"\b(co|company|companies|corp|corporation|inc|incorporated|group|ins)\b",
    re.IGNORECASE,
)


# ── Value helpers ─────────────────────────────────────────────────────────────

def _fv(facts: dict, key: str):
    """Scalar fact value, unwrapping the {value, confidence} envelope."""
    if not isinstance(facts, dict):
        return None
    v = facts.get(key)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return None
    return v


def _has_value(v: Any) -> bool:
    return v is not None and str(v).strip() not in ("", "null", "None")


def _policy_token(value: Any) -> str:
    """Comparison token for a policy identifier: alphanumeric, upper-cased."""
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _humanize_field(field: str) -> str:
    """Light humanization of an ACORD field name for a review message."""
    base = field or ""
    if len(base) > 2 and base[-2] == "_" and base[-1].isalpha():
        base = base[:-2]          # drop a trailing row letter (_A/_B/...)
    return base.replace("_", " ").strip()


def _form_label(form_id: str) -> str:
    return (form_id or "").replace("ACORD_", "ACORD ")


# ── Field-role classification (from the field NAME shape) ─────────────────────

# Name-bearing suffixes: the field holds the NAME of an entity (not an address,
# city, phone, code, ...). Used to keep address/city/contact sub-fields out of
# the insured/owner identity role even though they contain the word "name".
_NAME_SUFFIX_TOKENS = ("fullname", "dbaname", "tradename", "businessname")

# Address / contact / code markers that disqualify a field from being an
# insured/owner NAME field even if it contains "name" (e.g. CityName).
_NON_IDENTITY_MARKERS = (
    "address", "city", "state", "postal", "zip", "phone", "fax", "email",
    "website", "naic", "fein", "taxid", "code", "date", "indicator",
)


def _fl(field_name: Optional[str]) -> str:
    return (field_name or "").lower()


def is_insured_owner_field(field_name: Optional[str]) -> bool:
    """True when the field is meant to hold the name of an entity that DEFINES
    the coverage relationship: who the coverage is FOR, who OWNS the covered
    property, or who is OWED proof of coverage.

    These are the slots the client said must never receive carrier/policy data.
    Recognized generically from the field-name shape so it covers every form:
      * the named insured / applicant / insured name,
      * an explicit vehicle/business OWNER name,
      * an additional-interest name (the ACORD 127 "Name of Other Owner" boxes),
      * a WC officer/partner/owner schedule entry (ACORD 130
        ``WorkersCompensation_Individual_FullName_*`` - verified against the real
        schema tooltip: "the full name of the partner or executive officer..."),
      * a PEO Notice-of-Assignment employer identity (ACORD 133
        ``...EmployerOrganization_FullName_*`` - tooltip: "the full name of the
        employer organization (PEO)"),
      * a covered location's name when it may BE the insured business (ACORD 131
        ``CommercialStructure_Location_FullName_*`` / ACORD 133
        ``Location_FullName_*`` - tooltip: "...this may be a company name" /
        "...list the company name..."),
      * a certificate holder (ACORD 25 ``CertificateHolder_FullName_*``) - the
        third party OWED proof of coverage, same risk class as an additional
        interest: the wrong name here misrepresents who the coverage runs to.

    Deliberately excludes person/entity names that appear ON a form but do NOT
    define the coverage relationship - a driver, an employee, an auditor, a
    parent/subsidiary organization. A carrier name in one of THOSE fields is
    still sloppy, but it does not misstate who is insured, who owns what is
    insured, or who is owed proof - so it is out of this module's scope.

    Address, city, contact and code sub-fields are excluded even when their name
    contains "name" (e.g. ``...MailingAddress_CityName``).
    """
    fl = _fl(field_name)
    if not fl:
        return False
    if any(m in fl for m in _NON_IDENTITY_MARKERS):
        return False
    if not any(tok in fl for tok in _NAME_SUFFIX_TOKENS):
        return False
    # "insurer" is the CARRIER field - never treat it as an insured/owner slot.
    if "insurer" in fl and "insured" not in fl:
        return False
    return (
        "namedinsured" in fl
        or "insured" in fl
        or "applicant" in fl
        or "owner" in fl
        or "additionalinterest" in fl
        # WC officer/partner/owner schedule row. Requires BOTH tokens together
        # (not bare "individual") so an unrelated future "...individual..."
        # field on some other form is never swept in by accident.
        or ("workerscompensation" in fl and "individual" in fl)
        or "employerorganization" in fl
        or "location" in fl
        or "certificateholder" in fl
    )


def is_insured_identity_field(field_name: Optional[str]) -> bool:
    """True for the NAMED INSURED / applicant slot specifically (a subset of
    :func:`is_insured_owner_field`). Used to exempt a field that correctly holds
    the applicant name from the carrier-shape heuristic."""
    fl = _fl(field_name)
    if not is_insured_owner_field(field_name):
        return False
    return "namedinsured" in fl or "applicant" in fl or "insured" in fl


# High-impact auto / underwriting questions the client named (Figure 33): auto
# ownership, HNOA (hired & non-owned auto), leasing, hazardous materials, and
# vehicle-maintenance. Matched on the field-name shape, generic across forms.
# "hiredborrowed" added after checking all 17 forms: ACORD 137_CA/137_CO name
# their hired/non-owned indicator checkboxes "Vehicle_HiredBorrowed_YesIndicator_A"
# / "Vehicle_TruckersHiredBorrowed_*" - a synonym for "hired auto" that neither
# "hiredauto" nor "nonowned" would otherwise catch.
_HIGH_IMPACT_AUTO_TOKENS = (
    "nonowned", "non_owned", "hirednonowned", "hiredautomobile", "hiredauto",
    "hiredborrowed", "hazardousmaterial", "hazardous", "leasedtoothers", "leased",
    "lease", "maintenanceprogram", "vehiclemaintenance",
    "solelyowned", "notsolelyowned", "vehicleowner",
)

# ACORD schemas give the Yes/No ANSWER field for each of these questions an
# opaque internal code as its field name (e.g. "Question_AAJCode_A", or a
# numeric-symbol name like "Vehicle_BusinessAutoSymbol_EightIndicator_A" on 137/
# 138) - the human-readable topic exists only in that field's schema tooltip
# ("tu"), not in the field name itself. Only the free-text "...Explanation"
# SIBLING field has a descriptive name, so name-only matching
# (_HIGH_IMPACT_AUTO_TOKENS above) misses the Yes/No answer itself. These
# phrases catch it via the tooltip text instead, so the actual answer - not
# just its explanation - is treated as high-impact.
# Verified against the real schema wording across all 17 forms, e.g.:
#   ACORD_127: "...are any vehicles...not solely owned by and registered to
#               the applicant" / "...vehicle maintenance program in
#               operation?" / "...any vehicles leased to others?" /
#               "...transporting hazardous material?"
#   ACORD_131: "...hired and non-owned coverages provided?"
#   ACORD_141: "...Any employees leased from others?" (the "to others" case was
#               already covered; "from others" was not, until checked directly)
#   ACORD_160/25/137/138: "...hired auto[s]...coverage" / "...non-owned
#               auto[s]...coverage" - SINGULAR "auto" (no trailing "s"), which
#               the original "hired autos"/"non-owned autos" phrases (copied
#               from ACORD 131's plural wording) did NOT match - confirmed by
#               directly grepping the real tooltip text on these forms, not
#               assumed. Fixed by dropping the plural 's' (the singular form is
#               a substring of the plural, so this catches both).
#   ACORD_137_CA/137_CO: "...hired / borrowed coverage..." / "...hired or
#               borrowed..." - a THIRD synonym for the same HNOA concept.
_HIGH_IMPACT_TOOLTIP_PHRASES = (
    "solely owned", "registered to the applicant", "registered to the",
    "leased to others", "leased from others", "hazardous material",
    "vehicle maintenance program",
    "hired and non-owned", "hired and non owned", "hired or non-owned",
    "hired / borrowed", "hired or borrowed",
    "hired auto", "non-owned auto", "nonowned auto",
)


def is_high_impact_field(field_name: Optional[str], tooltip: Optional[str] = None) -> bool:
    """True for a field the client asked be treated as HIGH-IMPACT (Figure 33):
    the insured/owner identity slots plus the auto ownership / HNOA / leasing /
    hazardous-materials / maintenance questions. ``field_qa`` uses this to
    surface a loosely-inferred value here individually rather than in a rollup.

    ``tooltip`` is the field's schema description (schema[field]["tu"]), passed
    by the caller when available. It is what catches the bare Yes/No ANSWER
    field for these questions (opaquely-coded field name, descriptive tooltip
    only) - without it, only the free-text Explanation sibling is recognized.
    """
    if is_insured_owner_field(field_name):
        return True
    fl = _fl(field_name)
    if any(tok in fl for tok in _HIGH_IMPACT_AUTO_TOKENS):
        return True
    tl = (tooltip or "").lower()
    return bool(tl) and any(phrase in tl for phrase in _HIGH_IMPACT_TOOLTIP_PHRASES)


# ── Carrier-shape heuristic ───────────────────────────────────────────────────

def looks_like_carrier(value: Any) -> bool:
    """Heuristic: does ``value`` READ like an insurance carrier's name?

    True when it carries a carrier-defining word (insurance / casualty / mutual /
    indemnity / ...) together with a company/entity token - the shape of
    "EMCASCO Insurance Company" or "Employers Mutual Casualty Company". Requiring
    BOTH keeps an ordinary business name ("Orbin Contracting LLC") from matching.
    """
    s = str(value or "").strip()
    if not s:
        return False
    return bool(_CARRIER_WORD_RX.search(s) and _COMPANY_WORD_RX.search(s))


def looks_like_policy_number(value: Any) -> bool:
    """Heuristic: does ``value`` READ like a policy number / identifier code?

    The policy-side counterpart to :func:`looks_like_carrier` - catches a
    hallucinated policy/identifier code stamped into an owner/insured field even
    when no extracted policy fact confirms it (closing the asymmetry where the
    carrier side had a shape fallback and the policy side did not).

    A real owner/insured NAME is letter-dominated words; a policy number is a
    compact, DIGIT-dominated alphanumeric token. Conservative on purpose:
    requires a substantial digit run AND digits >= letters, so an ordinary
    business name that merely contains a number ("3M Company", "1st National
    Bank", "84 Lumber", "12345 Holdings LLC") is never mistaken for a policy
    number - only a genuinely code-shaped value ("CPP1234567", "GL 000 123
    456", a bare FEIN/VIN pasted into a name box) matches.
    """
    tok = _policy_token(value)          # alphanumeric-only, uppercased
    if len(tok) < _MIN_POLICY_TOKEN_LEN:
        return False
    digits = sum(c.isdigit() for c in tok)
    letters = sum(c.isalpha() for c in tok)
    return digits >= 4 and digits >= letters


# ── Detection ─────────────────────────────────────────────────────────────────

def _collect_forbidden(merged_facts: dict, confirmations: dict):
    """Build the sets of normalized carrier / policy values that must NOT appear
    in an insured/owner field. Confirmed values take precedence over extracted.
    Each entry maps normalized value -> (raw value, source fact key) so a finding
    can report which fact actually matched instead of a hardcoded key name."""
    carriers: Dict[str, tuple] = {}   # normalized -> (raw, fact_key)
    policies: Dict[str, tuple] = {}
    for key in _CARRIER_FACT_KEYS:
        raw = confirmations.get(key)
        if raw is None:
            raw = _fv(merged_facts, key)
        if raw is None:
            continue
        norm = normalize_carrier(raw)
        if norm:
            carriers.setdefault(norm, (str(raw), key))
    for key in _POLICY_FACT_KEYS:
        raw = confirmations.get(key)
        if raw is None:
            raw = _fv(merged_facts, key)
        if raw is None:
            continue
        tok = _policy_token(raw)
        if len(tok) >= _MIN_POLICY_TOKEN_LEN:
            policies.setdefault(tok, (str(raw), key))
    return carriers, policies


def _classify_value(
    field: str, value: Any, *, carriers: Dict[str, tuple], policies: Dict[str, tuple],
    applicant_norm: str,
) -> tuple:
    """Core single-value contamination check: does ``value`` belong in an
    insured/owner field, or does it look like carrier/policy data?

    Returns ``(reason_code, matched_fact_key, matched_value)`` - all ``None``
    when the value is clean. Pure; the caller has already confirmed
    ``field`` is an insured/owner NAME slot and ``value`` is non-empty.

    SHARED by :func:`detect_field_mapping_contamination` (post-generation,
    whole-package warning) and :func:`is_value_contaminated` (single-field,
    used by pdf_service's fill-time confidence override) so the two can never
    silently drift apart into disagreeing about what counts as contamination.
    """
    sv = str(value).strip()

    # A field that correctly holds the applicant's own name is fine, even if
    # the applicant name happens to look carrier-ish.
    if applicant_norm and is_insured_identity_field(field) and normalize_name(sv) == applicant_norm:
        return None, None, None

    carrier_norm = normalize_carrier(sv)
    policy_tok = _policy_token(sv)

    if carrier_norm and carrier_norm in carriers:
        matched_value, matched_key = carriers[carrier_norm]
        return "carrier_in_insured_owner_field", matched_key, matched_value
    if policy_tok and policy_tok in policies:
        matched_value, matched_key = policies[policy_tok]
        return "policy_in_insured_owner_field", matched_key, matched_value
    if looks_like_carrier(sv):
        return "carrier_shaped_value_in_insured_owner_field", None, None
    if looks_like_policy_number(sv):
        return "policy_shaped_value_in_insured_owner_field", None, None
    return None, None, None


def is_value_contaminated(
    field_name: str,
    value: Any,
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> bool:
    """True when ``value`` looks like carrier/policy data that does not belong
    in ``field_name`` (an insured/owner NAME slot).

    Single-VALUE entry point (as opposed to :func:`detect_field_mapping_contamination`,
    which scans a whole ``generated_forms`` dict) - used by pdf_service at FILL
    TIME to force an owner/insured field to ``low_confidence`` (reviewable,
    never blanked) when its value is contamination-shaped, REGARDLESS of how it
    was filled (deterministic rule, alias stamp, or GPT). A deterministic rule
    is not automatically safe here: e.g. CertificateHolder_FullName has its own
    rule pulling from the "certificate_holder" fact, a different key from
    "carrier_name" - if that fact happens to hold the carrier's name (a
    document that lists the same company as both), the field is still wrong,
    even though it was never touched by GPT. Uses the exact same classification
    as the post-generation warning (:func:`_classify_value`), so the two
    mechanisms never disagree.

    Returns False for any field that is not an insured/owner NAME slot, or for
    an empty value - never mutates anything, never raises for ordinary input.
    """
    if not is_insured_owner_field(field_name) or not _has_value(value):
        return False
    merged_facts = merged_facts or {}
    confirmations = confirmations or {}
    carriers, policies = _collect_forbidden(merged_facts, confirmations)
    applicant_norm = normalize_name(
        confirmations.get("applicant_name") or _fv(merged_facts, "applicant_name") or ""
    )
    reason_code, _, _ = _classify_value(
        field_name, value, carriers=carriers, policies=policies, applicant_norm=applicant_norm,
    )
    return reason_code is not None


def _finding_message(label: str, form_id: str, value: str, kind: str, fact_matched: bool) -> str:
    """Warning text for one finding, worded to match its actual certainty.

    A FACT match (the stamped value literally equals the extracted carrier
    name or policy number) is near-certain - state it plainly. A SHAPE-only
    match (looks_like_carrier - no extracted fact confirms it) is a genuine,
    necessary fallback (it is what catches the original Figure 33 case, where
    the LLM's hallucinated carrier name had no corresponding extracted fact to
    compare against) - but it can also fire on a legitimate third party whose
    real legal name happens to be insurance-shaped (a premium finance company,
    an "Insurance Services" subsidiary acting as a lienholder). Hedging the
    wording for that case doesn't weaken detection - the finding still fires,
    still shows up as a warning to review - it just doesn't overstate certainty
    the system doesn't have.
    """
    form_label = _form_label(form_id)
    if fact_matched:
        return (
            f"{label} on {form_label} shows \"{value}\", which matches your {kind} "
            f"information, not the insured/owner. Review and correct this field "
            "before sending the package to a carrier."
        )
    if kind == "policy":
        return (
            f"{label} on {form_label} shows \"{value}\", which reads like a policy "
            "number or identifier code, not an owner/insured name. If this is "
            "genuinely the correct value for this field, no action is needed - "
            "otherwise, correct it before sending the package to a carrier."
        )
    return (
        f"{label} on {form_label} shows \"{value}\", which reads like an insurance "
        f"{kind}'s name. If this is really the correct name for this field (e.g. a "
        "lienholder or certificate holder whose own name contains an insurance-"
        "related word), no action is needed - otherwise, correct it before sending "
        "the package to a carrier."
    )


def detect_field_mapping_contamination(
    generated_forms: Optional[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Detect carrier/policy data stamped into an insured/owner field.

    Parameters mirror ``field_qa.run_field_qa`` so the same generation result and
    facts can be passed straight through.

    Returns
    -------
    {
      "review_required": bool,          # True -> at least one warning to show
      "checked": int,                   # insured/owner field-values inspected
      "findings": [ {form_id, field, field_label, value, reason_code, message,
                     matched_fact_key, matched_value}, ... ],
      "message": str,                   # one-line rollup for the 409 detail
      "model_version": str,
    }

    A finding fires ONLY when a value that does not belong in the slot is
    present: it equals an extracted/confirmed carrier or policy value, or it is
    SHAPED like a carrier name and is not the applicant's own name. Nothing is
    mutated; this is a read-only assertion.
    """
    generated_forms = generated_forms or {}
    merged_facts = merged_facts or {}
    confirmations = confirmations or {}

    carriers, policies = _collect_forbidden(merged_facts, confirmations)
    applicant_norm = normalize_name(
        confirmations.get("applicant_name") or _fv(merged_facts, "applicant_name") or ""
    )

    findings: List[dict] = []
    checked = 0

    for form_id, fr in generated_forms.items():
        fr = fr or {}
        # Prefer the CURRENT edited field_state over the original mapping, so a
        # field the producer fixed is re-evaluated and no longer flagged.
        mapped = fr.get("field_state") or fr.get("mapped") or {}

        for field, val in mapped.items():
            if not is_insured_owner_field(field) or not _has_value(val):
                continue
            checked += 1
            sv = str(val).strip()

            reason_code, matched_fact_key, matched_value = _classify_value(
                field, val, carriers=carriers, policies=policies, applicant_norm=applicant_norm,
            )
            if reason_code is None:
                continue

            label = _humanize_field(field)
            kind = "policy" if reason_code.startswith("policy") else "carrier"
            findings.append({
                "form_id":          form_id,
                "field":            field,
                "field_label":      label,
                "value":            sv,
                "reason_code":      reason_code,
                "matched_fact_key": matched_fact_key,
                "matched_value":    matched_value,
                "message": _finding_message(label, form_id, sv, kind, matched_fact_key is not None),
            })

    review_required = bool(findings)
    if review_required:
        logger.warning(
            "field_mapping_integrity: %d contamination finding(s) across %d form(s): %s",
            len(findings), len(generated_forms),
            "; ".join(f"{f['field']} on {f['form_id']} = {f['value']!r}" for f in findings),
        )

    if not findings:
        message = ""
    elif len(findings) == 1:
        message = findings[0]["message"]
    else:
        message = (
            f"{len(findings)} insured/owner field(s) appear to contain carrier or policy "
            "data. Review and correct them before sending the package to a carrier."
        )

    return {
        "review_required": review_required,
        "checked":         checked,
        "findings":        findings,
        "message":         message,
        "model_version":   FIELD_MAPPING_INTEGRITY_MODEL_VERSION,
    }


# ── Presentation: findings -> pre-download / post-download warning rows ───────
# Advisory only, same as field_qa.to_recommendation_rows: these rows are shown
# to the producer on the pre-download SQS review screen and the post-download
# checklist screen, but never block the download itself.

def _rec_id(*parts: str) -> str:
    """Stable, collision-safe rec id from its parts (so re-runs dedupe)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p) for p in parts if p))
    return f"fieldmap_{slug.strip('_')[:80]}"


# A trailing single- or double-letter row suffix (_A, _B, ... _AA, _AB, ...) -
# ACORD's repeating-schedule convention (e.g. AdditionalInterest_FullName_A/B/
# C/D, a WC officer schedule with up to 4 slots). Used ONLY to GROUP findings
# for display when the SAME bad value repeats across several slots of the
# SAME underlying field; never affects detection itself.
_ROW_SUFFIX_STRIP_RE = re.compile(r"_[A-Z]{1,2}$")


def _base_field_for_grouping(field: str) -> str:
    return _ROW_SUFFIX_STRIP_RE.sub("", field or "")


def to_recommendation_rows(result: Optional[dict]) -> List[dict]:
    """Translate a :func:`detect_field_mapping_contamination` result into rows
    for the existing pre-download / post-download review (the same
    sqs_recommendation_audit channel field_qa already uses). Each DISTINCT
    contamination finding is surfaced INDIVIDUALLY (never rolled into a
    summary count) since a carrier/policy value sitting in an insured/owner
    field is exactly the kind of specific, actionable item a producer needs to
    see and fix before sending the package to a carrier - never blocking,
    always visible.

    Findings sharing the same form + underlying field (row suffix stripped) +
    reason + contaminated VALUE merge into a single row with a count (client
    feedback 2026-07-16: "don't want to see a flood of notifications") - this
    is the genuine "same bad value repeated across N repeating slots" case
    (e.g. one carrier name bleeding into AdditionalInterest_FullName_A AND
    _B). Findings that differ in VALUE stay separate rows even on the same
    base field, since each names a different specific problem the producer
    must independently review - collapsing those would hide which field holds
    which bad value, the opposite of what this channel exists to surface.
    """
    if not result:
        return []
    rows: List[dict] = []
    groups: Dict[tuple, dict] = {}
    order: List[tuple] = []
    for f in result.get("findings") or []:
        form_id = f.get("form_id")
        key = (form_id, _base_field_for_grouping(f.get("field")), f.get("reason_code"), f.get("value"))
        if key not in groups:
            order.append(key)
            groups[key] = {"fields": [], "sample": f}
        groups[key]["fields"].append(f.get("field"))

    for key in order:
        form_id, base_field, reason_code, value = key
        grp = groups[key]
        fields = grp["fields"]
        n = len(fields)
        sample = grp["sample"]
        if n == 1:
            message = sample.get("message")
        else:
            label = sample.get("field_label") or _humanize_field(base_field)
            form_label = _form_label(form_id)
            message = (
                f"{label} on {form_label}: the same value \"{value}\" appears in {n} "
                "insured/owner fields. Review and correct each before sending the "
                "package to a carrier."
            )
        rows.append({
            "rec_id":       _rec_id(form_id, base_field, reason_code, value, "grp" if n > 1 else ""),
            "message":      message,
            "type":         "suggestion",
            "field":        fields[0] if n == 1 else None,
            "component":    form_id,
            "score_impact": None,
        })
    return rows


# ── A PARTY BOX MUST HOLD A PARTY ────────────────────────────────────────────
# Client 2026-09-11 item 8: *"'For Informational Purposes Only' was populated as
# an Additional Interest. That phrase came from the COI and is not a person or
# organization. We need entity validation before text can populate an Additional
# Interest, Loss Payee, Lienholder, etc."*
#
# ROOT CAUSE: there is no entity validation anywhere. Measured - of the six
# facts that feed the 65 party-name boxes across the 17 schemas,
# `certificate_holder`, `additional_named_insureds`, `loss_payee_name`,
# `mortgagee_name` and `dba_name` all carry ``validate = None``. Whatever string
# extraction grabs becomes a named party on a legal document.
#
# WHY THIS IS NOT A PHRASE LIST. The 2026-08-08 Data Consistency defect is the
# standing lesson: three successive denylists each closed the reported sentence
# and left the next phrasing free (see `underwriting_consistency._scan_shape`).
# So the test is STRUCTURAL - a party name is a NOUN PHRASE, and boilerplate is
# a CLAUSE:
#
#   * it opens with a preposition, demonstrative or verb  ("For ...", "This ...")
#   * it closes on a qualifying adverb                    ("... Only")
#   * it contains a finite verb                           ("... IS ISSUED ...")
#
# Any one of those is disqualifying, and a name must ALSO carry a positive
# signal (a legal suffix, or proper-noun shape). Two conditions, per the H1-F
# rule that a necessary test needs a structural second one.
#
# Companion to `is_party_role_label` (a ROLE is not a party) and
# `_rejects_role_or_arrangement`, which already catch "Certificate Holder",
# "See Attached", "Various" and "N/A". This catches the clause shape they miss.

_PARTY_LEGAL_SUFFIX_RX = re.compile(
    r"\b(l\.?l\.?c|inc|incorporated|corp|corporation|co|company|companies|ltd|"
    r"limited|l\.?p|l\.?l\.?p|p\.?l\.?l\.?c|p\.?c|p\.?a|plc|trust|bank|banking|"
    r"association|assn|authority|district|agency|university|college|academy|"
    r"hospital|church|foundation|partnership|holdings|group|enterprises|"
    r"services|properties|leasing|finance|financial|credit\s+union|fcu|n\.?a|"
    r"municipality|city|county|state|department|dept|board|commission|"
    r"cooperative|co-?op|institute|society|club|estate|lp)\b", re.I)

# Openers a NOUN PHRASE never begins with. Articles are deliberately absent -
# "The Bank of New York Mellon" is a party.
_PARTY_CLAUSE_OPENERS = frozenset({
    "for", "in", "on", "at", "by", "with", "to", "from", "as", "per", "if",
    "when", "while", "where", "subject", "see", "refer", "this", "that",
    "these", "those", "such", "any", "all", "each", "every", "none", "no",
    "not", "is", "are", "was", "were", "will", "shall", "should", "must",
    "may", "can", "does", "do", "did", "has", "have", "had", "been", "being",
    "please", "note", "including", "included", "except", "unless", "pursuant",
    "regarding", "re", "insured", "coverage", "certificate", "policy",
})

# Tails a NOUN PHRASE never ends on.
_PARTY_CLAUSE_TAILS = frozenset({
    "only", "applicable", "required", "attached", "below", "above", "herein",
    "thereof", "hereof", "purposes", "needed", "requested", "noted", "shown",
    "listed", "stated", "provided", "issued", "endorsed", "waived", "apply",
    "applies", "necessary", "available", "pending", "tbd", "unknown",
    # A document's own copy marker: "Agency Copy", "Insured Copy", "File Copy".
    "copy", "copies",
})

_PARTY_FINITE_VERB_RX = re.compile(
    r"\b(is|are|was|were|shall|will|would|should|must|may|can|does|do|did|"
    r"has|have|had|been|being|provides?|applies|apply|includes?|excludes?|"
    r"covers?|constitutes?|evidences?|confers?|amends?|extends?|remains?)\b",
    re.I)

_PARTY_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'&./-]*")
_PARTY_ARTICLES = frozenset({"the", "a", "an"})
_RUN_TOGETHER_BOUNDARY_RX = re.compile(r"(?<=[a-z])(?=[A-Z])")

# Words a certificate prints ABOUT itself - its status, not a party. With
# ACORD's own field vocabulary they make the look-alike placeholders: "Proof
# of Insurance", "Sample Certificate", "Holder of Record", "Evidence Only".
_DOCUMENT_STATUS_WORDS = frozenset({
    "proof", "evidence", "sample", "specimen", "copy", "copies", "record",
    "records", "informational", "information", "purposes", "purpose",
    "reference", "void", "draft", "file", "ongoing",
})
_VOCAB_CONNECTORS = frozenset({
    "the", "of", "and", "a", "an", "for", "to", "in", "on", "at", "by", "or"})
_ACORD_VOCAB_CACHE: List[frozenset] = []


def _acord_vocabulary():
    """(field-name words, tooltip words) of the 17 ACORD schemas - ACORD's own
    vocabulary, read once. Empty sets when the schemas cannot be read, which
    simply switches both vocabulary rules off."""
    if not _ACORD_VOCAB_CACHE:
        import json as _json
        import os as _os
        field_words, tip_words = set(), set()
        try:
            folder = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))), "forms_schemas")
            for name in sorted(_os.listdir(folder)):
                if not name.endswith("_schema.json"):
                    continue
                with open(_os.path.join(folder, name), encoding="utf-8") as fh:
                    schema = _json.load(fh)
                for field, meta in (schema.items() if isinstance(schema, dict) else []):
                    field_words.update(
                        w.lower() for w in re.findall(r"[A-Z][a-z]+", str(field)))
                    if isinstance(meta, dict):
                        tip_words.update(w for w in re.findall(
                            r"[a-z]+", str(meta.get("tu") or "").lower()) if len(w) >= 2)
        except Exception:                                     # noqa: BLE001
            field_words, tip_words = set(), set()
        _ACORD_VOCAB_CACHE.extend([frozenset(field_words), frozenset(tip_words)])
    return _ACORD_VOCAB_CACHE[0], _ACORD_VOCAB_CACHE[1]


def _segment_glued_caps(token: str) -> Optional[List[str]]:
    """Split an ALL-CAPS (or all-lower) glued token into ACORD vocabulary words,
    or None when it does not split cleanly: FORINFORMATIONALPURPOSESONLY ->
    for / informational / purposes / only; KESTRELTERMINALAUTHORITY -> None."""
    _fields, tips = _acord_vocabulary()
    if not tips:
        return None
    vocab = tips | _DOCUMENT_STATUS_WORDS | _VOCAB_CONNECTORS
    t = token.lower()
    best: List[Optional[List[str]]] = [None] * (len(t) + 1)
    best[0] = []
    for i in range(2, len(t) + 1):
        for j in range(max(0, i - 24), i - 1):       # every piece >= 2 letters
            if best[j] is None:
                continue
            piece = t[j:i]
            if piece in vocab or (len(piece) > 3 and piece.endswith("s")
                                  and piece[:-1] in vocab):
                if best[i] is None or len(best[j]) + 1 < len(best[i]):
                    best[i] = best[j] + [piece]
    return best[len(t)]


def _respace_run_together(head: str) -> str:
    """Re-space ONE token that OCR glued together from several words.

    The Orbin certificate's OCR prints its holder box as
    ``ForInformationalPurposesOnly`` - one token, so the clause test saw a
    single capitalised word and called it a name. A mixed-case token splits at
    its capitals; an ALL-CAPS one (``FORINFORMATIONALPURPOSESONLY``) splits into
    ACORD's own vocabulary or not at all - a real name such as
    ``KESTRELTERMINALAUTHORITY`` does not split. Only a split into THREE or more
    words is used, so ``OrbinContracting`` or ``CRSInsurance`` are judged
    exactly as before. A glued LEGAL name (``InTownSuitesLLC``) stays one token
    - re-spaced it would open on "In" and read as a clause.
    """
    if not head or any(ch.isspace() for ch in head):
        return head
    if _RUN_TOGETHER_BOUNDARY_RX.search(head):
        spaced = _RUN_TOGETHER_BOUNDARY_RX.sub(" ", head)
    elif len(head) >= 12 and head.isalpha() and (head.isupper() or head.islower()):
        pieces = _segment_glued_caps(head)
        spaced = " ".join(p.capitalize() for p in pieces) if pieces else head
    else:
        return head
    if len(spaced.split()) < 3 or _PARTY_LEGAL_SUFFIX_RX.search(spaced):
        return head
    return spaced


def _made_only_of_form_words(head: str) -> bool:
    """A third-party "name" built ONLY from ACORD's own field vocabulary and a
    certificate's status words names nobody: "Proof of Insurance", "Sample
    Certificate", "Holder of Record", "Commercial General Liability".

    Measured before shipping: 0 of the 547 real party names stored in the
    database are refused. A suffix-less "Commercial Credit" would be - a blank
    box the producer fills, never a wrong party on the form.
    """
    field_words, _tips = _acord_vocabulary()
    if not field_words:
        return False
    toks = [w for w in re.findall(r"[a-z]+", head.lower())
            if w not in _VOCAB_CONNECTORS and w != "s"]
    if not toks:
        return False
    vocab = field_words | _DOCUMENT_STATUS_WORDS
    return all(w in vocab or (w.endswith("s") and w[:-1] in vocab) for w in toks)


def names_a_party(value: Any, third_party: bool = False,
                  respace: Optional[bool] = None) -> bool:
    """Does ``value`` name a person or an organisation?

    Structural, not a phrase list. Returns False for a clause, a disclaimer or
    a fragment; True for a name. An address may ride along after the name (the
    questionnaire asks for "name and address" in one box), so only the part
    before the first comma is judged for shape.

    ``third_party`` (14 Sep 2026) is for a box or fact that names someone OTHER
    than the insured - certificate holder, additional interest, loss payee,
    mortgagee, lienholder. There a glued OCR token is re-spaced before the
    shape test (see `_respace_run_together`), and a "name" made only of ACORD's
    own form vocabulary is refused (see `_made_only_of_form_words`). Off by
    default, so the insured's own name boxes are judged exactly as before.

    ``respace`` defaults to ``third_party``. A GAP-FILLED insured box asks for
    the re-spacing alone: an insured's own name is often ordinary words
    ("Commercial Roofing"), so the vocabulary rule never judges it.
    """
    s = str(value or "").strip().strip('"\u201c\u201d')
    if len(s) < 2:
        return False
    head = s.split(",")[0].strip()
    do_respace = third_party if respace is None else bool(respace)
    if do_respace:
        head = _respace_run_together(head)
    words = _PARTY_WORD_RX.findall(head)
    if not words:
        return False

    lead = [w for w in words if w.lower() not in _PARTY_ARTICLES]
    if not lead:
        return False
    if lead[0].lower().strip(".") in _PARTY_CLAUSE_OPENERS:
        return False
    if words[-1].lower().strip(".") in _PARTY_CLAUSE_TAILS:
        return False
    if _PARTY_FINITE_VERB_RX.search(head):
        return False
    if third_party:
        try:
            from services.normalization import is_party_role_label
            if is_party_role_label(head):
                return False               # "Landlord", "Owner" - a role, not a party
        except Exception:                                     # noqa: BLE001
            pass
    if third_party and not _PARTY_LEGAL_SUFFIX_RX.search(head) \
            and _made_only_of_form_words(head):
        return False

    # Positive signal required - a necessary test needs a sufficient one.
    if _PARTY_LEGAL_SUFFIX_RX.search(head):
        return True
    proper = [w for w in lead if w[:1].isupper() or w.isupper()]
    if len(proper) >= 2:
        return True
    return len(lead) == 1 and len(lead[0]) >= 3 and lead[0][:1].isupper()


def is_party_name_field(field_name: Optional[str]) -> bool:
    """Does this ACORD box hold a party's NAME?

    Derived from ACORD's own naming: a party subject segment
    (AdditionalInterest, CertificateHolder, LossPayee, Mortgagee, NamedInsured,
    AdditionalInsured, Lienholder) followed by a name box.
    """
    f = str(field_name or "")
    if not re.search(r"(FullName|_Name)(_[A-Z])?$", f):
        return False
    return bool(re.match(
        r"^(AdditionalInterest|CertificateHolder|LossPayee|Mortgagee|"
        r"NamedInsured|AdditionalInsured|Lienholder|ThirdParty)", f))
