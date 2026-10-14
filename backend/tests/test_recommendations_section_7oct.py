"""Choice Electric #22 / #27 (7 Oct 2026) - the package page's Recommendations
section (implementer RECS).

Brent #22: "All of these Recommendation items should be addressable prior to
(and independently of) the forms." #27: to-dos "earlier in the workflow" and
"accurate requests" - 176 items was too many.

The section has two groups, each read off a list the product already computes:
  "Raise your score"     - the package scorer's Best Solutions rows a person
                           can answer; the server attaches the fix window each
                           opens (`services/review_recommendations`).
  "Your forms will need" - before forms the "Before you generate" dry run,
                           after forms the editor's needs-attention Missing
                           rows.
One to-do, one place: what a Hard Stop / Warning card or a key-details link
already asks for is not repeated (`frontend/src/utils/recommendations.js`, run
here under node).
"""
import ast
import asyncio
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services import review_recommendations as rr

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
UTIL = FRONTEND / "utils" / "recommendations.js"
RECS_JSX = FRONTEND / "components" / "form" / "review" / "Recommendations.jsx"
RAIL = FRONTEND / "components" / "form" / "review" / "ReviewRailLayout.jsx"
MODAL = FRONTEND / "components" / "form" / "AcordModal.jsx"
BYG = FRONTEND / "components" / "form" / "review" / "BeforeYouGenerate.jsx"


# The shapes the live Choice Electric session (7 Oct, pre-form) produced, with
# the values that matter for routing - no client text.
def _best_solutions():
    return [
        {"pillar": "hard_stops_present", "action": "Property COPE incomplete", "field": None,
         "answer_mode": "none", "points_available": None},
        {"pillar": "structural_completeness", "action": "Applicant mailing address",
         "field": "mailing_address", "answer_mode": "field", "points_available": 15.2,
         "answer_gain": 2, "answer_gain_is_exact": True, "closes_with": "type"},
        {"pillar": "property_integrity", "action": "Improve property integrity", "field": None,
         "answer_mode": "none", "points_available": 15.0, "closes_with": "review"},
        {"pillar": "loss_history_alignment", "action": "No loss history provided",
         "field": "loss_history_no_prior_losses_indicator", "answer_mode": "field",
         "points_available": 11.2, "answer_gain": 3, "answer_gain_is_exact": True,
         "closes_with": "type"},
        {"pillar": "narrative_quality", "action": "Narrative lacks Account Overview",
         "field": "additional_remarks_text", "answer_mode": "narrative",
         "points_available": 5.1, "closes_with": "type"},
    ]


# ── 1. The fix window on each Best Solutions row (backend) ───────────────────

def test_answerable_rows_get_the_cards_own_fix_window():
    pkg = {"package_sqs_score": 42, "top_recommendations": _best_solutions()}
    out = rr.with_fix_routes(pkg, {})
    rows = {r["pillar"]: r for r in out["top_recommendations"]}
    from services.issue_registry import field_resolution
    assert rows["loss_history_alignment"]["resolution"] == field_resolution(
        "loss_history_no_prior_losses_indicator")
    # The same choices a card on that fact offers (a select, not a text box).
    ctl = rows["loss_history_alignment"]["resolution"]["controls"]["loss_history_no_prior_losses_indicator"]
    assert ctl["control"] == "select" and ctl["options"]
    assert rows["structural_completeness"]["resolution"]["facts"] == ["mailing_address"]
    assert rows["narrative_quality"]["resolution"] == {"mode": "narrative"}
    for pillar in ("hard_stops_present", "property_integrity"):
        assert "resolution" not in rows[pillar]


def test_the_score_and_the_stored_package_are_untouched():
    rows = _best_solutions()
    pkg = {"package_sqs_score": 42, "tier": "Not Ready", "top_recommendations": rows}
    before = copy.deepcopy(pkg)
    out = rr.with_fix_routes(pkg, {})
    assert pkg == before                                  # never mutates (persisted after forms)
    assert out is not pkg and out["top_recommendations"] is not rows
    assert {k: v for k, v in out.items() if k != "top_recommendations"} == \
        {k: v for k, v in pkg.items() if k != "top_recommendations"}
    stripped = [{k: v for k, v in r.items() if k != "resolution"} for r in out["top_recommendations"]]
    assert stripped == before["top_recommendations"]


@pytest.mark.parametrize("pkg", [None, {}, {"package_sqs_score": 1}, {"top_recommendations": []},
                                 {"top_recommendations": "x"}, "nope"])
def test_anything_that_is_not_a_scored_package_passes_through(pkg):
    assert rr.with_fix_routes(pkg, {}) is pkg


def test_a_legacy_string_row_and_a_stale_resolution():
    rows = ["Add a loss run", {"pillar": "x", "field": None, "resolution": {"mode": "field", "facts": ["a"]}}]
    out = rr.with_fix_routes({"top_recommendations": rows}, {})["top_recommendations"]
    assert out[0] == "Add a loss run"
    assert "resolution" not in out[1]                     # no field = no route, a stale one is dropped


def test_a_row_without_answer_mode_is_routed_by_the_one_door():
    from services.answer_routing import answer_mode
    from services.schedule_capture import SCHEDULE_DEFS
    table = next(iter(SCHEDULE_DEFS))
    assert answer_mode(table)["mode"] == "schedule"
    assert rr.fix_route_for_row({"pillar": "p", "field": table}, {}) == \
        {"mode": "schedule", "schedule_key": table}
    assert rr.fix_route_for_row({"pillar": "p", "field": "mailing_address"}, {})["facts"] == ["mailing_address"]
    assert rr.fix_route_for_row({"pillar": "p", "field": "_internal_flag"}, {}) is None
    assert rr.fix_route_for_row({"pillar": "p", "field": "additional_remarks_text"}, {}) == {"mode": "narrative"}


def test_only_the_remarks_open_the_remarks_box():
    # The narrative write APPENDS to the ACORD 101 remarks; any other prose fact
    # is typed into its own fact.
    res = rr.fix_route_for_row({"pillar": "p", "field": "operations_description",
                                "answer_mode": "narrative"}, {})
    assert res["mode"] == "field" and res["facts"] == ["operations_description"]


def test_a_table_holding_rows_is_never_offered_as_a_text_box():
    res = rr.fix_route_for_row({"pillar": "p", "field": "x", "answer_mode": "none"}, {})
    assert res is None
    sched = rr.fix_route_for_row({"pillar": "p", "field": "auto_drivers", "answer_mode": "schedule",
                                  "schedule_key": "auto_drivers"}, {})
    assert sched == {"mode": "schedule", "schedule_key": "auto_drivers"}


def test_the_pre_form_status_carries_the_fix_routes(monkeypatch):
    from routes import form_routes as fr
    from services import form_dry_run as fdr

    stored = {"package_sqs_score": 42, "top_recommendations": _best_solutions()}
    before = copy.deepcopy(stored)

    async def no_dry(*a, **k):
        return None

    monkeypatch.setattr(fdr, "dry_run_payload", no_dry)
    monkeypatch.setattr(fr, "current_package_sqs", lambda *a, **k: stored)
    status = asyncio.run(fr._pre_form_status("sid-r", {}, {}, {}, {"id": "u"},
                                             session_row={"facts": {}, "flags": {}}))
    pkg, _kd = status
    assert pkg["package_sqs_score"] == 42
    assert [r.get("resolution", {}).get("mode") for r in pkg["top_recommendations"]] == \
        [None, "field", None, "field", "narrative"]
    assert stored == before                               # the persisted package is not written to


def test_pre_form_status_still_scores_through_the_one_door():
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_pre_form_status")
    calls = {getattr(c.func, "id", getattr(c.func, "attr", None)) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "current_package_sqs" in calls and "with_fix_routes" in calls
    assert not calls & {"calculate_package_sqs", "score_package_pre_generation", "calculate_sqs"}


# ── 2. The section's rules (frontend util, under node) ───────────────────────

def _run_node(tmp_path, body: str) -> dict:
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as R from {json.dumps(UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _pkg_with_routes():
    return rr.with_fix_routes({"package_sqs_score": 42, "top_recommendations": _best_solutions()}, {})


# The live session's cards: the COPE hard stop opens the location table for
# three named columns plus occupancy; the baseline warning types the mailing
# address and the contact facts; the driver warning opens the whole table.
GROUPED = {
    "hard_stops": [{"cluster": "Property COPE completeness", "count": 1, "items": [{
        "code": "minimum_viable_cope_missing", "message": "COPE",
        "resolution": {"mode": "schedule", "schedule_key": "property_locations",
                       "columns": ["construction_type", "building_value", "bpp_value"],
                       "facts": ["occupancy_type"]}}]}],
    "warnings": {
        "required": [{"cluster": "Missing baseline ACORD 125 fields", "count": 2, "items": [
            {"code": "tier1_missing_Applicant mailing address",
             "resolution": {"mode": "field", "facts": ["mailing_address"]}},
            {"code": "tier1_missing_Contact information",
             "resolution": {"mode": "field", "facts": ["contact_name", "contact_phone", "contact_email"]}}]}],
        "recommended": [{"cluster": "Auto completeness", "count": 1, "items": [
            {"code": "legacy_auto_driver_schedule_missing",
             "resolution": {"mode": "schedule", "schedule_key": "auto_drivers"}}]}],
        "binder_followup": [],
    },
}


def _item(fid, label, iid, res, blocks=False):
    return {"id": iid, "form_id": fid, "form_label": fid.replace("_", " "), "label": label,
            "blocks_download": blocks, "what_to_do": "Enter it", "resolution": res}


DRY = {"status": "ready", "count": 7, "forms": [
    {"form_id": "ACORD_125", "form_label": "ACORD 125", "items": [
        _item("ACORD_125", "Location 1: Street", "a1",
              {"mode": "schedule", "schedule_key": "property_locations", "columns": ["address_line1"], "rows": [0]}),
        _item("ACORD_125", "Date began", "a2", {"mode": "field", "facts": ["business_start_date"]}),
        _item("ACORD_125", "Mailing address", "a3", {"mode": "field", "facts": ["mailing_address"]}),
    ]},
    {"form_id": "ACORD_140", "form_label": "ACORD 140", "items": [
        _item("ACORD_140", "Location 1: Year built, Roof", "b1",
              {"mode": "schedule", "schedule_key": "property_locations",
               "columns": ["year_built", "roof_material"], "rows": [0]}, True),
        _item("ACORD_140", "Location 2: Construction", "b2",
              {"mode": "schedule", "schedule_key": "property_locations",
               "columns": ["construction_type"], "rows": [1]}, True),
    ]},
    {"form_id": "ACORD_127", "form_label": "ACORD 127", "items": [
        _item("ACORD_127", "Driver 1: Licence", "c1",
              {"mode": "schedule", "schedule_key": "auto_drivers", "columns": ["license_number"], "rows": [0]}),
        _item("ACORD_101", "Loss statement", "c2",
              {"mode": "field", "facts": ["loss_history_no_prior_losses_indicator"]}),
    ]},
]}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_one_to_do_one_place_before_forms(tmp_path):
    o = _run_node(tmp_path, (
        f"const pkg = {json.dumps(_pkg_with_routes())};\n"
        f"const grouped = {json.dumps(GROUPED)};\n"
        f"const dry = {json.dumps(DRY)};\n"
        "const kd = {missing_items: [{label: 'Years in business', resolution: {mode: 'field', facts: ['years_in_business']}}]};\n"
        "const m = R.buildRecommendations({packageSqs: pkg, groupedIssues: grouped, keyDetails: kd, dryRun: dry, formsExist: false});\n"
        "console.log(JSON.stringify({\n"
        " score: m.score.map(s => [s.title, R.pointsText(s.points), s.resolution.mode, s.alsoOnForms]),\n"
        " forms: m.forms.forms.map(f => [f.form_id, f.items.map(i => i.id)]),\n"
        " hidden: [...m.forms.hiddenIds].sort(), count: m.count,\n"
        " issue: R.scoreFixIssue(m.score[0]),\n"
        "}));"))
    # The mailing address is the warning card's (never twice); the synthetic
    # hard-stops row and the routeless pillar are not listed; points are the
    # answer's own gain, never a percentage.
    # 14 Oct 2026 (owner): before forms the section is the SCORE only - "we are
    # trying to make SQS independent of forms ... this section does not increase
    # score". The dry run's items are not listed or counted, and no score row is
    # tagged with a form that does not exist yet.
    assert o["score"] == [["Loss History", "+3 pts", "field", []],
                          ["Narrative Quality", "up to +5 pts", "narrative", []]]
    assert o["forms"] == [] and o["hidden"] == []
    assert o["count"] == 2
    assert o["issue"]["__scoreItem"] is True and o["issue"]["resolution"]["mode"] == "field"
    assert "+3 pts" in o["issue"]["message"] and "%" not in o["issue"]["message"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_edge_cases(tmp_path):
    o = _run_node(tmp_path, (
        "const row = (p, f, mode, extra = {}) => ({pillar: p, field: f, answer_mode: mode, action: 'a', ...extra});\n"
        "const out = {};\n"
        # nothing at all
        "out.empty = R.buildRecommendations({}).count;\n"
        "out.nulls = R.buildRecommendations({packageSqs: null, groupedIssues: null, keyDetails: null, dryRun: null}).count;\n"
        # a measured gain of 0 adds nothing; a pillar gap with no gain is a bound
        "out.zero = R.scoreItems({top_recommendations: [row('loss_history_alignment', 'x', 'field', {answer_gain: 0, answer_gain_is_exact: true, points_available: 9})]}).length;\n"
        "out.bound = R.scoreItems({top_recommendations: [row('exposure_consistency', 'x', 'field', {points_available: 4.6})]}).map(s => R.pointsText(s.points));\n"
        "out.inexact = R.scoreItems({top_recommendations: [row('exposure_consistency', 'x', 'field', {answer_gain: 2.4, answer_gain_is_exact: false})]}).map(s => R.pointsText(s.points));\n"
        # no route, no points, a schedule row from an editor payload (no resolution)
        "out.noroute = R.scoreItems({top_recommendations: [row('p', null, 'none', {points_available: 5}), row('p', 'x', 'none', {points_available: 5})]}).length;\n"
        "out.sched = R.scoreItems({top_recommendations: [row('p', 'auto_drivers', 'schedule', {schedule_key: 'auto_drivers', points_available: 3})]}).map(s => s.resolution);\n"
        # two rows asking for one answer are one item
        "out.twice = R.scoreItems({top_recommendations: [row('a', 'x', 'field', {points_available: 3}), row('b', 'x', 'field', {points_available: 2})]}).length;\n"
        # a column-less card covers a whole-table score row, never the named cells a form needs
        "const cov = R.onScreenFixKeys({hard_stops: [{items: [{resolution: {mode: 'schedule', schedule_key: 't', columns: ['c1']}}]}]}, null);\n"
        "out.tableCovered = R.allCovered(['table:t'], cov);\n"
        "out.otherCell = R.allCovered(['col:t:c2'], cov);\n"
        "out.sameCell = R.allCovered(['col:t:c1'], cov);\n"
        "out.partial = R.allCovered(['col:t:c1', 'col:t:c2'], cov);\n"
        "out.nokeys = R.allCovered([], cov);\n"
        # a pending / skipped dry run lists and counts nothing yet
        "out.pending = R.buildRecommendations({dryRun: {status: 'pending', forms: [{form_id: 'F', items: [{id: 'i', resolution: {mode: 'field', facts: ['q']}}]}]}}).count;\n"
        "out.skipped = R.buildRecommendations({dryRun: {status: 'skipped'}}).count;\n"
        "out.n = [0, 1, 2].map(R.recommendationsText);\n"
        "console.log(JSON.stringify(out));"))
    assert o["empty"] == 0 and o["nulls"] == 0
    assert o["zero"] == 0
    assert o["bound"] == ["up to +5 pts"]
    assert o["inexact"] == ["up to +2 pts"]
    assert o["noroute"] == 0
    assert o["sched"] == [{"mode": "schedule", "schedule_key": "auto_drivers"}]
    assert o["twice"] == 1
    assert o["tableCovered"] is True and o["otherCell"] is False and o["sameCell"] is True
    assert o["partial"] is False and o["nokeys"] is False
    assert o["pending"] == 0 and o["skipped"] == 0
    assert o["n"] == ["0 recommendations", "1 recommendation", "2 recommendations"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_after_forms_the_forms_group_is_the_editors_needs_attention_list(tmp_path):
    from services.needs_attention import STATUS_HELD_BACK, STATUS_MISSING, STATUS_VERIFY
    attention = {"forms": [
        {"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": [
            {"field": "F1", "label": "FEIN", "status": STATUS_MISSING, "fact_key": "fein", "what_to_do": "Enter it"},
            {"field": "F2", "label": "Mailing", "status": STATUS_MISSING, "fact_key": "mailing_address"},
            {"field": "F3", "label": "Losses", "status": STATUS_MISSING, "fact_key": "loss_history_no_prior_losses_indicator"},
            {"field": "F4", "label": "Sign", "status": STATUS_MISSING, "applicant_step": True},
            {"field": "F5", "label": "Box", "status": STATUS_MISSING},
            {"field": "F6", "label": "Phone", "status": STATUS_VERIFY},
            {"field": "F7", "label": "NAIC", "status": STATUS_HELD_BACK},
        ]},
        {"form_id": "ACORD_126", "form_label": "ACORD 126", "rows": [
            {"field": "G1", "label": "Signed", "status": STATUS_MISSING, "applicant_step": True}]},
    ]}
    o = _run_node(tmp_path, (
        f"const pkg = {json.dumps(_pkg_with_routes())};\n"
        f"const grouped = {json.dumps(GROUPED)};\n"
        f"const att = {json.dumps(attention)};\n"
        "const m = R.buildRecommendations({packageSqs: pkg, groupedIssues: grouped, dryRun: null, attention: att, formsExist: true});\n"
        "const loading = R.buildRecommendations({packageSqs: pkg, groupedIssues: grouped, attention: undefined, formsExist: true});\n"
        "console.log(JSON.stringify({\n"
        " forms: m.forms.forms.map(f => [f.form_id, f.items.map(i => i.field), f.toCheck]),\n"
        " score: m.score.map(s => [s.title, s.alsoOnForms]), count: m.count, ready: m.formsReady,\n"
        " loadingCount: loading.count, loadingReady: loading.formsReady,\n"
        "}));"))
    # Missing rows only (the producer's boxes): the applicant's signature steps
    # are not a to-do here, "verify" / "held back" are counted, not listed; the
    # mailing address is the warning card's; the loss box is the score row's.
    assert o["forms"] == [["ACORD_125", ["F1", "F5"], 2]]
    assert o["score"] == [["Loss History", ["ACORD 125"]], ["Narrative Quality", []]]
    assert o["count"] == 2 + 2 and o["ready"] is True
    assert o["loadingCount"] == 2 and o["loadingReady"] is False


def test_needs_attention_statuses_are_the_ones_the_util_reads():
    from services import needs_attention as na
    src = UTIL.read_text(encoding="utf-8")
    for status in (na.STATUS_MISSING, na.STATUS_VERIFY, na.STATUS_HELD_BACK):
        assert f'"{status}"' in src


# ── 3. The page ──────────────────────────────────────────────────────────────

def test_the_rail_has_a_recommendations_section_after_warnings():
    src = RAIL.read_text(encoding="utf-8")
    ids = re.findall(r'\{ id: "([a-z]+)", label: "[^"]+", group:', src)
    assert ids[-2:] == ["warnings", "recommendations"]
    assert "recommendations: recommendationsSection" in src
    assert re.search(r'id: "recommendations",\s*\n\s*sub:', src)          # its rail entry


def test_the_overview_keeps_one_line_and_no_dry_run_block():
    src = RAIL.read_text(encoding="utf-8")
    overview = src[src.index("const overview = ("):src.index("const documents = (")]
    assert "BeforeYouGenerate" not in overview and "<Recommendations" not in overview
    assert overview.count('onSectionChange("recommendations")') == 1
    assert "recommendationsText(recModel.count)} - see Recommendations" in overview
    # The Overview's count and the section are the same model.
    assert src.count("buildRecommendations(") == 1 and "model={recModel}" in src


def test_the_classic_layout_lists_them_after_the_warnings():
    src = MODAL.read_text(encoding="utf-8")
    classic = src[src.index('{step === "review" && !reviewRail && ('):]
    classic = classic[:classic.index("{/* ── FORM SELECTION")]
    rec = classic.index("<Recommendations heading")
    assert classic.index("softStops.map((s, i) => (") < rec       # after the warnings
    # before continue (its click ignores a double-click's second click, 9 Oct 2026)
    assert rec < classic.index("onClick={(e) => { if (e.detail > 1) return; handleContinueFromPackage(); }}")
    assert "<BeforeYouGenerate" not in src                 # composed inside Recommendations only
    assert "onFixScoreItem={openScoreFix}" in src and "issue?.__scoreItem" in src


def test_before_forms_the_section_is_the_score_only():
    """14 Oct 2026 (owner): "Your forms will need" is gone before forms - the dry run is
    not rendered (BeforeYouGenerate stays as a component, unused) and the forms group
    appears only once forms exist (each form's Missing rows)."""
    rec = RECS_JSX.read_text(encoding="utf-8")
    byg = BYG.read_text(encoding="utf-8")
    assert "<BeforeYouGenerate" not in rec and "import BeforeYouGenerate" not in rec
    assert "{formsExist && (" in rec and "<AfterFormsGroup" in rec
    for needle in ("MAX_POLLS = 12", "POLL_MS = 2500", "dryRunMatchesTicks(dryRun, tickedFormIds)", "Check again"):
        assert needle in byg


@pytest.mark.parametrize("path", [UTIL, RECS_JSX, RECS_JSX.with_suffix(".css"),
                                  RECS_JSX.parent / "useAttentionList.js"])
def test_no_em_dash_and_no_percentage_in_the_new_ui(path):
    src = path.read_text(encoding="utf-8")
    assert "—" not in src
    if path.suffix in (".jsx", ".js"):
        # No percentages on recommendation rows (owner, 1 Oct 2026).
        assert not re.search(r"\d\s*%|%\s*\}|`%", src)
