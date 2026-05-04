import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_MAX_HEAVY:        int = int(os.getenv("MAX_CONCURRENT_HEAVY_OPS", "3"))
_WEB_CONCURRENCY:  int = int(os.getenv("WEB_CONCURRENCY", "1"))
_SEM_KEY      = "heavy_ops_semaphore"
_SEM_TTL_MS   = 300_000  # 300 seconds — auto-release if process crashes

# ── Redis distributed semaphore (multi-worker mode) ───────────────────────────
_redis = None
if _WEB_CONCURRENCY > 1:
    try:
        import redis as _redis_lib
        from config.settings import REDIS_URL as _REDIS_URL
        _redis = _redis_lib.from_url(
            _REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        _redis.ping()
        logger.info(f"concurrency: Redis distributed semaphore active ({_REDIS_URL})")
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

def _redis_acquire() -> str | None:
    """
    Attempt to acquire one slot in the distributed semaphore.
    Uses SET NX PX on a unique token key.  Returns the token on success, None if full.
    The slot count is tracked as a Redis sorted set keyed by _SEM_KEY; each active
    holder has a member with score=expiry_ms so stale holders are pruned on each call.
    """
    now_ms = int(time.monotonic() * 1000)
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
    result = _redis.eval(lua, 1, _SEM_KEY, now_ms, expiry_ms, _MAX_HEAVY, token)
    return token if result == 1 else None


def _redis_release(token: str) -> None:
    """Release a previously acquired distributed semaphore slot."""
    try:
        _redis.zrem(_SEM_KEY, token)
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
        token = _redis_acquire()
        return token if token else False

    sem = get_heavy_sem()
    if sem.locked():
        return False
    await sem.acquire()
    return True


def release_heavy(token: "str | bool" = True) -> None:
    """Release a previously acquired heavy-ops slot.

    Pass the value returned by try_acquire_heavy().
    """
    if _redis is not None and isinstance(token, str):
        _redis_release(token)
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
            detail="Server busy — too many concurrent requests. Please retry in 30 seconds.",
            headers={"Retry-After": "30"},
        )
    try:
        yield
    finally:
        release_heavy(token)
