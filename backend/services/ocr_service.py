import os
import logging
import uuid
import zipfile
from typing import List, Tuple

import pdfplumber
from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR confidence thresholds
# Tiered per field criticality — NOT a flat global threshold.
# These are used by ocr_service only to mark low-confidence tokens;
# the per-field threshold logic lives in extraction_service.py.
# ---------------------------------------------------------------------------
OCR_CONFIDENCE_THRESHOLD = 0.70   # default / fallback for token flagging

# Minimum native-text length before we fall back to image OCR.
# pdfplumber returns empty strings for scanned PDFs; 100 chars is a safe floor.
_MIN_NATIVE_TEXT_LEN = 100

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
# Provider-specific OCR implementations
# ---------------------------------------------------------------------------

def _ocr_easyocr(img_path: str) -> Tuple[str, List[str]]:
    try:
        reader = _get_easyocr()
        if reader is None:
            return "", []
        results  = reader.readtext(img_path, detail=1)   # [(bbox, text, conf), ...]
        full_text = "\n".join(text for (_, text, _conf) in results).strip()
        low_conf  = [text for (_, text, conf) in results if conf < OCR_CONFIDENCE_THRESHOLD]
        return full_text, low_conf
    except Exception as ex:
        logger.error(f"EasyOCR error on {img_path}: {ex}")
        return "", []


def _ocr_google_vision(img_path: str) -> Tuple[str, List[str]]:
    try:
        from google.cloud import vision as gvision
        c        = gvision.ImageAnnotatorClient()
        with open(img_path, "rb") as f:
            content = f.read()
        image    = gvision.Image(content=content)
        response = c.document_text_detection(image=image)
        full_text = response.full_text_annotation.text.strip()
        low_conf: List[str] = []
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for para in block.paragraphs:
                    for word in para.words:
                        if word.confidence < OCR_CONFIDENCE_THRESHOLD:
                            word_text = "".join(s.text for s in word.symbols)
                            low_conf.append(word_text)
        return full_text, low_conf
    except Exception as ex:
        logger.error(f"Google Vision error: {ex}")
        return "", []


def _ocr_aws_textract(img_path: str) -> Tuple[str, List[str]]:
    try:
        import boto3
        c       = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
        with open(img_path, "rb") as f:
            content = f.read()
        response  = c.detect_document_text(Document={"Bytes": content})
        blocks    = response["Blocks"]
        full_text = "\n".join(b["Text"] for b in blocks if b["BlockType"] == "LINE").strip()
        low_conf  = [
            b["Text"] for b in blocks
            if b["BlockType"] == "WORD"
            and b.get("Confidence", 100) / 100 < OCR_CONFIDENCE_THRESHOLD
        ]
        return full_text, low_conf
    except Exception as ex:
        logger.error(f"AWS Textract error: {ex}")
        return "", []


# ---------------------------------------------------------------------------
# Public OCR dispatcher
# ---------------------------------------------------------------------------

def ocr_image_file(img_path: str) -> Tuple[str, List[str]]:
    """Return (full_text, low_confidence_tokens) for the given image file.

    Dispatches to the provider configured in OCR_PROVIDER env var.
    Falls back to EasyOCR on unknown providers.
    """
    if OCR_PROVIDER == "google":
        return _ocr_google_vision(img_path)
    elif OCR_PROVIDER == "aws":
        return _ocr_aws_textract(img_path)
    return _ocr_easyocr(img_path)


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def extract_images_from_pdf(pdf_path: str) -> List[str]:
    """Render each PDF page as a PNG using PyMuPDF at 2x zoom (~144 dpi).

    Returns a list of temp file paths. Caller owns cleanup.
    """
    out_paths: List[str] = []
    try:
        import fitz  # PyMuPDF
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
    """Return (full_text, low_confidence_tokens) for a PDF.

    Strategy:
      1. Try pdfplumber native text extraction (fast, zero OCR confidence data).
      2. If extracted text is below _MIN_NATIVE_TEXT_LEN (scanned/image PDF),
         fall back to page-by-page image OCR which returns confidence tokens.

    Low-confidence tokens are only populated in the OCR fallback path;
    native PDFs have no per-word confidence metadata.
    """
    text      = ""
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
        logger.info(f"Native text too short ({len(text.strip())} chars) — falling back to image OCR: {pdf_path}")
        img_paths = extract_images_from_pdf(pdf_path)
        for ip in img_paths:
            page_text, page_low = ocr_image_file(ip)
            text     += page_text + "\n"
            low_conf += page_low
            # Clean up temp image file
            try:
                os.remove(ip)
            except OSError:
                pass

    return text.strip(), low_conf


# ---------------------------------------------------------------------------
# Public file dispatcher
# ---------------------------------------------------------------------------

def extract_text(file_path: str) -> Tuple[str, List[str]]:
    """Return (full_text, low_confidence_tokens) for any supported file type.

    Supported: .pdf, and any extension in SUPPORTED_IMG (typically png/jpg/tiff/bmp/webp).
    Returns ("", []) for unsupported types — callers should check len(text) > 0.
    """
    ext = os.path.splitext(file_path.lower())[1]
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in SUPPORTED_IMG:
        return ocr_image_file(file_path)
    logger.warning(f"extract_text: unsupported file type '{ext}' for {file_path}")
    return "", []


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def extract_zip(zip_path: str) -> List[str]:
    """Extract PDF and image files from a ZIP archive.

    Returns a list of extracted file paths saved to UPLOAD_DIR.
    Skips entries with unsupported extensions silently.
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