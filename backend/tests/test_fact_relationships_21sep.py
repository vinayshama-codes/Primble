"""Relationship preservation, checked WITHOUT an answer key.

The live defects this module exists for were all REAL values, correctly shaped
and literally present in the document - attached to the wrong party. Nothing in
the pipeline could see them, because every check asked "is this value right?"
and none asked "is it right FOR THIS ENTITY?".

Adversarial cases first: a checker that cries wolf on an ordinary corporate
group is worse than no checker, because nobody reads its output twice.
"""
from __future__ import annotations

import pytest

from services.fact_relationships import (
    ERROR, WARN, check_fact_relationships, summarise,
)


def _codes(findings):
    return {f["code"] for f in findings}


# ═══════════════════════════════════════════════════════════════════════════
# ADVERSARIAL: ordinary packages that must stay SILENT
# ═══════════════════════════════════════════════════════════════════════════

def test_an_ordinary_single_entity_package_is_silent():
    assert check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "fein": "93-2841760", "applicant_website": "www.meridianiw.com",
    }) == []


def test_a_group_sharing_one_domain_is_silent():
    """ADVERSARIAL. A holding company genuinely runs every subsidiary off the
    operating company's domain. Sharing alone must never fire - the check only
    speaks when the domain names some OTHER party BETTER."""
    assert _codes(check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "additional_named_insureds": ["Meridian Ironworks Property Holdings, LLC"],
        "applicant_website": "www.meridianiw.com",
        "named_insured_details": [
            {"name": "Meridian Ironworks Property Holdings, LLC",
             "website": "www.meridianiw.com"}],
    })) == set()


def test_affiliates_sharing_a_switchboard_is_silent():
    """ADVERSARIAL. Two companies at one address share a phone every day of the
    week. Only a legally unique identifier - the FEIN - is treated as proof of
    a mixed row."""
    assert _codes(check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "fein": "93-2841760",
        "additional_named_insureds": ["Meridian Ironworks Property Holdings, LLC"],
        "named_insured_details": [
            {"name": "Meridian Ironworks Property Holdings, LLC",
             "fein": "88-2207734", "phone": "(503) 555-0162"}],
    })) == set()


def test_no_facts_at_all_is_silent():
    assert check_fact_relationships({}) == []
    assert check_fact_relationships(None) == []


def test_a_legitimate_yes_with_detail_is_silent():
    assert _codes(check_fact_relationships({
        "disclosure_answers": [{"topic": "has_subsidiaries", "answer": "Y",
                                "evidence_quote": "wholly owns Cedar Bluff"}],
        "organization_relationships": [{"role": "subsidiary", "name": "Cedar Bluff"}],
    })) == set()


# ═══════════════════════════════════════════════════════════════════════════
# The live defects
# ═══════════════════════════════════════════════════════════════════════════

def test_the_live_website_misattribution_is_caught_with_no_key():
    """21 Sep, ACORD 125: `applicant_website` held the SECOND insured's site and
    the form printed it on the FIRST insured's row. The value was real, the
    spelling was right, the box was right. Only the OWNER was wrong."""
    f = check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc.",
                                      "Tualatin Valley Mechanical Services, LLC"],
        "applicant_website": "www.cedarbluffsteel.com",
    })
    assert "IDENTITY_FILED_UNDER_THE_WRONG_PARTY" in _codes(f)
    assert any("Cedar Bluff" in x["message"] for x in f)


def test_a_concatenated_domain_still_matches_its_owner():
    """THE BUG IN THE FIRST VERSION OF THIS CHECK. A real domain welds the name
    together - "cedarbluffsteel" - so a token-set intersection against
    {cedar, bluff, steel} is EMPTY and the check silently never fires. It did
    exactly that on its first run against the defect it was written for."""
    from services.fact_relationships import _domain_text, _domain_affinity
    assert _domain_text("www.cedarbluffsteel.com") == "cedarbluffsteel"
    assert _domain_affinity("cedarbluffsteel", "Cedar Bluff Steel Fabricators, Inc.") == 3
    assert _domain_affinity("cedarbluffsteel", "Meridian Ironworks & Mechanical, LLC") == 0


def test_two_parties_cannot_hold_one_fein():
    f = check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "fein": "93-2841760",
        "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."],
        "named_insured_details": [{"name": "Cedar Bluff Steel Fabricators, Inc.",
                                   "fein": "93-2841760"}],
    })
    assert "SHARED_FEIN" in _codes(f)
    assert [x for x in f if x["code"] == "SHARED_FEIN"][0]["severity"] == ERROR


def test_a_detail_row_for_a_party_nobody_names_is_caught():
    f = check_fact_relationships({
        "applicant_name": "Meridian Ironworks & Mechanical, LLC",
        "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."],
        "named_insured_details": [
            {"name": "Cedar Bluff Steel Fabricators, Inc.", "fein": "26-0459318"},
            {"name": "Ironbridge Capital Leasing Corporation", "fein": "47-3318805"}],
    })
    assert "ORPHAN_DETAIL_ROW" in _codes(f)


def test_an_answer_that_contradicts_its_own_detail_is_caught():
    f = check_fact_relationships({
        "disclosure_answers": [{"topic": "has_subsidiaries", "answer": "N"}],
        "organization_relationships": [{"role": "subsidiary", "name": "Cedar Bluff"}],
    })
    assert "DISCLOSURE_CONTRADICTS_DETAIL" in _codes(f)


def test_a_topic_no_box_can_receive_is_caught():
    f = check_fact_relationships({
        "disclosure_answers": [{"topic": "fleet_size", "answer": "Y"}]})
    assert "UNKNOWN_DISCLOSURE_TOPIC" in _codes(f)


def test_a_quote_the_document_does_not_contain_is_caught():
    facts = {"disclosure_answers": [
        {"topic": "business_in_trust", "answer": "N",
         "evidence_quote": "The business has never been placed into any trust."}]}
    assert "EVIDENCE_QUOTE_NOT_IN_DOCUMENT" in _codes(
        check_fact_relationships(facts, raw_text="An unrelated declarations page."))
    # ...and it is SILENT when the quote is really there
    assert "EVIDENCE_QUOTE_NOT_IN_DOCUMENT" not in _codes(check_fact_relationships(
        facts, raw_text="... The business has never been placed into any trust. ..."))


def test_no_raw_text_means_no_opinion_about_quotes():
    """ADVERSARIAL. Absence of the document is not evidence against the quote."""
    assert "EVIDENCE_QUOTE_NOT_IN_DOCUMENT" not in _codes(check_fact_relationships(
        {"disclosure_answers": [{"topic": "business_in_trust", "answer": "N",
                                 "evidence_quote": "something not checkable"}]}))


def test_the_seven_digit_account_number_in_a_fein_column_is_caught():
    """The kit's own SHAPE trap, and the same signature as a value copied out
    of the neighbouring box."""
    assert "COLUMN_SHAPE" in _codes(check_fact_relationships({
        "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."],
        "named_insured_details": [{"name": "Cedar Bluff Steel Fabricators, Inc.",
                                   "fein": "4471100"}]}))


# ═══════════════════════════════════════════════════════════════════════════
# Contract
# ═══════════════════════════════════════════════════════════════════════════

def test_it_never_raises_on_hostile_input():
    """A diagnostic that can break a pipeline is worse than no diagnostic."""
    for junk in ({"named_insured_details": "not a list"},
                 {"named_insured_details": [None, 3, "x"]},
                 {"disclosure_answers": [{"topic": None, "answer": 7}]},
                 {"applicant_name": 42, "applicant_website": ["a"]},
                 {"organization_relationships": {"role": "parent"}},
                 {"safety_program_elements": "Safety Manual"}):
        assert isinstance(check_fact_relationships(junk), list)


def test_it_never_mutates_the_facts_it_is_given():
    facts = {"applicant_name": "A", "named_insured_details": [{"name": "B"}]}
    import copy
    before = copy.deepcopy(facts)
    check_fact_relationships(facts, "text")
    assert facts == before


def test_findings_are_ordered_most_severe_first():
    f = check_fact_relationships({
        "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."],
        "named_insured_details": [{"name": "Ironbridge Capital", "fein": "123"}],
        "safety_program_elements": ["Toolbox Talks"]})
    sevs = [x["severity"] for x in f]
    assert sevs == sorted(sevs, key=lambda s: {ERROR: 0, WARN: 1}.get(s, 2))


def test_summarise_counts_by_severity_and_code():
    s = summarise(check_fact_relationships({
        "disclosure_answers": [{"topic": "nope", "answer": "Y"}]}))
    assert s.get(ERROR) == 1 and s.get("UNKNOWN_DISCLOSURE_TOPIC") == 1
