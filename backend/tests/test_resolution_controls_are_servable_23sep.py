"""A card must not offer a control the server cannot serve (2026-09-23).

Two live defects, reported minutes apart on one session, both the BUG-05 class:
the producer is told to fix something and handed nothing that fixes it.

DEFECT 1 - "Contact information" rendered TWICE, and a resolved Tier 1 item
could never leave the list. The ACORD 125 baseline warnings moved into
`evaluate_stops` earlier the same day, so they are rebuilt on every
recalculation - but they are coded `tier1_missing_<label>`, and
`_RECOMPUTED_CODE_PREFIXES` was `("legacy_",)`. `replace_recomputed_issues`
therefore PRESERVED the stale copy and appended the fresh one. Exactly the shape
that constant was widened for once before (2026-08-08): a recomputed issue whose
prefix nobody added outlives its own fix.

DEFECT 2 - the "Driver schedule not provided" warning offers `schedule` mode,
and opening it answered "This schedule is not available for the current forms."
`get_session_schedules` derived relevance from `generated_forms` alone while its
own docstring said "the session's SELECTED forms". Pre-generation both are
empty, so every schedule was filtered out - and this warning fires
pre-selection, because it is gated on `has_auto_coverage`, which exists as soon
as extraction finishes.
"""
import asyncio

import pytest

from services import schedule_capture
from services.issue_registry import (
    _RECOMPUTED_CODE_PREFIXES, make_issue, replace_recomputed_issues,
)

_T1_MSG = ("ACORD 125 minimum field missing: Contact information "
           "(Fix: Provide this value manually, or upload a document that states it.)")


# ── Defect 1 ────────────────────────────────────────────────────────────────

def test_a_recomputed_tier1_issue_replaces_its_stale_copy():
    stale = [make_issue("tier1_missing_Contact information", "soft_warning", _T1_MSG)]
    fresh = [make_issue("tier1_missing_Contact information", "soft_warning", _T1_MSG)]
    out = replace_recomputed_issues(stale, fresh)
    codes = [i["code"] for i in out]
    assert codes.count("tier1_missing_Contact information") == 1, (
        f"the Tier 1 row is duplicated across a recompute: {codes}"
    )


def test_a_fixed_tier1_issue_leaves_the_list():
    """It is rebuilt from the facts, so an empty rebuild means it is fixed."""
    stale = [make_issue("tier1_missing_Contact information", "soft_warning", _T1_MSG)]
    assert replace_recomputed_issues(stale, []) == []


def test_issues_nobody_recomputes_are_still_preserved():
    """The widening must not start discarding the sources this function exists
    to keep - a document conflict is not re-derived by a recalculation."""
    keep = [make_issue("doc_conflict_warn_dba_name", "soft_warning", "DBA differs")]
    assert replace_recomputed_issues(keep, []) == keep


def test_every_engine_emitted_code_prefix_is_recomputed():
    """ANTI-ROT. `evaluate_stops` output is rebuilt on every recalculation, so
    EVERY code its messages classify to must be in _RECOMPUTED_CODE_PREFIXES or
    the stale copy outlives its fix. Driven from the engine's own messages."""
    import ast
    import inspect
    import textwrap

    import services.sqs_service as sqs
    from services.issue_registry import classify_legacy

    src = textwrap.dedent(inspect.getsource(sqs.evaluate_stops))
    messages = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"):
            continue
        tgt = node.func.value
        if not (isinstance(tgt, ast.Name) and tgt.id in ("hard", "soft")) or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            messages.append(arg.value)
        elif isinstance(arg, ast.JoinedStr):
            lead = ""
            for v in arg.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    lead += v.value
                else:
                    break
            if lead:
                messages.append(lead)
    assert len(messages) > 15, f"harvest looks vacuous: {len(messages)}"

    bad = []
    for m in messages:
        # A Tier 1 sentence carries its label; give the harvested prefix one so
        # it classifies the way a real message would.
        probe = m + "Contact information" if m.rstrip().endswith(":") else m
        code, _c, _t = classify_legacy(probe, "soft_warning")
        if code and not code.startswith(_RECOMPUTED_CODE_PREFIXES):
            bad.append((code, m[:60]))
    assert not bad, (
        "evaluate_stops emits messages whose code is NOT recomputed, so a "
        f"resolved one will outlive its fix: {bad}"
    )


# ── Defect 2 ────────────────────────────────────────────────────────────────

def _run(coro):
    """`asyncio.run`, not `get_event_loop().run_until_complete`.

    These three tests passed alone and failed in the full suite: by the time
    they run, an earlier test has already created and closed the process-wide
    loop, so `get_event_loop()` returns a dead one (and on 3.12+ warns about
    there being no current loop at all). `asyncio.run` owns a fresh loop per
    call, which is what a synchronous test driving one coroutine needs."""
    return asyncio.run(coro)


@pytest.fixture
def _session(monkeypatch):
    """A pre-selection session: nothing generated, nothing selected, the
    recommender naming ACORD 127 - the live shape."""
    sess = {
        "facts": {}, "flags": {"has_auto_coverage": True},
        "generated_forms": {}, "selected_form_ids": [],
        "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_127"}],
    }

    async def _get(_sid):
        return sess

    import repositories.session_repository as sr
    monkeypatch.setattr(sr, "get_processing_session", _get)
    return sess


def test_a_schedule_opens_before_any_form_is_generated(_session):
    """THE REPORTED DEFECT. The warning fires pre-selection, so its table must
    open pre-selection."""
    from services.arq_service import get_session_schedules

    out = _run(get_session_schedules("s1", only_key="auto_drivers"))
    assert out, ("the driver table is unavailable before generation - the "
                 "warning offering it opens onto nothing")
    assert out[0]["schedule_key"] == "auto_drivers"
    assert "ACORD_127" in out[0]["form_ids"]


def test_an_irrelevant_schedule_is_still_withheld(_session):
    """The guarantee the old narrow rule was protecting: no Workers Comp
    class-code table on a package with no Workers Comp."""
    from services.arq_service import get_session_schedules

    assert _run(get_session_schedules("s1", only_key="wc_class_codes")) == []


def test_a_selected_but_ungenerated_form_also_counts(_session):
    from services.arq_service import get_session_schedules

    _session["recommendations"] = []
    _session["selected_form_ids"] = ["ACORD_127"]
    out = _run(get_session_schedules("s1", only_key="auto_drivers"))
    assert out and "ACORD_127" in out[0]["form_ids"]


def test_every_schedule_a_rule_offers_is_reachable_from_some_form():
    """ANTI-ROT, structural. A `schedule`-mode resolution naming a table that no
    ACORD form carries could never be served, whatever the session looks like."""
    from services.issue_registry import RESOLUTION_MAP, _LEGACY_CODE_RESOLUTIONS
    import glob
    import os
    import re

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "forms_schemas")
    form_ids = [re.sub(r"_schema\.json$", "", os.path.basename(p))
                for p in glob.glob(os.path.join(root, "*_schema.json"))]
    assert form_ids, "no schemas found - this guard would pass vacuously"

    carried = set()
    for fid in form_ids:
        try:
            carried |= set(schedule_capture.schedules_on_form(fid))
        except Exception:                                          # noqa: BLE001
            continue

    offered = {
        res["schedule_key"]
        for src in (RESOLUTION_MAP, _LEGACY_CODE_RESOLUTIONS)
        for res in src.values()
        if isinstance(res, dict) and res.get("mode") == "schedule"
        and res.get("schedule_key")
    }
    unreachable = sorted(offered - carried)
    assert not unreachable, (
        f"these rules offer a schedule no ACORD form carries: {unreachable} - "
        "the table can never be served and the card opens onto nothing"
    )


# ── Defect 3: the PACKAGE recommendations offered no control ────────────────
# Live 2026-09-23, on a generated package. The numbered package list rendered:
#   1. Loss History 25%   "No loss history provided..."
#   2. Narrative 40%      "Narrative includes ... but does not include ..."
#   3. Structural 69%     "FEIN / Tax ID"
# ALL THREE carried answer_mode "none" and the note "This one has no single
# value to fill - attach a supporting document or dismiss it with a note", while
# the FORM cards immediately beneath offered working controls for the first two
# and `fein` is an ordinary writable Tier 2 fact. One screen, two doors,
# opposite answers.
#
# Cause: `top_recs` entries are built from pillar rankings with
# `pillar`/`score`/`action`/`missing` and NO `field`, and
# `answer_routing.stamp_recommendations` routes on `rec["field"]`.

def test_package_recommendations_carry_a_routable_field():
    from services.sqs_service import _pillar_rec_field
    from services.answer_routing import answer_mode

    cases = [
        ("loss_history_alignment",
         "No loss history provided - required for carrier submission",
         "loss_history_no_prior_losses_indicator", "field"),
        ("loss_history_alignment",
         "If this business is a new venture with no prior operations, confirm "
         "New Venture status - Loss History will then be marked Not Applicable "
         "instead of counting against the score.",
         "new_venture_indicator", "field"),
        ("narrative_quality", "Narrative includes Operations Description, but "
         "does not include Account Overview",
         "additional_remarks_text", "narrative"),
        ("structural_completeness", "FEIN / Tax ID", "fein", "field"),
        ("structural_completeness", "Annual revenue", "total_revenue", "field"),
        ("structural_completeness", "Number of employees", "num_employees", "field"),
        ("structural_completeness", "Years in business", "years_in_business", "field"),
    ]
    for pillar, action, expect_fact, expect_mode in cases:
        got = _pillar_rec_field(pillar, action)
        assert got == expect_fact, f"{pillar}/{action[:40]!r} -> {got!r}"
        assert answer_mode(got, {})["mode"] == expect_mode, (
            f"{got} is not {expect_mode} per the one door"
        )


def test_an_unroutable_pillar_still_returns_none():
    """Returning None keeps the old `none` rendering. A pillar we cannot route
    must never be handed a typed box the write door would refuse."""
    from services.sqs_service import _pillar_rec_field

    assert _pillar_rec_field("exposure_consistency", "Improve exposure consistency") is None
    assert _pillar_rec_field("property_integrity", "Improve property integrity") is None
    assert _pillar_rec_field("structural_completeness", "Not A Real Label") is None
    assert _pillar_rec_field("loss_history_alignment", "") is None


def test_every_tier_label_the_scorer_can_emit_is_routable():
    """ANTI-ROT. `top_recs`' structural `action` is a Tier 1 / Tier 2 LABEL. If
    a label is ever added without a fact behind it, that row silently loses its
    control - which is exactly the defect this closed."""
    from services.sqs_service import (
        TIER1_FIELDS, TIER1_CONTACT, TIER2_FIELDS, _pillar_rec_field,
    )
    from services.arq_service import _canonical_key

    labels = list(TIER1_FIELDS.values()) + list(TIER2_FIELDS.values()) + [
        "Contact information", "NAICS or SIC industry code",
    ]
    assert len(labels) > 8, "label harvest looks vacuous"
    bad = []
    for label in labels:
        fact = _pillar_rec_field("structural_completeness", label)
        if not fact or not _canonical_key(fact):
            bad.append((label, fact))
    assert not bad, f"Tier labels with no writable fact behind them: {bad}"
    assert TIER1_CONTACT  # the any-one-of rule still has members


# ── The fix for Defect 2 had to narrow again, the same day ──────────────────
# Widening `get_session_schedules` to read `recommendations` fixed the reported
# defect and introduced a new one: that list is written ONCE at extraction and
# never pruned (`select_forms_bulk` writes only `selected_form_ids` /
# `generated_forms`), so a form the producer DECLINED kept contributing its
# schedules for the life of the session.
#
# Measured on a property package with 125 + 140 generated and 130 + 127 offered
# then declined: the endpoint served `wc_class_codes`, `wc_officers`,
# `auto_drivers` and `auto_vin_schedule`, labelled "Forms: 130" - breaking the
# function's own docstring guarantee that a property-only package is never shown
# a Workers Comp class-code table. `save_session_schedule` has no relevance gate,
# so it ACCEPTED the table, wrote `wc_class_codes` plus a derived
# `wc_payroll_by_state`, and returned success with `forms_updated: []`.
#
# The recommender is not a proxy for the package, and cannot be: it offers
# ACORD 130 at tier `needs_confirmation` on packages with no WC flag precisely
# so the producer can decline it. Declining is the designed path.

def _sessions():
    return {
        "pre_selection": {
            "facts": {}, "selected_form_ids": [], "generated_forms": {},
            "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_127"}],
        },
        "selected_not_generated": {
            "facts": {}, "selected_form_ids": ["ACORD_127"], "generated_forms": {},
            "recommendations": [],
        },
        "generated_with_declines": {
            "facts": {}, "selected_form_ids": ["ACORD_125", "ACORD_140"],
            "generated_forms": {"ACORD_125": {"schema": {}}, "ACORD_140": {"schema": {}}},
            "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_140"},
                                {"form_id": "ACORD_130"}, {"form_id": "ACORD_127"}],
        },
    }


@pytest.fixture
def _stage(monkeypatch):
    holder = {}

    async def _get(_sid):
        return holder["sess"]

    import repositories.session_repository as sr
    monkeypatch.setattr(sr, "get_processing_session", _get)
    return holder


def _keys(stage, name):
    from services.arq_service import get_session_schedules
    stage["sess"] = _sessions()[name]
    return {o["schedule_key"] for o in _run(get_session_schedules("s1"))}


def test_a_declined_form_stops_offering_its_schedules(_stage):
    """THE REGRESSION. Once anything is selected or generated, the recommender
    is no longer consulted - so a form the producer said no to contributes
    nothing."""
    keys = _keys(_stage, "generated_with_declines")
    assert "wc_class_codes" not in keys, (
        "a Workers Comp class-code table is being offered on a property-only "
        "package - the recommender's list is not the package"
    )
    assert "wc_officers" not in keys
    assert not (keys & {"auto_drivers", "auto_vin_schedule"}), (
        "ACORD 127 was declined; its schedules must not be offered"
    )


def test_the_original_pre_selection_fix_still_holds(_stage):
    """Narrowing must not undo what the widening was for."""
    keys = _keys(_stage, "pre_selection")
    assert "auto_drivers" in keys and "auto_vin_schedule" in keys
    assert "wc_class_codes" not in keys      # 130 was never recommended here


def test_selected_but_ungenerated_is_unaffected(_stage):
    keys = _keys(_stage, "selected_not_generated")
    assert "auto_drivers" in keys and "auto_vin_schedule" in keys


def test_the_recommender_is_a_fallback_not_a_union(_stage):
    """The invariant in one line: consulted only when nothing is chosen."""
    from services.arq_service import get_session_schedules
    sess = _sessions()["generated_with_declines"]
    _stage["sess"] = sess
    with_recs = {o["schedule_key"] for o in _run(get_session_schedules("s1"))}
    _stage["sess"] = dict(sess, recommendations=[])
    without = {o["schedule_key"] for o in _run(get_session_schedules("s1"))}
    assert with_recs == without, (
        "recommendations still change the answer after selection - they are "
        f"being unioned in, not used as a fallback: {with_recs ^ without}"
    )
