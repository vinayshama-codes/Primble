"""A 60 cap must always be visible as a hard stop.

Reported live 2026-08-31: three generated forms pinned at SQS 60, the Hard
Stops list empty, warnings only, and nothing on screen explaining the number.

Root cause: `calculate_sqs` accepts a cap from `extra_hard_reason` - the COPE,
umbrella and property-integrity gates - which lives OUTSIDE hard_stops, so the
score was held by something that produced no card anywhere. `_resolve_cap` is
the one door for caps; this file is the standing guard that every cap coming
through it is also SAID somewhere.

Nothing here asserts a score VALUE changed. The fix is display-only.

20 Oct 2026 (owner): the caps are back exactly as before 19 Oct. What 19 Oct
changed and still stands: Brent's short hard-stop list - the property gate is a
warning (85) and so is an umbrella whose underlying limit is stated only in
words, while Minimum Viable COPE and an umbrella with no underlying limit at all
still hold 60 - and the readiness fields: a form's `ready_blockers` are its own
`hard_stops` plus the gate in `cap_hard_stops`, each with a row to fix it.
"""
import inspect

import pytest

from services.sqs_service import (
    calculate_sqs, evaluate_stops, _umbrella_has_underlying, _resolve_cap,
    HARD_STOP_CAP, SOFT_STOP_CAP,
)


def _score(facts, flags, hard_stops=None, soft_stops=None, fid="ACORD_125"):
    return calculate_sqs(
        facts=facts, flags=flags, mapped_data={}, form_schema={},
        selected_form_ids=[fid], hard_stops=hard_stops or [],
        soft_stops=soft_stops or [], tier2_score=90, form_id=fid,
        schema_size=200, fields_mapped=180,
    )


# The live package: GL $1M/$1M, Auto $500K CSL, EL $500K, umbrella carried.
# Every underlying limit IS stated. _calculate_umbrella_adequacy still reaches
# 0 because the ordinary deductions stack past 100.
_LIVE_FACTS = {
    "applicant_name": "ACME CONTRACTING LLC", "fein": "84-2210987",
    "mailing_address": "123 Main St, Detroit, MI 48226", "entity_type": "LLC",
    "effective_date": "07/15/2026", "expiration_date": "07/15/2027",
    "total_revenue": "5000000", "total_payroll": "1200000", "num_employees": "24",
    "operations_description": "Commercial roofing contractor, re-roofing and repair.",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$1,000,000",
    "gl_class_codes": "5551", "auto_liability_limit": "$500,000",
    "employers_liability_limits": "$500,000",
    "carrier_name": "EMC", "policy_number": "BBC7263",
}
_LIVE_FLAGS = {
    "has_general_liability": True, "has_auto_coverage": True,
    "has_workers_comp": True, "has_umbrella": True,
    "has_property_coverage": False,
}


# A genuinely BROKEN tower - umbrella present, no underlying GL or Auto limit.
# This is the only shape the umbrella gate caps at 60 on since 2026-09-23; see
# test_a_healthy_umbrella_tower_is_never_capped_at_60 below for why.
# 21 Oct 2026 (Brent's rule 2, `sqs_service.umbrella_underlying`): the EL limit
# goes too - an employers liability limit IS an applicable underlying limit, so
# with it kept this package was no longer a broken tower (the fixture pinned the
# old GL-or-Auto-only reading).
_BARE_FACTS = {k: v for k, v in _LIVE_FACTS.items()
               if k not in ("gl_each_occurrence", "auto_liability_limit",
                            "employers_liability_limits",
                            # 21 Oct (Z30, umbrella review M4): a GL aggregate is
                            # a GL underlying limit, so a broken tower has none.
                            "gl_aggregate")}

# The broken tower's own hard stop (`evaluate_stops`, Brent's short list).
_UMBRELLA_STOP = "Umbrella detected but no underlying GL or Auto limits found"
# The umbrella gate's warning sentence (85 since 19 Oct 2026; it held 60 before).
_UMBRELLA_DETAIL = ("Umbrella coverage is present but its supporting detail is "
                    "incomplete - umbrella limit, underlying limits, schedule of "
                    "underlying insurance and follow-form status")


def test_client_reported_case_is_explained():
    """A 60 held by the gate alone, with an empty Hard Stops list, must name
    itself.

    THE FIXTURE MOVED ON 2026-09-23, the invariant did not. It used to be
    `_LIVE_FACTS` - a package carrying BOTH underlying limits - because back
    then the umbrella gate capped that at 60 by accumulated pillar deductions.
    That was the defect CLAUDE.md held for Brent ("the umbrella gate turns
    Brent's own warnings into a hard stop"), now fixed, so a healthy tower is
    correctly no longer capped and cannot exercise this invariant. The broken
    tower still caps, so it carries the test.
    """
    sqs = _score(_BARE_FACTS, _LIVE_FLAGS)     # no stops passed: gate alone
    assert sqs["cap_applied"] == HARD_STOP_CAP
    assert sqs["sqs_score"] == min(sqs["raw_sqs_score"], HARD_STOP_CAP)
    # The cap is now named, on the form, in a channel the UI renders.
    assert sqs["cap_hard_stops"], "a 60 cap with no hard stop must surface one"
    assert sqs["cap_reason"] in sqs["cap_hard_stops"]
    assert sqs["cap_reason"] in sqs["issues"]
    # (19 Oct 2026, kept) the gate is the form's one readiness blocker, clickable.
    assert sqs["ready_blockers"] == sqs["cap_hard_stops"]
    assert sqs["open_hard_stops"] == 1 and sqs["submission_ready"] is False
    item, = sqs["ready_blocker_items"]
    assert item["message"] == sqs["cap_reason"] and item["severity"] == "hard_stop"
    assert item["code"] and item["resolution"]

    # With the broken tower's own hard stop passed, that stop holds the 60 and
    # the gate stays quiet - one blocker, never two.
    hard, soft = evaluate_stops(_BARE_FACTS, _LIVE_FLAGS)
    assert hard == [_UMBRELLA_STOP]
    sqs = _score(_BARE_FACTS, _LIVE_FLAGS, hard, soft)
    assert sqs["cap_applied"] == HARD_STOP_CAP and sqs["cap_reason"] == _UMBRELLA_STOP
    assert sqs["cap_hard_stops"] == []
    assert sqs["ready_blockers"] == [_UMBRELLA_STOP]
    item, = sqs["ready_blocker_items"]
    assert item["message"] == _UMBRELLA_STOP and item["severity"] == "hard_stop"
    assert item["code"] and item["resolution"]


def test_a_healthy_umbrella_tower_is_never_capped_at_60():
    """The client ruling, made executable (2026-09-23).

    `sqs_service` records it three times over - underlying limits below the
    umbrella baseline are a WARNING plus a score reduction, never a block,
    because carrier attachment points vary. The pillar honoured it and the cap
    gate reading that pillar undid it: `_calculate_umbrella_adequacy` starts at
    100 and subtracts up to 135 points across seven deductions, two of which
    fire on nearly every submission, so it hit 0 by ACCUMULATION on packages
    whose underlying limits were all present - and 0 meant a 60 cap.

    `_LIVE_FACTS` states both a GL occurrence limit and an auto liability
    limit. It must never be capped at 60 by the umbrella gate again.
    """
    assert _umbrella_has_underlying(_LIVE_FACTS) is True
    hard, soft = evaluate_stops(_LIVE_FACTS, _LIVE_FLAGS)
    assert hard == [], "fixture must carry no hard stop of its own"
    sqs = _score(_LIVE_FACTS, _LIVE_FLAGS, hard, soft)
    assert sqs["cap_applied"] != HARD_STOP_CAP, (
        "a package stating both underlying limits was capped at 60 by the "
        "umbrella gate - the ruling says warn, never block"
    )
    assert sqs["cap_hard_stops"] == []
    # (19 Oct 2026, kept) and nothing blocks its Submission Ready.
    assert sqs["ready_blockers"] == [] and sqs["open_hard_stops"] == 0


def test_the_reason_does_not_lie_about_underlying_limits():
    """The old wording claimed 'no underlying GL or Auto limits' on a package
    carrying both. The two causes are told apart by one shared door - and since
    2026-09-23 the has-underlying case does not reach the gate at all, which is
    a stronger guarantee than wording it correctly."""
    assert _umbrella_has_underlying(_LIVE_FACTS) is True
    assert _score(_LIVE_FACTS, _LIVE_FLAGS)["cap_hard_stops"] == []
    hard, _soft = evaluate_stops(_LIVE_FACTS, _LIVE_FLAGS)
    assert not any("no underlying" in m.lower() for m in hard)

    assert _umbrella_has_underlying(_BARE_FACTS) is False
    absent = _score(_BARE_FACTS, _LIVE_FLAGS)["cap_hard_stops"][0]
    assert "no underlying" in absent.lower()
    # (19 Oct 2026, kept) the broken tower's own stop says it too, as its blocker.
    hard, soft = evaluate_stops(_BARE_FACTS, _LIVE_FLAGS)
    blocker = _score(_BARE_FACTS, _LIVE_FLAGS, hard, soft)["ready_blockers"][0]
    assert "no underlying" in blocker.lower()


@pytest.mark.parametrize("word", ["Included", "Statutory", "See schedule", "$0"])
def test_an_underlying_limit_stated_in_words_holds_85_not_60(word):
    """An underlying limit printed but not as a number - "Included" - is not a
    broken tower. With the pillar at 0 the gate says the supporting detail is
    incomplete: a WARNING since 19 Oct 2026, so it holds 85 (it held 60 before),
    names itself in `cap_soft_stops` with a row to fix it, and never blocks
    Submission Ready."""
    facts = {**_BARE_FACTS, "gl_each_occurrence": word}
    assert _umbrella_has_underlying(facts) is False      # no number to compare
    sqs = _score(facts, _LIVE_FLAGS)                      # no stops passed: gate alone
    assert sqs["breakdown"]["umbrella_limit_adequacy"] == 0
    assert sqs["cap_applied"] == SOFT_STOP_CAP
    assert sqs["cap_reason"] == _UMBRELLA_DETAIL
    assert sqs["cap_soft_stops"] == [_UMBRELLA_DETAIL] and sqs["cap_hard_stops"] == []
    assert _UMBRELLA_DETAIL in sqs["issues"]
    item, = sqs["cap_soft_stop_items"]
    assert item["message"] == _UMBRELLA_DETAIL
    assert item["code"] == "legacy_umbrella_gate_detail_incomplete" and item["resolution"]
    assert sqs["ready_blockers"] == [] and sqs["open_hard_stops"] == 0


def test_never_duplicates_a_stop_the_screen_already_shows():
    """A real hard stop already renders a card; the gate must stay quiet."""
    sqs = _score(_LIVE_FACTS, _LIVE_FLAGS,
                 hard_stops=["FEIN differs across uploaded documents."])
    assert sqs["cap_applied"] == HARD_STOP_CAP
    assert sqs["cap_hard_stops"] == []
    # (19 Oct 2026, kept) the stop blocks the status once.
    assert sqs["ready_blockers"] == ["FEIN differs across uploaded documents."]
    assert len(sqs["ready_blocker_items"]) == 1


def test_no_gate_means_nothing_is_invented():
    flags = dict(_LIVE_FLAGS, has_umbrella=False)
    hard, soft = evaluate_stops(_LIVE_FACTS, flags)
    sqs = _score(_LIVE_FACTS, flags, hard, soft)
    assert sqs["cap_applied"] != HARD_STOP_CAP
    assert sqs["cap_hard_stops"] == []
    # (19 Oct 2026, kept) no hard stop, no blocker.
    assert sqs["ready_blockers"] == [] and sqs["ready_blocker_items"] == []


def test_the_one_cap_door_and_the_form_gates():
    """`_resolve_cap` is the one door (20 Oct 2026, the caps are back): any hard
    stop - its list, then a hard cross issue, then a gate - holds 60 and names
    the first; else any warning holds 85; else nothing. The form scorer's gates
    feed it again: COPE and umbrella hard, the property gate soft only (19 Oct
    2026: a missing Period of Restoration is a warning), so a hard property
    gate cannot come back without failing here."""
    assert _resolve_cap(["a hard stop"], ["a warning"], hard_cross=["x"],
                        extra_hard_reason="gate", extra_soft_reason="gate") \
        == (HARD_STOP_CAP, "a hard stop")
    assert _resolve_cap([], ["a warning"], hard_cross=["x"]) == (HARD_STOP_CAP, "x")
    assert _resolve_cap([], ["a warning"], extra_hard_reason="gate") == (HARD_STOP_CAP, "gate")
    assert _resolve_cap([], ["a warning"], extra_soft_reason="gate") == (SOFT_STOP_CAP, "a warning")
    assert _resolve_cap([], [], extra_soft_reason="gate") == (SOFT_STOP_CAP, "gate")
    assert _resolve_cap([], []) == (None, None)

    src = inspect.getsource(calculate_sqs)
    for back in ("cope_hard", "umb_fail", "_prop_soft_because",
                 "extra_hard_reason", "extra_soft_reason"):
        assert back in src, f"{back} is missing from calculate_sqs"
    assert "_prop_hard" not in src, "the property gate is a warning only since 19 Oct 2026"


@pytest.mark.parametrize("fid", ["ACORD_125", "ACORD_126", "ACORD_25",
                                 "ACORD_140", "ACORD_133", "ACORD_131"])
def test_every_blocker_is_said_somewhere(fid):
    """THE INVARIANT. Whatever holds a form at 60, it is either already a hard
    stop on screen or it is now in cap_hard_stops; the same for an 85 and
    cap_soft_stops. A future gate added to _resolve_cap's extra_*_reason cannot
    go silent without failing here. And (19 Oct 2026, kept) whatever blocks the
    form's Submission Ready is exactly those hard stops, each with a row to fix
    it - a warning never blocks."""
    scenarios = [
        (_LIVE_FACTS, _LIVE_FLAGS),                                   # umbrella
        ({**_BARE_FACTS, "gl_each_occurrence": "Included"},           # umbrella, words
         _LIVE_FLAGS),
        ({**_LIVE_FACTS, "business_income_limit": "$500,000"},         # property
         {"has_property_coverage": True, "property_has_bi_coverage": True}),
        ({"applicant_name": "X"},                                      # empty COPE
         {"has_property_coverage": True}),
    ]
    for facts, flags in scenarios:
        hard, soft = evaluate_stops(facts, flags)
        sqs = _score(facts, flags, hard, soft, fid=fid)
        if sqs["cap_applied"] == HARD_STOP_CAP:
            assert sqs["cap_reason"] in hard or sqs["cap_reason"] in sqs["cap_hard_stops"], (
                f"{fid} held at 60 by {sqs['cap_reason']!r} with nothing on screen"
            )
        if sqs["cap_applied"] == SOFT_STOP_CAP:
            assert sqs["cap_reason"] in soft or sqs["cap_reason"] in sqs["cap_soft_stops"], (
                f"{fid} held at 85 by {sqs['cap_reason']!r} with nothing on screen"
            )
        if sqs["cap_applied"] is not None:
            assert sqs["sqs_score"] == min(sqs["raw_sqs_score"], sqs["cap_applied"])

        # Only this form's stops hold it (`stops_for_form`, 30 Oct 2026): a stop
        # whose subject is another form ("ACORD 125 minimum field missing")
        # holds the package and that form, never this one.
        from services.sqs_service import stops_for_form
        assert sqs["ready_blockers"] == list(dict.fromkeys(stops_for_form(hard, fid)
                                                           + sqs["cap_hard_stops"])), (
            f"{fid} blocked by something the Hard Stops list does not show")
        assert not set(sqs["ready_blockers"]) & set(soft)
        assert sqs["open_hard_stops"] == len(sqs["ready_blockers"])
        assert [i["message"] for i in sqs["ready_blocker_items"]] == sqs["ready_blockers"]
        for item in sqs["ready_blocker_items"]:
            assert item["severity"] == "hard_stop" and item["code"], item
        if sqs["ready_blockers"]:
            assert sqs["cap_applied"] == HARD_STOP_CAP, "every blocker holds the 60"
            assert sqs["submission_ready"] is False and sqs["tier"] != "Submission Ready"
