"""fact_history.py - the E&O fact lineage (Brent's V2 list, 27 Oct 2026).

Brent: "Continue expanding E&O fact lineage (source, confidence, AI or human,
timestamps, edited from/to, etc.)". `fact_lineage.py` answers WHERE a fact's
CURRENT value is printed (document + page, computed at read time). This module
answers the other half: every value a fact has ever held on a package, who or
what put it there, from what to what, and when. Append-only, one row per change.

THE DOORS. Every value a package's facts hold is written by exactly two
functions in `repositories/session_repository.py`:

  * `new_processing_session` - the first extraction of an upload;
  * `upd_processing_session` - everything after: a re-merge (documents added,
    reclassified, excluded), a producer fix (resolve-issue, a recommendation
    card), the client's questionnaire, an editor write-back, a Data Consistency
    confirm, a table save, the explicit retractions in `delete_facts`.

Both call `record_fact_changes` with the facts BEFORE and AFTER the write, on the
same connection and inside the same transaction as the value itself (a
SAVEPOINT, so a lineage failure never undoes the write). Nothing upstream has to
remember to call it. `tests/test_lane_c_27oct.py` fails the build on any other
SQL that writes `processing_sessions` without being listed there with its reason.

WHAT IS A CHANGE. A fact's (value, source, person-confirmed) triple changed:
  set            empty -> a value
  changed        one value -> another
  removed        a value -> empty (a retraction, an excluded document)
  confirmed      same value, now confirmed by a person (Data Consistency pick,
                 the client's "this is correct")
  source_changed same value, a different source label
A write that changes none of these writes no row - an envelope annotation
(verified_in_text, value_state) is not a change of value.

WHAT IS NOT TRACKED. Underscore sidecars (machinery: `_scoped`,
`_uw_conflicted_keys`, ...) except the person-written ones in
`PERSON_SIDECARS`; `dec_page_entries` (the internal declarations index, purged
after generation); a BARE Python boolean (pipeline bookkeeping by construction -
extraction wraps every real boolean answer in an envelope; the E&O export skips
them for the same reason).

WHO. `RequestContextMiddleware` gives each HTTP request a mutable dict; the
auth dependency notes the signed-in user on it (`note_user`), the client
questionnaire routes note the questionnaire (`note_client`). A write outside any
request (the worker, the scheduler) is the system. `acting(...)` overrides the
action / actor for a block of code that knows better.

KIND (the "AI or human" axis), read off the NEW value's own envelope first:
ai / document / derived / producer / client / confirmed, else from the actor.

PII. `from_value`, `to_value` and `sources` are Fernet ciphertext
(`utils.crypto`), the same as the session's facts. Fact keys, labels and
timestamps are plaintext so the history can be listed without decrypting.
Retention: values are blanked when the package's facts are purged
(`scheduler_service.run_facts_retention`), rows go with the package.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

TABLE = "fact_lineage"

# ── Vocabulary ──────────────────────────────────────────────────────────────
KIND_AI = "ai"
KIND_DOCUMENT = "document"
KIND_DERIVED = "derived"
KIND_PRODUCER = "producer"
KIND_CLIENT = "client"
KIND_CONFIRMED = "confirmed"
KIND_SYSTEM = "system"
KINDS = frozenset({KIND_AI, KIND_DOCUMENT, KIND_DERIVED, KIND_PRODUCER,
                   KIND_CLIENT, KIND_CONFIRMED, KIND_SYSTEM})
KIND_LABELS = {
    KIND_AI: "AI extraction",
    KIND_DOCUMENT: "Read from a document",
    KIND_DERIVED: "Calculated by Primble",
    KIND_PRODUCER: "Entered by the producer",
    KIND_CLIENT: "Entered by the client",
    KIND_CONFIRMED: "Confirmed by a person",
    KIND_SYSTEM: "System",
}

CHANGE_SET = "set"
CHANGE_CHANGED = "changed"
CHANGE_REMOVED = "removed"
CHANGE_CONFIRMED = "confirmed"
CHANGE_SOURCE = "source_changed"
CHANGE_TYPES = frozenset({CHANGE_SET, CHANGE_CHANGED, CHANGE_REMOVED,
                          CHANGE_CONFIRMED, CHANGE_SOURCE})

ACTOR_PRODUCER = "producer"
ACTOR_CLIENT = "client"
ACTOR_SYSTEM = "system"

# Source labels the pipeline writes on envelopes, mapped to the kind axis.
# Unknown labels fall through to the confidence and then the actor.
_KIND_BY_SOURCE = {
    "producer": KIND_PRODUCER, "manual": KIND_PRODUCER, "card": KIND_PRODUCER,
    "table": KIND_PRODUCER, "account": KIND_PRODUCER,
    "client_arq": KIND_CLIENT,
    "user_confirmed": KIND_CONFIRMED, "confirmed": KIND_CONFIRMED,
    "derived": KIND_DERIVED,
    "ai": KIND_AI,
    "dec_entry": KIND_DOCUMENT, "policy_doc_text": KIND_DOCUMENT,
    "document_text": KIND_DOCUMENT, "coverage_blocks": KIND_DOCUMENT,
    "documents": KIND_DOCUMENT, "document_amendment": KIND_DOCUMENT,
    "subject_labels": KIND_DOCUMENT, "content": KIND_DOCUMENT,
}

# Sidecars a PERSON writes (the policies table edits). Every other underscore
# key is machinery and is not a fact.
PERSON_SIDECARS = frozenset({"_producer_policy_lines"})
_SKIP_KEYS = frozenset({"dec_page_entries"})

# A value longer than this (a 40-vehicle schedule) is stored as a digest plus
# its head - the full table is already on the session and on the forms.
_MAX_VALUE_CHARS = 20000
# One write never records more than this many rows (a pathological payload).
_MAX_ROWS_PER_WRITE = 2000
# Document attribution is computed only for writes this size or smaller
# (a first extraction is ~200 facts); a bigger write keeps kind + source.
_ATTRIBUTE_MAX_FACTS = 600
_MAX_SOURCES = 3

# Route templates whose writes re-read the documents, and those that generate
# forms - they decide the kind of a bare (envelope-less) value.
_DOCUMENT_ACTIONS = frozenset({
    "POST /api/upload-declaration",
    "POST /api/session/{session_id}/documents",
    "POST /api/document/reclassify",
    "POST /api/submission-integrity/resolve",
})
_GENERATION_ACTIONS = frozenset({
    "POST /api/select-forms-bulk",
    "POST /api/select-form",
    "POST /api/lite/generate-internal/{session_id}",
    "POST /api/clarity/analyze/{session_id}",
})

# Display words for the triggering action. A route not listed shows as
# "METHOD /path" - never blank.
ACTION_LABELS = {
    "POST /api/upload-declaration": "Documents uploaded and read",
    "POST /api/session/{session_id}/documents": "Documents added",
    "POST /api/session/{session_id}/documents/suggestions/keep": "New document value kept",
    "POST /api/session/{session_id}/documents/add-form": "Form added for a new document",
    "POST /api/document/reclassify": "Document type changed or excluded",
    "POST /api/submission-integrity/resolve": "Submission integrity review",
    "POST /api/underwriting/confirm-value": "Data Consistency value confirmed",
    "POST /api/underwriting/confirm-value-in-editor": "Data Consistency value confirmed (form editor)",
    "POST /api/client-answer/resolve": "Held client answer decided",
    "POST /api/select-forms-bulk": "Forms generated",
    "POST /api/select-form": "Form generated",
    "POST /api/lite/generate-internal/{session_id}": "Score generated",
    "POST /api/clarity/analyze/{session_id}": "Package analysed again",
    "POST /api/update-pdf": "Form editor save",
    "POST /api/audit/answer": "Recommendation answered",
    "POST /api/audit/reopen-recommendation": "Recommendation reopened",
    "POST /api/audit/resolve-issue": "Issue fixed",
    "POST /api/audit/reopen-issue": "Issue fix taken back",
    "PUT /api/arq/schedules/{session_id}": "Table saved",
    "POST /api/arq/submit/{token}": "Client questionnaire submitted",
    "POST /api/questionnaire/{session_id}/answer": "Narrative questionnaire answered",
    "POST /api/questionnaire/{session_id}/narrative/approve": "Carrier narrative approved",
    "POST /api/policy-lines/{session_id}/edit": "Policy line edited",
    "POST /api/policy-lines/{session_id}/add": "Policy line added",
    "DELETE /api/policy-lines/{session_id}/added/{line_id}": "Policy line removed",
    "POST /api/policy-lines/{session_id}/prior-other": "Prior carrier column chosen",
    "POST /api/policy-lines/{session_id}/add-form": "Form added from the policies table",
    "POST /api/session/{session_id}/marketing-reason": "Marketing reason saved",
    "POST /api/apply-signature/{session_id}/{form_id}": "Signature applied",
    "POST /api/applicant-sign/sign/{token}": "Applicant signed",
    "system": "System",
}

# ── Who is writing ──────────────────────────────────────────────────────────
_REQUEST: contextvars.ContextVar = contextvars.ContextVar("fact_history_request", default=None)
_ACTING: contextvars.ContextVar = contextvars.ContextVar("fact_history_acting", default=None)


class RequestContextMiddleware:
    """Pure ASGI: one mutable dict per HTTP request, shared by everything that
    request runs (dependencies, the route, its background tasks and the tasks
    it spawns - they inherit the context, and the dict is the same object, so a
    user noted by the auth dependency is visible to a write made later)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _REQUEST.set({"scope": scope})
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST.reset(token)


def request_context() -> Optional[dict]:
    return _REQUEST.get()


def request_method() -> Optional[str]:
    ctx = _REQUEST.get()
    if not isinstance(ctx, dict):
        return None
    return str((ctx.get("scope") or {}).get("method") or "").upper() or None


def note_user(user: Any) -> None:
    """The signed-in user of this request (called by the auth dependency).
    The FIRST user noted wins - a nested lookup never re-labels the request."""
    ctx = _REQUEST.get()
    if not isinstance(ctx, dict) or not isinstance(user, dict):
        return
    uid = user.get("id")
    if uid is not None and not ctx.get("user_id"):
        ctx["user_id"] = str(uid)


def note_client(arq_id: Any) -> None:
    """This request is the client acting through their questionnaire link."""
    ctx = _REQUEST.get()
    if isinstance(ctx, dict) and arq_id:
        ctx["client_id"] = str(arq_id)


@contextmanager
def acting(action: Optional[str] = None, actor_type: Optional[str] = None,
           actor_id: Optional[str] = None):
    """Name the action / actor for the writes inside the block."""
    token = _ACTING.set({"action": action, "actor_type": actor_type, "actor_id": actor_id})
    try:
        yield
    finally:
        _ACTING.reset(token)


def _route_template(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None) or scope.get("path") or ""
    method = str(scope.get("method") or "").upper()
    return f"{method} {path}".strip()


def _is_client_route(scope: dict) -> bool:
    route = scope.get("route")
    path = getattr(route, "path", None) or scope.get("path") or ""
    return "{token}" in path and (path.startswith("/api/arq/")
                                  or path.startswith("/api/applicant-sign/"))


def current_actor() -> dict:
    """{actor_type, actor_id, action} for a write made now."""
    out = {"actor_type": ACTOR_SYSTEM, "actor_id": None, "action": "system"}
    ctx = _REQUEST.get()
    if isinstance(ctx, dict):
        scope = ctx.get("scope") or {}
        out["action"] = _route_template(scope) or "system"
        if ctx.get("client_id"):
            out.update(actor_type=ACTOR_CLIENT, actor_id=ctx["client_id"])
        elif ctx.get("user_id"):
            out.update(actor_type=ACTOR_PRODUCER, actor_id=ctx["user_id"])
        elif _is_client_route(scope):
            out["actor_type"] = ACTOR_CLIENT
    override = _ACTING.get()
    if isinstance(override, dict):
        for k in ("action", "actor_type", "actor_id"):
            if override.get(k):
                out[k] = override[k]
    return out


def action_label(action: Optional[str]) -> str:
    a = str(action or "").strip()
    if not a:
        return "System"
    return ACTION_LABELS.get(a, a)


# ── What changed ────────────────────────────────────────────────────────────

def _envelope(raw: Any) -> Optional[dict]:
    return raw if isinstance(raw, dict) and "value" in raw else None


def _value(raw: Any) -> Any:
    env = _envelope(raw)
    return env.get("value") if env is not None else raw


def _empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, dict, set)):
        return not v
    return False


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str, ensure_ascii=False)


def tracked_key(key: Any) -> bool:
    """Is this facts key a fact whose history is kept?"""
    if not isinstance(key, str) or not key:
        return False
    if key in _SKIP_KEYS:
        return False
    if key.startswith("_"):
        return key in PERSON_SIDECARS
    return True


def _signature(raw: Any):
    """(value, source, person-confirmed) - what a change is measured on. None =
    the fact holds nothing (absent, blank, or a bare bookkeeping boolean)."""
    if isinstance(raw, bool):
        return None
    v = _value(raw)
    if isinstance(v, bool) and _envelope(raw) is None:
        return None
    if _empty(v):
        return None
    env = _envelope(raw) or {}
    return (_canon(v),
            str(env.get("source") or "").strip().lower(),
            str(env.get("evidence_state") or "").strip().lower() == "user_confirmed")


def _facts_dict(facts: Any) -> dict:
    """A facts mapping, or {} for none / an unreadable value / a retention
    tombstone ({"purged": true, ...} is not a set of facts)."""
    if not isinstance(facts, dict):
        return {}
    if facts.get("purged") is True:
        return {}
    return facts


def diff_facts(before: Any, after: Any) -> List[dict]:
    """Every tracked fact whose value, source or confirmation differs.
    Deterministic order (sorted keys), so a write's rows have stable ordinals."""
    b, a = _facts_dict(before), _facts_dict(after)
    changes: List[dict] = []
    for key in sorted(set(b) | set(a)):
        if not tracked_key(key):
            continue
        old, new = b.get(key), a.get(key)
        so, sn = _signature(old), _signature(new)
        if so == sn:
            continue
        if so is None:
            ctype = CHANGE_SET
        elif sn is None:
            ctype = CHANGE_REMOVED
        elif so[0] == sn[0]:
            ctype = CHANGE_CONFIRMED if (sn[2] and not so[2]) else CHANGE_SOURCE
        else:
            ctype = CHANGE_CHANGED
        changes.append({"fact_key": key, "change_type": ctype,
                        "old": None if so is None else old,
                        "new": None if sn is None else new})
    return changes


def _kind_from_actor(actor: dict, removal: bool = False) -> str:
    action = str(actor.get("action") or "")
    atype = actor.get("actor_type")
    if atype == ACTOR_CLIENT:
        return KIND_CLIENT
    if action in _DOCUMENT_ACTIONS:
        return KIND_DOCUMENT
    if atype == ACTOR_SYSTEM or action in _GENERATION_ACTIONS:
        return KIND_SYSTEM if removal else KIND_DERIVED
    if atype == ACTOR_PRODUCER:
        return KIND_PRODUCER
    return KIND_SYSTEM


def kind_of(raw: Any, actor: dict) -> str:
    """The provenance of a NEW value: its own envelope first (a person's
    confirmation of a document's value is `confirmed`; a person's own entry
    stays theirs), then its confidence, then who wrote it."""
    env = _envelope(raw)
    if env is not None:
        src = str(env.get("source") or "").strip().lower()
        ev = str(env.get("evidence_state") or "").strip().lower()
        kind = _KIND_BY_SOURCE.get(src)
        if ev == "user_confirmed" and kind not in (KIND_PRODUCER, KIND_CLIENT):
            return KIND_CONFIRMED
        if kind:
            return kind
        conf = str(env.get("confidence") or "").strip().lower()
        if conf in ("ai_high", "ai_low"):
            return KIND_AI
        if conf == "client_arq":
            return KIND_CLIENT
        if ev == "derived":
            return KIND_DERIVED
    return _kind_from_actor(actor)


# ── Sealing values (PII) ────────────────────────────────────────────────────

def _seal_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    from utils.crypto import encrypt_field
    return encrypt_field(text)


def seal_value(value: Any) -> Optional[str]:
    """Fernet ciphertext of the value's JSON, or None for an empty value."""
    if _empty(value):
        return None
    text = _canon(value)
    if len(text) > _MAX_VALUE_CHARS:
        text = _canon({
            "_truncated": True,
            "chars": len(text),
            "rows": len(value) if isinstance(value, (list, tuple)) else None,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "head": text[:2000],
        })
    return _seal_text(text)


def open_value(token: Optional[str]):
    """(value, readable) - the stored value, decrypted. An undecryptable token
    (a rotated key) is (None, False), never an exception."""
    if not token:
        return None, True
    try:
        from utils.crypto import decrypt_field
        text = decrypt_field(token)
    except Exception:                                          # noqa: BLE001
        return None, False
    try:
        return json.loads(text), True
    except (TypeError, ValueError):
        return text, True


def _attribute(fact_key: str, raw: Any, doc_index: list) -> Optional[list]:
    try:
        from services.fact_lineage import sources_for_fact
        found = sources_for_fact(fact_key, raw, doc_index) or []
    except Exception:                                          # noqa: BLE001
        return None
    out = [{k: s.get(k) for k in ("doc_id", "filename", "page", "method", "rows")
            if s.get(k) is not None}
           for s in found[:_MAX_SOURCES] if isinstance(s, dict)]
    return out or None


def build_rows(session_id: str, owner_id: Optional[str], changes: List[dict],
               actor: dict, docs: Optional[list] = None,
               now: Optional[str] = None) -> List[tuple]:
    """INSERT parameter tuples for `changes` (see _INSERT_SQL's column order)."""
    now = now or datetime.now(timezone.utc).isoformat()
    write_id = uuid.uuid4().hex
    changes = changes[:_MAX_ROWS_PER_WRITE]
    kinds = []
    for ch in changes:
        if ch["change_type"] == CHANGE_REMOVED:
            kinds.append(_kind_from_actor(actor, removal=True))
        else:
            kinds.append(kind_of(ch["new"], actor))
    doc_index = None
    if (docs and len(changes) <= _ATTRIBUTE_MAX_FACTS
            and any(k in (KIND_AI, KIND_DOCUMENT) for k in kinds)):
        try:
            from services.fact_lineage import build_doc_index
            doc_index = build_doc_index(docs)
        except Exception:                                      # noqa: BLE001
            doc_index = None
    rows: List[tuple] = []
    for i, (ch, kind) in enumerate(zip(changes, kinds)):
        old, new = ch["old"], ch["new"]
        env_old, env_new = _envelope(old) or {}, _envelope(new) or {}
        sources = None
        if doc_index and kind in (KIND_AI, KIND_DOCUMENT) and ch["change_type"] != CHANGE_REMOVED:
            sources = _attribute(ch["fact_key"], new, doc_index)
        rows.append((
            f"fl_{uuid.uuid4().hex}",
            str(session_id),
            str(owner_id) if owner_id else None,
            ch["fact_key"],
            ch["change_type"],
            kind,
            seal_value(_value(old)),
            seal_value(_value(new)),
            (str(env_old.get("source") or "").strip() or None),
            (str(env_new.get("source") or "").strip() or None),
            (str(env_new.get("confidence") or "").strip() or None),
            (str(env_new.get("evidence_state") or "").strip() or None),
            _seal_text(_canon(sources)) if sources else None,
            actor.get("actor_type"),
            (str(actor["actor_id"]) if actor.get("actor_id") else None),
            (str(actor.get("action") or "system"))[:200],
            write_id,
            i,
            now,
        ))
    return rows


_COLUMNS = ("id, session_id, user_id, fact_key, change_type, kind, from_value, "
            "to_value, from_source, to_source, confidence, evidence_state, sources, "
            "actor_type, actor_id, action, write_id, ordinal, created_at")
_INSERT_SQL = (f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES "
               "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)")


async def record_fact_changes(conn, session_id: str, owner_id: Optional[str],
                              before: Any, after: Any, *,
                              docs: Optional[list] = None) -> int:
    """Append one lineage row per changed fact. Called by the two write doors
    with their own connection, inside their transaction; the insert runs in a
    SAVEPOINT so a missing table or a bad row rolls back only the lineage.
    Never raises; returns the number of rows written."""
    try:
        changes = diff_facts(before, after)
    except Exception as ex:                                    # noqa: BLE001
        logger.error("fact lineage: diff failed for %s: %s", session_id, ex, exc_info=True)
        return 0
    if not changes:
        return 0
    insert = getattr(conn, "executemany", None)
    if insert is None:              # a test double without it - nothing to write to
        return 0
    try:
        actor = current_actor()
        if docs:
            # Document attribution is CPU work linear in the documents' size
            # (~0.3 s for 260 facts over 720k chars, measured) - run it off the
            # event loop, which this write holds a row lock inside (review R4).
            import asyncio
            rows = await asyncio.to_thread(build_rows, session_id, owner_id, changes,
                                           actor, docs)
        else:
            rows = build_rows(session_id, owner_id, changes, actor)
        async with conn.transaction():
            await insert(_INSERT_SQL, rows)
        return len(rows)
    except Exception as ex:                                    # noqa: BLE001
        logger.error("fact lineage: %d change(s) for %s not recorded: %s",
                     len(changes), session_id, ex, exc_info=True)
        return 0


# ── Reading it back ─────────────────────────────────────────────────────────

def display_value(value: Any, limit: int = 200) -> str:
    """One readable line for a stored value."""
    if value is None:
        return ""
    if isinstance(value, dict) and value.get("_truncated"):
        rows = value.get("rows")
        return f"[{rows} row(s)]" if rows else "[long value]"
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} row(s)]"
    if isinstance(value, dict):
        text = _canon(value)
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def decode_row(row: Any) -> dict:
    r = dict(row)
    old, ok_old = open_value(r.get("from_value"))
    new, ok_new = open_value(r.get("to_value"))
    sources, _ok = open_value(r.get("sources"))
    purged = bool(r.get("values_purged"))
    kind = r.get("kind") or KIND_SYSTEM
    return {
        "fact_key": r.get("fact_key"),
        "change_type": r.get("change_type"),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "from": old,
        "to": new,
        "from_display": display_value(old),
        "to_display": display_value(new),
        "from_source": r.get("from_source"),
        "to_source": r.get("to_source"),
        "confidence": r.get("confidence"),
        "evidence_state": r.get("evidence_state"),
        "sources": sources if isinstance(sources, list) else [],
        "actor_type": r.get("actor_type"),
        "actor_id": r.get("actor_id"),
        "action": r.get("action"),
        "action_label": action_label(r.get("action")),
        "at": r.get("created_at"),
        "values_purged": purged,
        "unreadable": not (ok_old and ok_new),
    }


_SELECT = (f"SELECT fact_key, change_type, kind, from_value, to_value, from_source, "
           f"to_source, confidence, evidence_state, sources, actor_type, actor_id, "
           f"action, created_at, ordinal, values_purged FROM {TABLE}")


async def fact_history(session_id: str, fact_key: Optional[str] = None,
                       limit: int = 500) -> List[dict]:
    """A package's lineage, oldest first; one fact's when `fact_key` is given.
    Never raises - an unreadable store returns [] (logged)."""
    limit = max(1, min(int(limit or 500), 20000))
    try:
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            if fact_key:
                rows = await conn.fetch(
                    _SELECT + " WHERE session_id=$1 AND fact_key=$2"
                    " ORDER BY created_at ASC, ordinal ASC LIMIT $3",
                    session_id, fact_key, limit)
            else:
                rows = await conn.fetch(
                    _SELECT + " WHERE session_id=$1"
                    " ORDER BY created_at ASC, ordinal ASC LIMIT $2",
                    session_id, limit)
    except Exception as ex:                                    # noqa: BLE001
        logger.error("fact lineage: read failed for %s: %s", session_id, ex, exc_info=True)
        return []
    return [decode_row(r) for r in rows]


def actor_ids_in(rows: Iterable[dict]) -> set:
    return {str(r.get("actor_id")) for r in rows or []
            if r.get("actor_type") == ACTOR_PRODUCER and r.get("actor_id")}


def who(row: dict, actors: Optional[dict] = None) -> str:
    """The person (or system) behind a row, in words."""
    atype = row.get("actor_type")
    if atype == ACTOR_PRODUCER:
        person = (actors or {}).get(str(row.get("actor_id") or "")) or {}
        name = person.get("name") or person.get("email")
        return f"Producer ({name})" if name else "Producer"
    if atype == ACTOR_CLIENT:
        return "Client (questionnaire)"
    return "System"


def export_rows(rows: List[dict], actors: Optional[dict] = None) -> List[dict]:
    """The E&O record's FACT HISTORY section: display strings, no raw values."""
    out = []
    for r in rows or []:
        out.append({
            "fact": r.get("fact_key"),
            "change_type": r.get("change_type"),
            "from": r.get("from_display", ""),
            "to": r.get("to_display", ""),
            "kind": r.get("kind"),
            "how": r.get("kind_label"),
            "who": who(r, actors),
            "actor_type": r.get("actor_type"),
            "action": r.get("action_label"),
            "confidence": r.get("confidence"),
            "source": r.get("to_source") or r.get("from_source"),
            "evidence": r.get("sources") or [],
            "at": r.get("at"),
            "values_purged": r.get("values_purged", False),
        })
    return out


# ── Retention ───────────────────────────────────────────────────────────────
# The ONLY statements that change a lineage row after it is written. A package
# whose facts the retention policy purged keeps the record THAT values changed
# (who, when, how) but not the values themselves.
# A tombstone written before 27 Oct 2026 is stored as a JSON STRING holding the
# object's text (the pool's codec encoded the already-encoded JSON); a newer one
# is an object. Both are found - the string by its fixed prefix, never by a cast
# (a cast of an encrypted "enc:..." blob would fail the statement).
PURGE_VALUES_SQL = (
    f"UPDATE {TABLE} SET from_value = NULL, to_value = NULL, sources = NULL,"
    " values_purged = TRUE"
    " WHERE values_purged IS NOT TRUE"
    "   AND session_id IN (SELECT id FROM processing_sessions"
    "                      WHERE data->'facts'->>'purged' = 'true'"
    "                         OR (jsonb_typeof(data->'facts') = 'string'"
    "                             AND (data->>'facts') LIKE '{\"purged\": true%'))"
)
