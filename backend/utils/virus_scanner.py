"""Virus/malware scanning abstraction.

Provides a consistent interface for file scanning. In production this is a
hard gate: if no scanner is configured, uploads are rejected.

Controlled by the VIRUS_SCANNER env var:
  none       — skip scanning (ONLY safe for development; blocked in production)
  clamav     — call ClamAV via clamd socket (requires clamd running)
  custom     — call VIRUS_SCANNER_WEBHOOK with file bytes for external scanning

In production (ENVIRONMENT=production), VIRUS_SCANNER=none raises HTTP 503.

To run ClamAV locally:
  brew install clamav && clamd
  Set CLAMAV_SOCKET=/var/run/clamav/clamd.ctl
"""
import logging
import os

from fastapi import HTTPException

logger       = logging.getLogger(__name__)
_SCANNER     = os.getenv("VIRUS_SCANNER", "none").lower()
_ENV         = os.getenv("ENVIRONMENT", "development").lower()
_IS_PROD     = _ENV == "production"


def scan_file_bytes(content: bytes, filename: str) -> None:
    """Scan file content for malware. Raises HTTP 400 if infected, HTTP 503 if scanner unavailable in production.

    Safe no-op in development when VIRUS_SCANNER=none.
    """
    if _SCANNER == "none":
        if _IS_PROD:
            logger.error("VIRUS_SCANNER=none in production — rejecting upload for safety")
            raise HTTPException(
                503,
                "Virus scanning is not configured. Set VIRUS_SCANNER=clamav or VIRUS_SCANNER=custom in production.",
            )
        # Development: log warning and allow
        logger.debug("virus_scanner: scanning disabled (dev mode) for %s", filename)
        return

    if _SCANNER == "clamav":
        _scan_clamav(content, filename)
    elif _SCANNER == "custom":
        _scan_custom_webhook(content, filename)
    else:
        logger.warning("Unknown VIRUS_SCANNER=%s — treating as unscanned", _SCANNER)
        if _IS_PROD:
            raise HTTPException(503, "Virus scanner misconfigured.")


def _scan_clamav(content: bytes, filename: str) -> None:
    """Stream file bytes to ClamAV via clamd INSTREAM."""
    socket_path = os.getenv("CLAMAV_SOCKET", "/var/run/clamav/clamd.ctl")
    try:
        import socket as _socket
        import struct

        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(socket_path)

        # INSTREAM protocol: send zINSTREAM\0, then chunks [len(4 bytes BE)][data], end with \x00\x00\x00\x00
        sock.send(b"zINSTREAM\0")
        chunk_size = 4096
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            sock.send(struct.pack("!I", len(chunk)) + chunk)
        sock.send(struct.pack("!I", 0))

        result = b""
        while True:
            data = sock.recv(4096)
            if not data:
                break
            result += data
        sock.close()

        result_str = result.decode("utf-8", errors="replace").strip()
        logger.debug("ClamAV result for %s: %s", filename, result_str)
        if "FOUND" in result_str:
            threat = result_str.split(":")[-1].strip() if ":" in result_str else "Unknown threat"
            logger.warning("Malware detected in %s: %s", filename, threat)
            raise HTTPException(400, "Uploaded file was rejected by antivirus scan.")
    except HTTPException:
        raise
    except Exception as ex:
        logger.error("ClamAV scan failed for %s: %s", filename, ex)
        if _IS_PROD:
            raise HTTPException(503, "Virus scanning temporarily unavailable.")
        logger.warning("ClamAV unavailable in dev — allowing upload")


def _scan_custom_webhook(content: bytes, filename: str) -> None:
    """POST file bytes to a configured external scanning webhook."""
    webhook_url = os.getenv("VIRUS_SCANNER_WEBHOOK", "").strip()
    if not webhook_url:
        logger.error("VIRUS_SCANNER=custom but VIRUS_SCANNER_WEBHOOK is not set")
        if _IS_PROD:
            raise HTTPException(503, "Virus scanner not configured.")
        return
    try:
        import urllib.request as _req
        import urllib.error as _err
        import json as _json

        req_obj = _req.Request(
            webhook_url,
            data=content,
            headers={"Content-Type": "application/octet-stream", "X-Filename": filename},
            method="POST",
        )
        with _req.urlopen(req_obj, timeout=20) as resp:
            body = _json.loads(resp.read().decode())
            if body.get("infected") or body.get("status") == "infected":
                logger.warning("Custom scanner: malware in %s", filename)
                raise HTTPException(400, "Uploaded file was rejected by antivirus scan.")
    except HTTPException:
        raise
    except Exception as ex:
        logger.error("Custom scanner webhook failed for %s: %s", filename, ex)
        if _IS_PROD:
            raise HTTPException(503, "Virus scanning temporarily unavailable.")
