"""package_archive.py - archive / unarchive a package, read-only while archived
(Brent's V2 list, "Session archival / retention", 27 Oct 2026).

THE STATE lives on the package row itself - `data.archived_at` (ISO time),
`data.archived_by` (the user id, or "system" for an idle auto-archive) and
`data.archive_reason` - so it needs no schema change and every reader that
already loads the row can see it. Only `archive_package` / `unarchive_package`
and the scheduler's auto-archive write those keys; the write door strips them
from any other update, so a stale copy of the row can never re-archive or
unarchive a package by writing itself back.

READ-ONLY, TWO LAYERS, ONE RULE ("an archived package does not change"):

  1. `ArchivedPackageGuard` (ASGI middleware) refuses EVERY write request
     (POST / PUT / PATCH / DELETE) that names an archived package - by its
     path (`{session_id}`, a questionnaire / signing `{token}`, an `{arq_id}`)
     or by the `session_id` in its JSON body - with a 409 before any work
     runs. It sits inside CORS, so the browser can read the 409.
     `NOT_A_PACKAGE_CHANGE` lists the few write routes that touch a package
     without changing it (preview, navigation, a download note, the client's
     Form Assistant, the archive door itself). tests/test_lane_c_27oct.py
     walks every write route the app mounts and fails the build on one the
     guard cannot place.
  2. The write door, `session_repository.upd_processing_session`, asks
     `door_verdict` on the locked row: an archived package accepts only the
     bookkeeping a READ leaves (`READ_BOOKKEEPING_KEYS` - a download's time and
     usage count, the form open). Any other write inside a GET (a legacy label
     repair while a form is viewed) is dropped, never raised - the read still
     works; any other write outside a GET (a background task started before
     the archive, the worker) is refused with the same 409.

RETENTION (scheduler_service.run_retention_cleanup): an archived package is
kept ARCHIVED_SESSION_RETENTION_DAYS (default 730, never shorter than the
active SESSION_RETENTION_DAYS) from the day it was archived; an active package
keeps the old rule. PACKAGE_AUTO_ARCHIVE_DAYS (default 0 = off) archives a
package idle that long - only one still inside the active retention, so turning
it on never rescues a package already due for deletion.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

ARCHIVED_KEY = "archived_at"
ARCHIVED_BY_KEY = "archived_by"
ARCHIVE_REASON_KEY = "archive_reason"
ARCHIVE_KEYS = (ARCHIVED_KEY, ARCHIVED_BY_KEY, ARCHIVE_REASON_KEY)

ARCHIVED_CODE = "package_archived"
ARCHIVED_MESSAGE = "This package is archived. Unarchive it to make changes."
ARCHIVED_CLIENT_MESSAGE = ("This questionnaire is closed. Please contact your broker "
                           "if you still need to send answers.")

# What a READ of an archived package may still record: a download's time and
# its usage count, and the form the producer has open.
READ_BOOKKEEPING_KEYS = frozenset({"last_downloaded_at", "package_counted_at", "active_form_id"})

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_READ_METHODS = frozenset({"GET", "HEAD"})

# Write routes that touch ONE package without changing it. Everything else
# that names a package is refused while it is archived.
NOT_A_PACKAGE_CHANGE = {
    ("POST", "/api/review/preview-answer"): "a preview - reads a copy, never saves",
    ("POST", "/api/session/{session_id}/active-form"): "navigation - the form open",
    ("POST", "/api/audit/download-anyway"): "a note on a download, which an archive allows",
    ("POST", "/api/arq/chat/{token}"): "the client's Form Assistant - explains, never writes",
    # The Essentials score screen POSTs this on every visit. On an archived
    # package the route serves the stored score and writes nothing (review R3).
    ("POST", "/api/lite/generate-internal/{session_id}"):
        "the Essentials score screen - an archived package gets its stored score, no write",
    ("POST", "/api/sessions/{session_id}/archive"): "the archive door",
    ("POST", "/api/sessions/{session_id}/unarchive"): "the archive door",
}

# Write routes that never name an existing package (the account, billing,
# admin, a new upload, ...). Listed so the anti-rot test can tell "the guard
# does not apply" from "the guard was forgotten" - a new write route has to be
# placed in one of the two lists or name its package where the guard looks.
NO_PACKAGE_WRITE_ROUTES = {
    ("POST", "/api/upload-declaration"): "creates a NEW package",
    ("POST", "/api/assistant/chat"): "the dashboard assistant - no package",
    ("POST", "/api/arq/notifications/read"): "the producer's notification list",
    ("POST", "/api/arq/decode-vin"): "a VIN lookup - no package",
    ("POST", "/api/auth/save-signature"): "the producer's saved signature",
    ("POST", "/api/acord/confirm-license"): "the account's licence",
}
# Whole prefixes of routes that never name a package.
NO_PACKAGE_PREFIXES = ("/api/auth/", "/api/stripe/", "/api/admin/", "/api/dev/",
                       "/api/billing/", "/api/count-download")

_PATH_SESSION_PARAMS = ("session_id", "sid")
_MAX_JSON_BODY = 2 * 1024 * 1024


def _env_days(name: str, default: int, floor: int = 0) -> int:
    try:
        return max(floor, int(str(os.getenv(name, str(default))).strip()))
    except (TypeError, ValueError):
        return default


def active_retention_days() -> int:
    return _env_days("SESSION_RETENTION_DAYS", 180, 1)


def archive_retention_days() -> int:
    """Days an archived package is kept after it was archived - never shorter
    than an active package's retention."""
    return max(_env_days("ARCHIVED_SESSION_RETENTION_DAYS", 730, 1), active_retention_days())


def auto_archive_days() -> int:
    """Idle days before a package is archived by the nightly job; 0 = off."""
    return _env_days("PACKAGE_AUTO_ARCHIVE_DAYS", 0, 0)


def is_archived(session: Any) -> bool:
    return isinstance(session, dict) and bool(session.get(ARCHIVED_KEY))


def archive_fields(session: Any) -> dict:
    """The archive state for a response: archived_at / archived_by / reason."""
    s = session if isinstance(session, dict) else {}
    return {
        "archived": bool(s.get(ARCHIVED_KEY)),
        "archived_at": s.get(ARCHIVED_KEY),
        "archive_reason": s.get(ARCHIVE_REASON_KEY),
    }


def without_archive_keys(updates: dict) -> dict:
    """`updates` minus the archive keys - only the archive door sets them."""
    if not isinstance(updates, dict) or not any(k in updates for k in ARCHIVE_KEYS):
        return updates
    return {k: v for k, v in updates.items() if k not in ARCHIVE_KEYS}


WRITE, DROP, REFUSE = "write", "drop", "refuse"


def door_verdict(current: Any, updates: Any, delete_facts: Optional[Iterable] = None,
                 method: Optional[str] = None) -> str:
    """What the write door does with an update to this row:
    WRITE (not archived, or only read bookkeeping), DROP (archived, inside a
    GET - the read goes on), REFUSE (archived, any other write)."""
    if not is_archived(current):
        return WRITE
    keys = {k for k in (updates or {}) if k not in ARCHIVE_KEYS}
    if not delete_facts and keys <= READ_BOOKKEEPING_KEYS:
        return WRITE
    if method is None:
        try:
            from services.fact_history import request_method
            method = request_method()
        except Exception:                                      # noqa: BLE001
            method = None
    if (method or "").upper() in _READ_METHODS:
        return DROP
    return REFUSE


def archived_http_error(client: bool = False):
    from fastapi import HTTPException
    return HTTPException(409, ARCHIVED_CLIENT_MESSAGE if client else ARCHIVED_MESSAGE)


# ── DB reads the guard needs ────────────────────────────────────────────────

async def archived_state(session_id: str) -> Optional[str]:
    """`archived_at` of a package, or None (not archived, or no such row)."""
    from config.database import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data->>'archived_at' AS archived_at FROM processing_sessions WHERE id = $1",
            str(session_id))
    value = dict(row).get("archived_at") if row else None
    return value if isinstance(value, str) and value.strip() else None


async def session_for_link(path: str, params: dict) -> Optional[str]:
    """The package a questionnaire / signing link or a questionnaire id names."""
    from config.database import get_pool
    token, arq_id = params.get("token"), params.get("arq_id")
    if token and path.startswith("/api/applicant-sign/"):
        sql, arg = "SELECT session_id FROM signature_requests WHERE token = $1", token
    elif token and path.startswith("/api/arq/"):
        sql, arg = "SELECT session_id FROM arq_sessions WHERE token = $1", token
    elif arq_id:
        sql, arg = "SELECT session_id FROM arq_sessions WHERE id = $1", arq_id
    else:
        return None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, str(arg))
    value = dict(row).get("session_id") if row else None
    return str(value) if value else None


# ── The route guard ─────────────────────────────────────────────────────────

def match_route(app: Any, scope: dict) -> Tuple[Any, dict]:
    """(route, path_params) the router would pick for this request."""
    try:
        from starlette.routing import Match
    except Exception:                                          # noqa: BLE001
        return None, {}
    for route in getattr(getattr(app, "router", None), "routes", []) or []:
        try:
            match, child = route.matches(scope)
        except Exception:                                      # noqa: BLE001
            continue
        if match == Match.FULL:
            return route, dict((child or {}).get("path_params") or {})
    return None, {}


def classify_route(method: str, path: str, path_params: Iterable[str]) -> str:
    """How the guard places a write route: "exempt" (touches no package, or
    does not change one), "path" (its package is in the path), "link" (a
    questionnaire / signing link names it), "body" (the JSON body's
    session_id), or "unknown"."""
    key = (method, path)
    if key in NOT_A_PACKAGE_CHANGE or key in NO_PACKAGE_WRITE_ROUTES:
        return "exempt"
    if any(path.startswith(p) for p in NO_PACKAGE_PREFIXES):
        return "exempt"
    params = set(path_params or ())
    if params & set(_PATH_SESSION_PARAMS):
        return "path"
    if params & {"token", "arq_id"}:
        return "link"
    return "body"


def _header(scope: dict, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            try:
                return v.decode("latin-1")
            except Exception:                                  # noqa: BLE001
                return ""
    return ""


def is_json_content_type(ctype: str) -> bool:
    """FastAPI's own rule for a body it parses as JSON (fastapi.routing): no
    content type at all, `application/json`, or any `application/*+json`. The
    guard must read every body the handler will read (review R1, 27 Oct 2026 -
    a bare or `+json` body reached its handler on an archived package)."""
    main = str(ctype or "").split(";", 1)[0].strip().lower()
    if not main:
        return True
    return main == "application/json" or (main.startswith("application/")
                                          and main.endswith("+json"))


async def _buffer_body(receive, limit: Optional[int] = None):
    """Read the request body (at most `limit` bytes) and return (body, a
    receive that replays it). A body longer than `limit` is not judged - body
    is None - and the replay hands the handler what was read, then the rest of
    the stream, byte for byte (a chunked body has no Content-Length to check
    beforehand)."""
    chunks, more, disconnected, size = [], True, False, 0
    while more:
        msg = await receive()
        if msg.get("type") == "http.disconnect":
            disconnected = True
            break
        chunk = msg.get("body", b"") or b""
        chunks.append(chunk)
        size += len(chunk)
        more = bool(msg.get("more_body", False))
        if more and limit is not None and size > limit:
            break                                   # too long to judge - stream the rest
    body = b"".join(chunks)
    over = more and not disconnected
    sent = False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            if disconnected:
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": body, "more_body": over}
        return await receive()

    return (None if over else body), replay


def session_id_in_body(body: bytes) -> Optional[str]:
    try:
        data = json.loads(body.decode("utf-8")) if body else None
    except Exception:                                          # noqa: BLE001
        return None
    if isinstance(data, dict):
        sid = data.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class ArchivedPackageGuard:
    """Refuses a write request that names an archived package (409)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        method = str(scope.get("method") or "").upper()
        if scope.get("type") != "http" or method not in _WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        route, params = match_route(scope.get("app"), scope)
        path = getattr(route, "path", None)
        if route is None or not path:
            await self.app(scope, receive, send)
            return
        kind = classify_route(method, path, params.keys())
        if kind == "exempt":
            await self.app(scope, receive, send)
            return
        sid = None
        client = False
        try:
            if kind == "path":
                sid = next((params[p] for p in _PATH_SESSION_PARAMS if params.get(p)), None)
            elif kind == "link":
                client = "token" in params
                sid = await session_for_link(path, params)
            else:
                ctype = _header(scope, b"content-type")
                length = _header(scope, b"content-length").strip()
                if is_json_content_type(ctype) and not (
                        length.isdigit() and int(length) > _MAX_JSON_BODY):
                    body, receive = await _buffer_body(receive, _MAX_JSON_BODY)
                    sid = session_id_in_body(body) if body is not None else None
            archived = await archived_state(sid) if sid else None
        except Exception as ex:                                # noqa: BLE001
            # The guard cannot tell - let the request through; the write door
            # still refuses a change to an archived package.
            logger.warning("archive guard: check skipped for %s %s: %s", method, path, ex)
            archived = None
        if archived:
            await _send_json(send, 409, {
                "detail": ARCHIVED_CLIENT_MESSAGE if client else ARCHIVED_MESSAGE,
                "code": ARCHIVED_CODE,
                "archived_at": archived,
            })
            return
        await self.app(scope, receive, send)


# ── The archive door ────────────────────────────────────────────────────────

async def _generation_running(session: dict) -> bool:
    """A form generation or an added document's AI reading is in flight."""
    from services.generation_state import (
        generation_state, document_fill_running, STATE_RUNNING,
    )
    if document_fill_running(session):
        return True
    jid = session.get("generation_job_id")
    if not jid or session.get("generated_forms"):
        return False
    try:
        from services.job_queue import get_job_queue
        job = await get_job_queue().get_status(str(jid))
    except Exception:                                          # noqa: BLE001
        return True                     # unreadable job: refusing is the safe side
    return generation_state(session, job) == STATE_RUNNING


async def archive_package(session_id: str, user_id: str, reason: str = "producer") -> dict:
    """Archive the owner's package. Idempotent. 404 / 403 / 409 as HTTPException."""
    from fastapi import HTTPException
    from config.database import get_pool
    from repositories.session_repository import get_processing_session
    session = await get_processing_session(session_id)          # 404 when missing
    if str(session.get("user_id") or "") != str(user_id):
        raise HTTPException(403, "Access denied")
    if is_archived(session):
        return {"archived": True, "archived_at": session.get(ARCHIVED_KEY), "changed": False}
    if await _generation_running(session):
        raise HTTPException(409, "Forms are being generated - wait for them to finish "
                                 "before archiving.")
    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        status = await conn.execute(
            "UPDATE processing_sessions"
            " SET data = data || jsonb_build_object('archived_at', $3::text,"
            "                                       'archived_by', $2::text,"
            "                                       'archive_reason', $4::text)"
            " WHERE id = $1 AND user_id = $2 AND (data->>'archived_at') IS NULL",
            str(session_id), str(user_id), now, str(reason or "producer")[:40])
    changed = str(status or "").strip().endswith(" 1")
    if changed:
        await _log(session_id, user_id, "package_archived", {"reason": reason})
    return {"archived": True, "archived_at": now, "changed": changed}


async def unarchive_package(session_id: str, user_id: str) -> dict:
    """Unarchive the owner's package. The package's clock restarts (updated_at
    = now), so the next retention sweep never deletes a package the producer
    just brought back. Idempotent."""
    from fastapi import HTTPException
    from config.database import get_pool
    from repositories.session_repository import get_processing_session
    session = await get_processing_session(session_id)
    if str(session.get("user_id") or "") != str(user_id):
        raise HTTPException(403, "Access denied")
    if not is_archived(session):
        return {"archived": False, "changed": False}
    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        status = await conn.execute(
            "UPDATE processing_sessions"
            " SET data = data - 'archived_at' - 'archived_by' - 'archive_reason',"
            "     updated_at = $3"
            " WHERE id = $1 AND user_id = $2",
            str(session_id), str(user_id), now)
    changed = str(status or "").strip().endswith(" 1")
    if changed:
        await _log(session_id, user_id, "package_unarchived",
                   {"archived_at": session.get(ARCHIVED_KEY)})
    return {"archived": False, "changed": changed}


async def _log(session_id: str, user_id: str, event_type: str, data: dict) -> None:
    try:
        from services.audit_service import log_audit_event
        await log_audit_event(session_id, user_id, event_type, data)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("archive: audit event %s not logged for %s: %s",
                       event_type, session_id, ex)


# ── Retention SQL (scheduler_service.run_retention_cleanup) ─────────────────
# $1 = the active cutoff (updated_at), $2 = the archive cutoff (archived_at).
# An archived_at that is not an ISO time is never "expired" - a package is
# never deleted on a value we cannot read.
EXPIRED_PACKAGE_IDS_SQL = (
    "SELECT id FROM processing_sessions"
    " WHERE ((data->>'archived_at') IS NULL AND updated_at < $1)"
    "    OR ((data->>'archived_at') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'"
    "        AND (data->>'archived_at') < $2)"
)

# $1 = idle cutoff (now - PACKAGE_AUTO_ARCHIVE_DAYS), $2 = active cutoff,
# $3 = now. Only packages still inside the active retention. A package idle a
# whole day cannot have a generation in flight (a run takes minutes and writes
# the row when it starts), so no run is archived under its own feet.
AUTO_ARCHIVE_SQL = (
    "UPDATE processing_sessions"
    " SET data = data || jsonb_build_object('archived_at', $3::text,"
    "                                       'archived_by', 'system',"
    "                                       'archive_reason', 'idle')"
    " WHERE (data->>'archived_at') IS NULL"
    "   AND updated_at < $1 AND updated_at >= $2"
)
