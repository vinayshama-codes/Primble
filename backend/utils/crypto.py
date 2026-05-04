"""
Field-level encryption helpers using Fernet (AES-128-CBC + HMAC-SHA256).

Key lifecycle:
  - Set FIELD_ENCRYPTION_KEY to a URL-safe base64-encoded 32-byte key.
  - Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - If the env var is absent the helpers raise RuntimeError so misconfiguration
    is caught at startup/first use rather than silently storing plaintext.

Encrypted values are prefixed with "enc:" so that:
  1. decrypt_field can detect already-plaintext values during the migration window.
  2. A NULL or empty string is passed through unchanged on both sides.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "enc:"

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY env var is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    _fernet = Fernet(key.encode())
    return _fernet


def encrypt_field(value: str | None) -> str | None:
    """Return Fernet-encrypted, prefixed ciphertext, or None/'' unchanged."""
    if not value:
        return value
    if value.startswith(_PREFIX):
        return value  # already encrypted — idempotent
    token = _get_fernet().encrypt(value.encode()).decode()
    return f"{_PREFIX}{token}"


def decrypt_field(value: str | None) -> str | None:
    """Return plaintext. Handles both encrypted (enc:…) and legacy plaintext values."""
    if not value:
        return value
    if not value.startswith(_PREFIX):
        # Legacy plaintext row — return as-is (will be encrypted on next write).
        return value
    try:
        return _get_fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("decrypt_field: InvalidToken — wrong key or corrupted data")
        raise
