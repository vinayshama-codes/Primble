"""A 60 cap must always be visible as a hard stop.

Reported live 2026-08-31: three generated forms pinned at SQS 60, the Hard
Stops list empty, warnings only, and nothing on screen explaining the number.

Root cause: `calculate_sqs` accepts a cap from `extra_hard_reason` - the COPE,
umbrella and property-integrity gates - which lives OUTSIDE hard_stops, so the
score was held by something that produced no card anywhere. `_resolve_cap` is
the one door for caps; this file is the standing guard that every cap coming
through it is also SAID somewhere.

Nothing here asserts a score VALUE changed. The fix is display-only.
"""
import pytest

from services.sqs_service import (
    calculate_sqs, evaluate_stops, _umbrella_has_underlying, HARD_STOP_CAP,
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


def test_client_reported_case_is_explained():
    """The literal reported run: 60 with an empty Hard Stops list."""
    hard, soft = evaluate_stops(_LIVE_FACTS, _LIVE_FLAGS)
    assert hard == [], "fixture must reproduce the ZERO-hard-stop condition"

    sqs = _score(_LIVE_FACTS, _LIVE_FLAGS, hard, soft)
    assert sqs["cap_applied"] == HARD_STOP_CAP
    # The cap is now named, on the form, in a channel the UI renders.
    assert sqs["cap_hard_stops"], "a 60 cap with no hard stop must surface one"
    assert sqs["cap_reason"] in sqs["cap_hard_stops"]
    assert sqs["cap_reason"] in sqs["issues"]


def test_the_reason_does_not_lie_about_underlying_limits():
    """The old wording claimed 'no underlying GL or Auto limits' on a package
    carrying both. The two causes are now told apart by one shared door."""
    assert _umbrella_has_underlying(_LIVE_FACTS) is True
    stated = _score(_LIVE_FACTS, _LIVE_FLAGS)["cap_hard_stops"][0]
    assert "no underlying" not in stated.lower()

    bare = {k: v for k, v in _LIVE_FACTS.items()
            if k not in ("gl_each_occurrence", "auto_liability_limit")}
    assert _umbrella_has_underlying(bare) is False
    absent = _score(bare, _LIVE_FLAGS)["cap_hard_stops"][0]
    assert "no underlying" in absent.lower()


def test_never_duplicates_a_stop_the_screen_already_shows():
    """A real hard stop already renders a card; the gate must stay quiet."""
    sqs = _score(_LIVE_FACTS, _LIVE_FLAGS,
                 hard_stops=["FEIN differs across uploaded documents."])
    assert sqs["cap_applied"] == HARD_STOP_CAP
    assert sqs["cap_hard_stops"] == []


def test_no_gate_means_nothing_is_invented():
    flags = dict(_LIVE_FLAGS, has_umbrella=False)
    hard, soft = evaluate_stops(_LIVE_FACTS, flags)
    sqs = _score(_LIVE_FACTS, flags, hard, soft)
    assert sqs["cap_applied"] != HARD_STOP_CAP
    assert sqs["cap_hard_stops"] == []


@pytest.mark.parametrize("fid", ["ACORD_125", "ACORD_126", "ACORD_25",
                                 "ACORD_140", "ACORD_133", "ACORD_131"])
def test_every_60_cap_is_said_somewhere(fid):
    """THE INVARIANT. Whatever holds a form at 60, it is either already a hard
    stop on screen or it is now in cap_hard_stops. A future gate added to
    _resolve_cap's extra_hard_reason cannot go silent without failing here."""
    scenarios = [
        (_LIVE_FACTS, _LIVE_FLAGS),                                   # umbrella
        ({**_LIVE_FACTS, "business_income_limit": "$500,000"},         # property
         {"has_property_coverage": True, "property_has_bi_coverage": True}),
        ({"applicant_name": "X"},                                      # empty COPE
         {"has_property_coverage": True}),
    ]
    for facts, flags in scenarios:
        hard, soft = evaluate_stops(facts, flags)
        sqs = _score(facts, flags, hard, soft, fid=fid)
        if sqs["cap_applied"] != HARD_STOP_CAP:
            continue
        assert sqs["cap_reason"] in hard or sqs["cap_reason"] in sqs["cap_hard_stops"], (
            f"{fid} held at 60 by {sqs['cap_reason']!r} with nothing on screen"
        )
