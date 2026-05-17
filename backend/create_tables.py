"""
create_tables.py
Creates ARQ tables (arq_sessions, arq_notifications) if they don't already exist.
Safe to run on a fresh DB or an existing one.
"""
import os
from dotenv import load_dotenv
from config.database import get_db_cursor

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_tables():
    if not DATABASE_URL:
        print("❌ DATABASE_URL env var not set")
        return False

    try:
        print("Connecting to database...")
        with get_db_cursor() as (conn, cur):
            # ── arq_sessions ──
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
            print("  ✅ arq_sessions")

            # ── arq_notifications ──
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
            print("  ✅ arq_notifications")

            # Safe ALTER for existing DBs that already have arq_sessions without newer cols
            extras = [
                "ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS client_name TEXT DEFAULT ''",
                "ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS reminder_sent INTEGER DEFAULT 0",
                "ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS reminder_count INTEGER DEFAULT 0",
                "ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS last_reminder_at TEXT",
                "ALTER TABLE arq_sessions ADD COLUMN IF NOT EXISTS draft_answers JSONB DEFAULT '{}'",
            ]
            for sql in extras:
                try:
                    cur.execute(sql)
                    conn.commit()
                except Exception:
                    conn.rollback()

            conn.commit()
        print("\n✅ All ARQ tables created/verified successfully!")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    create_tables()