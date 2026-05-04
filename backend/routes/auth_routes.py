import hashlib
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
    GoogleAuthRequest, CompleteProfileRequest,
)
from services.auth_service import (
    hash_password, verify_password, create_session_token, get_current_user,
    revoke_token, rotate_session, revoke_all_sessions,
)
from services.email_service import send_verification_email, _send_generic_email
from utils.helpers import generate_verification_code
from utils.validators import validate_work_email, validate_password
from utils.rate_limiter import check_auth_rate_limit, get_client_ip, _redis as _rate_limiter_redis

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

import os as _os
_IS_PRODUCTION  = _os.getenv("ENVIRONMENT", "development").lower() == "production"
_COOKIE_SECURE  = _IS_PRODUCTION          # False on localhost (http), True on prod (https)
_COOKIE_SAMESITE = "lax"

_NONCE_TTL = 300  # seconds

# In-process nonce store used when Redis is unavailable.
# Maps nonce -> (fingerprint, expires_at_monotonic)
_nonce_store: dict = {}

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
    response.delete_cookie(key="acordly_session", path="/")


@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    check_auth_rate_limit(req.email.lower())
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer to create an account.")
    ok_email, email_msg = validate_work_email(req.email)
    if not ok_email:
        raise HTTPException(400, email_msg)
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
    resp  = JSONResponse({
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

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", req.email)
        if not row or not dict(row).get("password_hash"):
            raise HTTPException(401, "Invalid credentials")
        user = dict(row)
        if not verify_password(req.password, user["password_hash"]):
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

    token = await create_session_token(
        user["id"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
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
            user    = dict(row)
            code    = generate_verification_code()
            expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            await conn.execute(
                "UPDATE users SET verification_code=$1, verification_expires=$2 WHERE email=$3",
                code, expires, email,
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
        if not stored_code or stored_code != code:
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
        # Validate state/nonce sent by the frontend
        nonce = getattr(req, "nonce", None)
        if not nonce:
            raise HTTPException(400, "Invalid or missing OAuth state/nonce")
        stored_fp = _nonce_pop(nonce)
        if stored_fp is None:
            raise HTTPException(400, "Invalid or missing OAuth state/nonce")
        if stored_fp != _nonce_fingerprint(request):
            raise HTTPException(400, "OAuth nonce fingerprint mismatch")

        cid    = GOOGLE_CLIENT_ID
        idinfo = id_token.verify_oauth2_token(req.credential, google_requests.Request(), cid, clock_skew_in_seconds=10)
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
                    uid = dict(row)["id"]
                    await conn.execute(
                        "UPDATE users SET google_id=$1, auth_provider='google', email_verified=1 WHERE id=$2",
                        google_id, uid,
                    )
                    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)
                else:
                    uid = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    await conn.execute(
                        "INSERT INTO users (id, email, google_id, full_name, auth_provider, email_verified, created_at, last_login) "
                        "VALUES ($1,$2,$3,$4,'google',1,$5,$6)",
                        uid, email, google_id, name, now, now,
                    )
                    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)

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
        sub                = user.get("subscription_tier", "free") or "free"
        used               = int(user.get("downloads_used", 0) or 0)
        org_name           = user.get("organization_name") or ""
        disclaimer         = int(user.get("acord_disclaimer_accepted", 0) or 0)
        profile_incomplete = not org_name.strip() or not disclaimer
        resp = JSONResponse({
            "success": True, "profile_incomplete": profile_incomplete,
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
    current_user: dict = Depends(get_current_user),
):
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer.")
    if not req.organization_name or not req.organization_name.strip():
        raise HTTPException(400, "Organization name is required.")
    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET organization_name=$1, acord_disclaimer_accepted=1, acord_disclaimer_accepted_at=$2 WHERE id=$3",
            req.organization_name.strip(), now, current_user["id"],
        )

    resp = JSONResponse({"success": True, "message": "Profile updated."})
    if acordly_session:
        new_token = await rotate_session(
            acordly_session,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
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


@router.post("/logout")
async def logout(
    authorization: str = Header(None),
    acordly_session: str = Cookie(None),
):
    token = acordly_session
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    if token:
        await revoke_token(token)
    resp = JSONResponse({"success": True})
    _clear_session_cookie(resp)
    return resp
