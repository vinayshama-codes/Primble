import logging
from typing import Optional

import stripe

from config.database import get_pool
from config.settings import SOFT_BUFFER_PCT

logger = logging.getLogger(__name__)


# ASYNC-SAFE
async def get_or_create_stripe_customer(user: dict) -> Optional[str]:
    customer_id = user.get("stripe_customer_id")
    if customer_id:
        return customer_id
    if not stripe.api_key:
        return None
    try:
        customers = stripe.Customer.list(email=user["email"], limit=1)
        if customers.data:
            customer_id = customers.data[0].id
        else:
            cust = stripe.Customer.create(
                email=user["email"],
                name=user.get("full_name", ""),
                metadata={"user_id": user["id"], "org": user.get("organization_name", "")},
            )
            customer_id = cust.id
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE users SET stripe_customer_id=$1 WHERE id=$2",
                customer_id, user["id"],
            )
        return customer_id
    except Exception as ex:
        logger.error(f"get_or_create_stripe_customer failed: {ex}")
        return None


def create_overage_invoice_item(user: dict, overage_rate_cents: int) -> bool:
    """Sync — Stripe SDK call, runs from background scheduler thread."""
    if not stripe.api_key:
        logger.warning(f"Stripe not configured — overage not billed for user={user['id']}")
        return False
    customer_id = None  # caller must resolve customer_id separately if needed
    sub        = user.get("subscription_tier", "")
    tier_label = "Essentials" if sub == "essentials" else "Professional"
    try:
        stripe.InvoiceItem.create(
            customer=user.get("stripe_customer_id"),
            amount=overage_rate_cents,
            currency="usd",
            description=f"Acordly {tier_label} — 1 overage ACORD package (@ ${overage_rate_cents/100:.2f})",
            metadata={"user_id": user["id"], "user_email": user.get("email", ""), "plan": sub, "type": "overage_package"},
        )
        logger.info(f"Overage invoice item queued: user={user['id']} amount={overage_rate_cents}¢")
        return True
    except Exception as ex:
        logger.error(f"Failed to create overage invoice item: {ex}")
        return False


# ASYNC-SAFE
async def evaluate_package_limit(fresh: dict) -> dict:
    sub                = fresh.get("subscription_tier", "free") or "free"
    pkgs_used          = int(fresh.get("packages_used", 0) or 0)
    pkgs_limit         = int(fresh.get("packages_limit", 0) or 0)
    _default_rate = 175 if sub == "essentials" else (150 if sub == "professional" else 125)
    overage_rate_cents = int(fresh.get("overage_rate") or _default_rate)

    if pkgs_limit == 0:
        pkgs_limit = 50 if sub == "essentials" else (100 if sub == "professional" else 400)
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
