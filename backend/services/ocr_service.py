import asyncio
import base64
import hashlib
import json
import os
import re
import logging
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

import pdfplumber
import httpx
from circuitbreaker import CircuitBreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER
from utils.text_cleaner import clean_text
# Reading-order repair + header-anchored tables for one page. Every page's text
# goes through page_text() (byte-identical to page.extract_text() unless a line
# was riffled - see extraction_arch_change.md) and its tables are emitted inline.
from utils.page_layout import (
    page_words, page_text, detect_tables, render_tables, vision_words,
)

logger = logging.getLogger(__name__)

# Shared executor for all blocking OCR/PDF operations (module-level, not per-call)
_OCR_MAX_WORKERS = (os.cpu_count() or 2) * 2
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=_OCR_MAX_WORKERS)

# Circuit breaker for the external OCR provider.
_vision_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60, name="google_vision")
_GOOGLE_PROVIDER_ALIASES = {"google", "google_vision", "vision"}
_GOOGLE_VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"
_google_vision_client = None

if OCR_PROVIDER not in _GOOGLE_PROVIDER_ALIASES:
    logger.warning(
        "ocr_service: unsupported OCR_PROVIDER=%r; Google Vision is the only "
        "packaged OCR provider and will be used.",
        OCR_PROVIDER,
    )

# ---------------------------------------------------------------------------
# OCR confidence thresholds
# ---------------------------------------------------------------------------
OCR_CONFIDENCE_THRESHOLD = 0.70
_DOC_REVIEW_THRESHOLD    = 0.50
_MIN_NATIVE_TEXT_LEN     = 100
_MAX_LOW_CONF_FRACTION   = 0.40

_OCR_CONFUSION_MAP = str.maketrans({
    "O": "0", "o": "0",
    "l": "1", "I": "1",
    "S": "5", "Z": "2",
    "B": "8", "G": "6",
})


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Read a positive int from the environment, falling back on any bad value.

    Deployment config is not trusted input: a typo must degrade to the default
    rather than crash extraction at import time or produce a nonsensical cap.
    """
    try:
        value = int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        logger.warning("ocr_service: %s is not an integer; using default %d", name, default)
        return default
    if value < minimum:
        logger.warning("ocr_service: %s=%d below minimum %d; using %d", name, value, minimum, minimum)
        return minimum
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        logger.warning("ocr_service: %s is not a number; using default %s", name, default)
        return default
    return max(minimum, value)


# ---------------------------------------------------------------------------
# Batched-OCR tuning
# ---------------------------------------------------------------------------
# Google Vision's images:annotate accepts at most 16 image requests per call.
# Verified empirically against the live API: 16 -> 200 with 16 responses,
# 17 -> HTTP 400 "Too many images per request". This is an API limit, not a
# preference, so it is clamped rather than merely defaulted.
_VISION_HARD_MAX_BATCH   = 16
_VISION_MAX_BATCH        = min(_env_int("OCR_VISION_BATCH", 16), _VISION_HARD_MAX_BATCH)

# Vision caps the *request* at ~20 MB. base64 inflates payloads by ~33%, so the
# raw byte budget per batch is held well under that ceiling. A single oversized
# image is downscaled rather than dropped.
_VISION_MAX_BATCH_BYTES  = _env_int("OCR_VISION_BATCH_BYTES", 6 * 1024 * 1024, minimum=256 * 1024)
_VISION_MAX_IMAGE_BYTES  = _env_int("OCR_VISION_IMAGE_BYTES", 4 * 1024 * 1024, minimum=128 * 1024)

# Concurrent in-flight Vision requests. Vision's default quota is 1800 req/min;
# 4 concurrent batches of 16 is far below that while still hiding network RTT.
_OCR_BATCH_CONCURRENCY   = _env_int("OCR_BATCH_CONCURRENCY", 4)

# Pages are processed in windows so peak memory stays bounded regardless of
# document length: only one window's rendered payloads are resident at a time.
_OCR_PAGE_WINDOW         = _env_int("OCR_PAGE_WINDOW", 24)

# Upper bound on full-page OCR per document. Exceeding it does NOT drop text:
# native text is still kept for every page, and the shortfall is logged and
# flagged for manual review. Silent truncation is never acceptable here.
_OCR_MAX_PAGES_PER_DOC   = _env_int("OCR_MAX_PAGES_PER_DOC", 400)

_PAGE_RENDER_ZOOM        = _env_float("OCR_PAGE_RENDER_ZOOM", 2.0, minimum=1.0)

# Floor for the oversized-page clamp in _render_page_png. Only ever reached by
# sheets far larger than any ACORD form; a reduced-resolution read beats an
# out-of-memory kill, which loses the whole document.
_PAGE_RENDER_MIN_ZOOM    = _env_float("OCR_PAGE_RENDER_MIN_ZOOM", 0.5, minimum=0.05)

# ---------------------------------------------------------------------------
# Embedded-image candidate filter (Path A)
# ---------------------------------------------------------------------------
# These gates decide which embedded images are worth their own OCR call on a
# page that ALREADY has usable native text.
#
# They are deliberately far more permissive than a "is this page scanned?"
# test, because the two error directions are not symmetric under this design:
# a false positive costs one sub-call inside an existing batch and appends a
# company name; a false negative silently loses policy data (the original bug -
# a 120x60pt image holding a policy number scores 1.49% of page area and was
# previously discarded by a 2% gate).
#
# The load-bearing gate is the STORED RASTER size, not the displayed area:
# decorative icons are stored at 32-64px regardless of how they are scaled on
# the page, while any raster that could hold legible text is materially larger.
_EMB_MIN_DISPLAY_PT       = _env_float("OCR_EMB_MIN_DISPLAY_PT", 20.0)
_EMB_MIN_AREA_RATIO       = _env_float("OCR_EMB_MIN_AREA_RATIO", 0.0015)
_EMB_MIN_RASTER_LONG_PX   = _env_int("OCR_EMB_MIN_RASTER_LONG_PX", 150)
_EMB_MIN_RASTER_SHORT_PX  = _env_int("OCR_EMB_MIN_RASTER_SHORT_PX", 40)
_EMB_MAX_IMAGES_PER_PAGE  = _env_int("OCR_EMB_MAX_IMAGES_PER_PAGE", 12)
_EMB_MAX_IMAGES_PER_DOC   = _env_int("OCR_EMB_MAX_IMAGES_PER_DOC", 60)

# Searchable-scan guard.
#
# Adobe Scan, ABBYY and essentially every modern scanner emit a "searchable
# PDF": the page bitmap PLUS an invisible text layer holding that scanner's own
# OCR of it. Such a page has a full native text layer AND a full-page image, so
# it takes Path A - and OCR'ing the image would emit the very same content a
# second time. clean_text cannot collapse the duplicate, because the scanner's
# OCR and Vision's OCR are never byte-identical, so the extractor would receive
# two subtly different copies of every figure on the page.
#
# Two independent signals must BOTH agree before an image is skipped, and each
# was chosen because the other one alone was measured to fail:
#
#   glyph AREA over the image     - how densely native text covers it
#   vertical BAND spread          - over how much of the image's INKED height
#                                   that text is distributed (10 bands). Spread
#                                   is measured against where the image really
#                                   has content, not against the page: a
#                                   scanned certificate filling only the top
#                                   half still carries a COMPLETE OCR layer
#                                   over that half, and judging it against the
#                                   full page would re-OCR and duplicate it.
#                                   See _image_ink_bands.
#
# Word COUNT is not usable and is actively dangerous: a full-page scan carrying
# only a Bates stamp already has 14-50 native words inside the image's box, and
# skipping on that basis would discard the entire scan - the exact silent data
# loss this whole change exists to eliminate.
#
# Measured against realistic documents (a scanned ACORD 25, not synthetic text):
#
#                                        words    area    bands   decision
#     real searchable ACORD 25 dec page     95    8.3%     100%   skip
#     dense searchable scan                101    9.1%     100%   skip
#     scan + diagonal CONFIDENTIAL mark     27    5.4%      70%   OCR
#     scan + header AND footer blocks       90    4.2%      40%   OCR
#     scan + 14-line native header          84    4.4%      30%   OCR
#     scan + Bates / confidential banner    14    1.0%      20%   OCR
#     pasted exhibit, no overlap             0    0.0%       0%   OCR
#
# Area alone would misclassify nothing here but has only a 1.5x gap; bands
# alone would wrongly skip the watermarked scan. Requiring both means a page
# has to defeat two independent tests to be wrongly skipped, and either one
# failing sends it to OCR. Both thresholds also fail in the safe direction: a
# sparse OCR layer drops below them and gets OCR'd, costing some duplicated
# text rather than losing a page.
_EMB_NATIVE_COVER_RATIO     = _env_float("OCR_EMB_NATIVE_COVER_RATIO", 0.06)
_EMB_NATIVE_COVER_BANDS     = _env_float("OCR_EMB_NATIVE_COVER_BANDS", 0.80)
_EMB_NATIVE_COVER_MIN_WORDS = _env_int("OCR_EMB_NATIVE_COVER_MIN_WORDS", 8)
_EMB_NATIVE_BAND_COUNT      = _env_int("OCR_EMB_NATIVE_BAND_COUNT", 10, minimum=2)

# "Ink" has to be defined relative to the paper, not against a fixed value.
# A fixed cutoff of 250 was measured to classify EVERY band of a real scan as
# inked as soon as the paper rendered at byte 249 or darker - which is almost
# always, since scanner output carries lamp falloff, paper tint and JPEG noise.
# The ink-relative band test then silently degenerated into the page-relative
# one it exists to replace, and a searchable scan whose content fills only part
# of the sheet was re-OCR'd and duplicated.
#
# Paper level is therefore measured per image (90th-percentile luminance of the
# probe render) and ink is anything materially darker than it.
_EMB_INK_PAPER_PERCENTILE   = _env_float("OCR_EMB_INK_PAPER_PCT", 0.90, minimum=0.5)
_EMB_INK_MARGIN             = _env_int("OCR_EMB_INK_MARGIN", 12, minimum=1)

# Minimum inked bands before the ink-relative basis is trusted. Without this a
# nearly-empty image inks one band, and any native text landing in that band
# scores 1/1 = 100% spread and skips the image on a single-band coincidence.
# Below the floor the guard falls back to the page-relative measure, which is
# the conservative direction (it OCRs, costing duplication rather than loss).
_EMB_INK_MIN_BANDS          = _env_int("OCR_EMB_INK_MIN_BANDS", 3, minimum=1)

# Decoding an embedded raster costs width*height*3 bytes of RAM: a 600 DPI
# letter scan is ~34 Mpx = ~101 MB, and a 1200 DPI one would be ~400 MB, enough
# to OOM a small instance. Above this cap the image is NOT decoded; the page
# region it occupies is rendered at a bounded zoom instead, which reaches the
# same pixels with a fixed memory ceiling.
_EMB_MAX_DECODE_PIXELS    = _env_int("OCR_EMB_MAX_DECODE_PIXELS", 25_000_000, minimum=1_000_000)
_EMB_REGION_MAX_ZOOM      = _env_float("OCR_EMB_REGION_MAX_ZOOM", 3.0, minimum=1.0)

# Formats Google Vision decodes natively. Anything else (JBIG2, JPX/JPEG2000,
# CCITT, raw) is transcoded to PNG before sending - these are common in scanned
# PDFs, and passing them through untouched would fail per-image at the API.
_VISION_NATIVE_IMAGE_EXTS = {"jpeg", "jpg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico"}

# Marker prefixing OCR text recovered from an embedded image.
#
# Deliberately joined into the surrounding page text with single newlines and
# with internal blank-line runs collapsed. utils.text_cleaner.clean_text splits
# on blank lines, drops paragraphs under 10 characters, and de-duplicates by
# MD5 - so introducing a blank line here would both change existing paragraph
# boundaries for every document and risk a short image block being dropped
# outright. Keeping the block inside the current paragraph guarantees it
# survives and leaves clean_text's behaviour on existing documents unchanged.
_EMBEDDED_IMAGE_MARKER = "[Embedded image text - page {page}]"

# Page boundary marker, multi-page documents only (a single page stays byte-
# identical to the pre-2026-08-22 output). Same single-newline discipline as the
# image marker. The wording is deliberate: utils.text_cleaner.clean_text strips
# any "Page N of M" pattern as page furniture, so that form would be deleted on
# its way to the model. Emitted only for a page that has content (text, a table
# or an image block) - a blank multi-page scan must still read as empty to the
# `len(text) < 30` guards in the pipeline. OCR_PAGE_MARKERS=0 disables.
_PAGE_MARKER = "[Document page {page}]"
_PAGE_MARKERS_ON = os.getenv("OCR_PAGE_MARKERS", "1").strip().lower() not in ("0", "false", "no", "off")


def _normalize_token(token: str) -> str:
    return token.translate(_OCR_CONFUSION_MAP)


def _numeric_correction_score(token: str) -> float:
    norm = _normalize_token(token)
    if not norm.replace(".", "").replace(",", "").isdigit():
        return 0.0
    diff_chars = sum(1 for a, b in zip(token, norm) if a != b)
    return min(1.0, diff_chars * 0.15)


def _flag_for_manual_review(
    full_text: str,
    low_conf_tokens: List[str],
    total_token_count: int,
    source_path: str,
) -> bool:
    if not full_text.strip() or len(full_text.strip()) < 50:
        logger.warning(
            f"ocr_service: MANUAL REVIEW flagged — empty/near-empty OCR output: {source_path}"
        )
        return True
    if total_token_count > 0:
        frac = len(low_conf_tokens) / total_token_count
        if frac > _MAX_LOW_CONF_FRACTION:
            logger.warning(
                f"ocr_service: MANUAL REVIEW flagged — {frac:.0%} low-confidence tokens "
                f"({len(low_conf_tokens)}/{total_token_count}): {source_path}"
            )
            return True
    return False


# ---------------------------------------------------------------------------
# Provider OCR implementations (sync — called via executor)
# ---------------------------------------------------------------------------

def _materialize_google_credentials_json() -> None:
    """Allow deploying Google service-account JSON as a single secret env var."""
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw:
        return

    path = os.path.join(tempfile.gettempdir(), "google-vision-credentials.json")
    if not os.path.exists(path):
        try:
            data = json.dumps(json.loads(raw))
        except json.JSONDecodeError:
            data = raw
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


def _get_google_vision_client():
    global _google_vision_client
    if _google_vision_client is None:
        _materialize_google_credentials_json()
        from google.cloud import vision as gvision
        _google_vision_client = gvision.ImageAnnotatorClient()
        logger.info("Google Vision OCR client initialised")
    return _google_vision_client


# One pooled HTTP client for the REST path. The previous code built a fresh
# httpx.Client per image, paying a full TCP+TLS handshake for every page.
_http_client: Optional[httpx.Client] = None
_http_client_lock = threading.Lock()


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        with _http_client_lock:
            if _http_client is None:
                _http_client = httpx.Client(
                    timeout=httpx.Timeout(_env_float("GOOGLE_VISION_TIMEOUT_SECONDS", 60.0, minimum=5.0)),
                    limits=httpx.Limits(
                        max_connections=max(4, _OCR_BATCH_CONCURRENCY * 2),
                        max_keepalive_connections=max(2, _OCR_BATCH_CONCURRENCY),
                    ),
                )
    return _http_client


def _use_rest_api() -> bool:
    """REST when an API key is configured, gRPC service-account client otherwise."""
    return bool(os.getenv("GOOGLE_VISION_API_KEY", "").strip())


@dataclass
class _OcrResult:
    """One image's OCR outcome. `ok` distinguishes 'read nothing' from 'failed'.

    `words` carries Vision's per-word boxes ({x0, x1, top, bottom, text}, pixels)
    so a scanned page can run the same header-anchored table detector as a native
    one. Always optional: an empty list means "geometry unavailable", never an
    error, and every existing caller that builds _OcrResult by keyword is unchanged.
    """
    text: str = ""
    low_conf: List[str] = field(default_factory=list)
    total_tokens: int = 0
    ok: bool = True
    words: List[dict] = field(default_factory=list)


def _extract_low_conf_from_annotation(annotation: dict) -> Tuple[str, List[str], int]:
    full_text = (annotation.get("text") or "").strip()
    low_conf: List[str] = []
    total = 0

    for page in annotation.get("pages") or []:
        for block in page.get("blocks") or []:
            for para in block.get("paragraphs") or []:
                for word in para.get("words") or []:
                    total += 1
                    word_text = "".join(
                        symbol.get("text", "")
                        for symbol in word.get("symbols") or []
                    )
                    confidence = float(word.get("confidence", 1.0) or 0.0)
                    penalty = _numeric_correction_score(word_text)
                    adj_conf = max(0.0, confidence - penalty)
                    if adj_conf < OCR_CONFIDENCE_THRESHOLD:
                        low_conf.append(_normalize_token(word_text))

    return full_text, low_conf, total


def _extract_low_conf_from_proto(annotation) -> Tuple[str, List[str], int]:
    """Same as _extract_low_conf_from_annotation for the gRPC client's protos."""
    full_text = (annotation.text or "").strip() if annotation else ""
    low_conf: List[str] = []
    total = 0
    for page in getattr(annotation, "pages", []) or []:
        for block in page.blocks:
            for para in block.paragraphs:
                for word in para.words:
                    total += 1
                    word_text = "".join(s.text for s in word.symbols)
                    penalty = _numeric_correction_score(word_text)
                    adj_conf = max(0.0, word.confidence - penalty)
                    if adj_conf < OCR_CONFIDENCE_THRESHOLD:
                        low_conf.append(_normalize_token(word_text))
    return full_text, low_conf, total


def _is_retryable(exc: BaseException) -> bool:
    """Retry only what a retry can actually fix.

    Transport errors, timeouts, 429 and 5xx are transient. Any other 4xx is a
    permanent rejection of this exact request (malformed image, bad key, image
    too large) - retrying it burns the backoff budget three times over and then
    does it again at every level of the split-on-failure recursion, turning one
    bad image into tens of seconds of dead time.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    if isinstance(exc, (ValueError, TypeError)):
        return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _vision_rest_batch(payloads: Sequence[bytes]) -> List[_OcrResult]:
    """POST up to _VISION_MAX_BATCH images in ONE images:annotate request.

    Raises on transport/HTTP failure so tenacity retries the whole batch and
    the circuit breaker sees the failure. Per-image errors reported inside a
    200 response are isolated to that image and never fail its neighbours.
    """
    api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_VISION_API_KEY is not configured")
    if len(payloads) > _VISION_HARD_MAX_BATCH:
        raise ValueError(
            f"batch of {len(payloads)} exceeds Vision's hard limit of {_VISION_HARD_MAX_BATCH}"
        )

    body = {
        "requests": [
            {
                "image": {"content": base64.b64encode(p).decode("ascii")},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
            for p in payloads
        ]
    }
    # Scale the read timeout with batch size; a 16-image batch legitimately
    # takes longer than a single image.
    base_timeout = _env_float("GOOGLE_VISION_TIMEOUT_SECONDS", 60.0, minimum=5.0)
    timeout = min(300.0, base_timeout + 6.0 * max(0, len(payloads) - 1))

    response = _get_http_client().post(
        _GOOGLE_VISION_API_URL, params={"key": api_key}, json=body, timeout=timeout,
    )
    response.raise_for_status()
    items = response.json().get("responses") or []

    out: List[_OcrResult] = []
    for idx in range(len(payloads)):
        item = items[idx] if idx < len(items) else {}
        if item.get("error"):
            message = item["error"].get("message", "unknown Google Vision error")
            logger.warning("ocr_service: Vision per-image error [%d]: %s", idx, message)
            out.append(_OcrResult(ok=False))
            continue
        annotation = item.get("fullTextAnnotation") or {}
        text, low_conf, total = _extract_low_conf_from_annotation(annotation)
        out.append(_OcrResult(text=text, low_conf=low_conf, total_tokens=total,
                              words=vision_words(annotation)))
    return out


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _vision_grpc_batch(payloads: Sequence[bytes]) -> List[_OcrResult]:
    """Service-account equivalent of _vision_rest_batch via batch_annotate_images."""
    from google.cloud import vision as gvision

    if len(payloads) > _VISION_HARD_MAX_BATCH:
        raise ValueError(
            f"batch of {len(payloads)} exceeds Vision's hard limit of {_VISION_HARD_MAX_BATCH}"
        )

    client = _get_google_vision_client()
    feature = gvision.Feature(type_=gvision.Feature.Type.DOCUMENT_TEXT_DETECTION)
    requests = [
        gvision.AnnotateImageRequest(image=gvision.Image(content=p), features=[feature])
        for p in payloads
    ]
    response = client.batch_annotate_images(requests=requests)
    items = list(response.responses or [])

    out: List[_OcrResult] = []
    for idx in range(len(payloads)):
        if idx >= len(items):
            out.append(_OcrResult(ok=False))
            continue
        item = items[idx]
        if item.error.message:
            logger.warning("ocr_service: Vision per-image error [%d]: %s", idx, item.error.message)
            out.append(_OcrResult(ok=False))
            continue
        text, low_conf, total = _extract_low_conf_from_proto(item.full_text_annotation)
        out.append(_OcrResult(text=text, low_conf=low_conf, total_tokens=total,
                              words=vision_words(item.full_text_annotation)))
    return out


def _vision_batch_call(payloads: Sequence[bytes]) -> List[_OcrResult]:
    return _vision_rest_batch(payloads) if _use_rest_api() else _vision_grpc_batch(payloads)


def _ocr_batch_sync(payloads: Sequence[bytes], _depth: int = 0) -> List[_OcrResult]:
    """Circuit-broken, failure-isolating batch OCR (sync; called via executor).

    On a whole-request failure the batch is split in half and each half retried
    independently, so a single undecodable image cannot destroy the results of
    the 15 valid images travelling with it. Recursion is bounded by log2(batch).
    Never raises: a permanently failing payload yields ok=False for that item.
    """
    if not payloads:
        return []

    if _vision_cb.opened:
        logger.warning(
            "ocr_service: Google Vision circuit OPEN — skipping OCR for %d image(s)",
            len(payloads),
        )
        return [_OcrResult(ok=False) for _ in payloads]

    try:
        return _vision_cb.call(_vision_batch_call, payloads)
    except Exception as ex:
        if len(payloads) == 1:
            logger.error("ocr_service: Vision failed for image: %s", ex)
            return [_OcrResult(ok=False)]
        mid = len(payloads) // 2
        logger.warning(
            "ocr_service: Vision batch of %d failed (%s) — splitting into %d + %d",
            len(payloads), ex, mid, len(payloads) - mid,
        )
        return (
            _ocr_batch_sync(payloads[:mid], _depth + 1)
            + _ocr_batch_sync(payloads[mid:], _depth + 1)
        )


def _ocr_google_vision(img_path: str) -> Tuple[str, List[str], int]:
    """Single-image OCR by path. Preserved for the public image entry point."""
    try:
        with open(img_path, "rb") as f:
            content = f.read()
    except OSError as ex:
        logger.error(f"ocr_service: cannot read image {img_path}: {ex}")
        return "", [], 0
    result = _ocr_batch_sync([content])[0]
    return result.text, result.low_conf, result.total_tokens


def _run_ocr_provider(img_path: str) -> Tuple[str, List[str], int]:
    """Dispatch to the configured OCR provider (sync, called via executor)."""
    return _ocr_google_vision(img_path)


# ---------------------------------------------------------------------------
# Async batch scheduling
# ---------------------------------------------------------------------------

def _group_payloads(sizes: Sequence[int]) -> List[List[int]]:
    """Group payload indices into batches bounded by BOTH count and total bytes.

    Vision limits the whole request, not just the image count, so a batch of 16
    large page renders can breach the request ceiling even though the count is
    legal. An item that alone exceeds the byte budget still gets its own batch
    rather than being dropped (it is already downscaled by this point).
    """
    batches: List[List[int]] = []
    current: List[int] = []
    current_bytes = 0
    for idx, size in enumerate(sizes):
        if current and (
            len(current) >= _VISION_MAX_BATCH
            or current_bytes + size > _VISION_MAX_BATCH_BYTES
        ):
            batches.append(current)
            current, current_bytes = [], 0
        current.append(idx)
        current_bytes += size
    if current:
        batches.append(current)
    return batches


async def _ocr_payloads(payloads: Sequence[bytes]) -> List[_OcrResult]:
    """OCR a list of images with bounded-concurrency batching.

    Results are returned positionally aligned with `payloads` regardless of the
    order batches complete in, so downstream page assembly stays deterministic.
    """
    if not payloads:
        return []

    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(_OCR_BATCH_CONCURRENCY)
    results: List[_OcrResult] = [_OcrResult(ok=False) for _ in payloads]

    async def run_batch(indices: List[int]) -> None:
        chunk = [payloads[i] for i in indices]
        async with sem:
            batch_results = await loop.run_in_executor(_OCR_EXECUTOR, _ocr_batch_sync, chunk)
        for pos, res in zip(indices, batch_results):
            results[pos] = res

    batches = _group_payloads([len(p) for p in payloads])
    logger.info(
        "ocr_service: dispatching %d image(s) in %d Vision batch(es)",
        len(payloads), len(batches),
    )
    await asyncio.gather(*(run_batch(b) for b in batches))
    return results


# ---------------------------------------------------------------------------
# Public OCR dispatcher
# ---------------------------------------------------------------------------

# ASYNC-SAFE
async def ocr_image_file(img_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for an image file.
    Runs blocking OCR in a thread pool executor.
    """
    loop = asyncio.get_running_loop()
    # Queue-depth monitoring: warn when all worker threads are busy
    active = len([t for t in _OCR_EXECUTOR._threads if t.is_alive()])
    if active >= _OCR_MAX_WORKERS:
        logger.warning(
            "ocr_service: all %d OCR executor threads busy — request will queue",
            _OCR_MAX_WORKERS,
        )
    full_text, low_conf, total = await loop.run_in_executor(
        _OCR_EXECUTOR, _run_ocr_provider, img_path
    )

    low_conf = list(dict.fromkeys(low_conf))

    if _flag_for_manual_review(full_text, low_conf, total, img_path):
        low_conf = ["needs_manual_review"] + low_conf

    return full_text, low_conf


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def extract_images_from_pdf(pdf_path: str) -> List[str]:
    """Render each PDF page as PNG via PyMuPDF at 2x zoom. Caller owns cleanup.

    Retained for backward compatibility and as the last-resort whole-document
    fallback. The main pipeline renders to memory instead (see _render_page_png)
    so it never writes intermediate PNGs into UPLOAD_DIR.
    """
    out_paths: List[str] = []
    doc = None
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            mat   = fitz.Matrix(2.0, 2.0)
            pix   = page.get_pixmap(matrix=mat)
            fname = os.path.join(UPLOAD_DIR, f"page_{uuid.uuid4().hex[:8]}_{page_num}.png")
            pix.save(fname)
            out_paths.append(fname)
    except Exception as ex:
        logger.warning(f"PDF page rendering failed (PyMuPDF): {ex}")
    finally:
        _safe_close(doc)
    return out_paths


def _safe_close(doc) -> None:
    """Close a PyMuPDF document, ignoring an already-closed/None handle.

    An unclosed fitz.Document keeps an OS handle on the file. On Windows that
    makes the caller's os.remove() of the uploaded file fail with WinError 32,
    which form_routes swallows as a bare OSError - leaving the uploaded
    document (PII) on disk indefinitely with no log line. Every fitz.open in
    this module is therefore paired with this in a finally block.
    """
    if doc is None:
        return
    try:
        doc.close()
    except Exception:
        pass


# ── Two-column label/value scramble recovery ──────────────────────────────
# pdfplumber's default extract_text() (and layout=True, and Google Vision's
# own document_text_detection - both tested, both fail identically) read a
# page in a single global top-to-bottom order. On a genuine two-column
# label/value block (e.g. "CARRIER" in a left column, the carrier name in a
# right column) whose row heights drift even slightly between the two
# columns - common in Word/reporting-engine table exports - that single
# reading order interleaves the wrong label with the wrong value ("CARRIER:
# 84-2210987", the actual FEIN, instead of the actual carrier name).
#
# Recovery: detect the corruption by its fingerprint (a meaningful fraction
# of lines are a bare label with NOTHING after it on the same line - which a
# correctly-paired document essentially never produces), then reconstruct
# just that y-band by splitting words into two x-clusters and pairing lines
# by their ORDINAL position within each column (not by matching absolute
# y-coordinates, which is what breaks under drift). The reflow is scoped to
# only the y-band containing the scrambled lines - not the whole page - so a
# genuine multi-column table elsewhere on the same page (Schedule of
# Hazards, a vehicle schedule, ...) is left untouched. If the fingerprint
# isn't present, or the reflow doesn't actually reduce it, the untouched
# default extraction is used - this never makes a normal document worse.
_BARE_LABEL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9 /\-\']{1,40}:\s*$')
_COLUMN_GAP_THRESHOLD = 40   # points; the x-gap that marks a real column boundary


def _cluster_words_into_lines(words: list, y_tol: float = 4) -> List[str]:
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: List[list] = []
    cur: list = []
    cur_top: Optional[float] = None
    for w in words:
        if cur and abs(w["top"] - cur_top) > y_tol:
            lines.append(cur)
            cur = []
        cur.append(w)
        cur_top = w["top"] if cur_top is None else (cur_top if abs(w["top"] - cur_top) <= y_tol else w["top"])
    if cur:
        lines.append(cur)
    return [" ".join(x["text"] for x in sorted(ln, key=lambda w: w["x0"])) for ln in lines]


def _reflow_two_column_words(words: list) -> Optional[str]:
    """Split words into two x-clusters at the single largest horizontal gap
    and pair lines by ordinal position within each column. Returns None when
    no gap wide enough to be a real column boundary is found."""
    if not words:
        return None
    xs = sorted(w["x0"] for w in words)
    gaps = sorted(
        ((xs[i + 1] - xs[i], xs[i], xs[i + 1]) for i in range(len(xs) - 1)),
        reverse=True,
    )
    if not gaps or gaps[0][0] < _COLUMN_GAP_THRESHOLD:
        return None
    split_x = (gaps[0][1] + gaps[0][2]) / 2
    left  = _cluster_words_into_lines([w for w in words if w["x0"] < split_x])
    right = _cluster_words_into_lines([w for w in words if w["x0"] >= split_x])
    n = max(len(left), len(right))
    out = []
    for i in range(n):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        out.append(f"{l} {r}".strip())
    return "\n".join(out)


def _extract_page_text_smart(page, pw=None) -> str:
    """Default extraction, unless the page shows the bare-label scramble
    fingerprint - then attempt a scoped column-reflow recovery and use it
    only if that recovery actually reduces the fingerprint. See module
    comment above for the full rationale.

    "Default" is page_layout.page_text: byte-identical to page.extract_text()
    on every page without a riffled line (pinned by test), and the riffle
    repair on the ones that have one. The same clean words feed the reflow,
    so a zone that is BOTH riffled and column-scrambled is repaired on both
    axes instead of the zone re-extraction reintroducing the riffle.
    `pw` is an optional precomputed page_words() result (the table pass needs
    the same words; computing them once per page keeps the cost flat)."""
    if pw is None:
        try:
            pw = page_words(page)
        except Exception:
            pw = None
    default = page_text(page, pw)[0] if pw is not None else (page.extract_text() or "")

    try:
        words = pw[0] if pw is not None else page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return default
    if not words:
        return default

    # Line groups WITH bounding boxes (needed to find the scrambled y-band).
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    groups: List[list] = []
    cur: list = []
    cur_top: Optional[float] = None
    for w in sorted_words:
        if cur and abs(w["top"] - cur_top) > 4:
            groups.append(cur)
            cur = []
        cur.append(w)
        cur_top = w["top"] if cur_top is None else (cur_top if abs(w["top"] - cur_top) <= 4 else w["top"])
    if cur:
        groups.append(cur)

    lines_bbox = []
    for g in groups:
        text = " ".join(x["text"] for x in sorted(g, key=lambda w: w["x0"]))
        lines_bbox.append((text, min(x["top"] for x in g), max(x["bottom"] for x in g)))

    bare = [(t, top, bot) for t, top, bot in lines_bbox if _BARE_LABEL_RE.match(t.strip())]
    total_lines = len(lines_bbox) or 1
    if len(bare) < 3 or (len(bare) / total_lines) < 0.15:
        return default  # no scramble fingerprint - untouched, zero risk

    line_heights = [b - t for _, t, b in lines_bbox if b > t]
    avg_h = (sum(line_heights) / len(line_heights)) if line_heights else 12
    zone_top    = max(0.0, min(top for _, top, _ in bare) - avg_h * 2)
    zone_bottom = min(page.height, max(bot for _, _, bot in bare) + avg_h * (len(bare) + 3))

    try:
        zone = page.within_bbox((0, zone_top, page.width, zone_bottom))
        zone_pw = page_words(zone)
        zone_words = zone_pw[0]
        zone_default = page_text(zone, zone_pw)[0]
    except Exception:
        return default

    reflowed_zone = _reflow_two_column_words(zone_words)
    if reflowed_zone is None:
        return default

    bare_before = sum(1 for l in zone_default.splitlines() if _BARE_LABEL_RE.match(l.strip()))
    bare_after  = sum(1 for l in reflowed_zone.splitlines() if _BARE_LABEL_RE.match(l.strip()))
    if bare_after >= bare_before:
        return default  # reflow didn't actually help here - don't ship a guess

    try:
        before_text = page_text(page.within_bbox((0, 0, page.width, zone_top)))[0]
        after_text  = page_text(page.within_bbox((0, zone_bottom, page.width, page.height)))[0]
    except Exception:
        return default

    parts = [p for p in (before_text, reflowed_zone, after_text) if p.strip()]
    return "\n".join(parts)


# Lines-mode pdfplumber tables (ruled grids) are kept as a per-page FALLBACK for
# pages where the header-anchored detector found nothing. They are the only thing
# the old end-of-document table append ever produced, and on every insurance page
# in the corpus it produced nothing - but a carrier form with a real ruled grid
# still deserves it. Capped because page.extract_tables() is O(objects) and was
# observed blocking on long packages; the header-anchored pass is O(words) and
# already has the words, so it runs on every page.
_RULED_TABLE_PAGE_LIMIT = int(os.getenv("TABLE_EXTRACT_PAGE_LIMIT", "40"))


def _ruled_tables(page) -> List[dict]:
    """pdfplumber lines-mode tables in page_layout's table shape (first row = header)."""
    out: List[dict] = []
    try:
        for tbl in page.extract_tables() or []:
            rows = [[(str(c).strip() if c is not None else "") for c in row] for row in tbl]
            rows = [r for r in rows if any(r)]
            if len(rows) >= 2 and len(rows[0]) >= 2:
                out.append({"section": None, "header": rows[0], "rows": rows[1:],
                            "top": 0.0, "bottom": 0.0})
    except Exception as ex:                                  # noqa: BLE001
        logger.debug("ocr_service: ruled-table fallback failed: %s", ex)
    return out


def _pdfplumber_extract_pages_structured(pdf_path: str) -> List[Tuple[str, str]]:
    """Per page: (native text through the reflow recovery, rendered table block).

    One pdfplumber pass computes the page's clean words once and feeds BOTH the
    text (via _extract_page_text_smart) and the table detector. Empty strings for
    a page with no extractable native text / no table. A table failure never
    costs the page its text."""
    pages: List[Tuple[str, str]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for idx, page in enumerate(pdf.pages):
                text, tables_block = "", ""
                pw = None
                try:
                    pw = page_words(page)
                except Exception as ex:                      # noqa: BLE001
                    logger.debug("ocr_service: page_words failed on page %d: %s", idx + 1, ex)
                try:
                    text = _extract_page_text_smart(page, pw) or ""
                except Exception as page_ex:
                    # One malformed page must not cost the whole document.
                    logger.warning(
                        "pdfplumber: page %d failed on %s: %s", idx, pdf_path, page_ex
                    )
                try:
                    tables = detect_tables(pw[0]) if pw else []
                    if not tables and idx < _RULED_TABLE_PAGE_LIMIT:
                        tables = _ruled_tables(page)
                    if tables:
                        tables_block = render_tables(tables, idx + 1)
                except Exception as ex:                      # noqa: BLE001
                    logger.warning("ocr_service: table pass failed on page %d of %s: %s",
                                   idx + 1, pdf_path, ex)
                pages.append((text, tables_block))
    except Exception as ex:
        logger.error(f"pdfplumber error on {pdf_path}: {ex}")
    return pages


def _pdfplumber_extract_pages(pdf_path: str) -> List[str]:
    """Per-page native text, each page passed through the column-reflow
    recovery. Empty string for a page with no extractable native text."""
    return [text for text, _ in _pdfplumber_extract_pages_structured(pdf_path)]


def _pdfplumber_extract(pdf_path: str) -> str:
    """Sync pdfplumber text extraction — called via executor."""
    return "".join(t + "\n" for t in _pdfplumber_extract_pages(pdf_path) if t)


def _pdf_page_count(pdf_path: str) -> int:
    """Page count via PyMuPDF. Returns 0 when the file cannot be opened."""
    doc = None
    try:
        import fitz
        doc = fitz.open(pdf_path)
        return doc.page_count
    except Exception as ex:
        logger.warning(f"ocr_service: cannot determine page count for {pdf_path}: {ex}")
        return 0
    finally:
        _safe_close(doc)


# ---------------------------------------------------------------------------
# Embedded-image extraction (Path A)
# ---------------------------------------------------------------------------

@dataclass
class _OcrJob:
    """One queued OCR unit: either a whole rendered page or one embedded image."""
    kind: str          # "page" | "image"
    page_idx: int
    payload: bytes


@dataclass
class _DocBudget:
    """Cross-window state: image dedup keys, per-document caps, and the tally
    that explains what happened to every embedded image.

    The caps are read through default_factory rather than as plain defaults so
    they resolve at construction time. A bare default would freeze the value at
    class-creation time, making the limits impossible to override at runtime
    and silently ignoring any later change to the module constants.

    The counters exist because this module's failure mode is SILENT data loss.
    Knowing only "7 images OCR'd" tells an operator nothing about whether the
    filter quietly discarded fifty more; the breakdown makes over-filtering
    visible in ordinary production logs instead of requiring a repro.
    """
    seen_image_keys: Set[str] = field(default_factory=set)
    # Xrefs already accepted for OCR. A cheap pre-check that avoids rebuilding
    # (and, for JBIG2/CCITT/JPX, fully re-decoding) the payload of a letterhead
    # that recurs on every page just to discover it hashes to something already
    # seen. Only populated when an image is actually accepted, never when one is
    # dropped at a cap - otherwise a capped image would suppress its own later
    # occurrences and turn a cost into silent loss.
    seen_xrefs: Set[int] = field(default_factory=set)
    images_remaining: int = field(default_factory=lambda: _EMB_MAX_IMAGES_PER_DOC)
    full_ocr_remaining: int = field(default_factory=lambda: _OCR_MAX_PAGES_PER_DOC)
    pages_over_cap: int = 0

    # Disposition of every image encountered on a Path A page. These partition
    # `images_examined` exactly, so a mismatch means a branch is unaccounted for.
    images_examined: int = 0
    skipped_small: int = 0        # failed the raster / displayed-size gates
    skipped_covered: int = 0      # a native text layer already transcribes it
    skipped_unreadable: int = 0   # could not decode or re-encode the raster
    skipped_duplicate: int = 0    # same content already OCR'd on an earlier page
    skipped_capped: int = 0       # hit a per-page or per-document cap

    # Loss that a cap caused, tracked separately from the partition above so it
    # can raise needs_manual_review. `skipped_capped` says how the tally splits;
    # these two say a broker is looking at a form built from less than we were
    # handed. A cap that trims real candidates is degradation, and this module's
    # whole failure mode is that degradation is invisible - so it is surfaced,
    # exactly as pages_over_cap already is for full-page OCR.
    images_over_cap: int = 0             # candidates dropped at a cap
    pages_images_unexamined: int = 0     # pages not even looked at, cap spent
    pages_render_failed: int = 0         # scanned page that would not rasterise


def _encode_pixmap(pix) -> Optional[bytes]:
    """Encode a Pixmap to Vision-decodable bytes within the per-image budget.

    Alpha is dropped and CMYK is converted first: Vision does not need alpha,
    and PyMuPDF raises ValueError ("cannot have alpha") on a JPEG encode of an
    alpha pixmap. PNG is preferred while it fits because it is lossless; an
    oversized image falls back to JPEG and then to repeated halving, so it
    degrades in resolution rather than being dropped.
    """
    import fitz

    try:
        if (pix.n - pix.alpha) > 3:          # CMYK / separation -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.alpha:                        # Pixmap(csRGB, pix) KEEPS alpha
            pix = fitz.Pixmap(pix, 0)

        out = pix.tobytes("png")
        if len(out) > _VISION_MAX_IMAGE_BYTES:
            # PNG of a photographic scan can be many times its source JPEG.
            out = pix.tobytes("jpeg")
        guard = 0
        while len(out) > _VISION_MAX_IMAGE_BYTES and guard < 5:
            pix.shrink(1)                    # halves both dimensions
            out = pix.tobytes("jpeg")
            guard += 1
        if len(out) > _VISION_MAX_IMAGE_BYTES:
            logger.warning(
                "ocr_service: image still %d bytes after downscaling — skipping", len(out)
            )
            return None
        return out
    except Exception as ex:
        logger.debug("ocr_service: pixmap encode failed: %s", ex)
        return None


def _normalise_image_bytes(data: bytes, ext: str) -> Optional[bytes]:
    """Return Vision-decodable bytes for an embedded image stream.

    The common case (a JPEG/PNG within budget) is returned untouched and is
    never decoded, so no pixel buffer is allocated. Only streams Vision cannot
    read (JBIG2/JPX/CCITT, routine in scanned PDFs) or streams over the byte
    budget are decoded and re-encoded.
    """
    import fitz

    needs_transcode = (ext or "").lower() not in _VISION_NATIVE_IMAGE_EXTS
    if not needs_transcode and len(data) <= _VISION_MAX_IMAGE_BYTES:
        return data

    try:
        return _encode_pixmap(fitz.Pixmap(data))
    except Exception as ex:
        logger.debug("ocr_service: image normalisation failed (%s): %s", ext, ex)
        return None


def _image_payload(doc, page, xref: int, bbox, raster_w: int, raster_h: int) -> Optional[bytes]:
    """Vision-ready bytes for one embedded image, with a hard memory ceiling.

    Normal case: hand back the stored stream (or a transcode of it) at its full
    resolution. Very large rasters are never decoded whole - the page region
    they occupy is rendered at a bounded zoom instead, which keeps peak RAM
    fixed while still reaching the image's pixels.
    """
    import fitz

    pixels = max(0, raster_w) * max(0, raster_h)
    if pixels and pixels > _EMB_MAX_DECODE_PIXELS:
        if bbox is None or bbox.is_empty or bbox.is_infinite:
            logger.warning(
                "ocr_service: skipping %dx%d image (xref %s) — too large to decode "
                "and no bbox to render from", raster_w, raster_h, xref,
            )
            return None
        area_pt = max(1.0, bbox.width * bbox.height)
        zoom = min(_EMB_REGION_MAX_ZOOM, (_EMB_MAX_DECODE_PIXELS / area_pt) ** 0.5)
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=bbox)
        except Exception as ex:
            logger.warning("ocr_service: region render failed for xref %s: %s", xref, ex)
            return None
        logger.info(
            "ocr_service: %dx%d image too large to decode — rendered its page region at %.2fx",
            raster_w, raster_h, zoom,
        )
        return _encode_pixmap(pix)

    try:
        raw = doc.extract_image(xref)
    except Exception as ex:
        logger.debug("ocr_service: extract_image failed for xref %s: %s", xref, ex)
        return None
    if not raw or not raw.get("image"):
        return None
    return _normalise_image_bytes(raw["image"], raw.get("ext", ""))


def _native_word_boxes(page) -> List[Tuple[float, float, float, float]]:
    """Bounding boxes of the page's native words, including invisible ones,
    expressed in the same coordinate frame as page.get_image_bbox().

    A scanner's OCR layer is drawn with render mode 3 (invisible); PyMuPDF
    still reports it here, which is exactly what the searchable-scan guard
    needs to see.

    The rotation step is load-bearing. page.get_text("words") reports boxes in
    the page's UNROTATED space, while page.get_image_bbox() - the only rect
    these are ever compared against - reports in the ROTATED (displayed) space.
    On a page carrying /Rotate 90/180/270 the two frames differ, so comparing
    them measures a region of the page unrelated to the image, and the
    searchable-scan guard then fires (or fails to fire) essentially at random:
    verified on one document saved at four rotations, native-text coverage over
    the same embedded image read 0.0% upright and 86.2% at 270 degrees, which
    silently discarded a pasted declarations page. Rotated pages are routine in
    broker submissions (landscape schedules, MFP auto-rotation).

    page.rotation_matrix is the identity when rotation is 0, but the no-op is
    taken explicitly so unrotated documents cannot be perturbed at all.
    """
    try:
        boxes = [(w[0], w[1], w[2], w[3]) for w in page.get_text("words")]
    except Exception:
        return []
    if not boxes or not getattr(page, "rotation", 0):
        return boxes
    try:
        import fitz
        matrix = page.rotation_matrix
        # Rect * Matrix returns an already-normalised rect.
        return [tuple(fitz.Rect(*b) * matrix) for b in boxes]
    except Exception as ex:
        # Better to measure in the wrong frame than to lose the guard entirely;
        # this is logged because it silently changes how the guard behaves.
        logger.warning("ocr_service: could not map word boxes to page rotation: %s", ex)
        return boxes


def _native_text_coverage(bbox, word_boxes) -> Tuple[int, float, Set[int]]:
    """How thoroughly native text covers `bbox`.

    Returns (word count, glyph-area fraction, set of occupied vertical bands).

    Word boxes on a page do not overlap, so summing their areas approximates
    their union closely enough. The band set records which of
    _EMB_NATIVE_BAND_COUNT equal-height slices of `bbox` contain at least one
    word - it distinguishes a text layer spread across the image from one
    clustered in a header or footer, which area alone cannot do.
    """
    empty: Set[int] = set()
    if bbox is None:
        return 0, 0.0, empty
    area = bbox.get_area()
    height = bbox.height
    if area <= 0 or height <= 0:
        return 0, 0.0, empty

    count = 0
    covered = 0.0
    bands: Set[int] = set()
    band_h = height / _EMB_NATIVE_BAND_COUNT
    for x0, y0, x1, y1 in word_boxes:
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if bbox.x0 <= cx <= bbox.x1 and bbox.y0 <= cy <= bbox.y1:
            count += 1
            covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
            bands.add(min(_EMB_NATIVE_BAND_COUNT - 1, int((cy - bbox.y0) / band_h)))
    return count, covered / area, bands


def _image_ink_bands(page, bbox) -> Optional[Set[int]]:
    """Which vertical bands of `bbox` actually contain ink in the rendered page.

    The band test has to be relative to where the image has CONTENT, not to the
    page. A scanned certificate whose text occupies only the top 60% still has
    a complete OCR layer over that 60%; measuring against the full page height
    would call it partial and re-OCR it, duplicating the page.

    Rendered deliberately tiny (a few thousand pixels, greyscale) so this costs
    microseconds. Returns None when it cannot be determined, which callers must
    treat as "unknown" and fall back to the page-relative measure.

    Ink is defined relative to this image's own paper level rather than against
    a fixed near-white cutoff - see the _EMB_INK_* notes for the measurement
    showing why a fixed cutoff makes this whole function a no-op on real scans.
    """
    import fitz

    try:
        target_px = 64.0
        zoom = min(0.5, max(0.02, target_px / max(bbox.width, bbox.height, 1.0)))
        pix = page.get_pixmap(
            clip=bbox, matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY,
        )
        if pix.height <= 0 or pix.width <= 0:
            return None
        samples = pix.samples
        stride = pix.stride

        # Pass 1 - what is this image's paper? Histogram over the probe render;
        # the high percentile is the background even when a dark figure covers
        # a large minority of the area.
        hist = [0] * 256
        for row in range(pix.height):
            base = row * stride
            for value in samples[base:base + pix.width]:
                hist[value] += 1
        total = sum(hist)
        if total <= 0:
            return None
        paper = 255
        seen = 0
        for value in range(256):
            seen += hist[value]
            if seen >= total * _EMB_INK_PAPER_PERCENTILE:
                paper = value
                break
        threshold = paper - _EMB_INK_MARGIN
        if threshold <= 0:
            # A uniformly dark image: everything is "paper", nothing stands out.
            # Report no ink so the caller falls back to the page-relative basis.
            return set()

        # Pass 2 - which bands contain anything darker than that paper.
        bands: Set[int] = set()
        for row in range(pix.height):
            band = min(_EMB_NATIVE_BAND_COUNT - 1,
                       int(row * _EMB_NATIVE_BAND_COUNT / pix.height))
            if band in bands:
                continue
            base = row * stride
            for col in range(pix.width):
                if samples[base + col] < threshold:
                    bands.add(band)
                    break
        return bands
    except Exception as ex:
        logger.debug("ocr_service: ink-band probe failed: %s", ex)
        return None


def _image_candidates(
    doc, page, page_idx: int, budget: "_DocBudget"
) -> List[Tuple[int, str, bytes]]:
    """Embedded images on `page` worth their own OCR call, as (xref, key, bytes).

    Selection rationale is documented at the _EMB_* constants. Every step is
    individually guarded: a single unreadable image must never abort the page.
    Each rejection is tallied on `budget` so the summary log can explain what
    became of every image rather than only reporting the survivors.
    """
    out: List[Tuple[int, str, bytes]] = []
    try:
        image_list = page.get_images(full=True)
    except Exception as ex:
        logger.debug("ocr_service: get_images failed on page %d: %s", page_idx, ex)
        return out
    if not image_list:
        return out

    try:
        page_area = page.rect.get_area()
    except Exception:
        page_area = 0.0
    if page_area <= 0:
        return out

    # Computed once per page, not per image.
    word_boxes = _native_word_boxes(page)

    for seen_on_page, img in enumerate(image_list):
        if len(out) >= _EMB_MAX_IMAGES_PER_PAGE:
            remaining = len(image_list) - seen_on_page
            logger.info(
                "ocr_service: page %d hit the per-page embedded-image cap (%d); "
                "%d image(s) on this page not examined",
                page_idx + 1, _EMB_MAX_IMAGES_PER_PAGE, remaining,
            )
            budget.images_examined += remaining
            budget.skipped_capped += remaining
            budget.images_over_cap += remaining
            break
        budget.images_examined += 1
        try:
            xref = img[0]
            raster_w, raster_h = int(img[2] or 0), int(img[3] or 0)

            # Gate 0 - already accepted under this xref on an earlier page.
            # Checked before any payload work: a letterhead recurring on 200
            # pages would otherwise be extracted, transcoded and hashed 200
            # times to be discarded 199 times, and for JBIG2/CCITT/JPX streams
            # that is a full decode and PNG re-encode per page. The content
            # hash below still runs, and still catches the same asset
            # re-embedded under a different xref by the producing tool.
            if xref in budget.seen_xrefs:
                budget.skipped_duplicate += 1
                continue

            # Gate 1 - stored raster size. The load-bearing discriminator:
            # decorative icons are small rasters no matter how they are scaled.
            if max(raster_w, raster_h) < _EMB_MIN_RASTER_LONG_PX:
                budget.skipped_small += 1
                continue
            if min(raster_w, raster_h) < _EMB_MIN_RASTER_SHORT_PX:
                budget.skipped_small += 1
                continue

            # Gate 2 - displayed geometry. An image placed but effectively
            # invisible carries no readable text.
            try:
                bbox = page.get_image_bbox(img)
            except Exception:
                bbox = None
            if bbox is not None:
                if bbox.is_infinite or bbox.is_empty:
                    budget.skipped_small += 1
                    continue
                if bbox.width < _EMB_MIN_DISPLAY_PT or bbox.height < _EMB_MIN_DISPLAY_PT:
                    budget.skipped_small += 1
                    continue
                if (bbox.get_area() / page_area) < _EMB_MIN_AREA_RATIO:
                    budget.skipped_small += 1
                    continue

                # Gate 3 - searchable-scan guard. If a dense native text layer
                # already sits over this image, its content is present in the
                # page text; OCR'ing it would duplicate every figure on the
                # page in the extractor's input. Glyph area and band spread
                # must BOTH agree - see the _EMB_NATIVE_COVER_* notes for the
                # measurements showing why neither alone is safe.
                words_over, coverage, text_bands = _native_text_coverage(
                    bbox, word_boxes
                )
                if (words_over >= _EMB_NATIVE_COVER_MIN_WORDS
                        and coverage >= _EMB_NATIVE_COVER_RATIO):
                    # Measure the text layer's spread against where the image
                    # actually has ink, falling back to the whole image when the
                    # ink probe is unavailable.
                    ink_bands = _image_ink_bands(page, bbox)
                    if ink_bands and len(ink_bands) >= _EMB_INK_MIN_BANDS:
                        spread = len(text_bands & ink_bands) / len(ink_bands)
                        basis = "ink"
                    else:
                        # Too little ink to divide into bands meaningfully (or
                        # the probe failed): a one-band denominator would score
                        # any single coincidence at 100%. Fall back to the
                        # page-relative measure, which errs toward OCR'ing.
                        spread = len(text_bands) / _EMB_NATIVE_BAND_COUNT
                        basis = "page"
                    if spread >= _EMB_NATIVE_COVER_BANDS:
                        logger.debug(
                            "ocr_service: page %d image already carries a native "
                            "text layer (%d words, %.0f%% glyph coverage, %.0f%% "
                            "%s-band spread) — skipping to avoid duplicating it",
                            page_idx + 1, words_over, coverage * 100,
                            spread * 100, basis,
                        )
                        budget.skipped_covered += 1
                        continue
            # bbox unavailable (nested/inline XObject): the raster gate already
            # passed, so keep the image rather than lose it on a geometry miss.

            payload = _image_payload(doc, page, xref, bbox, raster_w, raster_h)
            if not payload:
                budget.skipped_unreadable += 1
                continue

            # Dedup by content as well as xref: the same letterhead is often
            # re-embedded under a DIFFERENT xref on every page, which gate 0
            # cannot see.
            key = hashlib.sha256(payload).hexdigest()
            out.append((xref, key, payload))
        except Exception as ex:
            logger.debug("ocr_service: embedded image skipped on page %d: %s", page_idx, ex)
            budget.skipped_unreadable += 1
            continue
    return out


def _render_page_png(page) -> Optional[bytes]:
    """Render a page to in-memory PNG bytes at the configured zoom.

    In-memory by design: the previous implementation wrote a PNG into
    UPLOAD_DIR per page and deleted it afterwards, which leaked files whenever
    the OCR step raised.

    Zoom is clamped so the render obeys the same pixel ceiling embedded images
    do. A letter page at 2x is 1.9 Mpx, but PDF allows sheets up to 200 inches:
    a 34x44in E-size drawing renders to 31 Mpx (~93 MB of RGB) at 2x, and a
    window of 24 such pages is built before anything is dispatched. Reducing
    resolution degrades OCR slightly; exhausting memory loses the document.
    """
    import fitz

    try:
        zoom = _PAGE_RENDER_ZOOM
        try:
            area_pt = float(page.rect.width) * float(page.rect.height)
        except Exception:
            area_pt = 0.0
        if area_pt > 0:
            # 0.99 absorbs PyMuPDF rounding each pixel axis UP, which otherwise
            # lands the render a few thousand pixels ABOVE the ceiling this
            # clamp exists to enforce.
            max_zoom = (_EMB_MAX_DECODE_PIXELS * 0.99 / area_pt) ** 0.5
            if max_zoom < zoom:
                zoom = max(_PAGE_RENDER_MIN_ZOOM, max_zoom)
                logger.info(
                    "ocr_service: oversized page (%.0fx%.0f pt) — render zoom "
                    "reduced %.2fx -> %.2fx to stay inside the %d Mpx ceiling",
                    page.rect.width, page.rect.height, _PAGE_RENDER_ZOOM, zoom,
                    _EMB_MAX_DECODE_PIXELS // 1_000_000,
                )
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        data = pix.tobytes("png")
        if len(data) > _VISION_MAX_IMAGE_BYTES:
            normalised = _normalise_image_bytes(data, "png")
            return normalised
        return data
    except Exception as ex:
        logger.warning("ocr_service: page render failed: %s", ex)
        return None


def _page_is_blank(page) -> bool:
    """True only when a page provably holds nothing OCR could recover.

    Errs toward False: when anything is uncertain the page is sent to OCR,
    because a wrongly-skipped page is silent data loss while a wrongly-OCR'd
    blank page costs one sub-call inside an existing batch.
    """
    try:
        if page.get_images(full=True):
            return False
        if (page.get_text("text") or "").strip():
            return False
        if page.get_drawings():
            return False
        return True
    except Exception:
        return False


def _build_window_jobs(
    pdf_path: str,
    page_indices: Sequence[int],
    page_texts: Sequence[str],
    budget: _DocBudget,
) -> List[_OcrJob]:
    """Materialise OCR payloads for one window of pages (sync; via executor).

    Opens the document once per window rather than once per page, and never
    shares the handle across threads - PyMuPDF documents are not safe for
    concurrent use, and windows are awaited strictly sequentially.
    """
    jobs: List[_OcrJob] = []
    doc = None
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page_idx in page_indices:
            if page_idx >= doc.page_count:
                break
            try:
                page = doc[page_idx]
            except Exception as ex:
                logger.warning("ocr_service: cannot load page %d: %s", page_idx, ex)
                continue

            native = page_texts[page_idx] if page_idx < len(page_texts) else ""
            if len(native.strip()) < _MIN_NATIVE_TEXT_LEN:
                # ── Path B: no usable native layer, OCR the whole page ──
                if _page_is_blank(page):
                    continue
                if budget.full_ocr_remaining <= 0:
                    budget.pages_over_cap += 1
                    continue
                payload = _render_page_png(page)
                if payload:
                    budget.full_ocr_remaining -= 1
                    jobs.append(_OcrJob(kind="page", page_idx=page_idx, payload=payload))
                else:
                    # A scanned page we could not even rasterise. It keeps only
                    # its sub-100-character native remnant, which is
                    # indistinguishable downstream from a page that genuinely
                    # said nothing - so say so out loud.
                    budget.pages_render_failed += 1
                continue

            # ── Path A: keep native text, OCR embedded images separately ──
            if budget.images_remaining <= 0:
                # The document cap is already spent. Record that this page was
                # never looked at: previously this branch returned silently, so
                # `images_examined` never counted these images, the partition
                # check still balanced, and an arbitrary number of declarations
                # images could vanish with nothing in the log at all.
                try:
                    if page.get_images(full=True):
                        budget.pages_images_unexamined += 1
                except Exception:
                    pass
                continue
            candidates = _image_candidates(doc, page, page_idx, budget)
            for pos, (xref, key, payload) in enumerate(candidates):
                if budget.images_remaining <= 0:
                    # Count EVERY remaining candidate, not just this one: the
                    # previous `+= 1` before breaking under-reported the loss by
                    # len(candidates) - pos - 1 and tripped the partition check.
                    dropped = len(candidates) - pos
                    logger.warning(
                        "ocr_service: per-document embedded-image cap (%d) reached on "
                        "page %d — %d candidate image(s) dropped",
                        _EMB_MAX_IMAGES_PER_DOC, page_idx + 1, dropped,
                    )
                    budget.skipped_capped += dropped
                    budget.images_over_cap += dropped
                    break
                if key in budget.seen_image_keys:
                    # Repeated asset (letterhead, footer logo). OCR'd once on
                    # its first page; re-appending it on every page would add
                    # hundreds of duplicate lines to the LLM input.
                    budget.skipped_duplicate += 1
                    continue
                budget.seen_image_keys.add(key)
                budget.seen_xrefs.add(xref)
                budget.images_remaining -= 1
                jobs.append(_OcrJob(kind="image", page_idx=page_idx, payload=payload))
    except Exception as ex:
        logger.error("ocr_service: window build failed for %s: %s", pdf_path, ex)
    finally:
        _safe_close(doc)
    return jobs


def _format_image_block(page_idx: int, text: str) -> str:
    """Marker + OCR text as a single clean_text paragraph (see marker comment)."""
    collapsed = re.sub(r"\n\s*\n+", "\n", text.strip())
    return _EMBEDDED_IMAGE_MARKER.format(page=page_idx + 1) + "\n" + collapsed


# ASYNC-SAFE
async def extract_text_from_pdf(pdf_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for a PDF.

    Decides OCR per PAGE, not per document, and uses a different strategy for
    each of the two ways text hides in a PDF:

      Path B - the page has no usable native text layer (a scan). The page is
        rendered and OCR'd; the OCR text is used.

      Path A - the page HAS a native text layer but also carries embedded
        images. The native text is kept verbatim (so the column-reflow recovery
        still applies and no perfectly-accurate text is downgraded to OCR), and
        each embedded image is OCR'd from its own stored raster and APPENDED.

    The previous implementation applied a document-level threshold: any PDF
    with >= 100 characters of native text skipped OCR entirely, so a dec page
    pasted in as an image inside an otherwise text-based PDF was silently lost.

    All OCR is batched (up to 16 images per Vision request) and dispatched with
    bounded concurrency, and pages are processed in windows so peak memory does
    not grow with document length.
    """
    loop = asyncio.get_running_loop()
    structured = await loop.run_in_executor(
        _OCR_EXECUTOR, _pdfplumber_extract_pages_structured, pdf_path
    )
    page_texts: List[str] = [t for t, _ in structured]
    page_tables: List[str] = [tb for _, tb in structured]
    fitz_pages = await loop.run_in_executor(_OCR_EXECUTOR, _pdf_page_count, pdf_path)

    if not page_texts:
        if fitz_pages <= 0:
            logger.error(f"ocr_service: no readable pages in {pdf_path}")
            return "", ["needs_manual_review"]
        logger.warning(
            "ocr_service: pdfplumber returned no pages for %s — treating all %d page(s) as scanned",
            pdf_path, fitz_pages,
        )
        page_texts = [""] * fitz_pages
        page_tables = [""] * fitz_pages
    elif fitz_pages > len(page_texts):
        # Defensive: the two parsers disagree on page count. Trust the larger
        # so the extra pages still get OCR'd instead of being dropped.
        logger.warning(
            "ocr_service: page-count mismatch on %s (pdfplumber=%d, pymupdf=%d) — padding",
            pdf_path, len(page_texts), fitz_pages,
        )
        page_tables = list(page_tables) + [""] * (fitz_pages - len(page_texts))
        page_texts = list(page_texts) + [""] * (fitz_pages - len(page_texts))

    total_pages = len(page_texts)
    budget = _DocBudget()
    page_ocr_text: Dict[int, str] = {}
    ocr_tables: Dict[int, str] = {}          # scanned pages: tables from Vision word boxes
    image_blocks: Dict[int, List[str]] = {}
    low_conf: List[str] = []
    ocr_pages = 0
    ocr_images = 0
    ocr_images_failed = 0

    async def _dispatch(batch: List[_OcrJob]) -> None:
        """OCR a set of jobs and fold the results into the page accumulators."""
        nonlocal ocr_pages, ocr_images, ocr_images_failed
        if not batch:
            return
        results = await _ocr_payloads([j.payload for j in batch])
        for job, res in zip(batch, results):
            if job.kind == "page":
                ocr_pages += 1
                if res.text.strip():
                    page_ocr_text[job.page_idx] = res.text
                    if res.words:
                        # Same detector as a native page, on Vision's pixel boxes.
                        # Geometry is a bonus: any failure here leaves the OCR text
                        # exactly as it was.
                        try:
                            _t = detect_tables(res.words)
                            if _t:
                                ocr_tables[job.page_idx] = render_tables(_t, job.page_idx + 1)
                        except Exception as _tex:              # noqa: BLE001
                            logger.debug("ocr_service: scanned-page table pass failed on "
                                         "page %d: %s", job.page_idx + 1, _tex)
                low_conf.extend(res.low_conf)
                # A near-empty full-page OCR means a page we could not read.
                if _flag_for_manual_review(
                    res.text, res.low_conf, res.total_tokens,
                    f"{pdf_path}#page{job.page_idx + 1}",
                ):
                    low_conf.append("needs_manual_review")
            else:
                # `ok` is the whole reason _OcrResult carries it: a provider
                # failure and "this logo has no words in it" both arrive as
                # empty text, and only the first is data loss. Treating them
                # alike reported a hard failure as a successful OCR.
                if not res.ok:
                    ocr_images_failed += 1
                    logger.error(
                        "ocr_service: OCR FAILED for an embedded image on page %d of "
                        "%s — its text is absent from the extracted output",
                        job.page_idx + 1, pdf_path,
                    )
                    low_conf.append("needs_manual_review")
                    continue
                ocr_images += 1
                if res.text.strip():
                    image_blocks.setdefault(job.page_idx, []).append(
                        _format_image_block(job.page_idx, res.text)
                    )
                    # A pasted-in scan of a dec page or schedule is the case this
                    # whole Path A exists for; its rows deserve the same table
                    # treatment as a native page. Emitted right after its own
                    # image block, so the table stays with the text it came from.
                    if res.words:
                        try:
                            _t = detect_tables(res.words)
                            if _t:
                                image_blocks[job.page_idx].append(
                                    render_tables(_t, job.page_idx + 1)
                                )
                        except Exception as _tex:              # noqa: BLE001
                            logger.debug("ocr_service: embedded-image table pass failed "
                                         "on page %d: %s", job.page_idx + 1, _tex)
                low_conf.extend(res.low_conf)
                # An EMPTY-but-successful read is deliberately NOT flagged: a
                # logo legitimately carries little or no text, and flagging it
                # would mark essentially every branded document for review.

    # Jobs accumulate ACROSS windows and only complete batches are sent; the
    # incomplete tail waits for the next window.
    #
    # Windows exist to bound memory, not to bound requests. Dispatching each
    # window's jobs separately meant a document whose images are spread thinly -
    # a 271-page policy with one logo and a few graphics - fired a separate
    # HTTP request per window holding one or two images. Measured: 8 images
    # went out as 5 requests instead of 1. It costs nothing extra in Vision
    # charges (billing is per image, not per request) but it is pure added
    # latency, and on a long scanned document it also left the concurrency
    # budget unused, since a single window can only ever fill two batches.
    pending: List[_OcrJob] = []

    for start in range(0, total_pages, _OCR_PAGE_WINDOW):
        window = range(start, min(start + _OCR_PAGE_WINDOW, total_pages))
        jobs = await loop.run_in_executor(
            _OCR_EXECUTOR, _build_window_jobs, pdf_path, list(window), page_texts, budget
        )
        if jobs:
            pending.extend(jobs)

        # _group_payloads closes a group only when the next item does not fit,
        # so every group but the last is full by count or by bytes. Send those
        # and carry the last one forward. Carried payloads are capped at one
        # group, keeping the memory bound this loop exists to provide.
        if len(pending) > 1:
            groups = _group_payloads([len(j.payload) for j in pending])
            if len(groups) > 1:
                cut = sum(len(g) for g in groups[:-1])
                await _dispatch(pending[:cut])
                pending = pending[cut:]

    await _dispatch(pending)
    pending = []

    if budget.pages_over_cap:
        logger.error(
            "ocr_service: %s has more scanned pages than OCR_MAX_PAGES_PER_DOC=%d; "
            "%d page(s) kept native text only and are flagged for manual review",
            pdf_path, _OCR_MAX_PAGES_PER_DOC, budget.pages_over_cap,
        )
        low_conf.append("needs_manual_review")

    if budget.pages_render_failed:
        logger.error(
            "ocr_service: %s — %d scanned page(s) could not be rendered for OCR; "
            "they retain only their native text remnant and are flagged for "
            "manual review",
            pdf_path, budget.pages_render_failed,
        )
        low_conf.append("needs_manual_review")

    # The embedded-image caps must degrade as loudly as the page cap above.
    # They previously did not: exhausting OCR_EMB_MAX_IMAGES_PER_DOC dropped
    # candidate images with no error, no review flag, and nothing in the tally.
    if budget.images_over_cap or budget.pages_images_unexamined:
        logger.error(
            "ocr_service: %s exceeded the embedded-image caps "
            "(per-page=%d, per-document=%d); %d candidate image(s) dropped and "
            "%d further page(s) not examined — flagged for manual review",
            pdf_path, _EMB_MAX_IMAGES_PER_PAGE, _EMB_MAX_IMAGES_PER_DOC,
            budget.images_over_cap, budget.pages_images_unexamined,
        )
        low_conf.append("needs_manual_review")

    # ── Assemble in strict page order ────────────────────────────────────────
    # Pages are joined with a single newline and image blocks are appended with
    # single newlines, exactly matching the previous output shape. This keeps
    # clean_text's paragraph boundaries (and therefore its MD5 de-duplication)
    # identical to before for every document that has no embedded images.
    # Per page, in order: [Document page N] marker (multi-page only, and only
    # when the page has something under it) -> page text -> that page's table
    # block (native detector, or Vision-box detector on a scanned page) ->
    # embedded-image OCR blocks. Tables sit WITH their page; the old end-of-
    # document append (extraction_pipeline, removed 2026-08-22) put a page-1
    # schedule 270 pages away from page 1.
    parts: List[str] = []
    markers = _PAGE_MARKERS_ON and total_pages > 1
    tables_emitted = 0
    for idx in range(total_pages):
        native = page_texts[idx]
        chosen = page_ocr_text.get(idx) or native
        if idx in page_ocr_text:
            table_block = ocr_tables.get(idx, "")
        else:
            table_block = page_tables[idx] if idx < len(page_tables) else ""
        blocks = image_blocks.get(idx, [])
        if markers and (chosen.strip() or table_block or blocks):
            parts.append(_PAGE_MARKER.format(page=idx + 1))
        if chosen.strip():
            parts.append(chosen)
        if table_block:
            parts.append(table_block)
            tables_emitted += table_block.count("[Table - page ")
        for block in blocks:
            parts.append(block)
    if tables_emitted:
        logger.info("ocr_service: %s - %d table(s) emitted inline across %d page(s)",
                    os.path.basename(pdf_path), tables_emitted, total_pages)

    text = "".join(p + "\n" for p in parts)

    if ocr_pages or ocr_images or budget.images_examined:
        # The breakdown is the point: "7 images OCR'd" alone cannot tell an
        # operator whether the filter also discarded fifty that mattered.
        # A large `filtered` count on a document that should be image-rich is
        # the signal that the _EMB_* gates need review.
        logger.info(
            "ocr_service: %s — %d/%d page(s) OCR'd, %d embedded image(s) OCR'd, "
            "%d failed at the provider "
            "(%d examined: %d repeat, %d covered by text layer, %d too small, "
            "%d unreadable, %d over cap; %d page(s) not examined)",
            os.path.basename(pdf_path), ocr_pages, total_pages, ocr_images,
            ocr_images_failed,
            budget.images_examined, budget.skipped_duplicate,
            budget.skipped_covered, budget.skipped_small,
            budget.skipped_unreadable, budget.skipped_capped,
            budget.pages_images_unexamined,
        )
        accounted = (ocr_images + ocr_images_failed
                     + budget.skipped_duplicate + budget.skipped_covered
                     + budget.skipped_small + budget.skipped_unreadable
                     + budget.skipped_capped)
        if accounted != budget.images_examined:
            # Not fatal, but it means an image took a path with no tally, so the
            # breakdown above understates what was dropped. Worth a look.
            logger.warning(
                "ocr_service: image tally mismatch on %s — examined=%d accounted=%d",
                os.path.basename(pdf_path), budget.images_examined, accounted,
            )

    low_conf = list(dict.fromkeys(low_conf))
    # Hoist the review marker to the front. extract_facts truncates this list to
    # the first 40 tokens when building its prompt note, and on a long scanned
    # document the marker would otherwise be pushed out by ordinary low-
    # confidence words from earlier pages.
    if "needs_manual_review" in low_conf:
        low_conf = ["needs_manual_review"] + [t for t in low_conf if t != "needs_manual_review"]
    return text.strip(), low_conf


# ---------------------------------------------------------------------------
# Plain-text files
# ---------------------------------------------------------------------------

def _read_text_file_sync(path: str) -> str:
    """Read a .txt file as text. UTF-8 first, latin-1 fallback so no upload
    is rejected over a stray byte. Decode never fails on the latin-1 path."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (UnicodeDecodeError, ValueError):
        with open(path, "r", encoding="latin-1") as fh:
            return fh.read()
    except OSError as ex:
        logger.error(f"_read_text_file: cannot read {path}: {ex}")
        return ""


async def _read_text_file(path: str) -> str:
    """Async wrapper — reads off the event loop via the shared executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_OCR_EXECUTOR, _read_text_file_sync, path)


# ---------------------------------------------------------------------------
# Public file dispatcher
# ---------------------------------------------------------------------------

# ASYNC-SAFE
async def extract_text(file_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for any supported file type.
    Returns ("", []) for unsupported types.
    """
    ext = os.path.splitext(file_path.lower())[1]
    if ext == ".pdf":
        raw_text, low_conf = await extract_text_from_pdf(file_path)
    elif ext == ".txt":
        raw_text, low_conf = await _read_text_file(file_path), []
    elif ext in SUPPORTED_IMG:
        raw_text, low_conf = await ocr_image_file(file_path)
    else:
        logger.warning(f"extract_text: unsupported file type '{ext}' for {file_path}")
        return "", []
    return clean_text(raw_text), low_conf


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

_ZIP_MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB
_ZIP_MAX_RATIO              = 100


def extract_zip(zip_path: str) -> List[str]:
    """Extract PDF and image files from a ZIP archive. ZIP bomb guarded."""
    extracted: List[str] = []
    supported_exts = {".pdf"} | set(SUPPORTED_IMG)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            total_uncompressed = sum(i.file_size for i in infos)
            if total_uncompressed > _ZIP_MAX_UNCOMPRESSED_BYTES:
                logger.error(
                    f"extract_zip: archive too large when uncompressed "
                    f"({total_uncompressed / 1024 / 1024:.0f} MB): {zip_path}"
                )
                return []
            for info in infos:
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > _ZIP_MAX_RATIO:
                        logger.warning(
                            f"extract_zip: skipping '{info.filename}' — "
                            f"compression ratio {ratio:.0f}:1 exceeds limit"
                        )
                        continue
                ext = os.path.splitext(info.filename.lower())[1]
                if ext in supported_exts:
                    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(info.filename)}"
                    out = os.path.join(UPLOAD_DIR, safe_name)
                    with open(out, "wb") as fh:
                        fh.write(zf.read(info.filename))
                    extracted.append(out)
    except zipfile.BadZipFile as ex:
        logger.error(f"extract_zip: bad zip file {zip_path}: {ex}")
    except Exception as ex:
        logger.error(f"extract_zip: unexpected error on {zip_path}: {ex}")
    return extracted
