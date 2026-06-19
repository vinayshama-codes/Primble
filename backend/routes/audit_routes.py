import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from config.database import get_pool
from models.schemas import (
    DismissRecommendationRequest,
    ResolveRecommendationRequest,
    DownloadAnywayRequest,
)
from repositories.session_repository import get_processing_session
from services.audit_service import (
    get_open_recommendations,
    get_dismissed_recommendations,
    get_audit_summary,
    mark_recommendation_dismissed,
    mark_recommendation_resolved,
    log_download_with_open_recs,
)
from services.auth_service import get_current_user
from services.sqs_service import SQS_MODEL_VERSION, generate_sqs_narrative

router = APIRouter(tags=["audit"])
logger = logging.getLogger(__name__)


def _grade_from_score(score: int) -> tuple:
    """Return (grade, tier, tier_color) for a given SQS score.
    Mirrors the frontend sqsGradeFromScore + tierMap so DB and UI always agree.
    """
    if score >= 90:
        return "A", "Submission Ready", "green"
    if score >= 80:
        return "B", "Almost There", "yellow"
    if score >= 70:
        return "C", "Needs Work", "orange"
    if score >= 60:
        return "D", "Major Gaps", "red"
    return "F", "Not Ready", "red"


def _stop_cap(hard_count: int, hard_cross_count: int, soft_count: int) -> int:
    """Return the max SQS score allowed given the session's active stops.

    Mirrors the cap logic in sqs_service.calculate_sqs exactly:
      * any active hard stop (field-level OR cross-form) -> capped at 60
      * else any active soft stop (warning)             -> capped at 85
      * else no cap (100)
    Hard stops take precedence when both are present.
    """
    if hard_count > 0 or hard_cross_count > 0:
        return 60
    if soft_count > 0:
        return 85
    return 100


async def _apply_dismiss_score_credit(
    session_id: str,
    form_id: str,
    score_at_action: int,
    score_impact: int,
) -> dict:
    """Bump the per-form SQS score after a producer override, then recompute the
    package SQS score as the average of all per-form scores.

    The credited score is capped by the session's active stops (hard stop -> 60,
    warning -> 85) so a producer override can never push a form past the same
    ceiling the scorer enforces while those stops are unresolved.  Dismissing a
    recommendation is an acknowledgment, not a fix — the underlying stop remains
    until the field is actually filled (which triggers a full recalculation that
    lifts the cap).  Persists score, grade, tier, tier_color (per-form) and the
    package score + tier so a page reload always shows the correct values.
    """
    new_score = min(100, (score_at_action or 0) + score_impact)
    try:
        async with get_pool().acquire() as conn:
            # Active-stop counts drive the cap. cross_issues_last carries cross-form
            # hard stops that aren't in the flat hard_stops list — count both, exactly
            # like calculate_sqs does (hard_stops OR hard_cross -> 60).
            stop_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(jsonb_array_length(data->'hard_stops'), 0) AS hard_count,
                    COALESCE(jsonb_array_length(data->'soft_stops'), 0) AS soft_count,
                    COALESCE((
                        SELECT count(*)
                        FROM jsonb_array_elements(COALESCE(data->'cross_issues_last', '[]'::jsonb)) e
                        WHERE e->>'type' = 'hard_stop'
                    ), 0) AS hard_cross_count
                FROM processing_sessions
                WHERE id = $1
                """,
                session_id,
            )
            hard_count       = (stop_row["hard_count"]       if stop_row else 0) or 0
            soft_count       = (stop_row["soft_count"]       if stop_row else 0) or 0
            hard_cross_count = (stop_row["hard_cross_count"] if stop_row else 0) or 0
            cap = _stop_cap(hard_count, hard_cross_count, soft_count)

            # Cap the credited form, then derive its grade/tier from the capped score.
            new_score = min(new_score, cap)
            new_grade, new_tier, new_tier_color = _grade_from_score(new_score)

            # Recompute the package as the average of all per-form scores (each of
            # which is already capped by its own calculate_sqs), then cap the
            # package too so it can never exceed the active-stop ceiling.
            rows = await conn.fetch(
                """
                SELECT ge.key AS form_id,
                       (ge.value->'sqs'->>'sqs_score')::int AS score
                FROM processing_sessions ps,
                     jsonb_each(COALESCE(ps.data->'generated_forms', '{}'::jsonb)) AS ge
                WHERE ps.id = $1
                """,
                session_id,
            )
            scores = {r["form_id"]: r["score"] for r in rows if r["score"] is not None}
            scores[form_id] = new_score
            new_pkg_score = int(round(sum(scores.values()) / len(scores))) if scores else new_score
            new_pkg_score = min(new_pkg_score, cap)
            _, new_pkg_tier, _ = _grade_from_score(new_pkg_score)

            await conn.execute(
                """
                UPDATE processing_sessions
                SET data = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    jsonb_set(
                                        data,
                                        ARRAY['generated_forms', $1, 'sqs', 'sqs_score'],
                                        to_jsonb($2::int), false
                                    ),
                                    ARRAY['generated_forms', $1, 'sqs', 'grade'],
                                    to_jsonb($6::text), false
                                ),
                                ARRAY['generated_forms', $1, 'sqs', 'tier'],
                                to_jsonb($7::text), false
                            ),
                            ARRAY['generated_forms', $1, 'sqs', 'tier_color'],
                            to_jsonb($8::text), false
                        ),
                        ARRAY['package_sqs', 'package_sqs_score'],
                        to_jsonb($3::int), false
                    ),
                    ARRAY['package_sqs', 'tier'],
                    to_jsonb($9::text), false
                ),
                updated_at = $4
                WHERE id = $5
                """,
                form_id,
                new_score,
                new_pkg_score,
                datetime.now(timezone.utc).isoformat(),
                session_id,
                new_grade,
                new_tier,
                new_tier_color,
                new_pkg_tier,
            )
        logger.info(
            f"Dismiss credit applied: session={session_id} form={form_id} "
            f"{score_at_action}+{score_impact}->{new_score} (cap={cap}) "
            f"grade={new_grade} pkg(avg)={new_pkg_score}"
        )
        return {
            "new_sqs_score": new_score,
            "new_package_sqs_score": new_pkg_score,
            "new_grade": new_grade,
            "new_tier": new_tier,
            "new_tier_color": new_tier_color,
            "new_package_tier": new_pkg_tier,
        }
    except Exception as ex:
        logger.error(f"Failed to apply dismiss score credit: {ex}")
        return {"new_sqs_score": None, "new_package_sqs_score": None}


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

    # Credit the score_impact back when the producer provides a real override
    # reason (typed text, not the default sentinel).  Plain "Dismiss" with no
    # reason intentionally does NOT credit the score — the card is hidden but
    # the gap remains on record.
    credit: dict = {}
    if (
        success
        and req.override_reason
        and req.override_reason != "No reason provided"
        and req.score_impact is not None
        and req.score_impact > 0
        and req.form_id
    ):
        credit = await _apply_dismiss_score_credit(
            session_id=req.session_id,
            form_id=req.form_id,
            score_at_action=req.sqs_score_at_action,
            score_impact=req.score_impact,
        )

    return JSONResponse({
        "success": success,
        "new_sqs_score": credit.get("new_sqs_score"),
        "new_package_sqs_score": credit.get("new_package_sqs_score"),
        "new_grade": credit.get("new_grade"),
        "new_tier": credit.get("new_tier"),
        "new_tier_color": credit.get("new_tier_color"),
        "new_package_tier": credit.get("new_package_tier"),
    })


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


@router.get("/api/audit/dismissed/{session_id}")
async def get_dismissed_recs(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)
    recs = await get_dismissed_recommendations(session_id)
    return JSONResponse({"success": True, "dismissed_recommendations": recs, "count": len(recs)})


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
