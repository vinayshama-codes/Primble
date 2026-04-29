
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from config.database import get_db
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user
from services.email_service import _send_payment_failed_email
from services.scheduler_service import run_daily_payment_lifecycle

router = APIRouter(tags=["dev"])
logger = logging.getLogger(__name__)

_ADMIN_EMAILS: set = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}


def _require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("email", "").lower() not in _ADMIN_EMAILS:
        raise HTTPException(403, "Admin access required")
    return current_user


@router.post("/api/acord/confirm-license")
async def confirm_acord_license(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE users SET acord_license_confirmed=1, acord_license_confirmed_at=%s WHERE id=%s",
        (now, current_user["id"]),
    )
    conn.commit()
    cur.close()
    conn.close()

    write_audit_log(
        user={**current_user, "acord_license_confirmed": 1},
        action="license_confirmed",
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "acord_license_confirmed": True}


@router.get("/api/acord/audit-log")
async def get_audit_log(
    current_user: dict = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0,
):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM acord_audit_log WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s OFFSET %s",
        (current_user["id"], limit, offset),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"success": True, "entries": rows, "count": len(rows)}


@router.post("/api/billing/payment-lifecycle")
async def run_payment_lifecycle(_: dict = Depends(_require_admin)):
    await run_daily_payment_lifecycle()
    return {
        "processed":   True,
        "checked_at":  datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/dev/test-email")
async def test_email(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    body = await request.json()
    to   = body.get("email", "")
    day  = int(body.get("day", 1))

    if not to:
        raise HTTPException(400, "email required")

    sent = _send_payment_failed_email(to, "Test User", day=day)
    logger.info(
        f"Test email day={day} to {to}: "
        f"{'sent' if sent else 'FAILED'} "
        f"(triggered by {current_user['email']})"
    )
    return {"sent": sent, "to": to, "day": day}


@router.post("/api/dev/simulate-payment-failure")
async def simulate_payment_failure(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    body     = await request.json()
    days_ago = int(body.get("days_ago", 0))
    fake_dt  = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    if days_ago >= 21:
        final_status = "suspended"
    elif days_ago >= 10:
        final_status = "soft_locked"
    else:
        final_status = "failed"

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE users SET payment_status=%s, payment_failed_at=%s WHERE id=%s",
        (final_status, fake_dt, current_user["id"]),
    )
    conn.commit()
    cur.close()
    conn.close()

    logger.info(
        f"DEV: simulated payment failure {days_ago} days ago "
        f"→ {final_status} for user={current_user['id']}"
    )

    email_day = (
        21 if days_ago >= 21
        else 10 if days_ago >= 10
        else 7  if days_ago >= 7
        else 1
    )
    sent = _send_payment_failed_email(
        current_user["email"],
        current_user.get("full_name", ""),
        day=email_day,
    )
    logger.info(
        f"DEV simulate: sent day={email_day} email "
        f"to {current_user['email']}: {'✅' if sent else '❌'}"
    )

    return {
        "success":          True,
        "payment_failed_at": fake_dt,
        "days_ago":         days_ago,
        "status_set":       final_status,
        "email_sent":       sent,
        "email_day":        email_day,
    }


@router.post("/api/stripe/reconcile-overage")
async def reconcile_overage(current_user: dict = Depends(get_current_user)):
    from config.settings import SOFT_BUFFER_PCT
    from services.stripe_service import create_overage_invoice_item

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(404, "User not found")

    user = dict(row)
    sub  = user.get("subscription_tier", "free") or "free"

    if sub not in ("essentials", "professional"):
        raise HTTPException(400, "Reconciliation only applies to paid plans")

    pkgs_used          = int(user.get("packages_used", 0) or 0)
    pkgs_limit         = int(user.get("packages_limit", 0) or 0)
    already_invoiced   = int(user.get("overage_packages_invoiced", 0) or 0)
    overage_rate_cents = int(user.get("overage_rate") or (150 if sub == "essentials" else 125))
    soft_buffer        = int(pkgs_limit * SOFT_BUFFER_PCT)

    billable_overages = max(0, pkgs_used - pkgs_limit - soft_buffer)
    uninvoiced        = max(0, billable_overages - already_invoiced)

    if uninvoiced == 0:
        return {
            "success": True,
            "message": "No uninvoiced overages found.",
            "uninvoiced": 0,
        }

    queued = 0
    failed = 0
    for _ in range(uninvoiced):
        ok = create_overage_invoice_item(user, overage_rate_cents)
        if ok:
            queued += 1
        else:
            failed += 1

    if queued > 0:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE users SET overage_packages_invoiced = overage_packages_invoiced + %s WHERE id = %s",
            (queued, current_user["id"]),
        )
        conn.commit()
        cur.close()
        conn.close()

    logger.info(
        f"Reconcile overage: user={current_user['id']} "
        f"uninvoiced={uninvoiced} queued={queued} failed={failed}"
    )

    return {
        "success":          True,
        "packages_used":    pkgs_used,
        "packages_limit":   pkgs_limit,
        "soft_buffer":      soft_buffer,
        "billable_overages": billable_overages,
        "already_invoiced": already_invoiced,
        "newly_queued":     queued,
        "failed":           failed,
        "message": (
            f"Queued {queued} overage invoice item(s) to Stripe."
            if queued else "All overages already invoiced."
        ),
    }


@router.post("/api/count-download")
async def count_download(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT subscription_tier, downloads_used FROM users WHERE id = %s",
        (current_user["id"],),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(404, "User not found")

    row  = dict(row)
    sub  = row.get("subscription_tier", "free") or "free"
    used = int(row.get("downloads_used", 0) or 0)

    if sub == "free" and used >= 3:
        cur.close()
        conn.close()
        return {"success": False, "upgrade_required": True}

    if sub == "free":
        cur.execute(
            "UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s",
            (current_user["id"],),
        )
        conn.commit()

    cur.close()
    conn.close()
    return {"success": True}