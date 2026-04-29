"""
migrate.py
Run once to apply incremental schema migrations.
Safe to re-run — uses IF NOT EXISTS / exception catch per statement.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def run_migration():
    if not DATABASE_URL:
        print("❌ DATABASE_URL env var not set")
        return False

    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    migrations = [
        # arq_sessions columns
        ("ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS client_name TEXT DEFAULT ''",
         "arq_sessions.client_name"),
        ("ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS reminder_sent INTEGER DEFAULT 0",
         "arq_sessions.reminder_sent"),
        ("ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS reminder_count INTEGER DEFAULT 0",
         "arq_sessions.reminder_count"),
        ("ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS last_reminder_at TEXT",
         "arq_sessions.last_reminder_at"),
        # arq_notifications
        ("""
            CREATE TABLE IF NOT EXISTS arq_notifications (
                id          TEXT PRIMARY KEY,
                arq_id      TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                type        TEXT NOT NULL,
                read_status INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """, "table arq_notifications"),
        # ------------------------------------------------------------------ #
        # jobs table — async job tracking (Step 5)
        # ------------------------------------------------------------------ #
        ("""
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
        """, "table jobs"),
        ("CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id)",
         "idx_jobs_session_id"),
        ("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)",
         "idx_jobs_user_id"),
        # processing_sessions — user_id index for fast per-user session lookups
        ("CREATE INDEX IF NOT EXISTS idx_processing_sessions_user_id ON processing_sessions(user_id)",
         "idx_processing_sessions_user_id"),
        # s3_pdf_key column — stores S3 object key instead of keeping PDF bytes in BYTEA
        ("ALTER TABLE processing_sessions ADD COLUMN IF NOT EXISTS s3_pdf_key TEXT",
         "processing_sessions.s3_pdf_key"),
        # stripe_events — idempotency table to deduplicate webhook deliveries
        ("""
            CREATE TABLE IF NOT EXISTS stripe_events (
                event_id    TEXT PRIMARY KEY,
                event_type  TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )
        """, "table stripe_events"),
    ]

    for sql, label in migrations:
        try:
            cur.execute(sql)
            conn.commit()
            print(f"  ✅ {label}")
        except Exception as e:
            conn.rollback()
            # Column may already exist with older Postgres — not an error
            print(f"  ⚠️  {label} — skipped ({e})")

    cur.close()
    conn.close()
    print("\n✅ Migration completed successfully!")
    return True


if __name__ == "__main__":
    run_migration()