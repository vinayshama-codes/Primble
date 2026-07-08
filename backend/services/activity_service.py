"""
activity_service.py
Durable, user-level package activity log.

Records discrete package events (forms generated, SQS scored, questionnaire
sent/opened/in-progress/submitted, answers applied, reminders, downloads) into
the `activity_events` table so the producer can see where each package stands
in the navbar Activity Log - persisting even after the processing session is
closed.

Design rules:
- record_event() NEVER raises into the caller. Activity logging is a
  best-effort side channel; a failure here must never break the flow that
  triggered it (form generation, ARQ submit, download, etc.).
- No fresh PII is stored: event_data keeps only a client FIRST name where
  relevant (see arq_routes call sites), never the client email, so the log
  table needs no field-level encryption.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool

logger = logging.getLogger(__name__)

# Canonical event types (kept as constants so call sites don't drift).
EVENT_FORMS_GENERATED   = "forms_generated"
EVENT_SQS_SCORED        = "sqs_scored"
EVENT_ARQ_SENT          = "questionnaire_sent"
EVENT_ARQ_OPENED        = "questionnaire_opened"
EVENT_ARQ_IN_PROGRESS   = "questionnaire_in_progress"
EVENT_ARQ_SUBMITTED     = "questionnaire_submitted"
EVENT_ANSWERS_APPLIED   = "answers_applied"
EVENT_REMINDER_SENT     = "reminder_sent"
EVENT_DOWNLOAD          = "download"


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
    """Insert one activity event. Swallows all errors (best-effort logging)."""
    if not user_id or not event_type:
        return
    try:
        event_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc).isoformat()
        payload  = event_data if isinstance(event_data, dict) else {}
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO activity_events
                   (id, user_id, session_id, package_label, event_type, event_data, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                event_id, str(user_id), session_id, (package_label or "")[:120],
                event_type, json.dumps(payload), now,
            )
    except Exception as ex:
        logger.warning(f"activity record_event failed ({event_type}): {ex}")


# ASYNC-SAFE
async def get_user_activity(user_id: str, limit: int = 200) -> List[dict]:
    """Newest-first activity for a user."""
    try:
        limit = max(1, min(int(limit), 500))
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, package_label, event_type, event_data, created_at
                   FROM activity_events
                   WHERE user_id=$1
                   ORDER BY created_at DESC
                   LIMIT $2""",
                str(user_id), limit,
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
