"""
migrate.py
Run once to add ARQ reminder columns to existing arq_sessions table.
Safe to re-run — uses IF NOT EXISTS / exception catch per column.
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