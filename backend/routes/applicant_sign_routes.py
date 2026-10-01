"""The applicant signs the generated forms as a question in the client
questionnaire (Orbin item 14, 1 Oct 2026). services/applicant_signing.py holds
the rules; this file is the HTTP edge.

Producer (signed in): where each form's applicant signature stands.
Client (the signing token the questionnaire carries, no sign-in): sign once -
the question asks only for the signature (owner, 1 Oct night). The signature is recorded
on the forms when the questionnaire is submitted (arq_routes.submit).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from repositories.session_repository import get_processing_session
from services import applicant_signing as asg
from services.auth_service import get_current_user
from utils.rate_limiter import check_arq_submit_rate_limit, get_client_ip

router = APIRouter(prefix="/api/applicant-sign", tags=["applicant-sign"])
logger = logging.getLogger(__name__)

def _refusal(err: "asg.SigningError") -> JSONResponse:
    return JSONResponse({"success": False, "error": err.code, "message": err.message},
                        status_code=err.status)


async def _owned_session(session_id: str, current_user: dict) -> dict:
    sess = await get_processing_session(session_id)
    if str(sess.get("user_id")) != str(current_user["id"]):
        raise HTTPException(403, "Access denied")
    return sess


# ── Producer ──────────────────────────────────────────────────────────────────

@router.get("/{session_id}/status")
async def signature_status(session_id: str, current_user: dict = Depends(get_current_user)):
    sess = await _owned_session(session_id, current_user)
    requests = await asg.requests_for_session(session_id, str(current_user["id"]))
    for r in requests:
        r.pop("token", None)                 # the client's key, never the producer's to see
    return JSONResponse({"success": True, "forms": asg.form_statuses(sess), "requests": requests})


# ── Client (token) ────────────────────────────────────────────────────────────

@router.post("/sign/{token}")
async def sign_forms(token: str, request: Request):
    ip = get_client_ip(request)
    await check_arq_submit_rate_limit(ip)
    if not asg.valid_token(token):
        return _refusal(asg.SigningError("not_found", "This signature link was not found.", 404))
    raw = await request.body()
    if len(raw) > asg.MAX_BODY_BYTES:
        return _refusal(asg.SigningError("image", "That picture is too large. Use one under 2 MB.", 413))
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _refusal(asg.SigningError("bad_request", "Something went wrong. Please try again.", 400))
    try:
        done = await asg.sign(token, body.get("signer_name"), body.get("consent"), body.get("signature_data"),
                              body.get("versions"), body.get("tz_offset_minutes"), ip,
                              request.headers.get("user-agent", ""))
    except asg.SigningError as err:
        return _refusal(err)

    labels = [asg.form_label(f) for f in done["forms"]]
    return JSONResponse({"success": True, "forms": labels})
