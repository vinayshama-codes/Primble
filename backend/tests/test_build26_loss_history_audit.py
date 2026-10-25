"""LOSS HISTORY AUDIT (owner, 24 Oct 2026): the claims question's Resolved row.

Reported: the claims question answered "Yes - we have had claims or losses", the
two follow-up rows appeared ("Record that loss runs have been requested",
"Upload carrier loss runs"), and the claims row was not in the Recommendations
Resolved list. The suspected cause - the fix-state rule reading the pillar's
NEW rows as the same item still open - was checked against the page's own
JavaScript on real payloads (business age 15 / 3 / unknown, answered Yes and
No): the rule reads a row by its OWN fix keys, never by its pillar, and files
the claims row "fixed" in every case. These tests pin that rule and the whole
claims journey (answer -> Resolved once -> Open again -> listed again with its
number), so a pillar-level reading can never creep in.
"""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tests.test_build26_loss_plan_journeys import (
    AGES, HAD_CLAIMS, INDICATOR, NO_CLAIMS, _answer, _page, _row, _score,
)

_UTILS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils"
_REC = _UTILS / "recommendations.js"
_RESOLVED = _UTILS / "resolvedIssues.js"
CLAIMS_ID = f"score:loss_history_alignment:fact:{INDICATOR}"


def _node(tmp_path: Path, body: str, data: dict) -> dict:
    (tmp_path / "data.json").write_text(json.dumps(data, default=str), encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(
        "import fs from 'fs';\n"
        f"import * as R from {json.dumps(_REC.as_uri())};\n"
        f"import * as V from {json.dumps(_RESOLVED.as_uri())};\n"
        f"const D = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'data.json'))}, 'utf8'));\n"
        + body, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# What the page does with one save of the claims row (AcordModal
# markClearedRecommendations + markRecommendationFix, then the Resolved list).
_SAVE = (
    "const before = R.scoreItems(D.before, new Set());\n"
    "const after = R.scoreItems(D.after, new Set());\n"
    "const own = before.find((s) => s.id === D.id);\n"
    "const state = R.recommendationFixState('score', D.id, {packageSqs: D.after});\n"
    "const cleared = R.clearedScoreItems(before, D.after, new Set([D.id])).map((s) => s.id);\n"
    "const iid = V.recScoreIssueId(D.id);\n"
    "const statuses = state === 'fixed' ? [[iid, {status: 'resolved', message: R.scoreFixIssue(own).__recTitle,"
    " severity: V.REC_PAGE}]] : [];\n"
    "const resolved = R.recommendationResolvedRows({statusEntries: statuses,"
    " liveIds: R.liveRecommendationIds({packageSqs: D.after})});\n"
    "console.log(JSON.stringify({listedBefore: !!own, state, cleared, resolved,"
    " after: after.map((s) => ({id: s.id, pillar: s.pillar, detail: s.detail}))}));\n"
)


@pytest.mark.parametrize("age", AGES)
def test_claims_yes_files_the_claims_row_resolved_beside_its_follow_up_rows(tmp_path, age):
    """The reported journey: "Yes" brings the request / upload rows in the SAME
    pillar under new words; the claims row is still fixed - filed once, never
    read as still open because its pillar lists other rows."""
    row = _row(age=age)
    before = _page(row)
    _answer(row, INDICATOR, HAD_CLAIMS)
    after = _page(row)
    o = _node(tmp_path, _SAVE, {"before": before, "after": after, "id": CLAIMS_ID})
    assert o["listedBefore"], "the claims question is listed when nothing is known"
    lh_after = [s for s in o["after"] if s["pillar"] == "loss_history_alignment"]
    assert lh_after and all(s["id"] != CLAIMS_ID for s in lh_after), lh_after
    assert o["state"] == "fixed"
    assert o["cleared"] == []                       # its own row is never "cleared by" itself
    assert [r["iid"] for r in o["resolved"]] == [f"rec:{CLAIMS_ID}"]
    assert o["resolved"][0]["clearedBy"] is None
    assert "Any claims" in o["resolved"][0]["title"]


@pytest.mark.parametrize("age", AGES)
def test_claims_no_files_the_row_and_takes_loss_history_out(tmp_path, age):
    row = _row(age=age)
    before = _page(row)
    _answer(row, INDICATOR, NO_CLAIMS)
    after = _page(row)
    assert _score(after) == 100 and _score(after) >= _score(before)
    o = _node(tmp_path, _SAVE, {"before": before, "after": after, "id": CLAIMS_ID})
    assert o["state"] == "fixed"
    assert [r["iid"] for r in o["resolved"]] == [f"rec:{CLAIMS_ID}"]
    assert not [s for s in o["after"] if s["pillar"] == "loss_history_alignment"]


@pytest.mark.parametrize("answer", [HAD_CLAIMS, NO_CLAIMS])
def test_open_again_on_the_claims_answer_lists_the_question_again(tmp_path, answer):
    """Open again takes the answer back: the question is listed again with its
    number, and a stored "resolved" on it no longer shows under Resolved."""
    row = _row(age=15)
    start = _page(row)
    answered = copy.deepcopy(row)
    _answer(answered, INDICATOR, answer)
    reopened = copy.deepcopy(answered)
    reopened["facts"].pop(INDICATOR, None)
    reopened["flags"]["no_prior_losses"] = False
    back = _page(reopened)
    assert _score(back) == _score(start)
    o = _node(tmp_path, (
        "const items = R.scoreItems(D.back, new Set());\n"
        "const claims = items.find((s) => s.id === D.id);\n"
        "const iid = V.recScoreIssueId(D.id);\n"
        "const resolved = R.recommendationResolvedRows({statusEntries: [[iid, {status: 'resolved',"
        " message: 'Loss History: Any claims in the last 5 years?', severity: V.REC_PAGE}]],"
        " liveIds: R.liveRecommendationIds({packageSqs: D.back})});\n"
        "console.log(JSON.stringify({points: claims ? claims.points : null, resolved: resolved.length}));\n"),
        {"back": back, "id": CLAIMS_ID})
    assert o["points"] and o["points"]["points"] >= 1
    assert o["resolved"] == 0


def test_the_fix_state_reads_a_rows_own_keys_never_its_pillar(tmp_path):
    """The generic rule: a row whose own facts are answered and no longer asked
    is fixed, whatever other rows its pillar now lists; a row whose fact is
    still asked (under any id) is open."""
    o = _node(tmp_path, (
        "const row = (f, a) => ({pillar: 'loss_history_alignment', field: f, action: a, points_available: 3,"
        " answer_mode: 'field', resolution: {mode: 'field', facts: [f]}});\n"
        "const id = R.scoreItems({top_recommendations: [row('q1', 'Question one')]})[0].id;\n"
        "const newRows = {top_recommendations: [row('q2', 'Follow-up two'), row('q3', 'Follow-up three')]};\n"
        "const sameFact = {top_recommendations: [{...row('q1', 'New words for q1'), pillar: 'loss_history_alignment'}]};\n"
        "const merged = {top_recommendations: [{...row('q2', 'q2 + q1'), merged_fields: ['q2', 'q1'],"
        " resolution: {mode: 'field', facts: ['q2', 'q1']}}]};\n"
        "console.log(JSON.stringify({\n"
        "  newRows: R.recommendationFixState('score', id, {packageSqs: newRows}),\n"
        "  sameFact: R.recommendationFixState('score', id, {packageSqs: sameFact}),\n"
        "  merged: R.recommendationFixState('score', id, {packageSqs: merged}),\n"
        "  empty: R.recommendationFixState('score', id, {packageSqs: {top_recommendations: []}}),\n"
        "}));\n"), {})
    assert o == {"newRows": "fixed", "sameFact": "open", "merged": "open", "empty": "fixed"}


# ── Fixes found by the matrix run (24 Oct 2026) ──────────────────────────────
_COVERAGE = _UTILS / "lossCoverage.js"


def test_the_first_loss_run_states_the_score_move(tmp_path):
    """Marking the first file as Loss runs (no coverage before) moved the score
    and the message said only "Loss runs now cover 1 of 5 years". It now says
    the move whenever both scores are known; a score that is not known yet
    (integrity review pending) is never printed."""
    script = tmp_path / "cov.mjs"
    script.write_text(
        f"import * as L from {json.dumps(_COVERAGE.as_uri())};\n"
        "const one = {covered: 1, required: 5, label: '1 of 5 years (2025)'};\n"
        "console.log(JSON.stringify({\n"
        "  first: L.lossCoverageChangeText(null, one, 92, 95),\n"
        "  noScore: L.lossCoverageChangeText(null, one, 92, null),\n"
        "  same: L.lossCoverageChangeText(one, one, 95, 95),\n"
        "  down: L.lossCoverageChangeText({covered: 5, label: '5 of 5 years'}, one, 100, 95),\n"
        "}));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o == {"first": "Loss runs now cover 1 of 5 years - score 95 (+3)",
                 "noScore": "Loss runs now cover 1 of 5 years",
                 "same": "",
                 "down": "Loss runs now cover 1 of 5 years - score 95 (-5)"}


def _undo_session(docs, facts):
    return {"docs": docs, "facts": facts, "flags": {}, "generated_forms": {}}


_TABLE_BEFORE = {"value": [{"year_built": ""}], "source": "document"}
_TABLE_AFTER = {"value": [{"year_built": "2005"}], "source": "producer"}
_DEC = {"doc_id": "dec", "doc_type": "dec_page", "excluded": False,
        "facts": {"property_locations": {"value": [{"year_built": ""}]}}}


def _loss_run(doc_id="lr1", **facts):
    return {"doc_id": doc_id, "doc_type": "loss_run", "excluded": False,
            "facts": {"loss_run_period_start": {"value": "01/01/2025"}, **facts}}


def test_a_replaced_value_undoes_when_the_new_documents_say_nothing_about_it():
    """Audit (24 Oct 2026): loss runs uploaded after a COPE table fix blocked its
    "Open again" ("Its values were changed after this fix"). The runs never state
    the table, so the old documents' table is still the documents' table."""
    from services import issue_fix_undo as u
    before = _undo_session([_DEC], {})
    receipt = {"facts": {"property_locations": {"before": _TABLE_BEFORE, "after": _TABLE_AFTER}},
               "docs": u.docs_fingerprint(before)}
    now = _undo_session([_DEC, _loss_run()], {"property_locations": _TABLE_AFTER})
    state, plan = u.plan_undo(now, receipt)
    assert state == "ok" and plan["set_facts"] == {"property_locations": _TABLE_BEFORE}


@pytest.mark.parametrize("change", ["states_it", "excluded_source", "removed", "no_facts_on_file"])
def test_a_replaced_value_still_refuses_when_a_changed_document_may_state_it(change):
    from services import issue_fix_undo as u
    before = _undo_session([_DEC], {})
    receipt = {"facts": {"property_locations": {"before": _TABLE_BEFORE, "after": _TABLE_AFTER}},
               "docs": u.docs_fingerprint(before)}
    docs = {
        "states_it": [_DEC, _loss_run(property_locations={"value": [{"year_built": "1990"}]})],
        "excluded_source": [{**_DEC, "excluded": True}],
        "removed": [_loss_run()],
        "no_facts_on_file": [_DEC, {"doc_id": "new", "doc_type": "dec_page", "excluded": False}],
    }[change]
    now = _undo_session(docs, {"property_locations": _TABLE_AFTER})
    assert u.plan_undo(now, receipt) == ("changed", {"changed": ["documents"]})
