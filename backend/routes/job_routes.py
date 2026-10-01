import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from services.job_queue import get_job_queue, JOB_TYPE_FORM_GENERATION
from services.generation_state import job_is_stale
from services.auth_service import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("/{job_id}/status")
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    job = await get_job_queue().get_status(job_id)
    if job is None or str(job["user_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse({
        "job_id": job["job_id"],
        "session_id": job["session_id"],
        "status": job["status"],
        "progress_message": job.get("progress_message"),
        "error": job.get("error_message"),
        "result": job.get("result"),
        # Orbin item 1: a form generation whose heartbeat stopped died with its
        # process (restart / deploy / crash). The progress screen stops waiting
        # on it. Only form generation heartbeats, so only it can be stale.
        "stale": job.get("job_type") == JOB_TYPE_FORM_GENERATION and job_is_stale(job),
    })
