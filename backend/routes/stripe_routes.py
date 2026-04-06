import json
import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config.database import get_db
from config.settings import PLANS, FRONTEND_URL, STRIPE_WEBHOOK_SECRET
from models.schemas import ApplyOverageRequest, CheckoutRequest, OverageCheckoutRequest
from services.auth_service import get_current_user
from services.email_service import _send_payment_failed_email
from services.stripe_service import evaluate_package_limit, get_or_create_stripe_customer

router = APIRouter(prefix="/api/stripe", tags=["stripe"])
logger = logging.getLogger(__name__)


@router.post("/create-checkout")
async def create_checkout(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    plan = req.plan.lower()
    cycle = req.billing_cycle.lower()
    if plan == "enterprise":
        raise HTTPException(400, "Enterprise requires contacting sales.")
    if plan not in PLANS:
        raise HTTPException(400, f"Unknown plan '{plan}'")
    if cycle not in ("monthly", "annual"):
        raise HTTPException(400, "billing_cycle must be 'monthly' or 'annual'")

    plan_cfg = PLANS[plan][cycle]
    plan_label = f"Acordly {plan.title()} — {'Annual' if cycle == 'annual' else 'Monthly'}"
    try:
        session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price_data": {"currency": "usd",
            "product_data": {"name": plan_label},
            "unit_amount": plan_cfg["amount"],
            "recurring": {"interval": plan_cfg["interval"]}}, "quantity": 1}],
        mode="subscription",
        success_url=f"{FRONTEND_URL}?upgraded=true",
        cancel_url=f"{FRONTEND_URL}?upgraded=false",
        client_reference_id=str(current_user["id"]),
        customer_email=current_user["email"],
        metadata={"plan": plan, "billing_cycle": cycle, "user_id": str(current_user["id"])},
        subscription_data={
            "metadata": {"plan": plan, "billing_cycle": cycle, "user_id": str(current_user["id"])}
        },
    )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(500, f"Stripe error: {e}")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    from fastapi import HTTPException
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            logger.warning("STRIPE_WEBHOOK_SECRET not set")
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(400, "Invalid webhook signature")
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}")

    logger.info(f"Stripe webhook: {event['type']}")

    def _resolve_user(obj):
        user_id = obj["client_reference_id"] if "client_reference_id" in obj else None
        email = obj.get("customer_email") or (obj.get("customer_details") or {}).get("email")
        conn = get_db(); cur = conn.cursor()
        if user_id:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row: user_id = None
        if not user_id and email:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row: user_id = dict(row)["id"]
        cur.close(); conn.close()
        return user_id

    if event["type"] == "checkout.session.completed":
        obj = json.loads(str(event["data"]["object"]))
        user_id = _resolve_user(obj)
        metadata = obj.get("metadata", {})

        if metadata.get("type") == "overage":
            qty = int(metadata.get("qty", 0))
            uid = metadata.get("user_id") or user_id
            sid = obj.get("id", "")
            if uid and qty > 0 and sid:
                conn = get_db(); cur = conn.cursor()
                cur.execute("SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = %s", (sid,))
                if not cur.fetchone():
                    now = datetime.now(timezone.utc).isoformat()
                    cur.execute("UPDATE users SET packages_limit = packages_limit + %s WHERE id = %s", (qty, uid))
                    cur.execute("INSERT INTO applied_overage_sessions VALUES (%s,%s,%s,%s)", (sid, str(uid), qty, now))
                    conn.commit()
                cur.close(); conn.close()
            return {"received": True}

        sub_id = obj.get("subscription")
        if not sub_id and obj.get("customer"):
            _subs = stripe.Subscription.list(customer=obj["customer"], status="active", limit=1)
            if _subs.data:
                sub_id = _subs.data[0].id
        plan = metadata.get("plan", "essentials")
        cycle = metadata.get("billing_cycle", "monthly")
        if user_id and plan in PLANS and cycle in PLANS[plan]:
            cfg = PLANS[plan][cycle]
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            stripe_customer = obj.get("customer")
            if stripe_customer:
                cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s", (stripe_customer, user_id))
            cur.execute("""UPDATE users SET subscription_tier=%s, stripe_subscription_id=%s,
                packages_limit=%s, packages_used=0, billing_cycle=%s, billing_period_start=%s,
                overage_rate=%s, payment_status='ok', payment_failed_at=NULL,
                overage_packages_pending=0, overage_packages_invoiced=0 WHERE id=%s""",
                (plan, sub_id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id))
            conn.commit(); cur.close(); conn.close()

        # Auto-retry any open/failed invoices after new card added
        customer_id = obj.get("customer")
        if customer_id:
            setup_intent_id = obj.get("setup_intent")
            if setup_intent_id:
                try:
                    si = stripe.SetupIntent.retrieve(setup_intent_id)
                    pm = si.get("payment_method")
                    if pm:
                        stripe.Customer.modify(customer_id,
                            invoice_settings={"default_payment_method": pm}
                        )
                        logger.info(f"Set default payment method {pm} for {customer_id}")
                except Exception as e:
                    logger.warning(f"Could not set default payment method: {e}")

            try:
                for status in ["open", "uncollectible"]:
                    invoices = stripe.Invoice.list(customer=customer_id, status=status, limit=5)
                    for invoice in invoices.auto_paging_iter():
                        try:
                            stripe.Invoice.pay(invoice["id"])
                            logger.info(f"Auto-retried invoice {invoice['id']} for {customer_id}")
                        except stripe.error.CardError as e:
                            logger.warning(f"Card declined on retry: {e}")
                        except stripe.error.InvalidRequestError as e:
                            logger.warning(f"Invoice retry invalid: {e}")
            except Exception as e:
                logger.warning(f"Could not list/retry invoices: {e}")

    elif event["type"] in ("invoice.paid", "invoice.payment_succeeded"):
        obj = json.loads(str(event["data"]["object"]))
        sub_id = obj.get("subscription")
        if not sub_id:
            parent = obj.get("parent") or {}
            sub_id = (parent.get("subscription_details") or {}).get("subscription")
        if sub_id:
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            cur.execute("""UPDATE users SET packages_used=0, billing_period_start=%s,
                payment_status='ok', payment_failed_at=NULL,
                overage_packages_pending=0, overage_packages_invoiced=0
                WHERE stripe_subscription_id=%s""", (now, sub_id))
            conn.commit(); cur.close(); conn.close()

    elif event["type"] == "invoice.payment_failed":
        obj = json.loads(str(event["data"]["object"]))
        sub_id = obj.get("subscription")
        if not sub_id:
            parent = obj.get("parent") or {}
            sub_id = (parent.get("subscription_details") or {}).get("subscription")
        if sub_id:
            now = datetime.now(timezone.utc).isoformat()
            conn = get_db(); cur = conn.cursor()
            cur.execute("UPDATE users SET payment_status='failed', payment_failed_at=COALESCE(payment_failed_at,%s) WHERE stripe_subscription_id=%s", (now, sub_id))
            conn.commit()
            cur.execute("SELECT email, full_name FROM users WHERE stripe_subscription_id = %s", (sub_id,))
            row = cur.fetchone(); cur.close(); conn.close()
            if row:
                row = dict(row)
                _send_payment_failed_email(row["email"], row.get("full_name",""), day=1)

    elif event["type"] == "customer.subscription.deleted":
        sub_id = json.loads(str(event["data"]["object"])).get("id")
        if sub_id:
            conn = get_db(); cur = conn.cursor()
            cur.execute("UPDATE users SET subscription_tier='free', packages_limit=0, packages_used=0, payment_status='ok', payment_failed_at=NULL, overage_packages_pending=0, overage_packages_invoiced=0 WHERE stripe_subscription_id=%s", (sub_id,))
            conn.commit(); cur.close(); conn.close()

    return {"received": True}


@router.post("/verify-upgrade")
async def verify_upgrade(current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    user_email = current_user.get("email")
    user_id = current_user.get("id")
    if current_user.get("subscription_tier") not in ("free", None):
        return {"subscription_tier": current_user["subscription_tier"], "upgraded": False, "reason": "already_subscribed"}
    try:
        customers = stripe.Customer.list(email=user_email, limit=5)
        if not customers.data:
            return {"subscription_tier": "free", "upgraded": False, "reason": "no_stripe_customer"}
        for customer in customers.data:
            subs = stripe.Subscription.list(customer=customer.id, status="active", limit=5)
            if subs.data:
                sub = subs.data[0]; sub_id = sub.id
                meta = dict(sub.get("metadata") or {})
                plan = meta.get("plan", "essentials"); cycle = meta.get("billing_cycle","monthly")
                cfg = PLANS.get(plan, {}).get(cycle, PLANS["essentials"]["monthly"])
                now = datetime.now(timezone.utc).isoformat()
                conn = get_db(); cur = conn.cursor()
                cur.execute("UPDATE users SET subscription_tier=%s, stripe_subscription_id=%s, stripe_customer_id=%s, packages_limit=%s, billing_cycle=%s, billing_period_start=%s, overage_rate=%s, payment_status='ok', payment_failed_at=NULL WHERE id=%s",
                            (plan, sub_id, customer.id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id))
                conn.commit(); cur.close(); conn.close()
                return {"subscription_tier": plan, "upgraded": True, "reason": "stripe_verified"}

        return {"subscription_tier": "free", "upgraded": False, "reason": "no_active_subscription"}
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key not configured")
    except Exception as e:
        import traceback
        logger.error(f"verify-upgrade error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Stripe verification failed: {e}")


@router.post("/create-overage-checkout")
async def create_overage_checkout(
    req: OverageCheckoutRequest,
    current_user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")

    tier = current_user.get("subscription_tier", "free")
    overage_rate_cents = int(current_user.get("overage_rate") or (150 if tier == "essentials" else 125))
    overage_rate_dollars = overage_rate_cents / 100
    qty = max(1, min(req.quantity, 10000))
    tier_label = "Essentials" if tier == "essentials" else "Professional"
    description = (
        f"Acordly {tier_label} — {qty} additional ACORD packages "
        f"@ ${overage_rate_dollars:.2f}/pkg"
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
                        "name": f"Acordly Extra Packages ({tier_label})",
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
        raise HTTPException(500, str(e))


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
    except Exception as e:
        raise HTTPException(400, f"Could not verify payment: {e}")

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

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id = %s",
        (current_user["id"],),
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(404, "User not found")

    cur.execute(
        "SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = %s",
        (req.stripe_session_id,),
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute(
            "SELECT packages_limit FROM users WHERE id = %s",
            (current_user["id"],),
        )
        row = dict(cur2.fetchone())
        cur2.close()
        conn2.close()
        return {
            "credited": False,
            "already_applied": True,
            "packages_limit": row["packages_limit"],
        }

    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "UPDATE users SET packages_limit = packages_limit + %s WHERE id = %s",
        (qty, current_user["id"]),
    )
    cur.execute(
        "INSERT INTO applied_overage_sessions (stripe_session_id, user_id, qty, applied_at) VALUES (%s,%s,%s,%s)",
        (req.stripe_session_id, str(current_user["id"]), qty, now),
    )
    conn.commit()

    cur.execute(
        "SELECT packages_limit FROM users WHERE id = %s",
        (current_user["id"],),
    )
    updated = dict(cur.fetchone())
    cur.close()
    conn.close()

    return {
        "credited": True,
        "qty": qty,
        "packages_limit": updated["packages_limit"],
    }


@router.post("/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):
    from fastapi import HTTPException

    if not user.get("stripe_customer_id"):
        try:
            plan = user.get("subscription_tier", "essentials")
            billing_cycle = user.get("billing_cycle", "monthly") or "monthly"

            if plan not in PLANS or plan == "free":
                plan = "essentials"
            if billing_cycle not in ("monthly", "annual"):
                billing_cycle = "monthly"

            plan_data = PLANS[plan][billing_cycle]

            customer = stripe.Customer.create(
                email=user["email"],
                name=user.get("full_name", ""),
                metadata={"user_id": user["id"]},
            )

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET stripe_customer_id = %s WHERE id = %s",
                (customer.id, user["id"]),
            )
            conn.commit()
            cur.close()
            conn.close()

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
        session = stripe.checkout.Session.create(
            customer=user["stripe_customer_id"],
            payment_method_types=["card"],
            mode="setup",
            success_url=f"{FRONTEND_URL}?billing_updated=true",
            cancel_url=FRONTEND_URL,
        )
        return {"url": session.url}
    except Exception as ex:
        logger.error(f"Portal session failed: {ex}")
        raise HTTPException(500, "Could not open billing portal.")














