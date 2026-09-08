"""
A document denying it has something is not evidence that it does (live 2026-09-08).

THE DEFECT
----------
A commercial application whose closing line read

    "Loss runs have not been attached to this submission."

classified as a LOSS RUN, high confidence - `loss_run 10.0` against
`application 4.5` - because `_content_scores` asked only `kw in tl` and the
literal phrase "loss runs" is worth 3.0. Downstream: `has_loss_run_doc` True,
the Loss History pillar took the runs-uploaded path (checked BEFORE the
attestation branch, correctly), scored 60 instead of 40, and emitted two
recommendations about a document that does not exist.

THE CLIENT HAS RULED ON THIS AXIS
---------------------------------
* Principle 3, *"Missing Does Not Mean No"* - *"distinguish between information
  that is actually negative and information that simply was not found."*
* The 1 Sep handoff - *"a narrative stating no losses, a client confirming no
  losses, and CARRIER LOSS RUNS NOT BEING PROVIDED are different evidence states
  and should not be collapsed into the same result."*

Reading "not provided" as "provided" does not collapse that state; it inverts it.

THE ADVERSARIAL CASE DECIDED THE DESIGN, AND IT WAS WRITTEN FIRST
-----------------------------------------------------------------
ACORD 25 prints its own denial in boilerplate on every certificate ever issued:

    "THIS CERTIFICATE OF INSURANCE DOES NOT CONSTITUTE A CONTRACT ..."

A rule that deleted any keyword appearing in a negated clause would stop every
certificate from classifying as one - far worse than the bug. So the rule is
**a phrase counts when at least one of its occurrences is not denied**. The
certificate's title is an ordinary mention; the application mentions "loss runs"
once and denies it.

`test_the_rule_can_only_ever_lower_a_score` is the safety property: the change
can cost a match, it can never invent one.

Run from backend/:
    python -m pytest tests/test_denied_keywords_do_not_classify.py -v
"""

import os
import random
import string
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.extraction_service import (  # noqa: E402
    DOC_TYPE_KEYWORDS,
    _content_scores,
    _phrase_counts,
    classify_document,
)

APP_HEAD = ("ACORD 125 - COMMERCIAL INSURANCE APPLICATION. Application for Insurance. "
            "Named Insured: Kirkbride Dry Cleaner Company. FEIN 27-4244106. ")


def _type(text, filename=None):
    return classify_document(text, filename)["doc_type"]


def _score(text, doc_type):
    return _content_scores(text.lower()).get(doc_type, 0.0)


# ── 1. The reported case ─────────────────────────────────────────────────────

def test_an_application_denying_loss_runs_is_not_a_loss_run():
    text = APP_HEAD + "LOSS HISTORY. Loss runs have not been attached to this submission."
    assert _type(text, "submission.pdf") == "application"


@pytest.mark.parametrize("denial", [
    "Loss runs have not been attached to this submission.",
    "Loss runs were not provided with this application.",
    "Loss runs are not available for this account.",
    "Loss runs: not attached.",
    "Loss runs not attached.",
    "There are no loss runs on file for this account.",
    "This submission is without loss runs.",
    "The producer has never received loss runs for this insured.",
])
def test_every_way_of_denying_it_reads_as_a_denial(denial):
    assert _score(APP_HEAD + denial, "loss_run") < 3.0, denial


# ── 2. THE ADVERSARIAL CASE - real documents must survive ────────────────────

def test_acord25_boilerplate_still_classifies_as_a_certificate():
    """ACORD 25 denies itself in print on every certificate ever issued. A rule
    that stripped keywords from negated clauses would break all of them."""
    text = (
        "CERTIFICATE OF LIABILITY INSURANCE\n"
        "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY AND CONFERS NO "
        "RIGHTS UPON THE CERTIFICATE HOLDER. THIS CERTIFICATE OF INSURANCE DOES NOT "
        "CONSTITUTE A CONTRACT BETWEEN THE ISSUING INSURER(S), AUTHORIZED "
        "REPRESENTATIVE OR PRODUCER, AND THE CERTIFICATE HOLDER.\n"
        "THIS IS TO CERTIFY THAT THE POLICIES OF INSURANCE LISTED BELOW HAVE BEEN "
        "ISSUED TO THE INSURED NAMED ABOVE.\n"
        "CERTIFICATE HOLDER: Kestrel Terminal Authority"
    )
    assert _type(text) == "certificate"


def test_a_genuine_loss_run_with_claims_is_untouched():
    text = ("LOSS RUN. Claim number 88213. Date of loss 03/14/2024. "
            "Paid losses $12,000. Claimant: J Doe. Reserve $0. "
            "No injuries reported on this claim.")
    assert _type(text) == "loss_run"


def test_a_genuine_loss_run_for_a_clean_account_is_untouched():
    """The dangerous direction: a REAL loss run that reports no claims. Its
    title is an ordinary mention, so it still scores."""
    text = ("LOSS RUN REPORT. Insured: Kirkbride Dry Cleaner Company. "
            "Valuation date 09/01/2026. Date of loss: none. Paid losses: $0. "
            "No claims were reported during this period.")
    assert _type(text) == "loss_run"


@pytest.mark.parametrize("text,expect", [
    ("POLICY DECLARATIONS. Declarations page. Policy period 01/01/2026 to 01/01/2027. "
     "Named insured: X. Policy number BBC7263.", "dec_page"),
    ("COMMERCIAL INSURANCE APPLICATION. Application for insurance. "
     "Please provide loss runs for the past five years.", "application"),
    ("STATEMENT OF VALUES. Schedule of values. Building value $1,200,000.", "sov"),
])
def test_other_document_types_are_unaffected(text, expect):
    assert _type(text) == expect


def test_a_positive_mention_still_scores():
    assert _score("Loss runs attached for the past five years.", "loss_run") >= 3.0


@pytest.mark.parametrize("text,kw", [
    ("Policy No. 12345 - Loss Run Report", "loss run"),
    ("Claim No. 88213 loss run", "loss run"),
    ("Certificate No. 4471 certificate of insurance", "certificate of insurance"),
])
def test_no_as_an_abbreviation_for_number_is_not_a_negation(text, kw):
    """Found while implementing, not by a report. "Policy No. 12345" puts the
    token "no" two words before the phrase on documents we handle every day -
    a dec page, a loss run header, a certificate. A real denial never has a bare
    figure as its object."""
    assert _phrase_counts(text.lower(), kw) is True


# ── 3. THE SAFETY PROPERTY - it can cost a match, never invent one ───────────

def _score_without_the_rule(tl, doc_type):
    """The pre-fix scorer, reimplemented here on purpose: this is the BASELINE
    the new rule must never exceed, so a local copy is the point."""
    return sum(w for kw, w in DOC_TYPE_KEYWORDS[doc_type] if kw in tl)


def test_the_rule_can_only_ever_lower_a_score():
    """Over 3,000 random texts built from the real keyword vocabulary mixed with
    negations, every doc type's score is <= what the old presence test gave."""
    rng = random.Random(20260908)
    vocab = sorted({kw for kws in DOC_TYPE_KEYWORDS.values() for kw, _w in kws})
    joiners = [". ", ", ", " and ", "\n", "; ", ": ", " - "]
    negs = ["no ", "not ", "without ", "there is no ", "there are no ",
            "", "", "", "the ", "this "]
    tails = [" have not been attached", " is not included", " was not provided",
             " attached", " listed below", " for the period", "", "", ""]
    for _ in range(3000):
        parts = []
        for _p in range(rng.randint(1, 8)):
            parts.append(rng.choice(negs) + rng.choice(vocab) + rng.choice(tails))
        tl = rng.choice(joiners).join(parts).lower()
        new = _content_scores(tl)
        for doc_type in DOC_TYPE_KEYWORDS:
            assert new[doc_type] <= _score_without_the_rule(tl, doc_type) + 1e-9, tl


def test_a_phrase_that_is_absent_stays_absent():
    for kw in ("loss run", "certificate of insurance", "declarations page"):
        assert _phrase_counts("nothing relevant here at all", kw) is False


def test_a_dense_document_keeps_its_keyword_whatever_the_grammar():
    """The occurrence cap fails toward today's behaviour: at that density the
    document is about the thing however each sentence is phrased."""
    tl = ("there is no loss run here. " * 400).lower()
    assert _phrase_counts(tl, "loss run") is True


# ── 4. Totality ──────────────────────────────────────────────────────────────

def test_fuzz_never_raises_on_arbitrary_text():
    rng = random.Random(11)
    pool = list(string.printable) + ["loss run", "not", "no", "certificate", "\x00", "é"]
    for _ in range(2000):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 200)))
        try:
            classify_document(text, rng.choice([None, "a.pdf", "loss run.pdf"]))
        except Exception as exc:                                # noqa: BLE001
            pytest.fail(f"raised on {text!r}: {exc}")


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "."])
def test_empty_input_is_safe(text):
    assert isinstance(classify_document(text), dict)
