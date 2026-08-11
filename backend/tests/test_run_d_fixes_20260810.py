"""Regression tests for the defects visible on run D (ACORD_125_FILLED_NEW(3)),
each replayed with the run's literal values.

H1  "not present" stamped in the NAIC box -> absence sentinels blocked.
H2  Statutory fraud-warning boilerplate in Q5's narrative -> policy-language.
H3  BOILER & MACHINERY ticked from a bare mention -> lines_of_business ticks
    need grant corroboration when per-line data exists.
H4  "# D13" duplicated into LineTwo / claims-carrier contacts in the applicant
    block -> LineTwo and NamedInsured_Contact_* are owned by their facts.
H5  ISSUE POLICY + RENEW both ticked by the model -> LLM-sourced single-choice
    contradictions are cleared.
H6  "Emc Property & Casualty Company" as the ADDITIONAL INSURED -> a name that
    identity-matches the carrier/producer is blanked (and the orphan sweep
    then clears the rest of the row).
H7  Business start date == policy effective date -> blanked, any source.
H8  Application completion date is the GENERATION date, never the policy
    effective date.
"""

import json
import os
from datetime import datetime

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


# ── H1 ───────────────────────────────────────────────────────────────────────

def test_absence_phrasings_are_never_values():
    from services.pdf_service import _is_empty_llm_value
    for s in ("not present", "Not Present", "NOT STATED", "not found",
              "not shown", "not mentioned", "none found", "not on file"):
        assert _is_empty_llm_value(s), f"{s!r} survived as a stampable value"


# ── H2 ───────────────────────────────────────────────────────────────────────

def test_fraud_warning_boilerplate_is_policy_language():
    from services.pdf_service import _is_policy_contract_language
    run_d_text = ("A false statement knowingly made by the insured on the "
                  "application for this coverage will render the coverage void.")
    assert _is_policy_contract_language(
        "CancelNonRenew_UnderwritingConditionCorrectedDescription_A", run_d_text)
    # A genuine applicant narrative is untouched.
    assert not _is_policy_contract_language(
        "CancelNonRenew_UnderwritingConditionCorrectedDescription_A",
        "Prior policy was non-renewed after a roof claim; roof was replaced "
        "in 2023 and coverage has been continuous since.")


# ── H3 ───────────────────────────────────────────────────────────────────────

def test_boiler_mention_without_grant_resolves_no():
    from services.pdf_service import _derive_indicator
    facts = {
        "lines_of_business": ["General Liability", "Boiler & Machinery"],
        "coverage_lines": [
            {"line": "Commercial General Liability", "premium": "$3,954"},
            {"line": "Business Auto", "premium": "$2,991"},
        ],
    }
    assert _derive_indicator(
        "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A", facts) == "No"


def test_boiler_with_grant_still_ticks():
    from services.pdf_service import _derive_indicator
    facts = {
        "lines_of_business": ["Boiler & Machinery"],
        "coverage_lines": [{"line": "Boiler & Machinery", "premium": "$450"}],
    }
    assert _derive_indicator(
        "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A", facts) == "Yes"


def test_boiler_without_per_line_data_keeps_legacy_behaviour():
    from services.pdf_service import _derive_indicator
    facts = {"lines_of_business": ["Boiler & Machinery"]}
    assert _derive_indicator(
        "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A", facts) == "Yes"


# ── H4 ───────────────────────────────────────────────────────────────────────

def test_line_two_is_owned_by_the_parsed_mailing_address():
    from services.pdf_service import compute_form_gaps
    facts = {"mailing_address": "4800 Dahlia St # D13, Denver, CO 80216-3121"}
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    f = "NamedInsured_MailingAddress_LineTwo_A"
    assert mapped.get(f) is None
    assert f not in unmatched, "LineTwo still LLM-fillable — the # D13 dup can recur"
    assert f in det
    # A real 4-part address still yields its suite on line two.
    from services.pdf_service import _resolve_address_line_two
    assert _resolve_address_line_two(
        f, {"mailing_address": "4800 Dahlia St, # D13, Denver, CO 80216-3121"},
    ) == "# D13"


def test_applicant_contact_family_is_blank_without_applicant_facts():
    from services.pdf_service import compute_form_gaps
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), {})
    for f in ("NamedInsured_Contact_ContactDescription_A",
              "NamedInsured_Contact_SecondaryPhoneNumber_A",
              "NamedInsured_Contact_PrimaryEmailAddress_A"):
        assert mapped.get(f) is None
        assert f not in unmatched, f"{f} still LLM-fillable with no applicant contact"
        assert f in det


def test_applicant_contact_family_opens_when_a_real_contact_exists():
    from services.pdf_service import compute_form_gaps
    mapped, unmatched, _det = compute_form_gaps(
        "ACORD_125", _schema_125(),
        {"contact_name": "Pat Owner", "contact_phone": "303-555-9999"},
    )
    assert mapped.get("NamedInsured_Contact_FullName_A") == "Pat Owner"
    assert "NamedInsured_Contact_ContactDescription_A" in unmatched


# ── H5 ───────────────────────────────────────────────────────────────────────

def test_llm_sourced_status_contradiction_is_cleared():
    planted = {
        "Policy_Status_IssueIndicator_A": "Yes",
        "Policy_Status_RenewIndicator_A": "Yes",
    }
    mapped = _map_125({}, planted, "issued renewal policy")
    assert mapped.get("Policy_Status_IssueIndicator_A") is None
    assert mapped.get("Policy_Status_RenewIndicator_A") is None


# ── H6 ───────────────────────────────────────────────────────────────────────

def test_carrier_named_as_additional_insured_is_removed_with_its_row():
    facts = {"carrier_name": "Employers Mutual Casualty Company"}
    planted = {
        "AdditionalInterest_FullName_A": "Emc Property & Casualty Company",
        "AdditionalInterest_Interest_AdditionalInsuredIndicator_A": "Yes",
        "AdditionalInterest_MailingAddress_CityName_A": "Greenwood Village",
    }
    mapped = _map_125(
        facts, planted,
        "Emc Property & Casualty Company Greenwood Village servicing carrier",
    )
    for f in planted:
        assert mapped.get(f) is None, f"{f} survived with {mapped.get(f)!r}"


def test_a_genuine_bank_additional_interest_is_untouched():
    facts = {"carrier_name": "Employers Mutual Casualty Company"}
    planted = {
        "AdditionalInterest_FullName_A": "First Bank of Denver",
        "AdditionalInterest_Interest_MortgageeIndicator_A": "Yes",
    }
    mapped = _map_125(facts, planted, "Mortgagee: First Bank of Denver")
    assert str(mapped.get("AdditionalInterest_FullName_A")).lower() == "first bank of denver"


# ── H7 ───────────────────────────────────────────────────────────────────────

def test_business_start_date_equal_to_policy_date_is_blanked():
    facts = {"business_start_date": "07/15/2025",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}
    mapped = _map_125(facts, {}, "policy effective 07/15/2025")
    assert mapped.get("NamedInsured_BusinessStartDate_A") is None


def test_a_genuine_business_start_date_survives():
    facts = {"business_start_date": "03/10/2010",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}
    mapped = _map_125(facts, {}, "in business since 03/10/2010")
    assert mapped.get("NamedInsured_BusinessStartDate_A") == "03/10/2010"


# ── H8 ───────────────────────────────────────────────────────────────────────

def test_form_completion_date_is_the_generation_date():
    from services.pdf_service import _deterministic_map
    got = _deterministic_map(
        "Form_CompletionDate_A", {"effective_date": "07/15/2025"})
    assert got == datetime.now().strftime("%m/%d/%Y")
    assert got != "07/15/2025"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
