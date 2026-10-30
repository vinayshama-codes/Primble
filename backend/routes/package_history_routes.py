"""V2 package records (27 Oct 2026): a fact's lineage, archive / unarchive, and
the Form Assistant's usage. Thin routes - the rules live in
`services/fact_history.py`, `services/package_archive.py` and
`services/arq_assistant_usage.py`."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from repositories.session_repository import get_processing_session
from services.auth_service import get_current_user
from utils.helpers import check_payment_access

router = APIRouter(tags=["package-records"])
logger = logging.getLogger(__name__)

_FACT_KEY_RE = re.compile(r"^[A-Za-z0-9_.:@\-]{1,120}$")


async def _owned_session(session_id: str, current_user: dict) -> dict:
    session = await get_processing_session(session_id)          # 404 when missing
    if str(session.get("user_id") or "") != str(current_user.get("id")):
        raise HTTPException(403, "Access denied")
    return session


@router.get("/api/fact-history/{session_id}")
async def get_fact_history(
    session_id: str,
    fact_key: str = Query(None, max_length=120),
    limit: int = Query(500, ge=1, le=5000),
    current_user: dict = Depends(get_current_user),
):
    """Every recorded change of one fact (or of the whole package) - oldest
    first, values decrypted for the owner, who / how / when on each row."""
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    await _owned_session(session_id, current_user)
    key = (fact_key or "").strip() or None
    if key and not _FACT_KEY_RE.match(key):
        raise HTTPException(400, "Unknown fact.")
    from services.fact_history import fact_history, actor_ids_in, who
    rows = await fact_history(session_id, key, limit=limit)
    actors = {}
    try:
        from services.audit_service import resolve_actors
        actors = await resolve_actors(actor_ids_in(rows))
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("fact history: actors unresolved for %s: %s", session_id, ex)
    for r in rows:
        r["who"] = who(r, actors)
    return JSONResponse({"success": True, "session_id": session_id,
                         "fact_key": key, "history": rows, "count": len(rows)})


@router.post("/api/sessions/{session_id}/archive")
async def archive_session(session_id: str, current_user: dict = Depends(get_current_user)):
    """Archive the package: it leaves the main dashboard list and is read-only
    until it is unarchived."""
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    from services.package_archive import archive_package
    result = await archive_package(session_id, str(current_user["id"]))
    return JSONResponse({"success": True, "session_id": session_id, **result})


@router.post("/api/sessions/{session_id}/unarchive")
async def unarchive_session(session_id: str, current_user: dict = Depends(get_current_user)):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    from services.package_archive import unarchive_package
    result = await unarchive_package(session_id, str(current_user["id"]))
    return JSONResponse({"success": True, "session_id": session_id, **result})


@router.get("/api/sessions/{session_id}/assistant-usage")
async def session_assistant_usage(session_id: str, current_user: dict = Depends(get_current_user)):
    """How often the client used the Form Assistant on this package's
    questionnaires (counts only - never what they typed)."""
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    await _owned_session(session_id, current_user)
    from services.arq_assistant_usage import package_usage
    return JSONResponse({"success": True, "session_id": session_id,
                         "assistant_usage": await package_usage(session_id)})


async def _admin(current_user: dict = Depends(get_current_user)) -> dict:
    from routes.admin_routes import _require_admin
    return await _require_admin(current_user)


@router.get("/api/admin/arq-assistant-usage")
async def admin_assistant_usage(
    days: int = Query(30, ge=1, le=3650),
    top: int = Query(10, ge=1, le=50),
    _: dict = Depends(_admin),
):
    """Form Assistant usage across every account (admin only)."""
    from services.arq_assistant_usage import admin_summary
    return JSONResponse({"success": True, **(await admin_summary(days=days, top=top))})
