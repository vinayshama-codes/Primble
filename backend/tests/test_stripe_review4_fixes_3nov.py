"""Adversarial billing review, pass 4 (3 Nov 2026), fixed offline. The reviewer's
repros (each asserted the WRONG behaviour) turned around to assert the CORRECT
one, plus the edge cases each fix needs. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py; nothing reaches Stripe or a database.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import services.auth_service as auth_service
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, fs, mail, run, sessions, side,
    sr, svc, us, webhook,
)
from tests.test_stripe_payment_lifecycle_2nov import _Req, sub_event
from tests.test_stripe_review2_fixes_2nov import _deleted, _freeze_usage_clock, _unit
from tests.test_stripe_review2_fixes_3nov import A, B, C, _failing_since_A, _overage, _renewal_paid


def _units(db, state=None):
    return {k: v for k, v in db.keys("overage_unit:").items() if state is None or v == state}


def _failing_with_usage(env, monkeypatch, n1, n2=0):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    _failing_since_A(db)
    db.lite.execute("UPDATE users SET payment_status='failed', payment_email_sent_day=1")
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(n1):
        clock.now = A + timedelta(days=2, minutes=i)
        count("u1", f"p1_{i}")
    for i in range(n2):
        clock.now = B + timedelta(days=2, minutes=i)
        count("u1", f"p2_{i}")
    return db, fs, clock


# ═════════════════════════════════════════════════════════════════════════════
# #1 - a delayed twin of the current renewal after a tier switch recounts nothing
# ═════════════════════════════════════════════════════════════════════════════
def test_Q1_a_delayed_twin_after_a_tier_switch_bills_nothing(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300,
                billing_period_start=(A + timedelta(minutes=5)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", amount=29900)
    fs.subs[SUB]["items"]["data"][0].update(current_period_start=int(B.timestamp()),
                                            current_period_end=int(C.timestamp()))
    clock.now = B + timedelta(hours=1)
    paid = _renewal_paid("evt_i2_paid", "in_2", inv_created=B, paid_at=clock.now, start=B, end=C)
    deliver(paid)
    for i in range(105):
        clock.now = B + timedelta(hours=2, minutes=i)
        count("u1", f"pro_{i}")
    W = B + timedelta(days=1)
    clock.now = W
    fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": 19900, "currency": "usd",
                                                 "recurring": {"interval": "month", "interval_count": 1}}
    deliver({"id": "evt_switch", "type": "customer.subscription.updated", "created": int(W.timestamp()),
             "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                 "metadata": fs.subs[SUB]["metadata"], "items": fs.subs[SUB]["items"]}}})
    assert db.user()["subscription_tier"] == "essentials"
    for i in range(100):
        clock.now = W + timedelta(hours=1, minutes=i)
        count("u1", f"ess_{i}")
    clock.now = B + timedelta(days=2)
    twin = json.loads(json.dumps(paid))
    twin["id"], twin["type"] = "evt_i2_succeeded", "invoice.payment_succeeded"
    deliver(twin)
    assert _overage(fs) == [] and _units(db) == {}
    assert db.user()["packages_used"] == 100


# ═════════════════════════════════════════════════════════════════════════════
# #2 - an older renewal paid first places only its own period's extras
# ═════════════════════════════════════════════════════════════════════════════
def test_Q2_older_first_still_failing_holds_nothing_from_the_next_period(env, monkeypatch):
    db, fs, clock = _failing_with_usage(env, monkeypatch, 100, 100)
    pay = C + timedelta(days=1)
    fs.add_open_invoice("in_2", attempt_count=3, reason="subscription_cycle")
    clock.now = pay
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B))
    assert _units(db) == {}
    fs.invoices["in_2"]["status"] = "paid"
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay + timedelta(minutes=1), start=B, end=C))
    assert db.user()["payment_status"] == "ok" and _overage(fs) == []


def test_Q2_older_first_restoring_bills_nothing_from_the_next_period(env, monkeypatch):
    db, fs, clock = _failing_with_usage(env, monkeypatch, 100, 100)
    clock.now = C + timedelta(days=1)
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=clock.now, start=A, end=B))
    assert _overage(fs) == []


def test_Q2_older_first_bills_exactly_its_own_extras(env, monkeypatch):
    """110 in P1 (5 extras) + 100 in P2 (none): exactly P1's five, never a P2 package."""
    db, fs, clock = _failing_with_usage(env, monkeypatch, 110, 100)
    pay = C + timedelta(days=1)
    fs.add_open_invoice("in_2", attempt_count=3, reason="subscription_cycle")
    clock.now = pay
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B))
    held = _units(db, "overage_held")
    assert len(held) == 5 and all(":p1_" in k for k in held)
    fs.invoices["in_2"]["status"] = "paid"
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay + timedelta(minutes=1), start=B, end=C))
    billed = _overage(fs)
    assert len(billed) == 5 and all(":p1_" in i["metadata"]["unit_key"] for i in billed)


# ═════════════════════════════════════════════════════════════════════════════
# #3 - units held on a plan that ended unpaid are never billed on a later plan
# ═════════════════════════════════════════════════════════════════════════════
def test_Q3_old_plans_held_units_are_forgiven_at_its_end(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    anchor = datetime(2027, 1, 31, 15, tzinfo=timezone.utc)
    db.add_user(billing_cycle="annual", packages_used=105, packages_limit=100,
                billing_period_start=anchor.isoformat(), payment_status="failed",
                payment_failed_at=datetime(2027, 2, 10, 15, tzinfo=timezone.utc).isoformat(),
                payment_email_sent_day=1)
    for key, kind in (("usage_anchor:u1", "usage_anchor"), ("usage_month:u1", "usage_month")):
        db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (key, kind, anchor.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="past_due", cycle="annual")
    for i in range(3):
        clock.now = datetime(2027, 2, 11, 15, tzinfo=timezone.utc) + timedelta(minutes=i)
        assert count("u1", f"held_{i}")["pkg_eval"]["billing"] == "held"
    fs.subs[SUB]["status"] = "canceled"
    clock.now = datetime(2027, 3, 1, 15, tzinfo=timezone.utc)
    deliver(_deleted("evt_del_A"))
    assert set(_units(db).values()) == {"overage_forgiven"}
    fs.add_sub("sub_B", status="active")
    clock.now = datetime(2027, 6, 1, 15, tzinfo=timezone.utc)
    deliver(checkout_event("evt_co_B", "sub_B"))
    db.lite.execute("UPDATE users SET payment_status='canceling'")
    clock.now = datetime(2027, 6, 5, 15, tzinfo=timezone.utc)
    deliver(sub_event("evt_resume_B", "active", sub="sub_B", created=clock.now))
    run(us.retry_pending_overage())
    assert _overage(fs) == []


def test_Q3_a_replaced_dead_plan_forgives_its_held_units(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    _unit(db, "u1", "h1", "overage_held")
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_cs", "sub_new"))
    assert _units(db) == {"overage_unit:u1:h1": "overage_forgiven"}


# ═════════════════════════════════════════════════════════════════════════════
# #4 - hold or bill is decided from the row under the lock
# ═════════════════════════════════════════════════════════════════════════════
def test_Q4_extras_found_after_another_restore_are_billed_not_stranded(env, monkeypatch):
    db, fs, clock = _failing_with_usage(env, monkeypatch, 110)
    fs.add_open_invoice("in_2", attempt_count=3, reason="subscription_cycle")
    pay = B + timedelta(days=5)
    clock.now = pay
    real_state = sr._subscription_state

    async def state(sub_id, event_id, *a, **k):
        if event_id == "evt_i1":
            got = await real_state(sub_id, event_id, *a, **k)
            await asyncio.sleep(0.05)
            return got
        fs.invoices["in_2"]["status"] = "paid"
        return await real_state(sub_id, event_id, *a, **k)
    monkeypatch.setattr(sr, "_subscription_state", state)
    e1 = _renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B)
    e2 = _renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay + timedelta(seconds=20), start=B, end=C)

    async def both():
        await asyncio.gather(sr.stripe_webhook(_Req(json.dumps(e1).encode())),
                             sr.stripe_webhook(_Req(json.dumps(e2).encode())))
    asyncio.run(both())
    assert db.user()["payment_status"] == "ok"
    assert len(_overage(fs)) == 5 and set(_units(db).values()) == {"overage_billed"}


# ═════════════════════════════════════════════════════════════════════════════
# #5 - a mid-period failure holds its extras; the restore bills them, once
# ═════════════════════════════════════════════════════════════════════════════
def _inv_event(evt_id, etype, inv_id, reason, when):
    inv = {"id": inv_id, "object": "invoice", "customer": CUS,
           "parent": {"type": "subscription_details", "subscription_details": {"subscription": SUB}},
           "billing_reason": reason, "status": "paid" if etype == "invoice.paid" else "open",
           "created": int(when.timestamp()), "status_transitions": {"paid_at": int(when.timestamp())},
           "lines": {"data": [], "has_more": False}}
    return {"id": evt_id, "type": etype, "created": int(when.timestamp()), "data": {"object": inv}}


def test_Q5_extras_counted_during_a_midperiod_failure_are_held_then_billed_once(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300, billing_period_start=B.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", C.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(100):
        clock.now = B + timedelta(days=1, minutes=i)
        count("u1", f"base_{i}")
    clock.now = B + timedelta(days=10)
    deliver(_inv_event("evt_pf", "invoice.payment_failed", "in_pr", "subscription_update", clock.now))
    results = []
    for i in range(10):
        clock.now = B + timedelta(days=11, minutes=i)
        results.append(count("u1", f"fail_{i}")["pkg_eval"].get("billing"))
    assert results.count("held") == 5 and _overage(fs) == []
    clock.now = B + timedelta(days=12)
    deliver(_inv_event("evt_pp", "invoice.paid", "in_pr", "subscription_update", clock.now))
    assert db.user()["payment_status"] == "ok" and len(_overage(fs)) == 5
    clock.now = C + timedelta(hours=1)
    deliver(_renewal_paid("evt_i3", "in_3", inv_created=C, paid_at=clock.now, start=C, end=C + timedelta(days=30)))
    assert len(_overage(fs)) == 5


def test_Q5_a_renewal_failure_is_left_to_the_paid_renewal(env, monkeypatch):
    """With the period ended (or no end stored) the counter may carry an unpaid
    earlier period: nothing is held at count time."""
    db, fs, clock = _failing_with_usage(env, monkeypatch, 0)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", A.isoformat()))
    db.lite.execute("UPDATE users SET packages_used=105")
    clock.now = A + timedelta(days=3)
    assert count("u1", "x")["pkg_eval"]["billing"] == "not_billable"
    assert _units(db) == {}


# ═════════════════════════════════════════════════════════════════════════════
# #6 - the period a package belongs to is read under the count's own lock
# ═════════════════════════════════════════════════════════════════════════════
def test_Q6_a_reset_committing_after_the_count_never_bills_it_as_old_overage(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300, billing_period_start=A.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", B.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(105):
        clock.now = A + timedelta(days=1, minutes=i)
        count("u1", f"p1_{i}")
    clock.now = B + timedelta(minutes=30)
    real = auth_service.invalidate_user_cache
    fired = {"n": 0}

    async def _between(uid):
        if not fired["n"]:
            fired["n"] = 1
            e = _renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=clock.now, start=B, end=C)
            await sr.stripe_webhook(_Req(json.dumps(e).encode()))
        return await real(uid)
    monkeypatch.setattr(auth_service, "invalidate_user_cache", _between)
    r = count("u1", "x")
    assert db.user()["packages_used"] == 1
    assert r["pkg_eval"]["billing"] == "deferred" and _overage(fs) == []


# ═════════════════════════════════════════════════════════════════════════════
# #7 - units left to a person by a refused final bill are never billed again
# ═════════════════════════════════════════════════════════════════════════════
def test_Q7_manual_final_bill_units_are_never_billed_automatically(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status="canceling")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    _unit(db, "u1", "p3", "overage_pending")
    fs.refuse.add("Invoice.create")
    deliver(_deleted())
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_MANUAL]
    assert _units(db) == {"overage_unit:u1:p3": "overage_manual"}
    fs.refuse.clear()
    fs.add_sub("sub_B", status="active")
    deliver(checkout_event("evt_co_B", "sub_B"))
    run(us.retry_pending_overage())
    assert _overage(fs) == []
