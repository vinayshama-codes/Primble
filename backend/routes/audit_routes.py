import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from models.schemas import (
    DismissRecommendationRequest,
    ResolveRecommendationRequest,
    DownloadAnywayRequest,
)
from repositories.session_repository import get_processing_session
from services.audit_service import (
    get_open_recommendations,
    get_audit_summary,
    mark_recommendation_dismissed,
    mark_recommendation_resolved,
    log_download_with_open_recs,
)
from services.auth_service import get_current_user
from services.sqs_service import SQS_MODEL_VERSION, generate_sqs_narrative

router = APIRouter(tags=["audit"])
logger = logging.getLogger(__name__)


async def _verify_session_owner(session_id: str, current_user: dict) -> None:
    """Raise 403 if the session does not belong to current_user."""
    try:
        session = await get_processing_session(session_id)
    except HTTPException:
        raise HTTPException(404, "Session not found")
    if str(session.get("user_id", "")) != str(current_user["id"]):
        raise HTTPException(403, "Access denied")


@router.post("/api/audit/dismiss")
async def dismiss_recommendation(
    req: DismissRecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(req.session_id, current_user)
    success = await mark_recommendation_dismissed(
        session_id=req.session_id,
        rec_id=req.rec_id,
        override_reason=req.override_reason,
        sqs_score_at_action=req.sqs_score_at_action,
        model_version=SQS_MODEL_VERSION,
        message=req.message,
        field=req.field,
        component=req.component,
        score_impact=req.score_impact,
        user_id=str(current_user["id"]),
        form_id=req.form_id,
    )
    return JSONResponse({"success": success})


@router.post("/api/audit/resolve")
async def resolve_recommendation(
    req: ResolveRecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(req.session_id, current_user)
    success = await mark_recommendation_resolved(
        session_id=req.session_id,
        rec_id=req.rec_id,
        sqs_score_at_action=req.sqs_score_at_action,
        model_version=SQS_MODEL_VERSION,
    )
    return JSONResponse({"success": success})


@router.get("/api/audit/open/{session_id}")
async def get_open_recs(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)
    recs = await get_open_recommendations(session_id)
    return JSONResponse({"success": True, "open_recommendations": recs, "count": len(recs)})


@router.post("/api/audit/download-anyway")
async def download_anyway(
    req: DownloadAnywayRequest,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(req.session_id, current_user)
    count = await log_download_with_open_recs(
        session_id=req.session_id,
        override_reason=req.override_reason,
        model_version=SQS_MODEL_VERSION,
        user_id=str(current_user["id"]),
    )
    return JSONResponse({"success": True, "logged_count": count})


@router.get("/api/audit/summary/{session_id}")
async def audit_summary(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)
    summary = await get_audit_summary(session_id)
    return JSONResponse({"success": True, **summary})


@router.get("/api/sqs/narrative/{session_id}")
async def sqs_narrative(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)

    try:
        session = await get_processing_session(session_id)
    except HTTPException:
        raise HTTPException(404, "Session not found")

    generated = session.get("generated_forms", {})
    sqs_result: dict = {}
    if generated:
        first_form = next(iter(generated.values()), {})
        sqs_result = first_form.get("sqs", {})

    if not sqs_result:
        raise HTTPException(status_code=404, detail="No SQS data found for this session")

    summary         = await get_audit_summary(session_id)
    rec_counts      = summary.get("recommendations", {})
    resolved_count  = int(rec_counts.get("resolved") or 0)
    dismissed_count = int(rec_counts.get("dismissed") or 0)
    delta = sqs_result.get("delta_this_session") or 0

    resolved_recs = [f"{resolved_count} recommendation(s) resolved"] if resolved_count else []
    ignored_recs  = [f"{dismissed_count} recommendation(s) dismissed"] if dismissed_count else []

    narrative = await generate_sqs_narrative(
        sqs_result=sqs_result,
        delta_this_session=delta,
        resolved_recs=resolved_recs,
        ignored_recs=ignored_recs,
    )
    return JSONResponse({"success": True, "narrative": narrative})
