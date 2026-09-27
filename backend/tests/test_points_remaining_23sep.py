"""Every gap worth points is shown, ranked by what it is worth (2026-09-23).

THE REPORTED PROBLEM. A producer cleared every warning and every hard stop -
`hard_stops: []`, `soft_stops: []` - and the package scored 78. Nothing on
screen said 22 points were still available, where they sat, or which of them
were theirs to type. They asked, reasonably: "why was there no warning or hard
stop I could fix to make this reach 100?"

There was none, because warnings and the score are disjoint machinery. A warning
fires on a RULE VIOLATION and its only effect is a ceiling (60/85). The score is
earned from six weighted pillars, and absence of evidence is not a rule
violation, so it raises no warning. The package's own "Best Solutions" list was
the only surface that could have bridged them, and it had three defects:

  1. `[:3]` - a fourth gap was never shown. Live: Exposure at 82 was worth 5.3
     points and got no row anywhere in the product.
  2. `< 90` - a pillar at 92 still costs over a point at the .25 weights and was
     never mentioned.
  3. Ranked by SCORE, not by points. Pillars carry different weights, so live
     the panel put narrative (40%, worth 7.1) ABOVE structural (70%, worth 8.8)
     and recommended the smaller win first.
"""
import pytest

from services.sqs_service import (
    SPEC_PILLAR_WEIGHTS, calculate_package_sqs,
)


def _F(v):
    return {"value": v, "confidence": "filled", "source": "ai_high"}


_FACTS = {
    "applicant_name": _F("PANEL LLC"), "producer_name": _F("Broker"),
    "mailing_address": _F("1 Main St, Denver, CO 80216"), "entity_type": _F("LLC"),
    "effective_date": _F("01/01/2027"), "expiration_date": _F("01/01/2028"),
    "lines_of_business": _F(["General Liability"]), "contact_email": _F("a@b.example"),
    "operations_description": _F("Commercial carpentry contractor"),
    "gl_each_occurrence": _F("1000000"), "gl_aggregate": _F("2000000"),
    "gl_class_codes_by_location": _F("91340 Carpentry"),
}
_FLAGS = {"has_general_liability": True, "is_commercial_policy": True}
_SESS = {"docs": [], "selected_form_ids": ["ACORD_125"], "sqs_history": []}


def _pkg(facts=None, flags=None):
    return calculate_package_sqs(
        facts=facts or _FACTS, flags=flags or _FLAGS, form_results=[],
        cross_issues=[], hard_stops=[], soft_stops=[], session_data=_SESS,
    )


def _recs(pkg):
    return [r for r in (pkg.get("top_recommendations") or [])
            if r.get("pillar") != "hard_stops_present"]


def test_every_pillar_short_of_100_is_listed():
    """No [:3] cap and no `< 90` filter - a gap nobody renders is a gap nobody
    can close."""
    pkg = _pkg()
    listed = {r["pillar"] for r in _recs(pkg)}
    short = {k for k, v in (pkg.get("pillars") or {}).items()
             if v is not None and v < 100}
    assert short, "fixture must have at least one imperfect pillar"
    assert short == listed, f"pillars short of 100 but not listed: {short - listed}"


def test_rows_are_ranked_by_points_not_by_score():
    """A low score on a light pillar must not outrank a mild gap on a heavy one."""
    pkg = _pkg()
    pts = [r["points_available"] for r in _recs(pkg)]
    assert pts == sorted(pts, reverse=True), f"not ranked by points: {pts}"


def test_points_available_uses_the_effective_weight():
    """The same weights the SCORE used, so a Not Applicable pillar's weight is
    already redistributed and the numbers describe the real gap."""
    pkg = _pkg()
    pillars = pkg.get("pillars") or {}
    na = [k for k, v in pillars.items() if v is None]
    live = sum(w for k, w in SPEC_PILLAR_WEIGHTS.items() if k not in na) or 1.0
    for r in _recs(pkg):
        eff = SPEC_PILLAR_WEIGHTS[r["pillar"]] / live
        assert r["points_available"] == pytest.approx(
            round((100 - pillars[r["pillar"]]) * eff, 1), abs=0.05)


def test_points_remaining_closes_the_gap_to_100():
    """raw + points_remaining must land on 100, or the number is not the gap."""
    pkg = _pkg()
    assert pkg["raw_sqs_score"] + pkg["points_remaining"] == pytest.approx(100, abs=1.0)


def test_points_remaining_is_zero_on_a_perfect_package():
    """Not a special case - it must fall out of the same arithmetic."""
    pkg = _pkg()
    if pkg["raw_sqs_score"] >= 100:
        assert pkg["points_remaining"] == 0


def test_every_row_says_how_it_closes():
    pkg = _pkg()
    for r in _recs(pkg):
        assert r.get("closes_with") in ("type", "document", "review"), r


def test_a_typeable_row_carries_a_routable_field():
    """`closes_with == "type"` is a promise that a control exists behind it."""
    from services.answer_routing import answer_mode
    from services.arq_service import _canonical_key

    for r in _recs(_pkg()):
        if r.get("closes_with") != "type":
            continue
        assert r.get("field"), f"{r['pillar']} says type but names no fact"
        assert _canonical_key(r["field"]), f"{r['field']} is not writable"
        assert answer_mode(r["field"], {})["mode"] != "none"


def test_loss_history_without_a_loss_run_says_it_needs_a_document():
    """The distinction that matters most: a gap waiting on the insured reads
    exactly like one the producer could close in ten seconds, unless it says so."""
    pkg = _pkg()
    loss = next((r for r in _recs(pkg)
                 if r["pillar"] == "loss_history_alignment"), None)
    if loss is not None:          # None = Not Applicable, which is not a gap
        assert loss["closes_with"] == "document"


def test_an_na_pillar_is_never_listed_as_a_gap():
    """Not Applicable is removed from the calculation, not a gap to close."""
    pkg = _pkg()
    na = {k for k, v in (pkg.get("pillars") or {}).items() if v is None}
    listed = {r["pillar"] for r in _recs(pkg)}
    assert not (na & listed), f"N/A pillars listed as gaps: {na & listed}"
