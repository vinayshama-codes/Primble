"""Adversarial billing review, pass 3 (3 Nov 2026), fixed offline. The reviewer's
repros (each asserted the WRONG behaviour) turned around to assert the CORRECT
one, plus the edge cases each fix needs. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py (sqlite behind an asyncpg-shaped pool,
a fake Stripe recording every call, sockets blocked). Nothing reaches Stripe or a
database.
"""
import asyncio
import json
from datetime import timedelta

import services.stripe_service as svc_mod
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, clock, count, db, deliver, env, fs, mail, run, sessions, side, sr, svc, us,
    webhook,
)
from tests.test_stripe_payment_lifecycle_2nov import _Req
from tests.test_stripe_review2_fixes_2nov import _freeze_usage_clock
from tests.test_stripe_review2_fixes_3nov import A, B, C, _failing_since_A, _marker, _overage, _renewal_paid


def _units(db, state=None):
    return {k: v for k, v in db.keys("overage_unit:").items() if state is None or v == state}


def _p1_usage_while_failing(env, monkeypatch, n=110):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    _failing_since_A(db)
    db.lite.execute("UPDATE users SET payment_status='failed', payment_email_sent_day=1")
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(n):                       # P1 = [A, B): used while the renewal I1 is failing
        clock.now = A + timedelta(days=2, minutes=i)
        count("u1", f"p1_{i}")
    return db, fs, clock


# ═════════════════════════════════════════════════════════════════════════════
# #1 - two renewals handled at once never rewind the period
# ═════════════════════════════════════════════════════════════════════════════
def test_R1_concurrent_renewals_leave_the_newer_period(env, monkeypatch):
    """Repro test_DEFECT_concurrent_renewals_rewind_the_period, fixed: the period
    is judged from the row read under its lock inside the transaction."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    _failing_since_A(db)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    pay = B + timedelta(days=5)
    clock.now = pay
    real_state = sr._subscription_state

    async def slow_state(sub_id, event_id, *a, **k):
        await asyncio.sleep(0.05 if event_id == "evt_i1" else 0.0)      # the older commits last
        return await real_state(sub_id, event_id, *a, **k)
    monkeypatch.setattr(sr, "_subscription_state", slow_state)
    e1 = _renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B)
    e2 = _renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay, start=B, end=C)

    async def both():
        await asyncio.gather(sr.stripe_webhook(_Req(json.dumps(e1).encode())),
                             sr.stripe_webhook(_Req(json.dumps(e2).encode())))
    asyncio.run(both())
    u = db.user()
    assert u["payment_status"] == "ok"
    assert u["billing_period_start"] == B.isoformat()
    assert _marker(db, "billing_period_end:u1") == C.isoformat()
    for i in range(110):
        clock.now = pay + timedelta(days=1, minutes=i)
        count("u1", f"p2_{i}")
    assert len(_overage(fs)) == 5                                       # P2's extras billed in P2


def test_R1_the_period_is_read_inside_the_transaction():
    """The decision reads billing_period_start from the row lock's RETURNING,
    never from the copy read before the Stripe calls."""
    import inspect
    src = inspect.getsource(sr._handle_invoice_paid)
    lock = src.index('RETURNING billing_period_start')
    assert src.index('stored_start = _safe_parse_dt(locked.get("billing_period_start"))') > lock
    assert src.index("record_period_end(conn") > lock
    assert 'row.get("billing_period_start")' not in src


# ═════════════════════════════════════════════════════════════════════════════
# #2 - the older renewal handled second still bills its own period's extras
# ═════════════════════════════════════════════════════════════════════════════
def test_R2_newer_invoice_first_still_bills_P1_overage_once(env, monkeypatch):
    """Repro test_DEFECT_newer_invoice_first_never_bills_P1_overage, fixed."""
    db, fs, clock = _p1_usage_while_failing(env, monkeypatch)
    pay = B + timedelta(days=5)
    fs.add_open_invoice("in_1", attempt_count=4, reason="subscription_cycle")
    clock.now = pay
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay, start=B, end=C))
    assert _overage(fs) == []                                           # still failing: nothing billed
    fs.invoices["in_1"]["status"] = "paid"
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay + timedelta(minutes=1), start=A, end=B))
    assert db.user()["payment_status"] == "ok"
    assert len(_overage(fs)) == 5 and len(_units(db, "overage_billed")) == 5
    # A second delivery of the older invoice (another event id) adds nothing.
    deliver(_renewal_paid("evt_i1_again", "in_1", inv_created=A, paid_at=pay + timedelta(minutes=1),
                          start=A, end=B))
    assert len(_overage(fs)) == 5


def test_R2_control_older_invoice_first_bills_P1_overage_once(env, monkeypatch):
    db, fs, clock = _p1_usage_while_failing(env, monkeypatch)
    pay = B + timedelta(days=5)
    fs.add_open_invoice("in_2", attempt_count=3, reason="subscription_cycle")
    clock.now = pay
    deliver(_renewal_paid("evt_i1", "in_1", inv_created=A, paid_at=pay, start=A, end=B))
    fs.invoices["in_2"]["status"] = "paid"
    clock.now = pay + timedelta(minutes=1)
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=pay + timedelta(minutes=1), start=B, end=C))
    assert db.user()["payment_status"] == "ok"
    assert len(_overage(fs)) == 5


def test_R2_a_period_never_gets_more_units_than_its_extras(env, monkeypatch):
    """Units the ledger already has for the period's packages count against its
    extras, wherever the counter placed them - the recount adds only the rest."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user()
    counted = [(f"s{i}", (A + timedelta(minutes=i)).isoformat()) for i in range(110)]
    for sid in ("s3", "s4"):                                            # billed at count time, low places
        db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                        (us.overage_unit_key("u1", sid), "overage_billed", T0.isoformat()))

    async def place():
        async with sr.get_pool().acquire() as conn:
            return await us.place_period_overage(conn, "u1", counted, 105, hold=False)
    assert run(place()) == 3
    assert len(_units(db)) == 5 and len(_units(db, "overage_pending")) == 3
    assert run(place()) == 0                                            # idempotent


# ═════════════════════════════════════════════════════════════════════════════
# #3 - a price billed every N > 1 months never syncs as a cycle
# ═════════════════════════════════════════════════════════════════════════════
def _sub(amount, interval, count_, meta_cycle="annual"):
    return {"id": SUB, "metadata": {"plan": "professional", "billing_cycle": meta_cycle, "user_id": "u1"},
            "items": {"data": [{"price": {"unit_amount": amount, "currency": "usd",
                                          "recurring": {"interval": interval, "interval_count": count_}}}]}}


def test_R3_an_off_cycle_price_names_no_cycle_and_no_plan():
    for sub in (_sub(286800, "month", 12), _sub(89700, "month", 3, meta_cycle="monthly"),
                _sub(500000, "year", 2)):
        assert svc.price_cycle(sub) is None
        assert svc_mod.off_cycle_price(sub) is True
        assert svc.subscription_plan(sub) == (None, None)
    # Count 1 (or none given) is still a cycle.
    assert svc.price_cycle(_sub(1, "month", 1)) == "monthly"
    no_count = {"items": {"data": [{"price": {"recurring": {"interval": "year"}}}]}}
    assert svc.price_cycle(no_count) == "annual" and svc_mod.off_cycle_price(no_count) is False
    assert svc.subscription_plan(_sub(286800, "year", 1)) == ("professional", "annual")


def test_R3_a_12_month_price_is_not_synced_and_a_person_is_alerted_once(env, monkeypatch):
    """Repro test_DEFECT_12_month_price_charges_overage_inside_the_monthly_allowance, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_cycle="annual", packages_limit=100,
                billing_period_start=(T0 - timedelta(days=2)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", cycle="annual", amount=286800)
    item = _sub(286800, "month", 12)["items"]["data"][0]
    fs.subs[SUB]["items"] = {"data": [item]}
    clock.now = T0 + timedelta(minutes=1)
    for evt_id in ("evt_swap12", "evt_swap12_b"):
        deliver({"id": evt_id, "type": "customer.subscription.updated", "created": int(T0.timestamp()),
                 "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                     "metadata": fs.subs[SUB]["metadata"], "items": fs.subs[SUB]["items"]}}})
    u = db.user()
    assert (u["billing_cycle"], u["subscription_tier"]) == ("annual", "professional")
    assert not any(c[2].get("pending_invoice_item_interval") == "" for c in fs.names("Subscription.modify"))
    alerts = [a for a in env["alerts"] if "unsupported cycle" in a[1]]
    assert len(alerts) == 1 and alerts[0][0] == svc.BILLING_ALERT_TO and SUB in alerts[0][2]


# ═════════════════════════════════════════════════════════════════════════════
# #4 - overage found by a reset is recorded before the commit
# ═════════════════════════════════════════════════════════════════════════════
def test_R4_deferred_overage_survives_a_failed_bill_after_the_reset(env, monkeypatch):
    """Repro test_DEFECT_deferred_overage_lost_when_the_post_commit_bill_fails_once, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=40, billing_period_start=A.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", B.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(110):
        clock.now = B + timedelta(minutes=i % 50, seconds=i)
        count("u1", f"p2_{i}")
    assert _units(db) == {} and _overage(fs) == []                      # all deferred
    real = us._refresh_user

    async def down(uid):
        raise ConnectionError("db blip")
    monkeypatch.setattr(us, "_refresh_user", down)
    clock.now = B + timedelta(hours=1)
    evt = _renewal_paid("evt_ren", "in_ren", inv_created=B, paid_at=B + timedelta(hours=1), start=B, end=C)
    deliver(evt)
    assert db.user()["packages_used"] == 110
    assert len(_units(db, "overage_pending")) == 5 and _overage(fs) == []     # recorded, not yet billed
    assert db.user()["overage_packages_pending"] == 5
    deliver(evt)                                                        # re-delivery: duplicate
    monkeypatch.setattr(us, "_refresh_user", real)
    clock.now = B + timedelta(days=1)
    assert run(us.retry_pending_overage()) == 5                         # the daily retry bills them
    assert len(_overage(fs)) == 5 and len(_units(db, "overage_billed")) == 5
    assert run(us.retry_pending_overage()) == 0


def test_R4_a_webhook_restore_makes_held_units_pending_before_its_bill(env, monkeypatch):
    """Held units of a user restored by invoice.paid are pending in the restore's
    own transaction: a failed bill after it is retried by the daily job."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(payment_status="failed", payment_failed_at=(T0 - timedelta(days=2)).isoformat(),
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    for sid in ("h1", "h2"):
        db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                        (us.overage_unit_key("u1", sid), "overage_held", T0.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")

    async def boom(*_a, **_k):
        raise ConnectionError("blip")
    monkeypatch.setattr(sr, "retry_pending_overage", boom)
    clock.now = T0 + timedelta(hours=1)
    evt = _renewal_paid("evt_rec", "in_rec", inv_created=T0 - timedelta(days=2), paid_at=clock.now,
                        start=T0 - timedelta(days=2), end=T0 + timedelta(days=28))
    evt["data"]["object"]["billing_reason"] = "manual"
    deliver(evt)
    assert db.user()["payment_status"] == "ok"
    assert len(_units(db, "overage_pending")) == 2 and _units(db, "overage_held") == {}
    assert run(us.retry_pending_overage()) == 2 and len(_overage(fs)) == 2


def test_R4_a_still_failing_reset_holds_and_bills_nothing(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(payment_status="failed", payment_failed_at=(B - timedelta(hours=1)).isoformat(),
                billing_period_start=A.isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_open_invoice("in_other", attempt_count=2)                    # still not paid up
    for i in range(108):
        clock.now = B + timedelta(minutes=i % 50, seconds=i)
        count("u1", f"p_{i}")
    clock.now = B + timedelta(hours=2)
    deliver(_renewal_paid("evt_ren", "in_ren", inv_created=B, paid_at=clock.now, start=B, end=C))
    assert db.user()["payment_status"] == "failed"
    assert len(_units(db, "overage_held")) == 3 and _overage(fs) == []
    assert run(us.retry_pending_overage()) == 0                         # held is never retried while failing


# ═════════════════════════════════════════════════════════════════════════════
# #5 - a closing plan's final bill never takes another plan's unit
# ═════════════════════════════════════════════════════════════════════════════
def _final_setup(env, state, at):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id="sub_new")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    fs.add_sub("sub_new", status="active")
    uk = "overage_unit:u1:new_106"
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (uk, state, at.isoformat()))
    key = svc.final_overage_key("u1", SUB, CUS, 300)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (key, svc.FINAL_PENDING, T0.isoformat()))
    return db, fs, uk, key


def test_R5_the_new_plans_in_flight_unit_stays_off_the_old_plans_final_invoice(env):
    """Repro test_DEFECT_new_plans_in_flight_unit_is_billed_on_the_old_plans_final_invoice_too, fixed."""
    db, fs, uk, key = _final_setup(env, "overage_billing", T0)
    fs.items.append({"id": "ii_new_106", "customer": CUS, "amount": 300, "subscription": "sub_new",
                     "metadata": {"user_id": "u1", "unit_key": uk, "type": "overage_package"}})
    out = run(svc.settle_final_overage(key))
    assert out["state"] == "none" and fs.invoices == {}
    assert [i["id"] for i in fs.items if not i.get("invoice")] == ["ii_new_106"]
    assert db.keys("overage_unit:")[uk] == "overage_billing"            # untouched: its own retry owns it


def test_R5_a_unit_just_claimed_is_never_owed_by_a_final_bill(env):
    """An overage_billing unit under an hour old has a Stripe call in flight -
    not owed here, even before its item exists."""
    from datetime import datetime, timezone
    db, fs, uk, key = _final_setup(env, "overage_billing", datetime.now(timezone.utc))
    assert run(svc.settle_final_overage(key))["state"] == "none" and fs.invoices == {}


def test_R5_a_stale_unit_Stripe_never_took_is_still_billed_on_the_final_invoice(env):
    db, fs, uk, key = _final_setup(env, "overage_billing", T0 - timedelta(days=2))
    assert run(svc.settle_final_overage(key))["state"] == "invoiced"
    (final,) = fs.invoices.values()
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == final["id"]] == [uk]
