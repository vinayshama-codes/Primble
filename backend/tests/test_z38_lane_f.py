"""Z38 lane F (24 Oct 2026): the inline follow-up preview is fast, and the
loss-run coverage note follows every document change.

1. `answer_preview.preview_follow_ups` read the review page twice per pick
   (~2.5-3 s on package 3e835b53). Now the "before" reading is cached by the
   row's content, a whole preview by row + answers + shown boxes, and one
   reading runs the stops door and the prior-carrier grid once each. What it
   returns is unchanged - pinned here against the uncached recipe.
2. `lossCoverage.lossCoverageNoteFor` is the one message for add / exclude /
   include / reclassify, before forms and after (`handleDocumentsChanged`).

Snapshot: `laneF/p.pkl` (package 3e835b53, read with a SELECT only); the
module skips where it is absent. Never touches the database.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import pickle
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services import answer_preview as ap                             # noqa: E402
from services import stops_now as sn                                  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-vinaysharma-Downloads-Primble-16thsep/"
               "427f82bb-424b-4678-bf06-9112a9013561/scratchpad")
SNAP = SCRATCH / "laneF" / "p.pkl"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
SID = "3e835b53-fb4a-4c0e-8cd2-f71e1f4c3f6e"
CLAIMS = "loss_history_no_prior_losses_indicator"

needs_snap = pytest.mark.skipif(not SNAP.exists(), reason="lane F snapshot not on this machine")


@pytest.fixture(scope="module")
def row():
    return pickle.load(open(SNAP, "rb"))


def _uncached(row, answers, shown):
    """The pre-Z38 recipe: both readings fresh, no memo, no cache."""
    work = copy.deepcopy(row)
    written = []
    for f, v in answers:
        c = ap.apply_answer_in_memory(work, f, v)
        if c:
            written += [c, f]
    uid = str(row["user_id"])
    before, _ = ap._page_items_now(row, SID, uid)
    after, ids = ap._page_items_now(work, SID, uid)
    with patch.object(ap, "page_items_before", lambda *_a, **_k: (before, {})), \
            patch.object(ap, "page_items_now", lambda *_a, **_k: (after, ids)):
        return ap._follow_ups(row, work, SID, uid, written, shown, "x")


@needs_snap
@pytest.mark.parametrize("pick", ["no", "yes"])
def test_follow_ups_identical_to_the_uncached_recipe(row, pick):
    from services.loss_history_state import claims_question_answers
    no, yes = claims_question_answers()
    ans = [(CLAIMS, no if pick == "no" else yes)]
    ap.clear_caches()
    fast = ap.preview_follow_ups(row, SID, str(row["user_id"]), ans, [CLAIMS])
    assert fast == _uncached(row, ans, [CLAIMS])
    again = ap.preview_follow_ups(row, SID, str(row["user_id"]), ans, [CLAIMS])
    assert again == fast


@needs_snap
def test_the_second_pick_reuses_the_before_reading_and_a_repeat_is_instant(row):
    from services.loss_history_state import claims_question_answers
    no, yes = claims_question_answers()
    uid = str(row["user_id"])
    ap.clear_caches()
    stats = dict(ap.CACHE_STATS)
    ap.preview_follow_ups(row, SID, uid, [(CLAIMS, no)], [CLAIMS])
    ap.preview_follow_ups(row, SID, uid, [(CLAIMS, yes)], [CLAIMS])
    assert ap.CACHE_STATS["before_misses"] - stats["before_misses"] == 1
    assert ap.CACHE_STATS["before_hits"] - stats["before_hits"] == 1
    t = time.time()
    ap.preview_follow_ups(row, SID, uid, [(CLAIMS, no)], [CLAIMS])
    assert time.time() - t < 0.5                                  # loose: a cached result
    assert ap.CACHE_STATS["result_hits"] - stats["result_hits"] == 1


@needs_snap
def test_a_changed_row_misses_the_cache(row):
    uid = str(row["user_id"])
    ap.clear_caches()
    ap.warm(row, SID, uid)
    other = copy.deepcopy(row)
    other.setdefault("facts", {})["z38_probe"] = {"value": "x"}
    assert ap.row_fingerprint(other) != ap.row_fingerprint(row)
    misses = ap.CACHE_STATS["before_misses"]
    ap.page_items_before(other, SID, uid)
    assert ap.CACHE_STATS["before_misses"] == misses + 1


@needs_snap
def test_a_memoised_reading_equals_a_plain_one(row):
    uid = str(row["user_id"])
    assert ap.page_items_now(row, SID, uid) == ap._page_items_now(row, SID, uid)


def test_stops_memo_is_scoped_and_returns_copies():
    calls = []
    real = sn.field_level_stops

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    session = {"facts": {}, "flags": {}, "docs": [], "recommendations": [{"form_id": "ACORD_125"}]}
    with patch.object(sn, "field_level_stops", spy):
        sn.stops_now(session, pre_form=True)
        sn.stops_now(session, pre_form=True)
        assert len(calls) == 2                                    # no memo outside the block
        with sn.stops_memo():
            a = sn.stops_now(session, pre_form=True)
            a["soft"].append("mutated")
            b = sn.stops_now(session, ["ACORD_125"], pre_form=True, facts=session["facts"],
                             flags=session["flags"])
            assert len(calls) == 3 and "mutated" not in b["soft"]
            sn.stops_now(dict(session), pre_form=True)            # another row object: recomputed
            assert len(calls) == 4
    assert sn._STOPS_MEMO.get() is None


def test_route_takes_warm():
    src = (Path(__file__).resolve().parents[1] / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    assert "warm: Optional[bool] = None" in src and "from services.answer_preview import warm" in src


def test_route_warm_reads_before_only(row=None):
    if not SNAP.exists():
        pytest.skip("snapshot absent")
    import routes.audit_routes as ar
    r = pickle.load(open(SNAP, "rb"))

    async def _get(_sid, *_a, **_k):
        return copy.deepcopy(r)

    ap.clear_caches()
    with patch.object(ar, "get_processing_session", _get):
        out = asyncio.run(ar.preview_answer(ar.PreviewAnswerRequest(session_id=SID, warm=True),
                                            current_user={"id": r["user_id"]}))
    assert out == {"success": True, "follow_ups": []}
    assert len(ap._BEFORE_CACHE) == 1


# ── frontend (node) ───────────────────────────────────────────────────────────

def test_modal_warms_and_prefetches_and_every_document_change_sets_the_note():
    modal = (FRONTEND / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "warmFollowUps(API_BASE, sessionId)" in modal and "prefetchAnswerLists(" in modal
    acord = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert acord.count("lossCoverageNoteFor(") == 2           # reclassify (pre-form) + every other change
    body = acord[acord.index("const handleDocumentsChanged"):]
    body = body[:body.index("\n  };")]
    assert "lossCoverageNoteFor(pkgBefore, restored.package_sqs" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_helpers(tmp_path):
    lc = (FRONTEND / "utils" / "lossCoverage.js").as_uri()
    fp = (FRONTEND / "utils" / "followUpPreview.js").as_uri()
    script = tmp_path / "check.mjs"
    script.write_text(f"""
import * as L from {json.dumps(lc)};
import * as F from {json.dumps(fp)};
const cov = (n) => ({{ covered: n, required: 5, label: `${{n}} of 5 years (2021-2023)` }});
const out = {{}};
out.add = L.lossCoverageNoteFor({{ package_sqs_score: 80 }}, {{ package_sqs_score: 84, loss_coverage: cov(3) }}, []);
out.same = L.lossCoverageNoteFor({{ package_sqs_score: 80, loss_coverage: cov(3) }}, {{ package_sqs_score: 80, loss_coverage: cov(3) }});
out.exclude = L.lossCoverageNoteFor({{ package_sqs_score: 84, loss_coverage: cov(3) }}, {{ package_sqs_score: 80 }});
out.unrelated = L.lossCoverageNoteFor({{ package_sqs_score: 80 }}, {{ package_sqs_score: 80 }}, []);
out.unknownBefore = L.lossCoverageNoteFor({{ package_sqs_score: 80 }}, {{ package_sqs_score: 80, loss_coverage: cov(3) }},
  [{{ doc_type: "loss_run", excluded: false }}]);
out.prefetch = F.prefetchAnswerLists(["q"], {{ q: {{ options: ["Yes", "No", "Other"] }} }});
out.prefetchLong = F.prefetchAnswerLists(["q"], {{ q: {{ options: ["a", "b", "c", "d", "e"] }} }}).length;
out.prefetchTwo = F.prefetchAnswerLists(["q", "r"], {{ q: {{ options: ["Yes"] }} }}).length;
// prefetch fills the cache; a pick then shows at once with no second ask
const asked = []; const shown = [];
const timer = {{ set: (fn) => setTimeout(fn, 0), clear: (id) => clearTimeout(id) }};
const p = F.createPreviewer(async (a) => {{ asked.push(a[0].value); return [{{ id: a[0].value }}]; }},
  (l) => shown.push(l), {{ timer }});
await p.prefetch(out.prefetch);
p.request([{{ field: "q", value: "No" }}]);
out.asked = asked; out.shownAfterPick = shown;
// a pick whose prefetch is still on its way waits for it, never asks twice
const asked2 = []; const shown2 = []; let release;
const p2 = F.createPreviewer((a) => {{ asked2.push(a[0].value); return new Promise((r) => {{ release = () => r([{{ id: "late" }}]); }}); }},
  (l) => shown2.push(l), {{ timer }});
const pf = p2.prefetch([[{{ field: "q", value: "Yes" }}]]);
p2.request([{{ field: "q", value: "Yes" }}]);
release(); await pf; await new Promise((r) => setTimeout(r, 5));
out.asked2 = asked2; out.shown2 = shown2;
// a superseded live request is aborted
const signals = [];
const p3 = F.createPreviewer((a, o) => {{ signals.push(o && o.signal); return new Promise(() => {{}}); }}, () => {{}}, {{ timer }});
p3.request([{{ field: "q", value: "Yes" }}]); await new Promise((r) => setTimeout(r, 5));
p3.request([{{ field: "q", value: "No" }}]); await new Promise((r) => setTimeout(r, 5));
out.aborted = signals.length === 2 && signals[0].aborted === true && signals[1].aborted === false;
console.log(JSON.stringify(out));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["add"] == "Loss runs now cover 3 of 5 years - score 84 (+4)"
    assert o["same"] == ""
    assert o["exclude"] == "Loss runs now cover 0 of 5 years - score 80 (-4)"
    assert o["unrelated"] == ""
    assert o["unknownBefore"] == ""
    assert o["prefetch"] == [[{"field": "q", "value": "Yes"}], [{"field": "q", "value": "No"}]]
    assert o["prefetchLong"] == 0 and o["prefetchTwo"] == 0
    assert o["asked"] == ["Yes", "No"] and o["shownAfterPick"] == [[{"id": "No"}]]
    assert o["asked2"] == ["Yes"] and o["shown2"][-1] == [{"id": "late"}]
    assert o["aborted"] is True


def test_a_cancel_never_kills_the_previewer(tmp_path):
    """Review fix (24 Oct): React StrictMode (dev) runs the window's unmount
    cleanup once on a LIVE window; a permanent stop then dropped every later
    reply, so no follow-up ever showed on localhost. A cancel ends only what is
    in flight."""
    fp = (FRONTEND / "utils" / "followUpPreview.js").as_uri()
    script = tmp_path / "cancel.mjs"
    script.write_text(f"""
import * as F from {json.dumps(fp)};
const timer = {{ set: (fn) => setTimeout(fn, 0), clear: (id) => clearTimeout(id) }};
const shown = []; const asked = [];
const p = F.createPreviewer(async (a) => {{ asked.push(a[0].value); return [{{ id: a[0].value }}]; }},
  (l) => shown.push(l), {{ timer }});
p.cancel();                                   // StrictMode's simulated unmount
await p.prefetch([[{{ field: "q", value: "Yes" }}]]);
p.request([{{ field: "q", value: "No" }}]);
await new Promise((r) => setTimeout(r, 10));
console.log(JSON.stringify({{ asked, shown }}));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["asked"] == ["Yes", "No"]
    assert o["shown"][-1] == [{"id": "No"}]
