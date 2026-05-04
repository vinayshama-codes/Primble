import asyncio
import os
import logging
import uuid
import zipfile
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor

import pdfplumber
from circuitbreaker import CircuitBreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER
from utils.text_cleaner import clean_text

logger = logging.getLogger(__name__)

# Shared executor for all blocking OCR/PDF operations (module-level, not per-call)
_OCR_MAX_WORKERS = (os.cpu_count() or 2) * 2
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=_OCR_MAX_WORKERS)

# Circuit breakers for external OCR providers
_textract_cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60, name="textract")
_vision_cb   = CircuitBreaker(failure_threshold=3, recovery_timeout=60, name="google_vision")

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
# EasyOCR singleton — lazy-init, GPU disabled for server safety
# ---------------------------------------------------------------------------
_easyocr_reader = None


def _get_easyocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("EasyOCR reader initialised")
        except Exception as ex:
            logger.error(f"EasyOCR init failed: {ex}")
    return _easyocr_reader


# ---------------------------------------------------------------------------
# Provider OCR implementations (sync — called via executor)
# ---------------------------------------------------------------------------

def _ocr_easyocr(img_path: str) -> Tuple[str, List[str], int]:
    try:
        reader = _get_easyocr()
        if reader is None:
            logger.error(f"EasyOCR not available — returning empty for {img_path}")
            return "", [], 0
        results   = reader.readtext(img_path, detail=1)
        all_texts = [text for (_, text, _) in results]
        full_text = "\n".join(all_texts).strip()
        total     = len(results)
        low_conf: List[str] = []
        for (_, text, conf) in results:
            penalty    = _numeric_correction_score(text)
            adj_conf   = max(0.0, conf - penalty)
            norm_token = _normalize_token(text)
            if adj_conf < OCR_CONFIDENCE_THRESHOLD:
                low_conf.append(norm_token)
        return full_text, low_conf, total
    except Exception as ex:
        logger.error(f"EasyOCR error on {img_path}: {ex}")
        return "", [], 0


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _ocr_google_vision_attempt(img_path: str) -> Tuple[str, List[str], int]:
    """Single attempt — called by _ocr_google_vision which owns the CB and error boundary."""
    from google.cloud import vision as gvision
    c = gvision.ImageAnnotatorClient()
    with open(img_path, "rb") as f:
        content = f.read()
    image    = gvision.Image(content=content)
    response = c.document_text_detection(image=image)
    full_text = response.full_text_annotation.text.strip()

    low_conf: List[str] = []
    total = 0
    for page in response.full_text_annotation.pages:
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


_textract_client = None


def _get_textract_client():
    global _textract_client
    if _textract_client is None:
        import boto3
        _textract_client = boto3.client(
            "textract",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            config=boto3.session.Config(connect_timeout=30, read_timeout=30),
        )
    return _textract_client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _ocr_aws_textract_attempt(img_path: str) -> Tuple[str, List[str], int]:
    """Single attempt — called by _ocr_aws_textract which owns the CB and error boundary."""
    c = _get_textract_client()
    with open(img_path, "rb") as f:
        content = f.read()
    response  = c.detect_document_text(Document={"Bytes": content})
    blocks    = response["Blocks"]
    full_text = "\n".join(b["Text"] for b in blocks if b["BlockType"] == "LINE").strip()

    low_conf: List[str] = []
    word_blocks = [b for b in blocks if b["BlockType"] == "WORD"]
    total       = len(word_blocks)
    for b in word_blocks:
        word_text = b["Text"]
        penalty   = _numeric_correction_score(word_text)
        adj_conf  = max(0.0, b.get("Confidence", 100.0) / 100.0 - penalty)
        if adj_conf < OCR_CONFIDENCE_THRESHOLD:
            low_conf.append(_normalize_token(word_text))
    return full_text, low_conf, total


def _ocr_aws_textract(img_path: str) -> Tuple[str, List[str], int]:
    if _textract_cb.opened:
        logger.warning(f"ocr_service: Textract circuit OPEN — skipping OCR for {img_path}")
        return "", [], 0
    try:
        # call() records success/failure on the circuit breaker automatically
        return _textract_cb.call(_ocr_aws_textract_attempt, img_path)
    except Exception as ex:
        logger.error(f"AWS Textract error on {img_path}: {ex}")
        return "", [], 0


def _run_ocr_provider(img_path: str) -> Tuple[str, List[str], int]:
    """Dispatch to the configured OCR provider (sync, called via executor)."""
    if OCR_PROVIDER == "google":
        return _ocr_google_vision(img_path)
    elif OCR_PROVIDER == "aws":
        return _ocr_aws_textract(img_path)
    else:
        return _ocr_easyocr(img_path)


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
