import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.database import get_db
from services.email_service import _send_payment_failed_email
from utils.helpers import _safe_parse_dt

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def run_daily_payment_lifecycle():
    try:
        now  = datetime.now(timezone.utc)
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT id, email, full_name, payment_failed_at, payment_status FROM users WHERE payment_failed_at IS NOT NULL")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        for row in rows:
            try:
                failed_at = _safe_parse_dt(row["payment_failed_at"])
                if failed_at is None:
                    continue
                days_since     = (now - failed_at).days
                current_status = row.get("payment_status", "failed") or "failed"
                new_status     = current_status
                email_day      = None

                if days_since >= 60 and current_status != "archived":
                    new_status = "archived"
                elif days_since >= 21 and current_status not in ("suspended", "archived"):
                    new_status = "suspended"
                    email_day  = 21
                elif days_since >= 10 and current_status not in ("soft_locked", "suspended", "archived"):
                    new_status = "soft_locked"
                    email_day  = 10
                elif days_since == 7 and current_status == "failed":
                    email_day  = 7

                if new_status != current_status:
                    conn2 = get_db()
                    cur2  = conn2.cursor()
                    cur2.execute("UPDATE users SET payment_status=%s WHERE id=%s", (new_status, row["id"]))
                    conn2.commit()
                    cur2.close()
                    conn2.close()
                    logger.info(f"Lifecycle: user={row['id']} {current_status} → {new_status} (day {days_since})")

                if email_day:
                    _send_payment_failed_email(row["email"], row.get("full_name", ""), day=email_day)

            except Exception as ex:
                logger.error(f"Lifecycle error user={row['id']}: {ex}")
    except Exception as ex:
        logger.error(f"Lifecycle cron failed: {ex}")


def start_scheduler():
    scheduler.add_job(run_daily_payment_lifecycle, "cron", hour=9, minute=0)
    scheduler.start()
    logger.info("Daily payment lifecycle scheduler started")


def stop_scheduler():
    scheduler.shutdown()