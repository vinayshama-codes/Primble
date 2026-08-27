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

All rules here are additive - they never remove or modify existing
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
    # Single canonical implementation lives in sqs_service; import it lazily to
    # avoid a circular import at module load (cross_form_validator is imported by
    # sqs_service indirectly through extraction_pipeline).
    from services.sqs_service import _to_int as _sqs_to_int
    return _sqs_to_int(v)


def _dates_differ(a: Any, b: Any) -> bool:
    """True only when two date strings resolve to DIFFERENT calendar dates.

    Beta Report §5.2: equivalent dates in different formats (e.g. 07/15/2025 vs
    7/15/2025) must NOT generate a hard stop. Both sides are normalized to ISO
    via the shared normalization layer before comparison; when either value is
    not a parseable date we fall back to a trimmed raw-string compare so two
    genuinely different non-date values still differ.
    """
    from services.normalization import normalize_date
    na, nb = normalize_date(a), normalize_date(b)
    if na is not None and nb is not None:
        return na != nb
    return str(a).strip() != str(b).strip()


def _issue(issue_type: str, code: str, message: str, forms: List[str]) -> dict:
    # `issue_id` is a durable, content-derived barcode used only by the display /
    # resolution-status layer (issue_registry.issue_id_for). It never affects the
    # cross-form gating below, which continues to key off `code`/`message`.
    #
    # `resolution` (issue_registry.resolution_for) tells the SQS panel how the
    # producer can fix THIS issue inline (enter a value / edit a schedule / add
    # an ACORD 101 note), keyed purely off `code`. Additive: None for any code
    # without an inline resolution, and never consulted by scoring/gating.
    from services.issue_registry import issue_id_for, resolution_for
    issue = {
        "type": issue_type, "code": code, "message": message, "forms": forms,
        "issue_id": issue_id_for(message, forms),
    }
    _res = resolution_for(code)
    if _res:
        issue["resolution"] = _res
    return issue


def _umbrella_in_scope(flags: dict) -> bool:
    """Single gate for every umbrella cross-form check (§6.5).

    Gates on the umbrella coverage flag alone - the SAME signal the SQS score
    pillar and the umbrella evidence state use - so scoring, evidence state and
    cross-form validation always agree on whether an umbrella is present. This
    keeps all umbrella checks uniform and is independent of which forms the user
    selected (it fires whenever umbrella coverage is detected, even if the
    umbrella form was deselected). A dec-page umbrella line that never set the
    coverage flag is therefore treated as "not yet a confirmed umbrella"
    everywhere - the recommender still surfaces the umbrella form for the user
    to confirm, at which point the flag is set and all layers engage together.
    """
    return bool(flags.get("has_umbrella"))


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
    tot_rev = _to_float(_fv(facts, "total_revenue"))

    if wc_pay and tot_pay and tot_pay > 0:
        diff_pct = abs(wc_pay - tot_pay) / tot_pay
        if diff_pct > 0.20:
            issues.append(_issue(
                "hard_stop",
                "wc_payroll_mismatch",
                (
                    f"WC payroll (${wc_pay:,.0f}) differs from total payroll "
                    f"(${tot_pay:,.0f}) by {diff_pct * 100:.0f}% - exceeds 20% "
                    "tolerance. Reconcile or add ACORD 101 explanation."
                ),
                ["ACORD_125", "ACORD_130"],
            ))

    # Spec §121: "WC payroll must reconcile with ACORD 125 revenue/operations".
    # If total_payroll is missing/zero, fall back to revenue-based sanity check:
    # WC payroll >85% of revenue is operationally implausible for most businesses.
    if wc_pay and tot_rev and tot_rev > 0:
        wc_to_rev_ratio = wc_pay / tot_rev
        if wc_to_rev_ratio > 0.85:
            issues.append(_issue(
                "soft_warning",
                "wc_payroll_vs_revenue",
                (
                    f"WC payroll (${wc_pay:,.0f}) is {wc_to_rev_ratio * 100:.0f}% of "
                    f"total revenue (${tot_rev:,.0f}) - unusually high. "
                    "Reconcile with operations or add ACORD 101 explanation."
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

    # Spec §56-61: Address Mapping - physical locations must align between
    # ACORD 125 and 140 by ADDRESS, not just count. Use the shared normalize_address
    # so street-suffix abbreviations (Street/St, Avenue/Ave, etc.) and unit markers
    # (#D13 vs D13) don't manufacture false location mismatches (Beta Report §5.2).
    def _normalise_location(loc) -> str:
        from services.normalization import normalize_address
        if isinstance(loc, dict):
            raw = " ".join(str(v) for v in loc.values() if v)
        else:
            raw = str(loc or "")
        return normalize_address(raw)

    addrs_125 = {_normalise_location(loc) for loc in locs_125 if loc}
    addrs_140 = {_normalise_location(loc) for loc in locs_140 if loc}
    addrs_125.discard("")
    addrs_140.discard("")

    if addrs_125 and addrs_140:
        # Locations in 125 not represented in 140 (substring-match either way
        # to tolerate minor differences like apartment numbers or zip suffixes).
        def _addr_present(addr, addr_set):
            return any(addr in other or other in addr for other in addr_set)

        unmatched_125 = [a for a in addrs_125 if not _addr_present(a, addrs_140)]
        unmatched_140 = [a for a in addrs_140 if not _addr_present(a, addrs_125)]

        if unmatched_125 or unmatched_140:
            issues.append(_issue(
                "soft_warning",
                "location_address_mismatch",
                (
                    "Location addresses do not align between ACORD 125 and ACORD 140. "
                    "Verify each insured location is represented on both forms or add "
                    "ACORD 101 explanation."
                ),
                ["ACORD_125", "ACORD_140"],
            ))

    return issues


def _check_umbrella_attachment_stack(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Umbrella (ACORD 131) attachment checks:
    1. WC Employers Liability limits must be present when umbrella attaches over WC.
    2. Umbrella policy period must align with underlying GL/Auto/WC periods.

    REMOVED 2026-08-12 - "SIR must be >= GL deductible". It fired as a HARD STOP
    (capping the package at 60) on the ordinary, healthy structure, and it
    compared two things that do not interact:

      * an Umbrella SIR applies only to claims the umbrella covers and the
        underlying does NOT - the drop-down case;
      * a GL deductible is what the insured pays on a claim the GL DOES cover.

    On a GL-covered claim the umbrella attaches above the GL LIMIT; the SIR
    never enters. So a $0 SIR against a $1,000 GL deductible is not a gap - a
    $0 SIR is the most favourable retention there is, and this codebase already
    says so in writing for the Auto twin.

    This is the same conflation as `umbrella_sir_below_auto_deductible`, deleted
    2026-08-07 after the client reported it firing on a submission where nothing
    was wrong. That entry called this GL sibling "defensible... not something
    the client flagged"; it has since been reported doing exactly the same
    thing, one coverage part over.

    The REAL attachment check - umbrella against the underlying GL LIMIT, which
    is the comparison that can genuinely reveal a gap - already exists and is
    untouched: `_check_umbrella_gl_minimum_limits`. Nothing is lost by removing
    this. `umbrella_sir` and `gl_deductible` also remain registered in
    `underwriting_consistency.RECONCILABLE_FIELDS`, so a genuine cross-document
    disagreement about either figure is still surfaced for review.

    GL/Auto underlying MINIMUM LIMIT checks are NOT in this function - they live
    in the sibling checks `_check_umbrella_gl_minimum_limits` and
    `_check_umbrella_auto_minimum_limits` (both registered in _RULE_FUNCTIONS
    directly after this one, so run_cross_form_validation still covers them).
    Kept separate because they're independently unit-tested and the GL check
    needed to ship ahead of the Auto one - do not re-merge them here without
    updating both call sites and their tests.

    Spec: "Verify GL/Auto limits meet umbrella minimums. If not → hard stop."
    (See _check_umbrella_gl_minimum_limits / _check_umbrella_auto_minimum_limits
    for that half of the spec - Client Q1 downgraded "hard stop" to a soft
    warning + score reduction, since carrier attachment requirements vary.)
    """
    issues: List[dict] = []

    if not _umbrella_in_scope(flags):
        return issues

    # 1. WC Employers Liability when umbrella attaches over WC
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
            # Client Q2: minimum preferred EL for umbrella attachment is $500K
            # (was $100K). Below $500K is a warning + score reduction, not a block.
            if el_val and el_val < 500_000:
                issues.append(_issue(
                    "soft_warning",
                    "umbrella_el_below_minimum",
                    (
                        f"Employers Liability limit (${el_val:,}) is below the "
                        "$500,000 minimum preferred by umbrella markets."
                    ),
                    ["ACORD_130", "ACORD_131"],
                ))

    # 2. Policy period alignment - underlying must match umbrella
    umb_eff = _fv(facts, "umbrella_effective_date")
    umb_exp = _fv(facts, "umbrella_expiration_date")
    gl_eff, gl_exp, _term_label = _package_period_on_umbrella_footing(facts)

    # Spec: misaligned effective/expiration dates = HARD STOP unless explained.
    # An ACORD 101 narrative is treated as the "explained" exception.
    _dates_explained = bool(_fv(facts, "acord101_remarks") or _fv(facts, "additional_remarks_text") or _fv(facts, "policy_period_explanation"))
    _date_sev = "soft_warning" if _dates_explained else "hard_stop"

    if umb_eff and gl_eff and _dates_differ(umb_eff, gl_eff):
        issues.append(_issue(
            _date_sev,
            "umbrella_gl_period_misaligned",
            (
                f"Umbrella effective date ({umb_eff}) does not match "
                f"{_term_label} effective date ({gl_eff}). Policy periods must "
                "align or be explained via ACORD 101."
            ),
            ["ACORD_125", "ACORD_131"],
        ))

    if umb_exp and gl_exp and _dates_differ(umb_exp, gl_exp):
        issues.append(_issue(
            _date_sev,
            "umbrella_gl_expiration_misaligned",
            (
                f"Umbrella expiration date ({umb_exp}) does not match "
                f"{_term_label} expiration date ({gl_exp}). Periods must align "
                "or be explained via ACORD 101."
            ),
            ["ACORD_125", "ACORD_131"],
        ))

    return issues


def _check_builders_risk_vs_property_deduplication(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 133 (Builders Risk) and ACORD 140 (Completed Property) must not
    cover the same insured values for the same location - duplication risk.

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

    # If breakdown is present, verify it totals to ACORD 125 payroll.
    # V1 H3 (2026-08-27): the merge has ALWAYS written this fact as a DICT
    # ({state: amount}) and this branch only ever read a LIST, so the check
    # below never ran on live data. Both shapes are read now; a free-text
    # answer (a string) has no total and is left alone.
    if isinstance(wc_by_state, dict):
        amounts = list(wc_by_state.values())
    elif isinstance(wc_by_state, list):
        amounts = wc_by_state
    else:
        amounts = []
    if amounts:
        state_total = sum(
            _to_float(
                entry.get("payroll") if isinstance(entry, dict) else entry
            ) or 0
            for entry in amounts
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
                        f"reports total payroll of ${tot_pay:,.0f} - "
                        f"{diff_pct * 100:.0f}% variance. Reconcile payroll totals."
                    ),
                    ["ACORD_125", "ACORD_130"],
                ))

    return issues


def _check_acord125_always_present(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    ACORD 125 is the anchor form - it must always be triggered for any
    commercial submission.

    Spec: "ACORD 125 is mandatory for every commercial submission."
    """
    issues: List[dict] = []

    # AN EMPTY FORM SET IS NOT A FINDING (2026-08-14). Every rule here is
    # gated on which forms are in scope, and this one reads that set to decide
    # whether the anchor form is missing. When the set is EMPTY - which is the
    # state before the producer reaches form selection, and on any re-run that
    # passes `selected_form_ids` while nothing is selected - "was ACORD 125
    # included?" has no answer, and answering "no" put a false warning in front
    # of the producer on every single run while the system was simultaneously
    # RECOMMENDING ACORD 125. Verified on the live session: recommendations
    # contained ACORD_125 and `selected_form_ids` was []. Silence here is
    # correct; the rule fires normally the moment a real form set exists.
    if not triggered_ids:
        return issues

    if "ACORD_125" not in triggered_ids:
        # NOTE: surfaced as a soft warning so the user can still proceed.
        # The decision-tree spec calls this a hard stop, but the product
        # intentionally lets brokers continue with a visible warning and
        # complete the submission with missing baseline data.
        issues.append(_issue(
            "soft_warning",
            "acord125_missing",
            (
                "ACORD 125 (Commercial Insurance Application) was not detected. "
                "It is normally required for every commercial submission - please "
                "review the missing baseline data before generating forms."
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

    if not _umbrella_in_scope(flags):
        return issues

    has_gl   = "ACORD_126" in triggered_ids or bool(_fv(facts, "gl_limits"))
    try:
        from services.coverage_evidence import auto_liability_stated as _auto_stated
        _auto_limit = _auto_stated(facts)          # CSL or split limits (live P5)
    except Exception:                                          # noqa: BLE001
        _auto_limit = bool(_fv(facts, "auto_liability_limit"))
    has_auto = "ACORD_127" in triggered_ids or _auto_limit

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
    If there is significant cash/financial handling exposure but no crime
    coverage, surface an advisory.

    Spec: "If company has high internal cash handling but no crime coverage
    → flag silent exposure."
    """
    issues: List[dict] = []

    if flags.get("has_crime") or _fv(facts, "crime_limit"):
        return issues

    # THE EVIDENCE IS CASH HANDLING, NOT HEADCOUNT (fixed 2026-08-17).
    # The trigger was `has_cash_exposure or num_emp > 10`. Ten employees is
    # below almost every commercial account, so this fired on practically every
    # submission - it appeared on all four probe runs, including a ROOFING
    # CONTRACTOR whose description mentions no cash, no retail and no money.
    # Worse, the message then asserted that "the business description indicates
    # potential employee dishonesty or cash-handling exposure", which was simply
    # untrue: nothing in the description said so, only the headcount did.
    #
    # The spec is explicit - "If company has HIGH INTERNAL CASH HANDLING but no
    # crime coverage" - and says nothing about headcount. The headcount clause
    # was never spec'd and produced only noise, so it is gone.
    #
    # Detection is WIDENED to compensate: the narrative fields are read too, not
    # just `operations_description`, so a genuine cash exposure described
    # anywhere in the submission is still caught. And the message now NAMES the
    # evidence, so a producer can check whether we read the document correctly.
    _CASH_TERMS = ("cash", "retail", "restaurant", "bar ", "tavern", "bank",
                   "financial", "jewelry", "jewellery", "money", "teller",
                   "payroll service", "check cashing", "atm", "casino",
                   "pawn", "currency", "armored", "vault")
    haystacks = [
        (_fv(facts, k) or "") for k in (
            "operations_description", "account_description",
            "certificate_description_of_operations", "contractor_type",
        )
    ]
    ops = " ".join(str(h) for h in haystacks).lower()
    matched = sorted({kw.strip() for kw in _CASH_TERMS if kw in ops})

    if matched:
        # Spec: silent crime exposure = SOFT WARNING (not advisory)
        issues.append(_issue(
            "soft_warning",
            "crime_silent_exposure",
            (
                "The business description mentions "
                f"{', '.join(repr(m) for m in matched[:3])}, which suggests "
                "cash-handling or employee-dishonesty exposure, but no Crime "
                "coverage is included. Consider adding crime coverage."
            ),
            [],
        ))

    return issues


def _check_cyber_silent_exposure(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If business handles PHI/PCI/digital assets but no Cyber coverage is
    included, surface an advisory.

    Spec: "If business stores PHI/PCI and no cyber limits listed → soft-warning."
    """
    issues: List[dict] = []

    if flags.get("has_cyber") or _fv(facts, "cyber_limit"):
        return issues

    ops = (_fv(facts, "operations_description") or "").lower()
    cyber_keywords = ["software", "saas", "cloud", "data", "pci", "phi",
                      "health", "medical", "ecommerce", "e-commerce",
                      "online", "tech", "platform", "digital"]
    has_cyber_exposure = any(kw in ops for kw in cyber_keywords)

    if has_cyber_exposure:
        # Spec: silent cyber exposure = SOFT WARNING (not advisory)
        issues.append(_issue(
            "soft_warning",
            "cyber_silent_exposure",
            (
                "Business operations indicate digital assets, customer data, or "
                "e-commerce exposure but no Cyber Liability coverage is included. "
                "Consider adding cyber coverage."
            ),
            [],
        ))

    return issues


def _check_auto_hired_nonowned_symbols(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    If Hired/Non-Owned auto exposure is detected, the liability covered-auto
    symbol must actually reach that exposure.

    Spec: "Symbols must align with exposure (e.g., hired/non-owned symbols
    present when exposure exists)."

    REWRITTEN 2026-08-07 - the previous version read `hired_auto_symbol` and
    `non_owned_symbol`, two fact keys that NOTHING in this codebase has ever
    written (not the extraction prompt, not FACT_REGISTRY, not any stamper).
    They were permanently empty, so this warning fired on every submission with
    hired/non-owned exposure regardless of what the policy said, and demanded
    Symbols 8 and 9 specifically. That demand is also wrong underwriting:
    Symbol 1 (any auto) is BROADER than 8 and 9 and already designates hired
    and non-owned autos for liability, which is the ordinary structure on a
    real dec page. Both defects are fixed by reasoning over the symbols the
    document actually carries (`auto_covered_symbols`) through
    `services.auto_symbols`.

    Silence is the default. The check only speaks when the symbols are known
    AND genuinely fail to reach the exposure. Unknown or unrecognised symbols
    (`covers()` returning None) leave it quiet - "blank over wrong".
    """
    from services import auto_symbols as sym

    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("auto_has_hired_nonowned"):
        return issues

    numbers = sym.liability_symbols(facts)
    if not numbers:
        return issues  # handled once, centrally, by _check_auto_symbols_captured

    gaps = [
        label for exposure, label in ((sym.HIRED, "hired"), (sym.NONOWNED, "non-owned"))
        if sym.covers(numbers, exposure) is False
    ]
    if gaps:
        issues.append(_issue(
            "soft_warning",
            "auto_hired_nonowned_symbols_missing",
            (
                f"Hired/Non-Owned auto exposure detected, but the liability "
                f"covered-auto symbol on this policy - {sym.describe_all(numbers)} - "
                f"does not designate {' or '.join(gaps)} autos. Confirm the "
                f"liability symbol, or add Symbol 8 (hired) / Symbol 9 (non-owned)."
            ),
            ["ACORD_127"],
        ))

    return issues


def _check_auto_symbols_captured(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    One advisory when an auto submission carries NO covered-auto symbol at all.

    This is a data-transfer gap, not a coverage decision: the carrier has
    already designated the covered autos on the declarations, and the number
    simply has not reached the ACORD. Worded that way, and resolvable inline by
    entering the symbols (see issue_registry.RESOLUTION_MAP), because it is.

    Deliberately ONE issue rather than one per coverage line - a submission with
    no symbols anywhere would otherwise emit the same complaint three times.
    """
    from services import auto_symbols as sym

    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("has_auto_coverage"):
        return issues
    if sym.all_numbers(facts):
        return issues

    issues.append(_issue(
        "soft_warning",
        "auto_symbols_not_captured",
        (
            "No covered-auto symbols were found for this commercial auto policy. "
            "The declarations designate covered autos by symbol (e.g. 1 = any auto, "
            "7 = specifically described autos, 8 = hired, 9 = non-owned); enter the "
            "symbols shown on the policy so they carry onto the ACORD forms."
        ),
        ["ACORD_127"],
    ))

    return issues


def _check_auto_owned_fleet_symbol_gap(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    The business schedules owned vehicles, but the liability symbol only reaches
    hired and/or non-owned autos - i.e. the fleet on the schedule is not covered
    for liability by the designation on the policy.

    This is the check the old phantom-key code was reaching for and could never
    perform, and it is the one that matters: a real, expensive coverage hole
    rather than a paperwork complaint. Symbol 8 and/or 9 alone against a
    scheduled fleet is the classic version of it.

    Silent unless the symbols are known AND recognised - `covers()` returns None
    on anything this table does not define, and None is never treated as a gap.
    """
    from services import auto_symbols as sym

    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues
    if not flags.get("has_auto_coverage"):
        return issues

    fleet = _fv(facts, "auto_vin_schedule") or []
    if not isinstance(fleet, list) or not fleet:
        return issues

    numbers = sym.liability_symbols(facts)
    if not numbers:
        return issues

    reaches_fleet = (
        sym.covers(numbers, sym.OWNED) is True
        or sym.covers(numbers, sym.SCHEDULED) is True
    )
    if sym.covers(numbers, sym.OWNED) is None:
        return issues  # unknown / unrecognised symbol - say nothing

    if not reaches_fleet:
        issues.append(_issue(
            "hard_stop",
            "auto_owned_fleet_not_covered_by_symbol",
            (
                f"{len(fleet)} scheduled vehicle(s) are listed, but the liability "
                f"covered-auto symbol - {sym.describe_all(numbers)} - does not "
                f"designate owned or specifically described autos. As written, the "
                f"scheduled fleet has no auto liability coverage. Verify the symbol "
                f"against the declarations."
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
    from services import auto_symbols as sym

    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues

    if not flags.get("has_auto_coverage"):
        return issues

    # ── Physical damage symbols vs requested coverage ────────────────────────
    # REWRITTEN 2026-08-07, same root cause as _check_auto_hired_nonowned_
    # symbols above: `auto_physical_damage_comp_symbol` / `..._coll_symbol` were
    # never written by anything, so this fired on every physical-damage
    # submission. A dec page showing "Comprehensive 07 / Collision 07" now
    # satisfies it. When the whole submission has no symbols at all,
    # _check_auto_symbols_captured says so once instead of this firing too.
    if flags.get("auto_has_physical_damage") and sym.all_numbers(facts):
        missing = [
            sym.COVERAGE_LABEL[cov].lower()
            for cov in (sym.COMPREHENSIVE, sym.COLLISION)
            if not sym.symbols_for(facts, cov, sym.PHYSICAL_DAMAGE)
        ]
        if missing:
            issues.append(_issue(
                "soft_warning",
                "auto_physical_damage_symbols_missing",
                (
                    f"Physical damage coverage is requested but no covered-auto symbol "
                    f"was found for: {', '.join(missing)}. The declarations normally "
                    f"show Symbol 7 (specifically described autos) for physical damage; "
                    f"enter the symbol shown on the policy."
                ),
                ["ACORD_127"],
            ))

    # Check liability coverage structure
    liability_struct = _fv(facts, "auto_liability_structure")
    if liability_struct in ("split", "combined"):
        if liability_struct == "split":
            # Must have all three components. THE REAL KEYS (H1 audit,
            # 2026-08-26): this read the unprefixed `bi_per_person` family,
            # which nothing writes - the extractor, registry and stamper use
            # `auto_bi_per_person` / `auto_bi_per_accident` /
            # `auto_pd_per_accident` - so every split-limit policy raised this
            # HARD STOP and none could ever clear it. Legacy names read last.
            bi_pp = _fv(facts, "auto_bi_per_person") or _fv(facts, "bi_per_person")
            bi_pa = _fv(facts, "auto_bi_per_accident") or _fv(facts, "bi_per_accident")
            pd_pa = _fv(facts, "auto_pd_per_accident") or _fv(facts, "pd_per_accident")
            if not all([bi_pp, bi_pa, pd_pa]):
                # Spec: split limits incomplete = HARD STOP
                issues.append(_issue(
                    "hard_stop",
                    "auto_split_limits_incomplete",
                    "Split liability structure selected but not all three limits (BI/person, BI/accident, PD/accident) defined",
                    ["ACORD_127"],
                ))

    # ── Drive Other Car ──────────────────────────────────────────────────────
    # REWRITTEN 2026-08-07. This read `drive_other_car_symbol`, the third fact
    # key in this function that nothing ever wrote - but it was also wrong at
    # the concept level: Drive Other Car is an ENDORSEMENT naming individual
    # insureds (CA 99 10), not a covered-auto symbol. ACORD 127 records it as
    # `Driver_Coverage_DriverOtherCarCode_<row>`, a per-driver Y/N box, and
    # there is no DOC symbol field on any of the 17 schemas. So the check now
    # asks the only question the form can answer: DOC was referenced - is it
    # attached to anybody?
    if flags.get("auto_has_drive_other_car"):
        drivers = _fv(facts, "auto_drivers") or []
        doc_named = any(
            str((d or {}).get("drive_other_car", "")).strip().lower()
            in {"y", "yes", "true", "1"}
            for d in drivers if isinstance(d, dict)
        )
        if not doc_named and not _fv(facts, "auto_drive_other_car"):
            issues.append(_issue(
                "soft_warning",
                "auto_doc_symbol_missing",
                (
                    "Drive Other Car coverage is referenced but no driver is marked "
                    "as covered by it. DOC is an endorsement naming individual "
                    "insureds - indicate which drivers it applies to on ACORD 127."
                ),
                ["ACORD_127"],
            ))

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

    # Spec: valuation method missing on property submissions = SOFT BLOCK
    # (prompt user to select RCV or ACV). Only flag when property coverage exists.
    if not val_method and (bldg_val or _to_float(_fv(facts, "property_bpp_value"))):
        issues.append(_issue(
            "soft_warning",
            "property_valuation_method_missing",
            (
                "Property valuation method is missing - select Replacement Cost "
                "Value (RCV) or Actual Cash Value (ACV) for each property limit."
            ),
            ["ACORD_140"],
        ))

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

    # V1 BETA EXIT (2026-08-28) - "WC-specific information no longer penalizes
    # non-WC submissions." This was the ONE cross-form rule reading a WC fact
    # with no WC gate. Measured before the fix: a GL-only roofing contractor
    # (`has_workers_comp` False, forms 125/126/186, 40% subcontracted, no
    # payroll) raised the HARD STOP below and its package fell 71 -> 60,
    # demanding "Workers Comp payroll" from a submission that carries no
    # Workers Comp line. The remediation asks for `wc_payroll`, so the producer
    # could only clear it by inventing a WC figure.
    #
    # Both branches reason about WC payroll, so the gate is on the whole rule,
    # in the same shape its five siblings already use (`ACORD_130 in
    # triggered_ids`, two of them also reading the flag). Slightly broader than
    # those - the flag alone is enough - so a genuine WC package that did not
    # select ACORD 130 keeps the check. Strictly NARROWER than the behaviour it
    # replaces, so it can only ever remove a false stop, never add one.
    #
    # NOTE the subcontractor exposure itself is a real GL concern; it is not
    # lost, it is simply not stated as a missing WC figure. A GL-side rule for
    # it would be a NEW validation rule (Principle 7 / the precedence note) and
    # belongs to Brent, not to this fix.
    # SCORES GO UP on GL-only contractor packages carrying ACORD 186 - D6.
    if "ACORD_130" not in triggered_ids and not flags.get("has_workers_comp"):
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
                "explanation - attach ACORD 101 to clarify."
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
                "provided. Confirm whether prior acts / nose coverage applies - "
                "required for umbrella attachment integrity."
            ),
            ["ACORD_126", "ACORD_131"] if "ACORD_131" in triggered_ids else ["ACORD_126"],
        ))

    return issues


def _package_period_on_umbrella_footing(facts: dict):
    """The package term that is CHRONOLOGICALLY COMPARABLE to the umbrella's
    extracted dates, plus a label for the message.

    THE DEFECT THIS FIXES (client run, 2026-08-16): the review screen showed
    three "Umbrella policy period alignment" issues -

        Umbrella effective date (07/15/25) does not match GL/policy
        effective date (07/15/2026)

    - and neither date is wrong. `umbrella_effective_date` is read off the
    umbrella's own DEC PAGE, so on a renewal it is the EXPIRING term; and
    `effective_date`, after `_route_renewal_dates`, is the DERIVED PROPOSED
    renewal term. The check was comparing the expiring umbrella against the
    proposed package - apples to oranges - and calling the difference a
    misalignment. It is the client's own chronology rule ("existing/expiring
    policy information, later policy changes, proposed renewal information,
    and application dates need to remain distinct") broken inside a validator.

    It was also UNRESOLVABLE, which is what the producer hit: the fix panel
    offers the two dates it compared, so correcting either one just moves the
    mismatch (07/15/2026 -> 09/15/2026 re-raised it as 09/15/2027), and no
    value the producer can type makes an expiring term equal a proposed one.

    On a routed renewal the comparable package term is the EXPIRING one, which
    `_route_renewal_dates` parks in prior_effective_date/prior_expiration_date.
    Returning those blanks when they are absent is deliberate: the caller
    already guards on both dates being present, so "no comparable term" means
    the check stands down rather than comparing across footings again.
    The sibling Auto/WC check needs none of this - those dates come off their
    own dec pages, so they share the umbrella's footing by construction.
    """
    if _fv(facts, "renewal_dates_routed"):
        return (_fv(facts, "prior_effective_date"),
                _fv(facts, "prior_expiration_date"),
                "expiring GL/policy")
    return (_fv(facts, "effective_date"),
            _fv(facts, "expiration_date"),
            "GL/policy")


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

    if not _umbrella_in_scope(flags):
        return issues

    umb_eff = _fv(facts, "umbrella_effective_date")
    umb_exp = _fv(facts, "umbrella_expiration_date")

    if not umb_eff and not umb_exp:
        return issues

    # Spec: underlying policy period misalignment = HARD STOP unless explained.
    _dates_explained = bool(_fv(facts, "acord101_remarks") or _fv(facts, "additional_remarks_text") or _fv(facts, "policy_period_explanation"))
    _date_sev = "soft_warning" if _dates_explained else "hard_stop"

    # Auto period alignment
    if "ACORD_127" in triggered_ids and flags.get("has_auto_coverage"):
        auto_eff = _fv(facts, "auto_effective_date")
        auto_exp = _fv(facts, "auto_expiration_date")

        if umb_eff and auto_eff and _dates_differ(umb_eff, auto_eff):
            issues.append(_issue(
                _date_sev,
                "umbrella_auto_period_misaligned",
                (
                    f"Umbrella effective date ({umb_eff}) does not match Auto "
                    f"policy effective date ({auto_eff}). Periods must align when "
                    "umbrella attaches to Auto (or be explained via ACORD 101)."
                ),
                ["ACORD_127", "ACORD_131"],
            ))

        if umb_exp and auto_exp and _dates_differ(umb_exp, auto_exp):
            issues.append(_issue(
                _date_sev,
                "umbrella_auto_expiration_misaligned",
                (
                    f"Umbrella expiration date ({umb_exp}) does not match Auto "
                    f"policy expiration date ({auto_exp}). Periods must align when "
                    "umbrella attaches to Auto (or be explained via ACORD 101)."
                ),
                ["ACORD_127", "ACORD_131"],
            ))

    # WC period alignment
    if "ACORD_130" in triggered_ids and flags.get("has_workers_comp"):
        wc_eff = _fv(facts, "wc_effective_date")
        wc_exp = _fv(facts, "wc_expiration_date")

        if umb_eff and wc_eff and _dates_differ(umb_eff, wc_eff):
            issues.append(_issue(
                _date_sev,
                "umbrella_wc_period_misaligned",
                (
                    f"Umbrella effective date ({umb_eff}) does not match Workers "
                    f"Compensation effective date ({wc_eff}). Periods must align when "
                    "umbrella attaches over WC (or be explained via ACORD 101)."
                ),
                ["ACORD_130", "ACORD_131"],
            ))

    return issues


def _check_umbrella_gl_minimum_limits(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    GL underlying limits are compared against umbrella attachment requirements -
    not just Auto. If GL limits are present but below the baseline, this is an
    attachment risk worth surfacing.

    Client Q1 (§6.5): underlying limits below the baseline must NOT fail the
    submission - they produce a WARNING + score reduction, never a hard stop,
    because carrier attachment requirements vary. (Missing ALL underlying
    coverage remains a hard stop - handled by _check_gl_missing_when_umbrella.)

    Gate: umbrella in scope (coverage flag OR umbrella form recommended), not
    ACORD 131 form selection, so the check runs whenever umbrella coverage is
    detected in the documents, regardless of whether the user explicitly
    selected ACORD 131. Shared with every other umbrella check and aligned with
    the SQS scoring layer.
    """
    issues: List[dict] = []

    if not _umbrella_in_scope(flags):
        return issues

    umb_limit = _to_int(_fv(facts, "umbrella_limit"))
    if not umb_limit:
        return issues

    gl_limit_raw = _fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits")
    gl_limit = _to_int(gl_limit_raw)

    # Client Q1 baseline: $1M GL each-occurrence underlying for umbrella attachment.
    _GL_MINIMUM = 1_000_000

    if gl_limit is not None and gl_limit < _GL_MINIMUM:
        issues.append(_issue(
            "soft_warning",
            "umbrella_gl_attachment_failure",
            (
                f"Underlying GL each-occurrence limit (${gl_limit:,}) may not meet "
                f"umbrella requirements (${_GL_MINIMUM:,}+ typically expected). "
                "Carrier attachment requirements vary - verify before binding."
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


def _check_umbrella_auto_minimum_limits(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Auto underlying limits are compared against umbrella attachment requirements,
    giving Auto parity with the GL minimum check at the cross-form layer.

    Client Q1 (§6.5): underlying limits below the baseline must NOT fail the
    submission - they produce a WARNING + score reduction, never a hard stop,
    because carrier attachment requirements vary. (Missing ALL underlying
    coverage remains a hard stop - handled by _check_gl_missing_when_umbrella.)

    Gate: umbrella in scope (coverage flag OR umbrella form recommended) —
    matches the gate used by every other umbrella check and the SQS scoring
    layer.
    """
    issues: List[dict] = []

    if not _umbrella_in_scope(flags):
        return issues

    umb_limit = _to_int(_fv(facts, "umbrella_limit"))
    if not umb_limit:
        return issues

    auto_limit = _to_int(_fv(facts, "auto_liability_limit"))

    # Client Q1 baseline: $1M Auto CSL underlying for umbrella attachment.
    _AUTO_MINIMUM = 1_000_000

    # V1 H1 (2026-08-26): a SPLIT-limit policy states its liability without a
    # CSL figure, so "the Auto combined single limit could not be determined"
    # is false on a fully-stated policy - and its Resolve button asked for the
    # CSL fact. The CSL comparison below is not attempted on split parts
    # (comparing a per-person figure to a combined baseline is not a rule
    # either document defines); the umbrella scorer surfaces it for producer
    # review instead. Principle 7: preserve, do not invent.
    if auto_limit is None:
        try:
            from services.coverage_evidence import auto_split_limits_stated
            if auto_split_limits_stated(facts):
                return issues
        except Exception:                                      # noqa: BLE001
            pass

    if auto_limit is not None and auto_limit < _AUTO_MINIMUM:
        issues.append(_issue(
            "soft_warning",
            "umbrella_auto_attachment_failure",
            (
                f"Underlying Auto combined single limit (${auto_limit:,}) may not "
                f"meet umbrella requirements (${_AUTO_MINIMUM:,}+ CSL typically "
                "expected). Carrier attachment requirements vary - verify before binding."
            ),
            ["ACORD_127", "ACORD_131"],
        ))
    elif "ACORD_127" in triggered_ids and not auto_limit:
        issues.append(_issue(
            "soft_warning",
            "umbrella_auto_limits_not_found",
            (
                "Umbrella is present and Auto is triggered but the Auto combined "
                "single limit could not be determined. Verify Auto limits meet "
                "umbrella attachment requirements."
            ),
            ["ACORD_127", "ACORD_131"],
        ))

    return issues


# _check_umbrella_sir_vs_auto_deductible was REMOVED (2026-08-07), not retired - it
# compared Umbrella SIR (a liability-side retention, only relevant when a claim isn't
# covered by the underlying liability policy) against Auto's comp/collision deductible
# (a physical-damage figure for repairing the insured's own vehicle). No underwriting
# rule relates those two amounts - a $0 SIR is the NORMAL, healthy structure, so this
# fired a false "coverage gap" warning on ordinary Auto+Umbrella submissions. The fact
# registry has no "auto liability deductible" field (primary Auto Liability is
# conventionally $0 deductible), so there was never a valid Auto-side figure to compare
# SIR against - do not reintroduce this check under any threshold.
#
# Decision_Tree.txt lines 226-231 ("Deductible/SIR Consistency ... across ACORD 126/127,
# ACORD 131, Dec page representations") is what this function was built to satisfy - read
# plainly, that line asks whether the SAME figure agrees across documents (e.g. the SIR
# the dec page states vs. what got extracted for ACORD 131), not whether SIR and a
# physical-damage deductible should track each other. THAT feature now exists properly:
# umbrella_sir / gl_deductible / auto_deductible_comp / auto_deductible_collision are
# registered in underwriting_consistency.RECONCILABLE_FIELDS, so a genuine cross-document
# disagreement on any of these is flagged for review with source attribution - the
# existing Data Consistency picker engine, not a bespoke comparison here.
#
# The attachment requirement this form actually needs IS already enforced, correctly, by
# `_check_umbrella_auto_minimum_limits` (Umbrella limit vs. underlying Auto LIABILITY
# limit - the two figures that legitimately have to stack). See CLAUDE.md Critical Issues
# & Roadmap, "Umbrella SIR vs Auto Deductible False-Positive Warning" (2026-08-07).


def _check_auto_optional_coverages(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Optional auto coverages advisory: if exposure exists but coverage is omitted,
    surface an advisory (no auto-add, no hard stop).

    Spec: "Medical Payments / PIP (state-dependent), Uninsured / Underinsured
    Motorist, Hired & Non-Owned Auto Liability, Drive Other Car - If optional
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

    # UM/UIM - required in many states; advisory if not found.
    #
    # `auto_um_limit` / `auto_uim_limit` ARE PHANTOM KEYS - grepped the whole
    # repo 2026-08-12: they appear ONLY in this line. Nothing writes them, so
    # the check was unsatisfiable and fired on every auto submission ever
    # processed. The canonical fact is `auto_um_uim_limit` (extraction prompt,
    # FACT_REGISTRY, issue_registry's own resolution for THIS issue id, and four
    # uses in sqs_service). Same defect class as the five phantom auto-symbol
    # keys fixed on 2026-08-07 - see CLAUDE.md.
    #
    # Confirmed against the client's real 50-page declarations: page 39 states
    # "Uninsured Motorists Coverage ... SELECTED $1,000,000 EACH ACCIDENT" and
    # "Rejection Of UM/UIM Coverage ... NOT ELECTED", extraction captured
    # `auto_um_uim_limit = "$ 1,000,000 EACH ACCIDENT"`, and the warning fired
    # anyway telling the producer to go and confirm it.
    # The legacy names are still read so a session predating the canonical fact
    # is not made worse.
    if not (_fv(facts, "auto_um_uim_limit") or _fv(facts, "auto_um_limit")
            or _fv(facts, "auto_uim_limit")):
        issues.append(_issue(
            "advisory",
            "auto_um_uim_not_specified",
            (
                "Uninsured/Underinsured Motorist (UM/UIM) coverage is not specified "
                "on the auto application. UM/UIM is required in many states - "
                "confirm with the insured whether coverage is desired or waived."
            ),
            ["ACORD_127"],
        ))

    # Med Pay / PIP - state-dependent
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

    # Drive Other Car - relevant when named insureds / officers drive non-fleet vehicles
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


# Mirrors pdf_service._OVERFLOW_CHAR_THRESHOLD (Figure 29 ACORD 101 overflow
# routing). That routing only ever fires if ACORD 101 is already in the
# generated packet, so this trigger is what actually gets it there when the
# operations narrative alone is too long for its own form field.
_OPS_OVERFLOW_CHAR_THRESHOLD = 300


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
    needed - the actual conflicts will already be in the issues list.

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
    # WORDS, not characters. `len(ops_desc) < 30` asked for an ACORD 101
    # narrative from "Tree trimming and removal" (25 chars - a complete trade
    # description) while staying silent on "We provide a wide variety of
    # services to our valued clients" (59 chars, which says nothing). Character
    # count is a proxy for "does this explain the operations" that is wrong in
    # BOTH directions. A named trade takes very few characters and several
    # words; a bare "Bakery" or "Roofing" is still one word and still needs the
    # narrative. Advisory only - this costs no score either way (verified).
    if gl_codes and isinstance(gl_codes, list) and gl_codes and len(ops_desc.split()) < 4:
        needs_101 = True
        reason_parts.append("GL class codes present but operations description is insufficient")

    # Operations narrative exceeds what its own ACORD field can hold
    if len(ops_desc) > _OPS_OVERFLOW_CHAR_THRESHOLD:
        needs_101 = True
        reason_parts.append(
            f"operations narrative is {len(ops_desc)} characters - exceeds field capacity, "
            "full text continues on ACORD 101"
        )

    # Payroll / revenue anomaly
    rev = _to_float(_fv(facts, "total_revenue"))
    pay = _to_float(_fv(facts, "total_payroll"))
    if rev and pay and rev > 0 and pay / rev > 0.85:
        needs_101 = True
        reason_parts.append(f"payroll is {pay/rev*100:.0f}% of revenue - unusually high")

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
            f"{pct_sub:.0f}% subcontracted work with WC payroll present - "
            "clarify employee vs subcontractor split"
        )

    # Claims history present with no explanation
    num_claims = _to_int(_fv(facts, "num_claims"))
    if num_claims and num_claims > 2:
        needs_101 = True
        reason_parts.append(f"{num_claims} prior claims - narrative explanation required")

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
        issues.append(_issue(
            "soft_warning",
            "property_aop_deductible_missing",
            "Property coverage present but AOP (All Other Perils) deductible not specified",
            ["ACORD_140", "ACORD_141"],
        ))

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

        issues.append(_issue(
            "soft_warning",
            "property_peril_deductible_incomplete",
            f"Some peril-specific deductibles defined but missing: {', '.join(missing_perils)}. "
            "Define all peril deductibles or remove partially-defined ones.",
            ["ACORD_140", "ACORD_141"],
        ))

    # Check deductible basis (if deductible present, basis should be clear)
    has_any_ded = aop_ded or has_wind or has_earth or has_flood
    if has_any_ded:
        # `deductible_basis` is the canonical fact (schema + FACT_REGISTRY).
        # `property_deductible_basis` was a phantom nothing wrote, so this
        # warning fired on every property policy with any deductible and its
        # resolution said "narrative only". Fixed 2026-08-26 (H1 audit).
        basis = (_fv(facts, "deductible_basis")
                 or _fv(facts, "deductible_application")
                 or _fv(facts, "property_deductible_basis"))
        if not basis:
            issues.append(_issue(
                "soft_warning",
                "property_deductible_basis_missing",
                "Property deductible defined but basis (flat dollar or percentage) not specified",
                ["ACORD_140", "ACORD_141"],
            ))

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
        issues.append(_issue(
            "soft_warning",
            "property_coinsurance_missing",
            "Property values present but coinsurance percentage or agreed value endorsement not specified. "
            "Define coinsurance % or confirm agreed value endorsement is in place.",
            ["ACORD_140", "ACORD_141"],
        ))
    elif coinsurance_pct:
        # Validate coinsurance percentage is reasonable (typically 80-100%)
        try:
            coinspct_val = float(re.sub(r"[^\d.]", "", str(coinsurance_pct)))
            if coinspct_val < 60 or coinspct_val > 100:
                issues.append(_issue(
                    "soft_warning",
                    "property_coinsurance_unreasonable",
                    f"Coinsurance percentage {coinspct_val}% appears outside normal range (80-100%). "
                    "Verify this is intentional.",
                    ["ACORD_140", "ACORD_141"],
                ))
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
            issues.append(_issue(
                "hard_stop",
                "peril_deductible_referenced_but_undefined",
                f"Peril-specific deductible referenced on document but amounts undefined: {', '.join(missing_perils)}. "
                "Define deductible amounts or remove references.",
                ["ACORD_140", "ACORD_141"],
            ))

    return issues


def _check_identity_address_distinction(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: "physical vs mailing address distinctions must be explicit".
    If only one of the two is captured but the dec page implies a separate
    physical location (multiple locations or property coverage), surface a
    soft warning.
    """
    issues: List[dict] = []

    mailing = _fv(facts, "mailing_address")
    physical = _fv(facts, "physical_address")
    locations = _fv(facts, "locations") or []
    loc_count = len(locations) if isinstance(locations, list) else 0

    # ── C3 3.12 (2026-08-25) ────────────────────────────────────────────────
    # *"Physical address is not universally required for Structural
    # Completeness. It becomes applicable when the exposure requires it.
    # Examples: Property location, Auto garaging, location-specific
    # operations/exposures."*
    #
    # AUTO GARAGING added: the client names it, so this is his rule, not a new
    # one. A garaged fleet has a physical location by definition, and the
    # garaging address is what rates it.
    has_property_or_multi = (
        flags.get("has_property_coverage")
        or loc_count > 1
        or flags.get("has_multiple_locations")
        or flags.get("has_auto_coverage")
    )

    # ...and the requirement is SATISFIED, not merely triggered, when the
    # location schedule already carries the address. 3.12 says the requirement
    # exists "when the exposure requires it" - if the exposure's own schedule
    # states where it is, that requirement is met, and warning anyway would be
    # the "universal Structural penalty" the same clause forbids. Positive
    # evidence only: a row must actually carry an address-shaped value, so an
    # empty or label-only schedule still leaves the question open.
    #
    # BOTH ROW SHAPES, because `locations` is normally a list of plain STRINGS.
    # `extraction_service` ends with
    #   facts["locations"] = [str(o["address"]) for o in consolidated ...]
    # so the dict form only survives on paths that skip consolidation. The first
    # version of this check tested `isinstance(row, dict)` alone - guessed from
    # the schedule-capture shape instead of read from the writer - and therefore
    # never fired on a real session: S6A warned on 2026-08-25 with two street
    # addresses sitting in its schedule. Read the writer, not the shape you
    # expect.
    def _row_address(row) -> str:
        if isinstance(row, str):
            return row.strip()
        if isinstance(row, dict):
            for key in ("address", "street", "location_address", "address1",
                        "line1", "full_address"):
                val = str(row.get(key) or "").strip()
                if val:
                    return val
        return ""

    # A street ADDRESS, not a label. Three tokens and a digit is what separates
    # "1450 Lantern Court" from the two shapes that must still warn:
    # "See attached" (no digit) and "Location 1" (only two tokens). A digit
    # alone is not enough - that was the first cut and "Location 1" walked
    # straight through it.
    def _looks_like_street_address(text: str) -> bool:
        return (len(text.split()) >= 3
                and re.search(r"\d", text) is not None
                and re.search(r"[A-Za-z]{3}", text) is not None)

    # V1 H1 6.3 (2026-08-26): a GARAGING address satisfies the requirement
    # exactly as a location row does - 3.12 names auto garaging as the reason
    # the requirement exists, so the garaging schedule stating where the fleet
    # sits IS the physical location. Without this, 6.3's "no garaging" -5 and
    # this warning fired together on one gap and stayed together after the
    # garaging address was supplied.
    garaging = _fv(facts, "auto_garaging_addresses") or []
    _address_rows = list(locations if isinstance(locations, list) else []) + \
        list(garaging if isinstance(garaging, list) else [])
    _schedule_has_address = any(
        _looks_like_street_address(_a)
        for _a in (_row_address(r) for r in _address_rows)
        if _a
    )

    if mailing and not physical and has_property_or_multi and not _schedule_has_address:
        issues.append(_issue(
            "soft_warning",
            "physical_vs_mailing_address_unclear",
            (
                "Mailing address is captured but physical operating address is "
                "missing. For property or multi-location submissions, the physical "
                "and mailing addresses must be explicitly distinguished."
            ),
            ["ACORD_125"],
        ))

    # Sanity: legal name and DBA captured identically - likely an extraction error
    legal = (_fv(facts, "applicant_name") or "").strip().lower()
    dba   = (_fv(facts, "dba_name") or "").strip().lower()
    if legal and dba and legal == dba:
        issues.append(_issue(
            "advisory",
            "legal_name_equals_dba",
            (
                "Legal named insured and DBA are identical - verify whether a "
                "separate DBA exists or remove the duplicate value."
            ),
            ["ACORD_125"],
        ))

    return issues


def _check_builders_risk_project_value(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: "IF project_value_missing THEN block (HARD STOP) or require ACORD 101
    with explanation."
    """
    issues: List[dict] = []

    # The flag alone is not sufficient corroboration - same principle as the
    # ACORD 133 form-trigger fix in form_service.py (client report 2026-08-07):
    # `has_builders_risk` with zero extracted project evidence and ACORD 133 not
    # even in the package must not manufacture a hard stop out of nothing. A
    # package where ACORD 133 IS selected still reaches this check normally -
    # form_service.py now only adds it when real evidence already exists.
    _br_evidence = bool(
        _fv(facts, "builders_risk_project_address")
        or _fv(facts, "builders_risk_project_cost")
        or _fv(facts, "builders_risk_completion_date")
    )
    if "ACORD_133" not in triggered_ids and not (flags.get("has_builders_risk") and _br_evidence):
        return issues

    project_cost = _to_float(_fv(facts, "builders_risk_project_cost"))
    if not project_cost:
        # If an ACORD 101 narrative is provided, treat as soft instead of hard.
        explained = bool(_fv(facts, "acord101_remarks") or _fv(facts, "additional_remarks_text"))
        issues.append(_issue(
            "soft_warning" if explained else "hard_stop",
            "builders_risk_project_value_missing",
            (
                "Builders Risk (ACORD 133) requires a project value/cost. "
                "Provide the total construction cost or attach an ACORD 101 "
                "narrative explaining the project scope."
            ),
            ["ACORD_133"],
        ))

    return issues


def _check_minimum_viable_cope_unit(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: Minimum Viable COPE missing on a property submission = HARD STOP.
    Emit a single rule-level hard stop listing exactly which fields are missing.
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues
    if "ACORD_140" not in triggered_ids:
        return issues

    has_bldg = bool(_fv(facts, "property_building_value"))
    has_bpp  = bool(_fv(facts, "property_bpp_value"))

    missing: List[str] = []
    if not (_fv(facts, "locations") or _fv(facts, "property_locations") or _fv(facts, "mailing_address")):
        missing.append("street address")
    if not _fv(facts, "occupancy_type"):
        missing.append("occupancy type")
    if not _fv(facts, "construction_type"):
        missing.append("construction type")
    # Spec 3.3 Minimum Viable COPE: "Building value OR required Business
    # Personal Property value" - EITHER satisfies it, exactly as the legacy
    # twin in `sqs_service.evaluate_stops` reads it. The previous two lines
    # read `has_building_coverage` / `has_bpp_coverage`, flags nothing writes,
    # with the fact itself as the default - so each collapsed to
    # `has_x and not has_x` and a property submission with NEITHER value could
    # never be told so here. Fixed 2026-08-26 (H1 audit).
    if not (has_bldg or has_bpp):
        missing.append("building or BPP value")

    if missing:
        issues.append(_issue(
            "hard_stop",
            "minimum_viable_cope_missing",
            (
                "Property submission missing Minimum Viable COPE: "
                + ", ".join(missing)
                + ". These fields are required to submit property to underwriting."
            ),
            ["ACORD_140"],
        ))

    return issues


def _check_carrier_grade_cope_quality(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: Carrier-Grade COPE quality fields (sprinkler, roof year, protection
    class, fire dept type, distance to hydrant) are not hard stops but
    influence SQS. Surface as soft warnings so they appear in the UI list.
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues
    if "ACORD_140" not in triggered_ids:
        return issues

    # Only emit when Minimum Viable COPE is satisfied - avoid noise on incomplete subs
    if not (_fv(facts, "occupancy_type") and _fv(facts, "construction_type")):
        return issues

    missing_quality: List[str] = []
    if not _fv(facts, "year_built"):
        missing_quality.append("year built")
    if not _fv(facts, "roof_year"):
        missing_quality.append("roof year")
    if _fv(facts, "sprinkler_system") in (None, ""):
        missing_quality.append("sprinkler system")
    if not _fv(facts, "fire_protection_class"):
        missing_quality.append("protection class")

    if len(missing_quality) >= 2:
        issues.append(_issue(
            "soft_warning",
            "carrier_grade_cope_incomplete",
            (
                "Carrier-Grade COPE detail incomplete - missing: "
                + ", ".join(missing_quality)
                + ". Submission can proceed but SQS will be capped."
            ),
            ["ACORD_140"],
        ))

    return issues


def _check_per_location_cope_completeness(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Beta Report Figure 27: a submission with multiple DISTINCT insured
    locations should have COPE detail (construction type, building/BPP value)
    captured per location, not just once at the submission level.

    `_check_minimum_viable_cope_unit` already hard-stops when the
    submission-wide COPE scalars are empty. That check is satisfied as soon
    as ONE location has values, so a second/third location with genuinely
    different COPE detail can stay blank without tripping it. This is a
    non-blocking companion check: it only fires when some locations in the
    canonical `property_locations` list have COPE detail and others don't -
    i.e. partial per-location data, not "no data at all" (already covered).
    """
    issues: List[dict] = []

    if not flags.get("has_property_coverage"):
        return issues

    locs = _fv(facts, "property_locations")
    if not isinstance(locs, list) or len(locs) < 2:
        return issues

    def _has_cope(loc: dict) -> bool:
        return bool(loc.get("construction_type") and (loc.get("building_value") or loc.get("bpp_value")))

    dict_locs = [loc for loc in locs if isinstance(loc, dict)]
    incomplete = [loc for loc in dict_locs if not _has_cope(loc)]

    if incomplete and len(incomplete) < len(dict_locs):
        issues.append(_issue(
            "soft_warning",
            "per_location_cope_incomplete",
            (
                f"{len(incomplete)} of {len(dict_locs)} insured locations are missing "
                "construction type or building/BPP value. Confirm COPE detail for every "
                "location before treating the property submission as complete."
            ),
            ["ACORD_140"],
        ))

    return issues


def _check_auto_agreed_value_schedule(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: "If Agreed Value or Stated Amount is selected, vehicle schedule
    confirmation is required."
    """
    issues: List[dict] = []

    if "ACORD_127" not in triggered_ids:
        return issues

    pd_val = str(_fv(facts, "auto_physical_damage_valuation") or "").lower()
    if not pd_val:
        return issues

    is_agreed_or_stated = (
        "agreed" in pd_val
        or "stated" in pd_val
        or "guaranteed" in pd_val
    )
    if not is_agreed_or_stated:
        return issues

    vehicle_schedule = _fv(facts, "auto_vin_schedule") or _fv(facts, "vehicle_schedule")
    has_schedule = bool(
        vehicle_schedule and isinstance(vehicle_schedule, list) and len(vehicle_schedule) > 0
    )

    if not has_schedule:
        issues.append(_issue(
            "soft_warning",
            "auto_agreed_value_requires_schedule",
            (
                f"Physical damage valuation is '{pd_val}' (Agreed Value / Stated "
                "Amount). A confirmed vehicle schedule (VIN, year, make/model, "
                "value) is required when this valuation method is selected."
            ),
            ["ACORD_127"],
        ))

    return issues


def _check_certificate_requested_but_missing(
    facts: dict, flags: dict, triggered_ids: set
) -> List[dict]:
    """
    Spec: "Missing certificate when requested = user-facing failure
    (but not an underwriting hard stop)." Emit as soft warning.
    """
    issues: List[dict] = []

    cert_requested = (
        flags.get("has_certificate_request")
        or bool(_fv(facts, "certificate_holder"))
        or bool(_fv(facts, "certificate_holder_address"))
    )
    if cert_requested and "ACORD_25" not in triggered_ids:
        issues.append(_issue(
            "soft_warning",
            "certificate_requested_but_acord25_missing",
            (
                "A certificate of liability was requested (certificate holder "
                "detected) but ACORD 25 is not in the selected forms. Add "
                "ACORD 25 to satisfy the request."
            ),
            ["ACORD_25"],
        ))

    mortgagee = bool(_fv(facts, "mortgagee_name")) or bool(_fv(facts, "loss_payee_name"))
    if (mortgagee or flags.get("has_property_coverage")) and (
        "ACORD_28" not in triggered_ids and (mortgagee or flags.get("has_property_evidence_request"))
    ):
        if mortgagee:
            issues.append(_issue(
                "soft_warning",
                "property_evidence_requested_but_acord28_missing",
                (
                    "A mortgagee/loss payee was detected but ACORD 28 (Evidence "
                    "of Commercial Property Insurance) is not in the selected "
                    "forms. Add ACORD 28 to satisfy the lender requirement."
                ),
                ["ACORD_28"],
            ))

    return issues


_RULE_FUNCTIONS = [
    _check_acord125_always_present,
    _check_identity_address_distinction,
    _check_builders_risk_project_value,
    _check_minimum_viable_cope_unit,
    _check_carrier_grade_cope_quality,
    _check_per_location_cope_completeness,
    _check_auto_agreed_value_schedule,
    _check_certificate_requested_but_missing,
    _check_wc_payroll_reconciliation,
    _check_wc_multi_state_payroll_breakdown,
    _check_wc_gl_class_code_alignment,
    _check_gl_class_code_vs_operations,
    _check_location_address_reconciliation,
    _check_umbrella_attachment_stack,
    _check_umbrella_gl_minimum_limits,
    _check_umbrella_auto_minimum_limits,
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
    _check_auto_symbols_captured,              # NEW (2026-08-07): symbols absent entirely
    _check_auto_owned_fleet_symbol_gap,        # NEW (2026-08-07): real coverage hole
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
    List of issue dicts - each has keys: type, code, message, forms.
    """
    all_issues: List[dict] = []

    for rule_fn in _RULE_FUNCTIONS:
        try:
            result = rule_fn(facts, flags, triggered_ids)
            if result:
                all_issues.extend(result)
        except Exception as exc:
            logger.warning(
                "cross_form_validator: rule %s raised %s - skipping",
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
        forms = issue.get("forms") or []
        # Attribution bracket (client feedback: "which form it might affect and
        # how to fix it"). ``forms`` is already computed by every rule in this
        # module - it was being discarded here on the way to a plain string.
        # No per-document source is added: these rules read the already-merged
        # facts/flags across the whole package, not one specific document, so
        # naming a document would be a guess, not a fact. The remediation is
        # intentionally generic (these are coverage/limit rules, not identity
        # conflicts with a dedicated picker like check_doc_consistency's).
        if forms:
            pretty = ", ".join(f.replace("ACORD_", "ACORD ") for f in forms)
            msg = f"{msg} (Affects: {pretty}. Fix: Review the coverage/limit details for the affected form(s).)"
        if itype == "hard_stop":
            hard_stops.append(msg)
        elif itype == "soft_warning":
            soft_stops.append(msg)
        else:
            advisories.append(issue)

    return hard_stops, soft_stops, advisories
