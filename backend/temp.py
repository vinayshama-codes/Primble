"""
Acordly API v12.3
=================
✅ PostgreSQL (psycopg2) — ALL state persisted, including processing sessions
✅ OCR: EasyOCR (no system deps) | Google Vision | AWS Textract
✅ Backend single source of truth — field_state, on-demand PDF regen
✅ Processing sessions in PostgreSQL JSONB — survives restarts, scales horizontally
✅ Bulk form generation + ZIP download
✅ Stripe 3-tier billing: Essentials ($129/mo or $99/mo annual) | Professional ($449/mo or $399/mo annual) | Enterprise ($1,199/mo, contact sales)
✅ Overage: 5% soft buffer (free), then auto-billed via invoice item on next monthly invoice
✅ Payment failure lifecycle: webhook-driven state machine (day 1/7/10/21/60)
✅ Stripe billing portal: dynamic session creation for updating payment methods
✅ Email verification, Google OAuth, Forgot Password
✅ ACORD compliance: disclaimer at signup, license confirmation checkbox on download
✅ Cover page: AI narrative summary + truly hidden A2A JSON block, prepended to ZIP bundle
✅ Producer signature: draw/upload, stored as base64 PNG, injected into PDF signature fields on demand
✅ FIXED: Cron lifecycle day-7 duplicate emails, timezone parsing, double DB write, dev endpoint auth
"""

import os, json, io, logging, uuid, re, zipfile, secrets, random, textwrap
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import bcrypt
import psycopg2
import psycopg2.extras
import pdfplumber
import pikepdf
from PIL import Image
from groq import Groq
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, EmailStr
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import stripe

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# ── OCR provider setup ──────────────────────────────────────────
OCR_PROVIDER = os.getenv("OCR_PROVIDER", "easyocr").lower()

_easyocr_reader = None
def _get_easyocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("EasyOCR reader initialized")
        except Exception as ex:
            logger.error(f"EasyOCR init failed: {ex}")
    return _easyocr_reader

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "tmp");    os.makedirs(UPLOAD_DIR, exist_ok=True)
TEMPLATE_DIR  = os.path.join(BASE_DIR, "templates")
FORMS_DB_DIR  = os.path.join(BASE_DIR, "forms_database")
FORMS_INDEX   = os.path.join(FORMS_DB_DIR, "forms_index.json")

DATABASE_URL    = os.getenv("DATABASE_URL", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

STRIPE_CURRENCY = "usd"

PLANS = {
    "essentials": {
        "monthly":  {"amount": 12900,  "interval": "month", "packages": 100,  "overage_rate": 150},
        "annual":   {"amount": 118800, "interval": "year",  "packages": 1200, "overage_rate": 150},
    },
    "professional": {
        "monthly":  {"amount": 44900,  "interval": "month", "packages": 400,  "overage_rate": 125},
        "annual":   {"amount": 478800, "interval": "year",  "packages": 4800, "overage_rate": 125},
    },
    "enterprise": {
        "monthly":  {"amount": 119900, "interval": "month", "packages": 0,    "overage_rate": 0},
        "annual":   {"amount": 119900, "interval": "month", "packages": 0,    "overage_rate": 0},
    },
}

SOFT_BUFFER_PCT = 0.05
STRIPE_BILLING_PORTAL_URL = os.getenv("STRIPE_BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/")
STRIPE_YEARLY_AMOUNT = 30000
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

app = FastAPI(title="Acordly API", version="12.3.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════
#  PAYMENT LIFECYCLE CRON (runs daily at 09:00 UTC)
# ══════════════════════════════════════════════════════════════════
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()


def _safe_parse_dt(raw) -> Optional[datetime]:
    """
    Parse a datetime from DB (str or datetime obj). Handles:
      - Python datetime objects (naive or aware)
      - ISO strings with +00:00 or Z suffix  ← FIX: Z was crashing fromisoformat()
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, str):
        # FIX: Python < 3.11 fromisoformat() does not accept 'Z' — replace it
        normalized = raw.replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            logger.error(f"_safe_parse_dt: cannot parse '{raw}'")
            return None
    return None


async def run_daily_payment_lifecycle():
    
    try:
        now = datetime.now(timezone.utc)
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT id, email, full_name, payment_failed_at, payment_status "
            "FROM users WHERE payment_failed_at IS NOT NULL"
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()

        for row in rows:
            try:
                failed_at = _safe_parse_dt(row['payment_failed_at'])
                if failed_at is None:
                    logger.warning(f"Lifecycle cron: unparseable payment_failed_at for user={row['id']}")
                    continue

                days_since     = (now - failed_at).days
                current_status = row.get('payment_status', 'failed') or 'failed'
                new_status     = current_status
                email_day      = None

                if days_since >= 60 and current_status != 'archived':
                    new_status = 'archived'
                    email_day  = 60         
                    logger.info(f"Day 60: archiving user={row['id']} — sending archive notification")
                elif days_since >= 21 and current_status not in ('suspended', 'archived'):
                    new_status = 'suspended'
                    email_day  = 21
                elif days_since >= 10 and current_status not in ('soft_locked', 'suspended', 'archived'):
                    new_status = 'soft_locked'
                    email_day  = 10
                elif days_since == 7 and current_status == 'failed':
                    
                    email_day  = 7
               

                if new_status != current_status:
                    conn2 = get_db(); cur2 = conn2.cursor()
                    try:
                        cur2.execute(
                            "UPDATE users SET payment_status=%s WHERE id=%s",
                            (new_status, row['id'])
                        )
                        conn2.commit()
                        logger.info(
                            f"Lifecycle cron: user={row['id']} "
                            f"{current_status} → {new_status} (day {days_since})"
                        )
                    finally:
                        cur2.close(); conn2.close()

                if email_day:
                    _send_payment_failed_email(
                        row['email'], row.get('full_name', ''), day=email_day
                    )

            except Exception as ex:
                logger.error(f"Lifecycle cron error user={row['id']}: {ex}")

    except Exception as ex:
        logger.error(f"Lifecycle cron failed: {ex}")


@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(run_daily_payment_lifecycle, "cron", hour=9, minute=0)
    scheduler.start()
    logger.info("✅ Daily payment lifecycle scheduler started")


@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()


# ══════════════════════════════════════════════════════════════════
#  POSTGRESQL DATABASE
# ══════════════════════════════════════════════════════════════════
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                            TEXT PRIMARY KEY,
            email                         TEXT UNIQUE NOT NULL,
            password_hash                 TEXT,
            full_name                     TEXT,
            organization_name             TEXT,
            auth_provider                 TEXT DEFAULT 'email',
            google_id                     TEXT UNIQUE,
            email_verified                INTEGER DEFAULT 0,
            verification_code             TEXT,
            verification_expires          TEXT,
            subscription_tier             TEXT DEFAULT 'free',
            stripe_customer_id            TEXT,
            stripe_subscription_id        TEXT,
            downloads_used                INTEGER DEFAULT 0,
            packages_used                 INTEGER DEFAULT 0,
            packages_limit                INTEGER DEFAULT 0,
            billing_cycle                 TEXT DEFAULT 'monthly',
            billing_period_start          TEXT,
            overage_rate                  INTEGER DEFAULT 0,
            payment_status                TEXT DEFAULT 'ok',
            payment_failed_at             TEXT,
            acord_disclaimer_accepted     INTEGER DEFAULT 0,
            acord_disclaimer_accepted_at  TEXT,
            acord_license_confirmed       INTEGER DEFAULT 0,
            acord_license_confirmed_at    TEXT,
            created_at                    TEXT,
            last_login                    TEXT
        )
    """)

    for col, definition in [
        ("organization_name",            "TEXT"),
        ("acord_disclaimer_accepted",    "INTEGER DEFAULT 0"),
        ("acord_disclaimer_accepted_at", "TEXT"),
        ("acord_license_confirmed",      "INTEGER DEFAULT 0"),
        ("acord_license_confirmed_at",   "TEXT"),
        ("packages_used",                "INTEGER DEFAULT 0"),
        ("packages_limit",               "INTEGER DEFAULT 0"),
        ("billing_cycle",                "TEXT DEFAULT 'monthly'"),
        ("billing_period_start",         "TEXT"),
        ("overage_rate",                 "INTEGER DEFAULT 0"),
        ("payment_status",               "TEXT DEFAULT 'ok'"),
        ("payment_failed_at",            "TEXT"),
        ("signature_data",               "TEXT"),
        ("stripe_customer_id",           "TEXT"),
        ("overage_packages_pending",     "INTEGER DEFAULT 0"),
        # Track how many overage packages have already been invoiced to Stripe
        # Used by /api/stripe/reconcile-overage to avoid double-billing
        ("overage_packages_invoiced",    "INTEGER DEFAULT 0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            conn.commit()
            logger.info(f"Migration: added column users.{col}")
        except Exception:
            conn.rollback()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            token      TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processing_sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            data       JSONB NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS session_pdf_bytes (
            session_id TEXT NOT NULL,
            form_id    TEXT NOT NULL,
            pdf_bytes  BYTEA NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, form_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_signups (
            id                            TEXT PRIMARY KEY,
            email                         TEXT UNIQUE NOT NULL,
            password_hash                 TEXT NOT NULL,
            full_name                     TEXT,
            organization_name             TEXT,
            verification_code             TEXT,
            verification_expires          TEXT,
            acord_disclaimer_accepted     INTEGER DEFAULT 0,
            acord_disclaimer_accepted_at  TEXT,
            created_at                    TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS acord_audit_log (
            id                      TEXT PRIMARY KEY,
            user_id                 TEXT NOT NULL,
            user_email              TEXT NOT NULL,
            organization_name       TEXT,
            action                  TEXT NOT NULL,
            form_id                 TEXT,
            form_name               TEXT,
            session_id              TEXT,
            ip_address              TEXT,
            acord_license_confirmed INTEGER DEFAULT 0,
            timestamp               TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applied_overage_sessions (
            stripe_session_id TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL,
            qty               INTEGER NOT NULL,
            applied_at        TEXT NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ PostgreSQL database initialized")


try:
    init_db()
except Exception as e:
    logger.error(f"DB init error: {e}")


# ══════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════════
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    organization_name: str
    acord_disclaimer_accepted: bool = False

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str

class GoogleAuthRequest(BaseModel):
    credential: str

class FormSelectionRequest(BaseModel):
    session_id: str
    selected_form_id: str

class BulkFormSelectionRequest(BaseModel):
    session_id: str
    form_ids: List[str]

class PDFUpdateRequest(BaseModel):
    session_id: str
    field_updates: Dict[str, str]

class CheckoutRequest(BaseModel):
    plan: str = "essentials"
    billing_cycle: str = "monthly"


# ══════════════════════════════════════════════════════════════════
#  EMAIL VERIFICATION
# ══════════════════════════════════════════════════════════════════
def generate_verification_code() -> str:
    return str(random.randint(100000, 999999))

def send_verification_email(email: str, code: str) -> bool:
    provider = os.getenv("EMAIL_PROVIDER", "").lower()
    from_addr = os.getenv("EMAIL_FROM", "noreply@acordly.ai")

    subject  = "Your Acordly Verification Code"
    body_txt = f"Your Acordly verification code is: {code}\n\nThis code expires in 10 minutes.\n\nIf you did not create an account, please ignore this email."
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
      <h2 style="color:#1e293b;margin-bottom:8px;">Verify your Acordly account</h2>
      <p style="color:#475569;margin-bottom:24px;">Enter the code below to complete your sign-up.</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin-bottom:24px;">
        <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
      </div>
      <p style="color:#64748b;font-size:13px;">This code expires in <strong>10 minutes</strong>.</p>
      <p style="color:#64748b;font-size:13px;">If you did not create an account, you can safely ignore this email.</p>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
      <p style="color:#94a3b8;font-size:11px;">Acordly &mdash; AI-powered ACORD form automation</p>
    </div>
    """

    if provider == "resend":
        try:
            import urllib.request, urllib.error
            api_key = os.getenv("RESEND_API_KEY", "")
            if not api_key:
                logger.error("RESEND_API_KEY not set"); return False
            payload = json.dumps({"from": from_addr, "to": [email], "subject": subject, "html": body_html, "text": body_txt}).encode()
            req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                logger.info(f"Resend: verification email sent to {email} (id={result.get('id')})")
                return True
        except Exception as ex:
            logger.error(f"Resend email failed for {email}: {ex}"); return False

    elif provider == "sendgrid":
        try:
            import urllib.request
            api_key = os.getenv("SENDGRID_API_KEY", "")
            if not api_key:
                logger.error("SENDGRID_API_KEY not set"); return False
            payload = json.dumps({"personalizations": [{"to": [{"email": email}]}], "from": {"email": from_addr},
                "subject": subject, "content": [{"type": "text/plain", "value": body_txt}, {"type": "text/html", "value": body_html}]}).encode()
            req = urllib.request.Request("https://api.sendgrid.com/v3/mail/send", data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"SendGrid: verification email sent to {email} (status={resp.status})"); return True
        except Exception as ex:
            logger.error(f"SendGrid email failed for {email}: {ex}"); return False

    elif provider == "smtp":
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            host = os.getenv("SMTP_HOST", "smtp.gmail.com"); port = int(os.getenv("SMTP_PORT", "587"))
            user = os.getenv("SMTP_USER", ""); pw = os.getenv("SMTP_PASS", "")
            if not user or not pw:
                logger.error("SMTP_USER or SMTP_PASS not set"); return False
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject; msg["From"] = from_addr; msg["To"] = email
            msg.attach(MIMEText(body_txt, "plain")); msg.attach(MIMEText(body_html, "html"))
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo(); server.starttls(); server.login(user, pw)
                server.sendmail(from_addr, [email], msg.as_string())
            logger.info(f"SMTP: verification email sent to {email}"); return True
        except Exception as ex:
            logger.error(f"SMTP email failed for {email}: {ex}"); return False

    else:
        logger.warning(f"EMAIL_PROVIDER not set — verification code for {email}: {code}")
        return True


# ══════════════════════════════════════════════════════════════════
#  AUTH UTILITIES
# ══════════════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com","icloud.com",
    "live.com","aol.com","msn.com","ymail.com","mail.com",
    "protonmail.com","proton.me","tutanota.com","zoho.com",
}

def validate_work_email(email: str) -> Tuple[bool, str]:
    domain = email.lower().split("@")[-1] if "@" in email else ""
    if domain in PERSONAL_EMAIL_DOMAINS:
        return False, f"Please use a work email address. Personal email domains ({domain}) are not accepted."
    return True, ""

def validate_password(password: str) -> Tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    return True, ""

def create_session_token(user_id: str) -> str:
    conn   = get_db(); cur = conn.cursor()
    token  = secrets.token_urlsafe(32)
    exp    = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    cur.execute(
        "INSERT INTO sessions (id, user_id, token, expires_at, created_at) VALUES (%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), user_id, token, exp, datetime.now(timezone.utc).isoformat())
    )
    conn.commit(); cur.close(); conn.close()
    return token

def _user_row(cur, user_id: str) -> Optional[dict]:
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.replace("Bearer ", "")
    conn  = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE token = %s", (token,))
    session = cur.fetchone()
    if not session:
        cur.close(); conn.close(); raise HTTPException(401, "Invalid token")
    session = dict(session)
    if datetime.fromisoformat(session['expires_at']) < datetime.now(timezone.utc):
        cur.close(); conn.close(); raise HTTPException(401, "Session expired")
    user = _user_row(cur, session['user_id'])
    cur.close(); conn.close()
    if not user:
        raise HTTPException(401, "User not found")
    provider  = user.get('auth_provider', 'email') or 'email'
    verified  = int(user.get('email_verified', 0) or 0)
    if provider == 'email' and not verified:
        raise HTTPException(403, "Email not verified.")
    return user


# ══════════════════════════════════════════════════════════════════
#  PROCESSING SESSIONS — PostgreSQL JSONB
# ══════════════════════════════════════════════════════════════════

def _session_to_db(data: dict) -> dict:
    clean = {}
    generated = data.get("generated_forms", {})
    clean_gen  = {}
    for fid, form_data in generated.items():
        fd_copy = {k: v for k, v in form_data.items() if k != "pdf_bytes"}
        clean_gen[fid] = fd_copy
    clean = {k: v for k, v in data.items() if k != "generated_forms"}
    clean["generated_forms"] = clean_gen
    return clean


def _session_from_db(data: dict, sid: str) -> dict:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT form_id, pdf_bytes FROM session_pdf_bytes WHERE session_id = %s", (sid,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    pb_map = {r["form_id"]: bytes(r["pdf_bytes"]) for r in rows}
    generated = data.get("generated_forms", {})
    for fid, form_data in generated.items():
        if fid in pb_map:
            form_data["pdf_bytes"] = pb_map[fid]
    return data


def new_processing_session(data: dict) -> str:
    sid  = str(uuid.uuid4())
    now  = datetime.now(timezone.utc).isoformat()
    _save_pdf_bytes(sid, data.get("generated_forms", {}))
    clean = _session_to_db(data)
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO processing_sessions (id, user_id, data, created_at, updated_at) VALUES (%s,%s,%s,%s,%s)",
        (sid, data.get("user_id",""), json.dumps(clean), now, now)
    )
    conn.commit(); cur.close(); conn.close()
    logger.info(f"Processing session created: {sid}")
    return sid


def get_processing_session(sid: str) -> dict:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT data FROM processing_sessions WHERE id = %s", (sid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(404, f"Processing session {sid} not found")
    data = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
    return _session_from_db(data, sid)


def upd_processing_session(sid: str, updates: dict):
    current = get_processing_session(sid)
    if "generated_forms" in updates:
        existing_gen = current.get("generated_forms", {})
        for fid, form_data in updates["generated_forms"].items():
            if fid not in existing_gen:
                existing_gen[fid] = form_data
            else:
                existing_gen[fid].update(form_data)
        current["generated_forms"] = existing_gen
        _save_pdf_bytes(sid, current["generated_forms"])
    for k, v in updates.items():
        if k != "generated_forms":
            current[k] = v
    clean = _session_to_db(current)
    now   = datetime.now(timezone.utc).isoformat()
    conn  = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE processing_sessions SET data = %s, updated_at = %s WHERE id = %s",
        (json.dumps(clean), now, sid)
    )
    conn.commit(); cur.close(); conn.close()


def _save_pdf_bytes(sid: str, generated: dict):
    if not generated:
        return
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db(); cur = conn.cursor()
    for fid, form_data in generated.items():
        pb = form_data.get("pdf_bytes")
        if pb is not None:
            cur.execute("""
                INSERT INTO session_pdf_bytes (session_id, form_id, pdf_bytes, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, form_id)
                DO UPDATE SET pdf_bytes = EXCLUDED.pdf_bytes, updated_at = EXCLUDED.updated_at
            """, (sid, fid, psycopg2.Binary(pb), now))
    conn.commit(); cur.close(); conn.close()


# ══════════════════════════════════════════════════════════════════
#  OVERAGE BILLING HELPERS
# ══════════════════════════════════════════════════════════════════

def _get_or_create_stripe_customer(user: dict) -> Optional[str]:
    customer_id = user.get('stripe_customer_id')
    if customer_id:
        return customer_id
    if not stripe.api_key:
        return None
    try:
        customers = stripe.Customer.list(email=user['email'], limit=1)
        if customers.data:
            customer_id = customers.data[0].id
        else:
            cust = stripe.Customer.create(
                email=user['email'],
                name=user.get('full_name', ''),
                metadata={'user_id': user['id'], 'org': user.get('organization_name', '')},
            )
            customer_id = cust.id
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s",
                    (customer_id, user['id']))
        conn.commit(); cur.close(); conn.close()
        return customer_id
    except Exception as ex:
        logger.error(f"_get_or_create_stripe_customer failed for user={user['id']}: {ex}")
        return None


def _create_overage_invoice_item(user: dict, overage_rate_cents: int) -> bool:
    """
    Queue one overage package as a Stripe invoice item on the next subscription invoice.
    """
    if not stripe.api_key:
        logger.warning(f"Stripe not configured — overage not billed for user={user['id']}")
        return False

    customer_id = _get_or_create_stripe_customer(user)
    if not customer_id:
        logger.warning(f"Cannot create overage invoice item: no Stripe customer for user={user['id']}")
        return False

    sub = user.get('subscription_tier', '')
    tier_label = 'Essentials' if sub == 'essentials' else 'Professional'

    try:
        stripe.InvoiceItem.create(
            customer=customer_id,
            amount=overage_rate_cents,
            currency='usd',
            description=f"Acordly {tier_label} — 1 overage ACORD package (@ ${overage_rate_cents/100:.2f})",
            metadata={
                'user_id':    user['id'],
                'user_email': user.get('email', ''),
                'plan':       sub,
                'type':       'overage_package',
            },
        )
        logger.info(
            f"✅ Overage invoice item queued: user={user['id']} "
            f"plan={sub} amount={overage_rate_cents}¢"
        )
        return True
    except Exception as ex:
        logger.error(f"Failed to create overage invoice item for user={user['id']}: {ex}")
        return False


def _evaluate_package_limit(fresh: dict) -> dict:
    sub        = fresh.get('subscription_tier', 'free') or 'free'
    pkgs_used  = int(fresh.get('packages_used', 0) or 0)
    pkgs_limit = int(fresh.get('packages_limit', 0) or 0)
    overage_rate_cents = int(fresh.get('overage_rate') or (150 if sub == 'essentials' else 125))

    if pkgs_limit == 0:
        pkgs_limit = 100 if sub == 'essentials' else 400
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE users SET packages_limit = %s WHERE id = %s", (pkgs_limit, fresh['id']))
        conn.commit(); cur.close(); conn.close()
        logger.info(f"Backfilled packages_limit={pkgs_limit} for user={fresh['id']} tier={sub}")

    soft_buffer = int(pkgs_limit * SOFT_BUFFER_PCT)
    hard_limit  = pkgs_limit + soft_buffer

    if pkgs_used < pkgs_limit:
        return {
            "status": "normal", "allow": True, "message": "",
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }
    elif pkgs_used < hard_limit:
        remaining_buffer = hard_limit - pkgs_used - 1
        return {
            "status": "soft_buffer", "allow": True,
            "message": (
                f"You have used all {pkgs_limit} included packages this month. "
                f"You have {remaining_buffer} complimentary buffer package(s) remaining — "
                f"no charge for these. After that, overages are billed at "
                f"${overage_rate_cents/100:.2f}/package on your next invoice."
            ),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }
    else:
        return {
            "status": "overage", "allow": True,
            "message": (
                f"You are over your {pkgs_limit}-package limit (including the 5% complimentary buffer). "
                f"This package will be billed at ${overage_rate_cents/100:.2f} on your next monthly invoice."
            ),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }


# ══════════════════════════════════════════════════════════════════
#  AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════
@app.post("/api/auth/signup")
async def signup(req: SignupRequest):
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

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, email_verified FROM users WHERE email = %s", (req.email,))
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
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
              password_hash            = EXCLUDED.password_hash,
              full_name                = EXCLUDED.full_name,
              organization_name        = EXCLUDED.organization_name,
              verification_code        = EXCLUDED.verification_code,
              verification_expires     = EXCLUDED.verification_expires,
              acord_disclaimer_accepted_at = EXCLUDED.acord_disclaimer_accepted_at
        """, (pending_id, req.email, hash_password(req.password),
              req.full_name, req.organization_name.strip(), code, expires, now, now))
        conn.commit()
    except Exception as ex:
        cur.close(); conn.close()
        raise HTTPException(500, f"Database error: {ex}")
    finally:
        cur.close(); conn.close()

    send_verification_email(req.email, code)
    return JSONResponse({
        "success": True, "message": f"Verification code sent to {req.email}.",
        "email": req.email, "requires_verification": True,
    }, status_code=202)


@app.post("/api/auth/verify-email")
async def verify_email(req: VerifyEmailRequest):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    existing = cur.fetchone()
    if existing and int(dict(existing).get('email_verified', 0) or 0):
        cur.close(); conn.close()
        raise HTTPException(400, "Email already verified. Please sign in.")

    cur.execute("SELECT * FROM pending_signups WHERE email = %s", (req.email,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(404, "No pending signup found. Please sign up again.")
    pending = dict(row)

    if pending.get('verification_code') != req.code:
        cur.close(); conn.close()
        raise HTTPException(400, "Invalid verification code.")

    exp = pending.get('verification_expires', '')
    if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
        cur.close(); conn.close()
        raise HTTPException(400, "Code has expired. Please request a new one.")

    now     = datetime.now(timezone.utc).isoformat()
    user_id = pending['id']
    try:
        cur.execute("""
            INSERT INTO users
              (id, email, password_hash, full_name, organization_name,
               auth_provider, email_verified,
               acord_disclaimer_accepted, acord_disclaimer_accepted_at,
               subscription_tier, downloads_used, created_at, last_login)
            VALUES (%s,%s,%s,%s,%s,'email',1,%s,%s,'free',0,%s,%s)
        """, (user_id, pending['email'], pending['password_hash'],
              pending.get('full_name', ''), pending.get('organization_name', ''),
              int(pending.get('acord_disclaimer_accepted', 0) or 0),
              pending.get('acord_disclaimer_accepted_at', now),
              pending.get('created_at', now), now))
        cur.execute("DELETE FROM pending_signups WHERE email = %s", (req.email,))
        conn.commit()
    except Exception as ex:
        conn.rollback(); cur.close(); conn.close()
        raise HTTPException(500, f"Account creation failed: {ex}")
    finally:
        cur.close(); conn.close()

    token = create_session_token(user_id)
    return {
        "success": True, "token": token,
        "user": {
            "id": user_id, "email": pending['email'],
            "full_name": pending.get('full_name', ''),
            "organization_name": pending.get('organization_name', ''),
            "subscription_tier": 'free', "downloads_remaining": 3,
            "acord_license_confirmed": False,
        }
    }


@app.post("/api/auth/resend-verification")
async def resend_verification(request: Request):
    body  = await request.json()
    email = body.get("email")
    if not email:
        raise HTTPException(400, "Email required")
    conn  = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM pending_signups WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT email_verified FROM users WHERE email = %s", (email,))
        u = cur.fetchone()
        cur.close(); conn.close()
        if u and int(dict(u).get('email_verified', 0) or 0):
            raise HTTPException(400, "Email already verified. Please sign in.")
        raise HTTPException(404, "No pending signup found. Please sign up again.")
    code    = generate_verification_code()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    cur.execute("UPDATE pending_signups SET verification_code=%s, verification_expires=%s WHERE email=%s",
                (code, expires, email))
    conn.commit(); cur.close(); conn.close()
    send_verification_email(email, code)
    return {"success": True, "message": "Code resent"}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (req.email,))
    row = cur.fetchone()
    if not row or not dict(row).get('password_hash'):
        cur.close(); conn.close(); raise HTTPException(401, "Invalid credentials")
    user = dict(row)
    if not verify_password(req.password, user['password_hash']):
        cur.close(); conn.close(); raise HTTPException(401, "Invalid credentials")
    if not int(user.get('email_verified', 0) or 0):
        cur.close(); conn.close()
        return JSONResponse({"success": False, "requires_verification": True, "email": req.email,
                             "message": "Please verify your email first."}, status_code=403)
    cur.execute("UPDATE users SET last_login=%s WHERE id=%s",
                (datetime.now(timezone.utc).isoformat(), user['id']))
    conn.commit(); cur.close(); conn.close()
    token = create_session_token(user['id'])
    sub   = user.get('subscription_tier', 'free') or 'free'
    used  = int(user.get('downloads_used', 0) or 0)
    return {"success": True, "token": token,
            "user": {"id": user['id'], "email": user['email'], "full_name": user.get('full_name', ''),
                     "subscription_tier": sub, "downloads_remaining": 3 - used if sub == 'free' else -1}}


@app.post("/api/auth/forgot-password")
async def forgot_password(request: Request):
    body  = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email required")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if row:
        user = dict(row)
        code    = generate_verification_code()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("UPDATE users SET verification_code=%s, verification_expires=%s WHERE email=%s",
                     (code, expires, email))
        conn2.commit(); cur2.close(); conn2.close()
        provider = user.get('auth_provider', 'email') or 'email'
        is_google_only = provider == 'google' and not user.get('password_hash')
        if is_google_only:
            subject  = "Set a password for your Acordly account"
            body_txt = f"Use this code to set a password for your Acordly account: {code}\n\nThis code expires in 15 minutes."
            body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
              <h2 style="color:#1e293b;">Set your Acordly password</h2>
              <p style="color:#475569;">You signed up with Google. Use this code to set a password.</p>
              <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin:24px 0;">
                <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
              </div>
              <p style="color:#64748b;font-size:13px;">Expires in <strong>15 minutes</strong>.</p>
            </div>"""
        else:
            subject  = "Reset your Acordly password"
            body_txt = f"Your Acordly password reset code is: {code}\n\nThis code expires in 15 minutes."
            body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
              <h2 style="color:#1e293b;">Reset your Acordly password</h2>
              <div style="background:#f1f5f9;border-radius:8px;padding:24px;text-align:center;margin:24px 0;">
                <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#0f172a;">{code}</span>
              </div>
              <p style="color:#64748b;font-size:13px;">Expires in <strong>15 minutes</strong>.</p>
            </div>"""
        return _send_generic_email(email, subject, body_txt, body_html)
    return {"success": True, "message": "If that email is registered, a reset code has been sent."}


def _send_generic_email(to_email: str, subject: str, body_txt: str, body_html: str) -> bool:
    provider  = os.getenv("EMAIL_PROVIDER", "").lower()
    from_addr = os.getenv("EMAIL_FROM", "noreply@acordly.ai")
    if provider == "resend":
        try:
            import urllib.request
            api_key = os.getenv("RESEND_API_KEY", "")
            if not api_key: return False
            payload = json.dumps({"from": from_addr, "to": [to_email], "subject": subject, "html": body_html, "text": body_txt}).encode()
            req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10): return True
        except Exception as ex:
            logger.error(f"Resend generic email failed: {ex}"); return False
    elif provider == "sendgrid":
        try:
            import urllib.request
            api_key = os.getenv("SENDGRID_API_KEY", "")
            if not api_key: return False
            payload = json.dumps({"personalizations":[{"to":[{"email":to_email}]}], "from":{"email":from_addr},
                "subject":subject, "content":[{"type":"text/plain","value":body_txt},{"type":"text/html","value":body_html}]}).encode()
            req = urllib.request.Request("https://api.sendgrid.com/v3/mail/send", data=payload,
                headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10): return True
        except Exception as ex:
            logger.error(f"SendGrid generic email failed: {ex}"); return False
    elif provider == "smtp":
        def _do_smtp():
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            host = os.getenv("SMTP_HOST","smtp.gmail.com")
            port = int(os.getenv("SMTP_PORT","587"))
            user = os.getenv("SMTP_USER","")
            pw   = os.getenv("SMTP_PASS","")
            if not user or not pw:
                raise ValueError("SMTP_USER or SMTP_PASS not set in .env")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = from_addr
            msg["To"]      = to_email
            msg.attach(MIMEText(body_txt, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo(); server.starttls(); server.ehlo()
                server.login(user, pw)
                server.sendmail(from_addr, [to_email], msg.as_string())
            return True
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_smtp)
                result = future.result(timeout=45)
            logger.info(f"SMTP: email sent to {to_email} — '{subject[:50]}'")
            return True
        except Exception as ex:
            logger.error(f"SMTP failed to {to_email}: {ex}"); return False
    else:
        logger.warning(f"EMAIL not configured — email for {to_email} not sent")
        return True


@app.post("/api/auth/reset-password")
async def reset_password(request: Request):
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
        cur.close(); conn.close(); raise HTTPException(404, "Account not found")
    user = dict(row)
    stored_code    = user.get("verification_code", "")
    stored_expires = user.get("verification_expires", "")
    if not stored_code or stored_code != code:
        cur.close(); conn.close(); raise HTTPException(400, "Invalid reset code")
    try:
        if datetime.fromisoformat(stored_expires) < datetime.now(timezone.utc):
            cur.close(); conn.close(); raise HTTPException(400, "Reset code has expired — please request a new one")
    except Exception:
        cur.close(); conn.close(); raise HTTPException(400, "Reset code invalid")
    new_hash = hash_password(new_pass)
    cur.execute("UPDATE users SET password_hash=%s, verification_code=NULL, verification_expires=NULL, email_verified=1 WHERE email=%s",
                (new_hash, email))
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "message": "Password updated successfully. You can now sign in."}


@app.post("/api/auth/google")
async def google_auth(req: GoogleAuthRequest):
    try:
        cid = GOOGLE_CLIENT_ID.lstrip("G") if GOOGLE_CLIENT_ID.startswith("G") and not GOOGLE_CLIENT_ID.startswith("Go") else GOOGLE_CLIENT_ID
        idinfo = id_token.verify_oauth2_token(req.credential, google_requests.Request(), cid, clock_skew_in_seconds=10)
        if idinfo.get('iss') not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Invalid issuer')
        if idinfo.get('aud') != cid:
            raise ValueError('Invalid audience')
        google_id = idinfo['sub']; email = idinfo.get('email'); name = idinfo.get('name', email)
        if not email:
            raise ValueError('No email in token')
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                uid = dict(row)['id']
                cur.execute("UPDATE users SET google_id=%s, auth_provider='google', email_verified=1 WHERE id=%s", (google_id, uid))
                conn.commit()
                cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
            else:
                uid = str(uuid.uuid4()); now = datetime.now(timezone.utc).isoformat()
                cur.execute("""INSERT INTO users (id, email, google_id, full_name, auth_provider, email_verified, created_at, last_login)
                    VALUES (%s,%s,%s,%s,'google',1,%s,%s)""", (uid, email, google_id, name, now, now))
                conn.commit()
                cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
                row = cur.fetchone()
        user = dict(row)
        cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (datetime.now(timezone.utc).isoformat(), user['id']))
        conn.commit(); cur.close(); conn.close()
        token = create_session_token(user['id'])
        sub   = user.get('subscription_tier', 'free') or 'free'
        used  = int(user.get('downloads_used', 0) or 0)
        org_name   = user.get('organization_name') or ''
        disclaimer = int(user.get('acord_disclaimer_accepted', 0) or 0)
        profile_incomplete = not org_name.strip() or not disclaimer
        return {"success": True, "token": token, "profile_incomplete": profile_incomplete,
                "user": {"id": user['id'], "email": user['email'], "full_name": user.get('full_name', ''),
                         "organization_name": org_name, "subscription_tier": sub,
                         "downloads_remaining": 3 - used if sub == 'free' else -1,
                         "acord_license_confirmed": bool(int(user.get('acord_license_confirmed', 0) or 0)),
                         "acord_disclaimer_accepted": bool(disclaimer)}}
    except ValueError as e:
        raise HTTPException(401, f"Invalid Google token: {e}")
    except Exception as e:
        raise HTTPException(401, f"Google auth failed: {e}")


class CompleteProfileRequest(BaseModel):
    organization_name: str
    acord_disclaimer_accepted: bool = False


@app.post("/api/auth/complete-profile")
async def complete_profile(req: CompleteProfileRequest, current_user: dict = Depends(get_current_user)):
    if not req.acord_disclaimer_accepted:
        raise HTTPException(400, "You must accept the ACORD disclaimer to continue.")
    if not req.organization_name or not req.organization_name.strip():
        raise HTTPException(400, "Organization or agency name is required.")
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""UPDATE users SET organization_name=%s, acord_disclaimer_accepted=1, acord_disclaimer_accepted_at=%s WHERE id=%s""",
                (req.organization_name.strip(), now, current_user['id']))
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "message": "Profile updated."}


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    sub  = current_user.get('subscription_tier', 'free') or 'free'
    used = int(current_user.get('downloads_used', 0) or 0)
    pkgs_used  = int(current_user.get('packages_used', 0) or 0)
    pkgs_limit = int(current_user.get('packages_limit', 0) or 0)
    overage_pending = int(current_user.get('overage_packages_pending', 0) or 0)
    soft_buffer = int(pkgs_limit * SOFT_BUFFER_PCT) if pkgs_limit > 0 else 0

    return {
        "id": current_user['id'], "email": current_user['email'],
        "full_name": current_user.get('full_name', ''),
        "organization_name": current_user.get('organization_name', ''),
        "subscription_tier": sub,
        "billing_cycle": current_user.get('billing_cycle', 'monthly') or 'monthly',
        "downloads_remaining": 3 - used if sub == 'free' else -1,
        "packages_used": pkgs_used,
        "packages_limit": pkgs_limit,
        "packages_soft_buffer": soft_buffer,
        "overage_packages_pending": overage_pending,
        "email_verified": bool(int(current_user.get('email_verified', 0) or 0)),
        "acord_license_confirmed": bool(int(current_user.get('acord_license_confirmed', 0) or 0)),
        "acord_disclaimer_accepted": bool(int(current_user.get('acord_disclaimer_accepted', 0) or 0)),
        "payment_status": current_user.get('payment_status', 'ok') or 'ok',
        "payment_failed_at": current_user.get('payment_failed_at'),
        "overage_rate": int(current_user.get('overage_rate', 0) or 0),
    }


@app.post("/api/auth/logout")
async def logout(authorization: str = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        conn  = get_db(); cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit(); cur.close(); conn.close()
    return {"success": True}


# ══════════════════════════════════════════════════════════════════
#  ACORD COMPLIANCE ENDPOINTS
# ══════════════════════════════════════════════════════════════════

def write_audit_log(user: dict, action: str, form_id: str = None,
                    form_name: str = None, session_id: str = None, ip_address: str = None):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""INSERT INTO acord_audit_log
              (id, user_id, user_email, organization_name, action, form_id, form_name, session_id, ip_address, acord_license_confirmed, timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (str(uuid.uuid4()), user.get('id'), user.get('email'), user.get('organization_name', ''),
             action, form_id, form_name, session_id, ip_address,
             int(user.get('acord_license_confirmed', 0) or 0), datetime.now(timezone.utc).isoformat()))
        conn.commit(); cur.close(); conn.close()
    except Exception as ex:
        logger.error(f"audit_log write failed: {ex}")


@app.post("/api/acord/confirm-license")
async def confirm_acord_license(request: Request, current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET acord_license_confirmed=1, acord_license_confirmed_at=%s WHERE id=%s",
                (now, current_user['id']))
    conn.commit(); cur.close(); conn.close()
    write_audit_log(user={**current_user, 'acord_license_confirmed': 1}, action='license_confirmed',
                    ip_address=request.client.host if request.client else None)
    return {"success": True, "acord_license_confirmed": True}


@app.get("/api/acord/audit-log")
async def get_audit_log(current_user: dict = Depends(get_current_user), limit: int = 100, offset: int = 0):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM acord_audit_log WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                (current_user['id'], limit, offset))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return {"success": True, "entries": rows, "count": len(rows)}


# ══════════════════════════════════════════════════════════════════
#  STRIPE BILLING
# ══════════════════════════════════════════════════════════════════
@app.post("/api/stripe/create-checkout")
async def create_checkout(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    plan  = req.plan.lower()
    cycle = req.billing_cycle.lower()

    if plan == "enterprise":
        raise HTTPException(400, "Enterprise plan requires contacting sales. Email sales@acordly.ai")
    if plan not in PLANS:
        raise HTTPException(400, f"Unknown plan '{plan}'. Choose: essentials, professional")
    if cycle not in ("monthly", "annual"):
        raise HTTPException(400, "billing_cycle must be 'monthly' or 'annual'")

    plan_cfg   = PLANS[plan][cycle]
    plan_label = f"Acordly {plan.title()} — {'Annual' if cycle == 'annual' else 'Monthly'}"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price_data": {"currency": STRIPE_CURRENCY,
                "product_data": {"name": plan_label},
                "unit_amount": plan_cfg["amount"],
                "recurring": {"interval": plan_cfg["interval"]}}, "quantity": 1}],
            mode="subscription",
            success_url=f"{FRONTEND_URL}?upgraded=true",
            cancel_url=f"{FRONTEND_URL}?upgraded=false",
            client_reference_id=current_user['id'],
            customer_email=current_user['email'],
            metadata={"plan": plan, "billing_cycle": cycle},
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(500, f"Stripe error: {e}")


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            logger.warning("STRIPE_WEBHOOK_SECRET not set — skipping signature verification")
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Webhook signature verification failed: {e}")
        raise HTTPException(400, "Invalid webhook signature")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        raise HTTPException(400, f"Webhook error: {e}")

    logger.info(f"Stripe webhook received: {event['type']}")

    def _resolve_user(obj):
        user_id = obj.get('client_reference_id')
        email   = obj.get('customer_email') or obj.get('customer_details', {}).get('email')
        conn = get_db(); cur = conn.cursor()
        if user_id:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row: user_id = None
        if not user_id and email:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row: user_id = dict(row)['id']
        cur.close(); conn.close()
        return user_id

    if event['type'] == 'checkout.session.completed':
        obj      = event['data']['object']
        user_id  = _resolve_user(obj)
        metadata = obj.get('metadata', {})

        if metadata.get('type') == 'overage':
            qty = int(metadata.get('qty', 0))
            uid = metadata.get('user_id') or user_id
            sid = obj.get('id', '')
            if uid and qty > 0 and sid:
                conn = get_db(); cur = conn.cursor()
                cur.execute("SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = %s", (sid,))
                if cur.fetchone():
                    logger.info(f"Webhook overage skip (already applied): session={sid} user={uid}")
                    cur.close(); conn.close()
                    return {"received": True}
                now = datetime.now(timezone.utc).isoformat()
                cur.execute("UPDATE users SET packages_limit = packages_limit + %s WHERE id = %s", (qty, uid))
                cur.execute("INSERT INTO applied_overage_sessions (stripe_session_id, user_id, qty, applied_at) VALUES (%s,%s,%s,%s)",
                            (sid, str(uid), qty, now))
                conn.commit(); cur.close(); conn.close()
                logger.info(f"✅ Webhook overage credited: user={uid} +{qty} packages session={sid}")
            return {"received": True}

        sub_id = obj.get('subscription')
        plan   = metadata.get('plan', 'essentials')
        cycle  = metadata.get('billing_cycle', 'monthly')

        if user_id and plan in PLANS and cycle in PLANS[plan]:
            cfg = PLANS[plan][cycle]
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            stripe_customer = obj.get('customer')
            if stripe_customer:
                cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s",
                            (stripe_customer, user_id))
            cur.execute("""UPDATE users SET subscription_tier=%s, stripe_subscription_id=%s,
                packages_limit=%s, packages_used=0, billing_cycle=%s, billing_period_start=%s,
                overage_rate=%s, payment_status='ok', payment_failed_at=NULL,
                overage_packages_pending=0, overage_packages_invoiced=0 WHERE id=%s""",
                (plan, sub_id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id))
            conn.commit(); cur.close(); conn.close()
            logger.info(f"✅ Subscription activated: user={user_id} plan={plan} cycle={cycle}")

    elif event['type'] in ('invoice.paid', 'invoice.payment_succeeded'):
        obj    = event['data']['object']
        sub_id = obj.get('subscription')
        if not sub_id:
            parent = obj.get('parent') or {}
            sub_id = (parent.get('subscription_details') or {}).get('subscription')
        logger.info(f"🔍 invoice paid: sub_id={sub_id}")
        if sub_id:
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            cur.execute("""UPDATE users SET packages_used=0, billing_period_start=%s,
                payment_status='ok', payment_failed_at=NULL,
                overage_packages_pending=0, overage_packages_invoiced=0
                WHERE stripe_subscription_id=%s""", (now, sub_id))
            conn.commit()
            cur.execute("SELECT id, email FROM users WHERE stripe_subscription_id = %s", (sub_id,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row:
                logger.info(f"✅ Invoice paid: reset packages_used + overage tracking for user={dict(row)['id']}")

    elif event['type'] == 'invoice.payment_failed':
        obj    = event['data']['object']
        sub_id = obj.get('subscription')
        if not sub_id:
            parent = obj.get('parent') or {}
            sub_id = (parent.get('subscription_details') or {}).get('subscription')
        logger.info(f"🔍 payment_failed fired: sub_id={sub_id}")
        if sub_id:
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            cur.execute("""UPDATE users SET payment_status='failed',
                payment_failed_at=COALESCE(payment_failed_at, %s)
                WHERE stripe_subscription_id=%s""", (now, sub_id))
            conn.commit()
            cur.execute("SELECT email, full_name FROM users WHERE stripe_subscription_id = %s", (sub_id,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row:
                row = dict(row)
                # Day-1 email sent HERE by webhook — cron does NOT resend it
                _send_payment_failed_email(row['email'], row.get('full_name',''), day=1)

    elif event['type'] == 'customer.subscription.updated':
        obj = event['data']['object']
        sub_id = obj.get('id')
        status = obj.get('status')
        if sub_id and status in ('active', 'trialing'):
            conn = get_db(); cur = conn.cursor()
            cur.execute("""
                UPDATE users SET payment_status='ok', payment_failed_at=NULL
                WHERE stripe_subscription_id=%s
                AND payment_status NOT IN ('failed', 'soft_locked', 'suspended', 'archived')
            """, (sub_id,))
            conn.commit(); cur.close(); conn.close()

    elif event['type'] == 'customer.subscription.deleted':
        sub_id = event['data']['object'].get('id')
        if sub_id:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""UPDATE users SET subscription_tier='free', packages_limit=0, packages_used=0,
                payment_status='ok', payment_failed_at=NULL,
                overage_packages_pending=0, overage_packages_invoiced=0
                WHERE stripe_subscription_id=%s""", (sub_id,))
            conn.commit(); cur.close(); conn.close()

    return {"received": True}


def _send_payment_failed_email(email: str, name: str, day: int):
    billing_portal = STRIPE_BILLING_PORTAL_URL

    if day == 1:
        subject  = "Action required: Payment failed for your Acordly subscription"
        body_txt = (f"Hi {name or 'there'},\n\nWe were unable to process your Acordly subscription payment. "
                    f"Please update your payment method to avoid any interruption to your service.\n\n"
                    f"Update your billing here: {billing_portal}\n\nThe Acordly Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#1e293b;">Payment failed</h2>
          <p>Hi {name or 'there'},</p>
          <p>We were unable to process your Acordly subscription payment.</p>
          <p>Please update your payment method to avoid interruption.</p>
          <p><a href="{billing_portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
          <p style="color:#94a3b8;font-size:11px;">Acordly — AI-powered ACORD form automation</p>
        </div>"""
    elif day == 7:
        subject  = "Important: Your Acordly payment is still overdue"
        body_txt = (f"Hi {name or 'there'},\n\nYour Acordly subscription payment is still outstanding. "
                    f"Please update your payment method immediately to avoid account restrictions.\n\n"
                    f"Update your billing here: {billing_portal}\n\nThe Acordly Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">Payment still overdue</h2>
          <p>Hi {name or 'there'},</p>
          <p style="color:#dc2626;font-weight:bold;">Your account will be restricted if payment is not received soon.</p>
          <p><a href="{billing_portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
          <p style="color:#94a3b8;font-size:11px;">Acordly — AI-powered ACORD form automation</p>
        </div>"""
    elif day == 10:
        subject  = "Account Disabled: Update Billing"
        body_txt = (f"Hi {name or 'there'},\n\nYour Acordly account has been disabled due to non-payment. "
                    f"Please update your billing to restore access: {billing_portal}\n\nThe Acordly Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#b45309;">Account Disabled &mdash; Update Billing</h2>
          <p>Hi {name or 'there'},</p>
          <p>Your Acordly account has been disabled because your payment is now 10 days overdue.</p>
          <p><a href="{billing_portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
          <p style="color:#94a3b8;font-size:11px;">Acordly &mdash; AI-powered ACORD form automation</p>
        </div>"""
    elif day == 21:
        subject  = "Account suspended: Acordly access restricted due to non-payment"
        body_txt = (f"Hi {name or 'there'},\n\nYour Acordly account has been suspended due to non-payment. "
                    f"Please update your billing to restore access: {billing_portal}\n\nThe Acordly Team")
        body_html = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
          <h2 style="color:#dc2626;">🚫 Account suspended</h2>
          <p>Hi {name or 'there'},</p>
          <p>Your Acordly account has been <strong>suspended</strong> due to 21 days of non-payment.</p>
          <p><a href="{billing_portal}" style="background:#e6007a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;">Update Billing</a></p>
          <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
          <p style="color:#94a3b8;font-size:11px;">Acordly — AI-powered ACORD form automation</p>
        </div>"""
    else:
        return False

    # NOTE: Day-60 template removed — archive is silent (no customer email at 60 days)
    return _send_generic_email(email, subject, body_txt, body_html)


@app.post("/api/billing/payment-lifecycle")
async def run_payment_lifecycle():
    """
    Manual trigger for the same logic as the daily cron.
    Useful for testing or backfilling missed runs.

    FIX: Same fixes as cron — day == 7 (not >= 7), no day-1 branch,
         and robust timezone parsing via _safe_parse_dt().
    """
    now  = datetime.now(timezone.utc)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, email, full_name, payment_failed_at, payment_status FROM users WHERE payment_failed_at IS NOT NULL")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    processed = 0
    for row in rows:
        try:
            failed_at = _safe_parse_dt(row['payment_failed_at'])
            if failed_at is None:
                logger.warning(f"Lifecycle: unparseable payment_failed_at for user={row['id']}")
                continue

            days_since     = (now - failed_at).days
            current_status = row.get('payment_status', 'failed') or 'failed'
            new_status     = current_status
            email_day      = None

            if days_since >= 60 and current_status != 'archived':
                new_status = 'archived'; email_day = None
                logger.info(f"Day 60: silently archiving user={row['id']}")
            elif days_since >= 21 and current_status not in ('suspended', 'archived'):
                new_status = 'suspended'; email_day = 21
            elif days_since >= 10 and current_status not in ('soft_locked', 'suspended', 'archived'):
                new_status = 'soft_locked'; email_day = 10
            elif days_since == 7 and current_status == 'failed':
                # FIX: was >= 7 — sent day-7 email on Day 7, 8, 9
                email_day = 7
            # NOTE: Day-1 omitted — handled by invoice.payment_failed webhook

            if new_status != current_status:
                conn2 = get_db(); cur2 = conn2.cursor()
                cur2.execute("UPDATE users SET payment_status=%s WHERE id=%s", (new_status, row['id']))
                conn2.commit(); cur2.close(); conn2.close()
                logger.info(f"Payment lifecycle: user={row['id']} → {new_status} (day {days_since})")

            if email_day:
                sent = _send_payment_failed_email(row['email'], row.get('full_name', ''), day=email_day)
                logger.info(f"Payment lifecycle email day={email_day} to {row['email']}: {'sent ✅' if sent else 'FAILED ❌'}")
            processed += 1
        except Exception as ex:
            logger.error(f"Payment lifecycle error for user={row['id']}: {ex}")

    return {"processed": processed, "checked_at": now.isoformat()}


# ── Dev / Admin endpoints ─────────────────────────────────────────

@app.post("/api/dev/test-email")
async def test_email(
    request: Request,
    current_user: dict = Depends(get_current_user)   # FIX: was unauthenticated
):
    """Send a test payment-failure email. Requires auth to prevent spam abuse."""
    body = await request.json()
    to   = body.get("email", "")
    day  = int(body.get("day", 1))
    if not to:
        raise HTTPException(400, "email required")
    sent = _send_payment_failed_email(to, "Test User", day=day)
    logger.info(f"Test email day={day} to {to}: {'sent ✅' if sent else 'FAILED ❌'} (triggered by {current_user['email']})")
    return {"sent": sent, "to": to, "day": day}


@app.post("/api/dev/simulate-payment-failure")
async def simulate_payment_failure(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Dev helper — sets payment_failed_at in the past to test lifecycle logic.

    FIX: Previously wrote to DB twice (set 'failed', then set final_status).
         Now consolidates into a single write.
    """
    body     = await request.json()
    days_ago = int(body.get("days_ago", 0))
    fake_dt  = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    # Determine final status in one pass
    if days_ago >= 21:
        final_status = 'suspended'
    elif days_ago >= 10:
        final_status = 'soft_locked'
    else:
        final_status = 'failed'

    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "UPDATE users SET payment_status=%s, payment_failed_at=%s WHERE id=%s",
        (final_status, fake_dt, current_user['id'])
    )
    conn.commit(); cur.close(); conn.close()
    logger.info(f"DEV: simulated payment failure {days_ago} days ago → {final_status} for user={current_user['id']}")

    email_day = 21 if days_ago >= 21 else 10 if days_ago >= 10 else 7 if days_ago >= 7 else 1
    sent = _send_payment_failed_email(current_user['email'], current_user.get('full_name',''), day=email_day)
    logger.info(f"DEV simulate: sent day={email_day} email to {current_user['email']}: {'✅' if sent else '❌'}")

    return {
        "success": True, "payment_failed_at": fake_dt, "days_ago": days_ago,
        "status_set": final_status, "email_sent": sent, "email_day": email_day,
    }


@app.post("/api/stripe/verify-upgrade")
async def verify_upgrade(current_user: dict = Depends(get_current_user)):
    user_email = current_user.get('email')
    user_id    = current_user.get('id')
    if current_user.get('subscription_tier') not in ('free', None):
        return {"subscription_tier": current_user['subscription_tier'], "upgraded": False, "reason": "already_subscribed"}
    try:
        customers = stripe.Customer.list(email=user_email, limit=5)
        if not customers.data:
            return {"subscription_tier": "free", "upgraded": False, "reason": "no_stripe_customer"}
        for customer in customers.data:
            subs = stripe.Subscription.list(customer=customer.id, status="active", limit=5)
            if subs.data:
                sub      = subs.data[0]
                sub_id   = sub.id
                metadata = sub.get('metadata', {})
                plan     = metadata.get('plan', 'essentials')
                cycle    = metadata.get('billing_cycle', 'monthly')
                cfg      = PLANS.get(plan, {}).get(cycle, PLANS['essentials']['monthly'])
                now      = datetime.now(timezone.utc).isoformat()
                conn = get_db(); cur = conn.cursor()
                cur.execute("""UPDATE users SET subscription_tier=%s, stripe_subscription_id=%s,
                    stripe_customer_id=%s, packages_limit=%s, billing_cycle=%s,
                    billing_period_start=%s, overage_rate=%s,
                    payment_status='ok', payment_failed_at=NULL WHERE id=%s""",
                    (plan, sub_id, customer.id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id))
                conn.commit(); cur.close(); conn.close()
                return {"subscription_tier": plan, "upgraded": True, "reason": "stripe_verified"}
        return {"subscription_tier": "free", "upgraded": False, "reason": "no_active_subscription"}
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key not configured")
    except Exception as e:
        logger.error(f"verify-upgrade error: {e}")
        raise HTTPException(500, f"Stripe verification failed: {e}")


class OverageCheckoutRequest(BaseModel):
    quantity: int

@app.post("/api/stripe/create-overage-checkout")
async def create_overage_checkout(req: OverageCheckoutRequest, current_user: dict = Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    tier               = current_user.get('subscription_tier', 'free')
    overage_rate_cents = int(current_user.get('overage_rate') or (150 if tier == 'essentials' else 125))
    overage_rate_dollars = overage_rate_cents / 100
    qty                = max(1, min(req.quantity, 10000))
    tier_label         = 'Essentials' if tier == 'essentials' else 'Professional'
    description        = f"Acordly {tier_label} — {qty} additional ACORD packages @ ${overage_rate_dollars:.2f}/pkg"
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"], mode="payment",
            client_reference_id=str(current_user['id']),
            line_items=[{"price_data": {"currency": "usd", "unit_amount": overage_rate_cents,
                "product_data": {"name": f"Acordly Extra Packages ({tier_label})", "description": description}},
                "quantity": qty}],
            metadata={"type": "overage", "user_id": str(current_user['id']), "qty": str(qty)},
            success_url=f"{FRONTEND_URL}/?overage_paid=true&qty={qty}&user_id={current_user['id']}&stripe_session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"Overage checkout error: {e}"); raise HTTPException(500, str(e))


class ApplyOverageRequest(BaseModel):
    stripe_session_id: str
    qty: int

@app.post("/api/stripe/apply-overage")
async def apply_overage(req: ApplyOverageRequest, current_user: dict = Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    try:
        cs = stripe.checkout.Session.retrieve(req.stripe_session_id)
    except Exception as e:
        raise HTTPException(400, f"Could not verify payment: {e}")
    if cs.get('payment_status') != 'paid':
        raise HTTPException(400, f"Payment not completed (status={cs.get('payment_status')})")
    session_user_id = cs.get('client_reference_id') or cs.get('metadata', {}).get('user_id')
    if str(session_user_id) != str(current_user['id']):
        raise HTTPException(403, "Session does not belong to this user")
    if cs.get('metadata', {}).get('type') != 'overage':
        raise HTTPException(400, "Not an overage session")
    qty = int(cs.get('metadata', {}).get('qty', 0))
    if qty <= 0:
        raise HTTPException(400, "Invalid quantity in session metadata")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = %s", (current_user['id'],))
    if not cur.fetchone():
        cur.close(); conn.close(); raise HTTPException(404, "User not found")
    cur.execute("SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = %s", (req.stripe_session_id,))
    if cur.fetchone():
        cur.close(); conn.close()
        conn2 = get_db(); cur2 = conn2.cursor()
        cur2.execute("SELECT packages_limit FROM users WHERE id = %s", (current_user['id'],))
        row = dict(cur2.fetchone()); cur2.close(); conn2.close()
        return {"credited": False, "already_applied": True, "packages_limit": row['packages_limit']}
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("UPDATE users SET packages_limit = packages_limit + %s WHERE id = %s", (qty, current_user['id']))
    cur.execute("INSERT INTO applied_overage_sessions (stripe_session_id, user_id, qty, applied_at) VALUES (%s,%s,%s,%s)",
                (req.stripe_session_id, str(current_user['id']), qty, now))
    conn.commit()
    cur.execute("SELECT packages_limit FROM users WHERE id = %s", (current_user['id'],))
    updated = dict(cur.fetchone()); cur.close(); conn.close()
    return {"credited": True, "qty": qty, "packages_limit": updated['packages_limit']}


@app.post("/api/stripe/reconcile-overage")
async def reconcile_overage(current_user: dict = Depends(get_current_user)):
    """
    FIX Issue 7: When packages_used is manually updated in the DB (e.g. via Supabase),
    no Stripe invoice item gets created automatically. This endpoint reconciles the gap.

    It calculates how many overage packages have NOT yet been invoiced to Stripe
    (packages_used - packages_limit - soft_buffer - overage_packages_invoiced)
    and creates invoice items for the difference.

    Call this after any manual DB adjustment to packages_used.
    """
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (current_user['id'],))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row:
        raise HTTPException(404, "User not found")

    user = dict(row)
    sub  = user.get('subscription_tier', 'free') or 'free'
    if sub not in ('essentials', 'professional'):
        raise HTTPException(400, "Reconciliation only applies to paid plans")

    pkgs_used     = int(user.get('packages_used', 0) or 0)
    pkgs_limit    = int(user.get('packages_limit', 0) or 0)
    already_invoiced = int(user.get('overage_packages_invoiced', 0) or 0)
    overage_rate_cents = int(user.get('overage_rate') or (150 if sub == 'essentials' else 125))
    soft_buffer   = int(pkgs_limit * SOFT_BUFFER_PCT)

    # Total overages that should be billed (past soft buffer)
    billable_overages = max(0, pkgs_used - pkgs_limit - soft_buffer)
    uninvoiced        = max(0, billable_overages - already_invoiced)

    if uninvoiced == 0:
        return {"success": True, "message": "No uninvoiced overages found.", "uninvoiced": 0}

    queued = 0
    failed = 0
    for _ in range(uninvoiced):
        ok = _create_overage_invoice_item(user, overage_rate_cents)
        if ok:
            queued += 1
        else:
            failed += 1

    if queued > 0:
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "UPDATE users SET overage_packages_invoiced = overage_packages_invoiced + %s WHERE id = %s",
            (queued, current_user['id'])
        )
        conn.commit(); cur.close(); conn.close()

    logger.info(
        f"✅ Reconcile overage: user={current_user['id']} "
        f"uninvoiced={uninvoiced} queued={queued} failed={failed}"
    )
    return {
        "success": True,
        "packages_used": pkgs_used,
        "packages_limit": pkgs_limit,
        "soft_buffer": soft_buffer,
        "billable_overages": billable_overages,
        "already_invoiced": already_invoiced,
        "newly_queued": queued,
        "failed": failed,
        "message": f"Queued {queued} overage invoice item(s) to Stripe." if queued else "All overages already invoiced.",
    }


@app.post("/api/stripe/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):

    # ── No Stripe customer → send to checkout ──
    if not user.get('stripe_customer_id'):
        try:
            plan          = user.get('subscription_tier', 'essentials')
            billing_cycle = user.get('billing_cycle', 'monthly') or 'monthly'
            if plan not in PLANS or plan == 'free':
                plan = 'essentials'
            if billing_cycle not in ('monthly', 'annual'):
                billing_cycle = 'monthly'

            plan_data = PLANS[plan][billing_cycle]

            customer = stripe.Customer.create(
                email=user['email'],
                name=user.get('full_name', ''),
                metadata={'user_id': user['id']}
            )

            conn = get_db(); cur = conn.cursor()
            cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s",
                (customer.id, user['id']))
            conn.commit(); cur.close(); conn.close()

            checkout = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                mode='subscription',
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': f"Acordly {plan.title()} — {billing_cycle.title()}"},
                        'unit_amount': plan_data['amount'],
                        'recurring': {'interval': plan_data['interval']},
                    },
                    'quantity': 1,
                }],
                success_url=f"{FRONTEND_URL}?billing_updated=true",
                cancel_url=FRONTEND_URL,
                metadata={'user_id': user['id'], 'plan': plan, 'billing_cycle': billing_cycle}
            )
            return {"url": checkout.url}

        except Exception as ex:
            logger.error(f"Portal checkout fallback failed: {ex}")
            raise HTTPException(500, "Could not open billing. Please contact support.")

    # ── Existing Stripe customer → open billing portal ──
    try:
        session = stripe.checkout.Session.create(
            customer=user['stripe_customer_id'],
            payment_method_types=['card'],
            mode='setup',
            success_url=f"{FRONTEND_URL}?billing_updated=true",
            cancel_url=FRONTEND_URL,
        )
        return {"url": session.url}
        logger.info(f"FRONTEND_URL = {FRONTEND_URL}")
    except Exception as ex:
        logger.error(f"Portal session failed: {ex}")
        raise HTTPException(500, "Could not open billing portal.")
    

    
# ══════════════════════════════════════════════════════════════════
#  FORM LOADING HELPERS
# ══════════════════════════════════════════════════════════════════
def load_index() -> dict:
    if not os.path.exists(FORMS_INDEX): return {"forms": []}
    with open(FORMS_INDEX) as f: return json.load(f)

def load_form_detail(form_id: str) -> Optional[dict]:
    p = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
    if not os.path.exists(p): return None
    with open(p) as f: return json.load(f)

def load_all_forms() -> List[dict]:
    idx = load_index()
    return [d for ref in idx.get("forms", []) if (d := load_form_detail(ref["form_id"])) is not None]

def filter_available_forms(forms: List[dict]) -> List[dict]:
    return [f for f in forms if os.path.exists(os.path.join(TEMPLATE_DIR, f.get("template_file", "")))]


# ══════════════════════════════════════════════════════════════════
#  ZIP EXTRACTION
# ══════════════════════════════════════════════════════════════════
SUPPORTED_IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

def extract_zip(zip_path: str) -> List[str]:
    extracted = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            ext = os.path.splitext(name.lower())[1]
            if ext in {'.pdf'} | SUPPORTED_IMG:
                out = os.path.join(UPLOAD_DIR, os.path.basename(name))
                with open(out, 'wb') as fh: fh.write(zf.read(name))
                extracted.append(out)
    return extracted


# ══════════════════════════════════════════════════════════════════
#  OCR
# ══════════════════════════════════════════════════════════════════
def ocr_image_file(img_path: str) -> str:
    provider = OCR_PROVIDER
    if provider == "google": return _ocr_google_vision(img_path)
    elif provider == "aws":  return _ocr_aws_textract(img_path)
    else:                    return _ocr_easyocr(img_path)

def _ocr_easyocr(img_path: str) -> str:
    try:
        reader = _get_easyocr()
        if reader is None: return ""
        results = reader.readtext(img_path, detail=0, paragraph=True)
        return "\n".join(results).strip()
    except Exception as ex:
        logger.error(f"EasyOCR error on {img_path}: {ex}"); return ""

def _ocr_google_vision(img_path: str) -> str:
    try:
        from google.cloud import vision as gvision
        c = gvision.ImageAnnotatorClient()
        with open(img_path, 'rb') as f: content = f.read()
        image    = gvision.Image(content=content)
        response = c.document_text_detection(image=image)
        return response.full_text_annotation.text.strip()
    except Exception as ex:
        logger.error(f"Google Vision error: {ex}"); return ""

def _ocr_aws_textract(img_path: str) -> str:
    try:
        import boto3
        c = boto3.client('textract', region_name=os.getenv('AWS_REGION', 'us-east-1'))
        with open(img_path, 'rb') as f: content = f.read()
        response = c.detect_document_text(Document={'Bytes': content})
        return "\n".join(b['Text'] for b in response['Blocks'] if b['BlockType'] == 'LINE').strip()
    except Exception as ex:
        logger.error(f"AWS Textract error: {ex}"); return ""

def extract_images_from_pdf(pdf_path: str) -> List[str]:
    out_paths = []
    try:
        pdf = pikepdf.open(pdf_path)
        for page_num, page in enumerate(pdf.pages):
            resources = page.get("/Resources", None)
            if resources is None: continue
            xobjects = resources.get("/XObject", None)
            if xobjects is None: continue
            for name, obj in xobjects.items():
                try:
                    if obj.get("/Subtype", "") == "/Image":
                        img_data = bytes(obj.read_raw_bytes())
                        ext = ".jpg" if "/DCTDecode" in str(obj.get("/Filter", "")) else ".png"
                        fname = os.path.join(UPLOAD_DIR, f"embed_{uuid.uuid4().hex[:8]}{ext}")
                        with open(fname, 'wb') as fh: fh.write(img_data)
                        out_paths.append(fname)
                except Exception: pass
        pdf.close()
    except Exception as ex:
        logger.warning(f"Image extraction from PDF failed: {ex}")
    return out_paths

def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n"
    except Exception as ex:
        logger.error(f"pdfplumber error: {ex}")
    if len(text.strip()) < 100:
        for ip in extract_images_from_pdf(pdf_path):
            text += ocr_image_file(ip) + "\n"
    return text.strip()

def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path.lower())[1]
    if ext == '.pdf': return extract_text_from_pdf(file_path)
    elif ext in SUPPORTED_IMG: return ocr_image_file(file_path)
    return ""


# ══════════════════════════════════════════════════════════════════
#  DOCUMENT TYPE IDENTIFICATION
# ══════════════════════════════════════════════════════════════════
DOC_TYPE_KEYWORDS = {
    "dec_page":    ["declarations", "dec page", "policy declarations", "named insured",
                    "policy period", "coverage summary", "insuring agreement", "policy number"],
    "certificate": ["certificate of liability", "certificate of insurance", "acord 25",
                    "certificate holder", "evidence of insurance", "this is to certify"],
    "loss_run":    ["loss run", "loss history", "incurred", "reserve", "paid losses", "claimant", "date of loss"],
    "schedule":    ["schedule of", "vehicle schedule", "equipment schedule", "location schedule", "driver schedule"],
    "quote":       ["quote", "proposal", "indication", "estimated premium", "quoted premium"],
    "application": ["application", "acord 125", "acord 126", "acord 130", "prior application"],
    "endorsement": ["endorsement", "additional insured", "waiver of subrogation", "mortgagee"],
}

def identify_doc_type(text: str) -> str:
    tl     = text.lower()
    scores = {dt: sum(1 for kw in kws if kw in tl) for dt, kws in DOC_TYPE_KEYWORDS.items()}
    best   = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"

def select_primary_truth(docs: List[dict]) -> dict:
    priority = ["dec_page", "application", "quote", "schedule", "endorsement", "certificate", "loss_run", "unknown"]
    by_type  = {}
    for d in docs: by_type.setdefault(d["doc_type"], d)
    for p in priority:
        if p in by_type: return by_type[p]
    return docs[0]


# ══════════════════════════════════════════════════════════════════
#  VALIDATORS
# ══════════════════════════════════════════════════════════════════
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","VI","GU","MP","AS",
}

def validate_address(addr: str) -> Tuple[bool, str]:
    if not addr: return True, ""
    parts       = addr.upper().split()
    state_found = any(p.strip(",.") in US_STATES for p in parts)
    zip_found   = bool(re.search(r'\b\d{5}(-\d{4})?\b', addr))
    if not state_found: return False, f"Address missing valid US state: '{addr}'"
    if not zip_found:   return False, f"Address missing ZIP code: '{addr}'"
    return True, ""

def validate_phone(phone: str) -> Tuple[bool, str]:
    if not phone: return True, ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) not in (10, 11): return False, f"Phone '{phone}' should be 10 digits"
    return True, ""

def validate_email_format(email: str) -> Tuple[bool, str]:
    if not email: return True, ""
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email.strip()):
        return False, f"Email '{email}' is invalid"
    return True, ""

def run_field_validations(facts: dict) -> Tuple[List[str], List[str]]:
    hard, soft = [], []
    for fn, fv in [("mailing_address", validate_address), ("contact_phone", validate_phone), ("contact_email", validate_email_format)]:
        ok, msg = fv(facts.get(fn, ""))
        if not ok: soft.append(msg)
    eff, exp = facts.get("effective_date", ""), facts.get("expiration_date", "")
    if eff and exp:
        fmts = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"]
        def parse(d):
            for fmt in fmts:
                try: return datetime.strptime(d.strip(), fmt)
                except ValueError: pass
            return None
        d_e, d_x = parse(eff), parse(exp)
        if d_e and d_x and d_e >= d_x:
            hard.append("Effective date is on or after expiration date")
    return hard, soft


# ══════════════════════════════════════════════════════════════════
#  FACTS EXTRACTION
# ══════════════════════════════════════════════════════════════════
def extract_facts(text: str) -> dict:
    if len(text) < 30: return {"facts": {}, "flags": {}}
    prompt = (
        'You are a carrier-grade insurance document analyzer. Extract every available data point.\n\n'
        'Return ONLY a valid JSON object with exactly these two top-level keys:\n\n'
        '"facts": {\n'
        '  "producer_name": string or null, "applicant_name": string or null,\n'
        '  "dba_name": string or null, "mailing_address": string or null,\n'
        '  "physical_address": string or null, "contact_name": string or null,\n'
        '  "contact_phone": string or null, "contact_email": string or null,\n'
        '  "fein": string or null, "entity_type": string or null,\n'
        '  "effective_date": string or null, "expiration_date": string or null,\n'
        '  "policy_number": string or null, "lines_of_business": [],\n'
        '  "total_revenue": string or null, "total_payroll": string or null,\n'
        '  "num_employees": string or null, "locations": [],\n'
        '  "operations_description": string or null, "prior_carrier": string or null,\n'
        '  "naics_code": string or null, "sic_code": string or null,\n'
        '  "years_in_business": string or null,\n'
        '  "gl_limits": string or null, "gl_aggregate": string or null,\n'
        '  "gl_each_occurrence": string or null, "gl_class_codes": [],\n'
        '  "gl_deductible": string or null, "gl_form_type": string or null,\n'
        '  "retro_date": string or null, "additional_insured": string or null,\n'
        '  "property_building_value": string or null, "property_bpp_value": string or null,\n'
        '  "construction_type": string or null, "occupancy_type": string or null,\n'
        '  "year_built": string or null, "roof_year": string or null,\n'
        '  "sprinkler_system": string or null, "fire_protection_class": string or null,\n'
        '  "valuation_method": string or null, "coinsurance_percentage": string or null,\n'
        '  "business_income_limit": string or null, "period_of_restoration": string or null,\n'
        '  "property_deductible_aop": string or null, "property_deductible_wind": string or null,\n'
        '  "property_deductible_earthquake": string or null, "property_deductible_flood": string or null,\n'
        '  "mortgagee_name": string or null, "auto_liability_limit": string or null,\n'
        '  "auto_liability_structure": string or null, "auto_deductible_comp": string or null,\n'
        '  "auto_deductible_collision": string or null, "auto_vin_schedule": [], "auto_garaging_addresses": [],\n'
        '  "wc_payroll": string or null, "wc_payroll_by_state": {}, "wc_class_codes": [],\n'
        '  "wc_xmod": string or null, "wc_officer_exclusions": string or null,\n'
        '  "umbrella_limit": string or null, "umbrella_sir": string or null,\n'
        '  "umbrella_attachment_point": string or null, "percent_subcontracted": string or null,\n'
        '  "contractor_type": string or null, "num_claims": string or null,\n'
        '  "loss_history_years": string or null, "certificate_holder": string or null\n'
        '},\n\n'
        '"flags": {\n'
        '  "is_commercial_policy": boolean, "has_general_liability": boolean,\n'
        '  "has_property_coverage": boolean, "has_auto_coverage": boolean,\n'
        '  "has_workers_comp": boolean, "has_umbrella": boolean,\n'
        '  "has_multiple_locations": boolean, "has_loss_history": boolean,\n'
        '  "is_contractor": boolean, "has_certificate_request": boolean,\n'
        '  "is_certificate_doc": boolean, "gl_is_claims_made": boolean,\n'
        '  "auto_has_physical_damage": boolean, "auto_split_limits": boolean,\n'
        '  "wc_multi_state": boolean, "wc_has_monopolistic_state": boolean,\n'
        '  "property_has_bi_coverage": boolean, "property_has_peril_deductibles": boolean\n'
        '}\n\n'
        'Return ONLY the JSON object, no markdown, no extra text.\n\n'
        f'Text:\n"""\n{text[:7000]}\n"""'
    )
    try:
        r   = client.chat.completions.create(model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}], temperature=0)
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"): raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1: raw = raw[s:e+1]
        return json.loads(raw)
    except Exception as ex:
        logger.error(f"Facts extraction error: {ex}"); return {"facts": {}, "flags": {}}

def merge_facts(docs: List[dict], primary: dict) -> Tuple[dict, dict]:
    mf, mg = {}, {}
    for d in docs:
        if d["filename"] != primary["filename"]:
            mf.update({k: v for k, v in d["facts"].items() if v})
            mg.update({k: v for k, v in d["flags"].items() if v})
    mf.update({k: v for k, v in primary["facts"].items() if v})
    mg.update({k: v for k, v in primary["flags"].items() if v})
    return mf, mg


# ══════════════════════════════════════════════════════════════════
#  TIER 1 / 2
# ══════════════════════════════════════════════════════════════════
TIER1_FIELDS  = {
    "producer_name": "Producer / Agency name", "applicant_name": "Applicant legal name",
    "mailing_address": "Applicant mailing address", "effective_date": "Proposed effective date",
    "lines_of_business": "Lines of business requested",
}
TIER1_CONTACT = ("contact_name", "contact_phone", "contact_email")

def check_tier1(facts: dict, flags: dict) -> Tuple[bool, List[str]]:
    if flags.get("is_certificate_doc") or flags.get("has_certificate_request"): return True, []
    missing = []
    for field, label in TIER1_FIELDS.items():
        val = facts.get(field)
        if not val or (isinstance(val, list) and not val): missing.append(label)
    if not any(facts.get(f) for f in TIER1_CONTACT): missing.append("Contact information")
    return len(missing) == 0, missing

TIER2_FIELDS = {
    "fein": "FEIN / Tax ID", "entity_type": "Business entity type",
    "operations_description": "Operations description", "total_revenue": "Annual revenue",
    "prior_carrier": "Prior carrier name", "num_employees": "Number of employees",
}

def check_tier2(facts: dict) -> Tuple[int, List[str]]:
    missing = [label for field, label in TIER2_FIELDS.items() if not facts.get(field)]
    score   = 100 - (len(missing) * (100 // max(len(TIER2_FIELDS), 1)))
    return score, missing


# ══════════════════════════════════════════════════════════════════
#  STOPS
# ══════════════════════════════════════════════════════════════════
def evaluate_stops(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    hard, soft = run_field_validations(facts)
    if flags.get("gl_is_claims_made"):
        if not facts.get("retro_date"):
            soft.append("GL policy is claims-made — retro date is required for carrier submission")
    if flags.get("has_general_liability") and not facts.get("total_revenue") and not facts.get("total_payroll"):
        soft.append("GL coverage detected but no revenue or payroll found — required for exposure rating")
    if flags.get("has_property_coverage"):
        min_cope = {"locations": bool(facts.get("locations")), "occupancy_type": bool(facts.get("occupancy_type")),
                    "construction_type": bool(facts.get("construction_type")),
                    "building_or_bpp_value": bool(facts.get("property_building_value") or facts.get("property_bpp_value"))}
        missing_min = [k.replace("_", " ") for k, v in min_cope.items() if not v]
        if missing_min:
            hard.append("Property Minimum Viable COPE incomplete — missing: " + ", ".join(missing_min))
        else:
            carrier_cope = {k: bool(facts.get(k)) for k in
                ["year_built","roof_year","sprinkler_system","fire_protection_class","valuation_method","coinsurance_percentage"]}
            missing_c = [k.replace("_", " ") for k, v in carrier_cope.items() if not v]
            if missing_c:
                soft.append("Carrier-Grade COPE incomplete — SQS capped at 85. Missing: " + ", ".join(missing_c))
        if flags.get("property_has_bi_coverage"):
            if facts.get("business_income_limit") and not facts.get("period_of_restoration"):
                soft.append("Business Income limit present but Period of Restoration is missing")
            elif not facts.get("business_income_limit"):
                soft.append("Business Income coverage detected — BI limit and Period of Restoration should be provided")
        if flags.get("property_has_peril_deductibles"):
            missing_perils = [p for p, k in [("wind/hail","property_deductible_wind"),("earthquake","property_deductible_earthquake"),("flood","property_deductible_flood")] if not facts.get(k)]
            if missing_perils:
                soft.append("Peril-specific deductibles referenced — please define amounts for: " + ", ".join(missing_perils))
        if not facts.get("valuation_method"):
            soft.append("Property valuation method not specified — select RCV or ACV")
    if flags.get("has_workers_comp"):
        if not facts.get("wc_payroll") and not facts.get("total_payroll"):
            soft.append("Workers Comp detected but payroll is missing — required for WC rating")
        if flags.get("wc_has_monopolistic_state"):
            soft.append("Monopolistic WC state detected (ND/OH/WA/WY) — WC must be handled through the state fund")
        if flags.get("wc_multi_state") and not facts.get("wc_payroll_by_state"):
            soft.append("Multi-state WC exposure detected — payroll breakdown by state and class code is required")
    if flags.get("has_umbrella"):
        if not facts.get("gl_limits") and not facts.get("auto_liability_limit"):
            hard.append("Umbrella detected but no underlying GL or Auto limits found")
    if flags.get("has_general_liability"):
        codes = facts.get("gl_class_codes", [])
        if isinstance(codes, list) and not codes:
            soft.append("GL coverage detected but no class codes found")
    return hard, soft


# ══════════════════════════════════════════════════════════════════
#  FORM MATCHING
# ══════════════════════════════════════════════════════════════════
def stage1_filter(flags: dict, all_forms: List[dict]) -> List[dict]:
    active = {k for k, v in flags.items() if v}
    candidates = []; seen = set()
    for form in all_forms:
        fid = form["form_id"]
        if fid in seen: continue
        include = False
        if form.get("always_include"): include = True
        elif set(form.get("matching_flags", [])) & active: include = True
        elif fid == "ACORD_126" and (flags.get("has_general_liability") or flags.get("is_contractor")): include = True
        elif fid == "ACORD_140" and flags.get("has_property_coverage"): include = True
        elif fid == "ACORD_25" and (flags.get("has_certificate_request") or flags.get("is_certificate_doc")): include = True
        if include: candidates.append(form); seen.add(fid)
    return candidates

def stage2_ai_match(facts: dict, flags: dict, candidates: List[dict]) -> List[dict]:
    slim = [{"form_id": f["form_id"], "form_name": f["form_name"], "description": f.get("description", ""),
             "matching_keywords": f.get("matching_keywords", [])} for f in candidates]
    prompt = (
        "You are a carrier-grade insurance submission expert.\n"
        "Rank these candidate ACORD forms by relevance. Only use forms from the list.\n\n"
        "Rules:\n- ACORD_125 always required first\n- ACORD_126 if GL present\n"
        "- ACORD_140 if property present\n- ACORD_25 only if certificate holder explicitly requested\n\n"
        f"Facts: {json.dumps(facts, indent=2)}\nFlags: {json.dumps(flags, indent=2)}\n"
        f"Candidates: {json.dumps(slim, indent=2)}\n\n"
        'Return ONLY a raw JSON array sorted by confidence descending.\n'
        '[{"form_id":"ACORD_XXX","form_name":"...","confidence":0.95,"reason":"one sentence"}]'
    )
    try:
        r   = client.chat.completions.create(model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}], temperature=0)
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"): raw = raw.replace("```json","").replace("```","").strip()
        s, e = raw.find("["), raw.rfind("]")
        recs = json.loads(raw[s:e+1]) if s != -1 and e != -1 else []
        if not isinstance(recs, list): recs = []
        valid_ids = {f["form_id"] for f in candidates}
        recs = [r for r in recs if r.get("form_id") in valid_ids]
        is_cert_only = flags.get("is_certificate_doc") and not flags.get("is_commercial_policy")
        if not is_cert_only and not any(r.get("form_id") == "ACORD_125" for r in recs):
            a125 = next((f for f in candidates if f["form_id"] == "ACORD_125"), None)
            if a125:
                recs.insert(0, {"form_id":"ACORD_125","form_name":a125["form_name"],
                                 "confidence":0.99,"reason":"Always required for commercial submissions"})
        recs.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return recs
    except Exception as ex:
        logger.error(f"Stage 2 error: {ex}")
        return [{"form_id":"ACORD_125","form_name":"ACORD 125 - Commercial Insurance Application","confidence":0.99,"reason":"Default"}]

def match_forms(facts: dict, flags: dict, all_forms: List[dict]) -> List[dict]:
    candidates = stage1_filter(flags, all_forms) or all_forms
    return stage2_ai_match(facts, flags, candidates)


# ══════════════════════════════════════════════════════════════════
#  CROSS-FORM VALIDATION
# ══════════════════════════════════════════════════════════════════
def cross_validate(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    issues = []
    def _num(s):
        try: return float(str(s).replace(",","").replace("$","").strip()) if s else None
        except: return None

    if not facts.get("applicant_name"):
        issues.append({"type":"hard_stop","message":"Named insured missing — required on all forms"})
    fein = facts.get("fein", "")
    if fein and len(str(fein).replace("-","").replace(" ","")) not in (9, 0):
        issues.append({"type":"warning","message":f"FEIN format appears invalid: '{fein}'"})
    if not facts.get("effective_date"):
        issues.append({"type":"warning","message":"Policy effective date missing"})
    if "ACORD_140" in selected_form_ids and not facts.get("locations"):
        issues.append({"type":"hard_stop","message":"ACORD 140 selected but no property locations found"})
    if flags.get("has_general_liability"):
        if "ACORD_126" not in selected_form_ids:
            issues.append({"type":"warning","message":"GL coverage detected — ACORD 126 should be included"})
        if isinstance(facts.get("gl_class_codes"), list) and facts.get("gl_class_codes") and not facts.get("operations_description"):
            issues.append({"type":"warning","message":"GL class codes present but no operations description"})
        if flags.get("is_contractor"):
            pct = _num(facts.get("percent_subcontracted"))
            wc  = _num(facts.get("wc_payroll") or facts.get("total_payroll"))
            if pct and pct > 30 and not wc:
                issues.append({"type":"warning","message":f"High subcontracting ({pct:.0f}%) with no WC payroll"})
    wc_pay, tot_pay = _num(facts.get("wc_payroll")), _num(facts.get("total_payroll"))
    if wc_pay and tot_pay and tot_pay > 0:
        diff_pct = abs(wc_pay - tot_pay) / tot_pay
        if diff_pct > 0.20:
            issues.append({"type":"warning","message":f"WC payroll (${wc_pay:,.0f}) differs from total payroll (${tot_pay:,.0f}) by {diff_pct*100:.0f}%"})
    rev = _num(facts.get("total_revenue"))
    if rev and tot_pay and tot_pay > 0 and rev > 0:
        ratio = tot_pay / rev
        if ratio > 0.85:
            issues.append({"type":"warning","message":f"Payroll is {ratio*100:.0f}% of revenue — unusually high"})
    if "ACORD_140" in selected_form_ids:
        if flags.get("property_has_bi_coverage") and not facts.get("business_income_limit"):
            issues.append({"type":"warning","message":"Business Income coverage detected — BI limit required"})
        if not facts.get("valuation_method"):
            issues.append({"type":"warning","message":"Property valuation method not specified on ACORD 140"})
    if "ACORD_131" in selected_form_ids and not facts.get("gl_limits"):
        issues.append({"type":"hard_stop","message":"Umbrella selected but GL limits missing"})
    return issues


# ══════════════════════════════════════════════════════════════════
#  SQS
# ══════════════════════════════════════════════════════════════════
def calculate_sqs(facts, flags, mapped_data, form_schema, selected_form_ids, hard_stops, soft_stops,
                  tier2_score, form_id=None, schema_size=None, fields_mapped=None) -> dict:
    breakdown = {}; issues = []; recommendations = []; fraud_penalty = 0
    fid = form_id or (selected_form_ids[0] if selected_form_ids else "UNKNOWN")
    is_cert_only = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
    total_fields  = schema_size  if schema_size  is not None else len(form_schema)
    filled_fields = fields_mapped if fields_mapped is not None else sum(
        1 for v in mapped_data.values() if v is not None and str(v).strip() not in ("", "null", "None"))
    fill_rate = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    if is_cert_only:
        chks = [bool(facts.get("applicant_name") or facts.get("certificate_holder")),
                bool(facts.get("effective_date")), bool(facts.get("policy_number")),
                bool(facts.get("gl_limits") or facts.get("gl_aggregate"))]
        struct = int(sum(chks) / len(chks) * 100)
    elif fid == "ACORD_125":
        chks = [bool(facts.get("applicant_name")), bool(facts.get("mailing_address")),
                bool(facts.get("effective_date")), bool(facts.get("lines_of_business")),
                bool(facts.get("contact_name") or facts.get("contact_phone") or facts.get("contact_email")),
                bool(facts.get("producer_name"))]
        struct = int(sum(chks) / len(chks) * 100)
        missing = [l for l, ok in zip(["applicant name","mailing address","effective date","lines of business","contact info","producer name"], chks) if not ok]
        if missing: recommendations.append("ACORD 125 missing: " + ", ".join(missing))
    elif fid == "ACORD_126":
        chks = [bool(facts.get("gl_limits") or facts.get("gl_aggregate") or facts.get("gl_each_occurrence")),
                bool(facts.get("gl_class_codes")), bool(facts.get("operations_description")),
                bool(facts.get("total_payroll") or facts.get("total_revenue")), bool(facts.get("gl_form_type"))]
        struct = int(sum(chks) / len(chks) * 100)
        if not facts.get("gl_class_codes"): issues.append("GL class codes missing"); recommendations.append("Provide GL class codes")
        if not facts.get("gl_form_type"): recommendations.append("Specify GL form type: occurrence or claims-made")
    elif fid == "ACORD_140":
        min_cope = [bool(facts.get("locations")), bool(facts.get("occupancy_type")),
                    bool(facts.get("construction_type")), bool(facts.get("property_building_value") or facts.get("property_bpp_value"))]
        if not all(min_cope):
            struct = 0; issues.append("Minimum Viable COPE incomplete")
            recommendations.append("Required: street address, occupancy, construction type, building/BPP value")
        else:
            carrier_cope = [bool(facts.get(k)) for k in ["year_built","roof_year","sprinkler_system","fire_protection_class","valuation_method","coinsurance_percentage"]]
            struct = int(60 + (sum(carrier_cope) / len(carrier_cope)) * 40)
            mc = [l for l, ok in zip(["year built","roof year","sprinkler system","fire protection class","valuation method","coinsurance %"], carrier_cope) if not ok]
            if mc: recommendations.append("For Carrier-Grade COPE provide: " + ", ".join(mc))
    else:
        struct = fill_rate
    breakdown["structural_completeness"] = struct

    if fid == "ACORD_125":
        chks = [bool(facts.get("total_revenue") or facts.get("total_payroll")), bool(facts.get("operations_description")),
                bool(facts.get("num_employees")), bool(facts.get("fein")), bool(facts.get("entity_type"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if facts.get("naics_code") or facts.get("sic_code"): exp_score = min(100, exp_score + 5)
    elif fid == "ACORD_126":
        chks = [bool(facts.get("gl_class_codes")), bool(facts.get("total_payroll") or facts.get("total_revenue")),
                bool(facts.get("operations_description")), bool(facts.get("gl_limits"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if isinstance(facts.get("gl_class_codes"), list) and facts.get("gl_class_codes"): exp_score = min(100, exp_score + 10)
        else: exp_score = max(0, exp_score - 15); recommendations.append("Add GL class codes")
    elif fid == "ACORD_140":
        chks = [bool(facts.get("valuation_method")), bool(facts.get("coinsurance_percentage") or facts.get("property_deductible_aop")),
                bool(facts.get("property_building_value") or facts.get("property_bpp_value")), bool(facts.get("occupancy_type"))]
        exp_score = int(sum(chks) / len(chks) * 100)
        if not facts.get("valuation_method"): exp_score = max(0, exp_score - 15); recommendations.append("Specify RCV or ACV valuation method")
    else:
        chks = [bool(facts.get("total_revenue") or facts.get("total_payroll")), bool(facts.get("operations_description"))]
        exp_score = int(sum(chks) / len(chks) * 100)
    breakdown["exposure_consistency"] = exp_score

    if fid == "ACORD_140":
        prop = struct
        if flags.get("property_has_bi_coverage") and facts.get("business_income_limit") and not facts.get("period_of_restoration"):
            prop = max(0, prop - 8); recommendations.append("Add Period of Restoration")
        if flags.get("property_has_peril_deductibles"):
            d = sum(bool(facts.get(f)) for f in ["property_deductible_wind","property_deductible_earthquake","property_deductible_flood"])
            if d == 0: prop = max(0, prop - 10); recommendations.append("Define peril deductibles")
    elif flags.get("has_property_coverage"):
        min_ok = all([bool(facts.get("locations")), bool(facts.get("occupancy_type")), bool(facts.get("construction_type")),
                      bool(facts.get("property_building_value") or facts.get("property_bpp_value"))])
        if not min_ok: prop = 0; issues.append("Minimum Viable COPE incomplete")
        else:
            cc = [bool(facts.get(k)) for k in ["year_built","roof_year","sprinkler_system","fire_protection_class","valuation_method","coinsurance_percentage"]]
            prop = int(60 + (sum(cc)/len(cc))*40)
    else:
        prop = 100
    breakdown["property_integrity"] = prop

    has_loss = flags.get("has_loss_history") or bool(facts.get("num_claims"))
    has_carrier = bool(facts.get("prior_carrier"))
    loss_score = 90 if (has_loss and has_carrier) else 80 if has_loss else 65 if has_carrier else 50
    if not has_loss: recommendations.append("Attach 3–5 years of loss runs to improve SQS")
    breakdown["loss_history_alignment"] = loss_score

    if flags.get("has_umbrella"):
        has_underlying = bool(facts.get("gl_limits") or facts.get("auto_liability_limit"))
        umbrella_score = 100 if has_underlying else 0
        if not has_underlying: issues.append("Umbrella detected but no underlying GL/Auto limits"); recommendations.append("Provide underlying limits")
    else:
        umbrella_score = 100
    breakdown["umbrella_limit_adequacy"] = umbrella_score

    narrative_score = min(tier2_score, 100)
    if len(str(facts.get("operations_description") or "")) > 50: narrative_score = min(100, narrative_score + 10)
    breakdown["narrative_quality"] = narrative_score

    weights = {"structural_completeness":0.25,"exposure_consistency":0.25,"property_integrity":0.15,
               "loss_history_alignment":0.15,"umbrella_limit_adequacy":0.10,"narrative_quality":0.10}
    raw_score = int(sum(breakdown[k] * w for k, w in weights.items()))

    cope_hard = fid == "ACORD_140" and prop == 0
    umb_fail  = flags.get("has_umbrella") and umbrella_score == 0
    if hard_stops or cope_hard or umb_fail: raw_score = min(raw_score, 60)
    elif soft_stops: raw_score = min(raw_score, 85)
    raw_score = max(0, raw_score - fraud_penalty)

    tier, tc = (("Carrier-Ready","green") if raw_score>=90 else ("Review-Ready","yellow") if raw_score>=75
                else ("At-Risk","orange") if raw_score>=60 else ("Decline-Prone","red"))
    routing = ("auto_quote" if raw_score>=85 else "review" if raw_score>=65 else "full_review" if raw_score>=40 else "hold")

    risk_drivers = [{"component": k.replace("_"," ").title(), "score": v}
                    for k, v in sorted(breakdown.items(), key=lambda x: x[1])[:3] if v < 90]

    return {"sqs_score": raw_score, "tier": tier, "tier_color": tc,
            "grade": "A" if raw_score>=90 else "B" if raw_score>=80 else "C" if raw_score>=70 else "D" if raw_score>=60 else "F",
            "routing_decision": routing, "breakdown": breakdown, "risk_drivers": risk_drivers,
            "issues": issues, "recommendations": recommendations,
            "fraud_penalty": fraud_penalty, "fill_rate": fill_rate, "form_id": fid}


def _collect_fields_pikepdf(arr, results: dict):
    for item in arr:
        try:
            t = item.get("/T", None); kids = item.get("/Kids", None)
            ft = str(item.get("/FT", "")); tu = str(item.get("/TU", ""))[:80]
            ff = int(item.get("/Ff", 0) or 0)
            if t: results[str(t)] = {"ft": ft, "tu": tu, "required": bool(ff & 2)}
            if kids: _collect_fields_pikepdf(kids, results)
        except Exception: pass

def extract_form_schema(path: str) -> dict:
    if not os.path.exists(path): return {}
    try:
        pdf = pikepdf.open(path)
        if "/AcroForm" not in pdf.Root: pdf.close(); return {}
        schema = {}
        _collect_fields_pikepdf(pdf.Root["/AcroForm"]["/Fields"], schema)
        pdf.close()
        return schema
    except Exception as ex:
        logger.error(f"extract_form_schema error: {ex}"); return {}


# ══════════════════════════════════════════════════════════════════
#  AI MAPPING
# ══════════════════════════════════════════════════════════════════
_ACORD_FIELD_RULES = [
    ("Producer_FullName","producer_name"),("Producer_CustomerIdentifier","producer_name"),
    ("Producer_ContactPerson_FullName","contact_name"),("Producer_ContactPerson_Phone","contact_phone"),
    ("Producer_ContactPerson_Email","contact_email"),
    ("Producer_MailingAddress_LineOne","_addr_line1"),("Producer_MailingAddress_LineTwo","_addr_line2"),
    ("Producer_MailingAddress_CityName","_addr_city"),("Producer_MailingAddress_StateOrProv","_addr_state"),
    ("Producer_MailingAddress_PostalCode","_addr_zip"),
    ("NamedInsured_FullName","applicant_name"),
    ("NamedInsured_MailingAddress_LineOne","_addr_line1"),("NamedInsured_MailingAddress_LineTwo","_addr_line2"),
    ("NamedInsured_MailingAddress_CityName","_addr_city"),("NamedInsured_MailingAddress_StateOrProv","_addr_state"),
    ("NamedInsured_MailingAddress_PostalCode","_addr_zip"),
    ("Policy_PolicyNumberIdentifier","policy_number"),("Policy_EffectiveDate","effective_date"),
    ("Policy_ExpirationDate","expiration_date"),("Form_CompletionDate","effective_date"),
    ("Insurer_FullName","prior_carrier"),
    ("GeneralLiability_EachOccurrence","gl_each_occurrence"),("GeneralLiability_GeneralAggregate","gl_aggregate"),
    ("GeneralLiability_Aggregate","gl_aggregate"),("GeneralAggregate","gl_aggregate"),
    ("EachOccurrence","gl_each_occurrence"),
    ("CommercialProperty_Premises_LimitAmount","property_building_value"),
    ("CommercialStructure_Construction_TypeCode","construction_type"),
    ("CommercialStructure_YearBuilt","year_built"),("CommercialStructure_Roof_Year","roof_year"),
    ("CommercialStructure_Occupancy","occupancy_type"),
    ("CertificateHolder_FullName","certificate_holder"),
    ("AutoLiability_CombinedSingleLimit","auto_liability_limit"),
    ("WorkersCompensation_Payroll","wc_payroll"),("Umbrella_EachOccurrence","umbrella_limit"),
]

def _parse_address(addr: str) -> dict:
    if not addr: return {}
    parts = [p.strip() for p in addr.split(",")]; result = {}
    if len(parts) >= 1: result["line1"] = parts[0]
    if len(parts) >= 3:
        last = parts[-1].strip().split()
        if len(last) >= 2: result["state"] = last[-2]; result["zip"] = last[-1]
        result["city"] = parts[-2]
    return result

def _resolve_special(key: str, facts: dict, prefix: str) -> str:
    if prefix == "_addr": raw = facts.get("mailing_address", "")
    elif prefix == "_loc":
        locs = facts.get("locations", []); raw = locs[0] if isinstance(locs, list) and locs else facts.get("mailing_address","")
    else: raw = facts.get("mailing_address", "")
    parsed = _parse_address(raw); suffix = key.split("_")[-1]
    return parsed.get(suffix, "") or ""

def _deterministic_map(field_name: str, facts: dict):
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None: return None
            if fact_key.startswith("_"): return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
            val = facts.get(fact_key)
            if isinstance(val, list): return str(val[0]) if val else None
            return str(val) if val is not None else None
    return "UNMATCHED"

def map_facts_to_form(facts: dict, schema: dict) -> Tuple[dict, dict]:
    if not schema: return {}, {}
    mapped = {}; unmatched = {}; confidence = {}
    for field in schema.keys():
        result = _deterministic_map(field, facts)
        if result == "UNMATCHED": unmatched[field] = schema[field]
        else: mapped[field] = result

    if unmatched:
        BATCH = 40; unmatched_keys = list(unmatched.keys()); ai_mapped: dict = {}
        for batch_start in range(0, len(unmatched_keys), BATCH):
            batch_keys  = unmatched_keys[batch_start:batch_start + BATCH]
            batch_hints = []
            for k in batch_keys:
                info = unmatched[k] if isinstance(unmatched[k], dict) else {}
                tu   = info.get("tu","")[:60] if info else ""
                batch_hints.append(k + (f"  # {tu}" if tu else ""))
            prompt = (f"Map these PDF form fields to insurance facts. Return ONLY JSON. Use null if no match.\n\n"
                      f"Facts: {json.dumps(facts, indent=2)}\n\nFields: {json.dumps(batch_hints)}\n\nOutput:")
            try:
                r   = client.chat.completions.create(model="llama-3.1-8b-instant",
                        messages=[{"role":"user","content":prompt}], temperature=0)
                raw = (r.choices[0].message.content or "").strip()
                if raw.startswith("```"): raw = raw.replace("```json","").replace("```","").strip()
                s, e = raw.find("{"), raw.rfind("}")
                if s != -1 and e != -1: ai_mapped.update(json.loads(raw[s:e+1]))
            except Exception as ex:
                logger.warning(f"AI batch failed: {ex}")
        mapped.update(ai_mapped)

    for field, meta in schema.items():
        val       = mapped.get(field)
        has_value = val is not None and str(val).strip() not in ("", "null", "None")
        is_req    = meta.get("required", False) if isinstance(meta, dict) else False
        was_ai    = field in unmatched and field in mapped and mapped[field] is not None
        if has_value: confidence[field] = "low_confidence" if was_ai else "filled"
        elif is_req:  confidence[field] = "missing_required"
        else:         confidence[field] = "low_confidence"

    total_filled = sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("","null","None"))
    logger.info(f"Mapped {total_filled}/{len(schema)} fields")
    return mapped, confidence


# ══════════════════════════════════════════════════════════════════
#  PDF FILLING
# ══════════════════════════════════════════════════════════════════
def _fill_and_highlight(arr, data: dict, confidence: dict, counter: list):
    YELLOW = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(1.0), pikepdf.Real(0.0)])
    PINK   = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(0.71), pikepdf.Real(0.76)])
    WHITE  = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(1.0), pikepdf.Real(1.0)])
    for item in arr:
        try:
            t = item.get("/T", None); kids = item.get("/Kids", None)
            if t:
                name = str(t); val = data.get(name); conf = confidence.get(name, "low_confidence")
                if val is not None and str(val).strip() not in ("", "null", "None"):
                    item["/V"] = pikepdf.String(str(val))
                    if "/AP" in item: del item["/AP"]
                    counter[0] += 1
                if conf == "filled":             item["/MK"] = pikepdf.Dictionary(**{"/BG": WHITE})
                elif conf == "missing_required": item["/MK"] = pikepdf.Dictionary(**{"/BG": YELLOW})
                else:                            item["/MK"] = pikepdf.Dictionary(**{"/BG": PINK})
            if kids: _fill_and_highlight(kids, data, confidence, counter)
        except Exception: pass

def fill_pdf(template_path: str, data: dict, confidence: Optional[dict] = None) -> bytes:
    try:
        pdf = pikepdf.open(template_path)
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            counter = [0]
            _fill_and_highlight(acro.get("/Fields", []), data, confidence or {}, counter)
            logger.info(f"fill_pdf: wrote {counter[0]} field values with highlights")
        else:
            logger.warning("fill_pdf: no AcroForm")
        buf = io.BytesIO(); pdf.save(buf); pdf.close(); buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"fill_pdf error: {ex}")
        with open(template_path, "rb") as f: return f.read()


# ══════════════════════════════════════════════════════════════════
#  BULK FORM PROCESSING HELPER
# ══════════════════════════════════════════════════════════════════
def process_single_form(form_meta: dict, session: dict) -> dict:
    tpl  = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
    schema = extract_form_schema(tpl)
    mapped, confidence = map_facts_to_form(session["facts"], schema)
    selected_ids = session.get("selected_form_ids", []) + [form_meta["form_id"]]
    cross = cross_validate(session["facts"], session["flags"], selected_ids)
    sqs   = calculate_sqs(facts=session["facts"], flags=session["flags"],
                mapped_data=mapped, form_schema=schema,
                selected_form_ids=[form_meta["form_id"]],
                hard_stops=session.get("hard_stops", []), soft_stops=session.get("soft_stops", []),
                tier2_score=session.get("tier2_score", 50), form_id=form_meta["form_id"],
                schema_size=len(schema),
                fields_mapped=sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("","null","None")))
    pdf_bytes = fill_pdf(tpl, mapped, confidence)
    return {"form_id": form_meta["form_id"], "form_name": form_meta["form_name"],
            "form": form_meta, "schema": schema, "mapped": mapped,
            "confidence": confidence, "sqs": sqs, "cross": cross, "pdf_bytes": pdf_bytes}


# ══════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════
@app.get("/")
def home():
    return {"message": "Acordly API v12.3.1", "status": "operational"}

@app.get("/api/health")
def health():
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM users"); count = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) as c FROM processing_sessions"); ps_count = cur.fetchone()['c']
        cur.close(); conn.close()
        return {"status":"healthy","users":count,"active_sessions":ps_count}
    except Exception as e:
        return {"status":"error","detail":str(e)}


@app.post("/api/upload-declaration")
async def upload_declaration(files: List[UploadFile] = File(...), current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT payment_status, subscription_tier FROM users WHERE id = %s", (current_user['id'],))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        ps = dict(row).get('payment_status', 'ok') or 'ok'
        if ps == 'suspended': raise HTTPException(403, "Account suspended due to non-payment.")
        if ps == 'archived':  raise HTTPException(403, "Account archived. Please contact support@acordly.ai.")
        if ps == 'soft_locked': raise HTTPException(403, "Account disabled due to overdue payment. Please update your billing to restore access.")

    try:
        all_paths = []
        for f in files:
            path = os.path.join(UPLOAD_DIR, f.filename)
            with open(path, "wb") as fp: fp.write(await f.read())
            ext = os.path.splitext(f.filename.lower())[1]
            if ext == '.zip': all_paths.extend(extract_zip(path))
            elif ext == '.pdf' or ext in SUPPORTED_IMG: all_paths.append(path)

        if not all_paths: raise HTTPException(400, "No supported files found")

        processed_docs = []
        for path in all_paths:
            text = extract_text(path)
            if len(text) < 30: continue
            doc_type  = identify_doc_type(text)
            extracted = extract_facts(text)
            processed_docs.append({"filename": os.path.basename(path), "path": path, "doc_type": doc_type,
                                    "text": text, "facts": extracted.get("facts", {}), "flags": extracted.get("flags", {})})

        if not processed_docs: raise HTTPException(400, "No readable text found in uploaded files")

        primary              = select_primary_truth(processed_docs)
        merged_facts, mflags = merge_facts(processed_docs, primary)
        tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

        if not tier1_ok:
            return JSONResponse({"success": False, "gate": "tier1_fail",
                                  "message": "Submission missing required fields",
                                  "missing_fields": tier1_missing, "flags": mflags})

        tier2_score, tier2_missing = check_tier2(merged_facts)
        hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)
        all_forms                  = load_all_forms()
        available_forms            = filter_available_forms(all_forms)
        recommendations            = match_forms(merged_facts, mflags, available_forms)

        sid = new_processing_session({
            "user_id": current_user['id'], "docs": processed_docs,
            "primary_doc": primary["filename"], "facts": merged_facts, "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": hard_stops, "soft_stops": soft_stops,
            "all_forms": available_forms, "recommendations": recommendations,
            "selected_form_ids": [], "generated_forms": {},
        })

        return JSONResponse({
            "success": True, "session_id": sid,
            "doc_summary": [{"filename":d["filename"],"doc_type":d["doc_type"],"is_primary":d["filename"]==primary["filename"]} for d in processed_docs],
            "primary_doc": primary["filename"], "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": hard_stops, "soft_stops": soft_stops,
            "recommendations": recommendations,
            "all_available_forms": [{"form_id":f["form_id"],"form_name":f["form_name"],"description":f.get("description","")} for f in available_forms],
        })
    except Exception as ex:
        logger.error(f"Upload error: {ex}"); raise HTTPException(500, str(ex))


@app.post("/api/select-forms-bulk")
async def select_forms_bulk(req: BulkFormSelectionRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT payment_status FROM users WHERE id = %s", (current_user['id'],))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        ps = dict(row).get('payment_status', 'ok') or 'ok'
        if ps in ('soft_locked', 'suspended', 'archived'):
            raise HTTPException(403, "Account disabled due to non-payment. Please update your billing to restore access.")

    session = get_processing_session(req.session_id)
    results = {}; combined_ids = req.form_ids

    for form_id in req.form_ids:
        form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
        if not form_meta: continue
        tpl = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
        if not os.path.exists(tpl): continue
        try:
            result = process_single_form(form_meta, session)
            results[form_id] = result
        except Exception as ex:
            logger.error(f"Error processing {form_id}: {ex}")

    if not results: raise HTTPException(400, "No forms could be generated")

    cross_issues_raw = cross_validate(session["facts"], session["flags"], combined_ids)
    seen_msgs = set(); cross_issues_deduped = []
    for issue in cross_issues_raw:
        msg = issue.get("message", "")
        if msg not in seen_msgs: seen_msgs.add(msg); cross_issues_deduped.append(issue)

    upd_processing_session(req.session_id, {
        "selected_form_ids": combined_ids, "generated_forms": results,
        "active_form_id": combined_ids[0] if combined_ids else None,
        "cross_issues_last": cross_issues_deduped,
    })

    summary = {}
    for fid, r in results.items():
        summary[fid] = {"form_id": r["form_id"], "form_name": r["form_name"], "form": r["form"],
                         "sqs": r["sqs"], "fields_mapped": sum(1 for v in r["mapped"].values() if v is not None),
                         "schema_size": len(r["schema"])}

    return JSONResponse({"success": True, "generated": summary, "form_ids": combined_ids, "cross_issues": cross_issues_deduped})


@app.post("/api/select-form")
async def select_form(req: FormSelectionRequest, current_user: dict = Depends(get_current_user)):
    return await select_forms_bulk(BulkFormSelectionRequest(session_id=req.session_id, form_ids=[req.selected_form_id]), current_user)


def _validate_token_from_request(token_query: Optional[str], authorization: Optional[str]) -> bool:
    raw_token = None
    if authorization and authorization.startswith("Bearer "): raw_token = authorization.replace("Bearer ", "")
    elif token_query: raw_token = token_query
    if not raw_token: return False
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT expires_at FROM sessions WHERE token = %s", (raw_token,))
    sess = cur.fetchone(); cur.close(); conn.close()
    if not sess: return False
    return datetime.fromisoformat(dict(sess)['expires_at']) >= datetime.now(timezone.utc)


def _regenerate_pdf_for_form(proc_session: dict, form_id: str, force: bool = False) -> bytes:
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated: raise HTTPException(404, f"Form {form_id} not generated")
    r          = generated[form_id]
    tpl        = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    field_data = r.get("field_state") or r.get("mapped", {})
    confidence = r.get("confidence", {})

    if r.get("signature_applied") and r.get("pdf_bytes"):
        cached = r["pdf_bytes"]
        return cached if isinstance(cached, bytes) else bytes(cached)

    if not force:
        import hashlib
        state_hash   = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
        cached_hash  = r.get("_pdf_cache_hash")
        cached_bytes = r.get("pdf_bytes")
        if cached_bytes and cached_hash == state_hash:
            return cached_bytes if isinstance(cached_bytes, bytes) else bytes(cached_bytes)

    pdf_bytes = fill_pdf(tpl, field_data, confidence)
    import hashlib
    state_hash = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
    generated[form_id]["pdf_bytes"]       = pdf_bytes
    generated[form_id]["_pdf_cache_hash"] = state_hash
    return pdf_bytes


def extract_form_fields_with_positions(path: str) -> List[dict]:
    fields: List[dict] = []
    if not os.path.exists(path): return fields
    try:
        pdf = pikepdf.open(path)
        for page_idx, page in enumerate(pdf.pages):
            raw_annots = page.get("/Annots", None)
            if raw_annots is None: continue
            try: annot_list = list(raw_annots)
            except Exception: continue
            for annot_ref in annot_list:
                try:
                    annot = annot_ref
                    if "/Widget" not in str(annot.get("/Subtype", "")): continue
                    t = annot.get("/T")
                    if t is None:
                        parent = annot.get("/Parent")
                        if parent: t = parent.get("/T")
                    if t is None: continue
                    name = str(t)
                    rect = annot.get("/Rect")
                    if rect is None: continue
                    x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        parent = annot.get("/Parent")
                        if parent: ft_raw = parent.get("/FT")
                    ft_str = str(ft_raw) if ft_raw else "/Tx"
                    field_type = "checkbox" if "/Btn" in ft_str else "dropdown" if "/Ch" in ft_str else "text"
                    v = annot.get("/V")
                    if v is None:
                        parent = annot.get("/Parent")
                        if parent: v = parent.get("/V")
                    val = ""
                    if v is not None:
                        sv = str(v)
                        if sv.startswith("/"): sv = sv[1:]
                        val = sv if sv not in ("Off", "null", "None") else ""
                    fields.append({"name": name, "page": page_idx,
                                   "rect": {"x": round(x1, 2), "y": round(y1, 2),
                                            "width": round(x2-x1, 2), "height": round(y2-y1, 2)},
                                   "type": field_type, "value": val})
                except Exception: pass
        pdf.close()
    except Exception as ex:
        logger.error(f"extract_form_fields_with_positions error: {ex}")
    return fields


def get_page_dims_pikepdf(path: str) -> List[dict]:
    dims = []
    try:
        pdf = pikepdf.open(path)
        for page in pdf.pages:
            mb = page.get("/MediaBox", None)
            if mb: dims.append({"width": float(mb[2])-float(mb[0]), "height": float(mb[3])-float(mb[1])})
            else:  dims.append({"width": 612.0, "height": 792.0})
        pdf.close()
    except Exception as ex:
        logger.error(f"get_page_dims_pikepdf error: {ex}")
    return dims


@app.get("/api/fields/{session_id}/{form_id}")
async def get_form_fields(session_id: str, form_id: str,
                          token: Optional[str] = Query(default=None),
                          authorization: str   = Header(default=None)):
    if not _validate_token_from_request(token, authorization):
        raise HTTPException(401, "Not authenticated")
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated: raise HTTPException(404, f"Form '{form_id}' not found")
    r   = generated[form_id]
    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    if not os.path.exists(tpl): raise HTTPException(404, f"Template not found")
    fields    = extract_form_fields_with_positions(tpl)
    page_dims = get_page_dims_pikepdf(tpl)
    field_state = r.get("field_state") or r.get("mapped", {})
    for f in fields:
        if f["name"] in field_state:
            sv = field_state[f["name"]]
            f["value"] = str(sv) if sv is not None and str(sv) not in ("null", "None") else ""
    return JSONResponse({"success": True, "fields": fields, "page_dims": page_dims})


@app.get("/api/get-pdf/{session_id}/{form_id}")
async def get_pdf(session_id: str, form_id: str,
                  token: Optional[str] = Query(default=None),
                  authorization: str = Header(default=None)):
    if not _validate_token_from_request(token, authorization):
        raise HTTPException(401, "Not authenticated")
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form {form_id} not generated")

    r = generated[form_id]

    if r.get("signature_applied") and r.get("pdf_bytes"):
        pdf_bytes = r["pdf_bytes"]
        if not isinstance(pdf_bytes, bytes):
            pdf_bytes = bytes(pdf_bytes)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={form_id}_preview.pdf",
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            }
        )

    pdf_bytes = _regenerate_pdf_for_form(proc_session, form_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename={form_id}_preview.pdf",
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        }
    )


@app.post("/api/update-pdf")
async def update_pdf(req: PDFUpdateRequest, current_user: dict = Depends(get_current_user)):
    session   = get_processing_session(req.session_id)
    generated = session.get("generated_forms", {})
    active_id = session.get("active_form_id")

    form_id = req.field_updates.pop("__form_id__", active_id)
    req.field_updates.pop("__signed__", None)

    cleared_sig_fields_raw = req.field_updates.pop("__cleared_sig_fields__", "[]")
    try:
        cleared_sig_fields = set(json.loads(cleared_sig_fields_raw))
    except Exception:
        cleared_sig_fields = set()

    if not form_id or form_id not in generated:
        raise HTTPException(400, "No active form to update")

    r = generated[form_id]
    current_state = r.get("field_state", dict(r.get("mapped", {})))
    current_state.update(req.field_updates)
    confidence = r.get("confidence", {})
    for k in req.field_updates:
        confidence[k] = "filled"

    sqs = calculate_sqs(
        facts=session["facts"], flags=session["flags"],
        mapped_data=current_state, form_schema=r.get("schema", {}),
        selected_form_ids=session.get("selected_form_ids", []),
        hard_stops=session.get("hard_stops", []), soft_stops=session.get("soft_stops", []),
        tier2_score=session.get("tier2_score", 50)
    )

    was_signed = bool(r.get("signature_applied")) and len(cleared_sig_fields) == 0

    new_pdf_bytes   = None
    new_sig_applied = False

    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    if os.path.exists(tpl):
        new_pdf_bytes = fill_pdf(tpl, current_state, confidence)

        if was_signed:
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT signature_data FROM users WHERE id = %s", (current_user["id"],))
            row = cur.fetchone(); cur.close(); conn.close()
            sig = dict(row).get("signature_data") if row else None
            if sig:
                field_data_for_sig = dict(current_state)
                for fn in list(field_data_for_sig.keys()):
                    if _is_signature_field(fn) and fn not in cleared_sig_fields:
                        field_data_for_sig[fn] = ""
                        confidence[fn] = "filled"
                try:
                    new_pdf_bytes   = _inject_signature_into_pdf(tpl, field_data_for_sig, confidence, sig)
                    new_sig_applied = True
                except Exception as ex:
                    logger.error(f"update_pdf: signature re-injection failed: {ex}")
                    new_sig_applied = False

    import hashlib
    cache_hash = hashlib.md5(new_pdf_bytes).hexdigest() if new_pdf_bytes else None

    generated[form_id].update({
        "field_state":       current_state,
        "confidence":        confidence,
        "sqs":               sqs,
        "_pdf_cache_hash":   cache_hash,
        "pdf_bytes":         new_pdf_bytes,
        "signature_applied": new_sig_applied,
    })
    upd_processing_session(req.session_id, {"generated_forms": generated})
    return JSONResponse({"success": True, "sqs": sqs})

@app.get("/api/session/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    summary = {fid: {"form_id": r.get("form_id", fid), "form_name": r.get("form_name", fid),
                     "form": r.get("form", {}), "sqs": r.get("sqs", {})} for fid, r in generated.items()}
    return JSONResponse({"session_id": session_id, "generated_forms": summary,
                         "cross_issues": proc_session.get("cross_issues_last", [])})


@app.get("/api/download-pdf/{session_id}/{form_id}")
async def download_pdf(session_id: str, form_id: str, request: Request,
                       current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (current_user['id'],))
    fresh = cur.fetchone(); cur.close(); conn.close()
    if not fresh: raise HTTPException(401, "User not found")
    fresh = dict(fresh)
    sub = fresh.get('subscription_tier', 'free') or 'free'
    used = int(fresh.get('downloads_used', 0) or 0)

    if fresh.get('payment_status') == 'suspended':
        return JSONResponse({"success": False, "payment_locked": True,
                             "message": "Account suspended due to non-payment."}, status_code=403)
    if fresh.get('payment_status') == 'soft_locked':
        return JSONResponse({"success": False, "payment_locked": True,
                             "message": "Account disabled — please update your billing."}, status_code=403)

    if sub == 'free' and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True,
                             "message": "Free limit reached. Upgrade to continue."}, status_code=403)

    pkg_eval = None
    if sub in ('essentials', 'professional'):
        pkg_eval = _evaluate_package_limit(fresh)

    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    form_name    = generated.get(form_id, {}).get("form_name", form_id)

    pdf_bytes   = _regenerate_pdf_for_form(proc_session, form_id, force=True)
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"
    sqs_results = {form_id: generated[form_id].get("sqs", {})} if form_id in generated else {}

    ai_content = _generate_ai_cover_narrative(
        facts=facts, flags=flags, sqs_results=sqs_results,
        form_ids=[form_id], org_name=org_name, user=fresh
    )
    cover_pdf = _build_cover_page_pdf(
        facts=facts, flags=flags, sqs_results=sqs_results,
        form_ids=[form_id], org_name=org_name,
        narrative=ai_content["narrative"], ai_block=ai_content["ai_block"],
        sqs_reasoning=ai_content.get("sqs_reasoning", ""), user=fresh
    )

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        zf.writestr(f"{form_id}_FILLED.pdf", pdf_bytes)
    zip_buf.seek(0)

    conn = get_db(); cur = conn.cursor()
    if sub == 'free':
        cur.execute("UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s", (fresh['id'],))
    elif sub in ('essentials', 'professional') and pkg_eval:
        cur.execute("UPDATE users SET packages_used = packages_used + 1 WHERE id = %s", (fresh['id'],))

        if pkg_eval["status"] == "overage":
            stripe_queued = _create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
            if stripe_queued:
                cur.execute(
                    "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced, 0) + 1 WHERE id = %s",
                    (fresh['id'],)
                )
            else:
                cur.execute(
                    "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending, 0) + 1 WHERE id = %s",
                    (fresh['id'],)
                )
                logger.warning(f"⚠️ Stripe overage queue failed — added to pending for user={fresh['id']}")
        elif pkg_eval["status"] == "soft_buffer":
            logger.info(f"Soft-buffer download (free): user={fresh['id']} plan={sub}")

    conn.commit(); cur.close(); conn.close()

    write_audit_log(user=fresh, action='download', form_id=form_id, form_name=form_name,
                    session_id=session_id, ip_address=request.client.host if request.client else None)

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"] = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={form_id}_Package.zip",
            **extra_headers,
        }
    )


# ══════════════════════════════════════════════════════════════════
#  COVER PAGE
# ══════════════════════════════════════════════════════════════════

def _generate_ai_cover_narrative(facts: dict, flags: dict, sqs_results: dict,
                                  form_ids: List[str], org_name: str, user: dict = None) -> dict:
    sqs_summary = [{"form": fid, "score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
                    "tier": sqs.get("tier"), "routing": sqs.get("routing_decision"),
                    "breakdown": sqs.get("breakdown", {}), "issues": sqs.get("issues", []),
                    "recommendations": sqs.get("recommendations", [])} for fid, sqs in sqs_results.items()]
    avg_sqs = int(sum(s.get("sqs_score", 0) for s in sqs_results.values()) / max(len(sqs_results), 1))

    prompt = f"""You are an expert commercial insurance underwriting analyst at Acordly.
Generate a professional cover page summary for this ACORD submission package.

SUBMISSION DATA:
Agent/User: {user.get('full_name', '') if user else ''}
Agency/Org: {org_name}
Applicant: {facts.get('applicant_name', 'Unknown')}
Lines of Business: {facts.get('lines_of_business', [])}
Effective Date: {facts.get('effective_date', 'Not specified')}
Expiration Date: {facts.get('expiration_date', 'Not specified')}
Operations: {facts.get('operations_description', 'Not provided')}
Revenue: {facts.get('total_revenue', 'Not provided')}
Employees: {facts.get('num_employees', 'Not provided')}
Prior Carrier: {facts.get('prior_carrier', 'Not provided')}
Forms Generated: {', '.join(form_ids)}
Overall Average SQS: {avg_sqs}/100
SQS Results: {json.dumps(sqs_summary)}

Respond with ONLY a valid JSON object with exactly three keys:
"narrative": A 3-4 paragraph professional narrative (plain text, no markdown)
"sqs_reasoning": A single paragraph (3-5 sentences) explaining the SQS score in plain English
"ai_block": A machine-readable structured JSON object with: submission_id, generated_at (ISO timestamp),
  agent_name, applicant_name, org_name, lines_of_business (array), effective_date, expiration_date,
  total_revenue, total_payroll, num_employees, entity_type, fein, naics_code, prior_carrier,
  forms_included (array), sqs_scores (object), sqs_grades (object), sqs_breakdowns (object),
  overall_avg_sqs, overall_routing_recommendation, hard_stops (array), soft_stops (array),
  risk_flags (array), acordly_version: "12.3.1", a2a_schema_version: "1.0"

Return ONLY the JSON object. No markdown, no backticks, no extra text."""

    try:
        r = client.chat.completions.create(model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}], temperature=0)
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"): raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s:e+1])
            return {"narrative": result.get("narrative", ""), "sqs_reasoning": result.get("sqs_reasoning", ""),
                    "ai_block": result.get("ai_block", {})}
    except Exception as ex:
        logger.error(f"Cover page AI generation failed: {ex}")

    return {"narrative": f"This ACORD submission package was prepared by {org_name} for applicant {facts.get('applicant_name', 'Unknown')}.",
            "sqs_reasoning": f"Average SQS of {avg_sqs}/100 across {len(form_ids)} form(s).",
            "ai_block": {"agent_name": (user.get("full_name", "") if user else ""), "applicant_name": facts.get("applicant_name"),
                         "org_name": org_name, "forms_included": form_ids,
                         "sqs_scores": {fid: sqs_results[fid].get("sqs_score") for fid in sqs_results},
                         "overall_avg_sqs": avg_sqs, "acordly_version": "12.3.1", "a2a_schema_version": "1.0"}}


def _build_cover_page_pdf(facts: dict, flags: dict, sqs_results: dict,
                           form_ids: List[str], org_name: str,
                           narrative: str, ai_block: dict,
                           sqs_reasoning: str = "", user: dict = None) -> bytes:
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, HRFlowable)
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
        from reportlab.pdfgen import canvas as rl_canvas

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter,
            leftMargin=0.65*inch, rightMargin=0.65*inch,
            topMargin=0.65*inch, bottomMargin=0.65*inch)

        NAVY   = colors.HexColor("#0f172a")
        PINK   = colors.HexColor("#e6007a")
        PINK_LIGHT = colors.HexColor("#fdf2f8")
        SLATE  = colors.HexColor("#64748b")
        LIGHT  = colors.HexColor("#f8fafc")
        LIGHTER= colors.HexColor("#f1f5f9")
        WHITE  = colors.white
        GREEN  = colors.HexColor("#10b981")
        YELLOW = colors.HexColor("#f59e0b")
        RED    = colors.HexColor("#ef4444")
        BORDER = colors.HexColor("#e2e8f0")
        TEXT_MAIN = colors.HexColor("#1e293b")
        TEXT_MUTE = colors.HexColor("#64748b")
        TEXT_HINT = colors.HexColor("#94a3b8")

        def sqs_color(score):
            if score is None: return SLATE
            if score >= 90: return GREEN
            if score >= 75: return YELLOW
            return RED

        styles = getSampleStyleSheet()
        def S(name, **kw): return ParagraphStyle(name, parent=styles["Normal"], **kw)

        h2_style     = S("H2",   fontSize=12, textColor=NAVY,     fontName="Helvetica-Bold", leading=17, spaceAfter=3)
        body_style   = S("Body", fontSize=9,  textColor=TEXT_MAIN, fontName="Helvetica",      leading=14, spaceAfter=3, alignment=TA_JUSTIFY)
        label_s      = S("Lbl",  fontSize=8,  textColor=SLATE,    fontName="Helvetica-Bold")
        val_s        = S("Val",  fontSize=8,  textColor=NAVY,     fontName="Helvetica")
        small_s      = S("Sm",   fontSize=7,  textColor=TEXT_HINT, fontName="Helvetica", leading=10)
        reasoning_s  = S("Rsn",  fontSize=9,  textColor=TEXT_MAIN, fontName="Helvetica-Oblique", leading=14, spaceAfter=3)
        disclaimer_s = S("Disc", fontSize=7,  textColor=TEXT_MUTE, fontName="Helvetica-BoldOblique", leading=10)

        story = []

        logo_cell    = Paragraph('<font color="#e6007a"><b>acordly</b></font>', S("Logo", fontSize=26, textColor=PINK, fontName="Helvetica-Bold", leading=32))
        powered_cell = Paragraph(f'<font color="#e6007a"><b>Powered by acordly.ai</b></font><br/><font color="#94a3b8" size="7">{generated_at}</font>',
                                  S("Pwr", fontSize=9, fontName="Helvetica", alignment=TA_RIGHT))
        header_tbl = Table([[logo_cell, powered_cell]], colWidths=[3.5*inch, 3.5*inch])
        header_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),NAVY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14),
            ("TOPPADDING",(0,0),(-1,-1),16),("BOTTOMPADDING",(0,0),(-1,-1),16)]))
        story.append(header_tbl); story.append(Spacer(1, 0.14*inch))

        agent_name = (user.get("full_name","") if user else "") or "—"
        applicant  = facts.get("applicant_name","—") or "—"
        eff_date   = facts.get("effective_date","—") or "—"
        exp_date   = facts.get("expiration_date","—") or "—"
        entity     = facts.get("entity_type","—") or "—"
        revenue    = facts.get("total_revenue","—") or "—"
        employees  = str(facts.get("num_employees","—") or "—")
        lobs_raw   = facts.get("lines_of_business", [])
        lobs       = ", ".join(lobs_raw) if lobs_raw else "—"
        addr       = facts.get("mailing_address","—") or "—"
        prior_carr = facts.get("prior_carrier","—") or "—"
        forms_list = ", ".join(form_ids) if form_ids else "—"

        info_rows = [
            [Paragraph("AGENT / USER",label_s),Paragraph(agent_name,val_s),Paragraph("POLICY PERIOD",label_s),Paragraph(f"{eff_date} – {exp_date}",val_s)],
            [Paragraph("AGENCY",label_s),Paragraph(org_name,val_s),Paragraph("ENTITY TYPE",label_s),Paragraph(entity,val_s)],
            [Paragraph("APPLICANT",label_s),Paragraph(applicant,val_s),Paragraph("ANNUAL REVENUE",label_s),Paragraph(revenue,val_s)],
            [Paragraph("LINES OF BUSINESS",label_s),Paragraph(lobs,val_s),Paragraph("EMPLOYEES",label_s),Paragraph(employees,val_s)],
            [Paragraph("FORMS INCLUDED",label_s),Paragraph(forms_list,val_s),Paragraph("PRIOR CARRIER",label_s),Paragraph(prior_carr,val_s)],
            [Paragraph("MAILING ADDRESS",label_s),Paragraph(addr,val_s),Paragraph("PREPARED BY",label_s),Paragraph(f"acordly.ai · {generated_at}",small_s)],
        ]
        info_tbl = Table(info_rows, colWidths=[1.2*inch,2.25*inch,1.3*inch,2.25*inch])
        info_tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS",(0,0),(-1,-1),[LIGHT,WHITE]),("LEFTPADDING",(0,0),(-1,-1),8),
            ("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),
            ("BOTTOMPADDING",(0,0),(-1,-1),5),("GRID",(0,0),(-1,-1),0.25,BORDER)]))
        story.append(info_tbl); story.append(Spacer(1, 0.14*inch))

        story.append(Paragraph("Submission Quality Scores (SQS)", h2_style))
        routing_labels = {"auto_quote":"✅ Auto-Quote","review":"🔍 Light Review","full_review":"📋 Full Review","hold":"🚫 Hold"}
        sqs_header = [Paragraph(f"<b>{h}</b>", S("TH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold"))
                      for h in ["Form","Score","Grade","Tier","Routing"]]
        sqs_rows = [sqs_header]
        for fid, sqs in sqs_results.items():
            score   = sqs.get("sqs_score", 0)
            sc      = sqs_color(score)
            routing = routing_labels.get(sqs.get("routing_decision",""), sqs.get("routing_decision","—"))
            sqs_rows.append([
                Paragraph(fid.replace("_"," "), S("Cell",fontSize=8,fontName="Helvetica")),
                Paragraph(f"<b>{score}/100</b>", S("Cell",fontSize=9,fontName="Helvetica-Bold",textColor=sc)),
                Paragraph(sqs.get("grade","—"), S("Cell",fontSize=8,fontName="Helvetica-Bold",textColor=sc)),
                Paragraph(sqs.get("tier","—"), S("Cell",fontSize=7,fontName="Helvetica")),
                Paragraph(routing, S("Cell",fontSize=7,fontName="Helvetica")),
            ])
        sqs_tbl = Table(sqs_rows, colWidths=[1.6*inch,0.75*inch,0.65*inch,1.4*inch,2.6*inch])
        sqs_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,LIGHTER]),
            ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("GRID",(0,0),(-1,-1),0.25,BORDER)]))
        story.append(sqs_tbl); story.append(Spacer(1, 0.10*inch))

        if sqs_reasoning and sqs_reasoning.strip():
            story.append(Paragraph("SQS Score Explanation", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(sqs_reasoning.strip(), reasoning_s))
            story.append(Spacer(1, 0.10*inch))

        story.append(Paragraph("Package Summary", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 0.05*inch))
        for para_text in narrative.split("\n"):
            para_text = para_text.strip()
            if para_text: story.append(Paragraph(para_text, body_style)); story.append(Spacer(1, 0.04*inch))
        story.append(Spacer(1, 0.10*inch))

        disclaimer_text = (
            "IMPORTANT — This page contains carrier-grade AI-to-AI (A2A) data for next-generation "
            "carrier AI ingestion engines. Please include this page in your underwriting submission package."
        )
        disclaimer_data = [[Paragraph("🤖", S("DIcon",fontSize=14,fontName="Helvetica")),
                            Paragraph(disclaimer_text, disclaimer_s)]]
        disclaimer_tbl = Table(disclaimer_data, colWidths=[0.3*inch, 6.7*inch])
        disclaimer_tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),PINK_LIGHT),("LEFTPADDING",(0,0),(-1,-1),8),
            ("RIGHTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),7),
            ("BOTTOMPADDING",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LINEABOVE",(0,0),(-1,-1),1,PINK),("LINEBELOW",(0,0),(-1,-1),1,PINK)]))
        story.append(disclaimer_tbl)
        story.append(Spacer(1, 0.10*inch))

        ai_json_str = json.dumps(ai_block, indent=2, default=str)
        wrapped_lines = []
        for line in ai_json_str.split("\n"):
            wrapped_lines.extend(textwrap.wrap(line, width=110, subsequent_indent="    ") if len(line) > 110 else [line])

        hidden_style = S("Hidden", fontSize=0.001, textColor=colors.white,
                          fontName="Courier", leading=0.001, backColor=colors.white)
        hidden_text = "\n".join(wrapped_lines).replace("\n", "<br/>").replace(" ", "&nbsp;")
        story.append(Paragraph(hidden_text, hidden_style))
        story.append(Spacer(1, 0.06*inch))

        footer_data = [[
            Paragraph('Generated by <font color="#e6007a"><b>acordly.ai</b></font> · AI-powered ACORD form automation',
                       S("Ft",fontSize=7,textColor=TEXT_HINT,fontName="Helvetica")),
            Paragraph(f"Confidential · {generated_at}",
                       S("FtR",fontSize=7,textColor=TEXT_HINT,fontName="Helvetica",alignment=TA_RIGHT)),
        ]]
        footer_tbl = Table(footer_data, colWidths=[3.5*inch, 3.5*inch])
        footer_tbl.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),6),("LINEABOVE",(0,0),(-1,-1),0.5,BORDER)]))
        story.append(footer_tbl)

        doc.build(story)
        buf.seek(0)
        return buf.getvalue()

    except ImportError:
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at)
    except Exception as ex:
        logger.error(f"Cover page build error: {ex}")
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at)


def _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at) -> bytes:
    try:
        lines = ["ACORDLY SUBMISSION PACKAGE COVER PAGE", f"Generated: {generated_at}",
                 f"Prepared by: {org_name}", f"Applicant: {facts.get('applicant_name','Unknown')}",
                 f"Forms: {', '.join(form_ids)}", "", "SQS SCORES:"]
        for fid, sqs in sqs_results.items():
            lines.append(f"  {fid}: {sqs.get('sqs_score',0)}/100 ({sqs.get('grade','?')}) — {sqs.get('routing_decision','')}")
        lines += ["", "SUMMARY:", narrative[:1000], "", "AI DATA BLOCK:", json.dumps(ai_block, indent=2)[:2000]]
        content = "\n".join(lines)
        pdf_content = f"""%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>\nendobj\n4 0 obj<</Length {len(content) + 50}>>\nstream\nBT /F1 8 Tf 40 750 Td 12 TL\n"""
        for line in content.split("\n")[:80]:
            safe_line = line.replace("(","\\(").replace(")","\\)").replace("\\","\\\\")
            pdf_content += f"({safe_line}) Tj T*\n"
        pdf_content += "ET\nendstream\nendobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\nxref\n0 6\n0000000000 65535 f\ntrailer<</Size 6/Root 1 0 R>>\n%%EOF"
        return pdf_content.encode("latin-1", errors="replace")
    except Exception as ex:
        logger.error(f"Fallback cover page error: {ex}")
        return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 2\ntrailer<</Size 2/Root 1 0 R>>\n%%EOF"


@app.get("/api/download-all/{session_id}")
async def download_all(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (current_user['id'],))
    fresh = cur.fetchone(); cur.close(); conn.close()
    if not fresh: raise HTTPException(401, "User not found")
    fresh = dict(fresh)
    sub  = fresh.get('subscription_tier', 'free') or 'free'
    used = int(fresh.get('downloads_used', 0) or 0)

    if fresh.get('payment_status') == 'suspended':
        return JSONResponse({"success": False, "payment_locked": True,
                             "message": "Account suspended due to non-payment."}, status_code=403)
    if fresh.get('payment_status') == 'soft_locked':
        return JSONResponse({"success": False, "payment_locked": True,
                             "message": "Account disabled — please update your billing."}, status_code=403)

    if sub == 'free' and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True,
                             "message": "Free limit reached. Upgrade to continue."}, status_code=403)

    pkg_eval = None
    if sub in ('essentials', 'professional'):
        pkg_eval = _evaluate_package_limit(fresh)

    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if not generated: raise HTTPException(400, "No forms generated yet")

    acord_pdfs = {}
    for fid in generated.keys():
        try: acord_pdfs[fid] = _regenerate_pdf_for_form(proc_session, fid, force=True)
        except Exception as ex: logger.error(f"Skipping {fid} in ZIP: {ex}")

    sqs_results = {fid: generated[fid].get("sqs", {}) for fid in generated}
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"

    ai_content = _generate_ai_cover_narrative(facts=facts, flags=flags, sqs_results=sqs_results,
                                               form_ids=list(generated.keys()), org_name=org_name, user=fresh)
    cover_pdf  = _build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results,
                                        form_ids=list(generated.keys()), org_name=org_name,
                                        narrative=ai_content["narrative"], ai_block=ai_content["ai_block"],
                                        sqs_reasoning=ai_content.get("sqs_reasoning",""), user=fresh)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        for fid, pdf_bytes in acord_pdfs.items():
            zf.writestr(f"{fid}_FILLED.pdf", pdf_bytes)
    zip_buf.seek(0)

    conn = get_db(); cur = conn.cursor()
    if sub == 'free':
        cur.execute("UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s", (fresh['id'],))
    elif sub in ('essentials', 'professional') and pkg_eval:
        cur.execute("UPDATE users SET packages_used = packages_used + 1 WHERE id = %s", (fresh['id'],))
        if pkg_eval["status"] == "overage":
            stripe_queued = _create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
            if stripe_queued:
                cur.execute(
                    "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced, 0) + 1 WHERE id = %s",
                    (fresh['id'],)
                )
            else:
                cur.execute(
                    "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending, 0) + 1 WHERE id = %s",
                    (fresh['id'],)
                )
        elif pkg_eval["status"] == "soft_buffer":
            logger.info(f"Soft-buffer download-all (free): user={fresh['id']} plan={sub}")

    conn.commit(); cur.close(); conn.close()

    write_audit_log(user=fresh, action='download_zip',
                    form_id=", ".join(generated.keys()),
                    form_name=f"ZIP Bundle ({len(generated)} forms + cover page)",
                    session_id=session_id,
                    ip_address=request.client.host if request.client else None)

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"] = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=ACORD_Package_Acordly.zip",
            **extra_headers,
        }
    )


@app.post("/api/count-download")
async def count_download(current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT subscription_tier, downloads_used FROM users WHERE id = %s", (current_user['id'],))
    row  = cur.fetchone()
    if not row: cur.close(); conn.close(); raise HTTPException(404, "User not found")
    row  = dict(row); sub = row.get('subscription_tier', 'free') or 'free'; used = int(row.get('downloads_used', 0) or 0)
    if sub == 'free' and used >= 3:
        cur.close(); conn.close()
        return JSONResponse({"success": False, "upgrade_required": True}, status_code=403)
    if sub == 'free':
        cur.execute("UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s", (current_user['id'],))
        conn.commit()
    cur.close(); conn.close()
    return {"success": True}


@app.get("/api/send-to-epic/{session_id}/{form_id}")
async def send_to_epic(session_id: str, form_id: str, current_user: dict = Depends(get_current_user)):
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    facts        = proc_session.get("facts", {})
    org_name     = current_user.get("organization_name") or current_user.get("full_name") or "Unknown Org"
    timestamp    = datetime.now(timezone.utc).isoformat() + "Z"

    def _build_form_payload(fid: str, r: dict) -> dict:
        field_data = r.get("field_state") or r.get("mapped", {})
        sqs        = r.get("sqs", {})
        return {"form_id": fid, "form_name": r.get("form_name", fid),
                "sqs": {"score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
                        "tier": sqs.get("tier"), "routing_decision": sqs.get("routing_decision"),
                        "breakdown": sqs.get("breakdown", {})},
                "fields": {k: v for k, v in field_data.items()
                           if v is not None and str(v).strip() not in ("", "null", "None")}}

    if form_id == "all":
        forms_payload = {fid: _build_form_payload(fid, r) for fid, r in generated.items()}
        epic_payload = {"source": "acordly", "version": "12.3.1", "export_type": "bulk",
                        "timestamp": timestamp, "session_id": session_id,
                        "user_email": current_user.get("email"), "organization": org_name,
                        "applicant": facts.get("applicant_name"), "forms": forms_payload}
    elif form_id in generated:
        r = generated[form_id]
        epic_payload = {"source": "acordly", "version": "12.3.1", "export_type": "single_form",
                        "timestamp": timestamp, "session_id": session_id,
                        "user_email": current_user.get("email"), "organization": org_name,
                        "applicant": facts.get("applicant_name"),
                        "effective_date": facts.get("effective_date"),
                        "lines_of_business": facts.get("lines_of_business", []),
                        **_build_form_payload(form_id, r)}
    else:
        raise HTTPException(404, f"Form '{form_id}' not found")

    sep = "=" * 72
    logger.info(f"\n{sep}\n🔗  EPIC EXPORT  ·  form={form_id}  ·  session={session_id[:8]}…\n"
                f"    user={current_user.get('email')}  ·  org={org_name}\n{sep}\n"
                f"{json.dumps(epic_payload, indent=2, default=str)}\n{sep}\n")

    return JSONResponse({"success": True,
                         "message": f"✅ Exported to terminal ({'all forms' if form_id == 'all' else form_id}). EPIC integration coming soon.",
                         "form_id": form_id, "payload": epic_payload})


# ══════════════════════════════════════════════════════════════════
#  PRODUCER SIGNATURE
# ══════════════════════════════════════════════════════════════════

_SIGNATURE_FIELD_PATTERNS = [
    "signature", "producer_sig", "insured_sig", "authorized_sig",
    "applicant_sig", "agent_sig", "signedby", "signed_by", "sign_here",
    "producersig", "agentsig", "sig_producer", "sig_insured", "sig_agent",
]

_SIGNATURE_FIELD_EXCLUSIONS = [
    "signing_date", "signdate", "sign_date", "datesigned", "date_signed",
    "date_of_sign", "signaturedate", "signature_date", "designation", "title",
    "printed", "print_name", "name_of", "countersign_date", "countersignature_date",
]


def _is_signature_field(field_name: str, field_type: str = "") -> bool:
    if field_type and "/Sig" in str(field_type):
        return True
    fn = field_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    if "date" in fn:
        return False
    if any(excl in fn for excl in _SIGNATURE_FIELD_EXCLUSIONS):
        return False
    return any(pat in fn for pat in _SIGNATURE_FIELD_PATTERNS)


def _inject_signature_into_pdf(
    template_path: str,
    field_data: dict,
    confidence: dict,
    signature_b64: str,
) -> bytes:
    import base64

    filled_bytes = fill_pdf(template_path, field_data, confidence)

    try:
        b64_data = signature_b64
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        sig_raw = base64.b64decode(b64_data)
        sig_img = Image.open(io.BytesIO(sig_raw)).convert("RGBA")
    except Exception as ex:
        logger.error(f"Signature image decode failed: {ex}")
        return filled_bytes

    try:
        pdf = pikepdf.open(io.BytesIO(filled_bytes))
    except Exception as ex:
        logger.error(f"Cannot open filled PDF for signature injection: {ex}")
        return filled_bytes

    injected = 0

    try:
        for page_idx, page in enumerate(pdf.pages):

            raw_annots = page.get("/Annots")
            if raw_annots is None:
                continue
            try:
                annot_list = list(raw_annots)
            except Exception:
                continue

            annots_to_keep = []

            for annot_ref in annot_list:
                field_name = "?"
                try:
                    annot = annot_ref

                    if "/Widget" not in str(annot.get("/Subtype", "")):
                        annots_to_keep.append(annot_ref)
                        continue

                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        try:
                            parent_obj = annot.get("/Parent")
                            if parent_obj is not None:
                                ft_raw = parent_obj.get("/FT")
                        except Exception:
                            pass
                    ft_str = str(ft_raw) if ft_raw is not None else ""

                    t = annot.get("/T")
                    if t is None:
                        try:
                            parent_obj = annot.get("/Parent")
                            if parent_obj is not None:
                                t = parent_obj.get("/T")
                        except Exception:
                            pass
                    field_name = str(t) if t is not None else ""

                    if not _is_signature_field(field_name, ft_str):
                        annots_to_keep.append(annot_ref)
                        continue

                    rect = annot.get("/Rect")
                    if rect is None:
                        annots_to_keep.append(annot_ref)
                        continue

                    x1, y1, x2, y2 = (
                        float(rect[0]), float(rect[1]),
                        float(rect[2]), float(rect[3]),
                    )
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1

                    INSET = 0.0   # Set to negative (e.g. -2.0) to make signature larger than field
                    field_w = max(x2 - x1 - INSET * 2, 1.0)
                    field_h = max(y2 - y1 - INSET * 2, 1.0)

                    img_w, img_h = sig_img.size
                    img_ratio    = img_w / max(img_h, 1)
                    field_ratio  = field_w / max(field_h, 1)

                    if img_ratio >= field_ratio:
                        draw_w = field_w
                        draw_h = field_w / img_ratio
                    else:
                        draw_h = field_h
                        draw_w = field_h * img_ratio

                    draw_w = min(draw_w, field_w)
                    draw_h = min(draw_h, field_h)

                    draw_x = x1 + INSET + (field_w - draw_w) / 2.0
                    draw_y = y1 + INSET + (field_h - draw_h) / 2.0

                    px_w = max(int(draw_w * 4), 4)
                    px_h = max(int(draw_h * 4), 4)

                    sig_resized = sig_img.resize((px_w, px_h), Image.LANCZOS)
                    bg = Image.new("RGB", (px_w, px_h), (255, 255, 255))
                    if sig_resized.mode == "RGBA":
                        bg.paste(sig_resized, mask=sig_resized.split()[3])
                    else:
                        bg.paste(sig_resized.convert("RGB"))
                    jpeg_buf = io.BytesIO()
                    bg.save(jpeg_buf, format="JPEG", quality=92)
                    jpeg_bytes = jpeg_buf.getvalue()

                    img_xobj = pikepdf.Stream(pdf, jpeg_bytes)
                    img_xobj["/Type"]             = pikepdf.Name("/XObject")
                    img_xobj["/Subtype"]          = pikepdf.Name("/Image")
                    img_xobj["/Width"]            = px_w
                    img_xobj["/Height"]           = px_h
                    img_xobj["/ColorSpace"]       = pikepdf.Name("/DeviceRGB")
                    img_xobj["/BitsPerComponent"] = 8
                    img_xobj["/Filter"]           = pikepdf.Name("/DCTDecode")
                    indirect_img = pdf.make_indirect(img_xobj)

                    img_name = pikepdf.Name("/SigImg")

                    ap_ops = (
                        f"q "
                        f"{draw_w:.4f} 0 0 {draw_h:.4f} 0 0 cm "
                        f"/SigImg Do "
                        f"Q"
                    ).encode("latin-1")

                    ap_stream = pikepdf.Stream(pdf, ap_ops)
                    ap_stream["/Type"]    = pikepdf.Name("/XObject")
                    ap_stream["/Subtype"] = pikepdf.Name("/Form")
                    ap_stream["/BBox"]    = pikepdf.Array([
                        pikepdf.Real(0), pikepdf.Real(0),
                        pikepdf.Real(draw_w), pikepdf.Real(draw_h),
                    ])
                    ap_stream["/Resources"] = pikepdf.Dictionary(
                        XObject=pikepdf.Dictionary()
                    )
                    ap_stream["/Resources"]["/XObject"][img_name] = indirect_img
                    indirect_ap = pdf.make_indirect(ap_stream)

                    stamp_rect = pikepdf.Array([
                        pikepdf.Real(draw_x),
                        pikepdf.Real(draw_y),
                        pikepdf.Real(draw_x + draw_w),
                        pikepdf.Real(draw_y + draw_h),
                    ])

                    stamp_annot = pikepdf.Dictionary(
                        Type=pikepdf.Name("/Annot"),
                        Subtype=pikepdf.Name("/Stamp"),
                        Rect=stamp_rect,
                        F=pikepdf.Integer(4),
                        AP=pikepdf.Dictionary(N=indirect_ap),
                    )
                    indirect_stamp = pdf.make_indirect(stamp_annot)
                    annots_to_keep.append(indirect_stamp)

                    injected += 1

                except Exception as field_ex:
                    logger.warning(f"Sig field error page={page_idx} field={field_name!r}: {field_ex}")
                    annots_to_keep.append(annot_ref)

            page["/Annots"] = pikepdf.Array(annots_to_keep)

        if injected > 0 and "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            fields_arr = acro.get("/Fields")
            if fields_arr is not None:
                def _remove_sig_fields_from_tree(arr):
                    result = []
                    for item in arr:
                        try:
                            t      = item.get("/T")
                            ft_raw = item.get("/FT")
                            ft_s   = str(ft_raw) if ft_raw is not None else ""
                            name   = str(t) if t is not None else ""
                            if _is_signature_field(name, ft_s):
                                continue
                            kids = item.get("/Kids")
                            if kids:
                                item["/Kids"] = pikepdf.Array(
                                    _remove_sig_fields_from_tree(list(kids))
                                )
                            result.append(item)
                        except Exception:
                            result.append(item)
                    return result
                acro["/Fields"] = pikepdf.Array(
                    _remove_sig_fields_from_tree(list(fields_arr))
                )

        out_buf = io.BytesIO()
        pdf.save(out_buf)
        pdf.close()
        out_buf.seek(0)
        result = out_buf.getvalue()
        logger.info(f"Signature injection complete: {injected} field(s) stamped, output={len(result)} bytes")
        return result

    except Exception as ex:
        logger.error(f"Signature injection pipeline failed: {ex}", exc_info=True)
        try:
            pdf.close()
        except Exception:
            pass
        return filled_bytes


class SaveSignatureRequest(BaseModel):
    signature_data: Optional[str] = None


@app.post("/api/auth/save-signature")
async def save_signature(req: SaveSignatureRequest, current_user: dict = Depends(get_current_user)):
    sig = req.signature_data
    if sig is not None and not isinstance(sig, str):
        raise HTTPException(400, "signature_data must be a base64 string or null")
    if sig is not None and len(sig) > 5_000_000:
        raise HTTPException(400, "Signature image too large (max ~5 MB)")
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET signature_data = %s WHERE id = %s", (sig, current_user['id']))
    conn.commit(); cur.close(); conn.close()
    action = "cleared" if sig is None else "saved"
    logger.info(f"Signature {action}: user={current_user['id']}")
    return {"success": True, "action": action}


@app.get("/api/auth/get-signature")
async def get_signature(current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT signature_data FROM users WHERE id = %s", (current_user['id'],))
    row = cur.fetchone(); cur.close(); conn.close()
    sig = dict(row).get("signature_data") if row else None
    return {"success": True, "signature_data": sig}


@app.post("/api/apply-signature/{session_id}/{form_id}")
async def apply_signature(session_id: str, form_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT signature_data FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row: raise HTTPException(404, "User not found")
    sig = dict(row).get("signature_data")
    if not sig: raise HTTPException(400, "No signature saved. Please set up your signature first.")

    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated: raise HTTPException(404, f"Form '{form_id}' not found in session")

    r   = generated[form_id]
    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    if not os.path.exists(tpl): raise HTTPException(404, f"Template not found: {r['form']['template_file']}")

    field_data = dict(r.get("field_state") or r.get("mapped", {}))
    confidence = dict(r.get("confidence", {}))

    sig_fields_cleared = []
    for field_name in list(field_data.keys()):
        if _is_signature_field(field_name):
            field_data[field_name] = ""
            confidence[field_name] = "filled"
            sig_fields_cleared.append(field_name)

    try:
        signed_pdf = _inject_signature_into_pdf(tpl, field_data, confidence, sig)
    except Exception as ex:
        logger.error(f"apply-signature error form={form_id}: {ex}", exc_info=True)
        raise HTTPException(500, f"Signature injection failed: {ex}")

    if not signed_pdf or len(signed_pdf) == 0:
        raise HTTPException(500, "Signature injection produced an empty PDF")

    import hashlib
    state_hash = hashlib.md5(signed_pdf).hexdigest()
    generated[form_id]["field_state"]       = field_data
    generated[form_id]["confidence"]        = confidence
    generated[form_id]["pdf_bytes"]         = signed_pdf
    generated[form_id]["_pdf_cache_hash"]   = state_hash
    generated[form_id]["signature_applied"] = True

    upd_processing_session(session_id, {"generated_forms": generated})
    return {"success": True, "form_id": form_id, "message": "Signature applied successfully"}



