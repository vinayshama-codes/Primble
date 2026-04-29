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
_AUTH_MAX_WINDOW        = int(os.getenv("RATE_LIMIT_AUTH_PER_WINDOW", "10"))

# ── Redis connection (optional) ───────────────────────────────────────────────
# Mirrors the same lazy-init pattern used in extraction_service.py.
# Falls back gracefully to in-process state when Redis is unavailable.
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
    logger.info(f"rate_limiter: Redis connected ({_REDIS_URL})")
except Exception as _redis_init_err:
    logger.warning(
        f"rate_limiter: Redis unavailable ({_redis_init_err}) — "
        "in-process sliding window active"
    )
    _redis = None

import os as _os
if _redis is None and int(_os.getenv("WEB_CONCURRENCY", "1")) > 1:
    logger.error(
        "rate_limiter: Redis not configured but WEB_CONCURRENCY > 1."
        " Per-user limits are PER-WORKER only. Set REDIS_URL to fix."
    )

# In-process fallback — per-user list of request timestamps inside the current window.
# Safe under the GIL for single-worker uvicorn.
_windows: dict = defaultdict(list)


def check_upload_rate_limit(user_id: str) -> None:
    """
    Raise HTTPException(429) when the user exceeds RATE_LIMIT_UPLOADS_PER_WINDOW
    uploads within RATE_LIMIT_WINDOW_SECONDS seconds.

    Uses a Redis fixed-window counter when Redis is reachable; falls back to an
    in-process sliding window otherwise.  Both paths are transparent to callers.
    """
    from fastapi import HTTPException

    now        = time.time()
    window_key = int(now // _WINDOW_SECONDS)

    if _redis is not None:
        try:
            key   = f"rl:upload:{user_id}:{window_key}"
            count = _redis.incr(key)
            if count == 1:
                # First hit in this window — set expiry so the key auto-cleans up.
                _redis.expire(key, _WINDOW_SECONDS * 2)
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

    # In-process sliding window fallback
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


def _check_rate_limit_by_key(namespace: str, identifier: str, max_per_window: int) -> None:
    """Generic rate limiter keyed by namespace:identifier. Raises HTTP 429 when exceeded."""
    from fastapi import HTTPException

    now        = time.time()
    window_key = int(now // _WINDOW_SECONDS)
    key_str    = f"rl:{namespace}:{identifier}"

    if _redis is not None:
        try:
            redis_key = f"{key_str}:{window_key}"
            count = _redis.incr(redis_key)
            if count == 1:
                _redis.expire(redis_key, _WINDOW_SECONDS * 2)
            if count > max_per_window:
                raise HTTPException(429, "Too many requests. Please try again later.")
            return
        except HTTPException:
            raise
        except Exception as ex:
            logger.warning(f"rate_limiter: Redis error for {key_str}: {ex}")

    cutoff = now - _WINDOW_SECONDS
    _windows[key_str] = [t for t in _windows[key_str] if t > cutoff]
    if len(_windows[key_str]) >= max_per_window:
        raise HTTPException(429, "Too many requests. Please try again later.")
    _windows[key_str].append(now)


def check_arq_public_rate_limit(ip: str) -> None:
    """Rate limit public ARQ view requests by IP address."""
    _check_rate_limit_by_key("arq_view", ip, _ARQ_PUBLIC_MAX_WINDOW)


def check_arq_submit_rate_limit(ip: str) -> None:
    """Rate limit public ARQ submission requests by IP address."""
    _check_rate_limit_by_key("arq_submit", ip, _ARQ_SUBMIT_MAX_WINDOW)


def check_arq_chat_rate_limit(ip: str) -> None:
    """Rate limit public ARQ chat (LLM) requests by IP address."""
    _check_rate_limit_by_key("arq_chat", ip, _ARQ_CHAT_MAX_WINDOW)


def check_auth_rate_limit(identifier: str) -> None:
    """Rate limit auth endpoints (login, forgot-password, resend) by email or IP."""
    _check_rate_limit_by_key("auth", identifier, _AUTH_MAX_WINDOW)
