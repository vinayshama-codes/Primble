"""Final money-path review, fixed offline (2 Nov 2026): F1-F4 and the
reviewer's repros A, B, C (with their two controls), turned around to assert
the CORRECT behaviour. Reuses the fakes of tests/test_stripe_live_readiness_2nov.py.
"""
from datetime import timedelta

import pytest
import stripe
from fastapi import HTTPException

from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _no_network, clock, count, db, deliver, env, fs, mail, paid_event, run,
    run_lifecycle, sessions, side, sr, ss, sub_event, svc, us, webhook,
)
from tests.test_stripe_review2_fixes_2nov import (
    _deleted, _ending_user, _final_invoices, _freeze_usage_clock, _line, _pending_item, _unit,
)


def _ten_overage_lines(at):
    stamp = int(at.timestamp())
    return [{"object": "line_item", "amount": 300, "parent": {"type": "invoice_item_details"},
             "period": {"start": stamp, "end": stamp}} for _ in range(10)]


def _preload_counted(sessions, n, at, uid="u1", prefix="old"):
    for i in range(n):
        sessions.counted[f"{prefix}{i:04d}"] = (uid, at.isoformat())


def _overage_items(fs, prefix="overage_unit:u1:"):
    return [i for i in fs.items if (i.get("metadata") or {}).get("unit_key", "").startswith(prefix)]


# ═════════════════════════════════════════════════════════════════════════════
# F1 (A) - a heavy renewal never loses the next period's overage
# ═════════════════════════════════════════════════════════════════════════════
def _heavy_renewal_user(env, monkeypatch, with_period=True):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=120, packages_limit=100,
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    if with_period:
        fs.subs[SUB]["items"]["data"][0].update(current_period_start=int(T0.timestamp()),
                                                current_period_end=int((T0 + timedelta(days=30)).timestamp()))
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("billing_period_end:u1", "billing_period_end", T0.isoformat()))
    clock.now = T0 + timedelta(minutes=5)
    evt = paid_event("evt_ren1", "in_ren1", created=clock.now, inv_created=T0,
                     lines=_ten_overage_lines(T0 - timedelta(days=3)))
    evt["data"]["object"]["lines"]["has_more"] = True
    return db, fs, clock, evt


def _use_and_renew(env, db, fs, clock):
    for i in range(115):
        clock.now = T0 + timedelta(days=1, minutes=i)
        count("u1", f"p{i:04d}")
    clock.now = T0 + timedelta(days=30, minutes=5)
    deliver(paid_event("evt_ren2", "in_ren2", created=clock.now, inv_created=T0 + timedelta(days=30),
                       lines=[_line(T0 + timedelta(days=30), T0 + timedelta(days=60))]))
    run_lifecycle(clock, 31)


def test_F1_A_a_transient_at_a_heavy_renewal_is_a_503_and_nothing_is_lost(env, monkeypatch):
    """Repro A, fixed: the transient answers 503 before anything is claimed;
    Stripe re-sends; the period's 10 overage packages are all billed."""
    db, fs, clock, evt = _heavy_renewal_user(env, monkeypatch)
    fs.fail = {"Subscription.retrieve"}
    with pytest.raises(HTTPException) as ei:
        deliver(evt)
    assert ei.value.status_code == 503
    assert db.keys() == {"billing_period_end:u1": "billing_period_end"}     # nothing claimed or spent
    assert db.user()["packages_used"] == 120
    fs.fail = set()
    deliver(evt)                                                            # Stripe re-sends
    assert db.user()["packages_used"] == 0
    _use_and_renew(env, db, fs, clock)
    assert len(_overage_items(fs, "overage_unit:u1:p")) == 10


def test_F1_A_control_no_transient_bills_ten(env, monkeypatch):
    db, fs, clock, evt = _heavy_renewal_user(env, monkeypatch)
    deliver(evt)
    _use_and_renew(env, db, fs, clock)
    assert len(_overage_items(fs, "overage_unit:u1:p")) == 10


def test_F1_A_a_renewal_with_no_period_known_clears_the_stale_end(env, monkeypatch):
    """No plan line on the page and no period on the subscription: the stale
    end is cleared, so the new period's overage bills in-period."""
    db, fs, clock, evt = _heavy_renewal_user(env, monkeypatch, with_period=False)
    deliver(evt)
    assert db.keys("billing_period_end:") == {}
    _use_and_renew(env, db, fs, clock)
    assert len(_overage_items(fs, "overage_unit:u1:p")) == 10


# ═════════════════════════════════════════════════════════════════════════════
# F1 (B) - overage used while failing is billed when the user is restored
# ═════════════════════════════════════════════════════════════════════════════
def _recovering_user(env, monkeypatch, sub_status="active"):
    db, fs, clock, sessions = env["db"], env["stripe"], env["clock"], env["sessions"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=105, packages_limit=100, payment_status="failed",
                payment_failed_at=(T0 + timedelta(minutes=1)).isoformat(), payment_email_sent_day=1,
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status=sub_status)
    _preload_counted(sessions, 105, T0 + timedelta(minutes=30))
    for i in range(5):
        clock.now = T0 + timedelta(days=1, hours=i)
        assert count("u1", f"f{i}")["pkg_eval"]["billing"] == "not_billable"
    assert fs.items == []
    clock.now = T0 + timedelta(days=4)
    return db, fs, clock


def _paid(clock, evt_id="evt_paid", etype="invoice.paid", seconds=0):
    return paid_event(evt_id, "in_ren", etype=etype, created=clock.now + timedelta(seconds=seconds),
                      inv_created=T0, lines=[_line(T0, T0 + timedelta(days=30))])


def test_F1_B_a_transient_at_the_recovering_renewal_is_a_503_and_the_twin_bills(env, monkeypatch):
    """Repro B, fixed."""
    db, fs, clock = _recovering_user(env, monkeypatch)
    fs.fail = {"Subscription.retrieve"}
    with pytest.raises(HTTPException) as ei:
        deliver(_paid(clock))
    assert ei.value.status_code == 503 and db.keys("invoice_reset:") == {}
    fs.fail = set()
    deliver(_paid(clock, "evt_succ", "invoice.payment_succeeded", seconds=2))
    run_lifecycle(clock, 5)
    assert db.user()["payment_status"] == "ok"
    assert len(fs.items) == 5


def test_F1_B_control_no_transient_bills_five(env, monkeypatch):
    db, fs, clock = _recovering_user(env, monkeypatch)
    deliver(_paid(clock))
    assert len(fs.items) == 5


def test_F1_B_stripe_updating_the_plan_after_invoice_paid_holds_then_bills_once(env, monkeypatch):
    """No Stripe error: the plan is still past_due when invoice.paid lands, so
    the user stays failed and the overage is HELD; subscription.updated
    'active' restores the user and bills it - once."""
    db, fs, clock = _recovering_user(env, monkeypatch, sub_status="past_due")
    deliver(_paid(clock))
    assert db.user()["payment_status"] == "failed" and fs.items == []
    assert sorted(v for k, v in db.keys("overage_unit:u1:f").items()) == ["overage_held"] * 5
    fs.subs[SUB]["status"] = "active"
    deliver(sub_event("evt_act", "active", created=clock.now + timedelta(minutes=1)))
    assert db.user()["payment_status"] == "ok" and len(fs.items) == 5
    deliver(sub_event("evt_act2", "active", created=clock.now + timedelta(minutes=2)))
    run_lifecycle(clock, 5)
    assert len(fs.items) == 5


def test_F1_B_the_daily_restore_bills_held_overage(env, monkeypatch):
    db, fs, clock = _recovering_user(env, monkeypatch, sub_status="past_due")
    deliver(_paid(clock))
    assert fs.items == []
    fs.subs[SUB]["status"] = "active"
    run_lifecycle(clock, 5)
    assert db.user()["payment_status"] == "ok" and len(fs.items) == 5
    run_lifecycle(clock, 6)
    assert len(fs.items) == 5


def test_F1_held_overage_is_never_billed_while_still_failing(env, monkeypatch):
    db, fs, clock = _recovering_user(env, monkeypatch, sub_status="past_due")
    deliver(_paid(clock))
    assert run(us.bill_held_overage("u1")) == 0 and fs.items == []


# ═════════════════════════════════════════════════════════════════════════════
# F2 - a stale pending copy of an invoiced unit is deleted, never billed
# ═════════════════════════════════════════════════════════════════════════════
def test_F2_C_a_stale_pending_copy_of_an_invoiced_unit_is_not_billed_again(env):
    """Repro C, fixed."""
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id="sub_B", payment_status="canceling")
    fs.add_customer()
    fs.add_sub("sub_B", status="canceled")
    _unit(db, "u1", "X", "overage_billed")
    uk = "overage_unit:u1:X"
    fs.items.append({"id": "ii_on_final_A", "customer": CUS, "amount": 300, "invoice": "in_final_A",
                     "metadata": {"unit_key": uk, "user_id": "u1"}})
    fs.items.append({"id": "ii_stale_X", "customer": CUS, "amount": 300, "subscription": "sub_A",
                     "metadata": {"unit_key": uk, "user_id": "u1"}})
    deliver(_deleted(sub="sub_B"))
    charged = [i for i in fs.items if str(i.get("invoice", "")).startswith("in_final_")
               and i["id"] != "ii_on_final_A"]
    assert charged == []
    assert "ii_stale_X" not in {i["id"] for i in fs.items}              # the stale copy is gone


def test_F2_the_listing_order_does_not_matter(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(stripe_subscription_id="sub_B", payment_status="canceling")
    fs.add_customer()
    fs.add_sub("sub_B", status="canceled")
    _unit(db, "u1", "X", "overage_billed")
    uk = "overage_unit:u1:X"
    fs.items.append({"id": "ii_stale_X", "customer": CUS, "amount": 300, "subscription": "sub_B",
                     "metadata": {"unit_key": uk}})                       # pending copy listed FIRST
    fs.items.append({"id": "ii_on_renewal", "customer": CUS, "amount": 300, "invoice": "in_renewal",
                     "metadata": {"unit_key": uk}})
    deliver(_deleted(sub="sub_B"))
    assert _final_invoices(fs) == []


# ═════════════════════════════════════════════════════════════════════════════
# F3 - recovering a finalized final invoice touches only its own units
# ═════════════════════════════════════════════════════════════════════════════
def test_F3_recovering_a_finalized_final_invoice_never_wipes_a_new_plans_overage(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deliver(_deleted())                                       # plan A's final invoice, paid
    (key,) = db.keys("final_overage:")
    # The user is on plan B now: one pending unit of B in Stripe, one B never took.
    fs.add_sub("sub_B", status="active")
    _unit(db, "u1", "Y", "overage_billed")
    _pending_item(fs, "u1", "Y", subscription="sub_B")
    _unit(db, "u1", "Z", "overage_pending")
    # A's final bill is retried (its ledger row reset, e.g. after a crash).
    db.lite.execute("UPDATE processed_webhook_events SET event_type=? WHERE event_id=?", (svc.FINAL_PENDING, key))
    run(svc.settle_final_overage(key))
    assert "ii_u1_Y" in {i["id"] for i in fs.items if not i.get("invoice")}     # B's pending item kept
    assert db.keys("overage_unit:")["overage_unit:u1:Z"] == "overage_pending"  # not marked billed
    assert len(_final_invoices(fs)) == 1


def test_F3_a_plans_final_bill_leaves_another_plans_pending_items(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    _unit(db, "u1", "q1", "overage_billed")
    _pending_item(fs, "u1", "q1", subscription="sub_other_plan")
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == ["overage_unit:u1:p1"]
    assert "ii_u1_q1" in {i["id"] for i in fs.items if not i.get("invoice")}


# ═════════════════════════════════════════════════════════════════════════════
# F4 - "already paid" right after finalizing is a success
# ═════════════════════════════════════════════════════════════════════════════
def test_F4_an_invoice_stripe_collected_first_is_no_failed_charge(env, monkeypatch):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")

    def collected_first(iid, **kw):
        fs.calls.append(("Invoice.pay", (iid,), kw))
        fs.invoices[iid]["status"] = "paid"                    # auto_advance collected it
        raise stripe.error.InvalidRequestError("Invoice is already paid", None)
    monkeypatch.setattr(stripe.Invoice, "pay", collected_first)
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert inv["status"] == "paid"
    assert not [a for a in env["side"]["audit"] if a[1] == "payment.final_overage_charge_failed"]
    assert env["alerts"] == []
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_INVOICED]


def test_F4_a_real_decline_is_still_a_failed_charge(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.fail.add("Invoice.pay:decline")
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert ("u1", "payment.final_overage_charge_failed", inv["id"]) in env["side"]["audit"]
    assert len(env["alerts"]) == 1


def test_a_draft_left_by_a_crash_is_found_again_after_the_keys_expired(env):
    """The final bill created its draft, then Stripe failed before the items
    were added; 24 h+ later (idempotency keys gone) the retry finds the draft by
    its metadata - one final invoice, never two."""
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.fail = {"InvoiceItem.create"}
    deliver(_deleted())
    assert [i["status"] for i in _final_invoices(fs)] == ["draft"]
    fs.fail = set()
    fs.idem.clear()
    db.lite.execute("UPDATE processed_webhook_events SET processed_at='2000-01-01T00:00:00+00:00'"
                    " WHERE event_id LIKE 'final_overage:%'")
    assert run(svc.retry_final_overage()) == 1
    (inv,) = _final_invoices(fs)
    assert inv["status"] == "paid"
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == ["overage_unit:u1:p1"]
