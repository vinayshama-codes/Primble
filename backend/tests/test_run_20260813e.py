"""Run 5 of 2026-08-13: every survivor traced to the check it walked around.

    FAX = 303-996-7800 (4th time)  <- extraction filed the PHONE under
                                      `producer_fax`; the resolver trusted the fact
    DEPOSIT = $31                  <- the terrorism premium, hunted down by the walk
    Q3 = Y  "Location 000: Limited Pollution Coverage - Work Sites $150"
                                   <- row-label prefix defeated exact membership
    Q5 = Y  "CONTRACTORS EQUIPMENT $10,000"
                                   <- the IM item's dec entry was dropped at
                                      verification, so the dec-line check was blind
    Q8 = Y  "Please contact your agent to discuss any questions."
                                   <- an imperative has verbs; nothing caught it
    Q13 = Y "2012 SUBARU OUTBACK SEDAN: ID NO 4S4BRCGC9C3217772"
                                   <- the VIN stamped in row 1 of the SAME form
    Q1 = Y over an empty owner table; vehicle row 2 junk with no identity
                                   <- BOTH the same ordering disease: judged
                                      before later guards emptied the evidence
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402


# ── 1. A fax that is the phone is a mislabel, whoever produced it ────────────

def test_the_phone_filed_under_producer_fax_is_rejected():
    facts = {"producer_fax": "303-996-7800", "producer_phone": "303-996-7800"}
    assert ps._resolve_party_fax("Producer_FaxNumber_A", facts) is None


def test_formatting_differences_do_not_save_the_mislabel():
    facts = {"producer_fax": "(303) 996-7800", "producer_contact_phone": "303.996.7800"}
    assert ps._resolve_party_fax("Producer_FaxNumber_A", facts) is None


def test_a_genuinely_distinct_fax_still_stamps():
    facts = {"producer_fax": "303-996-7801", "producer_phone": "303-996-7800"}
    assert ps._resolve_party_fax("Producer_FaxNumber_A", facts) == "303-996-7801"


# ── 2. The deposit box ────────────────────────────────────────────────────────

def test_deposit_is_blank_without_a_deposit_fact():
    assert ps._resolve_payment_deposit("Policy_Payment_DepositAmount_A", {}) is None
    assert ps._is_authoritative_blank_field("Policy_Payment_DepositAmount_A", {})


def test_a_real_deposit_fact_still_stamps():
    assert ps._resolve_payment_deposit(
        "Policy_Payment_DepositAmount_A", {"deposit_amount": "$500"}) == "$500"


def test_the_estimated_total_box_is_not_claimed():
    assert ps._resolve_payment_deposit(
        "Policy_Payment_EstimatedTotalAmount_A", {}) is ps._SCHED_SKIP


# ── 3. Coverage artifacts: the three shapes from run 5, verbatim ─────────────

_DEC_LINES = ps._dec_coverage_line_set({"dec_page_entries": [
    {"label": "Limited Pollution Coverage - Work Sites", "value": "$150"},
]})
_FACTS = {"inland_marine_items": [
    {"name": "Contractors' Equipment", "limit": "$10,000"},
    {"name": "Contractors' Essential Industry Extension", "limit": "$870"},
]}


def test_a_row_label_prefix_no_longer_defeats_the_dec_line_check():
    """Predicted as the known partial coverage when the check shipped; run 5
    delivered it verbatim. Now closed."""
    assert ps._is_coverage_artifact_text(
        "Location 000: Limited Pollution Coverage - Work Sites $150",
        _DEC_LINES, _FACTS)


def test_a_scheduled_items_name_is_an_artifact_even_when_its_entry_was_dropped():
    """The IM item's dec entry failed verbatim verification (the carrier
    truncates it differently per page), so the dec-line check was blind - but
    the item lives in the FACTS as a schedule row, and that is enough."""
    for echo in ("CONTRACTORS' EQUIPMENT $10,000", "CONTRACTORS EQUIPMENT",
                 "Contractors' Equipment $300"):
        assert ps._is_coverage_artifact_text(echo, _DEC_LINES, _FACTS), echo


def test_an_instruction_to_the_reader_is_not_evidence():
    assert ps._is_coverage_artifact_text(
        "Please contact your agent to discuss any questions.",
        frozenset(), {})


@pytest.mark.parametrize("genuine", [
    "Custom ladder rack mounted on roof.",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
    "The applicant transports hazardous materials to job sites weekly.",
    "INSURED IS: LLC",
])
def test_genuine_statements_are_not_artifacts(genuine):
    assert not ps._is_coverage_artifact_text(genuine, _DEC_LINES, _FACTS), genuine


# ── 4. A Yes contradicted by the form's own schedule ─────────────────────────

_YN_TU = ('Enter Y for a "Yes" response. Input N for "No" response. '
          'Indicates the response to the question, "{}"')


def test_q13_falls_when_its_vin_is_already_scheduled():
    """The literal run-5 value: 'any vehicles owned but NOT scheduled?' = Y,
    supported by the VIN stamped in vehicle row 1 of the same form."""
    q = "CommercialVehicleLineOfBusiness_Question_KACCode_A"
    fields = {
        q: {"tu": _YN_TU.format(
            "Any vehicles owned but not scheduled on this application?"),
            "ft": "/Tx"},
        "Vehicle_VINIdentifier_A": {"tu": "Enter identifier: VIN", "ft": "/Tx"},
    }
    pre = {"filled_values": {q: "Y"},
           "raw_text_fields": set(),
           "question_grounding": {
               q: "2012 SUBARU OUTBACK SEDAN: ID NO 4S4BRCGC9C3217772"}}
    doc = ("BUSINESS AUTO DECLARATIONS\n2012 SUBARU OUTBACK SEDAN: "
           "ID NO 4S4BRCGC9C3217772\n")
    # The VIN reaches row A the way it does live: from the schedule fact,
    # through the deterministic row resolver - not through gap fill.
    facts = {"auto_vin_schedule": [
        {"vin": "4S4BRCGC9C3217772", "year": "2012", "make": "SUBARU"}]}
    mapped, _ = ps.map_facts_to_form(facts, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get("Vehicle_VINIdentifier_A") == "4S4BRCGC9C3217772"
    assert mapped.get(q) is None


def test_an_unscheduled_vin_keeps_its_yes():
    """A genuinely different VIN is exactly what Q13 exists to disclose."""
    q = "CommercialVehicleLineOfBusiness_Question_KACCode_A"
    fields = {
        q: {"tu": _YN_TU.format(
            "Any vehicles owned but not scheduled on this application?"),
            "ft": "/Tx"},
        "Vehicle_VINIdentifier_A": {"tu": "Enter identifier: VIN", "ft": "/Tx"},
    }
    pre = {"filled_values": {q: "Y"},
           "raw_text_fields": set(),
           "question_grounding": {
               q: "The applicant also owns a 2019 FORD F250, ID NO "
                  "1FT7W2BT5KEE11111, which is not scheduled."}}
    doc = ("BUSINESS AUTO DECLARATIONS\n2012 SUBARU OUTBACK: ID NO "
           "4S4BRCGC9C3217772\nThe applicant also owns a 2019 FORD F250, ID NO "
           "1FT7W2BT5KEE11111, which is not scheduled.\n")
    facts = {"auto_vin_schedule": [
        {"vin": "4S4BRCGC9C3217772", "year": "2012", "make": "SUBARU"}]}
    mapped, _ = ps.map_facts_to_form(facts, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get(q) == "Y"


# ── 5. The ordering disease, pinned ──────────────────────────────────────────

def test_the_late_row_sweep_clears_junk_that_outlived_its_anchor():
    """Row B junk whose copied identity a later guard removed: the late pass
    judges anchor state at the END, when it is finally true."""
    schema = {
        "Vehicle_VINIdentifier_B": {}, "Vehicle_ModelYear_B": {},
        "Vehicle_RateClassCode_B": {}, "Vehicle_CostNewAmount_B": {},
    }
    mapped = {"Vehicle_RateClassCode_B": "91585",
              "Vehicle_CostNewAmount_B": "$10,000"}
    ghost = ps._unanchored_schedule_row_fields(mapped, schema, set(mapped))
    assert ghost == {"Vehicle_RateClassCode_B", "Vehicle_CostNewAmount_B"}
