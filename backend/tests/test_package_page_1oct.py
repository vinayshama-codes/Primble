"""Orbin item 1 (client, 22 Sep; owner's decisions of 1 Oct 2026): clicking a
package always lands on its package page.

* Forms generated  -> "Continue where you left off" opens the editor on the form
  last open; the score reads "Total Package Score"; the generated forms are
  listed under Key Details, each with its own score and an Open link.
* Forms generating -> the same button opens the progress screen.
* A run that did not finish -> "Generation didn't finish" + "Continue to form
  selection" - never an endless spinner. A live run proves it is alive with a
  heartbeat (services/generation_state.py); a dead one is told apart by its
  silence, so a restart, a deploy or a crash is reported, not waited out.
* Once forms exist (or are generating) the actions that re-read the documents
  - reclassify, exclude, supporting-only, confirm a Data Consistency value,
  resolve integrity, generate again - are off, on the screen AND on the server:
  they never update forms that already exist.
"""
import ast
import asyncio
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

import routes.audit_routes as ar
import routes.form_routes as fr
import routes.job_routes as jr
import services.generation_state as gs
from services.job_queue import InMemoryJobQueue, LocalFileJobQueue

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
MODAL = FRONTEND / "components" / "form" / "AcordModal.jsx"
RAIL = FRONTEND / "components" / "form" / "review" / "ReviewRailLayout.jsx"
PG = FRONTEND / "utils" / "packageGeneration.js"
_EM_DASHES = ("—", "–")


def _src(p):
    return Path(p).read_text(encoding="utf-8")


def _iso(seconds_ago, now=1_800_000_000.0):
    return datetime.fromtimestamp(now - seconds_ago, tz=timezone.utc).isoformat()


NOW = 1_800_000_000.0


# ══ 1. The one door: generation_state ════════════════════════════════════════

def test_forms_win_over_everything():
    for job in (None, {"status": "failed"}, {"status": "processing", "updated_at": _iso(10_000)}):
        sess = {"generated_forms": {"ACORD_125": {}}, "generation_job_id": "j1"}
        assert gs.generation_state(sess, job, NOW) == gs.STATE_DONE


@pytest.mark.parametrize("sess", [{}, None, "junk", {"generated_forms": {}}, {"generation_job_id": ""}])
def test_no_marker_is_never_generated(sess):
    assert gs.generation_state(sess, {"status": "processing"}, NOW) == gs.STATE_NONE


def test_a_fresh_processing_job_is_running():
    sess = {"generation_job_id": "j1"}
    job = {"status": "processing", "updated_at": _iso(gs.STALE_AFTER_SECONDS - 5)}
    assert gs.generation_state(sess, job, NOW) == gs.STATE_RUNNING


def test_a_silent_processing_job_did_not_finish():
    sess = {"generation_job_id": "j1"}
    job = {"status": "processing", "updated_at": _iso(gs.STALE_AFTER_SECONDS + 5)}
    assert gs.generation_state(sess, job, NOW) == gs.STATE_INTERRUPTED


def test_a_pending_job_waits_the_queue_window_not_the_heartbeat_window():
    sess = {"generation_job_id": "j1"}
    queued = {"status": "pending", "updated_at": _iso(gs.STALE_AFTER_SECONDS + 60)}
    assert gs.generation_state(sess, queued, NOW) == gs.STATE_RUNNING
    old = {"status": "pending", "updated_at": _iso(gs.PENDING_STALE_AFTER_SECONDS + 5)}
    assert gs.generation_state(sess, old, NOW) == gs.STATE_INTERRUPTED


@pytest.mark.parametrize("job", [None, {"status": "failed"}, {"status": "weird"}, {}])
def test_a_failed_or_missing_job_did_not_finish(job):
    assert gs.generation_state({"generation_job_id": "j1"}, job, NOW) == gs.STATE_INTERRUPTED


def test_a_completed_job_without_forms_is_a_raced_read():
    # forms are stored BEFORE the job completes; the route re-reads the row
    assert gs.generation_state({"generation_job_id": "j1"}, {"status": "completed"}, NOW) == gs.STATE_RUNNING


@pytest.mark.parametrize("stamp", [None, "", "not a date", "2026-13-45T99:99"])
def test_an_unreadable_timestamp_never_declares_a_run_dead(stamp):
    job = {"status": "processing", "updated_at": stamp, "created_at": stamp}
    assert gs.job_is_stale(job, NOW) is False
    assert gs.generation_state({"generation_job_id": "j1"}, job, NOW) == gs.STATE_RUNNING


def test_timestamp_shapes():
    old = NOW - gs.STALE_AFTER_SECONDS - 100
    for stamp in (datetime.fromtimestamp(old, tz=timezone.utc).isoformat(),
                  datetime.fromtimestamp(old, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                  datetime.utcfromtimestamp(old).isoformat(),          # naive = UTC
                  datetime.fromtimestamp(old, tz=timezone.utc),        # a datetime
                  old):                                                 # epoch seconds
        assert gs.job_is_stale({"status": "processing", "updated_at": stamp}, NOW) is True, stamp
    # updated_at missing -> created_at is the evidence
    assert gs.job_is_stale({"status": "processing", "created_at": _iso(gs.STALE_AFTER_SECONDS + 1)}, NOW)


@pytest.mark.parametrize("status", ["completed", "failed", "", None])
def test_a_finished_job_is_never_stale(status):
    assert gs.job_is_stale({"status": status, "updated_at": _iso(10 ** 7)}, NOW) is False
    assert gs.job_is_stale(None, NOW) is False and gs.job_is_stale("x", NOW) is False


def test_the_lock_sentences():
    assert gs.forms_locked_reason({"generated_forms": {"A": {}}}) == \
        "Forms are generated - make changes in the form editor."
    assert gs.forms_locked_reason({"generated_forms": {"A": {}}}, gs.STATE_INTERRUPTED) == \
        "Forms are generated - make changes in the form editor."
    assert gs.forms_locked_reason({}, gs.STATE_RUNNING) == \
        "Forms are being generated - wait for them to finish."
    for state in (gs.STATE_NONE, gs.STATE_INTERRUPTED, None):
        assert gs.forms_locked_reason({}, state) is None
    assert gs.forms_locked_reason(None, None) is None
    for text in (gs.forms_locked_reason({"generated_forms": {"A": 1}}), gs.forms_locked_reason({}, gs.STATE_RUNNING)):
        assert not any(d in text for d in _EM_DASHES)


def test_env_windows_are_bounded(monkeypatch):
    monkeypatch.setenv("X_WIN", "3")
    assert gs._env_seconds("X_WIN", 300, 60) == 60
    monkeypatch.setenv("X_WIN", "junk")
    assert gs._env_seconds("X_WIN", 300, 60) == 300
    monkeypatch.setenv("X_WIN", "900")
    assert gs._env_seconds("X_WIN", 300, 60) == 900
    # ten missed beats at the default
    assert gs.STALE_AFTER_SECONDS >= 10 * gs.HEARTBEAT_SECONDS


# ══ 2. The heartbeat and the queue's touch ════════════════════════════════════

def test_the_heartbeat_keeps_a_run_alive_and_never_overwrites_its_end():
    async def go():
        q = InMemoryJobQueue()
        jid = await q.enqueue("form_generation", {}, "u", session_id="s")
        await q.update_status(jid, "processing")
        q._jobs[jid]["updated_at"] = _iso(10_000, now=datetime.now(timezone.utc).timestamp())
        assert gs.job_is_stale(await q.get_status(jid))
        hb = await gs.GenerationHeartbeat(q, jid, every=0.02).start()
        await hb.start()                                  # a second start adds no task
        await asyncio.sleep(0.1)
        assert not gs.job_is_stale(await q.get_status(jid))
        await q.update_status(jid, "completed")
        stamp = (await q.get_status(jid))["updated_at"]
        await asyncio.sleep(0.1)
        job = await q.get_status(jid)
        assert job["status"] == "completed" and job["updated_at"] == stamp
        await hb.stop(); await hb.stop()                  # idempotent
        assert hb._task is None
    asyncio.run(go())


def test_a_queue_without_touch_gets_no_heartbeat_and_no_error():
    class Bare:
        pass

    async def go():
        async with gs.GenerationHeartbeat(Bare(), "j1", every=0.01):
            await asyncio.sleep(0.05)
    asyncio.run(go())


def test_a_failing_touch_is_logged_not_raised():
    class Boom:
        calls = 0

        async def touch(self, job_id):
            Boom.calls += 1
            raise RuntimeError("db down")

    async def go():
        hb = await gs.GenerationHeartbeat(Boom(), "j1", every=0.01).start()
        await asyncio.sleep(0.06)
        await hb.stop()
    asyncio.run(go())
    assert Boom.calls >= 2


def test_no_job_id_no_task():
    async def go():
        hb = await gs.GenerationHeartbeat(InMemoryJobQueue(), "", every=0.01).start()
        assert hb._task is None
    asyncio.run(go())


def test_the_file_queue_touches_only_a_processing_job(tmp_path):
    async def go():
        q = LocalFileJobQueue(jobs_dir=str(tmp_path))
        jid = await q.enqueue("form_generation", {}, "u", session_id="s")
        before = (await q.get_status(jid))["updated_at"]
        await q.touch(jid)                                   # pending: untouched
        assert (await q.get_status(jid))["updated_at"] == before
        await q.update_status(jid, "processing")
        p = Path(q._path(jid))
        job = json.loads(p.read_text()); job["updated_at"] = "2000-01-01T00:00:00+00:00"; p.write_text(json.dumps(job))
        await q.touch(jid)
        assert (await q.get_status(jid))["updated_at"] != "2000-01-01T00:00:00+00:00"
        await q.update_status(jid, "failed")
        stamp = (await q.get_status(jid))["updated_at"]
        await q.touch(jid)
        assert (await q.get_status(jid))["updated_at"] == stamp
        await q.touch("no-such-job")                         # never raises
    asyncio.run(go())


def test_the_default_touch_reads_then_writes_only_processing():
    from services.job_queue import JobQueue

    class Q(InMemoryJobQueue):
        touch = JobQueue.touch                     # the interface's own default

    async def go():
        q = Q()
        jid = await q.enqueue("form_generation", {}, "u")
        await q.update_status(jid, "failed")
        stamp = (await q.get_status(jid))["updated_at"]
        await q.touch(jid)
        assert (await q.get_status(jid))["status"] == "failed"
        assert (await q.get_status(jid))["updated_at"] == stamp
        await q.update_status(jid, "processing")
        q._jobs[jid]["updated_at"] = "2000-01-01T00:00:00+00:00"
        await q.touch(jid)
        assert (await q.get_status(jid))["updated_at"] != "2000-01-01T00:00:00+00:00"
        assert (await q.get_status(jid))["status"] == "processing"
        await q.touch("missing")
    asyncio.run(go())


def test_the_db_touch_is_one_conditional_statement():
    src = _src(BACKEND / "repositories" / "job_repository.py")
    body = src[src.index("async def touch"):]
    body = body[:body.index("# ASYNC-SAFE")]
    assert "UPDATE jobs SET updated_at = $1 WHERE job_id = $2 AND status = 'processing'" in body
    assert body.count("execute(") == 1


# ══ 3. The generation paths beat, and a crash says so ═════════════════════════

def _fn_src(path, name):
    src = _src(path)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(name)


def test_the_sync_route_beats_inside_its_try_and_stops_in_finally():
    body = _fn_src(BACKEND / "routes" / "form_routes.py", "select_forms_bulk")
    try_at = body.index("    try:\n        await _heartbeat.start()")
    assert body.index("GenerationHeartbeat(_queue, _job_id)") < try_at
    assert body.index("finally:\n        await _heartbeat.stop()") > try_at
    # every way the run ends without forms marks the job failed
    assert body.count("await _mark_generation_failed(_queue, _job_id,") == 2
    # the 202 (async) return comes before the heartbeat - the worker beats then
    assert body.index("status_code=202") < body.index("GenerationHeartbeat(")


def test_the_worker_beats_and_stops():
    body = _fn_src(BACKEND / "worker.py", "_process_form_generation_job")
    assert "GenerationHeartbeat(queue, job_id)" in body
    assert "await _heartbeat.start()" in body
    assert body.rstrip().endswith("await _heartbeat.stop()")


def test_mark_failed_never_raises():
    class Q:
        async def update_status(self, *a, **k):
            raise RuntimeError("db down")
    asyncio.run(fr._mark_generation_failed(Q(), "j1", "boom"))

    seen = {}

    class Q2:
        async def update_status(self, job_id, status, **k):
            seen.update(job_id=job_id, status=status, **k)
    asyncio.run(fr._mark_generation_failed(Q2(), "j1", "x" * 900))
    assert seen["status"] == "failed" and len(seen["error"]) == 500
    asyncio.run(fr._mark_generation_failed(Q2(), "j2", ""))
    assert seen["error"] == "generation_failed"


def test_the_job_status_reports_a_dead_generation_only():
    class Q:
        def __init__(self, job):
            self.job = job

        async def get_status(self, job_id):
            return self.job

    def status(job, monkeypatch):
        monkeypatch.setattr(jr, "get_job_queue", lambda: Q(job))
        resp = asyncio.run(jr.get_job_status("j1", current_user={"id": "u1"}))
        return json.loads(resp.body)

    mp = pytest.MonkeyPatch()
    try:
        dead = {"job_id": "j1", "user_id": "u1", "session_id": "s", "status": "processing",
                "job_type": "form_generation", "updated_at": _iso(10 ** 6, now=datetime.now(timezone.utc).timestamp())}
        assert status(dead, mp)["stale"] is True
        assert status({**dead, "job_type": "extraction"}, mp)["stale"] is False   # extraction never beats
        assert status({**dead, "status": "completed"}, mp)["stale"] is False
        fresh = {**dead, "updated_at": datetime.now(timezone.utc).isoformat()}
        assert status(fresh, mp)["stale"] is False
    finally:
        mp.undo()


# ══ 4. The server locks the pre-form actions ═════════════════════════════════

class _Queue:
    def __init__(self, job=None, boom=False):
        self.job, self.boom = job, boom

    async def get_status(self, job_id):
        if self.boom:
            raise RuntimeError("queue down")
        return self.job


def _refuse(session, queue, monkeypatch):
    monkeypatch.setattr(fr, "get_job_queue", lambda: queue)
    try:
        asyncio.run(fr._refuse_once_forms_exist(session))
        return None
    except HTTPException as ex:
        return ex


def test_the_lock_refuses_once_forms_exist(monkeypatch):
    ex = _refuse({"generated_forms": {"ACORD_125": {}}}, _Queue(), monkeypatch)
    assert ex.status_code == 409 and ex.detail == "Forms are generated - make changes in the form editor."


def test_the_lock_refuses_while_a_live_run_works(monkeypatch):
    live = {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}
    ex = _refuse({"generation_job_id": "j1"}, _Queue(live), monkeypatch)
    assert ex.status_code == 409 and "being generated" in ex.detail
    # an unreadable queue is the safe side: refuse
    assert _refuse({"generation_job_id": "j1"}, _Queue(boom=True), monkeypatch).status_code == 409


def test_the_lock_lets_an_unfinished_run_go_again(monkeypatch):
    dead = {"status": "processing", "updated_at": _iso(10 ** 6, now=datetime.now(timezone.utc).timestamp())}
    assert _refuse({"generation_job_id": "j1"}, _Queue(dead), monkeypatch) is None
    assert _refuse({"generation_job_id": "j1"}, _Queue({"status": "failed"}), monkeypatch) is None
    assert _refuse({"generation_job_id": "j1"}, _Queue(None), monkeypatch) is None
    assert _refuse({}, _Queue(), monkeypatch) is None


@pytest.mark.parametrize("route", [
    "submission_integrity_resolve", "document_reclassify", "underwriting_confirm_value", "select_forms_bulk",
])
def test_every_pre_form_writer_checks_the_lock_right_after_the_owner(route):
    body = _fn_src(BACKEND / "routes" / "form_routes.py", route)
    owner = body.index('raise HTTPException(403, "Access denied")')
    lock = body.index("await _refuse_once_forms_exist(session)")
    assert owner < lock
    # nothing that writes runs before the lock
    between = body[owner:lock]
    for writer in ("reclassify_document(", "confirm_underwriting_value(", "resolve_submission_integrity(",
                   ".enqueue(", "upd_processing_session("):
        assert writer not in between, (route, writer)


def test_reclassify_refuses_on_a_generated_package_before_any_work(monkeypatch):
    from models.schemas import DocumentReclassifyRequest

    async def _get(sid):
        return {"user_id": "u1", "generated_forms": {"ACORD_125": {}}}

    async def _never(*a, **k):
        raise AssertionError("reclassify ran on a generated package")

    monkeypatch.setattr(fr, "get_processing_session", _get)
    monkeypatch.setattr(fr, "reclassify_document", _never)
    req = DocumentReclassifyRequest(session_id="s1", doc_id="d1", action="exclude")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(fr.document_reclassify(req, current_user={"id": "u1"}))
    assert ei.value.status_code == 409


# ══ 5. GET /api/session: state, the producer's order, the last open form ══════

def _get_session(row, monkeypatch, job=None, reread=None):
    reads = {"n": 0}

    async def _get(sid):
        reads["n"] += 1
        return reread if (reread is not None and reads["n"] > 1) else row

    monkeypatch.setattr(fr, "get_processing_session", _get)
    monkeypatch.setattr(fr, "check_payment_access", lambda *a, **k: None)
    monkeypatch.setattr(fr, "get_job_queue", lambda: _Queue(job))
    resp = asyncio.run(fr.get_session("s1", current_user={"id": "u1", "payment_status": "ok"}))
    return json.loads(resp.body), reads["n"]


def test_the_session_payload_orders_the_forms_and_names_the_last_open(monkeypatch):
    row = {"user_id": "u1", "selected_form_ids": ["ACORD_125", "ACORD_126", "ACORD_GONE", "ACORD_25"],
           "generated_forms": {"ACORD_25": {"form_id": "ACORD_25"}, "ACORD_125": {"form_id": "ACORD_125"},
                               "ACORD_126": {"form_id": "ACORD_126"}, "ACORD_131": {"form_id": "ACORD_131"}},
           "active_form_id": "ACORD_126"}
    body, _ = _get_session(row, monkeypatch)
    assert body["generation_state"] == "done"
    assert body["form_order"] == ["ACORD_125", "ACORD_126", "ACORD_25", "ACORD_131"]
    assert body["active_form_id"] == "ACORD_126"
    # a last-open form the package no longer has falls back to the first
    body, _ = _get_session({**row, "active_form_id": "ACORD_GONE"}, monkeypatch)
    assert body["active_form_id"] == "ACORD_125"
    # selected_form_ids emptied (a pre-form re-run) -> the forms keep their own order
    body, _ = _get_session({**row, "selected_form_ids": []}, monkeypatch)
    assert sorted(body["form_order"]) == sorted(row["generated_forms"]) and body["active_form_id"] == "ACORD_126"


def test_the_session_payload_before_forms(monkeypatch):
    body, _ = _get_session({"user_id": "u1"}, monkeypatch)
    assert body["generation_state"] == "none" and body["form_order"] == [] and body["active_form_id"] is None
    live = {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}
    body, _ = _get_session({"user_id": "u1", "generation_job_id": "j1"}, monkeypatch, job=live)
    assert body["generation_state"] == "running"
    body, _ = _get_session({"user_id": "u1", "generation_job_id": "j1"}, monkeypatch, job={"status": "failed"})
    assert body["generation_state"] == "interrupted"


def test_a_job_that_completed_between_two_reads_rereads_the_row(monkeypatch):
    row = {"user_id": "u1", "generation_job_id": "j1"}
    stored = {"user_id": "u1", "generated_forms": {"ACORD_125": {}}, "selected_form_ids": ["ACORD_125"]}
    body, reads = _get_session(row, monkeypatch, job={"status": "completed"}, reread=stored)
    assert reads == 2 and body["generation_state"] == "done" and body["form_order"] == ["ACORD_125"]
    body, reads = _get_session(row, monkeypatch, job={"status": "completed"}, reread=row)
    assert reads == 2 and body["generation_state"] == "interrupted"


def test_the_active_form_endpoint(monkeypatch):
    from models.schemas import ActiveFormRequest
    calls = []

    async def _set(sid, uid, fid):
        calls.append((sid, uid, fid))
        return fid == "ACORD_125"

    monkeypatch.setattr(fr, "set_active_form", _set)
    ok = asyncio.run(fr.set_session_active_form("s1", ActiveFormRequest(form_id=" ACORD_125 "), current_user={"id": 7}))
    assert json.loads(ok.body) == {"success": True, "active_form_id": "ACORD_125"}
    assert calls[-1] == ("s1", "7", "ACORD_125")
    for bad, code in (("", 400), ("x" * 65, 400), ("ACORD_999", 404)):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(fr.set_session_active_form("s1", ActiveFormRequest(form_id=bad), current_user={"id": 7}))
        assert ei.value.status_code == code


def test_the_active_form_write_is_owner_scoped_and_one_key():
    body = _fn_src(BACKEND / "repositories" / "session_repository.py", "set_active_form")
    stmt = body[body.index('"UPDATE processing_sessions"'):body.index("sid, str(user_id)")]
    sql = " ".join(re.findall(r'"([^"]*)"', stmt))
    assert "jsonb_set(data, '{active_form_id}'" in sql
    assert "WHERE id = $1 AND user_id = $2 AND (data->'generated_forms') ? $3" in sql
    assert "updated_at" not in sql          # opening a form does not reorder the dashboard


# ══ 6. A fix on the package page refreshes its Key Details ═══════════════════

def test_key_details_ride_along_only_after_generation():
    from services.sqs_service import key_details
    facts = {"applicant_name": "Orbin LLC"}
    assert ar._package_page_key_details({"facts": facts}) == {}
    assert ar._package_page_key_details({"generated_forms": {}, "facts": facts}) == {}
    out = ar._package_page_key_details({"generated_forms": {"A": {}}, "facts": facts, "flags": {}})
    assert out == {"key_details": key_details(facts, {})}

    class _Boom(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")
    assert ar._package_page_key_details(_Boom()) == {}


def test_both_handlers_spread_it():
    src = _src(BACKEND / "routes" / "audit_routes.py")
    tree = ast.parse(src)
    for name in ("resolve_issue", "reopen_issue"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        spreads = [v for n in ast.walk(fn) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if k is None and isinstance(v, ast.Call) and getattr(v.func, "id", None) == "_package_page_key_details"]
        assert spreads, name


# ══ 7. The frontend helper, run for real ═════════════════════════════════════

def test_the_frontend_sentences_are_the_servers():
    pg = _src(PG)
    assert f'FORMS_LOCKED_TEXT = "{gs.forms_locked_reason({"generated_forms": {"A": 1}})}"' in pg
    assert f'FORMS_RUNNING_TEXT = "{gs.forms_locked_reason({}, gs.STATE_RUNNING)}"' in pg
    for state in (gs.STATE_NONE, gs.STATE_RUNNING, gs.STATE_DONE, gs.STATE_INTERRUPTED):
        assert f'= "{state}";' in pg


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_helper_in_node(tmp_path):
    script = tmp_path / "check.mjs"
    gen = {"ACORD_25": {"sqs": {"sqs_score": 81, "grade": "B", "tier": "Almost There"}},
           "ACORD_125": {"sqs": {"sqs_score": "77", "tier": "Needs Work"}},
           "ACORD_126": {"sqs": {"sqs_score": ""}},
           "ACORD_131": {}}
    script.write_text(
        f"import * as P from {json.dumps(PG.as_uri())};\n"
        f"const gen = {json.dumps(gen)};\n"
        "const out = {\n"
        " st: [P.generationStateOf(null), P.generationStateOf({generation_state: 'interrupted', generated_forms: {A: 1}}),\n"
        "      P.generationStateOf({generated_forms: {A: 1}}), P.generationStateOf({generation_job_id: 'j'}),\n"
        "      P.generationStateOf({generation_state: 'bogus'}), P.generationStateOf({generated_forms: {}})],\n"
        " order: P.orderedFormIds(gen, ['ACORD_125', 'NOPE', 'ACORD_125', 'ACORD_126']),\n"
        " keys: Object.keys(P.inProducerOrder(gen, ['ACORD_131', 'ACORD_25'])),\n"
        " empty: [P.orderedFormIds(null, ['A']), P.orderedFormIds({}, null), P.formToOpen({}, [], 'A', 'B')],\n"
        " open: [P.formToOpen(gen, ['ACORD_125'], 'ACORD_25', 'ACORD_126'), P.formToOpen(gen, ['ACORD_125'], 'NOPE', 'ACORD_126'),\n"
        "        P.formToOpen(gen, ['ACORD_125'], null, 'GONE'), P.formToOpen(gen, null, null, null)],\n"
        " lock: [P.lockedReason('done'), P.lockedReason('running'), P.lockedReason('interrupted'), P.lockedReason('none')],\n"
        " label: ['done', 'running', 'interrupted', 'none'].map(P.continueLabel),\n"
        " head: ['done', 'running', 'interrupted', 'none'].map(P.scoreHeading),\n"
        " rows: P.formRows(gen, ['ACORD_125']),\n"
        "};\n"
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["st"] == ["none", "interrupted", "done", "running", "none", "none"]
    assert o["order"] == ["ACORD_125", "ACORD_126", "ACORD_25", "ACORD_131"]
    assert o["keys"] == ["ACORD_131", "ACORD_25", "ACORD_125", "ACORD_126"]
    assert o["empty"] == [[], [], None]
    assert o["open"] == ["ACORD_25", "ACORD_126", "ACORD_125", "ACORD_25"]
    assert o["lock"] == ["Forms are generated - make changes in the form editor.",
                         "Forms are being generated - wait for them to finish.", None, None]
    assert o["label"] == ["Continue where you left off", "Continue where you left off",
                          "Continue to form selection", "Continue to form selection"]
    assert o["head"] == ["Total Package Score", "Score so far", "Score so far", "Score so far"]
    assert o["rows"] == [
        {"formId": "ACORD_125", "label": "ACORD 125", "score": 77, "grade": None, "tier": "Needs Work"},
        {"formId": "ACORD_25", "label": "ACORD 25", "score": 81, "grade": "B", "tier": "Almost There"},
        {"formId": "ACORD_126", "label": "ACORD 126", "score": None, "grade": None, "tier": None},
        {"formId": "ACORD_131", "label": "ACORD 131", "score": None, "grade": None, "tier": None},
    ]


# ══ 8. The screens ═══════════════════════════════════════════════════════════

def test_a_package_click_always_lands_on_the_package_page():
    src = _src(MODAL)
    body = src[src.index("const handleResumeSession = sid =>"):]
    body = body[:body.index("const handleSendToEpic")]
    assert 'setStep("editor")' not in body.split("const ok = await _restoreFromExtraction(sid, _freshSignal());")[0]
    assert "_restoreFromExtraction(sid, _freshSignal())" in body
    assert "ctrl.signal);" not in body.split("fetch(`${API_BASE}/api/session/${sid}`")[1]
    # essentials untouched
    assert 'if (isEssentials && data?.session_id) {\n          setSessionId(sid); setStep("lite");' in body


def test_no_restore_is_handed_a_spent_signal():
    src = _src(MODAL)
    assert "_restoreFromExtraction(resumeSessionId, ctrl.signal)" not in src
    assert "_restoreFromExtraction(sid, ctrl.signal)" not in src


def test_the_poll_stops_on_a_dead_run_and_a_live_one_is_waited_out():
    src = _src(MODAL)
    poll = src[src.index("const _pollJobStatus = async"):]
    poll = poll[:poll.index("};\n")]
    assert "if (job.stale) throw new Error(GENERATION_DIDNT_FINISH);" in poll
    assert "_pollJobStatus(data.generation_job_id, 1200)" in src


def test_every_way_into_the_editor_uses_one_loader():
    src = _src(MODAL)
    assert src.count("Object.keys(data.generated_forms)[0]") == 0
    assert src.count("Object.keys(d.generated_forms)[0]") == 0
    assert src.count("_loadEditorState(") >= 6


def test_both_layouts_switch_the_button_and_the_score_label():
    rail, modal = _src(RAIL), _src(MODAL)
    assert "{continueLabel(genState)}" in rail and "{continueLabel(pkgGen.state)}" in modal
    assert "onContinue={handleContinueFromPackage}" in modal and "onClick={handleContinueFromPackage}" in modal
    assert 'onContinue={() => setStep("form_selection")}' not in modal
    assert '? <div className="rr-ready__note">Total Package Score</div>' in rail
    assert '{pkgGen.state === GEN_DONE ? scoreHeading(GEN_DONE) : "Submission Quality Score so far"}' in modal
    assert '{pkgGen.state !== GEN_DONE && <div className="tier2-detail">It can change when forms are generated.</div>}' in modal


def test_both_layouts_lock_the_document_and_value_actions():
    rail, modal = _src(RAIL), _src(MODAL)
    assert rail.count("disabled={anyReclassBusy || !!lockText}") == 3
    assert "const rowDisabled = busy || !!lockText;" in rail
    assert "disabled={anyConfirmInFlight || !picked || !!lockText}" in rail
    assert modal.count("disabled={anyReclassBusy || reclassLocked}") == 3
    assert "const rowDisabled = busy || !!lockedReason(pkgGen.state);" in modal
    for handler in ("handleResolveIntegrity", "handleReclassify", "handleConfirmUnderwriting"):
        head = modal[modal.index(f"const {handler} = async"):]
        head = head[:head.index("try {")]
        assert "if (lockedReason(pkgGen.state)) { setError(lockedReason(pkgGen.state)); return; }" in head, handler


def test_after_generation_a_missing_form_is_added_in_the_package_not_ticked():
    modal = _src(MODAL)
    assert "if (formsGenerated) return list.filter((f) => f && !Object.prototype.hasOwnProperty.call(generatedForms, f));" in modal
    assert "? openResolution({ ...it, forms:" in modal
    assert ": addFormBeforeGeneration(fid))} />" in modal


def test_the_forms_list_sits_under_key_details_with_open_links():
    rail = _src(RAIL)
    assert rail.index('<Panel title="Key details"') < rail.index('<Panel title="Your forms"') \
        < rail.index("<RemediationDiffBand diff={issueDiff} />")
    assert "packageGen?.onOpenForm?.(f.formId)" in rail
    modal = _src(MODAL)
    assert "onClick={() => openFormFromPackage(f.formId)}" in modal


def test_the_last_open_form_is_recorded_on_the_server():
    modal = _src(MODAL)
    assert "`${API_BASE}/api/session/${sessionId}/active-form`" in modal
    eff = modal[modal.index("lastRecordedFormRef.current === key"):]
    eff = eff[:eff.index("}, [step, sessionId, activeFormId]);")]
    assert 'if (step !== "editor"' in modal[modal.index("lastRecordedFormRef.current === key") - 400:]


@pytest.mark.parametrize("path", [PG, RAIL])
def test_no_em_dashes_in_the_new_copy(path):
    src = _src(path)
    for line in src.splitlines():
        if any(w in line for w in ("Continue where", "Generation didn", "Total Package Score", "being generated",
                                   "Forms are generated", "Your forms", "Needs your input")):
            assert not any(d in line for d in _EM_DASHES), line


# ══ 9. Fixes from the adversarial review (1 Oct night) ════════════════════════

def test_fixes_cannot_be_written_while_a_run_is_stamping_from_older_facts(monkeypatch):
    live = {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(fr, "get_job_queue", lambda: _Queue(live))
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ar._refuse_while_generating({"generation_job_id": "j1"}))
    assert ei.value.status_code == 409 and "being generated" in ei.value.detail
    # forms exist, nothing running, or a dead run: the fix goes through
    asyncio.run(ar._refuse_while_generating({"generated_forms": {"A": {}}, "generation_job_id": "j1"}))
    asyncio.run(ar._refuse_while_generating({}))
    monkeypatch.setattr(fr, "get_job_queue", lambda: _Queue({"status": "failed"}))
    asyncio.run(ar._refuse_while_generating({"generation_job_id": "j1"}))
    src = (BACKEND / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    for name in ("resolve_issue", "reopen_issue"):
        body = _fn_src(BACKEND / "routes" / "audit_routes.py", name)
        assert "await _refuse_while_generating(await _verify_session_owner(req.session_id, current_user))" in body


def test_a_run_that_made_no_forms_keeps_its_marker():
    body = _fn_src(BACKEND / "routes" / "form_routes.py", "select_forms_bulk")
    nf = body[body.index("if not results:"):body.index('raise HTTPException(400, "No forms could be generated")')]
    assert '"generation_job_id": None' not in nf


def test_the_heartbeat_beats_on_the_wall_clock(monkeypatch):
    # The loop's clock can stop (a sleeping Mac); the beat follows time.time().
    clock = {"t": 1000.0}
    monkeypatch.setattr(gs.time, "time", lambda: clock["t"])
    touched = []

    class Q:
        async def touch(self, job_id):
            touched.append(clock["t"])

    async def go():
        hb = await gs.GenerationHeartbeat(Q(), "j1", every=30).start()
        await asyncio.sleep(0)
        clock["t"] += 3600                      # an hour asleep
        await asyncio.sleep(5.2)                # one short nap later it beats
        await hb.stop()
    asyncio.run(go())
    assert touched and touched[0] == 4600.0


def test_the_screens_after_the_review():
    modal = _src(MODAL)
    # a failed / refused Generate asks the server before inviting a retry
    gen = modal[modal.index("const handleGenerateAll"):modal.index("const formIdList")]
    assert gen.count("await _settleAfterGenerate()") == 2
    assert "_pollJobStatus(queued.job_id, 1200)" in gen
    # the URL resume asks the server too
    assert "setPkgGen(p => ({ ...p, state: GEN_INTERRUPTED }));" not in modal
    # no dead "Fix in Data Consistency" / "Add form" while locked
    assert "!!dcKey && !formsGenerated && !lockedReason(pkgGen.state)" in modal
    assert "if (lockedReason(pkgGen.state)) return [];" in modal
    afb = modal[modal.index("const addFormBeforeGeneration"):modal.index("const itemResolveAndStatus")]
    assert "lockedReason(pkgGen.state)" in afb
    # locked items are not "needing your input"; no stale "so far" score
    assert "const openItemCount = lockedReason(pkgGen.state) ? 0 :" in modal
    assert "setPackageSqs(d.package_sqs || null);" in modal
    rail = _src(RAIL)
    assert "const docsOpen = preFormLocked ? 0 : docsNeedingReview.length;" in rail
    assert "canProceedWithWarning && warningStops.length > 0 && !afterForms" in rail
    assert ": genState === GEN_RUNNING ? GENERATION_RUNNING_TEXT" in rail
