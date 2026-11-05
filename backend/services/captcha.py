"""Login / sign-up captcha - Cloudflare Turnstile (3 Nov 2026, OPEN_ITEMS "V2 roadmap: captcha").

Guards the routes a bot can abuse without an account: sign-up (fake accounts each get a free package - OCR + AI
cost - and a verification e-mail to any address), resend-verification and forgot-password (e-mail bombing), and
e-mail / password login (credential stuffing). Google sign-in is screened by Google; the code-entry routes need a
6-digit code and are rate-limited.

Switches (both on the SERVER - the page reads the site key from `GET /api/auth/captcha-config`, so the two halves
can never disagree):
    TURNSTILE_SITE_KEY    public key the widget is drawn with
    TURNSTILE_SECRET_KEY  private key the answer is checked with
Both set = captcha required. Either missing = captcha off (today's behaviour). For local tests, Cloudflare's own
test keys: site 1x00000000000000000000AA + secret 1x0000000000000000000000000000000AA always pass; secret
2x0000000000000000000000000000000AA always fails.

A missing or rejected answer is refused (400), and so is an answer solved for another action (a login answer
replayed on sign-up). Only when Cloudflare itself cannot be reached - no connection, a timeout, a 5xx - is the
request let through, logged `CAPTCHA_UNREACHABLE`: a Cloudflare outage must not lock every user out, and an attacker
cannot cause one. Anything else Cloudflare answers (a 4xx, a 429, a reply that is not JSON) is refused (hard review,
3 Nov 2026), and a key Cloudflare calls invalid is logged `CAPTCHA_MISCONFIGURED` at ERROR - every sign-in is
refused until the keys are fixed.
The user's IP is not sent: behind Render's proxy `request.client.host` is the proxy's (OPEN_ITEMS), and Turnstile
treats `remoteip` as optional.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
FAILED = "Please complete the security check and try again."
_MAX_TOKEN = 2048              # Turnstile answers are well under this


def site_key() -> str:
    return (os.getenv("TURNSTILE_SITE_KEY") or "").strip()


def _secret() -> str:
    return (os.getenv("TURNSTILE_SECRET_KEY") or "").strip()


def enabled() -> bool:
    return bool(site_key() and _secret())


def public_config() -> dict:
    """What the sign-in page needs: the site key when the captcha is on, else an empty string."""
    return {"site_key": site_key() if enabled() else ""}


async def verify(token: Optional[str], action: str) -> None:
    """Return when the answer is good (or the captcha is off, or Cloudflare cannot be reached); raise 400 when the
    captcha is on and the answer is missing or rejected."""
    if not enabled():
        return
    token = str(token or "").strip()
    if not token or len(token) > _MAX_TOKEN:
        logger.info("CAPTCHA_MISSING action=%s", action)
        raise HTTPException(400, FAILED)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            reply = await client.post(SITEVERIFY_URL, data={"secret": _secret(), "response": token})
    except httpx.TransportError as ex:                       # no connection, a timeout: Cloudflare unreachable
        logger.warning("CAPTCHA_UNREACHABLE action=%s error=%s - request allowed", action, type(ex).__name__)
        return
    except Exception as ex:                                  # noqa: BLE001 - anything else is not an outage
        logger.warning("CAPTCHA_ERROR action=%s error=%s - refused", action, type(ex).__name__)
        raise HTTPException(400, FAILED)
    if reply.status_code >= 500:
        logger.warning("CAPTCHA_UNREACHABLE action=%s status=%s - request allowed", action, reply.status_code)
        return
    try:
        body = reply.json()
    except Exception:                                        # noqa: BLE001
        body = None
    if reply.status_code != 200 or not isinstance(body, dict) or body.get("success") is not True:
        codes = body.get("error-codes") if isinstance(body, dict) else None
        if isinstance(codes, list) and {"invalid-input-secret", "missing-input-secret"} & {str(c) for c in codes}:
            logger.error("CAPTCHA_MISCONFIGURED action=%s codes=%s - check TURNSTILE_SECRET_KEY", action, codes)
        else:
            logger.info("CAPTCHA_REJECTED action=%s status=%s codes=%s", action, reply.status_code, codes)
        raise HTTPException(400, FAILED)
    # Our widgets always name their action, so the answer must carry THIS action - an answer from a widget drawn
    # without one, or for another screen, is refused (review pass 3). Cloudflare's always-pass TEST secret reports no
    # real action, so it is exempt. `TURNSTILE_HOSTNAMES` (comma list), when set, also pins the site it was solved on.
    solved_for = str(body.get("action") or "")
    if solved_for != action and not _secret().startswith(("1x0000000000", "2x0000000000", "3x0000000000")):
        logger.info("CAPTCHA_WRONG_ACTION action=%s solved_for=%s", action, solved_for[:40])
        raise HTTPException(400, FAILED)
    hosts = {h.strip().lower() for h in (os.getenv("TURNSTILE_HOSTNAMES") or "").split(",") if h.strip()}
    if hosts and str(body.get("hostname") or "").lower() not in hosts:
        logger.info("CAPTCHA_WRONG_HOST action=%s", action)
        raise HTTPException(400, FAILED)
