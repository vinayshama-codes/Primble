"""applicant_signing.py - the applicant signs the generated forms through a link
(Orbin item 14, client 22 Sep: "How is the applicant (not producer) supposed to
sign these forms?"; owner, 1 Oct 2026: built in, the same draw-or-upload pad
the producer uses).

The flow:
1. The producer sends a signature request for the generated forms that carry an
   applicant signature line (signature_boxes.applicant_signature_lines). One
   live request per package: a new one replaces any still pending.
2. The client opens the link, reads each filled form (read-only PDF), ticks the
   consent, types their name and signs by drawing or uploading an image.
3. The signature is checked (a real PNG / JPEG, a sane size, not blank),
   trimmed to its ink, stored ENCRYPTED, and recorded on each form with the
   fingerprint of what the client reviewed (signature_boxes.form_fingerprint).
   Every render then paints it on the applicant's signature lines and dates
   them - until any value on that form changes, when the producer is told to
   send for signature again.

Not a questionnaire answer: the receipt counts, the "N of M questions" summary
and the answer pipeline never see it (an image cannot ride the 500-character
answer clamp, and a signature is not a question).
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services import signature_boxes as sb

logger = logging.getLogger(__name__)

REQUEST_DAYS = 7
STATUS_PENDING = "pending"

# The signature rides the client questionnaire as ONE question (owner, 1 Oct
# 2026: "send it as a question along with other questions"). Its answer is this
# marker, written only once the signature is really stored; the image itself
# travels on its own endpoint (an answer is clamped to 500 characters).
SIGNATURE_FIELD = "__applicant_signature__"
SIGNATURE_FIELD_TYPE = "signature"
SIGNED_ANSWER = "__SIGNED__"
STATUS_SIGNED = "signed"
STATUS_REPLACED = "replaced"          # a newer request for the same package

CONSENT_TEXT = (
    "I have reviewed these forms. The information in them is true, correct and "
    "complete to the best of my knowledge, and I sign them as the applicant."
)

MAX_BODY_BYTES = 3_500_000            # the sign request, image included
MAX_IMAGE_BYTES = 2_000_000           # the decoded image
MAX_IMAGE_SIDE = 4000                 # pixels, either side, before trimming
_OUT_MAX_WIDTH = 1600                 # what is stored, after trimming
_INK_THRESHOLD = 235                  # 0-255 grey: darker than this is ink
_PAD = 8                              # pixels kept around the ink

_TOKEN_RE = re.compile(r"^[a-f0-9]{64}$")
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg);base64,", re.IGNORECASE)
_NAME_BAD = re.compile(r"[<>{}\\]")
_MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}


class SigningError(ValueError):
    """A refusal the signer can act on: `code` for the screen, `message` in
    plain words, `status` for the HTTP reply."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ── Pure checks ───────────────────────────────────────────────────────────────

def valid_token(token: Any) -> bool:
    return isinstance(token, str) and bool(_TOKEN_RE.match(token))


def new_token() -> str:
    return secrets.token_hex(32)


def clean_signer_name(raw: Any) -> str:
    """The signer's typed full name: 2-100 characters, at least one letter, no
    markup. Raises SigningError."""
    name = " ".join(str(raw or "").split())
    if len(name) < 2 or not any(ch.isalpha() for ch in name):
        raise SigningError("name", "Type your full name.")
    if len(name) > 100 or _NAME_BAD.search(name):
        raise SigningError("name", "Type your full name using letters only.")
    return name


def normalize_signature_image(data_url: Any) -> str:
    """A PNG data URL of the signature's ink, from what the pad drew or the
    signer uploaded. Raises SigningError for anything that is not a real,
    reasonably sized PNG / JPEG with something drawn on it."""
    from PIL import Image, ImageOps

    text = str(data_url or "").strip()
    m = _DATA_URL_RE.match(text)
    if not m:
        raise SigningError("image", "Draw your signature, or upload a PNG or JPG picture of it.")
    try:
        raw = base64.b64decode(text[m.end():], validate=True)
    except (binascii.Error, ValueError):
        raise SigningError("image", "That picture could not be read. Try drawing your signature instead.")
    if not raw:
        raise SigningError("image", "Draw your signature, or upload a PNG or JPG picture of it.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise SigningError("image", "That picture is too large. Use one under 2 MB.")
    kind = "png" if raw.startswith(_MAGIC["png"]) else "jpeg" if raw.startswith(_MAGIC["jpeg"]) else None
    if kind is None:
        raise SigningError("image", "Only PNG or JPG pictures can be used.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            w, h = probe.size
            if w < 1 or h < 1 or w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE:
                raise SigningError("image", "That picture is too large. Use one under 4000 pixels wide.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            rgba = im.convert("RGBA")
    except SigningError:
        raise
    except Exception:
        raise SigningError("image", "That picture could not be read. Try drawing your signature instead.")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.split()[3])
    grey = flat.convert("L")
    ink = grey.point(lambda v: 255 if v < _INK_THRESHOLD else 0)
    box = ink.getbbox()
    if not box:
        raise SigningError("image", "The signature is empty. Draw your signature first.")
    x0, y0, x1, y1 = box
    crop = flat.crop((max(0, x0 - _PAD), max(0, y0 - _PAD),
                      min(flat.width, x1 + _PAD), min(flat.height, y1 + _PAD)))
    if crop.width > _OUT_MAX_WIDTH:
        crop = crop.resize((_OUT_MAX_WIDTH, max(1, round(crop.height * _OUT_MAX_WIDTH / crop.width))))
    out = io.BytesIO()
    crop.save(out, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def signing_date(now: Optional[datetime] = None, tz_offset_minutes: Any = None) -> str:
    """MM/DD/YYYY at the signer's location: the server's clock, shifted by the
    browser's UTC offset (bounded to a real one, -14h..+14h). The forms' own
    date format."""
    now = now or datetime.now(timezone.utc)
    try:
        offset = int(tz_offset_minutes)
    except (TypeError, ValueError):
        offset = 0
    offset = max(-14 * 60, min(14 * 60, offset))
    return (now + timedelta(minutes=offset)).strftime("%m/%d/%Y")


def _expired(row: dict, now: Optional[datetime] = None) -> bool:
    try:
        exp = datetime.fromisoformat(str(row.get("expires_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) > exp


def form_label(form_id: str) -> str:
    return str(form_id or "").replace("_", " ").strip()


def _form_order(proc_session: dict) -> List[str]:
    generated = proc_session.get("generated_forms") or {}
    order = [f for f in (proc_session.get("selected_form_ids") or []) if f in generated]
    return order + [f for f in generated if f not in order]


def signable_form_ids(proc_session: Any) -> List[str]:
    """The generated forms the applicant signs, in the producer's order: those
    whose printed form has an applicant signature line."""
    if not isinstance(proc_session, dict):
        return []
    generated = proc_session.get("generated_forms") or {}
    out = []
    for fid in _form_order(proc_session):
        tpl = sb.template_path_for(generated.get(fid) or {})
        if tpl and sb.applicant_signature_lines(tpl):
            out.append(fid)
    return out


def signature_question(proc_session: Any) -> Optional[dict]:
    """The questionnaire question that asks the applicant to sign the
    generated forms that carry an applicant line - None when no form does.
    Pre-ticked like the critical questions (owner, 1 Oct night)."""
    from services.question_classifier import TOPIC_APPLICANT, TOPIC_LABELS
    forms = signable_form_ids(proc_session)
    if not forms:
        return None
    labels = ", ".join(form_label(f) for f in forms)
    return {
        "field_name": SIGNATURE_FIELD,
        "question": "Please sign your insurance application.",
        "hint": f"Draw your signature or upload a picture of it. It goes on the applicant's signature line of: {labels}.",
        "forms": labels[:100],
        "form_ids": forms,
        "field_type": SIGNATURE_FIELD_TYPE,
        "audience": "client",
        "priority": "important",
        "bucket": "client",
        "bucket_label": "Client",
        "topic_group": TOPIC_APPLICANT,
        "topic_label": TOPIC_LABELS[TOPIC_APPLICANT],
        "escalatable_to_client": False,
        "force_preselect": True,
        "score_impact": {"sqs": False, "form_completion": True,
                         "submission_readiness": True, "hard_stop_resolution": False},
    }


def is_signature_question(q: Any) -> bool:
    return isinstance(q, dict) and q.get("field_type") == SIGNATURE_FIELD_TYPE


def form_versions(proc_session: dict, form_ids: Iterable[str]) -> Dict[str, str]:
    """Each form's fingerprint as it stands - what the client reviews."""
    generated = proc_session.get("generated_forms") or {}
    out = {}
    for fid in form_ids or []:
        gen = generated.get(fid)
        if isinstance(gen, dict):
            schema = gen.get("schema") if isinstance(gen.get("schema"), dict) else None
            out[fid] = sb.form_fingerprint(sb._field_data_of(gen), schema)
    return out


def form_statuses(proc_session: Any) -> List[dict]:
    """For the producer: each signable form and where its applicant signature
    stands - "signed" (with who and when), "stale" (the form changed after
    signing - send for signature again) or "unsigned"."""
    out = []
    generated = (proc_session or {}).get("generated_forms") or {}
    for fid in signable_form_ids(proc_session):
        gen = generated.get(fid) or {}
        state = sb.applicant_signature_state(gen) or "unsigned"
        # "Signed" only when the render can paint it: a record whose image this
        # server cannot read (another key, a rotation) prints blank - send again.
        if state == sb.STATE_SIGNED and sb.applicant_signature_for(proc_session, fid) is None:
            state = sb.STATE_STALE
        meta = gen.get(sb.APPLICANT_SIGNATURE_KEY) if state != "unsigned" else None
        out.append({
            "form_id": fid, "label": form_label(fid), "state": state,
            "signed_at": (meta or {}).get("signed_at"),
            "signed_date": (meta or {}).get("signed_date"),
            "signer_name": (meta or {}).get("signer_name"),
        })
    return out


def signed_form_updates(proc_session: dict, request_id: str, versions: Dict[str, str],
                        signer_name: str, signed_at: str, signed_date: str) -> dict:
    """The per-form session write for a signature: the record on each form, and
    the cache invalidated so the next render paints it."""
    updates = {}
    for fid, fingerprint in versions.items():
        updates[fid] = {
            sb.APPLICANT_SIGNATURE_KEY: {
                "request_id": request_id, "fingerprint": fingerprint,
                "signed_at": signed_at, "signed_date": signed_date, "signer_name": signer_name,
            },
            "_pdf_cache_hash": "",
            sb.APPLICANT_RENDER_KEY: None,
        }
    return updates


def images_after(proc_session: dict, request_id: str, encrypted: str) -> dict:
    """The session's encrypted signature images after this one is added. None
    is retired: a writer that loaded the session before this signing can put an
    older form record back, and its image must still be readable (a record
    whose image is gone would read "signed" and print blank)."""
    images = dict(proc_session.get(sb.APPLICANT_IMAGES_KEY) or {})
    images[request_id] = encrypted
    return images


# ── Storage ───────────────────────────────────────────────────────────────────

def _decode_row(row: Any) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    for key in ("form_ids", "form_versions"):
        v = d.get(key)
        if isinstance(v, str):
            try:
                d[key] = json.loads(v)
            except ValueError:
                d[key] = None
    return d


async def create_request(session_id: str, user_id: str, email: str, client_name: str,
                         form_ids: List[str]) -> dict:
    from config.database import get_pool
    req_id = str(uuid.uuid4())
    token = new_token()
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=REQUEST_DAYS)).isoformat()
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            # One live request per package: the newest link is the one to sign.
            await conn.execute(
                "UPDATE signature_requests SET status = $1 WHERE session_id = $2 AND status = $3",
                STATUS_REPLACED, session_id, STATUS_PENDING)
            await conn.execute(
                "INSERT INTO signature_requests (id, session_id, user_id, token, email, client_name,"
                " status, form_ids, expires_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                req_id, session_id, str(user_id), token, email, client_name or "",
                STATUS_PENDING, list(form_ids), expires, now.isoformat())
    return {"id": req_id, "token": token, "expires_at": expires}


async def get_by_token(token: str) -> Optional[dict]:
    from config.database import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM signature_requests WHERE token = $1", token)
    return _decode_row(row)


async def requests_for_session(session_id: str, user_id: str) -> List[dict]:
    from config.database import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, token, email, client_name, status, form_ids, created_at, expires_at,"
            " viewed_at, signed_at, signer_name FROM signature_requests"
            " WHERE session_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT 20",
            session_id, str(user_id))
    out = []
    for r in rows:
        d = _decode_row(r)
        d["expired"] = d.get("status") == STATUS_PENDING and _expired(d)
        out.append(d)
    return out


async def mark_viewed(token: str) -> None:
    from config.database import get_pool
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE signature_requests SET viewed_at = $1 WHERE token = $2 AND viewed_at IS NULL",
            datetime.now(timezone.utc).isoformat(), token)


def check_open(row: Optional[dict]) -> dict:
    """The request a link names, if it can still be signed. Raises SigningError."""
    if not row:
        raise SigningError("not_found", "This signature link was not found.", 404)
    if row.get("status") == STATUS_SIGNED:
        raise SigningError("already_signed", "These forms have already been signed.", 409)
    if row.get("status") != STATUS_PENDING:
        raise SigningError("replaced", "This link was replaced by a newer one. Use the latest e-mail.", 409)
    if _expired(row):
        raise SigningError("expired", "This link has expired. Ask your agent to send a new one.", 410)
    return row


def forms_to_sign(row: dict, proc_session: dict) -> List[str]:
    """The request's forms that still exist and still carry an applicant line."""
    signable = set(signable_form_ids(proc_session))
    return [f for f in (row.get("form_ids") or []) if f in signable]


async def _session_for(row: dict) -> dict:
    from repositories.session_repository import get_processing_session
    try:
        return await get_processing_session(row["session_id"])
    except Exception:
        raise SigningError("not_found", "This signature link was not found.", 404)


async def sign(token: str, signer_name: Any, consent: Any, image: Any,
               versions: Any, tz_offset_minutes: Any, ip: str, agent: str) -> dict:
    """The client signs inside the questionnaire. Every check runs before
    anything is written, and the request is claimed in one statement, so a link
    signs once. The forms are NOT touched here: `finalize` records the
    signature on them after the questionnaire's answers are applied, so it
    covers the forms as they print with the client's own answers in."""
    from config.database import get_pool
    from utils.crypto import encrypt_field

    row = check_open(await get_by_token(token))
    # The question asks only for the signature (owner, 1 Oct night). A typed
    # name, a consent tick and the forms the page showed are recorded when a
    # page sends them; otherwise the name is the one the producer sent the
    # questionnaire to.
    name = clean_signer_name(signer_name) if str(signer_name or "").strip() \
        else " ".join(str(row.get("client_name") or "").split())[:100]
    picture = normalize_signature_image(image)

    proc_session = await _session_for(row)
    forms = forms_to_sign(row, proc_session)
    if not forms:
        raise SigningError("no_forms", "There is nothing left to sign. Ask your agent.", 409)
    current = form_versions(proc_session, forms)
    seen = versions if isinstance(versions, dict) else {}
    if seen and any(seen.get(f) != current.get(f) for f in forms):
        raise SigningError("forms_changed",
                           "Your agent updated these forms after you opened this page. "
                           "Please review them again before signing.", 409)
    try:
        encrypted = encrypt_field(picture)
    except Exception as ex:
        logger.error("applicant signature: encryption unavailable: %s", ex)
        encrypted = None
    if not encrypted or not str(encrypted).startswith("enc:"):
        raise SigningError("storage", "Your signature could not be saved. Please try again later.", 503)

    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        claimed = await conn.fetchval(
            "UPDATE signature_requests SET status = $1, signed_at = $2, signer_name = $3,"
            " signature_data = $4, consent_text = $5, signer_ip = $6, signer_agent = $7,"
            " form_versions = $8 WHERE token = $9 AND status = $10 RETURNING id",
            STATUS_SIGNED, now.isoformat(), name, encrypted,
            CONSENT_TEXT if consent is True else None, (ip or "")[:64],
            (agent or "")[:300], {"_tz_offset_minutes": _offset(tz_offset_minutes), **current},
            token, STATUS_PENDING)
    if not claimed:
        raise SigningError("already_signed", "These forms have already been signed.", 409)
    return {"request": row, "forms": forms, "signer_name": name}


def _offset(tz_offset_minutes: Any) -> int:
    try:
        return max(-14 * 60, min(14 * 60, int(tz_offset_minutes)))
    except (TypeError, ValueError):
        return 0


async def finalize(token: str) -> Optional[dict]:
    """Record a signed request on the package's forms - after the
    questionnaire's answers are applied, so the fingerprint is of the forms as
    they print now. Idempotent; None when the request is not signed (or gone).
    The image moves into the session, encrypted as stored."""
    from repositories.session_repository import upd_processing_session
    row = await get_by_token(token) if valid_token(token) else None
    if not row or row.get("status") != STATUS_SIGNED or not row.get("signature_data"):
        return None
    try:
        proc_session = await _session_for(row)
    except SigningError:
        return None
    forms = forms_to_sign(row, proc_session)
    if not forms:
        return None
    # Recorded once: re-recording later would re-validate a signature the
    # forms have since moved away from.
    generated = proc_session.get("generated_forms") or {}
    if any(((generated.get(f) or {}).get(sb.APPLICANT_SIGNATURE_KEY) or {}).get("request_id") == row["id"]
           for f in forms):
        return None
    current = form_versions(proc_session, forms)
    stored = row.get("form_versions") if isinstance(row.get("form_versions"), dict) else {}
    try:
        signed_at = datetime.fromisoformat(str(row.get("signed_at")).replace("Z", "+00:00"))
    except ValueError:
        signed_at = datetime.now(timezone.utc)
    signed_date = signing_date(signed_at, stored.get("_tz_offset_minutes"))
    await upd_processing_session(row["session_id"], {
        "generated_forms": signed_form_updates(proc_session, row["id"], current,
                                               row.get("signer_name") or "", signed_at.isoformat(), signed_date),
        sb.APPLICANT_IMAGES_KEY: images_after(proc_session, row["id"], row["signature_data"]),
    })
    return {"request": row, "forms": forms, "signed_date": signed_date,
            "signer_name": row.get("signer_name") or ""}
