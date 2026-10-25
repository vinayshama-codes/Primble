"""Z42 review C (25 Oct 2026): adversarial review of Z41 lane 2's stamping fixes.

Each test is an edge case that failed on the lane 2 code (see 25sepChanges.md).
"""
import json
from pathlib import Path

import services.pdf_service as ps
from services.scoped_evidence import DOCS_KEY, Doc

SCHEMAS = Path(__file__).resolve().parent.parent / "forms_schemas"


def _schema(fid):
    return json.loads((SCHEMAS / f"{fid}_schema.json").read_text())


# ── 1. EBL written with GL is a part of the GL policy, never its own 101 row ─
def _prior_facts(ebl_carrier="AMERISURE INSURANCE COMPANY", ebl_no=None, gl_no=None):
    def rec(line, carrier, premium, no=None):
        return {"line": line, "carrier": carrier, "premium": premium, "policy_no": no,
                "effective": "01/01/2025", "expiration": "01/01/2026"}
    return [("GeneralLiability", "2025", rec("General Liability", "AMERISURE INSURANCE COMPANY",
                                              "$16,818", gl_no)),
            ("OtherLine", "2025", rec("Employee Benefits Liability", ebl_carrier, "$425", ebl_no)),
            ("OtherLine", "2025", rec("Cyber", "ACE American Insurance Company", "$4,162"))]


def _unplaced(entries):
    grid = {("GeneralLiability", 0): entries[0][2]}
    return [e.get("line") for e in ps._prior_grid_unplaced(grid, entries[1:], ["2025"], ["2025"])]


def test_ebl_written_with_gl_is_not_its_own_expiring_policy():
    assert _unplaced(_prior_facts()) == ["Cyber"]
    # another company's EBL is a policy of its own
    assert "Employee Benefits Liability" in _unplaced(_prior_facts(ebl_carrier="Hartford"))
    # two printed numbers that differ are two policies
    assert "Employee Benefits Liability" in _unplaced(_prior_facts(ebl_no="EBL-1", gl_no="GL-9"))


# ── 2. a remark prints once per form, never in a premises / question box ─────
def test_short_remark_prints_once_per_form():
    facts = {"_form_id": "ACORD_137_CO", "additional_remarks_text": "Seasonal lease."}
    assert ps._resolve_remark_text("CommercialVehicleLineOfBusiness_RemarkText_A", facts) == "Seasonal lease."
    for f in ("CommercialVehicleLineOfBusiness_RemarkText_B",
              "CommercialVehicleLineOfBusiness_RemarkText_C"):
        assert ps._resolve_remark_text(f, facts) is None
    assert ps._resolve_remark_text("CommercialProperty_Premises_RemarkText_A",
                                   {**facts, "_form_id": "ACORD_140"}) is None
    assert ps._resolve_remark_text("Underwriting_Question_RemarkText_A",
                                   {**facts, "_form_id": "ACORD_133"}) is None
    assert ps._resolve_remark_text("CommercialPropertyLineOfBusiness_RemarkText_A",
                                   {**facts, "_form_id": "ACORD_140"}) == "Seasonal lease."


def test_acord101_does_not_repeat_a_remark_the_125_prints():
    pkg = ["ACORD_101", "ACORD_125"]
    short = {"_form_id": "ACORD_101", "_package_form_ids": pkg,
             "additional_remarks_text": "Seasonal lease at location 2."}
    assert "Seasonal lease" not in "\n".join(t for _f, t in ps._acord101_blocks(short))
    # no 125 in the package -> the 101 prints it
    alone = {**short, "_package_form_ids": ["ACORD_101", "ACORD_126"]}
    assert "Seasonal lease" in "\n".join(t for _f, t in ps._acord101_blocks(alone))
    # a long remark: the 125 points, the 101 prints it once
    long = {**short, "additional_remarks_text": "Account overview. " * 30}
    assert "\n".join(t for _f, t in ps._acord101_blocks(long)).count("Account overview.") == 30
    assert ps._resolve_remark_text("CommercialPolicy_RemarkText_A",
                                   {**long, "_form_id": "ACORD_125"}) == ps._REMARKS_ON_101_POINTER


def test_acord101_form_number_names_the_127_it_continues():
    rows = [{"year": "2017", "make": "CHEVROLET", "model": f"G{n}"} for n in range(6)]
    facts = {"_form_id": "ACORD_101", "auto_vin_schedule": rows,
             "_package_form_ids": ["ACORD_101", "ACORD_127"]}
    assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", facts) == "127"


# ── 3. the umbrella's loss grid: liability claims by line, not by wording ──
def test_liability_claims_by_line():
    L = ps.is_liability_loss
    assert L({"line_of_business": "GL", "description": "Customer slipped"})
    assert L({"line_of_business": "Umbrella", "description": ""})
    assert L({"line_of_business": "General Liability",
              "description": "Property damage to a customer's vehicle"})
    assert L({"line_of_business": "Commercial Auto", "description": "Rear-end, other driver hurt"})
    assert not L({"line_of_business": "Workers Compensation and Employers Liability",
                  "description": "Shoulder strain"})
    assert L({"line_of_business": "Workers Compensation and Employers Liability",
              "description": "Employers liability suit by a spouse"})
    assert not L({"line_of_business": "Commercial Package", "description": "Property | Hail damage"})
    assert not L({"line_of_business": "", "description": ""})


# ── 4. one location: same company folds; another ZIP stays ──────────────────
def test_location_rows_same_company_fold_other_zip_stays():
    m = {"CommercialStructure_Location_ProducerIdentifier_A": "1",
         "CommercialStructure_Location_FullName_A": "Choice Electric LLC",
         "CommercialStructure_Location_ProducerIdentifier_B": "1",
         "CommercialStructure_Location_FullName_B": "CHOICE ELECTRIC, LLC"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_131")
    m = {"CommercialStructure_Location_ProducerIdentifier_A": "1",
         "CommercialStructure_Location_FullName_A": "Choice Electric LLC",
         "CommercialStructure_Location_ProducerIdentifier_B": "1",
         "CommercialStructure_Location_FullName_B": "Berger Holdings LLC"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_131") == []
    m = {"Location_ProducerIdentifier_A": "1", "Location_PhysicalAddress_PostalCode_A": "80221",
         "Location_ProducerIdentifier_B": "1", "Location_PhysicalAddress_PostalCode_B": "80903"}
    assert ps._dedupe_repeated_location_rows(m, "ACORD_130") == []


# ── 5. 126 guards: a stated dollar amount; the ISO per-project wording ──────
def test_percent_guard_spares_a_dollar_amount_the_documents_print():
    facts = {"coinsurance_percentage": "100%",
             DOCS_KEY: [Doc("auto.pdf", None, "Comprehensive deductible $100")]}
    mapped = {"Vehicle_Coverage_ComprehensiveDeductibleAmount_A": "$100"}
    assert ps._refuse_misplaced_ai_values(mapped, facts, set(mapped)) == {}
    facts[DOCS_KEY] = [Doc("auto.pdf", None, "Comprehensive deductible $100,000")]
    assert ps._refuse_misplaced_ai_values(dict(mapped), facts, set(mapped))


def test_aggregate_tick_reads_iso_endorsement_and_colon_wording():
    for text in ("CG 25 03 Designated Construction Project(s) General Aggregate Limit",
                 "General Aggregate Limit applies per: Project"):
        facts = {DOCS_KEY: [Doc("gl.pdf", None, text)]}
        mapped = {"GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A": "Yes"}
        assert ps._refuse_misplaced_ai_values(mapped, facts, set(mapped)) == {}, text
    facts = {DOCS_KEY: [Doc("gl.pdf", None, "General aggregate $2,000,000")]}
    mapped = {"GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A": "Yes"}
    assert ps._refuse_misplaced_ai_values(mapped, facts, set(mapped))


# ── 6. a fleet garaged at several places: row A's city is not exempt ────────
def test_garaging_repeat_not_exempt_with_several_garaging_places():
    rows = [{"make": "CHEVROLET"}, {"make": "GMC"}]
    one = {"auto_vin_schedule": rows, "auto_garaging_addresses": ["4800 Dahlia St Denver CO"]}
    assert ps._repeat_prone_value_kept("Vehicle_PhysicalAddress_CityName_B", "Denver", one)
    two = {**one, "auto_garaging_addresses": ["4800 Dahlia St Denver CO", "12 Main St Aurora CO"]}
    assert not ps._repeat_prone_value_kept("Vehicle_PhysicalAddress_CityName_B", "Denver", two)


# ── 7. the 101 vehicle block skips rows that state nothing ──────────────────
def test_vehicle_continuation_skips_empty_rows():
    rows = [{"make": f"M{n}"} for n in range(4)] + [{}, {"year": "2021", "make": "RAM"}]
    text = ps._vehicle_continuation({"auto_vin_schedule": rows})
    assert "Description not shown" not in text and "Vehicle 6 | 2021 RAM" in text
    assert "1 of 6" in text


# ── 8. hired PD: two deductibles for one coverage -> an owned blank ─────────
def test_hired_pd_two_deductibles_is_an_owned_blank():
    table = ("ST | Coverage | Cost of Hire | Limit | Deductible | Premium\n"
             "CO | WITH DRIVERS - HIRED AUTOS - PHYSICAL DAMAGE - COLLISION | | 75000 | 500 | 250\n"
             "CO | WITHOUT DRIVERS - HIRED AUTOS - PHYSICAL DAMAGE - COLLISION | | 75000 | 1,000 | 90\n"
             "[End table]")
    facts = {"_form_id": "ACORD_137_CO", DOCS_KEY: [Doc("auto.pdf", None, table)]}
    assert ps._resolve_hired_pd_box("Vehicle_Collision_DeductibleAmount_A", facts) is None
    assert ps._resolve_hired_pd_box("Vehicle_Coverage_CollisionIndicator_A", facts) is None
    assert ps._resolve_hired_pd_box("Vehicle_Comprehensive_DeductibleAmount_A", facts) is ps._SCHED_SKIP


# ── 9. ACORD 28: a blanket limit is never summed ────────────────────────────
def test_evidence_property_limit_steps_aside_on_blanket():
    pc = {"sections": [{"premises": "1", "coverages": [
        {"kind": "building", "limit": "$2,000,000", "blanket": "Blanket 1"},
        {"kind": "bpp", "limit": "$2,000,000", "blanket": "Blanket 1"}]}]}
    assert ps.evidence_property_limit({"_property_coverages": pc}) is None


# ── 10. thousands omitted: another document's full-dollar amount is not scaled
def test_thousands_omitted_cross_document_amount_not_scaled():
    from services.thousands_omitted import scale_thousands_omitted
    excess = {"text": "POLICY LIMITS (000 OMITTED)\n5,000 EACH OCCURRENCE\n",
              "facts": {"underlying_policies": [{"limit": "5,000 EACH OCCURRENCE"}]}}
    other = {"text": "Medical expense 5,000 any one person",
             "facts": {"underlying_policies": [{"limit": "5,000 medical expense"}]}}
    merged = {"underlying_policies": [{"limit": "5,000 EACH OCCURRENCE"}]}
    assert scale_thousands_omitted(merged, [excess, other]) == []
    assert merged["underlying_policies"][0]["limit"] == "5,000 EACH OCCURRENCE"
    assert excess["facts"]["underlying_policies"][0]["limit"] == "$5,000,000 EACH OCCURRENCE"
    assert other["facts"]["underlying_policies"][0]["limit"] == "5,000 medical expense"


# ── 11. a typed full-time count is not the headcount's to re-stamp ──────────
def test_twin_fallback_only_while_the_twin_is_blank():
    rows = [{"premises_number": "001", "building_number": "001", "location_number": "1"}]
    facts = {"_form_id": "ACORD_125", "property_locations": rows,
             "num_employees_full_time": {"value": "20", "source": "producer"}}
    reads = ps.premises_twin_reads("BusinessInformation_FullTimeEmployeeCount_A", facts, "ACORD_125")
    assert reads == {"num_employees_full_time"}
