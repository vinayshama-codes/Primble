"""Global cap on simultaneous OpenAI chat completions, distributed via Redis.

Why this exists
---------------
On OpenAI Tier 1, gpt-4o / gpt-4o-mini has a 500 RPM ceiling. The form-fill
pipeline parallelises GPT calls (per-form, per-chunk), so a small number of
concurrent users can fire 50-300+ requests in a single second. OpenAI sees
this as a burst, returns 429, and the retry layer backs off for 30-60s.

The semaphore lets calls queue inside our process(es) instead of being
rejected by OpenAI, smoothing the burst into a steady stream under the RPM
cap.

Why Redis
---------
With WEB_CONCURRENCY=2 (web) plus the worker process, the previous per-process
asyncio.Semaphore gave us LLM_MAX_CONCURRENT * 3 effective slots, not the
single global ceiling we wanted. A Redis sorted set keyed by expiry timestamp
lets all processes share one global budget, identical pattern to the existing
heavy-ops semaphore.

Local fallback
--------------
When Redis is unavailable (or when called from a ThreadPoolExecutor thread
where asyncio.run() creates a fresh event loop that doesn't own the module-
level Redis connection pool), the limiter falls back to a threading.Semaphore.
Unlike asyncio.Semaphore, threading.Semaphore is not bound to any event loop
and works correctly from any thread regardless of which loop is running.

Tuning
------
LLM_MAX_CONCURRENT — GLOBAL cap on in-flight OpenAI requests across every
   process (web workers + background worker) that talks to the same Redis.
   Default 12. Safe for Tier 1 (500 RPM ≈ 8 RPS, each call ~1-3s).
   Raise to 30-50 on Tier 2 (5,000 RPM); higher tiers proportionally.

LLM_ACQUIRE_TIMEOUT — max seconds a caller will wait for a free slot before
   raising. Default 90s. Set high enough to absorb queue depth; too low
   causes spurious failures during bursts.

When Redis is unreachable the limiter degrades to a per-process
threading.Semaphore (development / single-instance fallback). Call sites do
not change.
"""
import asyncio
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_LLM_MAX_CONCURRENT  = int(os.getenv("LLM_MAX_CONCURRENT", "12"))
_ACQUIRE_TIMEOUT_S   = float(os.getenv("LLM_ACQUIRE_TIMEOUT", "90"))
_SLOT_TTL_MS         = int(os.getenv("LLM_SLOT_TTL_MS", "180000"))  # 180s auto-release
_POLL_BASE_S         = 0.05  # initial wait between retries (jittered)
_POLL_MAX_S          = 0.5

_SEM_KEY = "llm_global_semaphore"

# Sentinel returned by _redis_try_acquire when Redis threw an exception
# (as opposed to None which means "slot full but Redis is healthy").
_REDIS_ERROR = object()

# ── Redis distributed limiter ─────────────────────────────────────────────────
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
    logger.info(
        "llm_limiter: Redis-distributed semaphore active (cap=%d, ttl=%dms)",
        _LLM_MAX_CONCURRENT, _SLOT_TTL_MS,
    )
except Exception as _e:
    logger.warning(
        "llm_limiter: Redis unavailable (%s) — per-process semaphore only", _e
    )
    _redis = None

# ── Thread-safe local fallback ────────────────────────────────────────────────
# threading.Semaphore is not bound to any event loop, so it works correctly
# whether called from the main asyncio loop, from asyncio.run() on a fresh
# loop inside a ThreadPoolExecutor thread, or from plain synchronous code.
_thread_sem = threading.Semaphore(_LLM_MAX_CONCURRENT)


_LUA_ACQUIRE = """
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


async def _redis_try_acquire():
    """Try to claim a slot in the Redis sorted set.

    Returns:
        str   — token that was stored (caller must release it)
        None  — all slots occupied; Redis is healthy, just full
        _REDIS_ERROR (sentinel) — Redis call raised an exception
    """
    now_ms    = int(time.monotonic() * 1000)
    expiry_ms = now_ms + _SLOT_TTL_MS
    token     = str(uuid.uuid4())
    try:
        result = await _redis.eval(
            _LUA_ACQUIRE, 1, _SEM_KEY, now_ms, expiry_ms, _LLM_MAX_CONCURRENT, token
        )
    except Exception as ex:
        logger.warning("llm_limiter: Redis acquire failed (%s) — falling back to local", ex)
        return _REDIS_ERROR
    return token if result == 1 else None


async def _redis_release(token: str) -> None:
    try:
        await _redis.zrem(_SEM_KEY, token)
    except Exception as ex:
        logger.warning("llm_limiter: Redis release failed: %s", ex)


async def _acquire_thread_sem(timeout_s: float) -> bool:
    """Acquire _thread_sem without blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _thread_sem.acquire(timeout=timeout_s)
    )


@asynccontextmanager
async def llm_slot():
    """Acquire one global LLM slot for the duration of the block.

    Blocks (cooperatively) until a slot is free or LLM_ACQUIRE_TIMEOUT_S
    elapses. On timeout raises asyncio.TimeoutError — callers can either
    surface 503 to the user or let the caller's existing retry layer handle
    it.

    Works correctly whether called from:
    - the main asyncio event loop (web request handlers)
    - asyncio.run() inside a ThreadPoolExecutor thread (form generation worker)
    - any other thread context
    """
    token: str | None = None

    if _redis is None:
        # Pure in-process path: threading.Semaphore works from any event loop.
        acquired = await _acquire_thread_sem(_ACQUIRE_TIMEOUT_S)
        if not acquired:
            raise asyncio.TimeoutError(
                f"llm_limiter: no slot available within {_ACQUIRE_TIMEOUT_S:.0f}s"
            )
        try:
            yield
        finally:
            _thread_sem.release()
        return

    # Distributed path — poll the Lua acquire until success or timeout.
    # If Redis consistently raises (e.g. event-loop mismatch in an executor
    # thread), fall back to the thread semaphore after 3 consecutive errors
    # rather than burning the full 90s timeout.
    deadline               = time.monotonic() + _ACQUIRE_TIMEOUT_S
    wait_s                 = _POLL_BASE_S
    consecutive_redis_errs = 0

    while True:
        result = await _redis_try_acquire()

        if isinstance(result, str):
            # Got a Redis token — proceed with distributed path.
            token = result
            break

        if result is _REDIS_ERROR:
            consecutive_redis_errs += 1
            if consecutive_redis_errs >= 3:
                logger.warning(
                    "llm_limiter: Redis unavailable after %d attempts — using thread semaphore",
                    consecutive_redis_errs,
                )
                remaining = max(1.0, deadline - time.monotonic())
                acquired  = await _acquire_thread_sem(remaining)
                if not acquired:
                    raise asyncio.TimeoutError(
                        f"llm_limiter: no slot available within {_ACQUIRE_TIMEOUT_S:.0f}s"
                    )
                try:
                    yield
                finally:
                    _thread_sem.release()
                return
        else:
            # Slot is full but Redis is responding — reset error counter.
            consecutive_redis_errs = 0

        if time.monotonic() >= deadline:
            raise asyncio.TimeoutError(
                f"llm_limiter: no slot available within {_ACQUIRE_TIMEOUT_S:.0f}s"
            )

        import random as _r
        await asyncio.sleep(wait_s * (0.75 + _r.random() * 0.5))
        wait_s = min(wait_s * 2, _POLL_MAX_S)

    try:
        yield
    finally:
        if token:
            await _redis_release(token)


# ── Backwards-compatible shim ────────────────────────────────────────────────
# Older call sites use `async with get_llm_semaphore():`. Keep the name; route
# it through the new Redis-aware llm_slot() so no callers need to change.

class _LegacyShim:
    def __aenter__(self):
        self._cm = llm_slot()
        return self._cm.__aenter__()

    def __aexit__(self, exc_type, exc, tb):
        return self._cm.__aexit__(exc_type, exc, tb)


def get_llm_semaphore() -> "_LegacyShim":
    """Return an async-context-manager that acquires one global LLM slot.

    Kept as a function (not a constant) so the lazy import order matches
    the original semantics — the first acquire establishes the connection.
    """
    return _LegacyShim()
