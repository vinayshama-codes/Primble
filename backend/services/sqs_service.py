
#sqs_service.py

import json
import logging
import re
from typing import List, Tuple, Dict

from utils.validators import run_field_validations
from services.extraction_service import _fv, _focr

logger = logging.getLogger(__name__)


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
    # Original 6
    "fein":                   "FEIN / Tax ID",
    "entity_type":            "Business entity type",
    "operations_description": "Operations description",
    "total_revenue":          "Annual revenue",
    "prior_carrier":          "Prior carrier name",
    "num_employees":          "Number of employees",
    # Added 5
    "years_in_business":      "Years in business",
    "naics_code":             "NAICS / industry code",
    "num_claims":             "Number of prior claims",
    "total_payroll":          "Annual payroll",
    # NOTE: mailing_address is intentionally excluded here — it already gates
    # at TIER1. Including it in TIER2 would double-penalise the user for the
    # same missing field and produce a misleading narrative quality score.
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

    Cross-doc hard stops (fein_conflict, date_conflict, expiration_conflict) are
    appended by the caller after check_doc_consistency() runs — not here.
    calculate_sqs() caps at 60 whenever hard_stops is non-empty, so externally
    appended items trigger the same cap automatically.
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
            hard.append("Property Minimum Viable COPE incomplete — missing: " + ", ".join(missing_min))
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
    # FIX: was flags.get("has_auto") — correct key is "has_auto_coverage"
    if flags.get("has_auto_coverage"):
        # 1. Split limits completeness
        # FIX: was "auto_limit_structure" — correct key matches extraction schema
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

        # 2. Physical damage deductibles
        # FIX: was flags.get("has_physical_damage") — correct key is "auto_has_physical_damage"
        if flags.get("auto_has_physical_damage"):
            comp_ded = _fv(facts, "auto_deductible_comp")
            coll_ded = _fv(facts, "auto_deductible_collision")
            if not comp_ded or not coll_ded:
                soft.append("Physical damage coverage present but deductibles not specified.")

        # 3. Umbrella attachment check
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
        # Claims-made GL retro date
        if flags.get("gl_is_claims_made") and not _fv(facts, "retro_date"):
            if "GL policy is claims-made — retro date is required" not in soft:
                soft.append("Claims-made GL policy requires retro date for umbrella attachment.")

        # WC Employers Liability limits
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

        # Policy period alignment
        umb_eff = _fv(facts, "umbrella_effective_date")
        gl_eff  = _fv(facts, "effective_date")
        if umb_eff and gl_eff and umb_eff != gl_eff:
            soft.append("Umbrella and GL policy periods misaligned.")

        umb_exp = _fv(facts, "umbrella_expiration_date")
        gl_exp  = _fv(facts, "expiration_date")
        if umb_exp and gl_exp and umb_exp != gl_exp:
            soft.append("Umbrella and GL expiration dates misaligned.")

        # SIR vs deductible
        sir    = _to_int(_fv(facts, "umbrella_sir"))
        gl_ded = _to_int(_fv(facts, "gl_deductible"))
        if sir and gl_ded and sir < gl_ded:
            soft.append(
                f"Umbrella SIR ({sir:,}) is lower than GL deductible ({gl_ded:,}) — verify attachment."
            )

    return hard, soft


# ── Risk transfer compliance checklist ───────────────────────────────────────

def risk_transfer_check(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    """
    Advisory-only compliance checklist for risk transfer requirements.
    Reads from facts["risk_transfer"] (populated by the extraction prompt).
    Never raises hard stops.

    FIX: added json.loads() fallback for when the LLM returns the risk_transfer
    block as a JSON-escaped string instead of a native dict.
    """
    checklist: List[dict] = []

    rt = facts.get("risk_transfer")
    # Unwrap OCR envelope if present (should not be, but guard defensively).
    if isinstance(rt, dict) and "value" in rt:
        rt = rt["value"]
    # FIX: LLM sometimes serialises the nested dict as a string — parse it.
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = {}
    if not isinstance(rt, dict):
        rt = {}

    # 1. Additional insured
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

    # 2. Waiver of subrogation
    if rt.get("waiver_of_subrogation_required") is True or flags.get("has_waiver_of_subrogation"):
        checklist.append({
            "check":   "waiver_of_subrogation",
            "label":   "Waiver of Subrogation",
            "status":  "required",
            "message": "WOS endorsement needed — waiver of subrogation requirement detected.",
        })

    # 3. Primary and non-contributory
    if rt.get("primary_noncontributory_required") is True or flags.get("has_primary_noncontributory"):
        checklist.append({
            "check":   "primary_noncontributory",
            "label":   "Primary & Non-Contributory",
            "status":  "required",
            "message": "PNC endorsement needed — primary and non-contributory requirement detected.",
        })

    # 4. Specific wording — advisory only
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
    """
    Form-specific cross-validation checks.

    FIX: auto flag names corrected to match extraction schema:
      has_auto             → has_auto_coverage
      has_hired_non_owned  → auto_has_hired_nonowned
    FIX: total_revenue parsed via _fv() to unwrap OCR envelope before regex.
    """
    issues: List[dict] = []

    # ── Basic identity ────────────────────────────────────────────────────────
    if not _fv(facts, "applicant_name"):
        issues.append({"type": "hard_stop", "message": "Named insured missing — required on all forms"})

    fein = _fv(facts, "fein", "")
    if fein and len(str(fein).replace("-", "").replace(" ", "")) not in (9, 0):
        issues.append({"type": "warning", "message": f"FEIN format appears invalid: '{fein}'"})

    if not _fv(facts, "effective_date"):
        issues.append({"type": "warning", "message": "Policy effective date missing"})

    # ── Property ──────────────────────────────────────────────────────────────
    if "ACORD_140" in selected_form_ids and not _fv(facts, "locations"):
        issues.append({"type": "hard_stop", "message": "ACORD 140 selected but no property locations found"})

    # ── GL ────────────────────────────────────────────────────────────────────
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

    # ── Payroll / revenue ratios ──────────────────────────────────────────────
    # FIX: use _fv() to unwrap OCR envelope before _to_float() to prevent
    # garbage numbers from dict repr being passed to the regex parser.
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

    # ── Property form checks ──────────────────────────────────────────────────
    if "ACORD_140" in selected_form_ids:
        if flags.get("property_has_bi_coverage") and not _fv(facts, "business_income_limit"):
            issues.append({"type": "warning", "message": "Business Income coverage detected — BI limit required"})
        if not _fv(facts, "valuation_method"):
            issues.append({"type": "warning", "message": "Property valuation method not specified on ACORD 140"})

    # ── Umbrella ──────────────────────────────────────────────────────────────
    if "ACORD_131" in selected_form_ids and not _fv(facts, "gl_limits"):
        issues.append({"type": "hard_stop", "message": "Umbrella selected but GL limits missing"})

    # ── ACORD 127: coverage symbols ───────────────────────────────────────────
    # FIX: corrected flag key from "has_auto" → "has_auto_coverage"
    #      and "has_hired_non_owned" → "auto_has_hired_nonowned"
    if flags.get("has_auto_coverage") and flags.get("auto_has_hired_nonowned"):
        if not _fv(facts, "hired_auto_symbol") or not _fv(facts, "non_owned_symbol"):
            issues.append({
                "type":    "warning",
                "message": "Hired/Non-Owned exposure detected but coverage symbols not defined.",
            })

    # ── Location count reconciliation ─────────────────────────────────────────
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
    """
    Check that key identity fields are consistent across all uploaded documents.

    Returns strings prefixed with "[hard_stop]" or "[warning]".
    Caller parses the prefix to route to hard_stops or advisory lists.

    FIX: total_revenue compared via _fv() (envelope-unwrapped) before float
    parsing, preventing dict repr from producing garbage numbers.
    """
    issues: List[str] = []

    # ── applicant_name mismatch: hard stop ───────────────────────────────────
    _applicant_vals = {_fv(d["facts"], "applicant_name") for d in docs if _fv(d["facts"], "applicant_name")}
    if len(_applicant_vals) > 1:
        issues.append(
            "[hard_stop] code=name_conflict "
            f"Inconsistent applicant_name across docs: {sorted(str(v) for v in _applicant_vals)}"
        )

    # ── Advisory exact-match fields ───────────────────────────────────────────
    for key in ("entity_type", "mailing_address"):
        vals = {_fv(d["facts"], key) for d in docs if _fv(d["facts"], key)}
        if len(vals) > 1:
            issues.append(
                f"[warning] field={key} Inconsistent {key} across docs: {sorted(str(v) for v in vals)}"
            )

    # ── FEIN hard stop ────────────────────────────────────────────────────────
    fein_vals = {_fv(d["facts"], "fein") for d in docs if _fv(d["facts"], "fein")}
    if len(fein_vals) > 1:
        issues.append(
            "[hard_stop] code=fein_conflict "
            "FEIN mismatch across uploaded documents. Submission blocked."
        )

    # ── Policy date hard stops ────────────────────────────────────────────────
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

    # ── Lines of business: order-insensitive set comparison ──────────────────
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

    # ── total_revenue: flag if docs diverge by more than ±10% ────────────────
    # FIX: use _fv() to unwrap OCR envelope before passing to the regex float parser.
    revenue_vals = []
    for d in docs:
        raw = _fv(d["facts"], "total_revenue")   # envelope-unwrapped
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


# ── Loss history gradient scorer ─────────────────────────────────────────────

def _loss_history_score(facts, flags):
    has_history = flags.get("has_loss_history", False)
    has_carrier = bool(_fv(facts, "prior_carrier"))
    n_claims = _to_int(_fv(facts, "num_claims")) or 0
    incurred = _to_int(_fv(facts, "total_incurred")) or 0
    base = 50
    if has_history: base += 20
    if has_carrier: base += 15
    if n_claims > 0: base += 10
    if incurred >= 0 and has_history: base += 5
    if n_claims > 5: base -= 10
    if incurred > 250_000: base -= 5
    return max(40, min(100, base))


# ── SQS calculation ───────────────────────────────────────────────────────────

def calculate_sqs(
    facts,
    flags,
    mapped_data,
    form_schema,
    selected_form_ids,
    hard_stops,
    soft_stops,
    tier2_score,
    form_id=None,
    schema_size=None,
    fields_mapped=None,
) -> dict:
    extraction_quality = facts.get("_extraction_quality", 1.0)
    if isinstance(extraction_quality, float) and extraction_quality < 0.60:
        return {
            "sqs_score": None,
            "needs_reextraction": True,
            "tier": "Incomplete",
            "routing_decision": "hold",
            "issues": [f"Only {int(extraction_quality*100)}% of document was processed. Re-upload or reprocess."],
            "recommendations": ["Re-upload document or contact support."],
        }

    breakdown:       dict = {}
    issues:          List[str] = []
    recommendations: List[str] = []
    fraud_penalty = 0

    fid          = form_id or (selected_form_ids[0] if selected_form_ids else "UNKNOWN")
    is_cert_only = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
    total_fields  = schema_size  if schema_size  is not None else len(form_schema)
    filled_fields = fields_mapped if fields_mapped is not None else sum(
        1 for v in mapped_data.values()
        if v is not None and str(v).strip() not in ("", "null", "None")
    )
    fill_rate = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    # ── Structural completeness ───────────────────────────────────────────────
    if is_cert_only:
        chks   = [
            bool(_fv(facts, "applicant_name") or _fv(facts, "certificate_holder")),
            bool(_fv(facts, "effective_date")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate")),
        ]
        struct = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_125":
        chks   = [
            bool(_fv(facts, "applicant_name")),
            bool(_fv(facts, "mailing_address")),
            bool(_fv(facts, "effective_date")),
            bool(_fv(facts, "lines_of_business")),
            bool(_fv(facts, "contact_name") or _fv(facts, "contact_phone") or _fv(facts, "contact_email")),
            bool(_fv(facts, "producer_name")),
        ]
        struct  = int(sum(chks) / len(chks) * 100)
        missing = [
            l for l, ok in zip(
                ["applicant name", "mailing address", "effective date",
                 "lines of business", "contact info", "producer name"],
                chks,
            )
            if not ok
        ]
        if missing:
            recommendations.append("ACORD 125 missing: " + ", ".join(missing))

    elif fid == "ACORD_126":
        chks   = [
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "gl_class_codes_by_location")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "gl_form_type")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
        if not _fv(facts, "gl_class_codes_by_location"):
            issues.append("GL class codes missing")
            recommendations.append("Provide GL class codes")
        if not _fv(facts, "gl_form_type"):
            recommendations.append("Specify GL form type: occurrence or claims-made")

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
            recommendations.append("Required: street address, occupancy, construction type, building/BPP value")
        else:
            carrier_cope = [bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]]
            struct = int(60 + (sum(carrier_cope) / len(carrier_cope)) * 40)
            mc = [
                l for l, ok in zip(
                    ["year built", "roof year", "sprinkler system",
                     "fire protection class", "valuation method", "coinsurance %"],
                    carrier_cope,
                )
                if not ok
            ]
            if mc:
                recommendations.append("For Carrier-Grade COPE provide: " + ", ".join(mc))
    else:
        struct = fill_rate

    # OCR confidence penalty: -6 per tier-1 field with ocr_confident=False, cap 30.
    _ocr_tier1 = list(TIER1_FIELDS.keys()) + list(TIER1_CONTACT)
    ocr_low_count = sum(1 for k in _ocr_tier1 if not _focr(facts, k))
    ocr_penalty = min(30, ocr_low_count * 6)
    struct = max(0, struct - ocr_penalty)
    breakdown["structural_completeness"] = struct

    # ── Exposure consistency ──────────────────────────────────────────────────
    if fid == "ACORD_125":
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
        exp_score  = int(sum(chks) / len(chks) * 100)
        _gl_codes  = _fv(facts, "gl_class_codes_by_location")
        if isinstance(_gl_codes, list) and _gl_codes:
            exp_score = min(100, exp_score + 10)
        else:
            exp_score = max(0, exp_score - 15)
            recommendations.append("Add GL class codes")

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
            recommendations.append("Specify RCV or ACV valuation method")

    else:
        chks = [
            bool(_fv(facts, "total_revenue") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "operations_description")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    breakdown["exposure_consistency"] = exp_score

    # ── Property integrity ────────────────────────────────────────────────────
    _prop_hard = False   # triggers hard cap (≤ 60)
    _prop_soft = False   # triggers soft cap (≤ 85)

    if fid == "ACORD_140":
        prop = struct  # inherit structural score as base
        if flags.get("property_has_bi_coverage") and _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            prop = max(0, prop - 8)
            recommendations.append("Add Period of Restoration")
        if flags.get("property_has_peril_deductibles"):
            d = sum(bool(_fv(facts, f)) for f in [
                "property_deductible_wind", "property_deductible_earthquake", "property_deductible_flood",
            ])
            if d == 0:
                prop = max(0, prop - 10)
                recommendations.append("Define peril deductibles")

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
            cc   = [bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]]
            prop = int(60 + (sum(cc) / len(cc)) * 40)
    else:
        prop = 100

    # ── Property delta penalties ──────────────────────────────────────────────
    # Applied on top of COPE tier logic. _prop_hard / _prop_soft control the cap
    # gate below without mutating the caller-supplied hard_stops / soft_stops lists.
    if fid == "ACORD_140" or flags.get("has_property_coverage"):
        # Δ1: valuation method missing → -5 pts
        if not _fv(facts, "valuation_method"):
            prop = max(0, prop - 5)
            recommendations.append(
                "Specify property valuation method (RCV or ACV) — affects claim settlement"
            )

        # Δ2: BI limit present but period of restoration absent → soft cap
        if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            _prop_soft = True
            issues.append("BI coverage present but period of restoration not specified")

        # Δ3: peril deductible flag set but values undefined → hard cap
        if flags.get("property_has_peril_deductibles"):
            _missing_perils = [
                label for label, key in [
                    ("wind/hail",  "property_deductible_wind"),
                    ("earthquake", "property_deductible_earthquake"),
                    ("flood",      "property_deductible_flood"),
                ]
                if not _fv(facts, key)
            ]
            if _missing_perils:
                _prop_hard = True
                issues.append(
                    "Peril-specific deductible referenced but not defined: "
                    + ", ".join(_missing_perils)
                )

        # Δ4: coinsurance percentage absent when property value is on file → -5 pts
        if (
            (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value"))
            and not _fv(facts, "coinsurance_percentage")
        ):
            prop = max(0, prop - 5)
            issues.append("Coinsurance percentage not specified for insured property")

    # FIX: always write final prop value back to breakdown AFTER all delta
    # adjustments so the UI component score reflects the post-delta value,
    # not the mid-calculation intermediate.
    breakdown["property_integrity"] = max(0, prop)

    # ── Loss history alignment ────────────────────────────────────────────────
    loss_score = _loss_history_score(facts, flags)
    if not (flags.get("has_loss_history") or bool(_fv(facts, "num_claims"))):
        recommendations.append("Attach 3–5 years of loss runs to improve SQS")
    breakdown["loss_history_alignment"] = loss_score

    # ── Umbrella / limit adequacy ─────────────────────────────────────────────
    if flags.get("has_umbrella"):
        has_underlying = bool(_fv(facts, "gl_limits") or _fv(facts, "auto_liability_limit"))
        umbrella_score = 100 if has_underlying else 0
        if not has_underlying:
            issues.append("Umbrella detected but no underlying GL/Auto limits")
            recommendations.append("Provide underlying limits")
    else:
        umbrella_score = 100
    breakdown["umbrella_limit_adequacy"] = umbrella_score

    # ── Narrative quality ─────────────────────────────────────────────────────
    narrative_score = min(tier2_score, 100)
    ops_desc = str(_fv(facts, "operations_description") or "")
    if len(ops_desc) > 50:
        diversity     = _token_diversity(ops_desc)
        bonus         = 15 if diversity > 0.6 else 10
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
    umb_fail  = flags.get("has_umbrella") and umbrella_score == 0

    if hard_stops or cope_hard or umb_fail or _prop_hard:
        raw_score = min(raw_score, 60)
    elif soft_stops or _prop_soft:
        raw_score = min(raw_score, 85)

    raw_score = max(0, raw_score - fraud_penalty)

    # ── Tier and routing ──────────────────────────────────────────────────────
    tier, tc = (
        ("Carrier-Ready", "green")  if raw_score >= 90 else
        ("Review-Ready",  "yellow") if raw_score >= 75 else
        ("At-Risk",       "orange") if raw_score >= 60 else
        ("Decline-Prone", "red")
    )
    routing = (
        # Strict > 85: score capped at exactly 85 by a soft_stop routes to
        # "review", not "auto_quote". >= 85 would let soft_stop submissions
        # through to auto_quote, defeating the soft cap's purpose.
        "auto_quote"  if raw_score > 85 else
        "review"      if raw_score >= 65 else
        "full_review" if raw_score >= 40 else
        "hold"
    )
    risk_drivers = [
        {"component": k.replace("_", " ").title(), "score": v}
        for k, v in sorted(breakdown.items(), key=lambda x: x[1])[:3]
        if v < 90
    ]

    return {
        "sqs_score":          raw_score,
        "tier":               tier,
        "tier_color":         tc,
        "grade":              "A" if raw_score >= 90 else "B" if raw_score >= 80 else "C" if raw_score >= 70 else "D" if raw_score >= 60 else "F",
        "routing_decision":   routing,
        "breakdown":          breakdown,
        "risk_drivers":       risk_drivers,
        "issues":             issues,
        "recommendations":    recommendations,
        "fraud_penalty":      fraud_penalty,
        "fill_rate":          fill_rate,
        "form_id":            fid,
        "compliance_checklist": risk_transfer_check(facts, flags, selected_form_ids),
    }


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
) -> dict:
    """
    Calculate SQS for the Clarity pipeline without form generation.
    Uses FORM_FIELD_INVENTORY to derive fill_rate instead of a live PDF schema.
    All domain scoring logic is identical to calculate_sqs().
    """
    fid       = form_id or (selected_form_ids[0] if selected_form_ids else "ACORD_125")
    inventory = FORM_FIELD_INVENTORY.get(fid, list(facts.keys()))

    synthetic_mapped = {k: _fv(facts, k) for k in inventory}
    filled           = sum(1 for k in inventory if _fact_is_filled(_fv(facts, k)))
    schema_size      = len(inventory)

    return calculate_sqs(
        facts            = facts,
        flags            = flags,
        mapped_data      = synthetic_mapped,
        form_schema      = {k: {} for k in inventory},
        selected_form_ids= selected_form_ids,
        hard_stops       = hard_stops,
        soft_stops       = soft_stops,
        tier2_score      = tier2_score,
        form_id          = fid,
        schema_size      = schema_size,
        fields_mapped    = filled,
    )