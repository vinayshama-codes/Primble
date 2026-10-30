"""The download screens print the review plan's numbers - the side panel's -
never a card's own stored `score_impact` (29 Oct 2026).

Before: the download review / post-download checklist printed each row's stored
`score_impact`, the editor's side panel the ordered plan's number
(`packageSqs.review_plan`), so one item read two different numbers. Now
`utils/downloadPlanPoints.js` gives a row the plan's number for the plan item it
is (issue id, then rule code; a card row by its fact), hides a number the plan
does not list, counts a plan item (or what it mirrors) once and never sums past
100 minus the score.
"""
import json
import os
import shutil
import subprocess
import textwrap

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.normpath(os.path.join(BACKEND, "..", "frontend", "src"))
HELPER = os.path.join(FRONT, "utils", "downloadPlanPoints.js")
PANEL = os.path.join(FRONT, "components", "form", "NeedsAttentionPanel.jsx")
MODAL = os.path.join(FRONT, "components", "form", "AcordModal.jsx")


def _plan(items, score=79, recs=None):
    return {"package_sqs_score": score, "top_recommendations": recs or [],
            "review_plan": {"after_forms": True, "items": items, "total": 100 - score, "left": 0}}


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    js = tmp_path / "t.mjs"
    js.write_text(textwrap.dedent(f"""
        import {{ downloadPlanPoints, withDownloadPlanPoints }} from {json.dumps("file://" + HELPER)};
        const toObj = (m) => Object.fromEntries([...m.entries()]);
    """) + textwrap.dedent(body))
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_rows_take_the_plans_numbers_and_never_their_stored_ones(tmp_path):
    sqs = _plan([
        {"id": "kd:Annual revenue", "kind": "detail", "label": "Annual revenue", "points": 2,
         "exact": True, "keys": ["fact:annual_revenue"]},
        {"id": "card:cope_min", "kind": "card", "code": "cope_min", "issue_id": "iss-1",
         "first_of_code": True, "points": 6, "exact": True, "keys": ["fact:occupancy_type"]},
        {"id": "card:uncovered_soft_stop", "kind": "card", "code": "uncovered_soft_stop",
         "issue_id": "iss-2", "first_of_code": True, "points": 3, "exact": False, "keys": []},
        {"id": "card:held_one", "kind": "card", "code": "held_one", "issue_id": "iss-3",
         "first_of_code": True, "points": 0, "held_by": "Occupancy", "exact": False, "keys": []},
        {"id": "rec:0", "kind": "rec", "row_index": 0, "field": "auto_radius", "points": 1, "keys": []},
        {"id": "card:revenue_check", "kind": "card", "code": "revenue_check", "issue_id": "iss-5",
         "first_of_code": True, "points": 0, "mirror_of": "kd:Annual revenue",
         "keys": ["fact:annual_revenue"]},
    ], recs=[{"field": "auto_radius", "plan_id": "rec:0", "answer_gain": 1, "answer_gain_is_exact": True,
              "pillar": "exposure_consistency", "action": "Radius"}])
    rows = [
        {"rec_id": "iss-1", "issue_id": "iss-1", "code": "cope_min", "recommendation_type": "hard_stop",
         "score_impact": 13, "review_issue": True},
        # issue id unknown to the plan: found by its rule code
        {"rec_id": "iss-9", "issue_id": "iss-9", "code": "uncovered_soft_stop",
         "recommendation_type": "soft_warning", "score_impact": 7, "review_issue": True},
        # a second row of the same code: the plan item is counted once
        {"rec_id": "iss-10", "issue_id": "iss-10", "code": "uncovered_soft_stop",
         "recommendation_type": "soft_warning", "score_impact": 7, "review_issue": True},
        {"rec_id": "iss-3", "issue_id": "iss-3", "code": "held_one", "recommendation_type": "soft_warning",
         "review_issue": True},
        # a stored card: the side panel's reading of its plan row
        {"rec_id": "rec_auto_radius", "field": "auto_radius", "recommendation_type": "soft_warning",
         "score_impact": 5},
        # a mirror of a key detail the screen does not list: the key detail's number
        {"rec_id": "iss-5", "issue_id": "iss-5", "code": "revenue_check", "recommendation_type": "soft_warning",
         "review_issue": True},
        # the plan does not list these: no number, never the stale one
        {"rec_id": "iss-77", "issue_id": "iss-77", "code": "not_in_plan", "recommendation_type": "soft_warning",
         "score_impact": 9, "review_issue": True},
        {"rec_id": "fieldqa_hardblock_ACORD_140_x", "field": "Construction_Code_A",
         "recommendation_type": "hard_stop", "score_impact": 4},
    ]
    got = _node(tmp_path, f"""
        const sqs = {json.dumps(sqs)};
        const rows = {json.dumps(rows)};
        const m = downloadPlanPoints(sqs, rows);
        const annotated = withDownloadPlanPoints(rows, rows, sqs).map((r) => [r.rec_id, r.plan_points]);
        console.log(JSON.stringify({{ m: toObj(m), annotated, none: toObj(downloadPlanPoints(null, rows)),
          before: withDownloadPlanPoints(rows, rows, {{ package_sqs_score: 79 }}).every((r) => r.plan_points === "") }}));
    """)
    assert got["m"] == {
        "iss-1": "+6 pts",
        "iss-9": "up to +3 pts",
        "iss-3": "Counts once Occupancy is fixed",
        "rec_auto_radius": "+1 pts",
        "iss-5": "+2 pts",
    }
    assert dict(got["annotated"])["iss-77"] == "" and dict(got["annotated"])["iss-10"] == ""
    assert dict(got["annotated"])["fieldqa_hardblock_ACORD_140_x"] == ""
    assert got["none"] == {} and got["before"] is True


def test_the_numbers_never_add_up_past_100_minus_the_score(tmp_path):
    # An inconsistent plan (items worth 9 at 95): the screen shows at most 5.
    sqs = _plan([
        {"id": "card:a", "kind": "card", "code": "a", "issue_id": "a", "points": 4, "exact": True},
        {"id": "card:b", "kind": "card", "code": "b", "issue_id": "b", "points": 3, "exact": True},
        {"id": "card:c", "kind": "card", "code": "c", "issue_id": "c", "points": 2, "exact": True},
    ], score=95)
    rows = [{"rec_id": k, "issue_id": k, "code": k, "review_issue": True} for k in ("a", "b", "c")]
    got = _node(tmp_path, f"""
        console.log(JSON.stringify(toObj(downloadPlanPoints({json.dumps(sqs)}, {json.dumps(rows)}))));
    """)
    assert got == {"a": "+4 pts", "b": "up to +1 pts"}
    # ... and a mirror is never counted beside its first place.
    sqs2 = _plan([
        {"id": "card:x", "kind": "card", "code": "x", "issue_id": "x", "points": 5, "exact": True},
        {"id": "card:y", "kind": "card", "code": "y", "issue_id": "y", "points": 0, "mirror_of": "card:x"},
    ], score=95)
    rows2 = [{"rec_id": k, "issue_id": k, "code": k, "review_issue": True} for k in ("x", "y")]
    got2 = _node(tmp_path, f"""
        console.log(JSON.stringify(toObj(downloadPlanPoints({json.dumps(sqs2)}, {json.dumps(rows2)}))));
    """)
    assert got2 == {"x": "+5 pts"}


def test_the_screens_print_only_the_plan_number():
    panel = open(PANEL, encoding="utf-8").read()
    box = panel[panel.index("function RecBox"):panel.index("function SuggestionLines")]
    assert "score_impact" not in box and "planPts(r)" in box
    modal = open(MODAL, encoding="utf-8").read()
    assert "openRecs={downloadRecs}" in modal and "const recs     = downloadRecs;" in modal
    assert "withDownloadPlanPoints(recs, downloadSteps(recs, preflightAttention)" in modal
    assert "—" not in open(HELPER, encoding="utf-8").read()
