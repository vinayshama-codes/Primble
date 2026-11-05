import ipaddress
import uuid
import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

_WINDOW_SECONDS         = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
_MAX_PER_WINDOW         = int(os.getenv("RATE_LIMIT_UPLOADS_PER_WINDOW", "10"))
_ARQ_PUBLIC_MAX_WINDOW  = int(os.getenv("RATE_LIMIT_ARQ_PUBLIC_PER_WINDOW", "30"))
_ARQ_SUBMIT_MAX_WINDOW  = int(os.getenv("RATE_LIMIT_ARQ_SUBMIT_PER_WINDOW", "5"))
_ARQ_CHAT_MAX_WINDOW    = int(os.getenv("RATE_LIMIT_ARQ_CHAT_PER_WINDOW", "20"))
_ASSISTANT_CHAT_MAX_WINDOW = int(os.getenv("RATE_LIMIT_ASSISTANT_CHAT_PER_WINDOW", "20"))
_AUTH_MAX_WINDOW        = int(os.getenv("RATE_LIMIT_AUTH_PER_WINDOW", "10"))
_DOWNLOAD_MAX_WINDOW    = int(os.getenv("RATE_LIMIT_DOWNLOADS_PER_WINDOW", "20"))
_VERIFY_UPGRADE_MAX     = int(os.getenv("RATE_LIMIT_VERIFY_UPGRADE_PER_WINDOW", "5"))

_WEB_CONCURRENCY = int(os.getenv("WEB_CONCURRENCY", "1"))

# ── Redis connection (optional) ───────────────────────────────────────────────
# Uses Redis sorted sets for true sliding-window rate limiting across workers.
# Falls back to in-process sliding window only when WEB_CONCURRENCY=1.
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
    logger.info("rate_limiter: Redis connected")
except Exception as _redis_init_err:
    logger.warning(
        f"rate_limiter: Redis unavailable ({_redis_init_err}) — "
        "in-process sliding window active"
    )
    _redis = None

if _redis is None and _WEB_CONCURRENCY > 1:
    raise RuntimeError(
        "REDIS_URL must be set when WEB_CONCURRENCY > 1. "
        "In-process rate limiting is per-worker and cannot enforce global limits across processes."
    )

# In-process fallback — per-user list of request timestamps inside the current window.
# Safe under the GIL for single-worker uvicorn.
_windows: dict = defaultdict(list)


async def _redis_sliding_window(key: str, max_per_window: int, window_seconds: int = 0) -> int:
    """
    Sliding-window rate limit check via Redis sorted sets.
    Returns the current request count after recording this request.
    Uses ZADD + ZREMRANGEBYSCORE + ZCARD in a pipeline for atomicity.
    `window_seconds` (0 = RATE_LIMIT_WINDOW_SECONDS) lets a limit run over an hour as well as a minute.
    """
    window = window_seconds or _WINDOW_SECONDS
    now = time.time()
    cutoff = now - window
    member = f"{now}:{uuid.uuid4().hex[:8]}"           # two requests in one tick are two entries
    async with _redis.pipeline() as pipe:
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window * 2)
        results = await pipe.execute()
    count = results[2]  # ZCARD result
    if count > max_per_window:
        # A refused attempt never stays in the window, as in the in-process path: retrying while blocked must not
        # keep a user blocked past the window (review pass 2, 3 Nov 2026).
        try:
            await _redis.zrem(key, member)
        except Exception:                                  # noqa: BLE001 - it expires with the key
            pass
    return count


_ip_source_logged = False


def _without_port(entry: str) -> str:
    """"203.0.113.7:51234" -> "203.0.113.7"; "[2001:db8::1]:443" -> "2001:db8::1"; a bare IPv6 stays whole."""
    e = entry.strip()
    if e.startswith("["):
        return e[1:e.index("]")] if "]" in e else e
    if e.count(":") == 1:
        return e.split(":", 1)[0]
    return e


def _limit_identity(identifier: str) -> str:
    """The bucket a limit counts in. An IPv6 address counts as its /64 - one home or office gets a whole /64, so a
    client rotating addresses inside it would otherwise get a fresh bucket each time (review pass 2, 3 Nov 2026).
    Anything else (an IPv4 address, a user id) is itself. `get_client_ip` still returns the exact address."""
    try:
        ip = ipaddress.ip_address(str(identifier))
    except ValueError:
        return identifier
    if ip.version == 6:
        if ip.ipv4_mapped:                                 # "::ffff:203.0.113.7" is that IPv4 address
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def get_client_ip(request) -> str:
    """The client's IP for IP-keyed limits.

    Behind a proxy (Render) `request.client.host` is the PROXY's address, so every IP-keyed limit was one shared
    bucket (3 Nov 2026). `TRUSTED_PROXY_HOPS` = how many proxies sit in front of the app (Render alone: 1; Cloudflare
    in front of Render: 2). Each proxy APPENDS the address that connected to it to X-Forwarded-For, so the entry that
    many places from the END is the real client; entries further left were written by the client and can be forged,
    so they are never used. 0 (the default) = `request.client.host`, exactly as before. Uvicorn's own
    "trust forwarded headers" switch is deliberately not used: trusting every hop lets a client pick its own IP.
    Set 2 ONLY when the origin refuses traffic that did not come through Cloudflare: with 2, a request sent straight
    to primble.onrender.com can forge the second-to-last entry (review pass 3).
    """
    global _ip_source_logged
    peer = request.client.host if getattr(request, "client", None) else "unknown"
    try:
        hops = max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0") or 0))
    except ValueError:
        hops = 0
    if hops == 0:
        return peer
    headers = getattr(request, "headers", None)
    # A request can carry the header more than once; the proxies' entries are in the LAST one, so all are read in
    # order (hard review, 3 Nov 2026).
    if headers is None:
        values = []
    elif hasattr(headers, "getlist"):
        values = headers.getlist("x-forwarded-for")
    else:
        values = [headers.get("x-forwarded-for")]
    entries = [e.strip() for v in values for e in str(v or "").split(",") if e.strip()]
    if not _ip_source_logged and entries:
        _ip_source_logged = True
        # Counts only, never an address: tells whether TRUSTED_PROXY_HOPS matches the real number of proxies.
        logger.info("CLIENT_IP_SOURCE trusted_hops=%d forwarded_entries=%d", hops, len(entries))
    if len(entries) < hops:
        return peer
    candidate = _without_port(entries[-hops])
    try:
        candidate = str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer
    return candidate


async def check_upload_rate_limit(user_id: str) -> None:
    """
    Raise HTTPException(429) when the user exceeds RATE_LIMIT_UPLOADS_PER_WINDOW
    uploads within RATE_LIMIT_WINDOW_SECONDS seconds.

    Uses a Redis sliding-window (sorted set) when Redis is reachable; falls back to an
    in-process sliding window otherwise.  Both paths are transparent to callers.
    """
    from fastapi import HTTPException

    now = time.time()

    if _redis is not None:
        try:
            key   = f"rl:upload:{user_id}"
            count = await _redis_sliding_window(key, _MAX_PER_WINDOW)
            if count > _MAX_PER_WINDOW:
                logger.warning(
                    f"rate_limiter: user {user_id} throttled "
                    f"({count}/{_MAX_PER_WINDOW} in window, Redis)"
                )
                raise HTTPException(
                    429,
                    f"Too many uploads — maximum {_MAX_PER_WINDOW} per minute. "
                    "Please wait and try again.",
                )
            return
        except HTTPException:
            raise
        except Exception as ex:
            logger.warning(f"rate_limiter: Redis error, using in-process fallback: {ex}")

    # In-process sliding window fallback (single-worker only)
    cutoff = now - _WINDOW_SECONDS
    _windows[user_id] = [t for t in _windows[user_id] if t > cutoff]
    if len(_windows[user_id]) >= _MAX_PER_WINDOW:
        logger.warning(
            f"rate_limiter: user {user_id} throttled "
            f"({len(_windows[user_id])}/{_MAX_PER_WINDOW} in window, in-process)"
        )
        raise HTTPException(
            429,
            f"Too many uploads — maximum {_MAX_PER_WINDOW} per minute. "
            "Please wait and try again.",
        )
    _windows[user_id].append(now)


async def _check_rate_limit_by_key(namespace: str, identifier: str, max_per_window: int,
                                   window_seconds: int = 0,
                                   message: str = "Too many requests. Please try again later.") -> None:
    """Generic rate limiter keyed by namespace:identifier. Raises HTTP 429 when exceeded."""
    from fastapi import HTTPException

    window  = window_seconds or _WINDOW_SECONDS
    now     = time.time()
    key_str = f"rl:{namespace}:{_limit_identity(identifier)}"

    if _redis is not None:
        try:
            count = await _redis_sliding_window(key_str, max_per_window, window)
            if count > max_per_window:
                raise HTTPException(429, message)
            return
        except HTTPException:
            raise
        except Exception as ex:
            logger.warning(f"rate_limiter: Redis error for {key_str}: {ex}")

    # In-process sliding window fallback (single-worker only)
    cutoff = now - window
    _windows[key_str] = [t for t in _windows[key_str] if t > cutoff]
    if len(_windows[key_str]) >= max_per_window:
        raise HTTPException(429, message)
    _windows[key_str].append(now)


_CLIENT_SENDS_PER_MINUTE = int(os.getenv("RATE_LIMIT_CLIENT_SENDS_PER_MINUTE", "10"))
_CLIENT_SENDS_PER_HOUR   = int(os.getenv("RATE_LIMIT_CLIENT_SENDS_PER_HOUR", "60"))
_CLIENT_SENDS_MESSAGE    = "Too many questionnaires sent. Please wait a few minutes and try again."


async def check_client_send_rate_limit(user_id: str) -> None:
    """Questionnaire sends AND reminders, per producer (3 Nov 2026): each one is an e-mail to an address the
    producer types, so an unlimited route could be used to spam. 10 a minute and 60 an hour by default."""
    await _check_rate_limit_by_key("client_send_m", user_id, _CLIENT_SENDS_PER_MINUTE, 60, _CLIENT_SENDS_MESSAGE)
    await _check_rate_limit_by_key("client_send_h", user_id, _CLIENT_SENDS_PER_HOUR, 3600,
                                   "Too many questionnaires sent this hour. Please try again later.")


async def check_arq_public_rate_limit(ip: str) -> None:
    """Rate limit public ARQ view requests by IP address."""
    await _check_rate_limit_by_key("arq_view", ip, _ARQ_PUBLIC_MAX_WINDOW)


async def check_arq_submit_rate_limit(ip: str) -> None:
    """Rate limit public ARQ submission requests by IP address."""
    await _check_rate_limit_by_key("arq_submit", ip, _ARQ_SUBMIT_MAX_WINDOW)


async def check_arq_chat_rate_limit(ip: str) -> None:
    """Rate limit public ARQ chat (LLM) requests by IP address."""
    await _check_rate_limit_by_key("arq_chat", ip, _ARQ_CHAT_MAX_WINDOW)


async def check_assistant_chat_rate_limit(user_id: str) -> None:
    """Rate limit authenticated in-app assistant chat (LLM) requests by user ID."""
    await _check_rate_limit_by_key("assistant_chat", user_id, _ASSISTANT_CHAT_MAX_WINDOW)


async def check_auth_rate_limit(identifier: str) -> None:
    """Rate limit auth endpoints (login, forgot-password, resend) by email or IP."""
    await _check_rate_limit_by_key("auth", identifier, _AUTH_MAX_WINDOW)


async def check_download_rate_limit(user_id: str) -> None:
    """Rate limit download endpoints by user ID."""
    await _check_rate_limit_by_key("download", user_id, _DOWNLOAD_MAX_WINDOW)


async def check_verify_upgrade_rate_limit(user_id: str) -> None:
    """Rate limit /verify-upgrade endpoint by user ID — capped at 5 per minute."""
    await _check_rate_limit_by_key("verify_upgrade", user_id, _VERIFY_UPGRADE_MAX)
