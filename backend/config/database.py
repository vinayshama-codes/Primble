import logging
import psycopg2
import psycopg2.extras
from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


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
        ("overage_packages_invoiced",    "INTEGER DEFAULT 0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            conn.commit()
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
    logger.info("PostgreSQL database initialized")