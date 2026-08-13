"""Client run 2026-08-12: three defects, verified against the real schemas.

1. THE PRODUCER WAS A DRIVER. ACORD 127 listed "ERIN ROYAL" - the producer
   contact at Commercial Risk Solutions - in the driver schedule, and ACORD 125
   then ticked DRIVER INFORMATION SCHEDULE because `auto_drivers` was non-empty.
   One bad row, two wrong boxes on two forms.

2. ACORD 125 QUESTION 5 answered from policy boilerplate, twice, with DIFFERENT
   wording each time - which is why the fix is structural rather than lexical:
     2026-08-08  NON-PAYMENT ticked + "The description of how the underwriting
                 condition that caused the policy not to be written..."
     2026-08-12  NON-RENEWAL ticked + "The policyholder is a member of the
                 Company and shall participate in the distribution of dividends"
   Neither says anything about this applicant. The second slips every wording
   guard - `_is_policy_contract_language` returns False on it.

3. NATURE OF BUSINESS printed "Contractor" while the CONTRACTORS SUPPLEMENT
   attachment stayed blank, because that box read `contractor_type` (free text a
   dec page rarely states) instead of the derived flag that ticks the other.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _schema(form_id="ACORD_125"):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# The client's literal identity values.
IDENTITY = {
    "producer_contact_name": "Erin Royal",
    "producer_name": "Commercial Risk Solutions, Inc.",
    "carrier_name": "Employers Mutual Casualty Company",
}


# ── 1. A transaction party is not a driver ──────────────────────────────────

def test_the_producer_is_dropped_from_the_driver_schedule():
    """THE reported case, with the client's literal name and casing."""
    rows = [{"name": "ERIN ROYAL"}, {"name": "John Smith", "license_number": "CO123"}]
    kept = es._drop_transaction_party_rows("auto_drivers", rows, IDENTITY)
    assert [r["name"] for r in kept] == ["John Smith"]


def test_the_carrier_is_dropped_too():
    rows = [{"name": "Employers Mutual Casualty Company"}, {"name": "Jane Doe"}]
    kept = es._drop_transaction_party_rows("auto_drivers", rows, IDENTITY)
    assert [r["name"] for r in kept] == ["Jane Doe"]


def test_an_all_party_schedule_becomes_empty_not_restored():
    """Empty IS the right answer - there is no driver schedule. Restoring the
    rows would put the producer back on the form and re-tick the attachment."""
    assert es._drop_transaction_party_rows(
        "auto_drivers", [{"name": "Erin Royal"}], IDENTITY) == []


def test_no_identity_facts_means_no_filtering():
    """Acts only on positive evidence - never guesses who a party is."""
    rows = [{"name": "ERIN ROYAL"}, {"name": "John Smith"}]
    assert es._drop_transaction_party_rows("auto_drivers", rows, {}) == rows


def test_only_person_schedules_are_filtered():
    """A company name legitimately repeats down a property or vehicle schedule."""
    rows = [{"name": "Employers Mutual Casualty Company"}]
    assert es._drop_transaction_party_rows("property_locations", rows, IDENTITY) == rows


def test_a_short_name_can_never_match():
    """Guards against a two-letter producer name blocking a real driver."""
    rows = [{"name": "Lee"}]
    assert es._drop_transaction_party_rows(
        "auto_drivers", rows, {"producer_contact_name": "Lee"}) == rows


def test_the_attachment_box_follows_the_filtered_schedule():
    """The second half of the defect: the ACORD 125 checkbox."""
    field = "Policy_SectionAttached_DriverInformationScheduleIndicator_A"
    assert ps._derive_indicator(field, {"auto_drivers": []}) == "No"
    assert ps._derive_indicator(field, {"auto_drivers": [
        {"name": "John Smith", "license_number": "S123-4567"}]}) == "Yes"


def test_a_name_only_row_is_not_a_driver_schedule():
    """TIGHTENED 2026-08-13, and the fixture above moved with it.

    Live run: the attachment box was ticked on a package with no drivers,
    because extraction had read page 92's `CA 99 10 A DRIVE OTHER CAR COVERAGE -
    NAMES OF INDIVIDUALS` as a driver schedule. Drive Other Car names an
    individual covered while driving someone else's car; it is not a schedule of
    the applicant's drivers, and on the page the two shapes are identical.

    The client's own instruction is the test: the box is for when we "actually
    create and attach a COMPLETED driver-information schedule". A row with
    nothing but a name completes nothing - every other ACORD driver column would
    ship blank.
    """
    field = "Policy_SectionAttached_DriverInformationScheduleIndicator_A"
    assert ps._derive_indicator(
        field, {"auto_drivers": [{"name": "Erin Royal"}]}) == "No"
    # Empty strings and nulls are not substance either.
    assert ps._derive_indicator(field, {"auto_drivers": [
        {"name": "Erin Royal", "dob": None, "license_number": ""}]}) == "No"
    # ANY real column brings it back - not just a licence number.
    for col in ("dob", "license_state", "hire_date", "experience_years"):
        assert ps._derive_indicator(
            field, {"auto_drivers": [{"name": "Erin Royal", col: "X"}]}) == "Yes", col


def test_the_rows_themselves_are_not_deleted():
    """Non-destructive by design: only the ATTACHMENT CLAIM is withdrawn. The
    rows stay in the facts for `Driver_FullName_*` and the questionnaire, because
    deleting extracted data on a heuristic is the failure mode this codebase
    already documented at C24."""
    rows = [{"name": "Erin Royal"}]
    facts = {"auto_drivers": rows}
    ps._derive_indicator(
        "Policy_SectionAttached_DriverInformationScheduleIndicator_A", facts)
    assert facts["auto_drivers"] == rows


# ── 2. Question 5's reason boxes depend on Question 5 ────────────────────────

Q5 = "CommercialPolicy_Question_AACCode_A"
Q5_DEPENDENTS = (
    "CancelNonRenew_NonPaymentIndicator_A",
    "CancelNonRenew_NonRenewalIndicator_A",
    "CancelNonRenew_UnderwritingIndicator_A",
    "CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A",
    "CancelNonRenew_OtherIndicator_A",
    "CancelNonRenew_OtherDescription_A",
    "CancelNonRenew_UnderwritingConditionCorrectedIndicator_A",
    "CancelNonRenew_UnderwritingConditionCorrectedDescription_A",
)


def test_every_q5_dependent_exists_in_the_real_schema():
    """A typo here would silently disable the guard."""
    schema = _schema()
    assert Q5 in schema
    missing = [f for f in Q5_DEPENDENTS if f not in schema]
    assert not missing, f"not real ACORD 125 fields: {missing}"


@pytest.mark.parametrize("narrative", [
    "The policyholder is a member of the Company and shall participate in the "
    "distribution of dividends",
    "The description of how the underwriting condition that caused the policy "
    "not to be written was corrected",
])
def test_an_unanswered_q5_clears_its_reasons_and_narrative(narrative):
    """BOTH live boilerplate variants, verbatim."""
    mapped = {
        Q5: None,
        "CancelNonRenew_NonRenewalIndicator_A": "Yes",
        "CancelNonRenew_UnderwritingConditionCorrectedDescription_A": narrative,
    }
    ps._enforce_post_fill_guards(mapped, _schema(), {}, gpt_filled_set=set(mapped))
    assert mapped["CancelNonRenew_NonRenewalIndicator_A"] is None
    assert mapped["CancelNonRenew_UnderwritingConditionCorrectedDescription_A"] is None


def test_a_genuine_cancellation_survives():
    """THE load-bearing test. A real reported event must still reach the form -
    the guard removes an unsupported answer, never a supported one."""
    mapped = {
        Q5: "Y",
        "CancelNonRenew_NonPaymentIndicator_A": "Yes",
        "CancelNonRenew_OtherDescription_A":
            "Cancelled 03/2024 for late payment of the March installment",
    }
    ps._enforce_post_fill_guards(mapped, _schema(), {}, gpt_filled_set=set(mapped))
    assert mapped[Q5] == "Y"
    assert mapped["CancelNonRenew_NonPaymentIndicator_A"] == "Yes"
    assert mapped["CancelNonRenew_OtherDescription_A"].startswith("Cancelled 03/2024")


def test_the_guard_is_wording_independent():
    """The 2026-08-12 narrative defeats every lexical check, which is the whole
    reason the fix anchors on the question instead of the sentence."""
    assert not ps._is_policy_contract_language(
        "CancelNonRenew_UnderwritingConditionCorrectedDescription_A",
        "The policyholder is a member of the Company and shall participate in "
        "the distribution of dividends")


# ── 3. The form must not contradict itself ──────────────────────────────────

def test_contractor_nature_of_business_implies_the_contractors_supplement():
    box = "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"
    assert ps._derive_indicator(box, {"is_contractor": True}) == "Yes"
    assert ps._derive_indicator(box, {"is_contractor": False}) == "No"


def test_edp_stays_closed_to_the_machine():
    """Deliberately NOT fixed, and pinned so it is not 'fixed' by mistake.

    The client asked for this box to stay ticked because the declarations grant
    EDP coverage. The box asks whether an ACORD EDP SECTION is attached to the
    application WE produce - we produce none. Driving it from a coverage flag
    was tried on 2026-08-12 and reverted. Their own Driver Information Schedule
    instruction states the correct rule for the whole family.
    """
    field = "Policy_SectionAttached_ElectronicDataProcessingIndicator_A"
    assert ps._is_authoritative_blank_field(field, {})
    assert ps._deterministic_map(field, {}) is None
