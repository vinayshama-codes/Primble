"""The date resolver is umbrella-aware, and no resolution trades silently.

OWNER (2026-08-14), verbatim: "The date resolver should be umbrella-aware -
entering an expiration that misaligns with the umbrella's 07/15/2026 should tell
you so in the modal, instead of silently trading one issue for another. That's
the loop you've been stuck in."

THE LOOP, measured on the live ORBIN package: `legacy_policy_term_expired`
offered exactly two inputs, effective and expiration. The umbrella carries its
OWN printed period (07/15/2026). Typing any other expiration cleared the expired
term and immediately raised `umbrella_gl_expiration_misaligned` - a different
issue, in a different column, with no connection drawn between them. Fix one,
another appears; fix that, the first returns.

TWO HALVES, and both are needed:

1. `umbrella_expiration_date` is a third, OPTIONAL input on both term rows. The
   modal pre-fills every fact it renders, so the umbrella's date is now VISIBLE
   beside the date being changed - the conflict is legible before it is caused.
   It submits only the facts actually TOUCHED, so leaving the box alone behaves
   exactly as it did before this change.

2. The resolve endpoint reports what a value RAISED. Scoped to issues the
   applied fact is a DECLARED remedy for (RESOLUTION_MAP - the same table that
   decides which inputs the modal renders), never by matching words in the
   message. Generic: any future rule listing a fact as one of its remedies is
   covered the day it is added.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from routes.audit_routes import _issues_bound_to_fact, _trade_off_note  # noqa: E402
from services.issue_registry import resolution_for                      # noqa: E402

AUDIT = open(os.path.join(os.path.dirname(__file__), "..", "routes",
                          "audit_routes.py"), encoding="utf-8").read()

# The live strings, verbatim - a fix can pass every synthetic test and still
# miss the reported case.
_EXPIRED = ("Policy term already expired (07/15/26) - the application proposes "
            "a period that ended. Fix: Update the proposed effective and "
            "expiration dates to the term being applied for.")
_UMB_CODED = ("Umbrella expiration date (07/15/2026) does not match GL/policy "
              "expiration date (09/15/26). Periods must align or be explained "
              "via ACORD 101.")
_UMB_LEGACY = ("Umbrella and GL expiration dates misaligned. "
               "Fix: Review and correct this before proceeding.")


# ── 1. The umbrella date is on the modal ────────────────────────────────────

@pytest.mark.parametrize("code", ["legacy_policy_term_expired",
                                  "legacy_policy_term_expiring"])
def test_both_term_rules_offer_the_umbrella_expiration(code):
    """`_expiring` is the same modal with the same trade - fixing only the
    reported half would leave the identical trap one rule over."""
    facts = (resolution_for(code) or {}).get("facts") or []
    assert "umbrella_expiration_date" in facts


@pytest.mark.parametrize("code", ["legacy_policy_term_expired",
                                  "legacy_policy_term_expiring"])
def test_the_original_two_inputs_are_unchanged_and_still_first(code):
    """The umbrella box is ADDITIVE. The modal autofocuses facts[0] and renders
    in order, so prepending it would move the cursor off the date the producer
    opened the modal to fix."""
    facts = (resolution_for(code) or {}).get("facts") or []
    assert facts[:2] == ["effective_date", "expiration_date"]


def test_the_umbrella_fact_is_writable_through_the_producer_path():
    """`mode: field` requires every fact to resolve through
    arq_service._canonical_key or the modal renders a box that cannot save."""
    from services.arq_service import _canonical_key
    assert _canonical_key("umbrella_expiration_date")


def test_the_umbrella_fact_was_already_proven_by_the_coded_twin():
    """It is not a new capability - the coded rule for the very issue this
    change surfaces has offered the same input all along."""
    facts = (resolution_for("umbrella_gl_expiration_misaligned") or {}).get("facts") or []
    assert facts == ["umbrella_expiration_date", "expiration_date"]


# ── 2. Binding: which issues does THIS fact answer for? ─────────────────────

def test_the_coded_umbrella_issue_binds_to_the_expiration_date():
    """THE LIVE CASE. Applying `expiration_date` must be able to see that it is
    a declared remedy for the umbrella misalignment."""
    found = _issues_bound_to_fact(
        {"cross_issues_last": [{"code": "umbrella_gl_expiration_misaligned",
                                "type": "hard_stop", "message": _UMB_CODED}]},
        "expiration_date",
    )
    assert _UMB_CODED in found
    assert "umbrella_expiration_date" in found[_UMB_CODED]


def test_a_plain_legacy_string_binds_through_classify_legacy():
    """The stop arrays hold bare sentences with no code attached. Classifying
    them is the only way this reaches the legacy engine's half of the pair."""
    found = _issues_bound_to_fact({"soft_stops": [_UMB_LEGACY]}, "expiration_date")
    assert _UMB_LEGACY in found


def test_an_unrelated_fact_binds_to_nothing():
    """The scope is what stops this from crying wolf on ordinary recompute
    churn - the stop arrays are rebuilt from scratch on every recalculation."""
    assert _issues_bound_to_fact(
        {"hard_stops": [_EXPIRED], "soft_stops": [_UMB_LEGACY]},
        "num_employees",
    ) == {}


def test_an_unclassifiable_message_is_ignored_not_crashed():
    assert _issues_bound_to_fact(
        {"soft_stops": ["", "   ", "a sentence no rule ever emits"]},
        "expiration_date",
    ) == {}


def test_the_same_problem_from_both_engines_is_not_double_counted():
    """Identity is the message, so the coded and legacy copies of one problem
    each get one row - but two DIFFERENT messages both stay."""
    found = _issues_bound_to_fact(
        {"soft_stops": [_UMB_LEGACY, _UMB_LEGACY],
         "cross_issues_last": [{"code": "umbrella_gl_expiration_misaligned",
                                "message": _UMB_CODED}]},
        "expiration_date",
    )
    assert len(found) == 2


# ── 3. The note: says what was raised, and how to settle it here ────────────

def test_nothing_introduced_means_no_note():
    """Silence is the normal outcome. A note on every resolve is noise."""
    assert _trade_off_note({}, ["effective_date", "expiration_date"], "expiration_date") == ""


def test_the_note_names_the_issue_that_was_raised():
    note = _trade_off_note({_UMB_CODED: ["umbrella_expiration_date", "expiration_date"]},
                           ["effective_date", "expiration_date", "umbrella_expiration_date"],
                           "expiration_date")
    assert "07/15/2026" in note and "09/15/26" in note


def test_the_note_points_at_the_input_already_on_screen():
    """The whole point: the remedy is one box away, so say so rather than
    sending the producer back to the panel to start the loop again."""
    note = _trade_off_note({_UMB_CODED: ["umbrella_expiration_date", "expiration_date"]},
                           ["effective_date", "expiration_date", "umbrella_expiration_date"],
                           "expiration_date")
    assert "Umbrella Expiration Date" in note


def test_the_note_never_points_back_at_the_field_just_applied():
    """"Fill in Expiration Date above" - which they just did - is the loop in
    miniature."""
    note = _trade_off_note({_UMB_CODED: ["expiration_date"]},
                           ["effective_date", "expiration_date"], "expiration_date")
    assert "fill in" not in note.lower()


def test_a_remedy_not_on_this_modal_is_not_offered_here():
    """Suggesting an input the producer cannot see would be worse than silence."""
    note = _trade_off_note({"Some other issue": ["gl_deductible"]},
                           ["effective_date", "expiration_date"], "expiration_date")
    assert "Some other issue" in note and "fill in" not in note.lower()


def test_several_introduced_issues_are_counted_not_dumped():
    note = _trade_off_note({"A": ["x"], "B": ["y"], "C": ["z"]},
                           ["expiration_date"], "expiration_date")
    assert "and 2 more" in note


# ── 4. Wiring + anti-rot ────────────────────────────────────────────────────

def test_the_note_is_advisory_and_never_fails_the_write():
    """The value IS applied before this runs. A note failure must not turn a
    successful resolve into an error."""
    _i = AUDIT.index("_note = _trade_off_note(")
    _block = AUDIT[_i - 400:_i + 400]
    assert "except Exception" in _block
    assert "non-fatal" in _block


def test_the_note_is_returned_to_the_modal():
    assert '"note":                     _note,' in AUDIT


def test_the_snapshot_is_taken_before_the_write():
    """After-only cannot tell "your value raised this" from "this was already
    open", which is exactly the distinction the producer needs."""
    assert AUDIT.index("_before = _issues_bound_to_fact(") < \
           AUDIT.index("applied, _ = await apply_producer_answer_to_session(")


def test_the_binding_comes_from_the_resolution_map_not_from_words():
    """ANTI-ROT: keyword matching against message text is the heuristic this
    codebase has rejected three times. It must not reappear here."""
    _i = AUDIT.index("def _issues_bound_to_fact")
    _block = AUDIT[_i:AUDIT.index("def _trade_off_note")]
    _code = "\n".join(l for l in _block.splitlines() if not l.strip().startswith("#"))
    assert "resolution_for" in _code
    assert "umbrella" not in _code.lower(), "the note must stay rule-agnostic"


def test_the_resolve_refresh_shows_hard_stops_as_hard_stops():
    """C75 LEAK: form_routes.py was fixed so the display reads the same arrays
    the scorer reads. THIS route kept the old shape, so resolving anything
    silently flipped severity back to 'warning' on the refreshed panel."""
    assert "_fs_soft = list(sess.get(\"soft_stops\") or []) + list(_warning_stops)" not in AUDIT
    assert "_can_proceed_warn, _, _warning_stops = classify_stops(" in AUDIT


def test_the_proceed_anyway_data_survives_that_fix():
    """`classify_stops` still decides whether the producer MAY proceed - it just
    no longer decides what they SEE. Emptying it would delete a live feature."""
    assert '"warning_stops":            _warning_stops,' in AUDIT
    assert '"can_proceed_with_warning": _can_proceed_warn,' in AUDIT
