# audit_service.py — asyncpg implementation

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from models.schemas import (
    SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS,
    DOWNLOAD_AUDIT_STATEMENTS, SUBMISSION_INTEGRITY_AUDIT_STATEMENTS,
    UNDERWRITING_CONFIRMATION_AUDIT_STATEMENTS,
)

logger = logging.getLogger(__name__)


# ASYNC-SAFE
async def init_audit_tables() -> None:
    """Create audit tables if they don't exist. Called from main.py startup."""
    async with get_pool().acquire() as conn:
        for stmt in (
            SQS_RECOMMENDATION_AUDIT_STATEMENTS
            + FIELD_SOURCE_AUDIT_STATEMENTS
            + DOWNLOAD_AUDIT_STATEMENTS
            + SUBMISSION_INTEGRITY_AUDIT_STATEMENTS
            + UNDERWRITING_CONFIRMATION_AUDIT_STATEMENTS
        ):
            try:
                await conn.execute(stmt)
            except Exception as ex:
                logger.warning(f"Audit table statement skipped (likely already exists): {ex}")
    logger.info("Audit tables ready (asyncpg)")


# ASYNC-SAFE
async def log_recommendations_presented(
    session_id: str,
    user_id: str,
    sqs_result: dict,
    model_version: str,
) -> None:
    recommendations = sqs_result.get("recommendations", [])
    sqs_score       = sqs_result.get("sqs_score") or sqs_result.get("package_sqs_score")
    form_id         = sqs_result.get("form_id")
    if not recommendations:
        return

    async with get_pool().acquire() as conn:
        for rec in recommendations:
            if isinstance(rec, str):
                rec = {
                    "rec_id":       f"rec_{uuid.uuid4().hex[:8]}",
                    "message":      rec,
                    "type":         "suggestion",
                    "field":        None,
                    "component":    None,
                    "score_impact": None,
                }
            rec_id = rec.get("rec_id") or f"rec_{uuid.uuid4().hex[:8]}"
            try:
                await conn.execute(
                    """
                    INSERT INTO sqs_recommendation_audit (
                        id, session_id, user_id, form_id, rec_id, field,
                        recommendation_type, component, message, score_impact,
                        presented_at, sqs_score_at_presentation, model_version
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (session_id, rec_id) DO NOTHING
                    """,
                    f"audit_{uuid.uuid4().hex}",
                    session_id, user_id, form_id, rec_id,
                    rec.get("field"),
                    rec.get("type", "suggestion"),
                    rec.get("component"),
                    rec.get("message"),
                    rec.get("score_impact"),
                    datetime.now(timezone.utc).isoformat(),
                    sqs_score,
                    model_version,
                )
            except Exception as ex:
                logger.error(f"Failed to log recommendation {rec_id}: {ex}")
    logger.info(f"Logged {len(recommendations)} recommendations for session {session_id}")


# ASYNC-SAFE
async def log_field_change(
    session_id: str,
    user_id: str,
    form_id: Optional[str],
    field_name: str,
    fact_key: Optional[str],
    source: str,
    previous_value: Optional[str],
    new_value: str,
    confidence: Optional[str],
    model_version: str,
) -> None:
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO field_source_audit (
                    id, session_id, user_id, form_id, field_name, fact_key,
                    source, previous_value, new_value, confidence,
                    changed_at, model_version
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                f"field_{uuid.uuid4().hex}",
                session_id, user_id, form_id, field_name, fact_key,
                source, previous_value, new_value, confidence,
                datetime.now(timezone.utc).isoformat(),
                model_version,
            )
        logger.debug(f"Logged field change: {field_name} → {str(new_value)[:50]}")
    except Exception as ex:
        logger.error(f"Failed to log field change: {ex}")


# ASYNC-SAFE
async def log_download_with_open_recs(
    session_id: str,
    override_reason: Optional[str],
    model_version: str,
    user_id: Optional[str] = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    """UPDATE sqs_recommendation_audit
                       SET action='downloaded_anyway', action_at=$1
                       WHERE session_id=$2 AND action IS NULL""",
                    now, session_id,
                )
                count = int(status.split()[-1]) if status else 0
                await conn.execute(
                    """INSERT INTO download_audit
                       (id, session_id, user_id, override_note, open_rec_count,
                        downloaded_at, model_version)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                    f"dl_{uuid.uuid4().hex}", session_id, user_id,
                    override_reason or "", count, now, model_version,
                )
        logger.info(f"Logged download for session {session_id}: {count} open recs stamped")
        return count
    except Exception as ex:
        logger.error(f"Failed to log download: {ex}")
        return 0


# ASYNC-SAFE
async def mark_recommendation_resolved(
    session_id: str,
    rec_id: str,
    sqs_score_at_action: int,
    model_version: str,
    user_id: Optional[str] = None,
    form_id: Optional[str] = None,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sqs_recommendation_audit (
                    id, session_id, user_id, form_id, rec_id, field,
                    recommendation_type, component, message, score_impact,
                    presented_at, sqs_score_at_presentation, model_version,
                    action, action_at, sqs_score_at_action
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                ON CONFLICT (session_id, rec_id) DO UPDATE
                    SET action='resolved', action_at=EXCLUDED.action_at,
                        sqs_score_at_action=EXCLUDED.sqs_score_at_action
                    WHERE sqs_recommendation_audit.action IS NULL
                """,
                f"audit_{uuid.uuid4().hex}",
                session_id, user_id, form_id, rec_id,
                None, "suggestion", None, None, None,
                now, sqs_score_at_action, model_version,
                "resolved", now, sqs_score_at_action,
            )
        logger.info(f"Marked rec {rec_id} resolved (session {session_id})")
        return True
    except Exception as ex:
        logger.error(f"Failed to resolve recommendation: {ex}")
        return False


# ASYNC-SAFE
async def mark_recommendation_dismissed(
    session_id: str,
    rec_id: str,
    override_reason: str,
    sqs_score_at_action: int,
    model_version: str,
    message: Optional[str] = None,
    field: Optional[str] = None,
    component: Optional[str] = None,
    score_impact: Optional[int] = None,
    user_id: Optional[str] = None,
    form_id: Optional[str] = None,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sqs_recommendation_audit (
                    id, session_id, user_id, form_id, rec_id, field,
                    recommendation_type, component, message, score_impact,
                    presented_at, sqs_score_at_presentation, model_version,
                    action, action_at, sqs_score_at_action, override_reason
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (session_id, rec_id) DO UPDATE
                    SET action='dismissed', action_at=EXCLUDED.action_at,
                        sqs_score_at_action=EXCLUDED.sqs_score_at_action,
                        override_reason=EXCLUDED.override_reason,
                        -- Associate the dismissed rec with the form it was DISMISSED
                        -- on (EXCLUDED), falling back to the presented form_id only
                        -- when the dismiss carried none. Multi-form recs (e.g.
                        -- rec_applicant_name) are presented once under whichever form
                        -- was processed first (ON CONFLICT DO NOTHING at presentation),
                        -- so keeping that original form_id hid the rec from the
                        -- dismissed dropdown on the form the producer actually acted on
                        -- (the dropdown filters by form). Preferring the dismiss form_id
                        -- makes it appear where the producer dismissed it.
                        form_id=COALESCE(EXCLUDED.form_id, sqs_recommendation_audit.form_id)
                    WHERE sqs_recommendation_audit.action IS NULL
                """,
                f"audit_{uuid.uuid4().hex}",
                session_id, user_id, form_id, rec_id,
                field, "suggestion", component, message, score_impact,
                now, sqs_score_at_action, model_version,
                "dismissed", now, sqs_score_at_action, override_reason,
            )
        logger.info(f"Marked rec {rec_id} dismissed (session {session_id})")
        return True
    except Exception as ex:
        logger.error(f"Failed to dismiss recommendation: {ex}")
        return False


# ASYNC-SAFE
async def get_dismissed_recommendations(session_id: str) -> List[dict]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, form_id, message, score_impact, override_reason, action_at
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND action='dismissed'
                   ORDER BY action_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get dismissed recommendations: {ex}")
        return []


# ASYNC-SAFE
async def get_open_recommendations(session_id: str) -> List[dict]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, field, recommendation_type, message, score_impact
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND action IS NULL
                   ORDER BY score_impact DESC NULLS LAST""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get open recommendations: {ex}")
        return []


# ASYNC-SAFE
async def get_audit_summary(session_id: str) -> dict:
    try:
        async with get_pool().acquire() as conn:
            rec_row = await conn.fetchrow(
                """SELECT
                       COUNT(*)                                                AS total,
                       SUM(CASE WHEN action='resolved'          THEN 1 ELSE 0 END) AS resolved,
                       SUM(CASE WHEN action='dismissed'         THEN 1 ELSE 0 END) AS dismissed,
                       SUM(CASE WHEN action='downloaded_anyway' THEN 1 ELSE 0 END) AS downloaded_anyway,
                       SUM(CASE WHEN action IS NULL             THEN 1 ELSE 0 END) AS open
                   FROM sqs_recommendation_audit WHERE session_id=$1""",
                session_id,
            )
            field_row = await conn.fetchrow(
                """SELECT
                       COUNT(*)                                                    AS total_changes,
                       SUM(CASE WHEN source='producer'   THEN 1 ELSE 0 END)       AS producer_edits,
                       SUM(CASE WHEN source='ai'         THEN 1 ELSE 0 END)       AS ai_extractions,
                       SUM(CASE WHEN source='client_arq' THEN 1 ELSE 0 END)       AS client_submissions
                   FROM field_source_audit WHERE session_id=$1""",
                session_id,
            )
        return {
            "session_id":      session_id,
            "recommendations": dict(rec_row)   if rec_row   else {},
            "field_changes":   dict(field_row) if field_row else {},
        }
    except Exception as ex:
        logger.error(f"Failed to get audit summary: {ex}")
        return {"error": str(ex)}


# ── Workstream 1 audit trail (Beta Report §4.1 + §4.2) ───────────────────────
# Best-effort recording of Submission Integrity / Document Classification user
# events. Every helper swallows DB errors so an audit failure never breaks the
# user-facing flow (mirrors the recommendation/field audit helpers above).

def _integrity_model_version(integrity: Optional[dict]) -> str:
    return (integrity or {}).get("model_version") or "unknown"


# ASYNC-SAFE
async def log_integrity_assessed(
    session_id: str,
    user_id: Optional[str],
    integrity: dict,
) -> None:
    """Record a Submission Integrity verdict (§4.1) — the clustering result and,
    critically, whether a multi-insured warning was raised. Pairs with
    ``log_integrity_resolution`` so a warning issued → override can be traced.

    Skips trivially-clean single-insured verdicts (status 'high', no review) to
    avoid noise; medium/low or review-required verdicts are always recorded.
    """
    integrity = integrity or {}
    status = integrity.get("status")
    review_required = bool(integrity.get("review_required"))
    if status == "high" and not review_required:
        return
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO submission_integrity_audit (
                    id, session_id, user_id, event_type,
                    integrity_status, confidence, review_required,
                    detected_entities, reasons, signals,
                    model_version, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                f"sia_{uuid.uuid4().hex}",
                session_id, str(user_id) if user_id is not None else None,
                "integrity_assessed",
                status,
                integrity.get("confidence"),
                review_required,
                integrity.get("detected_entities") or [],
                integrity.get("reasons") or [],
                integrity.get("signals") or {},
                _integrity_model_version(integrity),
                datetime.now(timezone.utc).isoformat(),
            )
        logger.info(
            f"Logged integrity assessment for session {session_id} "
            f"(status={status}, review_required={review_required})"
        )
    except Exception as ex:
        logger.error(f"Failed to log integrity assessment: {ex}")


# ASYNC-SAFE
async def log_integrity_resolution(
    session_id: str,
    user_id: Optional[str],
    action: str,
    integrity: Optional[dict] = None,
    removed_doc_ids: Optional[List[str]] = None,
    created_submissions: Optional[List[dict]] = None,
) -> None:
    """Record how the user resolved a Submission Integrity review (§4.1).

    ``overridden`` is True whenever the user kept a flagged package
    (continue_anyway / create_separate_submissions) — this is the explicit
    "records whether the user overrode the warning" acceptance criterion.
    """
    integrity = integrity or {}
    overridden = action in ("continue_anyway", "create_separate_submissions")
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO submission_integrity_audit (
                    id, session_id, user_id, event_type,
                    integrity_status, confidence, review_required,
                    detected_entities, action, overridden,
                    removed_doc_ids, acknowledged_entities, created_submissions,
                    model_version, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                f"sia_{uuid.uuid4().hex}",
                session_id, str(user_id) if user_id is not None else None,
                "integrity_resolved",
                integrity.get("status"),
                integrity.get("confidence"),
                bool(integrity.get("review_required")),
                integrity.get("detected_entities") or [],
                action,
                overridden,
                list(removed_doc_ids or []),
                integrity.get("detected_entities") or [],
                created_submissions or [],
                _integrity_model_version(integrity),
                datetime.now(timezone.utc).isoformat(),
            )
        logger.info(
            f"Logged integrity resolution for session {session_id} "
            f"(action={action}, overridden={overridden})"
        )
    except Exception as ex:
        logger.error(f"Failed to log integrity resolution: {ex}")


# ASYNC-SAFE
async def log_document_reclassified(
    session_id: str,
    user_id: Optional[str],
    doc_id: str,
    action: str,
    previous_doc_type: Optional[str],
    new_doc_type: Optional[str],
) -> None:
    """Record a manual document-classification correction (§4.2): set_type,
    exclude, include, or supporting_only — with the before/after doc type."""
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO submission_integrity_audit (
                    id, session_id, user_id, event_type,
                    action, doc_id, previous_doc_type, new_doc_type, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                f"sia_{uuid.uuid4().hex}",
                session_id, str(user_id) if user_id is not None else None,
                "document_reclassified",
                action, str(doc_id),
                previous_doc_type, new_doc_type,
                datetime.now(timezone.utc).isoformat(),
            )
        logger.info(
            f"Logged document reclassification for session {session_id} "
            f"(doc={doc_id}, action={action}, {previous_doc_type}->{new_doc_type})"
        )
    except Exception as ex:
        logger.error(f"Failed to log document reclassification: {ex}")


# ASYNC-SAFE
async def log_underwriting_confirmation(
    session_id: str,
    user_id: Optional[str],
    fact_key: str,
    label: str,
    confirmed_value: str,
    previous_value: Optional[str],
) -> None:
    """Record a user-confirmed underwriting value (Beta Report §4.3 / §5.1).

    Writes one row to ``underwriting_confirmation_audit`` so every "you chose X
    on date Y" event is permanently queryable — fact_key, the human label,
    the confirmed value, the value that was in merged_facts before confirmation,
    and an exact UTC timestamp. Non-fatal: a logging failure never blocks the
    confirmation itself.
    """
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO underwriting_confirmation_audit (
                    id, session_id, user_id, fact_key, label,
                    confirmed_value, previous_value, confirmed_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                f"uwc_{uuid.uuid4().hex}",
                session_id,
                str(user_id) if user_id is not None else None,
                fact_key,
                label,
                confirmed_value,
                previous_value,
                datetime.now(timezone.utc).isoformat(),
            )
        logger.info(
            "Logged underwriting confirmation session=%s field=%s value=%r",
            session_id, fact_key, confirmed_value,
        )
    except Exception as ex:
        logger.error(f"Failed to log underwriting confirmation: {ex}")
