"""
Generate a test PDF for §6.5 Umbrella Adequacy UI verification.

Usage:
    cd backend
    python scripts/generate_test_pdf.py

Outputs:
    backend/tmp/umbrella_test_weak.pdf   -- umbrella present, score ~55, warns on low GL
    backend/tmp/umbrella_test_strong.pdf -- umbrella present, all limits met, score ~100
    backend/tmp/umbrella_test_none.pdf   -- no umbrella, N/A path

Run with:  pip install reportlab  (if not already installed)
"""
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tmp")
os.makedirs(OUT_DIR, exist_ok=True)

styles = getSampleStyleSheet()

TITLE_STYLE   = ParagraphStyle("title",   parent=styles["Heading1"], alignment=TA_CENTER, fontSize=14)
H2_STYLE      = ParagraphStyle("h2",      parent=styles["Heading2"], fontSize=11, spaceAfter=4)
BODY_STYLE    = ParagraphStyle("body",    parent=styles["Normal"],   fontSize=9,  leading=13)
SECTION_STYLE = ParagraphStyle("section", parent=styles["Heading3"], fontSize=10, spaceBefore=10, spaceAfter=4)

def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths or [2.5*inch, 4*inch])
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#e8e8e8")),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("GRID",          (0,0), (-1,-1), 0.5, colors.grey),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
    ]))
    return t


def _build_weak(path: str):
    """Umbrella present; GL below threshold. Expect score ~55, 2-3 warnings in UI."""
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    story = []

    story.append(Paragraph("COMMERCIAL INSURANCE - POLICY DECLARATIONS", TITLE_STYLE))
    story.append(Paragraph("ACORD 125 - Commercial Insurance Application", TITLE_STYLE))
    story.append(Spacer(1, 0.15*inch))

    # Named insured block
    story.append(_table([
        ["Field", "Value"],
        ["Producer",            "Pinnacle Insurance Brokers, LLC"],
        ["Named Insured",       "Orbin Contracting LLC"],
        ["Mailing Address",     "18 Depot Street, Raleigh, NC 27601"],
        ["FEIN",                "56-1234567"],
        ["Policy Effective",    "01/01/2026"],
        ["Policy Expiration",   "01/01/2027"],
        ["Business Description","General contractor - commercial remodeling"],
    ]))
    story.append(Spacer(1, 0.15*inch))

    # GL section - intentionally LOW to trigger warnings
    story.append(Paragraph("COMMERCIAL GENERAL LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "Coverage Form: CGL Occurrence. Insurer: Hartford Fire Insurance Company. Policy No: GL-2026-001.",
        BODY_STYLE))
    story.append(_table([
        ["Coverage",              "Limit"],
        ["Each Occurrence Limit", "$500,000"],           # <-- below $1M threshold
        ["General Aggregate",     "$1,000,000"],          # <-- below $2M threshold
        ["Products-Comp/Op Agg", "$1,000,000"],
        ["Personal & Adv Injury", "$500,000"],
        ["Fire Damage (any one)", "$100,000"],
        ["Med Exp (any one)",     "$5,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    # Auto section - meets threshold
    story.append(Paragraph("COMMERCIAL AUTOMOBILE LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "Policy covers owned, hired, and non-owned autos. Insurer: Travelers Indemnity. Policy No: CA-2026-001.",
        BODY_STYLE))
    story.append(_table([
        ["Coverage",                "Limit"],
        ["Combined Single Limit",   "$1,000,000"],       # meets $1M CSL threshold
        ["Uninsured Motorists",     "$1,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    # WC / EL section - EL below $500K (each-accident figure)
    story.append(Paragraph("WORKERS COMPENSATION AND EMPLOYERS LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "Statutory Workers Compensation. Insurer: Liberty Mutual. Policy No: WC-2026-001.",
        BODY_STYLE))
    story.append(_table([
        ["Coverage",                   "Limit"],
        ["Workers Compensation",       "Statutory"],
        ["EL Each Accident",           "$100,000"],      # <-- triggers EL warning
        ["EL Disease - Policy Limit",  "$500,000"],
        ["EL Disease - Each Employee", "$100,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    # Umbrella section - present and clearly stated with dollar amount
    story.append(Paragraph("COMMERCIAL UMBRELLA / EXCESS LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "Insurer: XL Insurance. Policy No: UMB-2026-001. "
        "Coverage: Commercial Umbrella Liability. "
        "The umbrella policy provides coverage in excess of the scheduled underlying policies.",
        BODY_STYLE))
    story.append(_table([
        ["Coverage",            "Limit"],
        ["Each Occurrence",     "$5,000,000"],
        ["Aggregate Limit",     "$5,000,000"],
        ["Self-Insured Retention (SIR)", "$10,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(
        "NOTE: No schedule of underlying insurance is attached to this application.",
        BODY_STYLE))

    doc.build(story)
    print(f"  Created: {path}")


def _build_strong(path: str):
    """Umbrella present; all limits met; follow-form explicit. Expect score ~100."""
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    story = []

    story.append(Paragraph("COMMERCIAL INSURANCE - POLICY DECLARATIONS", TITLE_STYLE))
    story.append(Paragraph("ACORD 125 - Commercial Insurance Application (Strong Case)", TITLE_STYLE))
    story.append(Spacer(1, 0.15*inch))

    story.append(_table([
        ["Field", "Value"],
        ["Producer",            "Summit Risk Advisors Inc."],
        ["Named Insured",       "Meridian Construction Corp."],
        ["Mailing Address",     "400 Commerce Blvd, Charlotte, NC 28201"],
        ["FEIN",                "83-4567890"],
        ["Policy Effective",    "01/01/2026"],
        ["Policy Expiration",   "01/01/2027"],
        ["Business Description","Commercial general contractor"],
    ]))
    story.append(Spacer(1, 0.15*inch))

    story.append(Paragraph("COMMERCIAL GENERAL LIABILITY", SECTION_STYLE))
    story.append(_table([
        ["Coverage",              "Limit"],
        ["Each Occurrence Limit", "$1,000,000"],         # meets $1M threshold
        ["General Aggregate",     "$2,000,000"],          # meets $2M threshold
        ["Products-Comp/Op Agg", "$2,000,000"],
        ["Personal & Adv Injury", "$1,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("COMMERCIAL AUTOMOBILE LIABILITY", SECTION_STYLE))
    story.append(_table([
        ["Coverage",              "Limit"],
        ["Combined Single Limit", "$1,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("WORKERS COMPENSATION AND EMPLOYERS LIABILITY", SECTION_STYLE))
    story.append(_table([
        ["Coverage",                   "Limit"],
        ["Workers Compensation",       "Statutory"],
        ["EL Each Accident",           "$1,000,000"],    # meets full-credit threshold
        ["EL Disease - Policy Limit",  "$1,000,000"],
        ["EL Disease - Each Employee", "$1,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("COMMERCIAL UMBRELLA / EXCESS LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "Insurer: Chubb Group. Policy No: UMB-2026-STRONG-001. "
        "The umbrella policy follows form and provides coverage excess of and following "
        "the terms and conditions of the scheduled underlying policies listed below.",
        BODY_STYLE))
    story.append(_table([
        ["Coverage",            "Limit"],
        ["Each Occurrence",     "$10,000,000"],
        ["Aggregate Limit",     "$10,000,000"],
        ["Self-Insured Retention (SIR)", "$0"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("SCHEDULE OF UNDERLYING INSURANCE", SECTION_STYLE))
    story.append(_table([
        ["Policy Type",                "Insurer",              "Limit"],
        ["Commercial General Liability","Hartford",            "$1,000,000 per occ / $2,000,000 agg"],
        ["Commercial Auto",            "Travelers",            "$1,000,000 CSL"],
        ["Workers Compensation",       "Liberty Mutual",       "Statutory / $1,000,000 EL"],
    ], col_widths=[2*inch, 2*inch, 2.5*inch]))

    doc.build(story)
    print(f"  Created: {path}")


def _build_none(path: str):
    """No umbrella section at all. Expect N/A in UI (umbrella sub-block not rendered)."""
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    story = []

    story.append(Paragraph("COMMERCIAL INSURANCE - POLICY DECLARATIONS", TITLE_STYLE))
    story.append(Paragraph("ACORD 125 - Commercial Insurance Application (No Umbrella)", TITLE_STYLE))
    story.append(Spacer(1, 0.15*inch))

    story.append(_table([
        ["Field", "Value"],
        ["Producer",            "Coast Insurance Group"],
        ["Named Insured",       "Harborview Landscaping LLC"],
        ["Mailing Address",     "55 Oak Avenue, Wilmington, NC 28401"],
        ["FEIN",                "27-9988776"],
        ["Policy Effective",    "01/01/2026"],
        ["Policy Expiration",   "01/01/2027"],
        ["Business Description","Commercial landscaping and lawn maintenance"],
    ]))
    story.append(Spacer(1, 0.15*inch))

    story.append(Paragraph("COMMERCIAL GENERAL LIABILITY", SECTION_STYLE))
    story.append(_table([
        ["Coverage",              "Limit"],
        ["Each Occurrence Limit", "$1,000,000"],
        ["General Aggregate",     "$2,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("COMMERCIAL AUTOMOBILE LIABILITY", SECTION_STYLE))
    story.append(_table([
        ["Coverage",              "Limit"],
        ["Combined Single Limit", "$1,000,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("NO UMBRELLA OR EXCESS LIABILITY", SECTION_STYLE))
    story.append(Paragraph(
        "No commercial umbrella or excess liability coverage is included in this submission. "
        "Client has declined umbrella coverage.",
        BODY_STYLE))

    doc.build(story)
    print(f"  Created: {path}")


if __name__ == "__main__":
    print("Generating test PDFs...")
    _build_weak(   os.path.join(OUT_DIR, "umbrella_test_weak.pdf"))
    _build_strong( os.path.join(OUT_DIR, "umbrella_test_strong.pdf"))
    _build_none(   os.path.join(OUT_DIR, "umbrella_test_none.pdf"))
    print("\nDone. Upload via Primble UI:")
    print("  umbrella_test_weak.pdf   -> expect score ~55, Umbrella Adequacy pillar with warnings")
    print("  umbrella_test_strong.pdf -> expect score ~100, green follow-form confirmed")
    print("  umbrella_test_none.pdf   -> expect Umbrella Adequacy = N/A, sub-block hidden")
