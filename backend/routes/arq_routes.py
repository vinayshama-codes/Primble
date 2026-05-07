import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from config.database import get_pool
from config.settings import FRONTEND_URL
from repositories.session_repository import get_processing_session
from services.arq_service import (
    apply_arq_answers_to_session,
    create_arq_notification,
    create_arq_session,
    generate_arq_questions,
    get_arq_by_id,
    get_arq_by_token,
    get_arq_notifications,
    get_arq_sessions_for_user,
    get_client_filled_fields,
    mark_arq_viewed,
    mark_notifications_read,
    save_arq_draft,
    send_arq_reminder,
    submit_arq_answers,
)
from services.auth_service import get_current_user
from services.email_service import send_arq_email, send_arq_submitted_notification
from utils.rate_limiter import check_arq_public_rate_limit, check_arq_submit_rate_limit, check_arq_chat_rate_limit, get_client_ip

router = APIRouter(prefix="/api/arq", tags=["arq"])
logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _sanitize_str(val: str, max_len: int = 500) -> str:
    if not val:
        return ""
    val = re.sub(r"<[^>]*>", "", str(val))
    return val.strip()[:max_len]


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

    generated = proc_session.get("generated_forms", {})
    if not generated:
        raise HTTPException(400, "No forms generated yet — generate forms first")

    questions = await generate_arq_questions(
        facts=proc_session.get("facts", {}),
        flags=proc_session.get("flags", {}),
        generated_forms=generated,
        hard_stops=proc_session.get("hard_stops", []),
        soft_stops=proc_session.get("soft_stops", []),
    )

    producer_full_name  = current_user.get("full_name", "") or current_user.get("email", "")
    producer_first_name = producer_full_name.split()[0] if producer_full_name else ""

    return JSONResponse({
        "success":             True,
        "questions":           questions,
        "total_count":         len(questions),
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
    if len(questions) > 500:
        raise HTTPException(400, "Too many questions in a single ARQ")

    try:
        proc_session = await get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")

    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")

    clean_questions = []
    for q in questions:
        clean_questions.append({
            "field_name":    _sanitize_str(q.get("field_name", ""), 128),
            "question":      _sanitize_str(q.get("question", ""), 500),
            "forms":         _sanitize_str(q.get("forms", ""), 100),
            "form_ids":      q.get("form_ids", []),
            "field_type":    _sanitize_str(q.get("field_type", "text"), 32),
            "current_value": "",
        })

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
    check_arq_public_rate_limit(client_ip)

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

    await mark_arq_viewed(token)

    producer_email = ""
    producer_phone = ""
    producer_name  = ""
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, full_name FROM users WHERE id=$1", arq["user_id"]
            )
        if row:
            producer_email = dict(row).get("email", "") or ""
            producer_name  = dict(row).get("full_name", "") or ""
    except Exception as ex:
        logger.warning(f"client_view: could not fetch producer info: {ex}")

    draft_answers = arq.get("draft_answers") or {}
    if isinstance(draft_answers, str):
        import json as _json
        try:
            draft_answers = _json.loads(draft_answers)
        except Exception:
            draft_answers = {}

    questions_for_client = [
        {
            "field_name":    q["field_name"],
            "question":      q["question"],
            "hint":          q.get("hint", ""),
            "forms":         q.get("forms", ""),
            "field_type":    q.get("field_type", "text"),
            "current_value": "",
        }
        for q in arq.get("questions", [])
    ]

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
    check_arq_public_rate_limit(client_ip)

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

    sanitized = {
        _sanitize_str(k, 128): _sanitize_str(str(v), 500)
        for k, v in raw_answers.items()
    }

    await save_arq_draft(token, sanitized)
    return JSONResponse({"success": True})


@router.post("/submit/{token}")
async def submit_arq(token: str, request: Request):
    client_ip = get_client_ip(request)
    check_arq_submit_rate_limit(client_ip)

    if not token or len(token) > 128:
        return JSONResponse({"success": False, "message": "Invalid token."}, status_code=400)

    body        = await request.json()
    raw_answers = body.get("answers", {})

    if not isinstance(raw_answers, dict) or not raw_answers:
        return JSONResponse({"success": False, "message": "No answers provided."}, status_code=400)
    if len(raw_answers) > 500:
        return JSONResponse({"success": False, "message": "Too many fields in submission."}, status_code=400)

    sanitized_answers = {
        _sanitize_str(k, 128): _sanitize_str(str(v), 500)
        for k, v in raw_answers.items()
    }

    arq = await get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "message": "Questionnaire not found."}, status_code=404)

    ok, msg, updated_fields = await submit_arq_answers(
        token=token,
        raw_answers=sanitized_answers,
        processing_session_id=arq["session_id"],
        generated_forms={},
    )

    if not ok:
        return JSONResponse({"success": False, "message": msg}, status_code=400)

    apply_ok, applied_fields = await apply_arq_answers_to_session(
        arq_id=arq["id"],
        processing_session_id=arq["session_id"],
    )

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

    return JSONResponse({
        "success":        True,
        "message":        "Answers submitted successfully.",
        "fields_updated": len(applied_fields),
    })


@router.post("/chat/{token}")
async def arq_chat(token: str, request: Request):
    from config.settings import groq_chat

    client_ip = get_client_ip(request)
    check_arq_chat_rate_limit(client_ip)

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

    if not message:
        return JSONResponse({"success": False, "reply": "No message provided."}, status_code=400)

    history = [h for h in history[-6:] if h.get("role") in ("user", "assistant") and h.get("content")]

    questions      = arq.get("questions", [])
    question_list  = [f"{i}. {q.get('question','')} (Field: {q.get('field_name','')})" for i, q in enumerate(questions, 1)]
    questions_ctx  = "\n".join(question_list) if question_list else "No specific questions available."

    system_prompt = f"""You are a helpful form assistant helping a business owner complete an insurance application questionnaire.

IMPORTANT RULES:
1. ONLY answer questions related to the specific questions listed below
2. If asked about something NOT in the list, say: "I'm sorry, I can only help with questions from this insurance form."
3. Explain insurance terms in simple, plain English
4. Be helpful but concise (2-4 sentences maximum)
5. NEVER invent information or give legal advice

Here are the EXACT questions from this insurance form:

{questions_ctx}"""

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": h["role"], "content": _sanitize_str(h.get("content", ""), 500)})
    messages.append({"role": "user", "content": message})

    fallback = "I'm sorry, I can only help with questions about this insurance form. Please contact your agent for assistance."

    try:
        reply = await groq_chat(
            "llama-3.1-8b-instant",
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
    })


@router.get("/list/{session_id}")
async def list_arqs(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, email, client_name, created_at, submitted_at, expires_at, reminder_count "
            "FROM arq_sessions WHERE session_id=$1 AND user_id=$2 ORDER BY created_at DESC",
            session_id, current_user["id"],
        )
    return JSONResponse({"success": True, "arq_sessions": [dict(r) for r in rows]})


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
    if arq["status"] == "submitted":
        raise HTTPException(400, "Client has already submitted this questionnaire")

    ok = await send_arq_reminder(arq_id, current_user)
    return JSONResponse({"success": ok, "message": "Reminder sent." if ok else "Failed to send reminder."})


@router.get("/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    notifs = await get_arq_notifications(current_user["id"])
    return JSONResponse({"success": True, "notifications": notifs})


@router.post("/notifications/read")
async def mark_read(current_user: dict = Depends(get_current_user)):
    await mark_notifications_read(current_user["id"])
    return JSONResponse({"success": True})


@router.get("/client-filled/{session_id}")
async def get_client_filled(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    fields = await get_client_filled_fields(session_id)
    return JSONResponse({"success": True, "client_filled_fields": fields})
