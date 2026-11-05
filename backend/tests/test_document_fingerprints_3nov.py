"""Cross-account document alert (FW-2, 3 Nov 2026, services/document_fingerprints.py). An in-memory stand-in for the
table - no database, no e-mail is really sent."""
import asyncio
import os

import pytest

from services import document_fingerprints as F

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = "DECLARATIONS - Named Insured: CHOICE ELECTRIC LLC - Policy CPP 123 - " * 10


class _Clock:
    t = 1000.0


class _Conn:
    def __init__(self, db):
        self.db = db

    async def fetchrow(self, sql, uid):
        return self.db["users"].get(uid)

    async def fetchval(self, sql, *args):
        rows = self.db["fps"]
        if sql.lstrip().startswith("INSERT INTO document_fingerprints"):
            fp, kind, uid = args
            if (fp, uid) in rows:
                rows[(fp, uid)]["uploads"] += 1
                return False
            rows[(fp, uid)] = {"fp": fp, "user_id": uid, "first_seen": _Clock.t, "alerted_at": None, "uploads": 1}
            return True
        if "MAX(alerted_at)" in sql:
            uid, secs = args
            times = [r["alerted_at"] for r in rows.values() if r["user_id"] == uid and r["alerted_at"] is not None]
            return (bool(times) and _Clock.t - max(times) < secs) or None
        raise AssertionError(sql)

    async def fetch(self, sql, fps, uid):
        out = {}
        for r in self.db["fps"].values():
            if r["fp"] in fps and r["user_id"] != uid:
                u = self.db["users"].get(r["user_id"]) or {}
                o = out.setdefault(r["user_id"], {"user_id": r["user_id"], "first_seen": r["first_seen"],
                                                   "email": u.get("email"), "organization_name": u.get("organization_name")})
                o["first_seen"] = min(o["first_seen"], r["first_seen"])
        return list(out.values())

    async def execute(self, sql, *args):
        if "pg_advisory_xact_lock" in sql:
            self.db["locks"].append(args[0])
            return
        uid, fps = args
        value = None if "alerted_at = NULL" in sql else _Clock.t
        for r in self.db["fps"].values():
            if r["user_id"] == uid and r["fp"] in fps:
                r["alerted_at"] = value

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False
        return _Tx()


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        conn = _Conn(self.db)

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()


@pytest.fixture
def world(monkeypatch):
    import config.database as cdb
    import config.settings as cs
    import repositories.audit_repository as ar
    import services.email_service as es
    db = {"users": {
        "a": {"id": "a", "email": "joe@gmail.com", "organization_name": "Joe Agency"},
        "b": {"id": "b", "email": "kim@rivalbrokers.com", "organization_name": "Rival Brokers"},
        "b2": {"id": "b2", "email": "lee@rivalbrokers.com", "organization_name": "Rival Brokers"},
        "c": {"id": "c", "email": "new1@yahoo.com", "organization_name": "Test"},
        "me": {"id": "me", "email": "vinaysharma@astreait.com", "organization_name": "Primble"},
    }, "fps": {}, "mails": [], "audit": [], "locks": []}
    monkeypatch.setattr(cdb, "get_pool", lambda: _Pool(db))
    monkeypatch.setattr(cs, "ADMIN_EMAILS", {"vinaysharma@astreait.com"})
    monkeypatch.setenv("FINGERPRINT_ALERT_EMAILS", "brent@example.com")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k1")
    monkeypatch.delenv("DOCUMENT_FINGERPRINTS", raising=False)
    monkeypatch.delenv("FINGERPRINT_IGNORE", raising=False)
    monkeypatch.setattr(es, "_send_generic_email", lambda to, s, t, h: db["mails"].append((to, s, t)) or True)

    async def audit(user, action, **kw):
        db["audit"].append((user.get("id"), action, kw))
    monkeypatch.setattr(ar, "write_audit_log", audit)
    _Clock.t = 1000.0
    return db


def up(uid, text=DOC, name="dec.pdf"):
    async def go():
        await F.record_upload(uid, name, text, None)
        await F.drain()                                                    # the alert is sent in the background
    asyncio.run(go())


def test_fingerprint_reads_the_text_not_its_spacing_and_is_keyed(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k1")
    a = dict(F.fingerprints(DOC))
    b = dict(F.fingerprints("  " + DOC.upper().replace(" ", "\n  ") + "\t"))
    assert a["text"] == b["text"]
    assert F.fingerprints("too short") == []                               # a blank page is no identity
    assert dict(F.fingerprints(DOC, b"%PDF-1"))["file"]
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k2")
    assert dict(F.fingerprints(DOC))["text"] != a["text"]                  # keyed: no bare SHA-256 of the text
    assert DOC.strip()[:20].lower() not in a["text"]


def test_who_counts_as_another_account(monkeypatch):
    import config.settings as cs
    monkeypatch.setattr(cs, "ADMIN_EMAILS", {"boss@x.com"})
    monkeypatch.delenv("FINGERPRINT_IGNORE", raising=False)
    assert F.is_internal("boss@x.com") and F.is_internal("dev@astreait.com") and F.is_internal("a@primble.ai")
    assert not F.is_internal("joe@gmail.com") and not F.is_internal("")
    assert F.same_company("kim@rivalbrokers.com", "lee@rivalbrokers.com")
    assert not F.same_company("a@gmail.com", "b@gmail.com")                # a public mail domain is no company
    me = {"email": "kim@rivalbrokers.com"}
    earlier = [{"email": "lee@rivalbrokers.com"}, {"email": "dev@astreait.com"}, {"email": "joe@gmail.com"}]
    assert [r["email"] for r in F.unrelated_accounts(me, earlier)] == ["joe@gmail.com"]


def test_first_upload_is_quiet_an_unrelated_second_account_alerts_once(world):
    up("a")
    assert world["mails"] == [] and world["audit"] == []
    up("b")
    assert sorted(m[0] for m in world["mails"]) == ["brent@example.com", "vinaysharma@astreait.com"]
    subject, body = world["mails"][0][1], world["mails"][0][2]
    assert "more than one account" in subject
    assert "kim@rivalbrokers.com (Rival Brokers)" in body and "joe@gmail.com (Joe Agency)" in body
    assert "CHOICE" not in body                                            # never the document's content
    assert "dec.pdf" not in body                                           # nor its file name
    assert [a[1] for a in world["audit"]] == ["document.cross_account_upload"]
    up("b")                                                                # the same account again: quiet
    assert len(world["mails"]) == 2 and len(world["audit"]) == 1


def test_colleagues_and_internal_accounts_never_alert(world):
    up("b")
    up("b2")                                                               # same company domain
    up("me")                                                               # internal uploader
    assert world["mails"] == [] and world["audit"] == []
    world["fps"].clear()
    up("me")
    up("a")                                                                # only an internal account came before
    assert world["mails"] == []


def test_at_most_one_email_an_hour_per_account_but_every_match_is_audited(world):
    other = DOC.replace("CPP 123", "CPP 999")
    up("a")
    up("a", other)
    up("c")
    _Clock.t += 60
    up("c", other)                                                         # a second match within the hour
    assert len(world["mails"]) == 2 and len(world["audit"]) == 2
    _Clock.t += 3600
    third = DOC.replace("CPP 123", "CPP 777")
    up("a", third)
    up("c", third)                                                         # an hour later: e-mailed again
    assert len(world["mails"]) == 4


def test_off_switch_and_failures_never_break_an_upload(world, monkeypatch):
    monkeypatch.setenv("DOCUMENT_FINGERPRINTS", "0")
    up("a")
    assert world["fps"] == {}
    monkeypatch.delenv("DOCUMENT_FINGERPRINTS")
    import config.database as cdb

    def broken():
        raise RuntimeError("no database")
    monkeypatch.setattr(cdb, "get_pool", broken)
    up("a")                                                                # no exception


def test_every_upload_door_records_it_and_the_table_is_built_at_startup():
    pipe = open(os.path.join(BACKEND, "services", "extraction_pipeline.py")).read()
    door = pipe[pipe.index("async def extract_document("):]
    door = door[:door.index("\nasync def ") if "\nasync def " in door else len(door)]
    assert "await record_upload(user_id, display_name, text, path)" in door
    db = open(os.path.join(BACKEND, "config", "database.py")).read()
    assert "await conn.execute(_FP_TABLE)" in db and "await conn.execute(_FP_INDEX)" in db
    assert "PRIMARY KEY (fingerprint, user_id)" in F.TABLE_SQL


def test_a_failed_email_does_not_start_the_quiet_hour(world, monkeypatch):
    import services.email_service as es
    monkeypatch.setattr(es, "_send_generic_email", lambda to, s, t, h: False)
    up("a")
    up("c")
    assert all(r["alerted_at"] is None for r in world["fps"].values())    # nothing went: no quiet hour
    monkeypatch.setattr(es, "_send_generic_email", lambda to, s, t, h: world["mails"].append((to, s, t)) or True)
    up("c", DOC.replace("CPP 123", "CPP 555"))
    up("a", DOC.replace("CPP 123", "CPP 555"))                             # the next match is e-mailed
    assert len(world["mails"]) == 2


def test_hashing_runs_off_the_event_loop_and_the_account_index_exists():
    src = open(os.path.join(BACKEND, "services", "document_fingerprints.py")).read()
    assert "await asyncio.to_thread(_fingerprints_of_upload, text, path)" in src
    assert "(user_id, alerted_at)" in F.INDEX_SQL


def test_the_file_is_hashed_in_pieces_and_matches_the_whole_file_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k1")
    data = bytes(range(256)) * 9000                                         # ~2.3 MB, several pieces
    f = tmp_path / "dec.pdf"
    f.write_bytes(data)
    assert F._file_fingerprint(str(f)) == dict(F.fingerprints(DOC, data))["file"]
    assert F._file_fingerprint(str(tmp_path / "missing.pdf")) is None


def test_two_uploads_at_once_send_one_alert_under_the_accounts_lock(world):
    other = DOC.replace("CPP 123", "CPP 999")
    up("a")
    up("a", other)

    async def both():
        await asyncio.gather(F.record_upload("c", "x.pdf", DOC, None), F.record_upload("c", "y.pdf", other, None))
        await F.drain()
    asyncio.run(both())
    assert len(world["mails"]) == 2                                         # one alert (two admins), not two
    assert world["locks"] and set(world["locks"]) == {"document_alert:c"}
