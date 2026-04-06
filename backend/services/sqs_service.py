import logging
from typing import List, Tuple, Dict

from utils.validators import run_field_validations

logger = logging.getLogger(__name__)

TIER1_FIELDS = {
    "producer_name":    "Producer / Agency name",
    "applicant_name":   "Applicant legal name",
    "mailing_address":  "Applicant mailing address",
    "effective_date":   "Proposed effective date",
    "lines_of_business": "Lines of business requested",
}
TIER1_CONTACT = ("contact_name", "contact_phone", "contact_email")

TIER2_FIELDS = {
    "fein":                  "FEIN / Tax ID",
    "entity_type":           "Business entity type",
    "operations_description": "Operations description",
    "total_revenue":         "Annual revenue",
    "prior_carrier":         "Prior carrier name",
    "num_employees":         "Number of employees",
}


def check_tier1(facts: dict, flags: dict) -> Tuple[bool, List[str]]:
    if flags.get("is_certificate_doc") or flags.get("has_certificate_request"):
        return True, []
    missing = []
    for field, label in TIER1_FIELDS.items():
        val = facts.get(field)
        if not val or (isinstance(val, list) and not val):
            missing.append(label)
    if not any(facts.get(f) for f in TIER1_CONTACT):
        missing.append("Contact information")
    return len(missing) == 0, missing


def check_tier2(facts: dict) -> Tuple[int, List[str]]:
    missing = [label for field, label in TIER2_FIELDS.items() if not facts.get(field)]
    score   = 100 - (len(missing) * (100 // max(len(TIER2_FIELDS), 1)))
    return score, missing


def evaluate_stops(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    hard, soft = run_field_validations(facts)
    if flags.get("gl_is_claims_made") and not facts.get("retro_date"):
        soft.append("GL policy is claims-made — retro date is required")
    if flags.get("has_general_liability") and not facts.get("total_revenue") and not facts.get("total_payroll"):
        soft.append("GL coverage detected but no revenue or payroll found")
    if flags.get("has_property_coverage"):
        min_cope = {
            "locations":          bool(facts.get("locations")),
            "occupancy_type":     bool(facts.get("occupancy_type")),
            "construction_type":  bool(facts.get("construction_type")),
            "building_or_bpp_value": bool(facts.get("property_building_value") or facts.get("property_bpp_value")),
        }
        missing_min = [k.replace("_", " ") for k, v in min_cope.items() if not v]
        if missing_min:
            hard.append("Property Minimum Viable COPE incomplete — missing: " + ", ".join(missing_min))
        else:
            carrier_cope = {k: bool(facts.get(k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]}
            missing_c = [k.replace("_", " ") for k, v in carrier_cope.items() if not v]
            if missing_c:
                soft.append("Carrier-Grade COPE incomplete — SQS capped at 85. Missing: " + ", ".join(missing_c))
        if flags.get("property_has_bi_coverage"):
            if facts.get("business_income_limit") and not facts.get("period_of_restoration"):
                soft.append("Business Income limit present but Period of Restoration is missing")
            elif not facts.get("business_income_limit"):
                soft.append("Business Income coverage detected — BI limit and Period of Restoration should be provided")
        if flags.get("property_has_peril_deductibles"):
            missing_perils = [p for p, k in [
                ("wind/hail", "property_deductible_wind"),
                ("earthquake", "property_deductible_earthquake"),
                ("flood", "property_deductible_flood"),
            ] if not facts.get(k)]
            if missing_perils:
                soft.append("Peril-specific deductibles referenced — define amounts for: " + ", ".join(missing_perils))
        if not facts.get("valuation_method"):
            soft.append("Property valuation method not specified — select RCV or ACV")
    if flags.get("has_workers_comp"):
        if not facts.get("wc_payroll") and not facts.get("total_payroll"):
            soft.append("Workers Comp detected but payroll is missing")
        if flags.get("wc_has_monopolistic_state"):
            soft.append("Monopolistic WC state detected (ND/OH/WA/WY) — must use state fund")
        if flags.get("wc_multi_state") and not facts.get("wc_payroll_by_state"):
            soft.append("Multi-state WC — payroll breakdown by state and class code required")
    if flags.get("has_umbrella") and not facts.get("gl_limits") and not facts.get("auto_liability_limit"):
        hard.append("Umbrella detected but no underlying GL or Auto limits found")
    if flags.get("has_general_liability"):
        codes = facts.get("gl_class_codes", [])
        if isinstance(codes, list) and not codes:
            soft.append("GL coverage detected but no class codes found")
    return hard, soft


def cross_validate(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    issues = []

    def _num(s):
        try:
            return float(str(s).replace(",", "").replace("$", "").strip()) if s else None
        except:
            return None

    if not facts.get("applicant_name"):
        issues.append({"type": "hard_stop", "message": "Named insured missing — required on all forms"})
    fein = facts.get("fein", "")
    if fein and len(str(fein).replace("-", "").replace(" ", "")) not in (9, 0):
        issues.append({"type": "warning", "message": f"FEIN format appears invalid: '{fein}'"})
    if not facts.get("effective_date"):
        issues.append({"type": "warning", "message": "Policy effective date missing"})
    if "ACORD_140" in selected_form_ids and not facts.get("locations"):
        issues.append({"type": "hard_stop", "message": "ACORD 140 selected but no property locations found"})
    if flags.get("has_general_liability"):
        if "ACORD_126" not in selected_form_ids:
            issues.append({"type": "warning", "message": "GL coverage detected — ACORD 126 should be included"})
        if isinstance(facts.get("gl_class_codes"), list) and facts.get("gl_class_codes") and not facts.get("operations_description"):
            issues.append({"type": "warning", "message": "GL class codes present but no operations description"})
        if flags.get("is_contractor"):
            pct = _num(facts.get("percent_subcontracted"))
            wc  = _num(facts.get("wc_payroll") or facts.get("total_payroll"))
            if pct and pct > 30 and not wc:
                issues.append({"type": "warning", "message": f"High subcontracting ({pct:.0f}%) with no WC payroll"})
    wc_pay  = _num(facts.get("wc_payroll"))
    tot_pay = _num(facts.get("total_payroll"))
    if wc_pay and tot_pay and tot_pay > 0:
        diff_pct = abs(wc_pay - tot_pay) / tot_pay
        if diff_pct > 0.20:
            issues.append({"type": "warning", "message": f"WC payroll differs from total payroll by {diff_pct * 100:.0f}%"})
    rev = _num(facts.get("total_revenue"))
    if rev and tot_pay and tot_pay > 0 and rev > 0:
        ratio = tot_pay / rev
        if ratio > 0.85:
            issues.append({"type": "warning", "message": f"Payroll is {ratio * 100:.0f}% of revenue — unusually high"})
    if "ACORD_140" in selected_form_ids:
        if flags.get("property_has_bi_coverage") and not facts.get("business_income_limit"):
            issues.append({"type": "warning", "message": "Business Income coverage detected — BI limit required"})
        if not facts.get("valuation_method"):
            issues.append({"type": "warning", "message": "Property valuation method not specified on ACORD 140"})
    if "ACORD_131" in selected_form_ids and not facts.get("gl_limits"):
        issues.append({"type": "hard_stop", "message": "Umbrella selected but GL limits missing"})
    return issues


def calculate_sqs(
    facts, flags, mapped_data, form_schema, selected_form_ids,
    hard_stops, soft_stops, tier2_score,
    form_id=None, schema_size=None, fields_mapped=None,
) -> dict:
    breakdown = {}
    issues = []
    recommendations = []
    fraud_penalty = 0
    fid = form_id or (selected_form_ids[0] if selected_form_ids else "UNKNOWN")
    is_cert_only  = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
    total_fields  = schema_size  if schema_size  is not None else len(form_schema)
    filled_fields = fields_mapped if fields_mapped is not None else sum(
        1 for v in mapped_data.values() if v is not None and str(v).strip() not in ("", "null", "None")
    )
    fill_rate = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    def _bar(v):
        return "#10b981" if v >= 80 else "#f59e0b" if v >= 60 else "#ef4444"

    if is_cert_only:
        chks  = [bool(facts.get("applicant_name") or facts.get("certificate_holder")),
                 bool(facts.get("effective_date")), bool(facts.get("policy_number")),
                 bool(facts.get("gl_limits") or facts.get("gl_aggregate"))]
        struct = int(sum(chks) / len(chks) * 100)
    elif fid == "ACORD_125":
        chks  = [bool(facts.get("applicant_name")), bool(facts.get("mailing_address")),
                 bool(facts.get("effective_date")), bool(facts.get("lines_of_business")),
                 bool(facts.get("contact_name") or facts.get("contact_phone") or facts.get("contact_email")),
                 bool(facts.get("producer_name"))]
        struct = int(sum(chks) / len(chks) * 100)
        missing = [l for l, ok in zip(["applicant name", "mailing address", "effective date",
                                        "lines of business", "contact info", "producer name"], chks) if not ok]
        if missing:
            recommendations.append("ACORD 125 missing: " + ", ".join(missing))
    elif fid == "ACORD_126":
        chks  = [bool(facts.get("gl_limits") or facts.get("gl_aggregate") or facts.get("gl_each_occurrence")),
                 bool(facts.get("gl_class_codes")), bool(facts.get("operations_description")),
                 bool(facts.get("total_payroll") or facts.get("total_revenue")), bool(facts.get("gl_form_type"))]
        struct = int(sum(chks) / len(chks) * 100)
        if not facts.get("gl_class_codes"):
            issues.append("GL class codes missing")
            recommendations.append("Provide GL class codes")
        if not facts.get("gl_form_type"):
            recommendations.append("Specify GL form type: occurrence or claims-made")
    elif fid == "ACORD_140":
        min_cope = [bool(facts.get("locations")), bool(facts.get("occupancy_type")),
                    bool(facts.get("construction_type")),
                    bool(facts.get("property_building_value") or facts.get("property_bpp_value"))]
        if not all(min_cope):
            struct = 0
            issues.append("Minimum Viable COPE incomplete")
            recommendations.append("Required: street address, occupancy, construction type, building/BPP value")
        else:
            carrier_cope = [bool(facts.get(k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]]
            struct = int(60 + (sum(carrier_cope) / len(carrier_cope)) * 40)
            mc = [l for l, ok in zip(["year built", "roof year", "sprinkler system",
                                       "fire protection class", "valuation method", "coinsurance %"], carrier_cope) if not ok]
            if mc:
                recommendations.append("For Carrier-Grade COPE provide: " + ", ".join(mc))
    else:
        struct = fill_rate
    breakdown["structural_completeness"] = struct

    if fid == "ACORD_125":
        chks = [bool(facts.get("total_revenue") or facts.get("total_payroll")),
                bool(facts.get("operations_description")), bool(facts.get("num_employees")),
                bool(facts.get("fein")), bool(facts.get("entity_type"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if facts.get("naics_code") or facts.get("sic_code"):
            exp_score = min(100, exp_score + 5)
    elif fid == "ACORD_126":
        chks = [bool(facts.get("gl_class_codes")),
                bool(facts.get("total_payroll") or facts.get("total_revenue")),
                bool(facts.get("operations_description")), bool(facts.get("gl_limits"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if isinstance(facts.get("gl_class_codes"), list) and facts.get("gl_class_codes"):
            exp_score = min(100, exp_score + 10)
        else:
            exp_score = max(0, exp_score - 15)
            recommendations.append("Add GL class codes")
    elif fid == "ACORD_140":
        chks = [bool(facts.get("valuation_method")),
                bool(facts.get("coinsurance_percentage") or facts.get("property_deductible_aop")),
                bool(facts.get("property_building_value") or facts.get("property_bpp_value")),
                bool(facts.get("occupancy_type"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if not facts.get("valuation_method"):
            exp_score = max(0, exp_score - 15)
            recommendations.append("Specify RCV or ACV valuation method")
    else:
        chks = [bool(facts.get("total_revenue") or facts.get("total_payroll")),
                bool(facts.get("operations_description"))]
        exp_score = int(sum(chks) / len(chks) * 100)
    breakdown["exposure_consistency"] = exp_score

    if fid == "ACORD_140":
        prop = struct
        if flags.get("property_has_bi_coverage") and facts.get("business_income_limit") and not facts.get("period_of_restoration"):
            prop = max(0, prop - 8)
            recommendations.append("Add Period of Restoration")
        if flags.get("property_has_peril_deductibles"):
            d = sum(bool(facts.get(f)) for f in ["property_deductible_wind", "property_deductible_earthquake", "property_deductible_flood"])
            if d == 0:
                prop = max(0, prop - 10)
                recommendations.append("Define peril deductibles")
    elif flags.get("has_property_coverage"):
        min_ok = all([bool(facts.get("locations")), bool(facts.get("occupancy_type")),
                      bool(facts.get("construction_type")),
                      bool(facts.get("property_building_value") or facts.get("property_bpp_value"))])
        if not min_ok:
            prop = 0
            issues.append("Minimum Viable COPE incomplete")
        else:
            cc   = [bool(facts.get(k)) for k in ["year_built", "roof_year", "sprinkler_system",
                                                   "fire_protection_class", "valuation_method", "coinsurance_percentage"]]
            prop = int(60 + (sum(cc) / len(cc)) * 40)
    else:
        prop = 100
    breakdown["property_integrity"] = prop

    has_loss    = flags.get("has_loss_history") or bool(facts.get("num_claims"))
    has_carrier = bool(facts.get("prior_carrier"))
    loss_score  = 90 if (has_loss and has_carrier) else 80 if has_loss else 65 if has_carrier else 50
    if not has_loss:
        recommendations.append("Attach 3–5 years of loss runs to improve SQS")
    breakdown["loss_history_alignment"] = loss_score

    if flags.get("has_umbrella"):
        has_underlying = bool(facts.get("gl_limits") or facts.get("auto_liability_limit"))
        umbrella_score = 100 if has_underlying else 0
        if not has_underlying:
            issues.append("Umbrella detected but no underlying GL/Auto limits")
            recommendations.append("Provide underlying limits")
    else:
        umbrella_score = 100
    breakdown["umbrella_limit_adequacy"] = umbrella_score

    narrative_score = min(tier2_score, 100)
    if len(str(facts.get("operations_description") or "")) > 50:
        narrative_score = min(100, narrative_score + 10)
    breakdown["narrative_quality"] = narrative_score

    weights = {
        "structural_completeness": 0.25, "exposure_consistency":    0.25,
        "property_integrity":      0.15, "loss_history_alignment":  0.15,
        "umbrella_limit_adequacy": 0.10, "narrative_quality":       0.10,
    }
    raw_score = int(sum(breakdown[k] * w for k, w in weights.items()))

    cope_hard = fid == "ACORD_140" and prop == 0
    umb_fail  = flags.get("has_umbrella") and umbrella_score == 0
    if hard_stops or cope_hard or umb_fail:
        raw_score = min(raw_score, 60)
    elif soft_stops:
        raw_score = min(raw_score, 85)
    raw_score = max(0, raw_score - fraud_penalty)

    tier, tc = (
        ("Carrier-Ready", "green")   if raw_score >= 90 else
        ("Review-Ready",  "yellow")  if raw_score >= 75 else
        ("At-Risk",       "orange")  if raw_score >= 60 else
        ("Decline-Prone", "red")
    )
    routing = (
        "auto_quote"  if raw_score >= 85 else
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
        "sqs_score": raw_score, "tier": tier, "tier_color": tc,
        "grade": "A" if raw_score >= 90 else "B" if raw_score >= 80 else "C" if raw_score >= 70 else "D" if raw_score >= 60 else "F",
        "routing_decision": routing, "breakdown": breakdown,
        "risk_drivers": risk_drivers, "issues": issues,
        "recommendations": recommendations, "fraud_penalty": fraud_penalty,
        "fill_rate": fill_rate, "form_id": fid,
    }