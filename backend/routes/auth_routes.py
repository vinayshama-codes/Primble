import hashlib
import hmac
import secrets
import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, Header, Cookie, HTTPException
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from config.database import get_pool
from config.settings import GOOGLE_CLIENT_ID, SESSION_TTL_H as _SESSION_TTL_H
from models.schemas import (
    SignupRequest, LoginRequest, VerifyEmailRequest,
    GoogleAuthRequest, CompleteProfileRequest, UpdateProfileRequest,
)
from services.auth_service import (
    hash_password, verify_password, create_session_token, get_current_user,
    revoke_token, rotate_session, revoke_all_sessions,
    _auth_redis,
)
from services.email_service import send_verification_email, _send_generic_email
from utils.helpers import generate_verification_code
from utils.validators import validate_password
from utils.rate_limiter import check_auth_rate_limit, get_client_ip, _redis as _rate_limiter_redis
from repositories.audit_repository import write_audit_log

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

import os as _os
import httpx as _httpx
_IS_PRODUCTION  = _os.getenv("ENVIRONMENT", "development").lower() == "production"
_COOKIE_SECURE  = _IS_PRODUCTION          # False on localhost (http), True on prod (https)
_COOKIE_SAMESITE = "none" if _IS_PRODUCTION else "lax"

_RECAPTCHA_SECRET = _os.getenv("RECAPTCHA_SECRET_KEY", "")
_RECAPTCHA_MIN_SCORE = float(_os.getenv("RECAPTCHA_MIN_SCORE", "0.5"))

async def _verify_recaptcha(token: str | None) -> None:
    """Verify reCAPTCHA v3 token. Skipped entirely if RECAPTCHA_SECRET_KEY is not set."""
    if not _RECAPTCHA_SECRET or not token:
        return
    try:
        async with _httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={"secret": _RECAPTCHA_SECRET, "response": token},
            )
        result = resp.json()
        if not result.get("success") or result.get("score", 0) < _RECAPTCHA_MIN_SCORE:
            logger.warning(f"reCAPTCHA failed: {result}")
            raise HTTPException(400, "reCAPTCHA verification failed. Please try again.")
    except HTTPException:
        raise
    except Exception as ex:
        logger.warning(f"reCAPTCHA check error (non-blocking): {ex}")

_NONCE_TTL = 300  # seconds

# In-process nonce store used when Redis is unavailable.
# Maps nonce -> (fingerprint, expires_at_monotonic)
_nonce_store: dict = {}

# Pending Google sign-up tokens — holds Google identity until profile is completed.
# Keyed by a random token; expires after 10 minutes.
_PENDING_TOKEN_TTL = 600
_pending_store: dict = {}


def _pending_set(token: str, google_id: str, email: str, name: str) -> None:
    import time as _time, json as _json
    payload = {"google_id": google_id, "email": email, "name": name,
               "expires_at": _time.monotonic() + _PENDING_TOKEN_TTL}
    _pending_store[token] = payload
    if _auth_redis is not None:
        try:
            _auth_redis.setex(f"pending:{token}", _PENDING_TOKEN_TTL, _json.dumps(
                {"google_id": google_id, "email": email, "name": name}
            ))
        except Exception:
            pass


def _pending_pop(token: str) -> dict | None:
    import time as _time, json as _json
    entry = _pending_store.pop(token, None)
    if entry and entry["expires_at"] > _time.monotonic():
        return entry
    if _auth_redis is not None:
        try:
            raw = _auth_redis.getdel(f"pending:{token}")
            if raw:
                return _json.loads(raw)
        except Exception:
            pass
    return None


# Account lockout configuration (SOC 2 CC6.1)
_LOCKOUT_MAX_FAILURES = 10
_LOCKOUT_WINDOW_S     = 900  # 15 minutes
# In-memory fallback: email_hash -> (failure_count, locked_until_monotonic | None)
_lockout_store: dict = {}


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def _nonce_fingerprint(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{ip}:{ua}".encode()).hexdigest()


def _nonce_set(nonce: str, fingerprint: str) -> None:
    if _rate_limiter_redis is not None:
        try:
            _rate_limiter_redis.setex(f"oauth_nonce:{nonce}", _NONCE_TTL, fingerprint)
            return
        except Exception:
            pass
    import time
    _nonce_store[nonce] = (fingerprint, time.monotonic() + _NONCE_TTL)


def _nonce_pop(nonce: str):
    """Return stored fingerprint and remove the nonce atomically. Returns None if not found."""
    if _rate_limiter_redis is not None:
        try:
            return _rate_limiter_redis.getdel(f"oauth_nonce:{nonce}")
        except Exception:
            pass
    import time
    entry = _nonce_store.pop(nonce, None)
    if entry is None:
        return None
    fingerprint, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return fingerprint


# ── Account lockout helpers (SOC 2 CC6.1) ────────────────────────────────────

def _lockout_key(email: str) -> str:
    return f"login_failures:{_email_hash(email)}"


def _check_lockout(email: str) -> None:
    """Raise 429 if the account is currently locked out."""
    key = _lockout_key(email)
    redis = _auth_redis or _rate_limiter_redis
    if redis is not None:
        try:
            val = redis.get(key)
            if val is not None:
                count = int(val)
                if count >= _LOCKOUT_MAX_FAILURES:
                    raise HTTPException(
                        429,
                        "Account temporarily locked. Try again in 15 minutes.",
                    )
            return
        except HTTPException:
            raise
        except Exception:
            pass
    import time
    entry = _lockout_store.get(key)
    if entry:
        count, locked_until = entry
        if locked_until and time.monotonic() < locked_until and count >= _LOCKOUT_MAX_FAILURES:
            raise HTTPException(
                429,
                "Account temporarily locked. Try again in 15 minutes.",
            )


def _record_failed_login(email: str) -> bool:
    """Increment failure counter. Returns True if this attempt triggers lockout."""
    key = _lockout_key(email)
    redis = _auth_redis or _rate_limiter_redis
    if redis is not None:
        try:
            count = redis.incr(key)
            redis.expire(key, _LOCKOUT_WINDOW_S)
            return int(count) >= _LOCKOUT_MAX_FAILURES
        except Exception:
            pass
    import time
    entry = _lockout_store.get(key, (0, None))
    count = entry[0] + 1
    locked_until = time.monotonic() + _LOCKOUT_WINDOW_S if count >= _LOCKOUT_MAX_FAILURES else None
    _lockout_store[key] = (count, locked_until)
    return count >= _LOCKOUT_MAX_FAILURES


def _clear_failed_logins(email: str) -> None:
    key = _lockout_key(email)
    redis = _auth_redis or _rate_limiter_redis
    if redis is not None:
        try:
            redis.delete(key)
            return
        except Exception:
            pass
    _lockout_store.pop(key, None)


def _send_lockout_notification(email: str) -> None:
    subject   = "Acordly: Your account has been temporarily locked"
    body_txt  = (
        "Multiple failed login attempts were detected on your Acordly account.\n\n"
        "Your account has been temporarily locked for 15 minutes as a security precaution.\n\n"
        "If this was you, please wait and try again. If this was not you, consider resetting your password."
    )
    body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
  <h2 style="color:#dc2626;">Security Alert</h2>
  <p>Multiple failed login attempts were detected on your <strong>Acordly</strong> account.</p>
  <p>Your account has been <strong>temporarily locked for 15 minutes</strong> as a security precaution.</p>
  <p style="color:#64748b;font-size:13px;">If this was you, please wait and try again. If this was not you, <a href="#" style="color:#e6007a;">reset your password</a> immediately.</p>
</div>"""
    try:
        _send_generic_email(email, subject, body_txt, body_html)
    except Exception as ex:
        logger.warning(f"Failed to send lockout notification to {email}: {ex}")


# ── Cookie helpers ────────────────────────────────────────────────────────────

def _set_session_cookie(response: JSONResponse, token: str) -> None:
    response.set_cookie(
        key="acordly_session",
        value=token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        max_age=_SESSION_TTL_H * 3600,
        path="/",
    )

def _clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key="acordly_session",
        path="/",
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
    )

# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    check_auth_rate_limit(req.email.lower())
    await _verify_recaptcha(req.recaptcha_token)
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer to create an account.")
    if not req.organization_name or not req.organization_name.strip():
        raise HTTPException(400, "Organization or agency name is required.")
    ok, msg = validate_password(req.password)
    if not ok:
        raise HTTPException(400, msg)

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", req.email)
        if row:
            raise HTTPException(400, "Email already registered")

        now        = datetime.now(timezone.utc).isoformat()
        code       = generate_verification_code()
        expires    = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        pending_id = str(uuid.uuid4())
        try:
            await conn.execute(
                """INSERT INTO pending_signups
                     (id, email, password_hash, full_name, organization_name,
                      verification_code, verification_expires,
                      acord_disclaimer_accepted, acord_disclaimer_accepted_at, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,$9)
                   ON CONFLICT (email) DO UPDATE SET
                     password_hash = EXCLUDED.password_hash,
                     full_name = EXCLUDED.full_name,
                     organization_name = EXCLUDED.organization_name,
                     verification_code = EXCLUDED.verification_code,
                     verification_expires = EXCLUDED.verification_expires,
                     acord_disclaimer_accepted_at = EXCLUDED.acord_disclaimer_accepted_at""",
                pending_id, req.email, hash_password(req.password), req.full_name,
                req.organization_name.strip(), code, expires, now, now,
            )
        except Exception:
            raise HTTPException(500, "Account creation failed. Please try again.")

    send_verification_email(req.email, code)
    return JSONResponse(
        {"success": True, "message": f"Verification code sent to {req.email}.",
         "email": req.email, "requires_verification": True},
        status_code=202,
    )


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, request: Request):
    check_auth_rate_limit(req.email.lower())
    async with get_pool().acquire() as conn:
        existing = await conn.fetchrow("SELECT id, email_verified FROM users WHERE email = $1", req.email)
        if existing and int(dict(existing).get("email_verified", 0) or 0):
            raise HTTPException(400, "Email already verified. Please sign in.")

        row = await conn.fetchrow("SELECT * FROM pending_signups WHERE email = $1", req.email)
        if not row:
            raise HTTPException(404, "No pending signup found. Please sign up again.")
        pending = dict(row)

        if pending.get("verification_code") != req.code:
            raise HTTPException(400, "Invalid verification code.")
        exp = pending.get("verification_expires", "")
        if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
            raise HTTPException(400, "Code has expired. Please request a new one.")

        now     = datetime.now(timezone.utc).isoformat()
        user_id = pending["id"]
        try:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO users
                         (id, email, password_hash, full_name, organization_name,
                          auth_provider, email_verified, acord_disclaimer_accepted,
                          acord_disclaimer_accepted_at, subscription_tier, downloads_used,
                          created_at, last_login)
                       VALUES ($1,$2,$3,$4,$5,'email',1,$6,$7,'free',0,$8,$9)""",
                    user_id, pending["email"], pending["password_hash"],
                    pending.get("full_name", ""), pending.get("organization_name", ""),
                    int(pending.get("acord_disclaimer_accepted", 0) or 0),
                    pending.get("acord_disclaimer_accepted_at", now),
                    pending.get("created_at", now), now,
                )
                await conn.execute("DELETE FROM pending_signups WHERE email = $1", req.email)
        except Exception:
            raise HTTPException(500, "Account creation failed. Please try again.")

    token = await create_session_token(
        user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user_stub = {
        "id": user_id,
        "email": pending["email"],
        "full_name": pending.get("full_name", ""),
        "organization_name": pending.get("organization_name", ""),
        "acord_license_confirmed": 0,
        "acord_disclaimer_accepted": 1,
    }
    await write_audit_log(
        user_stub, "user.signup",
        ip_address=request.client.host if request.client else None,
    )
    resp = JSONResponse({
        "success": True,
        "user": {
            "id": user_id, "email": pending["email"],
            "full_name": pending.get("full_name", ""),
            "organization_name": pending.get("organization_name", ""),
            "subscription_tier": "free", "downloads_remaining": 3,
            "acord_license_confirmed": False,
        },
    })
    _set_session_cookie(resp, token)
    return resp


@router.post("/resend-verification")
async def resend_verification(request: Request):
    body  = await request.json()
    email = body.get("email")
    if not email:
        raise HTTPException(400, "Email required")
    check_auth_rate_limit(str(email).lower())

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pending_signups WHERE email = $1", email)
        if not row:
            u = await conn.fetchrow("SELECT email_verified FROM users WHERE email = $1", email)
            if u and int(dict(u).get("email_verified", 0) or 0):
                raise HTTPException(400, "Email already verified. Please sign in.")
            raise HTTPException(404, "No pending signup found.")
        code    = generate_verification_code()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        await conn.execute(
            "UPDATE pending_signups SET verification_code=$1, verification_expires=$2 WHERE email=$3",
            code, expires, email,
        )

    send_verification_email(email, code)
    return {"success": True, "message": "Code resent"}


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    check_auth_rate_limit(req.email.lower())
    _check_lockout(req.email)

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", req.email)
        if not row or not dict(row).get("password_hash"):
            # Log failed attempt with hashed email — SOC 2 CC7.2
            await write_audit_log(
                {"id": None, "email": _email_hash(req.email.lower()), "organization_name": "",
                 "acord_license_confirmed": 0},
                "user.login_failed",
                ip_address=request.client.host if request.client else None,
            )
            triggered_lockout = _record_failed_login(req.email)
            if triggered_lockout:
                _send_lockout_notification(req.email)
            raise HTTPException(401, "Invalid credentials")
        user = dict(row)
        if not verify_password(req.password, user["password_hash"]):
            # Log failed attempt with hashed email — SOC 2 CC7.2
            await write_audit_log(
                {"id": None, "email": _email_hash(req.email.lower()), "organization_name": "",
                 "acord_license_confirmed": 0},
                "user.login_failed",
                ip_address=request.client.host if request.client else None,
            )
            triggered_lockout = _record_failed_login(req.email)
            if triggered_lockout:
                _send_lockout_notification(req.email)
            raise HTTPException(401, "Invalid credentials")
        if not int(user.get("email_verified", 0) or 0):
            return JSONResponse(
                {"success": False, "requires_verification": True, "email": req.email,
                 "message": "Please verify your email first."},
                status_code=403,
            )
        await conn.execute(
            "UPDATE users SET last_login=$1 WHERE id=$2",
            datetime.now(timezone.utc).isoformat(), user["id"],
        )

    _clear_failed_logins(req.email)
    token = await create_session_token(
        user["id"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await write_audit_log(
        user, "user.login",
        ip_address=request.client.host if request.client else None,
    )
    sub   = user.get("subscription_tier", "free") or "free"
    used  = int(user.get("downloads_used", 0) or 0)
    resp  = JSONResponse({
        "success": True,
        "user": {
            "id": user["id"], "email": user["email"],
            "full_name": user.get("full_name", ""),
            "subscription_tier": sub,
            "downloads_remaining": 3 - used if sub == "free" else -1,
        },
    })
    _set_session_cookie(resp, token)
    return resp


@router.post("/forgot-password")
async def forgot_password(request: Request):
    body  = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email required")
    check_auth_rate_limit(email)

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        if row:
            user      = dict(row)
            code      = generate_verification_code()
            code_hash = hashlib.sha256(code.encode()).hexdigest()
            expires   = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            await conn.execute(
                "UPDATE users SET verification_code=$1, verification_expires=$2 WHERE email=$3",
                code_hash, expires, email,
            )
            provider       = user.get("auth_provider", "email") or "email"
            is_google_only = provider == "google" and not user.get("password_hash")
            subject   = "Set a password for your Acordly account" if is_google_only else "Reset your Acordly password"
            body_txt  = f"Your code: {code}\n\nExpires in 15 minutes."
            body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
  <h2>{'Set your Acordly password' if is_google_only else 'Reset your Acordly password'}</h2>
  <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin:24px 0;">
    <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
  </div>
  <p style="color:#64748b;font-size:13px;">Expires in <strong>15 minutes</strong>.</p>
</div>"""
            _send_generic_email(email, subject, body_txt, body_html)

    return {"success": True, "message": "If that email is registered, a reset code has been sent."}


@router.post("/reset-password")
async def reset_password(request: Request):
    body     = await request.json()
    email    = (body.get("email") or "").strip().lower()
    code     = (body.get("code") or "").strip()
    new_pass = body.get("new_password") or ""
    if not email or not code or not new_pass:
        raise HTTPException(400, "email, code, and new_password are required")
    check_auth_rate_limit(email)
    valid_pw, pw_msg = validate_password(new_pass)
    if not valid_pw:
        raise HTTPException(400, pw_msg)

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        if not row:
            raise HTTPException(400, "Invalid request")
        user           = dict(row)
        stored_code    = user.get("verification_code", "")
        stored_expires = user.get("verification_expires", "")
        submitted_hash = hashlib.sha256(code.encode()).hexdigest()
        if not stored_code or not hmac.compare_digest(stored_code, submitted_hash):
            raise HTTPException(400, "Invalid reset code")
        try:
            if datetime.fromisoformat(stored_expires) < datetime.now(timezone.utc):
                raise HTTPException(400, "Reset code has expired")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Reset code invalid")
        await conn.execute(
            "UPDATE users SET password_hash=$1, verification_code=NULL, verification_expires=NULL, email_verified=1 WHERE email=$2",
            hash_password(new_pass), email,
        )

    await revoke_all_sessions(user["id"])
    await write_audit_log(
        user, "user.password_reset",
        ip_address=request.client.host if request.client else None,
    )

    # Notify the user that their password was changed (SOC 2 CC6.1)
    try:
        _send_generic_email(
            email,
            "Your Acordly password was changed",
            "Your Acordly account password was successfully changed. If you did not do this, please contact support immediately.",
            """<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
  <h2>Password Changed</h2>
  <p>Your <strong>Acordly</strong> account password was successfully changed.</p>
  <p style="color:#dc2626;">If you did not make this change, please contact support immediately and reset your password.</p>
</div>""",
        )
    except Exception as ex:
        logger.warning(f"Failed to send password-change notification to {email}: {ex}")

    return {"success": True, "message": "Password updated successfully."}


@router.get("/google/nonce")
async def google_nonce(request: Request):
    """Issue a one-time nonce the frontend must include as the OAuth state parameter."""
    check_auth_rate_limit(get_client_ip(request))
    nonce = secrets.token_urlsafe(32)
    _nonce_set(nonce, _nonce_fingerprint(request))
    return {"nonce": nonce}


@router.post("/google")
async def google_auth(req: GoogleAuthRequest, request: Request):
    check_auth_rate_limit(get_client_ip(request))
    try:
        # Validate state/nonce if the frontend sends one
        nonce = req.nonce
        if nonce:
            stored_fp = _nonce_pop(nonce)
            if stored_fp is None:
                raise HTTPException(400, "Invalid or missing OAuth state/nonce")
            if stored_fp != _nonce_fingerprint(request):
                raise HTTPException(400, "OAuth nonce fingerprint mismatch")

        cid    = GOOGLE_CLIENT_ID
        idinfo = id_token.verify_oauth2_token(req.credential, google_requests.Request(), cid, clock_skew_in_seconds=5)
        if idinfo.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Invalid issuer")
        if idinfo.get("aud") != cid:
            raise ValueError("Invalid audience")
        google_id = idinfo["sub"]
        email     = idinfo.get("email")
        name      = idinfo.get("name", email)
        if not email:
            raise ValueError("No email in token")

        async with get_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE google_id = $1", google_id)
            if not row:
                row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
                if row:
                    # Existing email-signup user connecting Google for the first time
                    uid = dict(row)["id"]
                    await conn.execute(
                        "UPDATE users SET google_id=$1, auth_provider='google', email_verified=1 WHERE id=$2",
                        google_id, uid,
                    )
                    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)
                else:
                    # Brand-new user — don't create the record yet; require profile completion first
                    pending_token = secrets.token_urlsafe(32)
                    _pending_set(pending_token, google_id, email, name)
                    return JSONResponse({
                        "success": True,
                        "profile_incomplete": True,
                        "pending_token": pending_token,
                        "user": {"email": email, "full_name": name},
                    })

            user = dict(row)
            await conn.execute(
                "UPDATE users SET last_login=$1 WHERE id=$2",
                datetime.now(timezone.utc).isoformat(), user["id"],
            )

        token              = await create_session_token(
            user["id"],
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await write_audit_log(
            user, "user.oauth_login",
            ip_address=request.client.host if request.client else None,
        )
        sub                = user.get("subscription_tier", "free") or "free"
        used               = int(user.get("downloads_used", 0) or 0)
        org_name           = user.get("organization_name") or ""
        disclaimer         = int(user.get("acord_disclaimer_accepted", 0) or 0)
        profile_incomplete = not org_name.strip() or not disclaimer
        if profile_incomplete:
            # Existing user with incomplete profile — issue pending token, no session yet
            pending_token = secrets.token_urlsafe(32)
            _pending_set(pending_token, google_id, email, name)
            return JSONResponse({
                "success": True,
                "profile_incomplete": True,
                "pending_token": pending_token,
                "user": {"email": email, "full_name": name},
            })
        resp = JSONResponse({
            "success": True, "profile_incomplete": False,
            "user": {
                "id": user["id"], "email": user["email"],
                "full_name": user.get("full_name", ""),
                "organization_name": org_name, "subscription_tier": sub,
                "downloads_remaining": 3 - used if sub == "free" else -1,
                "acord_license_confirmed": bool(int(user.get("acord_license_confirmed", 0) or 0)),
                "acord_disclaimer_accepted": bool(disclaimer),
            },
        })
        _set_session_cookie(resp, token)
        return resp
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Authentication failed. Please try again.")


@router.post("/complete-profile")
async def complete_profile(
    req: CompleteProfileRequest,
    request: Request,
    acordly_session: str = Cookie(None),
):
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer.")
    if not req.organization_name or not req.organization_name.strip():
        raise HTTPException(400, "Organization name is required.")
    now = datetime.now(timezone.utc).isoformat()
    ip  = request.client.host if request.client else None
    ua  = request.headers.get("user-agent")

    if req.pending_token:
        # New Google user — verify pending token then INSERT the record
        identity = _pending_pop(req.pending_token)
        if not identity:
            raise HTTPException(400, "Sign-up session expired. Please sign in with Google again.")
        uid = str(uuid.uuid4())
        async with get_pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO users "
                "(id, email, google_id, full_name, auth_provider, email_verified, "
                " organization_name, acord_disclaimer_accepted, acord_disclaimer_accepted_at, "
                " created_at, last_login) "
                "VALUES ($1,$2,$3,$4,'google',1,$5,1,$6,$7,$8)",
                uid, identity["email"], identity["google_id"], identity["name"],
                req.organization_name.strip(), now, now, now,
            )
            row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)
        user = dict(row)
        await write_audit_log(user, "user.oauth_signup", ip_address=ip)
        token = await create_session_token(uid, ip_address=ip, user_agent=ua)
        resp  = JSONResponse({
            "success": True,
            "user": {
                "id": user["id"], "email": user["email"],
                "full_name": user.get("full_name", ""),
                "organization_name": req.organization_name.strip(),
                "subscription_tier": "free", "downloads_remaining": 3,
                "acord_license_confirmed": False, "acord_disclaimer_accepted": True,
            },
        })
        _set_session_cookie(resp, token)
        return resp

    # Existing user updating their profile (session-cookie path)
    from services.auth_service import get_current_user as _get_current_user
    current_user = await _get_current_user(acordly_session=acordly_session)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET organization_name=$1, acord_disclaimer_accepted=1, "
            "acord_disclaimer_accepted_at=$2 WHERE id=$3",
            req.organization_name.strip(), now, current_user["id"],
        )
    resp = JSONResponse({"success": True, "message": "Profile updated."})
    if acordly_session:
        new_token = await rotate_session(acordly_session, ip_address=ip, user_agent=ua)
        _set_session_cookie(resp, new_token)
    return resp


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    import stripe as stripe_lib
    sub         = current_user.get("subscription_tier", "free") or "free"
    used        = int(current_user.get("downloads_used", 0) or 0)
    pkgs_used   = int(current_user.get("packages_used", 0) or 0)
    pkgs_limit  = int(current_user.get("packages_limit", 0) or 0)
    soft_buffer = int(pkgs_limit * 0.05) if pkgs_limit > 0 else 0

    customer_id   = current_user.get("stripe_customer_id")
    stored_sub_id = current_user.get("stripe_subscription_id")
    if customer_id and sub not in ("free", None):
        try:
            from config.settings import PLANS as _PLANS
            active_subs = stripe_lib.Subscription.list(customer=customer_id, status="active", limit=1)
            real_sub    = active_subs.data[0] if active_subs.data else None
            real_sub_id = getattr(real_sub, "id", None) if real_sub else None
            if real_sub_id and real_sub_id != stored_sub_id:
                raw_meta     = getattr(real_sub, "metadata", None) or {}
                stripe_plan  = (raw_meta.get("plan") if isinstance(raw_meta, dict) else getattr(raw_meta, "plan", None))
                stripe_cycle = (raw_meta.get("billing_cycle") if isinstance(raw_meta, dict) else getattr(raw_meta, "billing_cycle", None)) or "monthly"
                async with get_pool().acquire() as conn:
                    if stripe_plan and stripe_plan in _PLANS and stripe_plan != sub:
                        cfg = _PLANS[stripe_plan].get(stripe_cycle) or _PLANS[stripe_plan]["monthly"]
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc).isoformat()
                        await conn.execute(
                            """UPDATE users SET stripe_subscription_id=$1, subscription_tier=$2,
                               billing_cycle=$3, packages_limit=$4, overage_rate=$5,
                               packages_used=0, billing_period_start=$6,
                               payment_status='ok', payment_failed_at=NULL WHERE id=$7""",
                            real_sub_id, stripe_plan, stripe_cycle,
                            cfg["packages"], cfg["overage_rate"], now, current_user["id"],
                        )
                        sub        = stripe_plan
                        pkgs_limit = cfg["packages"]
                        pkgs_used  = 0
                    else:
                        await conn.execute(
                            "UPDATE users SET stripe_subscription_id=$1 WHERE id=$2",
                            real_sub_id, current_user["id"],
                        )
                stored_sub_id = real_sub_id
        except Exception:
            pass

    return {
        "id": current_user["id"], "email": current_user["email"],
        "full_name": current_user.get("full_name", ""),
        "organization_name": current_user.get("organization_name", ""),
        "subscription_tier": sub,
        "billing_cycle": current_user.get("billing_cycle", "monthly") or "monthly",
        "downloads_remaining": 3 - used if sub == "free" else -1,
        "packages_used": pkgs_used, "packages_limit": pkgs_limit,
        "packages_soft_buffer": soft_buffer,
        "overage_packages_pending": int(current_user.get("overage_packages_pending", 0) or 0),
        "email_verified": bool(int(current_user.get("email_verified", 0) or 0)),
        "acord_license_confirmed": bool(int(current_user.get("acord_license_confirmed", 0) or 0)),
        "acord_disclaimer_accepted": bool(int(current_user.get("acord_disclaimer_accepted", 0) or 0)),
        "payment_status": current_user.get("payment_status", "ok") or "ok",
        "payment_failed_at": current_user.get("payment_failed_at"),
        "overage_rate": int(current_user.get("overage_rate", 0) or 0),
    }


@router.patch("/update-profile")
async def update_profile(
    req: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    updates = {}
    if req.full_name is not None:
        updates["full_name"] = req.full_name.strip()
    if req.organization_name is not None:
        updates["organization_name"] = req.organization_name.strip()
    if not updates:
        raise HTTPException(400, "No fields to update.")
    set_clause = ", ".join(f"{k}=${i+1}" for i, k in enumerate(updates))
    values = list(updates.values()) + [current_user["id"]]
    async with get_pool().acquire() as conn:
        await conn.execute(
            f"UPDATE users SET {set_clause} WHERE id=${len(values)}",
            *values,
        )
    return {"success": True, **updates}


@router.post("/contact")
async def contact_primble(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    body = await request.json()
    from_email = (body.get("from_email") or "").strip()
    subject    = (body.get("subject") or "").strip()
    message    = (body.get("message") or "").strip()
    if not subject or not message:
        raise HTTPException(400, "Subject and message are required.")
    full_msg = (
        f"From: {current_user.get('full_name', '')} <{from_email or current_user['email']}>\n"
        f"User ID: {current_user['id']}\n\n"
        f"{message}"
    )
    _send_generic_email(
        to_email="info@primble.com",
        subject=f"[Primble Contact] {subject}",
        body_txt=full_msg,
        body_html=f"<pre style='font-family:sans-serif;white-space:pre-wrap'>{full_msg}</pre>",
    )
    return {"success": True}


@router.post("/logout")
async def logout(
    request: Request,
    authorization: str = Header(None),
    acordly_session: str = Cookie(None),
    current_user: dict = Depends(get_current_user),
):
    token = acordly_session
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    if token:
        await revoke_token(token)
    await write_audit_log(
        current_user, "user.logout",
        ip_address=request.client.host if request.client else None,
    )
    resp = JSONResponse({"success": True})
    _clear_session_cookie(resp)
    return resp


# ── GDPR / SOC 2 user-rights endpoints ───────────────────────────────────────

@router.delete("/delete-account")
async def delete_account(
    request: Request,
    current_user: dict = Depends(get_current_user),
    acordly_session: str = Cookie(None),
    authorization: str = Header(None),
):
    """
    Permanently delete the caller's account.

    Request body: { "password": "<current password>" }
    Google-only accounts (no password_hash) skip the password check.
    All user PII and related data are cascade-deleted; the Stripe subscription
    is cancelled immediately if one exists.
    """
    body = await request.json()
    provided_pw = body.get("password") or ""

    # Password confirmation — skip for Google-only accounts
    has_password = bool(current_user.get("password_hash"))
    if has_password:
        if not provided_pw:
            raise HTTPException(400, "Password confirmation is required to delete your account.")
        if not verify_password(provided_pw, current_user["password_hash"]):
            raise HTTPException(403, "Incorrect password.")

    user_id     = current_user["id"]
    email       = current_user.get("email", "")
    customer_id = current_user.get("stripe_customer_id")
    sub_id      = current_user.get("stripe_subscription_id")

    # Cancel Stripe subscription immediately
    if customer_id or sub_id:
        try:
            import stripe as _stripe
            if sub_id:
                try:
                    _stripe.Subscription.cancel(sub_id)
                    logger.info(f"delete_account: cancelled Stripe sub {sub_id} for user {user_id}")
                except Exception as se:
                    logger.warning(f"delete_account: could not cancel sub {sub_id}: {se}")
            else:
                subs = _stripe.Subscription.list(customer=customer_id, status="active", limit=10)
                for s in subs.data:
                    try:
                        _stripe.Subscription.cancel(s.id)
                    except Exception as se:
                        logger.warning(f"delete_account: could not cancel sub {s.id}: {se}")
        except Exception as ex:
            logger.warning(f"delete_account: Stripe cancellation error for user {user_id}: {ex}")

    # Revoke all sessions
    token = acordly_session
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    await revoke_all_sessions(user_id)

    # Audit log before deletion (so we have a record)
    await write_audit_log(
        current_user, "user.account_deleted",
        ip_address=request.client.host if request.client else None,
    )

    # Cascade-delete all user data
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM sessions            WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM processing_sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM applied_overage_sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM arq_sessions        WHERE user_id = $1", user_id)
            # Anonymize audit log rows rather than deleting (preserves the deletion record)
            await conn.execute(
                """UPDATE acord_audit_log
                   SET user_email = '[deleted]', organization_name = '[deleted]'
                   WHERE user_id = $1""",
                user_id,
            )
            # Hard-delete the user row; cascade handles FK-linked tables
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)

    logger.info(f"delete_account: user {user_id} ({email}) deleted their account")
    resp = JSONResponse({"success": True, "message": "Account deleted."})
    _clear_session_cookie(resp)
    return resp


@router.get("/data-export")
async def data_export(
    current_user: dict = Depends(get_current_user),
):
    """
    GDPR Art. 20 data portability — return all data held for this user.
    """
    user_id = current_user["id"]

    async with get_pool().acquire() as conn:
        sessions_rows = await conn.fetch(
            """SELECT id, created_at, last_used_at, expires_at, ip_address, user_agent
               FROM sessions WHERE user_id = $1 ORDER BY created_at DESC""",
            user_id,
        )
        audit_rows = await conn.fetch(
            """SELECT id, action, form_id, form_name, ip_address, timestamp
               FROM acord_audit_log WHERE user_id = $1 ORDER BY timestamp DESC LIMIT 500""",
            user_id,
        )
        ps_rows = await conn.fetch(
            """SELECT id, form_type, status, created_at, updated_at
               FROM processing_sessions WHERE user_id = $1 ORDER BY created_at DESC""",
            user_id,
        )

    # Redact sensitive columns from the user profile before exporting
    profile = {k: v for k, v in current_user.items() if k not in (
        "password_hash", "verification_code", "verification_expires",
    )}

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {k: (str(v) if v is not None else None) for k, v in profile.items()},
        "sessions": [dict(r) for r in sessions_rows],
        "audit_log": [dict(r) for r in audit_rows],
        "form_submissions": [dict(r) for r in ps_rows],
    }
