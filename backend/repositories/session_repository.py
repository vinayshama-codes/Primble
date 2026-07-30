import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from config.database import get_pool
from fastapi import HTTPException
from services.extraction_service import _fv
from cryptography.fernet import InvalidToken as _InvalidToken

from utils.crypto import encrypt_field, decrypt_field

_FACTS_PREFIX = "enc:"


logger = logging.getLogger(__name__)


def _encrypt_facts(data: dict) -> dict:
    """Encrypt the facts dict inside session data before writing to DB."""
    facts = data.get("facts")
    if not facts:
        return data
    serialized = json.dumps(facts)
    # idempotent: encrypt_field already checks for enc: prefix
    data = dict(data)
    data["facts"] = encrypt_field(serialized)
    return data


def _decrypt_facts(data: dict) -> dict:
    """Decrypt the facts value in session data after reading from DB."""
    facts_raw = data.get("facts")
    if not facts_raw:
        return data
    if isinstance(facts_raw, str):
        try:
            decrypted = decrypt_field(facts_raw)
        except _InvalidToken:
            # Key mismatch (e.g. FIELD_ENCRYPTION_KEY rotated or differs between
            # environments).  Return session without facts rather than crashing —
            # the frontend shows an empty session and the user can re-upload.
            logger.error(
                "decrypt_facts: FIELD_ENCRYPTION_KEY mismatch for session %s — "
                "facts cannot be decrypted. Verify FIELD_ENCRYPTION_KEY on Render "
                "matches the key used when this data was written.",
                data.get("session_id", "?"),
            )
            data = dict(data)
            data["facts"] = None
            return data
        try:
            data = dict(data)
            data["facts"] = json.loads(decrypted)
        except (json.JSONDecodeError, TypeError):
            # Legacy row stored facts as a plain JSON object string — leave as-is
            pass
    return data


def _strip_null_bytes(obj):
    """Recursively remove \\u0000 null bytes from all strings — PostgreSQL rejects them."""
    if isinstance(obj, str):
        return obj.replace('\x00', '')
    if isinstance(obj, dict):
        return {k: _strip_null_bytes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null_bytes(i) for i in obj]
    return obj


def _session_to_db(data: dict) -> dict:
    generated  = data.get("generated_forms", {})
    clean_gen  = {fid: {k: v for k, v in fd.items() if k != "pdf_bytes"} for fid, fd in generated.items()}
    clean      = {k: v for k, v in data.items() if k != "generated_forms"}
    clean["generated_forms"] = clean_gen
    return _strip_null_bytes(clean)


# ASYNC-SAFE
async def _session_from_db(data: dict, sid: str) -> dict:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM session_pdf_bytes WHERE session_id = $1", sid
        )
    generated = data.get("generated_forms", {})
    for row in rows:
        row = dict(row)
        fid = row["form_id"]
        pb  = bytes(row["pdf_bytes"]) if row.get("pdf_bytes") else None
        if pb is not None and fid in generated:
            generated[fid]["pdf_bytes"] = pb
    return data


# ASYNC-SAFE
async def _save_pdf_bytes(sid: str, generated: dict) -> None:
    if not generated:
        return
    now = datetime.now(timezone.utc).isoformat()

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            for fid, form_data in generated.items():
                pb = form_data.get("pdf_bytes")
                if pb is None:
                    continue
                await conn.execute(
                    """INSERT INTO session_pdf_bytes
                           (session_id, form_id, pdf_bytes, updated_at)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (session_id, form_id)
                       DO UPDATE SET pdf_bytes=EXCLUDED.pdf_bytes,
                                     updated_at=EXCLUDED.updated_at""",
                    sid, fid, pb, now,
                )


# ASYNC-SAFE
async def new_processing_session(data: dict) -> str:
    sid  = str(uuid.uuid4())
    now  = datetime.now(timezone.utc).isoformat()
    await _save_pdf_bytes(sid, data.get("generated_forms", {}))
    clean = _session_to_db(_encrypt_facts(data))
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO processing_sessions (id, user_id, data, created_at, updated_at)"
            " VALUES ($1,$2,$3,$4,$5)",
            sid, data.get("user_id", ""), clean, now, now,
        )
    logger.info(f"Processing session created: {sid}")
    return sid


# ASYNC-SAFE
async def get_processing_session(sid: str, include_pdf: bool = False) -> dict:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data FROM processing_sessions WHERE id = $1", sid
        )
    if not row:
        raise HTTPException(404, f"Processing session {sid} not found")
    data = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
    data = _decrypt_facts(data)
    if include_pdf:
        return await _session_from_db(data, sid)
    return data


# ASYNC-SAFE
async def upd_processing_session(
    sid: str,
    updates: dict,
    delete_facts: Optional[List[str]] = None,
) -> None:
    """Merge `updates` into the session's JSONB blob.

    `delete_facts` REMOVES those keys from `facts` outright. It exists because the
    `facts` merge below is deliberately additive - it skips None/empty values so an
    in-flight writer can never blank a value another writer just set - which also
    means a key simply *absent* from `updates["facts"]` is preserved. There was
    therefore no way to genuinely retract a fact, and the one caller that tried
    (`clear_producer_answer_from_session`, undoing a producer's answer) silently
    had its deletion dropped: the form field was blanked but the fact survived and
    was re-stamped on the next recalculation.

    Deliberately a keyword parameter rather than a sentinel key inside `updates`:
    it cannot leak into `current[k]` via the wholesale-replace branch below, and it
    cannot ever collide with a real session-data key.
    """
    # Phase 1: if there are new pdf_bytes, upload to S3/BYTEA before acquiring the
    # row lock so the DB transaction stays short and doesn't block other writers.
    if "generated_forms" in updates:
        await _save_pdf_bytes(sid, updates["generated_forms"])

    # Phase 2: short read-modify-write transaction.
    # After GPT fill (which can take 3+ minutes) the pool may hand us a connection
    # whose underlying TCP socket was reset by the OS or PG server.  We retry once
    # with a fresh connection before surfacing the error.
    _MAX_RETRIES = 2
    last_exc: Exception = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT data, version FROM processing_sessions WHERE id = $1 FOR UPDATE",
                        sid,
                    )
                    if not row:
                        raise HTTPException(404, f"Processing session {sid} not found")

                    current = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
                    current = _decrypt_facts(current)
                    version = row["version"]

                    if "generated_forms" in updates:
                        existing_gen = current.get("generated_forms", {})
                        for fid, form_data in updates["generated_forms"].items():
                            if fid not in existing_gen:
                                existing_gen[fid] = form_data
                            else:
                                existing_gen[fid].update(form_data)
                        current["generated_forms"] = existing_gen

                    # Spec / concurrency: append-only merge for sqs_history so
                    # concurrent writers don't wipe each other's entries; dict
                    # merge for facts so ARQ apply / extraction / edit don't
                    # overwrite each other's keys.  (Other keys keep the
                    # legacy wholesale-replace behaviour.)
                    for k, v in updates.items():
                        if k == "generated_forms":
                            continue
                        if k == "sqs_history" and isinstance(v, list):
                            existing_hist = current.get("sqs_history") or []
                            if not isinstance(existing_hist, list):
                                existing_hist = []
                            merged = list(existing_hist)
                            # Dedup by (stage, at, score) to avoid duplicates.
                            seen = {
                                (h.get("stage"), h.get("at"), h.get("score"))
                                for h in merged if isinstance(h, dict)
                            }
                            for entry in v:
                                if not isinstance(entry, dict):
                                    continue
                                key = (entry.get("stage"), entry.get("at"), entry.get("score"))
                                if key not in seen:
                                    merged.append(entry)
                                    seen.add(key)
                            current["sqs_history"] = merged
                        elif k == "facts" and isinstance(v, dict) and isinstance(current.get("facts"), dict):
                            merged_facts = dict(current.get("facts") or {})
                            for fk, fv in v.items():
                                # Last-write-wins per key, but only when the new
                                # value is non-empty — never let an in-flight
                                # caller's blank value erase a previously-set
                                # value (the common ARQ-vs-extraction race).
                                if fv is None:
                                    continue
                                if isinstance(fv, str) and not fv.strip():
                                    continue
                                if isinstance(fv, (list, dict)) and not fv:
                                    continue
                                merged_facts[fk] = fv
                            current["facts"] = merged_facts
                        else:
                            current[k] = v

                    # Explicit retraction, applied AFTER the additive merge above so
                    # a caller can pass the same fact in both places without the
                    # merge resurrecting it. Idempotent, so the connection-error
                    # retry below can safely re-run this whole block.
                    if delete_facts and isinstance(current.get("facts"), dict):
                        for _fk in delete_facts:
                            current["facts"].pop(_fk, None)

                    clean = _session_to_db(_encrypt_facts(current))
                    now   = datetime.now(timezone.utc).isoformat()
                    await conn.execute(
                        "UPDATE processing_sessions"
                        " SET data=$1, updated_at=$2, version=$3"
                        " WHERE id=$4",
                        clean, now, version + 1, sid,
                    )
            return  # success
        except HTTPException:
            raise
        except Exception as exc:
            last_exc = exc
            # Only retry on connection-level errors (reset socket, closed interface, etc.)
            exc_str = str(exc).lower()
            is_conn_err = (
                "connection" in exc_str
                or "interface" in exc_str
                or "closed" in exc_str
                or "broken pipe" in exc_str
                or isinstance(exc, (OSError, ConnectionResetError))
            )
            if is_conn_err and attempt < _MAX_RETRIES - 1:
                logger.warning(
                    "upd_processing_session: connection error on attempt %d/%d for sid=%s — retrying: %s",
                    attempt + 1, _MAX_RETRIES, sid, exc,
                )
                await asyncio.sleep(0.5)
                continue
            raise


def _mask_ssn(value: str | None) -> str | None:
    """Return ***-**-XXXX, exposing only the last 4 digits."""
    if not value:
        return value
    digits = "".join(c for c in str(value) if c.isdigit())
    last4  = digits[-4:] if len(digits) >= 4 else digits.ljust(4, "X")
    return f"***-**-{last4}"


def _mask_fein(value: str | None) -> str | None:
    """Return **-***XXXX, exposing only the last 4 digits."""
    if not value:
        return value
    digits = "".join(c for c in str(value) if c.isdigit())
    last4  = digits[-4:] if len(digits) >= 4 else digits.ljust(4, "X")
    return f"**-***{last4}"


def _mask_dob(value: str | None) -> str | None:
    """Return only the year component; mask month and day."""
    if not value:
        return value
    parts = str(value).replace("/", "-").split("-")
    # Support YYYY-MM-DD and MM/DD/YYYY
    for part in parts:
        if len(part) == 4 and part.isdigit():
            return part
    return "****"


def _mask_facts_for_summary(facts: dict) -> dict:
    """Return a copy of facts with sensitive PII fields masked for list/summary responses."""
    if not facts or not isinstance(facts, dict):
        return facts
    masked = dict(facts)
    for key in list(masked.keys()):
        lower = key.lower()
        val   = masked[key]
        raw   = val.get("value", val) if isinstance(val, dict) else val
        if "ssn" in lower or "social_security" in lower:
            masked[key] = _mask_ssn(str(raw)) if raw else raw
        elif "fein" in lower or "federal_employer" in lower or "ein" in lower:
            masked[key] = _mask_fein(str(raw)) if raw else raw
        elif "dob" in lower or "date_of_birth" in lower or "birth_date" in lower:
            masked[key] = _mask_dob(str(raw)) if raw else raw
    return masked


def compute_session_status(data: dict) -> str:
    # A questionnaire still out to the client is the most actionable state, so it
    # takes precedence over the download / progress lifecycle.
    if data.get("arq_pending"):
        return "AWAITING_CLIENT"
    if data.get("last_downloaded_at"):
        return "COMPLETED"
    if data.get("generated_forms") or data.get("clarity_result"):
        return "IN_PROGRESS"
    return "NOT_STARTED"


# ASYNC-SAFE
async def count_sessions_for_user(user_id: str, search: str = None) -> int:
    """Total number of processing sessions for a user - drives dashboard paging.
    Matches the COUNT(*) used by /api/sessions/stats total_packages.
    With `search`, counts only packages whose applicant name matches (keyword
    search); without it, identical to the original unfiltered count."""
    async with get_pool().acquire() as conn:
        if search:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS n FROM processing_sessions
                WHERE user_id = $1
                  AND COALESCE(NULLIF(data->>'submission_label', ''),
                               data->'facts'->'applicant_name'->>'value',
                               data->'facts'->>'applicant_name') ILIKE '%' || $2 || '%'
                """,
                user_id, search,
            )
        else:
            row = await conn.fetchrow(
                "SELECT COUNT(*)::int AS n FROM processing_sessions WHERE user_id = $1",
                user_id,
            )
    return int(row["n"]) if row and row["n"] is not None else 0


# ASYNC-SAFE
async def list_sessions_for_user(user_id: str, limit: int = 50, offset: int = 0, search: str = None) -> list:
    # Optional keyword filter on the displayed applicant name. Server-side so it
    # spans the whole account, not just the current page. Backward compatible:
    # with no search, the query and params are identical to before.
    search_clause = ""
    params = [user_id, limit, offset]
    if search:
        search_clause = (
            " AND COALESCE(NULLIF(data->>'submission_label', ''), "
            "data->'facts'->'applicant_name'->>'value', "
            "data->'facts'->>'applicant_name') ILIKE '%' || $4 || '%'"
        )
        params.append(search)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id,
                created_at,
                updated_at,
                data->>'last_downloaded_at'                          AS last_downloaded_at,
                COALESCE(
                    NULLIF(data->>'submission_label', ''),
                    data->'facts'->'applicant_name'->>'value',
                    data->'facts'->>'applicant_name'
                )                                                    AS applicant_name,
                data->'facts'->'lines_of_business'                   AS lines_of_business,
                data->'clarity_result'->'sqs_combined'               AS clarity_sqs,
                (SELECT jsonb_object_agg(key, value->'sqs')
                   FROM jsonb_each(COALESCE(data->'generated_forms', '{}'::jsonb)))
                                                                     AS sqs_scores,
                (SELECT jsonb_agg(key)
                   FROM jsonb_each(COALESCE(data->'generated_forms', '{}'::jsonb)))
                                                                     AS form_ids,
                EXISTS (
                    SELECT 1 FROM arq_sessions a
                    WHERE a.session_id = processing_sessions.id
                      AND a.status = 'pending'
                )                                                    AS arq_pending
            FROM processing_sessions
            WHERE user_id = $1""" + search_clause + """
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            *params,
        )
    result = []
    for row in rows:
        row = dict(row)

        sqs_scores = {}
        if row["sqs_scores"]:
            raw = row["sqs_scores"] if isinstance(row["sqs_scores"], dict) else json.loads(row["sqs_scores"])
            sqs_scores = {k: v for k, v in raw.items() if v is not None}
        if not sqs_scores and row["clarity_sqs"]:
            clarity_sqs = row["clarity_sqs"] if isinstance(row["clarity_sqs"], dict) else json.loads(row["clarity_sqs"])
            sqs_scores = {"clarity": clarity_sqs}

        lines = []
        if row["lines_of_business"]:
            raw_lines = row["lines_of_business"] if isinstance(row["lines_of_business"], list) else json.loads(row["lines_of_business"])
            # Each entry may be a plain string or a {"value": "..."} object
            lines = [
                (item["value"] if isinstance(item, dict) and "value" in item else str(item))
                for item in raw_lines
            ]

        form_ids = []
        if row["form_ids"]:
            form_ids = row["form_ids"] if isinstance(row["form_ids"], list) else json.loads(row["form_ids"])

        result.append({
            "session_id":         row["id"],
            "created_at":         row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at":         row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            "last_downloaded_at": row["last_downloaded_at"],
            "applicant":          row["applicant_name"] or "Unknown Applicant",
            "lines":              lines,
            "form_ids":           form_ids,
            "sqs":                sqs_scores,
            "status":             compute_session_status({
                                      "arq_pending":        bool(row.get("arq_pending")),
                                      "last_downloaded_at": row["last_downloaded_at"],
                                      "generated_forms":    {k: {} for k in form_ids},
                                      "clarity_result":     {"sqs_combined": row["clarity_sqs"]} if row["clarity_sqs"] else {},
                                  }),
        })
    return result
