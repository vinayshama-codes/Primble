"""Choice Electric live run 15f43bba (8 Oct 2026, all seven documents) - round 10.

Each defect was found on the owner's stored session and each fix measured over
the stored documents (1,695) and the round-5 corpus (691 sessions / 1,210 forms)
before it shipped; the numbers are in 25sepChanges.md part T.
"""
import json
import os

import pytest

import services.ai_answer_guards as G
import services.extraction_service as es
import services.pdf_service as P
import services.scoped_evidence as SE
from services.coverage_evidence import parse_xmod

_SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json")) as fh:
        return json.load(fh)


# ── An issue date is not a policy's start ────────────────────────────────────
_COMMON_DEC = (
    "COMMON POLICY DECLARATIONS\nAMERISURE INSURANCE COMPANY\n"
    "POLICYPERIOD: FROM 01/01/2025 TO 01/01/2026 AT12:01A.M.STANDARD\n"
    "THIS POLICY CONSISTS OF THE FOLLOWING COVERAGEPARTS FOR WHICHAPREMIUMIS\n"
    "COMMERCIAL AUTOMOBILE COVERAGE PART $\nCOMMERCIAL PROPERTY COVERAGE PART $\n"
    "Premium shownispayable:$ atinception.$\n01/16/2025\nIssue Date: _____________\n"
)


def test_a_date_printed_only_beside_issue_date_is_issue_only():
    assert es.issue_only_dates(_COMMON_DEC) == {"2025-01-16"}


def test_a_label_belongs_to_the_nearest_date():
    text = "POLICY NUMBER:\nEFFECTIVE DATE: 01/01/2025\nISSUE DATE: 01/23/2025\n"
    assert es.issue_only_dates(text) == {"2025-01-23"}


def test_an_issue_date_the_document_also_prints_as_the_period_stays():
    text = "Effective Date: 01/01/2025\nIssue Date: 01/01/2025\n"
    assert es.issue_only_dates(text) == set()
    ranged = "Policy 01/01/2025 - 01/01/2026\nDate Issued: 01/01/2026\n"
    assert es.issue_only_dates(ranged) == set()


def test_no_issue_label_no_opinion():
    assert es.issue_only_dates("Policy Period 01/01/2025 to 01/01/2026") == set()
    assert es.issue_only_dates("") == set()


def _auto_doc():
    rows = [
        {"line": "Commercial Auto", "carrier": "AMERISURE INSURANCE COMPANY",
         "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
        {"line": "Commercial Property", "carrier": "AMERISURE INSURANCE COMPANY",
         "effective_date": "01/16/2025"},
        {"line": "Commercial General Liability", "carrier": "AMERISURE INSURANCE COMPANY",
         "effective_date": "01/16/2025"},
    ]
    return {"filename": "auto.pdf", "text": _COMMON_DEC,
            "facts": {"coverage_lines": {"value": rows},
                      "effective_date": {"value": "01/01/2025"}}}


def test_menu_rows_lose_the_issue_date_and_the_real_row_keeps_its_term():
    doc = _auto_doc()
    cleared = es.clear_issue_dates(doc)
    rows = doc["facts"]["coverage_lines"]["value"]
    assert len(cleared) == 2
    assert rows[0]["effective_date"] == "01/01/2025" and rows[0]["expiration_date"] == "01/01/2026"
    assert rows[1]["effective_date"] is None and rows[2]["effective_date"] is None
    assert doc["facts"]["effective_date"]["value"] == "01/01/2025"


def test_a_document_level_issue_date_is_cleared_too():
    doc = {"filename": "cert.pdf", "text": "CERTIFICATE\nDate Issued: July 15, 2025\nINSURED:",
           "facts": {"effective_date": {"value": "07/15/25"}}}
    assert es.clear_issue_dates(doc) == ["effective_date=07/15/25"]
    assert "effective_date" not in doc["facts"]


# ── A bare menu entry is not a second line on the document ──────────────────
def test_menu_rows_with_nothing_of_their_own_do_not_unmake_own_declarations():
    doc = _auto_doc()
    es.clear_issue_dates(doc)
    assert es._sources_are_own_declarations("auto", ["auto.pdf"], [doc]) is True


def test_a_document_of_only_bare_rows_is_judged_on_all_of_them():
    doc = {"filename": "app.pdf",
           "facts": {"coverage_lines": [{"line": "General Liability"}]}}
    assert es._sources_are_own_declarations("general_liab", ["app.pdf"], [doc]) is True


def test_two_speaking_lines_are_still_not_one_policy():
    doc = {"filename": "common.pdf", "facts": {"coverage_lines": [
        {"line": "Commercial Auto", "premium": "$31,000"},
        {"line": "Commercial Property", "premium": "$6,275"}]}}
    assert es._sources_are_own_declarations("auto", ["common.pdf"], [doc]) is False


# ── A building attribute must be stated as that attribute ───────────────────
_PROPERTY = ("RATE Premium\nGRP I 0.046 $367.00\nGRP II 0.059 $474.00\nSPECIAL 0.041 $330.00\n"
             "Construction Type: FRAME\n")


def test_a_rate_group_is_not_a_protection_class():
    assert G.cope_answer_without_evidence(
        "BuildingFireProtection_ProtectionClassCode_A", "GRP I", _PROPERTY) is True


def test_a_stated_protection_class_stands():
    text = _PROPERTY + "Protection Class: 3\n"
    assert G.cope_answer_without_evidence(
        "BuildingFireProtection_ProtectionClassCode_A", "3", text) is False


def test_a_bceg_grade_needs_bceg_wording():
    assert G.cope_answer_without_evidence(
        "Construction_BuildingCodeEffectivenessGradeCode_A", "0", _PROPERTY) is True
    assert G.cope_answer_without_evidence(
        "Construction_BuildingCodeEffectivenessGradeCode_A", "4", _PROPERTY + "BCEG: 4\n") is False


def test_a_yes_no_tick_is_not_judged_as_a_code():
    assert G.cope_answer_without_evidence("BuildingFireProtection_SprinklerIndicator_A", "Y",
                                          _PROPERTY) is False


# ── A vehicle make is not a party ────────────────────────────────────────────
_FLEET = {"auto_vin_schedule": {"value": [
    {"year": "2001", "make": "CHEVROLET", "model": "EXPRESS G2500"},
    {"year": "1999", "make": "GMC", "model": "SAFARI XT"}]}}


def test_a_make_in_an_other_owner_box_is_refused():
    mapped = {"AdditionalInterest_FullName_C": "Chevrolet", "AdditionalInterest_FullName_D": "Gmc"}
    out = P._vehicle_make_in_a_party_box(mapped, _FLEET, set(mapped))
    assert set(out) == set(mapped)


def test_a_lender_and_a_real_owner_stand():
    mapped = {"AdditionalInterest_FullName_C": "GM Financial",
              "AdditionalInterest_FullName_D": "Ryder Truck Rental Inc"}
    assert P._vehicle_make_in_a_party_box(mapped, _FLEET, set(mapped)) == {}


def test_only_ai_values_are_judged_and_no_schedule_no_opinion():
    mapped = {"AdditionalInterest_FullName_C": "Chevrolet"}
    assert P._vehicle_make_in_a_party_box(mapped, _FLEET, set()) == {}
    assert P._vehicle_make_in_a_party_box(mapped, {}, set(mapped)) == {}


# ── Another policy's text takes its Yes with it ──────────────────────────────
_WC_TEXT = ("WORKERS COMPENSATION AND EMPLOYERS LIABILITY POLICY\n"
            "CO 0930 Waiver of Our Right to Recover from Others Endorsement-Blanket 0.0200 500.00\n")
_AUTO_TEXT = "BUSINESS AUTO DECLARATIONS\nCOVERED AUTOS LIABILITY 1 $1,000,000\n"


def _two_docs():
    docs = [
        {"filename": "auto.pdf", "text": _AUTO_TEXT, "facts": {"coverage_lines": [
            {"line": "Commercial Auto", "premium": "$31,000"}]}},
        {"filename": "wc.pdf", "text": _WC_TEXT, "facts": {"coverage_lines": [
            {"line": "Workers Compensation", "premium": "$29,278"}]}},
    ]
    facts = {}
    SE.attach_documents(facts, docs)
    return facts, docs


def _stamp_hold_harmless(monkeypatch, explanation_text, raw):
    monkeypatch.setattr(P, "_EVIDENCE_JUDGE_ENABLED", False)      # no model call
    facts, _docs = _two_docs()
    q = "CommercialVehicleLineOfBusiness_Question_AABCode_A"
    e = "CommercialVehicleLineOfBusiness_HoldHarmlessAgreementsExplanation_A"
    gpt = {"filled_values": {q: "Y", e: explanation_text},
           "question_grounding": {q: explanation_text}}
    report: list = []
    mapped, _conf = P.map_facts_to_form(facts, _schema("ACORD_127"), "ACORD_127", raw_text=raw,
                                        pre_filled_gpt=gpt, guard_report=report)
    reasons = {r.get("field"): r.get("reason") for r in report}
    return mapped, reasons, q, e


def test_a_yes_explained_by_another_policys_endorsement_is_blanked(monkeypatch):
    quote = "Waiver of Our Right to Recover from Others Endorsement-Blanket"
    mapped, reasons, q, e = _stamp_hold_harmless(monkeypatch, quote, _AUTO_TEXT + _WC_TEXT)
    assert not mapped.get(e) and not mapped.get(q)
    assert reasons.get(e) == reasons.get(q) == SE.REASON_OTHER_POLICY


def test_a_yes_explained_by_its_own_policy_stands(monkeypatch):
    own = "Hold harmless agreement with the general contractor for all autos"
    mapped, reasons, q, e = _stamp_hold_harmless(
        monkeypatch, own, _AUTO_TEXT + own + "\n" + _WC_TEXT)
    assert reasons.get(q) != SE.REASON_OTHER_POLICY



# ── A reference-only document speaks for limits, not deductibles ────────────
def _wc_package():
    docs = [
        {"filename": "wc.pdf", "text": "WC POLICY\nCO 9664 Small Deductible 6.5000 -2,495.00\n"
                                        "Employers Liability $1,000,000 each accident\n",
         "facts": {"coverage_lines": [{"line": "Workers Compensation", "premium": "$29,278"}]}},
        {"filename": "umbrella.pdf",
         "text": "UMBRELLA DECLARATIONS\nMinimum Policy Charge $1,000.00\n"
                 "SCHEDULE OF UNDERLYING INSURANCE\nWorkers Compensation and Employers Liability "
                 "$1,000,000 Bodily Injury by Accident\n",
         "facts": {"coverage_lines": [{"line": "Commercial Liability Umbrella", "premium": "$17,082"}]},
         "flags": {"has_workers_comp": True}},
    ]
    facts = {}
    SE.attach_documents(facts, docs)
    return facts


def test_an_umbrella_schedule_does_not_witness_a_wc_deductible():
    facts = _wc_package()
    f = "WorkersCompensation_DeductibleAmount_A"
    out = SE.foreign_policy_values({f: "$1,000"}, _schema("ACORD_130"), facts, "ACORD_130", {f})
    assert out == {f: SE.REASON_OTHER_POLICY}


def test_the_wc_policys_own_figure_stands():
    facts = _wc_package()
    f = "WorkersCompensation_DeductibleAmount_A"
    assert SE.foreign_policy_values({f: "$2,495"}, _schema("ACORD_130"), facts, "ACORD_130",
                                    {f}) == {}


# ── Not an answer ────────────────────────────────────────────────────────────
def test_a_label_repeating_itself_is_not_an_answer():
    assert G.is_self_labelled("CO: CO") is True
    assert G.is_self_labelled("CO: Colorado") is False
    assert G.is_self_labelled("Colorado") is False


@pytest.mark.parametrize("field", [
    "UnderlyingCoverage_InformationDescription_A", "ExcessUmbrella_OtherCoverageDescription_A"])
def test_a_summary_about_the_submitted_documents_is_refused(field):
    sentence = "Umbrella follows form over the underlying coverages (per submitted documents)"
    out = G.refuse_non_answers({field: sentence}, _schema("ACORD_131"), {},
                               "EXCESS (FOLLOWING FORM) LIABILITY", {field}, "ACORD_131")
    assert out.get(field, "").startswith(G.REASON_SUMMARY)


def test_self_labelled_value_is_refused_in_its_box():
    f = "WorkersCompensation_AdditionalCompanyInformation_A"
    out = G.refuse_non_answers({f: "CO: CO"}, _schema("ACORD_130"), {}, "CO 5190", {f}, "ACORD_130")
    assert out.get(f, "").startswith(G.REASON_SELF_LABELLED)


# ── The experience mod the rating worksheet prints ──────────────────────────
_WORKSHEET = ("CO Total Subject Premium 36,304.00\nCO 9898 Experience Mod 1.0800 2,904.00\n"
              "CO | | 9898 | Experience Mod | | 1.0800 | 2,904.00\n"
              "CW WC000403 Experience Rating Modification Factor Endorsement 04_84\n")


def test_four_decimal_mods_parse():
    assert parse_xmod("1.0800") == pytest.approx(1.08)
    assert parse_xmod("0.95") == pytest.approx(0.95)


def test_the_printed_mod_is_derived_once():
    mf: dict = {}
    assert es.derive_xmod_from_rating_lines(mf, [{"text": _WORKSHEET}]) == "1.0800"
    assert mf["wc_xmod"]["source"] == "derived"


def test_two_different_mods_and_a_held_mod_write_nothing():
    two = [{"text": _WORKSHEET}, {"text": "Experience Mod 0.9500"}]
    assert es.derive_xmod_from_rating_lines({}, two) is None
    held = {"wc_xmod": {"value": "0.95", "source": "producer"}}
    assert es.derive_xmod_from_rating_lines(held, [{"text": _WORKSHEET}]) is None
    assert held["wc_xmod"]["value"] == "0.95"


def test_an_endorsement_title_is_not_a_mod():
    text = "CW WC000403 Experience Rating Modification Factor Endorsement 04_84\n"
    assert es.derive_xmod_from_rating_lines({}, [{"text": text}]) is None


# ══ Round 10b - the owner's re-run `2076fe35` ═══════════════════════════════

# ── The building / BPP value the premises schedule prints ────────────────────
def _premises_doc(doc_type, rows):
    return {"filename": f"{doc_type}.pdf", "doc_type": doc_type,
            "facts": {"property_locations": {"value": rows}}}


_ROWS = [{"building_number": "001", "building_value": "$798,556", "bpp_value": "$73,008"},
         {"building_number": "002", "building_value": "$421,714", "bpp_value": "$73,008"}]


def test_an_empty_building_value_takes_the_first_scheduled_buildings():
    mf = {"property_locations": {"value": [dict(r) for r in _ROWS]}}
    notes = es.derive_property_values_from_premises(mf, [_premises_doc("dec_page", _ROWS)])
    assert mf["property_building_value"]["value"] == "$798,556"
    assert mf["property_bpp_value"]["value"] == "$73,008"
    assert mf["property_building_value"]["source"] == "derived" and len(notes) == 2


def test_a_certificates_limit_is_never_a_building_value():
    rows = [{"building_value": "$4,200,000"}]
    mf = {"property_locations": {"value": rows}}
    assert es.derive_property_values_from_premises(mf, [_premises_doc("certificate", rows)]) == []
    assert "property_building_value" not in mf


def test_a_held_value_and_an_empty_row_are_never_used():
    mf = {"property_locations": {"value": [{"building_value": "$0"}, {"building_value": "$900,000"}]},
          "property_bpp_value": {"value": "$50,000", "source": "ai"}}
    es.derive_property_values_from_premises(
        mf, [_premises_doc("dec_page", [{"building_value": "$900,000"}])])
    assert mf["property_building_value"]["value"] == "$900,000"
    assert mf["property_bpp_value"]["value"] == "$50,000"


# ── A policy's coverage trigger is its own documents' ───────────────────────
def _trigger_facts(extra_docs=()):
    docs = [
        {"filename": "excess.pdf", "text": "EXCESS (FOLLOWING FORM) LIABILITY\n"
                                           "$4,000,000 any one occurrence\nPolicy Period 01/01/2025 to 01/01/2026\n",
         "facts": {"coverage_lines": [{"line": "Excess (Following Form) Liability", "premium": "$10,692"}]}},
        {"filename": "epl.pdf", "text": "NOTICE: THE LIABILITY COVERAGE PARTS PROVIDE CLAIMS-MADE COVERAGE\n",
         "facts": {"coverage_lines": [{"line": "Employment Practices Liability", "premium": "$2,000"}]}},
    ] + list(extra_docs)
    facts = {}
    SE.attach_documents(facts, docs)
    return facts


def test_a_claims_made_tick_borrowed_from_another_policy_is_refused():
    f = "ExcessUmbrella_ClaimsMadeIndicator_A"
    out = SE.trigger_values({f: "Yes"}, _schema("ACORD_131"), _trigger_facts(), "ACORD_131", {f})
    assert out == {f: SE.REASON_OTHER_POLICY}


def test_a_retro_date_no_document_prints_as_retro_is_refused():
    f = "ExcessUmbrella_CurrentRetroactiveDate_A"
    out = SE.trigger_values({f: "01/01/2025"}, _schema("ACORD_131"), _trigger_facts(), "ACORD_131", {f})
    assert out == {f: SE.REASON_TRIGGER_NOT_STATED}


def test_a_printed_retro_date_and_a_no_stand():
    gl = {"filename": "gl.pdf",
          "text": "COMMERCIAL GENERAL LIABILITY DECLARATIONS\nEMPLOYEE BENEFITS LIABILITY - CLAIMS MADE\n"
                  "Retroactive Date: 07/15/2020\n",
          "facts": {"coverage_lines": [{"line": "Commercial General Liability", "premium": "$16,818"}]}}
    facts = _trigger_facts([gl])
    f = "GeneralLiability_EmployeeBenefits_RetroactiveDate_A"
    assert SE.trigger_values({f: "07/15/2020"}, _schema("ACORD_126"), facts, "ACORD_126", {f}) == {}
    g = "ExcessUmbrella_ClaimsMadeIndicator_A"
    assert SE.trigger_values({g: "No"}, _schema("ACORD_131"), _trigger_facts(), "ACORD_131", {g}) == {}


# ── A bureau's number or name is printed as that bureau's ───────────────────
_PACKAGE_HEADER = "POLICYNUMBER: IL DS 71 05 02 08\nACCOUNT NUMBER: 3\nCOMMON POLICY DECLARATIONS\n"


@pytest.mark.parametrize("field,value", [
    ("NamedInsured_CreditBureauIdentifier_A", "3"),
    ("NamedInsured_RatingBureauIdentifier_A", "3"),
    ("NamedInsured_CreditBureauName_A", "Dun And Bradstreet Number"),
])
def test_an_account_number_is_not_a_bureau_id(field, value):
    out = G.refuse_non_answers({field: value}, _schema("ACORD_130"), {}, _PACKAGE_HEADER, {field},
                               "ACORD_130")
    assert out.get(field, "").startswith(G.REASON_BUREAU_NOT_STATED)


def test_a_printed_duns_number_and_its_bureau_stand():
    text = "Dun & Bradstreet D-U-N-S Number: 12-345-6789\n"
    assert not G.bureau_value_without_its_label("NamedInsured_CreditBureauIdentifier_A", "12-345-6789", text)
    assert not G.bureau_value_without_its_label("NamedInsured_CreditBureauName_A", "Dun & Bradstreet", text)


# ══ Brent's answers of 8 Oct 2026 (ACORD 125 page one; landlords) ═══════════
_TWO_WRITERS = {
    "_form_id": "ACORD_125",
    "carrier_is_current_policy": True,
    "renews_current_programme": True,
    "_programme_writers": ["EMC Property & Casualty Company", "Employers Mutual Casualty Company"],
    "carrier_name": {"value": "Employers Mutual Casualty Company", "source": "ai"},
}


def test_two_writing_companies_are_not_listed_in_the_top_carrier_box():
    # "That field is for the carrier tied to the application" - blank, and the
    # unscored "carrier receiving this submission" card asks.
    assert P._resolve_page_one_receiving_carrier("Insurer_FullName_A", dict(_TWO_WRITERS)) is None


def _dec_renewal_facts():
    rows = [{"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
             "premium": "$4,000", "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}]
    mf = {"carrier_name": {"value": "EMC Property & Casualty Company", "source": "ai"},
          "effective_date": {"value": "07/15/2026", "source": "derived"},
          "coverage_lines": {"value": rows}}
    docs = [{"filename": "dec.pdf", "doc_type": "dec_page", "facts": {"coverage_lines": rows}}]
    return mf, docs


def test_a_dec_renewal_leaves_page_one_premiums_blank():
    mf, docs = _dec_renewal_facts()
    es._mark_page_one_current_policy(mf, docs)
    assert mf.get("renews_current_programme") is True
    assert mf.get("premium_is_current_policy") is True


def test_a_quoted_premium_still_prints():
    mf, docs = _dec_renewal_facts()
    docs.append({"filename": "quote.pdf", "doc_type": "quote",
                 "facts": {"total_policy_premium": {"value": "$4,400"}}})
    es._mark_page_one_current_policy(mf, docs)
    assert mf.get("premium_is_current_policy") is not True


def _two_rented_locations():
    return {"_form_id": "ACORD_125", "property_locations": {"value": [
        {"location_number": "1", "address": "100 Main St, Denver, CO 80221", "is_tenant": True,
         "landlord_name": "Front Range Properties LLC",
         "landlord_address": "500 Market St, Denver, CO 80202"},
        {"location_number": "2", "address": "200 Oak Ave, Aurora, CO 80011", "is_tenant": True,
         "landlord_name": "Aurora Holdings Inc", "landlord_address": "9 Elm St, Aurora, CO 80011"},
    ]}}


def test_the_first_landlord_prints_on_the_125():
    row = P.landlord_interest_row(_two_rented_locations())
    assert row and row["name"] == "Front Range Properties LLC" and row["location"] == "1"


def test_the_other_landlords_are_an_acord45_todo():
    import services.needs_attention as NA
    assert NA._landlords_for_acord45(_two_rented_locations()) == ["Aurora Holdings Inc (location 2)"]
    one = _two_rented_locations()
    one["property_locations"]["value"][1].pop("landlord_name")
    assert NA._landlords_for_acord45(one) == []
