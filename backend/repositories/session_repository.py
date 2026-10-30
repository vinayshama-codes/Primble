import asyncio
import json
import re
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from config.database import get_pool
from fastapi import HTTPException
from services.extraction_service import _fv
from cryptography.fernet import InvalidToken as _InvalidToken

from utils.crypto import encrypt_field, decrypt_field

_FACTS_PREFIX = "enc:"


logger = logging.getLogger(__name__)


# Private marker carrying the ORIGINAL ciphertext of a facts blob we could not
# decrypt. It exists so an unreadable blob is never overwritten - see the long
# note on _decrypt_facts. Never leaves this module: stripped on the read path,
# consumed on the write path.
_FACTS_CIPHERTEXT_PRESERVED = "_facts_ciphertext_preserved"


def _encrypt_facts(data: dict) -> dict:
    """Encrypt the facts dict inside session data before writing to DB."""
    # An undecryptable blob is written back BYTE-FOR-BYTE. Without this the
    # `if not facts` early return below left `facts` as the None that
    # _decrypt_facts substituted, and the row was then written with facts=null -
    # destroying recoverable ciphertext on the next write of ANY kind, including
    # writes that never mentioned facts.
    preserved = data.get(_FACTS_CIPHERTEXT_PRESERVED)
    if preserved is not None:
        data = {k: v for k, v in data.items() if k != _FACTS_CIPHERTEXT_PRESERVED}
        data["facts"] = preserved
        return data
    facts = data.get("facts")
    if not facts:
        return data
    serialized = json.dumps(facts)
    # idempotent: encrypt_field already checks for enc: prefix
    data = dict(data)
    data["facts"] = encrypt_field(serialized)
    # The dashboard searches the CURRENT applicant name (27 Oct 2026): the
    # facts blob is one ciphertext, so SQL can never read inside it. Each write
    # keeps a small encrypted copy of the name beside it; the list decrypts it
    # in the app (`_search_name`), never the whole blob.
    if isinstance(facts, dict):
        name = _applicant_name_of(facts)
        if name:
            data[SEARCH_NAME_KEY] = encrypt_field(name)
        else:
            data.pop(SEARCH_NAME_KEY, None)
    return data


SEARCH_NAME_KEY = "search_name"


def _applicant_name_of(facts: dict) -> str:
    raw = facts.get("applicant_name")
    if isinstance(raw, dict):
        raw = raw.get("value")
    return str(raw).strip() if isinstance(raw, (str, int, float)) and str(raw).strip() else ""


def _search_name(cipher: Any) -> str:
    """The decrypted search copy of the applicant name, or "" (none, legacy
    plaintext kept as is, or a key mismatch - never raises)."""
    if not cipher or not isinstance(cipher, str):
        return ""
    try:
        return str(decrypt_field(cipher) or "").strip()
    except Exception:                                          # noqa: BLE001
        return ""


def _fold_name(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", str(text or "").casefold()).strip()


def name_matches_search(search: str, *names: Any) -> bool:
    """A keyword matches when it appears in any of `names`, ignoring case,
    punctuation and spacing ("choice electric llc" finds "CHOICE ELECTRIC, LLC";
    "oneil" finds "O'Neil"). A keyword with no letters or digits is matched
    literally. Empty keyword = no filter."""
    raw = str(search or "").strip().casefold()
    if not raw:
        return True
    want = _fold_name(raw)
    for name in names:
        if not name:
            continue
        if not want:
            if raw in str(name).casefold():
                return True
            continue
        have = _fold_name(name)
        if want in have or want.replace(" ", "") in have.replace(" ", ""):
            return True
    return False


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
            #
            # THE CIPHERTEXT IS KEPT. Returning facts=None is right for READERS
            # and was catastrophic for WRITERS: `upd_processing_session`'s
            # additive merge only engages when the existing facts is a dict, so
            # None fell through to wholesale replace and the next save - any
            # save - replaced the whole fact set with whatever it happened to
            # carry. Measured 2026-08-17 on a live session: 71 facts became 1
            # (`loss_history_years`, from a single ARQ answer) and the package
            # score fell 81 -> 37. `_encrypt_facts` writes this value straight
            # back, so the data survives and is recoverable the moment the key
            # is corrected.
            logger.error(
                "decrypt_facts: FIELD_ENCRYPTION_KEY mismatch for session %s — "
                "facts cannot be decrypted. Verify FIELD_ENCRYPTION_KEY on Render "
                "matches the key used when this data was written. The stored "
                "ciphertext is PRESERVED and will not be overwritten.",
                data.get("session_id", "?"),
            )
            data = dict(data)
            data[_FACTS_CIPHERTEXT_PRESERVED] = facts_raw
            data["facts"] = None
            return data
        try:
            data = dict(data)
            data["facts"] = json.loads(decrypted)
        except (json.JSONDecodeError, TypeError):
            # Legacy row stored facts as a plain JSON object string — leave as-is
            pass
    return data


def resolve_facts_write(current: dict, incoming: dict,
                        sid: str = "?") -> Optional[dict]:
    """The new ``facts`` value for a session, or ``None`` to REFUSE the write.

    Pure - no DB, no I/O. Extracted from ``upd_processing_session`` so the most
    dangerous decision in this module can be unit-tested without a database
    (the suite stubs out asyncpg and runs offline).

    NEVER REPLACE FACTS WHOLESALE WHEN THERE IS SOMETHING TO LOSE. On 2026-08-17
    a live session lost 70 of its 71 facts here: the stored blob could not be
    decrypted, ``_decrypt_facts`` substituted ``None``, ``None`` is not a dict
    so the additive branch was skipped, and the next write - a single ARQ answer
    carrying one fact - became the entire fact set. The package score fell from
    81 to 37 and the producer saw a POSITIVE answer destroy their submission.

    Four cases, and only one of them may replace:

    * existing facts is a dict          -> ADDITIVE merge (unchanged behaviour)
    * the blob could not be decrypted   -> REFUSE; ``_encrypt_facts`` writes the
                                           original ciphertext back untouched,
                                           so the data stays recoverable
    * existing facts is some other
      non-empty value we cannot read    -> REFUSE; replacing it is silent loss
    * nothing stored at all             -> accept (a new session's first write)
    """
    existing = current.get("facts")

    if isinstance(existing, dict):
        merged = dict(existing)
        for fk, fv in incoming.items():
            # Last-write-wins per key, but only when the new value is non-empty
            # — never let an in-flight caller's blank value erase a
            # previously-set value (the common ARQ-vs-extraction race).
            if fv is None:
                continue
            if isinstance(fv, str) and not fv.strip():
                continue
            if isinstance(fv, (list, dict)) and not fv:
                continue
            merged[fk] = fv
        return merged

    if current.get(_FACTS_CIPHERTEXT_PRESERVED) is not None:
        logger.error(
            "resolve_facts_write: REFUSING to write facts for %s - the stored "
            "blob could not be decrypted, so replacing it would destroy "
            "recoverable data. The update's other keys are still applied.", sid,
        )
        return None

    if existing:
        logger.error(
            "resolve_facts_write: REFUSING to write facts for %s - existing "
            "facts is %s, not a dict; replacing it would be silent data loss.",
            sid, type(existing).__name__,
        )
        return None

    return dict(incoming)          # nothing stored yet - a new session


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
    # Only the archive door sets a package's archive state.
    from services.package_archive import without_archive_keys
    data = without_archive_keys(data)
    clean = _session_to_db(_encrypt_facts(data))
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO processing_sessions (id, user_id, data, created_at, updated_at)"
            " VALUES ($1,$2,$3,$4,$5)",
            sid, data.get("user_id", ""), clean, now, now,
        )
        # E&O lineage: the first value of every fact, with its source document
        # and page (services/fact_history.py - this door and the one below are
        # the only facts writers). Never fails the create.
        from services.fact_history import record_fact_changes
        await record_fact_changes(conn, sid, data.get("user_id"), {}, data.get("facts"),
                                  docs=data.get("docs"))
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
    # The preservation marker is a WRITE-PATH concern only (upd_processing_session
    # reads the row itself, so it still sees it). Callers - and therefore API
    # responses - must never see raw ciphertext on a session object.
    data.pop(_FACTS_CIPHERTEXT_PRESERVED, None)
    if include_pdf:
        return await _session_from_db(data, sid)
    return data


# ASYNC-SAFE
async def set_active_form(sid: str, user_id: str, form_id: str) -> bool:
    """Record the form the producer has open (Orbin item 1: "Continue where you
    left off" reopens it). One key in one statement, only on the owner's
    session and only for a form that session generated - so it never races a
    save's merge of the rest of the row. `updated_at` is left alone: opening a
    form is not activity that should reorder the dashboard. False when nothing
    matched."""
    async with get_pool().acquire() as conn:
        status = await conn.execute(
            "UPDATE processing_sessions"
            " SET data = jsonb_set(data, '{active_form_id}', to_jsonb($3::text), true)"
            " WHERE id = $1 AND user_id = $2 AND (data->'generated_forms') ? $3",
            sid, str(user_id), str(form_id),
        )
    return str(status or "").strip().endswith(" 1")


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
        # The PDFs are written before the row lock, so an archived package's
        # read-only rule is asked here too (the locked check below covers the row).
        if any(isinstance(fd, dict) and fd.get("pdf_bytes") is not None
               for fd in (updates.get("generated_forms") or {}).values()):
            from services import package_archive as _pa
            try:
                _arch = await _pa.archived_state(sid)
            except Exception:                                  # noqa: BLE001
                _arch = None
            if _arch:
                _v = _pa.door_verdict({_pa.ARCHIVED_KEY: _arch}, updates, delete_facts)
                if _v == _pa.REFUSE:
                    raise _pa.archived_http_error()
                if _v == _pa.DROP:
                    logger.info("upd_processing_session: %s is archived - PDF write "
                                "dropped (read-only)", sid)
                    return
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

                    # An archived package does not change (services/
                    # package_archive.py): only a read's bookkeeping lands; any
                    # other write inside a GET is dropped, outside one refused.
                    from services import package_archive as _pa
                    _verdict = _pa.door_verdict(current, updates, delete_facts)
                    if _verdict == _pa.REFUSE:
                        raise _pa.archived_http_error()
                    if _verdict == _pa.DROP:
                        logger.info("upd_processing_session: %s is archived - write of %s "
                                    "dropped (read-only)", sid, sorted(updates))
                        return
                    updates = _pa.without_archive_keys(updates)

                    # E&O lineage: the facts as they stood before this write -
                    # None when they could not be read (no diff is trusted then).
                    _existing_facts = current.get("facts")
                    if isinstance(_existing_facts, dict):
                        _facts_before = dict(_existing_facts)
                    elif (_existing_facts is None
                          and current.get(_FACTS_CIPHERTEXT_PRESERVED) is None):
                        _facts_before = {}
                    else:
                        _facts_before = None

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
                        elif k == "facts" and isinstance(v, dict):
                            resolved = resolve_facts_write(current, v, sid)
                            if resolved is not None:
                                current["facts"] = resolved
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
                    # E&O lineage, in this transaction (a savepoint inside):
                    # one row per fact whose value, source or confirmation
                    # moved. A write that never touched facts is skipped.
                    if ("facts" in updates or delete_facts) and _facts_before is not None:
                        from services.fact_history import record_fact_changes
                        _docs = updates.get("docs") if isinstance(updates.get("docs"), list) else None
                        await record_fact_changes(conn, sid, current.get("user_id"),
                                                  _facts_before, current.get("facts"),
                                                  docs=_docs)
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


def _archived_clause(archived: bool) -> str:
    """The dashboard's two lists (27 Oct 2026, services/package_archive.py):
    the main list holds active packages, the Archived filter the archived ones."""
    return (" AND (data->>'archived_at') IS NOT NULL" if archived
            else " AND (data->>'archived_at') IS NULL")


_LEGACY_NAME_CACHE: "dict" = {}
_LEGACY_NAME_CACHE_MAX = 5000


_MATCH_CACHE: dict = {}
_MATCH_CACHE_TTL = 5.0


async def _matching_session_ids(user_id: str, search: str, archived: bool) -> List[str]:
    """One match per dashboard request: the page and its count ask the same
    question back to back, so the answer is reused for a few seconds."""
    import time
    key = (str(user_id), str(search or "").strip().casefold(), bool(archived))
    hit = _MATCH_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _MATCH_CACHE_TTL:
        return list(hit[1])
    ids = await _match_session_ids(user_id, search, archived)
    if len(_MATCH_CACHE) > 500:
        _MATCH_CACHE.clear()
    _MATCH_CACHE[key] = (time.monotonic(), list(ids))
    return ids


async def _match_session_ids(user_id: str, search: str, archived: bool) -> List[str]:
    """Ids of this user's packages whose displayed or current applicant name
    matches `search`, newest first - the dashboard search (27 Oct 2026).

    Reads only the small fields: the upload label and the encrypted search copy
    of the name (`SEARCH_NAME_KEY`), decrypted here. A package saved before the
    search copy existed (until the startup backfill reaches it) has its facts
    fetched in small batches and decrypted once; its name is cached by
    (id, updated_at) and its copy back-filled, so no later search pulls it."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text AS id, updated_at, data->>'submission_label' AS label, "
            "data->>'search_name' AS search_name "
            "FROM processing_sessions WHERE user_id = $1" + _archived_clause(archived)
            + " ORDER BY updated_at DESC",
            user_id,
        )
    names: dict = {}
    legacy = []
    for r in rows:
        name = _search_name(r["search_name"])
        if not name and r["search_name"] is None:
            cached = _LEGACY_NAME_CACHE.get((r["id"], str(r["updated_at"])))
            if cached is None:
                legacy.append(r)
            name = cached or ""
        names[r["id"]] = name
    backfill: List[tuple] = []
    for k in range(0, len(legacy), _LEGACY_FETCH_BATCH):
        part = legacy[k:k + _LEGACY_FETCH_BATCH]
        try:
            async with get_pool().acquire() as conn:
                got = await conn.fetch(
                    "SELECT id::text AS id, data->'facts' AS facts FROM processing_sessions "
                    "WHERE user_id = $1 AND id::text = ANY($2::text[])",
                    user_id, [r["id"] for r in part],
                )
        except Exception as ex:                                    # noqa: BLE001
            logger.warning("search: legacy names skipped: %s", ex)
            break
        facts_by_id = {g["id"]: g["facts"] for g in got}
        for r in part:
            name = ""
            try:
                raw = facts_by_id.get(r["id"])
                raw = json.loads(raw) if isinstance(raw, str) else raw
                facts = _decrypt_facts({"facts": raw}).get("facts") if raw is not None else None
                name = _applicant_name_of(facts) if isinstance(facts, dict) else ""
            except Exception:                                      # noqa: BLE001
                name = ""
            if len(_LEGACY_NAME_CACHE) >= _LEGACY_NAME_CACHE_MAX:
                _LEGACY_NAME_CACHE.clear()
            _LEGACY_NAME_CACHE[(r["id"], str(r["updated_at"]))] = name
            names[r["id"]] = name
            if name:
                backfill.append((r["id"], encrypt_field(name)))
    if backfill:
        await _backfill_search_names(backfill)
    return [r["id"] for r in rows if name_matches_search(search, r["label"], names.get(r["id"]))]


_LEGACY_FETCH_BATCH = 20


async def backfill_search_names(batch: int = 25, pause: float = 0.5) -> int:
    """Startup job: give every package this server can decrypt its encrypted
    search copy of the applicant name, a batch at a time, so the first dashboard
    search after a deploy never has to decrypt whole fact sets. Rows another
    environment's key wrote (unreadable here) or with no applicant name are
    remembered and skipped. Returns how many were filled. Never raises."""
    import asyncio
    done, skipped = 0, set()
    try:
        while True:
            async with get_pool().acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id::text AS id, data->'facts' AS facts FROM processing_sessions "
                    "WHERE data->>'search_name' IS NULL AND data ? 'facts' "
                    "AND NOT (id::text = ANY($1::text[])) ORDER BY updated_at DESC LIMIT $2",
                    list(skipped), batch,
                )
            if not rows:
                return done
            pairs = []
            for r in rows:
                try:
                    raw = r["facts"]
                    raw = json.loads(raw) if isinstance(raw, str) else raw
                    facts = _decrypt_facts({"facts": raw}).get("facts")
                    name = _applicant_name_of(facts) if isinstance(facts, dict) else ""
                except Exception:                                  # noqa: BLE001
                    name = ""
                if name:
                    pairs.append((r["id"], encrypt_field(name)))
                else:
                    skipped.add(r["id"])
            if pairs:
                await _backfill_search_names(pairs)
                done += len(pairs)
                # Each row is tried ONCE: a failed write must never loop.
                skipped.update(pid for pid, _ in pairs)
            await asyncio.sleep(pause)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("search-name startup backfill stopped after %d: %s", done, ex)
        return done


async def _backfill_search_names(pairs: List[tuple]) -> None:
    """Give packages saved before the search copy existed their copy, so the
    next search never decrypts their facts again. Written by the server that
    just decrypted them, so the copy carries the same key as their facts (local
    and Render use different keys). Only the one key; `updated_at` untouched;
    never over a copy a write has set meanwhile. Best effort - never raises."""
    try:
        async with get_pool().acquire() as conn:
            await conn.executemany(
                "UPDATE processing_sessions SET data = jsonb_set(data, '{search_name}', to_jsonb($2::text)) "
                "WHERE id::text = $1 AND data->>'search_name' IS NULL",
                pairs,
            )
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("search-name backfill skipped: %s", ex)


# ASYNC-SAFE
async def count_sessions_for_user(user_id: str, search: str = None,
                                  archived: bool = False) -> int:
    """Total number of processing sessions for a user - drives dashboard paging.
    With `search`, counts only packages whose applicant name matches (keyword
    search). `archived` picks the list: active packages (default) or the
    archived ones - the same split `list_sessions_for_user` draws."""
    if search:
        return len(await _matching_session_ids(user_id, search, archived))
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*)::int AS n FROM processing_sessions WHERE user_id = $1"
            + _archived_clause(archived),
            user_id,
        )
    return int(row["n"]) if row and row["n"] is not None else 0


# ASYNC-SAFE
async def list_sessions_for_user(user_id: str, limit: int = 50, offset: int = 0, search: str = None,
                                 archived: bool = False) -> list:
    # Optional keyword filter on the displayed applicant name. Server-side so it
    # spans the whole account, not just the current page. `archived` picks the
    # dashboard list (27 Oct 2026): active packages by default, else the
    # Archived filter's.
    search_clause = _archived_clause(archived)
    params = [user_id, limit, offset]
    if search:
        # Matched in the app (`_matching_session_ids`): the name sits inside
        # encrypted facts, which an SQL ILIKE never sees.
        ids = (await _matching_session_ids(user_id, search, archived))[offset:offset + limit]
        if not ids:
            return []
        search_clause += " AND id::text = ANY($4::text[])"
        params = [user_id, limit, 0, ids]
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id,
                created_at,
                updated_at,
                data->>'last_downloaded_at'                          AS last_downloaded_at,
                data->>'archived_at'                                 AS archived_at,
                data->>'search_name'                                 AS search_name,
                COALESCE(
                    NULLIF(data->>'submission_label', ''),
                    data->'facts'->'applicant_name'->>'value',
                    data->'facts'->>'applicant_name'
                )                                                    AS applicant_name,
                COALESCE(data->'carried_lines', data->'facts'->'lines_of_business') AS lines_of_business,
                data->'clarity_result'->'sqs_combined'               AS clarity_sqs,
                -- The submission's OWN score. The list used to average the
                -- per-form scores client-side and label the result "Quote
                -- Ready" at 90 - which is the PACKAGE threshold - so the badge
                -- could disagree with the banner inside the same submission.
                -- Before forms (14 Oct 2026, Orbin item 2) the score the pre-form
                -- screen showed (`form_routes._remember_pre_form_score`).
                -- Before forms the pre-form copy comes FIRST (30 Oct 2026, live
                -- 6875e80c): a pre-form recalculation also saves `package_sqs`,
                -- and a later add / re-merge moved the page past it - the list
                -- kept 94 while the page read 100.
                CASE WHEN COALESCE(data->'generated_forms', '{}'::jsonb) IN ('{}'::jsonb, '[]'::jsonb, 'null'::jsonb)
                     THEN COALESCE((data->'pre_form_score'->>'package_sqs_score')::int,
                                   (data->'package_sqs'->>'package_sqs_score')::int)
                     ELSE COALESCE((data->'package_sqs'->>'package_sqs_score')::int,
                                   (data->'pre_form_score'->>'package_sqs_score')::int) END
                                                                     AS package_sqs_score,
                -- "Quote Ready" needs NO open hard stop as well as the score
                -- (Brent, 19 Oct 2026); read from the same score as above, and
                -- derived from that score and its open hard stops whenever the
                -- payload carries the count (a credit moves the score after
                -- scoring). NULL on a score saved before then - the badge falls
                -- back to 90+, which the 60 cap a hard stop holds makes the
                -- same rule.
                CASE WHEN COALESCE(data->'generated_forms', '{}'::jsonb) IN ('{}'::jsonb, '[]'::jsonb, 'null'::jsonb)
                          AND (data->'pre_form_score'->>'package_sqs_score') IS NOT NULL
                     THEN data->'pre_form_score'->>'submission_ready'
                     WHEN (data->'package_sqs'->>'package_sqs_score') IS NOT NULL
                     THEN CASE WHEN (data->'package_sqs'->>'open_hard_stops') IS NOT NULL
                               THEN (((data->'package_sqs'->>'package_sqs_score')::int >= 90)
                                     AND ((data->'package_sqs'->>'open_hard_stops')::int = 0))::text
                               ELSE data->'package_sqs'->>'submission_ready' END
                     ELSE data->'pre_form_score'->>'submission_ready' END
                                                                     AS submission_ready,
                (SELECT jsonb_object_agg(key, value->'sqs')
                   FROM jsonb_each(CASE WHEN jsonb_typeof(data->'generated_forms') = 'object'
                                        THEN data->'generated_forms' ELSE '{}'::jsonb END))
                                                                     AS sqs_scores,
                (SELECT jsonb_agg(key)
                   FROM jsonb_each(CASE WHEN jsonb_typeof(data->'generated_forms') = 'object'
                                        THEN data->'generated_forms' ELSE '{}'::jsonb END))
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
            "archived_at":        dict(row).get("archived_at"),
            "applicant":          (row["applicant_name"] or _search_name(row.get("search_name"))
                                   or "Unknown Applicant"),
            "lines":              lines,
            "form_ids":           form_ids,
            "sqs":                sqs_scores,
            "package_sqs_score":  row["package_sqs_score"],
            "submission_ready":   (None if row.get("submission_ready") is None
                                   else str(row["submission_ready"]).lower() == "true"),
            "status":             compute_session_status({
                                      "arq_pending":        bool(row.get("arq_pending")),
                                      "last_downloaded_at": row["last_downloaded_at"],
                                      "generated_forms":    {k: {} for k in form_ids},
                                      "clarity_result":     {"sqs_combined": row["clarity_sqs"]} if row["clarity_sqs"] else {},
                                  }),
        })
    return result
