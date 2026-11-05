"""Annual plans: 100 packages PER MONTH, extras billed MONTHLY (Brent, 3 Nov 2026).

- config.settings.PLANS: an annual plan's `packages` is the monthly allowance.
- services/usage_service: usage months anchored on the plan's start, rolled
  over lazily under the user row's lock and by the daily job.
- stripe_routes / stripe_service: Stripe's `pending_invoice_item_interval`
  (monthly) on every annual subscription, set at checkout and ensured daily;
  Stripe's monthly pending-item invoices never reset usage.
Reuses the offline fakes of tests/test_stripe_live_readiness_2nov.py.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import PLANS
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, failed_user, fs, mail,
    paid_event, run, run_lifecycle, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_stripe_review2_fixes_2nov import _deleted, _final_invoices, _freeze_usage_clock, _line

UTC = timezone.utc


def dt(y, m, d, h=15, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


# ═════════════════════════════════════════════════════════════════════════════
# The plan table
# ═════════════════════════════════════════════════════════════════════════════
def test_an_annual_plan_allows_100_packages_a_month():
    assert PLANS["essentials"]["annual"]["packages"] == 100
    assert PLANS["professional"]["annual"]["packages"] == 100
    assert PLANS["business"]["annual"]["packages"] == 400
    assert PLANS["essentials"]["annual"]["amount"] == 190800        # prices unchanged
    assert PLANS["professional"]["annual"]["amount"] == 286800
    for plan in ("essentials", "professional", "business"):
        assert PLANS[plan]["annual"]["packages"] == PLANS[plan]["monthly"]["packages"]


# ═════════════════════════════════════════════════════════════════════════════
# Month arithmetic
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("anchor,k,want", [
    (dt(2027, 1, 31), 1, dt(2027, 2, 28)),          # clamped
    (dt(2028, 1, 31), 1, dt(2028, 2, 29)),          # leap year
    (dt(2027, 1, 31), 2, dt(2027, 3, 31)),          # back to the 31st (from the anchor, never chained)
    (dt(2027, 1, 30), 1, dt(2027, 2, 28)),
    (dt(2027, 1, 29), 1, dt(2027, 2, 28)),
    (dt(2028, 1, 29), 1, dt(2028, 2, 29)),
    (dt(2027, 3, 31), 1, dt(2027, 4, 30)),
    (dt(2027, 12, 15), 1, dt(2028, 1, 15)),         # year wrap
    (dt(2027, 11, 30), 3, dt(2028, 2, 29)),
    (dt(2027, 5, 10), 12, dt(2028, 5, 10)),         # the yearly renewal
    (dt(2028, 2, 29), 12, dt(2029, 2, 28)),
])
def test_add_months(anchor, k, want):
    assert us.add_months(anchor, k) == want


@pytest.mark.parametrize("anchor,now,start,nxt", [
    (dt(2027, 1, 31), dt(2027, 2, 27), dt(2027, 1, 31), dt(2027, 2, 28)),
    (dt(2027, 1, 31), dt(2027, 2, 28, 14, 59), dt(2027, 1, 31), dt(2027, 2, 28)),   # a minute early
    (dt(2027, 1, 31), dt(2027, 2, 28, 15, 0), dt(2027, 2, 28), dt(2027, 3, 31)),    # exactly the boundary
    (dt(2027, 1, 31), dt(2027, 3, 1), dt(2027, 2, 28), dt(2027, 3, 31)),
    (dt(2027, 1, 31), dt(2027, 3, 31, 16, 0), dt(2027, 3, 31), dt(2027, 4, 30)),
    (dt(2027, 1, 15), dt(2027, 5, 20), dt(2027, 5, 15), dt(2027, 6, 15)),           # months skipped
    (dt(2027, 1, 15), dt(2027, 1, 15, 14), dt(2027, 1, 15), dt(2027, 2, 15)),       # before the anchor
])
def test_usage_month_bounds(anchor, now, start, nxt):
    assert us.usage_month_bounds(anchor, now) == (start, nxt)


# ═════════════════════════════════════════════════════════════════════════════
# Checkout: allowance, anchor, monthly overage billing
# ═════════════════════════════════════════════════════════════════════════════
def _annual_checkout(env, sub="sub_ann", start=None, plan="professional"):
    db, fs = env["db"], env["stripe"]
    fs.add_sub(sub, status="active", cycle="annual", plan=plan)
    if start is not None:
        fs.subs[sub]["items"]["data"][0].update(
            current_period_start=int(start.timestamp()),
            current_period_end=int(us.add_months(start, 12).timestamp()))
    deliver(checkout_event(f"evt_{sub}", sub, cycle="annual", plan=plan))
    return db, fs


def _marker(db, key):
    row = db.lite.execute("SELECT processed_at FROM processed_webhook_events WHERE event_id=?", (key,)).fetchone()
    return row[0] if row else None


def test_an_annual_checkout_records_100_a_month_its_anchor_and_monthly_overage_billing(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    _annual_checkout(env, start=dt(2027, 1, 31))
    u = db.user()
    assert (u["billing_cycle"], u["packages_limit"]) == ("annual", 100)
    assert _marker(db, "usage_anchor:u1") == dt(2027, 1, 31).isoformat()
    assert _marker(db, "usage_month:u1") == dt(2027, 1, 31).isoformat()
    (mod,) = fs.names("Subscription.modify")
    assert mod[1] == ("sub_ann",)
    assert mod[2]["pending_invoice_item_interval"] == {"interval": "month", "interval_count": 1}
    assert mod[2]["idempotency_key"] == "primble-pii-interval:sub_ann"
    assert fs.subs["sub_ann"]["pending_invoice_item_interval"]["interval"] == "month"
    assert "pii_interval:sub_ann" in db.keys("pii_interval:")


def test_a_monthly_checkout_is_unchanged(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_m", status="active")
    deliver(checkout_event("evt_m", "sub_m"))
    assert db.user()["packages_limit"] == 100 and db.user()["billing_cycle"] == "monthly"
    assert not fs.names("Subscription.modify")
    assert db.keys("usage_anchor:") == {} and db.keys("pii_interval:") == {}


def test_a_duplicate_annual_checkout_sets_nothing(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active", cycle="annual", latest_invoice="in_dup")
    fs.invoice_payments["in_dup"] = ["pi_dup"]
    deliver(checkout_event("evt_dup", "sub_dup", cycle="annual", invoice="in_dup"))
    assert not fs.names("Subscription.modify") and db.keys("usage_anchor:") == {}


def test_a_failed_interval_is_set_by_the_daily_job_once(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.fail = {"Subscription.modify"}
    _annual_checkout(env)
    assert db.keys("pii_interval:") == {}
    assert "pending_invoice_item_interval" not in fs.subs["sub_ann"]
    fs.fail = set()
    run_lifecycle(clock, 1)
    assert fs.subs["sub_ann"]["pending_invoice_item_interval"]["interval"] == "month"
    n = len(fs.calls)
    run_lifecycle(clock, 2)                                     # done: no Stripe call again
    assert not [c for c in fs.calls[n:] if c[0].startswith("Subscription")]


def test_the_daily_job_leaves_an_interval_already_set_alone(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(billing_cycle="annual", stripe_subscription_id="sub_ann")
    fs.add_customer()
    fs.add_sub("sub_ann", status="active", cycle="annual")
    fs.subs["sub_ann"]["pending_invoice_item_interval"] = {"interval": "month", "interval_count": 1}
    run_lifecycle(clock, 1)
    assert not fs.names("Subscription.modify") and "pii_interval:sub_ann" in db.keys("pii_interval:")


def test_an_internal_test_mode_subscription_is_noted_once(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(billing_cycle="annual", stripe_subscription_id="sub_test_mode", packages_limit=1200)
    fs.add_customer()
    run_lifecycle(clock, 1)
    run_lifecycle(clock, 2)
    assert len(fs.names("Subscription.retrieve")) == 1
    assert db.keys("pii_interval:") == {"pii_interval:sub_test_mode": "pii_interval_missing"}
    assert db.user()["packages_limit"] == 1200                   # an existing row keeps its limit


# ═════════════════════════════════════════════════════════════════════════════
# Usage months
# ═════════════════════════════════════════════════════════════════════════════
def _annual_user(env, monkeypatch, anchor=dt(2027, 1, 31), used=0, limit=100, **cols):
    db, clock = env["db"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_cycle="annual", packages_used=used, packages_limit=limit,
                billing_period_start=anchor.isoformat(), **cols)
    for key, kind in (("usage_anchor:u1", "usage_anchor"), ("usage_month:u1", "usage_month")):
        db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (key, kind, anchor.isoformat()))
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", us.add_months(anchor, 12).isoformat()))
    env["stripe"].add_customer()
    env["stripe"].add_sub(SUB, status="active", cycle="annual")
    return db, env["stripe"], clock


def _count_at(clock, when, sid):
    clock.now = when
    return count("u1", sid)


def test_the_106th_package_of_month_two_is_billed_and_month_one_does_not_count(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch)
    for i in range(106):
        r = _count_at(clock, dt(2027, 2, 1) + timedelta(minutes=i), f"m1_{i}")
    assert r["pkg_eval"]["status"] == "overage" and len(fs.items) == 1   # month 1's #106
    for i in range(106):
        r = _count_at(clock, dt(2027, 3, 1) + timedelta(minutes=i), f"m2_{i}")
        if i == 0:
            assert db.user()["packages_used"] == 1                    # rolled: month 1 not counted
            assert db.user()["overage_packages_invoiced"] == 0
    assert r["pkg_eval"]["status"] == "overage" and r["pkg_eval"]["billing"] == "billed"
    assert [i["metadata"]["unit_key"] for i in fs.items] == ["overage_unit:u1:m1_105", "overage_unit:u1:m2_105"]
    assert all(i["subscription"] == SUB for i in fs.items)
    assert _marker(db, "usage_month:u1") == dt(2027, 2, 28).isoformat()


def test_several_skipped_months_are_one_rollover(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, anchor=dt(2027, 1, 15), used=80)
    _count_at(clock, dt(2027, 5, 20), "may")
    assert db.user()["packages_used"] == 1
    assert _marker(db, "usage_month:u1") == dt(2027, 5, 15).isoformat()


def test_no_rollover_inside_the_month(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=40)
    _count_at(clock, dt(2027, 2, 28, 14, 59), "late_in_month_1")
    assert db.user()["packages_used"] == 41


def test_the_rollover_racing_counts_counts_each_package_once(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=90)
    clock.now = dt(2027, 2, 28, 15, 0) + timedelta(seconds=1)

    async def five():
        await asyncio.gather(*(us.count_session_usage("u1", f"race{i}") for i in range(5)))
    run(five())
    assert db.user()["packages_used"] == 5
    assert _marker(db, "usage_month:u1") == dt(2027, 2, 28).isoformat()


def test_a_package_billed_as_the_old_months_overage_stays_in_the_old_month(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch)
    # Counted just after the boundary but billed as month 1's overage (the month
    # had not been rolled yet - e.g. an anchor learned late).
    env["sessions"].counted["edge"] = ("u1", dt(2027, 2, 28, 15, 1).isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("overage_unit:u1:edge", "overage_billed", dt(2027, 2, 28, 15, 1).isoformat()))
    _count_at(clock, dt(2027, 3, 2), "first_of_month_2")
    assert db.user()["packages_used"] == 1


def test_the_daily_job_rolls_a_quiet_account(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=57)
    clock.now = dt(2027, 3, 1, 9)
    run(ss.run_daily_payment_lifecycle())
    assert db.user()["packages_used"] == 0
    assert _marker(db, "usage_month:u1") == dt(2027, 2, 28).isoformat()


def test_a_monthly_user_never_rolls(env, monkeypatch):
    db, clock = env["db"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=40, packages_limit=100, billing_period_start=dt(2027, 1, 31).isoformat())
    _count_at(clock, dt(2027, 3, 15), "later")
    assert db.user()["packages_used"] == 41
    run(us.roll_usage_months_due())
    assert db.user()["packages_used"] == 41 and db.keys("usage_month:") == {}


def test_an_existing_annual_row_keeps_its_stored_limit(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=10, limit=1200)
    _count_at(clock, dt(2027, 3, 2), "x")
    deliver(sub_event("evt_upd", "active", metadata={"plan": "professional", "billing_cycle": "annual"}))
    assert db.user()["packages_limit"] == 1200


def test_an_annual_row_without_an_anchor_counts_months_from_its_last_payment(env, monkeypatch):
    db, clock = env["db"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_cycle="annual", packages_used=70, packages_limit=1200,
                billing_period_start=dt(2027, 1, 10).isoformat())
    _count_at(clock, dt(2027, 2, 12), "feb")
    assert db.user()["packages_used"] == 1
    assert _marker(db, "usage_month:u1") == dt(2027, 2, 10).isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# Renewals and Stripe's monthly invoices
# ═════════════════════════════════════════════════════════════════════════════
def test_a_yearly_renewal_on_a_month_boundary_still_resets_and_re_anchors(env, monkeypatch):
    anchor = dt(2027, 1, 31)
    db, fs, clock = _annual_user(env, monkeypatch, anchor=anchor)
    year = us.add_months(anchor, 12)                              # 31 Jan 2028
    _count_at(clock, year + timedelta(minutes=1), "boundary_pkg")  # rolls to month 12 first
    assert _marker(db, "usage_month:u1") == year.isoformat()
    clock.now = year + timedelta(hours=1)
    deliver(paid_event("evt_year", "in_year", created=clock.now, inv_created=year,
                       lines=[_line(year, us.add_months(year, 12))]))
    u = db.user()
    # The period starts where the renewal's own period starts (3 Nov 2026, pass 2 #2 - it was the
    # time the event was handled); the paid time is kept in last_paid.
    assert u["packages_used"] == 1 and u["billing_period_start"] == year.isoformat()
    assert _marker(db, "last_paid:u1") == clock.now.isoformat()
    assert _marker(db, "usage_anchor:u1") == year.isoformat()
    assert _marker(db, "billing_period_end:u1") == us.add_months(year, 12).isoformat()


def test_stripes_monthly_overage_invoice_never_resets_usage(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=60)
    clock.now = dt(2027, 2, 28, 16)
    evt = paid_event("evt_pii", "in_pii", created=clock.now, inv_created=clock.now,
                     lines=[{"amount": 300, "parent": {"type": "invoice_item_details"},
                             "period": {"start": int(clock.now.timestamp()), "end": int(clock.now.timestamp())}}])
    evt["data"]["object"]["billing_reason"] = "automatic_pending_invoice_item_invoice"
    deliver(evt)
    assert db.user()["packages_used"] == 60
    assert _marker(db, "billing_period_end:u1") == us.add_months(dt(2027, 1, 31), 12).isoformat()


def test_a_failed_monthly_overage_invoice_takes_the_normal_failure_path(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=60)
    clock.now = dt(2027, 2, 28, 16)
    deliver({"id": "evt_pii_fail", "type": "invoice.payment_failed", "created": int(clock.now.timestamp()),
             "data": {"object": {"id": "in_pii", "customer": CUS, "subscription": SUB,
                                 "billing_reason": "automatic_pending_invoice_item_invoice"}}})
    u = db.user()
    assert u["payment_status"] == "failed" and env["mail"].days() == [1]


def test_annual_overage_while_failing_is_held_and_billed_on_restore(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=105, payment_status="failed",
                                 payment_failed_at=dt(2027, 2, 10).isoformat(), payment_email_sent_day=1)
    r = _count_at(clock, dt(2027, 2, 11), "while_failing")
    assert r["pkg_eval"]["billing"] == "held" and fs.items == []
    fs.subs[SUB]["status"] = "active"
    clock.now = dt(2027, 2, 12)
    deliver(sub_event("evt_act", "active", created=clock.now))
    assert db.user()["payment_status"] == "ok"
    assert [i["metadata"]["unit_key"] for i in fs.items] == ["overage_unit:u1:while_failing"]


def test_an_annual_plan_end_bills_the_last_months_pending_overage_and_clears_its_months(env, monkeypatch):
    db, fs, clock = _annual_user(env, monkeypatch, used=105, payment_status="canceling")
    _count_at(clock, dt(2027, 2, 5), "last_month_extra")
    assert len(fs.items) == 1 and not fs.items[0].get("invoice")
    fs.subs[SUB]["status"] = "canceled"
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == [
        "overage_unit:u1:last_month_extra"]
    assert db.keys("usage_anchor:") == {} and db.keys("usage_month:") == {}
