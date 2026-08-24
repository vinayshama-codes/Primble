import contextlib
import json
import logging
import os
import re
import time

import asyncpg
import psycopg2
from psycopg2 import pool as pg_pool

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_SAFE_IDENT = re.compile(r'^[a-z_][a-z0-9_]*$')
_SAFE_DEF = re.compile(r'^[A-Z ]+(\(\d+\))?( DEFAULT [a-zA-Z0-9\']+)?( NOT NULL)?$')

_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
# Allow up to this many connections during bursts; surplus idle ones are
# recycled after DB_POOL_MAX_INACTIVE_LIFETIME seconds (default 300 s).
_POOL_MAX_INACTIVE_LIFETIME = float(os.getenv("DB_POOL_MAX_INACTIVE_LIFETIME", "300"))

_pool: asyncpg.Pool = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so Python dicts are auto-serialized."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# ASYNC-SAFE
async def create_pool() -> None:
    global _pool
    _env = os.getenv("ENVIRONMENT", "development").lower()
    _ssl = "require" if _env == "production" else None
    # statement_cache_size=0 is required when connecting through PgBouncer in
    # transaction mode (Supabase pooled URL, port 6543). PgBouncer does not
    # support prepared statements across connections; asyncpg's cache causes
    # "prepared statement already exists" errors without this setting.
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=_POOL_MIN,
        max_size=_POOL_MAX,
        command_timeout=120,
        # Recycle idle connections after this many seconds so stale TCP sockets
        # (reset by OS after long GPT/PDF runs) are never handed to callers.
        max_inactive_connection_lifetime=min(_POOL_MAX_INACTIVE_LIFETIME, 120),
        ssl=_ssl,
        init=_init_conn,
        statement_cache_size=0,
    )
    # Fast-fail startup if the DB is unreachable rather than serving requests that
    # will all fail at the query layer.
    async with _pool.acquire() as _conn:
        await _conn.execute("SELECT 1")
    logger.info(f"asyncpg pool created and verified (min={_POOL_MIN}, max={_POOL_MAX}, ssl={_ssl})")


# ASYNC-SAFE
async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call create_pool() in startup.")
    return _pool


# ASYNC-SAFE
async def init_db() -> None:
    """Create all tables and run idempotent column migrations."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                            TEXT PRIMARY KEY,
                email                         TEXT UNIQUE NOT NULL,
                password_hash                 TEXT,
                full_name                     TEXT,
                phone                         TEXT,
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
                acord_license_version         TEXT,
                created_at                    TEXT,
                last_login                    TEXT
            )
        """)

        for col, definition in [
            ("organization_name",            "TEXT"),
            # Producer contact phone — shown to the client on the questionnaire's
            # "Contact Your Agent" card. Optional; blank simply hides the line.
            ("phone",                        "TEXT"),
            ("acord_disclaimer_accepted",    "INTEGER DEFAULT 0"),
            ("acord_disclaimer_accepted_at", "TEXT"),
            ("acord_license_confirmed",      "INTEGER DEFAULT 0"),
            ("acord_license_confirmed_at",   "TEXT"),
            ("acord_license_version",        "TEXT"),
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
            ("payment_email_sent_day",       "INTEGER DEFAULT 0"),
        ]:
            if not (_SAFE_IDENT.match(col) and _SAFE_DEF.match(definition)):
                raise ValueError(f"Unsafe DDL identifier blocked: {col!r} {definition!r}")
            try:
                await conn.execute(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
            except Exception:
                pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_sessions (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                data       JSONB NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_pdf_bytes (
                session_id TEXT NOT NULL,
                form_id    TEXT NOT NULL,
                pdf_bytes  BYTEA,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, form_id)
            )
        """)

        await conn.execute("""
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

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                email      TEXT PRIMARY KEY,
                added_by   TEXT,
                created_at TEXT NOT NULL
            )
        """)

        await conn.execute("""
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
                sqs_score_at_download   REAL,
                unresolved_issues       JSONB,
                file_checksum           TEXT,
                actor_email             TEXT,
                license_version         TEXT,
                timestamp               TEXT NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_overage_sessions (
                stripe_session_id TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                qty               INTEGER NOT NULL,
                applied_at        TEXT NOT NULL
            )
        """)

        await conn.execute("""
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
                draft_answers    JSONB DEFAULT '{}',
                not_sure_fields  JSONB DEFAULT '[]',
                review_fields    JSONB DEFAULT '[]',
                expires_at       TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                submitted_at     TEXT,
                viewed_at        TEXT,
                reminder_sent    INTEGER DEFAULT 0,
                reminder_count   INTEGER DEFAULT 0,
                last_reminder_at TEXT
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arq_notifications (
                id          TEXT PRIMARY KEY,
                arq_id      TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                type        TEXT NOT NULL,
                read_status INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)

        for col, definition in [
            ("client_name",           "TEXT DEFAULT ''"),
            ("reminder_sent",         "INTEGER DEFAULT 0"),
            ("reminder_count",        "INTEGER DEFAULT 0"),
            ("last_reminder_at",      "TEXT"),
            ("remediation_status",    "TEXT DEFAULT NULL"),
            ("fields_answered_count", "INTEGER DEFAULT 0"),
            # Server-side draft persistence (cross-browser / incognito safe). This
            # previously existed ONLY in the legacy create_tables.py / migrate.py
            # paths, neither of which runs at startup — so a fresh database never
            # got the column and draft saving silently failed. Added here so the
            # schema stays portable per the documented convention.
            #
            # NOTE: both are declared bare `JSONB` (no DEFAULT). _SAFE_DEF rejects
            # a brace-containing default such as "JSONB DEFAULT '{}'" and raises
            # OUTSIDE the try/except below, which would abort startup. Existing
            # rows therefore back-fill as NULL and every reader coerces NULL to an
            # empty dict/list.
            ("draft_answers",         "JSONB"),
            # Fields the client explicitly answered "I'm not sure" on. Kept OUT of
            # `answers` on purpose so the sentinel can never be stamped into an
            # ACORD field or counted as a real answer by the scorer.
            ("not_sure_fields",       "JSONB"),
            # Figure 18: answers the client DID give that we could not normalize
            # (an unreadable date, a NAICS code of the wrong width). Previously
            # these were silently discarded at submit; they are now stored in
            # `answers` like any other value and listed here so the producer can
            # confirm them. Bare JSONB for the same _SAFE_DEF reason noted above.
            ("review_fields",         "JSONB"),
        ]:
            if not (_SAFE_IDENT.match(col) and _SAFE_DEF.match(definition)):
                raise ValueError(f"Unsafe DDL identifier blocked: {col!r} {definition!r}")
            try:
                await conn.execute(
                    f"ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
            except Exception:
                pass

        # Figure 21: immutable client response receipt. Written ONCE at submit
        # and never updated - `arq_sessions.answers` is a working row that later
        # stages read and that a future edit path could rewrite, so it cannot
        # serve as the record of what the client actually said. This table is the
        # point-in-time record the package audit trail points at.
        #
        # `payload` holds the whole receipt as Fernet ciphertext (TEXT, not JSONB)
        # because it contains the client's own answers - the same PII class as
        # processing_sessions.facts, which is encrypted the same way. The counts
        # beside it are deliberately plaintext so the panel can summarise a
        # receipt without decrypting it.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arq_receipts (
                id             TEXT PRIMARY KEY,
                arq_id         TEXT NOT NULL,
                session_id     TEXT,
                user_id        TEXT NOT NULL,
                client_name    TEXT DEFAULT '',
                client_email   TEXT DEFAULT '',
                payload        TEXT NOT NULL,
                item_count     INTEGER DEFAULT 0,
                answered_count INTEGER DEFAULT 0,
                not_sure_count INTEGER DEFAULT 0,
                review_count   INTEGER DEFAULT 0,
                submitted_at   TEXT NOT NULL,
                created_at     TEXT NOT NULL
            )
        """)

        # Package activity log — durable, user-level event feed. Persists
        # independently of processing_sessions so the log survives session close
        # (session_id is kept only as a grouping key, not a FK).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_events (
                id            TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                session_id    TEXT,
                package_label TEXT DEFAULT '',
                event_type    TEXT NOT NULL,
                event_data    JSONB DEFAULT '{}',
                created_at    TEXT NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_webhook_events (
                event_id     TEXT PRIMARY KEY,
                event_type   TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )
        """)

        for stmt in [
            "ALTER TABLE session_pdf_bytes ADD COLUMN IF NOT EXISTS s3_key TEXT",
            "ALTER TABLE processing_sessions ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_used_at TEXT",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip_address TEXT",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent TEXT",
            # Download audit record (client requirement): score, unresolved issues and
            # file checksum captured at the moment a package is downloaded.
            "ALTER TABLE acord_audit_log ADD COLUMN IF NOT EXISTS sqs_score_at_download REAL",
            "ALTER TABLE acord_audit_log ADD COLUMN IF NOT EXISTS unresolved_issues JSONB",
            "ALTER TABLE acord_audit_log ADD COLUMN IF NOT EXISTS file_checksum TEXT",
            # actor_email: for admin-initiated audit events (e.g. license_reset),
            # records WHICH admin performed the action on the target user's row.
            "ALTER TABLE acord_audit_log ADD COLUMN IF NOT EXISTS actor_email TEXT",
            # license_version: which ACORD license modal wording
            # (ACORD_LICENSE_VERSION in config/settings.py) a user agreed to,
            # so re-confirmation can be forced when the legal text changes.
            # (users.acord_license_version is handled by the users column loop above.)
            "ALTER TABLE acord_audit_log ADD COLUMN IF NOT EXISTS license_version TEXT",
            # V1 plan C1 F10: producer resolution keeps every competing value.
            "ALTER TABLE underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS candidates JSONB",
            "ALTER TABLE underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS reason TEXT",
            # retry_count: incremented each time a job is requeued due to semaphore-full or transient error
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0",
            # priority: lower number = higher priority. 1=urgent (paid/retries), 5=default, 9=background.
            # Workers select in (priority ASC, created_at ASC) order so urgent jobs preempt standard ones.
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 5",
            # Composite index that matches the worker's claim query so list_pending() does an index scan
            # instead of a table scan once the jobs table grows past a few thousand rows.
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_pending_priority ON jobs(priority ASC, created_at ASC) WHERE status = 'pending'",
            # Index for the watchdog's stuck-job sweep — finds 'processing' rows whose updated_at is old.
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_processing_updated ON jobs(updated_at) WHERE status = 'processing'",
        ]:
            try:
                await conn.execute(stmt)
            except Exception:
                pass

        try:
            await conn.execute(
                "ALTER TABLE session_pdf_bytes ALTER COLUMN pdf_bytes DROP NOT NULL"
            )
        except Exception:
            pass

        for idx_stmt in [
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ps_user_updated ON processing_sessions(user_id, updated_at DESC)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_token ON sessions(token)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_activity_user_created ON activity_events(user_id, created_at DESC)",
            # Receipt lookup is always "the receipt for this questionnaire".
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_arq_receipts_arq ON arq_receipts(arq_id)",
        ]:
            try:
                await conn.execute(idx_stmt)
            except Exception:
                pass

        logger.info("PostgreSQL database initialized (asyncpg)")


# ── Sync psycopg2 pool — used by standalone scripts (migrate.py, create_tables.py) ──
_SYNC_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
_SYNC_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 1.0

_sync_pool: pg_pool.ThreadedConnectionPool = None


def _get_sync_pool() -> pg_pool.ThreadedConnectionPool:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = pg_pool.ThreadedConnectionPool(_SYNC_POOL_MIN, _SYNC_POOL_MAX, DATABASE_URL)
    return _sync_pool


@contextlib.contextmanager
def get_db_cursor():
    p = _get_sync_pool()
    conn = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            conn = p.getconn()
            break
        except Exception:
            if attempt == _RETRY_ATTEMPTS:
                raise
            time.sleep(_RETRY_DELAY)
    try:
        cur = conn.cursor()
        try:
            yield conn, cur
        finally:
            cur.close()
    finally:
        p.putconn(conn)
