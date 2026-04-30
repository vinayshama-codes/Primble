import secrets
import uuid
import logging
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Header
from config.database import get_pool

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ASYNC-SAFE
async def create_session_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    exp   = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, user_id, token, expires_at, created_at)"
            " VALUES ($1,$2,$3,$4,$5)",
            str(uuid.uuid4()), user_id, token, exp,
            datetime.now(timezone.utc).isoformat(),
        )
    return token


# ASYNC-SAFE
async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.replace("Bearer ", "")
    async with get_pool().acquire() as conn:
        session = await conn.fetchrow(
            "SELECT * FROM sessions WHERE token = $1", token
        )
        if not session:
            raise HTTPException(401, "Invalid token")
        session = dict(session)
        if datetime.fromisoformat(session["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(401, "Session expired")
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
    return user


# ASYNC-SAFE
async def get_user_from_token_request(
    token_query: Optional[str],
    authorization: Optional[str],
) -> Optional[dict]:
    """Validate token and return the associated user dict, or None if invalid/expired."""
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "")
    elif token_query:
        raw_token = token_query
    if not raw_token:
        return None
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            """SELECT u.* FROM users u
               JOIN sessions s ON s.user_id = u.id
               WHERE s.token = $1 AND s.expires_at > $2""",
            raw_token, datetime.now(timezone.utc).isoformat(),
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
    async with get_pool().acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT expires_at FROM sessions WHERE token = $1", raw_token
        )
    if not sess:
        return False
    return datetime.fromisoformat(dict(sess)["expires_at"]) >= datetime.now(timezone.utc)
