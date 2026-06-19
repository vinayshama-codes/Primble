"""
Generate two conflicting declarations PDFs to test Form SQS vs Package SQS divergence.

Same insured, same location - but Doc A states building value $2,000,000
and Doc B states building value $3,500,000. When both are uploaded and ONE
form is selected, the system detects the conflict and caps Package SQS at 60
while Form SQS keeps its higher score. That gap proves the two are computed
independently.

Usage:
    cd backend
    python scripts/generate_conflict_test_pdfs.py

Outputs:
    backend/tmp/conflict_doc_A.pdf  -- building value $2,000,000
    backend/tmp/conflict_doc_B.pdf  -- building value $3,500,000 (intentional conflict)

Upload BOTH files together in one Primble session, then select one form (ACORD 125
or ACORD 140). Expected: Form SQS > 60, Package SQS capped at 60.
Resolve the conflict in the Data Consistency picker -> Package re-converges to Form.
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
TITLE_STYLE   = ParagraphStyle("title",   parent=styles["Heading1"], alignment=TA_CENTER, fontSize=13, spaceAfter=4)
SUBTITLE_STYLE= ParagraphStyle("sub",     parent=styles["Normal"],   alignment=TA_CENTER, fontSize=9,  spaceAfter=10, textColor=colors.HexColor("#555555"))
H2_STYLE      = ParagraphStyle("h2",      parent=styles["Heading2"], fontSize=10, spaceBefore=10, spaceAfter=4)
BODY_STYLE    = ParagraphStyle("body",    parent=styles["Normal"],   fontSize=9,  leading=13)
WARN_STYLE    = ParagraphStyle("warn",    parent=styles["Normal"],   fontSize=8,  leading=12, textColor=colors.HexColor("#7c2d12"))

# Shared insured details - identical across both docs
INSURED = {
    "name":        "Lakewood Commercial Properties LLC",
    "address":     "340 Industrial Parkway, Durham, NC 27701",
    "fein":        "47-8821034",
    "effective":   "03/01/2026",
    "expiration":  "03/01/2027",
    "description": "Owner and operator of commercial warehouse and light industrial facilities",
    "producer":    "Triangle Risk Management Group",
    "insurer":     "Nationwide Property & Casualty Insurance Company",
    "policy_no":   "CPP-2026-LCP-001",
}


def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths or [2.6*inch, 3.9*inch])
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("BACKGROUND",    (0, 0), (-1,  0), colors.HexColor("#e8edf2")),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c4")),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
    ]))
    return t


def _highlight_table(data, highlight_row, col_widths=None):
    """Same as _table but highlights a specific row in amber to draw attention."""
    t = Table(data, colWidths=col_widths or [2.6*inch, 3.9*inch])
    style = [
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("BACKGROUND",    (0, 0), (-1,  0), colors.HexColor("#e8edf2")),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c4")),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("BACKGROUND",    (0, highlight_row), (-1, highlight_row), colors.HexColor("#fef3c7")),
        ("FONTNAME",      (0, highlight_row), (-1, highlight_row), "Helvetica-Bold"),
    ]
    t.setStyle(TableStyle(style))
    return t


def _build_doc(path: str, building_value: str, label: str, note: str):
    doc = SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.7*inch,   bottomMargin=0.7*inch,
    )
    story = []

    # Header
    story.append(Paragraph("COMMERCIAL PROPERTY - POLICY DECLARATIONS", TITLE_STYLE))
    story.append(Paragraph(f"Document {label}  |  Test document for Primble SQS verification", SUBTITLE_STYLE))
    story.append(Spacer(1, 0.1*inch))

    # Insured / policy block
    story.append(Paragraph("POLICY INFORMATION", H2_STYLE))
    story.append(_table([
        ["Field",                "Value"],
        ["Named Insured",        INSURED["name"]],
        ["Mailing Address",      INSURED["address"]],
        ["FEIN",                 INSURED["fein"]],
        ["Business Description", INSURED["description"]],
        ["Policy Number",        INSURED["policy_no"]],
        ["Insurer",              INSURED["insurer"]],
        ["Producer",             INSURED["producer"]],
        ["Policy Effective",     INSURED["effective"]],
        ["Policy Expiration",    INSURED["expiration"]],
    ]))
    story.append(Spacer(1, 0.12*inch))

    # Property schedule - building value is the intentional variable
    story.append(Paragraph("SCHEDULE OF INSURED LOCATIONS", H2_STYLE))
    story.append(Paragraph(
        "Location 1: 340 Industrial Parkway, Durham, NC 27701. "
        "Occupancy: Light industrial warehouse. Construction: Masonry non-combustible. "
        "Year Built: 1998. Sprinklered: Yes.",
        BODY_STYLE,
    ))
    story.append(Spacer(1, 0.06*inch))
    story.append(_highlight_table([
        ["Coverage Item",               "Amount / Detail"],
        ["Building Value (Replacement)", building_value],   # <-- the conflicting field
        ["Business Personal Property",  "$180,000"],
        ["Business Income / Extra Exp", "$240,000 (12-month period)"],
        ["Deductible",                  "$5,000 per occurrence"],
        ["Coinsurance",                 "90%"],
        ["Valuation Basis",             "Replacement Cost"],
    ], highlight_row=1))
    story.append(Spacer(1, 0.06*inch))
    story.append(Paragraph(
        note,
        WARN_STYLE,
    ))
    story.append(Spacer(1, 0.12*inch))

    # Liability section - identical in both docs
    story.append(Paragraph("COMMERCIAL GENERAL LIABILITY", H2_STYLE))
    story.append(Paragraph(
        "Coverage Form: CGL Occurrence. Insurer: Nationwide. Policy No: GL-2026-LCP-001.",
        BODY_STYLE,
    ))
    story.append(_table([
        ["Coverage",               "Limit"],
        ["Each Occurrence Limit",  "$1,000,000"],
        ["General Aggregate",      "$2,000,000"],
        ["Products-Comp/Op Agg",   "$2,000,000"],
        ["Personal & Adv Injury",  "$1,000,000"],
        ["Fire Damage (any one)",  "$100,000"],
        ["Med Exp (any one)",      "$10,000"],
    ]))
    story.append(Spacer(1, 0.1*inch))

    # Loss history - identical in both docs
    story.append(Paragraph("LOSS HISTORY (Prior 5 Years)", H2_STYLE))
    story.append(_table([
        ["Year",  "Type",       "Amount Paid", "Status"],
        ["2023",  "Property",   "$12,500",     "Closed"],
        ["2021",  "Liability",  "$0",          "Closed - no payment"],
        ["2020",  "Property",   "$8,200",      "Closed"],
    ], col_widths=[0.8*inch, 1.8*inch, 1.5*inch, 2.4*inch]))
    story.append(Spacer(1, 0.12*inch))

    # Footer note
    story.append(Paragraph(
        f"THIS IS A TEST DOCUMENT GENERATED FOR SQS VERIFICATION PURPOSES. "
        f"Building value on this document: {building_value}. "
        f"Document {label} of 2. Upload both documents together in one Primble session.",
        WARN_STYLE,
    ))

    doc.build(story)
    print(f"  Created: {path}  (building value: {building_value})")


if __name__ == "__main__":
    print("Generating conflicting building-value test PDFs...")
    print()

    _build_doc(
        path=os.path.join(OUT_DIR, "conflict_doc_A.pdf"),
        building_value="$2,000,000",
        label="A",
        note=(
            "Document A states building replacement value as $2,000,000. "
            "This conflicts with Document B which states $3,500,000 for the same location. "
            "The system should flag this as a data-consistency conflict on property_building_value."
        ),
    )

    _build_doc(
        path=os.path.join(OUT_DIR, "conflict_doc_B.pdf"),
        building_value="$3,500,000",
        label="B",
        note=(
            "Document B states building replacement value as $3,500,000. "
            "This conflicts with Document A which states $2,000,000 for the same location. "
            "The system should flag this as a data-consistency conflict on property_building_value."
        ),
    )

    print()
    print("=" * 60)
    print("NEXT STEPS - test Form SQS vs Package SQS divergence:")
    print("=" * 60)
    print()
    print("1. Open Primble in your browser.")
    print("2. Start a NEW session.")
    print("3. Upload BOTH files together:")
    print("     backend/tmp/conflict_doc_A.pdf")
    print("     backend/tmp/conflict_doc_B.pdf")
    print("4. Select ONE form - ACORD 125 or ACORD 140.")
    print("5. Generate the form and open the SQS panel.")
    print()
    print("EXPECTED RESULT:")
    print("  Form SQS   = real computed score (e.g. 75-85)")
    print("  Package SQS = 60  (hard-capped by building-value conflict)")
    print("  -> The two numbers differ. That is the correct behaviour.")
    print()
    print("TO CONFIRM THE GAP IS REAL (not random):")
    print("  Resolve the conflict in the Data Consistency picker")
    print("  -> Package SQS rises back to match Form SQS.")
    print()
    print("If both scores are the same even with the conflict, the")
    print("cross-document detection did not fire - check the session's")
    print("underwriting_consistency data in the backend logs.")
