"""A table row owns its own cells in Field QA (14 Oct 2026, live run f83757cf).

The download review listed "ACORD 125: Number of full time employees shows "90" but
the source value is "100". Fix: Re-confirm" and the same for the premises' "Office and
electrical shop" against the business description. 90 is building 1's full-time staff
(the location table) and 100 the company's employees; re-confirming would have written
a building's count over the company's. `authoritative_expected_value` - the one door
for "what should this box hold?" - now asks the schedule resolver too.
"""
import json
import os

import services.pdf_service as ps
from services.field_qa import run_field_qa

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _person(value):
    return {"value": value, "source": "producer"}


FACTS = {
    "applicant_name": "Choice Electric LLC",
    "num_employees": _person("100"),
    "operations_description": _person("Commercial electrical contractor - new construction and service work"),
    "property_locations": [
        {"location_number": "1", "building_number": "001", "address_line1": "4800 Washington St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80216",
         "operations_description": "Office and electrical shop", "full_time_employees": "90",
         "part_time_employees": "10"},
        {"location_number": "1", "building_number": "002", "address_line1": "4800 Washington St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80216",
         "operations_description": "Material and equipment storage"},
    ],
}


def _generated():
    schema = _schema("ACORD_125")
    m, c = ps.map_facts_to_form(dict(FACTS), schema, "ACORD_125", "", allow_llm=False)
    return {"ACORD_125": {"schema": schema, "field_state": m, "mapped": m, "confidence": c}}


def test_the_location_rows_own_cells_are_not_compared_with_package_facts():
    gen = _generated()
    fs = gen["ACORD_125"]["field_state"]
    assert fs.get("BusinessInformation_FullTimeEmployeeCount_A") == "90"
    assert fs.get("BuildingOccupancy_OperationsDescription_A") == "Office and electrical shop"
    out = run_field_qa(gen, dict(FACTS))
    flagged = {r["field"] for r in out.get("results") or [] if r.get("reason_code") == "value_mismatch"}
    assert "BusinessInformation_FullTimeEmployeeCount_A" not in flagged
    assert "BuildingOccupancy_OperationsDescription_A" not in flagged


def test_a_cell_that_disagrees_with_its_own_row_is_still_flagged():
    gen = _generated()
    gen["ACORD_125"]["field_state"]["BusinessInformation_FullTimeEmployeeCount_A"] = "75"
    gen["ACORD_125"]["mapped"] = gen["ACORD_125"]["field_state"]
    out = run_field_qa(gen, dict(FACTS))
    rows = [r for r in out.get("results") or [] if r.get("reason_code") == "value_mismatch"
            and r["field"] == "BusinessInformation_FullTimeEmployeeCount_A"]
    assert rows and rows[0]["expected"] == "90"


def test_the_owner_door_reads_the_row():
    schema = _schema("ACORD_125")
    owner = ps.authoritative_expected_value("ACORD_125", "BusinessInformation_FullTimeEmployeeCount_A", FACTS, schema)
    assert owner == "90"
    # a page-one box no table owns is untouched
    assert ps.authoritative_expected_value("ACORD_125", "NamedInsured_FullName_A", FACTS, schema) is ps._AUTH_UNOWNED
