"""Loss-history cards must post their answer to the fact that actually moves them.

2026-08-17, measured on a live session: every loss recommendation carried a
hardcoded `field: "loss_history_years"`. The card asking the producer to CONFIRM
No Known Losses therefore wrote the attestation into a year COUNT. The producer
typed "no losses", `_to_int` read it as 0, the pillar fell through to "No loss
history provided" (25), the card came straight back and the score never moved.

The answer was correct. It was delivered to the wrong field.

These tests drive the real code with the producer's literal value.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services import sqs_service as sq
from services.sqs_service import (
    _LOSS_RECOMMENDATION_FIELDS,
    calculate_p4_loss_history,
    loss_recommendation_field,
)


# ── The reported defect ───────────────────────────────────────────────────────

def test_the_no_known_losses_card_targets_the_attestation_not_a_year_count():
    """The client's literal case. Must never regress."""
    _, recs = calculate_p4_loss_history({}, {"narrative_states_no_losses": True})
    assert recs, "the narrative-stated state must emit a recommendation"
    msg = recs[0]
    assert "No Known Losses (stated in narrative)" in msg
    assert loss_recommendation_field(msg) == "loss_history_no_prior_losses_indicator"
    assert loss_recommendation_field(msg) != "loss_history_years"


def test_confirming_no_known_losses_actually_moves_the_pillar():
    """40 -> 60, via the field the card now targets. This is the whole point.
    (Narrative-only is 40 since C2 2.5; it was 45 before 2026-08-24.)"""
    before, _ = calculate_p4_loss_history({}, {"narrative_states_no_losses": True})
    assert before == 40

    field = loss_recommendation_field(
        "No Known Losses (stated in narrative) - confirm with the insured, or "
        "attach loss runs or a signed no-known-loss letter to corroborate the "
        "statement"
    )
    after, _ = calculate_p4_loss_history(
        {field: {"value": "no losses", "confidence": "filled", "source": "producer"}},
        {"narrative_states_no_losses": True},
    )
    assert after == 60, "the producer's confirmation must raise the pillar"


def test_the_old_field_still_moves_nothing_which_is_why_it_was_wrong():
    """Pins the mechanism, so nobody 'simplifies' the routing back."""
    after, _ = calculate_p4_loss_history(
        {"loss_history_years": {"value": "no losses", "source": "producer"}},
        {"narrative_states_no_losses": True},
    )
    assert after == 40, "writing the attestation into a year count changes nothing"


def test_no_loss_history_at_all_is_answerable_by_attesting():
    _, recs = calculate_p4_loss_history({}, {})
    assert recs[0] == "No loss history provided - required for carrier submission"
    assert loss_recommendation_field(recs[0]) == "loss_history_no_prior_losses_indicator"
    # C2 2.2: the nothing-provided state also offers the producer the New
    # Venture confirmation, routed to the fact that drives the N/A.
    _nv = [r for r in recs if "new venture" in r.lower()]
    assert _nv and loss_recommendation_field(_nv[0]) == "new_venture_indicator"


# ── Routing correctness for the rest of the vocabulary ────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("Prior carrier name missing - add carrier details to strengthen the loss "
     "history record", "prior_carrier"),
    ("Loss run insured name does not match - verify these runs belong to this "
     "submission", "applicant_name"),
    ("Loss run ownership partially verified - name and address match but "
     "FEIN/policy number not confirmed", "fein"),
    ("3 years of loss runs provided - 5 years preferred for full credit",
     "loss_history_years"),
    ("Loss history incomplete - fewer than 3 years provided", "loss_history_years"),
    ("Loss runs requested / pending - update score when received", None),
    ("Loss runs appear stale (372 days old). Updated loss runs may be required "
     "before bind.", None),
])
def test_each_message_routes_to_the_fact_that_answers_it(message, expected):
    assert loss_recommendation_field(message) == expected


def test_a_varying_number_cannot_fork_a_row():
    """Same template, different age - same routing (the _loss_rec_id lesson)."""
    a = "Loss runs appear stale (91 days old). Updated loss runs may be required before bind."
    b = "Loss runs appear stale (912 days old). Updated loss runs may be required before bind."
    assert loss_recommendation_field(a) == loss_recommendation_field(b)


def test_an_unknown_message_is_never_guessed_into_a_field():
    assert loss_recommendation_field("something nobody has written yet") is None
    assert loss_recommendation_field("") is None
    assert loss_recommendation_field(None) is None


# ── Anti-rot: the table must cover everything the pillar can emit ─────────────

def _harvest_every_loss_message() -> set:
    """Every string calculate_p4_loss_history can produce.

    Driven, not read: the branches are mutually exclusive, so a static scan
    would under-cover and the coverage test below would pass vacuously - the
    trap the legacy-rules harvester documents.
    """
    seen: set = set()
    stale = {"loss_run_valuation_date": "2020-01-01"}
    scenarios = [
        ({}, {}, False, "no_loss_run"),
        ({}, {"no_prior_losses": True}, False, "no_loss_run"),
        ({}, {"narrative_states_no_losses": True}, False, "no_loss_run"),
        ({"loss_run_status": "pending"}, {}, False, "no_loss_run"),
        ({"loss_history_years": 5}, {}, True, "strong"),
        ({"loss_history_years": 3}, {}, True, "strong"),
        ({"loss_history_years": 1}, {}, True, "strong"),
        ({}, {}, True, "strong"),
        ({}, {}, True, "moderate"),
        ({}, {}, True, "possible"),
        ({}, {}, True, "no_match"),
        ({}, {}, True, "no_loss_run"),
        ({"prior_carrier": "EMC"}, {}, True, "moderate"),
        (dict(stale), {}, True, "moderate"),
        ({"loss_run_status": "pending"}, {}, True, "no_loss_run"),
        # conflict: an attestation contradicted by real claims
        ({"num_claims": 3, "total_incurred": 50000}, {"no_prior_losses": True},
         True, "strong"),
    ]
    for facts, flags, has_doc, match in scenarios:
        _, recs = calculate_p4_loss_history(
            facts, flags, has_loss_run_doc=has_doc, loss_run_match=match)
        seen.update(recs)
    return seen


def test_the_harvester_actually_harvests():
    """An empty harvest would make the coverage test below pass vacuously."""
    msgs = _harvest_every_loss_message()
    assert len(msgs) >= 10, f"harvest looks broken - only got {len(msgs)}: {msgs}"


def test_every_loss_message_maps_to_a_row_in_the_table():
    """A new message with no row would silently become an unanswerable card."""
    unmapped = [
        m for m in _harvest_every_loss_message()
        if not any(p in m.lower() for p, _ in _LOSS_RECOMMENDATION_FIELDS)
    ]
    assert not unmapped, (
        "these loss recommendations match no row in _LOSS_RECOMMENDATION_FIELDS, "
        f"so they carry no field and can only be waived: {unmapped}"
    )


def test_no_row_is_shadowed_by_an_earlier_one():
    """First match wins, so a broader phrase above a narrower one is a bug."""
    phrases = [p for p, _ in _LOSS_RECOMMENDATION_FIELDS]
    for i, later in enumerate(phrases):
        for earlier in phrases[:i]:
            assert earlier not in later, (
                f"'{earlier}' sits above '{later}' and swallows it - "
                "reorder _LOSS_RECOMMENDATION_FIELDS"
            )


def test_every_routed_field_is_actually_writable():
    """A field the answer path cannot write is worse than no field at all:
    the card offers a text box that can never close the gap."""
    from services.arq_service import _canonical_key
    for phrase, field in _LOSS_RECOMMENDATION_FIELDS:
        if field is None:
            continue
        assert _canonical_key(field) == field, (
            f"'{phrase}' routes to '{field}', which apply_producer_answer_to_"
            f"session cannot resolve to a canonical fact"
        )


def test_the_attestation_field_is_the_one_the_flag_derivation_watches():
    """Routing and flag-setting must name the SAME fact or the pillar still
    will not move - the two halves of this fix are coupled."""
    from services.arq_service import NO_LOSS_INDICATOR_FIELD
    assert loss_recommendation_field(
        "No Known Losses (stated in narrative) - confirm with the insured"
    ) == NO_LOSS_INDICATOR_FIELD


# ── The scorer must carry the routed field onto the recommendation ────────────

def test_the_per_form_scorer_stamps_the_routed_field_not_a_constant():
    recs = []
    for msg in _harvest_every_loss_message():
        recs.append({
            "field": loss_recommendation_field(msg),
            "message": msg,
        })
    fields = {r["field"] for r in recs}
    assert fields != {"loss_history_years"}, (
        "every loss card still carries the same hardcoded field - the defect"
    )
    assert "loss_history_no_prior_losses_indicator" in fields


def test_source_has_no_hardcoded_loss_field_left():
    """Grep guard: the constant must not creep back into the scorer."""
    import inspect
    src = inspect.getsource(sq)
    marker = '"field": "loss_history_years"'
    assert marker not in src, (
        f'{marker} is back in sqs_service - route through '
        'loss_recommendation_field() instead'
    )


# ── Second half: text must not be accepted into a number field ───────────────

def _validate(field, answer):
    from routes.audit_routes import _validate_producer_answer
    return _validate_producer_answer(field, answer)


def test_words_are_rejected_from_a_year_count():
    """The literal reported value. It used to sail through and become 0."""
    ok, msg = _validate("loss_history_years", "no losses")
    assert ok is False
    assert msg, "a rejection must tell the producer what was expected"


@pytest.mark.parametrize("field,bad", [
    ("loss_history_years", "five"),
    ("loss_history_years", "no losses"),
    ("num_claims", "none"),
    ("fein", "no losses"),
])
def test_type_mismatches_are_refused(field, bad):
    ok, _ = _validate(field, bad)
    assert ok is False, f"{field} should not accept {bad!r}"


@pytest.mark.parametrize("field,good", [
    ("loss_history_years", "5"),
    ("num_claims", "0"),
    ("num_claims", "3"),
    ("fein", "84-2210987"),
    ("applicant_name", "ORBIN CONTRACTING LLC"),
    ("prior_carrier", "EMPLOYERS MUTUAL CASUALTY COMPANY"),
])
def test_real_answers_still_pass(field, good):
    ok, msg = _validate(field, good)
    assert ok is True, f"{field}={good!r} was refused: {msg}"


def test_the_documented_leniency_branches_are_untouched():
    """Monetary boxes legitimately hold words - that allowance must survive."""
    for text in ("Not covered", "Waived", "Statutory", "See schedule"):
        ok, _ = _validate("gl_deductible", text)
        assert ok is True, f"monetary leniency broke on {text!r}"
    ok, _ = _validate("gl_deductible", "1,000")
    assert ok is True
    # validate_monetary strips formatting before parsing, so it only refuses a
    # value that is structurally impossible as a number. Deliberate (see the
    # docstring) and unchanged by this fix - pinned so a future tightening of
    # the monetary branch is a decision, not a side effect.
    ok, _ = _validate("gl_deductible", "12.34.56")
    assert ok is False, "a structurally malformed number must still be refused"


def test_a_field_with_no_declared_validator_is_still_accepted():
    """Permissive by default - we only reject what a fact declares invalid."""
    ok, _ = _validate("some_field_nobody_registered", "anything at all")
    assert ok is True


def test_a_broken_validator_never_blocks_a_real_answer():
    import routes.audit_routes as ar
    original = ar._registry_entry
    try:
        ar._registry_entry = lambda f: {
            "validate": (lambda v: (_ for _ in ()).throw(RuntimeError("boom"))),
            "format_hint": "x",
        }
        ok, _ = _validate("loss_history_years", "5")
        assert ok is True
    finally:
        ar._registry_entry = original
