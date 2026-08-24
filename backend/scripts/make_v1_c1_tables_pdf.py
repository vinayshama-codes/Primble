"""make_v1_c1_tables_pdf.py - a FIFTH file for the V1 C1 test package: one
multi-page declarations document carrying five complex tables.

    py backend/scripts/make_v1_c1_tables_pdf.py

Writes test_data_v1_c1/5_complex_tables.pdf. Upload it WITH the other four
(same insured, same four policies, same renewal period) or alone.

WHAT EACH TABLE IS BUILT TO TEST in the dec index (LLM call 1, dedicated pass):
  T1 PREMIUM SUMMARY BY COVERAGE PART   - a Common Declarations page that prints
     an ACCOUNT number and no policy number: entries here must NOT borrow a
     policy number from another page. Three NO COVERAGE rows. A TRIA charge and
     a policy fee printed in the same column as the line premiums.
  TOC (not a table)                      - a table of contents whose values are
     page numbers: rule 6b says record nothing from it.
  T2 SCHEDULE OF HAZARDS (GL)            - four class-code rows over two
     locations. Four cells labelled RATE, four labelled ADVANCE PREMIUM: only a
     ROW key can say which rate belongs to which class code.
  T3 SCHEDULE OF COVERED AUTOS           - three vehicles, two garaged at the
     SAME address with the SAME deductibles: a per-cell index must not collapse
     them, and each VIN must stay on its own row.
  T4 SCHEDULE OF DRIVERS                 - names, DOBs, licence numbers: the
     C22 shape (a name in a code box, a VIN in a tax-id box) must not recur.
  T5 SCHEDULE OF UNDERLYING INSURANCE    - printed UNDER the umbrella heading
     but describing the GL and AUTO policies: the C23 discriminator. Entries
     must carry the GL/Auto keys, never the umbrella's. Includes a THIRD
     carrier (Pinnacol) and a policy number no other page prints.
The carrier name on every section page is printed as a captionless header
line (rule 9). Real text, not a scan - same as the other four files.
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

INSURED = "ORBIN CONTRACTING LLC"
ADDR = "4800 Dahlia St # D13, Denver, CO 80216-3121"
PRODUCER = "Commercial Risk Solutions, Inc., 9780 S Meridian Blvd Ste 400, Englewood, CO 80112-6072"
ACCOUNT = "0482854"
PERIOD = "07/15/2026 to 07/15/2027"

POL_GL, POL_AUTO, POL_UMB, POL_IM = "BBC7263-26", "6E7-40-02---26", "6J7-40-02---26", "IM-5540-26"
CARRIER_GL = "EMC Property & Casualty Company"
CARRIER_OTHER = "Employers Mutual Casualty Company"


def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9)
        c.drawString(1 * inch, 9.97 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.85 * inch, 7.5 * inch, 9.85 * inch)
    return 9.55 * inch


def _row(c, y, label, value, lw=2.6):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, f"{label}:")
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, value)
    return y - 0.21 * inch


def _head(c, y, text):
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y - 0.08 * inch, text)
    return y - 0.32 * inch


def _plain(c, y, text, size=9):
    c.setFont("Helvetica", size)
    c.drawString(1 * inch, y, text)
    return y - 0.2 * inch


def _table(c, y, cols, header, rows, size=7.5):
    c.setFont("Helvetica-Bold", size)
    for x, h in zip(cols, header):
        c.drawString(x * inch, y, h)
    y -= 0.19 * inch
    c.setFont("Helvetica", size)
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.18 * inch
    return y - 0.1 * inch


def build(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    # PAGE 1: common declarations + premium summary + table of contents
    y = _page(c, "COMMON POLICY DECLARATIONS",
              "Commercial Package Policy - Renewal Declarations")
    y = _row(c, y, "Account Number", ACCOUNT)
    y = _row(c, y, "Policy Period", f"{PERIOD} 12:01 A.M. Standard Time")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", ADDR)
    y = _row(c, y, "Producer", PRODUCER)
    y = _row(c, y, "Agent No.", "W6258-0001")
    y = _row(c, y, "Business Description", "Commercial General Contractor - Roofing and Electrical")
    y = _row(c, y, "Form of Business", "Limited Liability Company")

    y = _head(c, y, "PREMIUM SUMMARY BY COVERAGE PART")
    y = _table(c, y, [1.0, 1.55, 3.55, 4.85, 6.55],
               ["SECTION", "COVERAGE PART", "POLICY NUMBER", "CARRIER", "PREMIUM"],
               [("I",   "Commercial General Liability",  POL_GL,   "EMC Prop & Cas Co",       "$6,720.00"),
                ("II",  "Commercial Property",           "-",      "-",                       "NO COVERAGE"),
                ("III", "Commercial Automobile",         POL_AUTO, "Employers Mutual Cas Co", "$2,991.00"),
                ("IV",  "Commercial Inland Marine",      POL_IM,   "Employers Mutual Cas Co", "$1,150.00"),
                ("V",   "Commercial Liability Umbrella", POL_UMB,  "Employers Mutual Cas Co", "$4,100.00"),
                ("VI",  "Workers Compensation",          "-",      "-",                       "NO COVERAGE"),
                ("VII", "Crime and Fidelity",            "-",      "-",                       "NO COVERAGE")])
    y = _row(c, y, "Total Policy Premium", "$14,961.00", 3.2)
    y = _row(c, y, "Certified Acts of Terrorism Premium", "$31.00", 3.2)
    y = _row(c, y, "Policy Administration Fee", "$250.00", 3.2)
    y = _row(c, y, "Total Amount Due", "$15,242.00", 3.2)

    y = _head(c, y, "TABLE OF CONTENTS")
    for line, pg in [("SECTION I - COMMON DECLARATIONS", "1"),
                     ("SECTION II - GENERAL LIABILITY DECLARATIONS", "2"),
                     ("SECTION III - LIMITS OF INSURANCE", "2"),
                     ("SECTION IV - BUSINESS AUTO DECLARATIONS", "3"),
                     ("SECTION V - COMMERCIAL UMBRELLA DECLARATIONS", "4"),
                     ("SECTION VI - FORMS AND ENDORSEMENTS", "4")]:
        c.setFont("Helvetica", 9)
        c.drawString(1 * inch, y, line)
        c.drawString(6.9 * inch, y, pg)
        y -= 0.2 * inch
    c.showPage()

    # PAGE 2: GL declarations + schedule of hazards + locations
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(1 * inch, 10.55 * inch, CARRIER_GL)          # captionless carrier line
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              f"Policy Number {POL_GL}    Policy Period {PERIOD}")
    y = _row(c, y, "Named Insured", INSURED)
    y = _head(c, y, "LIMITS OF INSURANCE")
    for k, v in [("Each Occurrence Limit", "$1,000,000"),
                 ("General Aggregate Limit", "$2,000,000"),
                 ("Products-Completed Operations Aggregate Limit", "$2,000,000"),
                 ("Personal and Advertising Injury Limit", "$1,000,000 (any one person or organization)"),
                 ("Damage to Premises Rented to You Limit", "$100,000 (any one premises)"),
                 ("Medical Expense Limit", "$5,000 (any one person)"),
                 ("Deductible", "$1,000 per claim (Bodily Injury and Property Damage)")]:
        y = _row(c, y, k, v, 3.6)
    y = _head(c, y, "SCHEDULE OF HAZARDS")
    y = _table(c, y, [1.0, 1.3, 2.2, 4.25, 5.05, 5.75, 6.25, 6.85],
               ["LOC", "CLASS CODE", "CLASSIFICATION", "PREM BASIS", "EXPOSURE", "TERR", "RATE", "ADVANCE PREMIUM"],
               [("001", "91580", "Contractors - Executive Supervisors",  "Payroll",    "$285,000", "004", "6.119",  "$1,744"),
                ("001", "98305", "Roofing - Commercial",                 "Payroll",    "$640,000", "004", "5.000",  "$3,200"),
                ("002", "91585", "Contractors - Subcontracted Work NOC", "Total Cost", "$350,000", "004", "2.293",  "$803"),
                ("002", "91340", "Carpentry - Interior",                 "Payroll",    "$95,000",  "004", "10.242", "$973")])
    y = _plain(c, y, "Rates are per $1,000 of premium basis.", 8)
    y = _row(c, y, "Total Advance Premium - General Liability", "$6,720.00", 3.6)
    y = _head(c, y, "LOCATIONS")
    y = _table(c, y, [1.0, 1.5, 5.0, 6.3],
               ["LOC", "ADDRESS", "OCCUPANCY", "INTEREST"],
               [("001", "4800 Dahlia St # D13, Denver, CO 80216-3121", "Office and Warehouse", "Tenant"),
                ("002", "1220 W Colfax Ave, Aurora, CO 80011",         "Material Yard",        "Owner")])
    c.showPage()

    # PAGE 3: business auto declarations + vehicle and driver schedules
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(1 * inch, 10.55 * inch, CARRIER_OTHER)
    y = _page(c, "BUSINESS AUTO DECLARATIONS",
              f"Policy Number {POL_AUTO}    Policy Period {PERIOD}")
    y = _row(c, y, "Named Insured", INSURED)
    y = _head(c, y, "ITEM TWO - SCHEDULE OF COVERAGES AND COVERED AUTOS")
    y = _table(c, y, [1.0, 3.3, 4.3, 6.3],
               ["COVERAGE", "COVERED AUTOS", "LIMIT", "PREMIUM"],
               [("Covered Autos Liability",          "01", "$1,000,000 Each Accident", "$1,496.00"),
                ("Auto Medical Payments",            "02", "$5,000 Each Person",       "$35.00"),
                ("Uninsured/Underinsured Motorists", "02", "$1,000,000 Each Accident", "$174.00"),
                ("Comprehensive",                    "07", "ACV less deductible",      "$612.00"),
                ("Collision",                        "07", "ACV less deductible",      "$674.00")])
    y = _row(c, y, "Total Premium - Business Auto", "$2,991.00", 3.2)
    y = _head(c, y, "ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN")
    y = _table(c, y, [1.0, 1.35, 1.75, 2.7, 4.0, 4.45, 5.45, 6.1, 6.8],
               ["VEH", "YEAR", "MAKE / MODEL", "VIN", "GVW", "GARAGING", "COMP DED", "COLL DED", "PREMIUM"],
               [("1", "2021", "Ford F-250",       "1FT7W2BT5MED12345", "10,000", "Denver, CO 80216", "$1,000", "$1,000", "$1,180.00"),
                ("2", "2019", "Subaru Outback",   "4S4BSANC9K3287714", "4,585",  "Denver, CO 80216", "$1,000", "$1,000", "$846.00"),
                ("3", "2023", "Ram 3500 Chassis", "3C7WRTCL4PG654321", "14,000", "Aurora, CO 80011", "$2,500", "$2,500", "$965.00")],
               size=7)
    y = _head(c, y, "ITEM FOUR - SCHEDULE OF DRIVERS")
    y = _table(c, y, [1.0, 1.35, 2.75, 3.75, 4.95, 5.45, 6.4],
               ["DRV", "NAME", "DATE OF BIRTH", "LICENSE NO.", "STATE", "DATE HIRED", "ASSIGNED VEH"],
               [("1", "Marcus Orbin",  "03/14/1979", "CO-94-118-0422", "CO", "06/15/2014", "1"),
                ("2", "Erin Royal",    "11/02/1988", "CO-02-557-9031", "CO", "02/01/2019", "2"),
                ("3", "Daniel Ortega", "07/30/1995", "CO-71-204-6618", "CO", "09/12/2023", "3")])
    c.showPage()

    # PAGE 4: umbrella declarations + schedule of underlying insurance
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(1 * inch, 10.55 * inch, CARRIER_OTHER)
    y = _page(c, "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS",
              f"Policy Number {POL_UMB}    Policy Period {PERIOD}")
    y = _row(c, y, "Named Insured", INSURED)
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Each Occurrence Limit", "$3,000,000", 3.2)
    y = _row(c, y, "Aggregate Limit", "$3,000,000", 3.2)
    y = _row(c, y, "Self-Insured Retention", "$10,000", 3.2)
    y = _row(c, y, "Premium", "$4,100.00", 3.2)
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, [1.0, 2.35, 3.75, 4.75, 5.7],
               ["TYPE OF POLICY", "INSURER", "POLICY NUMBER", "POLICY PERIOD", "LIMITS"],
               [("Commercial General Liability", "EMC Property & Casualty Co",   POL_GL,    "07/15/26-07/15/27", "Each Occurrence $1,000,000"),
                ("",                             "",                             "",        "",                  "General Aggregate $2,000,000"),
                ("",                             "",                             "",        "",                  "Products/Completed Ops $2,000,000"),
                ("Business Auto Liability",      "Employers Mutual Casualty Co", POL_AUTO,  "07/15/26-07/15/27", "Each Accident $1,000,000"),
                ("Employers Liability",          "Pinnacol Assurance",           "4192077", "07/15/26-07/15/27", "Each Accident $500,000")],
               size=7)
    y = _head(c, y, "FORMS AND ENDORSEMENTS APPLICABLE")
    y = _plain(c, y, "CU 00 01 04 13    CU 21 23 02 02    CU 21 27 12 04    IL 00 17 11 98    IL 00 21 09 08", 8.5)
    c.showPage()
    c.save()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "5_complex_tables.pdf")
    build(path)
    print(f"Wrote {path} ({os.path.getsize(path) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
