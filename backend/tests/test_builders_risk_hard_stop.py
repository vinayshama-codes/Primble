"""test_builders_risk_hard_stop.py

Regression test for the second half of the "Builders Risk hard stop on a
package with no builders risk exposure" client report (2026-08-07).

Two independent gates fed the same hard stop
(cross_form_validator._check_builders_risk_project_value):

  1. form_service.py's ACORD_133 form-trigger let a bare keyword match
     ("builders risk" showing up anywhere in the document text - an exclusions
     clause, a coverage checklist, even a sentence denying the coverage) add
     ACORD_133 to `triggered_ids` with zero real project evidence. Covered by
     test_form_recommendation.py's test_133_* cases.
  2. THIS gate: even with (1) fixed, `_check_builders_risk_project_value` also
     fires standalone off `flags.get("has_builders_risk")` alone, with no
     check that ACORD_133 was ever actually selected or that any real project
     fact (address/cost/completion date) was ever extracted. A flag misfire
     with nothing behind it manufactured a hard stop out of nothing.

Both gates now require the same corroboration: at least one real
builders-risk fact (address, cost, or completion date) before the flag alone
(or a bare trigger) can produce a hard stop.
"""

from services.cross_form_validator import _check_builders_risk_project_value


def test_flag_alone_with_no_evidence_produces_no_hard_stop():
    """The exact false-positive from the client report: has_builders_risk set
    with nothing behind it, and ACORD 133 never selected."""
    issues = _check_builders_risk_project_value(
        facts={}, flags={"has_builders_risk": True}, triggered_ids=set(),
    )
    assert issues == []


def test_no_flag_and_not_triggered_produces_no_hard_stop():
    """Baseline: a package with no builders risk signal at all must stay silent."""
    issues = _check_builders_risk_project_value(
        facts={}, flags={}, triggered_ids=set(),
    )
    assert issues == []


def test_flag_plus_real_evidence_but_missing_cost_still_hard_stops():
    """A genuine active project (address extracted) whose cost is missing is
    exactly what this hard stop exists to catch - must not be swallowed by the
    corroboration fix."""
    issues = _check_builders_risk_project_value(
        facts={"builders_risk_project_address": "123 Main St, Denver, CO"},
        flags={"has_builders_risk": True},
        triggered_ids=set(),
    )
    assert len(issues) == 1
    assert issues[0]["code"] == "builders_risk_project_value_missing"
    assert issues[0]["type"] == "hard_stop"


def test_acord_133_selected_with_cost_provided_clears():
    """The happy path: ACORD 133 legitimately in the package and a real cost on
    file - no issue at all."""
    issues = _check_builders_risk_project_value(
        facts={"builders_risk_project_cost": "500000"},
        flags={"has_builders_risk": True},
        triggered_ids={"ACORD_133"},
    )
    assert issues == []


def test_acord_133_selected_without_cost_still_hard_stops():
    """ACORD 133 actually in the package (form_service.py only adds it with
    real evidence now) but cost specifically missing - the hard stop must
    still ask for it; this path is untouched by the fix."""
    issues = _check_builders_risk_project_value(
        facts={"builders_risk_project_address": "123 Main St, Denver, CO"},
        flags={},
        triggered_ids={"ACORD_133"},
    )
    assert len(issues) == 1
    assert issues[0]["code"] == "builders_risk_project_value_missing"
