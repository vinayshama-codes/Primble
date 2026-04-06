import logging
import uuid
from datetime import datetime, timezone
from config.database import get_db

logger = logging.getLogger(__name__)


def write_audit_log(
    user: dict,
    action: str,
    form_id: str = None,
    form_name: str = None,
    session_id: str = None,
    ip_address: str = None,
):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """INSERT INTO acord_audit_log
               (id, user_id, user_email, organization_name, action, form_id, form_name,
                session_id, ip_address, acord_license_confirmed, timestamp)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                str(uuid.uuid4()),
                user.get("id"),
                user.get("email"),
                user.get("organization_name", ""),
                action,
                form_id,
                form_name,
                session_id,
                ip_address,
                int(user.get("acord_license_confirmed", 0) or 0),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as ex:
        logger.error(f"audit_log write failed: {ex}")