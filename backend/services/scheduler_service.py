import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone

import stripe
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.database import get_pool
from config.settings import DATABASE_URL
from services.email_service import _send_payment_failed_email
from utils.helpers import _safe_parse_dt

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Kept alive for the process lifetime — advisory lock is session-scoped.
_lock_conn        = None
_ADVISORY_LOCK_ID = 7654321098


# ASYNC-SAFE
async def run_daily_payment_lifecycle():
    try:
        now = datetime.now(timezone.utc)
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, email, full_name, payment_failed_at, payment_status, stripe_customer_id, "
                "COALESCE(payment_email_sent_day, 0) AS payment_email_sent_day "
                "FROM users WHERE payment_failed_at IS NOT NULL"
            )
        rows = [dict(r) for r in rows]

        for row in rows:
            try:
                failed_at = _safe_parse_dt(row["payment_failed_at"])
                if failed_at is None:
                    continue
                days_since         = (now - failed_at).days
                current_status     = row.get("payment_status", "failed") or "failed"
                new_status         = current_status
                email_day          = None
                email_already_sent = int(row.get("payment_email_sent_day") or 0)

                if days_since in (2, 4, 6) and current_status == "failed":
                    customer_id = row.get("stripe_customer_id")
                    if customer_id:
                        try:
                            invoices = stripe.Invoice.list(customer=customer_id, status="open", limit=5)
                            for invoice in invoices.auto_paging_iter():
                                invoice_id = getattr(invoice, "id", None)
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
                    if email_already_sent < 60:
                        email_day = 60
                elif days_since >= 21 and current_status not in ("suspended", "archived"):
                    new_status = "suspended"
                    if email_already_sent < 21:
                        email_day = 21
                elif days_since >= 10 and current_status not in ("soft_locked", "suspended", "archived"):
                    new_status = "soft_locked"
                    if email_already_sent < 10:
                        email_day = 10
                elif 7 <= days_since < 10 and current_status == "failed":
                    if email_already_sent < 7:
                        email_day = 7

                if new_status != current_status:
                    async with get_pool().acquire() as conn:
                        await conn.execute(
                            "UPDATE users SET payment_status=$1 WHERE id=$2",
                            new_status, row["id"],
                        )
                    logger.info(f"Lifecycle: user={row['id']} {current_status} → {new_status} (day {days_since})")

                if email_day:
                    sent_ok = _send_payment_failed_email(row["email"], row.get("full_name", ""), day=email_day)
                    if sent_ok:
                        async with get_pool().acquire() as conn:
                            await conn.execute(
                                "UPDATE users SET payment_email_sent_day=$1 WHERE id=$2",
                                email_day, row["id"],
                            )
                    else:
                        logger.error(f"Lifecycle: day-{email_day} email send returned False for user={row['id']} — will retry tomorrow")

            except Exception as ex:
                logger.error(f"Lifecycle error user={row['id']}: {ex}")
    except Exception as ex:
        logger.error(f"Lifecycle cron failed: {ex}")


# ASYNC-SAFE
async def run_arq_auto_reminders():
    """Send automatic reminders for ARQ sessions pending > 3 days with no submission."""
    try:
        from services.arq_service import send_arq_reminder

        now    = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=3)).isoformat()

        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.id, a.user_id
                   FROM arq_sessions a
                   WHERE a.status = 'pending'
                     AND a.created_at <= $1
                     AND a.expires_at > $2
                     AND COALESCE(a.reminder_count, 0) < 1""",
                cutoff, now.isoformat(),
            )
        rows = [dict(r) for r in rows]

        for row in rows:
            try:
                async with get_pool().acquire() as conn:
                    user_row = await conn.fetchrow(
                        "SELECT email, full_name FROM users WHERE id=$1", row["user_id"]
                    )
                if user_row:
                    user = dict(user_row)
                    user["id"] = row["user_id"]
                    ok = await send_arq_reminder(row["id"], user)
                    logger.info(f"ARQ auto-reminder: arq_id={row['id']} ok={ok}")
            except Exception as ex:
                logger.error(f"ARQ auto-reminder error arq_id={row['id']}: {ex}")
    except Exception as ex:
        logger.error(f"ARQ auto-reminder cron failed: {ex}")


# ASYNC-SAFE
async def run_retention_cleanup():
    """
    Nightly data-retention sweep (runs at 03:00 UTC).
    Deletes stale jobs, ARQ sessions, processing sessions, and pending signups.
    """
    import os as _os

    jobs_days    = int(_os.getenv("JOBS_RETENTION_DAYS",    "30"))
    arq_days     = int(_os.getenv("ARQ_RETENTION_DAYS",     "90"))
    session_days = int(_os.getenv("SESSION_RETENTION_DAYS", "180"))

    now            = datetime.now(timezone.utc)
    jobs_cutoff    = (now - timedelta(days=jobs_days)).isoformat()
    arq_cutoff     = (now - timedelta(days=arq_days)).isoformat()
    session_cutoff = (now - timedelta(days=session_days)).isoformat()
    signup_cutoff  = (now - timedelta(hours=48)).isoformat()

    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                r1 = await conn.execute(
                    "DELETE FROM jobs WHERE status IN ('completed','failed') AND updated_at < $1",
                    jobs_cutoff,
                )
                r2 = await conn.execute(
                    "DELETE FROM arq_sessions WHERE expires_at < $1 AND created_at < $2",
                    now.isoformat(), arq_cutoff,
                )
                r3 = await conn.execute(
                    "DELETE FROM processing_sessions WHERE updated_at < $1",
                    session_cutoff,
                )
                r4 = await conn.execute(
                    "DELETE FROM pending_signups WHERE created_at < $1",
                    signup_cutoff,
                )

        def _row_count(status: str) -> int:
            try:
                return int(status.split()[-1])
            except Exception:
                return 0

        logger.info(
            "Retention cleanup: deleted jobs=%d arq=%d sessions=%d pending_signups=%d",
            _row_count(r1), _row_count(r2), _row_count(r3), _row_count(r4),
        )
    except Exception as ex:
        logger.error("Retention cleanup failed: %s", ex)


# ASYNC-SAFE
async def run_audit_log_retention():
    """
    SOC 2 Availability — nightly audit log retention sweep (runs at 03:30 UTC).

    Minimum retention per table: 1 year (365 days). Configurable upward via env vars.
    - acord_audit_log:         SOC 2 audit trail for all form activity
    - field_source_audit:      field-level change provenance
    - sqs_recommendation_audit: recommendation and SQS scoring history

    processing_sessions.facts retention is handled by run_facts_retention() at 04:00 UTC.
    """
    import os as _os

    audit_days = int(_os.getenv("AUDIT_LOG_RETENTION_DAYS", "365"))
    cutoff     = (datetime.now(timezone.utc) - timedelta(days=audit_days)).isoformat()

    def _row_count(status: str) -> int:
        try:
            return int(status.split()[-1])
        except Exception:
            return 0

    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                r_audit = await conn.execute(
                    "DELETE FROM acord_audit_log WHERE timestamp < $1",
                    cutoff,
                )
                r_field = await conn.execute(
                    "DELETE FROM field_source_audit WHERE changed_at < $1",
                    cutoff,
                )
                r_sqs = await conn.execute(
                    "DELETE FROM sqs_recommendation_audit WHERE presented_at < $1",
                    cutoff,
                )

        n_audit = _row_count(r_audit)
        n_field = _row_count(r_field)
        n_sqs   = _row_count(r_sqs)
        ts      = datetime.now(timezone.utc).isoformat()

        logger.info(
            "Audit log retention: cutoff=%s deleted acord_audit_log=%d "
            "field_source_audit=%d sqs_recommendation_audit=%d at=%s",
            cutoff, n_audit, n_field, n_sqs, ts,
        )
    except Exception as ex:
        logger.error("Audit log retention cleanup failed: %s", ex)


# ASYNC-SAFE
async def run_facts_retention():
    """
    SOC 2 Privacy / GDPR Art. 5(1)(e) — nightly facts data-minimization sweep (04:00 UTC).

    Nulls out processing_sessions.facts for sessions older than the tier threshold.
    The session row is preserved; only the facts JSONB column is replaced with a
    tombstone so downstream audit queries remain valid.

    Retention windows:
      free        →  30 days
      essentials  → 180 days
      professional / enterprise → indefinite (skipped)
    """
    import json as _json

    now = datetime.now(timezone.utc)
    ts  = now.isoformat()

    TIERS = {
        "free":       30,
        "essentials": 180,
    }

    def _tombstone(tier: str) -> str:
        return _json.dumps({
            "purged":    True,
            "purged_at": ts,
            "reason":    "retention_policy",
            "tier":      tier,
        })

    def _row_count(status: str) -> int:
        try:
            return int(status.split()[-1])
        except Exception:
            return 0

    totals: dict[str, int] = {}

    try:
        for tier, days in TIERS.items():
            cutoff = (now - timedelta(days=days)).isoformat()
            tombstone = _tombstone(tier)
            try:
                async with get_pool().acquire() as conn:
                    result = await conn.execute(
                        """
                        UPDATE processing_sessions ps
                        SET    facts = $1::jsonb
                        FROM   users u
                        WHERE  ps.user_id     = u.id
                          AND  u.subscription_tier = $2
                          AND  ps.updated_at  < $3
                          AND  (ps.facts IS NULL OR ps.facts->>'purged' IS DISTINCT FROM 'true')
                        """,
                        tombstone, tier, cutoff,
                    )
                totals[tier] = _row_count(result)
            except Exception as ex:
                logger.error("Facts retention failed for tier=%s: %s", tier, ex)
                totals[tier] = -1

        logger.info(
            "Facts retention: purged free=%d essentials=%d at=%s",
            totals.get("free", 0), totals.get("essentials", 0), ts,
        )
    except Exception as ex:
        logger.error("Facts retention cron failed: %s", ex)


def start_scheduler():
    global _lock_conn
    try:
        # Raw psycopg2 connection for the advisory lock — intentionally non-pooled.
        # The lock must live for the entire process lifetime; asyncpg pool connections
        # are recycled and would release the lock on checkout/checkin.
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
        logger.error(
            f"Scheduler: advisory lock check failed ({ex}) — "
            "scheduler will NOT start. Fix the database connection and restart."
        )
        return

    scheduler.add_job(run_daily_payment_lifecycle, "cron", hour=9,  minute=0)
    scheduler.add_job(run_arq_auto_reminders,      "cron", hour=10, minute=0)
    scheduler.add_job(run_retention_cleanup,        "cron", hour=3,  minute=0)
    scheduler.add_job(run_audit_log_retention,      "cron", hour=3,  minute=30)
    scheduler.add_job(run_facts_retention,          "cron", hour=4,  minute=0)
    scheduler.start()
    logger.info(
        "Schedulers started: payment lifecycle + ARQ auto-reminders + "
        "retention cleanup + audit log retention + facts retention"
    )


def stop_scheduler():
    global _lock_conn
    try:
        scheduler.shutdown()
    except Exception:
        pass
    if _lock_conn:
        try:
            _lock_conn.close()
        except Exception:
            pass
        _lock_conn = None
