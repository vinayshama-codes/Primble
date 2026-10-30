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

19 Oct 2026 (Brent): a hard stop also blocks the "Submission Ready" STATUS, and
the manufactured building-value item is a WARNING cross item
(`building_value_cross_items`) that costs its Exposure points and blocks nothing.
20 Oct 2026 (owner): the caps are back exactly as they were. The building value
now holds the 85 through its Data Consistency row, never a 60; a 60 the hard
stops do not carry can only come from a hard cross issue, and it is still said
in `cap_hard_stops`. The promotion path stays only for payloads stored before.
"""
import pytest

from services.sqs_service import (
    BUILDING_VALUE_CONFLICT_MSG, HARD_STOP_CAP, SOFT_STOP_CAP,
    building_value_cross_items, calculate_package_sqs, evaluate_stops,
    exposure_deduction_items,
)
from services.issue_registry import (
    build_grouped_view, grouped_with_package_caps, make_issue,
)


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
# (19 Oct 2026, Brent: a warning) - kept TRUE so the conflict is relevant: it then costs its Exposure
# points, and its Data Consistency row holds the 85 (20 Oct 2026, the cap is back).
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
    """The reported shape: a 60 cap whose cause reached no display channel.
    The manufactured item is now a warning that costs its Exposure points and
    never holds 60. Its 85 is said by a row that renders (its Data Consistency
    card) whenever that row is listed - and holds by itself when no list carries
    it (20 Oct 2026 review: after forms the recalculation's and the field
    edit's lists never do, and the conflict held no cap at all)."""
    pkg = _score()
    clean = _score(uw={"fields": []})
    _, soft = evaluate_stops(_FACTS, _FLAGS)
    # (20 Oct 2026, the cap is back; 19 Oct: a differing building value is a
    # warning) - the package is held at 85 by its listed warnings, never at 60.
    assert pkg["cap_applied"] == SOFT_STOP_CAP and pkg["cap_reason"] == soft[0]
    assert pkg["cap_hard_stops"] == [] and pkg["cap_hard_stop_codes"] == []
    assert pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], SOFT_STOP_CAP)
    # The building value's 85 is named by its Data Consistency row when that
    # listed warning is there - the row the screen accounts for...
    held = _score(hard=[], soft=[_WARN])
    assert (held["cap_applied"], held["cap_reason"]) == (SOFT_STOP_CAP, _WARN)
    assert held["cap_hard_stops"] == [] and held["cap_hard_stop_codes"] == []
    # ...and the manufactured item holds the same 85 when no list carries the
    # row (the post-form recalculation and the field edit) - never no cap.
    alone = _score(hard=[], soft=[])
    assert (alone["cap_applied"], alone["cap_reason"]) == (SOFT_STOP_CAP, BUILDING_VALUE_CONFLICT_MSG)
    assert alone["cap_hard_stops"] == [] and alone["ready_blockers"] == []
    # (19 Oct 2026, Brent: a differing building value is a warning) - it blocks nothing...
    assert pkg["ready_blockers"] == [] and pkg["open_hard_stops"] == 0
    session = {"underwriting_consistency": _UW}
    assert building_value_cross_items(_FLAGS, session) == [
        {"type": "soft_warning", "field": "property_building_value",
         "message": BUILDING_VALUE_CONFLICT_MSG}]
    # ...and costs exactly a warning's Exposure points (-5, the cross bucket).
    cross = [i for i in exposure_deduction_items(
                 _FACTS, _FLAGS, [], building_value_cross_items(_FLAGS, session))
             if i["bucket"] == "cross_document_consistency"]
    assert [(i["points"], i["kind"]) for i in cross] == [(5, "conflict")]
    assert (clean["pillars"]["exposure_consistency"]
            - pkg["pillars"]["exposure_consistency"]) == 5


def test_a_new_payload_keeps_the_warning_a_warning():
    """The card matches what blocks the package: a scorer that blocks nothing
    promotes nothing, and the picker row is still accounted for."""
    pkg = _score()
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]
    # (19 Oct 2026: no hard cross building value) - the shared door has no codes to promote on a new payload.
    assert pkg["cap_hard_stop_codes"] == []
    view = grouped_with_package_caps(structured, hard, soft, pkg)
    assert view["counts"]["hard_stops"] == 0
    assert view["hidden_warnings"] == 1, (
        "the picker row caps the score at 85 and draws no card here (Data "
        "Consistency owns it) - it must still be accounted for somewhere, or "
        "the screen reads 0 warnings")


def test_promotion_upgrades_the_existing_card_and_does_not_duplicate_it():
    """The warning becomes the hard stop. One row, not two. Kept for a payload
    stored before 19 Oct 2026, which still names the card it capped on."""
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]

    before = build_grouped_view(structured, hard, soft)
    assert before["counts"]["hard_stops"] == 0        # the defect
    # Since UI-13 the un-promoted picker row does not render as a warning here
    # either (Data Consistency owns it), which makes promotion the ONLY thing
    # keeping a capping conflict on this screen.
    _before_warn = before["counts"]["warnings"]

    # (19 Oct 2026: the building value is a warning) - only an OLD stored payload carries codes; the path still works for it.
    old_pkg = {"cap_hard_stop_codes": [_PICKER_CODE]}
    assert (grouped_with_package_caps(structured, hard, soft, old_pkg)["counts"]
            == build_grouped_view(structured, hard, soft,
                                  promote_codes=[_PICKER_CODE])["counts"])
    after = build_grouped_view(
        structured, hard, soft, promote_codes=old_pkg["cap_hard_stop_codes"])
    # Brent's "shown once" (owner, 30 Oct 2026; TEST updated): a FEIN / name
    # conflict - hard or promoted - shows in Data Consistency only, its row
    # reading "Holds the score at 60 until fixed"; the view draws no card for it
    # and accounts for it in `hidden_warning_messages`.
    assert after["counts"]["hard_stops"] == 0
    assert _WARN.strip() in (after.get("hidden_warning_messages") or [])
    # No card for it anywhere on this view (never twice: Data Consistency owns it).
    assert _all_messages(after).count(_WARN) == 0
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
    assert after["hidden_warnings"] == 1


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
    # (19 Oct 2026, Brent: a hard stop blocks Submission Ready) - and no blocker is invented.
    assert pkg["ready_blockers"] == [] and pkg["ready_blocker_items"] == []


def test_never_duplicates_a_stop_the_screen_already_shows():
    """A real hard stop already renders a card; the package cap stays quiet and
    nothing draws it twice."""
    pkg = _score(hard=["FEIN differs across uploaded documents."], soft=[])
    # (20 Oct 2026, the cap is back) - the stop holds the 60 and its own card says so.
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["cap_hard_stops"] == []
    # (19 Oct 2026, Brent: a hard stop blocks Submission Ready) - once.
    assert pkg["ready_blockers"] == ["FEIN differs across uploaded documents."]
    assert len(pkg["ready_blocker_items"]) == 1


def test_no_score_moved_by_this_change():
    """The whole fix is display. The cap and the number are what they were:
    the displayed score is the raw pillar sum held at its cap (20 Oct 2026, the
    caps are back) - 85 for warnings (the building value is one since 19 Oct
    2026), 60 for a hard stop - and the score trace's ceiling is that cap."""
    for pkg, cap in ((_score(), SOFT_STOP_CAP), (_score(uw={"fields": []}), SOFT_STOP_CAP),
                     (_score(hard=["FEIN differs across uploaded documents."], soft=[]),
                      HARD_STOP_CAP)):
        assert pkg["cap_applied"] == cap
        assert pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], cap)
        assert pkg["score_trace"]["arithmetic"]["ceiling"] == cap


@pytest.mark.parametrize("has_property", [True, False])
def test_every_package_blocker_is_said_somewhere(has_property):
    """THE INVARIANT, package half. Whatever holds the package at 60 is either
    already a hard stop the screen draws, or is in cap_hard_stops - and
    whatever blocks its Submission Ready is a hard stop with a row to fix it.
    A future cap or blocker source added to calculate_package_sqs cannot go
    silent without failing here.

    Both relevance branches are driven: the building-value conflict holds no 60
    and blocks in neither (a warning since 19 Oct 2026), so a hard cross issue
    - the one 60 the hard stops do not carry - is driven in both too.
    """
    flags = dict(_FLAGS, has_property_coverage=has_property)
    hard, soft = evaluate_stops(_FACTS, flags)
    _cross_msg = "Umbrella detected but no underlying GL or Auto limits found"
    crossed = calculate_package_sqs(
        facts=_FACTS, flags=flags, form_results=[], hard_stops=list(hard), soft_stops=list(soft),
        cross_issues=[{"type": "hard_stop", "code": "umbrella_no_underlying_coverage",
                       "message": _cross_msg}],
        session_data={"facts": _FACTS, "flags": flags, "docs": [],
                      "underwriting_consistency": _UW},
        session_id="t", user_id="t", calculation_stage="form_generated",
    )
    for pkg in (_score(flags=flags), crossed):
        # (20 Oct 2026, the cap is back) - a 60 is said on screen.
        if pkg["cap_applied"] == HARD_STOP_CAP:
            assert pkg["cap_reason"] in hard or pkg["cap_reason"] in pkg["cap_hard_stops"], (
                f"package held at 60 by {pkg['cap_reason']!r} with nothing on screen")
            assert pkg["cap_reason"] in [i["message"] for i in pkg["cap_hard_stop_items"]]
        assert pkg["cap_hard_stop_codes"] == []
        # (19 Oct 2026, Brent: a hard stop blocks the status) - the blockers ARE the hard stops.
        assert BUILDING_VALUE_CONFLICT_MSG not in pkg["ready_blockers"]
        assert [i["message"] for i in pkg["ready_blocker_items"]] == pkg["ready_blockers"]
        assert pkg["open_hard_stops"] == len(pkg["ready_blockers"])
    pkg = _score(flags=flags)
    assert pkg["cap_applied"] != HARD_STOP_CAP
    assert pkg["ready_blockers"] == list(dict.fromkeys(hard)), (
        f"package blocked by {pkg['ready_blockers']!r} with nothing on screen")
    assert crossed["cap_applied"] == HARD_STOP_CAP and crossed["cap_reason"] == _cross_msg
    assert crossed["cap_hard_stops"] == [_cross_msg]
    assert crossed["ready_blockers"] == list(dict.fromkeys(list(hard) + [_cross_msg]))


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
    # (19 Oct 2026, Brent: a differing building value is a warning) - nothing blocked.
    assert pkg["ready_blockers"] == list(dict.fromkeys(hard))
    assert BUILDING_VALUE_CONFLICT_MSG not in pkg["ready_blockers"]

    # Irrelevant means it costs nothing either: the scorer's own building-value
    # item needs property coverage (C75), so Exposure is the clean package's.
    assert building_value_cross_items(no_property, {"underwriting_consistency": _UW}) == []
    clean = calculate_package_sqs(
        facts=_FACTS, flags=no_property, form_results=[], cross_issues=[],
        hard_stops=list(hard), soft_stops=list(soft),
        session_data={"docs": [], "selected_form_ids": ["ACORD_125"],
                      "sqs_history": [], "underwriting_consistency": {"fields": []}},
    )
    assert pkg["package_sqs_score"] == clean["package_sqs_score"]

    # ...and it is NOT silently dropped: the conflict is still open, so the
    # warning it arrived as still holds the 85 (20 Oct 2026, the cap is back)
    # and is still accounted for on the Review screen.
    assert pkg["cap_applied"] == SOFT_STOP_CAP
    view = grouped_with_package_caps(
        [make_issue(_PICKER_CODE, "soft_warning", _WARN)], hard,
        list(soft) + [_WARN], pkg)
    assert view["counts"]["hard_stops"] == 0
    assert view["hidden_warnings"] == 1
