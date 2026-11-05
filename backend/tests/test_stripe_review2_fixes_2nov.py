"""Second billing review, fixed offline (2 Nov 2026).

Every item of the second review (C1, M-1, M-2, M-4, M-5, L-1 .. L-10) plus the
reviewer's offline reproductions A-I, turned around to assert the CORRECT
behaviour. Reuses the fakes of tests/test_stripe_live_readiness_2nov.py: an
in-memory sqlite store behind an asyncpg-shaped pool (the handlers' own SQL runs
as written), a fake Stripe that records every call, sockets blocked.
"""
import ast
import asyncio
import logging
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import stripe
from fastapi import HTTPException

import routes.auth_routes as ar
import routes.download_routes as dr
import routes.form_routes as fr
from tests.test_stripe_live_readiness_2nov import (  # noqa: F401  (fixtures by name)
    CUS, SUB, T0, _JsonReq, _Obj, _no_network, checkout, checkout_event, clock, count, db, deliver,
    env, failed_user, fs, mail, paid_event, run, run_lifecycle, sessions, side, sr, ss, svc, sub_event,
    us, webhook, invoice_event,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _freeze_usage_clock(monkeypatch, clock):
    class _Frozen(sr.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now if tz else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(us, "datetime", _Frozen)


def _unit(db, uid, sid, state, at=None):
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    (f"overage_unit:{uid}:{sid}", state, at or datetime.now(timezone.utc).isoformat()))


def _pending_item(fs, uid, sid, amount=300, customer=CUS, subscription=SUB):
    fs.items.append({"id": f"ii_{uid}_{sid}", "customer": customer, "amount": amount,
                     "subscription": subscription,
                     "metadata": {"unit_key": f"overage_unit:{uid}:{sid}", "user_id": uid}})


def _deleted(evt_id="evt_del", sub=SUB):
    return sub_event(evt_id, "canceled", etype="customer.subscription.deleted", sub=sub)


def _final_invoices(fs):
    return [i for i in fs.invoices.values()]


# ═════════════════════════════════════════════════════════════════════════════
# C1 - a plan that ends bills its unbilled extra packages, once
# ═════════════════════════════════════════════════════════════════════════════
def _ending_user(env, **cols):
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status="canceling", **cols)
    fs.add_customer()
    fs.add_sub(SUB, status="canceled")
    return db, fs


def test_C1_a_cancelled_plan_bills_its_pending_overage_on_one_final_invoice(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _unit(db, "u1", "p2", "overage_billed")
    _unit(db, "u1", "p3", "overage_pending")              # Stripe never took it
    _pending_item(fs, "u1", "p1")
    _pending_item(fs, "u1", "p2")
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    create = fs.names("Invoice.create")[0][2]
    assert create["pending_invoice_items_behavior"] == "exclude"
    assert create["collection_method"] == "charge_automatically" and create["auto_advance"] is False
    on_inv = sorted(i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"])
    assert on_inv == ["overage_unit:u1:p1", "overage_unit:u1:p2", "overage_unit:u1:p3"]
    assert not [i for i in fs.items if not i.get("invoice")]         # the pending copies are gone
    fin = fs.names("Invoice.finalize_invoice")[0]
    assert fin[2]["auto_advance"] is True
    assert fs.invoices[inv["id"]]["status"] == "paid"
    assert all(c[2].get("idempotency_key") for c in fs.calls if c[0] in (
        "Invoice.create", "InvoiceItem.create", "Invoice.finalize_invoice", "Invoice.pay"))
    keys = db.keys("final_overage:")
    assert list(keys.values()) == [svc.FINAL_INVOICED]
    assert db.keys("overage_unit:")["overage_unit:u1:p3"] == "overage_billed"
    u = db.user()
    assert u["subscription_tier"] == "free" and u["payment_status"] == "ok"
    assert ("u1", "payment.final_overage_invoiced", inv["id"]) in env["side"]["audit"]


def test_C1_a_redelivered_end_bills_nothing_more(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deliver(_deleted())
    n = len(fs.calls)
    deliver(_deleted())
    assert len(_final_invoices(fs)) == 1 and len(fs.calls) == n


def test_C1_units_counted_while_canceling_are_owed_and_billed(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(payment_status="canceling", packages_used=105, packages_limit=100)
    fs.add_customer()
    fs.add_sub(SUB, status="active", cancel_at_period_end=True)
    count("u1", "p106")                                    # canceling still pays its period
    (item,) = [c for c in fs.names("InvoiceItem.create")]
    assert item[2]["subscription"] == SUB and item[2]["idempotency_key"] == "overage_unit:u1:p106"
    fs.subs[SUB]["status"] = "canceled"                    # the period ends, no renewal
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert [i["metadata"]["unit_key"] for i in fs.items if i.get("invoice") == inv["id"]] == [
        "overage_unit:u1:p106"]


def test_C1_never_for_an_accidental_duplicate(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.add_sub("sub_dup", status="canceled")
    deliver(_deleted("evt_del_dup", sub="sub_dup"))        # the cancelled duplicate ends
    assert _final_invoices(fs) == [] and db.keys("final_overage:") == {}
    assert db.user()["subscription_tier"] == "professional"


def test_Q5_a_live_duplicate_never_keeps_the_ended_plan_alive(env):
    """Round 3 (Q5) - replaces the round-2 "never while another live plan"
    rule: the stored plan ended, so the user is downgraded and its overage
    billed even while an accidental duplicate (refund pending) is still live.
    The duplicate's own end later changes nothing."""
    db, fs = _ending_user(env)
    fs.add_sub("sub_dup", status="active")                # refund pending
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deliver(_deleted())
    assert db.user()["subscription_tier"] == "free" and db.user()["stripe_subscription_id"] is None
    assert len(_final_invoices(fs)) == 1
    fs.subs["sub_dup"]["status"] = "canceled"
    deliver(_deleted("evt_del_dup", sub="sub_dup"))
    assert db.user()["subscription_tier"] == "free" and len(_final_invoices(fs)) == 1


def test_C1_only_this_users_primble_units(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    _pending_item(fs, "u2", "x1")                          # someone else's unit (shared customer)
    fs.items.append({"id": "ii_manual", "customer": CUS, "amount": 999, "metadata": {}})
    deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert [i["metadata"].get("unit_key") for i in fs.items if i.get("invoice") == inv["id"]] == [
        "overage_unit:u1:p1"]
    assert {i["id"] for i in fs.items if not i.get("invoice")} == {"ii_u2_x1", "ii_manual"}


def test_C1_a_declined_final_charge_is_logged_audited_and_left_to_stripe(env, caplog):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.refuse = set()
    fs.fail = set()
    fs.fail.add("Invoice.pay:decline")
    with caplog.at_level(logging.ERROR):
        deliver(_deleted())
    (inv,) = _final_invoices(fs)
    assert inv["status"] == "open"                         # finalized; Stripe collects / retries
    assert ("u1", "payment.final_overage_charge_failed", inv["id"]) in env["side"]["audit"]
    assert any("Final overage charge FAILED" in r.message for r in caplog.records)
    u = db.user()
    assert u["subscription_tier"] == "free" and u["payment_status"] == "ok" and u["payment_failed_at"] is None
    # the final invoice's own failure webhook never touches the (now free) user
    deliver({"id": "evt_ff", "type": "invoice.payment_failed",
             "data": {"object": {"id": inv["id"], "customer": CUS, "billing_reason": "manual"}}})
    assert db.user()["payment_status"] == "ok"


def test_C1_stripe_unreachable_leaves_it_pending_and_the_daily_job_bills_it_once(env):
    db, fs, clock = _ending_user(env) + (env["clock"],)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.fail = {"Invoice.create"}
    deliver(_deleted())
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_PENDING]
    assert _final_invoices(fs) == []
    fs.fail = set()
    db.lite.execute("UPDATE processed_webhook_events SET processed_at='2000-01-01T00:00:00+00:00'"
                    " WHERE event_id LIKE 'final_overage:%'")
    assert run(svc.retry_final_overage()) == 1
    assert run(svc.retry_final_overage()) == 0
    assert len(_final_invoices(fs)) == 1


def test_C1_a_retry_after_the_idempotency_keys_expired_finds_its_invoice(env):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deliver(_deleted())
    (key,) = db.keys("final_overage:")
    fs.idem.clear()                                         # 24 h later: Stripe forgot the keys
    db.lite.execute("UPDATE processed_webhook_events SET event_type=? WHERE event_id=?",
                    (svc.FINAL_PENDING, key))
    run(svc.settle_final_overage(key))
    assert len(_final_invoices(fs)) == 1


def test_C1_a_blank_key_process_never_bills_or_gives_up(env, monkeypatch):
    db, fs = _ending_user(env)
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    monkeypatch.setattr(stripe, "api_key", "")
    deliver(_deleted())
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_PENDING]
    assert run(svc.retry_final_overage()) == 0 and _final_invoices(fs) == []


def test_C1_a_user_who_never_had_overage_costs_no_stripe_call(env):
    db, fs = _ending_user(env)
    fs.calls.clear()
    deliver(_deleted())
    assert not [c for c in fs.calls if c[0].startswith(("Invoice", "InvoiceItem"))]
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_NONE]


@pytest.fixture
def deleting(monkeypatch):
    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(ar, "revoke_all_sessions", _noop)
    monkeypatch.setattr(ar, "write_audit_log", _noop)
    return lambda user: run(ar.delete_account(_JsonReq({}), current_user=user,
                                              acordly_session=None, authorization=None))


def test_C1_delete_account_bills_the_final_overage_at_that_moment(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deleting(db.user())
    assert db.user() is None
    (inv,) = _final_invoices(fs)
    assert inv["status"] == "paid"
    # the subscription.deleted Stripe sends for that cancel bills nothing more
    deliver(_deleted("evt_after_delete"))
    assert len(_final_invoices(fs)) == 1


def test_C1_delete_account_with_stripe_down_on_the_bill_still_deletes_and_retries_later(env, deleting):
    db, fs = env["db"], env["stripe"]
    db.add_user(password_hash=None)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    fs.fail = {"InvoiceItem.list"}
    deleting(db.user())
    assert db.user() is None
    assert list(db.keys("final_overage:").values()) == [svc.FINAL_PENDING]
    fs.fail = set()
    db.lite.execute("UPDATE processed_webhook_events SET processed_at='2000-01-01T00:00:00+00:00'"
                    " WHERE event_id LIKE 'final_overage:%'")
    assert run(svc.retry_final_overage()) == 1 and len(_final_invoices(fs)) == 1


# ═════════════════════════════════════════════════════════════════════════════
# M-4 - an accidental duplicate's refund never refunds the existing plan's overage
# ═════════════════════════════════════════════════════════════════════════════
def test_M4_overage_items_are_scoped_to_the_users_plan(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(packages_used=105, packages_limit=100)
    count("u1", "p106")
    assert fs.names("InvoiceItem.create")[0][2]["subscription"] == SUB


def test_M4_the_duplicate_refund_covers_its_plan_line_only(env):
    """The duplicate's first invoice also carried a $3 overage item (a legacy,
    unscoped one): only the $299 plan line is refunded."""
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active", latest_invoice="in_dup")
    fs.invoice_payments["in_dup"] = ["pi_dup"]
    fs.invoice_lines["in_dup"] = [
        {"amount": 29900, "parent": {"type": "subscription_item_details",
                                     "subscription_item_details": {"subscription": "sub_dup"}}},
        {"amount": 300, "parent": {"type": "invoice_item_details"}},
    ]
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    (refund,) = fs.names("Refund.create")
    assert refund[2]["amount"] == 29900 and refund[2]["payment_intent"] == "pi_dup"


# ═════════════════════════════════════════════════════════════════════════════
# M-1 - only a Stripe refusal hands a duplicate to a person; a blank key never
# ═════════════════════════════════════════════════════════════════════════════
def _dup(env):
    db, fs = env["db"], env["stripe"]
    db.add_user()
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.add_sub("sub_dup", status="active", latest_invoice="in_dup")
    fs.invoice_payments["in_dup"] = ["pi_dup"]
    return db, fs


def _age_duplicates(db, iso="2000-01-01T00:00:00+00:00"):
    db.lite.execute("UPDATE processed_webhook_events SET processed_at=? WHERE event_id LIKE 'duplicate_checkout:%'",
                    (iso,))


@pytest.mark.parametrize("err", [
    stripe.error.APIConnectionError("down"),
    stripe.error.RateLimitError("slow down"),
    stripe.error.APIError("bad gateway", http_status=502),
    stripe.error.AuthenticationError("No API key provided"),
])
def test_M1_A_a_transient_failure_stays_pending_and_the_daily_job_refunds_it(env, monkeypatch, err):
    """Repro A, fixed: a transient failure no longer makes the duplicate manual
    for good - the daily job retries and refunds it."""
    db, fs = _dup(env)
    real_cancel = fs.sub_cancel

    def failing_cancel(sid, **kw):
        fs.calls.append(("Subscription.cancel", (sid,), kw))
        raise err
    monkeypatch.setattr(stripe.Subscription, "cancel", failing_cancel)
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert db.keys(svc.DUP_PREFIX) == {"duplicate_checkout:u1:sub_dup:in_dup": svc.DUP_PENDING}
    assert env["alerts"] == [] and not fs.names("Refund.create")
    monkeypatch.setattr(stripe.Subscription, "cancel", real_cancel)
    _age_duplicates(db)
    assert run(svc.retry_unsettled_duplicates()) == 1
    assert fs.subs["sub_dup"]["status"] == "canceled" and fs.names("Refund.create")
    assert db.keys(svc.DUP_PREFIX)["duplicate_checkout:u1:sub_dup:in_dup"] == svc.DUP_REFUNDED


def test_M1_a_blank_key_never_moves_a_duplicate_to_manual_nor_runs_the_job(env, monkeypatch):
    db, fs = _dup(env)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("duplicate_checkout:u1:sub_dup:in_dup", svc.DUP_PENDING, "2000-01-01T00:00:00+00:00"))
    monkeypatch.setattr(stripe, "api_key", "")
    out = run(svc.settle_duplicate_checkout({"id": "u1", "email": ""}, "sub_dup", "in_dup",
                                            first_seen="2000-01-01T00:00:00+00:00"))
    assert out["state"] == "pending"
    assert run(svc.retry_unsettled_duplicates()) == 0
    assert fs.calls == [] and env["alerts"] == []
    assert db.keys(svc.DUP_PREFIX)["duplicate_checkout:u1:sub_dup:in_dup"] == svc.DUP_PENDING


def test_M1_a_refusal_goes_manual_with_one_alert_email(env):
    db, fs = _dup(env)
    fs.refuse = {"Refund.create"}
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert db.keys(svc.DUP_PREFIX)["duplicate_checkout:u1:sub_dup:in_dup"] == svc.DUP_MANUAL
    (alert,) = env["alerts"]
    assert alert[0] == "info@primble.com" and "MANUAL REFUND NEEDED" in alert[1]
    assert "in_dup" in alert[2] and "sub_dup" in alert[2]
    # settling it again (a person re-runs it, a stray retry) never e-mails twice
    run(svc.settle_duplicate_checkout({"id": "u1", "email": ""}, "sub_dup", "in_dup"))
    assert len(env["alerts"]) == 1


def test_M1_an_alert_that_failed_to_send_goes_out_with_the_daily_job(env, monkeypatch):
    import services.email_service as email_service
    db, fs = _dup(env)
    fs.refuse = {"Refund.create"}
    monkeypatch.setattr(email_service, "_send_generic_email", lambda *a: False)
    deliver(checkout_event("evt_dup", "sub_dup", invoice="in_dup"))
    assert list(db.keys(svc.ALERT_PREFIX).values()) == [svc.ALERT_PENDING]
    sent = []
    monkeypatch.setattr(email_service, "_send_generic_email", lambda *a: sent.append(a) or True)
    assert run(svc.retry_billing_alerts()) == 1
    assert run(svc.retry_billing_alerts()) == 0
    assert sent[0][0] == "info@primble.com"


def test_M1_three_days_of_failures_go_to_a_person(env):
    db, fs = _dup(env)
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    ("duplicate_checkout:u1:sub_dup:in_dup", svc.DUP_PENDING, "2000-01-01T00:00:00+00:00"))
    fs.fail = {"Subscription.cancel"}
    run(svc.retry_unsettled_duplicates())
    assert db.keys(svc.DUP_PREFIX)["duplicate_checkout:u1:sub_dup:in_dup"] == svc.DUP_MANUAL
    assert len(env["alerts"]) == 1


@pytest.mark.parametrize("err,transient", [
    (stripe.error.APIConnectionError("x"), True), (stripe.error.RateLimitError("x"), True),
    (stripe.error.APIError("x", http_status=503), True), (stripe.error.AuthenticationError("x"), True),
    (stripe.error.IdempotencyError("x"), True), (svc.StripeUnavailable("x"), True),
    (stripe.error.InvalidRequestError("x", None), False), (stripe.error.CardError("x", None, "c"), False),
    (stripe.error.PermissionError("x"), False),
])
def test_M1_the_error_classes(err, transient):
    assert svc.is_transient(err) is transient


# ═════════════════════════════════════════════════════════════════════════════
# M-2 - the free reservation is tied to its session
# ═════════════════════════════════════════════════════════════════════════════
def _free(db):
    db.add_user(subscription_tier="free", stripe_customer_id=None, stripe_subscription_id=None, downloads_used=0)


def _age_reservations(db):
    db.lite.execute("UPDATE processed_webhook_events SET processed_at='2000-01-01T00:00:00+00:00'"
                    " WHERE event_id LIKE 'free_reservation:%'")


def test_M2_B_a_rerun_of_the_same_package_adopts_its_reservation(env):
    """Repro B, fixed: the process died mid-generation; the re-run of the same
    package passes the gate and adopts the reservation - no second package."""
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    # ...process killed here: no finally, no release.
    assert db.user()["downloads_used"] == 1
    assert run(us.free_packages_in_use("u1", "pkg1")) == 0          # the gate lets the re-run in
    assert run(us.reserve_free_package("u1", "pkg1"))                # adopted
    assert db.user()["downloads_used"] == 1
    count("u1", "pkg1", reserved_free=True)
    assert db.user()["downloads_used"] == 1


def test_M2_B_a_package_whose_run_died_after_saving_still_downloads(env):
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    assert run(us.holds_free_reservation("u1", "pkg1")) is True
    assert dr._free_limit_blocks("free", 1, {"generated_forms": {"ACORD_125": {}}}, reserved=True) is False
    count("u1", "pkg1")                                     # the download counts it: the reservation
    assert db.user()["downloads_used"] == 1
    assert run(us.holds_free_reservation("u1", "pkg1")) is False


def test_M2_a_dead_runs_reservation_is_released_for_another_package(env):
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "dead"))
    assert run(us.reserve_free_package("u1", "new")) is False        # still inside the heartbeat window
    _age_reservations(db)
    assert run(us.reserve_free_package("u1", "new")) is True         # dead one released, new taken
    assert db.user()["downloads_used"] == 1
    assert db.keys("free_reservation:")["free_reservation:u1:dead"] == "free_released"


def test_M2_a_live_generation_keeps_its_reservation(env, monkeypatch):
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "running"))
    _age_reservations(db)

    async def _live(_sid):
        return True
    monkeypatch.setattr(us, "_generation_live", _live)
    assert run(us.reserve_free_package("u1", "other")) is False
    assert db.keys("free_reservation:")["free_reservation:u1:running"] == "free_reserved"


def test_M2_a_counted_session_never_gives_its_reservation_back(env):
    db, sessions = env["db"], env["sessions"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    sessions.counted["pkg1"] = ("u1", datetime.now(timezone.utc).isoformat())   # counted elsewhere
    _age_reservations(db)
    run(us.reconcile_free_reservations("u1"))
    assert db.user()["downloads_used"] == 1
    assert db.keys("free_reservation:")["free_reservation:u1:pkg1"] == "free_consumed"


def test_M2_a_request_cancelled_after_counting_keeps_the_package_counted(env):
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    count("u1", "pkg1", reserved_free=True)
    run(us.release_free_package("u1", "pkg1"))             # the route's finally after a cancel
    assert db.user()["downloads_used"] == 1


def test_M2_a_failed_run_gives_its_reservation_back_once(env):
    db = env["db"]
    _free(db)
    assert run(us.reserve_free_package("u1", "pkg1"))
    run(us.release_free_package("u1", "pkg1"))
    run(us.release_free_package("u1", "pkg1"))
    assert db.user()["downloads_used"] == 0


def test_M2_the_routes_tie_the_reservation_to_the_session():
    src = (ROOT / "routes/form_routes.py").read_text()
    tree = ast.parse(src)
    for name in ("select_forms_bulk", "lite_generate_internal"):
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        body = ast.get_source_segment(src, fn)
        assert "free_packages_in_use(" in body
        assert "reserve_free_package(str(current_user[\"id\"]), " in body
        assert "release_free_package(str(current_user[\"id\"]), " in body
    dsrc = (ROOT / "routes/download_routes.py").read_text()
    assert dsrc.count("holds_free_reservation(") == 2


# ═════════════════════════════════════════════════════════════════════════════
# M-5 / L-6 - invoice.paid restores only a plan that pays again
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status", ["past_due", "unpaid"])
def test_M5_paying_one_old_invoice_of_an_unpaid_plan_restores_nothing(env, status):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, stage="suspended", sent=21, billing_period_start=(T0 - timedelta(days=40)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status=status)
    clock.at(days=25)
    deliver(paid_event("evt_old", "in_old_one", created=clock.now, inv_created=T0 - timedelta(days=10)))
    u = db.user()
    assert u["payment_status"] == "suspended" and u["payment_failed_at"] == T0.isoformat()


def test_M5_stripe_unreachable_keeps_the_failure_and_the_daily_job_restores(env):
    """Round 4 (F1): Stripe out of reach is now a 503 before anything is
    claimed (Stripe re-sends); the failure is kept meanwhile."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.fail = {"Subscription.retrieve"}
    clock.at(days=8)
    with pytest.raises(HTTPException) as ei:
        deliver(paid_event("evt_paid", "in_p", created=clock.now, inv_created=clock.now))
    assert ei.value.status_code == 503 and "evt_paid" not in db.keys()
    assert db.user()["payment_status"] == "failed"
    fs.fail = set()
    run_lifecycle(clock, 9)
    assert db.user()["payment_status"] == "ok"


def test_M5_an_active_plan_restores(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, stage="soft_locked", sent=10)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.at(days=12)
    deliver(paid_event("evt_paid", "in_p", created=clock.now, inv_created=clock.now))
    assert db.user()["payment_status"] == "ok"


def test_L6_F_invoice_paid_keeps_canceling(env):
    """Repro F, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(payment_status="failed", payment_failed_at=T0.isoformat(),
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active", cancel_at_period_end=True)
    clock.now = T0 + timedelta(days=1)
    deliver(paid_event("evt_paid", "in_x", created=clock.now, inv_created=T0))
    assert db.user()["payment_status"] == "canceling"


# ═════════════════════════════════════════════════════════════════════════════
# L-1 - 'active' restores 'archived'; the daily job asks about everyone failed
# ═════════════════════════════════════════════════════════════════════════════
def test_L1_G_an_archived_user_who_paid_is_restored_by_active_and_by_the_job(env):
    """Repro G, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(payment_status="archived", payment_failed_at=(T0 - timedelta(days=61)).isoformat(),
                payment_email_sent_day=60, billing_period_start=(T0 - timedelta(days=90)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 + timedelta(hours=1)
    deliver({"id": "evt_act", "type": "customer.subscription.updated", "created": int(clock.now.timestamp()),
             "data": {"object": {"id": SUB, "status": "active", "cancel_at_period_end": False,
                                 "metadata": {"plan": "professional"}}}})
    assert db.user()["payment_status"] == "ok"


def test_L1_the_job_restores_an_archived_user_with_nothing_due(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(payment_status="archived", payment_failed_at=(T0 - timedelta(days=61)).isoformat(),
                payment_email_sent_day=60)
    fs.add_customer()
    fs.add_sub(SUB, status="active")                       # paid in the portal; both webhooks lost
    clock.now = T0 + timedelta(days=1, hours=1)
    run(ss.run_daily_payment_lifecycle())
    assert db.user()["payment_status"] == "ok"


def test_L1_stripe_unreachable_changes_nobody(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(payment_status="archived", payment_failed_at=(T0 - timedelta(days=61)).isoformat(),
                payment_email_sent_day=60)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    fs.fail = {"Subscription.retrieve"}
    clock.now = T0 + timedelta(days=1, hours=1)
    run(ss.run_daily_payment_lifecycle())
    assert db.user()["payment_status"] == "archived"


# ═════════════════════════════════════════════════════════════════════════════
# L-2 - a checkout completed for a deleted account is cancelled and refunded
# ═════════════════════════════════════════════════════════════════════════════
def test_L2_H_a_checkout_for_a_deleted_user_is_cancelled_and_refunded(env):
    """Repro H, fixed."""
    db, fs = env["db"], env["stripe"]
    fs.add_customer()
    fs.add_sub("sub_orphan", status="active", latest_invoice="in_o")
    fs.invoice_payments["in_o"] = ["pi_o"]
    deliver(checkout_event("evt_o", "sub_orphan", invoice="in_o"))
    assert fs.subs["sub_orphan"]["status"] == "canceled"
    assert [c[2]["payment_intent"] for c in fs.names("Refund.create")] == ["pi_o"]
    assert "evt_o" in db.keys()
    assert db.keys(svc.DUP_PREFIX) == {"duplicate_checkout:u1:sub_orphan:in_o": svc.DUP_REFUNDED}
    fs.calls.clear()
    deliver(checkout_event("evt_o", "sub_orphan", invoice="in_o"))      # re-delivery
    assert not fs.names("Subscription.cancel") and not fs.names("Refund.create")


def test_L2_a_checkout_naming_no_user_is_still_ignored(env):
    db, fs = env["db"], env["stripe"]
    fs.add_customer()
    fs.add_sub("sub_x", status="active")
    deliver(checkout_event("evt_x", "sub_x", uid=None, metadata={"plan": "professional"}))
    assert fs.subs["sub_x"]["status"] == "active" and db.keys() == {}


# ═════════════════════════════════════════════════════════════════════════════
# L-3 + L-4 - a package counts once, in the period it was counted in
# ═════════════════════════════════════════════════════════════════════════════
def _line(start, end):
    return {"type": "subscription", "period": {"start": int(start.timestamp()), "end": int(end.timestamp())},
            "parent": {"type": "subscription_item_details"}}


def test_L3_C_packages_after_the_period_end_are_not_old_overage_and_count_once(env, monkeypatch):
    """Repro C, fixed. The previous renewal stored the period's end (T0). Three
    packages counted between T0 and the renewal being paid are not billed as
    old-period overage; the paid renewal counts them once, in the new period."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=104, packages_limit=100,
                billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 - timedelta(days=30)
    deliver(paid_event("evt_prev", "in_prev", created=clock.now, inv_created=clock.now - timedelta(minutes=1),
                       lines=[_line(T0 - timedelta(days=30), T0)]))
    db.lite.execute("UPDATE users SET packages_used=104 WHERE id='u1'")
    for i in range(3):
        clock.now = T0 + timedelta(minutes=10 + i)
        r = count("u1", f"win{i}")
    assert r["pkg_eval"]["billing"] == "deferred"
    assert fs.items == []                                   # nothing billed as old-period overage
    clock.now = T0 + timedelta(hours=1)
    deliver(paid_event("evt_ren", "in_ren", created=clock.now, inv_created=T0,
                       lines=[_line(T0, T0 + timedelta(days=30))]))
    u = db.user()
    assert u["packages_used"] == 3 and fs.items == []       # once, in the new period, within allowance


def test_L3_packages_before_the_period_end_still_bill_as_overage(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=105, packages_limit=100)
    clock.now = T0 - timedelta(days=30)
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    deliver(paid_event("evt_prev", "in_prev", created=clock.now, inv_created=clock.now - timedelta(minutes=1),
                       lines=[_line(T0 - timedelta(days=30), T0)]))
    db.lite.execute("UPDATE users SET packages_used=105 WHERE id='u1'")
    clock.now = T0 - timedelta(days=1)
    assert count("u1", "late_in_period")["pkg_eval"]["billing"] == "billed"


def test_L3_deferred_packages_beyond_the_new_allowance_are_billed_at_the_renewal(env, monkeypatch):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=0, packages_limit=2)          # allowance 2, buffer 0
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 - timedelta(days=30)
    deliver(paid_event("evt_prev", "in_prev", created=clock.now, inv_created=clock.now - timedelta(minutes=1),
                       lines=[_line(T0 - timedelta(days=30), T0)]))
    db.lite.execute("UPDATE users SET packages_used=2 WHERE id='u1'")
    for i in range(3):
        clock.now = T0 + timedelta(minutes=10 + i)
        count("u1", f"w{i}")
    assert fs.items == []
    clock.now = T0 + timedelta(hours=1)
    deliver(paid_event("evt_ren", "in_ren", created=clock.now, inv_created=T0,
                       lines=[_line(T0, T0 + timedelta(days=30))]))
    assert db.user()["packages_used"] == 3
    assert [i["metadata"]["unit_key"] for i in fs.items] == ["overage_unit:u1:w2"]


def test_L4_D_a_package_counted_during_the_recount_is_not_lost(env, monkeypatch):
    """Repro D, fixed: the recount and the counter move under one lock, and an
    increment that slipped past it is kept."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=50, packages_limit=100, billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0 + timedelta(minutes=5)
    count("u1", "a")
    real_since = sr.packages_counted_since

    async def racing_since(uid, since, conn=None):
        rows = await real_since(uid, since, conn=conn)
        clock.now = T0 + timedelta(minutes=30)
        await us.count_session_usage("u1", "b")
        return rows
    monkeypatch.setattr(sr, "packages_counted_since", racing_since)
    clock.now = T0 + timedelta(hours=1)
    deliver(paid_event("evt_ren", "in_ren", created=clock.now, inv_created=T0,
                       lines=[_line(T0, T0 + timedelta(days=30))]))
    assert db.user()["packages_used"] == 2


def test_L4_the_count_and_the_recount_take_the_user_rows_lock():
    usrc = (ROOT / "services/usage_service.py").read_text()
    body = usrc[usrc.index("async def count_session_usage("):usrc.index("async def _evaluate_counted(")]
    lock = body.index('UPDATE users SET packages_used = packages_used WHERE id = $1')
    assert lock < body.index("claim_package_count(") < body.index("packages_used = COALESCE(packages_used, 0) + 1")
    assert "conn=conn" in body
    rsrc = (ROOT / "routes/stripe_routes.py").read_text()
    paid = rsrc[rsrc.index("async def _handle_invoice_paid("):rsrc.index("async def _handle_payment_failed(")]
    assert paid.index("SET packages_used = packages_used WHERE id=$1") < paid.index("packages_counted_since(")
    assert "conn=conn" in paid and "COALESCE(packages_used, 0) - $2" in paid


# ═════════════════════════════════════════════════════════════════════════════
# L-5 - an enterprise plan is Primble's
# ═════════════════════════════════════════════════════════════════════════════
def test_L5_E_enterprise_cannot_open_a_checkout(env):
    """Repro E, fixed."""
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="enterprise", stripe_subscription_id=None, packages_limit=5000)
    with pytest.raises(HTTPException) as ei:
        checkout(db, plan="essentials")
    assert ei.value.status_code == 409
    assert ei.value.detail == {"code": "subscription_exists",
                               "message": "Your plan is managed by Primble. Contact support@primble.com to change it."}
    assert fs.calls == []


def test_L5_E_a_checkout_completing_on_an_enterprise_plan_is_refunded(env):
    db, fs = env["db"], env["stripe"]
    db.add_user(subscription_tier="enterprise", stripe_subscription_id=None, packages_limit=5000)
    fs.add_customer()
    fs.add_sub("sub_new", status="active", plan="essentials", latest_invoice="in_new")
    fs.invoice_payments["in_new"] = ["pi_new"]
    deliver(checkout_event("evt_e", "sub_new", plan="essentials", invoice="in_new"))
    u = db.user()
    assert u["subscription_tier"] == "enterprise" and u["packages_limit"] == 5000
    assert fs.subs["sub_new"]["status"] == "canceled" and fs.names("Refund.create")


def test_L5_me_never_replaces_an_enterprise_plan(env, monkeypatch):
    db, fs = env["db"], env["stripe"]
    monkeypatch.setattr(ar, "_auth_redis", None)
    db.add_user(subscription_tier="enterprise", stripe_subscription_id=None, packages_limit=5000)
    fs.add_customer()
    fs.add_sub("sub_mine", status="active", plan="essentials")
    run(ar.get_me(current_user=db.user()))
    u = db.user()
    assert u["subscription_tier"] == "enterprise" and u["stripe_subscription_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# L-7 - only the plan's own invoices start a usage period
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("reason", ["manual", "subscription_update", "subscription_threshold", None])
def test_L7_I_a_non_renewal_invoice_never_resets_usage(env, reason):
    """Repro I, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=90, packages_limit=100, billing_period_start=(T0 - timedelta(days=10)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0
    evt = paid_event("evt_manual", "in_manual", created=clock.now, inv_created=T0)
    evt["data"]["object"]["billing_reason"] = reason
    deliver(evt)
    assert db.user()["packages_used"] == 90


@pytest.mark.parametrize("reason", ["subscription_cycle", "subscription_create"])
def test_L7_the_plans_own_invoices_still_reset(env, reason):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=90, packages_limit=100, billing_period_start=(T0 - timedelta(days=30)).isoformat())
    clock.now = T0
    evt = paid_event("evt_cycle", "in_cycle", created=clock.now, inv_created=T0)
    evt["data"]["object"]["billing_reason"] = reason
    deliver(evt)
    assert db.user()["packages_used"] == 0


def test_L7_the_final_overage_invoice_resets_nothing(env):
    db = env["db"]
    db.add_user(packages_used=5)
    deliver({"id": "evt_final_paid", "type": "invoice.paid",
             "data": {"object": {"id": "in_final_1", "customer": CUS, "billing_reason": "manual"}}})
    assert db.user()["packages_used"] == 5


# ═════════════════════════════════════════════════════════════════════════════
# L-8 - a blank key or a dev run never takes the day
# ═════════════════════════════════════════════════════════════════════════════
def test_L8_A2_a_blank_key_run_does_not_claim_the_day(env, monkeypatch):
    """Repro A2, fixed."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(payment_status="failed", payment_failed_at=(T0 - timedelta(days=10)).isoformat(),
                payment_email_sent_day=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    monkeypatch.setattr(stripe, "api_key", None)
    run(ss.run_daily_payment_lifecycle(force=True))
    run(ss.run_daily_payment_lifecycle())
    assert db.keys("lifecycle_run:") == {} and db.user()["payment_status"] == "failed"
    monkeypatch.setattr(stripe, "api_key", "sk_test_offline_only")
    run(ss.run_daily_payment_lifecycle())                    # the live server, same day
    assert db.user()["payment_status"] == "soft_locked"


def test_L8_a_forced_dev_run_never_claims_the_day(env):
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    clock.at(days=10, hours=1)
    run(ss.run_daily_payment_lifecycle(force=True))
    assert db.keys("lifecycle_run:") == {}
    assert db.user()["payment_status"] == "soft_locked"


# ═════════════════════════════════════════════════════════════════════════════
# L-9 - a crash between claiming an e-mail and sending it does not lose it
# ═════════════════════════════════════════════════════════════════════════════
def _crash_after_claim(env, day, prev, stage="failed"):
    """The claim and its marker are written; the process dies before sending."""
    db = env["db"]
    failed_at = db.user()["payment_failed_at"]
    db.lite.execute("UPDATE users SET payment_email_sent_day=? WHERE id='u1'", (day,))
    db.lite.execute("INSERT INTO processed_webhook_events VALUES (?,?,?)",
                    (svc.email_marker_key(day, prev, "u1", failed_at), svc.EMAIL_SENDING,
                     "2000-01-01T00:00:00+00:00"))


def test_L9_an_unconfirmed_email_is_sent_once_more(env):
    db, fs, clock, mail = env["db"], env["stripe"], env["clock"], env["mail"]
    failed_user(db, stage="soft_locked", sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    _crash_after_claim(env, 10, 7)
    run_lifecycle(clock, 11)
    assert mail.days() == [10]
    run_lifecycle(clock, 12)
    assert mail.days() == [10]                                 # at most once more
    assert db.keys(svc.EMAIL_MARK_PREFIX) == {}


def test_L9_a_restored_user_gets_no_late_email(env):
    db, fs, clock, mail = env["db"], env["stripe"], env["clock"], env["mail"]
    failed_user(db, stage="soft_locked", sent=7)
    _crash_after_claim(env, 10, 7)
    db.lite.execute("UPDATE users SET payment_status='ok', payment_failed_at=NULL WHERE id='u1'")
    run_lifecycle(clock, 11)
    assert mail.sent == [] and db.keys(svc.EMAIL_MARK_PREFIX) == {}


def test_L9_a_confirmed_send_leaves_no_marker(env):
    db, fs, clock, mail = env["db"], env["stripe"], env["clock"], env["mail"]
    failed_user(db, sent=7)
    fs.add_customer()
    fs.add_sub(SUB, status="past_due")
    run_lifecycle(clock, 10)
    assert mail.days() == [10] and db.keys(svc.EMAIL_MARK_PREFIX) == {}


def test_L9_the_webhooks_day0_email_is_marked_too(env, monkeypatch):
    db, mail = env["db"], env["mail"]
    db.add_user()
    seen = {}
    real = svc.claim_payment_email

    async def spy(conn, uid, day, prev, *rest):
        ok = await real(conn, uid, day, prev, *rest)
        seen["marked"] = db.keys(svc.EMAIL_MARK_PREFIX)
        return ok
    monkeypatch.setattr(svc, "claim_payment_email", spy)
    deliver(invoice_event("evt_f1"))
    assert mail.days() == [1] and db.keys(svc.EMAIL_MARK_PREFIX) == {}


# ═════════════════════════════════════════════════════════════════════════════
# L-10 - free users of lite/generate-internal; the dev reconcile route
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def lite(monkeypatch, env):
    sess = {"user_id": "u1", "recommendations": [{"form_id": "ACORD_125"}], "generated_forms": {},
            "all_forms": []}

    async def _get(sid, **_kw):
        return {**sess, "package_counted_at": env["sessions"].counted.get(sid, (None, None))[1]}
    monkeypatch.setattr(fr, "get_processing_session", _get)
    calls = {"n": 0, "fail": False}

    async def _gap_fill(loop, session, form_ids):
        calls["n"] += 1
        if calls["fail"]:
            raise RuntimeError("generation died")
        return {}

    async def _stops(*_a, **_k):
        return {"cross_issues": []}

    async def _upd(*_a, **_k):
        return None
    monkeypatch.setattr(fr, "_lite_shared_gap_fill", _gap_fill)
    monkeypatch.setattr(fr._fi, "form_meta_for", lambda *a, **k: {"template_file": "t.pdf"})
    monkeypatch.setattr(fr, "safe_join", lambda *_a: __file__)
    monkeypatch.setattr(fr, "process_single_form", lambda *a: {"sqs": {"sqs_score": 70}})
    monkeypatch.setattr(fr, "run_scoring", _stops)
    monkeypatch.setattr(fr, "upd_processing_session", _upd)
    return calls


def test_L10_a_free_lite_generation_is_reserved_and_counted_once(env, lite):
    db = env["db"]
    _free(db)
    run(fr.lite_generate_internal("pkgL", current_user=db.user()))
    run(fr.lite_generate_internal("pkgL", current_user=db.user()))   # every visit re-runs it
    assert db.user()["downloads_used"] == 1
    assert env["sessions"].counted["pkgL"][0] == "u1"
    with pytest.raises(HTTPException) as ei:                          # a second free package
        run(fr.lite_generate_internal("pkgM", current_user=db.user()))
    assert ei.value.status_code == 403


def test_L10_a_failed_lite_generation_gives_the_package_back(env, lite):
    db = env["db"]
    _free(db)
    lite["fail"] = True
    with pytest.raises(RuntimeError):
        run(fr.lite_generate_internal("pkgL", current_user=db.user()))
    assert db.user()["downloads_used"] == 0


def test_L10_the_dev_reconcile_route_bills_through_the_ledger(env, monkeypatch):
    import routes.dev_routes as devr
    db, fs, sessions = env["db"], env["stripe"], env["sessions"]
    monkeypatch.setattr(devr, "get_pool", lambda: sr.get_pool())
    db.add_user(packages_used=4, packages_limit=2, billing_period_start="2026-11-01T00:00:00+00:00")
    for i in range(4):
        sessions.counted[f"d{i}"] = ("u1", f"2026-11-01T0{i + 1}:00:00+00:00")
    monkeypatch.setattr("repositories.session_repository.packages_counted_since", sessions.since)
    out = run(devr.reconcile_overage(current_user=db.user()))
    assert out["newly_queued"] == 2
    run(devr.reconcile_overage(current_user=db.user()))
    keys = [c[2]["idempotency_key"] for c in fs.names("InvoiceItem.create")]
    assert keys == ["overage_unit:u1:d2", "overage_unit:u1:d3"]


# ═════════════════════════════════════════════════════════════════════════════
# The blank-key process (the Mac after the switch) never moves money
# ═════════════════════════════════════════════════════════════════════════════
def test_no_daily_billing_job_runs_without_a_key(env, monkeypatch):
    monkeypatch.setattr(stripe, "api_key", "")
    assert run(svc.retry_unsettled_duplicates()) == 0
    assert run(svc.retry_final_overage()) == 0
    assert env["stripe"].calls == []


def test_C1_the_final_invoice_charges_the_card_the_plan_used(env):
    """Checkout saves the card on the subscription, not as the customer's
    default: the final invoice names it."""
    db, fs = _ending_user(env)
    fs.subs[SUB]["default_payment_method"] = "pm_plan_card"
    _unit(db, "u1", "p1", "overage_billed")
    _pending_item(fs, "u1", "p1")
    deliver(_deleted())
    assert fs.names("Invoice.create")[0][2]["default_payment_method"] == "pm_plan_card"



def test_L3_C_first_renewal_after_deploy_a_package_billed_as_old_overage_counts_once(env, monkeypatch):
    """Repro C exactly (no period end stored yet): #106 and #107 counted after
    the period ended were billed as the old period's overage before the
    renewal was known; the paid renewal leaves them in the old period - only
    #105 (never billed) counts in the new one."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    _freeze_usage_clock(monkeypatch, clock)
    db.add_user(packages_used=104, packages_limit=100, billing_period_start=(T0 - timedelta(days=30)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    for i in range(3):
        clock.now = T0 + timedelta(minutes=10 + i)
        count("u1", f"win{i}")
    assert len(fs.items) == 2
    clock.now = T0 + timedelta(hours=1)
    line = {"type": "subscription", "period": {"start": int(T0.timestamp())}}
    deliver(paid_event("evt_ren", "in_ren", created=clock.now, inv_created=T0, lines=[line]))
    assert db.user()["packages_used"] == 1
    assert len(fs.items) == 2                               # nothing billed again


def test_L7_I_a_subscription_invoice_with_no_plan_line_resets_nothing(env):
    """Repro I exactly: support invoices the plan's pending overage now - a
    subscription invoice whose only line is an invoice item."""
    db, fs, clock = env["db"], env["stripe"], env["clock"]
    db.add_user(packages_used=90, packages_limit=100, billing_period_start=(T0 - timedelta(days=10)).isoformat())
    fs.add_customer()
    fs.add_sub(SUB, status="active")
    clock.now = T0
    inv_line = {"parent": {"type": "invoice_item_details"}, "period": {"start": int(T0.timestamp())}}
    deliver(paid_event("evt_manual", "in_manual", created=clock.now, inv_created=T0, lines=[inv_line]))
    assert db.user()["packages_used"] == 90
