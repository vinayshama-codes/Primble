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

Key versioning / KMS roadmap
------------------------------
CURRENT STATE: FIELD_ENCRYPTION_KEY is a single static Fernet key with no versioning.
  - There is no key rotation mechanism; all ciphertext uses the same key.
  - Re-keying requires a full table scan + re-encrypt (see encrypt_facts_data.py pattern).

TODO: Migrate to envelope encryption via AWS KMS with key aliases:
  1. Create a KMS Customer Managed Key (CMK) with alias  alias/acordly-field-encryption.
  2. For each row, call kms.generate_data_key(KeyId="alias/acordly-field-encryption")
     to get a plaintext DEK + encrypted DEK blob.
  3. Encrypt the field value with the plaintext DEK (AES-256-GCM), then discard it.
  4. Store { "v": 2, "kdek": <b64-encrypted-DEK>, "ct": <b64-ciphertext> } as the field value.
  5. To decrypt, call kms.decrypt(CiphertextBlob=kdek) to recover the DEK, then decrypt ct.
  6. KMS automatic key rotation (annual) then rotates the CMK without requiring row-level re-encryption,
     because the encrypted DEK is re-wrapped transparently by KMS.
  See: encrypt_field_v2() / decrypt_field_versioned() stubs below.
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


# ---------------------------------------------------------------------------
# KMS envelope-encryption stubs (v2 — not yet active)
# ---------------------------------------------------------------------------
# These are scaffolding for the AWS KMS migration described in the module
# docstring above.  They raise NotImplementedError until the KMS CMK and
# boto3 dependency are wired in.  No production code calls them yet.

def encrypt_field_v2(value: str | None, key_version: str = "latest") -> str | None:
    """
    Stub: encrypt value using KMS envelope encryption.

    Args:
        value: plaintext string to encrypt.
        key_version: KMS key alias version (e.g. "latest", "2024-01").

    Returns:
        JSON string: { "v": 2, "kv": key_version, "kdek": <b64>, "ct": <b64> }

    TODO: implement with boto3:
        kms = boto3.client("kms")
        dek_resp = kms.generate_data_key(
            KeyId=f"alias/acordly-field-encryption/{key_version}",
            KeySpec="AES_256",
        )
        plaintext_dek = dek_resp["Plaintext"]
        encrypted_dek = base64.b64encode(dek_resp["CiphertextBlob"]).decode()
        ct = _aes_gcm_encrypt(value.encode(), plaintext_dek)
        return json.dumps({"v": 2, "kv": key_version, "kdek": encrypted_dek, "ct": ct})
    """
    raise NotImplementedError("encrypt_field_v2: KMS integration not yet implemented")


def decrypt_field_versioned(value: str | None) -> str | None:
    """
    Stub: decrypt a value that may be v1 (Fernet/enc: prefix) or v2 (KMS envelope).

    Dispatches based on the stored version tag so old rows remain readable
    after the KMS migration.

    TODO: implement v2 path with boto3:
        payload = json.loads(value)
        if payload["v"] == 2:
            kms = boto3.client("kms")
            dek = kms.decrypt(CiphertextBlob=base64.b64decode(payload["kdek"]))["Plaintext"]
            return _aes_gcm_decrypt(payload["ct"], dek)
        # fall through to v1
        return decrypt_field(value)
    """
    if value and not value.startswith("{"):
        # v1 path — delegate to existing Fernet decrypt
        return decrypt_field(value)
    raise NotImplementedError("decrypt_field_versioned: KMS v2 path not yet implemented")
