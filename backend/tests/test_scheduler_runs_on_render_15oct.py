"""The daily jobs run from Render, exactly once, and survive a deploy (15 Oct 2026).

Until 15 Oct the jobs ran only from the owner's Mac. Render runs the API as
several processes at once (gunicorn workers, plus the old and new instance
during a deploy). The old start-up-only lock check left every process that lost
the race without jobs for life, so once the winner was replaced nobody ran
them. The lock is now asked before every run. The client-facing jobs (payment
follow-up, questionnaire reminder) always run; jobs that delete data need
SCHEDULER_CLEANUP_JOBS=true.
"""
import asyncio
from datetime import timezone
from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

if not hasattr(AsyncIOScheduler, "add_job"):
    pytest.skip("APScheduler is not installed here - a test stub stands in for it",
                allow_module_level=True)

import services.scheduler_service as ss

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_lock_held(monkeypatch):
    monkeypatch.setattr(ss, "_lock_conn", None)


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.last = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.conn.dead:
            raise RuntimeError("server closed the connection")
        self.conn.statements.append(sql)
        self.last = sql

    def fetchone(self):
        return (self.conn.grant,) if "pg_try_advisory_lock" in self.last else (1,)


class _FakeConn:
    def __init__(self, grant=True, dead=False):
        self.grant, self.dead = grant, dead
        self.closed, self.autocommit = False, False
        self.statements = []

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


# ── the lock connection ───────────────────────────────────────────────────────
def test_lock_uses_session_mode_on_supabases_transaction_pooler(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    monkeypatch.setattr(ss, "DATABASE_URL",
                        "postgresql://postgres.abc:s3cr%2Bet@aws-1-ap-northeast-1.pooler.supabase.com"
                        ":6543/postgres?sslmode=require")
    assert ss._lock_database_url() == (
        "postgresql://postgres.abc:s3cr%2Bet@aws-1-ap-northeast-1.pooler.supabase.com"
        ":5432/postgres?sslmode=require")


@pytest.mark.parametrize("url", [
    "postgresql://postgres.abc:pw@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres",
    "postgresql://user:pw@db.example.com:6543/app",
    "postgresql://user:pw@localhost/app",
    "",
])
def test_any_other_url_is_left_alone(monkeypatch, url):
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    monkeypatch.setattr(ss, "DATABASE_URL", url)
    assert ss._lock_database_url() == url


def test_the_direct_url_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://u:p@direct.example.com:5432/db")
    monkeypatch.setattr(ss, "DATABASE_URL", "postgresql://u:p@x.pooler.supabase.com:6543/db")
    assert ss._lock_database_url() == "postgresql://u:p@direct.example.com:5432/db"


# ── who runs the jobs ─────────────────────────────────────────────────────────
def test_a_live_lock_connection_keeps_the_jobs_here(monkeypatch):
    held = _FakeConn()
    monkeypatch.setattr(ss, "_lock_conn", held)
    monkeypatch.setattr(ss.psycopg2, "connect",
                        lambda *a, **k: pytest.fail("a live holder must not reconnect"))
    assert ss._holds_lock() is True
    assert held.statements == ["SELECT 1"]


def test_a_lost_connection_takes_the_lock_again(monkeypatch):
    dead, fresh = _FakeConn(dead=True), _FakeConn(grant=True)
    monkeypatch.setattr(ss, "_lock_conn", dead)
    monkeypatch.setattr(ss.psycopg2, "connect", lambda *a, **k: fresh)
    assert ss._holds_lock() is True
    assert dead.closed and ss._lock_conn is fresh
    assert fresh.autocommit is True, "an idle-in-transaction session can be killed, freeing the lock"


def test_another_holder_means_this_process_stands_by(monkeypatch):
    other = _FakeConn(grant=False)
    monkeypatch.setattr(ss.psycopg2, "connect", lambda *a, **k: other)
    assert ss._holds_lock() is False
    assert other.closed and ss._lock_conn is None


def test_an_unreachable_database_skips_the_run_without_raising(monkeypatch):
    def _down(*a, **k):
        raise OSError("could not connect")
    monkeypatch.setattr(ss.psycopg2, "connect", _down)
    assert ss._holds_lock() is False


def test_a_job_runs_only_where_the_lock_is_held(monkeypatch):
    ran = []

    async def job():
        ran.append(1)

    monkeypatch.setattr(ss, "_holds_lock", lambda: False)
    asyncio.run(ss._run_if_owner(job)())
    assert ran == []
    monkeypatch.setattr(ss, "_holds_lock", lambda: True)
    asyncio.run(ss._run_if_owner(job)())
    assert ran == [1]


def test_a_process_that_loses_the_race_still_starts_its_jobs(monkeypatch):
    """The defect: the loser returned before adding a single job, so after a
    deploy replaced the winner, nobody ran them."""
    fresh = AsyncIOScheduler(timezone="UTC")
    monkeypatch.setattr(ss, "scheduler", fresh)
    monkeypatch.setattr(ss, "_holds_lock", lambda: False)
    monkeypatch.delenv("SCHEDULER_CLEANUP_JOBS", raising=False)

    async def go():
        ss.start_scheduler()
        try:
            assert fresh.running
            assert {j.id for j in fresh.get_jobs()} == {"payment_lifecycle", "arq_auto_reminders"}
        finally:
            fresh.shutdown(wait=False)

    asyncio.run(go())


# ── which jobs, when ──────────────────────────────────────────────────────────
def test_client_jobs_always_cleanup_jobs_only_when_asked():
    s = AsyncIOScheduler(timezone="UTC")
    assert ss.register_jobs(s, cleanup=False) == ["payment_lifecycle", "arq_auto_reminders"]
    assert {j.id for j in s.get_jobs()} == {"payment_lifecycle", "arq_auto_reminders"}

    s = AsyncIOScheduler(timezone="UTC")
    ss.register_jobs(s, cleanup=True)
    assert {j.id for j in s.get_jobs()} == {
        "payment_lifecycle", "arq_auto_reminders",
        "retention_cleanup", "audit_log_retention", "facts_retention",
    }


def test_jobs_keep_their_hours_and_survive_a_busy_minute():
    s = AsyncIOScheduler(timezone="UTC")
    ss.register_jobs(s, cleanup=True)
    jobs = {j.id: j for j in s.get_jobs()}
    expected = {"payment_lifecycle": ("9", "0"), "arq_auto_reminders": ("10", "0"),
                "retention_cleanup": ("3", "0"), "audit_log_retention": ("3", "30"),
                "facts_retention": ("4", "0")}
    for job_id, (hour, minute) in expected.items():
        trig = str(jobs[job_id].trigger)
        assert f"hour='{hour}'" in trig and f"minute='{minute}'" in trig, trig
        job = jobs[job_id]
        assert job.misfire_grace_time == 3600 and job.coalesce is True and job.max_instances == 1


def test_cleanup_jobs_are_off_unless_asked(monkeypatch):
    monkeypatch.delenv("SCHEDULER_CLEANUP_JOBS", raising=False)
    assert ss._cleanup_jobs_enabled() is False
    monkeypatch.setenv("SCHEDULER_CLEANUP_JOBS", "yes")
    assert ss._cleanup_jobs_enabled() is False
    monkeypatch.setenv("SCHEDULER_CLEANUP_JOBS", "true")
    assert ss._cleanup_jobs_enabled() is True


def test_the_clock_is_pinned_and_a_bad_zone_never_breaks_the_import(monkeypatch):
    monkeypatch.delenv("SCHEDULER_TIMEZONE", raising=False)
    assert str(ss._scheduler_timezone()) == "America/New_York"
    monkeypatch.setenv("SCHEDULER_TIMEZONE", "Not/A_Zone")
    assert ss._scheduler_timezone() is timezone.utc


def test_the_api_never_runs_the_jobs_unless_told():
    src = (ROOT / "main.py").read_text()
    assert 'os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"' in src
    assert '"false" if _IS_PROD else "true"' not in src


# ── the clean-up takes a package's PDFs with it ───────────────────────────────
class _Conn:
    def __init__(self):
        self.sql = []

    async def execute(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        return "DELETE 0"

    def transaction(self):
        return _AsyncCM(self)


class _AsyncCM:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncCM(self.conn)


def test_retention_deletes_a_packages_pdfs_and_signing_requests_with_it(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(ss, "get_pool", lambda: _Pool(conn))
    asyncio.run(ss.run_retention_cleanup())

    def at(table):
        return next(i for i, s in enumerate(conn.sql) if s.startswith(f"DELETE FROM {table}"))

    pdf, sig, pkg = at("session_pdf_bytes"), at("signature_requests"), at("processing_sessions")
    assert pdf < pkg and sig < pkg, "the package must still exist while its PDFs are found"
    for i, alias in ((pdf, "b"), (sig, "s")):
        assert "IN (SELECT id FROM processing_sessions WHERE updated_at < $1)" in conn.sql[i]
        assert f"NOT EXISTS (SELECT 1 FROM processing_sessions p WHERE p.id = {alias}.session_id)" in conn.sql[i]
