"""Tables read off the ACORD template PDFs, precomputed (6 Oct 2026).

Two readers measure each template's printed layout with pdfplumber - which
boxes already print a "$" (`pdf_service._fields_with_printed_currency`) and
which boxes sit under an "APPLICABLE ONLY IN <state>" heading
(`state_restricted_boxes.restricted_boxes`). Each read costs 2-8 seconds per
form, ONCE PER PROCESS: the first generation, and the first post-generation
Data Consistency confirm, after a deploy or an idle spin-down paid up to a
minute for five forms.

The templates are fixed files, so their tables are fixed too:
`scripts/build_template_tables.py` writes them to `templates/template_tables.json`
with each template's SHA-256 and the reader's version. A reader takes the
stored table only while both still match; a changed template or reader falls
back to reading the PDF live, exactly as before. Read-only at runtime.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLES_FILE = "template_tables.json"


def _template_dir() -> str:
    from config.settings import TEMPLATE_DIR
    return TEMPLATE_DIR


def tables_path() -> str:
    return os.path.join(_template_dir(), TABLES_FILE)


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        with open(tables_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("template_tables: %s unreadable (%s) - templates are read live",
                       TABLES_FILE, exc)
        return {}


@lru_cache(maxsize=64)
def template_sha(form_id: str) -> Optional[str]:
    # A form's second copy ("ACORD_131__excess") is its form's template.
    from services.form_instances import base_form_id
    path = os.path.join(_template_dir(), f"{base_form_id(form_id)}.pdf")
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def stored(table: str, form_id: str, version: int) -> Optional[Any]:
    """The precomputed `table` for `form_id`, or None (read the PDF live)."""
    from services.form_instances import base_form_id
    form_id = base_form_id(str(form_id or ""))
    entry = ((_load().get("tables") or {}).get(table) or {}).get(str(form_id or ""))
    if not isinstance(entry, dict):
        return None
    if entry.get("version") != version or entry.get("sha") != template_sha(form_id):
        return None
    return entry.get("data")
