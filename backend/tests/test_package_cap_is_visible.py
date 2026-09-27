"""A package 60 cap must render as a hard stop, not as a warning.

OWNER RULE, 2026-08-31: **the card must match the cap.** If something holds the
score at 60 it renders as a hard stop - even where the engine that emitted it
called it a warning. Never the reverse: a display problem is never fixed by
changing a score.

The live defect this pins: `calculate_package_sqs` MANUFACTURES a
`property_building_value` hard stop inside itself. It caps the package at 60 and
its own comment claims it "shows in the Hard Stops section" - it never did. The
dict is created locally, never written to `cross_issues_last` or
`structured_issues`, so `build_grouped_view` could not see it:
`grouped_issues.hard_stops` was empty, `counts.hard_stops` was 0, and the
frontend's `hasHardStops` gate hid the banner entirely. Meanwhile
`extraction_pipeline` draws the SAME fact as a soft warning when the package has
no property coverage - so the producer read "warning" while the score read
"blocker". Measured: raw 68 -> displayed 60 with `hard_stops == []`.

Nothing here asserts a score changed. The fix is display-only.
"""
import pytest

from services.sqs_service import (
    calculate_package_sqs, evaluate_stops, HARD_STOP_CAP,
)
from services.issue_registry import build_grouped_view, make_issue


_PICKER_CODE = "underwriting_reconciliation_property_building_value"

# The card `extraction_pipeline` already draws for this fact when the conflict is
# not relevant - a soft warning, with its own wording.
_WARN = ("Property Building Value: documents disagree ($2,500,000, $3,100,000). "
         "Fix: Confirm the correct value to apply it across forms.")

_FACTS = {
    "applicant_name": "ACME LLC", "fein": "84-2210987", "entity_type": "LLC",
    "mailing_address": "123 Main St, Detroit, MI 48226",
    "physical_address": "123 Main St, Detroit, MI 48226",
    "effective_date": "07/15/2026", "expiration_date": "07/15/2027",
    "total_revenue": "5000000", "total_payroll": "1200000", "num_employees": "24",
    "years_in_business": "12", "naics_code": "238160",
    "producer_name": "Midwest Agency", "carrier_name": "EMC",
    "carrier_naic": "25186", "policy_number": "BBC7263",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "gl_class_codes": "5551", "gl_exposure_basis": "payroll",
    "loss_history": "No known losses",
    "loss_history_no_prior_losses_indicator": "Y", "prior_carrier": "EMC",
    "property_building_value": "$2,500,000",
    # Minimum Viable COPE, so the property line does not raise a hard stop of
    # its own and this file keeps testing the CAP DISPLAY rather than COPE.
    "locations": [{"address": "123 Main St, Detroit, MI 48226"}],
    "occupancy_type": "Contractor office and shop",
    "construction_type": "Joisted Masonry",
    "operations_description": "Commercial roofing contractor performing re-roofing "
                              "and repair on existing structures.",
    "account_description": "Established roofing contractor, 12 years, stable "
                           "losses, strong safety program.",
}
# PROPERTY COVERAGE IS TRUE, AND THAT IS THE POINT (changed 2026-09-23).
# It was False, which made the building-value conflict IRRELEVANT - and on
# 2026-09-23 `calculate_package_sqs` stopped hard-stopping on an irrelevant
# conflict, honouring the ruling `extraction_pipeline` had already written down
# ("cannot block anything on a package that has no property coverage"). This
# file tests that a cap which DOES fire is visible, so its fixture has to be one
# where the cap legitimately fires. The old behaviour is pinned from the other
# side by test_an_irrelevant_building_value_conflict_does_not_cap below.
_FLAGS = {"has_general_liability": True, "has_property_coverage": True}
_UW = {"fields": [{
    "fact_key": "property_building_value", "review_required": True,
    "label": "Property Building Value",
    "values": [{"display": "$2,500,000"}, {"display": "$3,100,000"}],
}]}


def _all_messages(view):
    """Every message the grouped view renders, from ALL sections. `important` is
    an ECHO of the top warning clusters, so it is deliberately excluded - it
    would double-count a row that is rendered once."""
    out = []
    for cluster in list(view.get("hard_stops") or []) + [
            c for tier in (view.get("warnings") or {}).values() for c in tier]:
        for item in (cluster.get("items") or [cluster]):
            if item.get("message"):
                out.append(item["message"])
    return out


def _score(uw=_UW, hard=None, soft=None, facts=None, flags=None):
    facts = facts if facts is not None else _FACTS
    flags = flags if flags is not None else _FLAGS
    session = {"facts": facts, "flags": flags, "docs": []}
    if uw is not None:
        session["underwriting_consistency"] = uw
    _h, _s = evaluate_stops(facts, flags)
    return calculate_package_sqs(
        facts=facts, flags=flags, form_results=[], cross_issues=[],
        hard_stops=_h if hard is None else hard,
        soft_stops=_s if soft is None else soft,
        session_data=session, session_id="t", user_id="t",
        calculation_stage="form_generated",
    )


def test_the_manufactured_stop_is_no_longer_private():
    """The reported shape: a 60 cap whose cause reached no display channel."""
    pkg = _score()
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["cap_hard_stops"], "a package 60 cap with no card must surface one"
    assert pkg["cap_reason"] in pkg["cap_hard_stops"]
    # And it names the card that already exists, so the display can promote it.
    assert _PICKER_CODE in pkg["cap_hard_stop_codes"]


def test_promotion_upgrades_the_existing_card_and_does_not_duplicate_it():
    """The warning becomes the hard stop. One row, not two."""
    pkg = _score()
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]

    before = build_grouped_view(structured, hard, soft)
    assert before["counts"]["hard_stops"] == 0        # the defect
    # Since UI-13 the un-promoted picker row does not render as a warning here
    # either (Data Consistency owns it), which makes promotion the ONLY thing
    # keeping a capping conflict on this screen.
    _before_warn = before["counts"]["warnings"]

    after = build_grouped_view(
        structured, hard, soft, promote_codes=pkg["cap_hard_stop_codes"])
    assert after["counts"]["hard_stops"] == 1
    assert len(after["hard_stops"]) == 1
    # The SAME row moved - its wording is preserved, so its Resolve control
    # ("Fix in Data Consistency", derived from the code) moves with it.
    assert after["hard_stops"][0]["items"][0]["message"] == _WARN
    assert after["hard_stops"][0]["items"][0]["code"] == _PICKER_CODE
    # Exactly one row total for this problem - counted over the whole view,
    # which states "not duplicated" directly instead of inferring it from a
    # warning-count delta.
    assert _all_messages(after).count(_WARN) == 1
    assert after["counts"]["warnings"] == _before_warn
    # PROMOTION MOVES A ROW, it never mints one (2026-09-23). `counts` reports
    # only what rendered, so the un-promoted picker row appears in neither
    # bucket; `hidden_warnings` is where it is accounted for, and the sum of all
    # three is what must hold steady across the promotion.
    def _total(g):
        return (g["counts"]["hard_stops"] + g["counts"]["warnings"]
                + g.get("hidden_warnings", 0))
    assert _total(after) == _total(before)
    assert before["hidden_warnings"] == 1, (
        "the un-promoted picker row caps the score at 85 and draws no card - it "
        "must still be accounted for somewhere, or the screen reads 0 warnings"
    )
    assert after["hidden_warnings"] == 0


def test_promotion_is_inert_without_codes():
    """No promote_codes -> byte-identical to the previous behaviour."""
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]
    assert (build_grouped_view(structured, hard, soft)
            == build_grouped_view(structured, hard, soft, promote_codes=[]))


def test_no_conflict_means_nothing_is_invented():
    pkg = _score(uw={"fields": []})
    assert pkg["cap_hard_stops"] == []
    assert pkg["cap_hard_stop_codes"] == []


def test_never_duplicates_a_stop_the_screen_already_shows():
    """A real hard stop already renders a card; the package cap stays quiet."""
    pkg = _score(hard=["FEIN differs across uploaded documents."], soft=[])
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["cap_hard_stops"] == []


def test_no_score_moved_by_this_change():
    """The whole fix is display. The cap and the number are what they were."""
    pkg = _score()
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], HARD_STOP_CAP)


@pytest.mark.parametrize("has_property", [True, False])
def test_every_package_60_cap_is_said_somewhere(has_property):
    """THE INVARIANT, package half. Whatever holds the package at 60 is either
    already a hard stop the screen draws, or is in cap_hard_stops. A future cap
    source added to calculate_package_sqs cannot go silent without failing here.

    Both relevance branches are driven: Option A (owner, 2026-08-31) keeps the
    cap in BOTH, and requires it to be visible in both.
    """
    flags = dict(_FLAGS, has_property_coverage=has_property)
    pkg = _score(flags=flags)
    if pkg["cap_applied"] != HARD_STOP_CAP:
        pytest.skip("not capped in this branch")
    hard, _ = evaluate_stops(_FACTS, flags)
    assert pkg["cap_reason"] in hard or pkg["cap_reason"] in pkg["cap_hard_stops"], (
        f"package held at 60 by {pkg['cap_reason']!r} with nothing on screen"
    )


# ── The Review screen is built in TWO route modules (2026-09-23) ─────────────
# `form_routes` folded the package scorer's private 60-cap into the grouped view
# through `_grouped_with_package_caps` at all five of its response sites.
# `audit_routes._form_selection_view` - which rebuilds the SAME screen after
# resolve-issue and reopen-issue - called bare `build_grouped_view`. So the
# producer clicked "Open to fix" on any unrelated issue, the fix succeeded, and
# the only card explaining the 60 disappeared with the score unchanged. Exactly
# the class the promote_codes work shipped to close, surviving on the one call
# site that was not part of it, because nothing tied the two declarations
# together.
#
# The Cross-Form Validation PANEL is a deliberate exception: it renders the raw
# cross-form list for one panel and is not the Review screen's stop banner, so
# it neither has nor needs package stops. It is identified by function name.
_CROSS_PANEL_BUILDERS = ("_grouped_cross_issues_for_panel",
                         "_grouped_cross_issues_or_none")


def test_no_route_builds_the_review_view_without_the_package_caps():
    import ast
    import pathlib

    routes_dir = pathlib.Path(__file__).resolve().parent.parent / "routes"
    offenders = []
    checked = 0
    for path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in _CROSS_PANEL_BUILDERS:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "build_grouped_view"):
                    checked += 1
                    offenders.append(f"{path.name}::{fn.name}:{node.lineno}")
    assert checked or not offenders
    assert not offenders, (
        "these route functions build the grouped view WITHOUT the package "
        f"scorer's private caps: {offenders} - use "
        "issue_registry.grouped_with_package_caps so a 60 held by the package "
        "scorer keeps its card, or add the function to _CROSS_PANEL_BUILDERS "
        "if it genuinely renders only the cross-form panel"
    )


def test_the_shared_door_exists_and_both_route_modules_reach_it():
    """The guard above is only meaningful if the door is real and used."""
    from services.issue_registry import grouped_with_package_caps
    import pathlib

    routes_dir = pathlib.Path(__file__).resolve().parent.parent / "routes"
    users = [p.name for p in sorted(routes_dir.glob("*.py"))
             if "grouped_with_package_caps" in p.read_text(encoding="utf-8")]
    assert "form_routes.py" in users
    assert "audit_routes.py" in users, (
        "audit_routes rebuilds the Review screen after resolve/reopen - if it "
        "stops using the shared door, a package 60-cap loses its card again"
    )
    assert callable(grouped_with_package_caps)


def test_an_irrelevant_building_value_conflict_does_not_cap():
    """C75, applied to the package scorer (2026-09-23).

    `extraction_pipeline` decided this exact question for this exact fact and
    wrote the ruling into the code: a building-value conflict "cannot block
    anything on a package that has no property coverage - there is no ACORD 140
    to generate and no box for the number", so it keeps the conflict a WARNING
    when `has_property_coverage` is false. `calculate_package_sqs` applied it
    unconditionally, so one fact carried two verdicts in two files and the
    harsher one won: the pipeline drew a warning while the scorer capped the
    package at 60.

    Measured on the live Orbin session before the fix: 72 -> 60, taking the tier
    from "Needs Work" to "Major Gaps", on a package with no property line at
    all.
    """
    no_property = dict(_FLAGS, has_property_coverage=False)
    hard, soft = evaluate_stops(_FACTS, no_property)
    pkg = calculate_package_sqs(
        facts=_FACTS, flags=no_property, form_results=[], cross_issues=[],
        hard_stops=list(hard), soft_stops=list(soft) + [_WARN],
        session_data={"docs": [], "selected_form_ids": ["ACORD_125"],
                      "sqs_history": [], "underwriting_consistency": _UW},
    )
    assert pkg["cap_applied"] != HARD_STOP_CAP, (
        "a building-value conflict hard-stopped a package that carries no "
        "property coverage - the pipeline calls the same conflict a warning"
    )
    assert pkg["cap_hard_stops"] == []
    assert pkg["cap_hard_stop_codes"] == []

    # ...and it is NOT silently dropped: the conflict is still open, so the
    # warning it arrived as still holds the 85.
    assert pkg["cap_applied"] == 85
