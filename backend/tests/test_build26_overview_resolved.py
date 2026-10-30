"""Build 26 (23 Oct 2026): Overview's "Resolved (n)" for key details, and a prose
row's points.

1. A key detail fixed through its link on the Overview page no longer just
   vanishes: its fix is filed under "kd:<label>" (the undo receipt), it is
   recorded "resolved" under page "overview" only when the save FIXED it, and it
   is listed under a collapsed "Resolved (n)" on Overview with "Open again" (the
   Recommendations page's Resolved list, its rows). A status under that page
   shows nowhere else.
2. A prose row (the narrative) shows the pillar's whole remaining share, "up to":
   live fc04c74f sat at 98 with only the narrative left and the row read
   "up to +1" while answering both topics made 100.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from services import sqs_service as S

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
RESOLVED = SRC / "utils" / "resolvedIssues.js"
RECS = SRC / "utils" / "recommendations.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _node(tmp_path, imports: dict, body: str):
    head = "".join(f"import * as {n} from {json.dumps(p.as_uri())};\n" for n, p in imports.items())
    script = tmp_path / "check.mjs"
    script.write_text(head + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ── 1. Overview Resolved ─────────────────────────────────────────────────────

def test_overview_is_a_status_page():
    import services.audit_service as au
    assert "overview" in au.ISSUE_STATUS_PAGES


@needs_node
def test_key_detail_ids_pages_and_rows(tmp_path):
    out = _node(tmp_path, {"R": RESOLVED}, """
const kdBefore = { missing: ["Business phone", "FEIN"], missing_items: [{ label: "Business phone" }, { label: "FEIN" }] };
const kdAfter = { missing: ["FEIN"], missing_items: [{ label: "FEIN" }] };
const id = R.keyDetailIssueId("  Business   phone ");
const entries = [
  [id, { status: "resolved", message: "Business phone", severity: "overview" }],
  [R.keyDetailIssueId("FEIN"), { status: "resolved", message: "FEIN", severity: "overview" }],
  ["iss_1", { status: "resolved", message: "A warning", severity: "warning" }],
];
console.log(JSON.stringify({
  id, isKd: R.isKeyDetailId(id), notRec: R.isRecommendationId(id),
  page: R.pageOfStatus({ severity: "overview" }, null), pageById: R.pageOfStatus({}, id),
  fixed: R.keyDetailFixState("Business phone", kdAfter), open: R.keyDetailFixState("FEIN", kdAfter),
  unknown: R.keyDetailFixState("FEIN", null), empty: R.keyDetailIssueId(""),
  rows: R.keyDetailResolvedRows({ statusEntries: entries, keyDetails: kdAfter }),
  rowsBefore: R.keyDetailResolvedRows({ statusEntries: entries, keyDetails: kdBefore }),
  warn: R.storedHandledRows(entries, { liveIds: new Set(), page: "warning" }).map((r) => r.iid),
  rec: R.storedHandledRows(entries, { liveIds: new Set(), page: "recommendation" }).map((r) => r.iid),
}));
""")
    assert out["id"] == "kd:business phone" and out["isKd"] and not out["notRec"]
    assert out["page"] == "overview" and out["pageById"] == "overview"
    assert (out["fixed"], out["open"], out["unknown"], out["empty"]) == ("fixed", "open", None, None)
    # A fixed detail is listed; one still missing is not (it is back in its list).
    assert [r["iid"] for r in out["rows"]] == ["kd:business phone"]
    assert out["rows"][0]["title"] == "Business phone" and out["rows"][0]["status"] == "resolved"
    assert out["rowsBefore"] == []
    # A status under Overview never shows on another page.
    assert out["warn"] == ["iss_1"] and out["rec"] == []


def _src(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def test_the_fix_is_filed_under_the_key_details_id_and_reopened_through_the_one_door():
    acord = _src("components/form/AcordModal.jsx")
    open_fix = acord[acord.index("const openKeyDetailFix = "):][:1400]
    assert "issue_id: keyDetailIssueId(item.label)" in open_fix
    resolved = acord[acord.index("if (issue?.__keyDetail) {"):][:900]
    assert "keyDetailFixState(issue.__keyDetailLabel, data?.key_details)" in resolved
    assert 'setIssueStatus(iid, "resolved", meta)' in resolved and "severity: KD_PAGE" in resolved
    reopen = acord[acord.index("const reopenKeyDetail = "):][:600]
    assert "handleReopenIssue(row.iid" in reopen and "optimistic: false" in reopen
    # The editor's Cross-Form ghosts never take an Overview status.
    assert "pageOfStatus(st, iid) !== KD_PAGE" in acord


def test_both_layouts_render_overview_resolved():
    acord = _src("components/form/AcordModal.jsx")
    rail = _src("components/form/review/ReviewRailLayout.jsx")
    assert "<KeyDetailsResolved" in acord and "onReopen={reopenKeyDetail}" in acord
    assert "onReopenKeyDetail={reopenKeyDetail}" in acord
    assert "<KeyDetailsResolved" in rail and "onReopen={onReopenKeyDetail}" in rail
    kd = _src("components/form/review/KeyDetailsMissing.jsx")
    assert "<ResolvedGroup" in kd
    recs = _src("components/form/review/Recommendations.jsx")
    assert "export function ResolvedGroup" in recs and 'dismissed: "Dismissed"' in recs


def test_no_em_dash_in_the_new_ui():
    for rel in ("components/form/review/KeyDetailsMissing.jsx", "utils/resolvedIssues.js"):
        assert "—" not in _src(rel), rel


# ── 2. A prose row's points ──────────────────────────────────────────────────

def _narrative_at(score_target: int):
    """Pillars where only the narrative is short and the package scores
    `score_target` - the scorer's own arithmetic."""
    base = {"structural_completeness": 100.0, "exposure_consistency": 100.0, "property_integrity": None,
            "loss_history_alignment": 100.0, "umbrella_limit_adequacy": None}
    for n in range(100, -1, -1):
        p = {**base, "narrative_quality": float(n)}
        if S._weighted_pillar_sum(p, S.SPEC_PILLAR_WEIGHTS) == score_target:
            return p
    raise AssertionError("no narrative score lands there")


@pytest.mark.parametrize("score", [98, 97, 95])
def test_the_remaining_share_is_100_minus_the_score_when_only_the_narrative_is_left(score):
    pillars = _narrative_at(score)
    assert S._pillar_remaining_points(pillars, "narrative_quality", score) == 100 - score
    assert S._pillar_remaining_points(pillars, "umbrella_limit_adequacy", score) is None


@pytest.mark.parametrize("probe_gain", [0, 1])
def test_a_narrative_row_shows_up_to_the_whole_remaining_share(probe_gain):
    score = 98
    pillars = _narrative_at(score)
    rows = [{"pillar": "narrative_quality", "score": pillars["narrative_quality"],
             "field": "additional_remarks_text", "action": "Improve narrative quality", "missing": []}]
    # A placeholder probe cannot write what the reader scores: it adds 0 or 1.
    S._unify_card_points([], rows, {}, score, None, lambda _c: None, lambda _f: score + probe_gain,
                         pillar_remaining=lambda p: S._pillar_remaining_points(pillars, p, score))
    assert rows[0]["answer_gain"] == 100 - score
    assert rows[0]["answer_gain_is_exact"] is False                     # still "up to"


def test_the_pre_form_screen_share_of_a_lone_narrative_is_100_minus_the_score():
    score = 98
    pkg = {"package_sqs_score": score, "raw_sqs_score": score, "cap_applied": None,
           "pillars": {"narrative_quality": {"score": 60}},
           "top_recommendations": [{"pillar": "narrative_quality", "field": "additional_remarks_text",
                                    "action": "Improve narrative quality"}]}
    # Build 26 page-wide plan (TEST updated, code changed on purpose): a number is
    # what the real scorer measures in page order. This stub cannot be reproduced
    # by the scorer, so the row gets no invented share and the points still add up
    # to 100 through the "no item can add yet" row.
    out, _kd = S.complete_screen_shares({"facts": {}, "flags": {}}, "s", "u", pkg, None)
    row = out["top_recommendations"][0]
    assert row["answer_gain_is_exact"] is False
    left = sum(r["points"] for r in out["screen_unanswerable"])
    # SCORING_RULES.md P2 (29 Oct 2026): the items carry exactly 100 - score -
    # points no item adds are a breach the plan's guard repairs onto the
    # page's score items (`review_plan.enforce_contract`). TEST updated: it
    # pinned the row alone plus the "no item can add yet" row.
    plan = out["review_plan"]
    shown = sum(int(i.get("points") or 0) for i in plan["items"] if not i.get("mirror_of"))
    assert shown + left == 100 - score and row["answer_gain"] >= 1
    assert out["screen_total"] == 100 - score


@needs_node
def test_the_page_prints_up_to_the_whole_share_and_never_past_100(tmp_path):
    out = _node(tmp_path, {"Rc": RECS}, """
const row = { pillar: "narrative_quality", answer_gain: 2, answer_gain_is_exact: false, answer_gain_share: false };
const p = Rc.pointsFor(row);
const items = [{ points: p }];
Rc.withinHundred(items, 98);
const over = [{ points: { points: 5, exact: false } }];
Rc.withinHundred(over, 98);
console.log(JSON.stringify({ text: Rc.pointsText(items[0].points), over: over[0].points.points }));
""")
    assert out["text"] == "up to +2 pts"
    assert out["over"] == 2
