import csv
import io
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from config.database import get_pool
from config.settings import TEMPLATE_DIR, FORMS_INDEX
from repositories.audit_repository import write_audit_log
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


async def _require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Admin gate. An email is an admin if it's in the ADMIN_EMAILS env var
    (a permanent bootstrap/failsafe list — always required to be non-empty in
    production, see settings.validate_production_config) OR in the admin_users
    table (DB-editable via /api/admin/admins, no redeploy needed)."""
    email = current_user.get("email", "").lower()
    if email in _ADMIN_EMAILS:
        return current_user
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM admin_users WHERE email=$1", email)
    if row:
        return current_user
    raise HTTPException(403, "Admin access required")


@router.get("/dlq-inspect")
def dlq_inspect(
    limit: int = 10,
    _: dict = Depends(_require_admin),
):
    """Peek at failed jobs sitting in the dead-letter queue.

    Returns up to `limit` messages. Messages are NOT consumed — they remain in the DLQ.
    """
    from services.job_queue import get_job_queue
    queue = get_job_queue()
    if not hasattr(queue, "inspect_dlq"):
        return JSONResponse(
            status_code=200,
            content={"messages": [], "note": "DLQ inspection is only available for the SQS backend"},
        )
    messages = queue.inspect_dlq(max_messages=min(limit, 10))
    return JSONResponse({"messages": messages, "count": len(messages)})


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


# ── ACORD license confirmation: admin reset + audit export ────────────────────

_LICENSE_AUDIT_ACTIONS = ("license_confirmed", "license_reset")


@router.get("/status")
async def admin_status(admin: dict = Depends(_require_admin)):
    """Lightweight probe the frontend calls to decide whether to show admin UI.

    Returns 200 with is_admin=True for callers in ADMIN_EMAILS; the shared
    _require_admin dependency returns 403 for everyone else, so a non-200
    response tells the client to hide all admin controls.
    """
    return {"is_admin": True, "email": admin.get("email")}


@router.post("/reset-license")
async def reset_license_confirmation(
    request: Request,
    admin: dict = Depends(_require_admin),
):
    """Clear a user's ACORD license confirmation so they are prompted to
    re-accept on their next download. Admin-only.

    Body: { "email": "user@example.com" }

    Records a `license_reset` row in the audit log against the target user, and
    logs the acting admin. Idempotent — resetting an already-unconfirmed user
    simply re-writes the reset record.
    """
    body = await request.json()
    target_email = (body.get("email") or "").strip().lower()
    if not target_email:
        raise HTTPException(400, "email is required")

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, organization_name FROM users WHERE lower(email) = $1",
            target_email,
        )
        if not row:
            raise HTTPException(404, f"No user found with email {target_email}")
        target = dict(row)
        await conn.execute(
            "UPDATE users SET acord_license_confirmed=0, acord_license_confirmed_at=NULL, "
            "acord_license_version=NULL WHERE id=$1",
            target["id"],
        )

    await write_audit_log(
        user={**target, "acord_license_confirmed": 0},
        action="license_reset",
        ip_address=request.client.host if request.client else None,
        actor_email=admin.get("email"),
    )
    logger.info(
        "admin %s reset ACORD license confirmation for user %s",
        admin.get("email"), target_email,
    )
    return {
        "success": True,
        "email": target["email"],
        "acord_license_confirmed": False,
    }


@router.get("/license-audit-export")
async def license_audit_export(
    admin: dict = Depends(_require_admin),
    export_format: str = Query("csv", alias="format"),
    organization: str = Query(None),
    since: str = Query(None, description="ISO UTC timestamp lower bound (inclusive)"),
    until: str = Query(None, description="ISO UTC timestamp upper bound (inclusive)"),
    limit: int = Query(10000),
):
    """Export ACORD license confirmation / reset events for compliance.

    Admin-only. Returns every `license_confirmed` and `license_reset` audit row,
    newest first, as CSV (default) or JSON. Optional filters: organization
    (case-insensitive substring), since / until (ISO UTC timestamps).
    """
    if export_format not in ("csv", "json"):
        raise HTTPException(400, "format must be 'csv' or 'json'")
    limit = max(1, min(int(limit), 100000))

    clauses = ["action = ANY($1::text[])"]
    params: list = [list(_LICENSE_AUDIT_ACTIONS)]
    if organization:
        params.append(f"%{organization.lower()}%")
        clauses.append(f"lower(organization_name) LIKE ${len(params)}")
    if since:
        params.append(since)
        clauses.append(f"timestamp >= ${len(params)}")
    if until:
        params.append(until)
        clauses.append(f"timestamp <= ${len(params)}")
    params.append(limit)

    query = (
        "SELECT timestamp, user_email, organization_name, action, "
        "acord_license_confirmed, license_version, actor_email, ip_address "
        f"FROM acord_audit_log WHERE {' AND '.join(clauses)} "
        f"ORDER BY timestamp DESC LIMIT ${len(params)}"
    )
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *params)

    records = [dict(r) for r in rows]
    logger.info(
        "admin %s exported %d ACORD license audit rows",
        admin.get("email"), len(records),
    )

    columns = [
        "timestamp", "user_email", "organization_name",
        "action", "acord_license_confirmed", "license_version", "actor_email", "ip_address",
    ]

    if export_format == "json":
        return JSONResponse({"count": len(records), "records": records})

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in records:
        writer.writerow([r.get(col, "") for col in columns])

    filename = (
        "acord_license_audit_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Admin user management (DB-editable admin list) ─────────────────────────────
# ADMIN_EMAILS (env var) remains a permanent bootstrap/failsafe list — it's
# required to be non-empty in production (see settings.validate_production_config),
# so there is always at least one admin even if the admin_users table is empty
# or the database is unreachable. Admins added here are DB rows and can be
# granted/revoked without a redeploy.

@router.get("/admins")
async def list_admins(admin: dict = Depends(_require_admin)):
    """List all current admins: permanent env-var admins (not removable here)
    plus database-granted admins (removable via DELETE /api/admin/admins)."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT email, added_by, created_at FROM admin_users ORDER BY created_at ASC"
        )
    db_admins = [
        {"email": r["email"], "source": "database", "added_by": r["added_by"], "created_at": r["created_at"]}
        for r in rows
    ]
    env_admins = [
        {"email": e, "source": "env", "added_by": None, "created_at": None}
        for e in sorted(_ADMIN_EMAILS)
    ]
    return {"admins": env_admins + db_admins}


@router.post("/admins")
async def add_admin(request: Request, admin: dict = Depends(_require_admin)):
    """Grant admin access to an email via the database. Body: { "email": "..." }"""
    body = await request.json()
    target_email = (body.get("email") or "").strip().lower()
    if not target_email:
        raise HTTPException(400, "email is required")
    if target_email in _ADMIN_EMAILS:
        return {"success": True, "email": target_email, "note": "Already an admin via ADMIN_EMAILS."}

    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO admin_users (email, added_by, created_at) VALUES ($1,$2,$3) "
            "ON CONFLICT (email) DO NOTHING",
            target_email, admin.get("email"), now,
        )
    await write_audit_log(
        user={"id": None, "email": target_email, "organization_name": ""},
        action="admin_added",
        actor_email=admin.get("email"),
        ip_address=request.client.host if request.client else None,
    )
    logger.info("admin %s granted admin access to %s", admin.get("email"), target_email)
    return {"success": True, "email": target_email}


@router.delete("/admins")
async def remove_admin(
    request: Request,
    email: str = Query(...),
    admin: dict = Depends(_require_admin),
):
    """Revoke a database-granted admin's access. Admins set via the
    ADMIN_EMAILS env var cannot be removed here (they aren't DB rows) —
    edit the env var and redeploy instead."""
    target_email = email.strip().lower()
    if target_email in _ADMIN_EMAILS:
        raise HTTPException(
            400,
            f"{target_email} is an admin via the ADMIN_EMAILS env var, not the database. "
            "Remove it from ADMIN_EMAILS and redeploy instead.",
        )
    async with get_pool().acquire() as conn:
        status = await conn.execute("DELETE FROM admin_users WHERE email=$1", target_email)
    deleted = bool(status) and status.split()[-1] != "0"
    if not deleted:
        raise HTTPException(404, f"{target_email} is not a database-granted admin.")

    await write_audit_log(
        user={"id": None, "email": target_email, "organization_name": ""},
        action="admin_removed",
        actor_email=admin.get("email"),
        ip_address=request.client.host if request.client else None,
    )
    logger.info("admin %s revoked admin access from %s", admin.get("email"), target_email)
    return {"success": True, "email": target_email}
