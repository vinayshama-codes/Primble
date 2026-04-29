"""Initial production schema.

Revision ID: 0001
Revises:
Create Date: 2026-04-29

Consolidates all tables currently created by database.py:init_db() and migrate.py
into a single versioned source of truth. Safe to run on an empty database or an
existing one (all DDL uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                          TEXT PRIMARY KEY,
            email                       TEXT UNIQUE NOT NULL,
            password_hash               TEXT,
            full_name                   TEXT DEFAULT '',
            organization_name           TEXT DEFAULT '',
            google_id                   TEXT,
            auth_provider               TEXT DEFAULT 'email',
            email_verified              INTEGER DEFAULT 0,
            verification_code           TEXT,
            verification_expires        TEXT,
            subscription_tier           TEXT DEFAULT 'free',
            billing_cycle               TEXT DEFAULT 'monthly',
            stripe_customer_id          TEXT,
            stripe_subscription_id      TEXT,
            packages_used               INTEGER DEFAULT 0,
            packages_limit              INTEGER DEFAULT 0,
            overage_packages_invoiced   INTEGER DEFAULT 0,
            overage_packages_pending    INTEGER DEFAULT 0,
            overage_rate                INTEGER DEFAULT 0,
            downloads_used              INTEGER DEFAULT 0,
            payment_status              TEXT DEFAULT 'ok',
            payment_failed_at           TEXT,
            acord_disclaimer_accepted   INTEGER DEFAULT 0,
            acord_disclaimer_accepted_at TEXT,
            acord_license_confirmed     INTEGER DEFAULT 0,
            acord_license_confirmed_at  TEXT,
            created_at                  TEXT NOT NULL,
            last_login                  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token      TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS processing_sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            data       JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_processing_sessions_user_id ON processing_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_processing_sessions_updated_at ON processing_sessions(updated_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS session_pdf_bytes (
            session_id TEXT NOT NULL,
            form_id    TEXT NOT NULL,
            pdf_bytes  BYTEA,
            s3_key     TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, form_id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pending_signups (
            id                          TEXT PRIMARY KEY,
            email                       TEXT UNIQUE NOT NULL,
            password_hash               TEXT,
            full_name                   TEXT DEFAULT '',
            organization_name           TEXT DEFAULT '',
            verification_code           TEXT,
            verification_expires        TEXT,
            acord_disclaimer_accepted   INTEGER DEFAULT 0,
            acord_disclaimer_accepted_at TEXT,
            created_at                  TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS acord_audit_log (
            id             TEXT PRIMARY KEY,
            user_id        TEXT NOT NULL,
            action         TEXT NOT NULL,
            session_id     TEXT,
            form_id        TEXT,
            rec_id         TEXT,
            field          TEXT,
            component      TEXT,
            message        TEXT,
            override_reason TEXT,
            score_impact   REAL,
            sqs_score_at_action REAL,
            model_version  TEXT,
            timestamp      TEXT NOT NULL,
            ip_address     TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_session_id ON acord_audit_log(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON acord_audit_log(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS applied_overage_sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            session_id TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS arq_sessions (
            id             TEXT PRIMARY KEY,
            session_id     TEXT NOT NULL,
            user_id        TEXT NOT NULL,
            token          TEXT UNIQUE NOT NULL,
            email          TEXT NOT NULL,
            client_name    TEXT DEFAULT '',
            questions      JSONB DEFAULT '[]',
            answers        JSONB DEFAULT '{}',
            status         TEXT DEFAULT 'pending',
            created_at     TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            submitted_at   TEXT,
            viewed_at      TEXT,
            reminder_sent  INTEGER DEFAULT 0,
            reminder_count INTEGER DEFAULT 0,
            last_reminder_at TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_arq_sessions_token ON arq_sessions(token)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_arq_sessions_user_id ON arq_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_arq_sessions_session_id ON arq_sessions(session_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS arq_notifications (
            id          TEXT PRIMARY KEY,
            arq_id      TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            type        TEXT NOT NULL,
            read_status INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_arq_notifications_user_id ON arq_notifications(user_id)")

    # processed_webhook_events — idempotency for Stripe webhooks.
    # Note: older code used 'stripe_events'; this is the correct table name.
    op.execute("""
        CREATE TABLE IF NOT EXISTS processed_webhook_events (
            event_id    TEXT PRIMARY KEY,
            event_type  TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id           TEXT PRIMARY KEY,
            session_id       TEXT REFERENCES processing_sessions(id) ON DELETE SET NULL,
            user_id          TEXT NOT NULL,
            job_type         TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            payload          JSONB,
            result           JSONB,
            error_message    TEXT,
            progress_message TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")


def downgrade() -> None:
    # Ordered by FK dependency (reverse of creation order).
    for table in [
        "jobs", "processed_webhook_events", "arq_notifications", "arq_sessions",
        "applied_overage_sessions", "acord_audit_log", "pending_signups",
        "session_pdf_bytes", "processing_sessions", "sessions", "users",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
