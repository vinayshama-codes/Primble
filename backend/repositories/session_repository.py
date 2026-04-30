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
    download_pdf as _s3_download,
    upload_pdf   as _s3_upload,
    is_configured as _s3_configured,
)

_IS_PROD = os.getenv("ENVIRONMENT", "development").lower() == "production"

logger = logging.getLogger(__name__)


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
            pb = _s3_download(s3_key)
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
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            for fid, form_data in generated.items():
                pb = form_data.get("pdf_bytes")
                if pb is None:
                    continue
                if _s3_configured():
                    s3_key = _s3_upload(sid, fid, pb)
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
    clean = _session_to_db(data)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO processing_sessions (id, user_id, data, created_at, updated_at)"
            " VALUES ($1,$2,$3,$4,$5)",
            sid, data.get("user_id", ""), clean, now, now,
        )
    logger.info(f"Processing session created: {sid}")
    return sid


# ASYNC-SAFE
async def get_processing_session(sid: str) -> dict:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data FROM processing_sessions WHERE id = $1", sid
        )
    if not row:
        raise HTTPException(404, f"Processing session {sid} not found")
    data = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
    return await _session_from_db(data, sid)


# ASYNC-SAFE
async def upd_processing_session(sid: str, updates: dict) -> None:
    current = await get_processing_session(sid)
    if "generated_forms" in updates:
        existing_gen = current.get("generated_forms", {})
        for fid, form_data in updates["generated_forms"].items():
            if fid not in existing_gen:
                existing_gen[fid] = form_data
            else:
                existing_gen[fid].update(form_data)
        current["generated_forms"] = existing_gen
        await _save_pdf_bytes(sid, current["generated_forms"])
    for k, v in updates.items():
        if k != "generated_forms":
            current[k] = v
    clean = _session_to_db(current)
    now   = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE processing_sessions SET data=$1, updated_at=$2 WHERE id=$3",
            clean, now, sid,
        )


def compute_session_status(data: dict) -> str:
    if data.get("last_downloaded_at"):
        return "COMPLETED"
    if data.get("generated_forms") or data.get("clarity_result"):
        return "IN_PROGRESS"
    return "NOT_STARTED"


# ASYNC-SAFE
async def list_sessions_for_user(user_id: str) -> list:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, data, created_at, updated_at"
            " FROM processing_sessions"
            " WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 50",
            user_id,
        )
    result = []
    for row in rows:
        row  = dict(row)
        data = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
        generated  = data.get("generated_forms", {})
        facts      = data.get("facts", {})
        sqs_scores = {fid: fd.get("sqs", {}) for fid, fd in generated.items()}

        clarity = data.get("clarity_result", {})
        if not sqs_scores and clarity.get("sqs_combined"):
            sqs_scores = {"clarity": clarity["sqs_combined"]}

        result.append({
            "session_id":         row["id"],
            "created_at":         row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at":         row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            "last_downloaded_at": data.get("last_downloaded_at"),
            "applicant":          _fv(facts, "applicant_name") or "Unknown Applicant",
            "lines":              facts.get("lines_of_business") or [],
            "form_ids":           list(generated.keys()),
            "sqs":                sqs_scores,
            "status":             compute_session_status(data),
        })
    return result
