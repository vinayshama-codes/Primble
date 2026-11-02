import asyncio
import logging
from typing import Optional

import stripe

from config.database import get_pool
from config.settings import PLANS, SOFT_BUFFER_PCT, default_overage_rate_cents, plan_usage_unit

logger = logging.getLogger(__name__)

# A subscription that still bills, or still can (2 Nov 2026). "incomplete" is a
# first payment waiting on the card (3D Secure); "unpaid" is where Smart Retries
# leave a subscription now (the live account no longer cancels it).
LIVE_SUB_STATUSES = ("active", "trialing", "past_due", "unpaid", "incomplete")
PAYING_SUB_STATUSES = ("active", "trialing")
# payment_status values of the non-payment lifecycle.
FAILURE_STATUSES = ("failed", "soft_locked", "suspended", "archived")

SUBSCRIPTION_EXISTS = {
    "code": "subscription_exists",
    "message": "You already have an active Primble plan. To change your plan, contact support@primble.ai.",
}
PAYMENT_DUE = {
    "code": "payment_due",
    "message": "Your last payment didn't go through. Update your card in Manage billing to restore your plan.",
}


class StripeUnavailable(Exception):
    """Stripe could not be asked. Callers refuse or retry - they never guess."""


def field(obj, key, default=None):
    """One reader for a Stripe object or the plain dict a webhook carries."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, default)


def metadata_value(obj, key) -> Optional[str]:
    meta = field(obj, "metadata") or {}
    val = field(meta, key)
    return str(val) if val not in (None, "") else None


def is_ending(sub) -> bool:
    """Is this subscription set to end (the user is "canceling")? Stripe says it
    two ways: `cancel_at_period_end`, or a `cancel_at` date - the billing portal
    under flexible billing sets the date and leaves the flag false (local test on
    the test account, 2 Nov 2026, LT-1). Every reader asks this, never the flag."""
    return bool(field(sub, "cancel_at_period_end")) or bool(field(sub, "cancel_at"))


def object_id(value) -> Optional[str]:
    """An expandable Stripe field: an id string, or the expanded object."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return field(value, "id")


def belongs_to_user(sub, user_id, *, customer=None, own_customer=False) -> bool:
    """Is this subscription Primble's, for THIS user? (2 Nov 2026, H4)

    Its own metadata user_id decides. With none, the customer's metadata user_id
    decides. With neither, only `own_customer` (the customer stored on this
    user's row - never one found by e-mail) can claim it; the safety checks pass
    it, an upgrade never does."""
    owner = metadata_value(sub, "user_id")
    if owner:
        return owner == str(user_id)
    if customer is not None:
        c_owner = metadata_value(customer, "user_id")
        if c_owner:
            return c_owner == str(user_id)
    return bool(own_customer)


def _list_all(fn, **params) -> list:
    return list(fn(**params).auto_paging_iter())


async def list_all(fn, **params) -> list:
    """Every page of a Stripe list, fetched OFF the event loop: the pager's
    later pages are network calls too (2 Nov 2026, M7)."""
    return await asyncio.to_thread(_list_all, fn, **params)


def _is_missing(ex: Exception, what: str) -> bool:
    return isinstance(ex, stripe.error.InvalidRequestError) and f"no such {what}" in str(ex).lower()


def is_missing_customer(ex: Exception) -> bool:
    return _is_missing(ex, "customer")


def is_missing_subscription(ex: Exception) -> bool:
    return _is_missing(ex, "subscription")


async def primble_customers_by_email(user: dict) -> list:
    """Stripe customers with this user's e-mail AND this user's id in their
    metadata. Another product's customer with the same e-mail is never ours."""
    email = user.get("email")
    if not email:
        return []
    listed = await asyncio.to_thread(stripe.Customer.list, email=email, limit=10)
    return [c for c in (field(listed, "data") or [])
            if metadata_value(c, "user_id") == str(user["id"])]


# ASYNC-SAFE
async def ensure_stripe_customer(user: dict, *, replacing: Optional[str] = None) -> str:
    """ONE Stripe customer per user, stored on the row BEFORE any checkout
    (2 Nov 2026, B1/H3). Two tabs at once get the same customer: the create
    carries an idempotency key, and the row is written only while empty.
    `replacing` is a stale id just cleared - it keys a fresh customer.
    Raises StripeUnavailable when Stripe cannot be asked."""
    stored = user.get("stripe_customer_id")
    if stored and stored != replacing:
        return stored
    if not stripe.api_key:
        raise StripeUnavailable("stripe is not configured")
    try:
        found = await primble_customers_by_email(user)
        if found:
            customer_id = field(found[0], "id")
        else:
            cust = await asyncio.to_thread(
                stripe.Customer.create,
                email=user["email"],
                name=user.get("full_name", "") or "",
                metadata={"user_id": str(user["id"]), "org": user.get("organization_name", "") or ""},
                idempotency_key=f"primble-customer:{user['id']}:{replacing or 'none'}",
            )
            customer_id = field(cust, "id")
    except stripe.error.AuthenticationError:
        raise
    except Exception as ex:
        raise StripeUnavailable(str(ex)) from ex
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET stripe_customer_id=$1 WHERE id=$2 AND stripe_customer_id IS NULL"
            " RETURNING stripe_customer_id",
            customer_id, user["id"],
        )
        if not row:
            row = await conn.fetchrow("SELECT stripe_customer_id FROM users WHERE id=$1", user["id"])
            kept = (dict(row) if row else {}).get("stripe_customer_id")
            if kept and kept != customer_id:
                logger.info("ensure_stripe_customer: user %s already has customer %s", user["id"], kept)
                return kept
    return customer_id


async def clear_stale_customer(user_id, customer_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET stripe_customer_id=NULL WHERE id=$1 AND stripe_customer_id=$2",
            user_id, customer_id,
        )


# ASYNC-SAFE
async def live_primble_subscriptions(user: dict, customer_id: Optional[str]) -> list:
    """Every live subscription that is this user's: those on the user's own
    customer (not tagged to someone else) plus the one stored on the row.
    Raises the Stripe error (a missing customer included) - never guesses."""
    out, seen = [], set()
    if customer_id:
        for sub in await list_all(stripe.Subscription.list, customer=customer_id, status="all", limit=100):
            sid = field(sub, "id")
            if (field(sub, "status") in LIVE_SUB_STATUSES
                    and belongs_to_user(sub, user["id"], own_customer=True)):
                out.append(sub)
                seen.add(sid)
    stored = user.get("stripe_subscription_id")
    if stored and stored not in seen:
        try:
            sub = await asyncio.to_thread(stripe.Subscription.retrieve, stored)
        except Exception as ex:
            if not is_missing_subscription(ex):
                raise
            sub = None
        if sub is not None and field(sub, "status") in LIVE_SUB_STATUSES:
            out.append(sub)
    return out


def checkout_refusal(live_subs: list) -> Optional[dict]:
    """The 409 body for a user who must not open a second plan, or None."""
    if not live_subs:
        return None
    if any(field(s, "status") in PAYING_SUB_STATUSES for s in live_subs):
        return dict(SUBSCRIPTION_EXISTS)
    return dict(PAYMENT_DUE)


def plan_from_subscription(sub) -> tuple:
    """(plan, cycle) a subscription bills, or (None, None). Metadata first; else
    an EXACT price + interval match in PLANS - never a default plan."""
    plan = metadata_value(sub, "plan")
    cycle = metadata_value(sub, "billing_cycle")
    if plan in PLANS and plan != "enterprise":
        cycle = cycle if cycle in PLANS[plan] else "monthly"
        return plan, cycle
    try:
        items = field(field(sub, "items"), "data") or []
        price = field(items[0], "price")
        amount = field(price, "unit_amount")
        interval = field(field(price, "recurring"), "interval")
    except Exception:
        return None, None
    matches = [(p, c) for p, cfg in PLANS.items() if p != "enterprise"
               for c, v in cfg.items() if v["amount"] == amount and v["interval"] == interval]
    return matches[0] if len(matches) == 1 else (None, None)


def create_overage_invoice_item(user: dict, overage_rate_cents: int, unit_key: Optional[str] = None) -> bool:
    """Sync - Stripe SDK call. Run it with asyncio.to_thread from async code.

    `unit_key` names the one package this charge is for: it is the Stripe
    idempotency key and rides in the metadata, so a retry of the same unit can
    never bill twice (2 Nov 2026, M6)."""
    if not stripe.api_key:
        logger.warning(f"Stripe not configured — overage not billed for user={user['id']}")
        return False
    if not user.get("stripe_customer_id"):
        logger.warning(f"No stripe_customer_id for user={user['id']} — overage not billed")
        return False
    sub        = user.get("subscription_tier", "") or ""
    tier_label = sub.title() if sub in PLANS else "Professional"
    unit_label = plan_usage_unit(sub)
    meta = {"user_id": str(user["id"]), "plan": sub, "type": "overage_package"}
    kwargs = {}
    if unit_key:
        meta["unit_key"] = unit_key
        kwargs["idempotency_key"] = unit_key
    # Scoped to the plan it was used on (2 Nov 2026, M-4): Stripe puts the item
    # on THAT subscription's next invoice only - never on the first invoice of
    # an accidental second subscription, whose refund would refund it.
    if user.get("stripe_subscription_id"):
        kwargs["subscription"] = user["stripe_subscription_id"]
    try:
        stripe.InvoiceItem.create(
            customer=user.get("stripe_customer_id"),
            amount=overage_rate_cents,
            currency="usd",
            description=f"Primble {tier_label} — 1 overage ACORD {unit_label} (@ ${overage_rate_cents/100:.2f})",
            metadata=meta,
            **kwargs,
        )
        logger.info(f"Overage invoice item queued: user={user['id']} amount={overage_rate_cents}¢")
        return True
    except Exception as ex:
        logger.error(f"Failed to create overage invoice item for user={user['id']}: {ex}")
        return False


def overage_unit_already_billed(user: dict, unit_key: str, since_ts: Optional[int] = None) -> Optional[bool]:
    """Sync. True when Stripe already holds an invoice item for this unit (an
    idempotency key lasts 24 hours; this check does not). None = cannot tell."""
    if not stripe.api_key or not user.get("stripe_customer_id"):
        return None
    try:
        params = {"customer": user["stripe_customer_id"], "limit": 100}
        if since_ts:
            params["created"] = {"gte": int(since_ts)}
        listed = stripe.InvoiceItem.list(**params)
        for item in listed.auto_paging_iter():
            if metadata_value(item, "unit_key") == unit_key:
                return True
        return False
    except Exception as ex:
        logger.warning(f"overage_unit_already_billed: could not list items for user={user['id']}: {ex}")
        return None


def allowance_for(row: dict) -> tuple:
    """(packages_limit, hard_limit) of a package-tier user row: the plan's
    allowance plus the complimentary buffer. A package numbered above the hard
    limit in its period is an overage package."""
    sub = row.get("subscription_tier", "free") or "free"
    pkgs_limit = int(row.get("packages_limit", 0) or 0)
    if pkgs_limit == 0:
        _cycle = row.get("billing_cycle") or "monthly"
        _plan = PLANS.get(sub) or {}
        pkgs_limit = int((_plan.get(_cycle) or _plan.get("monthly") or {}).get("packages") or 400)
    return pkgs_limit, pkgs_limit + int(pkgs_limit * SOFT_BUFFER_PCT)


# ASYNC-SAFE
async def evaluate_package_limit(fresh: dict) -> dict:
    from services.usage_service import rolled_packages_used
    sub                = fresh.get("subscription_tier", "free") or "free"
    # An annual plan whose usage month ended shows the new month's count, not
    # last month's (3 Nov 2026): the month is started first when it is due.
    pkgs_used          = int(await rolled_packages_used(fresh) or 0)
    pkgs_limit         = int(fresh.get("packages_limit", 0) or 0)
    overage_rate_cents = int(fresh.get("overage_rate") or default_overage_rate_cents(sub))

    if pkgs_limit == 0:
        _cycle     = fresh.get("billing_cycle") or "monthly"
        _plan      = PLANS.get(sub) or {}
        pkgs_limit = int((_plan.get(_cycle) or _plan.get("monthly") or {}).get("packages") or 400)
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET packages_limit=$1 WHERE id=$2",
                pkgs_limit, fresh["id"],
            )

    soft_buffer = int(pkgs_limit * SOFT_BUFFER_PCT)
    hard_limit  = pkgs_limit + soft_buffer

    if pkgs_used < pkgs_limit:
        return {"status": "normal", "allow": True, "message": "",
                "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
                "pkgs_used": pkgs_used, "soft_buffer": soft_buffer}
    elif pkgs_used < hard_limit:
        remaining_buffer = hard_limit - pkgs_used - 1
        return {
            "status": "soft_buffer", "allow": True,
            "message": (
                f"You have used all {pkgs_limit} included packages this month. "
                f"{remaining_buffer} complimentary buffer package(s) remaining. "
                f"After that, overages are billed at ${overage_rate_cents/100:.2f}/package."
            ),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }
    else:
        return {
            "status": "overage", "allow": True,
            "message": (
                f"You are over your {pkgs_limit}-package limit. "
                f"This package will be billed at ${overage_rate_cents/100:.2f} on your next invoice."
            ),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }


# Kept for any caller of the old name: the one customer door, or None.
# ASYNC-SAFE
async def get_or_create_stripe_customer(user: dict) -> Optional[str]:
    try:
        return await ensure_stripe_customer(user)
    except Exception as ex:
        logger.error(f"get_or_create_stripe_customer failed for user={user.get('id')}: {ex}")
        return None


# ── the payment e-mail counter (2 Nov 2026, M8) ──────────────────────────────
# A stage e-mail is CLAIMED before it is sent: one statement moves the counter
# from the value the caller read to the stage's day. Two runs (the scheduler and
# the cron endpoint, or two webhook deliveries) can never both send it. A send
# that fails puts the counter back, so the next run retries it.
async def claim_payment_email(conn, user_id, day: int, prev: int) -> bool:
    row = await conn.fetchrow(
        "UPDATE users SET payment_email_sent_day=$2 WHERE id=$1"
        " AND COALESCE(payment_email_sent_day, 0) < $2"
        " AND COALESCE(payment_email_sent_day, 0) = $3 RETURNING id",
        user_id, int(day), int(prev),
    )
    return bool(row)


async def release_payment_email(conn, user_id, day: int, prev: int) -> None:
    await conn.execute(
        "UPDATE users SET payment_email_sent_day=$3 WHERE id=$1 AND payment_email_sent_day=$2",
        user_id, int(day), int(prev),
    )


def _attempted_open_invoice(sub_id: str) -> bool:
    """Sync. Does the subscription have an OPEN invoice Stripe has already tried
    to charge? (3 Nov 2026: an annual plan stays "active" while its failed
    monthly overage invoice is Smart-Retried - that plan is not paid up.)"""
    listed = stripe.Invoice.list(subscription=sub_id, status="open", limit=10)
    return any(int(field(inv, "attempt_count") or 0) > 0 for inv in listed.auto_paging_iter())


def subscription_payment_state(sub_id: str) -> dict:
    """Sync - is this subscription paid up? (2 Nov 2026, M9; 3 Nov 2026.)
    Paid up = Stripe reports it active or trialing AND it has no open invoice
    Stripe already tried to charge. No "latest invoice paid" escape: a past_due
    plan whose latest invoice is an older paid one is not paid up, and an active
    plan with a failed overage invoice being retried is not either.
    {"paid": bool, "cancel_at_period_end": bool, "missing": bool}. Raises when
    Stripe cannot be asked."""
    if not stripe.api_key:
        raise StripeUnavailable("stripe is not configured")
    try:
        sub = stripe.Subscription.retrieve(sub_id)
    except Exception as ex:
        if is_missing_subscription(ex):
            return {"paid": False, "cancel_at_period_end": False, "missing": True}
        raise
    paid = field(sub, "status") in PAYING_SUB_STATUSES and not _attempted_open_invoice(sub_id)
    return {"paid": bool(paid), "cancel_at_period_end": is_ending(sub),
            "missing": False}


# ── Stripe errors: retry later, or a person (2 Nov 2026, M-1) ────────────────
def is_transient(ex: Exception) -> bool:
    """True when the same call may succeed later: Stripe out of reach, rate
    limited, a 5xx, a key not set (a blank-key process), an idempotent request
    still in flight - or anything that is not a Stripe answer at all. Only a
    Stripe REFUSAL (invalid request, card, permission) is permanent."""
    if isinstance(ex, (StripeUnavailable, stripe.error.APIConnectionError, stripe.error.RateLimitError,
                       stripe.error.APIError, stripe.error.AuthenticationError,
                       stripe.error.IdempotencyError)):
        return True
    if isinstance(ex, stripe.error.StripeError):
        try:
            return int(getattr(ex, "http_status", 0) or 0) >= 500
        except Exception:
            return False
    return True


def _ledger_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _ledger_set(key: str, state: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1", key, state)


async def _ledger_claim(key: str, state: str) -> bool:
    async with get_pool().acquire() as conn:
        status = await conn.execute(
            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
            key, state, _ledger_now(),
        )
    return str(status).strip().endswith(" 1")


# The billing alert inbox (owner, 2 Nov 2026).
BILLING_ALERT_TO = "info@primble.com"
ALERT_PREFIX = "billing_alert:"
ALERT_PENDING = "alert_pending"
ALERT_SENT = "alert_sent"


async def send_billing_alert(ref_key: str, subject: str, body: str) -> bool:
    """One e-mail to the billing inbox per `ref_key`, ever: claimed in the
    ledger before it is sent; a send that fails stays pending and the daily job
    sends it again (`retry_billing_alerts`)."""
    key = ALERT_PREFIX + ref_key
    if not await _ledger_claim(key, ALERT_PENDING):
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT event_type FROM processed_webhook_events WHERE event_id=$1", key)
        if not row or dict(row)["event_type"] != ALERT_PENDING:
            return False
    return await _deliver_alert(key, subject, body)


async def _deliver_alert(key: str, subject: str, body: str) -> bool:
    import html as _html
    from services import email_service
    html_body = f"<pre style=\"font-family:Arial,sans-serif\">{_html.escape(body)}</pre>"
    try:
        ok = await asyncio.to_thread(email_service._send_generic_email, BILLING_ALERT_TO, subject, body, html_body)
    except Exception as ex:
        logger.error("billing alert %s not sent: %s", key, type(ex).__name__)
        ok = False
    if ok:
        await _ledger_set(key, ALERT_SENT)
    return bool(ok)


# ── an accidental second subscription (2 Nov 2026, B1/H3, M-1, M-4, L-2) ─────
# Two tabs, or a checkout page left open, can complete a second checkout while
# the user already has a live Primble plan (or for an account deleted since, or
# an enterprise plan Primble manages). The existing plan is kept; the new
# subscription is cancelled at once and ITS OWN plan line refunded - never
# anything else that invoice carried. Each one is a ledger row
# ("duplicate_checkout:<user>:<sub>:<invoice>") written in the webhook's own
# transaction. A Stripe failure that may pass (out of reach, rate limited, 5xx,
# a blank key) leaves it pending for the daily job; only a Stripe refusal - or
# three days of failures - hands it to a person: ERROR log, audit row naming
# the invoice, and one alert e-mail to the billing inbox.
DUP_PREFIX = "duplicate_checkout:"
DUP_PENDING = "duplicate_pending"
DUP_REFUNDED = "duplicate_refunded"
DUP_MANUAL = "duplicate_manual"
DUP_GIVE_UP_AFTER_HOURS = 72


def duplicate_key(user_id, sub_id: str, invoice_id: Optional[str]) -> str:
    return f"{DUP_PREFIX}{user_id}:{sub_id}:{invoice_id or ''}"


def _is_line_of(line, sub_id: str) -> bool:
    parent = field(line, "parent") or {}
    ptype = field(parent, "type")
    if ptype and ptype != "subscription_item_details":
        return False
    if not ptype and field(line, "type") not in (None, "subscription"):
        return False
    owner = object_id(field(line, "subscription")) or object_id(
        field(field(parent, "subscription_item_details") or {}, "subscription"))
    return owner in (None, sub_id)


def _cancel_and_refund(sub_id: str, invoice_id: Optional[str]) -> dict:
    """Sync - cancel the subscription now and refund its first invoice's PLAN
    line (M-4: an overage item that rode that invoice stays paid). Idempotency
    keys make a repeat harmless. Raises when the failure may pass (M-1);
    returns Stripe's refusals in `problems`."""
    problems, refunds = [], []
    try:
        stripe.Subscription.cancel(sub_id, idempotency_key=f"primble-dup-cancel:{sub_id}")
    except Exception as ex:
        if is_transient(ex):
            raise
        try:
            status = field(stripe.Subscription.retrieve(sub_id), "status")
        except Exception as ex2:
            if is_transient(ex2):
                raise
            status = None
        if status not in ("canceled", "incomplete_expired"):
            problems.append(f"cancel refused: {type(ex).__name__}")
    inv = invoice_id
    if not inv:
        try:
            inv = object_id(field(stripe.Subscription.retrieve(sub_id), "latest_invoice"))
        except Exception as ex:
            if is_transient(ex):
                raise
            problems.append(f"invoice not found: {type(ex).__name__}")
    if inv:
        try:
            lines = list(stripe.Invoice.list_lines(inv, limit=100).auto_paging_iter())
            plan_amount = sum(int(field(ln, "amount") or 0) for ln in lines if _is_line_of(ln, sub_id))
            pays = list(stripe.InvoicePayment.list(invoice=inv, status="paid", limit=10).auto_paging_iter())
            remaining = plan_amount
            for pay in pays:
                if remaining <= 0:
                    break
                detail = field(pay, "payment") or {}
                pi = object_id(field(detail, "payment_intent"))
                ch = object_id(field(detail, "charge"))
                target = {"payment_intent": pi} if pi else ({"charge": ch} if ch else None)
                if not target:
                    continue
                paid = int(field(pay, "amount_paid") or 0) or remaining
                amount = min(remaining, paid)
                # A refund this machinery already made on that payment is done
                # (Q6): a retry after the idempotency key expired never refunds
                # twice.
                made = [r for r in stripe.Refund.list(**target, limit=100).auto_paging_iter()
                        if metadata_value(r, "primble") == "duplicate_subscription"
                        and metadata_value(r, "invoice") == inv
                        and field(r, "status") not in ("failed", "canceled")]
                done_amount = sum(int(field(r, "amount") or 0) for r in made)
                refunds.extend(field(r, "id") for r in made)
                if done_amount >= amount:
                    remaining -= amount
                    continue
                ref = stripe.Refund.create(
                    **target, amount=amount - done_amount, reason="duplicate",
                    metadata={"primble": "duplicate_subscription", "subscription": sub_id, "invoice": inv},
                    idempotency_key=f"primble-dup-refund:{inv}:{field(pay, 'id')}",
                )
                refunds.append(field(ref, "id"))
                remaining -= amount
            if plan_amount <= 0:
                problems.append("no plan line found on the invoice")
            elif not refunds:
                problems.append("no paid payment found on the invoice")
        except Exception as ex:
            if is_transient(ex):
                raise
            problems.append(f"refund refused: {type(ex).__name__}")
    return {"refunds": refunds, "invoice": inv, "problems": problems}


def _hours_since(iso: Optional[str]) -> float:
    from datetime import datetime, timezone
    try:
        then = datetime.fromisoformat(str(iso))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0
    except Exception:
        return 0.0


# ASYNC-SAFE
async def settle_duplicate_checkout(user: dict, sub_id: str, invoice_id: Optional[str],
                                    first_seen: Optional[str] = None) -> dict:
    """Cancel + refund the accidental subscription, then record the outcome.
    The ledger row must already exist (DUP_PENDING). Returns {"state": ...}:
    "refunded", "pending" (try again later) or "manual"."""
    from repositories.audit_repository import write_audit_log
    key = duplicate_key(user["id"], sub_id, invoice_id)
    if not stripe.api_key:
        # A process with no key (the Mac after the switch) never decides a
        # refund is impossible - it leaves the duplicate for the live server.
        logger.warning("Duplicate subscription %s of user %s left pending - Stripe key not set here",
                       sub_id, user["id"])
        return {"state": "pending"}
    try:
        result = await asyncio.to_thread(_cancel_and_refund, sub_id, invoice_id)
    except Exception as ex:
        if _hours_since(first_seen) < DUP_GIVE_UP_AFTER_HOURS:
            logger.error("Duplicate subscription %s of user %s: Stripe failed (%s) - left pending, retried daily",
                         sub_id, user["id"], type(ex).__name__)
            return {"state": "pending"}
        result = {"refunds": [], "invoice": invoice_id,
                  "problems": [f"still failing after {DUP_GIVE_UP_AFTER_HOURS} hours: {type(ex).__name__}"]}
    inv = result.get("invoice") or invoice_id or ""
    if result["refunds"] and not result["problems"]:
        await _ledger_set(key, DUP_REFUNDED)
        logger.warning("Duplicate subscription %s of user %s cancelled and refunded (invoice %s)",
                       sub_id, user["id"], inv)
        await write_audit_log(user, "payment.duplicate_subscription_refunded",
                              session_id=inv, form_name=sub_id)
        return {"state": "refunded", **result}
    await _ledger_set(key, DUP_MANUAL)
    problems = "; ".join(result["problems"]) or "unknown"
    logger.error("MANUAL REFUND NEEDED: duplicate subscription %s of user %s, invoice %s - %s",
                 sub_id, user["id"], inv or "(unknown)", problems)
    await write_audit_log(user, "payment.duplicate_subscription_manual_refund",
                          session_id=inv or sub_id, form_name=sub_id)
    await send_billing_alert(
        key, f"MANUAL REFUND NEEDED - duplicate subscription {sub_id}",
        "A second Primble subscription was opened by mistake and could not be cancelled and\n"
        "refunded automatically. Cancel it and refund its first payment in the Stripe dashboard.\n\n"
        f"User id: {user['id']}\nSubscription: {sub_id}\nInvoice: {inv or '(unknown)'}\n"
        f"Stripe said: {problems}\n")
    return {"state": "manual", **result}


# ASYNC-SAFE
async def retry_unsettled_duplicates() -> int:
    """Run by the daily lifecycle job: a duplicate still pending an hour after
    its event is settled now. Never runs without a Stripe key."""
    if not stripe.api_key:
        return 0
    from datetime import datetime, timedelta, timezone
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id, processed_at FROM processed_webhook_events"
            " WHERE event_type=$1 AND processed_at < $2 AND event_id LIKE $3",
            DUP_PENDING, stale, DUP_PREFIX + "%",
        )
    settled = 0
    for r in [dict(x) for x in rows]:
        try:
            uid, sub_id, inv = r["event_id"][len(DUP_PREFIX):].split(":", 2)
            async with get_pool().acquire() as conn:
                urow = await conn.fetchrow("SELECT id, email, stripe_customer_id FROM users WHERE id=$1", uid)
            user = dict(urow) if urow else {"id": uid, "email": ""}
            out = await settle_duplicate_checkout(user, sub_id, inv or None, first_seen=r["processed_at"])
            if out.get("state") == "refunded":
                settled += 1
        except Exception as ex:
            logger.error("retry_unsettled_duplicates: %s not settled: %s", r["event_id"], ex)
    return settled


async def retry_billing_alerts() -> int:
    """Alerts whose send failed go out again (daily job)."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id FROM processed_webhook_events WHERE event_type=$1 AND event_id LIKE $2",
            ALERT_PENDING, ALERT_PREFIX + "%",
        )
    sent = 0
    for r in [dict(x) for x in rows]:
        ref = r["event_id"][len(ALERT_PREFIX):]
        if await _deliver_alert(r["event_id"], f"MANUAL ACTION NEEDED - billing ({ref})",
                                f"A billing item needs a person - see the ERROR log and the audit log for {ref}.\n"):
            sent += 1
    return sent


# ── the plan's last bill: extra packages still unbilled (2 Nov 2026, C1) ─────
# Overage rides the plan's NEXT invoice (an invoice item scoped to that
# subscription). When the plan ends - cancelled at period end, from the portal,
# or by delete-account - no next invoice ever comes, so the items would wait for
# ever. The plan's end bills them on ONE final invoice, built explicitly:
# a draft invoice (pending items excluded), each owed unit added to it by
# `invoice=`, the stale pending copy deleted, finalized with automatic
# collection, and charged. Owed = this user's Primble overage units that Stripe
# still holds as PENDING items, plus units Stripe never took (ledger pending).
# Exactly once: a ledger row per (user, plan) claimed by whoever sees the end
# first, idempotency keys on every call, and the draft found again by its
# metadata when a retry outlives those keys. A charge that fails is logged at
# ERROR and audited; Stripe's automatic collection retries it. The user row is
# never touched - the user is free by then.
FINAL_PREFIX = "final_overage:"
FINAL_PENDING = "final_pending"
FINAL_INVOICED = "final_invoiced"
FINAL_NONE = "final_none"
FINAL_MANUAL = "final_manual"


def final_overage_key(user_id, sub_id: Optional[str], customer_id: str, rate_cents: int) -> str:
    return f"{FINAL_PREFIX}{user_id}:{sub_id or 'none'}:{customer_id}:{int(rate_cents)}"


def _bill_final_overage(key: str, user_id: str, sub_id: str, customer_id: str, owed: list) -> dict:
    """Sync. `owed` = [(unit_key, amount_cents)] Stripe never took. Raises when
    a failure may pass. Returns the unit keys that are now billed
    (`billed_keys`): on this final invoice or already on any other invoice."""
    prefix = f"overage_unit:{user_id}:"
    pending, on_an_invoice = {}, set()
    # Everything first (F2): EVERY item carrying one of this user's unit keys,
    # pending or already on an invoice. A unit already on ANY invoice is never
    # billed again - and a stale pending copy of it is deleted.
    for item in stripe.InvoiceItem.list(customer=customer_id, limit=100).auto_paging_iter():
        uk = metadata_value(item, "unit_key") or ""
        if not uk.startswith(prefix):
            continue
        if object_id(field(item, "invoice")):
            on_an_invoice.add(uk)
        else:
            pending.setdefault(uk, []).append(
                (int(field(item, "amount") or 0), field(item, "id"), object_id(field(item, "subscription"))))
    for uk in on_an_invoice & set(pending):
        for _amt, item_id, _sub in pending.pop(uk):
            _drop_pending_item(item_id)
    # Only THIS plan's pending items (or unscoped legacy ones): a later plan's
    # pending overage rides that plan's own invoice (F3).
    units = {}
    for uk, copies in pending.items():
        mine = [c for c in copies if c[2] in (None, "", sub_id)] if sub_id else copies
        if mine:
            units[uk] = (mine[0][0], mine[0][1])
            for _amt, extra_id, _sub in mine[1:]:
                _drop_pending_item(extra_id)
    for uk, amount in owed:
        if uk not in on_an_invoice:
            units.setdefault(uk, (int(amount), None))

    found = [inv for inv in stripe.Invoice.list(customer=customer_id, limit=100).auto_paging_iter()
             if metadata_value(inv, "final_key") == key]
    done = next((inv for inv in found if field(inv, "status") in ("open", "paid", "uncollectible")), None)
    if done is not None:
        # Recovering a final invoice already finalized (F3): only the units ON
        # it are billed; only their pending copies go.
        on_done = {metadata_value(i, "unit_key")
                   for i in stripe.InvoiceItem.list(invoice=field(done, "id"), limit=100).auto_paging_iter()}
        for uk, (_amt, old_id) in units.items():
            if uk in on_done and old_id:
                _drop_pending_item(old_id)
        return {"state": "invoiced", "invoice": field(done, "id"), "units": 0, "charge_failed": False,
                "billed_keys": (on_done | on_an_invoice)}
    draft = next((inv for inv in found if field(inv, "status") == "draft"), None)
    if not units and draft is None:
        return {"state": "none", "units": 0, "billed_keys": set(on_an_invoice)}

    if draft is None:
        # The card the plan was paid with: Checkout saves it on the SUBSCRIPTION,
        # not as the customer's default, so a one-off invoice would have none.
        pm = None
        if sub_id:
            try:
                pm = object_id(field(stripe.Subscription.retrieve(sub_id), "default_payment_method"))
            except Exception as ex:
                if is_transient(ex):
                    raise
        extra = {"default_payment_method": pm} if pm else {}
        draft = stripe.Invoice.create(
            customer=customer_id, collection_method="charge_automatically", auto_advance=False,
            pending_invoice_items_behavior="exclude",
            description="Primble - extra packages used in your last billing period",
            metadata={"primble": "final_overage", "final_key": key, "user_id": str(user_id),
                      "subscription": sub_id or ""},
            idempotency_key=f"primble-final-invoice:{key}",
            **extra,
        )
    draft_id = field(draft, "id")
    on_draft = {metadata_value(i, "unit_key")
                for i in stripe.InvoiceItem.list(invoice=draft_id, limit=100).auto_paging_iter()}
    for uk, (amount, old_id) in sorted(units.items()):
        if uk not in on_draft:
            stripe.InvoiceItem.create(
                customer=customer_id, invoice=draft_id, amount=amount, currency="usd",
                description="Primble - 1 overage ACORD package",
                metadata={"user_id": str(user_id), "unit_key": uk, "type": "overage_package",
                          "final": "1"},
                idempotency_key=f"{uk}:final",
            )
            on_draft.add(uk)
        if old_id:
            _drop_pending_item(old_id)
    stripe.Invoice.finalize_invoice(draft_id, auto_advance=True,
                                    idempotency_key=f"primble-final-finalize:{key}")
    charge_failed = False
    try:
        stripe.Invoice.pay(draft_id, idempotency_key=f"primble-final-pay:{key}")
    except Exception as ex:
        if is_transient(ex):
            raise
        # Finalizing with auto_advance can let Stripe collect first: "already
        # paid" is a success, never a failed charge (F4).
        try:
            charge_failed = field(stripe.Invoice.retrieve(draft_id), "status") != "paid"
        except Exception as ex2:
            if is_transient(ex2):
                raise
            charge_failed = True        # declined: Stripe's automatic collection retries
    return {"state": "invoiced", "invoice": draft_id, "units": len(units), "charge_failed": charge_failed,
            "billed_keys": (on_draft | on_an_invoice)}


def _drop_pending_item(item_id: str) -> None:
    """The unit now sits on the final invoice: its pending copy goes."""
    try:
        stripe.InvoiceItem.delete(item_id)
    except Exception as ex:
        if is_transient(ex):
            raise
        if "no such" not in str(ex).lower():
            logger.error("final overage: pending item %s could not be deleted (%s) - check it is not"
                         " billed twice", item_id, type(ex).__name__)


# ASYNC-SAFE
async def settle_final_overage(key: str) -> dict:
    """Bill the plan's still-unbilled overage once, on its own final invoice.
    The ledger row (FINAL_PENDING) must already exist."""
    from repositories.audit_repository import write_audit_log
    try:
        uid, sub_id, customer_id, rate = key[len(FINAL_PREFIX):].split(":", 3)
        rate = int(rate)
    except Exception:
        logger.error("settle_final_overage: unreadable key %s", key)
        return {"state": "error"}
    if not stripe.api_key:
        logger.warning("Final overage of user %s left pending - Stripe key not set here", uid)
        return {"state": "pending"}
    unit_prefix = f"overage_unit:{uid}:"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id, event_type FROM processed_webhook_events WHERE event_id LIKE $1",
            unit_prefix + "%",
        )
    rows = [dict(r) for r in rows]
    if not rows:
        await _ledger_set(key, FINAL_NONE)          # never billed any overage: nothing can be owed
        return {"state": "none"}
    owed = [(r["event_id"], rate) for r in rows if r["event_type"] in ("overage_pending", "overage_billing")]
    try:
        result = await asyncio.to_thread(_bill_final_overage, key, uid,
                                         None if sub_id == "none" else sub_id, customer_id, owed)
    except Exception as ex:
        if is_transient(ex):
            logger.error("Final overage of user %s: Stripe failed (%s) - left pending, retried daily",
                         uid, type(ex).__name__)
            return {"state": "pending"}
        await _ledger_set(key, FINAL_MANUAL)
        logger.error("MANUAL BILLING NEEDED: final overage of user %s (plan %s) refused by Stripe: %s",
                     uid, sub_id, type(ex).__name__)
        await write_audit_log({"id": uid, "email": ""}, "payment.final_overage_manual",
                              session_id=sub_id, form_name=key)
        await send_billing_alert(
            key, f"MANUAL BILLING NEEDED - final overage of plan {sub_id}",
            "A Primble plan ended with extra packages still unbilled, and Stripe refused the final\n"
            "invoice. Bill them in the Stripe dashboard.\n\n"
            f"User id: {uid}\nPlan: {sub_id}\nCustomer: {customer_id}\nStripe said: {type(ex).__name__}\n")
        return {"state": "manual"}
    billed_keys = result.get("billed_keys") or set()
    if owed:
        async with get_pool().acquire() as conn:
            # Only units the final bill placed - or found already invoiced -
            # are marked billed (F3).
            for uk, _amt in owed:
                if uk not in billed_keys:
                    continue
                await conn.execute(
                    "UPDATE processed_webhook_events SET event_type='overage_billed' WHERE event_id=$1"
                    " AND event_type IN ('overage_pending','overage_billing')", uk)
    if result["state"] == "none":
        await _ledger_set(key, FINAL_NONE)
        return result
    await _ledger_set(key, FINAL_INVOICED)
    logger.info("Final overage of user %s invoiced on %s (%s units)", uid, result.get("invoice"), result.get("units"))
    await write_audit_log({"id": uid, "email": ""}, "payment.final_overage_invoiced",
                          session_id=result.get("invoice"), form_name=str(result.get("units")))
    if result.get("charge_failed"):
        logger.error("Final overage charge FAILED for user %s, invoice %s - Stripe's automatic collection"
                     " retries it", uid, result.get("invoice"))
        await write_audit_log({"id": uid, "email": ""}, "payment.final_overage_charge_failed",
                              session_id=result.get("invoice"), form_name=sub_id)
        await send_billing_alert(
            f"{key}:charge_failed", f"Final overage charge FAILED - invoice {result.get('invoice')}",
            "The final invoice for a Primble plan's extra packages was declined. Stripe's automatic\n"
            "collection retries it; follow up if it stays unpaid.\n\n"
            f"User id: {uid}\nPlan: {sub_id}\nInvoice: {result.get('invoice')}\n")
    return result


# ASYNC-SAFE
async def retry_final_overage() -> int:
    """Daily job: final bills whose Stripe calls failed are tried again."""
    if not stripe.api_key:
        return 0
    from datetime import datetime, timedelta, timezone
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id FROM processed_webhook_events"
            " WHERE event_type=$1 AND processed_at < $2 AND event_id LIKE $3",
            FINAL_PENDING, stale, FINAL_PREFIX + "%",
        )
    done = 0
    for r in [dict(x) for x in rows]:
        try:
            if (await settle_final_overage(r["event_id"])).get("state") in ("invoiced", "none"):
                done += 1
        except Exception as ex:
            logger.error("retry_final_overage: %s not settled: %s", r["event_id"], ex)
    return done


def subscription_period(sub) -> tuple:
    """(current_period_start, current_period_end) as epoch seconds, or Nones.
    API 2026-03-25.dahlia keeps them on the subscription's ITEMS; older shapes
    on the subscription itself. Never read from an invoice's line page (Q1)."""
    starts, ends = [], []
    for item in (field(field(sub, "items") or {}, "data") or []):
        if field(item, "current_period_start"):
            starts.append(int(field(item, "current_period_start")))
        if field(item, "current_period_end"):
            ends.append(int(field(item, "current_period_end")))
    if field(sub, "current_period_start"):
        starts.append(int(field(sub, "current_period_start")))
    if field(sub, "current_period_end"):
        ends.append(int(field(sub, "current_period_end")))
    return (min(starts) if starts else None, max(ends) if ends else None)


def price_cycle(sub) -> Optional[str]:
    """The cycle a subscription's price bills on - "annual" / "monthly" - or
    None. Support switches a plan's cycle in Stripe, where our metadata may not
    follow, so the price's own interval decides (3 Nov 2026)."""
    for item in (field(field(sub, "items") or {}, "data") or []):
        interval = field(field(field(item, "price") or {}, "recurring") or {}, "interval")
        if interval in ("year", "month"):
            return "annual" if interval == "year" else "monthly"
    return None


def subscription_plan(sub) -> tuple:
    """(plan, cycle) the subscription bills - the price's interval over the
    metadata's cycle - or (None, None)."""
    plan, meta_cycle = plan_from_subscription(sub)
    if plan is None:
        return None, None
    cycle = price_cycle(sub) or meta_cycle or "monthly"
    return plan, (cycle if cycle in PLANS[plan] else "monthly")


def subscription_status(sub_id: str, check_open: bool = False) -> dict:
    """Sync - the subscription's own status (2 Nov 2026, M-5): a failure is
    cleared only when the PLAN is paying again, not because one invoice was
    paid - and its current period (Q1/Q2). `check_open` also answers whether an
    open invoice was already tried (`open_attempted`, 3 Nov 2026), the restore
    check. Raises when Stripe cannot be asked."""
    if not stripe.api_key:
        raise StripeUnavailable("stripe is not configured")
    sub = stripe.Subscription.retrieve(sub_id)
    start, end = subscription_period(sub)
    plan, cycle = subscription_plan(sub)
    return {"status": field(sub, "status"),
            "cancel_at_period_end": is_ending(sub),
            "period_start": start, "period_end": end,
            "plan": plan, "cycle": cycle,
            "open_attempted": _attempted_open_invoice(sub_id) if check_open else None}


# ── a payment e-mail survives a crash (2 Nov 2026, L-9) ──────────────────────
# Claiming the e-mail (the counter) and writing an "email_sending" marker happen
# in ONE transaction; the marker goes when the send is confirmed or given back.
# A marker still there half an hour later means the process died between the
# claim and the send: the daily job sends that e-mail once more, at most once.
EMAIL_MARK_PREFIX = "email_send:"
EMAIL_SENDING = "email_sending"
EMAIL_RESENDING = "email_resending"


def email_marker_key(day: int, prev: int, user_id, failed_at) -> str:
    return f"{EMAIL_MARK_PREFIX}{int(day)}:{int(prev)}:{user_id}:{failed_at or ''}"


async def send_claimed_payment_email(get_pool_fn, sender, row: dict, day: int, prev: int) -> bool:
    """Claim the stage e-mail, mark it, send it; a send that fails gives the
    claim back (the next run retries). False when another run claimed it."""
    marker = email_marker_key(day, prev, row["id"], row.get("payment_failed_at"))
    async with get_pool_fn().acquire() as conn:
        async with conn.transaction():
            if not await claim_payment_email(conn, row["id"], day, prev):
                return False
            await conn.execute(
                "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO UPDATE"
                " SET event_type = excluded.event_type, processed_at = excluded.processed_at",
                marker, EMAIL_SENDING, _ledger_now(),
            )
    sent_ok = False
    try:
        sent_ok = await asyncio.get_running_loop().run_in_executor(
            None, lambda: sender(row["email"], row.get("full_name", ""), day=day))
    finally:
        async with get_pool_fn().acquire() as conn:
            if not sent_ok:
                await release_payment_email(conn, row["id"], day, prev)
            await conn.execute("DELETE FROM processed_webhook_events WHERE event_id=$1", marker)
        if not sent_ok:
            logger.error(f"Payment e-mail day-{day} send returned False for user={row['id']} — will retry")
    return bool(sent_ok)


async def resend_unconfirmed_payment_emails(get_pool_fn, sender) -> int:
    """Daily job: an e-mail claimed but never confirmed (the process died in
    between) is sent once more, while the user is still in that failure."""
    from datetime import datetime, timedelta, timezone
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    async with get_pool_fn().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id FROM processed_webhook_events"
            " WHERE event_type=$1 AND processed_at < $2 AND event_id LIKE $3",
            EMAIL_SENDING, stale, EMAIL_MARK_PREFIX + "%",
        )
    resent = 0
    for r in [dict(x) for x in rows]:
        key = r["event_id"]
        try:
            day, prev, uid, failed_at = key[len(EMAIL_MARK_PREFIX):].split(":", 3)
            day, prev = int(day), int(prev)
            async with get_pool_fn().acquire() as conn:
                moved = await conn.execute(
                    "UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1 AND event_type=$3",
                    key, EMAIL_RESENDING, EMAIL_SENDING)
                if not str(moved).strip().endswith(" 1"):
                    continue
                user = await conn.fetchrow(
                    "SELECT id, email, full_name, payment_status, payment_failed_at,"
                    " COALESCE(payment_email_sent_day, 0) AS payment_email_sent_day FROM users WHERE id=$1", uid)
            user = dict(user) if user else None
            still = (user and int(user["payment_email_sent_day"]) == day
                     and str(user.get("payment_failed_at") or "") == failed_at
                     and (user.get("payment_status") or "ok") in FAILURE_STATUSES)
            ok = False
            if still:
                ok = bool(await asyncio.get_running_loop().run_in_executor(
                    None, lambda: sender(user["email"], user.get("full_name", ""), day=day)))
                if ok:
                    resent += 1
                    logger.info(f"Payment e-mail day-{day} re-sent to user={uid} after an unconfirmed send")
            async with get_pool_fn().acquire() as conn:
                if still and not ok:
                    await release_payment_email(conn, uid, day, prev)
                await conn.execute("DELETE FROM processed_webhook_events WHERE event_id=$1", key)
        except Exception as ex:
            logger.error(f"resend_unconfirmed_payment_emails: {key} not handled: {ex}")
    return resent


# ── annual plans: extra packages billed monthly (Brent, 3 Nov 2026) ──────────
# Stripe's own `pending_invoice_item_interval` on every ANNUAL Primble
# subscription: each month Stripe invoices that subscription's pending invoice
# items - our per-package overage items, created with `subscription=` - with
# billing_reason "automatic_pending_invoice_item_invoice" (never a usage reset:
# stripe_routes._PERIOD_REASONS). Set right after an annual checkout; the daily
# job makes sure every stored live annual subscription has it.
MONTHLY_OVERAGE_INTERVAL = {"interval": "month", "interval_count": 1}
_PII_PREFIX = "pii_interval:"


def _interval_is_monthly(sub) -> bool:
    pii = field(sub, "pending_invoice_item_interval") or {}
    return field(pii, "interval") == "month" and int(field(pii, "interval_count") or 1) == 1


def set_monthly_overage_billing(sub_id: str, key_suffix: str = "") -> None:
    """Sync. Raises the Stripe error (the caller decides: retried daily).
    `key_suffix` (the plan-switch event) gives a re-set after a switch back
    from monthly its own idempotency key: Stripe would otherwise replay the
    first set for 24 hours and change nothing."""
    if not stripe.api_key:
        raise StripeUnavailable("stripe is not configured")
    key = f"primble-pii-interval:{sub_id}" + (f":{key_suffix}" if key_suffix else "")
    stripe.Subscription.modify(sub_id, pending_invoice_item_interval=dict(MONTHLY_OVERAGE_INTERVAL),
                               idempotency_key=key)


# ASYNC-SAFE
async def ensure_monthly_overage_billing(sub_id: str, check_first: bool = False,
                                         key_suffix: str = "") -> bool:
    """Make sure this annual subscription invoices its overage monthly; the
    ledger remembers one that is done. False when it is not (yet)."""
    key = _PII_PREFIX + sub_id
    async with get_pool().acquire() as conn:
        done = await conn.fetchrow("SELECT 1 FROM processed_webhook_events WHERE event_id=$1", key)
    if done:
        return True
    try:
        if check_first:
            sub = await asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
            if field(sub, "status") not in LIVE_SUB_STATUSES:
                return False
            if not _interval_is_monthly(sub):
                # Checked first, so a fresh key per day is safe - and a set
                # that a switch back to monthly undid is set again.
                from datetime import datetime, timezone
                day = datetime.now(timezone.utc).strftime("%Y%m%d")
                await asyncio.to_thread(set_monthly_overage_billing, sub_id, key_suffix or f"check:{day}")
        else:
            await asyncio.to_thread(set_monthly_overage_billing, sub_id, key_suffix)
    except Exception as ex:
        if is_missing_subscription(ex):
            # Not a subscription of this Stripe account (the internal test-mode
            # accounts after the live switch): noted once, never retried.
            await _ledger_claim(key, "pii_interval_missing")
            logger.warning("annual subscription %s not found in Stripe - monthly overage billing skipped", sub_id)
            return False
        logger.error("annual subscription %s: monthly overage billing not set (%s) - retried by the daily job",
                     sub_id, type(ex).__name__)
        return False
    await _ledger_claim(key, "pii_interval_set")
    logger.info("annual subscription %s bills its extra packages monthly", sub_id)
    return True


# ASYNC-SAFE
async def ensure_annual_overage_intervals() -> int:
    """Daily job: every stored live annual subscription bills overage monthly."""
    if not stripe.api_key:
        return 0
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT stripe_subscription_id FROM users WHERE billing_cycle='annual'"
            " AND stripe_subscription_id IS NOT NULL"
            " AND subscription_tier IN ('essentials','professional','business')")
    done = 0
    for r in [dict(x) for x in rows]:
        if await ensure_monthly_overage_billing(r["stripe_subscription_id"], check_first=True):
            done += 1
    return done


# ASYNC-SAFE
async def clear_monthly_overage_billing(sub_id: str, event_id: str) -> bool:
    """A plan switched from annual to monthly (by support, in Stripe): its
    overage rides the monthly renewal again, so the monthly pending-item
    invoices stop. False when Stripe could not be asked (logged)."""
    if not stripe.api_key:
        return False
    try:
        await asyncio.to_thread(stripe.Subscription.modify, sub_id, pending_invoice_item_interval="",
                                idempotency_key=f"primble-pii-unset:{sub_id}:{event_id}")
    except Exception as ex:
        logger.error("subscription %s: monthly overage billing not removed (%s)", sub_id, type(ex).__name__)
        return False
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM processed_webhook_events WHERE event_id=$1", _PII_PREFIX + sub_id)
    return True
