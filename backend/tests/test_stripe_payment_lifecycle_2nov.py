"""Stripe webhooks and the failed-payment lifecycle, offline (2 Nov 2026).

The live Stripe account now runs Smart Retries (up to 8 within 2 weeks) and,
when every retry fails, marks the subscription UNPAID instead of cancelling it.
Stripe's own "card payment failed" e-mail is off; Primble sends its own.
Brent's schedule: day 0 e-mail, day 7 e-mail, day 10 soft_locked + e-mail,
day 21 suspended + e-mail, day 60 archived + e-mail - each e-mail once, and
paying at any point restores access.

These tests drive the real handlers:
- `routes/stripe_routes.stripe_webhook` (called directly with a fake Request),
- `services/scheduler_service.run_daily_payment_lifecycle` (a frozen clock),
- `utils/helpers.check_payment_access`.

Nothing leaves the process. The pool is an asyncpg-shaped fake over an
in-memory sqlite store (stdlib, no file, no server) so the handlers' OWN SQL -
including their `IN` / `NOT IN` stage guards - runs as written; every statement
and its arguments are recorded. Stripe calls, e-mail senders, the audit log and
the user-cache invalidation are fakes; sockets are blocked outright.

The four defects / risks this file first found (a later failure lifting a lock, a
failed stage e-mail never retried, a stale failure re-failing a paying user, a
cancelled free user silently re-locked) were fixed on 2 Nov 2026 and are pinned below.
"""
import asyncio
import hashlib
import hmac
import json
import re
import socket
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
import stripe
from fastapi import HTTPException

import routes.stripe_routes as sr
import services.email_service as email_service
import services.scheduler_service as ss
from utils.helpers import check_payment_access

T0 = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
SECRET = "whsec_offline_test_only"
SUB = "sub_live_1"
CUS = "cus_live_1"
STAGES_LOCKED = ("soft_locked", "suspended", "archived")


# ── no network, ever ──────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_a, **_k):
        raise AssertionError("network access attempted in an offline test")
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(email_service, "_send_generic_email", _refuse)


# ── fake asyncpg pool over an in-memory sqlite store ─────────────────────────
_USERS_DDL = """
CREATE TABLE users (
    id                         TEXT PRIMARY KEY,
    email                      TEXT UNIQUE NOT NULL,
    full_name                  TEXT,
    subscription_tier          TEXT DEFAULT 'free',
    stripe_customer_id         TEXT,
    stripe_subscription_id     TEXT,
    packages_used              INTEGER DEFAULT 0,
    packages_limit             INTEGER DEFAULT 0,
    billing_cycle              TEXT DEFAULT 'monthly',
    billing_period_start       TEXT,
    overage_rate               INTEGER DEFAULT 0,
    payment_status             TEXT DEFAULT 'ok',
    payment_failed_at          TEXT,
    overage_packages_pending   INTEGER DEFAULT 0,
    overage_packages_invoiced  INTEGER DEFAULT 0,
    payment_email_sent_day     INTEGER DEFAULT 0
)"""
_EVENTS_DDL = """
CREATE TABLE processed_webhook_events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    processed_at TEXT NOT NULL
)"""
_PARAM = re.compile(r"\$(\d+)")


class FakeDB:
    def __init__(self):
        self.lite = sqlite3.connect(":memory:", isolation_level=None)
        self.lite.row_factory = sqlite3.Row
        self.lite.execute(_USERS_DDL)
        self.lite.execute(_EVENTS_DDL)
        self.log = []          # (sql, args) of every statement the code ran
        self._sp = 0

    # rows
    def add_user(self, uid="u1", **cols):
        row = {"id": uid, "email": f"{uid}@agency.test", "full_name": f"Producer {uid}",
               "subscription_tier": "professional", "stripe_customer_id": CUS,
               "stripe_subscription_id": SUB, "packages_used": 7, "packages_limit": 20,
               "payment_status": "ok", "overage_packages_pending": 2,
               "overage_packages_invoiced": 1}
        row.update(cols)
        keys = ",".join(row)
        marks = ",".join("?" for _ in row)
        self.lite.execute(f"INSERT INTO users ({keys}) VALUES ({marks})", tuple(row.values()))
        return uid

    def user(self, uid="u1"):
        r = self.lite.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def events(self):
        return [r["event_id"] for r in self.lite.execute("SELECT event_id FROM processed_webhook_events")]

    def user_writes(self):
        return [s for s, _ in self.log if s.lstrip().upper().startswith("UPDATE USERS")]

    # sql
    def run(self, sql, args):
        self.log.append((sql, args))
        cur = self.lite.execute(_PARAM.sub(r"?\1", sql), args)
        return cur

    def savepoint(self):
        self._sp += 1
        return f"sp{self._sp}"


class _Tx:
    def __init__(self, db):
        self.db, self.name = db, None

    async def __aenter__(self):
        self.name = self.db.savepoint()
        self.db.lite.execute(f"SAVEPOINT {self.name}")
        return self

    async def __aexit__(self, exc_type, *_):
        if exc_type is not None:
            self.db.lite.execute(f"ROLLBACK TO {self.name}")
        self.db.lite.execute(f"RELEASE {self.name}")
        return False


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *args):
        cur = self.db.run(sql, args)
        verb = sql.lstrip().split(None, 1)[0].upper()
        return f"INSERT 0 {cur.rowcount}" if verb == "INSERT" else f"{verb} {cur.rowcount}"

    async def fetchrow(self, sql, *args):
        r = self.db.run(sql, args).fetchone()
        return dict(r) if r else None

    async def fetch(self, sql, *args):
        return [dict(r) for r in self.db.run(sql, args).fetchall()]

    def transaction(self):
        return _Tx(self.db)


class _Acquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return FakeConn(self.db)

    async def __aexit__(self, *_):
        return False


class FakePool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _Acquire(self.db)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    pool = FakePool(d)
    monkeypatch.setattr(sr, "get_pool", lambda: pool)
    monkeypatch.setattr(ss, "get_pool", lambda: pool)
    return d


# ── frozen clock (webhook and lifecycle read the same one) ───────────────────
class Clock:
    def __init__(self):
        self.now = T0

    def at(self, days=0, hours=0):
        self.now = T0 + timedelta(days=days, hours=hours)
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return c.now if tz else c.now.replace(tzinfo=None)

    monkeypatch.setattr(sr, "datetime", _Frozen)
    monkeypatch.setattr(ss, "datetime", _Frozen)
    return c


# ── e-mail, audit, cache ──────────────────────────────────────────────────────
class Mail:
    def __init__(self, clock):
        self.sent = []          # (email, day-template, clock-day)
        self.fail_days = set()  # templates whose send returns False
        self.clock = clock

    def __call__(self, email, name, day):
        if day in self.fail_days:
            return False
        self.sent.append((email, day, (self.clock.now - T0).days))
        return True

    def days(self):
        return [d for _, d, _ in self.sent]


@pytest.fixture
def mail(monkeypatch, clock):
    m = Mail(clock)
    monkeypatch.setattr(sr, "_send_payment_failed_email", m)
    monkeypatch.setattr(ss, "_send_payment_failed_email", m)
    return m


@pytest.fixture
def side(monkeypatch):
    rec = {"audit": [], "invalidated": []}

    async def _audit(user, action, **kw):
        rec["audit"].append((str(user.get("id")), action, kw.get("session_id")))

    async def _invalidate(uid):
        rec["invalidated"].append(str(uid))

    monkeypatch.setattr(sr, "write_audit_log", _audit)
    monkeypatch.setattr(sr, "invalidate_user_cache", _invalidate)
    return rec


# ── Stripe ────────────────────────────────────────────────────────────────────
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _List:
    def __init__(self, items):
        self.data = list(items)

    def auto_paging_iter(self):
        return iter(self.data)


class FakeStripe:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []                  # (name, args, kwargs)
        self.active_subs = {}            # customer -> [sub ids]
        self.open_invoices = {}          # customer -> [invoice ids]
        self.pay_days = []               # clock-day of every Invoice.pay
        self.pay_succeeds = False
        # What Subscription.retrieve says (2 Nov 2026: the lifecycle asks Stripe
        # before any lock or stage e-mail). Default: still past due.
        self.sub_status = {}             # sub id -> status
        self.retrieve_fails = False

    def sub_list(self, **kw):
        self.calls.append(("Subscription.list", (), kw))
        ids = self.active_subs.get(kw.get("customer"), []) if kw.get("status") in ("active", None) else []
        return _List(_Obj(id=i, status="active") for i in ids)

    def sub_cancel(self, sid, **kw):
        self.calls.append(("Subscription.cancel", (sid,), kw))

    def sub_modify(self, sid, **kw):
        self.calls.append(("Subscription.modify", (sid,), kw))

    def sub_retrieve(self, sid, **kw):
        self.calls.append(("Subscription.retrieve", (sid,), kw))
        if self.retrieve_fails:
            raise stripe.error.APIConnectionError("Stripe unreachable")
        status = self.sub_status.get(sid, "past_due")
        inv = _Obj(id="in_latest", status="paid" if status == "active" else "open")
        return _Obj(id=sid, status=status, cancel_at_period_end=False, latest_invoice=inv)

    def inv_list(self, **kw):
        self.calls.append(("Invoice.list", (), kw))
        return _List(_Obj(id=i) for i in self.open_invoices.get(kw.get("customer"), []))

    def inv_pay(self, iid, **kw):
        self.calls.append(("Invoice.pay", (iid,), kw))
        self.pay_days.append((self.clock.now - T0).days)
        if not self.pay_succeeds:
            raise stripe.error.CardError("Your card was declined.", None, "card_declined")

    def names(self):
        return [n for n, _, _ in self.calls]


@pytest.fixture
def fake_stripe(monkeypatch, clock):
    f = FakeStripe(clock)
    # A key is configured (never a real one): without it the lifecycle cannot
    # ask Stripe and moves nobody (2 Nov 2026, M9).
    monkeypatch.setattr(stripe, "api_key", "sk_test_offline_only")
    monkeypatch.setattr(stripe.Subscription, "list", f.sub_list)
    monkeypatch.setattr(stripe.Subscription, "cancel", f.sub_cancel)
    monkeypatch.setattr(stripe.Subscription, "modify", f.sub_modify)
    monkeypatch.setattr(stripe.Subscription, "retrieve", f.sub_retrieve)
    monkeypatch.setattr(stripe.Invoice, "list", f.inv_list)
    monkeypatch.setattr(stripe.Invoice, "pay", f.inv_pay)
    monkeypatch.setattr(_STRIPE_NOW, "fake", f)
    return f


class _StripeNow:
    """The fake Stripe the running test uses, so `deliver` can keep it in step
    with the events it sends (2 Nov 2026, M-5: invoice.paid asks Stripe whether
    the plan pays again - as in Stripe, paying the invoice makes it active)."""
    fake = None


_STRIPE_NOW = _StripeNow()


def _mirror_in_stripe(event):
    f = _STRIPE_NOW.fake
    if f is None:
        return
    obj = (event.get("data") or {}).get("object") or {}
    etype = event.get("type")
    if etype in ("invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"):
        sub = obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        if sub:
            f.sub_status[sub] = "past_due" if etype == "invoice.payment_failed" else "active"
    elif etype == "customer.subscription.updated" and obj.get("id"):
        f.sub_status[obj["id"]] = obj.get("status") or "active"


class _Event:
    """What stripe.Webhook.construct_event hands back: str() is the JSON."""
    def __init__(self, raw):
        self.raw = raw

    def __str__(self):
        return self.raw.decode()


@pytest.fixture
def webhook(monkeypatch):
    seen = []

    def _construct(payload, sig, secret):
        seen.append(sig)
        if secret != SECRET or sig != "good":
            raise stripe.error.SignatureVerificationError("No signatures found", sig)
        return _Event(payload)

    monkeypatch.setattr(sr, "STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(stripe.Webhook, "construct_event", _construct)
    return seen


@pytest.fixture
def env(db, clock, mail, side, fake_stripe, webhook):
    return {"db": db, "clock": clock, "mail": mail, "side": side,
            "stripe": fake_stripe}


# ── drivers ───────────────────────────────────────────────────────────────────
class _Req:
    def __init__(self, body, sig="good"):
        self._body = body
        self.headers = {"stripe-signature": sig}

    async def body(self):
        return self._body


def deliver(event, sig="good"):
    if sig == "good":
        _mirror_in_stripe(event)
    return asyncio.run(sr.stripe_webhook(_Req(json.dumps(event).encode(), sig)))


def run_lifecycle(clock, day, hours=1):
    clock.at(days=day, hours=hours)
    asyncio.run(ss.run_daily_payment_lifecycle())


def invoice_event(evt_id, etype="invoice.payment_failed", sub=SUB, cus=CUS, fmt="top",
                  billing_reason="subscription_cycle", created=None):
    inv = {"id": f"in_{evt_id}", "object": "invoice", "customer": cus,
           "billing_reason": billing_reason, "status": "open"}
    if fmt == "top":
        inv["subscription"] = sub
    elif fmt == "parent":    # Stripe API 2025+: no top-level subscription key
        inv["parent"] = {"type": "subscription_details",
                         "subscription_details": {"subscription": sub, "metadata": {}}}
    evt = {"id": evt_id, "object": "event", "type": etype, "data": {"object": inv}}
    if created is not None:
        evt["created"] = int(created.timestamp())
    return evt


def sub_event(evt_id, status, etype="customer.subscription.updated", sub=SUB, cus=CUS,
              cancel_at_period_end=False, metadata=None, created=None):
    evt = {"id": evt_id, "object": "event", "type": etype,
           "data": {"object": {"id": sub, "object": "subscription", "customer": cus,
                               "status": status,
                               "cancel_at_period_end": cancel_at_period_end,
                               "metadata": metadata or {}}}}
    if created is not None:
        evt["created"] = int(created.timestamp())
    return evt


def failed_user(db, stage="failed", day_failed=0, sent=1, **kw):
    """A user already inside the lifecycle (failure recorded `day_failed` days after T0)."""
    return db.add_user(payment_status=stage,
                       payment_failed_at=(T0 + timedelta(days=day_failed)).isoformat(),
                       payment_email_sent_day=sent, **kw)


# ═════════════════════════════════════════════════════════════════════════════
# 1. invoice.payment_failed
# ═════════════════════════════════════════════════════════════════════════════
def test_payment_failed_marks_user_and_sends_day0_email_once(env):
    db, mail, side = env["db"], env["mail"], env["side"]
    db.add_user()
    assert deliver(invoice_event("evt_f1")) == {"received": True}

    u = db.user()
    assert u["payment_status"] == "failed"
    assert u["payment_failed_at"] == T0.isoformat()
    assert u["payment_email_sent_day"] == 1
    assert u["subscription_tier"] == "professional"          # never downgraded
    assert u["stripe_subscription_id"] == SUB
    assert mail.sent == [("u1@agency.test", 1, 0)]
    assert ("u1", "payment.failed", SUB) in side["audit"]
    assert "u1" in side["invalidated"]
    assert db.events() == ["evt_f1"]


def test_duplicate_delivery_of_the_same_event_does_nothing_more(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_f1"))
    writes_after_first = len(db.user_writes())

    env["clock"].at(hours=3)
    assert deliver(invoice_event("evt_f1")) == {"received": True}

    assert mail.days() == [1]
    assert len(db.user_writes()) == writes_after_first      # the user row is not touched
    assert db.events() == ["evt_f1"]
    assert db.user()["payment_failed_at"] == T0.isoformat()


def test_a_smart_retry_failure_keeps_the_day0_clock_and_sends_nothing(env):
    db, mail, clock = env["db"], env["mail"], env["clock"]
    db.add_user()
    deliver(invoice_event("evt_f1"))
    for n, day in enumerate((1, 3, 5, 8), start=2):          # Stripe's retries, new event ids
        clock.at(days=day)
        deliver(invoice_event(f"evt_f{n}"))
    u = db.user()
    assert u["payment_failed_at"] == T0.isoformat()          # COALESCE keeps the first failure
    assert u["payment_status"] == "failed"
    assert mail.days() == [1]


def test_a_failed_day0_send_is_retried_by_the_next_failure_event(env):
    db, mail, clock = env["db"], env["mail"], env["clock"]
    db.add_user()
    mail.fail_days = {1}
    deliver(invoice_event("evt_f1"))
    assert db.user()["payment_email_sent_day"] == 0
    assert mail.sent == []

    mail.fail_days = set()
    clock.at(days=1)
    deliver(invoice_event("evt_f2"))
    assert mail.days() == [1]
    assert db.user()["payment_email_sent_day"] == 1


@pytest.mark.parametrize("fmt", ["top", "parent"])
def test_both_invoice_formats_resolve_the_user(env, fmt):
    db, mail = env["db"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_fmt", fmt=fmt))
    assert db.user()["payment_status"] == "failed"
    assert mail.days() == [1]


def test_an_invoice_with_no_subscription_changes_nothing(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_none", fmt="none"))
    assert db.user()["payment_status"] == "ok"
    assert mail.sent == [] and db.user_writes() == []


def test_fallback_by_customer_when_the_subscription_is_not_stored_yet(env):
    db, mail = env["db"], env["mail"]
    db.add_user(stripe_subscription_id=None)
    deliver(invoice_event("evt_fb"))
    u = db.user()
    assert u["payment_status"] == "failed"
    assert u["stripe_subscription_id"] == SUB               # written back
    assert u["payment_failed_at"] == T0.isoformat()
    assert mail.days() == [1]


def test_fallback_ignores_an_invoice_of_an_older_subscription(env):
    db, mail = env["db"], env["mail"]
    db.add_user(stripe_subscription_id="sub_new")
    deliver(invoice_event("evt_old", sub="sub_old"))
    u = db.user()
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None
    assert u["stripe_subscription_id"] == "sub_new"
    assert mail.sent == []


def test_an_unknown_customer_is_logged_not_written(env):
    db, mail = env["db"], env["mail"]
    db.add_user(stripe_subscription_id="sub_other", stripe_customer_id="cus_other")
    deliver(invoice_event("evt_x"))
    assert db.user()["payment_status"] == "ok"
    assert mail.sent == []


@pytest.mark.parametrize("stage,day", [("soft_locked", 12), ("suspended", 23), ("archived", 63)])
def test_a_later_failure_never_unlocks_a_locked_stage(env, stage, day):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage=stage, sent={"soft_locked": 10, "suspended": 21, "archived": 60}[stage])
    clock.at(days=day)
    deliver(invoice_event(f"evt_retry_{stage}"))
    assert db.user()["payment_status"] == stage


@pytest.mark.parametrize("stage,day,sent", [("soft_locked", 12, 10), ("suspended", 23, 21),
                                            ("archived", 63, 60)])
def test_a_later_failure_keeps_the_lock_and_sends_nothing(env, stage, day, sent):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    failed_user(db, stage=stage, sent=sent)
    clock.at(days=day)
    deliver(invoice_event(f"evt_retry_{stage}"))
    with pytest.raises(HTTPException):
        check_payment_access(db.user()["payment_status"], "upload")
    assert db.user()["payment_failed_at"] == T0.isoformat()
    assert mail.sent == []
    run_lifecycle(clock, day + 1)
    assert db.user()["payment_status"] == stage
    assert mail.sent == []


# ═════════════════════════════════════════════════════════════════════════════
# 2. customer.subscription.updated - past_due
# ═════════════════════════════════════════════════════════════════════════════
def test_past_due_marks_failed_and_starts_the_clock_without_mail(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    deliver(sub_event("evt_pd", "past_due"))
    u = db.user()
    assert u["payment_status"] == "failed"
    assert u["payment_failed_at"] == T0.isoformat()
    assert mail.sent == []          # the e-mail is invoice.payment_failed's job


def test_past_due_then_invoice_failed_sends_day0_once(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    deliver(sub_event("evt_pd", "past_due"))
    env["clock"].at(hours=1)
    deliver(invoice_event("evt_f1"))
    assert mail.days() == [1]
    assert db.user()["payment_failed_at"] == T0.isoformat()


@pytest.mark.parametrize("stage", STAGES_LOCKED)
def test_past_due_never_overwrites_a_later_stage(env, stage):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage=stage, sent=10)
    clock.at(days=15)
    deliver(sub_event(f"evt_pd_{stage}", "past_due"))
    u = db.user()
    assert u["payment_status"] == stage
    assert u["payment_failed_at"] == T0.isoformat()


def test_past_due_keeps_an_earlier_failure_date(env):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="failed")
    clock.at(days=4)
    deliver(sub_event("evt_pd", "past_due"))
    assert db.user()["payment_failed_at"] == T0.isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# 3. customer.subscription.updated - unpaid (the new end-of-retries state)
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("stage,sent", [("failed", 7), ("soft_locked", 10), ("suspended", 21)])
@pytest.mark.parametrize("cancel_at_period_end", [False, True])
def test_unpaid_leaves_the_lifecycle_exactly_as_it_was(env, stage, sent, cancel_at_period_end):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, stage=stage, sent=sent)
    before = db.user()
    clock.at(days=14)
    deliver(sub_event("evt_unpaid", "unpaid", cancel_at_period_end=cancel_at_period_end,
                      metadata={"plan": "professional", "billing_cycle": "monthly"}))
    after = db.user()
    assert after == before          # status, failed_at, sent day, tier, limits, sub id
    assert mail.sent == []
    assert fs.calls == []           # never treated as a cancel (no active-sub check)


def test_unpaid_keeps_brents_schedule_running(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_f1"))
    deliver(sub_event("evt_pd", "past_due"))
    for day in range(1, 14):
        run_lifecycle(clock, day)
    clock.at(days=14)
    deliver(sub_event("evt_unpaid", "unpaid"))
    for day in range(14, 62):
        run_lifecycle(clock, day)
    u = db.user()
    assert u["payment_status"] == "archived"
    assert u["subscription_tier"] == "professional" and u["stripe_subscription_id"] == SUB
    assert [(d, at) for _, d, at in mail.sent] == [(1, 0), (7, 7), (10, 10), (21, 21), (60, 60)]


def test_unpaid_alone_never_starts_the_clock(env):
    """Documents a gap, not a defect today: 'unpaid' writes nothing, so a user whose
    past_due / invoice.payment_failed events never landed stays 'ok' with full access."""
    db = env["db"]
    db.add_user()
    deliver(sub_event("evt_unpaid", "unpaid"))
    u = db.user()
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. run_daily_payment_lifecycle
# ═════════════════════════════════════════════════════════════════════════════
def test_lifecycle_follows_brents_schedule_day_by_day(env):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    db.add_user()
    fs.open_invoices[CUS] = ["in_open_1"]
    deliver(invoice_event("evt_f1"))

    status_by_day = {}
    for day in range(0, 71):
        run_lifecycle(clock, day)
        status_by_day[day] = db.user()["payment_status"]

    assert [(d, at) for _, d, at in mail.sent] == [(1, 0), (7, 7), (10, 10), (21, 21), (60, 60)]
    assert {d for d, s in status_by_day.items() if s == "failed"} == set(range(0, 10))
    assert {d for d, s in status_by_day.items() if s == "soft_locked"} == set(range(10, 21))
    assert {d for d, s in status_by_day.items() if s == "suspended"} == set(range(21, 60))
    assert {d for d, s in status_by_day.items() if s == "archived"} == set(range(60, 71))
    # 2 Nov 2026 (M8): the lifecycle never charges the card itself - Stripe's
    # Smart Retries do (8 within 2 weeks). It used to pay the open invoice on
    # days 2 / 4 / 6 on top of them.
    assert fs.pay_days == []
    assert "Invoice.pay" not in fs.names() and "Invoice.list" not in fs.names()
    assert db.user()["payment_email_sent_day"] == 60


def test_repeated_daily_runs_send_each_email_once(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_f1"))
    for day in range(0, 66):
        for hour in (1, 5, 13):
            run_lifecycle(clock, day, hours=hour)
    assert mail.days() == [1, 7, 10, 21, 60]


def test_a_second_run_on_a_retry_day_never_charges_the_card(env):
    """Was: the silent retry keyed on the day only, so the APScheduler job plus the
    /trigger-lifecycle cron on the same day retried the card twice. 2 Nov 2026 (M8):
    the lifecycle runs once a day and never pays an invoice itself."""
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db)
    fs.open_invoices[CUS] = ["in_open_1"]
    run_lifecycle(clock, 2, hours=1)
    run_lifecycle(clock, 2, hours=8)
    assert fs.pay_days == []


def test_no_silent_retry_on_days_2_4_6(env):
    """2 Nov 2026 (M8): the days 2 / 4 / 6 Invoice.pay retries are gone."""
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, uid="u1")
    failed_user(db, uid="u2", stripe_customer_id=None, stripe_subscription_id="sub_2")
    fs.open_invoices[CUS] = ["in_open_1"]
    for day in (2, 4, 6):
        run_lifecycle(clock, day)
    assert fs.pay_days == []


def test_access_comes_back_when_invoice_paid_lands(env):
    """The lifecycle never pays (2 Nov 2026, M8); access comes back when
    invoice.paid lands."""
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db)
    fs.open_invoices[CUS] = ["in_open_1"]
    fs.pay_succeeds = True
    run_lifecycle(clock, 2)
    assert db.user()["payment_status"] == "failed" and fs.pay_days == []
    clock.at(days=2, hours=2)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    assert db.user()["payment_status"] == "ok"


@pytest.mark.parametrize("start_stage,sent,day,expect_stage,expect_mail", [
    ("failed", 1, 12, "soft_locked", [10]),      # day-7 e-mail skipped
    ("failed", 1, 25, "suspended", [21]),        # day-7 and day-10 skipped
    ("failed", 1, 65, "archived", [60]),         # 7, 10, 21 skipped
    ("soft_locked", 10, 65, "archived", [60]),   # day-21 skipped
    ("failed", 7, 8, "failed", []),              # day-7 already sent, nothing new
])
def test_a_late_first_run_jumps_to_the_current_stage(env, start_stage, sent, day,
                                                     expect_stage, expect_mail):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    failed_user(db, stage=start_stage, sent=sent)
    run_lifecycle(clock, day)
    assert db.user()["payment_status"] == expect_stage
    assert mail.days() == expect_mail
    run_lifecycle(clock, day + 1)
    assert mail.days() == expect_mail                   # still once


def test_a_failed_day7_send_is_retried_the_next_day(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    failed_user(db)
    mail.fail_days = {7}
    run_lifecycle(clock, 7)
    assert db.user()["payment_email_sent_day"] == 1
    mail.fail_days = set()
    run_lifecycle(clock, 8)
    assert mail.days() == [7]


@pytest.mark.parametrize("day,sent_before,stage", [(10, 7, "soft_locked"), (21, 10, "suspended"),
                                                   (60, 21, "archived")])
def test_a_failed_stage_email_is_retried_the_next_day(env, day, sent_before, stage):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    prev = {10: "failed", 21: "soft_locked", 60: "suspended"}[day]
    failed_user(db, stage=prev, sent=sent_before)
    mail.fail_days = {day}
    run_lifecycle(clock, day)
    assert db.user()["payment_status"] == stage
    mail.fail_days = set()
    run_lifecycle(clock, day + 1)
    assert mail.days() == [day]


def test_lifecycle_skips_healthy_and_unreadable_rows_and_keeps_going(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    db.add_user(uid="ok_user", stripe_subscription_id="sub_ok", stripe_customer_id="cus_ok")
    db.add_user(uid="bad_date", stripe_subscription_id="sub_bd", stripe_customer_id="cus_bd",
                payment_status="failed", payment_failed_at="not-a-date")
    failed_user(db, uid="real", stripe_subscription_id="sub_r", stripe_customer_id="cus_r")
    run_lifecycle(clock, 10)
    assert db.user("ok_user")["payment_status"] == "ok"
    assert db.user("bad_date")["payment_status"] == "failed"
    assert db.user("real")["payment_status"] == "soft_locked"
    assert mail.days() == [10]


def test_one_users_error_does_not_stop_the_others(env, monkeypatch):
    db, clock = env["db"], env["clock"]
    failed_user(db, uid="boom", stripe_subscription_id="sub_b", stripe_customer_id="cus_b")
    failed_user(db, uid="fine", stripe_subscription_id="sub_f", stripe_customer_id="cus_f")
    sent = []

    def _mail(email, name, day):
        if email.startswith("boom"):
            raise RuntimeError("smtp down")
        sent.append((email, day))
        return True

    monkeypatch.setattr(ss, "_send_payment_failed_email", _mail)
    run_lifecycle(clock, 10)
    assert db.user("fine")["payment_status"] == "soft_locked"
    assert sent == [("fine@agency.test", 10)]


# ═════════════════════════════════════════════════════════════════════════════
# 5. Recovery: invoice.paid / invoice.payment_succeeded
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("etype", ["invoice.paid", "invoice.payment_succeeded"])
@pytest.mark.parametrize("stage,sent,day", [("failed", 7, 8), ("soft_locked", 10, 15),
                                            ("suspended", 21, 40), ("archived", 60, 90)])
@pytest.mark.parametrize("fmt", ["top", "parent"])
def test_paying_restores_every_stage(env, etype, stage, sent, day, fmt):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    failed_user(db, stage=stage, sent=sent)
    clock.at(days=day)
    deliver(invoice_event(f"evt_pay_{stage}", etype=etype, fmt=fmt))
    u = db.user()
    assert u["payment_status"] == "ok"
    assert u["payment_failed_at"] is None
    assert u["payment_email_sent_day"] == 0
    assert u["packages_used"] == 0
    # 2 Nov 2026 (M6): pending overage (a Stripe call that failed) is billed by
    # its retry, never zeroed by the renewal; the per-period invoiced count resets.
    assert u["overage_packages_pending"] == 2 and u["overage_packages_invoiced"] == 0
    assert u["billing_period_start"] == clock.now.isoformat()
    assert u["subscription_tier"] == "professional" and u["stripe_subscription_id"] == SUB
    check_payment_access(u["payment_status"], "upload")
    check_payment_access(u["payment_status"], "form")
    run_lifecycle(clock, day + 1)
    assert db.user()["payment_status"] == "ok" and mail.sent == []


def test_both_paid_events_for_one_payment_are_harmless(env):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    clock.at(days=12)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    deliver(invoice_event("evt_succ", etype="invoice.payment_succeeded"))
    deliver(invoice_event("evt_paid", etype="invoice.paid"))          # redelivery
    assert db.user()["payment_status"] == "ok"
    # 2 Nov 2026 (L1): the usage reset of each invoice is recorded beside the
    # events ("invoice_reset:<invoice>"); the events themselves are as before.
    assert sorted(e for e in db.events() if e.startswith("evt_")) == ["evt_paid", "evt_succ"]


def test_a_renewal_cycle_paid_does_not_cancel_any_subscription(env):
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, stage="suspended", sent=21)
    clock.at(days=30)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    assert "Subscription.cancel" not in fs.names()


def test_after_recovery_a_new_failure_restarts_the_whole_schedule(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    db.add_user()
    deliver(invoice_event("evt_f1"))
    for day in range(1, 23):
        run_lifecycle(clock, day)
    assert db.user()["payment_status"] == "suspended"
    clock.at(days=23)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    clock.at(days=53)
    deliver(invoice_event("evt_f2"))
    assert db.user()["payment_failed_at"] == clock.now.isoformat()
    for day in range(54, 64):
        run_lifecycle(clock, day)
    assert [(d, at) for _, d, at in mail.sent] == [
        (1, 0), (7, 7), (10, 10), (21, 21),         # first failure
        (1, 53), (7, 60), (10, 63),                 # second failure, fresh schedule
    ]
    assert db.user()["payment_status"] == "soft_locked"


@pytest.mark.parametrize("late", ["invoice", "past_due"])
def test_a_stale_failure_after_payment_does_not_refail_the_user(env, late):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    created = clock.at(days=11)                       # Stripe made the failure here...
    old = (invoice_event("evt_f_old", created=created) if late == "invoice"
           else sub_event("evt_pd_old", "past_due", created=created))
    clock.at(days=12)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    clock.at(days=12, hours=4)                        # ...and redelivered it after the payment
    deliver(old)
    u = db.user()
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None
    assert env["mail"].sent == []


@pytest.mark.parametrize("late", ["invoice", "past_due"])
def test_a_failure_created_after_payment_still_counts(env, late):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    clock.at(days=12)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    created = clock.at(days=40)                       # next renewal fails
    deliver(invoice_event("evt_f_new", created=created) if late == "invoice"
            else sub_event("evt_pd_new", "past_due", created=created))
    u = db.user()
    assert u["payment_status"] == "failed"
    assert u["payment_failed_at"] == created.isoformat()


def test_a_failure_without_a_created_time_is_never_treated_as_stale(env):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    clock.at(days=12)
    deliver(invoice_event("evt_paid", etype="invoice.paid"))
    clock.at(days=40)
    deliver(invoice_event("evt_f_nocreated"))
    assert db.user()["payment_status"] == "failed"


# ═════════════════════════════════════════════════════════════════════════════
# 6. customer.subscription.updated - active
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("stage", ["failed", "soft_locked", "suspended", "canceling"])
def test_active_clears_the_lifecycle(env, stage):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage=stage, sent=10)
    clock.at(days=12)
    deliver(sub_event(f"evt_act_{stage}", "active"))
    u = db.user()
    assert u["payment_status"] == "ok"
    assert u["payment_failed_at"] is None and u["payment_email_sent_day"] == 0
    assert u["packages_used"] == 7               # usage is invoice.paid's job, not this one


def test_active_restores_archived_too(env):
    """Was: 'archived' was missing from the restore list, so a subscription back
    to active WITHOUT an invoice.paid (support voided the overdue invoice) left the
    user archived. 2 Nov 2026 (L-1): paying restores every stage."""
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="archived", sent=60)
    clock.at(days=70)
    deliver(sub_event("evt_act", "active"))
    assert db.user()["payment_status"] == "ok"
    assert db.user()["payment_failed_at"] is None


def test_active_with_cancel_at_period_end_leaves_a_failed_user_alone(env):
    db, clock = env["db"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    clock.at(days=12)
    deliver(sub_event("evt_act", "active", cancel_at_period_end=True))
    assert db.user()["payment_status"] == "soft_locked"


# ═════════════════════════════════════════════════════════════════════════════
# 7. customer.subscription.deleted (a real cancel only)
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("stage", ["ok", "failed", "suspended", "archived"])
def test_deleted_downgrades_to_free_and_clears_the_lifecycle(env, stage):
    db, clock, side, fs = env["db"], env["clock"], env["side"], env["stripe"]
    if stage == "ok":
        db.add_user()
    else:
        failed_user(db, stage=stage, sent=21)
    clock.at(days=30)
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    u = db.user()
    assert u["subscription_tier"] == "free"
    assert u["packages_limit"] == 0 and u["packages_used"] == 0
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None
    assert u["stripe_subscription_id"] is None
    assert ("u1", "payment.subscription_cancelled", SUB) in side["audit"]
    # 2 Nov 2026 (Q5): the plan that ended is judged by the stored subscription
    # alone - Stripe is not asked about the customer's other subscriptions.
    assert "Subscription.list" not in fs.names()
    # A cancel starts the counter afresh (2 Nov 2026).
    assert u["payment_email_sent_day"] == 0


def test_another_live_subscription_never_keeps_the_ended_plans_tier(env):
    """Was: a deletion was skipped while the customer had another active
    subscription (a plan-change race that no longer exists). 2 Nov 2026 (Q5):
    that other subscription is an accidental duplicate whose refund is pending -
    it never keeps a paid tier alive; the stored plan's end downgrades the user."""
    db, fs = env["db"], env["stripe"]
    failed_user(db, stage="suspended", sent=21)
    fs.active_subs[CUS] = ["sub_new"]
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    u = db.user()
    assert u["subscription_tier"] == "free" and u["payment_status"] == "ok"
    assert "evt_del" in db.events()


def test_unpaid_never_takes_the_cancel_path(env):
    db, fs = env["db"], env["stripe"]
    failed_user(db, stage="suspended", sent=21)
    deliver(sub_event("evt_unpaid", "unpaid"))
    assert fs.calls == []
    assert db.user()["subscription_tier"] == "professional"


def test_a_failure_on_a_cancelled_subscription_never_relocks_a_free_user(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    failed_user(db, stage="suspended", sent=21)
    clock.at(days=30)
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    clock.at(days=35)
    deliver(invoice_event("evt_f_late"))
    run_lifecycle(clock, 46)
    assert db.user()["payment_status"] == "ok"


# ═════════════════════════════════════════════════════════════════════════════
# 8. check_payment_access
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status,upload_blocked,form_blocked", [
    ("ok", False, False),
    ("canceling", False, False),
    ("failed", False, False),
    ("soft_locked", True, False),
    ("suspended", True, True),
    ("archived", True, True),
    (None, False, False),
    ("", False, False),
    ("SUSPENDED", True, True),
])
def test_check_payment_access(status, upload_blocked, form_blocked):
    for action, blocked in (("upload", upload_blocked), ("form", form_blocked)):
        if blocked:
            with pytest.raises(HTTPException) as ei:
                check_payment_access(status, action)
            assert ei.value.status_code == 403
        else:
            check_payment_access(status, action)


# ═════════════════════════════════════════════════════════════════════════════
# 9. Signature
# ═════════════════════════════════════════════════════════════════════════════
def test_a_bad_signature_is_400_and_writes_nothing(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    with pytest.raises(HTTPException) as ei:
        deliver(invoice_event("evt_f1"), sig="t=1,v1=forged")
    assert ei.value.status_code == 400 and ei.value.detail == "Invalid webhook signature"
    assert db.log == [] and mail.sent == []


@pytest.mark.parametrize("missing", ["", None])
def test_a_missing_webhook_secret_rejects_before_verifying(env, monkeypatch, missing):
    monkeypatch.setattr(sr, "STRIPE_WEBHOOK_SECRET", missing)
    calls = []

    def _construct(*a, **k):
        calls.append(a)
        raise AssertionError("must not verify without a secret")

    monkeypatch.setattr(stripe.Webhook, "construct_event", _construct)
    env["db"].add_user()
    with pytest.raises(HTTPException) as ei:
        deliver(invoice_event("evt_f1"))
    assert ei.value.status_code == 400 and ei.value.detail == "Webhook secret not configured"
    assert calls == [] and env["db"].log == [] and env["mail"].sent == []


def test_a_malformed_body_is_400(env, monkeypatch):
    monkeypatch.setattr(stripe.Webhook, "construct_event",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad json")))
    with pytest.raises(HTTPException) as ei:
        deliver({"id": "x"})
    assert ei.value.status_code == 400 and ei.value.detail == "Webhook processing error"


def test_the_real_verifier_round_trips_offline(db, clock, mail, side, fake_stripe, monkeypatch):
    """stripe.Webhook.construct_event is pure local HMAC - run the REAL one, so the
    json.loads(str(event)) step is proven on this stripe version (15.x)."""
    monkeypatch.setattr(sr, "STRIPE_WEBHOOK_SECRET", SECRET)
    db.add_user()
    body = json.dumps(invoice_event("evt_real", fmt="parent")).encode()
    ts = int(time.time())
    good = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    asyncio.run(sr.stripe_webhook(_Req(body, sig=f"t={ts},v1={good}")))
    assert db.user()["payment_status"] == "failed" and mail.days() == [1]

    tampered = body.replace(b"evt_real", b"evt_evil")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(sr.stripe_webhook(_Req(tampered, sig=f"t={ts},v1={good}")))
    assert ei.value.status_code == 400 and ei.value.detail == "Invalid webhook signature"
    assert db.events() == ["evt_real"]


def test_an_unhandled_event_type_is_acknowledged_and_ignored(env):
    db, mail = env["db"], env["mail"]
    db.add_user()
    out = deliver(invoice_event("evt_par", etype="invoice.payment_action_required"))
    assert out == {"received": True}
    assert db.user()["payment_status"] == "ok" and mail.sent == []
