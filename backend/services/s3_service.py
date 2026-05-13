import logging
import os
from typing import Optional

from circuitbreaker import CircuitBreaker, CircuitBreakerError

logger = logging.getLogger(__name__)

_BUCKET          = os.getenv("AWS_S3_BUCKET", "")
_REGION          = os.getenv("AWS_REGION", "us-east-1")
_PDF_PREFIX      = os.getenv("AWS_S3_PDF_PREFIX", "pdfs/")
_UPLOAD_PREFIX   = os.getenv("AWS_S3_UPLOAD_PREFIX", "uploads/")
_PRESIGN_EXPIRY  = int(os.getenv("AWS_S3_PRESIGN_EXPIRY_SECONDS", "900"))  # 15 min

# Circuit breaker: open after 5 consecutive failures; retry after 30 s
_s3_cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30, name="s3")


def _s3_open() -> bool:
    """Return True when the S3 circuit breaker is open (calls should be skipped)."""
    if _s3_cb.opened:
        logger.warning("s3_service: circuit breaker OPEN — skipping S3 operation")
        return True
    return False


def is_configured() -> bool:
    return bool(_BUCKET)


_s3_client = None


def _client():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=os.getenv("STORAGE_ENDPOINT") or None,
            aws_access_key_id=os.getenv("STORAGE_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("STORAGE_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    return _s3_client


async def upload_pdf_async(session_id: str, form_id: str, data: bytes) -> Optional[str]:
    """Async wrapper — offloads blocking boto3 call to a thread."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, upload_pdf, session_id, form_id, data)


async def download_pdf_async(s3_key: str) -> Optional[bytes]:
    """Async wrapper — offloads blocking boto3 call to a thread."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, download_pdf, s3_key)


def upload_pdf(session_id: str, form_id: str, data: bytes) -> Optional[str]:
    """Upload PDF bytes to S3. Returns the object key, or None on failure."""
    if not is_configured() or _s3_open():
        return None
    key = f"{_PDF_PREFIX}{session_id}/{form_id}.pdf"
    try:
        _s3_cb.call(
            _client().put_object,
            Bucket=_BUCKET,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )
        logger.debug(f"s3_service: uploaded {key} ({len(data)} bytes)")
        return key
    except Exception as ex:
        logger.error(f"s3_service: upload failed for {key}: {ex}")
        return None


def download_pdf(s3_key: str) -> Optional[bytes]:
    """Download PDF bytes from S3. Returns bytes, or None on failure."""
    if not is_configured() or _s3_open():
        return None
    try:
        resp = _s3_cb.call(_client().get_object, Bucket=_BUCKET, Key=s3_key)
        data = resp["Body"].read()
        logger.debug(f"s3_service: downloaded {s3_key} ({len(data)} bytes)")
        return data
    except Exception as ex:
        logger.error(f"s3_service: download failed for {s3_key}: {ex}")
        return None


def delete_pdf(s3_key: str) -> None:
    """Delete a PDF from S3. No-ops if S3 is not configured."""
    if not is_configured() or _s3_open():
        return
    try:
        _s3_cb.call(_client().delete_object, Bucket=_BUCKET, Key=s3_key)
        logger.debug(f"s3_service: deleted {s3_key}")
    except Exception as ex:
        logger.warning(f"s3_service: delete failed for {s3_key}: {ex}")


def upload_source_file(file_content: bytes, original_filename: str, upload_id: str) -> Optional[str]:
    """Upload a raw source document (PDF/image) to S3 for async worker processing.

    Returns the S3 key on success, or None on failure.
    """
    if not is_configured() or _s3_open():
        return None
    import uuid as _uuid
    safe_name = os.path.basename(original_filename or "upload")
    key = f"{_UPLOAD_PREFIX}{upload_id}/{_uuid.uuid4().hex}_{safe_name}"
    try:
        _s3_cb.call(
            _client().put_object,
            Bucket=_BUCKET,
            Key=key,
            Body=file_content,
            ContentType="application/octet-stream",
        )
        logger.debug(f"s3_service: source upload {key} ({len(file_content)} bytes)")
        return key
    except Exception as ex:
        logger.error(f"s3_service: source upload failed for {key}: {ex}")
        return None


def download_source_file(s3_key: str) -> Optional[bytes]:
    """Download a raw source document from S3."""
    if not is_configured() or _s3_open():
        return None
    try:
        resp = _s3_cb.call(_client().get_object, Bucket=_BUCKET, Key=s3_key)
        data = resp["Body"].read()
        logger.debug(f"s3_service: downloaded source {s3_key} ({len(data)} bytes)")
        return data
    except Exception as ex:
        logger.error(f"s3_service: source download failed for {s3_key}: {ex}")
        return None


def generate_presigned_upload_url(filename: str, upload_id: str, content_type: str = "application/octet-stream") -> Optional[dict]:
    """Generate a presigned S3 URL for direct browser-to-S3 upload.

    Returns {"url": ..., "s3_key": ..., "fields": ...} or None on failure.
    The caller passes s3_key back when confirming the upload.
    """
    if not is_configured() or _s3_open():
        return None
    import uuid as _uuid
    safe_name = os.path.basename(filename or "upload")
    key = f"{_UPLOAD_PREFIX}{upload_id}/{_uuid.uuid4().hex}_{safe_name}"
    try:
        presigned = _s3_cb.call(
            _client().generate_presigned_post,
            Bucket=_BUCKET,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024],
            ],
            ExpiresIn=_PRESIGN_EXPIRY,
        )
        return {"url": presigned["url"], "fields": presigned["fields"], "s3_key": key}
    except Exception as ex:
        logger.error(f"s3_service: presign failed for {key}: {ex}")
        return None


def delete_source_file(s3_key: str) -> None:
    """Delete a processed source file from S3."""
    if not is_configured() or _s3_open():
        return
    try:
        _s3_cb.call(_client().delete_object, Bucket=_BUCKET, Key=s3_key)
        logger.debug(f"s3_service: deleted source {s3_key}")
    except Exception as ex:
        logger.warning(f"s3_service: source delete failed for {s3_key}: {ex}")
