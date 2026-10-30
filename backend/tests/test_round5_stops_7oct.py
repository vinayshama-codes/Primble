"""Round 5 #15 (7 Oct 2026) - hard stops after generation (FX-STOPS).

Live session b248c194 (the owner's Choice Electric re-run, real AI fill). After
generation the session's `hard_stops` held three sentences for two problems:
the legacy "Property Minimum Viable COPE incomplete - missing: occupancy type"
AND its coded twin "Property submission missing Minimum Viable COPE: ...", plus
"Business Income limit is specified but Period of Restoration is missing" -
which was a WARNING before forms (C75 demotes cross-form hard stops while no
form is chosen; generation re-promotes them). Brent #18: "There were no Hard
Stops in the initial SQS prior to form selection, but there's Hard Stops now.
Why? This should all be addressable prior to forms."

TWO DISPLAY FIXES, no stop added or removed, no cap / score / severity moved
(C75 itself is Brent's pending decision and is untouched):

(a) ONE PROBLEM, ONE ROW, AT THE SEVERITY THAT IS APPLIED. Generation writes the
    stop LISTS at full force but never rewrites the structured card copies,
    which still carry the pre-form demotion. The grouped view decided severity
    twice: the twin rule called the coded COPE twin hard (its sentence is in the
    hard list) and hid the hard legacy copy, while the render loop drew that
    twin by its stale emitted severity - a warning. Measured on the stored
    session: the package page printed "No hard stops" beside a 60 cap held by
    two. Now one rule (`issue_registry._display_severity`) decides for both:
    the lists the scorer reads win. Corpus: 8 of 690 stored sessions drew a
    capping stop as a warning; all 8 now draw it hard, nothing else moved.
    Surfaces that print bare sentences (the Submission Brief, the Lite screen)
    collapse twins through the same rule (`issue_registry.stops_for_display`).

(b) BEFORE FORMS THE SCREEN SAYS WHAT GENERATION WILL MAKE A HARD STOP.
    `stops_now.becomes_hard_at_generation` reads the same cross-form run the
    C75 demotion reads and MEASURES which forms promote each warning; every
    pre-form payload carries it (`_pre_form_status`, `_pre_form_readiness`) and
    the grouped view tags the rows ("Becomes a hard stop when ACORD 140 is
    generated"); both Review layouts render the tag and "1 hard stop now, 1 more
    when forms are generated".

REVERSED 14 Oct 2026 (owner, one status from start to finish - see
`tests/test_one_status_14oct.py`): generation no longer re-promotes a
cross-form hard stop, so (b) is gone - nothing becomes a hard stop at
generation, and the backend emits no tag and no count. The (b) tests below now
pin that. (a) stays: it settles a row stored before that day, whose lists were
written at full severity.
"""
import ast
import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import stops_now as sn                                    # noqa: E402
from services.issue_registry import (                                   # noqa: E402
    _LEGACY_SUPERSEDED_BY_CODE, build_grouped_view, build_structured_from_sources,
    grouped_with_package_caps, make_issue, stops_for_display,
)

FRONTEND = BACKEND.parent / "frontend" / "src"
GEN_UTIL = FRONTEND / "utils" / "generationStops.js"
RAIL = FRONTEND / "components" / "form" / "review" / "ReviewRailLayout.jsx"
MODAL = FRONTEND / "components" / "form" / "AcordModal.jsx"

# The live sentences (rule wording only - no client text).
LEGACY = ("Property Minimum Viable COPE incomplete - missing: occupancy type "
          "Fix: Review and correct this before proceeding.")
CODED = ("Property submission missing Minimum Viable COPE: occupancy type. These "
         "fields are required to submit property to underwriting.")
BI = ("Business Income limit is specified but Period of Restoration is missing. "
      "Both are required when BI coverage is requested.")
AFFECTS = " (Affects: ACORD 140. Fix: Review the coverage/limit details for the affected form(s).)"
T1 = ("ACORD 125 minimum field missing: Applicant mailing address (Fix: Provide this "
      "value manually, or upload a document that states it.)")
GL = "GL coverage detected but no class codes found Fix: Review and correct this before proceeding."


def F(v, src="ai_high"):
    return {"value": v, "confidence": "filled", "source": src}


def _two_buildings() -> dict:
    """Two buildings at one premises (the live shape) - occupancy missing."""
    return {
        "property_locations": [
            {"location_id": "L1", "location_number": "1", "building_number": "1",
             "premises_label": "Prem. #: 001 Bldg #: 001",
             "construction_type": "FRAME", "building_value": "$798,556", "bpp_value": "$73,008"},
            {"location_id": "L2", "location_number": "1", "building_number": "2",
             "premises_label": "Prem. #: 001 Bldg #: 002",
             "construction_type": "FRAME", "building_value": "$421,714", "bpp_value": "$73,008"},
        ],
        "construction_type": "FRAME", "property_building_value": "$798,556",
        "property_bpp_value": "$73,008",
    }


def _cross(code, msg, type_="hard_stop"):
    return {"code": code, "type": type_, "message": msg, "forms": ["ACORD_140"]}


def _live_after_generation():
    """b248c194 as stored after generation: the card copies are the PRE-FORM
    ones (coded COPE + BI demoted to warnings), the lists are generation's."""
    structured = [
        make_issue("legacy_minimum_viable_cope", "hard_stop", LEGACY),
        make_issue("tier1_missing_Applicant mailing address", "soft_warning", T1),
        make_issue("legacy_gl_no_class_codes", "soft_warning", GL),
        make_issue("minimum_viable_cope_missing", "soft_warning", CODED, ["ACORD_140"]),
        make_issue("bi_missing_period_of_restoration", "soft_warning", BI, ["ACORD_140"]),
    ]
    hard = [LEGACY, CODED + AFFECTS, BI + AFFECTS]
    soft = [T1, GL]
    cross = [_cross("minimum_viable_cope_missing", CODED), _cross("bi_missing_period_of_restoration", BI)]
    pkg = {"cap_applied": 60, "cap_reason": LEGACY, "cap_hard_stops": [], "cap_hard_stop_codes": []}
    return structured, hard, soft, cross, pkg


def _rows(view, tier="all"):
    hard = [it for c in view["hard_stops"] for it in c["items"]]
    warn = [it for t in view["warnings"].values() for c in t for it in c["items"]]
    return {"hard": hard, "warn": warn, "all": hard + warn}[tier]


# ── (a) one problem, one row, at the severity the lists apply ────────────────

def test_after_generation_the_cope_twin_shows_once_and_both_stops_are_hard():
    structured, hard, soft, cross, pkg = _live_after_generation()
    view = grouped_with_package_caps(structured, hard, soft, pkg, cross_issues=cross,
                                     facts=_two_buildings())
    hard_rows = _rows(view, "hard")
    codes = sorted(r["code"] for r in hard_rows)
    assert codes == ["bi_missing_period_of_restoration", "minimum_viable_cope_missing"], codes
    assert view["counts"] == {"hard_stops": 2, "warnings": 2, "info": 0}
    # the COPE problem once - never the legacy sentence beside its twin
    assert not any(r["message"].startswith("Property Minimum Viable COPE incomplete")
                   for r in _rows(view))
    # the kept row carries the routed fix. On two buildings with only occupancy
    # missing it is that one box (21 Oct 2026, Brent 17 Oct item 8 - the TEST
    # pinned the whole-table window his "ask only what is missing" replaces).
    cope = next(r for r in hard_rows if r["code"] == "minimum_viable_cope_missing")
    assert cope["resolution"]["mode"] == "field"
    assert "schedule_key" not in cope["resolution"]
    assert cope["resolution"]["facts"] == ["occupancy_type"]


def test_before_the_fix_the_live_shape_drew_no_hard_stop_at_all():
    """THE DEFECT, pinned in the shape it was found: every sentence in the
    stored hard list is drawn as a hard row (directly or through its twin)."""
    structured, hard, soft, cross, pkg = _live_after_generation()
    view = grouped_with_package_caps(structured, hard, soft, pkg, cross_issues=cross)
    drawn = [r["message"] for r in _rows(view, "hard")]
    for sentence in hard:
        covered = any(sentence.startswith(m) for m in drawn)
        twin = any(p in sentence for p in _LEGACY_SUPERSEDED_BY_CODE.values()) and any(
            m.startswith(CODED) for m in drawn)
        assert covered or twin, f"a capping stop is not drawn as a hard stop: {sentence[:60]}"


def test_old_lists_keep_the_hard_legacy_row_and_hide_the_demoted_twin():
    """Stored before 6 Oct (4d70d6b2 / cda0d536): the legacy copy is the hard
    stop, the coded copy sits in the SOFT list while `cross_issues_last` still
    says hard. The lists decide - the legacy row is the blocker, shown once."""
    structured = [make_issue("legacy_minimum_viable_cope", "hard_stop", LEGACY)]
    view = build_grouped_view(structured, [LEGACY], [CODED + AFFECTS],
                              cross_issues=[_cross("minimum_viable_cope_missing", CODED)])
    assert [r["code"] for r in _rows(view, "hard")] == ["legacy_minimum_viable_cope"]
    assert not any(r["code"] == "minimum_viable_cope_missing" for r in _rows(view))
    assert view["counts"] == {"hard_stops": 1, "warnings": 0, "info": 0}


def test_a_gate_cap_reads_as_the_hard_stop_it_is():
    """ac300073 / 10d39f15: the package held at 60 by a stop with no card of its
    own (`cap_hard_stops`), its only card a stale warning copy - the card now
    matches the cap (owner, 2026-08-31)."""
    structured = [make_issue("bi_missing_period_of_restoration", "soft_warning", BI, ["ACORD_140"])]
    pkg = {"cap_applied": 60, "cap_reason": BI, "cap_hard_stops": [BI], "cap_hard_stop_codes": []}
    view = grouped_with_package_caps(structured, [], [], pkg)
    assert [r["code"] for r in _rows(view, "hard")] == ["bi_missing_period_of_restoration"]
    assert view["counts"] == {"hard_stops": 1, "warnings": 0, "info": 0}


@pytest.mark.parametrize("legacy_sev,coded_sev,kept,kept_sev", [
    ("hard_stop", "hard_stop", "minimum_viable_cope_missing", "hard_stop"),
    ("hard_stop", "soft_warning", "legacy_minimum_viable_cope", "hard_stop"),
    ("soft_warning", "soft_warning", "minimum_viable_cope_missing", "soft_warning"),
    ("soft_warning", "hard_stop", "minimum_viable_cope_missing", "hard_stop"),
])
def test_consistent_twins_keep_their_rule(legacy_sev, coded_sev, kept, kept_sev):
    """Every consistent pairing keeps the 6 Oct contract: shown once, the coded
    row kept unless that would hide a hard legacy stop behind a warning."""
    structured = [make_issue("legacy_minimum_viable_cope", legacy_sev, LEGACY),
                  make_issue("minimum_viable_cope_missing", coded_sev, CODED, ["ACORD_140"])]
    hard = [m for m, s in ((LEGACY, legacy_sev), (CODED + AFFECTS, coded_sev)) if s == "hard_stop"]
    soft = [m for m, s in ((LEGACY, legacy_sev), (CODED + AFFECTS, coded_sev)) if s != "hard_stop"]
    rows = _rows(build_grouped_view(structured, hard, soft))
    assert [(r["code"], r["severity"]) for r in rows] == [(kept, kept_sev)]


def test_the_view_never_mutates_the_scorer_lists():
    structured, hard, soft, cross, pkg = _live_after_generation()
    before = copy.deepcopy((structured, hard, soft, cross, pkg))
    grouped_with_package_caps(structured, hard, soft, pkg, cross_issues=cross, facts=_two_buildings())
    assert (structured, hard, soft, cross, pkg) == before


def test_the_editor_hard_stops_block_names_the_cope_problem_once_with_its_fix():
    """The editor's package HARD STOPS block prints the scorer's own cap
    reason - one sentence, never a twin pair - with the routed table fix."""
    from services.sqs_service import _cap_stop_items
    _s, _h, _so, cross, _p = _live_after_generation()
    items = _cap_stop_items([LEGACY], coded_issues=cross, facts=_two_buildings())
    assert len(items) == 1
    assert items[0]["code"] == "legacy_minimum_viable_cope"
    # Only occupancy missing on two buildings: just that box, the same routed
    # fix the review draws (21 Oct 2026, Brent 17 Oct item 8 - the TEST pinned
    # the whole-table window).
    assert items[0]["resolution"]["mode"] == "field"
    assert items[0]["resolution"]["facts"] == ["occupancy_type"]
    # A per-building item missing still opens the table, per building.
    two = _two_buildings()
    two.pop("construction_type")
    two["property_locations"][1]["construction_type"] = ""
    msg = LEGACY.replace("occupancy type", "occupancy type, construction type")
    items = _cap_stop_items([msg], coded_issues=[], facts=two)
    assert items[0]["resolution"]["mode"] == "schedule"
    assert items[0]["resolution"]["schedule_key"] == "property_locations"
    assert items[0]["resolution"]["columns"] == ["construction_type"]


def test_the_scorer_still_reads_both_twins():
    """Display only: the door's lists - what caps the score - keep every
    sentence, the twin included; only what is DRAWN collapses.

    14 Oct 2026 (one status from start to finish): after forms the coded twin
    and BI keep the WARNING status they had before forms - the TEST pinned the
    re-promotion the owner removed; the field-level legacy copy stays hard."""
    facts = dict(_two_buildings(), business_income_limit=F("$100,000"))
    out = sn.stops_now({"facts": facts, "flags": {"has_property_coverage": True}},
                       ["ACORD_140"], pre_form=False)
    assert any("Minimum Viable COPE incomplete" in m for m in out["hard"])
    assert any(m.startswith("Property submission missing Minimum Viable COPE") for m in out["soft"])
    assert any(m.startswith(BI) for m in out["soft"])
    assert not any(m.startswith(BI) or m.startswith("Property submission missing") for m in out["hard"])


# ── the bare-sentence door (Submission Brief, Lite screen) ───────────────────

def test_stops_for_display_after_generation_prints_each_problem_once():
    _s, hard, soft, cross, _p = _live_after_generation()
    before = (list(hard), list(soft))
    shown_hard, shown_soft = stops_for_display(hard, soft, cross)
    assert shown_hard == [CODED + AFFECTS, BI + AFFECTS]
    assert shown_soft == soft
    assert (hard, soft) == before, "the caller's lists are not mutated"


def test_stops_for_display_before_forms_keeps_the_hard_legacy_stop():
    soft_in = [CODED + AFFECTS, BI + AFFECTS, GL]
    cross = [_cross("minimum_viable_cope_missing", CODED, "soft_warning"),
             _cross("bi_missing_period_of_restoration", BI, "soft_warning")]
    shown_hard, shown_soft = stops_for_display([LEGACY], soft_in, cross)
    assert shown_hard == [LEGACY]
    assert shown_soft == [BI + AFFECTS, GL]


def test_stops_for_display_touches_nothing_it_cannot_name():
    hard, soft = [LEGACY, "Something else entirely"], [GL]
    # no coded issue at all / a coded twin that is in neither list
    assert stops_for_display(hard, soft, None) == (hard, soft)
    assert stops_for_display(hard, soft, [_cross("minimum_viable_cope_missing", CODED)]) == (hard, soft)
    # two warnings: the legacy copy goes, the coded one stays
    assert stops_for_display([], [LEGACY, CODED + AFFECTS],
                             [_cross("minimum_viable_cope_missing", CODED, "soft_warning")]) \
        == ([], [CODED + AFFECTS])
    assert stops_for_display(None, None, None) == ([], [])


def test_the_brief_and_the_lite_screen_print_through_the_door():
    src = (BACKEND / "routes" / "download_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("lite_cover_sheet", "lite_analyze"):
        calls = {getattr(c.func, "id", getattr(c.func, "attr", None))
                 for c in ast.walk(fns[name]) if isinstance(c, ast.Call)}
        assert "stops_for_display" in calls, name
    brief = ast.get_source_segment(src, fns["lite_cover_sheet"])
    assert "hard_stops=_shown_hard, soft_stops=_shown_soft" in brief
    # ...while the scorer keeps the door's own lists
    assert "hard_stops=hard_stops, soft_stops=soft_stops" in brief


# ── (b) REVERSED 14 Oct 2026: nothing becomes a hard stop at generation ──────
# The tests here pinned `becomes_hard_at_generation` / `generation_tag` and the
# tagged rows. The TEST was right for the 7 Oct rule and is wrong for the
# owner's 14 Oct decision (a check keeps its status before and after forms),
# so it now pins the reversal.

def _property_session(recs=("ACORD_125", "ACORD_140")):
    from datetime import datetime, timedelta

    def _in_days(days):
        return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")

    # A proposed term (19 Oct 2026, Brent: without one the package carries a hard
    # stop of its own - these tests are about COPE and BI, not the term).
    facts = dict(_two_buildings(), business_income_limit=F("$100,000"),
                 locations=F([{"address": "1 Main St, Denver, CO 80221"}]),
                 effective_date=F(_in_days(30)), expiration_date=F(_in_days(395)))
    return {"facts": facts, "flags": {"has_property_coverage": True},
            "recommendations": [{"form_id": f} for f in recs]}


def test_the_live_pair_stays_a_warning_on_acord_140():
    session = _property_session()
    assert not hasattr(sn, "becomes_hard_at_generation")
    gen = sn.stops_now(session, ["ACORD_125", "ACORD_140"], pre_form=False)
    assert not any(m.startswith(BI) or m.startswith("Property submission missing") for m in gen["hard"])
    assert {i["code"]: i["type"] for i in gen["cross_issues"]
            if i["code"] in ("minimum_viable_cope_missing", "bi_missing_period_of_restoration")} == {
        "minimum_viable_cope_missing": "soft_warning", "bi_missing_period_of_restoration": "soft_warning"}


def test_no_generation_tag_and_the_shims_are_gone():
    # 14 Oct 2026: the retired helpers (`becomes_hard_at_generation`,
    # `with_generation_hard_stops`) were removed once nothing called them.
    for name in ("generation_tag", "becomes_hard_at_generation", "with_generation_hard_stops"):
        assert not hasattr(sn, name), name
    src = (BACKEND / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    assert "with_generation_hard_stops" not in src


def _pre_form_view(session):
    """The pre-form Review screen as the pipeline builds it: legacy rows from
    `evaluate_stops`, the C75-demoted cross-form rows, the door's lists."""
    st = sn.stops_now(session, None, pre_form=True)
    structured = build_structured_from_sources(legacy_hard=st["evaluate_hard"],
                                               legacy_soft=st["evaluate_soft"],
                                               cross_issues=st["cross_issues"])
    return structured, st


def test_the_pre_form_screen_carries_no_becomes_hard_tag():
    session = _property_session()
    structured, st = _pre_form_view(session)
    view = grouped_with_package_caps(structured, st["hard"], st["soft"], {}, facts=session["facts"])
    # the COPE problem is ONE hard stop (the legacy copy; its demoted twin is
    # hidden) and BI is a warning - exactly what generation will score
    assert [r["code"] for r in _rows(view, "hard")] == ["legacy_minimum_viable_cope"]
    assert ("bi_missing_period_of_restoration", "soft_warning") in \
        [(r["code"], r["severity"]) for r in _rows(view)]
    assert not any(r.get("becomes_hard_tag") for r in _rows(view))
    assert "becomes_hard" not in view


def test_every_pre_form_payload_carries_none(monkeypatch):
    """`_pre_form_status` (the five form_routes responses) and
    `_pre_form_readiness` (resolve / reopen) - one shape, no generation list."""
    from routes import form_routes as fr
    from routes import audit_routes as ar
    from services import form_dry_run as fdr

    async def no_dry(*a, **k):
        return None

    monkeypatch.setattr(fdr, "dry_run_payload", no_dry)
    monkeypatch.setattr(fr, "current_package_sqs", lambda *a, **k: {"package_sqs_score": 41})
    row = _property_session()
    pkg, _kd = asyncio.run(fr._pre_form_status("sid-r5", row["facts"], row["flags"], {},
                                               {"id": "u"}, session_row=row))
    assert pkg == {"package_sqs_score": 41}
    card = asyncio.run(ar._pre_form_readiness(row, "sid-r5", {"id": "u"},
                                              scored={"package_sqs_score": 41}))
    assert "becomes_hard_at_generation" not in (card["package_sqs"] or {})


def test_the_grouped_view_no_longer_reads_it():
    src = (BACKEND / "services" / "issue_registry.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "grouped_with_package_caps")
    seg = ast.get_source_segment(src, fn)
    assert "becomes_hard=" not in seg


# ── the two Review layouts ───────────────────────────────────────────────────
# 14 Oct 2026: the frontend leftovers of the retired "becomes a hard stop" rule
# are gone - `utils/generationStops.js` (its helpers and their unit test,
# `test_the_progress_line_wording`, deleted with it) and the per-row
# `BecomesHardTag`. `test_both_layouts_render_it` is rewritten below to pin
# the opposite: neither layout renders a tag the backend no longer sends.

def test_both_layouts_render_no_becomes_hard_tag():
    assert not GEN_UTIL.exists(), "utils/generationStops.js is retired"
    modal = MODAL.read_text(encoding="utf-8")
    rail = RAIL.read_text(encoding="utf-8")
    for name, text in (("AcordModal", modal), ("ReviewRailLayout", rail)):
        for gone in ("generationStops", "BecomesHardTag", "becomes_hard_tag", "becomesHardCount",
                     "laterHard"):
            assert gone not in text, f"{name} still carries {gone}"
    # the rows still go through the ONE per-row action door both layouts call
    assert ("renderItemActions={(it, forms, tone) => itemResolveAndStatus(it, forms, "
            "{ reviewScreen: true, tone })}") in modal


def test_no_layout_announces_a_future_hard_stop():
    """REVERSED 8 Oct 2026 (owner). Brent's item 18 ASKED why hard stops
    appeared after generation; he did not ask for the answer to be printed.

    The two SENTENCES are gone from both layouts - "1 hard stop now, 1 more
    when forms are generated" on the Overview tile and "1 warning becomes a
    hard stop when forms are generated." in the Hard Stops section. A sentence
    announcing a future problem, in a section where nothing can be done about
    it, is not a fix.

    The per-row `becomes_hard_tag` and the helpers were removed on 14 Oct 2026
    (a check keeps one status before and after forms); this still pins that no
    layout renders the sentences."""
    modal = MODAL.read_text(encoding="utf-8")
    rail = RAIL.read_text(encoding="utf-8")
    for name, text in (("AcordModal", modal), ("ReviewRailLayout", rail)):
        assert "hardStopsNowAndLaterText(" not in text, (
            f"{name} renders the 'N hard stops now, M more' sentence again")
        assert "laterHardStopsNote(" not in text, (
            f"{name} renders the 'becomes a hard stop' sentence again")
