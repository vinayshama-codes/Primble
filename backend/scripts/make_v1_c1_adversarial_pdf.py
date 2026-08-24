"""make_v1_c1_adversarial_pdf.py - the NEGATIVE CONTROL for the C1 fixture.

    py backend/scripts/make_v1_c1_adversarial_pdf.py

Writes ``test_data_v1_c1/6_conflicting_dec.pdf``.

WHY THIS FILE EXISTS
--------------------
Nine of the ten checks in ``README-HOW-TO-TEST.md`` are "this must NOT fire".
Only the umbrella gate tests the other direction. A fixture shaped that way
cannot tell "the fix works" apart from "the check is dead" - the exact trap
``improving-ll.md`` C25 documents, where a coverage test passed over a pipeline
that was dropping 46% of its input.

So this document is uploaded ALONGSIDE 1-5 in a SECOND submission (Run B) and
every planted item below MUST produce a row. A silent Run B means the checks
are dead, not passing.

WHAT IS PLANTED, AND WHAT MUST FIRE
-----------------------------------
1. mailing_address   - a different street, city and ZIP. NOT a component of the
                       Denver address; that case is check 1's "must not fire".
2. dba_name          - a different trade name. Warning, not a hard stop.
3. num_employees     - 47 against the 18 that files 1 and 3 both state.
4. carrier_name      - THE IMPORTANT ONE. A second General Liability carrier,
                       on the SAME line, in the SAME period. `_scope_values`
                       must REFUSE to scope this and must say so: two policies
                       on one coverage line is the single case its per-line
                       disjointness guard exists for. If this scopes into
                       silence it is C1-H all over again.
5. gl_each_occurrence / gl_aggregate - $2M/$4M against $1M/$2M.
6. lines_of_business - Commercial Property is GRANTED here (carrier, policy
                       number, premium, limits) while files 1 and 5 both mark
                       it NO COVERAGE. That is positive evidence on both sides,
                       which is what client 1.7's acceptance criterion requires
                       before a LOB conflict may be raised.

WHAT IS DELIBERATELY *NOT* PLANTED
----------------------------------
* The FEIN and the insured name are IDENTICAL to the rest of the package. Both
  drive a blocking pause in `submission_integrity` and a 60 cap, which would
  stop the run before most of the screen renders. The identity comparator still
  gets a negative control through the DBA row, which is only a warning.
* Auto and Umbrella are repeated here identical to file 1 - same carrier, same
  policy numbers, same limits. They are the IN-RUN CONTROL: if a second
  declarations page simply floods the screen with conflicts, those two light up
  as well, and that tells us the detection is not targeted.
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

# -- Values that MATCH the rest of the package (must stay quiet) -------------
INSURED_FULL = "ORBIN CONTRACTING LLC"
FEIN_DASHED = "84-2210987"
POL_AUTO = "6E7-40-02---26"
POL_UMB = "6J7-40-02---26"
CARRIER_OTHER = "Employers Mutual Casualty Company"
UMBRELLA_LIMIT = "$3,000,000"

# -- Values that CONFLICT (every one must produce a row) --------------------
DBA_CONFLICT = "Orbin Electrical Services"                      # vs "Orbin Roofing"
ADDR_CONFLICT = "2255 S Wadsworth Blvd Ste 410, Lakewood, CO 80227"
EMPLOYEES_CONFLICT = "47"                                       # vs 18
CARRIER_GL_RIVAL = "Travelers Property Casualty Company of America"
POL_GL_RIVAL = "GL-4471102-26"                                  # vs BBC7263-26
POL_PROP_RIVAL = "CP-4471103-26"
GL_OCC_CONFLICT = "$2,000,000"                                  # vs $1,000,000
GL_AGG_CONFLICT = "$4,000,000"                                  # vs $2,000,000


def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=2.9):
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


def doc6_conflicting_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "SUPPLEMENTAL COMMERCIAL DECLARATIONS",
              "Policy Period 07/15/2026 to 07/15/2027 - issued 08/05/2026")

    y = _row(c, y, "Named Insured", INSURED_FULL)
    y = _row(c, y, "DBA", DBA_CONFLICT)
    y = _row(c, y, "Mailing Address", ADDR_CONFLICT)
    y = _row(c, y, "FEIN", FEIN_DASHED)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Number of Employees", EMPLOYEES_CONFLICT)

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS")
    c.setFont("Helvetica-Bold", 8.5)
    # Wide columns on purpose: at tighter spacing pdfplumber interleaved the
    # carrier and policy cells and produced 'ComBpBaCny7263-26', a fixture
    # defect that read exactly like a product truncation bug (2026-08-22).
    cols = [0.55, 2.45, 4.55, 6.00, 6.75]
    for x, h in zip(cols, ["LINE OF BUSINESS", "CARRIER", "POLICY NUMBER",
                           "PREMIUM", "EFF / EXP"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 7)
    rows = [
        # THE RIVAL GL - same line, same period, a different carrier entity.
        ("Commercial General Liability", "Travelers Prop Cas Co of Am",
         POL_GL_RIVAL, "$7,410", "07/15/26-07/15/27"),
        # GRANTED here; files 1 and 5 both print NO COVERAGE for this line.
        ("Commercial Property", "Travelers Prop Cas Co of Am",
         POL_PROP_RIVAL, "$3,880", "07/15/26-07/15/27"),
        # CONTROL - identical to file 1. These must stay quiet.
        ("Commercial Automobile Liability", "Employers Mutual Cas Co",
         POL_AUTO, "$2,991", "07/15/26-07/15/27"),
        ("Commercial Liability Umbrella", "Employers Mutual Cas Co",
         POL_UMB, "$4,100", "07/15/26-07/15/27"),
    ]
    for lob, car, pol, prem, per in rows:
        for x, v in zip(cols, [lob, car, pol, prem, per]):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch

    # Every table row is repeated as a plain 'label: value' pair. The table is
    # the realistic shape; these pairs are what guarantees the values survive
    # whatever column-reflow decision the extractor makes.
    y = _head(c, y, "CARRIER BY COVERAGE PART")
    y = _row(c, y, "General Liability Carrier", CARRIER_GL_RIVAL, 3.2)
    y = _row(c, y, "General Liability Policy Number", POL_GL_RIVAL, 3.2)
    y = _row(c, y, "Commercial Property Carrier", CARRIER_GL_RIVAL, 3.2)
    y = _row(c, y, "Commercial Property Policy Number", POL_PROP_RIVAL, 3.2)
    y = _row(c, y, "Automobile Carrier", CARRIER_OTHER, 3.2)
    y = _row(c, y, "Automobile Policy Number", POL_AUTO, 3.2)
    y = _row(c, y, "Umbrella Carrier", CARRIER_OTHER, 3.2)
    y = _row(c, y, "Umbrella Policy Number", POL_UMB, 3.2)

    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _row(c, y, "Each Occurrence", GL_OCC_CONFLICT, 3.2)
    y = _row(c, y, "General Aggregate", GL_AGG_CONFLICT, 3.2)
    y = _row(c, y, "Products/Completed Ops Aggregate", GL_AGG_CONFLICT, 3.2)

    y = _head(c, y, "COMMERCIAL PROPERTY")
    y = _row(c, y, "Building Limit", "$1,450,000", 3.2)
    y = _row(c, y, "Business Personal Property Limit", "$325,000", 3.2)
    y = _row(c, y, "Property Deductible", "$5,000", 3.2)
    y = _row(c, y, "Causes of Loss Form", "Special Form", 3.2)

    y = _head(c, y, "COMMERCIAL LIABILITY UMBRELLA")
    y = _row(c, y, "Each Occurrence Limit", UMBRELLA_LIMIT, 3.2)
    y = _row(c, y, "Aggregate Limit", UMBRELLA_LIMIT, 3.2)

    c.showPage()
    c.save()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "6_conflicting_dec.pdf")
    doc6_conflicting_dec(path)
    print(f"Wrote {path}  ({os.path.getsize(path) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
