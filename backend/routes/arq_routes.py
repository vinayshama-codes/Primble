import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config.database import get_db
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
    send_arq_reminder,
    submit_arq_answers,
)
from services.auth_service import get_current_user
from services.email_service import (
    send_arq_email,
    send_arq_submitted_notification,
)
from config.settings import FRONTEND_URL

router = APIRouter(prefix="/api/arq", tags=["arq"])
logger = logging.getLogger(__name__)


@router.get("/generate/{session_id}")
async def generate_questions(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Generate ARQ questions from a processing session's missing fields."""
    from fastapi import HTTPException
    try:
        proc_session = get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")

    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")

    generated = proc_session.get("generated_forms", {})
    if not generated:
        raise HTTPException(400, "No forms generated yet — generate forms first")
    
    for fid, fd in generated.items():
        conf = fd.get("confidence", {})
        logger.info(f"DEBUG ARQ Form {fid}: confidence sample = {dict(list(conf.items())[:5])}")
        field_state = fd.get("field_state") or fd.get("mapped", {})
        logger.info(f"DEBUG ARQ Form {fid}: field_state sample = {dict(list(field_state.items())[:5])}")

    questions = generate_arq_questions(
        facts=proc_session.get("facts", {}),
        flags=proc_session.get("flags", {}),
        generated_forms=generated,
        hard_stops=proc_session.get("hard_stops", []),
        soft_stops=proc_session.get("soft_stops", []),
    )

    # Auto-fill producer info for the send modal
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
    """Create ARQ session and send email to client."""
    from fastapi import HTTPException
    body = await request.json()

    session_id  = body.get("session_id", "").strip()
    client_email = body.get("client_email", "").strip()
    client_name  = body.get("client_name", "").strip()
    questions    = body.get("questions", [])

    if not session_id:
        raise HTTPException(400, "session_id is required")
    if not client_email:
        raise HTTPException(400, "client_email is required")
    if not questions:
        raise HTTPException(400, "At least one question is required")

    import re
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", client_email):
        raise HTTPException(400, "Invalid client email address")

    # Verify session ownership
    try:
        proc_session = get_processing_session(session_id)
    except Exception:
        raise HTTPException(404, "Processing session not found")

    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")

    # Strip any pre-filled answers from questions (only question metadata is stored)
    clean_questions = []
    for q in questions:
        clean_questions.append({
            "field_name":    q.get("field_name", ""),
            "question":      q.get("question", ""),
            "forms":         q.get("forms", ""),
            "form_ids":      q.get("form_ids", []),
            "field_type":    q.get("field_type", "text"),
            "current_value": q.get("current_value", ""),
        })

    arq_data = create_arq_session(
        processing_session_id=session_id,
        user_id=current_user["id"],
        client_email=client_email,
        client_name=client_name,
        questions=clean_questions,
    )

    arq_link     = f"{FRONTEND_URL}/questionnaire/{arq_data['token']}"
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
async def client_view(token: str):
    """Public endpoint: return questionnaire data for client."""
    arq = get_arq_by_token(token)
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

    # Mark as viewed
    mark_arq_viewed(token)

    # Return only what client needs — no internal IDs except token
    questions_for_client = []
    for q in arq.get("questions", []):
        questions_for_client.append({
            "field_name":  q["field_name"],
            "question":    q["question"],
            "forms":       q.get("forms", ""),
            "field_type":  q.get("field_type", "text"),
            "current_value": "",  # Never pre-fill for client
        })

    return JSONResponse({
        "success":     True,
        "client_name": arq.get("client_name", ""),
        "questions":   questions_for_client,
        "expires_at":  arq["expires_at"],
    })


@router.post("/submit/{token}")
async def submit_arq(token: str, request: Request):
    """Public endpoint: client submits answers."""
    body = await request.json()
    raw_answers = body.get("answers", {})

    if not isinstance(raw_answers, dict) or not raw_answers:
        return JSONResponse({"success": False, "message": "No answers provided."}, status_code=400)

    arq = get_arq_by_token(token)
    if not arq:
        return JSONResponse({"success": False, "message": "Questionnaire not found."}, status_code=404)

    ok, msg, updated_fields = submit_arq_answers(
        token=token,
        raw_answers=raw_answers,
        processing_session_id=arq["session_id"],
        generated_forms={},  # not needed at submit stage
    )

    if not ok:
        return JSONResponse({"success": False, "message": msg}, status_code=400)

    # Apply answers to session forms
    apply_ok, applied_fields = apply_arq_answers_to_session(
        arq_id=arq["id"],
        processing_session_id=arq["session_id"],
    )

    # Create notification for producer
    create_arq_notification(arq["id"], arq["user_id"], "submitted")

    # Send notification email to producer
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT email, full_name FROM users WHERE id=%s", (arq["user_id"],))
        row = cur.fetchone()
        cur.close()
        conn.close()
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


@router.get("/status/{arq_id}")
async def get_arq_status(
    arq_id: str,
    current_user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException
    arq = get_arq_by_id(arq_id)
    if not arq:
        raise HTTPException(404, "ARQ session not found")
    if arq["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")

    return JSONResponse({
        "success":      True,
        "arq_id":       arq["id"],
        "status":       arq["status"],
        "client_email": arq["email"],
        "client_name":  arq.get("client_name", ""),
        "created_at":   arq["created_at"],
        "submitted_at": arq.get("submitted_at"),
        "viewed_at":    arq.get("viewed_at"),
        "expires_at":   arq["expires_at"],
        "reminder_count": arq.get("reminder_count", 0),
        "fields_answered": len(arq.get("answers", {})),
        "total_questions": len(arq.get("questions", [])),
    })


@router.get("/list/{session_id}")
async def list_arqs(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """List all ARQ sessions for a processing session."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, status, email, client_name, created_at, submitted_at, expires_at, reminder_count FROM arq_sessions WHERE session_id=%s AND user_id=%s ORDER BY created_at DESC",
        (session_id, current_user["id"]),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return JSONResponse({"success": True, "arq_sessions": rows})


@router.post("/remind/{arq_id}")
async def send_reminder(
    arq_id: str,
    current_user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException
    arq = get_arq_by_id(arq_id)
    if not arq:
        raise HTTPException(404, "ARQ session not found")
    if arq["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")
    if arq["status"] == "submitted":
        raise HTTPException(400, "Client has already submitted this questionnaire")

    ok = send_arq_reminder(arq_id, current_user)
    return JSONResponse({"success": ok, "message": "Reminder sent." if ok else "Failed to send reminder."})


@router.get("/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    notifs = get_arq_notifications(current_user["id"])
    return JSONResponse({"success": True, "notifications": notifs})


@router.post("/notifications/read")
async def mark_read(current_user: dict = Depends(get_current_user)):
    mark_notifications_read(current_user["id"])
    return JSONResponse({"success": True})


@router.get("/client-filled/{session_id}")
async def get_client_filled(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return field names filled by client via ARQ for editor highlighting."""
    fields = get_client_filled_fields(session_id)
    return JSONResponse({"success": True, "client_filled_fields": fields})