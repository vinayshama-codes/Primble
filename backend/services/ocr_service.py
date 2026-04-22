import os
import logging
import uuid
import zipfile
from typing import List, Tuple

import pdfplumber
from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER
from utils.text_cleaner import clean_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR confidence thresholds
# Used for token-level flagging only.
# Per-field threshold logic lives in extraction_service.py.
# ---------------------------------------------------------------------------
OCR_CONFIDENCE_THRESHOLD = 0.70   # default / fallback for token flagging

# Minimum confidence across ALL tokens before flagging the document for
# manual review (document-level, not token-level).
_DOC_REVIEW_THRESHOLD = 0.50

# Minimum native-text length before falling back to image OCR.
_MIN_NATIVE_TEXT_LEN = 100

# Maximum fraction of tokens that can be low-confidence before the full
# document is flagged for manual review.
_MAX_LOW_CONF_FRACTION = 0.40

# ---------------------------------------------------------------------------
# OCR confusion normalization — mirrors extraction_service._normalize_for_ocr_check.
# Applied to tokens BEFORE confidence comparison to reduce false negatives
# caused by common OCR substitutions.
# ---------------------------------------------------------------------------
_OCR_CONFUSION_MAP = str.maketrans({
    "O": "0", "o": "0",
    "l": "1", "I": "1",
    "S": "5", "Z": "2",
    "B": "8", "G": "6",
})


def _normalize_token(token: str) -> str:
    """Normalize OCR-confusable chars. Applied before confidence filtering."""
    return token.translate(_OCR_CONFUSION_MAP)


def _numeric_correction_score(token: str) -> float:
    """
    Heuristic: if a token looks like a number but contains alpha chars that
    are common OCR substitutions (O for 0, l for 1), score it lower so it
    gets flagged as low-confidence more aggressively.

    Returns a penalty in [0, 1]: 0 = no penalty, 1 = max penalty.
    Callers subtract this from the raw OCR confidence.
    """
    norm = _normalize_token(token)
    if not norm.replace(".", "").replace(",", "").isdigit():
        return 0.0
    # Compare original vs normalized — difference indicates substitution risk
    diff_chars = sum(1 for a, b in zip(token, norm) if a != b)
    return min(1.0, diff_chars * 0.15)   # 15% penalty per suspicious char, capped at 100%


def _flag_for_manual_review(
    full_text: str,
    low_conf_tokens: List[str],
    total_token_count: int,
    source_path: str,
) -> bool:
    """
    Returns True if the document should be flagged for manual review.
    Criteria:
      1. More than _MAX_LOW_CONF_FRACTION of tokens are low-confidence.
      2. Extracted text is empty or near-empty.
    Logs a WARNING when flagging.
    """
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
# Provider OCR implementations
# Each returns (full_text, low_confidence_tokens, total_token_count).
# total_token_count is needed for _flag_for_manual_review fraction check.
# ---------------------------------------------------------------------------

def _ocr_easyocr(img_path: str) -> Tuple[str, List[str], int]:
    try:
        reader = _get_easyocr()
        if reader is None:
            logger.error(f"EasyOCR not available — returning empty for {img_path}")
            return "", [], 0
        results   = reader.readtext(img_path, detail=1)   # [(bbox, text, conf), ...]
        all_texts = [text for (_, text, _) in results]
        full_text = "\n".join(all_texts).strip()
        total     = len(results)
        low_conf: List[str] = []
        for (_, text, conf) in results:
            # Apply numeric confusion penalty before threshold check
            penalty    = _numeric_correction_score(text)
            adj_conf   = max(0.0, conf - penalty)
            norm_token = _normalize_token(text)
            if adj_conf < OCR_CONFIDENCE_THRESHOLD:
                low_conf.append(norm_token)  # store normalized form for downstream matching
        return full_text, low_conf, total
    except Exception as ex:
        logger.error(f"EasyOCR error on {img_path}: {ex}")
        return "", [], 0


def _ocr_google_vision(img_path: str) -> Tuple[str, List[str], int]:
    try:
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
    except Exception as ex:
        logger.error(f"Google Vision error on {img_path}: {ex}")
        return "", [], 0


def _ocr_aws_textract(img_path: str) -> Tuple[str, List[str], int]:
    try:
        import boto3
        c = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
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
    except Exception as ex:
        logger.error(f"AWS Textract error on {img_path}: {ex}")
        return "", [], 0


# ---------------------------------------------------------------------------
# Public OCR dispatcher
# ---------------------------------------------------------------------------

def ocr_image_file(img_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for an image file.
    Dispatches to OCR_PROVIDER env var. Falls back to EasyOCR on unknown providers.

    Flags for manual review if token low-confidence fraction exceeds threshold
    or if OCR output is empty — adds 'needs_manual_review' marker to returned tokens.
    (Callers can check: 'needs_manual_review' in low_confidence_tokens.)
    """
    if OCR_PROVIDER == "google":
        full_text, low_conf, total = _ocr_google_vision(img_path)
    elif OCR_PROVIDER == "aws":
        full_text, low_conf, total = _ocr_aws_textract(img_path)
    else:
        full_text, low_conf, total = _ocr_easyocr(img_path)

    # Deduplicate low-conf tokens (preserve order)
    low_conf = list(dict.fromkeys(low_conf))

    if _flag_for_manual_review(full_text, low_conf, total, img_path):
        low_conf = ["needs_manual_review"] + low_conf

    return full_text, low_conf


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def extract_images_from_pdf(pdf_path: str) -> List[str]:
    """
    Render each PDF page as PNG via PyMuPDF at 2x zoom (~144 dpi).
    Returns list of temp file paths. Caller owns cleanup.
    """
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


def extract_text_from_pdf(pdf_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for a PDF.

    Strategy:
      1. pdfplumber native text extraction (fast, no confidence data).
      2. If extracted text < _MIN_NATIVE_TEXT_LEN (scanned PDF),
         fall back to page-by-page image OCR with confidence tokens.

    Native PDFs: low_conf is always [] (no word-level confidence from pdfplumber).
    """
    text     = ""
    low_conf: List[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as ex:
        logger.error(f"pdfplumber error on {pdf_path}: {ex}")

    if len(text.strip()) < _MIN_NATIVE_TEXT_LEN:
        logger.info(
            f"Native text too short ({len(text.strip())} chars) — image OCR fallback: {pdf_path}"
        )
        img_paths = extract_images_from_pdf(pdf_path)
        for ip in img_paths:
            page_text, page_low = ocr_image_file(ip)
            text     += page_text + "\n"
            low_conf += page_low
            try:
                os.remove(ip)
            except OSError:
                pass

    # Deduplicate low-conf tokens
    low_conf = list(dict.fromkeys(low_conf))
    return text.strip(), low_conf


# ---------------------------------------------------------------------------
# Public file dispatcher
# ---------------------------------------------------------------------------

def extract_text(file_path: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, low_confidence_tokens) for any supported file type.
    Returns ("", []) for unsupported types — callers should check len(text) > 0.
    """
    ext = os.path.splitext(file_path.lower())[1]
    if ext == ".pdf":
        raw_text, low_conf = extract_text_from_pdf(file_path)
    elif ext in SUPPORTED_IMG:
        raw_text, low_conf = ocr_image_file(file_path)
    else:
        logger.warning(f"extract_text: unsupported file type '{ext}' for {file_path}")
        return "", []
    return clean_text(raw_text), low_conf


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def extract_zip(zip_path: str) -> List[str]:
    """
    Extract PDF and image files from a ZIP archive.
    Returns list of extracted file paths saved to UPLOAD_DIR.
    Skips unsupported extensions silently.
    """
    extracted: List[str] = []
    supported_exts = {".pdf"} | set(SUPPORTED_IMG)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                ext = os.path.splitext(name.lower())[1]
                if ext in supported_exts:
                    out = os.path.join(UPLOAD_DIR, os.path.basename(name))
                    with open(out, "wb") as fh:
                        fh.write(zf.read(name))
                    extracted.append(out)
    except zipfile.BadZipFile as ex:
        logger.error(f"extract_zip: bad zip file {zip_path}: {ex}")
    except Exception as ex:
        logger.error(f"extract_zip: unexpected error on {zip_path}: {ex}")
    return extracted