"""FR125 v2, round 2 test 3 (session 4c734a06, 28 Sep 2026) - the fixes.

The run scored 219 of 312 with 49 wrong and 8 made up. Every defect was traced
on the stored session; the stored run replayed through these fixes scores 297,
1 wrong, 0 made up. Orbin's stored run moves 4 boxes (all earlier fixes or an
unprinted "No"); FR125 v1's gains 1 and loses nothing.

Each test names the CLASS, not the kit: a lender that DECLINES an item, a tooltip
that says what a box is, a unit on the wrong line, a renewal a document calls
new business, a current term that precedes the proposal.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                   # noqa: E402
import services.extraction_service as es                            # noqa: E402

SCHEMA = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text())


def _ctx():
    return ps._schema_context(SCHEMA)


# ═════════════════════════════════════════════════════════════════════════════
# 1. A declined item is not a requested one
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("text,cert,pol,bill", [
    ("Certificate of insurance (policy copy not required; do not send bills)", True, False, False),
    ("Certificate and policy copy required; send bill to the lender", True, True, True),
    ("Policy copy required", False, True, False),
    ("No certificate needed", False, False, False),
])
def test_interest_evidence_reads_each_clause(text, cert, pol, bill):
    facts = {"additional_interests": [{"name": "Peak National Bank", "evidence_requested": text}]}
    got = {k: ps._resolve_additional_interest_evidence(f"AdditionalInterest_{k}_A", facts) == "Y"
           for k in ("CertificateRequiredIndicator", "PolicyRequiredIndicator", "SendBillIndicator")}
    assert got == {"CertificateRequiredIndicator": cert, "PolicyRequiredIndicator": pol,
                   "SendBillIndicator": bill}


# ═════════════════════════════════════════════════════════════════════════════
# 2. The tooltip decides what a box is: NAME OF TRUST
# ═════════════════════════════════════════════════════════════════════════════
_TRUST_BOX = "AdditionalInterest_FullName_B"
_TWO_INTERESTS = [{"name": "Peak National Bank"}, {"name": "Rocky Mountain Equipment Finance LLC"}]


def _trust(answer, text):
    return {"additional_interests": _TWO_INTERESTS, "disclosure_answers": [
        {"topic": "business_in_trust", "answer": answer, "evidence_quote": text,
         "explanation": text}]}


def test_the_trust_box_prints_the_trust_never_the_second_interest():
    with _ctx():
        facts = _trust("Y", "The managing member's interest is held by the Ortega Family Trust.")
        assert ps._resolve_trust_name_box(_TRUST_BOX, facts) == "Ortega Family Trust"
        assert ps._resolve_additional_interest_detail(_TRUST_BOX, facts) is ps._SCHED_SKIP
        # question 11 NO: an owned blank, and still never the loss payee
        assert ps._resolve_trust_name_box(_TRUST_BOX, _trust("N", "Not placed in a trust.")) is None
        # silence is not an answer: no question-11 entry, or a YES naming no
        # trust, leaves the box to the gated gap fill - never to the interest
        assert ps._resolve_trust_name_box(_TRUST_BOX, _trust("Y", "Yes, placed in trust.")) \
            is ps._SCHED_SKIP
        assert ps._resolve_trust_name_box(_TRUST_BOX, {"additional_interests": _TWO_INTERESTS}) \
            is ps._SCHED_SKIP
        # row A is a real interest, untouched
        assert ps._resolve_trust_name_box("AdditionalInterest_FullName_A", facts) is ps._SCHED_SKIP


def test_the_trust_box_is_known_without_a_schema_context():
    """A post-generation re-stamp runs with no schema context; `_form_id` names
    the form. ACORD 127's `AdditionalInterest_FullName_B` is a REAL second
    interest and must stay one."""
    facts = dict(_trust("Y", "Held by the Ortega Family Trust."), _form_id="ACORD_125")
    assert ps._is_trust_name_box(_TRUST_BOX, facts)
    assert not ps._is_trust_name_box(_TRUST_BOX, dict(facts, _form_id="ACORD_127"))
    # ...and the named form outranks a context another form left behind
    with _ctx():
        assert not ps._is_trust_name_box(_TRUST_BOX, dict(facts, _form_id="ACORD_127"))


# ═════════════════════════════════════════════════════════════════════════════
# 3. Payment plan is a CODE; method of payment is a METHOD
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("plan,code", [
    ("monthly EFT", "MO"), ("Annual (paid in full)", "AN"), ("Quarterly", "QT"),
    ("MO", "MO"), ("semi-annual", "semi-annual"), ("10 pay", "10 pay")])
def test_payment_plan_becomes_the_tooltip_code(plan, code):
    with _ctx():
        assert ps._resolve_payment_schedule(
            "Policy_Payment_PaymentScheduleCode_A", {"payment_plan": plan}) == code


def test_a_stated_method_outranks_the_billing_plan():
    f = "Policy_PaymentMethod_MethodDescription_A"
    assert ps._resolve_payment_method_description(
        f, {"payment_plan": "monthly EFT", "billing_plan": "Direct bill"}) == "EFT"
    assert ps._resolve_payment_method_description(
        f, {"payment_method": "credit card", "billing_plan": "Agency bill"}) == "credit card"
    # the billing plan alone still prints, exactly as before (6 Sep / 14 Aug)
    assert ps._resolve_payment_method_description(f, {"billing_plan": "DIRECT BILL"}) == "DIRECT BILL"
    assert ps._resolve_payment_method_description(f, {}) is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. The guards that deleted correct values
# ═════════════════════════════════════════════════════════════════════════════
def test_a_carrier_that_renewed_is_kept_in_every_year():
    carrier = "Timberline Mutual Insurance Company"
    facts = {"prior_coverage_by_line": [
        {"line": "General Liability", "carrier": carrier, "policy_no": f"GL-{y}",
         "effective": f"10/01/{y}", "expiration": f"10/01/{y + 1}"} for y in (2024, 2023)]}
    mapped = {"PriorCoverage_GeneralLiability_InsurerFullName_A": carrier,
              "PriorCoverage_GeneralLiability_InsurerFullName_B": carrier}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, facts)
    assert mapped["PriorCoverage_GeneralLiability_InsurerFullName_B"] == carrier
    # an UNGROUNDED repeat of the same roster name still goes
    mapped = {"PriorCoverage_GeneralLiability_InsurerFullName_A": carrier,
              "PriorCoverage_GeneralLiability_InsurerFullName_B": carrier}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert not mapped["PriorCoverage_GeneralLiability_InsurerFullName_B"]


def test_a_different_suite_is_a_different_address():
    mapped = {"NamedInsured_MailingAddress_LineOne_A": "8000 Commerce Way",
              "NamedInsured_MailingAddress_LineTwo_A": "Suite 120",
              "NamedInsured_MailingAddress_LineOne_B": "8000 Commerce Way, Suite 130"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert mapped["NamedInsured_MailingAddress_LineOne_B"] == "8000 Commerce Way"
    assert mapped["NamedInsured_MailingAddress_LineTwo_B"] == "Suite 130"


def test_row_a_reformatted_is_still_a_duplicate():
    """The live case Guard 11 was built for must still fire."""
    mapped = {"CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
              "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Dahlia St D13 Denver CO. 80216-3121"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert not mapped["CommercialStructure_PhysicalAddress_LineOne_B"]


def test_the_company_line_may_also_be_a_contacts_second_line():
    base = {"NamedInsured_Primary_PhoneNumber_A": "303-555-0175",
            "NamedInsured_Contact_PrimaryPhoneNumber_A": "303-555-0188",
            "NamedInsured_Contact_SecondaryPhoneNumber_A": "303-555-0175"}
    stated = {"applicant_business_phone": "303-555-0175"}
    m = dict(base)
    assert ps._blank_contact_value_in_an_entity_box(m, SCHEMA, stated) == []
    # no fact saying it is the company's: blanked, as before
    m = dict(base)
    assert ps._blank_contact_value_in_an_entity_box(m, SCHEMA, {}) == [
        "NamedInsured_Primary_PhoneNumber_A"]
    # a contact's PRIMARY line in the company box: blanked whatever the facts
    m = dict(base, NamedInsured_Contact_PrimaryPhoneNumber_A="303-555-0175")
    assert "NamedInsured_Primary_PhoneNumber_A" in \
        ps._blank_contact_value_in_an_entity_box(m, SCHEMA, stated)


def test_an_unresolved_item_has_no_resolve_date():
    d, r = ("CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A",
            "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A")
    q = {"CommercialPolicy_Question_AAFCode_A": "Y",           # question 8 answered
         "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A":
             "Two extinguishers had expired inspection tags."}
    mapped = {**q, d: "Extinguisher service is scheduled.", r: "10/05/2020"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert not mapped[d] and not mapped[r]
    # a future date is a plan, whatever the sentence
    mapped = {**q, d: "Exit cleared and passed re-inspection.", r: "10/05/2099"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert mapped[d] and not mapped[r]
    # a completed, past-dated resolution stands
    mapped = {**q, d: "Invoice paid and the lien released.", r: "02/27/2024"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert mapped[d] and mapped[r] == "02/27/2024"


# ═════════════════════════════════════════════════════════════════════════════
# 5. What the submission says it is
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("text,marked", [
    ("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION", True),
    ("Transaction ........ New business - quote", True),
    ("SUBMISSION TYPE QUOTE (new business to this carrier)", True),
    ("We write new business every day.", False),                   # no transaction word
    ("If this is a new business submission, attach loss runs.", False),  # a condition
    ("Transaction: New business quote\nRenewal submission for GL", False),  # contested
])
def test_a_stated_new_business_submission(text, marked):
    mf = {}
    assert es._mark_stated_new_business(mf, text) is marked
    assert (mf.get("submission_is_new_business") is True) is marked


def test_new_business_ticks_quote_and_never_renew():
    facts = {"is_renewal": "Y", "_form_id": "ACORD_125"}
    assert ps._resolve_policy_status("Policy_Status_RenewIndicator_A", facts) == "Yes"
    facts["submission_is_new_business"] = True
    assert ps._resolve_policy_status("Policy_Status_RenewIndicator_A", facts) is None
    assert ps._resolve_policy_status("Policy_Status_QuoteIndicator_A", facts) == "Yes"


def test_new_business_drops_the_one_writer_renewal_exemption():
    lines = [{"line": "General Liability", "carrier": "Timberline Mutual",
              "policy_number": "GL-1"}]
    mf = {"carrier_name": "Timberline Mutual", "is_renewal": "Y", "coverage_lines": lines}
    es._mark_page_one_current_policy(mf, [])
    assert mf.get("carrier_is_current_policy") is not True           # the exemption
    mf = {"carrier_name": "Timberline Mutual", "is_renewal": "Y", "coverage_lines": lines,
          "submission_is_new_business": True}
    es._mark_page_one_current_policy(mf, [])
    assert mf.get("carrier_is_current_policy") is True


# ═════════════════════════════════════════════════════════════════════════════
# 6. The receiving carrier and its program
# ═════════════════════════════════════════════════════════════════════════════
_ACK = "GRANITE ARCH CASUALTY COMPANY - ACKNOWLEDGEMENT OF SUBMISSION"


def _entries(*rows):
    return {"_form_id": "ACORD_125", "dec_page_entries": [
        {"label": l, "value": v, "section": s, "owner": o} for l, v, s, o in rows]}


def test_a_bare_carrier_label_in_the_submission_section_is_the_addressee():
    facts = _entries(("Carrier", "Granite Arch Casualty Company", _ACK, "carrier"),
                     ("Program code", "CSP-EL", _ACK, "policy"),
                     ("Carrier", "Timberline Mutual", "GL DECLARATIONS - CURRENT POLICY", "carrier"))
    assert ps._receiving_carrier_from_entries(facts) == {
        "name": "Granite Arch Casualty Company", "naic": None}
    assert ps._receiving_section_detail("Insurer_ProductCode_A", facts) == "CSP-EL"
    assert ps._receiving_section_detail("Insurer_Underwriter_FullName_A", facts) is ps._SCHED_SKIP


def test_a_declarations_carrier_is_never_the_addressee():
    facts = _entries(("Carrier", "Timberline Mutual", "SUBMISSION - CURRENT POLICY SCHEDULE", "carrier"))
    assert ps._receiving_carrier_from_entries(facts) is None


def test_two_addressees_are_no_answer():
    facts = _entries(("Carrier", "Granite Arch Casualty Company", _ACK, "carrier"),
                     ("Submitted to", "Northbridge Atlantic", "COVER SHEET", "carrier"))
    assert ps._receiving_carrier_from_entries(facts) is None


# ═════════════════════════════════════════════════════════════════════════════
# 7. Question 4: the document's own answer decides the list
# ═════════════════════════════════════════════════════════════════════════════
_CURRENT = [{"line": "General Liability", "carrier": "Timberline", "policy_number": "GL-123456"}]


def _q4(answer, quote):
    return {"coverage_lines": _CURRENT, "disclosure_answers": [
        {"topic": "other_insurance_with_carrier", "answer": answer, "evidence_quote": quote}]}


def test_q4_yes_lists_the_policies_the_document_names():
    rows = ps._other_policy_rows(_q4(
        "Y", "Workers Compensation WC-GA-448120; Commercial Inland Marine IM-GA-220915"))
    assert [(r["line"], r["policy_number"]) for r in rows] == [
        ("Workers Compensation", "WC-GA-448120"), ("Commercial Inland Marine", "IM-GA-220915")]


def test_q4_no_lists_nothing_and_silence_keeps_the_inferred_list():
    assert ps._other_policy_rows(_q4("N", "No policies are carried with Granite Arch.")) == []
    assert [r["policy_number"] for r in ps._other_policy_rows({"coverage_lines": _CURRENT})] == [
        "GL-123456"]
    # a YES whose quote names no number falls back too
    assert [r["policy_number"] for r in ps._other_policy_rows(
        _q4("Y", "Yes, workers compensation is with this company."))] == ["GL-123456"]


# ═════════════════════════════════════════════════════════════════════════════
# 8. The current term is prior coverage when the proposal follows it
# ═════════════════════════════════════════════════════════════════════════════
def _grid_facts(proposed):
    return {
        "effective_date": proposed, "current_term_rows_ok": True,
        "_line_records": [{"line": "general_liab", "carrier_name": "Timberline",
                           "policy_number": "GL-123456", "effective_date": "10/01/2025",
                           "expiration_date": "10/01/2026"}],
        "prior_coverage_by_line": [{"line": "General Liability", "carrier": "Timberline",
                                    "policy_no": "GL-104471", "effective": "10/01/2024",
                                    "expiration": "10/01/2025"}],
    }


def test_the_current_term_is_year_one_before_the_proposal():
    grid, years = ps._prior_coverage_grid(_grid_facts("10/01/2026"))
    assert years[:2] == ["2025", "2024"]
    assert grid[("GeneralLiability", 0)]["policy_no"] == "GL-123456"


def test_the_current_term_is_not_prior_when_it_is_the_proposal():
    grid, years = ps._prior_coverage_grid(_grid_facts("10/01/2025"))
    assert years == ["2024"]


# ═════════════════════════════════════════════════════════════════════════════
# 9. Copied, not composed; presented where ACORD prints it
# ═════════════════════════════════════════════════════════════════════════════
def test_an_email_is_repaired_to_the_address_the_document_prints():
    text = "Alt e-mail ... jsmith.site@example-electrical.com\nfoo@a.com foo@b.com"
    mf = {"applicant_contacts": [{"secondary_email": "jsmith.site@example.com",
                                  "email": "foo@c.com"}],
          "producer_contact_email": {"value": "jsmith.site@example.com"}}
    es._repair_emails_from_text(mf, text)
    assert mf["applicant_contacts"][0]["secondary_email"] == "jsmith.site@example-electrical.com"
    assert mf["applicant_contacts"][0]["email"] == "foo@c.com"        # two candidates: left
    assert mf["producer_contact_email"]["value"] == "jsmith.site@example-electrical.com"


def test_a_safety_other_box_never_restates_the_listed_elements():
    o, i = ("CommercialPolicy_FormalSafetyProgram_OtherDescription_B",
            "CommercialPolicy_FormalSafetyProgram_OtherIndicator_B")
    mapped = {o: "Safety Manual, Safety Position, Monthly Meetings, OSHA", i: "Yes"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert not mapped[o] and not mapped[i]
    mapped = {o: "Daily job hazard analysis before every shift", i: "Yes"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert mapped[o] and mapped[i] == "Yes"


@pytest.mark.parametrize("given,printed", [
    ("GL", "General Liability"), ("WC", "Workers Compensation"),
    ("General Liability", "General Liability"), ("BA", "BA"), ("Auto", "Auto")])
def test_a_loss_line_prints_in_words(given, printed):
    mapped = {"LossHistory_LineOfBusiness_A": given}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert mapped["LossHistory_LineOfBusiness_A"] == printed


def test_the_unit_moves_to_line_two_only_when_it_is_its_own_segment():
    mapped = {"AdditionalInterest_MailingAddress_LineOne_A": "1600 Broadway, Suite 900",
              "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
              "CommercialStructure_PhysicalAddress_LineOne_B": "5 Main St, Suite 2",
              "CommercialStructure_PhysicalAddress_LineTwo_B": "Rear building"}
    with _ctx():
        ps._enforce_post_fill_guards(mapped, SCHEMA, {})
    assert (mapped["AdditionalInterest_MailingAddress_LineOne_A"],
            mapped["AdditionalInterest_MailingAddress_LineTwo_A"]) == ("1600 Broadway", "Suite 900")
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_A"] == "4800 Dahlia St # D13"
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_B"] == "5 Main St, Suite 2"


@pytest.mark.parametrize("explanation,quote,verbatim", [
    ("The applicant owns one DJI Mavic 3 Enterprise drone for roof and site inspections.",
     "The applicant owns one DJI Mavic 3 Enterprise drone flown by a Part 107 certified "
     "employee for roof and site inspections.", True),
    ("The applicant is 80% owned by Front Range Holdings Inc.",
     "Is the applicant a subsidiary of another entity? X", False),     # the question line
    ("The managing member's interest is held by the Ortega Family Trust.",
     "Trust property includes the managing member's 55% interest in the company.", False),
])
def test_the_explanation_is_the_documents_sentence_when_it_paraphrases_it(
        explanation, quote, verbatim):
    got = ps._document_words_for_explanation(explanation, quote)
    assert got == (quote if verbatim else explanation)


# ═════════════════════════════════════════════════════════════════════════════
# 10. End to end through the stamper
# ═════════════════════════════════════════════════════════════════════════════
def test_end_to_end_driver_schedule_follows_the_package():
    drivers = [{"name": "Pat Doe", "license_number": "123456789", "dob": "01/01/1980"}]
    box = "Policy_SectionAttached_DriverInformationScheduleIndicator_A"

    def stamp(package):
        facts = {"auto_drivers": drivers, "_package_form_ids": package}
        mapped, _ = ps.map_facts_to_form(facts, SCHEMA, "ACORD_125", raw_text="",
                                         pre_filled_gpt={"filled_values": {}})
        return mapped.get(box)

    assert not stamp(["ACORD_125"])
    assert stamp(["ACORD_125", "ACORD_127"]) in ("Yes", "Y")


# ═════════════════════════════════════════════════════════════════════════════
# 11. The grader: a negation governs what follows it
# ═════════════════════════════════════════════════════════════════════════════
def test_the_grader_scopes_a_negation_to_what_follows_it():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_t_sff", str(BACKEND / "scripts" / "score_form_fill.py"))
    sff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sff)
    same = sff.meaning(
        "The managing member owns Summit Solar Services LLC, a residential solar "
        "installer that is not part of this submission.",
        "Luis Ortega owns Summit Solar Services LLC, a residential solar installer "
        "not part of this submission.")
    assert same[0] == "meaning", same
    for a, b in (("The applicant does not own drones.", "The applicant owns drones."),
                 ("No manufacturing is performed.", "Manufacturing is performed.")):
        assert sff.meaning(a, b)[0] == "no" and "polarity" in sff.meaning(a, b)[1]


# ═════════════════════════════════════════════════════════════════════════════
# 12. Round 2 test 4 (session a7ef6f98) - the live run on the fixed code
# ═════════════════════════════════════════════════════════════════════════════
def test_q1a_follows_the_parent_the_form_prints():
    """Extraction skipped question 1a's entry; the parent block printed anyway."""
    rel = [{"role": "parent", "name": "Front Range Holdings Inc", "percent_owned": "80%"}]
    facts = {"organization_relationships": rel, "disclosure_answers": [
        {"topic": "has_subsidiaries", "answer": "N", "evidence_quote": "No subsidiaries."}]}
    with _ctx():
        assert ps._resolve_disclosure_answer("CommercialPolicy_Question_AAICode_A", facts) == "Y"
        # no parent row: silence stays silence
        assert ps._resolve_disclosure_answer(
            "CommercialPolicy_Question_AAICode_A",
            dict(facts, organization_relationships=[])) is ps._SCHED_SKIP
        # an explicit entry still decides
        facts["disclosure_answers"].append(
            {"topic": "subsidiary_of_another", "answer": "N",
             "evidence_quote": "The applicant is not owned by any other entity."})
        assert ps._resolve_disclosure_answer("CommercialPolicy_Question_AAICode_A", facts) == "N"


def test_item_class_is_the_interests_own_detail():
    facts = {"additional_interests": [{"name": "Peak National Bank"}]}
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_Item_ScheduledItemClassCode_A", facts) is None
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_Item_ScheduledItemClassCode_A",
        {"additional_interests": [{"name": "X", "item_class": "Contractors Equipment"}]}) \
        == "Contractors Equipment"


def test_an_other_box_restating_a_ticked_option_is_cleared():
    base = {"CommercialPolicy_Question_AACCode_A": "Y",
            "CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A": "Y",
            "CancelNonRenew_OtherIndicator_A": "Y"}
    m = dict(base, CancelNonRenew_OtherDescription_A="Agent no longer represents carrier")
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {"_form_id": "ACORD_125"})
    assert not m["CancelNonRenew_OtherDescription_A"] and not m["CancelNonRenew_OtherIndicator_A"]
    # a genuinely other reason survives
    m = dict(base, CancelNonRenew_OtherDescription_A="Carrier withdrew from the Colorado market")
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {"_form_id": "ACORD_125"})
    assert m["CancelNonRenew_OtherDescription_A"] and m["CancelNonRenew_OtherIndicator_A"]
    # the option restated but NOT ticked: since test 5 the tick MOVES to the
    # option (see test_an_other_that_is_word_for_word_a_printed_option_moves_the_tick);
    # a paraphrase that is not the printed label is still left for a human
    m = {"CommercialPolicy_Question_AACCode_A": "Y", "CancelNonRenew_OtherIndicator_A": "Y",
         "CancelNonRenew_OtherDescription_A": "The agent stopped writing for that carrier"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {"_form_id": "ACORD_125"})
    assert m["CancelNonRenew_OtherDescription_A"]
    assert not m.get("CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A")


def test_the_printed_labels_are_read_from_the_template():
    labels = ps._printed_checkbox_labels("ACORD_125")
    assert labels["CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A"] == \
        "AGENT NO LONGER REPRESENTS CARRIER"
    assert labels["CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"] == "SAFETY MANUAL"
    assert ps._printed_checkbox_labels("NO_SUCH_FORM") == {}


@pytest.mark.parametrize("text,method", [
    ("Method of payment EFT (automatic ACH debit)", "EFT"),
    ("PAYMENT METHOD: Credit card", "credit card"),
    ("Method of payment EFT\nMethod of payment: check", None),       # two methods
    ("Pay by EFT whenever possible.", None),                        # not labelled
])
def test_payment_method_is_read_where_the_document_labels_it(text, method):
    mf = {}
    es._backfill_payment_method(mf, text)
    got = (mf.get("payment_method") or {}).get("value")
    assert got == method
    mf = {"payment_method": "wire transfer"}
    es._backfill_payment_method(mf, "Method of payment EFT")
    assert mf["payment_method"] == "wire transfer"                  # never overwrites


def test_prior_rows_the_index_verified_are_restored():
    sec = "PRIOR-TERM DECLARATIONS SUMMARIES (INCUMBENT AND PRIOR CARRIERS)"
    mf = {"prior_coverage_by_line": [{"line": "General Liability", "policy_no": "GL-104471"}],
          "dec_page_entries": [
              {"label": "General Liability", "section": sec,
               "value": "Timberline Mutual Insurance Company GL-091233 $16,900 10/01/2023 10/01/2024"},
              {"label": "General Liability", "section": sec,           # already held
               "value": "Timberline Mutual Insurance Company GL-104471 $17,600 10/01/2024 10/01/2025"},
              {"label": "POLICY YEAR 2023 TERM", "section": sec,       # not a line
               "value": "10/01/2023 - 10/01/2024"},
              {"label": "General Liability", "section": "GL DECLARATIONS - CURRENT POLICY",
               "value": "Timberline Mutual Insurance Company GL-123456 $18,450 10/01/2025 10/01/2026"},
          ]}
    added = es._backfill_prior_coverage_from_entries(mf)
    assert [r["policy_no"] for r in added] == ["GL-091233"]
    row = mf["prior_coverage_by_line"][-1]
    assert (row["carrier"], row["premium"], row["effective"], row["expiration"]) == (
        "Timberline Mutual Insurance Company", "$16,900", "10/01/2023", "10/01/2024")


def test_a_second_guard_pass_keeps_three_companies_in_one_building():
    m = {"NamedInsured_MailingAddress_LineOne_A": "8000 Commerce Way",
         "NamedInsured_MailingAddress_LineTwo_A": "Suite 120",
         "NamedInsured_MailingAddress_LineOne_B": "8000 Commerce Way",
         "NamedInsured_MailingAddress_LineTwo_B": "Suite 130"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {})
        ps._enforce_post_fill_guards(m, SCHEMA, {})
    assert m["NamedInsured_MailingAddress_LineOne_B"] == "8000 Commerce Way"
    # the same street and NO unit is still a duplicate
    m = {"NamedInsured_MailingAddress_LineOne_A": "8000 Commerce Way",
         "NamedInsured_MailingAddress_LineOne_B": "8000 Commerce Way"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {})
    assert not m["NamedInsured_MailingAddress_LineOne_B"]


@pytest.mark.parametrize("value,is_person", [
    ("Denver Branch", False), ("Summit Commercial Insurance", False),
    ("Erin Royal", True), ("Dana Whitfield", True)])
def test_an_organisation_is_not_a_person(value, is_person):
    assert ps._looks_like_person_name(value) is is_person


def test_program_falls_back_to_the_submission_itself():
    facts = _entries(("Carrier", "Granite Arch Casualty Company", _ACK, "carrier"),
                     ("Program", "Contractors Select Program",
                      "SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION", "policy"),
                     ("Program", "Some Other Program", "GL DECLARATIONS - CURRENT POLICY", "policy"))
    assert ps._receiving_section_detail("Insurer_ProductDescription_A", facts) == \
        "Contractors Select Program"


# ═════════════════════════════════════════════════════════════════════════════
# 13. Round 2 test 5 (session b63c3e25) and extraction v23
# ═════════════════════════════════════════════════════════════════════════════
def test_v23_asks_for_what_the_form_needs():
    for key in ("submission_carrier_name", "submission_carrier_naic",
                "submission_program_name", "submission_program_code",
                "submission_underwriter", "submission_underwriter_office",
                "nonrenewal_reasons", "secondary_phone_kind",
                "item_building_number", "item_class"):
        assert f'"{key}"' in es._EXTRACT_SCHEMA, key
    assert '"Other: <the element as the document prints it>"' in es._EXTRACT_SCHEMA
    assert es.PROMPT_VERSION == es.SCHEMA_VERSION == "v25"          # v23, v24, v25 the same day
    assert "nonrenewal_reasons" in es._LIST_FIELDS and "nonrenewal_reasons" in es._LONG_DOC_LIST_KEYS


def test_the_addressee_fact_answers_when_the_documents_name_no_other():
    # (Before test 6 this asserted the fact OUTRANKS a submission section that
    # names another carrier. Test 6 showed the fact can be the incumbent: two
    # witnesses naming two carriers is now no answer - see
    # test_the_fact_and_the_documents_must_agree.)
    facts = _entries(("Carrier", "Timberline Mutual", "GL DECLARATIONS - CURRENT POLICY", "carrier"))
    facts.update({"submission_carrier_name": {"value": "Granite Arch Casualty Company",
                                              "verified_in_text": True},
                  "submission_carrier_naic": "21334",
                  "submission_underwriter": "Dana Whitfield"})
    assert ps._receiving_carrier_from_entries(facts) == {
        "name": "Granite Arch Casualty Company", "naic": "21334"}
    assert ps._receiving_section_detail("Insurer_Underwriter_FullName_A", facts) == "Dana Whitfield"
    # a value the merge could not find in the documents is not an addressee
    facts["submission_carrier_name"]["verified_in_text"] = False
    assert ps._receiving_carrier_from_entries(facts) is None     # and a dec page is no addressee


def test_the_heading_names_the_carrier_when_the_index_lost_its_line():
    """Test 5: NAIC, program code and underwriter recorded; "Carrier" not."""
    facts = _entries(("NAIC", "21334", _ACK, "carrier"),
                     ("Underwriter", "Dana Whitfield", _ACK, "carrier"))
    assert ps._receiving_carrier_from_entries(facts) == {
        "name": "Granite Arch Casualty Company", "naic": "21334"}
    # a heading with no company, or a declarations heading, names nobody
    assert ps._company_in_heading("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION") is None
    assert ps._receiving_carrier_from_entries(_entries(
        ("NAIC", "27413", "TIMBERLINE MUTUAL INSURANCE COMPANY - DECLARATIONS", "carrier"))) is None


def test_page_one_marks_the_incumbent_when_the_addressee_differs():
    lines = [{"line": "General Liability", "carrier": "Timberline Mutual", "policy_number": "GL-1"}]
    mf = {"carrier_name": "Timberline Mutual", "is_renewal": "Y", "coverage_lines": lines,
          "submission_carrier_name": "Granite Arch Casualty Company"}
    es._mark_page_one_current_policy(mf, [])
    assert mf.get("carrier_is_current_policy") is True


def test_question_5_reasons_tick_their_own_boxes():
    facts = {"nonrenewal_reasons": ["Agent no longer represents carrier", "Underwriting",
                                    "Other: carrier withdrew from Colorado"]}
    got = {f: ps._resolve_nonrenewal_reason(f"CancelNonRenew_{f}_A", facts) for f in (
        "AgentNoLongerWritesForInsurerIndicator", "UnderwritingIndicator",
        "NonPaymentIndicator", "OtherIndicator", "OtherDescription")}
    assert got == {"AgentNoLongerWritesForInsurerIndicator": "Y", "UnderwritingIndicator": "Y",
                   "NonPaymentIndicator": None, "OtherIndicator": "Y",
                   "OtherDescription": "carrier withdrew from Colorado"}
    # no list, or an empty one, is silence
    assert ps._resolve_nonrenewal_reason("CancelNonRenew_UnderwritingIndicator_A", {}) is ps._SCHED_SKIP
    assert ps._resolve_nonrenewal_reason(
        "CancelNonRenew_UnderwritingIndicator_A", {"nonrenewal_reasons": []}) is ps._SCHED_SKIP


def test_an_other_that_is_word_for_word_a_printed_option_moves_the_tick():
    m = {"CommercialPolicy_Question_AACCode_A": "Y", "CancelNonRenew_UnderwritingIndicator_A": "Y",
         "CancelNonRenew_OtherIndicator_A": "Y",
         "CancelNonRenew_OtherDescription_A": "Agent no longer represents carrier"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {"_form_id": "ACORD_125"})
    assert m["CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A"] == "Y"
    assert not m["CancelNonRenew_OtherIndicator_A"] and not m["CancelNonRenew_OtherDescription_A"]
    # a longer reason is not a label: it stays in OTHER
    m = {"CommercialPolicy_Question_AACCode_A": "Y", "CancelNonRenew_OtherIndicator_A": "Y",
         "CancelNonRenew_OtherDescription_A": "Agent no longer represents carrier in Colorado"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {"_form_id": "ACORD_125"})
    assert m["CancelNonRenew_OtherDescription_A"]


def test_the_safety_other_element_prints_from_the_list():
    facts = {"safety_program_elements": ["Safety Manual", "Other: Daily job hazard analysis"]}
    assert ps._resolve_safety_program_element(
        "CommercialPolicy_FormalSafetyProgram_OtherIndicator_B", facts) == "Y"
    assert ps._resolve_safety_program_element(
        "CommercialPolicy_FormalSafetyProgram_OtherDescription_B", facts) == "Daily job hazard analysis"
    assert ps._resolve_safety_program_element(
        "CommercialPolicy_FormalSafetyProgram_OtherIndicator_B",
        {"safety_program_elements": ["Safety Manual"]}) is ps._SCHED_SKIP


def test_the_secondary_phone_kind_and_the_interest_building():
    facts = {"applicant_contacts": [{"name": "John Smith", "phone": "303-555-0188",
                                     "phone_kind": "Cell", "secondary_phone": "303-555-0175",
                                     "secondary_phone_kind": "Business"}]}
    assert ps._resolve_contact_detail(
        "NamedInsured_Contact_SecondaryBusinessPhoneIndicator_A", facts) == "Y"
    assert ps._resolve_contact_detail(
        "NamedInsured_Contact_SecondaryCellPhoneIndicator_A", facts) is None
    facts["applicant_contacts"][0]["secondary_phone"] = None      # no number, no kind
    assert ps._resolve_contact_detail(
        "NamedInsured_Contact_SecondaryBusinessPhoneIndicator_A", facts) is None
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_Item_BuildingProducerIdentifier_A",
        {"additional_interests": [{"name": "Peak National Bank", "item_building_number": "1"}]}) == "1"
    assert not ps._is_nonfillable_field("AdditionalInterest_Item_BuildingProducerIdentifier_A")


@pytest.mark.parametrize("text,marked", [
    ("REMARKS FOR THE APPLICATION\nPlease quote General Liability at $1,000,000.", True),
    ("REMARKS\nThe applicant is under common control with Harbor Line.", True),
    ("DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES (ACORD 101, Additional Remarks "
     "Schedule, may be attached)\nNote: Reduced Umbrella Limit.", False),       # a certificate
    ("C-2427 Western Sheet Metal 04/01/2026 CERT\nCertificates are evidence of insurance only.", False),
])
def test_the_remarks_box_takes_only_the_submissions_remark(text, marked):
    remark = text.split("\n", 1)[1]
    mf = {"additional_remarks_text": remark}
    assert es._mark_submission_remark(mf, "Cover letter.\n" + text) is marked


def test_the_general_remarks_box_is_wired():
    """Registered in _AUTHORITATIVE_BLANK_RESOLVERS since August and never
    called: the box printed blank on every run."""
    facts = {"additional_remarks_text": "Please quote General Liability at $1,000,000.",
             "remarks_under_remarks_heading": True}
    with _ctx():
        assert ps._deterministic_map("CommercialPolicy_RemarkText_A", facts) == \
            "Please quote General Liability at $1,000,000."
        facts["remarks_under_remarks_heading"] = False
        assert not ps._deterministic_map("CommercialPolicy_RemarkText_A", facts)


def test_a_list_of_other_rows_is_never_rewritten():
    """ACORD 131 prints FOUR other-coverage rows, each with its own limits: a
    leftover line fills one (16 Aug) and must not be moved to the printed
    LIQUOR LIABILITY box, which would orphan that row's policy details."""
    schema = json.loads((BACKEND / "forms_schemas" / "ACORD_131_schema.json").read_text())
    m = {"UnderlyingCoverage_Coverage_OtherIndicator_A": "Y",
         "UnderlyingCoverage_Coverage_OtherDescription_A": "Liquor Liability"}
    with ps._schema_context(schema):
        ps._enforce_post_fill_guards(m, schema, {"_form_id": "ACORD_131"})
    assert m["UnderlyingCoverage_Coverage_OtherDescription_A"] == "Liquor Liability"
    assert not m.get("UnderlyingCoverage_Coverage_LiquorLiabilityIndicator_A")


# ═════════════════════════════════════════════════════════════════════════════
# 14. Round 2 test 6 (session c3059a2d) - the first live v23 run, and v24
# ═════════════════════════════════════════════════════════════════════════════
def test_an_addressee_that_is_the_incumbent_is_rejected_and_the_letter_read():
    """Test 6: submission_carrier_name = the incumbent, with the addressee's
    NAIC - page one printed one company's name beside another's number."""
    text = ("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION\n"
            "TO: Granite Arch Casualty Company\nATTN: Dana Whitfield\n"
            "Granite Arch Casualty Company NAIC 21334 1200 17th Street\n"
            "Company Timberline Mutual Insurance Company NAIC 27413\n")
    mf = {"carrier_name": "Timberline Mutual Insurance Company", "carrier_is_current_policy": True,
          "submission_carrier_name": {"value": "Timberline Mutual Insurance Company", "source": "ai"},
          "submission_carrier_naic": {"value": "21334", "source": "ai"}}
    es._validate_submission_carrier(mf, text)
    assert es._fv(mf, "submission_carrier_name") == "Granite Arch Casualty Company"
    assert es._fv(mf, "submission_carrier_naic") == "21334"


def test_a_naic_is_kept_only_beside_its_own_name():
    text = "TO: Granite Arch Casualty Company\nquote request\nOther Co NAIC 99999\n"
    mf = {"submission_carrier_name": "Granite Arch Casualty Company",
          "submission_carrier_naic": "99999"}
    es._validate_submission_carrier(mf, text + "x" * 400 + "\nGranite Arch Casualty Company\n")
    assert "submission_carrier_naic" not in mf


def test_a_letter_to_line_needs_a_company_and_a_submission():
    assert es._addressee_from_text("TO: Granite Arch Casualty Company\nPlease quote.")["name"] == \
        "Granite Arch Casualty Company"
    assert es._addressee_from_text("TO: Dana Whitfield\nPlease quote.") is None          # a person
    assert es._addressee_from_text("TO: Granite Arch Casualty Company\nHappy holidays.") is None
    assert es._addressee_from_text("TO: Acme Insurance Company\nquote\nTO: Beta Mutual\nquote") is None


def test_the_fact_and_the_documents_must_agree():
    facts = _entries(("TO", "Granite Arch Casualty Company", "", "carrier"))
    facts["submission_carrier_name"] = "Summit Specialty Insurance Company"
    assert ps._receiving_carrier_from_entries(facts) is None            # two addressees
    facts["submission_carrier_name"] = "Granite Arch Casualty Company"
    assert ps._receiving_carrier_from_entries(facts)["name"] == "Granite Arch Casualty Company"
    # a stored incumbent fact is refused at stamp time too
    stored = _entries(("TO", "Granite Arch Casualty Company", "", "carrier"))
    stored.update({"carrier_name": "Timberline Mutual", "carrier_is_current_policy": True,
                   "submission_carrier_name": "Timberline Mutual"})
    assert ps._receiving_carrier_from_entries(stored)["name"] == "Granite Arch Casualty Company"


def test_question_4_reads_every_yes_row_and_only_printed_numbers():
    rows = [{"topic": "other_insurance_with_carrier", "answer": "Y",
             "evidence_quote": "Any other insurance with this company? X",
             "explanation": "Workers Compensation WC-GA-448120; Commercial Inland Marine IM-GA-220915; Auto ZZ-99999"},
            {"topic": "other_insurance_with_carrier", "answer": "Y",
             "evidence_quote": "The old Timberline paperwork still shows the old audit."}]
    text = "Existing policies with us: Workers Compensation WC-GA-448120; Commercial Inland Marine IM-GA-220915"
    mf = {"disclosure_answers": rows}
    got = es._derive_other_insurance_policies(mf, text)
    assert [r["policy_number"] for r in got] == ["WC-GA-448120", "IM-GA-220915"]    # ZZ-99999 not printed
    assert ps._other_policy_rows(dict(mf, coverage_lines=_CURRENT)) == got
    mf = {"disclosure_answers": [{"topic": "other_insurance_with_carrier", "answer": "N"}]}
    assert es._derive_other_insurance_policies(mf, text) == [] and mf["other_insurance_policies"] == []


def test_the_inferred_list_is_only_the_addressees_policies():
    facts = _entries(("TO", "Granite Arch Casualty Company", "", "carrier"))
    facts.update({"coverage_lines": [
        {"line": "General Liability", "carrier": "Timberline Mutual", "policy_number": "GL-123456"},
        {"line": "Workers Compensation", "carrier": "Granite Arch Casualty Company",
         "policy_number": "WC-GA-448120"}]})
    assert [r["policy_number"] for r in ps._other_policy_rows(facts)] == ["WC-GA-448120"]
    # no addressee: the owner's 24 Sep list, unchanged
    assert len(ps._other_policy_rows({"coverage_lines": facts["coverage_lines"]})) == 2


def test_condition_corrected_ticks_when_the_correction_is_described():
    facts = {"nonrenewal_reasons": ["Agent no longer represents carrier", "Underwriting"],
             "disclosure_answers": [{"topic": "coverage_declined_cancelled_nonrenewed", "answer": "Y",
                                     "resolution": "A written fleet safety program was adopted."}]}
    assert ps._resolve_nonrenewal_reason(
        "CancelNonRenew_UnderwritingConditionCorrectedIndicator_A", facts) == "Y"
    facts["disclosure_answers"][0]["resolution"] = None
    assert ps._resolve_nonrenewal_reason(
        "CancelNonRenew_UnderwritingConditionCorrectedIndicator_A", facts) is None


def test_the_labelled_explanation_is_the_explanation():
    text = ("9. Foreclosure, repossession or bankruptcy in the last five years?\nANSWER: Y -\n"
            "Yes. A leased compact excavator was repossessed in April 2022.\nOCCUR DATE: 04/18/2022\n"
            "EXPLANATION: A leased compact excavator was repossessed by the lessor after a billing\n"
            "dispute.\nRESOLUTION: Dispute settled.\n10. Any judgement or lien?\nANSWER: N\n"
            "EXPLANATION: this belongs to question 10 and must never move up.\n")
    rows = [{"topic": "foreclosure_repossession_bankruptcy", "answer": "Y",
             "explanation": "A leased compact excavator was repossessed in April 2022.",
             "evidence_quote": "Yes. A leased compact excavator was repossessed in April 2022."}]
    es._prefer_labelled_explanations({"disclosure_answers": rows}, text)
    assert rows[0]["explanation"] == \
        "A leased compact excavator was repossessed by the lessor after a billing dispute."
    # a block with no labelled explanation keeps its own words; the next
    # question's label is never borrowed
    rows = [{"topic": "judgement_or_lien", "answer": "Y", "explanation": "Yes. Lien released.",
             "evidence_quote": "Yes. A leased compact excavator was repossessed in April 2022."}]
    text2 = text.replace("EXPLANATION: A leased", "NOTE: A leased")
    es._prefer_labelled_explanations({"disclosure_answers": rows}, text2)
    assert rows[0]["explanation"] == "Yes. Lien released."


@pytest.mark.parametrize("given,printed", [
    ("Yes. Two fire extinguishers carry expired tags.", "Two fire extinguishers carry expired tags."),
    ("No - nothing to report here.", "nothing to report here."),
    ("Yesterday the lien was released.", "Yesterday the lien was released."),
    ("Yes.", "Yes."),
])
def test_an_explanation_never_starts_with_the_bare_answer(given, printed):
    assert ps._without_answer_word(given) == printed


def test_a_premises_unit_is_copied_back_only_when_it_is_the_only_one():
    mf = {"property_locations": [{"address": "4750 Centennial Blvd, Colorado Springs, CO 80919"},
                                 {"address": "8000 Commerce Way, Denver, CO 80216"}]}
    text = ("4750 Centennial Blvd Suite 210 Colorado Springs\n"
            "8000 Commerce Way, Suite 120\n8000 Commerce Way, Suite 130\n")
    es._repair_location_units(mf, text)
    assert mf["property_locations"][0]["address"] == \
        "4750 Centennial Blvd, Suite 210, Colorado Springs, CO 80919"
    assert mf["property_locations"][1]["address"] == "8000 Commerce Way, Denver, CO 80216"


def test_a_loss_description_does_not_repeat_its_line():
    m = {"LossHistory_LineOfBusiness_A": "General Liability",
         "LossHistory_OccurrenceDescription_A": "General Liability Customer ceiling damaged by water",
         "LossHistory_LineOfBusiness_B": "Property",
         "LossHistory_OccurrenceDescription_B": "Property damage to a rented crane"}
    with _ctx():
        ps._enforce_post_fill_guards(m, SCHEMA, {})
    assert m["LossHistory_OccurrenceDescription_A"] == "Customer ceiling damaged by water"
    assert m["LossHistory_OccurrenceDescription_B"] == "damage to a rented crane"


def test_v24_wording():
    assert es.PROMPT_VERSION == es.SCHEMA_VERSION == "v25"          # v24's wording kept in v25
    assert "copy THAT text" in es._EXTRACT_SCHEMA
    assert "that carrier is NOT the addressee" in es._EXTRACT_SCHEMA
    assert "narrative sentence, not a table cell" not in es._EXTRACT_SCHEMA


def test_a_word_after_suite_is_not_a_unit():
    """FR125 v1's lease: "8000 Commerce Way, Suite occupied 5,000 SF of 15,000
    SF" - "Suite" the noun. It printed "Ste Occupied" on the premises row."""
    mf = {"property_locations": [{"address": "8000 Commerce Way, Denver, CO 80216"}]}
    assert es._repair_location_units(
        mf, "Premises: 8000 Commerce Way, Suite occupied 5,000 SF of 15,000 SF") == []
    assert ps._address_unit_numbers("Suite occupied") == frozenset()
    assert ps._TRAILING_UNIT_SEGMENT_RE.match("5 Main St, Suite occupied") is None
    assert ps._address_unit_numbers("Suite B") == frozenset({"b"})


# ═════════════════════════════════════════════════════════════════════════════
# 15. Round 2 test 7 (session 5af86855) - page one's billing and audit
# ═════════════════════════════════════════════════════════════════════════════
_T7_TEXT = (
    "BILLING AND PAYMENT\nBilling preference Direct bill\nMethod of payment EFT\n"
    "GRANITE ARCH CASUALTY COMPANY - ACKNOWLEDGEMENT OF SUBMISSION\n"
    "Premium audit ........ Annual (audit period code A)\n"
    "COMMERCIAL GENERAL LIABILITY DECLARATIONS - CURRENT POLICY (INCUMBENT)\n"
    "POLICY NO GL-123456\nBilling Agency bill - Quarterly installments\nAudit Semi-annual\n"
    "E-MAIL CORRESPONDENCE - SUBMISSION FILE\n"
    "The old Timberline paperwork still shows the old\naudit and quarterly agency billing.\n"
    "Direct bill, monthly EFT please.\n")


def test_page_one_billing_and_audit_are_the_submissions():
    """Test 7 took both from the sentence about the OLD paperwork."""
    mf = {"billing_plan": {"value": "quarterly agency billing", "source": "ai"},
          "audit_period": {"value": "old audit", "source": "ai"}}
    es._prefer_submission_terms(mf, _T7_TEXT)
    assert es._fv(mf, "billing_plan") == "DIRECT BILL"
    assert es._fv(mf, "audit_period") == "Annual"


def test_the_incumbents_terms_alone_change_nothing():
    """A declarations-only package (Orbin): no submission statement, the
    extraction stands - even when it is the incumbent's own billing."""
    text = ("COMMERCIAL GENERAL LIABILITY DECLARATIONS - CURRENT POLICY\n"
            "Billing Agency bill\nAudit Period: Semi-annual\n")
    mf = {"billing_plan": "AGENCY BILL", "audit_period": "Semi-annual"}
    assert es._prefer_submission_terms(mf, text) == []
    assert mf == {"billing_plan": "AGENCY BILL", "audit_period": "Semi-annual"}


def test_disagreeing_submission_statements_decide_nothing():
    text = "COVER LETTER TO THE MARKET\nDirect bill please.\nAPPLICATION FOR INSURANCE\nAgency bill."
    mf = {"billing_plan": "AGENCY BILL"}
    es._prefer_submission_terms(mf, text)
    assert mf["billing_plan"] == "AGENCY BILL"


def test_a_persons_billing_is_never_replaced_and_a_non_period_is_dropped():
    mf = {"billing_plan": {"value": "AGENCY BILL", "source": "producer"},
          "audit_period": {"value": "old audit", "source": "ai"}}
    es._prefer_submission_terms(mf, "COVER NOTE FOR THE UNDERWRITER\nPlease note: Direct bill.\n")
    assert es._fv(mf, "billing_plan") == "AGENCY BILL"
    assert "audit_period" not in mf


def test_v25_defines_billing_and_audit():
    assert es.PROMPT_VERSION == es.SCHEMA_VERSION == "v25"
    assert "the billing plan THIS submission asks for" in es._EXTRACT_SCHEMA
    assert "the premium audit period THIS submission states" in es._EXTRACT_SCHEMA


def test_the_audit_accepts_a_relationship_as_question_1as_statement():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_t_audit_rules", str(BACKEND / "scripts" / "audit_125_rules.py"))
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    stamped = {"CommercialPolicy_Question_AAICode_A": "Y",
               "BusinessInformation_ParentOrganizationName_A": "Front Range Holdings Inc"}
    facts = {"disclosure_answers": [{"topic": "has_subsidiaries", "answer": "N"}]}
    res = {r["id"]: r for r in audit.audit(stamped, facts, "", {}, ["ACORD_125"])}
    assert res["C16"]["status"] != "FAIL"
    stamped.pop("BusinessInformation_ParentOrganizationName_A")
    res = {r["id"]: r for r in audit.audit(stamped, facts, "", {}, ["ACORD_125"])}
    assert res["C16"]["status"] == "FAIL"


# ═════════════════════════════════════════════════════════════════════════════
# 16. Round 2 test 8 (session e3cebd88) - 312 of 312 with 3 made up
# ═════════════════════════════════════════════════════════════════════════════
_Q4_TEXT = ("Existing policies with us: Workers Compensation WC-GA-448120; Commercial Inland Marine "
            "IM-GA-220915\nGeneral Liability Timberline Mutual Insurance Company GL-123456 $18,450\n"
            "Business Auto Timberline Mutual Insurance Company BA-456789 $14,200\n")


def test_question_4_keeps_only_the_addressees_policies():
    """Test 8: a second YES row, written from the incumbent's pages, listed
    Timberline's policies - numbers the document does print."""
    mf = {"submission_carrier_name": "Granite Arch Casualty Company",
          "coverage_lines": [{"line": "General Liability", "carrier": "Timberline Mutual Insurance Company",
                              "policy_number": "GL-123456"}],
          "disclosure_answers": [
              {"topic": "other_insurance_with_carrier", "answer": "Y",
               "explanation": "Workers Compensation WC-GA-448120; Commercial Inland Marine IM-GA-220915"},
              {"topic": "other_insurance_with_carrier", "answer": "Y",
               "explanation": "General Liability Timberline Mutual Insurance Company GL-123456; "
                              "Business Auto Timberline Mutual Insurance Company BA-456789"}]}
    got = es._derive_other_insurance_policies(mf, _Q4_TEXT)
    assert [(r["line"], r["policy_number"]) for r in got] == [
        ("Workers Compensation", "WC-GA-448120"), ("Commercial Inland Marine", "IM-GA-220915")]


def test_question_4_without_an_addressee_is_unchanged():
    mf = {"disclosure_answers": [{"topic": "other_insurance_with_carrier", "answer": "Y",
                                  "explanation": "General Liability GL-123456"}]}
    assert [r["policy_number"] for r in es._derive_other_insurance_policies(mf, _Q4_TEXT)] == ["GL-123456"]


def test_disagreeing_answers_the_document_corroborates_the_yes():
    """Test 8: question 5 as YES (dated non-renewals) and as NO - quoting a
    sentence about old paperwork. The form printed YES only by row order."""
    rows = [{"topic": "coverage_declined_cancelled_nonrenewed", "answer": "N",
             "evidence_quote": "The old Timberline paperwork still shows the old audit."},
            {"topic": "coverage_declined_cancelled_nonrenewed", "answer": "Y",
             "occurrence_date": "10/01/2023", "evidence_quote": "Alpine States non-renewed every line."}]
    mf = {"disclosure_answers": list(rows)}
    assert es._reconcile_disclosure_conflicts(mf) == ["coverage_declined_cancelled_nonrenewed=Y"]
    assert [r["answer"] for r in mf["disclosure_answers"]] == ["Y"]


def test_uncorroborated_disagreement_leaves_the_question_unanswered():
    mf = {"disclosure_answers": [
        {"topic": "foreign_operations", "answer": "Y", "evidence_quote": "We import some parts."},
        {"topic": "foreign_operations", "answer": "N", "evidence_quote": "No foreign operations."},
        {"topic": "fraud_arson_conviction", "answer": "N", "evidence_quote": "No convictions."}]}
    assert es._reconcile_disclosure_conflicts(mf) == ["foreign_operations=unanswered"]
    assert [r["topic"] for r in mf["disclosure_answers"]] == ["fraud_arson_conviction"]


def test_a_question_4_yes_is_corroborated_by_its_own_policy_number():
    mf = {"disclosure_answers": [
        {"topic": "other_insurance_with_carrier", "answer": "N", "evidence_quote": "None with us."},
        {"topic": "other_insurance_with_carrier", "answer": "Y",
         "evidence_quote": "Workers Compensation WC-GA-448120"}]}
    assert es._reconcile_disclosure_conflicts(mf) == ["other_insurance_with_carrier=Y"]
