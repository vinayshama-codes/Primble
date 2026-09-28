"""
make_fr125_test_pdf.py - the Front Range ACORD 125 kit, built from the CLIENT'S
own answer key.

    python3 backend/scripts/make_fr125_test_pdf.py

Writes into `fr125_test_data/`:

    FR125_front_range_package.pdf   ~100 pages, deliberately hard to extract
    FR125_answer_key.json           a verdict for ALL 548 ACORD 125 fields
    README-FR125-HOW-TO-TEST.md     what each trap proves and how to score

WHY A SECOND KIT
----------------
The Meridian kit (`271page_test_data/`) grades us against an answer sheet I
wrote, so a box I misunderstood scores "correct" against my own mistake - which
is exactly what happened with the prior-carrier OTHER line. This kit grades us
against the answer sheet the CLIENT wrote (`125_reference/`). Passing it means
passing their test.

The two kits do different jobs and both are kept:
  * Meridian - adversarial: four named insureds, five premises, four claims,
    silence traps (questions nobody asked), eleven decoys.
  * Front Range - the client's case: one entity, one premises, one claim, every
    question answered - made HARD by how the documents are printed rather than
    by what they omit.

WHAT MAKES IT HARD (every technique is one a real package uses)
--------------------------------------------------------------
  scanned pages      an image with NO text layer - only OCR can read it. Some
                     facts live ONLY there, tagged `SCANNED_ONLY` in the key so
                     a miss is attributed to OCR first.
  landscape page     a wide statement of values printed sideways-wide
  X-in-a-column      yes / no answers given by an X under a column header, the
                     way every paper questionnaire does it
  riffled tables     a description that runs under the next column (`pa$rt4y`)
  teletype           letter-spaced dec-page text (`G L - 1 2 3 4 5 6`)
  two-column drift   two contacts side by side whose lines do not align
  dot leaders        a label on the left, its value 70 characters away
  abbreviations      FT / PT / OCC SF / PUB SF / TOT SF / CL / INT / LSD
  spelled 3 ways     $4,250,000 / "about $4.25 million" / 4,250 ($000)
  placeholders       "N/A", "--", "(none)" in source cells - a box they reach
                     must end up EMPTY, never carrying the placeholder
  two valuations     the same claim on a current loss run AND an old faxed one
"""
from __future__ import annotations

import json
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
LEFT, TOP, LEAD = 38.0, H - 54.0, 10.6
MONO, BOLD = "Courier", "Courier-Bold"
TARGET_PAGES = 100

Draw = Callable[[canvas.Canvas, float, float], None]      # (canvas, width, height)
PAGES: List[Tuple[Draw, bool]] = []                        # (draw, is_landscape)
SCANNED_TEXT: List[str] = []                               # what the scans say


# ═════════════════════════════════════════════════════════════════════════════
# Primitives
# ═════════════════════════════════════════════════════════════════════════════
def _head(c: canvas.Canvas, title: str, w: float, h: float) -> float:
    """Running header carrying the CURRENT carrier's contact details on every
    page - the frequency decoy that must never become the applicant's."""
    c.setFont(MONO, 6.2)
    c.drawString(LEFT, h - 30, f"{D.CUR_CARRIER}   {D.CUR_CARRIER_WEB}   "
                               f"Service {D.CUR_CARRIER_PHONE}")
    c.setFont(BOLD, 8.6)
    c.drawString(LEFT, h - 44, title[:118])
    return h - 58


def add(draw: Draw, wide: bool = False) -> None:
    PAGES.append((draw, wide))


def plain(title: str, lines: List[str]) -> None:
    def draw(c, w, h):
        y = _head(c, title, w, h)
        for ln in lines:
            s = ln.strip()
            c.setFont(BOLD if (s and s.isupper() and len(s) < 90) else MONO, 7.4)
            c.drawString(LEFT, y, ln[:130])
            y -= LEAD
    add(draw)


def _tracked(c, x, y, text, size=7.0):
    gw = size * 0.6
    adv, extra = gw * 2.0, gw * 3.0
    cx = x
    for ch in text:
        if ch == " ":
            cx += adv + extra
            continue
        c.drawString(cx, y, ch)
        cx += adv


def teletype_block(c, x, y, lines, size=7.0):
    c.setFont(MONO, size)
    for ln in lines:
        _tracked(c, x, y, ln[:58], size)
        y -= LEAD
    return y


def riffled(c, y, header, rows, xs, size=6.9):
    """Whitespace table; long cells are drawn untruncated so they run under the
    next column and interleave when a reader sorts characters by x."""
    c.setFont(BOLD, 7.0)
    for x, hd in zip(xs, header):
        c.drawString(x, y, hd)
    y -= LEAD
    c.setFont(MONO, size)
    for row in rows:
        for x, cell in zip(xs, row):
            c.drawString(x, y, str(cell))
        y -= LEAD
    return y


def ruled_grid(c, x0, y0, col_w, row_h, header, rows, size=6.8):
    """A drawn grid - the box-and-line table a carrier's dec page prints."""
    n = len(header)
    width = sum(col_w)
    c.setLineWidth(0.4)
    c.setFont(BOLD, size)
    y = y0
    for r in range(len(rows) + 1):
        c.line(x0, y, x0 + width, y)
        y -= row_h
    c.line(x0, y, x0 + width, y)
    x = x0
    for i in range(n + 1):
        c.line(x, y0, x, y)
        if i < n:
            x += col_w[i]
    x = x0
    for i, hd in enumerate(header):
        c.drawString(x + 2, y0 - row_h + 3, hd)
        x += col_w[i]
    c.setFont(MONO, size)
    yy = y0 - row_h
    for row in rows:
        x = x0
        for i, cell in enumerate(row):
            c.drawString(x + 2, yy - row_h + 3, str(cell)[: int(col_w[i] / 3.6)])
            x += col_w[i]
        yy -= row_h
    return y - 6


def dot_leaders(title: str, pairs: List[Tuple[str, str]], intro: List[str] = ()):
    def draw(c, w, h):
        y = _head(c, title, w, h)
        c.setFont(MONO, 7.4)
        for ln in intro:
            c.drawString(LEFT, y, ln); y -= LEAD
        y -= 4
        for label, value in pairs:
            text = f"{label} " + "." * max(4, 78 - len(label)) + f" {value}"
            c.drawString(LEFT, y, text[:128]); y -= LEAD * 1.3
    add(draw)


def two_column(title: str, left: List[str], right: List[str]):
    def draw(c, w, h):
        y = _head(c, title, w, h)
        c.setFont(MONO, 7.4)
        for i in range(max(len(left), len(right))):
            if i < len(left):
                c.drawString(LEFT, y, left[i][:52])
            if i < len(right):
                c.drawString(322, y + (0.9 if i % 3 else 0.0), right[i][:56])
            y -= LEAD
    add(draw)


def bare_labels(title: str, pairs: List[Tuple[str, str]], intro: List[str] = ()):
    def draw(c, w, h):
        y = _head(c, title, w, h)
        c.setFont(MONO, 7.4)
        for ln in intro:
            c.drawString(LEFT, y, ln); y -= LEAD
        y -= 4
        for label, value in pairs:
            c.drawString(LEFT, y, f"{label}:"); y -= LEAD
            c.drawString(LEFT + 24, y, str(value)); y -= LEAD
    add(draw)


# ── Scanned pages: an image, no text layer ───────────────────────────────────
def _font(size: int):
    from PIL import ImageFont
    for path, idx in (("/System/Library/Fonts/Courier.ttc", 0),
                      ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
                      ("/Library/Fonts/Arial.ttf", 0)):
        try:
            return ImageFont.truetype(path, size, index=idx)
        except Exception:                                   # noqa: BLE001
            continue
    return ImageFont.load_default()


def scanned(lines: List[str], skew: float = 0.7, fax: str = "",
            quality: str = "scan") -> None:
    """Render `lines` as a raster page: skewed, speckled, fax-banded. There is
    no text layer at all, so the ONLY way in is OCR. `quality="fax"` halves the
    vertical resolution the way a 200x100 fax does."""
    from PIL import Image, ImageDraw, ImageFilter
    import random
    SCANNED_TEXT.extend(lines)
    rnd = random.Random(len(SCANNED_TEXT))                  # deterministic
    img = Image.new("L", (1700, 2200), 250)
    d = ImageDraw.Draw(img)
    f_body, f_head = _font(30), _font(24)
    y = 90
    if fax:
        d.text((80, 40), fax, fill=40, font=f_head)
        y = 120
    for ln in lines:
        d.text((110, y), ln, fill=rnd.randint(10, 45), font=f_body)
        y += 44
    for _ in range(2600):                                   # speckle
        x, yy = rnd.randint(0, 1699), rnd.randint(0, 2199)
        img.putpixel((x, yy), rnd.randint(60, 190))
    img = img.rotate(skew, resample=Image.BICUBIC, fillcolor=250)
    if quality == "fax":
        img = img.resize((1700, 1100)).resize((1700, 2200))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    tmp = Path(tempfile.gettempdir()) / f"fr125_scan_{len(SCANNED_TEXT)}_{len(PAGES)}.png"
    img.save(tmp)

    def draw(c, w, h, _p=str(tmp)):
        c.drawImage(_p, 0, 0, width=w, height=h)
    add(draw)


# ═════════════════════════════════════════════════════════════════════════════
# The document
# ═════════════════════════════════════════════════════════════════════════════
def _rule(n=112):
    return "-" * n


def build_pages() -> None:
    PAGES.clear(); SCANNED_TEXT.clear()
    C0, C1 = D.CONTACTS
    L = D.LOC

    # 1. Broker cover letter - the ONLY place the RECEIVING carrier is named
    plain("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION", [
        f"{D.PRODUCER}   {D.PRODUCER_L1}, {D.PRODUCER_L2}   {D.PRODUCER_CITY}, "
        f"{D.PRODUCER_STATE} {D.PRODUCER_ZIP}",
        f"Tel {D.PRODUCER_PHONE}   {D.PRODUCER_EMAIL}", "",
        "August 18, 2026", "",
        f"TO:        {D.CARRIER}",
        f"ATTN:      {D.UNDERWRITER}, Commercial Underwriting - {D.UNDERWRITER_OFFICE}",
        f"RE:        {D.NAME} - new business submission - QUOTE requested",
        f"Agency Customer ID: {D.AGENCY_CUSTOMER_ID}", "",
        f"Dear {D.UNDERWRITER.split()[0]},", "",
        "Please quote the account below for a term of "
        f"{D.PROPOSED_EFF} to {D.PROPOSED_EXP}. This is new business to your company;",
        "the insured has never been written by you and holds no policy with you today.",
        "", "LINES REQUESTED",
        "  Commercial General Liability   Commercial Property   Business Auto   Umbrella",
        "LINES NOT REQUESTED",
        "  Workers Compensation (placed separately, monoline)   Inland Marine   Cyber",
        "  Crime   Liquor   Professional", "",
        f"Billing preference: {D.BILLING} bill.   Payment plan requested: "
        f"{D.PAYMENT_PLAN_WORD} (paid in full).",
        "No premium indication is requested at this stage.", "",
        "The current programme renews 10/01/2026 with the incumbent and will NOT be",
        "renewed there. The incumbent's declarations are enclosed for reference only.",
        "", "Enclosures: applicant profile, contacts, premises schedule, statement",
        "of values, operations, revenue / payroll, census, safety programme, hazardous",
        "materials, signed questionnaire, current declarations (GL, Auto, Property,",
        "Umbrella), workers compensation summary, loss runs, lease summary.", "",
        f"Regards,", f"{D.PRODUCER_CONTACT}", f"{D.PRODUCER}",
    ])

    # 2. Checklist - an ATTACHMENT list that belongs to the BROKER's submission
    def checklist(c, w, h):
        y = _head(c, "SUBMISSION CHECKLIST", w, h)
        ruled_grid(c, LEFT, y, [220, 60, 250], 14,
                   ["DOCUMENT", "INCL", "NOTES"],
                   [["Statement / Schedule of Values", "Y", "landscape, 1 page"],
                    ["Vehicle Schedule", "Y", "on the Auto declarations"],
                    ["Driver Information Schedule", "Y", "on the Auto declarations"],
                    ["Loss Summary / Loss Runs", "Y", "5 years, all lines"],
                    ["Contractors Supplement", "N/A", "--"],
                    ["Additional Interest Schedule", "(none)", "no interests"],
                    ["Premium Payment Supplement", "N/A", "--"],
                    ["International Exposure", "N/A", "--"]])
    add(checklist)

    # 3. Applicant profile - riffled, placeholders, spelled-three-ways
    def profile(c, w, h):
        y = _head(c, "APPLICANT PROFILE", w, h)
        c.setFont(MONO, 7.4)
        for ln in [f"Legal name ........ {D.NAME}",
                   f"Mailing address ... {D.MAIL_L1}, {D.MAIL_CITY}, {D.MAIL_STATE} "
                   f"{D.MAIL_ZIP}", "Address line 2 .... --",
                   f"Business phone .... {D.BUS_PHONE}      Fax ..... N/A",
                   f"Website ........... {D.WEBSITE}",
                   f"Legal entity ...... Limited Liability Company ({D.ENTITY})",
                   "Members / managers  --",
                   f"Date business started (per Articles): {D.START_DATE_WORDS}",
                   "Relocated to the Commerce Way premises in 2019.", ""]:
            c.drawString(LEFT, y, ln); y -= LEAD
        y -= 4
        y = riffled(c, y, ["IDENTIFIER", "VALUE", "ISSUED BY / NOTE"],
                    [["FEIN", D.FEIN, "IRS - see W-9 enclosed"],
                     ["CO sales tax account", D.CO_TAX_ACCOUNT,
                      "Colorado Department of Revenue - not a federal number"],
                     ["USDOT", D.USDOT, "FMCSA - two vehicles over 10,001 lb GVWR"],
                     ["Contractor licence", D.CONTRACTOR_LIC,
                      "Colorado State Electrical Board (Master)"],
                     ["NAICS", D.NAICS, "Electrical Contractors and Other Wiring"],
                     ["SIC", D.SIC, "Electrical Work"]],
                    [LEFT, LEFT + 150, LEFT + 250], size=6.8)
        y -= 8
        c.setFont(MONO, 7.4)
        c.drawString(LEFT, y, "Established 2014-06-15. Formation documents on file "
                              "with the Colorado Secretary of State.")
    add(profile)

    # 4. Contacts - two drifting columns
    two_column("CONTACTS FOR THIS SUBMISSION",
               ["CONTACT 1", f"Type ........ {C0['type']}",
                f"Name ........ {C0['name']}", f"Phone ....... {C0['phone']}",
                f"E-mail ...... {C0['email']}", "Secondary ... N/A", "",
                "Available weekdays 7:00-3:30 for site", "inspection scheduling."],
               ["CONTACT 2", f"Type ........ {C1['type']}",
                f"Name ........ {C1['name']}", f"Phone ....... {C1['phone']}",
                f"E-mail ...... {C1['email']}", "Secondary ... (none)", "",
                "Billing, audit and certificate", "requests."])

    # 5. Premises schedule - ABBREVIATED headers, riffled, one row
    def premises(c, w, h):
        y = _head(c, "SCHEDULE OF PREMISES", w, h)
        c.setFont(MONO, 7.2)
        c.drawString(LEFT, y, "One premises. CL = city limits, INT = interest, "
                              "FT/PT = employees at this location."); y -= LEAD * 2
        y = riffled(c, y, ["LOC", "BLD", "STREET", "CITY", "CNTY", "ST", "ZIP",
                           "CL", "INT"],
                    [[L["num"], L["bldg"], L["l1"], L["city"], L["county"],
                      L["state"], L["zip"], "IN", L["interest"].upper()]],
                    [LEFT, LEFT + 26, LEFT + 52, LEFT + 150, LEFT + 205,
                     LEFT + 250, LEFT + 276, LEFT + 320, LEFT + 346], size=6.8)
        y -= 12
        y = riffled(c, y, ["LOC", "FT", "PT", "ANN REV", "OCC SF", "PUB SF",
                           "TOT SF", "LSD"],
                    [[L["num"], L["ft"], L["pt"], L["revenue"], L["occupied"],
                      L["public"], L["total_area"], L["leased_to_others"]]],
                    [LEFT, LEFT + 30, LEFT + 58, LEFT + 88, LEFT + 168,
                     LEFT + 222, LEFT + 272, LEFT + 326], size=6.8)
        y -= 12
        c.setFont(MONO, 7.2)
        c.drawString(LEFT, y, "OPERATIONS AT THIS LOCATION:"); y -= LEAD
        for ln in _wrap(L["ops"], 104):
            c.drawString(LEFT + 12, y, ln); y -= LEAD
    add(premises)

    # 6. The same premises facts, in prose and spelled differently
    plain("PREMISES - NARRATIVE", [
        "The insured leases roughly one third of a 15,000 sq ft multi-tenant flex",
        "building at 8000 Commerce Way from the building owner (see lease summary).",
        "It occupies 5000 sq ft, of which approximately 500 sq ft - the front",
        "counter and will-call area - is open to the public. No portion of the",
        "insured's space is sublet or leased to anyone else.", "",
        "Eighteen full-time and two part-time employees report to this location.",
        "Annual revenue attributable to the location is about $4.25 million (all",
        "company revenue is booked here). The premises are inside the Denver city",
        "limits, in the City and County of Denver.",
    ])

    # 7. Statement of values - LANDSCAPE, wide, decoy figures
    def sov(c, w, h):
        y = _head(c, "STATEMENT OF VALUES", w, h)
        ruled_grid(c, LEFT, y, [28, 28, 120, 60, 40, 44, 60, 70, 70, 70, 70, 64],
                   13, ["LOC", "BLD", "ADDRESS", "CITY", "ST", "ZIP", "OCC SF",
                        "BUILDING", "BPP", "EQUIPMENT", "TIV", "CONST"],
                   [[L["num"], L["bldg"], L["l1"], L["city"], L["state"], L["zip"],
                     L["occupied"], "Tenant - N/A", "$385,000", "$240,000",
                     "$625,000", "Joisted masonry"]])
        c.setFont(MONO, 6.8)
        c.drawString(LEFT, y - 60, "Building value not insured by the tenant. "
                                   "Building gross area per landlord: 15,000 SF.")
    add(sov, wide=True)

    # 8-9. Operations - two columns, the two distinct narratives
    two_column("OPERATIONS", ["DESCRIPTION OF PRIMARY OPERATIONS", ""]
               + _wrap(D.PRIMARY_OPERATIONS, 44),
               ["NATURE OF BUSINESS", f"  {D.NATURE}", "",
                "Not a retailer, not a manufacturer,", "not a wholesaler. The office",
                "and warehouse support field crews.", "",
                "OTHER NAMED INSUREDS", "  (none)"])
    plain("OPERATIONS - REVENUE MIX", [
        "RETAIL STORES OR SERVICE OPERATIONS - % OF TOTAL SALES",
        f"  Retail sales ............................................ {D.RETAIL_PCT}",
        f"  Installation, service or repair work .................... {D.INSTALL_PCT}",
        f"  ... of which performed OFF premises (customer locations)  {D.INSTALL_OFF_PCT}",
        "", "Service work is billed on time and materials; installation is bid.",
    ])

    # 10-11. Revenue and payroll - multi-year decoys
    def financials(c, w, h):
        y = _head(c, "REVENUE AND PAYROLL", w, h)
        y = ruled_grid(c, LEFT, y, [140, 110, 110], 13,
                       ["PERIOD", "REVENUE", "REVENUE ($000)"],
                       [[p, r, r.replace("$", "").replace(",000", "")]
                        for p, r in D.REVENUE_BY_YEAR])
        y -= 10
        c.setFont(MONO, 7.2)
        c.drawString(LEFT, y, "Annual revenue for this application = FY2025 actual "
                              "(most recent complete year)."); y -= LEAD * 2
        ruled_grid(c, LEFT, y, [160, 60, 60, 110], 13,
                   ["CLASS", "FT", "PT", "PAYROLL"],
                   [["Electricians (field)", "12", "0", "$1,150,000"],
                    ["Apprentices", "3", "2", "$210,000"],
                    ["Office / estimating", "3", "0", "$280,000"],
                    ["TOTAL", "18", "2", D.TOTAL_PAYROLL]])
    add(financials)

    # 12-13. Employee census - 20 people, and 6 agency temps who are not
    census = [(f"E-{100 + i}", t, "FT" if i < 18 else "PT")
              for i, t in enumerate(
                  ["Master Electrician"] * 2 + ["Journeyman Electrician"] * 10
                  + ["Apprentice"] * 3 + ["Estimator", "Office Manager",
                                          "Safety Manager", "Apprentice",
                                          "Office Assistant"])]
    def census_page(rows, title):
        def draw(c, w, h):
            y = _head(c, title, w, h)
            ruled_grid(c, LEFT, y, [70, 190, 60, 120], 13,
                       ["EMP ID", "POSITION", "STATUS", "LOCATION"],
                       [[a, b, s, "LOC 1"] for a, b, s in rows])
        add(draw)
    census_page(census[:12], "EMPLOYEE CENSUS (1 of 2)")
    def census2(c, w, h):
        y = _head(c, "EMPLOYEE CENSUS (2 of 2)", w, h)
        y = ruled_grid(c, LEFT, y, [70, 190, 60, 120], 13,
                       ["EMP ID", "POSITION", "STATUS", "LOCATION"],
                       [[a, b, s, "LOC 1"] for a, b, s in census[12:]])
        c.setFont(MONO, 7.2)
        for ln in ["Totals: 18 full-time, 2 part-time (20 employees).",
                   f"Also on site in peak season: {D.SEASONAL_TEMPS} laborers supplied by "
                   "Mile High Staffing -", "agency employees, NOT on the insured's payroll."]:
            y -= LEAD; c.drawString(LEFT, y, ln)
    add(census2)

    # 14-16. Job sites - 45 customer addresses, none a premises
    for part in range(3):
        rows = D.JOB_SITES[part * 15:(part + 1) * 15]
        def jobs(c, w, h, rows=rows, part=part):
            y = _head(c, f"RECENT PROJECTS - CUSTOMER JOB SITES ({part + 1} of 3)", w, h)
            c.setFont(MONO, 7.0)
            c.drawString(LEFT, y, "Work performed AT customer locations. Not insured "
                                  "premises."); y -= LEAD * 1.5
            riffled(c, y, ["#", "SITE ADDRESS", "CITY", "ZIP", "SCOPE"],
                    [[str(part * 15 + i + 1), a, ci, z, s]
                     for i, (a, ci, z, s) in enumerate(rows)],
                    [LEFT, LEFT + 20, LEFT + 150, LEFT + 250, LEFT + 290])
        add(jobs)

    # 17. Subcontractors
    def subs(c, w, h):
        y = _head(c, "SUBCONTRACTORS", w, h)
        ruled_grid(c, LEFT, y, [190, 130, 120, 90], 13,
                   ["NAME", "TRADE", "COI ON FILE", "LIMIT"],
                   [["Apex Trenching Inc", "Excavation", "Yes - 07/2026", "$1,000,000"],
                    ["Summit Low Voltage LLC", "Data cabling", "Yes - 03/2026",
                     "$1,000,000"],
                    ["Rocky Mtn Crane Service", "Crane rental", "Yes - 05/2026",
                     "$2,000,000"]])
    add(subs)

    # 18-19. Safety programme + OSHA 300A (the OSHA box is NOT asserted)
    plain("SAFETY PROGRAMME", [
        "FORMAL SAFETY PROGRAMME: IN OPERATION", "",
        "  1. Written safety manual (revised January 2025), issued to every employee.",
        f"  2. Designated safety manager: {D.SAFETY_MANAGER}, Safety Manager (full time).",
        "  3. Monthly safety meetings, attendance recorded; toolbox talks on site.", "",
        "The programme is described above in full. No other element is claimed.",
    ])
    def osha(c, w, h):
        y = _head(c, "OSHA FORM 300A - SUMMARY OF WORK-RELATED INJURIES (2025)", w, h)
        ruled_grid(c, LEFT, y, [260, 80], 13, ["ITEM", "COUNT"],
                   [["Total deaths", "0"], ["Cases with days away", "0"],
                    ["Cases with job transfer or restriction", "1"],
                    ["Other recordable cases", "2"],
                    ["Annual average employees", "20"],
                    ["Total hours worked", "38,400"]])
    add(osha)

    # 20. Hazardous materials - question 3's evidence
    def hazmat(c, w, h):
        y = _head(c, "HAZARDOUS MATERIALS INVENTORY", w, h)
        y = ruled_grid(c, LEFT, y, [170, 90, 150, 120], 13,
                       ["MATERIAL", "MAX QTY", "STORAGE", "LOCATION"],
                       [["PVC solvent cement", "4 qt", "Approved flammables cabinet",
                         "Warehouse"],
                        ["Construction adhesive", "12 tubes", "Approved cabinet",
                         "Warehouse"],
                        ["Pipe-thread sealant", "2 qt", "Approved cabinet", "Warehouse"],
                        ["Contact cleaner (aerosol)", "6 cans", "Approved cabinet",
                         "Vans"]])
        c.setFont(MONO, 7.2)
        c.drawString(LEFT, y - 4, "Limited quantities of common jobsite adhesives and "
                                  "solvents stored in approved containers.")
        c.drawString(LEFT, y - 4 - LEAD, "No explosives. No bulk chemical storage.")
    add(hazmat)

    # 21-22. Signed questionnaire, page 1 - X in a column, native text
    def questionnaire(c, w, h):
        y = _head(c, "UNDERWRITING QUESTIONNAIRE - SIGNED BY APPLICANT (page 1 of 2)",
                  w, h)
        c.setFont(BOLD, 7.0)
        c.drawString(LEFT, y, "#"); c.drawString(LEFT + 22, y, "QUESTION")
        c.drawString(LEFT + 330, y, "YES"); c.drawString(LEFT + 360, y, "NO")
        c.drawString(LEFT + 392, y, "APPLICANT'S STATEMENT")
        y -= LEAD * 1.4
        c.setFont(MONO, 6.6)
        for code, q in D.QUESTIONS.items():
            if q["scanned"]:
                continue
            c.drawString(LEFT, y, q["n"])
            c.drawString(LEFT + 22, y, q["q"][:62])
            for col in (330, 360):
                c.rect(LEFT + col, y - 2, 9, 9, stroke=1, fill=0)
            mark = 330 if q["answer"] == "Y" else 360
            c.drawString(LEFT + mark + 2, y, "X")
            c.drawString(LEFT + 392, y, q["stated"][:34])
            if len(q["stated"]) > 34:
                y -= LEAD
                c.drawString(LEFT + 392, y, q["stated"][34:70])
                if len(q["stated"]) > 70:
                    y -= LEAD
                    c.drawString(LEFT + 392, y, q["stated"][70:106])
            y -= LEAD * 1.6
        y -= LEAD
        c.setFont(MONO, 7.0)
        c.drawString(LEFT, y, "Questions 8 through 15 continue on page 2 "
                              "(signed original, scanned).")
    add(questionnaire)

    # 22. Signed questionnaire, page 2 - SCANNED, answers only here
    scanned(["UNDERWRITING QUESTIONNAIRE (page 2 of 2)",
             f"Applicant: {D.NAME}", ""]
            + sum([[f"{q['n']}. {q['q']}", f"    ANSWER: {q['answer']}   -  {q['stated']}"]
                   for q in D.QUESTIONS.values() if q["scanned"]], [])
            + ["", "I certify the above answers are true and complete.",
               "Signed: ______________________  Title: Managing Member",
               "Date: 08/14/2026"],
            skew=0.9, fax="FAX  303 555 0175  ->  SUMMIT COMMERCIAL   08/14/2026 16:42   P.2/2")

    # 23-26. Current GL declarations - teletype policy number, grid, forms list
    def gl_dec(c, w, h):
        y = _head(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS (CURRENT POLICY)", w, h)
        y = teletype_block(c, LEFT, y, [
            "POLICY NO  GL-123456",
            f"PERIOD  {D.CUR_EFF}  TO  {D.CUR_EXP}",
            "RENEWAL OF  GL-104471"])
        y -= 6
        c.setFont(MONO, 7.4)
        for ln in [f"Named insured: {D.NAME}",
                   f"Mailing address: {D.MAIL_L1}, {D.MAIL_CITY}, {D.MAIL_STATE} "
                   f"{D.MAIL_ZIP}",
                   f"Company: {D.CUR_CARRIER}   NAIC {D.CUR_CARRIER_NAIC}",
                   f"Agent: {D.PRODUCER}", "",
                   "Each occurrence $1,000,000   General aggregate $2,000,000",
                   "Products-completed operations aggregate $2,000,000",
                   "Personal and advertising injury $1,000,000",
                   "Damage to premises rented $300,000   Medical expense $10,000", "",
                   "Billing: Agency bill - Quarterly installments",
                   f"Total advance premium: {D.CURRENT_LINES[0]['premium']}"]:
            c.drawString(LEFT, y, ln); y -= LEAD
    add(gl_dec)
    def gl_class(c, w, h):
        y = _head(c, "CGL - SCHEDULE OF CLASSIFICATIONS (CURRENT POLICY GL-123456)", w, h)
        ruled_grid(c, LEFT, y, [40, 60, 220, 80, 90, 70], 13,
                   ["LOC", "CLASS", "DESCRIPTION", "BASIS", "EXPOSURE", "PREMIUM"],
                   [["1", D.GL_CODE, "Electrical Work - Within Buildings",
                     "Payroll", "$1,360,000", "$16,900"],
                    ["1", "--", "Products-completed operations", "Incl.", "--",
                     "Incl."]])
    add(gl_class)
    forms = [("CG 00 01 04 13", "Commercial General Liability Coverage Form"),
             ("CG 20 11 04 13", "Additional Insured - Managers or Lessors of Premises"),
             ("CG 21 47 12 07", "Employment-Related Practices Exclusion"),
             ("CG 21 06 05 14", "Exclusion - Access or Disclosure of Confidential Info"),
             ("CG 22 79 04 13", "Exclusion - Contractors - Professional Liability"),
             ("CG 24 04 05 09", "Waiver of Transfer of Rights of Recovery"),
             ("IL 00 17 11 98", "Common Policy Conditions"),
             ("IL 00 21 09 08", "Nuclear Energy Liability Exclusion"),
             ("CG 21 67 12 04", "Fungi or Bacteria Exclusion"),
             ("CG 21 73 01 15", "Exclusion of Certified Acts of Terrorism")]
    def gl_forms(c, w, h):
        y = _head(c, "CGL - FORMS AND ENDORSEMENTS (CURRENT POLICY)", w, h)
        ruled_grid(c, LEFT, y, [120, 360], 13, ["FORM", "TITLE"],
                   [list(f) for f in forms])
        c.setFont(MONO, 6.8)
        c.drawString(LEFT, y - 170, "CG 20 11: no additional insured is scheduled. "
                                    "Landlord endorsement not activated.")
    add(gl_forms)

    # 27-32. Current auto declarations
    def auto_dec(c, w, h):
        y = _head(c, "BUSINESS AUTO DECLARATIONS (CURRENT POLICY)", w, h)
        c.setFont(MONO, 7.4)
        for ln in [f"Policy BA-456789   Period {D.CUR_EFF} - {D.CUR_EXP}",
                   f"Company: {D.CUR_CARRIER}", "Covered autos: Liability symbol 1",
                   "Physical damage symbol 7", "Liability CSL $1,000,000",
                   "Uninsured motorists $1,000,000", "Medical payments $5,000",
                   f"Premium {D.CURRENT_LINES[1]['premium']}"]:
            c.drawString(LEFT, y, ln); y -= LEAD
    add(auto_dec)
    vehicles = [("2022", "Ford", "Transit 250", "1FTBR1C8XNKA1234"),
                ("2021", "Ford", "Transit 350", "1FTBW3XM4MKA2231"),
                ("2023", "RAM", "ProMaster 2500", "3C6LRVDG5PE501122"),
                ("2020", "Chevrolet", "Express 2500", "1GCWGAFP8L1203344"),
                ("2019", "Ford", "F-250", "1FT7W2B67KEE55667"),
                ("2024", "Ford", "F-350", "1FT8W3BT2REC77889"),
                ("2022", "Isuzu", "NPR-HD", "54DC4W1B7NS800112"),
                ("2021", "Chevrolet", "Silverado 2500", "1GC4YLE7XMF301234")]
    def auto_sched(c, w, h):
        y = _head(c, "SCHEDULE OF COVERED AUTOS (CURRENT POLICY BA-456789)", w, h)
        ruled_grid(c, LEFT, y, [22, 40, 70, 90, 130, 70, 110], 13,
                   ["#", "YEAR", "MAKE", "MODEL", "VIN", "COST NEW", "LIENHOLDER"],
                   [[str(i + 1), a, b, m, v, f"${38 + i * 4},900", "None"]
                    for i, (a, b, m, v) in enumerate(vehicles)])
    add(auto_sched)
    def drivers(c, w, h):
        y = _head(c, "DRIVER LIST (CURRENT POLICY BA-456789)", w, h)
        names = ["Anderson, K", "Baca, R", "Chen, L", "Diaz, M", "Evans, T",
                 "Fischer, J", "Garcia, A", "Hughes, P", "Ibarra, S", "Jensen, D",
                 "Kowalski, B", "Lopez, E", "Moore, C", "Nguyen, H", "Ortega, L"]
        ruled_grid(c, LEFT, y, [150, 60, 110, 70], 13,
                   ["DRIVER", "STATE", "LICENSE", "HIRED"],
                   [[n, "CO", f"CO-{900000 + i * 1371}", f"{2014 + i % 10}"]
                    for i, n in enumerate(names)])
    add(drivers)

    # 33-35. Current property declarations - the CIM / crime decoys
    def prop_dec(c, w, h):
        y = _head(c, "COMMERCIAL PROPERTY DECLARATIONS (CURRENT POLICY)", w, h)
        c.setFont(MONO, 7.4)
        for ln in [f"Policy CP-567890   {D.CUR_EFF} to {D.CUR_EXP}   {D.CUR_CARRIER}",
                   f"Premises: LOC 1  {D.LOC['l1']}, {D.LOC['city']} CO",
                   "Business personal property $385,000   Special form   RC   80% coins.",
                   "Deductible $2,500", "",
                   "COVERAGE EXTENSIONS ATTACHED TO THIS PROPERTY POLICY",
                   "  Contractors equipment (scheduled tools)      $240,000",
                   "  Installation floater                          $50,000",
                   "  Employee dishonesty (sublimit)                $10,000",
                   "  These are EXTENSIONS of the property form, not separate lines.", "",
                   f"Premium {D.CURRENT_LINES[2]['premium']}"]:
            c.drawString(LEFT, y, ln); y -= LEAD
    add(prop_dec)

    # 36-37. Current umbrella - WC underlying with a THIRD carrier
    def umb_dec(c, w, h):
        y = _head(c, "COMMERCIAL UMBRELLA DECLARATIONS (CURRENT POLICY)", w, h)
        c.setFont(MONO, 7.4)
        for ln in [f"Policy CU-678901   {D.CUR_EFF} - {D.CUR_EXP}   {D.CUR_CARRIER}",
                   "Each occurrence $2,000,000   Aggregate $2,000,000   SIR $10,000",
                   f"Premium {D.CURRENT_LINES[3]['premium']}",
                   f"Total current programme premium (GL, Auto, Property, Umbrella): "
                   f"{D.CUR_TOTAL_PREMIUM}", "",
                   "SCHEDULE OF UNDERLYING INSURANCE"]:
            c.drawString(LEFT, y, ln); y -= LEAD
        ruled_grid(c, LEFT, y, [140, 170, 90, 120], 13,
                   ["LINE", "CARRIER", "POLICY", "LIMITS"],
                   [["General Liability", D.CUR_CARRIER_SHORT, "GL-123456",
                     "$1M / $2M"],
                    ["Business Auto", D.CUR_CARRIER_SHORT, "BA-456789", "$1M CSL"],
                    ["Employers Liability", "Pinecrest Employers", D.WC_POLICY,
                     "$1M / $1M / $1M"]])
    add(umb_dec)
    plain("WORKERS COMPENSATION - SUMMARY (NOT PART OF THIS SUBMISSION)", [
        f"Carrier: {D.WC_CARRIER}", f"Policy: {D.WC_POLICY}   "
        f"{D.CUR_EFF} - {D.CUR_EXP}", f"Estimated annual premium: {D.WC_PREMIUM}",
        "Class 5190 Electrical Wiring - Within Buildings", "",
        "Workers compensation is placed separately and is not being marketed.",
    ])

    # 39-43. Loss runs - four native, one old FAXED copy of the auto run
    for line in ("GENERAL LIABILITY", "COMMERCIAL PROPERTY", "COMMERCIAL UMBRELLA"):
        def lr(c, w, h, line=line):
            y = _head(c, f"LOSS RUN - {line} - valued {D.LOSS_VALUED}", w, h)
            ruled_grid(c, LEFT, y, [140, 110, 110, 110], 13,
                       ["TERM", "CLAIMS", "PAID", "RESERVED"],
                       [[f"10/01/{yr} - 10/01/{yr + 1}", "0", "$0", "$0"]
                        for yr in range(2021, 2026)])
        add(lr)
    def lr_auto(c, w, h):
        y = _head(c, f"LOSS RUN - BUSINESS AUTO - valued {D.LOSS_VALUED}", w, h)
        c.setFont(MONO, 7.0)
        c.drawString(LEFT, y, "Five policy years 10/01/2021 - 10/01/2026. One claim."
                              "  Supersedes all earlier valuations."); y -= LEAD * 1.6
        y = riffled(c, y, ["CLAIM", "DOL", "REPORTED", "DESCRIPTION", "PAID",
                           "RESERVE", "SUB", "STATUS"],
                    [[D.LOSS["claim_no"], D.LOSS["occurrence"], D.LOSS["claim"],
                      D.LOSS["desc"], D.LOSS["paid"], D.LOSS["reserved"],
                      D.LOSS["subro"], "CLOSED"]],
                    [LEFT, LEFT + 62, LEFT + 116, LEFT + 170, LEFT + 336,
                     LEFT + 380, LEFT + 424, LEFT + 446], size=6.6)
        y -= 8
        c.setFont(MONO, 7.0)
        c.drawString(LEFT, y, f"TOTAL PAID {D.TOTAL_PAID}   TOTAL RESERVED $0   "
                              f"TOTAL INCURRED {D.TOTAL_PAID}")
    add(lr_auto)
    scanned([f"{D.CUR_CARRIER.upper()} - LOSS RUN", "BUSINESS AUTO",
             f"VALUED AS OF {D.LOSS_OLD['valued']}", "",
             "CLAIM        DOL        DESCRIPTION                     PAID    RESERVE  STATUS",
             f"{D.LOSS['claim_no']}  {D.LOSS['occurrence']} Insd veh rear-ended 3rd party "
             f"{D.LOSS_OLD['paid']}  {D.LOSS_OLD['reserved']}  OPEN", "",
             "THIS LOSS RUN IS VALUED AS SHOWN ABOVE."],
            skew=1.4, quality="fax",
            fax="FAX  800 555 0147  TIMBERLINE MUTUAL CLAIMS   07/02/2024 09:11   P.1/1")

    # 44. Lease summary - the landlord is not an interest on any policy
    plain("LEASE SUMMARY", [
        f"Landlord: {D.LANDLORD}", f"Landlord address: {D.LANDLORD_ADDR}",
        f"Landlord phone: {D.LANDLORD_PHONE}",
        f"Tenant: {D.NAME}", f"Premises: {D.LOC['l1']}, Suite occupied 5,000 SF of 15,000 SF",
        "Term: 06/01/2019 - 05/31/2029", "",
        "The lease requires the tenant to carry liability insurance. It does not",
        "require the landlord to be named as an additional insured, loss payee or",
        "any other interest, and none has been scheduled on any policy.",
    ])

    # 45-46. Scanned formation documents and W-9
    scanned(["STATE OF COLORADO - SECRETARY OF STATE",
             "ARTICLES OF ORGANIZATION - LIMITED LIABILITY COMPANY", "",
             f"Entity name: {D.NAME}", f"Date of formation: {D.START_DATE}",
             "Principal office: 8000 Commerce Way, Denver, CO 80216",
             "Management: member-managed", "", "Filed electronically."],
            skew=-0.6)
    scanned(["Form W-9 (Rev. March 2024)",
             "Request for Taxpayer Identification Number and Certification", "",
             f"1 Name: {D.NAME}", "3 Federal tax classification: LLC (partnership)",
             f"5 Address: {D.MAIL_L1}", f"6 City, state, ZIP: {D.MAIL_CITY}, "
             f"{D.MAIL_STATE} {D.MAIL_ZIP}", "",
             f"Employer identification number: {D.FEIN}"],
            skew=0.5)

    # 47-49. Fleet maintenance log - noise
    for part in range(3):
        def maint(c, w, h, part=part):
            y = _head(c, f"FLEET MAINTENANCE LOG ({part + 1} of 3)", w, h)
            ruled_grid(c, LEFT, y, [22, 80, 70, 170, 80, 70], 12,
                       ["#", "DATE", "UNIT", "SERVICE", "ODOMETER", "COST"],
                       [[str(i + 1), f"{(i % 12) + 1:02d}/{(i % 27) + 1:02d}/2026",
                         f"V-{(i % 8) + 1}", ["Oil change", "Brakes", "Tyres",
                                             "Inspection", "Battery"][i % 5],
                         f"{41000 + i * 1337:,}", f"${120 + (i * 37) % 900}"]
                        for i in range(part * 30, part * 30 + 30)])
        add(maint)

    # 50-51. Tools and equipment - the inland-marine decoy
    def tools(c, w, h):
        y = _head(c, "TOOLS AND EQUIPMENT (covered as a PROPERTY extension)", w, h)
        ruled_grid(c, LEFT, y, [200, 90, 90, 100], 13,
                   ["ITEM", "QTY", "VALUE", "SERIAL"],
                   [["Cable puller 8000 lb", "2", "$18,400", "CP-22901"],
                    ["Trencher, walk-behind", "1", "$11,200", "TR-1180"],
                    ["Scissor lift 19 ft", "2", "$29,000", "SL-4471"],
                    ["Conduit bender set", "6", "$9,600", "--"],
                    ["Thermal camera", "3", "$7,800", "TC-310"],
                    ["Generator 7 kW", "2", "$6,400", "GN-7K"]])
    add(tools)

    table_noise()


def _two_line_header(c, y, heads: List[Tuple[str, str]], xs: List[float]) -> float:
    """A header printed on TWO lines ("CONTRACT" over "VALUE"): the lower word
    sits alone on its line and belongs to nothing a reader sorting by y sees."""
    c.setFont(BOLD, 6.8)
    for (top, bottom), x in zip(heads, xs):
        c.drawString(x, y, top)
        if bottom:
            c.drawString(x, y - 8, bottom)
    return y - 8 - LEAD


def table_noise() -> None:
    """Tables a real contractor's package carries, each one a trap."""
    H = D.CERT_HOLDERS
    for part in range(2):
        rows = H[part * 14:(part + 1) * 14]
        def certs(c, w, h, rows=rows, part=part):
            y = _head(c, f"CERTIFICATES OF INSURANCE ISSUED - LOG ({part + 1} of 2)", w, h)
            y = ruled_grid(c, LEFT, y, [40, 160, 130, 80, 40, 60, 40], 13,
                           ["CERT", "HOLDER", "ADDRESS", "CITY", "ZIP", "ISSUED",
                            "TYPE"],
                           [[f"C-{2400 + part * 14 + i}", n, a, ci, z,
                             f"{(i % 12) + 1:02d}/{(i * 3) % 27 + 1:02d}/2026",
                             "CERT"] for i, (n, a, ci, z) in enumerate(rows)])
            c.setFont(MONO, 6.8)
            c.drawString(LEFT, y - 6, "Certificates are evidence of insurance only. "
                                      "No holder is an additional insured, loss")
            c.drawString(LEFT, y - 6 - LEAD, "payee, mortgagee or any other interest "
                                             "on any policy of the named insured.")
        add(certs)

    for part in range(2):
        rows = D.WIP[part * 9:(part + 1) * 9]
        def wip(c, w, h, rows=rows, part=part):
            y = _head(c, f"WORK IN PROGRESS SCHEDULE AS OF 08/31/2026 ({part + 1} of 2)",
                      w, h)
            xs = [LEFT, LEFT + 50, LEFT + 230, LEFT + 310, LEFT + 390]
            y = _two_line_header(c, y, [("JOB", "NO."), ("PROJECT", ""),
                                        ("CONTRACT", "VALUE"), ("BILLED TO", "DATE"),
                                        ("PCT", "COMPLETE")], xs)
            c.setFont(MONO, 6.9)
            for r in rows:
                for x, cell in zip(xs, r):
                    c.drawString(x, y, cell)
                y -= LEAD
            if part == 1:
                y -= 6
                c.setFont(BOLD, 7.0)
                c.drawString(LEFT, y, f"TOTAL CONTRACT VALUE (BACKLOG)  {D.WIP_BACKLOG}")
                c.setFont(MONO, 6.8)
                c.drawString(LEFT, y - LEAD, "Contract value is not revenue; revenue is "
                                             "recognised as work is performed.")
        add(wip)

    def monthly(c, w, h):
        y = _head(c, "REVENUE BY MONTH - FISCAL YEAR 2025 (OCT 2024 - SEP 2025)", w, h)
        y = ruled_grid(c, LEFT, y, [120, 110], 13, ["MONTH", "REVENUE"],
                       [list(r) for r in D.MONTHLY_REVENUE_FY2025]
                       + [["FY2025 TOTAL", D.LOC["revenue"]]])
        c.setFont(MONO, 6.8)
        c.drawString(LEFT, y - 4, "FY2026 year to date (Oct 2025 - Aug 2026): "
                                  "$4,190,000 - full-year projection $4,610,000.")
    add(monthly)

    def payroll(c, w, h):
        y = _head(c, "PAYROLL REGISTER - CALENDAR 2025 (GROSS WAGES)", w, h)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                  "Oct", "Nov", "Dec"]
        per = [128_400, 124_900, 131_200, 136_800, 141_700, 143_300, 145_900,
               146_200, 139_500, 136_100, 132_400, 133_600]
        ruled_grid(c, LEFT, y, [70, 90, 90, 90, 90], 13,
                   ["MONTH", "FIELD", "APPRENTICE", "OFFICE", "TOTAL"],
                   [[m, f"${round(p * .70):,}", f"${round(p * .13):,}",
                     f"${p - round(p * .70) - round(p * .13):,}", f"${p:,}"]
                    for m, p in zip(months, per)]
                   + [["TOTAL", "", "", "", f"${sum(per):,}"]])
    add(payroll)

    def aging(c, w, h):
        y = _head(c, "ACCOUNTS RECEIVABLE AGING AS OF 08/31/2026", w, h)
        ruled_grid(c, LEFT, y, [190, 70, 70, 70, 70, 70], 13,
                   ["CUSTOMER", "CURRENT", "31-60", "61-90", "90+", "TOTAL"],
                   [[n, f"${(i * 7919) % 90000 + 4000:,}", f"${(i * 3331) % 20000:,}",
                     "$0" if i % 3 else f"${(i * 911) % 9000:,}", "$0",
                     "see detail"] for i, (n, *_r) in enumerate(D.CERT_HOLDERS[:16])])
    add(aging)

    courses = ["OSHA 10 Construction", "NFPA 70E Arc Flash", "Fall Protection",
               "Lockout / Tagout", "First Aid / CPR", "Aerial Lift Operator",
               "Confined Space Awareness", "Trenching Awareness"]
    for part in range(2):
        def training(c, w, h, part=part):
            y = _head(c, f"SAFETY TRAINING LOG - 2025/2026 ({part + 1} of 2)", w, h)
            ruled_grid(c, LEFT, y, [70, 170, 80, 150], 12,
                       ["EMP ID", "COURSE", "DATE", "TRAINER"],
                       [[f"E-{100 + (i % 20)}", courses[i % len(courses)],
                         f"{(i % 12) + 1:02d}/{(i * 7) % 27 + 1:02d}/"
                         f"{2025 + (i // 24)}",
                         D.SAFETY_MANAGER if i % 3 else "Mile High Safety Training"]
                        for i in range(part * 30, part * 30 + 30)])
        add(training)

    def bids(c, w, h):
        y = _head(c, "BID LOG - 2026", w, h)
        ruled_grid(c, LEFT, y, [50, 200, 90, 80, 80], 13,
                   ["BID", "OWNER / GC", "BID AMOUNT", "DUE", "RESULT"],
                   [[f"B-{610 + i}", n, f"${(i * 45_311) % 900_000 + 60_000:,}",
                     f"{(i % 8) + 1:02d}/15/2026", ["WON", "LOST", "PENDING"][i % 3]]
                    for i, (n, *_r) in enumerate(D.CERT_HOLDERS[8:24])])
    add(bids)

    def depreciation(c, w, h):
        y = _head(c, "FIXED ASSET / DEPRECIATION SCHEDULE (BOOK)", w, h)
        ruled_grid(c, LEFT, y, [190, 60, 80, 80, 80], 13,
                   ["ASSET", "IN SVC", "COST", "ACCUM DEPR", "NET BOOK"],
                   [["Vehicles (8)", "2019-24", "$412,600", "$198,300", "$214,300"],
                    ["Tools and equipment", "2016-26", "$240,000", "$131,000",
                     "$109,000"],
                    ["Office furniture", "2019", "$38,200", "$27,300", "$10,900"],
                    ["Computers and software", "2023-26", "$46,800", "$22,100",
                     "$24,700"],
                    ["Leasehold improvements", "2019", "$96,000", "$67,200",
                     "$28,800"]])
    add(depreciation)


def _wrap(text: str, width: int) -> List[str]:
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


_WORDING = [
    "SECTION I - COVERAGES. We will pay those sums that the insured becomes legally",
    "obligated to pay as damages because of bodily injury or property damage to",
    "which this insurance applies. We will have the right and duty to defend the",
    "insured against any suit seeking those damages. However, we will have no duty",
    "to defend the insured against any suit seeking damages for bodily injury or",
    "property damage to which this insurance does not apply. We may, at our",
    "discretion, investigate any occurrence and settle any claim or suit that may",
    "result. The amount we will pay for damages is limited as described in Section",
    "III - Limits Of Insurance. Our right and duty to defend ends when we have used",
    "up the applicable limit of insurance in the payment of judgments or",
    "settlements. No other obligation or liability to pay sums or perform acts or",
    "services is covered unless explicitly provided for under Supplementary",
    "Payments. This insurance applies to bodily injury and property damage only if",
    "the bodily injury or property damage is caused by an occurrence that takes",
    "place in the coverage territory and occurs during the policy period.",
    "EXCLUSIONS. This insurance does not apply to expected or intended injury,",
    "contractual liability, liquor liability, workers compensation and similar",
    "laws, employer's liability, pollution, aircraft, auto or watercraft, mobile",
    "equipment, war, damage to property, damage to your product, damage to your",
    "work, damage to impaired property, recall of products, personal and",
    "advertising injury, electronic data, or distribution of material in",
    "violation of statutes. Cyber incidents, crime and fiduciary acts are not",
    "covered and no such line is afforded under this policy.",
]


def pad_to_target() -> None:
    n = 0
    while len(PAGES) < TARGET_PAGES:
        n += 1
        form = ["CG 00 01 04 13", "IL 00 17 11 98", "CA 00 01 10 13",
                "CP 00 10 10 12", "CU 00 01 12 07"][n % 5]
        def draw(c, w, h, n=n, form=form):
            y = _head(c, f"POLICY WORDING - {form} - PAGE {n}", w, h)
            c.setFont(MONO, 6.9)
            for i in range(58):
                c.drawString(LEFT, y, _WORDING[(i + n) % len(_WORDING)])
                y -= 10.2
            c.setFont(MONO, 6.2)
            c.drawString(LEFT, 26, f"{form}   Copyright ISO Properties, Inc.")
        add(draw)


def render() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    c = canvas.Canvas(str(PDF_PATH), pagesize=LETTER)
    c.setTitle(f"{D.NAME} - submission package")
    for i, (draw, wide) in enumerate(PAGES, start=1):
        size = landscape(LETTER) if wide else LETTER
        c.setPageSize(size)
        draw(c, size[0], size[1])
        c.setFont(MONO, 6.2)
        c.drawString(size[0] - 110, 16, f"Page {i} of {len(PAGES)}")
        c.showPage()
    c.save()
    return len(PAGES)


# ═════════════════════════════════════════════════════════════════════════════
# The answer key - one verdict for every one of the 548 fields
# ═════════════════════════════════════════════════════════════════════════════
V_EXPECT, V_NO_DATA, V_BY_RULE = "expect", "blank_no_data", "blank_by_rule"
V_NA, V_NOT_SCORED = "not_applicable", "not_scored"
FIELDS: Dict[str, dict] = {}


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


def _na_rows(prefix_letters: List[str], why: str, trap: str = "") -> None:
    for f in prefix_letters:
        _put(f, V_NA, "", why, trap)


ACCOUNT_WHY = ("resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded "
               "document - scored manually against the account, not by this key")


def build_key() -> dict:
    schema = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json")
                        .read_text(encoding="utf-8"))
    FIELDS.clear()
    Q, L = D.QUESTIONS, D.LOC

    # ── FORM ─────────────────────────────────────────────────────────────────
    _put("Form_EditionIdentifier_A", V_EXPECT, "ACORD 125 (2025/03)",
         "the client asks for FORM-EDITION validation; 2025/03 is current")
    _put("Form_CompletionDate_A", V_NOT_SCORED, "", "the generation date")

    # ── PRODUCER - the logged-in agency, and another agency's identifiers ────
    for f, v in (("Producer_FullName_A", D.PRODUCER),
                 ("Producer_MailingAddress_LineOne_A", D.PRODUCER_L1),
                 ("Producer_MailingAddress_LineTwo_A", D.PRODUCER_L2),
                 ("Producer_MailingAddress_CityName_A", D.PRODUCER_CITY),
                 ("Producer_MailingAddress_StateOrProvinceCode_A", D.PRODUCER_STATE),
                 ("Producer_MailingAddress_PostalCode_A", D.PRODUCER_ZIP),
                 ("Producer_ContactPerson_FullName_A", D.PRODUCER_CONTACT),
                 ("Producer_ContactPerson_PhoneNumber_A", D.PRODUCER_PHONE),
                 ("Producer_ContactPerson_EmailAddress_A", D.PRODUCER_EMAIL),
                 ("Producer_AuthorizedRepresentative_FullName_A", D.PRODUCER_CONTACT)):
        _put(f, V_NOT_SCORED, v, ACCOUNT_WHY)
    _put("Producer_FaxNumber_A", V_NO_DATA, "", "the documents print no producer fax")
    _put("Producer_CustomerIdentifier_A", V_BY_RULE, "",
         "client: 'populate only if verified from agency/AMS'. FREC-001 is printed by "
         "Summit, which is not the logged-in agency",
         trap=f"must not be {D.AGENCY_CUSTOMER_ID}")
    for f in ("Producer_NationalIdentifier_A", "Producer_StateLicenseIdentifier_A"):
        _put(f, V_NO_DATA, "", "lives in the agency profile, never in an upload")
    _put("Producer_AuthorizedRepresentative_Signature_A", V_BY_RULE, "",
         "AUTHORSHIP: a machine never signs for the producer")

    # ── INSURER - the carrier RECEIVING the submission ───────────────────────
    _put("Insurer_FullName_A", V_EXPECT, D.CARRIER,
         "client: 'Example carrier receiving submission' - named on the cover letter",
         trap=f"must not be {D.CUR_CARRIER} (the CURRENT carrier)")
    _put("Insurer_NAICCode_A", V_NO_DATA, "",
         "client: 'Only populate if carrier/NAIC is verified' - the receiving "
         "carrier's NAIC is printed nowhere",
         trap=f"must not be {D.CUR_CARRIER_NAIC} (the current carrier's)")
    _put("Insurer_Underwriter_FullName_A", V_EXPECT, D.UNDERWRITER,
         "client: 'Named underwriter if submission is directed to one'")
    _put("Insurer_Underwriter_OfficeIdentifier_A", V_EXPECT, D.UNDERWRITER_OFFICE)
    for f in ("Insurer_ProducerIdentifier_A", "Insurer_SubProducerIdentifier_A"):
        _put(f, V_NO_DATA, "", "client: 'Populate only if verified from agency/AMS'")
    for f in ("Insurer_ProductCode_A", "Insurer_ProductDescription_A"):
        _put(f, V_NO_DATA, "", "no programme is named")

    # ── POLICY - the policy being APPLIED FOR ────────────────────────────────
    _put("Policy_EffectiveDate_A", V_EXPECT, D.PROPOSED_EFF,
         trap=f"must not be {D.CUR_EFF}")
    _put("Policy_ExpirationDate_A", V_EXPECT, D.PROPOSED_EXP,
         trap=f"must not be {D.CUR_EXP}")
    _put("Policy_PolicyNumberIdentifier_A", V_NO_DATA, "",
         "client: 'Blank for new-business quote unless an existing/current policy "
         "number applies'", trap="must not take GL-123456 or a form number")
    _tick("Policy_Status_QuoteIndicator_A", True, "client: 'Status: QUOTE'")
    for st in ("Issue", "Bound", "Change", "Cancel", "Renew"):
        _tick(f"Policy_Status_{st}Indicator_A", False,
              "the only status stated is a quote",
              trap="the current decs print 'RENEWAL OF' - that is the old policy")
    for f in ("Policy_Status_EffectiveDate_A", "Policy_Status_EffectiveTime_A"):
        _put(f, V_NO_DATA, "", "for bound / change / cancel, not a quote")
    _tick("Policy_Status_EffectiveTimeAMIndicator_A", False)
    _tick("Policy_Status_EffectiveTimePMIndicator_A", False)
    for k, name in (("CommercialGeneralLiability", "CGL"),
                    ("CommercialProperty", "Commercial Property"),
                    ("BusinessAutoIndicator", "Business Auto"),
                    ("UmbrellaIndicator", "Umbrella")):
        _tick(f"Policy_LineOfBusiness_{k}_A", True, f"client: {name} ticked")
    for k in ("BoilerAndMachineryIndicator", "BusinessOwnersIndicator",
              "CrimeIndicator", "CyberAndPrivacy", "FiduciaryLiabilityIndicator",
              "GarageAndDealersIndicator", "LiquorLiabilityIndicator",
              "MotorCarrierIndicator", "TruckersIndicator", "YachtIndicator",
              "CommercialInlandMarineIndicator"):
        _tick(f"Policy_LineOfBusiness_{k}_A", False,
              "client: 'Other LOB boxes: Blank'",
              trap="inland marine / crime are EXTENSIONS on the property form; the "
                   "cover letter names cyber, crime, liquor only to decline them")
    for ch in "ABCDEF":
        _put(f"Policy_LineOfBusiness_OtherIndicator_{ch}", V_NO_DATA, "",
             trap="workers comp is not being applied for")
        _put(f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{ch}", V_NO_DATA)
    for b in ("BoilerAndMachinery", "BusinessOwners", "CommercialInlandMarine",
              "CommercialProperty", "CommercialVehicle", "CommercialUmbrella", "Crime",
              "CyberAndPrivacy", "Fiduciary", "GarageAndDealers", "LiquorLiability",
              "MotorCarrier", "Truckers", "Yacht"):
        _put(f"{b}LineOfBusiness_PremiumAmount_A", V_BY_RULE, "",
             "client: 'Policy Premium: Blank at submission stage unless known'")
    _put("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", V_BY_RULE, "",
         "a quote is not priced", trap="must not be $18,450")
    _put("Policy_Payment_EstimatedTotalAmount_A", V_BY_RULE, "",
         "a quote is not priced", trap=f"must not be {D.CUR_TOTAL_PREMIUM}")
    _tick("Policy_Payment_DirectBillIndicator_A", True,
          "client: 'Billing Plan: Direct, if known' - the cover letter states it",
          trap="the CURRENT GL dec says Agency bill - that is the old policy")
    _tick("Policy_Payment_ProducerBillIndicator_A", False,
          "billing is Direct", trap="the current dec says Agency bill")
    _put("Policy_Payment_PaymentScheduleCode_A", V_EXPECT, D.PAYMENT_PLAN_CODE,
         "client: 'Payment Plan: Annual, if requested/known'. ACORD tooltip: "
         "'AN - Annual, MO - Monthly' - the box takes the CODE",
         trap="the current dec says Quarterly installments")
    for f in ("Policy_Payment_DepositAmount_A", "Policy_Payment_MinimumPremiumAmount_A"):
        _put(f, V_BY_RULE, "", "a quote is not priced")
    _put("Policy_PaymentMethod_MethodDescription_A", V_NO_DATA, "",
         "no method of payment is stated")
    _put("Policy_Audit_FrequencyCode_A", V_NO_DATA, "",
         "no audit term is printed anywhere in the package")
    _put("Policy_InformationPracticesNoticeIndicator_A", V_BY_RULE, "",
         "AUTHORSHIP: an attestation that the agency did something")

    # attachments name what OUR package contains - this kit generates 125 alone
    # VEHICLE SCHEDULE is DISPUTED, so it is not scored (28 Sep): the owner's
    # principle ("about our own package - derive it from what we generate") and
    # the client's driver-box instruction say blank on a 125-only package; an
    # early Orbin "do not regress" list (which also kept two values since
    # overturned) says tick. Owner decision pending - see improving125-21sep.md.
    _put("Policy_SectionAttached_VehicleScheduleIndicator_A", V_NOT_SCORED, "",
         "disputed: package principle vs the Orbin 'do not regress' list")
    for k in ("AccountsReceivableValuablePapersIndicator", "DealerIndicator",
              "ElectronicDataProcessingIndicator", "GlassAndSignIndicator",
              "InstallationBuildersRiskIndicator", "OpenCargoIndicator",
              "DriverInformationScheduleIndicator"):
        _put(f"Policy_SectionAttached_{k}_A", V_BY_RULE, "",
             "only ACORD 125 is generated", trap="the broker's checklist lists a "
             "vehicle and driver schedule for ITS submission, not ours")
    for ch in "ABCDEF":
        _put(f"Policy_SectionAttached_OtherPremiumAmount_{ch}", V_BY_RULE, "",
             "a quote is not priced")
    for k in ("ContractorsSupplementIndicator", "StatementOfValuesIndicator",
              "LossSummaryIndicator", "AdditionalInterestScheduleIndicator",
              "AdditionalPremisesScheduleIndicator",
              "ApartmentBuildingSupplementIndicator",
              "CondominiumAssociationByLawsIndicator", "CoveragesScheduleIndicator",
              "HotelMotelSupplementIndicator",
              "InternationalLiabilityExposureSupplementIndicator",
              "InternationalPropertyExposureSupplementIndicator",
              "PremiumPaymentSupplementIndicator",
              "ProfessionalLiabilitySupplementIndicator",
              "RestaurantTavernSupplementIndicator", "StateSupplementIndicator",
              "VacantBuildingSupplementIndicator"):
        _put(f"CommercialPolicy_Attachment_{k}_A", V_BY_RULE, "",
             "only ACORD 125 is generated")
    for ch in "ABCDEF":
        _put(f"CommercialPolicy_Attachment_OtherIndicator_{ch}", V_NO_DATA)
        _put(f"CommercialPolicy_Attachment_OtherDescription_{ch}", V_NO_DATA)

    # ── THE FIFTEEN QUESTIONS - the client's answers ─────────────────────────
    for code, q in Q.items():
        _put(f"CommercialPolicy_Question_{code}Code_A", V_EXPECT, q["answer"],
             f"client: question {q['n']} = {q['answer']}; the document states it",
             source="scanned" if q["scanned"] else "text")
    _put("CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A",
         V_EXPECT, Q["ABC"]["stated"],
         "client: 'Y - limited quantities of common jobsite adhesives/solvents "
         "stored in approved containers' (graded on MEANING)")
    for f in ("CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A",
              "CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A",
              "CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A",
              "CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A",
              "CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A"):
        _put(f, V_NO_DATA, "", "the answer is N - a No needs no explanation",
             trap="the stated sentence is evidence for the N, not an explanation")
    for blk in ("ForeclosureRepossessionBankruptcy", "JudgementOrLien",
                "UncorrectedFireCodeViolation"):
        for ch in "AB":
            for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate",
                        "_ResolutionDescription"):
                _put(f"CommercialPolicy_{blk}{suf}_{ch}", V_NO_DATA, "",
                     "the question is answered N - the block stays empty")
    _tick("CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A", True,
          "client: 'written safety manual'")
    _tick("CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B", True,
          "client: 'designated safety manager'")
    _tick("CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B", True,
          "client: 'monthly meetings'")
    _tick("CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B", False,
          "no statement that the programme meets OSHA guidelines",
          trap="an OSHA 300A LOG is record-keeping, not a programme element")
    _tick("CommercialPolicy_FormalSafetyProgram_OtherIndicator_B", False,
          "'No other element is claimed'")
    _put("CommercialPolicy_FormalSafetyProgram_OtherDescription_B", V_NO_DATA)
    _put("CommercialPolicy_OperationsDescription_A", V_EXPECT, D.PRIMARY_OPERATIONS,
         "client: 'Description of Primary Operations' (graded on MEANING)",
         trap="must not be the premises description of operations")
    _put("CommercialPolicy_OperationsDescription_B", V_NO_DATA, "",
         "client: 'Other Named Insured Operations: Blank'")
    _put("CommercialPolicy_RemarkText_A", V_NO_DATA, "", "no remark is stated")

    # ── NAMED INSURED row A; rows B and C have no entity ─────────────────────
    _put("NamedInsured_FullName_A", V_EXPECT, D.NAME)
    _put("NamedInsured_TaxIdentifier_A", V_EXPECT, D.FEIN,
         trap="must not be the CO tax account (8 digits) or the USDOT (7 digits)")
    _put("NamedInsured_SICCode_A", V_EXPECT, D.SIC)
    _put("NamedInsured_NAICSCode_A", V_EXPECT, D.NAICS,
         trap=f"must not be the GL class {D.GL_CODE}")
    _put("NamedInsured_GeneralLiabilityCode_A", V_EXPECT, D.GL_CODE,
         "client: 'Populate only from verified classification/rating source' - the "
         "GL declarations' classification schedule is that source")
    _put("NamedInsured_Primary_PhoneNumber_A", V_EXPECT, D.BUS_PHONE,
         trap="must not be the producer's, the carrier's or the landlord's number")
    _put("NamedInsured_Primary_WebsiteAddress_A", V_EXPECT, D.WEBSITE,
         trap=f"must not be {D.CUR_CARRIER_WEB}")
    _put("NamedInsured_MailingAddress_LineOne_A", V_EXPECT, D.MAIL_L1)
    _put("NamedInsured_MailingAddress_LineTwo_A", V_NO_DATA, "",
         "the address has no second line - the profile prints '--'",
         trap="a placeholder must never reach the box")
    _put("NamedInsured_MailingAddress_CityName_A", V_EXPECT, D.MAIL_CITY)
    _put("NamedInsured_MailingAddress_StateOrProvinceCode_A", V_EXPECT, D.MAIL_STATE)
    _put("NamedInsured_MailingAddress_PostalCode_A", V_EXPECT, D.MAIL_ZIP)
    _put("NamedInsured_LegalEntity_MemberManagerCount_A", V_NO_DATA, "",
         "the profile prints '--'", trap="a placeholder must never reach the box")
    ents = ["CorporationIndicator", "IndividualIndicator", "JointVentureIndicator",
            "LimitedLiabilityCorporationIndicator", "NotForProfitIndicator",
            "OtherIndicator", "PartnershipIndicator",
            "SubchapterSCorporationIndicator", "TrustIndicator"]
    for e in ents:
        _tick(f"NamedInsured_LegalEntity_{e}_A",
              e == "LimitedLiabilityCorporationIndicator", "client: '☒ LLC'",
              trap="the W-9 says the LLC is taxed as a partnership - the legal "
                   "entity is still an LLC")
    _put("NamedInsured_LegalEntity_OtherDescription_A", V_NO_DATA)
    for ch in "BC":
        cols = ["FullName", "TaxIdentifier", "SICCode", "NAICSCode",
                "GeneralLiabilityCode", "Primary_PhoneNumber",
                "Primary_WebsiteAddress", "MailingAddress_LineOne",
                "MailingAddress_LineTwo", "MailingAddress_CityName",
                "MailingAddress_StateOrProvinceCode", "MailingAddress_PostalCode",
                "LegalEntity_MemberManagerCount", "LegalEntity_OtherDescription"]
        _na_rows([f"NamedInsured_{k}_{ch}" for k in cols]
                 + [f"NamedInsured_LegalEntity_{e}_{ch}" for e in ents],
                 "client: 'Other Named Insured: Blank - no other named insured "
                 "supported by source'",
                 trap="the landlord, the subcontractors and the WC carrier are not "
                      "named insureds")
    _put("NamedInsured_BusinessStartDate_A", V_EXPECT, D.START_DATE,
         "stated as 'June 15, 2014', '2014-06-15' and (scanned) '06/15/2014'",
         trap="the 2019 relocation date is not the start date")
    for i, ch in enumerate("AB"):
        ct = D.CONTACTS[i]
        _put(f"NamedInsured_Contact_ContactDescription_{ch}", V_EXPECT, ct["type"])
        _put(f"NamedInsured_Contact_FullName_{ch}", V_EXPECT, ct["name"])
        _put(f"NamedInsured_Contact_PrimaryPhoneNumber_{ch}", V_EXPECT, ct["phone"])
        _put(f"NamedInsured_Contact_PrimaryEmailAddress_{ch}", V_EXPECT, ct["email"])
        for k in ("PrimaryBusinessPhoneIndicator", "PrimaryCellPhoneIndicator",
                  "PrimaryHomePhoneIndicator", "SecondaryBusinessPhoneIndicator",
                  "SecondaryCellPhoneIndicator", "SecondaryHomePhoneIndicator"):
            _tick(f"NamedInsured_Contact_{k}_{ch}", False,
                  "no phone type is stated for either contact")
        _put(f"NamedInsured_Contact_SecondaryPhoneNumber_{ch}", V_NO_DATA, "",
             "the source prints 'N/A' / '(none)'",
             trap="must not take the OTHER contact's number, or the placeholder")
        _put(f"NamedInsured_Contact_SecondaryEmailAddress_{ch}", V_NO_DATA)
    for f in ("NamedInsured_Initials_A", "NamedInsured_Signature_A",
              "NamedInsured_SignatureDate_A"):
        _put(f, V_BY_RULE, "", "AUTHORSHIP: the insured signs, not the machine",
             trap="the scanned questionnaire is dated 08/14/2026 - that is THAT "
                  "document's signature, not the application's")

    # ── BUSINESS INFORMATION ─────────────────────────────────────────────────
    _tick("BusinessInformation_BusinessType_ContractorIndicator_A", True,
          "client: '☒ Contractor'")
    for k in ("ApartmentsIndicator", "CondominiumsIndicator", "InstitutionalIndicator",
              "ManufacturingIndicator", "OfficeIndicator", "OtherIndicator",
              "RestaurantIndicator", "RetailIndicator", "ServiceIndicator",
              "WholesaleIndicator"):
        _tick(f"BusinessInformation_BusinessType_{k}_A", False,
              "one nature of business is stated",
              trap="'office', 'warehouse', 'service' and 'retail' all appear in prose")
    _put("BusinessInformation_BusinessType_OtherDescription_A", V_NO_DATA)
    _put("BusinessInformation_ParentOrganizationName_A", V_NO_DATA, "",
         "question 1a is N - there is no parent")
    _put("BusinessInformation_FullTimeEmployeeCount_A", V_EXPECT, L["ft"],
         "headed 'FT' in the premises table; 'Eighteen' in the prose",
         trap=f"must not be {D.HEADCOUNT_TOTAL} (total headcount)")
    _put("BusinessInformation_PartTimeEmployeeCount_A", V_EXPECT, L["pt"],
         "headed 'PT'", trap=f"must not be {D.SEASONAL_TEMPS} (agency temps)")
    for ch in "BCD":
        for k in ("FullTimeEmployeeCount", "PartTimeEmployeeCount"):
            _put(f"BusinessInformation_{k}_{ch}", V_NA, "", "one premises only")

    # ── PREMISES row A; B-D have no premises ─────────────────────────────────
    _put("CommercialStructure_Location_ProducerIdentifier_A", V_EXPECT, L["num"])
    _put("CommercialStructure_Building_ProducerIdentifier_A", V_EXPECT, L["bldg"])
    _put("CommercialStructure_PhysicalAddress_LineOne_A", V_EXPECT, L["l1"])
    _put("CommercialStructure_PhysicalAddress_LineTwo_A", V_NO_DATA, "",
         "no second line")
    _put("CommercialStructure_PhysicalAddress_CityName_A", V_EXPECT, L["city"])
    _put("CommercialStructure_PhysicalAddress_CountyName_A", V_EXPECT, L["county"],
         "headed 'CNTY'; 'City and County of Denver' in prose")
    _put("CommercialStructure_PhysicalAddress_StateOrProvinceCode_A", V_EXPECT,
         L["state"])
    _put("CommercialStructure_PhysicalAddress_PostalCode_A", V_EXPECT, L["zip"])
    _put("CommercialStructure_AnnualRevenueAmount_A", V_EXPECT, L["revenue"],
         "stated as $4,250,000, 'about $4.25 million' and 4,250 ($000)",
         trap="must not be the projected 2026 figure or the payroll")
    _tick("CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A", True,
          "headed 'CL: IN'")
    _tick("CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_A", False)
    _tick("CommercialStructure_InsuredInterest_TenantIndicator_A", True,
          "headed 'INT: TENANT'")
    _tick("CommercialStructure_InsuredInterest_OwnerIndicator_A", False,
          trap="the landlord owns the building")
    _tick("CommercialStructure_InsuredInterest_OtherIndicator_A", False)
    _put("CommercialStructure_InsuredInterest_OtherDescription_A", V_NO_DATA)
    _tick("CommercialStructure_RiskLocation_OtherIndicator_A", False)
    _put("CommercialStructure_RiskLocation_OtherDescription_A", V_NO_DATA)
    _put("CommercialStructure_Question_ABBCode_A", V_EXPECT, L["leased_to_others"],
         "headed 'LSD'; 'no portion ... is sublet' in prose")
    _put("CommercialStructure_InstallationRepairWorkPercent_A", V_EXPECT,
         D.INSTALL_PCT)
    _put("CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", V_EXPECT,
         D.INSTALL_OFF_PCT)
    _put("BuildingOccupancy_OccupiedArea_A", V_EXPECT, L["occupied"],
         "headed 'OCC SF'; '5000 sq ft' in prose",
         trap="must not be the 15,000 building total")
    _put("BuildingOccupancy_OpenToPublicArea_A", V_EXPECT, L["public"])
    _put("BuildingOccupancy_OperationsDescription_A", V_EXPECT, L["ops"],
         "client: premises 'Description of Operations' (graded on MEANING)",
         trap="must not be the PRIMARY operations paragraph")
    _put("Construction_BuildingArea_A", V_EXPECT, L["total_area"],
         "headed 'TOT SF'", trap="must not be the 5,000 occupied")
    prem_cols = ["Location_ProducerIdentifier", "Building_ProducerIdentifier",
                 "PhysicalAddress_LineOne", "PhysicalAddress_LineTwo",
                 "PhysicalAddress_CityName", "PhysicalAddress_CountyName",
                 "PhysicalAddress_StateOrProvinceCode", "PhysicalAddress_PostalCode",
                 "AnnualRevenueAmount", "RiskLocation_InsideCityLimitsIndicator",
                 "RiskLocation_OutsideCityLimitsIndicator",
                 "InsuredInterest_TenantIndicator", "InsuredInterest_OwnerIndicator",
                 "InsuredInterest_OtherIndicator", "InsuredInterest_OtherDescription",
                 "RiskLocation_OtherIndicator", "RiskLocation_OtherDescription",
                 "Question_ABBCode"]
    for ch in "BCD":
        _na_rows([f"CommercialStructure_{k}_{ch}" for k in prem_cols]
                 + [f"BuildingOccupancy_{k}_{ch}" for k in
                    ("OccupiedArea", "OpenToPublicArea", "OperationsDescription")]
                 + [f"Construction_BuildingArea_{ch}"],
                 "one premises only",
                 trap="45 customer JOB SITES are listed - none is a premises")

    # ── LOSS HISTORY - one claim, the LATEST valuation ───────────────────────
    ls = D.LOSS
    for k, v in (("OccurrenceDate", ls["occurrence"]), ("ClaimDate", ls["claim"]),
                 ("LineOfBusiness", ls["line"]),
                 ("OccurrenceDescription", ls["desc"]),
                 ("PaidAmount", ls["paid"]), ("ReservedAmount", ls["reserved"]),
                 ("ClaimStatus_SubrogationCode", ls["subro"]),
                 ("ClaimStatus_OpenCode", ls["open"])):
        _put(f"LossHistory_{k}_A", V_EXPECT, v,
             "the loss run valued 08/31/2026 SUPERSEDES the 06/30/2024 fax",
             trap="the faxed old valuation says paid $3,200 / reserved $1,650 / OPEN")
    for ch in "BC":
        for k in ("OccurrenceDate", "ClaimDate", "LineOfBusiness",
                  "OccurrenceDescription", "PaidAmount", "ReservedAmount",
                  "ClaimStatus_SubrogationCode", "ClaimStatus_OpenCode"):
            _put(f"LossHistory_{k}_{ch}", V_NA, "",
                 "one claim - the faxed copy is the SAME claim, not a second one",
                 trap="a second row is the duplicate-valuation defect")
    _put("LossHistory_InformationYearCount_A", V_EXPECT, D.LOSS_YEARS)
    _put("LossHistory_TotalAmount_A", V_EXPECT, D.TOTAL_PAID,
         "ACORD tooltip: 'the amount that has been PAID on all losses to date'")
    _tick("LossHistory_NoPriorLossesIndicator_A", False,
          "one claim is documented", trap="three loss runs print 'CLAIMS 0'")

    # ── PRIOR CARRIER - only the year the documents substantiate ─────────────
    _put("PriorCoverage_PolicyYear_A", V_EXPECT, D.PRIOR_YEAR,
         "ACORD tooltip: 'Enter year'")
    for ch in "BC":
        _put(f"PriorCoverage_PolicyYear_{ch}", V_NO_DATA, "",
             "client: 'populate only the year it can substantiate'",
             trap="the loss runs span five years but print no policy or premium "
                  "for earlier terms - that is not carrier history")
    for ln in D.CURRENT_LINES:
        g = ln["grid"]
        _put(f"PriorCoverage_{g}_InsurerFullName_A", V_EXPECT, D.CUR_CARRIER)
        _put(f"PriorCoverage_{g}_PolicyNumberIdentifier_A", V_EXPECT, ln["policy"])
        _put(f"PriorCoverage_{g}_TotalPremiumAmount_A", V_EXPECT, ln["premium"],
             "the current premium belongs HERE, not on page one")
        _put(f"PriorCoverage_{g}_EffectiveDate_A", V_EXPECT, D.CUR_EFF)
        _put(f"PriorCoverage_{g}_ExpirationDate_A", V_EXPECT, D.CUR_EXP)
        for ch in "BC":
            for k in ("InsurerFullName", "PolicyNumberIdentifier", "TotalPremiumAmount",
                      "EffectiveDate", "ExpirationDate"):
                _put(f"PriorCoverage_{g}_{k}_{ch}", V_NO_DATA, "",
                     "not substantiated - do not manufacture carrier history")
    _put("PriorCoverage_OtherLine_LineOfBusinessCode_A", V_NOT_SCORED, "",
         "ACORD tooltip: 'Enter CODE'. The repo has no ACORD line-of-business code "
         "table, so no correct value can be pinned without inventing one. Open "
         "item from the 28 Sep review - a phrase such as 'Commercial Umbrella' is a "
         "wrong-shaped value in a code box")

    # ── OTHER POLICY - question 4 is N ───────────────────────────────────────
    for ch in "ABCD":
        _put(f"OtherPolicy_LineOfBusinessCode_{ch}", V_NO_DATA, "", "question 4 is N")
        _put(f"OtherPolicy_PolicyNumberIdentifier_{ch}", V_NO_DATA, "",
             "question 4 is N", trap="the current policies are with another carrier")

    # ── SUBSIDIARY - questions 1a and 1b are N ───────────────────────────────
    for f in ("Subsidiary_ParentOwnershipPercent_A",
              "Subsidiary_ParentSubsidiaryRelationshipDescription_A",
              "Subsidiary_OrganizationName_A", "Subsidiary_ParentOwnershipPercent_B",
              "Subsidiary_ParentSubsidiaryRelationshipDescription_B"):
        _put(f, V_NO_DATA, "", "questions 1a and 1b are N")

    # ── CANCEL / NON-RENEW - question 5 is N ─────────────────────────────────
    for k in ("AgentNoLongerWritesForInsurerIndicator", "NonPaymentIndicator",
              "NonRenewalIndicator", "OtherIndicator", "UnderwritingIndicator",
              "UnderwritingConditionCorrectedIndicator"):
        _tick(f"CancelNonRenew_{k}_A", False, "question 5 is N",
              trap="the cover letter says the current programme will not be renewed "
                   "THERE - that is the insured moving, not a non-renewal")
    _put("CancelNonRenew_OtherDescription_A", V_NO_DATA)
    _put("CancelNonRenew_UnderwritingConditionCorrectedDescription_A", V_NO_DATA)

    # ── ADDITIONAL INTEREST - none documented ────────────────────────────────
    _put("AdditionalInterest_FullName_A", V_NO_DATA, "",
         "client: 'Fill only if mortgagee, loss payee, landlord, lienholder, etc. is "
         "actually documented' - none is",
         trap="the landlord is named in a lease summary; every vehicle's "
              "LIENHOLDER cell says 'None'")
    _put("AdditionalInterest_FullName_B", V_NO_DATA)

    # ── Default: every field not decided above ───────────────────────────────
    # Printed at build time so a forgotten expectation is SEEN, not silently
    # scored as a blank violation.
    defaulted = [f for f in schema if f not in FIELDS]
    for f in defaulted:
        why = ("no additional interest is documented"
               if f.startswith("AdditionalInterest_") else
               "not stated in the package")
        _put(f, V_NO_DATA, "", why)
    return schema, defaulted


# ═════════════════════════════════════════════════════════════════════════════
# Assemble - the shape `score_form_fill.py` reads
# ═════════════════════════════════════════════════════════════════════════════
_NARRATIVE_NAME = re.compile(
    r"(Description|Explanation|RemarkText|Operations|Relationship)", re.I)


def _match_mode(field: str, meta: dict) -> str:
    tu = (meta.get("tu") or "").strip().lower()
    if (meta.get("ft") == "/Tx" and tu.startswith("enter text")
            and _NARRATIVE_NAME.search(field)):
        return "semantic"
    return "exact"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def assemble(schema: dict) -> dict:
    unknown = [f for f in FIELDS if f not in schema]
    if unknown:
        raise SystemExit(f"answer key names {len(unknown)} field(s) NOT on the real "
                         f"ACORD 125 schema: {unknown[:8]}")
    missing = [f for f in schema if f not in FIELDS]
    if missing:
        raise SystemExit(f"no verdict for {len(missing)} fields: {missing[:10]}")
    for f, v in FIELDS.items():
        v["match"] = _match_mode(f, schema.get(f) or {})
    expect = {f: v["value"] for f, v in FIELDS.items() if v["verdict"] == V_EXPECT}
    blanks = sorted(f for f, v in FIELDS.items()
                    if v["verdict"] in (V_NO_DATA, V_BY_RULE, V_NA))
    forbidden: Dict[str, List[str]] = {}
    for value, scope, _why in D.DECOYS:
        forbidden.setdefault(scope, []).append(value)
    forbidden.setdefault("Policy_ExpirationDate_A", []).append(D.CUR_EXP)
    forbidden.setdefault("Construction_BuildingArea_A", []).append(D.LOC["occupied"])
    forbidden.setdefault("BuildingOccupancy_OccupiedArea_A", []).append(
        D.LOC["total_area"])
    shapes = {
        "NamedInsured_TaxIdentifier_*": {"regex": r"^\d{2}-?\d{7}$",
                                         "why": "a FEIN is nine digits"},
        "NamedInsured_NAICSCode_*": {"regex": r"^\d{6}$", "why": "NAICS is six digits"},
        "NamedInsured_SICCode_*": {"regex": r"^\d{4}$", "why": "SIC is four digits"},
        "*_PostalCode_*": {"regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP"},
        "*StateOrProvinceCode*": {"regex": r"^[A-Za-z]{2}$", "why": "two letters"},
        "Policy_Payment_PaymentScheduleCode_A": {
            "regex": r"^[A-Z]{2}$", "why": "ACORD: a two-letter code (AN, MO, QT)"},
        "Policy_Audit_FrequencyCode_A": {
            "regex": r"^[ASQMO]$", "why": "ACORD: A / S / Q / M / O"},
    }
    expected_absent = {
        "scope": ["CommercialStructure_PhysicalAddress_LineOne_*",
                  "NamedInsured_FullName_*", "AdditionalInterest_FullName_*",
                  "AdditionalInterest_MailingAddress_LineOne_*",
                  "LossHistory_OccurrenceDescription_[BC]",
                  "LossHistory_OccurrenceDate_[BC]"],
        "values": [a for a, _c, _z, _s in D.JOB_SITES]
                  + [n for n, *_r in D.CERT_HOLDERS]
                  + [a for _n, a, *_r in D.CERT_HOLDERS]
                  + [D.LANDLORD, D.LOSS["desc"], D.LOSS["occurrence"]],
    }
    row_sets = {
        "premises": {"slots": list("ABCD"), "columns": {
            "loc": "CommercialStructure_Location_ProducerIdentifier_{row}",
            "line1": "CommercialStructure_PhysicalAddress_LineOne_{row}",
            "city": "CommercialStructure_PhysicalAddress_CityName_{row}",
            "zip": "CommercialStructure_PhysicalAddress_PostalCode_{row}",
            "revenue": "CommercialStructure_AnnualRevenueAmount_{row}",
            "ft": "BusinessInformation_FullTimeEmployeeCount_{row}",
            "occupied": "BuildingOccupancy_OccupiedArea_{row}",
            "area": "Construction_BuildingArea_{row}"},
            "rows": [{"loc": D.LOC["num"], "line1": D.LOC["l1"], "city": D.LOC["city"],
                      "zip": D.LOC["zip"], "revenue": D.LOC["revenue"],
                      "ft": D.LOC["ft"], "occupied": D.LOC["occupied"],
                      "area": D.LOC["total_area"]}]},
        "contacts": {"slots": list("AB"), "columns": {
            "type": "NamedInsured_Contact_ContactDescription_{row}",
            "name": "NamedInsured_Contact_FullName_{row}",
            "phone": "NamedInsured_Contact_PrimaryPhoneNumber_{row}",
            "email": "NamedInsured_Contact_PrimaryEmailAddress_{row}"},
            "rows": [{"type": c["type"], "name": c["name"], "phone": c["phone"],
                      "email": c["email"]} for c in D.CONTACTS]},
        "losses": {"slots": list("ABC"), "columns": {
            "occurrence": "LossHistory_OccurrenceDate_{row}",
            "line": "LossHistory_LineOfBusiness_{row}",
            "paid": "LossHistory_PaidAmount_{row}",
            "reserved": "LossHistory_ReservedAmount_{row}",
            "open": "LossHistory_ClaimStatus_OpenCode_{row}"},
            "rows": [{"occurrence": D.LOSS["occurrence"], "line": D.LOSS["line"],
                      "paid": D.LOSS["paid"], "reserved": D.LOSS["reserved"],
                      "open": D.LOSS["open"]}]},
        "prior_coverage_year_one": {"slots": ["A"], "columns": {
            f"{ln['grid']}_{k}": f"PriorCoverage_{ln['grid']}_{fld}_{{row}}"
            for ln in D.CURRENT_LINES
            for k, fld in (("carrier", "InsurerFullName"),
                           ("policy", "PolicyNumberIdentifier"),
                           ("premium", "TotalPremiumAmount"))},
            "rows": [{f"{ln['grid']}_{k}": v for ln in D.CURRENT_LINES
                      for k, v in (("carrier", D.CUR_CARRIER),
                                   ("policy", ln["policy"]),
                                   ("premium", ln["premium"]))}]},
    }
    counts = {v: sum(1 for x in FIELDS.values() if x["verdict"] == v)
              for v in (V_EXPECT, V_NO_DATA, V_BY_RULE, V_NA, V_NOT_SCORED)}
    return {
        "_meta": {"kit": "FR125 - the client's ACORD 125 test case",
                  "account": D.NAME, "document": PDF_PATH.name,
                  "built_by": "backend/scripts/make_fr125_test_pdf.py",
                  "answers_from": "125_reference/ACORD 125 - field completition "
                                  "8-19-26.docx (the CLIENT's answer key)",
                  "fields_on_form": len(schema), "verdict_counts": counts,
                  "absent_by_design": D.ABSENT_BY_DESIGN,
                  "scanned_only": D.SCANNED_ONLY},
        "_doc": f"{PDF_PATH.name} - one upload, ~{TARGET_PAGES} pages",
        "_forms": ["ACORD_125"],
        "expect": {"ACORD_125": expect},
        "must_be_blank": {"ACORD_125": blanks},
        "forbidden": {"ACORD_125": forbidden},
        "shapes": {"ACORD_125": shapes},
        "expected_absent": {"ACORD_125": expected_absent},
        "row_sets": {"ACORD_125": row_sets},
        "fields": FIELDS,
        "match_modes": {"ACORD_125": {
            "semantic": sorted(f for f, v in FIELDS.items()
                               if v["verdict"] == V_EXPECT and v["match"] == "semantic"),
            "rule": "semantic = ACORD tooltip 'Enter text:' AND a narrative field name. "
                    "Everything else is exact after formatting normalisation."}},
        "expected_facts": expected_facts(),
    }


def expected_facts() -> dict:
    """What LLM call 1 should produce, for `score_a125_extraction.py --key`."""
    return {
        "_scalars": {
            "applicant_name": D.NAME, "fein": D.FEIN, "sic_code": D.SIC,
            "naics_code": D.NAICS, "entity_type": D.ENTITY,
            "business_start_date": D.START_DATE, "effective_date": D.PROPOSED_EFF,
            "expiration_date": D.PROPOSED_EXP,
            "operations_description": D.PRIMARY_OPERATIONS,
            "applicant_business_phone": D.BUS_PHONE, "applicant_website": D.WEBSITE,
            "applicant_gl_class_code": D.GL_CODE,
            "sales_installation_repair_percent": D.INSTALL_PCT,
            "sales_installation_repair_off_premises_percent": D.INSTALL_OFF_PCT,
        },
        "_lists": {
            "applicant_contacts": {
                "expected": [{"name": c["name"], "contact_type": c["type"],
                              "phone": c["phone"], "email": c["email"]}
                             for c in D.CONTACTS],
                "key": "name", "columns": ["contact_type", "phone", "email"]},
            "property_locations": {
                "expected": [{"address": D.LOC["l1"], "county": D.LOC["county"],
                              "full_time_employees": D.LOC["ft"],
                              "part_time_employees": D.LOC["pt"],
                              "annual_revenue": D.LOC["revenue"],
                              "occupied_area": D.LOC["occupied"],
                              "open_to_public_area": D.LOC["public"],
                              "total_building_area": D.LOC["total_area"]}],
                "key": "address",
                "columns": ["county", "full_time_employees", "part_time_employees",
                            "annual_revenue", "occupied_area", "open_to_public_area",
                            "total_building_area"]},
            "disclosure_answers": {
                "expected": [{"topic": t, "answer": q["answer"]}
                             for code, q in D.QUESTIONS.items()
                             for t in [_TOPIC[code]]],
                "key": "topic", "columns": ["answer"]},
            # a list of STRINGS in the schema; the grader reads each as a row
            "safety_program_elements": {
                "expected": [{"element": e} for e in
                             ("Safety Manual", "Safety Position", "Monthly Meetings")],
                "key": "element", "columns": []},
            # ONE row, at the LATEST valuation - the faxed 2024 copy is the
            # same claim, not a second one
            "loss_history": {
                "expected": [{"claim_number": D.LOSS["claim_no"],
                              "date": D.LOSS["occurrence"], "paid": D.LOSS["paid"],
                              "reserved_amount": D.LOSS["reserved"],
                              "open_code": "C"}],
                "key": "claim_number",
                "columns": ["date", "paid", "reserved_amount", "open_code"]},
        },
        "_must_be_empty": ["named_insured_details", "additional_interests",
                           "organization_relationships",
                           "other_named_insured_operations"],
    }


_TOPIC = {"AAI": "subsidiary_of_another", "AAJ": "has_subsidiaries",
          "KAA": "formal_safety_program", "ABC": "flammables_explosives_chemicals",
          "AAH": "other_insurance_with_carrier",
          "AAC": "coverage_declined_cancelled_nonrenewed",
          "AAD": "abuse_molestation_discrimination_claims",
          "KAB": "fraud_arson_conviction", "AAF": "uncorrected_fire_safety_violations",
          "KAK": "foreclosure_repossession_bankruptcy", "KAL": "judgement_or_lien",
          "ABB": "business_in_trust", "KAC": "foreign_operations",
          "KAM": "other_business_ventures", "KAN": "owns_leases_operates_drones",
          "KAO": "hires_drone_operators"}


# ═════════════════════════════════════════════════════════════════════════════
# Verify - the kit must be FAIR: every expectation printed, every decoy printed
# ═════════════════════════════════════════════════════════════════════════════
def _extract() -> str:
    import pdfplumber
    from utils import page_layout as pl
    out = []
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for pg in pdf.pages:
            t = pl.page_text(pg)
            out.append(t if isinstance(t, str) else (t[0] if t else ""))
    return "\n".join(out)


def verify(key: dict, pages: int) -> None:
    text = _extract()
    hay = _norm(text)
    scan_hay = _norm(" ".join(SCANNED_TEXT))
    problems: List[str] = []
    for field, val in key["expect"]["ACORD_125"].items():
        meta = FIELDS[field]
        if field in ("Form_EditionIdentifier_A",):
            continue
        if meta["value"] in ("Y", "N") and field.endswith(("Indicator_A",
                                                           "Indicator_B")):
            continue                            # a tick is not a quotable string
        if field == "Policy_Payment_PaymentScheduleCode_A":
            if _norm(D.PAYMENT_PLAN_WORD) not in hay:
                problems.append("the payment-plan WORD is not printed")
            continue
        if field.startswith("CommercialPolicy_Question_"):
            code = field.split("_")[2].replace("Code", "")
            q = D.QUESTIONS[code]
            where = scan_hay if q["scanned"] else hay
            if _norm(q["stated"])[:50] not in where:
                problems.append(f"question {q['n']}'s statement is not printed")
            continue
        if meta["match"] == "semantic":
            # graded on MEANING, so fair when every content word is printed -
            # a riffled cell interleaves the words but does not lose them
            words = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
            lost = [w for w in re.findall(r"[a-z0-9]{3,}", str(val).lower())
                    if w not in words]
            if lost:
                problems.append(f"NOT IN DOCUMENT: {field} lost words {lost[:5]}")
            continue
        probe = _norm(val)[:60]
        if probe and probe not in hay and probe not in scan_hay:
            problems.append(f"NOT IN DOCUMENT: {field} = {str(val)[:70]!r}")
    for value, scope, _why in D.DECOYS:
        if _norm(value) not in hay and _norm(value) not in scan_hay:
            problems.append(f"DECOY MISSING: {value!r} ({scope})")
    # the fuzz must actually be there - and the repair layer must see through it
    for probe, what in (("POLICYNOGL123456", "teletype despacing on the GL dec"),):
        if _norm(probe) not in hay:
            problems.append(f"FUZZ NOT REPAIRED: {what}")
    # facts that are SCANNED-only must NOT also be in the text layer
    for code, q in D.QUESTIONS.items():
        if q["scanned"] and _norm(q["stated"])[:50] in hay:
            problems.append(f"question {q['n']} leaks into the text layer - it is "
                            f"supposed to be reachable by OCR only")
    problems += _self_consistency(key)
    if problems:
        for p in problems:
            print("  FAIL:", p)
        raise SystemExit(f"verification failed: {len(problems)} problem(s)")
    print(f"  verification OK: {pages} pages, {len(text):,} text-layer chars, "
          f"{len(SCANNED_TEXT)} scanned lines, "
          f"{len(key['expect']['ACORD_125'])} expectations, "
          f"{len(key['must_be_blank']['ACORD_125'])} must-be-blank, "
          f"{len(D.DECOYS)} decoys")


def _self_consistency(key: dict) -> List[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_sff", str(BACKEND / "scripts" / "score_form_fill.py"))
    sff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sff)
    out: List[str] = []
    perfect = dict(key["expect"]["ACORD_125"])
    res = sff.score_form("ACORD_125", key, perfect, lambda f: None)
    t = res["tally"]
    for kind in ("wrong", "blank_violation", "forbidden", "shape", "overflow_leak"):
        for row in res["details"].get(kind, [])[:4]:
            out.append(f"SELF-CONSISTENCY ({kind}): {row}")
    if t.get("correct") != len(perfect):
        out.append(f"SELF-CONSISTENCY: {t.get('correct')} of {len(perfect)} correct")
    for g in sff.score_rows("ACORD_125", key, perfect):
        if g.get("cross_row") or g.get("cells_correct") != g.get("cells_expected"):
            out.append(f"SELF-CONSISTENCY (row-cell): {g}")
    res0 = sff.score_form("ACORD_125", key, {}, lambda f: None)
    for kind in ("blank_violation", "forbidden", "shape", "overflow_leak", "wrong"):
        if res0["tally"].get(kind):
            out.append(f"SELF-CONSISTENCY: an EMPTY form reports "
                       f"{res0['tally'][kind]} {kind}")
    return out


# ═════════════════════════════════════════════════════════════════════════════
def write_readme(key: dict, pages: int, defaulted: List[str]) -> None:
    c = key["_meta"]["verdict_counts"]
    sem = key["match_modes"]["ACORD_125"]["semantic"]
    lines = [
        "# FR125 - the client's ACORD 125 test case", "",
        "**Upload:** `FR125_front_range_package.pdf` "
        f"({pages} pages, one file).  ",
        "**Answer key:** `FR125_answer_key.json` - a verdict for all "
        f"{key['_meta']['fields_on_form']} ACORD 125 boxes.  ",
        "**Answers come from:** the CLIENT's own answer key "
        "(`125_reference/ACORD 125 - field completition 8-19-26.docx`).", "",
        "## Verdicts", "",
        "| | |", "|---|---|",
        f"| expect a value | {c['expect']} ({len(sem)} graded on MEANING) |",
        f"| must be blank - nothing stated | {c['blank_no_data']} |",
        f"| must be blank - a rule owns it | {c['blank_by_rule']} |",
        f"| no entity for the row | {c['not_applicable']} |",
        f"| not scored | {c['not_scored']} |", "",
        "## Run it", "", "```bash",
        "# 1. RESTART THE BACKEND (a stale process ran old code on test 2)",
        "python3 backend/scripts/make_fr125_test_pdf.py",
        "# 2. upload fr125_test_data/FR125_front_range_package.pdf,",
        "#    generate ACORD 125 ONLY, change nothing",
        "python3 backend/scripts/dump_a125_run.py --list",
        "python3 backend/scripts/dump_a125_run.py <session_id> > fr125_run.json",
        "python3 backend/scripts/report_125_run.py --key "
        "fr125_test_data/FR125_answer_key.json --dump fr125_run.json",
        "python3 backend/scripts/audit_125_rules.py fr125_run.json", "```", "",
        "## What is hard, and where", "",
        "| technique | where | what it tests |", "|---|---|---|",
        "| scanned page, no text layer | questionnaire p.2, W-9, articles, old "
        "loss run | OCR; questions 8-15 are ONLY here |",
        "| X in a column | questionnaire p.1 | reading an answer from its position |",
        "| abbreviated headers | premises table (FT, PT, OCC SF, TOT SF, LSD) | "
        "RC-G beyond the two columns fixed on 21 Sep |",
        "| landscape page | statement of values | wide-table reading order |",
        "| teletype | GL declarations | `page_layout.despaced_words` |",
        "| riffled table | premises, profile, job sites, auto loss run | "
        "`page_layout.page_words` |",
        "| two-column drift | contacts, operations | column reflow |",
        "| dot leaders | profile | label and value 70 characters apart |",
        "| spelled three ways | revenue, employees, area, start date | "
        "normalisation |",
        "| placeholders in source | '--', 'N/A', '(none)' | Guard 13 at the source |",
        "| two valuations of one claim | auto loss run + old fax | latest wins, "
        "never two rows |", "",
        "## Decoys (each scoped to the boxes it is forbidden in)", "",
        "| value | forbidden in | why |", "|---|---|---|",
        *[f"| `{v}` | `{s}` | {w} |" for v, s, w in D.DECOYS], "",
        "## Facts reachable ONLY by OCR", "",
        *[f"- `{f}`" for f in D.SCANNED_ONLY], "",
        "If these miss and everything else lands, OCR is the suspect - check the "
        "backend log for `ocr_service` before touching extraction.", "",
        "## Deliberately never stated", "", *[f"- {a}" for a in D.ABSENT_BY_DESIGN],
        "", "## Defaulted to blank at build time", "",
        f"{len(defaulted)} fields were not decided explicitly and default to "
        "`blank_no_data`. They are listed in the build output; review them when "
        "the kit changes.",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    build_pages()
    pad_to_target()
    pages = render()
    schema, defaulted = build_key()
    key = assemble(schema)
    KEY_PATH.write_text(json.dumps(key, indent=1), encoding="utf-8")
    verify(key, pages)
    write_readme(key, pages, defaulted)
    fam: Dict[str, int] = {}
    for f in defaulted:
        fam[f.rsplit("_", 1)[0].split("_")[0]] = fam.get(
            f.rsplit("_", 1)[0].split("_")[0], 0) + 1
    print(f"  wrote {PDF_PATH.relative_to(ROOT)} ({pages} pages)")
    print(f"  wrote {KEY_PATH.relative_to(ROOT)}  {key['_meta']['verdict_counts']}")
    print(f"  defaulted to blank_no_data: {len(defaulted)}  by family: {fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
