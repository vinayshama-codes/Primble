"""Choice Electric items 5 / 18 / 22 / 27 (13 Oct 2026, run `ba7c709d`).

5  - ACORD 130 ticks "At expiration" for an annual audit; its code box stays
     empty. ACORD 125 (code box only) keeps "A".
18 - answers reach the forms: the GL class code a warning saves prints on the
     126; building 2 at the same premises prints the location's hydrant.
22 - a form's own checklist cards are listed before forms (dry run).
27 - one premises with two buildings is ONE location: its revenue / staff are
     asked once (first row), its interest and city limits repeat, and every
     location box is answerable before forms (location table columns).
"""
from services import pdf_service as ps
from services import premises_interest as pi


def _row(**kw):
    r = {"address_line1": "4800 Washington St", "address_city": "Denver",
         "address_state": "CO", "location_number": "1"}
    r.update(kw)
    return r


def _facts(rows, form="ACORD_125", **extra):
    f = {"_form_id": form, "property_locations": rows}
    f.update(extra)
    return f


# ── 27: one premises ──────────────────────────────────────────────────────────

def test_same_premises_reads_loc_number_then_street():
    assert pi.same_premises(_row(location_number="001"), _row(location_number="1"))
    assert pi.same_premises(_row(location_number=None), _row(location_number=None))
    assert not pi.same_premises(_row(), _row(address_line1="10 Other Rd"))
    assert not pi.same_premises(_row(location_number="1"), _row(location_number="2"))


def test_one_premises_row_covers_several_buildings_only():
    two_bldgs = [_row(building_number="1"), _row(building_number="2")]
    assert pi.one_premises_row({"property_locations": two_bldgs}) is two_bldgs[0]
    assert pi.one_premises_row({"property_locations": [_row(), _row(address_line1="9 Elm St", location_number="2")]}) is None


def test_second_building_prints_location_once_and_shares_interest_and_city_limits():
    rows = [_row(building_number="1", is_inside_city_limits=True, is_outside_city_limits=False),
            _row(building_number="2")]
    f = _facts(rows, total_revenue="4500000", premises_interest="Owner - the business owns the building")
    assert ps._resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_A", f) == "4,500,000" or \
        "4500000" in str(ps._resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_A", f)).replace(",", "")
    assert ps._resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_B", f) is None
    assert ps._resolve_schedule_row("BusinessInformation_FullTimeEmployeeCount_B", f) is None
    assert ps._resolve_schedule_row("CommercialStructure_InsuredInterest_OwnerIndicator_B", f) == "Yes"
    assert ps._resolve_schedule_row("CommercialStructure_RiskLocation_InsideCityLimitsIndicator_B", f) == "Yes"
    # The row's own value always wins.
    rows[1]["annual_revenue"] = "100000"
    assert ps._resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_B", f) == "100000"


def test_two_premises_keep_their_own_rows():
    rows = [_row(is_owner=True), _row(address_line1="9 Elm St", location_number="2", annual_revenue="5")]
    f = _facts(rows)
    assert ps._resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_B", f) == "5"
    assert ps._resolve_schedule_row("CommercialStructure_InsuredInterest_OwnerIndicator_B", f) in (None, "")


def test_city_limits_column_yes_no_and_outside_follows():
    inside_box = "CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A"
    outside_box = "CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_A"
    # A typed answer decides both boxes, over a stale OUTSIDE beside it.
    for typed, inside, outside in (("Yes", "Yes", "No"), ("No", "No", "Yes")):
        f = _facts([_row(is_inside_city_limits=typed, is_outside_city_limits=False)])
        assert ps._resolve_schedule_row(inside_box, f) == inside
        assert ps._resolve_schedule_row(outside_box, f) == outside
    # Unreadable text is no answer: the row's own OUTSIDE stands.
    f = _facts([_row(is_inside_city_limits="maybe", is_outside_city_limits=True)])
    assert ps._resolve_schedule_row(inside_box, f) in (None, "")
    assert ps._resolve_schedule_row(outside_box, f) == "Yes"
    other = _facts([_row(is_inside_city_limits="No", is_other_city_limits=True)])
    assert ps._resolve_schedule_row(outside_box, other) in (None, "")


def test_125_yellow_boxes_skip_a_later_building():
    rows = [_row(building_number="1"), _row(building_number="2")]
    boxes = ("BusinessInformation_FullTimeEmployeeCount", "CommercialStructure_AnnualRevenueAmount",
             "CommercialStructure_InsuredInterest_OwnerIndicator",
             "CommercialStructure_RiskLocation_InsideCityLimitsIndicator", "Construction_BuildingArea")
    state = {f"{b}_{r}": "" for b in boxes for r in "AB"}
    state.update({"CommercialStructure_PhysicalAddress_LineOne_A": "4800 Washington St",
                  "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Washington St"})
    conf = ps.apply_acord125_missing_field_highlights("ACORD_125", _facts(rows), state, {})
    assert conf.get("BusinessInformation_FullTimeEmployeeCount_A") == "missing_required"
    assert conf.get("CommercialStructure_InsuredInterest_OwnerIndicator_A") == "missing_required"
    for box in ("BusinessInformation_FullTimeEmployeeCount_B", "CommercialStructure_AnnualRevenueAmount_B",
                "CommercialStructure_InsuredInterest_OwnerIndicator_B",
                "CommercialStructure_RiskLocation_InsideCityLimitsIndicator_B"):
        assert conf.get(box) != "missing_required", box
    assert conf.get("Construction_BuildingArea_B") == "missing_required"   # per building


def test_later_building_interest_box_is_a_twin_of_the_business_answer():
    assert ps.premises_twin_key("CommercialStructure_InsuredInterest_OwnerIndicator_B") == "premises_interest"
    assert ps.premises_twin_key("CommercialStructure_AnnualRevenueAmount_B") is None
    f = _facts([_row(building_number="1"), _row(building_number="2")])
    assert ps.premises_twin_fact("CommercialStructure_InsuredInterest_OwnerIndicator_B", f) == "premises_interest"
    f["property_locations"][1]["is_tenant"] = True
    assert ps.premises_twin_fact("CommercialStructure_InsuredInterest_OwnerIndicator_B", f) is None


def test_location_table_offers_the_new_columns_and_shows_yes_no():
    from services.schedule_capture import SCHEDULE_DEFS, rows_from_facts
    cols = {c["key"]: c for c in SCHEDULE_DEFS["property_locations"]["columns"]}
    for k in ("annual_revenue", "full_time_employees", "part_time_employees",
              "total_building_area", "is_inside_city_limits"):
        assert cols[k]["producer_only"]
    rows = rows_from_facts("property_locations", {"property_locations": [_row(is_inside_city_limits=True)]})
    assert rows[0]["is_inside_city_limits"] == "Yes"


def test_one_own_or_rent_question_for_one_premises():
    from services.arq_service import _maybe_inject_premises_questions
    q = []
    _maybe_inject_premises_questions(q, {"property_locations": [_row(), _row(building_number="2")]},
                                     {}, ["ACORD_125"])
    names = [x["field_name"] for x in q]
    assert "premises_interest" in names and not any("@loc" in n for n in names)
    q = []
    _maybe_inject_premises_questions(q, {"property_locations": [
        _row(location_number="1"), _row(location_number="1", building_number="2"),
        _row(address_line1="9 Elm St", location_number="2")]}, {}, ["ACORD_125"])
    names = {x["field_name"] for x in q}
    assert "premises_interest@loc1" in names and "premises_interest@loc3" in names
    assert "premises_interest@loc2" not in names


def test_llc_member_count_is_answerable():
    from services.arq_service import _canonical_key
    from services.answer_routing import answer_mode
    assert _canonical_key("NamedInsured_LegalEntity_MemberManagerCount_A") == "applicant_member_manager_count"
    assert _canonical_key("NamedInsured_LegalEntity_MemberManagerCount_B") is None
    assert answer_mode("applicant_member_manager_count", {})["mode"] == "field"
    f = {"_form_id": "ACORD_125", "applicant_member_manager_count": "2"}
    assert ps._deterministic_map("NamedInsured_LegalEntity_MemberManagerCount_A", f) == "2"


# ── 18 ────────────────────────────────────────────────────────────────────────

def test_hydrant_carries_to_a_building_at_the_same_premises_only():
    same = _facts([_row(building_number="1"), _row(building_number="2")], form="ACORD_140",
                  distance_to_hydrant="500")
    assert ps._deterministic_map("BuildingFireProtection_HydrantDistanceFeetCount_B", same) == "500"
    other = _facts([_row(), _row(address_line1="9 Elm St", location_number="2")], form="ACORD_140",
                   distance_to_hydrant="500")
    assert ps._deterministic_map("BuildingFireProtection_HydrantDistanceFeetCount_B", other) != "500"


def test_gl_code_a_person_saved_prints_on_the_126():
    f = {"_form_id": "ACORD_126", "gl_class_codes_by_location": "92478"}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_A", f) == "92478"
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_B", f) in (None, ps._SCHED_SKIP)


# ── 5 ─────────────────────────────────────────────────────────────────────────

def test_annual_audit_ticks_at_expiration_on_the_130_and_keeps_the_code_on_the_125():
    f130 = {"_form_id": "ACORD_130", "audit_frequency": "Annual"}
    assert ps._resolve_audit_tick("Policy_Audit_AtExpirationIndicator_A", f130) == "Yes"
    assert ps._resolve_audit_tick("Policy_Audit_SemiAnnualIndicator_A", f130) is None
    assert ps._resolve_audit_frequency("Policy_Audit_FrequencyCode_A", f130) is None
    assert ps._resolve_audit_frequency("Policy_Audit_FrequencyCode_A",
                                       {"_form_id": "ACORD_125", "audit_frequency": "Annual"}) == "A"
    assert ps._resolve_audit_tick("Policy_Audit_AtExpirationIndicator_A", {"_form_id": "ACORD_130"}) is None


# ── 22 ────────────────────────────────────────────────────────────────────────

def test_form_cards_are_listed_only_when_answerable_here(monkeypatch):
    from services import form_dry_run as fdr
    import services.sqs_service as sq
    recs = [{"type": "missing_field", "field": "gl_form_type", "rec_id": "rec_gl_form_type",
             "message": "Specify GL form type"},
            {"type": "missing_field", "field": "wc_officer_exclusions", "rec_id": "r2", "message": "x"},
            {"type": "missing_field", "field": "not_a_fact_anywhere", "rec_id": "r3", "message": "y"},
            {"type": "suggestion", "field": None, "rec_id": "r4", "message": "z"}]
    monkeypatch.setattr(sq, "calculate_sqs", lambda *a, **k: {"recommendations": recs})
    monkeypatch.setattr(fdr, "_key_detail_fixes", lambda f, fl: (set(), set()))
    gen = {"ACORD_126": {"mapped": {}, "schema": {}, "confidence": {}}}
    out = fdr.form_card_items(gen, {"wc_officer_exclusions": "No - all owners and officers are included"},
                              {}, ["ACORD_126"], [])
    assert [i["route"]["facts"] for i in out] == [["gl_form_type"]]
    assert out[0]["boxes"] == [] and out[0]["resolution"]["mode"] == "field"
    # Already an item -> not repeated.
    assert fdr.form_card_items(gen, {}, {}, ["ACORD_126"],
                               [{"route": {"mode": "field", "facts": ["gl_form_type"]}}]) == [] or \
        all(i["route"]["facts"] != ["gl_form_type"] for i in fdr.form_card_items(
            gen, {}, {}, ["ACORD_126"], [{"route": {"mode": "field", "facts": ["gl_form_type"]}}]))


def test_dry_run_offers_the_business_answer_for_the_interest_tick():
    from services.form_dry_run import _field_routes
    routes = _field_routes("CommercialStructure_InsuredInterest_OwnerIndicator_A", {})
    assert {"mode": "field", "facts": ["premises_interest"]} in routes
