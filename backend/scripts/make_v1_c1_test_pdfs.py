"""make_v1_c1_test_pdfs.py - the live test package for V1 item C1.

Generates four PDFs that between them reproduce EVERY defect the client
reported in section 1, plus the two conflicts that must SURVIVE (if those stop
firing, the fix went too far and that is worse than the original bug).

    py backend/scripts/make_v1_c1_test_pdfs.py

Writes to test_data_v1_c1/ at the repo root. Upload all four together.

Design notes
------------
* Real text, not scans - reportlab emits extractable text, so pdfplumber reads
  it directly and the run does not depend on OCR quality. That keeps the test
  about the CONSISTENCY layer, which is what C1 changed.
* The values are the client's literal ones wherever the client supplied them
  (the Orbin address trio, the three policy numbers, the two EMC entities, the
  $3,000,000-vs-$1,000,000 umbrella limit) - the standing
  replay-client-report-verbatim rule.
* Deliberately FOUR policies, not three: the client's own point is that a
  package can carry any number, so the fixture proves the scope logic is not
  quietly tuned to the reported case.
"""
from __future__ import annotations

import os

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_data_v1_c1",
)

# ── The values under test ────────────────────────────────────────────────────
INSURED_FULL = "ORBIN CONTRACTING LLC"
INSURED_COMMA = "Orbin Contracting, LLC"
INSURED_TRUNC = "Orbin Contract"                 # mid-word truncation
DBA = "Orbin Roofing"

ADDR_DEC = "4800 Dahlia St # D13, Denver, CO 80216-3121"   # ZIP+4, abbreviated
ADDR_COI = "4800 Dahlia Street D13, Denver, CO 80216"      # spelled out, ZIP5
ADDR_APP = "Denver, Colorado"                              # city/state only

FEIN_DASHED = "84-2210987"
FEIN_PLAIN = "842210987"

POL_GL = "BBC7263-26"
POL_AUTO = "6E7-40-02---26"
POL_AUTO_SPACED = "6E7 40 02 26"                 # same policy, spaced printing
POL_UMB = "6J7-40-02---26"
POL_IM = "IM-5540-26"                            # a FOURTH policy

CARRIER_GL = "EMC Property & Casualty Company"
CARRIER_OTHER = "Employers Mutual Casualty Company"
CARRIER_LOSSRUN = "EMC Insurance Companies"      # alias of the same group

UMBRELLA_DEC = "$3,000,000"
UMBRELLA_COI = "$1,000,000"                      # THE CONFLICT THAT MUST SURVIVE


def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=2.6):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, f"{label}:")
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.21 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.22 * inch


def _note(c, y, text):
    c.setFont("Helvetica-Oblique", 8.5)
    c.drawString(1 * inch, y, text)
    return y - 0.19 * inch


# ═════════════════════════════════════════════════════════════════════════════
def doc1_dec_page(path):
    """Package declarations: FOUR policies, TWO carrier entities, ZIP+4 address."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE DECLARATIONS",
              "Renewal Declarations - Policy Period 07/15/2026 to 07/15/2027")
    y = _row(c, y, "Named Insured", INSURED_FULL)
    y = _row(c, y, "DBA", DBA)
    y = _row(c, y, "Mailing Address", ADDR_DEC)
    y = _row(c, y, "FEIN", FEIN_DASHED)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Business Phone", "303-555-0175")
    y = _row(c, y, "Annual Revenue", "$4,250,000")
    y = _row(c, y, "Total Payroll", "$1,880,000")
    y = _row(c, y, "Number of Employees", "18")

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS")
    c.setFont("Helvetica-Bold", 8.5)
    # Columns must be far enough apart that pdfplumber never interleaves two
    # cells' characters. At the first spacing 'Company' and 'BBC7263-26'
    # extracted as 'ComBpBaCny7263-26' - a fixture defect that looked exactly
    # like a product truncation bug (2026-08-22).
    cols = [0.55, 2.35, 4.15, 5.75, 6.55]
    for x, h in zip(cols, ["LINE OF BUSINESS", "CARRIER", "POLICY NUMBER",
                           "PREMIUM", "EFF / EXP"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 7)
    rows = [
        ("Commercial General Liability", "EMC Prop & Cas Co", POL_GL, "$6,720", "07/15/26-07/15/27"),
        ("Commercial Automobile Liability", "Employers Mutual Cas Co", POL_AUTO, "$2,991", "07/15/26-07/15/27"),
        ("Commercial Liability Umbrella", "Employers Mutual Cas Co", POL_UMB, "$4,100", "07/15/26-07/15/27"),
        ("Commercial Inland Marine", "Employers Mutual Cas Co", POL_IM, "$1,150", "07/15/26-07/15/27"),
        ("Commercial Property", "-", "-", "NO COVERAGE", "-"),
        ("Crime and Fidelity", "-", "-", "NO COVERAGE", "-"),
    ]
    for lob, car, pol, prem, per in rows:
        for x, v in zip(cols, [lob, car, pol, prem, per]):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Policy Premium", "$14,961")

    y = _head(c, y, "CARRIER BY COVERAGE PART")
    y = _row(c, y, "General Liability Carrier", CARRIER_GL, 3.0)
    y = _row(c, y, "General Liability Policy Number", POL_GL, 3.0)
    y = _row(c, y, "Automobile Carrier", CARRIER_OTHER, 3.0)
    y = _row(c, y, "Automobile Policy Number", POL_AUTO, 3.0)
    y = _row(c, y, "Umbrella Carrier", CARRIER_OTHER, 3.0)
    y = _row(c, y, "Umbrella Policy Number", POL_UMB, 3.0)
    y = _row(c, y, "Inland Marine Carrier", CARRIER_OTHER, 3.0)
    y = _row(c, y, "Inland Marine Policy Number", POL_IM, 3.0)

    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _row(c, y, "Products/Completed Ops Aggregate", "$2,000,000")

    y = _head(c, y, "COMMERCIAL LIABILITY UMBRELLA")
    y = _row(c, y, "Each Occurrence Limit", UMBRELLA_DEC)
    y = _row(c, y, "Aggregate Limit", UMBRELLA_DEC)
    y = _row(c, y, "Self-Insured Retention", "$0")

    y = _head(c, y, "COMMERCIAL AUTOMOBILE")
    y = _row(c, y, "Covered Autos Liability", "Symbol 01 - Any Auto")
    y = _row(c, y, "Comprehensive / Collision", "Symbol 07  Deductible $1,000")
    c.showPage()
    c.save()


def doc2_certificate(path):
    """COI: same address spelled out, comma'd name, FEWER lines, DIFFERENT umbrella."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "Issue Date 08/01/2026 - this certificate is issued as a matter of information only")
    y = _row(c, y, "Insured", INSURED_COMMA)
    y = _row(c, y, "Address", ADDR_COI)
    y = _row(c, y, "Producer", "Summit Commercial Insurance, 1800 Market Street, Denver, CO 80202")
    y = _row(c, y, "Insurer A", CARRIER_GL)
    y = _row(c, y, "Insurer B", CARRIER_OTHER)

    y = _head(c, y, "COVERAGES")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.9, 4.4, 6.0]
    for x, h in zip(cols, ["TYPE OF INSURANCE", "POLICY NUMBER", "POLICY PERIOD", "LIMITS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    # Deliberately FEWER lines than the dec, and DIFFERENT terminology.
    rows = [
        ("General Liability", POL_GL, "07/15/26-07/15/27", "Each Occurrence $1,000,000"),
        ("", "", "", "General Aggregate $2,000,000"),
        ("Automobile Liability", POL_AUTO, "07/15/26-07/15/27", "Combined Single Limit $1,000,000"),
        ("Umbrella Liability", POL_UMB, "07/15/26-07/15/27", f"Each Occurrence {UMBRELLA_COI}"),
    ]
    for a, b, d, e in rows:
        for x, v in zip(cols, [a, b, d, e]):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _note(c, y, "Licensed electrical and roofing contractor. Commercial and residential")
    y = _note(c, y, "installation, repair and service work performed at customer locations.")
    c.showPage()
    c.save()


def doc3_application(path):
    """Application: city/state-only address, TRUNCATED insured name, a SPECIALTY line."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION - SUPPLEMENT",
              "Submitted by Summit Commercial Insurance")
    y = _row(c, y, "Applicant", INSURED_TRUNC)
    y = _row(c, y, "Location", ADDR_APP)
    y = _row(c, y, "FEIN", FEIN_DASHED)
    y = _row(c, y, "Number of Employees", "18")
    y = _row(c, y, "Annual Revenue", "$4,250,000")
    y = _row(c, y, "Date Business Started", "06/15/2014")

    y = _head(c, y, "OTHER COVERAGE CARRIED")
    y = _row(c, y, "Professional Liability", "Carrier: Hartford Fire Insurance Company")
    y = _row(c, y, "Policy Number", "PL-99881-26")
    y = _note(c, y, "(Professional Liability is a separate line - it is NOT General Liability.)")

    y = _head(c, y, "OPERATIONS")
    y = _note(c, y, "Administrative office, contracting warehouse and material storage at the")
    y = _note(c, y, "Denver premises. Crews perform electrical installation, panel upgrades and")
    y = _note(c, y, "roofing work at customer sites. No manufacturing is performed.")
    c.showPage()
    c.save()


def doc4_loss_run(path):
    """Loss run: FEIN with NO punctuation, policy number SPACED, carrier ALIAS."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT", f"Prepared by {CARRIER_LOSSRUN} - Valuation Date 08/01/2026")
    y = _row(c, y, "Insured", INSURED_COMMA)
    y = _row(c, y, "FEIN", FEIN_PLAIN)
    y = _row(c, y, "Policy Number", POL_AUTO_SPACED)
    y = _row(c, y, "Carrier", CARRIER_LOSSRUN)
    y = _row(c, y, "Period Covered", "07/15/2021 to 08/01/2026  (5 years)")

    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.1, 3.3, 5.0, 5.9, 6.7]
    for x, h in zip(cols, ["DATE OF LOSS", "LINE", "DESCRIPTION", "PAID",
                           "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        ("03/28/2024", "Business Auto", "Insured vehicle rear-ended third party",
         "$4,850", "$0", "Closed"),
        ("11/02/2022", "General Liability", "Water damage to customer premises",
         "$12,300", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$17,150")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    made = []
    for name, fn in (("1_dec_page.pdf", doc1_dec_page),
                     ("2_certificate.pdf", doc2_certificate),
                     ("3_application.pdf", doc3_application),
                     ("4_loss_run.pdf", doc4_loss_run)):
        path = os.path.join(OUT_DIR, name)
        fn(path)
        made.append((name, os.path.getsize(path)))
    print(f"Wrote {len(made)} PDFs to {OUT_DIR}")
    for n, sz in made:
        print(f"   {n:22s} {sz/1024:6.1f} KB")


if __name__ == "__main__":
    main()
