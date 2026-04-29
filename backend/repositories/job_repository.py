import json
import logging
from typing import List, Optional

from config.database import get_db
from services.job_queue import JobQueue, STATUS_PENDING, _build_job, _now_iso

logger = logging.getLogger(__name__)


class JobRepository(JobQueue):
    """PostgreSQL-backed JobQueue.

    Survives restarts and is safe across multiple uvicorn workers because
    all state lives in the DB.  Enable with JOB_QUEUE_BACKEND=db.
    """

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        job  = _build_job(job_type, payload, user_id, session_id)
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """INSERT INTO jobs
               (job_id, session_id, user_id, job_type, status,
                payload, result, error_message, progress_message,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, NULL, %s, %s)""",
            (
                job["job_id"],
                job["session_id"],
                job["user_id"],
                job["job_type"],
                job["status"],
                json.dumps(job["payload"]),
                job["created_at"],
                job["updated_at"],
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Job enqueued: %s type=%s", job["job_id"], job_type)
        return job["job_id"]

    async def get_status(self, job_id: str) -> Optional[dict]:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        # JSONB columns come back as dicts from psycopg2 RealDictCursor.
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

    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        now    = _now_iso()
        cols   = ["status = %s", "updated_at = %s"]
        params = [status, now]
        if result is not None:
            cols.append("result = %s")
            params.append(json.dumps(result))
        if error is not None:
            cols.append("error_message = %s")
            params.append(error)
        if progress_message is not None:
            cols.append("progress_message = %s")
            params.append(progress_message)
        params.append(job_id)
        conn = get_db()
        cur  = conn.cursor()
        # cols contains only hardcoded strings with %s placeholders — safe to interpolate.
        cur.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id = %s", params)
        conn.commit()
        cur.close()
        conn.close()

    async def list_pending(self, limit: int = 10) -> List[dict]:
        """Atomically claim up to `limit` pending jobs by transitioning them to
        'processing' in a single statement.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so that concurrent workers
        each claim a disjoint set of rows — no two workers process the same job.
        The UPDATE is inside the same transaction, so a worker that crashes before
        completing leaves jobs in 'processing'; a separate stuck-job reaper (or
        the retention cleanup) can reset those after a timeout.
        """
        now  = _now_iso()
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE jobs
            SET    status = 'processing', updated_at = %s
            WHERE  job_id IN (
                SELECT job_id
                FROM   jobs
                WHERE  status = %s
                ORDER  BY created_at ASC
                LIMIT  %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (now, STATUS_PENDING, limit),
        )
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        conn.close()

        result = []
        for row in rows:
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
