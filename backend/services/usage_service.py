"""Usage / package counting at SQS-generation time.

Client decision (2026-07-01): a submission consumes ONE usage the moment it is
analysed and an SQS is produced - not only when the package is downloaded. This
closes the loophole where a user could repeatedly generate / regenerate an SQS
(or the forms) to read the extracted data without ever downloading, bypassing
the count entirely.

Counting stays exactly ONCE per processing session, guarded by the session's
`package_counted_at` stamp. Since 2 Nov 2026 the stamp is CLAIMED in one
statement (`session_repository.claim_package_count`), so generation, a download
and the browser's count call can never both count one package, in one process
or across several. Every counting path calls `count_session_usage` - there is no
second copy of the counter.

Per-tier trigger points (decided with the client):
  * professional / business -> when the form-recommendations screen is shown
    (the browser's count call) and, server-side, when forms are generated
  * essentials              -> when the SQS is generated (lite/generate-internal)
  * free                    -> when forms are generated (select-forms-bulk); the
    one free package is RESERVED when generation starts (`reserve_free_package`)

Reprocessing documents / re-uploading creates a brand new session (fresh
`package_counted_at`), so a materially new analysis counts again - and a split
into separate submissions ("Create separate submissions") yields one session,
and therefore one count, per insured.

Overage (2 Nov 2026, M6 / M11 / L9): the package counter is incremented and read
back in one statement, so each package above the allowance + buffer is billed
exactly once. Each overage package is one unit in a ledger (rows of
`processed_webhook_events` keyed "overage_unit:<user>:<session>") and one Stripe
invoice item whose idempotency key is that same unit key. A unit Stripe did not
take stays pending and is retried by the daily lifecycle job and before the next
overage. Nothing is billed while a payment is failing; the paid renewal recounts
the period and bills what is over then.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.database import get_pool
from config.settings import FREE_PACKAGE_LIMIT, default_overage_rate_cents
from repositories.session_repository import (
    claim_package_count, get_processing_session, packages_counted_since,
)
from services.stripe_service import (
    FAILURE_STATUSES, allowance_for, create_overage_invoice_item, overage_unit_already_billed,
)

logger = logging.getLogger(__name__)

# Tiers billed against the package allowance (with Stripe overage). Free is
# metered separately against `downloads_used`.
_PACKAGE_TIERS = ("essentials", "professional", "business")

_UNIT_PREFIX  = "overage_unit:"
_UNIT_BILLING = "overage_billing"    # a Stripe call for it is in flight
_UNIT_PENDING = "overage_pending"    # Stripe did not take it - retried
_UNIT_BILLED  = "overage_billed"
# A package over the allowance of a period recounted while the user's payment
# was failing: owed, billed the moment the user is restored (F1, 2 Nov 2026).
_UNIT_HELD    = "overage_held"
# An in-flight unit older than this was left by a process that died.
_STALE_BILLING = timedelta(hours=1)


def overage_unit_key(user_id, session_id) -> str:
    return f"{_UNIT_PREFIX}{user_id}:{session_id}"


def _rows_changed(status) -> int:
    try:
        return int(str(status).split()[-1])
    except Exception:
        return 0


async def _refresh_user(user_id: str) -> dict | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return dict(row) if row else None


def _billable(row: dict) -> bool:
    """Overage is billed only to a package plan whose payments are not failing
    (2 Nov 2026, M11). 'canceling' still pays for its current period."""
    return ((row.get("subscription_tier") or "free") in _PACKAGE_TIERS
            and (row.get("payment_status") or "ok") not in FAILURE_STATUSES)


# ── the free package (2 Nov 2026, M3 / M-2) ──────────────────────────────────
# The free package is TAKEN when generation starts (one conditional statement,
# so parallel generations cannot all pass the limit), and the reservation is
# tied to its session in the ledger ("free_reservation:<user>:<session>"):
#   reserved -> consumed  when that session's package is counted
#   reserved -> released  when it is given back (the counter goes down once)
# A process that dies mid-generation leaves "reserved": the next generation
# attempt adopts it (same session) or releases it once its session is neither
# counted nor generating (another session). A session that WAS counted never
# gives its reservation back.
_RES_PREFIX   = "free_reservation:"
_RES_RESERVED = "free_reserved"
_RES_CONSUMED = "free_consumed"
_RES_RELEASED = "free_released"


def free_reservation_key(user_id, session_id) -> str:
    return f"{_RES_PREFIX}{user_id}:{session_id}"


async def _ledger_state(conn, key: str):
    row = await conn.fetchrow("SELECT event_type, processed_at FROM processed_webhook_events WHERE event_id=$1", key)
    return dict(row) if row else None


async def _ledger_move(conn, key: str, frm: str, to: str) -> bool:
    status = await conn.execute(
        "UPDATE processed_webhook_events SET event_type=$3 WHERE event_id=$1 AND event_type=$2", key, frm, to)
    return _rows_changed(status) > 0


async def _session_counted(session_id: str) -> bool:
    try:
        return bool((await get_processing_session(session_id)).get("package_counted_at"))
    except Exception:
        return False


async def _forms_saved(session_id: str) -> bool:
    """The run got as far as saving its forms (Q3): the package exists and is
    counted at the latest when it is downloaded - never an abandoned run."""
    try:
        return bool((await get_processing_session(session_id)).get("generated_forms"))
    except Exception:
        return False


async def _generation_live(session_id: str) -> bool:
    """Is a generation of this session running now? (services/generation_state;
    an unreadable job counts as live - never release under a running run)."""
    from services.generation_state import STATE_RUNNING, generation_state
    try:
        session = await get_processing_session(session_id)
    except Exception:
        return False
    jid = session.get("generation_job_id")
    if not jid or session.get("generated_forms"):
        return False
    try:
        from services.job_queue import get_job_queue
        job = await get_job_queue().get_status(str(jid))
    except Exception:
        return True
    return generation_state(session, job) == STATE_RUNNING


async def _decrement_downloads(conn, user_id) -> None:
    await conn.execute(
        "UPDATE users SET downloads_used = CASE WHEN COALESCE(downloads_used, 0) > 0"
        " THEN downloads_used - 1 ELSE 0 END WHERE id = $1",
        user_id,
    )


# ASYNC-SAFE
async def reconcile_free_reservations(user_id: str, keep_session: str | None = None) -> None:
    """Settle reservations a dead run left behind: one whose session was
    counted is consumed; one whose session is not counted and not generating -
    and older than a live run's heartbeat window - is released."""
    from services.generation_state import STALE_AFTER_SECONDS
    grace = (datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_SECONDS)).isoformat()
    prefix = f"{_RES_PREFIX}{user_id}:"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id, processed_at FROM processed_webhook_events"
            " WHERE event_type=$1 AND event_id LIKE $2",
            _RES_RESERVED, prefix + "%",
        )
    for r in [dict(x) for x in rows]:
        sid = r["event_id"][len(prefix):]
        if sid == keep_session or str(r["processed_at"]) > grace:
            continue
        async with get_pool().acquire() as conn:
            if await _session_counted(sid):
                await _ledger_move(conn, r["event_id"], _RES_RESERVED, _RES_CONSUMED)
                continue
        if await _generation_live(sid) or await _forms_saved(sid):
            continue
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                if await _ledger_move(conn, r["event_id"], _RES_RESERVED, _RES_RELEASED):
                    await _decrement_downloads(conn, user_id)
                    logger.info("free reservation of user=%s session=%s released (run died, nothing counted)",
                                user_id, sid)


class reservation_heartbeat:
    """While a free generation runs, its reservation's time is renewed every
    heartbeat (services/generation_state's window), so a run longer than five
    minutes - the lite route has no job to beat - is never taken for a dead
    one (Q3). A run that dies stops beating and is settled five minutes later."""

    def __init__(self, user_id: str, session_id: str, active: bool = True):
        self.key = free_reservation_key(user_id, session_id)
        self.active = active
        self._task = None

    async def _beat(self):
        from services.generation_state import HEARTBEAT_SECONDS
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "UPDATE processed_webhook_events SET processed_at=$2 WHERE event_id=$1 AND event_type=$3",
                        self.key, datetime.now(timezone.utc).isoformat(), _RES_RESERVED)
            except Exception as ex:                                # noqa: BLE001
                logger.warning("reservation heartbeat %s missed: %s", self.key, ex)

    async def __aenter__(self):
        if self.active:
            self._task = asyncio.create_task(self._beat())
        return self

    async def __aexit__(self, *_exc):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:                                  # noqa: BLE001
                pass
        return False


# ASYNC-SAFE
async def free_packages_in_use(user_id: str, session_id: str | None = None) -> int:
    """downloads_used after dead reservations are settled, NOT counting the one
    this session holds (its next run adopts it) - the free gate's number."""
    await reconcile_free_reservations(user_id, keep_session=session_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT COALESCE(downloads_used, 0) AS used FROM users WHERE id=$1", user_id)
        own = await _ledger_state(conn, free_reservation_key(user_id, session_id)) if session_id else None
    used = int((dict(row) if row else {}).get("used") or 0)
    if own and own["event_type"] == _RES_RESERVED:
        used = max(0, used - 1)
    return used


# ASYNC-SAFE
async def holds_free_reservation(user_id: str, session_id: str) -> bool:
    async with get_pool().acquire() as conn:
        own = await _ledger_state(conn, free_reservation_key(user_id, session_id))
    return bool(own and own["event_type"] == _RES_RESERVED)


# ASYNC-SAFE
async def reserve_free_package(user_id: str, session_id: str) -> bool:
    """Take the free package when generation STARTS. False when the allowance
    is spent. The reservation is recorded on its session (a reservation with no
    session could never be settled after a crash - M-2): a second run of the
    same session adopts it."""
    if not session_id:
        raise ValueError("a free reservation needs its session")
    await reconcile_free_reservations(user_id, keep_session=session_id)
    key = free_reservation_key(user_id, session_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            inserted = _rows_changed(await conn.execute(
                "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING", key, _RES_RESERVED, now_iso)) > 0
            if not inserted:
                state = (await _ledger_state(conn, key) or {}).get("event_type")
                if state in (_RES_RESERVED, _RES_CONSUMED):
                    return True                         # adopted (or already counted)
                if not await _ledger_move(conn, key, _RES_RELEASED, _RES_RESERVED):
                    return True
                await conn.execute("UPDATE processed_webhook_events SET processed_at=$2 WHERE event_id=$1",
                                   key, now_iso)
            row = await conn.fetchrow(
                "UPDATE users SET downloads_used = COALESCE(downloads_used, 0) + 1"
                " WHERE id = $1 AND COALESCE(downloads_used, 0) < $2 RETURNING downloads_used",
                user_id, FREE_PACKAGE_LIMIT,
            )
            if not row:
                await conn.execute("UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1",
                                   key, _RES_RELEASED)
                return False
    return True


# ASYNC-SAFE
async def release_free_package(user_id: str, session_id: str) -> None:
    """Give back a reservation whose generation ended before its package was
    counted. A session that WAS counted keeps it (a request cancelled after
    counting must not hand back a package it used). Only a reservation recorded
    on the session moves - never a bare counter decrement."""
    key = free_reservation_key(user_id, session_id)
    if await _session_counted(session_id):
        async with get_pool().acquire() as conn:
            await _ledger_move(conn, key, _RES_RESERVED, _RES_CONSUMED)
        return
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if await _ledger_move(conn, key, _RES_RESERVED, _RES_RELEASED):
                await _decrement_downloads(conn, user_id)


# ── the period a package belongs to (2 Nov 2026, L-3) ────────────────────────
# Stripe's end of the period the package counter belongs to, stored at every
# paid renewal ("billing_period_end:<user>"). A package counted after it -
# between the period's end and the renewal being PAID - belongs to the NEW
# period: it is never billed as overage of the old one; the paid renewal's
# recount places it and bills it if the new allowance is passed.
_PERIOD_PREFIX = "billing_period_end:"


async def record_period_end(conn, user_id, end_iso: str) -> None:
    await conn.execute(
        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
        " VALUES ($1,'billing_period_end',$2)"
        " ON CONFLICT (event_id) DO UPDATE SET processed_at = excluded.processed_at",
        f"{_PERIOD_PREFIX}{user_id}", end_iso,
    )


async def clear_period_end(conn, user_id) -> None:
    """A plan ended or a new one starts: the old period's end is history (Q2)."""
    await conn.execute("DELETE FROM processed_webhook_events WHERE event_id=$1", f"{_PERIOD_PREFIX}{user_id}")


_SUB_PERIOD_PREFIX = "sub_period_end:"


async def record_sub_period_end(conn, sub_id: str, end_iso: str) -> None:
    """An invoice of a subscription no user carries YET (its first invoice is
    often handled before checkout.session.completed): its period end is kept
    for the checkout to pick up - never lost (Q2)."""
    await conn.execute(
        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
        " VALUES ($1,'sub_period_end',$2)"
        " ON CONFLICT (event_id) DO UPDATE SET processed_at = excluded.processed_at",
        f"{_SUB_PERIOD_PREFIX}{sub_id}", end_iso,
    )


async def sub_period_end(conn, sub_id: str):
    row = await conn.fetchrow("SELECT processed_at FROM processed_webhook_events WHERE event_id=$1",
                              f"{_SUB_PERIOD_PREFIX}{sub_id}")
    return dict(row)["processed_at"] if row else None


async def _period_ended(user_id) -> bool:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT processed_at FROM processed_webhook_events WHERE event_id=$1",
                                  f"{_PERIOD_PREFIX}{user_id}")
    if not row:
        return False
    try:
        end = datetime.fromisoformat(str(dict(row)["processed_at"]))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= end
    except Exception:
        return False


# ── counting ─────────────────────────────────────────────────────────────────
async def count_session_usage(user_id: str, session_id: str, *, reserved_free: bool = False) -> dict:
    """Count one usage for this session - the ONE counter (generation, the
    browser's count call and every download path call it).

    Idempotent per session via the claimed `package_counted_at`. The claim and
    the counter move in ONE transaction that first locks the user row, so a
    paid renewal's recount (which takes the same lock) sees each package once
    (2 Nov 2026, L-4). Free -> downloads_used, or the session's reservation;
    package tiers -> packages_used + overage. Never raises on a billing hiccup
    (counting must not block the analysis the user asked for)."""
    claimed = False
    try:
        fresh = await _refresh_user(user_id)
        if not fresh:
            if reserved_free:
                await release_free_package(user_id, session_id)
            return {"counted": False, "reason": "user_not_found"}
        sub = fresh.get("subscription_tier", "free") or "free"

        try:
            proc_session = await get_processing_session(session_id)
        except Exception:
            proc_session = {}
        if proc_session.get("package_counted_at"):
            if reserved_free:
                await release_free_package(user_id, session_id)
            return {"counted": False, "reason": "already_counted"}

        now_iso = datetime.now(timezone.utc).isoformat()
        row = None
        res_key = free_reservation_key(fresh["id"], session_id)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                # The user row's lock (a no-op update holds it to commit).
                await conn.execute("UPDATE users SET packages_used = packages_used WHERE id = $1", fresh["id"])
                claimed = await claim_package_count(session_id, str(fresh["id"]), now_iso, conn=conn)
                if claimed:
                    # Only a reservation this package still HOLDS stands in for
                    # its count: one released meanwhile (a run taken for dead)
                    # counts the package again, so no package is ever free of
                    # the limit (Q3).
                    consumed = await _ledger_move(conn, res_key, _RES_RESERVED, _RES_CONSUMED)
                    if sub == "free":
                        if not consumed:
                            await conn.execute(
                                "UPDATE users SET downloads_used = COALESCE(downloads_used, 0) + 1 WHERE id = $1",
                                fresh["id"],
                            )
                    elif consumed:
                        # Upgraded while the free run went: the plan counts it.
                        await _decrement_downloads(conn, fresh["id"])
                    if sub in _PACKAGE_TIERS:
                        row = await conn.fetchrow(
                            "UPDATE users SET packages_used = COALESCE(packages_used, 0) + 1 WHERE id = $1"
                            " RETURNING id, packages_used, packages_limit, billing_cycle, subscription_tier,"
                            " payment_status, overage_rate, stripe_customer_id, stripe_subscription_id",
                            fresh["id"],
                        )
        if not claimed:
            if reserved_free:
                await release_free_package(user_id, session_id)
            return {"counted": False, "reason": "already_counted"}

        # The counter moved: drop the user's cached /me and auth copies (30 s
        # each), or the screen's refresh reads the old usage (LT-3, 2 Nov 2026).
        try:
            from services.auth_service import invalidate_user_cache
            await invalidate_user_cache(str(fresh["id"]))
        except Exception as ex:                                # noqa: BLE001
            logger.warning("count_session_usage: user cache not cleared for user=%s: %s", fresh["id"], ex)

        if sub == "free":
            logger.info("count_session_usage: counted 1 usage for user=%s session=%s tier=free",
                        fresh["id"], session_id)
            return {"counted": True, "pkg_eval": None}
        if sub not in _PACKAGE_TIERS:
            # Enterprise: stamped, never metered.
            return {"counted": True, "pkg_eval": None}

        pkg_eval = await _evaluate_counted(dict(row) if row else dict(fresh), session_id)
        logger.info("count_session_usage: counted 1 usage for user=%s session=%s tier=%s status=%s",
                    fresh["id"], session_id, sub, (pkg_eval or {}).get("status"))
        return {"counted": True, "pkg_eval": pkg_eval}
    except Exception as ex:
        # Never let a counting failure break form generation / scoring. A free
        # reservation whose package was never stamped goes back - else the
        # package it paid for would be refused at download.
        logger.error("count_session_usage failed for user=%s session=%s: %s", user_id, session_id, ex, exc_info=True)
        if reserved_free and not claimed:
            try:
                await release_free_package(user_id, session_id)
            except Exception as rel_ex:                        # noqa: BLE001
                logger.error("count_session_usage: free reservation not released for user=%s: %s",
                             user_id, rel_ex)
        return {"counted": False, "reason": "error"}


async def _evaluate_counted(row: dict, session_id: str) -> dict:
    """The counter was incremented and read back in the locked transaction: the
    number is this package's own place in the period, so two packages at the
    limit can never both read "within the buffer" (2 Nov 2026, L9)."""
    n = int(row.get("packages_used") or 0)
    pkgs_limit, hard_limit = allowance_for(row)
    if int(row.get("packages_limit") or 0) == 0:
        async with get_pool().acquire() as conn:
            await conn.execute("UPDATE users SET packages_limit=$1 WHERE id=$2 AND COALESCE(packages_limit,0)=0",
                               pkgs_limit, row["id"])
    rate = int(row.get("overage_rate") or default_overage_rate_cents(row.get("subscription_tier") or ""))
    status = "overage" if n > hard_limit else ("soft_buffer" if n > pkgs_limit else "normal")
    pkg_eval = {"status": status, "allow": True, "overage_rate_cents": rate,
                "pkgs_limit": pkgs_limit, "pkgs_used": n, "soft_buffer": hard_limit - pkgs_limit}
    if status == "overage":
        if not _billable(row):
            logger.info("count_session_usage: overage package for user=%s not billed - payment_status=%s;"
                        " the paid renewal recounts the period", row["id"], row.get("payment_status"))
            pkg_eval["billing"] = "not_billable"
        elif await _period_ended(row["id"]):
            logger.info("count_session_usage: overage package for user=%s counted after its period ended"
                        " - the paid renewal places it (L-3)", row["id"])
            pkg_eval["billing"] = "deferred"
        else:
            await retry_pending_overage(str(row["id"]))
            pkg_eval["billing"] = await bill_overage_unit(row, session_id)
    return pkg_eval


# ── the overage ledger ───────────────────────────────────────────────────────
# ASYNC-SAFE
async def bill_overage_unit(row: dict, session_id: str) -> str:
    """Bill ONE overage package, once ever: "billed", "pending" (Stripe did not
    take it - retried later) or "already" (this package was billed or queued)."""
    key = overage_unit_key(row["id"], session_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        claimed = await conn.execute(
            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
            key, _UNIT_BILLING, now_iso,
        )
        if _rows_changed(claimed) == 0:
            # A unit HELD while the user was failing (F1) is billed now - once.
            claimed = await conn.execute(
                "UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1 AND event_type=$3",
                key, _UNIT_BILLING, _UNIT_HELD)
    if _rows_changed(claimed) == 0:
        return "already"
    rate = int(row.get("overage_rate") or default_overage_rate_cents(row.get("subscription_tier") or ""))
    ok = await asyncio.to_thread(create_overage_invoice_item, row, rate, key)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1",
            key, _UNIT_BILLED if ok else _UNIT_PENDING,
        )
        col = "overage_packages_invoiced" if ok else "overage_packages_pending"
        await conn.execute(f"UPDATE users SET {col} = COALESCE({col},0) + 1 WHERE id = $1", row["id"])
    return "billed" if ok else "pending"


async def hold_overage_for_period(conn, user_id: str, counted: list, hard_limit: int) -> int:
    """A renewal recounted the period while the user's payment is still
    failing: the packages above the allowance are recorded as HELD (inside the
    caller's transaction), and billed when the user is restored - by
    invoice.paid, subscription.updated or the daily job (F1)."""
    held = 0
    for session_id, _at in list(counted)[hard_limit:]:
        status = await conn.execute(
            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
            overage_unit_key(user_id, session_id), _UNIT_HELD, datetime.now(timezone.utc).isoformat())
        held += _rows_changed(status)
    return held


# ASYNC-SAFE
async def bill_held_overage(user_id: str) -> int:
    """Bill the overage HELD while the user was failing (F1). Runs on every
    restore; a unit is billed once (its ledger row moves held -> billed)."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id FROM processed_webhook_events WHERE event_type=$1 AND event_id LIKE $2",
            _UNIT_HELD, f"{_UNIT_PREFIX}{user_id}:%")
    if not rows:
        return 0
    row = await _refresh_user(user_id)
    if not row or not _billable(row):
        return 0
    billed = 0
    for r in [dict(x) for x in rows]:
        session_id = r["event_id"][len(f"{_UNIT_PREFIX}{user_id}:"):]
        if await bill_overage_unit(row, session_id) == "billed":
            billed += 1
    if billed:
        logger.info("bill_held_overage: %s overage package(s) held while failing billed for user=%s",
                    billed, user_id)
    return billed


# ASYNC-SAFE
async def bill_overage_for_period(user_id: str, counted: list) -> int:
    """After a paid renewal recounted the period (M11): bill the packages placed
    above the allowance + buffer. A package already billed is skipped by its
    unit key, so this never bills one twice. Returns the number billed."""
    row = await _refresh_user(user_id)
    if not row or not _billable(row):
        return 0
    _, hard_limit = allowance_for(row)
    billed = 0
    for session_id, _at in list(counted)[hard_limit:]:
        if await bill_overage_unit(row, session_id) == "billed":
            billed += 1
    return billed


# ASYNC-SAFE
async def retry_pending_overage(user_id: str | None = None) -> int:
    """Bill the overage units Stripe did not take (M6). Called by the daily
    lifecycle job (every user) and before a user's next overage. A unit is
    claimed before its Stripe call; Stripe is asked whether it already holds the
    unit's item, and the create carries the unit key as its idempotency key - a
    retry can never bill twice. Returns the number billed."""
    prefix = _UNIT_PREFIX + (f"{user_id}:" if user_id else "")
    stale_before = (datetime.now(timezone.utc) - _STALE_BILLING).isoformat()
    try:
        async with get_pool().acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    "SELECT event_id, event_type, processed_at FROM processed_webhook_events"
                    " WHERE event_type = $1 AND event_id LIKE $2",
                    _UNIT_PENDING, prefix + "%",
                )
            else:
                rows = await conn.fetch(
                    "SELECT event_id, event_type, processed_at FROM processed_webhook_events"
                    " WHERE (event_type = $1 OR (event_type = $2 AND processed_at < $3))"
                    "   AND event_id LIKE $4",
                    _UNIT_PENDING, _UNIT_BILLING, stale_before, prefix + "%",
                )
    except Exception as ex:
        logger.error("retry_pending_overage: could not read the ledger: %s", ex)
        return 0
    billed = 0
    users: dict = {}
    for r in [dict(x) for x in rows]:
        key, was = r["event_id"], r["event_type"]
        try:
            uid = key[len(_UNIT_PREFIX):].split(":", 1)[0]
            if uid not in users:
                users[uid] = await _refresh_user(uid)
            user = users[uid]
            if not user or not _billable(user) or not user.get("stripe_customer_id"):
                continue
            async with get_pool().acquire() as conn:
                claimed = await conn.execute(
                    "UPDATE processed_webhook_events SET event_type=$2"
                    " WHERE event_id=$1 AND event_type=$3",
                    key, _UNIT_BILLING, was,
                )
            if _rows_changed(claimed) == 0:
                continue
            since = None
            try:
                since = int(datetime.fromisoformat(str(r["processed_at"])).timestamp()) - 86400
            except Exception:
                pass
            already = await asyncio.to_thread(overage_unit_already_billed, user, key, since)
            if already is None:
                ok = False          # cannot tell what Stripe holds - never guess, try tomorrow
            elif already:
                ok = True
            else:
                rate = int(user.get("overage_rate") or default_overage_rate_cents(user.get("subscription_tier") or ""))
                ok = await asyncio.to_thread(create_overage_invoice_item, user, rate, key)
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "UPDATE processed_webhook_events SET event_type=$2 WHERE event_id=$1",
                    key, _UNIT_BILLED if ok else _UNIT_PENDING,
                )
                if ok:
                    await conn.execute(
                        "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1"
                        + (", overage_packages_pending = CASE WHEN COALESCE(overage_packages_pending,0) > 0"
                           " THEN overage_packages_pending - 1 ELSE 0 END" if was == _UNIT_PENDING else "")
                        + " WHERE id = $1",
                        uid,
                    )
                elif was == _UNIT_BILLING:
                    await conn.execute(
                        "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1"
                        " WHERE id = $1", uid,
                    )
            if ok:
                billed += 1
                logger.info("retry_pending_overage: unit billed for user=%s", uid)
        except Exception as ex:
            logger.error("retry_pending_overage: unit %s not retried: %s", key, ex)
    return billed
