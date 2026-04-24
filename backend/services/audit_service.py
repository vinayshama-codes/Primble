# audit_service.py — PostgreSQL / Supabase implementation

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_db
from models.schemas import SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS

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
        for stmt in SQS_RECOMMENDATION_AUDIT_STATEMENTS + FIELD_SOURCE_AUDIT_STATEMENTS:
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
) -> int:
    """
    Bulk-stamp all open (action IS NULL) recommendations as 'downloaded_anyway'.
    Called when the user proceeds through the download pre-flight gate.
    Returns count of rows updated.
    """
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sqs_recommendation_audit
            SET action          = 'downloaded_anyway',
                action_at       = %s,
                override_reason = %s
            WHERE session_id = %s AND action IS NULL
            """,
            (datetime.now(timezone.utc).isoformat(), override_reason, session_id),
        )
        count = cur.rowcount
        conn.commit()
        logger.info(f"Logged downloaded_anyway for {count} open recs (session {session_id})")
        return count
    except Exception as ex:
        logger.error(f"Failed to log download_anyway: {ex}")
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
) -> bool:
    """Mark a recommendation as resolved when the producer fixes the flagged field."""
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sqs_recommendation_audit
            SET action              = 'resolved',
                action_at           = %s,
                sqs_score_at_action = %s
            WHERE session_id = %s AND rec_id = %s AND action IS NULL
            """,
            (datetime.now(timezone.utc).isoformat(), sqs_score_at_action, session_id, rec_id),
        )
        success = cur.rowcount > 0
        conn.commit()
        if success:
            logger.info(f"Marked rec {rec_id} resolved (session {session_id})")
        return success
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
) -> bool:
    """Mark a recommendation as dismissed with a required override reason."""
    conn = get_db()
    cur  = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sqs_recommendation_audit
            SET action              = 'dismissed',
                action_at           = %s,
                sqs_score_at_action = %s,
                override_reason     = %s
            WHERE session_id = %s AND rec_id = %s AND action IS NULL
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                sqs_score_at_action,
                override_reason,
                session_id,
                rec_id,
            ),
        )
        success = cur.rowcount > 0
        conn.commit()
        if success:
            logger.info(f"Marked rec {rec_id} dismissed (session {session_id})")
        return success
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
