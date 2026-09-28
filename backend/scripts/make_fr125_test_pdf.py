"""
make_fr125_test_pdf.py - the FR125 kit, VERSION 2: a dense, 100-page submission
that fills an ACORD 125 the way the client's Vertafore data map fills it.

    python3 backend/scripts/make_fr125_test_pdf.py

Writes into `fr125_test_data/`:
    FR125_front_range_package.pdf   100 FULL pages, >= 300,000 text characters
    FR125_answer_key.json           a verdict for ALL 548 ACORD 125 fields
    README-FR125-HOW-TO-TEST.md

Version 1 (archived: fr125_test_data/v1_round2_test2/) printed one short
section per page - 38 of its 100 pages held under 800 characters - and asked
for a form the client's rules keep mostly blank. The owner asked for the
opposite on both counts (28 Sep): every page nearly full, and a form filled
like the data map. So:

  FLOW LAYOUT   content pours down the page and on to the next; a table
                crossing a page break repeats its header. No page is a heading
                and white space. The total is pinned at exactly 100 pages.
  FULL FILL     the documents STATE a source for ~320 of the 548 boxes -
                three named insureds, four premises, both contacts with phone
                types, the mortgagee, fourteen YES answers with their detail,
                three prior-carrier years, three claims. Every client rule
                still holds; the documents just verify more.
  STILL HARD    scanned pages with no text layer, answers given by an X in a
                column, abbreviated and two-line headers, riffled cells,
                teletype, drifting columns, dot leaders, a landscape schedule,
                figures spelled three ways, placeholders in source cells, one
                claim on two valuations, a resolution that has not happened.
"""
from __future__ import annotations

import json
import random
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Tuple

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import _fr125_data as D                                          # noqa: E402

from reportlab.lib.pagesizes import LETTER, landscape            # noqa: E402
from reportlab.pdfgen import canvas                              # noqa: E402

ROOT     = HERE.parents[2]
BACKEND  = HERE.parents[1]
OUT_DIR  = ROOT / "fr125_test_data"
PDF_PATH = OUT_DIR / "FR125_front_range_package.pdf"
KEY_PATH = OUT_DIR / "FR125_answer_key.json"
DOC_PATH = OUT_DIR / "README-FR125-HOW-TO-TEST.md"

W, H = LETTER
LEFT = 36.0
MONO, BOLD = "Courier", "Courier-Bold"
FS = 7.0
LEAD = 10.0
BODY_TOP = H - 60.0
LINES_PER_PAGE = int((BODY_TOP - 36.0) // LEAD)
WRAP = 124
TARGET_PAGES = 100
MIN_CHARS = 300_000

SCANNED_TEXT: List[str] = []


# ═════════════════════════════════════════════════════════════════════════════
# The flow engine
# ═════════════════════════════════════════════════════════════════════════════
class Line:
    """One printed line: (x, text, font, size, kind) items, and an optional rule
    underneath with column separators (ruled tables)."""
    __slots__ = ("items", "rule", "cols")

    def __init__(self, items=None, rule=False, cols=None):
        self.items = items or []
        self.rule = rule
        self.cols = cols


class Flow:
    def __init__(self):
        self.pages: List[tuple] = []       # ("flow", title, lines) or ("special", fn, wide)
        self.cur: List[Line] = []
        self.title = ""
        self.cur_title = ""
        self.pending: List[tuple] = []     # scans / landscape pages waiting for a break

    def _new_page(self):
        if self.cur:
            self.pages.append(("flow", self.cur_title, self.cur))
        self.cur = []
        self.cur_title = self.title
        # an insert waits for the page in progress to FILL - it never cuts it short
        while self.pending:
            self.pages.append(self.pending.pop(0))

    def room(self) -> int:
        return LINES_PER_PAGE - len(self.cur)

    def need(self, n: int):
        if self.room() < n:
            self._new_page()

    def add(self, line: Line):
        if self.room() <= 0:
            self._new_page()
        if not self.cur:
            self.cur_title = self.title
        self.cur.append(line)

    def special(self, fn: Callable, wide: bool = False):
        if self.cur:
            self.pending.append(("special", fn, wide))
        else:
            self.pages.append(("special", fn, wide))

    def page_count(self) -> int:
        return len(self.pages) + (1 if self.cur else 0) + len(self.pending)

    def doc(self, title: str, subtitle: str = ""):
        self.need(6)
        self.title = title
        if not self.cur:
            self.cur_title = title
        if self.cur:
            self.add(Line())
        self.add(Line([(LEFT, "=" * 124, MONO, 6.2, "plain")]))
        self.add(Line([(LEFT, title[:110], BOLD, 8.2, "plain")]))
        if subtitle:
            self.add(Line([(LEFT, subtitle[:124], MONO, FS, "plain")]))

    def head(self, text: str):
        self.need(4)
        self.add(Line())
        self.add(Line([(LEFT, text[:120], BOLD, 7.4, "plain")]))

    def text(self, s: str, x: float = LEFT, font=MONO):
        self.add(Line([(x, s[:130], font, FS, "plain")]))

    def para(self, s: str, width: int = WRAP, indent: float = 0.0):
        for ln in _wrap(s, width):
            self.text(ln, LEFT + indent)

    def blank(self):
        if self.cur:
            self.add(Line())

    def kv(self, pairs, leader: bool = False, width: int = 60):
        """Label and value. A long value first shortens its dot leader, then
        wraps - a value is NEVER clipped at the page edge."""
        for k, v in pairs:
            v = str(v)
            if leader:
                dots = max(3, min(width - len(k), WRAP - len(k) - len(v) - 2))
                head = f"{k} " + "." * dots + " "
            else:
                head = f"{k:<34}"
            room = WRAP - len(head)
            chunks = _wrap(v, max(20, room)) or [""]
            self.text(head + chunks[0])
            for ch in chunks[1:]:
                self.text(" " * len(head) + ch)

    def teletype(self, lines):
        for ln in lines:
            self.add(Line([(LEFT, ln[:56], MONO, FS, "tracked")]))

    def two_column(self, left, right):
        for i in range(max(len(left), len(right))):
            items = []
            if i < len(left):
                items.append((LEFT, left[i][:58], MONO, FS, "plain"))
            if i < len(right):
                items.append((322.0, right[i][:62], MONO, FS, "drift" if i % 3 else "plain"))
            self.add(Line(items))

    def table(self, header, rows, xs, style: str = "ruled", repeat_header: bool = True):
        """ruled (grid, cells clipped), plain (aligned, clipped) or riffled (cells
        NOT clipped - a long cell runs under the next column)."""
        widths = [int(((xs[i + 1] if i + 1 < len(xs) else W - LEFT) - xs[i]) / (FS * 0.6)) - 1
                  for i in range(len(xs))]

        def cells(row, bold=False):
            out = []
            for i, (x, c) in enumerate(zip(xs, row)):
                c = str(c)
                if style != "riffled":
                    c = c[: max(1, widths[i])]
                out.append((x, c, BOLD if bold else MONO, FS, "plain"))
            return out

        hdrs = header if header and isinstance(header[0], (list, tuple)) else [header]
        self.need(len(hdrs) + 2)
        for h in hdrs:
            self.add(Line(cells(h, True), rule=(style == "ruled"), cols=xs))
        for row in rows:
            if self.room() <= 0:
                self._new_page()
                if repeat_header:
                    for h in hdrs:
                        self.add(Line(cells(h, True), rule=(style == "ruled"), cols=xs))
            self.add(Line(cells(row), rule=(style == "ruled"), cols=xs))

    def xcolumn(self, rows):
        """A questionnaire answered by an X in a YES or NO column."""
        self.need(3)
        self.add(Line([(LEFT, "#", BOLD, FS, "plain"), (LEFT + 22, "QUESTION", BOLD, FS, "plain"),
                       (LEFT + 340, "YES", BOLD, FS, "plain"), (LEFT + 368, "NO", BOLD, FS, "plain")]))
        for n, q, ans in rows:
            self.add(Line([(LEFT, n, MONO, FS, "plain"), (LEFT + 22, q[:72], MONO, FS, "plain"),
                           (LEFT + 342, "", MONO, FS, "box_on" if ans == "Y" else "box_off"),
                           (LEFT + 370, "", MONO, FS, "box_on" if ans == "N" else "box_off")]))

    def fill_page(self, bank: List[str]):
        if not self.cur:
            return
        i = 0
        while self.room() > 0:
            self.text(bank[i % len(bank)])
            i += 1


def _wrap(text: str, width: int) -> List[str]:
    out, line = [], ""
    for word in str(text).split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Rendering
# ═════════════════════════════════════════════════════════════════════════════
def _tracked(c, x, y, text, size):
    gw = size * 0.6
    cx = x
    for ch in text:
        if ch == " ":
            cx += gw * 5
            continue
        c.drawString(cx, y, ch)
        cx += gw * 2


def _draw_flow_page(c, title: str, lines: List[Line], n: int, total: int):
    c.setFont(MONO, 6.0)
    c.drawString(LEFT, H - 26, f"{D.CUR_CARRIER}   {D.CUR_CARRIER_WEB}   Service "
                               f"{D.CUR_CARRIER_PHONE}   |   Submission package - {D.NAME}")
    c.setFont(BOLD, 7.0)
    c.drawString(LEFT, H - 40, title[:110])
    y = BODY_TOP
    for ln in lines:
        for x, text, font, size, kind in ln.items:
            if kind == "tracked":
                c.setFont(font, size)
                _tracked(c, x, y, text, size)
            elif kind in ("box_on", "box_off"):
                c.setLineWidth(0.5)
                c.rect(x, y - 2, 8, 8, stroke=1, fill=0)
                if kind == "box_on":
                    c.setFont(BOLD, 8)
                    c.drawString(x + 1.2, y - 0.6, "X")
            else:
                c.setFont(font, size)
                c.drawString(x, y + (0.9 if kind == "drift" else 0.0), text)
        if ln.rule and ln.cols:
            c.setLineWidth(0.3)
            c.line(ln.cols[0] - 2, y - 2.6, W - LEFT, y - 2.6)
            for x in ln.cols:
                c.line(x - 2, y + LEAD - 2.6, x - 2, y - 2.6)
            c.line(W - LEFT, y + LEAD - 2.6, W - LEFT, y - 2.6)
        y -= LEAD
    c.setFont(MONO, 6.0)
    c.drawString(W - 112, 18, f"Page {n} of {total}")


def _font(size: int):
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Courier.ttc",
                 "/System/Library/Fonts/Supplemental/Courier New.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:                                       # noqa: BLE001
            continue
    return ImageFont.load_default()


def scanned_page(lines: List[str], skew: float = 0.7, fax: str = "",
                 quality: str = "scan") -> Callable:
    """A raster page with NO text layer - only OCR can read it. Filled top to
    bottom, skewed and speckled; `fax` halves the vertical resolution."""
    from PIL import Image, ImageDraw, ImageFilter
    SCANNED_TEXT.extend(lines)
    rnd = random.Random(len(SCANNED_TEXT))
    img = Image.new("L", (1700, 2200), 250)
    d = ImageDraw.Draw(img)
    f_body, f_head = _font(27), _font(22)
    y = 70
    if fax:
        d.text((70, 30), fax, fill=40, font=f_head)
        y = 100
    for ln in lines:
        d.text((95, y), ln, fill=rnd.randint(10, 45), font=f_body)
        y += 39
    for _ in range(3200):
        img.putpixel((rnd.randint(0, 1699), rnd.randint(0, 2199)), rnd.randint(60, 190))
    img = img.rotate(skew, resample=Image.BICUBIC, fillcolor=250)
    if quality == "fax":
        img = img.resize((1700, 1100)).resize((1700, 2200))
    img = img.filter(ImageFilter.GaussianBlur(0.55))
    tmp = Path(tempfile.gettempdir()) / f"fr125v2_scan_{len(SCANNED_TEXT)}.png"
    img.save(tmp)

    def draw(c, w, h, _p=str(tmp)):
        c.drawImage(_p, 0, 0, width=w, height=h)
    return draw


# ═════════════════════════════════════════════════════════════════════════════
# The package
# ═════════════════════════════════════════════════════════════════════════════
_CLAUSES = [
    "We will pay those sums that the insured becomes legally obligated to pay as damages because of bodily injury or property damage.",
    "We will have the right and duty to defend the insured against any suit seeking those damages; there is no duty to defend otherwise.",
    "The amount we will pay for damages is limited as described in the Limits Of Insurance section of this coverage part.",
    "This insurance applies only if the injury or damage occurs during the policy period within the coverage territory.",
    "Expected or intended injury from the standpoint of the insured is excluded, except injury resulting from reasonable force.",
    "Contractual liability is excluded unless the liability is assumed in an insured contract executed before the injury.",
    "This insurance does not apply to the discharge, dispersal, seepage, migration, release or escape of pollutants.",
    "Aircraft, auto or watercraft owned or operated by or rented or loaned to any insured is excluded under this coverage form.",
    "Damage to your work arising out of it and included in the products-completed operations hazard is excluded.",
    "Recall of products, work or impaired property is excluded, including any cost incurred for loss of use.",
    "Supplementary payments include all expenses we incur and reasonable expenses incurred at our request.",
    "Each person or organization is an insured only with respect to liability arising out of your operations or premises.",
    "Duties in the event of occurrence: notify us as soon as practicable of an occurrence which may result in a claim.",
    "Other insurance: this insurance is primary except when excess insurance is available as described in the conditions.",
    "Premium audit: premiums for this coverage part are computed in accordance with our rules and rates.",
    "Separation of insureds: except with respect to limits, this insurance applies as if each named insured were the only one.",
    "Transfer of rights of recovery: if the insured has rights to recover all or part of any payment, those rights pass to us.",
    "When we do not renew, we will mail or deliver written notice of the nonrenewal before the expiration date.",
    "Coverage territory means the United States of America, including its territories and possessions, Puerto Rico and Canada.",
    "Mobile equipment means land vehicles, including machinery and apparatus attached thereto, whether or not self-propelled.",
    "Occurrence means an accident, including continuous or repeated exposure to substantially the same harmful conditions.",
    "Property damage means physical injury to tangible property, including all resulting loss of use of that property.",
    "Suit means a civil proceeding in which damages because of bodily injury or property damage are alleged.",
    "Covered autos: the symbols entered next to a coverage on the declarations designate the only covered autos.",
    "We will pay for loss to a covered auto or its equipment under comprehensive coverage from any cause except collision.",
    "Covered property includes your business personal property located in or on the building at the described premises.",
    "Covered causes of loss means direct physical loss unless the loss is excluded or limited in this form.",
    "Coinsurance: we will not pay the full amount of a loss if the value of covered property exceeds the stated percentage.",
    "Mortgageholders: we will pay for covered loss to buildings to each mortgageholder shown in the declarations.",
    "Loss payment: in the event of covered loss or damage, at our option we will pay the value of lost or damaged property.",
    "The umbrella applies to damages in excess of the retained limit, the total of the underlying insurance or the SIR.",
    "Maintenance of underlying insurance: the scheduled underlying policies must be maintained in full effect.",
    "Cancellation: the first named insured may cancel this policy by mailing or delivering advance written notice.",
    "Examination of your books and records: we may examine and audit your books and records as they relate to this policy.",
    "Inspections and surveys: we have the right to make inspections and surveys at any time and report on conditions.",
    "Changes: this policy contains all the agreements between you and us concerning the insurance afforded.",
    "Certified acts of terrorism are covered subject to the federal program's annual aggregate limit.",
    "The insurance does not apply under any liability coverage to injury arising from nuclear material.",
    "This insurance does not apply to injury or damage arising out of any fungi or bacteria.",
    "Injury arising out of refusal to employ, termination, coercion or other employment practices is excluded.",
]


def wording_bank(seed: int) -> List[str]:
    rnd = random.Random(seed)
    return [f"{k % 9 + 1}.{rnd.randint(1, 12)}  {_CLAUSES[rnd.randrange(len(_CLAUSES))]}"[:124]
            for k in range(260)]


_FIRST = ["Karen", "Robert", "Li", "Miguel", "Tara", "Jonas", "Alma", "Peter", "Sofia",
          "Derek", "Brian", "Elena", "Chris", "Hana", "Luis", "Maria", "Owen", "Rosa",
          "Grant", "Nia"]
_LAST = ["Anderson", "Baca", "Chen", "Diaz", "Evans", "Fischer", "Garcia", "Hughes",
         "Ibarra", "Jensen", "Kowalski", "Lopez", "Moore", "Nguyen", "Ortega", "Ortega",
         "Price", "Quintana", "Reyes", "Sato"]


def build_flow() -> Flow:
    SCANNED_TEXT.clear()
    f = Flow()
    C0, C1 = D.CONTACTS
    L = D.LOCATIONS
    M = D.MORTGAGEE
    Q = D.QUESTIONS

    # 1. Cover letter - the ONLY place the RECEIVING carrier is addressed
    f.doc("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION",
          f"{D.PRODUCER}   {D.PRODUCER_L1}, {D.PRODUCER_L2}, {D.PRODUCER_CITY}, "
          f"{D.PRODUCER_STATE} {D.PRODUCER_ZIP}   Tel {D.PRODUCER_PHONE}   {D.PRODUCER_EMAIL}")
    for ln in ["", "August 18, 2026", "",
               f"TO:        {D.CARRIER}",
               f"ATTN:      {D.UNDERWRITER}, Commercial Underwriting - {D.UNDERWRITER_OFFICE}",
               f"PROGRAM:   {D.PROGRAM_NAME}",
               f"RE:        {D.NAME} - new business submission - QUOTE requested",
               f"Agency customer ID (our AMS): {D.AGENCY_CUSTOMER_ID}", ""]:
        f.text(ln)
    f.para(f"Dear {D.UNDERWRITER.split()[0]}, please quote the account below for the term "
           f"{D.PROPOSED_EFF} to {D.PROPOSED_EXP}. The insured already holds its workers "
           f"compensation and inland marine policies with {D.CARRIER}; the lines below are new "
           f"to you. The current package is written by the incumbent and will NOT be renewed "
           f"there - its declarations are enclosed for reference only.")
    f.head("LINES REQUESTED")
    f.text("  Commercial General Liability     Commercial Property     Business Auto     Umbrella")
    f.head("LINES NOT REQUESTED")
    f.text("  Workers Compensation and Inland Marine (already with you)   Cyber   Crime   Liquor   "
           "Professional")
    f.head("BILLING AND PAYMENT")
    f.kv([("Billing preference", f"{D.BILLING} bill"),
          ("Payment plan requested", f"{D.PAYMENT_PLAN_WORD} ({D.PAYMENT_PLAN_CODE})"),
          ("Method of payment", f"{D.PAYMENT_METHOD} (automatic ACH debit)"),
          ("Premium indication", "not requested at this stage")])
    f.head("REMARKS FOR THE APPLICATION")
    f.para(D.REMARKS)
    f.blank()
    f.para("Enclosures: applicant profile, named insured schedule, contacts, premises schedule "
           "and statement of values, operations, financials, census, signed questionnaire "
           "(two pages), supporting documents for every YES answer, current and prior "
           "declarations, loss runs, lease and loan documents, logs and schedules.")
    f.text(f"Regards,   {D.PRODUCER_CONTACT}, {D.PRODUCER}")

    # 2. The carrier's acknowledgement - NAIC, program code, audit
    f.doc(f"{D.CARRIER.upper()} - ACKNOWLEDGEMENT OF SUBMISSION",
          f"{D.CARRIER}   NAIC {D.CARRIER_NAIC}   1200 17th Street, Suite 1500, Denver, CO 80202")
    f.kv([("Insured", D.NAME), ("Program", D.PROGRAM_NAME), ("Program code", D.PROGRAM_CODE),
          ("Underwriter", D.UNDERWRITER), ("Underwriting office", D.UNDERWRITER_OFFICE),
          ("Transaction", "New business - quote"),
          ("Premium audit", f"{D.AUDIT_WORD} (audit period code {D.AUDIT_CODE})"),
          ("Existing policies with us", "; ".join(f"{a} {b}" for a, b in D.OTHER_POLICIES))],
         leader=True)
    f.para("Receipt of the submission is acknowledged. No coverage is bound by this letter. "
           "Quotation requires the signed application, currently valued loss runs and the "
           "statement of values. Program minimum and deposit terms are set at quotation.")

    # 3. Applicant profile - dot leaders, identifiers, placeholders
    f.doc("APPLICANT PROFILE")
    f.kv([("Legal name", D.NAME),
          ("Mailing address", f"{D.MAIL_L1}, {D.MAIL_L2}, {D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}"),
          ("Business phone", D.BUS_PHONE), ("Fax", "N/A"), ("Website", D.WEBSITE),
          ("Legal entity", f"Limited Liability Company ({D.ENTITY})"),
          ("Members / managers", "see Schedule A of the Operating Agreement (scanned, enclosed)"),
          ("Date business started (Articles)", D.START_DATE_WORDS),
          ("Relocated to Commerce Way", "2019"), ("Nature of business", D.NATURE)], leader=True)
    f.blank()
    f.table(["IDENTIFIER", "VALUE", "ISSUED BY / NOTE"],
            [["FEIN", D.FEIN, "IRS - see W-9"],
             ["CO sales tax account", D.CO_TAX_ACCOUNT, "Colorado Department of Revenue - not a federal number"],
             ["USDOT", D.USDOT, "FMCSA - vehicles over 10,001 lb GVWR"],
             ["Contractor licence", D.CONTRACTOR_LIC, "Colorado State Electrical Board (Master)"],
             ["NAICS", D.NAICS, "Electrical Contractors and Other Wiring Installation"],
             ["SIC", D.SIC, "Electrical Work"],
             ["GL classification", D.GL_CODE, "Electrical work - within buildings (rating schedule)"]],
            [LEFT, LEFT + 150, LEFT + 250], style="riffled")
    f.text("Established 2014-06-15. Formation documents on file with the Colorado Secretary of State.")

    # 4. Named insureds and the organisation
    f.doc("SCHEDULE OF NAMED INSUREDS AND ORGANISATION")
    f.para(f"{D.NAME} is the first named insured. It is {D.PARENT_PCT} owned by "
           f"{D.PARENT_ORG} ({D.PARENT_RELATIONSHIP.lower()}), which is NOT an insured under "
           f"this submission. The two entities below are requested as additional named insureds.")
    rows = [[D.NAME, D.FEIN, D.ENTITY, "Sch. A", D.SIC, D.NAICS, D.GL_CODE]]
    rows += [[o["name"], o["fein"], o["entity"], o["members"], o["sic"], o["naics"], o["gl"]]
             for o in D.OTHER_INSUREDS]
    f.table(["NAMED INSURED", "FEIN", "ENT", "MBRS", "SIC", "NAICS", "GL"], rows,
            [LEFT, LEFT + 200, LEFT + 262, LEFT + 292, LEFT + 324, LEFT + 356, LEFT + 400],
            style="riffled")
    for o in D.OTHER_INSUREDS:
        f.head(o["name"].upper())
        f.kv([("Mailing address", f"{o['l1']}, {o['l2']}, {o['city']}, {o['state']} {o['zip']}"),
              ("Business phone", o["phone"]), ("Website", o["web"]),
              ("Legal entity", f"{o['entity']} - {o['members']} member(s)"),
              ("Relationship", o["role"])])
    f.head("ORGANISATION CHART")
    f.table(["ENTITY", "RELATIONSHIP TO APPLICANT", "% OWNED"],
            [[D.PARENT_ORG, D.PARENT_RELATIONSHIP, D.PARENT_PCT],
             [D.SUB_ORG, D.SUB_RELATIONSHIP, D.SUB_PCT],
             [D.OTHER_INSUREDS[1]["name"], "Sister company (common parent)", "--"]],
            [LEFT, LEFT + 220, LEFT + 420])

    # 5. Contacts - drifting columns, phone TYPES
    f.doc("CONTACTS FOR THIS SUBMISSION")
    f.two_column(
        ["CONTACT 1", f"Type ......... {C0['type']}", f"Name ......... {C0['name']}",
         f"Primary ...... {C0['phone']} ({C0['phone_type'].lower()})",
         f"Secondary .... {C0['phone2']} ({C0['phone2_type'].lower()})",
         f"E-mail ....... {C0['email']}", f"Alt e-mail ... {C0['email2']}",
         "Available weekdays 7:00-3:30 for site", "inspection scheduling."],
        ["CONTACT 2", f"Type ......... {C1['type']}", f"Name ......... {C1['name']}",
         f"Primary ...... {C1['phone']} ({C1['phone_type'].lower()})",
         f"Secondary .... {C1['phone2']} ({C1['phone2_type'].lower()})",
         f"E-mail ....... {C1['email']}", f"Alt e-mail ... {C1['email2']}",
         "Billing, audit and certificate", "requests."])

    # 6. Premises - abbreviated headers, riffled
    f.doc("SCHEDULE OF PREMISES",
          "CL = city limits, INT = insured's interest, FT/PT = employees at the location, "
          "LSD = any area leased to others.")
    f.table(["LOC", "BLD", "STREET", "STE", "CITY", "CNTY", "ST", "ZIP", "CL", "INT"],
            [[l["num"], l["bldg"], l["l1"], l["l2"] or "--", l["city"], l["county"],
              l["state"], l["zip"], "IN" if l["inside"] else "OUT", l["interest"].upper()]
             for l in L],
            [LEFT, LEFT + 24, LEFT + 48, LEFT + 150, LEFT + 206, LEFT + 290, LEFT + 336,
             LEFT + 356, LEFT + 392, LEFT + 414], style="riffled")
    f.blank()
    f.table(["LOC", "FT", "PT", "ANN REV", "OCC SF", "PUB SF", "TOT SF", "LSD"],
            [[l["num"], l["ft"], l["pt"], l["revenue"], l["occupied"], l["public"],
              l["total_area"], l["leased"]] for l in L],
            [LEFT, LEFT + 30, LEFT + 58, LEFT + 88, LEFT + 168, LEFT + 222, LEFT + 272,
             LEFT + 326], style="riffled")
    f.head("OPERATIONS AT EACH LOCATION")
    for l in L:
        f.para(f"Location {l['num']} - {l['l1']}, {l['city']}: {l['ops']}", indent=6)
    f.head("PREMISES - NARRATIVE")
    f.para("Location 1 is roughly one third of a 15,000 sq ft multi-tenant flex building "
           "leased from its owner; about 500 sq ft - the counter and will-call area - is open "
           "to the public. Location 2 is an owned 8,000 sq ft fleet building outside the Denver "
           "city limits in unincorporated Adams County, mortgaged to Peak National Bank. "
           "Location 3 is a 1,200 sq ft branch suite in a 22,000 sq ft office building. "
           "Location 4 is an owned 3,000 sq ft storage building in Longmont; half of it is "
           "sublet to a cabinet shop. Eighteen full-time and two part-time employees work "
           "across the four premises; company revenue of about $4.25 million is booked by "
           "location as shown above.")

    # 7. Statement of values - LANDSCAPE, standalone
    def sov(c, w, h):
        c.setFont(MONO, 6.0)
        c.drawString(LEFT, h - 26, f"{D.CUR_CARRIER}   {D.CUR_CARRIER_WEB}")
        c.setFont(BOLD, 8.2)
        c.drawString(LEFT, h - 42, "STATEMENT OF VALUES - LOCATIONS 1-4 - AS OF 08/31/2026")
        xs = [LEFT, LEFT + 30, LEFT + 58, LEFT + 180, LEFT + 290, LEFT + 330, LEFT + 380,
              LEFT + 440, LEFT + 510, LEFT + 580, LEFT + 640]
        hdr = ["LOC", "BLD", "ADDRESS", "CITY", "ST", "ZIP", "OCC SF", "BUILDING", "BPP",
               "EQUIP", "CONST / YR / ROOF / PROT"]
        y = h - 64
        c.setFont(BOLD, 6.8)
        for x, t in zip(xs, hdr):
            c.drawString(x, y, t)
        vals = [("Tenant - N/A", "$385,000", "$240,000", "JM 1998 2016 PC3"),
                ("$1,480,000", "$210,000", "$165,000", "MNC 2004 2024 PC5"),
                ("Tenant - N/A", "$62,000", "$18,000", "FR 2009 2019 PC2"),
                ("$420,000", "$95,000", "$12,000", "F 1976 2021 PC4")]
        c.setFont(MONO, 6.8)
        for l, v in zip(L, vals):
            y -= 13
            for x, t in zip(xs, [l["num"], l["bldg"], l["l1"], l["city"], l["state"], l["zip"],
                                 l["occupied"], v[0], v[1], v[2], v[3]]):
                c.drawString(x, y, str(t))
        y -= 18
        rnd = random.Random(7)
        c.setFont(MONO, 6.2)
        c.drawString(LEFT, y, "CONTENTS DETAIL BY LOCATION (BPP) - valued at replacement cost")
        for i in range(52):
            y -= 8.6
            l = L[i % 4]
            c.drawString(LEFT, y, f"{l['num']:>2}  "
                         f"{rnd.choice(['Wire','Conduit','Fixtures','Panels','Breakers','Office','Tools','Lifts','Ladders','Meters'])}"
                         f" lot {i + 1:03d}   qty {rnd.randint(4, 900):>4}   unit ${rnd.randint(8, 2400):>5}   "
                         f"ext ${rnd.randint(500, 42000):>7,}   bin {rnd.choice('ABCDEFGH')}-{rnd.randint(1, 40):02d}   "
                         f"counted 08/{rnd.randint(1, 28):02d}/2026 by {rnd.choice(['LO', 'MO', 'SJ', 'JS', 'RB'])}")
    f.special(sov, wide=True)

    # 8. Operations
    f.doc("OPERATIONS")
    f.head("DESCRIPTION OF PRIMARY OPERATIONS")
    f.para(D.PRIMARY_OPERATIONS)
    f.head("DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS")
    f.para(D.OTHER_INSURED_OPERATIONS)
    f.head("REVENUE MIX - % OF TOTAL SALES")
    f.kv([("Retail sales", D.RETAIL_PCT),
          ("Installation, service or repair work", D.INSTALL_PCT),
          ("... of which performed OFF premises", D.INSTALL_OFF_PCT)], leader=True)
    f.para("Not a retailer, not a manufacturer, not a wholesaler. Service work is billed on "
           "time and materials; installation is bid. The office and warehouse support field "
           "crews at customer locations.")

    # 9. Financials
    f.doc("REVENUE, PAYROLL AND HEADCOUNT")
    f.table(["PERIOD", "REVENUE", "REVENUE ($000)"],
            [[p, r, r.replace("$", "").replace(",000", "")] for p, r in D.REVENUE_BY_YEAR],
            [LEFT, LEFT + 150, LEFT + 260])
    f.text("Annual revenue for this application = FY2025 actual, booked by location:")
    f.table(["LOC", "FY2025 REVENUE", "FT", "PT"],
            [[l["num"], l["revenue"], l["ft"], l["pt"]] for l in L] + [["TOTAL", "$4,250,000", "18", "2"]],
            [LEFT, LEFT + 60, LEFT + 180, LEFT + 220])
    f.head("REVENUE BY MONTH - FY2025")
    f.table(["MONTH", "REVENUE"], [list(r) for r in D.MONTHLY_REVENUE_FY2025],
            [LEFT, LEFT + 120], style="plain")
    f.head("PAYROLL BY CLASS - CALENDAR 2025")
    f.table(["CLASS", "FT", "PT", "PAYROLL"],
            [["Electricians (field)", "12", "0", "$1,150,000"], ["Apprentices", "3", "1", "$210,000"],
             ["Management / estimating / office", "3", "1", "$280,000"],
             ["TOTAL", "18", "2", D.TOTAL_PAYROLL]],
            [LEFT, LEFT + 180, LEFT + 220, LEFT + 260])
    f.para(f"Headcount {D.HEADCOUNT_TOTAL} (18 full-time, 2 part-time). In peak season "
           f"{D.SEASONAL_TEMPS} laborers are supplied by Mile High Staffing - agency employees, "
           "NOT on the insured's payroll.")

    # 10. Census
    # Luis Ortega (row 14) is the managing member AND the safety manager - the
    # safety programme names him, so the census must too.
    titles = (["Master Electrician"] * 2 + ["Journeyman Electrician"] * 10 + ["Apprentice"] * 2
              + ["Managing Member / Safety Mgr", "Estimator", "Office Manager", "Apprentice",
                 "Apprentice", "Office Assistant"])
    locs = ["1"] * 12 + ["2"] * 4 + ["3"] * 2 + ["1", "2"]
    status = ["FT"] * 18 + ["PT", "PT"]
    f.doc("EMPLOYEE CENSUS")
    f.table(["EMP", "NAME", "POSITION", "ST", "LOC", "HIRED"],
            [[f"E-{100 + i}", f"{_LAST[i]}, {_FIRST[i]}", titles[i], status[i], locs[i],
              f"{(i % 12) + 1:02d}/{(i * 3) % 27 + 1:02d}/{2014 + i % 11}"] for i in range(20)],
            [LEFT, LEFT + 40, LEFT + 150, LEFT + 290, LEFT + 312, LEFT + 342])

    # 11. Questionnaire, page 1 - X in a column
    f.doc("UNDERWRITING QUESTIONNAIRE - SIGNED BY APPLICANT (page 1 of 2)")
    f.xcolumn([(q["n"], q["q"], q["answer"]) for q in Q.values() if not q["scanned"]])
    f.head("1a. PARENT COMPANY")
    f.table(["PARENT COMPANY NAME", "RELATIONSHIP DESCRIPTION", "% OWNED"],
            [[D.PARENT_ORG, D.PARENT_RELATIONSHIP, D.PARENT_PCT]], [LEFT, LEFT + 220, LEFT + 420])
    f.head("1b. SUBSIDIARY")
    f.table(["SUBSIDIARY COMPANY NAME", "RELATIONSHIP DESCRIPTION", "% OWNED"],
            [[D.SUB_ORG, D.SUB_RELATIONSHIP, D.SUB_PCT]], [LEFT, LEFT + 220, LEFT + 420])
    f.head("2. SAFETY PROGRAMME ELEMENTS")
    f.xcolumn([("", "Safety manual", "Y"), ("", "Safety position", "Y"),
               ("", "Monthly meetings", "Y"), ("", "Meets OSHA guidelines", "Y"),
               ("", f"Other: {D.SAFETY_OTHER}", "Y")])
    f.head("3. FLAMMABLES, EXPLOSIVES, CHEMICALS - EXPLAIN")
    f.para(Q["ABC"]["stated"], indent=6)
    f.head("4. OTHER INSURANCE WITH THIS COMPANY - POLICY NUMBERS")
    f.table(["LINE OF BUSINESS", "POLICY NUMBER"], [list(p) for p in D.OTHER_POLICIES],
            [LEFT, LEFT + 220])
    f.head("5. DECLINED / CANCELLED / NON-RENEWED - REASON")
    f.xcolumn([("", "Non-payment", "N"), ("", "Agent no longer represents carrier", "Y"),
               ("", "Non-renewal (reason box)", "N"), ("", "Underwriting", "Y"),
               ("", "Condition corrected", "Y")])
    for e in D.NONRENEWALS:
        f.para(f"{e['year']}: {e['detail']}", indent=6)
    f.para(f"Condition corrected: {D.CONDITION_CORRECTED}", indent=6)
    f.head("6. EXPLAIN")
    f.para(Q["AAD"]["stated"], indent=6)
    f.head("7.")
    f.para(Q["KAB"]["stated"], indent=6)
    f.text("Questions 8 through 15 continue on page 2 (signed original, scanned).")

    # 12. Questionnaire, page 2 - SCANNED, full page
    scan = [f"UNDERWRITING QUESTIONNAIRE (page 2 of 2)      Applicant: {D.NAME}", ""]
    for code in ("AAF", "KAK", "KAL", "ABB", "KAC", "KAM", "KAN", "KAO"):
        q = Q[code]
        scan.append(f"{q['n']}. {q['q']}")
        scan += [f"    ANSWER: {q['answer']}  -  " + s for s in _wrap(q["stated"], 80)[:1]]
        scan += ["      " + s for s in _wrap(q["stated"], 80)[1:]]
        if code == "AAF":
            scan += [f"    OCCUR DATE: {D.FIRE_CODE['occur']}"]
            scan += ["    EXPLANATION: " + s for s in _wrap(D.FIRE_CODE["explain"], 76)[:1]]
            scan += ["      " + s for s in _wrap(D.FIRE_CODE["explain"], 76)[1:]]
            scan += [f"    RESOLUTION: none yet - {D.FIRE_CODE['pending']}"]
        if code in ("KAK", "KAL"):
            r = D.REPOSSESSION if code == "KAK" else D.LIEN
            scan += [f"    OCCUR DATE: {r['occur']}"]
            scan += ["    EXPLANATION: " + s for s in _wrap(r["explain"], 76)[:1]]
            scan += ["      " + s for s in _wrap(r["explain"], 76)[1:]]
            scan += [f"    RESOLUTION: {r['resolution']}", f"    RESOLVED: {r['resolved']}"]
        if code == "ABB":
            scan += [f"    NAME OF TRUST: {D.TRUST_NAME}"]
        scan.append("")
    scan += ["I certify the above answers are true and complete.",
             "Signed: ______________________   Title: Managing Member   Date: 08/14/2026"]
    f.special(scanned_page(scan, skew=0.9,
                           fax="FAX 303 555 0175 -> SUMMIT COMMERCIAL  08/14/2026 16:42  P.2/2"))

    # 13. Supporting documents for every YES
    f.doc("SUPPORTING DOCUMENTS - GENERAL INFORMATION ANSWERS")
    f.head("Q5 - NON-RENEWAL NOTICES")
    for e in D.NONRENEWALS:
        f.kv([("Carrier", e["carrier"]), ("Line(s)", e["line"]),
              ("Effective", f"10/01/{e['year']}"), ("Reason (ACORD)", e["reason"])])
        f.para(e["detail"], indent=6)
    f.head("Q5 - FLEET SAFETY PROGRAM ADOPTED")
    f.para(f"Memo, 01/15/2025: {D.CONDITION_CORRECTED} Every driver's MVR is reviewed "
           "annually; new drivers complete defensive-driving training before assignment.")
    f.head("Q6 - EEOC CHARGE")
    f.para("Charge 541-2023-01187, filed 03/06/2023 by a former apprentice alleging "
           "discrimination. Dismissal and notice of rights issued 11/14/2023; no lawsuit filed.")
    f.head("Q8 - FIRE INSPECTION REPORT, COLORADO SPRINGS FIRE DEPARTMENT")
    f.kv([("Inspection date", D.FIRE_CODE["occur"]),
          ("Premises", "Location 3, 4750 Centennial Blvd"),
          ("Finding", "Two portable extinguishers - inspection tags expired"),
          ("Status", "OPEN - " + D.FIRE_CODE["pending"]), ("Re-inspection", "not yet performed")])
    f.head("Q9 - REPOSSESSION AND SETTLEMENT")
    f.para(f"{D.REPOSSESSION['explain']} Repossessed {D.REPOSSESSION['occur']}. "
           f"{D.REPOSSESSION['resolution']} Settlement letter dated {D.REPOSSESSION['resolved']}.")
    f.head("Q10 - LIEN AND RELEASE")
    f.para(f"{D.LIEN['explain']} Recorded {D.LIEN['occur']}. {D.LIEN['resolution']} "
           f"Release recorded {D.LIEN['resolved']}, reception no. 2024018842.")
    f.head("Q12 - FOREIGN PRODUCTS: SUPPLIER INVOICES")
    rnd = random.Random(12)
    f.table(["INVOICE", "DATE", "SUPPLIER", "COUNTRY", "ITEMS", "USD"],
            [[f"NL-{7700 + i}", f"{(i % 12) + 1:02d}/{(i * 5) % 27 + 1:02d}/2026",
              "Northern Lumen Ltd", "Canada (ON)",
              rnd.choice(["LED troffers", "Control panels", "High-bay fixtures", "Drivers"]),
              f"${rnd.randint(2, 60) * 1000 + rnd.randint(0, 999):,}"] for i in range(14)],
            [LEFT, LEFT + 60, LEFT + 130, LEFT + 250, LEFT + 330, LEFT + 440])
    f.head("Q13 - OTHER BUSINESS VENTURE")
    f.para("Summit Solar Services LLC (residential rooftop solar) is owned by Luis Ortega "
           "personally. It has its own employees and its own insurance programme.")
    f.head("Q14 - DRONE REGISTRATION")
    f.kv([("Aircraft", "DJI Mavic 3 Enterprise"), ("FAA registration", "FA3XK9P2QT"),
          ("Remote pilot", "Owen Price - Part 107 certificate 4410982"),
          ("Use", "roof and site inspections")])
    f.head("Q15 - DRONE SERVICES AGREEMENT")
    f.para("Master services agreement with Aerial Vantage LLC, dated 03/01/2026: the vendor "
           "flies progress-photography missions on request, carries its own aviation liability "
           "and names the applicant as additional insured.")

    # 14. Operating agreement Schedule A - SCANNED (the member count lives only here)
    oa = ["OPERATING AGREEMENT OF", D.NAME.upper(), "SCHEDULE A - MEMBERS", "",
          "MEMBER                          CAPACITY           PERCENTAGE INTEREST"]
    oa += [f"{n:<32}{r:<19}{p}" for n, r, p in D.MEMBER_LIST]
    oa += ["", f"Number of members and managers: {D.MEMBERS}", "Management: member-managed", "",
           "Date of formation: 06/15/2014.  Amended January 3, 2022.", "",
           "ARTICLE IV - CAPITAL CONTRIBUTIONS",
           "4.1 Each member has contributed the capital shown in the company records.",
           "4.2 No member shall be required to make an additional capital contribution.",
           "4.3 No interest shall accrue on any capital contribution.", "",
           "ARTICLE V - ALLOCATIONS AND DISTRIBUTIONS",
           "5.1 Profits and losses are allocated in proportion to percentage interests.",
           "5.2 Distributions are made at the times determined by the managing member.",
           "5.3 No distribution shall be made that renders the company insolvent.", "",
           "ARTICLE VI - MANAGEMENT",
           "6.1 The company is managed by its members acting through the managing member.",
           "6.2 The managing member may bind the company in the ordinary course.",
           "6.3 Major decisions require the consent of members holding 75%.", "",
           "ARTICLE VII - TRANSFERS",
           "7.1 No member may transfer an interest without the consent of the others.",
           "7.2 Transfers to a revocable trust for estate planning are permitted.", "",
           "ARTICLE VIII - DISSOLUTION",
           "8.1 The company dissolves only on the written consent of all members.",
           "8.2 On dissolution the assets are applied first to creditors.", "",
           "Signed: Luis Ortega    Maria Ortega    for Front Range Holdings Inc"]
    f.special(scanned_page(oa, skew=-0.6))

    # 15. Trust certificate + W-9 - SCANNED
    tw = ["CERTIFICATE OF TRUST", "", f"Name of trust: {D.TRUST_NAME}",
          "Date of trust: March 2, 2021      Trustee: Luis Ortega",
          "Trust property includes the managing member's 55% interest in",
          f"{D.NAME}.", "The trust is revocable. The trustee may hold LLC interests.", "",
          "-" * 70, "Form W-9 (Rev. March 2024)",
          "Request for Taxpayer Identification Number and Certification", "",
          f"1 Name: {D.NAME}", "3 Federal tax classification: LLC (partnership)",
          f"5 Address: {D.MAIL_L1}, {D.MAIL_L2}",
          f"6 City, state, ZIP: {D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}", "",
          f"Employer identification number: {D.FEIN}", "",
          "Part II Certification - Under penalties of perjury, I certify that:",
          "1. The number shown on this form is my correct taxpayer identification number;",
          "2. I am not subject to backup withholding;", "3. I am a U.S. person; and",
          "4. The FATCA code(s) entered on this form (if any) are correct.", "",
          "Sign here: ______________________   Date: 01/09/2026", "",
          "General instructions - section references are to the Internal Revenue Code.",
          "Purpose of form: an entity required to file an information return with the",
          "IRS must obtain your correct TIN to report payments made to you.",
          "Backup withholding: persons making certain payments must withhold and pay",
          "to the IRS 24% of such payments under certain conditions.",
          "Updating your information: provide updated information to any person to",
          "whom you claimed to be an exempt payee if you are no longer one.",
          "Penalties: failure to furnish a TIN - penalty of $50 for each failure.",
          "Misuse of TINs: a requester who discloses TINs in violation of law may be",
          "subject to civil and criminal penalties.", "",
          "Privacy Act notice: section 6109 requires you to provide your correct TIN."]
    f.special(scanned_page(tw, skew=0.5))

    # 16. The receiving carrier's existing policies (question 4)
    f.doc(f"{D.CARRIER.upper()} - POLICIES IN FORCE FOR THE APPLICANT")
    f.table(["LINE", "POLICY", "TERM", "PREMIUM"],
            [["Workers Compensation", "WC-GA-448120", f"{D.CUR_EFF} - {D.CUR_EXP}", "$21,960"],
             ["Commercial Inland Marine", "IM-GA-220915", f"{D.CUR_EFF} - {D.CUR_EXP}", "$2,340"]],
            [LEFT, LEFT + 170, LEFT + 260, LEFT + 400])
    f.para("These policies are not part of the lines requested; they are listed because the "
           "application asks for other insurance with this company. Contractors equipment and "
           "installation floater exposures are written on IM-GA-220915.")

    # 17. Current declarations (the incumbent)
    f.doc("COMMERCIAL GENERAL LIABILITY DECLARATIONS - CURRENT POLICY (INCUMBENT)")
    f.teletype(["POLICY NO  GL-123456", f"PERIOD  {D.CUR_EFF}  TO  {D.CUR_EXP}",
                "RENEWAL OF  GL-104471"])
    f.kv([("Named insured", D.NAME), ("Company", f"{D.CUR_CARRIER}  NAIC {D.CUR_CARRIER_NAIC}"),
          ("Agent", D.PRODUCER), ("Billing", D.CUR_BILLING),
          ("Each occurrence / aggregate", "$1,000,000 / $2,000,000"),
          ("Products-completed operations aggregate", "$2,000,000"),
          ("Personal and advertising injury", "$1,000,000"),
          ("Damage to premises rented / medical", "$300,000 / $10,000"),
          ("Total advance premium", "$18,450")])
    f.table(["LOC", "CLASS", "DESCRIPTION", "BASIS", "EXPOSURE", "PREMIUM"],
            [[l["num"], D.GL_CODE, "Electrical Work - Within Buildings", "Payroll",
              f"${340_000 * (4 - i):,}", f"${4_200 * (4 - i):,}"] for i, l in enumerate(L[:3])]
            + [["4", "68500", "Warehouses - private", "Area", "3,000", "$65"]],
            [LEFT, LEFT + 30, LEFT + 80, LEFT + 260, LEFT + 320, LEFT + 400])
    forms = [("CG 00 01 04 13", "Commercial General Liability Coverage Form"),
             ("CG 20 11 04 13", "Additional Insured - Managers or Lessors of Premises"),
             ("CG 21 47 12 07", "Employment-Related Practices Exclusion"),
             ("CG 22 79 04 13", "Exclusion - Contractors - Professional Liability"),
             ("CG 24 04 05 09", "Waiver of Transfer of Rights of Recovery"),
             ("IL 00 17 11 98", "Common Policy Conditions"),
             ("IL 00 21 09 08", "Nuclear Energy Liability Exclusion"),
             ("CG 21 67 12 04", "Fungi or Bacteria Exclusion")]
    f.table(["FORM", "TITLE"], [list(x) for x in forms], [LEFT, LEFT + 110])
    f.text("CG 20 11: no additional insured is scheduled. The landlord endorsement is not activated.")
    vehicles = [("2022", "Ford", "Transit 250", "1FTBR1C8XNKA12345"),
                ("2021", "Ford", "Transit 350", "1FTBW3XM4MKA22317"),
                ("2023", "RAM", "ProMaster 2500", "3C6LRVDG5PE501122"),
                ("2020", "Chevrolet", "Express 2500", "1GCWGAFP8L1203344"),
                ("2019", "Ford", "F-250", "1FT7W2B67KEE55667"),
                ("2024", "Ford", "F-350", "1FT8W3BT2REC77889"),
                ("2022", "Isuzu", "NPR-HD", "54DC4W1B7NS800112"),
                ("2021", "Chevrolet", "Silverado 2500", "1GC4YLE7XMF301234"),
                ("2023", "Ford", "E-Transit", "1FTBW9CK3PKA40567"),
                ("2020", "RAM", "2500 Tradesman", "3C6UR5CJ4LG198765")]
    f.doc("BUSINESS AUTO DECLARATIONS AND SCHEDULE - CURRENT POLICY (INCUMBENT)")
    f.kv([("Policy", f"BA-456789   {D.CUR_EFF} - {D.CUR_EXP}"), ("Company", D.CUR_CARRIER),
          ("Liability", "Symbol 1 - CSL $1,000,000"), ("Physical damage", "Symbol 7"),
          ("Premium", "$14,200")])
    f.table(["#", "YEAR", "MAKE", "MODEL", "VIN", "GARAGE", "COST NEW", "LIENHOLDER"],
            [[str(i + 1), a, b, m, v, "LOC 2", f"${38 + i * 4},900", "None"]
             for i, (a, b, m, v) in enumerate(vehicles)],
            [LEFT, LEFT + 18, LEFT + 50, LEFT + 110, LEFT + 190, LEFT + 300, LEFT + 342, LEFT + 402])
    f.table(["DRIVER", "LICENCE", "STATE", "DOB (yr)", "MVR PTS", "HIRED"],
            [[f"{_LAST[i]}, {_FIRST[i][0]}", f"CO-{900000 + i * 1371}", "CO",
              f"{1966 + (i * 3) % 36}", str((i * 7) % 4), f"{2014 + i % 10}"] for i in range(18)],
            [LEFT, LEFT + 110, LEFT + 200, LEFT + 240, LEFT + 300, LEFT + 350])
    f.doc("COMMERCIAL PROPERTY DECLARATIONS - CURRENT POLICY (INCUMBENT)")
    f.kv([("Policy", f"CP-567890   {D.CUR_EFF} to {D.CUR_EXP}   {D.CUR_CARRIER}"),
          ("Premium", "$8,750"), ("Form", "Special form, replacement cost, 80% coinsurance")])
    f.table(["LOC", "BLD", "BUILDING", "BPP", "DEDUCTIBLE", "MORTGAGEHOLDER"],
            [["1", "1", "Tenant - none", "$385,000", "$2,500", "--"],
             ["2", "1", "$1,480,000", "$210,000", "$5,000", M["name"]],
             ["3", "1", "Tenant - none", "$62,000", "$2,500", "--"],
             ["4", "1", "$420,000", "$95,000", "$5,000", "none"]],
            [LEFT, LEFT + 30, LEFT + 60, LEFT + 160, LEFT + 240, LEFT + 310])
    f.para("Coverage extensions attached to this property policy: contractors equipment "
           "$240,000, installation floater $50,000, employee dishonesty $10,000 - EXTENSIONS of "
           "the property form, not separate lines.")
    f.doc("COMMERCIAL UMBRELLA DECLARATIONS - CURRENT POLICY (INCUMBENT)")
    f.kv([("Policy", f"CU-678901   {D.CUR_EFF} - {D.CUR_EXP}   {D.CUR_CARRIER}"),
          ("Limits", "$2,000,000 each occurrence / aggregate   SIR $10,000"),
          ("Premium", "$4,100"),
          ("Total current package premium (4 lines)", D.CUR_TOTAL_PREMIUM)])
    f.table(["UNDERLYING", "CARRIER", "POLICY", "LIMITS"],
            [["General Liability", D.CUR_CARRIER_SHORT, "GL-123456", "$1M / $2M"],
             ["Business Auto", D.CUR_CARRIER_SHORT, "BA-456789", "$1M CSL"],
             ["Employers Liability", "Granite Arch", "WC-GA-448120", "$1M / $1M / $1M"]],
            [LEFT, LEFT + 140, LEFT + 260, LEFT + 360])

    # 18. Prior terms - years two and three of the grid
    f.doc("PRIOR-TERM DECLARATIONS SUMMARIES (INCUMBENT AND PRIOR CARRIERS)")
    for term in D.PRIOR_TERMS:
        f.head(f"POLICY YEAR {term['year']}   TERM {term['eff']} - {term['exp']}")
        f.table(["LINE", "CARRIER", "POLICY NUMBER", "PREMIUM", "EFFECTIVE", "EXPIRATION"],
                [[D.GRID_LINE_NAMES[g], v[0], v[1], v[2], term["eff"], term["exp"]]
                 for g, v in term["lines"].items()],
                [LEFT, LEFT + 110, LEFT + 290, LEFT + 370, LEFT + 420, LEFT + 480])
    f.para("Terms before 10/01/2023 were written by Alpine States Insurance Company; their "
           "policy numbers and premiums are not available and are not part of this summary.")

    # 19. Loss runs + the stale FAXED copy
    f.doc(f"LOSS RUNS - ALL LINES - VALUED {D.LOSS_VALUED}",
          "Five policy years 10/01/2021 - 10/01/2026. Supersedes all earlier valuations.")
    f.table(["CLAIM", "DOL", "REPORTED", "LINE", "DESCRIPTION", "PAID", "RESERVE", "SUB", "STATUS"],
            [[x["claim_no"], x["occurrence"], x["claim"], x["line"], x["desc"], x["paid"],
              x["reserved"], x["subro"], "OPEN" if x["open"] == "Y" else "CLOSED"] for x in D.LOSSES],
            [LEFT, LEFT + 58, LEFT + 106, LEFT + 154, LEFT + 244, LEFT + 380, LEFT + 420,
             LEFT + 458, LEFT + 478], style="riffled")
    f.text(f"TOTAL PAID {D.TOTAL_PAID}     TOTAL RESERVED $3,000     TOTAL INCURRED {D.TOTAL_INCURRED}")
    for line in ("General Liability", "Business Auto", "Commercial Property", "Commercial Umbrella"):
        f.head(f"{line.upper()} - CLAIMS BY POLICY YEAR")
        f.table(["TERM", "CLAIMS", "NOTE"],
                [[f"10/01/{yr} - 10/01/{yr + 1}",
                  str(sum(1 for x in D.LOSSES if x["line"] == line
                          and _in_term(x["occurrence"], yr))), "see claim detail above"]
                 for yr in range(2021, 2026)],
                [LEFT, LEFT + 160, LEFT + 220])
    f.special(scanned_page(
        [f"{D.CUR_CARRIER.upper()} - LOSS RUN - BUSINESS AUTO", f"VALUED AS OF {D.LOSS_OLD['valued']}",
         "", "CLAIM        DOL        DESCRIPTION                       PAID     RESERVE  STATUS",
         f"{D.LOSS['claim_no']}  {D.LOSS['occurrence']} Insd veh rear-ended 3rd party   "
         f"{D.LOSS_OLD['paid']}   {D.LOSS_OLD['reserved']}   OPEN", "",
         "THIS LOSS RUN IS VALUED AS SHOWN ABOVE.", ""]
        + [f"{yr}-{yr + 1}   POLICY BA-{400000 + yr}   CLAIMS 0   PAID $0   RESERVE $0"
           for yr in range(2019, 2024)] + [""]
        + [f"LINE {i:02d}  NOTE: valuation subject to change; reserves are estimates only."
           for i in range(1, 33)],
        skew=1.4, quality="fax",
        fax="FAX 800 555 0147  TIMBERLINE MUTUAL CLAIMS  07/02/2024 09:11  P.1/1"))

    # 20. Leases, mortgage, equipment finance
    f.doc("LEASE ABSTRACTS - LOCATIONS 1 AND 3")
    f.kv([("Location 1 landlord", D.LANDLORD), ("Landlord address", D.LANDLORD_ADDR),
          ("Landlord phone", D.LANDLORD_PHONE), ("Term", "06/01/2019 - 05/31/2029"),
          ("Location 3 landlord", "Centennial Office Partners LLC"),
          ("Term", "01/01/2024 - 12/31/2028")])
    f.para("Both leases require the tenant to carry liability insurance. Neither requires the "
           "landlord to be named as an additional insured, loss payee or any other interest, "
           "and none has been scheduled on any policy.")
    f.doc("LOAN SUMMARY - FIRST MORTGAGE ON LOCATION 2")
    f.kv([("Lender (mortgagee)", M["name"]), ("Lien position (rank)", M["rank"]),
          ("Lender address", f"{M['l1']}, {M['l2']}, {M['city']}, {M['state']} {M['zip']}"),
          ("Country", M["country"]), ("Loan number", M["loan_no"]),
          ("Original loan amount", M["amount"]), ("Maturity - interest ends", M["end"]),
          ("Servicing phone", M["phone"]), ("Servicing fax", M["fax"]),
          ("Servicing e-mail", M["email"]),
          ("Collateral", f"Location {M['loc']}, Building {M['bldg']} - {M['item']}"),
          ("Reason for interest", M["reason"]),
          ("Evidence required", "Certificate of insurance (policy copy not required; do not send bills)"),
          ("Aircraft / airport", "N/A"), ("Boat", "N/A"), ("Vehicle", "N/A"),
          ("Scheduled item class", "N/A")], leader=True)
    f.doc("EQUIPMENT FINANCE AGREEMENT - AERIAL LIFTS")
    f.para(f"Lessor and loss payee: {D.LOSS_PAYEE_B}, 4100 E Mississippi Ave, Glendale, CO "
           "80246. Collateral: two 19 ft scissor lifts (serials SL-4471, SL-4472) and one "
           "34 ft articulating boom (serial AB-3310). The lessee must name the lessor as loss "
           "payee on its property coverage.")

    # 21. Safety programme, hazmat
    f.doc("SAFETY PROGRAMME")
    f.para("FORMAL SAFETY PROGRAMME: IN OPERATION. The programme meets OSHA 29 CFR 1926 "
           "construction standards and is reviewed each January by the safety manager.")
    for i, ln in enumerate([
            "Written safety manual (revised January 2025), issued to every employee.",
            f"Designated safety manager: {D.SAFETY_MANAGER}, Safety Manager (full time).",
            "Monthly safety meetings with recorded attendance; toolbox talks on site.",
            f"{D.SAFETY_OTHER}.",
            "Lockout / tagout, arc-flash (NFPA 70E) and fall-protection procedures.",
            "Incident reporting within 24 hours; root-cause review within 7 days."], 1):
        f.text(f"  {i}. {ln}")
    f.head("SAFETY MEETING MINUTES - 2025/2026")
    topics = ["Ladder safety", "Arc flash PPE", "Trench awareness", "Heat illness",
              "Driver fatigue", "Lockout / tagout", "Aerial lifts", "Hand tools",
              "Silica", "Cold stress", "Housekeeping", "First aid"]
    f.table(["DATE", "TOPIC", "LED BY", "ATTENDED", "ACTIONS"],
            [[f"{(i % 12) + 1:02d}/0{1 + i % 8}/{2025 + i // 12}", topics[i % 12],
              D.SAFETY_MANAGER, str(14 + i % 6),
              ["none", "replace 2 harnesses", "retrain 1 crew", "order cooling vests"][i % 4]]
             for i in range(20)],
            [LEFT, LEFT + 70, LEFT + 190, LEFT + 290, LEFT + 350])
    f.head("OSHA 300 LOG - 2025 (RECORD-KEEPING)")
    f.table(["CASE", "DATE", "JOB", "INJURY", "DAYS AWAY", "RESTRICTED"],
            [["25-01", "02/11/2025", "Journeyman", "Hand laceration", "0", "3"],
             ["25-02", "06/23/2025", "Apprentice", "Ankle sprain", "4", "6"],
             ["25-03", "09/02/2025", "Journeyman", "Eye irritation", "0", "0"]],
            [LEFT, LEFT + 50, LEFT + 120, LEFT + 200, LEFT + 320, LEFT + 390])
    f.doc("HAZARDOUS MATERIALS INVENTORY")
    f.table(["MATERIAL", "MAX QTY", "STORAGE", "LOCATION", "SDS ON FILE"],
            [["PVC solvent cement", "4 qt", "Approved flammables cabinet", "LOC 1", "Y"],
             ["Construction adhesive", "12 tubes", "Approved cabinet", "LOC 1", "Y"],
             ["Pipe-thread sealant", "2 qt", "Approved cabinet", "LOC 1", "Y"],
             ["Contact cleaner (aerosol)", "6 cans", "Approved cabinet", "Vans", "Y"],
             ["Wire-pulling lubricant", "5 gal", "Shelf", "LOC 2", "Y"],
             ["Two-stroke fuel mix", "2 gal", "Safety can", "LOC 2", "Y"]],
            [LEFT, LEFT + 150, LEFT + 220, LEFT + 380, LEFT + 440])
    f.para(Q["ABC"]["stated"] + " No explosives. No bulk chemical storage.")

    # 22. Schedules a contractor's package carries
    f.doc("CERTIFICATES OF INSURANCE ISSUED - LOG")
    f.table(["CERT", "HOLDER", "ADDRESS", "CITY", "ZIP", "ISSUED", "TYPE"],
            [[f"C-{2400 + i}", n, a, ci, z, f"{(i % 12) + 1:02d}/{(i * 3) % 27 + 1:02d}/2026", "CERT"]
             for i, (n, a, ci, z) in enumerate(D.CERT_HOLDERS)],
            [LEFT, LEFT + 40, LEFT + 200, LEFT + 330, LEFT + 410, LEFT + 446, LEFT + 500])
    f.para("Certificates are evidence of insurance only. No holder is an additional insured, "
           "loss payee, mortgagee or any other interest on any policy of the named insured.")
    f.doc("RECENT PROJECTS - CUSTOMER JOB SITES (work performed AT customer locations)")
    f.table(["#", "SITE ADDRESS", "CITY", "ZIP", "SCOPE"],
            [[str(i + 1), a, ci, z, s] for i, (a, ci, z, s) in enumerate(D.JOB_SITES)],
            [LEFT, LEFT + 24, LEFT + 150, LEFT + 260, LEFT + 300], style="riffled")
    f.doc("WORK IN PROGRESS SCHEDULE AS OF 08/31/2026")
    f.table([["JOB", "PROJECT", "CONTRACT", "BILLED TO", "PCT"],
             ["NO.", "", "VALUE", "DATE", "COMPLETE"]],
            [list(r) for r in D.WIP],
            [LEFT, LEFT + 60, LEFT + 260, LEFT + 350, LEFT + 440], style="plain")
    f.text(f"TOTAL CONTRACT VALUE (BACKLOG)  {D.WIP_BACKLOG} - contract value is not revenue.")
    return f


def _in_term(date: str, yr: int) -> bool:
    m, _d, y = (int(x) for x in date.split("/"))
    return (y == yr and m >= 10) or (y == yr + 1 and m < 10)


def bulk_sections(f: Flow, pages_left: Callable[[], int]):
    """Ledgers and logs, added until the package reaches 100 pages. Every row is
    deterministic and none states a fact the key expects."""
    rnd = random.Random(2026)
    vendors = ["Mile High Supply", "Graybar", "Border States", "CED Denver", "Home Depot Pro",
               "Crescent Electric", "Wesco", "United Rentals", "Sunbelt Rentals", "Fastenal"]
    items = ["THHN 12 AWG 500 ft", "EMT 3/4 in x 10 ft", "200A panel", "LED troffer 2x4",
             "Breaker 20A", "MC cable 250 ft", "Junction boxes (50)", "Wire nuts (500)",
             "Scissor lift rental", "Trencher rental", "Conduit fittings", "Grounding rods"]

    def rows(n, make):
        return [make() for _ in range(n)]

    def ledger():
        f.doc("JOB COST LEDGER - FY2026 YEAR TO DATE")
        f.table(["DATE", "JOB", "CODE", "VENDOR", "ITEM", "QTY", "AMOUNT"],
                rows(860, lambda: [f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/2026",
                                   D.WIP[rnd.randrange(30)][0],
                                   f"{rnd.randint(1, 16):02d}-{rnd.randint(100, 999)}",
                                   rnd.choice(vendors), rnd.choice(items), str(rnd.randint(1, 60)),
                                   f"${rnd.randint(40, 18_000):,}.{rnd.randint(0, 99):02d}"]),
                [LEFT, LEFT + 60, LEFT + 110, LEFT + 160, LEFT + 270, LEFT + 400, LEFT + 430])

    def fuel():
        f.doc("FLEET FUEL AND MILEAGE LOG - 2026")
        f.table(["DATE", "UNIT", "DRIVER", "GALLONS", "ODOMETER", "STATION", "COST"],
                rows(560, lambda: [f"{rnd.randint(1, 8):02d}/{rnd.randint(1, 28):02d}/2026",
                                   f"V-{rnd.randint(1, 10)}",
                                   rnd.choice(["Baca", "Chen", "Diaz", "Evans", "Lopez", "Moore"]),
                                   f"{rnd.randint(8, 34)}.{rnd.randint(0, 9)}",
                                   f"{rnd.randint(20_000, 140_000):,}",
                                   rnd.choice(["Conoco 6th Ave", "Shell Federal", "King Soopers Fuel"]),
                                   f"${rnd.randint(30, 140)}.{rnd.randint(0, 99):02d}"]),
                [LEFT, LEFT + 60, LEFT + 100, LEFT + 170, LEFT + 230, LEFT + 300, LEFT + 430])

    def payroll():
        f.doc("PAYROLL REGISTER BY EMPLOYEE - 2026 (BI-WEEKLY)")
        f.table(["PERIOD END", "EMP", "CLASS", "REG HRS", "OT HRS", "GROSS", "NET"],
                rows(620, lambda: [f"{rnd.randint(1, 8):02d}/{rnd.randint(1, 28):02d}/2026",
                                   f"E-{100 + rnd.randint(0, 19)}",
                                   rnd.choice(["Field", "Apprentice", "Office"]),
                                   str(rnd.randint(60, 80)), str(rnd.randint(0, 14)),
                                   f"${rnd.randint(1_400, 5_200):,}.{rnd.randint(0, 99):02d}",
                                   f"${rnd.randint(1_000, 3_900):,}.{rnd.randint(0, 99):02d}"]),
                [LEFT, LEFT + 70, LEFT + 110, LEFT + 180, LEFT + 230, LEFT + 290, LEFT + 380])

    def maint():
        f.doc("FLEET AND LIFT MAINTENANCE LOG")
        f.table(["DATE", "UNIT", "SERVICE", "ODOM / HRS", "SHOP", "COST"],
                rows(420, lambda: [f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/{rnd.choice([2025, 2026])}",
                                   rnd.choice([f"V-{rnd.randint(1, 10)}", f"SL-{rnd.randint(4471, 4472)}", "AB-3310"]),
                                   rnd.choice(["Oil change", "Brakes", "Tyres", "Annual inspection",
                                               "Battery", "Hydraulic service", "Load test"]),
                                   f"{rnd.randint(1_000, 140_000):,}",
                                   rnd.choice(["In-house LOC 2", "Fleet Pro", "Sunbelt service"]),
                                   f"${rnd.randint(60, 2_400):,}"]),
                [LEFT, LEFT + 70, LEFT + 120, LEFT + 230, LEFT + 300, LEFT + 420])

    def training():
        f.doc("SAFETY TRAINING LOG")
        f.table(["EMP", "COURSE", "DATE", "TRAINER", "HOURS", "EXPIRES"],
                rows(420, lambda: [f"E-{100 + rnd.randint(0, 19)}",
                                   rnd.choice(["OSHA 30 Construction", "NFPA 70E Arc Flash",
                                               "Fall Protection", "Lockout / Tagout",
                                               "First Aid / CPR", "Aerial Lift Operator",
                                               "Confined Space", "Defensive Driving"]),
                                   f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/{rnd.choice([2025, 2026])}",
                                   rnd.choice([D.SAFETY_MANAGER, "Mile High Safety Training", "Red Cross"]),
                                   str(rnd.choice([2, 4, 8, 10, 30])), str(rnd.choice([2027, 2028, 2029]))]),
                [LEFT, LEFT + 50, LEFT + 200, LEFT + 270, LEFT + 400, LEFT + 450])

    def aging():
        f.doc("ACCOUNTS RECEIVABLE AND PAYABLE AGING AS OF 08/31/2026")
        names = [h[0] for h in D.CERT_HOLDERS] + vendors
        f.table(["PARTY", "TYPE", "CURRENT", "31-60", "61-90", "90+"],
                [[n, "AR" if i < len(D.CERT_HOLDERS) else "AP",
                  f"${rnd.randint(1_000, 90_000):,}", f"${rnd.randint(0, 20_000):,}",
                  f"${rnd.randint(0, 8_000):,}", f"${rnd.choice([0, 0, rnd.randint(0, 4_000)]):,}"]
                 for i, n in enumerate(names)],
                [LEFT, LEFT + 200, LEFT + 240, LEFT + 310, LEFT + 380, LEFT + 450])

    def bids():
        f.doc("BID LOG - 2026")
        f.table(["BID", "OWNER / GC", "BID AMOUNT", "DUE", "RESULT"],
                [[f"B-{610 + i}", D.CERT_HOLDERS[i % len(D.CERT_HOLDERS)][0],
                  f"${rnd.randint(60_000, 960_000):,}", f"{rnd.randint(1, 12):02d}/15/2026",
                  rnd.choice(["WON", "LOST", "PENDING"])] for i in range(160)],
                [LEFT, LEFT + 50, LEFT + 260, LEFT + 350, LEFT + 420])

    def purchases():
        f.doc("MATERIAL PURCHASE ORDERS - 2026")
        f.table(["PO", "DATE", "VENDOR", "ITEM", "QTY", "UNIT", "TOTAL"],
                [[f"PO-{9000 + i}", f"{rnd.randint(1, 8):02d}/{rnd.randint(1, 28):02d}/2026",
                  rnd.choice(vendors), rnd.choice(items), str(rnd.randint(1, 80)),
                  f"${rnd.randint(2, 900)}.{rnd.randint(0, 99):02d}",
                  f"${rnd.randint(50, 40_000):,}"] for i in range(700)],
                [LEFT, LEFT + 50, LEFT + 110, LEFT + 220, LEFT + 350, LEFT + 380, LEFT + 440])

    def email():
        f.doc("E-MAIL CORRESPONDENCE - SUBMISSION FILE")
        thread = [
            ("08/12/2026", "Michelle Smith", "Luis Ortega",
             "Please confirm the four premises and which ones you own. Also the members of the LLC."),
            ("08/12/2026", "Luis Ortega", "Michelle Smith",
             "Locations 2 and 4 are ours; 1 and 3 are leased. Members are on Schedule A. The old "
             "Timberline paperwork still shows the old audit and quarterly agency billing."),
            ("08/13/2026", "Michelle Smith", "Sarah Jones",
             "Can you send current loss runs? The 2024 fax shows the auto claim still open."),
            ("08/14/2026", "Sarah Jones", "Michelle Smith",
             "Attached, valued 08/31/2026 - the auto claim closed at $4,850. Ignore the old fax."),
            ("08/18/2026", "Michelle Smith", D.UNDERWRITER,
             f"Submission attached for the {D.PROGRAM_NAME}. Direct bill, monthly EFT please."),
            ("08/20/2026", D.UNDERWRITER, "Michelle Smith",
             "Received. We will need the extinguisher service confirmation at Location 3."),
        ]
        for dt, fr, to, body in thread * 5:
            f.text(f"Date: {dt}   From: {fr}   To: {to}")
            f.para(body, indent=12)

    for fn in (email, ledger, payroll, fuel, maint, training, aging, bids, purchases):
        if pages_left() <= 0:
            return
        fn()


def assemble_pages() -> List[tuple]:
    f = build_flow()
    bulk_sections(f, lambda: TARGET_PAGES - f.page_count())
    f.fill_page(wording_bank(9))
    f._new_page()
    f.pages.extend(f.pending)
    f.pending = []
    while len(f.pages) > TARGET_PAGES:
        for i in range(len(f.pages) - 1, -1, -1):
            if f.pages[i][0] != "special":
                del f.pages[i]
                break
    n = 0
    while len(f.pages) < TARGET_PAGES:
        n += 1
        form = ["CG 00 01 04 13", "IL 00 17 11 98", "CA 00 01 10 13", "CP 00 10 10 12",
                "CU 00 01 12 07"][n % 5]
        f.pages.append(("flow", f"POLICY WORDING - {form}",
                        [Line([(LEFT, ln, MONO, FS, "plain")])
                         for ln in wording_bank(100 + n)[:LINES_PER_PAGE]]))
    return f.pages


def render(pages) -> int:
    OUT_DIR.mkdir(exist_ok=True)
    c = canvas.Canvas(str(PDF_PATH), pagesize=LETTER)
    c.setTitle(f"{D.NAME} - submission package")
    total = len(pages)
    for i, p in enumerate(pages, start=1):
        if p[0] == "special":
            _tag, fn, wide = p
            size = landscape(LETTER) if wide else LETTER
            c.setPageSize(size)
            fn(c, size[0], size[1])
            c.setFont(MONO, 6.0)
            c.drawString(size[0] - 112, 18, f"Page {i} of {total}")
        else:
            c.setPageSize(LETTER)
            _tag, title, lines = p
            _draw_flow_page(c, title, lines, i, total)
        c.showPage()
    c.save()
    return total


# ═════════════════════════════════════════════════════════════════════════════
# The answer key - every one of the 548 boxes
# ═════════════════════════════════════════════════════════════════════════════
V_EXPECT, V_NO_DATA, V_BY_RULE = "expect", "blank_no_data", "blank_by_rule"
V_NA, V_NOT_SCORED = "not_applicable", "not_scored"
FIELDS: Dict[str, dict] = {}
ACCOUNT_WHY = ("resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded "
               "document - scored manually against the account, not by this key")


def _put(field, verdict, value="", why="", trap="", source="text"):
    if field in FIELDS:
        raise SystemExit(f"answer key: {field} assigned twice")
    FIELDS[field] = {"verdict": verdict, "value": value, "why": why, "trap": trap,
                     "source": source}


def _tick(field, on, why="", trap=""):
    if on:
        _put(field, V_EXPECT, "Y", why, trap)
    else:
        _put(field, V_NO_DATA, "", why or "the document does not assert this", trap)


def build_key():
    schema = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json")
                        .read_text(encoding="utf-8"))
    FIELDS.clear()
    Q, M = D.QUESTIONS, D.MORTGAGEE

    # FORM, PRODUCER
    _put("Form_EditionIdentifier_A", V_EXPECT, "ACORD 125 (2025/03)")
    _put("Form_CompletionDate_A", V_NOT_SCORED, "", "the generation date")
    for fld, v in (("Producer_FullName_A", D.PRODUCER),
                   ("Producer_MailingAddress_LineOne_A", D.PRODUCER_L1),
                   ("Producer_MailingAddress_LineTwo_A", D.PRODUCER_L2),
                   ("Producer_MailingAddress_CityName_A", D.PRODUCER_CITY),
                   ("Producer_MailingAddress_StateOrProvinceCode_A", D.PRODUCER_STATE),
                   ("Producer_MailingAddress_PostalCode_A", D.PRODUCER_ZIP),
                   ("Producer_ContactPerson_FullName_A", D.PRODUCER_CONTACT),
                   ("Producer_ContactPerson_PhoneNumber_A", D.PRODUCER_PHONE),
                   ("Producer_ContactPerson_EmailAddress_A", D.PRODUCER_EMAIL),
                   ("Producer_AuthorizedRepresentative_FullName_A", D.PRODUCER_CONTACT)):
        _put(fld, V_NOT_SCORED, v, ACCOUNT_WHY)
    _put("Producer_FaxNumber_A", V_NO_DATA, "", "no producer fax is printed")
    _put("Producer_CustomerIdentifier_A", V_BY_RULE, "",
         "client: 'only if verified from agency/AMS' - FREC-001 is another agency's",
         trap=f"must not be {D.AGENCY_CUSTOMER_ID}")
    for fld in ("Producer_NationalIdentifier_A", "Producer_StateLicenseIdentifier_A"):
        _put(fld, V_NO_DATA, "", "lives in the agency profile, never in an upload")
    _put("Producer_AuthorizedRepresentative_Signature_A", V_BY_RULE, "", "AUTHORSHIP")

    # INSURER - the RECEIVING carrier, verified
    _put("Insurer_FullName_A", V_EXPECT, D.CARRIER, "the addressee of the submission",
         trap=f"must not be {D.CUR_CARRIER}")
    _put("Insurer_NAICCode_A", V_EXPECT, D.CARRIER_NAIC,
         "client: 'only if verified' - the carrier prints it on its acknowledgement",
         trap=f"must not be {D.CUR_CARRIER_NAIC}")
    _put("Insurer_ProductDescription_A", V_EXPECT, D.PROGRAM_NAME)
    _put("Insurer_ProductCode_A", V_EXPECT, D.PROGRAM_CODE)
    _put("Insurer_Underwriter_FullName_A", V_EXPECT, D.UNDERWRITER)
    _put("Insurer_Underwriter_OfficeIdentifier_A", V_EXPECT, D.UNDERWRITER_OFFICE)
    for fld in ("Insurer_ProducerIdentifier_A", "Insurer_SubProducerIdentifier_A"):
        _put(fld, V_NO_DATA, "", "client: 'only if verified from agency/AMS'")

    # POLICY
    _put("Policy_EffectiveDate_A", V_EXPECT, D.PROPOSED_EFF, trap=f"must not be {D.CUR_EFF}")
    _put("Policy_ExpirationDate_A", V_EXPECT, D.PROPOSED_EXP, trap=f"must not be {D.CUR_EXP}")
    _put("Policy_PolicyNumberIdentifier_A", V_NO_DATA, "",
         "client: blank for a new-business quote", trap="GL-123456 is the EXPIRING policy")
    _tick("Policy_Status_QuoteIndicator_A", True, "client: QUOTE")
    for st in ("Issue", "Bound", "Change", "Cancel", "Renew"):
        _tick(f"Policy_Status_{st}Indicator_A", False, "the transaction is a quote",
              trap="the incumbent dec prints 'RENEWAL OF GL-104471'")
    for fld in ("Policy_Status_EffectiveDate_A", "Policy_Status_EffectiveTime_A"):
        _put(fld, V_NO_DATA)
    _tick("Policy_Status_EffectiveTimeAMIndicator_A", False)
    _tick("Policy_Status_EffectiveTimePMIndicator_A", False)
    for k in ("CommercialGeneralLiability", "CommercialProperty", "BusinessAutoIndicator",
              "UmbrellaIndicator"):
        _tick(f"Policy_LineOfBusiness_{k}_A", True, "a line requested on the cover letter")
    for k in ("BoilerAndMachineryIndicator", "BusinessOwnersIndicator", "CrimeIndicator",
              "CyberAndPrivacy", "FiduciaryLiabilityIndicator", "GarageAndDealersIndicator",
              "LiquorLiabilityIndicator", "MotorCarrierIndicator", "TruckersIndicator",
              "YachtIndicator", "CommercialInlandMarineIndicator"):
        _tick(f"Policy_LineOfBusiness_{k}_A", False, "not requested",
              trap="inland marine is already with the carrier; property extensions are not lines")
    for ch in "ABCDEF":
        _put(f"Policy_LineOfBusiness_OtherIndicator_{ch}", V_NO_DATA)
        _put(f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{ch}", V_NO_DATA)
    for b in ("BoilerAndMachinery", "BusinessOwners", "CommercialInlandMarine",
              "CommercialProperty", "CommercialVehicle", "CommercialUmbrella", "Crime",
              "CyberAndPrivacy", "Fiduciary", "GarageAndDealers", "LiquorLiability",
              "MotorCarrier", "Truckers", "Yacht"):
        _put(f"{b}LineOfBusiness_PremiumAmount_A", V_BY_RULE, "", "a quote is not priced")
    _put("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", V_BY_RULE, "",
         "a quote is not priced", trap="must not be $18,450")
    _put("Policy_Payment_EstimatedTotalAmount_A", V_BY_RULE, "", "a quote is not priced",
         trap=f"must not be {D.CUR_TOTAL_PREMIUM}")
    _tick("Policy_Payment_DirectBillIndicator_A", True, "client: 'Direct, if known' - stated",
          trap="the incumbent dec says agency bill")
    _tick("Policy_Payment_ProducerBillIndicator_A", False, "billing is Direct")
    _put("Policy_Payment_PaymentScheduleCode_A", V_EXPECT, D.PAYMENT_PLAN_CODE,
         "ACORD tooltip: 'MO - Monthly'", trap="the incumbent billed quarterly")
    _put("Policy_PaymentMethod_MethodDescription_A", V_EXPECT, D.PAYMENT_METHOD,
         "the cover letter states the method", trap=f"must not be '{D.CUR_BILLING}'")
    _put("Policy_Audit_FrequencyCode_A", V_EXPECT, D.AUDIT_CODE,
         "the carrier's acknowledgement: premium audit annual")
    for fld in ("Policy_Payment_DepositAmount_A", "Policy_Payment_MinimumPremiumAmount_A"):
        _put(fld, V_BY_RULE, "", "set at quotation - the documents say so")
    _put("Policy_InformationPracticesNoticeIndicator_A", V_BY_RULE, "", "AUTHORSHIP")

    # ATTACHMENTS - what OUR package contains (ACORD 125 alone)
    _put("Policy_SectionAttached_VehicleScheduleIndicator_A", V_NOT_SCORED, "",
         "disputed: package principle vs the Orbin 'do not regress' list (owner decision)")
    for k in ("AccountsReceivableValuablePapersIndicator", "DealerIndicator",
              "ElectronicDataProcessingIndicator", "GlassAndSignIndicator",
              "InstallationBuildersRiskIndicator", "OpenCargoIndicator",
              "DriverInformationScheduleIndicator"):
        _put(f"Policy_SectionAttached_{k}_A", V_BY_RULE, "",
             "only ACORD 125 is generated; the client: tick 'only when Primble actually "
             "creates and attaches' the schedule")
    for ch in "ABCDEF":
        _put(f"Policy_SectionAttached_OtherPremiumAmount_{ch}", V_BY_RULE, "", "not priced")
        _put(f"CommercialPolicy_Attachment_OtherIndicator_{ch}", V_NO_DATA)
        _put(f"CommercialPolicy_Attachment_OtherDescription_{ch}", V_NO_DATA)
    for k in ("ContractorsSupplementIndicator", "StatementOfValuesIndicator",
              "LossSummaryIndicator", "AdditionalInterestScheduleIndicator",
              "AdditionalPremisesScheduleIndicator", "ApartmentBuildingSupplementIndicator",
              "CondominiumAssociationByLawsIndicator", "CoveragesScheduleIndicator",
              "HotelMotelSupplementIndicator",
              "InternationalLiabilityExposureSupplementIndicator",
              "InternationalPropertyExposureSupplementIndicator",
              "PremiumPaymentSupplementIndicator", "ProfessionalLiabilitySupplementIndicator",
              "RestaurantTavernSupplementIndicator", "StateSupplementIndicator",
              "VacantBuildingSupplementIndicator"):
        _put(f"CommercialPolicy_Attachment_{k}_A", V_BY_RULE, "", "only ACORD 125 is generated")

    # THE FIFTEEN QUESTIONS
    for code, q in Q.items():
        _put(f"CommercialPolicy_Question_{code}Code_A", V_EXPECT, q["answer"],
             f"the questionnaire answers {q['answer']}",
             source="scanned" if q["scanned"] else "text")
    _put("BusinessInformation_ParentOrganizationName_A", V_EXPECT, D.PARENT_ORG, "1a")
    _put("Subsidiary_ParentSubsidiaryRelationshipDescription_A", V_EXPECT, D.PARENT_RELATIONSHIP, "1a")
    _put("Subsidiary_ParentOwnershipPercent_A", V_EXPECT, D.PARENT_PCT, "1a")
    _put("Subsidiary_OrganizationName_A", V_EXPECT, D.SUB_ORG, "1b")
    _put("Subsidiary_ParentSubsidiaryRelationshipDescription_B", V_EXPECT, D.SUB_RELATIONSHIP, "1b")
    _put("Subsidiary_ParentOwnershipPercent_B", V_EXPECT, D.SUB_PCT, "1b")
    for k in ("SafetyManualIndicator_A", "SafetyPositionIndicator_B",
              "MonthlyMeetingsIndicator_B", "OSHAIndicator_B", "OtherIndicator_B"):
        _tick(f"CommercialPolicy_FormalSafetyProgram_{k}", True, "question 2's elements")
    _put("CommercialPolicy_FormalSafetyProgram_OtherDescription_B", V_EXPECT, D.SAFETY_OTHER)
    _put("CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A",
         V_EXPECT, Q["ABC"]["stated"])
    for i, (lob, pol) in enumerate(D.OTHER_POLICIES):
        r = "ABCD"[i]
        _put(f"OtherPolicy_PolicyNumberIdentifier_{r}", V_EXPECT, pol, "question 4")
        _put(f"OtherPolicy_LineOfBusinessCode_{r}", V_NOT_SCORED, "",
             "ACORD wants a line-of-business CODE; no code table in the repo")
    for r in "CD":
        _put(f"OtherPolicy_PolicyNumberIdentifier_{r}", V_NO_DATA, "", "two policies only",
             trap="the INCUMBENT's policies are not with this company")
        _put(f"OtherPolicy_LineOfBusinessCode_{r}", V_NO_DATA)
    _tick("CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A", True, "question 5 reason")
    _tick("CancelNonRenew_UnderwritingIndicator_A", True, "question 5 reason")
    _tick("CancelNonRenew_UnderwritingConditionCorrectedIndicator_A", True, "question 5")
    _put("CancelNonRenew_UnderwritingConditionCorrectedDescription_A", V_EXPECT, D.CONDITION_CORRECTED)
    _put("CancelNonRenew_NonRenewalIndicator_A", V_NOT_SCORED, "",
         "both events ARE non-renewals, but the questionnaire leaves this reason box "
         "unmarked - ambiguous")
    _tick("CancelNonRenew_NonPaymentIndicator_A", False, "no non-payment")
    _tick("CancelNonRenew_OtherIndicator_A", False)
    _put("CancelNonRenew_OtherDescription_A", V_NO_DATA)
    _put("CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A",
         V_EXPECT, Q["AAD"]["stated"])
    _put("CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A",
         V_NO_DATA, "", "question 7 is N")
    _put("CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A", V_EXPECT, D.FIRE_CODE["occur"])
    _put("CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", V_EXPECT, D.FIRE_CODE["explain"])
    _put("CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A", V_BY_RULE, "",
         "the service is only SCHEDULED - a resolution that has not happened is not one",
         trap=D.FIRE_CODE["pending"])
    _put("CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A", V_NO_DATA, "",
         "not resolved", trap="10/05/2026 is the SCHEDULED date")
    for blk, data in (("ForeclosureRepossessionBankruptcy", D.REPOSSESSION),
                      ("JudgementOrLien", D.LIEN)):
        _put(f"CommercialPolicy_{blk}_OccurrenceDate_A", V_EXPECT, data["occur"])
        _put(f"CommercialPolicy_{blk}Explanation_A", V_EXPECT, data["explain"])
        _put(f"CommercialPolicy_{blk}_ResolutionDescription_A", V_EXPECT, data["resolution"])
        _put(f"CommercialPolicy_{blk}_ResolutionDate_A", V_EXPECT, data["resolved"])
    for blk in ("UncorrectedFireCodeViolation", "ForeclosureRepossessionBankruptcy",
                "JudgementOrLien"):
        for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate", "_ResolutionDescription"):
            _put(f"CommercialPolicy_{blk}{suf}_B", V_NO_DATA, "", "one occurrence each")
    _put("CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A",
         V_EXPECT, Q["KAM"]["stated"])
    _put("CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A", V_EXPECT, Q["KAN"]["stated"])
    _put("CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A", V_EXPECT, Q["KAO"]["stated"])
    _put("CommercialPolicy_OperationsDescription_A", V_EXPECT, D.PRIMARY_OPERATIONS)
    _put("CommercialPolicy_OperationsDescription_B", V_EXPECT, D.OTHER_INSURED_OPERATIONS)
    _put("CommercialPolicy_RemarkText_A", V_EXPECT, D.REMARKS)

    # NAMED INSUREDS
    ents = ["CorporationIndicator", "IndividualIndicator", "JointVentureIndicator",
            "LimitedLiabilityCorporationIndicator", "NotForProfitIndicator", "OtherIndicator",
            "PartnershipIndicator", "SubchapterSCorporationIndicator", "TrustIndicator"]
    rows = [{"name": D.NAME, "fein": D.FEIN, "sic": D.SIC, "naics": D.NAICS, "gl": D.GL_CODE,
             "phone": D.BUS_PHONE, "web": D.WEBSITE, "l1": D.MAIL_L1, "l2": D.MAIL_L2,
             "city": D.MAIL_CITY, "state": D.MAIL_STATE, "zip": D.MAIL_ZIP,
             "members": D.MEMBERS}] + D.OTHER_INSUREDS
    for r, o in zip("ABC", rows):
        for col, key in (("FullName", "name"), ("TaxIdentifier", "fein"), ("SICCode", "sic"),
                         ("NAICSCode", "naics"), ("GeneralLiabilityCode", "gl"),
                         ("Primary_PhoneNumber", "phone"), ("Primary_WebsiteAddress", "web"),
                         ("MailingAddress_LineOne", "l1"), ("MailingAddress_LineTwo", "l2"),
                         ("MailingAddress_CityName", "city"),
                         ("MailingAddress_StateOrProvinceCode", "state"),
                         ("MailingAddress_PostalCode", "zip"),
                         ("LegalEntity_MemberManagerCount", "members")):
            src = "scanned" if (r == "A" and key == "members") else "text"
            _put(f"NamedInsured_{col}_{r}", V_EXPECT, o[key], source=src)
        for e in ents:
            _tick(f"NamedInsured_LegalEntity_{e}_{r}",
                  e == "LimitedLiabilityCorporationIndicator", "all three are LLCs")
        _put(f"NamedInsured_LegalEntity_OtherDescription_{r}", V_NO_DATA)
    _put("NamedInsured_BusinessStartDate_A", V_EXPECT, D.START_DATE, trap="2019 is the relocation")
    for i, ct in enumerate(D.CONTACTS):
        r = "AB"[i]
        _put(f"NamedInsured_Contact_ContactDescription_{r}", V_EXPECT, ct["type"])
        _put(f"NamedInsured_Contact_FullName_{r}", V_EXPECT, ct["name"])
        _put(f"NamedInsured_Contact_PrimaryPhoneNumber_{r}", V_EXPECT, ct["phone"])
        _put(f"NamedInsured_Contact_SecondaryPhoneNumber_{r}", V_EXPECT, ct["phone2"])
        _put(f"NamedInsured_Contact_PrimaryEmailAddress_{r}", V_EXPECT, ct["email"])
        _put(f"NamedInsured_Contact_SecondaryEmailAddress_{r}", V_EXPECT, ct["email2"])
        for slot, typ in (("Primary", ct["phone_type"]), ("Secondary", ct["phone2_type"])):
            for kind in ("Business", "Cell", "Home"):
                _tick(f"NamedInsured_Contact_{slot}{kind}PhoneIndicator_{r}", kind == typ,
                      "the phone's type is printed beside it")
    for fld in ("NamedInsured_Initials_A", "NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"):
        _put(fld, V_BY_RULE, "", "AUTHORSHIP")

    # BUSINESS INFORMATION
    _tick("BusinessInformation_BusinessType_ContractorIndicator_A", True)
    for k in ("ApartmentsIndicator", "CondominiumsIndicator", "InstitutionalIndicator",
              "ManufacturingIndicator", "OfficeIndicator", "OtherIndicator",
              "RestaurantIndicator", "RetailIndicator", "ServiceIndicator", "WholesaleIndicator"):
        _tick(f"BusinessInformation_BusinessType_{k}_A", False, "one nature of business")
    _put("BusinessInformation_BusinessType_OtherDescription_A", V_NO_DATA)

    # PREMISES A-D
    for r, l in zip("ABCD", D.LOCATIONS):
        _put(f"CommercialStructure_Location_ProducerIdentifier_{r}", V_EXPECT, l["num"])
        _put(f"CommercialStructure_Building_ProducerIdentifier_{r}", V_EXPECT, l["bldg"])
        _put(f"CommercialStructure_PhysicalAddress_LineOne_{r}", V_EXPECT, l["l1"])
        if l["l2"]:
            _put(f"CommercialStructure_PhysicalAddress_LineTwo_{r}", V_EXPECT, l["l2"])
        else:
            _put(f"CommercialStructure_PhysicalAddress_LineTwo_{r}", V_NO_DATA, "",
                 "no suite - the schedule prints '--'", trap="a placeholder never prints")
        for col, key in (("CityName", "city"), ("CountyName", "county"),
                         ("StateOrProvinceCode", "state"), ("PostalCode", "zip")):
            _put(f"CommercialStructure_PhysicalAddress_{col}_{r}", V_EXPECT, l[key])
        _put(f"CommercialStructure_AnnualRevenueAmount_{r}", V_EXPECT, l["revenue"],
             trap="the company total, the projection, payroll and the backlog")
        _tick(f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{r}", l["inside"])
        _tick(f"CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_{r}", not l["inside"])
        _tick(f"CommercialStructure_InsuredInterest_TenantIndicator_{r}", l["interest"] == "Tenant")
        _tick(f"CommercialStructure_InsuredInterest_OwnerIndicator_{r}", l["interest"] == "Owner")
        _tick(f"CommercialStructure_InsuredInterest_OtherIndicator_{r}", False)
        _put(f"CommercialStructure_InsuredInterest_OtherDescription_{r}", V_NO_DATA)
        _tick(f"CommercialStructure_RiskLocation_OtherIndicator_{r}", False)
        _put(f"CommercialStructure_RiskLocation_OtherDescription_{r}", V_NO_DATA)
        _put(f"CommercialStructure_Question_ABBCode_{r}", V_EXPECT, l["leased"])
        _put(f"BusinessInformation_FullTimeEmployeeCount_{r}", V_EXPECT, l["ft"],
             trap="20 is the headcount")
        _put(f"BusinessInformation_PartTimeEmployeeCount_{r}", V_EXPECT, l["pt"],
             trap="6 agency temps are not employees")
        _put(f"BuildingOccupancy_OccupiedArea_{r}", V_EXPECT, l["occupied"])
        _put(f"BuildingOccupancy_OpenToPublicArea_{r}", V_EXPECT, l["public"])
        _put(f"BuildingOccupancy_OperationsDescription_{r}", V_EXPECT, l["ops"])
        _put(f"Construction_BuildingArea_{r}", V_EXPECT, l["total_area"])
    _put("CommercialStructure_InstallationRepairWorkPercent_A", V_EXPECT, D.INSTALL_PCT)
    _put("CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", V_EXPECT, D.INSTALL_OFF_PCT)

    # LOSS HISTORY - three claims, latest valuation
    for r, x in zip("ABC", D.LOSSES):
        for col, key in (("OccurrenceDate", "occurrence"), ("ClaimDate", "claim"),
                         ("LineOfBusiness", "line"), ("OccurrenceDescription", "desc"),
                         ("PaidAmount", "paid"), ("ReservedAmount", "reserved"),
                         ("ClaimStatus_SubrogationCode", "subro"), ("ClaimStatus_OpenCode", "open")):
            _put(f"LossHistory_{col}_{r}", V_EXPECT, x[key],
                 trap="the 2024 fax is an OLD valuation of the auto claim"
                 if key in ("paid", "reserved", "open") else "")
    _put("LossHistory_InformationYearCount_A", V_EXPECT, D.LOSS_YEARS)
    _put("LossHistory_TotalAmount_A", V_EXPECT, D.TOTAL_PAID, "ACORD tooltip: PAID",
         trap=f"must not be {D.TOTAL_INCURRED} (incurred)")
    _tick("LossHistory_NoPriorLossesIndicator_A", False, "three claims")

    # PRIOR CARRIER - three substantiated years
    for r, term in zip("ABC", D.PRIOR_TERMS):
        _put(f"PriorCoverage_PolicyYear_{r}", V_EXPECT, term["year"])
        for g, (carrier, pol, prem) in term["lines"].items():
            _put(f"PriorCoverage_{g}_InsurerFullName_{r}", V_EXPECT, carrier)
            _put(f"PriorCoverage_{g}_PolicyNumberIdentifier_{r}", V_EXPECT, pol)
            _put(f"PriorCoverage_{g}_TotalPremiumAmount_{r}", V_EXPECT, prem)
            _put(f"PriorCoverage_{g}_EffectiveDate_{r}", V_EXPECT, term["eff"])
            _put(f"PriorCoverage_{g}_ExpirationDate_{r}", V_EXPECT, term["exp"])
    _put("PriorCoverage_OtherLine_LineOfBusinessCode_A", V_NOT_SCORED, "",
         "ACORD wants a CODE; no code table in the repo")

    # ADDITIONAL INTEREST - the mortgagee, and a loss payee
    for col, v in (("FullName_A", M["name"]), ("MailingAddress_LineOne_A", M["l1"]),
                   ("MailingAddress_LineTwo_A", M["l2"]), ("MailingAddress_CityName_A", M["city"]),
                   ("MailingAddress_StateOrProvinceCode_A", M["state"]),
                   ("MailingAddress_PostalCode_A", M["zip"]),
                   ("MailingAddress_CountryCode_A", M["country"]),
                   ("InterestRank_A", M["rank"]), ("AccountNumberIdentifier_A", M["loan_no"]),
                   ("InterestEndDate_A", M["end"]), ("LoanAmount_A", M["amount"]),
                   ("Primary_PhoneNumber_A", M["phone"]), ("Primary_FaxNumber_A", M["fax"]),
                   ("Primary_EmailAddress_A", M["email"]),
                   ("InterestReasonDescription_A", M["reason"]),
                   ("Item_LocationProducerIdentifier_A", M["loc"]),
                   ("Item_BuildingProducerIdentifier_A", M["bldg"]),
                   ("ItemDescription_A", M["item"])):
        _put(f"AdditionalInterest_{col}", V_EXPECT, v, "the loan summary")
    # ACORD's tooltip: "The additional interest's full name. As used here, this
    # is the name of the TRUST" - question 11's box, not a second interest.
    # (Corrected 28 Sep: the first version-2 key expected the loss payee here.)
    _put("AdditionalInterest_FullName_B", V_EXPECT, D.TRUST_NAME,
         "question 11 - the name of the trust (ACORD tooltip)", source="scanned",
         trap=f"must not be {D.LOSS_PAYEE_B} (a loss payee, not the trust)")
    _tick("AdditionalInterest_Interest_MortgageeIndicator_A", True, "a first mortgage")
    _tick("AdditionalInterest_CertificateRequiredIndicator_A", True, "evidence: certificate")
    for k in ("AdditionalInsuredIndicator", "BreachOfWarrantyIndicator", "CoOwnerIndicator",
              "EmployeeAsLessorIndicator", "LeasebackOwnerIndicator",
              "LendersLossPayableIndicator", "LienholderIndicator", "LossPayeeIndicator",
              "OtherIndicator", "OwnerIndicator", "RegistrantIndicator", "TrusteeIndicator"):
        _tick(f"AdditionalInterest_Interest_{k}_A", False, "the interest is a mortgagee")
    _tick("AdditionalInterest_PolicyRequiredIndicator_A", False, "policy copy not required")
    _tick("AdditionalInterest_SendBillIndicator_A", False, "do not send bills")
    _put("AdditionalInterest_Interest_OtherDescription_A", V_NO_DATA)
    for col in ("Item_AircraftProducerIdentifier_A", "Item_AirportIdentifier_A",
                "Item_BoatProducerIdentifier_A", "Item_VehicleProducerIdentifier_A",
                "Item_ScheduledItemClassCode_A", "Item_ScheduledItemProducerIdentifier_A"):
        _put(f"AdditionalInterest_{col}", V_NO_DATA, "", "the loan summary prints 'N/A'",
             trap="a placeholder never prints")

    defaulted = [fld for fld in schema if fld not in FIELDS]
    for fld in defaulted:
        _put(fld, V_NO_DATA, "", "not stated in the package")
    return schema, defaulted


_NARRATIVE_NAME = re.compile(r"(Description|Explanation|RemarkText|Operations|Relationship)", re.I)


def _match_mode(field: str, meta: dict) -> str:
    tu = (meta.get("tu") or "").strip().lower()
    if meta.get("ft") == "/Tx" and tu.startswith("enter text") and _NARRATIVE_NAME.search(field):
        return "semantic"
    return "exact"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


_TOPIC = {"AAI": "subsidiary_of_another", "AAJ": "has_subsidiaries",
          "KAA": "formal_safety_program", "ABC": "flammables_explosives_chemicals",
          "AAH": "other_insurance_with_carrier", "AAC": "coverage_declined_cancelled_nonrenewed",
          "AAD": "abuse_molestation_discrimination_claims", "KAB": "fraud_arson_conviction",
          "AAF": "uncorrected_fire_safety_violations", "KAK": "foreclosure_repossession_bankruptcy",
          "KAL": "judgement_or_lien", "ABB": "business_in_trust", "KAC": "foreign_operations",
          "KAM": "other_business_ventures", "KAN": "owns_leases_operates_drones",
          "KAO": "hires_drone_operators"}


def assemble(schema: dict) -> dict:
    unknown = [fld for fld in FIELDS if fld not in schema]
    if unknown:
        raise SystemExit(f"answer key names fields NOT on the ACORD 125 schema: {unknown[:8]}")
    for fld, v in FIELDS.items():
        v["match"] = _match_mode(fld, schema.get(fld) or {})
    expect = {fld: v["value"] for fld, v in FIELDS.items() if v["verdict"] == V_EXPECT}
    blanks = sorted(fld for fld, v in FIELDS.items() if v["verdict"] in (V_NO_DATA, V_BY_RULE, V_NA))
    forbidden: Dict[str, List[str]] = {}
    for value, scope, _why in D.DECOYS:
        forbidden.setdefault(scope, []).append(value)
    forbidden.setdefault("Policy_ExpirationDate_A", []).append(D.CUR_EXP)
    shapes = {
        "NamedInsured_TaxIdentifier_*": {"regex": r"^\d{2}-?\d{7}$", "why": "a FEIN is nine digits"},
        "NamedInsured_NAICSCode_*": {"regex": r"^\d{6}$", "why": "NAICS is six digits"},
        "NamedInsured_SICCode_*": {"regex": r"^\d{4}$", "why": "SIC is four digits"},
        "*_PostalCode_*": {"regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP"},
        "*StateOrProvinceCode*": {"regex": r"^[A-Za-z]{2}$", "why": "two letters"},
        "Policy_Payment_PaymentScheduleCode_A": {"regex": r"^[A-Z]{2}$", "why": "AN / MO / QT"},
        "Policy_Audit_FrequencyCode_A": {"regex": r"^[ASQMO]$", "why": "A / S / Q / M / O"},
    }
    expected_absent = {
        "scope": ["CommercialStructure_PhysicalAddress_LineOne_*", "NamedInsured_FullName_*",
                  "AdditionalInterest_FullName_*", "AdditionalInterest_MailingAddress_LineOne_*"],
        "values": [a for a, *_r in D.JOB_SITES] + [n for n, *_r in D.CERT_HOLDERS]
                  + [a for _n, a, *_r in D.CERT_HOLDERS] + [D.LANDLORD, D.PARENT_ORG],
    }
    row_sets = {
        "named_insureds": {"slots": list("ABC"), "columns": {
            "name": "NamedInsured_FullName_{row}", "fein": "NamedInsured_TaxIdentifier_{row}",
            "naics": "NamedInsured_NAICSCode_{row}",
            "phone": "NamedInsured_Primary_PhoneNumber_{row}",
            "web": "NamedInsured_Primary_WebsiteAddress_{row}"},
            "rows": [{"name": D.NAME, "fein": D.FEIN, "naics": D.NAICS, "phone": D.BUS_PHONE,
                      "web": D.WEBSITE}] + [{"name": o["name"], "fein": o["fein"],
                                             "naics": o["naics"], "phone": o["phone"],
                                             "web": o["web"]} for o in D.OTHER_INSUREDS]},
        "premises": {"slots": list("ABCD"), "columns": {
            "loc": "CommercialStructure_Location_ProducerIdentifier_{row}",
            "line1": "CommercialStructure_PhysicalAddress_LineOne_{row}",
            "city": "CommercialStructure_PhysicalAddress_CityName_{row}",
            "zip": "CommercialStructure_PhysicalAddress_PostalCode_{row}",
            "revenue": "CommercialStructure_AnnualRevenueAmount_{row}",
            "ft": "BusinessInformation_FullTimeEmployeeCount_{row}",
            "occupied": "BuildingOccupancy_OccupiedArea_{row}",
            "area": "Construction_BuildingArea_{row}"},
            "rows": [{"loc": l["num"], "line1": l["l1"], "city": l["city"], "zip": l["zip"],
                      "revenue": l["revenue"], "ft": l["ft"], "occupied": l["occupied"],
                      "area": l["total_area"]} for l in D.LOCATIONS]},
        "contacts": {"slots": list("AB"), "columns": {
            "type": "NamedInsured_Contact_ContactDescription_{row}",
            "name": "NamedInsured_Contact_FullName_{row}",
            "phone": "NamedInsured_Contact_PrimaryPhoneNumber_{row}",
            "email": "NamedInsured_Contact_PrimaryEmailAddress_{row}"},
            "rows": [{"type": c["type"], "name": c["name"], "phone": c["phone"],
                      "email": c["email"]} for c in D.CONTACTS]},
        "losses": {"slots": list("ABC"), "columns": {
            "occurrence": "LossHistory_OccurrenceDate_{row}",
            "line": "LossHistory_LineOfBusiness_{row}", "paid": "LossHistory_PaidAmount_{row}",
            "reserved": "LossHistory_ReservedAmount_{row}",
            "open": "LossHistory_ClaimStatus_OpenCode_{row}"},
            "rows": [{"occurrence": x["occurrence"], "line": x["line"], "paid": x["paid"],
                      "reserved": x["reserved"], "open": x["open"]} for x in D.LOSSES]},
        "prior_coverage": {"slots": list("ABC"), "columns": {
            f"{g}_{k}": f"PriorCoverage_{g}_{fld}_{{row}}" for g in D.GRID_LINE_NAMES
            for k, fld in (("carrier", "InsurerFullName"), ("policy", "PolicyNumberIdentifier"),
                           ("premium", "TotalPremiumAmount"))},
            "rows": [{f"{g}_{k}": v for g, (c, p, pr) in t["lines"].items()
                      for k, v in (("carrier", c), ("policy", p), ("premium", pr))}
                     for t in D.PRIOR_TERMS]},
    }
    counts = {v: sum(1 for x in FIELDS.values() if x["verdict"] == v)
              for v in (V_EXPECT, V_NO_DATA, V_BY_RULE, V_NA, V_NOT_SCORED)}
    return {
        "_meta": {"kit": "FR125 v2 - the client's case at data-map density", "account": D.NAME,
                  "document": PDF_PATH.name, "built_by": "backend/scripts/make_fr125_test_pdf.py",
                  "answers_from": "the client's rules (125_reference, 8-19-26) applied to "
                                  "documents that state what the Vertafore data map fills",
                  "fields_on_form": len(schema), "verdict_counts": counts,
                  "absent_by_design": D.ABSENT_BY_DESIGN, "scanned_only": D.SCANNED_ONLY},
        "_doc": f"{PDF_PATH.name} - one upload, {TARGET_PAGES} pages",
        "_forms": ["ACORD_125"],
        "expect": {"ACORD_125": expect},
        "must_be_blank": {"ACORD_125": blanks},
        "forbidden": {"ACORD_125": forbidden},
        "shapes": {"ACORD_125": shapes},
        "expected_absent": {"ACORD_125": expected_absent},
        "row_sets": {"ACORD_125": row_sets},
        "fields": FIELDS,
        "match_modes": {"ACORD_125": {
            "semantic": sorted(fld for fld, v in FIELDS.items()
                               if v["verdict"] == V_EXPECT and v["match"] == "semantic"),
            "rule": "semantic = ACORD tooltip 'Enter text:' AND a narrative field name."}},
        "expected_facts": expected_facts(),
    }


def expected_facts() -> dict:
    return {
        "_scalars": {
            "applicant_name": D.NAME, "fein": D.FEIN, "sic_code": D.SIC, "naics_code": D.NAICS,
            "entity_type": D.ENTITY, "business_start_date": D.START_DATE,
            "effective_date": D.PROPOSED_EFF, "expiration_date": D.PROPOSED_EXP,
            "operations_description": D.PRIMARY_OPERATIONS,
            "other_named_insured_operations": D.OTHER_INSURED_OPERATIONS,
            "applicant_business_phone": D.BUS_PHONE, "applicant_website": D.WEBSITE,
            "applicant_gl_class_code": D.GL_CODE,
            "sales_installation_repair_percent": D.INSTALL_PCT,
            "sales_installation_repair_off_premises_percent": D.INSTALL_OFF_PCT,
            "audit_period": D.AUDIT_WORD,
        },
        "_lists": {
            "applicant_contacts": {
                "expected": [{"name": c["name"], "contact_type": c["type"], "phone": c["phone"],
                              "email": c["email"]} for c in D.CONTACTS],
                "key": "name", "columns": ["contact_type", "phone", "email"]},
            "property_locations": {
                "expected": [{"address": l["l1"], "county": l["county"],
                              "full_time_employees": l["ft"], "part_time_employees": l["pt"],
                              "annual_revenue": l["revenue"], "occupied_area": l["occupied"],
                              "open_to_public_area": l["public"],
                              "total_building_area": l["total_area"]} for l in D.LOCATIONS],
                "key": "address",
                "columns": ["county", "full_time_employees", "part_time_employees",
                            "annual_revenue", "occupied_area", "open_to_public_area",
                            "total_building_area"]},
            "named_insured_details": {
                "expected": [{"name": o["name"], "fein": o["fein"], "sic": o["sic"],
                              "naics": o["naics"], "phone": o["phone"], "website": o["web"]}
                             for o in D.OTHER_INSUREDS],
                "key": "name", "columns": ["fein", "sic", "naics", "phone", "website"]},
            "organization_relationships": {
                "expected": [{"name": D.PARENT_ORG, "role": "parent", "percent_owned": D.PARENT_PCT},
                             {"name": D.SUB_ORG, "role": "subsidiary", "percent_owned": D.SUB_PCT}],
                "key": "name", "columns": ["role", "percent_owned"]},
            "disclosure_answers": {
                "expected": [{"topic": _TOPIC[c], "answer": q["answer"]} for c, q in D.QUESTIONS.items()],
                "key": "topic", "columns": ["answer"]},
            "safety_program_elements": {
                "expected": [{"element": e} for e in
                             ("Safety Manual", "Safety Position", "Monthly Meetings", "OSHA")],
                "key": "element", "columns": []},
            "loss_history": {
                "expected": [{"claim_number": x["claim_no"], "date": x["occurrence"],
                              "paid": x["paid"], "reserved_amount": x["reserved"],
                              "open_code": "O" if x["open"] == "Y" else "C"} for x in D.LOSSES],
                "key": "claim_number", "columns": ["date", "paid", "reserved_amount", "open_code"]},
            "additional_interests": {
                "expected": [{"name": D.MORTGAGEE["name"], "interest_type": "Mortgagee",
                              "lien_amount": D.MORTGAGEE["amount"],
                              "reference_number": D.MORTGAGEE["loan_no"],
                              "phone": D.MORTGAGEE["phone"], "email": D.MORTGAGEE["email"]},
                             {"name": D.LOSS_PAYEE_B, "interest_type": "Loss Payee"}],
                "key": "name",
                "columns": ["interest_type", "lien_amount", "reference_number", "phone", "email"]},
        },
        "_must_be_empty": [],
    }


# ═════════════════════════════════════════════════════════════════════════════
# Verification - the kit must be FAIR and DENSE
# ═════════════════════════════════════════════════════════════════════════════
def page_texts() -> List[str]:
    import pdfplumber
    from utils import page_layout as pl
    out = []
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for pg in pdf.pages:
            t = pl.page_text(pg)
            out.append(t if isinstance(t, str) else (t[0] if t else ""))
    return out


def verify(key: dict, pages: int) -> dict:
    texts = page_texts()
    text = "\n".join(texts)
    hay = _norm(text)
    scan_hay = _norm(" ".join(SCANNED_TEXT))
    words = set(re.findall(r"[a-z0-9]{3,}", (text + " " + " ".join(SCANNED_TEXT)).lower()))
    problems: List[str] = []
    for fld, val in key["expect"]["ACORD_125"].items():
        meta = FIELDS[fld]
        if fld == "Form_EditionIdentifier_A" or "Indicator_" in fld:
            continue                       # a tick is not a quotable string
        if fld in ("Policy_Payment_PaymentScheduleCode_A", "Policy_Audit_FrequencyCode_A"):
            continue                       # printed as "Monthly (MO)" / "code A" - checked below
        if fld.startswith("CommercialPolicy_Question_") or fld.startswith(
                "CommercialStructure_Question_ABBCode_"):
            continue                       # an X, or a Y/N column - checked below / by eye
        if meta["match"] == "semantic":
            lost = [w for w in re.findall(r"[a-z0-9]{3,}", str(val).lower()) if w not in words]
            if lost:
                problems.append(f"NOT IN DOCUMENT: {fld} lost words {lost[:5]}")
            continue
        probe = _norm(val)[:60]
        if probe and probe not in hay and probe not in scan_hay:
            problems.append(f"NOT IN DOCUMENT: {fld} = {str(val)[:70]!r}")
    for code, q in D.QUESTIONS.items():
        if q["scanned"] and _norm(q["stated"])[:40] not in scan_hay:
            problems.append(f"question {q['n']}'s statement is not on the scan")
        if q["scanned"] and _norm(q["stated"])[:40] in hay:
            problems.append(f"question {q['n']} leaks into the text layer (scanned-only)")
    for value, scope, _why in D.DECOYS:
        if _norm(value) not in hay and _norm(value) not in scan_hay:
            problems.append(f"DECOY MISSING: {value!r} ({scope})")
    for probe, what in ((_norm(f"{D.PAYMENT_PLAN_WORD} ({D.PAYMENT_PLAN_CODE})"), "payment plan"),
                        ("auditperiodcodea", "audit code"), ("policynogl123456", "teletype repair")):
        if probe not in hay:
            problems.append(f"NOT PRINTED / NOT REPAIRED: {what}")
    if f"numberofmembersandmanagers{D.MEMBERS}" in hay:
        problems.append("the member count leaks into the text layer (scanned-only)")
    total_chars = sum(len(t) for t in texts)
    thin = [(i + 1, len(t)) for i, t in enumerate(texts) if 40 < len(t) < 2500]
    if pages != TARGET_PAGES:
        problems.append(f"{pages} pages, not {TARGET_PAGES}")
    if total_chars < MIN_CHARS:
        problems.append(f"only {total_chars:,} text characters (< {MIN_CHARS:,})")
    if thin:
        problems.append(f"thin pages (< 2,500 chars): {thin[:8]}")
    problems += _self_consistency(key)
    if problems:
        for p in problems:
            print("  FAIL:", p)
        raise SystemExit(f"verification failed: {len(problems)} problem(s)")
    stats = {"pages": pages, "text_chars": total_chars,
             "scanned_pages": sum(1 for t in texts if len(t) <= 40),
             "min_page_chars": min(len(t) for t in texts if len(t) > 40),
             "expectations": len(key["expect"]["ACORD_125"]),
             "must_be_blank": len(key["must_be_blank"]["ACORD_125"]), "decoys": len(D.DECOYS)}
    print(f"  verification OK: {stats}")
    return stats


def _self_consistency(key: dict) -> List[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sff", str(BACKEND / "scripts" / "score_form_fill.py"))
    sff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sff)
    out: List[str] = []
    perfect = dict(key["expect"]["ACORD_125"])
    res = sff.score_form("ACORD_125", key, perfect, lambda f: None)
    for kind in ("wrong", "blank_violation", "forbidden", "shape", "overflow_leak"):
        for row in res["details"].get(kind, [])[:4]:
            out.append(f"SELF-CONSISTENCY ({kind}): {row}")
    if res["tally"].get("correct") != len(perfect):
        out.append(f"SELF-CONSISTENCY: {res['tally'].get('correct')} of {len(perfect)} correct")
    for g in sff.score_rows("ACORD_125", key, perfect):
        if g.get("cross_row") or g.get("cells_correct") != g.get("cells_expected"):
            out.append(f"SELF-CONSISTENCY (row-cell): {g}")
    res0 = sff.score_form("ACORD_125", key, {}, lambda f: None)
    for kind in ("blank_violation", "forbidden", "shape", "overflow_leak", "wrong"):
        if res0["tally"].get(kind):
            out.append(f"SELF-CONSISTENCY: an EMPTY form reports {res0['tally'][kind]} {kind}")
    return out


def write_readme(key: dict, stats: dict, defaulted: List[str]) -> None:
    c = key["_meta"]["verdict_counts"]
    lines = [
        "# FR125 v2 - the client's case at data-map density", "",
        f"**Upload:** `FR125_front_range_package.pdf` - {stats['pages']} pages, "
        f"{stats['text_chars']:,} text-layer characters (every text page at least "
        f"{stats['min_page_chars']:,}), {stats['scanned_pages']} scanned pages with no text "
        "layer, 1 landscape page.  ",
        "**Answer key:** `FR125_answer_key.json` - all 548 ACORD 125 boxes.  ",
        "**Version 1** (the sparse client case graded in round 2 test 2) is kept in "
        "`v1_round2_test2/`.", "",
        "## What the form should look like", "",
        "Filled the way the client's Vertafore data map is filled: nearly every box a document "
        "can support carries a value. Every client rule still holds - receiving carrier, NAIC "
        "only if verified (it is, on the carrier's acknowledgement), no policy number or "
        "premium on a quote, no invented history, blank is not No.", "",
        "| | boxes |", "|---|---|",
        f"| expect a value | **{c['expect']}** |",
        f"| must be blank - nothing stated | {c['blank_no_data']} |",
        f"| must be blank - a rule owns it | {c['blank_by_rule']} |",
        f"| not scored | {c['not_scored']} |", "",
        "## Run it", "", "```bash", "# restart the backend first",
        "python3 backend/scripts/make_fr125_test_pdf.py",
        "# upload the PDF, generate ACORD 125 ONLY, change nothing",
        "python3 backend/scripts/dump_a125_run.py --list",
        "python3 backend/scripts/dump_a125_run.py <session_id> > fr125_run.json",
        "python3 backend/scripts/report_125_run.py --key fr125_test_data/FR125_answer_key.json "
        "--dump fr125_run.json --label \"ROUND 2 - TEST 3\"", "```", "",
        "## The traps", "", "| value | forbidden in | why |", "|---|---|---|",
        *[f"| `{v}` | `{s}` | {w} |" for v, s, w in D.DECOYS], "",
        "## Reachable ONLY by OCR", "", *[f"- `{x}`" for x in D.SCANNED_ONLY], "",
        "## Deliberately never stated", "", *[f"- {a}" for a in D.ABSENT_BY_DESIGN], "",
        f"{len(defaulted)} boxes defaulted to 'nothing stated' at build time.",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_pages():
    """Compatibility for the tests: builds the flow (and SCANNED_TEXT)."""
    return build_flow()


def main() -> int:
    pages = assemble_pages()
    n = render(pages)
    schema, defaulted = build_key()
    key = assemble(schema)
    KEY_PATH.write_text(json.dumps(key, indent=1), encoding="utf-8")
    stats = verify(key, n)
    write_readme(key, stats, defaulted)
    fam: Dict[str, int] = {}
    for fld in defaulted:
        fam[fld.split("_")[0]] = fam.get(fld.split("_")[0], 0) + 1
    print(f"  wrote {PDF_PATH.relative_to(ROOT)} ({n} pages)")
    print(f"  wrote {KEY_PATH.relative_to(ROOT)}  {key['_meta']['verdict_counts']}")
    print(f"  defaulted to blank_no_data: {len(defaulted)}  by family: {fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
