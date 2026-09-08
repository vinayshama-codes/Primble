"""make_sys06_test_pdfs.py - live test kit for SYS-06 (carrier / policy mapping).

    py backend/scripts/make_sys06_test_pdfs.py

Writes to sys06_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

THREE files, TWO sessions. They cannot be merged into one, and that is the
design, not a limitation:

  PACKAGE A   A1 + A2 uploaded TOGETHER (one session)
              The client's own case. Five coverage lines, TWO legal carriers
              with TWO different NAICs, five different policy numbers, and a
              certificate that prints the same policies WITHOUT their term
              markers. Must produce ZERO identity conflicts.

  PACKAGE B   B uploaded ALONE (a second session)
              The positive control. TWO different insurers both writing
              General Liability. Must STILL raise a conflict, and the conflict
              must name the LINE.

WHY NOT ONE PACKAGE
-------------------
A is asserting "nothing is wrong here"; B is asserting "this IS wrong". Put B's
rival GL policy into A and A can no longer prove anything - the conflict it is
supposed to be free of is now legitimately present. Two claims, two sessions.
Different insureds so extraction caches and identity matching never bleed.

WHAT EACH EDGE CASE IS FOR
--------------------------
  1  GL carrier + NAIC differ from every other line       the client's headline
  2  five different policy numbers, one per line          "must not create a
                                                           conflict by themselves"
  3  the certificate drops the ` - 26` / `---26` tail     ONE policy printed two
     (BBC7263 vs BBC7263 - 26, 6E74002 vs 6E7-40-02---26)  ways; the defect that
                                                           produced "two policies
                                                           on the same coverage
                                                           line" on clean data
  4  ISO/AAIS FORM numbers printed on the IM section      a form number names the
     (IM 7100 06 04, CG 00 01 04 13)                       coverage WORDING - it
                                                           must never become a
                                                           phantom sixth policy
  5  a SHORT but real policy number (CR-4471)             the form-number filter
                                                           must be narrow: it may
                                                           not also eat short
                                                           real numbers
  6  the certificate prints NO premiums                   a COI corroborates a
                                                           line, it never rivals
                                                           it
  7  both documents print the same policies               the SOURCE column: each
                                                           record must cite BOTH
                                                           files
  8  (B) two real GL policies, two real carriers          scoping is not an
                                                           amnesty - D-1 must
                                                           still fire
  9  (B) a clean Auto line beside the conflict            a conflict on ONE line
                                                           must not poison the
                                                           rest of the package
 10  (B) confirm the GL answer                            it must apply to the GL
                                                           line ONLY, populate the
                                                           GL form, leave Auto
                                                           alone, and not come back

WHY THE CARRIER NAMES AND POLICY NUMBERS ARE THE CLIENT'S LITERAL ONES
----------------------------------------------------------------------
Standing rule (`replay-client-report-verbatim`): a fix can pass every unit test
and still fail the reported case. Both mechanisms under test are sensitive to the
exact strings:

  * `normalize_carrier` is a FAMILY key - "EMC Property & Casualty Company" and
    "Employers Mutual Casualty Company" BOTH reduce to "emc". Invented names do
    not fuse, so an invented package would pass without testing anything.
  * the term-marker fold requires the tail to be printed SEPARATED. `BBC7263 - 26`
    folds into `BBC7263`; `POL12345` does not fold into `POL123`. Only the real
    shapes exercise it.

The INSUREDS are invented, so these sessions cannot collide with earlier runs.

Design rules (inherited from make_c6/make_h5, all proven)
---------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY, so nothing drifts into an expired-term or renewal
  path (a routed renewal moves dates to prior_* and changes what is asked).
* Every coverage line prints its OWN Carrier / NAIC / Policy Number / Premium -
  what RULE 16 asks extraction for and what the line records read.
* Every package's ABSENCES are self-verified at the bottom of this file by
  scanning the generated text. One stray word silently invalidates a check.
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
    "sys06_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Harborline Insurance Brokers LLC"

# ── The client's literal identity values (see the module docstring) ─────────
CAR_GL = "EMC Property & Casualty Company"        # NAIC 25186 - GL only
CAR_PKG = "Employers Mutual Casualty Company"     # NAIC 21415 - everything else
NAIC_GL = "25186"
NAIC_PKG = "21415"

# Dec-page printings: the term marker is SEPARATED, which is what makes it a
# term marker rather than part of the number.
POL_GL_LONG = "BBC7263 - 26"
POL_AUTO_LONG = "6E7-40-02---26"
POL_UMB_LONG = "6J7-40-02---26"
POL_IM_LONG = "6C7-40-02---26"
POL_CRIME = "CR-4471"                             # short, and real (edge case 5)

# Certificate printings: the same five contracts, tail dropped.
POL_GL_SHORT = "BBC7263"
POL_AUTO_SHORT = "6E74002"
POL_UMB_SHORT = "6J74002"
POL_IM_SHORT = "6C74002"

# ISO / AAIS FORM numbers. These name coverage WORDING, never a contract.
FORM_NUMBERS = ["IM 7100 06 04", "IM 7201 10 02", "CG 00 01 04 13"]


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


def _new_page(c, title, subtitle=""):
    c.showPage()
    return _page(c, title, subtitle)


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


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp,
               yib, naics, entity="Limited Liability Company"):
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


def _coverage(c, y, heading, carrier, naic, policy, premium, limits):
    """One coverage part as a package dec page prints it: the line's OWN
    carrier, NAIC, number and premium under its own heading. This block is
    exactly what RULE 16 turns into a `coverage_lines` row, and what
    `_build_line_records` folds into one record per (line, contract)."""
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    if naic:
        y = _row(c, y, "Carrier NAIC", naic)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    for label, value in limits:
        y = _row(c, y, label, value)
    y = _row(c, y, "Annual Premium", premium)
    return y


GL_LIMITS = [("Each Occurrence Limit", "$1,000,000"),
             ("General Aggregate Limit", "$2,000,000"),
             ("Products/Completed Operations Aggregate", "$2,000,000"),
             ("Personal & Advertising Injury Limit", "$1,000,000"),
             ("Damage To Rented Premises", "$100,000"),
             ("Medical Expense Limit", "$5,000"),
             ("Coverage Form", "Occurrence")]
AUTO_LIMITS = [("Combined Single Limit - Each Accident", "$1,000,000"),
               ("Covered Autos", "Symbol 1 - Any Auto"),
               ("Comprehensive Deductible", "$1,000"),
               ("Collision Deductible", "$1,000")]
UMB_LIMITS = [("Each Occurrence Limit", "$3,000,000"),
              ("Aggregate Limit", "$3,000,000"),
              ("Self-Insured Retention", "$10,000"),
              ("Coverage Form", "Occurrence")]
IM_LIMITS = [("Scheduled Equipment Limit", "$285,000"),
             ("Per Item Maximum", "$60,000"),
             ("Deductible", "$1,000")]
CRIME_LIMITS = [("Employee Theft Limit", "$100,000"),
                ("Deductible", "$2,500")]


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE A - THE CLIENT'S CASE (two files, uploaded TOGETHER)
# ════════════════════════════════════════════════════════════════════════════

A_INSURED = "Kestrel Ridge Logistics LLC"
A_ADDR = "4820 Falconer Way, Suite 210, Boise, ID 83709"
A_FEIN = "84-3319027"
A_OPS = "Refrigerated freight hauling and bonded warehousing for food distributors"


def build_a1(path):
    """The package declarations page - five lines, two carriers, five numbers."""
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - Renewal is not being sought; this is a "
              "new proposal")
    y = _applicant(c, y, A_INSURED, A_ADDR, A_FEIN,
                   "Marla Devereaux", "(208) 555-0148", "mdevereaux@kestrelridge.com",
                   A_OPS, "$7,450,000", "38", "12", "484121")
    y = _head(c, y, "SCHEDULE OF COVERAGES - THIS POLICY IS ISSUED BY MORE THAN ONE COMPANY")
    y = _para(c, y, "Each coverage part below is written by the company named against it and")
    y = _para(c, y, "carries its own policy number. The companies are affiliates of one group.")
    y = _table(
        c, y,
        ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
        [["General Liability", CAR_GL, NAIC_GL, POL_GL_LONG, "$6,720"],
         ["Commercial Auto", CAR_PKG, NAIC_PKG, POL_AUTO_LONG, "$2,991"],
         ["Commercial Umbrella", CAR_PKG, NAIC_PKG, POL_UMB_LONG, "$1,480"],
         ["Inland Marine", CAR_PKG, NAIC_PKG, POL_IM_LONG, "$905"],
         ["Crime", CAR_PKG, NAIC_PKG, POL_CRIME, "$310"]],
        [1.0, 2.25, 4.35, 4.95, 6.55])
    y = _row(c, y, "Total Advance Premium", "$12,406")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", CAR_GL, NAIC_GL,
                  POL_GL_LONG, "$6,720", GL_LIMITS)
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE", "RATE"],
               [["99471", "Refrigerated warehousing", "Area", "44,000", "1.884"],
                ["91580", "Contractors - subcontracted work", "Cost", "$118,400", "2.310"]],
               [1.0, 2.0, 4.6, 5.5, 6.7])

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS", "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", CAR_PKG, NAIC_PKG,
                  POL_AUTO_LONG, "$2,991", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2022", "Freightliner", "M2 106", "1FVACWDT4NHNM1234", "33,000", "Commercial"],
                ["2020", "Isuzu", "NRR", "JALE5W165L7900321", "19,500", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])

    y = _new_page(c, "COMMERCIAL UMBRELLA DECLARATIONS",
                  "Coverage Part - Commercial Umbrella")
    y = _coverage(c, y, "COMMERCIAL UMBRELLA COVERAGE PART", CAR_PKG, NAIC_PKG,
                  POL_UMB_LONG, "$1,480", UMB_LIMITS)
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, ["COVERAGE", "COMPANY", "POLICY NUMBER", "LIMIT"],
               [["General Liability", CAR_GL, POL_GL_LONG, "$1,000,000"],
                ["Business Auto Liability", CAR_PKG, POL_AUTO_LONG, "$1,000,000"]],
               [1.0, 2.5, 4.6, 6.4])

    y = _new_page(c, "INLAND MARINE DECLARATIONS",
                  "Coverage Part - Inland Marine (Contractors Equipment)")
    y = _coverage(c, y, "INLAND MARINE COVERAGE PART", CAR_PKG, NAIC_PKG,
                  POL_IM_LONG, "$905", IM_LIMITS)
    # EDGE CASE 4. Form numbers are printed exactly where a real dec page prints
    # them - a FORMS AND ENDORSEMENTS schedule on the coverage part - so an
    # extractor that mistakes one for a policy number produces a phantom SIXTH
    # policy on a line that already has one.
    y = _head(c, y, "FORMS AND ENDORSEMENTS APPLICABLE TO THIS COVERAGE PART")
    y = _table(c, y, ["FORM NUMBER", "FORM TITLE"],
               [[FORM_NUMBERS[0], "Contractors Equipment Coverage Form"],
                [FORM_NUMBERS[1], "Scheduled Equipment Endorsement"],
                [FORM_NUMBERS[2], "Commercial General Liability Coverage Form"]],
               [1.0, 3.0])
    y = _head(c, y, "CRIME COVERAGE PART")
    y = _coverage(c, y, "COMMERCIAL CRIME COVERAGE PART", CAR_PKG, NAIC_PKG,
                  POL_CRIME, "$310", CRIME_LIMITS)

    c.save()


def build_a2(path):
    """A certificate naming the SAME five contracts - tails dropped, no premiums."""
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and confers "
              "no rights upon the certificate holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", A_INSURED)
    y = _row(c, y, "Insured Address", A_ADDR)
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _table(c, y, ["LTR", "INSURER", "NAIC #"],
               [["A", CAR_GL, NAIC_GL],
                ["B", CAR_PKG, NAIC_PKG]],
               [1.0, 1.6, 5.6])
    # EDGE CASE 3 + 6: the same five contracts, printed WITHOUT the separated
    # term marker and with NO premium column. A certificate never prints
    # premiums, so every row here is `grants=False` to the stamper - it must
    # corroborate these lines, never rival them.
    y = _head(c, y, "COVERAGES - CERTIFICATE NUMBER: CRT-2291")
    y = _table(
        c, y,
        ["LTR", "TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
        [["A", "General Liability", POL_GL_SHORT, EFF, EXP, "$1,000,000 Each Occurrence"],
         ["B", "Automobile Liability", POL_AUTO_SHORT, EFF, EXP, "$1,000,000 CSL"],
         ["B", "Umbrella Liability", POL_UMB_SHORT, EFF, EXP, "$3,000,000 Each Occurrence"],
         ["B", "Inland Marine", POL_IM_SHORT, EFF, EXP, "$285,000 Scheduled Equipment"],
         ["B", "Crime", POL_CRIME, EFF, EXP, "$100,000 Employee Theft"]],
        [1.0, 1.4, 3.15, 4.45, 5.35, 6.25])
    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    y = _para(c, y, A_OPS + ".")
    y = _para(c, y, "Certificate holder is an additional insured with respect to operations")
    y = _para(c, y, "at the terminal, as required by written contract.")
    y = _head(c, y, "CERTIFICATE HOLDER")
    y = _para(c, y, "Cascade Terminal Authority, 1900 Dockside Road, Lewiston, ID 83501")

    c.save()


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE B - THE CONTROL (one file, uploaded ALONE)
# ════════════════════════════════════════════════════════════════════════════

B_INSURED = "Thornbury Grounds Management LLC"
B_ADDR = "77 Marchmont Lane, Spokane, WA 99205"
B_FEIN = "27-6640185"
B_OPS = "Commercial landscaping, grounds maintenance and seasonal snow removal"

B_CAR_1 = "Redwood Basin Insurance Company"
B_CAR_2 = "Trinity Ridge Mutual Insurance Company"
B_NAIC_1 = "14312"
B_NAIC_2 = "36161"
B_POL_GL_1 = "RB-GL-880194-26"
B_POL_GL_2 = "TR-4471102-26"
B_POL_AUTO = "RB-CA-880771-26"


def build_b(path):
    """TWO different insurers both writing General Liability, plus a clean Auto
    line written by one of them alone."""
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - new proposal")
    y = _applicant(c, y, B_INSURED, B_ADDR, B_FEIN,
                   "Devon Ashcroft", "(509) 555-0172", "dashcroft@thornburygm.com",
                   B_OPS, "$3,120,000", "24", "9", "561730")
    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _para(c, y, "Two General Liability policies are shown below. Both were bound for the")
    y = _para(c, y, "same period and the file does not record which one is being placed.")
    y = _table(
        c, y,
        ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
        [["General Liability", B_CAR_1, B_NAIC_1, B_POL_GL_1, "$5,010"],
         ["General Liability", B_CAR_2, B_NAIC_2, B_POL_GL_2, "$5,240"],
         ["Commercial Auto", B_CAR_1, B_NAIC_1, B_POL_AUTO, "$2,180"]],
        [1.0, 2.25, 4.35, 4.95, 6.55])

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability (first of two on file)")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", B_CAR_1, B_NAIC_1,
                  B_POL_GL_1, "$5,010", GL_LIMITS)
    y = _head(c, y, "GENERAL LIABILITY COVERAGE PART - SECOND POLICY ON FILE")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", B_CAR_2, B_NAIC_2,
                  B_POL_GL_2, "$5,240", GL_LIMITS)

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS", "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", B_CAR_1, B_NAIC_1,
                  B_POL_AUTO, "$2,180", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2021", "Ford", "F-350", "1FT8W3BT5MED55512", "14,000", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])

    c.save()


# ════════════════════════════════════════════════════════════════════════════
# Self-verification - a stray word silently invalidates a check
# ════════════════════════════════════════════════════════════════════════════

def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _verify(paths):
    a1, a2, b = (_text(p) for p in paths)
    problems = []

    def need(hay, needle, where):
        if needle not in hay:
            problems.append(f"{where}: MISSING {needle!r}")

    def forbid(hay, needle, where):
        if needle in hay:
            problems.append(f"{where}: must NOT contain {needle!r}")

    # A1 - every line states its own carrier, NAIC and number.
    for v in (CAR_GL, CAR_PKG, NAIC_GL, NAIC_PKG, POL_GL_LONG, POL_AUTO_LONG,
              POL_UMB_LONG, POL_IM_LONG, POL_CRIME, *FORM_NUMBERS):
        need(a1, v, "A1")
    # The dec page must NOT carry the short printings as VALUES of their own,
    # or the fold is not being tested - it would just be two documents agreeing.
    #
    # A plain substring test cannot say this, and the self-check caught that on
    # its first run: the short printing is a PREFIX of the long one by
    # construction ("BBC7263" is inside "BBC7263 - 26"), so `forbid` fired on
    # the very value the page is supposed to print. The honest test is a COUNT -
    # every occurrence of the short form must be accounted for by a long one.
    for short, long in ((POL_GL_SHORT, POL_GL_LONG),
                        (POL_AUTO_SHORT, POL_AUTO_LONG),
                        (POL_UMB_SHORT, POL_UMB_LONG),
                        (POL_IM_SHORT, POL_IM_LONG)):
        if a1.count(short) > a1.count(long):
            problems.append(
                f"A1: {short!r} appears on its own ({a1.count(short)} times vs "
                f"{a1.count(long)} of {long!r}) - the certificate would then be "
                f"agreeing rather than folding, and the kit tests nothing")

    # A2 - the SHORT printings, and no premium anywhere.
    for v in (POL_GL_SHORT, POL_AUTO_SHORT, POL_UMB_SHORT, POL_IM_SHORT,
              CAR_GL, CAR_PKG):
        need(a2, v, "A2")
    for v in ("Annual Premium", "Advance Premium", "$6,720", "$2,991"):
        forbid(a2, v, "A2")
    # And it must NOT print the long forms, or there is nothing to fold.
    # (A long form is not a substring of its short one, so a plain test is
    # correct in this direction.)
    for v in (POL_GL_LONG, POL_AUTO_LONG, POL_UMB_LONG, POL_IM_LONG):
        forbid(a2, v, "A2")

    # B - two GL carriers, two GL numbers, one clean Auto line.
    for v in (B_CAR_1, B_CAR_2, B_POL_GL_1, B_POL_GL_2, B_POL_AUTO):
        need(b, v, "B")
    # B must not name the A carriers, or the control's conflict could be read
    # as the same family fusion A is testing.
    for v in (CAR_GL, CAR_PKG):
        forbid(b, v, "B")
    # Neither package may mention Workers Compensation - an unasked-for line
    # changes what the questionnaire and the scorer demand.
    for name, hay in (("A1", a1), ("A2", a2), ("B", b)):
        for v in ("Workers Compensation", "Workers' Compensation"):
            forbid(hay, v, name)

    # The term-marker fold must be a REAL fold, not string equality.
    from services.fact_comparison import same_policy_contract
    pairs = [(POL_GL_LONG, POL_GL_SHORT), (POL_AUTO_LONG, POL_AUTO_SHORT),
             (POL_UMB_LONG, POL_UMB_SHORT), (POL_IM_LONG, POL_IM_SHORT)]
    for lo, sh in pairs:
        if not same_policy_contract(lo, sh):
            problems.append(f"door: {lo!r} and {sh!r} do NOT fold - the kit "
                            f"would not test the defect")
    # ...and the control's two GL policies must NOT fold, or B proves nothing.
    if same_policy_contract(B_POL_GL_1, B_POL_GL_2):
        problems.append("door: the control's two GL policies fold - B is useless")
    # A short-but-real number must survive the form-number filter (edge case 5).
    from services.extraction_service import _looks_like_a_form_number
    if _looks_like_a_form_number(POL_CRIME):
        problems.append(f"{POL_CRIME!r} is read as a FORM number - it is a real "
                        f"policy number and would lose its scope")
    for f in FORM_NUMBERS:
        if not _looks_like_a_form_number(f):
            problems.append(f"{f!r} is NOT read as a form number - it would "
                            f"become a phantom policy")
    return problems


README = """# SYS-06 live test - carrier and policy number stay LINE-SPECIFIC

Generated by `backend/scripts/make_sys06_test_pdfs.py`.

**THREE files, TWO separate uploads. Do not merge them.**
Package A asserts *"nothing is wrong here"*; Package B asserts *"this IS wrong"*.
Putting B's rival GL policy into A would destroy A's whole claim.

---

## Upload 1 - PACKAGE A (the client's case)

**Upload `A1_package_dec_five_lines.pdf` AND `A2_certificate_same_policies.pdf`
TOGETHER, in one session.**

Kestrel Ridge Logistics. Five coverage lines, **two legal carriers with two
different NAICs**, five different policy numbers - and a certificate that names
the same five contracts with the term marker dropped (`BBC7263` for
`BBC7263 - 26`, `6E74002` for `6E7-40-02---26`).

**Generate: ACORD 125, ACORD 126, ACORD 127, ACORD 131.**

### Data Consistency - the whole point

| Row | Expected |
|---|---|
| Carrier | **`2 policies, 2 values - not a conflict`** (read-only, no radio buttons) |
| Policy Number | **`5 policies, 5 values - not a conflict`** |
| Carrier NAIC | **`2 policies, 2 values - not a conflict`** |
| Anything asking you to CHOOSE a carrier or a policy number | **FAIL - send the card** |

You should also see a new **"Policies in this submission"** table above those
rows. It must read:

| Line | Carrier | NAIC | Policy number | Source |
|---|---|---|---|---|
| General Liability | EMC Property & Casualty Company | 25186 | BBC7263 - 26 | **both files** |
| Commercial Auto | Employers Mutual Casualty Company | 21415 | 6E7-40-02---26 | **both files** |
| Commercial Umbrella | Employers Mutual Casualty Company | 21415 | 6J7-40-02---26 | **both files** |
| Inland Marine | Employers Mutual Casualty Company | 21415 | 6C7-40-02---26 | **both files** |
| Crime | Employers Mutual Casualty Company | 21415 | CR-4471 | both files |

Five rows. **Not six, not nine.** The things that must NOT appear as policies:

* `IM 7100 06 04`, `IM 7201 10 02`, `CG 00 01 04 13` - ISO/AAIS **form numbers**
  printed in the Inland Marine forms schedule. A form number names the coverage
  WORDING, not a contract.
* `BBC7263`, `6E74002`, `6J74002`, `6C74002` as **separate** policies - they are
  the certificate's printing of contracts already listed.

`CR-4471` **must** appear. It is short, and it is real - the form-number filter
has to be narrow enough not to eat it.

### On the forms - each line's own identity

| Form | Policy number | Carrier | NAIC |
|---|---|---|---|
| ACORD 126 (GL) | `BBC7263 - 26` | EMC Property & Casualty Company | `25186` |
| ACORD 127 (Auto) | `6E7-40-02---26` | Employers Mutual Casualty Company | `21415` |
| ACORD 131 (Umbrella) | `6J7-40-02---26` | Employers Mutual Casualty Company | `21415` |
| ACORD 125 | must not pair one carrier's NAME with the other's NAIC (blank is fine) |

**The GL row is the client's headline.** If ACORD 126 shows `21415`, or shows the
Auto number, the pairing has been lost again.

---

## Upload 2 - PACKAGE B (the control)

**Upload `B_two_GL_policies_CONTROL.pdf` ALONE, in a new session.**

Thornbury Grounds. **Two different insurers both writing General Liability**,
plus a clean Auto line written by one of them alone. **This package is SUPPOSED
to complain.**

**Generate: ACORD 125, ACORD 126, ACORD 127.**

### Step 1 - before you confirm anything

| Row | Expected |
|---|---|
| Carrier | **CONFLICT.** Reason must name the line: *"two policies on the same coverage line (general liab)..."* |
| Policy Number | **CONFLICT**, same reason |
| The button on that card | **`Confirm for general liab`** - not "Confirm & apply to forms" |
| ACORD 127 (Auto) | `RB-CA-880771-26` / Redwood Basin - **clean, unaffected** |

**If B is silent, the fix over-corrected. That matters more than A passing.**
The Auto line staying clean is the second half: a conflict on ONE line must not
poison the rest of the package.

### Step 2 - now confirm

Select **`Redwood Basin Insurance Company`** on the Carrier card and click
**Confirm for general liab**. Then select **`RB-GL-880194-26`** on the Policy
Number card and confirm it the same way.

| After confirming | Expected |
|---|---|
| The Carrier / Policy Number rows | no longer a conflict; the scoped row shows `Confirmed: general liab - Redwood Basin Insurance Company` |
| ACORD 126 (GL) | `RB-GL-880194-26` / Redwood Basin Insurance Company / `14312` |
| ACORD 127 (Auto) | **still** `RB-CA-880771-26` / Redwood Basin - the answer must not have leaked onto another line |
| The same question reappearing | **FAIL** - the answer has to stick |

---

## What to send back

Per upload, in one message. A PASS / DIFFERS table is enough - **one failing line
with the value it actually printed beats the rest passing**, because the value
tells me which door failed.

**Package A**
1. The whole **Data Consistency** section, including the "Policies in this
   submission" table (I need the Source column).
2. The **policy number, carrier and NAIC header boxes** from ACORD 126, 127
   and 131.
3. The ACORD 125 carrier / NAIC header.
4. The **warning count** at the top.

**Package B**
1. The Data Consistency section **before** confirming - I need to see the
   conflict and the exact reason text and button label.
2. The same section **after** confirming both cards.
3. ACORD 126 and ACORD 127 headers, after confirming.

### On scores

They are **supposed to move up on A** - the identity boxes that used to ship
blank now fill, which adds fill-rate credit, and A no longer carries a false
carrier conflict. **B should still be capped** before you confirm; it has a real
conflict. If A's score moves DOWN, send it - that is a finding.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    a1 = os.path.join(OUT_DIR, "A1_package_dec_five_lines.pdf")
    a2 = os.path.join(OUT_DIR, "A2_certificate_same_policies.pdf")
    b = os.path.join(OUT_DIR, "B_two_GL_policies_CONTROL.pdf")
    build_a1(a1)
    build_a2(a2)
    build_b(b)

    problems = _verify([a1, a2, b])
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)

    for p in (a1, a2, b):
        print("wrote", os.path.relpath(p, os.path.dirname(OUT_DIR)))
    print("wrote", os.path.relpath(
        os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), os.path.dirname(OUT_DIR)))
    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("\nself-check: OK - every value present, every absence held, and the "
          "fold/no-fold pairs behave as the kit assumes")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    main()
