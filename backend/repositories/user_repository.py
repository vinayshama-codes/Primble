import logging
from typing import Optional
from config.database import get_db

logger = logging.getLogger(__name__)


def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def get_fresh_user(user_id: str) -> Optional[dict]:
    return get_user_by_id(user_id)