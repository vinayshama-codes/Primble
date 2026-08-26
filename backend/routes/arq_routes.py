import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from config.database import get_pool
from config.settings import FRONTEND_URL
from repositories.session_repository import get_processing_session, upd_processing_session
from services.arq_service import (
    _backfill_and_resolve_present,
    apply_arq_answers_to_session,
    create_arq_notification,
    create_arq_session,
    filter_arq_questions_for_session,
    generate_arq_questions,
    generate_cross_form_arq_questions,
    get_arq_by_id,
    get_arq_by_token,
    get_arq_notifications,
    get_arq_sessions_for_user,
    get_client_filled_fields,
    get_session_schedules,
    mark_arq_viewed,
    mark_notifications_read,
    save_arq_draft,
    save_session_schedule,
    send_arq_reminder,
    submit_arq_answers,
)
from services.arq_service import recalculate_session_scores
from services.arq_receipt_service import create_receipt, get_receipt_for_arq
from services import schedule_capture
from services.question_classifier import (
    AUDIENCE_CLIENT,
    AUDIENCE_DO_NOT_SEND,
    BUCKET_DO_NOT_SEND,
    BUCKET_LABELS,
    BUCKET_ORDER,
    DEFAULT_SELECT_CAP,
    TOPIC_LABELS,
    TOPIC_ORDER,
    apply_default_selection,
)
from services.auth_service import get_current_user
from services.activity_service import (
    record_event,
    EVENT_ARQ_SENT, EVENT_ARQ_OPENED, EVENT_ARQ_IN_PROGRESS,
    EVENT_ARQ_SUBMITTED, EVENT_ANSWERS_APPLIED, EVENT_REMINDER_SENT,
)
from services.email_service import send_arq_email, send_arq_submitted_notification
from utils.rate_limiter import check_arq_public_rate_limit, check_arq_submit_rate_limit, check_arq_chat_rate_limit, get_client_ip
from utils.helpers import check_payment_access

router = APIRouter(prefix="/api/arq", tags=["arq"])
logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _sanitize_str(val: str, max_len: int = 500) -> str:
    if not val:
        return ""
    val = re.sub(r"<[^>]*>", "", str(val))
    return val.strip()[:max_len]


def _sanitize_digits(val) -> int:
    """Clamp an expected code width to a sane int (Figure 18).

    Never raises: a crafted or malformed payload yields 0, which the renderer
    reads as "no fixed width" rather than failing the request.
    """
    try:
        return max(0, min(int(val or 0), 20))
    except (TypeError, ValueError):
        return 0


def _sanitize_suggestions(raw) -> list:
    """Normalize Figure 20 NAICS / SIC candidates for storage and for the client.

    Used by BOTH question serializers - `send_arq` (producer request body, on the
    way into the stored ARQ) and `client_view` (stored ARQ, on the way out to the
    questionnaire). Shared deliberately: when these were two inline copies, the
    send-side one was missing entirely and the personalized hint shipped without
    its chips. One definition means one place to keep correct.

    Returns [] for anything malformed, so a caller can treat a falsy result as
    "no suggestions" without a type check.
    """
    if not isinstance(raw, list) or not raw:
        return []
    out = []
    for s in raw[:3]:
        if not isinstance(s, dict):
            continue
        code = _sanitize_str(str(s.get("code", "")), 10)
        if not code:
            continue
        conf = s.get("confidence")
        out.append({
            "code":       code,
            "label":      _sanitize_str(str(s.get("label", "")), 80),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        })
    return out


def _sanitize_answers(raw_answers: dict) -> dict:
    """Sanitize a questionnaire answer map.

    Scalar answers keep the long-standing behaviour (strip markup, clamp to 500
    chars). Schedule answers (reserved `schedule::<key>` namespace) carry a LIST
    OF ROWS and must not be flattened through `str(v)[:500]` - that would
    silently truncate a fleet to the first couple of vehicles. They are instead
    parsed, per-cell sanitized and re-encoded by `schedule_capture`, which
    applies its own row/cell bounds (MAX_ROWS / MAX_CELL_LEN).
    """
    out: dict = {}
    for k, v in (raw_answers or {}).items():
        key = _sanitize_str(k, 128)
        if not key:
            continue
        if schedule_capture.is_schedule_answer_key(key):
            list_key = schedule_capture.list_key_from_answer_key(key)
            if schedule_capture.get_def(list_key) is None:
                continue  # unknown schedule key - drop rather than store junk
            rows, _report = schedule_capture.validate_rows(
                list_key, schedule_capture.decode_answer(v),
            )
            out[key] = schedule_capture.encode_answer(rows)
        else:
            out[key] = _sanitize_str(str(v), 500)
    return out


@router.get("/generate/{session_id}")
async def generate_questions(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        proc_session = await get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")

    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    generated = proc_session.get("generated_forms", {})
    if not generated:
        raise HTTPException(400, "No forms generated yet — generate forms first")

    _facts = proc_session.get("facts", {})
    # Close the "known fact, blank box" mapping gap before generating questions:
    # back-fill any known fact whose form box is still blank (deterministically,
    # no LLM), and compute the form-aware set of facts that are genuinely present
    # on the forms. A fact we know but could not stamp anywhere is intentionally
    # left out so the client is still asked for it. Persist only when a box was
    # actually stamped so the next PDF render shows the value.
    present_on_form, _backfilled = _backfill_and_resolve_present(generated, _facts)
    if _backfilled:
        try:
            await upd_processing_session(session_id, {"generated_forms": generated})
        except Exception as _persist_ex:
            logger.warning(f"ARQ generate: back-fill persist failed: {_persist_ex}")

    # `_gen_stats` collects the "Duplicate / Merged Questions Removed" metric the
    # client asked for (canonical-fact merges folded during generation).
    _gen_stats: dict = {"merged_removed": 0}
    questions = await generate_arq_questions(
        facts=_facts,
        flags=proc_session.get("flags", {}),
        generated_forms=generated,
        hard_stops=proc_session.get("hard_stops", []),
        soft_stops=proc_session.get("soft_stops", []),
        session_docs=proc_session.get("docs", []),
        present_fact_keys=present_on_form,
        stats=_gen_stats,
    )

    # Merge cross-form conflict questions — placed at the front so the producer
    # sees structural conflict flags before the form-level missing fields.
    cf_merged = 0
    cross_form_issues = proc_session.get("cross_form_issues", [])
    if cross_form_issues:
        cf_questions = generate_cross_form_arq_questions(
            cross_form_issues, generated,
            facts=proc_session.get("facts", {}),
            flags=proc_session.get("flags", {}),
        )
        # Deduplicate by field_name against per-form questions already in the list
        existing_fields = {q["field_name"] for q in questions}
        new_cf = [q for q in cf_questions if q["field_name"] not in existing_fields]
        cf_merged = len(cf_questions) - len(new_cf)
        questions = new_cf + questions

    # Re-apply the curated default-selection policy across the FULL merged list so
    # the soft cap on pre-selected questions is global, not per-generator
    # (Beta Report §8.2 item 3 + §11 #20).
    selection_summary = apply_default_selection(questions)
    # Surface the merged-duplicate count (generation merges + route-level cross-form
    # dedup) so the UI can show "N duplicates merged" per the client's ARQ metric.
    selection_summary["merged_removed"] = _gen_stats.get("merged_removed", 0) + cf_merged

    producer_full_name  = current_user.get("full_name", "") or current_user.get("email", "")
    producer_first_name = producer_full_name.split()[0] if producer_full_name else ""

    return JSONResponse({
        "success":             True,
        "questions":           questions,
        "total_count":         len(questions),
        "selection_summary":   selection_summary,
        "default_select_cap":  DEFAULT_SELECT_CAP,
        "topic_order":         TOPIC_ORDER,
        "topic_labels":        TOPIC_LABELS,
        "bucket_order":        BUCKET_ORDER,
        "bucket_labels":       BUCKET_LABELS,
        "producer_full_name":  producer_full_name,
        "producer_first_name": producer_first_name,
    })


@router.post("/send")
async def send_arq(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    body = await request.json()

    session_id   = _sanitize_str(body.get("session_id", ""), 128)
    client_email = _sanitize_str(body.get("client_email", ""), 254).lower()
    client_name  = _sanitize_str(body.get("client_name", ""), 100)
    questions    = body.get("questions", [])

    if not session_id:
        raise HTTPException(400, "session_id is required")
    if not client_email:
        raise HTTPException(400, "client_email is required")
    if not EMAIL_RE.match(client_email):
        raise HTTPException(400, "Invalid client email address")
    if not questions:
        raise HTTPException(400, "At least one question is required")
    if len(questions) > 1000:
        raise HTTPException(400, "Too many questions in a single ARQ")

    try:
        proc_session = await get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")

    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "upload")

    guarded_questions = filter_arq_questions_for_session(
        proc_session.get("generated_forms", {}),
        questions,
    )
    if not guarded_questions:
        raise HTTPException(400, "At least one valid question is required")

    clean_questions = []
    for q in guarded_questions:
        # Defense in depth: "Never send" items (producer fax etc.) are never
        # selectable in the UI, but hard-drop them here too so a crafted payload
        # can never email a do-not-send field to the insured.
        if q.get("bucket") == BUCKET_DO_NOT_SEND or q.get("audience") == AUDIENCE_DO_NOT_SEND:
            continue
        si = q.get("score_impact") if isinstance(q.get("score_impact"), dict) else {}
        q_entry = {
            "field_name":    _sanitize_str(q.get("field_name", ""), 128),
            "question":      _sanitize_str(q.get("question", ""), 500),
            "hint":          _sanitize_str(q.get("hint", ""), 500),
            "forms":         _sanitize_str(q.get("forms", ""), 100),
            "form_ids":      q.get("form_ids", []),
            "field_type":    _sanitize_str(q.get("field_type", "text"), 32),
            # Figure 18: expected digit width for a `code` field (NAICS 6,
            # SIC 4, FEIN 9). Coerced to a small int so a crafted payload
            # cannot drive the client-side input cap.
            "code_digits":   _sanitize_digits(q.get("code_digits")),
            "current_value": "",
            # Carry the curation taxonomy so the stored ARQ keeps its grouping /
            # audience / bucket / score-impact context (Beta Report §8 + 3-bucket).
            "audience":      _sanitize_str(q.get("audience", AUDIENCE_CLIENT), 32),
            "priority":      _sanitize_str(q.get("priority", "optional"), 32),
            "bucket":        _sanitize_str(q.get("bucket", "client"), 32),
            "bucket_label":  _sanitize_str(q.get("bucket_label", "Client"), 64),
            "escalatable_to_client": bool(q.get("escalatable_to_client")),
            "topic_group":   _sanitize_str(q.get("topic_group", "other"), 48),
            "topic_label":   _sanitize_str(q.get("topic_label", "Other"), 64),
            "score_impact":  {
                "sqs":                  bool(si.get("sqs")),
                "form_completion":      bool(si.get("form_completion")),
                "submission_readiness": bool(si.get("submission_readiness")),
                "hard_stop_resolution": bool(si.get("hard_stop_resolution")),
            },
        }
        # Preserve select options so the client questionnaire can render a dropdown
        raw_opts = q.get("options")
        if isinstance(raw_opts, list) and raw_opts:
            q_entry["options"] = [_sanitize_str(str(o), 200) for o in raw_opts]

        # Figure 20: preserve the unconfirmed NAICS / SIC candidates so the
        # client questionnaire can render the suggestion chips. Without this the
        # personalized HINT survived (it is a plain string on q_entry above) but
        # the candidates themselves were dropped here, before the ARQ was ever
        # stored - so `client_view` had nothing to serve and no chips appeared.
        # Sanitized rather than trusted: this arrives in a producer request body.
        _clean_sugg = _sanitize_suggestions(q.get("suggestions"))
        if _clean_sugg:
            q_entry["suggestions"] = _clean_sugg

        # Preserve the schedule spec (Figure 15) so the client questionnaire can
        # render the table. The column spec and any pre-loaded rows are rebuilt
        # from the server-side definition rather than trusted from the request,
        # so a crafted payload cannot inject columns or oversized row data.
        if q.get("field_type") == "schedule":
            _lk = _sanitize_str(q.get("schedule_key", ""), 64)
            _sdef = schedule_capture.get_def(_lk)
            if _sdef is None:
                continue
            _rows, _ = schedule_capture.validate_rows(_lk, q.get("current_rows") or [])
            q_entry["schedule_key"]      = _lk
            q_entry["schedule_label"]    = _sdef["label"]
            q_entry["schedule_singular"] = _sdef["singular"]
            q_entry["columns"]           = _sdef["columns"]
            q_entry["dedup_keys"]        = _sdef["dedup_keys"]
            q_entry["vin_decode"]        = bool(_sdef["vin_decode"])
            q_entry["row_capacity"]      = schedule_capture.ROW_CAPACITY
            q_entry["current_rows"]      = _rows

        clean_questions.append(q_entry)

    if not clean_questions:
        raise HTTPException(400, "At least one valid question is required")

    arq_data = await create_arq_session(
        processing_session_id=session_id,
        user_id=current_user["id"],
        client_email=client_email,
        client_name=client_name,
        questions=clean_questions,
    )

    arq_link      = f"{FRONTEND_URL}/questionnaire/{arq_data['token']}"
    producer_name = current_user.get("full_name", "") or current_user.get("email", "")
    first_name    = producer_name.split()[0] if producer_name else "Your Agent"

    email_sent = send_arq_email(
        to_email=client_email,
        client_name=client_name,
        producer_full_name=producer_name,
        producer_first_name=first_name,
        arq_link=arq_link,
    )

    logger.info(f"ARQ sent: arq_id={arq_data['arq_id']} to={client_email} email_ok={email_sent}")

    # Package activity log (best-effort). Store only the client FIRST name, never
    # the email, so the log table holds no fresh PII.
    _client_first = (client_name or "").split()[0] if client_name else ""
    await record_event(
        current_user["id"], session_id, EVENT_ARQ_SENT,
        {"client_first": _client_first, "question_count": len(clean_questions)},
    )

    return JSONResponse({
        "success":    True,
        "arq_id":     arq_data["arq_id"],
        "email_sent": email_sent,
        "expires_at": arq_data["expires_at"],
        "link":       arq_link,
    })


@router.get("/client-view/{token}")
async def client_view(token: str, request: Request):
    client_ip = get_client_ip(request)
    await check_arq_public_rate_limit(client_ip)

    if not token or len(token) > 128 or not re.match(r"^[a-f0-9\-]+$", token):
        return JSONResponse({"success": False, "error": "not_found", "message": "Questionnaire not found."}, status_code=404)

    arq = await get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "error": "not_found", "message": "Questionnaire not found."}, status_code=404)

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if now > expires:
        return JSONResponse({"success": False, "error": "expired", "message": "This link has expired."}, status_code=410)
    if arq["status"] == "submitted":
        return JSONResponse({"success": False, "error": "already_submitted", "message": "Already submitted."}, status_code=409)

    # Log the first open only (viewed_at is set once, on first view).
    if not arq.get("viewed_at"):
        _cf = (arq.get("client_name") or "").split()[0] if arq.get("client_name") else ""
        await record_event(
            arq["user_id"], arq.get("session_id"), EVENT_ARQ_OPENED,
            {"client_first": _cf},
        )
    await mark_arq_viewed(token)

    producer_email = ""
    producer_phone = ""
    producer_name  = ""
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, full_name, phone FROM users WHERE id=$1", arq["user_id"]
            )
        if row:
            producer_email = dict(row).get("email", "") or ""
            producer_name  = dict(row).get("full_name", "") or ""
            # Previously never populated: the query omitted `phone`, so the
            # client's "Contact Your Agent" card silently dropped the number.
            producer_phone = dict(row).get("phone", "") or ""
    except Exception as ex:
        logger.warning(f"client_view: could not fetch producer info: {ex}")

    draft_answers = arq.get("draft_answers") or {}
    if isinstance(draft_answers, str):
        import json as _json
        try:
            draft_answers = _json.loads(draft_answers)
        except Exception:
            draft_answers = {}

    questions_for_client = []
    for q in arq.get("questions", []):
        q_item = {
            "field_name":    q["field_name"],
            "question":      q["question"],
            "hint":          q.get("hint", ""),
            "forms":         q.get("forms", ""),
            "field_type":    q.get("field_type", "text"),
            "code_digits":   q.get("code_digits") or 0,
            "current_value": "",
        }
        if q.get("field_type") == "select" and isinstance(q.get("options"), list):
            q_item["options"] = q["options"]
        # Figure 20: unconfirmed NAICS / SIC candidates for the chip row. Kept
        # out of `current_value` on purpose - a suggestion must never arrive
        # pre-filled. Re-validated here rather than trusted, because the ARQ
        # record is persisted JSON that outlives the generator that wrote it.
        _clean = _sanitize_suggestions(q.get("suggestions"))
        if _clean:
            q_item["suggestions"] = _clean
        # Figure 15: hand the table spec + any pre-loaded rows to the renderer.
        # Columns are re-read from the server-side definition so a stored ARQ
        # always renders against the current schema, never a stale snapshot.
        if q.get("field_type") == "schedule":
            _lk = q.get("schedule_key", "")
            _sdef = schedule_capture.get_def(_lk)
            if _sdef is None:
                continue
            _rows, _ = schedule_capture.validate_rows(_lk, q.get("current_rows") or [])
            # Master-plan 4.9 / core principle 5 (2026-08-26): a column flagged
            # `producer_only` is stripped from the CLIENT's copy of the table.
            # Covered-auto symbols are the live case - they are a producer
            # decision with their own producer question, so showing the column
            # here asked the insured to classify coverage. This is the ONLY
            # place the flag is applied: the producer's own table (served whole
            # by /generate), the pre-load endpoint and the stamping path all
            # keep every column, so nothing the agency fills is lost.
            _client_cols = [c for c in _sdef["columns"]
                            if not (isinstance(c, dict) and c.get("producer_only"))]
            q_item.update({
                "schedule_key":      _lk,
                "schedule_label":    _sdef["label"],
                "schedule_singular": _sdef["singular"],
                "columns":           _client_cols,
                "dedup_keys":        _sdef["dedup_keys"],
                "vin_decode":        bool(_sdef["vin_decode"]),
                "row_capacity":      schedule_capture.ROW_CAPACITY,
                "current_rows":      _rows,
            })
        questions_for_client.append(q_item)

    return JSONResponse({
        "success":        True,
        "client_name":    arq.get("client_name", ""),
        "questions":      questions_for_client,
        "draft_answers":  draft_answers,
        "expires_at":     arq["expires_at"],
        "producer_name":  producer_name,
        "producer_email": producer_email,
        "producer_phone": producer_phone,
    })


@router.patch("/draft/{token}")
async def save_draft(token: str, request: Request):
    client_ip = get_client_ip(request)
    await check_arq_public_rate_limit(client_ip)

    if not token or len(token) > 128 or not re.match(r"^[a-f0-9\-]+$", token):
        return JSONResponse({"success": False, "message": "Invalid token."}, status_code=400)

    arq = await get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "message": "Questionnaire not found."}, status_code=404)

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return JSONResponse({"success": False, "message": "Link expired."}, status_code=410)
    if arq["status"] == "submitted":
        return JSONResponse({"success": True, "message": "Already submitted."})

    body = await request.json()
    raw_answers = body.get("answers", {})
    if not isinstance(raw_answers, dict) or len(raw_answers) > 500:
        return JSONResponse({"success": False, "message": "Invalid answers."}, status_code=400)

    sanitized = _sanitize_answers(raw_answers)

    # Detect first-draft transition (arq snapshot is pre-save) so the activity
    # log records "in progress" once, not on every autosave. draft_answers comes
    # back as a JSONB dict OR a JSON string (see client_view above), so handle both
    # forms - otherwise the guard never sees a prior draft and re-logs every save.
    _prev_draft = arq.get("draft_answers")
    if isinstance(_prev_draft, dict):
        _had_draft = len(_prev_draft) > 0
    elif isinstance(_prev_draft, str):
        _had_draft = _prev_draft.strip() not in ("", "{}", "null")
    else:
        _had_draft = False

    await save_arq_draft(token, sanitized)

    if not _had_draft and sanitized:
        _cf = (arq.get("client_name") or "").split()[0] if arq.get("client_name") else ""
        await record_event(
            arq["user_id"], arq.get("session_id"), EVENT_ARQ_IN_PROGRESS,
            {"client_first": _cf},
        )
    return JSONResponse({"success": True})


@router.post("/submit/{token}")
async def submit_arq(token: str, request: Request):
    client_ip = get_client_ip(request)
    await check_arq_submit_rate_limit(client_ip)

    if not token or len(token) > 128:
        return JSONResponse({"success": False, "message": "Invalid token."}, status_code=400)

    body        = await request.json()
    raw_answers = body.get("answers", {})

    if not isinstance(raw_answers, dict) or not raw_answers:
        return JSONResponse({"success": False, "message": "No answers provided."}, status_code=400)
    if len(raw_answers) > 500:
        return JSONResponse({"success": False, "message": "Too many fields in submission."}, status_code=400)

    sanitized_answers = _sanitize_answers(raw_answers)

    arq = await get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "message": "Questionnaire not found."}, status_code=404)

    ok, msg, updated_fields, field_errors = await submit_arq_answers(
        token=token,
        raw_answers=sanitized_answers,
        processing_session_id=arq["session_id"],
        generated_forms={},
    )

    if field_errors:
        # 422 + field_errors is the shape the questionnaire already knows how
        # to render: it highlights each field and scrolls to the first one.
        # Nothing was written, and the client's draft is still saved, so they
        # simply correct the format and resubmit.
        return JSONResponse(
            {"success": False, "message": msg, "field_errors": field_errors},
            status_code=422,
        )

    if not ok:
        return JSONResponse({"success": False, "message": msg}, status_code=400)

    apply_ok, applied_fields = await apply_arq_answers_to_session(
        arq_id=arq["id"],
        processing_session_id=arq["session_id"],
    )

    # Recalculate scores/stops/readiness so the producer sees the impact of the
    # client's answers on next view (Beta Report §6.2 / §8.2.7). Pure-Python and
    # cheap; failures here must not break the client's submission confirmation.
    score_update = {}
    if apply_ok:
        try:
            score_update = await recalculate_session_scores(arq["session_id"])
        except Exception as _recalc_ex:
            logger.error(f"ARQ submit: score recalculation failed: {_recalc_ex}", exc_info=True)
            # Don't swallow the failure silently: mark it so the producer can be
            # told scores are stale rather than assuming remediation took effect.
            score_update = {"ok": False}

    # §6.2: persist remediation status + answer count so the producer sees them
    # in the ARQ panel without re-running the recalculation.
    if score_update.get("ok") and score_update.get("status"):
        try:
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE arq_sessions SET remediation_status=$1, fields_answered_count=$2 WHERE id=$3",
                    score_update["status"],
                    len(sanitized_answers),
                    arq["id"],
                )
        except Exception as _persist_ex:
            logger.error(f"ARQ submit: failed to persist remediation_status: {_persist_ex}")

    # Figure 21: immutable client response receipt, written before any
    # notification goes out so the record exists by the time anyone acts on it.
    #
    # Built from the arq row RE-READ after the submit write, not from the
    # request body: the row is what the server actually accepted and stored
    # (post-normalization, with the "I'm not sure" list and the review flags
    # split out), which is the thing worth recording. Falls back to the
    # pre-read row if that re-read fails, so a receipt is still written.
    _submitted_arq = await get_arq_by_id(arq["id"]) or arq
    receipt_id     = await create_receipt(_submitted_arq)

    await create_arq_notification(arq["id"], arq["user_id"], "submitted")

    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, full_name FROM users WHERE id=$1", arq["user_id"]
            )
        if row:
            producer = dict(row)
            send_arq_submitted_notification(
                producer_email=producer["email"],
                producer_name=producer.get("full_name", ""),
                client_name=arq.get("client_name", ""),
                client_email=arq["email"],
                fields_filled=len(applied_fields),
                session_id=arq["session_id"],
                frontend_url=FRONTEND_URL,
            )
    except Exception as ex:
        logger.error(f"ARQ submit: notification email failed: {ex}")

    logger.info(f"ARQ submitted: arq_id={arq['id']} applied_fields={len(applied_fields)}")

    # Package activity log: the client's submit, then the system apply + re-score.
    _cf = (arq.get("client_name") or "").split()[0] if arq.get("client_name") else ""
    await record_event(
        arq["user_id"], arq.get("session_id"), EVENT_ARQ_SUBMITTED,
        # `receipt_id` is what attaches the response receipt to the package
        # audit trail: the timeline entry now points at the immutable record of
        # what was said, instead of only counting it.
        {"client_first": _cf, "fields": len(sanitized_answers),
         "receipt_id": receipt_id, "arq_id": arq["id"]},
    )
    if apply_ok:
        await record_event(
            arq["user_id"], arq.get("session_id"), EVENT_ANSWERS_APPLIED,
            {"client_first": _cf, "fields_updated": len(applied_fields),
             "scores_updated": bool(score_update.get("ok"))},
        )

    return JSONResponse({
        "success":        True,
        "message":        "Answers submitted successfully.",
        "fields_updated": len(applied_fields),
        # Explicit flag so the frontend can warn the producer when scores could not
        # be recalculated (recalc threw or failed) instead of showing stale numbers.
        "scores_updated": bool(score_update.get("ok")),
        "score_update":   score_update,
        # Short human-quotable reference so the client's confirmation is an
        # actual receipt they can cite back to their agent. Only the leading
        # segment of the uuid is exposed - enough to look up, not enough to
        # enumerate, and the endpoint that serves receipts is keyed on arq_id
        # + owner anyway, never on this string.
        "receipt_ref":    (receipt_id.split("-")[0].upper() if receipt_id else ""),
    })


# ---------------------------------------------------------------------------
# Form Assistant context (Figure 19)
# ---------------------------------------------------------------------------
# The assistant used to receive only a flat list of question texts, so it had no
# idea which field the client was actually looking at, what shape of answer that
# field accepts, or anything about the business - which made an unqualified
# "where do I find this?" unanswerable. These helpers build the context block.

_ANSWER_TYPE_HELP = {
    "text":     "free text",
    "number":   "a number",
    "currency": "a dollar amount, e.g. $250,000",
    "date":     "a date written MM/DD/YYYY",
    "code":     "a numeric code",
    "select":   "one of the listed options, nothing else",
    "checkbox": "yes or no",
    "schedule": "a table the client fills in one row at a time",
}

# A questionnaire this large is pathological, but the prompt must stay bounded.
_ASSISTANT_MAX_LISTED_QUESTIONS = 120


def _assistant_field_block(q: dict) -> str:
    """Full detail for the ONE field the client currently has focused."""
    lines = [f'QUESTION: "{(q.get("question") or "").strip()}"',
             f'QUESTION ID: {q.get("field_name", "")}']
    hint = (q.get("hint") or "").strip()
    if hint:
        lines.append(f"GUIDANCE ALREADY ON SCREEN: {hint}")

    ft = q.get("field_type") or "text"
    lines.append(f"ANSWER TYPE: {_ANSWER_TYPE_HELP.get(ft, ft)}")

    if ft == "code" and q.get("code_digits"):
        lines.append(f"REQUIRED LENGTH: exactly {q['code_digits']} digits")
    if ft == "select" and isinstance(q.get("options"), list) and q["options"]:
        opts = " | ".join(str(o) for o in q["options"][:20])
        lines.append(f"ONLY THESE ANSWERS ARE ACCEPTED: {opts}")
    if q.get("forms"):
        lines.append(f"APPEARS ON: {q['forms']}")

    # Figure 20: NAICS / SIC candidates derived from this business's own
    # operations text. Rule 7 forbids stating a code as though it were the
    # client's confirmed answer, so these are handed over explicitly labelled as
    # unconfirmed suggestions that are already on screen next to the box.
    picks = q.get("suggestions")
    if isinstance(picks, list) and picks:
        rendered = "; ".join(
            f"{p.get('code','')} ({p.get('label','')}, {p.get('confidence','')} match)"
            for p in picks[:3] if isinstance(p, dict) and p.get("code")
        )
        if rendered:
            lines.append(
                "UNCONFIRMED SUGGESTIONS SHOWN NEXT TO THIS FIELD (derived from this "
                f"business's described operations, NOT confirmed): {rendered}. "
                "You may discuss these and explain what each one covers, but always "
                "say they must be confirmed with their agent before being relied on, "
                "and that leaving the box blank is fine."
            )
    return "\n".join(lines)


def _assistant_question_list(questions: list, active_q: dict = None) -> str:
    """Compact roster of every question, with the focused one flagged.

    Question text is clipped: the assistant needs to know a question EXISTS and
    roughly what it asks, but only the focused field needs full detail - and an
    unbounded roster is what makes these prompts expensive.
    """
    out = []
    for i, q in enumerate(questions[:_ASSISTANT_MAX_LISTED_QUESTIONS], 1):
        txt = (q.get("question") or "").strip()
        if len(txt) > 160:
            txt = txt[:157] + "..."
        here = "   <-- CLIENT IS LOOKING AT THIS ONE" if active_q is not None and q is active_q else ""
        # Rule 12 forbids naming an option that is not on the list, so a select
        # field the client has NOT focused still has to carry its options -
        # otherwise the model has nothing to be faithful to and will invent them.
        # Selects are a handful per questionnaire, so this costs almost nothing.
        opts = q.get("options")
        picks = ""
        if q.get("field_type") == "select" and isinstance(opts, list) and 0 < len(opts) <= 8:
            picks = " (options: " + " | ".join(str(o) for o in opts) + ")"
        out.append(f"{i}. {txt}{picks} [id: {q.get('field_name','')}]{here}")
    if len(questions) > _ASSISTANT_MAX_LISTED_QUESTIONS:
        out.append(f"...and {len(questions) - _ASSISTANT_MAX_LISTED_QUESTIONS} more questions.")
    return "\n".join(out) if out else "No specific questions available."


async def _assistant_package_context(arq: dict) -> str:
    """Business + package context for the assistant.

    Best-effort by design: the questionnaire link outlives nothing here, but the
    underlying processing session can be missing or undecryptable, and chat must
    keep working regardless. Never raises.
    """
    lines = []

    forms = sorted({
        f.strip()
        for q in (arq.get("questions") or [])
        for f in str(q.get("forms", "") or "").split(",")
        if f.strip()
    })
    if forms:
        lines.append(f"INSURANCE FORMS IN THIS PACKAGE: {', '.join(forms)}")

    sid = arq.get("session_id")
    if sid:
        try:
            sess  = await get_processing_session(sid)
            facts = sess.get("facts") or {}

            def _fact(key: str) -> str:
                v = facts.get(key)
                if isinstance(v, dict) and "value" in v:
                    v = v.get("value")
                return str(v).strip() if v not in (None, "") else ""

            name = _fact("applicant_name")
            if name:
                lines.append(f"BUSINESS: {name}")
            desc = _fact("operations_description")
            if desc:
                lines.append(f"WHAT THE BUSINESS DOES: {desc[:300]}")
        except Exception as ex:
            logger.debug(f"assistant package context unavailable for {sid}: {ex}")

    return "\n".join(lines)


_ARQ_ASSISTANT_RULES = """You are Primble's Form Assistant. You help a business owner fill in an insurance questionnaire their agent sent them. Assume they are not an insurance expert.

WHAT YOU DO:
1. Explain what a question on this form means, in plain English.
2. Explain where to find information they do not have on hand - which document, filing, or website to look at, or who to ask.
3. Explain what format an answer must be in, using the ANSWER TYPE given for that field.
4. Answer general insurance-terminology questions when they relate to a question on this form.

WHAT YOU NEVER DO:
5. Never recommend coverage, limits, deductibles, endorsements or carriers, and never say whether a coverage is enough, needed, wise or a good deal. That is their agent's job. If asked, say so plainly and offer to explain what the question means instead.
6. Never give legal, tax, or claims advice.
7. Never state a specific code, number, date or dollar amount as though it were this business's real answer. You may give a clearly-labelled example of the right SHAPE ("a roofing contractor would use something like 238160"), and you must tell them to confirm it with their agent before relying on it.
8. Never claim to fill in, change, or submit an answer. You cannot - you can only explain.
9. If a request has nothing to do with this form or with insurance, politely steer back.

HOW YOU ANSWER:
10. Be concise and friendly: 2-4 sentences. No jargon. No bullet lists unless you are listing allowed options.
11. If a CURRENT FIELD is shown below, the client is looking at it right now. Treat an unqualified question - "where do I find this?", "what does this mean?", "is this required?" - as being about THAT field, and answer it directly. Do not ask them which question they mean.
12. Respect the field's ANSWER TYPE exactly. Never suggest an answer that would not fit it, and if the field lists accepted options, never name one that is not on the list.
13. Leaving a question blank is always allowed when they genuinely do not know. Say so rather than pushing them to guess.
14. Write plain text only. The chat window does not render Markdown, so asterisks, underscores, backticks and hash headings appear literally to the client. Never use them - to stress a value, just write it plainly."""


@router.post("/chat/{token}")
async def arq_chat(token: str, request: Request):
    from config.settings import groq_chat, LLM_MODEL

    client_ip = get_client_ip(request)
    await check_arq_chat_rate_limit(client_ip)

    if not token or len(token) > 128 or not re.match(r"^[a-f0-9\-]+$", token):
        return JSONResponse({"success": False, "reply": "Session not found."}, status_code=404)

    arq = await get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "reply": "Session not found."}, status_code=404)

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return JSONResponse({"success": False, "reply": "This questionnaire link has expired."}, status_code=410)
    if arq.get("status") == "submitted":
        return JSONResponse({"success": False, "reply": "This questionnaire has already been submitted."}, status_code=409)

    body    = await request.json()
    message = _sanitize_str(body.get("message", ""), 500)
    history = body.get("history", [])
    # Figure 19: the field the client has focused in the UI, sent as its
    # field_name (the stable question id used everywhere else in the ARQ).
    active_field = _sanitize_str(body.get("active_field", ""), 200)

    if not message:
        return JSONResponse({"success": False, "reply": "No message provided."}, status_code=400)

    history = [h for h in history[-6:] if h.get("role") in ("user", "assistant") and h.get("content")]

    questions = arq.get("questions", [])
    active_q  = next(
        (q for q in questions if q.get("field_name") == active_field), None
    ) if active_field else None

    questions_ctx = _assistant_question_list(questions, active_q)
    package_ctx   = await _assistant_package_context(arq)

    context_parts = []
    if package_ctx:
        context_parts.append(package_ctx)
    if active_q is not None:
        context_parts.append("CURRENT FIELD (the client has this one open right now):\n"
                             + _assistant_field_block(active_q))
    context_parts.append(f"EVERY QUESTION ON THIS FORM:\n{questions_ctx}")

    system_prompt = _ARQ_ASSISTANT_RULES + "\n\n--- CONTEXT ---\n" + "\n\n".join(context_parts)

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": h["role"], "content": _sanitize_str(h.get("content", ""), 500)})
    messages.append({"role": "user", "content": message})

    # Both uses below are technical failures (empty completion / exception), not
    # refusals - so this must not read like the assistant declined to help.
    fallback = "Sorry, I couldn't get you an answer just now. Please try again in a moment, or ask your agent."

    try:
        reply = await groq_chat(
            LLM_MODEL,
            messages,
            temperature=0.3,
            max_tokens=300,
        )
        if not reply or len(reply) < 5:
            reply = fallback
        return JSONResponse({"success": True, "reply": reply})
    except Exception as ex:
        logger.error(f"ARQ chat failed: {ex}")
        return JSONResponse({"success": True, "reply": fallback})


@router.get("/status/{arq_id}")
async def get_arq_status(
    arq_id: str,
    current_user: dict = Depends(get_current_user),
):
    arq = await get_arq_by_id(arq_id)
    if not arq:
        raise HTTPException(404, "ARQ session not found")
    if arq["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    return JSONResponse({
        "success":         True,
        "arq_id":          arq["id"],
        "status":          arq["status"],
        "client_email":    arq["email"],
        "client_name":     arq.get("client_name", ""),
        "created_at":      str(arq["created_at"]),
        "submitted_at":    str(arq.get("submitted_at") or ""),
        "viewed_at":       str(arq.get("viewed_at") or ""),
        "expires_at":      arq["expires_at"],
        "reminder_count":  arq.get("reminder_count", 0),
        "fields_answered": len(arq.get("answers", {})),
        "total_questions": len(arq.get("questions", [])),
        # Fields the client explicitly could not answer ("I'm not sure"), kept
        # distinct from fields they simply never reached.
        "not_sure_fields": arq.get("not_sure_fields", []),
        "not_sure_count":  len(arq.get("not_sure_fields", []) or []),
        # Figure 18: answers the client gave that could not be normalized. Kept
        # in `answers`, surfaced here so the producer can confirm them.
        "review_fields":   arq.get("review_fields", []),
        "review_count":    len(arq.get("review_fields", []) or []),
    })


@router.get("/receipt/{arq_id}")
async def get_arq_receipt(
    arq_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Figure 21: the read-only client response receipt.

    READ ONLY in the strict sense - there is deliberately no PUT/PATCH/DELETE
    counterpart anywhere in the codebase. The record of what a client told their
    underwriter must not be editable after the fact, by them or by us.

    Ownership is enforced twice on purpose: once here against the ARQ row (so an
    unknown id 404s rather than leaking existence), and again inside
    `get_receipt_for_arq`, where user_id is part of the WHERE clause.
    """
    arq = await get_arq_by_id(arq_id)
    if not arq:
        raise HTTPException(404, "ARQ session not found")
    if arq["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    receipt = await get_receipt_for_arq(arq_id, current_user["id"])
    if not receipt:
        # A questionnaire submitted before this feature existed has no receipt,
        # and that is a normal state - not an error. The panel says so rather
        # than implying the data was lost.
        return JSONResponse({
            "success": True,
            "receipt": None,
            "reason":  "not_submitted" if arq.get("status") != "submitted" else "no_receipt",
        })

    return JSONResponse({
        "success": True,
        "receipt": {
            "receipt_ref":    str(receipt["id"]).split("-")[0].upper(),
            "arq_id":         receipt["arq_id"],
            "client_name":    receipt.get("client_name", ""),
            "client_email":   receipt.get("client_email", ""),
            "submitted_at":   str(receipt.get("submitted_at") or ""),
            "item_count":     receipt.get("item_count", 0),
            "answered_count": receipt.get("answered_count", 0),
            "not_sure_count": receipt.get("not_sure_count", 0),
            "review_count":   receipt.get("review_count", 0),
            "unreadable":     bool(receipt.get("unreadable")),
            "items":          receipt.get("items", []),
        },
    })


@router.get("/list/{session_id}")
async def list_arqs(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    _BASE_COLS = (
        "SELECT id, status, email, client_name, created_at, submitted_at, viewed_at, expires_at, "
        "reminder_count, remediation_status, fields_answered_count"
    )
    async with get_pool().acquire() as conn:
        try:
            rows = await conn.fetch(
                _BASE_COLS + ", not_sure_fields, review_fields, "
                "(draft_answers IS NOT NULL AND draft_answers::text <> '{}') AS has_draft "
                "FROM arq_sessions WHERE session_id=$1 AND user_id=$2 ORDER BY created_at DESC",
                session_id, current_user["id"],
            )
        except Exception as ex:
            # `not_sure_fields` / `draft_answers` are added by init_db() at
            # startup. If that ALTER was skipped (its DDL loop swallows errors,
            # or the instance has not been restarted since the column was
            # introduced) this query would 500 and take the whole "Sent
            # Questionnaires" panel down with it. Degrade to the columns that
            # have always existed instead of failing the request.
            logger.warning(
                "list_arqs: optional columns unavailable (%s) — falling back to base columns", ex,
            )
            rows = await conn.fetch(
                _BASE_COLS + " FROM arq_sessions WHERE session_id=$1 AND user_id=$2 "
                "ORDER BY created_at DESC",
                session_id, current_user["id"],
            )

    # `not_sure_fields` / `review_fields` are JSONB and asyncpg may hand them
    # back as raw strings depending on the codec, so normalize to a list before
    # serializing. NULL on rows created before the column existed -> empty list,
    # as is the degraded fallback path above which selects neither column.
    def _as_list(v):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                return []
        return v if isinstance(v, list) else []

    sessions = []
    for r in rows:
        d = dict(r)
        nsf = _as_list(d.get("not_sure_fields"))
        d["not_sure_fields"] = nsf
        d["not_sure_count"]  = len(nsf)
        rvf = _as_list(d.get("review_fields"))
        d["review_fields"]   = rvf
        d["review_count"]    = len(rvf)
        # Present even on the degraded fallback path above, so the UI never has
        # to distinguish "no draft" from "column missing".
        d.setdefault("has_draft", False)
        sessions.append(d)

    return JSONResponse({"success": True, "arq_sessions": sessions})


@router.post("/remind/{arq_id}")
async def send_reminder(
    arq_id: str,
    current_user: dict = Depends(get_current_user),
):
    arq = await get_arq_by_id(arq_id)
    if not arq:
        raise HTTPException(404, "ARQ session not found")
    if arq["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    if arq["status"] == "submitted":
        raise HTTPException(400, "Client has already submitted this questionnaire")

    ok = await send_arq_reminder(arq_id, current_user)
    if ok:
        _cf = (arq.get("client_name") or "").split()[0] if arq.get("client_name") else ""
        await record_event(
            arq["user_id"], arq.get("session_id"), EVENT_REMINDER_SENT,
            {"client_first": _cf, "reminder_count": (arq.get("reminder_count", 0) or 0) + 1},
        )
    return JSONResponse({"success": ok, "message": "Reminder sent." if ok else "Failed to send reminder."})


@router.get("/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    notifs = await get_arq_notifications(current_user["id"])
    return JSONResponse({"success": True, "notifications": notifs})


@router.post("/notifications/read")
async def mark_read(current_user: dict = Depends(get_current_user)):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    await mark_notifications_read(current_user["id"])
    return JSONResponse({"success": True})


@router.get("/schedules/{session_id}")
async def list_session_schedules(
    session_id: str,
    schedule_key: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Producer pre-load (Figure 15): the schedules this package can capture.

    ``schedule_key`` (optional) limits the response to a single schedule - the
    inline ResolutionModal needs exactly one, so it avoids building/validating
    every schedule for the session (client #2 latency fix). Omitted -> all.
    """
    try:
        proc_session = await get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    only_key = _sanitize_str(schedule_key, 64) or None
    schedules = await get_session_schedules(session_id, only_key=only_key)
    return JSONResponse({"success": True, "schedules": schedules})


@router.put("/schedules/{session_id}")
async def save_session_schedule_route(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Producer pre-load save: validate, store in facts, stamp the forms."""
    try:
        proc_session = await get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    body     = await request.json()
    list_key = _sanitize_str(body.get("schedule_key", ""), 64)
    rows     = body.get("rows", [])

    if schedule_capture.get_def(list_key) is None:
        raise HTTPException(400, "Unknown schedule key")
    if not isinstance(rows, list):
        raise HTTPException(400, "rows must be a list")
    if len(rows) > schedule_capture.MAX_ROWS:
        raise HTTPException(
            400, f"Too many rows (max {schedule_capture.MAX_ROWS})",
        )

    # E&O 5.9/5.11: schedule pre-load saves replaced facts[list_key] wholesale
    # with no audit row at all until 2026-08-26. One row per save, summarized
    # by row count (the rows themselves live in facts).
    _prev_rows = (proc_session.get("facts") or {}).get(list_key)
    if isinstance(_prev_rows, dict):
        _prev_rows = _prev_rows.get("value")
    _prev_n = len(_prev_rows) if isinstance(_prev_rows, list) else 0

    ok, result = await save_session_schedule(session_id, list_key, rows)
    if not ok:
        raise HTTPException(400, result.get("message", "Could not save schedule"))
    try:
        from services.audit_service import log_field_change
        from services.sqs_service import SQS_MODEL_VERSION
        await log_field_change(
            session_id=session_id, user_id=str(current_user["id"]),
            form_id=None, field_name=f"schedule::{list_key}", fact_key=list_key,
            source="producer", previous_value=f"{_prev_n} row(s)",
            new_value=f"{len(result.get('rows') or [])} row(s)",
            confidence="filled", model_version=SQS_MODEL_VERSION,
        )
    except Exception as _se:
        logger.warning(f"save_session_schedule_route: audit log failed: {_se}")
    return JSONResponse({"success": True, **result})


# Small in-process cache: a fleet import decodes many VINs at once and the same
# VIN is commonly re-decoded on edit. Bounded so it can never grow unbounded.
_VIN_CACHE: dict = {}
_VIN_CACHE_MAX = 2000


@router.post("/decode-vin")
async def decode_vin(request: Request):
    """Decode VINs via the NHTSA vPIC service (public, free, no API key).

    Proxied server-side rather than called from the browser so that: the page
    keeps a strict connect-src, results are cached across users, and a vPIC
    outage degrades to manual entry instead of a console error. Unauthenticated
    because the client questionnaire (a tokenless public page) needs it, so it
    is rate-limited on the caller's IP like the other public ARQ endpoints.
    """
    client_ip = get_client_ip(request)
    await check_arq_public_rate_limit(client_ip)

    body = await request.json()
    raw_vins = body.get("vins", [])
    if not isinstance(raw_vins, list):
        raise HTTPException(400, "vins must be a list")
    # Bounded per call; the frontend chunks a large import into batches.
    vins = [schedule_capture.normalize_vin(v) for v in raw_vins[:50]]
    vins = [v for v in vins if schedule_capture.is_valid_vin(v)]
    if not vins:
        return JSONResponse({"success": True, "results": {}})

    results: dict = {}
    pending = []
    for vin in vins:
        if vin in _VIN_CACHE:
            results[vin] = _VIN_CACHE[vin]
        else:
            pending.append(vin)

    if pending:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                for vin in pending:
                    try:
                        resp = await client.get(
                            "https://vpic.nhtsa.dot.gov/api/vehicles/"
                            f"DecodeVinValues/{vin}?format=json"
                        )
                        data = (resp.json().get("Results") or [{}])[0]
                    except Exception as ex:
                        logger.info(f"decode_vin: lookup failed for {vin[:8]}…: {ex}")
                        continue
                    decoded = {
                        "year":      str(data.get("ModelYear") or "").strip(),
                        "make":      str(data.get("Make") or "").strip().title(),
                        "model":     str(data.get("Model") or "").strip(),
                        "body_type": str(data.get("BodyClass") or "").strip(),
                    }
                    # vPIC answers 200 with empty fields for an unknown VIN;
                    # only cache/return a decode that actually identified it.
                    if not decoded["make"] and not decoded["year"]:
                        continue
                    if len(_VIN_CACHE) < _VIN_CACHE_MAX:
                        _VIN_CACHE[vin] = decoded
                    results[vin] = decoded
        except Exception as ex:
            logger.warning(f"decode_vin: vPIC unavailable: {ex}")

    return JSONResponse({"success": True, "results": results})


@router.get("/client-filled/{session_id}")
async def get_client_filled(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    fields = await get_client_filled_fields(session_id)
    return JSONResponse({"success": True, "client_filled_fields": fields})
