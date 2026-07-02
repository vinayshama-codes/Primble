"""Usage / package counting at SQS-generation time.

Client decision (2026-07-01): a submission consumes ONE usage the moment it is
analysed and an SQS is produced - not only when the package is downloaded. This
closes the loophole where a user could repeatedly generate / regenerate an SQS
(or the forms) to read the extracted data without ever downloading, bypassing
the count entirely.

Counting stays exactly ONCE per processing session, guarded by the existing
`package_counted_at` flag on the session. Because the download-time counters in
download_routes.py are guarded by the same flag, whichever path fires first wins
and the other becomes a no-op - so no double counting, and old sessions that were
never counted at generation still count on download as a fallback.

Per-tier trigger points (decided with the client):
  * professional / business -> when the form-recommendations screen is shown
  * essentials              -> when the SQS is generated (lite/generate-internal)
  * free                    -> when forms are generated (select-forms-bulk)

Reprocessing documents / re-uploading creates a brand new session (fresh
`package_counted_at`), so a materially new analysis counts again - and a split
into separate submissions ("Create separate submissions") yields one session,
and therefore one count, per insured.
"""

import logging
import time
from datetime import datetime, timezone

from config.database import get_pool
from repositories.session_repository import get_processing_session, upd_processing_session
from services.stripe_service import evaluate_package_limit, create_overage_invoice_item

logger = logging.getLogger(__name__)

# Same 5-minute rapid-retry window used by the download-time dedup.
_DEDUP_WINDOW_SECONDS = 300

try:
    from utils.rate_limiter import _redis as _usage_redis
except Exception:  # pragma: no cover - Redis optional
    _usage_redis = None

_dedup_seen: dict = {}

# Tiers billed against the package allowance (with Stripe overage). Free is
# metered separately against `downloads_used`.
_PACKAGE_TIERS = ("essentials", "professional", "business")


async def _acquire_usage_lock(user_id: str, session_id: str) -> bool:
    """Return True (and take the lock) for a fresh count; False for a duplicate.

    Guards against a rapid double-fire of the SAME generation event (e.g. the
    recommendations effect running twice). Cross-path dedup (generation vs.
    download) is handled by the persisted `package_counted_at` flag, re-checked
    under this lock below.
    """
    key = f"usage_counted:{user_id}:{session_id}"
    now = time.time()

    if _usage_redis is not None:
        try:
            acquired = await _usage_redis.set(key, "1", nx=True, ex=_DEDUP_WINDOW_SECONDS)
            return bool(acquired)
        except Exception as ex:
            logger.warning("usage dedup Redis error, using in-process fallback: %s", ex)

    stale = [k for k, exp in list(_dedup_seen.items()) if exp <= now]
    for k in stale:
        del _dedup_seen[k]
    if key in _dedup_seen:
        return False
    _dedup_seen[key] = now + _DEDUP_WINDOW_SECONDS
    return True


async def _refresh_user(user_id: str) -> dict | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return dict(row) if row else None


async def count_session_usage(user_id: str, session_id: str) -> dict:
    """Count one usage for this session at SQS/recommendation generation time.

    Idempotent per session via `package_counted_at`. Mirrors the download-time
    counting (free -> downloads_used; paid -> packages_used + Stripe overage) so
    the later download simply skips. Returns a small status dict; never raises on
    a billing hiccup (counting must not block the analysis the user asked for).
    """
    try:
        fresh = await _refresh_user(user_id)
        if not fresh:
            return {"counted": False, "reason": "user_not_found"}
        sub = fresh.get("subscription_tier", "free") or "free"

        # Fast path: already counted for this session (download or a prior
        # generation event) -> nothing to do.
        proc_session = await get_processing_session(session_id)
        if proc_session.get("package_counted_at"):
            return {"counted": False, "reason": "already_counted"}

        pkg_eval = None
        if sub in _PACKAGE_TIERS:
            pkg_eval = await evaluate_package_limit(fresh)

        if not await _acquire_usage_lock(fresh["id"], session_id):
            return {"counted": False, "reason": "locked"}

        # Re-check under the lock against the freshest session state to shrink the
        # window where a concurrent download could also have counted.
        proc_session = await get_processing_session(session_id)
        if proc_session.get("package_counted_at"):
            return {"counted": False, "reason": "already_counted"}

        now_iso = datetime.now(timezone.utc).isoformat()
        await upd_processing_session(session_id, {"package_counted_at": now_iso})

        async with get_pool().acquire() as conn:
            if sub == "free":
                await conn.execute(
                    "UPDATE users SET downloads_used = COALESCE(downloads_used, 0) + 1 WHERE id = $1",
                    fresh["id"],
                )
            elif sub in _PACKAGE_TIERS and pkg_eval:
                await conn.execute(
                    "UPDATE users SET packages_used = COALESCE(packages_used, 0) + 1 WHERE id = $1",
                    fresh["id"],
                )
                if pkg_eval["status"] == "overage":
                    stripe_queued = create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
                    if stripe_queued:
                        await conn.execute(
                            "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )
                    else:
                        await conn.execute(
                            "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )

        logger.info(
            "count_session_usage: counted 1 usage for user=%s session=%s tier=%s",
            fresh["id"], session_id, sub,
        )
        return {"counted": True, "pkg_eval": pkg_eval}
    except Exception as ex:
        # Never let a counting failure break form generation / scoring.
        logger.error("count_session_usage failed for user=%s session=%s: %s", user_id, session_id, ex, exc_info=True)
        return {"counted": False, "reason": "error"}
