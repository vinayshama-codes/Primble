"""The answers a person typed that the deterministic readers could not read.

CLAUDE.md, "Answer Interpretation", GAP 2: the owner declined an LLM layer for
reading what a person types (latency, determinism), so the only evidence of
whether `services/answer_semantics.py` is missing real phrasings is the list
of answers it could not read (`_record_unreadable`). That list lived in
process memory, died with every restart and was read by nobody. This module
keeps it in the database, one counter per phrasing, and an admin route lists
the most common ones by fact (`routes/admin_routes.py`).

WHAT IS STORED - AND WHAT IS NOT (decided 27 Oct 2026, Lane B item 5). A typed
answer can be anything - a payroll, a phone number, a person's name - so the
RAW TEXT IS NEVER STORED. What is kept is its SHAPE (`shape_of`): lower-cased,
every digit run a "#", an e-mail address "<email>", a token mixing letters and
digits (a VIN, a policy number, an ID) "<id>", capped at 80 characters. The
shape is what a new reading rule is written from ("about # k", "# per year",
"approx $# m") and it carries no amount, date, phone or identifier. The words
that remain are still a person's words, so the shape is ENCRYPTED at rest
(`utils.crypto.encrypt_field`, the field-level key) and the counter row is
keyed by a SHA-256 of fact + kind + shape - so the same phrasing counts up in
one row without the plain shape ever being written.

WHY A BUFFER AND AN EXPLICIT FLUSH. `interpret_answer` is pure and sync and is
called from previews, probes and three request doors; it may not schedule an
asyncio task (the build fails on a sync function that does -
`test_no_sync_function_schedules_an_asyncio_task`). So the reader only NOTES
a fall-through here (`note`, a bounded in-memory buffer), and the async person
doors flush it after they have read the answer (`flush_pending`): the producer
card and the inline resolution (`audit_routes`), the client questionnaire
submit and apply (`arq_service`), the narrative questionnaire
(`questionnaire_routes`). One request that reads the same answer several times
counts it once (`flush_pending` folds duplicates in a batch).
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "answer_fallthroughs"
_SHAPE_MAX = 80
_BUFFER_MAX = 500

_PENDING: Deque[Tuple[str, str, str]] = deque(maxlen=_BUFFER_MAX)
_LOCK = threading.Lock()
# A reading that is not a person's ANSWER (the follow-up preview reads what is
# being typed before it is saved) is not counted: the save that follows is.
_NOT_COUNTED: ContextVar[bool] = ContextVar("unread_answers_not_counted", default=False)


@contextmanager
def not_counted():
    """Readings inside this block note nothing (`asyncio.to_thread` carries
    the flag into its thread - it copies the context)."""
    token = _NOT_COUNTED.set(True)
    try:
        yield
    finally:
        _NOT_COUNTED.reset(token)

_EMAIL_RE = re.compile(r"\S+@\S+")
_MIXED_RE = re.compile(r"\b(?=[a-z\-]*\d)(?=[\d\-]*[a-z])[a-z0-9\-]{4,}\b")
_DIGITS_RE = re.compile(r"\d+(?:[.,]\d+)*")


def shape_of(raw: Any) -> str:
    """The phrasing of a typed answer with everything identifying taken out:
    lower-cased, e-mails "<email>", letter-digit tokens "<id>", digit runs "#",
    spaces collapsed, at most 80 characters. "" for an empty answer."""
    s = re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip().lower()
    if not s:
        return ""
    s = _EMAIL_RE.sub("<email>", s)
    s = _MIXED_RE.sub("<id>", s)
    s = _DIGITS_RE.sub("#", s)
    return s[:_SHAPE_MAX]


def shape_key(fact_key: str, kind: str, shape: str) -> str:
    """The counter row's key - a digest, so the plain shape is never a key."""
    return hashlib.sha256(f"{fact_key}\x1f{kind}\x1f{shape}".encode("utf-8")).hexdigest()


def note(fact_key: Any, kind: Any, raw: Any) -> None:
    """Record one fall-through for the next flush. Sync, never raises, never
    blocks on I/O, never keeps the raw text."""
    try:
        if _NOT_COUNTED.get():
            return
        shape = shape_of(raw)
        if not shape:
            return
        with _LOCK:
            _PENDING.append((str(fact_key or "")[:120], str(kind or "")[:40], shape))
    except Exception:                                          # noqa: BLE001
        pass


def pending_count() -> int:
    with _LOCK:
        return len(_PENDING)


def _take_pending() -> Dict[Tuple[str, str, str], int]:
    """Empty the buffer into {(fact, kind, shape): 1} - one count per
    distinct phrasing per flush (a request re-reads the same answer)."""
    with _LOCK:
        items = list(_PENDING)
        _PENDING.clear()
    return {item: 1 for item in items}


async def flush_pending() -> int:
    """Write the buffered fall-throughs (one upsert per phrasing). Returns how
    many rows were written; 0 when there is nothing to write or the store is
    unavailable (the entries are put back, so a later flush still counts them).
    Never raises - an admin log must never fail a person's request."""
    batch = _take_pending()
    if not batch:
        return 0
    try:
        from config.database import get_pool
        from utils.crypto import encrypt_field
        now = datetime.now(timezone.utc).isoformat()
        async with get_pool().acquire() as conn:
            for (fact, kind, shape), count in batch.items():
                await conn.execute(
                    f"""
                    INSERT INTO {TABLE}
                        (shape_hash, fact_key, kind, shape_enc, seen_count, first_seen, last_seen)
                    VALUES ($1, $2, $3, $4, $5, $6, $6)
                    ON CONFLICT (shape_hash) DO UPDATE
                    SET seen_count = {TABLE}.seen_count + EXCLUDED.seen_count,
                        last_seen  = EXCLUDED.last_seen
                    """,
                    shape_key(fact, kind, shape), fact, kind,
                    encrypt_field(shape), int(count), now,
                )
        return len(batch)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("unread answers: flush skipped (%s) - kept for the next flush", exc)
        with _LOCK:
            for item in batch:
                _PENDING.append(item)
        return 0


async def top_unread(limit: int = 50, fact_key: Optional[str] = None) -> List[dict]:
    """The most common unread phrasings, most seen first: fact, kind, shape
    (decrypted for the admin), count, first / last seen."""
    try:
        limit = max(1, min(int(limit or 50), 500))
    except (TypeError, ValueError):
        limit = 50
    from config.database import get_pool
    from utils.crypto import decrypt_field_soft
    async with get_pool().acquire() as conn:
        if fact_key:
            rows = await conn.fetch(
                f"SELECT fact_key, kind, shape_enc, seen_count, first_seen, last_seen "
                f"FROM {TABLE} WHERE fact_key = $1 "
                f"ORDER BY seen_count DESC, last_seen DESC LIMIT $2",
                str(fact_key), limit)
        else:
            rows = await conn.fetch(
                f"SELECT fact_key, kind, shape_enc, seen_count, first_seen, last_seen "
                f"FROM {TABLE} ORDER BY seen_count DESC, last_seen DESC LIMIT $1", limit)
    out = []
    for r in rows:
        r = dict(r)
        out.append({
            "fact": r.get("fact_key"),
            "kind": r.get("kind"),
            "shape": decrypt_field_soft(r.get("shape_enc")),
            "count": int(r.get("seen_count") or 0),
            "first_seen": r.get("first_seen"),
            "last_seen": r.get("last_seen"),
        })
    return out


def by_fact(rows: List[dict]) -> Dict[str, List[dict]]:
    """Group `top_unread` rows by fact, each fact's phrasings most seen first."""
    out: Dict[str, List[dict]] = {}
    for r in rows or []:
        out.setdefault(str(r.get("fact") or ""), []).append(r)
    for v in out.values():
        v.sort(key=lambda r: -int(r.get("count") or 0))
    return out
