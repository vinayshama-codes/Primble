# audit_service.py — asyncpg implementation

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from config.database import get_pool
from models.schemas import (
    SQS_RECOMMENDATION_AUDIT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS,
    DOWNLOAD_AUDIT_STATEMENTS, SUBMISSION_INTEGRITY_AUDIT_STATEMENTS,
    UNDERWRITING_CONFIRMATION_AUDIT_STATEMENTS, MARKETING_REASON_AUDIT_STATEMENTS,
    SUBMISSION_ISSUE_STATUS_STATEMENTS, AUDIT_EVENT_STATEMENTS,
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
            + AUDIT_EVENT_STATEMENTS
        ):
            try:
                await conn.execute(stmt)
            except Exception as ex:
                logger.warning(f"Audit table statement skipped (likely already exists): {ex}")
    logger.info("Audit tables ready (asyncpg)")


def _fallback_rec_id(message: str) -> str:
    """Deterministic id for a recommendation that arrived without one.

    A hash of the MESSAGE, never a random uuid: a random id defeats the
    ON CONFLICT (session_id, rec_id) dedupe, so the same plain-string
    recommendation presented twice (two forms' scorers, or a recalculation)
    stored two identical rows in the pre-download review.
    """
    digest = hashlib.sha1((message or "").encode("utf-8")).hexdigest()[:10]
    return f"rec_str_{digest}"


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
                    "rec_id":       _fallback_rec_id(rec),
                    "message":      rec,
                    "type":         "suggestion",
                    "field":        None,
                    "component":    None,
                    "score_impact": None,
                }
            rec_id = rec.get("rec_id") or _fallback_rec_id(rec.get("message") or "")
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
    previous_source: Optional[str] = None,
    reason: Optional[str] = None,
    record_unchanged: bool = False,
) -> None:
    """Record one field modification - the index row AND the history event.

    `previous_source` is the confidence the value carried BEFORE this change.
    It is what separates the client's "generated-value override" from an
    ordinary producer edit; `audit_history.change_kind` derives the distinction
    rather than asking each call site to label it. Optional so the eight
    existing call sites keep working unchanged; only `update_pdf` has the prior
    confidence to hand and passes it.

    The spine event is emitted HERE, not at the routes (D49): every path that
    modifies a fact already comes through this function, so this is the one
    place a material change cannot be forgotten.

    A NO-OP IS NOT A MODIFICATION. Re-submitting an identical answer is not a
    change, and recording it as one puts `"No" -> "No" / corrected an existing
    entry` into an E&O record - a statement that the producer altered something
    they did not. `update_pdf` has always skipped unchanged fields; the
    producer-answer and resolve-issue paths did not, and the live run
    2026-08-27 produced exactly that row. Guarded here rather than at each
    route so a future writer inherits it.

    ``record_unchanged=True`` is the deliberate exception for the SCHEDULE save
    paths, whose before/after is a ROW COUNT: editing a VIN in row 2 of a
    three-row fleet leaves "3 row(s)" -> "3 row(s)" while genuinely changing
    the data, so suppressing it there would lose a real modification.
    """
    if not record_unchanged:
        _prev_cmp = str(previous_value).strip() if previous_value is not None else ""
        _new_cmp  = str(new_value).strip() if new_value is not None else ""
        if _prev_cmp == _new_cmp:
            logger.debug("field change skipped (unchanged): %s", field_name)
            return

    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO field_source_audit (
                    id, session_id, user_id, form_id, field_name, fact_key,
                    source, previous_value, new_value, confidence,
                    previous_source, reason, changed_at, model_version
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """,
                f"field_{uuid.uuid4().hex}",
                session_id, user_id, form_id, field_name, fact_key,
                source, previous_value, new_value, confidence,
                previous_source, reason,
                datetime.now(timezone.utc).isoformat(),
                model_version,
            )
        logger.debug(f"Logged field change: {field_name} → {str(new_value)[:50]}")
    except Exception as ex:
        logger.error(f"Failed to log field change: {ex}")

    # The append-only half. Separate try/except on purpose (D35): the index row
    # above has already committed, and losing the history event must not be
    # reported as "the change was not recorded".
    try:
        from services.audit_history import (
            EVENT_FIELD_CHANGED, ACTION_EDITED, ACTION_RETRACTED,
        )
        _retracting = not str(new_value or "").strip() and bool(str(previous_value or "").strip())
        await record_material_change(
            session_id, EVENT_FIELD_CHANGED,
            action=ACTION_RETRACTED if _retracting else ACTION_EDITED,
            fact_key=fact_key, field_name=field_name, form_id=form_id,
            previous_value=previous_value, new_value=new_value,
            previous_source=previous_source, source=source,
            user_id=user_id, reason=reason,
            detail={"confidence": confidence} if confidence else None,
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"field change event not recorded for {field_name}: {ex}",
                       exc_info=True)


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
    except Exception as ex:
        logger.error(f"Failed to log download: {ex}")
        return 0

    # E&O section 12: downloading with open items is an override of the
    # pre-download gate, and the note the producer typed is its reason. The
    # per-file checksum + full open-items list stay in acord_audit_log (state);
    # this is the act (history).
    try:
        from services.audit_history import EVENT_PACKAGE_DOWNLOADED, ACTION_DOWNLOADED
        await record_material_change(
            session_id, EVENT_PACKAGE_DOWNLOADED,
            action=ACTION_DOWNLOADED, field_name="package",
            new_value=f"{count} open item(s) at download",
            source="producer", user_id=user_id, reason=override_reason,
            detail={"open_rec_count": count, "overrode_open_items": count > 0},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"download event not recorded for {session_id}: {ex}",
                       exc_info=True)
    return count


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
            # UPDATE FIRST, and this ordering is the whole fix.
            #
            # The INSERT ... ON CONFLICT below reads as "update the row if it
            # exists", but Postgres validates the PROPOSED row's NOT NULL
            # constraints before it ever gets to conflict resolution. This
            # function's only non-route caller - the auto-resolve pass in
            # recalculate_session_scores - has no user_id to pass, and `user_id`
            # is NOT NULL. So the statement raised, the except below swallowed
            # it, and False came back.
            #
            # Measured 2026-08-17: auto-resolve had therefore NEVER resolved
            # anything. A producer could answer a recommendation, watch the score
            # rise correctly, and the card would sit in neither the open list nor
            # Reviewed - it was the client's "even after answering it is still
            # there" report. Every recommendation, every session, since the
            # feature shipped.
            #
            # Updating an existing row needs none of the columns the insert path
            # requires, so the common case can no longer be blocked by them. The
            # INSERT stays as the fallback for a rec that was never presented.
            updated = await conn.execute(
                """
                UPDATE sqs_recommendation_audit
                   SET action='resolved', action_at=$3, sqs_score_at_action=$4,
                       -- E&O 5.11: a manual resolve names its actor; the
                       -- auto-resolve pass passes NULL and the COALESCE keeps
                       -- the presented user, exactly as before.
                       user_id=COALESCE($5, user_id)
                 WHERE session_id=$1 AND rec_id=$2
                   AND (action IS NULL OR action = 'downloaded_anyway')
                """,
                session_id, rec_id, now, sqs_score_at_action, user_id,
            )
            if updated and updated.rsplit(" ", 1)[-1] != "0":
                return True

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
                        -- E&O 5.9: the row must name who DISMISSED, not who it
                        -- was presented to (presentation seeds the row first).
                        user_id=COALESCE(EXCLUDED.user_id, sqs_recommendation_audit.user_id),
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
                    -- V1 BETA EXIT (2026-08-28) - "Downloads with unresolved
                    -- issues preserve the open-item state."
                    --
                    -- This clause used to read `action IS NULL`. A download
                    -- with open items stamps `action='downloaded_anyway'` on
                    -- every unresolved row (`log_download_with_open_recs`), so
                    -- after ONE Download Anyway every later dismiss on this
                    -- session was a silent no-op: the UPDATE matched nothing
                    -- while the function still logged "Marked rec dismissed",
                    -- returned True, and appended `recommendation_dismissed`
                    -- to the event spine. The DISMISSED ITEMS table and
                    -- COMPLETE HISTORY then contradicted each other, the item
                    -- stayed "unresolved" on every later download record, and
                    -- `active_score_credits` (which reads action='dismissed')
                    -- never re-applied the credit - so a typed-reason credit
                    -- was granted once and silently reverted on the next
                    -- rescore.
                    --
                    -- `downloaded_anyway` is a MARKER that the producer shipped
                    -- with the item open, not a terminal resolution, so it must
                    -- not freeze the row. Its two siblings on this same table -
                    -- `mark_recommendation_resolved` and
                    -- `mark_recommendation_answer_recorded` - already accept
                    -- it; the dismiss writer was the odd one out.
                    --
                    -- Still guarded: a genuinely terminal action (resolved,
                    -- dismissed, answer_recorded) is never overwritten, so a
                    -- dismiss cannot undo a resolution or double-credit itself.
                    WHERE sqs_recommendation_audit.action IS NULL
                       OR sqs_recommendation_audit.action = 'downloaded_anyway'
                """,
                f"audit_{uuid.uuid4().hex}",
                session_id, user_id, form_id, rec_id,
                field, "suggestion", component, message, score_impact,
                now, sqs_score_at_action, model_version,
                "dismissed", now, sqs_score_at_action, override_reason,
            )
        logger.info(f"Marked rec {rec_id} dismissed (session {session_id})")
    except Exception as ex:
        logger.error(f"Failed to dismiss recommendation: {ex}")
        return False

    # E&O section 12: the row above is a latest-wins UPSERT - it holds the
    # CURRENT action and nothing else, so a dismiss -> reopen -> dismiss cycle
    # left one row and no history. The spine keeps each act (D49).
    try:
        from services.audit_history import (
            EVENT_RECOMMENDATION_DISMISSED, ACTION_DISMISSED,
        )
        await record_material_change(
            session_id, EVENT_RECOMMENDATION_DISMISSED,
            action=ACTION_DISMISSED, fact_key=field, field_name=field,
            form_id=form_id, source="producer", user_id=user_id,
            # "No reason provided" is the UI's SENTINEL for an unexplained
            # dismissal - `dismiss_earned_credit` already treats it as no
            # reason. Printing it as `Reason: No reason provided` in an E&O
            # record states that the producer gave one.
            reason=(override_reason if override_reason not in _NO_REASON_SENTINELS
                    else None),
            detail={"rec_id": rec_id, "message": message,
                    "component": component, "score_impact": score_impact,
                    "sqs_score_at_action": sqs_score_at_action},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"dismissal event not recorded for {rec_id}: {ex}", exc_info=True)
    return True


# ASYNC-SAFE
async def get_dismissed_recommendations(session_id: str) -> List[dict]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, form_id, field, message, score_impact,
                          override_reason, action_at, user_id
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND action='dismissed'
                   ORDER BY action_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get dismissed recommendations: {ex}")
        return []


# ── Dismissal score credits ──────────────────────────────────────────────────
# A dismissal with a real typed reason earns points; a plain dismiss does not.
# The predicate lives HERE rather than in the route because three callers need
# it - the dismiss route (to award), the reopen route (to reverse) and the
# rescore (to re-apply). It used to live in audit_routes with a docstring
# calling itself the single source of truth while the rescore path knew nothing
# about credits at all, which is why every recalculation silently erased them.

# The values that all mean "the producer dismissed this without explaining".
# Named once so the score credit and the E&O record cannot disagree about what
# counts as a reason.
_NO_REASON_SENTINELS = (None, "", "No reason provided")


def dismiss_earned_credit(override_reason, score_impact) -> bool:
    """Did this dismissal earn a score credit?

    Only a real typed reason (not the default sentinel) with a positive impact
    credits. A plain "Dismiss" hides the card and leaves the gap on record.
    """
    return (
        override_reason not in _NO_REASON_SENTINELS
        and score_impact is not None
        and score_impact > 0
    )


async def active_score_credits(
    session_id: str,
    facts: Optional[dict] = None,
) -> Tuple[int, List[dict]]:
    """Total dismissal credit still in force, plus the rows backing it.

    A credit compensates for a gap that could not be filled. Once the underlying
    field IS genuinely filled, the submission earns those points through the
    pillars instead, so the credit RETIRES rather than stacking on top of the
    real improvement (owner decision, 2026-08-16).

    Credits are capped at 100 in aggregate purely as a sanity bound; the real
    ceiling is applied later by sqs_service.final_score_with_credits.
    """
    try:
        from services.extraction_service import _fv
    except Exception:                                          # pragma: no cover
        _fv = None

    def _filled(key: str) -> bool:
        if not key or not isinstance(facts, dict):
            return False
        val = _fv(facts, key) if _fv else facts.get(key)
        if isinstance(val, (list, dict)):
            return bool(val)
        return str(val).strip() not in ("", "None", "null")

    total, kept = 0, []
    try:
        # ── C3 3.11: "never stack on top of the same improvement twice" ─────
        # Credits are keyed per RECOMMENDATION, and several recommendations can
        # point at ONE fact. Measured 2026-08-25: `_LOSS_RECOMMENDATION_FIELDS`
        # maps four different loss-history messages to `loss_history_years`,
        # two to `fein` and two to `loss_history_no_prior_losses_indicator`.
        # Each carries its own stable `rec_id`, so dismissing two cards about
        # the same missing fact - both with written reasons - paid for that one
        # gap twice.
        #
        # One credit per FIELD, the largest of the competing rows. Largest, not
        # first, because the rows are ordered by when the producer happened to
        # click and a credit must not depend on click order; and it is the
        # honest ceiling, since whichever card is worth most is what filling
        # that one field would actually have earned. Rows with NO field (a
        # document is needed, nothing to fill) cannot collide, so they are kept
        # individually - deduping them would silently merge unrelated asks.
        _best_by_field: dict = {}
        _fieldless: list = []
        for row in await get_dismissed_recommendations(session_id):
            if not dismiss_earned_credit(row.get("override_reason"), row.get("score_impact")):
                continue
            field = row.get("field")
            if _filled(field):
                logger.info(
                    "credit retired: session=%s rec=%s field=%s now filled",
                    session_id, row.get("rec_id"), field,
                )
                continue
            if not field:
                _fieldless.append(row)
                continue
            prev = _best_by_field.get(field)
            if prev is None or int(row["score_impact"]) > int(prev["score_impact"]):
                if prev is not None:
                    logger.info(
                        "credit de-duplicated: session=%s field=%s keeping rec=%s "
                        "(%s pts) over rec=%s (%s pts) - one improvement, one credit",
                        session_id, field, row.get("rec_id"), row.get("score_impact"),
                        prev.get("rec_id"), prev.get("score_impact"),
                    )
                _best_by_field[field] = row
            else:
                logger.info(
                    "credit de-duplicated: session=%s field=%s dropping rec=%s "
                    "(%s pts) - already credited by rec=%s",
                    session_id, field, row.get("rec_id"), row.get("score_impact"),
                    prev.get("rec_id"),
                )
        kept = list(_best_by_field.values()) + _fieldless
        total = sum(int(r["score_impact"]) for r in kept)
    except Exception as ex:
        logger.error(f"active_score_credits failed for {session_id}: {ex}")
        return 0, []
    return min(100, total), kept


# ASYNC-SAFE
async def mark_recommendation_answer_recorded(
    session_id: str,
    rec_id: str,
    producer_answer: str,
    model_version: str,
    field: Optional[str] = None,
    message: Optional[str] = None,
    score_impact: Optional[int] = None,
    user_id: Optional[str] = None,
    form_id: Optional[str] = None,
) -> bool:
    """Record the value a producer typed on a recommendation card.

    Deliberately does NOT write `action`. Whether the recommendation is actually
    resolved is decided by the recalculation that follows: its auto-resolve pass
    stamps 'resolved' only when the rec genuinely drops out of the recomputed
    recommendations. Stamping 'resolved' here instead would hide answers that did
    not in fact close the gap (several recs are satisfied by a combination of
    facts, e.g. rec_min_cope needs four) from the pre-download gate, which is the
    control that exists to stop exactly that.

    The two resulting states are both meaningful:
      producer_answer NOT NULL + action='resolved' -> answered and cleared; shows
          in "Reviewed" and can be reopened.
      producer_answer NOT NULL + action IS NULL    -> answered, gap remains; stays
          in the open list and still blocks download. Correct.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sqs_recommendation_audit (
                    id, session_id, user_id, form_id, rec_id, field,
                    recommendation_type, component, message, score_impact,
                    presented_at, model_version, producer_answer, answered_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (session_id, rec_id) DO UPDATE
                    SET producer_answer = EXCLUDED.producer_answer,
                        -- E&O 5.8: the answer's own timestamp and actor. Before
                        -- 2026-08-26 an answer landing via this UPDATE branch
                        -- carried NO timestamp (presented_at is INSERT-only) and
                        -- kept the PRESENTED user - an answer that never closed
                        -- its gap was permanently untimed.
                        answered_at = EXCLUDED.answered_at,
                        user_id = COALESCE(EXCLUDED.user_id, sqs_recommendation_audit.user_id),
                        field   = COALESCE(sqs_recommendation_audit.field,   EXCLUDED.field),
                        form_id = COALESCE(EXCLUDED.form_id, sqs_recommendation_audit.form_id),
                        score_impact = COALESCE(sqs_recommendation_audit.score_impact,
                                                EXCLUDED.score_impact)
                    WHERE sqs_recommendation_audit.action IS NULL
                       OR sqs_recommendation_audit.action = 'downloaded_anyway'
                """,
                f"audit_{uuid.uuid4().hex}",
                session_id, user_id, form_id, rec_id,
                field, "suggestion", None,
                # message is NOT NULL; a rec that first appeared on a recalculation
                # was never seeded by log_recommendations_presented, so fall back to
                # the rec_id rather than violating the constraint.
                message or rec_id,
                score_impact,
                now, model_version, producer_answer, now,
            )
        logger.info(f"Recorded producer answer for rec {rec_id} (session {session_id})")
    except Exception as ex:
        logger.error(f"Failed to record recommendation answer: {ex}")
        return False

    # E&O section 12. `producer_answer` / `answered_at` are OVERWRITTEN by the
    # UPDATE branch above, so answer -> reopen -> re-answer kept only the last
    # value. Each answer is now its own immutable event.
    try:
        from services.audit_history import (
            EVENT_RECOMMENDATION_ANSWERED, ACTION_ANSWERED,
        )
        await record_material_change(
            session_id, EVENT_RECOMMENDATION_ANSWERED,
            action=ACTION_ANSWERED, fact_key=field, field_name=field,
            form_id=form_id, new_value=producer_answer,
            source="producer", user_id=user_id,
            detail={"rec_id": rec_id, "message": message,
                    "score_impact": score_impact},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"answer event not recorded for {rec_id}: {ex}", exc_info=True)
    return True


# ASYNC-SAFE
async def get_reviewed_recommendations(session_id: str) -> List[dict]:
    """Recommendations the PRODUCER has acted on - the "Reviewed" section of the
    SQS panel. Two kinds: dismissed, and answered-with-a-value-that-cleared-it.

    The `producer_answer IS NOT NULL` half of the predicate matters: without it
    this would also return every rec the client's questionnaire auto-resolved,
    which the producer never touched and has nothing to reopen.

    Separate from get_dismissed_recommendations(), which stays dismissals-only
    because it feeds the E&O audit-trail export.
    """
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, form_id, field, message, score_impact,
                          override_reason, producer_answer, action, action_at
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1
                     AND (action = 'dismissed'
                          OR (action = 'resolved' AND producer_answer IS NOT NULL))
                   ORDER BY action_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get reviewed recommendations: {ex}")
        return []


# ASYNC-SAFE
async def get_recommendation_audit_row(session_id: str, rec_id: str) -> Optional[dict]:
    """One audit row, or None. Used by the reopen route to decide what has to be
    undone: whether a producer fact must be retracted, and whether a dismiss score
    credit was ever applied."""
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """SELECT rec_id, form_id, field, message, score_impact, component,
                          override_reason, producer_answer, action, action_at,
                          sqs_score_at_action, answered_at
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND rec_id=$2""",
                session_id, rec_id,
            )
        return dict(row) if row else None
    except Exception as ex:
        logger.error(f"Failed to get recommendation audit row: {ex}")
        return None


# ASYNC-SAFE
async def reopen_recommendation(session_id: str, rec_id: str) -> bool:
    """Return a reviewed recommendation to the open state.

    Nulls only the ACTION-STATE columns. `override_reason` and `producer_answer`
    are deliberately preserved: they are the record of what the producer last
    submitted, they are what the E&O export reports, and keeping them lets the
    reopened card prefill the previous text for editing. They are overwritten only
    when the producer submits a new value.

    Note this is the only writer that can clear `action`; both mark_* writers are
    latched on `action IS NULL` and cannot un-set it.
    """
    try:
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                """UPDATE sqs_recommendation_audit
                   SET action=NULL, action_at=NULL, sqs_score_at_action=NULL
                   WHERE session_id=$1 AND rec_id=$2""",
                session_id, rec_id,
            )
        logger.info(f"Reopened rec {rec_id} (session {session_id}): {result}")
        return True
    except Exception as ex:
        logger.error(f"Failed to reopen recommendation: {ex}")
        return False


# ASYNC-SAFE
async def get_download_audit_log(session_id: str) -> List[dict]:
    """"Download anyway" override notes for this session (download_audit table),
    oldest first. Read-only counterpart to log_download_with_open_recs()."""
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT override_note, open_rec_count, downloaded_at, user_id
                   FROM download_audit
                   WHERE session_id=$1
                   ORDER BY downloaded_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get download audit log: {ex}")
        return []


# ASYNC-SAFE
async def get_field_change_log(session_id: str) -> List[dict]:
    """Every recorded modification to a package field, oldest first, with the
    source that made it ('ai' / 'producer' / 'client_arq') and the before/after
    values. Read-only counterpart to log_field_change()."""
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT form_id, field_name, fact_key, source, previous_value,
                          new_value, confidence, previous_source, reason,
                          changed_at, user_id
                   FROM field_source_audit
                   WHERE session_id=$1
                   ORDER BY changed_at ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get field change log: {ex}")
        return []


# ── E&O append-only event history + SQS snapshots (client 5.11 / 5.12) ────────
# audit_events is INSERT-only. Nothing here or anywhere else may UPDATE or
# DELETE a row - that property is what makes it usable as history (5.11), and
# the reopen paths rely on it to preserve the state their table UPDATE erases.

# ASYNC-SAFE
async def log_audit_event(
    session_id: str,
    user_id: Optional[str],
    event_type: str,
    event_data: Optional[dict] = None,
    package_label: str = "",
    visibility: Optional[str] = None,
) -> bool:
    """Append one meaningful package event. Best-effort like every audit write:
    a failed row must never block the action it records - but it is logged with
    the traceback (D35).

    `visibility` defaults to the event type's own class (D50): the nine
    product-history types render in the navbar Activity Log, everything else is
    E&O record / debugging only. Passing it explicitly is for the adapter in
    `activity_service`, not for ordinary callers.
    """
    try:
        from services.audit_history import visibility_for
        vis = visibility or visibility_for(event_type)
    except Exception:                                          # pragma: no cover
        vis = visibility or "audit"
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_events
                   (id, session_id, user_id, event_type, event_data,
                    package_label, visibility, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)""",
                f"evt_{uuid.uuid4().hex}",
                session_id, user_id, event_type,
                json.dumps(event_data or {}, default=str),
                (package_label or "")[:120], vis,
                datetime.now(timezone.utc).isoformat(),
            )
        return True
    except Exception as ex:
        logger.error(f"Failed to log audit event {event_type} for {session_id}: {ex}",
                     exc_info=True)
        return False


# ── THE ONE WRITER for a material change (client section 12, D49) ─────────────

# ASYNC-SAFE
async def record_material_change(
    session_id: str,
    event_type: str,
    *,
    action: Optional[str] = None,
    fact_key: Optional[str] = None,
    field_name: Optional[str] = None,
    form_id: Optional[str] = None,
    previous_value=None,
    new_value=None,
    previous_source: Optional[str] = None,
    source: Optional[str] = None,
    user_id: Optional[str] = None,
    role: Optional[str] = None,
    reason: Optional[str] = None,
    detail: Optional[dict] = None,
) -> bool:
    """Append ONE immutable envelope to the spine for one material act.

    Every call site goes through `audit_history.build_change_envelope`, so the
    client's seven attributes (fact/field, original value, new value, actor,
    role, timestamp, reason/action) are present in a fixed shape on every event
    and can never migrate into free-form `detail` the way they did before H7.

    Called from INSIDE the existing audit writers, never from a route: a route
    can forget, a writer the action must already go through cannot. Same
    one-door reasoning as `fact_comparison` (D3) and `coverage_evidence` (H1).

    Best-effort by contract - the act has already happened and been persisted by
    the time this runs; a failed history row must never undo it.
    """
    if not session_id:
        return False
    try:
        from services.audit_history import build_change_envelope
        envelope = build_change_envelope(
            event_type=event_type, action=action, fact_key=fact_key,
            field_name=field_name, form_id=form_id,
            previous_value=previous_value, new_value=new_value,
            previous_source=previous_source, source=source,
            user_id=user_id, role=role, reason=reason, detail=detail,
        )
    except Exception as ex:                                    # pragma: no cover
        logger.error(f"record_material_change: envelope build failed for "
                     f"{event_type}/{session_id}: {ex}", exc_info=True)
        return False
    return await log_audit_event(session_id, user_id, event_type, envelope)


# ASYNC-SAFE
async def resolve_actors(user_ids) -> dict:
    """Map user ids to a display identity for the E&O record.

    Resolved at READ time, once per export, over the DISTINCT ids - not stamped
    on every event at write time. The id is the immutable anchor; the name is a
    display convenience, and every field edit writing an extra user lookup would
    put a query on the hottest path in the app for something the reader can do
    in one round trip.

    Never raises: an unresolvable id still renders, as the id.
    """
    ids = sorted({str(u).strip() for u in (user_ids or []) if str(u or "").strip()})
    if not ids:
        return {}
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, full_name, email FROM users WHERE id = ANY($1::text[])",
                ids,
            )
        return {
            str(r["id"]): {
                "id":    str(r["id"]),
                "name":  (r["full_name"] or "").strip(),
                "email": (r["email"] or "").strip(),
            }
            for r in rows
        }
    except Exception as ex:
        logger.warning(f"resolve_actors failed: {ex}")
        return {}


# ASYNC-SAFE
async def get_audit_events(session_id: str,
                           event_type: Optional[str] = None) -> List[dict]:
    """Chronological event history for one session, oldest first."""
    try:
        async with get_pool().acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    """SELECT event_type, user_id, event_data, created_at
                       FROM audit_events
                       WHERE session_id=$1 AND event_type=$2
                       ORDER BY created_at ASC""",
                    session_id, event_type,
                )
            else:
                rows = await conn.fetch(
                    """SELECT event_type, user_id, event_data, created_at
                       FROM audit_events
                       WHERE session_id=$1
                       ORDER BY created_at ASC""",
                    session_id,
                )
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("event_data"), str):
                try:
                    d["event_data"] = json.loads(d["event_data"])
                except Exception:                              # noqa: BLE001
                    pass
            out.append(d)
        return out
    except Exception as ex:
        logger.error(f"Failed to get audit events: {ex}")
        return []


def _snapshot_signature(package_sqs: Optional[dict]) -> dict:
    """The exact fields 5.12 says a new snapshot must be triggered by: raw SQS,
    displayed SQS, every pillar score, applied ceiling, ceiling reason. Pure -
    reads the scorer's own output (D33: never recomputed for display)."""
    p = package_sqs or {}
    pillars = p.get("pillars") or {}
    # The same cap prints with or without the appended remediation sentence
    # (" Fix: ...") depending on which path rendered it. The SUBSTANCE of the
    # 5.12 trigger is the cap and its cause - live run 2026-08-26 showed the
    # suffix alone fabricating a "ceiling reason changed" snapshot.
    reason = p.get("cap_reason")
    if isinstance(reason, str):
        reason = reason.split(" Fix:")[0].strip()
    return {
        "raw_sqs":        p.get("raw_sqs_score"),
        "displayed_sqs":  p.get("package_sqs_score"),
        "pillars":        {k: pillars.get(k) for k in sorted(pillars)},
        "ceiling":        p.get("cap_applied"),
        "ceiling_reason": reason,
    }


def _snapshots_differ(a: Optional[dict], b: Optional[dict]) -> bool:
    """True when any 5.12 trigger fires between two signatures - a score moved,
    a pillar moved, a ceiling appeared/disappeared or changed its reason."""
    return (a or {}) != (b or {})


# ASYNC-SAFE
async def log_sqs_snapshot_if_changed(
    session_id: str,
    user_id: Optional[str],
    package_sqs: Optional[dict],
    trigger: str,
) -> bool:
    """5.12: store a scoring snapshot when the score MATERIALLY changed, never
    per invisible recalculation. ``trigger='package_downloaded'`` always
    snapshots (a download is its own trigger in 5.12's list). The snapshot
    body is the scorer's emitted trace, per D33."""
    if not isinstance(package_sqs, dict) or not package_sqs:
        return False
    sig = _snapshot_signature(package_sqs)
    try:
        if trigger != "package_downloaded":
            prior = await get_audit_events(session_id, event_type="sqs_snapshot")
            if prior:
                last = (prior[-1].get("event_data") or {}).get("signature")
                if not _snapshots_differ(last, sig):
                    return False
        return await log_audit_event(
            session_id, user_id, "sqs_snapshot",
            {
                "signature":         sig,
                "trigger":           trigger,
                "tier":              package_sqs.get("tier"),
                "calculation_stage": package_sqs.get("calculation_stage"),
                "weights_version":   package_sqs.get("weights_version"),
                "score_trace":       package_sqs.get("score_trace"),
            },
        )
    except Exception as ex:
        logger.error(f"SQS snapshot failed for {session_id}: {ex}", exc_info=True)
        return False


# ASYNC-SAFE
async def get_producer_answers(session_id: str) -> List[dict]:
    """Every value a producer typed on a recommendation card (5.8), whatever
    its current action state - including answered-but-still-open rows, which
    get_reviewed_recommendations deliberately excludes."""
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT rec_id, form_id, field, message, producer_answer,
                          answered_at, action, action_at, user_id
                   FROM sqs_recommendation_audit
                   WHERE session_id=$1 AND producer_answer IS NOT NULL
                   ORDER BY COALESCE(answered_at, presented_at) ASC""",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as ex:
        logger.error(f"Failed to get producer answers: {ex}")
        return []


# ASYNC-SAFE
async def get_underwriting_confirmations(session_id: str) -> List[dict]:
    """Every Data Consistency resolution on this submission (5.10): chosen
    value, prior value, all competing candidates with their per-document
    sources, actor, timestamp, conflict reason, optional producer note.
    The table existed since C1; this is its FIRST reader - the evidence was
    stored and unreachable until the E&O export gained this section."""
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT fact_key, label, confirmed_value, previous_value,
                          confirmed_at, candidates, reason, note, user_id
                   FROM underwriting_confirmation_audit
                   WHERE session_id=$1
                   ORDER BY confirmed_at ASC""",
                session_id,
            )
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("candidates"), str):
                try:
                    d["candidates"] = json.loads(d["candidates"])
                except Exception:                              # noqa: BLE001
                    d["candidates"] = []
            out.append(d)
        return out
    except Exception as ex:
        logger.error(f"Failed to get underwriting confirmations: {ex}")
        return []


# ASYNC-SAFE
async def get_package_download_log(session_id: str) -> List[dict]:
    """Every download of this package from acord_audit_log (5.13): action,
    form, timestamp, the score at download, the file checksum, and the FULL
    list of open items recorded server-side at that moment. This table was
    written on every download since the feature shipped and never read by the
    E&O export - the record printed a count while the list sat here."""
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT action, form_id, form_name, timestamp,
                          sqs_score_at_download, unresolved_issues, file_checksum
                   FROM acord_audit_log
                   WHERE session_id=$1 AND action LIKE 'download%'
                   ORDER BY timestamp ASC""",
                session_id,
            )
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("unresolved_issues"), str):
                try:
                    d["unresolved_issues"] = json.loads(d["unresolved_issues"])
                except Exception:                              # noqa: BLE001
                    pass
            out.append(d)
        return out
    except Exception as ex:
        logger.error(f"Failed to get package download log: {ex}")
        return []


# Max characters of any single fact value rendered into the export. Long
# narrative facts (operations descriptions, remarks) are truncated rather than
# dropped - the record is meant to show WHAT was captured and from WHERE, not
# to be a second copy of the whole document.
_EXPORT_VALUE_MAX = 300


def _flatten_fact(key: str, raw, facts: Optional[dict] = None) -> Optional[dict]:
    """Normalize one entry of the session `facts` dict into a flat
    {fact/value/source/confidence} row for the audit export.

    Facts are stored either as a provenance envelope ({"value","confidence",
    "source"}) or, for older/simpler entries, as a bare scalar. Schedules
    (vehicles, drivers, locations, loss runs) are lists - those are summarized
    by row count rather than dumped, since each row is itself a dict and the
    detail already lives in the generated forms. Returns None for empty facts
    so the export shows what WAS captured, not a wall of blanks.

    ``facts`` (the whole dict) is passed through to ``derive_states`` - without
    it the conflicting / not_applicable / unable_to_determine branches can
    never fire (they read the ``_uw_conflict_keys`` / denied-lines /
    ``_rejected_facts`` sidecars), which silently reduced the state axes to
    two values in every export before 2026-08-26.
    """
    if isinstance(raw, dict) and "value" in raw:
        value = raw.get("value")
        source = raw.get("source") or ""
        confidence = raw.get("confidence") or ""
    else:
        value, source, confidence = raw, "", ""
    # V1 plan C1 F5: the two state axes (client 1.3 / 1.4) and the 125 doc's
    # four-word projection, derived from the same envelope so the export can
    # never disagree with the session.
    try:
        from services.fact_state import derive_states, display_state
        _st = derive_states(key, raw, facts)
    except Exception:                                         # noqa: BLE001
        _st = {}

    if value is None or value == "" or value == [] or value == {}:
        return None

    if isinstance(value, (list, tuple)):
        display = f"[{len(value)} row(s) captured]"
    elif isinstance(value, dict):
        display = "[structured value]"
    else:
        display = str(value)
        if len(display) > _EXPORT_VALUE_MAX:
            display = display[:_EXPORT_VALUE_MAX] + "…(truncated)"

    row = {
        "fact": key,
        "value": display,
        "source": source,
        "confidence": confidence,
    }
    if _st:
        row["value_state"] = _st.get("value_state")
        row["evidence_state"] = _st.get("evidence_state")
        if _st.get("evidence_actor"):
            row["evidence_actor"] = _st["evidence_actor"]
        row["display_state"] = display_state(_st.get("value_state"), _st.get("evidence_state"))
    # E&O 5.7: how a derived value was produced - rule + input facts, written
    # onto the envelope by the deriving code itself.
    if isinstance(raw, dict) and isinstance(raw.get("derivation"), dict):
        row["derivation"] = raw["derivation"]
    # D19's scoped store: LOB / policy scope for this fact where recorded.
    try:
        scoped = (facts or {}).get("_scoped") or {}
        entries = scoped.get(key)
        if isinstance(entries, list) and entries:
            row["scope"] = [
                {"value": str(e.get("value") or "")[:80],
                 **{k: v for k, v in (e.get("scope") or {}).items() if v}}
                for e in entries[:6] if isinstance(e, dict)
            ]
    except Exception:                                         # noqa: BLE001
        pass
    return row


# ASYNC-SAFE
async def get_audit_trail_export(session_id: str) -> dict:
    """Full E&O record for one submission, for the producer to download.

    Two halves, both required by the client (Figure 6 + the 2026-07-28
    follow-up "should be in addition to traditional E&O... a record of all
    inputs (including source) and modifications to the package"):

      1. DECISIONS - every reason the producer gave: the package-level
         marketing reason, each dismissed recommendation, each issue-status
         override, each download-anyway note.
      2. INPUTS & MODIFICATIONS - the documents the package was built from,
         every captured fact with the source that produced it (AI extraction /
         producer edit / client questionnaire), and the chronological change
         log of every recorded field modification with its before/after values.

    Purely a read aggregation of data these tables already hold - writes
    nothing, and never touches scoring, dismiss-credit, or generation. Session
    lookup is best-effort: if the session blob is gone (facts-retention job) the
    durable audit tables still produce a usable record, which is exactly why the
    reason/change data was put in its own tables in the first place.
    """
    marketing_reason = await get_marketing_reason(session_id)
    dismissed = await get_dismissed_recommendations(session_id)
    answered = [r for r in await get_producer_answers(session_id)
                if r.get("action") != "dismissed"]
    issue_statuses = [s for s in await get_issue_statuses(session_id) if s.get("reason")]
    downloads = await get_download_audit_log(session_id)
    field_changes = await get_field_change_log(session_id)
    conflict_resolutions = await get_underwriting_confirmations(session_id)
    package_downloads = await get_package_download_log(session_id)
    events = await get_audit_events(session_id)
    sqs_snapshots = [e for e in events if e.get("event_type") == "sqs_snapshot"]
    # F (client section 12): submission_integrity_audit's first reader. Two of
    # the client's "producer override" events were written here and never shown.
    integrity_overrides = await get_integrity_audit_log(session_id)

    # ── The chronological history (client section 12's Desired Outcome) ───────
    # ONE list, built from the append-only spine, with every actor resolved to a
    # person. This is the half the record was missing: the twelve sections below
    # are DETAIL VIEWS of current state, and before H7 the modification history
    # had to be inferred from them. Nothing here is reconstructed - each row was
    # written by the workflow at the moment the act happened (D49).
    history: List[dict] = []
    actors: dict = {}
    try:
        from services.audit_history import (
            normalize_event, actor_ids_in, EVENT_SQS_SNAPSHOT,
        )
        _actor_ids = actor_ids_in(events)
        # Every other section names an actor too, and they are the same people.
        for _row in (list(field_changes) + list(conflict_resolutions)
                     + list(answered) + list(dismissed) + list(issue_statuses)
                     + list(downloads) + list(integrity_overrides)):
            if isinstance(_row, dict) and _row.get("user_id"):
                _actor_ids.add(str(_row["user_id"]))
        actors = await resolve_actors(_actor_ids)
        # Score snapshots have their own SCORE HISTORY section with their own
        # rendering; repeating them here would bury the human acts.
        history = [normalize_event(e, actors) for e in events
                   if e.get("event_type") != EVENT_SQS_SNAPSHOT]
    except Exception as ex:                                    # noqa: BLE001
        logger.warning(f"Audit export: history assembly failed for {session_id}: {ex}",
                       exc_info=True)

    def _with_actor(rows):
        """Attach the resolved person to any row carrying a user_id."""
        out = []
        for r in rows or []:
            if not isinstance(r, dict):
                out.append(r)
                continue
            r = dict(r)
            who = actors.get(str(r.get("user_id") or ""))
            if who:
                r["actor_name"]  = who.get("name") or who.get("email") or ""
                r["actor_email"] = who.get("email") or ""
            out.append(r)
        return out

    documents: List[dict] = []
    inputs: List[dict] = []
    generated_forms: List[str] = []
    rejected_facts: List[dict] = []
    client_receipts: List[dict] = []
    try:
        from repositories.session_repository import get_processing_session
        session = await get_processing_session(session_id)
        facts = session.get("facts") or {}
        # A retention-tombstoned session ({"purged": true, ...}) has no inputs
        # to list - without this guard the tombstone's own keys would render
        # as fact rows.
        if facts.get("purged") is True:
            facts = {}
        docs = session.get("docs") or []

        # 5.2 Source Document Record - from the documents the session actually
        # stores. The old read of `doc_summary` was a key that only ever
        # existed in HTTP responses and was never persisted, so SOURCE
        # DOCUMENTS printed "(none recorded)" on EVERY export since the
        # feature shipped. `doc_summary` remains as the legacy fallback for
        # any old session that might carry it.
        for d in (docs or session.get("doc_summary") or []):
            documents.append({
                "filename":   d.get("filename") or "",
                "doc_id":     d.get("doc_id") or "",
                "doc_type":   d.get("doc_type_label") or d.get("doc_type") or "",
                "confidence": d.get("doc_type_confidence") or "",
                "classified_by": d.get("doc_type_source") or "",
                "overridden": bool(d.get("doc_type_overridden")),
                "excluded":   bool(d.get("excluded")),
                "uploaded_at": d.get("uploaded_at") or session.get("created_at") or "",
                "uploaded_by": d.get("uploaded_by") or session.get("user_id") or "",
            })

        # 5.3-5.6 fact-level lineage: rejoin each merged fact against every
        # document's OWN extraction and page-marked text. Computed, not
        # stored - both sides of the join already live on the session.
        doc_index = []
        try:
            from services.fact_lineage import build_doc_index, sources_for_fact
            doc_index = build_doc_index(docs)
        except Exception as _lx:                              # noqa: BLE001
            logger.warning(f"Audit export: lineage index unavailable: {_lx}",
                           exc_info=True)

        for key, raw in sorted(facts.items()):
            # Private sidecars (_scoped, _uw_conflict_keys, ...) and the
            # internal dec index are machinery, not captured inputs - before
            # 2026-08-26 they rendered as junk rows like "_scoped:
            # [structured value] / Source: unspecified".
            if key.startswith("_") or key == "dec_page_entries":
                continue
            # A BARE Python boolean is pipeline bookkeeping by construction
            # (dec_states_payroll_basis, renewal_dates_routed): extraction
            # wraps every real boolean answer in an envelope as the string
            # "True"/"False" (_annotate_facts), so a bare bool can only have
            # been written by internal code. Live run 2026-08-26: these
            # rendered as 'True / Source: unspecified' - the exact junk-row
            # class the client reported.
            if isinstance(raw, bool):
                continue
            row = _flatten_fact(key, raw, facts)
            if row:
                if doc_index:
                    try:
                        row["sources"] = sources_for_fact(key, raw, doc_index)
                    except Exception:                          # noqa: BLE001
                        row["sources"] = []
                inputs.append(row)

        # "What remained unresolved": values seen and REFUSED, with the reason
        # the pipeline recorded when it refused them.
        rej = facts.get("_rejected_facts")
        if isinstance(rej, dict):
            rejected_facts = [{"fact": k, "reason": str(v)[:300]}
                              for k, v in sorted(rej.items())]

        generated_forms = sorted((session.get("generated_forms") or {}).keys())

        # 5.8: the client's questionnaire answers with respondent identity and
        # timestamp, from the immutable encrypted receipts.
        try:
            from services.arq_receipt_service import get_receipts_for_session
            owner = str(session.get("user_id") or "")
            if owner:
                client_receipts = await get_receipts_for_session(session_id, owner)
        except Exception as _rx:                              # noqa: BLE001
            logger.warning(f"Audit export: receipts unavailable: {_rx}")
    except Exception as ex:
        logger.warning(f"Audit export: session detail unavailable for {session_id}: {ex}")

    return {
        "session_id": session_id,
        "marketing_reason": marketing_reason,
        "dismissed_recommendations": _with_actor(dismissed),
        "answered_recommendations": _with_actor(answered),
        "issue_status_overrides": _with_actor(issue_statuses),
        "download_anyway_log": _with_actor(downloads),
        "package_downloads": package_downloads,
        "conflict_resolutions": _with_actor(conflict_resolutions),
        "integrity_overrides": _with_actor(integrity_overrides),
        "documents": documents,
        "inputs": inputs,
        "rejected_facts": rejected_facts,
        "client_receipts": client_receipts,
        "field_modifications": _with_actor(field_changes),
        # The one chronological history (client section 12). `audit_events` is
        # kept alongside it so the existing EVENT LOG section and any consumer
        # written against the raw rows keeps working.
        "history": history,
        "audit_events": events,
        "sqs_snapshots": sqs_snapshots,
        "generated_forms": generated_forms,
    }


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
    except Exception as ex:
        logger.error(f"Failed to set issue status: {ex}")
        return False

    # E&O section 12: another latest-wins UPSERT. open -> resolved -> reopened
    # -> dismissed left ONE row carrying only the last status, and the export
    # showed the row only when it happened to carry a reason - so a resolve
    # without a note was invisible. Each transition is now an event.
    try:
        from services.audit_history import (
            EVENT_ISSUE_STATUS_CHANGED, ACTION_RESOLVED, ACTION_DISMISSED,
            ACTION_REOPENED,
        )
        _action = {"resolved": ACTION_RESOLVED, "dismissed": ACTION_DISMISSED,
                   "open": ACTION_REOPENED}.get(status, status)
        await record_material_change(
            session_id, EVENT_ISSUE_STATUS_CHANGED,
            action=_action, fact_key=source_fact, field_name=field,
            form_id=form_id, new_value=status,
            source="producer", user_id=user_id, reason=reason,
            detail={"issue_id": issue_id, "rule_code": rule_code,
                    "message": message},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"issue status event not recorded for {issue_id}: {ex}",
                       exc_info=True)
    return True


# ASYNC-SAFE
async def get_issue_statuses(session_id: str) -> List[dict]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT issue_id, status, reason, form_id, field, rule_code,
                          source_fact, message, updated_at, user_id
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

    # E&O section 12: keeping a package the system flagged IS the client's
    # "producer override". Only the override reaches the spine - an ordinary
    # "remove the odd document" resolution is housekeeping, not an override of
    # a system determination, and the full row stays in submission_integrity_audit
    # either way (which now has a reader - see get_integrity_audit_log).
    if overridden:
        try:
            from services.audit_history import EVENT_PRODUCER_OVERRIDE, ACTION_OVERRIDDEN
            await record_material_change(
                session_id, EVENT_PRODUCER_OVERRIDE,
                action=ACTION_OVERRIDDEN,
                field_name="submission_integrity",
                new_value=action, source="producer", user_id=user_id,
                detail={"kind": "submission_integrity",
                        "integrity_status": integrity.get("status"),
                        "review_required": bool(integrity.get("review_required")),
                        "detected_entities": integrity.get("detected_entities") or [],
                        "removed_doc_ids": list(removed_doc_ids or [])},
            )
        except Exception as ex:                                # pragma: no cover
            logger.warning(f"integrity override event not recorded: {ex}", exc_info=True)


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

    # E&O section 12: correcting the type the classifier chose is an override of
    # a generated value - the same act as editing an AI-filled field, one level
    # up. The record used to print only "Document type was manually corrected by
    # the user" off the CURRENT session blob, with no actor, no timestamp and no
    # previous type, while all three sat unread in submission_integrity_audit.
    try:
        from services.audit_history import EVENT_PRODUCER_OVERRIDE, ACTION_OVERRIDDEN
        await record_material_change(
            session_id, EVENT_PRODUCER_OVERRIDE,
            action=ACTION_OVERRIDDEN, field_name="document_type",
            previous_value=previous_doc_type, new_value=new_doc_type,
            previous_source="ai_high", source="producer", user_id=user_id,
            detail={"kind": "document_reclassified",
                    "doc_id": str(doc_id), "reclassify_action": action},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"reclassification event not recorded for {doc_id}: {ex}",
                       exc_info=True)


# ASYNC-SAFE
async def get_integrity_audit_log(session_id: str) -> List[dict]:
    """Submission Integrity verdicts, resolutions and document reclassifications.

    FIRST READER of `submission_integrity_audit`. The table had three writers
    and no reader anywhere in the codebase - exactly the defect C5-A fixed for
    `underwriting_confirmation_audit`, recurring one table over. Two of the
    client's section-12 "producer override" events lived here, recorded and
    invisible: keeping a package the system flagged for multiple insureds, and
    correcting the document type the classifier chose.

    `integrity_assessed` rows are excluded - they are the system's own verdict,
    not a human act, and the resolution row carries the verdict it acted on.
    """
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_type, action, overridden, integrity_status,
                          confidence, review_required, detected_entities,
                          removed_doc_ids, created_submissions,
                          doc_id, previous_doc_type, new_doc_type,
                          user_id, created_at
                   FROM submission_integrity_audit
                   WHERE session_id=$1 AND event_type <> 'integrity_assessed'
                   ORDER BY created_at ASC""",
                session_id,
            )
        out = []
        for r in rows:
            d = dict(r)
            for k in ("detected_entities", "removed_doc_ids", "created_submissions"):
                if isinstance(d.get(k), str):
                    try:
                        d[k] = json.loads(d[k])
                    except Exception:                          # noqa: BLE001
                        d[k] = []
            out.append(d)
        return out
    except Exception as ex:
        logger.error(f"Failed to get integrity audit log: {ex}")
        return []


# ASYNC-SAFE
async def log_underwriting_confirmation(
    session_id: str,
    user_id: Optional[str],
    fact_key: str,
    label: str,
    confirmed_value: str,
    previous_value: Optional[str],
    candidates: Optional[list] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Record a user-confirmed underwriting value (Beta Report §4.3 / §5.1).

    ``candidates`` (V1 plan C1 F10): every competing value the picker showed,
    with its sources and scope, captured BEFORE the confirmation rewrote the
    merged fact - the client's "resolution must not delete the prior
    evidence". ``reason`` is the comparator's reason for the conflict.

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
                    confirmed_value, previous_value, confirmed_at,
                    candidates, reason, note
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                f"uwc_{uuid.uuid4().hex}",
                session_id,
                str(user_id) if user_id is not None else None,
                fact_key,
                label,
                confirmed_value,
                previous_value,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(candidates) if candidates is not None else None,
                reason,
                (str(note).strip()[:2000] or None) if note else None,
            )
        logger.info(
            "Logged underwriting confirmation session=%s field=%s value=%r",
            session_id, fact_key, confirmed_value,
        )
    except Exception as ex:
        logger.error(f"Failed to log underwriting confirmation: {ex}")

    # E&O section 12: this table is genuinely append-only, but it was NOT on the
    # spine - so a conflict resolution changed a fact and never appeared in the
    # chronological modification history, only in its own section. The competing
    # values stay in `candidates` on the row above (C1 F10); the event carries
    # the decision.
    try:
        from services.audit_history import EVENT_CONFLICT_RESOLVED, ACTION_CONFIRMED
        # D16 stamps the suggested value BEFORE confirmation, so confirming the
        # suggestion leaves previous == confirmed. C5-D fix 7 suppressed that
        # "(was: same thing)" in the resolutions section; printing it here as
        # `"$3,000,000" -> "$3,000,000"` is the same defect one layer up, and it
        # reads as a change that never happened.
        _prev = (previous_value
                 if str(previous_value or "").strip() != str(confirmed_value or "").strip()
                 else None)
        await record_material_change(
            session_id, EVENT_CONFLICT_RESOLVED,
            action=ACTION_CONFIRMED, fact_key=fact_key, field_name=label,
            previous_value=_prev, new_value=confirmed_value,
            source="producer", user_id=user_id,
            reason=note or reason,
            detail={"label": label, "conflict_reason": reason,
                    "producer_note": note,
                    "candidate_count": len(candidates or [])},
        )
    except Exception as ex:                                    # pragma: no cover
        logger.warning(f"conflict resolution event not recorded for {fact_key}: {ex}",
                       exc_info=True)
