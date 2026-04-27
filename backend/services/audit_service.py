# audit_service.py — PostgreSQL / Supabase implementation

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_db
from models.schemas import SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS, DOWNLOAD_AUDIT_STATEMENTS

logger = logging.getLogger(__name__)


def init_audit_tables() -> None:
    """
    Create audit tables if they don't exist.
    Called from main.py startup and from database.py init_db().
    Each statement is executed individually — psycopg2 does not support
    multi-statement strings.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        for stmt in SQS_RECOMMENDATION_AUDIT_STATEMENTS + FIELD_SOURCE_AUDIT_STATEMENTS + DOWNLOAD_AUDIT_STATEMENTS:
            try:
                cur.execute(stmt)
                conn.commit()
            except Exception as ex:
                conn.rollback()
                logger.warning(f"Audit table statement skipped (likely already exists): {ex}")
        logger.info("Audit tables ready (PostgreSQL)")
    finally:
        cur.close()
        conn.close()


# ── Audit logging ─────────────────────────────────────────────────────────────

def log_recommendations_presented(
    session_id: str,
    user_id: str,
    sqs_result: dict,
    model_version: str,
) -> None:
    """
    Insert one row per recommendation shown to the user.
    Uses ON CONFLICT DO NOTHING so re-generates on the same session
    don't create duplicate rows.
    Called after calculate_sqs() returns.
    """
    recommendations = sqs_result.get("recommendations", [])
    sqs_score       = sqs_result.get("sqs_score") or sqs_result.get("package_sqs_score")
    form_id         = sqs_result.get("form_id")

    if not recommendations:
        return

    conn = get_db()
    cur  = conn.cursor()
    try:
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
            cur.execute(
                """
                INSERT INTO sqs_recommendation_audit (
                    id, session_id, user_id, form_id, rec_id, field,
                    recommendation_type, component, message, score_impact,
                    presented_at, sqs_score_at_presentation, model_version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (session_id, rec_id) DO NOTHING
                """,
                (
                    f"audit_{uuid.uuid4().hex}",
                    session_id,
                    user_id,
                    form_id,
                    rec_id,
                    rec.get("field"),
                    rec.get("type", "suggestion"),
                    rec.get("component"),
                    rec.get("message"),
                    rec.get("score_impact"),
                    datetime.now(timezone.utc).isoformat(),
                    sqs_score,
                    model_version,
                ),
            )
        conn.commit()
        logger.info(f"Logged {len(recommendations)} recommendations for session {session_id}")
    except Exception as ex:
        logger.error(f"Failed to log recommendations: {ex}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def log_field_change(
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
    """
    Log a single field edit.
    Called in the update_pdf endpoint after a field is written.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO field_source_audit (
                id, session_id, user_id, form_id, field_name, fact_key,
                source, previous_value, new_value, confidence,
                changed_at, model_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                f"field_{uuid.uuid4().hex}",
                session_id,
                user_id,
                form_id,
                field_name,
                fact_key,
                source,
                previous_value,
                new_value,
                confidence,
                datetime.now(timezone.utc).isoformat(),
                model_version,
            ),
        )
        conn.commit()
        logger.debug(f"Logged field change: {field_name} → {str(new_value)[:50]} (session {session_id})")
    except Exception as ex:
        logger.error(f"Failed to log field change: {ex}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def log_download_with_open_recs(
    session_id: str,
    override_reason: Optional[str],
    model_version: str,
    user_id: Optional[str] = None,
) -> int:
    """
    1. Stamps all still-open recs as 'downloaded_anyway' (no override_reason — that lives in download_audit).
    2. Inserts one row into download_audit with the override note as its own record.
    Returns count of rec rows stamped.
    """
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    try:
        # Stamp open recs — no override_reason written here
        cur.execute(
            """
            UPDATE sqs_recommendation_audit
            SET action    = 'downloaded_anyway',
                action_at = %s
            WHERE session_id = %s AND action IS NULL
            """,
            (now, session_id),
        )
        count = cur.rowcount

        # Write the override note to its own table
        cur.execute(
            """
            INSERT INTO download_audit (id, session_id, user_id, override_note, open_rec_count, downloaded_at, model_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (f"dl_{uuid.uuid4().hex}", session_id, user_id, override_reason or "", count, now, model_version),
        )
        conn.commit()
        logger.info(f"Logged download for session {session_id}: {count} open recs stamped, override note saved")
        return count
    except Exception as ex:
        logger.error(f"Failed to log download: {ex}")
        conn.rollback()
        return 0
    finally:
        cur.close()
        conn.close()


def mark_recommendation_resolved(
    session_id: str,
    rec_id: str,
    sqs_score_at_action: int,
    model_version: str,
    user_id: Optional[str] = None,
    form_id: Optional[str] = None,
) -> bool:
    """Mark a recommendation as resolved. Upserts the row if it was never logged."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO sqs_recommendation_audit (
                id, session_id, user_id, form_id, rec_id, field,
                recommendation_type, component, message, score_impact,
                presented_at, sqs_score_at_presentation, model_version,
                action, action_at, sqs_score_at_action
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (session_id, rec_id) DO UPDATE
                SET action              = 'resolved',
                    action_at           = EXCLUDED.action_at,
                    sqs_score_at_action = EXCLUDED.sqs_score_at_action
                WHERE sqs_recommendation_audit.action IS NULL
            """,
            (
                f"audit_{uuid.uuid4().hex}",
                session_id,
                user_id,
                form_id,
                rec_id,
                None, "suggestion", None, None, None,
                now, sqs_score_at_action, model_version,
                "resolved", now, sqs_score_at_action,
            ),
        )
        conn.commit()
        logger.info(f"Marked rec {rec_id} resolved (session {session_id})")
        return True
    except Exception as ex:
        logger.error(f"Failed to resolve recommendation: {ex}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def mark_recommendation_dismissed(
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
    """Mark a recommendation as dismissed. Upserts the row if it was never logged."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO sqs_recommendation_audit (
                id, session_id, user_id, form_id, rec_id, field,
                recommendation_type, component, message, score_impact,
                presented_at, sqs_score_at_presentation, model_version,
                action, action_at, sqs_score_at_action, override_reason
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (session_id, rec_id) DO UPDATE
                SET action              = 'dismissed',
                    action_at           = EXCLUDED.action_at,
                    sqs_score_at_action = EXCLUDED.sqs_score_at_action,
                    override_reason     = EXCLUDED.override_reason
                WHERE sqs_recommendation_audit.action IS NULL
            """,
            (
                f"audit_{uuid.uuid4().hex}",
                session_id,
                user_id,
                form_id,
                rec_id,
                field,
                "suggestion",
                component,
                message,
                score_impact,
                now,
                sqs_score_at_action,
                model_version,
                "dismissed",
                now,
                sqs_score_at_action,
                override_reason,
            ),
        )
        conn.commit()
        logger.info(f"Marked rec {rec_id} dismissed (session {session_id})")
        return True
    except Exception as ex:
        logger.error(f"Failed to dismiss recommendation: {ex}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def get_open_recommendations(session_id: str) -> List[dict]:
    """
    Return all recommendations with no action yet for this session.
    Used by the download pre-flight check.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            SELECT rec_id, field, recommendation_type, message, score_impact
            FROM sqs_recommendation_audit
            WHERE session_id = %s AND action IS NULL
            ORDER BY score_impact DESC NULLS LAST
            """,
            (session_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get open recommendations: {ex}")
        return []
    finally:
        cur.close()
        conn.close()


def get_audit_summary(session_id: str) -> dict:
    """
    Aggregate counts of resolved / dismissed / downloaded_anyway / open recs
    plus field-change breakdown. Used for compliance reporting.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                COUNT(*)                                            AS total,
                SUM(CASE WHEN action = 'resolved'          THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN action = 'dismissed'         THEN 1 ELSE 0 END) AS dismissed,
                SUM(CASE WHEN action = 'downloaded_anyway' THEN 1 ELSE 0 END) AS downloaded_anyway,
                SUM(CASE WHEN action IS NULL               THEN 1 ELSE 0 END) AS open
            FROM sqs_recommendation_audit
            WHERE session_id = %s
            """,
            (session_id,),
        )
        rec_row = cur.fetchone()
        rec_summary = dict(rec_row) if rec_row else {}

        cur.execute(
            """
            SELECT
                COUNT(*)                                                    AS total_changes,
                SUM(CASE WHEN source = 'producer'   THEN 1 ELSE 0 END)     AS producer_edits,
                SUM(CASE WHEN source = 'ai'         THEN 1 ELSE 0 END)     AS ai_extractions,
                SUM(CASE WHEN source = 'client_arq' THEN 1 ELSE 0 END)     AS client_submissions
            FROM field_source_audit
            WHERE session_id = %s
            """,
            (session_id,),
        )
        field_row = cur.fetchone()
        field_summary = dict(field_row) if field_row else {}

        return {
            "session_id":    session_id,
            "recommendations": rec_summary,
            "field_changes":   field_summary,
        }
    except Exception as ex:
        logger.error(f"Failed to get audit summary: {ex}")
        return {"error": str(ex)}
    finally:
        cur.close()
        conn.close()
