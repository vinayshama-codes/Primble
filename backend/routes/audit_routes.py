import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from models.schemas import (
    DismissRecommendationRequest,
    ResolveRecommendationRequest,
    DownloadAnywayRequest,
)
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


@router.post("/api/audit/dismiss")
async def dismiss_recommendation(
    req: DismissRecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    success = mark_recommendation_dismissed(
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
    success = mark_recommendation_resolved(
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
    recs = get_open_recommendations(session_id)
    return JSONResponse({"success": True, "open_recommendations": recs, "count": len(recs)})


@router.post("/api/audit/download-anyway")
async def download_anyway(
    req: DownloadAnywayRequest,
    current_user: dict = Depends(get_current_user),
):
    count = log_download_with_open_recs(
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
    summary = get_audit_summary(session_id)
    return JSONResponse({"success": True, **summary})


@router.get("/api/sqs/narrative/{session_id}")
async def sqs_narrative(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate (or regenerate) a prose narrative for this session's SQS.
    Pulls the stored SQS result from the session, derives delta / resolved / ignored
    counts from the audit table, then calls the LLM narrative generator.
    """
    from repositories.session_repository import get_processing_session
    from services.audit_service import get_audit_summary

    try:
        session = get_processing_session(session_id)
    except Exception:
        session = None
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Pick the best SQS result — fall back to first form's SQS
    generated = session.get("generated_forms", {})
    sqs_result: dict = {}
    if generated:
        first_form = next(iter(generated.values()), {})
        sqs_result = first_form.get("sqs", {})

    if not sqs_result:
        raise HTTPException(status_code=404, detail="No SQS data found for this session")

    # Derive delta / resolved / ignored from the audit table
    summary = get_audit_summary(session_id)
    rec_counts = summary.get("recommendations", {})
    resolved_count = int(rec_counts.get("resolved") or 0)
    dismissed_count = int(rec_counts.get("dismissed") or 0)
    delta = sqs_result.get("sqs_score") or sqs_result.get("package_sqs_score") or 0

    # Build lightweight label lists for the narrative prompt
    resolved_recs = [f"{resolved_count} recommendation(s) resolved"] if resolved_count else []
    ignored_recs  = [f"{dismissed_count} recommendation(s) dismissed"] if dismissed_count else []

    narrative = generate_sqs_narrative(
        sqs_result=sqs_result,
        delta_this_session=delta,
        resolved_recs=resolved_recs,
        ignored_recs=ignored_recs,
    )
    return JSONResponse({"success": True, "narrative": narrative})
