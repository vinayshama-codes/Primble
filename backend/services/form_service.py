#form_service.py

import json
import logging
import os
import re
from typing import Dict, FrozenSet, List, Optional, Tuple

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_INDEX
from services.extraction_service import _fv, _is_empty
from services.pdf_service import extract_form_schema, map_facts_to_form, fill_pdf, _OVERFLOW_CHAR_THRESHOLD
from services.sqs_service import cross_validate, calculate_sqs, _check_loss_run_insured_match, _extract_narrative_doc_text
from utils.validators import US_STATES, run_field_validations

logger = logging.getLogger(__name__)


# ── "Why this form" evidence facts (Beta Report Fig 7) ──────────────────────
# The concrete, already-extracted value that corroborates each form's trigger,
# surfaced next to the recommendation so a producer can validate the detection.
# This is DISPLAY/AUDIT enrichment only - it reads facts that were already
# extracted and NEVER changes which forms are triggered. Each entry:
#   form_id -> ordered list of (fact_key, short_label)
# Each entry: form_id -> {"combine": bool, "facts": [(fact_key, short_label), ...]}.
#   combine=True  → the listed facts are a related SET; when 2+ are present show
#                   them together as "limits a / b" (GL occurrence + aggregate -
#                   the paired-limit presentation the client asked for).
#   combine=False → the listed facts are ALTERNATIVE sources for one value; show
#                   the first one that is present (e.g. WC payroll may live under
#                   total_payroll OR wc_payroll depending on the document).
# Either way, EVERY present fact is recorded in `trigger_facts` for the audit
# trail. All 17 supported forms are covered. When a form has no dedicated value
# fact, the closest real registry fact is used as a proxy (noted inline). Any form
# whose facts are all absent for a given submission falls back to its existing
# generic message unchanged - the merge is never forced.
_FORM_EVIDENCE_FACTS: Dict[str, dict] = {
    # ── Master application - headline underwriting figure ────────────────────
    "ACORD_125": {"combine": False, "facts": [("total_revenue", "Annual revenue"),
                                              ("total_payroll", "Total payroll")]},
    # ── Certificate of Liability - the liability limit being certified ───────
    "ACORD_25":  {"combine": False, "facts": [("gl_each_occurrence", "GL per-occurrence"),
                                              ("auto_liability_limit", "Auto liability limit"),
                                              ("umbrella_limit", "Umbrella limit")]},
    # ── General Liability - paired occurrence + aggregate limits ─────────────
    "ACORD_126": {"combine": True,  "facts": [("gl_each_occurrence", "GL per-occurrence"),
                                              ("gl_aggregate", "GL aggregate"),
                                              ("gl_limits", "GL limits")]},
    # ── Business Auto ────────────────────────────────────────────────────────
    "ACORD_127": {"combine": False, "facts": [("auto_liability_limit", "Auto liability limit")]},
    # ── Workers Comp - payroll (total_payroll OR wc_payroll, per document) ────
    "ACORD_130": {"combine": False, "facts": [("total_payroll", "Total payroll"),
                                              ("wc_payroll", "WC payroll")]},
    # ── Umbrella / Excess ────────────────────────────────────────────────────
    "ACORD_131": {"combine": False, "facts": [("umbrella_limit", "Umbrella limit")]},
    # ── Property - building value, else business personal property value ─────
    "ACORD_140": {"combine": False, "facts": [("property_building_value", "Building value"),
                                              ("property_bpp_value", "Business property value")]},
    # ── Inland Marine - total scheduled value ────────────────────────────────
    "ACORD_141": {"combine": False, "facts": [("inland_marine_total_value", "Inland marine value")]},
    # ── Additional Remarks - loss count when losses drove the narrative ──────
    "ACORD_101": {"combine": False, "facts": [("num_claims", "Prior claims")]},
    # ── Builders Risk - project cost ─────────────────────────────────────────
    "ACORD_133": {"combine": False, "facts": [("builders_risk_project_cost", "Project cost")]},
    # ── Cyber - coverage limit ───────────────────────────────────────────────
    "ACORD_160": {"combine": False, "facts": [("cyber_limit", "Cyber limit")]},
    # ── Contractors Supplemental - subcontracting exposure ───────────────────
    "ACORD_186": {"combine": False, "facts": [("percent_subcontracted", "% subcontracted")]},
    # ── Evidence of Property - the property value being evidenced ────────────
    "ACORD_28":  {"combine": False, "facts": [("property_building_value", "Building value"),
                                              ("property_bpp_value", "Business property value")]},
    # ── Contractors (state variants) - contractor profile ────────────────────
    "ACORD_137_CA": {"combine": False, "facts": [("contractor_type", "Contractor type"),
                                                 ("percent_subcontracted", "% subcontracted")]},
    "ACORD_137_CO": {"combine": False, "facts": [("contractor_type", "Contractor type"),
                                                 ("percent_subcontracted", "% subcontracted")]},
    # ── Contractors Equipment (state variants) - equipment/contents value ────
    # Proxy: no dedicated equipment-schedule fact exists, so use business
    # personal-property value, then inland-marine scheduled value.
    "ACORD_138_CA": {"combine": False, "facts": [("property_bpp_value", "Equipment value"),
                                                 ("inland_marine_total_value", "Scheduled value")]},
    "ACORD_138_CO": {"combine": False, "facts": [("property_bpp_value", "Equipment value"),
                                                 ("inland_marine_total_value", "Scheduled value")]},
}


def _build_trigger_facts(form_id: str, facts: dict) -> Tuple[List[dict], Optional[str]]:
    """Return (trigger_facts, evidence_suffix) for one recommendation.

    trigger_facts : [{code, label, value}] for every corroborating fact that is
                    actually present (empty list when none) - persisted as-is for
                    the audit trail.
    evidence_suffix : a short human string ("limits $1M / $2M" or "Total payroll:
                    $2,500,000") for merging into the display reason, or None when
                    no evidence fact was extracted so the caller falls back to the
                    existing generic message unchanged.
    """
    spec = _FORM_EVIDENCE_FACTS.get(form_id)
    if not spec:
        return [], None
    present: List[dict] = []
    for key, label in spec["facts"]:
        val = _fv(facts, key)
        if _is_empty(val):
            continue
        sval = str(val).strip()
        if not sval:
            continue
        # A numerically-zero value ("0", "$0", "0%") is not useful evidence and
        # can mislead (e.g. "Prior claims: 0" on a narrative triggered by a
        # coverage conflict rather than losses). Skip it so the form falls back
        # to its generic message. Non-numeric values (e.g. "General Contractor")
        # are unaffected.
        _digits = re.sub(r"[^\d.]", "", sval)
        try:
            if _digits and float(_digits) == 0:
                continue
        except ValueError:
            pass
        present.append({"code": key, "label": label, "value": sval})
    if not present:
        return [], None
    if spec.get("combine") and len(present) >= 2:
        # Paired limits (GL occurrence + aggregate) read as "limits a / b".
        suffix = "limits " + " / ".join(tf["value"] for tf in present[:2])
    else:
        # Single value, or the first available of several alternative sources.
        suffix = f"{present[0]['label']}: {present[0]['value']}"
    return present, suffix


# ── State detection for ACORD 137/138 variants ──────────────────────────────

_STATE_NAME_TO_CODE = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME",
    "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI",
    "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND",
    "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
}

_SUPPORTED_137_138_STATES = {"CA", "CO"}


# ── Recommendation tiers (Beta Report §7 - ACORD Form Recommendation Logic) ──
# Additive classification on top of the EXISTING trigger logic. They do not
# change which forms are recommended or their confidence/match score - they only
# label each recommendation so the UI can group the list by underwriting
# priority (Required / Recommended / Optional / Needs Confirmation).
TIER_REQUIRED           = "required"
TIER_RECOMMENDED        = "recommended"
TIER_OPTIONAL           = "optional"
TIER_NEEDS_CONFIRMATION = "needs_confirmation"


# ── Uploaded-ACORD-form detection (Beta Report §7 "Situation 3") ──────────────
# Client direction: when a broker UPLOADS an already-filled ACORD form as part of
# the submission, it is a SOURCE document (evidence of existing coverage), not a
# form to generate from scratch. The form stays in the list but is labelled
# "generate a clean copy only if needed". Originally this only covered ACORD
# 25/28 (via the LLM is_certificate_doc flag, which only recognises those two);
# this generalises it to ALL 17 supported forms.
#
# Signal: the ACORD form-number STAMP printed on the document - the form number
# IMMEDIATELY followed by its edition-date in parentheses, e.g. "ACORD 130
# (2026/01)" or "ACORD 137 CA (2023/01)". Every ACORD form carries exactly this
# stamp identifying what the document IS; the edition date is the discriminator.
#
# Why the edition date is REQUIRED (not just the bare number): an ACORD form's
# BODY routinely cross-references OTHER forms by bare number - e.g. an ACORD 137
# prints "Attach to ACORD 127", "REMARKS (ACORD 101...)", "ACORD 61 CA". Matching
# a bare "ACORD NNN" anywhere in the text therefore mis-tags those referenced
# forms as if they too were uploaded (the 125/127/101 false positives seen when a
# single empty ACORD 137 was uploaded). A cross-reference is NEVER followed by an
# edition-date stamp, so requiring "(YYYY/MM)" right after the number isolates the
# document's own identity and eliminates the cross-reference false positives.
#
# State variants (137/138): the state code is part of the stamp ("137 CA
# (2023/01)"), so the stamp resolves directly to the exact CA/CO variant - no
# downstream guessing needed.
_ACORD_NUMBER_TO_FORMS: Dict[str, Tuple[str, ...]] = {
    "25":     ("ACORD_25",),
    "28":     ("ACORD_28",),
    "101":    ("ACORD_101",),
    "125":    ("ACORD_125",),
    "126":    ("ACORD_126",),
    "127":    ("ACORD_127",),
    "130":    ("ACORD_130",),
    "131":    ("ACORD_131",),
    "133":    ("ACORD_133",),
    "140":    ("ACORD_140",),
    "141":    ("ACORD_141",),
    "160":    ("ACORD_160",),
    "186":    ("ACORD_186",),
    # 137/138 are only valid as state editions in this system (CA/CO). A bare
    # "137 (...)" with no recognised state is ignored (no national variant exists
    # here), so it never mis-maps to a CA or CO form.
    "137":    (),
    "138":    (),
    "137_CA": ("ACORD_137_CA",), "137_CO": ("ACORD_137_CO",),
    "138_CA": ("ACORD_138_CA",), "138_CO": ("ACORD_138_CO",),
}

# Identity STAMP: "ACORD <number> [<state>] (<edition date>)". The trailing
# "(YYYY/MM)" is mandatory - it is what distinguishes the form's own number stamp
# from a bare body cross-reference to another form. Separators between tokens are
# optional/flexible to survive OCR spacing variance ("ACORD137CA(2023/01)").
_ACORD_FORM_STAMP_RE = re.compile(
    r"\bACORD[\s\-]*([0-9]{2,3})[\s\-]*([A-Z]{2})?[\s\-]*\(\s*\d{4}\s*/\s*\d{2}\s*\)",
    re.IGNORECASE,
)


def _detect_uploaded_acord_forms(text: str) -> set:
    """Return the set of form_ids the broker has UPLOADED as filled/blank source
    documents, detected from each form's printed identity STAMP - the ACORD
    number followed by its edition date, e.g. "ACORD 130 (2026/01)".

    Requiring the edition-date stamp (not a bare "ACORD NNN") is deliberate: an
    ACORD form's body cross-references other forms by bare number, so a bare-number
    scan mis-tags those referenced forms as uploaded. Only the document's own
    number carries the trailing "(YYYY/MM)" stamp, so this keys on identity and
    never on a cross-reference. State variants (137/138) are resolved by the state
    code carried in the stamp itself.
    """
    if not text:
        return set()
    found: set = set()
    for m in _ACORD_FORM_STAMP_RE.finditer(text):
        number = m.group(1)
        state  = (m.group(2) or "").upper()
        # Prefer the state-qualified key for the state-variant forms.
        key = f"{number}_{state}" if (state and f"{number}_{state}" in _ACORD_NUMBER_TO_FORMS) else number
        found.update(_ACORD_NUMBER_TO_FORMS.get(key, ()))
    return found


def _extract_state_code(value) -> Optional[str]:
    text = str(value or "").upper().strip()
    if not text:
        return None
    if text in US_STATES:
        return text

    for state_name, code in _STATE_NAME_TO_CODE.items():
        if re.search(rf"\b{re.escape(state_name)}\b", text):
            return code

    zip_match = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", text)
    if zip_match and zip_match.group(1) in US_STATES:
        return zip_match.group(1)

    comma_parts = [p.strip(" .") for p in text.split(",") if p.strip(" .")]
    for part in reversed(comma_parts):
        token = part.split()[0] if part.split() else ""
        if token in US_STATES:
            return token

    tokens = [t.strip(".,") for t in text.split()]
    if tokens and tokens[-1] in US_STATES and any(ch.isdigit() for ch in text):
        return tokens[-1]

    return None


def _infer_primary_state(facts: dict) -> Optional[str]:
    """
    Infer the primary state from applicant facts.
    Returns a 2-letter state code (CA, CO, etc.) or None.

    Priority:
    0. LLM-extracted state_of_operations field (most reliable)
    1. Extract from mailing_address or physical_address using US address patterns
    2. Check first location in locations list
    3. Check wc_payroll_by_state (first/dominant state)
    """
    state_val = facts.get("state_of_operations")
    if state_val:
        if isinstance(state_val, dict):
            state_val = (
                state_val.get("primary") or
                state_val.get("state") or
                state_val.get("value") or
                next(iter(state_val.values()), None)
            )
        if state_val and isinstance(state_val, str):
            code = state_val.upper().strip()[:2]
            if code in US_STATES:
                return code

    for key in ("mailing_address", "physical_address"):
        state = _extract_state_code(_fv(facts, key))
        if state:
            return state

    # Try first location
    locs = _fv(facts, "locations")
    if locs and isinstance(locs, list) and locs:
        state = _extract_state_code(locs[0])
        if state:
            return state

    # Try WC payroll by state
    wc_by_state = _fv(facts, "wc_payroll_by_state")
    if wc_by_state and isinstance(wc_by_state, dict):
        for state in wc_by_state.keys():
            code = _extract_state_code(state)
            if code:
                return code

    return None


def _infer_primary_state_from_flags(flags: dict) -> Optional[str]:
    if flags.get("is_california"):
        return "CA"
    if flags.get("is_colorado"):
        return "CO"
    return None


def _collect_states(facts: dict) -> set:
    """
    Return the SET of US state codes the insured appears to touch, drawn from
    every available signal: operations state, mailing/physical address, EVERY
    location (not just the first), and WC-payroll-by-state keys.

    Unlike ``_infer_primary_state`` (single dominant state), this surfaces
    secondary states too, so a state-specific form (ACORD 137/138 CA/CO) can be
    recommended when a *location* or *operations* in that state exist - directly
    implementing Beta Report §7.2 item 4 ("a location in that state exists" /
    "operations in that state exist"). Only evidence-backed states are returned,
    so this never re-inflates the list with states the insured doesn't touch.
    """
    states: set = set()

    def _add_code(value) -> None:
        code = _extract_state_code(value)
        if code:
            states.add(code)

    # Operations state - may be a plain string, a dict, or a list.
    sv = facts.get("state_of_operations")
    if isinstance(sv, dict):
        for v in sv.values():
            _add_code(v)
    elif isinstance(sv, (list, tuple)):
        for v in sv:
            _add_code(v)
    else:
        _add_code(sv)

    for key in ("mailing_address", "physical_address"):
        _add_code(_fv(facts, key))

    locs = _fv(facts, "locations")
    if isinstance(locs, list):
        for loc in locs:
            if isinstance(loc, dict):
                # Prefer an explicit state field; fall back to all values joined.
                explicit = loc.get("state") or loc.get("state_code") or loc.get("st")
                _add_code(explicit or " ".join(str(v) for v in loc.values()))
            else:
                _add_code(loc)

    wc_by_state = _fv(facts, "wc_payroll_by_state")
    if isinstance(wc_by_state, dict):
        for k in wc_by_state.keys():
            _add_code(k)

    return states


def _supported_state_forms(facts: dict, flags: dict) -> List[str]:
    """
    Supported state-specific form states (subset of {CA, CO}) the insured
    touches - from extracted data OR the is_california/is_colorado flags.
    Sorted for deterministic recommendation ordering.
    """
    codes = _collect_states(facts)
    if flags.get("is_california"):
        codes.add("CA")
    if flags.get("is_colorado"):
        codes.add("CO")
    return sorted(codes & _SUPPORTED_137_138_STATES)


# ── Account profile: business class / account type / coverage goals ───────────
# Beta Report §7.2 item 5 asks recommendations to be filtered/labelled by
# account type, business class, and user-selected goals (in addition to the
# state / coverage-line / exposure dimensions already wired). This block derives
# those three from the extracted facts + flags. It is READ-ONLY context - it does
# NOT change which forms are recommended.

# Coverage-line flags → label. Represents the lines the submission is seeking,
# i.e. the user's coverage goals (ACORD 125 §3 "Lines of Business" selections).
_COVERAGE_GOAL_LABELS = {
    "has_general_liability": "General Liability",
    "has_auto_coverage":     "Commercial Auto",
    "has_property_coverage": "Commercial Property",
    "has_workers_comp":      "Workers' Compensation",
    "has_umbrella":          "Umbrella / Excess",
    "has_inland_marine":     "Inland Marine",
    "has_builders_risk":     "Builders Risk",
    "has_cyber":             "Cyber",
    "has_crime":             "Crime",
}

# Ordered business-class signals (first match wins). Contractor is resolved via
# the is_contractor flag first (already corroborated upstream), then keywords.
_BUSINESS_CLASS_KEYWORDS = [
    ("contractor",              ("contractor", "contracting", "construction", "roofing",
                                 "excavation", "demolition", "scaffolding", "hvac")),
    ("manufacturing",           ("manufactur", "fabricat", "assembly line", "packaging",
                                 "foundry", "processing plant", "mill")),
    ("restaurant_food",         ("restaurant", "cafe", "food service", "catering",
                                 "tavern", "diner", "bar and grill")),
    ("auto_services",           ("auto dealer", "dealership", "garage", "auto repair",
                                 "body shop", "service station")),
    ("habitational_realestate", ("apartment", "condominium", "habitational", "lessor",
                                 "rental dwelling", "real estate", "property management",
                                 "landlord")),
    ("wholesale_distribution",  ("wholesale", "distributor", "distribution center",
                                 "warehousing", "logistics")),
    ("retail",                  ("retail", "storefront", "boutique")),
    ("office_professional",     ("office", "consulting", "professional services",
                                 "accounting", "law firm", "engineering services",
                                 "architect")),
]


def derive_account_profile(facts: dict, flags: dict, text: str = "") -> dict:
    """
    Derive account-level context used to filter/label form recommendations
    (Beta Report §7.2 item 5): business class, account type, transaction type,
    and coverage goals (requested lines). Read-only - never changes which forms
    are recommended; only adds context the UI can surface.
    """
    facts = facts or {}
    flags = flags or {}
    ops  = (_fv(facts, "operations_description") or "").lower()
    lobs = " ".join(facts.get("lines_of_business") or []).lower()
    blob = f"{ops} {lobs} {(text or '').lower()}"

    # Business class - is_contractor flag first (already corroborated), else kw.
    business_class = "general_commercial"
    if flags.get("is_contractor"):
        business_class = "contractor"
    else:
        for cls, kws in _BUSINESS_CLASS_KEYWORDS:
            if any(kw in blob for kw in kws):
                business_class = cls
                break

    # Coverage goals - only lines explicitly confirmed (flag is True).
    coverage_goals = [
        label for flag, label in _COVERAGE_GOAL_LABELS.items() if flags.get(flag) is True
    ]

    # Account type - package (multi-line) vs monoline; new vs renewal.
    is_renewal = bool(flags.get("is_renewal")) or "renew" in blob
    transaction_type = "renewal" if is_renewal else "new_business"
    is_package = (
        len(coverage_goals) >= 2
        or bool(flags.get("is_package_policy"))
        or "commercial package" in blob
        or "package policy" in blob
    )
    account_type = "commercial_package" if is_package else "monoline"

    return {
        "business_class":   business_class,
        "business_class_label": business_class.replace("_", " ").title(),
        "account_type":     account_type,
        "account_type_label": "Commercial Package" if account_type == "commercial_package" else "Monoline",
        "transaction_type": transaction_type,
        "coverage_goals":   coverage_goals,
    }


# ── Account-profile relevance for each recommendation (Beta Report §7.2 item 5) ─
# Filters/labels recommendations by account type, business class, and the user's
# confirmed coverage goals. This is CONSERVATIVE and ADDITIVE: it stamps a
# `profile_relevant` flag onto each recommendation but never removes or reorders
# one, so a legitimately-triggered form is never dropped (acceptance criterion:
# "Business-class recommendations are clearly labeled" / "Low fill score does not
# make a relevant form appear irrelevant"). Only a weak OPTIONAL-tier form that
# serves none of the confirmed coverage goals and is not relevant to the business
# class is flagged for the UI to de-emphasize.

# Form → the coverage goal it serves. Goal strings MUST match _COVERAGE_GOAL_LABELS.
_FORM_COVERAGE_GOAL = {
    "ACORD_126":    "General Liability",
    "ACORD_127":    "Commercial Auto",
    "ACORD_130":    "Workers' Compensation",
    "ACORD_131":    "Umbrella / Excess",
    "ACORD_140":    "Commercial Property",
    "ACORD_141":    "Commercial Property",
    "ACORD_133":    "Builders Risk",
    "ACORD_160":    "Inland Marine",
    "ACORD_137_CA": "Commercial Auto", "ACORD_137_CO": "Commercial Auto",
    "ACORD_138_CA": "Commercial Auto", "ACORD_138_CO": "Commercial Auto",
    "ACORD_28":     "Commercial Property",
}

# Business class → supplemental forms that stay relevant for that class even when
# they are not tied to an explicit confirmed coverage goal.
_CLASS_RELEVANT_FORMS = {
    "contractor": {"ACORD_186", "ACORD_133", "ACORD_160"},
}

# Always relevant regardless of profile: master application + the narrative form.
_ALWAYS_RELEVANT_FORMS = {"ACORD_125", "ACORD_101"}


def _assess_profile_relevance(
    form_id: str, tier: str, is_source_document: bool, profile: dict
) -> Tuple[bool, str]:
    """Return (profile_relevant, relevance_reason) for one recommendation.

    Required / Recommended / Needs-Confirmation forms, the master application, the
    narrative, and uploaded source documents are always relevant. Only an OPTIONAL
    form that serves none of the confirmed coverage goals and is not relevant to
    the detected business class is marked not-relevant - so the engine never
    mislabels a form it triggered on a strong signal.
    """
    if form_id in _ALWAYS_RELEVANT_FORMS or is_source_document:
        return True, ""
    if tier in (TIER_REQUIRED, TIER_RECOMMENDED, TIER_NEEDS_CONFIRMATION):
        return True, ""
    # OPTIONAL tier - relevant only if it serves a confirmed goal or the class.
    goals = set(profile.get("coverage_goals") or [])
    goal  = _FORM_COVERAGE_GOAL.get(form_id)
    if goal and goal in goals:
        return True, ""
    if form_id in _CLASS_RELEVANT_FORMS.get(profile.get("business_class", ""), set()):
        return True, ""
    label = profile.get("business_class_label") or "this account"
    return False, f"Weakly related to {label} - optional, confirm before including"


# ── Positive business-class label for a recommendation ───────────────────────
# Companion to _assess_profile_relevance (which flags WEAKLY-related optional
# forms for de-emphasis). This names WHY a form fits the detected business class
# so the UI can tag it per-form, not just via the account-level "Tailored for:"
# badge - directly satisfying the Beta Report §7 acceptance criterion
# "Business-class recommendations are clearly labeled". Read-only/additive: it
# never changes which forms are recommended, their tier, order, or confidence.
def _profile_relevance_label(form_id: str, profile: dict) -> str:
    """Short, plain-English tag for a form's tie to the account's business class
    (e.g. "Relevant to Contractor operations" for ACORD 186/133/160 on a
    contractor submission). Returns "" for universal forms (125/101) and for any
    form with no business-class-specific tie, so the chip appears only where it
    adds signal and never clutters the line-of-business forms.
    """
    if form_id in _ALWAYS_RELEVANT_FORMS:
        return ""
    business_class = profile.get("business_class") or ""
    if form_id in _CLASS_RELEVANT_FORMS.get(business_class, set()):
        label = profile.get("business_class_label") or "this account"
        return f"Relevant to {label} operations"
    return ""


# ── Form required-keys index (built once at import time) ──────────────────────
#
# Maps form_id → frozenset of fact-keys that the form needs.
# Sources (in priority order):
#   1. Fieldmap JSON  - ACORD_<form_id>_fieldmap.json  (non-null values only)
#   2. form JSON      - required_fields / tier1_minimum_fields lists
#
# Internal pseudo-keys that start with "_" (address helpers like _addr_line1)
# are excluded - they are always synthesised from mailing_address and cannot
# be checked directly against the facts dict.
#
# The index is intentionally a module-level constant so every request shares
# the same object without any lock or lazy-init logic.

def _build_form_required_keys() -> Dict[str, FrozenSet[str]]:
    """
    Walk every form in forms_index.json and build the set of fact-keys that
    form requires, drawing from fieldmaps first, then form-level field lists.
    Returns {form_id: frozenset(fact_keys)}.
    """
    index: Dict[str, FrozenSet[str]] = {}

    if not os.path.exists(FORMS_INDEX):
        return index

    try:
        with open(FORMS_INDEX) as f:
            forms_list = json.load(f).get("forms", [])
    except Exception as exc:
        logger.error("form_service: failed to read forms_index.json: %s", exc)
        return index

    for ref in forms_list:
        form_id = ref.get("form_id", "")
        if not form_id:
            continue

        keys: set = set()

        # ── Source 1: fieldmap JSON ────────────────────────────────────────
        # Naming convention used by pdf_service._load_fieldmap:
        #   ACORD_{form_id}_fieldmap.json  where form_id is WITHOUT the ACORD_ prefix
        # But the forms_index stores form_id as e.g. "ACORD_126".
        # The fieldmap files on disk are named  ACORD_ACORD_126_fieldmap.json
        # (i.e. "ACORD_" + form_id + "_fieldmap.json").
        fieldmap_path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
        if os.path.exists(fieldmap_path):
            try:
                with open(fieldmap_path) as f:
                    fieldmap = json.load(f)
                for fact_key in fieldmap.values():
                    if fact_key and isinstance(fact_key, str) and not fact_key.startswith("_"):
                        keys.add(fact_key)
            except Exception as exc:
                logger.warning("form_service: could not read fieldmap %s: %s", fieldmap_path, exc)

        # ── Source 2: form JSON field lists ────────────────────────────────
        form_json_path = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
        if os.path.exists(form_json_path):
            try:
                with open(form_json_path) as f:
                    form_meta = json.load(f)
                for list_key in ("required_fields", "tier1_minimum_fields",
                                 "tier1_cope_fields", "tier2_carrier_grade_cope_fields"):
                    for fk in form_meta.get(list_key) or []:
                        if fk and not str(fk).startswith("_"):
                            keys.add(fk)
            except Exception as exc:
                logger.warning("form_service: could not read form JSON %s: %s", form_json_path, exc)

        index[form_id] = frozenset(keys)
        logger.debug("form_service: %s → %d required keys", form_id, len(keys))

    return index


# Module-level cache - built once, shared across all requests.
_FORM_REQUIRED_KEYS: Dict[str, FrozenSet[str]] = _build_form_required_keys()


def _build_form_name_index() -> Dict[str, str]:
    """form_id → display form_name, read once from each form's detail JSON.
    Used by the uploaded-source-document backstop so a form the broker uploaded
    but that no trigger surfaced can still be added with its proper name.
    Falls back to the form_id if a name can't be read."""
    names: Dict[str, str] = {}
    if not os.path.exists(FORMS_INDEX):
        return names
    try:
        with open(FORMS_INDEX) as f:
            forms_list = json.load(f).get("forms", [])
    except Exception as exc:
        logger.error("form_service: failed to read forms_index.json for names: %s", exc)
        return names
    for ref in forms_list:
        form_id = ref.get("form_id", "")
        if not form_id:
            continue
        name = ref.get("form_name")
        if not name:
            detail_path = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
            if os.path.exists(detail_path):
                try:
                    with open(detail_path) as f:
                        name = json.load(f).get("form_name")
                except Exception as exc:
                    logger.warning("form_service: could not read form name %s: %s", detail_path, exc)
        names[form_id] = name or form_id
    return names


_FORM_NAMES: Dict[str, str] = _build_form_name_index()


def _score_field_coverage(form_id: str, facts: dict) -> Tuple[float, int, int]:
    """
    Return (coverage_ratio, filled_count, total_count) for the given form
    against the extracted facts dict.

    coverage_ratio is in [0.0, 1.0].  If the form has no required keys the
    ratio is 0.0 (caller handles this edge-case by falling back to trigger tier).

    A fact-key is considered "filled" if:
      - it exists in facts AND
      - its value (unwrapped from OCR-confidence envelope if present) is
        non-empty (not None / "" / "null" / "none" / "n/a").

    Facts stored as annotated dicts {value, confidence} are handled via _fv/_is_empty.
    List-type facts (e.g. lines_of_business) count as filled when non-empty.
    """
    required = _FORM_REQUIRED_KEYS.get(form_id, frozenset())
    total    = len(required)
    if total == 0:
        return 0.0, 0, 0

    filled = 0
    for key in required:
        raw = facts.get(key)
        if raw is None:
            continue
        # _is_empty handles: None, "", "null"/"none"/"n/a", empty list/dict,
        # and annotated envelopes {"value": ..., "confidence": ...}
        if not _is_empty(raw):
            filled += 1

    ratio = filled / total
    return ratio, filled, total


def _compute_confidence(
    form_id: str,
    facts: dict,
    trigger_weight: float,
    triggered: bool,
) -> Tuple[float, str]:
    """
    Compute the blended confidence score and a human-readable reason string.

    Formula (when the form has required keys):
        blended = 0.6 * field_coverage + 0.4 * trigger_weight

    Floor guarantee for triggered forms:
        blended ≥ trigger_weight * 0.55
        (a triggered form can never score below ~55% of its trigger tier)

    When the form has no required keys (no fieldmap + no field lists), we
    return trigger_weight directly so the score is at least the tier signal.

    Parameters
    ----------
    trigger_weight : float
        1.0 for always-required, 0.95 for flag-based, 0.85 for keyword-based,
        0.0 for non-triggered forms scored for the "add more forms" list.
    triggered : bool
        True when the form was matched by rule/flag/keyword logic.
    """
    coverage, filled, total = _score_field_coverage(form_id, facts)

    if total == 0:
        # No schema data to compute coverage - honour trigger tier as-is.
        # Non-triggered forms with no schema get 0.
        score = trigger_weight
        if triggered and trigger_weight > 0:
            reason = "Form triggered by document signals; no field schema available for detailed scoring"
        elif not triggered:
            reason = "No field schema available"
        else:
            reason = "Always required"
        return round(score, 4), reason

    blended = 0.6 * coverage + 0.4 * trigger_weight

    if triggered and trigger_weight > 0:
        floor   = trigger_weight * 0.55
        blended = max(blended, floor)

    blended = min(blended, 1.0)

    pct = round(coverage * 100)
    reason = f"{filled} of {total} required fields found in document ({pct}%)"
    return round(blended, 4), reason


# ─────────────────────────────────────────────────────────────────────────────


def load_index() -> dict:
    if not os.path.exists(FORMS_INDEX):
        return {"forms": []}
    with open(FORMS_INDEX) as f:
        return json.load(f)


def load_form_detail(form_id: str) -> Optional[dict]:
    p = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def load_all_forms() -> List[dict]:
    idx = load_index()
    return [d for ref in idx.get("forms", []) if (d := load_form_detail(ref["form_id"])) is not None]


def filter_available_forms(forms: List[dict]) -> List[dict]:
    # Exclude forms with no template_file: an empty string resolves to TEMPLATE_DIR
    # itself (which always exists), so we must gate on truthiness first.
    return [
        f for f in forms
        if f.get("template_file")
        and os.path.exists(os.path.join(TEMPLATE_DIR, f["template_file"]))
    ]


def stage1_filter(flags: dict, all_forms: List[dict]) -> List[dict]:
    active     = {k for k, v in flags.items() if v}
    candidates = []
    seen       = set()
    for form in all_forms:
        fid     = form["form_id"]
        if fid in seen:
            continue
        include = False
        if form.get("always_include"):
            include = True
        elif set(form.get("matching_flags", [])) & active:
            include = True
        elif fid == "ACORD_126" and (flags.get("has_general_liability") or flags.get("is_contractor")):
            include = True
        elif fid == "ACORD_140" and flags.get("has_property_coverage"):
            include = True
        elif fid == "ACORD_25" and (flags.get("has_certificate_request") or flags.get("is_certificate_doc")):
            include = True
        if include:
            candidates.append(form)
            seen.add(fid)
    return candidates



# ── Dec-page "line of coverage present" detector ─────────────────────────────
# Decision_Tree.txt prime rule (L2): "identify each line of coverage present on
# the uploaded documents (especially the dec page)". The LLM coverage flags
# (has_general_liability, ...) are the primary signal, but beta testing showed
# their RECALL drops when a line is not the dominant coverage - a dec page that
# clearly printed "GENERAL LIABILITY $1,000,000" still came back with the flag
# unset/False, so the form was dropped. When the raw text shows a coverage NAME
# immediately followed by a money amount / premium / limit (a real dec-page line
# item, not incidental prose), we trust the page and surface the form. It is
# tiered Needs Confirmation (the structured flag did not confirm it), so the
# broker reviews - but the coverage is never silently dropped.
_COVERAGE_LINE_SIGNAL = re.compile(
    r"\$\s*[\d,]|\bpremium\b|\blimit\b|\bstatutory\b|combined single|\bcsl\b|/\s*\$",
    re.IGNORECASE,
)
# Bug fix: added "cgl" abbreviation; "general liability" alone already covers most dec pages
_GL_LINE_PHRASES   = ("general liability", "commercial general liability", "cgl liability")
# Bug fix: added "automobile" (standalone) for carrier dec pages that abbreviate
_AUTO_LINE_PHRASES = ("business auto", "commercial auto", "automobile liability", "auto liability",
                      "hired and non-owned", "hired auto")
# Bug fix: added "employers liability" - always a WC sub-line; if it appears with a
# money signal the document has WC coverage even when "Workers Compensation" isn't nearby.
_WC_LINE_PHRASES   = ("workers compensation", "workers' compensation", "workers comp",
                      "employers liability")
_UMB_LINE_PHRASES  = ("umbrella", "excess liability", "excess and umbrella")
# Multi-word, unambiguous property line phrases - safe for the 90-char proximity
# scan in _dec_line_present(). Bare "building"/"dwelling"/"contents" are NOT here:
# they are common words and a 90-char window would let an auto/GL dec line
# ("leased building ... auto liability limit $1,000,000") falsely trigger ACORD
# 140. Those single nouns are handled by the tighter, dollar-adjacent _PROP_VALUE_RE
# below instead. "property damage limit" is deliberately EXCLUDED - it is GL/auto
# third-party PD liability, NOT first-party commercial property.
_PROP_LINE_PHRASES = ("commercial property", "building limit", "business personal property",
                      "property coverage", "lessor's risk", "lessors risk",
                      "habitational property", "building and contents", "contents coverage",
                      "blanket building", "blanket bpp")
# "Building $500,000" / "BPP $120,000" / "Dwelling $250,000" - a property NOUN
# followed within 15 chars by a 4+ digit dollar amount is a real property VALUE
# line item. Habitational / lessor's-risk dec pages write the value this way rather
# than the two-word "building limit", so _dec_line_present misses them. The tight
# 15-char gap keeps precision high: "Building Coverage $500,000" matches, but
# "leased building; auto liability limit $1,000,000" (≈34 char gap) does NOT - the
# dollar there belongs to the auto line, not the building.
_PROP_VALUE_RE = re.compile(
    r"\b(?:building|dwelling|bpp|contents|business personal property|real property)"
    r"\b[^\n$]{0,15}\$\s*[\d,]{4,}",
    re.IGNORECASE,
)


def _dec_line_present(text: str, phrases) -> bool:
    """True if any phrase appears on what looks like a dec-page LINE ITEM - the
    phrase followed within ~90 chars by a money / premium / limit / statutory
    signal. High precision: "general liability ... $1,000,000 premium" matches;
    "general liability concerns" does not."""
    if not text:
        return False
    # Collapse dotted leaders ("GENERAL LIABILITY ....... $1,000,000") and long
    # whitespace runs so the coverage name and its amount stay within the window.
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    for ph in phrases:
        start = 0
        while True:
            i = text.find(ph, start)
            if i < 0:
                break
            if _COVERAGE_LINE_SIGNAL.search(text[i:i + 90]):
                return True
            start = i + 1
    return False


def match_forms_deterministic(facts: dict, flags: dict, text: str = "",
                              account_profile: dict = None) -> List[dict]:
    """
    Rule-based form matching combined with live document field-coverage scoring.

    Trigger logic is unchanged (flag/keyword rules decide WHICH forms to recommend).
    Confidence is now a live blended score:
        confidence = 0.6 * field_coverage + 0.4 * trigger_weight
    where field_coverage = (fact-keys present in extracted facts) / (total required keys
    for this form, derived from its fieldmap + form JSON).

    Floor for triggered forms: confidence ≥ trigger_weight × 0.55 so that a strongly
    triggered form is never buried by a sparse document.

    Forms without any schema data (no fieldmap, no field lists) fall back to their
    raw trigger weight so the score is still meaningful.

    Return shape per item:
        {
          "form_id":          str,
          "form_name":        str,
          "confidence":       float,   # blended [0.0, 1.0]
          "reason":           str,     # human-readable - shown in UI
          "trigger_reason":   str,     # what fired the rule (kept for audit / E&O log)
          "fields_filled":    int,
          "fields_total":     int,
          "template_pending": bool,    # only present when True
        }
    """
    matches: List[dict] = []

    # Build a single searchable text from operations + lines of business + raw OCR.
    ops    = (_fv(facts, "operations_description") or "").lower()
    lobs   = " ".join(facts.get("lines_of_business") or []).lower()
    cert_h = (_fv(facts, "certificate_holder") or "").lower()
    text   = (text or "").lower()
    search = f"{ops} {lobs} {cert_h} {text}"

    # Forms the broker has ALREADY uploaded as a filled document (detected by the
    # ACORD form number printed on the upload). Any recommended form in this set
    # is tagged as a SOURCE document - "generate a clean copy only if needed" -
    # generalising the original ACORD 25/28-only behaviour to all 17 forms
    # (Beta Report §7 "Situation 3"). Case-insensitive regex, so the lowercased
    # `search` is fine. Additive only: never changes which forms are recommended.
    _uploaded_forms = _detect_uploaded_acord_forms(search)

    # Account profile (business class / account type / coverage goals) used to
    # stamp each recommendation's filter dimensions (Beta Report §7.2 item 5).
    # Accept a pre-computed profile from the caller; otherwise derive it here.
    _profile = account_profile or derive_account_profile(facts, flags, text)

    def _already_matched(form_id: str) -> bool:
        return any(m["form_id"] == form_id for m in matches)

    def _add(form_id: str, form_name: str, trigger_weight: float,
             trigger_reason: str, template_pending: bool = False,
             needs_state_confirmation: bool = False,
             tier: str = TIER_RECOMMENDED, reason_label: str = None,
             is_source_document: bool = False) -> None:
        # Generalised source-document detection (Beta Report §7 "Situation 3"):
        # if the broker uploaded this exact ACORD form (its printed number was
        # found in the upload), it is already-provided evidence, not a form to
        # build. The ACORD 25/28 callers still pass is_source_document via the
        # is_certificate_doc flag (kept as a belt-and-suspenders signal); this
        # adds the same treatment to the other 15 forms. When the upload signal
        # fires for a form whose caller did NOT already supply a source-document
        # label, swap in the standard note so the wording is consistent.
        _uploaded_this_form = form_id in _uploaded_forms
        if _uploaded_this_form and not is_source_document:
            is_source_document = True
            reason_label = (
                "Detected as an uploaded ACORD form - generate a clean copy only if needed"
            )
        confidence, reason = _compute_confidence(form_id, facts, trigger_weight, triggered=True)
        entry: dict = {
            "form_id":        form_id,
            "form_name":      form_name,
            "confidence":     confidence,
            "reason":         reason,
            "trigger_reason": trigger_reason,
            # ── Workstream 4 add-ons (Beta Report §7) ──────────────────────────
            # tier         : grouping bucket for the recommendation list.
            # reason_label : short, plain-English "why this form" shown to the
            #                broker (the verbose trigger_reason is kept for audit).
            "tier":           tier,
            "reason_label":   reason_label or trigger_reason,
        }
        # ── Beta Report Fig 7: "why this form" evidence ─────────────────────
        # Merge the concrete extracted value into the display reason (keeping the
        # current message) and record the structured trigger facts for audit.
        # Reads already-extracted facts only - triggering is unchanged. Falls
        # back to the existing message when no evidence value was extracted, and
        # is skipped for uploaded source docs (their message is about a clean
        # copy, not coverage evidence).
        _trigger_facts, _evidence = _build_trigger_facts(form_id, facts)
        if _trigger_facts:
            entry["trigger_facts"] = _trigger_facts
            if _evidence and not is_source_document:
                entry["reason_label"] = f"{entry['reason_label']} - {_evidence}"
        # Expose raw counts so the frontend can render "12 of 18 fields"
        _, filled, total = _score_field_coverage(form_id, facts)
        entry["fields_filled"] = filled
        entry["fields_total"]  = total
        if template_pending:
            entry["template_pending"] = True
        if needs_state_confirmation:
            entry["needs_state_confirmation"] = True
        # ACORD 25/28 detected as an already-uploaded proof document, not a form
        # to build from scratch (Beta Report §7 action item 6).
        if is_source_document:
            entry["is_source_document"] = True
        # ── Beta Report §7.2 item 5: stamp account-profile filter dimensions ──
        # business class / account type + whether this form aligns with the
        # confirmed coverage goals or the business class. Additive metadata only:
        # it never removes or reorders a recommendation, so a legitimately
        # triggered form is never dropped - the UI can filter/label by these.
        entry["business_class"] = _profile.get("business_class")
        entry["account_type"]   = _profile.get("account_type")
        _rel, _rel_reason = _assess_profile_relevance(form_id, tier, is_source_document, _profile)
        entry["profile_relevant"] = _rel
        if _rel_reason:
            entry["relevance_reason"] = _rel_reason
        # Positive per-form business-class label (e.g. "Relevant to Contractor
        # operations"). Additive optional key - present only when the form has a
        # business-class-specific tie; the UI renders it as a small chip.
        _rel_label = _profile_relevance_label(form_id, _profile)
        if _rel_label:
            entry["relevance_label"] = _rel_label
        matches.append(entry)

    # ── Always required ────────────────────────────────────────────────────────
    # Reason reflects the account/package type (Beta Report §7.2 item 1 example:
    # "Required based on selected package type"). A multi-line submission reads as
    # a commercial package; a single line reads as monoline. This is display-only
    # - ACORD 125 is ALWAYS required either way (Decision_Tree L28).
    _125_line_count = sum(
        1 for _k in ("has_general_liability", "has_auto_coverage", "has_property_coverage",
                     "has_workers_comp", "has_umbrella", "has_inland_marine", "has_builders_risk")
        if flags.get(_k) is True
    )
    _125_reason = (
        "Required - master application for this commercial package"
        if _125_line_count >= 2 else
        "Required for every commercial submission"
    )
    _add("ACORD_125",
         "ACORD 125 - Commercial Insurance Application",
         trigger_weight=1.0,
         trigger_reason="Always required for any commercial submission",
         tier=TIER_REQUIRED,
         reason_label=_125_reason)

    # ── Flag-based (trigger_weight 0.95) ──────────────────────────────────────

    # Keyword fallback sets - used ONLY when the LLM-derived flag is missing
    # (not when the LLM explicitly evaluated it as False). Phrases here are
    # narrow enough to imply coverage-being-requested, not incidental mentions
    # (e.g. "bodily injury", "additional insured" appear on every COI and are
    # therefore excluded - they would over-trigger).
    _126_kw = {
        "general liability", "premises-operations", "premises/operations",
        "products/completed", "products-completed", "personal & advertising injury",
        "personal and advertising injury", "acord 126",
    }
    _127_kw = {
        "business auto", "commercial auto", "vehicle schedule",
        "auto liability", "year/make/model", "year make model", "acord 127",
        # Decision_Tree.txt ACORD 127 triggers (L168) + cues (L169): hired /
        # non-owned auto is an explicit trigger phrase - add to the fallback set.
        "hired auto", "non-owned auto", "hired and non-owned", "hired & non-owned",
        "hired/non-owned", "non-owned and hired",
    }
    _140_kw = {
        "building limit", "business personal property",
        "construction type", "sprinklered", "roof year",
        "business income", "year built", "fire protection class",
        "acord 140",
        # Decision_Tree.txt ACORD 140 cue (L257): "BPP" abbreviation.
        "bpp",
        # Bug fix: habitational / real-estate accounts use these terms on dec pages
        # and in operations descriptions - none were previously in the fallback set,
        # causing ACORD 140 to be silently omitted for lessor's risk / apartment / etc.
        # (These fire only on the flag-absent fallback path → Needs Confirmation tier.)
        "habitational", "apartment building", "rental property",
        "lessor's risk", "lessor risk", "dwelling coverage",
        "landlord", "landlord coverage", "condominium",
    }
    # Decision_Tree.txt ACORD 130 decision rule (L125): add WC on payroll OR
    # WC_terms. We intentionally EXCLUDE bare "payroll" (it is also a GL exposure
    # base per L88) and bare "wc" (substring-unsafe). Only unambiguous WC terms
    # below - and only as a fallback when the LLM flag is absent.
    _130_kw = {
        "workers compensation", "workers' compensation", "workmens compensation",
        "workmen's compensation", "workers comp", "ncci", "experience modification",
        "x-mod", "xmod", "acord 130",
    }

    _gl_line = _dec_line_present(search, _GL_LINE_PHRASES)
    _has_gl = flags.get("has_general_liability")
    if _has_gl is True or (_has_gl is None and any(kw in search for kw in _126_kw)) or _gl_line:
        _gl_confirmed = _has_gl is True
        _gl_reason = (
            "has_general_liability flag detected"
            if _gl_confirmed
            else "general liability line detected on document (flag unconfirmed)"
        )
        _add("ACORD_126",
             "ACORD 126 - Commercial General Liability Section",
             trigger_weight=0.95,
             trigger_reason=_gl_reason,
             tier=TIER_REQUIRED if _gl_confirmed else TIER_NEEDS_CONFIRMATION,
             reason_label=("General Liability coverage detected" if _gl_confirmed
                           else "Possible General Liability exposure - confirm"))

    _wc_line = _dec_line_present(search, _WC_LINE_PHRASES)
    _has_wc = flags.get("has_workers_comp")
    if _has_wc is True or (_has_wc is None and any(kw in search for kw in _130_kw)) or _wc_line:
        _wc_confirmed = _has_wc is True
        _wc_reason = (
            "has_workers_comp flag detected"
            if _wc_confirmed
            else "workers compensation keywords detected in document text"
        )
        # Spec §137-142: monopolistic WC states (ND/OH/WA/WY) require state
        # fund - surface the constraint in the recommendation reason so users
        # see it at recommendation time, not just at SQS time.
        if flags.get("wc_has_monopolistic_state"):
            _wc_reason += (
                " (monopolistic state detected - ND/OH/WA/WY require state fund; "
                "private-carrier WC will be hard-stopped unless state-fund acknowledgement is provided)"
            )
        _add("ACORD_130",
             "ACORD 130 - Workers Compensation Application",
             trigger_weight=0.95,
             trigger_reason=_wc_reason,
             template_pending=True,
             tier=TIER_REQUIRED if _wc_confirmed else TIER_NEEDS_CONFIRMATION,
             reason_label=("Workers' Compensation exposure detected" if _wc_confirmed
                           else "Possible Workers' Compensation exposure - confirm"))

    _auto_line = _dec_line_present(search, _AUTO_LINE_PHRASES)
    _has_auto = flags.get("has_auto_coverage")
    if _has_auto is True or (_has_auto is None and any(kw in search for kw in _127_kw)) or _auto_line:
        _auto_confirmed = _has_auto is True
        _auto_reason = (
            "has_auto_coverage flag detected"
            if _auto_confirmed
            else "auto line detected on document (flag unconfirmed)"
        )
        _add("ACORD_127",
             "ACORD 127 - Business Auto Section",
             trigger_weight=0.95,
             trigger_reason=_auto_reason,
             template_pending=True,
             tier=TIER_REQUIRED if _auto_confirmed else TIER_NEEDS_CONFIRMATION,
             reason_label=("Commercial Auto exposure detected" if _auto_confirmed
                           else "Possible Auto exposure - confirm"))

    # ACORD 131 fires whenever an umbrella / excess line is REQUESTED or shown - the
    # has_umbrella flag (the LLM confirmed/requested the line), extracted umbrella
    # facts, or a dec-page umbrella line item. This mirrors the other primary line
    # forms (126/127/130/140), which surface on the flag alone. Per Decision_Tree.txt
    # ("IF 125.requested_line(Umbrella) THEN add ACORD_131"), a confirmed flag must
    # NEVER be silently dropped just because supporting limits weren't extracted - the
    # old logic required corroboration to even add the form, so a bare confirmed flag
    # with no umbrella fact and no literal "umbrella"/"excess liability" wording (e.g.
    # "following form excess of $1M over GL") produced NO ACORD 131 at all.
    #
    # Tier (client Q1 - "Umbrella confirmed = ACORD 131 Required"):
    #   REQUIRED           - has_umbrella flag confirmed by the LLM. Exactly like the
    #                        other four primary line forms (126/127/130/140), a
    #                        confirmed flag makes the form Required on the flag ALONE;
    #                        an extracted umbrella fact or literal wording only refines
    #                        the reason shown, never the tier.
    #   NEEDS CONFIRMATION - a dec-page umbrella line WITHOUT the structured flag (the
    #                        LLM did not confirm it), pending broker review.
    _umb_facts = any([
        _fv(facts, "umbrella_limit"),
        _fv(facts, "umbrella_attachment_point"),
        _fv(facts, "umbrella_sir"),
    ])
    # `search` (not raw `text`) so umbrella mentions in ops / lines-of-business count too.
    _umb_kw_in_text = any(kw in search for kw in ("umbrella", "excess liability"))
    _umb_line = _dec_line_present(search, _UMB_LINE_PHRASES)
    _umb_flag = bool(flags.get("has_umbrella"))
    if _umb_flag or _umb_line:
        # Corroboration (an umbrella fact or literal wording) refines ONLY the reason
        # text - the tier is driven purely by whether the LLM confirmed the flag.
        _umb_corroborated = _umb_facts or _umb_kw_in_text
        if _umb_flag and _umb_corroborated:
            _umb_reason = "has_umbrella flag detected with supporting umbrella data"
            _umb_label  = "Umbrella / Excess coverage detected"
        elif _umb_flag:
            _umb_reason = ("has_umbrella flag confirmed; underlying umbrella limit / "
                           "attachment point not yet extracted")
            _umb_label  = "Umbrella / Excess coverage confirmed"
        else:
            _umb_reason = "umbrella / excess line detected on document (flag unconfirmed)"
            _umb_label  = "Umbrella / Excess shown on document - confirm"
        _add("ACORD_131",
             "ACORD 131 - Umbrella / Excess Liability",
             trigger_weight=0.95,
             trigger_reason=_umb_reason,
             template_pending=True,
             tier=TIER_REQUIRED if _umb_flag else TIER_NEEDS_CONFIRMATION,
             reason_label=_umb_label)

    _prop_line = _dec_line_present(search, _PROP_LINE_PHRASES) or bool(_PROP_VALUE_RE.search(search))
    _has_prop = flags.get("has_property_coverage")
    if _has_prop is True or (_has_prop is None and any(kw in search for kw in _140_kw)) or _prop_line:
        _prop_confirmed = _has_prop is True
        _prop_reason = (
            "has_property_coverage flag detected"
            if _prop_confirmed
            else "property line detected on document (flag unconfirmed)"
        )
        _add("ACORD_140",
             "ACORD 140 - Commercial Property Section",
             trigger_weight=0.95,
             trigger_reason=_prop_reason,
             tier=TIER_REQUIRED if _prop_confirmed else TIER_NEEDS_CONFIRMATION,
             reason_label=("Commercial Property coverage detected" if _prop_confirmed
                           else "Possible Property exposure - confirm"))

    # ACORD 25 flag path.
    # is_certificate_doc  → the uploaded document IS literally a COI (strong, precise
    #                        classification signal - fires alone).
    # has_certificate_request → LLM infers a cert was requested. This flag fires too
    #                        easily (any doc with "certificate holder" printed on it
    #                        sets it). Require strong keyword corroboration so a random
    #                        dec page or policy doesn't pull ACORD 25 into the list.
    _25_strong_kw = {
        "certificate of liability insurance", "certificate of liability",
        "proof of insurance", "evidence of liability", "acord 25",
        "certificate required", "certificate requested",
        "liability certificate", "additional insured certificate",
    }
    _25_cert_request_confirmed = (
        flags.get("has_certificate_request")
        and any(kw in search for kw in _25_strong_kw)
    )
    if flags.get("is_certificate_doc") or _25_cert_request_confirmed:
        _25_is_source = bool(flags.get("is_certificate_doc"))
        _add("ACORD_25",
             "ACORD 25 - Certificate of Liability Insurance",
             trigger_weight=0.95,
             trigger_reason="has_certificate_request or is_certificate_doc flag detected",
             tier=TIER_NEEDS_CONFIRMATION,
             reason_label=("Detected as an uploaded certificate - generate a clean copy only if needed"
                           if _25_is_source else "Certificate of Insurance requested - confirm if needed"),
             is_source_document=_25_is_source)

    if flags.get("is_contractor"):
        # Require at least one contractor-specific fact or keyword in ops/text
        # as secondary confirmation - prevents firing when the LLM sets
        # is_contractor from incidental construction mentions.
        _186_confirm_kw = {
            "general contractor", "roofing", "excavation", "demolition",
            "subcontractor", "plumbing", "electrical", "contractor",
            # Decision_Tree.txt ACORD 186 rule (L461): operations.contains("contracting").
            # "contractor" is NOT a substring of "contracting" - without this a
            # business literally named "<X> Contracting LLC" was missed.
            "contracting",
        }
        _contractor_confirmed = (
            _fv(facts, "contractor_type")
            or _fv(facts, "percent_subcontracted")
            or any(kw in ops for kw in _186_confirm_kw)
            or any(kw in text for kw in {"general contractor", "roofing contractor",
                                          "licensed contractor", "subcontractor",
                                          "contracting"})
        )
        if _contractor_confirmed:
            _add("ACORD_186",
                 "ACORD 186 - Contractors Supplemental Application",
                 trigger_weight=0.95,
                 trigger_reason="is_contractor flag with contractor trade confirmed in document",
                 tier=TIER_RECOMMENDED,
                 reason_label="Contractor operations detected - supplements GL & WC")

    # ── Keyword / rule-based (trigger_weight 0.85) ────────────────────────────

    # ACORD 137 / 138 (CA / CO) - Commercial Auto & Garage state-section forms.
    # Beta Report §7.2 item 4 - a state-specific form may appear ONLY when:
    #   • the insured's state is supported (CA / CO), detected from operations,
    #     mailing / physical address, ANY location, or WC-payroll state
    #     (covers "insured state matches", "location in that state exists",
    #      "operations in that state exist"), AND
    #   • the matching coverage/exposure is present - auto for 137, garage/
    #     dealers for 138 ("a coverage or exposure requires that state form").
    # States come only from extracted evidence, so a CO-only insured never gets
    # CA forms (and vice-versa) - no spurious dual recommendations. Detecting
    # every state (not just the primary) means a secondary CA/CO location/op also
    # surfaces its form. The user can still pull any unlisted state form via
    # "Add more ACORD forms" ("the user manually selects that state").
    _supported_states = _supported_state_forms(facts, flags)
    if _supported_states:
        _auto_137_kw = {
            "trailer interchange", "uninsured motorist",
            "truckers", "motor carrier", "acord 137",
        }
        _has_auto_137_flag = (
            flags.get("has_auto_coverage")
            or flags.get("has_commercial_auto")
            or flags.get("has_auto_liability")
            or flags.get("has_truckers_coverage")
            or flags.get("has_motor_carrier_coverage")
        )
        # Allow keyword fallback only when no auto flag was extracted at all.
        _all_auto_flags_absent = all(
            flags.get(k) is None for k in (
                "has_auto_coverage", "has_commercial_auto", "has_auto_liability",
                "has_truckers_coverage", "has_motor_carrier_coverage",
            )
        )
        # _auto_line (computed in the ACORD 127 block) is a clear dec-page auto
        # line item - a CO/CA insured with commercial auto on the page needs the
        # state auto-section form even if the auto flag / trucking keywords missed.
        _auto_137_triggered = _has_auto_137_flag or _auto_line or (
            _all_auto_flags_absent and any(kw in search for kw in _auto_137_kw)
        )

        _garage_138_kw = {
            "garage liability", "garage keepers", "garagekeepers",
            "auto dealership", "dealer plates", "dealer operations",
            "autos left for service", "transportation plates", "acord 138",
        }
        _has_138_garage_flag = (
            flags.get("has_garage_operations")
            or flags.get("has_auto_dealer_exposure")
            or flags.get("has_garagekeepers_coverage")
            or flags.get("has_garage_coverage")
            or flags.get("has_dealers_coverage")
            or flags.get("has_garage_liability")
            or flags.get("has_garage_keepers")
        )
        _all_garage_flags_absent = all(
            flags.get(k) is None for k in (
                "has_garage_operations", "has_auto_dealer_exposure",
                "has_garagekeepers_coverage", "has_garage_coverage",
                "has_dealers_coverage", "has_garage_liability", "has_garage_keepers",
            )
        )
        _garage_138_triggered = _has_138_garage_flag or (
            _all_garage_flags_absent and any(kw in search for kw in _garage_138_kw)
        )

        # Surface the matching form for EACH supported state the insured touches.
        # Client direction (Brent): keep all state-specific forms at Needs Confirmation
        # regardless of how much evidence exists. Not every carrier requires these forms
        # even when auto is confirmed in CA/CO - keeping them here makes Primble
        # carrier-neutral. Reason label updated to reflect this explicitly.
        for _st in _supported_states:
            if _auto_137_triggered:
                _add(f"ACORD_137_{_st}",
                     f"ACORD 137 {_st} - Commercial Auto Coverages / Limits Section",
                     trigger_weight=0.85,
                     trigger_reason=f"commercial auto coverage signals detected (state: {_st})",
                     tier=TIER_NEEDS_CONFIRMATION,
                     reason_label=f"State-specific supplemental form ({_st}) - may be required depending on carrier requirements")
            if _garage_138_triggered:
                _add(f"ACORD_138_{_st}",
                     f"ACORD 138 {_st} - Garage and Dealers Coverages / Limits Section",
                     trigger_weight=0.85,
                     trigger_reason=f"garage/dealers coverage signals detected (state: {_st})",
                     tier=TIER_NEEDS_CONFIRMATION,
                     reason_label=f"State-specific supplemental form ({_st}) - may be required depending on carrier requirements")

    # ACORD 101 - Additional Remarks
    # Client feedback (Brent): ACORD 101 should NOT always be Optional.
    # When serious issues are detected (data conflicts, large/incomplete losses,
    # unusual financial ratios, subcontracting gaps, cross-doc inconsistencies)
    # it escalates to RECOMMENDED - a good narrative helps the underwriter
    # understand the account. Minor clarifications (vague ops, split limit gaps)
    # stay Optional.
    #
    # Escalation triggers → RECOMMENDED:
    #   • Cross-validation issues     (data conflicts / cross-document inconsistencies)
    #   • Loss history present but incomplete  (large losses / missing context)
    #   • Payroll/revenue ratio >85%  (unusual operations)
    #   • Subcontract >30% + no WC payroll (operational data gap)
    #
    # Minor triggers → OPTIONAL:
    #   • Vague operations description alongside GL class codes
    #   • Split auto limits incomplete
    _101_recommended_reasons: List[str] = []   # serious - escalate tier
    _101_optional_reasons:    List[str] = []   # minor - stay Optional

    if _fv(facts, "gl_class_codes_by_location") and len(ops) < 30 and not _fv(facts, "occupancy_type"):
        _101_optional_reasons.append("GL class codes present but operations description is vague (<30 chars)")

    # Operations narrative too long for its own ACORD field (Figure 29 overflow).
    # pdf_service.combined_gap_fill routes the full text to ACORD 101's Additional
    # Remarks rows losslessly, but only if ACORD 101 is actually in the packet -
    # this is what gets it there. Same threshold pdf_service uses to decide a
    # field can't hold the text, so the two stay in lockstep by construction.
    if len(ops) > _OVERFLOW_CHAR_THRESHOLD:
        _101_recommended_reasons.append(
            f"operations narrative is {len(ops)} characters - exceeds field capacity, "
            "full text continues on ACORD 101"
        )

    _payroll_str = _fv(facts, "total_payroll") or _fv(facts, "wc_payroll")
    _revenue_str = _fv(facts, "total_revenue")
    if _payroll_str and _revenue_str:
        try:
            _pr = float(re.sub(r"[^\d.]", "", str(_payroll_str)))
            _rv = float(re.sub(r"[^\d.]", "", str(_revenue_str)))
            if _rv > 0 and _pr / _rv > 0.85:
                _101_recommended_reasons.append("payroll/revenue ratio exceeds 85% - unusual operations require explanation")
        except ValueError:
            pass

    _subpct_str = _fv(facts, "percent_subcontracted")
    if _subpct_str:
        try:
            if float(re.sub(r"[^\d.]", "", str(_subpct_str))) > 30 and not _fv(facts, "wc_payroll"):
                _101_recommended_reasons.append("subcontract percentage >30% with no WC payroll on file")
        except ValueError:
            pass

    if flags.get("has_loss_history") and not _fv(facts, "num_claims") and not _fv(facts, "total_incurred"):
        _101_recommended_reasons.append("loss history detected but claim count and incurred amount are missing - narrative required")

    # Large losses detected - Brent Q1: "Large losses" is an explicit escalation trigger.
    # Mirrors the SQS thresholds in sqs_service.py (_calculate_p4_loss_history).
    _num_claims_str    = _fv(facts, "num_claims")
    _total_incurred_str = _fv(facts, "total_incurred")
    if _num_claims_str:
        try:
            _nc = int(float(re.sub(r"[^\d.]", "", str(_num_claims_str))))
            if _nc > 3:
                _101_recommended_reasons.append(
                    f"{_nc} prior claims detected - narrative recommended to explain loss history"
                )
        except (ValueError, TypeError):
            pass
    if _total_incurred_str:
        try:
            _ti = float(re.sub(r"[^\d.]", "", str(_total_incurred_str)))
            if _ti > 100_000:
                _101_recommended_reasons.append(
                    f"Total incurred losses ${_ti:,.0f} - narrative recommended to provide context for underwriter"
                )
        except (ValueError, TypeError):
            pass

    if flags.get("auto_split_limits"):
        _limit_val = str(_fv(facts, "auto_liability_limit") or "")
        if _limit_val.count("/") < 2:
            _101_optional_reasons.append(
                "split auto limits selected but not all three components found "
                "(BI per person / BI per accident / PD per accident) - additional remarks needed"
            )

    _cross_issues = cross_validate(facts, flags, [m["form_id"] for m in matches])
    # Client Q1 (Workstream 4): genuine "data conflicts" / "cross-document
    # inconsistencies" escalate ACORD 101 to Recommended. A single HARD conflict is
    # already a real underwriting concern, so it escalates on its own; a lone SOFT
    # warning (formatting / extraction variance) still needs a second issue before
    # it escalates, so one minor mismatch does not force 101 into every packet.
    _cross_hard = [i for i in _cross_issues if isinstance(i, dict) and i.get("type") == "hard_stop"]
    if _cross_hard or len(_cross_issues) >= 2:
        # A genuine hard conflict, or multiple independent issues → escalate.
        _101_recommended_reasons.append(
            f"cross-validation flagged {len(_cross_issues)} issue(s) - data conflicts or inconsistencies require explanation"
        )
    elif _cross_issues:
        # A single SOFT warning only → likely a minor formatting mismatch or
        # extraction variance; keep as Optional so the broker can add context if
        # needed without forcing an ACORD 101 into every single-document submission.
        _101_optional_reasons.append(
            f"cross-validation flagged {len(_cross_issues)} issue(s) - review may be needed"
        )

    # Prior carrier adverse action (Brent feedback): producer confirmed via ARQ
    # that the carrier nonrenewed, cancelled, or declined — a narrative is required
    # so the underwriter understands the underwriting concern driving the move.
    if flags.get("prior_carrier_adverse_action"):
        _carrier_reason = _fv(facts, "carrier_marketing_reason") or "carrier issue indicated"
        _101_recommended_reasons.append(
            f"carrier adverse action confirmed by producer ({_carrier_reason}) - "
            "narrative required to explain underwriting concern"
        )

    # Prior carrier issues (client Q1/Q2 Workstream 4): the client was explicit that
    # ACORD 101 should NOT over-trigger. A merely MISSING prior-carrier name on a
    # renewal is weak evidence - it is usually just an extraction miss, not a real
    # underwriting concern - so it must NOT auto-escalate 101 to Recommended (that is
    # exactly the over-triggering the client warned against). Keep it as an OPTIONAL
    # clarification the broker may choose to add. A GENUINE carrier issue (nonrenewal /
    # cancellation / declination) escalates to Recommended separately, via the
    # producer-confirmed `prior_carrier_adverse_action` path above.
    # Use only the extracted is_renewal flag. Word-matching "renew" in ops/lobs
    # produces too many false positives (any description mentioning "annual
    # renewal period" or a LOB labelled "renewal" would trip it).
    _is_renewal_type = bool(flags.get("is_renewal"))
    if _is_renewal_type and not _fv(facts, "prior_carrier"):
        _101_optional_reasons.append(
            "renewal submission without prior carrier name - additional remarks may help provide coverage history"
        )

    # Missing context (client Q1 Workstream 4): a multi-line submission with no
    # operations description gives the underwriter no account context.
    _active_line_count = sum(
        1 for k in (
            "has_general_liability", "has_auto_coverage", "has_property_coverage",
            "has_workers_comp", "has_umbrella",
        )
        if flags.get(k) is True
    )
    # Accept occupancy_type or account_description as sufficient context so a
    # property submission with "12 unit apartment building" as the occupancy
    # doesn't produce a spurious ACORD 101 merely because operations_description
    # wasn't separately populated by the LLM extraction pass.
    _has_ops_context = bool(
        _fv(facts, "operations_description")
        or _fv(facts, "occupancy_type")
        or _fv(facts, "account_description")
    )
    if _active_line_count >= 2 and not _has_ops_context:
        _101_recommended_reasons.append(
            "multi-line submission without operations description - narrative needed for underwriter account context"
        )

    _101_all_reasons = _101_recommended_reasons + _101_optional_reasons
    if _101_all_reasons:
        _101_tier = TIER_RECOMMENDED if _101_recommended_reasons else TIER_OPTIONAL
        _101_label = (
            "Narrative recommended - losses, conflicts, or unusual operations detected"
            if _101_recommended_reasons else
            "Additional remarks may be needed for clarifications"
        )
        _add("ACORD_101",
             "ACORD 101 - Additional Remarks",
             trigger_weight=0.85,
             trigger_reason="; ".join(_101_all_reasons),
             template_pending=True,
             tier=_101_tier,
             reason_label=_101_label)

    _133_kw = {
        "builders risk", "builder's risk", "course of construction",
        "construction loan", "ground-up construction",
    }
    _has_br = flags.get("has_builders_risk")
    _br_kw_in_text = any(kw in text for kw in _133_kw)
    # Require at least one extracted builders-risk fact as corroboration, no
    # matter which signal (flag or keyword) got there first. This prevents a
    # BARE keyword match from adding ACORD 133 on its own - "builders risk"
    # showing up in an exclusions clause, a coverage checklist, an endorsement
    # schedule, or a sentence denying the coverage ("does NOT include builders
    # risk") all contain the keyword with zero real exposure behind them.
    # `_br_kw_in_text or (...)` used to make the keyword alone sufficient,
    # silently skipping the corroboration this comment already promised -
    # that was the actual bug (client report 2026-08-07: ACORD 133 hard stop
    # fired on a package with no builders risk exposure at all). A real BR
    # submission always yields at least one of these facts, so requiring one
    # costs nothing on genuine cases and closes the false-positive path.
    _br_facts = any([
        _fv(facts, "builders_risk_project_address"),
        _fv(facts, "builders_risk_project_cost"),
        _fv(facts, "builders_risk_completion_date"),
    ])
    if _br_facts and (_has_br or _br_kw_in_text):
        _add("ACORD_133",
             "ACORD 133 - Builders Risk Application",
             trigger_weight=0.85,
             trigger_reason="builders risk flag or construction keywords detected",
             template_pending=True,
             tier=TIER_RECOMMENDED,
             reason_label="Builders Risk / construction project exposure detected")

    _160_kw = {
        "inland marine", "contractor's equipment", "contractors equipment",
        "motor truck cargo", "equipment schedule", "installation floater",
        "scheduled equipment", "tool floater", "installation risk",
        "equipment breakdown",
        # Decision_Tree.txt ACORD 160 cue (L440): bare "floater" (always means an
        # inland-marine scheduled-property floater - unambiguous, safe to add).
        "floater",
    }
    _has_im = flags.get("has_inland_marine")
    _im_kw_in_text = any(kw in text for kw in _160_kw)
    _im_facts = any([
        _fv(facts, "inland_marine_total_value"),
        _fv(facts, "inland_marine_transit_limit"),
        bool(_fv(facts, "inland_marine_items")),
    ])
    # Flag-alone is not sufficient - require keyword or extracted inland marine
    # data as corroboration (prevents firing when the flag was set on a brief
    # incidental mention in ops description without actual IM coverage).
    if _im_kw_in_text or (_has_im is True and _im_facts) or (_has_im is None and _im_kw_in_text):
        _add("ACORD_160",
             "ACORD 160 - Inland Marine Application",
             trigger_weight=0.85,
             trigger_reason="inland marine flag or equipment / cargo keywords detected",
             template_pending=True,
             tier=TIER_OPTIONAL,
             reason_label="Possible Inland Marine / equipment exposure")

    # TODO: Add a dedicated crime/fidelity ACORD form (e.g. ACORD 140 or a crime-specific form)
    # once the correct form template is added to forms_database. ACORD 137 is a commercial
    # AUTO form and must NOT be used for crime/fidelity coverage detection.

    # ACORD 138 (national) - Cyber / Network Security: intentionally out of
    # scope for now. The state-variant ACORD 138 CA/CO forms in the form DB
    # cover Garage and Dealers (not Cyber), so cyber signals must NOT trigger
    # them - that produced wrong-form recommendations. Crime (ACORD 137) is
    # likewise out of scope. Both remain pending until proper national
    # templates are added.

    # ACORD 186 - flag-matched above; keyword fallback for any submission with
    # contractor-type operations. Per Decision_Tree.txt L461:
    #   "IF 125.operations.contains(contracting) THEN add ACORD_186"
    # The spec triggers on operations alone, independent of the GL flag - so
    # WC-only or pure-operations contractor submissions also get 186.
    _186_kw = {
        "roofing", "demolition", "scaffolding",
        "blasting", "general contractor", "licensed contractor",
        "excavation", "underground", "crane", "rigging", "pile driving",
        "residential construction", "commercial construction",
        # Decision_Tree.txt L461: operations.contains("contracting").
        "contracting",
    }
    if (not _already_matched("ACORD_186")
            and any(kw in ops for kw in _186_kw)):
        _add("ACORD_186",
             "ACORD 186 - Contractors Supplemental Application",
             trigger_weight=0.85,
             trigger_reason="contractor-type operations keywords detected in 125 operations description",
             tier=TIER_RECOMMENDED,
             reason_label="Contractor operations detected - supplements GL & WC")

    # ACORD 141 - property + valuation/coinsurance detail or multiple locations
    _141_kw = {
        "agreed value", "coinsurance", "replacement cost value", "rcv", "acv",
        "actual cash value", "scheduled property", "property schedule",
        "period of restoration", "business income limit", "wind/hail deductible",
        "flood deductible", "earthquake deductible",
    }
    # Property present via the confirmed flag OR a recovered dec-page property line
    # (mirrors the ACORD 140 recall fix) AND (multiple locations OR valuation detail).
    if (not _already_matched("ACORD_141")
            and (flags.get("has_property_coverage") or _prop_line)
            and (flags.get("has_multiple_locations") or any(kw in text for kw in _141_kw))):
        _add("ACORD_141",
             "ACORD 141 - Property Schedule",
             trigger_weight=0.90,
             trigger_reason="property coverage with multiple locations or detailed valuation/coinsurance data detected",
             template_pending=True,
             tier=TIER_RECOMMENDED,
             reason_label="Detailed property values or multiple locations detected")

    # ACORD 25 keyword path - only if not already flag-matched above.
    # "certificate holder" REMOVED: it is a standard printed field on dec pages,
    # policies, and almost every commercial document - fires on random uploads.
    # "coi" also excluded: appears in filenames, banners, unrelated abbreviations.
    # Only unambiguous COI-specific phrases remain.
    _25_kw = {
        "certificate of liability insurance", "certificate of liability",
        "proof of insurance", "evidence of liability", "acord 25",
        "liability certificate", "additional insured certificate",
        "certificate required", "certificate requested",
    }
    if not _already_matched("ACORD_25") and any(kw in text for kw in _25_kw):
        _25kw_is_source = bool(flags.get("is_certificate_doc"))
        _add("ACORD_25",
             "ACORD 25 - Certificate of Liability Insurance",
             trigger_weight=0.85,
             trigger_reason="certificate keywords detected in document text",
             tier=TIER_NEEDS_CONFIRMATION,
             reason_label=("Detected as an uploaded certificate - generate a clean copy only if needed"
                           if _25kw_is_source else "Certificate of Insurance referenced - confirm if needed"),
             is_source_document=_25kw_is_source)

    _28_kw = {
        "mortgagee", "evidence of insurance", "loss payee",
        "evidence of property", "lender evidence", "acord 28",
        "property certificate", "lender requirement", "mortgage lender",
    }
    _cert_holder_val = (_fv(facts, "certificate_holder") or "").lower()
    _mortgagee_val   = (_fv(facts, "mortgagee_name") or "").lower()
    _28_entity_signal = any(
        w in _cert_holder_val or w in _mortgagee_val
        for w in ["bank", "lender", "mortgage", "financial", "credit union", "trust"]
    )
    # Spec L496-499: ACORD 28 trigger is "If a lender, landlord or other party
    # requests evidence of the property policy" - a standalone lender/mortgagee
    # request must trigger 28 even without a property coverage flag on the
    # uploaded document (e.g. a lender request letter without dec page).
    _28_strong_lender_signal = (
        _28_entity_signal
        or flags.get("has_mortgagee_requirement")
        or flags.get("has_loss_payee_requirement")
        or any(kw in text for kw in ("mortgagee", "evidence of property", "lender evidence",
                                      "lender requirement", "mortgage lender", "acord 28"))
    )
    if not _already_matched("ACORD_28") and (
        (flags.get("has_property_coverage") and (_28_entity_signal or any(kw in text for kw in _28_kw)))
        or _28_strong_lender_signal
    ):
        # `is_certificate_doc` is set for an uploaded ACORD 25 (liability COI) OR an
        # uploaded ACORD 28 (property evidence) - the flag cannot say WHICH. Only call
        # ACORD 28 a SOURCE document (already-provided property evidence) when a
        # property-evidence signal is ALSO present, so a liability-only certificate
        # upload doesn't mislabel 28 as "already provided / generate a clean copy".
        _28_is_source = bool(flags.get("is_certificate_doc")) and bool(_28_strong_lender_signal)
        _add("ACORD_28",
             "ACORD 28 - Evidence of Commercial Property Insurance",
             trigger_weight=0.85,
             trigger_reason="mortgagee/lender/loss payee evidence request detected",
             template_pending=True,
             tier=TIER_NEEDS_CONFIRMATION,
             reason_label=("Detected as uploaded property evidence - generate a clean copy only if needed"
                           if _28_is_source else "Lender / mortgagee evidence - confirm if needed"),
             is_source_document=_28_is_source)

    # ── Consistency backstop: ACORD 186 supplements GL (Decision_Tree L91/L454).
    # A confirmed contractor virtually always carries General Liability - never
    # recommend the contractor SUPPLEMENT (186) without its BASE form (126). If
    # 186 matched but 126 did not (the coverage line + flag were both missed),
    # surface 126 for confirmation.
    if _already_matched("ACORD_186") and not _already_matched("ACORD_126"):
        _add("ACORD_126",
             "ACORD 126 - Commercial General Liability Section",
             trigger_weight=0.85,
             trigger_reason="contractor operations (ACORD 186) imply General Liability exposure",
             tier=TIER_NEEDS_CONFIRMATION,
             reason_label="Contractor operations imply General Liability - confirm")

    # ── Subcontracting WC backstop ─────────────────────────────────────────────
    # The cross-form validator (and ACORD 186 data) flag WC payroll obligations
    # when percent_subcontracted > 30. That warning appears in the UI but the form
    # that resolves it (ACORD 130) was not being recommended because has_workers_comp
    # is unset and the dec-page WC line was missed. Surface it as Needs Confirmation
    # whenever the subcontracting threshold triggers the known obligation.
    if _already_matched("ACORD_186") and not _already_matched("ACORD_130"):
        _sub_pct_val = _fv(facts, "percent_subcontracted")
        _sub_pct = 0.0
        if _sub_pct_val:
            try:
                _sub_pct = float(re.sub(r"[^\d.]", "", str(_sub_pct_val)))
            except ValueError:
                pass
        if _sub_pct > 30:
            _add("ACORD_130",
                 "ACORD 130 - Workers Compensation Application",
                 trigger_weight=0.85,
                 trigger_reason=(
                     f"contractor with {_sub_pct:.0f}% subcontracting implies WC payroll "
                     "obligation (>30% threshold per ACORD 186 cross-validation rule)"
                 ),
                 template_pending=True,
                 tier=TIER_NEEDS_CONFIRMATION,
                 reason_label="Subcontracting >30% - confirm Workers' Comp coverage")

    # ── Uploaded-source-document backstop (Beta Report §7 "Situation 3") ───────
    # If the broker uploaded a filled ACORD form (its printed number was detected)
    # but no trigger surfaced it above, add it so an already-provided form is never
    # silently dropped from the list. It is tagged is_source_document via _add()'s
    # generalised detection and labelled "generate a clean copy only if needed".
    # For the state-variant forms, only backstop a variant whose state the insured
    # actually touches (or whose state edition was printed) - never recommend a CA
    # form to a CO-only insured. Tier = Needs Confirmation (the broker confirms
    # whether a fresh copy is needed); this mirrors the existing 25/28 default.
    for _up_fid in sorted(_uploaded_forms):
        if _already_matched(_up_fid):
            continue
        # No state-guessing needed: a 137/138 variant only reaches _uploaded_forms
        # when its exact state edition stamp ("ACORD 137 CA (2023/01)") was printed,
        # which is itself direct evidence of that state's form. The detector never
        # emits a bare/ambiguous 137/138.
        _add(_up_fid,
             _FORM_NAMES.get(_up_fid, _up_fid),
             trigger_weight=0.85,
             trigger_reason="uploaded ACORD form detected by printed form-number stamp",
             tier=TIER_NEEDS_CONFIRMATION,
             is_source_document=True,
             reason_label="Detected as an uploaded ACORD form - generate a clean copy only if needed")

    # ── Sort: blended confidence descending (ACORD_125 naturally stays first) ──
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches


def score_extra_forms(facts: dict, triggered_ids: set, all_forms: List[dict]) -> List[dict]:
    """
    Score every form that was NOT triggered by match_forms_deterministic, so the
    'Add more ACORD forms' section can also show a live field-coverage percentage.

    Returns the same shape as match_forms_deterministic items but with
    trigger_weight=0 (no rule fired) - confidence is pure field_coverage × 0.6.
    Items with confidence=0 (no schema + not triggered) are still returned so
    the UI can list them; they will show 0%.

    Sorted by confidence descending.
    """
    scored: List[dict] = []
    for form in all_forms:
        fid = form["form_id"]
        if fid in triggered_ids:
            continue
        confidence, reason = _compute_confidence(fid, facts, trigger_weight=0.0, triggered=False)
        _, filled, total = _score_field_coverage(fid, facts)
        scored.append({
            "form_id":       fid,
            "form_name":     form.get("form_name", fid),
            "description":   form.get("description", ""),
            "confidence":    confidence,
            "reason":        reason,
            "fields_filled": filled,
            "fields_total":  total,
        })
    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return scored


def match_forms(facts: dict, flags: dict, all_forms: List[dict], text: str = "") -> List[dict]:
    return match_forms_deterministic(facts, flags, text=text)


def active_document_text(session: dict) -> str:
    """The uploaded text an LLM is allowed to read: EXCLUDED DOCUMENTS REMOVED.

    "Exclude" is an explicit user action (`reclassify_document`, action="exclude"
    - "this document is not part of this submission"). Every other consumer in
    the pipeline already honours it via
    ``active_docs = [d for d in docs if not d.get("excluded")]``:
    extraction, fact merging, form matching, integrity, SQS - see
    services/extraction_pipeline.py. The two places that built the gap-fill
    prompt did NOT, so a document the user had deleted was still shipped to the
    model as "RAW DOCUMENT TEXT (AUTHORITATIVE SOURCE)" - and the prompt tells
    the model that text OUTRANKS the extracted facts, which had correctly
    dropped it. A removed document could therefore overwrite a correct value.

    The `or` fallback mirrors extraction_pipeline's and is load-bearing: if every
    document were excluded, an empty string here makes _fill_unmatched_with_gpt
    return immediately ("no raw_text provided - skipping GPT fill"), silently
    losing EVERY gap-filled field on every form. Degrading to the old behaviour
    is strictly better than that.
    """
    docs = session.get("docs") or []
    active = [d for d in docs if isinstance(d, dict) and not d.get("excluded")]
    if not active:
        active = [d for d in docs if isinstance(d, dict)]
    return " ".join(d.get("text", "") for d in active)


def process_single_form(form_meta: dict, session: dict, pre_filled_gpt: dict = None) -> dict:
    tpl              = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
    schema           = extract_form_schema(tpl, form_id=form_meta["form_id"])
    raw_text         = active_document_text(session)
    # Merge flags into facts so _derive_indicator and GPT both see has_general_liability,
    # is_contractor, has_auto_coverage, etc. for checkbox resolution.
    facts_with_flags = {**session["facts"], **session.get("flags", {})}
    # Guard blanks: boxes a post-fill guard emptied because the value was not
    # possible for that box. They are invisible to `evaluate_stops` (which
    # validates FACTS, not stamped VALUES), which is why four consecutive runs
    # showed "no warnings" on forms where a dozen fabricated values had been
    # caught and removed. Carried through to field QA so the pre-download review
    # can say so.
    guard_blanks: list = []
    mapped, confidence = map_facts_to_form(
        facts_with_flags, schema,
        form_id=form_meta["form_id"],
        raw_text=raw_text,
        pre_filled_gpt=pre_filled_gpt,
        guard_report=guard_blanks,
    )

    hard_stops, soft_stops = run_field_validations(mapped)
    if hard_stops:
        logger.warning(
            "Field validation hard stops for form %s (flagged for review): %s",
            form_meta["form_id"], hard_stops,
        )
    if soft_stops:
        logger.info(
            "Field validation soft stops for form %s: %s",
            form_meta["form_id"], soft_stops,
        )

    selected_ids     = session.get("selected_form_ids", []) + [form_meta["form_id"]]
    cross            = cross_validate(session["facts"], session["flags"], selected_ids)
    # §6.3/§6.4: feed classified-document presence + loss-run insured match so the
    # narrative/loss-history floors actually apply here. The package score averages
    # these per-form scores, so without this the floors stay bypassed (the confirmed
    # "Narrative 20% / Loss 10% despite uploaded docs" symptom).
    _docs        = session.get("docs", []) or []
    _present     = {str(d.get("doc_type") or "").strip() for d in _docs if isinstance(d, dict) and not d.get("excluded")}
    _has_narr    = "narrative" in _present
    _has_loss    = "loss_run" in _present
    _loss_match  = _check_loss_run_insured_match(_docs, _fv(session["facts"], "applicant_name"))
    _narr_text   = _extract_narrative_doc_text(_docs)
    sqs              = calculate_sqs(
        facts=session["facts"], flags=session["flags"],
        mapped_data=mapped, form_schema=schema,
        selected_form_ids=[form_meta["form_id"]],
        hard_stops=session.get("hard_stops", []),
        soft_stops=session.get("soft_stops", []),
        tier2_score=session.get("tier2_score", 50),
        form_id=form_meta["form_id"],
        schema_size=len(schema),
        fields_mapped=sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None")),
        # Spec: producer-edits=1.00, AI-high=0.85, AI-low=0.50.
        confidence_dict=confidence,
        has_narrative_doc=_has_narr,
        has_loss_run_doc=_has_loss,
        loss_run_match=_loss_match,
        cross_issues_full=cross,
        narrative_doc_text=_narr_text,
    )
    pdf_bytes = fill_pdf(tpl, mapped, confidence)
    return {
        "form_id":    form_meta["form_id"],
        "form_name":  form_meta["form_name"],
        "form":       form_meta,
        "schema":     schema,
        "mapped":     mapped,
        "confidence": confidence,
        "sqs":        sqs,
        "cross":      cross,
        "pdf_bytes":  pdf_bytes,
        "guard_blanks": guard_blanks,
    }
