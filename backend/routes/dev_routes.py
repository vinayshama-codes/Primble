
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from config.database import get_pool
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


# ASYNC-SAFE
@router.get("/api/admin/audit-log")
async def get_audit_log(
    request: Request,
    admin_user: dict = Depends(_require_admin),
    limit: int = 100,
    offset: int = 0,
):
    capped_limit = min(limit, 500)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM acord_audit_log ORDER BY timestamp DESC LIMIT $1 OFFSET $2",
            capped_limit, offset,
        )

    await write_audit_log(
        user=admin_user,
        action="admin.audit_log_accessed",
        ip_address=request.client.host if request.client else None,
        form_name=f"limit={capped_limit} offset={offset}",
    )

    return {"success": True, "entries": [dict(r) for r in rows], "count": len(rows)}


@router.post("/api/billing/payment-lifecycle")
async def run_payment_lifecycle(
    request: Request,
    admin_user: dict = Depends(_require_admin),
):
    await write_audit_log(
        user=admin_user,
        action="admin.run_payment_lifecycle",
        ip_address=request.client.host if request.client else None,
    )
    await run_daily_payment_lifecycle()
    return {
        "processed":  True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/dev/run-lifecycle-local")
async def run_lifecycle_local(request: Request):
    """No-auth lifecycle trigger — only works from localhost, never mounted in production."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Only accessible from localhost")
    await run_daily_payment_lifecycle()
    return {"processed": True, "checked_at": datetime.now(timezone.utc).isoformat()}


@router.post("/api/dev/reset-payment-state-local")
async def reset_payment_state_local(request: Request):
    """No-auth payment-state reset for local testing. Body: {"email": "..."}. Resets every flag that controls email delivery."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Only accessible from localhost")
    body  = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET payment_status='ok', payment_failed_at=NULL,"
            " payment_email_sent_day=0 WHERE email=$1",
            email,
        )
    return {"reset": True, "email": email, "rows": result}


@router.post("/api/dev/test-email")
async def test_email(
    request: Request,
    admin_user: dict = Depends(_require_admin),
):
    body = await request.json()
    to   = body.get("email", "")
    day  = int(body.get("day", 1))

    if not to:
        raise HTTPException(400, "email required")

    await write_audit_log(
        user=admin_user,
        action="admin.test_email",
        ip_address=request.client.host if request.client else None,
        form_name=f"to={to} day={day}",
    )

    sent = _send_payment_failed_email(to, "Test User", day=day)
    logger.info(
        f"Test email day={day} to {to}: "
        f"{'sent' if sent else 'FAILED'} "
        f"(triggered by {admin_user['email']})"
    )
    return {"sent": sent, "to": to, "day": day}


# ASYNC-SAFE
@router.post("/api/dev/simulate-payment-failure")
async def simulate_payment_failure(
    request: Request,
    admin_user: dict = Depends(_require_admin),
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

    body_email = body.get("email", "").strip().lower()

    async with get_pool().acquire() as conn:
        if body_email and body_email != admin_user["email"].lower():
            target = await conn.fetchrow("SELECT id, email, full_name FROM users WHERE email = $1", body_email)
            if not target:
                raise HTTPException(404, f"User not found: {body_email}")
            target_id    = target["id"]
            target_email = target["email"]
            target_name  = target.get("full_name", "")
        else:
            target_id    = admin_user["id"]
            target_email = admin_user["email"]
            target_name  = admin_user.get("full_name", "")

        await conn.execute(
            "UPDATE users SET payment_status=$1, payment_failed_at=$2, payment_email_sent_day=0 WHERE id=$3",
            final_status, fake_dt, target_id,
        )

    await write_audit_log(
        user=admin_user,
        action="admin.simulate_payment_failure",
        ip_address=request.client.host if request.client else None,
        form_name=f"days_ago={days_ago} status_set={final_status} target={target_email}",
    )

    logger.info(
        f"DEV: simulated payment failure {days_ago} days ago "
        f"→ {final_status} for user={target_id} ({target_email})"
    )

    email_day = (
        21 if days_ago >= 21
        else 10 if days_ago >= 10
        else 7  if days_ago >= 7
        else 1
    )
    sent = _send_payment_failed_email(target_email, target_name, day=email_day)
    logger.info(
        f"DEV simulate: sent day={email_day} email "
        f"to {target_email}: {'ok' if sent else 'FAILED'}"
    )

    return {
        "success":           True,
        "target_email":      target_email,
        "payment_failed_at": fake_dt,
        "days_ago":          days_ago,
        "status_set":        final_status,
        "email_sent":        sent,
        "email_day":         email_day,
    }


# ASYNC-SAFE
@router.post("/api/stripe/reconcile-overage")
async def reconcile_overage(current_user: dict = Depends(get_current_user)):
    from config.settings import SOFT_BUFFER_PCT
    from services.stripe_service import create_overage_invoice_item

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", current_user["id"])

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
            "success":   True,
            "message":   "No uninvoiced overages found.",
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
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET overage_packages_invoiced = overage_packages_invoiced + $1 WHERE id = $2",
                queued, current_user["id"],
            )

    logger.info(
        f"Reconcile overage: user={current_user['id']} "
        f"uninvoiced={uninvoiced} queued={queued} failed={failed}"
    )

    return {
        "success":           True,
        "packages_used":     pkgs_used,
        "packages_limit":    pkgs_limit,
        "soft_buffer":       soft_buffer,
        "billable_overages": billable_overages,
        "already_invoiced":  already_invoiced,
        "newly_queued":      queued,
        "failed":            failed,
        "message": (
            f"Queued {queued} overage invoice item(s) to Stripe."
            if queued else "All overages already invoiced."
        ),
    }


# ASYNC-SAFE
@router.post("/api/count-download")
async def count_download(current_user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT subscription_tier, downloads_used FROM users WHERE id = $1",
            current_user["id"],
        )
        if not row:
            raise HTTPException(404, "User not found")

        row  = dict(row)
        sub  = row.get("subscription_tier", "free") or "free"
        used = int(row.get("downloads_used", 0) or 0)

        if sub == "free" and used >= 3:
            return {"success": False, "upgrade_required": True}

        if sub == "free":
            await conn.execute(
                "UPDATE users SET downloads_used = downloads_used + 1 WHERE id = $1",
                current_user["id"],
            )

    return {"success": True}


@router.post("/api/dev/umbrella-probe")
async def umbrella_probe(request: Request):
    """Exercise the §6.5 umbrella adequacy logic directly from a facts/flags blob,
    bypassing upload -> OCR -> LLM extraction. Localhost-only, dev-routes-gated.

    Body:
      {
        "facts":  { "umbrella_limit": "5000000", "gl_each_occurrence": "500000", ... },
        "flags":  { "has_umbrella": true, "has_workers_comp": true, ... },
        "triggered_ids": ["ACORD_125","ACORD_130","ACORD_131"]   // optional
      }

    The umbrella SCORE / STATE / FOLLOW-FORM / WARNINGS are derived from facts+flags
    only (no triggered_ids needed). triggered_ids is passed to the cross-form layer
    so its form-specific inner checks (EL-over-WC, etc.) can also be observed; it
    defaults to a set that drives underlying-coverage presence from the FACTS rather
    than from form selection, so the "no underlying => hard stop" path is visible.
    """
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Only accessible from localhost")

    body  = await request.json()
    facts = body.get("facts") or {}
    flags = body.get("flags") or {}
    if not isinstance(facts, dict) or not isinstance(flags, dict):
        raise HTTPException(400, "facts and flags must be objects")
    triggered_ids = set(body.get("triggered_ids") or ["ACORD_125", "ACORD_130", "ACORD_131"])

    # Lazy imports: sqs_service pulls in the heavy scoring/validation graph.
    from services.sqs_service import (
        _calculate_umbrella_adequacy, _get_umbrella_state, _get_follow_form_status,
        _build_umbrella_warnings, _build_umbrella_review_items,
        _UMB_GL_OCC_MIN, _UMB_GL_AGG_MIN, _UMB_AUTO_CSL_MIN, _UMB_EL_FULL, _UMB_EL_OK,
    )
    from services.cross_form_validator import (
        run_cross_form_validation, split_cross_form_issues,
    )

    score        = _calculate_umbrella_adequacy(facts, flags)   # None when N/A
    state        = _get_umbrella_state(facts, flags)
    follow_form  = _get_follow_form_status(facts)
    warnings     = _build_umbrella_warnings(facts, flags, score)
    review_items = _build_umbrella_review_items(flags, follow_form, score)

    cf_issues          = run_cross_form_validation(facts, flags, triggered_ids)
    cf_hard, cf_soft, cf_adv = split_cross_form_issues(cf_issues)
    umbrella_cf = [i for i in cf_issues if "umbrella" in (i.get("code") or "")]

    return {
        "umbrella_adequacy_score": score,           # None = Not Applicable (excluded from SQS)
        "is_not_applicable":       score is None,
        "umbrella_state":          state,
        "follow_form":             follow_form,
        "umbrella_warnings":       warnings,
        "review_items":            review_items,
        "cross_form": {
            "umbrella_issues": umbrella_cf,
            "hard_stops":      cf_hard,
            "soft_stops":      cf_soft,
        },
        "thresholds": {
            "gl_each_occurrence_min": _UMB_GL_OCC_MIN,
            "gl_aggregate_min":       _UMB_GL_AGG_MIN,
            "auto_csl_min":           _UMB_AUTO_CSL_MIN,
            "el_full_credit":         _UMB_EL_FULL,
            "el_acceptable_min":      _UMB_EL_OK,
        },
        "inputs_echo": {"facts": facts, "flags": flags, "triggered_ids": sorted(triggered_ids)},
    }
