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


def _cap_from(hard_count: int, soft_count: int) -> int:
    """Max SQS allowed given active stop counts (mirrors the scorer cap gates).

    Any active hard stop -> 60, else any active soft stop -> 85, else no cap (100).
    Per the SQS design the per-form scorer is fed FIELD-LEVEL stops only while the
    package scorer is fed field-level + cross-form stops, so callers pass the count
    appropriate to the scope they are capping (see _apply_dismiss_score_credit).
    """
    if hard_count > 0:
        return 60
    if soft_count > 0:
        return 85
    return 100


def _credited_score(base: int, impact: int, cap: int) -> int:
    """Apply a recommendation/ARQ point credit as a CEILING, never a floor.

    The score rises by `impact` from its OWN current `base`, bounded at 100 and at
    the active-stop ceiling `cap` (60 hard / 85 soft / 100 none). The cap only binds
    when base+impact would EXCEED it:
      * a score already below the cap keeps its own value - it is never raised to
        the cap (e.g. 22 + 8 = 30 stays 30 under a hard stop, not 60);
      * a score that crosses the cap is clamped to it (e.g. 56 + 8 = 64 -> 60);
      * scores that do not each cross the cap stay distinct - they never collapse
        onto a shared 60/85.
    Each form and the package are credited independently with this same rule, so a
    submission-wide hard stop no longer drags every score onto 60.
    """
    return min(min(100, base + impact), cap)


async def _apply_dismiss_score_credit(
    session_id: str,
    rec_id: str,
    score_at_action: int,
    score_impact: int,
) -> dict:
    """Credit +score_impact to every form that carries rec_id plus the package.

    Scope rules:
    - Forms affected: all generated forms whose SQS recommendations list contains
      this rec_id. A recommendation that appears in two forms (same field gap,
      e.g. applicant_name missing in both ACORD 125 and ACORD 130) credits both.
      A recommendation that appears in only one form credits only that form.
    - Package: always credited with the same +score_impact, starting from its own
      independently-computed baseline (not an average of the form scores).
    - If no form contains this rec_id (package-level or cross-form issue), only
      the package is credited and all form scores are left untouched.

    Capping (mirrors the scorer cap gates - hard stop -> 60, soft stop -> 85):
    the per-form ceiling and the package ceiling are computed from DIFFERENT stop
    scopes, exactly like the scorers do, and that distinction is what keeps the two
    scores independent:
      * per-form cap uses FIELD-LEVEL stops only (calculate_sqs ignores cross-form
        stops for individual forms);
      * package cap uses field-level + cross-form stops (calculate_package_sqs).
    Applying one combined cap to both - the prior bug - dragged every form down to
    the package's cross-form ceiling (e.g. a cross-form hard stop pinned all forms
    AND the package to 60), making them collapse to the same value. The session
    stores COMBINED stops (field + cross) in hard_stops/soft_stops plus the cross
    issues in cross_issues_last, so field-level counts are the combined counts minus
    the cross counts.
    """
    try:
        async with get_pool().acquire() as conn:
            # Active-stop counts. hard_stops/soft_stops are COMBINED (field+cross);
            # cross_issues_last carries the cross-form issues (type hard_stop /
            # soft_warning). Field-level = combined - cross.
            stop_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(jsonb_array_length(data->'hard_stops'), 0) AS hard_total,
                    COALESCE(jsonb_array_length(data->'soft_stops'), 0) AS soft_total,
                    COALESCE((
                        SELECT count(*) FROM jsonb_array_elements(
                            COALESCE(data->'cross_issues_last', '[]'::jsonb)) e
                        WHERE e->>'type' = 'hard_stop'
                    ), 0) AS hard_cross,
                    COALESCE((
                        SELECT count(*) FROM jsonb_array_elements(
                            COALESCE(data->'cross_issues_last', '[]'::jsonb)) e
                        WHERE e->>'type' = 'soft_warning'
                    ), 0) AS soft_cross
                FROM processing_sessions
                WHERE id = $1
                """,
                session_id,
            )
            hard_total = (stop_row["hard_total"] if stop_row else 0) or 0
            soft_total = (stop_row["soft_total"] if stop_row else 0) or 0
            hard_cross = (stop_row["hard_cross"] if stop_row else 0) or 0
            soft_cross = (stop_row["soft_cross"] if stop_row else 0) or 0

            # Per-form ceiling: field-level stops only (exclude cross-form).
            form_cap = _cap_from(max(0, hard_total - hard_cross),
                                 max(0, soft_total - soft_cross))
            # Package ceiling: field-level + cross-form (the combined totals).
            pkg_cap  = _cap_from(hard_total, soft_total)

            # Find every form that has this rec_id in its recommendations list.
            affected_rows = await conn.fetch(
                """
                SELECT ge.key AS form_id,
                       (ge.value->'sqs'->>'sqs_score')::int AS score
                FROM processing_sessions ps,
                     jsonb_each(COALESCE(ps.data->'generated_forms', '{}'::jsonb)) AS ge
                WHERE ps.id = $1
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(
                               COALESCE(ge.value->'sqs'->'recommendations', '[]'::jsonb)
                           ) AS r
                      WHERE r->>'rec_id' = $2
                  )
                """,
                session_id, rec_id,
            )

            # Credit package from its own independent baseline.
            existing_pkg = await conn.fetchval(
                "SELECT (data->'package_sqs'->>'package_sqs_score')::int "
                "FROM processing_sessions WHERE id = $1",
                session_id,
            )
            pkg_base      = existing_pkg if existing_pkg is not None else score_at_action
            new_pkg_score = _credited_score(pkg_base, score_impact, pkg_cap)
            _, new_pkg_tier, _ = _grade_from_score(new_pkg_score)

            # Build per-form updates: bump each affected form independently.
            updated_forms: dict = {}
            now_ts = datetime.now(timezone.utc).isoformat()

            for row in affected_rows:
                fid        = row["form_id"]
                base_score = row["score"] if row["score"] is not None else score_at_action
                new_score  = _credited_score(base_score, score_impact, form_cap)
                new_grade, new_tier, new_tier_color = _grade_from_score(new_score)

                await conn.execute(
                    """
                    UPDATE processing_sessions
                    SET data = jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    data,
                                    ARRAY['generated_forms', $1, 'sqs', 'sqs_score'],
                                    to_jsonb($2::int), false
                                ),
                                ARRAY['generated_forms', $1, 'sqs', 'grade'],
                                to_jsonb($3::text), false
                            ),
                            ARRAY['generated_forms', $1, 'sqs', 'tier'],
                            to_jsonb($4::text), false
                        ),
                        ARRAY['generated_forms', $1, 'sqs', 'tier_color'],
                        to_jsonb($5::text), false
                    ),
                    updated_at = $6
                    WHERE id = $7
                    """,
                    fid, new_score, new_grade, new_tier, new_tier_color,
                    now_ts, session_id,
                )
                updated_forms[fid] = {
                    "new_sqs_score":  new_score,
                    "new_grade":      new_grade,
                    "new_tier":       new_tier,
                    "new_tier_color": new_tier_color,
                }

            # Always update the package score.
            await conn.execute(
                """
                UPDATE processing_sessions
                SET data = jsonb_set(
                    jsonb_set(
                        data,
                        ARRAY['package_sqs', 'package_sqs_score'],
                        to_jsonb($1::int), false
                    ),
                    ARRAY['package_sqs', 'tier'],
                    to_jsonb($2::text), false
                ),
                updated_at = $3
                WHERE id = $4
                """,
                new_pkg_score, new_pkg_tier, now_ts, session_id,
            )

        logger.info(
            f"Dismiss credit applied: session={session_id} rec={rec_id} "
            f"forms_credited={list(updated_forms.keys())} (form_cap={form_cap}) "
            f"pkg({pkg_base}+{score_impact}->{new_pkg_score} pkg_cap={pkg_cap})"
        )
        return {
            "updated_forms":        updated_forms,
            "new_package_sqs_score": new_pkg_score,
            "new_package_tier":      new_pkg_tier,
        }
    except Exception as ex:
        logger.error(f"Failed to apply dismiss score credit: {ex}")
        return {"updated_forms": {}, "new_package_sqs_score": None}


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
    ):
        credit = await _apply_dismiss_score_credit(
            session_id=req.session_id,
            rec_id=req.rec_id,
            score_at_action=req.sqs_score_at_action,
            score_impact=req.score_impact,
        )

    return JSONResponse({
        "success":               success,
        "updated_forms":         credit.get("updated_forms", {}),
        "new_package_sqs_score": credit.get("new_package_sqs_score"),
        "new_package_tier":      credit.get("new_package_tier"),
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
