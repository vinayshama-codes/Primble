"""
Idempotent migration: encrypt any plaintext facts inside processing_sessions.data.

Rows where data->'facts' is already a string starting with "enc:" are skipped.
Processes in batches of 100 to avoid locking the table.

Can be invoked manually:
    cd backend
    DATABASE_URL="..." FIELD_ENCRYPTION_KEY="..." python scripts/encrypt_facts_data.py
"""

import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

_PREFIX = "enc:"
_BATCH_SIZE = 100


async def run_migration() -> None:
    """Encrypt all plaintext facts rows. Uses the live asyncpg pool."""
    from config.database import get_pool
    from utils.crypto import encrypt_field

    async with get_pool().acquire() as conn:
        # Fetch rows where facts is not null, not empty, and not yet encrypted.
        # data->'facts' is a JSONB value; cast to text to check prefix.
        rows = await conn.fetch(
            """
            SELECT id, data->'facts' AS facts_raw
            FROM processing_sessions
            WHERE data ? 'facts'
              AND data->>'facts' IS NOT NULL
              AND data->>'facts' != ''
              AND data->>'facts' NOT LIKE $1
            """,
            f"{_PREFIX}%",
        )

    total    = len(rows)
    updated  = 0
    skipped  = 0

    logger.info(f"encrypt_facts_data: found {total} row(s) to inspect")

    for i in range(0, total, _BATCH_SIZE):
        batch = rows[i : i + _BATCH_SIZE]
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                for row in batch:
                    facts_raw = row["facts_raw"]

                    # facts_raw is a JSONB value — could be a dict (object) or str
                    if isinstance(facts_raw, str):
                        if facts_raw.startswith(_PREFIX):
                            skipped += 1
                            continue
                        plaintext = facts_raw
                    elif isinstance(facts_raw, dict):
                        plaintext = json.dumps(facts_raw)
                    else:
                        skipped += 1
                        continue

                    encrypted = encrypt_field(plaintext)

                    # Store the encrypted string back as a JSON text value
                    await conn.execute(
                        """
                        UPDATE processing_sessions
                        SET data = jsonb_set(data, '{facts}', to_jsonb($1::text), true)
                        WHERE id = $2
                        """,
                        encrypted,
                        row["id"],
                    )
                    updated += 1

        logger.info(
            f"encrypt_facts_data: batch {i // _BATCH_SIZE + 1} done "
            f"({min(i + _BATCH_SIZE, total)}/{total})"
        )

    logger.info(
        f"encrypt_facts_data migration complete: "
        f"encrypted={updated}, skipped={skipped}, total_inspected={total}"
    )


# ── CLI entry-point (manual use only) ────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

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
