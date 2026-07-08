import logging
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services.auth_service import get_current_user
from utils.helpers import check_payment_access
from utils.rate_limiter import check_assistant_chat_rate_limit

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)

_FALLBACK = "Sorry, I couldn't process that just now. Please try again in a moment."

_SYSTEM_PROMPT = (
    "You are Primble Assistant, a friendly in-app guide for insurance brokers and "
    "agents using Primble - a platform that automates ACORD insurance form filling "
    "by extracting data from uploaded policy documents and preparing "
    "underwriting-ready forms.\n\n"
    "RULES:\n"
    "1. Help with using Primble (uploading document packages, checking submission "
    "quality / SQS scores, resolving findings, generating and downloading ACORD "
    "forms) and with general insurance-submission terminology.\n"
    "2. Explain insurance terms in plain, simple English.\n"
    "3. Be concise and friendly (2-5 sentences).\n"
    "4. Never invent account-specific data, give legal advice, or claim to take "
    "actions you cannot perform.\n"
    "5. If a request is unrelated to insurance or Primble, politely steer back."
)


def _sanitize(text, limit: int = 800) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"<[^>]*>", "", text).strip()[:limit]


@router.post("/chat")
async def assistant_chat(request: Request, current_user: dict = Depends(get_current_user)):
    """Authenticated in-app assistant chat. Mirrors the public ARQ chat pattern
    (arq_routes.arq_chat) but is scoped to the logged-in dashboard user."""
    from config.settings import groq_chat, LLM_MODEL

    check_payment_access(current_user.get("payment_status", "ok"), "form")
    await check_assistant_chat_rate_limit(str(current_user["id"]))

    body    = await request.json()
    message = _sanitize(body.get("message", ""), 800)
    history = body.get("history", [])

    if not message:
        return JSONResponse({"success": False, "reply": "No message provided."}, status_code=400)

    history = [
        h for h in (history or [])[-6:]
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content")
    ]

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for h in history:
        messages.append({"role": h["role"], "content": _sanitize(h.get("content", ""), 800)})
    messages.append({"role": "user", "content": message})

    try:
        reply = await groq_chat(
            LLM_MODEL,
            messages,
            temperature=0.4,
            max_tokens=400,
        )
        reply = (reply or "").strip() or _FALLBACK
        return JSONResponse({"success": True, "reply": reply})
    except Exception as ex:
        logger.error(f"Assistant chat failed: {ex}")
        return JSONResponse({"success": True, "reply": _FALLBACK})
