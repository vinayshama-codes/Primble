"""A producer's pre-form answers reach their own boxes, and only those
(14 Oct 2026, live run `b117f010`, Choice Electric item 18 / Orbin item 13).

1. ACORD 125's GL CODE box read only the rating schedule: the "no class codes"
   card's answer printed on the 126 grid and not here.
2. A typed auto liability limit is stored as bare digits ("1000000"); the
   amount reader refused a bare number, so the 131's underlying auto limit
   stayed blank although the answer had cleared the score's warning.
3. Any AI value equal to ANY person's value skipped every refusal rule: the
   hydrant "500" stood as miles to the fire station and four exposure
   distances, the auto limit as the 137's uninsured motorist limits, the roof
   year as the heating / wiring / other improvement years.
"""
import json
import os

import services.ai_answer_guards as g
import services.pdf_service as ps
from services.coverage_evidence import liability_amounts

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _person(value):
    return {"value": value, "source": "producer"}


# ── 1. the 125 GL CODE box ────────────────────────────────────────────────────

def test_the_125_gl_code_box_prints_the_code_a_person_gave():
    f = {"_form_id": "ACORD_125", "gl_class_codes_by_location": _person("92478")}
    assert ps._deterministic_map("NamedInsured_GeneralLiabilityCode_A", f) == "92478"


def test_a_rating_schedule_still_wins_over_the_typed_code():
    f = {"_form_id": "ACORD_125", "gl_class_codes_by_location": _person("92478"),
         "gl_class_code_schedule": [{"class_code": "91580", "classification": "Contractors",
                                     "premium_basis": "payroll", "exposure": "39300"}]}
    out = ps._deterministic_map("NamedInsured_GeneralLiabilityCode_A", f)
    assert "92478" not in str(out)


def test_a_non_iso_code_never_prints_in_the_gl_code_box():
    for typed in ("1731", "5190", "none", "TBD"):
        f = {"_form_id": "ACORD_125", "gl_class_codes_by_location": _person(typed)}
        assert ps._deterministic_map("NamedInsured_GeneralLiabilityCode_A", f) != typed


# ── 2. a typed limit stored as bare digits ───────────────────────────────────

def test_a_whole_bare_number_is_that_amount():
    assert liability_amounts("1000000") == [1000000.0]
    assert liability_amounts(1000000) == [1000000.0]
    assert liability_amounts("1000000.00") == [1000000.0]
    # inside a printing a bare number is still not an amount (policy numbers)
    assert liability_amounts("Policy 1000000") == []
    assert liability_amounts("2026") == [] and liability_amounts("12") == []


def test_the_131_underlying_auto_limit_prints_the_typed_answer():
    f = {"_form_id": "ACORD_131", "auto_liability_limit": _person("1000000")}
    with ps._schema_context(_schema("ACORD_131")):
        assert ps._resolve_auto_liability_limit_cell(
            "Vehicle_CombinedSingleLimit_EachAccidentAmount_A", f) == "1000000"


# ── 3. a person's value is evidence only for its own question ────────────────
# Document text in the shape of the live package: "500" and "1,000,000" are
# printed, but never beside exposure, fire station, towing or uninsured
# motorist wording, and 2015 only inside a date.
RAW = ("COMMERCIAL GENERAL LIABILITY EACH OCCURRENCE $1,000,000 GENERAL AGGREGATE $2,000,000\n"
       "POLICY PERIOD 01/01/2015 TO 01/01/2016\n"
       "PREMISES 001 BUILDING 001 FRAME CONSTRUCTION\n"
       "CRIME AND FIDELITY COVERAGE PART $ 500.00\n")


def _judge(form_id, facts, field, value, raw=RAW):
    return g._judge(field, value, g._Context({}, {**facts, "_form_id": form_id}, raw, form_id))


def test_the_hydrant_answer_is_not_the_fire_station_or_exposure_distance():
    facts = {"distance_to_hydrant": _person("500")}
    for box in ("BuildingFireProtection_FireStationDistanceMileCount_A", "BuildingExposure_FrontDistance_A",
                "BuildingExposure_RearDistance_B"):
        assert _judge("ACORD_140", facts, box, "500"), box
    # the hydrant box itself asks the person's question
    assert _judge("ACORD_140", facts, "BuildingFireProtection_HydrantDistanceFeetCount_B", "500") is None


def test_an_exposure_distance_the_documents_state_is_kept():
    raw = RAW + "EXPOSURES: REAR 50 FT TO ADJACENT BUILDING\n"
    assert _judge("ACORD_140", {}, "BuildingExposure_RearDistance_A", "50", raw) is None
    assert _judge("ACORD_140", {}, "BuildingExposure_FrontDistance_A", "75", raw)   # 75 is never stated


def test_the_auto_limit_is_not_the_uninsured_motorist_or_towing_limit():
    facts = {"auto_liability_limit": _person("1000000")}
    for box in ("Vehicle_UninsuredMotorists_BodilyInjuryPerAccidentLimitAmount_A",
                "Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A",
                "Vehicle_TowingAndLabour_LimitAmount_A"):
        assert _judge("ACORD_137_CO", facts, box, "1,000,000"), box
    # a towing limit the documents print beside towing is kept
    raw = RAW + "TOWING AND LABOR $ 75 PER DISABLEMENT\n"
    assert _judge("ACORD_137_CO", {}, "Vehicle_TowingAndLabour_LimitAmount_A", "75", raw) is None


def test_the_roof_year_is_not_the_wiring_or_heating_year_but_is_the_roof_year():
    facts = {"roof_year": _person("2015")}
    assert _judge("ACORD_140", facts, "BuildingImprovement_WiringYear_A", "2015")
    assert _judge("ACORD_140", facts, "BuildingImprovement_HeatingYear_A", "2015")
    assert _judge("ACORD_140", facts, "BuildingImprovement_RoofingYear_A", "2015") is None
    assert _judge("ACORD_140", facts, "BuildingImprovement_RoofingYear_B", "2015") is None


def test_round_9_still_holds_a_persons_year_built_and_protection_class_on_building_2():
    facts = {"year_built": _person("2001"), "fire_protection_class": _person("3")}
    assert _judge("ACORD_140", facts, "CommercialStructure_BuiltYear_B", "2001") is None
    assert _judge("ACORD_140", facts, "BuildingFireProtection_ProtectionClassCode_B", "3") is None


def test_box_question_facts_reads_the_stampers_own_doors():
    assert "fire_protection_class" in g.box_question_facts("BuildingFireProtection_ProtectionClassCode_B", {}, "ACORD_140")
    assert "year_built" in g.box_question_facts("CommercialStructure_BuiltYear_B", {}, "ACORD_140")
    assert "distance_to_hydrant" in g.box_question_facts("BuildingFireProtection_HydrantDistanceFeetCount_A", {}, "ACORD_140")
    assert "distance_to_hydrant" not in g.box_question_facts(
        "BuildingFireProtection_FireStationDistanceMileCount_A", {}, "ACORD_140")


# ── The review's corrections (same day) ──────────────────────────────────────

def test_a_persons_um_and_med_pay_answers_stay_on_the_138_and_137():
    facts = {"auto_um_uim_limit": _person("1000000"), "auto_med_pay_limit": _person("5000")}
    for form in ("ACORD_138_CA", "ACORD_137_CA"):
        assert _judge(form, facts, "Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A", "1,000,000") is None
        assert _judge(form, facts, "Vehicle_MedicalPayments_PerPersonLimitAmount_A", "5,000") is None
    # ...but the LIABILITY limit is still not the UM limit
    assert _judge("ACORD_138_CA", {"auto_liability_limit": _person("1000000")},
                  "Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A", "1,000,000")


def test_split_limits_typed_in_words_stay_split():
    from services.coverage_evidence import _human_liability_reading
    split = {"auto_liability_limit": {"value": "500000", "source": "producer",
                                      "answer_text": "$500,000 per person / $1,000,000 per accident / $250,000 PD"}}
    assert _human_liability_reading(split) == "split"
    one = {"auto_liability_limit": {"value": "1000000", "source": "producer", "answer_text": "$1,000,000"}}
    assert _human_liability_reading(one) == "csl"
    bare = {"auto_liability_limit": {"value": "1000000", "source": "producer"}}
    assert _human_liability_reading(bare) == "csl"


def test_the_131_underlying_policy_grid_is_never_the_auto_limit_cell():
    f = {"_form_id": "ACORD_131", "auto_liability_limit": _person("1000000")}
    for box in ("UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A",
                "UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A"):
        assert ps._resolve_auto_liability_limit_cell(box, f) is ps._SCHED_SKIP


def test_a_bare_premium_with_cents_is_not_a_limit():
    assert liability_amounts("16818.00") == []
    assert liability_amounts("1000000.00") == [1000000.0]
