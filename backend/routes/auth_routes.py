import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request,  Header
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from config.database import get_db
from config.settings import GOOGLE_CLIENT_ID
from models.schemas import (
    SignupRequest, LoginRequest, VerifyEmailRequest,
    GoogleAuthRequest, CompleteProfileRequest,
)
from services.auth_service import (
    hash_password, verify_password, create_session_token, get_current_user,
)
from services.email_service import send_verification_email, _send_generic_email
from utils.helpers import generate_verification_code
from utils.validators import validate_work_email, validate_password
from utils.rate_limiter import check_auth_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/signup")
async def signup(req: SignupRequest):
    if not req.acord_disclaimer_accepted:
        from fastapi import HTTPException
        raise HTTPException(400, "You must accept the ACORD disclaimer to create an account.")
    ok_email, email_msg = validate_work_email(req.email)
    if not ok_email:
        from fastapi import HTTPException
        raise HTTPException(400, email_msg)
    if not req.organization_name or not req.organization_name.strip():
        from fastapi import HTTPException
        raise HTTPException(400, "Organization or agency name is required.")
    ok, msg = validate_password(req.password)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(400, msg)

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    if cur.fetchone():
        cur.close(); conn.close()
        from fastapi import HTTPException
        raise HTTPException(400, "Email already registered")

    now     = datetime.now(timezone.utc).isoformat()
    code    = generate_verification_code()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    pending_id = str(uuid.uuid4())

    try:
        cur.execute("""
            INSERT INTO pending_signups
              (id, email, password_hash, full_name, organization_name,
               verification_code, verification_expires,
               acord_disclaimer_accepted, acord_disclaimer_accepted_at, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
            ON CONFLICT (email) DO UPDATE SET
              password_hash = EXCLUDED.password_hash, full_name = EXCLUDED.full_name,
              organization_name = EXCLUDED.organization_name,
              verification_code = EXCLUDED.verification_code,
              verification_expires = EXCLUDED.verification_expires,
              acord_disclaimer_accepted_at = EXCLUDED.acord_disclaimer_accepted_at
        """, (pending_id, req.email, hash_password(req.password), req.full_name,
              req.organization_name.strip(), code, expires, now, now))
        conn.commit()
    except Exception as ex:
        cur.close(); conn.close()
        from fastapi import HTTPException
        raise HTTPException(500, "Account creation failed. Please try again.")
    finally:
        try: cur.close(); conn.close()
        except: pass

    send_verification_email(req.email, code)
    return JSONResponse({"success": True, "message": f"Verification code sent to {req.email}.",
                         "email": req.email, "requires_verification": True}, status_code=202)


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    from fastapi import HTTPException
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, email_verified FROM users WHERE email = %s", (req.email,))
    existing = cur.fetchone()
    if existing and int(dict(existing).get("email_verified", 0) or 0):
        cur.close(); conn.close()
        raise HTTPException(400, "Email already verified. Please sign in.")
    cur.execute("SELECT * FROM pending_signups WHERE email = %s", (req.email,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(404, "No pending signup found. Please sign up again.")
    pending = dict(row)
    if pending.get("verification_code") != req.code:
        cur.close(); conn.close()
        raise HTTPException(400, "Invalid verification code.")
    exp = pending.get("verification_expires", "")
    if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
        cur.close(); conn.close()
        raise HTTPException(400, "Code has expired. Please request a new one.")
    now     = datetime.now(timezone.utc).isoformat()
    user_id = pending["id"]
    try:
        cur.execute("""
            INSERT INTO users (id, email, password_hash, full_name, organization_name,
               auth_provider, email_verified, acord_disclaimer_accepted, acord_disclaimer_accepted_at,
               subscription_tier, downloads_used, created_at, last_login)
            VALUES (%s,%s,%s,%s,%s,'email',1,%s,%s,'free',0,%s,%s)
        """, (user_id, pending["email"], pending["password_hash"], pending.get("full_name",""),
              pending.get("organization_name",""), int(pending.get("acord_disclaimer_accepted",0) or 0),
              pending.get("acord_disclaimer_accepted_at", now), pending.get("created_at", now), now))
        cur.execute("DELETE FROM pending_signups WHERE email = %s", (req.email,))
        conn.commit()
    except Exception as ex:
        conn.rollback(); cur.close(); conn.close()
        raise HTTPException(500, "Account creation failed. Please try again.")
    finally:
        try: cur.close(); conn.close()
        except: pass
    token = create_session_token(user_id)
    return {"success": True, "token": token,
            "user": {"id": user_id, "email": pending["email"], "full_name": pending.get("full_name",""),
                     "organization_name": pending.get("organization_name",""), "subscription_tier": "free",
                     "downloads_remaining": 3, "acord_license_confirmed": False}}


@router.post("/resend-verification")
async def resend_verification(request: Request):
    from fastapi import HTTPException
    body  = await request.json()
    email = body.get("email")
    if not email:
        raise HTTPException(400, "Email required")
    check_auth_rate_limit(str(email).lower())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM pending_signups WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT email_verified FROM users WHERE email = %s", (email,))
        u = cur.fetchone(); cur.close(); conn.close()
        if u and int(dict(u).get("email_verified", 0) or 0):
            raise HTTPException(400, "Email already verified. Please sign in.")
        raise HTTPException(404, "No pending signup found.")
    code    = generate_verification_code()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    cur.execute("UPDATE pending_signups SET verification_code=%s, verification_expires=%s WHERE email=%s", (code, expires, email))
    conn.commit(); cur.close(); conn.close()
    send_verification_email(email, code)
    return {"success": True, "message": "Code resent"}


@router.post("/login")
async def login(req: LoginRequest):
    from fastapi import HTTPException
    check_auth_rate_limit(req.email.lower())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    row = cur.fetchone()
    if not row or not dict(row).get("password_hash"):
        cur.close(); conn.close()
        raise HTTPException(401, "Invalid credentials")
    user = dict(row)
    if not verify_password(req.password, user["password_hash"]):
        cur.close(); conn.close()
        raise HTTPException(401, "Invalid credentials")
    if not int(user.get("email_verified", 0) or 0):
        cur.close(); conn.close()
        return JSONResponse({"success": False, "requires_verification": True, "email": req.email,
                             "message": "Please verify your email first."}, status_code=403)
    cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (datetime.now(timezone.utc).isoformat(), user["id"]))
    conn.commit(); cur.close(); conn.close()
    token = create_session_token(user["id"])
    sub   = user.get("subscription_tier", "free") or "free"
    used  = int(user.get("downloads_used", 0) or 0)
    return {"success": True, "token": token,
            "user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name",""),
                     "subscription_tier": sub, "downloads_remaining": 3 - used if sub == "free" else -1}}


@router.post("/forgot-password")
async def forgot_password(request: Request):
    body  = await request.json()
    email = (body.get("email") or "").strip().lower()
    if email:
        check_auth_rate_limit(email)
    if not email:
        from fastapi import HTTPException
        raise HTTPException(400, "Email required")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row  = cur.fetchone(); cur.close(); conn.close()
    if row:
        user    = dict(row)
        code    = generate_verification_code()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        conn2   = get_db(); cur2 = conn2.cursor()
        cur2.execute("UPDATE users SET verification_code=%s, verification_expires=%s WHERE email=%s", (code, expires, email))
        conn2.commit(); cur2.close(); conn2.close()
        provider      = user.get("auth_provider", "email") or "email"
        is_google_only = provider == "google" and not user.get("password_hash")
        subject  = "Set a password for your Acordly account" if is_google_only else "Reset your Acordly password"
        body_txt = f"Your code: {code}\n\nExpires in 15 minutes."
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
    from fastapi import HTTPException
    body     = await request.json()
    email    = (body.get("email") or "").strip().lower()
    code     = (body.get("code") or "").strip()
    new_pass = body.get("new_password") or ""
    if not email or not code or not new_pass:
        raise HTTPException(400, "email, code, and new_password are required")
    valid_pw, pw_msg = validate_password(new_pass)
    if not valid_pw:
        raise HTTPException(400, pw_msg)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(400, "Invalid request")
    user           = dict(row)
    stored_code    = user.get("verification_code", "")
    stored_expires = user.get("verification_expires", "")
    if not stored_code or stored_code != code:
        cur.close(); conn.close()
        raise HTTPException(400, "Invalid reset code")
    try:
        if datetime.fromisoformat(stored_expires) < datetime.now(timezone.utc):
            cur.close(); conn.close()
            raise HTTPException(400, "Reset code has expired")
    except Exception:
        cur.close(); conn.close()
        raise HTTPException(400, "Reset code invalid")
    cur.execute("UPDATE users SET password_hash=%s, verification_code=NULL, verification_expires=NULL, email_verified=1 WHERE email=%s",
                (hash_password(new_pass), email))
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "message": "Password updated successfully."}


@router.post("/google")
async def google_auth(req: GoogleAuthRequest):
    from fastapi import HTTPException
    try:
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
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                uid = dict(row)["id"]
                cur.execute("UPDATE users SET google_id=%s, auth_provider='google', email_verified=1 WHERE id=%s", (google_id, uid))
                conn.commit()
                cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
            else:
                uid = str(uuid.uuid4()); now = datetime.now(timezone.utc).isoformat()
                cur.execute("INSERT INTO users (id, email, google_id, full_name, auth_provider, email_verified, created_at, last_login) VALUES (%s,%s,%s,%s,'google',1,%s,%s)", (uid, email, google_id, name, now, now))
                conn.commit()
                cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
        user = dict(row)
        cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (datetime.now(timezone.utc).isoformat(), user["id"]))
        conn.commit(); cur.close(); conn.close()
        token              = create_session_token(user["id"])
        sub                = user.get("subscription_tier", "free") or "free"
        used               = int(user.get("downloads_used", 0) or 0)
        org_name           = user.get("organization_name") or ""
        disclaimer         = int(user.get("acord_disclaimer_accepted", 0) or 0)
        profile_incomplete = not org_name.strip() or not disclaimer
        return {"success": True, "token": token, "profile_incomplete": profile_incomplete,
                "user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name",""),
                         "organization_name": org_name, "subscription_tier": sub,
                         "downloads_remaining": 3 - used if sub == "free" else -1,
                         "acord_license_confirmed": bool(int(user.get("acord_license_confirmed",0) or 0)),
                         "acord_disclaimer_accepted": bool(disclaimer)}}
    except ValueError as e:
        raise HTTPException(401, "Authentication failed. Please try again.")
    except Exception as e:
        raise HTTPException(401, "Authentication failed. Please try again.")


@router.post("/complete-profile")
async def complete_profile(req: CompleteProfileRequest, current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer.")
    if not req.organization_name or not req.organization_name.strip():
        raise HTTPException(400, "Organization name is required.")
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET organization_name=%s, acord_disclaimer_accepted=1, acord_disclaimer_accepted_at=%s WHERE id=%s",
                (req.organization_name.strip(), now, current_user["id"]))
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "message": "Profile updated."}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    import stripe as stripe_lib
    sub  = current_user.get("subscription_tier", "free") or "free"
    used = int(current_user.get("downloads_used", 0) or 0)
    pkgs_used   = int(current_user.get("packages_used", 0) or 0)
    pkgs_limit  = int(current_user.get("packages_limit", 0) or 0)
    soft_buffer = int(pkgs_limit * 0.05) if pkgs_limit > 0 else 0

    # Auto-sync subscription data from Stripe if the active sub ID has changed
    customer_id = current_user.get("stripe_customer_id")
    stored_sub_id = current_user.get("stripe_subscription_id")
    if customer_id and sub not in ("free", None):
        try:
            from config.settings import PLANS as _PLANS
            active_subs = stripe_lib.Subscription.list(customer=customer_id, status="active", limit=1)
            real_sub = active_subs.data[0] if active_subs.data else None
            real_sub_id = getattr(real_sub, "id", None) if real_sub else None
            if real_sub_id and real_sub_id != stored_sub_id:
                # Subscription ID changed — also sync plan/tier from Stripe metadata
                raw_meta = getattr(real_sub, "metadata", None) or {}
                stripe_plan = (raw_meta.get("plan") if isinstance(raw_meta, dict) else getattr(raw_meta, "plan", None))
                stripe_cycle = (raw_meta.get("billing_cycle") if isinstance(raw_meta, dict) else getattr(raw_meta, "billing_cycle", None)) or "monthly"
                conn = get_db(); cur = conn.cursor()
                if stripe_plan and stripe_plan in _PLANS and stripe_plan != sub:
                    cfg = _PLANS[stripe_plan].get(stripe_cycle) or _PLANS[stripe_plan]["monthly"]
                    cur.execute("""UPDATE users SET stripe_subscription_id=%s, subscription_tier=%s,
                        billing_cycle=%s, packages_limit=%s, overage_rate=%s,
                        payment_status='ok', payment_failed_at=NULL WHERE id=%s""",
                        (real_sub_id, stripe_plan, stripe_cycle, cfg["packages"], cfg["overage_rate"], current_user["id"]))
                    sub = stripe_plan  # Reflect updated plan in this response
                    pkgs_limit = cfg["packages"]
                else:
                    cur.execute("UPDATE users SET stripe_subscription_id=%s WHERE id=%s", (real_sub_id, current_user["id"]))
                conn.commit(); cur.close(); conn.close()
                stored_sub_id = real_sub_id
        except Exception:
            pass  # Never break /me due to Stripe issues

    return {
        "id": current_user["id"], "email": current_user["email"],
        "full_name": current_user.get("full_name",""), "organization_name": current_user.get("organization_name",""),
        "subscription_tier": sub, "billing_cycle": current_user.get("billing_cycle","monthly") or "monthly",
        "downloads_remaining": 3 - used if sub == "free" else -1,
        "packages_used": pkgs_used, "packages_limit": pkgs_limit, "packages_soft_buffer": soft_buffer,
        "overage_packages_pending": int(current_user.get("overage_packages_pending",0) or 0),
        "email_verified": bool(int(current_user.get("email_verified",0) or 0)),
        "acord_license_confirmed": bool(int(current_user.get("acord_license_confirmed",0) or 0)),
        "acord_disclaimer_accepted": bool(int(current_user.get("acord_disclaimer_accepted",0) or 0)),
        "payment_status": current_user.get("payment_status","ok") or "ok",
        "payment_failed_at": current_user.get("payment_failed_at"),
        "overage_rate": int(current_user.get("overage_rate",0) or 0),
    }


# REPLACE WITH THIS
@router.post("/logout")
async def logout(authorization: str = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        conn  = get_db()
        cur   = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
        cur.close()
        conn.close()
    return {"success": True}
