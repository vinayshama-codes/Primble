import asyncio
import hashlib
import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from config.database import get_pool
from config.settings import TEMPLATE_DIR
from models.schemas import SaveSignatureRequest
from repositories.session_repository import get_processing_session, upd_processing_session
from services.auth_service import get_current_user
from services.pdf_service import _is_signature_field, inject_signature_into_pdf
from utils.crypto import decrypt_field, encrypt_field
from utils.helpers import safe_join, check_payment_access

router = APIRouter(tags=["signature"])
logger = logging.getLogger(__name__)


@router.post("/api/auth/save-signature")
async def save_signature(
    req: SaveSignatureRequest,
    current_user: dict = Depends(get_current_user),
):
    sig = req.signature_data
    if sig is not None and not isinstance(sig, str):
        raise HTTPException(400, "signature_data must be a base64 string or null")
    if sig is not None and len(sig) > 5_000_000:
        raise HTTPException(400, "Signature image too large (max ~5 MB)")

    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET signature_data = $1 WHERE id = $2",
            encrypt_field(sig), current_user["id"],
        )

    action = "cleared" if sig is None else "saved"
    logger.info(f"Signature {action}: user={current_user['id']}")
    return {"success": True, "action": action}


@router.get("/api/auth/get-signature")
async def get_signature(current_user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT signature_data FROM users WHERE id = $1",
            current_user["id"],
        )
    sig = dict(row).get("signature_data") if row else None
    try:
        decrypted = decrypt_field(sig)
    except Exception:
        decrypted = None
    return {"success": True, "signature_data": decrypted}


@router.post("/api/apply-signature/{session_id}/{form_id}")
async def apply_signature(
    session_id: str,
    form_id: str,
    current_user: dict = Depends(get_current_user),
):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT signature_data FROM users WHERE id = $1",
            current_user["id"],
        )

    if not row:
        raise HTTPException(404, "User not found")

    sig = decrypt_field(dict(row).get("signature_data"))
    if not sig:
        raise HTTPException(400, "No signature saved. Please set up your signature first.")

    proc_session = await get_processing_session(session_id, include_pdf=True)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})

    if form_id not in generated:
        raise HTTPException(404, f"Form '{form_id}' not found in session")

    r   = generated[form_id]
    try:
        tpl = safe_join(TEMPLATE_DIR, r["form"]["template_file"])
    except ValueError:
        raise HTTPException(400, "Invalid template path")

    if not os.path.exists(tpl):
        raise HTTPException(404, f"Template not found: {r['form']['template_file']}")

    field_data = dict(r.get("field_state") or r.get("mapped", {}))
    confidence = dict(r.get("confidence", {}))

    for field_name in list(field_data.keys()):
        if _is_signature_field(field_name):
            field_data[field_name] = ""
            confidence[field_name] = "filled"

    # Use the already-filled PDF bytes so values are never lost on re-generation
    existing_bytes = r.get("pdf_bytes")
    if existing_bytes is not None and not isinstance(existing_bytes, bytes):
        existing_bytes = bytes(existing_bytes)

    try:
        signed_pdf = await asyncio.get_event_loop().run_in_executor(
            None, inject_signature_into_pdf, tpl, field_data, confidence, sig, existing_bytes
        )
    except Exception as ex:
        logger.error(f"apply-signature error form={form_id}: {ex}", exc_info=True)
        raise HTTPException(500, "Signature processing failed. Please try again.")

    if not signed_pdf or len(signed_pdf) == 0:
        raise HTTPException(500, "Signature injection produced an empty PDF")

    state_hash = hashlib.md5(signed_pdf).hexdigest()

    generated[form_id]["field_state"]       = field_data
    generated[form_id]["confidence"]        = confidence
    generated[form_id]["pdf_bytes"]         = signed_pdf
    generated[form_id]["_pdf_cache_hash"]   = state_hash
    generated[form_id]["signature_applied"] = True
    generated[form_id]["signature_b64"]     = sig

    await upd_processing_session(session_id, {"generated_forms": generated})

    return {"success": True, "form_id": form_id, "message": "Signature applied successfully"}
