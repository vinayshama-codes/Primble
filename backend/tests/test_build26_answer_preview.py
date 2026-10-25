"""Build 26: follow-up questions shown inside the fix window (owner, 24 Oct 2026).

"if there are any follow up questions that are gonna be appearing if user
answers a particular answer, when user selects that answer show those followups
in that panel only". `POST /api/review/preview-answer` reads the review page's
items on an in-memory copy with the answer written and returns the new ones
(`services.answer_preview`). Run on a real snapshot: a fresh Choice Electric
package, nothing answered (`live26/m1.pkl`). Never touches the database.
"""
from __future__ import annotations

import asyncio
import copy
import os
import pickle
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

import routes.audit_routes as ar                                      # noqa: E402
from services import answer_preview as ap                             # noqa: E402

SNAP = Path("/private/tmp/claude-501/-Users-vinaysharma-Downloads-Primble-16thsep/"
            "427f82bb-424b-4678-bf06-9112a9013561/scratchpad/live26/m1.pkl")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
SID = "sid-preview"
CLAIMS = "loss_history_no_prior_losses_indicator"

pytestmark = pytest.mark.skipif(not SNAP.exists(), reason="live26 snapshot not on this machine")


@pytest.fixture(scope="module")
def row():
    return pickle.load(open(SNAP, "rb"))


def _call(row, **body):
    """The REAL route, with the session read stubbed to the in-memory row."""
    stored = copy.deepcopy(row)

    async def _get(_sid, *_a, **_k):
        return copy.deepcopy(stored)

    with patch.object(ar, "get_processing_session", _get):
        out = asyncio.run(ar.preview_answer(ar.PreviewAnswerRequest(session_id=SID, **body),
                                            current_user={"id": row["user_id"]}))
    return out, stored


@pytest.fixture(scope="module")
def yes(row):
    return _call(row, field=CLAIMS, value="Yes - we have had claims or losses")


def test_claims_yes_returns_the_requested_question_and_the_upload_step(yes):
    out, _ = yes
    fus = out["follow_ups"]
    fields = [f for f in fus if f["kind"] == "field"]
    assert any("loss_run_status" in (f["resolution"].get("facts") or []) for f in fields), fus
    assert any(f["label"].lower().startswith("record that loss runs") for f in fields)
    docs = [f for f in fus if f["kind"] == "document"]
    assert len(docs) == 1 and docs[0]["action"] == "add_documents"
    assert "loss runs" in docs[0]["label"].lower()
    # A field follow-up carries what the window needs to save it under its own row.
    req = next(f for f in fields if "loss_run_status" in f["resolution"]["facts"])
    assert req["source"] == "rec" and req["pillar"] and req["keys"] == ["fact:loss_run_status"]
    assert (req["resolution"].get("controls") or {}).get("loss_run_status", {}).get("options")


def test_claims_no_returns_none(row):
    out, _ = _call(row, field=CLAIMS, value="No - no claims or losses in the past 5 years")
    assert out["follow_ups"] == []


def test_occupancy_returns_no_field_the_window_already_shows(row):
    out, _ = _call(row, field="occupancy_type", value="Office", shown_fields=["occupancy_type"])
    for f in out["follow_ups"]:
        assert "fact:occupancy_type" not in (f.get("keys") or [])
        assert "occupancy_type" not in ((f.get("resolution") or {}).get("facts") or [])


def test_the_stored_row_is_unchanged(row, yes):
    _, stored = yes
    assert stored == row
    assert CLAIMS not in (row.get("facts") or {}) or row["facts"][CLAIMS] == stored["facts"][CLAIMS]


def test_answer_list_form_and_a_refused_answer(row):
    out, _ = _call(row, answers=[{"field": CLAIMS, "value": "TBD"}])
    assert out == {"success": True, "follow_ups": []}            # a non-answer previews nothing


def test_no_follow_ups_once_forms_exist(row):
    with_forms = {**copy.deepcopy(row), "generated_forms": {"ACORD_125": {"fields": {}}}}
    out, _ = _call(with_forms, field=CLAIMS, value="Yes - we have had claims or losses")
    assert out["follow_ups"] == []


def test_another_users_session_is_refused(row):
    async def _get(_sid, *_a, **_k):
        return copy.deepcopy(row)

    with patch.object(ar, "get_processing_session", _get):
        with pytest.raises(ar.HTTPException) as exc:
            asyncio.run(ar.preview_answer(ar.PreviewAnswerRequest(session_id=SID, field=CLAIMS, value="Yes"),
                                          current_user={"id": "someone-else"}))
    assert exc.value.status_code == 403


def test_the_window_asks_the_preview_and_saves_follow_ups_under_their_own_ids():
    src = (FRONTEND / "components/form/ResolutionModal.jsx").read_text()
    helper = (FRONTEND / "utils/followUpPreview.js").read_text()
    assert "fetchFollowUps" in src and "askPreview" in src and "/api/review/preview-answer" in helper
    assert "followUpIssueId" in src and "Then:" in src and "onAddDocuments" in src
    acord = (FRONTEND / "components/form/AcordModal.jsx").read_text()
    assert "onOpenFollowUp=" in acord and "onFollowUpSaved=" in acord


# ── The frontend helper (node) ───────────────────────────────────────────────
import json as _json                                                  # noqa: E402
import shutil as _shutil                                              # noqa: E402
import subprocess as _subprocess                                      # noqa: E402

_HELPER = FRONTEND / "utils" / "followUpPreview.js"


@pytest.mark.skipif(_shutil.which("node") is None, reason="node is not installed")
def test_helper_keeps_only_the_latest_reply_and_asks_once_per_answer(tmp_path):
    script = tmp_path / "check.mjs"
    script.write_text(f"""
import * as F from {_json.dumps(_HELPER.as_uri())};
const calls = []; const results = [];
const resolvers = [];
const fetchFn = (answers) => {{ calls.push(answers); return new Promise((r) => resolvers.push(r)); }};
const timers = []; const timer = {{ set: (fn) => {{ timers.push(fn); return timers.length; }}, clear: (id) => {{ timers[id - 1] = null; }} }};
const p = F.createPreviewer(fetchFn, (l) => results.push(l), {{ timer }});
const yes = [{{ field: "q", value: "Yes" }}], no = [{{ field: "q", value: "No" }}];
p.request(yes); timers[0]();             // ask for Yes
p.request(no);  timers[1]();             // the producer changes to No before Yes replies
resolvers[1]([]);                        // No replies first
await new Promise((r) => setTimeout(r, 0));
resolvers[0]([{{ id: "rec:1", kind: "field" }}]);   // the stale Yes reply arrives late
await new Promise((r) => setTimeout(r, 0));
p.request(no);                           // the same answer again: not asked again
const debounced = [];
const p2 = F.createPreviewer(async (a) => {{ debounced.push(a); return []; }}, () => {{}}, {{ timer }});
p2.request(yes); p2.request(no);         // a quick change: only the last is asked
timers.filter(Boolean).slice(-1)[0]();
await new Promise((r) => setTimeout(r, 0));
const split = F.splitFollowUps([{{ id: "a", kind: "field" }}, {{ id: "a", kind: "field" }},
  {{ id: "b", kind: "schedule" }}, {{ id: "c", kind: "document" }}]);
const recId = F.followUpIssueId({{ source: "rec", pillar: "loss_history", keys: ["fact:loss_run_status"],
  resolution: {{ mode: "field", facts: ["loss_run_status"] }} }});
const saves = F.followUpSaves([{{ id: "x", resolution: {{ facts: ["a", "b"] }} }}], {{ a: "v", b: "  " }});
console.log(JSON.stringify({{ calls: calls.length, last: results[results.length - 1],
  shown: results.filter((r) => r.length).length, debounced: debounced.length,
  split: [split.field.length, split.open.length, split.document.length], recId,
  saves: saves.map((s) => [s.field, s.value]),
  answers: F.previewAnswers({{ a: "Yes", b: "", c: "Other" }}, ["a", "b", "c"]) }}));
""", encoding="utf-8")
    run = _subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = _json.loads(run.stdout)
    assert out["calls"] == 2 and out["last"] == [] and out["shown"] == 0   # the stale Yes never shows
    assert out["debounced"] == 1
    assert out["split"] == [1, 1, 1]
    assert out["recId"] == "rec:score:loss_history:fact:loss_run_status"
    assert out["saves"] == [["a", "v"]]
    assert out["answers"] == [{"field": "a", "value": "Yes"}]
