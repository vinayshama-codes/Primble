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
    )
    logger.info(f"asyncpg pool created (min={_POOL_MIN}, max={_POOL_MAX}, ssl={_ssl})")


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
            ("client_name",      "TEXT DEFAULT ''"),
            ("reminder_sent",    "INTEGER DEFAULT 0"),
            ("reminder_count",   "INTEGER DEFAULT 0"),
            ("last_reminder_at", "TEXT"),
        ]:
            if not (_SAFE_IDENT.match(col) and _SAFE_DEF.match(definition)):
                raise ValueError(f"Unsafe DDL identifier blocked: {col!r} {definition!r}")
            try:
                await conn.execute(
                    f"ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
            except Exception:
                pass

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
