"""Run 9, second pass: the residuals the ground-truth fixture proved wrong.

Scored against `tests/fixtures/orbin_ground_truth.json` - built by reading all
271 real pages, not by running the pipeline - so every expectation below is a
fact about the client's document, not a guess about the model.

    ERIN ROYAL as the sole ACORD 127 driver
        fixture: "There is NO driver schedule in this package... ERIN ROYAL:
        page 92, CA 99 10 A DRIVE OTHER CAR COVERAGE, under 'NAMES OF
        INDIVIDUALS'. The ONLY personal name in 180 pages, and it is a Drive
        Other Car named individual, NOT a driver."
    A THIRD hazard row (91580 / Payroll / $39,300 / territory "CO")
        fixture: exactly TWO class codes, 91580 and 91585.
    MAXIMUM DOLLAR VALUE SUBJECT TO LOSS = $1,000,000
        fixture: that is the Auto LIABILITY limit; the one vehicle is $26,680.
    "# FULL-TIME STAFF 1 / # PART-TIME STAFF 0" on the 126
        fixture: no employee data anywhere. The 125's identical boxes were
        correctly blank - which is the tell.
    Q7 hazmat = Y, evidenced by "BUSINESS DESC: COMMERCIAL GENERAL CONTRA"
        the truncated business description wearing a label so it read as data.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")
_GT_PATH = os.path.join(BACKEND, "tests", "fixtures", "orbin_ground_truth.json")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def gt():
    with open(_GT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ── The fixture is the spec; keep it honest ──────────────────────────────────

def test_the_ground_truth_fixture_still_says_what_these_tests_assume(gt):
    """ANTI-ROT. Every expectation below quotes this file. If someone edits the
    fixture, the tests that depend on it must fail loudly rather than silently
    start grading against different numbers."""
    assert gt["_traps"]["driver_schedule"]["correct"] is None
    assert "ERIN ROYAL" in gt["_traps"]["driver_schedule"]["decoys"]
    assert len(gt["_traps"]["gl_class_codes"]["correct"]) == 2
    assert gt["_source_data"]["auto_section_pages_85_92"]["vehicle_1"]["cost_new"] == "26680"
    assert gt["_source_data"]["auto_section_pages_85_92"]["limits"]["liability_csl"] == "$1,000,000"
    # RESTRUCTURED 2026-08-14: the vehicle is now SCORED, not just recorded.
    assert gt["Vehicle_VINIdentifier_A"] == "4S4BRCGC9C3217772"
    assert gt["Vehicle_CostNewAmount_A"] == "$26,680"
    assert gt["_forms"] == ["ACORD_125", "ACORD_126", "ACORD_127"]
    assert gt["Policy_Payment_EstimatedTotalAmount_A"] == "$10,663.00"


# ── 1. A Drive Other Car named individual is not a driver ────────────────────

_ERIN = {"auto_drivers": [{"name": "Erin Royal"}]}


def test_a_name_only_driver_record_does_not_stamp_a_row():
    """Real ACORD 127 field names, taken off the schema - a hand-written name
    that exists on no form makes this pass vacuously."""
    schema = _schema("ACORD_127")
    for field in ("Driver_GivenName_A", "Driver_Surname_A"):
        assert field in schema, field
        assert ps._deterministic_map(field, _ERIN) is None, field


def test_a_real_driver_still_stamps():
    """The other direction: a driver the document actually schedules - licence,
    DOB, anything beyond the bare name - fills the row exactly as before."""
    facts = {"auto_drivers": [{"name": "Erin Royal",
                               "license_number": "12-345-6789",
                               "date_of_birth": "04/11/1980"}]}
    assert ps._deterministic_map("Driver_GivenName_A", facts)
    assert ps._deterministic_map("Driver_Surname_A", facts)


def test_name_only_additional_interests_are_untouched():
    """THE REVERT GUARD. A name-only additional named insured / additional
    interest IS a supported record shape - blanking those was tried once, broke
    five tests, and was reverted. This scoping must not widen by accident."""
    assert ps._NAME_ONLY_INVALID_SCHEDULES == frozenset({"auto_drivers", "drivers"}), (
        "the name-only rule was widened beyond drivers - check "
        "test_form_fill_ownership_20260810_runf before doing that")


# ── 2. Two class codes means two hazard rows ─────────────────────────────────

_TWO_CLASSES = {"gl_class_codes": [
    {"code": "91580", "description": "Contractors - Executive Supervisors"},
    {"code": "91585", "description": "Contrctrs-sub work-in connection"},
]}


@pytest.mark.parametrize("row", ["C", "D", "E"])
def test_a_hazard_row_past_the_schedule_is_an_authoritative_blank(row):
    """Run 9 printed a THIRD row - row 1's code, basis and exposure with an
    invented territory - because a row past the end returned 'UNMATCHED' and
    handed the whole row to gap fill."""
    for col in ps._GL_HAZARD_COL_TO_KEY:          # the resolver's own columns
        field = f"GeneralLiability_Hazard_{col}_{row}"
        assert ps._resolve_gl_hazard_row(field, _TWO_CLASSES) is None, field


def test_hazard_rows_within_the_schedule_are_not_suppressed():
    for row in ("A", "B"):
        got = ps._resolve_gl_hazard_row(
            f"GeneralLiability_Hazard_ClassCode_{row}", _TWO_CLASSES)
        assert got is not None, row


def test_no_schedule_at_all_still_reaches_the_model():
    """Acts only on POSITIVE evidence, exactly like the vehicle version:
    suppressing on no evidence would delete a schedule extraction merely
    missed."""
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_ClassCode_C", {}) == "UNMATCHED"


# ── 3. Maximum exposure is arithmetic over the vehicle schedule ──────────────

_MAXEXP = "CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_A"


def test_max_exposure_is_the_vehicle_value_not_the_liability_limit():
    facts = {"auto_vin_schedule": [
        {"vin": "4S4BRCGC9C3217772", "year": "2012", "cost_new": "26680"}]}
    assert ps._resolve_max_vehicle_exposure(_MAXEXP, facts) == "$26,680"


def test_max_exposure_sums_a_fleet():
    facts = {"auto_vin_schedule": [{"cost_new": "26680"},
                                   {"cost_new": "$41,800"},
                                   {"cost_new": "58,900"}]}
    assert ps._resolve_max_vehicle_exposure(_MAXEXP, facts) == "$127,380"


def test_max_exposure_is_blank_without_cost_figures():
    assert ps._resolve_max_vehicle_exposure(_MAXEXP, {}) is None
    assert ps._resolve_max_vehicle_exposure(
        _MAXEXP, {"auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}]}) is None
    assert ps._is_authoritative_blank_field(_MAXEXP, {})


def test_the_liability_limit_can_no_longer_reach_that_box():
    """End to end with the client's literal value."""
    schema = {_MAXEXP: {"tu": "Enter amount: The highest value that the insurer "
                              "would be subject to", "ft": "/Tx"}}
    mapped, _ = ps.map_facts_to_form(
        {"auto_liability_limit": "$1,000,000"}, schema, "ACORD_127",
        raw_text="COVERED AUTOS LIABILITY $1,000,000",
        pre_filled_gpt={"filled_values": {_MAXEXP: "$1,000,000"},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(_MAXEXP) is None


# ── 4. Contractor staff counts come from a fact or stay blank ────────────────

def test_contractor_staff_counts_are_blank_without_an_employee_fact():
    for f in ("Contractors_FullTimeEmployeeCount_A",
              "Contractors_PartTimeEmployeeCount_A"):
        assert ps._resolve_exposure_count(f, {}) is None, f
        assert ps._is_authoritative_blank_field(f, {}), f


def test_contractor_staff_counts_stamp_from_a_real_fact():
    assert ps._resolve_exposure_count(
        "Contractors_FullTimeEmployeeCount_A", {"full_time_employees": "12"}) == "12"
    assert ps._resolve_exposure_count(
        "Contractors_PartTimeEmployeeCount_A",
        {"num_employees_part_time": "3"}) == "3"


def test_the_125_employee_boxes_are_deliberately_out_of_scope():
    """The first cut matched every *EmployeeCount and broke three pinned ACORD
    125 behaviours (the part-time fact, the per-location schedule beating the
    scalar, row B staying blank). Those boxes were already correct."""
    assert ps._resolve_exposure_count(
        "BusinessInformation_FullTimeEmployeeCount_A", {}) is ps._SCHED_SKIP
    assert ps._resolve_exposure_count(
        "GeneralLiability_EmployeeBenefits_EmployeeCount_A", {}) is ps._SCHED_SKIP


# ── 5. A label does not turn a fact into evidence ────────────────────────────

_FACTS = {"contractor_type": "COMMERCIAL GENERAL CONTRA",
          "applicant_name": "ORBIN CONTRACTING LLC",
          "physical_address": "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"}


def test_the_labelled_business_description_cannot_evidence_hazmat():
    """Run 9's ACORD 127 Q7, verbatim. `_DATA_PAYLOAD_RE` exempts anything
    shaped 'LABEL: value' from the assertion test - so the truncated business
    description wore a label and read as data."""
    assert ps._is_coverage_artifact_text(
        "BUSINESS DESC: COMMERCIAL GENERAL CONTRA", frozenset(), _FACTS)


@pytest.mark.parametrize("legit", [
    "INSURED IS: LLC",
    "Date of Issue: 07/16/2025",
    "Policy Term: 07/15/2025-07/15/2026",
])
def test_legitimate_labelled_data_still_grounds_an_answer(legit):
    """The payload exemption exists for a reason and must survive: these carry
    real data the question can stand on."""
    assert not ps._is_coverage_artifact_text(legit, frozenset(), _FACTS), legit


def test_a_labelled_line_restating_a_held_fact_is_rejected_generally():
    for text in ("Named Insured: ORBIN CONTRACTING LLC",
                 "Business Desc: Commercial General Contra"):
        assert ps._is_coverage_artifact_text(text, frozenset(), _FACTS), text


def test_q7_falls_end_to_end():
    q = "CommercialVehicleLineOfBusiness_Question_AAFCode_A"
    tu = ('Enter Y for a "Yes" response. Input N for "No" response. Indicates '
          'the response to the question, "Do operations involve transporting '
          'hazardous material?"')
    mapped, _ = ps.map_facts_to_form(
        _FACTS, {q: {"tu": tu, "ft": "/Tx"}}, "ACORD_127",
        raw_text="BUSINESS DESC: COMMERCIAL GENERAL CONTRA\n",
        pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                        "question_grounding": {
                            q: "BUSINESS DESC: COMMERCIAL GENERAL CONTRA"}})
    assert mapped.get(q) is None


# ── 6. The values the fixture confirms CORRECT must not regress ──────────────

def test_the_vehicle_row_the_fixture_confirms_still_stamps(gt):
    """Everything C46/C22 fixed, re-pinned against the real package: one
    vehicle, its VIN, cost new, class, territory and both symbols."""
    v = gt["_source_data"]["auto_section_pages_85_92"]["vehicle_1"]
    facts = {"auto_vin_schedule": [{
        "vin": v["vin"], "year": v["year"], "make": v["make"],
        "model": v["model"], "cost_new": v["cost_new"]}]}
    assert ps._deterministic_map("Vehicle_VINIdentifier_A", facts) == v["vin"]
    assert ps._deterministic_map("Vehicle_ModelYear_A", facts) == v["year"]
    # ...and row B stays blank: ONE vehicle in this package.
    assert ps._deterministic_map("Vehicle_VINIdentifier_B", facts) is None


def test_the_comprehensive_and_collision_symbols_may_legitimately_agree(gt):
    """WHY THE CROSS-COLUMN GUARD WAS REMOVED. Both are '07' on this package
    and both are correct, which makes them structurally indistinguishable from
    RateClassCode vs SpecialIndustryClassCode - two taxonomies that must never
    agree. Blanking a covered-auto symbol is a coverage misstatement; a wrong
    industry class is a figure the underwriter re-rates. This test exists so
    nobody rebuilds that guard without solving the ambiguity first."""
    syms = gt["_source_data"]["auto_section_pages_85_92"]["covered_auto_symbols"]
    assert syms["comprehensive"] == syms["collision"] == "07"
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    assert "DELIBERATELY NOT GUARDED: one printed value in two row columns" in src
