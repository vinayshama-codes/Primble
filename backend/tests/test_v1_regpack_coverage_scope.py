"""V1 REQUIRED REGRESSION TEST PACK - Coverage terminology & scope
(client tests 2, 11, 12).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. Recurring regression
scenarios: re-run on every change to line-of-business canonicalisation, the
declared-absent path, the questionnaire's applicability filter, or the auto
exposure kind.

  Test 2  - Orbin Coverage Terminology
  Test 11 - Property-Only Package
  Test 12 - HNOA-Only Auto

Every test drives the REAL line-of-business leaf (`services/lob_canon.py`), the
REAL fact-state axis (`services/fact_state.py`), the REAL one door for auto
exposure (`services/coverage_evidence.py`) and the REAL questionnaire filter
(`arq_service._drop_not_applicable_questions`) - never a copy of the rule.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import arq_service                              # noqa: E402
from services import coverage_evidence as ce                  # noqa: E402
from services import fact_state as fs                         # noqa: E402
from services import lob_canon as lc                          # noqa: E402
from services import question_classifier as qc                # noqa: E402
from services import question_eligibility as qe               # noqa: E402
from services import sqs_service as sq                        # noqa: E402


# =============================================================================
# TEST 2 - Orbin Coverage Terminology
# =============================================================================

@pytest.mark.parametrize("variants,family", [
    (["General Liability", "Commercial General Liability", "CGL",
      "Liability - Premises/Operations", "COMMERCIAL GENERAL LIABILITY COVERAGE PART"],
     lc.GENERAL_LIAB),
    (["Business Auto", "Commercial Auto", "Automobile Liability",
      "BUSINESS AUTO COVERAGE PART", "Auto Liability"],
     lc.AUTO),
    (["Umbrella", "Commercial Liability Umbrella", "Excess Liability",
      "COMMERCIAL LIABILITY UMBRELLA COVERAGE PART"],
     lc.UMBRELLA),
])
def test_r02_equivalent_terms_normalize(variants, family):
    """Equivalent terms normalize to ONE canonical line."""
    resolved = {lc.canon_line(v) for v in variants}
    assert resolved == {family}, resolved


def test_r02_distinct_lines_stay_distinct():
    """Normalizing must not collapse genuinely different coverage parts.

    The control that makes the test above mean something: a canon_line that
    returned one family for everything would pass it.
    """
    families = {lc.canon_line(t) for t in
                ("General Liability", "Business Auto", "Commercial Liability Umbrella",
                 "Workers Compensation", "Commercial Property", "Inland Marine")}
    assert len(families) == 6
    assert None not in families


@pytest.mark.parametrize("sub", [
    "Inland Marine",
    "Contractors Equipment",
    "Installation Floater",
])
def test_r02_inland_marine_subcoverages_scope_to_their_parent(sub):
    """Sub-coverages scope correctly - they do NOT become a new top-level LOB."""
    assert lc.canon_line(sub) == lc.INLAND_MARINE


def test_r02_unrecognised_subcoverage_invents_no_line():
    """An unrecognised sub-coverage creates no new top-level LOB - it goes to
    producer review instead (V1 principle 7)."""
    assert lc.canon_line("Leased/Rented Equipment") is None
    unmapped = lc.unmapped_material_lines([
        {"line": "Commercial General Liability", "premium": "5000"},
        {"line": "Leased/Rented Equipment", "premium": "150"},
    ])
    assert "Leased/Rented Equipment" in unmapped
    # A line we DO understand is never sent to producer review.
    assert not any("General Liability" in u for u in unmapped)


ORBIN_COVERAGE_LINES = [
    {"line": "Commercial General Liability", "premium": "5,000"},
    {"line": "Business Auto", "premium": "2,991"},
    {"line": "Commercial Liability Umbrella", "premium": "1,200"},
    {"line": "Contractors Equipment", "premium": "450"},
    {"line": "Employment Practices Liability", "premium": "No Coverage"},
    {"line": "Cyber Liability", "premium": "NOT COVERED"},
]


def test_r02_no_coverage_sections_remain_inactive():
    """Policy sections marked "No Coverage" stay INACTIVE."""
    denied = lc.denied_families(ORBIN_COVERAGE_LINES)
    assert lc.EPLI in denied
    assert lc.CYBER in denied

    # The granted lines are NOT denied - a denial reader that returned
    # everything would pass the two assertions above.
    for granted in (lc.GENERAL_LIAB, lc.AUTO, lc.UMBRELLA, lc.INLAND_MARINE):
        assert granted not in denied

    # And the inactive sections become Not Applicable facts, never gaps.
    facts = {"coverage_lines": ORBIN_COVERAGE_LINES}
    assert fs.denied_lines(facts) >= {lc.EPLI, lc.CYBER}


def test_r02_a_denial_is_withdrawn_when_another_entry_grants_it():
    """Two sources disagreeing is a conflict for the producer, not a quiet
    "not applicable" - the client's 1.7 acceptance criterion."""
    conflicting = [
        {"line": "Business Auto", "premium": "No Coverage"},
        {"line": "Commercial Auto", "premium": "2,991"},
    ]
    assert lc.AUTO not in lc.denied_families(conflicting)


def test_r02_no_false_lob_warning():
    """No false LOB warning on a package whose terminology merely varies."""
    facts = {"coverage_lines": ORBIN_COVERAGE_LINES}
    flags = {"has_general_liability": True, "has_auto_coverage": True,
             "has_umbrella": True}
    hard, soft = sq.evaluate_stops(facts, flags)
    offenders = [m for m in list(hard) + list(soft)
                 if "coverage line" in m.lower() or "unrecognis" in m.lower()
                 or "unrecognized" in m.lower()]
    assert not offenders, offenders


# =============================================================================
# TEST 11 - Property-Only Package
# =============================================================================

PROPERTY_ONLY = {
    "coverage_lines": [
        {"line": "Commercial Property", "premium": "8,500"},
        {"line": "Business Auto", "premium": "No Coverage"},
        {"line": "Workers Compensation", "premium": "No Coverage"},
    ],
    "building_value": "1,250,000",
}
PROPERTY_ONLY_FLAGS = {"has_property_coverage": True}


def _q(key, form_id="ACORD_125"):
    return {"field_name": key, "canonical_key": key, "_canonical_key": key,
            "question": "please provide %s" % key, "form_id": form_id}


# The filter deliberately fails OPEN when it would empty the questionnaire
# entirely (`return kept or questions`), so every list below carries the
# applicable property question a real property-only ARQ would also carry.
PROPERTY_QUESTION = "building_value"


def test_r11_no_auto_questions():
    """No Auto questions on a property-only package."""
    questions = [_q(PROPERTY_QUESTION), _q("auto_liability_limit"),
                 _q("auto_vin_schedule"), _q("auto_radius_of_operation")]
    kept = arq_service._drop_not_applicable_questions(
        questions, PROPERTY_ONLY, form_ids=["ACORD_140"])
    assert [q["canonical_key"] for q in kept] == [PROPERTY_QUESTION]


def test_r11_no_wc_questions():
    """No WC questions on a property-only package."""
    questions = [_q(PROPERTY_QUESTION), _q("wc_class_codes"),
                 _q("wc_payroll"), _q("wc_xmod")]
    kept = arq_service._drop_not_applicable_questions(
        questions, PROPERTY_ONLY, form_ids=["ACORD_140"])
    assert [q["canonical_key"] for q in kept] == [PROPERTY_QUESTION]


def test_r11_property_questions_survive():
    """POSITIVE CONTROL - the questions this package DOES need are still asked,
    so the two tests above are the applicability filter and not a function that
    drops everything."""
    questions = [_q("building_value"), _q("year_built"), _q("construction_type")]
    kept = arq_service._drop_not_applicable_questions(
        questions, PROPERTY_ONLY, form_ids=["ACORD_140"])
    assert len(kept) == 3


def test_r11_irrelevant_fields_are_not_applicable_not_missing():
    """Irrelevant fields become N/A rather than "missing"."""
    for key in ("auto_liability_limit", "auto_vin_schedule",
                "wc_class_codes", "wc_payroll"):
        assert fs.value_state_of(PROPERTY_ONLY, key) == fs.NOT_APPLICABLE, key
        assert fs.is_not_applicable(PROPERTY_ONLY, key) is True, key

    # A property fact this package has simply not stated yet is NOT_STATED -
    # a real gap. N/A and missing must stay different states.
    assert fs.value_state_of(PROPERTY_ONLY, "year_built") == fs.NOT_STATED
    assert fs.is_not_applicable(PROPERTY_ONLY, "year_built") is False


def test_r11_no_auto_or_wc_deduction_is_charged():
    """N/A costs nothing: neither the Auto Completeness nor the supplemental WC
    bucket charges a property-only package."""
    assert ce.auto_completeness_applies(PROPERTY_ONLY, PROPERTY_ONLY_FLAGS) is False
    assert ce.auto_completeness_deduction(PROPERTY_ONLY, PROPERTY_ONLY_FLAGS) == 0
    assert ce.auto_exposure_kind(PROPERTY_ONLY, PROPERTY_ONLY_FLAGS) == ce.AUTO_NONE


def test_r11_selecting_the_section_overrides_the_documents():
    """A producer who selects ACORD 127 IS applying for auto - the expiring
    dec page must not leave that form blank AND unaskable."""
    questions = [_q("auto_liability_limit", form_id="ACORD_127")]
    kept = arq_service._drop_not_applicable_questions(
        questions, PROPERTY_ONLY, form_ids=["ACORD_140", "ACORD_127"])
    assert len(kept) == 1
    assert fs.is_not_applicable_for(
        PROPERTY_ONLY, "auto_liability_limit", ["ACORD_127"]) is False


# =============================================================================
# TEST 12 - HNOA-Only Auto
# =============================================================================

# Symbols 8 (hired) and 9 (non-owned) with no owned-auto evidence anywhere.
HNOA_ONLY = {
    "has_auto_coverage": True,
    "hired_auto_exposure": True,
    "auto_covered_symbols": [{"coverage": "liability", "symbols": [8, 9]}],
}
HNOA_FLAGS = {"has_auto_coverage": True}

OWNED = {
    "has_auto_coverage": True,
    "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}],
}


def test_r12_exposure_is_recognised_as_hnoa_only():
    assert ce.auto_exposure_kind(HNOA_ONLY, HNOA_FLAGS) == ce.AUTO_HNOA_ONLY
    # POSITIVE CONTROL - an owned fleet is still owned.
    assert ce.auto_exposure_kind(OWNED, HNOA_FLAGS) == ce.AUTO_OWNED


def test_r12_no_owned_vehicle_schedule_penalty():
    """No owned-vehicle-schedule penalty."""
    assert ce.auto_completeness_applies(HNOA_ONLY, HNOA_FLAGS) is False
    assert ce.auto_completeness_gaps(HNOA_ONLY, HNOA_FLAGS) == []
    assert ce.auto_completeness_deduction(HNOA_ONLY, HNOA_FLAGS) == 0

    # POSITIVE CONTROL - the identical account with OWNED autos is charged, so
    # the 0 above is the HNOA rule and not a dead bucket. A bare owned account
    # is missing all five items (15+10+5+5+5 = 40), held at the bucket cap.
    owned_gaps = {k for k, _, _ in ce.auto_completeness_gaps(OWNED, HNOA_FLAGS)}
    assert "auto_vin_schedule" in owned_gaps
    assert ce.auto_completeness_deduction(OWNED, HNOA_FLAGS) == ce.AUTO_COMPLETENESS_CAP


def test_r12_no_owned_garaging_penalty():
    """No owned-garaging penalty."""
    charged = {k for k, _, _ in ce.auto_completeness_gaps(HNOA_ONLY, HNOA_FLAGS)}
    assert "auto_garaging_addresses" not in charged

    hard, soft = sq.evaluate_stops(HNOA_ONLY, HNOA_FLAGS)
    offenders = [m for m in list(hard) + list(soft)
                 if "garag" in m.lower() or "vehicle schedule" in m.lower()]
    assert not offenders, offenders


@pytest.mark.parametrize("key", [
    "auto_vin_schedule",
    "auto_drivers",
    "auto_garaging_addresses",
    "auto_radius_of_operation",
    "auto_vehicle_use",
])
def test_r12_owned_vehicle_facts_are_not_applicable(key):
    """The questionnaire focuses on applicable HNOA exposure: the owned-vehicle
    facts are marked Not Applicable and stop being asked."""
    assert ce.h1_fact_not_applicable(key, HNOA_ONLY) is True
    assert fs.is_not_applicable(HNOA_ONLY, key) is True

    # POSITIVE CONTROL - on an owned account the same fact stays askable.
    assert ce.h1_fact_not_applicable(key, OWNED) is False


def test_r12_suppression_survives_acord_127_being_selected():
    """The override is LINE-level: selecting ACORD 127 means they ARE applying
    for auto, but a hired/non-owned-only account still has no owned vehicles."""
    for key in ("auto_vin_schedule", "auto_garaging_addresses",
                "auto_radius_of_operation", "auto_vehicle_use"):
        assert fs.is_not_applicable_for(HNOA_ONLY, key, ["ACORD_127"]) is True, key


@pytest.mark.parametrize("key", [
    "auto_vin_schedule",
    "auto_drivers",
    "auto_garaging_addresses",
    "auto_radius_of_operation",
    "auto_vehicle_use",
])
def test_r12_owned_vehicle_questions_are_suppressed(key):
    """THE QUESTIONNAIRE DOOR: eligibility Step 1 drops an owned-vehicle
    question on an HNOA-only account.

    This is the door that actually silences these questions - the coverage-line
    filter never fires here, because an HNOA-only account declines nothing.
    """
    overlay = qe.overlay_for(
        {"field_name": key, "canonical_key": key,
         "audience": qc.AUDIENCE_CLIENT, "field_type": "text"},
        HNOA_ONLY)
    assert overlay["suppressed"] is True
    assert overlay["suppressed_reason"] == qe.REASON_NOT_APPLICABLE
    assert overlay["eligibility_step"] == 1

    # POSITIVE CONTROL - the SAME question on an owned account is not dropped
    # by Step 1, so the suppression above is the HNOA rule.
    owned_overlay = qe.overlay_for(
        {"field_name": key, "canonical_key": key,
         "audience": qc.AUDIENCE_CLIENT, "field_type": "text"},
        OWNED)
    assert owned_overlay.get("eligibility_reason") != qe.REASON_NOT_APPLICABLE


def test_r12_applicable_hnoa_exposure_is_still_addressed():
    """POSITIVE CONTROL - test 12 narrows the questionnaire, it does not
    silence the auto line: the liability limit is still raised, as a producer
    item rather than dropped as inapplicable."""
    overlay = qe.overlay_for(
        {"field_name": "auto_liability_limit",
         "canonical_key": "auto_liability_limit",
         "audience": qc.AUDIENCE_CLIENT, "field_type": "text"},
        HNOA_ONLY)
    assert overlay["eligibility_reason"] == qe.REASON_INSURANCE_JUDGMENT
    assert overlay["producer_review"] is True
