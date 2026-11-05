"""Three guards found while scoping Apple Pay (3 Nov 2026, OPEN_ITEMS): a checkout whose payment has not settled
gives nothing; the Checkout payment-method parameter lives in one place with a tripwire for the Stripe API change;
the questionnaire send / remind limit; and the proxy-aware client IP. No Stripe call, no database."""
import asyncio
import json
import os

import pytest
import stripe

from routes import stripe_routes as sr
from utils import rate_limiter as rl

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 1. a payment that has not settled gives nothing ─────────────────────────
class _Req:
    def __init__(self, body):
        self._body, self.headers = body, {"stripe-signature": "t=1,v1=x"}

    async def body(self):
        return self._body


class _Event(dict):
    def __str__(self):
        return json.dumps(self)


def _fire(monkeypatch, event_type, obj):
    calls = []
    monkeypatch.setattr(sr, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda p, s, k: _Event(json.loads(p)))

    async def record(name):
        async def f(*a, **k):
            calls.append(name)
        return f
    for name in ("_handle_subscription_checkout", "_handle_overage_session", "_handle_setup_session"):
        monkeypatch.setattr(sr, name, asyncio.run(record(name)))
    event = {"id": "evt_1", "type": event_type, "created": 1, "data": {"object": obj}}
    out = asyncio.run(sr.stripe_webhook(_Req(json.dumps(event).encode())))
    return out, calls


SUB_SESSION = {"id": "cs_1", "mode": "subscription", "metadata": {"plan": "professional"}}


@pytest.mark.parametrize("status,granted", [("paid", True), ("no_payment_required", True), (None, True),
                                            ("unpaid", False)])
def test_checkout_completed_gives_only_settled_payments(monkeypatch, status, granted):
    obj = dict(SUB_SESSION, payment_status=status) if status else dict(SUB_SESSION)
    out, calls = _fire(monkeypatch, "checkout.session.completed", obj)
    assert out == {"received": True}
    assert calls == (["_handle_subscription_checkout"] if granted else [])


def test_the_delayed_payment_is_given_when_stripe_confirms_it(monkeypatch):
    _, calls = _fire(monkeypatch, "checkout.session.async_payment_succeeded", dict(SUB_SESSION, payment_status="paid"))
    assert calls == ["_handle_subscription_checkout"]
    _, calls = _fire(monkeypatch, "checkout.session.async_payment_failed", dict(SUB_SESSION, payment_status="unpaid"))
    assert calls == []


def test_an_unsettled_overage_pack_gives_nothing_either(monkeypatch):
    obj = {"id": "cs_2", "mode": "payment", "payment_status": "unpaid", "metadata": {"type": "overage"}}
    assert _fire(monkeypatch, "checkout.session.completed", obj)[1] == []
    assert _fire(monkeypatch, "checkout.session.completed", dict(obj, payment_status="paid"))[1] == ["_handle_overage_session"]


# ── 2. the Checkout parameter: one place, and a tripwire for Stripe's API change ──
def test_checkout_payment_methods_live_in_one_place():
    src = open(os.path.join(BACKEND, "routes", "stripe_routes.py")).read()
    assert src.count("**CHECKOUT_PAYMENT_METHODS") == 2
    assert 'payment_method_types=["card"]' not in src
    assert sr.CHECKOUT_PAYMENT_METHODS in ({"payment_method_types": ["card"]},
                                           {"allowed_payment_method_types": ["card"]})


def test_tripwire_stripe_api_version_vs_the_parameter():
    from stripe import _api_version
    version = _api_version._ApiVersion.CURRENT
    if version >= "2026-09-30" and "payment_method_types" in sr.CHECKOUT_PAYMENT_METHODS:
        pytest.fail(f"The Stripe SDK now uses API {version}, which rejects payment_method_types on Checkout "
                    "Sessions: set CHECKOUT_PAYMENT_METHODS = {'allowed_payment_method_types': ['card']} in "
                    "routes/stripe_routes.py (cards still include Apple Pay / Google Pay).")


# ── 3. the real client IP behind Render's proxy ──────────────────────────────
class _Http:
    def __init__(self, peer, xff=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}


def test_client_ip_default_is_unchanged(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert rl.get_client_ip(_Http("10.0.0.5", "1.2.3.4")) == "10.0.0.5"


@pytest.mark.parametrize("hops,xff,expected", [
    ("1", "203.0.113.7", "203.0.113.7"),                    # Render appended the real client
    ("1", "6.6.6.6, 203.0.113.7", "203.0.113.7"),           # a forged left entry is never used
    ("2", "203.0.113.7, 172.70.1.1", "203.0.113.7"),        # Cloudflare in front of Render
    ("2", "172.70.1.1", "10.0.0.5"),                        # fewer entries than hops: the peer
    ("1", "", "10.0.0.5"),
    ("1", "not-an-ip", "10.0.0.5"),
    ("1", "2001:db8::1", "2001:db8::1"),
    ("x", "203.0.113.7", "10.0.0.5"),                       # a bad setting = off
])
def test_client_ip_behind_trusted_proxies(monkeypatch, hops, xff, expected):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", hops)
    assert rl.get_client_ip(_Http("10.0.0.5", xff)) == expected


# ── 4. questionnaire sends and reminders are limited per producer ─────────────
def test_send_and_remind_share_one_limit(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(rl, "_redis", None)                 # the in-process window
    monkeypatch.setattr(rl, "_CLIENT_SENDS_PER_MINUTE", 3)
    for k in [k for k in rl._windows if "client_send" in k]:
        rl._windows.pop(k)
    for _ in range(3):
        asyncio.run(rl.check_client_send_rate_limit("u1"))
    with pytest.raises(HTTPException) as ex:
        asyncio.run(rl.check_client_send_rate_limit("u1"))
    assert ex.value.status_code == 429 and "questionnaires" in ex.value.detail
    asyncio.run(rl.check_client_send_rate_limit("u2"))      # another producer is not affected
    src = open(os.path.join(BACKEND, "routes", "arq_routes.py")).read()
    assert src.count("await check_client_send_rate_limit(current_user[\"id\"])") == 2   # send door + remind


# ── hard review, 3 Nov 2026: several headers, ports, the first log ───────────────────────────────────────────
def test_client_ip_reads_every_header_strips_ports_and_logs_once_with_entries(monkeypatch, caplog):
    import logging
    from starlette.datastructures import Headers
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")

    class _Many:
        def __init__(self, raw):
            self.client = type("C", (), {"host": "10.0.0.5"})()
            self.headers = Headers(raw=[(b"x-forwarded-for", v.encode()) for v in raw])
    assert rl.get_client_ip(_Many(["6.6.6.6", "203.0.113.7"])) == "203.0.113.7"    # the proxy's is in the last one
    for xff, ip in (("203.0.113.7:51234", "203.0.113.7"), ("[2001:db8::1]:443", "2001:db8::1"),
                    ("2001:db8::1", "2001:db8::1")):
        assert rl.get_client_ip(_Http("10.0.0.5", xff)) == ip
    monkeypatch.setattr(rl, "_ip_source_logged", False)
    with caplog.at_level(logging.INFO):
        rl.get_client_ip(_Http("10.0.0.5"))                   # a health check with no header: not the one logged
        rl.get_client_ip(_Http("10.0.0.5", "203.0.113.7"))
        rl.get_client_ip(_Http("10.0.0.5", "203.0.113.8"))
    logs = [r.getMessage() for r in caplog.records if "CLIENT_IP_SOURCE" in r.getMessage()]
    assert logs == ["CLIENT_IP_SOURCE trusted_hops=1 forwarded_entries=1"]
    assert "203.0.113" not in caplog.text


# ── review pass 2, 3 Nov 2026: refused attempts leave the window; an IPv6 /64 is one bucket ──────────────────
class _FakeRedis:
    def __init__(self):
        self.z = {}

    def pipeline(self):
        redis = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def zremrangebyscore(self, k, lo, hi):
                self.ops.append(("rem", k, hi))

            def zadd(self, k, m):
                self.ops.append(("add", k, m))

            def zcard(self, k):
                self.ops.append(("card", k))

            def expire(self, k, s):
                self.ops.append(("exp", k))

            async def execute(self):
                out = []
                for op in self.ops:
                    z = redis.z.setdefault(op[1], {})
                    if op[0] == "rem":
                        for m in [m for m, sc in z.items() if sc <= op[2]]:
                            del z[m]
                        out.append(0)
                    elif op[0] == "add":
                        z.update(op[2])
                        out.append(1)
                    elif op[0] == "card":
                        out.append(len(z))
                    else:
                        out.append(True)
                return out
        return _Pipe()

    async def zrem(self, k, m):
        self.z.get(k, {}).pop(m, None)


def test_retrying_while_blocked_never_extends_the_hour(monkeypatch):
    from fastapi import HTTPException
    clock = [0.0]
    monkeypatch.setattr(rl.time, "time", lambda: clock[0])
    monkeypatch.setattr(rl, "_redis", _FakeRedis())

    def attempt(minute):
        clock[0] = minute * 60.0
        try:
            asyncio.run(rl._check_rate_limit_by_key("client_send_h", "u1", 3, 3600, "x"))
            return "ok"
        except HTTPException:
            return "429"
    got = [attempt(t) for t in (0, 0.1, 0.2, 10, 20, 30, 40, 50, 60.5, 61, 70)]
    assert got == ["ok"] * 3 + ["429"] * 5 + ["ok"] * 3                # back in after the hour, as in-process


def test_an_ipv6_home_network_is_one_bucket_an_ipv4_address_is_itself():
    assert rl._limit_identity("2001:db8:1:2:aaaa::1") == rl._limit_identity("2001:db8:1:2:bbbb::9") == "2001:db8:1:2::/64"
    assert rl._limit_identity("2001:db8:1:3::1") != rl._limit_identity("2001:db8:1:2::1")
    assert rl._limit_identity("203.0.113.7") == "203.0.113.7"
    assert rl._limit_identity("::ffff:203.0.113.7") == "203.0.113.7"
    assert rl._limit_identity("user-123") == "user-123"                     # a user id is not an address
