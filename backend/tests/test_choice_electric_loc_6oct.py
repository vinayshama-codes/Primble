"""Choice Electric (stored session ca93ed8f, 5 Oct 2026) - the property /
location-table / ACORD 140 fixes of 6 Oct 2026 (implementer "LOC").

Client items #14, #23, #27 (140 part) and the location-table data loss:
  * a premises / building heading ("Prem. #: 001 Bldg #: 001") is never a
    street address - it is the row's LOC # / BLDG #, and the buildings of one
    printed premises share its LOC #;
  * a vehicle garaging address is never a premises;
  * the location table carries the COPE columns its card asks for, and a save
    MERGES into the stored rows (nothing the table has no column for is lost,
    LOC # typed on a form survives, `locations` is re-derived);
  * the ACORD 140 guards no longer delete building 2's own values, and the
    completeness gate no longer demands what a guard removed.

The fixture is the session's own per-document extraction (redacted documents),
the producer's pre-form answers and the values the shared gap fill wrote into
ACORD 140 on that run.
"""
import json
import os
from functools import lru_cache

import pytest

from services import extraction_service as es
from services import pdf_service as ps
from services import schedule_capture as sc

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "choice_electric_loc_6oct.json")
_SCHEMAS = os.path.join(os.path.dirname(_HERE), "forms_schemas")


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _merged():
    docs = [d for d in _fixture()["docs"] if not d.get("excluded")]
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags


def _schema(form_id: str) -> dict:
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _rows(facts):
    rows = facts.get("property_locations")
    if isinstance(rows, dict):
        rows = rows.get("value")
    return rows


# ── 1. Premises headings, numbering ──────────────────────────────────────────

@pytest.mark.parametrize("text, prem, bldg, street", [
    ("Prem. #: 001 Bldg #: 001", "001", "001", ""),
    ("Loc 2 Bldg 3", "2", "3", ""),
    ("Location No. 4", "4", "", ""),
    ("Premises #2, Building #4", "2", "4", ""),
    ("LOC # 1 / BLDG # 2", "1", "2", ""),
    ("Building 2", "", "2", ""),
    ("Loc 2 - 4800 Dahlia St, Denver, CO 80216", "2", "", "4800 Dahlia St, Denver, CO 80216"),
])
def test_a_premises_heading_is_read_as_numbers(text, prem, bldg, street):
    got = es.premises_label_parts(text)
    assert got == {"premises": prem, "building": bldg, "street": street}


@pytest.mark.parametrize("text", [
    "4800 Dahlia St, Denver, CO 80216", "DENVER, CO 80221", "Location", "1 Location Way",
    "Location 1 - Main Office", "Premises Ave 12", "", None,
])
def test_a_street_or_a_bare_word_is_not_a_heading(text):
    assert es.premises_label_parts(text) is None


def test_loc_number_shares_the_printed_premises_and_keeps_legacy_order():
    rows = [{"premises_number": "001"}, {"premises_number": "001"}, {"premises_number": "003"}]
    es.assign_location_numbers(rows)
    assert [r["location_number"] for r in rows] == ["1", "1", "3"]
    # No printed numbers anywhere: 1, 2, 3 - exactly as before.
    plain = [{}, {}, {}]
    es.assign_location_numbers(plain)
    assert [r["location_number"] for r in plain] == ["1", "2", "3"]
    # A typed / earlier LOC # is kept; a new row takes the next free number.
    mixed = [{"location_number": "2"}, {}, {"premises_number": "1"}]
    es.assign_location_numbers(mixed)
    assert [r["location_number"] for r in mixed] == ["2", "3", "1"]


def test_location_list_uses_the_address_else_the_heading():
    rows = [{"address": "4800 Dahlia St, Denver, CO"}, {"address": "", "premises_label": "Prem 1 Bldg 2"},
            {"address": None}]
    assert es.location_list_from_rows(rows) == ["4800 Dahlia St, Denver, CO", "Prem 1 Bldg 2"]


# ── 2. Consolidation ─────────────────────────────────────────────────────────

def _consolidate(facts, docs=None):
    facts = json.loads(json.dumps(facts))
    es._consolidate_property_locations(facts, "", docs=docs)
    return facts


def test_choice_electric_shape_is_one_premises_two_buildings_and_no_garaging():
    facts = _consolidate({
        "property_locations": [
            {"address": "Prem. #: 001 Bldg #: 001", "building_number": "001",
             "construction_type": "FRAME", "building_value": "$798,556", "bpp_value": "$73,008"},
            {"address": "Prem. #: 001 Bldg #: 002", "building_number": "002",
             "construction_type": "NON-COMBUSTIBLE - LIGHT STEEL", "building_value": "$421,714"},
        ],
        "locations": ["DENVER, CO 80221"],
        "auto_garaging_addresses": ["DENVER, CO 80221"],
    })
    rows = _rows(facts)
    assert len(rows) == 2
    assert [r["location_number"] for r in rows] == ["1", "1"]
    assert [r["building_number"] for r in rows] == ["001", "002"]
    assert all(not r.get("address_line1") for r in rows)          # no heading in the street box
    assert facts["locations"] == ["Prem. #: 001 Bldg #: 001", "Prem. #: 001 Bldg #: 002"]


def test_garaging_is_ruled_out_even_when_no_premises_row_carries_data():
    # The 5 Oct "beside a schedule with data" rule cannot fire here: nothing
    # carries data. The garaging list decides on its own evidence.
    facts = _consolidate({
        "property_locations": [{"address": "1450 Lantern Ct, Boulder, CO 80301"}],
        "locations": ["DENVER, CO 80221"],
        "auto_garaging_addresses": ["DENVER, CO 80221"],
    })
    assert [r.get("address_line1") for r in _rows(facts)] == ["1450 Lantern Ct"]


def test_garaging_is_kept_when_it_is_the_only_location():
    facts = _consolidate({"locations": ["4800 Dahlia St, Denver, CO 80216"],
                          "auto_garaging_addresses": ["4800 Dahlia St, Denver, CO 80216"]})
    assert len(_rows(facts)) == 1


def test_an_address_only_auto_documents_print_is_not_a_premises():
    docs = [
        {"facts": {"locations": ["77 Depot Rd, Golden, CO 80401"],
                   "auto_vin_schedule": [{"vin": "1FTFW1ET5DFC10312"}]}, "flags": {}},
        {"facts": {"property_locations": [{"address": "1450 Lantern Ct, Boulder, CO 80301"}]},
         "flags": {"has_property_coverage": True}},
    ]
    facts = _consolidate({
        "property_locations": [{"address": "1450 Lantern Ct, Boulder, CO 80301"}],
        "locations": ["77 Depot Rd, Golden, CO 80401"],
    }, docs=docs)
    assert [r.get("address_line1") for r in _rows(facts)] == ["1450 Lantern Ct"]
    # ...but a premises with its own data at the garaging address stays.
    facts = _consolidate({
        "property_locations": [{"address": "1450 Lantern Ct, Boulder, CO 80301"},
                               {"address": "77 Depot Rd, Golden, CO 80401", "building_value": "$400,000"}],
        "auto_garaging_addresses": ["77 Depot Rd, Golden, CO 80401"],
    })
    assert len(_rows(facts)) == 2


def test_a_heading_in_front_of_a_street_is_peeled_off_and_buildings_share_the_street():
    facts = _consolidate({"property_locations": [
        {"address": "Loc 1 - 100 Main St, Austin, TX 78701", "building_value": "$1,000,000"},
        {"address": "Prem 1 Bldg 2", "building_value": "$250,000"},
    ]})
    rows = _rows(facts)
    assert [r["location_number"] for r in rows] == ["1", "1"]
    assert [r.get("address_line1") for r in rows] == ["100 Main St", "100 Main St"]
    assert rows[1]["building_number"] == "2"


def test_two_mentions_of_one_heading_fold_and_street_rows_number_as_before():
    facts = _consolidate({"property_locations": [
        {"address": "Prem 1 Bldg 1", "building_value": "$100,000"},
        {"address": "Prem. #: 001 Bldg #: 001", "construction_type": "Frame"},
    ]})
    rows = _rows(facts)
    assert len(rows) == 1 and rows[0]["building_value"] == "$100,000"
    assert rows[0]["construction_type"] == "Frame"
    plain = _consolidate({"locations": ["100 Main St, Austin, TX 78701", "9 Elm St, Austin, TX 78702"]})
    assert [r["location_number"] for r in _rows(plain)] == ["1", "2"]


def test_the_stored_package_merges_to_one_premises_with_two_buildings():
    mf, _ = _merged()
    rows = _rows(mf)
    assert len(rows) == 2
    assert [r["location_number"] for r in rows] == ["1", "1"]
    assert [r["building_number"] for r in rows] == ["001", "002"]
    assert [r["construction_type"] for r in rows] == ["FRAME", "NON-COMBUSTIBLE - LIGHT STEEL"]
    assert not any("DENVER" in str(r.get("address") or "").upper() for r in rows)
    assert not any(str(r.get("address_line1") or "").startswith("Prem") for r in rows)


# ── 3. The location table ────────────────────────────────────────────────────

def test_the_table_has_the_columns_its_cope_card_asks_for():
    cols = {c["key"]: c for c in sc.SCHEDULE_DEFS["property_locations"]["columns"]}
    # The agency's numbering is producer-only; the COPE / values are the
    # insured's to give per building (the questionnaire asked them before).
    for key in ("location_number", "building_number"):
        assert cols[key]["producer_only"] is True
    for key in ("construction_type", "year_built", "building_value", "bpp_value"):
        assert cols[key]["producer_only"] is False
    assert cols["construction_type"].get("options")
    # A header-less import still lands addresses in the first column.
    assert sc.SCHEDULE_DEFS["property_locations"]["columns"][0]["key"] == "address_line1"


def test_the_client_is_still_asked_construction_and_year():
    import asyncio
    from services import arq_service as A
    gen = {}
    for fid in ("ACORD_125", "ACORD_140"):
        s = _schema(fid)
        gen[fid] = {"schema": s, "confidence": {k: "missing_required" for k in s},
                    "field_state": {k: "" for k in s}, "client_filled_fields": []}
    facts = {"applicant_name": "X LLC", "property_locations": [
        {"address": "100 Main St, Austin, TX 78701", "address_line1": "100 Main St", "location_number": "1"},
        {"address": "9 Elm St, Austin, TX 78702", "address_line1": "9 Elm St", "location_number": "2"}]}
    orig = A._humanize_fields_with_openai
    A._humanize_fields_with_openai = lambda *a, **k: asyncio.sleep(0)
    try:
        out = asyncio.run(A.generate_arq_questions(facts, {"has_property_coverage": True}, gen, [], []))
    finally:
        A._humanize_fields_with_openai = orig
    qs = out.get("questions") if isinstance(out, dict) else out
    client = [q for q in qs if q.get("audience") == "client"]
    table = next(q for q in client if q.get("field_name") == "schedule::property_locations")
    keys = {c["key"]: c.get("producer_only") for c in table["columns"]}
    assert keys["construction_type"] is False and keys["year_built"] is False
    # Build 24 (22 Oct 2026): on 2+ buildings the table asks construction and
    # year PER BUILDING, so the package-level scalar ("What is your building
    # mainly made of?") is no longer asked a second time beside it.
    names = {q.get("field_name") for q in client}
    assert not names & {"construction_type", "year_built"}


def test_each_new_column_binds_a_live_box():
    from tests.test_schedule_capture import test_every_schedule_column_binds_to_a_live_acord_field
    test_every_schedule_column_binds_to_a_live_acord_field()


def test_rows_carry_a_hidden_identity_that_never_reaches_the_facts():
    facts = {"property_locations": [{"address_line1": "1 A St", "location_id": "L7", "county": "Adams"}]}
    rows = sc.rows_from_facts("property_locations", facts)
    assert rows[0][sc.ROW_ID_KEY] == "L7" and "county" not in rows[0]
    clean, _ = sc.validate_rows("property_locations", rows)
    assert clean[0][sc.ROW_ID_KEY] == "L7"
    assert sc.ROW_ID_KEY not in sc.rows_for_facts("property_locations", clean)[0]
    # A row the person kept is never dropped as blank, whatever they can see.
    kept, _ = sc.validate_rows("property_locations", [{sc.ROW_ID_KEY: "L9"}, {}])
    assert len(kept) == 1


def _stored():
    return [
        {"location_id": "L1", "location_number": "1", "building_number": "001",
         "address": None, "premises_label": "Prem 1 Bldg 1", "county": "Adams",
         "ownership": "Owner", "is_owner": True, "annual_revenue": "$2,000,000",
         "full_time_employees": "12", "construction_type": "FRAME", "building_value": "$798,556"},
        {"location_id": "L2", "location_number": "1", "building_number": "002",
         "address": None, "county": "Adams", "construction_type": "NON-COMBUSTIBLE",
         "building_value": "$421,714"},
        {"location_id": "L3", "location_number": "2", "address": "DENVER, CO 80221",
         "address_line1": "DENVER", "address_state": "CO", "address_zip": "80221"},
    ]


def test_a_save_merges_typed_cells_and_keeps_every_field_without_a_column():
    stored = _stored()
    table = sc.rows_from_facts("property_locations", {"property_locations": stored})
    table = table[:2]                                           # the garaging row deleted
    table[0]["address_line1"] = "107 Heatherwood Drive"
    table[0]["address_city"] = "Littleton"
    clean, _ = sc.validate_rows("property_locations", table)
    out = sc.merge_saved_rows("property_locations", stored, clean, source="producer")
    assert len(out) == 2
    assert out[0]["county"] == "Adams" and out[0]["is_owner"] is True
    assert out[0]["annual_revenue"] == "$2,000,000" and out[0]["full_time_employees"] == "12"
    assert out[0]["location_number"] == "1" and out[0]["building_number"] == "001"
    assert out[0]["address"] == "107 Heatherwood Drive, Littleton"
    assert out[1]["construction_type"] == "NON-COMBUSTIBLE" and out[1]["location_id"] == "L2"


def test_a_new_row_gets_an_id_and_an_older_copy_matches_by_street():
    stored = _stored()
    typed = [{"address_line1": "DENVER", "address_state": "CO", "address_zip": "80221"},  # no id
             {"address_line1": "9 Elm St", "address_city": "Austin"}]
    clean, _ = sc.validate_rows("property_locations", typed)
    out = sc.merge_saved_rows("property_locations", stored, clean, source="producer")
    assert out[0]["location_id"] == "L3"                           # matched by its street
    assert out[1]["location_id"] == "L4" and out[1]["address"] == "9 Elm St, Austin"


def test_a_client_save_never_writes_the_agencys_columns():
    stored = _stored()[:1]
    client_copy = [{sc.ROW_ID_KEY: "L1", "address_line1": "107 Heatherwood Drive",
                    "construction_type": "FRAME", "building_value": "$798,556"}]
    clean, _ = sc.validate_rows("property_locations", client_copy)
    out = sc.merge_saved_rows("property_locations", stored, clean, source="client_arq")
    assert out[0]["location_number"] == "1" and out[0]["building_number"] == "001"
    assert out[0]["construction_type"] == "FRAME" and out[0]["building_value"] == "$798,556"
    assert out[0]["address_line1"] == "107 Heatherwood Drive"


def test_the_one_write_door_renumbers_resyncs_and_marks():
    from services.arq_service import _write_schedule_rows
    facts = {"property_locations": _stored(),
             "locations": ["Prem 1 Bldg 1", "x", "DENVER, CO 80221"]}
    table = sc.rows_from_facts("property_locations", facts)[:2]
    clean, _ = sc.validate_rows("property_locations", table)
    before, emptied = _write_schedule_rows(facts, "property_locations", clean, "producer")
    assert len(_rows(before)) == 3 and len(_rows(facts)) == 2
    assert facts["locations"] == es.location_list_from_rows(facts["property_locations"])
    assert sc.human_rows(facts, "property_locations")[1] == "producer"
    assert emptied == []
    _, emptied = _write_schedule_rows(facts, "property_locations", [], "producer")
    assert set(emptied) == {"property_locations", "locations"}


def _form(field_state, conf):
    schema = {f: {} for f in (
        "CommercialStructure_Location_ProducerIdentifier_A",
        "CommercialStructure_Location_ProducerIdentifier_B",
        "CommercialStructure_PhysicalAddress_LineOne_A",
        "CommercialStructure_PhysicalAddress_LineOne_B")}
    return {"ACORD_125": {"schema": schema, "field_state": dict(field_state),
                          "confidence": dict(conf), "client_filled_fields": []}}


def test_a_table_save_keeps_the_loc_number_the_producer_typed_on_the_form():
    from services.arq_service import _restamp_schedule_into_forms, _write_schedule_rows
    facts = {"property_locations": [
        {"location_id": "L1", "address": "Prem 1 Bldg 1"},
        {"location_id": "L2", "address": "Prem 1 Bldg 2"}]}
    gen = _form({"CommercialStructure_Location_ProducerIdentifier_A": "1",
                 "CommercialStructure_Location_ProducerIdentifier_B": "1"},
                {"CommercialStructure_Location_ProducerIdentifier_A": "producer",
                 "CommercialStructure_Location_ProducerIdentifier_B": "producer"})
    table = sc.rows_from_facts("property_locations", facts)
    table[0]["address_line1"] = "107 Heatherwood Drive"
    clean, _ = sc.validate_rows("property_locations", table)
    before, _ = _write_schedule_rows(facts, "property_locations", clean, "producer")
    _restamp_schedule_into_forms(gen, "property_locations", facts,
                                 facts_before=before, provenance="producer")
    fs, conf = gen["ACORD_125"]["field_state"], gen["ACORD_125"]["confidence"]
    assert fs["CommercialStructure_Location_ProducerIdentifier_A"] == "1"
    assert fs["CommercialStructure_Location_ProducerIdentifier_B"] == "1"
    assert fs["CommercialStructure_PhysicalAddress_LineOne_A"] == "107 Heatherwood Drive"
    assert conf["CommercialStructure_PhysicalAddress_LineOne_A"] == "producer"


def test_a_client_save_never_overwrites_a_producer_box_but_a_moved_column_does():
    from services.arq_service import _restamp_schedule_into_forms
    before = {"property_locations": [{"location_number": "1", "address_line1": "1 A St"}]}
    after = {"property_locations": [{"location_number": "4", "address_line1": "1 A St"}]}
    shown = {"CommercialStructure_Location_ProducerIdentifier_A": "1"}
    gen = _form(shown, {"CommercialStructure_Location_ProducerIdentifier_A": "producer"})
    _restamp_schedule_into_forms(gen, "property_locations", after, facts_before=before,
                                 provenance="client_arq")
    assert gen["ACORD_125"]["field_state"]["CommercialStructure_Location_ProducerIdentifier_A"] == "1"
    gen = _form(shown, {"CommercialStructure_Location_ProducerIdentifier_A": "producer"})
    _restamp_schedule_into_forms(gen, "property_locations", after, facts_before=before,
                                 provenance="producer")
    assert gen["ACORD_125"]["field_state"]["CommercialStructure_Location_ProducerIdentifier_A"] == "4"


def test_a_location_answer_re_marks_the_persons_table():
    from services.premises_interest import write_location_answer, PREMISES_INTEREST_FACT
    facts = {"property_locations": [{"address": "1 A St"}, {"address": "2 B St"}]}
    sc.mark_human_rows(facts, "property_locations", "producer")
    assert write_location_answer(facts, PREMISES_INTEREST_FACT, 2, "Tenant")
    rows, src = sc.human_rows(facts, "property_locations")
    assert rows is not None and src == "producer"


def test_a_stale_locations_copy_raises_no_count_or_address_warning():
    from services.cross_form_validator import _check_location_address_reconciliation
    facts = {"locations": ["Prem 1 Bldg 1", "Prem 1 Bldg 2", "DENVER, CO 80221"],
             "property_locations": [{"address_line1": "107 Heatherwood Drive"},
                                    {"address_line1": "107 Heatherwood Drive"}]}
    assert _check_location_address_reconciliation(
        facts, {"has_property_coverage": True}, {"ACORD_125", "ACORD_140"}) == []


# ── 4. ACORD 140 guards ──────────────────────────────────────────────────────

@pytest.mark.parametrize("label, value, want", [
    ("Prem #: 001 Bldg #: 002", "LIMIT $421,714", "limit"),
    ("Prem #: 001 Bldg #: 002", "DEDUCTIBLE $5,000", "deductible"),
    ("Prem #: 001 Bldg #: 002", "$75,000", None),
    ("Total Premium", "$10,692", "premium"),
    ("Policy No. 4471", "$500", None),
    ("Prem", "$500", "premium"),
])
def test_an_entry_is_classed_by_its_own_word_and_a_heading_is_an_identifier(label, value, want):
    assert ps._entry_amount_category(label, value) == want


def test_the_meaning_gate_keeps_property_limits_and_still_refuses_a_premium():
    facts = {"dec_page_entries": [
        {"label": "Prem #: 001 Bldg #: 002", "value": "LIMIT $421,714"},
        {"label": "Prem #: 001 Bldg #: 002", "value": "DEDUCTIBLE $5,000"},
        {"label": "Total Premium", "value": "$10,692"}]}
    schema = _schema("ACORD_140")
    mapped = {"CommercialProperty_Premises_LimitAmount_I": "$421,714",
              "CommercialProperty_Premises_DeductibleAmount_I": "$5,000",
              "CommercialProperty_Premises_LimitAmount_J": "$10,692"}
    ps._enforce_numeric_meaning_gate(mapped, schema, facts, set(mapped))
    assert mapped["CommercialProperty_Premises_LimitAmount_I"] == "$421,714"
    assert mapped["CommercialProperty_Premises_DeductibleAmount_I"] == "$5,000"
    assert mapped["CommercialProperty_Premises_LimitAmount_J"] is None


def _two_buildings():
    return {"property_locations": [{"location_number": "1", "building_number": "1",
                                    "construction_type": "FRAME"},
                                   {"location_number": "1", "building_number": "2",
                                    "construction_type": "FRAME"}]}


def test_guard_2_keeps_a_real_second_buildings_cope_and_its_own_value():
    facts = _two_buildings()
    schema = {f: {} for f in ("CommercialStructure_BuiltYear_A", "CommercialStructure_BuiltYear_B",
                              "Construction_ConstructionCode_A", "Construction_ConstructionCode_B",
                              "Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B")}
    mapped = {"CommercialStructure_BuiltYear_A": "2001", "CommercialStructure_BuiltYear_B": "2001",
              "Construction_ConstructionCode_A": "FRAME", "Construction_ConstructionCode_B": "FRAME",
              "Construction_RoofMaterialCode_A": "Metal", "Construction_RoofMaterialCode_B": "Metal"}
    ps._enforce_post_fill_guards(mapped, schema, facts, set(mapped))
    assert all(mapped[f] for f in mapped)
    # One building: row B is no building, and a copy of row A there still goes.
    one = {"property_locations": facts["property_locations"][:1]}
    mapped2 = dict(mapped)
    ps._enforce_post_fill_guards(mapped2, schema, one, set(mapped2))
    assert mapped2["Construction_RoofMaterialCode_B"] is None


def test_a_building_row_is_anchored_by_its_loc_bldg_or_street_never_by_area():
    schema = _schema("ACORD_140")
    mapped = {"CommercialStructure_Location_ProducerIdentifier_B": "1",
              "Construction_ConstructionCode_B": "NON-COMBUSTIBLE - LIGHT STEEL",
              "Construction_RoofMaterialCode_B": "Metal"}
    gfs = {"Construction_ConstructionCode_B", "Construction_RoofMaterialCode_B"}
    assert ps._unanchored_schedule_row_fields(mapped, schema, gfs) == set()
    mapped.pop("CommercialStructure_Location_ProducerIdentifier_B")
    assert ps._unanchored_schedule_row_fields(mapped, schema, gfs) == gfs


def test_a_subject_row_is_one_decision():
    pre = {"CommercialProperty_Premises_LimitAmount_C": "$798,556"}
    mapped = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
        "CommercialProperty_Premises_LimitAmount_A": "$798,556",
        "CommercialProperty_Premises_SubjectOfInsuranceCode_C": "Building",      # amount refused
        "CommercialProperty_Premises_LimitAmount_C": None,
        "CommercialProperty_Premises_SubjectOfInsuranceCode_G": "Building",
        "CommercialProperty_Premises_LimitAmount_G": "$421,714",
        "CommercialProperty_Premises_SubjectOfInsuranceCode_I": "Building",      # repeat of G
        "CommercialProperty_Premises_LimitAmount_I": "$421,714",
        "CommercialProperty_Premises_CauseOfLossCode_I": "Special",
        "CommercialProperty_Premises_LimitAmount_K": "$75,000",                  # unique, kept
    }
    gfs = {k for k in mapped if not k.endswith(("_A", "_G"))}
    cleared, cascade = ps._settle_subject_of_insurance_rows(mapped, gfs, pre)
    assert cleared == {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_C": "SUBJECT_WITHOUT_ITS_AMOUNT",
        "CommercialProperty_Premises_SubjectOfInsuranceCode_I": "REPEATS_SUBJECT_ROW_G",
        "CommercialProperty_Premises_LimitAmount_I": "REPEATS_SUBJECT_ROW_G"}
    assert cascade == {"CommercialProperty_Premises_CauseOfLossCode_I"}
    assert mapped["CommercialProperty_Premises_LimitAmount_K"] == "$75,000"
    assert mapped["CommercialProperty_Premises_LimitAmount_G"] == "$421,714"


@lru_cache(maxsize=1)
def _acord140_replay():
    mf, flags = _merged()
    facts = dict(mf)
    for k, v in _fixture()["producer_answers"].items():
        facts[k] = {"value": v, "source": "producer", "confidence": "filled", "value_state": "present"}
    facts = {**facts, **flags}
    ai = dict(_fixture()["acord140_gap_fill"])
    raw = "\n".join(d.get("text") or "" for d in _fixture()["docs"])
    report: list = []
    mapped, conf = ps.map_facts_to_form(
        facts, _schema("ACORD_140"), form_id="ACORD_140", raw_text=raw,
        pre_filled_gpt={"filled_values": ai, "raw_text_fields": set(ai), "question_grounding": {}},
        guard_report=report)
    return mapped, conf, report


def test_replay_acord140_keeps_building_twos_own_values():
    mapped, conf, _ = _acord140_replay()
    assert mapped["Construction_ConstructionCode_B"] == "NON-COMBUSTIBLE - LIGHT STEEL"
    assert mapped["CommercialProperty_Premises_LimitAmount_G"] == "$421,714"
    # Round 5 (7 Oct): the $75,000 stock is building 2's own schedule row, in
    # the schedule's order (G building, H BPP, I stock, J business income) -
    # no longer wherever gap fill happened to put it (K). Row K, after the last
    # coverage, is an owned blank.
    assert mapped["CommercialProperty_Premises_LimitAmount_I"] == "$75,000"
    assert mapped["CommercialProperty_Premises_SubjectOfInsuranceCode_I"] == "Stock"
    assert mapped.get("CommercialProperty_Premises_LimitAmount_K") is None
    assert mapped["CommercialStructure_Location_ProducerIdentifier_A"] == "1"
    assert mapped["CommercialStructure_Location_ProducerIdentifier_B"] == "1"
    assert [mapped["CommercialStructure_Building_ProducerIdentifier_A"],
            mapped["CommercialStructure_Building_ProducerIdentifier_B"]] == ["001", "002"]
    assert not str(mapped.get("CommercialStructure_PhysicalAddress_LineOne_A") or "").startswith("Prem")


def test_replay_acord140_raises_no_completeness_hard_block():
    """No GOOD value is emptied into a completeness gap (Brent's DRAFT, 6 Oct).

    UPDATED 8 Oct 2026 (round 9, `25sepChanges.md` part S) - the test was
    wrong, not the code. It asserted NO gap at all, which held only because gap
    fill's roof material "Composition" filled both buildings - a value no
    document and no answer states (the producer answered roof YEAR 2011, never
    a material). The building-attribute rule now refuses it, so roof material
    is the one honest gap. Every value a PERSON stated (year built 2001,
    protection class 3) still stands on both buildings."""
    mapped, conf, _ = _acord140_replay()
    assert sorted(f for f, c in conf.items() if c == "missing_required_gate") == [
        "Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B"]
    assert mapped["CommercialStructure_BuiltYear_B"] == "2001"
    assert mapped["BuildingFireProtection_ProtectionClassCode_B"] == "3"


def test_replay_every_refused_value_says_why():
    _, _, report = _acord140_replay()
    mine = {"Construction_", "CommercialProperty_Premises_", "CommercialStructure_BuiltYear",
            "BuildingFireProtection_ProtectionClassCode"}
    unexplained = [r["field"] for r in report
                   if any(r["field"].startswith(p) for p in mine)
                   and not r.get("reason") and r.get("kind") != "unanswered"]
    assert unexplained == []
