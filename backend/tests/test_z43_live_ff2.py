"""Live run ff2ba3e5 (25 Oct 2026): bugs found filling the owner's package."""
from services.extraction_service import drop_unmentioned_ai_yes_no


def _doc(text, value="False"):
    return {"text": text, "facts": {"agreed_value_endorsement": {"value": value, "source": "ai"}}}


def test_listed_coverage_option_drops_the_ai_no():
    d = _doc("COVERAGE: PERSONAL PROPERTY-INSURED\nCoverage Option(s):\nAGREED VALUE\n"
             "REPLACEMENT COST\nLIMIT COINSURANCE DEDUCTIBLE\n$73,008 80% $5,000\n")
    assert drop_unmentioned_ai_yes_no(d) == ["agreed_value_endorsement"]


def test_empty_optional_coverages_header_is_not_an_option():
    d = _doc("OPTIONAL COVERAGES\nAgreed Value Replacement Cost (X)\nSEE SCHEDULE\n")
    assert drop_unmentioned_ai_yes_no(d) == []


def test_agreement_is_not_agreed():
    d = _doc("This agreement is part of the policy. Stated value of the vehicle.")
    assert drop_unmentioned_ai_yes_no(d) == ["agreed_value_endorsement"]


def test_a_stated_no_on_agreed_value_stays():
    d = _doc("AGREED VALUE: NO\nCOINSURANCE 80%\n")
    assert drop_unmentioned_ai_yes_no(d) == []


def test_option_after_the_column_heading_is_not_read():
    d = _doc("Coverage Option(s):\nREPLACEMENT COST\nLIMIT\nAGREED VALUE\n")
    assert drop_unmentioned_ai_yes_no(d) == []


def test_loss_label_follows_the_narrative_when_it_contradicts_no_claims():
    from services.sqs_service import _get_loss_history_state, calculate_p4_loss_history
    facts = {
        "loss_history_no_prior_losses_indicator": {"value": "No - no claims or losses in the past 5 years", "source": "producer"},
        "additional_remarks_text": {"value": "Loss History Discussion: loss history shows 12 claims in the past five years, 4 still open.", "source": "producer"},
    }
    score, _ = calculate_p4_loss_history(facts, {}, False, "no_loss_run")
    state = _get_loss_history_state(facts, {})
    if score is not None:      # the pillar is scored, so the label must not say "left out"
        assert state != "no_known_losses_not_applicable"


def test_dec_page_product_is_not_the_submission_program():
    from services.extraction_service import drop_dec_page_submission_details
    d = {"doc_type": "dec_page", "facts": {"submission_program_name": {"value": "Chubb Cyber Enterprise Risk", "source": "ai"}}}
    assert drop_dec_page_submission_details(d) == ["submission_program_name"]
    q = {"doc_type": "quote", "facts": {"submission_program_name": {"value": "Contractors Select", "source": "ai"}}}
    assert drop_dec_page_submission_details(q) == []
    a = {"doc_type": "dec_page", "facts": {"submission_carrier_name": {"value": "Granite Arch", "source": "ai"},
                                           "submission_program_name": {"value": "Contractors Select", "source": "ai"}}}
    assert drop_dec_page_submission_details(a) == []


def _pc(*rows):
    return {"_property_coverages": {"sections": [{"coverages": list(rows)}]}}


def test_coinsurance_and_valuation_from_an_agreeing_schedule():
    from services.extraction_service import derive_policy_terms_from_property_schedule as d
    mf = _pc({"kind": "building", "coinsurance": "80%", "valuation": "R"},
             {"kind": "bpp", "coinsurance": "80%", "valuation": "R"},
             {"kind": "bi", "coinsurance": "50%"})
    assert d(mf) == ["coinsurance_percentage", "valuation_method"]
    assert mf["coinsurance_percentage"]["value"] == "80%" and mf["valuation_method"]["value"] == "RCV"


def test_disagreeing_schedule_or_an_existing_value_gives_nothing():
    from services.extraction_service import derive_policy_terms_from_property_schedule as d
    mf = _pc({"kind": "building", "coinsurance": "80%"}, {"kind": "bpp", "coinsurance": "90%"})
    assert d(mf) == []
    mf = _pc({"kind": "building", "coinsurance": "80%"})
    mf["coinsurance_percentage"] = {"value": "100%", "source": "producer"}
    assert d(mf) == [] and mf["coinsurance_percentage"]["value"] == "100%"


def test_a_percent_box_takes_the_percent_sign():
    from services.answer_semantics import interpret_answer
    for typed in ("80%", "80 %", "80 percent", "80"):
        r = interpret_answer("coinsurance_percentage", typed)
        assert r.accepted and r.value == "80", typed


def test_a_loss_run_period_of_bare_years_counts_its_years():
    from services.loss_history_state import loss_period_date, loss_run_coverage
    docs = [{"doc_type": "loss_run", "filename": "a.csv", "facts": {"loss_run_period_start": "2021", "loss_run_period_end": "2025"}}]
    cov = loss_run_coverage(docs, {})
    assert cov["documents"][0]["years"] == [2021, 2022, 2023, 2024, 2025], cov
    assert str(loss_period_date("2021")) == "2021-01-01"
    assert str(loss_period_date("2025", end=True)) == "2025-12-31"
    assert str(loss_period_date("01/01/2025")) == "2025-01-01"


def test_vehicle_use_counts_only_beside_a_use_label():
    from services.extraction_service import drop_unlabelled_vehicle_use
    title = {"text": "COMMERCIAL AUTO | SAMPLE DRIVER SCHEDULE\nFull Name | Date of Birth\n",
             "facts": {"auto_vehicle_use": {"value": "commercial", "source": "ai"}}}
    assert drop_unlabelled_vehicle_use(title) and "auto_vehicle_use" not in title["facts"]
    dec = {"text": "Classification Business Use SizeGVW Radius s=service r=retail c=commercial\n",
           "facts": {"auto_vehicle_use": {"value": "service", "source": "ai"}}}
    assert not drop_unlabelled_vehicle_use(dec)
    person = {"text": "nothing", "facts": {"auto_vehicle_use": {"value": "commercial", "source": "producer"}}}
    assert not drop_unlabelled_vehicle_use(person)


def test_coverage_label_names_the_last_policy_year():
    from services.loss_history_state import loss_run_coverage
    f = {"effective_date": "01/01/2027", "expiration_date": "01/01/2028"}
    for end in ("2025", "01/01/2026"):
        docs = [{"doc_type": "loss_run", "filename": "a.csv",
                 "facts": {"loss_run_period_start": "2021" if end == "2025" else "01/01/2021", "loss_run_period_end": end}}]
        f2 = dict(f, loss_run_period_start=docs[0]["facts"]["loss_run_period_start"], loss_run_period_end=end,
                  prior_expiration_date="01/01/2026", prior_effective_date="01/01/2025")
        cov = loss_run_coverage(docs, f2)
        assert cov["years"] and cov["years"][-1] == 2025, (end, cov)


def test_a_data_row_is_no_explanation_and_a_type_word_needs_a_document():
    from services.ai_answer_guards import is_data_table_row, unstated_type_word, _norm
    assert is_data_table_row("Hannah Price | 05/04/1997 | CO | 02/03/2025 | 7")
    assert not is_data_table_row("V009 | 2017 Chevrolet Express | damage")
    tu = "Enter text: The type of contact being described (e.g. accounting, claims, etc.). "
    assert unstated_type_word("Inspection", tu, _norm("eric berger owner"))
    assert not unstated_type_word("Claims", tu, _norm("claims contact jane"))


def test_gl_pd_deductible_needs_property_damage_wording():
    from services.ai_answer_guards import qualifier_not_stated
    f = "GeneralLiability_PropertyDamage_DeductibleAmount_A"
    assert qualifier_not_stated(f, "5,000", "BUILDING LIMIT COINSURANCE DEDUCTIBLE $798,556 80% $5,000")
    assert not qualifier_not_stated(f, "5,000", "Property Damage Deductible $5,000 per claim")


def test_a_percent_deductible_is_no_limit():
    from services.ai_answer_guards import percent_deductible_as_limit, amount_not_for_this_coverage
    raw = "COVERAGE: BUILDING\nWINDSTORM OR HAIL DEDUCTIBLE: 2%\nINFLATION GUARD 4%\n"
    assert percent_deductible_as_limit("CommercialPropertyCoverage_WindHail_LimitAmount_A", "2%", raw)
    assert not percent_deductible_as_limit("CommercialPropertyCoverage_WindHail_DeductibleAmount_A", "2%", raw)
    assert not percent_deductible_as_limit("CommercialPropertyCoverage_InflationGuard_LimitAmount_A", "4%", raw)
    # A wind / hail deductible applies to named storms too (Z42 review B) - it stands.
    assert not amount_not_for_this_coverage("CommercialPropertyCoverage_NamedWindstorm_DeductibleAmount_A", "2%", raw)
    assert not amount_not_for_this_coverage("CommercialPropertyCoverage_WindHail_DeductibleAmount_A", "2%", raw)


def test_140_inflation_guard_and_borrowed_improvement_year():
    from services.ai_answer_guards import qualifier_not_stated, improvement_year_is_another_year
    assert qualifier_not_stated("CommercialProperty_Premises_InflationGuardPercent_A", "80%",
                                "LIMIT COINSURANCE DEDUCTIBLE $798,556 80% $5,000\nInflation Guard (%): Bldg. %")
    assert not qualifier_not_stated("CommercialProperty_Premises_InflationGuardPercent_A", "4%",
                                    "Inflation Guard (%): Bldg. 4%")
    mapped = {"BuildingImprovement_RoofingYear_A": "2018", "CommercialStructure_BuiltYear_A": "2005"}
    assert improvement_year_is_another_year("BuildingImprovement_OtherYear_A", "2018", mapped)
    assert improvement_year_is_another_year("BuildingImprovement_WiringYear_A", "2005", mapped)
    assert not improvement_year_is_another_year("BuildingImprovement_WiringYear_A", "2019", mapped)
    assert not improvement_year_is_another_year("BuildingImprovement_RoofingYear_A", "2018", mapped)


def test_excess_retention_is_no_todo_once_its_attachment_is_known():
    from services.needs_attention import _retention_settled
    f = {"umbrella_sir": {"value": "0", "source": "ai"}}
    assert _retention_settled("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A", f, "ACORD_131")
    assert not _retention_settled("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A", {}, "ACORD_131")
    assert not _retention_settled("GeneralLiability_EachOccurrence_LimitAmount_A", f, "ACORD_131")


def test_a_negative_number_is_refused_not_stripped():
    from services.answer_semantics import interpret_answer
    for f, v in (("years_in_business", "-3"), ("total_revenue", "-$100"), ("coinsurance_percentage", "-5%")):
        r = interpret_answer(f, v)
        assert not r.accepted and "negative" in r.message, (f, v, r)
    assert interpret_answer("years_in_business", "3").value == "3"


def test_a_column_heading_is_no_contact_type():
    from services.ai_answer_guards import unstated_type_word, _norm
    tu = "Enter text: The type of contact being described (e.g. accounting, claims, etc.). "
    raw = _norm("Full Name | Date of Birth | Claims contact: Jane")
    assert unstated_type_word("Full Name", tu, raw)
    assert not unstated_type_word("Claims", tu, raw)


def test_equipment_breakdown_deductible_is_its_own_schedule_amount():
    from services.ai_answer_guards import amount_not_for_this_coverage
    raw = ("DEDUCTIBLE\n$500. Exceptions: SEE SCHEDULE\nCOVERAGE: BUILDING-EQUIPMENT BREAKDOWN\n"
           "LIMIT DEDUCTIBLE\nINCLUDED $5,000\n")
    f = "CommercialPropertyCoverage_EquipmentBreakdown_DeductibleAmount_A"
    assert amount_not_for_this_coverage(f, "$500", raw)
    assert not amount_not_for_this_coverage(f, "$5,000", raw)


def test_typing_a_premium_back_to_the_documents_value_clears_the_edit():
    import services.policy_lines as pl
    store = {"v": 1, "edits": {"cyber#x": {"fields": {"premium": "$5,555"}, "anchor": {}}}, "added": [], "flags_set": {}}
    orig = pl.find_row
    pl.find_row = lambda facts, key: {"premium": "$4,162" if not (facts.get(pl.STORE_KEY) or {}).get("edits") else "$5,555"}
    try:
        assert pl._fields_back_to_documents({}, store, "cyber#x", {"premium": "$4,162"}) == {"premium"}
        assert pl._fields_back_to_documents({}, store, "cyber#x", {"premium": "$7,000"}) == set()
    finally:
        pl.find_row = orig


def test_a_fein_confirmed_in_data_consistency_still_matches_the_loss_runs():
    from services.loss_run_identity import _package_identity
    for env in ({"value": "84-1234567", "source": "producer"},
                {"value": "84-1234567", "source": "user_confirmed", "confidence": "client_arq"}):
        assert "84-1234567" in _package_identity([], {"fein": env})["fein"], env
    assert "84-1234567" not in _package_identity([], {"fein": {"value": "84-1234567", "source": "ai"}})["fein"]


def test_umbrella_underlying_question_lists_only_the_lines_under_it():
    import services.questionnaire as qn
    import services.policy_lines as pl
    import services.umbrella_layers as ul
    rows = [{"line": l, "line_label": l} for l in ("auto", "general_liab", "workers_comp", "property", "cyber", "umbrella")]
    o1, o2 = pl.table_rows, ul.applicable_underlying_lines
    pl.table_rows = lambda facts, docs=None: rows
    ul.applicable_underlying_lines = lambda view: ["general_liab", "auto", "workers_comp"]
    try:
        page = type("P", (), {"facts": {}, "docs": [], "flags": {}, "statuses": {}})()
        out = qn._read_underlying(qn.QUESTIONS["H.1c"], page)
    finally:
        pl.table_rows, ul.applicable_underlying_lines = o1, o2
    if True:
        assert "property" not in (out["display_value"] or "") and "cyber" not in (out["display_value"] or "")
        assert "general_liab" in out["display_value"]


def test_typed_back_uses_the_value_recorded_with_the_first_edit():
    import services.policy_lines as pl
    store = {"edits": {"cyber#x": {"fields": {"premium": "$5,555"}, "originals": {"premium": "$4,162"}}}}
    assert pl._fields_back_to_documents({}, store, "cyber#x", {"premium": "$4,162"}) == {"premium"}
    assert pl._fields_back_to_documents({}, store, "cyber#x", {"premium": "$7,000"}) == set()


def test_a_carrier_entry_recorded_as_a_heading_still_names_the_rows():
    import tests.test_document_carrier_rows_14oct as base
    import services.extraction_service as es
    doc = base._pkg(rows=[base._row("Commercial General Liability", "$ 16,818.00")])
    doc["facts"]["dec_page_entries"] = [{"label": base.CARRIER, "owner": "carrier", "value": base.CARRIER}]
    assert es.assign_document_carrier_to_rows(doc) == [f"Commercial General Liability={base.CARRIER}"]


def test_a_coverage_part_menu_keeps_the_part_with_its_own_section():
    from services.extraction_service import _part_has_own_section
    text = ("Item 4. Coverage(s) Applicable to this Policy:\nDirectors & Officers and Entity Liability Coverage Part\n"
            "Employment Practices Liability Coverage Part\nFiduciary Liability Coverage Part\n"
            "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART\n(A) Aggregate Limit of Liability: $1,000,000\n")
    assert _part_has_own_section(text, "Employment Practices Liability")
    assert not _part_has_own_section(text, "Directors & Officers and Entity Liability")
    assert not _part_has_own_section(text, "Fiduciary Liability")


def test_the_insureds_own_owner_is_no_additional_interest():
    from services.ai_answer_guards import _is_the_insureds_own_party
    facts = {"contact_name": {"value": "Eric Berger", "source": "producer"}, "applicant_name": "CHOICE ELECTRIC LLC"}
    assert _is_the_insureds_own_party("Eric Berger", facts)
    assert _is_the_insureds_own_party("Choice Electric LLC", facts)
    assert not _is_the_insureds_own_party("First Bank of Denver", facts)


def test_a_menu_of_coverage_parts_keeps_only_the_part_with_its_own_section():
    from services.extraction_service import drop_menu_only_parts
    text = ("Item 4. Coverage(s) Applicable to this Policy:\nDirectors & Officers and Entity Liability Coverage Part\n"
            "Employment Practices Liability Coverage Part\nCrime Coverage Part\n"
            "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART\n(A) Aggregate Limit of Liability: $1,000,000\n")
    row = lambda l: {"line": l, "carrier": "Federal", "premium": None, "policy_number": None,
                     "effective_date": "January 1, 2025", "expiration_date": "January 1, 2026"}
    doc = {"text": text, "facts": {"coverage_lines": [row("Directors & Officers and Entity Liability"),
                                                      row("Employment Practices Liability"), row("Crime")]}}
    assert drop_menu_only_parts(doc) == ["Directors & Officers and Entity Liability", "Crime"]
    assert [r["line"] for r in doc["facts"]["coverage_lines"]] == ["Employment Practices Liability"]
    priced = {"text": text, "facts": {"coverage_lines": [dict(row("Crime"), premium="$500"), row("Employment Practices Liability")]}}
    assert drop_menu_only_parts(priced) == []


def test_a_stated_dividend_plan_is_a_participating_policy():
    from services.pdf_service import _resolve_dividend_plan_box, _SCHED_SKIP
    f = {"_form_id": "ACORD_130", "dec_page_entries": [{"label": "DIVIDEND PLAN", "value": "Blue I (B1) Dividend Plan"}]}
    assert _resolve_dividend_plan_box("Policy_ParticipatingIndicator_A", f) == "Yes"
    assert _resolve_dividend_plan_box("Policy_NonParticipatingIndicator_A", f) is None
    assert _resolve_dividend_plan_box("Policy_ParticipatingIndicator_A", {"_form_id": "ACORD_130"}) is _SCHED_SKIP
