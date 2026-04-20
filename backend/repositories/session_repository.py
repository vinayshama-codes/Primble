import json
import logging
import uuid
import psycopg2
from datetime import datetime, timezone
from typing import Optional

from config.database import get_db
from fastapi import HTTPException
from services.extraction_service import _fv

logger = logging.getLogger(__name__)


def _strip_null_bytes(obj):
    """Recursively remove \u0000 null bytes from all strings — PostgreSQL rejects them."""
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


def _session_from_db(data: dict, sid: str) -> dict:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT form_id, pdf_bytes FROM session_pdf_bytes WHERE session_id = %s", (sid,))
    rows   = cur.fetchall()
    cur.close()
    conn.close()
    pb_map    = {r["form_id"]: bytes(r["pdf_bytes"]) for r in rows}
    generated = data.get("generated_forms", {})
    for fid, form_data in generated.items():
        if fid in pb_map:
            form_data["pdf_bytes"] = pb_map[fid]
    return data


def _save_pdf_bytes(sid: str, generated: dict):
    if not generated:
        return
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    for fid, form_data in generated.items():
        pb = form_data.get("pdf_bytes")
        if pb is not None:
            cur.execute(
                """INSERT INTO session_pdf_bytes (session_id, form_id, pdf_bytes, updated_at)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (session_id, form_id)
                   DO UPDATE SET pdf_bytes = EXCLUDED.pdf_bytes, updated_at = EXCLUDED.updated_at""",
                (sid, fid, psycopg2.Binary(pb), now),
            )
    conn.commit()
    cur.close()
    conn.close()


def new_processing_session(data: dict) -> str:
    sid  = str(uuid.uuid4())
    now  = datetime.now(timezone.utc).isoformat()
    _save_pdf_bytes(sid, data.get("generated_forms", {}))
    clean = _session_to_db(data)
    conn  = get_db()
    cur   = conn.cursor()
    cur.execute(
        "INSERT INTO processing_sessions (id, user_id, data, created_at, updated_at) VALUES (%s,%s,%s,%s,%s)",
        (sid, data.get("user_id", ""), json.dumps(clean), now, now),
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Processing session created: {sid}")
    return sid


def get_processing_session(sid: str) -> dict:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT data FROM processing_sessions WHERE id = %s", (sid,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(404, f"Processing session {sid} not found")
    data = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
    return _session_from_db(data, sid)


def upd_processing_session(sid: str, updates: dict):
    current = get_processing_session(sid)
    if "generated_forms" in updates:
        existing_gen = current.get("generated_forms", {})
        for fid, form_data in updates["generated_forms"].items():
            if fid not in existing_gen:
                existing_gen[fid] = form_data
            else:
                existing_gen[fid].update(form_data)
        current["generated_forms"] = existing_gen
        _save_pdf_bytes(sid, current["generated_forms"])
    for k, v in updates.items():
        if k != "generated_forms":
            current[k] = v
    clean = _session_to_db(current)
    now   = datetime.now(timezone.utc).isoformat()
    conn  = get_db()
    cur   = conn.cursor()
    cur.execute(
        "UPDATE processing_sessions SET data = %s, updated_at = %s WHERE id = %s",
        (json.dumps(clean), now, sid),
    )
    conn.commit()
    cur.close()
    conn.close()

def compute_session_status(data: dict) -> str:
    """
    Derive the display status of a session from its stored data.

    NOT_STARTED  — uploaded but no forms generated or Clarity analysis run
    IN_PROGRESS  — forms generated / Clarity analysis done, never downloaded
    COMPLETED    — at least one download (single or ZIP) has been recorded

    This is the single source of truth for the dashboard badge.
    Never store status directly — always compute it from these fields
    so it cannot go stale.
    """
    if data.get("last_downloaded_at"):
        return "COMPLETED"
    if data.get("generated_forms") or data.get("clarity_result"):
        return "IN_PROGRESS"
    return "NOT_STARTED"


def list_sessions_for_user(user_id: str) -> list:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, data, created_at, updated_at FROM processing_sessions WHERE user_id = %s ORDER BY updated_at DESC LIMIT 50",
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for row in rows:
        data      = dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])
        generated = data.get("generated_forms", {})
        facts     = data.get("facts", {})
        sqs_scores = {fid: fd.get("sqs", {}) for fid, fd in generated.items()}

        # Include Clarity SQS if no Assembly forms were generated
        clarity = data.get("clarity_result", {})
        if not sqs_scores and clarity.get("sqs_combined"):
            sqs_scores = {"clarity": clarity["sqs_combined"]}

        result.append({
            "session_id":          row["id"],
            "created_at":          row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at":          row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            "last_downloaded_at":  data.get("last_downloaded_at"),
            "applicant":           _fv(facts, "applicant_name") or "Unknown Applicant",
            "lines":               facts.get("lines_of_business") or [],
            "form_ids":            list(generated.keys()),
            "sqs":                 sqs_scores,
            "status":              compute_session_status(data),
        })
    return result