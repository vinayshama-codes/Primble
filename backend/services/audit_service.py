# audit_service.py — asyncpg implementation

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from models.schemas import SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS, DOWNLOAD_AUDIT_STATEMENTS

logger = logging.getLogger(__name__)


# ASYNC-SAFE
async def init_audit_tables() -> None:
    """Create audit tables if they don't exist. Called from main.py startup."""
    async with get_pool().acquire() as conn:
        for stmt in (
            SQS_RECOMMENDATION_AUDIT_STATEMENTS
            + FIELD_SOURCE_AUDIT_STATEMENTS
            + DOWNLOAD_AUDIT_STATEMENTS
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
                        override_reason=EXCLUDED.override_reason
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
