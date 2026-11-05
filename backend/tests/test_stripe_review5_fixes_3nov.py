"""Adversarial billing review, pass 5 (3 Nov 2026), fixed offline. The reviewer's
repros (each asserted the WRONG behaviour) turned around to assert the CORRECT
one, plus the edge cases each fix needs. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py; nothing reaches Stripe or a database.
"""
import json
from datetime import timedelta

import services.auth_service as auth_service
import services.scheduler_service as ss
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, failed_user, fs, mail, run,
    run_lifecycle, sessions, side, sr, svc, us, webhook,
)
from tests.test_stripe_payment_lifecycle_2nov import _Req, sub_event
from tests.test_stripe_review2_fixes_2nov import _deleted, _freeze_usage_clock, _unit
from tests.test_stripe_review2_fixes_3nov import A, B, C, _overage, _renewal_paid
from tests.test_stripe_review4_fixes_3nov import _inv_event, _units


def _midperiod_failing(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300, billing_period_start=B.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", C.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(105):
        clock.now = B + timedelta(days=1, minutes=i)
        count("u1", f"base_{i}")
    clock.now = B + timedelta(days=10)
    deliver(_inv_event("evt_pf", "invoice.payment_failed", "in_pr", "subscription_update", clock.now))
    assert db.user()["payment_status"] == "failed"
    return db, fs, clock


def _between(monkeypatch, action):
    real = auth_service.invalidate_user_cache
    fired = {"n": 0}

    async def _f(uid):
        if not fired["n"]:
            fired["n"] = 1
            await action()
        return await real(uid)
    monkeypatch.setattr(auth_service, "invalidate_user_cache", _f)


# ═════════════════════════════════════════════════════════════════════════════
# #1 - a held package is written in its count's own transaction
# ═════════════════════════════════════════════════════════════════════════════
def test_S1_a_restore_right_after_the_count_bills_the_held_unit(env, monkeypatch):
    """Repro R1a, fixed."""
    db, fs, clock = _midperiod_failing(env, monkeypatch)
    clock.now = B + timedelta(days=11)

    async def restore():
        e = _inv_event("evt_pp", "invoice.paid", "in_pr", "subscription_update", clock.now)
        await sr.stripe_webhook(_Req(json.dumps(e).encode()))
    _between(monkeypatch, restore)
    r = count("u1", "x106")
    assert r["pkg_eval"]["billing"] == "held"
    assert db.user()["payment_status"] == "ok"
    assert _units(db) == {"overage_unit:u1:x106": "overage_billed"} and len(_overage(fs)) == 1


def test_S1_a_plans_end_right_after_the_count_forgives_the_held_unit(env, monkeypatch):
    """Repro R1b, fixed: the unit is forgiven with its plan, never billed on the next."""
    db, fs, clock = _midperiod_failing(env, monkeypatch)
    clock.now = B + timedelta(days=11)

    async def end_plan():
        fs.subs[SUB]["status"] = "canceled"
        await sr.stripe_webhook(_Req(json.dumps(_deleted("evt_del")).encode()))
    _between(monkeypatch, end_plan)
    count("u1", "x106")
    assert _units(db) == {"overage_unit:u1:x106": "overage_forgiven"}
    fs.add_sub("sub_B", status="active")
    deliver(checkout_event("evt_co_B", "sub_B"))
    clock.now = C + timedelta(days=3)
    db.lite.execute("UPDATE users SET payment_status='failed', payment_failed_at=?", (clock.now.isoformat(),))
    clock.now = C + timedelta(days=4)
    deliver(sub_event("evt_upd_B", "active", sub="sub_B", created=clock.now))
    run(us.retry_pending_overage())
    assert db.user()["payment_status"] == "ok" and _overage(fs) == []


def test_S1_verify_upgrade_forgives_the_dead_plans_held_units_first(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)

    async def _no_rl(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _no_rl)
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    _unit(db, "u1", "h1", "overage_held")
    fs.add_sub("sub_new", status="active", created=10_000)
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True
    assert _units(db) == {"overage_unit:u1:h1": "overage_forgiven"} and _overage(fs) == []
    src = __import__("inspect").getsource(sr.verify_upgrade)
    assert src.index("_claim_replaced_plan_bill(") < src.index("adopt_plan_usage(")


# ═════════════════════════════════════════════════════════════════════════════
# #2 - a renewal straddling a tier switch recounts the part before it
# ═════════════════════════════════════════════════════════════════════════════
def _straddle(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300, billing_period_start=A.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", B.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="past_due", amount=29900)
    fs.subs[SUB]["items"]["data"][0].update(current_period_start=int(B.timestamp()),
                                            current_period_end=int(C.timestamp()))
    clock.now = B + timedelta(hours=1)
    deliver(_inv_event("evt_f", "invoice.payment_failed", "in_2", "subscription_cycle", clock.now))
    for i in range(110):
        clock.now = B + timedelta(days=1, minutes=i)
        count("u1", f"p_{i}")
    P = B + timedelta(days=4)
    clock.now = P
    fs.subs[SUB]["status"] = "active"
    fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": 19900, "currency": "usd",
                                                 "recurring": {"interval": "month", "interval_count": 1}}
    deliver({"id": "evt_upd", "type": "customer.subscription.updated", "created": int(P.timestamp()),
             "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                 "metadata": fs.subs[SUB]["metadata"], "items": fs.subs[SUB]["items"]}}})
    assert db.user()["subscription_tier"] == "essentials"
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=P, start=B, end=C))
    run(us.retry_pending_overage())
    return db, fs, P


def test_S2_a_renewal_straddling_a_tier_sync_bills_nothing_and_tells_a_person(env, monkeypatch, caplog):
    """Repro R2, as decided in pass 6 (the owner's final call): the window before
    the switch is never billed automatically - one alert names it for a person.
    (Pass 5 recounted it against the old allowance; that TEST was updated.)"""
    import logging
    with caplog.at_level(logging.ERROR):
        db, fs, P = _straddle(env, monkeypatch)
    assert db.user()["payment_status"] == "ok"
    assert _overage(fs) == [] and _units(db) == {}
    (alert,) = [a for a in env["alerts"] if "BILL BY HAND" in a[1]]
    assert f"[{B.isoformat()}, {P.isoformat()})" in alert[2]
    assert "Packages in the window: 110" in alert[2]
    assert "professional/monthly until " + P.isoformat() in alert[2] and "Plan now: essentials/monthly" in alert[2]
    assert ("u1", "payment.overage_before_switch_manual", "in_2") in env["side"]["audit"]
    assert any("NOT billed automatically" in r.message for r in caplog.records)


# ═════════════════════════════════════════════════════════════════════════════
# #3 - the lifecycle never locks a user a restore just cleared
# ═════════════════════════════════════════════════════════════════════════════
def test_S3_a_restore_between_the_stripe_check_and_the_stage_move_wins(env, monkeypatch):
    """Repro R3, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=1)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    real = ss._lifecycle_action

    def _after_stripe_check(*a):
        db.lite.execute("UPDATE users SET payment_status='ok', payment_failed_at=NULL, payment_email_sent_day=0")
        return real(*a)
    monkeypatch.setattr(ss, "_lifecycle_action", _after_stripe_check)
    run_lifecycle(clock, 10)
    u = db.user()
    assert (u["payment_status"], u["payment_failed_at"]) == ("ok", None)
    assert env["mail"].days() == []


def test_S3_control_a_still_failing_user_still_moves(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=1)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    run_lifecycle(clock, 10)
    assert db.user()["payment_status"] == "soft_locked"


# ═════════════════════════════════════════════════════════════════════════════
# #4 - a plan's final bill owes only packages counted before its end
# ═════════════════════════════════════════════════════════════════════════════
def test_S4_a_later_plans_package_is_not_owed_by_the_old_plans_final_bill(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(stripe_subscription_id="sub_B")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    fs.add_sub("sub_B", status="active")
    sessions = env["sessions"]
    sessions.counted["old_1"] = ("u1", (T0 - timedelta(days=2)).isoformat())     # plan A's package
    sessions.counted["new_1"] = ("u1", (T0 + timedelta(days=2)).isoformat())     # plan B's package
    for sid in ("old_1", "new_1"):
        _unit(db, "u1", sid, "overage_pending", at=T0.isoformat())
    key = svc.final_overage_key("u1", SUB, CUS, 300)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)", (key, svc.FINAL_PENDING, T0.isoformat()))
    clock.now = T0 + timedelta(days=3)
    assert run(svc.settle_final_overage(key))["state"] == "invoiced"
    (final,) = fs.invoices.values()
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == final["id"]] == \
        ["overage_unit:u1:old_1"]
    assert _units(db)["overage_unit:u1:new_1"] == "overage_pending"            # rides plan B
