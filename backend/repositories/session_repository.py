import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from config.database import get_pool
from fastapi import HTTPException
from services.extraction_service import _fv
from services.s3_service import (
    download_pdf        as _s3_download,
    download_pdf_async  as _s3_download_async,
    upload_pdf          as _s3_upload,
    upload_pdf_async    as _s3_upload_async,
    is_configured       as _s3_configured,
)
from utils.crypto import encrypt_field, decrypt_field

_FACTS_PREFIX = "enc:"

_IS_PROD = os.getenv("ENVIRONMENT", "development").lower() == "production"

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
        decrypted = decrypt_field(facts_raw)
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
        row   = dict(row)
        fid   = row["form_id"]
        s3_key = row.get("s3_key")
        pb    = None
        if s3_key:
            pb = await _s3_download_async(s3_key)
        if pb is None and row.get("pdf_bytes"):
            pb = bytes(row["pdf_bytes"])
        if pb is not None and fid in generated:
            generated[fid]["pdf_bytes"] = pb
    return data


# ASYNC-SAFE
async def _save_pdf_bytes(sid: str, generated: dict) -> None:
    if not generated:
        return
    now = datetime.now(timezone.utc).isoformat()

    # Phase 1: upload to S3 outside the DB transaction to avoid holding a DB
    # connection open during network I/O.
    s3_results: dict = {}  # fid -> (s3_key | None, pdf_bytes | None)
    for fid, form_data in generated.items():
        pb = form_data.get("pdf_bytes")
        if pb is None:
            continue
        if _s3_configured():
            s3_key = await _s3_upload_async(sid, fid, pb)
            if s3_key:
                s3_results[fid] = (s3_key, None)
                continue
            if _IS_PROD:
                logger.error(
                    "S3 PDF upload failed for session %s form %s in production", sid, fid
                )
                raise HTTPException(503, "PDF storage failed. Please try again.")
            logger.warning(
                "S3 PDF upload failed for session %s form %s — BYTEA fallback (dev only)",
                sid, fid,
            )
        elif _IS_PROD:
            raise HTTPException(
                503, "PDF storage requires S3 in production. Set AWS_S3_BUCKET."
            )
        s3_results[fid] = (None, pb)

    if not s3_results:
        return

    # Phase 2: persist the keys/bytes in a short-lived DB transaction — no S3 I/O here.
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            for fid, (s3_key, pb) in s3_results.items():
                if s3_key:
                    await conn.execute(
                        """INSERT INTO session_pdf_bytes
                               (session_id, form_id, pdf_bytes, s3_key, updated_at)
                           VALUES ($1,$2,NULL,$3,$4)
                           ON CONFLICT (session_id, form_id)
                           DO UPDATE SET pdf_bytes=NULL, s3_key=EXCLUDED.s3_key,
                                         updated_at=EXCLUDED.updated_at""",
                        sid, fid, s3_key, now,
                    )
                else:
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
async def upd_processing_session(sid: str, updates: dict) -> None:
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

                    for k, v in updates.items():
                        if k != "generated_forms":
                            current[k] = v

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
    if data.get("last_downloaded_at"):
        return "COMPLETED"
    if data.get("generated_forms") or data.get("clarity_result"):
        return "IN_PROGRESS"
    return "NOT_STARTED"


# ASYNC-SAFE
async def list_sessions_for_user(user_id: str, limit: int = 50, offset: int = 0) -> list:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id,
                created_at,
                updated_at,
                data->>'last_downloaded_at'                          AS last_downloaded_at,
                COALESCE(
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
                                                                     AS form_ids
            FROM processing_sessions
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset,
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
                                      "last_downloaded_at": row["last_downloaded_at"],
                                      "generated_forms":    {k: {} for k in form_ids},
                                      "clarity_result":     {"sqs_combined": row["clarity_sqs"]} if row["clarity_sqs"] else {},
                                  }),
        })
    return result
