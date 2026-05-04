"""
Idempotent migration: encrypt any plaintext signature_data rows.

Runs automatically on every startup (called from main.py).
Rows already prefixed "enc:" are skipped, so re-running is always safe.

Can also be invoked manually:
    cd backend
    DATABASE_URL="..." FIELD_ENCRYPTION_KEY="..." python scripts/encrypt_signature_data.py
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

_PREFIX = "enc:"


async def run_migration() -> None:
    """Encrypt all plaintext signature_data rows. Uses the live asyncpg pool."""
    from config.database import get_pool
    from utils.crypto import encrypt_field

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, signature_data FROM users"
            " WHERE signature_data IS NOT NULL AND signature_data != ''"
        )

        updated = 0
        for row in rows:
            sig = row["signature_data"]
            if sig.startswith(_PREFIX):
                continue
            await conn.execute(
                "UPDATE users SET signature_data = $1 WHERE id = $2",
                encrypt_field(sig), row["id"],
            )
            updated += 1

    if updated:
        logger.info(f"signature_data migration: encrypted {updated} row(s)")
    else:
        logger.debug("signature_data migration: nothing to encrypt")


# ── CLI entry-point (manual use only) ────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from dotenv import load_dotenv
    load_dotenv()

    async def _main():
        from config.database import create_pool, close_pool
        await create_pool()
        try:
            await run_migration()
        finally:
            await close_pool()

    asyncio.run(_main())
