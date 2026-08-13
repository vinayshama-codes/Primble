"""Third live ACORD 125 of 2026-08-13: four remaining boxes, fixed by class.

    ADDITIONAL INTEREST   Location 000 / Denver CO 80216-3121 / Limited /
                          2012 SUBARU OUTBACK SEDAN VII / Location 000:
                          Limited Pollution Coverage - Work Sites
    OTHER NAMED INSUREDS  COMMERCIAL GENERAL CONTRA
    REMARKS               Policy: BBC7263 - 26; ... Forms Applicable:
                          CG0001(04/13), CG0069(12/23), ... [36 codes]
    LOSS HISTORY          FOR THE LAST 0 YEARS

One rule was tried and narrowed mid-build; the reason is pinned by
`test_a_genuinely_different_row_b_narrative_still_survives` so the broad version
is not rebuilt from the same reasoning.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

INTEREST = "AdditionalInterest_FullName_A"


# ── 1. A schedule row label is not a party ───────────────────────────────────

@pytest.mark.parametrize("label", [
    "Location 000",       # the client's literal value
    "Location 001", "Item 4", "Building 12", "BLDG 3", "Premises 07",
    "Vehicle 2", "Unit 11", "Loc #1", "Schedule 003", "Line 9", "Class 001",
])
def test_a_row_label_is_rejected_as_a_party_name(label):
    assert ps._is_row_label_not_a_name(INTEREST, label)


@pytest.mark.parametrize("name", [
    # THE SAFETY CASE. Anchored end to end, so a real company whose name merely
    # CONTAINS one of those words and a number is untouched.
    "Building 19 Holdings LLC", "Location Services Inc", "Item 4 Trust",
    "First Bank of Denver", "Meridian Fleet Leasing, LLC",
    "Unit Trust of Colorado", "Class Act Staffing 2 Inc",
    "Summit Ridge Property Holdings LLC",
])
def test_a_real_party_name_survives(name):
    assert not ps._is_row_label_not_a_name(INTEREST, name)


def test_the_rule_is_scoped_to_interest_name_boxes():
    """A schedule row label is CORRECT in a schedule field. This must only ever
    look at a party's NAME box."""
    for field in ("CommercialStructure_LocationNumber_A",
                  "GeneralLiability_Hazard_Classification_A",
                  "NamedInsured_FullName_A"):
        assert not ps._is_row_label_not_a_name(field, "Location 000"), field


def test_why_the_existing_address_guard_could_not_catch_this():
    """DOCUMENTS THE GAP so nobody 'simplifies' by widening the other guard.

    `_drop_third_party_address_bleed` compares the insured's address to a third
    party's on the STREET line only - deliberately, because a real mortgagee can
    share the insured's city, state and ZIP. On the client's row the street box
    was empty and only the city and postcode were filled, so it had nothing to
    match on. Widening it would start deleting genuine lenders.
    """
    facts = {"mailing_address": "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"}
    mapped = {INTEREST: "Location 000",
              "AdditionalInterest_MailingAddress_CityName_A": "Denver",
              "AdditionalInterest_MailingAddress_PostalCode_A": "80216-3121"}
    assert ps._drop_third_party_address_bleed(mapped, facts, set(mapped)) == []
    # ...which is exactly why the NAME rule has to carry this case.
    assert ps._is_row_label_not_a_name(INTEREST, mapped[INTEREST])


# ── 2. A truncated head of a value we already hold ───────────────────────────

_OPS_B = "CommercialPolicy_OperationsDescription_B"
_FRAGMENT = "COMMERCIAL GENERAL CONTRA"          # the client's literal value
_FULL = "COMMERCIAL GENERAL CONTRACTOR"


def test_the_carriers_truncation_is_rejected():
    got = ps._is_truncated_copy_of_a_held_value(
        _OPS_B, _FRAGMENT, {}, {"contractor_type": _FULL})
    assert got == _FULL


def test_it_also_sees_a_fuller_value_stamped_on_the_form():
    got = ps._is_truncated_copy_of_a_held_value(
        _OPS_B, _FRAGMENT, {"CommercialPolicy_OperationsDescription_A": _FULL}, {})
    assert got == _FULL


def test_a_genuinely_different_row_b_narrative_still_survives():
    """THE RULE THAT WAS NARROWED, and why.

    The first attempt anchored this on the other named insured being UNNAMED -
    "describing the operations of a party that does not exist is never right".
    It broke `test_a_genuinely_different_row_b_narrative_survives`, a deliberate
    prior contract: extraction can legitimately find a second insured's
    operations while missing their name, and blanking a real narrative to punish
    a missing name loses more than it saves.

    What is actually wrong with the client's value is that it is the cut-off HEAD
    of something we hold in full - not that its subject is unnamed.
    """
    other = ("Summit Ridge Property Holdings LLC owns and leases the Boulder "
             "office building to the operating company; no field operations.")
    assert ps._is_truncated_copy_of_a_held_value(
        _OPS_B, other, {}, {"contractor_type": _FULL}) is None


def test_a_short_prefix_coincidence_is_out_of_scope():
    """"Roofing" is a prefix of "Roofing and siding" and both can be real."""
    assert ps._is_truncated_copy_of_a_held_value(
        _OPS_B, "Roofing", {}, {"contractor_type": "Roofing and siding"}) is None


def test_a_one_character_difference_is_not_truncation():
    long_enough = "Commercial general contracting work"
    assert ps._is_truncated_copy_of_a_held_value(
        _OPS_B, long_enough, {}, {"x": long_enough + "."}) is None


def test_only_narrative_fields_are_in_scope():
    """A code or an amount is never judged by prefix containment."""
    for field in ("NamedInsured_FullName_B", "Policy_Payment_DepositAmount_A",
                  "NamedInsured_TaxIdentifier_A"):
        assert ps._is_truncated_copy_of_a_held_value(
            field, _FRAGMENT, {}, {"contractor_type": _FULL}) is None, field


# ── 3. REMARKS is about OUR submission ───────────────────────────────────────

REMARK = "CommercialPolicy_RemarkText_A"


def test_the_remarks_box_is_an_authoritative_blank():
    assert ps._resolve_remark_text(REMARK, {}) is None
    assert ps._is_authoritative_blank_field(REMARK, {})


def test_acord101s_own_remark_rows_are_exempt():
    """ACORD 101 IS the additional-remarks form; its rows are stamped by
    `_stamp_acord101_remarks` and must not be intercepted."""
    assert ps._resolve_remark_text(
        "AdditionalRemark_RemarkText_A", {}) is ps._SCHED_SKIP


def test_a_remark_we_genuinely_hold_still_stamps():
    """A producer note or an ARQ answer arrives as a FACT and is legitimate."""
    facts = {"additional_remarks_text":
             "Please bind effective 07/15 and issue the certificate to the GC."}
    assert ps._resolve_remark_text(REMARK, facts) == facts["additional_remarks_text"]


def test_a_forms_schedule_in_the_fact_is_still_rejected():
    """The fact is not trusted blind - that is exactly how it got filled on the
    client's run. The client's literal value, shortened."""
    facts = {"additional_remarks_text": (
        "Policy: BBC7263 - 26; Policy Term: 07/15/2025-07/15/2026; Forms "
        "Applicable: CG0001(04/13), CG0069(12/23), CG2106(12/23), "
        "CG2147(12/07), CG2167(12/04), IL0017(11/98), IL7004(03/20)")}
    assert ps._resolve_remark_text(REMARK, facts) is None


def test_a_real_remark_mentioning_an_endorsement_survives():
    """Naming an endorsement is ordinary broker practice and must not be read as
    a forms schedule. This is what the threshold is for."""
    facts = {"additional_remarks_text":
             "CG 20 10 additional insured endorsement attached per contract."}
    assert ps._resolve_remark_text(REMARK, facts) == facts["additional_remarks_text"]


# ── 4. A loss-history period of zero years ───────────────────────────────────

def test_zero_years_of_loss_history_is_rejected():
    assert ps._rejects_impossible_count("LossHistory_InformationYearCount_A", "0")


def test_a_real_loss_history_period_survives():
    for good in ("3", "5", 10):
        assert not ps._rejects_impossible_count(
            "LossHistory_InformationYearCount_A", good), good


def test_zero_total_losses_is_still_a_true_statement():
    """MUST NEVER BE ADDED to `_NONZERO_COUNT_FIELDS`. The client's own package
    reports no known losses in five years; deleting a true $0 is the opposite of
    what these guards exist for."""
    for field in ("LossHistory_TotalLossAmount_A", "LossHistory_PaidAmount_A",
                  "LossHistory_ReservedAmount_A"):
        assert not ps._rejects_impossible_count(field, "0"), field
    assert len(ps._NONZERO_COUNT_FIELDS) == 2, (
        "a new non-zero count field was added - state why zero cannot be true "
        "for it, and confirm it is not a loss/claim amount")
