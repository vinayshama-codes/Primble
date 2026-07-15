"""Regression tests for the two-column label/value scramble recovery in
services.ocr_service (_extract_page_text_smart / _pdfplumber_extract).

Root cause: pdfplumber's default extract_text() reads a page in a single
global top-to-bottom order. On a genuine two-column label/value block whose
row heights drift even slightly between the two columns (common in
Word/reporting-engine table exports), that single reading order interleaves
the wrong label with the wrong value - e.g. "CARRIER: 84-2210987" (the
actual FEIN) instead of the real carrier name. Confirmed (2026-07-11) that
pdfplumber's layout=True and Google Vision's document_text_detection fail
identically on this pattern - this is not a "pick a different flag" bug.

Run from backend/:
    python -m pytest tests/test_ocr_column_reflow.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from services.ocr_service import _pdfplumber_extract  # noqa: E402


def _build_scrambled_identity_block(path):
    """Left column (labels) and right column (values) with DIFFERENT line
    spacing - the drift that breaks naive row-alignment."""
    labels = ["Named Insured:", "Legal Entity:", "Mailing Address:", "FEIN:",
              "CARRIER:", "NAIC Code:", "Policy Number:", "Effective Date:",
              "Expiration Date:", "AGENCY:", "Producer:", "Producer Address:"]
    values = ["Summit Ridge Construction LLC", "Limited Liability Company (LLC)",
              "4820 Kettering Boulevard, Suite 210, Denver, CO 80216", "84-2210987",
              "Pinnacle Casualty Insurance Company", "38954", "GL-CO-778451",
              "04/01/2026", "04/01/2027", "Front Range Insurance Advisors",
              "Dana Whitfield", "1100 Larimer Street, Denver, CO 80202"]
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, height - 60, "COMMERCIAL GENERAL LIABILITY SECTION")
    c.setFont("Helvetica", 10)
    top_y = height - 100
    y = top_y
    for label in labels:
        c.drawString(60, y, label)
        y -= 20
    y = top_y
    for value in values:
        c.drawString(320, y, value)
        y -= 26   # deliberately different from the label column's spacing
    c.save()


def _build_normal_paragraph(path):
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica", 10)
    text = c.beginText(60, height - 80)
    paragraph = (
        "Summit Ridge Construction LLC is a commercial general contractor performing "
        "ground-up commercial construction and interior tenant remodel projects across "
        "the Denver metropolitan area. The applicant employs twenty eight full-time "
        "staff and engages licensed subcontractors for electrical, plumbing, and HVAC "
        "scopes on active job sites throughout the region."
    )
    import textwrap
    for line in textwrap.wrap(paragraph, 90):
        text.textLine(line)
    c.drawText(text)
    c.save()


def _build_three_column_table(path):
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, height - 60, "SCHEDULE OF HAZARDS")
    c.setFont("Helvetica", 9)
    c.drawString(60, height - 80, "LOC #"); c.drawString(200, height - 80, "CLASS CODE")
    c.drawString(340, height - 80, "PREMIUM BASIS"); c.drawString(480, height - 80, "EXPOSURE")
    rows = [("1", "97047", "Payroll", "1,250,000"), ("2", "91560", "Gross Sales", "3,400,000")]
    y = height - 100
    for r in rows:
        c.drawString(60, y, r[0]); c.drawString(200, y, r[1])
        c.drawString(340, y, r[2]); c.drawString(480, y, r[3])
        y -= 20
    c.save()


def _build_composite_page(path):
    """Scrambled identity block at the top, a genuine 3-column table well
    below it on the SAME page - the critical regression case: fixing the
    identity block must not corrupt the unrelated table further down."""
    labels = ["Named Insured:", "CARRIER:", "AGENCY:", "Policy Number:", "Effective Date:"]
    values = ["Summit Ridge Construction LLC", "Pinnacle Casualty Insurance Company",
              "Front Range Insurance Advisors", "GL-CO-778451", "04/01/2026"]
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, height - 60, "COMMERCIAL GENERAL LIABILITY SECTION")
    c.setFont("Helvetica", 10)
    top_y = height - 100
    y = top_y
    for l in labels:
        c.drawString(60, y, l)
        y -= 20
    y = top_y
    for v in values:
        c.drawString(320, y, v)
        y -= 27

    table_top = height - 350
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, table_top, "SCHEDULE OF HAZARDS")
    c.setFont("Helvetica", 9)
    rows = [("LOC #", "CLASS CODE", "PREMIUM BASIS"), ("1", "97047", "Payroll 1,250,000"),
            ("2", "91560", "Gross Sales 3,400,000")]
    ty = table_top - 20
    for r in rows:
        c.drawString(60, ty, r[0]); c.drawString(200, ty, r[1]); c.drawString(340, ty, r[2])
        ty -= 20
    c.save()


@pytest.fixture()
def pdf_dir(tmp_path):
    return tmp_path


def test_scrambled_identity_block_is_recovered(pdf_dir):
    path = str(pdf_dir / "scrambled.pdf")
    _build_scrambled_identity_block(path)
    text = _pdfplumber_extract(path)
    lines = text.splitlines()
    assert any("CARRIER" in l and "Pinnacle" in l for l in lines)
    assert any("AGENCY" in l and "Front Range" in l for l in lines)
    assert any("Mailing Address" in l and "Kettering" in l for l in lines)
    assert any("FEIN" in l and "84-2210987" in l for l in lines)


def test_normal_paragraph_is_untouched(pdf_dir):
    path = str(pdf_dir / "normal.pdf")
    _build_normal_paragraph(path)
    text = _pdfplumber_extract(path)
    assert "commercial general contractor" in text
    assert "Denver" in text and "metropolitan area" in text


def test_genuine_multi_column_table_is_untouched(pdf_dir):
    # This is the critical false-positive guard: a real 3+ column table that
    # already extracts correctly must never be mistaken for a scrambled
    # label/value block and get mangled by the reflow recovery.
    path = str(pdf_dir / "table.pdf")
    _build_three_column_table(path)
    text = _pdfplumber_extract(path)
    lines = text.splitlines()
    assert any("97047" in l and "1,250,000" in l for l in lines)
    assert any("91560" in l and "3,400,000" in l for l in lines)


def test_scramble_recovery_does_not_corrupt_unrelated_table_on_same_page(pdf_dir):
    # The critical regression case: fixing a scrambled identity block at the
    # top of a page must not damage a genuine table further down the SAME
    # page - the recovery must be scoped to only the scrambled y-band.
    path = str(pdf_dir / "composite.pdf")
    _build_composite_page(path)
    text = _pdfplumber_extract(path)
    lines = text.splitlines()
    assert any("CARRIER" in l and "Pinnacle" in l for l in lines)
    assert any("AGENCY" in l and "Front Range" in l for l in lines)
    assert any(l.strip().startswith("1 97047") and "1,250,000" in l for l in lines)
    assert any(l.strip().startswith("2 91560") and "3,400,000" in l for l in lines)
