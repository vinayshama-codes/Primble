import logging
from typing import Optional

from config.database import get_pool

logger = logging.getLogger(__name__)


# ASYNC-SAFE
async def get_user_by_id(user_id: str) -> Optional[dict]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None


# ASYNC-SAFE
async def get_user_by_email(email: str) -> Optional[dict]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        return dict(row) if row else None


# ASYNC-SAFE
async def get_fresh_user(user_id: str) -> Optional[dict]:
    return await get_user_by_id(user_id)
