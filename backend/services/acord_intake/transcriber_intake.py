"""Which pages of an uploaded document go to ASG Transcriber, how they are packaged,
cached and fetched, and how a reply becomes reader copies (29 Oct 2026,
ASG_TRANSCRIBER.md sections 7.4-7.6). The wire lives in `services.asg_transcriber`;
the copies go through `read.boxes_to_facts` exactly like our own reader's.

ROUTING (owner, 29 Oct 2026):
- a document carrying a Primble record (our own download, or our cover page) is never
  sent - the record reads it for free and Transcriber cannot see the record;
- every other recognised ACORD page goes: printed, scanned, photographed - and
  fillable too while TRANSCRIBER_SEND_FILLABLE=1 (the in-house exact read still wins
  for those pages: `read.merge_transcriber_copies`);
- declarations, loss runs, narratives, spreadsheets: never (they are not ACORD pages).

COST (the pilot: one transaction per extractable page): only the ACORD pages are
sent, as ONE sub-PDF per document; the result is cached by the bytes sent, so the
same file never costs twice; a document over TRANSCRIBER_MAX_PAGES_PER_PACKAGE
pages is not sent at all (today's reading) rather than half-read.
"""
from __future__ import annotations

import io
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.asg_transcriber import (TranscribedBox, TranscriberClient, TranscriberError, TranscriberResult,
                                      content_hash, load_config)

logger = logging.getLogger(__name__)

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
# ACORD writes a tick as a code letter / cross; the probe (asg_dec_test_data/
# transcriber_probe) confirms the exact spelling - until then every documented
# spelling counts, and only on boxes ACORD names as indicators.
_TICK_VALUES = frozenset({"y", "x", "yes", "true", "1", "on", "checked", "✓", "✔"})
_INDICATOR_RE = re.compile(r"Indicator(?:_[A-Z]{1,2})?$|Indicator_[A-Z]{1,2}\d*$")
SOURCE = "transcriber"
CONFIDENCE = "acord_transcriber"          # the fact-level label (0.85 = found, please verify)


@dataclass
class SendGroup:
    pages: List[int]                      # 0-based pages of the UPLOADED file, in sent order
    acord_numbers: List[str]              # per page, "125" / "137 CO"
    kinds: List[str]                      # per page, fillable / flattened / scanned
    data: bytes = b""
    input_format: str = "PDF"
    whole_file: bool = False
    hash: str = ""

    @property
    def label(self) -> str:
        return ",".join(sorted({n for n in self.acord_numbers}))


@dataclass
class GroupResult:
    group: SendGroup
    result: Optional[TranscriberResult]
    cached: bool = False
    error: str = ""


# ── 1. plan ───────────────────────────────────────────────────────────────────
def plan(path: str, acord_record: Optional[dict], *, has_primble_record: bool,
         ocr_text: str = "", cfg=None) -> Optional[SendGroup]:
    """The one group to send for this document, or None. `acord_record` is
    `intake.read_for_document(...)["record"]` (its `pages` are the recognised ACORD
    pages, 1-based); `has_primble_record` = the file carries our record."""
    cfg = cfg or load_config()
    if not cfg.usable or has_primble_record:
        return None
    low = str(path or "").lower()
    if low.endswith(_IMAGE_EXT):
        return _plan_image(path, ocr_text, cfg)
    if not low.endswith(".pdf"):
        return None
    pages = [p for p in ((acord_record or {}).get("pages") or []) if isinstance(p, dict) and p.get("kind")]
    eligible = [p for p in pages if p["kind"] in ("flattened", "scanned")
                or (p["kind"] == "fillable" and cfg.send_fillable)]
    if not eligible:
        return None
    # A footer alone is not an ACORD page (review, 29 Oct 2026): a carrier's page
    # printing "see ACORD 125 (2016/03)" in its bottom band would cost a page.
    # Every page of a real ACORD form also prints the ACORD copyright (page 1) or
    # "Page n of m" (all 63 pages of our 17 templates + ASG's ACORD 36 checked).
    # Fillable pages are proven by their box names and need no second signal.
    texts = _page_texts(path, [int(p["page"]) - 1 for p in eligible if p["kind"] != "fillable"], ocr_text)
    eligible = [p for p in eligible if p["kind"] == "fillable" or looks_like_acord_page(texts.get(int(p["page"]) - 1, ""))]
    if not eligible:
        return None
    if len(eligible) > cfg.max_pages_per_package:
        logger.warning("TRANSCRIBER_SKIP reason=page_cap pages=%d cap=%d file=%s",
                       len(eligible), cfg.max_pages_per_package, os.path.basename(path))
        return None
    idx = sorted(int(p["page"]) - 1 for p in eligible)
    by_page = {int(p["page"]) - 1: p for p in eligible}
    group = SendGroup(pages=idx, acord_numbers=[str(by_page[i].get("acord_number") or "") for i in idx],
                      kinds=[str(by_page[i].get("kind") or "") for i in idx])
    try:
        group.data, group.whole_file = _subset_pdf(path, idx)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("TRANSCRIBER_SKIP reason=subset_failed file=%s err=%s", os.path.basename(path), ex)
        return None
    if not group.data:
        return None
    group.hash = content_hash(group.data, "PDF|ELABEL|latest")
    return group


# OCR of a scan (the pages Transcriber matters most for) runs words together
# ("Page 2 of4", "ACORDCORPORATION") and reads a 1 as l / I: the spacing is
# optional and the page numbers tolerate those slips (bug hunt, 29 Oct 2026).
_ACORD_PAGE_SIGNAL_RE = re.compile(
    r"ACORD\s*CORPORATION|registered\s+marks\s+of\s+ACORD|\bPage\s*[\dlI]{1,2}\s*of\s*[\dlI]{1,2}\b", re.I)


def looks_like_acord_page(text: str) -> bool:
    return bool(_ACORD_PAGE_SIGNAL_RE.search(text or ""))


def _page_texts(path: str, pages: List[int], ocr_text: str) -> Dict[int, str]:
    """{0-based page: text} for `pages` - the PDF's own text, else the OCR text."""
    out: Dict[int, str] = {}
    if not pages:
        return out
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for i in pages:
                if 0 <= i < len(pdf.pages):
                    out[i] = pdf.pages[i].extract_text() or ""
    except Exception as ex:                                    # noqa: BLE001
        logger.info("transcriber plan: page text unreadable: %s", ex)
    if ocr_text:
        parts = re.split(r"\[Document page (\d+)\]", ocr_text)
        for k in range(1, len(parts) - 1, 2):
            i = int(parts[k]) - 1
            if i in pages and not (out.get(i) or "").strip():
                out[i] = parts[k + 1]
    return out


def _plan_image(path: str, ocr_text: str, cfg) -> Optional[SendGroup]:
    """A photographed / scanned form uploaded as an image: the ACORD footer is in
    the OCR text; the whole image is the page."""
    from services.acord_intake.recognize import footer_of
    foot = footer_of(ocr_text or "", tail=True)
    if not foot or not looks_like_acord_page(ocr_text):
        return None
    with open(path, "rb") as fh:
        data = fh.read()
    num = f"{foot.group('num')} {foot.group('var')}" if foot.group("var") else foot.group("num")
    g = SendGroup(pages=[0], acord_numbers=[num], kinds=["scanned"], data=data, input_format="IMAGE",
                  whole_file=True)
    g.hash = content_hash(data, "IMAGE|ELABEL|latest")
    return g


def _subset_pdf(path: str, pages: List[int]):
    """(bytes, whole_file). The original bytes when every page goes (a fillable
    form keeps its fields exactly); else a new PDF of just those pages, the
    AcroForm dictionary copied so fillable values survive the cut."""
    import pikepdf
    with pikepdf.open(path) as src:
        n = len(src.pages)
        if sorted(pages) == list(range(n)):
            with open(path, "rb") as fh:
                return fh.read(), True
        if "/AcroForm" in src.Root:
            # A fillable source cut to a subset can lose its form dictionary (and
            # with it every typed value ASG would see): paint the values into the
            # pages first, so the subset carries them as printed text.
            try:
                src.generate_appearance_streams()
                src.flatten_annotations("all")
            except Exception as ex:                            # noqa: BLE001
                logger.info("transcriber subset: values not painted before the cut: %s", ex)
        dst = pikepdf.new()
        for i in pages:
            if 0 <= i < n:
                dst.pages.append(src.pages[i])
        out = io.BytesIO()
        dst.save(out)
        return out.getvalue(), False


# ── 2. fetch (cache first) ────────────────────────────────────────────────────
async def fetch(group: SendGroup, *, client: Optional[TranscriberClient] = None,
                cache_get: Optional[Callable[[str, str], Awaitable[Optional[dict]]]] = None,
                cache_put: Optional[Callable[..., Awaitable[None]]] = None) -> GroupResult:
    """Never raises: an error is a GroupResult with `error` set and the document
    stays on today's reading."""
    client = client or _default_client()
    env = client.cfg.env
    resume = ""
    if cache_get is not None:
        try:
            hit = await cache_get(group.hash, env)
        except Exception as ex:                                # noqa: BLE001
            logger.warning("transcriber cache lookup failed: %s", ex)
            hit = None
        if hit and hit.get("status") == "pending":
            # submitted earlier, never collected (a timeout, a crash): poll it again
            # rather than pay for the pages twice; a pending mark older than
            # PENDING_MAX_AGE is stale and a fresh submit is made.
            age = _age_seconds(hit.get("submitted_at"))
            if hit.get("request_id") and (age is None or age <= PENDING_MAX_AGE):
                resume = str(hit["request_id"])
            hit = None
        if hit:
            try:
                res = TranscriberResult.from_json(hit)
                logger.info("TRANSCRIBER_CACHE_HIT hash=%s forms=%s", group.hash[:12],
                            [f.form_number for f in res.forms])
                return GroupResult(group=group, result=res, cached=True)
            except Exception as ex:                            # noqa: BLE001
                logger.warning("transcriber cache entry unreadable: %s", ex)

    async def _remember(rid: str) -> None:
        if cache_put is not None:
            await cache_put(group.hash, env, {"status": "pending", "request_id": rid,
                                              "submitted_at": _now_iso()},
                            pages=len(group.pages), form_numbers=group.label)
    try:
        res = await client.extract(group.data, input_format=group.input_format, pages=len(group.pages),
                                   label=group.label, resume_request_id=resume, on_submitted=_remember)
    except TranscriberError as ex:
        logger.warning("TRANSCRIBER_FALLBACK kind=%s label=%s pages=%d: %s", ex.kind, group.label,
                       len(group.pages), ex.message)
        return GroupResult(group=group, result=None, error=ex.kind)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("TRANSCRIBER_FALLBACK kind=unexpected label=%s: %s", group.label, ex)
        return GroupResult(group=group, result=None, error="unexpected")
    if res.status != "done":
        logger.warning("TRANSCRIBER_FALLBACK kind=%s label=%s: %s", res.status, group.label, res.message[:120])
        return GroupResult(group=group, result=None, error=res.status)
    if not res.forms:
        # ASG answers an unrecognised page with a Rejected / UNKNOWN element; a body
        # with NO element is an anomaly - today's reading, and never cached, or a
        # transient empty reply would answer this file for ever (review, 29 Oct 2026)
        logger.warning("TRANSCRIBER_FALLBACK kind=empty label=%s request=%s", group.label, res.request_id)
        return GroupResult(group=group, result=None, error="empty")
    if cache_put is not None:
        try:
            await cache_put(group.hash, env, res.to_json(), pages=len(group.pages),
                            form_numbers=",".join(f"{f.form_number}:{len(f.pages)}" for f in res.forms))
        except Exception as ex:                                # noqa: BLE001
            logger.warning("transcriber cache write failed: %s", ex)
    return GroupResult(group=group, result=res)


PENDING_MAX_AGE = 3600.0           # a request id is polled again for an hour, then resubmitted


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(stamp: Any) -> Optional[float]:
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(stamp))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:                                          # noqa: BLE001
        return None


# One page budget per PACKAGE (review, 29 Oct 2026): the per-document cap let a
# 20-file upload of 30-page forms send 600 pages. `presubmit_package` opens the
# budget for the upload's task; `read_document` spends from the same one.
import contextvars as _cv
_PACKAGE_BUDGET: "_cv.ContextVar[Optional[dict]]" = _cv.ContextVar("transcriber_package_budget", default=None)


def _spend(pages: int) -> bool:
    b = _PACKAGE_BUDGET.get()
    if b is None:
        return True
    if pages > b["left"]:
        logger.warning("TRANSCRIBER_SKIP reason=package_cap pages=%d left=%d", pages, b["left"])
        return False
    b["left"] -= pages
    return True


def open_package_budget() -> None:
    """A FRESH page budget for the package being read in this task - an upload
    (`presubmit_package`) and an add-documents call alike. Before (review, 29
    Oct 2026) only the pre-submit opened one, so documents added to a package
    read with NO package cap, and a long-lived task kept the last package's
    spent budget. Not live: no budget (nothing is sent)."""
    try:
        cfg = load_config()
        _PACKAGE_BUDGET.set({"left": int(cfg.max_pages_per_package)} if cfg.live else None)
    except Exception:                                          # noqa: BLE001
        _PACKAGE_BUDGET.set(None)


def _refund(pages: int) -> None:
    b = _PACKAGE_BUDGET.get()
    if b is not None:
        b["left"] += int(pages)


_CLIENT: Optional[TranscriberClient] = None


def _default_client() -> TranscriberClient:
    global _CLIENT
    cfg = load_config()
    if _CLIENT is None or _CLIENT.cfg != cfg:
        usage = None
        if cfg.live:
            from repositories.transcriber_repository import add_usage
            usage = add_usage
        _CLIENT = TranscriberClient(cfg, usage=usage)
    return _CLIENT


def reset_client() -> None:
    global _CLIENT
    _CLIENT = None


async def presubmit_package(paths: List[str]) -> int:
    """THE PRE-SUBMIT (29 Oct 2026, review: the wait was inline and sequential - 20
    outside forms = 20 x up to 150 s in one upload). At the start of an upload, every
    PDF whose ACORD pages its own text layer shows (fillable / flattened - a scan
    needs OCR first and waits for its turn) is planned and SUBMITTED at once, its
    request id remembered in the cache as `pending`. When `extract_document`
    reaches the file, `fetch` finds the mark and collects the result ASG has been
    building meanwhile - the same bytes, the same hash, never paid twice. Live
    clients only (a stub answers instantly); never raises. Returns the number sent."""
    cfg = load_config()
    # A FRESH budget for every package: this is the start of an upload, and the
    # worker runs every job in one long-lived task - a budget opened by the first
    # package was spent by every later one (bug hunt, 29 Oct 2026). Opened before
    # the early return, so no upload ever reads on an old package's budget.
    open_package_budget()
    if not (cfg.live and paths):
        return 0
    from repositories.transcriber_repository import get_cached, put_cached
    from services.acord_intake import primble_record
    import asyncio
    client = _default_client()
    sem = asyncio.Semaphore(4)
    planned: set = set()                 # group hashes this pre-submit already sent

    async def one(path: str) -> int:
        if not str(path).lower().endswith(".pdf"):
            return 0
        async with sem:
            try:
                # The cheap half of the reader: page recognition only (footer / box
                # names). The full box read happens once, in `extract_document`
                # (review, 29 Oct 2026: the pre-submit read every PDF twice).
                from services.acord_intake.recognize import recognize
                found = await asyncio.to_thread(recognize, path)
                rec = {"pages": [{"page": pf.page + 1, "kind": pf.kind, "form_id": pf.form_id,
                                  "acord_number": pf.acord_number, "edition": pf.edition}
                                 for pf in found if pf.kind]}
                if any(pf.kind is None and not (pf.text or "").strip() for pf in found):
                    # A page with no text layer may be a SCAN that OCR recognises
                    # later: `extract_document` then plans it WITH that page, a
                    # different sub-PDF and hash - this pre-submit would be paid
                    # for and never collected, and its pages paid again (bug hunt,
                    # 29 Oct 2026). Such a file waits for its turn.
                    return 0
                ours = await asyncio.to_thread(primble_record.carries_record, path)
                group = await asyncio.to_thread(plan, path, rec, has_primble_record=ours, cfg=cfg)
                if group is None:
                    return 0
                if group.hash in planned:
                    return 0                     # the same bytes twice in one upload: sent once
                planned.add(group.hash)
                if await get_cached(group.hash, cfg.env):
                    return 0                     # a result or a running request already exists
                if not _spend(len(group.pages)):
                    return 0
                try:
                    rid = await client.submit_only(group.data, input_format=group.input_format,
                                                   pages=len(group.pages), label=group.label)
                except Exception:
                    # Nothing was sent: the file reads (and spends) in its own turn.
                    _refund(len(group.pages))
                    raise
                await put_cached(group.hash, cfg.env, {"status": "pending", "request_id": rid,
                                                      "submitted_at": _now_iso()},
                                 pages=len(group.pages), form_numbers=group.label)
                return 1
            except Exception as ex:                            # noqa: BLE001
                logger.info("TRANSCRIBER_PRESUBMIT skipped for %s: %s", os.path.basename(str(path)), ex)
                return 0
    sent = sum(await asyncio.gather(*(one(p) for p in paths)))
    if sent:
        logger.info("TRANSCRIBER_PRESUBMIT files=%d sent=%d", len(paths), sent)
    return sent


async def read_document(path: str, acord_record: Optional[dict], *, has_primble_record: bool,
                        ocr_text: str = "") -> Optional[GroupResult]:
    """plan + fetch with the repository cache. The pipeline's one call."""
    cfg = load_config()
    import asyncio
    # Off the event loop: the plan reads every page's text and cuts a sub-PDF
    # (pdfplumber / pikepdf - seconds on a long package).
    group = await asyncio.to_thread(plan, path, acord_record, has_primble_record=has_primble_record,
                                    ocr_text=ocr_text, cfg=cfg)
    if group is None:
        return None
    cache_get = cache_put = None
    if cfg.live:
        from repositories.transcriber_repository import get_cached, put_cached
        cache_get, cache_put = get_cached, put_cached
        # a file not already sent / cached spends from the package's page budget
        if not await get_cached(group.hash, cfg.env) and not _spend(len(group.pages)):
            return None
    return await fetch(group, client=_default_client(), cache_get=cache_get, cache_put=cache_put)


# ── 3. reply -> reader copies ─────────────────────────────────────────────────
def _form_id_for(form_number: str, geo_code: str) -> str:
    from services.acord_intake.recognize import form_id_for_footer
    num = str(form_number or "").strip()
    geo = str(geo_code or "").strip().upper()
    fid = form_id_for_footer(num, geo or None) if num else None
    if fid:
        return fid
    return f"ACORD_{num}" + (f"_{geo}" if geo else "")


_SCHEMA_TYPES: Dict[str, Dict[str, str]] = {}
_UNTICKED_VALUES = frozenset({"0", "off", "n", "no", "false"})
_NAME_SPLIT_RE = re.compile(r"^(?P<prefix>.+?)_MailingAddress_LineOne_(?P<row>[A-Z]{1,2}\d*)$")
_ADDRESS_LINE_RE = re.compile(
    r"^\s*(\d|p\.?\s*o\.?\s*box|po box|one |two |suite|ste\b|unit\b|#|rural route|r\.?r\.?\s*\d|route\b|"
    r"rte\b|highway|hwy\b|building|bldg\b|floor\b|fl\b|apt\b|apartment|c/o\b|attn\b)", re.I)
# Only the INSURED's combined name-and-address box gives up a name line (the probe's
# case): a producer, interest or location block keeps its text whole (review, 29 Oct).
_NAME_SPLIT_PREFIXES = ("NamedInsured",)


def _schema_types(form_id: str) -> Dict[str, str]:
    """{box: field type} of one of our 17 schemas ("/Btn" = a tick box); {} for a
    form we hold no schema for."""
    if form_id in _SCHEMA_TYPES:
        return _SCHEMA_TYPES[form_id]
    types: Dict[str, str] = {}
    try:
        import json
        from services.acord_intake.recognize import _SCHEMA_DIR
        with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json")) as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            types = {k: str((v or {}).get("ft") or "") for k, v in raw.items() if isinstance(v, dict)}
    except Exception:                                          # noqa: BLE001
        types = {}
    _SCHEMA_TYPES[form_id] = types
    return types


def _box_kind(name: str, value: str, form_id: str = "") -> Optional[str]:
    """'check' for a ticked box, 'text' for a value, None to skip. A tick box is
    one our schema types "/Btn" (the probe: `Policy_LineOfBusiness_CyberAndPrivacy_A`
    carries no "Indicator" in its name); for a form we hold no schema for, the
    ACORD naming decides. Transcriber writes 1 / 0 (probe, 29 Oct 2026)."""
    v = str(value or "").strip()
    if not v:
        return None
    ft = _schema_types(form_id).get(name) if form_id else None
    is_tick = (ft == "/Btn") if ft else bool(_INDICATOR_RE.search(name))
    if is_tick:
        if v.lower() in _TICK_VALUES:
            return "check"
        if v.lower() in _UNTICKED_VALUES or len(v) == 1:
            return None
        return "text"                      # a radio group's option word
    return "text"


def _split_names_from_address_blocks(boxes: Dict[str, "TranscribedBox"]) -> Dict[str, str]:
    """{FullName box: first line} for every `<prefix>_MailingAddress_LineOne_<row>` that
    holds a whole NAME-AND-ADDRESS block while the form returned no
    `<prefix>_FullName_<row>` (the newest 125 prints one combined box; the probe
    came back with the insured's name only inside the address block, 29 Oct 2026).
    The first line is the name when it does not read like an address line."""
    out: Dict[str, str] = {}
    for name, box in boxes.items():
        m = _NAME_SPLIT_RE.match(name)
        if not m or m.group("prefix") not in _NAME_SPLIT_PREFIXES or not box.value or "\n" not in box.value:
            continue
        full = f"{m.group('prefix')}_FullName_{m.group('row')}"
        if boxes.get(full) is not None and boxes[full].value:
            continue
        first = box.value.split("\n", 1)[0].strip()
        if first and not _ADDRESS_LINE_RE.match(first) and sum(ch.isalpha() for ch in first) >= 3:
            out[full] = first
    return out


def copies_from(group: SendGroup, result: TranscriberResult) -> List[dict]:
    """The reader's copy dicts (`read.py`), one per form instance Transcriber read,
    pages mapped back onto the uploaded file. Rejected / UNKNOWN pages give none."""
    out: List[dict] = []
    count: Dict[str, int] = {}
    for form in result.forms:
        if form.rejected:
            continue
        fid = _form_id_for(form.form_number, form.geo_code)
        orig_pages = [group.pages[p - 1] for p in form.pages if 1 <= p <= len(group.pages)]
        if not orig_pages:
            continue
        count[fid] = count.get(fid, 0) + 1
        copy = {"form_id": fid, "copy": count[fid], "pages": orig_pages, "kind": "transcriber",
                "edition": form.edition, "boxes": {}, "kinds": {}, "box_page": {}, "raw": {},
                "confidence": {}, "accuracy": form.accuracy, "source": SOURCE,
                "request_id": result.request_id, "acord_number": form.form_number,
                "geo_code": form.geo_code}
        names = _split_names_from_address_blocks(form.boxes)
        for name, box in form.boxes.items():
            kind = _box_kind(name, box.value, fid)
            if kind is None:
                continue
            value = box.value
            if kind == "text" and name in _ADDRESS_HOSTS_OF(names):
                # the block minus the name line it gave up
                value = box.value.split("\n", 1)[1].strip() if "\n" in box.value else box.value
            copy["boxes"][name] = "Yes" if kind == "check" else value
            copy["kinds"][name] = kind
            pg = orig_pages[0]
            if box.page and 1 <= box.page <= len(group.pages):
                pg = group.pages[box.page - 1]
            copy["box_page"][name] = pg
            if box.confidence is not None:
                copy["confidence"][name] = box.confidence
        for full, first in names.items():
            host = full.replace("_FullName_", "_MailingAddress_LineOne_")
            copy["boxes"][full] = first
            copy["kinds"][full] = "text"
            copy["box_page"][full] = copy["box_page"].get(host, orig_pages[0])
            if host in copy["confidence"]:
                copy["confidence"][full] = copy["confidence"][host]
        if copy["boxes"]:
            out.append(copy)
    return out


def _ADDRESS_HOSTS_OF(names: Dict[str, str]) -> set:          # noqa: N802 - a tiny helper
    return {full.replace("_FullName_", "_MailingAddress_LineOne_") for full in names}


def record_entry(group: SendGroup, gr: GroupResult, copies: List[dict]) -> dict:
    """What the document remembers (`doc["acord"]["transcriber"]`): the forms read,
    their accuracy and every eLabel value as evidence - never a secret, never a
    request body."""
    forms = []
    for c in copies:
        forms.append({"form_id": c["form_id"], "acord_number": c.get("acord_number"),
                      "geo_code": c.get("geo_code") or "", "edition": c.get("edition") or "",
                      "pages": [p + 1 for p in c["pages"]], "accuracy": c.get("accuracy"),
                      "boxes_read": len(c["boxes"])})
                      # No values here: a document's record sits in plaintext on the
                      # session row; the values live in the facts (and, encrypted, in
                      # the transcriber_results cache) - review, 29 Oct 2026.
    rejected = []
    if gr.result is not None:
        for f in gr.result.forms:
            if f.rejected:
                rejected.append({"pages": [group.pages[p - 1] + 1 for p in f.pages if 1 <= p <= len(group.pages)],
                                 "form_number": f.form_number, "status": f.status})
    entry = {"env": load_config().env, "request_id": (gr.result.request_id if gr.result else ""),
             "cached": gr.cached, "error": gr.error, "pages_sent": len(group.pages),
             "sent_pages": [p + 1 for p in group.pages], "forms": forms, "rejected": rejected,
             "rule_exceptions": list(gr.result.rule_exceptions) if gr.result else []}
    sealed = seal_elabels(group, gr.result) if gr.result is not None else None
    if sealed:
        entry[ELABELS_KEY] = sealed
    return entry


# ── 4. KEEP EVERYTHING (29 Oct 2026, owner: "never throw anything away") ──────
# Every box Transcriber returned for the document - on any form, ours or one
# outside the 17 (ACORD 807 D&O) - is kept ENCRYPTED on the document record:
# name, value, confidence, page (of the uploaded file), form number / edition.
# Never plaintext on the session row (the earlier plaintext copy was removed for
# privacy). Only the values the reverse map turns into facts are ever used; the
# rest are shown to the producer as "read from the form" and never scored.
ELABELS_KEY = "elabels_enc"
ELABELS_VERSION = 1


def elabel_payload(group: SendGroup, result: TranscriberResult) -> dict:
    """Every returned box of every form element (rejected ones too), pages mapped
    back onto the uploaded file (1-based)."""
    forms = []
    count: Dict[str, int] = {}

    def _orig(p: Optional[int]) -> Optional[int]:
        if p and 1 <= p <= len(group.pages):
            return group.pages[p - 1] + 1
        return None
    for form in result.forms:
        fid = _form_id_for(form.form_number, form.geo_code)
        if not form.rejected:
            count[fid] = count.get(fid, 0) + 1
        forms.append({
            "form_id": fid, "copy": count.get(fid, 0) if not form.rejected else 0,
            "form_number": form.form_number, "geo_code": form.geo_code, "edition": form.edition,
            "form_name": form.form_name, "status": form.status, "rejected": bool(form.rejected),
            "accuracy": form.accuracy, "pages": [p for p in (_orig(x) for x in form.pages) if p],
            "boxes": [{"name": name, "value": box.value, "confidence": box.confidence, "page": _orig(box.page)}
                      for name, box in form.boxes.items()],
        })
    return {"v": ELABELS_VERSION, "forms": forms}


def seal_elabels(group: SendGroup, result: TranscriberResult) -> Optional[str]:
    """The payload, encrypted (`utils.crypto.encrypt_field`). None - and nothing
    stored - when there is nothing to keep or no encryption key: a value off the
    insured's form is never stored in plaintext."""
    payload = elabel_payload(group, result)
    if not any(f["boxes"] for f in payload["forms"]):
        return None
    try:
        import json
        from utils.crypto import encrypt_field
        sealed = encrypt_field(json.dumps(payload, separators=(",", ":")))
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("TRANSCRIBER_ELABELS_NOT_KEPT reason=%s", type(ex).__name__)
        return None
    return sealed if isinstance(sealed, str) and sealed.startswith("enc:") else None


def read_elabels(doc_or_entry: Any) -> Optional[dict]:
    """The decrypted payload of a document (or of its `acord.transcriber` entry),
    None when it keeps none or cannot be decrypted here (another server's key)."""
    entry = doc_or_entry
    if isinstance(entry, dict) and isinstance(entry.get("acord"), dict):
        entry = entry["acord"].get("transcriber")
    if not isinstance(entry, dict):
        return None
    sealed = entry.get(ELABELS_KEY)
    if not (isinstance(sealed, str) and sealed.startswith("enc:")):
        return None
    try:
        import json
        from utils.crypto import decrypt_field_soft
        plain = decrypt_field_soft(sealed)
        data = json.loads(plain) if plain else None
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("transcriber elabels unreadable: %s", type(ex).__name__)
        return None
    return data if isinstance(data, dict) and isinstance(data.get("forms"), list) else None


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_ROW_SUFFIX_RE = re.compile(r"_([A-Z]{1,2}\d*)$")
_LABEL_WORDS = {"Naic": "NAIC", "Fein": "FEIN", "Naics": "NAICS", "Sic": "SIC", "Vin": "VIN", "Csl": "CSL",
                "Url": "URL", "Id": "ID", "Gl": "GL", "Ncci": "NCCI", "Dba": "DBA", "Llc": "LLC"}


def readable_label(name: str) -> str:
    """"DirectorsAndOfficers_RequestedPerClaimLimitAmount_A" ->
    "Directors And Officers - Requested Per Claim Limit Amount (A)". ACORD's own
    words, split; the row letter in brackets. No em-dash (UI copy rule)."""
    n = str(name or "").strip()
    row = ""
    m = _ROW_SUFFIX_RE.search(n)
    if m:
        row, n = m.group(1), n[:m.start()]
    parts = []
    for seg in [x for x in n.split("_") if x]:
        words = [w for w in _CAMEL_RE.split(seg) if w]
        words = [_LABEL_WORDS.get(w.capitalize(), w) if len(w) > 1 else w for w in words]
        parts.append(" ".join(words))
    label = " - ".join(p for p in parts if p) or str(name or "")
    return f"{label} ({row})" if row else label


def _target_text(targets: List[dict]) -> str:
    """What a mapped box feeds, in plain words ("applicant_name", "Locations, row 2: city")."""
    out = []
    for t in targets:
        kind = t.get("t")
        if kind in ("fact", "code", "tick"):
            out.append(str(t.get("fact") or ""))
        elif kind in ("cell", "cell_all"):
            row = t.get("row")
            line = t.get("line")
            where = f" ({line})" if line else (f", row {int(row) + 1}" if isinstance(row, int) else "")
            out.append(f"{t.get('list')}{where}: {t.get('col')}")
        elif kind == "prior":
            out.append(f"prior_coverage_by_line: {t.get('col')}")
        elif kind in ("roster", "roster_ref"):
            out.append("insurer roster")
        elif kind == "by_tick":
            out.append(" / ".join(x for x in (t.get("csl_fact"), t.get("each_fact")) if x))
        elif kind == "symbol":
            out.append("auto_covered_symbols")
        elif kind in ("lob_other", "lob_other_tick"):
            out.append("lines_of_business")
    seen: List[str] = []
    for x in out:
        if x and x not in seen:
            seen.append(x)
    return ", ".join(seen)


def _target_facts(tg: List[dict]) -> List[str]:
    out: List[str] = []
    for t in tg:
        for k in (t.get("fact"), t.get("list"), t.get("csl_fact"), t.get("each_fact")):
            if k:
                out.append(str(k).split("#", 1)[0])
        if t.get("t") == "symbol":
            out.append("auto_covered_symbols")
        if t.get("t") in ("lob_other", "lob_other_tick"):
            out.append("lines_of_business")
        if t.get("t") == "prior":
            out.append("prior_coverage_lines")
        if t.get("t") in ("roster", "roster_ref"):
            out.append("coverage_lines")
    return out


def _box_survived(tg: List[dict], value: str, doc_facts: dict, pkg_facts: Optional[dict]) -> bool:
    """Did this box's reading reach the package? Only when a fact it targets is
    in the document's own facts (the reading and the document-level guards kept
    it), and - when the package's facts are given - the package holds that fact
    with a value the box agrees with (the merge's owner rules kept THIS reading:
    the login's producer, a dec's current policy, a person's answer outrank a
    form). A list / table target counts when the package holds the list.
    Michelle review 2, 30 Oct 2026: the dialog listed boxes as "Used in this
    package" from the reverse map alone, whatever the merge decided."""
    from services.acord_intake.merge_rules import _agrees, _empty
    keys = [k for k in _target_facts(tg) if k]
    for k in keys:
        if _empty((doc_facts or {}).get(k)):
            continue
        if pkg_facts is None:
            return True
        pv = pkg_facts.get(k)
        if _empty(pv):
            continue
        inner = pv.get("value") if isinstance(pv, dict) and "value" in pv else pv
        if isinstance(inner, (list, dict)):
            return True
        if _agrees(k, pv, value) or _agrees(k, pv, (doc_facts or {}).get(k)):
            return True
    return False


def form_values(doc: Any, package_facts: Optional[dict] = None) -> Optional[dict]:
    """The document's Transcriber boxes for the producer, grouped:
      used - a box whose reading reached the package (`_box_survived`: the
             reverse map gives it a fact AND the merge kept that reading);
      read - every other box with a value: read from the form, kept, never scored.
    Unticked boxes are counted, not listed. None when the document keeps none."""
    data = read_elabels(doc)
    if data is None:
        return None
    from services.acord_intake.reverse_map import box_targets, is_known_form, shared_entry
    used: List[dict] = []
    read: List[dict] = []
    unticked = 0
    forms_out = []
    doc_facts = doc.get("facts") if isinstance(doc, dict) and isinstance(doc.get("facts"), dict) else {}
    for form in data["forms"]:
        if not isinstance(form, dict):
            continue
        fid = str(form.get("form_id") or "")
        rejected = bool(form.get("rejected"))
        boxes = {str(b.get("name")): b for b in (form.get("boxes") or []) if isinstance(b, dict) and b.get("name")}
        tb = {n: TranscribedBox(value=str(b.get("value") or ""), confidence=b.get("confidence"), page=b.get("page"))
              for n, b in boxes.items()}
        split = {} if rejected else _split_names_from_address_blocks(tb)
        hosts = _ADDRESS_HOSTS_OF(split)
        rows = []
        for name, b in boxes.items():
            value = str(b.get("value") or "").strip()
            if not value:
                continue
            kind = _box_kind(name, value, fid)
            if kind is None:
                unticked += 1
                continue
            shown = "Ticked" if kind == "check" else value
            if name in hosts and "\n" in value:
                shown = value.split("\n", 1)[1].strip()
            rows.append((name, shown, b.get("confidence"), b.get("page")))
        for full, first in split.items():
            host = boxes.get(full.replace("_FullName_", "_MailingAddress_LineOne_")) or {}
            rows.append((full, first, host.get("confidence"), host.get("page")))
        for name, shown, conf, page in rows:
            item = {"box": name, "label": readable_label(name), "value": shown,
                    "confidence": conf, "page": page, "form_id": fid,
                    "form_number": form.get("form_number"), "edition": form.get("edition")}
            tg = [] if rejected else [t for t in box_targets(fid, name) if t.get("t") not in ("carry", "package")]
            if tg and _box_survived(tg, shown, doc_facts, package_facts):
                item["used_for"] = _target_text(tg)
                item["via"] = "form_map" if is_known_form(fid) else (
                    "shared_dictionary" if shared_entry(name)["status"] == "agreed" else "acord_naming")
                used.append(item)
            else:
                read.append(item)
        forms_out.append({"form_id": fid, "form_number": form.get("form_number"), "edition": form.get("edition"),
                          "status": form.get("status"), "rejected": rejected, "pages": form.get("pages") or [],
                          "accuracy": form.get("accuracy"), "known_form": is_known_form(fid)})
    return {"forms": forms_out, "used": used, "read": read, "unticked": unticked}
