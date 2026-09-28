"""make_orbin_retest_pdfs.py - live kit: the client's REAL Orbin submission, rebuilt.

    backend/.venv/bin/python backend/scripts/make_orbin_retest_pdfs.py

Writes orbin_retest_kit/ at the repo root: three PDFs uploaded together as ONE
package, plus README-HOW-TO-TEST.md. Offline and free - no database, no
network, no LLM call. The self-check at the bottom re-reads every PDF with
plain pdfplumber AND with the pipeline's own text extractor.

WHY THIS KIT EXISTS
-------------------
Michelle's 11 items (the client's 11 Sep audit, `11sep-form-improvement.md`)
were each fixed and replayed offline against session e7084347. Every earlier
live kit was a synthetic insured (HALVORSEN, BRAMBLE & STONE); none of them had
the client's actual shapes. This one does - the 271-page EMC package condensed
to the pages that carry a value plus the boilerplate that set the traps, the
certificate with its run-together OCR, and a narrative that names the old
broker and no new one. It must be uploaded as THREE files: several rules key on
each document's type (certificate vs dec page vs narrative), and a file carries
exactly one type.

THE THREE FILES (one upload)
----------------------------
  1_policy_package.pdf   EMC "Package Policy", 49 pages, text-based. Common
                         declarations + Inland Marine + Business Auto + Umbrella
                         + General Liability, in the real order, printed the way
                         the real OCR shows them.
  2_certificate.pdf      ACORD 25 look-alike dated 07/28/2025 whose key strings
                         are drawn with no space glyphs, so pdfplumber returns
                         them run-together exactly like the client's COI OCR.
  3_narrative.pdf        One-page underwriting narrative. Names the OLD broker in
                         passing, names NO new agency, the Subaru without a VIN,
                         the umbrella at $1,000,000, no losses in 5 years.

WHAT EACH TRAP IS FOR (item = Michelle's number)
------------------------------------------------
   1  page-1 "Coverages and Premium": lines + premiums, no      items 1, 2
      carrier, no number; "6 Workers' Compensation No
      Coverage" directly above "7 Umbrella $3,418.00"
   2  TWO legal entities: EMC Property & Casualty (GL only)     items 1, 5
      vs Employers Mutual Casualty (IM / Auto / Umbrella);
      the policy prints NO NAIC anywhere (as on the real
      package) - the NAIC pairs exist only on the certificate
   3  every page header names the producer and the section's   items 1, 4
      policy number; footers carry form numbers + the
      compact number + the "2601" print code (6C74002 2601)
   4  AAIS / ISO / carrier form numbers beside policy numbers:  item 3
      IM 7100 06 04, IM 7201 10 02, CU7001A 11-15, CA7450 M,
      CA7000A 02-22, CG 70 01A 10 12, IL 71 31A 04 01,
      CG 00 01 04 13, and the account number 0482854
   5  endorsement MENUS naming Property / Crime / Farm /        item 2
      Liquor / EPLI / OCP / Pollution / Medical Professional
   6  Drive Other Car: "DRIVE OTHER CAR - TERRITORY: 104 6679   items 6, 11
      $ 204.00", "Auto Elite Extension 8556", named
      individual ROYAL, ERIN (not a driver)
   7  one vehicle, VIN 4S4BRCGC9C3217772, CLASS 7383, TERR     items 6, 11
      111, USE: NA; the narrative repeats it with no VIN
   8  GL classes 91580 ($39,300 payroll) / 91585 ($350,000     item 6
      total cost), no territory; Location 000 credit lines
   9  umbrella dec dated 07/16/25 at $3,000,000; certificate   item 9
      $1,000,000 + "Note:ReducedUmbrellaLimitfrom$3,000,000
      to$1,000,000LimitEffective7/25/25."; narrative $1M
  10  GL extension: aggregate per project / per location;      items 5, 10
      "Coverage Form: CU7001A 11-15 Commercial Liability
      Umbrella Coverage Form" beside the umbrella limits
  11  certificate holder "ForInformationalPurposesOnly"        item 8
  12  certificate: unticked HIRED AUTOS ONLY / NON-OWNED       item 10
      boxes; an empty preprinted WC / EL row
  13  narrative: "The account has been placed through          item 4
      Commercial Risk Solutions" - the incumbent broker in a
      SUBMISSION document; no new agency anywhere
  14  AAIS CL 0182 / ISO IL 02 28 conditional renewal wording  item 10
      ("if it is a renewal of a policy issued by us")
  15  "Colorado Company Elimination" page naming four EMC      items 1, 10
      entities, incl. "EMC Property and Casualty Company"

WHAT IS NOT LIKE THE REAL PACKAGE, ON PURPOSE
---------------------------------------------
  * 49 pages, not 271. Every declarations / schedule page is kept; the ISO and
    AAIS forms are one or two representative pages each.
  * Every page (ISO pages included) carries a header stamp naming the section's
    carrier, policy number and the producer. The real ISO pages carry no stamp;
    the stamp starts with the carrier's legal name so the page-header carrier
    binder reads the RIGHT company off it (checked below with the pipeline's own
    `_header_carrier_name`), never a menu line like "THIS ENDORSEMENT MODIFIES
    INSURANCE".
  * Per the retest spec: the umbrella's schedule of underlying insurance prints
    BBC7263-26 / 6E7-40-02---26 (the real one printed BBC7263 / 6E74002); the
    GL dec prints "Coverage Form: ... Occurrence"; the umbrella dec prints the
    CU7001A 11-15 line; the Auto Elite Extension carries a hired-auto physical
    damage deductible schedule; the certificate's producer is Commercial Risk
    Solutions (the real COI printed "CRS Insurance Brokerage").
  * The Drive Other Car schedule prints "ROYAL, ERIN" (the spec) and the
    continuation page "ERIN ROYAL" (the real page 92). `named_individuals.
    printing_roles` matches the name AS PRINTED, so with only "ROYAL, ERIN" an
    extraction that copies "Erin Royal" would leave her a driver - a name-order
    gap in that rule, not the 14 Sep fix this kit is checking. Both printings
    keep item 11 testing the fix itself.
  * The certificate's side-by-side INSURED block sits half a row below each
    INSURER row, so every "INSURER A :..." reads as a line of its own, as the
    client's certificate OCR does.

No database, network or LLM is touched by this script. ISO / AAIS form text is
condensed from the client's own policy (271page_test_data/271page-testdec.txt).
"""

from __future__ import annotations

import difflib
import os
import re
import sys

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(REPO_ROOT, "backend")
OUT_DIR = os.path.join(REPO_ROOT, "orbin_retest_kit")
REAL_OCR = os.path.join(REPO_ROOT, "271page_test_data", "271page-testdec.txt")

F1 = "1_policy_package.pdf"
F2 = "2_certificate.pdf"
F3 = "3_narrative.pdf"

# ── The account ─────────────────────────────────────────────────────────────
INSURED = "ORBIN CONTRACTING LLC"
INSURED_MIXED = "Orbin Contracting LLC"
ADDR1 = "4800 DAHLIA ST # D13"
CITY = "DENVER, CO 80216-3121"
CITY_MF = "DENVER CO 80216-3121"            # the mainframe pages print no comma
ACCOUNT = "0482854"
TERM_MF = "EFF DATE: 07/15/25 EXP DATE: 07/15/26"

PRODUCER = "COMMERCIAL RISK SOLUTIONS, INC."
PRODUCER_MIXED = "Commercial Risk Solutions, Inc."
PRODUCER_ADDR1 = "9780 S MERIDIAN BLVD STE 400"
PRODUCER_CITY = "ENGLEWOOD, CO 80112-6072"
PRODUCER_CITY_MF = "ENGLEWOOD CO 80112-6072"
AGENT_NO = "W6258-0001"                    # page 1
AGENT_NO_MF = "AW 6258"                    # IM / Auto / Umbrella decs
AGENT_NO_GL = "W6258"                      # GL dec
AGENT_PHONE = "303-996-7800"
AGENT_PHONE_MF = "(303)996-7800"
CONTACT = "Terri Wroblewski"
CONTACT_EMAIL = "twroblewski@crsdenver.com"

CAR_MUT = "EMPLOYERS MUTUAL CASUALTY COMPANY"
CAR_MUT_MIXED = "Employers Mutual Casualty Company"
CAR_PC = "EMC Property & Casualty Company"
NAIC_MUT = "21415"
NAIC_PC = "25186"

POL_IM = "6C7-40-02---26"
POL_AUTO = "6E7-40-02---26"
POL_UMB = "6J7-40-02---26"
POL_GL = "BBC7263-26"
POL_GL_HDR = "BBC7263 - 26"                # the GL continuation pages' printing
POL_GL_SHORT = "BBC7263"                   # GL footers and the certificate
FOOT_IM, FOOT_AUTO, FOOT_UMB = "6C74002", "6E74002", "6J74002"

VIN = "4S4BRCGC9C3217772"
DOC_LINE = "DRIVE OTHER CAR - TERRITORY: 104 6679 $ 204.00"
ELITE_LINE = "Auto Elite Extension 8556 $ 250.00"
DOC_INDIVIDUAL = "ROYAL, ERIN"             # the retest spec's printing (schedule)
DOC_INDIVIDUAL_REAL = "ERIN ROYAL"         # the real package's printing (page 92)

FORM_NUMBERS = ["IM 7100 06 04", "IM 7201 10 02", "CU7001A 11-15", "CA7450 M",
                "CA7000A 02-22", "CG 70 01A 10 12", "IL 71 31A 04 01", "CG 00 01 04 13"]

NO_COVERAGE_ROWS = ["1 Property No Coverage", "3 Crime and Fidelity No Coverage",
                    "6 Workers' Compensation No Coverage"]

MENU_HEADER = "THIS ENDORSEMENT MODIFIES INSURANCE PROVIDED UNDER THE FOLLOWING:"
MENU_LINES = ["COMMERCIAL PROPERTY COVERAGE PART", "FARM COVERAGE PART",
              "LIQUOR LIABILITY COVERAGE PART",
              "EMPLOYMENT-RELATED PRACTICES LIABILITY COVERAGE PART",
              "OWNERS AND CONTRACTORS PROTECTIVE LIABILITY COVERAGE PART",
              "POLLUTION LIABILITY COVERAGE PART", "COMMERCIAL CRIME COVERAGE PART"]

# The certificate's run-together strings - EXACTLY as the client's COI OCR.
COI_INSURER_A = "INSURER A :EMCProperty&CasualtyCompany 25186"
COI_INSURER_B = "INSURER B :EmployersMutualCasualtyCo. 21415"
COI_HOLDER = "ForInformationalPurposesOnly"
COI_REMARK = "Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25."
COI_DATE = "07/28/2025"
RUN_TOGETHER = [COI_INSURER_A, COI_INSURER_B, COI_HOLDER, COI_REMARK]


# ── Layout ───────────────────────────────────────────────────────────────────
# Every column start is MEASURED with reportlab's own font metrics and checked
# before it is drawn: a fused cell ("LLCCOMMERCIAL") hands the model one token
# where the document prints two, and the value under test stops testing anything.

PAGE_W, PAGE_H = LETTER
LM = 0.6 * inch
RM = PAGE_W - 0.6 * inch
USABLE = RM - LM
TOP = PAGE_H - 0.55 * inch
BOTTOM = 0.8 * inch
MIN_GAP = 6.0                 # points between two cells on one baseline
GLUE = 1.6                    # a VISIBLE word gap below pdfplumber's x_tolerance (3pt)

MF = ("Courier", 8.2)         # EMC's mainframe-printed declarations
MF_BOLD = ("Courier-Bold", 8.2)
SANS = ("Helvetica", 8.6)     # EMC P&C / common declarations / narrative
SANS_BOLD = ("Helvetica-Bold", 8.6)
FORM = ("Helvetica", 7.6)     # ISO / AAIS forms


class _Doc:
    def __init__(self, path: str, title: str):
        self.path = path
        self.c = canvas.Canvas(path, pagesize=LETTER, pageCompression=1)
        self.c.setTitle(title)
        self.c.setAuthor("Primble retest kit (synthetic copy of a client package)")
        self.c.setCreator("make_orbin_retest_pdfs.py")
        self.page_no = 0
        self.y = TOP
        self.footer: tuple = ()
        self.meta: list = []      # per page: {"section", "carrier", "real_page"}

    # -- pages ---------------------------------------------------------------
    def page(self, *, section=None, carrier=None, real_page=None, footer=()):
        if self.page_no:
            self._finish()
        self.page_no += 1
        self.meta.append({"section": section, "carrier": carrier, "real_page": real_page})
        self.footer = tuple(footer)
        self.y = TOP

    def _finish(self):
        c = self.c
        y = 0.42 * inch + 9.0 * (len(self.footer) - 1)
        for item in self.footer:
            font, size = FORM
            if isinstance(item, tuple):
                self._draw_cells([(LM, item[0]), ("R", item[1])], font, size, y)
            else:
                self._fits(item, font, size, LM)
                c.setFont(font, size)
                c.drawString(LM, y, item)
            y -= 9.0
        c.showPage()

    def save(self):
        self._finish()
        self.c.save()

    # -- guards ----------------------------------------------------------------
    def _room(self, need: float):
        if self.y - need < BOTTOM:
            raise RuntimeError(f"{os.path.basename(self.path)}: page {self.page_no} overflows")

    @staticmethod
    def _fits(text, font, size, x):
        if x + stringWidth(str(text), font, size) > RM + 0.5:
            raise RuntimeError(f"text runs off the page: {text!r}")

    # -- drawing -------------------------------------------------------------------
    def _draw_cells(self, cells, font, size, y):
        placed = []
        for cell in cells:
            x, text = cell[0], str(cell[1])
            f = cell[2] if len(cell) > 2 and cell[2] else font
            s = cell[3] if len(cell) > 3 and cell[3] else size
            w = stringWidth(text, f, s)
            if x == "R":
                x = RM - w
            elif isinstance(x, tuple) and x[0] == "r":      # ("r", right edge)
                x = x[1] - w
            placed.append((x, w, text, f, s))
        placed.sort(key=lambda p: p[0])
        for (x0, w0, t0, _f, _s), (x1, _w1, t1, _g, _t) in zip(placed, placed[1:]):
            if x0 + w0 + MIN_GAP > x1:
                raise RuntimeError(f"cells collide: {t0!r} / {t1!r}")
        for x, _w, text, f, s in placed:
            self._fits(text, f, s, x)
            self.c.setFont(f, s)
            self.c.drawString(x, y, text)

    def line(self, text="", font=MF, x=None, lead=None):
        f, s = font
        lead = lead or s + 2.2
        self._room(lead)
        if text:
            x = LM if x is None else x
            self._fits(text, f, s, x)
            self.c.setFont(f, s)
            self.c.drawString(x, self.y, text)
        self.y -= lead

    def lines(self, texts, font=MF, lead=None):
        for t in texts:
            self.line(t, font=font, lead=lead)

    def cells(self, cells, font=MF, lead=None):
        f, s = font
        lead = lead or s + 2.2
        self._room(lead)
        self._draw_cells(cells, f, s, self.y)
        self.y -= lead

    def pair(self, left, right, xr, font=MF, lead=None):
        """Two independent blocks side by side (Named Insured | Producer)."""
        for i in range(max(len(left), len(right))):
            row = []
            if i < len(left) and left[i]:
                row.append((LM, left[i]))
            if i < len(right) and right[i]:
                row.append((xr, right[i]))
            self.cells(row, font=font, lead=lead)

    def gap(self, pts=5.0):
        self.y -= pts

    def rule(self, width=0.5):
        self.c.setLineWidth(width)
        self.c.line(LM, self.y + 6, RM, self.y + 6)
        self.gap(3)

    def glued(self, x, y, text, font, size):
        """Draw words with a visible gap but NO space glyph - pdfplumber returns
        them run-together, which is how the client's certificate reads."""
        for word in text.split(" "):
            self.c.setFont(font, size)
            self.c.drawString(x, y, word)
            x += stringWidth(word, font, size) + GLUE
        return x

    def wrap(self, text, font=SANS, x=None, width=None, lead=None):
        f, s = font
        x = LM if x is None else x
        width = width or (RM - x)
        lead = lead or s + 2.6
        cur = ""
        out = []
        for word in str(text).split():
            trial = f"{cur} {word}".strip()
            if stringWidth(trial, f, s) <= width:
                cur = trial
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        for ln in out:
            self.line(ln, font=font, x=x, lead=lead)

    def two_col(self, paragraphs, font=FORM, gutter=16.0):
        """ISO / AAIS forms print their body in two columns."""
        f, s = font
        lead = s + 2.5
        width = (USABLE - gutter) / 2.0
        rows = []
        for para in paragraphs:
            cur = ""
            for word in para.split():
                trial = f"{cur} {word}".strip()
                if stringWidth(trial, f, s) <= width:
                    cur = trial
                else:
                    rows.append(cur)
                    cur = word
            if cur:
                rows.append(cur)
            rows.append("")
        while rows and not rows[-1]:
            rows.pop()
        capacity = int((self.y - BOTTOM) // lead)
        if len(rows) > 2 * capacity:
            raise RuntimeError(f"{os.path.basename(self.path)}: page {self.page_no} "
                               f"two-column body overflows ({len(rows)} > {2 * capacity})")
        half = min(capacity, (len(rows) + 1) // 2)
        left, right = rows[:half], rows[half:]
        y0 = self.y
        for col, x in ((left, LM), (right, LM + width + gutter)):
            y = y0
            for ln in col:
                if ln:
                    self.c.setFont(f, s)
                    self.c.drawString(x, y, ln)
                y -= lead
        self.y = y0 - lead * max(len(left), len(right))


# ── Section headers: carrier + policy number first, then the producer ───────
# The page-header carrier binder (`extraction_service._contract_carriers_from_
# page_headers`) reads the FIRST line in a page's first six that looks like a
# company. EMC's own continuation headers start with the carrier, so the stamp
# does too - an ISO menu line ("THIS ENDORSEMENT MODIFIES INSURANCE") below it
# is never read as a carrier.
X_MF_RIGHT = LM + 290


def head_emc(d, pol, *, label="POLICY NUMBER:", term=TERM_MF):
    d.cells([(LM, CAR_MUT), (X_MF_RIGHT, f"{label} {pol}")])
    d.cells([(LM, INSURED), (X_MF_RIGHT, term)])
    d.line(f"PRODUCER: {PRODUCER} AGENT: {AGENT_NO_MF}")


def head_gl(d, *, first=False):
    d.line(CAR_PC, font=SANS)
    d.line(f"Policy Number: {POL_GL}" if first else f"Policy: {POL_GL_HDR}", font=SANS)
    d.line("Policy Term: 07/15/2025–07/15/2026", font=SANS)
    if not first:
        d.line(f"Producer: {PRODUCER} Agent No. {AGENT_NO_GL}", font=SANS)


def foot_emc(form, pol_foot):
    return (f"{form} BPP 07/15/25 027 SB {pol_foot} 2601",)


def foot_gl(form):
    return (f"{form} 07/15/2025 {POL_GL_SHORT} 2601",)


DASH = "- " * 38
EQ = "=" * 78
HR = "-" * 78


BAND_GAP = 11.0   # > 4x the line pitch: `page_layout` treats what follows as a new band


def dec_identity_block(d, *, insured_label, producer_label):
    """NAMED INSURED | PRODUCER side by side - the real layout. Whitespace above
    and below makes it its own horizontal band, which is what lets the pipeline's
    `page_layout._parallel_region` read it back as two blocks one after the other
    - exactly the real OCR's order (insured, then producer, then "DIRECT BILL
    AGENT PHONE: ..." on one line)."""
    d.gap(BAND_GAP)
    d.cells([(LM, insured_label), (X_MF_RIGHT, producer_label)])
    d.line(DASH.strip())
    d.pair([INSURED, ADDR1, CITY_MF, ""],
           [PRODUCER, PRODUCER_ADDR1, PRODUCER_CITY_MF, f"AGENT: {AGENT_NO_MF}"], X_MF_RIGHT)
    d.gap(BAND_GAP)
    d.pair(["DIRECT BILL", "", ""],
           [f"AGENT PHONE: {AGENT_PHONE_MF}", "CLAIM REPORTING: (888)362-2255",
            "SERVICING CARRIER: (720)200-3700"], X_MF_RIGHT)
    d.line(DASH.strip())


def policy_box(d, pol, period):
    xb = LM + 300
    d.cells([(xb, "*------------------------*")])
    d.cells([(LM, period), (xb, "* POLICY NUMBER *")])
    d.cells([(xb, f"*{pol}*")])


def schedule_table(d, rows, cols=(LM, LM + 62, LM + 108), font=MF):
    for r in rows:
        d.cells([(x, t) for x, t in zip(cols, r) if t], font=font)


# ── 1. THE POLICY PACKAGE ───────────────────────────────────────────────────

def p_common_1(d):
    d.page(section="common", real_page=1, footer=(f"Form: IL 7000A Ed. 9-02 {ACCOUNT}",))
    d.line(f"Account Number: {ACCOUNT}", font=SANS)
    d.line("Policy Term: See Section Declarations To: 07/15/2026", font=SANS)
    d.line("12:01 A.M. Standard Time", font=SANS)
    d.line("(Unless Changed On The Section Declarations)", font=SANS)
    d.gap(4)
    # No band break ABOVE the identity block: on the real page 1 the five header
    # lines share its band (utils/page_layout._parallel_region says so), which is
    # what gives the gutter enough two-sided rows to be found at all.
    d.line("Common Declarations", font=("Helvetica-Bold", 12), lead=14)
    xr = LM + 280
    d.pair(["Named Insured", f", {INSURED}", ADDR1, CITY],
           ["Producer", PRODUCER, PRODUCER_ADDR1, PRODUCER_CITY, f"AGENT NO. {AGENT_NO}",
            f"AGENT PHONE: {AGENT_PHONE}", "CLAIM REPORTING: 888-362-2255"], xr, font=SANS)
    # The premium table below raises this page's median line pitch to ~4pt, so the
    # band break under the identity block has to clear ~16pt, not ~9.
    d.gap(20)
    d.wrap("In return for the payment of the premium, and subject to all the terms of this "
           "policy, we agree with you to provide the insurance as stated in this policy. This "
           "policy consists of the following coverage parts for which a premium is indicated. "
           "This premium may be subject to adjustment. The company affording coverage is "
           "designated by the name in the declarations or information page for each section "
           "of the policy.", font=SANS)
    d.gap(6)
    d.line("Coverages and Premium", font=SANS_BOLD, lead=13)
    cols = (LM + 8, LM + 70, LM + 330)
    d.cells([(cols[0], "Section", *SANS_BOLD), (cols[1], "Coverage", *SANS_BOLD),
             (cols[2], "Premium", *SANS_BOLD)], font=SANS, lead=13)
    for sec, cov, prem in [("1", "Property", "No Coverage"), ("2", "Liability", "$3,954.00"),
                           ("3", "Crime and Fidelity", "No Coverage"),
                           ("4", "Inland Marine", "$300.00"), ("5", "Automobile", "$2,991.00"),
                           ("6", "Workers' Compensation", "No Coverage"),
                           ("7", "Umbrella", "$3,418.00"), ("8", "Other", "")]:
        row = [(cols[0], sec), (cols[1], cov)]
        if prem:
            row.append((cols[2], prem))
        d.cells(row, font=SANS, lead=12.5)
    d.cells([(cols[0], "Estimated Total Policy Premium", *SANS_BOLD),
             (cols[2], "$10,663.00", *SANS_BOLD)], font=SANS, lead=16)
    d.line("Forms applicable to all sections except:", font=SANS)
    d.line("1. Workers' compensation", font=SANS, x=LM + 10)
    d.gap(24)
    d.line("Authorized Representative Signature:", font=SANS)
    d.gap(6)
    d.line("Date of Issue: 07/16/2025 Place of Issue: Des Moines, IA", font=SANS)


def p_common_2(d):
    d.page(section="common", real_page=2, footer=(f"Form: IL 7000A Ed. 9-02 {ACCOUNT}",))
    d.line(f"Account Number: {ACCOUNT}", font=SANS)
    d.line("Policy Term: See Section Declarations To: 07/15/2026", font=SANS)
    d.line("12:01 A.M. Standard Time", font=SANS)
    d.line("(Unless Changed On The Section Declarations)", font=SANS)
    d.line(f"Producer: {PRODUCER} AGENT NO. {AGENT_NO}", font=SANS)
    d.gap(10)
    d.line("The address and telephone number of the servicing company is:", font=SANS)
    d.line("EMC Insurance Companies Phone: 720-200-3700", font=SANS)
    d.line("5445 DTC Parkway, Suite 320", font=SANS)
    d.line("Greenwood Village, CO 80111-3048", font=SANS)
    d.gap(30)
    d.line("Authorized Representative Signature:", font=SANS)
    d.gap(6)
    d.line("Date of Issue: 07/16/2025 Place of Issue: Des Moines, IA", font=SANS)


# -- Inland Marine: Employers Mutual Casualty Company, 6C7-40-02---26 -------------

IM_ENDORSEMENTS = [
    ("*CL0100", "03-99", "COMMON POLICY CONDITIONS"),
    ("*CL0182", "01-01", "AMENDATORY ENDORSEMENT COLORADO"),
    ("*CL0600", "01-15", "CERTIFIED TERRORISM LOSS"),
    ("*CL0700", "10-06", "VIRUS OR BACTERIA EXCLUSION"),
    ("*CL0811", "09-18", "CANNABIS ITEMS AND ACTIVITIES EXCL"),
    ("*CM7001A", "09-97", "COMMERCIAL INLAND MARINE SCHEDULE"),
    ("*CM7004", "09-06", "QUICK REFERENCE"),
    ("*CM7507", "06-18", "CONTRACTORS ESSENTIAL INDUSTRY EXT"),
    ("*CM8068", "12-19", "ADVISORY NOTICE TO POLICYHOLDERS"),
    ("*CM9905", "12-19", "CANNABIS EXCLUSION"),
    ("*IL0017", "11-98", "COMMON POLICY CONDITIONS"),
    ("*IL7004", "03-20", "MUTUAL POLICY PROVISIONS"),
    ("*IL7131A", "04-01", "COMM'L POLICY ENDORSEMENT SCHEDULE"),
    ("*IL7306", "08-98", "EXCLUSION OF CERTAIN COMPUTER LOSSES"),
    ("*IL7602", "04-16", "COLORADO COMPANY ELIMINATION"),
    ("*IL8383.2A", "12-20", "DISCL PURSUANT TERRSM RISK INS. ACT WAIVED"),
    ("*IL8491", "04-19", "DISCLOSURE NOTICE CANNABIS EXCLUSION"),
    ("*IM7000", "04-04", "CONTRACTOR'S EQUIPMENT COVERAGE"),
    ("*IM7017", "06-04", "WEIGHT OF LOAD ENDORSEMENT"),
    ("*IM7100", "06-04", "INSTALLATION FLOATER COVERAGE"),
    ("*IM7201", "10-02", "COMPUTER COVERAGE"),
    ("*IM7238", "10-02", "EARTHQUAKE, FLOOD AND SEWER BACKUP"),
]


def p_im_dec(d):
    d.page(section="inland_marine", carrier=CAR_MUT, real_page=3,
           footer=foot_emc("FORM: CM7000A ED. 3-20", FOOT_IM))
    d.cells([(LM, CAR_MUT), ("R", f"Policy Number: {POL_IM}")])
    d.line("COMMERCIAL INLAND MARINE DECLARATIONS")
    policy_box(d, POL_IM, "POLICY PERIOD: FROM 07/15/25 TO 07/15/26")
    d.cells([(LM + 300, "*------------------------*")])
    dec_identity_block(d, insured_label="NAMED INSURED:", producer_label="PRODUCER:")
    d.cells([(LM, "INSURED IS: LLC"), (LM + 150, "BUSINESS DESC: COMMERCIAL GENERAL CONTRA")])
    d.line(DASH.strip())
    d.line("SEE ATTACHED SCHEDULE FOR LIMITS AND DESCRIPTION OF COVERAGES")
    d.line("-" * 61)
    xp = LM + 330
    d.cells([(LM, "COVERAGES HEADINGS"), (xp, "PREMIUM")])
    d.cells([(LM, "-" * 47), (xp, "-" * 14)])
    d.cells([(LM, "CONTRACTORS EQUIPMENT"), (xp, "$ 300.00")])
    d.cells([(LM, "ELECTRONIC DATA PROCESSING"), (xp, "INCLUDED")])
    d.cells([(LM, "INSTALLATION FLOATER"), (xp, "INCLUDED")])
    d.line(HR[:75])
    d.cells([(LM, "TOTAL INLAND MARINE PREMIUM"), (xp, "$ 300.00")])
    d.line("-" * 44)
    d.lines(["A DEDUCTIBLE MAY APPLY FOR THE COVERAGE PROVIDED. IN THE EVENT A LOSS",
             "(OTHER THAN EARTHQUAKE) INVOLVES COVERED PROPERTY AT MORE THAN ONE",
             "LOCATION OR IN MORE THAN ONE CLASS, ONLY ONE DEDUCTIBLE, THE LARGEST",
             "DEDUCTIBLE SHOWN ON THE SCHEDULE FOR THE LOCATION OR CLASSES INVOLVED",
             "IN THE LOSS, WILL APPLY PER OCCURRENCE.",
             HR[:75],
             "FORM IL0017 ON THE COMMON DECLARATIONS DOES NOT APPLY TO THE FOLLOWING:",
             "CL0100(03/99)*, CL0182(01/01)*, CL0600(01/15)*, CL0700(10/06)*,",
             "CL0811(09/18)*, CM7001A(09/97)*, CM7004(09/06)*, CM7507(06/18)*,",
             "IL0017(11/98)*, IL7004(03/20)*, IL7131A(04/01)*, IL7306(08/98)*,",
             "IL7602(04/16)*, IL8383.2A(12/20)*, IL8491(04/19)*, IM7000(04/04)*,",
             "IM7017(06/04)*, IM7100(06/04)*, IM7201(10/02)*, IM7238(10/02)*",
             HR[:75],
             "DATE OF ISSUE: 07/16/25 (BPP)"])


def p_im_endorsements(d):
    d.page(section="inland_marine", carrier=CAR_MUT, real_page=4,
           footer=(f"FORM: IL7131A (ED. 04-01) 027 SB {FOOT_IM} 2601",))
    head_emc(d, POL_IM)
    d.lines(["COMML INLAND MARINE POLICY", "DECLARATIONS", EQ, "ENDORSEMENT SCHEDULE",
             "EDITION"])
    d.cells([(LM, "FORM DATE"), (LM + 108, "DESCRIPTION/ADDITIONAL INFORMATION"),
             (LM + 400, "PREMIUM")])
    d.line(HR)
    schedule_table(d, IM_ENDORSEMENTS)
    d.line("DATE OF ISSUE: 07/16/25")


def _im_sched_head(d, real_page, page_label=None):
    d.page(section="inland_marine", carrier=CAR_MUT, real_page=real_page,
           footer=(f"FORM: CM7001A ED. 9-97 BPP 07/15/25 027 SB {FOOT_IM} 2601",))
    if page_label:
        d.line(page_label)
    head_emc(d, POL_IM, label="POLICY NO:")
    d.line("COMMERCIAL INLAND MARINE SCHEDULE")
    d.line("-" * 80)


def amt(d, label, value, x=LM + 360):
    d.cells([(LM, label), (x, value)])


def p_im_schedule_1(d):
    _im_sched_head(d, 6)
    d.lines(["POLICYWIDE COVERAGES", HR, "CLASS/ITEM DESCRIPTION *SPEC INTEREST LIMITS", HR,
             "870 CONTRACTORS' ESSENTIAL INDUSTRY EXTENSION"])
    amt(d, "ANNUAL PREMIUM", "$ 300")
    d.lines([DASH.strip(), "CONTRACTORS EQUIPMENT", "801 CONTRACTORS EQUIPMENT",
             "$ 500 DEDUCTIBLE APPLIES PER OCCURRENCE TO THE FOLLOWING ITEMS",
             "80% COINSURANCE",
             "$ 10,000 CATASTROPHE LIMIT - THE MOST \"WE\" PAY FOR LOSS IN ANY ONE",
             "OCCURRENCE", "COVERAGE EXTENSIONS"])
    amt(d, "ADDITIONAL DEBRIS REMOVAL EXPENSES", "$ 25,000")
    d.line("SUPPLEMENTAL COVERAGES")
    amt(d, "EMPLOYEE TOOLS (ACTUAL CASH VALUE)", "$ 7,500")
    d.line("NEWLY PURCHASED EQUIPMENT")
    amt(d, "PERCENTAGE OF CATASTROPHE LIMIT", "30%")
    amt(d, "POLLUTANT CLEANUP AND REMOVAL", "$ 25,000")
    amt(d, "RENTAL REIMBURSEMENT LIMIT", "$ 7,500")
    amt(d, "WAITING PERIOD", "72 HRS")
    amt(d, "SPARE PARTS AND FUEL", "$ 7,500")
    d.line("ACTUAL CASH VALUE")
    amt(d, "UNSCHEDULED CONTRACTORS EQUIPMENT", "$ 10,000")
    amt(d, "THE MOST 'WE' PAY FOR LOSS TO ANY ONE ITEM", "$ 10,000")
    amt(d, "PREMIUM", "INCLUDED")
    d.lines(["840 CONTR. EQUIP. - LEASED OR RENTED FROM OTHERS", "LIMITS OF INSURANCE"])
    amt(d, "THE MOST \"WE\" PAY FOR LOSS TO ANY ONE ITEM", "$ 50,000")
    amt(d, "THE MOST \"WE\" PAY FOR LOSS IN ANY ONE", "$ 50,000")
    d.lines(["OCCURRENCE", "ACTUAL CASH VALUE"])
    amt(d, "DEDUCTIBLE", "$ 500")
    d.line("DATE OF ISSUE: 07/16/25 (BPP) (CONTINUED)")


def p_im_schedule_2(d):
    _im_sched_head(d, 7, "PAGE 2")
    amt(d, "NON-REPORTING FORM", "PREMIUM INCLUDED")
    d.lines(["INSTALLATION FLOATER", "999 INSTALLATION FLOATER", DASH.strip(),
             "$ 500 DEDUCTIBLE APPLIES TO ALL COVERED CAUSES OF",
             "LOSS EXCEPT FLOOD,EARTHQUAKE AND SEWER BACKUP",
             "NOT COVERED DEDUCTIBLE - EARTHQUAKE COVERAGE",
             "NOT COVERED DEDUCTIBLE - FLOOD COVERAGE",
             "$ 500 DEDUCTIBLE - SEWER BACKUP COVERAGE", "COVERAGE LIMITS",
             "$ 50,000 CATASTROPHE LIMIT - THE MOST \"WE\" PAY FOR",
             "LOSS IN ANY ONE OCCURRENCE",
             "$ 50,000 JOBSITE LIMIT - THE MOST \"WE\" PAY FOR LOSS AT",
             "ANY ONE \"JOBSITE\""])
    amt(d, "COINSURANCE", "80%")
    d.line("COVERAGE EXTENSIONS")
    amt(d, "ADDITIONAL DEBRIS REMOVAL EXPENSES", "$ 5,000")
    amt(d, "EMERGENCY REMOVAL", "10 DAYS")
    amt(d, "LIMITED FUNGUS COVERAGE", "$ 15,000")
    d.line("SUPPLEMENTAL COVERAGES")
    for label, value in [("CONTRACT PENALTY", "$ 5,000"),
                         ("POLLUTANT CLEANUP AND REMOVAL", "$ 10,000"),
                         ("SEWER BACKUP COVERAGE", "$ 5,000"), ("STORAGE LOCATIONS", "$ 5,000"),
                         ("TESTING", "$ 5,000"), ("TRANSIT", "$ 5,000")]:
        amt(d, label, value)
    amt(d, "BUSINESS PERSONAL PROPERTY - THE MOST \"WE\" PAY IN ANY", "NOT COVERED")
    d.lines(["ONE OCCURRENCE FOR LOSS TO PERSONAL PROPERTY", "EARTHQUAKE COVERAGE"])
    amt(d, "EARTHQUAKE LIMIT - THE MOST \"WE\" PAY FOR LOSS TO", "NOT COVERED")
    d.lines(["PROPERTY IN ANY ONE BUILDING OR STRUCTURE"])
    amt(d, "EARTHQUAKE CATASTROPHE LIMIT - THE MOST \"WE\"", "NOT COVERED")
    d.lines(["PAY FOR LOSS IN ANY ONE OCCURRENCE", "FLOOD COVERAGE"])
    amt(d, "FLOOD LIMIT - THE MOST \"WE\" PAY FOR LOSS TO PROPERTY", "NOT COVERED")
    d.line("IN ANY ONE BUILDING OR STRUCTURE")
    amt(d, "FLOOD CATASTROPHE LIMIT - THE MOST \"WE\" PAY", "NOT COVERED")
    d.lines(["FOR LOSS IN ANY ONE OCCURRENCE", "DATE OF ISSUE: 07/16/25 (BPP) (CONTINUED)"])


def p_im_schedule_3(d):
    _im_sched_head(d, 8, "PAGE 3")
    amt(d, "NON-REPORTING FORM", "PREMIUM INCLUDED")
    d.lines([f"LOCATION: 001 {ADDR1}", "DENVER, CO 80216-3121", "SPECIAL*",
             "CLASS DESCRIPTION INTEREST LIMITS", HR, HR, "DATA PROCESSING:",
             "$ 500 DEDUCTIBLE APPLIES TO ALL COVERED PERILS",
             "UNLESS A DIFFERENT DEDUCTIBLE IS INDICATED BELOW",
             "$ 500 DEDUCTIBLE - EARTHQUAKE AND VOLCANIC ERUPTION",
             "NOT COVERED DEDUCTIBLE - \"FLOOD\"",
             "$ 500 DEDUCTIBLE - \"MECHANICAL BREAKDOWN\", \"ELECTRICAL",
             "DISTURBANCE\" AND \"POWER SUPPLY DISTURBANCE\"", "80% COINSURANCE",
             "$ 15,000 EARTHQUAKE \"AGGREGATE\" LIMIT", "$ 15,000 EARTHQUAKE \"OCCURRENCE\" LIMIT",
             "$ 15,000 EARTHQUAKE \"CATASTROPHE\" LIMIT", "NOT COVERED FLOOD \"AGGREGATE\" LIMIT",
             "NOT COVERED FLOOD \"OCCURRENCE\" LIMIT", "NOT COVERED FLOOD \"CATASTROPHE\" LIMIT",
             "$ 15,000 SEWER BACKUP \"AGGREGATE\" LIMIT",
             "$ 15,000 SEWER BACKUP \"OCCURRENCE\" LIMIT",
             "$ 15,000 SEWER BACKUP \"CATASTROPHE\" LIMIT", "847 COMPUTER COVERAGE",
             "COVERAGE LIMITS - ACTUAL CASH VALUE", "$ 10,000 \"HARDWARE\"",
             "$ 5,000 \"PROGRAMS AND APPLICATIONS\" AND \"MEDIA\"",
             "NOT COVERED Income Coverage", "DATE OF ISSUE: 07/16/25 (BPP) (CONTINUED)"])


def p_im_schedule_4(d):
    _im_sched_head(d, 9, "PAGE 4")
    d.line("COVERAGE EXTENSIONS")
    for label, value in [("Additional Debris Removal Expenses", "$ 5,000"),
                         ("Emergency Removal (Number of DAYS)", "365"),
                         ("Emergency Removal Expenses", "$ 1,000"),
                         ("ELECTRICAL AND POWER SUPPLY DISTURBANCE", "COVERED")]:
        amt(d, label, value)
    d.line("-500 Feet Limitation NOT WAIVED")
    amt(d, "Fraud and Deceit", "$ 1,000")
    amt(d, "MECHANICAL BREAKDOWN COVERAGE", "COVERED")
    d.line("SUPPLEMENTAL COVERAGES")
    for label, value in [("Acquired Locations", "$ 250,000"), ("Earthquake Coverage", "COVERED"),
                         ("Flood Coverage", "NOT COVERED"),
                         ("NEWLY PURCHASED OR LEASED HARDWARE", "$ 250,000"),
                         ("Off-Site Computers", "$ 2,500"),
                         ("Pollutant Cleanup and Removal", "$ 10,000"),
                         ("Property in Transit", "$ 5,000"),
                         ("PROPRIETARY PROGRAMS AND DATA RECORDS", "$ 5,000"),
                         ("Sewer Backup", "COVERED"), ("REWARDS", "$ 1,000"),
                         ("Software Storage", "$ 25,000")]:
        amt(d, label, value)
    d.line("Virus and Hacking")
    amt(d, "Limit any one occurrence", "$ 5,000")
    amt(d, "Limit each separate 12 month period", "$ 10,000")
    amt(d, "FOREIGN TRANSIT AND LOCATION LIMIT", "NOT COVERED")
    d.line("ADDITONAL PROPERTY")
    amt(d, "ACCOUNTS RECEIVABLE-THE MOST \"WE\" PAY IN ANY ONE", "NOT COVERED")
    d.line("OCCURRENCE FOR LOSS TO ACCOUNTS RECEIVABLE")
    amt(d, "VALUABLE PAPERS-THE MOST \"WE\" PAY IN ANY ONE", "NOT COVERED")
    d.line("OCCURRENCE FOR LOSS TO \"VALUABLE PAPERS\"")
    amt(d, "PREMIUM", "INCLUDED")
    d.line(DASH.strip())
    # AAIS "schedule of coverages" form list - the AAIS printing of each number.
    d.line("FORMS AND ENDORSEMENTS APPLICABLE TO THIS SCHEDULE OF COVERAGES:")
    for form, title in [("IM 7000 04 04", "CONTRACTOR'S EQUIPMENT COVERAGE"),
                        ("IM 7017 06 04", "WEIGHT OF LOAD ENDORSEMENT"),
                        ("IM 7100 06 04", "INSTALLATION FLOATER COVERAGE"),
                        ("IM 7201 10 02", "COMPUTER COVERAGE"),
                        ("IM 7238 10 02", "EARTHQUAKE, FLOOD AND SEWER BACKUP")]:
        d.cells([(LM + 12, form), (LM + 110, title)])
    d.line(DASH.strip())
    d.lines(["INCLUDES COPYRIGHTED MATERIAL OF ISO COMMERCIAL RISK SERVICES, INC. WITH ITS",
             "PERMISSION.", "COPYRIGHT, ISO COMMERCIAL RISK SERVICES, INC.",
             "DATE OF ISSUE: 07/16/25 (BPP)"])


TRIA_BODY = [
    "A. Disclosure Of Premium:",
    "In accordance with the federal Terrorism Risk Insurance Act, we are",
    "required to provide you with a notice disclosing the portion of",
    "your premium, if any, attributable to coverage for terrorist acts",
    "certified under the Terrorism Risk Insurance Act. The portion of",
    "your premium attributable to such coverage is shown in the Schedule",
    "of this endorsement or in the policy Declarations.",
    "B. Disclosure Of Federal Participation In Payment Of Terrorism Losses:",
    "The United States Government, Department of the Treasury, will pay",
    "a share of terrorism losses insured under the federal program. The",
    "federal share equals 80% of that portion of the amount of such insured",
    "losses that exceeds the applicable insurer retention.",
    "C. Cap On Insurer Participation In Payment Of Terrorism Losses:",
    "If aggregate insured losses attributable to terrorist acts certified",
    "under the Terrorism Risk Insurance Act exceed $100 billion in a calendar",
    "year and we have met our insurer deductible under the Terrorism Risk",
    "Insurance Act, we shall not be liable for the payment of any portion of",
    "the amount of such losses that exceeds $100 billion.",
    "INCLUDES COPYRIGHTED MATERIAL OF ISO PROPERTIES, INC. WITH ITS PERMISSION",
]


def p_tria_emc(d, section, pol, foot_pol, premium_line, real_page):
    d.page(section=section, carrier=CAR_MUT, real_page=real_page,
           footer=(f"FORM: IL8383.2A(12-20) 027 SB {foot_pol} 2601",))
    head_emc(d, pol)
    d.lines(["THIS ENDORSEMENT IS ATTACHED TO AND MADE PART OF YOUR POLICY IN RESPONSE",
             "TO THE DISCLOSURE REQUIREMENTS OF THE TERRORISM RISK INSURANCE ACT.",
             "THIS ENDORSEMENT DOES NOT GRANT ANY COVERAGE OR CHANGE THE TERMS",
             "AND CONDITIONS OF ANY COVERAGE UNDER THE POLICY.", "DISCLOSURE PURSUANT TO",
             "TERRORISM RISK INSURANCE ACT", "-" * 71, "SCHEDULE", premium_line, "-" * 71])
    d.lines(TRIA_BODY)
    d.line("DATE OF ISSUE: 07/16/25")


def iso_page(d, *, section, carrier, head, top, menu=None, menu_header=None, body,
             footer, real_page=None):
    """One ISO / AAIS form page: the section stamp, the form's own header lines,
    an optional coverage-part MENU, and a two-column body."""
    d.page(section=section, carrier=carrier, real_page=real_page, footer=footer)
    head(d)
    d.gap(3)
    for i, t in enumerate(top):
        d.line(t, font=("Helvetica-Bold", 9.2) if i == len(top) - 1 else ("Helvetica", 8.2))
    if menu:
        d.line(menu_header or "This endorsement modifies insurance provided under the following:",
               font=("Helvetica", 8.2))
        for m in menu:
            d.line(m, font=("Helvetica", 8.2), x=LM + 24)
    d.gap(4)
    d.two_col(body)


def _stamp_im(d):
    head_emc(d, POL_IM)


def _stamp_auto(d):
    head_emc(d, POL_AUTO)


def _stamp_umb(d):
    head_emc(d, POL_UMB)


def _stamp_gl(d):
    head_gl(d)


AAIS_IM7100_P1 = [
    "AGREEMENT - In return for \"your\" payment of the required premium, \"we\" provide the "
    "coverage described herein subject to all the \"terms\" of the Installation Floater Coverage. "
    "This coverage is also subject to the \"schedule of coverages\" and additional policy "
    "conditions relating to assignment or transfer of rights or duties, cancellation, changes or "
    "modifications, inspections, and examination of books and records.",
    "Endorsements and schedules may also apply. They are identified on the \"schedule of "
    "coverages\". Refer to Definitions for words and phrases that have special meaning.",
    "DEFINITIONS",
    "1. The words \"you\" and \"your\" mean the persons or organizations named as the insured on "
    "the declarations.",
    "2. The words \"we\", \"us\", and \"our\" mean the company providing this coverage.",
    "3. \"Earth movement\" means any movement or vibration of the earth's surface (other than "
    "\"sinkhole collapse\") including but not limited to earthquake; landslide; mudflow; "
    "mudslide; mine subsidence; or sinking, rising, or shifting, of earth.",
    "4. \"Flood\" means flood, surface water, waves, tidal water, or the overflow of a body of "
    "water, all whether driven by wind or not.",
    "5. \"Fungus\" means a fungus, including but not limited to mildew and mold; a protist; wet "
    "rot and dry rot; a bacterium; or a chemical, matter, or compound produced or released by a "
    "fungus, a protist, wet rot, dry rot, or a bacterium.",
    "6. \"Jobsite\" means any location, project, or work site where \"you\" are involved in an "
    "installation or construction project.",
    "7. \"Limit\" means the amount of coverage that applies.",
    "8. \"Pollutant\" means any solid, liquid, gaseous, thermal, or radioactive irritant or "
    "contaminant, including acids, alkalis, chemicals, fumes, smoke, soot, vapor, and waste.",
    "9. \"Schedule of coverages\" means all pages labeled schedule of coverages or schedules that "
    "pertain to this coverage; and declarations or supplemental declarations that pertain to "
    "this coverage.",
    "PROPERTY COVERED - \"We\" cover direct physical loss to covered property at a \"jobsite\", "
    "in transit, or at a storage location, caused by a covered peril. Covered property means "
    "materials, supplies, machinery, fixtures, and equipment that \"you\" purchased to be "
    "installed, erected, or used in construction at a \"jobsite\".",
]

AAIS_IM7100_P15 = [
    "WHEN COVERAGE ENDS - Coverage will end when one of the following first occurs:",
    "1. this policy expires or is cancelled;",
    "2. the covered installation or construction project is accepted by the purchaser;",
    "3. \"your\" insurable interest in the covered property ceases;",
    "4. \"you\" abandon the installation or construction project with no intent to complete it;",
    "5. the installation or construction project has been completed for more than 30 days; or",
    "6. the covered property has been put to its intended use. However, this does not apply to "
    "roofs or walls.",
    "Any amount \"we\" pay under this coverage does not reduce the applicable \"limits\".",
]

AAIS_IM7201_P1 = [
    "AGREEMENT - In return for \"your\" payment of the required premium, \"we\" provide the "
    "coverage described herein subject to all the \"terms\" of the Computer Coverage. This "
    "coverage is also subject to the \"schedule of coverages\" and additional policy conditions "
    "relating to assignment or transfer of rights or duties, cancellation, changes or "
    "modifications, inspections, and examination of books and records.",
    "DEFINITIONS",
    "1. \"Computer virus\" means the introduction into a computer system of any malicious "
    "instructions or code that results in but is not limited to deletion, destruction, "
    "generation, or modification of \"software\".",
    "2. \"Hardware\" means a network of electronic machine components (microprocessors) capable "
    "of accepting instructions and information, processing the information according to the "
    "instructions, and producing desired results.",
    "3. \"Media\" means material on which information is recorded, such as film, magnetic tape, "
    "paper tape, disks, drums, and cards.",
    "4. \"Programs and applications\" means operating programs and applications that \"you\" "
    "purchase or develop for use on \"your\" computer system.",
    "PROPERTY COVERED - \"We\" cover the following property unless the property is excluded or "
    "subject to limitations: \"hardware\", \"programs and applications\" and \"media\" that "
    "\"you\" own or that are in \"your\" care, custody, or control.",
    "Territorial Limits - \"We\" cover property while it is in the United States of America, "
    "its territories and possessions, Canada, and Puerto Rico.",
]

AAIS_CL0182 = [
    "1. Under Common Policy Conditions, Cancellation is deleted and replaced by the following:",
    "Cancellation -- \"You\" may cancel this policy by returning the policy to \"us\" or by "
    "giving \"us\" a written notice and stating at what future date coverage is to stop.",
    "\"We\" may cancel this policy by written notice sent to \"you\" by first-class mail at "
    "\"your\" last mailing address known to \"us\". The notice will state the reason for "
    "cancellation and the time that the cancellation is to take effect.",
    "If this policy is in effect less than 60 days, \"we\" may cancel for any reason. \"We\" "
    "will give \"you\" notice at least ten days before cancellation is effective.",
    "After this policy has been in effect 60 days or more, or if it is a renewal of a policy "
    "issued by \"us\" effective immediately, \"we\" may cancel only if one or more of the "
    "following reasons apply: a. nonpayment of premium; b. a false statement knowingly made by "
    "\"you\" on the application of insurance; c. a substantial change in the exposure or risk "
    "other than that indicated in the application.",
    "Nonrenewal -- If \"we\" do not renew this policy, \"we\" will mail \"our\" notice of "
    "nonrenewal to \"you\" by first-class mail at least 45 days before the policy expiration "
    "date. This provision does not apply if \"you\" fail to pay any premium deposit required "
    "for renewal or to any policy or coverage which has been in effect less than 60 days, "
    "unless it is a renewal policy.",
    "2. Under Common Policy Conditions, the following condition is added: Increase In Premium "
    "or Decrease In Coverage -- If \"we\" decide to increase the premium unilaterally or "
    "decrease the coverage benefits on renewal, \"we\" will mail notice to \"you\" at least 45 "
    "days before the policy expiration date.",
]

ISO_IL7306 = [
    "A. We will not pay for loss (\"loss\") or damage caused directly or indirectly by the "
    "following. Such loss (\"loss\") or damage is excluded regardless of any other cause or "
    "event that contributes concurrently or in any sequence to the loss (\"loss\") or damage.",
    "1. The failure, malfunction or inadequacy of: a. Any of the following, whether belonging "
    "to any insured or to others: (1) Computer hardware, including microprocessors; (2) Computer "
    "application software; (3) Computer operating systems and related software; (4) Computer "
    "networks; (5) Microprocessors (computer chips) not part of any computer system; or (6) Any "
    "other computerized or electronic equipment or components;",
    "due to the inability to correctly recognize, process, distinguish, interpret or accept one "
    "or more dates or times.",
    "B. If an excluded Cause of Loss as described in Paragraph A. of this endorsement results "
    "in a Covered Cause of Loss under the Crime and Fidelity Coverage Part, the Commercial "
    "Inland Marine Coverage Part or the Standard Property Policy, we will pay only for the loss "
    "(\"loss\") or damage caused by such Covered Cause of Loss.",
]


def build_im(d):
    p_im_dec(d)
    p_im_endorsements(d)
    p_im_schedule_1(d)
    p_im_schedule_2(d)
    p_im_schedule_3(d)
    p_im_schedule_4(d)
    p_tria_emc(d, "inland_marine", POL_IM, FOOT_IM, "Terrorism Premium (Certified Acts) Waived", 5)
    aais = "Copyright, American Association of Insurance Services, Inc., 2004"
    iso_page(d, section="inland_marine", carrier=CAR_MUT, head=_stamp_im, real_page=44,
             top=["AAIS", "IM 7100 06 04", "INSTALLATION FLOATER COVERAGE"],
             body=AAIS_IM7100_P1, footer=(f"IM 7100 06 04 {aais} Page 1 of 15",))
    iso_page(d, section="inland_marine", carrier=CAR_MUT, head=_stamp_im, real_page=58,
             top=["AAIS", "IM 7100 06 04", "INSTALLATION FLOATER COVERAGE (CONTINUED)"],
             body=AAIS_IM7100_P15, footer=(f"IM 7100 06 04 {aais} Page 15 of 15",))
    iso_page(d, section="inland_marine", carrier=CAR_MUT, head=_stamp_im, real_page=59,
             top=["AAIS", "IM 7201 10 02", "COMPUTER COVERAGE"], body=AAIS_IM7201_P1,
             footer=("IM 7201 10 02 Copyright, American Association of Insurance Services, "
                     "Inc., 2002 Page 1 of 24",))
    iso_page(d, section="inland_marine", carrier=CAR_MUT, head=_stamp_im, real_page=11,
             top=["AAIS This endorsement changes the policy", "CL 0182 01 01",
                  "-- PLEASE READ THIS CAREFULLY --", "AMENDATORY ENDORSEMENT COLORADO"],
             body=AAIS_CL0182,
             footer=("CL 0182 01 01 Copyright, American Association of Insurance Services, "
                     "2001 Page 1 of 1",))
    iso_page(d, section="inland_marine", carrier=CAR_MUT, head=_stamp_im, real_page=27,
             top=["IL 73 06 08 98",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "EXCLUSION OF CERTAIN COMPUTER-RELATED LOSSES"],
             menu=["BOILER AND MACHINERY COVERAGE PART", "COMMERCIAL CRIME COVERAGE PART",
                   "COMMERCIAL INLAND MARINE COVERAGE PART", "COMMERCIAL PROPERTY COVERAGE PART",
                   "STANDARD PROPERTY POLICY"],
             body=ISO_IL7306,
             footer=("IL 73 06 08 98 Copyright, Insurance Services Office, Inc., 1998 "
                     "Page 1 of 2",))


# -- Business Auto: Employers Mutual Casualty Company, 6E7-40-02---26 ----------------

AUTO_ENDORSEMENTS = [
    ("*CA0001", "11-20", "BUSINESS AUTO COVERAGE FORM"),
    ("", "", "TERRORISM COVG INCL IN MAIN COV FORM $ 3"),
    ("*CA0113", "10-13", "COLORADO CHANGES"),
    ("*CA0440", "10-13", "COLORADO AUTO MEDICAL PAYMENTS COV"),
    ("*CA2150", "07-17", "CO UNINSURED MOTORISTS COVERAGE BI"),
    ("*CA7001A", "02-22", "COMM AUTO DECLARATIONS/ADDIT'L ITEMS"),
    ("*CA7002A", "02-22", "COMM AUTO DECLARATIONS - ITEMS 4 & 5"),
    ("*CA7007", "11-20", "QUICK REFERENCE BUSINESS AUTO FORM"),
    ("*CA7093A", "02-22", "UM/UIM SUPPLEMENTAL SCHEDULE"),
    ("*CA7313", "11-15", "PREJUDGMENT INTEREST"),
    ("*CA7450", "09-24", "COMMERCIAL AUTO ELITE EXTENSION"),
    ("*CA8112.2", "11-15", "IMPT NOTICE -PAYMENT FOR AFTERMARKET"),
    ("*CA8214", "05-12", "COLORADO POLICYHOLDER NOTICE"),
    ("*CA8214.1", "05-12", "COLORADO POLICYHOLDER NOTICE"),
    ("*CA8282", "08-18", "CO BODILY INJURY UNINSURED SEL/REJ"),
    ("*CA8336", "11-19", "IMPORTANT NOTICE TO POLICYHOLDERS"),
    ("*CA8338", "11-19", "ADVISORY NOTICE TO POLICYHOLDERS"),
    ("*CA9910A", "10-13", "DRIVE OTHER CAR COV FOR NAMED INDIV"),
    ("*IL0017", "11-98", "COMMON POLICY CONDITIONS"),
    ("*IL0021", "09-08", "NUCLEAR ENERGY LIAB EXCL/BROAD FORM"),
    ("*IL0125", "11-13", "COLORADO CHANGES - CIVIL UNION"),
    ("*IL0169", "09-07", "CO CHGS/CONCEALMENT,MISREPRSNT,FRAUD"),
    ("*IL0228", "09-07", "CO CHANGES - CANCELLATION/NONRENEWAL"),
    ("*IL7004", "03-20", "MUTUAL POLICY PROVISIONS"),
    ("*IL7131A", "04-01", "COMM'L POLICY ENDORSEMENT SCHEDULE"),
    ("*IL7447", "05-15", "NOTICE OF CANC W/WRITTEN CONTRACT"),
    ("*IL7602", "04-16", "COLORADO COMPANY ELIMINATION"),
    ("*IL8576", "10-17", "MEDICARE IMPT NOTICE TO POLICYHOLDER"),
]


def p_auto_dec(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=85,
           footer=foot_emc("CA7000A 02-22", FOOT_AUTO))
    d.cells([(LM, CAR_MUT), ("R", f"Policy Number: {POL_AUTO}")])
    d.line("COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO")
    policy_box(d, POL_AUTO, "POLICY PERIOD: FROM 07/15/25 TO 07/15/26")
    d.cells([(LM, "ITEM ONE:"), (LM + 300, "*------------------------*")])
    dec_identity_block(d, insured_label="NAMED INSURED:", producer_label="PRODUCER:")
    d.cells([(LM, "INSURED IS: LLC"), (LM + 150, "BUSINESS DESC: COMMERCIAL GENERAL CONTRA")])
    d.line(DASH.strip())
    d.lines(["ITEM TWO: SCHEDULE OF COVERAGES AND COVERED AUTOS",
             "THIS POLICY PROVIDES ONLY THOSE COVERAGES WHERE A CHARGE IS SHOWN IN THE",
             "PREMIUM COLUMN BELOW. EACH OF THESE COVERAGES WILL APPLY ONLY TO THOSE",
             "'AUTOS' SHOWN AS COVERED 'AUTOS'. 'AUTOS' ARE SHOWN AS",
             "COVERED 'AUTOS' FOR A PARTICULAR COVERAGE BY THE ENTRY OF ONE OR MORE OF",
             "THE SYMBOLS FROM THE COVERED AUTO SECTION OF THE BUSINESS AUTO COVERAGE FORM/",
             "MOTOR CARRIER COVERAGE FORM NEXT TO THE NAME OF THE COVERAGE."])
    c1, c2, c3, c4 = LM, LM + 170, LM + 222, LM + 380
    d.cells([(c1, "COVERAGES"), (c2 - 30, "COVERED AUTOS"), (c3 + 40, "LIMIT OR DEDUCTIBLES"),
             (c4, ". P R E M I U M")])
    d.cells([(c1, "COVERED AUTOS LIABILITY"), (c2, "01"), (c3, "$ 1,000,000"), (c4, ".$ 1,496.00")])
    d.cells([(c1, "AUTO MEDICAL PAYMENTS"), (c2, "02"), (c3, "$ 5,000 EACH INSURED"),
             (c4, ". 35.00")])
    d.cells([(c1, "UNINSURED AND"), (c2, "02"), (c3, "SEE ENDORSEMENT CA7093A"), (c4, ". 258.00")])
    d.cells([(c1, "UNDERINSURED MOTORISTS"), (c4, ".")])
    d.cells([(c1, "PHYSICAL DAMAGE COVERAGE (FOR EACH COVERED AUTO)."), (c4, ".")])
    d.cells([(c1, "COMPREHENSIVE"), (c2, "07"), (c3, "SEE ITEM SIX"), (c4, ". 134.00")])
    d.cells([(c1, "FOR DEALERS AUTOS"), (c4, ".")])
    d.cells([(c1, "COLLISION"), (c2, "07"), (c3, "SEE SCHEDULE FOR DED"), (c4, ". 289.00")])
    d.cells([(c1, "COVERAGE FOR EACH COVERED AUTO"), (c4, ".")])
    d.cells([(c4, ".")])
    d.cells([(c1, "PREMIUM FOR ATTACHED ITEMS 4, 5, AND/OR 6"), (c4, ". 322.00")])
    d.cells([(c4, ".")])
    d.cells([(c1, "PREMIUM FOR ENDORSEMENTS"), (c4, ".$ 457.00")])
    d.cells([(c2 - 30, "-" * 47)])
    d.cells([(c1, "*ESTIMATED TOTAL POLICY PREMIUM"), (c4, ".$ 2,991.00")])
    d.cells([(c2 - 30, "-" * 47)])
    d.line(DASH.strip())
    d.lines(["FORMS APPLICABLE:",
             "CA0001(11/20)*, CA0113(10/13)*, CA0440(10/13)*, CA2150(07/17)*,",
             "DATE OF ISSUE 07/16/25 (BPP) CONTINUED"])


def p_auto_dec_2(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=86,
           footer=foot_emc("CA7000A 02-22", FOOT_AUTO))
    head_emc(d, POL_AUTO)
    d.lines(["PAGE NO: 2 X", CAR_MUT, "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
             "CA7001A(02/22)*, CA7002A(02/22)*, CA7007(11/20)*, CA7093A(02/22)*,",
             "CA7313(11/15)*, CA7450(09/24)*, CA8112.2(11/15)*, CA8214(05/12)*,",
             "CA8214.1(05/12)*, CA8282(08/18)*, CA8336(11/19)*, CA8338(11/19)*,",
             "CA9910A(10/13)*, IL0017(11/98)*, IL0021(09/08)*, IL0125(11/13)*,",
             "IL0169(09/07)*, IL0228(09/07)*, IL7004(03/20)*, IL7131A(04/01)*,",
             "IL7447(05/15)*, IL7602(04/16)*, IL8576(10/17)*", DASH.strip(),
             "INCLUDES COPYRIGHTED MATERIAL OF ISO PROPERTIES, INC., WITH ITS PERMISSION.",
             "DATE OF ISSUE 07/16/25 (BPP)"])


def p_auto_endorsements(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=87,
           footer=(f"FORM: IL7131A (ED. 04-01) 027 SB {FOOT_AUTO} 2601",))
    head_emc(d, POL_AUTO)
    d.lines(["COMMERCIAL AUTO POLICY", "DECLARATIONS", EQ, "ENDORSEMENT SCHEDULE", "EDITION"])
    d.cells([(LM, "FORM DATE"), (LM + 108, "DESCRIPTION/ADDITIONAL INFORMATION"),
             (LM + 400, "PREMIUM")])
    d.line(HR)
    schedule_table(d, AUTO_ENDORSEMENTS)
    d.line("DATE OF ISSUE: 07/16/25")


def p_auto_um(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=88,
           footer=foot_emc("CA7093A 02-22", FOOT_AUTO))
    head_emc(d, POL_AUTO, label="POLICY NO:")
    d.lines(["**COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO COVERAGE FORM**",
             "SUPPLEMENTARY SCHEDULE",
             "ITEM TWO - UNINSURED MOTORISTS COVERAGE AND UNDERINSURED MOTORISTS COVERAGE",
             "-" * 76,
             "THE LIMIT OF INSURANCE FOR THE COVERAGE SHOWN BELOW IS THE LIMIT OF INSUR-",
             "ANCE SHOWN FOR THE STATE WHERE A COVERED 'AUTO' IS PRINCIPALLY GARAGED.",
             "REFER TO THE SPECIFIC COVERAGE ENDORSEMENT FOR THE DESCRIPTION OF THE",
             "COVERAGE PROVIDED FOR EACH STATE LISTED BELOW.", "COVERAGE",
             "UNINSURED MOTORISTS LIMIT OF INSURANCE",
             "\"BODILY INJURY\" \"BODILY INJURY\" \"BODILY INJURY\" \"PROPERTY DAMAGE\"",
             "AND \"PROPERTY EACH PERSON EACH \"ACCIDENT\" EACH \"ACCIDENT\"",
             "DAMAGE\" EACH \"ACCIDENT\"", "COMBINED", "ST SINGLE LIMIT"])
    d.cells([(LM, "CO"), (LM + 30, "$ 1,000,000")])
    d.line("DATE OF ISSUE 07/16/25 (BPP)")


def p_auto_item3(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=89,
           footer=foot_emc("CA7001A 02-22", FOOT_AUTO))
    head_emc(d, POL_AUTO, label="POLICY NO:")
    d.lines(["COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
             "ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN", "*" * 77])
    xd = LM + 380
    d.cells([(LM, "COVERED AUTO DESCRIPTION / COVERAGE"), (xd, ". PREMIUM")])
    d.lines(["*" * 77, "LOC: 001 4800 DAHLIA STREET D13", "DENVER CO. 80216-3121"])
    d.cells([(LM, "VEH NO 1 TERR: 111"), (xd, ".")])
    d.line(f"2012 SUBARU OUTBACK SEDAN ID NO {VIN}.")
    d.line("ADDITIONAL INFORMATION:")
    d.cells([(LM, "COST NEW: 26680 RADIUS: NA USE: NA"), (xd, ".")])
    d.cells([(LM, "AGE: LIAB-I PHYS-I"), (xd, ".")])
    d.cells([(LM, "PRIV PASSENGER - COMM CLASS: 7383"), (xd, ".")])
    for label, prem in [("COVERED AUTOS LIABILITY", ".$ 1,496.00"),
                        ("AUTO MEDICAL PAYMENTS", ". 35.00"),
                        ("UNINSURED MOTORISTS", ". INCLUDED"),
                        ("UNDERINSURED MOTORISTS", ". INCLUDED"),
                        ("COMPREHENSIVE ACV 1000 DED", ". 134.00")]:
        d.cells([(LM, label), (xd, prem)])
    d.lines(["$ 1000 DEDUCTIBLE FOR ALL PERILS FOR EACH COVERED AUTO",
             "(A MAXIMUM DEDUCTIBLE MAY ALSO APPLY REFER TO COVERAGE FORM",
             "FOR DETAILS.)", "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS"])
    d.cells([(LM, "COLLISION ACV 1000 DED"), (xd, ". 289.00")])
    d.cells([(LM, "TOTAL VEHICLE PREMIUM"), (xd, ".$ 2,212.00")])
    d.line(DASH.strip())
    d.line("ITEM 3 PREMIUM SUMMARY")
    for label, prem in [("COVERED AUTOS LIABILITY", ".$ 1,496.00"),
                        ("AUTO MEDICAL PAYMENTS", ". 35.00"), ("UNINSURED MOTORISTS", ". 258.00"),
                        ("UNDERINSURED MOTORISTS", ". INCLUDED"), ("COMPREHENSIVE", ". 134.00"),
                        ("COLLISION", ". 289.00")]:
        d.cells([(LM, label), (xd, prem)])
    d.cells([(xd, ".--------------")])
    d.cells([(LM, "TOTAL"), (xd, ".$ 2,212.00")])
    d.lines(["INCLUDES COPYRIGHTED MATERIAL OF ISO PROPERTIES, INC., WITH ITS PERMISSION.",
             "DATE OF ISSUE 07/16/25 (BPP)"])


def p_auto_items45(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=90,
           footer=foot_emc("CA7002A 02-22", FOOT_AUTO))
    # The real page prints its number without the term tail: "6E7-40-02".
    d.cells([(LM, CAR_MUT), (X_MF_RIGHT, "POLICY NUMBER 6E7-40-02")])
    d.cells([(LM, INSURED), (X_MF_RIGHT, TERM_MF)])
    d.line(f"PRODUCER: {PRODUCER} AGENT: {AGENT_NO_MF}")
    d.lines(["COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
             "ITEM FOUR: SCHEDULE OF HIRED OR BORROWED COVERED AUTO", "COVERAGE AND PREMIUMS",
             "COVERED AUTOS LIABILITY COVERAGE - COST OF HIRE BASIS",
             "FOR AUTOS NOT USED IN YOUR MOTOR",
             "CARRIER OPERATIONS (OTHER THAN MOBILE OR FARM EQUIPMENT)",
             "COVERED AUTOS STATE ESTIMATED ANNUAL COST OF RATE PREMIUM",
             "LIABILITY COVERAGE HIRE FOR ALL STATES"])
    d.cells([(LM, "EXCESS"), (LM + 110, "CO"), (LM + 200, "IF ANY"), (LM + 300, "100"),
             (LM + 380, "$ 185.00")])
    d.lines(["FOR 'AUTOS' NOT USED IN YOUR MOTOR CARRIER OPERATIONS, COST OF HIRE MEANS",
             "THE TOTAL AMOUNT YOU INCUR FOR THE HIRE OF 'AUTOS' YOU DON'T OWN (NOT",
             "INCLUDING 'AUTOS' YOU BORROW OR RENT FROM YOUR PARTNERS OR 'EMPLOYEES'",
             "OR THEIR FAMILY MEMBERS). COST OF HIRE DOES NOT INCLUDE CHARGES FOR SERVICES",
             "PERFORMED BY MOTOR CARRIERS OF PROPERTY OR PASSENGERS."])
    d.cells([(LM + 380, "-------------")])
    d.cells([(LM, "TOTAL PREMIUM"), (LM + 380, "$ 185.00")])
    d.lines(["ITEM FIVE: SCHEDULE FOR NON-OWNERSHIP COVERED AUTOS LIABILITY"])
    d.cells([(LM + 380, "PREMIUM")])
    d.line("OTHER THAN A SOCIAL SERVICE AGENCY")
    d.cells([(LM, "NUMBER OF EMPLOYEES 0 - 25"), (LM + 380, "$ 137.00")])
    d.cells([(LM + 380, "-------------")])
    d.cells([(LM, "TOTAL NON-OWNERSHIP COVERED AUTOS PREMIUM"), (LM + 380, "$ 137.00")])
    d.lines(["INCLUDES COPYRIGHTED MATERIAL OF ISO PROPERTIES, INC., WITH ITS PERMISSION.",
             "DATE OF ISSUE 07/16/25 (BPP)"])


def p_auto_endorsement_premium(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=91,
           footer=(f"ENDST-A BPP 07/15/25 027 SB {FOOT_AUTO} 2601",))
    head_emc(d, POL_AUTO, label="POLICY NO:")
    d.line("ENDORSEMENT PREMIUM DETAIL")
    xc, xp = LM + 270, LM + 350
    d.cells([(LM, "ENDORSEMENTS"), (xc, "CLASS"), (xp, "PREMIUM")])
    d.cells([(LM, "DRIVE OTHER CAR - TERRITORY: 104"), (xc, "6679"), (xp, "$ 204.00")])
    d.cells([(LM, "Auto Elite Extension"), (xc, "8556"), (xp, "$ 250.00")])
    d.lines(["INCLUDES COPYRIGHTED MATERIAL OF INSURANCE SERVICES OFFICE, INC.",
             "WITH ITS PERMISSION.", "DATE OF ISSUE 07/16/25 (BPP)"])


def p_auto_doc(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=92,
           footer=foot_emc("CA9910A 10-13", FOOT_AUTO))
    head_emc(d, POL_AUTO, label="POLICY NO:")
    d.lines(["DRIVE OTHER CAR COVERAGE", "BROADENED COVERAGE FOR", "NAMED INDIVIDUALS",
             "WITH RESPECT TO COVERAGE PROVIDED BY THIS ENDORSEMENT, THE PROVISIONS OF",
             "THE COVERAGE FORM APPLY UNLESS MODIFIED BY THE ENDORSEMENT."])
    xl, xp = LM + 230, LM + 360
    d.cells([(LM, "COVERAGES"), (xl, "LIMITS/DEDUCTIBLES"), (xp, "PREMIUM")])
    d.line("COVERED AUTOS")
    d.cells([(LM, "LIABILITY COVERAGE"), (xl, "$1,000,000"), (xp, "$ 174.00")])
    d.cells([(LM, "AUTO MEDICAL PAYMENTS"), (xl, "$ 5,000"), (xp, "$ 4.00")])
    d.cells([(LM, "UNINSURED MOTORISTS"), (xl, "$1,000,000"), (xp, "$ 26.00")])
    d.cells([(LM, "UNDERINSURED MOTORISTS"), (xl, "INCLUDED")])
    d.gap(3)
    d.line("SCHEDULE - NAMES OF INDIVIDUALS")
    d.line(DOC_INDIVIDUAL, x=LM + 24)
    d.gap(3)
    d.lines(["NOTE - WHEN UNINSURED MOTORISTS COVERAGE IS PROVIDED AT LIMITS HIGHER THAN",
             "THE BASIC LIMITS REQUIRED BY A FINANCIAL RESPONSIBILITY LAW, UNDER-",
             "INSURED MOTORISTS COVERAGE IS INCLUDED, UNLESS OTHERWISE NOTED.",
             "A. THIS ENDORSEMENT CHANGES ONLY THOSE COVERAGES WHERE A PREMIUM IS SHOWN",
             "IN THE SCHEDULE.", "B. CHANGES IN COVERED AUTOS LIABILITY COVERAGE",
             "1. ANY 'AUTO' YOU DON'T OWN, HIRE OR BORROW IS A COVERED 'AUTO' FOR",
             "LIABILITY COVERAGE WHILE BEING USED BY ANY INDIVIDUAL NAMED IN THE",
             "SCHEDULE OR BY HIS OR HER SPOUSE WHILE A RESIDENT OF THE SAME",
             "HOUSEHOLD EXCEPT:",
             "A. ANY 'AUTO' OWNED BY THAT INDIVIDUAL OR BY ANY MEMBER OF HIS OR",
             "HER HOUSEHOLD.",
             "B. ANY 'AUTO' USED BY THAT INDIVIDUAL OR HIS OR HER SPOUSE WHILE",
             "WORKING IN A BUSINESS OF SELLING, SERVICING, REPAIRING OR PARK-",
             "ING 'AUTOS'.", "2. THE FOLLOWING IS ADDED TO *WHO IS AN INSURED*:",
             "ANY INDIVIDUAL NAMED IN THE SCHEDULE AND HIS OR HER SPOUSE, WHILE A",
             "RESIDENT OF THE SAME HOUSEHOLD, ARE 'INSUREDS' WHILE USING ANY",
             "COVERED 'AUTO' DESCRIBED IN PARAGRAPH B.1. OF THIS ENDORSEMENT.",
             "DATE OF ISSUE 07/16/25 (BPP) CONTINUED"])


def p_auto_doc_2(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=93,
           footer=foot_emc("CA9910A 10-13", FOOT_AUTO))
    d.line("PAGE NO: 2 X")
    head_emc(d, POL_AUTO, label="POLICY NO:")
    d.lines(["C. CHANGES IN AUTO MEDICAL PAYMENTS AND UNINSURED AND UNDERINSURED MOTORISTS",
             "COVERAGES", "THE FOLLOWING IS ADDED TO *WHO IS AN INSURED*:",
             "ANY INDIVIDUAL NAMED IN THE SCHEDULE AND HIS OR HER 'FAMILY MEMBERS'",
             "ARE 'INSUREDS' WHILE 'OCCUPYING' OR WHILE A PEDESTRIAN WHEN BEING",
             "STRUCK BY ANY 'AUTO' YOU DON'T OWN EXCEPT:",
             "ANY 'AUTO' OWNED BY THAT INDIVIDUAL OR BY ANY 'FAMILY MEMBER'.",
             "D. CHANGES IN PHYSICAL DAMAGE COVERAGE",
             "ANY PRIVATE PASSENGER TYPE 'AUTO' YOU DON'T OWN, HIRE OR BORROW IS A",
             "COVERED 'AUTO' WHILE IN THE CARE, CUSTODY OR CONTROL OF ANY INDIVIDUAL",
             "NAMED IN THE SCHEDULE OR HIS OR HER SPOUSE WHILE A RESIDENT OF THE SAME",
             "HOUSEHOLD EXCEPT:",
             "1. ANY 'AUTO' OWNED BY THAT INDIVIDUAL OR BY ANY MEMBER OF HIS OR HER",
             "HOUSEHOLD.", "E. ADDITIONAL DEFINITION", "AS USED IN THIS ENDORSEMENT:",
             "'FAMILY MEMBER' MEANS A PERSON RELATED TO THE INDIVIDUAL NAMED IN THE",
             "SCHEDULE BY BLOOD, MARRIAGE OR ADOPTION WHO IS A RESIDENT OF THE",
             "INDIVIDUAL'S HOUSEHOLD, INCLUDING A WARD OR FOSTER CHILD.",
             # The real package prints the name first-last ("ERIN ROYAL"); the retest
             # spec prints it last-first on the schedule. Both printings sit under a
             # named-individual heading, so `named_individuals.printing_roles` finds
             # her whichever order extraction copies - item 11 then tests the 14 Sep
             # separation itself, not a name-order gap (reported separately).
             f"NAMED INDIVIDUAL SHOWN IN THE SCHEDULE: {DOC_INDIVIDUAL_REAL}",
             "INCLUDES COPYRIGHTED MATERIAL OF ISO PROPERTIES, INC., WITH ITS PERMISSION.",
             "DATE OF ISSUE 07/16/25 (BPP)"])


def p_ca0001(d):
    d.page(section="auto", carrier=CAR_MUT, real_page=94,
           footer=("CA 00 01 11 20 © Insurance Services Office, Inc., 2019 Page 1 of 13",))
    head_emc(d, POL_AUTO)
    d.gap(3)
    for t in ("COMMERCIAL AUTO", "CA 00 01 11 20"):
        d.line(t, font=("Helvetica", 8.2))
    d.line("BUSINESS AUTO COVERAGE FORM", font=("Helvetica-Bold", 9.2))
    d.gap(3)
    d.wrap("Various provisions in this Policy restrict coverage. Read the entire policy carefully "
           "to determine rights, duties and what is and is not covered. Throughout this Policy, "
           "the words \"you\" and \"your\" refer to the Named Insured shown in the Declarations. "
           "The words \"we\", \"us\" and \"our\" refer to the company providing this insurance.",
           font=FORM)
    d.gap(3)
    d.line("SECTION I - COVERED AUTOS", font=("Helvetica-Bold", 8.2))
    d.wrap("Item Two of the Declarations shows the \"autos\" that are covered \"autos\" for each "
           "of your coverages. The following numerical symbols describe the \"autos\" that may be "
           "covered \"autos\". The symbols entered next to a coverage on the Declarations "
           "designate the only \"autos\" that are covered \"autos\".", font=FORM)
    d.line("A. Description Of Covered Auto Designation Symbols", font=("Helvetica-Bold", 8.2))
    for sym, name, desc in [
        ("1", "Any \"Auto\"", ""),
        ("2", "Owned \"Autos\" Only", "Only those \"autos\" you own. This includes those \"autos\" "
         "you acquire ownership of after the Policy begins."),
        ("3", "Owned Private Passenger \"Autos\" Only", "Only the private passenger \"autos\" you "
         "own."),
        ("4", "Owned \"Autos\" Other Than Private Passenger", "Only those \"autos\" you own that "
         "are not of the private passenger type."),
        ("7", "Specifically Described \"Autos\"", "Only those \"autos\" described in Item Three "
         "of the Declarations for which a premium charge is shown."),
        ("8", "Hired \"Autos\" Only", "Only those \"autos\" you lease, hire, rent or borrow. "
         "This does not include any \"auto\" you lease, hire, rent or borrow from any of your "
         "\"employees\"."),
        ("9", "Non-owned \"Autos\" Only", "Only those \"autos\" you do not own, lease, hire, "
         "rent or borrow that are used in connection with your business."),
    ]:
        d.cells([(LM, sym, *FORM), (LM + 18, name, *FORM)], font=FORM)
        if desc:
            d.wrap(desc, font=FORM, x=LM + 190)


CA7450_P1 = [
    "The BUSINESS AUTO COVERAGE FORM is amended to include the following clarifications and "
    "extensions of coverage. With respect to coverage provided by this endorsement, the "
    "provisions of the Coverage Form apply unless modified by the endorsement.",
    "A. TEMPORARY SUBSTITUTE AUTO PHYSICAL DAMAGE - If Physical Damage Coverage is provided by "
    "this coverage form for an \"auto\" you own, the Physical Damage Coverages provided for that "
    "owned \"auto\" are extended to any \"auto\" you do not own while used with the permission "
    "of its owner as a temporary substitute for the covered \"auto\" you own that is out of "
    "service because of breakdown, repair, servicing, \"loss\" or destruction.",
    "B. BLANKET ADDITIONAL INSUREDS - Any person or organization whom you have agreed in a "
    "written contract or agreement to name as an additional \"insured\" under your \"auto\" "
    "Policy, but only with respects to liability arising out of the use of a covered \"auto\" "
    "you own, hire or borrow.",
    "C. EMPLOYEES AS INSUREDS - Any \"employee\" of yours is an \"insured\" while using a "
    "covered \"auto\" you don't own, hire or borrow in your business or your personal affairs.",
    "D. EMPLOYEE HIRED AUTOS - An \"employee\" of yours is an \"insured\" while operating an "
    "\"auto\" hired or rented under a contract or agreement in an \"employee's\" name, with your "
    "permission, while performing duties related to the conduct of your business.",
    "E. NEWLY FORMED OR ACQUIRED ORGANIZATIONS - Any organization which you acquire or form "
    "after the effective date of this Policy in which you maintain ownership or majority "
    "interest.",
]

CA7450_P3 = [
    "L. ELECTRONIC EQUIPMENT COVERAGE ADDED LIMITS - All electronic equipment that reproduces, "
    "receives or transmits audio, visual, or data signals in any one \"loss\" is $5,000, in "
    "addition to the sublimit in the Limits Of Insurance provision under Section III - Physical "
    "Damage Coverage.",
    "M. HIRED AUTO PHYSICAL DAMAGE - Section III - Physical Damage Coverage, A.4. Coverage "
    "Extensions is amended by adding the following: If hired \"autos\" are covered \"autos\" "
    "for Liability Coverage, and if Comprehensive, Specified Causes of Loss, or Collision "
    "Coverage is provided for any \"auto\" you own, then the Physical Damage coverages provided "
    "are extended to \"autos\" you lease, hire, rent or borrow, subject to the following limit "
    "and deductible:",
    "(1) The most we will pay for loss to any leased, hired, rented or borrowed \"auto\" is the "
    "lesser of up to a limit of $100,000, Actual Cash Value or Cost of Repair, minus the "
    "deductible.",
    "(2) The deductible will be equal to the largest deductible applicable to any owned "
    "\"auto\" for that coverage.",
    "We will pay up to $1,000, in addition to the limit above, for Loss Of Use of a hired auto "
    "to a leasing or rental concern for a monetary loss sustained, provided it results from an "
    "\"accident\" for which you are legally liable.",
    "N. AUTO LOAN/LEASE GAP COVERAGE - Autos of the private passenger, light or medium trucks "
    "that are loaned or leased for a period of six months or longer and which have been "
    "provided Physical Damage Coverage are covered \"autos\" under this Policy.",
]


def p_ca7450(d, real_page, page_of, body, schedule=False):
    d.page(section="auto", carrier=CAR_MUT, real_page=real_page,
           footer=("CA7450 M (09-24) Includes copyrighted material of ISO Properties, Inc. with "
                   f"its permission. Page {page_of} of 4",))
    head_emc(d, POL_AUTO)
    d.gap(3)
    d.line("COMMERCIAL AUTO", font=("Helvetica", 8.2))
    d.line("THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
           font=("Helvetica", 8.2))
    d.line("COMMERCIAL AUTO ELITE EXTENSION", font=("Helvetica-Bold", 9.2))
    d.line("This endorsement modifies insurance provided under the following:",
           font=("Helvetica", 8.2))
    d.line("BUSINESS AUTO COVERAGE FORM", font=("Helvetica", 8.2), x=LM + 24)
    if schedule:
        d.gap(4)
        d.line("SCHEDULE - HIRED AUTO PHYSICAL DAMAGE", font=("Helvetica-Bold", 8.4))
        xa = LM + 250
        for label, value in [("Limit - any one hired \"auto\"", "$100,000"),
                             ("Hired Auto Physical Damage - Comprehensive Deductible", "$1,000"),
                             ("Hired Auto Physical Damage - Collision Deductible", "$1,000"),
                             ("Loss Of Use - hired \"auto\"", "$1,000")]:
            d.cells([(LM + 12, label, *FORM), (xa, value, *FORM)], font=FORM)
    d.gap(4)
    d.two_col(body)


ISO_IL0021 = [
    "1. The insurance does not apply:",
    "A. Under any Liability Coverage, to \"bodily injury\" or \"property damage\": (1) With "
    "respect to which an \"insured\" under the policy is also an insured under a nuclear energy "
    "liability policy issued by Nuclear Energy Liability Insurance Association, Mutual Atomic "
    "Energy Liability Underwriters, Nuclear Insurance Association of Canada or any of their "
    "successors, or would be an insured under any such policy but for its termination upon "
    "exhaustion of its limit of liability; or",
    "(2) Resulting from the \"hazardous properties\" of \"nuclear material\" and with respect to "
    "which (a) any person or organization is required to maintain financial protection pursuant "
    "to the Atomic Energy Act of 1954, or any law amendatory thereof, or (b) the \"insured\" is, "
    "or had this policy not been issued would be, entitled to indemnity from the United States "
    "of America.",
    "B. Under any Medical Payments coverage, to expenses incurred with respect to \"bodily "
    "injury\" resulting from the \"hazardous properties\" of \"nuclear material\" and arising "
    "out of the operation of a \"nuclear facility\" by any person or organization.",
]

ISO_IL0228 = [
    "A. Paragraph 2. of the Cancellation Common Policy Condition is replaced by the following:",
    "2. If this policy has been in effect for less than 60 days, we may cancel this policy by "
    "mailing or delivering to the first Named Insured written notice of cancellation at least: "
    "a. 10 days before the effective date of cancellation if we cancel for nonpayment of "
    "premium; or b. 30 days before the effective date of cancellation if we cancel for any "
    "other reason.",
    "B. The following is added to the Cancellation Common Policy Condition: 7. If this policy "
    "has been in effect for 60 days or more, or is a renewal of a policy we issued, we may cancel "
    "this policy only for one or more of the following reasons: a. Nonpayment of premium; b. A "
    "false statement knowingly made by the insured on the application for insurance; or c. A "
    "substantial change in the exposure or risk other than that indicated in the application "
    "and underwritten as of the effective date of the policy unless the first Named Insured has "
    "notified us of the change and we accept such change.",
    "C. The following is added and supersedes any provisions to the contrary: NONRENEWAL - If "
    "we decide not to renew this policy, we will mail or deliver to the first Named Insured "
    "written notice of nonrenewal at least 45 days before the expiration date of the policy.",
    "D. If we decide to increase the premium or decrease the coverage benefits on renewal of "
    "this policy, we will mail or deliver written notice to the first Named Insured at least "
    "45 days before the expiration date.",
]


def build_auto(d):
    p_auto_dec(d)
    p_auto_dec_2(d)
    p_auto_endorsements(d)
    p_auto_um(d)
    p_auto_item3(d)
    p_auto_items45(d)
    p_auto_endorsement_premium(d)
    p_auto_doc(d)
    p_auto_doc_2(d)
    p_ca0001(d)
    p_ca7450(d, 117, 1, CA7450_P1)
    p_ca7450(d, 118, 3, CA7450_P3, schedule=True)
    iso_page(d, section="auto", carrier=CAR_MUT, head=_stamp_auto, real_page=132,
             top=["IL 00 21 09 08",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "NUCLEAR ENERGY LIABILITY EXCLUSION ENDORSEMENT (Broad Form)"],
             menu=["COMMERCIAL AUTOMOBILE COVERAGE PART",
                   "COMMERCIAL GENERAL LIABILITY COVERAGE PART", "FARM COVERAGE PART",
                   "LIQUOR LIABILITY COVERAGE PART",
                   "MEDICAL PROFESSIONAL LIABILITY COVERAGE PART",
                   "OWNERS AND CONTRACTORS PROTECTIVE LIABILITY COVERAGE PART",
                   "POLLUTION LIABILITY COVERAGE PART",
                   "PRODUCTS/COMPLETED OPERATIONS LIABILITY COVERAGE PART",
                   "RAILROAD PROTECTIVE LIABILITY COVERAGE PART",
                   "UNDERGROUND STORAGE TANK POLICY"],
             body=ISO_IL0021,
             footer=("IL 00 21 09 08 © ISO Properties, Inc., 2007 Page 1 of 2",))
    iso_page(d, section="auto", carrier=CAR_MUT, head=_stamp_auto, real_page=136,
             top=["IL 02 28 09 07",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "COLORADO CHANGES - CANCELLATION AND NONRENEWAL"],
             menu=["CAPITAL ASSETS PROGRAM (OUTPUT POLICY) COVERAGE PART",
                   "COMMERCIAL AUTOMOBILE COVERAGE PART",
                   "COMMERCIAL GENERAL LIABILITY COVERAGE PART",
                   "COMMERCIAL INLAND MARINE COVERAGE PART",
                   "COMMERCIAL LIABILITY UMBRELLA COVERAGE PART",
                   "COMMERCIAL PROPERTY COVERAGE PART", "CRIME AND FIDELITY COVERAGE PART",
                   "EMPLOYMENT-RELATED PRACTICES LIABILITY COVERAGE PART",
                   "EQUIPMENT BREAKDOWN COVERAGE PART", "FARM COVERAGE PART",
                   "FARM UMBRELLA LIABILITY POLICY", "LIQUOR LIABILITY COVERAGE PART",
                   "PRODUCTS/COMPLETED OPERATIONS LIABILITY COVERAGE PART"],
             body=ISO_IL0228,
             footer=("IL 02 28 09 07 © ISO Properties, Inc., 2006 Page 1 of 2",))


# -- Umbrella: Employers Mutual Casualty Company, 6J7-40-02---26 ---------------------

UMB_ENDORSEMENTS_1 = [
    ("*CU0001", "04-13", "COMM LIABILITY UMBRELLA COV FORM"),
    ("*CU0005", "12-23", "EXCL-VIOLATION/LAW ADDRESSING DATA"),
    ("*CU0146", "09-00", "CO CHANGES-REPRESENTATIONS OR FRAUD"),
    ("*CU2103", "09-00", "EXCL - DESIGNATED WORK"),
    ("", "", "DESCRIPTION OF YOUR WORK:"),
    ("", "", "ANY WORK ARISING OUT OF THE DESIGN,"),
    ("", "", "DEVELOPMENT, SITE PREPARATION, CONSTRUCTION,"),
    ("", "", "MARKETING, OR SALES OF MULTI-FAMILY"),
    ("", "", "HOUSING OR TRACT HOUSING AS DEFINED"),
    ("", "", "UNDER SECTION V-DEFINITIONS OF THE PRIMARY"),
    ("", "", "POLICY DESCRIBED IN SCHEDULE A."),
    ("*CU2123", "02-02", "NUCLEAR ENERGY LIAB EXCL BROAD FORM"),
    ("*CU2127", "12-04", "FUNGI OR BACTERIA EXCLUSION"),
    ("*CU2130", "01-15", "CAP OF LOSSES FROM CERT ACTS OF TERR"),
    ("*CU2136", "01-15", "EXCL PUNITIVE DMG CERT ACTS OF TERR"),
    ("*CU2150", "03-05", "SILICA OR SILICA RELATED DUST EXCL"),
    ("*CU2171", "06-15", "EXCLUSION-UNMANNED AIRCRAFT"),
    ("*CU2186", "12-23", "EXCL-ACCESS/DISCL OF CONFID/PERSONAL"),
    ("*CU3454", "05-23", "EXCL PERFLUOROALKYL/POLYFLUROALKYL"),
    ("*CU3456", "12-23", "CYBER INCIDENT"),
    ("*CU7001A", "11-15", "SCHED OF PRIMARY INS - AUTOMATED"),
    ("*CU7269", "08-06", "AGG LIMIT - PER LOC AGG FOR PREM OPS"),
    ("*CU7270", "08-06", "AGG LIMIT-PER PROJ AGG FOR PREM OPS"),
    ("*CU7276", "03-21", "COMMERCIAL UMBRELLA AMENDMENT OF COV"),
    ("*CU7293", "08-06", "FOREIGN EXPOSURE FOLLOWING FORM"),
    ("*CU7346", "11-20", "COMMUNICABLE DISEASE EXCLUSION"),
    ("*CU7404.1", "10-08", "UMBRELLA LIAB AMEND - FOLLOW FORM"),
    ("*CU7460", "12-15", "BLANKET WAIVER OF SUBROG WHEN REQUIR"),
    ("*CU7468", "01-17", "PRIMARY/NONCONT-OTHER INS-AUTOMATIC"),
    ("*CU7484", "01-22", "EXCL-ALL OPS COV/CONTROLLED WRAP UP"),
    ("*CU7486", "10-22", "CANNABIS EXCL/EXCP RETAIL SALES CBD"),
    ("*CU8160", "12-23", "CYBER INCIDENT/DATA PRIVACY EXCL PH"),
    ("*IL0017", "11-98", "COMMON POLICY CONDITIONS"),
]

UMB_ENDORSEMENTS_2 = [
    ("*IL0125", "11-13", "COLORADO CHANGES - CIVIL UNION"),
    ("*IL0228", "09-07", "CO CHANGES - CANCELLATION/NONRENEWAL"),
    ("*IL7004", "03-20", "MUTUAL POLICY PROVISIONS"),
    ("*IL7131A", "04-01", "COMM'L POLICY ENDORSEMENT SCHEDULE"),
    ("*IL7168", "01-22", "ASBESTOS EXCLUSION"),
    ("*IL7447", "05-15", "NOTICE OF CANCEL W/WRITTEN CONTRACT"),
    ("*IL7451", "03-17", "EXCL-SNOW/ICE PLOWING,RMVL OR TRTMNT"),
    ("*IL7602", "04-16", "COLORADO COMPANY ELIMINATION"),
    ("*IL8383.2A", "12-20", "DISCL PURSUANT TERRSM RISK INS. ACT $ 34"),
    ("*IL8384A", "01-08", "TERRORISM NOTICE"),
]


def p_umb_dec(d):
    d.page(section="umbrella", carrier=CAR_MUT, real_page=143,
           footer=(f"FORM CU7000A ED. 01-07 BPP 07/15/25 027 SB {FOOT_UMB} 2601",))
    d.cells([(LM, CAR_MUT), ("R", f"Policy Number: {POL_UMB}")])
    d.line("COMMERCIAL UMBRELLA DECLARATIONS")
    xb = LM + 300
    d.cells([(xb, "*------------------------*")])
    d.cells([(LM, "Policy Period: From 07/15/25 to 07/15/26"), (xb, "* Policy Number *")])
    d.cells([(xb, f"*{POL_UMB}*")])
    d.cells([(xb, "*------------------------*")])
    dec_identity_block(d, insured_label="NAMED INSURED", producer_label="PRODUCER")
    d.cells([(LM, "Insured is LLC"), (LM + 150, "Business Desc: COMMERCIAL GENERAL CONTRA")])
    d.line(DASH.strip())
    d.line("LIMITS OF INSURANCE")
    xa = LM + 380
    d.cells([(LM, "Each Occurrence Limit (Liability Coverage)"), (xa, "$ 3,000,000")])
    d.cells([(LM, "Personal & Advertising Injury Limit"), (xa, "$ 3,000,000")])
    d.line("(Any one person or organization)")
    d.cells([(LM, "Aggregate Limit (Liability Coverage)"), (xa, "$ 3,000,000")])
    d.line("(except with respect to \"covered autos\")")
    d.line("Coverage Form: CU7001A 11-15 Commercial Liability Umbrella Coverage Form")
    d.line("-" * 77)
    d.line("-" * 45)
    d.cells([(LM, "PREMIUM NOT SUBJECT TO AUDIT"), (xa, "$ 3,418.00")])
    d.line("-" * 45)
    d.lines(["A $100 MINIMUM POLICY PREMIUM APPLIES",
             "IF POLICY IS CANCELLED AFTER THE EFFECTIVE DATE.", "-" * 77, "Forms Applicable:",
             "CU0001(04/13)*, CU0005(12/23)*, CU0146(09/00)*, CU2103(09/00)*,",
             "CU2123(02/02)*, CU2127(12/04)*, CU2130(01/15)*, CU2136(01/15)*,",
             "CU2150(03/05)*, CU2171(06/15)*, CU2186(12/23)*, CU3454(05/23)*,",
             "CU3456(12/23)*, CU7001A(11/15)*, CU7269(08/06)*, CU7270(08/06)*,",
             "CU7276(03/21)*, CU7293(08/06)*, CU7346(11/20)*, CU7404.1(10/08)*,",
             "CU7460(12/15)*, CU7468(01/17)*, CU7484(01/22)*, CU7486(10/22)*,",
             "CU8160(12/23)*, IL0017(11/98)*, IL0125(11/13)*, IL0228(09/07)*,",
             "IL7004(03/20)*, IL7131A(04/01)*, IL7168(01/22)*, IL7447(05/15)*,",
             "IL7451(03/17)*, IL7602(04/16)*, IL8383.2A(12/20)*, IL8384A(01/08)*",
             "Date of Issue 07/16/25 BPP"])


def p_umb_endorsements(d, rows, real_page, page_label=None, continued=False):
    d.page(section="umbrella", carrier=CAR_MUT, real_page=real_page,
           footer=(f"FORM: IL7131A (ED. 04-01) 027 SB {FOOT_UMB} 2601",))
    if page_label:
        d.line(page_label)
    head_emc(d, POL_UMB)
    d.lines(["COMMERCIAL UMBRELLA POLICY", "DECLARATIONS", EQ, "ENDORSEMENT SCHEDULE",
             "EDITION"])
    d.cells([(LM, "FORM DATE"), (LM + 108, "DESCRIPTION/ADDITIONAL INFORMATION"),
             (LM + 400, "PREMIUM")])
    d.line(HR)
    schedule_table(d, rows)
    d.line("DATE OF ISSUE: 07/16/25 (CONTINUED)" if continued else "DATE OF ISSUE: 07/16/25")


def p_umb_schedule(d):
    d.page(section="umbrella", carrier=CAR_MUT, real_page=148,
           footer=(f"FORM CU7001A ED. 11-15 BPP 07/15/25 027 SB {FOOT_UMB} 2601",))
    # The real page prints this contract as "6J74002---26".
    d.cells([(LM, CAR_MUT), (X_MF_RIGHT, "Policy Number: 6J74002---26")])
    d.cells([(LM, INSURED), (X_MF_RIGHT, "Eff Date: 07/15/25 Exp Date: 07/15/26")])
    d.line(f"PRODUCER: {PRODUCER} AGENT: {AGENT_NO_MF}")
    d.lines(["COMMERCIAL UMBRELLA SCHEDULE", "*" * 76, "RETAINED LIMIT", "-" * 27])
    xa = LM + 300
    d.cells([(LM, "Self Insured Retention"), (xa, "$ 0")])
    d.lines(["SCHEDULE OF UNDERLYING INSURANCE", DASH.strip(), "Commercial General Liability",
             f"Company: {CAR_PC}"])
    d.cells([(LM, f"Policy Number: {POL_GL}"), (LM + 200, "Policy Period: 07/15/25 to 07/15/26")])
    d.lines(["Occurrence Basis", "Minimum Applicable Limits"])
    for label, value in [("General Aggregate", "$ 2,000,000"),
                         ("Products-Completed Operations Aggregate", "$ 2,000,000"),
                         ("Personal and Advertising Injury", "$ 1,000,000"),
                         ("Each Occurrence", "$ 1,000,000")]:
        d.cells([(LM, label), (xa, value)])
    d.lines([DASH.strip(), "Commercial Auto Liability", f"Company: {CAR_MUT_MIXED}"])
    d.cells([(LM, f"Policy Number: {POL_AUTO}"), (LM + 200, "Policy Period: 07/15/25 to 07/15/26")])
    d.line("Minimum Applicable Limits")
    d.cells([(LM, "Covered Auto Liability"), (xa, "$ 1,000,000 Each Accident")])
    d.lines([DASH.strip(), "Date of Issue 07/16/25 BPP"])


CU0001_P1 = [
    "Various provisions in this policy restrict coverage. Read the entire policy carefully to "
    "determine rights, duties and what is and is not covered.",
    "Throughout this policy the words \"you\" and \"your\" refer to the Named Insured shown in "
    "the Declarations, and any other person or organization qualifying as a Named Insured under "
    "this policy. The words \"we\", \"us\" and \"our\" refer to the company providing this "
    "insurance.",
    "SECTION I - COVERAGES",
    "COVERAGE A - BODILY INJURY AND PROPERTY DAMAGE LIABILITY",
    "1. Insuring Agreement",
    "a. We will pay on behalf of the insured the \"ultimate net loss\" in excess of the "
    "\"retained limit\" because of \"bodily injury\" or \"property damage\" to which this "
    "insurance applies. We will have the right and duty to defend the insured against any "
    "\"suit\" seeking damages for such \"bodily injury\" or \"property damage\" when the "
    "\"underlying insurance\" does not provide coverage or the limits of \"underlying "
    "insurance\" have been exhausted.",
    "b. This insurance applies to \"bodily injury\" or \"property damage\" that is subject to "
    "an applicable \"retained limit\". If any other limit, such as a sublimit, is specified in "
    "the \"underlying insurance\", this insurance does not apply to \"bodily injury\" or "
    "\"property damage\" arising out of that exposure unless that limit is specified in the "
    "Declarations under the Schedule of \"underlying insurance\".",
    "c. This insurance applies to \"bodily injury\" and \"property damage\" only if the "
    "\"bodily injury\" or \"property damage\" is caused by an \"occurrence\" that takes place "
    "in the \"coverage territory\" and occurs during the policy period.",
]


def p_cu72(d, form, title, body, real_page):
    iso_page(d, section="umbrella", carrier=CAR_MUT, head=_stamp_umb, real_page=real_page,
             top=["COMMERCIAL UMBRELLA",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "AGGREGATE LIMITS OF INSURANCE AMENDMENT", title],
             menu=["COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM"],
             menu_header="This endorsement modifies insurance coverage provided under the "
                         "following:",
             body=body, footer=(f"{form} Page 1 of 1",))


def build_umbrella(d):
    p_umb_dec(d)
    p_umb_endorsements(d, UMB_ENDORSEMENTS_1, 144, continued=True)
    p_umb_endorsements(d, UMB_ENDORSEMENTS_2, 145, page_label="PAGE NO: 2")
    p_tria_emc(d, "umbrella", POL_UMB, FOOT_UMB, "Terrorism Premium (Certified Acts) $34.00", 147)
    p_umb_schedule(d)
    iso_page(d, section="umbrella", carrier=CAR_MUT, head=_stamp_umb, real_page=149,
             top=["COMMERCIAL LIABILITY UMBRELLA", "CU 00 01 04 13",
                  "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM"],
             body=CU0001_P1,
             footer=("CU 00 01 04 13 © Insurance Services Office, Inc.,2012 "
                     "Page 1 of 18",))
    p_cu72(d, "CU7269(8-06)", "PER LOCATION AGGREGATE FOR PREMISES/OPERATIONS LIABILITY",
           ["Item 2 under Section III - Limits of Insurance is amended as follows by adding:",
            "C. As respects Excess Commercial General Liability Coverage other than excess "
            "Products/Completed Operations Hazard Coverage, the aggregate limit shall apply "
            "separately to each of your \"locations\" owned by or rented to you.",
            "\"Location\" means premises involving the same or connecting lots, or premises "
            "whose connection is interrupted only by a street, roadway, waterway or "
            "right-of-way of a railroad."], 182)
    p_cu72(d, "CU7270(8-06)", "PER PROJECT AGGREGATE FOR PREMISES/OPERATIONS LIABILITY",
           ["Item 2 under Section III - Limit of Insurance is amended as follows by adding:",
            "C. As respects Excess Commercial General Liability Coverage other than excess "
            "Products/Completed Operations Hazard Coverage, the aggregate limit shall apply "
            "separately to each of your projects away from premises owned by or rented to "
            "you."], 183)
    iso_page(d, section="umbrella", carrier=CAR_MUT, head=_stamp_umb, real_page=134,
             top=["IL 01 25 11 13",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "COLORADO CHANGES - CIVIL UNION"],
             menu=["COMMERCIAL AUTOMOBILE COVERAGE PART",
                   "COMMERCIAL GENERAL LIABILITY COVERAGE PART",
                   "COMMERCIAL LIABILITY UMBRELLA COVERAGE PART",
                   "ELECTRONIC DATA LIABILITY COVERAGE PART", "FARM COVERAGE PART",
                   "FARM UMBRELLA LIABILITY POLICY", "LIQUOR LIABILITY COVERAGE PART",
                   "MEDICAL PROFESSIONAL LIABILITY COVERAGE PART",
                   "OWNERS AND CONTRACTORS PROTECTIVE LIABILITY COVERAGE PART",
                   "POLLUTION LIABILITY COVERAGE PART", "PRODUCT WITHDRAWAL COVERAGE PART",
                   "PRODUCTS/COMPLETED OPERATIONS LIABILITY COVERAGE PART",
                   "UNDERGROUND STORAGE TANK POLICY"],
             body=["A. The term \"spouse\" is replaced by the following: Spouse or party to a "
                   "civil union recognized under Colorado law.",
                   "B. Under the Commercial Automobile Coverage Part, the term \"family "
                   "member\" is replaced by the following and supersedes any other provisions "
                   "to the contrary: \"Family member\" means a person related to the individual "
                   "Named Insured by blood, adoption, marriage or civil union recognized under "
                   "Colorado law, who is a resident of such Named Insured's household.",
                   "C. With respect to coverage for the ownership, maintenance or use of "
                   "\"covered autos\" provided under the Commercial Liability Umbrella Coverage "
                   "Part, the term \"family member\" is replaced by the same definition."],
             footer=("IL 01 25 11 13 © Insurance Services Office, Inc.,2013 Page 1 of 1",))
    # Shared conditions, printed between the umbrella and GL sections.
    iso_page(d, section="umbrella", carrier=CAR_MUT, head=_stamp_umb, real_page=204,
             top=["COMMERCIAL INTERLINE", "COLORADO COMPANY ELIMINATION ENDORSEMENT"],
             body=["The Colorado Insurance Department requires the company to explain by this "
                   "endorsement that: Employers Mutual Casualty Company, EMCASCO Insurance "
                   "Company, Union Insurance Company of Providence and EMC Property and "
                   "Casualty Company are licensed to do insurance business in Colorado, but: "
                   "Dakota Fire Insurance Company and Illinois EMCASCO Insurance Company are "
                   "not licensed companies in Colorado.",
                   "This endorsement in no way affects the coverage under the policy/bond to "
                   "which it is attached but is intended only to clarify the name of the "
                   "issuing company."],
             footer=("IL7602(4-16) Includes copyrighted material of ISO Properties, Inc. with "
                     "its permission.",))


# -- General Liability: EMC Property & Casualty Company, BBC7263-26 ------------------

GL_ENDORSEMENTS_1 = [
    ("CG 00 01", "04 13", "Commercial General Liability Coverage Form"),
    ("CG 00 69", "12 23", "Exclusion - Violation of Law Addressing Data Privacy"),
    ("CG 21 06", "12 23", "Exclusion- Access or Disclosure of Confidential or Personal"),
    ("", "", "Material or Information"),
    ("CG 21 47", "12 07", "Employment-Related Practices Exclusion"),
    ("CG 21 67", "12 04", "Fungi Or Bacteria Exclusion"),
    ("CG 21 70", "01 15", "Cap On Losses From Certified Acts Of Terrorism"),
    ("CG 21 76", "01 15", "Exclusion Of Punitive Damages Related To A Certified Act Of"),
    ("", "", "Terrorism"),
    ("CG 21 96", "03 05", "Silica Or Silica-Related Dust Exclusion"),
    ("CG 22 79", "04 13", "Exclusion - Contractors - Professional Liability"),
    ("CG 40 28", "09 22", "Broad Abuse Or Molestation Exclusion"),
    ("CG 40 32", "05 23", "Exclusion-Perfluoroalkyl and Polyfluoroalkyl Substances"),
    ("CG 40 35", "12 23", "Exclusion - Cyber Incident"),
    ("CG 70 01A", "10 12", "General Liability Schedule"),
    ("CG 70 03", "10 13", "GL Quick Reference (Occurrence)"),
    ("CG 72 76", "11 16", "Limited Pollution Coverage - Work Sites"),
    ("", "", "Each Pollution Incident Limit - $1,000,000"),
    ("", "", "Pollution Liability Aggregate Limit - $1,000,000"),
    ("", "", "Property Damage Deductible $1,000 Each Pollution Incidents"),
    ("CG 77 40", "11 20", "Communicable Disease Exclusion - Pandemic, Epidemic or Public"),
    ("", "", "Health Emergency"),
    ("CG 77 43", "01 22", "Exclusion- All Operations Covered by a Controlled (Wrap-Up)"),
    ("", "", "Insurance Program"),
    ("CG 77 48", "10 22", "Cannabis Exclusion With Limited Exception For Retail Sales Of"),
    ("", "", "CBD Products And Hemp Exception"),
    ("CG 77 59", "05 23", "Contractors General Liability Elite Extensions"),
]

GL_ENDORSEMENTS_2 = [
    ("CG 77 62", "05 23", "Exclusion Multi Family and Tract Housings"),
    ("CG 83 18", "12 23", "Cyber Incident and Data Privacy Exclusion Endorsement Advisory"),
    ("", "", "Notice to Policyholders"),
    ("CG 99 09", "12 19", "Premium Audit Noncompliance Charge"),
    ("", "", "Audit Noncompliance Charge Factor 1"),
    ("", "", "Number of Written Attempts To Obtain Audit Information 2"),
    ("", "", "Reassessment Charge 0"),
    ("IL 00 17", "11 98", "Common Policy Conditions"),
    ("IL 00 21", "09 08", "Nuclear Energy Liability Exclusion Endorsement"),
    ("IL 01 25", "11 13", "Colorado Changes - Civil Union"),
    ("IL 02 28", "09 07", "Colorado Changes - Cancellation And Nonrenewal"),
    ("IL 70 04", "03 20", "Mutual Policy Provisions"),
    ("IL 71 31A", "04 01", "Commercial Policy Endorsement Schedule"),
    ("IL 71 68", "01 22", "Asbestos Exclusion"),
    ("IL 74 47", "05 15", "Notice Of Cancellation Provided By Us To Person(S) Or"),
    ("", "", "Organization(S) With Whom You Have Agreed In A Written"),
    ("", "", "Contract Or Agreement"),
    ("IL 74 51", "03 17", "Exclusion - Snow And Ice Plowing, Removal Or Treatment"),
    ("IL 76 02", "04 16", "Colorado Company Elimination Endorsement"),
    ("IL 83 83.2A", "12 20", "Disclosure Pursuant To Terrorism Risk Insurance Act $31.00"),
    ("IL 83 84A", "01 08", "Notice"),
    ("IL 85 76", "10 17", "Important Notice To Policyholders"),
    ("IL 87 42", "03 17", "Important Notice To Policyholders"),
]


def p_gl_dec(d):
    d.page(section="general_liab", carrier=CAR_PC, real_page=205,
           footer=foot_gl("Form CG7000A Ed. 08-99"))
    head_gl(d, first=True)
    d.line("General Liability Declarations", font=SANS_BOLD, lead=14)
    xr = LM + 280
    d.pair(["Named Insured", INSURED, ADDR1, CITY, "DIRECT BILL"],
           ["Producer", PRODUCER, PRODUCER_ADDR1, PRODUCER_CITY, f"AGENT NO. {AGENT_NO_GL}",
            f"AGENT PHONE: {AGENT_PHONE}", "CLAIM REPORTING: 888-362-2255",
            "SERVICING CARRIER: 720-200-3700"], xr, font=SANS)
    d.gap(4)
    d.line("Organization Type: LLC", font=SANS)
    d.gap(4)
    d.line("Limits of Insurance", font=SANS_BOLD, lead=13)
    xa = LM + 300
    for label, value in [("Each Occurrence Limit", "$1,000,000"),
                         ("Damage To Premises Rented To You Limit", "$500,000(any one premises)"),
                         ("Medical Expense Limit", "$10,000(any one person)"),
                         ("Personal and Advertising Injury Limit",
                          "$1,000,000(any one person or organization)"),
                         ("General Aggregate Limit", "$2,000,000"),
                         ("Products/Completed Operations Aggregate Limit", "$2,000,000")]:
        d.cells([(LM, label), (xa, value)], font=SANS)
    d.gap(3)
    d.line("Coverage Form: CG 00 01 04 13 Commercial General Liability Coverage Form - "
           "Occurrence", font=SANS)
    d.gap(3)
    d.line("Coverages Provided", font=SANS_BOLD, lead=13)
    for label, value in [("Products/Completed Operations", "$1,198.00"),
                         ("Other Than Products/Completed Operations", "$2,756.00"),
                         ("Total Estimated Policy Premium", "$3,954.00")]:
        d.cells([(LM, label), (xa, value)], font=SANS)
    d.gap(4)
    d.line("See attached schedule for location of all premises owned, rented or occupied.",
           font=SANS)
    d.gap(10)
    d.line("Date of Issue: 07/16/2025", font=SANS)


def p_gl_forms(d):
    d.page(section="general_liab", carrier=CAR_PC, real_page=206,
           footer=foot_gl("Form CG7000A Ed. 08-99"))
    head_gl(d)
    d.line("Forms Applicable", font=SANS_BOLD, lead=13)
    d.lines(["CG0001(04/13), CG0069(12/23), CG2106(12/23), CG2147(12/07), CG2167(12/04), "
             "CG2170(01/15), CG2176(01/15),",
             "CG2196(03/05), CG2279(04/13), CG4028(09/22), CG4032(05/23), CG4035(12/23), "
             "CG7001A(10/12), CG7003(10/13),",
             "CG7276(11/16), CG7740(11/20), CG7743(01/22), CG7748(10/22), CG7759(05/23), "
             "CG7762(05/23), CG8318(12/23),",
             "CG9909(12/19), IL0017(11/98), IL0021(09/08), IL0125(11/13), IL0228(09/07), "
             "IL7004(03/20), IL7131A(04/01),",
             "IL7168(01/22), IL7447(05/15), IL7451(03/17), IL7602(04/16), IL8383.2A(12/20), "
             "IL8384A(01/08), IL8576(10/17),",
             "IL8742(03/17)"], font=("Helvetica", 7.6))
    d.gap(6)
    d.line("Audit Period: Annual", font=SANS)
    d.gap(6)
    d.line("Date of Issue: 07/16/2025", font=SANS)


def p_gl_endorsements(d, rows, real_page, title=True):
    d.page(section="general_liab", carrier=CAR_PC, real_page=real_page,
           footer=foot_gl("Form IL7131A Ed. 04-01"))
    head_gl(d)
    if title:
        d.line("Commercial General Liability Policy Declarations", font=SANS_BOLD, lead=13)
        d.line("Endorsement Schedule", font=SANS_BOLD, lead=13)
    c1, c2, c3 = LM, LM + 56, LM + 96
    d.cells([(c1, "Form"), (c2, "Edition"), (c3 + 12, "Description/Additional Information"),
             (LM + 440, "Premium")], font=("Helvetica-Bold", 8.0))
    d.cells([(c2, "Date")], font=("Helvetica-Bold", 8.0))
    for form, ed, desc in rows:
        cells = [(c3 + 12, desc)]
        if form:
            cells = [(c1, form), (c2 if len(form) < 10 else c2 + 6, ed)] + cells
        d.cells(cells, font=("Helvetica", 8.0))
    d.gap(4)
    d.line("Date of Issue: 07/16/2025", font=SANS)


def p_gl_tria(d):
    d.page(section="general_liab", carrier=CAR_PC, real_page=210,
           footer=foot_gl("Form IL8383.2A Ed. 12-20"))
    head_gl(d)
    d.wrap("This endorsement is attached to and made part of your policy in response to the "
           "disclosure requirements of the Terrorism Risk Insurance Act. This endorsement does "
           "not grant any coverage or change the terms and conditions of any coverage under the "
           "policy.", font=SANS)
    d.line("Disclosure Pursuant to Terrorism Risk Insurance Act", font=SANS_BOLD)
    d.line("Schedule", font=SANS_BOLD)
    d.line("Terrorism Premium (Certified Acts) $31.00", font=SANS)
    for para in ["A. Disclosure Of Premium: In accordance with the federal Terrorism Risk "
                 "Insurance Act, we are required to provide you with a notice disclosing the "
                 "portion of your premium, if any, attributable to coverage for terrorism acts "
                 "certified under the Terrorism Risk Insurance Act.",
                 "B. Disclosure Of Federal Participation In Payment Of Terrorism Losses: The "
                 "United States Government, Department of the Treasury, will pay a share of "
                 "terrorism losses insured under the federal program.",
                 "C. Cap On Insurer Participation In Payment Of Terrorism Losses: If aggregate "
                 "insured losses attributable to terrorist acts certified under the Terrorism "
                 "Risk Insurance Act exceed $100 billion in a calendar year, we shall not be "
                 "liable for the payment of any portion of the amount of such losses that "
                 "exceeds $100 billion."]:
        d.wrap(para, font=SANS)
    d.gap(6)
    d.line("Date of Issue: 07/16/2025 Includes copyrighted material of ISO Properties, Inc. with "
           "its permission.", font=("Helvetica", 7.6))


def p_gl_schedule(d):
    d.page(section="general_liab", carrier=CAR_PC, real_page=211,
           footer=foot_gl("Form CG7001A Ed. 10-12"))
    head_gl(d)
    d.line("General Liability Schedule", font=SANS_BOLD, lead=13)
    r1, r2, r3, r4 = LM + 250, LM + 300, LM + 360, LM + 410
    f = ("Helvetica", 8.2)
    d.cells([(r1, "Products/"), (r2, "Products/")], font=f)
    d.cells([(r1, "Compl Ops"), (r2, "Compl Ops"), (r3, "All Other"), (r4, "All Other")], font=f)
    d.cells([(LM, "Code No./Exposure/Classification"), (r1, "Rate"), (r2, "Advance Prem"),
             (r3, "Rate"), (r4, "Advance Prem")], font=f)
    d.line("Location 000", font=SANS_BOLD)
    d.cells([(LM, "Fungi Or Bacteria Exclusion"), (r2, "($33)")], font=f)
    d.cells([(LM, "Limited Pollution Coverage - Work Sites"), (r2, "$150")], font=f)
    d.line("Location 001", font=SANS_BOLD)
    d.cells([(LM, "91580 Contractors - Executive Supervisors"), (r1, "33.211"), (r2, "$1,305")],
            font=f)
    d.lines(["or Executive Superintendents", "Prem Basis: Payroll", "Exposure: $39,300",
             "Products/Completed Operations are", "subject to the General Aggregate Limit"],
            font=f)
    d.cells([(LM, "91585 Contrctrs-sub work-in connection"), (r1, "3.4240"), (r2, "$1,198"),
             (r3, "2.293"), (r4, "$803")], font=f)
    d.lines(["w/constrctn,recon,repr,erctn of buildings -", "NOC", "Prem Basis: Total Cost",
             "Exposure: $350,000"], font=f)
    d.gap(6)
    d.line("Policy Level Coverages", font=SANS_BOLD)
    d.cells([(LM, "Coverages"), (r1, "Limit of Insurance"), (r4, "Premium")], font=f)
    d.cells([(LM, "General Liability Elite Extension"), (r4, "$500")], font=f)
    d.cells([(LM, "Premium For Certified Acts of Terrorism"), (r4, "$31.00")], font=f)
    d.cells([(LM, "Total Estimated Policy Premium"), (r4, "$3,954.00")], font=f)
    d.gap(8)
    d.line("Date of Issue: 07/16/2025", font=SANS)


def p_gl_locations(d):
    d.page(section="general_liab", carrier=CAR_PC, real_page=212,
           footer=foot_gl("Form CG7001A Ed. 10-12"))
    head_gl(d)
    d.line("Location of All Premises Owned, Rented or Occupied", font=SANS_BOLD, lead=13)
    d.line("Rated Locations", font=SANS_BOLD, lead=13)
    y = d.y
    d.c.setFont(*SANS)
    d.c.drawString(LM, y, "4800 Dahlia St # D13")
    d.c.drawString(LM + 250, y - 6, "Location 1")
    d.c.drawString(LM, y - 12, "Denver, CO 80216-3121")
    d.y = y - 30
    d.line("Date of Issue: 07/16/2025", font=SANS)


CG0001_P1 = [
    "Various provisions in this policy restrict coverage. Read the entire policy carefully to "
    "determine rights, duties and what is and is not covered.",
    "Throughout this policy the words \"you\" and \"your\" refer to the Named Insured shown in "
    "the Declarations, and any other person or organization qualifying as a Named Insured under "
    "this policy. The words \"we\", \"us\" and \"our\" refer to the company providing this "
    "insurance.",
    "SECTION I - COVERAGES",
    "COVERAGE A - BODILY INJURY AND PROPERTY DAMAGE LIABILITY",
    "1. Insuring Agreement",
    "a. We will pay those sums that the insured becomes legally obligated to pay as damages "
    "because of \"bodily injury\" or \"property damage\" to which this insurance applies. We "
    "will have the right and duty to defend the insured against any \"suit\" seeking those "
    "damages.",
    "b. This insurance applies to \"bodily injury\" and \"property damage\" only if: (1) The "
    "\"bodily injury\" or \"property damage\" is caused by an \"occurrence\" that takes place in "
    "the \"coverage territory\"; (2) The \"bodily injury\" or \"property damage\" occurs during "
    "the policy period; and (3) Prior to the policy period, no insured knew that the \"bodily "
    "injury\" or \"property damage\" had occurred, in whole or in part.",
    "c. \"Bodily injury\" or \"property damage\" which occurs during the policy period and was "
    "not, prior to the policy period, known to have occurred by any insured includes any "
    "continuation, change or resumption of that \"bodily injury\" or \"property damage\" after "
    "the end of the policy period.",
]

CG7759_P1 = [
    "The COMMERCIAL GENERAL LIABILITY COVERAGE FORM is amended to include the following "
    "clarifications and extensions of coverage. The provisions of the Coverage Form apply "
    "unless modified by endorsement.",
    "A. EXPECTED OR INTENDED INJURY - Section I - Coverage A, Exclusion a. is amended as "
    "follows: a. \"Bodily injury\" or \"property damage\" expected or intended from the "
    "standpoint of an insured. This exclusion does not apply to \"bodily injury\" or "
    "\"property damage\" resulting from the use of reasonable force to protect persons or "
    "property.",
    "B. NON-OWNED WATERCRAFT - Section I - Coverage A, Exclusion g. (2) is amended as follows: "
    "A watercraft you do not own that is less than 51 feet long and not being used to carry "
    "persons or property for a charge.",
    "C. BLANKET ADDITIONAL INSURED - Any person or organization for whom you are performing "
    "operations when you and such person or organization have agreed in writing in a contract "
    "or agreement that such person or organization be added as an additional insured on your "
    "policy.",
]

CG7759_P5 = [
    "W. CONTRACTUAL LIABILITY (RAILROADS) - Definition 9. Insured Contract is amended as "
    "follows: Paragraph c. is deleted in its entirety and replaced with the following: Any "
    "easement or license agreement.",
    "X. AGGREGATE LIMITS PER PROJECT - The General Aggregate Limit applies separately to each "
    "of your construction projects away from premises owned by or rented to you.",
    "Y. AGGREGATE LIMITS PER LOCATION - The General Aggregate Limit applies separately to each "
    "of your locations, but only when required by written contract, written agreement, or "
    "certificate of insurance. Your locations are premises you own, rent or use involving the "
    "same or connecting lots or premises whose connection is interrupted only by a street, "
    "roadway, waterway, or right-of-way of a railroad. However, your locations do not include "
    "any premises where you, or others acting on your behalf, are performing construction "
    "operations.",
    "Z. CONTRACTUAL LIABILITY - PERSONAL AND ADVERTISING INJURY - Under SECTION I - COVERAGE "
    "B., Paragraph 2. Exclusions, Paragraph e. Contractual Liability is deleted.",
    "AA. MOBILE EQUIPMENT - Under the Section V - Definitions, Paragraph f.(1)(a), (b) and (c) "
    "of Mobile Equipment does not apply to self-propelled vehicles of less than 1,000 pounds "
    "gross vehicle weight.",
]

IL0003_BODY = [
    "The following is added: The premium shown in the Declarations was computed based on rates "
    "in effect at the time the policy was issued. On each renewal, continuation, or "
    "anniversary of the effective date of this policy, we will compute the premium in "
    "accordance with our rates and rules then in effect.",
    "The listing of coverage parts above identifies the coverage parts to which this "
    "endorsement may apply. It does not itself grant coverage and it does not indicate that "
    "any listed coverage part is part of this policy. The coverage parts forming part of this "
    "policy are shown in the Declarations.",
]


def build_gl(d):
    p_gl_dec(d)
    p_gl_forms(d)
    p_gl_endorsements(d, GL_ENDORSEMENTS_1, 207)
    p_gl_endorsements(d, GL_ENDORSEMENTS_2, 208, title=False)
    p_gl_tria(d)
    p_gl_schedule(d)
    p_gl_locations(d)
    iso_page(d, section="general_liab", carrier=CAR_PC, head=_stamp_gl, real_page=213,
             top=["COMMERCIAL GENERAL LIABILITY", "CG 00 01 04 13",
                  "COMMERCIAL GENERAL LIABILITY COVERAGE FORM"],
             body=CG0001_P1,
             footer=("CG 00 01 04 13 © Insurance Services Office, Inc.,2012 "
                     "Page 1 of 16",))
    iso_page(d, section="general_liab", carrier=CAR_PC, head=_stamp_gl, real_page=249,
             top=["COMMERCIAL GENERAL LIABILITY",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "CONTRACTORS GENERAL LIABILITY ELITE EXTENSIONS"],
             menu=["COMMERCIAL GENERAL LIABILITY COVERAGE FORM"], body=CG7759_P1,
             footer=("CG7759(5-23) Includes copyrighted material of ISO Properties, Inc. with "
                     "its permission. Page 1 of 5",))
    iso_page(d, section="general_liab", carrier=CAR_PC, head=_stamp_gl, real_page=253,
             top=["COMMERCIAL GENERAL LIABILITY",
                  "CONTRACTORS GENERAL LIABILITY ELITE EXTENSIONS (CONTINUED)"],
             body=CG7759_P5,
             footer=("CG7759(5-23) Includes copyrighted material of ISO Properties, Inc. with "
                     "its permission. Page 5 of 5",))
    iso_page(d, section="general_liab", carrier=CAR_PC, head=_stamp_gl, real_page=None,
             top=["IL 00 03 09 08",
                  "THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.",
                  "CALCULATION OF PREMIUM"],
             menu=MENU_LINES, menu_header=MENU_HEADER, body=IL0003_BODY,
             footer=("IL 00 03 09 08 © ISO Properties, Inc., 2007 Page 1 of 1",))


def build_policy(path):
    d = _Doc(path, "2526 Package Policy (Complete Copy)")
    p_common_1(d)
    p_common_2(d)
    build_im(d)
    build_auto(d)
    build_umbrella(d)
    build_gl(d)
    d.save()
    return d.meta


# ── 2. THE CERTIFICATE (ACORD 25 look-alike) ────────────────────────────────

def build_certificate(path):
    """ACORD 25 look-alike. Every string is measured and checked against every
    other string on its baseline before it is drawn - a label overlapping its
    amount makes pdfplumber riffle the two ("occ$u5rr0e0n,c0e0)0"), which is a
    defect of the fixture, not of the pipeline under test."""
    c = canvas.Canvas(path, pagesize=LETTER, pageCompression=1)
    c.setTitle("Certificate of Liability Insurance")
    c.setAuthor("Primble retest kit (synthetic copy of a client certificate)")
    c.setCreator("make_orbin_retest_pdfs.py")
    L, R = 0.4 * inch, PAGE_W - 0.4 * inch
    MID = L + 290
    placed = []                                   # (x0, x1, baseline, text)

    def _register(x0, x1, y, s, glued_to_left=False):
        for a0, a1, ay, t in placed:
            if glued_to_left and a1 <= x0 and x0 - a1 <= GLUE + 0.5:
                continue                           # the deliberate label:value glue
            if abs(ay - y) < 3.2 and x0 < a1 + 3.5 and a0 < x1 + 3.5:
                raise RuntimeError(f"certificate text collides: {t!r} / {s!r}")
        placed.append((x0, x1, y, s))

    def txt(x, y, s, font="Helvetica", size=7.0, align="l"):
        w = stringWidth(s, font, size)
        if align == "r":
            x = x - w
        if x < L - 0.5 or x + w > R + 0.5:
            raise RuntimeError(f"certificate text runs off the page: {s!r}")
        _register(x, x + w, y, s)
        c.setFont(font, size)
        c.drawString(x, y, s)
        return x + w

    def glued(x, y, s, font="Helvetica", size=7.4):
        """Words with a visible gap but NO space glyph: pdfplumber returns them
        run-together, exactly how the client's certificate OCR reads."""
        x0 = x
        for word in s.split(" "):
            c.setFont(font, size)
            c.drawString(x, y, word)
            x += stringWidth(word, font, size) + GLUE
        _register(x0, x - GLUE, y, s, glued_to_left=True)
        return x - GLUE

    def hline(y, x0=L, x1=R, w=0.6):
        c.setLineWidth(w)
        c.line(x0, y, x1, y)

    def vline(x, y0, y1, w=0.6):
        c.setLineWidth(w)
        c.line(x, y0, x, y1)

    def paragraph(y, text, size=5.9, lead=7.4):
        cur = ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if stringWidth(trial, "Helvetica", size) <= R - L:
                cur = trial
            else:
                txt(L, y, cur, "Helvetica", size)
                y -= lead
                cur = word
        if cur:
            txt(L, y, cur, "Helvetica", size)
            y -= lead
        return y

    y = PAGE_H - 0.45 * inch
    txt(L, y - 4, "ACORD", "Helvetica-Bold", 16)
    txt(L + 150, y - 2, "CERTIFICATE OF LIABILITY INSURANCE", "Helvetica-Bold", 13)
    txt(R, y + 4, "DATE (MM/DD/YYYY)", "Helvetica", 6, align="r")
    txt(R, y - 7, COI_DATE, "Helvetica", 8, align="r")
    y -= 22
    hline(y + 8)
    y = paragraph(y, "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY AND CONFERS NO "
                     "RIGHTS UPON THE CERTIFICATE HOLDER. THIS CERTIFICATE DOES NOT "
                     "AFFIRMATIVELY OR NEGATIVELY AMEND, EXTEND OR ALTER THE COVERAGE AFFORDED "
                     "BY THE POLICIES BELOW. THIS CERTIFICATE OF INSURANCE DOES NOT CONSTITUTE A "
                     "CONTRACT BETWEEN THE ISSUING INSURER(S), AUTHORIZED REPRESENTATIVE OR "
                     "PRODUCER, AND THE CERTIFICATE HOLDER.")
    y = paragraph(y, "IMPORTANT: If the certificate holder is an ADDITIONAL INSURED, the "
                     "policy(ies) must have ADDITIONAL INSURED provisions or be endorsed. If "
                     "SUBROGATION IS WAIVED, subject to the terms and conditions of the policy, "
                     "certain policies may require an endorsement. A statement on this "
                     "certificate does not confer rights to the certificate holder in lieu of "
                     "such endorsement(s).")
    y -= 2
    hline(y + 6)
    top_blocks = y + 6

    # PRODUCER (left) | CONTACT (right)
    txt(L, y - 2, "PRODUCER", "Helvetica-Bold", 6.2)
    txt(MID + 4, y - 2, "CONTACT", "Helvetica-Bold", 6.2)
    txt(MID + 4, y - 9, "NAME:", "Helvetica-Bold", 6.2)
    txt(MID + 40, y - 9, CONTACT, "Helvetica", 8)
    txt(L + 6, y - 14, PRODUCER_MIXED, "Helvetica", 8)
    x = txt(MID + 4, y - 22, "PHONE (A/C, No, Ext):", "Helvetica-Bold", 6.2)
    x = txt(x + 5, y - 22, "(303) 996-7800", "Helvetica", 8)
    x = txt(x + 12, y - 22, "FAX (A/C, No):", "Helvetica-Bold", 6.2)
    txt(x + 5, y - 22, "(303) 757-7719", "Helvetica", 8)
    txt(L + 6, y - 26, "9780 S Meridian Blvd Ste 400", "Helvetica", 8)
    x = txt(MID + 4, y - 33, "E-MAIL ADDRESS:", "Helvetica-Bold", 6.2)
    txt(x + 5, y - 33, CONTACT_EMAIL, "Helvetica", 8)
    txt(L + 6, y - 38, "Englewood CO 80112", "Helvetica", 8)
    hline(y - 38, MID, R)
    txt(MID + 60, y - 46, "INSURER(S) AFFORDING COVERAGE", "Helvetica-Bold", 6.2)
    txt(R - 4, y - 46, "NAIC #", "Helvetica-Bold", 6.2, align="r")
    hline(y - 49, MID, R)

    # INSURER rows: the label, then the value drawn GLUED to it (no space glyph).
    rows = [("INSURER A :", "EMC Property & Casualty Company", NAIC_PC),
            ("INSURER B :", "Employers Mutual Casualty Co.", NAIC_MUT),
            ("INSURER C :", "", ""), ("INSURER D :", "", ""), ("INSURER E :", "", ""),
            ("INSURER F :", "", "")]
    ry = y - 58
    row_ys = []
    for label, value, naic in rows:
        lx = txt(MID + 4, ry, label, "Helvetica-Bold", 7)
        if value:
            glued(lx + GLUE, ry, value, "Helvetica", 7.4)
            txt(R - 4, ry, naic, "Helvetica", 7.4, align="r")
        hline(ry - 3, MID, R, 0.3)
        row_ys.append(ry)
        ry -= 11
    # INSURED (left) sits on its OWN baselines, half a row below each insurer
    # row, so every INSURER line reads as a line of its own - as the client's
    # certificate OCR does.
    txt(L, row_ys[0] - 5.5, "INSURED", "Helvetica-Bold", 6.2)
    for i, s in enumerate([INSURED_MIXED, "4800 Dahlia St # D13", "Denver CO 80216-3121"]):
        txt(L + 6, row_ys[i + 1] - 5.5, s, "Helvetica", 8)
    y = ry - 2
    hline(y + 6)
    vline(MID, top_blocks, y + 6)

    # COVERAGES
    txt(L, y - 3, "COVERAGES", "Helvetica-Bold", 7.4)
    txt(L + 150, y - 3, "CERTIFICATE NUMBER:", "Helvetica-Bold", 6.4)
    txt(L + 380, y - 3, "REVISION NUMBER:", "Helvetica-Bold", 6.4)
    y -= 11
    y = paragraph(y, "THIS IS TO CERTIFY THAT THE POLICIES OF INSURANCE LISTED BELOW HAVE BEEN "
                     "ISSUED TO THE INSURED NAMED ABOVE FOR THE POLICY PERIOD INDICATED. "
                     "NOTWITHSTANDING ANY REQUIREMENT, TERM OR CONDITION OF ANY CONTRACT OR OTHER "
                     "DOCUMENT WITH RESPECT TO WHICH THIS CERTIFICATE MAY BE ISSUED OR MAY "
                     "PERTAIN, THE INSURANCE AFFORDED BY THE POLICIES DESCRIBED HEREIN IS SUBJECT "
                     "TO ALL THE TERMS, EXCLUSIONS AND CONDITIONS OF SUCH POLICIES. LIMITS SHOWN "
                     "MAY HAVE BEEN REDUCED BY PAID CLAIMS.")
    hline(y + 4)
    cx = {"ltr": L + 2, "type": L + 20, "sub2": L + 85, "addl": L + 166, "subr": L + 186,
          "pol": L + 206, "eff": L + 284, "exp": L + 328, "lim": L + 374, "amt": R - 3}
    for key, (a, b) in {"ltr": ("INSR", "LTR"), "addl": ("ADDL", "INSD"),
                        "subr": ("SUBR", "WVD")}.items():
        txt(cx[key], y - 3, a, "Helvetica-Bold", 5.4)
        txt(cx[key], y - 9, b, "Helvetica-Bold", 5.4)
    txt(cx["type"] + 34, y - 6, "TYPE OF INSURANCE", "Helvetica-Bold", 6.2)
    txt(cx["pol"] + 12, y - 6, "POLICY NUMBER", "Helvetica-Bold", 6.2)
    for key, a in (("eff", "POLICY EFF"), ("exp", "POLICY EXP")):
        txt(cx[key], y - 3, a, "Helvetica-Bold", 5.6)
        txt(cx[key], y - 9, "(MM/DD/YYYY)", "Helvetica-Bold", 5.0)
    txt(cx["lim"] + 60, y - 6, "LIMITS", "Helvetica-Bold", 6.2)
    y -= 12
    hline(y)
    y -= 9

    def cov_row(lines, *, ltr="", pol="", dates=False):
        """lines: [(type text, second type column, addl-column mark, limit label, amount)]"""
        nonlocal y
        start = y
        for i, (left, left2, mark, lim_label, lim_amt) in enumerate(lines):
            if i == 0 and ltr:
                txt(cx["ltr"] + 3, y, ltr, "Helvetica", 7.4)
            if left:
                txt(cx["type"], y, left, "Helvetica", 5.6)
            if left2:
                txt(cx["sub2"], y, left2, "Helvetica", 5.6)
            if mark:
                txt(cx["addl"], y, mark, "Helvetica", 5.6)
            if i == 0 and pol:
                txt(cx["pol"], y, pol, "Helvetica", 7.4)
            if i == 0 and dates:
                txt(cx["eff"], y, "7/15/2025", "Helvetica", 7.4)
                txt(cx["exp"], y, "7/15/2026", "Helvetica", 7.4)
            if lim_label:
                txt(cx["lim"], y, lim_label, "Helvetica", 5.6)
            if lim_amt:
                txt(cx["amt"], y, lim_amt, "Helvetica", 7.4, align="r")
            y -= 9.2
        hline(y + 6)
        for xx in (cx["type"] - 3, cx["addl"] - 3, cx["pol"] - 3, cx["eff"] - 3,
                   cx["exp"] - 3, cx["lim"] - 3):
            vline(xx, start + 9, y + 6, 0.3)
        y -= 3

    cov_row([("X COMMERCIAL GENERAL LIABILITY", "", "", "EACH OCCURRENCE", "$1,000,000"),
             ("CLAIMS-MADE X OCCUR", "", "", "DAMAGE TO RENTED PREMISES (Ea occurrence)",
              "$500,000"),
             ("", "", "", "MED EXP (Any one person)", "$10,000"),
             ("", "", "", "PERSONAL & ADV INJURY", "$1,000,000"),
             ("GEN'L AGGREGATE LIMIT APPLIES PER:", "", "", "GENERAL AGGREGATE", "$2,000,000"),
             ("POLICY PRO-JECT LOC", "", "", "PRODUCTS - COMP/OP AGG", "$2,000,000"),
             ("OTHER:", "", "", "", "")],
            ltr="A", pol=POL_GL_SHORT, dates=True)
    cov_row([("AUTOMOBILE LIABILITY", "", "", "COMBINED SINGLE LIMIT (Ea accident)",
              "$1,000,000"),
             ("X ANY AUTO", "", "", "BODILY INJURY (Per person)", "$"),
             ("OWNED AUTOS ONLY", "SCHEDULED AUTOS", "", "BODILY INJURY (Per accident)", "$"),
             ("HIRED AUTOS ONLY", "NON-OWNED AUTOS ONLY", "", "PROPERTY DAMAGE (Per accident)",
              "$")],
            ltr="B", pol=POL_AUTO, dates=True)
    cov_row([("X UMBRELLA LIAB", "X OCCUR", "", "EACH OCCURRENCE", "$1,000,000"),
             ("EXCESS LIAB", "CLAIMS-MADE", "", "AGGREGATE", "$1,000,000"),
             ("DED RETENTION $", "", "", "", "")],
            ltr="B", pol=POL_UMB, dates=True)
    cov_row([("WORKERS COMPENSATION", "", "", "PER STATUTE OTH-ER", ""),
             ("AND EMPLOYERS' LIABILITY", "", "Y / N", "E.L. EACH ACCIDENT", "$"),
             ("ANY PROPRIETOR/PARTNER/EXECUTIVE", "", "", "E.L. DISEASE - EA EMPLOYEE", "$"),
             ("OFFICER/MEMBER EXCLUDED?", "", "N / A", "E.L. DISEASE - POLICY LIMIT", "$"),
             ("(Mandatory in NH)", "", "", "", ""),
             ("If yes, describe under", "", "", "", ""),
             ("DESCRIPTION OF OPERATIONS below", "", "", "", "")])
    txt(L, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES (ACORD 101, Additional Remarks "
              "Schedule, may be attached if more space is required)", "Helvetica-Bold", 6.0)
    y -= 12
    glued(L + 6, y, "Note: Reduced Umbrella Limit from $3,000,000 to $1,000,000 Limit "
                    "Effective 7/25/25.", "Helvetica", 7.6)
    y -= 58
    hline(y + 8)
    split = y + 8
    txt(L, y - 1, "CERTIFICATE HOLDER", "Helvetica-Bold", 7)
    txt(MID + 4, y - 1, "CANCELLATION", "Helvetica-Bold", 7)
    for i, s in enumerate(["SHOULD ANY OF THE ABOVE DESCRIBED POLICIES BE CANCELLED BEFORE",
                           "THE EXPIRATION DATE THEREOF, NOTICE WILL BE DELIVERED IN",
                           "ACCORDANCE WITH THE POLICY PROVISIONS."]):
        txt(MID + 4, y - 12 - 7.6 * i, s, "Helvetica", 6.2)
    glued(L + 20, y - 40, "For Informational Purposes Only", "Helvetica", 8)
    txt(MID + 4, y - 48, "AUTHORIZED REPRESENTATIVE", "Helvetica-Bold", 6.2)
    hline(y - 60)
    vline(MID, split, y - 60)
    txt(L, y - 72, "ACORD 25 (2016/03)", "Helvetica-Bold", 7)
    c.showPage()
    c.save()


# ── 3. THE NARRATIVE ────────────────────────────────────────────────────────

NARRATIVE = [
    ("ACCOUNT OVERVIEW",
     "Orbin Contracting LLC is a commercial general contractor based in Denver, Colorado. The "
     "company manages tenant-finish, remodeling and light commercial construction projects for "
     "building owners and property managers in the Denver metro area, working from its office "
     "at 4800 Dahlia St # D13."),
    ("OPERATIONS",
     "The principals supervise every project directly and act as the executive supervisors on "
     "site. Trade work - framing, drywall, electrical, plumbing, mechanical and finish work - is "
     "subcontracted to licensed trade contractors under written subcontract agreements."),
    ("SUBCONTRACTING",
     "Subcontractors are required to carry their own general liability insurance and to "
     "provide certificates of insurance before they start work. Orbin keeps the certificates on "
     "file for every project."),
    ("VEHICLES", "The company owns one vehicle, a 2012 Subaru Outback."),
    ("UMBRELLA",
     "The account carries a commercial umbrella over its general liability and auto policies. "
     "The umbrella limit is $1,000,000."),
    ("PLACEMENT", "The account has been placed through Commercial Risk Solutions."),
    ("COVERAGE REQUESTED",
     "General Liability, Commercial Auto, Inland Marine (contractors equipment and installation "
     "floater) and Commercial Umbrella."),
    ("LOSS HISTORY", "There have been no losses in the past 5 years."),
]


def build_narrative(path):
    d = _Doc(path, "Underwriting Submission Narrative - Orbin Contracting LLC")
    d.page(section="narrative")
    d.line("UNDERWRITING SUBMISSION NARRATIVE", font=("Helvetica-Bold", 14), lead=20)
    d.line("Commercial package submission", font=("Helvetica", 10), lead=18)
    body = ("Helvetica", 10)
    xv = LM + 130
    for label, value in [("Applicant", INSURED_MIXED),
                         ("Mailing Address", "4800 Dahlia St # D13, Denver, CO 80216-3121"),
                         ("Legal Entity", "Limited Liability Company"),
                         ("Business", "Commercial general contractor")]:
        d.cells([(LM, f"{label}:", "Helvetica-Bold", 10), (xv, value)], font=body, lead=14)
    d.gap(8)
    for head, text in NARRATIVE:
        d.line(head, font=("Helvetica-Bold", 10.5), lead=15)
        d.wrap(text, font=body, lead=13.5)
        d.gap(7)
    d.save()


# ── Self-check: read the PDFs the way the live pipeline reads them ──────────

FILES = [
    # (file, builder, document type the pipeline must assign)
    (F1, build_policy, "dec_page"),
    (F2, build_certificate, "certificate"),
    (F3, build_narrative, "narrative"),
]

# Passages copied VERBATIM from the client's own OCR (271page-testdec.txt). Each
# must appear as consecutive lines in the real text AND in this kit's pipeline
# text - proof that the kit reads the way the client's package read.
REAL_PASSAGES = {
    "page 1 - Coverages and Premium": [
        "Coverages and Premium", "Section Coverage Premium", "1 Property No Coverage",
        "2 Liability $3,954.00", "3 Crime and Fidelity No Coverage", "4 Inland Marine $300.00",
        "5 Automobile $2,991.00", "6 Workers' Compensation No Coverage", "7 Umbrella $3,418.00",
        "8 Other", "Estimated Total Policy Premium $10,663.00"],
    "page 1 - producer block": [
        "Producer", "COMMERCIAL RISK SOLUTIONS, INC.", "9780 S MERIDIAN BLVD STE 400",
        "ENGLEWOOD, CO 80112-6072", "AGENT NO. W6258-0001", "AGENT PHONE: 303-996-7800",
        "CLAIM REPORTING: 888-362-2255"],
    "page 1 - named insured": ["Named Insured", ", ORBIN CONTRACTING LLC", "4800 DAHLIA ST # D13",
                               "DENVER, CO 80216-3121"],
    "IM dec - premium": ["CONTRACTORS EQUIPMENT $ 300.00", "ELECTRONIC DATA PROCESSING INCLUDED",
                         "INSTALLATION FLOATER INCLUDED"],
    "IM dec - insured block": ["ORBIN CONTRACTING LLC", "4800 DAHLIA ST # D13",
                               "DENVER CO 80216-3121"],
    "auto dec - item two": [
        "COVERED AUTOS LIABILITY 01 $ 1,000,000 .$ 1,496.00",
        "AUTO MEDICAL PAYMENTS 02 $ 5,000 EACH INSURED . 35.00",
        "UNINSURED AND 02 SEE ENDORSEMENT CA7093A . 258.00"],
    "auto - item three vehicle": [
        "LOC: 001 4800 DAHLIA STREET D13", "DENVER CO. 80216-3121", "VEH NO 1 TERR: 111 .",
        f"2012 SUBARU OUTBACK SEDAN ID NO {VIN}.", "ADDITIONAL INFORMATION:",
        "COST NEW: 26680 RADIUS: NA USE: NA .", "AGE: LIAB-I PHYS-I .",
        "PRIV PASSENGER - COMM CLASS: 7383 .", "COVERED AUTOS LIABILITY .$ 1,496.00"],
    "auto - endorsement premium detail": [
        "ENDORSEMENT PREMIUM DETAIL", "ENDORSEMENTS CLASS PREMIUM", DOC_LINE, ELITE_LINE],
    "auto - UM supplementary": ["CO $ 1,000,000"],
    "umbrella dec - limits": [
        "LIMITS OF INSURANCE", "Each Occurrence Limit (Liability Coverage) $ 3,000,000",
        "Personal & Advertising Injury Limit $ 3,000,000", "(Any one person or organization)",
        "Aggregate Limit (Liability Coverage) $ 3,000,000",
        "(except with respect to \"covered autos\")"],
    "GL dec - identity": [
        "EMC Property & Casualty Company"],
    "GL dec - producer": [
        "Producer", "COMMERCIAL RISK SOLUTIONS, INC.", "9780 S MERIDIAN BLVD STE 400",
        "ENGLEWOOD, CO 80112-6072", "AGENT NO. W6258", "AGENT PHONE: 303-996-7800",
        "CLAIM REPORTING: 888-362-2255", "SERVICING CARRIER: 720-200-3700"],
    "GL dec - limits": [
        "Each Occurrence Limit $1,000,000",
        "Damage To Premises Rented To You Limit $500,000(any one premises)",
        "Medical Expense Limit $10,000(any one person)",
        "Personal and Advertising Injury Limit $1,000,000(any one person or organization)",
        "General Aggregate Limit $2,000,000",
        "Products/Completed Operations Aggregate Limit $2,000,000"],
    "GL schedule - 91580": [
        "Location 001", "91580 Contractors - Executive Supervisors 33.211 $1,305",
        "or Executive Superintendents", "Prem Basis: Payroll", "Exposure: $39,300"],
    "GL schedule - 91585": [
        "91585 Contrctrs-sub work-in connection 3.4240 $1,198 2.293 $803",
        "w/constrctn,recon,repr,erctn of buildings -", "NOC", "Prem Basis: Total Cost",
        "Exposure: $350,000"],
    "GL endorsement schedule": [
        "CG 70 01A 10 12 General Liability Schedule",
        "CG 70 03 10 13 GL Quick Reference (Occurrence)"],
    "GL locations": ["4800 Dahlia St # D13", "Location 1", "Denver, CO 80216-3121"],
}


def _plain_pages(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages], [len(p.images) for p in pdf.pages]


def _pipeline_text(path):
    """The native-text half of `ocr_service.extract_text_from_pdf`, page markers
    included - what extraction and the gap-fill line scopes actually read."""
    from services.ocr_service import _pdfplumber_extract_pages_structured
    pages = _pdfplumber_extract_pages_structured(path)
    parts, per_page = [], []
    for i, (text, tables) in enumerate(pages):
        if len(pages) > 1 and (text.strip() or tables):
            parts.append(f"[Document page {i + 1}]")
        if text.strip():
            parts.append(text)
        if tables:
            parts.append(tables)
        per_page.append(text)
    return "\n".join(parts), per_page


def _norm_lines(text):
    return [re.sub(r"\s+", " ", ln).strip() for ln in str(text).splitlines() if ln.strip()]


def _has_passage(text, passage):
    lines = _norm_lines(text)
    want = [re.sub(r"\s+", " ", p).strip() for p in passage]
    n = len(want)
    return any(lines[i:i + n] == want for i in range(len(lines) - n + 1))


def _real_pages():
    if not os.path.exists(REAL_OCR):
        return None, None
    with open(REAL_OCR, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    parts = re.split(r"\[Document page (\d+)\]", raw)
    pages = {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    return raw, pages


def _verify(paths, meta):
    # Read-only imports of the pipeline's own text layer and rules. No bytecode is
    # written into backend/ - other work is in flight there.
    sys.dont_write_bytecode = True
    sys.path.insert(0, BACKEND)
    import logging
    logging.disable(logging.CRITICAL)
    problems, notes = [], []
    stats = {}

    plain, images = {}, {}
    for name, _b, _t in FILES:
        pages, imgs = _plain_pages(paths[name])
        plain[name], images[name] = pages, imgs

    # (a) page counts
    counts = {name: len(plain[name]) for name, _b, _t in FILES}
    stats["pages"] = counts
    print("  (a) page counts: " + ", ".join(f"{n} = {c}" for n, c in counts.items()))
    if not 40 <= counts[F1] <= 60:
        problems.append(f"{F1}: {counts[F1]} pages, the spec is 40-60")
    if counts[F2] != 1:
        problems.append(f"{F2}: must be ONE page, is {counts[F2]}")
    if not 1 <= counts[F3] <= 2:
        problems.append(f"{F3}: must be 1-2 pages, is {counts[F3]}")

    # Every page must carry >= 100 native characters and no image, or the live
    # pipeline sends it to Google Vision OCR instead of reading this text.
    for name, _b, _t in FILES:
        for i, (t, n_img) in enumerate(zip(plain[name], images[name]), 1):
            if len(t.strip()) < 100:
                problems.append(f"{name} page {i}: only {len(t.strip())} native chars (< 100)")
            if n_img:
                problems.append(f"{name} page {i}: carries {n_img} image(s)")

    plain_all = {name: "\n".join(pages) for name, pages in plain.items()}

    # (b) the certificate's run-together strings, verbatim, from page.extract_text()
    print("  (b) certificate run-together strings (plain pdfplumber page.extract_text()):")
    for s in RUN_TOGETHER:
        ok = s in plain_all[F2]
        print(f"        {'PRESENT' if ok else 'MISSING'}  {s}")
        if not ok:
            problems.append(f"{F2}: run-together string missing: {s!r}")

    # (c) the policy's traps, verbatim
    t1 = plain_all[F1]
    print("  (c) policy package contents (plain pdfplumber):")
    checks = ([("form number", f) for f in FORM_NUMBERS]
              + [("account number", ACCOUNT)]
              + [("no-coverage row", r) for r in NO_COVERAGE_ROWS]
              + [("DOC line", DOC_LINE), ("Elite line", ELITE_LINE), ("VIN", VIN),
                 ("DOC individual", DOC_INDIVIDUAL), ("umbrella $3M", "$ 3,000,000"),
                 ("GL carrier", CAR_PC), ("auto/IM/umb carrier", CAR_MUT)])
    for label, s in checks:
        n = t1.count(s)
        print(f"        {'PRESENT' if n else 'MISSING'} x{n:<3} {label:18s} {s}")
        if not n:
            problems.append(f"{F1}: missing {label} {s!r}")
    for r in NO_COVERAGE_ROWS:
        if not any(ln.strip() == r for ln in t1.splitlines()):
            problems.append(f"{F1}: {r!r} is not a line of its own")
    menu_ok = _has_passage(t1, [MENU_HEADER] + MENU_LINES)
    print(f"        {'PRESENT' if menu_ok else 'MISSING'}      endorsement menu "
          f"({MENU_HEADER[:40]}... + {len(MENU_LINES)} lines, consecutive)")
    if not menu_ok:
        problems.append(f"{F1}: the 7-line endorsement menu is not printed as consecutive lines")

    # Absences: things that would make a check pass for the wrong reason.
    for name, needle, why in [
            (F1, NAIC_MUT, "the real policy prints no NAIC"),
            (F1, NAIC_PC, "the real policy prints no NAIC"),
            (F1, "ThinkSmith", "the new agency is the LOGIN, never a document"),
            (F1, "Michelle", "the new agency is the LOGIN, never a document"),
            (F2, "ThinkSmith", "the new agency is the LOGIN"),
            (F2, "Michelle", "the new agency is the LOGIN"),
            (F3, "ThinkSmith", "the narrative names NO new agency"),
            (F3, "Michelle", "the narrative names NO new agency"),
            (F3, VIN, "the narrative's Subaru has no VIN"),
            (F3, "VIN", "the narrative's Subaru has no VIN"),
            (F3, "eclaration", "a narrative mentioning declarations classifies as a dec page"),
            (F3, "enewal", "a narrative renewal statement creates an is_renewal fact"),
            (F3, "Workers", "naming a line at all risks a phantom line"),
            (F3, "Property coverage", "naming a line at all risks a phantom line"),
            (F3, "Terri", "the old contact belongs to the certificate only"),
            (F3, "07/15", "the narrative states no term"),
            (F2, "Michelle Smith", "no authorised-representative name on the certificate")]:
        if needle in plain_all[name]:
            problems.append(f"{name}: must NOT contain {needle!r} - {why}")
    for s in ("Commercial Risk Solutions", "a 2012 Subaru Outback",
              "The umbrella limit is $1,000,000.", "no losses in the past 5 years"):
        if s not in plain_all[F3]:
            problems.append(f"{F3}: missing {s!r}")

    # Column collisions a fused cell would produce.
    for name, text in plain_all.items():
        for fused in ("LLCCOMMERCIAL", "COMPANYPolicy", "COMPANYPOLICY", "D13COMMERCIAL",
                      "LLC9780", "CoverageNo", "Compensation$", "CompanyPolicy", "INC.AGENT"):
            if fused in text:
                problems.append(f"{name}: column collision {fused!r}")

    # The pipeline's own text layer (page_layout repairs, tables inline).
    try:
        pipe = {name: _pipeline_text(paths[name]) for name, _b, _t in FILES}
    except Exception as exc:                                  # noqa: BLE001
        pipe = None
        notes.append(f"pipeline extractor unavailable ({exc}) - plain pdfplumber only")
    if pipe:
        print("  pipeline text layer (services.ocr_service._pdfplumber_extract_pages_structured):")
        for s in RUN_TOGETHER:
            if s not in pipe[F2][0]:
                problems.append(f"{F2}: pipeline text lost the run-together string {s!r}")
        print(f"        certificate: {sum(s in pipe[F2][0] for s in RUN_TOGETHER)}/"
              f"{len(RUN_TOGETHER)} run-together strings survive the page_layout repairs")
        t1p = pipe[F1][0]
        for label, s in checks:
            if s not in t1p:
                problems.append(f"{F1}: pipeline text lost {label} {s!r}")
        if not _has_passage(t1p, [MENU_HEADER] + MENU_LINES):
            problems.append(f"{F1}: pipeline text broke the endorsement menu")

        # Faithfulness: the client's own OCR, passage by passage.
        real_raw, real_pages = _real_pages()
        hit = 0
        for label, passage in REAL_PASSAGES.items():
            in_kit = _has_passage(t1p, passage)
            in_real = None if real_raw is None else _has_passage(real_raw, passage)
            hit += bool(in_kit)
            if not in_kit:
                problems.append(f"{F1}: real passage not reproduced - {label}")
            if in_real is False:
                problems.append(f"REAL_PASSAGES[{label!r}] is not verbatim in the real OCR")
        stats["passages"] = (hit, len(REAL_PASSAGES))
        print(f"        real-OCR passages reproduced verbatim: {hit}/{len(REAL_PASSAGES)}"
              + ("" if real_raw is not None else " (real OCR file absent - kit side only)"))
        if real_pages:
            sims = []
            for i, m in enumerate(meta):
                rp = m.get("real_page")
                if rp and rp in real_pages and i < len(pipe[F1][1]):
                    kit = "\n".join(_norm_lines(pipe[F1][1][i]))
                    real = "\n".join(_norm_lines(re.split(r"\[Table - page", real_pages[rp])[0]))
                    sims.append((i + 1, rp, difflib.SequenceMatcher(None, kit, real).ratio()))
            dense = [s for s in sims if s[1] in (1, 3, 4, 6, 7, 8, 9, 85, 87, 89, 90, 91, 92, 143,
                                                 144, 148, 205, 207, 208, 211)]
            if dense:
                avg = sum(s[2] for s in dense) / len(dense)
                stats["similarity"] = (avg, len(dense))
                print(f"        declarations/schedule pages vs the real OCR page, character "
                      f"similarity: mean {avg:.0%} over {len(dense)} pages")
                for kp, rp, r in dense:
                    print(f"            kit p{kp:<3} ~ real p{rp:<4} {r:.0%}")

        # Document roles - several rules key on them.
        try:
            from services.extraction_service import classify_document
            for name, _b, want in FILES:
                got = classify_document(pipe[name][0], name)
                stats.setdefault("types", {})[name] = got.get("doc_type")
                print(f"        classify_document({name}) = {got.get('doc_type')} "
                      f"({got.get('confidence')}, {got.get('source')})")
                if got.get("doc_type") != want:
                    problems.append(f"{name}: classifies as {got.get('doc_type')!r}, needs {want!r}")
        except Exception as exc:                              # noqa: BLE001
            notes.append(f"document-role check skipped ({exc})")

        # Page-header carrier binder: the first company-looking line in each
        # page's first six must be that section's own carrier.
        try:
            from services.extraction_service import _header_carrier_name
            bad = 0
            for i, m in enumerate(meta):
                if not m.get("carrier") or i >= len(pipe[F1][1]):
                    continue
                head = [ln.strip() for ln in pipe[F1][1][i].strip().splitlines()[:6]]
                first = next((n for n in (_header_carrier_name(h) for h in head) if n), None)
                if not first or first.strip(" ,*").upper() != m["carrier"].upper():
                    bad += 1
                    problems.append(f"{F1} page {i + 1}: header binder would read "
                                    f"{first!r}, section carrier is {m['carrier']!r}")
            n_sec = sum(1 for m in meta if m.get("carrier"))
            stats["binder"] = (n_sec - bad, n_sec)
            print(f"        page-header carrier binder: {sum(1 for m in meta if m.get('carrier')) - bad}"
                  f"/{sum(1 for m in meta if m.get('carrier'))} section pages read their own carrier")
        except Exception as exc:                              # noqa: BLE001
            notes.append(f"header-binder check skipped ({exc})")

        # The Drive Other Car individual must read as a NAMED INDIVIDUAL (never a
        # driver) whichever name order extraction copies - the 14 Sep rule
        # matches the name as printed.
        try:
            from services.named_individuals import printing_roles, _norm
            hay = [_norm(pipe[F1][0])]
            for name in (DOC_INDIVIDUAL, DOC_INDIVIDUAL_REAL, "Erin Royal"):
                roles = printing_roles(name, hay)
                ok = "named" in roles and "driver" not in roles
                print(f"        named-individual printing of {name!r}: {roles}")
                if not ok:
                    problems.append(f"{F1}: {name!r} is not printed under a named-individual "
                                    f"heading only ({roles})")
        except Exception as exc:                              # noqa: BLE001
            notes.append(f"named-individual check skipped ({exc})")

    for n in notes:
        print(f"  ! {n}")
    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("   -", p)
        return False, stats
    print("  self-check passed")
    return True, stats


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths, meta = {}, None
    for name, builder, _want in FILES:
        path = os.path.join(OUT_DIR, name)
        out = builder(path)
        if name == F1:
            meta = out
        paths[name] = path
    print(f"wrote {OUT_DIR}")
    for name, _b, _t in FILES:
        print(f"   {name:24s} {os.path.getsize(paths[name]):>8,} bytes")
    stale = sorted(f for f in os.listdir(OUT_DIR)
                   if f.lower().endswith(".pdf") and f not in {n for n, _b, _t in FILES})
    if stale:
        print(f"  ! stale PDFs from an older version of this kit: {stale}")
    ok, stats = _verify(paths, meta)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(render_readme(stats))
    print("   README-HOW-TO-TEST.md written")
    sys.exit(0 if ok else 1)


def render_readme(stats):
    """README-HOW-TO-TEST.md, with the self-check's own measurements in it."""
    pages = stats.get("pages") or {}
    p1, p2, p3 = pages.get(F1, "?"), pages.get(F2, "?"), pages.get(F3, "?")
    hit, total = stats.get("passages", ("?", "?"))
    sim = stats.get("similarity")
    sim_txt = f"{sim[0]:.0%} over {sim[1]} declarations / schedule pages" if sim else "n/a"
    ok_b, n_b = stats.get("binder", ("?", "?"))
    return f"""# Orbin retest kit - the client's real submission, rebuilt

Built 24 Sep 2026 so the owner can check Michelle's 11 items on the SHAPE of
the client's own Orbin Contracting LLC submission. Every earlier kit used an
invented insured; this one reprints the client's EMC package (271 pages
condensed to {p1}), a certificate whose text comes back run-together exactly like
the client's certificate OCR, and a narrative that mentions the old broker and
names no new one.

| File | What it is | Pages | The pipeline must type it as |
|---|---|---|---|
| `{F1}` | EMC "Package Policy": common declarations, Inland Marine, Business Auto, Umbrella, General Liability, plus the endorsement pages that set the traps | {p1} | Dec Page |
| `{F2}` | ACORD 25 look-alike dated {COI_DATE} | {p2} | Certificate of Insurance |
| `{F3}` | Underwriting submission narrative | {p3} | Underwriting Narrative |

**Upload all three TOGETHER, as ONE package, in a NEW session.** Several rules
key on each document's type (a certificate documents the existing policy, a
narrative is a submission document), so they must stay three files. A re-used
session carries old confirmations (`IM 7100 06 04`, `$1,000,000`, the old
agency) that hide exactly the fixes this kit checks.

## Item numbers (the "Item" column)

Michelle's 11 items, numbered as in the client's 11 Sep audit
(`11sep-form-improvement.md`):

| Item | What the client reported |
|---|---|
| 1 | Carrier, NAIC, policy number and dates not staying with their own line of business |
| 2 | Phantom coverages - Property, Crime, Workers Comp, Farm, Liquor, EPLI, OCP, Pollution shown as lines |
| 3 | A form number (`IM 7100 06 04`) printed as a policy number; false conflicts |
| 4 | The expiring producer (Commercial Risk Solutions / Terri Wroblewski) on the new application |
| 5 | Carrier / NAIC pairs no document prints; comparisons that should never happen ($2M vs a Yes/No box, Claims-Made vs a form title) |
| 6 | Codes on the wrong line (GL class 91580 on the vehicle row, Drive Other Car 104 / 6679 on the GL form) |
| 7 | ACORD 137 for Colorado auto - offered, and filled correctly |
| 8 | "For Informational Purposes Only" printed as a named party |
| 9 | Umbrella $3,000,000 -> $1,000,000 treated as a conflict instead of a dated change |
| 10 | Comparison guardrails - conflict cards and warnings that should not exist |
| 11 | Asked again for what the policy already states (the Subaru, "Driver 25") |

## Before you start

1. **Restart the backend, then prove the running process is the current code.**
   `uvicorn --reload` has served stale code on this machine before (the A125
   run 4 served 16:01 code all evening). Stop it - if `--reload` left a parent
   AND a child, stop both (`kill -9` if they ignore TERM) - and start it
   without reload, keeping the log:

   ```
   cd backend
   PURGE_DEC_INDEX_AFTER_GENERATION=0 .venv/bin/uvicorn main:app --port 8000 2>&1 | tee ../orbin_retest_kit/backend-run.log
   ```

   Then check that the worker started AFTER the last code change:

   ```
   ps -eo pid,lstart,command | grep main:app
   ```

   Hard-refresh the browser too (rebuild if you serve a built frontend): the
   "ticking 127 ticks 137 CO" behaviour (A3 / A5) is frontend code.
2. **`PURGE_DEC_INDEX_AFTER_GENERATION=0`** - on the command line above, or in
   `backend/.env` - so `dec_page_entries` survives generation for inspection.
3. **Set your test user's profile: organization `ThinkSmith Agency LLC`, full
   name `Michelle Smith`** (and a phone number, if the profile has one). No
   uploaded document names the new agency - the producer block follows the
   LOGIN: agency, name, and since 24 Sep the login's e-mail and phone. If you
   keep your own account, read every "ThinkSmith Agency LLC / Michelle Smith"
   below as your own account's agency and name; the rule being checked is the
   same. **A profile with NO agency is not a pass or a fail - it voids every
   producer row:** the block then prints blank (never Commercial Risk
   Solutions) and the log says `submitting account unavailable` (section N).
4. **FRESH upload of all three files together as ONE package.** Record sections
   A-C before answering anything on the pre-form screen.
5. **Select ACORD 125, 126, 127, 131 and 186**, and check that ticking 127 ticks
   **ACORD 137 CO** by itself (row A3). Generate. (186 because the client
   generates it; without it the contractor rule caps the package at 85.)
6. **Download one generated form first.** If it is the blank template, stop:
   this environment cannot fill PDFs (the pikepdf issue) and nothing below means
   anything - grade from the stored session instead.

## What the documents say (the truth)

| Line | Carrier (legal entity) | NAIC | Policy number - every printing is ONE contract | Premium |
|---|---|---|---|---|
| General Liability | {CAR_PC} | {NAIC_PC} | `{POL_GL}` = `{POL_GL_HDR}` = `{POL_GL_SHORT}` | $3,954.00 |
| Business Auto | {CAR_MUT_MIXED} | {NAIC_MUT} | `{POL_AUTO}` = `6E7-40-02` = `{FOOT_AUTO}` | $2,991.00 |
| Inland Marine | {CAR_MUT_MIXED} | {NAIC_MUT} | `{POL_IM}` = `{FOOT_IM}` | $300.00 |
| Umbrella | {CAR_MUT_MIXED} | {NAIC_MUT} | `{POL_UMB}` = `6J74002---26` = `{FOOT_UMB}` | $3,418.00 |
| Property / Crime and Fidelity / Workers' Compensation | - | - | **No Coverage** on page 1 | - |

- Term 07/15/2025 - 07/15/2026 on every line; declarations issued 07/16/25;
  estimated total $10,663.00. Account number `{ACCOUNT}` is NOT a policy number.
- **The policy prints no NAIC anywhere** - exactly like the real package. Each
  carrier's NAIC exists only on the certificate (INSURER A / B).
- **GL:** OCCURRENCE (CG 00 01 04 13). Each Occurrence 1,000,000; General
  Aggregate 2,000,000; Products-Completed Ops 2,000,000; Personal & Adv Injury
  1,000,000; Damage to Premises Rented 500,000; Medical Expense 10,000. Classes
  91580 (payroll $39,300) and 91585 (total cost $350,000), no territory printed.
  The GL extension (CG 77 59) applies the aggregate per project and per location.
- **Auto:** CSL $1,000,000 symbol 1; Med Pay $5,000 symbol 2; UM / UIM
  $1,000,000 CSL symbol 2; comprehensive and collision $1,000 deductible symbol 7;
  hired auto physical damage deductibles $1,000 (CA7450 M). ONE vehicle - 2012
  SUBARU OUTBACK SEDAN, VIN `{VIN}`, CLASS 7383, TERR 111, USE: NA, garaged at
  4800 Dahlia St D13, Denver CO. Drive Other Car: TERRITORY 104, class 6679,
  $204.00, named individual ROYAL, ERIN (also printed "ERIN ROYAL", as on the real
  package) - she is NOT a driver. Auto Elite Extension class 8556.
- **Umbrella:** $3,000,000 each occurrence / aggregate on the 07/16/25
  declarations. The certificate ({COI_DATE}) prints $1,000,000 and the remark
  "Reduced Umbrella Limit from $3,000,000 to $1,000,000 Limit Effective 7/25/25";
  the narrative says $1,000,000. Underlying: GL {CAR_PC} `{POL_GL}`, Auto
  {CAR_MUT_MIXED} `{POL_AUTO}`.
- **Producer on every document:** {PRODUCER_MIXED} - the EXPIRING broker. The
  narrative's only agency sentence is "The account has been placed through
  Commercial Risk Solutions."

### Page map of `{F1}`

| Pages | Section |
|---|---|
| 1-2 | Common Declarations (IL 7000A) - Coverages and Premium, servicing company |
| 3-14 | Inland Marine `{POL_IM}` - dec, endorsement schedule, schedule of coverages, AAIS IM 7100 / IM 7201 / CL 0182, IL 73 06 |
| 15-28 | Business Auto `{POL_AUTO}` - dec, UM schedule, vehicle, hired / non-owned, endorsement premium detail, Drive Other Car, CA 00 01, CA7450 M, IL 00 21, IL 02 28 |
| 29-38 | Umbrella `{POL_UMB}` - dec, endorsement schedule, schedule of underlying insurance, CU 00 01, CU7269 / CU7270, IL 01 25, Colorado Company Elimination |
| 39-49 | General Liability `{POL_GL}` - dec, forms, endorsement schedule, GL schedule, locations, CG 00 01, CG 77 59, IL 00 03 |

## The traps

| Trap | Where | Item |
|---|---|---|
| Page 1 lists lines and premiums only; "6 Workers' Compensation No Coverage" sits directly above "7 Umbrella $3,418.00" | policy p1 | 1, 2 |
| Two legal entities of one group; "EMC Property and Casualty Company", "EMCASCO", "EMC Insurance Companies" printed elsewhere | policy p2, p38, GL section | 1, 5, 10 |
| Every page header names the producer and that section's policy number; footers print form numbers, the compact number and a "2601" print code (`6C74002 2601`) | every policy page | 1, 3, 4 |
| Form numbers beside policy numbers: IM 7100 06 04, IM 7201 10 02, CU7001A 11-15, CA7450 M, CA7000A 02-22, CG 70 01A 10 12, IL 71 31A 04 01, CG 00 01 04 13 | forms schedules, footers, umbrella dec | 3 |
| Endorsement MENUS naming Commercial Property, Commercial Crime, Crime and Fidelity, Farm, Liquor, EPLI, OCP, Pollution, Medical Professional | policy p14, 27, 28, 37, 49 | 2 |
| "DRIVE OTHER CAR - TERRITORY: 104 6679 $ 204.00" and "Auto Elite Extension 8556 $ 250.00" | policy p21 | 6 |
| VIN, CLASS 7383, TERR 111 in one vehicle block; the narrative repeats the car without a VIN | policy p19; narrative | 6, 11 |
| "Coverage Form: CU7001A 11-15 Commercial Liability Umbrella Coverage Form" beside the umbrella limits | policy p29 | 3, 5 |
| GL aggregate "applies separately to each of your construction projects" / "to each of your locations" | policy p48 | 5, 10 |
| Run-together certificate strings: `{COI_INSURER_A}`, `{COI_INSURER_B}`, `{COI_HOLDER}`, `{COI_REMARK}` | certificate | 1, 8, 9 |
| Unticked HIRED AUTOS ONLY / NON-OWNED AUTOS ONLY; an empty preprinted Workers Comp / Employers Liability row | certificate | 2, 10 |
| Conditional renewal wording ("if it is a renewal of a policy issued by us") | policy p13, 28, 49 | 10 |
| The old broker named in a SUBMISSION document | narrative | 4 |

## Checklist

Fill **Result**: PASS / FAIL + the literal value you saw. Row IDs are stable, so
"E4 FAIL, TERR shows 104" is enough. **Send = yes** means screenshot it.

### A. Form selection (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| A1 | 2 | Recommended forms | ACORD 125, 126, 127, 131 marked Required | any of the four missing or not Required | yes | |
| A2 | 2 | Recommended forms | ACORD 130, 140 and 141 NOT offered at all | any of them offered (page 1 says Workers' Comp, Property, Crime: No Coverage) | yes | |
| A3 | 7 | Tick ACORD 127 | ACORD 137 CO becomes ticked automatically, and its card still reads **Needs Confirmation** | 137 CO stays unticked, disappears, or is relabelled Required | yes | |
| A4 | 7 | ACORD 137 CO card evidence | auto facts: liability limit $1,000,000, UM / UIM $1,000,000 | contractor facts ("Contractor type: ...") | | |
| A5 | 7 | Untick 137 CO by hand (re-tick it before generating) | a banner "ACORD 127 is selected without ACORD 137 CO ..." with a one-click **Add ACORD 137 CO** | 137 CO silently dropped, no banner | | |
| A6 | new | "Tailored for:" chips above the list | no "Renewal" chip (no document says this is a renewal) | "Renewal" | | |

Not graded: ACORD 25, 186 and 160 may also be offered (160 is the known
mislabelled Business Owners form).

### B. Data Consistency (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| B1 | 1, 3, 10 | Policy Number | no conflict card - scoped per line: GL `{POL_GL}`, Auto `{POL_AUTO}`, Inland Marine `{POL_IM}`, Umbrella `{POL_UMB}` | a card; `IM 7100 06 04` / `IM 7201 10 02` / `CU7001A 11-15` / `IL 71 31A 04 01` / `CG 70 01A 10 12` / `{ACCOUNT}` offered as a choice | yes | |
| B2 | 1, 10 | Carrier | no conflict card - GL {CAR_PC}; Auto, Inland Marine, Umbrella {CAR_MUT_MIXED} | an "EMC Property & Casualty vs Employers Mutual" card; "EMC Insurance" or "EMCASCO" offered | yes | |
| B3 | 1, 5, 10 | Carrier NAIC | no conflict card - {NAIC_PC} on GL only, {NAIC_MUT} on Auto / Umbrella; Inland Marine shows "-" (only the certificate prints NAICs, and it does not list the Inland Marine policy) | a "{NAIC_PC} vs {NAIC_MUT}" card; {NAIC_PC} beside Employers Mutual | yes | |
| B4 | 9 | Umbrella Limit | **no umbrella row and no card** - the dated cut is kept on the backend and not shown (owner, 27 Sep); the 131 prints 1,000,000 (G2) | a "$3,000,000 vs $1,000,000" card asking you to confirm; a "Changed during the policy term" row | yes | |
| B5 | 4 | Producer Name | no card | COMMERCIAL RISK SOLUTIONS, INC. vs Commercial Risk Solutions, Inc. (or vs your agency) | | |
| B6 | 10 | Building value | no card | any building-value card - the package has no property coverage | | |
| B7 | 10 | Renewal | no is_renewal card | a renewal yes / no card - the only "renewal" words are cancellation-clause boilerplate | | |
| B8 | 10 | Hired auto | no card | a hired-auto yes / no card (the certificate's UNTICKED "HIRED AUTOS ONLY" label vs the policy's Item Four) | | |
| B9 | 1, 2 | Policies in this submission | 4 policies, each with its own carrier and number; no Workers Comp, Property or Crime row | 5+ rows; a No Coverage line listed; a dash for a number | yes | |

### C. Warnings / hard stops (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| C1 | 1, 10 | Warnings / submission integrity | NO "Multiple carriers referenced across documents" | present | yes | |
| C2 | 2 | Cover page, dashboard card, submission integrity, questionnaire | no coverage list naming Property, Crime, Workers Compensation, Farm, Liquor, Employment-Related Practices (EPLI), Owners and Contractors Protective (OCP) or Pollution - anywhere | any of them listed as a line the insured has | yes | |
| C3 | 9 | Warnings | no umbrella "documents state different amounts" warning | present | | |
| C4 | 4 | Warnings | no "Producer Name: documents disagree" warning | present | | |

Expected, NOT a failure: "Driver schedule not provided" (the policy schedules no
drivers - the only person is the Drive Other Car individual); a note that the
printed term already ended (07/15/2026) or that the new term must be confirmed.

### D. ACORD 125

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| D1 | 1, 3 | Page 1 CARRIER / NAIC / POLICY NUMBER | all three **blank** - no document names the carrier receiving this submission | Employers Mutual or EMC P&C; {NAIC_MUT} / {NAIC_PC}; any number (`IM 7100 06 04`, `{ACCOUNT}`, a 6E7 / BBC number) | yes | |
| D2 | 1 | STATUS OF TRANSACTION | **QUOTE** ticked | RENEW ticked, or nothing | | |
| D3 | 2 | LINES OF BUSINESS ticks | only Commercial General Liability, Business Auto, Inland Marine, Umbrella | Property, Crime, Workers Comp, Cyber, Liquor or anything else ticked | yes | |
| D4 | 1, 3, 10 | OTHER INSURANCE WITH THIS COMPANY (rows A-D) | the 4 policies, each with its own number: General Liability `{POL_GL}`, Commercial Auto `{POL_AUTO}`, Inland Marine `{POL_IM}`, Umbrella `{POL_UMB}` (row order may differ; `{POL_GL_HDR}` is the same GL policy) | one number on every row; a form number; `{ACCOUNT}`; a line with no number; a No Coverage line | yes | |
| D5 | 4 | Producer block - agency, contact, authorised representative | the logged-in agency and name (ThinkSmith Agency LLC / Michelle Smith); e-mail and phone are your login's (blank only if the profile has none); address blank | Commercial Risk Solutions / Terri Wroblewski; 303-996-7800 or twroblewski@crsdenver.com as the producer's contact | yes | |
| D6 | 4 | Anywhere on the form | none of: Commercial Risk Solutions, Terri Wroblewski, W6258-0001 (or AW 6258, W6258), 303-996-7800, {CONTACT_EMAIL}, Meridian | any of them | | |
| D7 | 8 | Any box | no "For Informational Purposes Only" in any spelling the kit prints (`{COI_HOLDER}`, `FOR INFORMATIONAL PURPOSES ONLY`) | in Additional Interest, certificate holder or remarks | | |
| D8 | 3 | Every policy-number box (page 1, other insurance, prior carrier grid) | never `IM 7100 06 04`, `IM 7201 10 02`, `CU7001A 11-15`, `CA7450 M`, `CA7000A 02-22`, `CG 70 01A 10 12`, `IL 71 31A 04 01`, `CG 00 01 04 13`; never `{ACCOUNT}` | any of them | | |
| D9 | new | DESCRIPTION OF PRIMARY OPERATIONS (page 2, the big box) | the narrative's own paragraph: "Commercial general contractor. The company manages tenant-finish, remodeling ..." | "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA" | yes | |
| D10 | new | Premises row DESCRIPTION OF OPERATIONS (one-line box) | "Commercial general contractor." at a readable size | the whole paragraph in tiny type, cut off mid-word; "INSURED IS: LLC ..." | | |
| D11 | new | General information Q "Any exposure to flammables, explosives, chemicals?" | blank (no document says) | Y - the live run printed Y "explained" by the business description | yes | |

**D4 - if the whole list is blank:** it was blanked on 16 Sep (run 10 read "this
company" as the carrier receiving the submission) and RESTORED on 24 Sep by owner
decision (`pdf_service._other_policy_rows`). A blank list most likely means the
backend is still running pre-24-Sep code - redo the restart check in "Before you
start", step 1, before recording a FAIL.

### E. ACORD 126

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| E1 | 1, 5 | Header CARRIER / NAIC / POLICY NUMBER | {CAR_PC} / {NAIC_PC} / `{POL_GL}` (`{POL_GL_HDR}` is the same policy) | Employers Mutual Casualty; {NAIC_MUT}; an auto / umbrella / inland marine number; blank | yes | |
| E2 | 5 | Occurrence / Claims-Made; retro date | OCCURRENCE ticked, CLAIMS-MADE not; PROPOSED RETROACTIVE DATE blank | Claims-Made ticked; both blank; any retro date | | |
| E3 | 1 | GL limits | Each Occurrence 1,000,000; General Aggregate 2,000,000; Products-Completed Ops 2,000,000; Personal & Adv Injury 1,000,000; Damage to Premises Rented 500,000; Medical Expense 10,000 | any 3,000,000 (the umbrella's); 1,000,000 as the aggregate | | |
| E4 | 6 | Hazard grid | row A 91580 (payroll $39,300), row B 91585 (total cost $350,000); **TERR blank** on both | 7383 / 6679 / 104 / 8556 in any cell; TERR filled; a third row copying row A or reading "Fungi Or Bacteria Exclusion" | yes | |
| E5 | 6 | Anywhere on 126 | no 7383, 6679, 104 or 8556 | any of them | | |
| E6 | 2, 6 | UM / UIM and Employee Benefits | no UM / UIM amount; no Employee Benefits limit | $1,000,000 in a UM / UIM box; EBL $1,000,000 or "0 - 25" | | |
| E7 | 2, 5 | OTHER coverage description | does not name an auto, inland marine or umbrella line (a GL coverage such as "Limited Pollution Coverage - Work Sites" may appear) | "Commercial Auto Liability", "Installation Floater", "Commercial Umbrella", "Commercial General Liability / Commercial Auto Liability" | | |
| E8 | new | DEDUCTIBLES | PROPERTY DAMAGE and BODILY INJURY blank; the third (OTHER) row reads "Property Damage Deductible Each Pollution Incidents" with 1,000 | 1,000 in the PROPERTY DAMAGE or BODILY INJURY box | yes | |
| E9 | new | Contractors Q4 "Do your subcontractors carry coverages or limits less than yours?" | blank (no document says) - and never the opposite of 131 Q14 (row G7) | N here with Y on 131, or any answer | | |
| E10 | new | Q "Vendors coverage required?" | blank (no document says) | Y - the live run printed Y "explained" by the subcontractor sentence | yes | |
| E11 | new | Contractors Q5 "Are subcontractors allowed to work without providing you with a certificate of insurance?" | N (the narrative: they must provide certificates before they start) or blank | Y | | |

### F. ACORD 127

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| F1 | 1 | Header | {CAR_MUT_MIXED} / {NAIC_MUT} / `{POL_AUTO}` | {NAIC_PC}; EMC P&C; another line's number | yes | |
| F2 | 6, 11 | Vehicle row 1 | 2012 / SUBARU / OUTBACK / VIN `{VIN}` / CLASS 7383 / TERR 111 | class 91580 / 91585 / 6679; TERR 104; VIN missing | yes | |
| F3 | 11 | Vehicle row 2 (and 3, 4) | **blank** - the narrative's "2012 Subaru Outback" is the SAME car and must merge into the declarations row | a second Subaru row; $39,300 / $350,000 / 26680 on another row | yes | |
| F4 | 11 | Driver rows | ERIN ROYAL not printed as a driver | ERIN / ROYAL in any Driver box; the name in a gender or tax-ID box | | |
| F5 | 6 | FARTHEST TERMINAL | blank | 6679 or 104 | | |
| F6 | 6 | Anywhere on 127 | no 91580, 91585, 6679 | any of them | | |
| F7 | 11 | Vehicle row 1 garaging address | 4800 DAHLIA STREET D13 / DENVER / CO / 80216-3121 (read off the vehicle block's LOC line) | blank; another address; the producer's Meridian address | | |
| F8 | new | Vehicle row 1 COST NEW and the "$ AA ST AMT" box | COST NEW 26,680; ACV ticked; the AA / ST AMT amount blank | 100,000 (the hired-auto limit) or any amount beside ACV; COST NEW blank | yes | |
| F9 | new | SYM / AGE, COMP/OTC SYM, COLL SYM | all blank (owner decision 24 Sep: covered-auto symbols print on the 137) | 7 / 07 / 07 | | |
| F10 | new | USE (commercial, service, retail, pleasure, farm, for hire, OTHER) | nothing ticked and the OTHER description blank - the vehicle's own block prints "USE: NA" | any use ticked; OTHER ticked with "PRIVATE PASSENGER" (the live run 2 value - that is the vehicle's TYPE) | yes | |
| F11 | new | "ACORD 129 attached for additional vehicles" | unticked - one vehicle fits the 127 | ticked | | |
| F12 | new | Page 2 MAXIMUM DOLLAR VALUE SUBJECT TO LOSS | 26,680 (the one vehicle's cost new) | 1,000,000 or any other amount | | |

### G. ACORD 131

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| G1 | 1 | Header | {CAR_MUT_MIXED} / {NAIC_MUT} / `{POL_UMB}` | {NAIC_PC}; the 6E7 number | | |
| G2 | 9 | Umbrella EACH OCCURRENCE / AGGREGATE | 1,000,000 / 1,000,000 | blank, or 3,000,000 | yes | |
| G3 | 9 | Anywhere on 131 | no 3,000,000 - including the personal & advertising injury / OTHER limit | any 3,000,000 | | |
| G4 | 1 | Underlying GL row | {CAR_PC} / `{POL_GL}` (or `{POL_GL_SHORT}`) | carrier or number blank; Employers Mutual on the GL row | yes | |
| G5 | 1 | Underlying Auto row | {CAR_MUT_MIXED} / `{POL_AUTO}` (or `{FOOT_AUTO}`) | carrier or number blank | | |
| G6 | 2 | Underlying schedule | no Liquor, Pollution, OCP or Employers Liability entries | an Employers Liability row or E.L. limits; any of the others | | |
| G7 | new | Q14 "Do subcontractors carry coverages or limits less than applicant?" | blank, like 126 (row E9) | Y (the live run printed Y while 126 printed N) | yes | |
| G8 | new | PRIMARY LOCATION description (one-line box) | "Commercial general contractor." at a readable size | the whole paragraph in tiny type, cut off; "INSURED IS: LLC BUSINESS DESC: ..." | | |

### H. ACORD 137 CO

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| H1 | 1, 7 | Header | {CAR_MUT_MIXED} / {NAIC_MUT} / `{POL_AUTO}` | anything else | | |
| H2 | 7 | Business Auto liability | CSL ticked + 1,000,000 | blank; EACH PERSON ticked | yes | |
| H3 | 7 | Med Pay | 5,000 | blank | | |
| H4 | 7 | Uninsured Motorists | CSL + 1,000,000 | blank | | |
| H5 | 7 | Symbol grid | 1 (liability) / 2 (med pay) / 2 (UM) / 7 (comprehensive) / 7 (collision), and no "other symbol" ticked on any row | rows blank; 1 on every row; UM row "other: 1" | yes | |
| H6 | 7 | Truckers and Motor Carrier pages | completely blank | any value or tick | | |
| H7 | 7 | Hired physical damage comprehensive / collision deductible | 1,000 or blank | any other amount | | |

### P. ACORD 186

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| P1 | 1 | Header | EMC Property & Casualty Company / 25186 / `BBC7263-26` | another line's carrier or number | | |
| P2 | 4 | CONTRACTORS LICENSE NUMBER | blank - no document prints a contractor licence | W6258-0001 (the old broker's AGENT NO.) or AW 6258 | yes | |
| P3 | new | MINIMUM GL LIMITS REQUIRED OF SUBCONTRACTORS | both blank - no document states a required minimum | 1,000,000 / 2,000,000 (Orbin's own limits) | yes | |
| P4 | new | TOTAL COST OF SUBCONTRACTED WORK PAST YEAR | 350,000 (GL class 91585's exposure) | blank or another amount | | |
| P5 | new | Questions marked * (1 plans, 2 blasting, 3 excavation, 4 safety policy, 7 subcontractor limits, 8 certificates, 9 lease equipment, 10 boats, 13 lease employees) | all blank - the form says "* DO NOT ANSWER IF THIS FORM IS ATTACHED TO ACORD 126", and 126 is in this package | any answer (the live run printed 8 = N) | yes | |

### I. Every generated form (125, 126, 127, 131, 137 CO, 186)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| I1 | 4 | Producer block | the logged-in agency / name on all six | Commercial Risk Solutions / Terri Wroblewski on any; W6258 / AW 6258 / 303-996-7800 anywhere | | |
| I2 | 8 | Any party box | never "For Informational Purposes Only" (any spelling) | present | | |
| I3 | 3 | Every policy-number box | never a form number (list in D8), never `{ACCOUNT}` | present | | |
| I4 | new | Every Y on an underwriting question (125, 126, 127, 131, 186) | its explanation actually states the thing asked; otherwise the question is blank | a Y "explained" by the business description ("Commercial general contractor ...") or by the subcontractor sentence ("Subcontractors are required to carry their own ...") | yes | |

### J. Pre-download review (Field QA)

| # | Item | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|
| J1 | 5, 10 | no row comparing a dollar amount with a Per Project / Per Location box | "PerLocation / PerProject shows No but source is $2,000,000" | yes | |
| J2 | 5 | no row comparing a Claims-Made tick with a form title | "... source is Commercial Liability Umbrella Coverage Form" / "CG 00 01 04 13" | | |
| J3 | 3 | no row comparing a policy number with a form number | "source value is IM 7100 06 04" (or any form number in the D8 list) | | |
| J4 | 1, 10 | no row comparing one line's number or NAIC with another line's | "shows {POL_UMB} but the source value is {POL_AUTO}"; "{NAIC_MUT} vs {NAIC_PC}" | | |

### K. Send to Client - preview only (do not send)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| K1 | 11 | Vehicle table | **CONFIRM mode**: "We found 1 vehicle in your policy declarations..." with the Subaru row shown and pre-ticked | "Please list the vehicles to be insured"; an empty table | yes | |
| K2 | 11 | Location table | confirm mode with 4800 DAHLIA ST # D13 / DENVER / CO / 80216-3121 | "Please list every business location" | yes | |
| K3 | 11 | Drivers | no numbered "(Nth driver)" questions | "(1st driver)" ... "(25th driver)"; ERIN ROYAL pre-filled as a driver | yes | |
| K4 | 11 | Confirm items | legal name (ORBIN CONTRACTING LLC) and mailing address shown as confirm items, pre-ticked | missing; empty text boxes asking for them | | |
| K5 | 1, 3 | Carrier / NAIC / policy-number questions | none | any | | |
| K6 | 2 | Coverage questions | no Workers Comp, Employers Liability or Property questions | any | | |
| K7 | 1, 3, 4 | After opening the preview, download 125 / 126 / 127 / 131 again | every value in D-H unchanged | `IM 7100 06 04`, {NAIC_PC} beside Employers Mutual, or Commercial Risk Solutions comes back | | |

### L. Cover page

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| L1 | 2 | LINES OF BUSINESS | Liability, Inland Marine, Automobile, Umbrella - nothing else | Property, Crime, Workers Comp, Farm, Liquor, EPLI, OCP, Pollution | yes | |
| L2 | 4 | PRIOR CARRIER | never "Commercial Risk Solutions" (a broker, not a carrier); the current policies' own carriers may appear | "PRIOR CARRIER: Commercial Risk Solutions" | | |
| L3 | 8 | Anywhere | no "For Informational Purposes Only" | present | | |
| L4 | new | POLICY PERIOD | "To be confirmed (expired term 07/15/25 - 07/15/26)" | "current term" | | |
| L5 | new | Package summary paragraph | never says the account is currently in force | "currently in force" | | |

### M. Scores - record only, nothing is graded

Package ___ | 125 ___ | 126 ___ | 127 ___ | 131 ___ | 137 CO ___

### N. Backend log - grep after the run

| grep (in `orbin_retest_kit/backend-run.log`) | Expected | Result |
|---|---|---|
| `grep "combined_gap_fill: line-scoped groups"` | present, with groups `None` (package-level questions), `general_liab` (126), `auto` (127 / 137 CO) and `umbrella` (131). Offline, each line's scope is the common pages plus its own section only - 12 to 16 of the {p1} pages | |
| `grep -c "UNKNOWN_KEYS"` | few or none | |
| `grep "calculate_package_sqs failed"` | absent | |
| `grep "submitting account unavailable"` | absent - present means the login's agency could not be read, and every producer row (B5, C4, D5, D6, I1, L2) is void | |
| `grep "vehicle block cells applied"` | present: cost_new ...=26680 and auto_vehicle_use cleared | |
| `grep "GL deductible applies to"` | present, `'other'` | |
| `grep "operations description from the applicant's own words"` | present | |
| `grep "answered both ways"` / `grep "PRODUCER_IDENTIFIER"` | either may appear - each line is a wrong answer the fill produced and the guard removed | |

## What to send back

1. This README with the **Result** column filled (row ID + PASS / FAIL + the
   literal value for every FAIL).
2. The generated PDFs: ACORD 125, 126, 127, 131, 137 CO and the cover page.
3. Screenshots of every **Send = yes** row - at minimum: the recommended-forms list
   after ticking 127; the whole Data Consistency panel (cards, the per-line rows,
   the policies table); the warnings / hard stops; the pre-download review list;
   the Send to Client preview (vehicle table, location table, drivers, confirm
   items).
4. The whole matching lines from the four greps in section N (or "none").
5. The scores from section M.

## Known, not graded here

- **Dates.** The printed term (07/15/2025 - 07/15/2026) ended on 07/15/2026.
  ACORD 125's proposed dates are asked of the producer (15 Sep ruling); the
  section forms keep the current policy's identity with the ended date blank.
- **The umbrella remark is run-together on purpose**, like the client's
  certificate. Since 24 Sep the change reader re-spaces it itself
  (`narrative_facts.respace_glued_prose`), so **a B4 conflict card is a FAIL** -
  with one exception worth a screenshot: open the certificate's extracted
  `additional_remarks_text` / `certificate_description_of_operations`. If the
  note is not there at all, extraction never captured it (send that); if it is
  there, in any spacing, the reader missed it (send that too). With no dated
  sentence anywhere the row stays a conflict by owner decision, and its
  suggested value is the amount the forms print (D16).
- **Drive Other Car name order.** The schedule prints "ROYAL, ERIN" (as the retest
  spec asked); the continuation page also prints "ERIN ROYAL" (as the real package
  does), so F4 / K3 test the 14 Sep named-individual rule whichever order
  extraction copies.
- The producer ADDRESS prints blank when the login's agency differs from the
  documents' (by design since 14 Sep); e-mail and phone come from the login
  since 24 Sep.
- **An abbreviated placeholder ("FIO", "FIPO") is NOT refused.** The party test
  is structural, and an initialism reads exactly like a real company ("3M",
  "EMC", "CRS"). The kit prints the client's full run-together phrase, which is
  refused; an abbreviation in a live document would print.
- ACORD 137 CO's hired physical damage deductible (H7) still comes from gap
  fill, not a deterministic reader - 1,000 or blank are both acceptable.
- ACORD 160 is the known mislabelled form; leave it.

## How this kit was built and self-checked

`backend/.venv/bin/python backend/scripts/make_orbin_retest_pdfs.py` rebuilds the
three PDFs and this README, offline (no database, network or LLM call), and fails
unless:

- the certificate's four run-together strings come back verbatim from plain
  pdfplumber `page.extract_text()` AND from the pipeline's own text layer;
- the policy contains every form number above, the account number, the three
  "No Coverage" rows as lines of their own, the 7-line endorsement menu, the Drive
  Other Car line and the VIN;
- {hit}/{total} passages copied verbatim from the client's own OCR
  (`271page_test_data/271page-testdec.txt`) come back as consecutive lines through
  the pipeline's text layer - character similarity to the real pages: mean
  {sim_txt};
- the pipeline's own classifier types the files dec page / certificate / narrative;
- the page-header carrier binder (`_header_carrier_name`) reads each section's own
  carrier off {ok_b}/{n_b} section pages;
- both printings of the Drive Other Car name sit under a named-individual heading
  (`named_individuals.printing_roles`);
- every page carries at least 100 native characters and no image, so the live
  pipeline reads this text instead of sending the page to Google Vision.

**Different from the real package, on purpose:** 49 pages instead of 271; every
page (ISO pages included) carries a carrier + policy number + producer header
stamp; per the retest spec, the umbrella's underlying schedule prints `{POL_GL}` /
`{POL_AUTO}` (the real one printed `{POL_GL_SHORT}` / `{FOOT_AUTO}`), the GL dec
prints "Coverage Form: CG 00 01 04 13 ... Occurrence", the umbrella dec prints the
`CU7001A 11-15` coverage-form line, the Auto Elite Extension carries a hired-auto
physical damage deductible schedule, and the certificate's producer is
Commercial Risk Solutions, Inc. (the real one printed "CRS Insurance Brokerage").
"""


if __name__ == "__main__":
    main()
