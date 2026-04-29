import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from config.settings import TEMPLATE_DIR, FORMS_INDEX
from services.auth_service import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_raw_admin_emails = os.getenv("ADMIN_EMAILS", "").strip()
if not _raw_admin_emails:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "ADMIN_EMAILS env var is not set — all admin routes will return 403. "
        "Set ADMIN_EMAILS=you@example.com to grant access."
    )

_ADMIN_EMAILS: set = {
    e.strip().lower()
    for e in _raw_admin_emails.split(",")
    if e.strip()
}


def _require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not _ADMIN_EMAILS or current_user.get("email", "").lower() not in _ADMIN_EMAILS:
        raise HTTPException(403, "Admin access required")
    return current_user


@router.get("/forms-status")
def forms_status(_: dict = Depends(_require_admin)):
    """
    Returns a live snapshot of active vs pending forms derived from
    forms_index.json and the templates/ directory on disk.
    No hardcoded lists — fully data-driven.
    """
    try:
        with open(FORMS_INDEX) as f:
            index = json.load(f)
    except Exception as exc:
        logger.error("forms-status: could not read forms_index.json: %s", exc)
        raise HTTPException(500, "Could not read forms index")

    templates_on_disk: set = set()
    try:
        templates_on_disk = {
            name for name in os.listdir(TEMPLATE_DIR)
            if name.lower().endswith(".pdf")
        }
    except Exception as exc:
        logger.warning("forms-status: could not list templates dir: %s", exc)

    active: list = []
    pending: list = []

    for entry in index.get("forms", []):
        form_id = entry.get("form_id", "")
        if not form_id:
            continue
        template_file = entry.get("template_file", "")
        is_pending = entry.get("template_pending", False)
        has_template_on_disk = bool(template_file and template_file in templates_on_disk)

        if has_template_on_disk and not is_pending:
            active.append(form_id)
        elif template_file and (is_pending or not has_template_on_disk):
            pending.append(form_id)

    return JSONResponse({
        "active_forms":      active,
        "pending_forms":     pending,
        "total_indexed":     len(index.get("forms", [])),
        "templates_on_disk": len(templates_on_disk),
    })
