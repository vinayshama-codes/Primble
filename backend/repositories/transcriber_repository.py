"""Transcriber results cache + page usage counter (29 Oct 2026, ASG_TRANSCRIBER.md 7.4).

Two tables, both created by `config.database.init_db`:
  transcriber_results(content_hash PK, env, request_id, form_numbers, pages, body, created_at)
      body = the parsed result as JSON, field-encrypted - a re-upload of the same bytes
      (any package, any user) answers from here and never calls ASG again.
  transcriber_usage(day, env, pages, requests, PK(day, env))
      the running page count the client checks against TRANSCRIBER_DAILY_PAGE_CAP.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config.database import get_pool

logger = logging.getLogger(__name__)


def _enc(text: str) -> str:
    from utils.crypto import encrypt_field
    return encrypt_field(text) or ""


def _dec(text: Any) -> Optional[str]:
    from utils.crypto import decrypt_field_soft
    return decrypt_field_soft(text) if text else None


async def get_cached(content_hash: str, env: str) -> Optional[dict]:
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT body FROM transcriber_results WHERE content_hash=$1 AND env=$2", content_hash, env)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("transcriber cache read failed: %s", ex)
        return None
    if not row:
        return None
    raw = _dec(row["body"])
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


async def put_cached(content_hash: str, env: str, result: dict, *, pages: int, form_numbers: str) -> None:
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO transcriber_results (content_hash, env, request_id, form_numbers, pages, body, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (content_hash, env) DO UPDATE SET body=EXCLUDED.body, request_id=EXCLUDED.request_id,
                       form_numbers=EXCLUDED.form_numbers, pages=EXCLUDED.pages""",
                content_hash, env, str(result.get("request_id") or ""), form_numbers, int(pages),
                _enc(json.dumps(result, separators=(",", ":"), default=str)),
                datetime.now(timezone.utc).isoformat())
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("transcriber cache write failed: %s", ex)


async def add_usage(pages: int, env: str) -> int:
    """Add `pages` to today's count and return the new total (UTC day). A negative
    `pages` is a refund (a submit that never reached ASG) and counts no request."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO transcriber_usage (day, env, pages, requests) VALUES ($1, $2, $3, $4)
                   ON CONFLICT (day, env) DO UPDATE SET
                       pages = GREATEST(0, transcriber_usage.pages + EXCLUDED.pages),
                       requests = transcriber_usage.requests + EXCLUDED.requests
                   RETURNING pages""", day, env, int(pages), 1 if int(pages) > 0 else 0)
            return int(row["pages"]) if row else int(pages)
    except Exception as ex:                                    # noqa: BLE001
        # FAIL CLOSED (review, 29 Oct 2026): with no counter the daily cap cannot
        # hold, so nothing is sent - the upload falls back to today's reading.
        logger.warning("transcriber usage write failed - refusing to send: %s", ex)
        return 10 ** 9 if int(pages) > 0 else 0          # asg_transcriber.USAGE_UNAVAILABLE


async def usage_summary(days: int = 30) -> Dict[str, Any]:
    try:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT day, env, pages, requests FROM transcriber_usage ORDER BY day DESC LIMIT $1", int(days) * 2)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("transcriber usage read failed: %s", ex)
        return {"days": [], "total_pages": 0}
    out = [dict(r) for r in rows]
    return {"days": out, "total_pages": sum(int(r["pages"]) for r in out)}
