"""Live run 11 (session 2ac7c1b7, 15 Sep 2026, Orbin policy only).

1. A phantom Workers' Compensation policy. The premium table's "Section 6
   Coverage Premium: No Coverage" came back attributed to WC AND to the page's
   policy 6C7 (the Inland Marine contract); the per-line index made 6C7 the WC
   number, "Policies in this submission" listed five policies, and ACORD 131
   printed an Employers Liability underlying row plus $1,000,000 E.L. limits.
2. The GL schedule's "Location 000" exclusion / endorsement lines (no class
   code, no basis) printed a third 126 hazard row and blanked $ PAID TO
   SUBCONTRACTORS and the TYPE OF WORK.
3. 126 OTHER coverage printed "Fungi Or Bacteria Exclusion; ...".
4. 131 Q7 "Y", explained by the package's own underlying lines.
5. 125 CYBER AND PRIVACY ticked off a GL "Exclusion - Cyber Incident".
6. 127 BODY "SEDAN", read off "2012 SUBARU OUTBACK SEDAN" (owner: blank).
7. 127 comp deductible "$ 1000 DEDUCTIBLE FOR ALL PERILS ..." blanked as prose.
"""
import copy
import json
import os

import pytest

import services.extraction_service as es
import services.pdf_service as ps

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IM, _AUTO, _GL, _UMB = "6C7-40-02---26", "6E7-40-02---26", "BBC7263 - 26", "6J7-40-02---26"
_EMC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
_WC_DENIAL = {"label": "Section 6 Coverage Premium", "value": "No Coverage", "section": "Coverages and Premium",
              "owner": "policy", "policy_number": _IM, "line_of_business": "Workers Compensation"}
_ENTRIES = [
    _WC_DENIAL,
    {"label": "Inland Marine Premium", "value": "$300.00", "section": "Commercial Inland Marine Declarations",
     "owner": "policy", "policy_number": _IM, "line_of_business": "Commercial Inland Marine"},
    {"label": "Policy Premium", "value": "$3,954.00", "section": "General Liability Declarations",
     "owner": "policy", "policy_number": _GL, "line_of_business": "General Liability"},
    {"label": "COVERED AUTOS LIABILITY", "value": "$ 1,496.00", "section": "Commercial Auto Declarations",
     "owner": "policy", "policy_number": _AUTO, "line_of_business": "Commercial Auto"},
    {"label": "Umbrella Premium", "value": "$3,418.00", "section": "Commercial Umbrella Declarations",
     "owner": "policy", "policy_number": _UMB, "line_of_business": "Commercial Umbrella"},
]
_WC_FAMILY = ("workers compensation", "employers liability")


@pytest.fixture(autouse=True)
def _no_llm_judge(monkeypatch):
    """The evidence judge is an LLM call; these tests never make one."""
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)


def _row(line, pn=None, premium=None, carrier=_EMC):
    return {"line": line, "carrier": carrier, "naic": None, "policy_number": pn, "premium": premium,
            "effective_date": "07/15/25", "expiration_date": "07/15/26"}


def _lines(wc_number=None):
    return [_row("Liability", _GL, "$3,954.00", "EMC Property & Casualty Company"),
            _row("Inland Marine", _IM, "$300.00"), _row("Automobile", _AUTO, "$2,991.00"),
            _row("Workers' Compensation", wc_number), _row("Umbrella", _UMB, "$3,418.00")]


def _wc_row(lines):
    return next(r for r in lines if r["line"] == "Workers' Compensation")


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. The phantom WC policy ─────────────────────────────────────────────────

def test_a_denial_entry_names_no_number_for_its_line():
    for by in (es.current_numbers_by_line(_ENTRIES, {}), es._policy_numbers_by_line(_ENTRIES)):
        assert "workers_comp" not in by
        assert by["inland_marine"] == {_IM}
    assert all(_IM != n or "workers_comp" not in ls for n, ls in es._entry_home_lines(_ENTRIES).items())


def test_a_denial_in_the_label_names_no_number_either():
    e = {"label": "Workers Compensation - No Coverage", "value": "", "policy_number": _IM,
         "line_of_business": "Workers Compensation", "section": "Workers Compensation"}
    assert "workers_comp" not in es.current_numbers_by_line([e], {})
    assert es._entry_home_lines([e]) == {}


def test_run11_the_wc_row_is_never_numbered():
    mf = {"coverage_lines": _lines(), "dec_page_entries": copy.deepcopy(_ENTRIES)}
    filled = es._fill_missing_line_numbers(mf)
    assert _wc_row(mf["coverage_lines"])["policy_number"] is None
    assert not any("Workers" in f for f in filled)


def test_another_entry_giving_wc_a_number_does_not_number_a_denied_row():
    extra = {"label": "Employers Liability", "value": "$1,000,000", "section": "Schedule of Underlying Insurance",
             "owner": "policy", "policy_number": _IM, "line_of_business": "Workers Compensation"}
    mf = {"coverage_lines": _lines(), "dec_page_entries": copy.deepcopy(_ENTRIES) + [extra]}
    assert es.current_numbers_by_line(mf["dec_page_entries"], {})["workers_comp"] == {_IM}
    es._fill_missing_line_numbers(mf)
    assert _wc_row(mf["coverage_lines"])["policy_number"] is None


def test_an_extraction_numbered_wc_row_is_cleared_by_the_repair():
    mf = {"coverage_lines": _lines(wc_number=_IM), "dec_page_entries": copy.deepcopy(_ENTRIES)}
    es._repair_coverage_lines_from_entries(mf)
    assert _wc_row(mf["coverage_lines"])["policy_number"] is None
    assert next(r for r in mf["coverage_lines"] if r["line"] == "Inland Marine")["policy_number"] == _IM


def test_a_granted_unnumbered_row_is_still_filled():
    lines = _lines()
    next(r for r in lines if r["line"] == "Inland Marine")["policy_number"] = None
    mf = {"coverage_lines": lines, "dec_page_entries": copy.deepcopy(_ENTRIES)}
    assert es._fill_missing_line_numbers(mf) == [f"Inland Marine -> {_IM}"]


@pytest.mark.parametrize("premium,expected", [(None, None), ("$500", "PKG 100200")])
def test_a_bare_mention_on_another_lines_pages_is_not_numbered(premium, expected):
    entries = [{"label": "Inland Marine", "value": "Included", "section": "Common Policy Declarations",
                "owner": "policy", "policy_number": "PKG 100200", "line_of_business": "Inland Marine"},
               {"label": "Building", "value": "$500,000", "section": "Commercial Property Declarations",
                "owner": "policy", "policy_number": "PKG 100200", "line_of_business": "Commercial Property"}]
    mf = {"coverage_lines": [_row("Inland Marine", None, premium)], "dec_page_entries": entries}
    es._fill_missing_line_numbers(mf)
    assert mf["coverage_lines"][0]["policy_number"] == expected


@pytest.mark.parametrize("section", ["Limits of Insurance", "Common Policy Declarations", "Information Page"])
def test_a_number_with_no_home_pages_still_fills(section):
    entries = [{"label": "Each Occurrence", "value": "$1,000,000", "section": section, "owner": "policy",
                "policy_number": "GL 7781-26", "line_of_business": "General Liability"}]
    mf = {"coverage_lines": [_row("General Liability")], "dec_page_entries": entries}
    es._fill_missing_line_numbers(mf)
    assert mf["coverage_lines"][0]["policy_number"] == "GL 7781-26"


# ── Review of run 11: what a denial may NOT take away ───────────────────────

def test_a_coverage_part_denial_does_not_deny_its_line():
    ba = "BA 5512-26"
    entries = [{"label": "COVERED AUTOS LIABILITY", "value": "$1,000,000", "section": "Business Auto Declarations",
                "owner": "policy", "policy_number": ba, "line_of_business": "Business Auto"},
               {"label": "Towing and Labor", "value": "No Coverage", "section": "Business Auto Declarations",
                "owner": "policy", "policy_number": ba, "line_of_business": "Business Auto"},
               {"label": "Hired Auto Physical Damage", "value": "Not Covered", "owner": "policy",
                "policy_number": ba}]
    assert es._denied_line_of(entries[1]) is None and es._denied_line_of(entries[2]) is None
    mf = {"coverage_lines": [_row("Business Auto")], "dec_page_entries": entries}
    es._fill_missing_line_numbers(mf)
    assert mf["coverage_lines"][0]["policy_number"] == ba


def test_a_real_wc_policy_beside_the_package_denial_stays():
    wc = "WC 998877-26"
    entries = [{"label": "Workers Compensation", "value": "No Coverage", "section": "Common Policy Declarations",
                "owner": "policy", "policy_number": None, "line_of_business": "Workers Compensation"},
               {"label": "Policy Number", "value": wc, "owner": "policy", "policy_number": wc,
                "section": "Workers Compensation and Employers Liability Declarations",
                "line_of_business": "Workers Compensation"}]
    lines = [_row("Liability", _GL, "$3,954.00"), _row("Automobile", _AUTO, "$2,991.00"),
             _row("Umbrella", _UMB, "$3,418.00"), _row("Workers' Compensation")]
    assert not es.row_is_a_denied_line(lines[-1], lines, entries)
    mf = {"coverage_lines": lines, "dec_page_entries": entries}
    es._fill_missing_line_numbers(mf)
    assert _wc_row(mf["coverage_lines"])["policy_number"] == wc
    assert not ps._line_absent_from_package(mf, _WC_FAMILY)


def test_a_package_number_shared_by_two_lines_is_not_another_lines():
    cpp = "CPP 4471102-26"
    lines = [_row("General Liability", cpp), _row("Commercial Property", cpp, "$6,200")]
    entries = [{"label": "Medical Expense Limit", "value": "Not Covered", "owner": "policy",
                "policy_number": cpp, "line_of_business": "General Liability"}]
    assert not es.row_is_a_denied_line(lines[0], lines, entries)


def test_a_value_that_also_prints_a_figure_keeps_its_number():
    entries = [{"label": "Property", "value": "Building $500,000; Earthquake - Not Covered", "section": "Property",
                "owner": "policy", "policy_number": "CP 5550-26", "line_of_business": "Property"}]
    assert not es._entry_denies_its_line(entries[0])
    assert es.current_numbers_by_line(entries, {})["property"] == {"CP 5550-26"}


def test_a_short_printing_of_another_lines_number_is_still_caught():
    lines = [_row("Inland Marine", _IM), _row("Workers' Compensation", "6C74002")]
    assert es.row_is_a_denied_line(lines[1], lines, _ENTRIES)


def test_a_denied_row_is_recognised_and_a_real_one_is_not():
    lines = _lines(wc_number=_IM)
    assert es.row_is_a_denied_line(_wc_row(lines), lines, _ENTRIES)
    assert es.row_is_a_denied_line(_row("Workers' Compensation"), lines, _ENTRIES)
    own = _row("Workers' Compensation", "WC 5512-26")
    assert not es.row_is_a_denied_line(own, lines + [own], _ENTRIES)          # its own contract
    granted = _row("Workers' Compensation", _IM, "$1,200")
    assert not es.row_is_a_denied_line(granted, lines, _ENTRIES)              # a premium is a grant
    assert not es.row_is_a_denied_line(_wc_row(lines), lines, _ENTRIES[1:])   # nothing denies WC
    for junk in (None, "x", {}, {"line": None}):
        assert not es.row_is_a_denied_line(junk, lines, _ENTRIES)
    assert not es.row_is_a_denied_line(_wc_row(lines), None, None)


def test_the_wc_family_is_declared_absent_when_its_row_restates_the_denial():
    facts = {"coverage_lines": _lines(wc_number=_IM), "dec_page_entries": _ENTRIES, "_form_id": "ACORD_131"}
    assert ps._line_absent_from_package(facts, _WC_FAMILY)
    assert ps._resolve_declared_absent_line_row(
        "UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A", facts) is None
    granted = copy.deepcopy(facts)
    _wc_row(granted["coverage_lines"])["premium"] = "$1,200"
    assert not ps._line_declared_absent(granted, _WC_FAMILY)


def test_run11_131_employers_liability_ships_blank_end_to_end():
    mf = {"coverage_lines": _lines(wc_number=_IM), "dec_page_entries": copy.deepcopy(_ENTRIES)}
    es._repair_coverage_lines_from_entries(mf)
    es._fill_missing_line_numbers(mf)
    el = {f"WorkersCompensationEmployersLiability_EmployersLiability_{k}LimitAmount_A": "$1,000,000"
          for k in ("EachAccident", "DiseasePolicy", "DiseaseEachEmployee")}
    m, _c = ps.map_facts_to_form({**mf, "has_workers_comp": False, "has_umbrella": True}, _schema("ACORD_131"),
                                 form_id="ACORD_131", raw_text="",
                                 pre_filled_gpt={"filled_values": el, "raw_text_fields": set(),
                                                 "question_grounding": {}}, guard_report=[])
    for attr in ("InsurerFullName", "PolicyNumberIdentifier", "PolicyEffectiveDate", "PolicyExpirationDate"):
        assert not m.get(f"UnderlyingPolicy_EmployersLiability_{attr}_A"), attr
    for f in el:
        assert not m.get(f), f


# ── 2. GL schedule lines that are not classifications ────────────────────────
_GL_ROWS = [
    {"location": "Location 001", "class_code": "91580",
     "classification": "Contractors - Executive Supervisors or Executive Superintendents",
     "premium_basis": "Payroll", "exposure_amount": "$39,300", "territory": None, "subcontractor_pct": None},
    {"location": "Location 001", "class_code": "91585",
     "classification": "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC",
     "premium_basis": "Total Cost", "exposure_amount": "$350,000", "territory": None, "subcontractor_pct": None},
    {"location": "Location 000", "class_code": None, "classification": "Fungi Or Bacteria Exclusion",
     "premium_basis": None, "exposure_amount": "($33)", "territory": None, "subcontractor_pct": None},
    {"location": "Location 000", "class_code": None, "classification": "Limited Pollution Coverage - Work Sites",
     "premium_basis": None, "exposure_amount": "$150", "territory": None, "subcontractor_pct": None},
]
_HAZ_COLS = ("ClassCode", "Classification", "PremiumBasisCode", "Exposure", "TerritoryCode",
             "LocationProducerIdentifier", "HazardProducerIdentifier")


@pytest.mark.parametrize("col", _HAZ_COLS)
def test_run11_hazard_row_c_is_an_owned_blank(col):
    facts = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS)}
    field = f"GeneralLiability_Hazard_{col}_C"
    assert ps._resolve_phantom_gl_hazard_row(field, facts) is None
    assert ps._resolve_gl_hazard_row(field, facts) is None


def test_the_real_class_rows_still_print():
    facts = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS)}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_B", facts) == "91585"
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_PremiumBasisCode_A", facts) == "P"


def test_run11_subcontract_cost_and_type_of_work_are_read_again():
    facts = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS)}
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", facts) == "$350,000"
    assert ps._resolve_subcontracted_work_description(
        "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", facts) == _GL_ROWS[1]["classification"]


def test_only_a_policy_level_line_stops_being_a_classification():
    assert ps._is_rated_class_row({"class_code": "91580", "premium_basis": None, "location": "Location 000"})
    assert ps._is_rated_class_row({"class_code": None, "premium_basis": "Payroll", "location": "Location 000"})
    assert not ps._is_rated_class_row({"location": "Location 000", "exposure_amount": "$150"})
    assert not ps._is_rated_class_row({"location": "Location 001", "exposure_amount": "($33)"})
    # Missing code and basis at a real location: maybe a half-read class - kept.
    assert ps._is_rated_class_row({"location": "Location 001", "exposure_amount": "$200,000"})
    assert ps._is_rated_class_row({"class_code": " ", "premium_basis": None})
    assert not ps._is_rated_class_row("91580")
    assert ps._names_a_classification("91580")                 # a legacy bare code
    assert ps._names_a_classification({"code": "91580"})       # another row shape


def test_a_half_read_class_still_blocks_a_partial_sum_and_prints():
    rows = [copy.deepcopy(_GL_ROWS[1]),
            {"location": "Location 001", "class_code": "", "premium_basis": "",
             "classification": "Carpentry", "exposure_amount": "$200,000"}]
    facts = {"gl_class_code_schedule": rows}
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A", facts) is None
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_Classification_B", facts) == "Carpentry"


def test_a_schedule_with_no_codes_at_real_locations_still_prints():
    facts = {"gl_class_code_schedule": [{"location": "Location 001", "classification": "Carpentry",
                                         "exposure_amount": "$200,000"}]}
    assert ps._resolve_gl_hazard_row("GeneralLiability_Hazard_Classification_A", facts) == "Carpentry"


def test_an_unknown_basis_on_a_real_class_still_blocks_the_sum():
    rows = copy.deepcopy(_GL_ROWS[:2]) + [{"location": "Location 002", "class_code": "91111",
                                           "classification": "X", "premium_basis": "Per Job",
                                           "exposure_amount": "$90,000"}]
    assert ps._resolve_subcontracted_cost("Contractors_SubcontractorsPaidAmount_A",
                                          {"gl_class_code_schedule": rows}) is None


def test_a_schedule_of_only_unrated_lines_is_not_gl_evidence():
    facts = {"gl_class_code_schedule": copy.deepcopy(_GL_ROWS[2:])}
    assert not ps._gl_schedule_evidence(facts)
    assert ps._resolve_phantom_gl_hazard_row("GeneralLiability_Hazard_ClassCode_A", facts) is None
    assert ps._gl_hazard_rows({"gl_class_codes": ["91580"]}) == ["91580"]
    assert ps._gl_hazard_rows({}) == [] and ps._gl_hazard_rows({"gl_class_code_schedule": None}) == []


# ── 3. An exclusion is not an other coverage ─────────────────────────────────
_DESC = "GeneralLiability_OtherCoverageDescription_A"
_TICK = "GeneralLiability_OtherCoverageIndicator_A"


def _guard(values, form_id="ACORD_126", ai=None):
    mapped = dict(values)
    ps._enforce_post_fill_guards(mapped, _schema(form_id), {"_form_id": form_id},
                                 set(values) if ai is None else set(ai))
    return mapped


def test_run11_the_exclusion_leaves_and_the_coverage_stays():
    out = _guard({_DESC: "Fungi Or Bacteria Exclusion; Limited Pollution Coverage - Work Sites", _TICK: "Yes"})
    assert out[_DESC] == "Limited Pollution Coverage - Work Sites"
    assert out[_TICK] == "Yes"


def test_nothing_but_exclusions_clears_the_row():
    out = _guard({_DESC: "Fungi Or Bacteria Exclusion; Exclusion - Cyber Incident", _TICK: "Yes"})
    assert out[_DESC] is None and out[_TICK] is None


@pytest.mark.parametrize("value", ["Pollution Exclusion - Limited Exception For A Short-Term Pollution Event",
                                   "Total Pollution Exclusion Buyback", "Amendment Of Fungi Exclusion",
                                   "Limited Fungi Or Bacteria Coverage", "Hired and Non-Owned Auto Liability"])
def test_coverage_given_back_is_not_an_exclusion(value):
    assert _guard({_DESC: value})[_DESC] == value


@pytest.mark.parametrize("value,expected", [
    ("Fungi Or Bacteria Exclusion ($33), Limited Pollution Coverage - Work Sites $1,500",
     "Limited Pollution Coverage - Work Sites $1,500"),
    ("Employee Benefits Liability $1,000,000; Fungi Or Bacteria Exclusion", "Employee Benefits Liability $1,000,000"),
    ("Hired/Non-Owned Auto Liability; Abuse Or Molestation Exclusion", "Hired/Non-Owned Auto Liability"),
])
def test_the_kept_coverage_is_printed_exactly_as_written(value, expected):
    assert _guard({_DESC: value})[_DESC] == expected


def test_an_exclusion_of_a_coverage_is_still_an_exclusion():
    out = _guard({_DESC: "Exclusion - Coverage C - Medical Payments", _TICK: "Yes"})
    assert out[_DESC] is None and out[_TICK] is None


def test_a_deterministic_or_frozen_description_is_not_touched():
    v = "Fungi Or Bacteria Exclusion"
    assert _guard({_DESC: v}, ai=set())[_DESC] == v
    assert _guard({_DESC: v}, form_id="ACORD_160")[_DESC] == v


# ── 4. A list of lines is not an explanation ─────────────────────────────────
_Q7 = "CommercialUmbrellaLineOfBusiness_Question_AAGCode_A"
_Q7_WHY = "CommercialUmbrellaLineOfBusiness_AnyUnitsNotInsuredUnderlyingPoliciesExplanation_A"


@pytest.mark.parametrize("value,n,expected", [
    ("Commercial General Liability; Commercial Auto Liability", 2, True),
    ("Commercial General Liability / Commercial Auto", 2, True),
    ("Crime and Fidelity; General Liability", 2, True),
    ("General Liability", 2, False), ("General Liability", 1, True),
    ("Liability; General Liability", 2, False),
    ("Hired and Non-Owned Auto", 1, False), ("Two leased trucks, General Liability", 1, False),
    ("", 1, False), (None, 1, False),
])
def test_line_of_business_lists(value, n, expected):
    assert ps._is_line_of_business_list(value, min_lines=n) is expected


def test_which_explanations_may_hold_lines():
    lines2 = "Commercial General Liability; Commercial Auto Liability"
    assert ps._explanation_lists_lines(_Q7_WHY, lines2, "ACORD_131")
    assert not ps._explanation_lists_lines(_Q7_WHY, "General Liability", "ACORD_131")
    assert not ps._explanation_lists_lines(
        "WorkersCompensationLineOfBusiness_OtherInsuranceWithThisInsurerExplanation_A", lines2, "ACORD_130")
    assert not ps._explanation_lists_lines("CrimeLineOfBusiness_AnyEmployeesLeasedToOthersExplanation_A",
                                           lines2, "ACORD_141")
    assert not ps._explanation_lists_lines("CommercialUmbrellaLineOfBusiness_Question_AAGCode_A", lines2, "ACORD_131")


@pytest.mark.parametrize("field,form_id", [
    ("WorkersCompensationLineOfBusiness_PriorCoverageDeclinedCancelledNonRenewedLastThreeYearsExplanation_A",
     "ACORD_130"),
    ("CommercialUmbrellaLineOfBusiness_TailCoveragePurchasedAnyPreviousPrimaryOrExcessPolicyExplanation_A",
     "ACORD_131"),
    ("GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A", "ACORD_126"),
    ("CommercialUmbrellaLineOfBusiness_ApplicantSelfInsuredAnyStateExplanation_A", "ACORD_131"),
    ("WorkersCompensationLineOfBusiness_UndisputedUnpaidWorkersCompensationPremiumDueExplanation_A", "ACORD_130"),
])
def test_a_question_about_insurance_may_be_answered_with_lines(field, form_id):
    assert not ps._explanation_lists_lines(field, "Workers Compensation; General Liability", form_id)


@pytest.mark.parametrize("field,form_id", [
    (_Q7_WHY, "ACORD_131"),
    ("GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A", "ACORD_126"),
    ("CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A", "ACORD_127"),
])
def test_a_question_about_units_products_or_vehicles_is_not(field, form_id):
    assert ps._explanation_lists_lines(field, "Workers Compensation; General Liability", form_id)


def _map(form_id, values, raw="", grounding=None):
    m, _c = ps.map_facts_to_form({}, _schema(form_id), form_id=form_id, raw_text=raw,
                                 pre_filled_gpt={"filled_values": dict(values), "raw_text_fields": set(),
                                                 "question_grounding": dict(grounding or {})},
                                 guard_report=[])
    return m


def test_run11_q7_explanation_and_its_y_go_end_to_end():
    lines2 = "Commercial General Liability; Commercial Auto Liability"
    m = _map("ACORD_131", {_Q7: "Y", _Q7_WHY: lines2}, raw=f"Schedule of underlying insurance: {lines2}.",
             grounding={_Q7: lines2})
    assert not m.get(_Q7_WHY) and not m.get(_Q7)


def test_a_naked_yes_goes_once_its_explanation_is_gone():
    mapped = {_Q7: "Y", _Q7_WHY: None}
    ps._final_yn_coherence(mapped, _schema("ACORD_131"), "ACORD_131", {_Q7})
    assert mapped[_Q7] is None


def test_a_list_of_lines_is_not_a_product():
    f = "ProductAndCompletedOperations_ProductName_A"
    assert not _map("ACORD_126", {f: "Commercial General Liability; Commercial Auto Liability"}).get(f)


# ── 5. A flag the line inventory never names does not tick its box ──────────
_CYBER = "Policy_LineOfBusiness_CyberAndPrivacy_A"


def _lob_facts(lines, **flags):
    return {"coverage_lines": lines, "_form_id": "ACORD_125", **flags}


def test_run11_cyber_is_not_ticked_off_an_exclusion():
    lines = _lines() + [_row("Premium for Endorsements", None, "$ 457.00"), _row("Comprehensive", None, "$ 134.00"),
                        _row("Uninsured and Underinsured Motorists", None, "$ 258.00")]
    assert ps._resolve_standard_lob_box(_CYBER, _lob_facts(lines, has_cyber=True)) is None


@pytest.mark.parametrize("name", ["Commercial Package Policy", "Data Compromise", "Builders Risk"])
def test_a_policy_no_rule_can_place_stops_the_census(name):
    lines = _lines() + [_row(name, "PKG 55-26", "$5,000")]
    assert ps._resolve_standard_lob_box(_CYBER, _lob_facts(lines, has_cyber=True)) == "Yes"


def test_a_cyber_line_the_inventory_names_keeps_its_flag():
    lines = _lines() + [_row("Cyber Liability")]
    assert ps._resolve_standard_lob_box(_CYBER, _lob_facts(lines, has_cyber=True)) == "Yes"


def test_a_thin_inventory_is_not_a_census():
    lines = [_row("Liability", _GL, "$3,954.00"), _row("Automobile", _AUTO, "$2,991.00")]
    assert ps._resolve_standard_lob_box(_CYBER, _lob_facts(lines, has_cyber=True)) == "Yes"


@pytest.mark.parametrize("box,omitted", [
    ("Policy_LineOfBusiness_CommercialGeneralLiability_A", False),
    ("Policy_LineOfBusiness_UmbrellaIndicator_A", False),
    ("Policy_LineOfBusiness_BusinessAutoIndicator_A", False),
    ("Policy_LineOfBusiness_CommercialInlandMarineIndicator_A", False),
    ("Policy_LineOfBusiness_CyberAndPrivacy_A", True),
    ("Policy_LineOfBusiness_CrimeIndicator_A", True),
])
def test_the_census_reads_each_box_by_its_own_line(box, omitted):
    assert ps._census_omits_box_line(box, _lob_facts(_lines())) is omitted


# ── 6. BODY is blank unless a BODY column prints it ─────────────────────────
_BODY = "Vehicle_BodyCode_A"
_VEH = {"year": "2012", "make": "SUBARU", "model": "OUTBACK", "vin": "4S4BRCGC9C3217772", "body_type": "SEDAN",
        "class_code": "7383", "territory": "111", "vehicle_type": "private_passenger"}


def test_run11_body_from_the_vehicle_description_is_blank():
    facts = {"auto_vin_schedule": [dict(_VEH)], "_carrier_documents_only": True, "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_type_cell(_BODY, facts) is None


def test_a_body_column_or_an_application_keeps_the_body():
    base = {"auto_vin_schedule": [dict(_VEH)], "_form_id": "ACORD_127"}
    body_entry = {"label": "BODY TYPE", "value": "SEDAN", "owner": "policy"}
    assert ps._resolve_vehicle_type_cell(
        _BODY, {**base, "_carrier_documents_only": True, "dec_page_entries": [body_entry]}) is ps._SCHED_SKIP
    assert ps._resolve_vehicle_type_cell(_BODY, {**base, "_carrier_documents_only": False}) is ps._SCHED_SKIP
    abbreviated = {"label": "BodyType", "value": "PK", "owner": "policy"}
    assert ps._resolve_vehicle_type_cell(
        _BODY, {**base, "_carrier_documents_only": True, "dec_page_entries": [abbreviated]}) is ps._SCHED_SKIP


def test_a_body_a_person_typed_is_kept():
    typed = {"value": [dict(_VEH, body_type="Pickup")], "source": "producer"}
    facts = {"auto_vin_schedule": typed, "_carrier_documents_only": True, "_form_id": "ACORD_127"}
    assert ps._resolve_vehicle_type_cell(_BODY, facts) is ps._SCHED_SKIP


# ── 7. The comp deductible is one figure plus its own wording ───────────────
@pytest.mark.parametrize("value,expected", [
    ("$ 1000 DEDUCTIBLE FOR ALL PERILS FOR EACH COVERED AUTO", "$ 1000"), ("$ 1000 DED", "$ 1000"),
    ("$1,000", "$1,000"), ("1000", "1000"),
    ("$1,000 Each Pollution Incidents", None), ("$500 / $1,000", None), ("Full Glass", None), ("", None),
    ("1% deductible per occurrence", None), ("5 % deductible each loss", None),
    ("1,000 DED ALL PERILS EXCEPT GLASS", None), ("$250 Glass", None),
])
def test_deductible_amount_salvage(value, expected):
    assert ps._deductible_amount_of(value) == expected


def test_run11_comp_deductible_prints_end_to_end():
    f = "Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_A"
    facts = {"auto_deductible_comp": "$ 1000 DEDUCTIBLE FOR ALL PERILS FOR EACH COVERED AUTO",
             "auto_vin_schedule": [dict(_VEH)]}
    m, _c = ps.map_facts_to_form(facts, _schema("ACORD_127"), form_id="ACORD_127", raw_text="",
                                 pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                                                 "question_grounding": {}}, guard_report=[])
    assert str(m.get(f) or "").replace(",", "").replace("$", "").strip() == "1000"
