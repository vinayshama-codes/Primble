"""Third billing review, fixed offline (2 Nov 2026): Q1-Q8, plus the reviewer's
three reproductions (truncated invoice lines, a stale period end, a long free
lite run) turned around to assert the CORRECT behaviour. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py; nothing leaves the process.
"""
import ast
import asyncio
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import services.generation_state as gs
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, failed_user, fs, mail,
    paid_event, run, run_lifecycle, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_stripe_review2_fixes_2nov import (
    _age_reservations, _deleted, _ending_user, _final_invoices, _free, _freeze_usage_clock, _line,
    _pending_item, _unit,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _sub_period(fs, sid, start, end):
    fs.subs[sid]["items"]["data"][0].update(current_period_start=int(start.timestamp()),
                                            current_period_end=int(end.timestamp()))


def _period_end_of(db, uid="u1"):
    return db.keys("billing_period_end:").get(f"billing_period_end:{uid}") and db.lite.execute(
        "SELECT processed_at FROM processed_webhook_events WHERE event_id=?", (f"billing_period_end:{uid}",)
    ).fetchone()[0]


# ═════════════════════════════════════════════════════════════════════════════
# Q1 - a renewal is the renewal however many overage lines come first
# ═════════════════════════════════════════════════════════════════════════════
def _ten_item_lines():
    stamp = int((T0 - timedelta(days=3)).timestamp())
    return [{"object": "line_item", "amount": 300, "parent": {"type": "invoice_item_details"},
             "period": {"start": stamp, "end": stamp}} for _ in range(10)]


def test_Q1_a_renewal_whose_plan_line_is_on_page_two_still_resets(env, monkeypatch):
    """The reviewer's truncated-lines repro, fixed: usage resets, the new
    period end comes from the subscription, and the first package of the new
    period is not overage."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=125, packages_limit=100,
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _sub_period(fs, SUB, T0, T0 + timedelta(days=30))
    clock.now = T0 + timedelta(minutes=5)
    evt = paid_event("evt_ren", "in_ren", created=clock.now, inv_created=T0, lines=_ten_item_lines())
    evt["data"]["object"]["lines"]["has_more"] = True
    deliver(evt)
    assert db.user()["packages_used"] == 0
    assert _period_end_of(db) == (T0 + timedelta(days=30)).isoformat()
    clock.now = T0 + timedelta(days=1)
    r = count("u1", "first_pkg_of_new_period")
    assert r["pkg_eval"]["status"] == "normal" and fs.items == []


def test_Q1_a_complete_page_with_no_plan_line_is_still_not_a_renewal(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=90, billing_period_start=(T0 - timedelta(days=10)).isoformat())
    clock.now = T0
    deliver(paid_event("evt_m", "in_m", created=T0, inv_created=T0, lines=_ten_item_lines()[:1]))
    assert db.user()["packages_used"] == 90


def test_Q1_a_very_late_event_never_takes_the_next_period(env):
    """The subscription has already moved on to the period AFTER this invoice's:
    its period is not used for this invoice."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=10, billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _sub_period(fs, SUB, T0 + timedelta(days=30), T0 + timedelta(days=60))
    clock.now = T0 + timedelta(days=31)
    evt = paid_event("evt_late", "in_late", created=clock.now, inv_created=T0, lines=_ten_item_lines())
    evt["data"]["object"]["lines"]["has_more"] = True
    deliver(evt)
    assert _period_end_of(db) is None


def test_Q1_the_renewal_test_reads_billing_reason_and_trusts_only_a_complete_page():
    src = (ROOT / "routes/stripe_routes.py").read_text()
    body = src[src.index("async def _handle_invoice_paid("):src.index("async def _handle_payment_failed(")]
    assert 'obj.get("billing_reason") in _PERIOD_REASONS' in body
    assert 'not lines.get("has_more")' in body


# ═════════════════════════════════════════════════════════════════════════════
# Q2 - the period end never goes stale
# ═════════════════════════════════════════════════════════════════════════════
def test_Q2_a_resubscriber_whose_first_invoice_comes_first_is_billed(env, monkeypatch):
    """The reviewer's stale-period-end repro, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_used=0, packages_limit=0)
    fs.add_customer()
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", (T0 - timedelta(days=90)).isoformat()))
    NEW = "sub_new"
    fs.add_sub(NEW, status="active")
    clock.now = T0
    first = paid_event("evt_first_inv", "in_first", sub=NEW, created=T0, inv_created=T0,
                       lines=[_line(T0, T0 + timedelta(days=30))])
    first["data"]["object"]["billing_reason"] = "subscription_create"
    deliver(first)                                   # before the checkout event
    assert db.keys("sub_period_end:") == {"sub_period_end:sub_new": "sub_period_end"}
    deliver(checkout_event("evt_co", NEW, created=T0))
    assert _period_end_of(db) == (T0 + timedelta(days=30)).isoformat()
    u = db.user()
    lim = int(u["packages_limit"])
    db.lite.execute("UPDATE users SET packages_used=? WHERE id='u1'", (lim + int(lim * 0.1) + 5,))
    clock.now = T0 + timedelta(days=10)
    r = count("u1", "over1")
    assert r["pkg_eval"]["status"] == "overage" and r["pkg_eval"]["billing"] == "billed"
    assert len(fs.items) == 1


def test_Q2_a_checkout_records_the_period_from_the_subscription_itself(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_new", status="active")
    _sub_period(fs, "sub_new", T0, T0 + timedelta(days=365))
    deliver(checkout_event("evt_co", "sub_new", cycle="annual"))
    assert _period_end_of(db) == (T0 + timedelta(days=365)).isoformat()


def test_Q2_a_new_checkout_with_no_period_known_clears_the_stale_one(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="free", stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub("sub_new", status="active")
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", (T0 - timedelta(days=90)).isoformat()))
    deliver(checkout_event("evt_co", "sub_new"))
    assert _period_end_of(db) is None
    lim = int(db.user()["packages_limit"])
    db.lite.execute("UPDATE users SET packages_used=? WHERE id='u1'", (lim + 50,))
    clock.now = T0 + timedelta(days=3)
    assert count("u1", "over")["pkg_eval"]["billing"] == "billed"


def test_Q2_a_plan_end_clears_the_period_end(env):
    db, fs = _ending_user(env)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", T0.isoformat()))
    deliver(_deleted())
    assert _period_end_of(db) is None


# ═════════════════════════════════════════════════════════════════════════════
# Q3 - a long free run is live; saved forms are never abandoned
# ═════════════════════════════════════════════════════════════════════════════
def test_Q3_a_reservation_released_meanwhile_still_counts_its_package(env):
    """The reviewer's long-lite-run repro, fixed: if a reservation is taken for
    dead and released, its package still counts when it finishes - two packages
    generated = two counted."""
    db, sessions = env["db"], env["sessions"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    _age_reservations(db)
    assert run(us.free_packages_in_use("u1", "pkg2")) == 0
    assert run(us.reserve_free_package("u1", "pkg2")) is True
    count("u1", "pkg1", reserved_free=True)
    count("u1", "pkg2", reserved_free=True)
    assert db.user()["downloads_used"] == 2


def test_Q3_a_beating_reservation_is_never_taken_for_dead(env, monkeypatch):
    db = env["db"]
    _free(db)
    monkeypatch.setattr(gs, "HEARTBEAT_SECONDS", 0.01)
    assert run(us.reserve_free_package("u1", "pkg1"))
    _age_reservations(db)                                  # it has run past five minutes

    async def long_run():
        async with us.reservation_heartbeat("u1", "pkg1"):
            await asyncio.sleep(0.05)
            return await us.reserve_free_package("u1", "pkg2")
    assert run(long_run()) is False                         # pkg1 still holds the one package
    assert db.keys("free_reservation:")["free_reservation:u1:pkg1"] == "free_reserved"
    assert db.user()["downloads_used"] == 1


def test_Q3_saved_but_uncounted_forms_are_never_abandoned(env):
    db, sessions = env["db"], env["sessions"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    sessions.saved.add("pkg1")                              # forms saved, the count not reached yet
    _age_reservations(db)
    assert run(us.reserve_free_package("u1", "pkg2")) is False
    assert db.keys("free_reservation:")["free_reservation:u1:pkg1"] == "free_reserved"


def test_Q3_both_free_routes_beat_their_reservation():
    src = (ROOT / "routes/form_routes.py").read_text()
    tree = ast.parse(src)
    for name in ("select_forms_bulk", "lite_generate_internal"):
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        body = ast.get_source_segment(src, fn)
        assert "reservation_heartbeat(" in body and "_res_beat.__aexit__(" in body


# ═════════════════════════════════════════════════════════════════════════════
# Q4 - the final bill never bills a unit a renewal already carried
# ═════════════════════════════════════════════════════════════════════════════
def test_Q4_a_unit_already_on_a_paid_invoice_is_not_billed_again(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p_swept", "overage_pending")            # the create timed out after succeeding
    fs.items.append({"id": "ii_swept", "customer": CUS, "amount": 300, "invoice": "in_renewal_paid",
                     "metadata": {"unit_key": "overage_unit:u1:p_swept"}})
    _unit(db, "u1", "p_new", "overage_pending")              # never reached Stripe
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == [
        "overage_unit:u1:p_new"]


# ═════════════════════════════════════════════════════════════════════════════
# Q5 - the ended plan is judged by the stored subscription
# ═════════════════════════════════════════════════════════════════════════════
def test_Q5_the_deletion_asks_stripe_nothing_about_other_subscriptions(env):
    db, fs = _ending_user(env)
    fs.add_sub("sub_dup", status="active")
    fs.calls.clear()
    deliver(_deleted())
    assert not fs.names("Subscription.list")
    assert db.user()["subscription_tier"] == "free"


# ═════════════════════════════════════════════════════════════════════════════
# Q6 - a refund already made is never made again
# ═════════════════════════════════════════════════════════════════════════════
def test_Q6_a_retry_after_a_crash_and_expired_keys_never_refunds_twice(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active", latest_invoice="in_dup")
    fs.invoice_payments["in_dup"] = ["pi_dup"]
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert len(fs.refunds) == 1
    # the process died after the refund, before recording it; 24 h+ later
    db.lite.execute("UPDATE processed_webhook_events SET event_type=?, processed_at=?"
                    " WHERE event_id LIKE 'duplicate_checkout:%'",
                    (svc.DUP_PENDING, "2000-01-01T00:00:00+00:00"))
    fs.idem.clear()
    assert run(svc.retry_unsettled_duplicates()) == 1
    assert len(fs.refunds) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Q7 - a final bill a person must handle sends the one alert e-mail
# ═════════════════════════════════════════════════════════════════════════════
def test_Q7_a_refused_final_bill_alerts_once(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.refuse = {"Invoice.create"}
    deliver(_deleted())
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_MANUAL]
    (alert,) = env["alerts"]
    assert alert[0] == "info@primble.com" and "MANUAL BILLING NEEDED" in alert[1]


def test_Q7_a_declined_final_charge_alerts_once(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.fail.add("Invoice.pay:decline")
    deliver(_deleted())
    (alert,) = env["alerts"]
    assert alert[0] == "info@primble.com" and "FAILED" in alert[1]
    (key,) = db.keys("final_overage:")
    db.lite.execute("UPDATE processed_webhook_events SET event_type=? WHERE event_id=?", (svc.FINAL_PENDING, key))
    run(svc.settle_final_overage(key))
    assert len(env["alerts"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Q8 - nothing re-syncs an enterprise plan
# ═════════════════════════════════════════════════════════════════════════════
def test_Q8_a_subscription_update_never_overwrites_enterprise(env):
    db = env["db"]
    db.add_user(subscription_tier="enterprise", packages_limit=5000)       # stored, no longer live sub
    deliver(sub_event("evt_upd", "active", metadata={"plan": "essentials", "billing_cycle": "monthly"}))
    u = db.user()
    assert u["subscription_tier"] == "enterprise" and u["packages_limit"] == 5000


def test_Q8_verify_upgrade_never_touches_enterprise(env, monkeypatch):
    db, fs = env["db"], env["stripe"]

    async def _no_rl(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _no_rl)
    db.add_user(subscription_tier="enterprise", packages_limit=5000)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="essentials")
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "enterprise", "upgraded": False, "reason": "enterprise"}
    assert fs.calls == [] and db.user()["subscription_tier"] == "enterprise"
