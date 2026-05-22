"""S3 storage stub — not in use. All operations are no-ops."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return False


async def upload_pdf_async(session_id: str, form_id: str, data: bytes) -> Optional[str]:
    return None


async def download_pdf_async(s3_key: str) -> Optional[bytes]:
    return None


def upload_pdf(session_id: str, form_id: str, data: bytes) -> Optional[str]:
    return None


def download_pdf(s3_key: str) -> Optional[bytes]:
    return None


def delete_pdf(s3_key: str) -> None:
    pass


def upload_source_file(file_content: bytes, original_filename: str, upload_id: str) -> Optional[str]:
    return None


def download_source_file(s3_key: str) -> Optional[bytes]:
    return None


def generate_presigned_upload_url(filename: str, upload_id: str, content_type: str = "application/octet-stream") -> Optional[dict]:
    return None


def delete_source_file(s3_key: str) -> None:
    pass
