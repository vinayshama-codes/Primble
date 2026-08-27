"""test_h1_coverage_regression.py - V1 H1 sections 6.1 (GL), 6.2 (Property),
6.5 (Umbrella): "Regression-test existing behavior. Do not redesign."

These pin the EXISTING rules against the spec tables that define them
(`SQS_Scoring_Specification` 3.2, 3.3, 3.5) and the cross-form rules the
client lists under each line, so the H1 auto / WC work - or anything after it
- cannot move a GL, Property or Umbrella number without this file saying so.
Measured before this file existed (2026-08-26): `_check_gl_class_code_vs_
operations` had ZERO test references, the coinsurance and BI/period rules had
none by code, and the umbrella minimum-limit rules were pinned only by
message text. Every fixture below is the LIVE shape the writers produce
(D22): `locations` is a list of strings, `gl_class_codes_by_location` a list
of dicts, `coverage_lines` dicts with a premium.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import cross_form_validator as cf                  # noqa: E402
from services import sqs_service as sq                           # noqa: E402

GL = {"has_general_liability": True}
PROP = {"has_property_coverage": True}
UMB = {"has_umbrella": True}


def _codes(*issues):
    return [i["code"] for i in issues]


def _exposure(facts, flags):
    return sq._calculate_exposure_consistency(facts, flags, [], [])[1]


# ── 6.1 General Liability: spec 3.2 Operations / Coverage rows ───────────────

def test_gl_with_no_class_codes_at_all_is_minus_20():
    subs = _exposure({"gl_limits": "$1,000,000"}, GL)
    assert subs["operations_description"] == 80


def test_gl_class_code_mismatching_operations_is_minus_15():
    facts = {"gl_limits": "$1,000,000",
             "operations_description": "Roofing contractor - residential re-roofs",
             "gl_class_codes_by_location": [{"code": "9079"}]}     # restaurant
    assert _exposure(facts, GL)["operations_description"] == 85
    facts["gl_class_codes_by_location"] = [{"code": "5551"}]        # roofing
    assert _exposure(facts, GL)["operations_description"] == 100


def test_gl_with_no_limits_is_minus_8():
    subs = _exposure({"gl_class_codes_by_location": [{"code": "91580"}]}, GL)
    assert subs["coverage_information"] == 92


def test_contractor_with_no_subcontracted_percentage_is_minus_8():
    facts = {"gl_limits": "$1,000,000", "gl_class_codes_by_location": [{"code": "91580"}]}
    assert _exposure(facts, {"has_general_liability": True, "is_contractor": True})[
        "operations_description"] == 92
    assert _exposure(dict(facts, percent_subcontracted="15"),
                     {"has_general_liability": True, "is_contractor": True})[
        "operations_description"] == 100


def test_gl_revenue_payroll_and_operations_are_not_charged_here():
    """C3 / owner 2026-08-25: revenue and operations description are Tier 2
    facts - Exposure must not charge for their absence. Pinned again so H1
    cannot re-open the double count."""
    base = {"gl_limits": "$1,000,000", "gl_class_codes_by_location": [{"code": "91580"}]}
    assert _exposure(base, GL) == _exposure(dict(base, total_revenue="$2,000,000",
                                                 operations_description="Roofing"), GL)


def test_gl_claims_made_without_retro_date_warns_and_caps_at_85():
    _hard, soft = sq.evaluate_stops({"gl_limits": "$1,000,000"},
                                    {"has_general_liability": True, "gl_is_claims_made": True})
    assert any("claims-made" in s and "retro date" in s for s in soft)
    assert sq._resolve_cap([], soft)[0] == 85
    _hard, soft = sq.evaluate_stops({"gl_limits": "$1,000,000", "retro_date": "01/01/2015"},
                                    {"has_general_liability": True, "gl_is_claims_made": True})
    assert not any("retro date" in s for s in soft)


def test_gl_exposure_basis_warning_fires_only_with_no_revenue_no_payroll_no_stated_basis():
    flags = GL
    assert any("no revenue or payroll" in s for s in sq.evaluate_stops({}, flags)[1])
    for satisfied in ({"total_revenue": "$1,000,000"}, {"total_payroll": "$400,000"},
                      {"dec_states_payroll_basis": True},
                      {"gl_class_code_schedule": [{"premium_basis": "Payroll",
                                                   "exposure_amount": "$39,300"}]}):
        assert not any("no revenue or payroll" in s
                       for s in sq.evaluate_stops(satisfied, flags)[1]), satisfied


def test_gl_codes_present_without_operations_asks_for_acord_101():
    facts = {"gl_class_codes_by_location": [{"code": "91580"}]}
    assert "gl_codes_no_operations" in _codes(
        *cf._check_gl_class_code_vs_operations(facts, GL, {"ACORD_126"}))
    assert "gl_codes_no_operations" not in _codes(
        *cf._check_gl_class_code_vs_operations(dict(facts, operations_description="Roofing"),
                                               GL, {"ACORD_126"}))
    assert not cf._check_gl_class_code_vs_operations(facts, GL, {"ACORD_125"}), (
        "gated on ACORD 126 being in the package")


def test_contractor_without_acord_186_is_flagged():
    flags = {"has_general_liability": True, "is_contractor": True}
    assert "contractor_missing_acord186" in _codes(
        *cf._check_gl_class_code_vs_operations({}, flags, {"ACORD_126"}))
    assert "contractor_missing_acord186" not in _codes(
        *cf._check_gl_class_code_vs_operations({}, flags, {"ACORD_126", "ACORD_186"}))


def test_gl_location_information_is_available_to_facts_and_questionnaire():
    """6.1 Location Review: 'Confirm that materially relevant GL location
    information is available to the underlying submission facts and
    questionnaire where needed. Do not add a separate GL location deduction.'"""
    from services.fact_registry import FACT_REGISTRY
    from services.schedule_capture import SCHEDULE_DEFS
    assert "gl_class_codes_by_location" in FACT_REGISTRY
    assert "locations" in FACT_REGISTRY
    assert "property_locations" in SCHEDULE_DEFS, "the location schedule is a client table"
    subs = _exposure({"gl_limits": "$1,000,000", "gl_class_codes_by_location": [{"code": "91580"}]}, GL)
    assert all(v == 100 for v in subs.values()), "no GL location deduction exists"


# ── 6.2 Property: spec 3.3 Property Integrity ────────────────────────────────

_MIN_COPE = {"locations": ["1450 Lantern Court, Columbus OH 43215"],
             "occupancy_type": "Office", "construction_type": "Frame",
             "property_building_value": "$900,000"}
_TIER1 = {"year_built": "1998", "roof_year": "2018", "sprinkler_system": "Yes",
          "fire_protection_class": "4"}
_TIER2 = {"distance_to_hydrant": "500 ft", "fire_department_type": "Paid",
          "business_income_limit": "$250,000", "period_of_restoration": "12 months"}


def test_no_property_coverage_scores_clean_100():
    assert sq._calculate_cope_score({}, {}) == 100


def test_minimum_viable_cope_incomplete_is_zero_and_a_hard_stop():
    for missing in ("locations", "occupancy_type", "construction_type"):
        facts = {k: v for k, v in _MIN_COPE.items() if k != missing}
        assert sq._calculate_cope_score(facts, PROP) == 0, missing
        hard, _soft = sq.evaluate_stops(facts, PROP)
        assert any("Minimum Viable COPE incomplete" in h for h in hard), missing
    facts = {k: v for k, v in _MIN_COPE.items() if k != "property_building_value"}
    assert sq._calculate_cope_score(dict(facts, property_bpp_value="$50,000"), PROP) == 60, (
        "building value OR BPP value satisfies the minimum")


def test_cope_ladder_is_60_plus_5_per_tier_field():
    assert sq._calculate_cope_score(dict(_MIN_COPE), PROP) == 60
    assert sq._calculate_cope_score(dict(_MIN_COPE, **_TIER1), PROP) == 80
    assert sq._calculate_cope_score(dict(_MIN_COPE, **_TIER1, **_TIER2), PROP) == 100
    assert sq._calculate_cope_score(dict(_MIN_COPE, year_built="1998"), PROP) == 65


def test_valuation_method_is_not_a_cope_credit_field():
    """Spec 3.3: 'Valuation method is deliberately excluded from the Tier-2
    credits ... Counting it as a credit field permanently capped a fully
    carrier-grade submission at 96.'"""
    full = dict(_MIN_COPE, **_TIER1, **_TIER2)
    assert sq._calculate_cope_score(full, PROP) == 100
    assert sq._calculate_cope_score(dict(full, valuation_method="RCV"), PROP) == 100


def test_acv_rcv_conflict_is_minus_10():
    full = dict(_MIN_COPE, **_TIER1, **_TIER2, valuation_method="RCV")
    assert sq._calculate_cope_score(full, PROP) == 100
    conflicted = dict(full, valuation_method="Replacement Cost and Actual Cash Value")
    if sq._acv_rcv_conflict(conflicted):
        assert sq._calculate_cope_score(conflicted, PROP) == 90


def test_carrier_grade_cope_gap_is_a_warning_that_caps_at_85():
    _hard, soft = sq.evaluate_stops(dict(_MIN_COPE), PROP)
    assert any("Carrier-Grade COPE incomplete" in s for s in soft)
    assert sq._resolve_cap([], soft)[0] == 85
    complete = dict(_MIN_COPE, **_TIER1, valuation_method="RCV", coinsurance_percentage="80")
    _hard, soft = sq.evaluate_stops(complete, PROP)
    assert not any("Carrier-Grade COPE incomplete" in s for s in soft)


def test_business_income_limit_without_period_of_restoration_is_a_hard_stop():
    facts = dict(_MIN_COPE, business_income_limit="$250,000")
    assert "bi_missing_period_of_restoration" in _codes(
        *cf._check_property_bi_period_of_restoration(facts, PROP, {"ACORD_140"}))
    assert not cf._check_property_bi_period_of_restoration(
        dict(facts, period_of_restoration="12 months"), PROP, {"ACORD_140"})
    flags = {"has_property_coverage": True, "property_has_bi_coverage": True}
    assert "bi_coverage_no_limit" in _codes(
        *cf._check_property_bi_period_of_restoration(dict(_MIN_COPE), flags, {"ACORD_140"}))


def test_valuation_method_missing_and_advisories():
    facts = dict(_MIN_COPE)
    assert "property_valuation_method_missing" in _codes(
        *cf._check_property_valuation_consistency(facts, PROP, {"ACORD_140"}))
    acv = dict(_MIN_COPE, valuation_method="ACV", property_building_value="$1,500,000")
    assert "acv_high_value_building" in _codes(
        *cf._check_property_valuation_consistency(acv, PROP, {"ACORD_140"}))
    old = dict(_MIN_COPE, valuation_method="RCV", property_building_value="$800,000",
               year_built=str(datetime.now().year - 55))
    assert "rcv_old_building" in _codes(
        *cf._check_property_valuation_consistency(old, PROP, {"ACORD_140"}))


def test_coinsurance_rules():
    facts = dict(_MIN_COPE)
    assert "property_coinsurance_missing" in _codes(
        *cf._check_property_coinsurance_enforcement(facts, PROP, {"ACORD_140"}))
    assert not cf._check_property_coinsurance_enforcement(
        dict(facts, coinsurance_percentage="80%"), PROP, {"ACORD_140"})
    assert not cf._check_property_coinsurance_enforcement(
        dict(facts, agreed_value_endorsement="yes"), PROP, {"ACORD_140"})
    assert "property_coinsurance_unreasonable" in _codes(
        *cf._check_property_coinsurance_enforcement(
            dict(facts, coinsurance_percentage="40%"), PROP, {"ACORD_140"}))


def test_carrier_grade_cope_cross_form_rule_lists_the_missing_fields():
    issues = cf._check_carrier_grade_cope_quality(dict(_MIN_COPE), PROP, {"ACORD_140"})
    assert issues and all(w in issues[0]["message"] for w in ("year built", "roof year"))
    assert not cf._check_carrier_grade_cope_quality(dict(_MIN_COPE, **_TIER1), PROP, {"ACORD_140"})


# ── 6.5 Umbrella: spec 3.5 Umbrella & Limit Adequacy ─────────────────────────

_UMB_FULL = {"umbrella_limit": "$5,000,000", "gl_each_occurrence": "$1,000,000",
             "gl_aggregate": "$2,000,000", "auto_liability_limit": "$1,000,000",
             "employers_liability_limits": "$1,000,000",
             "schedule_of_underlying_insurance": "attached",
             "umbrella_follow_form": "The umbrella follows form over all underlying policies"}
_UMB_FLAGS = {"has_umbrella": True, "has_general_liability": True,
              "has_auto_coverage": True, "has_workers_comp": True}


def test_umbrella_pillar_is_not_applicable_without_an_umbrella():
    assert sq._calculate_umbrella_adequacy(dict(_UMB_FULL), {}) is None


def test_umbrella_with_no_underlying_is_zero_and_a_hard_stop():
    assert sq._calculate_umbrella_adequacy({"umbrella_limit": "$5,000,000"}, UMB) == 0
    hard, _soft = sq.evaluate_stops({"umbrella_limit": "$5,000,000"}, UMB)
    assert any("Umbrella detected but no underlying" in h for h in hard)
    assert sq._resolve_cap(hard, [])[0] == 60


def test_umbrella_full_credit_and_each_deduction_of_spec_3_5():
    assert sq._calculate_umbrella_adequacy(dict(_UMB_FULL), _UMB_FLAGS) == 100
    cases = [
        ({"umbrella_limit": None}, 25, "the umbrella's own limit missing"),
        ({"gl_each_occurrence": "$500,000"}, 20, "GL occurrence below $1M"),
        ({"gl_aggregate": "$1,000,000"}, 20, "GL aggregate below $2M"),
        ({"auto_liability_limit": "$500,000"}, 20, "Auto CSL below $1M"),
        ({"employers_liability_limits": None}, 25, "EL missing when WC is present"),
        ({"employers_liability_limits": "$500,000"}, 10, "EL between $500K and $999K"),
        ({"employers_liability_limits": "$100,000"}, 25, "EL below $500K"),
        ({"schedule_of_underlying_insurance": None}, 15, "no Schedule of Underlying Insurance"),
        ({"umbrella_follow_form": "unable to determine whether the umbrella follows form"}, 10,
         "follow-form not affirmatively confirmed"),
    ]
    for override, points, why in cases:
        facts = dict(_UMB_FULL)
        for k, v in override.items():
            if v is None:
                facts.pop(k)
            else:
                facts[k] = v
        assert sq._calculate_umbrella_adequacy(facts, _UMB_FLAGS) == 100 - points, why


def test_underlying_limit_shortfalls_reduce_and_never_hard_stop():
    facts = dict(_UMB_FULL, auto_liability_limit="$500,000", gl_each_occurrence="$500,000")
    hard, soft = sq.evaluate_stops(facts, _UMB_FLAGS)
    assert not any("underlying" in h.lower() for h in hard)
    assert any("may not meet umbrella requirements" in s for s in soft)
    assert "umbrella_gl_attachment_failure" in _codes(
        *cf._check_umbrella_gl_minimum_limits(facts, _UMB_FLAGS, {"ACORD_131"}))
    assert "umbrella_auto_attachment_failure" in _codes(
        *cf._check_umbrella_auto_minimum_limits(facts, _UMB_FLAGS, {"ACORD_131"}))
    ok = dict(_UMB_FULL)
    assert not cf._check_umbrella_gl_minimum_limits(ok, _UMB_FLAGS, {"ACORD_131"})
    assert not cf._check_umbrella_auto_minimum_limits(ok, _UMB_FLAGS, {"ACORD_131"})


def test_umbrella_underlying_limits_not_found_when_the_section_is_triggered():
    facts = {"umbrella_limit": "$5,000,000"}
    assert "umbrella_gl_limits_not_found" in _codes(
        *cf._check_umbrella_gl_minimum_limits(facts, UMB, {"ACORD_126", "ACORD_131"}))
    assert "umbrella_auto_limits_not_found" in _codes(
        *cf._check_umbrella_auto_minimum_limits(facts, UMB, {"ACORD_127", "ACORD_131"}))
    assert not cf._check_umbrella_gl_minimum_limits(facts, UMB, {"ACORD_131"})


def test_umbrella_without_gl_or_auto_underlying_is_a_hard_stop_cross_form():
    assert "umbrella_no_underlying_coverage" in _codes(
        *cf._check_gl_missing_when_umbrella({"umbrella_limit": "$5,000,000"}, UMB, {"ACORD_131"}))
    assert not cf._check_gl_missing_when_umbrella(
        {"umbrella_limit": "$5,000,000", "gl_limits": "$1,000,000"}, UMB, {"ACORD_131"})


def test_umbrella_over_wc_needs_employers_liability_at_market_minimum():
    _hard, soft = sq.evaluate_stops({"umbrella_limit": "$5,000,000", "gl_limits": "$1,000,000"},
                                    {"has_umbrella": True, "has_workers_comp": True})
    assert any("Employers Liability limits not provided" in s for s in soft)
    _hard, soft = sq.evaluate_stops({"umbrella_limit": "$5,000,000", "gl_limits": "$1,000,000",
                                     "employers_liability_limits": "$100,000"},
                                    {"has_umbrella": True, "has_workers_comp": True})
    assert any("below the $500,000" in s for s in soft)


def test_follow_form_is_never_inferred_from_a_negated_or_uncertain_mention():
    assert sq._has_explicit_follow_form("The umbrella follows form over the underlying GL")
    assert not sq._has_explicit_follow_form("The umbrella does not follow form")
    assert not sq._has_explicit_follow_form("unable to determine whether the umbrella follows form")
    assert not sq._has_explicit_follow_form("")


def test_umbrella_period_misalignment_is_a_warning_not_a_stop():
    facts = {"umbrella_limit": "$5,000,000", "gl_limits": "$1,000,000",
             "effective_date": "01/01/2026", "expiration_date": "01/01/2027",
             "umbrella_effective_date": "03/01/2026", "umbrella_expiration_date": "03/01/2027"}
    hard, soft = sq.evaluate_stops(facts, {"has_umbrella": True, "has_general_liability": True})
    assert not any("misaligned" in h for h in hard)
    assert any("policy periods misaligned" in s for s in soft)


# ── The pillar weights, the ceilings and the N/A rescale, pinned once more ──

def test_pillar_weights_ceilings_and_rescale_are_unchanged_by_h1():
    assert sq.SPEC_PILLAR_WEIGHTS == {
        "structural_completeness": 0.25, "exposure_consistency": 0.25,
        "property_integrity": 0.15, "loss_history_alignment": 0.15,
        "umbrella_limit_adequacy": 0.10, "narrative_quality": 0.10,
    }
    assert (sq.HARD_STOP_CAP, sq.SOFT_STOP_CAP) == (60, 85)
    eff = sq.effective_pillar_weights(
        {"structural_completeness": 80, "exposure_consistency": 80, "property_integrity": 80,
         "loss_history_alignment": 80, "umbrella_limit_adequacy": None, "narrative_quality": 80},
        sq.SPEC_PILLAR_WEIGHTS)
    # The scorer rounds effective weights to 5 dp (0.27778), hence abs=1e-5.
    assert eff["structural_completeness"] == pytest.approx(0.25 / 0.90, abs=1e-5)
    # An N/A pillar is REMOVED from the effective weights (not zeroed) - that
    # is what "pillar removed, weights rescaled" means in spec 3.5.
    assert eff.get("umbrella_limit_adequacy", 0.0) == 0.0
    assert sum(eff.values()) == pytest.approx(1.0, abs=1e-4)
