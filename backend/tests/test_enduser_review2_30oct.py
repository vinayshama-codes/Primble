"""End-user production review, 30 Oct 2026 (second pass).

1. After forms, a partial score update (an answer, a dismissal, a reopen) that
   leaves the headline unchanged kept the old review plan, so the side panel
   and the download screen still listed the answered item with its points.
   `patchPackageScore` now drops an after-forms plan on every patch and moves
   `_plan_epoch`, so the panel's one-try-per-score key (`planScoreKey`) asks
   again. A pre-form plan keeps the old rule (dropped on a moved headline).
2. "Server busy" and the ARQ "no forms" refusals printed an em-dash to users.
"""
import json
import os
import shutil
import subprocess
import textwrap

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTIL = os.path.normpath(os.path.join(BACKEND, "..", "frontend", "src", "utils", "editorPlanList.js"))


def _node(tmp_path, body: str):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    js = tmp_path / "t.mjs"
    js.write_text(textwrap.dedent(f"""
        import {{ patchPackageScore, planScoreKey, planAfterForms }} from {json.dumps("file://" + UTIL)};
    """) + textwrap.dedent(body))
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_an_unchanged_headline_after_forms_still_drops_the_plan(tmp_path):
    got = _node(tmp_path, """
        const after = { package_sqs_score: 79, timestamp: "t1",
                        review_plan: { after_forms: true, items: [{ id: "a", points: 21 }], total: 21 } };
        const p1 = patchPackageScore(after, { package_sqs_score: 79 });
        const p2 = patchPackageScore({ ...p1, review_plan: after.review_plan }, { package_sqs_score: 79 });
        console.log(JSON.stringify({
          dropped: !("review_plan" in p1), epoch1: p1._plan_epoch, epoch2: p2._plan_epoch,
          keyMoved: planScoreKey(after) !== planScoreKey(p1),
          keyMovedAgain: planScoreKey(p1) !== planScoreKey(p2),
          stillAfter: planAfterForms(p1), untouched: "review_plan" in after,
        }));
    """)
    assert got == {"dropped": True, "epoch1": 1, "epoch2": 2, "keyMoved": True,
                   "keyMovedAgain": True, "stillAfter": False, "untouched": True}


def test_a_pre_form_plan_keeps_the_old_rule(tmp_path):
    got = _node(tmp_path, """
        const pre = { package_sqs_score: 70, review_plan: { items: [], total: 30 } };
        const same = patchPackageScore(pre, { package_sqs_score: 70 });
        const moved = patchPackageScore(pre, { package_sqs_score: 72 });
        console.log(JSON.stringify({ same: "review_plan" in same, moved: "review_plan" in moved,
          epoch: same._plan_epoch ?? null }));
    """)
    assert got == {"same": True, "moved": False, "epoch": None}


def test_a_plan_read_before_an_answer_is_not_used_after_it(tmp_path):
    # The download screen's own plan read is tied to the epoch it was asked at.
    got = _node(tmp_path, """
        const read = { package_sqs_score: 79, timestamp: "t1", _plan_epoch: 0,
                       review_plan: { after_forms: true, items: [] } };
        const onScreen = { package_sqs_score: 79, timestamp: "t1", _plan_epoch: 1 };
        console.log(JSON.stringify({ same: planScoreKey(read) === planScoreKey(onScreen),
          fresh: planScoreKey({ ...read, _plan_epoch: 1 }) === planScoreKey(onScreen),
          empty: planScoreKey(null) }));
    """)
    assert got == {"same": False, "fresh": True, "empty": ""}


def test_the_panel_and_download_read_the_plan_by_its_epoch():
    src = open(os.path.join(BACKEND, "..", "frontend", "src", "components", "form", "AcordModal.jsx")).read()
    assert "const key = `${sessionId}|${planScoreKey(packageSqs)}`;" in src
    assert "planScoreKey(preflightPlanSqs) === planScoreKey(packageSqs)" in src
    assert "_plan_epoch: epoch" in src


@pytest.mark.parametrize("rel", ["utils/concurrency.py", "routes/form_routes.py",
                                 "routes/session_documents_routes.py", "routes/arq_routes.py"])
def test_refusals_users_read_carry_no_em_dash(rel):
    text = open(os.path.join(BACKEND, rel), encoding="utf-8").read()
    for phrase in ("Server busy", "No forms generated yet"):
        for line in text.splitlines():
            if phrase in line:
                assert "—" not in line, line.strip()
