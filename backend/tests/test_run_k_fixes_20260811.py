"""Regression tests for the audit of the 25-page Orbin declarations run,
replayed with that document's literal values.

P1  The PRIOR CARRIER grid held the policies being APPLIED FOR - carriers,
    premiums and the proposed term. The dec's only prior reference is
    "RENEWAL OF: 6E7-40-02---25" (a number, no carrier/premium/dates).
P4  "None Scheduled" / "NOT PURCHASED" / "NO COVERAGE" were stamped as VALUES,
    including into the coded STATE and COUNTRY boxes.
P6  "This location is owned, rented or occupied by the named insured" - a
    deliberately non-committal sentence - ticked the "Other" interest box and
    became its description.
P7  The CITY LIMITS "Other" box was ticked with the insured's street address.
P8  Installation/repair percentages came out 0%/0% on one run and 100%/100%
    on the next, from a document that states no percentage.
P11 Every line-of-business premium box was BLANK on a dec that prints all
    four, because two spellings of one amount were counted as two rivals.
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_125() -> dict:
    with open(os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── P11 ──────────────────────────────────────────────────────────────────────

def test_two_spellings_of_one_premium_are_not_ambiguous():
    from services.pdf_service import _resolve_lob_premium
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$ 3,954.00"},
        {"line": "Commercial General Liability Coverage Part", "premium": "$3,954"},
    ]}
    assert _resolve_lob_premium(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) is not None


def test_two_different_premiums_still_suppress_the_box():
    from services.pdf_service import _resolve_lob_premium
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
        {"line": "Commercial General Liability", "premium": "$4,100"},
    ]}
    assert _resolve_lob_premium(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) is None


def test_all_four_orbin_line_premiums_stamp():
    from services.pdf_service import _resolve_lob_premium
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability Coverage Part", "premium": "$ 3,954.00"},
        {"line": "Commercial Auto Coverage Part", "premium": "$ 2,991.00"},
        {"line": "Commercial Inland Marine Coverage Part", "premium": "$ 300.00"},
        {"line": "Commercial Umbrella Coverage Part", "premium": "$ 3,418.00"},
    ]}
    for f in ("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A",
              "CommercialVehicleLineOfBusiness_PremiumAmount_A",
              "CommercialInlandMarineLineOfBusiness_PremiumAmount_A",
              "CommercialUmbrellaLineOfBusiness_PremiumAmount_A"):
        assert _resolve_lob_premium(f, facts) is not None, f


# ── P1 ───────────────────────────────────────────────────────────────────────

_CURRENT_AS_PRIOR = {
    "policy_number": "6E7-40-02---26",
    "effective_date": "07/15/2025",
    "expiration_date": "07/15/2026",
    "coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
        {"line": "Commercial Auto", "policy_number": "6E7-40-02---26"},
    ],
    "prior_coverage_by_line": [
        {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
         "policy_no": "BBC7263", "premium": "$3,954",
         "effective": "07/15/2025", "expiration": "07/15/2026"},
        {"line": "Automobile", "carrier": "Employers Mutual Casualty Company",
         "policy_no": "6E7-40-02---26", "premium": "$2,991",
         "effective": "07/15/2025", "expiration": "07/15/2026"},
    ],
}


def test_the_current_policies_never_fill_the_prior_carrier_grid():
    from services.pdf_service import _resolve_prior_coverage_cell
    for f in ("PriorCoverage_GeneralLiability_InsurerFullName_A",
              "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A",
              "PriorCoverage_GeneralLiability_TotalPremiumAmount_A",
              "PriorCoverage_Automobile_InsurerFullName_A",
              "PriorCoverage_Automobile_PolicyNumberIdentifier_A",
              "PriorCoverage_Automobile_EffectiveDate_A"):
        assert _resolve_prior_coverage_cell(f, _CURRENT_AS_PRIOR) is None, f


def test_a_genuine_prior_policy_still_fills_the_grid():
    from services.pdf_service import _resolve_prior_coverage_cell
    facts = dict(_CURRENT_AS_PRIOR)
    facts["prior_coverage_by_line"] = [
        {"line": "General Liability", "carrier": "Pinnacle Casualty Company",
         "policy_no": "GL-55110-25", "premium": "$3,950",
         "effective": "09/01/2024", "expiration": "09/01/2025"},
    ]
    assert _resolve_prior_coverage_cell(
        "PriorCoverage_GeneralLiability_InsurerFullName_A", facts) == "Pinnacle Casualty Company"
    assert _resolve_prior_coverage_cell(
        "PriorCoverage_GeneralLiability_TotalPremiumAmount_A", facts) == "$3,950"


# ── P4 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "None Scheduled", "NONE SCHEDULED", "NOT PURCHASED", "NOT ATTACHED",
    "NOT INCLUDED", "NO COVERAGE", "NOT RATED", "NOT REPORTED", "NOT ON FILE",
])
def test_a_declarations_absence_phrase_is_not_a_value(phrase):
    from services.pdf_service import _is_empty_llm_value
    assert _is_empty_llm_value(phrase)


def test_a_real_value_containing_none_is_untouched():
    from services.pdf_service import _is_empty_llm_value
    assert not _is_empty_llm_value("Nonesuch Equipment Finance LLC")


# ── P6 / P7 ──────────────────────────────────────────────────────────────────

def test_a_noncommittal_ownership_sentence_leaves_the_interest_unknown():
    from services.extraction_service import _consolidate_property_locations
    facts = {"property_locations": [{
        "address": "4800 Dahlia St # D13, Denver, CO 80216-3121",
        "ownership": "owned, rented or occupied by the named insured",
    }]}
    _consolidate_property_locations(facts)
    row = facts["property_locations"][0]
    assert row["is_owner"] is None and row["is_tenant"] is None
    assert row["is_other_interest"] is None
    assert row["other_interest_description"] is None


def test_a_plain_ownership_word_still_resolves():
    from services.extraction_service import _consolidate_property_locations
    for word, owner, tenant in (("tenant", False, True), ("owner", True, False)):
        facts = {"property_locations": [{"address": "1 Main St, Denver, CO 80202",
                                         "ownership": word}]}
        _consolidate_property_locations(facts)
        row = facts["property_locations"][0]
        assert row["is_owner"] is owner and row["is_tenant"] is tenant


def test_the_city_limits_other_box_is_owned_not_guessed():
    from services.pdf_service import compute_form_gaps
    facts = {"property_locations": [{
        "address": "4800 Dahlia St # D13, Denver, CO 80216-3121",
        "address_line1": "4800 Dahlia St # D13", "address_city": "Denver",
        "address_state": "CO", "address_zip": "80216-3121", "location_number": "1",
    }]}
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    for f in ("CommercialStructure_RiskLocation_OtherIndicator_A",
              "CommercialStructure_RiskLocation_OtherDescription_A"):
        assert mapped.get(f) is None
        assert f not in unmatched, f"{f} can still receive the street address"
        assert f in det


# ── P8 ───────────────────────────────────────────────────────────────────────

def _map_125(facts, planted, raw):
    from services.pdf_service import map_facts_to_form
    mapped, _c = map_facts_to_form(
        facts, _schema_125(), form_id="ACORD_125", raw_text=raw,
        pre_filled_gpt={"filled_values": planted, "raw_text_fields": set()},
    )
    return mapped


def test_a_percentage_absent_from_the_document_is_blanked():
    planted = {
        "CommercialStructure_InstallationRepairWorkPercent_A": "100%",
        "CommercialStructure_InstallationRepairWorkOffPremisesPercent_A": "100%",
    }
    raw = ("Contractors - subcontracted work. Experience Modification: 1.000. "
           "Estimated total cost of subcontracted construction: $350,000.")
    mapped = _map_125({}, planted, raw)
    for f in planted:
        assert mapped.get(f) is None, f"{f} kept a fabricated percentage"


def test_a_percentage_the_document_states_survives():
    planted = {"CommercialStructure_InstallationRepairWorkPercent_A": "15%"}
    raw = "Installation, service or repair work: 15% of operations."
    mapped = _map_125({}, planted, raw)
    assert mapped.get("CommercialStructure_InstallationRepairWorkPercent_A") == "15%"


# ── P2 / P3 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("clause", [
    "XCU exclusions are deleted. Coverage for explosion, collapse and underground "
    "property damage hazards is included for the classifications scheduled.",
    "No person or organization has a right under this Coverage Part to sue us on "
    "this Coverage Part unless all of its terms have been fully complied with.",
    "This Coverage Part is void in any case of fraud by you as it relates to this "
    "Coverage Part at any time.",
])
def test_selected_conditions_boilerplate_cannot_answer_a_question(clause):
    from services.pdf_service import _is_policy_contract_language
    assert _is_policy_contract_language(
        "CommercialPolicy_JudgementOrLienExplanation_A", clause)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
