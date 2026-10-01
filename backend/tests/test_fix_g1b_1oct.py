"""1 Oct 2026 - the wrong values the Orbin audit found on the newest run
(session 69687a55, the client's own 271-page declarations package), fixed in
`services/pdf_service.py`. Every fixture below is the live shape, trimmed to
the boxes and text the rule reads.

1. ACORD 127 NAME OF OTHER OWNER = "Emcasco Insurance Company" (the dec's
   corporate signature block), and Pass C then promoted "any vehicles not
   solely owned?" to Yes from it.
2. ACORD 126 "products of others sold or repackaged under applicant label?" = Y
   on 'Repackages or relabels "CBD products"' - item c. of the umbrella's
   cannabis exclusion, written with escaped quotes.
3. ACORD 186 "contractor's number of years of experience" = 20, in no document.
4. AI "No" answers on questions the package never addresses (126 pool /
   lodging / recreation, 127 drivers not covered by workers compensation).
5. Item 4: the calculated proposed dates were labelled "filled".
6. A person's typed value printed re-cased ("CBRE" -> "Cbre", "JLL" -> "Jll").
"""
from __future__ import annotations

import copy
import json
import os

import pytest

import services.pdf_service as ps

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


S125, S126, S127, S131, S186 = (_schema(f) for f in
                                ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_186"))


@pytest.fixture(autouse=True)
def _no_judge(monkeypatch):
    """The judge is an LLM; offline it is UNAVAILABLE (silence changes nothing)."""
    monkeypatch.setattr(ps, "_judge_evidence_batch", lambda items, form_id="", unjudged=None: {})


def _fill(fid, schema, raw, values, grounding=None, facts=None, report=None):
    mapped, conf = ps.map_facts_to_form(
        copy.deepcopy(facts or {}), schema, form_id=fid, raw_text=raw,
        pre_filled_gpt={"filled_values": dict(values), "raw_text_fields": set(),
                        "question_grounding": dict(grounding or {})},
        guard_report=report)
    return mapped, conf


# ══ 1. An insurer as the vehicle's other owner ═══════════════════════════════

_OWNER_C = "AdditionalInterest_FullName_C"
_AAJ = "CommercialVehicleLineOfBusiness_Question_AAJCode_A"
# The dec's own signature block, as printed (69687a55).
_SIGNATURE_BLOCK = (
    "IN WITNESS WHEREOF, this Company has executed and attested these presents.\n"
    "Todd A. Strother, Secretary Scott R. Jean, President\n"
    "EMCASCO Insurance Company\n"
    "Corporate Office, Des Moines, Iowa\n")
_CARRIER_LINES = {"coverage_lines": {"value": [
    {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company"},
    {"line": "Commercial Auto", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY"}],
    "source": "ai"}}


def test_the_live_insurer_co_owner_is_refused_and_does_not_promote_the_question():
    report: list = []
    mapped, _ = _fill("ACORD_127", S127, _SIGNATURE_BLOCK,
                      {_OWNER_C: "Emcasco Insurance Company"}, facts=_CARRIER_LINES,
                      report=report)
    assert not mapped.get(_OWNER_C)
    # Pass C promoted this to Y from the name on the live run.
    assert not mapped.get(_AAJ)
    row = next(r for r in report if r["field"] == _OWNER_C)
    assert row["reason"] == "INSURER_AS_PARTY" and row["removed_value"] == "Emcasco Insurance Company"


@pytest.mark.parametrize("lender", [
    "Ally Financial", "Wells Fargo Bank, N.A.", "Toyota Motor Credit Corporation",
    "Washington Mutual Finance Corporation",       # an insurer word, but a lender
    "First Insurance Funding Corp",                # a premium finance company
])
def test_a_real_lienholder_still_prints_and_still_answers_the_question(lender):
    raw = f"LIENHOLDER: {lender}, P.O. Box 380901, Bloomington, MN 55438\n" + _SIGNATURE_BLOCK
    mapped, _ = _fill("ACORD_127", S127, raw, {_OWNER_C: lender}, facts=_CARRIER_LINES)
    assert mapped.get(_OWNER_C) == lender
    assert mapped.get(_AAJ) == "Y"          # Pass C, unchanged for a real co-owner


def test_a_package_carrier_is_refused_even_without_insurer_words():
    facts = {"coverage_lines": [{"line": "Commercial Auto", "carrier": "Quillon Mutual"}]}
    out = ps._insurer_in_a_party_box({_OWNER_C: "QUILLON MUTUAL"}, facts, {_OWNER_C})
    assert _OWNER_C in out


def test_a_person_and_the_package_itself_outrank_the_shape():
    name = "Liberty Mutual Insurance Company"
    # a producer typed it
    facts = {"landlord_name": {"value": name, "source": "producer"}}
    assert ps._insurer_in_a_party_box({_OWNER_C: name}, facts, {_OWNER_C}) == {}
    # the package records it as the loss payee
    facts = {"loss_payee_name": {"value": name, "source": "ai"}}
    assert ps._insurer_in_a_party_box({_OWNER_C: name}, facts, {_OWNER_C}) == {}
    # a deterministic value is never judged (not in the gap-fill set)
    assert ps._insurer_in_a_party_box({_OWNER_C: name}, {}, set()) == {}
    # the insured's own box and the certificate holder keep their own rules
    for box in ("NamedInsured_FullName_A", "CertificateHolder_FullName_A"):
        assert ps._insurer_in_a_party_box({box: name}, {}, {box}) == {}


def test_a_pass_c_yes_falls_with_its_companion_whichever_guard_takes_it():
    """The class, not the case: whichever guard refuses the OTHER OWNER name -
    here the applicant's own name - the "not solely owned?" Yes that stood on
    it goes too (the late Yes-substantiation sweep; the insurer guard runs
    before Pass C, so an insurer never promotes it at all)."""
    raw = "Named Insured: ORBIN CONTRACTING LLC\n4800 DAHLIA ST # D13, DENVER, CO 80216-3121\n"
    facts = {"applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"}}
    mapped, _ = _fill("ACORD_127", S127, raw, {_OWNER_C: "ORBIN CONTRACTING LLC"}, facts=facts)
    assert not mapped.get(_OWNER_C)
    assert not mapped.get(_AAJ)


# ══ 2. An exclusion quoted as a "Yes" ════════════════════════════════════════

_ABF = "GeneralLiabilityLineOfBusiness_Question_ABFCode_A"
_ABF_X = "GeneralLiabilityLineOfBusiness_ProductsOfOthersSoldUnderApplicantLabelExplanation_A"
# The umbrella's cannabis endorsement, as printed (69687a55), trimmed.
_CANNABIS = (
    "B. Limited Exception for Retails Sales of CBD\nProducts\n"
    "1. The exclusion in Paragraph A. of this\nendorsement does not apply to \"bodily injury\"\n"
    "or \"property damage\" arising out of your retail\nsales of \"CBD products\" to consumers.\n"
    "However, this exception does not apply if any\ninsured:\n"
    "a. Offers or asserts any false or\nunsubstantiated claims or statements\n"
    "regarding the safety or effectiveness of\n\"CBD products\";\n"
    "b. Makes any physical or chemical change to\n\"CBD products\";\n"
    "c. Repackages or relabels \"CBD products\";\n"
    "d. Uses \"CBD products\" as ingredients in\nanother product;\n")
# The live explanation, exactly as stored: the model's escaped quote.
_LIVE_EXPLANATION = '"Repackages or relabels \\"CBD products\\";"'


def test_an_escaped_defined_term_is_still_policy_wording():
    assert ps._is_policy_wording_fragment(_LIVE_EXPLANATION)
    assert ps._evidence_as_printed(_LIVE_EXPLANATION) == '"Repackages or relabels "CBD products";"'
    # unchanged readings
    assert not ps._is_policy_wording_fragment("Subcontractors are required to carry coverage.")
    assert not ps._is_policy_wording_fragment('THE MOST "WE" PAY')


def test_the_live_cbd_yes_and_its_explanation_are_refused():
    report: list = []
    mapped, _ = _fill("ACORD_126", S126, _CANNABIS, {_ABF: "Y", _ABF_X: _LIVE_EXPLANATION},
                      report=report)
    assert not mapped.get(_ABF) and not mapped.get(_ABF_X)
    assert next(r for r in report if r["field"] == _ABF)["reason"] == "EVIDENCE_IS_POLICY_WORDING"


def test_the_same_exclusion_without_its_quote_marks_is_refused_by_where_it_sits():
    """A model that drops the defined term's quotes defeats the quote-shape
    check; the sentence still sits in the exclusion."""
    quote = "Repackages or relabels CBD products"
    assert not ps._is_policy_wording_fragment(quote)
    mapped, _ = _fill("ACORD_126", S126, _CANNABIS, {_ABF: "Y"}, grounding={_ABF: quote})
    assert not mapped.get(_ABF) and not mapped.get(_ABF_X)


def test_an_applicant_statement_yes_still_stands():
    raw = ("UNDERWRITING NARRATIVE\nThe applicant repackages hardware made by others and "
           "sells it under its own label through two retail stores.\n")
    sentence = ("The applicant repackages hardware made by others and sells it under its "
                "own label through two retail stores.")
    mapped, _ = _fill("ACORD_126", S126, raw, {_ABF: "Y", _ABF_X: sentence})
    assert mapped.get(_ABF) == "Y" and mapped.get(_ABF_X) == sentence


def test_a_coverage_question_may_still_cite_the_policy():
    assert ps._question_is_about_coverage("CommercialUmbrellaLineOfBusiness_Question_AAICode_A", S131)
    assert ps._question_is_about_coverage("CommercialPolicy_Question_AAHCode_A", S125)
    assert ps._question_is_about_coverage("Policy_LineOfBusiness_CommercialGeneralLiability_A", S125)
    assert not ps._question_is_about_coverage(_ABF, S126)


def test_the_context_reader_fails_open():
    assert not ps._evidence_sits_in_policy_wording("CBD", _CANNABIS)           # too short to place
    assert not ps._evidence_sits_in_policy_wording("not printed anywhere at all", _CANNABIS)
    assert not ps._evidence_sits_in_policy_wording("Repackages or relabels CBD products", "")
    # one place outside the wording is enough to keep it
    raw = _CANNABIS + "\n" * 3 + "x" * 900 + "\nApplicant: repackages or relabels CBD products daily.\n"
    assert not ps._evidence_sits_in_policy_wording("repackages or relabels CBD products", raw)


# ══ 4. An AI "No" the package never supports ═════════════════════════════════

_POOL = "GeneralLiabilityLineOfBusiness_Question_KAHCode_A"
_LODGING = "GeneralLiabilityLineOfBusiness_Question_KAACode_A"
_WC_DRIVERS = "CommercialVehicleLineOfBusiness_Question_AAHCode_A"
# The Common Declarations' premium table, as printed (page 1 of 69687a55).
_COMMON_DEC = ("Coverages and Premium\nSection Coverage Premium\n1 Property No Coverage\n"
               "2 Liability $3,954.00\n3 Crime and Fidelity No Coverage\n4 Inland Marine $300.00\n"
               "5 Automobile $2,991.00\n6 Workers' Compensation No Coverage\n7 Umbrella $3,418.00\n")
# A GL exclusion endorsement's definition (page 254 of 69687a55).
_MULTI_FAMILY = (
    "B. The following definition is added to Section V - Definitions:\n"
    "\"Multi-family housing\" means apartments, condominiums, townhouses or cooperatives.\n"
    "\"Multi-family housing\" does not include any structure that functions solely as an "
    "apartment building, hotel, motel, nursing home or college dormitory.\n"
    "This exclusion applies to \"bodily injury\" and \"property damage\".\n")


@pytest.mark.parametrize("field,quote", [
    (_POOL, "1 Property No Coverage"),
    (_LODGING, "3 Crime and Fidelity No Coverage"),
])
def test_a_coverage_denial_cannot_answer_an_applicant_question(field, quote):
    report: list = []
    mapped, _ = _fill("ACORD_126", S126, _COMMON_DEC, {field: "N"}, grounding={field: quote},
                      report=report)
    assert not mapped.get(field)
    assert next(r for r in report if r["field"] == field)["reason"] == "EVIDENCE_IS_A_COVERAGE_DENIAL"


def test_no_workers_comp_is_not_no_to_drivers_not_covered_by_workers_comp():
    mapped, _ = _fill("ACORD_127", S127, _COMMON_DEC, {_WC_DRIVERS: "N"},
                      grounding={_WC_DRIVERS: "6 Workers' Compensation No Coverage"})
    assert not mapped.get(_WC_DRIVERS)


def test_policy_wording_cannot_answer_no_either():
    quote = ("does not include any structure that functions solely as an apartment building, "
             "hotel, motel, nursing home or college dormitory")
    mapped, _ = _fill("ACORD_126", S126, _MULTI_FAMILY, {_LODGING: "N"}, grounding={_LODGING: quote})
    assert not mapped.get(_LODGING)


def test_a_grounded_applicant_no_still_stands():
    raw = "SUPPLEMENTAL APPLICATION\nThere is no swimming pool on the premises.\n"
    mapped, _ = _fill("ACORD_126", S126, raw, {_POOL: "N"},
                      grounding={_POOL: "There is no swimming pool on the premises."})
    assert mapped.get(_POOL) == "N"


def test_a_coverage_question_may_still_be_answered_no_by_a_denial():
    assert not ps._denial_cannot_answer("CommercialUmbrellaLineOfBusiness_Question_AAICode_A", S131)
    # ...but never "are any ... NOT covered?" - "No" there claims full coverage
    assert ps._denial_cannot_answer(_WC_DRIVERS, S127)


# ══ 3. A count nothing states ════════════════════════════════════════════════

_YEARS = "ContractorsUnderwriting_YearsExperienceCount_A"


def test_the_invented_years_of_experience_is_refused():
    raw = ("CONTRACTORS - SUBCONTRACTED WORK - IN CONNECTION WITH CONSTRUCTION 91580 "
           "Form: CG 00 01 04 13 Ed. 20 Policy Period 07/15/2025 to 07/15/2026\n")
    report: list = []
    mapped, _ = _fill("ACORD_186", S186, raw, {_YEARS: "20"}, report=report)
    assert not mapped.get(_YEARS)
    assert next(r for r in report if r["field"] == _YEARS)["reason"] == "COUNT_NOT_IN_DOCUMENTS"


@pytest.mark.parametrize("raw", [
    "The contractor has 20 years of experience in commercial roofing.\n",
    "Years of experience: 20\n",
    "Owner has twenty years experience in the trade.\n",
])
def test_a_stated_count_survives(raw):
    mapped, _ = _fill("ACORD_186", S186, raw, {_YEARS: "20"})
    assert mapped.get(_YEARS) == "20"


def test_a_count_a_fact_holds_survives():
    facts = {"years_in_business": {"value": "20", "source": "derived", "confidence": "deterministic"}}
    mapped, _ = _fill("ACORD_186", S186, "No relevant text.\n", {_YEARS: "20"}, facts=facts)
    assert mapped.get(_YEARS) == "20"


def test_only_counts_are_judged():
    # a phone number, a producer-assigned number and a measurement are not counts
    for fid, schema, box in (("ACORD_125", S125, "NamedInsured_Contact_PrimaryPhoneNumber_A"),
                             ("ACORD_125", S125, "CommercialStructure_Location_ProducerIdentifier_A"),
                             ("ACORD_125", S125, "Construction_BuildingArea_A")):
        assert not ps._count_subject_words(str(schema[box].get("tu") or "")), box
    assert ps._count_subject_words(S186[_YEARS]["tu"]) == {"year", "experience"}
    # nothing to check against - no opinion
    m = {_YEARS: "20"}
    assert ps._drop_unstated_counts(m, S186, {}, "", {_YEARS}) == {} and m[_YEARS] == "20"
    # a value no gap fill wrote is never judged
    m = {_YEARS: "20"}
    assert ps._drop_unstated_counts(m, S186, {}, "no text", set()) == {} and m[_YEARS] == "20"


# ══ 5. Item 4 - a calculated date asks to be verified ════════════════════════

_DERIVED_TERM = {
    "effective_date": {"value": "07/15/2026", "confidence": "low_confidence", "source": "derived",
                       "derivation": {"rule": "next_term_after_current_policy",
                                      "inputs": ["prior_expiration_date"]}},
    "expiration_date": {"value": "07/15/2027", "confidence": "low_confidence", "source": "derived",
                        "derivation": {"rule": "renewal_routing_prior_term_length",
                                       "inputs": ["prior_effective_date", "prior_expiration_date"]}},
}


@pytest.mark.parametrize("fid,schema", [("ACORD_125", S125), ("ACORD_126", S126), ("ACORD_186", S186)])
def test_the_derived_proposed_dates_ask_to_be_verified(fid, schema):
    mapped, conf = _fill(fid, schema, "", {}, facts=_DERIVED_TERM)
    assert mapped.get("Policy_EffectiveDate_A") == "07/15/2026"
    assert conf.get("Policy_EffectiveDate_A") == "low_confidence"
    if "Policy_ExpirationDate_A" in schema and mapped.get("Policy_ExpirationDate_A"):
        assert conf.get("Policy_ExpirationDate_A") == "low_confidence"


def test_a_stated_or_self_certain_value_keeps_filled():
    stated = {"effective_date": {"value": "07/15/2026", "confidence": "high", "source": "ai"}}
    _m, conf = _fill("ACORD_125", S125, "", {}, facts=stated)
    assert conf.get("Policy_EffectiveDate_A") == "filled"
    arithmetic = {"effective_date": {"value": "07/15/2026", "confidence": "deterministic",
                                     "source": "derived"}}
    _m, conf = _fill("ACORD_125", S125, "", {}, facts=arithmetic)
    assert conf.get("Policy_EffectiveDate_A") == "filled"
    # a box printing something other than the derived value keeps its label
    conf = {"Policy_EffectiveDate_A": "filled"}
    ps.apply_derived_value_labels("ACORD_125", dict(_DERIVED_TERM),
                                  {"Policy_EffectiveDate_A": "07/15/2025"}, conf)
    assert conf["Policy_EffectiveDate_A"] == "filled"


# ══ 6. A person's value prints exactly as typed ══════════════════════════════

@pytest.mark.parametrize("typed", ["CBRE Group Inc", "JLL", "Blake St Partners II LLC",
                                   "Claude sharma", "Astrea It services", "eBay Inc",
                                   "ACME BUILDERS LLC"])
def test_an_answer_path_prints_what_the_person_typed(typed):
    for box in ("AdditionalInterest_FullName_A", "Producer_FullName_A"):
        assert ps.display_value_for_box("ACORD_125", box, typed) == typed
        assert ps.display_value_for_box("ACORD_125", box, typed, provenance="producer") == typed


@pytest.mark.parametrize("typed,printed", [("claude sharma", "Claude Sharma"),
                                           ("vinay sharma", "Vinay Sharma"),
                                           ("blake st partners llc", "Blake St Partners LLC")])
def test_text_typed_with_no_capital_is_formatted_as_before(typed, printed):
    # Quick lower-case typing is not a chosen spelling: it prints like a
    # document's value (FR125 replay, 1 Oct - "vinay sharma" printed lower case).
    for prov in (None, "producer", "client_arq"):
        assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_FullName_A",
                                        typed, provenance=prov) == printed
    facts = {"landlord_name": {"value": typed, "source": "client_arq"}}
    assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_FullName_A",
                                    typed, facts=facts) == printed


def test_a_document_value_is_still_formatted():
    assert ps.display_value_for_box("ACORD_125", "NamedInsured_FullName_A", "ORBIN CONTRACTING LLC",
                                    provenance="filled") == "Orbin Contracting LLC"
    # money, dates and state codes are formatted whoever typed them
    assert ps.display_value_for_box("ACORD_125", "CommercialStructure_AnnualRevenueAmount_A",
                                    "300000") in ("300,000", "$300,000")
    assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_MailingAddress_StateOrProvinceCode_A",
                                    "co") == "CO"
    # with facts, the person is found by their own text
    facts = {"landlord_name": {"value": "JLL", "source": "client_arq"}}
    assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_FullName_A", "JLL", facts=facts) == "JLL"
    assert ps.display_value_for_box("ACORD_125", "NamedInsured_FullName_A", "ORBIN CONTRACTING LLC",
                                    facts=facts) == "Orbin Contracting LLC"


def test_generation_prints_the_account_agency_and_the_landlord_as_typed():
    facts = {
        "applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"},
        "producer_name": {"value": "Astrea It services", "source": "account"},
        "property_locations": [{"address": "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
                                "address_line1": "4800 DAHLIA ST", "address_line2": "# D13",
                                "address_city": "DENVER", "address_state": "CO",
                                "address_zip": "80216-3121", "location_number": "1",
                                "is_owner": None, "is_tenant": None, "is_other_interest": None,
                                "other_interest_description": None}],
        "premises_interest": {"value": "Tenant - the business rents its space", "source": "producer"},
        "landlord_name": {"value": "CBRE Group Inc", "source": "producer"},
        "landlord_address": {"value": "1200 Blake St, Suite 4, Denver, co 80202", "source": "producer"},
        "has_property_coverage": False,
    }
    mapped, _ = _fill("ACORD_125", S125, "", {}, facts=facts)
    assert mapped.get("Producer_FullName_A") == "Astrea It services"
    assert mapped.get("NamedInsured_FullName_A") == "Orbin Contracting LLC"      # the document's
    assert mapped.get("AdditionalInterest_FullName_A") == "CBRE Group Inc"
    # the typed address still splits into its boxes; the state code is a code
    assert mapped.get("AdditionalInterest_MailingAddress_LineOne_A") == "1200 Blake St"
    assert mapped.get("AdditionalInterest_MailingAddress_LineTwo_A") == "Suite 4"
    assert mapped.get("AdditionalInterest_MailingAddress_CityName_A") == "Denver"
    assert mapped.get("AdditionalInterest_MailingAddress_StateOrProvinceCode_A") == "CO"
    assert mapped.get("AdditionalInterest_MailingAddress_PostalCode_A") == "80202"


def test_a_document_value_that_only_matches_in_other_letters_is_not_the_persons():
    assert not ps._is_verbatim_piece("DENVER", "1200 Blake St, Denver, CO 80202")
    assert ps._is_verbatim_piece("Denver", "1200 Blake St, Denver, CO 80202")
    assert not ps._is_verbatim_piece("Den", "1200 Blake St, Denver, CO 80202")


# ══ Edges added on review (1 Oct 2026) ═══════════════════════════════════════

def test_only_the_insurers_own_dec_labels_name_a_carrier():
    """A carrier-owned dec row also prints the place of issue, the underwriter
    and the website, and a "company" label also names the insured's parent or
    subsidiary - none of them is an insurer, so none is refused as one."""
    entries = [
        {"label": "Company", "owner": "carrier", "value": "EMCASCO Insurance Company"},
        {"label": "Place of Issue", "owner": "carrier", "value": "Des Moines, IA"},
        {"label": "Underwriter", "owner": "carrier", "value": "Dana Whitfield"},
        {"label": "Parent company name", "owner": "other", "value": "Front Range Holdings Inc"},
        {"label": "Subsidiary company name", "owner": "other",
         "value": "Front Range Service Company LLC"},
        {"label": "Issuing Company", "owner": "carrier", "value": "Quillon Specialty"},
    ]
    keys = ps._package_carrier_keys({"dec_page_entries": entries})
    assert ps._carrier_identity_key("Quillon Specialty") in keys
    for not_a_carrier in ("Des Moines, IA", "Dana Whitfield", "Front Range Holdings Inc",
                          "Front Range Service Company LLC"):
        assert ps._carrier_identity_key(not_a_carrier) not in keys, not_a_carrier
        assert ps._insurer_in_a_party_box({_OWNER_C: not_a_carrier},
                                          {"dec_page_entries": entries}, {_OWNER_C}) == {}


@pytest.mark.parametrize("value,refused", [
    ("Insurance Services Office, Inc.", True),       # the ISO copyright line, not a party
    ("Smith Insurance Agency, Inc.", False),          # an intermediary is not an insurer
    ("Northgate Insurance Partners LLC", False),      # no company word - not insurer-shaped
    ("", False), (None, False),
])
def test_insurer_shape_edges(value, refused):
    out = ps._insurer_in_a_party_box({_OWNER_C: value}, {}, {_OWNER_C})
    assert (_OWNER_C in out) is refused


def test_every_owner_box_on_every_form_is_covered():
    """The guard decides the box from ACORD's own naming, so every additional
    interest / owner name box on all 17 forms is in scope, and no other name box is."""
    import glob
    in_scope = set()
    for path in glob.glob(os.path.join(HERE, "..", "forms_schemas", "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            for box in json.load(fh):
                if ps._insurer_in_a_party_box({box: "Emcasco Insurance Company"}, {}, {box}):
                    in_scope.add(box.rsplit("_", 1)[0])
    assert in_scope == {"AdditionalInterest_FullName"}


def test_the_question_the_insurer_answered_says_why_in_the_report():
    report: list = []
    mapped, _ = _fill("ACORD_127", S127, _SIGNATURE_BLOCK,
                      {_OWNER_C: "Emcasco Insurance Company", _AAJ: "Y"},
                      facts=_CARRIER_LINES, report=report)
    assert not mapped.get(_OWNER_C) and not mapped.get(_AAJ)
    assert next(r for r in report if r["field"] == _AAJ)["reason"] == "SUPPORT_WAS_AN_INSURER"


def test_a_coverage_denial_still_answers_a_coverage_question_no():
    # "Any other insurance with this company?" is about coverage: a denial is
    # not refused by the coverage-denial rule (other rules still judge it).
    assert not ps._coverage_denial_cannot_answer_no(
        "6 Workers' Compensation No Coverage", "CommercialPolicy_Question_AAHCode_A", S125)
    assert ps._coverage_denial_cannot_answer_no(
        "6 Workers' Compensation No Coverage", _WC_DRIVERS, S127)
    assert ps._coverage_denial_cannot_answer_no("1 Property No Coverage", _POOL, S126)
    # no denial in the quote - not this rule's business
    assert not ps._coverage_denial_cannot_answer_no("There is no swimming pool.", _POOL, S126)
    assert not ps._coverage_denial_cannot_answer_no(None, _POOL, S126)


def test_an_inherited_grade_on_a_derived_fact_keeps_filled():
    """Only a derivation that grades ITSELF an estimate asks to be verified; a
    rebuilt composite carries whatever grade the fact it replaced had."""
    for grade in ("ai_low", "high", "medium", None):
        facts = {"effective_date": {"value": "07/15/2026", "source": "derived",
                                    "confidence": grade}}
        conf = {"Policy_EffectiveDate_A": "filled"}
        ps.apply_derived_value_labels("ACORD_125", facts, {"Policy_EffectiveDate_A": "07/15/2026"}, conf)
        assert conf["Policy_EffectiveDate_A"] == "filled", grade
    # a label other than "filled" is never touched (a producer's own date)
    conf = {"Policy_EffectiveDate_A": "producer"}
    ps.apply_derived_value_labels("ACORD_125", dict(_DERIVED_TERM),
                                  {"Policy_EffectiveDate_A": "07/15/2026"}, conf)
    assert conf["Policy_EffectiveDate_A"] == "producer"
    # malformed inputs fail open
    assert ps.apply_derived_value_labels("ACORD_125", None, {}, {}) == {}
    assert ps.apply_derived_value_labels("ACORD_125", {}, None, None) is None


def test_typed_value_edges():
    # nothing typed - the document's value is formatted exactly as before
    assert ps._typed_texts({}) == [] and ps._typed_texts(None) == []
    assert ps.display_value_for_box("ACORD_125", "NamedInsured_FullName_A", "ORBIN CONTRACTING LLC",
                                    facts={}) == "Orbin Contracting LLC"
    # a typed value keeps its letters but not stray whitespace
    assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_FullName_A",
                                    "  CBRE   Group Inc ", provenance="client_arq") == "CBRE Group Inc"
    # a derivation's value is not a person's
    assert ps.display_value_for_box("ACORD_125", "NamedInsured_FullName_A", "ORBIN CONTRACTING LLC",
                                    provenance="filled") == "Orbin Contracting LLC"
    # None stays None
    assert ps.display_value_for_box("ACORD_125", "AdditionalInterest_FullName_A", None) is None
