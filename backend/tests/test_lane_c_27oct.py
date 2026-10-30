"""Lane C, 27 Oct 2026 - Brent's V2 list: E&O fact lineage, ARQ Bot (Form
Assistant) usage tracking, package archival / retention.

Everything here drives the REAL doors - `session_repository.new_processing_session`
/ `upd_processing_session`, the real routes through FastAPI's TestClient, the
real middleware - against an in-memory store that answers the SQL those doors
send. No network, no database, nothing written to a real package.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

import config.database as cdb                                  # noqa: E402
import repositories.session_repository as sr                   # noqa: E402
from services import fact_history as fh                        # noqa: E402
from services import package_archive as pa                     # noqa: E402
from services import arq_assistant_usage as au                 # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"


# ══ An in-memory store that answers the doors' SQL ═══════════════════════════

class _Store:
    def __init__(self):
        self.rows = {}          # sid -> {"data": dict, "version": int, "user_id", "updated_at"}
        self.lineage = []       # INSERT tuples, in _COLUMNS order
        self.updates = 0
        self.sql = []
        self.usage = []

    def lineage_dicts(self, sid=None):
        cols = [c.strip() for c in fh._COLUMNS.split(",")]
        out = [dict(zip(cols, r)) for r in self.lineage]
        out = [r | {"values_purged": False} for r in out]
        return [r for r in out if sid is None or r["session_id"] == sid]


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, store: _Store):
        self.store = store

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        self.store.sql.append(s)
        if "FROM processing_sessions" in s and "FOR UPDATE" in s:
            row = self.store.rows.get(args[0])
            if not row:
                return None
            return {"data": json.dumps(row["data"]), "version": row["version"]}
        if "data->>'archived_at' AS archived_at" in s:
            row = self.store.rows.get(args[0])
            return {"archived_at": (row["data"].get("archived_at") if row else None)} if row else None
        return None

    async def fetch(self, sql, *args):
        s = " ".join(sql.split())
        self.store.sql.append(s)
        if f"FROM {fh.TABLE}" in s:
            rows = self.store.lineage_dicts(args[0])
            if "AND fact_key=$2" in s:
                rows = [r for r in rows if r["fact_key"] == args[1]]
            rows.sort(key=lambda r: (r["created_at"], r["ordinal"]))
            return rows
        return []

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        self.store.sql.append(s)
        if s.startswith("INSERT INTO processing_sessions"):
            sid, uid, data, created, updated = args
            self.store.rows[sid] = {"data": data, "version": 1, "user_id": uid,
                                    "updated_at": updated}
        elif s.startswith("UPDATE processing_sessions SET data=$1"):
            data, now, version, sid = args
            self.store.rows[sid].update(data=data, version=version, updated_at=now)
            self.store.updates += 1
        return "UPDATE 1"

    async def executemany(self, sql, rows):
        assert sql.startswith(f"INSERT INTO {fh.TABLE}")
        self.store.lineage.extend(rows)


class _Pool:
    def __init__(self, store):
        self.conn = _Conn(store)

    def acquire(self):
        conn = self.conn

        class _A:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _A()


@contextmanager
def _db(store: _Store):
    pool = _Pool(store)
    with patch.object(sr, "get_pool", lambda: pool), \
         patch.object(cdb, "get_pool", lambda: pool):
        yield pool


@contextmanager
def _request(method="POST", path="/api/audit/resolve-issue", user_id="u-owner",
             client_id=None):
    """Code running as one HTTP request (what RequestContextMiddleware sets)."""
    ctx = {"scope": {"type": "http", "method": method, "path": path,
                     "route": SimpleNamespace(path=path)}}
    if user_id:
        ctx["user_id"] = user_id
    if client_id:
        ctx["client_id"] = client_id
    token = fh._REQUEST.set(ctx)
    try:
        yield ctx
    finally:
        fh._REQUEST.reset(token)


def _run(coro):
    return asyncio.run(coro)


def _env(value, source="ai", confidence="ai_high", **extra):
    return {"value": value, "source": source, "confidence": confidence, **extra}


def _new_package(store, facts, docs=None, user_id="u-owner"):
    with _db(store):
        return _run(sr.new_processing_session({"user_id": user_id, "facts": facts,
                                               "docs": docs or []}))


def _update(store, sid, updates, delete_facts=None):
    with _db(store), patch.object(sr, "_save_pdf_bytes", _noop):
        _run(sr.upd_processing_session(sid, updates, delete_facts=delete_facts))


async def _noop(*a, **k):
    return None


# ══ 1. E&O FACT LINEAGE ═══════════════════════════════════════════════════════

class TestDiff:
    def test_empty_both_sides_is_no_change(self):
        assert fh.diff_facts({}, {}) == []
        assert fh.diff_facts(None, None) == []
        assert fh.diff_facts({}, None) == []

    def test_first_values_are_set(self):
        ch = fh.diff_facts({}, {"applicant_name": _env("Acme LLC"), "fein": _env("12-3456789")})
        assert [(c["fact_key"], c["change_type"]) for c in ch] == [
            ("applicant_name", "set"), ("fein", "set")]

    def test_a_write_with_no_change_is_no_row(self):
        facts = {"applicant_name": _env("Acme LLC")}
        assert fh.diff_facts(facts, json.loads(json.dumps(facts))) == []

    def test_an_annotation_is_not_a_change(self):
        before = {"x": _env("1000000")}
        after = {"x": _env("1000000", verified_in_text=True, value_state="present")}
        assert fh.diff_facts(before, after) == []

    def test_changed_removed_confirmed_source(self):
        before = {"a": _env("1"), "b": _env("2"), "c": _env("3"), "d": _env("4")}
        after = {"a": _env("9", source="producer", confidence="filled"),
                 "c": _env("3", source="user_confirmed"),
                 "d": _env("4", source="dec_entry", confidence="deterministic")}
        got = {c["fact_key"]: c["change_type"] for c in fh.diff_facts(before, after)}
        assert got == {"a": "changed", "b": "removed", "c": "source_changed", "d": "source_changed"}

    def test_a_persons_confirmation_of_the_same_value(self):
        before = {"x": _env("Acme")}
        after = {"x": _env("Acme", evidence_state="user_confirmed")}
        assert [c["change_type"] for c in fh.diff_facts(before, after)] == ["confirmed"]

    def test_blank_values_count_as_empty(self):
        for blank in (None, "", "   ", [], {}):
            assert fh.diff_facts({"x": blank}, {}) == []
            assert fh.diff_facts({}, {"x": _env(blank)}) == []

    def test_machinery_is_not_a_fact(self):
        after = {"_scoped": {"a": 1}, "_uw_conflicted_keys": ["x"], "dec_page_entries": [{"l": 1}],
                 "renewal_dates_routed": True}
        assert fh.diff_facts({}, after) == []

    def test_the_policies_table_sidecar_is_tracked(self):
        from services.policy_lines import STORE_KEY
        assert STORE_KEY in fh.PERSON_SIDECARS
        ch = fh.diff_facts({}, {STORE_KEY: {"edits": {"l1": {"carrier": "Chubb"}}}})
        assert [c["fact_key"] for c in ch] == [STORE_KEY]

    def test_an_unknown_fact_key_is_still_recorded(self):
        ch = fh.diff_facts({}, {"some_fact_nobody_declared": "value"})
        assert ch and ch[0]["change_type"] == "set"

    def test_a_retention_tombstone_is_no_facts(self):
        tomb = {"purged": True, "purged_at": "x", "reason": "retention_policy"}
        assert fh.diff_facts(tomb, {"a": _env("1")})[0]["change_type"] == "set"
        assert fh.diff_facts({"a": _env("1")}, tomb)[0]["change_type"] == "removed"

    def test_schedules_compare_by_value(self):
        rows = [{"vin": "1HGCM82633A004352", "year": "2020"}]
        assert fh.diff_facts({"auto_vin_schedule": rows},
                             {"auto_vin_schedule": [dict(rows[0])]}) == []
        ch = fh.diff_facts({"auto_vin_schedule": rows},
                           {"auto_vin_schedule": rows + [{"vin": "2T1BURHE0JC000001"}]})
        assert ch[0]["change_type"] == "changed"


class TestKind:
    def test_envelope_sources(self):
        sys = {"actor_type": "system", "action": "system"}
        assert fh.kind_of(_env("x"), sys) == "ai"
        assert fh.kind_of(_env("x", source="dec_entry", confidence="deterministic"), sys) == "document"
        assert fh.kind_of(_env("x", source="derived"), sys) == "derived"
        assert fh.kind_of(_env("x", source="producer", confidence="filled"), sys) == "producer"
        assert fh.kind_of(_env("x", source="client_arq", confidence="client_arq"), sys) == "client"
        assert fh.kind_of(_env("x", source="user_confirmed"), sys) == "confirmed"

    def test_a_confirmed_document_value_is_confirmed_a_typed_one_stays_typed(self):
        sys = {"actor_type": "system"}
        assert fh.kind_of(_env("x", evidence_state="user_confirmed"), sys) == "confirmed"
        assert fh.kind_of(_env("x", source="client_arq", evidence_state="user_confirmed"), sys) == "client"

    def test_a_bare_value_takes_its_writer(self):
        assert fh.kind_of(["row"], {"actor_type": "producer", "action": "PUT /api/arq/schedules/{session_id}"}) == "producer"
        assert fh.kind_of(["row"], {"actor_type": "client", "action": "POST /api/arq/submit/{token}"}) == "client"
        assert fh.kind_of(["row"], {"actor_type": "producer", "action": "POST /api/upload-declaration"}) == "document"
        assert fh.kind_of(["row"], {"actor_type": "system", "action": "system"}) == "derived"

    def test_every_kind_has_words(self):
        assert set(fh.KIND_LABELS) == set(fh.KINDS)


class TestTheWriteDoors:
    def test_the_first_extraction_records_every_fact_with_its_page(self):
        store = _Store()
        docs = [{"doc_id": "d1", "filename": "Dec page.pdf",
                 "text": "[Document page 1]\nNAMED INSURED: Acme Roofing LLC\n"
                         "[Document page 2]\nFEIN 12-3456789",
                 "facts": {"applicant_name": _env("Acme Roofing LLC"), "fein": _env("12-3456789")}}]
        with _request(method="POST", path="/api/upload-declaration"):
            sid = _new_package(store, {"applicant_name": _env("Acme Roofing LLC"),
                                       "fein": _env("12-3456789")}, docs=docs)
        rows = store.lineage_dicts(sid)
        assert {r["fact_key"] for r in rows} == {"applicant_name", "fein"}
        by = {r["fact_key"]: r for r in rows}
        assert by["applicant_name"]["kind"] == "ai"
        assert by["applicant_name"]["confidence"] == "ai_high"
        assert by["applicant_name"]["actor_type"] == "producer"
        assert by["applicant_name"]["action"] == "POST /api/upload-declaration"
        src, _ok = fh.open_value(by["fein"]["sources"])
        assert src and src[0]["filename"] == "Dec page.pdf" and src[0]["page"] == 2

    def test_values_are_encrypted_at_rest(self):
        store = _Store()
        sid = _new_package(store, {"fein": _env("98-7654321")})
        _update(store, sid, {"facts": {"fein": _env("11-2223333", source="producer",
                                                    confidence="filled")}})
        for row in store.lineage:
            blob = json.dumps([v for v in row if isinstance(v, str)])
            assert "98-7654321" not in blob and "11-2223333" not in blob
        r = store.lineage_dicts(sid)[-1]
        assert r["from_value"].startswith("enc:") and r["to_value"].startswith("enc:")
        assert fh.open_value(r["from_value"]) == ("98-7654321", True)
        assert fh.open_value(r["to_value"]) == ("11-2223333", True)

    def test_a_write_that_changes_nothing_writes_no_row(self):
        store = _Store()
        sid = _new_package(store, {"applicant_name": _env("Acme")})
        n = len(store.lineage)
        _update(store, sid, {"facts": {"applicant_name": _env("Acme")}})
        _update(store, sid, {"hard_stops": ["x"]})                 # no facts at all
        _update(store, sid, {"facts": {"applicant_name": ""}})     # a blank never overwrites
        assert len(store.lineage) == n
        assert store.updates == 3

    def test_many_writes_make_one_ordered_chain(self):
        store = _Store()
        sid = _new_package(store, {"gl_each_occurrence": _env("$1,000,000")})
        values = ["$2,000,000", "$3,000,000", "$1,000,000", "$5,000,000"]
        for i, v in enumerate(values):
            with _request(user_id=f"u{i}"):
                _update(store, sid, {"facts": {"gl_each_occurrence": _env(
                    v, source="producer", confidence="filled")}})
        rows = [fh.decode_row(r) for r in store.lineage_dicts(sid)]
        assert [r["to"] for r in rows] == ["$1,000,000"] + values
        assert [r["from"] for r in rows] == [None, "$1,000,000"] + values[:-1]
        assert [r["actor_id"] for r in rows[1:]] == ["u0", "u1", "u2", "u3"]

    def test_a_retraction_is_a_removed_row(self):
        store = _Store()
        sid = _new_package(store, {"auto_drivers": [{"name": "Erin Royal"}],
                                   "applicant_name": _env("Acme")})
        with _request(path="/api/document/reclassify"):
            _update(store, sid, {}, delete_facts=["auto_drivers"])
        last = fh.decode_row(store.lineage_dicts(sid)[-1])
        assert last["fact_key"] == "auto_drivers" and last["change_type"] == "removed"
        assert last["from"] == [{"name": "Erin Royal"}] and last["to"] is None

    def test_the_client_and_the_system_are_named(self):
        store = _Store()
        sid = _new_package(store, {})
        with _request(method="POST", path="/api/arq/submit/{token}", user_id=None,
                      client_id="arq-7"):
            _update(store, sid, {"facts": {"num_employees": _env("12", source="client_arq",
                                                                 confidence="client_arq")}})
        _update(store, sid, {"facts": {"wc_payroll": _env("$90,000", source="derived")}})
        rows = {r["fact_key"]: fh.decode_row(r) for r in store.lineage_dicts(sid)}
        assert rows["num_employees"]["actor_type"] == "client"
        assert rows["num_employees"]["actor_id"] == "arq-7"
        assert rows["num_employees"]["kind"] == "client"
        assert rows["num_employees"]["action_label"] == "Client questionnaire submitted"
        assert rows["wc_payroll"]["actor_type"] == "system"
        assert rows["wc_payroll"]["kind"] == "derived"

    def test_a_lineage_failure_never_fails_the_write(self):
        store = _Store()
        sid = _new_package(store, {})

        async def _boom(*a, **k):
            raise RuntimeError("relation fact_lineage does not exist")
        with patch.object(_Conn, "executemany", _boom):
            _update(store, sid, {"facts": {"applicant_name": _env("Acme")}})
        data = sr._decrypt_facts(dict(store.rows[sid]["data"]))
        assert data["facts"]["applicant_name"]["value"] == "Acme"

    def test_an_unreadable_facts_blob_writes_no_lineage(self):
        store = _Store()
        store.rows["sid-x"] = {"data": {"facts": "enc:not-a-real-token", "user_id": "u"},
                               "version": 1, "user_id": "u"}
        _update(store, "sid-x", {"facts": {"applicant_name": _env("Acme")}})
        assert store.lineage == []

    def test_a_huge_schedule_is_stored_as_a_digest(self):
        store = _Store()
        rows = [{"vin": f"VIN{i:014d}", "desc": "x" * 300} for i in range(200)]
        sid = _new_package(store, {"auto_vin_schedule": rows})
        val, ok = fh.open_value(store.lineage_dicts(sid)[0]["to_value"])
        assert ok and val["_truncated"] and val["rows"] == 200 and len(val["sha256"]) == 64
        assert fh.display_value(val) == "[200 row(s)]"


class TestRequestContext:
    def test_the_middleware_and_auth_note_who_is_writing(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        store = _Store()
        sid = _new_package(store, {})

        def _user():
            fh.note_user({"id": "u-42", "email": "p@example.com"})
            return {"id": "u-42"}

        app = FastAPI()

        @app.post("/t/{session_id}")
        async def _write(session_id: str, _u=Depends(_user)):
            await sr.upd_processing_session(session_id, {"facts": {
                "contact_name": _env("Pat Doe", source="producer", confidence="filled")}})
            return {"ok": True}

        app.add_middleware(fh.RequestContextMiddleware)
        with _db(store), patch.object(sr, "_save_pdf_bytes", _noop):
            assert TestClient(app).post(f"/t/{sid}").status_code == 200
        row = fh.decode_row(store.lineage_dicts(sid)[-1])
        assert (row["actor_type"], row["actor_id"], row["action"]) == (
            "producer", "u-42", "POST /t/{session_id}")
        assert row["kind"] == "producer"

    def test_outside_a_request_it_is_the_system(self):
        assert fh.current_actor() == {"actor_type": "system", "actor_id": None, "action": "system"}

    def test_acting_overrides(self):
        with fh.acting(action="worker: generation", actor_type="system"):
            assert fh.current_actor()["action"] == "worker: generation"
        assert fh.current_actor()["action"] == "system"

    def test_the_auth_dependency_notes_the_user(self):
        src = (BACKEND / "services" / "auth_service.py").read_text()
        body = src[src.index("async def get_current_user"):src.index("def _note_request_user")]
        assert body.count("_note_request_user(") == 2      # the cache hit and the DB read


# ── The anti-rot test: no facts write bypasses the two doors ─────────────────
# Every SQL statement in the backend that writes processing_sessions, with the
# function it lives in. A new one fails here until it is placed: a facts write
# must go through session_repository's doors (which record lineage); anything
# else must say why it is not a facts write.
_ALLOWED_SESSION_WRITERS = {
    ("repositories/session_repository.py", "new_processing_session"): "door - records lineage",
    ("repositories/session_repository.py", "upd_processing_session"): "door - records lineage",
    ("repositories/session_repository.py", "set_active_form"): "active_form_id only",
    ("repositories/session_repository.py", "_backfill_search_names"): "search_name copy only",
    ("routes/audit_routes.py", "_apply_dismiss_score_credit"): "score paths only",
    ("services/scheduler_service.py", "run_facts_retention"): "retention tombstone; lineage values purged with it",
    ("services/scheduler_service.py", "run_retention_cleanup"): "deletes whole packages (lineage with them)",
    ("services/package_archive.py", "archive_package"): "archive keys only",
    ("services/package_archive.py", "unarchive_package"): "archive keys only",
    ("services/package_archive.py", "<module>"): "AUTO_ARCHIVE_SQL - archive keys only",
    ("routes/form_routes.py", "delete_session"): "deletes the package (lineage with it)",
    ("routes/auth_routes.py", "delete_account"): "deletes the account (lineage with it)",
}
_SKIP_DIRS = ("tests", "scripts", "alembic", ".venv", "__pycache__")
_SKIP_FILES = {"migrate.py", "create_tables.py"}
_WRITE_RE = re.compile(r"\b(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+processing_sessions\b", re.I)


def _session_writers():
    found = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.split("/")[0] in _SKIP_DIRS or path.name in _SKIP_FILES:
            continue
        src = path.read_text()
        if "processing_sessions" not in src:
            continue
        tree = ast.parse(src)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and _WRITE_RE.search(" ".join(node.value.split())):
                fn, cur = "<module>", node
                while cur in parents:
                    cur = parents[cur]
                    if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn = cur.name
                        break
                found.add((rel, fn))
    return found


def test_no_facts_write_bypasses_the_lineage_doors():
    found = _session_writers()
    unlisted = sorted(found - set(_ALLOWED_SESSION_WRITERS))
    assert not unlisted, (
        "SQL writing processing_sessions outside the lineage doors - route the "
        f"facts write through session_repository, or list it with its reason: {unlisted}")
    assert ("repositories/session_repository.py", "upd_processing_session") in found


def test_both_doors_call_the_lineage_recorder():
    src = (BACKEND / "repositories" / "session_repository.py").read_text()
    tree = ast.parse(src)
    fns = {n.name: ast.get_source_segment(src, n) for n in ast.walk(tree)
           if isinstance(n, ast.AsyncFunctionDef)}
    for name in ("new_processing_session", "upd_processing_session"):
        assert "record_fact_changes(" in fns[name], name


def test_the_only_lineage_update_is_the_retention_purge():
    hits = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.split("/")[0] in _SKIP_DIRS:
            continue
        for m in re.finditer(r"UPDATE\s+(?:\{TABLE\}|fact_lineage\b)", path.read_text()):
            hits.append(rel)
    assert hits == ["services/fact_history.py"]
    assert "from_value = NULL" in fh.PURGE_VALUES_SQL and "values_purged = TRUE" in fh.PURGE_VALUES_SQL


# ── The history endpoint ──────────────────────────────────────────────────────

def _history_client(store, user_id="u-owner"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import package_history_routes as phr
    from services.auth_service import get_current_user
    app = FastAPI()
    app.include_router(phr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "email": "p@x.com",
                                                          "payment_status": "ok"}

    async def _get(sid, include_pdf=False):
        row = store.rows.get(sid)
        if not row:
            from fastapi import HTTPException
            raise HTTPException(404, "not found")
        return sr._decrypt_facts(dict(row["data"]))
    return app, TestClient(app), _get


def _resolve_none(ids):
    async def _r(_ids):
        return {i: {"id": i, "name": "Pat Producer", "email": "pat@x.com"} for i in _ids}
    return _r


class TestHistoryRoute:
    def test_the_owner_reads_one_facts_history(self):
        store = _Store()
        sid = _new_package(store, {"fein": _env("98-7654321"), "applicant_name": _env("Acme")})
        with _request(user_id="u-owner"):
            _update(store, sid, {"facts": {"fein": _env("11-2223333", source="producer",
                                                        confidence="filled")}})
        app, client, _get = _history_client(store)
        from routes import package_history_routes as phr
        import services.audit_service as aud
        with _db(store), patch.object(phr, "get_processing_session", _get), \
             patch.object(aud, "resolve_actors", _resolve_none(None)):
            res = client.get(f"/api/fact-history/{sid}", params={"fact_key": "fein"})
        assert res.status_code == 200
        body = res.json()
        assert [h["to"] for h in body["history"]] == ["98-7654321", "11-2223333"]
        assert body["history"][1]["who"] == "Producer (Pat Producer)"
        assert body["history"][1]["kind_label"] == "Entered by the producer"

    def test_another_users_package_is_refused(self):
        store = _Store()
        sid = _new_package(store, {"fein": _env("98-7654321")}, user_id="u-owner")
        app, client, _get = _history_client(store, user_id="u-stranger")
        from routes import package_history_routes as phr
        with _db(store), patch.object(phr, "get_processing_session", _get):
            assert client.get(f"/api/fact-history/{sid}").status_code == 403

    def test_an_unknown_fact_is_an_empty_history_and_a_bad_key_a_400(self):
        store = _Store()
        sid = _new_package(store, {"fein": _env("98-7654321")})
        app, client, _get = _history_client(store)
        from routes import package_history_routes as phr
        with _db(store), patch.object(phr, "get_processing_session", _get):
            res = client.get(f"/api/fact-history/{sid}", params={"fact_key": "never_set"})
            assert res.status_code == 200 and res.json()["history"] == []
            assert client.get(f"/api/fact-history/{sid}",
                              params={"fact_key": "x'; DROP TABLE"}).status_code == 400
            assert client.get("/api/fact-history/no-such-package").status_code == 404

    def test_the_whole_package_history(self):
        store = _Store()
        sid = _new_package(store, {"a": _env("1"), "b": _env("2")})
        app, client, _get = _history_client(store)
        from routes import package_history_routes as phr
        with _db(store), patch.object(phr, "get_processing_session", _get):
            body = client.get(f"/api/fact-history/{sid}").json()
        assert body["count"] == 2 and {h["fact_key"] for h in body["history"]} == {"a", "b"}


def test_the_eo_record_carries_the_fact_history():
    import services.audit_service as aud
    store = _Store()
    sid = _new_package(store, {"fein": _env("98-7654321")})
    with _request(user_id="u-owner"):
        _update(store, sid, {"facts": {"fein": _env("11-2223333", source="producer",
                                                    confidence="filled")}})

    async def _empty(*a, **k):
        return []

    async def _none(*a, **k):
        return None

    async def _get(s, include_pdf=False):
        return sr._decrypt_facts(dict(store.rows[s]["data"]))

    stubs = {n: _empty for n in ("get_dismissed_recommendations", "get_producer_answers",
                                 "get_issue_statuses", "get_download_audit_log",
                                 "get_field_change_log", "get_underwriting_confirmations",
                                 "get_package_download_log", "get_audit_events",
                                 "get_integrity_audit_log")}
    with _db(store), patch.object(aud, "get_marketing_reason", _none), \
         patch.object(aud, "resolve_actors", _resolve_none(None)), \
         patch.object(sr, "get_processing_session", _get), \
         patch.multiple(aud, **stubs):
        export = _run(aud.get_audit_trail_export(sid))
    hist = export["fact_lineage"]
    assert [(h["fact"], h["from"], h["to"]) for h in hist] == [
        ("fein", "", "98-7654321"), ("fein", "98-7654321", "11-2223333")]
    assert hist[1]["who"] == "Producer (Pat Producer)" and hist[1]["how"] == "Entered by the producer"


def test_the_eo_download_prints_the_fact_history():
    src = (FRONT / "components" / "form" / "AcordModal.jsx").read_text()
    assert "d.fact_lineage" in src and "FACT HISTORY" in src


def test_the_schema_is_in_init_db_and_additive():
    src = (BACKEND / "config" / "database.py").read_text()
    body = src[src.index("async def init_db"):]
    for table in ("fact_lineage", "arq_assistant_usage"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in body
    for line in body.splitlines():
        u = line.upper()
        assert "DROP TABLE" not in u and "TRUNCATE" not in u
        if "FACT_LINEAGE" in u or "ARQ_ASSISTANT_USAGE" in u:
            assert "DROP" not in u and "RENAME" not in u
    cols = [c.strip() for c in fh._COLUMNS.split(",")]
    ddl = body[body.index("CREATE TABLE IF NOT EXISTS fact_lineage"):]
    ddl = ddl[:ddl.index(")\n        \"\"\")")]
    for c in cols + ["values_purged"]:
        assert re.search(rf"^\s+{c}\s", ddl, re.M), c


# ══ 2. ARQ BOT (FORM ASSISTANT) USAGE ═════════════════════════════════════════

class TestUsageRules:
    FALLBACK = "Sorry, I couldn't get you an answer just now."

    def test_outcomes(self):
        assert au.classify_reply("A FEIN is the 9-digit number the IRS gave your business.",
                                 self.FALLBACK) == ("answered", None)
        assert au.classify_reply("I can't recommend limits - that's your broker's call.",
                                 self.FALLBACK) == ("refused", "out_of_scope")
        assert au.classify_reply("That's a question for your broker. I can explain what "
                                 "the field means.", self.FALLBACK) == ("refused", "out_of_scope")
        assert au.classify_reply(self.FALLBACK, self.FALLBACK) == ("error", "empty_reply")
        assert au.classify_reply("", self.FALLBACK) == ("error", "empty_reply")

    def test_a_later_mention_of_the_broker_is_still_an_answer(self):
        reply = ("It is your total payroll for the year. Confirm the figure with your "
                 "broker before relying on it.")
        assert au.classify_reply(reply, self.FALLBACK)[0] == "answered"

    def test_only_a_real_question_id_is_stored(self):
        qs = [{"field_name": "fein"}, {"field_name": "naics_code"}]
        assert au.known_field(qs, "fein") == "fein"
        assert au.known_field(qs, "my bank password is hunter2") is None
        assert au.known_field(qs, "") is None and au.known_field(None, "fein") is None

    def test_token_counts_add_up_across_retries(self):
        got = au.sum_usage([{"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 64},
                            {"prompt_tokens": "5", "completion_tokens": None}, "junk"])
        assert got == {"prompt_tokens": 105, "completion_tokens": 20, "cached_tokens": 64}


def test_the_llm_wrapper_hands_back_its_token_counts():
    """No extra call: the counts OpenAI returns with the reply reach a caller that
    set LLM_USAGE_SINK; a caller that did not see nothing change."""
    import config.settings as cs
    import openai
    import utils.llm_limiter as lim

    class _Resp:
        usage = SimpleNamespace(prompt_tokens=321, completion_tokens=45,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=256))
        choices = [SimpleNamespace(message=SimpleNamespace(content=" Hello "))]

    class _Client:
        def __init__(self, *a, **k):
            async def _create(**kw):
                return _Resp()
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    class _Slot:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

    async def go(with_sink):
        sink = [] if with_sink else None
        tok = cs.LLM_USAGE_SINK.set(sink)
        try:
            reply = await cs.groq_chat("gpt-5.4-mini", [{"role": "user", "content": "hi"}])
        finally:
            cs.LLM_USAGE_SINK.reset(tok)
        return reply, sink

    with patch.object(openai, "AsyncOpenAI", _Client), \
         patch.object(lim, "get_llm_semaphore", lambda: _Slot()):
        reply, sink = _run(go(True))
        assert reply == "Hello"
        assert sink == [{"prompt_tokens": 321, "cached_tokens": 256, "completion_tokens": 45}]
        assert _run(go(False)) == ("Hello", None)


class _UsageConn:
    def __init__(self, rows=None):
        self.inserts = []
        self.rows = rows or []

    async def execute(self, sql, *args):
        self.inserts.append((" ".join(sql.split()), args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        return self.rows


def _usage_pool(conn):
    class _P:
        def acquire(self):
            class _A:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *e):
                    return False
            return _A()
    return _P()


class TestUsageStore:
    def test_a_use_is_one_row_with_no_client_text(self):
        conn = _UsageConn()
        with patch.object(cdb, "get_pool", lambda: _usage_pool(conn)):
            ok = _run(au.record_use(arq={"id": "arq-1", "session_id": "s-1", "user_id": "u-1"},
                                    field_name="fein", outcome="answered", model="gpt-5.4-mini",
                                    usage={"prompt_tokens": 900, "completion_tokens": 60},
                                    latency_ms=1234))
        assert ok and len(conn.inserts) == 1
        sql, args = conn.inserts[0]
        assert sql.startswith("INSERT INTO arq_assistant_usage")
        assert args[1:6] == ("arq-1", "s-1", "u-1", "fein", "answered")
        assert args[8:12] == (900, 60, 0, 1234)
        assert "message" not in sql and "reply" not in sql

    def test_a_bad_outcome_or_no_questionnaire_records_nothing(self):
        conn = _UsageConn()
        with patch.object(cdb, "get_pool", lambda: _usage_pool(conn)):
            assert not _run(au.record_use(arq={"id": "a"}, field_name=None, outcome="maybe"))
            assert not _run(au.record_use(arq={}, field_name=None, outcome="answered"))
        assert conn.inserts == []

    def test_a_store_failure_never_raises(self):
        def _down():
            raise RuntimeError("DB pool not initialized")
        with patch.object(cdb, "get_pool", _down):
            assert _run(au.record_use(arq={"id": "a"}, field_name=None, outcome="error")) is False
            assert _run(au.counts_for_arqs(["a"])) == {"a": au._empty_counts()}

    def test_counts_per_questionnaire(self):
        rows = [{"arq_id": "a1", "outcome": "answered", "n": 4, "last_at": "2026-10-27T10:00:00"},
                {"arq_id": "a1", "outcome": "refused", "n": 1, "last_at": "2026-10-27T11:00:00"},
                {"arq_id": "a2", "outcome": "error", "n": 2, "last_at": "2026-10-26T09:00:00"}]
        with patch.object(cdb, "get_pool", lambda: _usage_pool(_UsageConn(rows))):
            got = _run(au.counts_for_arqs(["a1", "a2", "a3", None]))
        assert got["a1"] == {"uses": 5, "answered": 4, "refused": 1, "error": 0,
                             "last_used_at": "2026-10-27T11:00:00"}
        assert got["a2"]["uses"] == 2 and got["a2"]["error"] == 2
        assert got["a3"]["uses"] == 0 and set(got) == {"a1", "a2", "a3"}


def _arq(**over):
    base = {"id": "arq-9", "session_id": "s-9", "user_id": "u-9", "status": "pending",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "questions": [{"field_name": "fein", "question": "What is your FEIN?"}]}
    base.update(over)
    return base


def _chat(arq, reply=None, raise_exc=None, body=None):
    """Drive the REAL client chat route; return (response, recorded uses)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import config.settings as cs
    import routes.arq_routes as ar
    recorded = []

    async def _rec(**kw):
        recorded.append(kw)
        return True

    async def _by_token(_t):
        return arq

    async def _no_limit(*_a, **_k):
        return None

    async def _ctx(_arq):
        return ""

    async def _fake_chat(model, messages, temperature=0, max_tokens=0, **k):
        sink = cs.LLM_USAGE_SINK.get()
        if isinstance(sink, list):
            sink.append({"prompt_tokens": 700, "completion_tokens": 40, "cached_tokens": 512})
        if raise_exc:
            raise raise_exc
        return reply

    app = FastAPI()
    app.include_router(ar.router)
    with patch.object(ar, "get_arq_by_token", _by_token), \
         patch.object(ar, "check_arq_chat_rate_limit", _no_limit), \
         patch.object(ar, "_assistant_package_context", _ctx), \
         patch.object(cs, "groq_chat", _fake_chat), \
         patch.object(au, "record_use", _rec):
        res = TestClient(app).post("/api/arq/chat/abc123", json=body or {
            "message": "My SSN is 123-45-6789, what goes here?", "active_field": "fein"})
    return res, recorded


class TestTheChatRoute:
    def test_an_answer_is_counted_with_its_tokens_and_question(self):
        res, rec = _chat(_arq(), reply="Your FEIN is the 9-digit number on your IRS letter.")
        assert res.status_code == 200 and res.json()["reply"].startswith("Your FEIN")
        assert len(rec) == 1
        r = rec[0]
        assert r["outcome"] == "answered" and r["field_name"] == "fein"
        assert r["usage"] == {"prompt_tokens": 700, "completion_tokens": 40, "cached_tokens": 512}
        assert r["latency_ms"] >= 0 and r["arq"]["id"] == "arq-9"
        assert "123-45-6789" not in json.dumps(r, default=str).replace(json.dumps(r["arq"]), "")

    def test_a_decline_and_an_error(self):
        _res, rec = _chat(_arq(), reply="I can't recommend a limit - that is your broker's job.")
        assert (rec[0]["outcome"], rec[0]["detail"]) == ("refused", "out_of_scope")
        res, rec = _chat(_arq(), raise_exc=RuntimeError("openai down"))
        assert res.status_code == 200 and "Sorry" in res.json()["reply"]
        assert (rec[0]["outcome"], rec[0]["detail"]) == ("error", "llm_error")
        _res, rec = _chat(_arq(), reply="")
        assert (rec[0]["outcome"], rec[0]["detail"]) == ("error", "empty_reply")

    def test_a_closed_link_is_a_refused_use_and_no_model_call(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        res, rec = _chat(_arq(expires_at=past), reply="never")
        assert res.status_code == 410 and rec[0]["detail"] == "link_expired"
        assert "usage" not in rec[0] or not rec[0].get("usage")
        res, rec = _chat(_arq(status="submitted"), reply="never")
        assert res.status_code == 409 and rec[0]["detail"] == "already_submitted"

    def test_an_unknown_field_is_not_stored_and_an_empty_message_is_not_a_use(self):
        _res, rec = _chat(_arq(), reply="Sure.", body={"message": "hi", "active_field": "free text"})
        assert rec[0]["field_name"] is None
        res, rec = _chat(_arq(), reply="Sure.", body={"message": "", "active_field": "fein"})
        assert res.status_code == 400 and rec == []


def test_the_admin_summary_is_admin_only():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import package_history_routes as phr
    import routes.admin_routes as adm
    from services.auth_service import get_current_user

    async def _summary(days=30, top=10):
        return {"days": days, "totals": {"uses": 3}}

    class _NoAdminRow:
        async def fetchrow(self, *a, **k):
            return None
    app = FastAPI()
    app.include_router(phr.router)
    with patch.object(adm, "_ADMIN_EMAILS", {"boss@primble.io"}), \
         patch.object(au, "admin_summary", _summary), \
         patch.object(adm, "get_pool", lambda: _usage_pool(_NoAdminRow())):
        app.dependency_overrides[get_current_user] = lambda: {"id": "u", "email": "rep@x.com"}
        assert TestClient(app).get("/api/admin/arq-assistant-usage").status_code == 403
        app.dependency_overrides[get_current_user] = lambda: {"id": "a", "email": "Boss@Primble.io"}
        res = TestClient(app).get("/api/admin/arq-assistant-usage", params={"days": 7})
    assert res.status_code == 200 and res.json()["days"] == 7 and res.json()["totals"]["uses"] == 3


def test_the_producer_sees_the_count_beside_the_questionnaire():
    src = (BACKEND / "routes" / "arq_routes.py").read_text()
    list_fn = src[src.index("async def list_arqs"):src.index("async def send_reminder")]
    assert "assistant_uses" in list_fn and "_assistant_counts(" in list_fn
    status_fn = src[src.index("async def get_arq_status"):src.index("async def _assistant_counts")]
    assert '"assistant_usage"' in status_fn
    front = (FRONT / "components" / "form" / "AcordModal.jsx").read_text()
    assert "arq.assistant_uses" in front and "Form Assistant used" in front


# ══ 3. ARCHIVAL / RETENTION ═══════════════════════════════════════════════════

ARCH = "2026-10-01T00:00:00+00:00"


class TestDoorVerdict:
    def test_matrix(self):
        live, arch = {"x": 1}, {"archived_at": ARCH}
        assert pa.door_verdict(live, {"facts": {}}, None, "POST") == "write"
        assert pa.door_verdict(arch, {"facts": {}}, None, "POST") == "refuse"
        assert pa.door_verdict(arch, {"facts": {}}, None, None) == "refuse"     # worker / task
        assert pa.door_verdict(arch, {"generated_forms": {}}, None, "GET") == "drop"
        assert pa.door_verdict(arch, {"last_downloaded_at": "t"}, None, "GET") == "write"
        assert pa.door_verdict(arch, {"package_counted_at": "t", "active_form_id": "A"}, None, "POST") == "write"
        assert pa.door_verdict(arch, {}, ["fein"], "GET") == "drop"
        assert pa.door_verdict(arch, {}, ["fein"], "POST") == "refuse"
        assert pa.door_verdict(arch, {"archived_at": None}, None, "POST") == "write"

    def test_the_archive_keys_never_ride_another_write(self):
        assert pa.without_archive_keys({"a": 1, "archived_at": "x", "archived_by": "u",
                                        "archive_reason": "r"}) == {"a": 1}
        same = {"a": 1}
        assert pa.without_archive_keys(same) is same


class TestTheDoorIsReadOnly:
    def _archived(self, store):
        sid = _new_package(store, {"fein": _env("98-7654321")})
        store.rows[sid]["data"]["archived_at"] = ARCH
        return sid

    def test_a_post_write_is_refused_and_nothing_lands(self):
        from fastapi import HTTPException
        store = _Store()
        sid = self._archived(store)
        before = json.dumps(store.rows[sid]["data"], sort_keys=True)
        with _request(method="POST"), pytest.raises(HTTPException) as e:
            _update(store, sid, {"facts": {"fein": _env("11-1111111", source="producer")}})
        assert e.value.status_code == 409 and "archived" in e.value.detail.lower()
        assert json.dumps(store.rows[sid]["data"], sort_keys=True) == before
        assert store.updates == 0 and len(store.lineage) == 1

    def test_a_write_inside_a_get_is_dropped_and_the_read_goes_on(self):
        store = _Store()
        sid = self._archived(store)
        with _request(method="GET", path="/api/fields/{session_id}/{form_id}"):
            _update(store, sid, {"generated_forms": {"ACORD_125": {"confidence": {}}}})
        assert store.updates == 0

    def test_a_download_still_records_itself(self):
        store = _Store()
        sid = self._archived(store)
        with _request(method="GET", path="/api/download-all/{session_id}"):
            _update(store, sid, {"last_downloaded_at": "2026-10-27T00:00:00"})
        assert store.updates == 1
        assert store.rows[sid]["data"]["last_downloaded_at"] == "2026-10-27T00:00:00"
        assert store.rows[sid]["data"]["archived_at"] == ARCH

    def test_a_background_task_cannot_change_an_archived_package(self):
        from fastapi import HTTPException
        store = _Store()
        sid = self._archived(store)
        with pytest.raises(HTTPException):
            _update(store, sid, {"document_ai_fill": {"state": "done"}})

    def test_a_pdf_write_is_checked_before_the_bytes_are_saved(self):
        from fastapi import HTTPException
        store = _Store()
        sid = self._archived(store)
        saved = []

        async def _save(s, g):
            saved.append(s)
        with _db(store), patch.object(sr, "_save_pdf_bytes", _save), \
             _request(method="POST"), pytest.raises(HTTPException):
            _run(sr.upd_processing_session(sid, {"generated_forms": {"ACORD_125": {"pdf_bytes": b"%PDF"}}}))
        assert saved == []

    def test_a_stale_copy_cannot_unarchive_or_rearchive(self):
        store = _Store()
        sid = _new_package(store, {})
        _update(store, sid, {"archived_at": "2020-01-01T00:00:00", "hard_stops": []})
        assert "archived_at" not in store.rows[sid]["data"]
        store.rows[sid]["data"]["archived_at"] = ARCH
        with _request(method="GET"):
            _update(store, sid, {"last_downloaded_at": "t", "archived_at": None})
        assert store.rows[sid]["data"]["archived_at"] == ARCH

    def test_a_new_package_never_starts_archived(self):
        store = _Store()
        with _db(store):
            sid = _run(sr.new_processing_session({"user_id": "u", "facts": {},
                                                  "archived_at": ARCH}))
        assert "archived_at" not in store.rows[sid]["data"]


class _ArchiveConn:
    def __init__(self):
        self.sql = []

    async def execute(self, sql, *args):
        self.sql.append((" ".join(sql.split()), args))
        return "UPDATE 1"


class TestTheArchiveDoor:
    def _go(self, fn, session, *args):
        conn = _ArchiveConn()
        logged = []

        async def _get(_sid, include_pdf=False):
            if session is None:
                from fastapi import HTTPException
                raise HTTPException(404, "not found")
            return dict(session)

        async def _log(*a, **k):
            logged.append(a)
            return True
        import services.audit_service as aud
        with patch.object(sr, "get_processing_session", _get), \
             patch.object(cdb, "get_pool", lambda: _usage_pool(conn)), \
             patch.object(aud, "log_audit_event", _log):
            out = _run(fn(*args))
        return out, conn.sql, logged

    def test_the_owner_archives_and_unarchives(self):
        out, sql, logged = self._go(pa.archive_package, {"user_id": "u1"}, "s1", "u1")
        assert out["archived"] and out["changed"]
        assert "jsonb_build_object('archived_at'" in sql[0][0]
        assert "WHERE id = $1 AND user_id = $2" in sql[0][0] and sql[0][1][:2] == ("s1", "u1")
        assert logged[0][2] == "package_archived"
        out, sql, logged = self._go(pa.unarchive_package, {"user_id": "u1", "archived_at": ARCH},
                                    "s1", "u1")
        assert out == {"archived": False, "changed": True}
        assert "data - 'archived_at'" in sql[0][0] and "updated_at = $3" in sql[0][0]
        assert logged[0][2] == "package_unarchived"

    def test_idempotent_both_ways(self):
        out, sql, _ = self._go(pa.archive_package, {"user_id": "u1", "archived_at": ARCH}, "s1", "u1")
        assert out["changed"] is False and sql == []
        out, sql, _ = self._go(pa.unarchive_package, {"user_id": "u1"}, "s1", "u1")
        assert out["changed"] is False and sql == []

    def test_only_the_owner(self):
        from fastapi import HTTPException
        for fn in (pa.archive_package, pa.unarchive_package):
            with pytest.raises(HTTPException) as e:
                self._go(fn, {"user_id": "u1"}, "s1", "u2")
            assert e.value.status_code == 403
            with pytest.raises(HTTPException) as e:
                self._go(fn, None, "s-missing", "u1")
            assert e.value.status_code == 404

    def test_not_while_forms_are_being_generated(self):
        from fastapi import HTTPException
        running = {"user_id": "u1", "document_ai_fill": {
            "state": "running", "started_at": datetime.now(timezone.utc).isoformat()}}
        with pytest.raises(HTTPException) as e:
            self._go(pa.archive_package, running, "s1", "u1")
        assert e.value.status_code == 409


class _ListConn:
    def __init__(self):
        self.sql = []

    async def fetch(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        return []

    async def fetchrow(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        return {"n": 0}


def test_the_dashboard_lists_split_on_the_archive():
    conn = _ListConn()
    with patch.object(sr, "get_pool", lambda: _usage_pool(conn)):
        _run(sr.list_sessions_for_user("u"))
        _run(sr.list_sessions_for_user("u", archived=True, search="acme"))
        _run(sr.count_sessions_for_user("u"))
        sr._MATCH_CACHE.clear()        # the page and its count share one match for 5 s
        _run(sr.count_sessions_for_user("u", search="acme", archived=True))
    active, archived, c_active, c_archived = conn.sql
    assert "(data->>'archived_at') IS NULL" in active
    assert "(data->>'archived_at') IS NOT NULL" not in active
    # The search matches in the app (27 Oct 2026, the name is in encrypted
    # facts) - the archive split still holds on its query, and no ILIKE.
    assert "(data->>'archived_at') IS NOT NULL" in archived and "ILIKE" not in archived
    assert "(data->>'archived_at') IS NULL" in c_active
    assert "(data->>'archived_at') IS NOT NULL" in c_archived
    assert "data->>'archived_at' AS archived_at" in active


class _RetentionConn:
    def __init__(self):
        self.sql = []

    async def execute(self, sql, *args):
        self.sql.append((" ".join(sql.split()), args))
        return "DELETE 0"

    def transaction(self):
        return _Tx()


def _retention(monkeypatch, **env):
    import services.scheduler_service as ss
    for k in ("SESSION_RETENTION_DAYS", "ARCHIVED_SESSION_RETENTION_DAYS",
              "PACKAGE_AUTO_ARCHIVE_DAYS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    conn = _RetentionConn()
    monkeypatch.setattr(ss, "get_pool", lambda: _usage_pool(conn))
    _run(ss.run_retention_cleanup())
    return conn.sql


def _days_ago(iso):
    return round((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 86400)


class TestRetention:
    def test_one_due_predicate_for_everything_a_package_owns(self, monkeypatch):
        sql = _retention(monkeypatch)
        by_table = {s.split()[2]: (s, a) for s, a in sql if s.startswith("DELETE FROM")}
        for table in ("session_pdf_bytes", "signature_requests", "fact_lineage", "processing_sessions"):
            s, args = by_table[table]
            assert " ".join(pa.EXPIRED_PACKAGE_IDS_SQL.split()) in s, table
            assert _days_ago(args[0]) == 180 and _days_ago(args[1]) == 730
        order = [s.split()[2] for s, _ in sql if s.startswith("DELETE FROM")]
        assert order.index("fact_lineage") < order.index("processing_sessions")
        assert not any(s.startswith("UPDATE processing_sessions") for s, _ in sql)  # auto-archive off

    def test_archive_retention_is_never_shorter_than_active(self, monkeypatch):
        sql = _retention(monkeypatch, SESSION_RETENTION_DAYS=180, ARCHIVED_SESSION_RETENTION_DAYS=30)
        s, args = next((s, a) for s, a in sql if s.startswith("DELETE FROM processing_sessions"))
        assert _days_ago(args[1]) == 180
        sql = _retention(monkeypatch, SESSION_RETENTION_DAYS=90, ARCHIVED_SESSION_RETENTION_DAYS=1000)
        s, args = next((s, a) for s, a in sql if s.startswith("DELETE FROM processing_sessions"))
        assert (_days_ago(args[0]), _days_ago(args[1])) == (90, 1000)

    def test_a_bad_value_falls_back_to_the_default(self, monkeypatch):
        sql = _retention(monkeypatch, ARCHIVED_SESSION_RETENTION_DAYS="forever",
                         PACKAGE_AUTO_ARCHIVE_DAYS="soon")
        s, args = next((s, a) for s, a in sql if s.startswith("DELETE FROM processing_sessions"))
        assert _days_ago(args[1]) == 730
        assert not any(s.startswith("UPDATE processing_sessions") for s, _ in sql)

    def test_auto_archive_runs_first_and_only_inside_the_active_window(self, monkeypatch):
        sql = _retention(monkeypatch, PACKAGE_AUTO_ARCHIVE_DAYS=60)
        assert sql[0][0] == " ".join(pa.AUTO_ARCHIVE_SQL.split())
        idle, active, now = sql[0][1]
        assert (_days_ago(idle), _days_ago(active), _days_ago(now)) == (60, 180, 0)
        assert "updated_at < $1 AND updated_at >= $2" in sql[0][0]
        assert "(data->>'archived_at') IS NULL" in sql[0][0]

    def test_auto_archive_at_or_past_the_active_retention_is_off(self, monkeypatch):
        for days in (180, 400):
            sql = _retention(monkeypatch, PACKAGE_AUTO_ARCHIVE_DAYS=days)
            assert not any(s.startswith("UPDATE processing_sessions") for s, _ in sql)

    def test_an_unreadable_archive_time_is_never_due(self):
        assert "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'" in pa.EXPIRED_PACKAGE_IDS_SQL
        assert "(data->>'archived_at') IS NULL AND updated_at < $1" in " ".join(pa.EXPIRED_PACKAGE_IDS_SQL.split())

    def test_the_facts_purge_blanks_the_lineage_values(self, monkeypatch):
        import services.scheduler_service as ss
        conn = _RetentionConn()
        monkeypatch.setattr(ss, "get_pool", lambda: _usage_pool(conn))
        _run(ss.run_facts_retention())
        assert any(s == " ".join(fh.PURGE_VALUES_SQL.split()) for s, _ in conn.sql)

    def test_a_deleted_package_takes_its_lineage(self):
        src = (BACKEND / "routes" / "form_routes.py").read_text()
        fn = src[src.index("async def delete_session"):]
        fn = fn[:fn.index("@router")]
        assert "DELETE FROM fact_lineage WHERE session_id = $1" in fn
        auth = (BACKEND / "routes" / "auth_routes.py").read_text()
        assert "DELETE FROM fact_lineage        WHERE user_id = $1" in auth
        assert "DELETE FROM arq_assistant_usage WHERE user_id = $1" in auth


# ── The route guard, over every write route the app mounts ────────────────────

def _main_app():
    import main                     # the real app, with its real middleware stack
    return main.app


def _write_routes(app):
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
                yield m, r


def _route_takes_body_session(route) -> bool:
    import inspect
    for f in route.dependant.body_params:
        ann = getattr(f, "type_", None) or getattr(getattr(f, "field_info", None), "annotation", None)
        fields = getattr(ann, "model_fields", None) or {}
        if "session_id" in fields:
            return True
    src = inspect.getsource(route.endpoint)
    return 'body.get("session_id"' in src


def test_every_write_route_is_placed_by_the_guard():
    """A new write route that names a package where the guard cannot see it -
    or touches none and is not listed - fails here."""
    app = _main_app()
    unplaced = []
    for method, route in _write_routes(app):
        params = re.findall(r"{(\w+)}", route.path)
        kind = pa.classify_route(method, route.path, params)
        if kind == "body" and not _route_takes_body_session(route):
            unplaced.append(f"{method} {route.path}")
    assert not unplaced, ("write routes the archive guard cannot place - name the package "
                          "in the path or the JSON body's session_id, or list the route in "
                          f"package_archive.NO_PACKAGE_WRITE_ROUTES: {unplaced}")


def _payload(route):
    return {"session_id": "sid-arch", "form_id": "ACORD_125", "fields": {}, "rec_id": "r"}


def test_every_write_route_refuses_an_archived_package_with_a_409():
    from fastapi.testclient import TestClient
    app = _main_app()
    reached = []

    async def _state(sid):
        return ARCH if sid == "sid-arch" else None

    async def _link(path, params):
        return "sid-arch"

    checked = 0
    with patch.object(pa, "archived_state", _state), patch.object(pa, "session_for_link", _link):
        client = TestClient(app, raise_server_exceptions=False)
        for method, route in _write_routes(app):
            params = re.findall(r"{(\w+)}", route.path)
            kind = pa.classify_route(method, route.path, params)
            if kind == "exempt":
                continue
            path = route.path
            for p in params:
                path = path.replace("{" + p + "}", "sid-arch" if p in ("session_id", "sid") else "tok-1")
            res = client.request(method, path, json=_payload(route))
            if res.status_code != 409 or res.json().get("code") != pa.ARCHIVED_CODE:
                reached.append(f"{method} {route.path} -> {res.status_code}")
            checked += 1
    # 39 since the review (R3): the Essentials score screen's POST serves an
    # archived package read-only itself, so the guard lets it through.
    assert checked >= 39
    assert not reached, f"write routes that reached their handler on an archived package: {reached}"


def test_an_active_package_and_every_read_pass_the_guard():
    from fastapi.testclient import TestClient
    app = _main_app()

    async def _state(sid):
        return None

    async def _arch(sid):
        return ARCH
    with patch.object(pa, "archived_state", _state):
        res = TestClient(app, raise_server_exceptions=False).post(
            "/api/update-pdf", json={"session_id": "sid-live", "form_id": "A", "fields": {}})
        assert res.status_code != 409                     # reaches auth -> 401
    with patch.object(pa, "archived_state", _arch):
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/api/session/sid-arch").status_code != 409
        assert client.post("/api/review/preview-answer",
                           json={"session_id": "sid-arch"}).status_code != 409
        assert client.post("/api/sessions/sid-arch/unarchive").status_code != 409


def test_the_409_carries_cors_headers_and_a_client_link_reads_closed():
    from fastapi.testclient import TestClient
    from config.settings import ALLOWED_ORIGINS
    app = _main_app()
    origin = sorted(ALLOWED_ORIGINS)[0] if ALLOWED_ORIGINS else "http://localhost:5173"

    async def _arch(sid):
        return ARCH

    async def _link(path, params):
        return "sid-arch"
    with patch.object(pa, "archived_state", _arch), patch.object(pa, "session_for_link", _link):
        client = TestClient(app, raise_server_exceptions=False)
        res = client.post("/api/update-pdf", json={"session_id": "sid-arch"},
                          headers={"Origin": origin})
        assert res.status_code == 409
        assert res.headers.get("access-control-allow-origin") == origin
        assert res.json()["detail"] == pa.ARCHIVED_MESSAGE
        res = client.post("/api/arq/submit/abc", json={"answers": {}})
        assert res.status_code == 409 and res.json()["detail"] == pa.ARCHIVED_CLIENT_MESSAGE


def test_the_dashboard_has_the_archived_filter_and_the_actions():
    src = (FRONT / "components" / "form" / "AcordModal.jsx").read_text()
    assert "archived=1" in src or "&archived=" in src
    assert '${archive ? "archive" : "unarchive"}' in src and "/unarchive`" in src
    assert "Archived" in src and "Unarchive" in src


def test_the_client_link_of_an_archived_package_reads_closed():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.arq_routes as ar

    async def _by_token(_t):
        return _arq()

    async def _no_limit(*_a, **_k):
        return None

    async def _arch(sid):
        return ARCH if sid == "s-9" else None
    app = FastAPI()
    app.include_router(ar.router)
    with patch.object(ar, "get_arq_by_token", _by_token), \
         patch.object(ar, "check_arq_public_rate_limit", _no_limit), \
         patch.object(pa, "archived_state", _arch):
        res = TestClient(app).get("/api/arq/client-view/abc123")
    assert res.status_code == 409
    assert res.json()["error"] == "closed" and res.json()["message"] == pa.ARCHIVED_CLIENT_MESSAGE


def test_a_buffered_json_body_reaches_the_handler_intact():
    """The guard reads a JSON body to find its session_id; the handler must still
    receive every byte (a large body included)."""
    from fastapi import Body, FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()

    @app.post("/echo")
    async def _echo(payload: dict = Body(...)):
        return payload

    app.add_middleware(pa.ArchivedPackageGuard)
    seen = []

    async def _state(sid):
        seen.append(sid)
        return None
    payload = {"session_id": "sid-live", "fields": {f"f{i}": "x" * 50 for i in range(2000)}}
    with patch.object(pa, "archived_state", _state):
        res = TestClient(app).post("/echo", json=payload)
    assert res.status_code == 200 and res.json() == payload and seen == ["sid-live"]
