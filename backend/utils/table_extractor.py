import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def extract_tables_from_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract tables from PDF. Tries pdfplumber first, camelot fallback.
    Returns list of {"page": int, "rows": [[...]], "source": str}
    """
    tables = []

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
    if not tables:
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
