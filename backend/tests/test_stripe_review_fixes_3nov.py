"""Adversarial billing review of 3 Nov 2026, fixed offline: H-A, M-A, M-B, M-C,
L-A .. L-F. The reviewer's eight repros (each asserted the WRONG behaviour) are
turned around here to assert the CORRECT one, plus the new cases each fix needs.
Reuses the fakes of tests/test_stripe_live_readiness_2nov.py: an in-memory
sqlite store behind an asyncpg-shaped pool (the handlers' own SQL runs as
written), a fake Stripe that records every call, sockets blocked. Nothing here
reaches Stripe or a database.
"""
import logging
from datetime import timedelta

import pytest
import stripe
from fastapi import HTTPException

import config.settings as settings
from config.settings import PLANS
from services.pipeline_router import is_assembly, is_clarity
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, checkout_event, clock, count, db, deliver, env, fs, mail, paid_event,
    run, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_stripe_payment_lifecycle_2nov import invoice_event
from tests.test_stripe_review2_fixes_2nov import _ending_user, _final_invoices, _freeze_usage_clock, _unit


@pytest.fixture
def no_rl(monkeypatch):
    async def _f(_uid):
        return None
    monkeypatch.setattr(sr, "check_verify_upgrade_rate_limit", _f)


def _marker(db, key):
    row = db.lite.execute("SELECT processed_at FROM processed_webhook_events WHERE event_id=?", (key,)).fetchone()
    return row[0] if row else None


def _price(fs, sid, amount, interval="month"):
    fs.subs[sid]["items"]["data"][0]["price"] = {"unit_amount": amount, "currency": "usd",
                                                 "recurring": {"interval": interval, "interval_count": 1}}


def _price_swap_event(evt_id, when, amount, interval="month", meta_plan="essentials", meta_cycle="monthly"):
    """What Stripe sends when support moves the subscription onto another
    catalogue price: the new price on the items, OUR metadata untouched."""
    return {"id": evt_id, "type": "customer.subscription.updated", "created": int(when.timestamp()),
            "data": {"object": {"id": SUB, "status": "active", "customer": CUS, "cancel_at_period_end": False,
                                "metadata": {"user_id": "u1", "plan": meta_plan, "billing_cycle": meta_cycle},
                                "items": {"data": [{"price": {"unit_amount": amount, "currency": "usd",
                                                              "recurring": {"interval": interval}},
                                                    "current_period_start": int(when.timestamp())}]}}}}


# ═════════════════════════════════════════════════════════════════════════════
# H-A - a tier change by support (a price swap) is followed, both ways
# ═════════════════════════════════════════════════════════════════════════════
def test_HA_a_support_price_swap_is_followed_up_and_back_down(env, monkeypatch):
    """Repro F1 + F1b, fixed: only the PRICE moves; Stripe keeps metadata.plan =
    essentials the whole time. Plan, forms access and overage rate follow."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="essentials", packages_limit=100, overage_rate=200,
                billing_period_start=(T0 - timedelta(days=3)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", plan="essentials", cycle="monthly", amount=19900)
    assert svc.subscription_plan(fs.subs[SUB]) == ("essentials", "monthly")
    # Up: Essentials -> Professional ($299/month).
    _price(fs, SUB, 29900)
    clock.now = T0 + timedelta(minutes=1)
    deliver(_price_swap_event("evt_up", T0, 29900))
    u = db.user()
    assert (u["subscription_tier"], u["billing_cycle"], u["overage_rate"], u["packages_limit"]) == \
        ("professional", "monthly", 300, 100)
    assert is_assembly(u["subscription_tier"])                          # forms
    assert svc.subscription_plan(fs.subs[SUB]) == ("professional", "monthly")
    assert fs.subs[SUB]["metadata"]["plan"] == "essentials"             # metadata never moved
    # Back down: Professional -> Essentials ($199/month), metadata still essentials.
    _price(fs, SUB, 19900)
    clock.now = T0 + timedelta(hours=1, minutes=1)
    deliver(_price_swap_event("evt_down", T0 + timedelta(hours=1), 19900))
    u = db.user()
    assert (u["subscription_tier"], u["overage_rate"]) == ("essentials", 200)
    assert is_clarity(u["subscription_tier"])                           # no forms
    assert svc.subscription_plan(fs.subs[SUB]) == ("essentials", "monthly")


def test_HA_a_professional_moved_down_with_professional_metadata_pays_and_gets_essentials(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="professional", billing_period_start=(T0 - timedelta(days=3)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", plan="professional", amount=29900)
    _price(fs, SUB, 19900)
    clock.now = T0 + timedelta(minutes=1)
    deliver(_price_swap_event("evt_down", T0, 19900, meta_plan="professional"))
    u = db.user()
    assert (u["subscription_tier"], u["overage_rate"]) == ("essentials", 200)


@pytest.mark.parametrize("plan,cycle", [(p, c) for p in PLANS if p != "enterprise" for c in PLANS[p]])
def test_HA_every_checkout_price_resolves_to_the_plan_it_was_sold_as(plan, cycle):
    """create-checkout's inline price_data carries the PLANS amount + interval:
    the price alone names the plan, with our metadata, without it, or against
    stale metadata naming another plan."""
    cfg = PLANS[plan][cycle]
    price = {"unit_amount": cfg["amount"], "currency": "usd", "recurring": {"interval": cfg["interval"]}}
    bare = {"items": {"data": [{"price": price}]}, "metadata": {}}
    assert svc.subscription_plan(bare) == (plan, cycle)
    tagged = {**bare, "metadata": {"plan": plan, "billing_cycle": cycle, "user_id": "u1"}}
    assert svc.subscription_plan(tagged) == (plan, cycle)
    other = "professional" if plan != "professional" else "essentials"
    stale = {**bare, "metadata": {"plan": other, "billing_cycle": "monthly"}}
    assert svc.subscription_plan(stale) == (plan, cycle)


def test_HA_metadata_decides_only_when_no_price_names_one_plan():
    meta = {"plan": "professional", "billing_cycle": "monthly"}
    unknown = {"items": {"data": [{"price": {"unit_amount": 24900, "recurring": {"interval": "month"}}}]},
               "metadata": meta}
    assert svc.subscription_plan(unknown) == ("professional", "monthly")
    # Not ours however it is priced: every 3 months, another currency, $0.
    for price in ({"unit_amount": 29900, "recurring": {"interval": "month", "interval_count": 3}},
                  {"unit_amount": 29900, "currency": "eur", "recurring": {"interval": "month"}},
                  {"unit_amount": 0, "recurring": {"interval": "month"}}):
        assert svc.plan_from_price(price) == (None, None)
        assert svc.subscription_plan({"items": {"data": [{"price": price}]}, "metadata": {}}) == (None, None)
    # Two items naming two plans: the price cannot decide, the metadata does.
    two = {"items": {"data": [{"price": {"unit_amount": 19900, "recurring": {"interval": "month"}}},
                              {"price": {"unit_amount": 29900, "recurring": {"interval": "month"}}}]},
           "metadata": meta}
    assert svc.subscription_plan(two) == ("professional", "monthly")
    # An add-on item beside the plan's own price: the plan's price decides.
    addon = {"items": {"data": [{"price": {"unit_amount": 500, "recurring": {"interval": "month"}}},
                                {"price": {"unit_amount": 19900, "recurring": {"interval": "month"}}}]},
             "metadata": meta}
    assert svc.subscription_plan(addon) == ("essentials", "monthly")
    # Enterprise metadata and no price: never a plan.
    assert svc.subscription_plan({"items": {"data": []}, "metadata": {"plan": "enterprise"}}) == (None, None)
    assert svc.subscription_plan({}) == (None, None)


def test_HA_a_cycle_swap_by_price_follows_the_price(env, monkeypatch):
    """Support moves Essentials monthly onto the Essentials ANNUAL price."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="essentials", overage_rate=200,
                billing_period_start=(T0 - timedelta(days=3)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", plan="essentials", amount=19900)
    _price(fs, SUB, 190800, interval="year")
    clock.now = T0 + timedelta(minutes=1)
    deliver(_price_swap_event("evt_cyc", T0, 190800, interval="year"))
    u = db.user()
    assert (u["subscription_tier"], u["billing_cycle"]) == ("essentials", "annual")


def test_HA_a_late_checkout_grants_what_the_subscription_bills_now(env, caplog):
    """The price changed before the delayed checkout event was handled: the
    subscription's price decides, not the session's metadata."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="professional", amount=19900)
    with caplog.at_level(logging.WARNING):
        deliver(checkout_event("evt_cs", "sub_new", plan="professional"))
    u = db.user()
    assert (u["subscription_tier"], u["overage_rate"], u["stripe_subscription_id"]) == \
        ("essentials", 200, "sub_new")
    assert any("the subscription's price decides" in r.message for r in caplog.records)


def test_HA_a_checkout_created_subscription_grants_the_plan_it_sold(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="professional", cycle="annual", amount=286800)
    deliver(checkout_event("evt_cs", "sub_new", plan="professional", cycle="annual"))
    u = db.user()
    assert (u["subscription_tier"], u["billing_cycle"], u["overage_rate"]) == ("professional", "annual", 300)


def test_HA_verify_upgrade_follows_the_price(env, no_rl):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="essentials", amount=29900)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out["upgraded"] is True and db.user()["subscription_tier"] == "professional"


# ═════════════════════════════════════════════════════════════════════════════
# M-A - a checkout handled after its subscription ended grants nothing
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("dead", ["canceled", "incomplete_expired"])
def test_MA_a_checkout_on_an_ended_subscription_grants_nothing(env, monkeypatch, caplog, dead):
    """Repro F7, fixed: refund + cancel while the completed event was delayed;
    the deletion is handled first, then the checkout."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status=dead)
    clock.now = T0 + timedelta(minutes=10)
    deliver(sub_event("evt_del", dead, etype="customer.subscription.deleted", sub="sub_new"))
    clock.now = T0 + timedelta(minutes=12)
    with caplog.at_level(logging.ERROR):
        deliver(checkout_event("evt_cs", "sub_new", created=T0))
        deliver(checkout_event("evt_cs", "sub_new", created=T0))       # re-delivery: nothing more
    u = db.user()
    assert (u["subscription_tier"], u["stripe_subscription_id"], u["packages_limit"]) == ("free", None, 0)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and "no plan granted" in r.message]
    assert len(errors) == 1
    assert env["side"]["audit"].count(("u1", "payment.checkout_subscription_not_live", "sub_new")) == 1
    assert "evt_cs" in db.keys()
    assert not fs.names("Refund.create") and not fs.names("Subscription.cancel")


def test_MA_a_live_subscription_still_grants(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active")
    deliver(checkout_event("evt_cs", "sub_new"))
    assert db.user()["subscription_tier"] == "professional"
    assert not [a for a in env["side"]["audit"] if a[1] == "payment.checkout_subscription_not_live"]


# ═════════════════════════════════════════════════════════════════════════════
# M-B - disputes: the admins are told; nothing is cancelled or locked
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def charges(monkeypatch):
    seen = []

    def retrieve(cid, **kw):
        seen.append(cid)
        return {"id": cid, "customer": CUS}
    monkeypatch.setattr(stripe.Charge, "retrieve", retrieve)
    return seen


def _dispute_event(evt_id, etype="charge.dispute.created", status="needs_response", amount=29900):
    return {"id": evt_id, "type": etype, "created": int(T0.timestamp()),
            "data": {"object": {"id": "dp_1", "object": "dispute", "amount": amount, "currency": "usd",
                                "charge": "ch_1", "payment_intent": "pi_1", "reason": "fraudulent",
                                "status": status,
                                "evidence_details": {"due_by": int((T0 + timedelta(days=7)).timestamp())}}}}


def test_MB_a_dispute_alerts_every_admin_once_and_changes_no_plan(env, charges, monkeypatch, caplog):
    db, fs = env["db"], env["stripe"]
    monkeypatch.setattr(settings, "ADMIN_EMAILS", {"owner@primble.test", "brent@primble.test"})
    db.add_user()
    before = db.user()
    with caplog.at_level(logging.ERROR):
        deliver(_dispute_event("evt_dp"))
        deliver(_dispute_event("evt_dp"))                    # re-delivery: no second e-mail
    alerts = env["alerts"]
    assert sorted(a[0] for a in alerts) == ["brent@primble.test", "owner@primble.test"]
    subject, body = alerts[0][1], alerts[0][2]
    assert "$299.00" in subject and "dp_1" in subject
    for needle in ("u1@agency.test", "$299.00", "fraudulent", "dp_1", "ch_1", "pi_1", CUS, SUB,
                   "Nothing was cancelled or locked"):
        assert needle in body
    assert chr(0x2014) not in subject + body                     # no em-dash
    assert env["side"]["audit"] == [("u1", "payment.dispute_opened", "dp_1")]
    err = [r.message for r in caplog.records if r.levelno == logging.ERROR and "DISPUTE OPENED" in r.message]
    assert len(err) == 1 and "nothing cancelled or locked automatically" in err[0]
    assert "u1@agency.test" not in err[0]                     # no e-mail address in the log
    assert db.user() == before                                # plan, status, subscription untouched
    assert not fs.names("Subscription.cancel") and not fs.names("Subscription.modify")


def test_MB_an_unreadable_charge_still_alerts_with_the_stripe_ids(env, monkeypatch):
    def down(cid, **kw):
        raise stripe.error.APIConnectionError("unreachable")
    monkeypatch.setattr(stripe.Charge, "retrieve", down)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", set())
    env["db"].add_user()
    deliver(_dispute_event("evt_dp"))
    (alert,) = env["alerts"]
    assert alert[0] == svc.BILLING_ALERT_TO                   # no admins set: the billing inbox
    assert "(not found)" in alert[2] and "dp_1" in alert[2] and "ch_1" in alert[2]
    assert env["side"]["audit"] == [("unknown", "payment.dispute_opened", "dp_1")]


@pytest.mark.parametrize("outcome,level", [("won", logging.WARNING), ("lost", logging.ERROR)])
def test_MB_a_closed_dispute_logs_its_outcome_and_changes_nothing(env, charges, caplog, outcome, level):
    db = env["db"]
    db.add_user()
    before = db.user()
    with caplog.at_level(logging.WARNING):
        deliver(_dispute_event("evt_dpc", etype="charge.dispute.closed", status=outcome))
    rec = [r for r in caplog.records if "DISPUTE CLOSED" in r.message]
    assert len(rec) == 1 and rec[0].levelno == level and outcome in rec[0].message
    assert env["side"]["audit"] == [("u1", "payment.dispute_closed", "dp_1")]
    assert env["alerts"] == [] and db.user() == before


# ═════════════════════════════════════════════════════════════════════════════
# M-C - a late checkout after verify-upgrade keeps the period's usage
# ═════════════════════════════════════════════════════════════════════════════
def _verified(env, monkeypatch, cycle="monthly"):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", cycle=cycle)
    end = us.add_months(T0, 12 if cycle == "annual" else 1)
    fs.subs["sub_new"]["items"]["data"][0].update(current_period_start=int(T0.timestamp()),
                                                  current_period_end=int(end.timestamp()))
    clock.now = T0 + timedelta(seconds=20)
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True
    return db, fs, clock


def _overage(fs):
    return [i for i in fs.items if (i.get("metadata") or {}).get("type") == "overage_package"]


def test_MC_a_late_checkout_keeps_the_usage_verify_upgrade_counted(env, monkeypatch, no_rl):
    """Repro F2, fixed."""
    db, fs, clock = _verified(env, monkeypatch)
    for i in range(110):
        clock.now = T0 + timedelta(hours=1, minutes=i)
        count("u1", f"pkg_{i}")
    assert db.user()["packages_used"] == 110 and len(_overage(fs)) == 5
    bps = db.user()["billing_period_start"]
    clock.now = T0 + timedelta(hours=4)
    deliver(checkout_event("evt_cs_late", "sub_new", invoice="in_sub_new", created=T0))
    u = db.user()
    assert (u["packages_used"], u["billing_period_start"], u["subscription_tier"]) == (110, bps, "professional")
    for i in range(110, 220):
        clock.now = T0 + timedelta(hours=5, minutes=i)
        count("u1", f"pkg_{i}")
    assert len(_overage(fs)) == 115                           # 220 in one period: 115 extras
    assert ("u1", "payment.subscription_created", "sub_new") in env["side"]["audit"]


def test_MC_a_late_checkout_never_clears_a_real_failure(env, monkeypatch, no_rl):
    db, fs, clock = _verified(env, monkeypatch)
    clock.now = T0 + timedelta(hours=1)
    deliver(invoice_event("evt_fail", sub="sub_new", created=clock.now))
    assert db.user()["payment_status"] == "failed"
    clock.now = T0 + timedelta(hours=2)
    deliver(checkout_event("evt_cs_late", "sub_new", created=T0))
    u = db.user()
    assert u["payment_status"] == "failed" and u["payment_failed_at"] is not None


def test_MC_a_late_annual_checkout_keeps_the_usage_months(env, monkeypatch, no_rl):
    db, fs, clock = _verified(env, monkeypatch, cycle="annual")
    anchor, month = _marker(db, "usage_anchor:u1"), _marker(db, "usage_month:u1")
    assert anchor is not None
    for i in range(3):
        clock.now = T0 + timedelta(days=40, minutes=i)       # month 1 of the year
        count("u1", f"pkg_{i}")
    used = db.user()["packages_used"]
    month_now = _marker(db, "usage_month:u1")
    deliver(checkout_event("evt_cs_late", "sub_new", cycle="annual", created=T0))
    assert (_marker(db, "usage_anchor:u1"), _marker(db, "usage_month:u1")) == (anchor, month_now)
    assert db.user()["packages_used"] == used and month_now != month


def test_MC_verify_upgrade_landing_mid_checkout_is_no_duplicate(env, monkeypatch):
    """verify-upgrade stores the subscription between the checkout handler's
    read and its compare-and-set: the same plan, never refunded as a second one."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", latest_invoice="in_new")
    fs.invoice_payments["in_new"] = ["pi_new"]
    original = sr._subscription_state

    async def racing(sub_id, event_id, **kw):
        out = await original(sub_id, event_id, **kw)
        db.lite.execute("UPDATE users SET stripe_subscription_id='sub_new', subscription_tier='professional',"
                        " packages_limit=100, packages_used=7 WHERE id='u1'")
        return out
    monkeypatch.setattr(sr, "_subscription_state", racing)
    deliver(checkout_event("evt_cs", "sub_new", invoice="in_new"))
    u = db.user()
    assert (u["stripe_subscription_id"], u["packages_used"]) == ("sub_new", 7)
    assert not fs.names("Refund.create") and not fs.names("Subscription.cancel")
    assert db.keys(svc.DUP_PREFIX) == {}


# ═════════════════════════════════════════════════════════════════════════════
# L-A - the deleted-account branch never refunds a plan delete-account ended
# ═════════════════════════════════════════════════════════════════════════════
def test_LA_a_late_checkout_after_delete_refunds_nothing(env, monkeypatch, no_rl):
    """Repro F5, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", latest_invoice="in_new")
    fs.invoice_payments["in_new"] = ["pi_new"]
    clock.now = T0 + timedelta(seconds=20)
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True
    for i in range(80):
        clock.now = T0 + timedelta(hours=1, minutes=i)
        count("u1", f"pkg_{i}")
    # delete-account cancels the plan, claims the plan's final bill under the subscription
    # the row carried (auth_routes.delete_account), then deletes the row.
    fs.subs["sub_new"]["status"] = "canceled"
    u = db.user()
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    (svc.final_overage_key("u1", "sub_new", CUS, u["overage_rate"]), svc.FINAL_NONE,
                     clock.now.isoformat()))
    db.lite.execute("DELETE FROM users WHERE id='u1'")
    clock.now = T0 + timedelta(hours=3)
    deliver(checkout_event("evt_cs_late", "sub_new", invoice="in_new", created=T0))
    assert fs.refunds == [] and not fs.names("Refund.create")
    assert ("u1", "payment.deleted_account_checkout_not_refunded", "sub_new") in env["side"]["audit"]
    assert "evt_cs_late" in db.keys() and db.keys(svc.DUP_PREFIX) == {}
    # The daily job finds nothing to refund later either.
    clock.now = T0 + timedelta(days=1)
    run(svc.retry_unsettled_duplicates())
    assert fs.refunds == []


def test_LA_stripe_unreachable_on_the_deleted_account_check_is_a_503(env):
    db, fs = env["db"], env["stripe"]
    fs.add_customer()
    fs.add_sub("sub_orphan", status="active")
    fs.fail.add("Subscription.retrieve")
    with pytest.raises(HTTPException) as ei:
        deliver(checkout_event("evt_o", "sub_orphan", invoice="in_o"))
    assert ei.value.status_code == 503
    assert db.keys() == {} and not fs.names("Refund.create")


# ═════════════════════════════════════════════════════════════════════════════
# L-B - an enterprise account's old Stripe plan ending never drops it to free
# ═════════════════════════════════════════════════════════════════════════════
def test_LB_cancelling_an_enterprise_accounts_old_subscription_keeps_enterprise(env):
    """Repro F3, fixed - the final overage is still claimed and settled."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="enterprise", packages_limit=5000, packages_used=42,
                payment_status="failed", payment_failed_at=T0.isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    u = db.user()
    assert (u["subscription_tier"], u["packages_limit"], u["packages_used"]) == ("enterprise", 5000, 42)
    assert u["stripe_subscription_id"] is None
    assert (u["payment_status"], u["payment_failed_at"]) == ("ok", None)   # no Stripe plan left to lock it
    assert len(db.keys("final_overage:")) == 1
    assert ("u1", "payment.subscription_cancelled", SUB) in env["side"]["audit"]


def test_LB_a_paid_tier_is_still_downgraded(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="professional")
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    u = db.user()
    assert (u["subscription_tier"], u["packages_limit"], u["stripe_subscription_id"]) == ("free", 0, None)


# ═════════════════════════════════════════════════════════════════════════════
# L-C - a payment is stamped with Stripe's time, never ours
# ═════════════════════════════════════════════════════════════════════════════
def test_LC_a_late_old_success_never_hides_a_newer_failure(env, monkeypatch):
    """Repro F4, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    t_old_paid = T0 - timedelta(hours=6)
    clock.now = T0 + timedelta(hours=2)
    old = paid_event("evt_old_paid", "in_old", created=t_old_paid, inv_created=t_old_paid - timedelta(days=1))
    old["data"]["object"]["billing_reason"] = "manual"
    deliver(old)
    assert _marker(db, "last_paid:u1") == t_old_paid.isoformat()
    fs.subs[SUB]["status"] = "past_due"
    clock.now = T0 + timedelta(hours=2, minutes=5)
    deliver(invoice_event("evt_fail", created=T0))
    deliver(sub_event("evt_pd", "past_due", created=T0))
    u = db.user()
    assert u["payment_status"] == "failed" and u["payment_failed_at"] == T0.isoformat()
    assert env["mail"].days() == [1]


def test_LC_the_invoices_paid_at_beats_the_event_time(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 + timedelta(hours=4)
    evt = paid_event("evt_p", "in_p", created=T0 + timedelta(hours=3), inv_created=T0 - timedelta(days=2))
    evt["data"]["object"].update(billing_reason="manual",
                                 status_transitions={"paid_at": int((T0 + timedelta(hours=1)).timestamp())})
    deliver(evt)
    assert _marker(db, "last_paid:u1") == (T0 + timedelta(hours=1)).isoformat()
    deliver(invoice_event("evt_fail", created=T0 + timedelta(hours=2)))   # after the payment: real
    assert db.user()["payment_status"] == "failed"


def test_LC_last_paid_never_moves_back(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 + timedelta(hours=6)
    for evt_id, inv, paid in (("evt_new", "in_new", T0 + timedelta(hours=5)),
                              ("evt_old", "in_old", T0 + timedelta(hours=1))):   # older one handled last
        evt = paid_event(evt_id, inv, created=paid, inv_created=paid - timedelta(hours=1))
        evt["data"]["object"]["billing_reason"] = "manual"
        deliver(evt)
    assert _marker(db, "last_paid:u1") == (T0 + timedelta(hours=5)).isoformat()
    deliver(invoice_event("evt_stale_fail", created=T0 + timedelta(hours=3)))   # before the newest payment
    assert db.user()["payment_status"] == "ok"


def test_LC_a_renewal_keeps_its_paid_time_and_starts_at_its_own_period(env, monkeypatch):
    """L-C as revised by pass 2 #2: last_paid takes Stripe's paid time; the period
    starts at the invoice's own period start (here its creation - no plan line)."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 + timedelta(hours=2)
    deliver(paid_event("evt_ren", "in_ren", created=T0 + timedelta(hours=1), inv_created=T0))
    assert db.user()["billing_period_start"] == T0.isoformat()
    assert _marker(db, "last_paid:u1") == (T0 + timedelta(hours=1)).isoformat()


def test_LC_an_event_dated_in_the_future_is_stamped_now(env):
    now = T0
    obj = {"status_transitions": {"paid_at": int((T0 + timedelta(hours=1)).timestamp())}}
    assert sr._paid_time(obj, T0 + timedelta(hours=1), now) == now
    assert sr._paid_time({}, None, now) == now
    assert sr._paid_time({}, T0 - timedelta(minutes=5), now) == T0 - timedelta(minutes=5)


# ═════════════════════════════════════════════════════════════════════════════
# L-D - the cancel route never lifts a failure and never repoints the plan
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("stage", ["failed", "soft_locked", "suspended", "archived"])
def test_LD_cancel_never_lifts_a_failure_stage(env, stage):
    """Repro F6, fixed (suspended), and every other failure stage."""
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status=stage, payment_failed_at=(T0 - timedelta(days=22)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    out = run(sr.cancel_subscription(current_user=db.user()))
    assert out["success"]
    u = db.user()
    assert (u["payment_status"], u["stripe_subscription_id"]) == (stage, SUB)
    assert fs.subs[SUB]["cancel_at_period_end"] is True


def test_LD_cancel_marks_a_paying_user_canceling_and_keeps_the_stored_plan(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active")
    run(sr.cancel_subscription(current_user=db.user()))
    u = db.user()
    assert (u["payment_status"], u["stripe_subscription_id"]) == ("canceling", SUB)


def test_LD_cancel_never_replaces_the_stored_subscription_with_another(env):
    """The row's plan is not among the subscriptions just set to end: the stored
    id stays, and the row's plan is not called "canceling"."""
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id="sub_stored")
    fs.add_customer()
    fs.add_sub("sub_stored", status="past_due")               # not listed as active
    fs.add_sub("sub_dup", status="active")
    run(sr.cancel_subscription(current_user=db.user()))
    u = db.user()
    assert (u["stripe_subscription_id"], u["payment_status"]) == ("sub_stored", "ok")


def test_LD_cancel_fills_an_empty_stored_subscription(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id=None)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    run(sr.cancel_subscription(current_user=db.user()))
    u = db.user()
    assert (u["stripe_subscription_id"], u["payment_status"]) == (SUB, "canceling")


# ═════════════════════════════════════════════════════════════════════════════
# L-E - the final bill reads an item's plan from parent.subscription_details too
# ═════════════════════════════════════════════════════════════════════════════
def test_LE_item_subscription_reads_every_shape():
    assert svc.item_subscription({"subscription": "sub_a"}) == "sub_a"
    assert svc.item_subscription({"subscription": {"id": "sub_a"}}) == "sub_a"
    dahlia = {"parent": {"type": "subscription_details", "subscription_details": {"subscription": "sub_b"}}}
    assert svc.item_subscription(dahlia) == "sub_b"
    assert svc.item_subscription({"subscription": None, **dahlia}) == "sub_b"
    assert svc.item_subscription({"parent": None}) is None
    assert svc.item_subscription({}) is None


def _dahlia_item(fs, uid, sid, subscription):
    fs.items.append({"id": f"ii_{uid}_{sid}", "customer": CUS, "amount": 300,
                     "parent": {"type": "subscription_details",
                                "subscription_details": {"subscription": subscription}},
                     "metadata": {"unit_key": f"overage_unit:{uid}:{sid}", "user_id": uid}})


def test_LE_a_final_bill_takes_only_its_own_plans_dahlia_items(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _dahlia_item(fs, "u1", "p1", SUB)
    _unit(db, "u1", "q1", "overage_billed")
    _dahlia_item(fs, "u1", "q1", "sub_other_plan")
    deliver(sub_event("evt_del", "canceled", etype="customer.subscription.deleted"))
    (inv,) = _final_invoices(fs)
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == ["overage_unit:u1:p1"]
    assert "ii_u1_q1" in {i["id"] for i in fs.items if not i.get("invoice")}     # the other plan's item stays
    assert "ii_u1_p1" not in {i["id"] for i in fs.items}                         # its pending copy went


# ═════════════════════════════════════════════════════════════════════════════
# L-F - verify-upgrade grants only a paid (or nothing-due) first invoice
# ═════════════════════════════════════════════════════════════════════════════
def _latest_invoice(monkeypatch, fs, inv, expand_ignored=False):
    def retrieve(sid, **kw):
        s = fs.sub_retrieve(sid, **({} if expand_ignored else kw))
        if not expand_ignored and "latest_invoice" in (kw.get("expand") or []):
            s["latest_invoice"] = inv
        elif expand_ignored:
            s["latest_invoice"] = inv
        return s
    monkeypatch.setattr(stripe.Subscription, "retrieve", retrieve)


def _free_with_sub(env, status="active"):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="free", stripe_subscription_id=None, packages_limit=0)
    fs.add_customer()
    fs.add_sub("sub_new", status=status)
    return db, fs


def test_LF_an_unpaid_first_invoice_grants_nothing(env, monkeypatch, no_rl):
    db, fs = _free_with_sub(env)
    _latest_invoice(monkeypatch, fs, {"id": "in_new", "status": "open", "amount_due": 29900})
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "free", "upgraded": False, "reason": "payment_pending"}
    u = db.user()
    assert (u["subscription_tier"], u["stripe_subscription_id"]) == ("free", None)


@pytest.mark.parametrize("inv", [{"id": "in_t", "status": "paid", "amount_due": 0},
                                 {"id": "in_z", "status": "open", "amount_due": 0},
                                 None])
def test_LF_nothing_due_still_grants(env, monkeypatch, no_rl, inv):
    db, fs = _free_with_sub(env, status="trialing")
    _latest_invoice(monkeypatch, fs, inv)
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True


def test_LF_a_card_payment_grants_as_before(env, no_rl):
    db, fs = _free_with_sub(env)
    out = run(sr.verify_upgrade(current_user=db.user()))
    assert out == {"subscription_tier": "professional", "upgraded": True, "reason": "stripe_verified"}
    assert ("Subscription.retrieve", ("sub_new",), {"expand": ["latest_invoice"]}) in fs.calls


def test_LF_an_unexpanded_latest_invoice_is_read_by_id(env, monkeypatch, no_rl):
    db, fs = _free_with_sub(env)
    fs.invoices["in_s"] = {"id": "in_s", "status": "open", "amount_due": 29900, "metadata": {}}
    _latest_invoice(monkeypatch, fs, "in_s", expand_ignored=True)
    assert run(sr.verify_upgrade(current_user=db.user()))["reason"] == "payment_pending"
    fs.invoices["in_s"]["status"] = "paid"
    assert run(sr.verify_upgrade(current_user=db.user()))["upgraded"] is True
