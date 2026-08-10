"""Policy contract language is not a fact about the applicant.

Client feedback on the live ACORD 125, Parts 11 and 12. Their own summary is the
rule this file enforces:

  "The central defect is that Primble is not distinguishing among:
     Policy metadata - dates, carriers and policy numbers
     Policy contract language - bankruptcy, judgments, liens and cancellation
       provisions
     Applicant-history facts - actual bankruptcies, violations, cancellations
   Only the third category belongs in these ACORD 125 questions."

And, verbatim:
  "A policy effective date must never be repurposed as an occurrence, loss,
   violation or incident date."
  "Do not interpret a policy's Bankruptcy condition as applicant-history
   evidence."
  "Never convert generic policy terminology into applicant-history facts."

Two guards here:

1. A grounding quote that is the POLICY describing its own operation cannot
   answer a question about the applicant - in EITHER direction. "Bankruptcy or
   insolvency of the insured will not relieve us of our obligations" reads as a
   negation, which is how a false "N" survived on the live form.

2. An event-date box must never hold one of the policy's own metadata dates.
   The live form had the policy inception, 07/15/2025, sitting in the
   uncorrected-fire-code OCCURRENCE DATE.
"""
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
POLICY_DATES = {"effective_date": "07/15/2025", "expiration_date": "07/15/2026"}
FIRE_DATE = "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A"


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. Contract language answers neither Y nor N ─────────────────────────────

@pytest.mark.parametrize("quote", [
    "Bankruptcy or insolvency of the insured or of the insured's estate will not "
    "relieve us of our obligations under this policy",
    'Bankruptcy or insolvency of the "underlying insurer" will not relieve us of our duties',
    "This insurance does not apply to bodily injury arising out of pollution",
    "We will not pay for loss caused by wear and tear",
    "The insurer's right to inspect the premises does not constitute a safety program",
])
def test_policy_contract_language_is_recognised(quote):
    assert ps._POLICY_CONTRACT_LANGUAGE_RE.search(quote) is not None


@pytest.mark.parametrize("quote", [
    "The applicant has no prior cancellations",
    "Loss-free for the past five years",
    "No vehicles are owned or leased by the applicant",
    # The APPLICANT saying "we" - must not be mistaken for the insurer.
    "We have had no claims in the past five years",
    "Applicant reports no bankruptcy filings",
    "There have been no judgments or liens against the business",
    "No subcontractors are used without a certificate of insurance",
])
def test_genuine_applicant_statements_survive(quote):
    """THE LOAD-BEARING TEST. Anchored on the INSURER speaking as a party, not on
    any topic word, so an applicant writing "we" is untouched."""
    assert ps._POLICY_CONTRACT_LANGUAGE_RE.search(quote) is None


def test_it_applies_to_both_directions():
    """Unlike the exclusion checks, this one is NOT scoped to "Yes". The live
    false answer was an "N" grounded on the bankruptcy condition."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    idx = src.index("_POLICY_CONTRACT_LANGUAGE_RE.search")
    window = src[max(0, idx - 160):idx]
    assert "not negative" not in window, (
        "the contract-language check must apply to N as well as Y"
    )


# ── 2. A policy date is not an event date ────────────────────────────────────

@pytest.mark.parametrize("value", [
    "07/15/2025", "2025-07-15", "July 15, 2025", "7/15/25", "07/15/2026",
])
def test_a_policy_date_in_an_event_box_is_caught_in_any_format(value):
    """Digits-only comparison is order-sensitive and would let the ISO form
    through; the shared `normalize_date` is used instead."""
    assert ps._event_date_is_really_a_policy_date(FIRE_DATE, value, POLICY_DATES)


@pytest.mark.parametrize("value", ["03/11/2023", "12/01/2024", "", None])
def test_a_genuine_event_date_is_untouched(value):
    assert not ps._event_date_is_really_a_policy_date(FIRE_DATE, value, POLICY_DATES)


def test_the_client_reported_case_end_to_end():
    """Client Part 12 #8: "The occurrence date 07/15/2025 is incorrect. That is
    the policy's effective date." """
    mapped = {FIRE_DATE: "07/15/2025",
              "Policy_EffectiveDate_A": "07/15/2025",
              "Policy_ExpirationDate_A": "07/15/2026"}
    ps._enforce_post_fill_guards(mapped, _acord125(), POLICY_DATES)
    assert mapped[FIRE_DATE] is None
    # The policy's OWN date boxes must keep it.
    assert mapped["Policy_EffectiveDate_A"] == "07/15/2025"
    assert mapped["Policy_ExpirationDate_A"] == "07/15/2026"


def test_a_real_violation_on_a_reported_question_survives():
    """A confirmed violation with its own date must not be blanked."""
    mapped = {
        "CommercialPolicy_Question_AAFCode_A": "Y",
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A":
            "Sprinkler inspection tag expired; corrected 04/2023",
        FIRE_DATE: "03/11/2023",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), POLICY_DATES)
    assert mapped[FIRE_DATE] == "03/11/2023"


def test_policy_date_still_goes_even_when_the_question_is_yes():
    mapped = {
        "CommercialPolicy_Question_AAFCode_A": "Y",
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A": "Sprinkler tag expired",
        FIRE_DATE: "07/15/2025",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), POLICY_DATES)
    assert mapped[FIRE_DATE] is None


def test_event_date_fields_are_found_across_the_forms():
    """STANDING GUARD on scope: 25 event-date boxes across ACORD 125, 131, 127.
    A drop to zero means the detector stopped matching and the guard is dead."""
    total = 0
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            total += sum(1 for f in json.load(fh) if ps._is_event_date_field(f))
    assert total >= 20, f"only {total} event-date fields detected"


def test_ordinary_date_fields_are_not_event_dates():
    """The policy's own date boxes must never be swept in."""
    for field in ("Policy_EffectiveDate_A", "Policy_ExpirationDate_A",
                  "NamedInsured_BusinessStartDate_A",
                  "PriorCoverage_GeneralLiability_EffectiveDate_A"):
        assert not ps._is_event_date_field(field), field
