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
    assert view["counts"] == {"hard_stops": 2, "warnings": 2}
    # the COPE problem once - never the legacy sentence beside its twin
    assert not any(r["message"].startswith("Property Minimum Viable COPE incomplete")
                   for r in _rows(view))
    # the kept row carries the routed fix: on two buildings it opens the table
    cope = next(r for r in hard_rows if r["code"] == "minimum_viable_cope_missing")
    assert cope["resolution"]["mode"] == "schedule"
    assert cope["resolution"]["schedule_key"] == "property_locations"
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
    assert view["counts"] == {"hard_stops": 1, "warnings": 0}


def test_a_gate_cap_reads_as_the_hard_stop_it_is():
    """ac300073 / 10d39f15: the package held at 60 by a stop with no card of its
    own (`cap_hard_stops`), its only card a stale warning copy - the card now
    matches the cap (owner, 2026-08-31)."""
    structured = [make_issue("bi_missing_period_of_restoration", "soft_warning", BI, ["ACORD_140"])]
    pkg = {"cap_applied": 60, "cap_reason": BI, "cap_hard_stops": [BI], "cap_hard_stop_codes": []}
    view = grouped_with_package_caps(structured, [], [], pkg)
    assert [r["code"] for r in _rows(view, "hard")] == ["bi_missing_period_of_restoration"]
    assert view["counts"] == {"hard_stops": 1, "warnings": 0}


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
    assert items[0]["resolution"]["mode"] == "schedule"
    assert items[0]["resolution"]["schedule_key"] == "property_locations"


def test_the_scorer_still_reads_both_twins():
    """Display only: the door's lists - what caps the score - keep every
    sentence, the twin included; only what is DRAWN collapses."""
    facts = dict(_two_buildings(), business_income_limit=F("$100,000"))
    out = sn.stops_now({"facts": facts, "flags": {"has_property_coverage": True}},
                       ["ACORD_140"], pre_form=False)
    assert any("Minimum Viable COPE incomplete" in m for m in out["hard"])
    assert any(m.startswith("Property submission missing Minimum Viable COPE") for m in out["hard"])
    assert any(m.startswith(BI) for m in out["hard"])


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


# ── (b) before forms: what generation will make a hard stop ──────────────────

def _property_session(recs=("ACORD_125", "ACORD_140")):
    facts = dict(_two_buildings(), business_income_limit=F("$100,000"),
                 locations=F([{"address": "1 Main St, Denver, CO 80221"}]))
    return {"facts": facts, "flags": {"has_property_coverage": True},
            "recommendations": [{"form_id": f} for f in recs]}


def test_the_live_pair_becomes_hard_on_acord_140():
    out = sn.becomes_hard_at_generation(_property_session())
    by_code = {e["code"]: e for e in out}
    assert set(by_code) == {"minimum_viable_cope_missing", "bi_missing_period_of_restoration"}
    for e in out:
        assert e["forms"] == ["ACORD_140"]
        assert e["tag"] == "Becomes a hard stop when ACORD 140 is generated"
        assert "—" not in e["tag"]


def test_the_forms_are_measured_not_read_off_the_affects_list():
    # BI fires on ACORD 140 OR 160: either alone makes it a hard stop (named
    # in form order, whatever order the recommender listed them in).
    out = {e["code"]: e for e in sn.becomes_hard_at_generation(
        _property_session(("ACORD_125", "ACORD_160", "ACORD_140")))}
    assert out["bi_missing_period_of_restoration"]["tag"] == \
        "Becomes a hard stop when ACORD 140 or ACORD 160 is generated"
    assert out["minimum_viable_cope_missing"]["forms"] == ["ACORD_140"]
    # WC payroll names ACORD 125 beside ACORD 130, but only ACORD 130 triggers it.
    wc = {"facts": {"wc_payroll": F("100000"), "total_payroll": F("500000")},
          "flags": {"has_workers_comp": True},
          "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_130"}]}
    assert [(e["code"], e["forms"]) for e in sn.becomes_hard_at_generation(wc)] == \
        [("wc_payroll_mismatch", ["ACORD_130"])]
    # a rule no form gates fires on any generation
    umb = {"facts": {}, "flags": {"has_umbrella": True},
           "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_131"}]}
    tags = {e["code"]: e["tag"] for e in sn.becomes_hard_at_generation(umb)}
    assert tags["umbrella_no_underlying_coverage"] == "Becomes a hard stop when forms are generated"


def test_nothing_becomes_hard_after_forms_or_while_integrity_is_pending():
    base = _property_session()
    assert sn.becomes_hard_at_generation(dict(base, generated_forms={"ACORD_140": {}})) == []
    assert sn.becomes_hard_at_generation(dict(base, integrity={"review_required": True})) == []
    assert sn.becomes_hard_at_generation(dict(base, recommendations=[])) == []
    assert sn.becomes_hard_at_generation(dict(base, flags={})) == []
    assert sn.becomes_hard_at_generation(None) == []


def test_generation_tag_wording():
    assert sn.generation_tag([]) == "Becomes a hard stop when forms are generated"
    assert sn.generation_tag(["ACORD_140"]) == "Becomes a hard stop when ACORD 140 is generated"
    assert sn.generation_tag(["ACORD_127", "ACORD_131"]) == \
        "Becomes a hard stop when ACORD 127 and ACORD 131 are generated"
    assert sn.generation_tag(["ACORD_140", "ACORD_160"], all_needed=False) == \
        "Becomes a hard stop when ACORD 140 or ACORD 160 is generated"
    assert sn.generation_tag(["ACORD_125", "ACORD_130", "ACORD_131__excess"]) == \
        "Becomes a hard stop when ACORD 125, ACORD 130 and ACORD 131 (Excess) are generated"


def test_the_payload_copy_keeps_shape_when_there_is_nothing_to_say():
    pkg = {"package_sqs_score": 70}
    assert sn.with_generation_hard_stops(pkg, {"facts": {}, "flags": {}}) is pkg
    assert sn.with_generation_hard_stops(None, _property_session()) is None
    before = copy.deepcopy(pkg)
    out = sn.with_generation_hard_stops(pkg, _property_session())
    assert out is not pkg and pkg == before
    assert [e["code"] for e in out["becomes_hard_at_generation"]] == \
        ["minimum_viable_cope_missing", "bi_missing_period_of_restoration"]


def _pre_form_view(session):
    """The pre-form Review screen as the pipeline builds it: legacy rows from
    `evaluate_stops`, the C75-demoted cross-form rows, the door's lists."""
    st = sn.stops_now(session, None, pre_form=True)
    structured = build_structured_from_sources(legacy_hard=st["evaluate_hard"],
                                               legacy_soft=st["evaluate_soft"],
                                               cross_issues=st["cross_issues"])
    return structured, st


def test_the_pre_form_screen_tags_the_warning_and_counts_it_once():
    session = _property_session()
    structured, st = _pre_form_view(session)
    plain = grouped_with_package_caps(structured, st["hard"], st["soft"], {}, facts=session["facts"])
    pkg = sn.with_generation_hard_stops({}, session)
    view = grouped_with_package_caps(structured, st["hard"], st["soft"], pkg, facts=session["facts"])
    # tagging never moves a row or a count
    assert view["counts"] == plain["counts"]
    assert [r["code"] for r in _rows(view)] == [r["code"] for r in _rows(plain)]
    # the COPE problem is ONE hard stop now (the legacy copy; its demoted twin
    # is hidden, so it is neither tagged nor counted as "more")
    assert [r["code"] for r in _rows(view, "hard")] == ["legacy_minimum_viable_cope"]
    tagged = [r for r in _rows(view) if r.get("becomes_hard_tag")]
    assert [(r["code"], r["severity"]) for r in tagged] == \
        [("bi_missing_period_of_restoration", "soft_warning")]
    assert tagged[0]["becomes_hard_tag"] == "Becomes a hard stop when ACORD 140 is generated"
    assert tagged[0]["becomes_hard_forms"] == ["ACORD_140"]
    assert view["becomes_hard"] == 1 and plain["becomes_hard"] == 0


def test_a_hard_row_is_never_tagged():
    entries = [{"code": "minimum_viable_cope_missing", "message": CODED, "forms": ["ACORD_140"],
                "tag": "Becomes a hard stop when ACORD 140 is generated"}]
    view = build_grouped_view([make_issue("minimum_viable_cope_missing", "hard_stop", CODED)],
                              [CODED], [], becomes_hard=entries)
    assert view["becomes_hard"] == 0
    assert not any(r.get("becomes_hard_tag") for r in _rows(view))


def test_every_pre_form_payload_carries_it(monkeypatch):
    """`_pre_form_status` (the five form_routes responses) and
    `_pre_form_readiness` (resolve / reopen) - one shape."""
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
    assert [e["code"] for e in pkg["becomes_hard_at_generation"]] == \
        ["minimum_viable_cope_missing", "bi_missing_period_of_restoration"]
    # after forms: the persisted package, untouched
    done = dict(row, generated_forms={"ACORD_140": {}})
    pkg2, _ = asyncio.run(fr._pre_form_status("sid-r5", row["facts"], row["flags"], {},
                                              {"id": "u"}, session_row=done))
    assert pkg2 == {"package_sqs_score": 41}
    # the resolve / reopen card, scored by the recalc
    card = asyncio.run(ar._pre_form_readiness(row, "sid-r5", {"id": "u"},
                                              scored={"package_sqs_score": 41}))
    assert [e["code"] for e in card["package_sqs"]["becomes_hard_at_generation"]] == \
        ["minimum_viable_cope_missing", "bi_missing_period_of_restoration"]


def test_the_grouped_view_reads_it_from_the_door_package():
    src = (BACKEND / "services" / "issue_registry.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "grouped_with_package_caps")
    seg = ast.get_source_segment(src, fn)
    assert 'becomes_hard=pkg.get("becomes_hard_at_generation")' in seg


# ── the two Review layouts ───────────────────────────────────────────────────

def _run_node(tmp_path, body: str) -> dict:
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as G from {json.dumps(GEN_UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_progress_line_wording(tmp_path):
    out = _run_node(tmp_path, """
console.log(JSON.stringify({
  a: G.hardStopsNowAndLaterText(1, 1),
  b: G.hardStopsNowAndLaterText(0, 1),
  c: G.hardStopsNowAndLaterText(2, 3),
  d: G.hardStopsNowAndLaterText(2, 0),
  e: G.laterHardStopsNote(1),
  f: G.laterHardStopsNote(2),
  g: G.laterHardStopsNote(0),
  h: G.becomesHardCount({ becomes_hard: 2 }),
  i: G.becomesHardCount(null),
  j: G.becomesHardCount({ becomes_hard: "x" }),
}));""")
    assert out["a"] == "1 hard stop now, 1 more when forms are generated"
    assert out["b"] == "No hard stops now, 1 when forms are generated"
    assert out["c"] == "2 hard stops now, 3 more when forms are generated"
    assert out["d"] is None and out["g"] is None
    assert out["e"] == "1 warning becomes a hard stop when forms are generated."
    assert out["f"] == "2 warnings become hard stops when forms are generated."
    assert (out["h"], out["i"], out["j"]) == (2, 0, 0)


def test_both_layouts_render_it():
    modal = MODAL.read_text(encoding="utf-8")
    rail = RAIL.read_text(encoding="utf-8")
    util = GEN_UTIL.read_text(encoding="utf-8")
    # the per-row tag lives in the ONE per-row action door both layouts call
    # (8 Oct 2026: the door takes the review screen's context - no Resolve there,
    # the page rides along with a status - and the rail passes it in.)
    start = modal.index("const itemResolveAndStatus = (it, forms, ctx = {}) => {")
    door = modal[start:modal.index("const sectionProgress", start)]
    assert door.count("<BecomesHardTag text={becomesHard} />") == 2, "both return branches"
    assert ("renderItemActions={(it, forms, tone) => itemResolveAndStatus(it, forms, "
            "{ reviewScreen: true, tone })}") in modal                # the rail's rows
    for text in (util, door):
        assert "—" not in text, "no em-dashes in UI copy"


def test_no_layout_announces_a_future_hard_stop():
    """REVERSED 8 Oct 2026 (owner). Brent's item 18 ASKED why hard stops
    appeared after generation; he did not ask for the answer to be printed.

    The two SENTENCES are gone from both layouts - "1 hard stop now, 1 more
    when forms are generated" on the Overview tile and "1 warning becomes a
    hard stop when forms are generated." in the Hard Stops section. A sentence
    announcing a future problem, in a section where nothing can be done about
    it, is not a fix.

    The per-row `becomes_hard_tag` STAYS (pinned above): it sits beside that
    row's own "Open to fix", where a person can act on it. The helpers keep
    their unit tests - they are still exported and still correct - this only
    pins that no layout renders their sentences."""
    modal = MODAL.read_text(encoding="utf-8")
    rail = RAIL.read_text(encoding="utf-8")
    for name, text in (("AcordModal", modal), ("ReviewRailLayout", rail)):
        assert "hardStopsNowAndLaterText(" not in text, (
            f"{name} renders the 'N hard stops now, M more' sentence again")
        assert "laterHardStopsNote(" not in text, (
            f"{name} renders the 'becomes a hard stop' sentence again")
