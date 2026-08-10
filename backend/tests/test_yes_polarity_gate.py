"""A "Yes" may not be justified by evidence that denies the thing.

The evidence gate has always required a "No" to cite a quote that actually
denies something (`_quote_expresses_negative`). A "Yes" only had to cite a quote
that EXISTS anywhere in the document. That asymmetry is what let

    "Commercial Property - No Coverage"

serve as the grounding quote for TICKING the Commercial Property box - the
client's report #5. A denial is not proof of the opposite.

THE TWO SIDES ARE DELIBERATELY NOT SYMMETRIC, and that is the point of this
file. The "No" side uses the broad `_NEGATION_CUE_RE`
(no|not|none|never|without|free|clear|clean|...) because its failure mode is a
blank. Using that same cue to reject a "Yes" would DELETE correct answers:

    "Crime Coverage Policy No. BBC7263 - Employee Dishonesty $50,000"   <- "No."
    "The building is a free-standing masonry structure"                 <- "free"
    "Item No. 4 - Contractors Equipment Floater"                        <- "No."

Measured: the broad cue wrongly rejects 7 of 10 realistic affirmative quotes.
The narrow `_COVERAGE_DENIAL_RE` ("no coverage" / "not covered" / "coverage not
provided") rejects 0 of 10 and still catches every real denial. Do not "tidy"
this into one shared helper.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
from services.extraction_service import _COVERAGE_DENIAL_RE  # noqa: E402


def _denies(quote: str) -> bool:
    return bool(_COVERAGE_DENIAL_RE.search(quote.lower()))


# Realistic grounding quotes for a legitimate "Yes".
AFFIRMATIVE_QUOTES = [
    "Crime Coverage Policy No. BBC7263 - Employee Dishonesty $50,000",
    "The building is a free-standing masonry structure",
    "Clean room operations are conducted on premises",
    "Loss-free for the past five years",
    "Coverage includes theft, not limited to burglary",
    "Cyber Liability $1,000,000 aggregate",
    "Applicant owns and operates 3 vehicles",
    "Hazardous materials are stored on site",
    "Item No. 4 - Contractors Equipment Floater",
    "Neither party may cancel without 30 days notice",
]

REAL_DENIALS = [
    "Property - No Coverage",
    "Crime and Fidelity - No Coverage",
    "Workers Compensation   Not Covered",
    "Coverage Not Provided for this line",
]


@pytest.mark.parametrize("quote", AFFIRMATIVE_QUOTES)
def test_a_legitimate_yes_quote_is_never_treated_as_a_denial(quote):
    """THE LOAD-BEARING TEST. Every one of these must survive - this change is
    only allowed to remove wrong Yes answers, never right ones."""
    assert _denies(quote) is False


@pytest.mark.parametrize("quote", REAL_DENIALS)
def test_a_real_denial_is_recognised(quote):
    assert _denies(quote) is True


def test_the_broad_negation_cue_would_have_been_unsafe_here():
    """Documents WHY the two sides differ, with the measurement that decided it.
    If someone later swaps the narrow pattern for the broad one, this fails and
    tells them how many correct answers it would cost."""
    wrongly_rejected = [
        q for q in AFFIRMATIVE_QUOTES if ps._quote_expresses_negative(q)
    ]
    assert len(wrongly_rejected) >= 5, (
        "the broad cue no longer over-fires on affirmative quotes; re-measure "
        "before assuming the two sides can be unified"
    )
    # ...and the narrow one costs nothing.
    assert not [q for q in AFFIRMATIVE_QUOTES if _denies(q)]


def test_the_no_side_still_uses_the_broad_cue():
    """The "No" side must keep its generous cue - its failure mode is a blank,
    and a genuine denial is phrased a hundred ways."""
    assert ps._quote_expresses_negative("The applicant has no prior cancellations")
    assert ps._quote_expresses_negative("No vehicles are owned or leased")
    assert ps._quote_expresses_negative("loss-free for five years")


# ── An exclusion title is not evidence an event happened ─────────────────────

EXCLUSION_TITLES = [
    "BROAD ABUSE OR MOLESTATION EXCLUSION",
    "Cyber Incident and Data Privacy Exclusion",
    "Employment-Related Practices Exclusion",
    "ASBESTOS EXCLUSION",
    "Total Pollution Exclusion.",
]

REAL_EVENT_QUOTES = [
    "The applicant had a molestation claim in 2023; an exclusion was added at renewal",
    "A discrimination suit was settled in 2022",
    "Prior negligent hiring claim paid $45,000",
    "Applicant reports one abuse allegation in the past five years",
    "Coverage is subject to the exclusions listed in form CG0001",
]


@pytest.mark.parametrize("quote", EXCLUSION_TITLES)
def test_an_exclusion_title_cannot_ground_a_yes(quote):
    """FOUND ON A REAL RUN. ACORD 125 Question 6 ("any past losses or claims
    relating to sexual abuse or molestation allegations...?") came back "Y",
    grounded on "BROAD ABUSE OR MOLESTATION EXCLUSION" - a form title lifted off
    the policy. An exclusion is the policy DECLINING to cover a thing; it is
    never evidence the thing happened."""
    assert ps._EXCLUSION_TITLE_RE.match(quote) is not None


@pytest.mark.parametrize("quote", REAL_EVENT_QUOTES)
def test_a_real_event_that_mentions_an_exclusion_still_counts(quote):
    """Deliberately NOT "contains the word exclusion". A genuine Yes may mention
    one; only a quote that IS a title is rejected."""
    assert ps._EXCLUSION_TITLE_RE.match(quote) is None


def test_the_gate_reads_the_shared_pattern_not_a_copy():
    """One rule, one definition. Two copies of a regex drifting apart is how the
    auto-symbol defect survived."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    assert "_COVERAGE_DENIAL_RE.search" in src
    # ...and it is the one extraction owns.
    from services import extraction_service as es
    assert ps._COVERAGE_DENIAL_RE is es._COVERAGE_DENIAL_RE


def test_denial_check_only_applies_to_affirmative_answers():
    """A "No" answer whose quote says "no coverage" is CORRECT and must not be
    caught by this - the new condition is guarded on `not negative`."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    idx = src.index("_COVERAGE_DENIAL_RE.search")
    window = src[max(0, idx - 200):idx]
    assert "not negative" in window, (
        "the denial check must be scoped to affirmative answers only"
    )
