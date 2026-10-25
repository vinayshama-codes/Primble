"""Magic-byte MIME validation for uploaded files.

Checks the actual file content headers, not just the extension.
This prevents extension-spoofing attacks (e.g. a .pdf that is actually an executable).
"""
import os
from typing import Tuple

from utils.spreadsheet_text import (
    CSV_EXTENSION, REFUSED_SPREADSHEET_EXTENSIONS, XLSX_EXTENSION, xlsx_package_problem,
)

# Magic bytes for supported types
_MAGIC: dict = {
    ".pdf":  [(0, b"%PDF")],
    ".zip":  [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    ".jpg":  [(0, b"\xff\xd8\xff")],
    ".jpeg": [(0, b"\xff\xd8\xff")],
    ".png":  [(0, b"\x89PNG\r\n\x1a\n")],
    ".bmp":  [(0, b"BM")],
    ".tiff": [(0, b"II*\x00"), (0, b"MM\x00*")],
    ".tif":  [(0, b"II*\x00"), (0, b"MM\x00*")],
    ".webp": [(0, b"RIFF"), (8, b"WEBP")],
}

# Plain-text extensions have no reliable magic signature. They are allowed
# without a byte-header check; content is validated as decodable text below.
# A CSV is text too (Brent's 17 Oct item 1, 21 Oct 2026).
_TEXT_EXTENSIONS = {".txt", CSV_EXTENSION}

# An Excel workbook (.xlsx) is a ZIP; `xlsx_package_problem` (the one check the
# reader runs too, utils/spreadsheet_text.py) then requires its workbook parts,
# refuses macros / encryption and caps the unpacked size (a ZIP bomb).
_SPREADSHEET_ZIP_EXTENSIONS = {XLSX_EXTENSION}

# Extensions we unconditionally allow without strict magic checks
_ALLOWED_EXTENSIONS = set(_MAGIC.keys()) | _TEXT_EXTENSIONS | _SPREADSHEET_ZIP_EXTENSIONS

# Every allowed type that is a DOCUMENT (read by the pipeline) - a ZIP is a
# container of documents. The upload door reads this one set, for a file and
# for a file inside a ZIP alike.
DOCUMENT_EXTENSIONS = frozenset(_ALLOWED_EXTENSIONS - {".zip"})

_ALLOWED_TEXT = "PDF, ZIP, JPG, PNG, BMP, TIFF, WEBP, TXT, XLSX, CSV"

# A UTF-16 text file (Excel's "Unicode Text") starts with its byte-order mark
# and is full of NUL bytes by design.
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def validate_file_mime(content: bytes, ext: str) -> Tuple[bool, str]:
    """Validate that `content` magic bytes match `ext`.

    Returns (True, "") on success, (False, error_message) on rejection.
    """
    ext = ext.lower()
    if ext in REFUSED_SPREADSHEET_EXTENSIONS:
        # .xls / .xlsm and the other spreadsheet formats this backend cannot
        # (or will not) read: say what to do, not just "not supported".
        return False, REFUSED_SPREADSHEET_EXTENSIONS[ext]
    if ext not in _ALLOWED_EXTENSIONS:
        return False, f"File type '{ext}' is not supported. Allowed: {_ALLOWED_TEXT}."

    if not content:
        return False, "File is empty."

    if ext in _SPREADSHEET_ZIP_EXTENSIONS:
        problem = xlsx_package_problem(content)
        return (False, problem) if problem else (True, "")

    # Plain text has no magic header. Accept it if the bytes decode as text and
    # contain no NUL byte (a strong signal of a binary file renamed to .txt).
    if ext in _TEXT_EXTENSIONS:
        if ext == CSV_EXTENSION and content.startswith(_UTF16_BOMS):
            try:
                content.decode("utf-16")
            except UnicodeDecodeError:
                return False, (
                    f"File content does not match the declared type '{ext}'. "
                    "The file is not readable text."
                )
            return True, ""
        if b"\x00" in content[:8192]:
            return False, (
                f"File content does not match the declared type '{ext}'. "
                "The file may be binary, corrupted, or renamed to bypass validation."
            )
        try:
            content[:8192].decode("utf-8")
        except UnicodeDecodeError:
            try:
                content[:8192].decode("latin-1")
            except UnicodeDecodeError:
                return False, (
                    f"File content does not match the declared type '{ext}'. "
                    "The file is not readable text."
                )
        return True, ""

    magic_rules = _MAGIC.get(ext)
    if not magic_rules:
        return True, ""

    # For extensions with multiple possible magic signatures, any match passes.
    for offset, signature in magic_rules:
        chunk = content[offset : offset + len(signature)]
        if chunk == signature:
            # Extra: for WEBP, check both offset 0 (RIFF) and offset 8 (WEBP)
            if ext == ".webp":
                if content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
                    return True, ""
                continue
            return True, ""

    return False, (
        f"File content does not match the declared type '{ext}'. "
        "The file may be corrupted or renamed to bypass validation."
    )
