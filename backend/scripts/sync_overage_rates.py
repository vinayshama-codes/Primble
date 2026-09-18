"""
Move every subscriber's stored overage rate onto the CURRENT price table.

Why this exists: a user's overage rate is copied from config.settings.PLANS onto
their users row when their subscription is recorded, and every overage charge
bills that stored number. A price change therefore reaches new subscribers only.
Run this after a price change when existing subscribers should move too.

Rates are read from PLANS, never typed here, so the script cannot drift from the
code. Only sellable tiers (SELLABLE_PLANS) are touched; a retired or sales-led
tier keeps whatever it was sold with. Idempotent - a second run changes nothing.

Dry run by default (prints what WOULD change). Writes only with --apply:
    cd backend
    python scripts/sync_overage_rates.py            # preview
    python scripts/sync_overage_rates.py --apply    # write, in one transaction
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402

from config.settings import DATABASE_URL, PLANS, SELLABLE_PLANS  # noqa: E402


def _mask(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    return f"{local[:3]}***@{domain}"


def _target_rate(tier: str) -> int:
    rates = {cfg["overage_rate"] for cfg in PLANS[tier].values()}
    if len(rates) != 1:
        raise SystemExit(f"PLANS[{tier!r}] has different overage rates per cycle: {rates}")
    return rates.pop()


async def main(apply: bool) -> None:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set")
    targets = {tier: _target_rate(tier) for tier in SELLABLE_PLANS}

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT id, email, subscription_tier, overage_rate FROM users"
            " WHERE subscription_tier = ANY($1::text[]) ORDER BY email",
            list(targets),
        )
        stale = [r for r in rows if r["overage_rate"] != targets[r["subscription_tier"]]]

        print(f"{len(rows)} subscriber(s) on {', '.join(targets)}; {len(stale)} on an old rate.")
        for r in stale:
            new = targets[r["subscription_tier"]]
            print(f"  {_mask(r['email']):28} {r['subscription_tier']:12}"
                  f" ${(r['overage_rate'] or 0) / 100:.2f} -> ${new / 100:.2f}")
        if not stale:
            return
        if not apply:
            print("Dry run - nothing written. Re-run with --apply to update.")
            return

        async with conn.transaction():
            for tier, rate in targets.items():
                await conn.execute(
                    "UPDATE users SET overage_rate = $1"
                    " WHERE subscription_tier = $2 AND overage_rate IS DISTINCT FROM $1",
                    rate, tier,
                )

        left = await conn.fetchval(
            "SELECT count(*) FROM users WHERE "
            + " OR ".join(
                f"(subscription_tier = ${i * 2 + 1} AND overage_rate IS DISTINCT FROM ${i * 2 + 2})"
                for i in range(len(targets))
            ),
            *[v for tier, rate in targets.items() for v in (tier, rate)],
        )
        print(f"Updated {len(stale)} subscriber(s). Still on an old rate: {left}.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv[1:]))
