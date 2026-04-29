"""Magic-byte MIME validation for uploaded files.

Checks the actual file content headers, not just the extension.
This prevents extension-spoofing attacks (e.g. a .pdf that is actually an executable).
"""
import os
from typing import Tuple

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

# Extensions we unconditionally allow without strict magic checks
_ALLOWED_EXTENSIONS = set(_MAGIC.keys())


def validate_file_mime(content: bytes, ext: str) -> Tuple[bool, str]:
    """Validate that `content` magic bytes match `ext`.

    Returns (True, "") on success, (False, error_message) on rejection.
    """
    ext = ext.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return False, f"File type '{ext}' is not supported. Allowed: PDF, ZIP, JPG, PNG, BMP, TIFF, WEBP."

    if not content:
        return False, "File is empty."

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
