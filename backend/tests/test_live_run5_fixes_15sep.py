"""Orbin live run 5 (15 Sep 2026, session 723eb79e, policy only): ten fixes.

Every fixture is the live shape - the extracted symbols, the Subaru row, the
coverage rows and the refused quotes are copied from the session, per the
`replay-client-report-verbatim` rule. Each section also pins what the fix must
NOT touch, because the quality bar is "simulate forward", not "the reported
case passes".
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.field_qa as fq                                    # noqa: E402
import services.pdf_service as ps                                 # noqa: E402
import services.state_auto_grid as sag                            # noqa: E402
from services import auto_symbols as sym                          # noqa: E402
from services.extraction_service import (                         # noqa: E402
    _count_fact_keys, _normalize_count_facts,
)
from services.lob_canon import (                                  # noqa: E402
    AUTO as AUTO_FAMILY, canon_line, canon_part, unmapped_material_lines,
)

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(values, grounding=None):
    return {"filled_values": dict(values), "raw_text_fields": set(),
            "question_grounding": dict(grounding or {})}


def _blank(v):
    return v is None or str(v).strip() in ("", "null", "None")


# ── The live facts ───────────────────────────────────────────────────────────
SYMBOLS = [
    {"coverage": "liability", "symbols": [1]},
    {"coverage": "medical payments", "symbols": [2]},
    {"coverage": "uninsured and underinsured motorists", "symbols": [2]},
    {"coverage": "comprehensive", "symbols": [7]},
    {"coverage": "collision", "symbols": [7]},
    {"coverage": "auto medical payments", "symbols": [2]},
    {"coverage": "uninsured motorists", "symbols": [2]},
    {"coverage": "underinsured motorists", "symbols": [2]},
]
SUBARU = {"year": "2012", "make": "SUBARU", "model": "OUTBACK SEDAN",
          "vin": "4S4BRCGC9C3217772"}
AUTO = {"auto_covered_symbols": SYMBOLS, "auto_vin_schedule": [SUBARU],
        "auto_deductible_comp": "1000 DED", "auto_deductible_collision": "1000 DED",
        "has_auto_coverage": True}
NON_OWNED_DEFINITION = ('9 Non-owned Only those "autos" you do not own, lease, '
                        'hire, rent or borrow that are used in')
LIABILITY_ARTIFACT = "COVERED AUTOS LIABILITY 01 $ 1,000,000 .$ 1,496.00"


def _f(form_id, **extra):
    return {**AUTO, "_form_id": form_id, **extra}


# ── 1. ACORD 137 hired / non-owned liability: the symbols decide ─────────────

@pytest.mark.parametrize("field,want", [
    ("Vehicle_NonOwned_YesIndicator_A", "Yes"),
    ("Vehicle_NonOwned_NoIndicator_A", "No"),
    ("Vehicle_HiredBorrowed_YesIndicator_A", "Yes"),
    ("Vehicle_HiredBorrowed_NoIndicator_A", "No"),
])
def test_symbol_1_decides_hired_and_non_owned_liability(field, want):
    assert sag.resolve("ACORD_137_CO", field, AUTO) == want


def test_the_live_form_prints_non_owned_yes_whatever_the_model_quoted():
    """THE LIVE CASE: the model's only quote was the symbol-9 DEFINITION, which
    the evidence gate refuses; the box went blank beside a printed CO state."""
    mapped, _c = ps.map_facts_to_form(
        dict(AUTO), _schema("ACORD_137_CO"), "ACORD_137_CO",
        raw_text=NON_OWNED_DEFINITION,
        pre_filled_gpt=_gpt({"Vehicle_NonOwned_YesIndicator_A": "Y"},
                            {"Vehicle_NonOwned_YesIndicator_A": NON_OWNED_DEFINITION}))
    assert mapped["Vehicle_NonOwned_YesIndicator_A"] == "Yes"


def test_a_symbol_that_does_not_prove_it_leaves_the_box_to_the_document():
    """Symbol 7 alone does not cover hired autos - but an endorsement's Symbol 8
    may simply not have been captured, so "No" is never decided from absence."""
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [7]}]}
    for f in ("Vehicle_HiredBorrowed_YesIndicator_A", "Vehicle_NonOwned_NoIndicator_A"):
        assert sag.resolve("ACORD_137_CO", f, facts) is sag.SKIP


def test_symbol_9_is_non_owned_and_not_hired():
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [9]}]}
    assert sag.resolve("ACORD_137_CO", "Vehicle_NonOwned_YesIndicator_A", facts) == "Yes"
    assert sag.resolve("ACORD_137_CO", "Vehicle_HiredBorrowed_YesIndicator_A", facts) is sag.SKIP


def test_an_unrecognised_symbol_decides_nothing():
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [1, 19]}]}
    assert sag.resolve("ACORD_137_CO", "Vehicle_NonOwned_YesIndicator_A", facts) is sag.SKIP


def test_a_truckers_symbol_speaks_for_its_own_page_only():
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [41]}]}
    assert sag.resolve("ACORD_137_CO", "Vehicle_NonOwned_YesIndicator_B", facts) == "Yes"
    # the Business Auto page is a section this package does not carry
    assert sag.resolve("ACORD_137_CO", "Vehicle_NonOwned_YesIndicator_A", facts) is None


def test_the_exposure_figures_stay_owned_blanks():
    """Fix 5c from run 4 is untouched: cost of hire, days, vehicles."""
    for f in ("Vehicle_HiredBorrowed_HiredCostAmount_A",
              "Vehicle_HiredPhysicalDamage_DayCount_A"):
        assert sag.resolve("ACORD_137_CO", f, AUTO) is None


# ── 2 + 8. ACORD 127 vehicle row: ticks from the symbols, OTHER owned blank ──

@pytest.mark.parametrize("box,want", [
    ("LiabilityIndicator", "Yes"), ("MedicalPaymentsIndicator", "Yes"),
    ("UninsuredMotoristsIndicator", "Yes"), ("UnderinsuredMotoristsIndicator", "Yes"),
    ("ComprehensiveIndicator", "Yes"), ("CollisionIndicator", "Yes"),
    ("ComprehensiveDeductibleIndicator", "Yes"),
    ("SpecifiedCauseOfLossIndicator", None), ("SpecifiedCauseOfLossDeductibleIndicator", None),
    ("FireIndicator", None), ("FireTheftIndicator", None),
    ("FireTheftWindstormIndicator", None), ("LimitedSpecifiedPerilsIndicator", None),
    ("OtherIndicator", None), ("OtherDescription", None),
])
def test_the_subaru_row(box, want):
    assert ps._deterministic_map(f"Vehicle_Coverage_{box}_A", _f("ACORD_127")) == want


def test_the_live_127_prints_liab_and_drops_drive_other_car():
    """THE LIVE CASE: LIAB lost to a refused quote while MED PAY / UM / UIM /
    COMP / COLL stood; "Drive O" in the OTHER box; SPEC C OF L beside COMP."""
    mapped, _c = ps.map_facts_to_form(
        _f("ACORD_127"), _schema("ACORD_127"), "ACORD_127",
        raw_text=LIABILITY_ARTIFACT + "\nDRIVE OTHER CAR COVERAGE",
        pre_filled_gpt=_gpt(
            {"Vehicle_Coverage_LiabilityIndicator_A": "Yes",
             "Vehicle_Coverage_OtherIndicator_A": "Yes",
             "Vehicle_Coverage_OtherDescription_A": "Drive Other Car",
             "Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A": "Yes"},
            {"Vehicle_Coverage_LiabilityIndicator_A": LIABILITY_ARTIFACT}))
    assert mapped["Vehicle_Coverage_LiabilityIndicator_A"] == "Yes"
    for f in ("Vehicle_Coverage_OtherIndicator_A", "Vehicle_Coverage_OtherDescription_A",
              "Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A"):
        assert _blank(mapped.get(f)), f


def test_decided_boxes_are_never_asked():
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_127", _schema("ACORD_127"), dict(AUTO))
    for box in ("Liability", "MedicalPayments", "Comprehensive", "Collision",
                "SpecifiedCauseOfLoss", "Other"):
        assert f"Vehicle_Coverage_{box}Indicator_A" not in unmatched, box
    assert "Vehicle_Coverage_OtherDescription_A" not in unmatched


def test_uninsured_alone_does_not_tick_underinsured():
    facts = {**_f("ACORD_127"), "auto_covered_symbols": [
        {"coverage": "liability", "symbols": [1]},
        {"coverage": "uninsured motorists", "symbols": [2]}]}
    assert ps._deterministic_map("Vehicle_Coverage_UninsuredMotoristsIndicator_A", facts) == "Yes"
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_UnderinsuredMotoristsIndicator_A", facts) is ps._SCHED_SKIP


def test_um_uim_label_reader():
    facts = {"auto_covered_symbols": [{"coverage": "UM/UIM", "symbols": ["02"]},
                                      {"coverage": "Comprehensive", "symbols": [7]}]}
    assert sym.symbols_labelled(facts, ps._UM_LABEL_RE) == [2]
    assert sym.symbols_labelled(facts, ps._UIM_LABEL_RE) == [2]
    assert sym.symbols_labelled({"auto_covered_symbols": [1, 7]}, ps._UM_LABEL_RE) == []


def test_hired_and_non_owned_only_symbols_never_tick_an_owned_auto():
    facts = {**_f("ACORD_127"),
             "auto_covered_symbols": [{"coverage": "liability", "symbols": [8, 9]}]}
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_LiabilityIndicator_A", facts) is ps._SCHED_SKIP


def test_a_row_that_states_its_own_symbol_wins():
    facts = {**_f("ACORD_127"), "auto_vin_schedule": [dict(SUBARU, comp_symbol="08")]}
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_ComprehensiveIndicator_A", facts) is ps._SCHED_SKIP
    # CORRECTED 15 Sep 2026 (audit of live runs 4-7). With no comprehensive the
    # named-peril alternatives are still not carried when the captured symbol
    # grid names none of them - the dec provides only the coverages it charges
    # for - so they are owned blanks. A grid row LABELLED with one keeps the
    # box with the document.
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A", facts) is None
    scol = {**facts, "auto_covered_symbols": list(facts["auto_covered_symbols"]) + [
        {"coverage": "specified causes of loss", "symbols": [7]}]}
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A", scol) is ps._SCHED_SKIP


def test_rows_beyond_the_schedule_and_other_forms_are_not_this_resolvers():
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_LiabilityIndicator_B", _f("ACORD_127")) is ps._SCHED_SKIP
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_ComprehensiveDeductibleIndicator_A", _f("ACORD_137_CO")) is ps._SCHED_SKIP
    no_fleet = {"auto_covered_symbols": SYMBOLS, "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_coverage_tick(
        "Vehicle_Coverage_LiabilityIndicator_A", no_fleet) is ps._SCHED_SKIP


# ── 3 + 4. ACORD 131: care, custody, control and the umbrella OTHER limit ────

_LIVE_131 = {
    "CareCustodyAndControl_Property_PersonalIndicator_A": "Yes",
    "CareCustodyAndControl_Property_PropertyDescription_A": "COMMERCIAL GENERAL CONTRA",
    "CareCustodyAndControl_Location_OccupiedArea_A": "4800 DAHLIA ST # D13",
    "ExcessUmbrella_OtherCoverageDescription_A": "Commercial Auto Liability",
    "ExcessUmbrella_OtherCoverageLimitAmount_A": "3,000,000",
}


def test_the_131_sections_are_never_asked():
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", _schema("ACORD_131"), {})
    leaked = [f for f in unmatched if f.startswith("CareCustodyAndControl_")
              or f.startswith("ExcessUmbrella_OtherCoverage")]
    assert not leaked, leaked


def test_the_live_131_values_do_not_print():
    mapped, _c = ps.map_facts_to_form(
        {}, _schema("ACORD_131"), "ACORD_131",
        raw_text="Business Desc: COMMERCIAL GENERAL CONTRA Commercial Auto Liability",
        pre_filled_gpt=_gpt(_LIVE_131))
    for f in _LIVE_131:
        assert _blank(mapped.get(f)), f


def test_acord_25s_umbrella_other_line_is_untouched():
    """On the certificate the same name holds a real entry ("Excess Employers
    Liability" - test_acord25_final_three_20260906)."""
    f = "ExcessUmbrella_OtherCoverageDescription_A"
    assert ps._resolve_umbrella_other_limit(f, {"_form_id": "ACORD_25"}) is ps._SCHED_SKIP
    assert not ps._is_authoritative_blank_field(f, {"_form_id": "ACORD_25"})
    assert ps._is_authoritative_blank_field(f, {"_form_id": "ACORD_131"})


# ── 5. A deductible amount without its coverage tick ─────────────────────────

_PD_SCHEMA = {f: {} for f in (
    "Vehicle_Coverage_ComprehensiveDeductibleIndicator_A", "Vehicle_Comprehensive_DeductibleAmount_A",
    "Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_A",
    "Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A",
    "Vehicle_Coverage_CollisionIndicator_A", "Vehicle_Collision_DeductibleAmount_A")}


def test_an_ai_amount_needs_its_own_tick():
    mapped = {"Vehicle_Coverage_ComprehensiveDeductibleIndicator_A": "Yes",
              "Vehicle_Comprehensive_DeductibleAmount_A": "1,000",
              "Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A": "1,000",
              "Vehicle_Collision_DeductibleAmount_A": "1,000"}
    ai = {"Vehicle_Comprehensive_DeductibleAmount_A",
          "Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A"}
    got = ps._orphaned_deductible_amounts(mapped, _PD_SCHEMA, ai)
    # COMP has its tick; COLL's amount is not the model's (stated): only SCOL.
    assert got == [("Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A",
                    "Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_A")]


def test_the_live_137_scol_amount_does_not_print():
    mapped, _c = ps.map_facts_to_form(
        dict(AUTO), _schema("ACORD_137_CO"), "ACORD_137_CO", raw_text="$ 1,000",
        pre_filled_gpt=_gpt({"Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A": "1,000"}))
    assert _blank(mapped.get("Vehicle_SpecifiedCauseOfLoss_DeductibleAmount_A"))


# ── 6. A count is one number ─────────────────────────────────────────────────

def test_the_count_facts_are_derived_from_their_validators():
    keys = set(_count_fact_keys())
    for k in ("num_employees", "num_employees_full_time", "years_in_business", "num_claims"):
        assert k in keys, k
    for k in ("total_revenue", "effective_date", "fein", "naics_code", "gl_each_occurrence"):
        assert k not in keys, k


def test_the_live_employee_band_is_not_a_headcount():
    mf = {"num_employees": {"value": "0 - 25", "confidence": "ai_high", "source": "ai",
                            "value_state": "present", "evidence_state": "suggested"}}
    assert _normalize_count_facts(mf) == ["num_employees"]
    assert mf["num_employees"] is None


@pytest.mark.parametrize("raw,want", [
    ("25 employees", "25"), ("approximately 40", "40"), ("1,250", "1,250"), ("12", "12"),
    ("25+", None), ("under 10", None), ("10 to 15", None), ("N/A", None), ("unknown", None),
])
def test_count_shapes(raw, want):
    mf = {"num_employees": {"value": raw, "source": "ai"}}
    _normalize_count_facts(mf)
    got = mf["num_employees"]
    assert (got or {}).get("value") if want else got is None
    if want:
        assert got["value"] == want and got["source"] == "ai"


def test_a_person_or_a_derivation_is_never_rewritten():
    mf = {"num_employees": {"value": "10-15", "source": "producer"},
          "years_in_business": {"value": "about 8", "source": "derived"}}
    assert _normalize_count_facts(mf) == []
    assert mf["num_employees"]["value"] == "10-15"


def test_the_merge_normalizes_counts_before_deriving_years_in_business():
    src = open(os.path.join(BACKEND, "services", "extraction_service.py"), encoding="utf-8").read()
    assert src.index("_normalize_count_facts(mf)") < src.index("_derive_years_in_business(mf)")


def test_a_count_box_refuses_a_range_and_keeps_a_count():
    schema = _schema("ACORD_131")
    meta = schema["BusinessInformation_EmployeeCount_B"]
    assert ps._rejects_declared_type("BusinessInformation_EmployeeCount_B", meta, "0 - 25")
    assert ps._rejects_declared_type("BusinessInformation_EmployeeCount_B", meta, "25+")
    assert not ps._rejects_declared_type("BusinessInformation_EmployeeCount_B", meta, "12")
    # a number box that is not a count keeps its codes and ranges
    loc = schema["CommercialStructure_Location_ProducerIdentifier_A"]
    assert not ps._rejects_declared_type("CommercialStructure_Location_ProducerIdentifier_A", loc, "1-2")
    assert not ps._rejects_declared_type("CommercialStructure_Location_ProducerIdentifier_A", loc, "B-1")


# ── 7. One premises: the full business description ───────────────────────────

_OPS = ("Contractors - Executive Supervisors or Executive Superintendents; "
        "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC")
_ONE_LOCATION = {
    "property_locations": [{"address": "4800 DAHLIA STREET D13 DENVER CO. 80216-3121",
                            "operations_description": "COMMERCIAL GENERAL CONTRA",
                            "address_line1": "4800 DAHLIA ST", "address_city": "DENVER",
                            "address_state": "CO", "address_zip": "80216-3121"}],
    "operations_description": _OPS,
}
_F125 = "BuildingOccupancy_OperationsDescription_A"


def test_the_live_shorthand_gives_way_at_all_three_doors():
    schema = _schema("ACORD_125")
    assert ps._deterministic_map(_F125, _ONE_LOCATION) == _OPS
    gaps, _u, _d = ps.compute_form_gaps("ACORD_125", schema, _ONE_LOCATION)
    mapped, _c = ps.map_facts_to_form(dict(_ONE_LOCATION), schema, "ACORD_125",
                                      raw_text=_OPS, pre_filled_gpt=_gpt({}))
    assert gaps.get(_F125) == _OPS and mapped.get(_F125) == _OPS


def test_without_an_account_description_the_location_keeps_its_own():
    facts = {"property_locations": _ONE_LOCATION["property_locations"]}
    assert ps._deterministic_map(_F125, facts) == "COMMERCIAL GENERAL CONTRA"


def test_two_locations_keep_their_own_text():
    facts = {"property_locations": [{"operations_description": "Equipment yard"},
                                    {"operations_description": "Fabrication shop"}],
             "operations_description": _OPS}
    assert ps._deterministic_map(_F125, facts) == "Equipment yard"


# ── 9. Drive Other Car is an auto coverage part ──────────────────────────────

_LIVE_LINES = [
    {"line": "Covered Autos Liability", "policy_number": "6E7-40-02---26", "premium": "$ 1,496.00"},
    {"line": "Automobile", "premium": "$2,991.00"},
    {"line": "Uninsured and Underinsured Motorists", "policy_number": "6E7-40-02---26", "premium": "$ 258.00"},
    {"line": "Comprehensive", "policy_number": "6E7-40-02---26", "premium": "$ 134.00"},
    {"line": "Collision", "policy_number": "6E7-40-02---26", "premium": "$ 289.00"},
    {"line": "Drive Other Car", "policy_number": "6E7-40-02---26", "premium": "$ 204.00"},
    {"line": "Commercial Umbrella", "policy_number": "6J7-40-02---26", "premium": "$ 3,418.00"},
]


def test_drive_other_car_is_placed_not_routed():
    assert unmapped_material_lines(_LIVE_LINES) == []
    assert canon_part("Drive Other Car") == AUTO_FAMILY
    assert canon_part("Broadened Coverage For Named Individuals") == AUTO_FAMILY
    assert canon_line("Drive Other Car") is None, "a part, never a line"


def test_a_genuinely_unknown_line_still_reaches_the_producer():
    lines = _LIVE_LINES + [{"line": "Kidnap and Ransom", "premium": "$ 900.00"}]
    assert unmapped_material_lines(lines) == ["Kidnap and Ransom"]


# ── 10. The "left blank on purpose" list says what is true ───────────────────

def test_an_unanswered_question_is_classed_unanswered_and_a_refusal_is_not():
    schema = _schema("ACORD_131")
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", schema, {})
    # A REAL count box that reaches gap fill on this schema - a hand-picked one
    # can be an owned blank and make the refusal half pass vacuously.
    count_box = next(f for f in sorted(unmatched)
                     if re.sub(r"_[A-Z]{1,2}$", "", f).endswith("Count")
                     and ps._tooltip_declared_type(schema[f]) == "number")
    question = "CommercialUmbrellaLineOfBusiness_Question_AAICode_A"
    assert question in unmatched
    report = []
    ps.map_facts_to_form(
        {}, schema, "ACORD_131", raw_text="ORBIN",
        pre_filled_gpt=_gpt({question: "Y", count_box: "0 - 25"}),
        guard_report=report)
    kinds = {r["field"]: r.get("kind") for r in report}
    assert kinds.get(question) == "unanswered"
    assert count_box in kinds, f"{count_box} was not refused"
    assert kinds[count_box] is None, "a range in a count box is a real refusal"


def test_question_groups_are_structural():
    schema = _schema("ACORD_125")
    mapped = {"CommercialPolicy_JudgementOrLienExplanation_A": None,
              "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A": "Foreclosure 2021"}
    got = ps._unanswered_question_fields(schema, mapped, {
        "CommercialPolicy_JudgementOrLien_OccurrenceDate_A",           # explanation empty
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_A",  # explanation kept
        "CommercialPolicy_Question_KACCode_A",                         # a Y/N box
        "NamedInsured_Primary_PhoneNumber_A",                          # a data box
    })
    assert got == {"CommercialPolicy_JudgementOrLien_OccurrenceDate_A",
                   "CommercialPolicy_Question_KACCode_A"}


def test_field_qa_lists_refusals_only_and_the_list_keeps_everything():
    blanks = [
        {"form_id": "ACORD_131", "field": "CommercialUmbrellaLineOfBusiness_Question_AAICode_A",
         "removed_value": "Y", "kind": "unanswered"},
        {"form_id": "ACORD_131", "field": "BusinessInformation_EmployeeCount_B",
         "removed_value": "0 - 25"},
    ]
    qa = fq.run_field_qa({"ACORD_131": {"mapped": {}, "confidence": {}, "schema": {},
                                        "guard_blanks": blanks}},
                         merged_facts={}, confirmations={})
    listed = [r["field"] for r in qa["results"] if r["reason_code"] == "guard_removed_value"]
    assert listed == ["BusinessInformation_EmployeeCount_B"]
    rows = fq.to_recommendation_rows(qa)
    msg = [r["message"] for r in rows if "left blank on purpose" in (r["message"] or "")]
    assert len(msg) == 1 and "1 field left blank" in msg[0]
    # arq reads `guard_blanks` so no later pass reopens a refused box - both stay
    assert len(blanks) == 2


def test_the_report_carries_the_kind_from_the_one_classification():
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"), encoding="utf-8").read()
    body = src[src.index("_unanswered = set(_gate_refused)"):]
    assert "_unanswered_question_fields(" in body[:400]
    assert '_row["kind"] = "unanswered"' in body[:1400]


# ── Round 2 (same day): what round 1 found and left ──────────────────────────

_UMBRELLA_ROWS = [
    {"line": "Commercial Umbrella", "policy_number": "6J7-40-02---26", "premium": "$ 3,418.00"},
    {"line": "Umbrella", "premium": "$3,418.00"},
    {"line": "Commercial Liability Umbrella"},
    {"line": "Commercial General Liability", "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
]


@pytest.mark.parametrize("form_id", ["ACORD_131", "ACORD_25"])
def test_the_umbrella_names_itself(form_id):
    facts = {"coverage_lines": _UMBRELLA_ROWS, "_form_id": form_id}
    assert ps._deterministic_map("Policy_PolicyType_UmbrellaIndicator_A", facts) == "Yes"
    assert ps._deterministic_map("Policy_PolicyType_ExcessIndicator_A", facts) == "No"


def test_an_excess_policy_ticks_excess():
    facts = {"coverage_lines": [{"line": "Commercial Excess Liability", "premium": "$ 2,100.00"}]}
    assert ps._resolve_umbrella_or_excess("Policy_PolicyType_ExcessIndicator_A", facts) == "Yes"
    assert ps._resolve_umbrella_or_excess("Policy_PolicyType_UmbrellaIndicator_A", facts) == "No"


@pytest.mark.parametrize("lines", [
    [{"line": "Umbrella / Excess Liability", "premium": "$ 900.00"}],              # both words
    [{"line": "Commercial Umbrella", "premium": "$1"}, {"line": "Excess Liability", "premium": "$2"}],
    [{"line": "Commercial General Liability", "premium": "$1"}],                    # no umbrella row
    [],                                                                              # no per-line data
])
def test_ambiguity_stays_with_the_document(lines):
    assert ps._resolve_umbrella_or_excess(
        "Policy_PolicyType_UmbrellaIndicator_A", {"coverage_lines": lines}) is ps._SCHED_SKIP


def test_a_row_marked_not_carried_is_not_evidence():
    lines = [{"line": "Umbrella", "premium": "No Coverage"}]
    assert ps._resolve_umbrella_or_excess(
        "Policy_PolicyType_UmbrellaIndicator_A", {"coverage_lines": lines}) is ps._SCHED_SKIP


def test_the_live_131_prints_umbrella():
    """THE LIVE CASE: the model ticked both, the conflict guard cleared both."""
    mapped, _c = ps.map_facts_to_form(
        {"coverage_lines": _UMBRELLA_ROWS}, _schema("ACORD_131"), "ACORD_131", raw_text="UMBRELLA",
        pre_filled_gpt=_gpt({"Policy_PolicyType_UmbrellaIndicator_A": "Yes",
                             "Policy_PolicyType_ExcessIndicator_A": "Yes"}))
    assert mapped["Policy_PolicyType_UmbrellaIndicator_A"] == "Yes"
    assert mapped.get("Policy_PolicyType_ExcessIndicator_A") in ("No", None)


@pytest.mark.parametrize("basis,occ,cm", [("Occurrence", "Yes", "No"), ("Claims-Made", "No", "Yes")])
def test_the_underlying_cgl_box_reads_the_gl_rows_own_fact(basis, occ, cm):
    facts = {"gl_form_type": basis, "_form_id": "ACORD_131"}
    assert ps._deterministic_map(
        "UnderlyingCoverage_Coverage_GeneralLiabilityOccurrenceIndicator_A", facts) == occ
    assert ps._deterministic_map(
        "UnderlyingCoverage_Coverage_GeneralLiabilityClaimsMadeIndicator_A", facts) == cm


def test_no_stated_basis_still_asks_the_document():
    box = "UnderlyingCoverage_Coverage_GeneralLiabilityOccurrenceIndicator_A"
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", _schema("ACORD_131"), {})
    assert box in unmatched
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", _schema("ACORD_131"),
                                             {"gl_form_type": "Occurrence"})
    assert box not in unmatched


_CRANES_Q = "CommercialUmbrellaLineOfBusiness_Question_ABACode_A"
_CRANES_E = "CommercialUmbrellaLineOfBusiness_ApplicantOwnRentUseCranesExplanation_A"


def test_a_coverage_form_title_cannot_carry_a_yes():
    """THE LIVE CASE: "uses cranes?" = Y, explained by a form's name that is
    verbatim in the document. Run 5 lost it only because the same title sat in
    four boxes and tripped the duplicate guard - used once, it shipped."""
    title = "Commercial General Liability Coverage Form"
    report = []
    mapped, _c = ps.map_facts_to_form(
        {}, _schema("ACORD_131"), "ACORD_131", raw_text="SECTION I " + title + " applies.",
        pre_filled_gpt=_gpt({_CRANES_Q: "Y", _CRANES_E: title}), guard_report=report)
    assert _blank(mapped.get(_CRANES_Q)) and _blank(mapped.get(_CRANES_E))
    assert {r["field"]: r.get("kind") for r in report}.get(_CRANES_Q) == "unanswered"


def test_a_real_explanation_still_carries_its_yes():
    said = "The applicant rents a mobile crane twice a year for roof truss installs."
    mapped, _c = ps.map_facts_to_form(
        {}, _schema("ACORD_131"), "ACORD_131", raw_text=said,
        pre_filled_gpt=_gpt({_CRANES_Q: "Y", _CRANES_E: said}))
    assert mapped.get(_CRANES_Q) == "Y" and mapped.get(_CRANES_E) == said


@pytest.mark.parametrize("text,is_title", [
    ("Commercial General Liability Coverage Form", True),
    ("CG 00 01 04 13 Commercial General Liability Coverage Form", True),
    ("Business Auto Coverage Form.", True),
    ("Commercial Inland Marine Coverage Part", True),
    ("Subcontractors are required to carry coverage.", False),
    ("This Coverage Form's Covered Autos Liability Coverage", False),
    ("The Commercial General Liability Coverage Form applies", False),
    ("", False),
])
def test_coverage_form_title_shape(text, is_title):
    assert ps._is_coverage_form_title(text) is is_title
