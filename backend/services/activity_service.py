"""
activity_service.py
Durable, user-level package activity log - now an ADAPTER over the one event
spine (`audit_events`), not a second store.

Records discrete package events (forms generated, SQS scored, questionnaire
sent/opened/in-progress/submitted, answers applied, reminders, downloads) so the
producer can see where each package stands in the navbar Activity Log -
persisting even after the processing session is closed.

ONE MODEL (V1 H7 / D50, owner ruling 2026-08-27)
------------------------------------------------
This module used to own `activity_events`, a table with a schema near-identical
to `audit_events` recording the SAME acts under different names
(`answers_applied` / `client_answers_applied`, `sqs_scored` / `sqs_snapshot`,
and one download writing three rows across three stores). The client's section
12 asked for "one underlying event/history model that can serve: product
history; debugging; source lineage; E&O Audit Record" - so writes now go to the
spine, tagged `visibility='product'`, and reads come back from it.

What deliberately did NOT change:
- the event-type STRINGS. `ActivityLogModal.jsx` renders per type and falls back
  to a grey dot with the raw type name, so renaming any of these would silently
  degrade the live Activity Log. One model does not mean one event name.
- `record_event()`'s signature, so no call site moves.
- the `{id, session_id, package_label, event_type, event_data, created_at}` read
  shape the UI consumes.
- the legacy `activity_events` rows. They are still read and merged (see
  get_user_activity) - the table is frozen, not dropped, so nothing a producer
  has already seen disappears from their feed.

Design rules (unchanged):
- record_event() NEVER raises into the caller. Activity logging is a
  best-effort side channel; a failure here must never break the flow that
  triggered it (form generation, ARQ submit, download, etc.).
- Call sites still pass only a client FIRST name, never the client email. NOTE
  (H7): the spine is a more sensitive table than `activity_events` was - it
  already carries `client_email` on `client_answers_applied` (arq_service) - so
  the old "this table needs no field-level encryption because it holds no fresh
  PII" reasoning belongs to the retired table, not to this one. Keep passing
  first names only; do not treat the spine as PII-free.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from services.audit_history import (
    VISIBILITY_PRODUCT,
    EVENT_FORMS_GENERATED, EVENT_SQS_SCORED, EVENT_ARQ_SENT, EVENT_ARQ_OPENED,
    EVENT_ARQ_IN_PROGRESS, EVENT_ARQ_SUBMITTED, EVENT_ANSWERS_APPLIED,
    EVENT_REMINDER_SENT, EVENT_DOWNLOAD,
)

logger = logging.getLogger(__name__)

# The nine canonical product-history event types now live in audit_history (the
# one vocabulary) and are re-exported here so every existing importer - the ARQ
# routes, the download routes, form_routes - keeps working untouched.
__all__ = [
    "record_event", "get_user_activity", "derive_package_label",
    "EVENT_FORMS_GENERATED", "EVENT_SQS_SCORED", "EVENT_ARQ_SENT",
    "EVENT_ARQ_OPENED", "EVENT_ARQ_IN_PROGRESS", "EVENT_ARQ_SUBMITTED",
    "EVENT_ANSWERS_APPLIED", "EVENT_REMINDER_SENT", "EVENT_DOWNLOAD",
]


def derive_package_label(facts: Optional[dict]) -> str:
    """Best-effort human name for a package, from the extracted facts.

    Falls back to an empty string; the frontend then groups purely by
    session_id and shows a generic label.
    """
    if not isinstance(facts, dict):
        return ""
    for key in ("applicant_name", "named_insured", "insured_name", "business_name"):
        val = facts.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:120]
    return ""


# ASYNC-SAFE
async def record_event(
    user_id: str,
    session_id: Optional[str],
    event_type: str,
    event_data: Optional[dict] = None,
    package_label: str = "",
) -> None:
    """Append one product-history event to the spine. Best-effort, never raises.

    Signature and payloads are unchanged from the `activity_events` era so no
    call site had to move; only the destination did (D50).

    `session_id` may be None here where the old nullable column allowed it, but
    `audit_events.session_id` is NOT NULL - every live call site passes one
    (`arq_sessions.session_id` is itself NOT NULL, verified), so a missing id is
    a bug in the caller, not a shape to support. It is skipped with a warning
    rather than raising into a flow that has already succeeded.
    """
    if not user_id or not event_type:
        return
    if not session_id:
        logger.warning("activity record_event skipped (%s): no session_id", event_type)
        return
    try:
        event_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc).isoformat()
        payload  = event_data if isinstance(event_data, dict) else {}
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_events
                   (id, session_id, user_id, event_type, event_data,
                    package_label, visibility, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)""",
                event_id, str(session_id), str(user_id), event_type,
                json.dumps(payload, default=str), (package_label or "")[:120],
                VISIBILITY_PRODUCT, now,
            )
    except Exception as ex:
        logger.warning(f"activity record_event failed ({event_type}): {ex}")


# ASYNC-SAFE
async def get_user_activity(user_id: str, limit: int = 200) -> List[dict]:
    """Newest-first product-history feed for a user.

    Reads the spine's product-visible rows and UNIONs the frozen legacy
    `activity_events` table, so a producer's existing feed survives the move
    (D50) - nothing they have already seen disappears. The legacy half is a
    fixed set that can only shrink; once it is empty the UNION costs nothing.

    The `visibility='product'` filter is what keeps E&O-only events - every
    field edit, every dismissal, every score snapshot - out of a feed built to
    show nine package milestones. Without it the Activity Log would render them
    as unlabelled raw event types (ActivityLogModal falls back to the type name
    with a grey dot).
    """
    try:
        limit = max(1, min(int(limit), 500))
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, package_label, event_type,
                          event_data, created_at
                     FROM audit_events
                    WHERE user_id=$1 AND visibility=$3
                    UNION ALL
                   SELECT id, session_id, package_label, event_type,
                          event_data::jsonb, created_at
                     FROM activity_events
                    WHERE user_id=$1
                 ORDER BY created_at DESC
                    LIMIT $2""",
                str(user_id), limit, VISIBILITY_PRODUCT,
            )
        out = []
        for r in rows:
            d = dict(r)
            data = d.get("event_data")
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            d["event_data"] = data or {}
            out.append(d)
        return out
    except Exception as ex:
        logger.warning(f"activity get_user_activity failed: {ex}")
        return []
