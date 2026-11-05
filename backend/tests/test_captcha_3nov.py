"""Login / sign-up captcha - Cloudflare Turnstile (3 Nov 2026, services/captcha.py). Never reaches Cloudflare: the
HTTP client is replaced in every test that would call it."""
import asyncio
import os
import re

import pytest
from fastapi import HTTPException

from services import captcha

PASS_SITE, PASS_SECRET = "1x00000000000000000000AA", "1x0000000000000000000000000000000AA"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SITE_KEY", PASS_SITE)
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", PASS_SECRET)


class _Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _fake_client(monkeypatch, reply=None, error=None, seen=None):
    import httpx

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            if seen is not None:
                seen.append((url, dict(data or {})))
            if error:
                raise error
            return reply
    monkeypatch.setattr(httpx, "AsyncClient", Client)


def _run(coro):
    return asyncio.run(coro)


def test_off_without_both_keys(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    assert not captcha.enabled() and captcha.public_config() == {"site_key": ""}
    _run(captcha.verify(None, "login"))                       # off: nothing asked, nothing refused
    monkeypatch.setenv("TURNSTILE_SITE_KEY", PASS_SITE)       # one key alone is still off
    assert not captcha.enabled() and captcha.public_config() == {"site_key": ""}


def test_on_hands_out_only_the_site_key(on):
    assert captcha.enabled()
    cfg = captcha.public_config()
    assert cfg == {"site_key": PASS_SITE} and PASS_SECRET not in str(cfg)


@pytest.mark.parametrize("token", [None, "", "   ", "x" * 3000])
def test_missing_or_oversized_answer_is_refused(on, monkeypatch, token):
    seen = []
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True}), seen=seen)
    with pytest.raises(HTTPException) as ex:
        _run(captcha.verify(token, "signup"))
    assert ex.value.status_code == 400 and ex.value.detail == captcha.FAILED
    assert seen == []                                          # refused without asking Cloudflare


def test_good_answer_passes_and_sends_the_secret(on, monkeypatch):
    seen = []
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True}), seen=seen)
    _run(captcha.verify("XXXX.DUMMY.TOKEN.XXXX", "login"))
    assert seen and seen[0][0] == captcha.SITEVERIFY_URL
    assert seen[0][1] == {"secret": PASS_SECRET, "response": "XXXX.DUMMY.TOKEN.XXXX"}   # no user IP sent


@pytest.mark.parametrize("body", [{"success": False, "error-codes": ["invalid-input-response"]},
                                  {"success": "true"}, {}, ["success"]])
def test_rejected_answer_is_refused(on, monkeypatch, body):
    _fake_client(monkeypatch, reply=_Reply(200, body))
    with pytest.raises(HTTPException) as ex:
        _run(captcha.verify("token", "forgot_password"))
    assert ex.value.status_code == 400


def test_cloudflare_down_lets_the_request_through(on, monkeypatch):
    import httpx
    # The log call is recorded directly: another test in a full run can switch log capture off (caplog came back
    # empty in the 4 Nov full suite while the code was right).
    logged = []
    monkeypatch.setattr(captcha.logger, "warning", lambda msg, *a, **k: logged.append(msg % a if a else msg))
    _fake_client(monkeypatch, error=httpx.ConnectError("down"))
    _run(captcha.verify("token", "login"))
    _fake_client(monkeypatch, reply=_Reply(503, {}))
    _run(captcha.verify("token", "login"))
    assert len(logged) == 2 and all("CAPTCHA_UNREACHABLE" in m for m in logged)


def test_signup_and_login_refuse_before_touching_the_database(on, monkeypatch):
    from models.schemas import LoginRequest, SignupRequest
    from routes import auth_routes

    async def no_limit(_key):
        return None
    monkeypatch.setattr(auth_routes, "check_auth_rate_limit", no_limit)

    def no_db():
        raise AssertionError("the database was reached")
    monkeypatch.setattr(auth_routes, "get_pool", no_db)
    _fake_client(monkeypatch, reply=_Reply(200, {"success": False}))
    signup = SignupRequest(email="a@example.com", password="Passw0rd!", full_name="A B",
                           organization_name="Agency", acord_disclaimer_accepted=True)
    for call in (auth_routes.signup(signup, None),
                 auth_routes.login(LoginRequest(email="a@example.com", password="x"), None)):
        with pytest.raises(HTTPException) as ex:
            _run(call)
        assert ex.value.status_code == 400 and ex.value.detail == captcha.FAILED


def test_every_abusable_auth_route_checks_the_captcha():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "routes", "auth_routes.py")).read()
    for action in ("signup", "login", "resend_verification", "forgot_password"):
        assert re.search(rf'captcha\.verify\(.*"{action}"\)', src), action
    assert '@router.get("/captcha-config")' in src


# ── hard review, 3 Nov 2026: only a real outage lets a request through ─────────────────────────────────────

class _BadJson(_Reply):
    def json(self):
        raise ValueError("not json")


@pytest.mark.parametrize("reply", [_Reply(429, {}), _Reply(400, {"success": True}), _Reply(403, None),
                                   _BadJson(200, None)])
def test_anything_cloudflare_answers_that_is_not_a_pass_is_refused(on, monkeypatch, reply):
    _fake_client(monkeypatch, reply=reply)
    with pytest.raises(HTTPException) as ex:
        _run(captcha.verify("token", "login"))
    assert ex.value.status_code == 400


def test_a_timeout_is_an_outage_but_a_code_error_is_not(on, monkeypatch):
    import httpx
    _fake_client(monkeypatch, error=httpx.ReadTimeout("slow"))
    _run(captcha.verify("token", "login"))                               # outage: allowed
    _fake_client(monkeypatch, error=ValueError("bug"))
    with pytest.raises(HTTPException):
        _run(captcha.verify("token", "login"))                           # not an outage: refused


def test_a_bad_secret_is_logged_as_an_error(on, monkeypatch, caplog):
    import logging
    _fake_client(monkeypatch, reply=_Reply(200, {"success": False, "error-codes": ["invalid-input-secret"]}))
    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException):
        _run(captcha.verify("token", "signup"))
    assert any(r.levelno == logging.ERROR and "CAPTCHA_MISCONFIGURED" in r.getMessage() for r in caplog.records)


def test_an_answer_solved_on_another_screen_is_refused(on, monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x4AAAAreal-secret")      # a real key: the action must match exactly
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True, "action": "login"}))
    with pytest.raises(HTTPException):
        _run(captcha.verify("token", "signup"))
    _run(captcha.verify("token", "login"))
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True, "action": ""}))   # a widget drawn without one
    with pytest.raises(HTTPException):
        _run(captcha.verify("token", "signup"))
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", PASS_SECRET)               # Cloudflare's test key reports no action
    _run(captcha.verify("token", "signup"))


def test_the_site_it_was_solved_on_can_be_pinned(on, monkeypatch):
    monkeypatch.setenv("TURNSTILE_HOSTNAMES", "primble.ai, www.primble.ai")
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True, "action": "login", "hostname": "evil.example"}))
    with pytest.raises(HTTPException):
        _run(captcha.verify("token", "login"))
    _fake_client(monkeypatch, reply=_Reply(200, {"success": True, "action": "login", "hostname": "primble.ai"}))
    _run(captcha.verify("token", "login"))


def test_the_page_solves_each_screen_under_the_servers_action_name():
    page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "frontend", "src", "components", "auth", "AuthModal.jsx")).read()
    actions = set(re.findall(r'action="([a-z_]+)"', page)) | set(re.findall(r'"(signup|login)"', page))
    assert {"resend_verification", "forgot_password", "signup", "login"} <= actions
    assert 'action="resend"' not in page and 'action="forgot"' not in page
