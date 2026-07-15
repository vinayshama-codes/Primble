"""
Regression tests for ACORD 125 page-3 General Information (Yes/No) questions.

Product decision (this session): these compliance questions
(CommercialPolicy_Question_*Code_*: subsidiaries, foreclosure/bankruptcy, arson,
abuse/discrimination claims, foreign operations, ...) are NOT treated as required
fields on the form, so an empty one must NOT be forced to missing_required /
yellow. 16 yellow compliance boxes made a generated form read as alarmingly
incomplete when most of these are edge-case questions.

They are still surfaced for the broker: an empty one is picked up by
field_qa's "not_answered" review item and listed in the pre-download modal -
just without a PDF highlight. These tests lock in BOTH halves of that decision
(no yellow on the form + still visible in review) so neither regresses.

Run from backend/:
    python -m pytest tests/test_acord125_compliance_questions.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import apply_acord125_missing_field_highlights  # noqa: E402
from services.field_qa import run_field_qa  # noqa: E402

_Q = "CommercialPolicy_Question_AADCode_A"   # "any past abuse/discrimination claims?"
_Q2 = "CommercialPolicy_Question_KABCode_A"  # "any fraud/bribery/arson conviction?"


def _apply(field_state, confidence, form_id="ACORD_125"):
    return apply_acord125_missing_field_highlights(form_id, {}, field_state, dict(confidence))


def test_empty_compliance_question_is_not_forced_yellow():
    # The whole point of the revert: an empty page-3 question stays low_confidence
    # (no highlight), it is NOT promoted to missing_required (yellow).
    out = _apply({}, {_Q: "low_confidence", _Q2: "low_confidence"})
    assert out[_Q] == "low_confidence"
    assert out[_Q2] == "low_confidence"


def test_empty_compliance_question_still_surfaces_in_field_qa():
    # No yellow on the form, but still visible: field_qa flags the blank as a
    # 'not_answered' review item so the broker sees it in the pre-download modal.
    gen = {"ACORD_125": {"confidence": {_Q: "low_confidence"}, "mapped": {}, "schema": {}}}
    r = run_field_qa(gen, merged_facts={})
    assert r["review_count"] == 1
    assert r["results"][0]["reason_code"] == "not_answered"
    assert r["results"][0]["field"] == _Q


def test_answered_compliance_question_is_untouched():
    # An answered "No"/"Yes" is a real value -> stays low_confidence (pink for
    # review), never promoted to yellow.
    assert _apply({_Q: "No"}, {_Q: "low_confidence"})[_Q] == "low_confidence"
    assert _apply({_Q: "Yes"}, {_Q: "low_confidence"})[_Q] == "low_confidence"


def test_core_required_field_still_yellow():
    # Guard: the revert must NOT have touched the groups we DO keep yellow.
    # A missing core-required field (named insured name) still paints yellow.
    out = _apply({}, {"NamedInsured_FullName_A": "low_confidence"})
    assert out["NamedInsured_FullName_A"] == "missing_required"


# ── Evidence-gate "proof of NO" contract (Figure 30) ──────────────────────────
# The gate keeps a "No" answer only when the model's grounding quote is both
# PRESENT in the document AND expresses a negative. This is the contract the
# prompt relies on: a Q&A answer ("Are any vehicles leased to others? No") is
# valid proof BECAUSE it carries the "No" word. These lock that in so a future
# gate change can't start dropping properly-grounded answers, and can't start
# accepting a bogus "No" cited from an unrelated positive sentence.

from services.pdf_service import (  # noqa: E402
    _normalize_for_search, _quote_grounds_claim, _quote_expresses_negative,
)

_DOC = (
    "ARE ANY VEHICLES LEASED TO OTHERS? No\n"
    "DO OPERATIONS INVOLVE TRANSPORTING HAZARDOUS MATERIAL? No\n"
    "IS THERE A VEHICLE MAINTENANCE PROGRAM IN OPERATION? Yes. "
    "All vehicles are serviced quarterly by an in-house mechanic."
)
_HAY = _normalize_for_search(_DOC)


def _no_is_kept(quote: str) -> bool:
    """Mirror the gate's negative branch: grounded AND expresses a negative."""
    return _quote_grounds_claim(quote, _HAY) and _quote_expresses_negative(quote)


def test_qa_no_with_answer_word_is_kept():
    # Q&A answer that INCLUDES the "No" -> valid proof, kept.
    assert _no_is_kept("Are any vehicles leased to others? No") is True
    assert _no_is_kept("Do operations involve transporting hazardous material? No") is True


def test_question_without_answer_word_is_not_proof():
    # The old failure mode: citing the question WITHOUT its "No" is not proof.
    assert _no_is_kept("Are any vehicles leased to others?") is False


def test_bogus_no_from_unrelated_positive_sentence_is_rejected():
    # Safety property: a positive descriptive sentence is never proof of a "No".
    assert _no_is_kept("All vehicles are serviced quarterly by an in-house mechanic") is False
