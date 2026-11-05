import asyncio
import hmac
import json
import logging
import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from config.database import get_pool
from config.settings import (
    PLANS, SELLABLE_PLANS, FRONTEND_URL, STRIPE_WEBHOOK_SECRET, default_overage_rate_cents,
    plan_usage_unit,
)
from models.schemas import CheckoutRequest
from repositories.audit_repository import write_audit_log
from repositories.session_repository import packages_counted_since
from services.auth_service import get_current_user, invalidate_user_cache
from services.email_service import _send_payment_failed_email
from services.stripe_service import (
    DUP_PENDING, FAILURE_STATUSES, FINAL_PENDING, FINAL_PREFIX, PAYING_SUB_STATUSES, LIVE_SUB_STATUSES,
    StripeUnavailable, allowance_for, clear_monthly_overage_billing, ensure_monthly_overage_billing,
    final_overage_key, is_transient, subscription_payment_state, subscription_period, subscription_plan,
    send_claimed_payment_email,
    settle_final_overage,
    subscription_status,
    belongs_to_user, checkout_refusal, clear_stale_customer,
    duplicate_key, ensure_stripe_customer, field, is_ending, is_missing_customer, is_missing_subscription,
    list_all, live_primble_subscriptions, notify_admins, off_cycle_price, primble_customers_by_email,
    send_billing_alert,
    settle_duplicate_checkout,
)
from services.usage_service import (
    adopt_plan_usage, clear_usage_months, last_paid_at, record_last_paid, record_usage_anchor, recount_period,
    roll_usage_month, start_plan_months,
    clear_period_end, forgive_held_overage, place_period_overage, plan_switches, record_plan_switch, record_period_end, record_sub_period_end,
    release_held_overage, retry_pending_overage, sub_period_end,
)
from utils.helpers import _safe_parse_dt
from utils.rate_limiter import check_verify_upgrade_rate_limit

# Cards only - which on Stripe's hosted Checkout includes the Apple Pay and Google Pay wallets (3 Nov 2026). ONE
# place for it: Stripe API 2026-09-30.endive rejects `payment_method_types` on Checkout Sessions (the replacement
# is `allowed_payment_method_types`). We are pinned to the SDK's version; `tests/test_stripe_guards_3nov.py` fails
# the build the day an SDK upgrade crosses that line, and this is the line to change.
CHECKOUT_PAYMENT_METHODS = {"payment_method_types": ["card"]}

router = APIRouter(prefix="/api/stripe", tags=["stripe"])
logger = logging.getLogger(__name__)

# A failure never lifts a lock: soft_locked / suspended / archived stay where the
# daily lifecycle put them (2 Nov 2026 - a Smart Retry on day 12 reopened uploads).
_MARK_FAILED = (
    "UPDATE users SET payment_status = CASE WHEN payment_status IN"
    " ('soft_locked','suspended','archived') THEN payment_status ELSE 'failed' END,"
    " payment_failed_at=COALESCE(payment_failed_at,$1)"
)

# The failure stages as an SQL list (internal constants, never user input).
_FAILURE_SQL = ",".join(f"'{s}'" for s in FAILURE_STATUSES)

BILLING_UNAVAILABLE = {
    "code": "billing_unavailable",
    "message": "We couldn't reach our payment provider. Please try again in a minute.",
}
NO_BILLING_ACCOUNT = {"code": "no_billing_account", "message": "There's no billing account to manage yet."}
ENTERPRISE_MANAGED = {"code": "subscription_exists",
                      "message": "Your plan is managed by Primble. Contact support@primble.com to change it."}
# Only the plan's own invoices start a new usage period (2 Nov 2026, L-7): a
# manual invoice, a one-off or a plan's final overage invoice never does.
_PERIOD_REASONS = ("subscription_cycle", "subscription_create")


def _ts_to_dt(ts) -> "datetime | None":
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc) if ts else None
    except Exception:
        return None


def _period_isos(sub) -> tuple:
    """A subscription's current period as ISO strings (None when unknown)."""
    start, end = subscription_period(sub)
    s_dt, e_dt = _ts_to_dt(start), _ts_to_dt(end)
    return (s_dt.isoformat() if s_dt else None, e_dt.isoformat() if e_dt else None)


def _event_created_at(event) -> "datetime | None":
    return _ts_to_dt(event.get("created"))


def _paid_after(row, event_created) -> bool:
    """Stripe does not deliver events in order: a failure it created before the
    user's last successful payment is stale and ignored. The payment is the
    later of billing_period_start (a paid renewal) and `last_paid_at` (any paid
    invoice or restore - an annual plan's monthly overage invoice moves no
    period, 3 Nov 2026, R2)."""
    if event_created is None or not row:
        return False
    times = [t for t in (_safe_parse_dt(row.get("billing_period_start")),
                         _safe_parse_dt(row.get("last_paid_at"))) if t]
    return bool(times and max(times) > event_created)


def _failed_before(row, event_created) -> bool:
    """A SUCCESS event Stripe created before the user's current failure is
    older news than the failure and never clears it (2 Nov 2026, M2)."""
    if event_created is None or not row:
        return False
    failed = _safe_parse_dt(row.get("payment_failed_at"))
    return bool(failed and event_created < failed)


def _failure_time(event_created, now: datetime) -> str:
    """When the payment failed: the event's own time when Stripe gave one, so
    the failure and the success events that follow compare like for like."""
    if event_created is not None and event_created <= now:
        return event_created.isoformat()
    return now.isoformat()


def _paid_time(obj, event_created, now: datetime) -> datetime:
    """When the money arrived, by Stripe's clock (3 Nov 2026, L-C): the
    invoice's own `status_transitions.paid_at`, else the event's time, else
    now. `_paid_after` compares it with a failure event's Stripe time, so a
    late-processed old success never makes a newer failure look stale."""
    paid_at = _ts_to_dt(((obj or {}).get("status_transitions") or {}).get("paid_at"))
    for t in (paid_at, event_created):
        if t is not None and t <= now:
            return t
    return now


def _invoice_subscription(obj) -> "str | None":
    # Stripe API v2026: subscription moved to parent.subscription_details.subscription
    sub_id = obj.get("subscription")
    if not sub_id:
        parent = obj.get("parent") or {}
        sub_id = (parent.get("subscription_details") or {}).get("subscription")
    return sub_id


def _is_proration_line(line) -> bool:
    """A proration line (a mid-period plan change): its period is [the switch,
    the OLD period's end] - it never names the period an invoice opens (3 Nov
    2026, pass 2 #1). Stripe marks it on the line's parent details (dahlia) or
    on the line itself (older API shapes)."""
    if line.get("proration"):
        return True
    parent = line.get("parent") or {}
    return any(bool((parent.get(k) or {}).get("proration"))
               for k in ("subscription_item_details", "invoice_item_details"))


def _subscription_line_periods(obj) -> list:
    """The periods of the invoice's own plan lines - never a proration line or
    a one-off item."""
    out = []
    for line in ((obj.get("lines") or {}).get("data") or []):
        parent = line.get("parent") or {}
        if parent and parent.get("type") not in (None, "subscription_item_details"):
            continue
        if not parent and line.get("type") not in (None, "subscription"):
            continue
        if _is_proration_line(line):
            continue
        out.append(line.get("period") or {})
    return out


def _invoice_period_start(obj) -> "datetime | None":
    """The start of the billing period an invoice pays: its subscription line's
    period (an overage item's line belongs to the period before). None when
    the payload carries no subscription line."""
    starts = [int(p["start"]) for p in _subscription_line_periods(obj) if p.get("start")]
    return _ts_to_dt(min(starts)) if starts else None


def _invoice_period_end(obj) -> "datetime | None":
    ends = [int(p["end"]) for p in _subscription_line_periods(obj) if p.get("end")]
    return _ts_to_dt(max(ends)) if ends else None


async def _claim_key(conn, key: str, kind: str) -> bool:
    """One row in the idempotency table, taken in one statement. True = new."""
    if not key:
        return True
    status = await conn.execute(
        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
        " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
        key, kind, datetime.now(timezone.utc).isoformat(),
    )
    try:
        return int(str(status).split()[-1]) > 0
    except Exception:
        return False


async def _claim_event(conn, event_id: str, event_type: str) -> bool:
    if await _claim_key(conn, event_id, event_type):
        return True
    logger.info(f"Stripe webhook: duplicate event {event_id}, skipping")
    return False


def _refuse(status: int, detail: dict):
    raise HTTPException(status, detail=dict(detail))


@router.post("/create-checkout")
async def create_checkout(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe is not configured. Contact support.")

    plan = req.plan.lower()
    cycle = req.billing_cycle.lower()
    if plan == "enterprise":
        raise HTTPException(400, "Enterprise requires contacting sales.")
    if plan == "business":
        raise HTTPException(400, "The Business plan is no longer offered. Please choose another plan.")
    if plan not in SELLABLE_PLANS:
        raise HTTPException(400, f"Unknown plan '{plan}'")
    if cycle not in ("monthly", "annual"):
        raise HTTPException(400, "billing_cycle must be 'monthly' or 'annual'")

    plan_cfg   = PLANS[plan][cycle]
    plan_label = f"Primble {plan.title()} — {'Annual' if cycle == 'annual' else 'Monthly'}"

    # Derived from PLANS so the text on the Stripe checkout page cannot drift
    # from what the subscription actually meters and bills.
    _monthly         = PLANS[plan]["monthly"]
    _unit            = plan_usage_unit(plan)
    plan_description = (
        f"Includes {_monthly['packages']} {_unit}s/month. "
        f"Overages billed at ${_monthly['overage_rate'] / 100:.2f}/{_unit}."
    )

    # An enterprise plan is Primble's to change, never a checkout's (L-5).
    if (current_user.get("subscription_tier") or "") == "enterprise":
        _refuse(409, ENTERPRISE_MANAGED)

    # One customer per user, stored BEFORE the checkout, and no second plan on
    # top of a live one (2 Nov 2026, B1/H3): a plan change by a new checkout
    # double-charged the user and left the old subscription billing. Stripe
    # out of reach = refuse; never open a checkout blind.
    user = dict(current_user)
    try:
        try:
            customer_id = await ensure_stripe_customer(user)
            live = await live_primble_subscriptions(user, customer_id)
        except Exception as ex:
            if not is_missing_customer(ex):
                raise
            stale = user.get("stripe_customer_id")
            logger.warning(f"Stale stripe_customer_id for user {user['id']}, replacing it")
            await clear_stale_customer(user["id"], stale)
            user["stripe_customer_id"] = None
            customer_id = await ensure_stripe_customer(user, replacing=stale)
            live = await live_primble_subscriptions(user, customer_id)
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key is invalid. Contact support.")
    except (StripeUnavailable, stripe.error.StripeError) as ex:
        logger.error(f"create-checkout: Stripe unreachable for user {user['id']}: {type(ex).__name__}")
        _refuse(503, BILLING_UNAVAILABLE)
    except Exception as ex:
        logger.error(f"create-checkout: subscription check failed for user {user['id']}: {ex}")
        _refuse(503, BILLING_UNAVAILABLE)

    refusal = checkout_refusal(live)
    if refusal:
        logger.info(f"create-checkout refused for user {user['id']}: {refusal['code']}")
        _refuse(409, refusal)

    try:
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            **CHECKOUT_PAYMENT_METHODS,
            line_items=[{"price_data": {"currency": "usd",
                "product_data": {"name": plan_label, "description": plan_description},
                "unit_amount": plan_cfg["amount"],
                "recurring": {"interval": plan_cfg["interval"]}}, "quantity": 1}],
            mode="subscription",
            customer=customer_id,
            success_url=f"{FRONTEND_URL}?upgraded=true&plan={plan}&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}?upgraded=false",
            client_reference_id=str(user["id"]),
            metadata={"plan": plan, "billing_cycle": cycle, "user_id": str(user["id"])},
            subscription_data={
                "metadata": {"plan": plan, "billing_cycle": cycle, "user_id": str(user["id"])}
            },
        )
        return {"checkout_url": session.url}
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key is invalid. Contact support.")
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(500, detail="Payment processing failed. Please try again.")
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(500, "Payment processing failed. Please try again.")


# ASYNC-SAFE
async def _resolve_user(obj):
    """The user a checkout belongs to: the id Primble put on it. Never an
    e-mail match - another product's checkout with the same e-mail is not ours
    (2 Nov 2026, H4)."""
    uid = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
    if not uid:
        return None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", uid)
    return dict(row)["id"] if row else None


async def _still_live(sub_id: str) -> bool:
    """Is the user's stored subscription still billing? Stripe out of reach =
    503, so Stripe re-delivers the event later - never a guess."""
    try:
        sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
    except Exception as ex:
        if is_missing_subscription(ex):
            return False
        logger.error(f"Stripe webhook: cannot check subscription {sub_id}: {type(ex).__name__} - 503, Stripe retries")
        raise HTTPException(503, "Payment provider unreachable - retry later")
    return field(sub, "status") in LIVE_SUB_STATUSES


async def _handle_overage_session(event_id: str, event_type: str, obj: dict) -> None:
    """The overage-pack checkout is retired (2 Nov 2026, M5). A paid pack that
    still arrives credits nothing by itself: it is logged at ERROR and audited
    for a person to credit or refund. One already applied is left alone."""
    metadata = obj.get("metadata") or {}
    uid = metadata.get("user_id") or obj.get("client_reference_id")
    sid = obj.get("id", "")
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
    applied = None
    try:
        async with get_pool().acquire() as conn:
            applied = await conn.fetchrow(
                "SELECT stripe_session_id FROM applied_overage_sessions WHERE stripe_session_id = $1", sid)
    except Exception:
        applied = None
    if applied:
        logger.info(f"checkout.session.completed: overage session {sid} was applied before - nothing to do")
        return
    logger.error(f"checkout.session.completed: paid overage pack {sid} (qty={metadata.get('qty')}) for user"
                 f" {uid} - the pack checkout is retired; a person must credit or refund it")
    if uid:
        await write_audit_log({"id": uid, "email": ""}, "payment.overage_pack_unapplied",
                              session_id=sid, form_name=str(metadata.get("qty", "")))


async def _handle_setup_session(event_id: str, event_type: str, obj: dict) -> None:
    """A setup-mode checkout saved a card: make it the default for the customer
    and its live subscriptions. Recorded first, so a re-delivery repeats
    nothing (2 Nov 2026, H2). Open invoices are never paid from here (H1) -
    the customer pays the open invoice in the billing portal."""
    customer_id = obj.get("customer")
    setup_intent_id = obj.get("setup_intent")
    if not customer_id or not setup_intent_id:
        return
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
    try:
        si = await asyncio.to_thread(stripe.SetupIntent.retrieve, setup_intent_id)
        pm = field(si, "payment_method")
        if not pm:
            return
        await asyncio.to_thread(
            stripe.Customer.modify, customer_id, invoice_settings={"default_payment_method": pm})
        logger.info(f"Set default payment method for {customer_id}")
        for sub in await list_all(stripe.Subscription.list, customer=customer_id, limit=10):
            if field(sub, "status") in ("canceled", "incomplete_expired"):
                continue
            await asyncio.to_thread(stripe.Subscription.modify, field(sub, "id"), default_payment_method=pm)
            logger.info(f"Updated subscription {field(sub, 'id')} payment method")
    except Exception as e:
        logger.warning(f"Could not set default payment method for {customer_id}: {e}")


async def _handle_subscription_checkout(event_id: str, event_type: str, obj: dict) -> None:
    metadata = obj.get("metadata") or {}
    tagged_id = obj.get("client_reference_id") or metadata.get("user_id")
    user_id = await _resolve_user(obj)
    sub_id = obj.get("subscription")
    plan = metadata.get("plan")
    cycle = metadata.get("billing_cycle") or "monthly"
    stripe_customer = obj.get("customer")
    if not (tagged_id and sub_id and plan in PLANS and cycle in PLANS[plan]):
        # Never a default plan for an untagged checkout (2 Nov 2026, H4).
        logger.warning(f"checkout.session.completed {event_id}: not a Primble subscription checkout"
                       f" (user={tagged_id!r} sub={sub_id!r} plan={plan!r}) - ignored")
        return
    invoice_id = obj.get("invoice")
    if not user_id:
        # The account was deleted while its checkout page was still open (they
        # live 24 h): the subscription is cancelled and refunded like an
        # accidental duplicate - it would otherwise bill nobody's account
        # (2 Nov 2026, L-2). A subscription that already ENDED while the
        # user's row CARRIED it (verify-upgrade granted it before this event
        # landed, then delete-account ended it) was a plan the user had:
        # nothing is refunded (3 Nov 2026, L-A). Ended but never carried - paid,
        # never granted, account deleted - is refunded as before (pass 2 #6).
        # Stripe out of reach = 503, nothing claimed.
        state = await _subscription_state(sub_id, event_id, retry_on_transient=True)
        if (state is not None and state.get("status") not in LIVE_SUB_STATUSES
                and await _plan_was_carried(tagged_id, sub_id)):
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    if not await _claim_event(conn, event_id, event_type):
                        return
            logger.warning(f"checkout.session.completed {event_id}: user {tagged_id} no longer exists and"
                           f" {sub_id} is already {state.get('status')} - a plan the account had, ended by"
                           f" its deletion; nothing refunded")
            await write_audit_log({"id": tagged_id, "email": ""}, "payment.deleted_account_checkout_not_refunded",
                                  session_id=sub_id, form_name=invoice_id)
            return
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                if not await _claim_event(conn, event_id, event_type):
                    return
                await _claim_key(conn, duplicate_key(tagged_id, sub_id, invoice_id), DUP_PENDING)
        logger.warning(f"checkout.session.completed: user {tagged_id} no longer exists -"
                       f" cancelling and refunding {sub_id}")
        await settle_duplicate_checkout({"id": tagged_id, "email": ""}, sub_id, invoice_id)
        return

    async with get_pool().acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT id, email, stripe_customer_id, stripe_subscription_id, subscription_tier, overage_rate"
            " FROM users WHERE id=$1", user_id)
    urow = dict(urow) if urow else {"id": user_id, "email": ""}
    existing = urow.get("stripe_subscription_id")
    # The row already carries THIS subscription: verify-upgrade (or a resync)
    # wrote the plan, its period and its months first. Its usage since then is
    # real - a late checkout event never resets it (3 Nov 2026, M-C).
    same_sub = bool(existing and existing == sub_id)
    # A checkout that completes while the user already has a different live
    # subscription (two tabs, an old checkout page) is an accidental second
    # plan: the existing plan is kept (2 Nov 2026, B1/H3). So is one that lands
    # on an enterprise plan, which Primble manages (L-5).
    duplicate = ((urow.get("subscription_tier") or "") == "enterprise"
                 or bool(existing and existing != sub_id and await _still_live(existing)))

    now = datetime.now(timezone.utc).isoformat()
    # The new plan's period, from the subscription itself (Q2).
    new_period_end = new_period_start = None
    if not duplicate:
        state = await _subscription_state(sub_id, event_id)
        if state is not None and state.get("status") not in LIVE_SUB_STATUSES:
            # The subscription ended before this event was handled (a refund +
            # cancel while the event was delayed): a paid tier on a dead plan
            # would never be taken back - no renewal, no event (3 Nov 2026, M-A).
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    if not await _claim_event(conn, event_id, event_type):
                        return
            logger.error(f"checkout.session.completed {event_id}: subscription {sub_id} of user {user_id} is"
                         f" {state.get('status')} in Stripe - no plan granted; a person should check it")
            await write_audit_log({"id": user_id, "email": urow.get("email", "")},
                                  "payment.checkout_subscription_not_live",
                                  session_id=sub_id, form_name=str(state.get("status")))
            return
        # The plan the subscription bills NOW (its price first - H-A): support
        # may have changed it before this event arrived. The session's own
        # metadata is the fallback when Stripe could not say.
        live_plan, live_cycle = (state or {}).get("plan"), (state or {}).get("cycle")
        if live_plan in PLANS and live_plan != "enterprise" and live_cycle in PLANS[live_plan]:
            if (live_plan, live_cycle) != (plan, cycle):
                logger.warning(f"checkout.session.completed {event_id}: {sub_id} bills {live_plan}/{live_cycle},"
                               f" the checkout said {plan}/{cycle} - the subscription's price decides")
            plan, cycle = live_plan, live_cycle
        new_period_end = _ts_to_dt((state or {}).get("period_end"))
        new_period_start = _ts_to_dt((state or {}).get("period_start"))
    cfg = PLANS[plan][cycle]
    replaced_key = None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
            if not duplicate and same_sub:
                # Only a missing customer id is filled in; the plan, usage,
                # period, months and payment state stay as written.
                await conn.execute(
                    "UPDATE users SET stripe_customer_id=COALESCE(stripe_customer_id, $1)"
                    " WHERE id=$2 AND stripe_subscription_id=$3",
                    stripe_customer, user_id, sub_id,
                )
            elif not duplicate:
                # Compare-and-set on the subscription read above: a second
                # checkout completing at the same moment cannot replace the first.
                status = await conn.execute(
                    """UPDATE users SET subscription_tier=$1, stripe_subscription_id=$2,
                        stripe_customer_id=COALESCE($8, stripe_customer_id),
                        packages_limit=$3, packages_used=0, billing_cycle=$4, billing_period_start=$5,
                        overage_rate=$6, payment_status='ok', payment_failed_at=NULL,
                        payment_email_sent_day=0, overage_packages_invoiced=0
                       WHERE id=$7 AND (stripe_subscription_id IS NULL OR stripe_subscription_id=$9)""",
                    plan, sub_id, cfg["packages"], cycle, now, cfg["overage_rate"], user_id,
                    stripe_customer, existing,
                )
                if int(str(status).split()[-1] or 0) == 0:
                    moved = await conn.fetchrow("SELECT stripe_subscription_id FROM users WHERE id=$1", user_id)
                    if (dict(moved) if moved else {}).get("stripe_subscription_id") == sub_id:
                        # verify-upgrade stored this subscription a moment ago (M-C).
                        same_sub = True
                    else:
                        duplicate = True
                else:
                    # A dead stored plan replaced: its unbilled extras are
                    # billed now - its late subscription.deleted finds no row
                    # carrying it (pass 2 #5).
                    if existing and existing != sub_id:
                        replaced_key = await _claim_replaced_plan_bill(
                            conn, urow, existing, urow.get("stripe_customer_id") or stripe_customer)
                    # A new plan: the old plan's period end is history (Q2).
                    await clear_period_end(conn, user_id)
                    end_iso = (new_period_end.isoformat() if new_period_end
                               else await sub_period_end(conn, sub_id))
                    if end_iso:
                        await record_period_end(conn, user_id, end_iso)
                    # An annual plan's usage months count from its start (3 Nov 2026).
                    await clear_usage_months(conn, user_id)
                    if cycle == "annual":
                        await record_usage_anchor(conn, user_id, (new_period_start.isoformat()
                                                                  if new_period_start else now))
            if duplicate:
                await _claim_key(conn, duplicate_key(user_id, sub_id, invoice_id), DUP_PENDING)

    if duplicate:
        logger.warning(f"checkout.session.completed: user {user_id} already has a live subscription -"
                       f" cancelling the new one {sub_id} and refunding it")
        await settle_duplicate_checkout(urow, sub_id, invoice_id)
        return
    if replaced_key:
        await _settle_replaced_plan_bill(replaced_key, existing)
    if same_sub:
        logger.info(f"checkout.session.completed {event_id}: {sub_id} already on user {user_id}'s row"
                    f" (verify-upgrade) - usage and period left as they are")
    await write_audit_log(
        {"id": user_id, "email": urow.get("email", ""), "stripe_customer_id": stripe_customer},
        "payment.subscription_created",
        session_id=sub_id,
    )
    await invalidate_user_cache(str(user_id))
    if cycle == "annual":
        # Its extra packages are billed monthly (Brent, 3 Nov 2026): Stripe
        # invoices the plan's pending items each month. A failure here is
        # retried by the daily job.
        await ensure_monthly_overage_billing(sub_id)


async def _plan_was_carried(user_id, sub_id) -> bool:
    """Did the user's row carry this subscription when it ended? Every path
    that ends a plan a row carries - delete-account, subscription.deleted, a
    replacement by a new plan - claims its final bill as
    final_overage:<user>:<subscription>:...; a plan the user never had has
    none (3 Nov 2026, pass 2 #6)."""
    prefix = f"{FINAL_PREFIX}{user_id}:"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT event_id FROM processed_webhook_events WHERE event_id LIKE $1",
                                prefix + "%")
    return any(dict(r)["event_id"][len(prefix):].split(":", 1)[0] == sub_id for r in rows)


async def _claim_replaced_plan_bill(conn, row: dict, old_sub, customer_id) -> "str | None":
    """A dead stored subscription is being replaced by a new plan (verify-upgrade,
    a checkout): its unbilled extra packages are owed, and its late
    customer.subscription.deleted will find no row carrying it (3 Nov 2026,
    pass 2 #5). The final bill is claimed in the caller's transaction (the key
    the delete handler would use - one claim, whoever comes first) and settled
    after the commit. Returns the claimed key, or None."""
    if not old_sub or not customer_id or not row:
        return None
    rate = int(row.get("overage_rate") or default_overage_rate_cents(row.get("subscription_tier") or ""))
    key = final_overage_key(row["id"], old_sub, customer_id, rate)
    claimed = await _claim_key(conn, key, FINAL_PENDING)
    # Units held while the dead plan was failing are never billed (pass 4 #3).
    await forgive_held_overage(conn, str(row["id"]))
    return key if claimed else None


async def _settle_replaced_plan_bill(key: str, old_sub) -> None:
    try:
        await settle_final_overage(key)
    except Exception as ex:
        logger.error(f"replaced plan {old_sub}: final overage not billed now ({ex}) - retried daily")


async def _subscription_state(sub_id: str, event_id: str, retry_on_transient: bool = False,
                              check_open: bool = False) -> "dict | None":
    """The subscription as Stripe has it now - status, cancel_at_period_end and
    its current period - or None when Stripe has no such subscription. A
    failure that may pass answers 503 when `retry_on_transient` (F1): the event
    is not claimed and nothing is spent, so Stripe sends it again."""
    try:
        return await asyncio.to_thread(subscription_status, sub_id, check_open)
    except Exception as ex:
        if retry_on_transient and is_transient(ex):
            logger.error(f"{event_id}: cannot ask Stripe about {sub_id} ({type(ex).__name__}) - 503,"
                         f" Stripe re-sends; nothing claimed")
            raise HTTPException(503, "Payment provider unreachable - retry later")
        logger.warning(f"{event_id}: cannot ask Stripe about {sub_id} ({type(ex).__name__})")
        return None


def _restore_status(state: "dict | None", sub_id: str, event_id: str) -> "str | None":
    """The status a failed user returns to, or None to keep the failure
    (2 Nov 2026, M-5 / L-6): only a subscription Stripe reports active or
    trialing clears it - paying one old invoice of an unpaid plan does not.
    Stripe out of reach = keep it; the daily job's Stripe check restores a
    paid-up user."""
    if state is None:
        logger.warning(f"invoice paid {event_id}: failure kept - the daily job checks {sub_id} again")
        return None
    if state.get("status") not in PAYING_SUB_STATUSES:
        logger.info(f"invoice paid {event_id}: subscription {sub_id} is {state.get('status')} - failure kept")
        return None
    if state.get("open_attempted"):
        # 3 Nov 2026: an annual plan stays active while a failed monthly
        # overage invoice is retried - not paid up until that invoice is.
        logger.info(f"invoice paid {event_id}: subscription {sub_id} still has a failed open invoice - failure kept")
        return None
    return "canceling" if state.get("cancel_at_period_end") else "ok"


async def _handle_invoice_paid(event_id: str, event_type: str, event_created, obj: dict) -> None:
    sub_id = _invoice_subscription(obj)
    if not sub_id:
        return
    invoice_id = obj.get("id")
    inv_created = _ts_to_dt(obj.get("created"))
    # L-7 / Q1: the plan's own invoice by Stripe's billing_reason. The webhook
    # embeds only the FIRST page of lines and Stripe lists pending items before
    # the plan line, so a missing plan line means "not a plan invoice" only on
    # a page known to be complete (support invoicing overage now).
    lines = obj.get("lines") or {}
    plan_line_seen = bool(_subscription_line_periods(obj))
    page_complete = bool(lines.get("data")) and not lines.get("has_more")
    renewal = (obj.get("billing_reason") in _PERIOD_REASONS
               and not (page_complete and not plan_line_seen))
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, payment_status, payment_failed_at, billing_period_start, subscription_tier,"
            " packages_limit, billing_cycle FROM users WHERE stripe_subscription_id=$1",
            sub_id,
        )
    row = dict(row) if row else None

    failing = bool(row and (row.get("payment_failed_at")
                            or (row.get("payment_status") or "ok") in FAILURE_STATUSES))
    stale_success = failing and _failed_before(row, event_created)
    state = None
    if renewal or (failing and not stale_success):
        # F1: a renewal and a failing user's payment need the subscription; a
        # Stripe failure that may pass answers 503 BEFORE anything is claimed.
        state = await _subscription_state(sub_id, event_id, retry_on_transient=True,
                                          check_open=failing and not stale_success)
    restore_to = None
    if failing:
        if stale_success:
            # M2: a success Stripe created before the current failure.
            logger.info(f"{event_type}: {event_id} predates the current failure of user {row['id']} - failure kept")
        else:
            restore_to = _restore_status(state, sub_id, event_id)

    # The new period: the plan line when the payload has it, else the
    # subscription's own current period - when it is the one this invoice
    # opened (a very late event must not take the period after it).
    period_from, period_end = _invoice_period_start(obj), _invoice_period_end(obj)
    if renewal and state and state.get("period_start") and (period_from is None or period_end is None):
        sub_start = _ts_to_dt(state["period_start"])
        anchor = inv_created or event_created
        if anchor is None or abs((sub_start - anchor).total_seconds()) <= 2 * 86400:
            period_from = period_from or sub_start
            period_end = period_end or _ts_to_dt(state.get("period_end"))
    period_from = period_from or inv_created or event_created

    now_dt = datetime.now(timezone.utc)
    # last_paid is stamped with Stripe's paid time, never the time we handled
    # it (L-C).
    paid_iso = _paid_time(obj, event_created, now_dt).isoformat()
    counted = None
    reset_usage = False
    placed = 0
    straddle = None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
            if not row:
                # The plan's first invoice is often handled BEFORE its
                # checkout.session.completed: no user carries the subscription
                # yet. Its period end is kept for the checkout (Q2).
                if renewal and period_end is not None:
                    await record_sub_period_end(conn, sub_id, period_end.isoformat())
                return
            # The user row's lock, taken FIRST and held to commit (3 Nov 2026,
            # pass 3 #1): the period is judged from the row as it is now, never
            # from the copy read before the Stripe calls - two renewals handled
            # at once would both see the old period, and the older one,
            # committing last, would rewind it. The counting path takes the
            # same lock, so a package counted at this moment lands either in a
            # recount or after it, never both or neither (L-3/L-4).
            locked = await conn.fetchrow(
                "UPDATE users SET packages_used = packages_used WHERE id=$1"
                " RETURNING billing_period_start, COALESCE(packages_used, 0) AS used,"
                " payment_status, payment_failed_at", row["id"])
            locked = dict(locked) if locked else {}
            used_at_lock = int(locked.get("used") or 0)
            # Still failing NOW, under the lock (pass 4 #4): another event may
            # have restored the user since the read above.
            failing_now = bool(locked.get("payment_failed_at")
                               or (locked.get("payment_status") or "ok") in FAILURE_STATUSES)
            # Any paid invoice of the plan is a payment: a failure Stripe made
            # before it was paid is stale (R2) - Stripe's paid time (L-C).
            await record_last_paid(conn, row["id"], paid_iso)
            # M2: an invoice older than the current period never resets the
            # usage. L-7: only the plan's own invoices start a period. "Older"
            # is the invoice's OWN period start against the stored one (3 Nov
            # 2026, pass 2 #2): two open renewals paid together after a long
            # failure each open their own period, in either order - the time an
            # invoice was created or paid says nothing about which period it is.
            stored_start = _safe_parse_dt(locked.get("billing_period_start"))
            newer = renewal and not (period_from is not None and stored_start is not None
                                     and period_from <= stored_start)
            # OLDER = a whole period that ends at or before the stored start
            # (pass 4 #1): a delayed twin of the CURRENT renewal, after a
            # mid-period tier change moved the stored start to the switch, is
            # neither newer nor older - it recounts nothing.
            older = (renewal and not newer and period_end is not None and stored_start is not None
                     and period_end <= stored_start)
            if renewal:
                # The new period's end, or - when nothing gives it - no stored
                # end at all: a stale one would defer the whole new period's
                # overage past the next recount (F1). An OLDER invoice never
                # moves the stored end back.
                if period_end is not None:
                    await record_period_end(conn, row["id"], period_end.isoformat(), only_later=not newer)
                elif newer:
                    await clear_period_end(conn, row["id"])
            reset_usage = newer
            # L1: invoice.paid and invoice.payment_succeeded of one invoice
            # reset the usage once.
            if reset_usage and invoice_id:
                reset_usage = await _claim_key(conn, f"invoice_reset:{invoice_id}", "invoice_reset")
            # Still failing after this invoice (the plan is not paying yet -
            # Stripe may update it a moment later): overage found now is HELD,
            # owed, billed by whichever restore comes next (F1); otherwise it is
            # recorded PENDING right here, in this transaction, and billed after
            # the commit - a failure there leaves it to the daily retry, never
            # lost (pass 3 #4).
            hold = failing_now and not restore_to
            _limit, hard_limit = allowance_for(row)
            if reset_usage:
                counted = []
                if period_from is not None:
                    try:
                        async with conn.transaction():
                            counted = await packages_counted_since(str(row["id"]), period_from.isoformat(),
                                                                   conn=conn)
                            # A package counted after the period's end but billed
                            # as the OLD period's overage (its end was not known
                            # yet - the first renewal after 2 Nov 2026) stays in
                            # the old period: never counted again in the new one.
                            billed = await conn.fetch(
                                "SELECT event_id FROM processed_webhook_events WHERE event_id LIKE $1"
                                " AND event_type IN ('overage_billed','overage_pending','overage_billing',"
                                "'overage_held')",
                                f"overage_unit:{row['id']}:%")
                            old_period = {dict(b)["event_id"].split(":", 2)[2] for b in billed}
                            counted = [c for c in counted if c[0] not in old_period]
                    except Exception as ex:
                        logger.warning(f"invoice.paid: could not recount the period for user {row['id']}:"
                                       f" {type(ex).__name__}")
                        counted = []
                # M6: pending overage is billed by its retry, never forgiven.
                # The period starts where the invoice's own period starts
                # (pass 2 #2) - the paid time lives in last_paid (L-C).
                await conn.execute(
                    "UPDATE users SET packages_used = $1 + (COALESCE(packages_used, 0) - $2),"
                    " billing_period_start=$3, overage_packages_invoiced=0 WHERE id=$4",
                    len(counted), used_at_lock, (period_from.isoformat() if period_from else paid_iso),
                    row["id"],
                )
                if (row.get("billing_cycle") or "") == "annual" and period_from is not None:
                    # The yearly renewal opens month 0 of the new year (3 Nov 2026).
                    await record_usage_anchor(conn, row["id"], period_from.isoformat())
                # Extras come only from THIS invoice's period: an older renewal
                # paid first counts everything since its start, but packages of
                # the periods after its end are theirs (pass 4 #2).
                in_period = ([c for c in counted if (_safe_parse_dt(c[1]) or period_end) < period_end]
                             if period_end is not None else counted)
                placed += await place_period_overage(conn, str(row["id"]), in_period, hard_limit, hold=hold)
            elif (renewal and not newer and not older and period_from is not None and stored_start is not None
                  and period_from < stored_start):
                # A renewal STRADDLING the stored start: a tier sync moved it
                # inside this period, so [its start, the switch) belonged to the
                # plan(s) before. Nothing is billed automatically (3 Nov 2026,
                # pass 6 - the owner's final call): annual months, several
                # switches and the old plans' own rates make any recount a guess
                # that can bill inside an allowance. A person is told instead.
                window = []
                try:
                    async with conn.transaction():
                        since = await packages_counted_since(str(row["id"]), period_from.isoformat(), conn=conn)
                        window = [c for c in since if (_safe_parse_dt(c[1]) or stored_start) < stored_start]
                except Exception as ex:
                    logger.warning(f"invoice.paid: could not count before the switch for user {row['id']}:"
                                   f" {type(ex).__name__}")
                straddle = {"from": period_from, "to": stored_start, "packages": len(window),
                            "plans": await plan_switches(conn, row["id"], period_from.isoformat(),
                                                         stored_start.isoformat())}
            elif older and (row.get("billing_cycle") or "") != "annual":
                # An OLDER renewal paid after a newer one (pass 3 #2): its period
                # [start, end) was never recounted - the packages above its
                # allowance were "not billable" while the user was failing and
                # are in no ledger row. Recounted now, within its own window,
                # placed like a reset's (held / pending); never more new units
                # than the window's extras minus those the ledger already has.
                window = []
                try:
                    async with conn.transaction():
                        since = await packages_counted_since(str(row["id"]), period_from.isoformat(), conn=conn)
                        bound = min(period_end, stored_start)
                        window = [c for c in since if (_safe_parse_dt(c[1]) or bound) < bound]
                except Exception as ex:
                    logger.warning(f"invoice.paid: could not recount the older period for user {row['id']}:"
                                   f" {type(ex).__name__}")
                    window = []
                placed += await place_period_overage(conn, str(row["id"]), window, hard_limit, hold=hold)
            if restore_to:
                await conn.execute(
                    "UPDATE users SET payment_status=$1, payment_failed_at=NULL, payment_email_sent_day=0"
                    " WHERE id=$2",
                    restore_to, row["id"],
                )
                # A restore makes held units billable: recorded PENDING in this
                # transaction, so a failed bill after the commit is retried by
                # the daily job (pass 3 #4).
                await release_held_overage(conn, str(row["id"]))
    await invalidate_user_cache(str(row["id"]))
    if straddle:
        now_plan = f"{row.get('subscription_tier') or '?'}/{row.get('billing_cycle') or 'monthly'}"
        switches = "; ".join(f"{label} until {at}" for at, label in straddle["plans"]) or "(not on record)"
        window = f"[{straddle['from'].isoformat()}, {straddle['to'].isoformat()})"
        logger.error(f"invoice.paid {event_id}: renewal of user {row['id']} straddles a plan switch - window"
                     f" {window}, {straddle['packages']} package(s), plans before: {switches}, now {now_plan};"
                     f" its overage is NOT billed automatically - a person must bill it")
        await write_audit_log({"id": row["id"], "email": ""}, "payment.overage_before_switch_manual",
                              session_id=invoice_id, form_name=str(straddle["packages"]))
        await send_billing_alert(
            f"straddle:{row['id']}:{invoice_id}", f"BILL BY HAND - overage before a plan switch, invoice {invoice_id}",
            "A renewal was paid for a period in which the plan was switched. Packages counted before the\n"
            "switch belong to the plan(s) before it; Primble does not bill them automatically. Check them\n"
            "against each old plan's monthly allowance (+5% buffer) and bill any extra packages at that\n"
            "plan's own rate in the Stripe dashboard.\n\n"
            f"User id: {row['id']}\nInvoice: {invoice_id}\nWindow: {window}\n"
            f"Packages in the window: {straddle['packages']}\nPlans before the switch: {switches}\n"
            f"Plan now: {now_plan}\n")
    try:
        if restore_to or (placed and not hold):
            await retry_pending_overage(str(row["id"]))
    except Exception as ex:
        logger.error(f"invoice.paid: overage of user {row['id']} not billed now ({ex}) - pending, retried daily")


async def _handle_payment_failed(event_id: str, event_type: str, event_created, obj: dict) -> None:
    sub_id = _invoice_subscription(obj)
    customer_id_from_invoice = obj.get("customer")
    logger.info(f"invoice.payment_failed: sub_id={sub_id!r} customer={customer_id_from_invoice!r} event={event_id}")

    if not sub_id:
        logger.warning(f"invoice.payment_failed: no subscription ID found in event {event_id} — cannot update user")
        return
    failed_at = _failure_time(event_created, datetime.now(timezone.utc))
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
            row = await conn.fetchrow(
                "SELECT id, email, full_name, stripe_customer_id, payment_failed_at, "
                "billing_period_start, "
                "COALESCE(payment_email_sent_day, 0) AS payment_email_sent_day "
                "FROM users WHERE stripe_subscription_id = $1",
                sub_id,
            )
            if row:
                row = {**dict(row), "last_paid_at": await last_paid_at(conn, dict(row)["id"])}
            if row and _paid_after(row, event_created):
                logger.info(f"invoice.payment_failed: stale event {event_id} - user {row['id']} paid after it, skipped")
                return
            if row:
                await conn.execute(_MARK_FAILED + " WHERE id=$2", failed_at, dict(row)["id"])
            # Fallback: look up by stripe_customer_id if sub_id not stored yet
            if not row and customer_id_from_invoice:
                logger.warning(f"invoice.payment_failed: no user found by sub_id={sub_id!r}, trying customer_id={customer_id_from_invoice!r}")
                row = await conn.fetchrow(
                    "SELECT id, email, full_name, stripe_customer_id, stripe_subscription_id, payment_failed_at, "
                    "billing_period_start, subscription_tier, "
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
                    elif not _current_sub and (dict(row).get("subscription_tier") or "free") in ("free", "enterprise"):
                        # No Stripe plan on file: the invoice belongs to an ended
                        # subscription (or a checkout that never completed).
                        # Never lock a free account over it - nor an enterprise
                        # account whose old Stripe plan ended (L-B keeps the
                        # tier with no subscription; Primble bills it): re-linking
                        # the dead plan would walk it into the lock (3 Nov 2026,
                        # pass 2 #3).
                        logger.info(
                            "invoice.payment_failed: skipping - user %s (%s) has no Stripe plan on file, sub=%s",
                            dict(row)["id"], dict(row).get("subscription_tier") or "free", sub_id,
                        )
                        row = None
                    elif _paid_after({**dict(row), "last_paid_at": await last_paid_at(conn, dict(row)["id"])},
                                     event_created):
                        logger.info(f"invoice.payment_failed: stale event {event_id} - user {dict(row)['id']} paid after it, skipped")
                        row = None
                    else:
                        await conn.execute(
                            _MARK_FAILED + ", stripe_subscription_id=$2 WHERE id=$3",
                            failed_at, sub_id, dict(row)["id"],
                        )

    if not row:
        logger.error(f"invoice.payment_failed: no user found for sub_id={sub_id!r} customer={customer_id_from_invoice!r} — DB NOT updated, email NOT sent")
        return
    row = dict(row)
    await write_audit_log(
        {"id": row["id"], "email": row["email"], "stripe_customer_id": row.get("stripe_customer_id", "")},
        "payment.failed",
        session_id=sub_id,
    )
    await invalidate_user_cache(str(row["id"]))
    prev = int(row.get("payment_email_sent_day") or 0)
    logger.info(f"invoice.payment_failed: user={row['id']} payment_email_sent_day={prev}")
    if prev >= 1:
        logger.info(f"invoice.payment_failed: day-1 email already sent for user={row['id']}, skipping")
        return
    # The day-0 e-mail is claimed before it is sent, so two failure events at
    # once send it once; a failed send gives the claim back (M8); a crash
    # between the claim and the send is caught by the daily job (L-9).
    async with get_pool().acquire() as conn:
        fresh = await conn.fetchrow("SELECT payment_failed_at FROM users WHERE id=$1", row["id"])
    row["payment_failed_at"] = (dict(fresh) if fresh else {}).get("payment_failed_at")
    await send_claimed_payment_email(get_pool, _send_payment_failed_email, row, 1, prev)


async def _handle_subscription_deleted(event_id: str, event_type: str, obj: dict) -> None:
    """The plan a user HAS (their stored subscription) ended: downgrade, and
    bill its unbilled extra packages (C1). Judged by the stored subscription
    alone (Q5): another live subscription of the user is an accidental second
    plan whose refund is pending - it never keeps a paid tier alive; it is
    cancelled and refunded by its own machinery. An ended subscription no user
    carries (a cancelled duplicate) changes nothing."""
    sub_id = obj.get("id")
    customer_id = obj.get("customer")
    if not sub_id:
        return
    final_key = None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
            cancelled_row = await conn.fetchrow(
                "SELECT id, email, stripe_customer_id, subscription_tier, overage_rate"
                " FROM users WHERE stripe_subscription_id = $1",
                sub_id,
            )
            # An enterprise plan is Primble's, not Stripe's (3 Nov 2026, L-B):
            # its old Stripe subscription ending drops only the link to it (and
            # that plan's failure state, which no Stripe plan can clear any
            # more) - never the tier, its allowance or its usage.
            await conn.execute(
                "UPDATE users SET stripe_subscription_id=NULL, payment_status='ok', payment_failed_at=NULL,"
                " payment_email_sent_day=0"
                " WHERE stripe_subscription_id=$1 AND subscription_tier='enterprise'",
                sub_id,
            )
            await conn.execute(
                "UPDATE users SET subscription_tier='free', packages_limit=0, packages_used=0,"
                " payment_status='ok', payment_failed_at=NULL, stripe_subscription_id=NULL,"
                " payment_email_sent_day=0,"
                " overage_packages_pending=0, overage_packages_invoiced=0"
                " WHERE stripe_subscription_id=$1 AND COALESCE(subscription_tier, 'free') <> 'enterprise'",
                sub_id,
            )
            if cancelled_row:
                await clear_period_end(conn, dict(cancelled_row)["id"])     # Q2
                await clear_usage_months(conn, dict(cancelled_row)["id"])
            # C1: the plan the user actually had has ended - its unbilled extra
            # packages are owed and no renewal invoice will ever carry them.
            # Claimed here, in the event's transaction (a re-delivery finds it
            # taken); billed after the commit.
            if cancelled_row and (cancelled_row.get("stripe_customer_id") or customer_id):
                cr = dict(cancelled_row)
                rate = int(cr.get("overage_rate") or default_overage_rate_cents(cr.get("subscription_tier") or ""))
                key = final_overage_key(cr["id"], sub_id, cr.get("stripe_customer_id") or customer_id, rate)
                if await _claim_key(conn, key, FINAL_PENDING):
                    final_key = key
                # Held units of the plan that ended are never billed (pass 4 #3).
                await forgive_held_overage(conn, cr["id"])
    if cancelled_row:
        cancelled_row = dict(cancelled_row)
        await write_audit_log(
            {"id": cancelled_row["id"], "email": cancelled_row["email"], "stripe_customer_id": cancelled_row.get("stripe_customer_id", "")},
            "payment.subscription_cancelled",
            session_id=sub_id,
        )
        await invalidate_user_cache(str(cancelled_row["id"]))
    if cancelled_row and (cancelled_row.get("subscription_tier") or "") == "enterprise":
        logger.warning(f"Subscription deleted: {sub_id} was an enterprise account's old Stripe plan -"
                       f" user {cancelled_row['id']} stays enterprise")
    else:
        logger.info(f"Subscription deleted: user downgraded to free for sub {sub_id}")
    if final_key:
        try:
            await settle_final_overage(final_key)
        except Exception as ex:
            logger.error(f"subscription.deleted: final overage of {sub_id} not billed now ({ex}) - retried daily")


async def _handle_subscription_updated(event_id: str, event_type: str, event_created, obj: dict) -> None:
    sub_id = obj.get("id")
    # `cancel_at_period_end` OR a `cancel_at` date: the billing portal sets the
    # date (LT-1) - the name is kept for the branches below.
    cancel_at_period_end = is_ending(obj)
    status = obj.get("status", "")
    if not sub_id:
        return
    ev_plan, ev_cycle = subscription_plan(obj)
    if ev_plan is None and off_cycle_price(obj):
        # Billed every N > 1 months / years: nothing syncs, a person decides
        # (3 Nov 2026, pass 3 #3). One alert per subscription.
        try:
            await send_billing_alert(
                f"off_cycle_price:{sub_id}", f"CHECK PLAN - subscription {sub_id} bills on an unsupported cycle",
                "A Primble subscription was moved onto a price billed every 3, 12 or N months. Primble meters\n"
                "plans billed every one month or one year only, so the plan was NOT synced: the account keeps\n"
                "its current tier, allowance and cycle. Move the subscription onto a monthly or annual price\n"
                "(the catalogue's Primble prices) in the Stripe dashboard.\n\n"
                f"Subscription: {sub_id}\nEvent: {event_id}\n")
        except Exception as ex:
            logger.error(f"subscription.updated {event_id}: off-cycle alert not sent ({type(ex).__name__})")
    async with get_pool().acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT id, subscription_tier, billing_cycle, payment_status, payment_failed_at"
            " FROM users WHERE stripe_subscription_id=$1", sub_id)
    urow = dict(urow) if urow else None
    row_tier = (urow or {}).get("subscription_tier") or ""
    row_cycle = (urow or {}).get("billing_cycle") or "monthly"
    failing = bool(urow and (urow.get("payment_failed_at")
                             or (urow.get("payment_status") or "ok") in FAILURE_STATUSES))
    # A plan change - the tier OR the cycle (support switches Professional
    # monthly <-> annual in Stripe, 3 Nov 2026) - is taken from the
    # subscription as Stripe has it NOW, never from this payload: Stripe does
    # not deliver events in order. Never on enterprise.
    live = None
    if (status == "active" and urow and ev_plan in PLANS and ev_plan != "enterprise"
            and row_tier != "enterprise" and (row_tier != ev_plan or row_cycle != ev_cycle)):
        live = await _subscription_state(sub_id, event_id, retry_on_transient=True)
        if not (live and live.get("plan") in PLANS and live.get("plan") != "enterprise"
                and live.get("status") in ("active", "trialing", "past_due")
                and (live["plan"] != row_tier or (live.get("cycle") or "monthly") != row_cycle)):
            live = None
    # "active" restores a failing user only when the plan is paid up - active
    # AND no open invoice already tried (3 Nov 2026): a card change or our own
    # interval modify also says "active" while a failed overage invoice is
    # being retried. Stripe out of reach = keep the failure.
    paid_up = False
    if (status == "active" and not cancel_at_period_end and failing
            and not _failed_before(urow, event_created)):
        try:
            paid_up = bool((await asyncio.to_thread(subscription_payment_state, sub_id)).get("paid"))
        except Exception as ex:
            logger.warning(f"subscription.updated {event_id}: cannot ask Stripe about {sub_id}"
                           f" ({type(ex).__name__}) - failure kept")
    restored_user = None
    synced = None
    now_dt = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
            if live:
                new_plan, new_cycle = live["plan"], live.get("cycle") or "monthly"
                cfg = PLANS[new_plan].get(new_cycle) or PLANS[new_plan]["monthly"]
                p_start, p_end = _ts_to_dt(live.get("period_start")), _ts_to_dt(live.get("period_end"))
                # The new plan starts at the switch. A cycle change opens a new
                # Stripe period at that moment (an interval change resets the
                # billing anchor); a tier change keeps the period and starts a
                # fresh allowance when it happened. Packages counted from then
                # on are the new plan's; earlier ones stay with the old plan
                # (their overage, billed or held, stays as it was).
                switched = event_created if (event_created and event_created <= now_dt) else now_dt
                if new_cycle != row_cycle and p_start:
                    since = p_start
                else:
                    since = max(switched, p_start) if p_start else switched
                await conn.execute("UPDATE users SET packages_used = packages_used WHERE id=$1", urow["id"])
                # The plan before the switch, named in the alert a straddling
                # renewal raises for a person (pass 5 #2, pass 6).
                await record_plan_switch(conn, urow["id"], since.isoformat(), row_tier, row_cycle)
                counted = []
                try:
                    async with conn.transaction():
                        counted = await recount_period(conn, urow["id"], since.isoformat())
                except Exception as ex:
                    logger.warning(f"subscription.updated: could not recount user {urow['id']}: {type(ex).__name__}")
                await conn.execute(
                    """UPDATE users SET subscription_tier=$1, billing_cycle=$2,
                        packages_limit=$3, overage_rate=$4, packages_used=$5,
                        billing_period_start=$6, overage_packages_invoiced=0
                       WHERE id=$7 AND subscription_tier != 'enterprise'""",
                    new_plan, new_cycle, cfg["packages"], cfg["overage_rate"], len(counted),
                    since.isoformat(), urow["id"],
                )
                await start_plan_months(conn, urow["id"], new_cycle, since.isoformat(),
                                        p_end.isoformat() if p_end else None)
                if new_cycle == "annual":
                    # The count is the CURRENT usage month's at once - a period
                    # that began months ago (a row whose stored cycle was wrong)
                    # never shows the whole year's packages until the next roll.
                    fresh = await conn.fetchrow("SELECT * FROM users WHERE id=$1", urow["id"])
                    if fresh:
                        await roll_usage_month(conn, dict(fresh))
                synced = (row_cycle, new_cycle)
                logger.info(f"subscription.updated: synced plan={new_plan} cycle={new_cycle} for sub {sub_id}"
                            f" ({len(counted)} package(s) already in the new plan's period)")
            if cancel_at_period_end:
                await conn.execute(
                    "UPDATE users SET payment_status='canceling'"
                    " WHERE stripe_subscription_id=$1"
                    " AND payment_status NOT IN ('failed','soft_locked','suspended','archived')",
                    sub_id,
                )
            elif status == "active" and not cancel_at_period_end:
                if urow and _failed_before(urow, event_created):
                    # M2: an "active" Stripe made before the current failure.
                    logger.info(f"subscription.updated: stale active {event_id} for sub {sub_id} - failure kept")
                elif failing and not paid_up:
                    logger.info(f"subscription.updated: {sub_id} active but not paid up - failure kept")
                else:
                    # 'archived' too (2 Nov 2026, L-1): paying restores every stage.
                    restored = await conn.execute(
                        "UPDATE users SET payment_status='ok', payment_failed_at=NULL,"
                        " payment_email_sent_day=0"
                        " WHERE stripe_subscription_id=$1"
                        " AND payment_status IN ('canceling','failed','soft_locked','suspended','archived')",
                        sub_id,
                    )
                    restored_user = bool(int(str(restored).split()[-1] or 0)) and urow
                    if restored_user and failing:
                        # Stripe's time for the "active", never ours (L-C).
                        await record_last_paid(conn, urow["id"], _paid_time({}, event_created, now_dt).isoformat())
                    if restored_user:
                        # Held units become pending in this transaction (pass 3 #4).
                        await release_held_overage(conn, str(urow["id"]))
            elif status == "past_due":
                pd_row = await conn.fetchrow(
                    "SELECT id, billing_period_start FROM users WHERE stripe_subscription_id=$1", sub_id
                )
                if pd_row:
                    pd_row = {**dict(pd_row), "last_paid_at": await last_paid_at(conn, dict(pd_row)["id"])}
                if pd_row and _paid_after(pd_row, event_created):
                    logger.info(f"subscription.updated: stale past_due {event_id} for sub {sub_id}, skipped")
                else:
                    await conn.execute(
                        "UPDATE users SET payment_status='failed',"
                        " payment_failed_at=COALESCE(payment_failed_at,$1)"
                        " WHERE stripe_subscription_id=$2"
                        " AND payment_status NOT IN ('soft_locked','suspended','archived')",
                        _failure_time(event_created, datetime.now(timezone.utc)), sub_id,
                    )
            affected = await conn.fetchrow(
                "SELECT id FROM users WHERE stripe_subscription_id=$1", sub_id
            )
    if affected:
        await invalidate_user_cache(str(dict(affected)["id"]))
    if synced:
        was, now_cycle = synced
        if now_cycle == "annual":
            # A plan switched to annual bills its extra packages monthly; a
            # failure here is retried by the daily job.
            await ensure_monthly_overage_billing(sub_id, key_suffix=event_id)
        elif was == "annual":
            await clear_monthly_overage_billing(sub_id, event_id)
    if restored_user:
        try:
            await retry_pending_overage(str(dict(restored_user)["id"]))       # F1, pass 3 #4
        except Exception as ex:
            logger.error(f"subscription.updated: held overage not billed for sub {sub_id}: {ex}")


def _money(amount, currency) -> str:
    try:
        cents = int(amount or 0)
    except (TypeError, ValueError):
        return f"{amount} {currency or ''}".strip()
    cur = (currency or "usd").upper()
    return f"${cents / 100:,.2f}" if cur == "USD" else f"{cents / 100:,.2f} {cur}"


async def _dispute_account(dispute: dict) -> dict:
    """Whose payment is disputed: the charge's customer -> the user row. Best
    effort - Stripe or the database out of reach still leaves the alert."""
    charge_id = field(dispute, "charge")
    charge_id = charge_id if isinstance(charge_id, str) else field(charge_id, "id")
    out = {"charge": charge_id, "customer": None, "user_id": None, "email": None,
           "subscription": None, "tier": None}
    customer = None
    if charge_id:
        try:
            charge = await asyncio.to_thread(stripe.Charge.retrieve, charge_id)
            customer = field(charge, "customer")
            customer = customer if isinstance(customer, str) or customer is None else field(customer, "id")
        except Exception as ex:
            logger.warning(f"dispute {field(dispute, 'id')}: charge {charge_id} not read ({type(ex).__name__})")
    out["customer"] = customer
    if customer:
        try:
            async with get_pool().acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, email, stripe_subscription_id, subscription_tier FROM users"
                    " WHERE stripe_customer_id=$1", customer)
            if row:
                row = dict(row)
                out.update(user_id=row["id"], email=row.get("email"),
                           subscription=row.get("stripe_subscription_id"), tier=row.get("subscription_tier"))
        except Exception as ex:
            logger.warning(f"dispute {field(dispute, 'id')}: account not looked up ({type(ex).__name__})")
    return out


async def _handle_dispute(event_id: str, event_type: str, obj: dict) -> None:
    """A chargeback (3 Nov 2026, M-B). Nothing is cancelled or locked here -
    whether a disputed account keeps its plan is the owner's / Brent's call.
    Opened: ERROR log, audit row, one e-mail to the admins. Closed: the
    outcome is logged and audited."""
    dispute_id = obj.get("id") or ""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if not await _claim_event(conn, event_id, event_type):
                return
    acct = await _dispute_account(obj)
    amount = _money(obj.get("amount"), obj.get("currency"))
    reason = obj.get("reason") or "unknown"
    status = obj.get("status") or "unknown"
    pi = obj.get("payment_intent")
    pi = pi if isinstance(pi, str) or pi is None else field(pi, "id")
    who = acct["user_id"] or "unknown"
    ids = (f"dispute={dispute_id} charge={acct['charge']} payment_intent={pi} customer={acct['customer']}"
           f" subscription={acct['subscription']}")
    if event_type == "charge.dispute.created":
        due_by = _ts_to_dt(((obj.get("evidence_details") or {}).get("due_by")))
        logger.error(f"DISPUTE OPENED: {amount} by user {who} (reason {reason}) {ids} - nothing cancelled or"
                     f" locked automatically; the owner / Brent decide; respond in the Stripe dashboard"
                     f"{' by ' + due_by.isoformat() if due_by else ''}")
        await write_audit_log({"id": who, "email": acct["email"] or ""}, "payment.dispute_opened",
                              session_id=dispute_id, form_name=acct["charge"])
        await notify_admins(
            f"Stripe dispute opened - {amount} ({dispute_id})",
            "A customer disputed a Primble payment (a chargeback). Nothing was cancelled or locked\n"
            "automatically: whether the account keeps its plan is your decision. Respond to the\n"
            "dispute in the Stripe dashboard before the evidence deadline.\n\n"
            f"Account e-mail: {acct['email'] or '(not found)'}\n"
            f"User id: {who}\nPlan: {acct['tier'] or '(unknown)'}\n"
            f"Amount: {amount}\nReason: {reason}\nStatus: {status}\n"
            f"Evidence due by: {due_by.isoformat() if due_by else '(not given)'}\n\n"
            f"Dispute: {dispute_id}\nCharge: {acct['charge'] or '(none)'}\n"
            f"Payment intent: {pi or '(none)'}\nCustomer: {acct['customer'] or '(unknown)'}\n"
            f"Subscription: {acct['subscription'] or '(none)'}\n")
        return
    log = logger.error if status == "lost" else logger.warning
    log(f"DISPUTE CLOSED: {status} - {amount} by user {who} (reason {reason}) {ids} - the plan was not"
        f" changed automatically")
    await write_audit_log({"id": who, "email": acct["email"] or ""}, "payment.dispute_closed",
                          session_id=dispute_id, form_name=status)


# ASYNC-SAFE
@router.post("/webhook")
async def stripe_webhook(request: Request):
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
    event_created = _event_created_at(event)
    obj = (event.get("data") or {}).get("object") or {}
    logger.info(f"Stripe webhook: {event_type} ({event_id})")

    # Every branch records the event BEFORE any Stripe side effect, so a
    # re-delivered event never repeats one (2 Nov 2026, H2).
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") == "unpaid":
            # A payment that settles later (a bank debit) is not money yet: nothing is given until Stripe confirms
            # it with checkout.session.async_payment_succeeded, which comes back through this same branch
            # (3 Nov 2026). Cards and wallets are paid when Checkout completes, so their flow is unchanged.
            logger.warning(f"{event_type} {event_id}: payment not confirmed yet (payment_status=unpaid) -"
                           " nothing given; waiting for checkout.session.async_payment_succeeded")
            return {"received": True}
        if (obj.get("metadata") or {}).get("type") == "overage":
            await _handle_overage_session(event_id, event_type, obj)
        elif obj.get("mode") == "setup":
            await _handle_setup_session(event_id, event_type, obj)
        elif obj.get("mode") == "subscription":
            await _handle_subscription_checkout(event_id, event_type, obj)
    elif event_type == "checkout.session.async_payment_failed":
        logger.warning(f"checkout.session.async_payment_failed {event_id}: the delayed payment failed -"
                       " nothing was given")
    elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
        await _handle_invoice_paid(event_id, event_type, event_created, obj)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(event_id, event_type, event_created, obj)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(event_id, event_type, obj)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(event_id, event_type, event_created, obj)
    elif event_type in ("charge.dispute.created", "charge.dispute.closed"):
        # The live webhook endpoint must subscribe to both (owner action).
        await _handle_dispute(event_id, event_type, obj)

    return {"received": True}


# ASYNC-SAFE — called by Render Cron Job (or any external cron) as a fallback
# when APScheduler doesn't fire (e.g. free-tier sleep, worker restart).
# Protect with LIFECYCLE_TRIGGER_SECRET env var set in Render dashboard. The
# lifecycle itself runs once per day whoever calls it (2 Nov 2026, M8).
@router.post("/trigger-lifecycle")
async def trigger_lifecycle(request: Request):
    secret   = request.headers.get("x-lifecycle-secret", "")
    expected = os.getenv("LIFECYCLE_TRIGGER_SECRET", "")
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(401, "Unauthorized")
    from services.scheduler_service import run_daily_payment_lifecycle
    await run_daily_payment_lifecycle()
    return {"triggered": True}


# ASYNC-SAFE
@router.post("/verify-upgrade")
async def verify_upgrade(current_user: dict = Depends(get_current_user)):
    """After a checkout, before its webhook lands: sync a NEW plan from Stripe.

    2 Nov 2026 (M1/L7/H4): it only ever upgrades - from a subscription tagged
    with this user's id, in active / trialing. It never downgrades, never clears
    the stored subscription, never replaces a live one (the webhook decides an
    accidental second plan), and leaves an enterprise account without a Stripe
    subscription alone."""
    await check_verify_upgrade_rate_limit(str(current_user["id"]))
    user_id = current_user.get("id")
    tier    = current_user.get("subscription_tier") or "free"
    stored  = current_user.get("stripe_subscription_id")
    if tier == "enterprise":
        # Primble manages an enterprise plan - a stored subscription, live or
        # not, never re-syncs it (L-5 / Q8).
        return {"subscription_tier": tier, "upgraded": False, "reason": "enterprise"}
    try:
        customer_id = current_user.get("stripe_customer_id")
        customers = []
        if customer_id:
            try:
                customers = [await asyncio.to_thread(stripe.Customer.retrieve, customer_id)]
            except Exception as ex:
                if not is_missing_customer(ex):
                    raise
                customers = []
        if not customers:
            customers = await primble_customers_by_email(current_user)
        if not customers:
            return {"subscription_tier": tier, "upgraded": False, "reason": "no_stripe_customer"}

        candidates = []
        for customer in customers:
            for sub in await list_all(stripe.Subscription.list, customer=field(customer, "id"),
                                      status="all", limit=20):
                if (field(sub, "status") in PAYING_SUB_STATUSES
                        and belongs_to_user(sub, user_id, customer=customer)):
                    candidates.append((customer, sub))
        if not candidates:
            return {"subscription_tier": tier, "upgraded": False, "reason": "no_active_subscription"}
        if stored and any(field(s, "id") == stored for _c, s in candidates):
            return {"subscription_tier": tier, "upgraded": tier != "free", "reason": "already_synced"}
        if stored and await _stored_is_live(stored):
            return {"subscription_tier": tier, "upgraded": False, "reason": "existing_subscription"}

        customer, sub = max(candidates, key=lambda cs: int(field(cs[1], "created") or 0))
        sub_id = field(sub, "id")
        plan, cycle = subscription_plan(sub)
        if not plan:
            logger.warning(f"verify-upgrade: subscription {sub_id} of user {user_id} names no known plan - not synced")
            return {"subscription_tier": tier, "upgraded": False, "reason": "unknown_plan"}
        if not await _first_payment_settled(sub_id):
            # A payment method that settles later (a bank debit) leaves the
            # subscription "active" before the money is there (3 Nov 2026,
            # L-F): the checkout webhook grants it once Stripe confirms it.
            logger.info(f"verify-upgrade: {sub_id} of user {user_id} - its latest invoice is not paid yet,"
                        f" not synced")
            return {"subscription_tier": tier, "upgraded": False, "reason": "payment_pending"}
        cfg = PLANS[plan][cycle]
        now = datetime.now(timezone.utc).isoformat()
        start_iso, end_iso = _period_isos(sub)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    """UPDATE users SET subscription_tier=$1, stripe_subscription_id=$2,
                        stripe_customer_id=$3, packages_limit=$4, billing_cycle=$5,
                        billing_period_start=$6, overage_rate=$7,
                        payment_status='ok', payment_failed_at=NULL,
                        payment_email_sent_day=0
                       WHERE id=$8 AND (stripe_subscription_id IS NULL OR stripe_subscription_id=$9)""",
                    plan, sub_id, field(customer, "id"), cfg["packages"], cycle,
                    now, cfg["overage_rate"], user_id, stored,
                )
                synced = int(str(status).split()[-1] or 0) > 0
                replaced_key = None
                if synced:
                    if stored and stored != sub_id:
                        # The dead plan it replaced bills its extras (pass 2 #5)
                        # and forgives its held units - BEFORE the new plan's
                        # usage is adopted (pass 5 #1).
                        replaced_key = await _claim_replaced_plan_bill(
                            conn, current_user, stored,
                            current_user.get("stripe_customer_id") or field(customer, "id"))
                    # The plan's months and period end, as the checkout webhook
                    # would leave them (3 Nov 2026) - it may never arrive.
                    await adopt_plan_usage(conn, user_id, cycle, start_iso or now, end_iso)
        if not synced:
            return {"subscription_tier": tier, "upgraded": False, "reason": "changed"}
        if replaced_key:
            await _settle_replaced_plan_bill(replaced_key, stored)
        logger.info(f"verify-upgrade synced user {user_id} to plan={plan} sub={sub_id}")
        await invalidate_user_cache(str(user_id))
        if cycle == "annual":
            await ensure_monthly_overage_billing(sub_id)
        return {"subscription_tier": plan, "upgraded": True, "reason": "stripe_verified"}
    except HTTPException:
        raise
    except stripe.error.AuthenticationError:
        raise HTTPException(500, "Stripe API key not configured")
    except Exception as e:
        import traceback
        logger.error(f"verify-upgrade error: error_type={type(e).__name__}, error_code={getattr(e, 'code', None)}")
        logger.debug(f"verify-upgrade traceback:\n{traceback.format_exc()}")
        raise HTTPException(500, "Subscription verification failed. Please try again.")


async def _first_payment_settled(sub_id: str) -> bool:
    """Has the subscription's latest invoice been paid - or does it ask for
    nothing (a trial, a $0 invoice, no invoice yet)? A card or wallet is paid
    when Checkout completes, so their flow is unchanged (3 Nov 2026, L-F).
    Raises when Stripe cannot be asked (the caller answers "try again")."""
    sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id, expand=["latest_invoice"])
    inv = field(sub, "latest_invoice")
    if not inv:
        return True
    if isinstance(inv, str):
        inv = await asyncio.to_thread(stripe.Invoice.retrieve, inv)
    if field(inv, "status") == "paid":
        return True
    due = field(inv, "amount_due")
    try:
        return due is not None and int(due) <= 0
    except (TypeError, ValueError):
        return False


async def _stored_is_live(sub_id: str) -> bool:
    try:
        sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
    except Exception as ex:
        if is_missing_subscription(ex):
            return False
        raise
    return field(sub, "status") in LIVE_SUB_STATUSES


# The one-off overage pack is retired (2 Nov 2026, M5): no screen uses it, and it
# took real money outside the subscription. Overage is billed on the invoice.
@router.post("/create-overage-checkout")
async def create_overage_checkout(current_user: dict = Depends(get_current_user)):
    raise HTTPException(410, "Overage packs are no longer sold. Overage is billed on your next invoice.")


@router.post("/apply-overage")
async def apply_overage(current_user: dict = Depends(get_current_user)):
    raise HTTPException(410, "Overage packs are no longer sold. Overage is billed on your next invoice.")


# ASYNC-SAFE
@router.post("/cancel-subscription")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    customer_id = current_user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer found for this account.")

    try:
        active_subs = await list_all(stripe.Subscription.list, customer=customer_id, status="active", limit=5)
        subs = [s for s in active_subs if belongs_to_user(s, current_user["id"], own_customer=True)]
        if not subs:
            raise HTTPException(400, "No active subscription found in Stripe.")

        cancelled_ids = []
        for sub in subs:
            real_sub_id = field(sub, "id")
            if not real_sub_id:
                continue
            await asyncio.to_thread(stripe.Subscription.modify, real_sub_id, cancel_at_period_end=True)
            cancelled_ids.append(real_sub_id)
            logger.info(f"Set cancel_at_period_end=True for sub {real_sub_id} (customer {customer_id})")

        # 3 Nov 2026 (L-D): a failure stage stays where the lifecycle put it
        # (cancelling never reopens a locked account); the user is "canceling"
        # only when the plan on their row is one just set to end; and the
        # stored subscription is never replaced - an empty one is filled in.
        stored = current_user.get("stripe_subscription_id")
        own = stored if stored in cancelled_ids else None
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET payment_status = CASE"
                f" WHEN COALESCE(payment_status, 'ok') IN ({_FAILURE_SQL})"
                " THEN payment_status"
                " WHEN stripe_subscription_id IS NULL OR stripe_subscription_id = $1 THEN 'canceling'"
                " ELSE payment_status END,"
                " stripe_subscription_id = COALESCE(stripe_subscription_id, $2)"
                " WHERE id=$3",
                own, cancelled_ids[0], current_user["id"],
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


async def _open_portal(user: dict, customer_id: str) -> dict:
    try:
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=f"{FRONTEND_URL}?billing_updated=true",
        )
        return {"url": session.url}
    except stripe.error.InvalidRequestError as ex:
        if "No such customer" in str(ex):
            logger.warning(f"Stale stripe_customer_id for user {user['id']}, clearing it")
            await clear_stale_customer(user["id"], customer_id)
            raise HTTPException(400, "Your billing profile was reset. Please try again to set up a new subscription.")
        # Portal not configured in Stripe dashboard — fall back to setup-mode checkout
        logger.warning(f"Billing portal not configured, falling back to setup session: {ex}")
        try:
            setup_session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                customer=customer_id,
                **CHECKOUT_PAYMENT_METHODS,
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


# ASYNC-SAFE
@router.post("/create-portal-session")
async def create_portal_session(user: dict = Depends(get_current_user)):
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        # A user with no customer on file has nothing to manage. One found by
        # e-mail counts only when it carries this user's id (2 Nov 2026, H4/L7);
        # this door never starts a new subscription.
        try:
            found = await primble_customers_by_email(user)
        except Exception as ex:
            logger.error(f"create-portal-session: Stripe unreachable for user {user['id']}: {type(ex).__name__}")
            _refuse(503, BILLING_UNAVAILABLE)
        if not found:
            _refuse(400, NO_BILLING_ACCOUNT)
        customer_id = field(found[0], "id")
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET stripe_customer_id = $1 WHERE id = $2 AND stripe_customer_id IS NULL",
                customer_id, user["id"],
            )
        if not user.get("stripe_subscription_id"):
            await _restore_subscription(user, found[0])
    return await _open_portal(user, customer_id)


async def _restore_subscription(user: dict, customer) -> None:
    """Link the user's tagged, active subscription to a row that lost it - never
    a guessed plan."""
    try:
        active = await list_all(stripe.Subscription.list, customer=field(customer, "id"),
                                status="active", limit=10)
    except Exception as ex:
        logger.warning(f"create-portal-session: could not list subscriptions for user {user['id']}: {ex}")
        return
    for sub in active:
        if not belongs_to_user(sub, user["id"], customer=customer):
            continue
        plan, cycle = subscription_plan(sub)
        if not plan:
            continue
        cfg = PLANS[plan][cycle]
        start_iso, end_iso = _period_isos(sub)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                done = await conn.execute(
                    """UPDATE users SET stripe_subscription_id=$1, subscription_tier=$2,
                       billing_cycle=$3, packages_limit=$4, overage_rate=$5,
                       billing_period_start=$6, payment_status='ok', payment_failed_at=NULL
                       WHERE id=$7 AND stripe_subscription_id IS NULL""",
                    field(sub, "id"), plan, cycle, cfg["packages"], cfg["overage_rate"],
                    start_iso or datetime.now(timezone.utc).isoformat(), user["id"],
                )
                adopted = bool(int(str(done).split()[-1] or 0))
                if adopted:
                    # Everything the month logic needs (3 Nov 2026).
                    await adopt_plan_usage(conn, user["id"], cycle, start_iso, end_iso)
        if not adopted:
            return
        logger.info(f"Restored subscription {field(sub, 'id')} for user {user['id']} from Stripe")
        await invalidate_user_cache(str(user["id"]))
        if cycle == "annual":
            await ensure_monthly_overage_billing(field(sub, "id"), check_first=True)
        return
