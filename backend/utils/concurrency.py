import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import HTTPException

_MAX_HEAVY: int = int(os.getenv("MAX_CONCURRENT_HEAVY_OPS", "3"))
_heavy_sem: asyncio.Semaphore = None


def get_heavy_sem() -> asyncio.Semaphore:
    """Return the global heavy-ops semaphore, creating it lazily on first call.

    Lazy init ensures the Semaphore is bound to the running uvicorn event loop,
    not to whatever loop (if any) exists at import time.
    """
    global _heavy_sem
    if _heavy_sem is None:
        _heavy_sem = asyncio.Semaphore(_MAX_HEAVY)
    return _heavy_sem


async def try_acquire_heavy() -> bool:
    """Non-blocking acquire of the heavy-ops semaphore.

    Returns True and holds the slot if capacity is available.
    Returns False immediately (no wait) if all slots are occupied.

    Atomicity guarantee: asyncio is single-threaded and cooperative. There is
    no await between locked() and acquire(), so no other coroutine can execute
    between them. When locked() is False, CPython's acquire() runs synchronously
    (no internal await) and cannot be cancelled mid-flight.

    Multi-process note: this semaphore is in-process only. With N uvicorn workers
    the effective global limit is MAX_CONCURRENT_HEAVY_OPS * N.
    """
    sem = get_heavy_sem()
    if sem.locked():
        return False
    await sem.acquire()
    return True


def release_heavy() -> None:
    """Release a previously acquired heavy-ops slot."""
    get_heavy_sem().release()


@asynccontextmanager
async def heavy_semaphore():
    """Acquire the heavy-ops semaphore or raise HTTP 429 immediately.

    Raises HTTP 429 with Retry-After: 30 when all slots are occupied.
    Use this for context-manager callsites; use try_acquire_heavy() + release_heavy()
    when the acquire and release happen in different try/finally blocks.
    """
    if not await try_acquire_heavy():
        raise HTTPException(
            status_code=429,
            detail="Server busy — too many concurrent requests. Please retry in 30 seconds.",
            headers={"Retry-After": "30"},
        )
    try:
        yield
    finally:
        release_heavy()
