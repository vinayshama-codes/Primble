"""
One-off rekey: decrypt all enc: values with OLD_FIELD_ENCRYPTION_KEY,
re-encrypt with the new FIELD_ENCRYPTION_KEY, and write back.

Usage:
    cd backend
    OLD_FIELD_ENCRYPTION_KEY="<old>" FIELD_ENCRYPTION_KEY="<new>" DATABASE_URL="..." python scripts/rekey_encryption.py
"""

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_PREFIX = "enc:"


def _build_fernets():
    from cryptography.fernet import Fernet
    old_key = os.environ.get("OLD_FIELD_ENCRYPTION_KEY", "").strip()
    new_key = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if not old_key:
        raise SystemExit("OLD_FIELD_ENCRYPTION_KEY is not set")
    if not new_key:
        raise SystemExit("FIELD_ENCRYPTION_KEY is not set")
    if old_key == new_key:
        raise SystemExit("OLD and NEW keys are identical — nothing to do")
    return Fernet(old_key.encode()), Fernet(new_key.encode())


def _rekey(value: str, old_f, new_f) -> str:
    if not value or not value.startswith(_PREFIX):
        return value
    plaintext = old_f.decrypt(value[len(_PREFIX):].encode())
    return _PREFIX + new_f.encrypt(plaintext).decode()


async def rekey_signatures(old_f, new_f, conn):
    rows = await conn.fetch(
        "SELECT id, signature_data FROM users WHERE signature_data LIKE $1",
        f"{_PREFIX}%",
    )
    logger.info("signatures: %d row(s) to rekey", len(rows))
    rekeyed = 0
    for row in rows:
        try:
            new_val = _rekey(row["signature_data"], old_f, new_f)
            await conn.execute(
                "UPDATE users SET signature_data=$1 WHERE id=$2",
                new_val, row["id"],
            )
            rekeyed += 1
        except Exception as exc:
            logger.error("signatures: failed row id=%s — %s", row["id"], exc)
    logger.info("signatures: rekeyed %d row(s)", rekeyed)


async def rekey_facts(old_f, new_f, conn):
    rows = await conn.fetch(
        """
        SELECT id, data->>'facts' AS facts_raw
        FROM processing_sessions
        WHERE data->>'facts' LIKE $1
        """,
        f"{_PREFIX}%",
    )
    logger.info("facts: %d row(s) to rekey", len(rows))
    rekeyed = 0
    for row in rows:
        try:
            new_val = _rekey(row["facts_raw"], old_f, new_f)
            await conn.execute(
                """
                UPDATE processing_sessions
                SET data = jsonb_set(data, '{facts}', to_jsonb($1::text), true)
                WHERE id = $2
                """,
                new_val, row["id"],
            )
            rekeyed += 1
        except Exception as exc:
            logger.error("facts: failed row id=%s — %s", row["id"], exc)
    logger.info("facts: rekeyed %d row(s)", rekeyed)


async def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dotenv import load_dotenv
    load_dotenv()

    old_f, new_f = _build_fernets()

    from config.database import create_pool, close_pool
    await create_pool()
    try:
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await rekey_signatures(old_f, new_f, conn)
                await rekey_facts(old_f, new_f, conn)
        logger.info("Rekey complete. Now update FIELD_ENCRYPTION_KEY on Render and redeploy.")
    finally:
        await close_pool()


asyncio.run(main())
