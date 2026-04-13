import logging
from datetime import datetime, timedelta, timezone

import stripe
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
        cur.execute("SELECT id, email, full_name, payment_failed_at, payment_status, stripe_customer_id FROM users WHERE payment_failed_at IS NOT NULL")
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

                # Silent retry on days 2, 4, 6 while still in "failed" state
                if days_since in (2, 4, 6) and current_status == "failed":
                    customer_id = row.get("stripe_customer_id")
                    if customer_id:
                        try:
                            invoices = stripe.Invoice.list(customer=customer_id, status="open", limit=5)
                            for invoice in invoices.auto_paging_iter():
                                invoice_id = getattr(invoice, "id", None) or invoice.get("id")
                                if not invoice_id:
                                    continue
                                try:
                                    stripe.Invoice.pay(invoice_id)
                                    logger.info(f"Silent retry day {days_since}: invoice {invoice_id} for {customer_id}")
                                except stripe.error.CardError:
                                    logger.info(f"Silent retry day {days_since}: card declined for {customer_id}")
                                except Exception as e:
                                    logger.warning(f"Silent retry day {days_since}: invoice {invoice_id} failed: {e}")
                        except Exception as e:
                            logger.warning(f"Silent retry day {days_since}: could not list invoices for {customer_id}: {e}")

                if days_since >= 60 and current_status != "archived":
                    new_status = "archived"
                    email_day  = 60
                elif days_since >= 21 and current_status not in ("suspended", "archived"):
                    new_status = "suspended"
                    email_day  = 21
                elif days_since >= 10 and current_status not in ("soft_locked", "suspended", "archived"):
                    new_status = "soft_locked"
                    email_day  = 10
                elif 7 <= days_since < 10 and current_status == "failed":
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


async def run_arq_auto_reminders():
    """Send automatic reminders for ARQ sessions pending > 3 days with no submission."""
    try:
        from services.arq_service import send_arq_reminder, get_arq_by_id

        now         = datetime.now(timezone.utc)
        cutoff      = (now - timedelta(days=3)).isoformat()
        conn        = get_db()
        cur         = conn.cursor()
        # Pending ARQs created more than 3 days ago, not yet submitted, not expired, reminder_count < 1
        cur.execute("""
            SELECT a.id, a.user_id
            FROM arq_sessions a
            WHERE a.status = 'pending'
              AND a.created_at <= %s
              AND a.expires_at > %s
              AND COALESCE(a.reminder_count, 0) < 1
        """, (cutoff, now.isoformat()))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        for row in rows:
            try:
                conn2 = get_db()
                cur2  = conn2.cursor()
                cur2.execute("SELECT email, full_name FROM users WHERE id=%s", (row["user_id"],))
                user_row = cur2.fetchone()
                cur2.close()
                conn2.close()
                if user_row:
                    user = dict(user_row)
                    user["id"] = row["user_id"]
                    ok = send_arq_reminder(row["id"], user)
                    logger.info(f"ARQ auto-reminder: arq_id={row['id']} ok={ok}")
            except Exception as ex:
                logger.error(f"ARQ auto-reminder error arq_id={row['id']}: {ex}")
    except Exception as ex:
        logger.error(f"ARQ auto-reminder cron failed: {ex}")


def start_scheduler():
    scheduler.add_job(run_daily_payment_lifecycle, "cron", hour=9, minute=0)
    scheduler.add_job(run_arq_auto_reminders, "cron", hour=10, minute=0)
    scheduler.start()
    logger.info("Schedulers started: payment lifecycle + ARQ auto-reminders")


def stop_scheduler():
    scheduler.shutdown()