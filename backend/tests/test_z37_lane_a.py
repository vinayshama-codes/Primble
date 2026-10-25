"""Z37 lane A (24 Oct 2026)."""
from __future__ import annotations

import copy

import services.session_documents as sd
from tests.test_new_document_fill_7oct import (  # noqa: F401  (the fixture)
    DEC, SID, _doc, env, form, make_package, run,
)

# ══ 1. CE 25 - excluding a filled ACORD 125 takes back its question 4 ═══════

Q4_TEXT = ("ACORD 125 COMMERCIAL INSURANCE APPLICATION\nApplicant: Bluebird Electric LLC\n"
           "ANY OTHER INSURANCE WITH THIS COMPANY? Y\n"
           "Commercial Package CPP-4418820-03; Business Auto BA-4418821-03\n")
Q4_FACTS = {"applicant_name": "Bluebird Electric LLC",
            "disclosure_answers": [{"topic": "other_insurance_with_carrier", "answer": "Y",
                                    "evidence_quote": "Commercial Package CPP-4418820-03; "
                                                      "Business Auto BA-4418821-03"}]}


def _filled_125():
    return _doc("d-125", "ACORD_125_FILLED 2.pdf", "application", Q4_TEXT, Q4_FACTS)


def _q4(f):
    st = f["field_state"]
    return {b: st.get(b) for b in st
            if b.startswith("OtherPolicy_") or b == "CommercialPolicy_Question_AAHCode_A"}


def test_excluding_the_filled_125_takes_back_question_4(env):
    make_package(env, docs=[DEC()])
    before = _q4(copy.deepcopy(form(env)))
    run(sd.add_documents(SID, [_filled_125()], user_id="u1", purge_dec_index=True))
    added = _q4(form(env))
    assert "CPP-4418820-03" in added.values()
    run(sd.change_document(SID, doc_id="d-125", action="exclude", user_id="u1"))
    after = _q4(form(env))
    assert "CPP-4418820-03" not in after.values() and "BA-4418821-03" not in after.values()
    # every Q4 box prints what it printed before the add (or is blank)
    assert {b: v for b, v in after.items() if v} == {b: v for b, v in before.items() if v}


def test_the_question_4_list_is_named_as_a_derived_fact_the_exclude_retracts():
    # The live exclude (15 Oct, fe11b8c) ran before `merge_only_keys` existed:
    # `other_insurance_policies` is DERIVED by the merge, never stated by a
    # document, so only that door retracts it.
    gone = sd.merge_only_keys([DEC(), _filled_125()], [DEC(), dict(_filled_125(), excluded=True)])
    assert "other_insurance_policies" in gone
    assert "other_insurance_policies" not in sd.stated_fact_keys([DEC(), _filled_125()])


# ══ 4. ACORD 137's hired physical damage deductible ══════════════════════════
import pytest  # noqa: E402

import services.scoped_evidence as se  # noqa: E402

_HPD = "Vehicle_Collision_DeductibleAmount_A"          # Business Auto page = HIRED PD block
_TRUCK_PD = "Vehicle_Collision_DeductibleAmount_B"     # another page's owned deductible


def _auto_doc(text, name="auto.pdf"):
    return {"filename": name, "doc_type": "dec_page", "text": text, "flags": {},
            "facts": {"coverage_lines": [{"line": "Business Auto", "premium": "$12,000"}]}}


def _gl_doc(text):
    return {"filename": "gl.pdf", "doc_type": "dec_page", "text": text, "flags": {},
            "facts": {"coverage_lines": [{"line": "Commercial General Liability", "premium": "$5,000"}]}}


_OWNED_ONLY = ("BUSINESS AUTO DECLARATIONS\nCOVERED AUTOS: 1\n"
               "PHYSICAL DAMAGE: COLLISION $1,000 DEDUCTIBLE COMPREHENSIVE $500 DEDUCTIBLE\n")


@pytest.mark.parametrize("form_id", ["ACORD_137_CO", "ACORD_137_CA"])
def test_hired_pd_deductible_needs_a_hired_label_in_the_auto_policy(form_id):
    assert _HPD in se._hired_pd_boxes(form_id) and _TRUCK_PD not in se._hired_pd_boxes(form_id)
    # the owned autos' deductible is printed, but never for hired autos
    facts = se.attach_documents({}, [_auto_doc(_OWNED_ONLY)])
    assert se.hired_pd_values({_HPD: "$1,000"}, {}, facts, form_id, {_HPD}) == \
        {_HPD: se.REASON_HIRED_PD_NOT_STATED}
    assert se.out_of_scope_values({_HPD: "$1,000"}, {}, facts, form_id, {_HPD}) == \
        {_HPD: se.REASON_HIRED_PD_NOT_STATED}
    assert "hired" in se.held_back_text(se.REASON_HIRED_PD_NOT_STATED)
    # the extension prints it for hired autos: kept
    text = _OWNED_ONLY + "HIRED AUTO PHYSICAL DAMAGE: COMPREHENSIVE $1,000 / COLLISION $1,000 DEDUCTIBLE\n"
    facts = se.attach_documents({}, [_auto_doc(text)])
    assert se.hired_pd_values({_HPD: "1,000"}, {}, facts, form_id, {_HPD}) == {}


def test_hired_pd_printed_only_by_another_policy_is_that_policys():
    gl = _gl_doc("HIRED AND NON-OWNED AUTO LIABILITY ENDORSEMENT DEDUCTIBLE $2,500")
    facts = se.attach_documents({}, [_auto_doc(_OWNED_ONLY), gl])
    assert se.hired_pd_values({_HPD: "$2,500"}, {}, facts, "ACORD_137_CO", {_HPD}) == \
        {_HPD: se.REASON_OTHER_POLICY}


def test_hired_pd_rule_stands_down_where_it_cannot_judge():
    facts = se.attach_documents({}, [_auto_doc(_OWNED_ONLY)])
    # not an AI value; not an amount; another page's owned deductible; no documents
    assert se.hired_pd_values({_HPD: "$1,000"}, {}, facts, "ACORD_137_CO", set()) == {}
    assert se.hired_pd_values({_HPD: "Included"}, {}, facts, "ACORD_137_CO", {_HPD}) == {}
    assert se.hired_pd_values({_TRUCK_PD: "$1,000"}, {}, facts, "ACORD_137_CO", {_TRUCK_PD}) == {}
    assert se.hired_pd_values({_HPD: "$1,000"}, {}, {}, "ACORD_137_CO", {_HPD}) == {}
    # never on any other form
    assert se.hired_pd_values({_HPD: "$1,000"}, {}, facts, "ACORD_127", {_HPD}) == {}


# ══ 5. ACORD 130 premium block OTHER row named only by a label ═══════════════
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import services.ai_answer_guards as aag  # noqa: E402

_S130 = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas" / "ACORD_130_schema.json")
                   .read_text(encoding="utf-8"))
_OD = "WorkersCompensationStateCoverage_Other_CoverageDescription_A"
_OF = "WorkersCompensationStateCoverage_Other_ModificationFactor_A"
_OP = "WorkersCompensationStateCoverage_Other_FactoredPremiumAmount_A"


@pytest.mark.parametrize("label", ["Workers Compensation", "Employers Liability", "Premium",
                                   "Total Estimated Annual Premium $37,600", "WC Premium",
                                   "Part One - Workers Compensation"])
def test_a_label_in_the_130_other_row_is_refused_with_its_row(label):
    mapped = {_OD: label, _OF: "1.00", _OP: "$37,600"}
    out = aag.refuse_non_answers(mapped, _S130, {}, "WORKERS COMPENSATION PREMIUM 37,600",
                                 {_OD, _OF, _OP}, "ACORD_130")
    assert set(out) == {_OD, _OF, _OP}
    assert all(v.startswith(aag.REASON_ROW_NAME_REFUSED) for v in out.values())
    assert mapped[_OD] is None and mapped[_OP] is None


@pytest.mark.parametrize("name", ["Terrorism", "Expense Constant", "Catastrophe (Other Than Certified Acts)",
                                  "Employers Liability Increased Limits", "Schedule Rating Credit"])
def test_a_real_factor_in_the_130_other_row_is_kept(name):
    mapped = {_OD: name, _OF: "1.05", _OP: "$422"}
    out = aag.refuse_non_answers(mapped, _S130, {}, f"{name.upper()} 1.05 422",
                                 {_OD, _OF, _OP}, "ACORD_130")
    assert not ({_OD, _OF, _OP} & {f for f, v in out.items() if "section label" in v})
    assert not aag.other_factor_row_is_a_label(_OD, _S130, mapped)


def test_the_label_rule_reads_only_the_worksheet_other_row():
    assert not aag.other_factor_row_is_a_label("WorkersCompensation_Coverage_OtherDescription_A", _S130,
                                               {"WorkersCompensation_Coverage_OtherDescription_A": "Premium"})
    assert not aag.other_factor_row_is_a_label(_OP, _S130, {_OP: "$1"})          # no name: another rule's


# ══ 2 / 3 (W1). An insurer's / office's address is nobody's mailing address ══
import services.extraction_service as es  # noqa: E402
from services.insured_scope import address_is_a_party_office, drop_office_addresses  # noqa: E402
from services.normalization import describes_insurance_not_business  # noqa: E402

_AMERISURE = ("AMERISURE INSURANCE COMPANY\n26777 HALSTED RD\nFARMINGTON HILLS MI 48331-3586\n"
              "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS\nNAMED INSURED: CHOICE ELECTRIC LLC\n"
              "1450 W EVANS AVE, DENVER, CO 80223\n")
_TRAVELERS = ("TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA\nOFFICE: PHOENIX AZ\n"
              "EXCESS LIABILITY DECLARATIONS\nNAMED INSURED: CHOICE ELECTRIC LLC\n")


def test_an_office_or_insurer_address_is_recognised_and_the_insureds_is_not():
    assert address_is_a_party_office("26777 Halsted Rd, Farmington Hills MI 48331-3586", [_AMERISURE])
    assert address_is_a_party_office("Office: Phoenix AZ", [_TRAVELERS])
    assert address_is_a_party_office("AZ", [_TRAVELERS])
    assert address_is_a_party_office("Phoenix, AZ", [_TRAVELERS])
    # the insured's own address, a value printed nowhere, a value printed elsewhere too
    assert not address_is_a_party_office("1450 W Evans Ave, Denver, CO 80223", [_AMERISURE])
    assert not address_is_a_party_office("500 Elm St, Boulder, CO", [_AMERISURE])
    assert not address_is_a_party_office("AZ", [_TRAVELERS + "MAILING ADDRESS: 9 PINE RD, MESA AZ 85201\n"])
    assert not address_is_a_party_office("", [_TRAVELERS]) and not address_is_a_party_office("AZ", [])
    # an agency named "... Mutual Insurance Agency" is not an insurer
    assert not address_is_a_party_office(
        "12 Oak St, Denver, CO", ["PRODUCER: FARMERS MUTUAL INSURANCE AGENCY\n12 OAK ST, DENVER, CO\n"])


def test_a_documents_applicant_address_read_off_an_office_line_leaves_its_facts():
    doc = {"text": _TRAVELERS, "facts": {"mailing_address": "Phoenix, AZ", "applicant_name": "Choice Electric LLC"}}
    assert drop_office_addresses(doc) == ["mailing_address"] and "mailing_address" not in doc["facts"]
    own = {"text": _AMERISURE, "facts": {"mailing_address": "1450 W Evans Ave, Denver, CO 80223"}}
    assert drop_office_addresses(own) == [] and own["facts"]["mailing_address"]
    person = {"text": _TRAVELERS, "facts": {"mailing_address": {"value": "Phoenix, AZ", "source": "producer"}}}
    assert drop_office_addresses(person) == []


def test_the_merge_drops_the_office_line_mailing_address():
    doc = {"doc_id": "d1", "filename": "excess.pdf", "doc_type": "dec_page", "text": _TRAVELERS,
           "facts": {"applicant_name": "Choice Electric LLC", "mailing_address": "Phoenix, AZ"}, "flags": {}}
    facts, _flags = es.merge_facts([doc], es.select_primary_truth([doc]))
    assert not es._fv(facts, "mailing_address")


def test_w1_a_carrier_head_office_is_not_the_producer_address():
    mf = {"producer_address": "26777 Halsted Rd, Farmington Hills MI 48331-3586",
          "applicant_name": "Choice Electric LLC"}
    docs = [{"doc_type": "dec_page", "text": _AMERISURE, "facts": {}}]
    account = {"organization_name": "ThinkSmith Agency", "address": "9 Main St, Denver, CO 80202"}
    es._route_producer_party(mf, docs, account)
    assert es._fv(mf, "producer_address") == "9 Main St, Denver, CO 80202"   # the account's
    mf = {"producer_address": "26777 Halsted Rd, Farmington Hills MI 48331-3586"}
    es._route_producer_party(mf, docs, None)
    assert not es._fv(mf, "producer_address")
    # the agency's own address (not printed under an insurer) stays; a person's always does
    mf = {"producer_address": "12 Oak St, Denver, CO"}
    es._route_producer_party(mf, [{"doc_type": "dec_page", "facts": {},
                                   "text": "AGENT: ROCKY RISK PARTNERS\n12 OAK ST, DENVER, CO\n"}], None)
    assert es._fv(mf, "producer_address") == "12 Oak St, Denver, CO"
    mf = {"producer_address": {"value": "26777 Halsted Rd, Farmington Hills MI", "source": "producer"}}
    es._route_producer_party(mf, docs, None)
    assert es._fv(mf, "producer_address")


def test_item_2_an_ai_mailing_state_read_off_an_office_line_is_refused():
    s125 = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas" / "ACORD_125_schema.json")
                      .read_text(encoding="utf-8"))
    st = "NamedInsured_MailingAddress_StateOrProvinceCode_A"
    city = "NamedInsured_MailingAddress_CityName_A"
    pst = "Producer_MailingAddress_StateOrProvinceCode_A"
    mapped = {st: "AZ", city: "Phoenix", pst: "AZ"}
    out = aag.refuse_non_answers(mapped, s125, {}, _TRAVELERS, {st, city, pst}, "ACORD_125")
    assert set(out) == {st, city, pst}
    assert all(v.startswith(aag.REASON_ADDRESS_NOT_THIS_PERSONS) for v in out.values())
    mapped = {st: "CO", city: "Denver"}
    assert aag.refuse_non_answers(mapped, s125, {}, _AMERISURE, {st, city}, "ACORD_125") == {}


# ══ 3 (W2). A summary of the insurance is not the business description ══════
_W2 = "Business auto coverage for a fleet of vehicles garaged in Denver, Colorado."
_AUTO_TEXT = "BUSINESS AUTO COVERAGE FORM\nNAMED INSURED: CHOICE ELECTRIC LLC\nGARAGING: DENVER CO\n"


def test_w2_rule():
    assert describes_insurance_not_business(_W2, _AUTO_TEXT)
    # printed in the document: its own words stand; no coverage talk; no text to judge
    assert not describes_insurance_not_business("Business auto coverage form", _AUTO_TEXT)
    assert not describes_insurance_not_business("Commercial electrical contractor", _AUTO_TEXT)
    assert not describes_insurance_not_business(_W2, "")


def test_w2_the_merge_and_the_ai_fill_both_refuse_it():
    doc = {"doc_id": "a", "filename": "auto.pdf", "doc_type": "dec_page", "text": _AUTO_TEXT,
           "facts": {"applicant_name": "Choice Electric LLC", "operations_description": _W2}, "flags": {}}
    assert es.drop_coverage_descriptions(copy.deepcopy(doc)) == ["operations_description"]
    docs = [copy.deepcopy(doc)]
    facts, _f = es.merge_facts(docs, es.select_primary_truth(docs))
    assert es._fv(facts, "operations_description") != _W2
    s125 = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas" / "ACORD_125_schema.json")
                      .read_text(encoding="utf-8"))
    box = "CommercialPolicy_OperationsDescription_A"
    out = aag.refuse_non_answers({box: _W2}, s125, {}, _AUTO_TEXT, {box}, "ACORD_125")
    assert out[box].startswith(aag.REASON_SUMMARY)
    kept = {box: "Commercial electrical contracting"}
    assert aag.refuse_non_answers(kept, s125, {}, _AUTO_TEXT, {box}, "ACORD_125") == {}


# ══ Review fixes (24 Oct 2026) ═══════════════════════════════════════════════

def test_two_column_dec_insurer_above_the_other_column_is_not_the_applicants():
    from services.insured_scope import address_is_a_party_office
    text = ("NAMED INSURED AND ADDRESS                 COMPANY\n"
            "CHOICE ELECTRIC LLC                        TRAVELERS CASUALTY COMPANY OF AMERICA\n"
            "123 MAIN ST                                ONE TOWER SQUARE 9\n"
            "DENVER CO 80202                            HARTFORD CT 06183")
    assert not address_is_a_party_office("123 Main St, Denver CO 80202", [text])
    assert address_is_a_party_office("One Tower Square 9, Hartford CT", [text])
    assert address_is_a_party_office(
        "26777 Halsted Rd", ["AMERISURE INSURANCE COMPANY\n26777 HALSTED RD\nFARMINGTON HILLS MI"])


def test_one_ordinary_word_is_not_coverage_talk():
    doc = "Insurance agency. Trucks parked at yard."
    assert not describes_insurance_not_business(
        "Independent insurance agency selling commercial and personal insurance policies", doc)
    assert not describes_insurance_not_business("Long-haul trucking; tractors garaged at the Denver terminal", doc)
    assert not describes_insurance_not_business("Security firm providing 24/7 patrol coverage", doc)
    assert describes_insurance_not_business("Commercial auto policy covering 12 vehicles garaged in Denver", doc)
    assert describes_insurance_not_business(_W2, _AUTO_TEXT)


def test_hired_pd_deductible_in_a_padded_table_is_read():
    pad = " " * 30
    text = ("BUSINESS AUTO DECLARATIONS\nHIRED AUTO PHYSICAL DAMAGE COVERAGE\n"
            f"COVERAGE{pad}LIMIT OF INSURANCE{pad}DEDUCTIBLE{pad}PREMIUM\n"
            f"COMPREHENSIVE{pad}ACTUAL CASH VALUE OR COST OF REPAIR, WHICHEVER IS LESS{pad}$500{pad}$25\n"
            f"COLLISION{pad}ACTUAL CASH VALUE OR COST OF REPAIR, WHICHEVER IS LESS{pad}$750{pad}$40\n")
    facts = se.attach_documents({}, [_auto_doc(text)])
    assert se.hired_pd_values({_HPD: "$750"}, {}, facts, "ACORD_137_CO", {_HPD}) == {}
