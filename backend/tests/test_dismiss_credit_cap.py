"""Dismiss/ARQ point-credit ceiling behaviour (audit_routes).

Locks the client-confirmed rule: a recommendation/ARQ credit raises each score by
its impact from that score's OWN base, capped at the active-stop ceiling ONLY when
the score would individually exceed it. Scores below the cap keep their own values
and never collapse onto a shared 60 (hard stop) or 85 (warning).

20 Oct 2026 (owner): the 60 / 85 ceilings are back after the 19 Oct "no cap"
build - `_cap_from` is 60 / 85 / 100 again and `_credited_score` takes a REQUIRED
cap. What 19 Oct changed and still stands is which items are hard stops, and an
open hard stop also blocks "Submission Ready" (`ready_blockers`).
"""
import pytest

import services.sqs_service as sq
from routes.audit_routes import _cap_from, _credited_score


def test_cap_from_matches_scorer_gates():
    # Hard stop -> 60, else soft stop -> 85, else no cap (100). Hard wins.
    assert _cap_from(1, 0) == 60
    assert _cap_from(2, 3) == 60      # hard takes precedence over soft
    assert _cap_from(0, 1) == 85
    assert _cap_from(0, 0) == 100
    # ...the same gates the scorer's `_resolve_cap` applies (caps restored 20 Oct 2026).
    assert sq._resolve_cap(["h"], ["s"]) == (sq.HARD_STOP_CAP, "h") == (60, "h")
    assert sq._resolve_cap([], ["s"]) == (sq.SOFT_STOP_CAP, "s") == (85, "s")
    assert sq._resolve_cap([], []) == (None, None)


def test_credit_is_a_ceiling_not_a_floor():
    # A score below the cap is NEVER raised to the cap - it keeps its own value.
    assert _credited_score(22, 8, 60) == 30   # 22 + 8 = 30, stays 30 (not 60)
    assert _credited_score(10, 5, 60) == 15
    # A score that crosses the cap is clamped to it.
    assert _credited_score(56, 8, 60) == 60   # 56 + 8 = 64 -> 60
    assert _credited_score(58, 8, 60) == 60
    # Exactly reaching the cap is fine.
    assert _credited_score(52, 8, 60) == 60


def test_client_hard_stop_scenario_no_collapse():
    # Client's exact example: forms 22 / 56, package 51, hard stop active (cap 60),
    # a multi-form recommendation credits +8 to both forms and the package.
    cap = _cap_from(1, 0)            # hard stop present -> 60
    form1 = _credited_score(22, 8, cap)
    form2 = _credited_score(56, 8, cap)
    pkg   = _credited_score(51, 8, cap)
    assert (form1, form2, pkg) == (30, 60, 59), (form1, form2, pkg)
    # The three scores must stay DISTINCT - the hard stop must not drag them to 60.
    assert len({form1, form2, pkg}) == 3


def test_warning_scenario_no_collapse():
    # Same rule for warnings (cap 85): only scores crossing 85 clamp; others stay.
    cap = _cap_from(0, 1)            # soft stop present -> 85
    assert cap == 85
    below   = _credited_score(70, 5, cap)   # 75, stays distinct
    crosses = _credited_score(82, 8, cap)   # 90 -> 85
    assert below == 75
    assert crosses == 85
    assert below != crosses


def test_credit_never_exceeds_100():
    # With no active stop the only ceiling is 100.
    cap = _cap_from(0, 0)
    assert cap == 100
    assert _credited_score(98, 8, cap) == 100
    assert _credited_score(40, 8, cap) == 48
    # The cap is REQUIRED again (20 Oct 2026): a caller cannot drop the ceiling
    # by leaving it out - the 19 Oct "no cap" default is gone.
    with pytest.raises(TypeError):
        _credited_score(98, 8)


def test_subsequent_credits_accumulate_until_cap():
    # "if further recommendations/ARQ cross 60 then cap them at 60": repeated
    # credits accumulate from the running base and only clamp once they cross.
    cap = _cap_from(1, 0)
    s = 40
    s = _credited_score(s, 8, cap)   # 48
    assert s == 48
    s = _credited_score(s, 8, cap)   # 56
    assert s == 56
    s = _credited_score(s, 8, cap)   # 64 -> 60
    assert s == 60
    s = _credited_score(s, 8, cap)   # already 60, stays 60
    assert s == 60


def test_replaying_surviving_credits_reproduces_the_original_sequence():
    """Reopening a recommendation must cost only ITS points, not everyone else's.

    The credits are written destructively into the stored score with no baseline
    kept, so reopening rescores from facts (wiping all of them) and then replays
    the dismissals that are still standing. Because _credited_score compounds from
    the running base, replaying the survivors in order lands on exactly the score
    the producer would have had if the reopened rec had never been dismissed.
    """
    cap  = _cap_from(0, 0)
    base = 62

    # Producer dismisses three recs with reasons: +8, +12, +5.
    running = base
    for impact in (8, 12, 5):
        running = _credited_score(running, impact, cap)
    assert running == 87

    # Reopen the +8 one: rescore back to base, replay only the survivors.
    replayed = base
    for impact in (12, 5):
        replayed = _credited_score(replayed, impact, cap)
    assert replayed == 79, "reopening +8 must cost 8, not all 25"

    # And it matches never having dismissed it in the first place.
    never = base
    for impact in (12, 5):
        never = _credited_score(never, impact, cap)
    assert replayed == never


def test_replay_respects_the_cap_it_originally_hit():
    # Survivors that collectively cross the ceiling still clamp to it on replay.
    cap = _cap_from(1, 0)            # hard stop -> 60
    replayed = 50
    for impact in (8, 12):
        replayed = _credited_score(replayed, impact, cap)
    assert replayed == 60


def test_scorer_hard_stop_is_a_ceiling_not_a_floor():
    # The ARQ / field-edit recompute re-runs calculate_sqs, whose hard-stop cap is
    # also a ceiling: a low-scoring form with a hard stop keeps its low score (it is
    # NOT raised to 60), so submission-wide hard stops don't collapse forms onto 60.
    sparse = {"applicant_name": "X"}
    kw = dict(facts=sparse, flags={}, mapped_data={"a": None}, form_schema={"a": {}},
              selected_form_ids=["ACORD_126"], tier2_score=20, form_id="ACORD_126")
    low_with_hard = sq.calculate_sqs(hard_stops=["Named insured missing"], soft_stops=[], **kw)["sqs_score"]
    low_no_hard   = sq.calculate_sqs(hard_stops=[], soft_stops=[], **kw)["sqs_score"]
    assert low_with_hard < 60, f"low-data form must not be forced up to 60, got {low_with_hard}"
    assert low_with_hard == low_no_hard, "hard-stop ceiling must not alter a sub-60 score"


# Rich facts that score ABOVE 85 with strong supporting docs, so the 60/85 ceilings
# are demonstrably binding at INITIAL scoring time (before any recommendation/ARQ).
_RICH_FACTS = {
    "producer_name": "Acme Brokers", "applicant_name": "Joe's Roofing LLC",
    "mailing_address": "123 Main St, Dallas TX", "effective_date": "07/01/2026",
    "expiration_date": "07/01/2027", "lines_of_business": ["General Liability"],
    "entity_type": "LLC", "contact_name": "Joe", "contact_phone": "555-1212",
    "contact_email": "j@x.com", "fein": "123456789", "num_employees": "20",
    "operations_description": "Commercial roofing contractor, 12 years",
    "total_revenue": "2000000", "prior_carrier": "Old Carrier", "prior_premium": "45000",
    "years_in_business": "12", "naics_code": "238160", "num_claims": "0",
    "total_payroll": "800000", "gl_limits": "1000000", "gl_aggregate": "2000000",
    "gl_class_codes_by_location": ["98305"], "gl_form_type": "occurrence",
    # Current-valued loss runs: a genuinely "rich" (>85) submission carries a recent
    # valuation date. Without it the §6.4 unknown-valuation-date penalty (-15) applies
    # and the baseline lands exactly on 85, which no longer exceeds the 85 cap.
    "loss_run_years": "5", "loss_run_age_days": "30",
    "acord101_remarks": (
        "Family-owned commercial roofing operator, 12 years in business with "
        "experienced management. No prior losses in 5 years. Written safety program "
        "with annual inspections, OSHA compliance, and documented risk controls."
    ),
}
_RICH_FLAGS = {"has_general_liability": True}


def _rich(hard, soft):
    return sq.calculate_sqs(
        facts=_RICH_FACTS, flags=_RICH_FLAGS,
        mapped_data={k: _RICH_FACTS[k] for k in _RICH_FACTS},
        form_schema={k: {} for k in _RICH_FACTS}, selected_form_ids=["ACORD_125"],
        hard_stops=hard, soft_stops=soft, tier2_score=100, form_id="ACORD_125",
        has_narrative_doc=True, has_loss_run_doc=True, loss_run_match=True,
    )


def _rich_score(hard, soft):
    return _rich(hard, soft)["sqs_score"]


def test_initial_scoring_caps_only_when_stops_present():
    # Confirms the cap applies at GENERATION (nothing answered yet) and ONLY when a
    # hard stop / warning exists - and only when the raw score exceeds the ceiling.
    raw = _rich_score([], [])
    assert raw > 85, f"need an above-85 baseline to prove the 85 cap binds, got {raw}"
    # No stops -> NOT capped: the score is allowed above 85 (up to 100).
    assert _rich_score([], []) == raw
    # Warning present + raw > 85 -> clamped to 85.
    assert _rich_score([], ["a warning"]) == 85
    # Hard stop present + raw > 85 -> clamped to 60.
    assert _rich_score(["a hard stop"], []) == 60
    # The routing follows the capped number, and the open hard stop is also named
    # as what blocks Submission Ready (19 Oct 2026; caps restored 20 Oct 2026).
    clean, warned, blocked = _rich([], []), _rich([], ["a warning"]), _rich(["a hard stop"], [])
    assert clean["routing_decision"] == "auto_quote"
    assert warned["routing_decision"] == "priority_review"     # 85 is not above 85
    assert blocked["routing_decision"] == "standard_review"    # held at 60
    assert warned["raw_sqs_score"] == blocked["raw_sqs_score"] == raw
    assert blocked["open_hard_stops"] == 1 and blocked["ready_blockers"] == ["a hard stop"]
    assert clean["open_hard_stops"] == warned["open_hard_stops"] == 0
