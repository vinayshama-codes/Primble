"""
Regression tests for the deterministic post-fill guards
(services.pdf_service._enforce_post_fill_guards) - Guard 3 (wrong-type value
rejection) and Guard 4 (cross-field boilerplate bleed). Neither guard had any
test coverage before this file.

Run from backend/:
    python -m pytest tests/test_post_fill_guards.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import _enforce_post_fill_guards  # noqa: E402


# ── Guard 3: wrong-type value rejection ────────────────────────────────────

def test_guard3_blanks_prose_in_checkbox():
    mapped = {"GeneralLiability_ClaimsMadeIndicator_A": "COMMERCIAL GENERAL CONTRACTOR"}
    schema = {"GeneralLiability_ClaimsMadeIndicator_A": {"ft": "/Btn"}}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["GeneralLiability_ClaimsMadeIndicator_A"] is None


def test_guard3_keeps_valid_checkbox_value():
    mapped = {"GeneralLiability_ClaimsMadeIndicator_A": "Yes"}
    schema = {"GeneralLiability_ClaimsMadeIndicator_A": {"ft": "/Btn"}}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["GeneralLiability_ClaimsMadeIndicator_A"] == "Yes"


def test_guard3_blanks_prose_in_numeric_deductible_field():
    # The exact reported bug (Figure 30): a contractor description landing in
    # a per-claim deductible box.
    mapped = {"GeneralLiability_DeductiblePerOccurrence_A": "COMMERCIAL GENERAL CONTRACTOR"}
    schema = {"GeneralLiability_DeductiblePerOccurrence_A": {"ft": "/Tx"}}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["GeneralLiability_DeductiblePerOccurrence_A"] is None


def test_guard3_keeps_valid_numeric_value():
    mapped = {"GeneralLiability_DeductiblePerOccurrence_A": "$1,000"}
    schema = {"GeneralLiability_DeductiblePerOccurrence_A": {"ft": "/Tx"}}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["GeneralLiability_DeductiblePerOccurrence_A"] == "$1,000"


# ── Guard 4: cross-field boilerplate bleed ─────────────────────────────────

def test_guard4_exact_duplicate_across_two_families_is_blanked():
    # Client requirement: "multiple unrelated fields". The guard now triggers
    # at 2+ distinct field families - the old 3+ threshold made a 2-field
    # bleed invisible.
    boilerplate = "This certificate confirms coverage at the location shown on file"
    mapped = {
        "CommercialPolicy_OperationsDescription_A": boilerplate,
        "AdditionalInterest_InterestReasonDescription_A": boilerplate,
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialPolicy_OperationsDescription_A"] is None
    assert mapped["AdditionalInterest_InterestReasonDescription_A"] is None


def test_guard4_keeps_the_legitimate_owner_field():
    boilerplate = "General contracting and remodeling services provided to residential clients"
    facts = {"operations_description": boilerplate}
    mapped = {
        "CommercialPolicy_OperationsDescription_A": boilerplate,          # real owner (deterministic rule)
        "AdditionalInterest_InterestReasonDescription_A": boilerplate,    # bled copy
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts=facts)
    assert mapped["CommercialPolicy_OperationsDescription_A"] == boilerplate  # kept
    assert mapped["AdditionalInterest_InterestReasonDescription_A"] is None   # blanked


def test_guard4_catches_paraphrased_boilerplate_not_just_verbatim():
    # The dominant real LLM failure mode is the same idea reworded per field,
    # not verbatim copy-paste. Exact-string matching alone (the old
    # implementation) never caught this.
    mapped = {
        "CommercialPolicy_OperationsDescription_A":
            "The applicant provides general contracting and remodeling services to residential clients",
        "AdditionalInterest_InterestReasonDescription_A":
            "General contracting and remodeling services are provided by the applicant to residential clients",
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert all(v is None for v in mapped.values())


def test_guard4_does_not_blank_short_or_unrelated_values():
    mapped = {
        "CommercialPolicy_OperationsDescription_A": "General contracting services",
        "AdditionalInterest_InterestReasonDescription_A": "Mortgagee interest in the insured premises",
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialPolicy_OperationsDescription_A"] == "General contracting services"
    assert mapped["AdditionalInterest_InterestReasonDescription_A"] == "Mortgagee interest in the insured premises"


def test_guard4_same_family_repeat_rows_do_not_count_as_bleed():
    # Two rows of the SAME schedule family collapse to one family - sharing a
    # value across A/B of the same GL-hazard base is not cross-field bleed.
    # (Uses the GL hazard schedule pattern, which Guard 2's separate row-
    # dedup deliberately exempts, so this isolates Guard 4's own behavior.)
    value = "Premises operations classification for the primary business location"
    mapped = {
        "GeneralLiability_Hazard_ClassCode_A": value,
        "GeneralLiability_Hazard_ClassCode_B": value,
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["GeneralLiability_Hazard_ClassCode_A"] == value
    assert mapped["GeneralLiability_Hazard_ClassCode_B"] == value


def test_guard4_does_not_blank_confirmed_yes_explanation_shared_with_other_fields():
    # Regression for a live-test finding (2026-07-13): the evidence gate
    # (Pass A in map_facts_to_form) keeps a "Yes" and guarantees it carries a
    # grounded explanation - but if the model reused that SAME real citation
    # as its (wrong) justification for other unrelated Yes/No questions too,
    # Guard 4 used to see 2+ field families sharing identical text and blank
    # ALL of them, including the one it was genuinely true for. Net result: a
    # bare "Yes" with no explanation reaches the download - exactly what the
    # evidence gate exists to prevent. The paired explanation of a currently
    # affirmative Question-code field is now exempted from this sweep.
    quote = "MVR checks are run annually on all drivers at time of hire and at each policy renewal"
    q_field = "CommercialVehicleLineOfBusiness_Question_KAECode_A"
    exp_field = "CommercialVehicleLineOfBusiness_ApplicantObtainMVRVerificationsExplanation_A"
    other_exp_field_1 = "CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A"
    other_exp_field_2 = "CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A"
    mapped = {
        q_field: "Y",
        exp_field: quote,
        other_exp_field_1: quote,
        other_exp_field_2: quote,
    }
    # Dict order matters: _question_explanation_pairs requires the explanation
    # to be the IMMEDIATE next schema key after its question.
    schema = {
        q_field: {"ft": "/Tx"},
        exp_field: {"ft": "/Tx"},
        other_exp_field_1: {"ft": "/Tx"},
        other_exp_field_2: {"ft": "/Tx"},
    }
    _enforce_post_fill_guards(mapped, schema, facts={})
    # The confirmed explanation for the kept "Yes" survives - no bare Yes.
    assert mapped[q_field] == "Y"
    assert mapped[exp_field] == quote
    # The exemption is narrow: unrelated fields that borrowed the same
    # boilerplate (not paired to any kept "Yes") are still correctly blanked.
    assert mapped[other_exp_field_1] is None
    assert mapped[other_exp_field_2] is None


def test_guard4_still_blanks_unconfirmed_explanation_bleed():
    # Sanity check the exemption doesn't neuter Guard 4 generally: with NO
    # Question-code pairing at all (ordinary narrative fields), identical
    # boilerplate across unrelated fields is still blanked exactly as before.
    boilerplate = "This certificate confirms coverage at the location shown on file"
    mapped = {
        "CommercialPolicy_OperationsDescription_A": boilerplate,
        "AdditionalInterest_InterestReasonDescription_A": boilerplate,
    }
    schema = {k: {"ft": "/Tx"} for k in mapped}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialPolicy_OperationsDescription_A"] is None
    assert mapped["AdditionalInterest_InterestReasonDescription_A"] is None
