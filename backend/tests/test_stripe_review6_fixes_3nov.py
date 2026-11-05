"""Final billing review, pass 6 (3 Nov 2026), fixed offline: a renewal straddling a
plan switch bills NOTHING automatically - one alert names the window for a person.
The reviewer's three shapes (annual -> monthly, Essentials -> Professional, two
switches in one period), each turned around; plus the lifecycle's stage e-mail
never going to a user a restore cleared mid-run. Reuses the fakes of
tests/test_stripe_live_readiness_2nov.py; nothing reaches Stripe or a database.
"""
from datetime import timedelta

from tests.test_stripe_live_readiness_2nov import (  # noqa: F401
    CUS, SUB, T0, _no_network, clock, count, db, deliver, env, fs, mail, run, sessions, side, sr, svc, us, webhook,
)
from tests.test_stripe_review2_fixes_2nov import _freeze_usage_clock
from tests.test_stripe_review2_fixes_3nov import _overage, _renewal_paid
from tests.test_stripe_review4_fixes_3nov import _inv_event, _units


def _assert_alert_only(env, db, fs):
    """Nothing placed, nothing billed, exactly one alert for a person."""
    assert _overage(fs) == [] and _units(db) == {}
    alerts = [a for a in env["alerts"] if "BILL BY HAND" in a[1]]
    assert len(alerts) == 1
    assert "Window: [" in alerts[0][2] and "Packages in the window:" in alerts[0][2]
    assert any(a[1] == "payment.overage_before_switch_manual" for a in env["side"]["audit"])
    return alerts[0]


def _sync_event(fs, evt, when):
    return {"id": evt, "type": "customer.subscription.updated", "created": int(when.timestamp()),
            "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                "metadata": fs.subs[SUB]["metadata"], "items": fs.subs[SUB]["items"]}}}


def test_P6_1_annual_to_monthly_switch_then_old_yearly_invoice_paid_bills_nothing(env, monkeypatch):
    """Annual Professional = 100/month. 80 packages a month for 3 months (never an
    extra). Yearly renewal failed; support moves the plan to monthly; the old yearly
    invoice is then paid. The straddle recount treats 3 annual months as ONE 110
    allowance and bills 135 packages (100 + 5% buffer = 105)."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    Y0 = T0 - timedelta(days=120)
    Y1 = Y0 + timedelta(days=365)
    db.add_user(packages_used=0, packages_limit=100, overage_rate=300, billing_cycle="annual",
                billing_period_start=Y0.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", Y1.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="past_due", cycle="annual", amount=286800)
    fs.subs[SUB]["items"]["data"][0]["price"]["recurring"]["interval_count"] = 1
    fs.subs[SUB]["items"]["data"][0]["price"]["currency"] = "usd"
    clock.now = Y0 + timedelta(hours=1)
    deliver(_inv_event("evt_f", "invoice.payment_failed", "in_y", "subscription_cycle", clock.now))
    assert db.user()["payment_status"] == "failed"
    for m in range(3):
        for i in range(80):
            clock.now = Y0 + timedelta(days=31 * m + 1, minutes=i)
            count("u1", f"m{m}_{i}")
    assert _units(db) == {}                      # never above 110 in any month: nothing owed
    S = Y0 + timedelta(days=95)
    clock.now = S
    fs.subs[SUB]["status"] = "active"
    fs.subs[SUB]["items"]["data"][0].update(current_period_start=int(S.timestamp()),
                                            current_period_end=int((S + timedelta(days=30)).timestamp()))
    fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": 19900, "currency": "usd",
                                                 "recurring": {"interval": "month", "interval_count": 1}}
    deliver(_sync_event(fs, "evt_upd", S))
    assert db.user()["billing_cycle"] == "monthly"
    clock.now = S + timedelta(days=1)
    deliver(_renewal_paid("evt_iy", "in_y", inv_created=Y0, paid_at=clock.now, start=Y0, end=Y1))
    run(us.retry_pending_overage())
    _assert_alert_only(env, db, fs)


def test_P6_2_essentials_to_professional_straddle_bills_nothing(env, monkeypatch):
    """Essentials ($2 an extra) -> Professional ($3) mid-period while the renewal is
    unpaid; the renewal is paid; the 5 extras counted on ESSENTIALS before the switch
    are billed at $3 each."""
    from tests.test_stripe_review2_fixes_3nov import A, B, C
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="essentials", packages_used=0, packages_limit=100, overage_rate=200,
                billing_period_start=A.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", B.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="past_due", plan="essentials", amount=19900)
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
    fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": 29900, "currency": "usd",
                                                 "recurring": {"interval": "month", "interval_count": 1}}
    deliver(_sync_event(fs, "evt_upd", P))
    assert db.user()["subscription_tier"] == "professional"
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=P, start=B, end=C))
    run(us.retry_pending_overage())
    _assert_alert_only(env, db, fs)


def test_P6_3_two_switches_in_one_period_bill_nothing_and_name_both_plans(env, monkeypatch):
    """Business (400 + 20) -> Professional (100 + 5) at S1 -> Business at S2, while the
    renewal is unpaid. 200 packages before S1 (inside 420), 50 between S1 and S2
    (inside 105): nothing is owed. The renewal is paid: [B, S2) = 250 is recounted
    against the allowance recorded at S2 (Professional's 105) and 145 are billed."""
    from tests.test_stripe_review2_fixes_3nov import A, B, C
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="business", packages_used=0, packages_limit=400, overage_rate=125,
                billing_period_start=A.isoformat())
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", B.isoformat()))
    fs.add_customer()
    fs.add_sub(SUB, status="past_due", plan="business", amount=44900)
    fs.subs[SUB]["items"]["data"][0].update(current_period_start=int(B.timestamp()),
                                            current_period_end=int(C.timestamp()))
    clock.now = B + timedelta(hours=1)
    deliver(_inv_event("evt_f", "invoice.payment_failed", "in_2", "subscription_cycle", clock.now))

    def _price(amount):
        fs.subs[SUB]["items"]["data"][0]["price"] = {"unit_amount": amount, "currency": "usd",
                                                     "recurring": {"interval": "month", "interval_count": 1}}
    for i in range(200):
        clock.now = B + timedelta(days=1, minutes=i)
        count("u1", f"a_{i}")
    S1 = B + timedelta(days=3)
    clock.now = S1
    fs.subs[SUB]["status"] = "active"
    _price(29900)
    deliver(_sync_event(fs, "evt_u1", S1))
    assert db.user()["subscription_tier"] == "professional"
    for i in range(50):
        clock.now = S1 + timedelta(hours=1, minutes=i)
        count("u1", f"b_{i}")
    S2 = B + timedelta(days=5)
    clock.now = S2
    _price(44900)
    deliver(_sync_event(fs, "evt_u2", S2))
    assert db.user()["subscription_tier"] == "business"
    clock.now = S2 + timedelta(hours=1)
    deliver(_renewal_paid("evt_i2", "in_2", inv_created=B, paid_at=clock.now, start=B, end=C))
    run(us.retry_pending_overage())
    _assert_alert_only(env, db, fs)


def test_P6_3b_the_alert_names_every_plan_before_the_switch(env, monkeypatch):
    test_P6_3_two_switches_in_one_period_bill_nothing_and_name_both_plans(env, monkeypatch)
    (alert,) = [a for a in env["alerts"] if "BILL BY HAND" in a[1]]
    assert "business/monthly until" in alert[2] and "professional/monthly until" in alert[2]
    assert "Packages in the window: 250" in alert[2] and "Plan now: business/monthly" in alert[2]


def test_P6_a_redelivered_straddling_renewal_alerts_once(env, monkeypatch):
    test_P6_2_essentials_to_professional_straddle_bills_nothing(env, monkeypatch)
    from tests.test_stripe_review2_fixes_3nov import B, C
    paid = _renewal_paid("evt_i2_again", "in_2", inv_created=B, paid_at=B + timedelta(days=4), start=B, end=C)
    deliver(paid)
    assert len([a for a in env["alerts"] if "BILL BY HAND" in a[1]]) == 1
    assert _overage(env["stripe"]) == []


# ═════════════════════════════════════════════════════════════════════════════
# The lifecycle's stage e-mail goes only to the failure the run read
# ═════════════════════════════════════════════════════════════════════════════
def test_P6_no_stage_email_to_a_user_restored_mid_run(env, monkeypatch):
    import services.scheduler_service as ss
    from tests.test_stripe_live_readiness_2nov import failed_user, run_lifecycle
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=0)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    real = ss._lifecycle_action

    def _restored_meanwhile(*a):
        db.lite.execute("UPDATE users SET payment_status='ok', payment_failed_at=NULL, payment_email_sent_day=0")
        return real(*a)
    monkeypatch.setattr(ss, "_lifecycle_action", _restored_meanwhile)
    run_lifecycle(clock, 0, hours=2)
    assert env["mail"].days() == []
    assert db.user()["payment_status"] == "ok" and db.user()["payment_email_sent_day"] == 0


def test_P6_control_a_still_failing_user_gets_the_stage_email(env):
    from tests.test_stripe_live_readiness_2nov import failed_user, run_lifecycle
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=0)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    run_lifecycle(clock, 0, hours=2)
    assert env["mail"].days() == [1]
