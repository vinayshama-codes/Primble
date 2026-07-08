"""progress_tracker.py

Live per-file upload progress side-channel (Figure 1 feedback).

The upload request is a single synchronous call that processes files in a loop
(OCR → extract → normalize → score → form-ready). To show TRUE progress instead
of a timed spinner, the pipeline writes each phase transition to a fast,
throwaway side-channel keyed by a client-generated ``progress_token``, and a
lightweight poll endpoint (``GET /api/upload-progress/{token}``) reads it back.

Why a side-channel and NOT the processing_sessions row
------------------------------------------------------
The session row is heavy (facts, raw text, flags) and is written with an
optimistic-locking ``SELECT ... FOR UPDATE`` at real milestones. Writing a
progress tick to it several times per file per upload would (a) contend on that
lock with the actual result write and (b) churn the row (Postgres rewrites the
whole tuple on every UPDATE). So progress lives in Redis — cheap, non-locking,
auto-expiring — and the database is only touched at the milestones it already
writes today. If Redis is down (single-worker dev), an in-process dict is used.

Design notes
------------
* BEST-EFFORT: every write/read is wrapped so a progress failure can NEVER break
  the upload. Progress is a cosmetic overlay; extraction is the real work.
* SINGLE WRITER per token (the upload request), so the reporter keeps the full
  state in memory and writes it WHOLESALE each tick — no read-modify-write, no
  races against itself or across workers.
* TTL-bounded: a token expires after ``_PROGRESS_TTL`` seconds. A user who
  returns hours later reads the finished submission from their history (the
  session row), not this ephemeral channel.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How long a progress record lives. Comfortably longer than the slowest upload,
# short enough that abandoned tokens evaporate on their own.
_PROGRESS_TTL = int(os.getenv("UPLOAD_PROGRESS_TTL_SECONDS", "1800"))  # 30 min

_WEB_CONCURRENCY = int(os.getenv("WEB_CONCURRENCY", "1"))

# Ordered phase vocabulary (Figure 1). The first four are PER-FILE; the last
# three are PACKAGE-level (they run once over the merged package, not per file).
FILE_PHASES = ("uploaded", "parsed", "extracting", "extracted")
PACKAGE_PHASES = ("normalized", "scored", "form_ready")


# ── Redis connection (optional; mirrors utils.rate_limiter) ───────────────────
try:
    import redis.asyncio as _aioredis
    from redis.asyncio.connection import ConnectionPool
    from config.settings import REDIS_URL as _REDIS_URL
    _redis = _aioredis.Redis(connection_pool=ConnectionPool.from_url(
        _REDIS_URL,
        max_connections=10,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        decode_responses=True,
    ))
    logger.info("progress_tracker: Redis connected (%s)", _REDIS_URL)
except Exception as _redis_init_err:  # pragma: no cover - depends on env
    logger.warning(
        "progress_tracker: Redis unavailable (%s) — in-process progress active "
        "(safe only for WEB_CONCURRENCY=1)", _redis_init_err,
    )
    _redis = None

# In-process fallback for single-worker dev: {token: (payload_json, expiry_ts)}.
_mem: Dict[str, tuple] = {}


def _key(token: str) -> str:
    return f"upload_progress:{token}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def write_progress(token: str, payload: dict) -> None:
    """Persist the full progress payload for ``token``. Best-effort — never raises."""
    if not token:
        return
    try:
        blob = json.dumps(payload, default=str)
    except Exception:  # pragma: no cover - payload is always plain data
        return
    if _redis is not None:
        try:
            await _redis.set(_key(token), blob, ex=_PROGRESS_TTL)
            return
        except Exception as exc:  # pragma: no cover - transient Redis issue
            logger.debug("progress_tracker: Redis write failed, using memory: %s", exc)
    _mem[_key(token)] = (blob, time.time() + _PROGRESS_TTL)


async def read_progress(token: str) -> Optional[dict]:
    """Return the progress payload for ``token``, or None. Best-effort — never raises."""
    if not token:
        return None
    if _redis is not None:
        try:
            blob = await _redis.get(_key(token))
            return json.loads(blob) if blob else None
        except Exception as exc:  # pragma: no cover - transient Redis issue
            logger.debug("progress_tracker: Redis read failed, using memory: %s", exc)
    entry = _mem.get(_key(token))
    if not entry:
        return None
    blob, expiry = entry
    if time.time() > expiry:
        _mem.pop(_key(token), None)
        return None
    try:
        return json.loads(blob)
    except Exception:  # pragma: no cover
        return None


# ── Reporter ──────────────────────────────────────────────────────────────────

_STAGE_FOR_FILE_PHASE = {"uploaded": "reading", "parsed": "reading", "extracting": "extracting", "extracted": "extracting"}
_STAGE_FOR_PACKAGE_PHASE = {"normalized": "normalizing", "scored": "scoring", "form_ready": "finalizing"}


class _NullReporter:
    """No-op reporter used when no progress token is supplied (worker path,
    integrity re-runs, reclassify, confirm) so instrumented call sites stay clean.

    Every method accepts ``*_a, **_k`` (rather than a fixed signature) so it can
    NEVER go out of sync with ProgressReporter's real signatures as they evolve -
    a fixed no-arg ``done()`` here once broke every re-run call site the moment
    ProgressReporter.done() gained an optional argument.
    """

    async def begin(self, *_a, **_k) -> None: ...
    async def active(self, *_a, **_k) -> None: ...
    async def file_phase(self, *_a, **_k) -> None: ...
    async def package_phase(self, *_a, **_k) -> None: ...
    async def done(self, *_a, **_k) -> None: ...


class ProgressReporter:
    """Maintains the full progress state in memory and flushes it wholesale.

    The upload request is the sole writer for its token, so there is no
    read-modify-write and no cross-worker race: each mutation rewrites the entire
    record. All flushes are best-effort via :func:`write_progress`.
    """

    def __init__(self, token: str, user_id: Any, filenames: List[str]):
        self.token = token
        self.state: Dict[str, Any] = {
            "user_id":       str(user_id),
            "files":         [{"name": n, "phase": "uploaded"} for n in filenames],
            "package_phase": None,
            "active":        "Reading your documents…",
            "stage":         "reading",
            "done":          False,
        }

    async def _flush(self) -> None:
        await write_progress(self.token, {**self.state, "updated_at": _now_iso()})

    async def begin(self) -> None:
        await self._flush()

    async def active(self, label: str, stage: Optional[str] = None) -> None:
        """Update only the headline ("what is happening right now")."""
        self.state["active"] = label
        if stage:
            self.state["stage"] = stage
        await self._flush()

    async def file_phase(self, index: int, phase: str, active: Optional[str] = None) -> None:
        files = self.state["files"]
        if 0 <= index < len(files):
            files[index]["phase"] = phase
        self.state["stage"] = _STAGE_FOR_FILE_PHASE.get(phase, self.state["stage"])
        if active is not None:
            self.state["active"] = active
        await self._flush()

    async def package_phase(self, phase: str, active: Optional[str] = None) -> None:
        self.state["package_phase"] = phase
        self.state["stage"] = _STAGE_FOR_PACKAGE_PHASE.get(phase, "finalizing")
        if active is not None:
            self.state["active"] = active
        await self._flush()

    async def done(self, session_id: Optional[str] = None) -> None:
        self.state["package_phase"] = "form_ready"
        self.state["stage"] = "done"
        self.state["active"] = "Ready"
        self.state["done"] = True
        # Carrying the session id lets a client that refreshed mid-upload reload
        # the finished submission from the poll alone (Figure 1 resume path).
        if session_id is not None:
            self.state["session_id"] = str(session_id)
        await self._flush()


def make_reporter(token: Optional[str], user_id: Any, filenames: List[str]):
    """Return a live :class:`ProgressReporter` when a token is supplied, otherwise
    a :class:`_NullReporter` so call sites never branch on progress being enabled."""
    if not token:
        return _NullReporter()
    try:
        return ProgressReporter(token, user_id, filenames)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("progress_tracker: reporter init failed (%s) — progress disabled", exc)
        return _NullReporter()
