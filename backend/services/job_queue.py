"""Job-queue abstraction layer.

Supports three backends, selected via env var JOB_QUEUE_BACKEND:
  local_file  (default) — one JSON file per job under backend/tmp/jobs/
  memory                — in-process dict; lost on restart
  db                    — PostgreSQL-backed; durable across restarts

JOB_QUEUE_BACKEND=db is the recommended production default.
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
        priority: int = 5,
    ) -> str:
        """Persist a new job record with status=pending. Returns job_id.

        priority is a hint for backends that support it (db). Lower number =
        higher priority. Default 5; use 1 for urgent (e.g. paid plan users)
        and 9 for background. Backends without priority support ignore it.
        """

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
        """Return up to `limit` jobs with status=pending."""
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
        priority: int = 5,
    ) -> str:
        job = _build_job(job_type, payload, user_id, session_id)
        job["priority"] = int(priority)
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
        priority: int = 5,
    ) -> str:
        job = _build_job(job_type, payload, user_id, session_id)
        job["priority"] = int(priority)
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
            "Use JOB_QUEUE_BACKEND=db."
        )


def get_job_queue() -> JobQueue:
    """Return the singleton JobQueue for the configured backend.

    Instantiated lazily on first call so that LocalFileJobQueue's
    os.makedirs() runs at request time, not at import time.

    Set JOB_QUEUE_BACKEND to one of: local_file (default), memory, db.
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
        else:
            raise ValueError(
                f"Unknown JOB_QUEUE_BACKEND={_BACKEND!r}. "
                "Valid options: local_file, memory, db."
            )
    return _instance
