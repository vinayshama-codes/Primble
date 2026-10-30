"""ACORD Solutions Group - Transcriber extraction client (29 Oct 2026).

Read ASG_TRANSCRIBER.md before changing anything here. The contract (section 7.2):

  token   POST {token_url}  grant_type=client_credentials (client id + secret)
  submit  POST {base}/forms/extract?inpFormat=PDF&outFormat=ELABEL&latestEdition=true
               &sort=true&confidenceScore=true&returnCoordinates=true
          headers x-api-key, Authorization: <token>, Content-Type: text/plain,
          x-extraction-traceid: <our uuid>; body = base64 of the file  -> 202
          {"status":"accepted","requestId":..,"callbackUrl":..}
  poll    GET  {base}/forms/extract/{requestId} -> {"responseBody": "<ACORD>..</ACORD>",
               "ruleExceptionList": []}; status="PROCESSING" while running
  large   > 5 MB base64: multipart POST {upload_url} -> contentLocation, then the
          submit with contentLocation= and an empty body
  big reply  X-asg-body-compression-enabled: Y -> base64 gzip body;
             X-asg-large-response-enabled: Y -> body is a download URL

What this module does NOT decide: which pages are sent (acord_intake.transcriber_intake),
how a result becomes facts (acord_intake.read), where results are cached
(repositories.transcriber_repository). It knows the wire and the reply shapes.

RULES (owner, 29 Oct 2026):
- No live call ever happens unless TRANSCRIBER=1 AND credentials are set AND no stub
  is configured. The test suite runs with the stub only (`TRANSCRIBER_STUB_DIR`).
- Usage is metered per PAGE (the pilot: 10,000, hard stop). The caller passes a
  `usage` hook; this module reports pages sent and refuses past the daily cap.
- Secrets never reach a log line. Logs carry trace id, request id, form numbers,
  page counts and timings - never a value read off a form.
- Production must not point at UAT: `TRANSCRIBER_ENV=uat` with ENVIRONMENT=production
  disables the client unless TRANSCRIBER_ALLOW_UAT_IN_PROD=1.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── configuration ─────────────────────────────────────────────────────────────
_TRUE = ("1", "true", "yes", "on")
# The reply body is third-party XML. `defusedxml` is not installed; the two
# attacks that matter are refused by inspection (external entities / DOCTYPE)
# and by size before ElementTree ever sees the text.
_XML_MAX_CHARS = 25_000_000
_FORBIDDEN_XML = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.I)
_LARGE_BODY_BYTES = 5 * 1024 * 1024          # the documented large-file threshold
_TOKEN_SKEW_SECONDS = 60
# what the usage hook returns when its counter cannot be written (fail closed)
USAGE_UNAVAILABLE = 10 ** 9
_POLL_BACKOFF = (5.0, 15.0, 30.0)                 # retryable poll errors, inside wait_seconds
_SUBMIT_429_WAIT = 5.0


def _flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


@dataclass(frozen=True)
class TranscriberConfig:
    enabled: bool
    env: str                                  # "uat" | "prod"
    token_url: str
    base_url: str                             # ends with /oauth
    upload_url: str
    client_id: str
    client_secret: str
    api_key: str
    scope: str
    wait_seconds: float
    poll_interval: float
    http_timeout: float
    max_pages_per_package: int
    daily_page_cap: int
    send_fillable: bool
    stub_dir: str
    bearer: bool                              # Authorization: "Bearer <t>" vs "<t>"

    @property
    def live(self) -> bool:
        """True when a real HTTP call would be made."""
        return self.enabled and not self.stub_dir and bool(self.client_id and self.client_secret and self.api_key)

    @property
    def usable(self) -> bool:
        return self.enabled and (bool(self.stub_dir) or self.live)


def load_config() -> TranscriberConfig:
    env = (os.getenv("TRANSCRIBER_ENV") or "uat").strip().lower()
    if env not in ("uat", "prod"):
        env = "uat"
    enabled = _flag("TRANSCRIBER", "0")
    app_env = (os.getenv("ENVIRONMENT") or "development").strip().lower()
    if enabled and env == "uat" and app_env == "production" and not _flag("TRANSCRIBER_ALLOW_UAT_IN_PROD"):
        logger.error("TRANSCRIBER disabled: ENVIRONMENT=production may not call the UAT service "
                     "(the pilot agreement forbids production use; set TRANSCRIBER_ENV=prod with "
                     "production credentials, or TRANSCRIBER_ALLOW_UAT_IN_PROD=1 to override)")
        enabled = False
    token_default = ("https://prod-token-transcriber.acordsolutions.net/oauth2/token" if env == "prod"
                     else "https://nonprod-token-transcriber.acordsolutions.net/oauth2/token")
    base_default = f"https://{env}-api-v1-transcriber.acordsolutions.net/oauth"
    upload_default = ("https://transcriber.acordsolutions.net/Iforms-webforms-app/v2/iforms/extract/uploadfile"
                      if env == "prod" else
                      "https://uat-transcriber.acordsolutions.net/Iforms-webforms-app/v2/iforms/extract/uploadfile")

    def _num(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, "") or default)
        except ValueError:
            return default

    return TranscriberConfig(
        enabled=enabled, env=env,
        token_url=(os.getenv("TRANSCRIBER_TOKEN_URL") or token_default).strip(),
        base_url=(os.getenv("TRANSCRIBER_BASE_URL") or base_default).strip().rstrip("/"),
        upload_url=(os.getenv("TRANSCRIBER_UPLOAD_URL") or upload_default).strip(),
        client_id=(os.getenv("TRANSCRIBER_CLIENT_ID") or "").strip(),
        client_secret=(os.getenv("TRANSCRIBER_CLIENT_SECRET") or "").strip(),
        api_key=(os.getenv("TRANSCRIBER_API_KEY") or "").strip(),
        scope=(os.getenv("TRANSCRIBER_SCOPE") or "").strip(),
        wait_seconds=_num("TRANSCRIBER_WAIT_SECONDS", 150),
        poll_interval=_num("TRANSCRIBER_POLL_SECONDS", 3),
        http_timeout=_num("TRANSCRIBER_HTTP_TIMEOUT", 60),
        max_pages_per_package=int(_num("TRANSCRIBER_MAX_PAGES_PER_PACKAGE", 40)),
        daily_page_cap=int(_num("TRANSCRIBER_DAILY_PAGE_CAP", 500)),
        send_fillable=_flag("TRANSCRIBER_SEND_FILLABLE", "1"),
        stub_dir=(os.getenv("TRANSCRIBER_STUB_DIR") or "").strip(),
        bearer=_flag("TRANSCRIBER_BEARER", "0"),
    )


# ── errors ────────────────────────────────────────────────────────────────────
class TranscriberError(Exception):
    """kind: auth | forbidden | quota | too_large | bad_request | server | timeout |
    rejected | unavailable | stub_miss. `retryable` says whether one more attempt
    is worth it; the caller's answer to any of these is today's reading."""

    def __init__(self, kind: str, message: str, retryable: bool = False, status: Optional[int] = None):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message, self.retryable, self.status = kind, message, retryable, status


# ── the parsed reply ──────────────────────────────────────────────────────────
@dataclass
class TranscribedBox:
    value: str
    confidence: Optional[float] = None
    page: Optional[int] = None                # physical page in the SENT file (1-based)
    bbox: Optional[Tuple[float, float, float, float]] = None


@dataclass
class TranscribedForm:
    """One form instance: consecutive pages of one formNumber / geoCode / edition
    whose formPageNum climbs. `pages` are 1-based page numbers IN THE SENT FILE."""
    form_number: str
    geo_code: str
    edition: str
    form_name: str
    pages: List[int]
    accuracy: Optional[float]
    status: str                               # Success | Rejected | ...
    boxes: Dict[str, TranscribedBox] = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return self.status.lower() != "success" or self.form_number.upper() == "UNKNOWN"


@dataclass
class TranscriberResult:
    status: str                               # processing | done | failed
    request_id: str = ""
    forms: List[TranscribedForm] = field(default_factory=list)
    rule_exceptions: List[Any] = field(default_factory=list)
    message: str = ""
    raw: str = ""                             # the eLabel body as received (kept for replay)
    elapsed: float = 0.0

    @property
    def readable_forms(self) -> List[TranscribedForm]:
        return [f for f in self.forms if not f.rejected]

    def to_json(self) -> dict:
        return {
            "status": self.status, "request_id": self.request_id, "message": self.message,
            "rule_exceptions": self.rule_exceptions, "elapsed": round(self.elapsed, 2),
            "forms": [{
                "form_number": f.form_number, "geo_code": f.geo_code, "edition": f.edition,
                "form_name": f.form_name, "pages": f.pages, "accuracy": f.accuracy, "status": f.status,
                "boxes": {b: {"value": x.value, "confidence": x.confidence, "page": x.page, "bbox": x.bbox}
                          for b, x in f.boxes.items()},
            } for f in self.forms],
        }

    @classmethod
    def from_json(cls, d: dict) -> "TranscriberResult":
        out = cls(status=str(d.get("status") or "done"), request_id=str(d.get("request_id") or ""),
                  message=str(d.get("message") or ""), rule_exceptions=list(d.get("rule_exceptions") or []),
                  elapsed=float(d.get("elapsed") or 0))
        for f in d.get("forms") or []:
            tf = TranscribedForm(form_number=str(f.get("form_number") or ""), geo_code=str(f.get("geo_code") or ""),
                                 edition=str(f.get("edition") or ""), form_name=str(f.get("form_name") or ""),
                                 pages=[int(p) for p in f.get("pages") or []],
                                 accuracy=f.get("accuracy"), status=str(f.get("status") or ""))
            for b, x in (f.get("boxes") or {}).items():
                bb = x.get("bbox")
                tf.boxes[b] = TranscribedBox(value=str(x.get("value") or ""), confidence=x.get("confidence"),
                                             page=x.get("page"), bbox=tuple(bb) if bb else None)
            out.forms.append(tf)
        return out


# ── parsing ───────────────────────────────────────────────────────────────────
def _float(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip()) if v not in (None, "") else None
    except ValueError:
        return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(str(v).strip())) if v not in (None, "") else None
    except ValueError:
        return None


def _group_pages(pages: List[dict]) -> List[TranscribedForm]:
    """Per-page records -> form instances. A new instance starts when the form
    identity changes or formPageNum does not climb (a second 125 behind the first)."""
    out: List[TranscribedForm] = []
    cur: Optional[TranscribedForm] = None
    last_fp = 0
    for pg in pages:
        ident = (pg["form_number"], pg["geo_code"], pg["edition"])
        fp = pg.get("form_page") or 0
        new = (cur is None or (cur.form_number, cur.geo_code, cur.edition) != ident
               or (fp and last_fp and fp <= last_fp) or pg["status"].lower() != "success")
        if new:
            cur = TranscribedForm(form_number=pg["form_number"], geo_code=pg["geo_code"], edition=pg["edition"],
                                  form_name=pg["form_name"], pages=[], accuracy=pg["accuracy"], status=pg["status"])
            out.append(cur)
            last_fp = 0
        # The real reply (probe, 29 Oct 2026) is ONE element per FORM whose boxes
        # carry their own page numbers: the form spans every page its boxes name.
        for p_ in sorted({pg["page"]} | {b.page for b in pg["boxes"].values() if b.page}):
            if p_ not in cur.pages:
                cur.pages.append(p_)
        cur.pages.sort()
        last_fp = fp or last_fp
        # one accuracy per instance: the lowest page is the honest one
        if pg["accuracy"] is not None:
            cur.accuracy = pg["accuracy"] if cur.accuracy is None else min(cur.accuracy, pg["accuracy"])
        for name, box in pg["boxes"].items():
            if name not in cur.boxes or (not cur.boxes[name].value and box.value):
                cur.boxes[name] = box
    return out


def parse_elabel_xml(text: str) -> List[TranscribedForm]:
    """The eLabel XML (`<ACORD><ACORD formNumber=.. ..><ELabel ..>v</ELabel>..</ACORD></ACORD>`)
    -> form instances. Raises TranscriberError("rejected") on the documented critical
    rule failure text, ValueError on malformed XML."""
    if not text or len(text) > _XML_MAX_CHARS:
        raise ValueError("empty or oversized eLabel body")
    if _FORBIDDEN_XML.search(text):
        raise ValueError("eLabel body declares entities")
    stripped = text.strip()
    if "Failed due to Exception occurred for critical rule" in stripped:
        raise TranscriberError("rejected", "critical rule failure", status=200)
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as ex:
        raise ValueError(f"malformed eLabel XML: {ex}") from ex
    page_elems = [e for e in root.iter("ACORD") if e is not root] or ([root] if root.attrib else [])
    pages: List[dict] = []
    for i, e in enumerate(page_elems):
        a = e.attrib
        boxes: Dict[str, TranscribedBox] = {}
        for child in e:
            name = child.tag
            if name == "ACORD":
                continue
            val = (child.text or "").strip()
            ba = child.attrib
            bbox = None
            if all(k in ba for k in ("tlx", "tly", "brx", "bry")):
                try:
                    bbox = (float(ba["tlx"]), float(ba["tly"]), float(ba["brx"]), float(ba["bry"]))
                except ValueError:
                    bbox = None
            boxes[name] = TranscribedBox(value=val, confidence=_float(ba.get("confidence_score")),
                                         page=_int(ba.get("physicalDocumentPageNo") or ba.get("pageNo")), bbox=bbox)
        pages.append({
            "form_number": str(a.get("formNumber") or "UNKNOWN").strip(),
            "geo_code": str(a.get("geoCode") or "").strip(),
            "edition": str(a.get("edition") or "").strip(),
            "form_name": str(a.get("formName") or "").strip(),
            "page": _int(a.get("documentPageNum")) or (i + 1),
            "form_page": _int(a.get("formPageNum")),
            "accuracy": _float(a.get("accuracyPercent")),
            "status": str(a.get("status") or ("Success" if boxes else "Rejected")).strip(),
            "boxes": boxes,
        })
    return _group_pages(pages)


def parse_elabel_json(obj: Any) -> List[TranscribedForm]:
    """The JSON twin ({"ACORD":{"ACORD":[{"formNumber":..,"<eLabel>":{"content":..,..}}]}} -
    Population's documented shape; whether extraction returns it under
    Accept: application/json is confirmed by the first real reply)."""
    inner = obj.get("ACORD") if isinstance(obj, dict) else None
    arr = inner.get("ACORD") if isinstance(inner, dict) else None
    if not isinstance(arr, list):
        raise ValueError("not an eLabel JSON document")
    meta = {"formNumber", "geoCode", "geoCodeSuffix", "edition", "formName", "documentPageNum", "formPageNum",
            "accuracyPercent", "status", "businessDomain", "broadLOB", "LOB", "documentName"}
    pages: List[dict] = []
    for i, e in enumerate(arr):
        if not isinstance(e, dict):
            continue
        boxes: Dict[str, TranscribedBox] = {}
        for name, x in e.items():
            if name in meta:
                continue
            if isinstance(x, dict):
                val = str(x.get("content") if x.get("content") is not None else x.get("value") or "").strip()
                conf = _float(x.get("confidence_score") or x.get("confidenceScore") or x.get("confidence"))
                page = _int(x.get("physicalDocumentPageNo") or x.get("pageNo"))
                bbox = None
                if all(k in x for k in ("tlx", "tly", "brx", "bry")):
                    try:
                        bbox = (float(x["tlx"]), float(x["tly"]), float(x["brx"]), float(x["bry"]))
                    except (TypeError, ValueError):
                        bbox = None
                boxes[name] = TranscribedBox(value=val, confidence=conf, page=page, bbox=bbox)
            else:
                boxes[name] = TranscribedBox(value=str(x if x is not None else "").strip())
        pages.append({
            "form_number": str(e.get("formNumber") or "UNKNOWN").strip(),
            "geo_code": str(e.get("geoCode") or "").strip(),
            "edition": str(e.get("edition") or "").strip(),
            "form_name": str(e.get("formName") or "").strip(),
            "page": _int(e.get("documentPageNum")) or (i + 1),
            "form_page": _int(e.get("formPageNum")),
            "accuracy": _float(e.get("accuracyPercent")),
            "status": str(e.get("status") or ("Success" if boxes else "Rejected")).strip(),
            "boxes": boxes,
        })
    return _group_pages(pages)


_PROCESSING_RE = re.compile(r'status\s*=\s*\\?"PROCESSING\\?"', re.I)


def parse_poll_reply(body: Any, headers: Optional[Dict[str, str]] = None) -> TranscriberResult:
    """One GET reply (already decoded from HTTP) -> TranscriberResult. `body` is the
    JSON object, or the raw text when it was not JSON."""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    obj = body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            obj = json.loads(body)
        except ValueError:
            obj = body
    # the large-reply shapes: a gzip+base64 body, or a download URL
    if isinstance(obj, str) and headers.get("x-asg-body-compression-enabled", "").upper() == "Y":
        try:
            obj = gzip.decompress(base64.b64decode(obj)).decode("utf-8", "replace")
            try:
                obj = json.loads(obj)
            except ValueError:
                pass
        except Exception as ex:                                # noqa: BLE001
            raise TranscriberError("server", f"compressed reply unreadable: {ex}")
    if isinstance(obj, str) and headers.get("x-asg-large-response-enabled", "").upper() == "Y":
        return TranscriberResult(status="download", message=obj.strip())
    inner: Any = obj
    rule_exceptions: List[Any] = []
    request_id = ""
    if isinstance(obj, dict):
        request_id = str(obj.get("requestId") or "")
        rule_exceptions = list(obj.get("ruleExceptionList") or [])
        if "responseBody" in obj:
            inner = obj["responseBody"]
        elif str(obj.get("status") or "").lower() in ("processing", "accepted", "retrying"):
            return TranscriberResult(status="processing", request_id=request_id, message=str(obj.get("message") or ""))
        elif "ACORD" in obj:
            inner = obj
        elif obj.get("status") or obj.get("message") or obj.get("error"):
            # a terminal envelope with no body ({"status":"FAILED","message":..}):
            # the extraction failed - never a parse error (review, 29 Oct 2026)
            return TranscriberResult(status="failed", request_id=request_id,
                                     message=str(obj.get("message") or obj.get("error") or obj.get("status") or "")[:300])
    if isinstance(inner, (bytes, bytearray)):
        inner = inner.decode("utf-8", "replace")
    if isinstance(inner, str):
        s = inner.strip()
        if not s:
            return TranscriberResult(status="processing", request_id=request_id)
        if s.startswith("{"):
            try:
                inner = json.loads(s)
            except ValueError:
                inner = s
        if isinstance(inner, str):
            if _PROCESSING_RE.search(s) or "<status>RETRYING</status>" in s:
                return TranscriberResult(status="processing", request_id=request_id, message="processing")
            if s.lower().startswith("unable to extract document"):
                return TranscriberResult(status="failed", request_id=request_id, message=s)
            forms = parse_elabel_xml(s)
            return TranscriberResult(status="done", request_id=request_id, forms=forms,
                                     rule_exceptions=rule_exceptions, raw=s)
    if isinstance(inner, dict):
        st = inner.get("ACORD") if isinstance(inner.get("ACORD"), dict) else None
        if st is not None and str(st.get("status") or "").upper() == "PROCESSING":
            return TranscriberResult(status="processing", request_id=request_id, message=str(st.get("message") or ""))
        forms = parse_elabel_json(inner)
        return TranscriberResult(status="done", request_id=request_id, forms=forms,
                                 rule_exceptions=rule_exceptions, raw=json.dumps(inner, separators=(",", ":")))
    raise TranscriberError("server", "unrecognised reply shape")


# ── the submit reply ──────────────────────────────────────────────────────────
_ID_KEY_RE = re.compile(r"^(request|message|transaction|job|correlation)[-_ ]?id$", re.I)
_ID_IN_URL_RE = re.compile(r"/forms/extract/([A-Za-z0-9][A-Za-z0-9._:-]{5,})/?(?:\?|$)")
_LOOKS_LIKE_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}[0-9]{0,4}$")


def _json_keys(text: str) -> List[str]:
    try:
        obj = json.loads(text or "")
    except ValueError:
        return []
    return sorted(obj.keys()) if isinstance(obj, dict) else [type(obj).__name__]


def request_id_from_submit_reply(text: str, headers: Optional[Dict[str, str]] = None) -> str:
    """The request id in a 202 reply, whatever its shape: `requestId` /
    `callbackUrl` (the manual), any `*Id` key or `.../forms/extract/<id>` URL at
    any depth, a bare id string, or a Location header."""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    found: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                if isinstance(x, (str, int)) and _ID_KEY_RE.match(str(k)) and str(x).strip():
                    found.append(str(x).strip())
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            m = _ID_IN_URL_RE.search(v)
            if m:
                found.append(m.group(1))
            elif _LOOKS_LIKE_ID_RE.match(v.strip()):
                found.append(v.strip())
    raw = (text or "").strip()
    try:
        obj = json.loads(raw) if raw else None
    except ValueError:
        obj = raw
    walk(obj)
    for h in ("location",):                          # never x-amzn-requestid: the gateway stamps every reply
        if h in headers and not found:
            m = _ID_IN_URL_RE.search(headers[h])
            found.append(m.group(1) if m else headers[h].strip())
    return found[0] if found else ""


def _mime_of(data: bytes) -> str:
    head = bytes(data[:8])
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"II*\x00") or head.startswith(b"MM\x00*"):
        return "image/tiff"
    return "application/octet-stream"


# ── the client ────────────────────────────────────────────────────────────────
def content_hash(data: bytes, params: str = "") -> str:
    h = hashlib.sha256()
    h.update(data)
    h.update(b"|")
    h.update(params.encode("utf-8"))
    return h.hexdigest()


_EXTRACT_PARAMS = {"inpFormat": "PDF", "outFormat": "ELABEL", "latestEdition": "true", "sort": "true",
                   "confidenceScore": "true", "returnCoordinates": "true"}


class TranscriberClient:
    """submit / poll / extract. `usage` is an async callable (pages: int, env: str)
    -> pages used today AFTER adding (the repository); None = no accounting."""

    def __init__(self, config: Optional[TranscriberConfig] = None,
                 usage: Optional[Callable[[int, str], Awaitable[int]]] = None,
                 http: Any = None):
        self.cfg = config or load_config()
        self._usage = usage
        self._http = http                      # an httpx.AsyncClient for tests; else one per call
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._bearer: bool = bool(self.cfg.bearer)
        self._auth_flipped: bool = False

    # -- helpers ---------------------------------------------------------------
    def _auth_value(self, token: str) -> str:
        return f"Bearer {token}" if self._bearer else token

    def _client(self):
        if self._http is not None:
            return self._http
        import httpx
        return httpx.AsyncClient(timeout=self.cfg.http_timeout)

    async def _request(self, method: str, url: str, **kw):
        if self._http is not None:
            return await self._http.request(method, url, **kw)
        import httpx
        async with httpx.AsyncClient(timeout=self.cfg.http_timeout) as c:
            return await c.request(method, url, **kw)

    @staticmethod
    def _raise_for(status: int, text: str) -> None:
        if status in (200, 202):
            return
        snippet = (text or "")[:200]
        if status == 401:
            raise TranscriberError("auth", "token missing or invalid", status=401)
        if status == 403:
            raise TranscriberError("forbidden", "API key missing / invalid / not authorised", status=403)
        if status == 413:
            raise TranscriberError("too_large", "payload too large", status=413)
        if status == 429:
            raise TranscriberError("quota", "rate limit or quota", retryable=True, status=429)
        if status == 400:
            raise TranscriberError("bad_request", snippet, status=400)
        if status == 504:
            raise TranscriberError("timeout", "endpoint timed out", retryable=True, status=504)
        if status >= 500:
            raise TranscriberError("server", snippet or "server error", retryable=True, status=status)
        raise TranscriberError("server", f"HTTP {status} {snippet}", status=status)

    # -- token -----------------------------------------------------------------
    async def token(self) -> str:
        if self._token and time.time() < self._token_expiry - _TOKEN_SKEW_SECONDS:
            return self._token
        data = {"grant_type": "client_credentials"}
        if self.cfg.scope:
            data["scope"] = self.cfg.scope
        basic = base64.b64encode(f"{self.cfg.client_id}:{self.cfg.client_secret}".encode()).decode()
        r = await self._request("POST", self.cfg.token_url, data=data,
                                headers={"Authorization": f"Basic {basic}",
                                         "Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            # Cognito also accepts the pair in the body
            data2 = dict(data, client_id=self.cfg.client_id, client_secret=self.cfg.client_secret)
            r = await self._request("POST", self.cfg.token_url, data=data2,
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            raise TranscriberError("auth", f"token endpoint answered {r.status_code}", status=r.status_code)
        body = r.json()
        tok = str(body.get("access_token") or "")
        if not tok:
            raise TranscriberError("auth", "token reply carried no access_token")
        self._token = tok
        self._token_expiry = time.time() + float(body.get("expires_in") or 3600)
        return tok

    def _headers(self, token: str, trace: str, **extra: str) -> Dict[str, str]:
        h = {"x-api-key": self.cfg.api_key, "Authorization": self._auth_value(token),
             "x-extraction-traceid": trace, "Accept": "application/json"}
        h.update(extra)
        return h

    # -- submit ----------------------------------------------------------------
    async def submit(self, data: bytes, *, input_format: str = "PDF", trace: Optional[str] = None) -> Tuple[str, str]:
        """-> (request_id, trace_id). Raises TranscriberError."""
        trace = trace or str(uuid.uuid4())
        token = await self.token()
        params = dict(_EXTRACT_PARAMS, inpFormat=input_format)
        b64 = base64.b64encode(data).decode("ascii")
        if len(b64) > _LARGE_BODY_BYTES:
            location = await self._upload_large(data, token, input_format)
            params["contentLocation"] = location
            r = await self._request("POST", f"{self.cfg.base_url}/forms/extract", params=params,
                                    headers=self._headers(token, trace, **{"Content-Type": "text/plain"}), content=b"")
        else:
            r = await self._request("POST", f"{self.cfg.base_url}/forms/extract", params=params,
                                    headers=self._headers(token, trace, **{"Content-Type": "text/plain"}), content=b64)
        self._raise_for(r.status_code, r.text)
        rid = request_id_from_submit_reply(r.text, dict(r.headers))
        if not rid:
            # The envelope carries no document data: its keys are safe to log and
            # are the only way to learn a shape the manual did not show
            # (live 29 Oct 2026: a 2xx with neither requestId nor callbackUrl).
            logger.warning("TRANSCRIBER_SUBMIT_SHAPE status=%s content_type=%s keys=%s head=%r",
                           r.status_code, r.headers.get("content-type"), _json_keys(r.text), (r.text or "")[:300])
            raise TranscriberError("server", "submit reply carried no requestId")
        return rid, trace

    async def _upload_large(self, data: bytes, token: str, input_format: str) -> str:
        mime = _mime_of(data) if input_format.upper() == "IMAGE" else (
            "application/pdf" if input_format.upper() == "PDF" else "application/octet-stream")
        r = await self._request("POST", self.cfg.upload_url, headers={"Authorization": self._auth_value(token)},
                                data={"contentMimeType": mime}, files={"file": ("document", data, mime)})
        self._raise_for(r.status_code, r.text)
        loc = (r.text or "").strip().strip('"')
        if not loc:
            raise TranscriberError("server", "large-file upload returned no content location")
        return loc

    # -- poll ------------------------------------------------------------------
    async def fetch(self, request_id: str, trace: Optional[str] = None) -> TranscriberResult:
        token = await self.token()
        r = await self._request("GET", f"{self.cfg.base_url}/forms/extract/{request_id}",
                                headers=self._headers(token, trace or str(uuid.uuid4())))
        if r.status_code == 401:
            # a token revoked or expired early: one fresh token, one more try
            self._token, self._token_expiry = "", 0.0
            token = await self.token()
            r = await self._request("GET", f"{self.cfg.base_url}/forms/extract/{request_id}",
                                    headers=self._headers(token, trace or str(uuid.uuid4())))
        if r.status_code == 500 and "not completed successfully" in (r.text or ""):
            raise TranscriberError("server", "extraction not completed", retryable=True, status=500)
        self._raise_for(r.status_code, r.text)
        try:
            res = parse_poll_reply(r.text, dict(r.headers))
        except ValueError as ex:
            # a gateway's HTML page or a truncated body: worth one more poll
            raise TranscriberError("server", f"unreadable reply: {str(ex)[:120]}", retryable=True)
        if res.status == "download":
            # The link is pre-signed (its token is in the query string): our
            # Authorization header would be a second auth mechanism, which S3 refuses.
            d = await self._request("GET", res.message)
            self._raise_for(d.status_code, d.text)
            res = parse_poll_reply(d.text, {})
        res.request_id = res.request_id or request_id
        return res

    # -- the whole thing -------------------------------------------------------
    async def extract(self, data: bytes, *, input_format: str = "PDF", pages: int = 1,
                      label: str = "", resume_request_id: str = "",
                      on_submitted: Optional[Callable[[str], Awaitable[None]]] = None) -> TranscriberResult:
        """submit + poll until done, within `wait_seconds`. Accounts `pages` through the
        usage hook BEFORE sending and refuses past the daily cap. A stub answers from
        disk and never touches the network. `resume_request_id`: a request already
        submitted for these bytes (a crash or timeout mid-poll) is polled again instead
        of being paid for twice; `on_submitted(request_id)` lets the caller remember it."""
        t0 = time.time()
        if self.cfg.stub_dir:
            res = self._stub(data, input_format)
            res.elapsed = time.time() - t0
            return res
        if not self.cfg.live:
            raise TranscriberError("unavailable", "transcriber not configured")
        trace = str(uuid.uuid4())
        if resume_request_id:
            rid = resume_request_id
            logger.info("TRANSCRIBER_RESUME env=%s trace=%s request=%s pages=%d label=%s",
                        self.cfg.env, trace, rid, pages, label)
        else:
            rid, trace = await self._paid_submit(data, input_format=input_format, pages=pages, label=label,
                                                 trace=trace, t0=t0, on_submitted=on_submitted)
        deadline = t0 + self.cfg.wait_seconds
        attempts = 0
        while True:
            await asyncio.sleep(self.cfg.poll_interval)
            try:
                res = await self.fetch(rid, trace)
            except TranscriberError as ex:
                # a 429 / 5xx / unreadable body: back off 5 / 15 / 30 s (a TPM-style
                # window clears in a minute) while the deadline allows, then give up
                if ex.retryable and attempts < len(_POLL_BACKOFF):
                    wait = min(_POLL_BACKOFF[attempts], max(0.0, deadline - time.time()))
                    attempts += 1
                    if time.time() + wait < deadline:
                        await asyncio.sleep(wait)
                        continue
                raise
            if res.status != "processing":
                res.elapsed = time.time() - t0
                logger.info("TRANSCRIBER_DONE trace=%s request=%s status=%s forms=%s elapsed=%.1fs",
                            trace, rid, res.status,
                            [f"{f.form_number}{('-' + f.geo_code) if f.geo_code else ''}x{len(f.pages)}"
                             f"{'' if not f.rejected else '(rejected)'}" for f in res.forms], res.elapsed)
                return res
            if time.time() >= deadline:
                raise TranscriberError("timeout", f"no result within {self.cfg.wait_seconds:.0f}s", retryable=False)

    async def _refund(self, pages: int) -> None:
        """Take back pages counted for a request that never reached ASG."""
        if self._usage is None or not pages:
            return
        try:
            await self._usage(-int(pages), self.cfg.env)
        except Exception as ex:                                # noqa: BLE001
            logger.warning("transcriber usage refund failed: %s", ex)

    async def _paid_submit(self, data: bytes, *, input_format: str, pages: int, label: str, trace: str,
                           t0: float, on_submitted: Optional[Callable[[str], Awaitable[None]]] = None) -> Tuple[str, str]:
        """Account the pages (refused past the daily cap), submit, refund if nothing
        reached ASG, remember the request id. -> (request_id, trace)."""
        counted = False
        if self._usage is not None:
            used = await self._usage(pages, self.cfg.env)
            counted = True
            if used > self.cfg.daily_page_cap:
                if used < USAGE_UNAVAILABLE:
                    # counted, then refused: take the pages back off. A counter that
                    # could not be written counted nothing - no refund (bug hunt, 29 Oct)
                    await self._refund(pages)
                raise TranscriberError("quota", f"daily page cap {self.cfg.daily_page_cap} reached ({used})")
        try:
            try:
                rid, trace = await self.submit(data, input_format=input_format, trace=trace)
            except TranscriberError as ex:
                if ex.status == 429 and time.time() + _SUBMIT_429_WAIT < t0 + self.cfg.wait_seconds:
                    # one rate-limit backoff on the submit itself
                    await asyncio.sleep(_SUBMIT_429_WAIT)
                    rid, trace = await self.submit(data, input_format=input_format, trace=trace)
                elif ex.status != 401 or self._auth_flipped:
                    # only a real 401 from the extract call flips the style - a token
                    # endpoint refusal (400 invalid_client) must not burn the one flip
                    raise
                else:
                    # Cognito tokens are usually sent bare here, sometimes as "Bearer":
                    # one flip, remembered for the process (ASG_TRANSCRIBER.md 7.1).
                    self._auth_flipped = True
                    self._bearer = not self._bearer
                    logger.info("TRANSCRIBER_AUTH_STYLE flipped bearer=%s after a 401", self._bearer)
                    rid, trace = await self.submit(data, input_format=input_format, trace=trace)
        except TranscriberError:
            # nothing reached ASG: the pages were never a transaction
            if counted:
                await self._refund(pages)
            raise
        except Exception as ex:                                # noqa: BLE001
            # a connection / read timeout or any transport error: refunded too
            if counted:
                await self._refund(pages)
            raise TranscriberError("unavailable", f"submit failed: {type(ex).__name__}", retryable=False)
        logger.info("TRANSCRIBER_SUBMIT env=%s trace=%s request=%s pages=%d bytes=%d label=%s",
                    self.cfg.env, trace, rid, pages, len(data), label)
        if on_submitted is not None:
            try:
                await on_submitted(rid)
            except Exception as ex:                            # noqa: BLE001
                logger.warning("transcriber request id not remembered: %s", ex)
        return rid, trace

    async def submit_only(self, data: bytes, *, input_format: str = "PDF", pages: int = 1, label: str = "",
                          on_submitted: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
        """The PRE-SUBMIT (29 Oct 2026): pay for and start the extraction now, collect
        it later through `extract(resume_request_id=...)` - a package's outside forms
        then run at ASG side by side while our own OCR and extraction proceed."""
        if self.cfg.stub_dir or not self.cfg.live:
            raise TranscriberError("unavailable", "pre-submit needs a live client")
        rid, _trace = await self._paid_submit(data, input_format=input_format, pages=pages, label=label,
                                              trace=str(uuid.uuid4()), t0=time.time(), on_submitted=on_submitted)
        return rid

    # -- stub ------------------------------------------------------------------
    def _stub(self, data: bytes, input_format: str) -> TranscriberResult:
        """A saved reply from `TRANSCRIBER_STUB_DIR`: `<sha256 of data>.json` first, then
        `default.json`. Either the saved HTTP body (`{"responseBody": ...}`) or a saved
        `TranscriberResult.to_json()`."""
        h = content_hash(data)
        for name in (f"{h}.json", "default.json"):
            path = os.path.join(self.cfg.stub_dir, name)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    txt = fh.read()
                try:
                    obj = json.loads(txt)
                except ValueError:
                    obj = txt
                if isinstance(obj, dict) and "forms" in obj and "status" in obj:
                    res = TranscriberResult.from_json(obj)
                else:
                    res = parse_poll_reply(obj if not isinstance(obj, dict) else json.dumps(obj), {})
                res.request_id = res.request_id or f"stub-{h[:12]}"
                return res
        raise TranscriberError("stub_miss", f"no stub reply for {h[:12]}")
