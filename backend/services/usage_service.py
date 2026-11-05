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
# Terminal states (3 Nov 2026, pass 4): never billed by any retry.
_UNIT_FORGIVEN = "overage_forgiven"   # held on a plan that ended unpaid (Option A)
_UNIT_MANUAL   = "overage_manual"     # a person was told to bill it by hand
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


async def record_period_end(conn, user_id, end_iso: str, only_later: bool = False) -> None:
    """`only_later`: an OLDER invoice paid late (two open renewals paid after a
    long failure) never moves the stored end back (3 Nov 2026, pass 2 #2)."""
    if only_later:
        row = await conn.fetchrow("SELECT processed_at FROM processed_webhook_events WHERE event_id=$1",
                                  f"{_PERIOD_PREFIX}{user_id}")
        stored, new = _as_dt(dict(row)["processed_at"] if row else None), _as_dt(end_iso)
        if stored is not None and (new is None or new <= stored):
            return
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


async def _stored_period_end(conn, user_id):
    row = await conn.fetchrow("SELECT processed_at FROM processed_webhook_events WHERE event_id=$1",
                              f"{_PERIOD_PREFIX}{user_id}")
    return _as_dt(dict(row)["processed_at"]) if row else None


async def _period_state(conn, user_id) -> str:
    """"ended", "open" (a stored end still ahead) or "unknown" (no end stored)."""
    end = await _stored_period_end(conn, user_id)
    if end is None:
        return "unknown"
    return "ended" if datetime.now(timezone.utc) >= end else "open"


async def _period_ended(user_id) -> bool:
    async with get_pool().acquire() as conn:
        return (await _period_state(conn, user_id)) == "ended"


# ── usage months on annual plans (Brent, 3 Nov 2026) ─────────────────────────
# An annual plan gets its allowance PER MONTH and its extra packages are billed
# monthly. Primble's usage month is anchored on the plan's start (the
# subscription's current period start, recorded at checkout and at each yearly
# renewal): month k starts at anchor + k calendar months, the day clamped to the
# month's end (31 Jan -> 28/29 Feb -> 31 Mar). When a month has ended the counter
# rolls over - lazily, under the user row's lock, before the next package is
# counted, and in the daily job. Monthly plans are untouched: their period is
# still Stripe's renewal. `billing_period_start` keeps meaning "the start of the
# last paid renewal's own period" (the stale-invoice check compares an invoice's
# period start with it; the stale-failure check also reads `last_paid`, the
# paid time - 3 Nov 2026); the month lives in the ledger ("usage_anchor:<user>",
# "usage_month:<user>").
_ANCHOR_PREFIX = "usage_anchor:"
_MONTH_PREFIX = "usage_month:"


def add_months(dt: datetime, k: int) -> datetime:
    """`dt` plus k calendar months, the day clamped to the month's length."""
    import calendar
    total = dt.month - 1 + k
    year, month = dt.year + total // 12, total % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def usage_month_bounds(anchor: datetime, now: datetime) -> tuple:
    """(start, next start) of the usage month `now` falls in. Always counted
    from the anchor - never chained - so a 31st anchor returns to the 31st."""
    if now < anchor:
        return anchor, add_months(anchor, 1)
    k = (now.year - anchor.year) * 12 + (now.month - anchor.month)
    start = add_months(anchor, k)
    while start > now:
        k -= 1
        start = add_months(anchor, k)
    return start, add_months(anchor, k + 1)


def _as_dt(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _upsert_marker(conn, key: str, kind: str, iso: str) -> None:
    await conn.execute(
        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at) VALUES ($1,$2,$3)"
        " ON CONFLICT (event_id) DO UPDATE SET processed_at = excluded.processed_at",
        key, kind, iso)


async def record_usage_anchor(conn, user_id, anchor_iso: str) -> None:
    """A new annual plan, or a yearly renewal: months count from this start,
    and the current usage month is the one it opens."""
    await _upsert_marker(conn, f"{_ANCHOR_PREFIX}{user_id}", "usage_anchor", anchor_iso)
    await _upsert_marker(conn, f"{_MONTH_PREFIX}{user_id}", "usage_month", anchor_iso)


async def clear_usage_months(conn, user_id) -> None:
    await conn.execute("DELETE FROM processed_webhook_events WHERE event_id IN ($1, $2)",
                       f"{_ANCHOR_PREFIX}{user_id}", f"{_MONTH_PREFIX}{user_id}")


async def _marker(conn, key: str):
    row = await conn.fetchrow("SELECT processed_at FROM processed_webhook_events WHERE event_id=$1", key)
    return dict(row)["processed_at"] if row else None


def _is_annual(row: dict) -> bool:
    return ((row.get("billing_cycle") or "") == "annual"
            and (row.get("subscription_tier") or "free") in _PACKAGE_TIERS)


async def _old_period_units(conn, user_id) -> set:
    """Sessions whose overage was billed (or held) in an EARLIER period: they
    stay in that period and are never counted again (the L-3 rule)."""
    rows = await conn.fetch(
        "SELECT event_id FROM processed_webhook_events WHERE event_id LIKE $1"
        " AND event_type IN ('overage_billed','overage_pending','overage_billing','overage_held')",
        f"{_UNIT_PREFIX}{user_id}:%")
    return {dict(r)["event_id"].split(":", 2)[2] for r in rows}


async def roll_usage_month(conn, row: dict, now: datetime | None = None) -> bool:
    """Inside the caller's transaction, AFTER the user row's lock: start the
    current usage month if it has not been started. The new month's count is
    recounted from the packages themselves (a package billed as an earlier
    month's overage stays in that month); several skipped months are one
    rollover. No Stripe call. True when it rolled."""
    if not _is_annual(row):
        return False
    now = now or datetime.now(timezone.utc)
    uid = row["id"]
    anchor = _as_dt(await _marker(conn, f"{_ANCHOR_PREFIX}{uid}")) or _as_dt(row.get("billing_period_start"))
    if anchor is None:
        return False
    month_start, _next = usage_month_bounds(anchor, now)
    current = _as_dt(await _marker(conn, f"{_MONTH_PREFIX}{uid}"))
    if current is not None and current >= month_start:
        return False
    counted = []
    try:
        async with conn.transaction():
            counted = await packages_counted_since(str(uid), month_start.isoformat(), conn=conn)
            old = await _old_period_units(conn, uid)
            counted = [c for c in counted if c[0] not in old]
    except Exception as ex:
        logger.warning("roll_usage_month: could not recount user=%s: %s", uid, type(ex).__name__)
        counted = []
    await conn.execute(
        "UPDATE users SET packages_used=$1, overage_packages_invoiced=0 WHERE id=$2", len(counted), uid)
    await _upsert_marker(conn, f"{_MONTH_PREFIX}{uid}", "usage_month", month_start.isoformat())
    logger.info("usage month rolled for user=%s to %s (%s package(s) already in it)",
                uid, month_start.isoformat(), len(counted))
    return True


async def recount_period(conn, user_id, since_iso: str) -> list:
    """The packages of a period that starts at `since_iso`, from the packages
    themselves, inside the caller's (locked) transaction. A package billed or
    held as an earlier period's overage stays in that period (the L-3 rule)."""
    counted = await packages_counted_since(str(user_id), since_iso, conn=conn)
    old = await _old_period_units(conn, user_id)
    return [c for c in counted if c[0] not in old]


async def start_plan_months(conn, user_id, cycle: str, period_start_iso, period_end_iso) -> None:
    """Every path that writes a plan onto a row (checkout, the plan sync, the
    portal restore, verify-upgrade, the /me resync) leaves what the month logic
    needs (3 Nov 2026): the plan's period end, and on an annual plan the usage
    months anchored on the plan's period start."""
    from datetime import datetime as _dt
    await clear_usage_months(conn, user_id)
    if cycle == "annual":
        await record_usage_anchor(conn, user_id, period_start_iso or _dt.now(timezone.utc).isoformat())
    if period_end_iso:
        await record_period_end(conn, user_id, period_end_iso)
    else:
        await clear_period_end(conn, user_id)


async def adopt_plan_usage(conn, user_id, cycle: str, period_start_iso, period_end_iso) -> int:
    """Inside the caller's transaction: a plan written onto a row from Stripe
    after the fact (the portal restore, the /me resync, verify-upgrade - 3 Nov
    2026) gets everything the month logic needs - the period end, an annual
    plan's months anchored on its period start - and the count of the period
    it is in, recounted from the packages (annual: the current usage month;
    monthly: since the period start). Takes the user row's lock first.
    Returns the count."""
    await conn.execute("UPDATE users SET packages_used = packages_used WHERE id=$1", user_id)
    since = period_start_iso or datetime.now(timezone.utc).isoformat()
    await start_plan_months(conn, user_id, cycle, since, period_end_iso)
    if cycle == "annual":
        fresh = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if fresh and await roll_usage_month(conn, dict(fresh)):
            again = await conn.fetchrow("SELECT packages_used FROM users WHERE id=$1", user_id)
            return int((dict(again) if again else {}).get("packages_used") or 0)
    counted = []
    try:
        async with conn.transaction():
            counted = await recount_period(conn, user_id, since)
    except Exception as ex:                                        # noqa: BLE001
        logger.warning("adopt_plan_usage: could not recount user=%s: %s", user_id, type(ex).__name__)
    await conn.execute("UPDATE users SET packages_used=$1, overage_packages_invoiced=0 WHERE id=$2",
                       len(counted), user_id)
    return len(counted)


# The last time the user was seen paid up (a paid invoice, a restore): a failure
# Stripe created before it is stale (3 Nov 2026, R2 - billing_period_start no
# longer moves for an annual plan's monthly overage invoices).
_LAST_PAID_PREFIX = "last_paid:"


_SWITCH_PREFIX = "plan_switch:"


async def record_plan_switch(conn, user_id, switch_iso: str, old_tier, old_cycle) -> None:
    """A tier sync at `switch_iso`: the plan BEFORE it, named in the alert a
    renewal straddling the switch raises for a person (3 Nov 2026, pass 6 -
    nothing is billed from it). The ledger row's processed_at holds the label."""
    await _upsert_marker(conn, f"{_SWITCH_PREFIX}{user_id}:{switch_iso}", "plan_switch",
                         f"{old_tier or '?'}/{old_cycle or 'monthly'}")


async def plan_switches(conn, user_id, from_iso: str, to_iso: str) -> list:
    """[(switch time, plan before it)] of the switches in (from, to], oldest first."""
    prefix = f"{_SWITCH_PREFIX}{user_id}:"
    rows = await conn.fetch("SELECT event_id, processed_at FROM processed_webhook_events WHERE event_id LIKE $1",
                            prefix + "%")
    lo, hi = _as_dt(from_iso), _as_dt(to_iso)
    out = []
    for r in [dict(x) for x in rows]:
        at = r["event_id"][len(prefix):]
        when = _as_dt(at)
        if when is not None and lo is not None and hi is not None and lo < when <= hi:
            out.append((at, r["processed_at"]))
    return sorted(out, key=lambda p: _as_dt(p[0]))


async def record_last_paid(conn, user_id, iso: str) -> None:
    """Never moves back: callers stamp Stripe's own paid time (3 Nov 2026, L-C),
    so an OLDER payment handled late must not hide a newer one."""
    old, new = _as_dt(await last_paid_at(conn, user_id)), _as_dt(iso)
    if old is not None and new is not None and new <= old:
        return
    await _upsert_marker(conn, f"{_LAST_PAID_PREFIX}{user_id}", "last_paid", iso)


async def last_paid_at(conn, user_id):
    return await _marker(conn, f"{_LAST_PAID_PREFIX}{user_id}")


async def _month_due(row: dict) -> bool:
    """Cheap: two ledger reads, no lock - is a new usage month waiting?"""
    async with get_pool().acquire() as conn:
        anchor = _as_dt(await _marker(conn, f"{_ANCHOR_PREFIX}{row['id']}")) or _as_dt(row.get("billing_period_start"))
        current = _as_dt(await _marker(conn, f"{_MONTH_PREFIX}{row['id']}"))
    if anchor is None:
        return False
    month_start, _next = usage_month_bounds(anchor, datetime.now(timezone.utc))
    return current is None or current < month_start


# ASYNC-SAFE
async def rolled_packages_used(row: dict):
    """The count a screen shows (3 Nov 2026, display): for an annual plan whose
    month has ended, the new month is started first (rare; under the lock), so
    /me and the package limit never show last month's count. Anything else:
    the row's own count."""
    used = int(row.get("packages_used") or 0)
    if not _is_annual(row):
        return used
    try:
        if not await _month_due(row):
            return used
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE users SET packages_used = packages_used WHERE id = $1", row["id"])
                fresh = await conn.fetchrow("SELECT * FROM users WHERE id=$1", row["id"])
                if not fresh:
                    return used
                await roll_usage_month(conn, dict(fresh))
                again = await conn.fetchrow("SELECT packages_used FROM users WHERE id=$1", row["id"])
        return int((dict(again) if again else {}).get("packages_used") or 0)
    except Exception as ex:                                        # noqa: BLE001
        logger.warning("rolled_packages_used: user=%s kept its stored count: %s", row.get("id"), ex)
        return used


# ASYNC-SAFE
async def roll_usage_months_due() -> int:
    """Daily job: every annual account starts its new usage month even when
    quiet, so the screens show the new month's count."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT id FROM users WHERE billing_cycle='annual' AND subscription_tier IN"
                                " ('essentials','professional','business')")
    rolled = 0
    for r in [dict(x) for x in rows]:
        try:
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    await conn.execute("UPDATE users SET packages_used = packages_used WHERE id = $1", r["id"])
                    fresh = await conn.fetchrow("SELECT * FROM users WHERE id=$1", r["id"])
                    if fresh and await roll_usage_month(conn, dict(fresh)):
                        rolled += 1
        except Exception as ex:
            logger.error("roll_usage_months_due: user=%s not rolled: %s", r["id"], ex)
    return rolled


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
        period_at_count = None
        held_in_count = False
        res_key = free_reservation_key(fresh["id"], session_id)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                # The user row's lock (a no-op update holds it to commit).
                await conn.execute("UPDATE users SET packages_used = packages_used WHERE id = $1", fresh["id"])
                # An annual plan's new usage month starts before this package
                # is counted, so the package lands in the month it was made in.
                await roll_usage_month(conn, fresh)
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
                        # The period this package was counted in, read under the
                        # same lock: a renewal's reset committing right after this
                        # transaction never makes it look like the OLD period's
                        # overage (3 Nov 2026, pass 4 #6).
                        period_at_count = await _period_state(conn, fresh["id"])
                        # A package to HOLD is written here, under the same lock
                        # and in the same transaction as its count (3 Nov 2026,
                        # pass 5 #1): a restore (which releases held units) or a
                        # plan's end (which forgives them) committing right after
                        # this one always sees it.
                        if row:
                            held_in_count = await _hold_in_count(conn, dict(row), session_id, period_at_count)
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

        pkg_eval = await _evaluate_counted(dict(row) if row else dict(fresh), session_id,
                                           period_state=period_at_count, held=held_in_count)
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


def _should_hold(row: dict, period_state) -> bool:
    """An overage package of a user who cannot be billed now is HELD when the
    counter is the period's own count: an annual plan's month, or a monthly
    plan failing MID-period (its stored end still ahead - pass 4 #5). With the
    period ended, or no end stored, the counter may still carry an unpaid
    earlier period: left to the paid renewal's recount."""
    return not _billable(row) and (_is_annual(row) or period_state == "open")


async def _hold_in_count(conn, row: dict, session_id: str, period_state) -> bool:
    """Inside the counting transaction: record the package HELD when it is an
    overage package that must be held (pass 5 #1). True when it is held."""
    n = int(row.get("packages_used") or 0)
    _limit, hard_limit = allowance_for(row)
    if n <= hard_limit or not _should_hold(row, period_state):
        return False
    await conn.execute(
        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
        " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
        overage_unit_key(row["id"], session_id), _UNIT_HELD, datetime.now(timezone.utc).isoformat())
    return True


async def _evaluate_counted(row: dict, session_id: str, period_state: str | None = None,
                            held: bool = False) -> dict:
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
        if period_state is None:
            async with get_pool().acquire() as conn:
                period_state = await _period_state(conn, row["id"])
        # A monthly plan failing MID-period (a proration / manual invoice): the
        # counter is this period's own count while its stored end is still
        # ahead, so the package is HELD like an annual one and billed on the
        # restore - no renewal recount would ever place it (pass 4 #5). With
        # the period ended, or no end stored, the counter may still carry an
        # unpaid earlier period: left to the paid renewal's recount.
        if held or _should_hold(row, period_state):
            # Held (F1): billed when the user is restored. Written in the
            # counting transaction when the count came through it (pass 5 #1).
            if not held:
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
                        " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING",
                        overage_unit_key(row["id"], session_id), _UNIT_HELD,
                        datetime.now(timezone.utc).isoformat())
            logger.info("count_session_usage: overage package for user=%s held - payment_status=%s",
                        row["id"], row.get("payment_status"))
            pkg_eval["billing"] = "held"
        elif not _billable(row):
            logger.info("count_session_usage: overage package for user=%s not billed - payment_status=%s;"
                        " the paid renewal recounts the period", row["id"], row.get("payment_status"))
            pkg_eval["billing"] = "not_billable"
        elif period_state == "ended":
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


async def place_period_overage(conn, user_id: str, counted: list, hard_limit: int, *, hold: bool) -> int:
    """Inside the caller's (locked) transaction: record the packages of a
    recounted period that sit above the allowance + buffer - HELD while the
    user is still failing, else PENDING (the daily retry bills a pending unit
    whatever happens after the commit; 3 Nov 2026, pass 3 #4).

    Never double: a unit already in the ledger (any state) is not recorded
    again, and the period never gets more new units than its extras minus the
    units the ledger already holds for its packages - a package billed at count
    time under a different place in the counter still counts against the
    period's extras (pass 3 #2). Returns the number of units recorded."""
    extras = list(counted)[hard_limit:]
    if not extras:
        return 0
    prefix = f"{_UNIT_PREFIX}{user_id}:"
    rows = await conn.fetch("SELECT event_id FROM processed_webhook_events WHERE event_id LIKE $1", prefix + "%")
    in_ledger = {dict(r)["event_id"] for r in rows}
    period_keys = {overage_unit_key(user_id, sid) for sid, _at in counted}
    budget = len(extras) - len(period_keys & in_ledger)
    state = _UNIT_HELD if hold else _UNIT_PENDING
    now_iso = datetime.now(timezone.utc).isoformat()
    placed = 0
    for session_id, _at in extras:
        if budget <= 0:
            break
        key = overage_unit_key(user_id, session_id)
        if key in in_ledger:
            continue
        status = await conn.execute(
            "INSERT INTO processed_webhook_events (event_id, event_type, processed_at)"
            " VALUES ($1,$2,$3) ON CONFLICT (event_id) DO NOTHING", key, state, now_iso)
        if _rows_changed(status):
            placed += 1
            budget -= 1
    if placed and not hold:
        await conn.execute("UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + $2"
                           " WHERE id = $1", user_id, placed)
    return placed


async def forgive_held_overage(conn, user_id: str) -> int:
    """Inside the transaction that claims a plan's final bill: units HELD while
    that plan was failing are never billed (Option A - a plan that ended
    unpaid), so they leave the held state for good and no later restore of
    ANOTHER plan bills them (3 Nov 2026, pass 4 #3)."""
    status = await conn.execute(
        "UPDATE processed_webhook_events SET event_type=$1 WHERE event_type=$2 AND event_id LIKE $3",
        _UNIT_FORGIVEN, _UNIT_HELD, f"{_UNIT_PREFIX}{user_id}:%")
    return _rows_changed(status)


async def release_held_overage(conn, user_id: str) -> int:
    """Inside a restore's transaction: the user pays again, so the units HELD
    while failing become PENDING - billed right after the commit, and by the
    daily retry if that fails (3 Nov 2026, pass 3 #4). Returns how many."""
    status = await conn.execute(
        "UPDATE processed_webhook_events SET event_type=$1 WHERE event_type=$2 AND event_id LIKE $3",
        _UNIT_PENDING, _UNIT_HELD, f"{_UNIT_PREFIX}{user_id}:%")
    moved = _rows_changed(status)
    if moved:
        await conn.execute("UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + $2"
                           " WHERE id = $1", user_id, moved)
    return moved


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
