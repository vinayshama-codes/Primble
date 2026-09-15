"""make_11sep_test_pdfs.py - live kit for the 11 Sep client audit (Orbin).

    py backend/scripts/make_11sep_test_pdfs.py

Writes 11sep_test_data/ at the repo root plus README-HOW-TO-TEST.md.

THREE files, TWO uploads. It cannot be fewer, and the reasons are structural:

  PACKAGE A   A1 + A2 uploaded TOGETHER
              A1 is the expiring declarations; A2 is the submission narrative.
              Item 4 needs an expiring-programme ROLE and a submission ROLE to
              disagree, and a file carries exactly one role - so two files is a
              floor, not a preference.

  PACKAGE B   B1 uploaded ALONE, second session, different insured
              The QUIET CONTROL. One carrier, per-line premiums present, no
              submission document. Everything on it must FILL. Its properties
              contradict A's, so it cannot be merged.

THE ROOT CAUSE IS ONE LINE OF THE DESIGN
----------------------------------------
Every coverage line on A1 states its carrier, NAIC, policy number and dates.
**No line states a premium** - the declarations print one package total, which
is exactly what the extraction prompt asks the model to produce ("Set premium to
null when only a package total is shown"). That single property is what
switched the whole per-line identity system off:

    ACORD 126 header, before / after
      BROKEN   Employers Mutual Casualty  /  25186  /  IM 7100 06 04
      FIXED    EMC Property & Casualty    /  25186  /  BBC7263 - 26

Same input either way. There is no premium column on A1's coverage table BY
DESIGN - a column reading "included in package total" would satisfy the grant
test and silently disarm the entire kit. `_verify` fails the build if one
appears.

WHAT EACH ADVERSARIAL VALUE IS FOR
----------------------------------
   1  four lines, TWO carriers, no per-line premium      THE root cause (item 1/3/5)
   2  EMC Property & Casualty vs Employers Mutual        a family key fuses them;
                                                          a strict key must not
   3  the GL carrier printed two ways                    entity folding must not
                                                          blank the box
   4  IM 7100 06 04 on the Inland Marine line            an AAIS FORM number must
                                                          never be a policy number
   5  BM 1234 05 21  (BOUNDARY PROBE)                    a REAL policy number in
                                                          ISO edition shape. This
                                                          one may legitimately
                                                          fail - see the README
   6  6E7-40-02---26 and 6E74002                         one contract, two
                                                          printings, must fold
   7  PROPERTY / CRIME / WC = NO COVERAGE                item 2
   8  the ISO endorsement "applies to" menu              item 2, the exact source
                                                          of Farm / Liquor / EPLI
                                                          / OCP
   9  GL classes 91580 / 91585, exposure $91,580         item 6, plus the H1-F
                                                          collision trap: an
                                                          EXPOSURE that equals a
                                                          CLASS CODE
  10  vehicle class 7383                                 item 6 negative control -
                                                          must SURVIVE
  11  Drive Other Car territory 6679                     KNOWN LIMIT: nothing
                                                          witnesses it, so no
                                                          guard can fire
  12  $2,000,000 + APPLIES PER POLICY/PROJECT/LOCATION   item 5, the checkbox
                                                          binding
  13  "Commercial Liability Umbrella Coverage Form"      item 5, poisons
      printed inside the GL block                         gl_form_type
  14  GL basis OCCURRENCE (A1) vs claims-made (A2)       item 10 NEGATIVE control:
                                                          two LEGAL values must
                                                          STILL conflict
  15  four good party names + two disclaimers            item 8, both directions
  16  Commercial Risk Solutions on every page header     item 4 - the 271-header
      vs ThinkSmith Agency once in the narrative          problem, in miniature
  17  Denver, CO                                         item 7 - ACORD 137 CO
  18  (B1) ONE carrier, premiums PRESENT, no narrative   the quiet control: the
                                                          borrow fallback, the old
                                                          priced path, and the
                                                          producer that must NOT
                                                          be wiped

DELIBERATELY NOT HERE
---------------------
  * two real policies on ONE line - it would blank the GL identity and destroy
    the headline check on the same form. Unit-tested + fuzzed.
  * a package with NO coverage_lines - cannot be forced reliably. 4 unit tests.
  * a code shared by two lines - the sub-key shapes are not guaranteed by the
    extraction schema, so the live check could be inert. Unit-tested.
  * GL spelling variants (CGL / Liability Coverage Part) - extraction may
    normalise the wording before the matcher sees it. 8 spellings pinned offline.
"""

from __future__ import annotations

import os
import sys

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "11sep_test_data")

# ── Package A ────────────────────────────────────────────────────────────────
A_INSURED = "HALVORSEN STRUCTURAL LLC"
A_ADDR = "1450 Wynkoop Street, Denver, CO 80202"
A_FEIN = "84-2210987"

CAR_GL = "EMC Property & Casualty"
CAR_GL_ALT = "EMC Property and Casualty Company"       # same entity, fuller name
CAR_PKG = "Employers Mutual Casualty"
NAIC_GL = "25186"
NAIC_PKG = "21415"

POL_GL = "BBC7263 - 26"
POL_AUTO = "6E7-40-02---26"
POL_AUTO_SHORT = "6E74002"                             # same contract, no tail
POL_IM = "6C7-40-02---26"
POL_UMB = "6J7-40-02---26"
POL_BM_PROBE = "BM 1234 05 21"                         # boundary probe
FORM_NUMBER = "IM 7100 06 04"                          # AAIS Installation Floater

AGENCY_OLD = "Commercial Risk Solutions"
AGENT_OLD = "Terri Wroblewski"
AGENCY_NEW = "ThinkSmith Agency"
AGENT_NEW = "Michelle Smith"

GL_CLASS_A = "91580"
GL_CLASS_B = "91585"
GL_EXPOSURE_COLLIDES = "$91,580"                       # equals the class code
AUTO_CLASS = "7383"
DOC_TERRITORY = "6679"

VEH_YEAR, VEH_MAKE, VEH_MODEL = "2012", "Subaru", "Outback"
VEH_VIN = "4S4BRCGC9C3217772"

PARTY_GOOD = [
    ("Wells Fargo Equipment Finance, Inc.", "Loss Payee",
     "800 Walnut Street, Des Moines, IA 50309"),
    ("Kestrel Terminal Authority", "Additional Insured",
     "1201 Port of Tacoma Rd, Tacoma, WA 98421"),
    ("John A. Smith", "Mortgagee", "77 Larimer Street, Denver, CO 80202"),
    ("City of Aurora", "Additional Insured", "15151 E Alameda Pkwy, Aurora, CO 80012"),
]
PARTY_BAD = [
    ("For Informational Purposes Only", "Certificate Holder", ""),
    ("As Their Interests May Appear", "Loss Payee", ""),
]

ISO_MENU = [
    "THIS ENDORSEMENT MODIFIES INSURANCE PROVIDED UNDER THE FOLLOWING:",
    "   COMMERCIAL PROPERTY COVERAGE PART",
    "   COMMERCIAL CRIME AND FIDELITY COVERAGE PART",
    "   COMMERCIAL GENERAL LIABILITY COVERAGE PART",
    "   COMMERCIAL INLAND MARINE COVERAGE PART",
    "   FARM COVERAGE PART",
    "   LIQUOR LIABILITY COVERAGE PART",
    "   EMPLOYMENT-RELATED PRACTICES LIABILITY COVERAGE PART",
    "   OWNERS AND CONTRACTORS PROTECTIVE LIABILITY COVERAGE PART",
    "   EQUIPMENT BREAKDOWN PROTECTION COVERAGE PART",
]

# ── Package B (the quiet control) ────────────────────────────────────────────
B_INSURED = "MERIDIAN FABRICATION INC"
B_ADDR = "900 Pearl Street, Boulder, CO 80302"
B_CARRIER = "Great Plains Casualty Company"
B_NAIC = "34521"
B_AGENCY = "Cascade Risk Partners"
B_AGENT = "Dana Whitfield"
B_POL_GL = "GPC-GL-55210"
B_POL_AUTO = "GPC-BA-55211"
B_POL_PROP = "GPC-CP-55212"
B_PARTY = "Boulder Valley Bank"


# ── Layout helpers ──────────────────────────────────────────────────────────

def _page(c, title, subtitle="", header=""):
    if header:
        c.setFont("Helvetica", 8)
        c.drawString(1 * inch, 10.55 * inch, header)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _next(c, title, subtitle="", header=""):
    c.showPage()
    return _page(c, title, subtitle, header)


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


def _para(c, y, text, size=9):
    c.setFont("Helvetica", size)
    c.drawString(1 * inch, y, text)
    return y - 0.19 * inch


def _table(c, y, headers, rows, cols):
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in zip(cols, headers):
        c.drawString(x * inch, y, h)
    y -= 0.06 * inch
    c.setLineWidth(0.4)
    c.line(1 * inch, y, 7.5 * inch, y)
    y -= 0.16 * inch
    c.setFont("Helvetica", 8.5)
    for r in rows:
        for x, cell in zip(cols, r):
            c.drawString(x * inch, y, str(cell))
        y -= 0.185 * inch
    return y - 0.06 * inch


# ── A1 - the expiring declarations ──────────────────────────────────────────

def build_a1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    hdr = f"AGENT: {AGENCY_OLD}   |   {AGENT_OLD}   |   (303) 555-0110"

    # ---- page 1: the common declarations ----------------------------------
    y = _page(c, "COMMERCIAL POLICY DECLARATIONS",
              "Common Policy Declarations - Renewal of BBC7263 - 25", hdr)
    y = _row(c, y, "NAMED INSURED", A_INSURED)
    y = _row(c, y, "MAILING ADDRESS", A_ADDR)
    y = _row(c, y, "FEIN", A_FEIN)
    y = _row(c, y, "POLICY PERIOD", "07/15/2026 to 07/15/2027 at 12:01 A.M.")
    y = _row(c, y, "BUSINESS DESCRIPTION", "Structural steel erection contractor")
    y = _row(c, y, "FORM OF BUSINESS", "Limited Liability Company")
    y -= 0.10 * inch

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS")
    # NO PREMIUM COLUMN. See the module docstring - this is the whole kit.
    y = _table(
        c, y,
        ["COVERAGE PART", "INSURER", "NAIC", "POLICY NUMBER", "STATUS"],
        [["General Liability", CAR_GL, NAIC_GL, POL_GL, "Covered"],
         ["Business Auto", CAR_PKG, NAIC_PKG, POL_AUTO, "Covered"],
         ["Inland Marine", CAR_PKG, NAIC_PKG, POL_IM, "Covered"],
         ["Commercial Liability Umbrella", CAR_PKG, NAIC_PKG, POL_UMB, "Covered"],
         ["Boiler and Machinery", CAR_PKG, NAIC_PKG, POL_BM_PROBE, "Covered"],
         ["Commercial Property", "", "", "", "NO COVERAGE"],
         ["Crime and Fidelity", "", "", "", "NO COVERAGE"],
         ["Workers Compensation", "", "", "", "NO COVERAGE"]],
        # MEASURED with reportlab stringWidth, not guessed. The widest label is
        # "Commercial Liability Umbrella" (1.56in), and the first cut at 2.5
        # welded it to the carrier - "...UmbrellaEmployers Mutual Casualty" -
        # on the one row the umbrella identity check depends on.
        [1.0, 2.7, 4.25, 4.75, 6.55])

    y = _head(c, y, "PREMIUM SUMMARY")
    y = _para(c, y, "A single package premium is charged for this policy. Individual")
    y = _para(c, y, "coverage parts are not separately rated on these declarations.")
    y = _row(c, y, "TOTAL POLICY PREMIUM", "$19,554")
    y = _row(c, y, "BILLING", "Direct Bill - Annual")

    y = _head(c, y, "FORMS AND ENDORSEMENTS ATTACHED")
    y = _para(c, y, f"Installation Floater Coverage Form .......... {FORM_NUMBER}")
    y = _para(c, y, "Commercial Liability Umbrella Coverage Form .. CU 00 01 04 13")
    y = _para(c, y, "Common Policy Conditions .................... IL 00 17 11 98")

    # ---- page 2: the GL coverage part -------------------------------------
    y = _next(c, "GENERAL LIABILITY COVERAGE PART DECLARATIONS",
              f"Issued by {CAR_GL_ALT}", hdr)
    y = _row(c, y, "INSURER", CAR_GL_ALT)
    y = _row(c, y, "NAIC CODE", NAIC_GL)
    y = _row(c, y, "POLICY NUMBER", POL_GL)
    y = _row(c, y, "COVERAGE BASIS", "OCCURRENCE")
    y -= 0.08 * inch

    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _table(c, y, ["COVERAGE", "LIMIT"],
               [["Each Occurrence", "$1,000,000"],
                ["General Aggregate", "$2,000,000"],
                ["Products/Completed Operations Aggregate", "$2,000,000"],
                ["Personal & Advertising Injury", "$1,000,000"],
                ["Damage To Premises Rented To You", "$100,000"],
                ["Medical Expense (any one person)", "$10,000"]],
               [1.0, 5.2])
    y = _para(c, y, "GENERAL AGGREGATE LIMIT APPLIES PER:  [ ] POLICY   [ ] PROJECT   "
                    "[ ] LOCATION")
    y = _row(c, y, "DEDUCTIBLE", "$1,000 per occurrence - Bodily Injury and Property Damage")
    y -= 0.08 * inch

    y = _head(c, y, "SCHEDULE OF HAZARDS - CLASSIFICATION AND PREMIUM BASIS")
    y = _table(c, y,
               ["LOC", "HAZ", "CLASS CODE", "CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
               [["1", "1", GL_CLASS_A,
                 "Contractors - subcontracted work", "Cost", GL_EXPOSURE_COLLIDES],
                ["1", "2", GL_CLASS_B,
                 "Contractors - executive supervisors", "Payroll", "$350,000"]],
               [1.0, 1.5, 2.1, 3.0, 5.4, 6.6])
    y = _para(c, y, "Coverage is excess over any Commercial Liability Umbrella Coverage Form")
    y = _para(c, y, "issued to the named insured for the same occurrence.")

    # ---- page 3: auto + umbrella ------------------------------------------
    y = _next(c, "BUSINESS AUTO COVERAGE PART DECLARATIONS",
              f"Issued by {CAR_PKG}", hdr)
    y = _row(c, y, "INSURER", CAR_PKG)
    y = _row(c, y, "NAIC CODE", NAIC_PKG)
    y = _row(c, y, "POLICY NUMBER", POL_AUTO)
    y = _row(c, y, "COVERED AUTOS LIABILITY", "Symbol 01 - Any Auto")
    y = _row(c, y, "LIABILITY LIMIT", "$1,000,000 Combined Single Limit")
    y = _row(c, y, "MEDICAL PAYMENTS", "$5,000")
    y = _row(c, y, "UNINSURED / UNDERINSURED MOTORIST", "$1,000,000")
    y = _row(c, y, "COMPREHENSIVE / COLLISION DEDUCTIBLE", "$1,000 / $1,000")
    y -= 0.08 * inch

    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y,
               ["NO", "YEAR", "MAKE", "MODEL", "VIN", "CLASS", "COST NEW", "GARAGED"],
               [["1", VEH_YEAR, VEH_MAKE, VEH_MODEL, VEH_VIN, AUTO_CLASS,
                 "$28,000", "Denver, CO"]],
               [1.0, 1.35, 1.9, 2.6, 3.4, 5.3, 5.9, 6.7])

    y = _head(c, y, "SCHEDULE OF DRIVERS")
    y = _table(c, y, ["NAME", "LICENSE NO", "STATE", "DATE OF BIRTH", "HIRE DATE"],
               [["Erin Royal", "CO-1234567", "CO", "04/02/1985", "03/11/2019"]],
               [1.0, 3.0, 4.3, 5.0, 6.3])

    y = _head(c, y, "CA 99 10 - DRIVE OTHER CAR COVERAGE - NAMES OF INDIVIDUALS")
    y = _table(c, y, ["NAMED INDIVIDUAL", "TERRITORY", "CLASS"],
               [["Erin Royal", DOC_TERRITORY, "8810"]],
               [1.0, 3.4, 4.8])

    y = _head(c, y, "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS")
    y = _row(c, y, "INSURER", CAR_PKG)
    y = _row(c, y, "POLICY NUMBER", POL_UMB)
    y = _row(c, y, "EACH OCCURRENCE LIMIT", "$3,000,000")
    y = _row(c, y, "SELF-INSURED RETENTION", "$0")
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, ["LINE", "INSURER", "POLICY NUMBER", "LIMIT"],
               [["General Liability", CAR_GL, POL_GL, "$1,000,000"],
                ["Business Auto", CAR_PKG, POL_AUTO_SHORT, "$1,000,000"]],
               [1.0, 2.4, 4.6, 6.4])

    # ---- page 4: interests + the ISO menu ---------------------------------
    y = _next(c, "SCHEDULE OF ADDITIONAL INTERESTS", "", hdr)
    rows = [[n, r, a] for n, r, a in PARTY_GOOD] + [[n, r, a] for n, r, a in PARTY_BAD]
    y = _table(c, y, ["NAME OR ORGANIZATION", "INTEREST", "ADDRESS"],
               rows, [1.0, 3.7, 5.0])
    y = _para(c, y, "Interests shown above are included as their interest may appear.")

    y = _head(c, y, "INLAND MARINE COVERAGE PART")
    y = _row(c, y, "INSURER", CAR_PKG)
    y = _row(c, y, "POLICY NUMBER", POL_IM)
    y = _row(c, y, "COVERAGE FORM", f"Installation Floater {FORM_NUMBER}")
    y = _row(c, y, "LIMIT", "$150,000 any one installation")

    y = _head(c, y, "COMMON POLICY CONDITIONS - IL 00 17 11 98")
    for line in ISO_MENU:
        y = _para(c, y, line, size=8.5)
    y = _para(c, y, "The listing above identifies the coverage parts to which this", size=8.5)
    y = _para(c, y, "endorsement may apply. It does not itself grant coverage.", size=8.5)
    c.save()


# ── A2 - the submission narrative ───────────────────────────────────────────

def build_a2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "UNDERWRITING NARRATIVE",
              "Submission Summary - Account Overview")
    y = _row(c, y, "APPLICANT", A_INSURED)
    y = _row(c, y, "LOCATION", A_ADDR)
    y = _row(c, y, "PRODUCER", AGENCY_NEW)
    y = _row(c, y, "PRODUCER CONTACT", AGENT_NEW)
    y = _row(c, y, "PRODUCER PHONE", "(303) 555-0142")
    y = _row(c, y, "PRODUCER EMAIL", "michelle.smith@thinksmith.example")
    y = _row(c, y, "EFFECTIVE", "07/15/2026")
    y -= 0.12 * inch

    y = _head(c, y, "ACCOUNT OVERVIEW")
    for line in [
        f"{A_INSURED} is a structural steel erection contractor operating from a",
        "single Denver location. The account is being re-marketed for the 07/15/2026",
        f"term. The expiring programme is placed through {AGENCY_OLD};",
        f"{AGENCY_NEW} is the submitting producer for this renewal.",
        "",
        "Coverage requested: General Liability, Business Auto, Inland Marine and a",
        "Commercial Liability Umbrella. The applicant carries no property, crime or",
        "workers compensation coverage under this programme.",
        "",
        "The General Liability coverage part is written on a claims-made basis.",
        "",
        "One vehicle is scheduled - a 2012 Subaru Outback - garaged at the Denver",
        "premises and used for supervisor travel between job sites.",
    ]:
        y = _para(c, y, line)

    y = _head(c, y, "LOSS SUMMARY")
    y = _para(c, y, "No known losses in the past five years.")
    c.save()


# ── B1 - the quiet control ──────────────────────────────────────────────────

def build_b1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    hdr = f"AGENT: {B_AGENCY}   |   {B_AGENT}   |   (720) 555-0188"
    y = _page(c, "COMMERCIAL POLICY DECLARATIONS",
              "Common Policy Declarations", hdr)
    y = _row(c, y, "NAMED INSURED", B_INSURED)
    y = _row(c, y, "MAILING ADDRESS", B_ADDR)
    y = _row(c, y, "FEIN", "47-1180022")
    y = _row(c, y, "POLICY PERIOD", "09/01/2026 to 09/01/2027")
    y = _row(c, y, "BUSINESS DESCRIPTION", "Metal fabrication shop")
    y = _row(c, y, "FORM OF BUSINESS", "Corporation")
    y -= 0.10 * inch

    # ONE carrier, and every line PRICED - the old path, unchanged.
    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS")
    y = _table(c, y,
               ["COVERAGE PART", "INSURER", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", B_CARRIER, B_NAIC, B_POL_GL, "$8,400"],
                ["Business Auto", B_CARRIER, B_NAIC, B_POL_AUTO, "$3,150"],
                ["Commercial Property", B_CARRIER, B_NAIC, B_POL_PROP, "$5,900"]],
               [1.0, 2.4, 4.3, 4.9, 6.6])
    y = _row(c, y, "TOTAL POLICY PREMIUM", "$17,450")

    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _table(c, y, ["COVERAGE", "LIMIT"],
               [["Each Occurrence", "$1,000,000"],
                ["General Aggregate", "$2,000,000"]], [1.0, 5.2])
    y = _row(c, y, "COVERAGE BASIS", "OCCURRENCE")

    y = _head(c, y, "BUSINESS AUTO")
    y = _row(c, y, "COVERED AUTOS LIABILITY", "Symbol 07 - Specifically Described Autos")
    y = _row(c, y, "LIABILITY LIMIT", "$1,000,000 Combined Single Limit")
    y = _table(c, y, ["NO", "YEAR", "MAKE", "MODEL", "VIN", "CLASS"],
               [["1", "2019", "Ford", "F-250", "1FT7W2BT5KEC12345", "7398"]],
               [1.0, 1.35, 1.9, 2.7, 3.6, 5.6])

    y = _head(c, y, "COMMERCIAL PROPERTY")
    y = _row(c, y, "BUILDING LIMIT", "$1,250,000")
    y = _row(c, y, "BUSINESS PERSONAL PROPERTY", "$400,000")
    y = _row(c, y, "YEAR BUILT", "1998")
    y = _row(c, y, "CONSTRUCTION", "Joisted Masonry")

    y = _head(c, y, "ADDITIONAL INTERESTS")
    y = _table(c, y, ["NAME OR ORGANIZATION", "INTEREST", "ADDRESS"],
               [[B_PARTY, "Mortgagee", "1600 Broadway, Boulder, CO 80302"]],
               [1.0, 3.7, 5.0])
    c.save()


# ── Self-check: the kit must be able to fail the build ──────────────────────

def _text(path):
    try:
        import pdfplumber
    except Exception:                                         # noqa: BLE001
        return None
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(a1_path, a2_path, b1_path):
    a1, a2, b1 = (_text(p) for p in (a1_path, a2_path, b1_path))
    if a1 is None:
        print("  ! pdfplumber unavailable - self-check skipped")
        return True
    problems = []

    def need(hay, val, where):
        if val not in hay:
            problems.append(f"{where}: MISSING {val!r}")

    def forbid(hay, val, where):
        if val in hay:
            problems.append(f"{where}: must NOT contain {val!r}")

    # A1 - identity evidence on every line, and the values under test.
    for v in (CAR_GL, CAR_GL_ALT, CAR_PKG, NAIC_GL, NAIC_PKG, POL_GL, POL_AUTO,
              POL_IM, POL_UMB, POL_BM_PROBE, POL_AUTO_SHORT, FORM_NUMBER,
              GL_CLASS_A, GL_CLASS_B, GL_EXPOSURE_COLLIDES, AUTO_CLASS,
              DOC_TERRITORY, VEH_VIN, AGENCY_OLD, AGENT_OLD, "NO COVERAGE",
              "$2,000,000", "APPLIES PER", "OCCURRENCE", "Denver, CO",
              "Commercial Liability Umbrella Coverage Form"):
        need(a1, v, "A1")
    for name, _role, _addr in PARTY_GOOD + PARTY_BAD:
        need(a1, name, "A1")
    for line in ISO_MENU[1:]:
        need(a1, line.strip(), "A1")

    # THE CONTRACT THIS WHOLE KIT RESTS ON. A premium against any coverage line
    # satisfies the grant test and silently disarms every item-1/3/5 check.
    if "PREMIUM" in a1.split("SCHEDULE OF COVERAGE PARTS")[-1].split(
            "PREMIUM SUMMARY")[0]:
        problems.append(
            "A1: the SCHEDULE OF COVERAGE PARTS carries a premium column - the "
            "root-cause trigger is disarmed and the kit proves nothing")
    for v in ("Included in package", "included in package"):
        forbid(a1, v, "A1")
    # A1 must not read as a certificate or the producer role test inverts.
    for v in ("CERTIFICATE OF LIABILITY INSURANCE", "THIS IS TO CERTIFY"):
        forbid(a1, v, "A1")
    # The new agency must appear ONLY in the narrative.
    forbid(a1, AGENCY_NEW, "A1")

    # A2 - the submitting producer and the legal rival value.
    for v in (AGENCY_NEW, AGENT_NEW, "claims-made", "UNDERWRITING NARRATIVE"):
        need(a2, v, "A2")
    need(a2, AGENCY_OLD, "A2")            # named as the EXPIRING producer, in prose
    for v in ("DECLARATIONS", "Declarations"):
        forbid(a2, v, "A2")               # would flip the role to dec_page

    # B1 - one carrier, priced lines, no submission document.
    for v in (B_CARRIER, B_NAIC, B_POL_GL, B_POL_AUTO, B_POL_PROP, B_AGENCY,
              B_PARTY, "$8,400"):
        need(b1, v, "B1")
    for v in (CAR_GL, CAR_PKG, AGENCY_NEW, AGENCY_OLD, A_INSURED):
        forbid(b1, v, "B1")               # no bleed between packages
    if b1.count(B_CARRIER) < 3:
        problems.append("B1: the single carrier must appear on all three lines")

    # The roles must actually classify, or three checks are inert.
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from services.extraction_service import classify_document
        for label, text, want, fname in (
                ("A1", a1, "dec_page", "expiring_dec.pdf"),
                ("A2", a2, "narrative", "underwriting_narrative.pdf"),
                ("B1", b1, "dec_page", "control_dec.pdf")):
            got = classify_document(text, fname).get("doc_type")
            if got != want:
                problems.append(
                    f"{label}: classifies as {got!r}, needs {want!r} - the "
                    f"producer-role check would be inert")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  ! role self-check skipped ({exc})")

    # No two table cells may touch. A fused cell hands the model ONE token where
    # the document prints two, and the row under test silently stops testing it.
    # The first cut printed "Commercial Liability UmbrellaEmployers Mutual
    # Casualty" - the umbrella's line name welded to its carrier, on the one row
    # the umbrella identity check depends on. Column starts are now measured
    # with reportlab `stringWidth`, and this catches the next one.
    for fused in ("UmbrellaEmployers", "CasualtyBBC", "MarineEmployers",
                  "LiabilityEMC", "MachineryEmployers", "PropertyNO",
                  "FidelityNO", "CompensationNO"):
        forbid(a1, fused, "A1 (column collision)")

    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("   -", p)
        return False
    print("  self-check passed (content, contracts and document roles)")
    return True


# ── README ──────────────────────────────────────────────────────────────────

README = f"""# 11 Sep kit - how to test

Two uploads. **Do not merge them.**

| Upload | Files | Insured |
|---|---|---|
| **A** | `expiring_dec.pdf` + `underwriting_narrative.pdf` together | {A_INSURED} |
| **B** | `control_dec.pdf` alone, a SECOND session | {B_INSURED} |

Generate forms for **ACORD 125, 126, 127, 131** on both.

---

## THE HEADLINE CHECK

Open **ACORD 126** from upload A and read three boxes.

```
  BROKEN   Employers Mutual Casualty  /  25186  /  IM 7100 06 04
  FIXED    EMC Property & Casualty    /  25186  /  BBC7263 - 26
```

No coverage line on that dec page states a premium - that single property is
what used to switch the whole per-line system off. If those three boxes are
right, the root cause is fixed.

---

## UPLOAD A - 31 checks

### Identity (items 1, 3, 5)

| # | Where | Expect |
|---|---|---|
| 1 | ACORD 126 header | INSURER `{CAR_GL}` or `{CAR_GL_ALT}` |
| 2 | ACORD 126 header | NAIC `{NAIC_GL}` |
| 3 | ACORD 126 header | POLICY NUMBER `{POL_GL}` |
| 4 | ACORD 126 header | EFFECTIVE `07/15/2026`, EXPIRATION `07/15/2027` |
| 5 | ACORD 127 header | `{CAR_PKG}` / `{NAIC_PKG}` / `{POL_AUTO}` |
| 6 | ACORD 131 header | `{CAR_PKG}` / `{NAIC_PKG}` / `{POL_UMB}` |
| 7 | any form | `{NAIC_GL}` NEVER printed beside `{CAR_PKG}` |
| 8 | ACORD 125 policy-number box | blank (5 policies - the package has no single number) |
| 9 | anywhere | `{FORM_NUMBER}` NEVER appears in a policy-number box |
| 10 | ACORD 125 Q4 grid | each line paired with its OWN number; `{POL_AUTO}` and `{POL_AUTO_SHORT}` counted as ONE policy |
| 11 | Data Consistency | NO "multiple policy numbers" / "which carrier" card. 5 policies is what a package IS |

### Phantom coverage (item 2)

| # | Where | Expect |
|---|---|---|
| 12 | cover page | Lines of Business lists ONLY General Liability, Business Auto, Inland Marine, Umbrella |
| 13 | cover page | **NOT** Farm, Liquor, Employment-Related Practices, Owners and Contractors Protective, Equipment Breakdown |
| 14 | cover page | **NOT** Property, Crime, Workers Compensation (dec says NO COVERAGE) |
| 15 | ACORD 125 LOB boxes | same four ticked, nothing else |
| 16 | recommendations | no WC / property / crime forms pushed |

### Producer (item 4)

| # | Where | Expect |
|---|---|---|
| 17 | ACORD 125 Producer block | `{AGENCY_NEW}` / `{AGENT_NEW}` |
| 18 | ACORD 125 Producer block | **NOT** `{AGENCY_OLD}` / `{AGENT_OLD}` |
| 19 | Data Consistency | no producer conflict card |

### Type (items 5, 10)

| # | Where | Expect |
|---|---|---|
| 20 | ACORD 126 | GENERAL AGGREGATE `$2,000,000` in the AMOUNT box |
| 21 | ACORD 126 | the three "applies per POLICY / PROJECT / LOCATION" ticks are NOT driven by that amount |
| 22 | Data Consistency | **NO** card comparing a limit with a Yes/No box, and none comparing Claims Made with `Commercial Liability Umbrella Coverage Form` |
| 23 | Data Consistency | **A card MUST appear** for GL form type: `OCCURRENCE` (dec) vs `claims-made` (narrative). **If this is missing the filter over-reached - that is a failure, not a pass.** |

### Cross-line codes (item 6)

| # | Where | Expect |
|---|---|---|
| 24 | ACORD 127 vehicle row | CLASS is `{AUTO_CLASS}` or blank - **never** `{GL_CLASS_A}` / `{GL_CLASS_B}` |
| 25 | ACORD 127 vehicle row | no `$91,580` or `$350,000` in a vehicle cost/value box |
| 26 | ACORD 126 hazard grid | class codes `{GL_CLASS_A}` / `{GL_CLASS_B}` present and correct |
| 27 | ACORD 126 hazard grid | never `{AUTO_CLASS}` |
| 28 | ACORD 127 | territory `{DOC_TERRITORY}` - **KNOWN LIMIT, PRE-MEASURED.** No schedule fact captures a Drive Other Car territory, so there is no witness and the guard cannot fire. If `{DOC_TERRITORY}` prints in a territory box, that is the documented gap, not a regression. Record it |

### Parties (item 8)

| # | Where | Expect |
|---|---|---|
| 29 | any Additional Interest / Loss Payee box | `Wells Fargo Equipment Finance, Inc.`, `Kestrel Terminal Authority`, `John A. Smith`, `City of Aurora` all allowed |
| 30 | any party box | `For Informational Purposes Only` and `As Their Interests May Appear` NEVER appear |

### Everything else

| # | Where | Expect |
|---|---|---|
| 31 | form recommendations | `ACORD 137 CO` offered (Needs Confirmation). Item 7 - it is a tier decision, not a bug |
| 32 | client questionnaire | the Subaru is NOT asked for again; no numbered "(Nth vehicle)" cards; no driver beyond the one on the dec |

### BOUNDARY PROBE - record the result, it may legitimately fail

| # | Where | Expect |
|---|---|---|
| 33 | ACORD 125 Q4 grid / Boiler and Machinery | `{POL_BM_PROBE}` is a REAL policy number in ISO edition shape. **PRE-MEASURED: it WILL be blanked** - `_looks_like_a_form_number` cannot tell it from `IM 7100 06 04`. This is the safe direction (blank over wrong), not a correctness failure, and it is here to size the cost. Confirm the blank and note whether any real carrier in Brent's book numbers policies this way |

---

## UPLOAD B - the quiet control, 5 checks

Its job is to fail loudly if a guard is too aggressive. **Everything must fill.**

| # | Where | Expect |
|---|---|---|
| 34 | ACORD 126 / 127 headers | `{B_CARRIER}` / `{B_NAIC}` - one carrier, borrowed correctly for every line |
| 35 | ACORD 126 / 127 headers | the right policy number per line (`{B_POL_GL}`, `{B_POL_AUTO}`) |
| 36 | ACORD 125 Producer block | `{B_AGENCY}` - **must NOT be wiped.** No submission document names a producer, and an incumbent broker is allowed to be both |
| 37 | cover page | Lines of Business lists General Liability, Business Auto, Commercial Property - the priced path, unchanged |
| 38 | any party box | `{B_PARTY}` fills |

**If B comes back with blanks, A's passes were luck.**

---

## What to send back

For each numbered check: PASS / FAIL / not-seen, and for any FAIL the literal
value that printed. Screenshots of ACORD 125 page 1, ACORD 126 page 1, ACORD 127
page 1, the cover page and the Data Consistency panel cover most of it.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    a1 = os.path.join(OUT_DIR, "expiring_dec.pdf")
    a2 = os.path.join(OUT_DIR, "underwriting_narrative.pdf")
    b1 = os.path.join(OUT_DIR, "control_dec.pdf")
    build_a1(a1)
    build_a2(a2)
    build_b1(b1)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)
    print(f"wrote {OUT_DIR}")
    for p in (a1, a2, b1):
        print(f"   {os.path.basename(p):32s} {os.path.getsize(p):>7,} bytes")
    print("   README-HOW-TO-TEST.md")
    ok = _verify(a1, a2, b1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
