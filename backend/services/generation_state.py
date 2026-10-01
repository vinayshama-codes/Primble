"""generation_state.py - is a package's form generation running, finished,
interrupted, or never started? (Orbin item 1, 1 Oct 2026.)

ONE door, read by the package page (GET /api/session), the progress screen's
poll (GET /api/jobs/{id}/status) and the actions that must not run while forms
exist or are being generated.

A run proves it is alive with a HEARTBEAT. While a form generation runs, the
sync route or the worker re-stamps its job's `updated_at` every
HEARTBEAT_SECONDS (`GenerationHeartbeat`, through `JobQueue.touch`, which never
touches a job that has finished). A processing job silent for longer than
`STALE_AFTER_SECONDS` died with its process - a restart, a deploy, a crash -
because nothing else stops the heartbeat without also writing the run's end.
Until 1 Oct 2026 a dead sync run left its job 'processing' forever: every reopen
spun for five minutes, then dropped the producer on the upload screen with no
word of what happened.

Pure apart from the heartbeat's own writes: no service imports.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATE_NONE = "none"              # never generated (or the marker was cleared)
STATE_RUNNING = "running"        # a live run is generating the forms now
STATE_DONE = "done"              # forms exist
STATE_INTERRUPTED = "interrupted"  # a run started and did not store forms


def _env_seconds(name: str, default: int, floor: int) -> int:
    try:
        return max(floor, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


HEARTBEAT_SECONDS = _env_seconds("GENERATION_HEARTBEAT_SECONDS", 30, 5)
# Ten missed beats. Generous on purpose: the steps that run on the event loop
# between executor calls (package scoring, field QA) cannot beat, and calling a
# live run dead lets the producer start a second one.
STALE_AFTER_SECONDS = _env_seconds("GENERATION_STALE_AFTER_SECONDS", 300, 60)
# A job still WAITING for a worker (async mode) is not heartbeated. Thirty
# minutes matches the queue's own dead-job window (job_repository: the in-flight
# count and the stuck-job watchdog).
PENDING_STALE_AFTER_SECONDS = _env_seconds("GENERATION_PENDING_STALE_AFTER_SECONDS", 1800, 60)

_ALIVE_STATUSES = {"pending": PENDING_STALE_AFTER_SECONDS, "processing": STALE_AFTER_SECONDS}


def _epoch(value: Any) -> Optional[float]:
    """A job timestamp (ISO text, a datetime, or epoch seconds) as epoch
    seconds; None when it cannot be read."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def job_is_stale(job: Any, now: Optional[float] = None) -> bool:
    """Has this unfinished job stopped showing signs of life? False for a
    finished job, and False whenever its last-touched time cannot be read
    (never call a run dead without evidence)."""
    if not isinstance(job, dict):
        return False
    window = _ALIVE_STATUSES.get(str(job.get("status") or ""))
    if window is None:
        return False
    last = _epoch(job.get("updated_at")) or _epoch(job.get("created_at"))
    if last is None:
        return False
    now = time.time() if now is None else float(now)
    return (now - last) > window


def generation_state(session: Any, job: Any, now: Optional[float] = None) -> str:
    """The package's generation state, from its session row and the job its
    in-progress marker names (None when that job does not exist)."""
    session = session if isinstance(session, dict) else {}
    if session.get("generated_forms"):
        return STATE_DONE
    if not session.get("generation_job_id"):
        return STATE_NONE
    if not isinstance(job, dict):
        return STATE_INTERRUPTED            # the job row is gone
    status = str(job.get("status") or "")
    if status in _ALIVE_STATUSES:
        return STATE_INTERRUPTED if job_is_stale(job, now) else STATE_RUNNING
    if status == "completed":
        # Forms are stored BEFORE the job is marked completed on both paths, so
        # this is a read that raced the store; the caller re-reads the session.
        return STATE_RUNNING
    return STATE_INTERRUPTED                # failed, or a status we do not know


def forms_locked_reason(session: Any, state: Optional[str] = None) -> Optional[str]:
    """Why the package's pre-form actions (reclassify, exclude, confirm a
    value, resolve integrity, generate again) must refuse, or None. Those
    actions re-read the documents and never touch forms that already exist, so
    after generation they would leave the forms on the old values."""
    session = session if isinstance(session, dict) else {}
    if session.get("generated_forms"):
        return "Forms are generated - make changes in the form editor."
    if state == STATE_RUNNING:
        return "Forms are being generated - wait for them to finish."
    return None


class GenerationHeartbeat:
    """Keeps a running form-generation job looking alive.

        hb = GenerationHeartbeat(queue, job_id)
        await hb.start()
        try: ... long run ...
        finally: await hb.stop()

    A queue without `touch` gets no heartbeat (and no error)."""

    def __init__(self, queue: Any, job_id: str, every: Optional[float] = None) -> None:
        self._queue = queue
        self._job_id = job_id
        self._every = float(every if every is not None else HEARTBEAT_SECONDS)
        self._task: Optional[asyncio.Task] = None

    async def _beat(self) -> None:
        touch = getattr(self._queue, "touch", None)
        if not callable(touch):
            return
        # Short naps, beats on the WALL clock: the loop's own clock stops while a
        # Mac sleeps, so a 30 s nap could wake into a run that already reads
        # dead. After a sleep the first wake-up beats at once.
        step = min(5.0, self._every)
        last = time.time()
        while True:
            await asyncio.sleep(step)
            if time.time() - last < self._every:
                continue
            last = time.time()
            try:
                await touch(self._job_id)
            except Exception as ex:                      # noqa: BLE001
                logger.warning("generation heartbeat failed for job %s: %s", self._job_id, ex)

    async def start(self) -> "GenerationHeartbeat":
        if self._task is None and self._job_id:
            self._task = asyncio.ensure_future(self._beat())
        return self

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def __aenter__(self) -> "GenerationHeartbeat":
        return await self.start()

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()
