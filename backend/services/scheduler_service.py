import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone

import stripe
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.database import get_db
from config.settings import DATABASE_URL
from services.email_service import _send_payment_failed_email
from utils.helpers import _safe_parse_dt

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Kept alive for the process lifetime — advisory lock is session-scoped and
# drops the moment this connection closes.
_lock_conn = None
_ADVISORY_LOCK_ID = 7654321098  # arbitrary stable integer for this application


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


async def run_retention_cleanup():
    """
    Nightly data-retention sweep (runs at 03:00 UTC).

    - Jobs: delete terminal rows older than JOBS_RETENTION_DAYS (default 30).
    - ARQ sessions: delete expired sessions older than ARQ_RETENTION_DAYS (default 90).
    - Processing sessions: delete sessions with no activity for SESSION_RETENTION_DAYS (default 180).
    - pending_signups: delete rows older than 48 hours (verification window expired).
    """
    import os as _os

    jobs_days    = int(_os.getenv("JOBS_RETENTION_DAYS",    "30"))
    arq_days     = int(_os.getenv("ARQ_RETENTION_DAYS",     "90"))
    session_days = int(_os.getenv("SESSION_RETENTION_DAYS", "180"))

    now = datetime.now(timezone.utc)
    jobs_cutoff    = (now - timedelta(days=jobs_days)).isoformat()
    arq_cutoff     = (now - timedelta(days=arq_days)).isoformat()
    session_cutoff = (now - timedelta(days=session_days)).isoformat()
    signup_cutoff  = (now - timedelta(hours=48)).isoformat()

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute(
            "DELETE FROM jobs WHERE status IN ('completed','failed') AND updated_at < %s",
            (jobs_cutoff,),
        )
        deleted_jobs = cur.rowcount

        cur.execute(
            "DELETE FROM arq_sessions WHERE expires_at < %s AND created_at < %s",
            (now.isoformat(), arq_cutoff),
        )
        deleted_arq = cur.rowcount

        cur.execute(
            "DELETE FROM processing_sessions WHERE updated_at < %s",
            (session_cutoff,),
        )
        deleted_sessions = cur.rowcount

        cur.execute(
            "DELETE FROM pending_signups WHERE created_at < %s",
            (signup_cutoff,),
        )
        deleted_signups = cur.rowcount

        conn.commit()
        cur.close()
        conn.close()

        logger.info(
            "Retention cleanup: deleted jobs=%d arq=%d sessions=%d pending_signups=%d",
            deleted_jobs, deleted_arq, deleted_sessions, deleted_signups,
        )
    except Exception as ex:
        logger.error("Retention cleanup failed: %s", ex)


def start_scheduler():
    global _lock_conn
    try:
        # Use a raw (non-pooled) connection so the advisory lock lives for the
        # entire process lifetime without consuming a pool slot.
        _lock_conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = _lock_conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s) AS got_lock", (_ADVISORY_LOCK_ID,))
        row      = cur.fetchone()
        got_lock = bool(row.get("got_lock", False)) if row else False
        cur.close()
        if not got_lock:
            logger.warning(
                "Scheduler: advisory lock already held by another process — "
                "skipping scheduler start (expected in multi-worker deployments)"
            )
            _lock_conn.close()
            _lock_conn = None
            return
        logger.info("Scheduler: acquired advisory lock — this process owns the cron jobs")
    except Exception as ex:
        logger.warning(
            f"Scheduler: advisory lock check failed ({ex}) — "
            "starting scheduler anyway (verify only one worker is running)"
        )

    scheduler.add_job(run_daily_payment_lifecycle, "cron", hour=9, minute=0)
    scheduler.add_job(run_arq_auto_reminders, "cron", hour=10, minute=0)
    scheduler.add_job(run_retention_cleanup, "cron", hour=3, minute=0)
    scheduler.start()
    logger.info("Schedulers started: payment lifecycle + ARQ auto-reminders + retention cleanup")


def stop_scheduler():
    global _lock_conn
    try:
        scheduler.shutdown()
    except Exception:
        pass
    if _lock_conn:
        try:
            _lock_conn.close()   # releases the advisory lock
        except Exception:
            pass
        _lock_conn = None