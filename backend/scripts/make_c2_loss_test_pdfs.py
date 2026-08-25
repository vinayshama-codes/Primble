"""make_c2_loss_test_pdfs.py - the live test packages for V1 item C2 (Loss History).

Generates FIVE separate scenario packages (upload each scenario's files as its
OWN session - they are different companies on purpose, so extraction caches and
identity matching can never bleed between scenarios):

    py backend/scripts/make_c2_loss_test_pdfs.py

Writes to test_data_c2_loss/ at the repo root, plus README-HOW-TO-TEST.md with
the numbered checks. REGENERATE BEFORE EVERY RUN - valuation/period dates are
computed from today so the recency bands stay in-band whenever you test.

Scenario -> the one C2 behaviour it proves live
    S1  Path B strong pin: matched runs, NO readable dates  -> pillar 60 (was 45)
    S2  Path A 3-4yr = 85 + freq/ratio ADVISORY only         -> pillar 85 (was 50)
    S3  2.6 contradiction: "no known losses" vs real claims  -> capped 45 + DC row
    S4  Path C nothing = 25 + New Venture flow               -> 25 -> N/A (rescale)
    S5  Pending = 50 (was 70)                                -> pillar 50

BRENT'S RULINGS 2026-08-24 (C2-E) - four more scenarios:
    S6  Loss run under a DECLARED DBA, tax ID matches        -> verified, 100
    S7  Tax ID matches, insured name is a former name        -> probable, 92
    S8  3-year-old business, no loss documents at all        -> 25 -> 85 attested
    S9  Loss runs but NO prior carrier named                 -> 90 -> 100 on "None"

Design notes (same rules as make_v1_c1_test_pdfs.py)
----------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave (the
  2026-08-22 fixture-defect lesson).
* S1 prints NO date anywhere and no year-like token - Path B exists only while
  claim years are unextractable. Self-verified below with a date-regex scan.
* No scenario except S3 contains any _NO_LOSS_PHRASES wording - also
  self-verified, because one stray "no claims" would silently change the path.
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
    "test_data_c2_loss",
)

TODAY = datetime.now()


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%m/%d/%Y")


def _future(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


# Proposed policy term shared by every scenario (starts just ahead of today so
# no expired-term / renewal-routing logic is tickled).
EFF = _future(8)
EXP = (TODAY + timedelta(days=8 + 365)).strftime("%m/%d/%Y")

# ── Layout helpers (proven in make_v1_c1_test_pdfs.py) ───────────────────────

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


def _para(c, y, text):
    c.setFont("Helvetica", 9)
    c.drawString(1 * inch, y, text)
    return y - 0.19 * inch


def _claim_table(c, y, rows, valued_label=None):
    """Standard claim-detail block. Kept in one place so every loss run carries
    the same classification signals (CLAIM NUMBER / DATE OF LOSS / Total
    Incurred), which is what `classify_document` scores on."""
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.15, 3.35, 5.15, 6.05, 6.85]
    for x, h in zip(cols, ["DATE OF LOSS", "CLAIM NUMBER", "DESCRIPTION",
                           "PAID", "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    total = 0
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        total += int(str(r[3]).replace("$", "").replace(",", ""))
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", f"${total:,}")
    y = _row(c, y, "Number of Claims", str(len(rows)))
    return y


def _dec_common(c, y, name, addr, fein, ops, revenue, payroll, employees,
                carrier, policy):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", revenue)
    y = _row(c, y, "Total Annual Payroll", payroll)
    y = _row(c, y, "Number of Employees", employees)
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    return y


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 1 - Cascade Plumbing: strong match, claim years NOT readable -> 60
# ═════════════════════════════════════════════════════════════════════════════
S1_NAME = "CASCADE PLUMBING SERVICES LLC"
S1_FEIN_DASHED = "45-3310886"
S1_FEIN_PLAIN = "453310886"          # loss run prints it unpunctuated (C1-proven)
S1_POL = "CPP-GLX-8842"              # letter-heavy: no year-like token anywhere
S1_CARRIER = "Granite State Mutual Insurance Company"


def s1_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations - New Business")
    _dec_common(c, y, S1_NAME, "2210 Alder Crossing, Tacoma, WA 98402",
                S1_FEIN_DASHED, "Residential and light commercial plumbing services",
                "$2,400,000", "$980,000", "11", S1_CARRIER, S1_POL)
    c.showPage()
    c.save()


def s1_loss_run(path):
    """The client's literal case: runs provably OURS (name + FEIN + policy),
    but every date is illegible - no valuation date, no period, no loss dates.
    Expected pillar: 60 PINNED (old system: 45 via the unknown-date -15)."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S1_CARRIER}")
    y = _row(c, y, "Insured", S1_NAME)
    y = _row(c, y, "FEIN", S1_FEIN_PLAIN)
    y = _row(c, y, "Policy Number", S1_POL)
    y = _para(c, y - 0.05 * inch,
              "Loss dates in the source report are illegible; amounts and "
              "statuses transcribed only.")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.4, 5.0, 5.9, 6.8]
    for x, h in zip(cols, ["CLAIM NUMBER", "DESCRIPTION", "PAID",
                           "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        ("CLM-88412", "Water line failure at customer residence",
         "$6,240", "$0", "Closed"),
        ("CLM-90177", "Slip incident at supply warehouse",
         "$11,900", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$18,140")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 2 - Bluewater Catering: 4 readable years -> 85; freq/ratio advisory
# ═════════════════════════════════════════════════════════════════════════════
S2_NAME = "BLUEWATER CATERING GROUP LLC"
S2_FEIN = "82-1147765"
S2_POL = "BWC-GLP-5521"
S2_CARRIER = "Lakeshore Standard Insurance Company"
S2_PRIOR = "Meridian Insurance Group"
S2_VAL = _d(10)                       # currently valued (<= 90 days)
S2_START = (TODAY - timedelta(days=10 + round(4 * 365.25))).strftime("%m/%d/%Y")


def s2_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations")
    y = _dec_common(c, y, S2_NAME, "515 Bayfront Avenue, Suite 3, Mobile, AL 36602",
                    S2_FEIN, "Off-premises catering and event food service",
                    "$1,000,000", "$620,000", "14", S2_CARRIER, S2_POL)
    y = _row(c, y, "Prior Carrier", S2_PRIOR)
    c.showPage()
    c.save()


def s2_loss_run(path):
    """4 readable years, currently valued, strong match, prior carrier named,
    HEAVY frequency (5 claims on $1M sales) and 15% loss ratio.
    Expected pillar: 85 EXACTLY - old system: 80 +10 carrier -25 freq -15 ratio = 50."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S2_PRIOR} - Valuation Date {S2_VAL}")
    y = _row(c, y, "Insured", S2_NAME)
    y = _row(c, y, "FEIN", S2_FEIN)
    y = _row(c, y, "Policy Number", S2_POL)
    y = _row(c, y, "Prior Carrier", S2_PRIOR)
    y = _row(c, y, "Period Covered", f"{S2_START} to {S2_VAL}  (4 years)")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.15, 3.35, 5.15, 6.05, 6.85]
    for x, h in zip(cols, ["DATE OF LOSS", "CLAIM NUMBER", "DESCRIPTION",
                           "PAID", "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        (_d(160), "BW-2201", "Guest illness alleged at event", "$18,000", "$0", "Closed"),
        (_d(420), "BW-2140", "Serving table collapse injury", "$42,500", "$12,000", "Open"),
        (_d(700), "BW-2071", "Delivery van struck fixed object", "$9,800", "$0", "Closed"),
        (_d(980), "BW-1988", "Burn injury to staff member", "$31,200", "$0", "Closed"),
        (_d(1300), "BW-1902", "Slip and fall at venue entrance", "$36,500", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$150,000")
    y = _row(c, y, "Number of Claims", "5")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 3 - Ironpeak Roofing: attestation vs real claims -> capped 45 + DC row
# ═════════════════════════════════════════════════════════════════════════════
S3_NAME = "IRONPEAK ROOFING LLC"
S3_FEIN = "47-9902213"
S3_POL = "IRP-GLR-3308"
S3_CARRIER = "Summit Ridge Insurance Company"
S3_VAL = _d(12)
S3_START = (TODAY - timedelta(days=12 + round(5 * 365.25))).strftime("%m/%d/%Y")


def s3_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S3_NAME, "77 Quarry Bend Road, Boise, ID 83702",
                    S3_FEIN, "Commercial roofing installation and repair",
                    "$3,600,000", "$1,450,000", "16", S3_CARRIER, S3_POL)
    y = _row(c, y, "Prior Carrier", "Summit Ridge Insurance Company")
    y = _head(c, y, "APPLICANT STATEMENT")
    y = _para(c, y, "The applicant reports no known losses.")
    c.showPage()
    c.save()


def s3_loss_run(path):
    """The runs contradict the statement above: 5 clean years would score 100,
    the contradiction must CAP at 45 and raise a Data Consistency card."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S3_CARRIER} - Valuation Date {S3_VAL}")
    y = _row(c, y, "Insured", S3_NAME)
    y = _row(c, y, "FEIN", S3_FEIN)
    y = _row(c, y, "Policy Number", S3_POL)
    y = _row(c, y, "Period Covered", f"{S3_START} to {S3_VAL}  (5 years)")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.15, 3.35, 5.15, 6.05, 6.85]
    for x, h in zip(cols, ["DATE OF LOSS", "CLAIM NUMBER", "DESCRIPTION",
                           "PAID", "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        (_d(430), "IR-7714", "Dropped material damaged parked vehicle",
         "$8,400", "$0", "Closed"),
        (_d(900), "IR-7583", "Water intrusion after re-roof",
         "$22,700", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$31,100")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 4 - Nova Kitchen Studio: nothing provided -> 25 -> New Venture flow
# ═════════════════════════════════════════════════════════════════════════════
S4_NAME = "NOVA KITCHEN STUDIO LLC"
S4_FEIN = "88-4406119"
S4_POL = "NKS-GLN-1102"
S4_CARRIER = "Beacon Harbor Insurance Company"


def s4_application(path):
    """ZERO loss-history information, no prior carrier, explicitly new business.
    The words 'loss' and 'claim' must not appear anywhere in this document -
    self-verified below."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section - New Business Submission")
    y = _dec_common(c, y, S4_NAME, "940 Larkspur Lane, Unit B, Madison, WI 53703",
                    S4_FEIN, "Custom kitchen design studio and showroom",
                    "$450,000", "$210,000", "4", S4_CARRIER, S4_POL)
    y = _row(c, y, "Transaction Type", "New Business")
    y = _row(c, y, "Business Start Date", _d(60))
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 5 - Harborline Electric: runs requested / pending -> 50 (was 70)
# ═════════════════════════════════════════════════════════════════════════════
S5_NAME = "HARBORLINE ELECTRIC LLC"
S5_FEIN = "61-2208843"
S5_POL = "HLE-GLE-7714"
S5_CARRIER = "Puget Crown Insurance Company"


def s5_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations")
    _dec_common(c, y, S5_NAME, "18 Ferry Slip Road, Bremerton, WA 98337",
                S5_FEIN, "Commercial electrical contracting",
                "$2,900,000", "$1,240,000", "13", S5_CARRIER, S5_POL)
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# BRENT'S RULINGS (C2-E) - S6 to S9
# ═════════════════════════════════════════════════════════════════════════════

# S6 - loss run under a DECLARED trade name, tax ID matches -> verified match
S6_NAME = "CASCADE FREIGHT INC"
S6_DBA = "CF Logistics"
S6_FEIN = "45-3310886"
S6_FEIN_PLAIN = "453310886"
S6_POL = "CFI-GLF-4417"
S6_CARRIER = "Granite State Mutual Insurance Company"
S6_PRIOR = "Northshore Indemnity Company"
S6_VAL = _d(14)
S6_START = (TODAY - timedelta(days=14 + round(5 * 365.25))).strftime("%m/%d/%Y")


def s6_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S6_NAME, "410 Harbor Industrial Way, Tacoma, WA 98421",
                    S6_FEIN, "Regional freight and drayage services",
                    "$5,100,000", "$2,050,000", "24", S6_CARRIER, S6_POL)
    y = _row(c, y, "DBA", S6_DBA)
    y = _row(c, y, "Prior Carrier", S6_PRIOR)
    y = _row(c, y, "Business Start Date", (TODAY - timedelta(days=round(8 * 365.25))).strftime("%m/%d/%Y"))
    c.showPage()
    c.save()


def s6_loss_run(path):
    """Issued to the TRADE NAME the applicant declared, with a matching tax ID.
    Brent: "Treat it as a verified match." Expect strong -> 5 readable years,
    currently valued, prior carrier named = 100."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S6_PRIOR} - Valuation Date {S6_VAL}")
    y = _row(c, y, "Insured", S6_DBA)
    y = _row(c, y, "FEIN", S6_FEIN_PLAIN)
    y = _row(c, y, "Policy Number", S6_POL)
    y = _row(c, y, "Period Covered", f"{S6_START} to {S6_VAL}  (5 years)")
    _claim_table(c, y, [
        (_d(300), "CF-4411", "Trailer door struck loading dock", "$5,600", "$0", "Closed"),
        (_d(880), "CF-4180", "Cargo water damage in transit", "$12,400", "$0", "Closed"),
    ])
    c.showPage()
    c.save()


# S7 - tax ID matches, insured name is a FORMER name -> probable match
S7_NAME = "MERIDIAN FABRICATION LLC"
S7_FORMER = "Northbridge Metalworks Corp"
S7_FEIN = "36-7742119"
S7_POL = "MFB-GLM-2290"
S7_CARRIER = "Lakeshore Standard Insurance Company"
S7_PRIOR = "Keystone Mutual Insurance Company"
S7_VAL = _d(20)
S7_START = (TODAY - timedelta(days=20 + round(5 * 365.25))).strftime("%m/%d/%Y")


def s7_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S7_NAME, "88 Foundry Street, Erie, PA 16507",
                    S7_FEIN, "Custom metal fabrication and welding",
                    "$4,400,000", "$1,760,000", "19", S7_CARRIER, S7_POL)
    y = _row(c, y, "Prior Carrier", S7_PRIOR)
    y = _row(c, y, "Business Start Date", (TODAY - timedelta(days=round(11 * 365.25))).strftime("%m/%d/%Y"))
    c.showPage()
    c.save()


def s7_loss_run(path):
    """The tax ID matches; the insured name on the run appears NOWHERE in the
    package (it is the company's former name). Brent: "a probable match ... ask
    for confirmation of the prior name or entity relationship."
    Expect moderate -> 100 base - 8 = 92, plus the confirmation note."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S7_PRIOR} - Valuation Date {S7_VAL}")
    y = _row(c, y, "Insured", S7_FORMER)
    y = _row(c, y, "FEIN", S7_FEIN)
    y = _row(c, y, "Policy Number", S7_POL)
    y = _row(c, y, "Period Covered", f"{S7_START} to {S7_VAL}  (5 years)")
    _claim_table(c, y, [
        (_d(520), "NB-8802", "Weld spatter ignited adjacent material", "$16,900", "$0", "Closed"),
    ])
    c.showPage()
    c.save()


# S8 - a 3-year-old business with no loss documents at all -> the ladder
S8_NAME = "ALDERGROVE DESIGN BUILD LLC"
S8_FEIN = "27-5518840"
S8_POL = "ADB-GLA-6620"
S8_CARRIER = "Beacon Harbor Insurance Company"


def s8_application(path):
    """Three years of operating history, zero loss information. Brent: at 1-5
    years "a satisfactory answer would be no known losses". Expect 25 before
    the questionnaire and 85 once the insured attests - where a 5+ year
    business would only reach 60. Carries no loss vocabulary at all."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S8_NAME, "1204 Cedar Mill Road, Bend, OR 97701",
                    S8_FEIN, "Residential design and build contracting",
                    "$1,300,000", "$540,000", "7", S8_CARRIER, S8_POL)
    y = _row(c, y, "Transaction Type", "New Business")
    y = _row(c, y, "Business Start Date",
             (TODAY - timedelta(days=round(3 * 365.25) + 40)).strftime("%m/%d/%Y"))
    c.showPage()
    c.save()


# S9 - loss runs present, NO prior carrier named anywhere -> "None" answer
S9_NAME = "PIONEER GLASSWORKS LLC"
S9_FEIN = "91-3320774"
S9_POL = "PGW-GLP-8830"
S9_CARRIER = "Summit Ridge Insurance Company"
S9_VAL = _d(16)
S9_START = (TODAY - timedelta(days=16 + round(5 * 365.25))).strftime("%m/%d/%Y")


def s9_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S9_NAME, "3300 Kiln Avenue, Toledo, OH 43604",
                    S9_FEIN, "Architectural glass fabrication and installation",
                    "$2,700,000", "$1,100,000", "15", S9_CARRIER, S9_POL)
    y = _row(c, y, "Business Start Date",
             (TODAY - timedelta(days=round(6 * 365.25))).strftime("%m/%d/%Y"))
    c.showPage()
    c.save()


def s9_loss_run(path):
    """Five readable years, strong match, but NO prior carrier stated anywhere
    in the package - so the -10 applies (loss runs prove coverage existed).
    Answering the prior-carrier card with "None" makes the applicant
    PREVIOUSLY UNINSURED, and Brent's ruling removes the deduction: 90 -> 100."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT", f"Valuation Date {S9_VAL}")
    y = _row(c, y, "Insured", S9_NAME)
    y = _row(c, y, "FEIN", S9_FEIN)
    y = _row(c, y, "Policy Number", S9_POL)
    y = _row(c, y, "Period Covered", f"{S9_START} to {S9_VAL}  (5 years)")
    _claim_table(c, y, [
        (_d(610), "PG-3301", "Glass panel dropped during install", "$7,300", "$0", "Closed"),
    ])
    c.showPage()
    c.save()


# S10 - a PROPERTY submission whose COPE is incomplete, so the hard stop and
# the carrier-grade warning both fire and their "Open to fix" modals can be
# checked. The loss scenarios carry no property coverage, so COPE never fires
# on them and the richest dropdowns (occupancy 17, construction 6, protection
# class 1-10, valuation, period of restoration) were untestable until now.
S10_NAME = "STILLWATER PROPERTIES LLC"
S10_FEIN = "26-8814402"
S10_POL = "SWP-PRP-9910"
S10_CARRIER = "Beacon Harbor Insurance Company"


def s10_property_dec(path):
    """Deliberately INCOMPLETE COPE: an address and a building value, but no
    occupancy, no construction type, no year built, no roof year, no sprinkler
    status, no protection class, no valuation method, and Business Income with
    no period of restoration. Every one of those is a dropdown now."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PROPERTY DECLARATIONS", "Policy Declarations")
    y = _row(c, y, "Named Insured", S10_NAME)
    y = _row(c, y, "Mailing Address", "1400 Millrace Road, Stillwater, MN 55082")
    y = _row(c, y, "FEIN", S10_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations", "Commercial property rental and management")
    y = _row(c, y, "Annual Gross Sales", "$1,850,000")
    y = _row(c, y, "Total Annual Payroll", "$430,000")
    y = _row(c, y, "Number of Employees", "6")
    y = _row(c, y, "Business Start Date",
             (TODAY - timedelta(days=round(12 * 365.25))).strftime("%m/%d/%Y"))

    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", S10_CARRIER)
    y = _row(c, y, "Policy Number", S10_POL)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _head(c, y, "SCHEDULED LOCATION 1")
    y = _row(c, y, "Location Address", "1400 Millrace Road, Stillwater, MN 55082")
    y = _row(c, y, "Building Limit", "$2,400,000")
    y = _row(c, y, "Business Personal Property Limit", "$310,000")
    y = _row(c, y, "Business Income Limit", "$500,000")
    y = _para(c, y - 0.05 * inch,
              "Construction, occupancy, protection and valuation details are "
              "not stated on this declarations page.")
    c.showPage()
    c.save()


def s5_cover_letter(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "SUBMISSION COVER LETTER",
              "Broker transmittal - supporting documentation status")
    y = _row(c, y, "Applicant", S5_NAME)
    y = _row(c, y, "FEIN", S5_FEIN)
    y = _para(c, y - 0.05 * inch,
              "Loss runs have been requested from the prior carrier, Atlantic "
              "Casualty Company, and are pending receipt.")
    y = _para(c, y,
              "They will be forwarded to the underwriter as soon as they arrive.")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# Self-verification - a fixture defect must fail HERE, not mid-live-run.
# ═════════════════════════════════════════════════════════════════════════════

_NO_LOSS_PHRASES = (
    "no prior losses", "no losses", "no prior claims", "no claims",
    "no known losses", "no known claims", "no reported losses",
    "no reported claims", "loss-free", "loss free", "claims-free",
    "claims free", "clean loss history", "favorable loss history",
    "clean loss record",
)
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _pdf_text(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(files: dict) -> None:
    errs = []
    t1 = _pdf_text(files["1B_loss_run_no_dates.pdf"]).lower()
    if _DATE_RE.search(t1):
        errs.append(f"S1 loss run contains a date: {_DATE_RE.search(t1).group(0)!r} "
                    "- Path B needs claim years unreadable")
    for fname in files:
        txt = _pdf_text(files[fname]).lower()
        hits = [p for p in _NO_LOSS_PHRASES if p in txt]
        if fname.startswith("3A"):
            if not hits:
                errs.append("S3 application lost its no-loss assertion")
        elif hits:
            errs.append(f"{fname} accidentally contains a no-loss phrase {hits} "
                        "- this silently changes the scoring path")
    for _blank in ("4A_application_only.pdf", "8A_application_3yr.pdf"):
        txt = _pdf_text(files[_blank]).lower()
        for word in ("loss", "claim"):
            if word in txt:
                errs.append(f"{_blank} mentions {word!r} - it must carry zero "
                            "loss-history signal")
    # S6's ruling only holds because the DBA is on the APPLICANT's own paper.
    if S6_DBA.lower() not in _pdf_text(files["6A_application_with_dba.pdf"]).lower():
        errs.append("S6 application no longer declares the DBA - the ruling it "
                    "tests requires the applicant to have declared it")
    # S7's former name must appear ONLY on the loss run.
    if S7_FORMER.lower() in _pdf_text(files["7A_application.pdf"]).lower():
        errs.append("S7 former name leaked into the application - it must be "
                    "unknown to the package for the ruling to apply")
    # S9 must name no prior carrier anywhere, or the "None" flow is untestable.
    for _f in ("9A_application.pdf", "9B_loss_run.pdf"):
        if "prior carrier" in _pdf_text(files[_f]).lower():
            errs.append(f"{_f} names a prior carrier - S9 requires none")
    t1_full = _pdf_text(files["1B_loss_run_no_dates.pdf"])
    for token in ("CLAIM NUMBER", "Total Incurred"):
        if token.lower() not in t1_full.lower():
            errs.append(f"S1 loss run missing {token!r} - may not classify as loss_run")
    if "pending" not in _pdf_text(files["5B_cover_letter.pdf"]).lower():
        errs.append("S5 letter lost its pending wording")
    if errs:
        raise SystemExit("FIXTURE SELF-CHECK FAILED:\n  - " + "\n  - ".join(errs))
    print("Self-check PASSED (dates/phrases/classification signals verified).")


README = """# C2 Loss History - live test packages (regenerated {today})

Five SEPARATE packages. Upload each scenario's file(s) as its OWN new session,
select **ACORD 125 only**, generate, then read the results in the review screen:

* **Loss History pillar + state**: right sidebar -> "Total Package Score" ->
  expand -> the **Loss History** row (number) and the state label under it.
  Click the label for the provenance card. "Matched on: ..." renders there too.
* **Cards**: the recommendations list (loss cards name their action).
* **Data Consistency / issues**: the validation & issues area (S3 only).
* **Client questionnaire**: the "Send to Client" question list (S1, S4).

Every number below was produced by running the REAL scorer against the fact
shape each package should extract to - not estimated.

| # | Upload | Expect | Previously |
|---|--------|--------|-----------------|
| S1 | 1A + 1B | Loss History **60**, state "Loss runs match insured", Matched on: name, fein, policy number. Card says pinned at 60 / confirm claim years. **NO prior-carrier card, NO valuation-date deduction.** ARQ does NOT ask "how many years of claims history can you provide" | 45 (unknown-date -15) |
| S2 | 2A + 2B | Loss History **85** exactly. TWO cards prefixed "Underwriting advisory (no score effect)" (frequency + loss ratio), each with NO points chip. State "Loss data reconciled" | 50 |
| S3 | 3A + 3B | Loss History **45** (capped), state "Conflicting". A conflict card AND, on the pre-form Review screen, a Data Consistency warning ("held at 45") | 45 cap; DC card added |
| S4 | 4A only | Loss History **25**, state "No loss information provided". Two cards: attestation + "confirm New Venture status" | no New Venture concept |
| S5 | 5A + 5B | Loss History **50**, state "Loss runs requested / pending" | 70 |
| **S6** | 6A + 6B | **100**, tier `strong`, **Matched on: dba_name, fein, policy number**. The run is issued to the trade name "CF Logistics" that the application itself declares | 25 (was `no_match`) |
| **S7** | 7A + 7B | **92**, tier `moderate`, note: *"tax ID matches ... Confirm the prior name or the entity relationship"*. The run's insured name appears nowhere else in the package | 25 (was `no_match`) |
| **S8** | 8A only | **25** at first. Answer the attestation "No - no claims or losses in the past 5 years" -> **85**, because the business is 3 years old. (A 5+ year business answering identically reaches only 60 - that is the ladder working) | 60 flat, no age awareness |
| **S9** | 9A + 9B | **90** with a "Prior carrier name missing" card. Answer that card with **None** -> **100**: the applicant is previously uninsured, not missing a carrier | 90, no way to clear it |
| **S10** | 10A only | Not a loss test - this one checks the **hard stop and warning** controls. Select **ACORD 140** as well as 125. Expect a "Minimum Viable COPE incomplete" HARD STOP and a "Carrier-Grade COPE incomplete" WARNING. Click **Open to fix** on each: occupancy, construction, sprinkler, protection class, valuation and period of restoration are now **dropdowns**; building value and year built stay typed inputs | every one was a bare text box |

S4's three answer flows (each on a FRESH session):
* **New Venture = Yes** -> pillar **N/A**, package rescales (loss AND umbrella
  both N/A), loss questions disappear from the client list.
* **"No - no claims or losses in the past 5 years"** -> pillar **N/A**, state
  *"Not applicable - under a year in business"*. **This is new**: S4's own
  application dates the business 60 days ago, so it falls in Brent's 0-1 year
  band - a business too young to have loss runs is no longer scored as if it
  withheld them. It scored 60 before his ruling.
* **"Yes - we have had claims or losses"** -> **25**, state "Prior claims known
  - runs not provided", and the client list gains the availability select
  ("Have loss runs been requested, or are any available to upload?").

What to send back per scenario: the Loss History pillar number, the state label,
the Matched-on line (S1/S2/S3), and which cards you saw. Screenshots beat prose.

Caveats
* Regenerate before every run (dates are relative to today) - the standing
  stale-fixture rule.
* S1 depends on the model NOT inventing claim years; if S1 shows a state of
  "Loss data reconciled" the model hallucinated dates - send the extracted
  facts and we adjust the fixture, not the code.
* S4 / S8 / S9 depend on `years_in_business` being derived from the printed
  business start date. If a score comes back on the wrong rung of the ladder,
  check that figure on the review screen FIRST - the band, not the scorer, is
  the likely culprit.
* S6 depends on the DBA being extracted from the application. If the tier
  comes back `no_match`, look at whether `dba_name` was captured before
  suspecting the ruling logic.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    plan = (
        ("1A_dec_page.pdf", s1_dec),
        ("1B_loss_run_no_dates.pdf", s1_loss_run),
        ("2A_dec_page.pdf", s2_dec),
        ("2B_loss_run_4yr.pdf", s2_loss_run),
        ("3A_application_no_loss_statement.pdf", s3_application),
        ("3B_loss_run_with_claims.pdf", s3_loss_run),
        ("4A_application_only.pdf", s4_application),
        ("5A_dec_page.pdf", s5_dec),
        ("5B_cover_letter.pdf", s5_cover_letter),
        ("6A_application_with_dba.pdf", s6_application),
        ("6B_loss_run_under_dba.pdf", s6_loss_run),
        ("7A_application.pdf", s7_application),
        ("7B_loss_run_former_name.pdf", s7_loss_run),
        ("8A_application_3yr.pdf", s8_application),
        ("9A_application.pdf", s9_application),
        ("9B_loss_run.pdf", s9_loss_run),
        ("10A_property_dec_incomplete_cope.pdf", s10_property_dec),
    )
    files = {}
    for name, fn in plan:
        path = os.path.join(OUT_DIR, name)
        fn(path)
        files[name] = path
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README.format(today=TODAY.strftime("%Y-%m-%d")))
    _verify(files)
    print(f"Wrote {len(files)} PDFs + README to {OUT_DIR}")
    for n in files:
        print(f"   {n:36s} {os.path.getsize(files[n]) / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
