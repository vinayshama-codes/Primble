import json
import logging
import os
from typing import List, Optional

from config.database import get_pool
from services.job_queue import JobQueue, STATUS_PENDING, _build_job, _now_iso

logger = logging.getLogger(__name__)

_UPDATABLE_JOB_COLS = frozenset({"status", "updated_at", "result", "error_message", "progress_message", "retry_count", "priority"})

# PostgreSQL LISTEN/NOTIFY channel — workers LISTEN on this channel and wake
# up immediately when enqueue() fires a NOTIFY. Replaces the 5s polling delay.
JOB_NOTIFY_CHANNEL = "acordly_jobs"

# Jobs left in 'processing' for longer than this are presumed orphaned (worker
# crashed or restarted mid-job). The watchdog at worker startup resets them
# back to 'pending' so they get picked up again.
_STUCK_JOB_THRESHOLD_MINUTES = int(os.getenv("STUCK_JOB_THRESHOLD_MINUTES", "30"))


class JobRepository(JobQueue):
    """PostgreSQL-backed JobQueue via asyncpg. Enable with JOB_QUEUE_BACKEND=db."""

    # ASYNC-SAFE
    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
        priority: int = 5,
    ) -> str:
        """Insert a pending job and notify any LISTENing worker.

        priority: lower number = higher priority. 1 = urgent (paid users,
        retries), 5 = default, 9 = background. Workers select in (priority,
        created_at) order, so a priority-1 job submitted now will run before
        a priority-5 job submitted earlier.
        """
        job = _build_job(job_type, payload, user_id, session_id)
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO jobs
                   (job_id, session_id, user_id, job_type, status,
                    payload, result, error_message, progress_message,
                    priority, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,NULL,NULL,NULL,$7,$8,$9)""",
                job["job_id"],
                job["session_id"],
                job["user_id"],
                job["job_type"],
                job["status"],
                job["payload"],          # dict — asyncpg encodes as jsonb
                int(priority),
                job["created_at"],
                job["updated_at"],
            )
            # Wake any LISTENing worker immediately. Payload is the job_id
            # for diagnostic purposes only; the worker re-queries the DB to
            # pick the highest-priority pending job, so payload contents are
            # not load-bearing.
            try:
                await conn.execute(
                    f"NOTIFY {JOB_NOTIFY_CHANNEL}, '{job['job_id']}'"
                )
            except Exception as ex:
                # NOTIFY failure is non-fatal — worker will pick the job up
                # on its next poll cycle. Log and continue.
                logger.warning("NOTIFY failed for job %s: %s", job["job_id"], ex)
        logger.info("Job enqueued: %s type=%s priority=%d", job["job_id"], job_type, priority)
        return job["job_id"]

    # ASYNC-SAFE
    async def get_status(self, job_id: str) -> Optional[dict]:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM jobs WHERE job_id = $1", job_id
            )
        if row is None:
            return None
        row = dict(row)
        payload = row["payload"]
        result  = row["result"]
        return {
            "job_id":           row["job_id"],
            "session_id":       row["session_id"],
            "user_id":          row["user_id"],
            "job_type":         row["job_type"],
            "status":           row["status"],
            "payload":          payload if isinstance(payload, dict) else (json.loads(payload) if payload else {}),
            "result":           result  if isinstance(result,  dict) else (json.loads(result)  if result  else None),
            "error_message":    row["error_message"],
            "progress_message": row["progress_message"],
            "retry_count":      row.get("retry_count", 0) or 0,
            "priority":         row.get("priority", 5) or 5,
            "created_at":       str(row["created_at"]),
            "updated_at":       str(row["updated_at"]),
        }

    # ASYNC-SAFE
    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        now    = _now_iso()
        cols   = ["status = $1", "updated_at = $2"]
        params: list = [status, now]
        if result is not None:
            params.append(result)          # dict — asyncpg encodes as jsonb
            cols.append(f"result = ${len(params)}")
        if error is not None:
            params.append(error)
            cols.append(f"error_message = ${len(params)}")
        if progress_message is not None:
            params.append(progress_message)
            cols.append(f"progress_message = ${len(params)}")
        params.append(job_id)
        # SOC 2 secure coding: whitelist guard prevents future injection via dynamic cols
        col_names = {c.split(" =")[0].strip() for c in cols}
        assert col_names <= _UPDATABLE_JOB_COLS, (
            f"SOC2: Unexpected column(s) in dynamic job UPDATE: {col_names - _UPDATABLE_JOB_COLS}"
        )
        async with get_pool().acquire() as conn:
            await conn.execute(
                f"UPDATE jobs SET {', '.join(cols)} WHERE job_id = ${len(params)}",
                *params,
            )

    # ASYNC-SAFE
    async def count_user_active_jobs(self, user_id: str) -> int:
        async with get_pool().acquire() as conn:
            # Jobs older than 30 minutes are considered dead (crashed/timed out) and excluded.
            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM jobs WHERE user_id = $1 AND status IN ('pending', 'processing') AND created_at::timestamptz > NOW() - INTERVAL '30 minutes'",
                str(user_id),
            )
        return int(row[0]) if row else 0

    # ASYNC-SAFE
    async def claim_job_if_pending(self, job_id: str) -> bool:
        """Atomically claim a job by transitioning pending→processing.

        Returns True only if this worker performed the update (i.e. the row
        was still 'pending'). Any other worker that races will find the status
        already changed and get False.
        """
        now = _now_iso()
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                "UPDATE jobs SET status='processing', updated_at=$1 WHERE job_id=$2 AND status='pending'",
                now, job_id,
            )
        return result == "UPDATE 1"

    # ASYNC-SAFE
    async def list_pending(self, limit: int = 10) -> List[dict]:
        """Atomically claim pending jobs (SELECT ... FOR UPDATE SKIP LOCKED).

        Ordered by (priority ASC, created_at ASC) so priority-1 urgent jobs
        preempt priority-5 standard jobs even if the standard job was queued
        first. FOR UPDATE SKIP LOCKED lets multiple worker instances pull
        disjoint sets without blocking each other.
        """
        now = _now_iso()
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    UPDATE jobs
                    SET    status = 'processing', updated_at = $1
                    WHERE  job_id IN (
                        SELECT job_id
                        FROM   jobs
                        WHERE  status = $2
                        ORDER  BY COALESCE(priority, 5) ASC, created_at ASC
                        LIMIT  $3
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                    """,
                    now, STATUS_PENDING, limit,
                )

        result = []
        for row in rows:
            row = dict(row)
            payload    = row["payload"]
            result_val = row["result"]
            result.append({
                "job_id":           row["job_id"],
                "session_id":       row["session_id"],
                "user_id":          row["user_id"],
                "job_type":         row["job_type"],
                "status":           row["status"],
                "payload":          payload    if isinstance(payload,    dict) else (json.loads(payload)    if payload    else {}),
                "result":           result_val if isinstance(result_val, dict) else (json.loads(result_val) if result_val else None),
                "error_message":    row["error_message"],
                "progress_message": row["progress_message"],
                "retry_count":      row.get("retry_count", 0) or 0,
                "priority":         row.get("priority", 5) or 5,
                "created_at":       str(row["created_at"]),
                "updated_at":       str(row["updated_at"]),
            })
        return result

    # ASYNC-SAFE
    async def increment_retry_count(self, job_id: str) -> int:
        """Atomically increment retry_count and return the new value."""
        now = _now_iso()
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE jobs SET retry_count = COALESCE(retry_count, 0) + 1, updated_at = $1 "
                "WHERE job_id = $2 RETURNING retry_count",
                now, job_id,
            )
        return int(row["retry_count"]) if row else 1

    # ASYNC-SAFE
    async def reset_stuck_jobs(self, threshold_minutes: Optional[int] = None) -> int:
        """Reset jobs orphaned by a crashed worker back to pending.

        A job in 'processing' that has not had its updated_at touched for
        threshold_minutes is presumed dead (the worker did not get a chance
        to mark it failed or completed). Reset it to 'pending' so the next
        polling cycle picks it up. Called once at worker startup and
        periodically thereafter.

        Returns the count of jobs reset. Jobs that have already exceeded
        WORKER_MAX_JOB_RETRIES are NOT reset — they stay in processing and
        will be dead-lettered manually via the admin UI to avoid an
        unbounded retry loop on a permanently failing job.
        """
        threshold = threshold_minutes if threshold_minutes is not None else _STUCK_JOB_THRESHOLD_MINUTES
        now = _now_iso()
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE jobs
                SET    status = 'pending',
                       updated_at = $1,
                       progress_message = 'recovered_from_stuck_processing'
                WHERE  status = 'processing'
                  AND  updated_at::timestamptz < NOW() - INTERVAL '{int(threshold)} minutes'
                  AND  COALESCE(retry_count, 0) < {int(os.getenv("WORKER_MAX_JOB_RETRIES", "5"))}
                """,
                now,
            )
        # asyncpg returns "UPDATE N" — parse the count.
        try:
            count = int(result.split()[-1])
        except (ValueError, IndexError):
            count = 0
        if count:
            logger.warning("Watchdog: reset %d stuck job(s) from processing → pending", count)
        return count
