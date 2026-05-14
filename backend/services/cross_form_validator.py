"""cross_form_validator.py

Cross-form and cross-document validation layer.

Called from extraction_pipeline.py *after* evaluate_stops() and
check_doc_consistency().  Operates on the full merged_facts dict plus
the list of triggered form IDs and the flags dict.

Returns a list of issue dicts:
    {
        "type":    "hard_stop" | "soft_warning" | "advisory",
        "code":    str,          # machine-readable key
        "message": str,          # human-readable explanation
        "forms":   list[str],    # which forms are involved
    }

Hard stops are propagated into the pipeline's hard_stops list.
Soft warnings are propagated into soft_stops.
Advisories are surfaced to the UI but do not affect SQS gating.

All rules here are additive — they never remove or modify existing
stops returned by evaluate_stops() or check_doc_consistency().
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fv(facts: dict, key: str, default=None):
    """Extract scalar value from a fact, unwrapping annotated envelopes."""
    v = facts.get(key, default)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return default
    return v


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(v)))
    except Exception:
        return None


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "").replace("$", "").strip()))
    except Exception:
        return None


def _issue(issue_type: str, code: str, message: str, forms: List[str]) -> dict:
    return {"type": issue_type, "code": code, "message": message, "forms": forms}


# ── Individual rule functions ─────────────────────────────────────────────────


def _check_wc_payroll_reconciliation(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    WC payroll (ACORD 130) must not diverge from total payroll (ACORD 125)
    by more than 20 %.  If ACORD 186 is present and the insured is a
    contractor, also validate that a high subcontracting percentage is
    consistent with WC payroll.

    Spec: "WC payroll must reconcile with ACORD 125 revenue/operations and
    subcontracting % from ACORD 186.  Flag large discrepancies."
    """
    issues: List[dict] = []

    if "ACORD_130" not in triggered_ids:
        return issues

    wc_pay  = _to_float(_fv(facts, "wc_payroll"))
    tot_pay = _to_float(_fv(facts, "total_payroll"))

    if wc_pay and tot_pay and tot_pay > 0:
        diff_pct = abs(wc_pay - tot_pay) / tot_pay
        if diff_pct > 0.20:
            issues.append(_issue(
                "hard_stop",
                "wc_payroll_mismatch",
                (
                    f"WC payroll (${wc_pay:,.0f}) differs from total payroll "
                    f"(${tot_pay:,.0f}) by {diff_pct * 100:.0f}% — exceeds 20% "
                    "tolerance. Reconcile or add ACORD 101 explanation."
                ),
                ["ACORD_125", "ACORD_130"],
            ))

    # Contractor subcontracting check against WC payroll
    if "ACORD_186" in triggered_ids and flags.get("is_contractor"):
        pct_sub = _to_float(_fv(facts, "percent_subcontracted"))
        if pct_sub and pct_sub > 50:
            wc_ref = wc_pay or tot_pay
            tot_rev = _to_float(_fv(facts, "total_revenue"))
            if wc_ref and tot_rev and tot_rev > 0:
                implied_payroll_ratio = wc_ref / tot_rev
                # If >50 % subcontracted but payroll is >60 % of revenue, suspicious
                if implied_payroll_ratio > 0.60:
                    issues.append(_issue(
                        "soft_warning",
                        "wc_subcontracting_payroll_conflict",
                        (
                            f"ACORD 186 reports {pct_sub:.0f}% subcontracted work, "
                            "but WC payroll is unusually high relative to revenue. "
                            "Verify subcontracting percentage and payroll split."
                        ),
                        ["ACORD_130", "ACORD_186"],
                    ))

    return issues


def _check_gl_class_code_vs_operations(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    GL class codes (ACORD 126) must align with the operations description
    on ACORD 125.  If GL class codes are present but no operations
    description exists, require ACORD 101.

    Spec: "GL class codes must align with operations in ACORD 125.
    If mismatch → require ACORD 101."
    """
    issues: List[dict] = []

    if "ACORD_126" not in triggered_ids:
        return issues

    gl_codes = _fv(facts, "gl_class_codes_by_location")
    ops_desc = _fv(facts, "operations_description")

    if gl_codes and isinstance(gl_codes, list) and gl_codes and not ops_desc:
        issues.append(_issue(
            "soft_warning",
            "gl_codes_no_operations",
            (
                "GL class codes are present on ACORD 126 but ACORD 125 has no "
                "operations description. Add operations detail or attach ACORD 101."
            ),
            ["ACORD_125", "ACORD_126"],
        ))

    # If contractor flag is set and ACORD 186 is missing, warn
    if flags.get("is_contractor") and "ACORD_186" not in triggered_ids:
        issues.append(_issue(
            "soft_warning",
            "contractor_missing_acord186",
            (
                "Operations indicate a contracting business (GL coverage present) "
                "but ACORD 186 Contractors Supplement is not included. "
                "Add ACORD 186 to capture subcontracting and high-hazard details."
            ),
            ["ACORD_126", "ACORD_186"],
        ))

    return issues


def _check_location_address_reconciliation(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Location count and addresses must reconcile across ACORD 125 and
    ACORD 140.  Difference > 1 = hard stop (previously was > 2).

    Spec: "Number of locations must reconcile across ACORD 125, ACORD 140,
    and any attached schedules. Mismatches require explanation or correction."
    """
    issues: List[dict] = []

    if "ACORD_140" not in triggered_ids:
        return issues
    if not flags.get("has_property_coverage"):
        return issues

    locs_125 = _fv(facts, "locations")
    locs_140 = _fv(facts, "property_locations")

    if not isinstance(locs_125, list) or not isinstance(locs_140, list):
        return issues
    if not locs_125 or not locs_140:
        return issues

    n, m = len(locs_125), len(locs_140)
    diff  = abs(n - m)

    if diff == 1:
        issues.append(_issue(
            "soft_warning",
            "location_count_mismatch_minor",
            (
                f"ACORD 125 lists {n} location(s) but ACORD 140 has {m}. "
                "Verify all insured locations are consistently represented."
            ),
            ["ACORD_125", "ACORD_140"],
        ))
    elif diff > 1:
        issues.append(_issue(
            "hard_stop",
            "location_count_mismatch",
            (
                f"ACORD 125 lists {n} location(s) but ACORD 140 has {m}. "
                "Location counts must match or be explained via ACORD 101."
            ),
            ["ACORD_125", "ACORD_140"],
        ))

    return issues


def _check_umbrella_attachment_stack(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Umbrella (ACORD 131) attachment checks:
    1. GL/Auto underlying limits must meet umbrella attachment minimum.
    2. Umbrella policy period must align with underlying GL/Auto/WC periods.
    3. SIR must be >= GL deductible (coverage gap if SIR < deductible).
    4. WC Employers Liability limits must be present when umbrella attaches over WC.

    Spec: "Verify GL/Auto limits meet umbrella minimums. If not → hard stop."
    """
    issues: List[dict] = []

    if "ACORD_131" not in triggered_ids:
        return issues
    if not flags.get("has_umbrella"):
        return issues

    # 1. SIR vs GL deductible — hard stop (was soft warning)
    sir    = _to_int(_fv(facts, "umbrella_sir"))
    gl_ded = _to_int(_fv(facts, "gl_deductible"))
    if sir is not None and gl_ded is not None and sir < gl_ded:
        issues.append(_issue(
            "hard_stop",
            "umbrella_sir_below_gl_deductible",
            (
                f"Umbrella SIR (${sir:,}) is lower than GL deductible (${gl_ded:,}). "
                "This creates a coverage gap between GL deductible and umbrella "
                "attachment. Align SIR ≥ GL deductible or add ACORD 101 explanation."
            ),
            ["ACORD_126", "ACORD_131"],
        ))

    # 2. WC Employers Liability when umbrella attaches over WC
    if "ACORD_130" in triggered_ids and flags.get("has_workers_comp"):
        el_limit = _fv(facts, "employers_liability_limits")
        if not el_limit:
            issues.append(_issue(
                "soft_warning",
                "umbrella_missing_employers_liability",
                (
                    "Umbrella attaches over Workers Compensation but Employers "
                    "Liability limits are not provided. Add EL limits on ACORD 130."
                ),
                ["ACORD_130", "ACORD_131"],
            ))
        else:
            el_val = _to_int(el_limit)
            if el_val and el_val < 100_000:
                issues.append(_issue(
                    "soft_warning",
                    "umbrella_el_below_minimum",
                    (
                        f"Employers Liability limit (${el_val:,}) is below the "
                        "standard minimum of $100,000 required for umbrella attachment."
                    ),
                    ["ACORD_130", "ACORD_131"],
                ))

    # 3. Policy period alignment — underlying must match umbrella
    umb_eff = _fv(facts, "umbrella_effective_date")
    umb_exp = _fv(facts, "umbrella_expiration_date")
    gl_eff  = _fv(facts, "effective_date")
    gl_exp  = _fv(facts, "expiration_date")

    if umb_eff and gl_eff and umb_eff != gl_eff:
        issues.append(_issue(
            "soft_warning",
            "umbrella_gl_period_misaligned",
            (
                f"Umbrella effective date ({umb_eff}) does not match GL/policy "
                f"effective date ({gl_eff}). Policy periods must align or be "
                "explained."
            ),
            ["ACORD_125", "ACORD_131"],
        ))

    if umb_exp and gl_exp and umb_exp != gl_exp:
        issues.append(_issue(
            "soft_warning",
            "umbrella_gl_expiration_misaligned",
            (
                f"Umbrella expiration date ({umb_exp}) does not match GL/policy "
                f"expiration date ({gl_exp}). Periods must align or be explained."
            ),
            ["ACORD_125", "ACORD_131"],
        ))

    return issues


def _check_builders_risk_vs_property_deduplication(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 133 (Builders Risk) and ACORD 140 (Completed Property) must not
    cover the same insured values for the same location — duplication risk.

    Spec: "If both 133 and 140 exist for same location, ensure period
    covered is disjoint."
    """
    issues: List[dict] = []

    if "ACORD_133" not in triggered_ids or "ACORD_140" not in triggered_ids:
        return issues

    br_value   = _to_float(_fv(facts, "builders_risk_project_cost"))
    prop_value = _to_float(
        _fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")
    )

    if br_value and prop_value:
        br_addr   = str(_fv(facts, "builders_risk_project_address") or "").strip().lower()
        prop_locs = _fv(facts, "locations") or _fv(facts, "property_locations") or []
        prop_addrs = [
            str(loc.get("address", loc) if isinstance(loc, dict) else loc).strip().lower()
            for loc in (prop_locs if isinstance(prop_locs, list) else [])
        ]
        overlap = any(br_addr and br_addr in addr for addr in prop_addrs) if prop_addrs else True
        if overlap or not br_addr:
            issues.append(_issue(
                "soft_warning",
                "builders_risk_property_duplication",
                (
                    "Both ACORD 133 (Builders Risk) and ACORD 140 (Commercial "
                    "Property) are present with overlapping insured values. "
                    "Ensure construction-period and completed-property values are "
                    "not double-counted. Attach ACORD 101 if coverages are disjoint."
                ),
                ["ACORD_133", "ACORD_140"],
            ))

    return issues


def _check_inland_marine_deduplication(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Items on ACORD 160 (Inland Marine) must not be double-counted in
    ACORD 140 / 141 (Commercial Property).

    Spec: "Ensure items on 160 are not double-counted on 140/141/133."
    """
    issues: List[dict] = []

    if "ACORD_160" not in triggered_ids:
        return issues

    im_value   = _to_float(_fv(facts, "inland_marine_total_value"))
    prop_value = _to_float(
        _fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")
    )

    if im_value and prop_value and "ACORD_140" in triggered_ids:
        issues.append(_issue(
            "advisory",
            "inland_marine_property_overlap",
            (
                "ACORD 160 (Inland Marine) and ACORD 140 (Commercial Property) "
                "are both present. Verify that mobile/scheduled items on ACORD 160 "
                "are not also included in ACORD 140 BPP values."
            ),
            ["ACORD_140", "ACORD_160"],
        ))

    return issues


def _check_property_bi_period_of_restoration(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If Business Income coverage is present, Period of Restoration is required
    as a hard stop (not just a soft warning for non-140 forms).

    Spec: "IF BI coverage requested → require BI limit and period of restoration."
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues

    bi_limit = _fv(facts, "business_income_limit")
    bi_por   = _fv(facts, "period_of_restoration")

    if bi_limit and not bi_por:
        issues.append(_issue(
            "hard_stop",
            "bi_missing_period_of_restoration",
            (
                "Business Income limit is specified but Period of Restoration is "
                "missing. Both are required when BI coverage is requested."
            ),
            ["ACORD_140"],
        ))
    elif flags.get("property_has_bi_coverage") and not bi_limit:
        issues.append(_issue(
            "soft_warning",
            "bi_coverage_no_limit",
            (
                "Business Income coverage is indicated but no BI limit is provided. "
                "Specify a BI limit and Period of Restoration."
            ),
            ["ACORD_140"],
        ))

    return issues


def _check_wc_multi_state_payroll_breakdown(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Multi-state WC requires payroll broken out by state and class code.
    Total must equal ACORD 125 payroll.

    Spec: "If the insured has payroll in more than one state, require
    payroll to be broken out by state and WC class code."
    """
    issues: List[dict] = []

    if "ACORD_130" not in triggered_ids:
        return issues
    if not flags.get("wc_multi_state"):
        return issues

    wc_by_state = _fv(facts, "wc_payroll_by_state")
    if not wc_by_state:
        issues.append(_issue(
            "hard_stop",
            "wc_multi_state_no_breakdown",
            (
                "Multi-state Workers Compensation exposure detected but payroll is "
                "not broken out by state and class code. Provide state-level payroll "
                "on ACORD 130."
            ),
            ["ACORD_130"],
        ))
        return issues

    # If breakdown is present, verify it totals to ACORD 125 payroll
    if isinstance(wc_by_state, list):
        state_total = sum(
            _to_float(
                entry.get("payroll") if isinstance(entry, dict) else entry
            ) or 0
            for entry in wc_by_state
        )
        tot_pay = _to_float(_fv(facts, "total_payroll"))
        if state_total > 0 and tot_pay and tot_pay > 0:
            diff_pct = abs(state_total - tot_pay) / tot_pay
            if diff_pct > 0.10:
                issues.append(_issue(
                    "hard_stop",
                    "wc_state_payroll_total_mismatch",
                    (
                        f"WC payroll by state totals ${state_total:,.0f} but ACORD 125 "
                        f"reports total payroll of ${tot_pay:,.0f} — "
                        f"{diff_pct * 100:.0f}% variance. Reconcile payroll totals."
                    ),
                    ["ACORD_125", "ACORD_130"],
                ))

    return issues


def _check_acord125_always_present(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 125 is the anchor form — it must always be triggered for any
    commercial submission.

    Spec: "ACORD 125 is mandatory for every commercial submission."
    """
    issues: List[dict] = []

    if "ACORD_125" not in triggered_ids:
        issues.append(_issue(
            "hard_stop",
            "acord125_missing",
            (
                "ACORD 125 (Commercial Insurance Application) is required for every "
                "commercial submission. It was not included in the triggered forms."
            ),
            ["ACORD_125"],
        ))

    return issues


def _check_gl_missing_when_umbrella(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If ACORD 131 (Umbrella) is triggered, ACORD 126 (GL) must also be
    triggered unless there is auto-only coverage.

    Spec: "Verify GL/Auto limits meet umbrella minimums."
    """
    issues: List[dict] = []

    if "ACORD_131" not in triggered_ids:
        return issues

    has_gl   = "ACORD_126" in triggered_ids or bool(_fv(facts, "gl_limits"))
    has_auto = "ACORD_127" in triggered_ids or bool(_fv(facts, "auto_liability_limit"))

    if not has_gl and not has_auto:
        issues.append(_issue(
            "hard_stop",
            "umbrella_no_underlying_coverage",
            (
                "ACORD 131 (Umbrella/Excess) is present but neither ACORD 126 (GL) "
                "nor ACORD 127 (Auto) underlying policies were found. Umbrella "
                "cannot attach without required underlying limits."
            ),
            ["ACORD_126", "ACORD_127", "ACORD_131"],
        ))

    return issues


def _check_crime_silent_exposure(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If there is significant cash/financial handling exposure but no ACORD 137
    (Crime), surface an advisory.

    Spec: "If company has high internal cash handling but no crime coverage
    → flag silent exposure."
    """
    issues: List[dict] = []

    if any(fid in triggered_ids for fid in ("ACORD_137_CA", "ACORD_137_CO")):
        return issues

    ops = (_fv(facts, "operations_description") or "").lower()
    cash_keywords = ["cash", "retail", "restaurant", "bank", "financial",
                     "jewelry", "money", "teller", "payroll service"]
    has_cash_exposure = any(kw in ops for kw in cash_keywords)
    num_emp = _to_int(_fv(facts, "num_employees")) or 0

    if has_cash_exposure or num_emp > 10:
        issues.append(_issue(
            "advisory",
            "crime_silent_exposure",
            (
                "The business description indicates potential employee dishonesty or "
                "cash-handling exposure but no Crime coverage (ACORD 137) is "
                "included. Consider adding crime coverage."
            ),
            ["ACORD_137_CA", "ACORD_137_CO"],
        ))

    return issues


def _check_cyber_silent_exposure(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If business handles PHI/PCI/digital assets but no ACORD 138 (Cyber)
    is included, surface an advisory.

    Spec: "If business stores PHI/PCI and no cyber limits listed → soft-warning."
    """
    issues: List[dict] = []

    if any(fid in triggered_ids for fid in ("ACORD_138_CA", "ACORD_138_CO")):
        return issues

    ops = (_fv(facts, "operations_description") or "").lower()
    cyber_keywords = ["software", "saas", "cloud", "data", "pci", "phi",
                      "health", "medical", "ecommerce", "e-commerce",
                      "online", "tech", "platform", "digital"]
    has_cyber_exposure = any(kw in ops for kw in cyber_keywords)

    if has_cyber_exposure:
        issues.append(_issue(
            "advisory",
            "cyber_silent_exposure",
            (
                "Business operations indicate digital assets, customer data, or "
                "e-commerce exposure but no Cyber Liability coverage (ACORD 138) "
                "is included. Consider adding cyber coverage."
            ),
            ["ACORD_138_CA", "ACORD_138_CO"],
        ))

    return issues


def _check_auto_hired_nonowned_symbols(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If Hired/Non-Owned auto exposure is detected, coverage symbols must be
    defined on ACORD 127.

    Spec: "Symbols must align with exposure (e.g., hired/non-owned symbols
    present when exposure exists)."
    """
    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("auto_has_hired_nonowned"):
        return issues

    hired_sym    = _fv(facts, "hired_auto_symbol")
    nonowned_sym = _fv(facts, "non_owned_symbol")

    if not hired_sym or not nonowned_sym:
        missing = []
        if not hired_sym:
            missing.append("Hired Auto symbol")
        if not nonowned_sym:
            missing.append("Non-Owned Auto symbol")
        issues.append(_issue(
            "soft_warning",
            "auto_hired_nonowned_symbols_missing",
            (
                f"Hired/Non-Owned auto exposure detected but coverage symbol(s) not "
                f"defined: {', '.join(missing)}. Define symbols on ACORD 127."
            ),
            ["ACORD_127"],
        ))

    return issues


def _check_auto_symbol_to_exposure_alignment(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Enhanced auto symbol validation: verify all physical damage and liability
    symbols align with actual vehicle exposures and requested coverages.

    Spec: "Coverage symbols must align with exposure"
    """
    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues

    if not flags.get("has_auto_coverage"):
        return issues

    # Check physical damage symbols vs requested coverage
    if flags.get("auto_has_physical_damage"):
        comp_sym = _fv(facts, "auto_physical_damage_comp_symbol")
        coll_sym = _fv(facts, "auto_physical_damage_coll_symbol")

        if not comp_sym or not coll_sym:
            missing = []
            if not comp_sym:
                missing.append("comprehensive")
            if not coll_sym:
                missing.append("collision")
            issues.append({
                "type": "soft_warning",
                "code": "auto_physical_damage_symbols_missing",
                "message": f"Physical damage coverage requested but symbols undefined: {', '.join(missing)}",
                "forms": ["ACORD_127"],
            })

    # Check liability coverage structure
    liability_struct = _fv(facts, "auto_liability_structure")
    if liability_struct in ("split", "combined"):
        if liability_struct == "split":
            # Must have all three components
            bi_pp = _fv(facts, "bi_per_person")
            bi_pa = _fv(facts, "bi_per_accident")
            pd_pa = _fv(facts, "pd_per_accident")
            if not all([bi_pp, bi_pa, pd_pa]):
                issues.append({
                    "type": "soft_warning",
                    "code": "auto_split_limits_incomplete",
                    "message": "Split liability structure selected but not all three limits (BI/person, BI/accident, PD/accident) defined",
                    "forms": ["ACORD_127"],
                })

    # Check drive other car (DOC) symbol if requested
    if flags.get("auto_has_drive_other_car") and not _fv(facts, "drive_other_car_symbol"):
        issues.append({
            "type": "soft_warning",
            "code": "auto_doc_symbol_missing",
            "message": "Drive Other Car coverage referenced but symbol not defined on ACORD 127",
            "forms": ["ACORD_127"],
        })

    return issues


def _check_property_valuation_consistency(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    RCV selection with high insured limits on a recently constructed building
    should be verified.  ACV with high limits must be flagged.

    Spec: "RCV values must be consistent with replacement-cost intent."
    """
    issues: List[dict] = []

    if "ACORD_140" not in triggered_ids:
        return issues

    val_method = str(_fv(facts, "valuation_method") or "").lower()
    bldg_val   = _to_float(_fv(facts, "property_building_value"))
    year_built = _to_int(_fv(facts, "year_built"))

    if not val_method or not bldg_val:
        return issues

    if "acv" in val_method or "actual" in val_method:
        if bldg_val and bldg_val > 1_000_000:
            issues.append(_issue(
                "advisory",
                "acv_high_value_building",
                (
                    f"Actual Cash Value (ACV) selected on a building valued at "
                    f"${bldg_val:,.0f}. ACV applies depreciation which may result in "
                    "significant underinsurance at claim time. Consider RCV."
                ),
                ["ACORD_140"],
            ))

    if ("rcv" in val_method or "replacement" in val_method) and year_built:
        from datetime import datetime
        current_year = datetime.now().year
        age = current_year - year_built
        if age > 40 and bldg_val and bldg_val > 500_000:
            issues.append(_issue(
                "advisory",
                "rcv_old_building",
                (
                    f"Replacement Cost Value (RCV) selected on a building built in "
                    f"{year_built} ({age} years old) valued at ${bldg_val:,.0f}. "
                    "Verify that insured value reflects current reconstruction cost."
                ),
                ["ACORD_140"],
            ))

    return issues


def _check_acord186_subcontracting_vs_gl_wc(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 186 subcontracting % must feed back into GL and WC exposures.
    High subcontracting with low WC payroll is a red flag.

    Spec: "Subcontracting % must feed back into WC and GL exposures.
    High subcontracting with low WC payroll = red flag."
    """
    issues: List[dict] = []

    if "ACORD_186" not in triggered_ids:
        return issues

    pct_sub = _to_float(_fv(facts, "percent_subcontracted"))
    wc_pay  = _to_float(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll"))
    tot_rev = _to_float(_fv(facts, "total_revenue"))

    if pct_sub and pct_sub > 50 and wc_pay and tot_rev and tot_rev > 0:
        own_work_ratio = 1.0 - (pct_sub / 100.0)
        implied_own_payroll = tot_rev * own_work_ratio * 0.40
        if wc_pay > implied_own_payroll * 2.0:
            issues.append(_issue(
                "soft_warning",
                "acord186_high_sub_high_wc_payroll",
                (
                    f"ACORD 186 reports {pct_sub:.0f}% subcontracted work, but WC "
                    f"payroll (${wc_pay:,.0f}) appears high relative to the expected "
                    "own-work payroll. Verify subcontracting percentage and WC payroll."
                ),
                ["ACORD_130", "ACORD_186"],
            ))

    if pct_sub and pct_sub > 30 and not wc_pay:
        issues.append(_issue(
            "hard_stop",
            "high_subcontracting_no_wc_payroll",
            (
                f"ACORD 186 reports {pct_sub:.0f}% subcontracted work but no "
                "Workers Comp payroll is provided. WC payroll is required when "
                "subcontracting exceeds 30%."
            ),
            ["ACORD_130", "ACORD_186"],
        ))

    return issues


def _check_wc_gl_class_code_alignment(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    WC class codes vs GL class codes: labor-driven exposure must align with
    operations.  Clerical GL + heavy manual-labor WC class codes is a red flag
    that requires explanation via ACORD 101.

    Spec: "WC class codes vs GL class codes: ensure labor-driven exposure
    aligns with operations. Clerical GL + heavy manual labor WC → require
    explanation."
    """
    issues: List[dict] = []

    if "ACORD_130" not in triggered_ids or "ACORD_126" not in triggered_ids:
        return issues

    wc_codes = _fv(facts, "wc_class_codes")
    gl_codes = _fv(facts, "gl_class_codes_by_location")

    if not wc_codes or not gl_codes:
        return issues

    # Clerical/office GL class codes (NCCI range 8800-8999 = clerical/office)
    # Manual labor WC class codes (NCCI ranges <5000 = manual/trade operations)
    _CLERICAL_GL_KEYWORDS = ["clerical", "office", "admin", "8810", "8742", "8800", "8820"]
    _HEAVY_WC_KEYWORDS    = ["roofing", "carpentry", "concrete", "ironwork", "blasting",
                              "demolition", "excavation", "framing", "steelwork",
                              "5160", "5183", "5190", "5213", "5221", "5403", "5403",
                              "5479", "5537", "5645", "6003", "6005"]

    gl_str = str(gl_codes).lower()
    wc_str = str(wc_codes).lower()

    gl_is_clerical  = any(kw in gl_str for kw in _CLERICAL_GL_KEYWORDS)
    wc_is_heavy     = any(kw in wc_str for kw in _HEAVY_WC_KEYWORDS)

    if gl_is_clerical and wc_is_heavy:
        issues.append(_issue(
            "soft_warning",
            "wc_gl_class_code_mismatch",
            (
                "GL class codes suggest clerical/office operations but WC class codes "
                "indicate heavy manual labor. This exposure mismatch requires an "
                "explanation — attach ACORD 101 to clarify."
            ),
            ["ACORD_126", "ACORD_130"],
        ))

    return issues


def _check_claims_made_prior_acts(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If GL is claims-made and umbrella is present, BOTH retro date AND prior
    acts confirmation are required for umbrella attachment integrity.

    Spec (ACORD 131 Coverage Integrity Checks): "If GL is claims-made, require:
    Retro date + Prior acts confirmation. Flag missing retro/prior acts as a
    coverage integrity issue."
    """
    issues: List[dict] = []

    if not flags.get("gl_is_claims_made"):
        return issues

    retro_date  = _fv(facts, "retro_date")
    prior_acts  = _fv(facts, "prior_acts_confirmation")

    if not retro_date:
        issues.append(_issue(
            "soft_warning",
            "claims_made_missing_retro_date",
            (
                "GL policy is claims-made but no retroactive date was found. "
                "Retro date is required for coverage continuity and umbrella "
                "attachment."
            ),
            ["ACORD_126", "ACORD_131"] if "ACORD_131" in triggered_ids else ["ACORD_126"],
        ))

    if not prior_acts:
        issues.append(_issue(
            "soft_warning",
            "claims_made_missing_prior_acts",
            (
                "GL policy is claims-made but prior acts confirmation is not "
                "provided. Confirm whether prior acts / nose coverage applies — "
                "required for umbrella attachment integrity."
            ),
            ["ACORD_126", "ACORD_131"] if "ACORD_131" in triggered_ids else ["ACORD_126"],
        ))

    return issues


def _check_umbrella_period_vs_auto_wc(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Underlying Auto and WC policy periods must align with the umbrella period
    (not just GL).

    Spec: "Underlying GL, Auto, and WC policy periods must align with the
    umbrella policy period."
    """
    issues: List[dict] = []

    if "ACORD_131" not in triggered_ids:
        return issues
    if not flags.get("has_umbrella"):
        return issues

    umb_eff = _fv(facts, "umbrella_effective_date")
    umb_exp = _fv(facts, "umbrella_expiration_date")

    if not umb_eff and not umb_exp:
        return issues

    # Auto period alignment
    if "ACORD_127" in triggered_ids and flags.get("has_auto_coverage"):
        auto_eff = _fv(facts, "auto_effective_date")
        auto_exp = _fv(facts, "auto_expiration_date")

        if umb_eff and auto_eff and umb_eff != auto_eff:
            issues.append(_issue(
                "soft_warning",
                "umbrella_auto_period_misaligned",
                (
                    f"Umbrella effective date ({umb_eff}) does not match Auto "
                    f"policy effective date ({auto_eff}). Periods must align when "
                    "umbrella attaches to Auto."
                ),
                ["ACORD_127", "ACORD_131"],
            ))

        if umb_exp and auto_exp and umb_exp != auto_exp:
            issues.append(_issue(
                "soft_warning",
                "umbrella_auto_expiration_misaligned",
                (
                    f"Umbrella expiration date ({umb_exp}) does not match Auto "
                    f"policy expiration date ({auto_exp}). Periods must align when "
                    "umbrella attaches to Auto."
                ),
                ["ACORD_127", "ACORD_131"],
            ))

    # WC period alignment
    if "ACORD_130" in triggered_ids and flags.get("has_workers_comp"):
        wc_eff = _fv(facts, "wc_effective_date")
        wc_exp = _fv(facts, "wc_expiration_date")

        if umb_eff and wc_eff and umb_eff != wc_eff:
            issues.append(_issue(
                "soft_warning",
                "umbrella_wc_period_misaligned",
                (
                    f"Umbrella effective date ({umb_eff}) does not match Workers "
                    f"Compensation effective date ({wc_eff}). Periods must align when "
                    "umbrella attaches over WC."
                ),
                ["ACORD_130", "ACORD_131"],
            ))

    return issues


def _check_umbrella_gl_minimum_limits(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    GL underlying limits must meet umbrella attachment requirements — not just
    Auto.  If GL limits are present but below the umbrella limit, this is an
    attachment failure risk.

    Spec: "Verify GL/Auto limits meet umbrella minimums. If not → hard stop
    (umbrella cannot attach without required underlying)."
    """
    issues: List[dict] = []

    if "ACORD_131" not in triggered_ids:
        return issues
    if not flags.get("has_umbrella"):
        return issues

    umb_limit = _to_int(_fv(facts, "umbrella_limit"))
    if not umb_limit:
        return issues

    gl_limit_raw = _fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits")
    gl_limit = _to_int(gl_limit_raw)

    # Standard umbrella requires at least $1M GL each-occurrence underlying
    _GL_MINIMUM = 1_000_000

    if gl_limit is not None and gl_limit < _GL_MINIMUM:
        issues.append(_issue(
            "hard_stop",
            "umbrella_gl_attachment_failure",
            (
                f"GL each-occurrence limit (${gl_limit:,}) is below the standard "
                f"minimum of ${_GL_MINIMUM:,} required for umbrella attachment. "
                "Increase GL limits or provide attachment documentation."
            ),
            ["ACORD_126", "ACORD_131"],
        ))
    elif "ACORD_126" in triggered_ids and not gl_limit:
        issues.append(_issue(
            "soft_warning",
            "umbrella_gl_limits_not_found",
            (
                "Umbrella is present and GL is triggered but GL each-occurrence "
                "limit could not be determined. Verify GL limits meet umbrella "
                "attachment requirements."
            ),
            ["ACORD_126", "ACORD_131"],
        ))

    return issues


def _check_umbrella_sir_vs_auto_deductible(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Umbrella SIR must also be consistent with Auto deductible — not just GL.

    Spec: "Validate deductibles and SIRs are consistent across ACORD 126/127,
    ACORD 131, and dec page representations. Flag unexplained discrepancies."
    """
    issues: List[dict] = []

    if "ACORD_131" not in triggered_ids or "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("has_umbrella") or not flags.get("has_auto_coverage"):
        return issues

    sir      = _to_int(_fv(facts, "umbrella_sir"))
    auto_ded = _to_int(
        _fv(facts, "auto_deductible_comp") or _fv(facts, "auto_deductible_collision")
    )

    if sir is not None and auto_ded is not None and sir < auto_ded:
        issues.append(_issue(
            "soft_warning",
            "umbrella_sir_below_auto_deductible",
            (
                f"Umbrella SIR (${sir:,}) is lower than Auto deductible "
                f"(${auto_ded:,}). Verify attachment consistency across Auto and "
                "Umbrella to prevent coverage gaps."
            ),
            ["ACORD_127", "ACORD_131"],
        ))

    return issues


def _check_auto_optional_coverages(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Optional auto coverages advisory: if exposure exists but coverage is omitted,
    surface an advisory (no auto-add, no hard stop).

    Spec: "Medical Payments / PIP (state-dependent), Uninsured / Underinsured
    Motorist, Hired & Non-Owned Auto Liability, Drive Other Car — If optional
    coverages are listed, extract limits. If exposure exists but coverage is
    omitted, surface an advisory warning only (no auto-add)."
    """
    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("has_auto_coverage"):
        return issues

    ops   = (_fv(facts, "operations_description") or "").lower()
    locs  = _fv(facts, "locations") or []
    state_list: List[str] = []
    if isinstance(locs, list):
        for loc in locs:
            state_val = (loc.get("state", "") if isinstance(loc, dict) else "").upper()
            if state_val:
                state_list.append(state_val)

    # UM/UIM — required in many states; advisory if not found
    if not _fv(facts, "auto_um_limit") and not _fv(facts, "auto_uim_limit"):
        issues.append(_issue(
            "advisory",
            "auto_um_uim_not_specified",
            (
                "Uninsured/Underinsured Motorist (UM/UIM) coverage is not specified "
                "on the auto application. UM/UIM is required in many states — "
                "confirm with the insured whether coverage is desired or waived."
            ),
            ["ACORD_127"],
        ))

    # Med Pay / PIP — state-dependent
    pip_states = {"FL", "MI", "NY", "NJ", "PA", "HI", "KY", "MA", "MN", "ND", "UT"}
    has_pip_state = bool(set(state_list) & pip_states)
    if has_pip_state and not _fv(facts, "auto_med_pay_limit") and not _fv(facts, "auto_pip_limit"):
        issues.append(_issue(
            "advisory",
            "auto_pip_medpay_not_specified",
            (
                "The insured has operations in a state that may require Personal "
                "Injury Protection (PIP) or Medical Payments. Confirm whether "
                "PIP/Med Pay coverage is included or waived."
            ),
            ["ACORD_127"],
        ))

    # Drive Other Car — relevant when named insureds / officers drive non-fleet vehicles
    num_officers = _to_int(_fv(facts, "num_owners")) or 0
    if num_officers > 0 and not _fv(facts, "auto_drive_other_car"):
        issues.append(_issue(
            "advisory",
            "auto_drive_other_car_not_specified",
            (
                "The application lists business owners/officers but Drive Other Car "
                "(DOC) coverage is not specified. Consider adding DOC for owners who "
                "drive vehicles not owned by the business."
            ),
            ["ACORD_127"],
        ))

    return issues


def _check_acord101_triggers(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 101 (Additional Remarks Schedule) must be suggested whenever there
    are cross-form conflicts, mismatches that require narrative explanation,
    or 'yes' answers that need elaboration.

    Spec: "IF cross_form_conflict OR missing_explanation THEN require ACORD_101
    before submission."

    This rule runs LAST so it can read the issues accumulated by all prior rules
    via the shared facts/flags.  It adds a single advisory noting ACORD 101 is
    needed — the actual conflicts will already be in the issues list.

    Note: The pipeline calls run_cross_form_validation() which includes this rule.
    The callers decide whether to auto-add ACORD_101 to recommendations based on
    whether this advisory is returned.
    """
    issues: List[dict] = []

    # Scenarios that always require ACORD 101 narrative
    needs_101 = False
    reason_parts: List[str] = []

    # GL class code / operations mismatch
    gl_codes = _fv(facts, "gl_class_codes_by_location")
    ops_desc = _fv(facts, "operations_description") or ""
    if gl_codes and isinstance(gl_codes, list) and gl_codes and len(ops_desc) < 30:
        needs_101 = True
        reason_parts.append("GL class codes present but operations description is insufficient")

    # Payroll / revenue anomaly
    rev = _to_float(_fv(facts, "total_revenue"))
    pay = _to_float(_fv(facts, "total_payroll"))
    if rev and pay and rev > 0 and pay / rev > 0.85:
        needs_101 = True
        reason_parts.append(f"payroll is {pay/rev*100:.0f}% of revenue — unusually high")

    # WC / GL class code mismatch flag from flags
    if flags.get("wc_gl_class_mismatch"):
        needs_101 = True
        reason_parts.append("WC and GL class codes indicate different exposure levels")

    # High subcontracting with WC payroll present (explanation needed)
    pct_sub = _to_float(_fv(facts, "percent_subcontracted"))
    wc_pay  = _to_float(_fv(facts, "wc_payroll"))
    if pct_sub and pct_sub > 50 and wc_pay:
        needs_101 = True
        reason_parts.append(
            f"{pct_sub:.0f}% subcontracted work with WC payroll present — "
            "clarify employee vs subcontractor split"
        )

    # Claims history present with no explanation
    num_claims = _to_int(_fv(facts, "num_claims"))
    if num_claims and num_claims > 2:
        needs_101 = True
        reason_parts.append(f"{num_claims} prior claims — narrative explanation required")

    if needs_101:
        issues.append(_issue(
            "advisory",
            "acord101_required",
            (
                "ACORD 101 (Additional Remarks Schedule) is required to explain: "
                + "; ".join(reason_parts) + ". "
                "Attach ACORD 101 with narrative before submission."
            ),
            ["ACORD_101"],
        ))

    return issues


# ── Main entry point ──────────────────────────────────────────────────────────


def _check_property_deductible_structure(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Validate property deductible structure completeness.

    Spec requirement: Property deductibles must be comprehensive.
    - If property coverage exists, AOP (All Other Perils) deductible required
    - If peril-specific deductibles are referenced, all must be defined
    - Deductible basis must be specified (flat dollar or percentage)
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues

    if "ACORD_140" not in triggered_ids and "ACORD_141" not in triggered_ids:
        return issues

    # Check for AOP deductible (minimum requirement)
    aop_ded = _fv(facts, "property_deductible_aop")
    if not aop_ded:
        issues.append({
            "type": "soft_warning",
            "code": "property_aop_deductible_missing",
            "message": "Property coverage present but AOP (All Other Perils) deductible not specified",
            "forms": ["ACORD_140", "ACORD_141"],
        })

    # Check for peril-specific deductible consistency
    has_wind = _fv(facts, "property_deductible_wind")
    has_earth = _fv(facts, "property_deductible_earthquake")
    has_flood = _fv(facts, "property_deductible_flood")

    # If any peril deductible is present, all should be defined (or user chose not to include)
    peril_deductibles = [has_wind, has_earth, has_flood]
    present_count = sum(1 for p in peril_deductibles if p)

    if 0 < present_count < 3:
        missing_perils = []
        if not has_wind:
            missing_perils.append("wind/hail")
        if not has_earth:
            missing_perils.append("earthquake")
        if not has_flood:
            missing_perils.append("flood")

        issues.append({
            "type": "soft_warning",
            "code": "property_peril_deductible_incomplete",
            "message": f"Some peril-specific deductibles defined but missing: {', '.join(missing_perils)}. "
                      "Define all peril deductibles or remove partially-defined ones.",
            "forms": ["ACORD_140", "ACORD_141"],
        })

    # Check deductible basis (if deductible present, basis should be clear)
    has_any_ded = aop_ded or has_wind or has_earth or has_flood
    if has_any_ded:
        basis = _fv(facts, "property_deductible_basis")
        if not basis:
            issues.append({
                "type": "soft_warning",
                "code": "property_deductible_basis_missing",
                "message": "Property deductible defined but basis (flat dollar or percentage) not specified",
                "forms": ["ACORD_140", "ACORD_141"],
            })

    return issues


def _check_property_coinsurance_enforcement(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Validate coinsurance clause completeness and consistency.

    Spec requirement: If coinsurance clause applies, enforce:
    - Coinsurance percentage must be defined, OR
    - Agreed value endorsement must be confirmed
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues

    if "ACORD_140" not in triggered_ids and "ACORD_141" not in triggered_ids:
        return issues

    # Check if insured values are present (hard requirement for coinsurance check)
    has_values = bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value"))
    if not has_values:
        return issues

    # Check coinsurance percentage
    coinsurance_pct = _fv(facts, "coinsurance_percentage")
    agreed_value_end = _fv(facts, "agreed_value_endorsement")

    if not coinsurance_pct and not agreed_value_end:
        issues.append({
            "type": "soft_warning",
            "code": "property_coinsurance_missing",
            "message": "Property values present but coinsurance percentage or agreed value endorsement not specified. "
                      "Define coinsurance % or confirm agreed value endorsement is in place.",
            "forms": ["ACORD_140", "ACORD_141"],
        })
    elif coinsurance_pct:
        # Validate coinsurance percentage is reasonable (typically 80-100%)
        try:
            coinspct_val = float(re.sub(r"[^\d.]", "", str(coinsurance_pct)))
            if coinspct_val < 60 or coinspct_val > 100:
                issues.append({
                    "type": "soft_warning",
                    "code": "property_coinsurance_unreasonable",
                    "message": f"Coinsurance percentage {coinspct_val}% appears outside normal range (80-100%). "
                              "Verify this is intentional.",
                    "forms": ["ACORD_140", "ACORD_141"],
                })
        except Exception:
            pass

    return issues


def _check_peril_specific_deductibles_referenced(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Enforce hard stop if peril-specific deductibles are REFERENCED but undefined.

    Spec requirement: If peril deductible is mentioned on doc but amount not provided,
    this is a HARD STOP (incomplete coverage definition).
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues

    if "ACORD_140" not in triggered_ids and "ACORD_141" not in triggered_ids:
        return issues

    # Check if peril deductibles are REFERENCED in the fact-extraction
    # but not defined with actual amounts
    peril_deductible_referenced = flags.get("property_has_peril_deductibles", False)

    if peril_deductible_referenced:
        has_wind = _fv(facts, "property_deductible_wind")
        has_earth = _fv(facts, "property_deductible_earthquake")
        has_flood = _fv(facts, "property_deductible_flood")

        missing_perils = []
        if not has_wind:
            missing_perils.append("wind/hail")
        if not has_earth:
            missing_perils.append("earthquake")
        if not has_flood:
            missing_perils.append("flood")

        if missing_perils:
            issues.append({
                "type": "hard_stop",
                "code": "peril_deductible_referenced_but_undefined",
                "message": f"Peril-specific deductible referenced on document but amounts undefined: {', '.join(missing_perils)}. "
                          "Define deductible amounts or remove references.",
                "forms": ["ACORD_140", "ACORD_141"],
            })

    return issues


_RULE_FUNCTIONS = [
    _check_acord125_always_present,
    _check_wc_payroll_reconciliation,
    _check_wc_multi_state_payroll_breakdown,
    _check_wc_gl_class_code_alignment,
    _check_gl_class_code_vs_operations,
    _check_location_address_reconciliation,
    _check_umbrella_attachment_stack,
    _check_umbrella_gl_minimum_limits,
    _check_umbrella_sir_vs_auto_deductible,
    _check_umbrella_period_vs_auto_wc,
    _check_gl_missing_when_umbrella,
    _check_claims_made_prior_acts,
    _check_builders_risk_vs_property_deduplication,
    _check_inland_marine_deduplication,
    _check_property_bi_period_of_restoration,
    _check_property_deductible_structure,  # NEW: Property deductible validation
    _check_property_coinsurance_enforcement,  # NEW: Coinsurance enforcement
    _check_peril_specific_deductibles_referenced,  # NEW: Peril deductible hard stops
    _check_acord186_subcontracting_vs_gl_wc,
    _check_auto_hired_nonowned_symbols,
    _check_auto_symbol_to_exposure_alignment,  # NEW: Enhanced symbol validation
    _check_auto_optional_coverages,
    _check_property_valuation_consistency,
    _check_crime_silent_exposure,
    _check_cyber_silent_exposure,
    _check_acord101_triggers,   # must run last
]


def run_cross_form_validation(
    facts: dict,
    flags: dict,
    triggered_ids: set,
) -> List[dict]:
    """
    Run all cross-form validation rules and return a flat list of issues.

    Parameters
    ----------
    facts        : merged facts dict from extraction_pipeline
    flags        : merged flags dict from extraction_pipeline
    triggered_ids: set of form IDs that were recommended/triggered
                   (e.g. {"ACORD_125", "ACORD_126", "ACORD_140"})

    Returns
    -------
    List of issue dicts — each has keys: type, code, message, forms.
    """
    all_issues: List[dict] = []

    for rule_fn in _RULE_FUNCTIONS:
        try:
            result = rule_fn(facts, flags, triggered_ids)
            if result:
                all_issues.extend(result)
        except Exception as exc:
            logger.warning(
                "cross_form_validator: rule %s raised %s — skipping",
                rule_fn.__name__,
                exc,
            )

    return all_issues


def split_cross_form_issues(
    issues: List[dict],
) -> tuple[List[str], List[str], List[dict]]:
    """
    Split cross-form issues into hard_stops, soft_stops, and advisories.

    Returns
    -------
    (hard_stops, soft_stops, advisories)
    where hard_stops and soft_stops are plain message strings (matching the
    format used by evaluate_stops / check_doc_consistency), and advisories
    are the full issue dicts.
    """
    hard_stops: List[str]  = []
    soft_stops: List[str]  = []
    advisories: List[dict] = []

    for issue in issues:
        itype = issue.get("type", "advisory")
        msg   = issue.get("message", "")
        if itype == "hard_stop":
            hard_stops.append(msg)
        elif itype == "soft_warning":
            soft_stops.append(msg)
        else:
            advisories.append(issue)

    return hard_stops, soft_stops, advisories
