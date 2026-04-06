import os
import logging
import uuid
import zipfile
from typing import List

import pdfplumber
import pikepdf

from config.settings import UPLOAD_DIR, SUPPORTED_IMG, OCR_PROVIDER

logger = logging.getLogger(__name__)

_easyocr_reader = None


def _get_easyocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("EasyOCR reader initialized")
        except Exception as ex:
            logger.error(f"EasyOCR init failed: {ex}")
    return _easyocr_reader


def _ocr_easyocr(img_path: str) -> str:
    try:
        reader = _get_easyocr()
        if reader is None:
            return ""
        results = reader.readtext(img_path, detail=0, paragraph=True)
        return "\n".join(results).strip()
    except Exception as ex:
        logger.error(f"EasyOCR error on {img_path}: {ex}")
        return ""


def _ocr_google_vision(img_path: str) -> str:
    try:
        from google.cloud import vision as gvision
        c = gvision.ImageAnnotatorClient()
        with open(img_path, "rb") as f:
            content = f.read()
        image    = gvision.Image(content=content)
        response = c.document_text_detection(image=image)
        return response.full_text_annotation.text.strip()
    except Exception as ex:
        logger.error(f"Google Vision error: {ex}")
        return ""


def _ocr_aws_textract(img_path: str) -> str:
    try:
        import boto3
        c = boto3.client("textract", region_name=os.getenv("AWS_REGION", "us-east-1"))
        with open(img_path, "rb") as f:
            content = f.read()
        response = c.detect_document_text(Document={"Bytes": content})
        return "\n".join(b["Text"] for b in response["Blocks"] if b["BlockType"] == "LINE").strip()
    except Exception as ex:
        logger.error(f"AWS Textract error: {ex}")
        return ""


def ocr_image_file(img_path: str) -> str:
    if OCR_PROVIDER == "google":
        return _ocr_google_vision(img_path)
    elif OCR_PROVIDER == "aws":
        return _ocr_aws_textract(img_path)
    return _ocr_easyocr(img_path)


def extract_images_from_pdf(pdf_path: str) -> List[str]:
    out_paths = []
    try:
        pdf = pikepdf.open(pdf_path)
        for page in pdf.pages:
            resources = page.get("/Resources", None)
            if resources is None:
                continue
            xobjects = resources.get("/XObject", None)
            if xobjects is None:
                continue
            for name, obj in xobjects.items():
                try:
                    if obj.get("/Subtype", "") == "/Image":
                        img_data = bytes(obj.read_raw_bytes())
                        ext  = ".jpg" if "/DCTDecode" in str(obj.get("/Filter", "")) else ".png"
                        fname = os.path.join(UPLOAD_DIR, f"embed_{uuid.uuid4().hex[:8]}{ext}")
                        with open(fname, "wb") as fh:
                            fh.write(img_data)
                        out_paths.append(fname)
                except Exception:
                    pass
        pdf.close()
    except Exception as ex:
        logger.warning(f"Image extraction from PDF failed: {ex}")
    return out_paths


def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as ex:
        logger.error(f"pdfplumber error: {ex}")
    if len(text.strip()) < 100:
        for ip in extract_images_from_pdf(pdf_path):
            text += ocr_image_file(ip) + "\n"
    return text.strip()


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path.lower())[1]
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in SUPPORTED_IMG:
        return ocr_image_file(file_path)
    return ""


def extract_zip(zip_path: str) -> List[str]:
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            ext = os.path.splitext(name.lower())[1]
            if ext in {".pdf"} | SUPPORTED_IMG:
                out = os.path.join(UPLOAD_DIR, os.path.basename(name))
                with open(out, "wb") as fh:
                    fh.write(zf.read(name))
                extracted.append(out)
    return extracted