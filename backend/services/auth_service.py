import hashlib
import hmac
import json
import secrets
import uuid
import logging
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Header, Cookie
from config.database import get_pool
from config.settings import SESSION_TTL_H as _CFG_SESSION_TTL_H

logger = logging.getLogger(__name__)

# ── Redis client — used for auth cache AND token revocation ───────────────────
try:
    import redis as _redis_lib
    from config.settings import REDIS_URL as _REDIS_URL
    _auth_redis = _redis_lib.from_url(
        _REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    _auth_redis.ping()
    logger.info(f"auth_service: Redis connected ({_REDIS_URL})")
except Exception as _redis_init_err:
    logger.warning(
        f"auth_service: Redis unavailable ({_redis_init_err}) — auth cache and Redis revocation disabled"
    )
    _auth_redis = None

_AUTH_CACHE_TTL  = 300                 # seconds — user dict cache
_SESSION_TTL_H   = _CFG_SESSION_TTL_H  # hours   — driven by SESSION_TTL_H env var
_REVOKED_KEY_PFX = "revoked:"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ASYNC-SAFE
async def create_session_token(
    user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    token      = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    now        = datetime.now(timezone.utc)
    exp        = (now + timedelta(hours=_SESSION_TTL_H)).isoformat()
    now_iso    = now.isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions"
            " (id, user_id, token, expires_at, created_at, last_used_at, ip_address, user_agent)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            str(uuid.uuid4()), user_id, token_hash, exp,
            now_iso, now_iso, ip_address, user_agent,
        )
    return token


async def revoke_token(token: str) -> None:
    """Add token hash to the revocation store and delete it from sessions."""
    token_hash = _hash_token(token)

    if _auth_redis is not None:
        try:
            _auth_redis.setex(
                f"{_REVOKED_KEY_PFX}{token_hash}",
                int(timedelta(hours=_SESSION_TTL_H).total_seconds()),
                "1",
            )
        except Exception as ex:
            logger.warning(f"auth_service: Redis revoke failed: {ex}")

    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE token = $1", token_hash)

    if _auth_redis is not None:
        try:
            _auth_redis.delete(f"auth:{token_hash}")
        except Exception:
            pass


async def revoke_all_sessions(user_id: str) -> None:
    """Revoke every active session for a user (e.g. after a password reset)."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT token FROM sessions WHERE user_id = $1", user_id
        )
        await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)

    if _auth_redis is not None:
        for row in rows:
            token_hash = dict(row)["token"]
            try:
                _auth_redis.setex(
                    f"{_REVOKED_KEY_PFX}{token_hash}",
                    int(timedelta(hours=_SESSION_TTL_H).total_seconds()),
                    "1",
                )
                _auth_redis.delete(f"auth:{token_hash}")
            except Exception as ex:
                logger.warning(f"auth_service: Redis bulk-revoke failed for hash: {ex}")


async def rotate_session(
    old_token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """Revoke old_token and issue a fresh one with the same user_id.

    Integration points (call before responding):
    - POST /auth/reset-password  (credential change)
    - POST /auth/complete-profile (privilege change)
    - Any endpoint that elevates permissions or changes sensitive user state.

    Returns the new raw token; caller must set the session cookie.
    """
    old_hash = _hash_token(old_token)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM sessions WHERE token=$1", old_hash
        )
    if not row:
        raise HTTPException(401, "Session not found for rotation")
    user_id = dict(row)["user_id"]
    await revoke_token(old_token)
    return await create_session_token(user_id, ip_address=ip_address, user_agent=user_agent)


def _is_token_revoked(token_hash: str) -> bool:
    if _auth_redis is None:
        return False
    try:
        return bool(_auth_redis.exists(f"{_REVOKED_KEY_PFX}{token_hash}"))
    except Exception as ex:
        logger.warning(f"auth_service: Redis revocation check failed: {ex}")
        return False


# ASYNC-SAFE — reads token from HttpOnly cookie; falls back to Bearer header for
# non-browser clients (e.g. download routes that pass token as query param via header).
async def get_current_user(
    authorization: str = Header(None),
    acordly_session: Optional[str] = Cookie(None),
) -> dict:
    raw_token = acordly_session
    if not raw_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Not authenticated")
        raw_token = authorization.replace("Bearer ", "")

    token_hash = _hash_token(raw_token)

    if _is_token_revoked(token_hash):
        raise HTTPException(401, "Token has been revoked")

    if _auth_redis is not None:
        try:
            cached = _auth_redis.get(f"auth:{token_hash}")
            if cached:
                return json.loads(cached)
        except Exception as ex:
            logger.warning(f"auth_service: Redis get failed: {ex}")

    async with get_pool().acquire() as conn:
        session = await conn.fetchrow(
            "SELECT * FROM sessions WHERE token = $1", token_hash
        )
        if not session:
            raise HTTPException(401, "Invalid token")
        session = dict(session)
        if datetime.fromisoformat(session["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(401, "Session expired")
        # refresh last_used_at; ignore failure (non-critical)
        try:
            await conn.execute(
                "UPDATE sessions SET last_used_at=$1 WHERE token=$2",
                datetime.now(timezone.utc).isoformat(), token_hash,
            )
        except Exception as _lu_err:
            logger.warning(f"auth_service: last_used_at update failed: {_lu_err}")
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1", session["user_id"]
        )
    if not user:
        raise HTTPException(401, "User not found")
    user     = dict(user)
    provider = user.get("auth_provider", "email") or "email"
    verified = int(user.get("email_verified", 0) or 0)
    if provider == "email" and not verified:
        raise HTTPException(403, "Email not verified.")

    if _auth_redis is not None:
        try:
            _auth_redis.setex(f"auth:{token_hash}", _AUTH_CACHE_TTL, json.dumps(user, default=str))
        except Exception as ex:
            logger.warning(f"auth_service: Redis set failed: {ex}")

    return user


# ASYNC-SAFE
async def get_user_from_token_request(
    token_query: Optional[str],
    authorization: Optional[str],
) -> Optional[dict]:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "")
    elif token_query:
        raw_token = token_query
    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    if _is_token_revoked(token_hash):
        return None
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            """SELECT u.* FROM users u
               JOIN sessions s ON s.user_id = u.id
               WHERE s.token = $1 AND s.expires_at > $2""",
            token_hash, datetime.now(timezone.utc).isoformat(),
        )
    return dict(user) if user else None


# ASYNC-SAFE
async def validate_token_from_request(
    token_query: Optional[str],
    authorization: Optional[str],
) -> bool:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "")
    elif token_query:
        raw_token = token_query
    if not raw_token:
        return False
    token_hash = _hash_token(raw_token)
    if _is_token_revoked(token_hash):
        return False
    async with get_pool().acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT expires_at FROM sessions WHERE token = $1", token_hash
        )
    if not sess:
        return False
    return datetime.fromisoformat(dict(sess)["expires_at"]) >= datetime.now(timezone.utc)
