"""Regression tests for the nine defects graded on run F (the synthetic
TEST_DEC_PAGE_ACORD125 fixture), each replayed with the run's literal values.

J1 prior-grid premium cells blocked by the "Premium" substring
J2 second named insured never stamped
J3 producer suite printed twice (LineOne with suite + parsed LineTwo)
J4 Retail/Office/Service ticked for a general contractor from prose mentions
J5 flammables "Y" justified by a leading-negation sentence
J6 negation sentence title-cased into PARENT COMPANY NAME
J7 a claim date orphaned into the judgment/lien RESOLVE DATE box
J8 the 2nd insured's name over the lender's address in ADDITIONAL INTEREST
J9 county unbound (the last fragment door)
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_125() -> dict:
    with open(os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _map_125(facts: dict, planted: dict, raw_text: str):
    from services.pdf_service import map_facts_to_form
    mapped, _conf = map_facts_to_form(
        facts, _schema_125(), form_id="ACORD_125", raw_text=raw_text,
        pre_filled_gpt={"filled_values": planted, "raw_text_fields": set()},
    )
    return mapped


# ── J1 ───────────────────────────────────────────────────────────────────────

def test_prior_grid_premium_cells_fill_from_the_per_line_fact():
    facts = {"prior_coverage_by_line": [
        {"line": "General Liability", "carrier": "Pinnacle Casualty Company",
         "policy_no": "GL-55110-25", "premium": "$3,950",
         "effective": "09/01/2025", "expiration": "09/01/2026"},
        {"line": "Automobile", "carrier": "Pinnacle Casualty Company",
         "policy_no": "CA-77120-25", "premium": "$2,880",
         "effective": "09/01/2025", "expiration": "09/01/2026"},
    ]}
    mapped = _map_125(facts, {}, "prior policy schedule")
    assert mapped.get("PriorCoverage_GeneralLiability_TotalPremiumAmount_A") == "$3,950"
    assert mapped.get("PriorCoverage_Automobile_TotalPremiumAmount_A") == "$2,880"
    assert mapped.get("PriorCoverage_Property_TotalPremiumAmount_A") is None


# ── J2 ───────────────────────────────────────────────────────────────────────

def test_second_named_insured_stamps_from_the_extraction_fact():
    from services.pdf_service import _resolve_schedule_row, compute_form_gaps
    facts = {
        "applicant_name": "Summit Ridge Builders LLC",
        "additional_named_insureds": ["Summit Ridge Property Holdings LLC"],
    }
    assert _resolve_schedule_row(
        "NamedInsured_FullName_B", facts) == "Summit Ridge Property Holdings LLC"
    mapped, _u, _d = compute_form_gaps("ACORD_125", _schema_125(), facts)
    assert mapped.get("NamedInsured_FullName_B") == "Summit Ridge Property Holdings LLC"
    # Row A stays the primary applicant via the scalar rule.
    assert mapped.get("NamedInsured_FullName_A") == "Summit Ridge Builders LLC"


# ── J3 ───────────────────────────────────────────────────────────────────────

def test_producer_mailing_block_is_owned_by_one_parse():
    from services.pdf_service import compute_form_gaps
    facts = {"producer_address":
             "6400 Fiddlers Green Circle, Suite 210, Greenwood Village, CO 80111"}
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    assert mapped.get("Producer_MailingAddress_LineOne_A") == "6400 Fiddlers Green Circle"
    assert mapped.get("Producer_MailingAddress_LineTwo_A") == "Suite 210"
    assert mapped.get("Producer_MailingAddress_CityName_A") == "Greenwood Village"
    assert mapped.get("Producer_MailingAddress_PostalCode_A") == "80111"
    for f in ("Producer_MailingAddress_LineOne_A", "Producer_MailingAddress_LineTwo_A"):
        assert f not in unmatched


def test_producer_mailing_without_the_fact_keeps_llm_coverage():
    from services.pdf_service import compute_form_gaps
    _m, unmatched, _d = compute_form_gaps("ACORD_125", _schema_125(), {})
    assert "Producer_MailingAddress_LineOne_A" in unmatched


# ── J4 ───────────────────────────────────────────────────────────────────────

def test_a_contractor_does_not_tick_retail_office_service():
    from services.pdf_service import _derive_indicator
    facts = {
        "is_contractor": True,
        "operations_description": ("Commercial general contractor specializing in "
                                   "tenant finish and light commercial renovation "
                                   "of occupied retail and office space."),
    }
    assert _derive_indicator(
        "BusinessInformation_BusinessType_ContractorIndicator_A", facts) == "Yes"
    for t in ("Retail", "Office", "Service"):
        assert _derive_indicator(
            f"BusinessInformation_BusinessType_{t}Indicator_A", facts) == "No", t


def test_a_real_retailer_still_ticks_retail():
    from services.pdf_service import _derive_indicator
    facts = {"is_contractor": False,
             "operations_description": "Retail hardware store"}
    assert _derive_indicator(
        "BusinessInformation_BusinessType_RetailIndicator_A", facts) == "Yes"


# ── J5 ───────────────────────────────────────────────────────────────────────

def _first_gated_question(schema):
    """First gated question WITHOUT a mandatory dependent section.

    CHANGED 2026-08-13: this used to return the first CommercialPolicy question
    outright, which is Q1a "is the applicant a subsidiary of another entity?" -
    a question whose form section demands the parent company's NAME. Under the
    owner's explicit rule ("whenever there is a Y, there should be an
    explanation mandatory") a Yes there no longer survives on a quote alone,
    which is a DIFFERENT contract from the one this file tests (that an
    affirmative quote, versus a negation, keeps a Yes). Picking a question with
    no dependent section keeps this file testing its own claim; the dependent
    rule has its own tests in test_run_20260813d.py.
    """
    from services.pdf_service import (
        is_compliance_question, _question_explanation_pairs,
        _unpaired_question_deps,
    )
    pairs = _question_explanation_pairs(schema)
    deps = _unpaired_question_deps(schema, pairs)
    for f, meta in schema.items():
        if f.startswith("CommercialPolicy_Question_") and f.endswith("Code_A") \
                and is_compliance_question(f, meta) \
                and f not in deps and f not in pairs:
            return f
    raise AssertionError("no dependency-free compliance question on ACORD 125")


def test_a_yes_backed_by_a_leading_negation_is_blanked():
    schema = _schema_125()
    q = _first_gated_question(schema)
    quote = "No roofing, no demolition, no exterior work above three stories."
    from services.pdf_service import map_facts_to_form
    mapped, _c = map_facts_to_form(
        {}, schema, form_id="ACORD_125",
        raw_text=f"OPERATIONS: {quote}",
        pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                        "question_grounding": {q: quote}},
    )
    assert mapped.get(q) is None, f"{q} kept a Yes backed by a denial"


def test_a_yes_backed_by_an_affirmative_quote_survives():
    schema = _schema_125()
    q = _first_gated_question(schema)
    quote = "The insured maintains a written safety manual and conducts monthly safety meetings."
    from services.pdf_service import map_facts_to_form
    mapped, _c = map_facts_to_form(
        {}, schema, form_id="ACORD_125",
        raw_text=f"SAFETY: {quote}",
        pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                        "question_grounding": {q: quote}},
    )
    assert str(mapped.get(q) or "").lower() in ("y", "yes")


# ── J6 ───────────────────────────────────────────────────────────────────────

def test_a_negation_sentence_never_stamps_into_a_name_box():
    planted = {"BusinessInformation_ParentOrganizationName_A":
               "The Named Insured Has No Parent Company And Has No Subsidiaries."}
    mapped = _map_125(
        {}, planted,
        "The Named Insured has no parent company and has no subsidiaries.")
    assert mapped.get("BusinessInformation_ParentOrganizationName_A") is None


def test_a_company_name_with_the_word_no_survives():
    from services.pdf_service import _is_negation_sentence_in_name_field
    assert not _is_negation_sentence_in_name_field(
        "AdditionalInterest_FullName_A", "Norton & Noble Equipment Finance LLC")


# ── J7 ───────────────────────────────────────────────────────────────────────

def test_an_orphan_resolve_date_is_cleared():
    planted = {"CommercialPolicy_JudgementOrLien_ResolutionDate_B": "05/22/2025"}
    mapped = _map_125({}, planted, "claim reported 05/22/2025")
    assert mapped.get("CommercialPolicy_JudgementOrLien_ResolutionDate_B") is None


# ── J8 ───────────────────────────────────────────────────────────────────────

def test_an_insureds_own_name_cannot_be_the_additional_interest():
    facts = {
        "applicant_name": "Summit Ridge Builders LLC",
        "additional_named_insureds": ["Summit Ridge Property Holdings LLC"],
    }
    planted = {
        "AdditionalInterest_FullName_A": "Summit Ridge Property Holdings LLC",
        "AdditionalInterest_MailingAddress_CityName_A": "Highlands Ranch",
    }
    mapped = _map_125(facts, planted,
                      "Summit Ridge Property Holdings LLC Highlands Ranch")
    assert mapped.get("AdditionalInterest_FullName_A") is None
    # Nameless row -> the orphan sweep clears the leftovers too.
    assert mapped.get("AdditionalInterest_MailingAddress_CityName_A") is None


def test_the_loss_payee_fact_seeds_the_interest_name():
    facts = {"loss_payee_name": "First Peak Equipment Finance"}
    mapped = _map_125(facts, {}, "Loss Payee: First Peak Equipment Finance")
    assert str(mapped.get("AdditionalInterest_FullName_A") or "").lower() \
        == "first peak equipment finance"


# ── J9 ───────────────────────────────────────────────────────────────────────

def test_county_is_schedule_bound_and_fills_from_extraction():
    from services.extraction_service import _consolidate_property_locations
    from services.pdf_service import compute_form_gaps
    facts = {"property_locations": [
        {"address": "2200 Cascade Court, Unit B4, Aurora, CO 80014-3315",
         "county": "Arapahoe", "ownership": "tenant"},
        {"address": "88 Marketplace Ave, Unit 12, Boulder, CO 80302",
         "county": "Boulder", "ownership": "owner"},
    ]}
    _consolidate_property_locations(facts)
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    assert mapped.get("CommercialStructure_PhysicalAddress_CountyName_A") == "Arapahoe"
    assert mapped.get("CommercialStructure_PhysicalAddress_CountyName_B") == "Boulder"
    # Every county cell is owned now - none can reach the model.
    for row in "ABCD":
        assert f"CommercialStructure_PhysicalAddress_CountyName_{row}" not in unmatched


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
