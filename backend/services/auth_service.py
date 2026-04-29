import secrets
import uuid
import logging
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Header
from config.database import get_db

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_session_token(user_id: str) -> str:
    conn  = get_db()
    cur   = conn.cursor()
    token = secrets.token_urlsafe(32)
    exp   = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    cur.execute(
        "INSERT INTO sessions (id, user_id, token, expires_at, created_at) VALUES (%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), user_id, token, exp, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()
    return token


def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.replace("Bearer ", "")
    conn  = get_db()
    cur   = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE token = %s", (token,))
    session = cur.fetchone()
    if not session:
        cur.close()
        conn.close()
        raise HTTPException(401, "Invalid token")
    session = dict(session)
    if datetime.fromisoformat(session["expires_at"]) < datetime.now(timezone.utc):
        cur.close()
        conn.close()
        raise HTTPException(401, "Session expired")
    cur.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user:
        raise HTTPException(401, "User not found")
    user     = dict(user)
    provider = user.get("auth_provider", "email") or "email"
    verified = int(user.get("email_verified", 0) or 0)
    if provider == "email" and not verified:
        raise HTTPException(403, "Email not verified.")
    return user


def get_user_from_token_request(token_query: Optional[str], authorization: Optional[str]) -> Optional[dict]:
    """Validate token and return the associated user dict, or None if invalid/expired."""
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "")
    elif token_query:
        raw_token = token_query
    if not raw_token:
        return None
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """SELECT u.* FROM users u
           JOIN sessions s ON s.user_id = u.id
           WHERE s.token = %s AND s.expires_at > %s""",
        (raw_token, datetime.now(timezone.utc).isoformat()),
    )
    user = cur.fetchone()
    cur.close()
    conn.close()
    return dict(user) if user else None


def validate_token_from_request(token_query: Optional[str], authorization: Optional[str]) -> bool:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "")
    elif token_query:
        raw_token = token_query
    if not raw_token:
        return False
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT expires_at FROM sessions WHERE token = %s", (raw_token,))
    sess = cur.fetchone()
    cur.close()
    conn.close()
    if not sess:
        return False
    return datetime.fromisoformat(dict(sess)["expires_at"]) >= datetime.now(timezone.utc)