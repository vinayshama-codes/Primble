"""Several users at once (MULTI_USER_READINESS_1NOV2026.md).

Live, 1 Nov 2026: three 271-page uploads killed the server ("Ran out of memory (used
over 2GB)"), and one user's scoring froze everyone else. Nothing caught it because
every other test runs one user at a time.
"""
import ast
import asyncio
import copy
import json
import pathlib
import random
import re
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── Two users' lookalike documents ───────────────────────────────────────────
def _lookalikes():
    head, tail = "H" * 60, "T" * 60
    return head + " LIMIT 111,111 ON 01/02/2026 " + tail, head + " LIMIT 222,222 ON 03/04/2027 " + tail


def test_lookalike_documents_are_never_read_as_each_other():
    """Same name, same length, same first and last 48 characters. Different documents."""
    from services import scoped_evidence as se
    a, b = _lookalikes()
    assert len(a) == len(b) and a[:48] == b[:48] and a[-48:] == b[-48:]
    da, db = se.Doc("dec.pdf", None, a), se.Doc("dec.pdf", None, b)
    assert se._cache_key(da) != se._cache_key(db)
    assert "111" in se._folded(da) and "222" not in se._folded(da)
    assert "222" in se._folded(db) and "111" not in se._folded(db)


def test_the_same_text_keeps_one_identity():
    from services import scoped_evidence as se
    a, _ = _lookalikes()
    assert se.text_fingerprint(a) == se.text_fingerprint("".join(list(a)))
    assert se.text_fingerprint(a) == se.text_fingerprint(a)
    assert len(se.text_fingerprint(a)) == 64


# ── Packages scored at the same moment ───────────────────────────────────────
def _normalised(res):
    pkg, kd, items = res
    text = json.dumps({"p": pkg, "k": kd, "i": items}, sort_keys=True, default=str)
    return re.sub(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d[.\d]*Z?", "T", text)


def _marked_packages(n):
    import reach100_harness as H
    rows = [H.wider_package(random.Random(500 + i)) for i in range(n)]
    for i, row in enumerate(rows):
        row["facts"]["applicant_name"] = {"value": f"ISOLATION MARKER {i} LLC", "source": "ai"}
    return rows


def test_packages_scored_together_match_scored_alone():
    """The cross-user guarantee: each result equals its own one-by-one result, and
    no other package's name appears in it."""
    import reach100_harness as H
    n = 4
    rows = _marked_packages(n)
    alone = [_normalised(H.read_page(copy.deepcopy(r))) for r in rows]
    for _round in range(2):
        out, errors = {}, []

        def work(i):
            try:
                out[i] = _normalised(H.read_page(copy.deepcopy(rows[i])))
            except Exception as ex:                            # noqa: BLE001
                errors.append(repr(ex))
        threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors, errors
        for i in range(n):
            assert out[i] == alone[i], f"package {i} changed when scored beside others"
            for j in range(n):
                assert j == i or f"ISOLATION MARKER {j} LLC" not in out[i]


def test_the_expiring_parts_memo_survives_threads():
    """Move-to-end and evict from several threads raised KeyError without the lock."""
    from services import cross_form_validator as cf
    errors = []

    def work(seed):
        try:
            for i in range(300):
                cf._expiring_policy_parts({"k": (seed * i) % 90}, False, False)
        except Exception as ex:                                # noqa: BLE001
            errors.append(repr(ex))
    threads = [threading.Thread(target=work, args=(s,)) for s in (1, 3, 7, 11)]
    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        [t.start() for t in threads]
        [t.join() for t in threads]
    finally:
        sys.setswitchinterval(switch)
    assert not errors, errors[:2]
    assert len(cf._EXPIRING_PARTS_MEMO) <= 64


def test_scoring_does_not_freeze_other_users():
    """A second request is served while a slow scoring call runs."""
    from utils.concurrency import run_scoring

    async def run():
        beats = []

        async def beat():
            while True:
                beats.append(time.monotonic())
                await asyncio.sleep(0.02)
        task = asyncio.create_task(beat())
        await asyncio.sleep(0)
        await run_scoring(time.sleep, 0.5)
        task.cancel()
        return beats
    beats = asyncio.run(run())
    assert len(beats) > 5
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.3


def test_a_stopiteration_in_scoring_fails_instead_of_hanging():
    """A future cannot carry StopIteration: the await hung for ever, under the lock."""
    from utils.concurrency import run_scoring

    def scorer():
        raise StopIteration

    async def run():
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(run_scoring(scorer), 2)
    asyncio.run(run())


def test_scoring_carries_the_requests_context():
    import contextvars
    from utils.concurrency import run_scoring
    var = contextvars.ContextVar("v", default="unset")

    async def run():
        var.set("this request")
        return await run_scoring(var.get)
    assert asyncio.run(run()) == "this request"


def test_no_route_scores_on_the_event_loop():
    """Anti-rot: an `async def` route calling a heavy scorer directly freezes everyone."""
    heavy = {"current_package_sqs", "complete_screen_shares", "calculate_package_sqs",
             "score_package_pre_generation", "calculate_sqs", "calculate_sqs_from_facts",
             "stops_now", "_stops_now", "merge_facts", "evaluate_stops", "run_cross_form_validation",
             "_restamp_canonical_into_forms", "_restamp_boxes_the_answer_decides",
             "_restamp_changed_boxes", "restamp_nonfillable_boxes", "_review_page_view",
             "_enforce_completeness_gate", "regenerate_pdf_for_form", "build_cover_page_pdf",
             "signature_question", "assess_underwriting_consistency", "log_breaches",
             "_partition_schedule_fields", "clean_text", "_restamp_schedule_into_forms",
             "_restamp_building_row", "_restamp_location_interest", "_restamp_late_forms",
             "_drop_not_applicable_questions", "_backfill_and_resolve_present",
             "apply_producer_policy_lines"}
    found = []
    # dev_routes: never mounted in production.
    for path in ([p for p in sorted((ROOT / "routes").glob("*.py")) if p.name != "dev_routes.py"]
                 + [ROOT / "services" / "arq_service.py", ROOT / "services" / "extraction_pipeline.py",
                    ROOT / "services" / "ocr_service.py", ROOT / "services" / "policy_lines.py",
                    ROOT / "services" / "issue_fix_undo.py", ROOT / "services" / "client_answer_review.py"]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            stack = list(ast.iter_child_nodes(fn))
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue            # a nested sync helper is judged where it is run
                stack.extend(ast.iter_child_nodes(node))
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in heavy:
                    found.append(f"{path.name}:{node.lineno} in {fn.name}")
    assert not found, found


def test_forms_stamped_together_match_stamped_alone():
    """Generation already runs in threads. Each form holds only its own package's values."""
    import reach100_harness as H
    from services.pdf_service import _deterministic_map, extract_form_schema
    import os
    from config.settings import TEMPLATE_DIR
    forms = ["ACORD_125", "ACORD_126"]
    schemas = {f: extract_form_schema(os.path.join(TEMPLATE_DIR, f"{f}.pdf")) for f in forms}
    rows = _marked_packages(4)

    def stamp(row, form):
        facts = dict(copy.deepcopy(row["facts"]), _form_id=form)
        return {name: str(_deterministic_map(name, facts) or "") for name in schemas[form]}
    jobs = [(i, f) for i in range(4) for f in forms]
    alone = {(i, f): stamp(rows[i], f) for i, f in jobs}
    assert any("ISOLATION MARKER 0" in v for v in alone[(0, "ACORD_125")].values())
    out, errors = {}, []

    def work(i, f):
        try:
            out[(i, f)] = stamp(rows[i], f)
        except Exception as ex:                                # noqa: BLE001
            errors.append(repr(ex))
    threads = [threading.Thread(target=work, args=job) for job in jobs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    for job in jobs:
        assert out[job] == alone[job], job
        text = " ".join(out[job].values())
        for j in range(4):
            assert j == job[0] or f"ISOLATION MARKER {j}" not in text


# ── One writer per package ───────────────────────────────────────────────────
def test_saves_on_one_package_run_one_at_a_time():
    from utils.concurrency import session_write_lock
    order = []

    async def save(name):
        async with session_write_lock("pkg-1"):
            order.append(f"{name} in")
            await asyncio.sleep(0.02)
            order.append(f"{name} out")

    async def run():
        await asyncio.gather(save("a"), save("b"))
    asyncio.run(run())
    assert [x.split()[1] for x in order] == ["in", "out", "in", "out"]


def test_different_packages_never_wait_on_each_other():
    from utils.concurrency import session_write_lock
    running = []

    async def save(pkg):
        async with session_write_lock(pkg):
            running.append(pkg)
            await asyncio.sleep(0.05)
            together.append(len(running))
            running.remove(pkg)

    async def run():
        await asyncio.gather(save("a"), save("b"))
    together = []
    asyncio.run(run())
    assert 2 in together, "two packages ran one after the other"


def test_a_route_holding_the_lock_can_call_a_recalculation_that_takes_it():
    from utils.concurrency import one_writer_per_package

    @one_writer_per_package
    async def recalc(session_id):
        return "done"

    class Req:
        session_id = "pkg-2"

    @one_writer_per_package
    async def route(req):
        return await recalc("pkg-2")

    assert asyncio.run(asyncio.wait_for(route(Req()), 2)) == "done"


def test_the_fix_window_and_the_policies_table_cannot_deadlock():
    """Reproduced in review: a fix-window save (package, then policy store) against a
    policies-table save (policy store, then package) hung for ever."""
    from routes import policy_line_routes as plr
    from services import policy_lines as pl
    from utils.concurrency import session_write_lock

    async def fix_window():
        async with session_write_lock("pkg-d"):
            await asyncio.sleep(0.02)
            async with pl.session_lock("pkg-d"):
                return "fix"

    async def policies_table():
        async with plr._lock_for("pkg-d"):
            await asyncio.sleep(0.02)
            async with session_write_lock("pkg-d"):     # the recalculation inside
                return "table"

    async def run():
        return await asyncio.wait_for(asyncio.gather(fix_window(), policies_table()), 3)
    assert sorted(asyncio.run(run())) == ["fix", "table"]


def test_a_documents_change_and_a_save_cannot_deadlock():
    from services import session_documents as sd
    from utils.concurrency import session_write_lock

    async def documents():
        async with sd._Serialized("pkg-e"):
            await asyncio.sleep(0.02)
            async with session_write_lock("pkg-e"):     # the re-score inside
                return "documents"

    async def save():
        async with session_write_lock("pkg-e"):
            await asyncio.sleep(0.02)
            async with sd._Serialized("pkg-e"):
                return "save"

    async def run():
        return await asyncio.wait_for(asyncio.gather(documents(), save()), 3)
    assert sorted(asyncio.run(run())) == ["documents", "save"]


@pytest.mark.parametrize("path,names", [
    ("services/arq_service.py", ["apply_arq_answers_to_session", "save_session_schedule",
                                 "apply_producer_answer_to_session", "recalculate_session_scores"]),
    ("routes/audit_routes.py", ["answer_recommendation", "reopen_recommendation", "dismiss_recommendation",
                                "resolve_issue", "reopen_issue"]),
    ("routes/form_routes.py", ["update_pdf", "client_answer_resolve", "mark_client_filled",
                               "underwriting_confirm_value", "underwriting_confirm_value_in_editor"]),
    ("routes/questionnaire_routes.py", ["answer_question", "approve_narrative"]),
    ("routes/arq_routes.py", ["save_session_schedule_route"]),
    ("routes/signature_routes.py", ["apply_signature"]),
    ("routes/session_documents_routes.py", ["add_offered_session_form"]),
])
def test_every_package_writer_takes_the_lock(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    for name in names:
        assert any(getattr(d, "id", "") == "one_writer_per_package" for d in fns[name].decorator_list), name


@pytest.mark.parametrize("call,kwargs,expected", [
    (("pkg",), {}, "pkg"),
    ((), {"session_id": "pkg"}, "pkg"),
    (("arq-id",), {"processing_session_id": "pkg"}, "pkg"),
    ((), {"req": type("R", (), {"session_id": "pkg"})()}, "pkg"),
])
def test_the_lock_finds_the_package_however_it_is_called(call, kwargs, expected):
    from utils import concurrency as cc
    seen = []

    @cc.one_writer_per_package
    async def route(*_a, **_k):
        seen.append(sorted(cc._HELD_SESSIONS.get()))
    asyncio.run(route(*call, **kwargs))
    assert seen == [[expected]]


def test_a_recalculation_writes_only_the_score_into_each_form():
    """Writing whole forms back blanked a box a save stamped while scoring ran (reproduced)."""
    import inspect
    from services import arq_service as arq
    src = inspect.getsource(arq.recalculate_session_scores)
    assert '"generated_forms": {fid: {"sqs": fdata.get("sqs")}' in src


def test_a_save_takes_no_upload_slot():
    src = (ROOT / "routes" / "form_routes.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_pdf")
    names = {getattr(c.func, "id", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not names & {"acquire_heavy_waiting", "try_acquire_heavy"}


def test_ai_slot_waiters_park_no_threads(monkeypatch):
    """With Redis down, a thread per waiter starved uploads and DNS for every user."""
    from utils import llm_limiter as lim
    sem = threading.Semaphore(1)
    monkeypatch.setattr(lim, "_thread_sem", sem)
    sem.acquire()

    async def run():
        waiters = [asyncio.create_task(lim._acquire_thread_sem(5)) for _ in range(64)]
        await asyncio.sleep(0.05)
        # The default pool still answers at once, whatever is waiting.
        await asyncio.wait_for(asyncio.to_thread(lambda: 1), 1)
        sem.release()
        done, pending = await asyncio.wait(waiters, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        return len(done)
    assert asyncio.run(run()) >= 1


def test_a_task_never_starts_under_the_lock():
    """A task started under the lock inherits it and would skip it after release."""
    for path in sorted((ROOT / "routes").glob("*.py")) + [ROOT / "services" / "arq_service.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            if not any(getattr(d, "id", "") == "one_writer_per_package" for d in fn.decorator_list):
                continue
            names = {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(fn)
                     if isinstance(c, ast.Call)}
            assert not names & {"create_task", "ensure_future"}, f"{path.name}:{fn.name}"


def test_the_lock_table_empties():
    from utils import concurrency as cc

    async def run():
        async with cc.session_write_lock("pkg-3"):
            pass
    asyncio.run(run())
    assert not cc._SESSION_LOCKS


# ── The slot limiters ────────────────────────────────────────────────────────
class _Sorted:
    """Redis' PEXPIREAT rule: a time in the past deletes the key."""
    def __init__(self):
        self.members = {}
        self.deleted = 0

    async def eval(self, _lua, _n, _key, now, expiry, maxn, token):
        self.members = {t: e for t, e in self.members.items() if e > now}
        if len(self.members) < maxn:
            self.members[token] = expiry
            if expiry + 1000 <= time.time() * 1000:
                self.members = {}
                self.deleted += 1
            return 1
        return 0

    async def zrem(self, _key, token):
        self.members.pop(token, None)


def test_the_upload_limit_really_holds(monkeypatch):
    """time.monotonic() as a Unix time is a date in 1970: PEXPIREAT deleted the key at
    once and the limit never held."""
    from utils import concurrency as cc
    fake = _Sorted()
    monkeypatch.setattr(cc, "_redis", fake)
    monkeypatch.setattr(cc, "_MAX_HEAVY", 2)

    async def run():
        return [await cc.try_acquire_heavy() for _ in range(3)]
    got = asyncio.run(run())
    assert fake.deleted == 0
    assert got[0] and got[1] and got[2] is False


def test_the_ai_limit_really_holds(monkeypatch):
    from utils import llm_limiter as lim
    fake = _Sorted()
    monkeypatch.setattr(lim, "_redis", fake)
    monkeypatch.setattr(lim, "_LLM_MAX_CONCURRENT", 2)

    async def run():
        return [await lim._redis_try_acquire() for _ in range(3)]
    got = asyncio.run(run())
    assert fake.deleted == 0
    assert got[0] and got[1] and got[2] is None


def test_a_long_upload_keeps_its_slot(monkeypatch):
    """A slot lapsing at 5 minutes let more uploads through than the limit."""
    from utils import concurrency as cc
    calls = []

    class Fake:
        async def eval(self, _lua, _n, _key, *argv):
            calls.append(argv)
            return 1

        async def zrem(self, _key, _token):
            return 1
    monkeypatch.setattr(cc, "_redis", Fake())
    monkeypatch.setattr(cc, "_RENEW_EVERY_S", 0.01)

    async def run():
        token = await cc.try_acquire_heavy()
        await asyncio.sleep(0.05)
        renewed = len(calls) - 1
        await cc.release_heavy(token)
        await asyncio.sleep(0.03)
        return token, renewed, len(calls) - 1
    token, renewed, after = asyncio.run(run())
    assert renewed >= 2
    assert after <= renewed + 1 and token not in cc._RENEWALS


def test_the_upload_limit_defaults_to_several_users():
    """Render sets no value, and 3 big uploads would queue the fourth user behind them."""
    src = (ROOT / "utils" / "concurrency.py").read_text(encoding="utf-8")
    assert 'os.getenv("MAX_CONCURRENT_HEAVY_OPS", "8")' in src


def test_startup_starts_the_watcher_the_sweep_and_the_memory_log():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup")
    names = {getattr(n, "id", getattr(n, "attr", "")) for n in ast.walk(fn)}
    assert {"watch_event_loop", "_remove_leftover_uploads", "log_startup_state"} <= names


def test_the_watcher_reports_a_blocked_loop(caplog):
    import logging
    from utils.concurrency import watch_event_loop

    async def run():
        task = asyncio.create_task(watch_event_loop(interval_s=0.01, warn_after_s=0.05))
        await asyncio.sleep(0.03)
        time.sleep(0.15)
        await asyncio.sleep(0.03)
        task.cancel()
    with caplog.at_level(logging.WARNING, logger="utils.concurrency"):
        asyncio.run(run())
    assert any("LOOP_BLOCKED" in r.getMessage() for r in caplog.records)


def test_a_busy_moment_waits_instead_of_refusing():
    from utils.concurrency import acquire_heavy_waiting
    calls = []

    async def acquire():
        calls.append(1)
        return "slot" if len(calls) >= 2 else False
    assert asyncio.run(acquire_heavy_waiting(acquire, max_wait_s=5)) == "slot"


def test_no_upload_route_refuses_on_the_first_full_moment():
    for name in ("form_routes.py", "session_documents_routes.py"):
        src = (ROOT / "routes" / name).read_text(encoding="utf-8")
        assert "await try_acquire_heavy()" not in src, name


def test_an_ai_slot_wait_outlasts_a_busy_moment():
    """Giving up after 90 s burned a retry and, on the third, shipped a batch blank."""
    from utils import llm_limiter as lim
    assert lim._ACQUIRE_TIMEOUT_S >= 600


# ── The memory safety net ────────────────────────────────────────────────────
def _cgroup(tmp_path, used, limit, inactive=0):
    (tmp_path / "memory.current").write_text(str(used))
    (tmp_path / "memory.max").write_text(str(limit))
    (tmp_path / "memory.stat").write_text(f"anon 1\ninactive_file {inactive}\n")
    return str(tmp_path)


def test_memory_state_reads_the_containers_limit(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1000, 2000, inactive=100))
    assert mg.memory_state() == (900, 2000)


@pytest.mark.parametrize("limit", ["max", "garbage"])
def test_an_unknown_limit_never_holds_anything(tmp_path, monkeypatch, limit):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1000, limit))
    assert mg.memory_state() is None and mg.memory_is_tight() is False


def test_page_cache_is_not_counted_as_short_memory(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1900, 2000, inactive=1500))
    assert mg.memory_is_tight() is False


def test_a_small_file_never_waits(tmp_path, monkeypatch, caplog):
    import logging
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1990, 2000))
    pdf = tmp_path / "small.pdf"
    pdf.write_bytes(b"x" * 1000)
    with caplog.at_level(logging.INFO, logger="utils.memory_guard"):
        asyncio.run(mg.wait_for_room([str(pdf)]))
    assert not any("MEMORY_GUARD_HOLD" in r.getMessage() for r in caplog.records)


def test_a_big_file_waits_for_room_then_goes(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1990, 2000))
    monkeypatch.setattr(mg, "_POLL_S", 0.01)
    monkeypatch.setattr(mg, "_START_GAP_S", 0.0)
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * (3 * 1024 * 1024))

    async def run():
        task = asyncio.create_task(mg.wait_for_room([str(pdf)]))
        await asyncio.sleep(0.05)
        assert not task.done()
        (tmp_path / "memory.current").write_text("100")
        await asyncio.wait_for(task, 1)
    asyncio.run(run())


def test_a_big_file_is_never_stuck_for_ever(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1990, 2000))
    monkeypatch.setattr(mg, "_POLL_S", 0.01)
    monkeypatch.setattr(mg, "_MAX_WAIT_S", 0.03)
    monkeypatch.setattr(mg, "_START_GAP_S", 0.0)
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * (3 * 1024 * 1024))
    asyncio.run(asyncio.wait_for(mg.wait_for_room([str(pdf)]), 1))


def test_waiting_files_are_let_go_one_at_a_time(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_CGROUP", _cgroup(tmp_path, 1990, 2000))
    monkeypatch.setattr(mg, "_POLL_S", 0.01)
    monkeypatch.setattr(mg, "_START_GAP_S", 0.05)
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * (3 * 1024 * 1024))

    async def run():
        tasks = [asyncio.create_task(mg.wait_for_room([str(pdf)])) for _ in range(2)]
        await asyncio.sleep(0.03)
        (tmp_path / "memory.current").write_text("100")
        await asyncio.sleep(0.03)
        # Memory is free, but the second keeps its turn until the first has started.
        return sum(t.done() for t in tasks), await asyncio.gather(*tasks)
    # both tasks read "tight" on arrival; only then does the gate order them
    done_early, _ = asyncio.run(run())
    assert done_early <= 1


def test_a_page_heavy_small_file_counts_as_big(tmp_path, monkeypatch):
    from utils import memory_guard as mg
    monkeypatch.setattr(mg, "_BIG_FILE_PAGES", 5)
    assert mg._is_big(_pdf(tmp_path, 6)) is True
    monkeypatch.setattr(mg, "_BIG_FILE_PAGES", 50)
    assert mg._is_big(_pdf(tmp_path, 6)) is False


def test_the_big_file_waits_before_taking_a_slot():
    """A waiting file holding a slot would make small files wait too."""
    for name, slot in (("form_routes.py", "_sem_token = await acquire_heavy_waiting"),
                       ("session_documents_routes.py", "sem_token = await acquire_heavy_waiting")):
        src = (ROOT / "routes" / name).read_text(encoding="utf-8")
        assert src.index("await wait_for_room(all_paths)") < src.index(slot), name


def test_the_guard_shows_no_queue_wording():
    src = (ROOT / "utils" / "memory_guard.py").read_text(encoding="utf-8")
    assert "reporter" not in src and "you're next" not in src.lower()


# ── Every PDF pass frees its pages ───────────────────────────────────────────
class _FreedPages:
    """Fails if a page is read while an earlier page still holds its parsed objects:
    that pile-up is what took 1,292 MB on a 271-page policy."""

    def __init__(self, monkeypatch):
        from pdfplumber.page import Page
        self.seen = []
        self.held = []
        for name in ("extract_text", "extract_words"):
            original = getattr(Page, name)

            def wrapped(page, *a, _original=original, **k):
                if not any(p is page for p in self.seen):
                    self.held += [p.page_number for p in self.seen if "_objects" in p.__dict__]
                    self.seen.append(page)
                return _original(page, *a, **k)
            monkeypatch.setattr(Page, name, wrapped)


def test_the_text_reader_frees_each_page(tmp_path, monkeypatch):
    from services import ocr_service as ocr
    path = _pdf(tmp_path, 6)
    spy = _FreedPages(monkeypatch)
    assert len(ocr._pdfplumber_extract_pages_structured(path)) == 6
    assert len(spy.seen) == 6 and not spy.held


def test_the_page_recogniser_frees_each_page(tmp_path, monkeypatch):
    from services.acord_intake import recognize
    path = _pdf(tmp_path, 6)
    spy = _FreedPages(monkeypatch)
    assert len(recognize.recognize(path)) == 6
    assert len(spy.seen) == 6 and not spy.held


def test_the_transcriber_page_check_frees_each_page(tmp_path, monkeypatch):
    from services.acord_intake import transcriber_intake as ti
    path = _pdf(tmp_path, 6)
    spy = _FreedPages(monkeypatch)
    assert len(ti._page_texts(path, list(range(6)), "")) == 6
    assert len(spy.seen) == 6 and not spy.held


def test_the_overlay_and_field_readers_free_their_pages():
    """Source pins: these two need a real filled form to reach the line."""
    assert "_prev_page.close()" in (ROOT / "services/acord_intake/overlay.py").read_text(encoding="utf-8")
    assert "pdf.pages[idx].close()" in (ROOT / "utils/form_field_text.py").read_text(encoding="utf-8")


def _pdf(tmp_path, pages):
    from reportlab.pdfgen import canvas
    p = tmp_path / "doc.pdf"
    c = canvas.Canvas(str(p))
    for i in range(pages):
        for line in range(30):
            c.drawString(50, 780 - line * 20, f"Page {i} line {line} Policy Number ABC{i}{line} limit $1,000,000")
        c.showPage()
    c.save()
    return str(p)


def test_clearing_pages_changes_no_text(tmp_path, monkeypatch):
    from services import ocr_service as ocr
    path = _pdf(tmp_path, 8)
    cleared = ocr._pdfplumber_extract_pages_structured(path)
    monkeypatch.setattr(ocr, "_close_page", lambda _p: None)
    kept = ocr._pdfplumber_extract_pages_structured(path)
    assert cleared == kept and len(cleared) == 8 and "Page 7" in cleared[7][0]


def test_a_cleared_page_can_still_be_read():
    """close() frees a parse, it does not break the page: the fallback paths may re-read."""
    import pdfplumber
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = _pdf(pathlib.Path(d), 1)
        with pdfplumber.open(path) as pdf:
            first = pdf.pages[0].extract_text()
            pdf.pages[0].close()
            assert pdf.pages[0].extract_text() == first


# ── Interrupted uploads ──────────────────────────────────────────────────────
def test_leftover_uploads_are_removed_and_fresh_ones_kept(tmp_path, monkeypatch):
    import os
    import main
    from config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.delenv("ENABLE_ASYNC_PROCESSING", raising=False)
    old, fresh = tmp_path / "old.pdf", tmp_path / "fresh.pdf"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    main._remove_leftover_uploads()
    assert not old.exists() and fresh.exists()


def test_async_mode_keeps_its_queued_files(tmp_path, monkeypatch):
    import os
    import main
    from config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_ASYNC_PROCESSING", "true")
    old = tmp_path / "queued.pdf"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    main._remove_leftover_uploads()
    assert old.exists()


def test_the_interrupted_upload_message_is_plain():
    root = ROOT.parent / "frontend" / "src" / "components" / "form"
    for name, flag in (("AcordModal.jsx", "!uploadReachedServer"), ("review/AddDocumentsPanel.jsx", "!reached")):
        src = (root / name).read_text(encoding="utf-8")
        assert "The upload was interrupted. Please upload it again" in src
        # Only when the request itself failed: after a good upload, "upload it again"
        # would make a duplicate package.
        assert flag in src, name
