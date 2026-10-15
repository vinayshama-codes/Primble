import asyncio
import logging
import os
import threading
import psycopg2
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import stripe
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.database import get_pool
from config.settings import DATABASE_URL
from services.email_service import _send_payment_failed_email
from utils.helpers import _safe_parse_dt

logger = logging.getLogger(__name__)


def _scheduler_timezone():
    """The clock the daily jobs read. Pinned, so "10:00" means the same hour on a
    Mac in India and on Render (UTC). Client e-mails go to US insureds, hence US
    Eastern by default. An unknown zone falls back to UTC rather than failing the
    import - this module loads with the API."""
    name = (os.getenv("SCHEDULER_TIMEZONE") or "America/New_York").strip()
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        logger.warning("SCHEDULER_TIMEZONE=%r is not a known time zone - using UTC", name)
        return timezone.utc


scheduler = AsyncIOScheduler(timezone=_scheduler_timezone())

# The ONE runner of the daily jobs across every process that has the scheduler
# on (Render's gunicorn workers, the old and new instance of a deploy). A Postgres
# session-level advisory lock: held while the holding connection lives, freed by
# Postgres the moment that session ends.
_lock_conn        = None
_ADVISORY_LOCK_ID = 7654321098
_lock_guard       = threading.Lock()


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
                    sent_ok = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: _send_payment_failed_email(row["email"], row.get("full_name", ""), day=email_day)
                    )
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

    orphan_cutoff  = (now - timedelta(days=1)).isoformat()

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
                # A package's PDFs (they can carry signatures) and its signing
                # requests go WITH it, as the app's own Delete does
                # (form_routes.delete_session). Deleting the package alone left
                # 146 orphan PDFs by 15 Oct 2026; those whose package is already
                # gone go too, a day after their last write.
                r_pdf = await conn.execute(
                    "DELETE FROM session_pdf_bytes b"
                    " WHERE b.session_id IN (SELECT id FROM processing_sessions WHERE updated_at < $1)"
                    "    OR (NOT EXISTS (SELECT 1 FROM processing_sessions p WHERE p.id = b.session_id)"
                    "        AND b.updated_at < $2)",
                    session_cutoff, orphan_cutoff,
                )
                r_sig = await conn.execute(
                    "DELETE FROM signature_requests s"
                    " WHERE s.session_id IN (SELECT id FROM processing_sessions WHERE updated_at < $1)"
                    "    OR (NOT EXISTS (SELECT 1 FROM processing_sessions p WHERE p.id = s.session_id)"
                    "        AND s.created_at < $2)",
                    session_cutoff, orphan_cutoff,
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
            "Retention cleanup: deleted jobs=%d arq=%d sessions=%d pending_signups=%d "
            "pdfs=%d signature_requests=%d",
            _row_count(r1), _row_count(r2), _row_count(r3), _row_count(r4),
            _row_count(r_pdf), _row_count(r_sig),
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

    audit_events (the E&O event spine) is swept here too, on its own knob.

    OWNER RULING 2026-08-27 (V1 H7 / D48): AUDIT_EVENTS_RETENTION_DAYS defaults
    to 365 and is FLOORED at 365, matching AUDIT_LOG_RETENTION_DAYS. This
    SUPERSEDES the 180-day half of the 2026-08-26 Q18 ruling.

    Why it had to move: at 180 days the spine expired BEFORE the mutable tables
    it exists to explain (field_source_audit / sqs_recommendation_audit /
    acord_audit_log, all 365) and before six tables that are never swept at all.
    From month 7 to month 12 the E&O record would have been current state with
    its history already deleted - precisely the failure the client's section 12
    describes. Q18's "keep the record for 6 months" is a FLOOR, so this extends
    it rather than weakening it; the facts-retention half (free/essentials =
    180 in run_facts_retention) is unchanged and still honours it directly.

    NOTE (D50): the spine is now also the product-history store, so the navbar
    Activity Log inherits this 365-day window. The retired `activity_events`
    table was never swept; its remaining rows are still not swept, and they only
    shrink.
    """
    import os as _os

    audit_days = int(_os.getenv("AUDIT_LOG_RETENTION_DAYS", "365"))
    cutoff     = (datetime.now(timezone.utc) - timedelta(days=audit_days)).isoformat()
    events_days = max(int(_os.getenv("AUDIT_EVENTS_RETENTION_DAYS", "365")), 365)
    events_cutoff = (datetime.now(timezone.utc) - timedelta(days=events_days)).isoformat()

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
                r_events = await conn.execute(
                    "DELETE FROM audit_events WHERE created_at < $1",
                    events_cutoff,
                )

        n_audit = _row_count(r_audit)
        n_field = _row_count(r_field)
        n_sqs   = _row_count(r_sqs)
        n_events = _row_count(r_events)
        ts      = datetime.now(timezone.utc).isoformat()

        logger.info(
            "Audit log retention: cutoff=%s deleted acord_audit_log=%d "
            "field_source_audit=%d sqs_recommendation_audit=%d "
            "audit_events(cutoff=%s)=%d at=%s",
            cutoff, n_audit, n_field, n_sqs, events_cutoff, n_events, ts,
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
      free        → 180 days (was 30 - raised 2026-08-26, owner ruling Q18:
                    "keep the [E&O] record for 6 months". The audit export's
                    captured-inputs section reads session facts; purging a
                    free session's facts at day 30 would blank that section
                    inside the ruled 6-month window)
      essentials  → 180 days
      professional / enterprise → indefinite (skipped)
    """
    import json as _json

    now = datetime.now(timezone.utc)
    ts  = now.isoformat()

    TIERS = {
        "free":       180,
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
                    # FIXED 2026-08-26 (found during the C5 E&O audit work):
                    # processing_sessions has NO `facts` column - facts live at
                    # data->'facts' (config/database.py). The old statement
                    # (`SET facts = ...`) raised "column does not exist" into
                    # the except below EVERY night since the job shipped, so no
                    # free/essentials session was ever actually purged. Same
                    # tombstone payload, applied where the data actually is.
                    # jsonb_set with create_missing=true also tombstones a
                    # session whose data has no facts key at all.
                    result = await conn.execute(
                        """
                        UPDATE processing_sessions ps
                        SET    data = jsonb_set(ps.data, '{facts}', $1::jsonb, true)
                        FROM   users u
                        WHERE  ps.user_id     = u.id
                          AND  u.subscription_tier = $2
                          AND  ps.updated_at  < $3
                          AND  (ps.data->'facts' IS NULL
                                OR ps.data->'facts'->>'purged' IS DISTINCT FROM 'true')
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


def _lock_database_url() -> str:
    """A SESSION connection for the advisory lock. Supabase's pooler serves
    transaction mode on 6543 and session mode on 5432 of the same host; a session
    lock taken through transaction pooling lands on whichever server connection
    ran that one statement, so we would neither hold nor release it.
    DATABASE_URL_DIRECT (render.yaml's session-mode URL) wins when set."""
    url = (os.getenv("DATABASE_URL_DIRECT") or DATABASE_URL or "").strip()
    try:
        parts = urlsplit(url)
        if (parts.port == 6543
                and (parts.hostname or "").endswith("pooler.supabase.com")
                and parts.netloc.endswith(":6543")):
            return urlunsplit(parts._replace(netloc=parts.netloc[: -len("6543")] + "5432"))
    except ValueError:
        pass
    return url


def _close_lock_conn() -> None:
    global _lock_conn
    if _lock_conn is not None:
        try:
            _lock_conn.close()
        except Exception:
            pass
    _lock_conn = None


def _holds_lock() -> bool:
    """True when THIS process runs the daily jobs.

    Asked before EVERY run, not once at start-up. The start-up-only check left a
    process that lost the race (the second gunicorn worker, the new instance of
    a deploy) without jobs for life, and once the winner was replaced nobody ran
    them. Holding = our lock connection still answers (Postgres frees a session
    lock only when its session ends); otherwise try to take the lock now."""
    global _lock_conn
    with _lock_guard:
        if _lock_conn is not None:
            try:
                with _lock_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                return True
            except Exception:
                logger.warning("Scheduler: job-lock connection lost - taking the lock again")
                _close_lock_conn()
        conn = None
        try:
            conn = psycopg2.connect(
                _lock_database_url(), connect_timeout=10,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
            )
            conn.autocommit = True   # never sit "idle in transaction" holding the session
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_ID,))
                got = bool(cur.fetchone()[0])
        except Exception as ex:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            logger.error("Scheduler: job lock unavailable (%s) - this run is skipped here", ex)
            return False
        if not got:
            conn.close()
            return False
        _lock_conn = conn
        logger.info("Scheduler: this process now runs the daily jobs (job lock taken)")
        return True


def _run_if_owner(job):
    """`job`, run only in the process holding the job lock - every process with
    the scheduler on fires the trigger, exactly one does the work."""
    async def _guarded():
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(None, _holds_lock):
            logger.info("Scheduler: %s skipped here - another process runs the daily jobs",
                        job.__name__)
            return
        await job()
    _guarded.__name__ = job.__name__
    return _guarded


# Client-facing jobs: always on wherever the scheduler runs.
_CLIENT_JOBS = (
    ("payment_lifecycle",  run_daily_payment_lifecycle, 9,  0),
    ("arq_auto_reminders", run_arq_auto_reminders,      10, 0),
)
# Jobs that DELETE data. Off unless SCHEDULER_CLEANUP_JOBS=true: deleting from the
# client's production database is a decision, not a side effect of turning on
# the reminders (15 Oct 2026 - until then they ran only from the owner's Mac).
_CLEANUP_JOBS = (
    ("retention_cleanup",   run_retention_cleanup,   3, 0),
    ("audit_log_retention", run_audit_log_retention, 3, 30),
    ("facts_retention",     run_facts_retention,     4, 0),
)


def _cleanup_jobs_enabled() -> bool:
    return (os.getenv("SCHEDULER_CLEANUP_JOBS") or "false").strip().lower() == "true"


def register_jobs(sched, cleanup=None) -> list:
    """Add the daily jobs to `sched` and return their ids. A run missed because
    the process was busy or restarting at that minute still fires within the
    hour (APScheduler's default grace is one second, then the day is lost)."""
    if cleanup is None:
        cleanup = _cleanup_jobs_enabled()
    jobs = _CLIENT_JOBS + (_CLEANUP_JOBS if cleanup else ())
    for job_id, fn, hour, minute in jobs:
        sched.add_job(
            _run_if_owner(fn), "cron", hour=hour, minute=minute,
            id=job_id, name=job_id, replace_existing=True,
            misfire_grace_time=3600, coalesce=True, max_instances=1,
        )
    return [job_id for job_id, *_ in jobs]


def start_scheduler():
    """Start the daily jobs in this process. Every process with the scheduler on
    starts them; the job lock, checked at each run, lets exactly one do the work,
    and a survivor takes over when that one goes (a deploy, a restart)."""
    if scheduler.running:
        return
    added = register_jobs(scheduler)
    scheduler.start()
    owner = _holds_lock()
    logger.info(
        "Scheduler started (%s): jobs=%s, cleanup jobs %s; this process %s",
        scheduler.timezone, ", ".join(added),
        "on" if _cleanup_jobs_enabled() else "off (SCHEDULER_CLEANUP_JOBS)",
        "runs them" if owner else "stands by (another process holds the job lock)",
    )


def stop_scheduler():
    try:
        scheduler.shutdown()
    except Exception:
        pass
    with _lock_guard:
        _close_lock_conn()
