"""make_policy_by_line_test_pdfs.py - live kit: policy number BY COVERAGE LINE.

    py backend/scripts/make_policy_by_line_test_pdfs.py

Writes policy_by_line_test_data/ at the repo root plus README-HOW-TO-TEST.md.

Client, 17 Sep 2026: "We received feedback that a single policy number is still
trying to be represented across all. Please let me know if this was corrected."

THREE files, TWO uploads - and it cannot be fewer:

  UPLOAD 1   1_renewal_package_policy.pdf + 2_certificate_project_gl.pdf
             The GL line has to be contested ACROSS documents to raise the
             producer question (the card compares documents, not rows), and a
             certificate carries exactly one role - so two files is a floor.
  UPLOAD 2   3_renewal_summary_one_number.pdf alone
             One printed number for three separate policies. Its whole point is
             that NO line identifies its own contract; merged with upload 1, the
             per-line index would identify them and the test would go inert.

WHAT EACH TRAP IS FOR (file 1 unless marked)
--------------------------------------------
   1  page-1 premium table: lines + premiums, no carrier,    the live Orbin shape
      no number, the group BRAND in the header
   2  page 1 prints ONE number, in a correspondence note     the single-number push,
      ("4A8 21 07 26")                                         and the D1 shape
                                                               inside a real package
   3  Workers Comp "No Coverage" directly above the IM dec    run 11 phantom WC
   4  THREE near-identical carrier entities                   a family key fuses them
      (Mutual Casualty / Property & Casualty / Specialty)
   5  IM issued by "Quillon Specialty Insurance Company"      _HEADER_CARRIER_RE stops
                                                               at the first INSURANCE
   6  GL + Property share ONE package number                  over-refusal control
   7  auto dec: "not part of package policy QPC5519 - 26"     a body sentence naming
                                                               another contract
   8  4A8-21-07---26 / 4A82107 / "4A8 21 07 26"               one contract, three printings
   9  QPC5519 - 26 / QPC5519                                  term-marker folding
  10  RENEWAL OF -25 numbers on the current dec pages         prior term, current box
  11  umbrella SCHEDULE OF UNDERLYING INSURANCE on the        run 8 polluted index
      umbrella's own page; "Quillon P&C Co."                   + the P&C abbreviation
  12  "Employers Liability - Not Scheduled"                   phantom WC / EL row
  13  Hired and Non-Owned Auto Liability on the PACKAGE page  auto-canon entry carrying
                                                               the package number
  14  IM 7100 06 04, CG 00 01 04 13, CA7001A 02-22,           form numbers beside
      CU7001A 11-15, CG 70 22A 04 17                           policy numbers
  15  forms schedule naming all four contracts                a page that binds nothing
  16  serial GS4618A-51207, loan LN-00917733, account         identifiers shaped like
      0482917, contract LCOA-2026-114                          policy numbers
  17  umbrella's older carrier Birchline BSX-44120-24         an older prior carrier
  18  loss run: claims under -25 / -24 numbers, dated         prior numbers undated
                                                               (RENEWAL OF) AND dated
  19  umbrella term 03/15 vs everyone else's 01/01            per-line term
  20  (file 2) a PROJECT GL policy from another carrier       two real GL policies:
                                                               the system must ASK,
                                                               for GL only
  21  (file 3) one number, three "separate" policies          the surviving form of
                                                               the client's complaint

No real carrier, insured or agency is named anywhere. The AAIS / ISO form
numbers are real public form references, printed the way carrier packages print
them.
"""

from __future__ import annotations

import os
import re
import sys

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(REPO_ROOT, "backend")
OUT_DIR = os.path.join(REPO_ROOT, "policy_by_line_test_data")

F1 = "1_renewal_package_policy.pdf"
F2 = "2_certificate_project_gl.pdf"
F3 = "3_renewal_summary_one_number.pdf"

# ── Upload 1 ─────────────────────────────────────────────────────────────────
A_INSURED = "BRAMBLE & STONE CONSTRUCTION LLC"
A_INSURED_MIXED = "Bramble & Stone Construction LLC"
A_ADDR = "2250 W Larkspur Ave, Denver, CO 80223"
A_FEIN = "84-7730214"
A_ACCOUNT = "0482917"
AGENCY = "Front Range Risk Advisors"
AGENT = "Priya Natarajan"
AGENCY_PHONE = "(303) 555-0176"

BRAND = "QUILLON INSURANCE GROUP"
CAR_PC = "Quillon Property & Casualty Company"
CAR_PC_ABBR = "Quillon P&C Co."
NAIC_PC = "91880"
CAR_MUT = "Quillon Mutual Casualty Company"
CAR_MUT_COI = "Quillon Mutual Casualty Co."
NAIC_MUT = "91872"
CAR_SPEC = "Quillon Specialty Insurance Company"
CAR_SPEC_COI = "Quillon Specialty Insurance Co."
CAR_SPEC_TRUNCATED = "QUILLON SPECIALTY INSURANCE"
NAIC_SPEC = "91895"

RIVAL_CARRIER = "Larchmont Specialty Insurance Company"
RIVAL_CARRIER_COI = "Larchmont Specialty Insurance Co."
RIVAL_NAIC = "93518"
POL_RIVAL_GL = "LSG-4471102-26"

POL_CPP = "QPC5519 - 26"
POL_CPP_SHORT = "QPC5519"
POL_CPP_PRIOR = "QPC5519 - 25"
POL_CPP_PRIOR2 = "QPC5519 - 24"
POL_AUTO = "4A8-21-07---26"
POL_AUTO_SHORT = "4A82107"
POL_AUTO_PROSE = "4A8 21 07 26"
POL_AUTO_PRIOR = "4A8-21-07---25"
POL_UMB = "4U8-21-07---26"
POL_UMB_SHORT = "4U82107"
POL_UMB_PRIOR = "4U8-21-07---25"
POL_IM = "SIM-7730418"
POL_IM_SHORT = "SIM7730418"
OLD_UMB_CARRIER = "Birchline Specialty Casualty Company"
POL_UMB_OLDEST = "BSX-44120-24"

FORM_AAIS = "IM 7100 06 04"
FORM_ISO_CGL = "CG 00 01 04 13"
FORM_AUTO_DEC = "CA7001A 02-22"
FORM_UMB_SCHED = "CU7001A 11-15"
FORM_HNOA = "CG 70 22A 04 17"

LENDER = "First Front Range Bank"
LOAN_NO = "LN-00917733"
SERIAL_TRAP = "GS4618A-51207"
CONTRACT_TRAP = "LCOA-2026-114"
AI_HOLDER = "Larkspur Commons Owners Association"

# ── Upload 2 ─────────────────────────────────────────────────────────────────
D_INSURED = "CINDERHOLT LANDSCAPE GROUP INC"
D_ADDR = "5120 Tejon St, Denver, CO 80221"
D_CARRIER = "Sagebrush Ridge Casualty Company"
D_NUMBER = "SRC-4410982"


# ── Layout ───────────────────────────────────────────────────────────────────
# Every column start is MEASURED with reportlab's own font metrics. A fused cell
# ("UmbrellaQuillon") hands the model one token where the document prints two,
# and the row under test silently stops testing anything.

PAGE_W, PAGE_H = LETTER
LM = 0.75 * inch
RM = PAGE_W - 0.75 * inch
USABLE = RM - LM
BOTTOM = 0.85 * inch
COL_GAP = 16


class _Doc:
    def __init__(self, path: str):
        self.path = path
        self.c = canvas.Canvas(path, pagesize=LETTER)
        self.y = 0.0
        self.page_no = 0
        self.footer = ""

    def page(self, title, subtitle="", header=(), footer=""):
        if self.page_no:
            self._finish()
        self.page_no += 1
        self.footer = footer
        c = self.c
        y = PAGE_H - 0.55 * inch
        for i, line in enumerate(header):
            self._fits(line, "Helvetica-Bold", 8.5)
            c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 8.5)
            c.drawString(LM, y, line)
            y -= 11.5
        y -= 6
        c.setFont("Helvetica-Bold", 14)
        c.drawString(LM, y, title)
        y -= 15
        if subtitle:
            c.setFont("Helvetica", 9.5)
            c.drawString(LM, y, subtitle)
            y -= 12
        c.setLineWidth(0.7)
        c.line(LM, y, RM, y)
        self.y = y - 16

    def _finish(self):
        if self.footer:
            self.c.setFont("Helvetica", 7.5)
            self.c.drawString(LM, 0.5 * inch, self.footer)
        self.c.showPage()

    def save(self):
        self._finish()
        self.c.save()

    def _room(self, need):
        if self.y - need < BOTTOM:
            raise RuntimeError(f"{os.path.basename(self.path)}: page {self.page_no} overflows")

    @staticmethod
    def _fits(text, font, size, x=LM):
        if x + stringWidth(str(text), font, size) > RM:
            raise RuntimeError(f"text runs off the page: {text!r}")

    def row(self, label, value):
        self._room(14)
        lab = f"{label}:"
        x = LM + max(stringWidth(lab, "Helvetica-Bold", 9) + 10, 2.0 * inch)
        self._fits(value, "Helvetica", 9, x)
        self.c.setFont("Helvetica-Bold", 9)
        self.c.drawString(LM, self.y, lab)
        self.c.setFont("Helvetica", 9)
        self.c.drawString(x, self.y, str(value))
        self.y -= 13.5

    def head(self, text):
        self._room(24)
        self.y -= 5
        self.c.setFont("Helvetica-Bold", 10.5)
        self.c.drawString(LM, self.y, text)
        self.y -= 15

    def para(self, text, size=9):
        lines, line = [], ""
        for word in str(text).split():
            trial = f"{line} {word}".strip()
            if stringWidth(trial, "Helvetica", size) <= USABLE:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        for ln in lines:
            self._room(size + 5)
            self.c.setFont("Helvetica", size)
            self.c.drawString(LM, self.y, ln)
            self.y -= size + 4

    def gap(self, pts=6):
        self.y -= pts

    def table(self, headers, rows, size=8.5):
        widths = []
        for i, h in enumerate(headers):
            w = stringWidth(h, "Helvetica-Bold", size)
            for r in rows:
                w = max(w, stringWidth(str(r[i]), "Helvetica", size))
            widths.append(w)
        if sum(widths) + COL_GAP * (len(headers) - 1) > USABLE:
            if size > 6.5:
                return self.table(headers, rows, size - 0.5)
            raise RuntimeError(f"table too wide: {headers}")
        xs = [LM]
        for w in widths[:-1]:
            xs.append(xs[-1] + w + COL_GAP)
        self._room((len(rows) + 1) * (size + 5) + 12)
        c = self.c
        c.setFont("Helvetica-Bold", size)
        for x, h in zip(xs, headers):
            c.drawString(x, self.y, h)
        self.y -= 4
        c.setLineWidth(0.4)
        c.line(LM, self.y, RM, self.y)
        self.y -= size + 4
        c.setFont("Helvetica", size)
        for r in rows:
            for x, cell in zip(xs, r):
                c.drawString(x, self.y, str(cell))
            self.y -= size + 4.5
        self.y -= 5


# ── File 1 - the renewal package policy ─────────────────────────────────────

IM_HEADER_LINE = f"{CAR_SPEC.upper()}      POLICY NUMBER: {POL_IM}"


def build_file1(path):
    d = _Doc(path)

    # Page 1 - common declarations. Lines and premiums only, and ONE number in
    # a correspondence note - the page the model hands its number to every row.
    d.page("COMMON POLICY DECLARATIONS", "Package Renewal - Coverage Summary",
           header=(BRAND, "Home Office: 1400 Harbor View Pkwy, Omaha, NE 68102"))
    d.row("NAMED INSURED", A_INSURED)
    d.row("MAILING ADDRESS", A_ADDR)
    d.row("FEIN", A_FEIN)
    d.row("ACCOUNT NUMBER", A_ACCOUNT)
    d.row("AGENT", f"{AGENCY} - {AGENT} - {AGENCY_PHONE}")
    d.row("BUSINESS DESCRIPTION", "Commercial concrete and masonry contractor")
    d.row("FORM OF BUSINESS", "Limited Liability Company")
    d.row("POLICY PERIOD", "Shown on each policy's declarations")
    d.head("COVERAGES AND PREMIUM")
    d.table(["SECTION", "COVERAGE", "PREMIUM"],
            [["1", "Property", "$3,480.00"],
             ["2", "Liability", "$4,812.00"],
             ["3", "Crime", "No Coverage"],
             ["4", "Inland Marine", "$415.00"],
             ["5", "Automobile", "$3,264.00"],
             ["6", "Workers Compensation", "No Coverage"],
             ["7", "Umbrella", "$2,977.00"]])
    d.row("ESTIMATED TOTAL POLICY PREMIUM", "$14,948.00")
    d.gap()
    d.para("Coverages are issued as separate policies by the member companies of the Quillon "
           "Insurance Group. Property and Liability are written together under one package "
           "policy. See each declarations page for the issuing company, policy number and "
           "policy period.")
    d.para(f"Please reference policy {POL_AUTO_PROSE} in all correspondence about this account.")

    # Page 2 - inland marine, issued by the "... Insurance Company" entity.
    d.page("COMMERCIAL INLAND MARINE DECLARATIONS", "",
           header=(IM_HEADER_LINE, "POLICY PERIOD: FROM 01/01/26 TO 01/01/27", A_INSURED),
           footer=f"CM7000A ED. 3-20      BPP 01/01/26      031      SB {POL_IM_SHORT}      2601")
    d.row("ISSUING COMPANY", CAR_SPEC)
    d.head("COVERAGE SCHEDULE")
    d.table(["COVERAGE", "FORM", "LIMIT", "PREMIUM"],
            [["Contractors Equipment Floater - Scheduled", "CM7000A 03-20", "$185,000", "$325.00"],
             ["Installation Floater", FORM_AAIS, "$50,000", "$90.00"]])
    d.row("TOTAL INLAND MARINE PREMIUM", "$415.00")
    d.head("SCHEDULE OF EQUIPMENT")
    d.table(["ITEM", "DESCRIPTION", "SERIAL NUMBER", "LIMIT"],
            [["1", "2019 Bobcat S650 Skid Steer", "B3NM11482", "$38,000"],
             ["2", "2018 Genie GS-3246 Scissor Lift", SERIAL_TRAP, "$22,000"],
             ["3", "Blanket unscheduled tools", "-", "$25,000"]])

    # Page 3 - the AAIS form page: no policy number on it, an ISO renewal
    # clause that is NOT a statement of renewal, the form number twice.
    d.page("INSTALLATION FLOATER COVERAGE", f"AAIS      {FORM_AAIS}",
           footer=f"{FORM_AAIS}      Page 1 of 1")
    d.para("This coverage applies to materials, supplies and equipment that the insured has "
           "purchased to be installed, erected or fabricated at a job site.")
    d.para("Cancellation - After this policy has been in effect 60 days or more, or if it is "
           "a renewal of a policy issued by \"us\", effective immediately, \"we\" may cancel "
           "this policy by giving the named insured notice.")
    d.para(f"This form must be attached to a policy that includes form {FORM_AAIS}.")

    # Page 4 - the package policy: ONE number, TWO coverage lines.
    cpp_hdr = (f"{CAR_PC.upper()}      NAIC {NAIC_PC}",
               f"POLICY NUMBER: {POL_CPP}      POLICY PERIOD: 01/01/2026 TO 01/01/2027",
               f"RENEWAL OF: {POL_CPP_PRIOR}")
    cpp_ftr = f"Form CG7001A Ed. 10-12      01/01/2026      {POL_CPP_SHORT}      2601"
    d.page("COMMERCIAL PACKAGE POLICY DECLARATIONS", "", header=cpp_hdr, footer=cpp_ftr)
    d.row("NAMED INSURED", A_INSURED)
    d.head("COVERAGE PARTS INCLUDED IN THIS POLICY")
    d.table(["COVERAGE PART", "POLICY NUMBER", "PREMIUM"],
            [["Commercial General Liability Coverage Part", POL_CPP, "$4,812.00"],
             ["Commercial Property Coverage Part", POL_CPP, "$3,480.00"]])
    d.row("PACKAGE POLICY PREMIUM", "$8,292.00")
    d.head("GENERAL LIABILITY LIMITS OF INSURANCE")
    d.table(["COVERAGE", "LIMIT"],
            [["Each Occurrence", "$1,000,000"],
             ["General Aggregate", "$2,000,000"],
             ["Products-Completed Operations Aggregate", "$2,000,000"],
             ["Personal and Advertising Injury", "$1,000,000"],
             ["Medical Expense - Any One Person", "$5,000"]])
    d.row("COVERAGE FORM", f"{FORM_ISO_CGL} Commercial General Liability Coverage Form - Occurrence")
    d.head("GENERAL LIABILITY SCHEDULE - Location 001")
    d.table(["CLASS", "CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE", "PREMIUM"],
            [["97447", "Masonry", "Payroll", "$412,000", "$3,406.00"],
             ["91585", "Contractors - subcontracted work", "Total Cost", "$180,000", "$1,258.00"]])
    d.head("ADDITIONAL COVERAGES ON THIS POLICY")
    d.table(["COVERAGE", "FORM", "PREMIUM"],
            [["Hired and Non-Owned Auto Liability", FORM_HNOA, "$148.00"]])

    # Page 5 - property coverage part + GL endorsements, same contract.
    d.page("COMMERCIAL PROPERTY COVERAGE PART", "", header=cpp_hdr, footer=cpp_ftr)
    d.row("PREMISES - LOCATION 001", A_ADDR)
    d.row("BUILDING LIMIT", "$1,250,000")
    d.row("BUSINESS PERSONAL PROPERTY", "$260,000")
    d.row("YEAR BUILT", "2006")
    d.row("CONSTRUCTION", "Masonry Non-Combustible")
    d.row("SPRINKLERED", "Yes")
    d.row("PROTECTION CLASS", "3")
    d.head("ADDITIONAL INSURED - OWNERS, LESSEES OR CONTRACTORS - SCHEDULED PERSON")
    d.row("SCHEDULED ORGANIZATION", AI_HOLDER)
    d.row("PROJECT CONTRACT NUMBER", CONTRACT_TRAP)
    d.head("THIS ENDORSEMENT MODIFIES INSURANCE PROVIDED UNDER THE FOLLOWING:")
    d.para("COMMERCIAL GENERAL LIABILITY COVERAGE PART")
    d.para("COMMERCIAL AUTO COVERAGE PART")
    d.para("COMMERCIAL UMBRELLA LIABILITY COVERAGE PART")

    # Page 6 - business auto (Quillon Mutual): prior number, loan number, and a
    # sentence naming the package policy.
    d.page("COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO", "",
           header=(f"{CAR_MUT.upper()}      POLICY NO: {POL_AUTO}",
                   f"{A_INSURED}      EFF DATE: 01/01/26      EXP DATE: 01/01/27",
                   f"RENEWAL OF: {POL_AUTO_PRIOR}"),
           footer=f"{FORM_AUTO_DEC}      BPP 01/01/26      031      SB {POL_AUTO_SHORT}      2601")
    d.head("ITEM TWO - SCHEDULE OF COVERAGES AND COVERED AUTOS")
    d.table(["COVERAGE", "SYMBOL", "LIMIT", "PREMIUM"],
            [["Covered Autos Liability", "01", "$1,000,000 Combined Single Limit", "$2,410.00"],
             ["Medical Payments", "02", "$5,000", "$62.00"],
             ["Uninsured Motorists", "02", "$1,000,000", "$148.00"],
             ["Comprehensive", "07", "$1,000 Deductible", "$286.00"],
             ["Collision", "07", "$1,000 Deductible", "$358.00"]])
    d.row("TOTAL AUTO PREMIUM", "$3,264.00")
    d.head("ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN")
    d.table(["VEH", "YEAR MAKE MODEL", "VIN", "CLASS", "TERR", "COST NEW"],
            [["1", "2021 Ford F-150", "1FTFW1E58MFA23417", "01499", "111", "$48,600"],
             ["2", "2020 Ram 2500", "3C6UR5DL4LG190275", "21499", "111", "$52,300"]])
    d.head("LOSS PAYEE SCHEDULE")
    d.row("LOSS PAYEE - VEH 2", f"{LENDER}, 1700 Broadway, Denver, CO 80290")
    d.row("LOAN NUMBER", LOAN_NO)
    d.para(f"This business auto policy is issued separately and is not part of package policy "
           f"{POL_CPP}.")

    # Page 7 - umbrella (Quillon Mutual): its OWN term, an older prior carrier,
    # and the schedule of underlying insurance on the umbrella's own page.
    d.page("COMMERCIAL UMBRELLA DECLARATIONS", "",
           header=(f"{CAR_MUT.upper()}      POLICY NO: {POL_UMB}",
                   f"{A_INSURED}      EFF DATE: 03/15/26      EXP DATE: 03/15/27",
                   f"RENEWAL OF: {POL_UMB_PRIOR}"),
           footer=f"{FORM_UMB_SCHED}      031      SB {POL_UMB_SHORT}      2601")
    d.row("EACH OCCURRENCE LIMIT", "$2,000,000")
    d.row("AGGREGATE LIMIT", "$2,000,000")
    d.row("SELF-INSURED RETENTION", "$0")
    d.row("COVERAGE FORM", "Commercial Umbrella Liability Coverage Form CU7000 11-15 - Occurrence")
    d.row("UMBRELLA PREMIUM", "$2,977.00")
    d.row("PRIOR UMBRELLA CARRIER", f"{OLD_UMB_CARRIER} - {POL_UMB_OLDEST} - 03/15/2024 to 03/15/2025")
    d.head("SCHEDULE OF UNDERLYING INSURANCE")
    d.table(["UNDERLYING COVERAGE", "COMPANY", "POLICY NUMBER", "LIMITS"],
            [["Commercial General Liability", CAR_PC_ABBR, POL_CPP_SHORT,
              "$1,000,000 occ / $2,000,000 agg"],
             ["Commercial Auto Liability", CAR_MUT_COI, POL_AUTO_SHORT, "$1,000,000 CSL"],
             ["Employers Liability", "Not Scheduled", "-", "-"]])
    d.para("Employers Liability is not scheduled: the named insured carries no workers "
           "compensation policy.")

    # Page 8 - one page naming all four contracts beside form references.
    d.page("SCHEDULE OF FORMS AND ENDORSEMENTS", "All policies in this package")
    d.table(["POLICY", "FORM", "TITLE"],
            [[POL_IM, "CM7000A 03-20", "Inland Marine Declarations"],
             [POL_IM, FORM_AAIS, "Installation Floater Coverage"],
             [POL_CPP, FORM_ISO_CGL, "Commercial General Liability Coverage Form"],
             [POL_CPP, FORM_HNOA, "Hired and Non-Owned Auto Liability"],
             [POL_CPP, "CP 00 10 10 12", "Building and Personal Property Coverage Form"],
             [POL_AUTO, FORM_AUTO_DEC, "Business Auto Declarations"],
             [POL_AUTO, "CA 00 01 11 20", "Business Auto Coverage Form"],
             [POL_UMB, "CU7000 11-15", "Commercial Umbrella Declarations"],
             [POL_UMB, FORM_UMB_SCHED, "Schedule of Underlying Insurance"],
             ["ALL", "IL 00 17 11 98", "Common Policy Conditions"]])

    # Page 9 - carrier loss run: prior numbers WITH dates (the dec prints them
    # without dates on RENEWAL OF lines).
    d.page("LOSS RUN REPORT", "Valued as of 02/01/2026", header=(BRAND,))
    d.row("NAMED INSURED", A_INSURED)
    d.row("ACCOUNT NUMBER", A_ACCOUNT)
    d.head("POLICY SUMMARY")
    d.table(["POLICY NUMBER", "LINE", "COMPANY", "TERM", "CLAIMS", "PAID"],
            [[POL_AUTO, "Commercial Auto", CAR_MUT, "01/01/2026-01/01/2027", "0", "$0"],
             [POL_AUTO_PRIOR, "Commercial Auto", CAR_MUT, "01/01/2025-01/01/2026", "1", "$7,420"],
             [POL_CPP_PRIOR, "General Liability", CAR_PC, "01/01/2025-01/01/2026", "0", "$0"],
             [POL_CPP_PRIOR2, "General Liability", CAR_PC, "01/01/2024-01/01/2025", "1", "$12,950"],
             [POL_UMB_PRIOR, "Commercial Umbrella", CAR_MUT, "03/15/2025-03/15/2026", "0", "$0"]])
    d.head("CLAIM DETAIL")
    d.table(["CLAIM NUMBER", "POLICY NUMBER", "DATE OF LOSS", "DESCRIPTION", "STATUS", "PAID"],
            [["AU-25-11873", POL_AUTO_PRIOR, "06/14/2025", "Rear-end collision, vehicle 1",
              "Closed", "$7,420"],
             ["GL-24-00419", POL_CPP_PRIOR2, "09/03/2024", "Property damage at job site",
              "Closed", "$12,950"]])
    d.row("TOTAL PAID", "$20,370")
    d.row("TOTAL OPEN RESERVES", "$0")
    d.save()


# ── File 2 - a PROJECT certificate: a second, real GL policy ────────────────

def build_file2(path):
    d = _Doc(path)
    d.page("CERTIFICATE OF LIABILITY INSURANCE", "DATE (MM/DD/YYYY): 02/10/2026")
    d.para("THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY AND CONFERS NO RIGHTS "
           "UPON THE CERTIFICATE HOLDER.", size=8)
    d.row("PRODUCER", f"{AGENCY}, 1550 Wewatta St, Denver, CO 80202")
    d.row("CONTACT", f"{AGENT}      PHONE: {AGENCY_PHONE}")
    d.row("INSURED", f"{A_INSURED_MIXED}, {A_ADDR}")
    d.head("INSURER(S) AFFORDING COVERAGE")
    d.table(["INSURER", "NAME", "NAIC #"],
            [["INSURER A", RIVAL_CARRIER_COI, RIVAL_NAIC],
             ["INSURER B", CAR_MUT_COI, NAIC_MUT],
             ["INSURER C", CAR_SPEC_COI, NAIC_SPEC]])
    d.row("CERTIFICATE NUMBER", "2026-00731")
    d.row("REVISION NUMBER", "1")
    d.head("COVERAGES")
    d.table(["INSR LTR", "TYPE OF INSURANCE", "POLICY NUMBER", "POLICY EFF", "POLICY EXP", "LIMITS"],
            [["A", "COMMERCIAL GENERAL LIABILITY - OCCUR", POL_RIVAL_GL, "01/01/2026",
              "01/01/2027", "EACH OCC $1,000,000"],
             ["B", "AUTOMOBILE LIABILITY - ANY AUTO", POL_AUTO_SHORT, "01/01/2026",
              "01/01/2027", "CSL $1,000,000"],
             ["B", "UMBRELLA LIAB - OCCUR", POL_UMB_SHORT, "03/15/2026",
              "03/15/2027", "EACH OCC $2,000,000"],
             ["", "WORKERS COMPENSATION", "NONE", "", "", ""],
             ["C", "CONTRACTORS EQUIPMENT", POL_IM_SHORT, "01/01/2026",
              "01/01/2027", "SCHEDULED $185,000"]])
    d.head("DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    d.para(f"Project: {AI_HOLDER} parking structure. General liability for work on this project "
           f"is provided under project policy {POL_RIVAL_GL}. Umbrella policy {POL_UMB_SHORT} "
           f"follows form over the policies above.")
    d.head("CERTIFICATE HOLDER")
    d.para(f"{AI_HOLDER}, 900 Larkspur Ct, Denver, CO 80223")
    d.head("CANCELLATION")
    d.para("Should any of the above described policies be cancelled before the expiration "
           "date thereof, notice will be delivered in accordance with the policy provisions.",
           size=8)
    d.save()


# ── File 3 - one printed number, three separate policies ────────────────────

def build_file3(path):
    d = _Doc(path)
    d.page("RENEWAL PREMIUM SUMMARY", "Policy Declarations Summary - Renewal",
           header=(D_CARRIER.upper(),))
    d.row("NAMED INSURED", D_INSURED)
    d.row("MAILING ADDRESS", D_ADDR)
    d.row("POLICY NUMBER", D_NUMBER)
    d.row("POLICY PERIOD", "08/01/2026 to 08/01/2027")
    d.row("BUSINESS DESCRIPTION", "Commercial landscape installation and maintenance")
    d.row("AGENT", "Clear Creek Insurance Services")
    d.head("COVERAGES ON THIS RENEWAL")
    d.table(["COVERAGE", "LIMIT", "PREMIUM"],
            [["Commercial General Liability", "$1,000,000 / $2,000,000", "$5,210.00"],
             ["Commercial Auto", "$1,000,000 CSL", "$3,880.00"],
             ["Commercial Umbrella", "$2,000,000", "$2,150.00"]])
    d.row("TOTAL RENEWAL PREMIUM", "$11,240.00")
    d.gap()
    d.para("Each coverage above is issued as a separate policy. Individual policy numbers are "
           "shown on each policy's own declarations, which are not included in this summary.")
    d.save()


FILES = [
    # (file name, builder, document type it must classify as)
    (F1, build_file1, "dec_page"),
    (F2, build_file2, "certificate"),
    (F3, build_file3, "dec_page"),
]


# ── Self-check: read the PDFs the way the live pipeline reads them ──────────

def _live_text(path):
    """The native-text half of `ocr_service.extract_text_from_pdf`, page markers
    included - the text extraction and the gap-fill page scopes actually see."""
    try:
        from services.ocr_service import _pdfplumber_extract_pages_structured
        pages = _pdfplumber_extract_pages_structured(path)
    except Exception as exc:                                  # noqa: BLE001
        print(f"  ! pipeline extractor unavailable ({exc}) - using plain pdfplumber")
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = [(p.extract_text() or "", "") for p in pdf.pages]
    parts = []
    for i, (text, tables) in enumerate(pages):
        if len(pages) > 1 and (text.strip() or tables):
            parts.append(f"[Document page {i + 1}]")
        if text.strip():
            parts.append(text)
        if tables:
            parts.append(tables)
    return "\n".join(parts)


def _verify(paths):
    sys.path.insert(0, BACKEND)
    import logging
    logging.disable(logging.CRITICAL)
    texts = {name: _live_text(paths[name]) for name, _b, _t in FILES}
    t1, t2, t3 = texts[F1], texts[F2], texts[F3]
    problems = []

    def need(name, *vals):
        for v in vals:
            if v not in texts[name]:
                problems.append(f"{name}: MISSING {v!r}")

    def forbid(name, *vals):
        for v in vals:
            if v in texts[name]:
                problems.append(f"{name}: must NOT contain {v!r}")

    need(F1, A_INSURED, BRAND, CAR_PC.upper(), CAR_MUT.upper(), CAR_SPEC.upper(), CAR_SPEC,
         CAR_PC_ABBR, CAR_MUT_COI, NAIC_PC, POL_CPP, POL_CPP_SHORT, POL_CPP_PRIOR,
         POL_CPP_PRIOR2, POL_AUTO, POL_AUTO_SHORT, POL_AUTO_PROSE, POL_AUTO_PRIOR, POL_UMB,
         POL_UMB_SHORT, POL_UMB_PRIOR, POL_IM, POL_IM_SHORT, POL_UMB_OLDEST, OLD_UMB_CARRIER,
         FORM_AAIS, FORM_ISO_CGL, FORM_AUTO_DEC, FORM_UMB_SCHED, FORM_HNOA, LOAN_NO,
         SERIAL_TRAP, CONTRACT_TRAP, A_ACCOUNT, "Workers Compensation", "No Coverage",
         "Employers Liability", "Not Scheduled", "Hired and Non-Owned Auto Liability",
         "EFF DATE: 03/15/26", "not part of package policy", "AU-25-11873", "GL-24-00419")
    # Page 1 is the live shape: no carrier, no NAIC, and exactly ONE policy
    # number - the correspondence note's prose printing.
    page1 = t1.split("[Document page 2]")[0]
    for v in (POL_CPP, POL_CPP_SHORT, POL_AUTO, POL_AUTO_SHORT, POL_UMB, POL_IM, CAR_MUT,
              CAR_PC, CAR_SPEC, CAR_MUT.upper(), CAR_PC.upper(), CAR_SPEC.upper(), NAIC_PC,
              NAIC_MUT, NAIC_SPEC):
        if v in page1:
            problems.append(f"file 1 page 1: must NOT contain {v!r} (breaks the live page-1 shape)")
    if page1.count(POL_AUTO_PROSE) != 1:
        problems.append("file 1 page 1: the correspondence note must print the auto number once")
    # NAICs of the Mutual and Specialty entities print ONLY on the certificate;
    # the rival GL policy exists ONLY on the certificate.
    forbid(F1, NAIC_MUT, NAIC_SPEC, RIVAL_NAIC, POL_RIVAL_GL, "Larchmont")
    if t1.count(POL_CPP) < 5:
        problems.append("file 1: the package number must print against BOTH coverage parts")

    need(F2, RIVAL_CARRIER_COI, RIVAL_NAIC, POL_RIVAL_GL, CAR_MUT_COI, NAIC_MUT, CAR_SPEC_COI,
         NAIC_SPEC, POL_AUTO_SHORT, POL_UMB_SHORT, POL_IM_SHORT, "03/15/2027",
         "WORKERS COMPENSATION", "NONE", AI_HOLDER)
    forbid(F2, POL_AUTO, POL_CPP, POL_CPP_SHORT, CAR_PC, NAIC_PC, POL_IM)

    need(F3, D_NUMBER, "Commercial General Liability", "Commercial Auto", "Commercial Umbrella",
         "separate policy")
    if t3.count(D_NUMBER) != 1:
        problems.append("file 3: exactly ONE policy number may print - that is the whole test")

    for name, text in texts.items():
        for fused in ("LiabilityQuillon", "Co.QPC", "Co.4A8", "Co.LSG", "CoverageNo",
                      "CompensationNo", "CompensationNONE", "PartQPC", "FloaterIM",
                      "LiabilityLarchmont", "EquipmentQuillon"):
            if fused in text:
                problems.append(f"{name}: column collision {fused!r}")

    try:
        from services.extraction_service import classify_document
        for name, _builder, want in FILES:
            got = classify_document(texts[name], name).get("doc_type")
            if got != want:
                problems.append(f"{name}: classifies as {got!r}, needs {want!r}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  ! document-role self-check skipped ({exc})")

    # Informational, never a failure: is the carrier-truncation trap still armed?
    try:
        try:
            from services.extraction_service import _header_carrier_name   # 17 Sep fix
            got = (_header_carrier_name(IM_HEADER_LINE) or "").strip(" ,*") or None
        except ImportError:
            from services.extraction_service import _HEADER_CARRIER_RE
            m = _HEADER_CARRIER_RE.match(IM_HEADER_LINE)
            got = m.group(1).strip(" ,*") if m else None
        state = ("ARMED - the header binder cuts it to "
                 f"{got!r}" if got == CAR_SPEC_TRUNCATED
                 else f"DISARMED - the header binder now reads {got!r} (fixed?)")
        print(f"  carrier-name trap: {state}")
    except Exception:                                         # noqa: BLE001
        pass

    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("   -", p)
        return False
    print("  self-check passed (content, page-1 shape, no fused cells, document roles)")
    return True


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = {}
    for name, builder, _want in FILES:
        path = os.path.join(OUT_DIR, name)
        builder(path)
        paths[name] = path
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(README)
    print(f"wrote {OUT_DIR}")
    for name, _b, _t in FILES:
        print(f"   {name:38s} {os.path.getsize(paths[name]):>7,} bytes")
    print("   README-HOW-TO-TEST.md")
    stale = sorted(f for f in os.listdir(OUT_DIR)
                   if f.lower().endswith(".pdf") and f not in {n for n, _b, _t in FILES})
    if stale:
        print(f"  ! stale PDFs from an older version of this kit are still in the folder: {stale}")
    ok = _verify(paths)
    sys.exit(0 if ok else 1)


README = f"""# Policy number by line - live test kit (3 files, 2 uploads)

Built 17 Sep 2026 for the client's question: *"a single policy number is still
trying to be represented across all - was this corrected?"*

| Upload | Files (together) | Insured |
|---|---|---|
| **1** | `{F1}` + `{F2}` | {A_INSURED} |
| **2** | `{F3}` alone, in a SECOND new session | {D_INSURED} |

## 0. RETEST AFTER THE 17 SEP FIXES - START HERE

The first live run (17 Sep) came back as 7 blank PDFs (pikepdf, fixed) and, read
from the stored session data: upload 1 passed on policy numbers but blanked
General Liability everywhere and printed the umbrella's PRIOR carrier as its
current one; upload 2 printed `{D_NUMBER}` on every line. All fixed; every value
below is measured by replaying that run's own extraction through the fixed code
(`backend/tests/test_policy_by_line_live_kit_17sep.py`).

**Restart the backend first** (`uvicorn --reload` picks the files up, but restart
to be sure), then run the same short run: upload 1 -> ACORD **125, 126, 131, 25**;
upload 2 -> ACORD **126, 131, 25**.

**Retest 1 (17 Sep, pre-form review):** upload 1 matched R2-R4. Upload 2's session
was merged with a gap - the extraction numbered at most one row, and the per-line
fill copied `SRC-4410982` onto Commercial Auto and Umbrella after the withhold ran.
Fixed (the withhold now reads the rows AND the per-line index). **Upload 2 must be
uploaded again in a NEW session** - a session's facts are merged at upload, and
generating forms on the old session reuses them. Any of the three General
Liability cards (policy number, carrier or NAIC) now chooses the same policy.
The Inland Marine Total Value card and the Builders Risk warning depend on the
extraction and may or may not appear on a given upload.

### Upload 1 - pre-form screen, answer nothing

| # | Where | Expected now |
|---|---|---|
| R1 | Downloaded PDF | values are printed (not a blank template) |
| R2 | Policy Number card | **"two policies on the same coverage line (general liab)"**, offering `{POL_CPP}` vs `{POL_RIVAL_GL}`, button **Confirm for general liab** |
| R3 | Carrier and Carrier NAIC cards | the same General Liability question: {CAR_PC} vs {RIVAL_CARRIER_COI}; 91880 vs {RIVAL_NAIC} |
| R4 | Policies in this submission | Auto {CAR_MUT} / {NAIC_MUT} / `{POL_AUTO}`; **two** General Liability rows - {CAR_PC} / {NAIC_PC} / `{POL_CPP}` and {RIVAL_CARRIER_COI} / {RIVAL_NAIC} / `{POL_RIVAL_GL}`; Inland Marine **{CAR_SPEC}** / {NAIC_SPEC} / `{POL_IM}`; Property {CAR_PC} / {NAIC_PC} / `{POL_CPP}`; Umbrella **{CAR_MUT}** / `{POL_UMB}` (NAIC may show a dash); no Workers Comp row; **no Birchline anywhere** |
| R5 | ACORD 126 | POLICY NUMBER, CARRIER, NAIC **blank** - General Liability is the open question |
| R6 | ACORD 131 | CARRIER {CAR_MUT} / NAIC {NAIC_MUT} / `{POL_UMB}`; EXPIRING POL # `{POL_UMB_PRIOR}`; underlying Auto `{POL_AUTO}`; underlying GL number blank (two GL policies) |
| R7 | ACORD 25 | Auto `{POL_AUTO}` **with** 01/01/2026 - 01/01/2027; Excess `{POL_UMB}` 03/15/2026 - 03/15/2027; GL row number **and** INSR LTR blank; insurer list {CAR_PC} 91880, {CAR_SPEC} {NAIC_SPEC}, {CAR_MUT} **{NAIC_MUT}** - Auto and Excess lettered to {CAR_MUT} |
| R8 | ACORD 125 page 1 / prior carrier grid | carrier, NAIC, policy number blank; 2025 row: `{POL_CPP_PRIOR}`, `{POL_AUTO_PRIOR}`, `{POL_UMB_PRIOR}` each beside its own dates |
| R9 | Pre-download review | **no** policy-number rows and **no** "Policy EffectiveDate ... source value" rows |
| R10 | Send to Client, then re-download 126 / 131 / 25 | nothing changes |

### Upload 1 - then confirm `{POL_RIVAL_GL}` for General Liability and regenerate

| # | Expected now |
|---|---|
| R11 | the three General Liability cards clear |
| R12 | ACORD 126: `{POL_RIVAL_GL}` / {RIVAL_CARRIER_COI} / {RIVAL_NAIC} |
| R13 | ACORD 25 GL row: `{POL_RIVAL_GL}`, lettered to {RIVAL_CARRIER_COI} (seated with {RIVAL_NAIC}) |
| R14 | nothing else moved: 131, 25 Auto / Excess, Property row `{POL_CPP}` |

(Confirming `{POL_CPP}` instead gives 126 `{POL_CPP}` / {CAR_PC} / 91880 and takes {RIVAL_CARRIER_COI} off the certificate.)

### Upload 2 - `{F3}` alone

| # | Where | Expected now |
|---|---|---|
| R15 | ACORD 126 / 131 POLICY NUMBER | **blank** - the page says each coverage is a separate policy |
| R16 | ACORD 131 underlying GL and Auto rows | policy number **blank** |
| R17 | ACORD 25 GL / Auto / Excess rows | policy number **blank**; carrier {D_CARRIER.upper()} lettered A |
| R18 | Carrier on 126 / 131 | {D_CARRIER.upper()} |

**Known and not in this fix** (report, don't count as a regression):
the "Policy number" / carrier questions in the client questionnaire still write a
package-level answer that does not land on a per-line form box; the Inland Marine
Total Value card ($235,000 is the LLM's sum of two floaters); the "Umbrella
effective date ... 03/15/2024" and "Builders Risk requires a project value"
warnings; "Lines of business differ" listing No Coverage lines.

Sections 1-6 below are the ORIGINAL measurements against the 16 Sep and 9 Sep
builds, kept as the before picture.

### Short run - 4 forms + 3 forms (measured on both builds)

| Upload | Generate only | Given up |
|---|---|---|
| 1 | ACORD **125, 126, 131, 25** | 127 / 137 CO (auto is still checked on 131's underlying row and 25's auto row), 140 (the shared-number control - still visible as the Property row of the policies table), 101 (FOUND-2), 141 / 130 (no-coverage blanks), 138 CO (identity map; the carrier truncation still shows on 25's insurer list) |
| 2 | ACORD **126, 131, 25** | 125 and 127 - 131 alone shows the one number on three lines |

On the short run F3 reads: 16 Sep = exactly **1** Field QA row (ACORD 126, `{POL_CPP}`
vs `{POL_CPP_SHORT}`); 9 Sep = **6-7** rows. For F2 re-download 125 and 131: 9 Sep
writes `{POL_AUTO}` into 125's policy number and `{POL_UMB_OLDEST}` into 131's
EXPIRING POL #. Checks that still apply: P1-P8, G1, G3-G5, G9-G15, G17, L1, C1-C2,
D1-D4.

**Before anything else:** download one generated form. If it is a blank
template, the environment cannot fill PDFs (on this Mac's `backend/.venv`,
pikepdf 9.3.0 has no `pikepdf.Boolean`, so `fill_pdf` returns the unfilled
template). Nothing below means anything on blank PDFs.

Every "Measured" value below comes from replaying these exact PDFs offline
through the real merge, stamper, Send-to-Client late-stamp, Field QA and Data
Consistency code, on the current build (16 Sep, `a8e6407`) and the 9 Sep build
(`162bfbd`). Section 6 says how, and what the live run can legitimately change.

---

## 1. IS THE 16 SEP FIX DEPLOYED? (upload 1)

The Data Consistency card is **not** a fingerprint in this kit - both builds show
the same package-wide question (see NEW-A). Use these instead:

| # | Where | 16 Sep build | 9 Sep build |
|---|---|---|---|
| F1 | ACORD 125 page 1, right after generating | CARRIER **blank**; "other insurance with this company" list **blank** | CARRIER `{CAR_MUT.upper()}`; the list shows 3-4 policy numbers (sometimes a bare `-`) |
| F2 | Click **Send to Client**, then re-download ACORD 125, 101 and 141 | **nothing changes** - POLICY NUMBER stays blank on all three | `{POL_AUTO}` appears on all three - including ACORD 141, a line with **No Coverage** - beside NAIC `{NAIC_PC}` |
| F3 | Pre-download review (Field QA) | **2-3** policy-number rows (3 when ACORD 137 CO is generated), and each compares two printings of the SAME policy (`{POL_CPP}` vs `{POL_CPP_SHORT}`; `{POL_AUTO}` vs `{POL_AUTO_SHORT}`) | **9-11** rows where ANOTHER line's number is "expected", e.g. *ACORD 131 shows `{POL_UMB}` but the source value is `{POL_AUTO}`* |
| F4 | supporting | Data Consistency never offers a form number | may offer `{FORM_AAIS}` as a policy-number choice |
| F5 | supporting | ACORD 25 Workers Comp row blank | may print `{POL_UMB}` on the Workers Comp row |

F1-F3 all left = 16 Sep build. Any of them right = pre-16-Sep build: stop, redeploy.

---

## 2. UPLOAD 1 - the package, the project certificate, every trap

### Truth

| Line | Carrier | NAIC | Current policy (all printings = one contract) | Term |
|---|---|---|---|---|
| General Liability | {CAR_PC} | {NAIC_PC} | `{POL_CPP}` = `{POL_CPP_SHORT}` - **a package policy shared with Property** | 01/01/2026-01/01/2027 |
| Commercial Property | {CAR_PC} | {NAIC_PC} | `{POL_CPP}` (same package policy) | 01/01/2026-01/01/2027 |
| Business Auto | {CAR_MUT} | {NAIC_MUT} | `{POL_AUTO}` = `{POL_AUTO_SHORT}` = `{POL_AUTO_PROSE}` | 01/01/2026-01/01/2027 |
| Umbrella | {CAR_MUT} | {NAIC_MUT} | `{POL_UMB}` = `{POL_UMB_SHORT}` | **03/15/2026-03/15/2027** |
| Inland Marine | **{CAR_SPEC}** | {NAIC_SPEC} | `{POL_IM}` = `{POL_IM_SHORT}` | 01/01/2026-01/01/2027 |
| Crime / Workers Comp | - | - | **No Coverage** | - |
| **Project GL (certificate only)** | {RIVAL_CARRIER} | {RIVAL_NAIC} | `{POL_RIVAL_GL}` - a SECOND real GL policy | 01/01/2026-01/01/2027 |

Prior terms: `{POL_CPP_PRIOR}`, `{POL_CPP_PRIOR2}`, `{POL_AUTO_PRIOR}`, `{POL_UMB_PRIOR}`;
the umbrella before that: {OLD_UMB_CARRIER} `{POL_UMB_OLDEST}`.

**Rule for every policy-number box:** its own line's number (any printing) or
blank. FAIL = another line's number, a `-25`/`-24` number in a current box, a form
number (`{FORM_AAIS}`, `{FORM_ISO_CGL}`, `{FORM_AUTO_DEC}`, `{FORM_UMB_SCHED}`,
`{FORM_HNOA}`), or an identifier shaped like one (`{SERIAL_TRAP}`, `{LOAN_NO}`,
`{A_ACCOUNT}`, `{CONTRACT_TRAP}`, `NONE`).

### Traps in these two files

| Trap | Attacks |
|---|---|
| Page 1: lines + premiums only, group brand `{BRAND}`, and ONE number in a correspondence note (`{POL_AUTO_PROSE}`) | the live Orbin page-1 shape; the single-number push |
| Workers Comp "No Coverage" row right above the inland marine page | run 11 phantom WC |
| Three near-identical carrier entities; the inland marine one is an "Insurance **Company**" | family-key fusion; header carrier truncation |
| GL + Property on ONE package number | over-refusal (140 must fill) |
| Hired and Non-Owned Auto Liability printed on the package page | an auto-looking line carrying the package number |
| Auto page: "not part of package policy `{POL_CPP}`" | a body sentence naming another contract |
| `RENEWAL OF` prior numbers in current page headers; a loss run with the same priors dated | prior term in a current box; prior-grid row alignment |
| Umbrella's schedule of underlying insurance (`{CAR_PC_ABBR}`, `{POL_CPP_SHORT}`, `{POL_AUTO_SHORT}`, "Employers Liability - Not Scheduled") | run 8 polluted index; P&C abbreviation; phantom EL row |
| AAIS / ISO / carrier form numbers beside policy numbers; a forms schedule naming four contracts | form number as policy number |
| Certificate: project GL policy from another carrier, compressed printings, `NONE` on Workers Comp | the must-ask case; printing folds; phantom WC |

### Step 1 - pre-form screen (Data Consistency)

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| P1 | Policy Number card | a question scoped to **General Liability only**: `{POL_CPP}` vs `{POL_RIVAL_GL}` | **FAIL - NEW-A.** Package-wide *"these values could not be matched to a coverage line - confirm which applies"*, offering `{POL_AUTO}` vs `{POL_RIVAL_GL}`, with a plain **Confirm** button. 9 Sep: the same |
| P2 | Policies in this submission - Auto row | {CAR_MUT} / {NAIC_MUT} / `{POL_AUTO}` | **FAIL - NEW-A.** No policy number; carrier {CAR_PC} (or {CAR_SPEC}) with NAIC {NAIC_PC} |
| P3 | Policies table - General Liability | `{POL_CPP}` (and the project policy flagged) | **FAIL - NEW-A.** No policy number |
| P4 | Policies table - Property | {CAR_PC} / {NAIC_PC} / `{POL_CPP}` | PASS |
| P5 | Policies table - Umbrella | {CAR_MUT} / {NAIC_MUT} / `{POL_UMB}` | PASS (on the Orbin-shaped extraction the carrier reads {CAR_SPEC}) |
| P6 | Policies table - Inland Marine | {CAR_SPEC} / {NAIC_SPEC} / `{POL_IM}` | **FAIL - FOUND-6.** `{CAR_SPEC_TRUNCATED}`, NAIC blank |
| P7 | Policies table - row count | 5 lines (GL, Property, Auto, Umbrella, Inland Marine), no Workers Comp | **FAIL - FOUND-1.** A Workers Comp row numbered `{POL_UMB}` |
| P8 | Any card | no form number, serial, loan, account or contract number offered as a policy number | PASS |

### Step 2 - generate without answering anything

Select **ACORD 101, 125, 126, 127, 131, 25** (+ 137 CO if offered), then **add
140, 141, 130 and 138 CO manually**.

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| G1 | ACORD 126 POLICY NUMBER | `{POL_CPP}` or blank - never `{POL_RIVAL_GL}`, `{POL_AUTO}`, `{POL_UMB}`, `{POL_IM}` | `{POL_CPP}` (printed while the GL question is still open - record) |
| G2 | ACORD 127 / 137 CO POLICY NUMBER | `{POL_AUTO}` - never `{POL_CPP}` (hired-auto trap, body sentence), never `{POL_AUTO_PRIOR}` | `{POL_AUTO}` |
| G3 | ACORD 131 POLICY NUMBER | `{POL_UMB}` | `{POL_UMB}` |
| G4 | ACORD 131 underlying Auto / GL rows | Auto: `{POL_AUTO_SHORT}` printing + Mutual; GL: `{POL_CPP_SHORT}` printing + P&C | both PASS |
| G5 | ACORD 131 Employers Liability row and EXPIRING POL # | both blank | blank |
| G6 | **ACORD 140** POLICY NUMBER / CARRIER / NAIC | `{POL_CPP}` / {CAR_PC} / {NAIC_PC} - **blank here is over-refusal** | PASS |
| G7 | ACORD 141 (Crime) and ACORD 130 (Workers Comp) | no policy number anywhere | blank |
| G8 | ACORD 138 CO | blank - no garage / dealers policy exists | **FAIL** - `{POL_IM}` (identity map still says inland marine) with carrier `{CAR_SPEC_TRUNCATED}` (FOUND-6) |
| G9 | ACORD 25 GL row | blank or `{POL_CPP}` while GL is contested | blank |
| G10 | ACORD 25 Auto row | `{POL_AUTO}` | **FAIL - NEW-A.** blank |
| G11 | ACORD 25 Excess row | `{POL_UMB}`, 03/15/2026 - 03/15/2027 | PASS |
| G12 | ACORD 25 Workers Comp row | blank | blank |
| G13 | ACORD 25 insurer roster | each company once, full legal name, own NAIC | **FAIL - FOUND-6.** `{CAR_SPEC_TRUNCATED}` without NAIC; on the Orbin-shaped extraction the same company is listed twice |
| G14 | ACORD 125 page 1 POLICY NUMBER / CARRIER | blank / blank | blank / blank |
| G15 | ACORD 125 prior carrier grid | GL column only `{POL_CPP_SHORT}` numbers, Auto only `4A8-21-07` numbers, `{POL_UMB_OLDEST}` only under OTHER, each number on the SAME row as its dates | **FAIL - FOUND-3.** Row A holds the 2025 numbers without dates; row B holds their dates without numbers |
| G16 | ACORD 101 POLICY NUMBER / CARRIER | blank / blank (several policies, several carriers) | blank / **FAIL - FOUND-2** `{CAR_MUT.upper()}` |
| G17 | Field QA list | no policy-number rows | **FAIL - NEW-C.** 2-3 rows, each comparing two printings of one policy |

### Step 3 - Send to Client, then re-download 125, 101, 126, 127, 131, 140, 141

| # | Correct | Measured, 16 Sep |
|---|---|---|
| L1 | Nothing changes on any of them | PASS (9 Sep: `{POL_AUTO}` on 125 / 101 / 141, and {CAR_MUT.upper()} and/or `{NAIC_PC}` written into the carrier / NAIC boxes of the section forms) |

### Step 4 - answer the Policy Number card

The card only offers a plain **Confirm** (NEW-A). Choose `{POL_RIVAL_GL}`,
confirm, and generate again.

| # | Correct | Measured, 16 Sep |
|---|---|---|
| C1 | The answer is applied to General Liability only: 126 and the ACORD 25 GL row print `{POL_RIVAL_GL}` with {RIVAL_CARRIER} / {RIVAL_NAIC} | **FAIL - NEW-B.** The card reads "confirmed" and no form changes: 126 keeps `{POL_CPP}`, the 25 GL row stays blank |
| C2 | No other line takes `{POL_RIVAL_GL}` | PASS - 127 / 131 / 140 / 138 unchanged, nothing sprayed |

---

## 3. UPLOAD 2 - one printed number, three separate policies

New session, `{F3}` alone. Select **ACORD 125, 126, 127, 131, 25**. The page
prints ONE number, `{D_NUMBER}`, never says which line owns it, and states
*"Each coverage above is issued as a separate policy."*

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| D1 | ACORD 126 / 127 / 131 POLICY NUMBER | blank (or a question) | **FAIL - FOUND-7.** `{D_NUMBER}` on all three (9 Sep: same) |
| D2 | ACORD 131 underlying GL and Auto rows | blank | **FAIL.** `{D_NUMBER}` - the umbrella claims its underlying policies share its own number |
| D3 | ACORD 25 GL / Auto / Excess rows | blank | **FAIL.** `{D_NUMBER}` on all three (9 Sep left them blank when the rows carried no number) |
| D4 | Data Consistency | a question | **FAIL.** "consistent" |
| D5 | ACORD 125 page 1 POLICY NUMBER after Send to Client | blank | PASS (9 Sep: `{D_NUMBER}` - another F2 fingerprint) |
| D6 | Carrier on 126 / 127 / 131 | {D_CARRIER} | PASS - one carrier, borrowed correctly |

**Upload 2 is the surviving live form of the client's complaint** for a summary,
proposal, binder or invoice that prints one number for several lines.

---

## 4. What the replay found - current code, none of it fixed

| ID | Defect | Seen at | Root cause, isolated input by input | Builds |
|---|---|---|---|---|
| **NEW-A** | A package policy + hired auto on the package page + a project GL certificate turn the Policy Number question package-wide ("confirm which applies", Auto number vs project GL), strip the Auto and GL numbers from the policies table, give Auto the wrong carrier, and blank the ACORD 25 Auto row | P1-P3, G10 | (1) the hired/non-owned auto dec entry, printed under a PACKAGE heading that names no single line, is indexed under Auto with the package number, so Auto looks like two contracts - drop that one entry and Auto recovers; (2) a number shared by GL + Property is scoped to Property only, so GL has no number of its own, the two GL policies never collide, and with the project certificate both documents' numbers become unplaceable - a package-wide question. Give Property its own number AND drop the hired-auto entry, and the card correctly asks about GL only | both |
| **NEW-B** | A package-wide confirmation is accepted and discarded - "confirmed", no form changes | C1 | the confirmation lands only in the flat `policy_number`, which no section resolver reads any more | current |
| **NEW-C** | Field QA flags the same policy printed two ways | G17 | the checker compares the owning resolver's raw printing (`{POL_CPP_SHORT}`, `{POL_AUTO_SHORT}`) with the stamped canonical printing | current |
| FOUND-1 | Phantom Workers Comp policy numbered with the umbrella's number | P7 | "Employers Liability - Not Scheduled" on the umbrella schedule; "Not Scheduled" is not read as a denial (run 11 handled only "No Coverage") | current |
| FOUND-2 | ACORD 101 prints one carrier on a multi-carrier package | G16 | no resolver owns `Insurer_FullName_A` on 101 | both |
| FOUND-3 | Prior carrier grid splits one prior policy across two rows | G15 | the same prior policy arrives undated (`RENEWAL OF`) and dated (loss run) | both |
| FOUND-6 | Any "... Insurance Company" carrier is cut to "... Insurance" and loses its NAIC; the certificate can list the company twice | P6, G8, G13 | `_HEADER_CARRIER_RE` matches lazily and stops at the FIRST "INSURANCE" | current (regression from the 14 Sep header binding) |
| FOUND-7 | One printed number spreads to every line, certificate rows included | D1-D4 | the per-line fill attributes the page's only number to every line printed on it | both; current also fills the certificate |
| 138 | ACORD 138 (Garage and Dealers) prints the inland marine policy | G8 | `_SECTION_FORM_LINE_PHRASES` still maps 138 to contractors equipment / inland marine | both |

**Measured offline, not reachable with this kit:** two defects in the GL-scoped
confirmation - a number-only confirmation recombines the row (the other company's
name with this company's NAIC, on ACORD 25 too), and a section header can ignore
the confirmed number when the dec index names one. The UI only offers the scoped
confirm when the card is already scoped to one line, and NEW-A turns it
package-wide first.

**Side observations, no box affected here:** the header binder refuses a page whose
header matches two contracts (numbers sharing digit blocks, or a `RENEWAL OF`
line), and a group-brand header can vote as a carrier ("QUILLON INSURANCE") on a
page whose first lines name one contract.

---

## 5. What to send back

For every check: PASS / FAIL / not seen, plus the literal value for any FAIL.
Screenshots: the Data Consistency panel (card + policies table), the pre-download
review list, ACORD 125 page 1 and its prior carrier grid, 126 / 127 / 131 page 1
plus 131's underlying schedule, 140, 138, 25, 101 - before and after Send to
Client.

## 6. How the expectations were measured

`backend/scripts/make_policy_by_line_test_pdfs.py` builds these PDFs and
self-checks them through the pipeline's own text extractor and document
classifier. The measured values come from running that real PDF text through
`merge_facts` -> `map_facts_to_form` -> the Send-to-Client late-stamp -> Field QA ->
the Data Consistency card, on both builds, with extraction output modelled three
ways (page-1 rows handed the next page's number as on the live Orbin runs,
handed the correspondence note's number, and clean). Outcomes were the same
across all three unless a row says otherwise.

**The live extraction will differ.** A box that comes back BLANK where the
replay filled it is usually an extraction miss - check the policies table first.
A box that shows ANOTHER line's number is a real failure whatever extraction did.
"""


if __name__ == "__main__":
    main()
