"""Cross-account document alert (FW-2 - Brent, 3 Nov 2026: "a great idea"; STRIPE_LIVE_READINESS_2NOV2026.md).

The same document uploaded from SEVERAL ACCOUNTS is the signature of competitor probing and of free-package abuse
(one package per account, many accounts). Every uploaded document leaves a fingerprint at upload - hash only - in
its own table, so deleting the package (or the account) never hides it. When a document first arrives in an account
and another, unrelated account uploaded it before, the admins get one e-mail and an audit row. Nothing is blocked:
an agency's two producers, or a public sample, can legitimately share a file - the alert says who, so a person
judges.

What is stored: keyed hashes (HMAC-SHA256) of the document's READ text (whitespace / case insensitive - a renamed or
re-saved copy matches) and of its file bytes (a scanned copy whose OCR varies by a character still matches), the
account id and the first / last upload time. Never the text, the file name or a value. The key is
`DOCUMENT_FINGERPRINT_KEY`, else derived from `FIELD_ENCRYPTION_KEY`, so a leaked table cannot be used to test
whether a given document was uploaded.

Not counted as "another account":
- internal accounts: `ADMIN_EMAILS` plus `FINGERPRINT_IGNORE` (comma list of e-mails or @domains; default our own
  domains) - the team re-uploads its test packages from several accounts all day;
- an account on the uploader's own company e-mail domain (colleagues; personal mail domains never count as one
  company).

Switch: `DOCUMENT_FINGERPRINTS=0` turns it off. E-mails go to `ADMIN_EMAILS` + `FINGERPRINT_ALERT_EMAILS`, at most one
per uploading account per hour (later matches in that hour are still audited); the hour starts only when an e-mail
really went (it is claimed under a per-account lock, so two uploads at once send one e-mail). The e-mail names the
accounts, never the file (its name often carries the insured's). It is sent in the
background, so an upload never waits for it. Never raises - an upload never fails because of this.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS document_fingerprints (
        fingerprint  TEXT        NOT NULL,
        kind         TEXT        NOT NULL,
        user_id      TEXT        NOT NULL,
        first_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        uploads      INTEGER     NOT NULL DEFAULT 1,
        alerted_at   TIMESTAMPTZ,
        PRIMARY KEY (fingerprint, user_id)
    )
"""
# The primary key already serves "who uploaded this fingerprint"; this one serves "when was this account last
# alerted" (hard review, 3 Nov 2026).
INDEX_SQL = ("CREATE INDEX IF NOT EXISTS idx_document_fingerprints_user"
             " ON document_fingerprints (user_id, alerted_at)")

_MIN_TEXT = 200                     # a near-empty text (a blank page) would match unrelated uploads
_MAX_FILE_BYTES = 60 * 1024 * 1024
_ALERT_EVERY_SECONDS = 3600
_DEFAULT_IGNORE = "@astreait.com,@primble.ai,@primble.com"
_PUBLIC_MAIL = frozenset("""gmail.com googlemail.com yahoo.com ymail.com outlook.com hotmail.com live.com msn.com
icloud.com me.com mac.com aol.com proton.me protonmail.com gmx.com gmx.net zoho.com yandex.com mail.com
comcast.net att.net verizon.net sbcglobal.net""".split())


def enabled() -> bool:
    return (os.getenv("DOCUMENT_FINGERPRINTS", "1") or "").strip().lower() not in ("0", "false", "no", "off")


def _key() -> bytes:
    raw = os.getenv("DOCUMENT_FINGERPRINT_KEY") or os.getenv("FIELD_ENCRYPTION_KEY") or "primble"
    return hashlib.sha256(b"primble-document-fingerprint:" + raw.encode("utf-8", "replace")).digest()


def fingerprints(text: Any, file_bytes: Optional[bytes] = None) -> List[Tuple[str, str]]:
    """[(kind, keyed hash)] for a document: its read text (when long enough to be a real document) and its bytes."""
    out: List[Tuple[str, str]] = []
    norm = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if len(norm) >= _MIN_TEXT:
        out.append(("text", hmac.new(_key(), b"text:" + norm.encode("utf-8", "replace"), hashlib.sha256).hexdigest()))
    if file_bytes:
        out.append(("file", hmac.new(_key(), b"file:" + bytes(file_bytes), hashlib.sha256).hexdigest()))
    return out


def _domain(email: Any) -> str:
    e = str(email or "").strip().lower()
    return e.rsplit("@", 1)[1] if "@" in e else ""


def is_internal(email: Any) -> bool:
    e = str(email or "").strip().lower()
    if not e:
        return False
    try:
        from config.settings import ADMIN_EMAILS
        if e in {str(a).strip().lower() for a in (ADMIN_EMAILS or ())}:
            return True
    except Exception:                                         # noqa: BLE001
        pass
    for item in (os.getenv("FINGERPRINT_IGNORE", _DEFAULT_IGNORE) or "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item.startswith("@") and e.endswith(item):
            return True
        if item == e:
            return True
    return False


def same_company(a: Any, b: Any) -> bool:
    """Two accounts on one company e-mail domain (never a public mail domain)."""
    da, db = _domain(a), _domain(b)
    return bool(da) and da == db and da not in _PUBLIC_MAIL


def unrelated_accounts(me: Dict[str, Any], earlier: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The earlier accounts that count: not internal, not the uploader's colleagues."""
    mine = (me or {}).get("email")
    return [r for r in earlier if not is_internal(r.get("email")) and not same_company(mine, r.get("email"))]


def _file_fingerprint(path: Any) -> Optional[str]:
    """The keyed hash of a file's bytes, read 1 MB at a time - never the whole file in memory (review pass 2: a 50 MB
    upload held 100 MB, on a server already near its memory limit). Equal to `fingerprints(.., file_bytes)`'s."""
    try:
        if not path or os.path.getsize(path) > _MAX_FILE_BYTES:
            return None
        h = hmac.new(_key(), b"file:", hashlib.sha256)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:                                         # noqa: BLE001
        return None


def _fingerprints_of_upload(text: Any, path: Any) -> List[Tuple[str, str]]:
    fps = fingerprints(text)
    file_fp = _file_fingerprint(path)
    if file_fp:
        fps.append(("file", file_fp))
    return fps


async def record_upload(user_id: Any, display_name: str, text: Any, path: Any = None) -> None:
    """Fingerprint one uploaded document for this account, and alert when an unrelated account uploaded it before.
    `display_name` is accepted for the callers' sake and never stored, logged or e-mailed. Never raises."""
    if not enabled() or not user_id:
        return
    try:
        # Reading and hashing a large file is slow work: off the event loop (hard review, 3 Nov 2026).
        fps = await asyncio.to_thread(_fingerprints_of_upload, text, path)
        if not fps:
            return
        from config.database import get_pool
        uid = str(user_id)
        async with get_pool().acquire() as conn:
            me_row = await conn.fetchrow("SELECT id, email, organization_name FROM users WHERE id = $1", uid)
            me = dict(me_row) if me_row else {"id": uid, "email": "", "organization_name": ""}
            new_fps: List[str] = []
            for kind, fp in fps:
                inserted = await conn.fetchval(
                    """INSERT INTO document_fingerprints (fingerprint, kind, user_id)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (fingerprint, user_id)
                       DO UPDATE SET last_seen = NOW(), uploads = document_fingerprints.uploads + 1
                       RETURNING (xmax = 0)""", fp, kind, uid)
                if inserted:
                    new_fps.append(fp)
            if not new_fps or is_internal(me.get("email")):
                return
            rows = await conn.fetch(
                """SELECT f.user_id, MIN(f.first_seen) AS first_seen, u.email, u.organization_name
                     FROM document_fingerprints f LEFT JOIN users u ON u.id = f.user_id
                    WHERE f.fingerprint = ANY($1::text[]) AND f.user_id <> $2
                    GROUP BY f.user_id, u.email, u.organization_name""", new_fps, uid)
            others = unrelated_accounts(me, [dict(r) for r in rows])
            if not others:
                return
            # The account's hour is CLAIMED before the e-mail goes, under a per-account lock, so two uploads at
            # once (two tabs, the other worker, the next document of one upload) send one e-mail, not two (review
            # pass 2, 3 Nov 2026). A failed send gives the hour back (`_alert_admins`).
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "document_alert:" + uid)
                recent = await conn.fetchval(
                    "SELECT MAX(alerted_at) > NOW() - make_interval(secs => $2) FROM document_fingerprints"
                    " WHERE user_id = $1", uid, float(_ALERT_EVERY_SECONDS))
                if not recent:
                    await conn.execute(
                        "UPDATE document_fingerprints SET alerted_at = NOW()"
                        " WHERE user_id = $1 AND fingerprint = ANY($2::text[])", uid, new_fps)
        logger.warning("DOCUMENT_CROSS_ACCOUNT user=%s earlier_accounts=%d e-mail=%s",
                       uid, len(others), "skipped (sent within the hour)" if recent else "sending")
        if not recent:
            # Started BEFORE the audit write: once the hour is claimed nothing may stand between it and its e-mail
            # (review pass 3).
            task = asyncio.get_running_loop().create_task(_alert_admins(uid, me, others, new_fps))
            _PENDING.add(task)                                # held, or the loop may drop it mid-send
            task.add_done_callback(_PENDING.discard)
        await _audit(me, others, new_fps)
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("DOCUMENT_FINGERPRINT_FAILED %s", type(ex).__name__)


_PENDING: set = set()


async def drain(timeout: Optional[float] = None) -> None:
    """Wait for the alert e-mails still being sent (tests; the app's shutdown, before the pool closes)."""
    async def _all():
        while _PENDING:
            await asyncio.gather(*list(_PENDING), return_exceptions=True)
    try:
        await asyncio.wait_for(_all(), timeout)
    except asyncio.TimeoutError:
        logger.warning("DOCUMENT_FINGERPRINT_DRAIN_TIMEOUT pending=%d", len(_PENDING))


async def _alert_admins(uid: str, me: Dict[str, Any], others: List[Dict[str, Any]], fps: List[str]) -> None:
    """E-mail the admins. The hour was claimed before sending; when no e-mail went it is given back, so the next
    match alerts again."""
    try:
        if await _email_admins(me, others):
            return
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE document_fingerprints SET alerted_at = NULL WHERE user_id = $1 AND fingerprint = ANY($2::text[])",
                uid, fps)
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("DOCUMENT_FINGERPRINT_ALERT_FAILED %s", type(ex).__name__)


async def _audit(me: Dict[str, Any], others: List[Dict[str, Any]], fps: List[str]) -> None:
    try:
        from repositories.audit_repository import write_audit_log
        await write_audit_log(
            {"id": me.get("id"), "email": me.get("email") or "", "organization_name": me.get("organization_name") or ""},
            "document.cross_account_upload",
            file_checksum=fps[0][:32],
            unresolved_issues=[{"earlier_account": o.get("user_id"),
                                "first_seen": str(o.get("first_seen") or "")} for o in others])
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("DOCUMENT_FINGERPRINT_AUDIT_FAILED %s", type(ex).__name__)


def alert_recipients() -> List[str]:
    out: List[str] = []
    try:
        from config.settings import ADMIN_EMAILS
        out.extend(sorted(str(a).strip() for a in (ADMIN_EMAILS or ()) if str(a).strip()))
    except Exception:                                         # noqa: BLE001
        pass
    for e in (os.getenv("FINGERPRINT_ALERT_EMAILS") or "").split(","):
        e = e.strip()
        if e and e.lower() not in {x.lower() for x in out}:
            out.append(e)
    return out


def alert_text(me: Dict[str, Any], others: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(subject, plain text) of the admins' e-mail. Accounts only - never the file's name or its content."""
    who = f"{me.get('email') or me.get('id')} ({me.get('organization_name') or 'no organisation'})"
    lines = [f"- {o.get('email') or 'a deleted account'} ({o.get('organization_name') or 'no organisation'}),"
             f" first uploaded {str(o.get('first_seen') or '')[:16]}" for o in others]
    subject = "Primble: a document was uploaded from more than one account"
    body = (f"The account {who} uploaded a document that "
            f"{'another account' if len(others) == 1 else f'{len(others)} other accounts'} uploaded before:\n"
            + "\n".join(lines)
            + "\n\nNothing was blocked. Two producers at one agency, or a shared sample, can explain it; several new "
              "accounts uploading the same file can mean competitor probing or free-package abuse.\n")
    return subject, body


async def _email_admins(me: Dict[str, Any], others: List[Dict[str, Any]]) -> bool:
    """True when at least one admin was e-mailed."""
    to = alert_recipients()
    if not to:
        return False
    subject, body = alert_text(me, others)
    import html as _html
    body_html = "<p>" + _html.escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    sent = False
    from services.email_service import _send_generic_email
    for addr in to:
        try:
            sent = bool(await asyncio.to_thread(_send_generic_email, addr, subject, body, body_html)) or sent
        except Exception as ex:                               # noqa: BLE001
            logger.warning("DOCUMENT_FINGERPRINT_EMAIL_FAILED %s", type(ex).__name__)
    return sent
