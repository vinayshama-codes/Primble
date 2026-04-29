import logging
import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

_pool: psycopg2.pool.ThreadedConnectionPool = None


class _PooledConn:
    """
    Proxy around a borrowed psycopg2 connection.
    .close() returns it to the pool (with a rollback to reset state) instead of
    discarding it — so all existing call sites work unchanged.
    """
    def __init__(self, conn, pool):
        self.__dict__["_conn"] = conn
        self.__dict__["_pool"] = pool

    def __getattr__(self, name):
        return getattr(self.__dict__["_conn"], name)

    def cursor(self, *args, **kwargs):
        return self.__dict__["_conn"].cursor(*args, **kwargs)

    def commit(self):
        return self.__dict__["_conn"].commit()

    def rollback(self):
        return self.__dict__["_conn"].rollback()

    def close(self):
        conn = self.__dict__["_conn"]
        pool = self.__dict__["_pool"]
        try:
            if not conn.closed:
                conn.rollback()   # reset uncommitted state before returning
        except Exception:
            pass
        pool.putconn(conn)


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            _POOL_MIN,
            _POOL_MAX,
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        logger.info(f"DB pool created (min={_POOL_MIN}, max={_POOL_MAX})")
    return _pool


def get_db() -> _PooledConn:
    p = _get_pool()
    return _PooledConn(p.getconn(), p)


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

    # ARQ tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS arq_sessions (
            id               TEXT PRIMARY KEY,
            session_id       TEXT NOT NULL,
            user_id          TEXT NOT NULL,
            token            TEXT UNIQUE NOT NULL,
            email            TEXT NOT NULL,
            client_name      TEXT DEFAULT '',
            status           TEXT DEFAULT 'pending',
            questions        JSONB NOT NULL,
            answers          JSONB DEFAULT '{}',
            expires_at       TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            submitted_at     TEXT,
            viewed_at        TEXT,
            reminder_sent    INTEGER DEFAULT 0,
            reminder_count   INTEGER DEFAULT 0,
            last_reminder_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS arq_notifications (
            id          TEXT PRIMARY KEY,
            arq_id      TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            type        TEXT NOT NULL,
            read_status INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)

    # Add missing columns to arq_sessions if upgrading
    for col, definition in [
        ("client_name",      "TEXT DEFAULT ''"),
        ("reminder_sent",    "INTEGER DEFAULT 0"),
        ("reminder_count",   "INTEGER DEFAULT 0"),
        ("last_reminder_at", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE arq_sessions ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            conn.rollback()

    # Webhook idempotency — stores processed Stripe event IDs to prevent
    # duplicate side-effects when Stripe retries on network errors.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_webhook_events (
            event_id     TEXT PRIMARY KEY,
            event_type   TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
    """)

    # S3 migration — add s3_key column so PDF bytes can be stored on S3 instead
    # of (or alongside) PostgreSQL BYTEA.  pdf_bytes made nullable so rows with
    # an s3_key don't need to duplicate the bytes in the DB.
    for _stmt in [
        "ALTER TABLE session_pdf_bytes ADD COLUMN s3_key TEXT",
        "ALTER TABLE session_pdf_bytes ALTER COLUMN pdf_bytes DROP NOT NULL",
    ]:
        try:
            cur.execute(_stmt)
            conn.commit()
        except Exception:
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    logger.info("PostgreSQL database initialized")