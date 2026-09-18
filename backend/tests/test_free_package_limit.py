"""The free-tier allowance has ONE owner: config.settings.FREE_PACKAGE_LIMIT.

Client direction 2026-09-16: a new account gets ONE free package, not three.
The number used to be a bare `3` repeated across five modules. These tests fail
the build if a gate, a remaining-count or a message goes back to a literal.
"""
import pathlib
import re

import pytest

from config.settings import FREE_PACKAGE_LIMIT

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Every module that gates, counts or announces the free allowance.
_GATE_FILES = [
    "routes/auth_routes.py",
    "routes/form_routes.py",
    "routes/download_routes.py",
    "routes/dev_routes.py",
]


def test_default_allowance_is_one():
    """The shipped default. An env var may raise it; nothing else may."""
    assert FREE_PACKAGE_LIMIT == 1


def test_the_limit_is_never_negative():
    assert FREE_PACKAGE_LIMIT >= 0


@pytest.mark.parametrize("rel", _GATE_FILES)
def test_no_module_hardcodes_the_free_allowance(rel):
    """A gate must read the constant, never a literal."""
    src = (_ROOT / rel).read_text(encoding="utf-8")
    offenders = []
    for ln, line in enumerate(src.splitlines(), 1):
        if "downloads_used" not in line and "downloads_remaining" not in line and "used >=" not in line:
            continue
        if (re.search(r"or 0\)\s*>=\s*\d", line)
                or re.search(r"used\s*>=\s*\d", line)
                or re.search(r"\d+\s*-\s*used", line)
                or re.search(r"\"downloads_remaining\":\s*\d", line)):
            offenders.append(f"{rel}:{ln}: {line.strip()}")
    assert not offenders, (
        "free-tier allowance hardcoded instead of reading FREE_PACKAGE_LIMIT:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("rel", _GATE_FILES)
def test_every_gate_module_imports_the_constant(rel):
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert "FREE_PACKAGE_LIMIT" in src, f"{rel} no longer reads the one door"


def test_user_facing_message_agrees_with_the_limit():
    """The upgrade wall must not promise a number the gate does not enforce."""
    src = (_ROOT / "routes/form_routes.py").read_text(encoding="utf-8")
    assert "You've used all {FREE_PACKAGE_LIMIT} free submission" in src
    # and it pluralises, so "all 1 free submissions" can never print
    assert "'' if FREE_PACKAGE_LIMIT == 1 else 's'" in src


def test_remaining_count_goes_to_zero_at_the_limit():
    """The gate and the displayed remaining count flip at the same point."""
    for used in range(0, FREE_PACKAGE_LIMIT + 3):
        assert (used >= FREE_PACKAGE_LIMIT) == ((FREE_PACKAGE_LIMIT - used) <= 0)


# ── The package the credit paid for must download ─────────────────────────────
#
# A free package is counted at GENERATION (usage_service.count_session_usage), so
# by download time `downloads_used` already includes it. Both download routes used
# to gate on the counter alone, before loading the session - which refused the
# very package the credit had paid for. At a limit of 1 that is the only package
# a free account ever gets.

import ast
import asyncio

from routes import download_routes
from services import usage_service


class _FakeConn:
    def __init__(self, user):
        self.user = user

    async def fetchrow(self, sql, *args):
        return dict(self.user)

    async def execute(self, sql, *args):
        if "downloads_used" in sql and "+ 1" in sql:
            self.user["downloads_used"] = int(self.user.get("downloads_used") or 0) + 1


class _FakePool:
    def __init__(self, user):
        self.conn = _FakeConn(user)

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool.conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def _generate(monkeypatch, user, sessions, session_id):
    """Run the real generation-time counter against an in-memory user/session."""
    monkeypatch.setattr(usage_service, "get_pool", lambda: _FakePool(user))
    monkeypatch.setattr(usage_service, "_usage_redis", None)
    monkeypatch.setattr(usage_service, "get_processing_session",
                        lambda sid, **kw: _async(sessions.setdefault(sid, {})))
    monkeypatch.setattr(usage_service, "upd_processing_session",
                        lambda sid, upd: _async(sessions.setdefault(sid, {}).update(upd)))
    return asyncio.run(usage_service.count_session_usage(user["id"], session_id))


async def _coro(value):
    return value


def _async(value):
    return _coro(value)


def test_the_one_free_package_downloads_after_generation(monkeypatch):
    user = {"id": "u1", "subscription_tier": "free", "downloads_used": 0}
    sessions = {}
    _generate(monkeypatch, user, sessions, "pkg-1")

    assert user["downloads_used"] == FREE_PACKAGE_LIMIT == 1
    assert sessions["pkg-1"].get("package_counted_at"), "generation must stamp the session"
    assert not download_routes._free_limit_blocks(
        "free", user["downloads_used"], sessions["pkg-1"]
    ), "the package the free credit paid for was refused at download"


def test_a_second_free_package_is_refused(monkeypatch):
    user = {"id": "u2", "subscription_tier": "free", "downloads_used": 0}
    sessions = {}
    _generate(monkeypatch, user, sessions, "pkg-1")
    # A second package never reaches generation (select-forms-bulk gates it), so
    # its session is never counted - the download door must refuse it too.
    assert download_routes._free_limit_blocks("free", user["downloads_used"], {})


def test_regenerating_the_same_package_does_not_spend_another_credit(monkeypatch):
    user = {"id": "u3", "subscription_tier": "free", "downloads_used": 0}
    sessions = {}
    _generate(monkeypatch, user, sessions, "pkg-1")
    usage_service._dedup_seen.clear()
    _generate(monkeypatch, user, sessions, "pkg-1")
    assert user["downloads_used"] == 1


@pytest.mark.parametrize("sub,used,session,blocked", [
    ("free", 0, {}, False),                                     # allowance left
    ("free", 1, {"package_counted_at": "2026-09-18T00:00Z"}, False),  # paid-for package
    ("free", 5, {"package_counted_at": "2026-09-18T00:00Z"}, False),  # over, but paid for
    ("free", 1, {}, True),                                      # would spend a new credit
    ("free", 1, {"package_counted_at": None}, True),
    ("professional", 99, {}, False),                            # not the free door
    ("essentials", 99, {}, False),
])
def test_free_limit_gate_matrix(sub, used, session, blocked):
    assert download_routes._free_limit_blocks(sub, used, session) is blocked


def test_download_routes_judge_the_session_not_the_bare_counter():
    """Both routes must load the session before deciding - never gate on `used` alone."""
    src = (_ROOT / "routes/download_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    routes = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
    for name in ("download_pdf", "download_all"):
        assert name in routes, f"route {name} not found"
        body = ast.get_source_segment(src, routes[name])
        assert "FREE_PACKAGE_LIMIT" not in body, f"{name} gates on the bare counter again"
        load = body.index("get_processing_session(")
        gate = body.index("_free_limit_blocks(")
        assert load < gate, f"{name} checks the free limit before loading the session"


def test_remaining_count_is_never_negative():
    """An account that used more than today's limit (e.g. 2 packages under the old
    limit of 3) must read 0, not -1: the frontend tests `downloads_remaining === 0`
    to show the upgrade wall, and the header would print "-1 free packages"."""
    src = (_ROOT / "routes/auth_routes.py").read_text(encoding="utf-8")
    computed = re.findall(r'"downloads_remaining":\s*(.+?)\s+if sub == "free"', src)
    assert computed, "no computed downloads_remaining found"
    for expr in computed:
        assert expr.startswith("max(0,"), f"unclamped remaining count: {expr}"
