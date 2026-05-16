import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config.database import get_pool
from config.settings import PLANS, FRONTEND_URL, STRIPE_WEBHOOK_SECRET
from models.schemas import ApplyOverageRequest, CheckoutRequest, OverageCheckoutRequest
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user, invalidate_user_cache
from services.email_service import _send_payment_failed_email
from services.stripe_service import evaluate_package_limit, get_or_create_stripe_customer
from utils.rate_limiter import check_verify_upgrade_rate_limit

router = APIRouter(prefix="/api/stripe", tags=["stripe"])
logger = logging.getLogger(__name__)


@router.post("/create-checkout")
async def create_checkout(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    if not stripe.api_key:
        raise HTTPException(500, "Stripe is not configured. Contact support.")

    plan = req.plan.lower()
    cycle = req.billing_cycle.lower()
    if plan == "enterprise":
        raise HTTPException(400, "Enterprise requires contacting sales.")
    if plan not in PLANS:
        raise HTTPException(400, f"Unknown plan '{plan}'")
    if cycle not in ("monthly", "annual"):
        raise HTTPException(400, "billing_cycle must be 'monthly' or 'annual'")

    plan_cfg   = PLANS[plan][cycle]
    plan_label = f"Acordly {plan.title()} — {'Annual' if cycle == 'annual' else 'Monthly'}"

    _overage_descriptions = {
        "essentials":    "Includes 50 scores/month. Overages billed at $1.75/score.",
        "professional":  "Includes 100 packages/month. Overages billed at $1.50/package.",
        "business":      "Includes 400 packages/month. Overages billed at $1.25/package.",
    }
    plan_description = _overage_descriptions.get(plan)

    customer_id = current_user.get("stripe_customer_id")

    def _build_checkout_kwargs(cid: str | None) -> dict:
        product_data = {"name": plan_label}
        if plan_description:
            product_data["description"] = plan_description
        kwargs = dict(
            payment_method_types=["card"],
            line_items=[{"price_data": {"currency": "usd",
                "product_data": product_data,
                "unit_amount": plan_cfg["amount"],
                "recurring": {"interval": plan_cfg["interval"]}}, "quantity": 1}],
            mode="subscription",
            success_url=f"{FRONTEND_URL}?upgraded=true&plan={plan}&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}?upgraded=false",
            client_reference_id=str(current_user["id"]),
            metadata={"plan": plan, "billing_cycle": cycle, "user_id": str(current_user["id"])},
            subscription_data={
                "metadata": {"plan": plan, "billing_cycle": cycle, "user_id": str(current_user["id"])}
            },
        )
        if cid:
            kwargs["customer"] = cid
        else:
            kwargs["customer_email"] = current_user["email"]
        return kwargs

    try:
        session = stripe.checkout.Session.create(**_build_checkout_kwargs(customer_id))
        return {"checkout_url": session.url}
    except stripe.error.InvalidRequestError as e:
        # Stale customer ID (deleted or wrong mode) — clear it and retry without it
        if customer_id and "No such customer" in str(e):
            logger.warning(f"Stale stripe_customer_id {customer_id} for user {current_user['id']}, clearing and retrying")
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE users SET stripe_customer_id = NULL WHERE id = $1", current_user["id"]
                )
            try:
                session = stripe.checkout.Session.create(**_build_checkout_kwargs(None))
                return {"checkout_url": session.url}
            except stripe.error.StripeError as inner_e:
                logger.error(f"Stripe error after customer reset: {inner_e}")
                raise HTTPException(500, detail="Payment processing failed. Please try again.")
        logger.error(f"Stripe error: {e}")
        raise HTTPException(500, detail="Payment processing failed. Please try again.")
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key is invalid. Contact support.")
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(500, detail="Payment processing failed. Please try again.")
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(500, "Payment processing failed. Please try again.")


# ASYNC-SAFE
@router.post("/webhook")
async def stripe_webhook(request: Request):
    from fastapi import HTTPException
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured — rejecting webhook")
        raise HTTPException(400, "Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        event = json.loads(str(event))
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature")
    except Exception:
        raise HTTPException(400, "Webhook processing error")

    event_id   = event.get("id", "")
    event_type = event["type"]
    logger.info(f"Stripe webhook: {event_type} ({event_id})")

    # ASYNC-SAFE
    async def _resolve_user(obj):
        uid = obj.get("client_reference_id")
        email = obj.get("customer_email") or (obj.get("customer_details") or {}).get("email")
        async with get_pool().acquire() as conn:
            if uid:
                row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", uid)
                if not row:
                    uid = None
            if not uid and email:
                row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
                if row:
                    uid = dict(row)["id"]
        return uid

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        user_id = await _resolve_user(obj)
        metadata = obj.get("metadata", {})

        if metadata.get("type") == "overage":
            qty = int(metadata.get("qty", 0))
            uid = metadata.get("user_id") or user_id
            sid = obj.get("id", "")
            if uid and qty > 0 and sid:
                async with get_pool().acquire() as conn:
                    async with conn.transaction():
                        if event_id:
                            now_str = datetime.now(timezone.utc).isoformat()
                            idempotency_status = await conn.execute(
                                "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                                " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                                event_id, event_type, now_str,
                            )
                            if int(idempotency_status.split()[-1]) == 0:
                                logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                                return {"received": True}
                        existing = await conn.fetchrow(
                            "SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = $1", sid
                        )
                        if not existing:
                            now = datetime.now(timezone.utc).isoformat()
                            await conn.execute(
                                "UPDATE users SET packages_limit = packages_limit + $1 WHERE id = $2", qty, uid
                            )
                            await conn.execute(
                                "INSERT INTO applied_overage_sessions VALUES ($1,$2,$3,$4)", sid, str(uid), qty, now
                            )
                            await write_audit_log(
                                {"id": uid, "email": ""},
                                "payment.overage_applied",
                                session_id=sid,
                                form_name=str(qty),
                            )
                            await invalidate_user_cache(str(uid))
            return {"received": True}

        if obj.get("mode") != "setup":
            sub_id = obj.get("subscription")
            if not sub_id and obj.get("customer"):
                _subs = stripe.Subscription.list(customer=obj["customer"], status="active", limit=1)
                if _subs.data:
                    sub_id = _subs.data[0].id
            plan = metadata.get("plan", "essentials")
            cycle = metadata.get("billing_cycle", "monthly")
            stripe_customer = obj.get("customer")
            # Always cancel all other active subscriptions the moment a new one is confirmed,
            # regardless of whether metadata is complete. Runs before DB update so the
            # customer never accumulates stale subs (Stripe enforces a 3-sub limit on test clocks).
            if stripe_customer and sub_id:
                try:
                    for st in ("active", "past_due", "trialing"):
                        old_subs = stripe.Subscription.list(customer=stripe_customer, status=st, limit=10)
                        for old_sub in old_subs.auto_paging_iter():
                            old_id = getattr(old_sub, "id", None)
                            if old_id and old_id != sub_id:
                                stripe.Subscription.cancel(old_id)
                                logger.info(f"Canceled old subscription {old_id} after new plan {plan} activated")
                except Exception as ce:
                    logger.warning(f"Could not cancel old subscriptions: {ce}")

            if user_id and plan in PLANS and cycle in PLANS[plan] and sub_id:
                cfg = PLANS[plan][cycle]
                now = datetime.now(timezone.utc).isoformat()
                async with get_pool().acquire() as conn:
                    async with conn.transaction():
                        if event_id:
                            now_str = datetime.now(timezone.utc).isoformat()
                            idempotency_status = await conn.execute(
                                "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                                " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                                event_id, event_type, now_str,
                            )
                            if int(idempotency_status.split()[-1]) == 0:
                                logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                                return {"received": True}
                        if stripe_customer:
                            await conn.execute(
                                "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
                                stripe_customer, user_id,
                            )
                        await conn.execute(
                            """UPDATE users SET subscription_tier=$1, stripe_subscription_id=$2,
                                packages_limit=$3, packages_used=0, billing_cycle=$4, billing_period_start=$5,
                                overage_rate=$6, payment_status='ok', payment_failed_at=NULL,
                                payment_email_sent_day=0,
                                overage_packages_pending=0, overage_packages_invoiced=0 WHERE id=$7""",
                            plan, sub_id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id,
                        )
                    await write_audit_log(
                        {"id": user_id, "email": obj.get("customer_email", ""), "stripe_customer_id": stripe_customer},
                        "payment.subscription_created",
                        session_id=sub_id,
                    )
                    await invalidate_user_cache(str(user_id))

        customer_id = obj.get("customer")
        if customer_id:
            pm = None
            setup_intent_id = obj.get("setup_intent")
            if setup_intent_id:
                try:
                    si = stripe.SetupIntent.retrieve(setup_intent_id)
                    pm = getattr(si, "payment_method", None)
                    if pm:
                        stripe.Customer.modify(customer_id,
                            invoice_settings={"default_payment_method": pm}
                        )
                        logger.info(f"Set default payment method {pm} for {customer_id}")
                        try:
                            subs = stripe.Subscription.list(customer=customer_id, limit=10)
                            for sub in subs.auto_paging_iter():
                                sub_status = getattr(sub, "status", "")
                                if sub_status not in ("canceled", "incomplete_expired"):
                                    stripe.Subscription.modify(
                                        getattr(sub, "id"),
                                        default_payment_method=pm
                                    )
                                    logger.info(f"Updated subscription {getattr(sub, 'id')} PM to {pm}")
                        except Exception as sub_e:
                            logger.warning(f"Could not update subscription PM: {sub_e}")
                except Exception as e:
                    logger.warning(f"Could not set default payment method: {e}")

            try:
                invoices = stripe.Invoice.list(customer=customer_id, status="open", limit=5)
                for invoice in invoices.auto_paging_iter():
                    invoice_id = getattr(invoice, "id", None)
                    if not invoice_id:
                        continue
                    try:
                        pay_kwargs = {"payment_method": pm} if pm else {}
                        stripe.Invoice.pay(invoice_id, **pay_kwargs)
                        logger.info(f"Auto-retried invoice {invoice_id} for {customer_id}")
                    except stripe.error.CardError as e:
                        logger.warning(f"Card declined on retry {invoice_id}: {e}")
                    except stripe.error.InvalidRequestError as e:
                        logger.warning(f"Invoice retry invalid {invoice_id}: {e}")
                    except Exception as e:
                        logger.warning(f"Invoice retry failed {invoice_id}: {e}")
            except Exception as e:
                logger.warning(f"Could not list/retry invoices: {e}")

    elif event["type"] in ("invoice.paid", "invoice.payment_succeeded"):
        obj = event["data"]["object"]
        sub_id = obj.get("subscription")
        if not sub_id:
            parent = obj.get("parent") or {}
            sub_id = (parent.get("subscription_details") or {}).get("subscription")
        if sub_id:
            # On the first payment of a new subscription, cancel any other active
            # subscriptions the customer still has. This runs on confirmed payment
            # and is the authoritative cancellation point (checkout.session.completed
            # may fire before the new sub is fully active).
            billing_reason = obj.get("billing_reason") or ""
            if billing_reason == "subscription_create":
                invoice_customer = obj.get("customer")
                if invoice_customer:
                    try:
                        for st in ("active", "past_due", "trialing"):
                            old_subs = stripe.Subscription.list(
                                customer=invoice_customer, status=st, limit=10
                            )
                            for old_sub in old_subs.auto_paging_iter():
                                old_id = getattr(old_sub, "id", None)
                                if old_id and old_id != sub_id:
                                    stripe.Subscription.cancel(old_id)
                                    logger.info(
                                        "invoice.paid: canceled old subscription %s "
                                        "(new sub %s confirmed for customer %s)",
                                        old_id, sub_id, invoice_customer,
                                    )
                    except Exception as ce:
                        logger.warning("invoice.paid: could not cancel old subscriptions: %s", ce)

            now = datetime.now(timezone.utc).isoformat()
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    if event_id:
                        now_str = datetime.now(timezone.utc).isoformat()
                        idempotency_status = await conn.execute(
                            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                            event_id, event_type, now_str,
                        )
                        if int(idempotency_status.split()[-1]) == 0:
                            logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                            return {"received": True}
                    await conn.execute(
                        """UPDATE users SET packages_used=0, billing_period_start=$1,
                            payment_status='ok', payment_failed_at=NULL,
                            payment_email_sent_day=0,
                            overage_packages_pending=0, overage_packages_invoiced=0
                            WHERE stripe_subscription_id=$2""",
                        now, sub_id,
                    )
                    updated_user = await conn.fetchrow(
                        "SELECT id FROM users WHERE stripe_subscription_id=$1", sub_id
                    )
                    if updated_user:
                        await invalidate_user_cache(str(dict(updated_user)["id"]))

    elif event["type"] == "invoice.payment_failed":
        obj = event["data"]["object"]

        # Stripe API v2026: subscription moved to parent.subscription_details.subscription
        sub_id = obj.get("subscription")
        if not sub_id:
            parent = obj.get("parent") or {}
            sub_id = (parent.get("subscription_details") or {}).get("subscription")
        customer_id_from_invoice = obj.get("customer")
        logger.info(f"invoice.payment_failed: sub_id={sub_id!r} customer={customer_id_from_invoice!r} event={event_id}")

        if not sub_id:
            logger.warning(f"invoice.payment_failed: no subscription ID found in event {event_id} — cannot update user")
        else:
            now = datetime.now(timezone.utc).isoformat()
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    if event_id:
                        now_str = datetime.now(timezone.utc).isoformat()
                        idempotency_status = await conn.execute(
                            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                            event_id, event_type, now_str,
                        )
                        if int(idempotency_status.split()[-1]) == 0:
                            logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                            return {"received": True}
                    await conn.execute(
                        "UPDATE users SET payment_status='failed',"
                        " payment_failed_at=COALESCE(payment_failed_at,$1)"
                        " WHERE stripe_subscription_id=$2",
                        now, sub_id,
                    )
                    row = await conn.fetchrow(
                        "SELECT id, email, full_name, stripe_customer_id, payment_failed_at, "
                        "COALESCE(payment_email_sent_day, 0) AS payment_email_sent_day "
                        "FROM users WHERE stripe_subscription_id = $1",
                        sub_id,
                    )
                    # Fallback: look up by stripe_customer_id if sub_id not stored yet
                    if not row and customer_id_from_invoice:
                        logger.warning(f"invoice.payment_failed: no user found by sub_id={sub_id!r}, trying customer_id={customer_id_from_invoice!r}")
                        row = await conn.fetchrow(
                            "SELECT id, email, full_name, stripe_customer_id, stripe_subscription_id, payment_failed_at, "
                            "COALESCE(payment_email_sent_day, 0) AS payment_email_sent_day "
                            "FROM users WHERE stripe_customer_id = $1",
                            customer_id_from_invoice,
                        )
                        if row:
                            _current_sub = dict(row).get("stripe_subscription_id")
                            if _current_sub and _current_sub != sub_id:
                                # User already upgraded to a different subscription.
                                # This invoice.payment_failed is for their old/cancelled sub — ignore it.
                                logger.info(
                                    "invoice.payment_failed: skipping — user %s already has sub=%s, "
                                    "invoice belongs to old sub=%s",
                                    dict(row)["id"], _current_sub, sub_id,
                                )
                                row = None  # prevents payment_failed email from being sent below
                            else:
                                await conn.execute(
                                    "UPDATE users SET payment_status='failed',"
                                    " payment_failed_at=COALESCE(payment_failed_at,$1),"
                                    " stripe_subscription_id=$2"
                                    " WHERE id=$3",
                                    now, sub_id, dict(row)["id"],
                                )

            if not row:
                logger.error(f"invoice.payment_failed: no user found for sub_id={sub_id!r} customer={customer_id_from_invoice!r} — DB NOT updated, email NOT sent")
            else:
                await write_audit_log(
                    {"id": row["id"], "email": row["email"], "stripe_customer_id": row.get("stripe_customer_id", "")},
                    "payment.failed",
                    session_id=sub_id,
                )
                await invalidate_user_cache(str(row["id"]))
                row = dict(row)
                logger.info(f"invoice.payment_failed: user={row['id']} email={row['email']} payment_email_sent_day={row.get('payment_email_sent_day')}")
                if int(row.get("payment_email_sent_day") or 0) < 1:
                    sent_ok = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: _send_payment_failed_email(row["email"], row.get("full_name", ""), day=1)
                    )
                    if sent_ok:
                        async with get_pool().acquire() as conn:
                            await conn.execute(
                                "UPDATE users SET payment_email_sent_day=1 WHERE id=$1",
                                row["id"],
                            )
                    else:
                        logger.error(f"invoice.payment_failed: day-1 email send returned False for user={row['id']} — will retry on next webhook/lifecycle run")
                else:
                    logger.info(f"invoice.payment_failed: day-1 email already sent for user={row['id']}, skipping")

    elif event["type"] == "customer.subscription.deleted":
        obj = event["data"]["object"]
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
        if sub_id:
            # Before downgrading, check if the customer has another active subscription.
            # This prevents a race condition where cancelling old subs (during a plan change)
            # fires deleted events that downgrade the user before the new sub is written to DB.
            has_active_sub = False
            if customer_id:
                try:
                    active = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
                    has_active_sub = bool(active.data)
                except Exception as e:
                    logger.warning(f"Could not check active subs for customer {customer_id}: {e}")

            if has_active_sub:
                logger.info(f"Subscription {sub_id} deleted but customer {customer_id} has another active sub — skipping downgrade")
            else:
                async with get_pool().acquire() as conn:
                    async with conn.transaction():
                        if event_id:
                            now_str = datetime.now(timezone.utc).isoformat()
                            idempotency_status = await conn.execute(
                                "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                                " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                                event_id, event_type, now_str,
                            )
                            if int(idempotency_status.split()[-1]) == 0:
                                logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                                return {"received": True}
                        cancelled_row = await conn.fetchrow(
                            "SELECT id, email, stripe_customer_id FROM users WHERE stripe_subscription_id = $1",
                            sub_id,
                        )
                        await conn.execute(
                            "UPDATE users SET subscription_tier='free', packages_limit=0, packages_used=0,"
                            " payment_status='ok', payment_failed_at=NULL, stripe_subscription_id=NULL,"
                            " overage_packages_pending=0, overage_packages_invoiced=0"
                            " WHERE stripe_subscription_id=$1",
                            sub_id,
                        )
                    if cancelled_row:
                        await write_audit_log(
                            {"id": cancelled_row["id"], "email": cancelled_row["email"], "stripe_customer_id": cancelled_row.get("stripe_customer_id", "")},
                            "payment.subscription_cancelled",
                            session_id=sub_id,
                        )
                        await invalidate_user_cache(str(cancelled_row["id"]))
                logger.info(f"Subscription deleted: user downgraded to free for sub {sub_id}")

    elif event["type"] == "customer.subscription.updated":
        obj = event["data"]["object"]
        sub_id = obj.get("id")
        cancel_at_period_end = obj.get("cancel_at_period_end", False)
        status = obj.get("status", "")
        metadata = obj.get("metadata") or {}
        new_plan = metadata.get("plan") if isinstance(metadata, dict) else getattr(metadata, "plan", None)
        new_cycle = (
            metadata.get("billing_cycle") if isinstance(metadata, dict)
            else getattr(metadata, "billing_cycle", None)
        ) or "monthly"
        if sub_id:
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    if event_id:
                        now_str = datetime.now(timezone.utc).isoformat()
                        idempotency_status = await conn.execute(
                            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                            event_id, event_type, now_str,
                        )
                        if int(idempotency_status.split()[-1]) == 0:
                            logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
                            return {"received": True}
                    if new_plan and new_plan in PLANS and status == "active":
                        cfg = PLANS[new_plan].get(new_cycle) or PLANS[new_plan]["monthly"]
                        now = datetime.now(timezone.utc).isoformat()
                        exec_status = await conn.execute(
                            """UPDATE users SET subscription_tier=$1, billing_cycle=$2,
                                packages_limit=$3, overage_rate=$4, packages_used=0,
                                billing_period_start=$5
                                WHERE stripe_subscription_id=$6 AND subscription_tier != $7""",
                            new_plan, new_cycle, cfg["packages"], cfg["overage_rate"], now, sub_id, new_plan,
                        )
                        if int(exec_status.split()[-1]):
                            logger.info(f"subscription.updated: synced plan={new_plan}, reset packages_used=0 for sub {sub_id}")
                    if cancel_at_period_end:
                        await conn.execute(
                            "UPDATE users SET payment_status='canceling'"
                            " WHERE stripe_subscription_id=$1"
                            " AND payment_status NOT IN ('failed','soft_locked','suspended','archived')",
                            sub_id,
                        )
                    elif status == "active" and not cancel_at_period_end:
                        await conn.execute(
                            "UPDATE users SET payment_status='ok', payment_failed_at=NULL,"
                            " payment_email_sent_day=0"
                            " WHERE stripe_subscription_id=$1"
                            " AND payment_status IN ('canceling','failed','soft_locked','suspended')",
                            sub_id,
                        )
                    elif status == "past_due":
                        now_pd = datetime.now(timezone.utc).isoformat()
                        await conn.execute(
                            "UPDATE users SET payment_status='failed',"
                            " payment_failed_at=COALESCE(payment_failed_at,$1)"
                            " WHERE stripe_subscription_id=$2"
                            " AND payment_status NOT IN ('soft_locked','suspended','archived')",
                            now_pd, sub_id,
                        )
                    affected = await conn.fetchrow(
                        "SELECT id FROM users WHERE stripe_subscription_id=$1", sub_id
                    )
                    if affected:
                        await invalidate_user_cache(str(dict(affected)["id"]))

    return {"received": True}


# ASYNC-SAFE — called by Render Cron Job (or any external cron) as a fallback
# when APScheduler doesn't fire (e.g. free-tier sleep, worker restart).
# Protect with LIFECYCLE_TRIGGER_SECRET env var set in Render dashboard.
@router.post("/trigger-lifecycle")
async def trigger_lifecycle(request: Request):
    from fastapi import HTTPException
    secret   = request.headers.get("x-lifecycle-secret", "")
    expected = os.getenv("LIFECYCLE_TRIGGER_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(401, "Unauthorized")
    from services.scheduler_service import run_daily_payment_lifecycle
    await run_daily_payment_lifecycle()
    return {"triggered": True}


# ASYNC-SAFE
@router.post("/verify-upgrade")
async def verify_upgrade(current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    check_verify_upgrade_rate_limit(str(current_user["id"]))
    user_email  = current_user.get("email")
    user_id     = current_user.get("id")
    customer_id = current_user.get("stripe_customer_id")
    try:
        customers_to_check = []
        if customer_id:
            customers_to_check.append(type("C", (), {"id": customer_id})())
        else:
            listed = stripe.Customer.list(email=user_email, limit=5)
            customers_to_check = list(listed.data)

        if not customers_to_check:
            return {"subscription_tier": "free", "upgraded": False, "reason": "no_stripe_customer"}

        for customer in customers_to_check:
            subs = stripe.Subscription.list(customer=customer.id, status="active", limit=5)
            if subs.data:
                sub    = subs.data[0]
                sub_id = sub.id
                raw_meta = getattr(sub, "metadata", None) or {}
                plan = (
                    raw_meta.get("plan") if isinstance(raw_meta, dict)
                    else getattr(raw_meta, "plan", None)
                ) or None
                cycle = (
                    raw_meta.get("billing_cycle") if isinstance(raw_meta, dict)
                    else getattr(raw_meta, "billing_cycle", None)
                ) or "monthly"
                if not plan or plan not in PLANS:
                    try:
                        price_amount = sub.items.data[0].price.unit_amount
                        plan = next(
                            (p for p, cfg in PLANS.items()
                             for c, v in cfg.items() if v["amount"] == price_amount),
                            "essentials",
                        )
                    except Exception:
                        plan = "essentials"
                cfg = PLANS.get(plan, {}).get(cycle) or PLANS["essentials"]["monthly"]
                now = datetime.now(timezone.utc).isoformat()
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        """UPDATE users SET subscription_tier=$1, stripe_subscription_id=$2,
                            stripe_customer_id=$3, packages_limit=$4, billing_cycle=$5,
                            billing_period_start=$6, overage_rate=$7,
                            payment_status='ok', payment_failed_at=NULL,
                            payment_email_sent_day=0 WHERE id=$8""",
                        plan, sub_id, customer.id, cfg["packages"], cycle,
                        now, cfg["overage_rate"], user_id,
                    )
                logger.info(f"verify-upgrade synced user {user_id} to plan={plan} sub={sub_id}, reset packages_used=0")
                await invalidate_user_cache(str(user_id))

                # Cancel every other active/past_due/trialing subscription for this
                # customer now that payment is confirmed and the new sub is synced.
                try:
                    for _st in ("active", "past_due", "trialing"):
                        _others = stripe.Subscription.list(customer=customer.id, status=_st, limit=10)
                        for _other in _others.auto_paging_iter():
                            _oid = getattr(_other, "id", None)
                            if _oid and _oid != sub_id:
                                stripe.Subscription.cancel(_oid)
                                logger.info(
                                    "verify-upgrade: canceled old subscription %s "
                                    "(new plan=%s sub=%s customer=%s)",
                                    _oid, plan, sub_id, customer.id,
                                )
                except Exception as _ce:
                    logger.warning("verify-upgrade: could not cancel old subscriptions: %s", _ce)

                return {"subscription_tier": plan, "upgraded": True, "reason": "stripe_verified"}

        if current_user.get("subscription_tier") not in ("free", None):
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE users SET subscription_tier='free', stripe_subscription_id=NULL,"
                    " packages_limit=0 WHERE id=$1",
                    user_id,
                )
        return {"subscription_tier": "free", "upgraded": False, "reason": "no_active_subscription"}
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key not configured")
    except Exception as e:
        import traceback
        logger.error(f"verify-upgrade error: error_type={type(e).__name__}, error_code={getattr(e, 'code', None)}")
        logger.debug(f"verify-upgrade traceback:\n{traceback.format_exc()}")
        raise HTTPException(500, "Subscription verification failed. Please try again.")


@router.post("/create-overage-checkout")
async def create_overage_checkout(
    req: OverageCheckoutRequest,
    current_user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")

    tier = current_user.get("subscription_tier", "free")
    _default_rate = 175 if tier == "essentials" else (150 if tier == "professional" else 125)
    overage_rate_cents  = int(current_user.get("overage_rate") or _default_rate)
    overage_rate_dollars = overage_rate_cents / 100
    qty        = max(1, min(req.quantity, 10000))
    tier_label = {"essentials": "Essentials", "professional": "Professional", "business": "Business"}.get(tier, tier.title())
    unit_label = "score" if tier == "essentials" else "package"
    description = (
        f"Acordly {tier_label} — {qty} additional ACORD {unit_label}s "
        f"@ ${overage_rate_dollars:.2f}/{unit_label}"
    )

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            client_reference_id=str(current_user["id"]),
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": overage_rate_cents,
                    "product_data": {
                        "name": f"Acordly Extra {unit_label.title()}s ({tier_label})",
                        "description": description,
                    },
                },
                "quantity": qty,
            }],
            metadata={
                "type": "overage",
                "user_id": str(current_user["id"]),
                "qty": str(qty),
            },
            success_url=(
                f"{FRONTEND_URL}/?overage_paid=true&qty={qty}"
                f"&user_id={current_user['id']}"
                f"&stripe_session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{FRONTEND_URL}/",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"Overage checkout error: {e}")
        raise HTTPException(500, "Could not create checkout session. Please try again.")


# ASYNC-SAFE
@router.post("/apply-overage")
async def apply_overage(
    req: ApplyOverageRequest,
    current_user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")

    try:
        cs = stripe.checkout.Session.retrieve(req.stripe_session_id)
    except Exception:
        raise HTTPException(400, "Could not verify payment. Please try again.")

    cs = json.loads(str(cs))
    if cs.get("payment_status") != "paid":
        raise HTTPException(
            400,
            f"Payment not completed (status={cs.get('payment_status')})",
        )

    session_user_id = cs.get("client_reference_id") or cs.get("metadata", {}).get("user_id")
    if str(session_user_id) != str(current_user["id"]):
        raise HTTPException(403, "Session does not belong to this user")

    if cs.get("metadata", {}).get("type") != "overage":
        raise HTTPException(400, "Not an overage session")

    qty = int(cs.get("metadata", {}).get("qty", 0))
    if qty <= 0:
        raise HTTPException(400, "Invalid quantity in session metadata")

    async with get_pool().acquire() as conn:
        user_row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", current_user["id"])
        if not user_row:
            raise HTTPException(404, "User not found")

        existing = await conn.fetchrow(
            "SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = $1",
            req.stripe_session_id,
        )
        if existing:
            limit_row = await conn.fetchrow(
                "SELECT packages_limit FROM users WHERE id = $1", current_user["id"]
            )
            return {
                "credited": False,
                "already_applied": True,
                "packages_limit": dict(limit_row)["packages_limit"],
            }

        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "UPDATE users SET packages_limit = packages_limit + $1 WHERE id = $2",
            qty, current_user["id"],
        )
        await conn.execute(
            "INSERT INTO applied_overage_sessions"
            " (stripe_session_id, user_id, qty, applied_at) VALUES ($1,$2,$3,$4)",
            req.stripe_session_id, str(current_user["id"]), qty, now,
        )
        updated = await conn.fetchrow(
            "SELECT packages_limit FROM users WHERE id = $1", current_user["id"]
        )

    return {
        "credited": True,
        "qty": qty,
        "packages_limit": dict(updated)["packages_limit"],
    }


# ASYNC-SAFE
@router.post("/cancel-subscription")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException

    customer_id = current_user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found for this account.")

    try:
        active_subs = stripe.Subscription.list(customer=customer_id, status="active", limit=5)
        subs = list(active_subs.auto_paging_iter())
        if not subs:
            raise HTTPException(400, "No active subscription found in Stripe.")

        cancelled_ids = []
        for sub in subs:
            real_sub_id = getattr(sub, "id", None)
            if not real_sub_id:
                continue
            stripe.Subscription.modify(real_sub_id, cancel_at_period_end=True)
            cancelled_ids.append(real_sub_id)
            logger.info(f"Set cancel_at_period_end=True for sub {real_sub_id} (customer {customer_id})")

        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET payment_status='canceling', stripe_subscription_id=$1 WHERE id=$2",
                cancelled_ids[0], current_user["id"],
            )
        await invalidate_user_cache(str(current_user["id"]))

        return {"success": True, "message": "Subscription will cancel at the end of the current billing period."}
    except stripe.error.InvalidRequestError:
        raise HTTPException(400, "Could not cancel subscription. Please contact support.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel subscription error: {e}")
        raise HTTPException(500, "Failed to cancel subscription.")


# ASYNC-SAFE
@router.post("/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):
    from fastapi import HTTPException

    if not user.get("stripe_customer_id"):
        try:
            plan          = user.get("subscription_tier", "essentials")
            billing_cycle = user.get("billing_cycle", "monthly") or "monthly"

            if plan not in PLANS or plan == "free":
                plan = "essentials"
            if billing_cycle not in ("monthly", "annual"):
                billing_cycle = "monthly"

            plan_data = PLANS[plan][billing_cycle]

            existing_customers = stripe.Customer.list(email=user["email"], limit=1)
            if existing_customers.data:
                customer = existing_customers.data[0]
                logger.info(f"Reusing existing Stripe customer {customer.id} for {user['email']}")
            else:
                customer = stripe.Customer.create(
                    email=user["email"],
                    name=user.get("full_name", ""),
                    metadata={"user_id": user["id"]},
                )

            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
                    customer.id, user["id"],
                )

            active_subs = stripe.Subscription.list(customer=customer.id, status="active", limit=1)
            if active_subs.data:
                existing_sub  = active_subs.data[0]
                sub_meta      = getattr(existing_sub, "metadata", None) or {}
                existing_plan = getattr(sub_meta, "plan", None) or plan
                existing_cycle = getattr(sub_meta, "billing_cycle", None) or billing_cycle
                existing_cfg  = PLANS.get(existing_plan, {}).get(existing_cycle, PLANS["essentials"]["monthly"])
                now = datetime.now(timezone.utc).isoformat()
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        """UPDATE users SET stripe_subscription_id=$1, subscription_tier=$2,
                           billing_cycle=$3, packages_limit=$4, overage_rate=$5,
                           payment_status='ok', payment_failed_at=NULL WHERE id=$6""",
                        existing_sub.id, existing_plan, existing_cycle,
                        existing_cfg["packages"], existing_cfg["overage_rate"], user["id"],
                    )
                logger.info(f"Restored subscription {existing_sub.id} for user {user['id']} from Stripe")
                try:
                    portal_session = stripe.billing_portal.Session.create(
                        customer=customer.id,
                        return_url=f"{FRONTEND_URL}?billing_updated=true",
                    )
                    return {"url": portal_session.url}
                except stripe.error.InvalidRequestError:
                    setup_session = stripe.checkout.Session.create(
                        customer=customer.id,
                        payment_method_types=["card"],
                        mode="setup",
                        success_url=f"{FRONTEND_URL}?billing_updated=true",
                        cancel_url=FRONTEND_URL,
                    )
                    return {"url": setup_session.url}

            checkout = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=["card"],
                mode="subscription",
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"Acordly {plan.title()} — {billing_cycle.title()}",
                        },
                        "unit_amount": plan_data["amount"],
                        "recurring": {"interval": plan_data["interval"]},
                    },
                    "quantity": 1,
                }],
                success_url=f"{FRONTEND_URL}?billing_updated=true",
                cancel_url=FRONTEND_URL,
                metadata={
                    "user_id": user["id"],
                    "plan": plan,
                    "billing_cycle": billing_cycle,
                },
            )
            return {"url": checkout.url}

        except Exception as ex:
            logger.error(f"Portal checkout fallback failed: {ex}")
            raise HTTPException(500, "Could not open billing. Please contact support.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            return_url=f"{FRONTEND_URL}?billing_updated=true",
        )
        return {"url": session.url}
    except stripe.error.InvalidRequestError as ex:
        if "No such customer" in str(ex):
            logger.warning(f"Stale stripe_customer_id {user['stripe_customer_id']} for user {user['id']}, clearing it")
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE users SET stripe_customer_id = NULL WHERE id = $1", user["id"]
                )
            raise HTTPException(400, "Your billing profile was reset. Please try again to set up a new subscription.")
        # Portal not configured in Stripe dashboard — fall back to setup-mode checkout
        logger.warning(f"Billing portal not configured, falling back to setup session: {ex}")
        try:
            setup_session = stripe.checkout.Session.create(
                customer=user["stripe_customer_id"],
                payment_method_types=["card"],
                mode="setup",
                success_url=f"{FRONTEND_URL}?billing_updated=true",
                cancel_url=FRONTEND_URL,
            )
            return {"url": setup_session.url}
        except Exception as inner_ex:
            logger.error(f"Setup session fallback failed: {inner_ex}")
            raise HTTPException(500, "Could not open billing portal.")
    except Exception as ex:
        logger.error(f"Portal session failed: {ex}")
        raise HTTPException(500, "Could not open billing portal.")
