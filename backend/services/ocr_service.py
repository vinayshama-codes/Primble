import asyncio
import base64
import json
import os
import logging
import tempfile
import uuid
import zipfile
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor

import pdfplumber
import httpx
from circuitbreaker import CircuitBreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER
from utils.text_cleaner import clean_text

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


def _ocr_google_vision_rest(img_path: str, content: bytes) -> Tuple[str, List[str], int]:
    api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_VISION_API_KEY is not configured")

    payload = {
        "requests": [
            {
                "image": {
                    "content": base64.b64encode(content).decode("ascii"),
                },
                "features": [
                    {"type": "DOCUMENT_TEXT_DETECTION"},
                ],
            }
        ]
    }
    timeout = float(os.getenv("GOOGLE_VISION_TIMEOUT_SECONDS", "60"))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            _GOOGLE_VISION_API_URL,
            params={"key": api_key},
            json=payload,
        )
    response.raise_for_status()
    body = response.json()
    item = (body.get("responses") or [{}])[0]
    if item.get("error"):
        message = item["error"].get("message", "unknown Google Vision error")
        raise RuntimeError(f"Google Vision OCR error: {message}")

    annotation = item.get("fullTextAnnotation") or {}
    return _extract_low_conf_from_annotation(annotation)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _ocr_google_vision_attempt(img_path: str) -> Tuple[str, List[str], int]:
    """Single attempt — called by _ocr_google_vision which owns the CB and error boundary."""
    with open(img_path, "rb") as f:
        content = f.read()

    if os.getenv("GOOGLE_VISION_API_KEY", "").strip():
        return _ocr_google_vision_rest(img_path, content)

    from google.cloud import vision as gvision
    c = _get_google_vision_client()
    image    = gvision.Image(content=content)
    response = c.document_text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Google Vision OCR error: {response.error.message}")

    annotation = response.full_text_annotation
    full_text = (annotation.text or "").strip() if annotation else ""

    low_conf: List[str] = []
    total = 0
    for page in getattr(annotation, "pages", []) or []:
        for block in page.blocks:
            for para in block.paragraphs:
                for word in para.words:
                    total    += 1
                    word_text = "".join(s.text for s in word.symbols)
                    penalty   = _numeric_correction_score(word_text)
                    adj_conf  = max(0.0, word.confidence - penalty)
                    if adj_conf < OCR_CONFIDENCE_THRESHOLD:
                        low_conf.append(_normalize_token(word_text))
    return full_text, low_conf, total


def _ocr_google_vision(img_path: str) -> Tuple[str, List[str], int]:
    if _vision_cb.opened:
        logger.warning(f"ocr_service: Google Vision circuit OPEN — skipping OCR for {img_path}")
        return "", [], 0
    try:
        # call() records success/failure on the circuit breaker automatically
        return _vision_cb.call(_ocr_google_vision_attempt, img_path)
    except Exception as ex:
        logger.error(f"Google Vision error on {img_path}: {ex}")
        return "", [], 0


def _run_ocr_provider(img_path: str) -> Tuple[str, List[str], int]:
    """Dispatch to the configured OCR provider (sync, called via executor)."""
    return _ocr_google_vision(img_path)


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
    """Render each PDF page as PNG via PyMuPDF at 2x zoom. Caller owns cleanup."""
    out_paths: List[str] = []
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            mat   = fitz.Matrix(2.0, 2.0)
            pix   = page.get_pixmap(matrix=mat)
            fname = os.path.join(UPLOAD_DIR, f"page_{uuid.uuid4().hex[:8]}_{page_num}.png")
            pix.save(fname)
            out_paths.append(fname)
        doc.close()
    except Exception as ex:
        logger.warning(f"PDF page rendering failed (PyMuPDF): {ex}")
    return out_paths


def _pdfplumber_extract(pdf_path: str) -> str:
    """Sync pdfplumber text extraction — called via executor."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as ex:
        logger.error(f"pdfplumber error on {pdf_path}: {ex}")
    return text


# ASYNC-SAFE
async def extract_text_from_pdf(pdf_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for a PDF.
    pdfplumber runs in thread pool executor to avoid blocking the event loop.
    Falls back to image OCR for scanned PDFs.
    """
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(_OCR_EXECUTOR, _pdfplumber_extract, pdf_path)

    low_conf: List[str] = []
    if len(text.strip()) < _MIN_NATIVE_TEXT_LEN:
        logger.info(
            f"Native text too short ({len(text.strip())} chars) — image OCR fallback: {pdf_path}"
        )
        img_paths = await loop.run_in_executor(_OCR_EXECUTOR, extract_images_from_pdf, pdf_path)
        for ip in img_paths:
            page_text, page_low = await ocr_image_file(ip)
            text     += page_text + "\n"
            low_conf += page_low
            try:
                os.remove(ip)
            except OSError:
                pass

    low_conf = list(dict.fromkeys(low_conf))
    return text.strip(), low_conf


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
