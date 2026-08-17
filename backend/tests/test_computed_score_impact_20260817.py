"""A recommendation must state what it is really worth, not a typed constant.

Client, 2026-08-17: "The UI currently tells the user that confirming No Known
Losses can improve SQS by up to +8 points. Based on the documented formula,
moving Loss History from 45 to 60 appears to contribute approximately +2.25 raw
SQS points."

He was right. Every score_impact was a literal, and all loss cards shared one, so
the same card promised 8 whether it was worth 2.25 or 5.25.

These drive the real scorer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services import sqs_service as sq
from services.sqs_service import (
    SPEC_PILLAR_WEIGHTS,
    _MAX_IMPACT_SIMULATIONS,
    _measure_recommendation_impacts,
    _pillar_headroom,
    calculate_sqs,
    producer_fields_exempt,
)


def _score(facts, flags=None, form_id="ACORD_125", **kw):
    return calculate_sqs(
        facts=facts, flags=flags or {}, mapped_data={}, form_schema={},
        selected_form_ids=[form_id], hard_stops=[], soft_stops=[],
        tier2_score=50, form_id=form_id, **kw)


def _rec(result, field):
    for r in result.get("recommendations") or []:
        if r.get("field") == field:
            return r
    return None


# ── The client's reconciliation ──────────────────────────────────────────────

def test_the_loss_card_no_longer_promises_a_flat_eight():
    r = _rec(_score({}, {}), "loss_history_no_prior_losses_indicator")
    assert r is not None, "the loss card must still be raised"
    assert r["score_impact"] != 8, "still the hand-typed constant"
    assert 0 < r["score_impact"] <= 15, "must sit inside the pillar's own ceiling"


def test_the_same_card_is_worth_less_from_a_better_starting_point():
    """25 -> 60 is a bigger gain than 45 -> 60. The old constant said 8 for both."""
    nothing = _rec(_score({}, {}), "loss_history_no_prior_losses_indicator")
    stated  = _rec(_score({}, {"narrative_states_no_losses": True}),
                   "loss_history_no_prior_losses_indicator")
    assert nothing and stated
    assert stated["score_impact"] < nothing["score_impact"], (
        "a card must be worth less when the pillar has already earned part of it"
    )


def test_the_measured_number_matches_the_published_formula():
    """(target - current) x pillar weight, to the point."""
    w = SPEC_PILLAR_WEIGHTS["loss_history_alignment"]
    r = _rec(_score({}, {"narrative_states_no_losses": True}),
             "loss_history_no_prior_losses_indicator")
    assert r is not None
    assert r["score_impact"] == pytest.approx(round((60 - 45) * w), abs=1)


# ── The three refusals ───────────────────────────────────────────────────────

def test_a_card_is_never_silently_zeroed_when_the_probe_cannot_answer_it():
    recs = [{"field": "some_numeric_field", "component": "loss_history_alignment",
             "score_impact": 7}]
    out = _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 0},
        weights=SPEC_PILLAR_WEIGHTS, rescore=lambda f: 50, facts={})
    pts, exact = out[id(recs[0])]
    assert pts > 0, "a card whose probe showed no movement must keep its value"
    assert exact is False, "a fallback must not claim to be exact"


def test_a_card_can_never_promise_more_than_the_pillar_can_still_give():
    recs = [{"field": "x", "component": "narrative_quality", "score_impact": 20}]
    out = _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"narrative_quality": 90},
        weights=SPEC_PILLAR_WEIGHTS, rescore=lambda f: 50, facts={})
    pts, _ = out[id(recs[0])]
    # narrative_quality is 10% and already at 90, so at most 1 point remains.
    assert pts <= 1, f"promised {pts} from a pillar with 1 point left"


def test_a_full_pillar_promises_nothing_and_says_so():
    recs = [{"field": "x", "component": "narrative_quality", "score_impact": 20}]
    out = _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"narrative_quality": 100},
        weights=SPEC_PILLAR_WEIGHTS, rescore=lambda f: 50, facts={})
    assert out[id(recs[0])] == (0, True)


def test_a_failing_simulation_never_breaks_scoring():
    def boom(_facts):
        raise RuntimeError("scorer exploded")
    recs = [{"field": "x", "component": "loss_history_alignment", "score_impact": 9}]
    out = _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 0},
        weights=SPEC_PILLAR_WEIGHTS, rescore=boom, facts={})
    pts, exact = out[id(recs[0])]
    assert pts > 0 and exact is False


def test_a_card_with_no_answerable_field_is_never_simulated():
    """Nothing to fill, so no probe is run - the rescore must not be called."""
    called = []
    recs = [{"field": None, "component": "loss_history_alignment", "score_impact": 8}]
    _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 0},
        weights=SPEC_PILLAR_WEIGHTS,
        rescore=lambda f: called.append(1) or 99, facts={})
    assert not called, "a card with no field has nothing to probe"


def test_a_card_with_no_answerable_field_is_still_bounded():
    """It cannot be measured, but it must not overstate itself either.

    Live case 2026-08-17: once the producer attested, the follow-up card
    ("attach loss runs to fully confirm") kept its typed 8 while the pillar sat
    at 60 with 6 points left. A document-only card is the MOST likely to
    overstate, because its literal was written for the empty case.
    """
    recs = [{"field": None, "component": "loss_history_alignment", "score_impact": 8}]
    out = _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 60},
        weights=SPEC_PILLAR_WEIGHTS, rescore=lambda f: 99, facts={})
    pts, exact = out[id(recs[0])]
    assert pts == 6, f"(100-60) x 0.15 = 6 points remain, card promised {pts}"
    assert exact is False, "not measured, so it must keep the 'up to' hedge"


# ── Cost and termination ─────────────────────────────────────────────────────

def test_the_simulation_terminates():
    """The counterfactual run must not measure impacts again, or this hangs."""
    result = _score({}, {})
    assert result.get("recommendations") is not None


def test_one_run_per_distinct_field_not_per_card():
    calls = []
    recs = [
        {"field": "a", "component": "loss_history_alignment", "score_impact": 5},
        {"field": "a", "component": "loss_history_alignment", "score_impact": 5},
        {"field": "b", "component": "loss_history_alignment", "score_impact": 5},
    ]

    def counting(f):
        calls.append(1)
        return 55
    _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 0},
        weights=SPEC_PILLAR_WEIGHTS, rescore=counting, facts={})
    assert len(calls) == 2, f"expected 2 simulations for 2 distinct fields, got {len(calls)}"


def test_simulations_are_capped():
    calls = []
    recs = [{"field": f"f{i}", "component": "loss_history_alignment",
             "score_impact": 5} for i in range(_MAX_IMPACT_SIMULATIONS + 25)]

    def counting(f):
        calls.append(1)
        return 55
    _measure_recommendation_impacts(
        recs, baseline=50, breakdown={"loss_history_alignment": 0},
        weights=SPEC_PILLAR_WEIGHTS, rescore=counting, facts={})
    assert len(calls) == _MAX_IMPACT_SIMULATIONS


# ── The "up to" hedge ────────────────────────────────────────────────────────

def test_a_capped_score_keeps_the_hedge():
    """Points are earned but will not SHOW until the stop clears."""
    result = calculate_sqs(
        facts={}, flags={}, mapped_data={}, form_schema={},
        selected_form_ids=["ACORD_125"],
        hard_stops=["something is badly wrong"], soft_stops=[],
        tier2_score=50, form_id="ACORD_125")
    for r in result.get("recommendations") or []:
        if r.get("score_impact", 0) > 0:
            assert r.get("impact_is_exact") is False, (
                "a capped score must not state an exact gain"
            )


def test_headroom_helper():
    w = SPEC_PILLAR_WEIGHTS
    assert _pillar_headroom("loss_history_alignment", {"loss_history_alignment": 0}, w) \
        == pytest.approx(15.0)
    assert _pillar_headroom("loss_history_alignment", {"loss_history_alignment": 100}, w) \
        == pytest.approx(0.0)
    assert _pillar_headroom("nope", {}, w) == 0.0


# ── O9: one definition of what a dec page owes ───────────────────────────────

def test_the_dec_page_exemption_is_shared_by_both_scorers():
    """The form scorer kept its own copy of the checklist and lacked the
    exemption, so answering contact_name moved the form and not the package."""
    flags = {"_doc_type": "dec_page"}
    assert producer_fields_exempt(flags) is True
    assert producer_fields_exempt({}) is False

    facts = {"applicant_name": "ORBIN CONTRACTING LLC",
             "mailing_address": "4800 Dahlia St, Denver CO",
             "effective_date": "2026-07-15",
             "lines_of_business": ["General Liability"]}
    with_contact = dict(facts, contact_name="Erin Royal")

    a = _score(facts, flags)["breakdown"]["structural_completeness"]
    b = _score(with_contact, flags)["breakdown"]["structural_completeness"]
    assert a == b == 100, (
        "on a dec page neither scorer may dock the pillar for producer-side "
        f"details (got {a} then {b})"
    )


def test_the_exemption_does_not_leak_to_ordinary_submissions():
    facts = {"applicant_name": "ORBIN CONTRACTING LLC",
             "mailing_address": "4800 Dahlia St, Denver CO",
             "effective_date": "2026-07-15",
             "lines_of_business": ["General Liability"]}
    assert _score(facts, {})["breakdown"]["structural_completeness"] < 100, (
        "a normal submission still owes contact and producer details"
    )


def test_the_card_is_still_raised_even_when_exempt():
    """Exempt from SCORING is not exempt from ASKING."""
    facts = {"applicant_name": "ORBIN CONTRACTING LLC",
             "mailing_address": "4800 Dahlia St, Denver CO",
             "effective_date": "2026-07-15",
             "lines_of_business": ["General Liability"]}
    r = _rec(_score(facts, {"_doc_type": "dec_page"}), "contact_name")
    assert r is not None, "we still want the contact details"
    assert r["score_impact"] == 0, "but it honestly cannot move the score"


# ── Anti-rot ─────────────────────────────────────────────────────────────────

def test_no_recommendation_ships_an_unmeasured_literal_above_its_pillar():
    """Whatever a card declares, what it PRINTS must fit its pillar."""
    for flags in ({}, {"_doc_type": "dec_page"}, {"has_umbrella": True},
                  {"narrative_states_no_losses": True}):
        for fid in ("ACORD_125", "ACORD_127", "ACORD_140"):
            res = _score({}, flags, form_id=fid)
            for r in res.get("recommendations") or []:
                comp = r.get("component")
                if comp not in SPEC_PILLAR_WEIGHTS:
                    continue
                ceiling = round(SPEC_PILLAR_WEIGHTS[comp] * 100)
                assert r.get("score_impact", 0) <= ceiling, (
                    f"{fid}/{comp}: card promises {r['score_impact']} but the "
                    f"pillar tops out at {ceiling}"
                )
