"""DEPRECATED for the extraction pipeline (2026-08-22).

Tables now reach the LLM inline with their page, from utils/page_layout.py's
header-anchored detector with pdfplumber lines-mode as a per-page fallback - both
wired inside services/ocr_service.extract_text_from_pdf. This module's only
pipeline caller (extraction_pipeline's end-of-document append) was removed: on
every insurance page in the corpus it produced nothing, because pdfplumber's
default needs ruled lines and insurance schedules are whitespace-aligned.
Kept importable for any external script; see extraction_arch_change.md.
"""
import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Camelot rasterises every page into a numpy array (~3.7 MB/page at default DPI).
# Running both lattice + stream passes with pages="all" on a 271-page PDF allocates
# ~2 GB, which OOMs a 2 GB Render instance. Disabled by default; enable only on a
# dedicated worker with >= 8 GB RAM via CAMELOT_DISABLED=false.
_CAMELOT_DISABLED = os.getenv("CAMELOT_DISABLED", "true").lower() == "true"

# pdfplumber's page.extract_tables() is also O(objects_per_page) per page and runs
# inside a thread that can block other extraction work. For very large documents
# (long declaration packages), table extraction adds little value because the page
# text has already been captured by extract_text(). Skip it entirely past this
# page count; the underlying page text is unaffected.
_TABLE_EXTRACT_PAGE_LIMIT = int(os.getenv("TABLE_EXTRACT_PAGE_LIMIT", "40"))


def _quick_page_count(pdf_path: str) -> int:
    """Return PDF page count without parsing content streams. Returns 0 on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0


def extract_tables_from_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract tables from PDF. Tries pdfplumber first, camelot fallback.
    Returns list of {"page": int, "rows": [[...]], "source": str}

    Documents larger than TABLE_EXTRACT_PAGE_LIMIT pages skip table extraction
    entirely — the page text is still captured by extract_text() in the main
    pipeline, so no words are lost.
    """
    tables = []

    page_count = _quick_page_count(pdf_path)
    if page_count > _TABLE_EXTRACT_PAGE_LIMIT:
        logger.info(
            "table_extractor: skipping %s — %d pages exceeds TABLE_EXTRACT_PAGE_LIMIT=%d",
            os.path.basename(pdf_path), page_count, _TABLE_EXTRACT_PAGE_LIMIT,
        )
        return tables

    # Layer 1: pdfplumber (fast, works on native PDFs)
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                for tbl in (page.extract_tables() or []):
                    if tbl and any(any(cell for cell in row) for row in tbl):
                        tables.append({
                            "page": page_num,
                            "rows": tbl,
                            "source": "pdfplumber",
                        })
    except Exception as ex:
        logger.warning(f"pdfplumber table extract failed: {ex}")

    # Layer 2: camelot (better for ruled/bordered tables)
    # Disabled by default — see module-level comment on _CAMELOT_DISABLED.
    if not tables and not _CAMELOT_DISABLED:
        try:
            import camelot
            parsed = camelot.read_pdf(pdf_path, pages="all", flavor="lattice")
            for tbl in parsed:
                rows = tbl.df.values.tolist()
                if rows:
                    tables.append({
                        "page": tbl.page,
                        "rows": rows,
                        "source": "camelot_lattice",
                    })
        except Exception as ex:
            logger.debug(f"camelot lattice failed: {ex}")

        try:
            import camelot
            parsed = camelot.read_pdf(pdf_path, pages="all", flavor="stream")
            for tbl in parsed:
                rows = tbl.df.values.tolist()
                if rows:
                    tables.append({
                        "page": tbl.page,
                        "rows": rows,
                        "source": "camelot_stream",
                    })
        except Exception as ex:
            logger.debug(f"camelot stream failed: {ex}")

    logger.info(f"table_extractor: found {len(tables)} tables in {pdf_path}")
    return tables
