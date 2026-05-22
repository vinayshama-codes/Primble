import logging
import uuid
from datetime import datetime, timezone

from config.database import get_pool

logger = logging.getLogger(__name__)


# ASYNC-SAFE
async def write_audit_log(
    user: dict,
    action: str,
    form_id: str = None,
    form_name: str = None,
    session_id: str = None,
    ip_address: str = None,
) -> None:
    try:
        user_email = user.get("email")
        # user_email is NOT NULL in DB; look it up when called from webhook with id only
        if not user_email and user.get("id"):
            try:
                async with get_pool().acquire() as conn2:
                    row2 = await conn2.fetchrow(
                        "SELECT email FROM users WHERE id = $1", str(user["id"])
                    )
                    if row2:
                        user_email = row2.get("email") or ""
            except Exception:
                pass
        user_email = user_email or ""

        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO acord_audit_log
                   (id, user_id, user_email, organization_name, action, form_id, form_name,
                    session_id, ip_address, acord_license_confirmed, timestamp)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                str(uuid.uuid4()),
                user.get("id"),
                user_email,
                user.get("organization_name", ""),
                action,
                form_id,
                form_name,
                session_id,
                ip_address,
                int(user.get("acord_license_confirmed", 0) or 0),
                datetime.now(timezone.utc).isoformat(),
            )
    except Exception as ex:
        logger.error(f"audit_log write failed: {ex}")
