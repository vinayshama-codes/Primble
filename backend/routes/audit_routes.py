import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from config.database import get_pool
from models.schemas import (
    DismissRecommendationRequest,
    ResolveRecommendationRequest,
    AnswerRecommendationRequest,
    ReopenRecommendationRequest,
    ResolveIssueRequest,
    ReopenIssueRequest,
    DownloadAnywayRequest,
    IssueStatusRequest,
)
from repositories.session_repository import get_processing_session
from services.audit_service import (
    get_open_recommendations,
    get_dismissed_recommendations,
    get_reviewed_recommendations,
    get_recommendation_audit_row,
    get_audit_summary,
    mark_recommendation_dismissed,
    mark_recommendation_resolved,
    mark_recommendation_answer_recorded,
    reopen_recommendation as _reopen_recommendation_row,
    log_download_with_open_recs,
    log_field_change,
    get_marketing_reason,
    set_issue_status,
    get_issue_statuses,
    get_audit_trail_export,
)
from services.auth_service import get_current_user
from services.sqs_service import SQS_MODEL_VERSION, generate_sqs_narrative
from config.settings import ENABLE_PRODUCER_ANSWERS

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


def _dismiss_earned_credit(override_reason, score_impact) -> bool:
    """Did this dismissal earn a score credit?

    A plain "Dismiss" with no reason intentionally hides the card without crediting
    the score - the gap remains on record. Only a real typed reason (not the default
    sentinel) with a positive impact credits.

    Single source of truth on purpose: the dismiss route uses it to decide whether to
    APPLY a credit and the reopen path uses it to decide whether to REVERSE and replay
    one. If the two predicates ever drifted, scores would silently mis-restore.
    """
    return (
        override_reason not in (None, "", "No reason provided")
        and score_impact is not None
        and score_impact > 0
    )


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
    if success and _dismiss_earned_credit(req.override_reason, req.score_impact):
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


def _validate_producer_answer(field: str, answer: str) -> tuple:
    """Lightweight type validation for a producer-entered recommendation answer.

    Returns (ok, error_message). Monetary / percentage / date fields (detected by
    the canonical field name) must parse via the existing field validators;
    everything else is treated as free text and only needs to be non-empty and of
    reasonable length. Deliberately lenient - the validators strip formatting like
    "$" and "," - so a real value is never rejected, only genuine garbage is.
    """
    from utils.validators import (
        validate_monetary, validate_percent, validate_date_format,
    )
    text = (answer or "").strip()
    if not text:
        return False, "Please enter an answer."
    if len(text) > 2000:
        return False, "Answer is too long."
    f = (field or "").lower()
    if any(t in f for t in ("percent", "pct", "coinsurance", "itv")):
        ok, msg = validate_percent(text, "Percentage")
        return (True, "") if ok else (False, msg)
    if any(t in f for t in ("date", "effective", "expiration", "retro")):
        ok, msg = validate_date_format(text, "Date")
        return (True, "") if ok else (False, msg)
    if any(t in f for t in ("limit", "value", "payroll", "revenue", "premium",
                            "amount", "deductible", "income", "receipts", "sales")):
        ok, msg = validate_monetary(text, "Amount")
        return (True, "") if ok else (False, msg)
    return True, ""


@router.post("/api/audit/answer")
async def answer_recommendation(
    req: AnswerRecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    """Producer-entered answer to a recommendation card (Fig 13).

    Validates the typed value, writes it into the session as a producer-provenance
    fact, re-runs the SQS / cross-form rules, and returns the before/after impact
    plus the recomputed per-form scores. The dismiss/waiver path is untouched.
    """
    await _verify_session_owner(req.session_id, current_user)
    if not ENABLE_PRODUCER_ANSWERS:
        return JSONResponse({
            "success": False, "disabled": True,
            "message": "Producer answers are disabled.",
        })

    ok, err = _validate_producer_answer(req.field, req.answer)
    if not ok:
        return JSONResponse({"success": False, "validation_error": err})

    from services.arq_service import (
        apply_producer_answer_to_session, recalculate_session_scores,
    )
    applied, _updated = await apply_producer_answer_to_session(
        req.session_id, req.field, req.answer,
    )
    if not applied:
        return JSONResponse({
            "success": False,
            "message": "This item can't be answered directly. Attach a supporting "
                       "document or dismiss it with a note.",
        })

    # Record the typed value BEFORE the recalculation. The recalculation's
    # auto-resolve pass may stamp action='resolved', and this writer is latched on
    # `action IS NULL` - recording afterwards would silently no-op and the answer
    # would never be persisted. It deliberately does not set `action` itself; see
    # mark_recommendation_answer_recorded.
    try:
        await mark_recommendation_answer_recorded(
            session_id=req.session_id,
            rec_id=req.rec_id,
            producer_answer=str(req.answer).strip(),
            model_version=SQS_MODEL_VERSION,
            field=req.field,
            message=req.message,
            score_impact=req.score_impact,
            user_id=str(current_user["id"]),
            form_id=req.form_id,
        )
    except Exception as _ae:
        logger.warning(f"answer_recommendation: answer record failed: {_ae}")

    try:
        await log_field_change(
            session_id=req.session_id,
            user_id=str(current_user["id"]),
            form_id=req.form_id,
            field_name=req.field,
            fact_key=req.field,
            source="producer",
            previous_value=None,
            new_value=str(req.answer).strip(),
            confidence="filled",
            model_version=SQS_MODEL_VERSION,
        )
    except Exception as _le:
        logger.warning(f"answer_recommendation: audit log failed: {_le}")

    impact = await recalculate_session_scores(req.session_id)

    # Read back the recomputed per-form scores so the UI can update each form tile,
    # in the same {new_sqs_score/new_grade/new_tier/new_tier_color} shape the
    # dismiss-credit path returns. Grade/tier/color are derived here (not read from
    # the sqs dict) so they always agree with _grade_from_score, exactly like the
    # dismiss path.
    updated_forms: dict = {}
    try:
        sess = await get_processing_session(req.session_id)
        for fid, fdata in (sess.get("generated_forms") or {}).items():
            if not isinstance(fdata, dict):
                continue
            score = (fdata.get("sqs") or {}).get("sqs_score")
            if score is None:
                continue
            g, t, c = _grade_from_score(int(score))
            updated_forms[fid] = {
                "new_sqs_score":  int(score),
                "new_grade":      g,
                "new_tier":       t,
                "new_tier_color": c,
            }
    except Exception as _re:
        logger.error(f"answer_recommendation: score read-back failed: {_re}")

    open_recs = await get_open_recommendations(req.session_id)

    return JSONResponse({
        "success":               True,
        "impact":                impact,
        "updated_forms":         updated_forms,
        "new_package_sqs_score": impact.get("score_after"),
        "new_package_tier":      impact.get("tier"),
        "open_recommendations":  open_recs,
    })


async def _reapply_dismiss_credits(session_id: str, exclude_rec_id: str) -> None:
    """Re-apply the score credit of every STILL-dismissed recommendation, except one.

    recalculate_session_scores replaces each form's `sqs` dict wholesale, and the
    dismiss credits were written destructively into that dict with no baseline stored
    anywhere. So any recalculation silently erases every outstanding credit. Before
    reopen that was rare; reopen would make it routine - dismissing three recs
    (+8, +12, +5) and reopening the +8 one would drop the score by all 25.

    Replaying is safe because _credited_score compounds from whatever the current base
    is, so applying the surviving dismissals in their original order reproduces the
    same sequence of credits. The reopened rec is already action=NULL (or is excluded
    here), so it can never be double-credited.
    """
    try:
        for row in await get_dismissed_recommendations(session_id):
            if row.get("rec_id") == exclude_rec_id:
                continue
            if not _dismiss_earned_credit(row.get("override_reason"), row.get("score_impact")):
                continue
            await _apply_dismiss_score_credit(
                session_id=session_id,
                rec_id=row["rec_id"],
                # Only a fallback for a NULL stored score. The recalculation that just
                # ran always writes live per-form and package scores, so the real base
                # is read from the session and this value is never reached.
                score_at_action=0,
                score_impact=int(row["score_impact"]),
            )
    except Exception as ex:
        logger.error(f"_reapply_dismiss_credits failed for {session_id}: {ex}")


async def _forms_payload_with_recs(session_id: str) -> tuple:
    """(updated_forms, package_score, package_tier) read back from the session.

    Same {new_sqs_score/new_grade/new_tier/new_tier_color} shape the dismiss and
    answer paths already return, plus each form's recommendations so the panel can
    restore its open card list without guessing which recs came back.
    """
    updated_forms: dict = {}
    pkg_score = None
    pkg_tier = None
    try:
        sess = await get_processing_session(session_id)
        for fid, fdata in (sess.get("generated_forms") or {}).items():
            if not isinstance(fdata, dict):
                continue
            sqs = fdata.get("sqs") or {}
            score = sqs.get("sqs_score")
            if score is None:
                continue
            g, t, c = _grade_from_score(int(score))
            updated_forms[fid] = {
                "new_sqs_score":   int(score),
                "new_grade":       g,
                "new_tier":        t,
                "new_tier_color":  c,
                "recommendations": sqs.get("recommendations") or [],
            }
        pkg = sess.get("package_sqs") or {}
        pkg_score = pkg.get("package_sqs_score")
        if pkg_score is not None:
            pkg_score = int(pkg_score)
            pkg_tier = _grade_from_score(pkg_score)[1]
    except Exception as ex:
        logger.error(f"_forms_payload_with_recs failed for {session_id}: {ex}")
    return updated_forms, pkg_score, pkg_tier


@router.post("/api/audit/reopen-recommendation")
async def reopen_recommendation(
    req: ReopenRecommendationRequest,
    current_user: dict = Depends(get_current_user),
):
    """Reopen a dismissed or producer-answered recommendation from "Reviewed".

    Undoes whatever that review actually did:
      * answered -> retracts the producer-provenance fact and blanks it on every form
        it was stamped into, so the gap and the score genuinely come back;
      * dismissed-with-a-reason -> reverses the score credit by rescoring from facts
        (no pre-credit baseline is stored, so a rescore is the only honest restore),
        then replays the OTHER dismissals' credits;
      * dismissed without a reason -> nothing was written and nothing was credited, so
        no rescore is needed at all.

    `override_reason` / `producer_answer` are preserved throughout - see
    audit_service.reopen_recommendation.
    """
    await _verify_session_owner(req.session_id, current_user)

    row = await get_recommendation_audit_row(req.session_id, req.rec_id)
    if not row:
        raise HTTPException(404, "Recommendation not found")

    was_answered = row.get("action") == "resolved" and row.get("producer_answer") is not None
    credit_applied = _dismiss_earned_credit(row.get("override_reason"), row.get("score_impact"))

    cleared = False
    if was_answered and row.get("field"):
        from services.arq_service import clear_producer_answer_from_session
        try:
            cleared, _ = await clear_producer_answer_from_session(
                req.session_id, row["field"],
            )
        except Exception as ex:
            logger.error(f"reopen_recommendation: clear failed for {row.get('field')}: {ex}")

    if cleared or credit_applied:
        from services.arq_service import recalculate_session_scores
        await recalculate_session_scores(req.session_id)
        await _reapply_dismiss_credits(req.session_id, exclude_rec_id=req.rec_id)

    # Only reopen the audit row if the gap actually came back. Several recs are
    # satisfied by a COMBINATION of facts (rec_gl_class_codes, rec_min_cope,
    # rec_auto_vin_schedule), so retracting one value may leave the rec legitimately
    # closed. Nulling `action` regardless would create a row that is open to
    # get_unresolved_recommendations - and so blocks the download preflight forever -
    # while rendering nowhere in the panel, leaving the producer no way to clear it.
    updated_forms, pkg_score, pkg_tier = await _forms_payload_with_recs(req.session_id)
    active_rec_ids = {
        r.get("rec_id")
        for f in updated_forms.values()
        for r in f.get("recommendations") or []
        if isinstance(r, dict)
    }

    reopened = req.rec_id in active_rec_ids
    if reopened:
        # Nulled LAST, deliberately: recalculate_session_scores' auto-resolve pass only
        # touches rows with action IS NULL, so clearing it earlier would let that pass
        # immediately re-stamp 'resolved' and defeat the reopen.
        await _reopen_recommendation_row(req.session_id, req.rec_id)

    return JSONResponse({
        "success":               True,
        "reopened":              reopened,
        "cleared":               cleared,
        "previous_answer":       row.get("producer_answer"),
        "previous_reason":       row.get("override_reason"),
        "updated_forms":         updated_forms,
        "new_package_sqs_score": pkg_score,
        "new_package_tier":      pkg_tier,
    })


@router.get("/api/audit/reviewed/{session_id}")
async def get_reviewed(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Recommendations the producer has dismissed or answered - the "Reviewed"
    section of the SQS panel. Distinct from /api/audit/dismissed/, which stays
    dismissals-only because it backs the E&O audit-trail export."""
    await _verify_session_owner(session_id, current_user)
    rows = await get_reviewed_recommendations(session_id)
    return JSONResponse({
        "success":                  True,
        "reviewed_recommendations": rows,
        "count":                    len(rows),
    })


def _grouped_cross_issues_for_panel(cross_issues: list):
    """Cluster + tier a raw cross_form_validator issue list for the SQS panel.

    Same shape the editor's Cross-Form Validation panel already consumes
    (form_routes._grouped_cross_issues_or_none): each cluster/item carries the
    inline `resolution` descriptor, attached centrally in issue_registry, so the
    panel can re-render its Open-to-fix affordance after a resolution is applied.
    """
    try:
        from services.issue_registry import (
            build_grouped_view, build_structured_from_sources, normalize_issue_type,
        )
        _typed = [(normalize_issue_type(i.get("type")), i.get("message", ""))
                  for i in (cross_issues or []) if isinstance(i, dict)]
        return build_grouped_view(
            build_structured_from_sources(cross_issues=cross_issues, include_advisories=True),
            [m for t, m in _typed if t == "hard_stop"],
            [m for t, m in _typed if t == "soft_warning"],
        )
    except Exception as _gx:
        logger.error(f"resolve_issue: grouped view computation failed (non-fatal): {_gx}")
        return None


@router.post("/api/audit/resolve-issue")
async def resolve_issue(
    req: ResolveIssueRequest,
    current_user: dict = Depends(get_current_user),
):
    """Resolve a Cross-Form Validation issue inline (SQS panel "Open" -> fix).

    Writes the producer's input into the session facts through the SAME paths the
    recommendation-answer and producer-schedule flows already use (so provenance,
    form re-stamping and the audit trail are identical), re-runs the SQS /
    cross-form rules, and returns the recomputed per-form scores plus a freshly
    grouped cross-issue view so the panel updates in place. The dismiss/answer
    endpoints are untouched.

      mode=field     -> apply a canonical scalar fact (producer answer path)
      mode=narrative -> append an ACORD 101 explanation (additional_remarks_text)
      mode=schedule  -> save an edited repeating schedule (producer schedule path)
    """
    await _verify_session_owner(req.session_id, current_user)
    if not ENABLE_PRODUCER_ANSWERS:
        return JSONResponse({
            "success": False, "disabled": True,
            "message": "Inline issue resolution is disabled.",
        })

    from services.arq_service import (
        apply_producer_answer_to_session, save_session_schedule,
        recalculate_session_scores,
    )

    mode = (req.mode or "").strip()
    applied = False
    _log_field: str = ""
    _log_value: str = ""

    if mode == "field":
        field = (req.field or "").strip()
        value = (req.value or "").strip()
        if not field or not value:
            return JSONResponse({"success": False, "message": "Enter a value to apply."})
        ok, err = _validate_producer_answer(field, value)
        if not ok:
            return JSONResponse({"success": False, "validation_error": err})
        applied, _ = await apply_producer_answer_to_session(req.session_id, field, value)
        if not applied:
            return JSONResponse({
                "success": False,
                "message": "This value can't be applied directly. Attach a "
                           "supporting document or dismiss it with a note.",
            })
        _log_field, _log_value = field, value

    elif mode == "narrative":
        text = (req.text or "").strip()
        if not text:
            return JSONResponse({"success": False, "message": "Enter an explanation to apply."})
        if len(text) > 4000:
            return JSONResponse({"success": False, "message": "Explanation is too long."})
        # Append to any existing ACORD 101 remarks rather than overwrite, so
        # explanations for different issues coexist instead of clobbering.
        try:
            _proc = await get_processing_session(req.session_id)
            _existing = (_proc.get("facts") or {}).get("additional_remarks_text")
            _existing_val = _existing.get("value") if isinstance(_existing, dict) else _existing
            _existing_val = str(_existing_val or "").strip()
        except Exception:
            _existing_val = ""
        if _existing_val and text not in _existing_val:
            combined = f"{_existing_val}\n{text}".strip()
        elif not _existing_val:
            combined = text
        else:
            combined = _existing_val
        applied, _ = await apply_producer_answer_to_session(
            req.session_id, "additional_remarks_text", combined,
        )
        if not applied:
            return JSONResponse({"success": False, "message": "Could not save the explanation."})
        _log_field, _log_value = "additional_remarks_text", text

    elif mode == "schedule":
        from services import schedule_capture
        list_key = (req.schedule_key or "").strip()
        rows = req.rows if isinstance(req.rows, list) else []
        if schedule_capture.get_def(list_key) is None:
            return JSONResponse({"success": False, "message": "Unknown schedule."})
        if len(rows) > schedule_capture.MAX_ROWS:
            return JSONResponse({
                "success": False,
                "message": f"Too many rows (max {schedule_capture.MAX_ROWS}).",
            })
        ok, result = await save_session_schedule(req.session_id, list_key, rows)
        if not ok:
            return JSONResponse({"success": False, "message": result.get("message", "Could not save schedule.")})
        applied = True

    else:
        return JSONResponse({
            "success": False,
            "message": "This item can't be resolved inline - use Resolve or Dismiss.",
        })

    if _log_field:
        try:
            await log_field_change(
                session_id=req.session_id, user_id=str(current_user["id"]),
                form_id=req.form_id, field_name=_log_field, fact_key=_log_field,
                source="producer", previous_value=None, new_value=str(_log_value)[:2000],
                confidence="filled", model_version=SQS_MODEL_VERSION,
            )
        except Exception as _le:
            logger.warning(f"resolve_issue: audit log failed: {_le}")

    # Re-run field + cross-form rules and per-form / package SQS from updated facts.
    impact = await recalculate_session_scores(req.session_id)
    if not isinstance(impact, dict):
        impact = {}

    # Read back the recomputed session for the panel: per-form scores (same shape
    # as the dismiss-credit / answer paths), fresh cross issues + grouped view,
    # and the final stop lists.
    sess = await get_processing_session(req.session_id)
    updated_forms: dict = {}
    try:
        for fid, fdata in (sess.get("generated_forms") or {}).items():
            if not isinstance(fdata, dict):
                continue
            score = (fdata.get("sqs") or {}).get("sqs_score")
            if score is None:
                continue
            g, t, c = _grade_from_score(int(score))
            updated_forms[fid] = {
                "new_sqs_score":  int(score),
                "new_grade":      g,
                "new_tier":       t,
                "new_tier_color": c,
            }
    except Exception as _re:
        logger.error(f"resolve_issue: score read-back failed: {_re}")

    cross_issues = sess.get("cross_issues_last") or []
    package_sqs  = sess.get("package_sqs") or {}

    # Form-selection (recommendations-step) view: the classified hard/soft split +
    # grouped_issues that the confirm-value / marketing-reason routes return, so an
    # inline resolution opened from the Select Forms banners refreshes them in place
    # just like the editor's Cross-Form panel does via grouped_cross_issues above.
    # The hard/soft lists here are the SAME stored lists, now classify_stops-
    # processed (a hard stop that downgrades for a non-property submission is shown
    # as a warning, matching every other Select Forms response). Best-effort: a
    # display-computation failure must never fail the resolve that already
    # succeeded server-side, so we fall back to the raw stored lists.
    _fs_hard = sess.get("hard_stops") or []
    _fs_soft = sess.get("soft_stops") or []
    _fs_grouped = None
    _can_proceed_warn = False
    _warning_stops: list = []
    try:
        from services.sqs_service import classify_stops
        from services.issue_registry import build_grouped_view
        _can_proceed_warn, _fs_hard, _warning_stops = classify_stops(
            sess.get("hard_stops") or [], sess.get("flags") or {}
        )
        _fs_soft = list(sess.get("soft_stops") or []) + list(_warning_stops)
        _fs_grouped = build_grouped_view(
            sess.get("structured_issues") or [],
            _fs_hard, _fs_soft,
            cross_issues=cross_issues,
        )
    except Exception as _fgx:
        logger.error(f"resolve_issue: form-selection grouped view failed (non-fatal): {_fgx}")
        _fs_hard = sess.get("hard_stops") or []
        _fs_soft = sess.get("soft_stops") or []

    return JSONResponse({
        "success":               True,
        "applied":               applied,
        "updated_forms":         updated_forms,
        "new_package_sqs_score": package_sqs.get("package_sqs_score", impact.get("score_after")),
        "new_package_tier":      package_sqs.get("tier") or impact.get("tier"),
        "cross_issues":          cross_issues,
        "grouped_cross_issues":  _grouped_cross_issues_for_panel(cross_issues),
        "hard_stops":            _fs_hard,
        "soft_stops":            _fs_soft,
        # New (form-selection banners). The editor panel ignores these.
        "grouped_issues":           _fs_grouped,
        "can_proceed_with_warning": _can_proceed_warn,
        "warning_stops":            _warning_stops,
    })


@router.get("/api/audit/issue-values/{session_id}")
async def issue_values(
    session_id: str,
    facts: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Current session values for a set of canonical facts (SQS panel modal).

    Lets the inline-resolution modal PRE-FILL its inputs with whatever is already
    on record, so reopening a validation shows the value the producer previously
    applied instead of a blank box. Read-only; owner-gated; returns the producer's
    own form data (nothing they can't already see on the forms).
    """
    await _verify_session_owner(session_id, current_user)
    try:
        proc = await get_processing_session(session_id)
    except Exception:
        return JSONResponse({"success": False, "values": {}})
    sess_facts = proc.get("facts") or {}

    def _scalar(key: str) -> str:
        v = sess_facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        if v is None or isinstance(v, (list, dict)):
            return ""
        return str(v)

    keys = [f.strip() for f in (facts or "").split(",") if f.strip()]
    return JSONResponse({"success": True, "values": {k: _scalar(k) for k in keys}})


@router.post("/api/audit/reopen-issue")
async def reopen_issue(
    req: ReopenIssueRequest,
    current_user: dict = Depends(get_current_user),
):
    """Reopen a Cross-Form Validation issue (SQS panel "Reopen").

    For a `field`-mode issue this UNDOES the inline fix: deletes the
    producer-provenance fact(s) resolve-issue wrote and blanks them on every
    form they were stamped into, then re-runs the rules - so Reopen genuinely
    restores the "needs input" state instead of leaving the old answer sitting
    on the form while the panel claims the issue is open again.

    Schedule/narrative-mode issues (and anything with no resolution) are
    deliberately NOT auto-cleared here:
      - a schedule can be shared by several validations (e.g. two location
        checks both point at `property_locations`) - clearing it because ONE
        was reopened could destroy rows a DIFFERENT still-resolved issue
        depends on. Editing an existing schedule is already fully supported
        via "Open to fix", which loads the current rows for editing.
      - a narrative note is appended into ONE shared ACORD 101 remarks fact -
        surgically removing just one issue's sentence out of that blob isn't
        something that can be done safely/unambiguously.
    Those two modes (and `none`) just flip the status marker, exactly as
    Resolve/Dismiss already do.
    """
    await _verify_session_owner(req.session_id, current_user)

    from services.issue_registry import resolution_for
    from services.arq_service import (
        clear_producer_answer_from_session, recalculate_session_scores,
    )

    resolution = resolution_for(req.code)
    cleared_any = False
    if resolution and resolution.get("mode") == "field":
        for fact in resolution.get("facts") or []:
            ok, _ = await clear_producer_answer_from_session(req.session_id, fact)
            cleared_any = cleared_any or ok

    if req.issue_id:
        await set_issue_status(
            session_id=req.session_id, issue_id=req.issue_id, status="open",
            user_id=str(current_user["id"]), form_id=req.form_id,
            rule_code=req.code, message=req.message,
        )

    if not cleared_any:
        # Nothing on any form actually changed - a plain status-only reopen,
        # same as Resolve/Dismiss have always been.
        return JSONResponse({"success": True, "cleared": False})

    await recalculate_session_scores(req.session_id)
    sess = await get_processing_session(req.session_id)

    updated_forms: dict = {}
    try:
        for fid, fdata in (sess.get("generated_forms") or {}).items():
            if not isinstance(fdata, dict):
                continue
            score = (fdata.get("sqs") or {}).get("sqs_score")
            if score is None:
                continue
            g, t, c = _grade_from_score(int(score))
            updated_forms[fid] = {
                "new_sqs_score":  int(score),
                "new_grade":      g,
                "new_tier":       t,
                "new_tier_color": c,
            }
    except Exception as _re:
        logger.error(f"reopen_issue: score read-back failed: {_re}")

    cross_issues = sess.get("cross_issues_last") or []
    package_sqs  = sess.get("package_sqs") or {}

    return JSONResponse({
        "success":               True,
        "cleared":               True,
        "updated_forms":         updated_forms,
        "new_package_sqs_score": package_sqs.get("package_sqs_score"),
        "new_package_tier":      package_sqs.get("tier"),
        "cross_issues":          cross_issues,
        "grouped_cross_issues":  _grouped_cross_issues_for_panel(cross_issues),
        "hard_stops":            sess.get("hard_stops") or [],
        "soft_stops":            sess.get("soft_stops") or [],
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
    # include_acknowledged: EVERY still-unresolved item (contamination warnings,
    # field-QA items, and SQS recs) re-appears on the pre-download modal and the
    # post-download checklist on EVERY download, any number of times, until it is
    # actually fixed (resolved) or explicitly dismissed. A prior "Download Anyway"
    # acknowledges but does not suppress. This route is the sole feeder of the
    # download preflight (frontend AcordModal), so the change is scoped to the
    # download flow; the non-download callers of get_open_recommendations keep the
    # default (action IS NULL) behavior.
    recs = await get_open_recommendations(session_id, include_acknowledged=True)
    return JSONResponse({"success": True, "open_recommendations": recs, "count": len(recs)})


# ── Issue-rail resolution status (pure work-tracking, no SQS scoring) ───────────
_ISSUE_STATUS_VALUES = {"open", "resolved", "dismissed"}


@router.post("/api/issues/status")
async def set_issue_status_route(
    req: IssueStatusRequest,
    current_user: dict = Depends(get_current_user),
):
    """Record a broker's resolution status for one rail issue.

    Intentionally isolated from the recommendation dismiss/resolve endpoints:
    it never runs SQS scoring or dismiss-credit logic, so hard-stop / cross-form
    acknowledgments stay a display-only work-tracking marker.
    """
    await _verify_session_owner(req.session_id, current_user)
    status = (req.status or "").strip().lower()
    if status not in _ISSUE_STATUS_VALUES:
        raise HTTPException(422, "Invalid status")
    ok = await set_issue_status(
        session_id=req.session_id,
        issue_id=req.issue_id,
        status=status,
        reason=req.reason,
        user_id=str(current_user["id"]),
        form_id=req.form_id,
        field=req.field,
        rule_code=req.rule_code,
        source_fact=req.source_fact,
        message=req.message,
    )
    return JSONResponse({"success": ok, "issue_id": req.issue_id, "status": status})


@router.get("/api/issues/status/{session_id}")
async def get_issue_statuses_route(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)
    statuses = await get_issue_statuses(session_id)
    return JSONResponse({"success": True, "issue_statuses": statuses})


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


@router.get("/api/audit/marketing-reason/{session_id}")
async def get_marketing_reason_audit(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Figure 6: surface the producer's "Why are you marketing this account?"
    answer (controlled reason_code + free-text reason_note) for underwriter /
    internal review, independent of the processing_sessions JSON blob."""
    await _verify_session_owner(session_id, current_user)
    reason = await get_marketing_reason(session_id)
    return JSONResponse({"success": True, "marketing_reason": reason})


@router.get("/api/audit/summary/{session_id}")
async def audit_summary(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _verify_session_owner(session_id, current_user)
    summary = await get_audit_summary(session_id)
    return JSONResponse({"success": True, **summary})


@router.get("/api/audit/export/{session_id}")
async def export_audit_trail(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """E&O audit record: the package-level marketing reason plus every
    individual dismissed-recommendation / issue-status / download-anyway
    reason on this submission, bundled for the producer to download for their
    own records. Per client clarification (Figure 6, 2026-07-17): this is not
    pushed to underwriters - it only needs to be available on demand to the
    user who owns the session."""
    await _verify_session_owner(session_id, current_user)
    export = await get_audit_trail_export(session_id)
    return JSONResponse({"success": True, **export})


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
