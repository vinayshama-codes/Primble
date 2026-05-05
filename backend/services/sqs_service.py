# sqs_service.py

import json
import logging
import re
from datetime import datetime
from typing import List, Tuple, Dict, Optional

from utils.validators import run_field_validations
from services.extraction_service import _fv, _focr

logger = logging.getLogger(__name__)

# ── SQS Version Control ───────────────────────────────────────────────────────
SQS_MODEL_VERSION = "2.1.0"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _token_diversity(text: str) -> float:
    """Type-token ratio (unique words / total words). Returns 0.0 for empty input."""
    words = str(text).lower().split()
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _to_int(v) -> int | None:
    """Parse a monetary/limit string to int. Returns None on failure."""
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "").replace("$", "").strip()))
    except Exception:
        return None


def _to_float(v) -> float | None:
    """Parse a numeric string to float. Returns None on failure."""
    if v is None:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(v)))
    except Exception:
        return None


# ── Tier field definitions ────────────────────────────────────────────────────

TIER1_FIELDS = {
    "producer_name":     "Producer / Agency name",
    "applicant_name":    "Applicant legal name",
    "mailing_address":   "Applicant mailing address",
    "effective_date":    "Proposed effective date",
    "lines_of_business": "Lines of business requested",
}
TIER1_CONTACT = ("contact_name", "contact_phone", "contact_email")

TIER2_FIELDS = {
    "fein":                   "FEIN / Tax ID",
    "entity_type":            "Business entity type",
    "operations_description": "Operations description",
    "total_revenue":          "Annual revenue",
    "prior_carrier":          "Prior carrier name",
    "num_employees":          "Number of employees",
    "years_in_business":      "Years in business",
    "naics_code":             "NAICS / industry code",
    "num_claims":             "Number of prior claims",
    "total_payroll":          "Annual payroll",
}


# ── Tier checks ───────────────────────────────────────────────────────────────

def check_tier1(facts: dict, flags: dict) -> Tuple[bool, List[str]]:
    if flags.get("is_certificate_doc") or flags.get("has_certificate_request"):
        missing = []
        if not _fv(facts, "applicant_name"):
            missing.append("Applicant legal name")
        if not _fv(facts, "effective_date"):
            missing.append("Proposed effective date")
        return len(missing) == 0, missing
    missing = []
    is_dec_page          = flags.get("_doc_type") == "dec_page"
    skip_producer_fields = is_dec_page
    for field, label in TIER1_FIELDS.items():
        if skip_producer_fields and field == "producer_name":
            continue
        val = _fv(facts, field)
        if not val or (isinstance(val, list) and not val):
            missing.append(label)
    if not skip_producer_fields and not any(_fv(facts, f) for f in TIER1_CONTACT):
        missing.append("Contact information")
    return len(missing) == 0, missing


def check_tier2(facts: dict) -> Tuple[int, List[str]]:
    missing = [label for field, label in TIER2_FIELDS.items() if not _fv(facts, field)]
    score   = max(0, round(100 - len(missing) * (100 / len(TIER2_FIELDS))))
    return score, missing


def validate_effective_date_window(facts: dict) -> tuple | None:
    from datetime import datetime, timedelta
    eff = _fv(facts, "effective_date")
    if not eff:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            d = datetime.strptime(str(eff).strip(), fmt)
            now = datetime.now()
            if d < now - timedelta(days=730):
                return ("soft", "effective_date is more than 2 years in the past")
            if d > now + timedelta(days=730):
                return ("soft", "effective_date is more than 2 years in the future")
            return None
        except ValueError:
            continue
    return ("soft", "effective_date format unrecognized")


_VALID_NAICS_PREFIXES = {
    "11","21","22","23","31","32","33","42","44","45",
    "48","49","51","52","53","54","55","56","61","62",
    "71","72","81","92"
}

def validate_naics_code(facts: dict) -> tuple | None:
    code = str(_fv(facts, "naics_code") or "").strip()
    if not code or code.lower() in {"null","none","n/a",""}:
        return None
    if not code.isdigit() or not (2 <= len(code) <= 6):
        return ("soft", f"NAICS code '{code}' is not 2-6 digits")
    if code[:2] not in _VALID_NAICS_PREFIXES:
        return ("soft", f"NAICS prefix '{code[:2]}' is not a valid industry sector")
    return None


# ── Stop evaluation ───────────────────────────────────────────────────────────

def evaluate_stops(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    """
    Evaluate hard and soft stops from facts/flags.
    Cross-doc hard stops appended by caller after check_doc_consistency().
    """
    hard, soft = run_field_validations(facts)

    date_issue = validate_effective_date_window(facts)
    if date_issue:
        soft.append(date_issue[1])

    naics_issue = validate_naics_code(facts)
    if naics_issue:
        soft.append(naics_issue[1])

    # ── GL ────────────────────────────────────────────────────────────────────
    if flags.get("gl_is_claims_made") and not _fv(facts, "retro_date"):
        soft.append("GL policy is claims-made — retro date is required")
    if flags.get("has_general_liability") and not _fv(facts, "total_revenue") and not _fv(facts, "total_payroll"):
        soft.append("GL coverage detected but no revenue or payroll found")
    if flags.get("has_general_liability"):
        codes = _fv(facts, "gl_class_codes_by_location") or []
        if isinstance(codes, list) and not codes:
            soft.append("GL coverage detected but no class codes found")

    # ── Property ──────────────────────────────────────────────────────────────
    if flags.get("has_property_coverage"):
        min_cope = {
            "locations":             bool(_fv(facts, "locations")),
            "occupancy_type":        bool(_fv(facts, "occupancy_type")),
            "construction_type":     bool(_fv(facts, "construction_type")),
            "building_or_bpp_value": bool(
                _fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")
            ),
        }
        missing_min = [k.replace("_", " ") for k, v in min_cope.items() if not v]
        if missing_min:
            hard.append("Property Minimum Viable COPE incomplete - missing: " + ", ".join(missing_min))
        else:
            carrier_cope = {k: bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]}
            missing_c = [k.replace("_", " ") for k, v in carrier_cope.items() if not v]
            if missing_c:
                soft.append("Carrier-Grade COPE incomplete — SQS capped at 85. Missing: " + ", ".join(missing_c))

        if flags.get("property_has_bi_coverage"):
            if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
                soft.append("Business Income limit present but Period of Restoration is missing")
            elif not _fv(facts, "business_income_limit"):
                soft.append("Business Income coverage detected — BI limit and Period of Restoration should be provided")

        if flags.get("property_has_peril_deductibles"):
            missing_perils = [
                p for p, k in [
                    ("wind/hail",  "property_deductible_wind"),
                    ("earthquake", "property_deductible_earthquake"),
                    ("flood",      "property_deductible_flood"),
                ]
                if not _fv(facts, k)
            ]
            if missing_perils:
                soft.append("Peril-specific deductibles referenced — define amounts for: " + ", ".join(missing_perils))

        if not _fv(facts, "valuation_method"):
            soft.append("Property valuation method not specified — select RCV or ACV")

    # ── Workers Comp ──────────────────────────────────────────────────────────
    if flags.get("has_workers_comp"):
        if not _fv(facts, "wc_payroll") and not _fv(facts, "total_payroll"):
            soft.append("Workers Comp detected but payroll is missing")
        if flags.get("wc_has_monopolistic_state"):
            soft.append("Monopolistic WC state detected (ND/OH/WA/WY) — must use state fund")
            if not _fv(facts, "wc_monopolistic_payroll"):
                hard.append("Monopolistic WC state detected but wc_monopolistic_payroll breakdown is missing")
        if flags.get("wc_multi_state") and not _fv(facts, "wc_payroll_by_state"):
            soft.append("Multi-state WC — payroll breakdown by state and class code required")

    # ── Umbrella ──────────────────────────────────────────────────────────────
    if flags.get("has_umbrella") and not _fv(facts, "gl_limits") and not _fv(facts, "auto_liability_limit"):
        hard.append("Umbrella detected but no underlying GL or Auto limits found")

    # ── ACORD 127: Auto coverage integrity ────────────────────────────────────
    if flags.get("has_auto_coverage"):
        auto_limit_structure = _fv(facts, "auto_liability_structure")
        if flags.get("auto_split_limits") or auto_limit_structure == "split":
            bi_pp = _fv(facts, "bi_per_person")
            bi_pa = _fv(facts, "bi_per_accident")
            pd_pa = _fv(facts, "pd_per_accident")
            if not all([bi_pp, bi_pa, pd_pa]):
                hard.append(
                    "auto_split_limits_incomplete: "
                    "Split liability limits incomplete — all three components required."
                )

        if flags.get("auto_has_physical_damage"):
            comp_ded = _fv(facts, "auto_deductible_comp")
            coll_ded = _fv(facts, "auto_deductible_collision")
            if not comp_ded or not coll_ded:
                soft.append("Physical damage coverage present but deductibles not specified.")

        if flags.get("has_umbrella"):
            umb_val  = _to_int(_fv(facts, "umbrella_limit"))
            auto_val = _to_int(_fv(facts, "auto_liability_limit"))
            _min_req = 1_000_000
            if umb_val and auto_val and auto_val < _min_req:
                hard.append(
                    f"auto_umbrella_attachment_failure: "
                    f"Auto liability limit ({auto_val:,}) is below the minimum "
                    f"({_min_req:,}) required for umbrella attachment."
                )

    # ── ACORD 131: Umbrella stack integrity ───────────────────────────────────
    if flags.get("has_umbrella"):
        if flags.get("gl_is_claims_made") and not _fv(facts, "retro_date"):
            if "GL policy is claims-made — retro date is required" not in soft:
                soft.append("Claims-made GL policy requires retro date for umbrella attachment.")

        if flags.get("has_workers_comp"):
            el_limit = _fv(facts, "employers_liability_limits")
            if not el_limit:
                soft.append("Umbrella attaches over WC but Employers Liability limits not provided.")
            else:
                el_val = _to_int(el_limit)
                if el_val and el_val < 100_000:
                    soft.append(
                        f"Employers Liability limit ({el_val:,}) is below the standard minimum (100,000)."
                    )

        umb_eff = _fv(facts, "umbrella_effective_date")
        gl_eff  = _fv(facts, "effective_date")
        if umb_eff and gl_eff and umb_eff != gl_eff:
            soft.append("Umbrella and GL policy periods misaligned.")

        umb_exp = _fv(facts, "umbrella_expiration_date")
        gl_exp  = _fv(facts, "expiration_date")
        if umb_exp and gl_exp and umb_exp != gl_exp:
            soft.append("Umbrella and GL expiration dates misaligned.")

        sir    = _to_int(_fv(facts, "umbrella_sir"))
        gl_ded = _to_int(_fv(facts, "gl_deductible"))
        if sir and gl_ded and sir < gl_ded:
            soft.append(
                f"Umbrella SIR ({sir:,}) is lower than GL deductible ({gl_ded:,}) — verify attachment."
            )

    return hard, soft


# ── Risk transfer compliance checklist ───────────────────────────────────────

def risk_transfer_check(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    """Advisory-only compliance checklist for risk transfer requirements."""
    checklist: List[dict] = []

    rt = facts.get("risk_transfer")
    if isinstance(rt, dict) and "value" in rt:
        rt = rt["value"]
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = {}
    if not isinstance(rt, dict):
        rt = {}

    if rt.get("additional_insured_required") is True or flags.get("has_additional_insured_requirement"):
        item: dict = {
            "check":   "additional_insured",
            "label":   "Additional Insured Endorsement",
            "status":  "required",
            "message": "Additional insured requirement detected.",
        }
        if "ACORD_25" not in selected_form_ids:
            item["advisory"] = (
                "ACORD 25 not included — consider adding it to document "
                "additional insured status."
            )
        checklist.append(item)

    ai_names = rt.get("additional_insured_names") or []
    if isinstance(ai_names, list) and ai_names:
        checklist.append({
            "check":   "additional_insured_names",
            "label":   "Additional Insured Names",
            "status":  "info",
            "message": "Additional insured(s) identified: " + ", ".join(str(n) for n in ai_names),
        })

    if rt.get("waiver_of_subrogation_required") is True or flags.get("has_waiver_of_subrogation"):
        checklist.append({
            "check":   "waiver_of_subrogation",
            "label":   "Waiver of Subrogation",
            "status":  "required",
            "message": "WOS endorsement needed — waiver of subrogation requirement detected.",
        })

    if rt.get("primary_noncontributory_required") is True or flags.get("has_primary_noncontributory"):
        checklist.append({
            "check":   "primary_noncontributory",
            "label":   "Primary & Non-Contributory",
            "status":  "required",
            "message": "PNC endorsement needed — primary and non-contributory requirement detected.",
        })

    wording = rt.get("specific_wording_requirements")
    if wording:
        checklist.append({
            "check":   "specific_wording",
            "label":   "Specific Wording Requirements",
            "status":  "advisory",
            "message": f"Specific endorsement wording required: {wording}",
        })

    return checklist


# ── Cross-validation ──────────────────────────────────────────────────────────

def cross_validate(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    """Form-specific cross-validation checks."""
    issues: List[dict] = []

    if not _fv(facts, "applicant_name"):
        issues.append({"type": "hard_stop", "message": "Named insured missing — required on all forms"})

    fein = _fv(facts, "fein", "")
    if fein and len(str(fein).replace("-", "").replace(" ", "")) not in (9, 0):
        issues.append({"type": "warning", "message": f"FEIN format appears invalid: '{fein}'"})

    if not _fv(facts, "effective_date"):
        issues.append({"type": "warning", "message": "Policy effective date missing"})

    if "ACORD_140" in selected_form_ids and not _fv(facts, "locations"):
        issues.append({"type": "hard_stop", "message": "ACORD 140 selected but no property locations found"})

    if flags.get("has_general_liability"):
        if "ACORD_126" not in selected_form_ids:
            issues.append({"type": "warning", "message": "GL coverage detected — ACORD 126 should be included"})
        _locs = _fv(facts, "gl_class_codes_by_location") or []
        if isinstance(_locs, list) and _locs and not _fv(facts, "operations_description"):
            issues.append({"type": "warning", "message": "GL class codes present but no operations description"})
        if flags.get("is_contractor"):
            pct = _to_float(_fv(facts, "percent_subcontracted"))
            wc  = _to_float(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll"))
            if pct and pct > 30 and not wc:
                issues.append({"type": "warning", "message": f"High subcontracting ({pct:.0f}%) with no WC payroll"})

    wc_pay  = _to_float(_fv(facts, "wc_payroll"))
    tot_pay = _to_float(_fv(facts, "total_payroll"))
    if wc_pay and tot_pay and tot_pay > 0:
        diff_pct = abs(wc_pay - tot_pay) / tot_pay
        if diff_pct > 0.20:
            issues.append({"type": "warning", "message": f"WC payroll differs from total payroll by {diff_pct * 100:.0f}%"})

    rev = _to_float(_fv(facts, "total_revenue"))
    if rev and tot_pay and tot_pay > 0 and rev > 0:
        ratio = tot_pay / rev
        if ratio > 0.85:
            issues.append({"type": "warning", "message": f"Payroll is {ratio * 100:.0f}% of revenue — unusually high"})

    if "ACORD_140" in selected_form_ids:
        if flags.get("property_has_bi_coverage") and not _fv(facts, "business_income_limit"):
            issues.append({"type": "warning", "message": "Business Income coverage detected — BI limit required"})
        if not _fv(facts, "valuation_method"):
            issues.append({"type": "warning", "message": "Property valuation method not specified on ACORD 140"})

    if "ACORD_131" in selected_form_ids and not _fv(facts, "gl_limits"):
        issues.append({"type": "hard_stop", "message": "Umbrella selected but GL limits missing"})

    if flags.get("has_auto_coverage") and flags.get("auto_has_hired_nonowned"):
        if not _fv(facts, "hired_auto_symbol") or not _fv(facts, "non_owned_symbol"):
            issues.append({
                "type":    "warning",
                "message": "Hired/Non-Owned exposure detected but coverage symbols not defined.",
            })

    locs_125 = _fv(facts, "locations") or []
    locs_140 = (_fv(facts, "property_locations") or []) if flags.get("has_property_coverage") else []
    if isinstance(locs_125, list) and isinstance(locs_140, list):
        n, m = len(locs_125), len(locs_140)
        if n > 0 and m > 0:
            diff = abs(n - m)
            if diff > 1:
                severity = "hard_stop" if diff > 2 else "warning"
                issues.append({
                    "type":      severity,
                    "field":     "location_count",
                    "125_count": n,
                    "140_count": m,
                    "severity":  severity,
                    "message":   "Location count mismatch between application and property schedule",
                })

    return issues


# ── Cross-document consistency ────────────────────────────────────────────────

def check_doc_consistency(docs: List[dict]) -> List[str]:
    """Check identity field consistency across documents."""
    issues: List[str] = []

    _applicant_vals = {_fv(d["facts"], "applicant_name") for d in docs if _fv(d["facts"], "applicant_name")}
    if len(_applicant_vals) > 1:
        issues.append(
            "[hard_stop] code=name_conflict "
            f"Inconsistent applicant_name across docs: {sorted(str(v) for v in _applicant_vals)}"
        )

    for key in ("entity_type", "mailing_address"):
        vals = {_fv(d["facts"], key) for d in docs if _fv(d["facts"], key)}
        if len(vals) > 1:
            issues.append(
                f"[warning] field={key} Inconsistent {key} across docs: {sorted(str(v) for v in vals)}"
            )

    fein_vals = {_fv(d["facts"], "fein") for d in docs if _fv(d["facts"], "fein")}
    if len(fein_vals) > 1:
        issues.append(
            "[hard_stop] code=fein_conflict "
            "FEIN mismatch across uploaded documents. Submission blocked."
        )

    eff_vals = {_fv(d["facts"], "effective_date") for d in docs if _fv(d["facts"], "effective_date")}
    if len(eff_vals) > 1:
        issues.append(
            "[hard_stop] code=date_conflict "
            "Policy date mismatch across documents. Submission blocked unless explained."
        )

    exp_vals = {_fv(d["facts"], "expiration_date") for d in docs if _fv(d["facts"], "expiration_date")}
    if len(exp_vals) > 1:
        issues.append(
            "[hard_stop] code=expiration_conflict "
            "Policy expiration date mismatch across documents. Submission blocked unless explained."
        )

    lob_sets = []
    for d in docs:
        lob = _fv(d["facts"], "lines_of_business")
        if lob and isinstance(lob, list) and lob:
            lob_sets.append(frozenset(str(x).strip().lower() for x in lob))
    if len(lob_sets) >= 2 and len(set(lob_sets)) > 1:
        issues.append(
            f"[warning] field=lines_of_business "
            f"Inconsistent lines_of_business across docs: "
            f"{[sorted(s) for s in lob_sets]}"
        )

    revenue_vals = []
    for d in docs:
        raw = _fv(d["facts"], "total_revenue")
        if raw:
            try:
                revenue_vals.append(float(re.sub(r"[^\d.]", "", str(raw))))
            except ValueError:
                pass
    if len(revenue_vals) >= 2:
        max_rev, min_rev = max(revenue_vals), min(revenue_vals)
        if max_rev > 0 and (max_rev - min_rev) / max_rev > 0.10:
            issues.append(
                f"[warning] field=total_revenue "
                f"Inconsistent total_revenue across docs (>10% variance): "
                f"{revenue_vals}"
            )

    return issues


# ── Confidence-weighted fill rate ────────────────────────────────────────────

CONFIDENCE_SCORE = {
    "deterministic": 1.00,
    "filled":        1.00,
    "ai_high":       0.85,
    "ai_low":        0.50,
    None:            0.00,
}


def confidence_fill_rate(mapped_data: dict, confidence_dict: dict) -> int:
    """Calculate confidence-weighted fill rate."""
    total = len(mapped_data)
    if total == 0:
        return 0
    
    weighted = sum(
        CONFIDENCE_SCORE.get(confidence_dict.get(field), 0.0)
        for field, val in mapped_data.items()
        if val is not None and str(val).strip() not in ("", "null", "None")
    )
    return int((weighted / total) * 100)


# ── Loss history integrity coefficient ───────────────────────────────────────

def loss_integrity_coefficient(
    loss_history_years: int,
    report_age_days: int,
    required_window: int = 5
) -> float:
    """
    90-day grace period: reports < 90 days old score full recency.
    After 90 days, recency decays linearly to 0 at 365 days.
    """
    years_ratio   = min((loss_history_years or 0) / required_window, 1.0)
    recency_ratio = max(0.0, 1.0 - max(0, report_age_days - 90) / 275)
    return round(years_ratio * recency_ratio, 3)


def calculate_p4_loss_history(facts: dict, flags: dict) -> Tuple[int, List[str]]:
    """Loss History Integrity pillar with coefficient-based scoring."""
    λ = loss_integrity_coefficient(
        loss_history_years = int(_fv(facts, "loss_history_years") or 0),
        report_age_days    = int(_fv(facts, "loss_run_age_days") or 365)
    )
    has_carrier = bool(_fv(facts, "prior_carrier"))

    if λ >= 0.85 and has_carrier:
        return 100, []
    elif λ >= 0.85:
        return 80, ["Prior carrier name missing"]
    elif λ >= 0.70:
        return 65, ["Loss runs older than recommended — verify recency"]
    elif λ >= 0.50:
        return 40, ["Loss history incomplete — fewer than 3 years provided"]
    elif λ > 0:
        return 20, ["Loss history critically incomplete or stale"]
    else:
        return 10, ["No loss history provided — required for carrier submission"]


# ── LOB inference ─────────────────────────────────────────────────────────────

NAICS_TO_LOB = {
    "236": "contractor", "237": "contractor", "238": "contractor",
    "722": "restaurant", "311": "restaurant", "312": "restaurant",
    "511": "technology", "518": "technology", "519": "technology",
    "541": "technology",
    "321": "manufacturing","331": "manufacturing","332": "manufacturing",
    "484": "transportation","485": "transportation","492": "transportation",
}


def infer_lob(facts: dict, flags: dict) -> str:
    """Infer line of business from NAICS, flags, or operations description."""
    naics = str(_fv(facts, "naics_code") or "")[:3]
    if naics and naics in NAICS_TO_LOB:
        return NAICS_TO_LOB[naics]
    
    if flags.get("is_contractor"):
        return "contractor"
    
    desc = (_fv(facts, "operations_description") or "").lower()
    if any(w in desc for w in ["restaurant","food","catering","kitchen","dining"]):
        return "restaurant"
    if any(w in desc for w in ["software","tech","saas","app","cloud","platform"]):
        return "technology"
    if any(w in desc for w in ["truck","freight","transport","delivery","fleet"]):
        return "transportation"
    
    return "generic"


# ── LOB-specific rules ────────────────────────────────────────────────────────

LOB_RULES = {
    "contractor": {
        "required": ["percent_subcontracted", "years_in_business", "operations_description"],
    },
    "restaurant": {
        "required": ["occupancy_type", "fire_protection_class", "years_in_business"],
    },
    "technology": {
        "required": ["operations_description", "total_revenue", "num_employees"],
    },
    "transportation": {
        "required": ["auto_vin_schedule", "auto_drivers", "auto_radius_of_operation"],
    },
    "generic": {
        "required": ["operations_description", "total_revenue"],
    },
}


def _calculate_cope_score(facts: dict, flags: dict) -> int:
    """Calculate COPE score for Exposure & COPE pillar."""
    if not flags.get("has_property_coverage"):
        return 100
    
    min_ok = all([
        bool(_fv(facts, "locations")),
        bool(_fv(facts, "occupancy_type")),
        bool(_fv(facts, "construction_type")),
        bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
    ])
    
    if not min_ok:
        return 0
    
    carrier_cope = [bool(_fv(facts, k)) for k in [
        "year_built", "roof_year", "sprinkler_system",
        "fire_protection_class", "valuation_method", "coinsurance_percentage",
    ]]
    
    return int(60 + (sum(carrier_cope) / len(carrier_cope)) * 40)


# ── Weight normalization ──────────────────────────────────────────────────────

def normalize_weights(base_weights: dict, override: dict) -> dict:
    """Normalize weights to sum to 1.0 after override."""
    w = {**base_weights, **override}
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


# ── Package-level SQS ─────────────────────────────────────────────────────────

BASE_PILLAR_WEIGHTS = {
    "data_integrity": 0.35,
    "exposure_cope":  0.25,
    "consistency":    0.20,
    "loss_history":   0.15,
    "narrative":      0.05
}

LOB_WEIGHT_OVERRIDES = {
    "contractor":     {"exposure_cope": 0.30, "data_integrity": 0.30},
    "restaurant":     {},
    "technology":     {"narrative": 0.10, "exposure_cope": 0.20},
    "transportation": {"exposure_cope": 0.30},
    "generic":        {}
}


def calculate_package_sqs(
    facts: dict,
    flags: dict,
    form_results: List[dict],
    cross_issues: List[dict],
    hard_stops: List[str],
    soft_stops: List[str],
    session_data: dict,
    mapped_data: Optional[dict] = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
) -> dict:
    """
    Calculate package-level SQS with 5 pillars, LOB-aware weights, and full metadata.
    """
    lob = infer_lob(facts, flags)
    weights = normalize_weights(BASE_PILLAR_WEIGHTS, LOB_WEIGHT_OVERRIDES.get(lob, {}))

    # P1 — Data Integrity
    tier1_ok, tier1_missing = check_tier1(facts, flags)
    tier2_score, tier2_missing = check_tier2(facts)
    conf_rate = confidence_fill_rate(mapped_data or {}, confidence_dict or {})
    p1 = int((
        (100 if tier1_ok else max(0, 100 - len(tier1_missing) * 20)) * 0.4 +
        tier2_score * 0.35 +
        conf_rate * 0.25
    ))

    # P2 — Exposure & COPE
    lob_rules   = LOB_RULES.get(lob, LOB_RULES["generic"])
    req_present = sum(1 for f in lob_rules["required"] if _fv(facts, f))
    req_total   = len(lob_rules["required"])
    lob_score   = int((req_present / req_total) * 100) if req_total else 100
    cope_score  = _calculate_cope_score(facts, flags)
    p2 = int(lob_score * 0.6 + cope_score * 0.4)

    # P3 — Cross-Form Consistency
    hard_cross  = [i for i in cross_issues if i.get("type") == "hard_stop"]
    warn_cross  = [i for i in cross_issues if i.get("type") == "warning"]
    p3 = max(0, 100 - len(hard_cross) * 25 - len(warn_cross) * 10)

    # P4 — Loss History Integrity
    p4, p4_recs = calculate_p4_loss_history(facts, flags)

    # P5 — Narrative Quality
    ops = _fv(facts, "operations_description") or ""
    p5 = min(100, int(
        (min(len(ops), 300) / 300) * 60 +
        (20 if any(w in ops.lower() for w in ["safety","certified","osha","protocol"]) else 0) +
        (20 if len(ops) > 100 else 0)
    ))

    # Weighted package score
    raw = int(
        p1 * weights["data_integrity"] +
        p2 * weights["exposure_cope"]  +
        p3 * weights["consistency"]    +
        p4 * weights["loss_history"]   +
        p5 * weights["narrative"]
    )

    # Hard stop penalty
    if hard_stops or any(hard_cross):
        raw = min(raw, 60)
    elif soft_stops:
        raw = min(raw, 85)
    raw = max(0, raw)

    # Tier determination
    tier = (
        "Carrier-Ready" if raw >= 90 else
        "Quote-Ready"   if raw >= 78 else
        "Review-Ready"  if raw >= 62 else
        "At-Risk"       if raw >= 45 else
        "Incomplete"
    )

    # SQS history management
    history = session_data.get("sqs_history", [])
    stage = calculation_stage
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    history.append({
        "at": timestamp,
        "score": raw,
        "stage": stage,
        "model_version": SQS_MODEL_VERSION
    })

    # Delta calculation
    delta = raw - history[0]["score"] if len(history) > 1 else 0

    # Top recommendations (merged from all components)
    all_recs = list(tier1_missing) + list(tier2_missing) + list(p4_recs)
    top_recs = all_recs[:5]

    return {
        "package_sqs_score": raw,
        "tier": tier,
        "lob": lob,
        "pillars": {
            "data_integrity": p1,
            "exposure_cope": p2,
            "consistency": p3,
            "loss_history": p4,
            "narrative": p5
        },
        "weights_used": weights,
        "top_recommendations": top_recs,
        "sqs_history": history,
        "delta_this_session": delta,
        "routing_decision": (
            "auto_quote"      if raw >= 85 else
            "priority_review" if raw >= 70 else
            "standard_review" if raw >= 50 else
            "hold"
        ),
        "narrative": "",  # Filled by generate_sqs_narrative at download
        "timestamp": timestamp,
        "model_version": SQS_MODEL_VERSION,
        "session_id": session_id,
        "user_id": user_id,
        "calculation_stage": stage,
    }


# ── Recommendation impact estimation ──────────────────────────────────────────

def _estimate_score_impact(
    field: str,
    component: str,
    current_breakdown: dict,
    weights: dict
) -> int:
    """Estimate SQS gain if field were filled."""
    # Simplified heuristic: tier-1 fields worth more
    tier1_fields = set(TIER1_FIELDS.keys())
    tier2_fields = set(TIER2_FIELDS.keys())
    
    if field in tier1_fields:
        base_impact = 15
    elif field in tier2_fields:
        base_impact = 8
    else:
        base_impact = 5
    
    # Weight by component importance
    component_weight = weights.get(component, 0.10)
    return int(base_impact * (component_weight / 0.25))


# ── Per-form SQS (enhanced with metadata) ─────────────────────────────────────

def calculate_sqs(
    facts: dict,
    flags: dict,
    mapped_data: dict,
    form_schema: dict,
    selected_form_ids: List[str],
    hard_stops: List[str],
    soft_stops: List[str],
    tier2_score: int,
    form_id: Optional[str] = None,
    schema_size: Optional[int] = None,
    fields_mapped: Optional[int] = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
) -> dict:
    """
    Per-form SQS calculation with full metadata and structured recommendations.
    """
    extraction_quality = facts.get("_extraction_quality", 1.0)
    if isinstance(extraction_quality, float) and extraction_quality < 0.60:
        return {
            "sqs_score": None,
            "needs_reextraction": True,
            "tier": "Incomplete",
            "routing_decision": "hold",
            "issues": [f"Only {int(extraction_quality*100)}% of document was processed. Re-upload or reprocess."],
            "recommendations": [],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_version": SQS_MODEL_VERSION,
            "session_id": session_id,
            "user_id": user_id,
            "calculation_stage": calculation_stage,
        }

    breakdown: dict = {}
    issues: List[str] = []
    recommendations: List[dict] = []
    fraud_penalty = 0

    fid = form_id or (selected_form_ids[0] if selected_form_ids else "UNKNOWN")
    is_cert_only = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
    total_fields = schema_size if schema_size is not None else len(form_schema)
    filled_fields = fields_mapped if fields_mapped is not None else sum(
        1 for v in mapped_data.values()
        if v is not None and str(v).strip() not in ("", "null", "None")
    )
    fill_rate = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    # Use confidence-weighted fill rate if available
    if confidence_dict:
        conf_rate = confidence_fill_rate(mapped_data, confidence_dict)
    else:
        conf_rate = fill_rate

    # ── Structural completeness ───────────────────────────────────────────────
    if is_cert_only:
        chks = [
            bool(_fv(facts, "applicant_name") or _fv(facts, "certificate_holder")),
            bool(_fv(facts, "effective_date")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate")),
        ]
        struct = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_125":
        chks = [
            bool(_fv(facts, "applicant_name")),
            bool(_fv(facts, "mailing_address")),
            bool(_fv(facts, "effective_date")),
            bool(_fv(facts, "lines_of_business")),
            bool(_fv(facts, "contact_name") or _fv(facts, "contact_phone") or _fv(facts, "contact_email")),
            bool(_fv(facts, "producer_name")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
        missing = [
            (l, f) for l, ok, f in zip(
                ["applicant name", "mailing address", "effective date",
                 "lines of business", "contact info", "producer name"],
                chks,
                ["applicant_name", "mailing_address", "effective_date",
                 "lines_of_business", "contact_name", "producer_name"]
            )
            if not ok
        ]
        for label, field_name in missing:
            recommendations.append({
                "rec_id": f"rec_{field_name}",
                "field": field_name,
                "component": "structural_completeness",
                "message": f"ACORD 125 missing: {label}",
                "type": "missing_field",
                "score_impact": 15 if field_name in TIER1_FIELDS else 8,
                "priority": 1 if field_name in TIER1_FIELDS else 2,
            })

    elif fid == "ACORD_126":
        chks = [
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "gl_class_codes_by_location")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "gl_form_type")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
        if not _fv(facts, "gl_class_codes_by_location"):
            issues.append("GL class codes missing")
            recommendations.append({
                "rec_id": "rec_gl_class_codes",
                "field": "gl_class_codes_by_location",
                "component": "exposure_consistency",
                "message": "Provide GL class codes",
                "type": "missing_field",
                "score_impact": 12,
                "priority": 1,
            })
        if not _fv(facts, "gl_form_type"):
            recommendations.append({
                "rec_id": "rec_gl_form_type",
                "field": "gl_form_type",
                "component": "exposure_consistency",
                "message": "Specify GL form type: occurrence or claims-made",
                "type": "missing_field",
                "score_impact": 5,
                "priority": 2,
            })

    elif fid == "ACORD_140":
        min_cope = [
            bool(_fv(facts, "locations")),
            bool(_fv(facts, "occupancy_type")),
            bool(_fv(facts, "construction_type")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
        ]
        if not all(min_cope):
            struct = 0
            issues.append("Minimum Viable COPE incomplete")
            recommendations.append({
                "rec_id": "rec_min_cope",
                "field": "locations",
                "component": "property_integrity",
                "message": "Required: street address, occupancy, construction type, building/BPP value",
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
        else:
            carrier_cope = [bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]]
            struct = int(60 + (sum(carrier_cope) / len(carrier_cope)) * 40)
            mc = [
                (l, f) for l, ok, f in zip(
                    ["year built", "roof year", "sprinkler system",
                     "fire protection class", "valuation method", "coinsurance %"],
                    carrier_cope,
                    ["year_built", "roof_year", "sprinkler_system",
                     "fire_protection_class", "valuation_method", "coinsurance_percentage"]
                )
                if not ok
            ]
            for label, field_name in mc:
                recommendations.append({
                    "rec_id": f"rec_{field_name}",
                    "field": field_name,
                    "component": "property_integrity",
                    "message": f"For Carrier-Grade COPE provide: {label}",
                    "type": "suggestion",
                    "score_impact": 6,
                    "priority": 2,
                })
    else:
        struct = conf_rate

    # OCR confidence penalty
    _ocr_tier1 = list(TIER1_FIELDS.keys()) + list(TIER1_CONTACT)
    ocr_low_count = sum(1 for k in _ocr_tier1 if not _focr(facts, k))
    ocr_penalty = min(30, ocr_low_count * 6)
    struct = max(0, struct - ocr_penalty)
    breakdown["structural_completeness"] = struct

    # ── Exposure consistency ──────────────────────────────────────────────────
    if is_cert_only:
        chks = [
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
            bool(_fv(facts, "applicant_name") or _fv(facts, "certificate_holder")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_125":
        chks = [
            bool(_fv(facts, "total_revenue") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "num_employees")),
            bool(_fv(facts, "fein")),
            bool(_fv(facts, "entity_type")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        if _fv(facts, "naics_code") or _fv(facts, "sic_code"):
            exp_score = min(100, exp_score + 5)

    elif fid == "ACORD_126":
        chks = [
            bool(_fv(facts, "gl_class_codes_by_location")),
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "gl_limits")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        _gl_codes = _fv(facts, "gl_class_codes_by_location")
        if isinstance(_gl_codes, list) and _gl_codes:
            exp_score = min(100, exp_score + 10)
        else:
            exp_score = max(0, exp_score - 15)

    elif fid == "ACORD_140":
        chks = [
            bool(_fv(facts, "valuation_method")),
            bool(_fv(facts, "coinsurance_percentage") or _fv(facts, "property_deductible_aop")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
            bool(_fv(facts, "occupancy_type")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        if not _fv(facts, "valuation_method"):
            exp_score = max(0, exp_score - 15)
            recommendations.append({
                "rec_id": "rec_valuation_method",
                "field": "valuation_method",
                "component": "exposure_consistency",
                "message": "Specify RCV or ACV valuation method",
                "type": "missing_field",
                "score_impact": 10,
                "priority": 1,
            })

    else:
        chks = [
            bool(_fv(facts, "total_revenue") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "operations_description")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    breakdown["exposure_consistency"] = exp_score

    # ── Property integrity ────────────────────────────────────────────────────
    _prop_hard = False
    _prop_soft = False

    if fid == "ACORD_140":
        prop = struct
        if flags.get("property_has_bi_coverage") and _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            prop = max(0, prop - 8)
            recommendations.append({
                "rec_id": "rec_period_of_restoration",
                "field": "period_of_restoration",
                "component": "property_integrity",
                "message": "Add Period of Restoration",
                "type": "suggestion",
                "score_impact": 8,
                "priority": 2,
            })
        if flags.get("property_has_peril_deductibles"):
            d = sum(bool(_fv(facts, f)) for f in [
                "property_deductible_wind", "property_deductible_earthquake", "property_deductible_flood",
            ])
            if d == 0:
                prop = max(0, prop - 10)
                recommendations.append({
                    "rec_id": "rec_peril_deductibles",
                    "field": "property_deductible_wind",
                    "component": "property_integrity",
                    "message": "Define peril deductibles",
                    "type": "soft_warning",
                    "score_impact": 10,
                    "priority": 1,
                })

    elif flags.get("has_property_coverage"):
        min_ok = all([
            bool(_fv(facts, "locations")),
            bool(_fv(facts, "occupancy_type")),
            bool(_fv(facts, "construction_type")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
        ])
        if not min_ok:
            prop = 0
            issues.append("Minimum Viable COPE incomplete")
        else:
            cc = [bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]]
            prop = int(60 + (sum(cc) / len(cc)) * 40)
    else:
        prop = 100

    # Property delta penalties
    if fid == "ACORD_140" or flags.get("has_property_coverage"):
        if not _fv(facts, "valuation_method"):
            prop = max(0, prop - 5)

        if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            _prop_soft = True
            issues.append("BI coverage present but period of restoration not specified")

        if flags.get("property_has_peril_deductibles"):
            _missing_perils = [
                label for label, key in [
                    ("wind/hail", "property_deductible_wind"),
                    ("earthquake", "property_deductible_earthquake"),
                    ("flood", "property_deductible_flood"),
                ]
                if not _fv(facts, key)
            ]
            if _missing_perils:
                _prop_hard = True
                issues.append(
                    "Peril-specific deductible referenced but not defined: "
                    + ", ".join(_missing_perils)
                )

        if (
            (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value"))
            and not _fv(facts, "coinsurance_percentage")
        ):
            prop = max(0, prop - 5)
            issues.append("Coinsurance percentage not specified for insured property")

    breakdown["property_integrity"] = max(0, prop)

    # ── Loss history alignment ────────────────────────────────────────────────
    loss_score, loss_recs = calculate_p4_loss_history(facts, flags)
    for rec_msg in loss_recs:
        recommendations.append({
            "rec_id": f"rec_loss_{len(recommendations)}",
            "field": "loss_history_years",
            "component": "loss_history_alignment",
            "message": rec_msg,
            "type": "suggestion",
            "score_impact": 8,
            "priority": 2,
        })
    breakdown["loss_history_alignment"] = loss_score

    # ── Umbrella / limit adequacy ─────────────────────────────────────────────
    if flags.get("has_umbrella"):
        has_underlying = bool(_fv(facts, "gl_limits") or _fv(facts, "auto_liability_limit"))
        umbrella_score = 100 if has_underlying else 0
        if not has_underlying:
            issues.append("Umbrella detected but no underlying GL/Auto limits")
            recommendations.append({
                "rec_id": "rec_underlying_limits",
                "field": "gl_limits",
                "component": "umbrella_limit_adequacy",
                "message": "Provide underlying limits",
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
    else:
        umbrella_score = 100
    breakdown["umbrella_limit_adequacy"] = umbrella_score

    # ── Narrative quality ─────────────────────────────────────────────────────
    narrative_score = min(tier2_score, 100)
    ops_desc = str(_fv(facts, "operations_description") or "")
    if len(ops_desc) > 50:
        diversity = _token_diversity(ops_desc)
        bonus = 15 if diversity > 0.6 else 10
        narrative_score = min(100, narrative_score + bonus)
    breakdown["narrative_quality"] = narrative_score

    # ── Weighted score ────────────────────────────────────────────────────────
    weights = {
        "structural_completeness": 0.25,
        "exposure_consistency":    0.25,
        "property_integrity":      0.15,
        "loss_history_alignment":  0.15,
        "umbrella_limit_adequacy": 0.10,
        "narrative_quality":       0.10,
    }
    raw_score = int(sum(breakdown[k] * w for k, w in weights.items()))

    # ── Cap gates ─────────────────────────────────────────────────────────────
    cope_hard = fid == "ACORD_140" and breakdown["property_integrity"] == 0
    umb_fail = flags.get("has_umbrella") and umbrella_score == 0

    if hard_stops or cope_hard or umb_fail or _prop_hard:
        raw_score = min(raw_score, 60)
    elif soft_stops or _prop_soft:
        raw_score = min(raw_score, 85)

    raw_score = max(0, raw_score - fraud_penalty)

    # ── Tier and routing ──────────────────────────────────────────────────────
    tier, tc = (
        ("Carrier-Ready", "green") if raw_score >= 90 else
        ("Review-Ready", "yellow") if raw_score >= 75 else
        ("At-Risk", "orange") if raw_score >= 60 else
        ("Decline-Prone", "red")
    )
    routing = (
        "auto_quote" if raw_score > 85 else
        "review" if raw_score >= 65 else
        "full_review" if raw_score >= 40 else
        "hold"
    )
    
    # Sort recommendations by priority then score impact
    recommendations.sort(key=lambda r: (-r.get("priority", 99), -r.get("score_impact", 0)))
    
    risk_drivers = [
        {"component": k.replace("_", " ").title(), "score": v}
        for k, v in sorted(breakdown.items(), key=lambda x: x[1])[:3]
        if v < 90
    ]

    return {
        "sqs_score": raw_score,
        "tier": tier,
        "tier_color": tc,
        "grade": "A" if raw_score >= 90 else "B" if raw_score >= 80 else "C" if raw_score >= 70 else "D" if raw_score >= 60 else "F",
        "routing_decision": routing,
        "breakdown": breakdown,
        "risk_drivers": risk_drivers,
        "issues": issues,
        "recommendations": recommendations,
        "fraud_penalty": fraud_penalty,
        "fill_rate": fill_rate,
        "confidence_fill_rate": conf_rate,
        "form_id": fid,
        "compliance_checklist": risk_transfer_check(facts, flags, selected_form_ids),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model_version": SQS_MODEL_VERSION,
        "session_id": session_id,
        "user_id": user_id,
        "calculation_stage": calculation_stage,
    }


# ── Narrative generation ──────────────────────────────────────────────────────

async def generate_sqs_narrative(
    sqs_result: dict,
    delta_this_session: int,
    resolved_recs: List[str],
    ignored_recs: List[str]
) -> str:
    """
    Generate narrative prose explaining SQS score.
    Called at download only. Uses llama-3.3-70b-versatile.
    """
    score = sqs_result.get("sqs_score") or sqs_result.get("package_sqs_score")
    tier  = sqs_result.get("tier")
    try:
        from config.settings import groq_chat

        breakdown    = sqs_result.get("breakdown", {})
        risk_drivers = sqs_result.get("risk_drivers", [])

        prompt = f"""Summarize this insurance submission quality in one concise paragraph (60-80 words). Be direct and professional.

Score: {score}/100 ({tier}) | Change this session: {'+' if delta_this_session >= 0 else ''}{delta_this_session} pts
Top risk drivers: {', '.join(str(r) for r in risk_drivers[:3]) if risk_drivers else 'none'}
Resolved: {', '.join(resolved_recs) if resolved_recs else 'none'} | Ignored: {', '.join(ignored_recs) if ignored_recs else 'none'}

One paragraph only. State the score tier, the main gap, and the single most impactful next action."""

        raw = await groq_chat(
            "llama-3.3-70b-versatile",
            [{"role": "user", "content": prompt}]
        )
        return raw.strip()

    except Exception as ex:
        logger.error(f"generate_sqs_narrative failed: {ex}")
        return f"SQS Score: {score}/100 ({tier}). Session improvement: {'+' if delta_this_session >= 0 else ''}{delta_this_session} points."


# ── Clarity pipeline (facts-only SQS) ────────────────────────────────────────

FORM_FIELD_INVENTORY: Dict[str, List[str]] = {
    "ACORD_125": [
        "applicant_name", "dba_name", "mailing_address", "physical_address",
        "fein", "entity_type", "effective_date", "expiration_date",
        "lines_of_business", "contact_name", "contact_phone", "contact_email",
        "producer_name", "total_revenue", "total_payroll", "num_employees",
        "operations_description", "years_in_business", "naics_code", "sic_code",
        "prior_carrier", "policy_number",
    ],
    "ACORD_126": [
        "gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_deductible",
        "gl_class_codes_by_location", "gl_form_type", "retro_date",
        "operations_description", "total_revenue", "total_payroll",
        "additional_named_insureds",
    ],
    "ACORD_140": [
        "locations", "occupancy_type", "construction_type", "year_built",
        "roof_year", "sprinkler_system", "fire_protection_class",
        "valuation_method", "coinsurance_percentage",
        "property_building_value", "property_bpp_value",
        "business_income_limit", "period_of_restoration",
        "property_deductible_aop", "property_deductible_wind",
        "mortgagee_name",
    ],
    "ACORD_25": [
        "applicant_name", "effective_date", "expiration_date",
        "policy_number", "gl_limits", "gl_aggregate", "certificate_holder",
    ],
    "ACORD_131": [
        "umbrella_limit", "umbrella_sir", "gl_limits", "auto_liability_limit",
        "effective_date", "applicant_name",
    ],
    "ACORD_130": [
        "wc_payroll", "wc_class_codes", "wc_xmod", "wc_officer_exclusions",
        "total_payroll", "num_employees", "applicant_name", "effective_date",
    ],
}

_EMPTY_VALUES = {"", "null", "none", "[]", "{}"}


def _fact_is_filled(val) -> bool:
    if isinstance(val, dict) and "value" in val:
        val = val["value"]
    if val is None:
        return False
    if isinstance(val, list):
        return len(val) > 0
    return str(val).strip().lower() not in _EMPTY_VALUES


def calculate_sqs_from_facts(
    facts: dict,
    flags: dict,
    selected_form_ids: List[str],
    hard_stops: List[str],
    soft_stops: List[str],
    tier2_score: int,
    form_id: str = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
) -> dict:
    """
    Calculate SQS for Clarity pipeline without form generation.
    Uses FORM_FIELD_INVENTORY to derive fill_rate.
    """
    fid = form_id or (selected_form_ids[0] if selected_form_ids else "ACORD_125")
    inventory = FORM_FIELD_INVENTORY.get(fid, list(facts.keys()))

    synthetic_mapped = {k: _fv(facts, k) for k in inventory}
    filled = sum(1 for k in inventory if _fact_is_filled(_fv(facts, k)))
    schema_size = len(inventory)

    return calculate_sqs(
        facts=facts,
        flags=flags,
        mapped_data=synthetic_mapped,
        form_schema={k: {} for k in inventory},
        selected_form_ids=selected_form_ids,
        hard_stops=hard_stops,
        soft_stops=soft_stops,
        tier2_score=tier2_score,
        form_id=fid,
        schema_size=schema_size,
        fields_mapped=filled,
        confidence_dict=confidence_dict,
        session_id=session_id,
        user_id=user_id,
        calculation_stage=calculation_stage,
    )