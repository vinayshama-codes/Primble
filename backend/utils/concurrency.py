import asyncio
import contextvars
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import wraps

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_MAX_HEAVY:        int = int(os.getenv("MAX_CONCURRENT_HEAVY_OPS", "8"))
_WEB_CONCURRENCY:  int = int(os.getenv("WEB_CONCURRENCY", "1"))
_SEM_KEY      = "heavy_ops_semaphore"
_SEM_TTL_MS   = 300_000  # 300 seconds — auto-release if process crashes
_HEAVY_MAX_WAIT_S = float(os.getenv("HEAVY_MAX_WAIT_S", "900"))

# ── Redis distributed semaphore ───────────────────────────────────────────────
# Enabled whenever REDIS_URL points to a reachable Redis. Multi-worker mode
# REQUIRES it; single-worker mode benefits from it too because multi-tab /
# multi-user concurrency on localhost otherwise shares one in-process semaphore.
_redis = None
try:
    import redis.asyncio as _aioredis
    from redis.asyncio.connection import ConnectionPool
    from config.settings import REDIS_URL as _REDIS_URL
    _redis = _aioredis.Redis(connection_pool=ConnectionPool.from_url(
        _REDIS_URL,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        decode_responses=True,
    ))
    logger.info("concurrency: Redis distributed semaphore active")
except Exception as _e:
    logger.warning(f"concurrency: Redis unavailable ({_e}) — in-process semaphore only")
    _redis = None

# ── In-process semaphore (single-worker fallback) ─────────────────────────────
_heavy_sem: asyncio.Semaphore = None


def get_heavy_sem() -> asyncio.Semaphore:
    """Return the in-process semaphore, creating it lazily on first call."""
    global _heavy_sem
    if _heavy_sem is None:
        _heavy_sem = asyncio.Semaphore(_MAX_HEAVY)
    return _heavy_sem


# ── Redis SET NX PX semaphore helpers ─────────────────────────────────────────

async def _redis_acquire() -> str | None:
    """
    Attempt to acquire one slot in the distributed semaphore.
    Uses SET NX PX on a unique token key.  Returns the token on success, None if full.
    The slot count is tracked as a Redis sorted set keyed by _SEM_KEY; each active
    holder has a member with score=expiry_ms so stale holders are pruned on each call.
    """
    # Wall clock, never time.monotonic(): the score is compared across processes and
    # restarts, and PEXPIREAT takes a Unix time - a monotonic value is a date in 1970,
    # which deletes the key at once, so the limit never held (1 Nov 2026).
    now_ms = int(time.time() * 1000)
    expiry_ms = now_ms + _SEM_TTL_MS
    token = str(uuid.uuid4())

    # Prune expired holders, then check/add atomically via Lua.
    # Lua script: trim stale entries → count live → if < max, add new holder → return 1 else 0
    lua = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local expiry = tonumber(ARGV[2])
local maxn   = tonumber(ARGV[3])
local token  = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
local count = redis.call('ZCARD', key)
if count < maxn then
    redis.call('ZADD', key, expiry, token)
    redis.call('PEXPIREAT', key, expiry + 1000)
    return 1
end
return 0
"""
    result = await _redis.eval(lua, 1, _SEM_KEY, now_ms, expiry_ms, _MAX_HEAVY, token)
    if result != 1:
        return None
    _RENEWALS[token] = asyncio.create_task(_renew_slot(token))
    return token


# A 271-page upload can run far past the slot's lifetime. Renewed while the work runs, so
# it keeps counting; a crash stops the renewal, and the slot then expires by itself.
_RENEWALS: dict = {}
_RENEW_EVERY_S = _SEM_TTL_MS / 1000 / 3


async def _renew_slot(token: str) -> None:
    lua = """
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then
    redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])
    redis.call('PEXPIREAT', KEYS[1], ARGV[1] + 1000)
    return 1
end
return 0
"""
    while True:
        await asyncio.sleep(_RENEW_EVERY_S)
        try:
            await _redis.eval(lua, 1, _SEM_KEY, int(time.time() * 1000) + _SEM_TTL_MS, token)
        except Exception as ex:                                # noqa: BLE001
            logger.warning(f"concurrency: slot renewal failed: {ex}")


async def _redis_release(token: str) -> None:
    """Release a previously acquired distributed semaphore slot."""
    renewal = _RENEWALS.pop(token, None)
    if renewal is not None:
        renewal.cancel()
    try:
        await _redis.zrem(_SEM_KEY, token)
    except Exception as ex:
        logger.warning(f"concurrency: Redis release failed: {ex}")


async def try_acquire_heavy() -> "str | bool":
    """
    Non-blocking acquire of the heavy-ops semaphore.

    Multi-worker: uses Redis distributed semaphore (SET NX / sorted-set Lua).
      Returns the string token on success, False if all slots are occupied.

    Single-worker: uses in-process asyncio.Semaphore.
      Returns True on success, False if locked.

    Callers must pass the return value to release_heavy().
    """
    if _redis is not None:
        try:
            token = await _redis_acquire()
            return token if token else False
        except Exception as ex:
            logger.warning(f"concurrency: Redis semaphore failed, using in-process fallback: {ex}")

    sem = get_heavy_sem()
    if sem.locked():
        return False
    await sem.acquire()
    return True


async def acquire_heavy_waiting(acquire=None, max_wait_s: float = _HEAVY_MAX_WAIT_S) -> "str | bool":
    """A heavy slot, WAITING for one: a busy moment keeps the user's normal spinner
    instead of refusing the upload (owner, 1 Nov 2026). False only after `max_wait_s`."""
    acquire = acquire or try_acquire_heavy
    deadline = time.monotonic() + max_wait_s
    while True:
        token = await acquire()
        if token or time.monotonic() >= deadline:
            return token
        await asyncio.sleep(1.0)


# Scoring is pure Python and takes seconds on a real package. On the event loop it
# freezes every other user for that long (measured 3.17 s -> 0.07 s, 1 Nov 2026).
_SCORING_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.getenv("SCORING_WORKERS", "4")), thread_name_prefix="scoring")


async def run_scoring(fn, /, *args, **kwargs):
    """Run a synchronous scoring call off the event loop, carrying this request's
    context variables with it (the trace id, the stops memo, the not-scored list)."""
    def _call():
        try:
            return fn(*args, **kwargs)
        except StopIteration as ex:
            # A future cannot carry StopIteration: the await would hang for ever,
            # under the package's lock.
            raise RuntimeError(f"{getattr(fn, '__name__', fn)} raised StopIteration") from ex
    ctx = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(_SCORING_EXECUTOR, ctx.run, _call)


# ── One writer per package ────────────────────────────────────────────────────
# With scoring off the loop, two saves on ONE package could overlap, and the older
# score could land last. Different packages never wait on each other. Re-entrant
# within a request (a route holding it may call a recalculation that takes it too).
_SESSION_LOCKS: dict = {}
_HELD_SESSIONS: contextvars.ContextVar = contextvars.ContextVar("held_session_locks", default=frozenset())


@asynccontextmanager
async def session_write_lock(session_id):
    key = str(session_id or "")
    if not key or key in _HELD_SESSIONS.get():
        yield
        return
    slot = (id(asyncio.get_running_loop()), key)     # an asyncio.Lock belongs to one loop
    entry = _SESSION_LOCKS.setdefault(slot, [asyncio.Lock(), 0])
    entry[1] += 1
    token = None
    try:
        async with entry[0]:
            token = _HELD_SESSIONS.set(_HELD_SESSIONS.get() | {key})
            try:
                yield
            finally:
                _HELD_SESSIONS.reset(token)
    finally:
        entry[1] -= 1
        if entry[1] <= 0 and _SESSION_LOCKS.get(slot) is entry:
            del _SESSION_LOCKS[slot]


def one_writer_per_package(route):
    """Run a save under its package's lock. The package id is a `session_id` or
    `processing_session_id` argument, `session_id` on the request model, or a first
    positional string. LOCK ORDER everywhere: package, then documents, then policy store."""
    @wraps(route)
    async def _guarded(*args, **kwargs):
        sid = kwargs.get("processing_session_id") or kwargs.get("session_id")
        if sid is None:
            first = args[0] if args else kwargs.get("req")
            sid = first if isinstance(first, str) else getattr(first, "session_id", None)
        async with session_write_lock(sid):
            return await route(*args, **kwargs)
    return _guarded


async def watch_event_loop(interval_s: float = 0.5, warn_after_s: float = 2.0) -> None:
    """Log `LOOP_BLOCKED` when something holds the event loop, because every user waits
    while it does. Grep live logs for it: it names the moment, and the trace id of
    whichever request ran next narrows the cause. Log only, no effect on anything."""
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        await asyncio.sleep(interval_s)
        lag = loop.time() - started - interval_s
        if lag >= warn_after_s:
            logger.warning("LOOP_BLOCKED lag=%.1fs", lag)


async def release_heavy(token: "str | bool" = True) -> None:
    """Release a previously acquired heavy-ops slot.

    Pass the value returned by try_acquire_heavy().
    """
    if _redis is not None and isinstance(token, str):
        await _redis_release(token)
        return
    # In-process path — token is True
    get_heavy_sem().release()


@asynccontextmanager
async def heavy_semaphore():
    """Acquire the heavy-ops semaphore or raise HTTP 429 immediately.

    Raises HTTP 429 with Retry-After: 30 when all slots are occupied.
    Use this for context-manager callsites; use try_acquire_heavy() + release_heavy()
    when the acquire and release happen in different try/finally blocks.
    """
    token = await try_acquire_heavy()
    if not token:
        raise HTTPException(
            status_code=429,
            detail="Server busy - too many requests at once. Please retry in 30 seconds.",
            headers={"Retry-After": "30"},
        )
    try:
        yield
    finally:
        await release_heavy(token)
