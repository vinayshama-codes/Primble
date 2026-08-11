"""Regression tests for the four defects graded on runs G (synthetic fixture)
and H (the real 271-page package), replayed with each run's literal values.

K1 POLICY PREMIUM summed to $9,438 on the 271-page package (one line's premium
   missed at extraction) against a stated total of $10,663 -> a total the
   DOCUMENT states wins; the sum stays as the fallback.
K2 "12:01 A.M." + the AM tick reappeared in the transaction-status TIME boxes
   whenever is_renewal failed to extract -> those boxes are owned always.
K3 One stated Loss Payee produced THREE interest ticks (Additional Insured,
   Loss Payee, Owner) -> the family is owned by the captured interest fact.
K4 "DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS" held a verbatim copy of
   the primary insured's operations -> a row-B narrative duplicating row A is
   a copy, not a record.
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


# ── K1 ───────────────────────────────────────────────────────────────────────

_PARTIAL_LINES = [                      # run H: the umbrella premium was missed
    {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "BBC7263-26"},
    {"line": "Business Auto", "premium": "$2,991", "policy_number": "6E7-40-02---26"},
    {"line": "Commercial Inland Marine", "premium": "$300", "policy_number": "6C7-40-02---26"},
    {"line": "Commercial Liability Umbrella", "premium": "$2,193", "policy_number": "6J7-40-02---26"},
]


def test_a_stated_total_beats_the_computed_sum():
    from services.pdf_service import _resolve_estimated_total
    facts = {"coverage_lines": _PARTIAL_LINES, "total_policy_premium": "$10,663"}
    assert _resolve_estimated_total(
        "Policy_Payment_EstimatedTotalAmount_A", facts) == "$10,663"


def test_the_sum_is_still_the_fallback_without_a_stated_total():
    from services.pdf_service import _resolve_estimated_total
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$4,200", "policy_number": "GL-1"},
        {"line": "Business Auto", "premium": "$3,100", "policy_number": "CA-1"},
        {"line": "Commercial Inland Marine", "premium": "$450", "policy_number": "IM-1"},
        {"line": "Commercial Liability Umbrella", "premium": "$2,750", "policy_number": "CU-1"},
    ]}
    assert _resolve_estimated_total(
        "Policy_Payment_EstimatedTotalAmount_A", facts) == "$10,500"


def test_a_non_currency_stated_total_is_ignored():
    from services.pdf_service import _resolve_estimated_total
    facts = {"coverage_lines": _PARTIAL_LINES, "total_policy_premium": "see schedule"}
    # Falls back to the sum rather than stamping prose into a money box.
    assert _resolve_estimated_total(
        "Policy_Payment_EstimatedTotalAmount_A", facts) == "$9,438"


# ── K2 ───────────────────────────────────────────────────────────────────────

def test_transaction_time_boxes_are_owned_even_without_the_renewal_fact():
    from services.pdf_service import compute_form_gaps
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), {})
    for f in ("Policy_Status_EffectiveTime_A",
              "Policy_Status_EffectiveTimeAMIndicator_A",
              "Policy_Status_EffectiveTimePMIndicator_A"):
        assert mapped.get(f) is None
        assert f not in unmatched, f"{f} can still receive the policy's 12:01 A.M."
        assert f in det
    # The rest of the family keeps its legacy path when renewal is unknown.
    assert "Policy_Status_RenewIndicator_A" in unmatched


# ── K3 ───────────────────────────────────────────────────────────────────────

def test_one_stated_loss_payee_ticks_exactly_one_interest_box():
    from services.pdf_service import compute_form_gaps
    facts = {"loss_payee_name": "First Peak Equipment Finance"}
    mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    assert mapped.get("AdditionalInterest_Interest_LossPayeeIndicator_A") == "Yes"
    for other in ("AdditionalInsured", "Owner", "Mortgagee", "Lienholder", "Trustee"):
        f = f"AdditionalInterest_Interest_{other}Indicator_A"
        assert mapped.get(f) is None, f"{f} ticked alongside the loss payee"
        assert f not in unmatched, f"{f} still LLM-fillable — a 2nd tick can recur"


def test_a_mortgagee_ticks_the_mortgagee_box():
    from services.pdf_service import _resolve_additional_interest_type
    facts = {"mortgagee_name": "First Bank of Denver"}
    assert _resolve_additional_interest_type(
        "AdditionalInterest_Interest_MortgageeIndicator_A", facts) == "Yes"
    assert _resolve_additional_interest_type(
        "AdditionalInterest_Interest_LossPayeeIndicator_A", facts) is None


def test_no_interest_fact_keeps_the_family_llm_eligible():
    from services.pdf_service import compute_form_gaps
    _m, unmatched, _d = compute_form_gaps("ACORD_125", _schema_125(), {})
    assert "AdditionalInterest_Interest_LossPayeeIndicator_A" in unmatched


# ── K4 ───────────────────────────────────────────────────────────────────────

_OPS = ("Commercial general contractor specializing in tenant finish and light "
        "commercial renovation of occupied retail and office space.")


def test_row_b_narrative_copying_row_a_is_blanked():
    planted = {
        "CommercialPolicy_OperationsDescription_A": _OPS,
        "CommercialPolicy_OperationsDescription_B": _OPS,
    }
    mapped = _map_125({}, planted, _OPS)
    assert mapped.get("CommercialPolicy_OperationsDescription_A") == _OPS
    assert mapped.get("CommercialPolicy_OperationsDescription_B") is None


def test_a_genuinely_different_row_b_narrative_survives():
    other = ("Summit Ridge Property Holdings LLC owns and leases the Boulder "
             "office building to the operating company; no field operations.")
    planted = {
        "CommercialPolicy_OperationsDescription_A": _OPS,
        "CommercialPolicy_OperationsDescription_B": other,
    }
    mapped = _map_125({}, planted, _OPS + " " + other)
    assert mapped.get("CommercialPolicy_OperationsDescription_B") == other


def test_short_repeated_codes_are_not_treated_as_narrative_copies():
    from services.pdf_service import _duplicates_primary_row_narrative
    mapped = {"Some_Field_A": "CO"}
    assert not _duplicates_primary_row_narrative("Some_Field_B", "CO", mapped)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
