"""Stripe live-readiness fixes, offline (2 Nov 2026).

Every item of the 2 Nov billing review that was decided for building (B1, H1-H4,
M1-M3, M5-M11, L1-L5, L7-L9) has a test here, plus the eleven offline
reproductions of the review (R1-R11) turned around to assert the CORRECT
behaviour. Nothing leaves the process: the database is an in-memory sqlite store
behind an asyncpg-shaped pool (the handlers' own SQL runs as written), Stripe and
the e-mail sender are fakes, and sockets are blocked.
"""
import ast
import asyncio
import json
import logging
import pathlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
import stripe
from fastapi import HTTPException

import repositories.audit_repository as audit_repo
import routes.auth_routes as ar
import routes.stripe_routes as sr
import services.email_service as email_service
import services.scheduler_service as ss
import services.stripe_service as svc
import services.usage_service as us
from tests.test_stripe_payment_lifecycle_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, _Obj, _Req, clock, deliver, invoice_event, mail, side, sub_event,
    webhook,
)
from utils.helpers import ARCHIVED_MESSAGE, check_payment_access

ROOT = pathlib.Path(__file__).resolve().parents[1]
_PARAM = __import__("re").compile(r"\$(\d+)")


# ── database: the users row, the idempotency / ledger table, sessions ────────
_DDL = [
    """CREATE TABLE users (
        id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, full_name TEXT, password_hash TEXT,
        subscription_tier TEXT DEFAULT 'free', stripe_customer_id TEXT, stripe_subscription_id TEXT,
        downloads_used INTEGER DEFAULT 0, packages_used INTEGER DEFAULT 0, packages_limit INTEGER DEFAULT 0,
        billing_cycle TEXT DEFAULT 'monthly', billing_period_start TEXT, overage_rate INTEGER DEFAULT 0,
        payment_status TEXT DEFAULT 'ok', payment_failed_at TEXT,
        overage_packages_pending INTEGER DEFAULT 0, overage_packages_invoiced INTEGER DEFAULT 0,
        payment_email_sent_day INTEGER DEFAULT 0)""",
    "CREATE TABLE processed_webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,"
    " processed_at TEXT NOT NULL)",
    "CREATE TABLE applied_overage_sessions (stripe_session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
    " qty INTEGER NOT NULL, applied_at TEXT NOT NULL)",
]
# Tables delete-account clears (only the columns its SQL names).
for _t in ("sessions", "processing_sessions", "arq_sessions", "signature_requests",
           "fact_lineage", "arq_assistant_usage"):
    _DDL.append(f"CREATE TABLE {_t} (id TEXT, user_id TEXT)")
_DDL.append("CREATE TABLE session_pdf_bytes (session_id TEXT)")
_DDL.append("CREATE TABLE acord_audit_log (user_id TEXT, user_email TEXT, organization_name TEXT)")


class DB:
    def __init__(self):
        self.lite = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.lite.row_factory = sqlite3.Row
        for ddl in _DDL:
            self.lite.execute(ddl)
        self.log = []
        self._sp = 0

    def add_user(self, uid="u1", **cols):
        row = {"id": uid, "email": f"{uid}@agency.test", "full_name": f"Producer {uid}",
               "subscription_tier": "professional", "stripe_customer_id": CUS,
               "stripe_subscription_id": SUB, "packages_used": 0, "packages_limit": 100,
               "overage_rate": 300, "payment_status": "ok"}
        row.update(cols)
        self.lite.execute(f"INSERT INTO users ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                          tuple(row.values()))
        return uid

    def user(self, uid="u1"):
        r = self.lite.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def keys(self, prefix=""):
        return {r["event_id"]: r["event_type"] for r in
                self.lite.execute("SELECT event_id, event_type FROM processed_webhook_events")
                if r["event_id"].startswith(prefix)}

    def run(self, sql, args):
        self.log.append((sql, args))
        return self.lite.execute(_PARAM.sub(r"?\1", sql), args)


class _Tx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db._sp += 1
        self.name = f"sp{self.db._sp}"
        self.db.lite.execute(f"SAVEPOINT {self.name}")
        return self

    async def __aexit__(self, exc_type, *_):
        if exc_type is not None:
            self.db.lite.execute(f"ROLLBACK TO {self.name}")
        self.db.lite.execute(f"RELEASE {self.name}")
        return False


class Conn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *args):
        cur = self.db.run(sql, args)
        verb = sql.lstrip().split(None, 1)[0].upper()
        return f"INSERT 0 {cur.rowcount}" if verb == "INSERT" else f"{verb} {cur.rowcount}"

    async def fetchrow(self, sql, *args):
        rows = self.db.run(sql, args).fetchall()
        return dict(rows[0]) if rows else None

    async def fetch(self, sql, *args):
        return [dict(r) for r in self.db.run(sql, args).fetchall()]

    def transaction(self):
        return _Tx(self.db)


class Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        db = self.db

        class _A:
            async def __aenter__(self):
                return Conn(db)

            async def __aexit__(self, *_):
                return False
        return _A()


class Sessions:
    """The processing sessions' `package_counted_at` (the real claim is one
    Postgres statement; its SQL is pinned separately below)."""
    def __init__(self, clock):
        self.counted = {}          # sid -> (user, iso)
        self.saved = set()         # sids whose forms are saved
        self.clock = clock

    async def claim(self, sid, user_id, at_iso, conn=None):
        if sid in self.counted:
            return False
        self.counted[sid] = (str(user_id), at_iso)
        return True

    async def get(self, sid, **_kw):
        return {"package_counted_at": self.counted.get(sid, (None, None))[1],
                "generated_forms": {"ACORD_125": {}} if sid in self.saved else {}}

    async def since(self, user_id, since_iso, conn=None):
        rows = [(sid, at) for sid, (u, at) in self.counted.items() if u == str(user_id) and at >= since_iso]
        return sorted(rows, key=lambda r: (r[1], r[0]))


@pytest.fixture
def db(monkeypatch, clock):
    d = DB()
    pool = Pool(d)
    for mod in (sr, ss, svc, us, ar):
        monkeypatch.setattr(mod, "get_pool", lambda: pool)
    return d


@pytest.fixture
def sessions(monkeypatch, clock):
    s = Sessions(clock)
    monkeypatch.setattr(us, "claim_package_count", s.claim)
    monkeypatch.setattr(us, "get_processing_session", s.get)
    monkeypatch.setattr(sr, "packages_counted_since", s.since)
    monkeypatch.setattr(us, "packages_counted_since", s.since)
    return s


# ── Stripe ────────────────────────────────────────────────────────────────────
class _L:
    def __init__(self, items):
        self.data = list(items)

    def auto_paging_iter(self):
        return iter(self.data)


def _missing(what, oid):
    return stripe.error.InvalidRequestError(f"No such {what}: '{oid}'", None)


class Stripe:
    def __init__(self):
        self.calls = []
        self.customers = {}
        self.subs = {}
        self.invoice_payments = {}       # invoice -> [payment intent ids]
        self.invoice_lines = {}          # invoice -> [line dicts]; default: one plan line
        self.invoices = {}               # created invoices (final bills)
        self.items = []                  # created invoice items (dicts)
        self.refunds = []                # refunds made
        self.idem = {}                   # idempotency key -> response
        self.down = False                # every call fails (Stripe unreachable)
        self.fail = set()                # names that fail as if Stripe were unreachable (transient)
        self.refuse = set()              # names Stripe REFUSES (permanent: invalid request)
        self.slow = 0.0
        self._n = 0

    def _call(self, _name, *args, **kw):
        self.calls.append((_name, args, kw))
        if self.slow:
            time.sleep(self.slow)
        if self.down or _name in self.fail:
            raise stripe.error.APIConnectionError(f"{_name}: unreachable")
        if _name in self.refuse:
            raise stripe.error.InvalidRequestError(f"{_name}: refused", None)

    def names(self, name=None):
        return [c for c in self.calls if c[0] == name] if name else [c[0] for c in self.calls]

    # objects
    def add_customer(self, cid=CUS, email="u1@agency.test", user_id="u1"):
        self.customers[cid] = {"id": cid, "email": email,
                               "metadata": {"user_id": user_id} if user_id else {}}
        return cid

    def add_sub(self, sid, status="active", customer=CUS, user_id="u1", plan="professional",
                cycle="monthly", amount=None, interval=None, cancel_at_period_end=False,
                latest_invoice=None, created=None):
        # A price bills on its plan's cycle, as in Stripe (3 Nov 2026: the
        # price's interval decides a plan's cycle).
        interval = interval or ("year" if cycle == "annual" else "month")
        meta = {}
        if user_id:
            meta["user_id"] = user_id
        if plan:
            meta.update(plan=plan, billing_cycle=cycle)
        self._n += 1
        self.subs[sid] = {"id": sid, "status": status, "customer": customer, "metadata": meta,
                          "cancel_at_period_end": cancel_at_period_end,
                          "latest_invoice": latest_invoice or f"in_{sid}",
                          "created": created or self._n,
                          "items": {"data": [{"price": {"unit_amount": amount, "recurring": {"interval": interval}}}]}}
        return sid

    # Customer
    def customer_list(self, **kw):
        self._call("Customer.list", **kw)
        return _L(dict(c) for c in self.customers.values() if c["email"] == kw.get("email"))

    def customer_create(self, **kw):
        self._call("Customer.create", **kw)
        key = kw.get("idempotency_key")
        if key in self.idem:
            return self.idem[key]
        cid = f"cus_new_{len(self.customers) + 1}"
        self.customers[cid] = {"id": cid, "email": kw.get("email"), "metadata": dict(kw.get("metadata") or {})}
        out = dict(self.customers[cid])
        if key:
            self.idem[key] = out
        return out

    def customer_retrieve(self, cid, **kw):
        self._call("Customer.retrieve", cid, **kw)
        if cid not in self.customers:
            raise _missing("customer", cid)
        return dict(self.customers[cid])

    def customer_modify(self, cid, **kw):
        self._call("Customer.modify", cid, **kw)

    # Subscription
    def sub_list(self, **kw):
        self._call("Subscription.list", **kw)
        cid, st = kw.get("customer"), kw.get("status")
        if cid not in self.customers:
            raise _missing("customer", cid)
        out = []
        for s in self.subs.values():
            if s["customer"] != cid:
                continue
            if st == "all" or (st is None and s["status"] != "canceled") or s["status"] == st:
                out.append(dict(s))
        return _L(out)

    def sub_retrieve(self, sid, **kw):
        self._call("Subscription.retrieve", sid, **kw)
        if sid not in self.subs:
            raise _missing("subscription", sid)
        s = dict(self.subs[sid])
        if "latest_invoice" in (kw.get("expand") or []):
            s["latest_invoice"] = {"id": s["latest_invoice"],
                                   "status": "paid" if s["status"] in ("active", "trialing") else "open"}
        return s

    def sub_cancel(self, sid, **kw):
        self._call("Subscription.cancel", sid, **kw)
        if sid not in self.subs:
            raise _missing("subscription", sid)
        self.subs[sid]["status"] = "canceled"
        return dict(self.subs[sid])

    def sub_modify(self, sid, **kw):
        self._call("Subscription.modify", sid, **kw)
        if sid not in self.subs:
            raise _missing("subscription", sid)
        self.subs[sid].update({k: v for k, v in kw.items() if k != "idempotency_key"})

    # Invoices / refunds / items
    def invoice_payment_list(self, **kw):
        self._call("InvoicePayment.list", **kw)
        pis = self.invoice_payments.get(kw.get("invoice"), [])
        return _L({"id": f"inpay_{pi}", "status": "paid",
                   "payment": {"type": "payment_intent", "payment_intent": pi}} for pi in pis)

    def invoice_list_lines(self, inv, **kw):
        self._call("Invoice.list_lines", inv, **kw)
        lines = self.invoice_lines.get(inv)
        if lines is None:
            lines = [{"amount": 29900, "parent": {"type": "subscription_item_details"}}]
        return _L(dict(ln) for ln in lines)

    def invoice_create(self, **kw):
        self._call("Invoice.create", **kw)
        key = kw.get("idempotency_key")
        if key and key in self.idem:
            return self.idem[key]
        iid = f"in_final_{len(self.invoices) + 1}"
        inv = {"id": iid, "status": "draft", "customer": kw.get("customer"),
               "metadata": dict(kw.get("metadata") or {}), "kw": kw}
        self.invoices[iid] = inv
        if key:
            self.idem[key] = inv
        return dict(inv)

    def invoice_list(self, **kw):
        self._call("Invoice.list", **kw)
        out = []
        for i in self.invoices.values():
            if "customer" in kw and i.get("customer") != kw["customer"]:
                continue
            if "subscription" in kw and i.get("subscription") != kw["subscription"]:
                continue
            if "status" in kw and i.get("status") != kw["status"]:
                continue
            if "customer" in kw or "subscription" in kw:
                out.append(dict(i))
        return _L(out)

    def add_open_invoice(self, iid, sub=SUB, customer=CUS, attempt_count=1, reason="automatic_pending_invoice_item_invoice"):
        """An invoice of the subscription Stripe has tried to charge and is
        retrying (3 Nov 2026: the paid-up check)."""
        self.invoices[iid] = {"id": iid, "status": "open", "customer": customer, "subscription": sub,
                              "attempt_count": attempt_count, "billing_reason": reason, "metadata": {}}
        return iid

    def invoice_retrieve(self, iid, **kw):
        self._call("Invoice.retrieve", iid, **kw)
        if iid not in self.invoices:
            raise _missing("invoice", iid)
        return dict(self.invoices[iid])

    def invoice_finalize(self, iid, **kw):
        self._call("Invoice.finalize_invoice", iid, **kw)
        self.invoices[iid]["status"] = "open"
        return dict(self.invoices[iid])

    def invoice_pay_final(self, iid, **kw):
        self._call("Invoice.pay", iid, **kw)
        if "Invoice.pay:decline" in self.fail:
            raise stripe.error.CardError("Your card was declined.", None, "card_declined")
        self.invoices[iid]["status"] = "paid"
        return dict(self.invoices[iid])

    def item_delete(self, iid, **kw):
        self._call("InvoiceItem.delete", iid, **kw)
        self.items = [i for i in self.items if i["id"] != iid]
        return {"id": iid, "deleted": True}

    def refund_create(self, **kw):
        self._call("Refund.create", **kw)
        ref = {"id": f"re_{kw.get('payment_intent') or kw.get('charge')}_{len(self.refunds) + 1}",
               "amount": kw.get("amount") or 0, "status": "succeeded",
               "payment_intent": kw.get("payment_intent"), "charge": kw.get("charge"),
               "metadata": dict(kw.get("metadata") or {})}
        self.refunds.append(ref)
        return dict(ref)

    def refund_list(self, **kw):
        self._call("Refund.list", **kw)
        return _L(dict(r) for r in self.refunds
                  if (kw.get("payment_intent") and r["payment_intent"] == kw["payment_intent"])
                  or (kw.get("charge") and r["charge"] == kw["charge"]))



    def item_create(self, **kw):
        self._call("InvoiceItem.create", **kw)
        key = kw.get("idempotency_key")
        if key and key in self.idem:
            return self.idem[key]
        item = {"id": f"ii_{len(self.items) + 1}", **{k: v for k, v in kw.items() if k != "idempotency_key"}}
        self.items.append(item)
        if key:
            self.idem[key] = item
        return item

    def item_list(self, **kw):
        self._call("InvoiceItem.list", **kw)
        out = [i for i in self.items if (kw.get("invoice") and i.get("invoice") == kw["invoice"])
               or (not kw.get("invoice") and i.get("customer") == kw.get("customer"))]
        if kw.get("pending") is True:
            out = [i for i in out if not i.get("invoice") and not i.get("swept")]
        return _L(out)

    def checkout_create(self, **kw):
        self._call("checkout.Session.create", **kw)
        return _Obj(url=f"https://checkout.test/{kw.get('mode')}")

    def portal_create(self, **kw):
        self._call("billing_portal.Session.create", **kw)
        return _Obj(url="https://portal.test/")

    def setup_intent_retrieve(self, sid, **kw):
        self._call("SetupIntent.retrieve", sid, **kw)
        return {"id": sid, "payment_method": "pm_new"}


@pytest.fixture
def fs(monkeypatch):
    f = Stripe()
    monkeypatch.setattr(stripe, "api_key", "sk_test_offline_only")
    for obj, name, fn in [
        (stripe.Customer, "list", f.customer_list), (stripe.Customer, "create", f.customer_create),
        (stripe.Customer, "retrieve", f.customer_retrieve), (stripe.Customer, "modify", f.customer_modify),
        (stripe.Subscription, "list", f.sub_list), (stripe.Subscription, "retrieve", f.sub_retrieve),
        (stripe.Subscription, "cancel", f.sub_cancel), (stripe.Subscription, "modify", f.sub_modify),
        (stripe.InvoicePayment, "list", f.invoice_payment_list), (stripe.Refund, "create", f.refund_create), (stripe.Refund, "list", f.refund_list),
        (stripe.Invoice, "pay", f.invoice_pay_final), (stripe.Invoice, "list", f.invoice_list),
        (stripe.Invoice, "list_lines", f.invoice_list_lines), (stripe.Invoice, "create", f.invoice_create),
        (stripe.Invoice, "finalize_invoice", f.invoice_finalize), (stripe.InvoiceItem, "delete", f.item_delete),
        (stripe.Invoice, "retrieve", f.invoice_retrieve),
        (stripe.InvoiceItem, "create", f.item_create), (stripe.InvoiceItem, "list", f.item_list),
        (stripe.checkout.Session, "create", f.checkout_create),
        (stripe.billing_portal.Session, "create", f.portal_create),
        (stripe.SetupIntent, "retrieve", f.setup_intent_retrieve),
    ]:
        monkeypatch.setattr(obj, name, fn)
    return f


@pytest.fixture
def env(db, sessions, fs, clock, mail, side, webhook, monkeypatch):
    async def _audit(user, action, **kw):
        side["audit"].append((str(user.get("id")), action, kw.get("session_id")))
    monkeypatch.setattr(audit_repo, "write_audit_log", _audit)
    alerts = []

    def _generic(to, subject, txt, html):
        alerts.append((to, subject, txt))
        return True
    monkeypatch.setattr(email_service, "_send_generic_email", _generic)

    async def _not_live(_sid):
        return False
    monkeypatch.setattr(us, "_generation_live", _not_live)
    return {"db": db, "sessions": sessions, "stripe": fs, "clock": clock, "mail": mail, "side": side,
            "alerts": alerts}


def run(coro):
    return asyncio.run(coro)


def checkout_event(evt_id, sub, uid="u1", plan="professional", cycle="monthly", cus=CUS,
                   invoice=None, created=None, mode="subscription", metadata=None):
    md = metadata if metadata is not None else {"plan": plan, "billing_cycle": cycle, "user_id": uid}
    obj = {"id": f"cs_{evt_id}", "object": "checkout.session", "mode": mode, "customer": cus,
           "subscription": sub, "client_reference_id": uid, "payment_status": "paid",
           "invoice": invoice or f"in_{sub}", "metadata": md}
    evt = {"id": evt_id, "type": "checkout.session.completed", "data": {"object": obj}}
    if created is not None:
        evt["created"] = int(created.timestamp())
    return evt


def paid_event(evt_id, invoice_id, etype="invoice.paid", sub=SUB, created=None, inv_created=None,
               lines=None):
    inv = {"id": invoice_id, "object": "invoice", "customer": CUS, "subscription": sub,
           "billing_reason": "subscription_cycle", "status": "paid"}
    if inv_created is not None:
        inv["created"] = int(inv_created.timestamp())
    if lines is not None:
        inv["lines"] = {"data": lines}
    evt = {"id": evt_id, "type": etype, "data": {"object": inv}}
    if created is not None:
        evt["created"] = int(created.timestamp())
    return evt


def failed_user(db, stage="failed", day_failed=0, sent=1, **kw):
    return db.add_user(payment_status=stage,
                       payment_failed_at=(T0 + timedelta(days=day_failed)).isoformat(),
                       payment_email_sent_day=sent, **kw)


def run_lifecycle(clock, day, hours=1):
    clock.at(days=day, hours=hours)
    run(ss.run_daily_payment_lifecycle())


class _JsonReq:
    def __init__(self, body=None):
        self._body = body or {}
        self.client = _Obj(host="127.0.0.1")
        self.headers = {}

    async def json(self):
        return self._body


def checkout(db, uid="u1", plan="professional", cycle="monthly"):
    from models.schemas import CheckoutRequest
    return run(sr.create_checkout(CheckoutRequest(plan=plan, billing_cycle=cycle), current_user=db.user(uid)))


# ═════════════════════════════════════════════════════════════════════════════
# B1 + H3 - create-checkout never opens a second plan; one customer per user
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status,code", [
    ("active", "subscription_exists"), ("trialing", "subscription_exists"),
    ("past_due", "payment_due"), ("unpaid", "payment_due"), ("incomplete", "payment_due"),
])
def test_checkout_refused_while_a_plan_is_live(env, status, code):
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status="failed" if code == "payment_due" else "ok")
    fs.add_customer()
    fs.add_sub(SUB, status=status)
    with pytest.raises(HTTPException) as ei:
        checkout(db, plan="essentials")
    assert ei.value.status_code == 409
    assert ei.value.detail["code"] == code
    want = svc.SUBSCRIPTION_EXISTS if code == "subscription_exists" else svc.PAYMENT_DUE
    assert ei.value.detail == want
    assert not fs.names("checkout.Session.create")


def test_the_409_messages_are_the_agreed_contract():
    assert svc.SUBSCRIPTION_EXISTS == {
        "code": "subscription_exists",
        "message": "You already have an active Primble plan. To change your plan, contact support@primble.ai."}
    assert svc.PAYMENT_DUE == {
        "code": "payment_due",
        "message": "Your last payment didn't go through. Update your card in Manage billing to restore your plan."}


def test_a_canceling_user_with_a_live_plan_is_subscription_exists(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status="canceling")
    fs.add_customer()
    fs.add_sub(SUB, status="active", cancel_at_period_end=True)
    with pytest.raises(HTTPException) as ei:
        checkout(db)
    assert ei.value.detail["code"] == "subscription_exists"


def test_a_live_plan_found_only_in_stripe_still_refuses(env):
    """The DB lost the subscription (a webhook never landed) - Stripe still has it."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_lost", status="active")
    with pytest.raises(HTTPException) as ei:
        checkout(db)
    assert ei.value.detail["code"] == "subscription_exists"


def test_a_stored_plan_stripe_cancelled_does_not_block_a_new_checkout(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    out = checkout(db)
    assert out == {"checkout_url": "https://checkout.test/subscription"}


def test_a_subscription_tagged_to_another_user_never_blocks(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_other_product", status="active", user_id="someone_else")
    assert checkout(db)["checkout_url"]


def test_stripe_unreachable_refuses_with_503_never_blind(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    fs.down = True
    with pytest.raises(HTTPException) as ei:
        checkout(db)
    assert ei.value.status_code == 503
    assert ei.value.detail["code"] == "billing_unavailable"
    assert not [c for c in fs.calls if c[0] == "checkout.Session.create"]
    assert db.user()["stripe_customer_id"] is None


def test_stripe_unreachable_on_the_subscription_check_refuses(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.fail = {"Subscription.list"}
    with pytest.raises(HTTPException) as ei:
        checkout(db)
    assert ei.value.status_code == 503
    assert not fs.names("checkout.Session.create")


def test_the_customer_is_created_and_stored_before_the_checkout(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    checkout(db)
    cid = db.user()["stripe_customer_id"]
    assert cid and fs.customers[cid]["metadata"]["user_id"] == "u1"
    (create,) = fs.names("checkout.Session.create")
    kw = create[2]
    assert kw["customer"] == cid and "customer_email" not in kw
    assert kw["subscription_data"]["metadata"] == {"plan": "professional", "billing_cycle": "monthly",
                                                   "user_id": "u1"}
    assert fs.names().index("Customer.create") < fs.names().index("checkout.Session.create")


def test_two_tabs_get_one_customer(env):
    """R11 (fixed): two checkouts before any webhook used customer_email, so Stripe
    made a customer each time. Now one customer, by idempotency key and by the row."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    user_before = db.user()

    async def two():
        from models.schemas import CheckoutRequest
        req = CheckoutRequest(plan="professional", billing_cycle="monthly")
        return await asyncio.gather(sr.create_checkout(req, current_user=dict(user_before)),
                                    sr.create_checkout(req, current_user=dict(user_before)))
    run(two())
    used = {c[2]["customer"] for c in fs.names("checkout.Session.create")}
    assert len(fs.customers) == 1 and used == {db.user()["stripe_customer_id"]}


def test_an_existing_customer_is_reused_only_when_it_carries_this_users_id(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    fs.add_customer("cus_foreign", user_id="other_user")            # same e-mail, not ours
    fs.add_customer("cus_untagged", user_id=None)                   # same e-mail, no id
    checkout(db)
    cid = db.user()["stripe_customer_id"]
    assert cid not in ("cus_foreign", "cus_untagged")
    db2 = env["db"]
    db2.lite.execute("UPDATE users SET stripe_customer_id=NULL WHERE id='u1'")
    fs.add_customer("cus_ours", user_id="u1")
    fs.customers.pop(cid)
    checkout(db2)
    assert db2.user()["stripe_customer_id"] == "cus_ours"


def test_a_stale_stored_customer_is_replaced(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id="cus_deleted")
    out = checkout(db)
    assert out["checkout_url"]
    cid = db.user()["stripe_customer_id"]
    assert cid != "cus_deleted" and cid in fs.customers
    assert fs.names("checkout.Session.create")[0][2]["customer"] == cid


# ═════════════════════════════════════════════════════════════════════════════
# B1 - a checkout that completes on top of a live plan is cancelled and refunded
# ═════════════════════════════════════════════════════════════════════════════
def _live_user_with_duplicate(env, invoice="in_dup"):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=5)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active", latest_invoice=invoice)
    fs.invoice_payments[invoice] = ["pi_dup"]
    return db, fs


def test_a_duplicate_checkout_keeps_the_existing_plan_and_refunds_the_new_one(env):
    db, fs = _live_user_with_duplicate(env)
    before = db.user()
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup", plan="essentials"))
    assert db.user() == before                                      # stays on the existing plan
    assert fs.subs["sub_dup"]["status"] == "canceled" and fs.subs[SUB]["status"] == "active"
    (refund,) = fs.names("Refund.create")
    assert refund[2]["payment_intent"] == "pi_dup" and refund[2]["reason"] == "duplicate"
    assert refund[2]["idempotency_key"].startswith("primble-dup-refund:in_dup")
    assert ("u1", "payment.duplicate_subscription_refunded", "in_dup") in env["side"]["audit"]
    assert db.keys(svc.DUP_PREFIX) == {"duplicate_checkout:u1:sub_dup:in_dup": svc.DUP_REFUNDED}
    assert ("Subscription.cancel", (SUB,), {}) not in fs.calls


def test_a_refused_refund_cancels_and_leaves_a_record_for_a_person(env, caplog):
    """A refund Stripe REFUSES goes to a person (2 Nov 2026, M-1: a transient
    failure stays pending instead - see the M-1 tests)."""
    db, fs = _live_user_with_duplicate(env)
    fs.refuse = {"Refund.create"}
    with caplog.at_level(logging.ERROR):
        deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert fs.subs["sub_dup"]["status"] == "canceled"
    assert db.user()["stripe_subscription_id"] == SUB
    assert ("u1", "payment.duplicate_subscription_manual_refund", "in_dup") in env["side"]["audit"]
    assert any("MANUAL REFUND NEEDED" in r.message and "in_dup" in r.message for r in caplog.records)
    assert db.keys(svc.DUP_PREFIX) == {"duplicate_checkout:u1:sub_dup:in_dup": svc.DUP_MANUAL}


def test_a_refused_cancel_is_also_left_for_a_person(env):
    db, fs = _live_user_with_duplicate(env)
    fs.refuse = {"Subscription.cancel"}
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert db.user()["stripe_subscription_id"] == SUB
    assert ("u1", "payment.duplicate_subscription_manual_refund", "in_dup") in env["side"]["audit"]


def test_a_redelivered_duplicate_checkout_repeats_no_side_effect(env):
    db, fs = _live_user_with_duplicate(env)
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    fs.calls.clear()
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert not fs.names("Subscription.cancel") and not fs.names("Refund.create")


def test_stripe_unreachable_on_the_duplicate_check_is_a_503_and_records_nothing(env):
    db, fs = _live_user_with_duplicate(env)
    fs.fail = {"Subscription.retrieve"}
    with pytest.raises(HTTPException) as ei:
        deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert ei.value.status_code == 503
    assert db.keys() == {}                       # Stripe re-delivers; nothing was recorded
    assert db.user()["stripe_subscription_id"] == SUB


def test_a_new_plan_after_the_old_one_ended_is_not_a_duplicate(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="essentials")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_new", "sub_new"))
    u = db.user()
    assert u["stripe_subscription_id"] == "sub_new" and u["subscription_tier"] == "professional"
    assert not fs.names("Refund.create") and not fs.names("Subscription.cancel")


def test_two_checkouts_completing_at_once_keep_exactly_one(env, monkeypatch):
    """A second checkout links its subscription between our read and our write:
    the compare-and-set loses and the new one is treated as the duplicate."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_a", status="active")
    fs.add_sub("sub_b", status="active", latest_invoice="in_b")
    fs.invoice_payments["in_b"] = ["pi_b"]
    real_claim = sr._claim_event

    async def racing_claim(conn, event_id, event_type):
        if event_id == "evt_b":
            await conn.execute("UPDATE users SET stripe_subscription_id='sub_a' WHERE id='u1'")
        return await real_claim(conn, event_id, event_type)
    monkeypatch.setattr(sr, "_claim_event", racing_claim)
    deliver(checkout_event("evt_b", "sub_b", invoice="in_b"))
    assert db.user()["stripe_subscription_id"] == "sub_a"
    assert fs.subs["sub_b"]["status"] == "canceled" and fs.names("Refund.create")


def test_R11_two_completed_checkouts_leave_no_orphan(env):
    """R11 (fixed): the second checkout no longer orphans the first subscription."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    fs.add_customer()
    fs.add_sub("sub_1", status="active")
    fs.add_sub("sub_2", status="active", latest_invoice="in_2")
    fs.invoice_payments["in_2"] = ["pi_2"]
    deliver(checkout_event("evt_1", "sub_1"))
    deliver(checkout_event("evt_2", "sub_2", invoice="in_2"))
    u = db.user()
    assert u["stripe_subscription_id"] == "sub_1"
    assert fs.subs["sub_2"]["status"] == "canceled" and fs.subs["sub_1"]["status"] == "active"
    assert [c[2]["payment_intent"] for c in fs.names("Refund.create")] == ["pi_2"]


def test_a_stranded_duplicate_is_settled_by_the_daily_job(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub("sub_dup", status="active", latest_invoice="in_dup")
    fs.invoice_payments["in_dup"] = ["pi_dup"]
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("duplicate_checkout:u1:sub_dup:in_dup", svc.DUP_PENDING, old))
    assert run(svc.retry_unsettled_duplicates()) == 1
    assert fs.subs["sub_dup"]["status"] == "canceled" and fs.names("Refund.create")
    assert db.keys(svc.DUP_PREFIX)["duplicate_checkout:u1:sub_dup:in_dup"] == svc.DUP_REFUNDED


# ═════════════════════════════════════════════════════════════════════════════
# H1 / H2 - no open-invoice paying, no cancel-the-others loops
# ═════════════════════════════════════════════════════════════════════════════
def test_R4_a_checkout_never_pays_the_customers_open_invoices(env):
    db, fs = env["db"], env["stripe"]
    failed_user(db, subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_new", "sub_new"))
    assert not fs.names("Invoice.pay") and not fs.names("Invoice.list")


def test_a_setup_checkout_records_first_then_sets_the_card_and_pays_nothing(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    evt = {"id": "evt_setup", "type": "checkout.session.completed",
           "data": {"object": {"id": "cs_setup", "mode": "setup", "customer": CUS, "setup_intent": "seti_1"}}}
    deliver(evt)
    assert fs.names("Customer.modify") and fs.names("Subscription.modify")
    assert not fs.names("Invoice.pay")
    fs.calls.clear()
    deliver(evt)                                                    # re-delivery: nothing again
    assert fs.calls == []


@pytest.mark.parametrize("module_src", ["routes/stripe_routes.py"])
def test_no_cancel_every_other_subscription_loop_is_left(module_src):
    src = (ROOT / module_src).read_text()
    assert "for st in (\"active\", \"past_due\", \"trialing\")" not in src
    assert "for _st in (\"active\", \"past_due\", \"trialing\")" not in src
    assert "Invoice.pay" not in src and "Invoice.list" not in src


def test_R3_a_late_old_checkout_event_cancels_nothing(env):
    """R3 (fixed): a re-delivered (or late) event of the OLD checkout never cancels
    the current paid plan, and never points the user back at a dead one."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_A", status="active", plan="essentials")
    deliver(checkout_event("evt_A", "sub_A", plan="essentials"))
    assert db.user()["stripe_subscription_id"] == "sub_A"
    fs.add_sub("sub_B", status="active", latest_invoice="in_B")
    fs.invoice_payments["in_B"] = ["pi_B"]
    deliver(checkout_event("evt_B", "sub_B", invoice="in_B"))       # a second plan: duplicate
    deliver(checkout_event("evt_A", "sub_A", plan="essentials"))    # re-delivery of the old event
    db.lite.execute("DELETE FROM processed_webhook_events WHERE event_id='evt_A'")
    deliver(checkout_event("evt_A", "sub_A", plan="essentials"))    # or its first, late delivery
    assert ("Subscription.cancel", ("sub_A",), {"idempotency_key": "primble-dup-cancel:sub_A"}) not in fs.calls
    assert fs.subs["sub_A"]["status"] == "active"
    u = db.user()
    assert u["stripe_subscription_id"] == "sub_A" and u["subscription_tier"] == "essentials"


def test_R5_a_plan_change_never_cancels_the_old_plan_without_credit(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(billing_cycle="annual")
    fs.add_customer()
    fs.add_sub(SUB, status="active", cycle="annual")
    fs.add_sub("sub_monthly_new", status="active", latest_invoice="in_m")
    fs.invoice_payments["in_m"] = ["pi_m"]
    deliver(checkout_event("evt_switch", "sub_monthly_new", invoice="in_m"))
    assert fs.subs[SUB]["status"] == "active"                       # the annual plan is kept
    assert db.user()["stripe_subscription_id"] == SUB
    assert fs.subs["sub_monthly_new"]["status"] == "canceled" and fs.names("Refund.create")


# ═════════════════════════════════════════════════════════════════════════════
# H4 - a customer / subscription found by e-mail is ours only when tagged
# ═════════════════════════════════════════════════════════════════════════════
def test_a_checkout_with_no_plan_metadata_never_defaults_to_essentials(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    deliver(checkout_event("evt_link", "sub_payment_link", metadata={}))
    assert db.user()["subscription_tier"] == "free"


def test_a_checkout_is_never_linked_to_a_user_by_email_alone(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    evt = checkout_event("evt_x", "sub_x", uid=None, metadata={"plan": "professional",
                                                               "billing_cycle": "monthly"})
    evt["data"]["object"]["customer_email"] = "u1@agency.test"
    deliver(evt)
    assert db.user()["subscription_tier"] == "free"


@pytest.fixture
def no_rate_limit(monkeypatch):
    async def _no_rl(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _no_rl)


def test_verify_upgrade_ignores_a_customer_found_by_email_for_someone_else(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id=None)
    fs.add_customer("cus_other", user_id="other")
    fs.add_sub("sub_other", status="active", customer="cus_other", user_id=None)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["upgraded"] is False and out["reason"] == "no_stripe_customer"
    assert db.user()["subscription_tier"] == "free"


def test_verify_upgrade_never_adopts_an_untagged_subscription(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer(user_id=None)
    fs.add_sub("sub_untagged", status="active", user_id=None, plan=None, amount=29900)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["upgraded"] is False and db.user()["subscription_tier"] == "free"


def test_verify_upgrade_accepts_the_customers_tag_when_the_subscription_has_none(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer(user_id="u1")
    fs.add_sub("sub_portal", status="active", user_id=None, plan=None, amount=29900)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "professional", "upgraded": True, "reason": "stripe_verified"}


def test_verify_upgrade_never_guesses_a_plan(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_odd", status="active", plan=None, amount=12345)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["reason"] == "unknown_plan" and db.user()["subscription_tier"] == "free"


@pytest.fixture
def me(monkeypatch):
    monkeypatch.setattr(ar, "_auth_redis", None)
    return lambda user: run(ar.get_me(current_user=user))


def test_me_never_adopts_another_products_subscription(env, me):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_foreign", status="active", user_id="someone_else", plan="business")
    me(db.user())
    assert db.user()["stripe_subscription_id"] is None and db.user()["subscription_tier"] == "professional"


def test_me_never_swaps_a_stored_subscription_for_another(env, me):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    fs.add_sub("sub_dup", status="active", plan="essentials")
    me(db.user())
    assert db.user()["stripe_subscription_id"] == SUB
    assert not fs.names("Subscription.list")


def test_me_links_a_tagged_subscription_onto_a_row_that_lost_it(env, me):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_mine", status="active")
    me(db.user())
    assert db.user()["stripe_subscription_id"] == "sub_mine"


# ═════════════════════════════════════════════════════════════════════════════
# M1 + L7 - verify-upgrade only upgrades; portal never sells a plan
# ═════════════════════════════════════════════════════════════════════════════
def test_R6_verify_upgrade_never_downgrades_a_past_due_payer(env, no_rate_limit):
    """R6 (fixed): past_due has no ACTIVE subscription - the plan and the stored
    subscription stay, so the later successful retry restores the user."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["subscription_tier"] == "professional" and out["upgraded"] is False
    u = db.user()
    assert u["subscription_tier"] == "professional" and u["stripe_subscription_id"] == SUB
    clock.at(days=3)
    fs.subs[SUB]["status"] = "active"                    # the retry paid: Stripe says active (M-5)
    deliver(invoice_event("evt_paid_retry", etype="invoice.paid"))
    assert db.user()["payment_status"] == "ok"


def test_verify_upgrade_upgrades_a_free_user_from_a_tagged_active_plan(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="essentials", cycle="annual")
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "essentials", "upgraded": True, "reason": "stripe_verified"}
    u = db.user()
    assert (u["subscription_tier"], u["billing_cycle"], u["stripe_subscription_id"]) == ("essentials", "annual", "sub_new")
    # Brent, 3 Nov 2026: an annual plan's allowance is 100 PER MONTH (was one 1,200 pot).
    assert u["packages_limit"] == 100


def test_verify_upgrade_never_replaces_a_live_stored_plan(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    fs.add_sub("sub_dup", status="active", plan="essentials")
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["reason"] == "existing_subscription"
    assert db.user()["stripe_subscription_id"] == SUB


def test_verify_upgrade_leaves_enterprise_alone(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="enterprise", stripe_subscription_id=None)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "enterprise", "upgraded": False, "reason": "enterprise"}
    assert fs.calls == [] and db.user()["subscription_tier"] == "enterprise"


def test_verify_upgrade_with_nothing_active_never_downgrades_or_clears(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="business")
    fs.add_customer()
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["subscription_tier"] == "business" and out["upgraded"] is False
    assert db.user()["subscription_tier"] == "business" and db.user()["stripe_subscription_id"] == SUB


def test_manage_billing_with_no_account_is_400_and_sells_nothing(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="professional", stripe_customer_id=None, stripe_subscription_id=None)
    with pytest.raises(HTTPException) as ei:
        run(sr.create_portal_session(user=db.user()))
    assert ei.value.status_code == 400
    assert ei.value.detail == {"code": "no_billing_account", "message": "There's no billing account to manage yet."}
    assert not fs.names("checkout.Session.create")


def test_manage_billing_unreachable_is_503(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_customer_id=None)
    fs.down = True
    with pytest.raises(HTTPException) as ei:
        run(sr.create_portal_session(user=db.user()))
    assert ei.value.status_code == 503


def test_manage_billing_finds_this_users_tagged_customer(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_customer_id=None, stripe_subscription_id=None)
    fs.add_customer("cus_mine", user_id="u1")
    fs.add_sub("sub_mine", status="active", customer="cus_mine")
    out = run(sr.create_portal_session(user=db.user()))
    assert out == {"url": "https://portal.test/"}
    u = db.user()
    assert u["stripe_customer_id"] == "cus_mine" and u["stripe_subscription_id"] == "sub_mine"
    assert not [c for c in fs.names("checkout.Session.create") if c[2].get("mode") == "subscription"]


# ═════════════════════════════════════════════════════════════════════════════
# M2 - late SUCCESS events never erase a newer failure
# ═════════════════════════════════════════════════════════════════════════════
def test_R1_a_stale_active_update_keeps_the_failure(env):
    db, clock, mail = env["db"], env["clock"], env["mail"]
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    clock.at(hours=1)
    deliver(invoice_event("evt_fail", created=T0 + timedelta(hours=1)))
    clock.at(hours=3)
    deliver(sub_event("evt_active_T0", "active", created=T0))
    u = db.user()
    assert u["payment_status"] == "failed"
    assert u["payment_failed_at"] == (T0 + timedelta(hours=1)).isoformat()
    clock.at(days=3)
    deliver(invoice_event("evt_fail2", created=T0 + timedelta(days=3)))
    assert db.user()["payment_failed_at"] == (T0 + timedelta(hours=1)).isoformat()
    assert mail.days() == [1]


def test_R2_a_stale_invoice_paid_neither_clears_nor_resets(env):
    db, clock = env["db"], env["clock"]
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat(), packages_used=9)
    deliver(invoice_event("evt_fail", created=T0))
    clock.at(days=12)
    deliver(paid_event("evt_old_paid", "in_last_month", created=T0 - timedelta(days=30)))
    u = db.user()
    assert u["payment_status"] == "failed" and u["payment_failed_at"] == T0.isoformat()
    assert u["packages_used"] == 9


def test_a_payment_made_after_the_failure_clears_it(env):
    db, clock = env["db"], env["clock"]
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    env["stripe"].add_customer()
    env["stripe"].add_sub(SUB, status="active")
    deliver(invoice_event("evt_fail", created=T0))
    clock.at(days=12)
    deliver(paid_event("evt_paid", "in_this_month", created=T0 + timedelta(days=12),
                       inv_created=T0))
    assert db.user()["payment_status"] == "ok"


def test_a_failure_records_when_stripe_says_it_failed(env):
    db, clock = env["db"], env["clock"]
    db.add_user()
    clock.at(hours=5)                                    # delivered late
    deliver(invoice_event("evt_fail", created=T0))
    assert db.user()["payment_failed_at"] == T0.isoformat()


def test_a_late_failure_does_not_mask_a_payment_made_before_its_delivery(env):
    """Failure created 10:00, delivered 15:00; the customer paid at 12:00: the
    payment is newer than the failure and clears it."""
    db, clock = env["db"], env["clock"]
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    env["stripe"].add_customer()
    env["stripe"].add_sub(SUB, status="active")
    clock.at(hours=5)
    deliver(invoice_event("evt_fail", created=T0))
    deliver(paid_event("evt_paid", "in_p", created=T0 + timedelta(hours=2), inv_created=T0))
    assert db.user()["payment_status"] == "ok"


# ═════════════════════════════════════════════════════════════════════════════
# L1 - one invoice resets usage once
# ═════════════════════════════════════════════════════════════════════════════
def test_R7_paid_and_succeeded_of_one_invoice_reset_usage_once(env):
    db = env["db"]
    db.add_user(packages_used=0)
    deliver(paid_event("evt_paid", "in_1"))
    db.lite.execute("UPDATE users SET packages_used=3 WHERE id='u1'")
    deliver(paid_event("evt_succ", "in_1", etype="invoice.payment_succeeded"))
    assert db.user()["packages_used"] == 3
    assert db.keys("invoice_reset:") == {"invoice_reset:in_1": "invoice_reset"}


def test_two_different_invoices_each_reset(env):
    db, clock = env["db"], env["clock"]
    db.add_user()
    deliver(paid_event("evt_1", "in_1"))
    db.lite.execute("UPDATE users SET packages_used=3 WHERE id='u1'")
    clock.at(days=30)
    deliver(paid_event("evt_2", "in_2"))
    assert db.user()["packages_used"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# M5 - the overage pack is retired
# ═════════════════════════════════════════════════════════════════════════════
def test_the_overage_pack_endpoints_are_gone(env):
    db = env["db"]
    db.add_user()
    for fn in (sr.create_overage_checkout, sr.apply_overage):
        with pytest.raises(HTTPException) as ei:
            run(fn(current_user=db.user()))
        assert ei.value.status_code == 410


def test_R8_a_paid_overage_pack_credits_nothing_and_is_recorded(env, caplog):
    db, clock = env["db"], env["clock"]
    db.add_user(packages_limit=100, packages_used=100)
    evt = {"id": "evt_ov", "type": "checkout.session.completed",
           "data": {"object": {"id": "cs_ov", "mode": "payment", "customer": CUS, "client_reference_id": "u1",
                               "metadata": {"type": "overage", "qty": "10", "user_id": "u1"}}}}
    with caplog.at_level(logging.ERROR):
        deliver(evt)
        deliver(evt)                                      # re-delivery: nothing more
    assert db.user()["packages_limit"] == 100
    assert env["side"]["audit"].count(("u1", "payment.overage_pack_unapplied", "cs_ov")) == 1
    assert any("a person must credit or refund it" in r.message for r in caplog.records)
    for m in range(1, 3):
        clock.at(days=30 * m)
        deliver(paid_event(f"evt_renew_{m}", f"in_r{m}"))
    assert db.user()["packages_limit"] == 100


def test_an_overage_pack_applied_before_is_left_alone(env):
    db = env["db"]
    db.add_user(packages_limit=110)
    db.lite.execute("INSERT INTO applied_overage_sessions VALUES ('cs_ov','u1',10,'x')")
    deliver({"id": "evt_ov", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_ov", "mode": "payment",
                                 "metadata": {"type": "overage", "qty": "10", "user_id": "u1"}}}})
    assert db.user()["packages_limit"] == 110 and env["side"]["audit"] == []


# ═════════════════════════════════════════════════════════════════════════════
# M6 / L8 / L9 / M11 - counting and overage
# ═════════════════════════════════════════════════════════════════════════════
def count(uid, sid, **kw):
    return run(us.count_session_usage(uid, sid, **kw))


def test_each_package_counts_once_however_many_paths_call(env):
    db = env["db"]
    db.add_user(packages_used=0)
    for _ in range(3):
        count("u1", "pkg1")
    assert db.user()["packages_used"] == 1


def test_overage_is_billed_once_per_package_above_the_buffer(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=104, packages_limit=100)    # 100 + 5 buffer
    r105 = count("u1", "p105")
    r106 = count("u1", "p106")
    count("u1", "p106")                                    # counted again: nothing
    assert r105["pkg_eval"]["status"] == "soft_buffer" and r106["pkg_eval"]["status"] == "overage"
    (item,) = fs.names("InvoiceItem.create")
    assert item[2]["idempotency_key"] == "overage_unit:u1:p106"
    assert item[2]["metadata"]["unit_key"] == "overage_unit:u1:p106" and item[2]["amount"] == 300
    assert db.user()["overage_packages_invoiced"] == 1
    assert db.keys("overage_unit:") == {"overage_unit:u1:p106": "overage_billed"}


def test_concurrent_counting_at_the_limit_bills_exactly_the_packages_over_it(env):
    """L9: each package reads back its OWN number from the increment."""
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=103, packages_limit=100)

    async def many():
        await asyncio.gather(*(us.count_session_usage("u1", f"p{i}") for i in range(5)))
    run(many())
    assert db.user()["packages_used"] == 108
    assert len(fs.names("InvoiceItem.create")) == 3              # numbers 106, 107, 108


def test_a_failed_stripe_call_leaves_the_unit_pending_and_the_retry_bills_it_once(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=105, packages_limit=100, overage_packages_pending=0)
    fs.fail = {"InvoiceItem.create"}
    assert count("u1", "p106")["pkg_eval"]["billing"] == "pending"
    assert db.user()["overage_packages_pending"] == 1
    assert db.keys("overage_unit:") == {"overage_unit:u1:p106": "overage_pending"}
    fs.fail = set()
    assert run(us.retry_pending_overage()) == 1
    assert run(us.retry_pending_overage()) == 0                     # never twice
    creates = [c for c in fs.names("InvoiceItem.create")]
    assert len(fs.items) == 1 and all(c[2]["idempotency_key"] == "overage_unit:u1:p106" for c in creates)
    u = db.user()
    assert u["overage_packages_pending"] == 0 and u["overage_packages_invoiced"] == 1


def test_the_retry_never_bills_a_unit_stripe_already_holds(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=105, overage_packages_pending=1)
    fs.items.append({"id": "ii_lost", "customer": CUS, "metadata": {"unit_key": "overage_unit:u1:p106"}})
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("overage_unit:u1:p106", "overage_pending", datetime.now(timezone.utc).isoformat()))
    assert run(us.retry_pending_overage()) == 1
    assert not fs.names("InvoiceItem.create")
    assert db.keys("overage_unit:")["overage_unit:u1:p106"] == "overage_billed"


def test_the_retry_waits_when_stripe_cannot_say(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=105, overage_packages_pending=1)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("overage_unit:u1:p106", "overage_pending", datetime.now(timezone.utc).isoformat()))
    fs.fail = {"InvoiceItem.list"}
    assert run(us.retry_pending_overage()) == 0
    assert not fs.names("InvoiceItem.create")
    assert db.keys("overage_unit:")["overage_unit:u1:p106"] == "overage_pending"


def test_pending_overage_is_retried_before_the_next_one(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=106, overage_packages_pending=1)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("overage_unit:u1:p106", "overage_pending", datetime.now(timezone.utc).isoformat()))
    count("u1", "p107")
    keys = [c[2]["idempotency_key"] for c in fs.names("InvoiceItem.create")]
    assert keys == ["overage_unit:u1:p106", "overage_unit:u1:p107"]


def test_the_daily_lifecycle_retries_pending_overage(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=106, overage_packages_pending=1)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("overage_unit:u1:p106", "overage_pending", datetime.now(timezone.utc).isoformat()))
    run_lifecycle(clock, 1)
    assert [c[2]["idempotency_key"] for c in fs.names("InvoiceItem.create")] == ["overage_unit:u1:p106"]


def test_a_renewal_never_forgives_pending_overage(env):
    db = env["db"]
    db.add_user(overage_packages_pending=2, overage_packages_invoiced=4)
    deliver(paid_event("evt_paid", "in_1"))
    u = db.user()
    assert u["overage_packages_pending"] == 2 and u["overage_packages_invoiced"] == 0


def test_create_overage_invoice_item_carries_the_unit_key(env):
    fs = env["stripe"]
    user = {"id": "u1", "stripe_customer_id": CUS, "subscription_tier": "professional"}
    assert svc.create_overage_invoice_item(user, 300, "overage_unit:u1:pX") is True
    kw = fs.names("InvoiceItem.create")[0][2]
    assert kw["idempotency_key"] == "overage_unit:u1:pX" and kw["metadata"]["unit_key"] == "overage_unit:u1:pX"
    assert "user_email" not in kw["metadata"]


@pytest.mark.parametrize("status", ["failed", "soft_locked", "suspended", "archived"])
def test_no_overage_is_billed_while_a_payment_is_failing(env, status):
    db, fs = env["db"], env["stripe"]
    failed_user(db, stage=status, packages_used=110)
    count("u1", "p111")
    assert db.user()["packages_used"] == 111
    assert not fs.names("InvoiceItem.create") and db.keys("overage_unit:") == {}


def test_a_late_paid_renewal_recounts_the_period_and_bills_what_is_over_once(env):
    """M11: renewal failed at T0 (period P2 starts T0); 7 packages were counted
    during the failure (nothing billed); paid on day 12 with a 5-package plan:
    packages_used = 7 and the 2 beyond 5 + 0 buffer are billed, once."""
    db, fs, sessions, clock = env["db"], env["stripe"], env["sessions"], env["clock"]
    failed_user(db, packages_used=60, packages_limit=5,
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")                     # paid on day 12 (M-5)
    sessions.counted["old"] = ("u1", (T0 - timedelta(days=3)).isoformat())   # last period
    for i in range(7):
        sessions.counted[f"p{i}"] = ("u1", (T0 + timedelta(days=1, hours=i)).isoformat())
    clock.at(days=12)
    line = {"type": "subscription", "period": {"start": int(T0.timestamp())},
            "parent": {"type": "subscription_item_details"}}
    overage_line = {"period": {"start": int((T0 - timedelta(days=20)).timestamp())},
                    "parent": {"type": "invoice_item_details"}}
    evt = paid_event("evt_late_paid", "in_P2", created=T0 + timedelta(days=12), inv_created=T0,
                     lines=[overage_line, line])
    deliver(evt)
    u = db.user()
    assert u["payment_status"] == "ok" and u["packages_used"] == 7
    assert [c[2]["idempotency_key"] for c in fs.names("InvoiceItem.create")] == [
        "overage_unit:u1:p5", "overage_unit:u1:p6"]
    deliver(paid_event("evt_late_succ", "in_P2", etype="invoice.payment_succeeded",
                       created=T0 + timedelta(days=12), inv_created=T0, lines=[line]))
    assert len(fs.names("InvoiceItem.create")) == 2 and db.user()["packages_used"] == 7


def test_the_invoice_period_ignores_an_overage_items_line():
    obj = {"lines": {"data": [
        {"period": {"start": 100}, "parent": {"type": "invoice_item_details"}},
        {"period": {"start": 500}, "parent": {"type": "subscription_item_details"}}]}}
    assert sr._invoice_period_start(obj) == datetime.fromtimestamp(500, timezone.utc)
    assert sr._invoice_period_start({}) is None


def test_the_count_usage_endpoint_stays_harmless(env, monkeypatch):
    import routes.form_routes as fr
    db = env["db"]
    db.add_user(packages_used=0)

    async def _sess(sid, **_kw):
        return {"user_id": "u1"}
    monkeypatch.setattr(fr, "get_processing_session", _sess)
    for _ in range(3):
        run(fr.count_session_usage_endpoint("pkgZ", current_user=db.user()))
    assert db.user()["packages_used"] == 1


def test_generation_counts_every_tier_on_the_server():
    src = (ROOT / "routes/form_routes.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "select_forms_bulk")
    body = ast.get_source_segment(src, fn)
    at = body.index("await count_session_usage(")
    window = body[max(0, at - 400):at]
    assert '== "free"' not in window, "the server-side count is free-only again"
    assert "reserved_free=_free_reserved" in body


def test_every_download_path_counts_through_the_one_door():
    src = (ROOT / "routes/download_routes.py").read_text()
    assert "create_overage_invoice_item" not in src
    assert src.count("await count_session_usage(") == 3
    assert "packages_used = COALESCE(packages_used, 0) + 1" not in src


def test_the_package_claim_is_one_conditional_statement(monkeypatch):
    import repositories.session_repository as srepo
    seen = []

    class _C:
        async def execute(self, sql, *args):
            seen.append(sql)
            return "UPDATE 1"

    class _P:
        def acquire(self):
            class _A:
                async def __aenter__(self_inner):
                    return _C()

                async def __aexit__(self_inner, *_):
                    return False
            return _A()
    monkeypatch.setattr(srepo, "get_pool", lambda: _P())
    assert run(srepo.claim_package_count("s1", "u1", "2026-11-02T00:00:00+00:00")) is True
    assert "(data->>'package_counted_at') IS NULL" in seen[0] and "user_id = $2" in seen[0]


# ═════════════════════════════════════════════════════════════════════════════
# M3 - the free package is reserved atomically
# ═════════════════════════════════════════════════════════════════════════════
def test_parallel_free_generations_reserve_one_package(env):
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)

    async def three():
        return await asyncio.gather(*(us.reserve_free_package("u1", f"pkg{i}") for i in range(3)))
    assert sorted(run(three())) == [False, False, True]
    assert db.user()["downloads_used"] == 1


def test_a_reservation_becomes_the_count_and_never_counts_twice(env):
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)
    assert run(us.reserve_free_package("u1", "pkg1"))
    assert count("u1", "pkg1", reserved_free=True)["counted"] is True
    assert db.user()["downloads_used"] == 1
    count("u1", "pkg1")                                   # the download later: no second count
    assert db.user()["downloads_used"] == 1


def test_a_reservation_of_a_package_counted_elsewhere_is_never_given_back(env):
    """2 Nov 2026 (M-2): a reservation is released only if its session was NOT
    counted - the other path that counted it consumed the reservation."""
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)
    assert run(us.reserve_free_package("u1", "pkg1"))
    count("u1", "pkg1")                                   # e.g. the download counted it first
    assert db.user()["downloads_used"] == 1
    count("u1", "pkg1", reserved_free=True)               # the generation's own count: no-op
    run(us.release_free_package("u1", "pkg1"))            # its finally: nothing to give back
    assert db.user()["downloads_used"] == 1


def test_a_failed_generation_gives_the_reservation_back(env):
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)
    assert run(us.reserve_free_package("u1", "pkg1"))
    run(us.release_free_package("u1", "pkg1"))
    assert db.user()["downloads_used"] == 0
    run(us.release_free_package("u1", "pkg1"))
    assert db.user()["downloads_used"] == 0                       # never negative


def test_a_counting_error_before_the_claim_gives_the_reservation_back(env, monkeypatch):
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)
    assert run(us.reserve_free_package("u1", "pkg1"))

    async def boom(*_a, **_k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(us, "claim_package_count", boom)
    assert count("u1", "pkg1", reserved_free=True)["reason"] == "error"
    assert db.user()["downloads_used"] == 0


def test_select_forms_bulk_reserves_then_releases_on_failure():
    src = (ROOT / "routes/form_routes.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "select_forms_bulk")
    body = ast.get_source_segment(src, fn)
    assert body.index("reserve_free_package(") < body.index("shared_gap_fill")
    final = body[body.rindex("finally:"):]
    assert "if _free_reserved:" in final and "release_free_package(" in final


# ═════════════════════════════════════════════════════════════════════════════
# M7 - no Stripe network call on the event loop
# ═════════════════════════════════════════════════════════════════════════════
_SYNC_STRIPE_HELPERS = {"create_overage_invoice_item", "overage_unit_already_billed",
                        "subscription_payment_state", "_cancel_and_refund", "_list_all"}


def _stripe_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


@pytest.mark.parametrize("rel", ["routes/stripe_routes.py", "services/scheduler_service.py",
                                 "services/usage_service.py", "services/stripe_service.py",
                                 "routes/auth_routes.py", "routes/download_routes.py",
                                 "routes/dev_routes.py"])
def test_no_async_function_calls_stripe_directly(rel):
    tree = ast.parse((ROOT / rel).read_text())
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            chain = _stripe_chain(node.func)
            if (chain and chain[0] in ("stripe", "_stripe", "stripe_lib") and len(chain) >= 3
                    and chain[1] not in ("error",) and chain[-1] != "construct_event"):
                offenders.append(".".join(chain))
            if chain and chain[-1] in _SYNC_STRIPE_HELPERS:
                offenders.append(".".join(chain))
            if chain and chain[-1] == "auto_paging_iter":
                offenders.append("auto_paging_iter")
    assert not offenders, f"{rel}: sync Stripe call on the event loop: {offenders}"


def test_R9_the_lifecycle_never_freezes_the_event_loop(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    fs.slow = 0.6
    clock.at(days=10, hours=1)
    ticks = []

    async def ticker():
        start = time.monotonic()
        while time.monotonic() - start < 0.8:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    async def main():
        await asyncio.gather(ticker(), ss.run_daily_payment_lifecycle())
    run(main())
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.3
    assert db.user()["payment_status"] == "soft_locked"


# ═════════════════════════════════════════════════════════════════════════════
# M8 - one lifecycle run a day; each e-mail claimed before it is sent
# ═════════════════════════════════════════════════════════════════════════════
def test_R10_overlapping_runs_send_once(env):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, sent=1)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    clock.at(days=10, hours=1)

    async def main():
        await asyncio.gather(ss.run_daily_payment_lifecycle(), ss.run_daily_payment_lifecycle())
    run(main())
    assert mail.days().count(10) == 1


def test_the_cron_endpoint_and_the_scheduler_share_one_run_a_day(env, monkeypatch):
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, sent=1)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    monkeypatch.setenv("LIFECYCLE_TRIGGER_SECRET", "s3cret")
    run_lifecycle(clock, 10, hours=1)
    n = len(fs.names("Subscription.retrieve"))
    req = _Obj(headers={"x-lifecycle-secret": "s3cret"})
    clock.at(days=10, hours=6)
    assert run(sr.trigger_lifecycle(req)) == {"triggered": True}
    assert len(fs.names("Subscription.retrieve")) == n           # the second run did nothing
    assert len(db.keys("lifecycle_run:")) == 1


def test_a_crashed_run_gives_the_day_back(env, monkeypatch):
    db, clock = env["db"], env["clock"]
    failed_user(db, sent=1)
    real = Conn.fetch

    async def broken(self, sql, *args):
        if "FROM users WHERE payment_failed_at" in sql:
            raise RuntimeError("db down")
        return await real(self, sql, *args)
    monkeypatch.setattr(Conn, "fetch", broken)
    run_lifecycle(clock, 10)
    assert db.keys("lifecycle_run:") == {}


@pytest.mark.parametrize("given,ok", [("s3cret", True), ("wrong", False), ("", False)])
def test_the_trigger_secret_is_compared_in_constant_time(env, monkeypatch, given, ok):
    monkeypatch.setenv("LIFECYCLE_TRIGGER_SECRET", "s3cret")
    req = _Obj(headers={"x-lifecycle-secret": given})
    if ok:
        assert run(sr.trigger_lifecycle(req)) == {"triggered": True}
    else:
        with pytest.raises(HTTPException) as ei:
            run(sr.trigger_lifecycle(req))
        assert ei.value.status_code == 401
    assert "hmac.compare_digest" in (ROOT / "routes/stripe_routes.py").read_text()


def test_two_failure_events_at_once_send_the_day0_email_once(env):
    db, mail = env["db"], env["mail"]
    db.add_user()

    async def both():
        await asyncio.gather(
            sr.stripe_webhook(_Req(json.dumps(invoice_event("evt_a")).encode())),
            sr.stripe_webhook(_Req(json.dumps(invoice_event("evt_b")).encode())))
    run(both())
    assert mail.days() == [1]


def test_a_failed_send_gives_the_claim_back_for_tomorrow(env):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    mail.fail_days = {10}
    run_lifecycle(clock, 10)
    assert db.user()["payment_email_sent_day"] == 7
    mail.fail_days = set()
    run_lifecycle(clock, 11)
    assert mail.days() == [10] and db.user()["payment_email_sent_day"] == 10


def test_the_lifecycle_never_pays_an_invoice(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    for day in range(0, 12):
        run_lifecycle(clock, day)
    assert not fs.names("Invoice.pay") and not fs.names("Invoice.list")


# ═════════════════════════════════════════════════════════════════════════════
# M9 - Stripe is asked before any lock
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("day,stage,sent", [(10, "failed", 7), (21, "soft_locked", 10), (60, "suspended", 21)])
def test_a_lost_payment_webhook_restores_instead_of_locking(env, day, stage, sent):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, stage=stage, sent=sent)
    fs.add_customer()
    fs.add_sub(SUB, status="active")                     # the customer paid; invoice.paid was lost
    run_lifecycle(clock, day)
    u = db.user()
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None
    assert u["payment_email_sent_day"] == 0 and mail.sent == []


def test_a_paid_up_canceling_subscription_restores_to_canceling(env):
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="active", cancel_at_period_end=True)
    run_lifecycle(clock, 10)
    assert db.user()["payment_status"] == "canceling"


def test_stripe_unreachable_moves_nobody_today_and_locks_tomorrow(env, caplog):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    fs.fail = {"Subscription.retrieve"}
    with caplog.at_level(logging.WARNING):
        run_lifecycle(clock, 10)
    assert db.user()["payment_status"] == "failed" and mail.sent == []
    assert any("Stripe unreachable" in r.message for r in caplog.records)
    fs.fail = set()
    run_lifecycle(clock, 11)
    assert db.user()["payment_status"] == "soft_locked" and mail.days() == [10]


def test_still_unpaid_in_stripe_locks_as_scheduled(env):
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="unpaid")
    run_lifecycle(clock, 10)
    assert db.user()["payment_status"] == "soft_locked"


def test_stripe_is_asked_about_every_failed_user_every_run(env):
    """2 Nov 2026 (L-1): asked even on a day with no lock or e-mail due."""
    db, clock, fs = env["db"], env["clock"], env["stripe"]
    failed_user(db, sent=1)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    run_lifecycle(clock, 3)
    assert fs.names("Subscription.retrieve")


# ═════════════════════════════════════════════════════════════════════════════
# M10 - deleting an account cancels its plans first, or deletes nothing
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def deleting(monkeypatch):
    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(ar, "revoke_all_sessions", _noop)
    monkeypatch.setattr(ar, "write_audit_log", _noop)
    return lambda user: run(ar.delete_account(_JsonReq({}), current_user=user,
                                              acordly_session=None, authorization=None))


def test_delete_account_cancels_every_live_primble_plan(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_pastdue", status="past_due")
    fs.add_sub("sub_foreign", status="active", user_id="other_user")
    deleting(db.user())
    assert fs.subs[SUB]["status"] == "canceled" and fs.subs["sub_pastdue"]["status"] == "canceled"
    assert fs.subs["sub_foreign"]["status"] == "active"
    assert db.user() is None


def test_delete_account_aborts_when_a_cancel_fails(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.fail = {"Subscription.cancel"}
    with pytest.raises(HTTPException) as ei:
        deleting(db.user())
    assert ei.value.status_code == 502
    assert db.user() is not None


def test_delete_account_aborts_when_stripe_is_unreachable(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None)
    fs.add_customer()
    fs.down = True
    with pytest.raises(HTTPException) as ei:
        deleting(db.user())
    assert ei.value.status_code == 503 and db.user() is not None


def test_delete_account_of_a_free_user_needs_no_stripe(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None, subscription_tier="free", stripe_customer_id=None, stripe_subscription_id=None)
    deleting(db.user())
    assert fs.calls == [] and db.user() is None


# ═════════════════════════════════════════════════════════════════════════════
# L2 / L3 / L4 - wording, the day-0 e-mail, logs
# ═════════════════════════════════════════════════════════════════════════════
def test_archived_says_paying_restores_access():
    with pytest.raises(HTTPException) as ei:
        check_payment_access("archived", "form")
    assert ei.value.detail == ARCHIVED_MESSAGE
    assert "Update your billing to restore access" in ARCHIVED_MESSAGE and "support" not in ARCHIVED_MESSAGE
    for rel in ("routes/form_routes.py", "utils/helpers.py"):
        src = (ROOT / rel).read_text()
        assert "Contact support@primble.ai to reactivate" not in src
        assert "Account archived. Contact support" not in src


def _captured_mail(monkeypatch, frontend="https://primble.ai/"):
    sent = []
    monkeypatch.setattr(email_service, "FRONTEND_URL", frontend)
    monkeypatch.setattr(email_service, "_send_generic_email",
                        lambda to, subject, txt, html: sent.append((to, subject, txt, html)) or True)
    return sent


def test_every_payment_email_links_to_manage_billing(monkeypatch):
    sent = _captured_mail(monkeypatch)
    for day in (1, 7, 10, 21, 60):
        assert email_service._send_payment_failed_email("a@b.test", "Ann", day) is True
    for _to, _s, txt, html in sent:
        assert "https://primble.ai/?open=billing" in txt and 'href="https://primble.ai/?open=billing"' in html
        assert "primble.ai//" not in txt + html


def test_the_day60_email_says_paying_reactivates(monkeypatch):
    sent = _captured_mail(monkeypatch)
    email_service._send_payment_failed_email("a@b.test", "Ann", 60)
    _to, subject, txt, html = sent[0]
    assert "subscription ended" not in subject.lower()
    assert "archived after 60 days of non-payment; update your billing to reactivate" in txt
    assert "contact support" not in (txt + html).lower()


def test_the_name_is_escaped_in_the_email_html(monkeypatch):
    sent = _captured_mail(monkeypatch)
    email_service._send_payment_failed_email("a@b.test", '<img src=x onerror="hack()">', 10)
    _to, _s, txt, html = sent[0]
    assert "<img" not in html and "&lt;img" in html
    assert "<img" in txt                                     # plain text keeps the name as typed


def test_no_email_address_in_billing_info_logs(env, caplog):
    db, mail, clock = env["db"], env["mail"], env["clock"]
    db.add_user()
    with caplog.at_level(logging.INFO):
        deliver(invoice_event("evt_f1"))
        clock.at(days=10, hours=1)
        env["stripe"].add_customer()
        env["stripe"].add_sub(SUB, status="past_due")
        run(ss.run_daily_payment_lifecycle())
    assert mail.days() == [1, 10]
    assert not [r for r in caplog.records if "@agency.test" in r.getMessage()]


def test_the_mail_sender_masks_addresses_in_its_logs():
    assert email_service._mask_email("jane.doe@agency.test") == "j***@agency.test"
    assert email_service._mask_email("") == "***"
    src = (ROOT / "services/email_service.py").read_text()
    assert "to={to_email}" not in src and "sent to {to_email}" not in src


@pytest.mark.parametrize("sent,status,day,want", [
    (0, "failed", 2, [1]),            # the day-0 e-mail never got out: sent now
    (1, "failed", 2, []),
    (0, "soft_locked", 12, [10]),     # past day 7 the stage e-mail covers it
])
def test_L3_the_lifecycle_sends_a_missing_day0_email(env, sent, status, day, want):
    db, clock, mail, fs = env["db"], env["clock"], env["mail"], env["stripe"]
    failed_user(db, stage=status, sent=sent)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    run_lifecycle(clock, day)
    assert mail.days() == want


# ═════════════════════════════════════════════════════════════════════════════
# L5 - the write routes check the payment lifecycle
# ═════════════════════════════════════════════════════════════════════════════
_GATED = {
    "routes/audit_routes.py": ["dismiss_recommendation", "answer_recommendation", "reopen_recommendation",
                               "reopen_issue", "resolve_recommendation", "set_issue_status_route",
                               "download_anyway", "resolve_issue"],
    "routes/form_routes.py": ["submission_integrity_resolve", "document_reclassify", "session_marketing_reason",
                              "underwriting_confirm_value", "underwriting_confirm_value_in_editor",
                              "client_answer_resolve"],
    "routes/questionnaire_routes.py": ["answer_question", "send_to_client", "draft_narrative",
                                       "approve_narrative"],
    "routes/policy_line_routes.py": ["_change"],
}


@pytest.mark.parametrize("rel,name", [(r, n) for r, ns in _GATED.items() for n in ns])
def test_write_routes_check_the_payment_lifecycle(rel, name):
    src = (ROOT / rel).read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _stripe_chain(c.func)[-1:] == ["check_payment_access"]]
    assert calls, f"{rel}:{name} writes package data without check_payment_access"
    assert any(isinstance(a, ast.Constant) and a.value == "form" for c in calls for a in c.args)


@pytest.mark.parametrize("rel,name", [(r, n) for r, ns in _GATED.items() for n in ns if n != "_change"])
def test_a_suspended_account_is_refused_by_the_write_routes(rel, name):
    import importlib
    mod = importlib.import_module(rel[:-3].replace("/", "."))
    fn = getattr(mod, name)
    fn = getattr(fn, "__wrapped__", fn)
    import inspect
    params = inspect.signature(fn).parameters
    kwargs = {p: _Obj(session_id="s1", form_id="F", fact_key="k", choice="x") for p in params}
    kwargs["current_user"] = {"id": "u1", "payment_status": "suspended"}
    for p in params:
        if p == "session_id":
            kwargs[p] = "s1"
    with pytest.raises(HTTPException) as ei:
        run(fn(**kwargs))
    assert ei.value.status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# Smaller doors touched on the way
# ═════════════════════════════════════════════════════════════════════════════
def test_cancel_subscription_touches_only_this_users_plans(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_foreign", status="active", user_id="someone_else")
    out = run(sr.cancel_subscription(current_user=db.user()))
    assert out["success"] is True
    assert fs.subs[SUB]["cancel_at_period_end"] is True
    assert fs.subs["sub_foreign"]["cancel_at_period_end"] is False
    u = db.user()
    assert u["payment_status"] == "canceling" and u["stripe_subscription_id"] == SUB


def test_verify_upgrade_with_a_stale_stored_customer_looks_it_up_by_tag(env, no_rate_limit):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, stripe_customer_id="cus_gone")
    fs.add_customer("cus_mine", user_id="u1")
    fs.add_sub("sub_new", status="active", customer="cus_mine")
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["upgraded"] is True and db.user()["stripe_customer_id"] == "cus_mine"


def test_a_reservation_on_an_account_no_longer_free_is_given_back(env):
    db = env["db"]
    db.add_user(subscription_tier="free", downloads_used=0, stripe_customer_id=None, stripe_subscription_id=None)
    assert run(us.reserve_free_package("u1", "pkg1"))
    db.lite.execute("UPDATE users SET subscription_tier='professional' WHERE id='u1'")  # upgraded meanwhile
    count("u1", "pkg1", reserved_free=True)
    u = db.user()
    assert u["downloads_used"] == 0 and u["packages_used"] == 1



def test_a_reservation_always_names_its_session():
    """2 Nov 2026 (M-2): a reservation with no session could never be settled
    after a crash - the API refuses one."""
    with pytest.raises((TypeError, ValueError)):
        run(us.reserve_free_package("u1"))
    with pytest.raises((TypeError, ValueError)):
        run(us.reserve_free_package("u1", ""))
