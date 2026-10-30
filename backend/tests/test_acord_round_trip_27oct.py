"""The Choice Electric round trip (27 Oct 2026, ACORD_INTAKE.md "Round trip"):
package A reached 100, its forms were downloaded and re-uploaded - alone (B1)
and with the 7 decs and 2 loss runs (B2). Every person answer came back through
the Primble record; what did not come back were document values the forms
print, each lost to one of these defects. One test per class, from the live
shapes."""
import copy

from services.acord_intake import merge_rules, read, reverse_map


# ── 1. A redacted fleet is ONE fleet, whichever documents list it ───────────────

def _van(year="2014", model="EXPRESS G2500", **kw):
    return {"year": year, "make": "CHEVROLET", "model": model, **kw}


def test_vehicles_without_vins_fold_across_documents_one_to_one():
    dec = [_van("2001", class_code="01483", territory="111"), _van("2014"), _van("2014")]
    form = [_van("2001", model="Express G2500", vehicle_number="1", cost_new="21,210"),
            _van("2014", vehicle_number="2"), _van("2014", vehicle_number="3")]
    out = merge_rules.fold_rows("auto_vin_schedule", [dec, form])
    assert len(out) == 3                                 # never 6, never 2
    assert out[0]["cost_new"] == "21,210" and out[0]["class_code"] == "01483"


def test_two_identical_vans_on_one_document_stay_two():
    assert len(merge_rules.fold_rows("auto_vin_schedule", [[_van(), _van()]])) == 2


def test_a_disagreeing_cost_class_or_number_means_two_vehicles():
    for a, b in ((dict(cost_new="21,210"), dict(cost_new="24,500")),
                 (dict(class_code="01483"), dict(class_code="7398")),
                 (dict(vehicle_number="4"), dict(vehicle_number="9"))):
        assert len(merge_rules.fold_rows("auto_vin_schedule", [[_van(**a)], [_van(**b)]])) == 2


def test_money_and_codes_compare_by_value_not_spelling():
    out = merge_rules.fold_rows("auto_vin_schedule", [[_van(cost_new="$21,210.00", class_code="01483")],
                                                      [_van(cost_new="21210", class_code="1483")]])
    assert len(out) == 1


def test_a_different_year_or_model_never_folds():
    assert len(merge_rules.fold_rows("auto_vin_schedule", [[_van("2014")], [_van("2015")]])) == 2
    assert len(merge_rules.fold_rows("auto_vin_schedule", [[_van()], [_van(model="SAFARI XT")]])) == 2


def _doc(name, facts, acord=False, doc_type="dec_page"):
    d = {"filename": name, "doc_type": doc_type, "facts": facts}
    if acord:
        d["acord"] = {"forms": [{"form_id": "ACORD_127", "copy": 1}], "read_keys": sorted(facts)}
    return d


def test_the_declarations_fleet_and_the_127s_fleet_fold_into_one():
    dec = _doc("auto.pdf", {"auto_vin_schedule": [_van("2001"), _van("2014")]})
    f127 = _doc("ACORD_127.pdf", {"auto_vin_schedule": [_van("2001"), _van("2014")]}, acord=True,
                doc_type="acord_form")
    view, _ = merge_rules.fold_acord_lists([dec, f127], dec)
    rows = [r for d in view for r in (d["facts"].get("auto_vin_schedule") or [])]
    assert len(rows) == 2
    assert dec["facts"]["auto_vin_schedule"] and f127["facts"]["auto_vin_schedule"]  # stored copies untouched


def test_a_package_without_an_acord_form_keeps_todays_merge():
    a = _doc("a.pdf", {"auto_vin_schedule": [_van()]})
    b = _doc("b.pdf", {"auto_vin_schedule": [_van()]})
    view, _ = merge_rules.fold_acord_lists([a, b], a)
    assert view[0] is a and view[1] is b


# ── 2. A box reading is the form's statement, not the model's guess ──────────────

def test_box_readings_sit_out_the_model_rules_and_come_back():
    facts = {"auto_vehicle_use": {"value": "Service", "source": "acord_form"},
             "fein": {"value": "84-1234567", "source": "producer"},
             "ai_box": {"value": "x", "source": "ai"}, "model_said": {"value": "y", "source": "ai"}}
    d = _doc("ACORD_127.pdf", dict(facts), acord=True, doc_type="acord_form")
    d["acord"]["read_keys"] = ["auto_vehicle_use", "fein", "ai_box"]
    held = merge_rules.lift_box_readings([d])
    assert set(d["facts"]) == {"ai_box", "model_said"}   # an AI fill the record names stays policed
    merge_rules.restore_box_readings(held)
    assert d["facts"] == facts


def test_a_document_stored_without_read_keys_lifts_its_exact_envelopes():
    d = _doc("ACORD_127.pdf", {"auto_vehicle_use": {"value": "Service", "source": "acord_form"},
                               "other": {"value": "z", "source": "ai"}}, acord=True, doc_type="acord_form")
    del d["acord"]["read_keys"]
    held = merge_rules.lift_box_readings([d])
    assert list(d["facts"]) == ["other"]
    merge_rules.restore_box_readings(held)
    assert "auto_vehicle_use" in d["facts"]


def test_a_non_acord_document_lifts_nothing():
    d = _doc("dec.pdf", {"auto_vehicle_use": {"value": "Service", "source": "acord_form"}})
    assert merge_rules.lift_box_readings([d]) == [] and "auto_vehicle_use" in d["facts"]


def test_the_vehicle_use_rule_never_drops_a_box_reading():
    from services.extraction_service import drop_unlabelled_vehicle_use, merge_facts
    doc = _doc("ACORD_127.pdf", {"auto_vehicle_use": {"value": "Service - technicians or crews driving to job sites",
                                                      "source": "acord_form", "confidence": "acord_exact"}},
               acord=True, doc_type="acord_form")
    doc["text"] = "BUSINESS AUTO SECTION vehicle schedule"
    assert drop_unlabelled_vehicle_use(copy.deepcopy(doc)) is True   # the rule itself, unchanged
    mf, _flags = merge_facts([doc], doc)
    assert "Service" in str((mf.get("auto_vehicle_use") or {}).get("value"))
    assert "auto_vehicle_use" in doc["facts"]                         # the stored copy too


def test_the_inference_gates_treat_a_form_box_as_stated():
    from services.extraction_service import _PERIOD_NAMED_SOURCES
    from services.fact_state import ACORD_BOX_SOURCE
    assert ACORD_BOX_SOURCE in _PERIOD_NAMED_SOURCES
    assert read.SOURCE == merge_rules.ACORD_SOURCE == ACORD_BOX_SOURCE


# ── 3. The term an application replaces is the prior term ────────────────────────

def _app(facts):
    return {"filename": "ACORD_125.pdf", "doc_type": "application", "facts": facts,
            "acord": {"forms": [{"form_id": "ACORD_125", "copy": 1}]}}


def test_the_declarations_term_becomes_the_prior_term():
    merged = {"effective_date": {"value": "01/01/2025", "source": "ai"},
              "expiration_date": {"value": "01/01/2026", "source": "ai"}}
    app = _app({"effective_date": {"value": "01/01/2027", "source": "acord_form"},
                "expiration_date": {"value": "01/01/2028", "source": "acord_form"}})
    merge_rules.apply_owner_rules(merged, [app])
    assert merged["effective_date"]["value"] == "01/01/2027"
    assert merged["prior_effective_date"]["value"] == "01/01/2025"
    assert merged["prior_expiration_date"]["value"] == "01/01/2026"
    assert merged["prior_effective_date"].get("routed_from") == "current_term"


def test_a_term_that_is_not_the_one_before_the_proposal_is_not_kept():
    for old in (("01/01/2027", "01/01/2028"),            # the same term
                ("06/01/2026", "06/01/2027"),            # overlaps the proposal
                ("01/01/2022", "01/01/2023")):           # years before it
        merged = {"effective_date": {"value": old[0], "source": "ai"},
                  "expiration_date": {"value": old[1], "source": "ai"}}
        app = _app({"effective_date": {"value": "01/01/2027", "source": "acord_form"},
                    "expiration_date": {"value": "01/01/2028", "source": "acord_form"}})
        merge_rules.apply_owner_rules(merged, [app])
        assert not merged.get("prior_effective_date"), old


def test_a_stated_prior_term_is_never_replaced():
    merged = {"effective_date": {"value": "01/01/2025", "source": "ai"},
              "expiration_date": {"value": "01/01/2026", "source": "ai"},
              "prior_effective_date": {"value": "01/01/2024", "source": "producer"},
              "prior_expiration_date": {"value": "01/01/2025", "source": "producer"}}
    app = _app({"effective_date": {"value": "01/01/2027", "source": "acord_form"},
                "expiration_date": {"value": "01/01/2028", "source": "acord_form"}})
    merge_rules.apply_owner_rules(merged, [app])
    assert merged["prior_effective_date"]["value"] == "01/01/2024"


def _grid_app(rows):
    return _app({"effective_date": {"value": "01/01/2027", "source": "acord_form"},
                 "expiration_date": {"value": "01/01/2028", "source": "acord_form"},
                 "prior_coverage_by_line": rows})


def test_forms_only_the_125_grid_states_the_prior_term_and_carrier():
    rows = [{"line": "General Liability", "carrier": "AMERISURE INSURANCE COMPANY",
             "effective": "01/01/2025", "expiration": "01/01/2026"},
            {"line": "Business Auto", "carrier": "AMERISURE INSURANCE COMPANY",
             "effective": "01/01/2025", "expiration": "01/01/2026"},
            {"line": "Umbrella", "carrier": "AMERISURE MUTUAL INSURANCE COMPANY",
             "effective": "01/01/2025", "expiration": "01/01/2026"},
            {"line": "General Liability", "carrier": "OLD CARRIER CO",
             "effective": "01/01/2024", "expiration": "01/01/2025"}]
    merged = {}
    merge_rules.apply_owner_rules(merged, [_grid_app(rows)])
    assert merged["prior_effective_date"]["value"] == "01/01/2025"
    assert merged["prior_expiration_date"]["value"] == "01/01/2026"
    assert merged["prior_carrier"]["value"] == "AMERISURE INSURANCE COMPANY / AMERISURE MUTUAL INSURANCE COMPANY"


def test_two_terms_ending_on_one_day_give_no_prior_term():
    rows = [{"carrier": "A", "effective": "01/01/2025", "expiration": "01/01/2026"},
            {"carrier": "B", "effective": "07/01/2025", "expiration": "01/01/2026"}]
    merged = {}
    merge_rules.apply_owner_rules(merged, [_grid_app(rows)])
    assert not merged.get("prior_effective_date") and not merged.get("prior_carrier")


# ── 4. An application agreeing with a policy's own dec places nothing ────────────

def _uc_values():
    return [{"display": "$5,000,000", "normalized": "5000000",
             "sources": [{"filename": "umb.pdf", "raw": "$5,000,000"},
                         {"filename": "ACORD_131.pdf", "raw": "5,000,000"}]},
            {"display": "$4,000,000", "normalized": "4000000",
             "sources": [{"filename": "exc.pdf", "raw": "$4,000,000"}]}]


_UC_FACTS = {"_line_records": [
    {"id": "umbrella#u1", "line": "umbrella", "policy_number": "U1", "carrier": "AMERISURE MUTUAL",
     "premium": "$17,082", "sources": ["umb.pdf"]},
    {"id": "umbrella~excess#x1", "line": "umbrella", "layer": "excess", "policy_number": "X1",
     "carrier": "TRAVELERS", "premium": "$10,692", "sources": ["exc.pdf"]}]}


def _uc_docs(*extra):
    return [{"filename": "umb.pdf", "doc_type": "dec_page"}, {"filename": "exc.pdf", "doc_type": "dec_page"},
            {"filename": "ACORD_131.pdf", "doc_type": "acord_form",
             "acord": {"forms": [{"form_id": "ACORD_131", "copy": 1}]}}, *extra]


def test_the_umbrella_and_the_excess_stay_two_policies_beside_a_131():
    from services.underwriting_consistency import _scope_by_policy_record
    assert _scope_by_policy_record("umbrella_limit", _uc_values(), _UC_FACTS, _uc_docs()) is True


def test_an_application_alone_in_its_group_still_places_nothing():
    from services.underwriting_consistency import _scope_by_policy_record
    vals = _uc_values()
    vals[0]["sources"] = [{"filename": "ACORD_131.pdf", "raw": "5,000,000"}]
    assert _scope_by_policy_record("umbrella_limit", vals, _UC_FACTS, _uc_docs()) is False


def test_a_certificate_is_never_an_agreeing_application():
    from services.underwriting_consistency import _scope_by_policy_record
    vals = _uc_values()
    vals[0]["sources"][1]["filename"] = "ACORD_25.pdf"
    docs = _uc_docs({"filename": "ACORD_25.pdf", "doc_type": "certificate",
                     "acord": {"forms": [{"form_id": "ACORD_25", "copy": 1}]}})
    assert _scope_by_policy_record("umbrella_limit", vals, _UC_FACTS, docs) is False


# ── 5. The 140's grid is a coverage schedule, read by subject ────────────────────

def _c140(boxes):
    return {"form_id": "ACORD_140", "copy": 1, "boxes": boxes, "kinds": {}, "box_page": {}}


GRID_140 = {
    "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
    "CommercialProperty_Premises_LimitAmount_A": "$798,556",
    "CommercialProperty_Premises_DeductibleAmount_A": "$5,000",
    "CommercialProperty_Premises_SubjectOfInsuranceCode_B": "Business Personal Property",
    "CommercialProperty_Premises_LimitAmount_B": "$73,008",
    "CommercialProperty_Premises_SubjectOfInsuranceCode_C": "Business Income with Extra Expense",
    "CommercialProperty_Premises_LimitAmount_C": "$1,000,000",
    "CommercialProperty_Premises_DeductibleAmount_C": "72 Hours",
    "CommercialProperty_Premises_SubjectOfInsuranceCode_G": "Business Personal Property",
    "CommercialProperty_Premises_LimitAmount_G": "$50,000",
}


def test_the_grid_reads_into_sections_by_premises():
    grid = read._premises_grid([_c140(GRID_140)])
    assert [c["kind"] for c in grid[0]] == ["building", "bpp", "bi"]
    assert [c["kind"] for c in grid[1]] == ["bpp"]


def test_values_follow_the_subject_not_the_row_letter():
    lists = {"property_locations": {0: {"location_number": "1", "building_number": "001"},
                                    1: {"location_number": "2", "building_value": "$50,000"}}}
    facts = {"property_deductible_aop": {"value": "$5,000", "source": "acord_form",
                                         "box": "CommercialProperty_Premises_DeductibleAmount_A"}}
    read._apply_premises_grid(read._premises_grid([_c140(GRID_140)]), lists, facts)
    rows = lists["property_locations"]
    assert rows[0]["building_value"] == "$798,556" and rows[0]["bpp_value"] == "$73,008"
    assert "building_value" not in rows[1] and rows[1]["bpp_value"] == "$50,000"   # row G is BPP
    assert "property_deductible_aop" not in facts                # a row's own, not the policy's
    secs = facts["_property_coverages"]["sections"]
    assert (secs[0]["premises"], secs[0]["building"]) == ("1", "1") and secs[0]["complete"]


def test_an_aop_deductible_from_another_box_stays():
    facts = {"property_deductible_aop": {"value": "$1,000", "source": "acord_form", "box": "Other_Box_A"}}
    read._apply_premises_grid(read._premises_grid([_c140(GRID_140)]), {}, facts)
    assert facts["property_deductible_aop"]["value"] == "$1,000"


def test_the_grid_is_used_only_where_no_document_prints_a_schedule():
    from services.property_coverages import KEY, derive_property_coverages
    sec = {"premises": "1", "building": "1", "complete": True,
           "coverages": [{"kind": "bi", "limit": "$1,000,000", "coverage": "Business Income"}]}
    acord = {"filename": "ACORD_140.pdf", "text": "", "facts": {KEY: {"sections": [sec], "source": "acord_form"}}}
    facts = {}
    derive_property_coverages(facts, [acord])
    assert facts[KEY]["sections"][0]["coverages"][0]["kind"] == "bi"


def test_a_scheduled_bi_row_and_deductible_are_stated():
    from services.property_coverages import KEY, schedule_states_deductible, schedule_states_limit
    facts = {KEY: {"sections": [{"coverages": [
        {"kind": "building", "limit": "$798,556", "deductible": "$5,000"},
        {"kind": "bi", "limit": "$1,000,000", "deductible": "72 Hours"}]}]}}
    assert schedule_states_limit(facts, "bi") and schedule_states_deductible(facts) == "$5,000"
    only_bi = {KEY: {"sections": [{"coverages": [{"kind": "bi", "limit": "$1", "deductible": "$500"}]}]}}
    assert not schedule_states_deductible(only_bi)          # a waiting period row is not the AOP


def test_the_property_pillar_does_not_ask_a_scheduled_bi_limit():
    from services.property_coverages import KEY
    from services.sqs_service import property_gap_items
    facts = {KEY: {"sections": [{"coverages": [{"kind": "bi", "limit": "$1,000,000"}]}]}}
    items = property_gap_items(facts, {"has_property_coverage": True})
    assert "business_income_limit" not in {i["fact"] for i in items}
    assert "business_income_limit" in {i["fact"] for i in property_gap_items({}, {"has_property_coverage": True})}


def test_the_aop_warning_reads_the_schedule():
    from services.cross_form_validator import run_cross_form_validation
    from services.property_coverages import KEY
    facts = {KEY: {"sections": [{"coverages": [{"kind": "building", "limit": "$1", "deductible": "$5,000"}]}]}}
    codes = {i.get("code") or i.get("rule_code") for i in
             run_cross_form_validation(facts, {"has_property_coverage": True}, ["ACORD_140"]) or []}
    assert "property_aop_deductible_missing" not in codes
    codes = {i.get("code") or i.get("rule_code") for i in
             run_cross_form_validation({}, {"has_property_coverage": True}, ["ACORD_140"]) or []}
    assert "property_aop_deductible_missing" in codes


# ── 6. Per-vehicle garaging is garaging information ─────────────────────────────

def test_the_127_garaging_boxes_read_into_the_vehicle_row():
    assert reverse_map.box_targets("ACORD_127", "Vehicle_PhysicalAddress_CityName_C") == [
        {"t": "cell", "list": "auto_vin_schedule", "row": 2, "col": "garaging_city"}]
    assert reverse_map.box_targets("ACORD_127", "Vehicle_PhysicalAddress_PostalCode_A")[0]["col"] == "garaging_zip"


def test_a_vehicle_rows_own_garaging_answers_the_garaging_item():
    from services.coverage_evidence import auto_completeness_gaps
    flags = {"has_auto_coverage": True}
    base = {"auto_vin_schedule": [{"year": "2014", "make": "CHEVROLET", "model": "EXPRESS"}]}
    assert "auto_garaging_addresses" in {k for k, _, _ in auto_completeness_gaps(base, flags)}
    base["auto_vin_schedule"][0]["garaging_city"] = "Denver"
    assert "auto_garaging_addresses" not in {k for k, _, _ in auto_completeness_gaps(base, flags)}


# ── 7. The 131's UNDERLYING INSURANCE section is a schedule ─────────────────────

def _c131(boxes):
    return {"form_id": "ACORD_131", "copy": 1, "boxes": boxes, "kinds": {}, "box_page": {}}


def test_the_131_underlying_section_reads_as_a_schedule():
    rows = read._underlying_schedule([_c131({
        "UnderlyingPolicy_GeneralLiability_InsurerFullName_A": "AMERISURE INSURANCE COMPANY",
        "GeneralLiability_EachOccurrence_LimitAmount_A": "1,000,000",
        "UnderlyingPolicy_GeneralLiability_PolicyEffectiveDate_A": "01/01/2025",
        "Vehicle_CombinedSingleLimit_EachAccidentAmount_A": "1,000,000",
        "UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A": "Off"})])
    assert [r["line"] for r in rows] == ["General Liability", "Automobile Liability"]
    assert rows[0]["carrier"] == "AMERISURE INSURANCE COMPANY" and "1,000,000" in rows[0]["limit"]
    assert rows[0]["effective_date"] == "01/01/2025"
    from services.coverage_evidence import umbrella_schedule_present
    assert umbrella_schedule_present({"underlying_policies": rows})


def test_a_131_stating_no_underlying_line_gives_no_schedule():
    assert read._underlying_schedule([_c131({"Policy_PolicyType_UmbrellaIndicator_A": "ticked"})]) == []


def test_two_131s_listing_one_gl_policy_fold_to_one_row():
    row = {"line": "General Liability", "carrier": "AMERISURE INSURANCE COMPANY", "limit": "x"}
    assert len(merge_rules.fold_rows("underlying_policies", [[dict(row)], [dict(row)]])) == 1


# ── 8. A person's answer the record restores is the PACKAGE's, not a document's ──

def test_restored_answers_land_on_the_package_never_on_a_document():
    restored = {"answers": {"property_deductible_wind": {"value": "50%", "source": "producer"}},
                "tables": {}}
    forms = [{"filename": f"ACORD_{n}.pdf", "doc_type": "acord_form", "facts": {},
              "acord": {"forms": [{"form_id": f"ACORD_{n}", "copy": 1}], "restored": restored}}
             for n in ("126", "140")]
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page",
           "facts": {"property_deductible_wind": {"value": "2%", "source": "ai"}}}
    merged = {"property_deductible_wind": {"value": "2%", "source": "ai"}}
    merge_rules.apply_owner_rules(merged, [dec] + forms)
    assert merged["property_deductible_wind"]["value"] == "50%"
    assert all("property_deductible_wind" not in d["facts"] for d in forms)


def test_two_forms_restoring_different_answers_restore_neither():
    def form(v):
        return {"filename": f"f{v}.pdf", "doc_type": "acord_form", "facts": {},
                "acord": {"forms": [{"form_id": "ACORD_126", "copy": 1}],
                          "restored": {"answers": {"occupancy_type": {"value": v, "source": "producer"}}}}}
    merged = {}
    merge_rules.apply_restored_answers(merged, [form("Office"), form("Warehouse")])
    assert "occupancy_type" not in merged


def test_an_excluded_forms_record_restores_nothing():
    d = {"filename": "f.pdf", "doc_type": "acord_form", "facts": {}, "excluded": True,
         "acord": {"forms": [{"form_id": "ACORD_126", "copy": 1}],
                   "restored": {"answers": {"occupancy_type": {"value": "Office", "source": "producer"}}}}}
    merged = {}
    merge_rules.apply_restored_answers(merged, [d])
    assert merged == {}


def test_a_scheduled_dollar_deductible_answers_the_basis_question():
    from services.cross_form_validator import run_cross_form_validation
    from services.property_coverages import KEY
    facts = {KEY: {"sections": [{"coverages": [{"kind": "building", "limit": "$1", "deductible": "$5,000",
                                                "deductible_type": "Dollars"}]}]}}
    codes = {i.get("code") or i.get("rule_code") for i in
             run_cross_form_validation(facts, {"has_property_coverage": True}, ["ACORD_140"]) or []}
    assert "property_deductible_basis_missing" not in codes


# ── 9. The excess layer's own limit is no rival of the umbrella's ──────────────

def _layer_doc(name, line, limit):
    return {"filename": name, "doc_type": "dec_page",
            "facts": {"coverage_lines": [{"line": line}], "umbrella_limit": {"value": limit, "source": "ai"}}}


def test_the_excess_decs_limit_never_withholds_the_umbrellas():
    from services.extraction_service import _flag_intra_document_limit_conflicts
    docs = [_layer_doc("umb.pdf", "Commercial Liability Umbrella", "$5,000,000"),
            _layer_doc("exc.pdf", "Excess (Following Form) Liability", "$4,000,000")]
    mf = {"umbrella_limit": {"value": "$5,000,000", "source": "ai"}}
    _flag_intra_document_limit_conflicts(mf, {"umbrella_limit": ["$4,000,000"]}, docs)
    assert "_uw_conflicted_keys" not in mf
    _flag_intra_document_limit_conflicts(mf, {"umbrella_limit": ["$4,000,000"]})   # no documents: as before
    assert mf["_uw_conflicted_keys"] == ["umbrella_limit"]


def test_an_umbrella_document_stating_the_other_amount_still_withholds():
    from services.extraction_service import _flag_intra_document_limit_conflicts
    docs = [_layer_doc("umb.pdf", "Commercial Liability Umbrella", "$5,000,000"),
            _layer_doc("umb2.pdf", "Commercial Liability Umbrella", "$4,000,000"),
            _layer_doc("exc.pdf", "Excess (Following Form) Liability", "$4,000,000")]
    mf = {"umbrella_limit": {"value": "$5,000,000", "source": "ai"}}
    _flag_intra_document_limit_conflicts(mf, {"umbrella_limit": ["$4,000,000"]}, docs)
    assert mf["_uw_conflicted_keys"] == ["umbrella_limit"]


# ── 10. Our own 127 and its 101 continuation list different vehicles ───────────

def _form_doc(name, form_id, rows):
    return {"filename": name, "doc_type": "acord_form", "facts": {"auto_vin_schedule": rows},
            "acord": {"forms": [{"form_id": form_id, "copy": 1}]}}


def test_the_127_leads_its_continuation_and_twin_vehicles_stay_two():
    f101 = _form_doc("ACORD_101.pdf", "ACORD_101",
                     [_van("2022", model="EQUINOX LT", vehicle_number="13", cost_new="28,750")])
    f127 = _form_doc("ACORD_127.pdf", "ACORD_127",
                     [_van("2001"), _van("2022", model="EQUINOX LT", cost_new="28,750")])
    view, _ = merge_rules.fold_acord_lists([f101, f127], f101)
    rows = [r for d in view for r in (d["facts"].get("auto_vin_schedule") or [])]
    assert [r["year"] for r in rows] == ["2001", "2022", "2022"]        # the 127's rows first, 3 vehicles


def test_a_declaration_still_absorbs_both_twins_one_to_one():
    dec = _doc("auto.pdf", {"auto_vin_schedule": [_van("2022", model="EQUINOX LT"), _van("2022", model="EQUINOX LT")]})
    f101 = _form_doc("ACORD_101.pdf", "ACORD_101", [_van("2022", model="EQUINOX LT", vehicle_number="13")])
    f127 = _form_doc("ACORD_127.pdf", "ACORD_127", [_van("2022", model="EQUINOX LT")])
    view, _ = merge_rules.fold_acord_lists([dec, f101, f127], dec)
    assert sum(len(d["facts"].get("auto_vin_schedule") or []) for d in view) == 2


# ── 11. A box no fact can hold is carried, never lost ──────────────────────────

def _copy(form_id, boxes, kinds=None):
    return {"form_id": form_id, "copy": 1, "boxes": boxes, "kinds": kinds or {}, "box_page": {}}


def test_a_value_its_fact_refuses_is_carried_onto_its_form():
    facts, carried = read.boxes_to_facts([_copy("ACORD_125", {"NamedInsured_BusinessStartDate_A": "2011"})])
    assert "business_start_date" not in facts
    assert carried["ACORD_125"]["NamedInsured_BusinessStartDate_A"] == "2011"


def test_a_tick_that_chooses_no_option_is_carried_as_a_tick():
    box = "GeneralLiability_CoverageIndicator_A"
    assert len({t["value"] for t in reverse_map.box_targets("ACORD_126", box) if t.get("t") == "tick"}) >= 2
    facts, carried = read.boxes_to_facts([_copy("ACORD_126", {box: "ticked"}, {box: "check"})])
    assert "gl_form_type" not in facts and carried["ACORD_126"][box] == "Yes"


def test_the_125s_other_line_rows_read_and_carry():
    boxes = {"Policy_LineOfBusiness_OtherIndicator_A": "ticked",
             "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Employment Practices Liability"}
    facts, carried = read.boxes_to_facts([_copy("ACORD_125", boxes,
                                                {"Policy_LineOfBusiness_OtherIndicator_A": "check"})])
    assert "Employment Practices Liability" in (facts.get("lines_of_business") or [])
    assert carried["ACORD_125"]["Policy_LineOfBusiness_OtherIndicator_A"] == "Yes"
    assert carried["ACORD_125"]["Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"] == "Employment Practices Liability"


def test_the_127_vehicle_value_boxes_read_into_the_row():
    assert reverse_map.box_targets("ACORD_127", "Vehicle_CostNewAmount_B") == [
        {"t": "cell", "list": "auto_vin_schedule", "row": 1, "col": "cost_new"}]
    assert reverse_map.box_targets("ACORD_127", "Vehicle_Coverage_AgreedOrStatedAmount_A")[0]["col"] == "stated_amount"


# ── 12. The prior term found tells the section forms to print the proposal ─────

def test_a_moved_or_grid_prior_term_marks_the_dates_routed():
    merged = {"effective_date": {"value": "01/01/2025", "source": "ai"},
              "expiration_date": {"value": "01/01/2026", "source": "ai"}}
    app = _app({"effective_date": {"value": "01/01/2027", "source": "acord_form"},
                "expiration_date": {"value": "01/01/2028", "source": "acord_form"}})
    merge_rules.apply_owner_rules(merged, [app])
    assert merged["renewal_dates_routed"] is True
    grid = {}
    merge_rules.apply_owner_rules(grid, [_grid_app([{"carrier": "A", "effective": "01/01/2025",
                                                     "expiration": "01/01/2026"}])])
    assert grid["renewal_dates_routed"] is True
    none = {}
    merge_rules.apply_owner_rules(none, [_grid_app([])])
    assert "renewal_dates_routed" not in none


# ── 13. A box printing the person's answer is the answer, not evidence ────────

def _record(answers):
    return {"v": 1, "answers": answers, "tables": {}, "ai_boxes": []}


def test_a_box_printing_the_answer_leaves_the_documents_facts():
    from services.acord_intake import primble_record
    facts = {"property_deductible_wind": {"value": "50%", "source": "acord_form", "box": "W"}}
    got = primble_record.apply(_record({"property_deductible_wind": {"value": "50%", "source": "producer"}}), facts)
    assert "property_deductible_wind" not in facts
    assert got["answers"]["property_deductible_wind"]["value"] == "50%"


def test_a_box_changed_after_download_stays_and_the_old_answer_is_not_restored():
    from services.acord_intake import primble_record
    facts = {"property_deductible_wind": {"value": "2%", "source": "acord_form", "box": "W"}}
    got = primble_record.apply(_record({"property_deductible_wind": {"value": "50%", "source": "producer"},
                                        "occupancy_type": {"value": "Office", "source": "producer"}}), facts)
    assert facts["property_deductible_wind"]["value"] == "2%"
    assert "property_deductible_wind" not in got["answers"] and got["answers"]["occupancy_type"]["value"] == "Office"


# ── 14. A certificate printing a restored answer is that answer, not evidence ──

def test_a_certificate_box_that_echoes_a_restored_answer_leaves_its_facts():
    restored = {"answers": {"property_deductible_wind": {"value": "50%", "source": "producer"}}}
    f140 = {"filename": "ACORD_140.pdf", "doc_type": "acord_form", "facts": {},
            "acord": {"forms": [{"form_id": "ACORD_140", "copy": 1}], "restored": restored}}
    c28 = {"filename": "ACORD_28.pdf", "doc_type": "certificate",
           "facts": {"property_deductible_wind": {"value": "50%", "source": "acord_form", "box": "W"}},
           "acord": {"forms": [{"form_id": "ACORD_28", "copy": 1}]}}
    other = {"filename": "ACORD_25.pdf", "doc_type": "certificate",
             "facts": {"property_deductible_wind": {"value": "2%", "source": "acord_form", "box": "W"}},
             "acord": {"forms": [{"form_id": "ACORD_25", "copy": 1}]}}
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page",
           "facts": {"property_deductible_wind": {"value": "2%", "source": "ai"}}}
    gone = merge_rules.drop_answer_echoes([dec, f140, c28, other])
    assert gone == ["ACORD_28.pdf:property_deductible_wind"]
    assert "property_deductible_wind" not in c28["facts"]
    assert other["facts"]["property_deductible_wind"]["value"] == "2%"     # a different reading stays
    assert dec["facts"]["property_deductible_wind"]["value"] == "2%"       # never a non-ACORD document


def test_no_record_no_echo():
    c28 = {"filename": "ACORD_28.pdf", "doc_type": "certificate",
           "facts": {"property_deductible_wind": {"value": "50%", "source": "acord_form"}},
           "acord": {"forms": [{"form_id": "ACORD_28", "copy": 1}]}}
    assert merge_rules.drop_answer_echoes([c28]) == [] and c28["facts"]


# ── 15. A policy period in the date column is a total's year, not a loss date ──

def test_a_year_range_in_the_date_column_is_still_a_total():
    from services.loss_history_state import _row_is_a_period_total, claim_rows
    total = {"date": "2023-2024", "description": "All lines", "line_of_business": "All lines",
             "paid": "4200", "amount": "4200"}
    assert _row_is_a_period_total(total)
    assert _row_is_a_period_total(dict(total, date="2023 / 24"))
    assert not _row_is_a_period_total(dict(total, date="03/04/2024"))      # a real loss date
    assert not _row_is_a_period_total(dict(total, claim_number="C-1"))
    claim = {"date": "03/04/2024", "description": "Water damage", "line_of_business": "Property", "paid": "900"}
    assert claim_rows([total, claim]) == [claim]


# ── 16. Adversarial review (27 Oct, night) ─────────────────────────────────────

def test_a_125_with_no_proposal_never_reads_its_grid_as_the_prior_term():
    # The declarations' CURRENT term stands in effective_date when the 125 leaves
    # PROPOSED EFF DATE blank; the grid's year before it is not the prior term.
    merged = {"effective_date": {"value": "01/01/2026", "source": "ai"},
              "expiration_date": {"value": "01/01/2027", "source": "ai"}}
    app = _app({"prior_coverage_by_line": [
        {"line": "General Liability", "carrier": "AMERISURE", "effective": "01/01/2026", "expiration": "01/01/2027"},
        {"line": "General Liability", "carrier": "OLD CARRIER", "effective": "01/01/2025", "expiration": "01/01/2026"}]})
    merge_rules.apply_owner_rules(merged, [app])
    assert not merged.get("prior_effective_date") and not merged.get("prior_carrier")
    assert "renewal_dates_routed" not in merged
    # A person's proposed term is a proposal: the grid reads against it.
    person = {"effective_date": {"value": "01/01/2027", "source": "producer"},
              "expiration_date": {"value": "01/01/2028", "source": "producer"}}
    merge_rules.apply_owner_rules(person, [_app({"prior_coverage_by_line": [
        {"carrier": "AMERISURE", "effective": "01/01/2026", "expiration": "01/01/2027"}]})])
    assert person["prior_effective_date"]["value"] == "01/01/2026"


def _record_doc(name, applicant, answers, form_id="ACORD_125"):
    return {"filename": name, "doc_type": "application",
            "facts": {"applicant_name": {"value": applicant, "source": "acord_form"}},
            "acord": {"forms": [{"form_id": form_id, "copy": 1}],
                      "restored": {"answers": answers, "tables": {}}}}


def test_another_insureds_record_restores_no_person_answer():
    dec = _doc("hb.pdf", {"applicant_name": {"value": "Harborline Plumbing Inc", "source": "ai"},
                          "total_revenue": {"value": "$900,000", "source": "ai"}})
    ce = _record_doc("ACORD_125.pdf", "Choice Electric LLC",
                     {"total_revenue": {"value": "5000000", "source": "producer"},
                      "property_deductible_wind": {"value": "50%", "source": "producer"}})
    c28 = {"filename": "ACORD_28.pdf", "doc_type": "certificate",
           "facts": {"property_deductible_wind": {"value": "50%", "source": "acord_form"}},
           "acord": {"forms": [{"form_id": "ACORD_28", "copy": 1}]}}
    assert merge_rules.drop_answer_echoes([dec, ce, c28]) == []          # an answer not taken is no echo
    merged = {"total_revenue": {"value": "$900,000", "source": "ai"}}
    merge_rules.apply_owner_rules(merged, [dec, ce, c28])
    assert merged["total_revenue"]["value"] == "$900,000"
    assert "property_deductible_wind" not in merged
    # The same record beside its own insured's documents restores.
    own = _doc("ce.pdf", {"applicant_name": {"value": "CHOICE ELECTRIC, LLC", "source": "ai"}})
    merged = {}
    merge_rules.apply_owner_rules(merged, [own, ce])
    assert merged["total_revenue"]["source"] == "producer"


def test_two_acord_forms_never_meet_in_one_declaration_vehicle():
    def eq(**kw):
        return {"year": "2022", "make": "CHEVROLET", "model": "EQUINOX", **kw}
    out = merge_rules.fold_rows("auto_vin_schedule",
                                [[eq(), eq()], [eq(garaging_city="DENVER")], [eq(vehicle_number="5")]],
                                [False, True, True])
    assert len(out) == 2
    assert out[0].get("garaging_city") == "DENVER" and not out[0].get("vehicle_number")
    assert out[1].get("vehicle_number") == "5"


def test_held_out_box_readings_are_still_the_insureds_evidence():
    from services.extraction_service import merge_facts, select_primary_truth
    dec = {"filename": "wc.pdf", "doc_type": "dec_page", "text": "WORKERS COMPENSATION DECLARATIONS Item 3A State: CO",
           "facts": {"state_of_operations": {"value": "CO", "source": "ai", "confidence": "high"}},
           "flags": {"has_workers_comp": True}}
    facts = {"mailing_address": {"value": "4800 Race St, Denver, CO 80216", "source": "acord_form"}}
    app = {"filename": "ACORD_125.pdf", "doc_type": "application", "text": "", "facts": facts, "flags": {},
           "acord": {"forms": [{"form_id": "ACORD_125", "copy": 1}], "read_keys": sorted(facts)}}
    docs = [dec, app]
    mf, _ = merge_facts(docs, select_primary_truth(docs))
    assert (mf.get("state_of_operations") or {}).get("value") == "CO"
    assert dec["facts"]["state_of_operations"]["value"] == "CO"           # the stored copy too


def test_a_none_answer_rides_the_record():
    from services.acord_intake import primble_record
    none = {"value": "", "source": "producer", "confidence": "high", "value_state": "not_applicable",
            "answer_text": "N/A"}
    rec = {"v": 1, "answers": primble_record._person_answers({"distance_to_hydrant": none}),
           "tables": {}, "ai_boxes": []}
    got = primble_record.apply(rec, {})
    assert got["answers"]["distance_to_hydrant"]["value_state"] == "not_applicable"
    merged = {}
    merge_rules.apply_restored_answers(merged, [_record_doc("ACORD_140.pdf", "", got["answers"], "ACORD_140")])
    assert merged["distance_to_hydrant"]["value_state"] == "not_applicable"
    # A box the form now prints is its statement: the old "None" is not restored
    # - and the key is named as EDITED, so no other form's record restores it
    # either (29 Oct 2026 review; the payload used to be None here).
    facts = {"distance_to_hydrant": {"value": "500 ft", "source": "acord_form"}}
    got = primble_record.apply(rec, facts)
    assert not (got or {}).get("answers") and facts["distance_to_hydrant"]["value"] == "500 ft"
    assert (got or {}).get("edited") == ["distance_to_hydrant"]


def test_a_mixed_documents_other_pages_keep_their_rows():
    from services.acord_intake.intake import overlay_facts
    model = {"facts": {"loss_history": [{"date": f"{i}/1{i}/2024", "description": f"claim {i}", "paid": f"${i},000.00"}
                                        for i in range(1, 9)]}}
    acord = {"facts": {"loss_history": [{"date": "01/11/2024", "description": "claim 1", "paid": "1000"}],
                       "fein": {"value": "84-1234567", "source": "acord_form"}},
             "record": {"read_keys": ["fein", "loss_history"]}}
    overlay_facts(model, acord)
    assert len(model["facts"]["loss_history"]) == 8                       # one claim, read twice, is one
    assert acord["record"]["read_keys"] == ["fein"]                       # the joined list is policed
    # The model read the box pages too (no page markers): the boxes' rows stand.
    m2 = {"facts": {"loss_history": [{"date": "1/1/2024", "paid": "5"}]}}
    overlay_facts(m2, {"facts": {"loss_history": [{"date": "02/02/2024", "paid": "9"}]},
                       "model_reads_acord_pages": True})
    assert m2["facts"]["loss_history"] == [{"date": "02/02/2024", "paid": "9"}]


def test_a_scheduled_bi_limit_clears_the_no_limit_warnings_too():
    from services.cross_form_validator import run_cross_form_validation
    from services.property_coverages import KEY
    from services.sqs_service import evaluate_stops
    facts = {KEY: {"sections": [{"premises": "1", "coverages": [{"kind": "bi", "limit": "$1,000,000"}]},
                                {"premises": "2", "coverages": [{"kind": "bi", "limit": "$25,000"}]}]}}
    flags = {"has_property_coverage": True, "property_has_bi_coverage": True}
    codes = {i["code"] for i in run_cross_form_validation(facts, flags, ["ACORD_140"])}
    assert "bi_coverage_no_limit" not in codes and "bi_missing_period_of_restoration" in codes
    assert not [s for s in evaluate_stops(facts, flags)[1] if "BI limit and Period" in s]
    # No schedule, no limit: still asked.
    assert "bi_coverage_no_limit" in {i["code"] for i in run_cross_form_validation({}, flags, ["ACORD_140"])}


def test_only_a_direct_damage_rows_deductible_is_the_aop():
    from services.property_coverages import KEY, schedule_states_deductible
    peril = {KEY: {"sections": [{"coverages": [{"kind": "", "coverage": "FLOOD", "limit": "$50,000",
                                                "deductible": "$25,000"}]}]}}
    assert schedule_states_deductible(peril) is None
    stock = {KEY: {"sections": [{"coverages": [{"kind": "stock", "limit": "$50,000", "deductible": "$1,000"}]}]}}
    assert schedule_states_deductible(stock) == "$1,000"


def test_an_excluded_acord_document_changes_nothing():
    merged = {"property_locations": [{"location_number": "1", "year_built": "1999"}]}
    before = copy.deepcopy(merged)
    gone = _app({"applicant_name": {"value": "Choice Electric LLC", "source": "acord_form"}})
    gone["excluded"] = True
    assert merge_rules.apply_owner_rules(merged, [_doc("dec.pdf", {}), gone]) == []
    assert merged == before


# ── 16. The SQS summary (cover page) carries the record too ────────────────────

import pytest


@pytest.fixture
def _fernet(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _blank_pdf() -> bytes:
    import io
    import pikepdf
    pdf = pikepdf.new()
    pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _package_session():
    from services.policy_lines import STORE_KEY
    from services.schedule_capture import mark_human_rows
    facts = {"applicant_name": {"value": "Choice Electric LLC", "source": "ai"},
             "effective_date": {"value": "01/01/2027", "source": "derived"},
             "expiration_date": {"value": "01/01/2028", "source": "derived"},
             "occupancy_type": {"value": "Office", "source": "producer"},
             "_explained_issue_codes": {"value": ["legacy_loss_narrative_mismatch"], "source": "producer"},
             "gl_class_code_schedule": [{"class_code": "92478", "classification": "Electrical work"}],
             STORE_KEY: {"v": 1, "edits": {"crime#unnumbered": {"fields": {"premium": "$500"}}},
                         "added": [], "flags_set": {}}}
    mark_human_rows(facts, "gl_class_code_schedule", "producer")
    return {"facts": facts, "generated_forms": {}}


def test_the_cover_carries_answers_tables_and_policy_edits(tmp_path, _fernet):
    from routes.download_routes import _cover_with_record
    from services.acord_intake import primble_record
    from services.policy_lines import STORE_KEY
    raw = _blank_pdf()
    out = _cover_with_record(raw, _package_session())
    assert out != raw and b"Office" not in out                  # hidden and encrypted
    p = tmp_path / "00_Primble_Cover_Page.pdf"
    p.write_bytes(out)
    rec = primble_record.read(str(p))
    assert rec["form"] == primble_record.SUMMARY_FORM
    got = primble_record.summary_payload(rec)
    assert got["applicant"] == "Choice Electric LLC"
    assert got["answers"]["occupancy_type"]["value"] == "Office"
    assert got["answers"]["_explained_issue_codes"]["value"] == ["legacy_loss_narrative_mismatch"]
    assert got["tables"]["gl_class_code_schedule"]["rows"][0]["class_code"] == "92478"
    assert got["stores"][STORE_KEY]["edits"]["crime#unnumbered"]["fields"]["premium"] == "$500"


def test_a_last_year_cover_restores_nothing(_fernet):
    from services.acord_intake import primble_record
    rec = {"v": 2, "form": primble_record.SUMMARY_FORM, "applicant": "X",
           "term": {"effective_date": "01/01/2023", "expiration_date": "01/01/2024"},
           "answers": {"occupancy_type": {"value": "Office", "source": "producer"}}}
    assert primble_record.summary_payload(rec) is None
    assert primble_record.summary_payload(dict(rec, form="ACORD_125")) is None    # not a summary


def test_an_uploaded_cover_is_read_by_its_record_alone(tmp_path, _fernet):
    from routes.download_routes import _cover_with_record
    from services.acord_intake import intake
    p = tmp_path / "cover.pdf"
    p.write_bytes(_cover_with_record(_blank_pdf(), _package_session()))
    r = intake.read_for_document(str(p), "PRIMBLE SUBMISSION SUMMARY Package Score 100 ...")
    assert r["classification"]["doc_type"] == "primble_summary" and r["other_text"] == ""
    assert r["facts"] == {} and r["record"]["primble_summary"] is True
    # sealed at rest since the production review (29 Oct): read through the one door
    from services.acord_intake.primble_record import restored_of
    assert restored_of(r["record"])["answers"]["occupancy_type"]["value"] == "Office"
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(_blank_pdf())
    assert intake.read_for_document(str(plain), "") is None or \
        not (intake.read_for_document(str(plain), "") or {}).get("record", {}).get("primble_summary")


def _summary_doc(applicant="Choice Electric LLC", **extra):
    payload = {"applicant": applicant,
               "answers": {"occupancy_type": {"value": "Office", "source": "producer"}},
               "tables": {}, "stores": {}}
    payload.update(extra)
    return {"filename": "00_Primble_Cover_Page.pdf", "doc_type": "primble_summary", "facts": {},
            "supporting_only": True, "acord": {"forms": [], "primble_summary": True, "restored": payload}}


def test_the_cover_restores_beside_the_declarations_alone():
    from services.policy_lines import STORE_KEY
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page",
           "facts": {"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"}}}
    store = {"v": 1, "edits": {"crime#unnumbered": {"fields": {"premium": "$500"}}}, "added": [], "flags_set": {}}
    merged = {}
    merge_rules.apply_owner_rules(merged, [dec, _summary_doc(stores={STORE_KEY: store})])
    assert merged["occupancy_type"]["value"] == "Office"
    assert merged[STORE_KEY]["edits"]["crime#unnumbered"]["fields"]["premium"] == "$500"


def test_another_insureds_cover_restores_nothing():
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page",
           "facts": {"applicant_name": {"value": "Harborline Plumbing LLC", "source": "ai"}}}
    merged = {}
    merge_rules.apply_owner_rules(merged, [dec, _summary_doc()])
    assert "occupancy_type" not in merged
    merged = {}
    merge_rules.apply_owner_rules(merged, [dec, _summary_doc(applicant="")])       # names nobody
    assert "occupancy_type" not in merged


def test_a_policy_edit_made_after_the_reupload_beats_the_record():
    from services.policy_lines import STORE_KEY, carry_and_apply
    restored = {"v": 1, "edits": {"crime#unnumbered": {"fields": {"premium": "$500"}}}, "added": [], "flags_set": {}}
    newer = {"v": 1, "edits": {"crime#unnumbered": {"fields": {"premium": "$650"}}}, "added": [], "flags_set": {}}
    merged = {STORE_KEY: restored}
    carry_and_apply(merged, {}, [], {STORE_KEY: newer})
    assert merged[STORE_KEY]["edits"]["crime#unnumbered"]["fields"]["premium"] == "$650"


def test_a_restored_location_table_writes_the_package_cope():
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page",
           "facts": {"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"}}}
    rows = [{"location_number": "1", "building_number": "001", "construction_type": "FRAME",
             "year_built": "2005", "roof_year": "2018", "protection_class": "3", "sprinkler": "0"}]
    cover = _summary_doc(tables={"property_locations": {"rows": rows, "saved_by": "producer"}})
    merged = {}
    merge_rules.apply_owner_rules(merged, [dec, cover])
    assert (merged.get("construction_type") or {}).get("value") == "FRAME"
    assert (merged.get("year_built") or {}).get("value") == "2005"


# ── Orbin round trip (27 Oct night) ──────────────────────────────────────────
def test_the_125_other_insurance_rows_come_back_as_policy_records():
    from services.acord_intake.read import _join_line_rows, _other_insurance_rows
    copies = [{"form_id": "ACORD_125", "boxes": {
        "OtherPolicy_LineOfBusinessCode_A": "Commercial General Liability",
        "OtherPolicy_PolicyNumberIdentifier_A": "BBC7263 - 26",
        "OtherPolicy_LineOfBusinessCode_B": "Commercial Inland Marine",
        "OtherPolicy_PolicyNumberIdentifier_B": "6C7-40-02---26",
        "OtherPolicy_LineOfBusinessCode_C": "Commercial Auto",          # no number: never one box alone
    }}]
    rows = _other_insurance_rows(copies)
    assert rows == [{"line": "Commercial General Liability", "policy_number": "BBC7263 - 26"},
                    {"line": "Commercial Inland Marine", "policy_number": "6C7-40-02---26"}]
    lines = {"General Liability": {"line": "General Liability", "carrier": "EMC"}}
    _join_line_rows(lines, rows)
    assert lines["General Liability"]["policy_number"] == "BBC7263 - 26"   # joined, not doubled
    assert any(r["line"] == "Commercial Inland Marine" for r in lines.values())
    assert len(lines) == 2


def test_a_location_row_with_no_identity_joins_the_one_premises():
    from services.acord_intake import merge_rules as M
    one = [[{"address_line1": "4800 Dahlia St", "address_city": "Denver", "location_number": "1"}],
           [{"full_time_employees": "6"}]]
    out = M.fold_rows("property_locations", one, [True, True])
    assert out == [{"address_line1": "4800 Dahlia St", "address_city": "Denver",
                    "location_number": "1", "full_time_employees": "6"}]
    two = [[{"address_line1": "1 A St", "location_number": "1"},
            {"address_line1": "2 B St", "location_number": "2"}], [{"full_time_employees": "6"}]]
    out = M.fold_rows("property_locations", two, [True, True])
    assert [r.get("location_number") for r in out] == ["1", "2"]          # beside several: dropped
    assert all("full_time_employees" not in r for r in out)


def test_the_131_any_auto_tick_comes_back_as_liability_symbol_1():
    from services.acord_intake.read import boxes_to_facts
    copies = [{"form_id": "ACORD_131", "copy": 1, "kinds": {"UnderlyingCoverage_Coverage_AnyAutoIndicator_A": "check"},
               "box_page": {}, "raw": {}, "boxes": {"UnderlyingCoverage_Coverage_AnyAutoIndicator_A": "/1"}}]
    facts, _carried = boxes_to_facts(copies)
    assert facts.get("auto_covered_symbols") == [{"coverage": "liability", "symbols": [1]}]


def test_an_ai_box_comes_back_onto_its_own_box_never_a_fact():
    from services.acord_intake.read import _carry_ai_boxes
    facts = {"gl_deductible": {"value": "1,000", "source": "ai", "restored_from": "primble_record",
                               "box": "GeneralLiability_PropertyDamage_DeductibleAmount_A", "acord_form": "ACORD_126"},
             "fein": {"value": "12-3456789", "source": "acord_form", "box": "NamedInsured_TaxIdentifier_A",
                      "acord_form": "ACORD_126"}}
    carried = {}
    _carry_ai_boxes(facts, carried)
    assert "gl_deductible" not in facts and "fein" in facts
    assert carried == {"ACORD_126": {"GeneralLiability_PropertyDamage_DeductibleAmount_A": "1,000"}}


def test_the_record_carries_the_narrative_reading_and_typed_parts():
    from services.acord_intake import primble_record as R
    from services.narrative_reader import READING_KEY
    facts = {"additional_remarks_text": {"value": "Our story.", "source": "producer", "typed_parts": ["Our story."]},
             READING_KEY: {"abc123": {"components": ["management"]}}}
    assert R._person_answers(facts)["additional_remarks_text"]["typed_parts"] == ["Our story."]
    assert R._person_stores(facts)[READING_KEY] == {"abc123": {"components": ["management"]}}


def test_a_cover_alone_restores_the_insured_and_the_term_into_gaps_only():
    from services.acord_intake import merge_rules as M
    cover = {"filename": "cover.pdf", "acord": {"primble_summary": True, "forms": [], "restored": {
        "answers": {}, "tables": {}, "stores": {}, "applicant": "Choice Electric LLC",
        "term": {"effective_date": "06/01/2026", "expiration_date": "06/01/2027"}}}}
    merged = {}
    M.apply_restored_answers(merged, [cover])
    assert merged["applicant_name"]["value"] == "Choice Electric LLC"
    assert merged["effective_date"]["value"] == "06/01/2026"
    stated = {"effective_date": {"value": "07/01/2026", "source": "ai"}}
    M.apply_restored_answers(stated, [cover])
    assert stated["effective_date"]["value"] == "07/01/2026"          # a document's statement wins


def test_two_buildings_at_one_street_address_stay_two_rows():
    import copy
    from services import extraction_service as E
    rows = [{"building_number": "001", "address_line1": "1234 W Colfax Ave", "building_value": "$798,556"},
            {"building_number": "002", "address_line1": "1234 W Colfax Ave", "building_value": "$421,714"},
            {"address_line1": "1234 W Colfax Ave", "annual_revenue": "3,200,000"}]
    f = {"property_locations": copy.deepcopy(rows)}
    E._consolidate_property_locations(f, "", [])
    out = f["property_locations"]
    out = out.get("value") if isinstance(out, dict) else out
    assert [(r.get("building_number"), r.get("building_value")) for r in out] == [
        ("001", "$798,556"), ("002", "$421,714")]
    assert out[0].get("annual_revenue") == "3,200,000"      # the premises-wide row joins building 1


def test_a_value_only_the_loss_runs_stated_never_verifies_the_loss_runs():
    """Orbin round trip, 28 Oct: the FEIN came only from the loss runs, ACORD 125
    printed it, and re-uploaded it matched the loss runs to themselves (85 -> 100)."""
    from services.acord_intake import primble_record as R
    from services.loss_run_identity import _package_identity
    session = {"facts": {"fein": {"value": "47-2918364", "source": "ai"}},
               "docs": [{"doc_type": "loss_run", "facts": {"fein": {"value": "47-2918364"}}},
                        {"doc_type": "dec_page", "facts": {"applicant_name": {"value": "Orbin"}}}]}
    assert R._loss_run_only_facts(session) == {"fein": "47-2918364"}
    box = {"fein": {"value": "47-2918364", "source": "acord_form", "box": "NamedInsured_TaxIdentifier_A"},
           "applicant_name": {"value": "Orbin Contracting LLC", "source": "acord_form"}}
    R.apply({"applicant": "Orbin Contracting LLC", "loss_run_only": {"fein": "47-2918364"}, "answers": {}}, box)
    assert box["fein"]["echo_of"] == "loss_run"
    ident = _package_identity([{"doc_type": "application", "facts": box}], {})
    assert ident["fein"] == []
    # A FEIN the declarations print too is the documents' own - it still counts.
    both = dict(session, docs=session["docs"] + [{"doc_type": "dec_page", "facts": {"fein": {"value": "47-2918364"}}}])
    assert R._loss_run_only_facts(both) == {}
