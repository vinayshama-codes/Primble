"""make_c6_test_pdfs.py - live test packages for client section 6 (V1 H1,
Coverage-Specific SQS Gap Closure) - every clause and every fix, in FIVE
packages.

    py backend/scripts/make_c6_test_pdfs.py

Writes to c6_test_data/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks, the steps, and exactly what to send back.

FIVE packages, ONE file each, each its OWN session (a different company every
time, so extraction caches and identity matching never bleed). Merging is safe
because every check reads its OWN row - Auto Completeness, WC Supplemental,
Property, Umbrella, Operations - so one package can carry several gaps and each
still reads cleanly.

Package -> what it proves live
  P1  EVERYTHING MISSING   6.3 empty fleet (-25, warnings, agreed-value card
                           de-duped), 6.4 three gaps (-10, three cards), 6.2
                           no building/BPP value + deductible with no basis,
                           6.1 three GL gaps, 6.5 four umbrella shortfalls;
                           STEPS: the edit path, then answering the WC cards
  P2  EVERYTHING COMPLETE  the controls: every new row 0 / every pillar 100,
                           radius + USE printed on the 127, mod on the 130,
                           garaging satisfies the physical-address rule
  P3  NOT APPLICABLE       HNOA-only auto (0, no schedule questions, HNOA
                           questions asked) + "not experience rated" (0, no
                           X-Mod card)
  P4  NEW VENTURE          producer confirms -> X-Mod card gone; a re-run
                           (reclassify) KEEPS the confirmation
  P5  SPLIT LIMITS +       PD-missing hard stop with a typed Resolve that
      PARTIAL FLEET        clears it; vehicles + drivers but no garaging /
                           radius / use (-15, no warnings); PO Box with no
                           garaging fires the address warning (P2 control);
                           WC mod indicated-but-missing (-5) with a quarterly
                           payroll (a stated period, no -3)

Design rules (inherited from make_v1_c3_test_pdfs.py, all proven)
------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates are computed from TODAY so nothing drifts into an expired-term or
  renewal path.
* Every package's ABSENCES are self-verified at the bottom of this file by
  scanning the generated text - one stray word silently invalidates a check.
* FIXTURE RULE (learned building this): a class-code schedule row that
  carries a payroll AMOUNT satisfies the WC payroll period by definition
  (D43). A package that wants the -3 must rate GL on gross sales and print WC
  class codes WITHOUT remuneration.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "c6_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Northgate Insurance Partners LLC"
CARRIER = "Meridian Casualty Insurance Company"


# ── Layout helpers ──────────────────────────────────────────────────────────

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _new_page(c, title):
    c.showPage()
    return _page(c, title)


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


def _para(c, y, text):
    c.setFont("Helvetica", 9)
    c.drawString(1 * inch, y, text)
    return y - 0.19 * inch


def _table(c, y, headers, rows, cols):
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in zip(cols, headers):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, str(v))
        y -= 0.19 * inch
    return y - 0.09 * inch


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp, yib, naics,
               entity="Limited Liability Company"):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", entity)
    y = _row(c, y, "Contact", f"{contact}, {phone}, {email}")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Proposed Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", sales)
    y = _row(c, y, "Number of Employees", emp)
    y = _row(c, y, "Years in Business", yib)
    y = _row(c, y, "NAICS Code", naics)
    return y


def _gl(c, y, policy, occ="$1,000,000", agg="$2,000,000", form="Occurrence"):
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Coverage Form", form)
    y = _row(c, y, "Each Occurrence Limit", occ)
    y = _row(c, y, "General Aggregate Limit", agg)
    y = _row(c, y, "Annual Premium", "$9,640")
    return y


def _gl_classes(c, y, code, desc, basis, exposure):
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    return _table(c, y, ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
                  [["Location 1", f"{code} - {desc}", basis, exposure]],
                  [1.0, 2.5, 4.6, 5.9])


def _auto_head(c, y, policy):
    y = _head(c, y, "COVERAGE - BUSINESS AUTO")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    return y


def _vehicles(c, y):
    y = _head(c, y, "SCHEDULE OF VEHICLES")
    return _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW"],
                  [["2021", "Ford", "F-250", "1FT7W2BT5MED12345", "10,000"],
                   ["2019", "Isuzu", "NPR", "JALC4W163K7001234", "14,500"]],
                  [1.0, 1.8, 2.7, 3.7, 6.0])


def _drivers(c, y, a, b):
    y = _head(c, y, "SCHEDULE OF DRIVERS")
    return _table(c, y, ["NAME", "DATE OF BIRTH", "LICENSE NO", "STATE", "YEARS EXP"],
                  [[a[0], "04/12/1981", a[1], a[2], "22"],
                   [b[0], "09/30/1990", b[1], b[2], "9"]],
                  [1.0, 2.6, 3.8, 5.1, 5.9])


def _wc_head(c, y, policy, el="$1,000,000 / $1,000,000 / $1,000,000"):
    y = _head(c, y, "COVERAGE - WORKERS COMPENSATION AND EMPLOYERS LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Employers Liability", el)
    return y


def _wc_classes(c, y, state, rows, with_amounts=True):
    y = _head(c, y, "WORKERS COMPENSATION CLASS CODES")
    if with_amounts:
        return _table(c, y, ["STATE", "CLASS CODE", "DESCRIPTION", "REMUNERATION"],
                      [[state] + r for r in rows], [1.0, 1.9, 3.1, 5.9])
    return _table(c, y, ["STATE", "CLASS CODE", "DESCRIPTION"],
                  [[state] + r[:2] for r in rows], [1.0, 1.9, 3.1])


def _officers(c, y, rows):
    y = _head(c, y, "OFFICERS AND OWNERS")
    return _table(c, y, ["NAME", "TITLE", "OWNERSHIP %", "INCLUDED / EXCLUDED"],
                  rows, [1.0, 3.0, 4.6, 5.9])


def _property_head(c, y, policy):
    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    return y


def _umbrella_head(c, y, policy, limit):
    y = _head(c, y, "COVERAGE - COMMERCIAL UMBRELLA LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Umbrella Limit", limit)
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _row(c, y, "Annual Premium", "$6,200")
    return y


def _save(name, draw):
    path = os.path.join(OUT_DIR, name)
    c = canvas.Canvas(path, pagesize=LETTER)
    draw(c)
    c.showPage()
    c.save()
    return path


# ═════════════════════════════════════════════════════════════════════════════
# P1 - SUMMIT ROOFING: everything missing
# ═════════════════════════════════════════════════════════════════════════════
P1_NAME = "SUMMIT ROOFING CONTRACTORS LLC"


def p1_everything_missing(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - GL, Business Auto, Workers Compensation, Property and Umbrella")
    y = _applicant(c, y, P1_NAME, "410 Industrial Parkway, Denver CO 80216", "84-3390127",
                   "Aaron Blake", "(303) 555-0195", "aaron@summitroofingco.com",
                   "Roofing contractor - commercial and residential re-roofs",
                   "$2,450,000", "16", "9", "238160")
    # 6.1 - claims-made with no retro date; a RESTAURANT class code against
    # roofing operations; subcontracting stated (so the -8 does not muddy it);
    # GL rated on GROSS SALES so the WC payroll period stays unresolved (D43).
    y = _gl(c, y, "MCI-GL-883104", occ="$500,000", agg="$1,000,000", form="Claims-Made")
    y = _gl_classes(c, y, "9079", "Restaurants - with table service", "Gross Sales", "$2,450,000")
    y = _row(c, y, "Subcontracted Work", "35% of gross receipts")
    y = _para(c, y, "The general liability form is written on a claims-made basis.")
    # 6.3 - Business Auto requested, agreed value valuation, NOTHING about the fleet.
    y = _auto_head(c, y, "MCI-BA-883104")
    y = _row(c, y, "Liability - Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Covered Autos - Liability", "Symbol 01")
    y = _row(c, y, "Covered Autos - Comprehensive / Collision", "Symbol 07")
    y = _row(c, y, "Physical Damage Valuation", "Agreed Value")
    y = _row(c, y, "Annual Premium", "$4,120")
    y = _para(c, y, "Fleet, personnel, location and territory details to be supplied under separate cover.")

    y = _new_page(c, "COMMERCIAL INSURANCE APPLICATION - continued")
    # 6.4 - bare payroll, mod pending, officers named with no treatment,
    # class codes WITHOUT amounts.
    y = _wc_head(c, y, "MCI-WC-883104", el="$500,000 / $500,000 / $500,000")
    y = _row(c, y, "Payroll", "$780,000")
    y = _row(c, y, "Experience Modification", "Pending - rating bureau worksheet to follow")
    y = _wc_classes(c, y, "CO", [["5551", "Roofing - All Kinds"], ["8810", "Clerical Office Employees"]],
                    with_amounts=False)
    y = _officers(c, y, [["Aaron Blake", "President", "60%", ""],
                         ["Jenna Blake", "Secretary", "40%", ""]])
    # 6.2 - minimum COPE without either value; a deductible with no basis.
    y = _property_head(c, y, "MCI-CP-883104")
    y = _row(c, y, "Location 1", "410 Industrial Parkway, Denver CO 80216")
    y = _row(c, y, "Occupancy", "Contractor shop and yard - owner occupied")
    y = _row(c, y, "Construction", "Frame")
    y = _row(c, y, "Year Built", "1974")
    y = _row(c, y, "Deductible - All Other Perils", "$1,000")
    y = _para(c, y, "Building and contents limits to be advised once the appraisal is received.")
    # 6.5 - $2M over GL $500K/$1M and EL $500K, no schedule, follow-form unknown.
    y = _umbrella_head(c, y, "MCI-UMB-883104", "$2,000,000")
    y = _para(c, y, "Whether the umbrella follows form over the underlying policies is unable to be")
    y = _para(c, y, "determined from the quote; the schedule of underlying insurance was not supplied.")


# ═════════════════════════════════════════════════════════════════════════════
# P2 - OAKMONT PRINTING: everything complete (the controls)
# ═════════════════════════════════════════════════════════════════════════════
P2_NAME = "OAKMONT PRINTING COMPANY INC"


def p2_everything_complete(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - GL, Business Auto, Workers Compensation, Property and Umbrella")
    y = _applicant(c, y, P2_NAME, "PO Box 4120, Lancaster PA 17604", "23-1180467",
                   "Ruth Adler", "(717) 555-0128", "ruth@oakmontprinting.com",
                   "Commercial offset and digital printing with local delivery",
                   "$3,100,000", "21", "26", "323111", entity="Corporation")
    y = _gl(c, y, "MCI-GL-118220")
    y = _gl_classes(c, y, "58408", "Printing", "Payroll", "$980,000")
    y = _auto_head(c, y, "MCI-BA-118220")
    y = _row(c, y, "Liability - Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Covered Autos - Liability", "Symbol 01")
    y = _row(c, y, "Covered Autos - Comprehensive / Collision", "Symbol 07")
    y = _row(c, y, "Comprehensive Deductible", "$1,000")
    y = _row(c, y, "Collision Deductible", "$1,000")
    y = _row(c, y, "Radius of Operation", "50")
    y = _row(c, y, "Vehicle Use", "Retail")
    y = _row(c, y, "Garaging Address", "1850 Columbia Avenue, Lancaster PA 17603")
    y = _vehicles(c, y)
    y = _drivers(c, y, ("Ruth Adler", "PA 27716540", "PA"), ("Omar Haddad", "PA 30119872", "PA"))

    y = _new_page(c, "COMMERCIAL INSURANCE APPLICATION - continued")
    y = _wc_head(c, y, "MCI-WC-118220")
    y = _row(c, y, "Estimated Annual Payroll", "$980,000")
    y = _row(c, y, "Experience Modification", "0.92")
    y = _wc_classes(c, y, "PA", [["4299", "Printing", "$800,000"],
                                 ["8810", "Clerical Office Employees", "$180,000"]])
    y = _officers(c, y, [["Ruth Adler", "President", "70%", "Included"],
                         ["Simon Adler", "Treasurer", "30%", "Excluded"]])
    y = _property_head(c, y, "MCI-CP-118220")
    y = _row(c, y, "Location 1", "1850 Columbia Avenue, Lancaster PA 17603")
    y = _row(c, y, "Occupancy", "Printing plant - owner occupied")
    y = _row(c, y, "Construction", "Joisted Masonry")
    y = _row(c, y, "Year Built", "1998")
    y = _row(c, y, "Roof Year", "2019")
    y = _row(c, y, "Sprinkler System", "Yes - wet pipe, 100% of building")
    y = _row(c, y, "Fire Protection Class", "3")
    y = _row(c, y, "Distance to Hydrant", "450 feet")
    y = _row(c, y, "Fire Department", "Paid")
    y = _row(c, y, "Building Value", "$2,400,000")
    y = _row(c, y, "Business Personal Property Value", "$850,000")
    y = _row(c, y, "Valuation Method", "Replacement Cost Value")
    y = _row(c, y, "Coinsurance", "80%")
    y = _row(c, y, "Business Income Limit", "$600,000")
    y = _row(c, y, "Period of Restoration", "12 months")
    y = _row(c, y, "Deductible - All Other Perils", "$2,500")
    y = _row(c, y, "Deductible Basis", "Per Occurrence")

    y = _new_page(c, "COMMERCIAL INSURANCE APPLICATION - continued")
    y = _umbrella_head(c, y, "MCI-UMB-118220", "$5,000,000")
    y = _row(c, y, "Follow Form", "The umbrella follows form over all scheduled underlying policies")
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, ["LINE", "CARRIER", "POLICY NUMBER", "LIMIT"],
               [["General Liability", CARRIER, "MCI-GL-118220", "$1,000,000 / $2,000,000"],
                ["Business Auto", CARRIER, "MCI-BA-118220", "$1,000,000 CSL"],
                ["Employers Liability", CARRIER, "MCI-WC-118220", "$1,000,000"]],
               [1.0, 2.5, 4.6, 5.9])


# ═════════════════════════════════════════════════════════════════════════════
# P3 - LANTERN HILL CONSULTING: the not-applicable paths
# ═════════════════════════════════════════════════════════════════════════════
P3_NAME = "LANTERN HILL CONSULTING GROUP LLC"


def p3_not_applicable(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - GL, Hired / Non-Owned Auto and Workers Compensation")
    y = _applicant(c, y, P3_NAME, "740 Beacon Avenue, Suite 300, Madison WI 53703", "39-4410772",
                   "Priya Natarajan", "(608) 555-0121", "priya@lanternhillcg.com",
                   "Management consulting; staff visit client offices using rental and personal cars",
                   "$1,750,000", "11", "6", "541611")
    y = _gl(c, y, "MCI-GL-991207")
    y = _gl_classes(c, y, "41677", "Consultants - Management", "Payroll", "$980,000")
    y = _head(c, y, "COVERAGE - HIRED AND NON-OWNED AUTO LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "MCI-HNOA-991207")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Liability - Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Covered Autos - Liability", "Symbols 08 and 09")
    y = _row(c, y, "Annual Premium", "$412")
    y = _para(c, y, "The applicant owns no vehicles. Employees drive rental cars and their own")
    y = _para(c, y, "personal vehicles for client visits. Hired and non-owned liability only.")
    y = _wc_head(c, y, "MCI-WC-991207")
    y = _row(c, y, "Estimated Annual Payroll", "$980,000")
    y = _row(c, y, "Experience Modification", "Not applicable - the risk is not experience rated")
    y = _wc_classes(c, y, "WI", [["8803", "Management Consultants", "$820,000"],
                                 ["8810", "Clerical Office Employees", "$160,000"]])


# ═════════════════════════════════════════════════════════════════════════════
# P4 - JUNIPER TRAIL BAKERY: new venture
# ═════════════════════════════════════════════════════════════════════════════
P4_NAME = "JUNIPER TRAIL BAKERY LLC"


def p4_new_venture(c):
    started = (TODAY - timedelta(days=34)).strftime("%m/%d/%Y")
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability and Workers Compensation - NEW VENTURE")
    y = _applicant(c, y, P4_NAME, "27 Station Street, Bend OR 97702", "93-7710356",
                   "Sofia Marchetti", "(541) 555-0172", "sofia@junipertrailbakery.com",
                   "Retail bakery and cafe", "$420,000 (projected)", "6", "0", "311811")
    y = _row(c, y, "Date Business Started", started)
    y = _row(c, y, "New Venture", "Yes - operations began this year, no prior insurance")
    y = _gl(c, y, "MCI-GL-201455")
    y = _gl_classes(c, y, "10100", "Bakeries", "Gross Sales", "$420,000")
    y = _wc_head(c, y, "MCI-WC-201455")
    # The PAYROLL PERIOD gap lives here (moved from P1 after the first live run:
    # a class-code schedule with amounts satisfies the period by D43 as soon as
    # the extractor attributes the total to the rows, so P1 could never show the
    # -3). A bare figure, codes WITHOUT amounts, no period wording anywhere.
    y = _row(c, y, "Payroll", "$210,000")
    y = _row(c, y, "WC Class Codes", "2003 Bakeries; 8810 Clerical Office Employees")
    y = _officers(c, y, [["Sofia Marchetti", "Owner / Member", "100%", "Included"]])


# ═════════════════════════════════════════════════════════════════════════════
# P5 - PINE HOLLOW TREE SERVICE: split limits, partial fleet, mod indicated
# ═════════════════════════════════════════════════════════════════════════════
P5_NAME = "PINE HOLLOW TREE SERVICE LLC"


def p5_split_and_partial(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - GL, Business Auto and Workers Compensation")
    y = _applicant(c, y, P5_NAME, "PO Box 3350, Asheville NC 28802", "56-4471932",
                   "Caleb Morrow", "(828) 555-0151", "caleb@pinehollowtree.com",
                   "Tree trimming, removal and stump grinding",
                   "$1,150,000", "10", "6", "561730")
    y = _gl(c, y, "MCI-GL-449216")
    y = _gl_classes(c, y, "99777", "Tree Pruning, Spraying, Repairing", "Gross Sales", "$1,150,000")
    y = _auto_head(c, y, "MCI-BA-449216")
    y = _row(c, y, "Liability - Split Limits", "Bodily Injury $250,000 per person / $500,000 per accident")
    y = _row(c, y, "Covered Autos - Liability", "Symbol 01")
    y = _row(c, y, "Covered Autos - Comprehensive / Collision", "Symbol 07")
    y = _row(c, y, "Comprehensive Deductible", "$1,000")
    y = _row(c, y, "Collision Deductible", "$1,000")
    y = _vehicles(c, y)
    y = _drivers(c, y, ("Caleb Morrow", "NC 6612903", "NC"), ("Devon Pike", "NC 9034471", "NC"))
    y = _para(c, y, "Property damage limit per accident to be confirmed by the applicant.")
    y = _wc_head(c, y, "MCI-WC-449216")
    y = _row(c, y, "Quarterly Payroll (most recent quarter)", "$105,000")
    y = _row(c, y, "Experience Modification Effective Date", EFF)
    y = _row(c, y, "Experience Modification Factor", "")
    y = _wc_classes(c, y, "NC", [["0106", "Tree Pruning", "$340,000"],
                                 ["8810", "Clerical Office Employees", "$80,000"]])
    y = _officers(c, y, [["Caleb Morrow", "Managing Member", "100%", "Included"]])


# ── Self-verification ───────────────────────────────────────────────────────

def _text_of(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages).lower()


def _verify(paths: dict) -> list:
    p: list = []
    t = {k: _text_of(v) for k, v in paths.items()}

    def absent(key, *words):
        for w in words:
            if w in t[key]:
                p.append(f"{key} must NOT print {w!r}")

    def present(key, *words):
        for w in words:
            if w not in t[key]:
                p.append(f"{key} MUST print {w!r}")

    # P1 - every absence is a check
    absent("P1", "vin", "driver", "garag", "radius", "vehicle use", "schedule of vehicles",
           "retro", "acord 186", "contractors supplement", "annual payroll", "remuneration",
           "building value", "business personal property value", "deductible basis",
           "coinsurance", "valuation method", "schedule of underlying insurance\n",
           "hired", "non-owned")
    # "follows form" may appear ONLY inside the uncertainty clause ("whether ...
    # unable to be determined") - that mention is the negation guard's test.
    for m in re.finditer(r"follows form", t["P1"]):
        if "whether" not in t["P1"][max(0, m.start() - 40):m.start()]:
            p.append("P1 must not AFFIRM follow-form - only the 'whether ... unable' clause is allowed")
    present("P1", "agreed value", "symbol 01", "claims-made", "restaurants", "roofing",
            "subcontracted work", "pending", "payroll: $780,000", "gross sales",
            "deductible - all other perils", "construction: frame", "umbrella limit: $2,000,000",
            "$500,000 / $500,000", "unable to be")
    if re.search(r"experience modification[^\n]*\d\.\d", t["P1"]):
        p.append("P1 must not print a mod FACTOR")
    _p1_rows = t["P1"].replace("included / excluded", "")
    if "included" in _p1_rows or "excluded" in _p1_rows:
        p.append("P1 officer rows must carry no Included/Excluded value")
    # P2 - every presence is a control
    present("P2", "schedule of vehicles", "schedule of drivers", "garaging address",
            "radius of operation: 50", "vehicle use: retail", "po box", "estimated annual payroll",
            "0.92", "included", "excluded", "deductible basis: per occurrence", "coinsurance: 80%",
            "period of restoration", "replacement cost", "follows form",
            "schedule of underlying insurance", "$1,000,000 csl", "umbrella limit: $5,000,000")
    absent("P2", "claims-made", "agreed value")
    # P3
    absent("P3", "vin", "schedule of vehicles", "symbol 01", "symbol 07", "comprehensive",
           "collision", "garag", "officers and owners")
    present("P3", "08 and 09", "non-owned", "owns no vehicles", "not experience rated",
            "estimated annual payroll")
    # P4
    present("P4", "new venture", "date business started", "payroll: $210,000")
    absent("P4", "experience modification", "annual payroll", "remuneration", "per year")
    # P5
    present("P5", "$250,000 per person", "$500,000 per accident", "schedule of vehicles",
            "schedule of drivers", "po box", "quarterly payroll",
            "experience modification effective date", "included")
    absent("P5", "$100,000 per accident", "property damage: $", "garag", "radius", "vehicle use",
           "annual payroll")
    if re.search(r"experience modification factor:\s*\d", t["P5"]):
        p.append("P5 must leave the mod factor blank")
    return p


PACKAGES = [
    ("P1", "P1_everything_missing.pdf", p1_everything_missing),
    ("P2", "P2_everything_complete.pdf", p2_everything_complete),
    ("P3", "P3_hnoa_only_and_not_experience_rated.pdf", p3_not_applicable),
    ("P4", "P4_new_venture.pdf", p4_new_venture),
    ("P5", "P5_split_limits_partial_fleet_mod_indicated.pdf", p5_split_and_partial),
]


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for stale in os.listdir(OUT_DIR):
        if stale.endswith(".pdf") and not any(stale == n for _, n, _ in PACKAGES):
            os.remove(os.path.join(OUT_DIR, stale))
    paths = {}
    for key, name, draw in PACKAGES:
        paths[key] = _save(name, draw)
        print(f"  {key}: {name}")
    problems = _verify(paths)
    if problems:
        for msg in problems:
            print("  FIXTURE DEFECT:", msg)
        raise SystemExit(1)
    print("  self-verification: every package prints what it must and nothing it must not")
    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")


README = f"""
# Client section 6 (V1 H1) - live test kit, five packages - ROUND 2

Generated {TODAY.strftime('%Y-%m-%d')}. **Regenerate before every run**
(`py backend/scripts/make_c6_test_pdfs.py`). Extraction is now v16, so every
upload re-extracts under the stricter rule - do not reuse round-1 sessions.

## What round 1 proved (do NOT redo)

| Package | Passed on the first run |
|---|---|
| P1 | Auto Completeness -25, WC Supplemental -10, Operations -15, Property 0, the COPE hard stop naming "building or BPP value", the typed deductible-basis card, the agreed-value card shown once, both schedule cards, the EDIT PATH (nothing moved), answering the mod card |
| P2 | Auto 0, WC 0, Property 100, Umbrella 100, no physical-address warning, mod 0.92 printed on the 130 |
| P3 | Auto 0, WC 0, no schedule warnings, HNOA questions asked, vehicle / driver tables marked Not applicable, no X-Mod card |
| P5 | the split-limit hard stop, ceiling 60 with the reason, WC Supplemental -5, the physical-address warning |

## What round 1 found, and what changed

| Seen | Cause | Fix |
|---|---|---|
| P2 and P4: Operations 85 on clean accounts | each printed its governing class (4299 printing / 2003 bakeries - neither in the lookup table) beside clerical 8810, which IS in it, so only the standard exception voted and the account read "office" | a standard-exception class (8810 / 8742 / 8871 / 7380) does not vote **when a real class sits beside it**. A LONE 8810 still does - on a roofing contractor that is the mismatch you asked for |
| P1: Umbrella 40, not 25 | the sentence "schedule of underlying insurance was not supplied" was stored AS the schedule | a negation is an absence (Principle 3) |
| P5: Coverage Info -10 "no liability limit" and a CSL card | split limits leave the CSL box empty by design | split parts = the limit is stated |
| P5: Auto Completeness -10, not -15 | extraction inferred a use / radius / garaging the document never printed | rule 2c now forbids inference; v16 |
| P3: comp / collision deductible, physical-damage valuation and return-to-yard cards on an account with no vehicles | not in the HNOA-only N/A set | added |
| P1: vehicles and drivers asked twice (table + free text) | the coverage-guarantee injector did not know they are tables | schedule-backed facts are tables only |
| P1 could not show the payroll-period -3 | a class-code schedule with amounts satisfies the period (D43) once the extractor attributes the total to the rows | the period gap moved to P4, which prints codes without amounts |

## What to run now - three uploads, two of them short

* Every package is ONE PDF and its OWN session.
* Open **Total Package Score > Exposure Consistency**; hover a row for the arithmetic.
* "Facts panel" = the extracted-facts view; when a row disagrees, copy the fact named.

### R1 - `P2_everything_complete.pdf`   (re-run: the 8810 fix)
**Generate: 125 + 127 + 130** - three, not six. Property Integrity and Umbrella
Adequacy are PACKAGE pillars computed from the facts, so they read 100 whether or
not you generate the 140 and the 131; the 127 and the 130 are here only because
you are reading a box printed on them.

**Expect:** Exposure > **Operations 100** (was 85). Everything else exactly as
round 1: Auto Completeness 0, WC Supplemental 0, Property 100, Umbrella 100,
no physical-address warning.
**Agency bucket, corrected expectation:** cards such as "Experience mod" and
"Officer inclusions / exclusions" DO appear on this package - they are
"confirm this suggested value" cards (master plan 4.1 step 3: a producer
decision the documents state but no human has confirmed), not "missing"
cards. That is by design. What must NOT appear is a **WC payroll period**
card.
**Send back:** the Exposure pillar. Optionally page 1 of the 127 - RADIUS 50 on
rows A and B, and **exactly one** USE box ticked (Retail) on rows A and B, none on
row C. If you see two USE boxes ticked on any row, send that page: the seven boxes
are mutually exclusive and one is the only correct answer.

### R2 - `P4_new_venture.pdf`   (the steps you did not get to, plus the period gap)
**Generate:** 125 + 130

The bakery prints a bare "Payroll: $210,000" with no period wording, class
codes without amounts, and no mod anywhere.

**On upload**
- Exposure > **Operations 100** (round 1 read 85 - the 8810 fix).
- **WC Supplemental deducted 3** - the payroll period only (hover). The mod is
  UNKNOWN: asked, never deducted.
- Agency: an X-Mod card and a **WC payroll period / basis** card. (Round 1
  also showed a second EMOD question under "Experience mod detail" - both go
  away in step 2.)
- Loss History shows the **"confirm New Venture status"** card.

**Step 2 - confirm New Venture** on the Loss History card (answer Yes).
- Loss History becomes **Not Applicable**.
- **Both X-Mod cards disappear** from the Agency bucket. WC Supplemental stays
  at 3 until step 3.

**Step 3 - answer the period card:** pick *Annual*. -> WC Supplemental **0**.

**Step 4 - a re-run must keep the confirmation.** In the documents panel
change this document's type to any other type, then back.
- Loss History **still Not Applicable**, the X-Mod cards **still gone**.

**Send back:** the Exposure pillar on upload and after step 3; the Agency
bucket and Loss History state after each of steps 2 and 4.

### R3 - `P5_split_limits_partial_fleet_mod_indicated.pdf`   (the split-limit fix + your step 2)
**Generate:** 125 + 127 + 130

**On upload**
- Hard stop **"Split liability limits incomplete"**, ceiling 60 - as before.
- Exposure > **Coverage Info 100** (round 1 read 90: "no liability limit" on a
  split-limit policy).
- Exposure > **Auto Completeness 85** = 5 garaging + 5 radius + 5 use (round 1
  read 90). If it still reads 90, send the facts panel values of
  `auto_vehicle_use`, `auto_radius_of_operation`, `auto_garaging_addresses` -
  one of them was filled from text that does not print it.
- WC Supplemental 95 and the physical-address warning - as before.
- Agency: **no** "Auto liability limit - CSL" card (split limits are the limit).

**Step 2.** Open the split-limit hard stop: its Open-to-fix must show **three
typed fields** with BI per person and BI per accident pre-filled. Type
**$100,000** into PD per accident, save.
- The hard stop clears; the ceiling lifts to 85 (the address warning remains).

**Send back:** the Exposure pillar; the hard-stop card open before step 2;
the score before and after step 2.

### Optional - `P1_everything_missing.pdf`   (only if you want the umbrella row re-checked)
**Generate: 125 only** - the umbrella pillar is package-level. Expect **Umbrella 25** (round
1 read 40 because "was not supplied" counted as a schedule). Nothing else
changed for P1 and nothing else needs re-checking. P3 needs no re-run.

## What to send back overall

R1's Exposure pillar; R2's four captures; R3's three captures. One table,
PASS / DIFFERS per line. One failing line with its facts beats the rest
passing.
"""


if __name__ == "__main__":
    main()
