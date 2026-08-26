"""
arq_receipt_service.py
Immutable, read-only client response receipt (Figure 21).

WHY THIS EXISTS
---------------
Before this, a submitted questionnaire left three separate traces and none of
them was a record of the submission:

  * `arq_sessions.answers` - a WORKING row. Later stages read it, and any future
    edit/resubmit path would overwrite it. "What the client said" would be gone.
  * `activity_events` - stored only a COUNT (`{"fields": 12}`). Useful for a
    timeline, useless for "what exactly did they tell us on the 14th?".
  * The producer UI - showed follow-up lists ("not sure", "needs confirming")
    but never the answers themselves.

A receipt is written ONCE, at submit, and is never updated or deleted by any
code path in this module. That immutability is the entire point: it is what
makes the row admissible as a record rather than a cache of current state.

DESIGN RULES
------------
1. NEVER raise into the submit flow. A receipt is a record OF a submission, not
   a precondition for one - a client must never see their submission fail
   because the audit side had a bad day. Every public function here returns a
   falsy value on failure and logs.
2. The payload is encrypted (Fernet, via utils.crypto) exactly like
   processing_sessions.facts. It is the client's own PII: names, revenue,
   loss history, vehicle schedules.
3. Counts are stored OUTSIDE the ciphertext so the producer panel can summarise
   a receipt without decrypting it.
4. The receipt is built from the PERSISTED arq row, re-read after the submit
   write - not from the request body. What is recorded is therefore exactly
   what the server accepted and stored, including its own normalization, not
   what the browser claimed to send.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from services import schedule_capture
from utils.crypto import decrypt_field, encrypt_field

logger = logging.getLogger(__name__)

# A single narrative answer is capped so one pathological entry cannot bloat the
# row. Generous on purpose - the point of a receipt is fidelity, and the submit
# path itself already clamps scalar answers to 500 chars.
_MAX_VALUE_LEN    = 4000
_MAX_QUESTION_LEN = 300
# Schedules can hold a whole fleet. The rows are kept (that IS the answer), but
# bounded so a crafted payload cannot write an unbounded row.
_MAX_SCHEDULE_ROWS = 200

# Item kinds, mirroring how the producer panel already talks about these.
KIND_ANSWER   = "answer"      # a real value the client provided
KIND_SCHEDULE = "schedule"    # a table of rows
KIND_NOT_SURE = "not_sure"    # explicitly "I'm not sure" - needs follow-up
KIND_BLANK    = "blank"       # asked, left empty


def _clip(val, limit: int) -> str:
    return str(val or "")[:limit]


def build_receipt_payload(arq: dict) -> dict:
    """Assemble the receipt body from a SUBMITTED arq row.

    Walks `questions` (the list as it was shown to the client) so the receipt
    preserves the original question order and text, and records what became of
    each one. Iterating questions rather than answer keys also means a crafted
    answer payload cannot inject rows that were never asked.
    """
    questions = arq.get("questions") or []
    answers   = arq.get("answers") or {}
    not_sure  = arq.get("not_sure_fields") or []
    review    = arq.get("review_fields") or []

    # field_name -> reason, for the "saved but worth confirming" annotation.
    review_by_field = {}
    for r in review:
        if isinstance(r, dict) and r.get("field_name"):
            review_by_field[r["field_name"]] = _clip(r.get("reason"), 200)

    not_sure_fields = {
        r.get("field_name") for r in not_sure
        if isinstance(r, dict) and r.get("field_name")
    }
    # Older rows stored not_sure as a bare list of field-name strings.
    not_sure_fields |= {r for r in not_sure if isinstance(r, str)}

    items: List[dict] = []
    answered = 0

    for q in questions:
        if not isinstance(q, dict):
            continue
        field_name = q.get("field_name")
        if not field_name:
            continue

        item = {
            "field_name": field_name,
            "question":   _clip(q.get("question"), _MAX_QUESTION_LEN),
        }

        if field_name in not_sure_fields:
            item["kind"] = KIND_NOT_SURE
            items.append(item)
            continue

        raw = answers.get(field_name)

        if schedule_capture.is_schedule_answer_key(field_name):
            rows = schedule_capture.decode_answer(raw) if raw else []
            if not rows:
                item["kind"] = KIND_BLANK
                items.append(item)
                continue
            item["kind"]      = KIND_SCHEDULE
            item["row_count"] = len(rows)
            item["rows"]      = rows[:_MAX_SCHEDULE_ROWS]
            if len(rows) > _MAX_SCHEDULE_ROWS:
                item["rows_truncated"] = True
            answered += 1
            items.append(item)
            continue

        val = "" if raw is None else str(raw).strip()
        if not val:
            item["kind"] = KIND_BLANK
            items.append(item)
            continue

        item["kind"]  = KIND_ANSWER
        item["value"] = _clip(val, _MAX_VALUE_LEN)
        if field_name in review_by_field:
            item["review_reason"] = review_by_field[field_name]
        answered += 1
        items.append(item)

    return {
        "version":        1,
        "arq_id":         arq.get("id"),
        "session_id":     arq.get("session_id"),
        "client_name":    _clip(arq.get("client_name"), 200),
        "client_email":   _clip(arq.get("email"), 200),
        "submitted_at":   arq.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
        "question_count": len(items),
        "answered_count": answered,
        "not_sure_count": len([i for i in items if i["kind"] == KIND_NOT_SURE]),
        "review_count":   len(review_by_field),
        "items":          items,
    }


# ASYNC-SAFE
async def create_receipt(arq: dict) -> Optional[str]:
    """Write the receipt for a submitted ARQ. Returns its id, or None.

    Never raises - see rule 1 in the module docstring. A caller may safely
    ignore the return value; it is used to stamp the activity event so the
    audit trail can point AT the receipt.
    """
    try:
        if not arq or not arq.get("id") or not arq.get("user_id"):
            return None

        payload = build_receipt_payload(arq)

        # Encryption failing is a genuine misconfiguration (no
        # FIELD_ENCRYPTION_KEY). Storing the client's answers in plaintext as a
        # "fallback" would silently downgrade security on the one table created
        # specifically to hold a durable copy of them, so we refuse to write
        # instead - loudly.
        try:
            ciphertext = encrypt_field(json.dumps(payload))
        except Exception as enc_ex:
            logger.error(
                "ARQ receipt: encryption failed for arq_id=%s (%s). No receipt "
                "written - check FIELD_ENCRYPTION_KEY.", arq.get("id"), enc_ex,
            )
            return None

        receipt_id = str(uuid.uuid4())
        now        = datetime.now(timezone.utc).isoformat()

        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO arq_receipts
                   (id, arq_id, session_id, user_id, client_name, client_email,
                    payload, item_count, answered_count, not_sure_count,
                    review_count, submitted_at, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                receipt_id, str(arq["id"]), arq.get("session_id"), str(arq["user_id"]),
                payload["client_name"], payload["client_email"],
                ciphertext, payload["question_count"], payload["answered_count"],
                payload["not_sure_count"], payload["review_count"],
                payload["submitted_at"], now,
            )

        logger.info(
            "ARQ receipt written: receipt_id=%s arq_id=%s items=%d answered=%d",
            receipt_id, arq["id"], payload["question_count"], payload["answered_count"],
        )
        return receipt_id

    except Exception as ex:
        logger.error(f"ARQ receipt: create failed for arq_id={arq.get('id')}: {ex}", exc_info=True)
        return None


# ASYNC-SAFE
async def get_receipt_for_arq(arq_id: str, user_id: str) -> Optional[dict]:
    """Fetch and decrypt the receipt for one ARQ, scoped to its owner.

    `user_id` is part of the WHERE clause, not an assertion after the fact, so a
    producer can never read another producer's client's answers even if they
    guess an arq_id. Returns None when absent or undecryptable.
    """
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, arq_id, session_id, client_name, client_email,
                          payload, item_count, answered_count, not_sure_count,
                          review_count, submitted_at, created_at
                   FROM arq_receipts
                   WHERE arq_id=$1 AND user_id=$2
                   ORDER BY created_at ASC
                   LIMIT 1""",
                str(arq_id), str(user_id),
            )
        if not row:
            return None

        rec = dict(row)
        try:
            body = json.loads(decrypt_field(rec.pop("payload")))
        except Exception as dec_ex:
            # A key rotation must not turn the panel into an error page: report
            # the receipt as existing but unreadable, which is the truth.
            logger.error(
                "ARQ receipt: payload could not be decrypted for arq_id=%s (%s)",
                arq_id, dec_ex,
            )
            rec["items"]      = []
            rec["unreadable"] = True
            return rec

        rec["items"]      = body.get("items", [])
        rec["version"]    = body.get("version", 1)
        rec["unreadable"] = False
        return rec

    except Exception as ex:
        logger.error(f"ARQ receipt: fetch failed for arq_id={arq_id}: {ex}", exc_info=True)
        return None


async def get_receipts_for_session(session_id: str, user_id: str) -> list:
    """Every questionnaire receipt on one submission, decrypted, oldest first.

    E&O 5.8: the audit export needs the client's answers WITH respondent
    identity and timestamp. Same owner-scoped WHERE and same
    unreadable-not-error decrypt handling as get_receipt_for_arq.
    """
    out: list = []
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, arq_id, session_id, client_name, client_email,
                          payload, item_count, answered_count, not_sure_count,
                          review_count, submitted_at, created_at
                   FROM arq_receipts
                   WHERE session_id=$1 AND user_id=$2
                   ORDER BY created_at ASC""",
                str(session_id), str(user_id),
            )
        for row in rows:
            rec = dict(row)
            try:
                body = json.loads(decrypt_field(rec.pop("payload")))
                rec["items"] = body.get("items", [])
                rec["unreadable"] = False
            except Exception as dec_ex:                        # noqa: BLE001
                logger.error(
                    "ARQ receipt: payload could not be decrypted for arq_id=%s (%s)",
                    rec.get("arq_id"), dec_ex,
                )
                rec.pop("payload", None)
                rec["items"] = []
                rec["unreadable"] = True
            out.append(rec)
    except Exception as ex:                                    # noqa: BLE001
        logger.error(
            f"ARQ receipt: session fetch failed for session={session_id}: {ex}",
            exc_info=True,
        )
    return out
