"""dry_run_routes.py - "Before you generate" on demand (Choice Electric #27, 7 Oct 2026).

Every pre-form response already carries the dry run as `dry_run`
(`form_routes._pre_form_status`). This route serves the two cases a response
cannot:

* the run was still going when the response left (`status: "pending"`) - the
  package page polls here until it is ready;
* the producer has ticked a different set of forms - the list is re-checked
  against exactly those forms (`form_ids`).

Read-only and owner-checked. Same door, same cache, same time bound as the
responses (`services.form_dry_run.dry_run_payload`).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from repositories.session_repository import get_processing_session
from services.auth_service import get_current_user

router = APIRouter(tags=["dry-run"])
logger = logging.getLogger(__name__)

# How long one request may wait for a run in progress before answering
# `pending` (the run keeps going into the cache either way).
_MAX_WAIT_SECONDS = 20.0


@router.get("/api/session/{session_id}/dry-run")
async def get_dry_run(
    session_id: str,
    form_ids: str = Query("", description="Comma-separated form ids (the producer's ticks)"),
    wait: float = Query(6.0, ge=0.0, le=_MAX_WAIT_SECONDS),
    current_user: dict = Depends(get_current_user),
):
    session = await get_processing_session(session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")
    # Withheld exactly like the rest of the pre-form payload while a Submission
    # Integrity review is pending; nothing to promise once forms exist.
    if (session.get("integrity") or {}).get("review_required"):
        return JSONResponse({"success": True, "dry_run": None,
                             "reason": "integrity_review_pending"})
    if session.get("generated_forms"):
        return JSONResponse({"success": True, "dry_run": None, "reason": "forms_generated"})
    ids = [f.strip() for f in (form_ids or "").split(",") if f.strip()][:40]
    from services.form_dry_run import dry_run_payload
    payload = await dry_run_payload(
        session, session.get("facts") or {}, session.get("flags") or {},
        ids or None, session_id=session_id, wait=min(float(wait), _MAX_WAIT_SECONDS),
    )
    return JSONResponse({"success": True, "dry_run": payload})
