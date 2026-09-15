"""Live run 7 (session 3872ec28, 15 Sep 2026, Orbin policy only) - the eight
things still wrong after run 6, plus every box a 69-box cross-run audit (runs
4-7, adversarially verified) found the facts already decide. Driven with the
LIVE values.

1. ACORD 137 PARTNERS printed "104" - the Drive Other Car TERRITORY code.
2. ACORD 126 OTHER deductible "Property Damage Deductible $1,000" - a printed
   row's name in the OTHER row, under a PD tick the gate refused.
3. ACORD 126 aggregate "applies to OTHER" ticked with nothing named.
4. ACORD 126 $ PAID TO SUBCONTRACTORS lost ($350,000 on one run of four).
5. ACORD 131 Q9 hired / non-owned flipped Y -> blank.
6. ACORD 127 VEHICLE TYPE blank while the dec prints "PRIV PASSENGER", and
   BODY TYPE took the type.
7. Cover page "left blank by the AI" listed boxes the AI was never asked.
8. "Policies in this submission" listed three "No Coverage" lines as policies.
"""
import copy
import json
import os

import pytest

import services.pdf_service as ps
import services.field_qa as fq
import services.extraction_service as es
import services.underwriting_consistency as uc

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = ps._SCHED_SKIP


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(values, grounding=None):
    return {"filled_values": values, "raw_text_fields": set(), "question_grounding": grounding or {}}


def _dec(label, value, section, line, pol=None, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner,
            "policy_number": pol, "line_of_business": line}


_AUTO_DEC = "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO"
_AUTO_POL = "6E7-40-02---26"
# Run 7's literal entries.
_EMPLOYEES = _dec("NUMBER OF EMPLOYEES", "0 - 25", _AUTO_DEC, "Commercial Auto", _AUTO_POL, "applicant")
_DOC_TERRITORY = _dec("DRIVE OTHER CAR - TERRITORY", "104 6679 $ 204.00", "ENDORSEMENT PREMIUM DETAIL",
                      "Commercial Auto", _AUTO_POL)
_LOC = _dec("LOC", "001 4800 DAHLIA STREET D13 DENVER CO. 80216-3121", _AUTO_DEC, "Commercial Auto",
            _AUTO_POL, "applicant")
_COST_NEW = _dec("COST NEW", "26680", _AUTO_DEC, "Commercial Auto", _AUTO_POL)
_UMB_POL = "6J7-40-02---26"
_UMB = [
    _dec("Each Occurrence Limit (Liability Coverage)", "$ 3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS",
         "Commercial Umbrella", _UMB_POL),
    _dec("Personal & Advertising Injury Limit", "$ 3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS",
         "Commercial Umbrella", _UMB_POL),
    _dec("Aggregate Limit (Liability Coverage)", "$ 3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS",
         "Commercial Umbrella", _UMB_POL),
    _dec("Self Insured Retention", "$ 0", "COMMERCIAL UMBRELLA SCHEDULE", "Commercial Umbrella", _UMB_POL),
    _dec("Personal and Advertising Injury", "$ 1,000,000", "SCHEDULE OF UNDERLYING INSURANCE",
         "Commercial Umbrella", _UMB_POL),
    _dec("Each Occurrence", "$ 1,000,000", "SCHEDULE OF UNDERLYING INSURANCE", "Commercial Umbrella", _UMB_POL),
]
_SYMBOLS = [{"coverage": "liability", "symbols": [1]}, {"coverage": "medical payments", "symbols": [2]},
            {"coverage": "uninsured and underinsured motorists", "symbols": [2]},
            {"coverage": "comprehensive", "symbols": [7]}, {"coverage": "collision", "symbols": [7]}]
_VEHICLE = {"year": "2012", "make": "SUBARU", "model": "OUTBACK SEDAN", "vin": "4S4BRCGC9C3217772",
            "body_type": "PRIV PASSENGER", "gvw": None, "comp_symbol": "07", "coll_symbol": "07",
            "class_code": "7383", "territory": "111"}
_LOCATION = {"address": "4800 Dahlia Street D13, Denver CO. 80216-3121",
             "address_line1": "4800 DAHLIA ST", "address_line2": "# D13", "address_city": "DENVER",
             "address_state": "CO", "address_zip": "80216-3121", "location_id": "L1",
             "location_number": "1", "address_county": None}
_EXEC = "Contractors - Executive Supervisors or Executive Superintendents"
_SUB = "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC"


def _row(loc, code, cls, basis, exposure):
    return {"location": loc, "class_code": code, "classification": cls, "premium_basis": basis,
            "exposure_amount": exposure, "territory": None, "subcontractor_pct": None}


_GL_ROWS = [_row("Location 001", "91580", _EXEC, "Payroll", "$39,300"),
            _row("Location 001", "91585", _SUB, "Total Cost", "$350,000")]


def _auto_facts(**extra):
    f = {"dec_page_entries": [_EMPLOYEES, _DOC_TERRITORY, _LOC, _COST_NEW],
         "auto_covered_symbols": copy.deepcopy(_SYMBOLS), "auto_vin_schedule": [dict(_VEHICLE)],
         "property_locations": [dict(_LOCATION)], "auto_named_individuals": [
             {"name": "ERIN ROYAL", "role": "named_individual", "territory": "104"}],
         "entity_type": "LLC", "has_auto_coverage": True, "auto_physical_damage_valuation": "ACV"}
    f.update(extra)
    return f


# ═════════════════════════════════════════════════════════════════════════════
# 1. ACORD 137 non-owned group counts and ticks
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("group", ["Partner", "Volunteer", "Employee"])
def test_the_live_137_count_boxes_are_owned_blanks(group):
    """"104" was the Drive Other Car TERRITORY; "0 - 25" is a rating band."""
    f = {**_auto_facts(), "_form_id": "ACORD_137_CO"}
    with ps._schema_context(_schema("ACORD_137_CO")):
        assert ps._deterministic_map(f"Vehicle_NonOwnedGroup_{group}Count_A", f) is None
        assert ps._owned_blank_claim(f"Vehicle_NonOwnedGroup_{group}Count_A", f)


_OWN = "NUMBER OF EMPLOYEES WHO USE THEIR OWN AUTOS"


@pytest.mark.parametrize("label,value,expected", [
    # ISO's non-ownership RATING headcount - not the box's use-own-auto subset.
    ("NUMBER OF EMPLOYEES", "12", None), ("NUMBER OF EMPLOYEES", "0 - 25", None),
    (_OWN, "12", "12"), (_OWN, "12 $ 137.00", "12"), (_OWN, "007", "7"),
    (_OWN, "0 - 25", None), (_OWN, "IF ANY", None), (_OWN, "twelve", None), (_OWN, "", None)])
def test_a_count_is_the_use_own_auto_number_the_auto_dec_states(label, value, expected):
    f = {"dec_page_entries": [_dec(label, value, _AUTO_DEC, "Commercial Auto")]}
    assert ps._nonowned_group_reading(f, "Employee")[0] == expected


def test_a_count_from_another_line_or_another_group_never_lands():
    f = {"dec_page_entries": [_dec(_OWN, "40", "WC SCHEDULE", "Workers Compensation"),
                              _dec(_OWN, "12", _AUTO_DEC, "Commercial Auto")]}
    assert ps._nonowned_group_reading(f, "Employee")[0] == "12"
    assert ps._nonowned_group_reading(f, "Partner") == (None, None)
    two = {"dec_page_entries": [_dec(_OWN, "12", _AUTO_DEC, "Commercial Auto"),
                                _dec(_OWN, "14", _AUTO_DEC, "Commercial Auto")]}
    assert ps._nonowned_group_reading(two, "Employee")[0] is None


@pytest.mark.parametrize("value,expected", [
    ("0 - 25", "Yes"), ("12", "Yes"), ("12 $ 137.00", "Yes"),
    ("0", None), ("NONE", None), ("N/A", None), ("NOT APPLICABLE", None), ("$0", None), ("--", None)])
def test_a_group_the_dec_rates_at_zero_is_never_ticked(value, expected):
    """Review of run 7: "NUMBER OF PARTNERS 0" ticked PARTNERS on an LLC."""
    f = {**_auto_facts(), "_form_id": "ACORD_137_CO",
         "dec_page_entries": [_dec("NUMBER OF PARTNERS", value, _AUTO_DEC, "Commercial Auto")]}
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_PartnerIndicator_A", f) == expected


def test_the_employee_tick_needs_the_symbol_and_the_employee_rating_line():
    f = {**_auto_facts(), "_form_id": "ACORD_137_CO"}
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_EmployeeIndicator_A", f) == "Yes"
    # Partners / volunteers are not the rated group on this schedule.
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_PartnerIndicator_A", f) is SKIP
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_VolunteerIndicator_A", f) is SKIP
    # A legacy UNATTRIBUTED grid never proves liability.
    bare = {**f, "auto_covered_symbols": [1, 7]}
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_EmployeeIndicator_A", bare) is SKIP
    no_line = {**f, "dec_page_entries": [_DOC_TERRITORY]}
    assert ps._resolve_nonowned_group_count("Vehicle_NonOwnedGroup_EmployeeIndicator_A", no_line) is SKIP


# ═════════════════════════════════════════════════════════════════════════════
# 2. An OTHER deductible that only names a printed row
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("desc,misfiled", [
    ("Property Damage Deductible", True), ("PROPERTY DAMAGE", True),
    ("Bodily Injury deductible - per claim", True),
    ("Limited Pollution Coverage - Work Sites", False),
    ("Bodily Injury and Property Damage", False),
    ("Limited Pollution - Property Damage", False), ("", False)])
def test_an_other_deductible_naming_a_printed_row_is_that_row(desc, misfiled):
    schema = _schema("ACORD_126")
    field = "GeneralLiability_OtherDeductibleDescription_A"
    got = ps._misfiled_other_deductibles({field: desc}, schema, {field})
    assert bool(got) is misfiled
    if misfiled:
        assert got[0][1] in ("GeneralLiability_PropertyDamage_DeductibleIndicator_A",
                             "GeneralLiability_BodilyInjury_DeductibleIndicator_A")


def test_a_deterministic_other_description_is_never_second_guessed():
    field = "GeneralLiability_OtherDeductibleDescription_A"
    assert ps._misfiled_other_deductibles({field: "Property Damage"}, _schema("ACORD_126"), set()) == []


def test_the_live_126_other_row_ships_blank():
    """Run 7: desc + amount survived as ai_verified, PD tick refused."""
    schema = _schema("ACORD_126")
    raw = ("LIMITED POLLUTION COVERAGE - WORK SITES. Property Damage Deductible $1,000 "
           "applies to the pollution coverage.")
    mapped, _c = ps.map_facts_to_form(
        {"_form_id": "ACORD_126"}, schema, form_id="ACORD_126", raw_text=raw,
        pre_filled_gpt=_gpt({"GeneralLiability_OtherDeductibleDescription_A": "Property Damage Deductible",
                             "GeneralLiability_OtherDeductibleAmount_A": "1,000"}),
        guard_report=[])
    assert not mapped.get("GeneralLiability_OtherDeductibleDescription_A")
    assert not mapped.get("GeneralLiability_OtherDeductibleAmount_A")
    assert not mapped.get("GeneralLiability_OtherDeductibleIndicator_A")


def test_the_real_other_deductible_still_prints():
    schema = _schema("ACORD_126")
    raw = "LIMITED POLLUTION COVERAGE - WORK SITES DEDUCTIBLE $1,000"
    mapped, _c = ps.map_facts_to_form(
        {"_form_id": "ACORD_126"}, schema, form_id="ACORD_126", raw_text=raw,
        pre_filled_gpt=_gpt({"GeneralLiability_OtherDeductibleDescription_A":
                             "Limited Pollution Coverage - Work Sites",
                             "GeneralLiability_OtherDeductibleAmount_A": "1,000"}),
        guard_report=[])
    assert mapped.get("GeneralLiability_OtherDeductibleDescription_A") == "Limited Pollution Coverage - Work Sites"
    assert "1,000" in str(mapped.get("GeneralLiability_OtherDeductibleAmount_A"))


# ═════════════════════════════════════════════════════════════════════════════
# 3. An OTHER tick that names nothing
# ═════════════════════════════════════════════════════════════════════════════

def test_the_aggregate_other_tick_is_paired_with_the_box_that_names_it():
    pairs = ps._other_tick_partners(_schema("ACORD_126"))
    assert pairs["GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A"] == \
        "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A"
    assert pairs["GeneralLiability_OtherDeductibleIndicator_A"] == "GeneralLiability_OtherDeductibleDescription_A"


def test_every_other_tick_pair_on_every_form_is_a_text_box_on_its_own_row():
    """Read off the forms, pinned: 145 pairs, each partner a /Tx box on the
    tick's own row letter and stem. A new schema that breaks this fails here."""
    total = 0
    for name in sorted(os.listdir(os.path.join(BACKEND, "forms_schemas"))):
        if not name.endswith("_schema.json"):
            continue
        schema = _schema(name[:-len("_schema.json")])
        for tick, partner in ps._other_tick_partners(schema).items():
            total += 1
            assert schema[tick]["ft"] == "/Btn" and schema[partner]["ft"] == "/Tx"
            assert tick.rsplit("_", 1)[1] == partner.rsplit("_", 1)[1]
            assert "OtherThanCollision" not in tick
    assert total == 145


@pytest.mark.parametrize("code,ai_tick,blanked", [
    ("", True, True), ("Per Contract", True, False), ("", False, False)])
def test_an_ai_other_tick_with_an_empty_naming_box_is_removed(code, ai_tick, blanked):
    tick = "GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A"
    partner = "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A"
    mapped = {tick: "Yes", partner: code}
    got = ps._unnamed_other_ticks(mapped, _schema("ACORD_126"), {tick} if ai_tick else set())
    assert bool(got) is blanked


# ═════════════════════════════════════════════════════════════════════════════
# 4. $ PAID TO SUBCONTRACTORS and the TYPE of work sublet
# ═════════════════════════════════════════════════════════════════════════════

def _gl(rows, **extra):
    return {"gl_class_code_schedule": rows, "_form_id": "ACORD_126", **extra}


def test_the_live_126_subcontract_cost_is_the_total_cost_exposure():
    f = _gl(copy.deepcopy(_GL_ROWS))
    with ps._schema_context(_schema("ACORD_126")):
        assert ps._deterministic_map("Contractors_SubcontractorsPaidAmount_A", f) == "$350,000"
        assert ps._deterministic_map(
            "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", f) == _SUB


def test_a_policy_level_copy_is_not_counted_twice():
    rows = copy.deepcopy(_GL_ROWS) + [_row("Location 000", "91585", _SUB, "Total Cost", "$350,000")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) == "$350,000"


def test_two_locations_add_up():
    rows = [_row("001", "91585", _SUB, "Total Cost", "$350,000"),
            _row("002", "91585", _SUB, "Total Cost", "$350,000"),
            _row("002", "91583", "Subcontracted work - other", "Cost", "$50,000")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) == "$750,000"


@pytest.mark.parametrize("rows,expected", [
    ([_row("001", "91585", _SUB, "Total Cost", "IF ANY")], None),
    ([_row("001", "91585", _SUB, "Total Cost", "350")], None),
    ([_row("001", "91585", _SUB, "Total Cost", "$350,000"),
      _row("001", "91585", _SUB, "Total Cost", "$400,000")], None),
    ([_row("001", "91580", _EXEC, "Payroll", "$39,300")], SKIP),
    ([], SKIP), (None, SKIP), ("junk", SKIP), ([None, 7, "x"], SKIP)])
def test_an_unknowable_sum_is_blank_never_partial(rows, expected):
    got = ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows))
    assert got is expected


def test_a_stated_percentage_is_appended_never_computed():
    f = _gl(copy.deepcopy(_GL_ROWS), percent_subcontracted="25%")
    assert ps._resolve_subcontracted_work_description(
        "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", f) == f"{_SUB} - 25%"
    f["percent_subcontracted"] = "most of it"
    assert ps._resolve_subcontracted_work_description(
        "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", f) == _SUB


# ═════════════════════════════════════════════════════════════════════════════
# 5. ACORD 131 Q9 - hired and non-owned
# ═════════════════════════════════════════════════════════════════════════════

_Q9 = "CommercialUmbrellaLineOfBusiness_Question_AAICode_A"
_Q9_EXP = "CommercialUmbrellaLineOfBusiness_HiredAndNonOwnedCoverageProvidedExplanation_J"


def test_the_live_q9_is_yes_from_symbol_1():
    f = {"auto_covered_symbols": copy.deepcopy(_SYMBOLS), "dec_page_entries": [_EMPLOYEES]}
    assert ps._resolve_umbrella_hired_nonowned(_Q9, f) == "Y"
    exp = ps._resolve_umbrella_hired_nonowned(_Q9_EXP, f)
    assert "symbol 1" in exp and "hired and non-owned" in exp


@pytest.mark.parametrize("symbols,expected", [
    ([{"coverage": "liability", "symbols": [8, 9]}], "Y"),
    ([{"coverage": "liability", "symbols": [7]}], SKIP),
    ([{"coverage": "liability", "symbols": [9]}], SKIP),
    ([{"coverage": "liability", "symbols": [1, 19]}], SKIP),
    ([1, 7], SKIP),
    ([], SKIP), (None, SKIP)])
def test_q9_is_derived_only_from_liability_symbols(symbols, expected):
    assert ps._resolve_umbrella_hired_nonowned(_Q9, {"auto_covered_symbols": symbols}) == expected


def test_a_rate_or_a_band_is_never_read_as_a_premium():
    """Run 6 explained Q9 with "(100 $ 185.00)" and "(0 - 25)"."""
    f = {"dec_page_entries": [
        _dec("HIRED AUTO PREMIUM", "100 $ 185.00", "ITEM FOUR HIRED OR BORROWED", "Commercial Auto"),
        _dec("NON-OWNERSHIP PREMIUM", "0 - 25", "ITEM FIVE NON-OWNERSHIP", "Commercial Auto")]}
    assert ps._hired_nonowned_premiums(f) is None
    good = {"dec_page_entries": [
        _dec("HIRED AUTO PREMIUM", "$ 185.00", "ITEM FOUR HIRED OR BORROWED", "Commercial Auto"),
        _dec("NON-OWNERSHIP PREMIUM", "$ 137.00", "ITEM FIVE NON-OWNERSHIP", "Commercial Auto")]}
    assert ps._hired_nonowned_premiums(good) == ("$ 185.00", "$ 137.00")


# ═════════════════════════════════════════════════════════════════════════════
# 6. ACORD 127 VEHICLE TYPE, and the BODY box
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    ("PRIV PASSENGER", "private_passenger"), ("Private Passenger Type", "private_passenger"),
    ("PP", "private_passenger"), ("private_passenger", "private_passenger"),
    ("COML", "commercial"), ("Commercial", "commercial"), ("Special", "special"),
    ("SEDAN", None), ("Pickup", None), ("Private passenger van", None), ("COMM", None),
    ("", None), (None, None), (7, None)])
def test_a_type_phrase_is_a_whole_value(value, expected):
    assert es.vehicle_type_of(value) == expected


def test_the_merge_reads_the_type_from_body_type_and_reports_it():
    f = {"auto_vin_schedule": [dict(_VEHICLE)]}
    got = es._backfill_vehicle_codes_from_text(f, [])
    assert f["auto_vin_schedule"][0]["vehicle_type"] == "private_passenger"
    assert got == ["217772.vehicle_type=private_passenger"]


def test_the_merge_reads_the_type_beside_its_own_vin():
    """The live block layout (raw lines 6018-6036), a second vehicle after it.
    A line exactly halfway between two VINs stays nobody's - the existing rule
    for class and territory, which this reuses."""
    text = "\n".join([
        "[Document page 89]", "LOC: 001 4800 DAHLIA STREET D13", "DENVER CO. 80216-3121",
        "VEH NO 1 TERR: 111 .", "2012 SUBARU OUTBACK SEDAN ID NO 4S4BRCGC9C3217772.",
        "ADDITIONAL INFORMATION:", "COST NEW: 26680 RADIUS: NA USE: NA .", "AGE: LIAB-I PHYS-I .",
        "PRIV PASSENGER - COMM CLASS: 7383 .", "COVERED AUTOS LIABILITY .$ 1,496.00",
        "AUTO MEDICAL PAYMENTS . 35.00", "COMPREHENSIVE ACV 1000 DED . 134.00",
        "COLLISION ACV 1000 DED . 289.00", "TOTAL VEHICLE PREMIUM .$ 2,212.00",
        "VEH NO 2 TERR: 111 .", "2019 FORD F250 ID NO 1FTBF2B61KEC12345.",
        "ADDITIONAL INFORMATION:", "LIGHT TRUCK - SERVICE CLASS: 01499"])
    rows = [dict(_VEHICLE, body_type="SEDAN"),
            {"vin": "1FTBF2B61KEC12345", "body_type": "PICKUP", "class_code": "01499", "territory": "111"}]
    f = {"auto_vin_schedule": rows}
    es._backfill_vehicle_codes_from_text(f, [{"text": text}])
    assert rows[0]["vehicle_type"] == "private_passenger"
    assert "vehicle_type" not in rows[1]


def test_a_heading_that_says_private_passenger_is_not_a_type():
    text = "\n".join(["ID NO 4S4BRCGC9C3217772", "PRIVATE PASSENGER AUTO MEDICAL PAYMENTS"])
    rows = [dict(_VEHICLE, body_type="SEDAN")]
    es._backfill_vehicle_codes_from_text({"auto_vin_schedule": rows}, [{"text": text}])
    assert "vehicle_type" not in rows[0]


@pytest.mark.parametrize("box,expected", [
    ("PrivatePassenger", "Yes"), ("Special", "No"), ("Commercial", "No")])
def test_the_live_127_type_ticks(box, expected):
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    with ps._schema_context(_schema("ACORD_127")):
        assert ps._deterministic_map(f"Vehicle_VehicleType_{box}Indicator_A", f) == expected


def test_the_body_box_never_takes_the_type():
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    with ps._schema_context(_schema("ACORD_127")):
        assert ps._deterministic_map("Vehicle_BodyCode_A", f) is None
        assert ps._owned_blank_claim("Vehicle_BodyCode_A", f)
    sedan = {**f, "auto_vin_schedule": [dict(_VEHICLE, body_type="SEDAN")]}
    assert ps._resolve_vehicle_type_cell("Vehicle_BodyCode_A", sedan) is SKIP
    assert ps._resolve_vehicle_type_cell("Vehicle_VehicleType_PrivatePassengerIndicator_A", sedan) is SKIP
    assert ps._resolve_vehicle_type_cell("Vehicle_VehicleType_PrivatePassengerIndicator_B", f) is SKIP


def test_the_live_127_body_box_ships_blank_and_is_not_reported_as_refused():
    """The schedule door stamped body_type past the owner; a name-shape guard
    then removed it and the cover page listed it as a refused value."""
    report = []
    mapped, _c = ps.map_facts_to_form(_auto_facts(), _schema("ACORD_127"), form_id="ACORD_127",
                                      raw_text="", pre_filled_gpt=_gpt({}), guard_report=report)
    assert not mapped.get("Vehicle_BodyCode_A")
    assert "Vehicle_BodyCode_A" not in {r["field"] for r in report}
    assert mapped.get("Vehicle_VehicleType_PrivatePassengerIndicator_A") == "Yes"


# ═════════════════════════════════════════════════════════════════════════════
# 7. The cover page's "left blank by the AI"
# ═════════════════════════════════════════════════════════════════════════════

def test_an_owned_blank_is_not_left_blank_by_the_ai():
    schema = _schema("ACORD_131")
    owned, asked = "BusinessInformation_EmployeeCount_A", "CommercialUmbrellaLineOfBusiness_Question_ABFCode_A"
    gen = {"ACORD_131": {"mapped": {owned: None, asked: None},
                         "confidence": {owned: "low_confidence", asked: "low_confidence"}, "schema": schema}}
    qa = fq.run_field_qa(gen, merged_facts={"num_employees": "0 - 25"}, confirmations={}, flags={})
    listed = {r["field"] for r in qa["results"] if r["reason_code"] == "not_answered"}
    assert owned not in listed
    assert asked in listed


# ═════════════════════════════════════════════════════════════════════════════
# 8. Policies in this submission
# ═════════════════════════════════════════════════════════════════════════════

_LINES = [
    {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
     "policy_number": "6C7-40-02---26", "premium": "$300.00", "effective_date": "07/15/2025",
     "expiration_date": "07/15/2026"},
    {"line": "Covered Autos Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
     "policy_number": _AUTO_POL, "premium": "$ 1,496.00", "effective_date": "07/15/25",
     "expiration_date": "07/15/26"},
    {"line": "General Liability", "carrier": "EMC Property & Casualty Company", "naic": None,
     "policy_number": "BBC7263 - 26", "premium": "$3,954.00", "effective_date": "07/15/2025",
     "expiration_date": "07/15/2026"},
    {"line": "Property", "carrier": None, "naic": None, "policy_number": None, "premium": None,
     "effective_date": None, "expiration_date": None},
    {"line": "Crime and Fidelity", "carrier": None, "naic": None, "policy_number": None, "premium": None,
     "effective_date": None, "expiration_date": None},
    {"line": "Workers' Compensation", "carrier": None, "naic": None, "policy_number": None,
     "premium": None, "effective_date": None, "expiration_date": None},
]


def test_a_bare_line_name_is_not_a_policy():
    recs = es._build_line_records({"coverage_lines": copy.deepcopy(_LINES)})
    assert sorted(r["line"] for r in recs) == ["auto", "general_liab", "inland_marine"]


def test_sessions_stored_before_the_fix_are_filtered_on_read():
    stored = [{"line": "property", "line_printed": "Property", "granted": False, "printings": {}},
              {"line": "auto", "line_printed": "Covered Autos Liability", "granted": True,
               "printings": {"policy_number": [_AUTO_POL]}, "policy_number": _AUTO_POL}]
    assert [r["line"] for r in uc._line_records({"_line_records": stored})] == ["auto"]


def _header_copied(line):
    return {"line": line, "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "naic": None,
            "policy_number": None, "premium": None, "effective_date": "07/15/2025",
            "expiration_date": "07/15/2026"}


def test_the_run4_shape_the_common_dec_header_copied_onto_no_coverage_lines():
    """Run 4 (136e3c11): the three "No Coverage" lines carried the package's
    carrier and term - copied from the common dec header - and nothing else."""
    lines = [_LINES[0], dict(_LINES[1], carrier="Employers Mutual Casualty Company",
                             effective_date="07/15/2025", expiration_date="07/15/2026"),
             _header_copied("Property"), _header_copied("Crime and Fidelity"),
             _header_copied("Workers' Compensation")]
    recs = es._build_line_records({"coverage_lines": lines})
    assert sorted(r["line"] for r in recs) == ["auto", "inland_marine"]


def test_a_second_carrier_on_an_unnumbered_line_keeps_its_scope():
    lines = [_LINES[1], dict(_header_copied("Workers' Compensation"), carrier="Pinnacol Assurance")]
    recs = es._build_line_records({"coverage_lines": lines})
    assert sorted(r["line"] for r in recs) == ["auto", "workers_comp"]


def test_the_read_side_drops_the_run4_shape_from_a_stored_session():
    auto = {"line": "auto", "line_printed": "COVERED AUTOS LIABILITY", "granted": True,
            "policy_number": _AUTO_POL, "carrier_name": "EMPLOYERS MUTUAL CASUALTY COMPANY",
            "effective_date": "07/15/2025", "expiration_date": "07/15/2026",
            "printings": {"carrier_name": ["EMPLOYERS MUTUAL CASUALTY COMPANY"],
                          "effective_date": ["07/15/2025", "07/15/25"], "expiration_date": ["07/15/2026"]}}
    prop = {"line": "property", "line_printed": "Property", "granted": False, "policy_number": None,
            "carrier_name": "EMPLOYERS MUTUAL CASUALTY COMPANY", "effective_date": "07/15/25",
            "expiration_date": "07/15/2026",
            "printings": {"carrier_name": ["EMPLOYERS MUTUAL CASUALTY COMPANY"],
                          "effective_date": ["07/15/25"], "expiration_date": ["07/15/2026"]}}
    assert [r["line"] for r in uc._line_records({"_line_records": [auto, prop]})] == ["auto"]


@pytest.mark.parametrize("rec,keep", [
    ({"granted": False, "printings": {}}, False),
    ({"granted": False, "printings": {}, "carrier_name": "EMC"}, True),
    ({"granted": False, "printings": {"effective_date": ["07/15/25"]}}, True),
    ({"granted": True, "printings": {}}, True),
    ({}, False), (None, False), ("x", False)])
def test_what_counts_as_an_identity(rec, keep):
    assert es.line_record_has_identity(rec) is keep


# ═════════════════════════════════════════════════════════════════════════════
# Audit of runs 4-7: boxes the facts already decide
# ═════════════════════════════════════════════════════════════════════════════

def test_the_126_general_liability_box():
    lines = copy.deepcopy(_LINES)
    f = {"coverage_lines": lines, "gl_form_type": "Occurrence", "_form_id": "ACORD_126"}
    assert ps._resolve_gl_master_coverage_box("GeneralLiability_CoverageIndicator_A", f) == "Yes"
    assert ps._resolve_gl_master_coverage_box(
        "GeneralLiability_CoverageIndicator_A", {**f, "gl_form_type": "CG 00 01 04 13"}) is SKIP
    assert ps._resolve_gl_master_coverage_box(
        "GeneralLiability_CoverageIndicator_A", {**f, "_form_id": "ACORD_25"}) is SKIP
    ocp = {**f, "coverage_lines": [{"line": "Owners and Contractors Protective Liability",
                                    "premium": "$900.00"}]}
    assert ps._resolve_gl_master_coverage_box("GeneralLiability_CoverageIndicator_A", ocp) is SKIP
    denied = {**f, "coverage_lines": [{"line": "General Liability", "premium": "No Coverage"}]}
    assert ps._resolve_gl_master_coverage_box("GeneralLiability_CoverageIndicator_A", denied) is None


@pytest.mark.parametrize("use", [None, "", "NA", "N/A", "none", "Not applicable"])
@pytest.mark.parametrize("box", ["Pleasure", "Farm", "Commercial", "Retail", "Service", "ForHire", "Other"])
def test_no_stated_use_is_an_owned_blank_never_an_other_use(use, box):
    f = {**_auto_facts(auto_vehicle_use=use), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_use_indicator(f"Vehicle_Use_{box}Indicator_A", f) is None


def test_a_stated_use_still_ticks_one_box():
    f = {**_auto_facts(auto_vehicle_use="Commercial - Retail Delivery"), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_use_indicator("Vehicle_Use_CommercialIndicator_A", f) == "Yes"
    assert ps._resolve_vehicle_use_indicator("Vehicle_Use_RetailIndicator_A", f) == "No"
    assert ps._resolve_vehicle_use_indicator("Vehicle_Use_CommercialIndicator_B", f) is SKIP


def test_named_peril_alternatives_are_owned_when_the_grid_is_captured():
    field = "Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A"
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_coverage_tick(field, f) is None
    liability_only = {**f, "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}],
                      "auto_vin_schedule": [dict(_VEHICLE, comp_symbol=None, coll_symbol=None)]}
    assert ps._resolve_vehicle_coverage_tick(field, liability_only) is None
    none_captured = {**liability_only, "auto_covered_symbols": None}
    assert ps._resolve_vehicle_coverage_tick(field, none_captured) is SKIP


def test_cost_new_is_the_one_vehicle_s_own_figure():
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_A", f) == "26,680"
    na = {**f, "dec_page_entries": [_dec("COST NEW", "NA", _AUTO_DEC, "Commercial Auto")]}
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_A", na) is None
    two = {**f, "auto_vin_schedule": [dict(_VEHICLE), dict(_VEHICLE, vin="1FTBF2B61KEC12345")]}
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_A", two) is SKIP
    own = {**two, "auto_vin_schedule": [dict(_VEHICLE), dict(_VEHICLE, cost_new="$41,800")]}
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_B", own) == "41,800"
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_C", own) is SKIP


def test_the_garaging_address_is_the_record_the_auto_line_points_to():
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    got = {part: ps._resolve_vehicle_garaging_cell(f"Vehicle_PhysicalAddress_{part}_A", f)
           for part in ("LineOne", "CityName", "StateOrProvinceCode", "PostalCode", "CountyName")}
    assert got == {"LineOne": "4800 DAHLIA ST # D13", "CityName": "DENVER",
                   "StateOrProvinceCode": "CO", "PostalCode": "80216-3121", "CountyName": None}
    assert ps._resolve_vehicle_garaging_cell(
        "CommercialVehicleLineOfBusiness_GarageStorageDescription_A", f) == \
        "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CityName_B", f) is SKIP


def test_a_second_garaging_place_leaves_the_address_to_the_document():
    other = _dec("LOC", "002 900 ELM STREET BOULDER CO 80301", _AUTO_DEC, "Commercial Auto")
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    f["dec_page_entries"] = f["dec_page_entries"] + [other]
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CityName_A", f) is SKIP
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CountyName_A", f) is None
    county = {**_auto_facts(), "_form_id": "ACORD_127",
              "property_locations": [dict(_LOCATION, address_county="Denver County")]}
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CountyName_A", county) == "Denver County"


@pytest.mark.parametrize("valuation,acv,agreed", [
    ("ACV", "Yes", "No"), ("Actual Cash Value", "Yes", "No"), ("Agreed Value", "No", "Yes")])
def test_the_pd_valuation_is_the_auto_line_s_own(valuation, acv, agreed):
    f = {**_auto_facts(auto_physical_damage_valuation=valuation), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_valuation_tick("Vehicle_Coverage_ValuationActualCashValueIndicator_A", f) == acv
    assert ps._resolve_vehicle_valuation_tick("Vehicle_Coverage_ValuationAgreedAmountIndicator_A", f) == agreed
    no_pd = {**f, "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}],
             "auto_vin_schedule": [dict(_VEHICLE, comp_symbol=None, coll_symbol=None)]}
    assert ps._resolve_vehicle_valuation_tick(
        "Vehicle_Coverage_ValuationActualCashValueIndicator_A", no_pd) is SKIP


def test_the_131_payroll_box_never_takes_one_class_s_rating_base():
    f = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS), "property_locations": [dict(_LOCATION)],
         "_form_id": "ACORD_131"}
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_A", f) is None
    stated = {**f, "total_payroll": "$250,000"}
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_A", stated) == "$250,000"
    # Rows B-F are subsidiaries (review of run 8): blank on a policy-only
    # package, the document's otherwise. Two premises are still one business.
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_B",
                                              {**stated, "_only_dec_page": True}) is None
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_B", stated) is SKIP
    two = {**stated, "property_locations": [dict(_LOCATION), dict(_LOCATION, location_number="2")]}
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_A", two) == "$250,000"
    assert ps._resolve_business_total_payroll(
        "BusinessInformation_TotalPayrollAmount_A", {**stated, "_form_id": "ACORD_160"}) is SKIP


@pytest.mark.parametrize("value,expected", [
    ("0 - 25", None), ("12", "12"), ("12.0", "12"), ("1,200", "1200"), ("about 12", None)])
def test_the_131_employee_box_takes_one_whole_number(value, expected):
    assert ps._resolve_exposure_count("BusinessInformation_EmployeeCount_A", {"num_employees": value}) == expected


def test_the_131_umbrella_third_limit_is_its_own_pair():
    f = {"dec_page_entries": copy.deepcopy(_UMB), "_form_id": "ACORD_131"}
    assert ps._umbrella_other_limit(f) == ("Personal & Advertising Injury", "$3,000,000")
    assert ps._resolve_umbrella_other_limit("ExcessUmbrella_OtherCoverageDescription_A", f) == \
        "Personal & Advertising Injury"
    assert ps._resolve_umbrella_other_limit("ExcessUmbrella_OtherCoverageLimitAmount_A", f) == "$3,000,000"
    assert ps._resolve_umbrella_other_limit(
        "ExcessUmbrella_OtherCoverageDescription_A", {**f, "_form_id": "ACORD_25"}) is SKIP
    two = {**f, "dec_page_entries": f["dec_page_entries"] + [
        _dec("Products-Completed Operations Limit", "$ 3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS",
             "Commercial Umbrella", _UMB_POL)]}
    assert ps._resolve_umbrella_other_limit("ExcessUmbrella_OtherCoverageDescription_A", two) is None
    assert ps._resolve_umbrella_other_limit("ExcessUmbrella_OtherCoverageDescription_A",
                                            {"_form_id": "ACORD_131"}) is None


def test_the_131_umbrella_third_limit_survives_the_label_echo_guard():
    mapped, _c = ps.map_facts_to_form({"dec_page_entries": copy.deepcopy(_UMB)}, _schema("ACORD_131"),
                                      form_id="ACORD_131", raw_text="", pre_filled_gpt=_gpt({}),
                                      guard_report=[])
    assert mapped.get("ExcessUmbrella_OtherCoverageDescription_A") == "Personal & Advertising Injury"
    assert "3,000,000" in str(mapped.get("ExcessUmbrella_OtherCoverageLimitAmount_A"))


def test_an_ai_label_echo_is_still_refused():
    mapped, _c = ps.map_facts_to_form(
        {}, _schema("ACORD_25"), form_id="ACORD_25", raw_text="General Aggregate Limit $2,000,000",
        pre_filled_gpt=_gpt({"GeneralLiability_OtherCoverageDescription_A": "General Aggregate Limit"}),
        guard_report=[])
    assert not mapped.get("GeneralLiability_OtherCoverageDescription_A")


def test_the_131_underlying_ebl_tick_needs_evidence():
    field = "UnderlyingCoverage_Coverage_EmployeeBenefitsLiabilityIndicator_A"
    f = {"coverage_lines": copy.deepcopy(_LINES), "_form_id": "ACORD_131"}
    assert ps._resolve_uncarried_coverage_part(field, f) is None
    ebl = {**f, "coverage_lines": f["coverage_lines"] + [{"line": "Employee Benefits Liability",
                                                          "premium": "$250.00"}]}
    assert ps._resolve_uncarried_coverage_part(field, ebl) is SKIP


def test_the_125_premises_counts_are_owned_only_when_nothing_states_one():
    field = "BusinessInformation_FullTimeEmployeeCount_A"
    f = {"property_locations": [dict(_LOCATION)], "_form_id": "ACORD_125"}
    with ps._schema_context(_schema("ACORD_125")):
        assert ps._resolve_premises_count_blank(field, f) is None
        stated = {**f, "property_locations": [dict(_LOCATION, full_time_employees="12")]}
        assert ps._resolve_premises_count_blank(field, stated) is SKIP
        assert ps._deterministic_map(field, stated) == "12"
    assert ps._resolve_premises_count_blank(field, {**f, "_form_id": "ACORD_186"}) is SKIP


# ═════════════════════════════════════════════════════════════════════════════
# Adversarial review of this round (19 confirmed findings), each pinned
# ═════════════════════════════════════════════════════════════════════════════

_UMB_DEC = "COMMERCIAL UMBRELLA DECLARATIONS"
_BASE_UMB = [_UMB[0], _UMB[2]]


@pytest.mark.parametrize("label,value", [
    ("Retained Limit", "$ 10,000"), ("Limit of Liability", "$ 5,000,000"),
    ("Required Underlying Auto Liability Limit", "$ 1,000,000"),
    ("Umbrella Liability Limit", "$ 3,000,000"), ("Umbrella Limit", "$ 3,000,000"),
    ("Policy Limit", "$ 3,000,000"), ("Excess Limit", "$ 3,000,000"),
    ("Limits of Liability", "$ 3,000,000"), ("Minimum Underlying Limits", "$ 1,000,000")])
def test_the_umbrella_third_limit_never_restates_the_umbrella_or_its_retention(label, value):
    extra = _dec(label, value, _UMB_DEC, "Commercial Umbrella", _UMB_POL)
    assert ps._umbrella_other_limit({"dec_page_entries": _BASE_UMB + [extra]}) is None
    assert ps._umbrella_other_limit({"dec_page_entries": [extra]}) is None


def test_a_primary_schedule_under_a_declarations_heading_is_not_the_umbrella_s_own():
    extra = _dec("Personal and Advertising Injury Limit", "$ 1,000,000",
                 "EXTENSION OF DECLARATIONS - SCHEDULE OF PRIMARY INSURANCE", "Commercial Umbrella", _UMB_POL)
    assert ps._umbrella_other_limit({"dec_page_entries": _BASE_UMB + [extra]}) is None


def test_a_retained_limit_ships_both_other_boxes_blank():
    entries = _BASE_UMB + [_dec("Retained Limit", "$ 10,000", _UMB_DEC, "Commercial Umbrella", _UMB_POL)]
    mapped, _c = ps.map_facts_to_form({"dec_page_entries": entries}, _schema("ACORD_131"),
                                      form_id="ACORD_131", raw_text="", pre_filled_gpt=_gpt({}),
                                      guard_report=[])
    assert not mapped.get("ExcessUmbrella_OtherCoverageDescription_A")
    assert not mapped.get("ExcessUmbrella_OtherCoverageLimitAmount_A")


def test_a_vin_first_layout_never_hands_one_vehicle_s_type_to_the_next():
    """Each block starts with its VIN and ends with its CLASS line, so vehicle
    1's class line sits one line above vehicle 2's VIN."""
    text = "\n".join(["[Document page 3]", "2012 SUBARU OUTBACK ID NO 4S4BRCGC9C3217772",
                      "COST NEW: 26680", "PRIV PASSENGER - COMM CLASS: 7398",
                      "2019 FORD F150 ID NO 1FTBF2B61KEC12345", "COST NEW: 41800",
                      "LIGHT TRUCK - COMM CLASS: 01499",
                      "2020 RAM 2500 ID NO 3C6UR5CJ0LG123456", "COST NEW: 52000",
                      "HEAVY TRUCK - COMM CLASS: 31499"])
    rows = [{"vin": "4S4BRCGC9C3217772", "body_type": "SEDAN"},
            {"vin": "1FTBF2B61KEC12345", "body_type": "PICKUP"},
            {"vin": "3C6UR5CJ0LG123456", "body_type": "PICKUP"}]
    es._backfill_vehicle_codes_from_text({"auto_vin_schedule": rows}, [{"text": text}])
    assert (rows[0].get("vehicle_type"), rows[0].get("class_code")) == ("private_passenger", "7398")
    assert (rows[1].get("vehicle_type"), rows[1].get("class_code")) == (None, "01499")
    assert (rows[2].get("vehicle_type"), rows[2].get("class_code")) == (None, "31499")


def _backfilled_payroll(value):
    return {"value": value, "confidence": "ai_low", "source": "dec_entry",
            "derivation": {"rule": "dec_entry_backfill", "inputs": ["dec_page_entries"],
                           "entry_label": "Payroll"}}


def test_one_class_s_payroll_backfilled_as_the_total_never_prints():
    f = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS), "property_locations": [dict(_LOCATION)],
         "total_payroll": _backfilled_payroll("$39,300")}
    assert ps._resolve_business_total_payroll(
        "BusinessInformation_TotalPayrollAmount_A", {**f, "_form_id": "ACORD_131"}) is None
    # ACORD 186 prints the same box (review of run 8; the 125 has none).
    with ps._schema_context(_schema("ACORD_186")):
        assert ps._deterministic_map("BusinessInformation_TotalPayrollAmount_A",
                                     {**f, "_form_id": "ACORD_186"}) is None
    stated = {**f, "total_payroll": {"value": "$39,300", "source": "ai"}, "_form_id": "ACORD_131"}
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_A", stated) == "$39,300"
    other = {**f, "total_payroll": _backfilled_payroll("$1,880,000"), "_form_id": "ACORD_131"}
    assert ps._resolve_business_total_payroll("BusinessInformation_TotalPayrollAmount_A", other) == "$1,880,000"


@pytest.mark.parametrize("value,box", [
    ("Stated Amount - the lesser of the stated amount or actual cash value", "StatedAmount"),
    ("ACV / Stated Amount", None), ("Actual Cash Value or Stated Amount", None),
    ("Agreed Value (lesser of agreed value or ACV)", "AgreedAmount"), ("ACV", "ActualCashValue"),
    ("", None), (None, None)])
def test_a_valuation_names_one_method_or_none(value, box):
    assert ps._valuation_box(value) == box


def test_a_fleet_row_without_its_own_pd_symbol_is_left_to_the_document():
    rows = [dict(_VEHICLE, comp_symbol=None, coll_symbol=None, vin=v)
            for v in ("4S4BRCGC9C3217772", "1FTBF2B61KEC12345", "3C6UR5CJ0LG123456")]
    f = {**_auto_facts(auto_vin_schedule=rows), "_form_id": "ACORD_127"}
    for row in "ABC":
        assert ps._resolve_vehicle_valuation_tick(
            f"Vehicle_Coverage_ValuationActualCashValueIndicator_{row}", f) is SKIP


def test_a_fleet_s_garaging_is_left_to_the_document():
    rows = [dict(_VEHICLE), dict(_VEHICLE, vin="1FTBF2B61KEC12345")]
    f = {**_auto_facts(auto_vin_schedule=rows), "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_LineOne_A", f) is SKIP
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CountyName_A", f) is None
    assert ps._resolve_vehicle_garaging_cell(
        "CommercialVehicleLineOfBusiness_GarageStorageDescription_A", f) is SKIP


def test_a_county_the_auto_line_states_prints():
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    f["dec_page_entries"] = f["dec_page_entries"] + [_dec("GARAGING COUNTY", "DENVER", _AUTO_DEC,
                                                          "Commercial Auto")]
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CountyName_A", f) == "Denver"


def test_a_policy_level_total_is_not_counted_twice():
    rows = [_row("001", "91585", _SUB, "Total Cost", "$120,000"),
            _row("002", "91585", _SUB, "Total Cost", "$80,000"),
            _row("000", "91585", _SUB, "Total Cost", "$200,000")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) == "$200,000"


def test_an_unplaced_figure_beside_located_rows_is_unknowable():
    rows = [_row("001", "91585", _SUB, "Total Cost", "$350,000"),
            _row(None, "91585", _SUB, "Total Cost", "$300,000")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) is None


def test_territories_are_separate_exposures():
    rows = [dict(_row(None, "91585", _SUB, "Total Cost", "$50,000"), territory="CO"),
            dict(_row(None, "91585", _SUB, "Total Cost", "$50,000"), territory="WY")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) == "$100,000"


@pytest.mark.parametrize("rows", [
    [_row("001", "91585", _SUB, "Total Cost", "350,000")],
    [_row("001", "91585", _SUB, "Total Cost", "$350,000"), _row("001", "99999", "Mystery", None, "$10,000")],
])
def test_an_unreadable_figure_or_basis_is_blank(rows):
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) is None


def test_basis_wording_variants_are_read_and_protective_classes_are_not_sublet():
    rows = [_row("001", "91585", _SUB, "(C) Total Cost", "$350,000"),
            _row("001", "91583", "Subcontracted work - other", "Cost of Work Sublet", "$50,000"),
            _row("001", "16292", "Owners and Contractors Protective", "Total Cost", "$900,000")]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", _gl(rows)) == "$400,000"


@pytest.mark.parametrize("label", ["SCOL", "SPEC C OF L", "Spec Causes of Loss", "SCL", "F&T", "LSP",
                                   "Specified Causes of Loss"])
def test_a_named_peril_row_in_acord_s_own_codes_keeps_the_box_with_the_document(label):
    f = {**_auto_facts(), "_form_id": "ACORD_127",
         "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]},
                                  {"coverage": label, "symbols": [7]}],
         "auto_vin_schedule": [dict(_VEHICLE, comp_symbol=None, coll_symbol=None)]}
    assert ps._resolve_vehicle_coverage_tick("Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A", f) is SKIP


@pytest.mark.parametrize("tick,partner", [
    ("Policy_Payment_OtherIndicator_A", "Policy_Payment_PaymentScheduleCode_A"),
    ("Policy_Audit_OtherIndicator_A", "Policy_Audit_FrequencyCode_A")])
def test_an_other_tick_beside_an_owned_code_box_is_kept(tick, partner):
    schema = _schema("ACORD_130")
    facts = {"_form_id": "ACORD_130"}
    with ps._schema_context(schema):
        assert ps._owned_blank_claim(partner, facts)
    assert ps._unnamed_other_ticks({tick: "Yes", partner: None}, schema, {tick}, facts) == []
    agg = "GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A"
    assert ps._unnamed_other_ticks({agg: "Yes"}, _schema("ACORD_126"), {agg}, {"_form_id": "ACORD_126"})


@pytest.mark.parametrize("value,box,expected", [
    ("SERVICE", "Service", "Yes"), ("SERVICE", "Commercial", "No"),
    ("NA", "Other", None), ("LIAB-I", "Other", None)])
def test_the_auto_dec_s_own_use_cell_is_read_when_the_fact_is_empty(value, box, expected):
    f = {**_auto_facts(), "_form_id": "ACORD_127"}
    f["dec_page_entries"] = f["dec_page_entries"] + [_dec("USE", value, _AUTO_DEC, "Commercial Auto")]
    assert ps._resolve_vehicle_use_indicator(f"Vehicle_Use_{box}Indicator_A", f) == expected


# ═════════════════════════════════════════════════════════════════════════════
# Breaking it on purpose: every new owner, every malformed fact shape
# ═════════════════════════════════════════════════════════════════════════════

_NEW_OWNERS = ("_resolve_nonowned_group_count", "_resolve_subcontracted_cost",
               "_resolve_subcontracted_work_description", "_resolve_vehicle_type_cell",
               "_resolve_vehicle_cost_new", "_resolve_vehicle_garaging_cell",
               "_resolve_vehicle_valuation_tick", "_resolve_gl_master_coverage_box",
               "_resolve_business_total_payroll", "_resolve_premises_count_blank",
               "_resolve_vehicle_use_indicator", "_resolve_umbrella_other_limit")
_JUNK = [None, "", "x", 0, 7, [], {}, [None, 3, "a"], {"value": None}, {"value": "junk"},
         {"value": [{"a": 1}]}, [{"vin": None}], [{"premium_basis": None, "exposure_amount": {}}]]
_FIELDS = ("Vehicle_NonOwnedGroup_PartnerCount_A", "Vehicle_NonOwnedGroup_EmployeeIndicator_A",
           "Contractors_SubcontractorsPaidAmount_A",
           "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A",
           "Vehicle_VehicleType_PrivatePassengerIndicator_A", "Vehicle_BodyCode_A",
           "Vehicle_CostNewAmount_A", "Vehicle_PhysicalAddress_CountyName_A",
           "CommercialVehicleLineOfBusiness_GarageStorageDescription_A",
           "Vehicle_Coverage_ValuationActualCashValueIndicator_A", "GeneralLiability_CoverageIndicator_A",
           "BusinessInformation_TotalPayrollAmount_A", "BusinessInformation_FullTimeEmployeeCount_A",
           "Vehicle_Use_OtherIndicator_A", "ExcessUmbrella_OtherCoverageDescription_A",
           "BusinessInformation_ForeignGrossSalesAmount_A")
_KEYS = ("dec_page_entries", "auto_vin_schedule", "auto_covered_symbols", "gl_class_code_schedule",
         "property_locations", "coverage_lines", "auto_vehicle_use", "total_payroll",
         "auto_physical_damage_valuation", "gl_form_type", "auto_garaging_addresses")


@pytest.mark.parametrize("junk", _JUNK, ids=[repr(j)[:20] for j in _JUNK])
@pytest.mark.parametrize("form_id", ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_137_CO"])
def test_no_new_owner_raises_on_malformed_facts(junk, form_id):
    facts = {k: copy.deepcopy(junk) for k in _KEYS}
    facts["_form_id"] = form_id
    for owner in _NEW_OWNERS:
        for field in _FIELDS:
            out = getattr(ps, owner)(field, facts)
            assert out is SKIP or out is None or isinstance(out, str), (owner, field, out)


def test_each_new_owner_claims_only_its_own_boxes():
    """No accidental claims: across all 17 schemas, with the live facts, a new
    owner answers only for the family its own pattern names."""
    families = {
        "_resolve_nonowned_group_count": "Vehicle_NonOwnedGroup_",
        "_resolve_subcontracted_cost": "Contractors_SubcontractorsPaidAmount_",
        "_resolve_subcontracted_work_description": "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontracted",
        "_resolve_vehicle_type_cell": ("Vehicle_VehicleType_", "Vehicle_BodyCode_"),
        "_resolve_vehicle_cost_new": "Vehicle_CostNewAmount_",
        "_resolve_vehicle_garaging_cell": ("Vehicle_PhysicalAddress_",
                                           "CommercialVehicleLineOfBusiness_GarageStorage"),
        "_resolve_vehicle_valuation_tick": "Vehicle_Coverage_Valuation",
        "_resolve_gl_master_coverage_box": "GeneralLiability_CoverageIndicator_A",
        # Widened on purpose in run 8 to the payroll box's two neighbours.
        "_resolve_business_total_payroll": ("BusinessInformation_TotalPayrollAmount_",
                                            "BusinessInformation_AnnualGrossReceiptsAmount_",
                                            "BusinessInformation_ForeignGrossSalesAmount_"),
        "_resolve_premises_count_blank": ("BusinessInformation_FullTimeEmployeeCount_",
                                          "BusinessInformation_PartTimeEmployeeCount_"),
    }
    base = {**_auto_facts(), "gl_class_code_schedule": copy.deepcopy(_GL_ROWS),
            "coverage_lines": copy.deepcopy(_LINES), "gl_form_type": "Occurrence",
            "total_payroll": "$250,000"}
    for name in sorted(os.listdir(os.path.join(BACKEND, "forms_schemas"))):
        if not name.endswith("_schema.json"):
            continue
        form_id = name[:-len("_schema.json")]
        schema = _schema(form_id)
        facts = {**base, "_form_id": form_id}
        with ps._schema_context(schema):
            for owner, prefix in families.items():
                for field in schema:
                    if getattr(ps, owner)(field, facts) is not SKIP:
                        assert field.startswith(prefix), (form_id, owner, field)


def test_every_new_owner_is_registered():
    for owner in ("_resolve_nonowned_group_count", "_resolve_subcontracted_cost",
                  "_resolve_vehicle_type_cell", "_resolve_vehicle_use_indicator",
                  "_resolve_vehicle_cost_new", "_resolve_vehicle_garaging_cell",
                  "_resolve_gl_master_coverage_box", "_resolve_business_total_payroll",
                  "_resolve_premises_count_blank"):
        assert owner in ps._AUTHORITATIVE_BLANK_RESOLVERS
