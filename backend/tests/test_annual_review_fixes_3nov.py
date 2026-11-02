"""The review of the 3 Nov annual build (FIX FIRST), each finding pinned.

1. A failed MONTHLY overage invoice looped: the subscription stays "active"
   while Stripe retries the invoice, so the daily job restored the user and the
   next retry failure e-mailed day 0 again. "Paid up" is now: the subscription
   active / trialing AND no open invoice Stripe already tried to charge - in
   the daily job, invoice.paid and customer.subscription.updated alike.
2. A failure created before a payment that moved no period (an annual plan's
   monthly overage invoice) is stale: `last_paid:<user>` in the ledger.
3. A plan's CYCLE change on the same tier (support, in Stripe) syncs the plan.
4. Every path that writes a plan from Stripe leaves the month logic its data.
5. /me and the package limit show the new usage month's count.
Reuses the offline fakes of tests/test_stripe_live_readiness_2nov.py.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from config.settings import PLANS
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, clock, count, db, deliver, env, fs, mail,
    paid_event, run, run_lifecycle, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_annual_monthly_allowance_3nov import _annual_user, _marker, dt
from tests.test_stripe_review2_fixes_2nov import _freeze_usage_clock


def _pii_failed(evt_id, when, invoice="in_pii_m2"):
    return {"id": evt_id, "type": "invoice.payment_failed", "created": int(when.timestamp()),
            "data": {"object": {"id": invoice, "customer": CUS, "subscription": SUB,
                                "billing_reason": "automatic_pending_invoice_item_invoice",
                                "status": "open"}}}


def _pii_paid(evt_id, when, invoice="in_pii_m2"):
    evt = paid_event(evt_id, invoice, created=when, inv_created=when - timedelta(days=3),
                     lines=[{"amount": 300, "parent": {"type": "invoice_item_details"},
                             "period": {"start": int(when.timestamp()), "end": int(when.timestamp())}}])
    evt["data"]["object"]["billing_reason"] = "automatic_pending_invoice_item_invoice"
    return evt


def _active(evt_id, when, cycle="annual"):
    return sub_event(evt_id, "active", metadata={"plan": "professional", "billing_cycle": cycle}, created=when)


# ═════════════════════════════════════════════════════════════════════════════
# 1 - a failed monthly overage invoice: failed until THAT invoice is paid
# ═════════════════════════════════════════════════════════════════════════════
def test_R1_retries_of_a_failed_overage_invoice_send_no_further_email_and_never_restore(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    fs.add_open_invoice("in_pii_m2")
    statuses = []
    for day in (0, 2, 4):                                   # Smart Retries
        clock.now = T0 + timedelta(days=day)
        deliver(_pii_failed(f"evt_fail_{day}", clock.now))
        statuses.append(db.user()["payment_status"])
        fs.invoices["in_pii_m2"]["attempt_count"] += 1
        run_lifecycle(clock, day + 1)                       # the plan is still "active" in Stripe
        statuses.append(db.user()["payment_status"])
    assert statuses == ["failed"] * 6
    assert env["mail"].days() == [1]                        # day 0, once
    assert db.user()["payment_failed_at"] == T0.isoformat()
    # An unrelated update (a card change, our own interval modify) says "active".
    clock.now = T0 + timedelta(days=5, hours=3)
    deliver(_active("evt_card", clock.now))
    assert db.user()["payment_status"] == "failed"
    # The invoice is paid: restored, once.
    fs.invoices["in_pii_m2"]["status"] = "paid"
    clock.now = T0 + timedelta(days=6)
    deliver(_pii_paid("evt_paid", clock.now))
    u = db.user()
    assert u["payment_status"] == "ok" and u["payment_failed_at"] is None
    assert env["mail"].days() == [1]


def test_R1_the_daily_job_restores_once_the_invoice_is_paid(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    fs.add_open_invoice("in_pii_m2")
    clock.now = T0
    deliver(_pii_failed("evt_f0", T0))
    run_lifecycle(clock, 1)
    assert db.user()["payment_status"] == "failed"
    fs.invoices["in_pii_m2"]["status"] = "paid"             # paid in the portal; the webhook lost
    run_lifecycle(clock, 2)
    assert db.user()["payment_status"] == "ok"
    assert _marker(db, "last_paid:u1") is not None


def test_R1_subscription_updated_restores_only_a_paid_up_plan(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    fs.add_open_invoice("in_pii_m2")
    clock.now = T0
    deliver(_pii_failed("evt_f0", T0))
    clock.now = T0 + timedelta(hours=2)
    deliver(_active("evt_a1", clock.now))
    assert db.user()["payment_status"] == "failed"
    fs.invoices["in_pii_m2"]["status"] = "paid"
    clock.now = T0 + timedelta(hours=3)
    deliver(_active("evt_a2", clock.now))
    assert db.user()["payment_status"] == "ok"
    assert _marker(db, "last_paid:u1") == clock.now.isoformat()


def test_R1_stripe_unreachable_on_subscription_updated_keeps_the_failure(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    clock.now = T0
    deliver(_pii_failed("evt_f0", T0))
    fs.fail.add("Subscription.retrieve")
    clock.now = T0 + timedelta(hours=2)
    deliver(_active("evt_a1", clock.now))
    assert db.user()["payment_status"] == "failed"


def test_R3_past_due_is_never_paid_up_whatever_its_latest_invoice(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    clock.now = T0
    deliver(_pii_failed("evt_f0", T0))
    fs.subs[SUB]["status"] = "past_due"
    fs.subs[SUB]["latest_invoice"] = "in_yearly"            # the paid yearly renewal
    run_lifecycle(clock, 1)
    assert db.user()["payment_status"] == "failed"
    assert not fs.names("Invoice.list")                     # past_due decides alone


@pytest.mark.parametrize("status,invoice,paid", [
    ("active", None, True),
    ("trialing", None, True),
    ("active", {"attempt_count": 0}, True),                 # finalized, never charged yet
    ("active", {"attempt_count": 1}, False),
    ("active", {"attempt_count": 3}, False),
    ("past_due", None, False),
    ("unpaid", None, False),
])
def test_the_paid_up_rule(env, status, invoice, paid):
    fs = env["stripe"]
    fs.add_customer()
    fs.add_sub(SUB, status=status, cycle="annual")
    if invoice is not None:
        fs.add_open_invoice("in_open", attempt_count=invoice["attempt_count"])
    assert svc.subscription_payment_state(SUB)["paid"] is paid
    state = svc.subscription_status(SUB, check_open=True)
    assert state["open_attempted"] is bool(invoice and invoice["attempt_count"] > 0)


def test_an_attempted_open_invoice_of_another_subscription_does_not_count(env):
    fs = env["stripe"]
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_open_invoice("in_other", sub="sub_other")
    assert svc.subscription_payment_state(SUB)["paid"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 2 - a failure created before the last payment is stale
# ═════════════════════════════════════════════════════════════════════════════
def test_R2_a_late_failure_after_paying_the_overage_invoice_is_stale(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    fs.add_open_invoice("in_pii_m2")
    clock.now = T0
    deliver(_pii_failed("evt_f0", T0))
    assert db.user()["payment_status"] == "failed"
    # Day 2 10:05 the customer pays; that event arrives first.
    fs.invoices["in_pii_m2"]["status"] = "paid"
    clock.now = T0 + timedelta(days=2, minutes=5)
    deliver(_pii_paid("evt_paid", clock.now))
    assert db.user()["payment_status"] == "ok"
    # ...then the retry failure Stripe created at 10:00 arrives late.
    clock.now = T0 + timedelta(days=2, minutes=6)
    deliver(_pii_failed("evt_f_late", T0 + timedelta(days=2)))
    assert db.user()["payment_status"] == "ok"
    assert env["mail"].days() == [1]


def test_R2_a_past_due_update_created_before_the_last_payment_is_stale(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=T0 - timedelta(days=40), used=10)
    paid_at = T0 + timedelta(days=2)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("last_paid:u1", "last_paid", paid_at.isoformat()))
    clock.now = paid_at + timedelta(minutes=5)
    deliver(sub_event("evt_pd_late", "past_due", created=paid_at - timedelta(minutes=1)))
    assert db.user()["payment_status"] == "ok"
    deliver(sub_event("evt_pd_new", "past_due", created=paid_at + timedelta(minutes=1)))
    assert db.user()["payment_status"] == "failed"


def test_paid_after_takes_the_later_of_the_period_start_and_the_last_payment():
    start, paid = dt(2027, 1, 10), dt(2027, 3, 5)
    row = {"billing_period_start": start.isoformat(), "last_paid_at": paid.isoformat()}
    assert sr._paid_after(row, dt(2027, 3, 4)) is True
    assert sr._paid_after(row, dt(2027, 3, 6)) is False
    assert sr._paid_after({"billing_period_start": start.isoformat()}, dt(2027, 3, 4)) is False
    assert sr._paid_after({"last_paid_at": paid.isoformat()}, dt(2027, 3, 4)) is True


# ═════════════════════════════════════════════════════════════════════════════
# 3 - a cycle change on the same tier syncs the plan
# ═════════════════════════════════════════════════════════════════════════════
def _switch_event(evt_id, when, interval, plan="professional", meta_cycle="monthly"):
    """customer.subscription.updated as Stripe sends it after support switches
    the price: the items carry the new price; our metadata is unchanged."""
    return {"id": evt_id, "type": "customer.subscription.updated", "created": int(when.timestamp()),
            "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                "metadata": {"user_id": "u1", "plan": plan, "billing_cycle": meta_cycle},
                                "items": {"data": [{"price": {"recurring": {"interval": interval}},
                                                    "current_period_start": int(when.timestamp())}]}}}}


def _stripe_switched(fs, interval, start, months):
    fs.subs[SUB]["items"] = {"data": [{"price": {"recurring": {"interval": interval}},
                                       "current_period_start": int(start.timestamp()),
                                       "current_period_end": int(us.add_months(start, months).timestamp())}]}


def _monthly_user(env, monkeypatch, used=0):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_cycle="monthly", packages_used=used,
                billing_period_start=(T0 - timedelta(days=10)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    return db, fs, clock


def test_monthly_to_annual_on_the_same_tier_syncs_the_plan(env, monkeypatch):
    db, fs, clock = _monthly_user(env, monkeypatch)
    for i in range(3):                                       # this month, before the switch
        clock.now = T0 - timedelta(days=5, minutes=-i)
        count("u1", f"before_{i}")
    switch = T0
    _stripe_switched(fs, "year", switch, 12)
    clock.now = switch + timedelta(seconds=30)
    count("u1", "after_0")                                   # between the switch and its webhook
    clock.now = switch + timedelta(minutes=1)
    deliver(_switch_event("evt_sw", switch, "year"))
    u = db.user()
    cfg = PLANS["professional"]["annual"]
    assert (u["subscription_tier"], u["billing_cycle"]) == ("professional", "annual")
    assert (u["packages_limit"], u["overage_rate"]) == (cfg["packages"], cfg["overage_rate"])
    assert u["billing_period_start"] == switch.isoformat()
    assert u["packages_used"] == 1                           # the old month's three stay with it
    assert _marker(db, "usage_anchor:u1") == switch.isoformat()
    assert _marker(db, "billing_period_end:u1") == us.add_months(switch, 12).isoformat()
    (mod,) = fs.names("Subscription.modify")
    assert mod[2]["pending_invoice_item_interval"] == {"interval": "month", "interval_count": 1}
    assert mod[2]["idempotency_key"] == f"primble-pii-interval:{SUB}:evt_sw"
    assert "pii_interval:" + SUB in db.keys("pii_interval:")


def test_annual_back_to_monthly_drops_the_months_and_the_interval_and_back_again(env, monkeypatch):
    db, fs, clock = _monthly_user(env, monkeypatch)
    s1 = T0
    _stripe_switched(fs, "year", s1, 12)
    clock.now = s1 + timedelta(minutes=1)
    deliver(_switch_event("evt_sw1", s1, "year"))
    assert db.user()["billing_cycle"] == "annual"
    s2 = T0 + timedelta(hours=5)
    _stripe_switched(fs, "month", s2, 1)
    clock.now = s2 + timedelta(minutes=1)
    deliver(_switch_event("evt_sw2", s2, "month", meta_cycle="annual"))
    u = db.user()
    assert (u["billing_cycle"], u["packages_limit"]) == ("monthly", PLANS["professional"]["monthly"]["packages"])
    assert db.keys("usage_anchor:") == {} and db.keys("usage_month:") == {}
    assert _marker(db, "billing_period_end:u1") == us.add_months(s2, 1).isoformat()
    unset = fs.names("Subscription.modify")[-1]
    assert unset[2]["pending_invoice_item_interval"] == ""
    assert db.keys("pii_interval:") == {}
    # Back to annual within 24 hours: a fresh idempotency key, so Stripe sets it again.
    s3 = T0 + timedelta(hours=9)
    _stripe_switched(fs, "year", s3, 12)
    clock.now = s3 + timedelta(minutes=1)
    deliver(_switch_event("evt_sw3", s3, "year"))
    again = fs.names("Subscription.modify")[-1]
    assert again[2]["idempotency_key"] == f"primble-pii-interval:{SUB}:evt_sw3"
    assert db.user()["billing_cycle"] == "annual"
    assert _marker(db, "usage_anchor:u1") == s3.isoformat()


def test_a_late_switch_event_never_undoes_a_later_switch(env, monkeypatch):
    """Stripe does not deliver in order: the payload says annual, Stripe says
    the plan is monthly again - nothing changes."""
    db, fs, clock = _monthly_user(env, monkeypatch)
    _stripe_switched(fs, "month", T0, 1)
    clock.now = T0 + timedelta(hours=6)
    deliver(_switch_event("evt_old", T0 - timedelta(hours=1), "year"))
    u = db.user()
    assert u["billing_cycle"] == "monthly"
    assert not fs.names("Subscription.modify")


def test_a_switch_stripe_cannot_confirm_is_a_503_and_nothing_is_claimed(env, monkeypatch):
    db, fs, clock = _monthly_user(env, monkeypatch)
    _stripe_switched(fs, "year", T0, 12)
    fs.fail.add("Subscription.retrieve")
    clock.now = T0 + timedelta(minutes=1)
    with pytest.raises(HTTPException) as ei:
        deliver(_switch_event("evt_sw", T0, "year"))
    assert ei.value.status_code == 503
    assert "evt_sw" not in db.keys("evt_")
    assert db.user()["billing_cycle"] == "monthly"


def test_a_cycle_change_never_touches_enterprise(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="enterprise", packages_limit=5000, billing_cycle="monthly")
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _stripe_switched(fs, "year", T0, 12)
    deliver(_switch_event("evt_sw", T0, "year"))
    u = db.user()
    assert (u["subscription_tier"], u["billing_cycle"], u["packages_limit"]) == ("enterprise", "monthly", 5000)
    assert not fs.names("Subscription.modify")


def test_a_tier_change_starts_a_fresh_allowance_at_the_change(env, monkeypatch):
    db, fs, clock = _monthly_user(env, monkeypatch)
    for i in range(4):
        clock.now = T0 - timedelta(days=3, minutes=-i)
        count("u1", f"before_{i}")
    fs.subs[SUB]["metadata"]["plan"] = "business"
    _stripe_switched(fs, "month", T0 - timedelta(days=10), 1)   # same period, prorated
    clock.now = T0 + timedelta(minutes=1)
    deliver(_switch_event("evt_up", T0, "month", plan="business"))
    u = db.user()
    assert (u["subscription_tier"], u["packages_limit"]) == ("business", PLANS["business"]["monthly"]["packages"])
    assert u["packages_used"] == 0 and u["billing_period_start"] == T0.isoformat()
    assert not fs.names("Subscription.modify")


# ═════════════════════════════════════════════════════════════════════════════
# 4 - the portal restore, verify-upgrade and /me leave the month data
# ═════════════════════════════════════════════════════════════════════════════
def test_the_portal_restore_writes_the_period_and_an_annual_plans_months(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    start = T0 - timedelta(days=45)
    db.add_user(stripe_subscription_id=None, billing_cycle="monthly")
    fs.add_customer()
    fs.add_sub("sub_lost", status="active", cycle="annual")
    fs.subs["sub_lost"]["items"]["data"][0].update(
        current_period_start=int(start.timestamp()),
        current_period_end=int(us.add_months(start, 12).timestamp()))
    clock.now = T0 - timedelta(days=20)
    count("u1", "last_month")
    clock.now = T0 - timedelta(days=5)
    count("u1", "this_month")
    clock.now = T0
    run(sr._restore_subscription(db.user(), fs.customers[CUS]))
    u = db.user()
    assert (u["stripe_subscription_id"], u["billing_cycle"]) == ("sub_lost", "annual")
    assert u["billing_period_start"] == start.isoformat()
    assert _marker(db, "usage_anchor:u1") == start.isoformat()
    assert _marker(db, "usage_month:u1") == us.add_months(start, 1).isoformat()
    assert _marker(db, "billing_period_end:u1") == us.add_months(start, 12).isoformat()
    assert u["packages_used"] == 1                           # this usage month's package only
    assert fs.names("Subscription.modify")[-1][2]["pending_invoice_item_interval"]["interval"] == "month"


def test_verify_upgrade_to_annual_writes_the_months_and_the_interval(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)

    async def _no_rl(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _no_rl)
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", cycle="annual")
    fs.subs["sub_new"]["items"]["data"][0].update(
        current_period_start=int(T0.timestamp()),
        current_period_end=int(us.add_months(T0, 12).timestamp()))
    clock.now = T0 + timedelta(minutes=1)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["upgraded"] is True
    assert _marker(db, "usage_anchor:u1") == T0.isoformat()
    assert _marker(db, "billing_period_end:u1") == us.add_months(T0, 12).isoformat()
    assert fs.names("Subscription.modify")[-1][2]["pending_invoice_item_interval"]["interval"] == "month"


def test_me_adopting_an_annual_plan_writes_its_months(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    from routes import auth_routes as ar
    monkeypatch.setattr(ar, "_auth_redis", None)
    start = T0 - timedelta(days=3)
    db.add_user(subscription_tier="essentials", stripe_subscription_id=None, billing_cycle="monthly")
    fs.add_customer()
    fs.add_sub("sub_mine", status="active", cycle="annual", plan="professional")
    fs.subs["sub_mine"]["items"]["data"][0].update(
        current_period_start=int(start.timestamp()),
        current_period_end=int(us.add_months(start, 12).timestamp()))
    clock.now = T0
    out = run(ar.get_me(current_user=db.user()))
    assert (out["subscription_tier"], out["billing_cycle"]) == ("professional", "annual")
    assert _marker(db, "usage_anchor:u1") == start.isoformat()
    assert _marker(db, "billing_period_end:u1") == us.add_months(start, 12).isoformat()
    assert db.user()["billing_period_start"] == start.isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# 5 - after a month boundary, /me and the package limit show the new month
# ═════════════════════════════════════════════════════════════════════════════
def test_me_shows_the_new_months_count_after_a_boundary(env, monkeypatch):
    from routes import auth_routes as ar
    monkeypatch.setattr(ar, "_auth_redis", None)
    db, fs, clock = _annual_user(env, monkeypatch, used=57)  # anchor 31 Jan 2027
    clock.now = dt(2027, 3, 1, 9)
    out = run(ar.get_me(current_user=db.user()))
    assert out["packages_used"] == 0
    assert db.user()["packages_used"] == 0
    assert _marker(db, "usage_month:u1") == dt(2027, 2, 28).isoformat()


def test_me_inside_the_month_reads_no_more_than_the_ledger(env, monkeypatch):
    from routes import auth_routes as ar
    monkeypatch.setattr(ar, "_auth_redis", None)
    db, fs, clock = _annual_user(env, monkeypatch, used=57)
    clock.now = dt(2027, 2, 20, 9)
    before = len(db.log)
    out = run(ar.get_me(current_user=db.user()))
    assert out["packages_used"] == 57
    writes = [sql for sql, _a in db.log[before:] if sql.lstrip().upper().startswith(("UPDATE", "INSERT"))]
    assert writes == []


def test_the_package_limit_reads_the_new_month(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=99)
    clock.now = dt(2027, 3, 1, 9)
    out = run(svc.evaluate_package_limit(db.user()))
    assert out["pkgs_used"] == 0 and out["status"] == "normal"


def test_a_monthly_plan_shows_its_stored_count(env, monkeypatch):
    db, fs, clock = _monthly_user(env, monkeypatch, used=12)
    out = run(svc.evaluate_package_limit(db.user()))
    assert out["pkgs_used"] == 12


def test_a_row_that_missed_its_switch_counts_only_the_current_month(env, monkeypatch):
    """The row still says monthly; Stripe has billed the plan yearly for 45 days
    (an earlier switch event was lost). The sync anchors the months on the
    annual period and counts only the current usage month."""
    db, fs, clock = _monthly_user(env, monkeypatch)
    start = T0 - timedelta(days=45)
    clock.now = T0 - timedelta(days=30)
    count("u1", "month_one")
    clock.now = T0 - timedelta(days=5)
    count("u1", "month_two")
    _stripe_switched(fs, "year", start, 12)
    clock.now = T0
    deliver(_switch_event("evt_late", T0, "year"))
    u = db.user()
    assert u["billing_cycle"] == "annual" and u["packages_used"] == 1
    assert _marker(db, "usage_anchor:u1") == start.isoformat()
    assert _marker(db, "usage_month:u1") == us.add_months(start, 1).isoformat()
