import json
import logging
from typing import List, Optional

from config.database import get_pool
from services.job_queue import JobQueue, STATUS_PENDING, _build_job, _now_iso

logger = logging.getLogger(__name__)

_UPDATABLE_JOB_COLS = frozenset({"status", "updated_at", "result", "error_message", "progress_message"})


class JobRepository(JobQueue):
    """PostgreSQL-backed JobQueue via asyncpg. Enable with JOB_QUEUE_BACKEND=db."""

    # ASYNC-SAFE
    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        job = _build_job(job_type, payload, user_id, session_id)
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO jobs
                   (job_id, session_id, user_id, job_type, status,
                    payload, result, error_message, progress_message,
                    created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,NULL,NULL,NULL,$7,$8)""",
                job["job_id"],
                job["session_id"],
                job["user_id"],
                job["job_type"],
                job["status"],
                job["payload"],          # dict — asyncpg encodes as jsonb
                job["created_at"],
                job["updated_at"],
            )
        logger.info("Job enqueued: %s type=%s", job["job_id"], job_type)
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
        """Atomically claim pending jobs (SELECT ... FOR UPDATE SKIP LOCKED)."""
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
                        ORDER  BY created_at ASC
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
                "created_at":       str(row["created_at"]),
                "updated_at":       str(row["updated_at"]),
            })
        return result
