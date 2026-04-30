import json
import logging
import os

import asyncpg

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

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
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=_POOL_MIN,
        max_size=_POOL_MAX,
        command_timeout=60,
        init=_init_conn,
    )
    logger.info(f"asyncpg pool created (min={_POOL_MIN}, max={_POOL_MAX})")


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
        ]:
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

        logger.info("PostgreSQL database initialized (asyncpg)")
