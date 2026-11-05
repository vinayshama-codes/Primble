"""Adversarial billing review, pass 2 (3 Nov 2026), fixed offline. The reviewer's
repros (each asserted the WRONG behaviour) turned around to assert the CORRECT
one, plus the edge cases each fix needs. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py (sqlite behind an asyncpg-shaped pool,
a fake Stripe recording every call, sockets blocked). Nothing reaches Stripe or a
database.
"""
from datetime import timedelta

import pytest

from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, fs, mail,
    paid_event, run, run_lifecycle, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_stripe_payment_lifecycle_2nov import invoice_event
from tests.test_stripe_review2_fixes_2nov import _freeze_usage_clock

A = T0 - timedelta(days=30)      # start of period P1 (renewal invoice I1)
B = T0                           # start of period P2 (renewal invoice I2)
C = T0 + timedelta(days=30)      # start of period P3 (renewal invoice I3)
D = T0 + timedelta(days=60)


@pytest.fixture
def no_rl(monkeypatch):
    async def _f(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _f)


def _line(start, end):
    return {"type": "subscription", "period": {"start": int(start.timestamp()), "end": int(end.timestamp())},
            "parent": {"type": "subscription_item_details"}}


def _proration_line(start, end, amount, legacy=False):
    period = {"start": int(start.timestamp()), "end": int(end.timestamp())}
    if legacy:      # older API shapes: the flag on the line itself
        return {"type": "subscription", "proration": True, "amount": amount, "period": period}
    return {"amount": amount, "period": period,
            "parent": {"type": "subscription_item_details",
                       "subscription_item_details": {"proration": True, "subscription": SUB,
                                                     "invoice_item": "ii_prorate"}}}


def _renewal_paid(evt_id, inv_id, inv_created, paid_at, start, end):
    """invoice.paid for a monthly renewal invoice as the dahlia snapshot carries it."""
    inv = {"id": inv_id, "object": "invoice", "customer": CUS,
           "parent": {"type": "subscription_details", "subscription_details": {"subscription": SUB}},
           "billing_reason": "subscription_cycle", "status": "paid",
           "created": int(inv_created.timestamp()),
           "status_transitions": {"paid_at": int(paid_at.timestamp())},
           "lines": {"data": [_line(start, end)], "has_more": False}}
    return {"id": evt_id, "type": "invoice.paid", "created": int(paid_at.timestamp()), "data": {"object": inv}}


def _overage(fs):
    return [i for i in fs.items if (i.get("metadata") or {}).get("type") == "overage_package"]


def _marker(db, key):
    row = db.lite.execute("SELECT processed_at FROM processed_webhook_events WHERE event_id=?", (key,)).fetchone()
    return row[0] if row else None


def _failing_since_A(db):
    """Monthly Professional (100 + 5 buffer, $3 overage); P1's renewal I1
    (created A) failed and the user went down Brent's schedule to suspended."""
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300,
                billing_period_start=(A - timedelta(days=30) + timedelta(hours=1)).isoformat(),
                payment_status="suspended", payment_failed_at=(A + timedelta(hours=1)).isoformat(),
                payment_email_sent_day=21)


# ═════════════════════════════════════════════════════════════════════════════
# #1 - a renewal's proration lines never move the period it opens
# ═════════════════════════════════════════════════════════════════════════════
def test_P1_proration_lines_never_name_the_invoice_period():
    S = A + timedelta(days=15)
    for legacy in (False, True):
        obj = {"lines": {"data": [_proration_line(S, B, -9950, legacy), _proration_line(S, B, 14950, legacy),
                                  _line(B, C)]}}
        assert sr._invoice_period_start(obj) == B and sr._invoice_period_end(obj) == C
    only_prorations = {"lines": {"data": [_proration_line(S, B, 100)], "has_more": False}}
    assert sr._invoice_period_start(only_prorations) is None
    # An ordinary plan line without the flag is still the period.
    assert sr._invoice_period_start({"lines": {"data": [_line(B, C)]}}) == B


def test_P1_the_renewal_after_a_support_upgrade_starts_its_own_period(env, monkeypatch):
    """Repro test_6, fixed: the 80 packages used after the switch stay in the old
    period; the new period starts at the plan line, not at the switch."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="essentials", packages_limit=100, overage_rate=200,
                billing_period_start=(A + timedelta(hours=1)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", plan="essentials", amount=19900)
    S = A + timedelta(days=15)
    fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": 29900, "currency": "usd",
                                                 "recurring": {"interval": "month", "interval_count": 1}}
    clock.now = S + timedelta(minutes=1)
    deliver({"id": "evt_swap", "type": "customer.subscription.updated", "created": int(S.timestamp()),
             "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                 "metadata": {"user_id": "u1", "plan": "essentials", "billing_cycle": "monthly"},
                                 "items": fs.subs[SUB]["items"]}}})
    assert db.user()["subscription_tier"] == "professional"
    for i in range(80):
        clock.now = S + timedelta(days=1, minutes=i)
        count("u1", f"p1_{i}")
    assert db.user()["packages_used"] == 80
    clock.now = B + timedelta(hours=1)
    inv = {"id": "in_ren", "object": "invoice", "customer": CUS, "subscription": SUB,
           "billing_reason": "subscription_cycle", "status": "paid", "created": int(B.timestamp()),
           "status_transitions": {"paid_at": int((B + timedelta(hours=1)).timestamp())},
           "lines": {"data": [_proration_line(S, B, -9950), _proration_line(S, B, 14950), _line(B, C)],
                     "has_more": False}}
    deliver({"id": "evt_ren", "type": "invoice.paid", "created": int((B + timedelta(hours=1)).timestamp()),
             "data": {"object": inv}})
    u = db.user()
    assert u["packages_used"] == 0 and u["billing_period_start"] == B.isoformat()
    for i in range(30):
        clock.now = B + timedelta(days=2, minutes=i)
        count("u1", f"p2_{i}")
    assert db.user()["packages_used"] == 30 and _overage(fs) == []


# ═════════════════════════════════════════════════════════════════════════════
# #2 - two open renewals paid together each open their own period, any order
# ═════════════════════════════════════════════════════════════════════════════
def test_P2_older_renewal_paid_first_then_newer_resets_into_its_own_period(env, monkeypatch):
    """Repro test_1a, fixed: P2's renewal starts P2 - P1's 90 packages never count in it."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    _failing_since_A(db)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(90):
        clock.now = A + timedelta(days=1, minutes=i)
        count("u1", f"p1_{i}")
    pay = B + timedelta(days=5)
    clock.now = pay
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B))
    u = db.user()
    assert (u["packages_used"], u["billing_period_start"]) == (90, A.isoformat())
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay + timedelta(minutes=1), start=B, end=C))
    u = db.user()
    assert u["payment_status"] == "ok"
    assert (u["packages_used"], u["billing_period_start"]) == (0, B.isoformat())
    assert _marker(db, "billing_period_end:u1") == C.isoformat()
    assert _marker(db, "last_paid:u1") == (pay + timedelta(minutes=1)).isoformat()
    for i in range(30):
        clock.now = pay + timedelta(days=1, minutes=i)
        count("u1", f"p2_{i}")
    assert db.user()["packages_used"] == 30 and _overage(fs) == []


def test_P2_newer_renewal_paid_first_then_older_never_rewinds_the_period(env, monkeypatch):
    """Repro test_1b, fixed: the older invoice changes neither the period start nor
    its end; P2's extras are billed in P2."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    _failing_since_A(db)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_open_invoice("in_1", attempt_count=4, reason="subscription_cycle")      # I1 still owed
    pay = B + timedelta(days=5)
    clock.now = pay
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay, start=B, end=C))
    assert db.user()["payment_status"] == "suspended"
    assert _marker(db, "billing_period_end:u1") == C.isoformat()
    fs.invoices["in_1"]["status"] = "paid"
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay + timedelta(minutes=1), start=A, end=B))
    u = db.user()
    assert u["payment_status"] == "ok"
    assert _marker(db, "billing_period_end:u1") == C.isoformat()          # never moved back
    assert u["billing_period_start"] == B.isoformat()
    assert _marker(db, "last_paid:u1") == (pay + timedelta(minutes=1)).isoformat()
    for i in range(110):
        clock.now = pay + timedelta(days=1, minutes=i)
        count("u1", f"p2_{i}")
    assert len(_overage(fs)) == 5                                         # #106-#110, billed in P2
    # The P3 renewal opens P3 from zero; nothing is billed twice.
    clock.now = C + timedelta(hours=1)
    deliver(_renewal_paid("evt_i3", "in_3", inv_created=C, paid_at=C + timedelta(hours=1), start=C, end=D))
    assert db.user()["packages_used"] == 0 and len(_overage(fs)) == 5


def test_P2_an_older_invoice_may_still_push_a_missing_end_forward(env, monkeypatch):
    """`only_later` refuses a rewind, never a move forward: a stored end older than
    the late invoice's own end is replaced."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_period_start=(B + timedelta(hours=1)).isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", (A + timedelta(days=1)).isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = B + timedelta(hours=2)
    deliver(_renewal_paid("evt_old", "in_old", inv_created=A, paid_at=B + timedelta(hours=2), start=A, end=B))
    assert _marker(db, "billing_period_end:u1") == B.isoformat()
    assert db.user()["billing_period_start"] == (B + timedelta(hours=1)).isoformat()   # no reset


# ═════════════════════════════════════════════════════════════════════════════
# #3 - an enterprise row with no Stripe plan is never re-linked and locked
# ═════════════════════════════════════════════════════════════════════════════
def test_P3_an_enterprise_row_is_never_relinked_to_its_dead_plan(env):
    """Repro test_2, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="enterprise", packages_limit=5000, packages_used=42)
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    clock.now = T0
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted", created=T0))
    clock.now = T0 + timedelta(hours=1)
    deliver(invoice_event("evt_old_fail", sub=SUB, fmt="parent", created=clock.now))
    u = db.user()
    assert (u["subscription_tier"], u["stripe_subscription_id"], u["payment_status"], u["payment_failed_at"]) == \
        ("enterprise", None, "ok", None)
    assert env["mail"].days() == []
    run_lifecycle(clock, 11)
    run_lifecycle(clock, 22)
    assert db.user()["payment_status"] == "ok"


def test_P3_control_a_free_row_is_still_protected(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="professional")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted", created=T0))
    clock.now = T0 + timedelta(hours=1)
    deliver(invoice_event("evt_old_fail", sub=SUB, fmt="parent", created=clock.now))
    u = db.user()
    assert (u["subscription_tier"], u["stripe_subscription_id"], u["payment_status"]) == ("free", None, "ok")


def test_P3_a_paid_row_found_by_customer_is_still_relinked_and_failed(env):
    """The fallback still works for a paying row whose stored subscription is empty."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="professional", stripe_subscription_id=None)
    fs.add_customer()
    clock.now = T0 + timedelta(hours=1)
    deliver(invoice_event("evt_fail", sub=SUB, fmt="parent", created=clock.now))
    u = db.user()
    assert (u["stripe_subscription_id"], u["payment_status"]) == (SUB, "failed")


# ═════════════════════════════════════════════════════════════════════════════
# #4 - the price that named the plan keeps its own cycle
# ═════════════════════════════════════════════════════════════════════════════
def _annual_with_monthly_addon_first():
    return {"metadata": {"plan": "professional", "billing_cycle": "annual", "user_id": "u1"},
            "items": {"data": [
                {"price": {"unit_amount": 1000, "currency": "usd", "recurring": {"interval": "month"}}},
                {"price": {"unit_amount": 286800, "currency": "usd", "recurring": {"interval": "year"}}}]}}


def test_P4_an_annual_plan_with_a_monthly_item_first_stays_annual(env, monkeypatch):
    """Repro test_3, fixed."""
    sub = _annual_with_monthly_addon_first()
    assert svc.plan_from_subscription(sub) == ("professional", "annual")
    assert svc.subscription_plan(sub) == ("professional", "annual")
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_cycle="annual", packages_limit=100,
                billing_period_start=(T0 - timedelta(days=40)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", cycle="annual", amount=286800)
    fs.subs[SUB]["items"] = sub["items"]
    clock.now = T0 + timedelta(minutes=1)
    deliver({"id": "evt_addon", "type": "customer.subscription.updated", "created": int(T0.timestamp()),
             "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                 **sub}}})
    assert db.user()["billing_cycle"] == "annual"
    assert not any(c[2].get("pending_invoice_item_interval") == "" for c in fs.names("Subscription.modify"))


def test_P4_the_metadata_fallback_still_takes_the_price_interval():
    """No price names a plan: the metadata names it and the price's interval
    still decides the cycle (support switches a cycle in Stripe)."""
    sub = {"metadata": {"plan": "professional", "billing_cycle": "monthly"},
           "items": {"data": [{"price": {"unit_amount": 250000, "recurring": {"interval": "year"}}}]}}
    assert svc.subscription_plan(sub) == ("professional", "annual")
    no_amount = {"metadata": {"plan": "essentials", "billing_cycle": "annual"},
                 "items": {"data": [{"price": {"recurring": {"interval": "month"}}}]}}
    assert svc.subscription_plan(no_amount) == ("essentials", "monthly")


# ═════════════════════════════════════════════════════════════════════════════
# #5 - a dead stored plan replaced by a new one bills its extras
# ═════════════════════════════════════════════════════════════════════════════
def _old_plan_with_pending_extras(db, fs, n=5):
    for i in range(n):
        key = f"overage_unit:u1:old_{i}"
        db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (key, "overage_billed", T0.isoformat()))
        fs.items.append({"id": f"ii_old_{i}", "customer": CUS, "amount": 300, "subscription": SUB,
                         "metadata": {"user_id": "u1", "unit_key": key, "type": "overage_package"}})


def _final_invoice_units(fs):
    (inv,) = fs.invoices.values()
    return sorted(i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"])


def test_P5_verify_upgrade_replacing_a_dead_plan_bills_its_extras_once(env, monkeypatch, no_rl):
    """Repro test_4, fixed - the late subscription.deleted changes nothing more."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=110, packages_limit=100, payment_status="canceling")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    _old_plan_with_pending_extras(db, fs)
    fs.add_sub("sub_new", status="active", created=10_000)
    clock.now = T0 + timedelta(minutes=5)
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True
    assert db.user()["stripe_subscription_id"] == "sub_new"
    assert db.keys("final_overage:") == {svc.final_overage_key("u1", SUB, CUS, 300): svc.FINAL_INVOICED}
    assert _final_invoice_units(fs) == [f"overage_unit:u1:old_{i}" for i in range(5)]
    assert not [i for i in fs.items if i.get("subscription") == SUB and not i.get("invoice")]
    clock.now = T0 + timedelta(hours=2)
    deliver(sub_event("evt_del_late", "canceled", etype="customer.subscription.deleted", created=T0))
    assert len(fs.invoices) == 1 and db.user()["stripe_subscription_id"] == "sub_new"


def test_P5_a_checkout_replacing_a_dead_plan_bills_its_extras(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=110, packages_limit=100)
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    _old_plan_with_pending_extras(db, fs, n=2)
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_cs", "sub_new"))
    u = db.user()
    assert (u["stripe_subscription_id"], u["packages_used"]) == ("sub_new", 0)
    assert list(db.keys("final_overage:")) == [svc.final_overage_key("u1", SUB, CUS, 300)]
    assert _final_invoice_units(fs) == ["overage_unit:u1:old_0", "overage_unit:u1:old_1"]
    assert not fs.names("Refund.create")


def test_P5_a_new_plan_on_an_empty_row_claims_no_old_bill(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_cs", "sub_new"))
    assert db.keys("final_overage:") == {} and fs.invoices == {}


# ═════════════════════════════════════════════════════════════════════════════
# #6 - ended is not "had": a plan the deleted account never carried is refunded
# ═════════════════════════════════════════════════════════════════════════════
def test_P6_paid_but_never_granted_then_deleted_is_refunded(env):
    """Repro test_5, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", latest_invoice="in_new")
    fs.invoice_payments["in_new"] = ["pi_new"]
    # delete-account: the row carried no plan, so its final-bill row names none.
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    (svc.final_overage_key("u1", None, CUS, 300), svc.FINAL_NONE, T0.isoformat()))
    fs.subs["sub_new"]["status"] = "canceled"
    db.lite.execute("DELETE FROM users WHERE id='u1'")
    clock.now = T0 + timedelta(hours=3)
    deliver(checkout_event("evt_cs_late", "sub_new", invoice="in_new", created=T0))
    assert [r["amount"] for r in fs.refunds] == [29900]
    assert db.keys(svc.DUP_PREFIX) == {"duplicate_checkout:u1:sub_new:in_new": svc.DUP_REFUNDED}
    assert not [a for a in env["side"]["audit"] if a[1] == "payment.deleted_account_checkout_not_refunded"]


def test_P6_a_plan_another_user_carried_never_counts_as_this_ones(monkeypatch):
    """The ledger match is exact: another user's row, or another subscription
    whose id merely starts the same, is not this plan."""
    import asyncio

    rows = [{"event_id": svc.final_overage_key("u10", "sub_new", CUS, 300)},
            {"event_id": svc.final_overage_key("u1", "sub_new_2", CUS, 300)}]

    class _Conn:
        async def fetch(self, sql, prefix):
            return [r for r in rows if r["event_id"].startswith(prefix[:-1])]

    class _Pool:
        def acquire(self):
            class _A:
                async def __aenter__(self):
                    return _Conn()

                async def __aexit__(self, *_):
                    return False
            return _A()

    monkeypatch.setattr(sr, "get_pool", lambda: _Pool())
    assert asyncio.run(sr._plan_was_carried("u1", "sub_new")) is False
    rows.append({"event_id": svc.final_overage_key("u1", "sub_new", CUS, 300)})
    assert asyncio.run(sr._plan_was_carried("u1", "sub_new")) is True
