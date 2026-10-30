"""Adversarial review of Lane C (27 Oct 2026) - see 25sepChanges.md Z44-C-R.

Each test pins a defect the review reproduced:
  R1  the archive guard read a request body only for `Content-Type:
      application/json` WITH a Content-Length, while FastAPI parses a body with
      NO content type, any `application/*+json`, and a chunked body as JSON - so
      those requests reached their handler on an archived package (and the
      dismiss credit's raw SQL is behind no write door);
  R2  the nightly questionnaire reminder e-mailed the client of an ARCHIVED
      package (its link then reads "closed");
  R3  an Essentials producer could not open an archived package: the lite
      screen POSTs `/api/lite/generate-internal/{id}` on every visit and the
      guard refused it, so the read-only view showed "Could not score";
  R4  document attribution (CPU, linear in document size) ran on the event loop
      inside the write's row lock.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services import package_archive as pa                     # noqa: E402
from services import fact_history as fh                        # noqa: E402

ARCH = "2026-10-01T00:00:00+00:00"


def _main_app():
    import main
    return main.app


async def _archived(sid):
    return ARCH if sid == "sid-arch" else None


# ── R1: the guard reads every body FastAPI reads as JSON ─────────────────────

def _client():
    from fastapi.testclient import TestClient
    return TestClient(_main_app(), raise_server_exceptions=False)


def _assert_refused(res):
    assert res.status_code == 409, (res.status_code, res.text[:200])
    assert res.json().get("code") == pa.ARCHIVED_CODE


def test_a_body_with_no_content_type_is_still_read():
    body = json.dumps({"session_id": "sid-arch", "rec_id": "r"}).encode()
    with patch.object(pa, "archived_state", _archived):
        res = _client().post("/api/audit/dismiss", content=body)
    _assert_refused(res)


def test_a_plus_json_body_is_still_read():
    body = json.dumps({"session_id": "sid-arch", "form_id": "A", "fields": {}}).encode()
    with patch.object(pa, "archived_state", _archived):
        res = _client().post("/api/update-pdf", content=body,
                             headers={"content-type": "application/merge-patch+json"})
    _assert_refused(res)


def test_a_chunked_json_body_is_still_read():
    payload = json.dumps({"session_id": "sid-arch", "rec_id": "r"}).encode()

    def chunks():
        yield payload[:10]
        yield payload[10:]
    with patch.object(pa, "archived_state", _archived):
        res = _client().post("/api/audit/dismiss", content=chunks(),
                             headers={"content-type": "application/json"})
    _assert_refused(res)


def test_the_json_predicate_is_fastapis():
    assert pa.is_json_content_type("")
    assert pa.is_json_content_type("application/json; charset=utf-8")
    assert pa.is_json_content_type("Application/JSON")
    assert pa.is_json_content_type("application/vnd.api+json")
    assert not pa.is_json_content_type("multipart/form-data; boundary=x")
    assert not pa.is_json_content_type("text/plain;charset=UTF-8")
    assert not pa.is_json_content_type("application/x-www-form-urlencoded")


def test_an_oversized_or_chunked_body_is_replayed_byte_for_byte():
    """A body the guard reads (or stops reading at its cap) reaches the
    handler unchanged - the guard never eats or reorders a byte."""
    big = [b"a" * 1000, b"b" * 1000, b"c" * 1000]

    async def go(limit):
        msgs = [{"type": "http.request", "body": c, "more_body": i < len(big) - 1}
                for i, c in enumerate(big)]

        async def receive():
            return msgs.pop(0) if msgs else {"type": "http.disconnect"}
        body, replay = await pa._buffer_body(receive, limit)
        got = []
        while True:
            m = await replay()
            if m["type"] != "http.request":
                break
            got.append(m.get("body", b""))
            if not m.get("more_body"):
                break
        return body, b"".join(got)
    body, seen = asyncio.run(go(1500))
    assert body is None and seen == b"".join(big)        # over the cap: not judged, all replayed
    body, seen = asyncio.run(go(10_000))
    assert body == b"".join(big) and seen == body


def test_an_active_package_with_a_bare_body_still_reaches_its_handler():
    body = json.dumps({"session_id": "sid-live", "rec_id": "r"}).encode()
    with patch.object(pa, "archived_state", _archived):
        res = _client().post("/api/audit/dismiss", content=body)
    assert res.status_code != 409                          # auth -> 401


# ── R2: no reminder e-mail for an archived package ───────────────────────────

def test_the_auto_reminder_skips_an_archived_package():
    from services import scheduler_service as ss
    sent, seen_sql = [], []

    class _Conn:
        async def fetch(self, sql, *args):
            seen_sql.append(" ".join(sql.split()))
            return []

        async def fetchrow(self, sql, *args):
            return None

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    class _Pool:
        def acquire(self):
            return _Acq()

    async def _send(arq_id, user):
        sent.append(arq_id)
        return True
    with patch.object(ss, "get_pool", lambda: _Pool()), \
            patch("services.arq_service.send_arq_reminder", _send):
        asyncio.run(ss.run_arq_auto_reminders())
    sql = seen_sql[0]
    # the package must be read and an archived one left out (verified on a
    # throwaway Postgres: before the fix the archived package's arq was e-mailed)
    assert "processing_sessions" in sql and "archived_at" in sql, sql
    assert "NOT EXISTS" in sql


# ── R3: an archived Essentials package still opens ───────────────────────────

def test_an_archived_lite_package_serves_its_stored_score_without_writing():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import form_routes as fr
    from services.auth_service import get_current_user

    stored = {
        "user_id": "u1", "archived_at": ARCH,
        "recommendations": [{"form_id": "ACORD_125"}],
        "selected_form_ids": ["ACORD_125"],
        "generated_forms": {"ACORD_125": {"sqs": {"sqs_score": 71, "tier": "Needs Work",
                                                  "compliance_checklist": ["x"]}}},
        "package_sqs": {"package_sqs_score": 74, "tier": "Needs Work", "pillars": {"a": 1}},
        "hard_stops": [], "soft_stops": ["w"], "flags": {"f": True},
    }
    writes = []

    async def _get(sid, include_pdf=False):
        return json.loads(json.dumps(stored))

    async def _upd(*a, **k):
        writes.append(a)

    async def _boom(*a, **k):
        raise AssertionError("an archived package must not be regenerated")
    app = FastAPI()
    app.include_router(fr.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "subscription_tier": "essentials", "payment_status": "ok"}
    with patch.object(fr, "get_processing_session", _get), \
            patch.object(fr, "upd_processing_session", _upd), \
            patch.object(fr, "_lite_shared_gap_fill", _boom):
        res = TestClient(app).post("/api/lite/generate-internal/sid-arch")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["success"] and d["sqs"]["sqs_score"] == 74 and d["soft_stops"] == ["w"]
    assert d["compliance_checklist"] == ["x"]
    assert writes == []


def test_an_archived_lite_package_with_no_score_is_refused():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes import form_routes as fr
    from services.auth_service import get_current_user

    async def _get(sid, include_pdf=False):
        return {"user_id": "u1", "archived_at": ARCH, "recommendations": [{"form_id": "ACORD_125"}],
                "generated_forms": {}}
    app = FastAPI()
    app.include_router(fr.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "subscription_tier": "essentials", "payment_status": "ok"}
    with patch.object(fr, "get_processing_session", _get):
        res = TestClient(app).post("/api/lite/generate-internal/sid-arch")
    assert res.status_code == 409


def test_the_lite_route_passes_the_guard_only_as_a_read():
    """Exempt from the guard because the route itself serves an archived
    package read-only (above) - the route still refuses a write."""
    assert ("POST", "/api/lite/generate-internal/{session_id}") in pa.NOT_A_PACKAGE_CHANGE


# ── R4: attribution never blocks the event loop ──────────────────────────────

def test_document_attribution_runs_off_the_event_loop():
    calls = []
    real = fh.build_rows

    def spy(*a, **k):
        import threading
        calls.append(threading.current_thread() is threading.main_thread())
        return real(*a, **k)

    class _Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

    class _Conn:
        rows = []

        def transaction(self):
            return _Tx()

        async def executemany(self, sql, rows):
            self.rows.extend(rows)
    conn = _Conn()
    docs = [{"doc_id": "d1", "filename": "Dec.pdf", "text": "[Document page 1]\nFEIN 12-3456789"}]
    with patch.object(fh, "build_rows", spy):
        n = asyncio.run(fh.record_fact_changes(conn, "s", "u", {},
                                               {"fein": {"value": "12-3456789", "source": "ai"}},
                                               docs=docs))
        n2 = asyncio.run(fh.record_fact_changes(conn, "s", "u", {},
                                                {"x": {"value": "1", "source": "producer"}}))
    assert n == 1 and n2 == 1
    assert calls == [False, True]          # with documents: a worker thread; without: inline
