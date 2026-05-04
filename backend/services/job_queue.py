"""Job-queue abstraction layer.

Supports four backends, selected via env var JOB_QUEUE_BACKEND:
  local_file  (default) — one JSON file per job under backend/tmp/jobs/
  memory                — in-process dict; lost on restart
  db                    — PostgreSQL-backed; durable across restarts
  sqs                   — AWS SQS + PostgreSQL status tracking

Required env vars for sqs backend:
  SQS_QUEUE_URL   — full HTTPS URL of the SQS queue
  AWS_REGION      — AWS region (default: us-east-1)
  JOB_QUEUE_BACKEND=sqs
  JOB_QUEUE_BACKEND=db is the recommended production default before SQS.
"""
import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status constants — shared with job_repository and routes
# ---------------------------------------------------------------------------
STATUS_PENDING    = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED  = "completed"
STATUS_FAILED     = "failed"

# Job types
JOB_TYPE_EXTRACTION       = "extraction"
JOB_TYPE_FORM_GENERATION  = "form_generation"
JOB_TYPE_EMAIL            = "email"

_JOBS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tmp", "jobs",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_job(
    job_type: str,
    payload: dict,
    user_id: str,
    session_id: Optional[str],
) -> dict:
    return {
        "job_id":           str(uuid.uuid4()),
        "session_id":       session_id,
        "user_id":          user_id,
        "job_type":         job_type,
        "status":           STATUS_PENDING,
        "payload":          payload,
        "result":           None,
        "error_message":    None,
        "progress_message": None,
        "created_at":       _now_iso(),
        "updated_at":       _now_iso(),
    }


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class JobQueue(ABC):
    @abstractmethod
    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Persist a new job record with status=pending. Returns job_id."""

    @abstractmethod
    async def get_status(self, job_id: str) -> Optional[dict]:
        """Return the full job dict, or None if not found."""

    @abstractmethod
    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        """Update status and optional fields on an existing job."""

    async def list_pending(self, limit: int = 10) -> List[dict]:
        """Return up to `limit` jobs with status=pending.

        Not all backends support this natively (SQS does not). Override in
        backends that have queryable storage; the default returns [].
        """
        return []

    async def count_user_active_jobs(self, user_id: str) -> int:
        """Return the number of pending/processing jobs for this user.

        Default implementation scans list_pending — subclasses with DB access
        should override with a targeted query for accuracy.
        """
        return 0


# ---------------------------------------------------------------------------
# InMemoryJobQueue
# ---------------------------------------------------------------------------

class InMemoryJobQueue(JobQueue):
    """In-process dict. State is lost on restart.

    Use for local development or tests when file I/O is undesirable.
    """

    def __init__(self) -> None:
        self._jobs: dict = {}

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        job = _build_job(job_type, payload, user_id, session_id)
        self._jobs[job["job_id"]] = job
        return job["job_id"]

    async def get_status(self, job_id: str) -> Optional[dict]:
        return self._jobs.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job["status"]     = status
        job["updated_at"] = _now_iso()
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error_message"] = error
        if progress_message is not None:
            job["progress_message"] = progress_message

    async def list_pending(self, limit: int = 10) -> List[dict]:
        return [
            j for j in list(self._jobs.values())
            if j["status"] == STATUS_PENDING
        ][:limit]

    async def count_user_active_jobs(self, user_id: str) -> int:
        return sum(
            1 for j in self._jobs.values()
            if j["user_id"] == str(user_id) and j["status"] in (STATUS_PENDING, STATUS_PROCESSING)
        )


# ---------------------------------------------------------------------------
# LocalFileJobQueue
# ---------------------------------------------------------------------------

class LocalFileJobQueue(JobQueue):
    """One JSON file per job under backend/tmp/jobs/.

    Survives process restarts unlike InMemoryJobQueue.

    Multi-worker note: each worker has its own Python process. A job file is
    created by one worker and updated only by that same worker (the one
    processing it), so file contention is unlikely. At multiple-worker scale,
    replace with the DB-backed job repository (Step 5 + 7).
    """

    def __init__(self, jobs_dir: str = _JOBS_DIR) -> None:
        self._dir = jobs_dir
        os.makedirs(self._dir, mode=0o700, exist_ok=True)

    def _path(self, job_id: str) -> str:
        # job_id is a UUID; no path traversal risk
        return os.path.join(self._dir, f"{job_id}.json")

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        job = _build_job(job_type, payload, user_id, session_id)
        fd = os.open(self._path(job["job_id"]), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(job, fh, default=str)
        return job["job_id"]

    async def get_status(self, job_id: str) -> Optional[dict]:
        path = self._path(job_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        path = self._path(job_id)
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as fh:
                job = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        job["status"]     = status
        job["updated_at"] = _now_iso()
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error_message"] = error
        if progress_message is not None:
            job["progress_message"] = progress_message
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(job, fh, default=str)

    async def count_user_active_jobs(self, user_id: str) -> int:
        count = 0
        try:
            for name in os.listdir(self._dir):
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(self._dir, name), encoding="utf-8") as fh:
                        job = json.load(fh)
                    if job.get("user_id") == str(user_id) and job.get("status") in (STATUS_PENDING, STATUS_PROCESSING):
                        count += 1
                except (OSError, json.JSONDecodeError):
                    continue
        except OSError:
            pass
        return count

    async def list_pending(self, limit: int = 10) -> List[dict]:
        pending = []
        try:
            for name in os.listdir(self._dir):
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(self._dir, name), encoding="utf-8") as fh:
                        job = json.load(fh)
                    if job.get("status") == STATUS_PENDING:
                        pending.append(job)
                        if len(pending) >= limit:
                            break
                except (OSError, json.JSONDecodeError):
                    continue
        except OSError:
            pass
        return pending


# ---------------------------------------------------------------------------
# SqsJobQueue
# ---------------------------------------------------------------------------

_DLQ_MAX_RECEIVE_COUNT = 3  # Move to DLQ after this many receive attempts


class SqsJobQueue(JobQueue):
    """AWS SQS-backed job queue with PostgreSQL status tracking.

    SQS provides durable delivery; PostgreSQL tracks job status so callers
    can poll /api/jobs/<id>/status without reading SQS.

    Required env vars:
      SQS_QUEUE_URL     — full HTTPS URL of the SQS queue
      SQS_DLQ_URL       — full HTTPS URL of the dead-letter queue (optional;
                          if set, messages that fail _DLQ_MAX_RECEIVE_COUNT
                          times are moved here instead of re-queued)
      AWS_REGION        — AWS region (default: us-east-1)
    """

    def __init__(self) -> None:
        import boto3
        self._queue_url = os.getenv("SQS_QUEUE_URL", "").strip()
        if not self._queue_url:
            raise ValueError(
                "SQS_QUEUE_URL env var is required for JOB_QUEUE_BACKEND=sqs"
            )
        self._dlq_url = os.getenv("SQS_DLQ_URL", "").strip()
        self._sqs = boto3.client(
            "sqs",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        # Status tracking lives in PostgreSQL via JobRepository.
        from repositories.job_repository import JobRepository
        self._db = JobRepository()
        if self._dlq_url:
            logger.info("SqsJobQueue initialised: queue=%s dlq=%s", self._queue_url, self._dlq_url)
        else:
            logger.info("SqsJobQueue initialised: queue=%s (no DLQ configured)", self._queue_url)

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        # Persist status in DB first so get_status works immediately.
        db_job_id = await self._db.enqueue(job_type, payload, user_id, session_id)
        sqs_body = json.dumps({
            "job_id":     db_job_id,
            "job_type":   job_type,
            "user_id":    user_id,
            "session_id": session_id,
            "payload":    payload,
        })
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=sqs_body,
            MessageAttributes={
                "job_type": {
                    "DataType": "String",
                    "StringValue": job_type,
                }
            },
        )
        logger.info("SQS job enqueued: job_id=%s type=%s", db_job_id, job_type)
        return db_job_id

    async def get_status(self, job_id: str) -> Optional[dict]:
        return await self._db.get_status(job_id)

    async def update_status(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        progress_message: Optional[str] = None,
    ) -> None:
        await self._db.update_status(job_id, status, result, error, progress_message)

    def receive_messages(self, max_messages: int = 1, wait_seconds: int = 20) -> list:
        """Long-poll SQS for messages. Used by worker.py.

        Messages that have been received >= _DLQ_MAX_RECEIVE_COUNT times are
        automatically routed to the DLQ (if configured) and excluded from the
        returned list so the worker never processes them.
        """
        resp = self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
            MessageAttributeNames=["All"],
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = resp.get("Messages", [])
        if not self._dlq_url:
            return messages

        clean: list = []
        for msg in messages:
            receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            if receive_count >= _DLQ_MAX_RECEIVE_COUNT:
                self._route_to_dlq(msg)
            else:
                clean.append(msg)
        return clean

    def _route_to_dlq(self, msg: dict) -> None:
        """Forward a poisoned message to the DLQ and delete it from the source queue."""
        try:
            self._sqs.send_message(
                QueueUrl=self._dlq_url,
                MessageBody=msg["Body"],
                MessageAttributes=msg.get("MessageAttributes", {}),
            )
            logger.warning(
                "SqsJobQueue: message moved to DLQ after %s receive attempts: %s",
                msg.get("Attributes", {}).get("ApproximateReceiveCount", "?"),
                msg.get("MessageId", "unknown"),
            )
        except Exception as ex:
            logger.error("SqsJobQueue: failed to route message to DLQ: %s", ex)
        finally:
            # Always delete from source to avoid infinite re-delivery
            try:
                self._sqs.delete_message(
                    QueueUrl=self._queue_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception as ex:
                logger.error("SqsJobQueue: failed to delete DLQ-routed message from source: %s", ex)

    def delete_message(self, receipt_handle: str) -> None:
        """Delete a processed message from SQS."""
        self._sqs.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt_handle,
        )

    def inspect_dlq(self, max_messages: int = 10) -> list:
        """Peek at up to max_messages in the DLQ without consuming them.

        Returns an empty list if no DLQ is configured or on error.
        Used by the /api/admin/dlq-inspect endpoint.
        """
        if not self._dlq_url:
            return []
        try:
            resp = self._sqs.receive_message(
                QueueUrl=self._dlq_url,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=0,
                MessageAttributeNames=["All"],
                AttributeNames=["All"],
                VisibilityTimeout=0,  # peek only — message stays visible immediately
            )
            messages = resp.get("Messages", [])
            result = []
            for msg in messages:
                try:
                    body = json.loads(msg["Body"])
                except (ValueError, KeyError):
                    body = msg.get("Body", "")
                result.append({
                    "message_id":       msg.get("MessageId"),
                    "receive_count":    msg.get("Attributes", {}).get("ApproximateReceiveCount"),
                    "sent_at":          msg.get("Attributes", {}).get("ApproximateFirstReceiveTimestamp"),
                    "body":             body,
                })
            return result
        except Exception as ex:
            logger.error("SqsJobQueue: inspect_dlq failed: %s", ex)
            return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKEND: str = os.getenv("JOB_QUEUE_BACKEND", "local_file").lower()
_instance: Optional[JobQueue] = None


_NON_DISTRIBUTED_BACKENDS = {"local_file", "memory"}


def validate_queue_backend_for_environment() -> None:
    """Raise RuntimeError if a non-distributed backend is used in production."""
    _env = os.getenv("ENVIRONMENT", "development").lower()
    if _env == "production" and _BACKEND in _NON_DISTRIBUTED_BACKENDS:
        raise RuntimeError(
            f"JOB_QUEUE_BACKEND='{_BACKEND}' is not allowed in production. "
            "Use JOB_QUEUE_BACKEND=db or JOB_QUEUE_BACKEND=sqs."
        )


def get_job_queue() -> JobQueue:
    """Return the singleton JobQueue for the configured backend.

    Instantiated lazily on first call so that LocalFileJobQueue's
    os.makedirs() runs at request time, not at import time.

    Set JOB_QUEUE_BACKEND to one of: local_file (default), memory, db, sqs.
    """
    global _instance
    if _instance is None:
        validate_queue_backend_for_environment()
        if _BACKEND == "local_file":
            _instance = LocalFileJobQueue()
        elif _BACKEND == "memory":
            _instance = InMemoryJobQueue()
        elif _BACKEND == "db":
            # Lazy import to avoid circular dependency at module load time.
            from repositories.job_repository import JobRepository
            _instance = JobRepository()
        elif _BACKEND == "sqs":
            _instance = SqsJobQueue()
        else:
            raise ValueError(
                f"Unknown JOB_QUEUE_BACKEND={_BACKEND!r}. "
                "Valid options: local_file, memory, db, sqs."
            )
    return _instance
