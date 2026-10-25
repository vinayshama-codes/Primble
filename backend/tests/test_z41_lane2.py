"""Z41 lane 2 (25 Oct 2026, live Choice Electric f575160b): stamping fixes.

Each test drives the real resolvers with the live package's shapes.
"""
import json
from pathlib import Path

import pytest

import services.pdf_service as ps

SCHEMAS = Path(__file__).resolve().parent.parent / "forms_schemas"


def _claim(date, paid, reserved, line, desc, no):
    return {"date": date, "claim_date": date, "paid": paid, "reserved_amount": reserved,
            "line_of_business": line, "description": desc, "claim_number": no}


LOSSES = [
    _claim("03/13/2025", "12000", "0", "Business Auto",
           "V009 | 2017 Chevrolet Express G2500 | Third-party vehicle property damage", "A1"),
    _claim("08/20/2025", "4500", "34500", "Business Auto",
           "V016 | 2014 Ford F150 SuperCrew | Alleged third-party bodily injury", "A2"),
    _claim("11/02/2025", "8400", "0", "Business Auto", "V011 | 2023 Chevrolet | Collision damage", "A3"),
    _claim("04/16/2025", "10500", "0", "Commercial Package",
           "Inland marine | Tool theft from service jobsite", "P1"),
    _claim("05/06/2025", "17500", "26000", "Commercial Package",
           "General liability | Third-party slip and fall at worksite", "P2"),
    _claim("06/28/2025", "24000", "30000", "Commercial Package",
           "Property | Prem 001, Bldg 002 | Hail damage", "P3"),
    _claim("02/19/2025", "18000", "8200", "Workers' Compensation",
           "5190 | Field electrician | Shoulder strain", "W1"),
    _claim("10/11/2025", "5200", "0", "Cyber", "Cyber incident | Malware response", "C1"),
    _claim("04/10/2025", "10000", "52000", "Employment Practices Liability",
           "Alleged wrongful termination", "E1"),
    # loss-run SUMMARY rows: never claims
    {"date": None, "paid": "151700", "reserved_amount": "150700",
     "line_of_business": "All lines", "description": "All lines", "claim_number": None},
    {"date": None, "paid": "4200", "reserved_amount": "0", "line_of_business": "All lines",
     "description": "2023-2024 | All lines | 1 | 4200 | 0 | 0 | 4200", "claim_number": None},
]
PAID_CLAIMS = 12000 + 4500 + 8400 + 10500 + 17500 + 24000 + 18000 + 5200 + 10000


def _schema(fid):
    return json.loads((SCHEMAS / f"{fid}_schema.json").read_text())


# ── 1. TOTAL LOSSES counts claims, never the loss run's summary rows ────────
def test_total_losses_skips_summary_rows():
    facts = {"_form_id": "ACORD_125", "loss_history": LOSSES}
    assert ps._resolve_loss_history_summary("LossHistory_TotalAmount_A", facts) == f"${PAID_CLAIMS:,}"


# ── 6. the 131 lists liability claims; the 130 prints no claim rows ────────
def test_umbrella_loss_grid_is_liability_only():
    kept = ps._form_loss_rows(LOSSES[:9], {"_form_id": "ACORD_131__excess"})
    assert [r["claim_number"] for r in kept] == ["A1", "A2", "P2"]
    # every other form keeps the whole list
    assert len(ps._form_loss_rows(LOSSES[:9], {"_form_id": "ACORD_125"})) == 9


@pytest.mark.parametrize("row,want", [
    ({"line_of_business": "General Liability", "description": "Completed work damaged equipment"}, True),
    ({"line_of_business": "Workers' Compensation", "description": "Employers liability suit"}, True),
    ({"line_of_business": "Workers' Compensation", "description": "Ankle injury"}, False),
    ({"line_of_business": "Business Auto", "description": "Comprehensive - windshield glass"}, False),
    ({"line_of_business": "Commercial Package", "description": "Property | water damage"}, False),
    ({"line_of_business": "", "description": ""}, False),
])
def test_is_liability_loss(row, want):
    assert ps.is_liability_loss(row) is want


def test_acord130_loss_boxes_are_owned_blanks():
    facts = {"_form_id": "ACORD_130", "loss_history": LOSSES}
    for f in ("LossHistory_PaidAmount_A", "LossHistory_ReservedAmount_B", "LossHistory_ClaimCount_A"):
        assert ps._resolve_wc_period_loss_box(f, facts) is None
    assert ps._resolve_wc_period_loss_box("LossHistory_PaidAmount_A",
                                          {"_form_id": "ACORD_125"}) is ps._SCHED_SKIP


# ── 2. losses past the 125 grid print on ACORD 101; the 125 box points there ─
NARRATIVE = "Account Overview: " + "Choice Electric LLC is a Denver electrical contractor. " * 12


def _pkg(form_id):
    return {"_form_id": form_id, "loss_history": LOSSES,
            "_package_form_ids": ["ACORD_101", "ACORD_125", "ACORD_130", "ACORD_131"],
            "additional_remarks_text": NARRATIVE}


def test_loss_overflow_reaches_acord101_in_full():
    blocks = ps._acord101_blocks(_pkg("ACORD_101"))
    text = "\n".join(t for _f, t in blocks)
    assert "LOSS HISTORY (continued from ACORD 125)" in text
    cap = ps._acord125_loss_capacity()
    assert cap == 3
    for r in LOSSES[cap:9]:
        assert r["claim_number"] in text
    assert "All lines" not in text
    assert text.count("Account Overview:") == 1          # the narrative, once


def test_acord125_remarks_box_is_a_pointer_when_101_attached():
    facts = _pkg("ACORD_125")
    ps._set_schema_context(_schema("ACORD_125"))
    out = ps._resolve_loss_overflow_remark("CommercialPolicy_RemarkText_A", facts)
    assert "ACORD 101" in out and "Account Overview" not in out
    assert "6 additional loss(es) (of 9)" in out


def test_without_101_the_box_keeps_the_losses():
    facts = {**_pkg("ACORD_125"), "_package_form_ids": ["ACORD_125"],
             "additional_remarks_text": "Seasonal lease at location 2."}
    ps._set_schema_context(_schema("ACORD_125"))
    out = ps._resolve_loss_overflow_remark("CommercialPolicy_RemarkText_A", facts)
    assert out.startswith("Seasonal lease at location 2.") and ps._LOSS_OVERFLOW_MARKER in out


def test_state_rating_remark_never_takes_the_narrative():
    facts = _pkg("ACORD_130")
    assert ps._resolve_remark_text("WorkersCompensation_RateState_RemarkText_A", facts) is None
    assert ps._resolve_loss_overflow_remark(
        "WorkersCompensation_RateState_RemarkText_A", facts) is ps._SCHED_SKIP
    # a line's own remarks box never repeats a long narrative the 101 prints
    assert ps._resolve_remark_text("CommercialUmbrellaLineOfBusiness_RemarkText_A",
                                   _pkg("ACORD_131")) is None
    # a short remark still prints where it fits
    short = {**_pkg("ACORD_131"), "additional_remarks_text": "Seasonal lease."}
    assert ps._resolve_remark_text("CommercialUmbrellaLineOfBusiness_RemarkText_A",
                                   short) == "Seasonal lease."


# ── 3. ACORD 101's carrier follows the 125's page one ───────────────────────
def test_acord101_carrier_follows_page_one():
    facts = {"_form_id": "ACORD_101", "carrier_is_current_policy": True,
             "carrier_name": "AMERISURE INSURANCE COMPANY"}
    assert ps._resolve_page_one_receiving_carrier("Insurer_FullName_A", facts) is None
    # not marked current -> steps aside, as on the 125
    assert ps._resolve_page_one_receiving_carrier(
        "Insurer_FullName_A", {"_form_id": "ACORD_101"}) is ps._SCHED_SKIP


# ── 7. one premises, two buildings: one location row ────────────────────────
def test_one_premises_prints_one_location_row():
    m = {"Location_ProducerIdentifier_A": "1", "Location_ProducerIdentifier_B": "1"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_130") == ["Location_ProducerIdentifier_B"]
    m = {"CommercialStructure_Location_ProducerIdentifier_A": "1",
         "CommercialStructure_Location_ProducerIdentifier_B": "1"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_131__excess")
    assert m["CommercialStructure_Location_ProducerIdentifier_B"] is None
    # another street under the same number stays; another number stays
    m = {"Location_ProducerIdentifier_A": "1", "Location_PhysicalAddress_LineOne_A": "1 Main St",
         "Location_ProducerIdentifier_B": "1", "Location_PhysicalAddress_LineOne_B": "9 Oak Ave",
         "Location_ProducerIdentifier_C": "2"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_130") == []
    # the 125 / 140 building rows are not this guard's
    m = {"CommercialStructure_Location_ProducerIdentifier_A": "1",
         "CommercialStructure_Location_ProducerIdentifier_B": "1"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_125") == []


# ── 8 / 9. AI values in the wrong kind of box ───────────────────────────────
def test_misplaced_ai_values_refused():
    facts = {"percent_subcontracted": {"value": "10", "source": "producer"}}
    mapped = {
        "Contractors_SubcontractorsPaidAmount_A": "$10",
        "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A":
            '"Commercial Package | Amerisure | SIM-PKG-004 | 09/15/2025 | Closed | 22500"',
        "GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A": "Yes",
        "WorkersCompensationStateCoverage_Other_CoverageDescription_B":
            "Bodily Injury by Accident: $1,000,000 each accident",
        "AthleticTeam_SportDescription_A": '"THEY HAVE A SMAL SPONSORSHIP WITH BRONCOS."',
        "Contractors_SubcontractorsCostAmount_A": "$350,000",
    }
    gfs = set(mapped)
    refused = ps._refuse_misplaced_ai_values(mapped, facts, gfs)
    assert set(refused) == {
        "Contractors_SubcontractorsPaidAmount_A",
        "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A",
        "GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A",
        "WorkersCompensationStateCoverage_Other_CoverageDescription_B",
    }
    assert mapped["AthleticTeam_SportDescription_A"] == "THEY HAVE A SMAL SPONSORSHIP WITH BRONCOS."
    assert mapped["Contractors_SubcontractorsCostAmount_A"] == "$350,000"


def test_misplaced_guard_leaves_resolver_values_alone():
    facts = {"percent_subcontracted": "10"}
    mapped = {"Contractors_SubcontractorsPaidAmount_A": "$10",
              "GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A": "Yes"}
    assert ps._refuse_misplaced_ai_values(mapped, facts, set()) == {}
    assert mapped["Contractors_SubcontractorsPaidAmount_A"] == "$10"


def test_aggregate_tick_kept_when_a_document_states_it():
    from services.scoped_evidence import DOCS_KEY, Doc
    facts = {DOCS_KEY: [Doc("gl.pdf", None, "General aggregate limit applies per project.")]}
    mapped = {"GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A": "Yes"}
    assert ps._refuse_misplaced_ai_values(mapped, facts, set(mapped)) == {}


# ── 11. a typed headcount reaches the one-premises 125 row ─────────────────
def test_one_premises_full_time_falls_back_to_headcount():
    rows = [{"premises_number": "001", "building_number": "001", "location_number": "1"},
            {"premises_number": "001", "building_number": "002", "location_number": "1"}]
    facts = {"_form_id": "ACORD_125", "property_locations": rows,
             "num_employees": {"value": "28", "source": "producer"}}
    assert ps._one_premises_twin_value("full_time_employees", facts) == "28"
    assert ps._one_premises_twin_value("part_time_employees", facts) is None


# ── 15. our vehicle-exposure sum is a calculated value ──────────────────────
def test_max_vehicle_exposure_is_calculated():
    facts = {"auto_vin_schedule": [{"cost_new": "$40,000"}, {"cost_new": "15,806"}]}
    box = "CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_A"
    assert ps.prints_a_calculated_value("ACORD_127", box, "$55,806", facts)
    assert not ps.prints_a_calculated_value("ACORD_127", box, "$90,000", facts)


# ── 13. fleet garaging and a dec's one cause of loss repeat down the column ─
def test_repeat_prone_values_kept_on_real_rows():
    from services.scoped_evidence import DOCS_KEY, Doc
    facts = {"auto_vin_schedule": [{"make": "CHEVROLET"}, {"make": "GMC"}],
             DOCS_KEY: [Doc("prop.pdf", None, "CAUSES OF LOSS: SPECIAL")]}
    assert ps._repeat_prone_value_kept("Vehicle_PhysicalAddress_CityName_B", "Denver", facts)
    # a row past the schedule is no vehicle
    assert not ps._repeat_prone_value_kept("Vehicle_PhysicalAddress_CityName_C", "Denver", facts)
    # the street line is not exempt (the territory-code refusal stands)
    assert not ps._repeat_prone_value_kept("Vehicle_PhysicalAddress_LineOne_B", "111", facts)
    mapped = {"CommercialProperty_Premises_SubjectOfInsuranceCode_G": "Building"}
    assert ps._repeat_prone_value_kept(
        "CommercialProperty_Premises_CauseOfLossCode_G", "Special", facts, mapped)
    assert not ps._repeat_prone_value_kept(
        "CommercialProperty_Premises_CauseOfLossCode_D", "Special", facts, mapped)
    assert not ps._repeat_prone_value_kept(
        "CommercialProperty_Premises_CauseOfLossCode_G", "Broad", facts, mapped)


# ── 16. vehicles past ACORD 127's rows continue on ACORD 101 ─────────────────
def test_vehicle_overflow_reaches_acord101():
    cap = ps._acord127_vehicle_capacity()
    assert cap == 4
    rows = [{"year": "2017", "make": "CHEVROLET", "model": f"G{n}", "cost_new": "31,940"}
            for n in range(1, 8)]
    facts = {"_form_id": "ACORD_101", "auto_vin_schedule": rows,
             "_package_form_ids": ["ACORD_101", "ACORD_127"]}
    text = "\n".join(t for _f, t in ps._acord101_blocks(facts))
    assert "VEHICLE SCHEDULE (continued from ACORD 127) - 3 of 7" in text
    assert "Vehicle 5 | 2017 CHEVROLET G5 | Cost new 31,940" in text
    assert ps._vehicle_continuation({"auto_vin_schedule": rows[:4]}) is None
    # not in the package -> nothing
    facts["_package_form_ids"] = ["ACORD_101", "ACORD_125"]
    assert "VEHICLE SCHEDULE" not in "\n".join(t for _f, t in ps._acord101_blocks(facts))


# ── 17. ACORD 137 Business Auto page: hired physical damage deductibles ──────
HIRED_TABLE = """[Table - page 14 - NAMED INSURED:]
ST | Coverage | Cost of Hire | Limit | Deductible | Premium
CO | OTHER THAN PUBLIC TRANSPORTATION - HIRED AUTOS - LIABILITY | | 1,000,000 | | 93
CO | WITH DRIVERS - COMPREHENSIVE - HIRED AUTOS - PHYSICAL DAMAGE - OTHER THAN COLLISION | | 75000 | 1,0 0 0 | 250
CO | WITH DRIVERS - HIRED AUTOS - PHYSICAL DAMAGE - COLLISION | | 75000 | 1,0 0 0 | 250
[End table]"""


def test_hired_pd_deductibles_read_from_the_schedule_table():
    assert ps.hired_physical_damage_deductibles(HIRED_TABLE) == {"comp": "$1,000", "coll": "$1,000"}
    two = HIRED_TABLE.replace("COLLISION | | 75000 | 1,0 0 0", "COLLISION | | 75000 | 500")
    two += "\nCO | HIRED AUTOS - PHYSICAL DAMAGE - COLLISION | | 75000 | 1,000 | 250"
    assert "coll" not in ps.hired_physical_damage_deductibles(two + "\nST | Coverage | Cost of Hire | Limit | Deductible | Premium\nCO | HIRED AUTOS - PHYSICAL DAMAGE - COLLISION | | 1 | 250 | 1")
    from services.scoped_evidence import DOCS_KEY, Doc
    facts = {"_form_id": "ACORD_137_CO", DOCS_KEY: [Doc("auto.pdf", None, HIRED_TABLE)]}
    assert ps._resolve_state_auto_grid("Vehicle_Collision_DeductibleAmount_A", facts) == "$1,000"
    assert ps._resolve_state_auto_grid("Vehicle_Coverage_ComprehensiveDeductibleIndicator_A", facts) == "Yes"
    assert ps._resolve_hired_pd_box("Vehicle_Collision_DeductibleAmount_A",
                                    {"_form_id": "ACORD_137_CO"}) is ps._SCHED_SKIP


# ── 18. ACORD 28's property limit is the premises' whole property limit ──────
def test_evidence_property_limit_sums_the_premises():
    pc = {"sections": [
        {"premises": "1", "coverages": [{"kind": "building", "limit": "$798,556"},
                                        {"kind": "bpp", "limit": "$73,008"},
                                        {"kind": "bi", "limit": "$1,000,000"}]},
        {"premises": "001", "coverages": [{"kind": "building", "limit": "$421,714"},
                                          {"kind": "bpp", "limit": "$73,008"},
                                          {"kind": "stock", "limit": "$75,000"}]}]}
    facts = {"_form_id": "ACORD_28", "_property_coverages": pc}
    assert ps._resolve_evidence_property_limit(
        "CommercialPropertyCoverage_Property_LimitAmount_A", facts) == "$1,441,286"
    # two premises, or a coverage with no amount -> steps aside
    pc2 = {"sections": pc["sections"][:1] + [{**pc["sections"][1], "premises": "2"}]}
    assert ps.evidence_property_limit({"_property_coverages": pc2}) is None
    pc3 = {"sections": [{"premises": "1", "coverages": [{"kind": "building", "limit": "SEE SCHEDULE"}]}]}
    assert ps.evidence_property_limit({"_property_coverages": pc3}) is None
    assert ps._resolve_evidence_property_limit(
        "CommercialPropertyCoverage_Property_LimitAmount_A",
        {**facts, "_form_id": "ACORD_140"}) is ps._SCHED_SKIP


# ── 11 (gap). an answer to the headcount re-stamps the one-premises box ─────
def test_twin_reads_include_the_fallback_fact():
    rows = [{"premises_number": "001", "building_number": "001", "location_number": "1"},
            {"premises_number": "001", "building_number": "002", "location_number": "1"}]
    facts = {"_form_id": "ACORD_125", "property_locations": rows}
    reads = ps.premises_twin_reads("BusinessInformation_FullTimeEmployeeCount_A", facts, "ACORD_125")
    assert reads == {"num_employees_full_time", "num_employees"}
    from services.arq_service import _premises_twin_reads
    assert "num_employees" in _premises_twin_reads(
        "BusinessInformation_FullTimeEmployeeCount_A", facts, "ACORD_125")


# ── "(000 OMITTED)": a schedule printed in thousands ─────────────────────────
def test_thousands_omitted_schedule_is_scaled():
    from services.thousands_omitted import scale_thousands_omitted
    text = ("Item 7 of the Declarations to include:\nPOLICY LIMITS (000 OMITTED) COVERAGE COMPANY\n"
            "Policy Period: 5,000 EACH OCCURRENCE UMBRELLA LIABILITY AMERISURE\n"
            "5,000 GENERAL AGGREGATE\n")
    facts = {"underlying_policies": [
        {"line": "Umbrella Liability", "limit": "5,000 EACH OCCURRENCE; 5,000 GENERAL AGGREGATE"},
        {"line": "General Liability", "limit": "$1,000,000"},
        {"line": "Auto", "limit": "2,000 EACH ACCIDENT"}]}           # not printed under the header
    doc = {"text": text, "facts": {"underlying_policies": [{"limit": "5,000 EACH OCCURRENCE"}]}}
    assert scale_thousands_omitted(facts, [doc]) == ["underlying_policies"]
    rows = facts["underlying_policies"]
    assert rows[0]["limit"] == "$5,000,000 EACH OCCURRENCE; $5,000,000 GENERAL AGGREGATE"
    assert rows[1]["limit"] == "$1,000,000" and rows[2]["limit"] == "2,000 EACH ACCIDENT"
    assert doc["facts"]["underlying_policies"][0]["limit"] == "$5,000,000 EACH OCCURRENCE"
    # no header anywhere -> nothing moves
    plain = {"underlying_policies": [{"limit": "5,000 EACH OCCURRENCE"}]}
    assert scale_thousands_omitted(plain, [{"text": "5,000 EACH OCCURRENCE"}]) == []
