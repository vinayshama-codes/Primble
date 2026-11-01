"""Hold a BIG PDF back while the server's memory is nearly full.

The safety net behind page clearing (MULTI_USER_READINESS_1NOV2026.md). Render
killed the server with "Ran out of memory (used over 2GB)" on 1 Nov 2026 when three
271-page packages were read together. The file waits on disk, which costs nothing,
and the user keeps their normal spinner. A small file never waits, and neither does
anything else on the server. Not knowing the memory limit means never waiting.
"""
import asyncio
import logging
import os
import time
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_BIG_FILE_BYTES = int(float(os.getenv("MEMORY_GUARD_BIG_FILE_MB", "2")) * 1024 * 1024)
_HIGH_WATER = float(os.getenv("MEMORY_GUARD_HIGH_WATER", "0.75"))
_MAX_WAIT_S = float(os.getenv("MEMORY_GUARD_MAX_WAIT_S", "180"))
_POLL_S = 2.0
_START_GAP_S = 5.0
_BIG_FILE_PAGES = int(os.getenv("MEMORY_GUARD_BIG_FILE_PAGES", "100"))
_CGROUP = os.getenv("MEMORY_GUARD_CGROUP_DIR", "/sys/fs/cgroup")


def _read_int(path: str) -> Optional[int]:
    try:
        with open(path, encoding="ascii") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):       # absent, or "max" (no limit)
        return None


def _inactive_file(stat_path: str) -> int:
    """Page cache the kernel gives back on demand: not memory we are short of."""
    try:
        with open(stat_path, encoding="ascii") as fh:
            for line in fh:
                key, _, val = line.partition(" ")
                if key in ("inactive_file", "total_inactive_file"):
                    return int(val)
    except (OSError, ValueError):
        pass
    return 0


def memory_state() -> Optional[tuple]:
    """(bytes in use, limit in bytes), or None when the limit cannot be known.
    Reads the container's own limit, never the host machine's size."""
    for used, limit, stat in (
            ("memory.current", "memory.max", "memory.stat"),                     # cgroup v2
            ("memory/memory.usage_in_bytes", "memory/memory.limit_in_bytes",     # cgroup v1
             "memory/memory.stat")):
        u = _read_int(os.path.join(_CGROUP, used))
        m = _read_int(os.path.join(_CGROUP, limit))
        # cgroup v1 reports "no limit" as an enormous number.
        if u is not None and m and m < 1 << 50:
            return max(0, u - _inactive_file(os.path.join(_CGROUP, stat))), m
    return None


def memory_is_tight() -> bool:
    state = memory_state()
    return bool(state) and state[0] >= _HIGH_WATER * state[1]


_GATE: Optional[asyncio.Lock] = None
_GATE_LOOP = None


def _gate() -> asyncio.Lock:
    global _GATE, _GATE_LOOP
    loop = asyncio.get_running_loop()
    if _GATE is None or _GATE_LOOP is not loop:
        _GATE, _GATE_LOOP = asyncio.Lock(), loop
    return _GATE


def _is_big(path: str) -> bool:
    """By bytes, then pages: a 209 KB package can still be a long read."""
    if not str(path).lower().endswith(".pdf"):
        return False
    if os.path.getsize(path) >= _BIG_FILE_BYTES:
        return True
    try:
        import fitz
        with fitz.open(path) as doc:
            return doc.page_count >= _BIG_FILE_PAGES
    except Exception:                                          # noqa: BLE001
        return False


async def wait_for_room(paths: Iterable[str]) -> None:
    """Return once these files may be read. Never raises and never refuses: after
    `_MAX_WAIT_S` it goes ahead, because a stuck upload is worse than a tight moment.
    Only a big PDF can wait. Waiting files are let go one at a time, with a pause, so
    they do not all see the same free memory and start together."""
    try:
        if isinstance(paths, str):
            paths = [paths]
        if not memory_is_tight():
            return
        big = False
        for path in paths:
            if await asyncio.to_thread(_is_big, path):
                big = True
                break
        if not big:
            return
        started = time.monotonic()
        logger.info("MEMORY_GUARD_HOLD a big PDF is waiting for memory")
        async with _gate():
            while memory_is_tight() and time.monotonic() - started < _MAX_WAIT_S:
                await asyncio.sleep(_POLL_S)
            await asyncio.sleep(_START_GAP_S)    # let it allocate before the next one looks
        logger.info("MEMORY_GUARD_RELEASE after %.0fs still_tight=%s",
                    time.monotonic() - started, memory_is_tight())
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("memory guard skipped: %s", ex)


def log_startup_state() -> None:
    """Say whether the guard can work here: with no readable limit it never holds."""
    state = memory_state()
    if state:
        logger.info("MEMORY_GUARD active limit_mb=%d in_use_mb=%d", state[1] // 1048576, state[0] // 1048576)
    else:
        logger.warning("MEMORY_GUARD inactive: this server reports no memory limit")
