# audit_service.py — asyncpg implementation

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from models.schemas import (
    SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS,
    DOWNLOAD_AUDIT_STATEMENTS, SUBMISSION_INTEGRITY_AUDIT_STATEMENTS,
    UNDERWRITING_CONFIRMATION_AUDIT_STATEMENTS, MARKETING_REASON_AUDIT_STATEMENTS,
    SUBMISSION_ISSUE_STATUS_STATEMENTS,
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
            + MARKETING_REASON_AUDIT_STATEMENTS
            + SUBMISSION_ISSUE_STATUS_STATEMENTS
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
async def sync_field_qa_findings(
    session_id: str,
    user_id: str,
    rows: list,
    model_version: str,
) -> None:
    """Replace this session's field-QA advisory rows with the current set.

    Field QA is RECOMPUTED on every generation, so the prior field-QA rows for
    the session are cleared first and the fresh findings inserted - a field that
    got fixed stops showing, a still-open one stays. Reuses the shared
    sqs_recommendation_audit table so the existing pre-download review surfaces
    these with no new UI or endpoint. These rows are advisory/soft - they never
    block a download.

    recommendation_type has a fixed CHECK constraint ('hard_stop','soft_warning',
    'missing_field','suggestion') - field-QA rows use the existing 'suggestion'
    type (see field_qa.to_recommendation_rows) rather than adding a new allowed
    value, and are identified for this session-scoped refresh by their
    "fieldqa_" rec_id prefix instead.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                # Clear the previous QA snapshot for this session only.
                await conn.execute(
                    "DELETE FROM sqs_recommendation_audit "
                    "WHERE session_id=$1 AND rec_id LIKE 'fieldqa_%'",
                    session_id,
                )
                for rec in rows or []:
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
                        session_id, user_id, rec.get("component"), rec.get("rec_id"),
                        rec.get("field"),
                        rec.get("type", "suggestion"),
                        rec.get("component"),
                        rec.get("message"),
                        rec.get("score_impact"),
                        now, None, model_version,
                    )
        if rows:
            logger.info("Logged %d field-QA finding(s) for session %s", len(rows), session_id)
    except Exception as ex:
        logger.warning(f"sync_field_qa_findings failed for session {session_id}: {ex}")


# ASYNC-SAFE
async def run_and_log_field_qa(
    session_id: str,
    user_id: str,
    generated_forms: dict,
    merged_facts: dict,
    confirmations: Optional[dict],
    enabled: bool,
) -> None:
    """Run form-level field QA and refresh its pre-download advisory rows.

    Single entry point used by every generation path (sync route, field-edit
    route, async worker) so the behavior can't drift between them. No-op unless
    ``enabled`` (ENABLE_FIELD_QA). Never raises - QA is advisory and must never
    break generation.
    """
    if not enabled:
        return
    try:
        from services.field_qa import (
            run_field_qa, to_recommendation_rows, FIELD_QA_MODEL_VERSION,
        )
        qa = run_field_qa(
            generated_forms,
            merged_facts=merged_facts or {},
            confirmations=confirmations or {},
        )
        await sync_field_qa_findings(
            session_id, user_id, to_recommendation_rows(qa), FIELD_QA_MODEL_VERSION,
        )
    except Exception as ex:
        logger.warning(f"run_and_log_field_qa skipped for session {session_id}: {ex}")


# ASYNC-SAFE
async def sync_field_mapping_findings(
    session_id: str,
    user_id: str,
    rows: list,
    model_version: str,
) -> None:
    """Replace this session's field-mapping-integrity warning rows with the
    current set (Figure 33 client feedback).

    Mirrors sync_field_qa_findings exactly, but isolated by the "fieldmap_"
    rec_id prefix so this never touches field-QA's own rows or any SQS-engine
    recommendation. Recomputed on every generation: a field the producer fixes
    stops showing, a still-contaminated one stays. Reuses the shared
    sqs_recommendation_audit table so the existing pre-download preflight modal
    AND the post-download checklist both surface these with no new UI/endpoint -
    they read the same session's open recommendations. Advisory/soft only -
    never blocks a download.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM sqs_recommendation_audit "
                    "WHERE session_id=$1 AND rec_id LIKE 'fieldmap_%'",
                    session_id,
                )
                for rec in rows or []:
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
                        session_id, user_id, rec.get("component"), rec.get("rec_id"),
                        rec.get("field"),
                        rec.get("type", "suggestion"),
                        rec.get("component"),
                        rec.get("message"),
                        rec.get("score_impact"),
                        now, None, model_version,
                    )
        if rows:
            logger.info("Logged %d field-mapping warning(s) for session %s", len(rows), session_id)
    except Exception as ex:
        logger.warning(f"sync_field_mapping_findings failed for session {session_id}: {ex}")


# ASYNC-SAFE
async def run_and_log_field_mapping_check(
    session_id: str,
    user_id: str,
    generated_forms: dict,
    merged_facts: dict,
    confirmations: Optional[dict],
) -> None:
    """Detect carrier/policy data mapped into an insured/owner field and refresh
    its warning rows (Figure 33 client feedback).

    Always runs - no feature flag, unlike field QA - so the check is active by
    default with no environment configuration required. Single entry point used
    by every generation path (sync route, field-edit route, async worker) so
    behavior can't drift between them. NEVER blocks the download: this only
    writes advisory rows that the existing pre-download preflight modal and
    post-download checklist already know how to display. Never raises - a
    detector fault must never break form generation.
    """
    try:
        from services.field_mapping_integrity import (
            detect_field_mapping_contamination, to_recommendation_rows,
            FIELD_MAPPING_INTEGRITY_MODEL_VERSION,
        )
        result = detect_field_mapping_contamination(
            generated_forms or {},
            merged_facts=merged_facts or {},
            confirmations=confirmations or {},
        )
        await sync_field_mapping_findings(
            session_id, user_id, to_recommendation_rows(result), FIELD_MAPPING_INTEGRITY_MODEL_VERSION,
        )
    except Exception as ex:
        logger.warning(f"run_and_log_field_mapping_check skipped for session {session_id}: {ex}")


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
                       OR sqs_recommendation_audit.action = 'downloaded_anyway'
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


# ── Issue-rail resolution status ───────────────────────────────────────────────
# Pure work-tracking for the issue rail. Writing a status here NEVER touches SQS
# scoring or dismiss-credit - it only records that a broker marked an issue
# open / resolved / dismissed on this submission. Keyed by the durable issue_id.

# ASYNC-SAFE
async def set_issue_status(
    session_id: str,
    issue_id: str,
    status: str,
    reason: Optional[str] = None,
    user_id: Optional[str] = None,
    form_id: Optional[str] = None,
    field: Optional[str] = None,
    rule_code: Optional[str] = None,
    source_fact: Optional[str] = None,
    message: Optional[str] = None,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO submission_issue_status (
                    id, session_id, user_id, issue_id, form_id, field,
                    rule_code, source_fact, message, status, reason, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (session_id, issue_id) DO UPDATE
                    SET status=EXCLUDED.status,
                        reason=EXCLUDED.reason,
                        updated_at=EXCLUDED.updated_at,
                        form_id=COALESCE(EXCLUDED.form_id, submission_issue_status.form_id),
                        field=COALESCE(EXCLUDED.field, submission_issue_status.field),
                        rule_code=COALESCE(EXCLUDED.rule_code, submission_issue_status.rule_code),
                        source_fact=COALESCE(EXCLUDED.source_fact, submission_issue_status.source_fact),
                        message=COALESCE(EXCLUDED.message, submission_issue_status.message)
                """,
                f"iss_status_{uuid.uuid4().hex}",
                session_id, user_id, issue_id, form_id, field,
                rule_code, source_fact, message, status, reason, now,
            )
        logger.info(f"Issue {issue_id} status={status} (session {session_id})")
        return True
    except Exception as ex:
        logger.error(f"Failed to set issue status: {ex}")
        return False


# ASYNC-SAFE
async def get_issue_statuses(session_id: str) -> List[dict]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT issue_id, status, reason, form_id, field, rule_code,
                          source_fact, message, updated_at
                   FROM submission_issue_status
                   WHERE session_id=$1
                   ORDER BY updated_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get issue statuses: {ex}")
        return []


# ASYNC-SAFE
async def upsert_marketing_reason(
    session_id: str,
    user_id: str,
    reason_code: str,
    reason_note: Optional[str],
    is_adverse: bool,
) -> bool:
    """Persist the Figure 6 "Why are you marketing this account?" answer,
    split into a controlled reason_code + free-text reason_note, durably
    (independent of the processing_sessions JSON blob so it survives the
    facts-retention job and is fetchable by an underwriter during an audit).

    Latest answer wins - one row per session_id, upserted in place - matching
    the product decision that this is a current-value field, not history.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO marketing_reason_audit (
                    id, session_id, user_id, reason_code, reason_note, is_adverse, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (session_id) DO UPDATE
                    SET reason_code = EXCLUDED.reason_code,
                        reason_note = EXCLUDED.reason_note,
                        is_adverse  = EXCLUDED.is_adverse,
                        updated_at  = EXCLUDED.updated_at
                """,
                f"mktreason_{uuid.uuid4().hex}", session_id, user_id,
                reason_code, reason_note, is_adverse, now,
            )
        return True
    except Exception as ex:
        logger.error(f"Failed to upsert marketing reason: {ex}")
        return False


# ASYNC-SAFE
async def get_marketing_reason(session_id: str) -> Optional[dict]:
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """SELECT session_id, user_id, reason_code, reason_note, is_adverse, updated_at
                   FROM marketing_reason_audit WHERE session_id=$1""",
                session_id,
            )
        return dict(row) if row else None
    except Exception as ex:
        logger.error(f"Failed to get marketing reason: {ex}")
        return None


# ASYNC-SAFE
async def get_open_recommendations(session_id: str, include_acknowledged: bool = False) -> List[dict]:
    """Recommendations that still need the producer's attention.

    Default (``include_acknowledged=False``): 'never reviewed' only (action IS
    NULL). Kept for the non-download callers (ARQ recalc auto-resolve, the
    recommendation-card refresh) whose semantics must not change.

    ``include_acknowledged=True`` (passed ONLY by the pre-download preflight
    route): returns EVERY still-unresolved item - action IS NULL *or*
    'downloaded_anyway' - excluding only 'resolved' (actually fixed) and
    'dismissed' (marked N/A). This is what makes the pre-download modal and the
    post-download checklist re-show ALL outstanding issues on EVERY download,
    however many times, and drop each one the moment it is genuinely fixed:
      * SQS recs           -> fixed => mark_recommendation_resolved sets
                              action='resolved' (now overrides a prior
                              'downloaded_anyway' too), so it stops returning.
      * field-QA / field-mapping rows -> fixed => their row is DELETEd + rebuilt
                              from live values on the next generation/edit, so a
                              corrected field simply has no row.
    A prior "Download Anyway" acknowledges but never suppresses - only a real
    fix (resolved) or an explicit dismiss removes an item from this set.

    Do NOT reuse this for audit/reporting purposes - see get_unresolved_recommendations.
    """
    # The WHERE clause is built from fixed literals only (no user input), so the
    # f-string interpolation below carries no injection risk.
    where = "action IS NULL"
    if include_acknowledged:
        where = (
            "action IS DISTINCT FROM 'resolved' "
            "AND action IS DISTINCT FROM 'dismissed'"
        )
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT rec_id, field, recommendation_type, message, score_impact
                    FROM sqs_recommendation_audit
                    WHERE session_id=$1 AND {where}
                    ORDER BY score_impact DESC NULLS LAST""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get open recommendations: {ex}")
        return []


# ASYNC-SAFE
async def get_unresolved_recommendations(session_id: str) -> List[dict]:
    """Recommendations that are still substantively unresolved: never reviewed
    (action IS NULL) OR acknowledged-but-not-fixed via the pre-download override
    ('downloaded_anyway'). Excludes only 'resolved' (data was actually fixed) and
    'dismissed' (producer marked it not applicable).

    This is the correct source for download audit records and cover-page Red Flags
    - clicking "Download Anyway" acknowledges an issue, it doesn't fix it, so it must
    still appear in the download's audit trail (that's the whole point of pairing it
    with the override note for an E&O record).
    """
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, field, recommendation_type, message, score_impact, action
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND action IS DISTINCT FROM 'resolved'
                                       AND action IS DISTINCT FROM 'dismissed'
                   ORDER BY score_impact DESC NULLS LAST""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get unresolved recommendations: {ex}")
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
