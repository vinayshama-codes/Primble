"""upload_intake.py - the ONE validation + temp-storage door for uploaded files
(7 Oct 2026, Choice Electric #25).

A package's documents arrive two ways: a fresh upload (`POST
/api/upload-declaration`, which creates the package) and documents ADDED to an
existing package (`POST /api/session/{id}/documents`). Both must refuse exactly
the same files with exactly the same words - a second copy of these checks is
how a limit or a virus scan gets forgotten on one path. The block below is the
upload route's own, moved here verbatim:

  * at most MAX_FILES_PER_UPLOAD files (400);
  * every file read with a one-byte overrun, so an oversize file is caught
    before anything is written; the aggregate cap (413) then the per-file cap
    (413);
  * the extension must match the content (`validate_file_mime`, 400) and the
    bytes pass the virus scanner (`scan_file_bytes`);
  * each file is written under a random prefix in UPLOAD_DIR; a ZIP is opened
    and every PDF / image inside is checked and scanned the same way (an inner
    file that fails its type check is skipped, a broken ZIP is a 400);
  * nothing supported at all is a 400.

Returns `(uploaded_paths, all_paths)`: every file written (the caller deletes
them when it is done) and the ones the pipeline reads. On ANY refusal the files
already written by this call are removed before the error is raised - the
caller never sees a partial list.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
import zipfile
from typing import List, Tuple

from fastapi import HTTPException

from config.settings import (
    MAX_FILES_PER_UPLOAD, MAX_UPLOAD_SIZE_BYTES, SUPPORTED_IMG, UPLOAD_DIR,
)
from utils.mime_validator import validate_file_mime
from utils.virus_scanner import scan_file_bytes

logger = logging.getLogger(__name__)


async def store_uploads(files) -> Tuple[List[str], List[str]]:
    """Validate and store `files` (FastAPI UploadFiles). See the module note."""
    uploaded_paths: List[str] = []
    all_paths: List[str] = []
    try:
        if len(files) > MAX_FILES_PER_UPLOAD:
            raise HTTPException(400, f"Too many files — maximum {MAX_FILES_PER_UPLOAD} per upload.")

        # Read all file bytes first so we can enforce the aggregate size cap before
        # touching the filesystem.  10 × 50 MB = 500 MB per request without this guard.
        contents = []
        for f in files:
            contents.append((f, await f.read(MAX_UPLOAD_SIZE_BYTES + 1)))

        total_bytes = sum(len(c) for _, c in contents)
        if total_bytes > MAX_UPLOAD_SIZE_BYTES * MAX_FILES_PER_UPLOAD:
            raise HTTPException(
                413,
                f"Total upload size exceeds the aggregate limit "
                f"({MAX_UPLOAD_SIZE_BYTES * MAX_FILES_PER_UPLOAD // 1024 // 1024} MB).",
            )

        for f, content in contents:
            if len(content) > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    413,
                    f"File '{f.filename}' exceeds the "
                    f"{MAX_UPLOAD_SIZE_BYTES // 1024 // 1024} MB limit.",
                )
            ext = os.path.splitext((f.filename or "upload").lower())[1]
            mime_ok, mime_err = validate_file_mime(content, ext)
            if not mime_ok:
                raise HTTPException(400, mime_err)
            scan_file_bytes(content, f.filename or "upload")
            safe_name = f"{uuid.uuid4().hex}_{os.path.basename(f.filename or 'upload')}"
            path = os.path.join(UPLOAD_DIR, safe_name)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda p=path, c=content: open(p, "wb").write(c)
            )
            uploaded_paths.append(path)
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(path, "r") as zf:
                        for info in zf.infolist():
                            inner_ext = os.path.splitext(info.filename.lower())[1]
                            if inner_ext not in ({".pdf"} | set(SUPPORTED_IMG)):
                                continue
                            inner_data = zf.read(info.filename)
                            inner_mime_ok, inner_mime_err = validate_file_mime(inner_data, inner_ext)
                            if not inner_mime_ok:
                                logger.warning(f"ZIP inner file failed MIME validation, skipping: {info.filename} — {inner_mime_err}")
                                continue
                            scan_file_bytes(inner_data, info.filename)
                            safe_inner = f"{uuid.uuid4().hex}_{os.path.basename(info.filename)}"
                            inner_path = os.path.join(UPLOAD_DIR, safe_inner)
                            await asyncio.get_event_loop().run_in_executor(
                                None, lambda p=inner_path, d=inner_data: open(p, "wb").write(d)
                            )
                            all_paths.append(inner_path)
                except zipfile.BadZipFile:
                    raise HTTPException(400, f"File '{f.filename}' is not a valid ZIP archive.")
            elif ext == ".pdf" or ext == ".txt" or ext in SUPPORTED_IMG:
                all_paths.append(path)

        # Release the in-memory upload buffer now that every file is on disk.
        # The extraction pipeline reads from `all_paths`; the raw bytes are no
        # longer needed and holding them costs up to ~500 MB of heap on a
        # 10-file × 50 MB upload while the pipeline runs.
        contents = None

        if not all_paths:
            raise HTTPException(400, "No supported files found")
        return uploaded_paths, all_paths
    except BaseException:
        remove_files(uploaded_paths, all_paths)
        raise


def remove_files(*path_lists) -> None:
    """Best effort: delete every temp file named in `path_lists`."""
    for p in set(p for paths in path_lists for p in (paths or [])):
        try:
            os.remove(p)
        except OSError:
            pass
