import logging
from typing import Optional

import stripe

from config.database import get_db
from config.settings import SOFT_BUFFER_PCT

logger = logging.getLogger(__name__)


def get_or_create_stripe_customer(user: dict) -> Optional[str]:
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
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("UPDATE users SET stripe_customer_id = %s WHERE id = %s", (customer_id, user["id"]))
        conn.commit()
        cur.close()
        conn.close()
        return customer_id
    except Exception as ex:
        logger.error(f"get_or_create_stripe_customer failed: {ex}")
        return None


def create_overage_invoice_item(user: dict, overage_rate_cents: int) -> bool:
    if not stripe.api_key:
        logger.warning(f"Stripe not configured — overage not billed for user={user['id']}")
        return False
    customer_id = get_or_create_stripe_customer(user)
    if not customer_id:
        return False
    sub        = user.get("subscription_tier", "")
    tier_label = "Essentials" if sub == "essentials" else "Professional"
    try:
        stripe.InvoiceItem.create(
            customer=customer_id,
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


def evaluate_package_limit(fresh: dict) -> dict:
    sub        = fresh.get("subscription_tier", "free") or "free"
    pkgs_used  = int(fresh.get("packages_used", 0) or 0)
    pkgs_limit = int(fresh.get("packages_limit", 0) or 0)
    overage_rate_cents = int(fresh.get("overage_rate") or (150 if sub == "essentials" else 125))

    if pkgs_limit == 0:
        pkgs_limit = 100 if sub == "essentials" else 400
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("UPDATE users SET packages_limit = %s WHERE id = %s", (pkgs_limit, fresh["id"]))
        conn.commit()
        cur.close()
        conn.close()

    soft_buffer = int(pkgs_limit * SOFT_BUFFER_PCT)
    hard_limit  = pkgs_limit + soft_buffer

    if pkgs_used < pkgs_limit:
        return {"status": "normal", "allow": True, "message": "", "overage_rate_cents": overage_rate_cents,
                "pkgs_limit": pkgs_limit, "pkgs_used": pkgs_used, "soft_buffer": soft_buffer}
    elif pkgs_used < hard_limit:
        remaining_buffer = hard_limit - pkgs_used - 1
        return {
            "status": "soft_buffer", "allow": True,
            "message": (f"You have used all {pkgs_limit} included packages this month. "
                        f"{remaining_buffer} complimentary buffer package(s) remaining. "
                        f"After that, overages are billed at ${overage_rate_cents/100:.2f}/package."),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }
    else:
        return {
            "status": "overage", "allow": True,
            "message": (f"You are over your {pkgs_limit}-package limit. "
                        f"This package will be billed at ${overage_rate_cents/100:.2f} on your next invoice."),
            "overage_rate_cents": overage_rate_cents, "pkgs_limit": pkgs_limit,
            "pkgs_used": pkgs_used, "soft_buffer": soft_buffer,
        }