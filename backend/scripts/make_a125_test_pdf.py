"""
make_a125_test_pdf.py - the ACORD 125 full-form test kit.

    py backend/scripts/make_a125_test_pdf.py

Writes into `271page_test_data/`:

    A125_meridian_package.pdf        ~100 pages, deliberately badly formatted
    A125_answer_key.json             a verdict for ALL 548 ACORD 125 fields
    README-A125-HOW-TO-TEST.md       what each trap proves and how to score

WHY THIS KIT EXISTS
-------------------
Every earlier kit scored a SUBSET of ACORD 125 that whoever wrote the kit chose.
The T1 key has an opinion on 146 of the form's 548 boxes; the other 402 are
unjudged, and the pipeline puts a value into 228 of them. This key gives every
one of the 548 a verdict, so "we filled 91%" can never again mean "91% of the
boxes we decided to look at".

FIVE THINGS IT MEASURES
-----------------------
1. EXTRACTION + RELATIONSHIP. Values are printed in the formats real carrier
   documents use and our own extraction layer was built to repair: riffled
   columns, letter-spaced teletype, two-column reading order, bare labels whose
   value is on the next line, one fact spelled three ways. If a value arrives at
   all, the repair worked; if it arrives attached to the right ROW and the right
   COVERAGE LINE, the relationship survived.
2. STAMPING. The key names the exact box each value belongs in, so a value that
   lands one box over is a WRONG, not a CORRECT.
3. CORRECT BLANKS. Sixteen things are deliberately never stated (see
   `_a125_data.ABSENT_BY_DESIGN`). Their boxes must ship empty.
4. INVENTION. `DECOYS` are real strings in the document that are tempting for a
   box they do not belong in - the carrier's own website in the applicant's
   website box, a 7-digit account number in a 9-digit FEIN box, the expiring
   policy number in the box for the policy being applied for. Each is scoped to
   the boxes it is forbidden in, never globally.
5. MEANING. Payroll must not reach a revenue box; a GL class code must not reach
   a NAICS box; the expiring premium must not reach a page-one premium box.

DESIGN RULES, INHERITED FROM THE T1/C5/H7 KITS
----------------------------------------------
1. A fixture must PRINT the value its check cites. `_verify()` re-reads the
   generated PDF THROUGH OUR OWN REPAIR LAYER (`utils.page_layout`) and fails
   the build if any expected value or any decoy is missing. A trap that is not
   in the document tests nothing and looks like a pass.
2. Every field name in the key is checked against the real schema JSON.
3. Forbidden values are SCOPED to the boxes they are forbidden in.
4. The PDF and the key are generated from one module (`_a125_data`), so they
   cannot disagree.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import _a125_data as D                                           # noqa: E402

from reportlab.lib.pagesizes import LETTER                        # noqa: E402
from reportlab.pdfgen import canvas                               # noqa: E402

ROOT     = HERE.parents[2]
BACKEND  = HERE.parents[1]
OUT_DIR  = ROOT / "271page_test_data"
PDF_PATH = OUT_DIR / "A125_meridian_package.pdf"
KEY_PATH = OUT_DIR / "A125_answer_key.json"
DOC_PATH = OUT_DIR / "README-A125-HOW-TO-TEST.md"

W, H = LETTER
LEFT, TOP, LEAD = 38.0, H - 54.0, 10.6
MONO, BOLD = "Courier", "Courier-Bold"
TARGET_PAGES = 100

Page = Callable[[canvas.Canvas], None]
PAGES: List[Page] = []


# ═════════════════════════════════════════════════════════════════════════════
# Drawing primitives - each one reproduces a real extraction defect
# ═════════════════════════════════════════════════════════════════════════════
def _head(c: canvas.Canvas, title: str) -> float:
    """Running header. Deliberately repeats the CARRIER's own contact details on
    every page: the merge ranks candidate values by how often they appear, so
    this is the frequency decoy that must not become the applicant's."""
    c.setFont(MONO, 6.2)
    c.drawString(LEFT, H - 30, f"{D.EXP_CARRIER}   {D.EXP_CARRIER_WEB}   "
                               f"{D.EXP_CARRIER_PHONE}   ACCOUNT {D.EXP_ACCOUNT_NO}")
    c.setFont(BOLD, 8.4)
    c.drawString(LEFT, H - 44, title[:110])
    return TOP


def _foot(c: canvas.Canvas, n: int) -> None:
    c.setFont(MONO, 6.2)
    c.drawString(LEFT, 26, f"Page {n}")
    c.drawString(W - 210, 26, f"{D.INSUREDS[0]['name']}")


def plain(title: str, lines: List[str]) -> Page:
    """Ordinary monospace text. The control: these pages must extract cleanly."""
    def draw(c: canvas.Canvas) -> None:
        y = _head(c, title)
        for ln in lines:
            c.setFont(BOLD if (ln.strip().isupper() and len(ln.strip()) < 88
                               and ln.strip()) else MONO, 7.4)
            c.drawString(LEFT, y, ln[:128])
            y -= LEAD
    return draw


def _draw_tracked(c: canvas.Canvas, x: float, y: float, text: str,
                  size: float = 7.0) -> None:
    """Draw `text` one glyph at a time with the gap between glyphs set to about
    one glyph width, and the gap between WORDS set well clear of it.

    Measured on the real EMC pages: glyph 6.41pt, inter-glyph gap 6.56pt, and
    the inter-WORD gap on ordinary text in the same document is also 6.56pt.
    That is the ambiguity - per character it cannot be resolved, only per line.
    `page_layout.despaced_words` detects `median_gap / median_glyph >= 0.5` and
    re-splits at gaps wider than 1.8x the tracking, so the word break here is
    put at ~3.8x to stay unambiguously clear of it.
    """
    gw = size * 0.6                       # Courier advance at this size
    adv = gw * 2.0                        # glyph + one-glyph gap
    word_extra = gw * 3.0
    cx = x
    for ch in text:
        if ch == " ":
            cx += adv + word_extra
            continue
        c.drawString(cx, y, ch)
        cx += adv


def teletype(title: str, lines: List[str]) -> Page:
    """Letter-spaced text, the shape carrier teletype declarations print in.

    This is the defect that reached a client's ACORD 125 as
    `6 C 7 - 4 0 - 0 2---26`. It is native text, not an OCR artefact, and
    `page_layout.despaced_words` is what repairs it. This page is what proves
    the repair still works.
    """
    def draw(c: canvas.Canvas) -> None:
        y = _head(c, title)
        c.setFont(MONO, 7.0)
        for ln in lines:
            _draw_tracked(c, LEFT, y, ln[:60])
            y -= LEAD
    return draw


def two_column(title: str, left: List[str], right: List[str],
               right_x: float = 322.0) -> Page:
    """Two independent columns. Read straight across, the two halves splice into
    sentences that exist in neither. `page_layout` reorders prose bands and
    splits side-by-side identity blocks; this page is what proves it.

    The baselines DRIFT between the columns on purpose - a projection histogram
    finds no gutter here, which is why the gutter is scored by crossings.
    """
    def draw(c: canvas.Canvas) -> None:
        y = _head(c, title)
        c.setFont(MONO, 7.4)
        for i in range(max(len(left), len(right))):
            if i < len(left):
                c.drawString(LEFT, y, left[i][:44])
            if i < len(right):
                # drift the right column by a fraction of a line
                c.drawString(right_x, y + (0.9 if i % 3 else 0.0), right[i][:44])
            y -= LEAD
    return draw


def riffled_table(title: str, intro: List[str], header: List[str],
                  rows: List[List[str]], xs: List[float],
                  overrun_col: int = 2, size: float = 6.9) -> Page:
    """A whitespace-aligned table whose description column physically overruns
    the column to its right.

    pdfplumber sorts characters by x across a line, so the two runs interleave:
    `pa$rt4y,850`. That is defect D1, the one `page_layout.page_words` repairs by
    re-segmenting the affected line from `use_text_flow=True`. The loss run in
    every real package looks like this.
    """
    def draw(c: canvas.Canvas) -> None:
        y = _head(c, title)
        c.setFont(MONO, 7.4)
        for ln in intro:
            c.drawString(LEFT, y, ln[:128]); y -= LEAD
        y -= 3
        c.setFont(BOLD, 7.0)
        for x, h in zip(xs, header):
            c.drawString(x, y, h)
        y -= LEAD
        c.setFont(MONO, size)
        for row in rows:
            for i, (x, cell) in enumerate(zip(xs, row)):
                if i == overrun_col:
                    # draw the long cell at its own x with NO truncation, so it
                    # runs under the next column's start
                    c.drawString(x, y, str(cell))
                else:
                    c.drawString(x, y, str(cell))
            y -= LEAD
    return draw


def bare_labels(title: str, pairs: List[Tuple[str, str]],
                intro: List[str] | None = None) -> Page:
    """Label on one line, value on the NEXT. A correctly-paired document almost
    never does this; a scanned two-column form that drifted does it constantly,
    and it is the fingerprint `_extract_page_text_smart` keys its column reflow
    on."""
    def draw(c: canvas.Canvas) -> None:
        y = _head(c, title)
        c.setFont(MONO, 7.4)
        for ln in (intro or []):
            c.drawString(LEFT, y, ln[:128]); y -= LEAD
        y -= 4
        for label, value in pairs:
            c.setFont(MONO, 7.4)
            c.drawString(LEFT, y, f"{label}:")
            y -= LEAD
            c.drawString(LEFT + 24, y, str(value))
            y -= LEAD
    return draw


def _rule(ch: str = "-", n: int = 112) -> str:
    return ch * n


def _kv(label: str, value: str, w: int = 40) -> str:
    return f"  {label:<{w}} {value}"


def _cols(xs: List[int], cells: List[str]) -> str:
    out = ""
    for x, cell in zip(xs, cells):
        if len(out) < x:
            out += " " * (x - len(out))
        out += str(cell)
    return "  " + out


# ═════════════════════════════════════════════════════════════════════════════
# The document
# ═════════════════════════════════════════════════════════════════════════════
def build_pages() -> None:
    I = D.INSUREDS
    A = I[0]

    # ── 1. Broker submission cover ───────────────────────────────────────────
    PAGES.append(plain("COMMERCIAL LINES SUBMISSION - COVER SHEET", [
        "", f"  {D.PRODUCER}",
        f"  {D.PRODUCER_L1}, {D.PRODUCER_L2}",
        f"  {D.PRODUCER_CITY}, {D.PRODUCER_STATE} {D.PRODUCER_ZIP}",
        f"  Submitted by: {D.PRODUCER_CONTACT}    {D.PRODUCER_PHONE}    {D.PRODUCER_EMAIL}",
        "", _rule(), "",
        f"  SUBMITTED TO           {D.CARRIER}",
        f"  NAIC                   {D.CARRIER_NAIC}",
        f"  SUBMISSION TYPE        {D.STATUS}  (new business to this carrier)",
        f"  PROPOSED EFFECTIVE     {D.PROPOSED_EFF}",
        f"  PROPOSED EXPIRATION    {D.PROPOSED_EXP}",
        "  POLICY NUMBER          (to be assigned on binding)",
        "  POLICY PREMIUM         (to be quoted)",
        "", _rule(), "",
        f"  APPLICANT              {A['name']}",
        f"  PREPARED               {D.FORM_DATE}",
        "",
        "  This submission replaces the expiring programme described in the",
        "  declarations that follow. The expiring carrier is NOT the carrier",
        "  receiving this submission.",
        "",
        "  COVERAGES REQUESTED",
    ] + [f"    [X] {ln}" for ln in D.LINES_CARRIED] + [""] + [
        "  " + s for s in _wrap(D.NEW_LINE_NOTE, 104)] + [""] + [
        "  COVERAGES NOT REQUESTED / NOT IN FORCE",
    ] + [f"    [ ] {ln:<26} {why}" for ln, why in D.LINES_DECLINED] + [
        "", _rule(), "",
        "  ATTACHMENTS SUBMITTED WITH THIS APPLICATION",
    ] + [f"    - {a}" for a in D.ATTACHMENTS_STATED] + [
        "",
        f"  PREMIUM AUDIT PERIOD   {D.AUDIT_PERIOD}",
        "",
        "  REMARKS",
    ] + ["    " + s for s in _wrap(D.REMARKS, 104)]))

    # ── 2. Submission detail, bare-label shape ───────────────────────────────
    PAGES.append(bare_labels("SUBMISSION DETAIL", [
        ("PRODUCER", D.PRODUCER),
        ("PRODUCER CONTACT", D.PRODUCER_CONTACT),
        ("PRODUCER PHONE", D.PRODUCER_PHONE),
        ("PRODUCER E-MAIL", D.PRODUCER_EMAIL),
        ("CARRIER RECEIVING SUBMISSION", D.CARRIER),
        ("CARRIER NAIC", D.CARRIER_NAIC),
        ("STATUS OF TRANSACTION", f"{D.STATUS} - new business to this carrier"),
        ("PROPOSED POLICY EFFECTIVE DATE", D.PROPOSED_EFF),
        ("PROPOSED POLICY EXPIRATION DATE", D.PROPOSED_EXP),
        ("DATE OF APPLICATION", D.FORM_DATE),
    ], intro=["", "  The fields below are the terms being applied for.",
              "  They are not the terms of the expiring policy.", ""]))

    # ── 3-4. Applicant identity, TWO COLUMN beside the producer ──────────────
    PAGES.append(two_column("APPLICANT AND PRODUCER", [
        "NAMED INSURED", "",
        A["name"], A["l1"], A["l2"],
        f"{A['city']}, {A['state']} {A['zip']}",
        "",
        f"PHONE  {A['phone']}",
        f"FEIN   {A['fein']}",
        f"ENTITY {A['entity']}",
        f"MEMBERS / MANAGERS  {A['members']}",
        f"SIC    {A['sic']}",
        f"NAICS  {A['naics']}",
        f"GL CODE {A['gl_code']}",
        f"BUSINESS STARTED {A['start']}",
        "WEBSITE  not provided",
    ], [
        "PRODUCER", "",
        D.PRODUCER, D.PRODUCER_L1, D.PRODUCER_L2,
        f"{D.PRODUCER_CITY}, {D.PRODUCER_STATE} {D.PRODUCER_ZIP}",
        "",
        f"PHONE  {D.PRODUCER_PHONE}",
        f"CONTACT {D.PRODUCER_CONTACT}",
        f"E-MAIL {D.PRODUCER_EMAIL}",
        "FAX    not provided",
        "AGENCY CODE  not provided",
        "NPN    not provided",
        "LICENCE  not provided",
        "", "",
    ]))

    # the same identity restated with OCR-style spelling drift
    PAGES.append(plain("APPLICANT IDENTITY - RESTATED", [
        "",
        "  The applicant is identified in carrier records in three ways. All",
        "  three refer to one entity.",
        "",
        f"    1.  {A['name']}",
        f"        FEIN {A['fein']}",
        f"    2.  MERIDIAN IRONWORKS AND MECHANICAL LLC",
        f"        FEIN {A['fein'].replace('-', ' ')}",
        f"    3.  Meridian Ironworks & Mech., LLC",
        f"        Federal Employer ID {A['fein'].replace('-', '')}",
        "",
        f"  Carrier account number for the EXPIRING programme: {D.EXP_ACCOUNT_NO}",
        "  (an account number, not a tax identifier)",
        "",
        _rule(), "",
        "  PARENT AND SUBSIDIARY",
        f"    Parent organisation      {D.PARENT_ORG}",
        f"    Parent ownership         {D.PARENT_PCT}",
        f"    Relationship             {D.PARENT_RELATION}",
        f"    Subsidiary               {D.SUBSIDIARY_ORG}",
        f"    Applicant ownership      {D.SUBSIDIARY_PCT}",
        f"    Relationship             {D.SUBSIDIARY_RELATION}",
        "",
        _rule(), "",
        "  APPLICANT CONTACTS",
    ] + sum([[
        f"    CONTACT TYPE   {ct['type']}",
        f"    NAME           {ct['name']}",
        f"    {ct['phone_kind'].upper()} PHONE {ct['phone']}",
        f"    E-MAIL         {ct['email'] or 'not provided'}",
        "",
    ] for ct in D.CONTACTS], [])))

    # ── 5-6. Named insured schedule, ragged ──────────────────────────────────
    ni_rows = [[i["name"], i["fein"], i["entity"], i["members"] or "-",
                i["sic"], i["naics"], i["gl_code"] or "-"] for i in I]
    PAGES.append(riffled_table(
        "SCHEDULE OF NAMED INSUREDS", [
            "", "  Four entities are carried as named insureds on the expiring",
            "  programme and are requested on the renewal.", ""],
        ["NAME", "FEIN", "ENTITY", "MBRS", "SIC", "NAICS", "GL"],
        ni_rows, [40, 236, 300, 352, 386, 420, 470], overrun_col=0))

    PAGES.append(plain("NAMED INSURED DETAIL", sum([[
        f"  ENTITY {n+1}",
        _kv("Full legal name", i["name"]),
        _kv("Mailing address line one", i["l1"]),
        _kv("Mailing address line two", i["l2"] or "(none)"),
        _kv("City / State / ZIP", f"{i['city']}, {i['state']} {i['zip']}"),
        _kv("Business phone", i["phone"]),
        _kv("Website", i["web"] or "not provided"),
        _kv("Legal entity type", i["entity"]),
        _kv("Members / managers", i["members"] or "(not applicable)"),
        _kv("FEIN", i["fein"]),
        _kv("SIC", i["sic"]),
        _kv("NAICS", i["naics"]),
        _kv("General liability class", i["gl_code"] or "(none assigned)"),
        _kv("Date business started", i["start"]),
        "",
    ] for n, i in enumerate(I)], [])))

    # ── 7-8. Premises schedule ───────────────────────────────────────────────
    loc_rows = [[l["num"], f"{l['l1']}{(' ' + l['l2']) if l['l2'] else ''}",
                 l["city"], l["county"] or "-", l["state"], l["zip"],
                 "IN" if l["inside"] else "OUT", l["interest"]]
                for l in D.LOCATIONS]
    PAGES.append(riffled_table(
        "SCHEDULE OF PREMISES", [
            "", "  Five premises. City-limits column reads IN or OUT.", ""],
        ["LOC", "ADDRESS", "CITY", "COUNTY", "ST", "ZIP", "CL", "INTEREST"],
        loc_rows, [40, 80, 250, 322, 392, 414, 456, 486], overrun_col=1))

    PAGES.append(riffled_table(
        "PREMISES - EXPOSURE AND AREA", [
            "", "  Areas in square feet. Revenue is annual gross receipts",
            "  attributable to that premises.", ""],
        ["LOC", "BLDG", "FT", "PT", "REVENUE", "OCCUPIED", "PUBLIC", "TOTAL", "LEASED"],
        [[l["num"], l["bldg"], l["ft"], l["pt"], l["revenue"], l["occupied"],
          l["public"], l["total_area"], l["leased_to_others"]]
         for l in D.LOCATIONS],
        [40, 78, 120, 152, 186, 268, 336, 396, 456], overrun_col=4))

    PAGES.append(plain("PREMISES - DESCRIPTION OF OPERATIONS", sum([[
        f"  LOCATION {l['num']}   BUILDING {l['bldg']}",
        f"    {l['l1']}{(', ' + l['l2']) if l['l2'] else ''}, {l['city']}, "
        f"{l['state']} {l['zip']}",
        f"    County: {l['county'] or 'not stated'}",
        f"    Interest: {l['interest']}",
        f"    Within city limits: {'Yes' if l['inside'] else 'No'}",
        f"    Any area leased to others: {l['leased_to_others']}",
        "    Description of operations:",
    ] + ["      " + s for s in _wrap(l["ops"], 100)] + [""]
        for l in D.LOCATIONS], [])))

    # ── 9-10. Business information and operations ────────────────────────────
    PAGES.append(plain("BUSINESS INFORMATION", [
        "",
        _kv("Nature of business", D.NATURE_OF_BUSINESS),
        _kv("Total annual gross revenue", D.TOTAL_REVENUE),
        _kv("Total annual payroll", D.TOTAL_PAYROLL),
        _kv("Total full time employees", D.TOTAL_FT),
        _kv("Total part time employees", D.TOTAL_PT),
        _kv("Installation / service / repair work", D.INSTALL_PCT),
        _kv("Of which performed off premises", D.INSTALL_OFF_PCT),
        _kv("Date business started", D.INSUREDS[0]["start"]),
        "", _rule(), "",
        "  DESCRIPTION OF OPERATIONS",
    ] + ["    " + s for s in _wrap(D.OPERATIONS, 104)] + [
        "", _rule(), "",
        "  DESCRIPTION OF PRIMARY OPERATIONS",
    ] + ["    " + s for s in _wrap(D.PRIMARY_OPERATIONS, 104)] + [
        "", _rule(), "",
        "  DESCRIPTION OF OPERATIONS - OTHER NAMED INSUREDS",
    ] + ["    " + s for s in _wrap(D.OTHER_INSURED_OPERATIONS.replace(chr(10), " "), 104)]))

    # ── 11-14. Expiring common declarations, TELETYPE ────────────────────────
    PAGES.append(teletype("COMMON POLICY DECLARATIONS", [
        "",
        f"POLICY NO {D.EXPIRING_LINES[0]['policy']}",
        f"ACCOUNT {D.EXP_ACCOUNT_NO}",
        "",
        "NAMED INSURED:",
        D.INSUREDS[0]["name"][:52],
        f"{D.INSUREDS[0]['l1']} {D.INSUREDS[0]['l2']}",
        f"{D.INSUREDS[0]['city']} {D.INSUREDS[0]['state']} {D.INSUREDS[0]['zip']}",
        "",
        f"POLICY PERIOD FROM {D.EXP_EFF} TO {D.EXP_EXP}",
        "12:01 A.M. STANDARD TIME AT THE",
        "MAILING ADDRESS SHOWN ABOVE",
        "",
        f"ISSUED BY {D.EXP_CARRIER_SHORT}",
        f"NAIC {D.EXP_CARRIER_NAIC}",
        "",
        f"TOTAL ADVANCE PREMIUM {D.EXP_TOTAL_PREMIUM}",
    ]))

    PAGES.append(plain("COMMON POLICY DECLARATIONS (CONTINUED)", [
        "",
        "  SCHEDULE OF COVERAGE PARTS AND PREMIUMS",
        "",
        _cols([2, 34, 62, 86], ["COVERAGE PART", "CARRIER", "POLICY NUMBER", "PREMIUM"]),
        _rule(),
    ] + [_cols([2, 34, 62, 86], [e["line"], e["carrier"],
                                 e["policy"], e["premium"]])
         for e in D.EXPIRING_LINES] + [
        _rule(),
        _cols([2, 86], ["TOTAL", D.EXP_TOTAL_PREMIUM]),
        "",
        "  COVERAGE PARTS NOT IN FORCE UNDER THIS POLICY",
        "",
    ] + [_cols([2, 34], [ln, why]) for ln, why in D.LINES_DECLINED] + [
        "",
        "  The coverage parts listed immediately above are shown for",
        "  completeness only. No premium is charged and no coverage is",
        "  afforded for any of them under this policy.",
    ]))

    # ── 15-20. Per-line expiring declarations ────────────────────────────────
    for e in D.EXPIRING_LINES:
        PAGES.append(two_column(f"{e['line'].upper()} DECLARATIONS", [
            f"POLICY NUMBER {e['policy']}",
            f"CARRIER {e['carrier'][:34]}",
            f"NAIC {e['naic']}",
            f"EFFECTIVE {D.EXP_EFF}",
            f"EXPIRATION {D.EXP_EXP}",
            f"PREMIUM THIS COVERAGE PART {e['premium']}",
            "",
            "NAMED INSURED",
            D.INSUREDS[0]["name"][:42],
            f"{D.INSUREDS[0]['l1']}",
            f"{D.INSUREDS[0]['city']}, {D.INSUREDS[0]['state']} "
            f"{D.INSUREDS[0]['zip']}",
        ], [
            "FORMS AND ENDORSEMENTS",
            "CG 00 01 04 13  Commercial General",
            "                Liability Coverage Form",
            "CG 21 47 12 07  Employment-Related",
            "                Practices Exclusion",
            "IL 00 17 11 98  Common Policy",
            "                Conditions",
            "",
            "This coverage part is subject to the",
            "forms and endorsements listed. Form",
            "numbers are not policy numbers.",
            "",
        ]))

    # ── 21. Coverages NOT carried, stated loudly ─────────────────────────────
    PAGES.append(plain("COVERAGE PARTS NOT AFFORDED", [
        "",
        "  The following coverage parts are referenced in this policy only to",
        "  record that they are NOT afforded. No limit, no premium and no",
        "  coverage applies to any of them.",
        "",
    ] + sum([[
        f"  {ln.upper()}",
        f"    Status ................ {why}",
        "    Limit ................. NONE",
        "    Premium ............... $0",
        "",
    ] for ln, why in D.LINES_DECLINED], []) + [
        "  Workers Compensation for Oregon operations is written separately",
        "  through the state accident insurance fund and is not part of this",
        "  programme or of this submission.",
    ]))

    # ── 22-24. Loss runs, RIFFLED ────────────────────────────────────────────
    PAGES.append(riffled_table(
        "LOSS RUN - FIVE YEAR HISTORY", [
            "", f"  Valued {D.FORM_DATE}. Period covered: {D.LOSS_YEARS} years.",
            f"  Insured {D.INSUREDS[0]['name']}", ""],
        ["DATE OF LOSS", "LINE", "DESCRIPTION", "PAID", "RESERVED", "S", "O/C"],
        [[l["occurrence"], l["line"], l["desc"], l["paid"], l["reserved"],
          l["subro"], l["open"]] for l in D.LOSSES],
        [38, 104, 200, 386, 440, 492, 516], overrun_col=2, size=6.4))

    PAGES.append(plain("LOSS RUN - CLAIM DETAIL", sum([[
        f"  CLAIM {l['claim_no']}",
        _kv("Date of occurrence", l["occurrence"]),
        _kv("Date claim reported", l["claim"]),
        _kv("Line of business", l["line"]),
        _kv("Amount paid", l["paid"]),
        _kv("Amount reserved", l["reserved"]),
        _kv("Subrogation", l["subro"]),
        _kv("Status", "Open" if l["open"] == "O" else "Closed"),
        "    Description:",
    ] + ["      " + s for s in _wrap(l["desc"], 100)] + [""]
        for l in D.LOSSES], []) + [
        _rule(), "",
        _kv("TOTAL PAID ALL LINES", D.TOTAL_PAID),
        _kv("TOTAL INCURRED ALL LINES (PAID PLUS RESERVED)", D.TOTAL_INCURRED),
        _kv("NUMBER OF CLAIMS", str(len(D.LOSSES))),
        _kv("YEARS OF LOSS INFORMATION", D.LOSS_YEARS),
        "",
        "  Loss runs are attached for each of the five years. The applicant",
        "  has not attested to a loss-free period and does not claim one.",
    ]))

    # ── 25. Additional interests ─────────────────────────────────────────────
    PAGES.append(plain("SCHEDULE OF ADDITIONAL INTERESTS", sum([[
        f"  INTEREST {n+1}",
        _kv("Name", it["name"]),
        _kv("Type of interest", it["interest"]),
        _kv("Rank", it["rank"] or "(not stated)"),
        _kv("Address line one", it["l1"]),
        _kv("Address line two", it["l2"]),
        _kv("City / State / ZIP", f"{it['city']}, {it['state']} {it['zip']}"),
        _kv("Phone", it["phone"] or "(not stated)"),
        _kv("E-mail", it["email"] or "(not stated)"),
        _kv("Account / reference number", it["account"] or "(not stated)"),
        _kv("Loan or lease amount", it["loan"] or "(not stated)"),
        _kv("Applies to location", it["loc"]),
        _kv("Item", it["item"] or "(not stated)"),
        _kv("Certificate required", it["cert_required"] or "(not stated)"),
        _kv("Reason for interest", it["reason"] or "(not stated)"),
        "",
    ] for n, it in enumerate(D.INTERESTS)], [])))

    # ── 26-28. The fifteen questions ─────────────────────────────────────────
    q_lines = ["", "  GENERAL INFORMATION - APPLICANT RESPONSES", ""]
    for code, q in D.QUESTIONS.items():
        if q["answer"] is None:
            continue                       # never addressed - prints nothing
        q_lines += [f"  QUESTION {q['n']}.  {q['q']}",
                    f"     ANSWER: {q['answer']}"]
        if q["text"]:
            q_lines += ["     " + s for s in _wrap(q["text"], 100)]
        if q.get("occurrence"):
            q_lines.append(_kv("     Date of occurrence", q["occurrence"]))
        if q.get("resolution_date"):
            q_lines.append(_kv("     Date resolved", q["resolution_date"]))
        if q.get("resolution"):
            q_lines += ["     Resolution: " + s
                        for s in _wrap(q["resolution"], 90)]
        q_lines.append("")
    q_lines += [
        _rule(), "",
        "  The numbered questions above are the ones the applicant answered.",
        "  Any question not printed above was not put to the applicant and has",
        "  no answer on file.",
        "",
        "  FORMAL SAFETY PROGRAMME - DETAIL",
        _kv("    Written safety manual", "Yes"),
        _kv("    Designated safety position", f"Yes - {D.SAFETY['director']}"),
        _kv("    Monthly safety meetings", "Yes"),
        "",
        "  No statement is made regarding participation in any OSHA",
        "  programme.",
    ]
    PAGES.append(plain("GENERAL INFORMATION", q_lines))

    # ── 29-30. Prior carrier history ─────────────────────────────────────────
    PAGES.append(riffled_table(
        "PRIOR CARRIER INFORMATION", [
            "", "  Two policy years are documented. Records for earlier years",
            "  are not available and are not represented here.", ""],
        ["YEAR", "LINE", "CARRIER", "POLICY NUMBER", "PREMIUM", "EFF", "EXP"],
        [[D.PRIOR1_YEAR, e["line"], e["carrier"], e["policy"],
          e["premium"], D.EXP_EFF, D.EXP_EXP] for e in D.EXPIRING_LINES] +
        [[D.PRIOR2_YEAR, e["line"], D.PRIOR2_CARRIER, e["policy"],
          e["premium"], D.PRIOR2_EFF, D.PRIOR2_EXP] for e in D.PRIOR2_LINES],
        [38, 80, 178, 336, 414, 452, 506], overrun_col=2, size=6.2))

    PAGES.append(plain("PRIOR CARRIER INFORMATION - DETAIL", [
        "", f"  POLICY YEAR {D.PRIOR1_YEAR}", "",
    ] + sum([[
        _kv(f"  {e['line']} carrier", e["carrier"]),
        _kv(f"  {e['line']} policy number", e["policy"]),
        _kv(f"  {e['line']} premium", e["premium"]),
        _kv(f"  {e['line']} term", f"{D.EXP_EFF} to {D.EXP_EXP}"),
        "",
    ] for e in D.EXPIRING_LINES], []) + [
        _rule(), "", f"  POLICY YEAR {D.PRIOR2_YEAR}", "",
    ] + sum([[
        _kv(f"  {e['line']} carrier", D.PRIOR2_CARRIER),
        _kv(f"  {e['line']} policy number", e["policy"]),
        _kv(f"  {e['line']} premium", e["premium"]),
        _kv(f"  {e['line']} term", f"{D.PRIOR2_EFF} to {D.PRIOR2_EXP}"),
        "",
    ] for e in D.PRIOR2_LINES], []) + [
        "  No umbrella or excess policy was carried in the "
        f"{D.PRIOR2_YEAR} policy year.",
        "",
        "  No records are held for policy years before "
        f"{D.PRIOR2_EFF}.",
        "",
    ] + ["  " + s for s in _wrap(D.NEW_LINE_NOTE, 104)]))


def _wrap(text: str, width: int) -> List[str]:
    import textwrap
    return textwrap.wrap(text, width) or [""]


# ═════════════════════════════════════════════════════════════════════════════
# Boilerplate padding - two-column policy wording carrying trigger words
# ═════════════════════════════════════════════════════════════════════════════
_WORDING_LEFT = [
    "SECTION I - COVERAGES", "",
    "COVERAGE A BODILY INJURY AND PROPERTY",
    "DAMAGE LIABILITY", "",
    "1. Insuring Agreement",
    "a. We will pay those sums that the insured",
    "becomes legally obligated to pay as damages",
    "because of \"bodily injury\" or \"property",
    "damage\" to which this insurance applies. We",
    "will have the right and duty to defend the",
    "insured against any \"suit\" seeking those",
    "damages. However, we will have no duty to",
    "defend the insured against any \"suit\" seeking",
    "damages for \"bodily injury\" or \"property",
    "damage\" to which this insurance does not",
    "apply.",
    "b. This insurance applies to \"bodily injury\"",
    "and \"property damage\" only if the \"bodily",
    "injury\" or \"property damage\" is caused by an",
    "\"occurrence\" that takes place in the",
    "\"coverage territory\".",
    "2. Exclusions",
    "This insurance does not apply to:",
    "a. Expected Or Intended Injury",
    "b. Contractual Liability",
    "c. Liquor Liability",
    "\"Bodily injury\" or \"property damage\" for",
    "which any insured may be held liable by",
    "reason of causing or contributing to the",
    "intoxication of any person.",
]
_WORDING_RIGHT = [
    "This exclusion applies even if the claims",
    "against any insured allege negligence or",
    "other wrongdoing in the supervision, hiring,",
    "employment, training or monitoring of others",
    "by that insured.",
    "d. Workers Compensation And Similar Laws",
    "Any obligation of the insured under a workers",
    "compensation, disability benefits or",
    "unemployment compensation law or any similar",
    "law.",
    "e. Employer's Liability",
    "\"Bodily injury\" to an \"employee\" of the",
    "insured arising out of and in the course of",
    "employment by the insured.",
    "This exclusion does not apply to liability",
    "assumed by the insured under an \"insured",
    "contract\".",
    "f. Pollution",
    "\"Bodily injury\" or \"property damage\" arising",
    "out of the actual, alleged or threatened",
    "discharge, dispersal, seepage, migration,",
    "release or escape of \"pollutants\".",
    "g. Aircraft, Auto Or Watercraft",
    "This exclusion applies even if the claims",
    "allege negligence in the supervision or",
    "maintenance of the aircraft or watercraft.",
    "h. Mobile Equipment",
    "i. War",
    "j. Damage To Property",
    "k. Damage To Your Product",
    "l. Damage To Your Work",
]


def pad_to_target() -> None:
    n = 1
    while len(PAGES) < TARGET_PAGES:
        PAGES.append(two_column(
            f"COMMERCIAL GENERAL LIABILITY COVERAGE FORM - CG 00 01 04 13 "
            f"(PART {n})", _WORDING_LEFT, _WORDING_RIGHT))
        n += 1
    del PAGES[TARGET_PAGES:]


# ═════════════════════════════════════════════════════════════════════════════
# Render
# ═════════════════════════════════════════════════════════════════════════════
def render() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(PDF_PATH), pagesize=LETTER)
    for n, page in enumerate(PAGES, 1):
        page(c)
        _foot(c, n)
        c.showPage()
    c.save()
    return len(PAGES)




# ═════════════════════════════════════════════════════════════════════════════
# The answer key - a verdict for EVERY field on ACORD 125
# ═════════════════════════════════════════════════════════════════════════════
# Five verdicts, and every one of the 548 boxes gets exactly one.
V_EXPECT = "expect"            # the document states it; this value belongs HERE
V_NO_DATA = "blank_no_data"    # the document says nothing; the box must be EMPTY
V_BY_RULE = "blank_by_rule"    # the document DOES state something, and one of our
                               # own rules owns the blank anyway (a signature, an
                               # agency-profile code, a premium on a quote). A
                               # value here is a rule breach, not a lucky fill.
V_NA = "not_applicable"        # a row the document has no entity for
V_NOT_SCORED = "not_scored"    # generation-time metadata, nobody can pin it

FIELDS: Dict[str, dict] = {}


def _put(field: str, verdict: str, value: str = "", why: str = "",
         trap: str = "") -> None:
    if field in FIELDS:
        raise SystemExit(f"answer key: {field} assigned twice")
    FIELDS[field] = {"verdict": verdict, "value": value, "why": why, "trap": trap}


def _rows(base: str, letters: str, verdict: str, values=None, why: str = "",
          trap: str = "") -> None:
    """Assign a row family. `values` is a dict letter -> value, or None."""
    for ch in letters:
        v = (values or {}).get(ch)
        if v is None:
            _put(f"{base}_{ch}", verdict, "", why, trap)
        elif v == "":
            _put(f"{base}_{ch}", V_NO_DATA, "", why or "not stated for this row", trap)
        else:
            _put(f"{base}_{ch}", V_EXPECT, str(v), why, trap)


def _tick(field: str, on: bool, why: str = "", trap: str = "") -> None:
    """An ACORD checkbox. On means Y; off means an EMPTY box, never "N"."""
    if on:
        _put(field, V_EXPECT, "Y", why, trap)
    else:
        _put(field, V_NO_DATA, "", why or "the document does not assert this", trap)


def build_key() -> dict:
    schema = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json")
                        .read_text(encoding="utf-8"))
    I, L, Q = D.INSUREDS, D.LOCATIONS, D.QUESTIONS
    FIELDS.clear()

    # ── FORM ─────────────────────────────────────────────────────────────────
    _put("Form_EditionIdentifier_A", V_EXPECT, "ACORD 125 (2025/03)",
         "read off the template, not the document")
    _put("Form_CompletionDate_A", V_NOT_SCORED, "",
         "the date the form is generated - cannot be pinned in a fixture")

    # ── PRODUCER ─────────────────────────────────────────────────────────────
    _put("Producer_FullName_A", V_NOT_SCORED, D.PRODUCER, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_MailingAddress_LineOne_A", V_NOT_SCORED, D.PRODUCER_L1, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_MailingAddress_LineTwo_A", V_NOT_SCORED, D.PRODUCER_L2, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_MailingAddress_CityName_A", V_NOT_SCORED, D.PRODUCER_CITY, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_MailingAddress_StateOrProvinceCode_A", V_NOT_SCORED, D.PRODUCER_STATE, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_MailingAddress_PostalCode_A", V_NOT_SCORED, D.PRODUCER_ZIP, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_ContactPerson_FullName_A", V_NOT_SCORED, D.PRODUCER_CONTACT, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_ContactPerson_PhoneNumber_A", V_NOT_SCORED, D.PRODUCER_PHONE, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_ContactPerson_EmailAddress_A", V_NOT_SCORED, D.PRODUCER_EMAIL, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_AuthorizedRepresentative_FullName_A", V_NOT_SCORED, D.PRODUCER_CONTACT, "resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded document - see v1-20AUG.md 'ORBIN - who is this party'. Scored manually against the account, not by this key")
    _put("Producer_FaxNumber_A", V_NO_DATA, "",
         "the document says 'FAX not provided'", trap="must not take the phone")
    for f, why in (("Producer_CustomerIdentifier_A", "agency customer id"),
                   ("Producer_NationalIdentifier_A", "NPN"),
                   ("Producer_StateLicenseIdentifier_A", "state producer licence")):
        _put(f, V_NO_DATA, "",
             f"{why} lives in the agency profile, never in an uploaded document",
             trap="a dec page's 'Agent Number' must not land here")
    _put("Producer_AuthorizedRepresentative_Signature_A", V_BY_RULE, "",
         "AUTHORSHIP: a machine never signs for the producer")

    # ── INSURER: the carrier RECEIVING the submission ────────────────────────
    _put("Insurer_FullName_A", V_EXPECT, D.CARRIER,
         "the broker's cover sheet names the carrier being submitted to",
         trap=f"must not be {D.EXP_CARRIER} (the EXPIRING carrier)")
    _put("Insurer_NAICCode_A", V_EXPECT, D.CARRIER_NAIC,
         trap=f"must not be {D.EXP_CARRIER_NAIC} (the expiring carrier's NAIC)")
    for f in ("Insurer_Underwriter_FullName_A", "Insurer_Underwriter_OfficeIdentifier_A"):
        _put(f, V_NO_DATA, "", "no underwriter is named anywhere in the package")
    for f in ("Insurer_ProducerIdentifier_A", "Insurer_SubProducerIdentifier_A",
              "Insurer_ProductCode_A", "Insurer_ProductDescription_A"):
        _put(f, V_NO_DATA, "", "carrier-assigned codes, not in any document")

    # ── POLICY: the policy being APPLIED FOR ─────────────────────────────────
    _put("Policy_EffectiveDate_A", V_EXPECT, D.PROPOSED_EFF,
         "the PROPOSED term, not the expiring one",
         trap=f"must not be {D.EXP_EFF}")
    _put("Policy_ExpirationDate_A", V_EXPECT, D.PROPOSED_EXP,
         trap=f"must not be {D.EXP_EXP}")
    _put("Policy_PolicyNumberIdentifier_A", V_NO_DATA, "",
         "new business quote - no policy number exists yet",
         trap="must not take the expiring GL number or an ISO form number")
    _tick("Policy_Status_QuoteIndicator_A", True, "the cover sheet states QUOTE")
    for st in ("Issue", "Bound", "Change", "Cancel", "Renew"):
        _tick(f"Policy_Status_{st}Indicator_A", False,
              "the only status the document states is QUOTE")
    for f in ("Policy_Status_EffectiveDate_A", "Policy_Status_EffectiveTime_A"):
        _put(f, V_NO_DATA, "",
             "ACORD: this is for bound / change / cancel, not for a quote")
    _tick("Policy_Status_EffectiveTimeAMIndicator_A", False, "no status date applies")
    _tick("Policy_Status_EffectiveTimePMIndicator_A", False, "no status date applies")

    lob_on = {
        "CommercialGeneralLiability": "Commercial General Liability",
        "CommercialProperty": "Commercial Property",
        "BusinessAutoIndicator": "Business Auto",
        "UmbrellaIndicator": "Commercial Umbrella",
        "CommercialInlandMarineIndicator": "Commercial Inland Marine",
    }
    lob_off = ["BoilerAndMachineryIndicator", "BusinessOwnersIndicator",
               "CrimeIndicator", "CyberAndPrivacy", "FiduciaryLiabilityIndicator",
               "GarageAndDealersIndicator", "LiquorLiabilityIndicator",
               "MotorCarrierIndicator", "TruckersIndicator", "YachtIndicator"]
    for k, name in lob_on.items():
        _tick(f"Policy_LineOfBusiness_{k}_A", True, f"{name} is requested")
    for k in lob_off:
        _tick(f"Policy_LineOfBusiness_{k}_A", False,
              "GRANT: the document NAMES this line only to record that it is "
              "not afforded - the words are present, the coverage is not")
    _rows("Policy_LineOfBusiness_OtherIndicator", "ABCDEF", V_NO_DATA,
          why="every requested line has its own named box")
    _rows("Policy_LineOfBusiness_OtherLineOfBusinessDescription", "ABCDEF", V_NO_DATA)

    prem_boxes = ["BoilerAndMachinery", "BusinessOwners", "CommercialInlandMarine",
                  "CommercialProperty", "CommercialVehicle", "CommercialUmbrella",
                  "Crime", "CyberAndPrivacy", "Fiduciary", "GarageAndDealers",
                  "LiquorLiability", "MotorCarrier", "Truckers", "Yacht"]
    for b in prem_boxes:
        _put(f"{b}LineOfBusiness_PremiumAmount_A", V_BY_RULE, "",
             "a quote is not priced - the expiring premiums belong in the "
             "PRIOR CARRIER grid, not here",
             trap="must not take an expiring line premium")
    _put("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", V_BY_RULE, "",
         "a quote is not priced", trap="must not be $73,410 (the expiring GL premium)")
    _put("Policy_Payment_EstimatedTotalAmount_A", V_BY_RULE, "",
         "no premium has been quoted",
         trap=f"must not be {D.EXP_TOTAL_PREMIUM} (the expiring package total)")
    for f in ("Policy_Payment_DirectBillIndicator_A",
              "Policy_Payment_ProducerBillIndicator_A",
              "Policy_Payment_PaymentScheduleCode_A",
              "Policy_Payment_DepositAmount_A",
              "Policy_Payment_MinimumPremiumAmount_A",
              "Policy_PaymentMethod_MethodDescription_A"):
        _put(f, V_NO_DATA, "", "no billing or payment plan is stated anywhere")
    _put("Policy_Audit_FrequencyCode_A", V_EXPECT, "A",
         "the document prints the WORD 'Annual'; ACORD's own tooltip asks for "
         "the CODE - A / S / Q / M / O")
    _put("Policy_InformationPracticesNoticeIndicator_A", V_BY_RULE, "",
         "AUTHORSHIP: an attestation that the AGENCY did something")

    # ATTACHMENTS ARE ABOUT THE SUBMISSION WE PRODUCE (ruling, 21 Sep 2026).
    # The box asks what accompanies THIS application. The uploaded file's own
    # cover sheet describes a DIFFERENT submission - a broker's old attachment
    # list cannot say what will be stapled to ours. So a box ticks only when
    # this package provably contains what it names: a form we generate, or a
    # schedule we fill. This kit generates ACORD 125 alone, so every one of
    # them is an owned blank, and the five the document lists are the proof
    # that a stated attachment list does NOT reach these boxes.
    for k in ("AccountsReceivableValuablePapersIndicator", "DealerIndicator",
              "ElectronicDataProcessingIndicator", "GlassAndSignIndicator",
              "InstallationBuildersRiskIndicator", "OpenCargoIndicator",
              "VehicleScheduleIndicator", "DriverInformationScheduleIndicator"):
        _put(f"Policy_SectionAttached_{k}_A", V_BY_RULE, "",
             "an attachment box names what THIS package contains; only "
             "ACORD 125 is generated here",
             trap="the document lists Vehicle Schedule and Driver Information "
                  "Schedule as attached to the BROKER's submission - that is "
                  "not this one")
    _rows("Policy_SectionAttached_OtherPremiumAmount", "ABCDEF", V_BY_RULE,
          why="a quote is not priced")

    # ── COMMERCIALPOLICY: attachments ────────────────────────────────────────
    att_on = {}
    att_off = ["ContractorsSupplementIndicator", "StatementOfValuesIndicator",
               "LossSummaryIndicator",
               "AdditionalInterestScheduleIndicator", "AdditionalPremisesScheduleIndicator",
               "ApartmentBuildingSupplementIndicator", "CondominiumAssociationByLawsIndicator",
               "CoveragesScheduleIndicator", "HotelMotelSupplementIndicator",
               "InternationalLiabilityExposureSupplementIndicator",
               "InternationalPropertyExposureSupplementIndicator",
               "PremiumPaymentSupplementIndicator", "ProfessionalLiabilitySupplementIndicator",
               "RestaurantTavernSupplementIndicator", "StateSupplementIndicator",
               "VacantBuildingSupplementIndicator"]
    for k, name in att_on.items():
        _tick(f"CommercialPolicy_Attachment_{k}_A", True,
              f"the cover sheet lists '{name}' as attached")
    for k in att_off:
        _put(f"CommercialPolicy_Attachment_{k}_A", V_BY_RULE, "",
             "an attachment box names what THIS package contains; only "
             "ACORD 125 is generated here (see the SectionAttached note above)")
    _rows("CommercialPolicy_Attachment_OtherIndicator", "ABCDEF", V_NO_DATA,
          why="every attachment named has its own box")
    _rows("CommercialPolicy_Attachment_OtherDescription", "ABCDEF", V_NO_DATA)

    # ── COMMERCIALPOLICY: the fifteen questions and their dependent blocks ───
    for code, q in Q.items():
        f = f"CommercialPolicy_Question_{code}Code_A"
        if q["answer"] is None:
            _put(f, V_NO_DATA, "",
                 f"question {q['n']} is never put to the applicant anywhere in "
                 f"the package. BLANK IS NOT 'No' - this is the client's own "
                 f"flagship rule",
                 trap="a defaulted 'N' here is the defect the kit exists to catch")
        else:
            _put(f, V_EXPECT, q["answer"], f"question {q['n']}: {q['q']}")

    # explanation blocks - one per question, filled only where the answer is Y
    _put("CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A",
         V_EXPECT, Q["ABC"]["text"], "question 3 answered Y")
    _put("CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A",
         V_EXPECT, Q["KAN"]["text"], "question 14 answered Y")
    _put("CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A",
         V_NO_DATA, "", "question 15 is N - a No needs no explanation")
    _put("CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A",
         V_NO_DATA, "", "question 13 is N")
    _put("CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A",
         V_NO_DATA, "", "question 7 is N")
    _put("CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A",
         V_NO_DATA, "", "question 6 is N")

    # question 9 - never asked. The WHOLE dependent block must stay empty.
    for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate",
                "_ResolutionDescription"):
        _rows(f"CommercialPolicy_ForeclosureRepossessionBankruptcy{suf}", "AB",
              V_NO_DATA,
              why="question 9 is never addressed - nothing may appear here")

    # question 10 - Y, and fully resolved
    _put("CommercialPolicy_JudgementOrLienExplanation_A", V_EXPECT, Q["KAL"]["text"],
         "question 10 answered Y")
    _put("CommercialPolicy_JudgementOrLien_OccurrenceDate_A", V_EXPECT,
         Q["KAL"]["occurrence"])
    _put("CommercialPolicy_JudgementOrLien_ResolutionDate_A", V_EXPECT,
         Q["KAL"]["resolution_date"])
    _put("CommercialPolicy_JudgementOrLien_ResolutionDescription_A", V_EXPECT,
         Q["KAL"]["resolution"])
    for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate",
                "_ResolutionDescription"):
        _put(f"CommercialPolicy_JudgementOrLien{suf}_B", V_NA, "",
             "only one judgment or lien is disclosed")

    # question 8 - Y, and deliberately NOT resolved. The half-filled block.
    _put("CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", V_EXPECT,
         Q["AAF"]["text"], "question 8 answered Y")
    _put("CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A", V_EXPECT,
         Q["AAF"]["occurrence"])
    _put("CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A", V_NO_DATA,
         "", "the violation is OPEN - no resolution date exists",
         trap="a date invented here asserts the risk is cured")
    _put("CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A",
         V_NO_DATA, "", "the violation is open")
    for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate",
                "_ResolutionDescription"):
        _put(f"CommercialPolicy_UncorrectedFireCodeViolation{suf}_B", V_NA, "",
             "only one violation is disclosed")

    # question 2's safety-programme detail
    _tick("CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A", True,
          "a written safety manual is stated")
    _tick("CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B", True,
          f"a Director of Safety ({D.SAFETY['director']}) is stated")
    _tick("CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B", True,
          "monthly safety meetings are stated")
    _tick("CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B", False,
          "the document explicitly makes NO statement about any OSHA programme",
          trap="Blank is not No, at checkbox level too")
    _tick("CommercialPolicy_FormalSafetyProgram_OtherIndicator_B", False,
          "no other safety element is stated")
    _put("CommercialPolicy_FormalSafetyProgram_OtherDescription_B", V_NO_DATA, "",
         "no other safety element is stated")

    _put("CommercialPolicy_OperationsDescription_A", V_EXPECT, D.PRIMARY_OPERATIONS,
         "ACORD tooltip: the description of PRIMARY operations")
    _put("CommercialPolicy_OperationsDescription_B", V_EXPECT,
         D.OTHER_INSURED_OPERATIONS.replace("\n", " "),
         "ACORD tooltip: operations for OTHER NAMED INSUREDS")
    # The applicant's own remark AND the loss the three-row grid cannot print.
    # Four losses, three rows: `_resolve_loss_overflow_remark` (shipped 2 Sep)
    # discloses the fourth here, lossless, and keeps the stated remark beside
    # it. This key was written expecting the remark alone; the old scorer's
    # substring rule hid that until 28 Sep.
    _ov = D.LOSSES[3]
    _put("CommercialPolicy_RemarkText_A", V_EXPECT,
         f"{D.REMARKS} Additional loss not shown in the loss grid: "
         f"{_ov['occurrence']} {_ov['claim_no']} {_ov['line']} {_ov['desc']} "
         f"paid {_ov['paid']} reserved {_ov['reserved']}.",
         "the stated remark plus the overflowed fourth loss (lossless)")

    # ── NAMEDINSURED rows A-C (a fourth entity is stated and has no slot) ────
    ent_map = {"LLC": "LimitedLiabilityCorporationIndicator",
               "Corporation": "CorporationIndicator"}
    all_ent = ["CorporationIndicator", "IndividualIndicator", "JointVentureIndicator",
               "LimitedLiabilityCorporationIndicator", "NotForProfitIndicator",
               "OtherIndicator", "PartnershipIndicator",
               "SubchapterSCorporationIndicator", "TrustIndicator"]
    for ch, ins in zip("ABC", I[:3]):
        _put(f"NamedInsured_FullName_{ch}", V_EXPECT, ins["name"])
        _put(f"NamedInsured_TaxIdentifier_{ch}", V_EXPECT, ins["fein"],
             trap=f"must not be {D.EXP_ACCOUNT_NO} - 7 digits is an account "
                  f"number, a FEIN is 9")
        _put(f"NamedInsured_SICCode_{ch}", V_EXPECT, ins["sic"])
        _put(f"NamedInsured_NAICSCode_{ch}", V_EXPECT, ins["naics"],
             trap="must not be the GL class code printed beside it")
        _put(f"NamedInsured_Primary_PhoneNumber_{ch}", V_EXPECT, ins["phone"],
             trap="must not be the producer's or the carrier's number")
        _put(f"NamedInsured_MailingAddress_LineOne_{ch}", V_EXPECT, ins["l1"])
        _put(f"NamedInsured_MailingAddress_CityName_{ch}", V_EXPECT, ins["city"])
        _put(f"NamedInsured_MailingAddress_StateOrProvinceCode_{ch}", V_EXPECT,
             ins["state"])
        _put(f"NamedInsured_MailingAddress_PostalCode_{ch}", V_EXPECT, ins["zip"])
        if ins["l2"]:
            _put(f"NamedInsured_MailingAddress_LineTwo_{ch}", V_EXPECT, ins["l2"])
        else:
            _put(f"NamedInsured_MailingAddress_LineTwo_{ch}", V_NO_DATA, "",
                 "this entity's address has no second line",
                 trap="must not repeat line one or the city")
        if ins["gl_code"]:
            _put(f"NamedInsured_GeneralLiabilityCode_{ch}", V_EXPECT, ins["gl_code"])
        else:
            _put(f"NamedInsured_GeneralLiabilityCode_{ch}", V_NO_DATA, "")
        if ins["web"]:
            _put(f"NamedInsured_Primary_WebsiteAddress_{ch}", V_EXPECT, ins["web"])
        else:
            _put(f"NamedInsured_Primary_WebsiteAddress_{ch}", V_NO_DATA, "",
                 "this entity states no website",
                 trap=f"must not be {D.EXP_CARRIER_WEB} - the carrier's own site, "
                      f"printed in 100 page headers")
        if ins["members"]:
            _put(f"NamedInsured_LegalEntity_MemberManagerCount_{ch}", V_EXPECT,
                 ins["members"])
        else:
            _put(f"NamedInsured_LegalEntity_MemberManagerCount_{ch}", V_NO_DATA, "",
                 "a corporation has no members or managers")
        on = ent_map[ins["entity"]]
        for e in all_ent:
            _tick(f"NamedInsured_LegalEntity_{e}_{ch}", e == on,
                  f"entity {ch} is a {ins['entity']}")
        _put(f"NamedInsured_LegalEntity_OtherDescription_{ch}", V_NO_DATA, "")
    _put("NamedInsured_BusinessStartDate_A", V_EXPECT, I[0]["start"])
    for ch in "AB":
        ct = D.CONTACTS["AB".index(ch)]
        _put(f"NamedInsured_Contact_ContactDescription_{ch}", V_EXPECT, ct["type"])
        _put(f"NamedInsured_Contact_FullName_{ch}", V_EXPECT, ct["name"])
        _put(f"NamedInsured_Contact_PrimaryPhoneNumber_{ch}", V_EXPECT, ct["phone"])
        _tick(f"NamedInsured_Contact_PrimaryBusinessPhoneIndicator_{ch}", True,
              "the document labels it a business phone")
        for k in ("PrimaryCellPhoneIndicator", "PrimaryHomePhoneIndicator",
                  "SecondaryBusinessPhoneIndicator", "SecondaryCellPhoneIndicator",
                  "SecondaryHomePhoneIndicator"):
            _tick(f"NamedInsured_Contact_{k}_{ch}", False,
                  "only one phone is stated for this contact")
        _put(f"NamedInsured_Contact_SecondaryPhoneNumber_{ch}", V_NO_DATA, "")
        _put(f"NamedInsured_Contact_SecondaryEmailAddress_{ch}", V_NO_DATA, "")
        if ct["email"]:
            _put(f"NamedInsured_Contact_PrimaryEmailAddress_{ch}", V_EXPECT, ct["email"])
        else:
            _put(f"NamedInsured_Contact_PrimaryEmailAddress_{ch}", V_NO_DATA, "",
                 "this contact states no e-mail address",
                 trap="must not borrow the other contact's address")
    _put("NamedInsured_Initials_A", V_BY_RULE, "",
         "AUTHORSHIP: initials are a signature")
    _put("NamedInsured_Signature_A", V_BY_RULE, "", "AUTHORSHIP")
    _put("NamedInsured_SignatureDate_A", V_BY_RULE, "",
         "AUTHORSHIP: undated until the insured actually signs")

    # ── BUSINESSINFORMATION ──────────────────────────────────────────────────
    _tick("BusinessInformation_BusinessType_ContractorIndicator_A", True,
          f"the document states NATURE OF BUSINESS: {D.NATURE_OF_BUSINESS}")
    for k in ("ApartmentsIndicator", "CondominiumsIndicator", "InstitutionalIndicator",
              "ManufacturingIndicator", "OfficeIndicator", "OtherIndicator",
              "RestaurantIndicator", "RetailIndicator", "ServiceIndicator",
              "WholesaleIndicator"):
        _tick(f"BusinessInformation_BusinessType_{k}_A", False,
              "the document names exactly ONE nature of business",
              trap="'fabrication', 'offices' and 'service' all appear in the "
                   "operations prose - none of them is a stated nature")
    _put("BusinessInformation_BusinessType_OtherDescription_A", V_NO_DATA, "")
    _put("BusinessInformation_ParentOrganizationName_A", V_EXPECT, D.PARENT_ORG,
         "question 1a's dependent value")
    _rows("BusinessInformation_FullTimeEmployeeCount", "ABCD", V_EXPECT,
          {ch: L[i]["ft"] for i, ch in enumerate("ABCD")},
          why="per PREMISES, not the applicant total",
          trap=f"must not be {D.TOTAL_FT} - that is the whole company")
    _rows("BusinessInformation_PartTimeEmployeeCount", "ABCD", V_EXPECT,
          {ch: L[i]["pt"] for i, ch in enumerate("ABCD")},
          trap=f"must not be {D.TOTAL_PT}")

    # ── COMMERCIALSTRUCTURE rows A-D (a fifth premises has no slot) ──────────
    _rows("CommercialStructure_Location_ProducerIdentifier", "ABCD", V_EXPECT,
          {ch: L[i]["num"] for i, ch in enumerate("ABCD")}, why="the LOC # box")
    _rows("CommercialStructure_Building_ProducerIdentifier", "ABCD", V_EXPECT,
          {ch: L[i]["bldg"] for i, ch in enumerate("ABCD")})
    _rows("CommercialStructure_PhysicalAddress_LineOne", "ABCD", V_EXPECT,
          {ch: L[i]["l1"] for i, ch in enumerate("ABCD")})
    _rows("CommercialStructure_PhysicalAddress_LineTwo", "ABCD", V_EXPECT,
          {ch: L[i]["l2"] for i, ch in enumerate("ABCD")},
          trap="a premises with no second line must stay blank, not repeat line one")
    _rows("CommercialStructure_PhysicalAddress_CityName", "ABCD", V_EXPECT,
          {ch: L[i]["city"] for i, ch in enumerate("ABCD")})
    _rows("CommercialStructure_PhysicalAddress_CountyName", "ABCD", V_EXPECT,
          {ch: L[i]["county"] for i, ch in enumerate("ABCD")},
          trap="Location 003 states NO county - it must not be guessed from the city")
    _rows("CommercialStructure_PhysicalAddress_StateOrProvinceCode", "ABCD", V_EXPECT,
          {ch: L[i]["state"] for i, ch in enumerate("ABCD")})
    _rows("CommercialStructure_PhysicalAddress_PostalCode", "ABCD", V_EXPECT,
          {ch: L[i]["zip"] for i, ch in enumerate("ABCD")})
    _rows("CommercialStructure_AnnualRevenueAmount", "ABCD", V_EXPECT,
          {ch: L[i]["revenue"] for i, ch in enumerate("ABCD")},
          why="revenue for THIS location",
          trap=f"must not be {D.TOTAL_REVENUE} (the company total) and must "
               f"never be {D.TOTAL_PAYROLL} (payroll is not revenue)")
    for i, ch in enumerate("ABCD"):
        loc = L[i]
        _tick(f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{ch}",
              loc["inside"], f"Location {loc['num']} within city limits: "
                             f"{'Yes' if loc['inside'] else 'No'}")
        _tick(f"CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_{ch}",
              not loc["inside"])
        _tick(f"CommercialStructure_InsuredInterest_OwnerIndicator_{ch}",
              loc["interest"] == "Owner", f"interest: {loc['interest']}")
        _tick(f"CommercialStructure_InsuredInterest_TenantIndicator_{ch}",
              loc["interest"] == "Tenant")
        _tick(f"CommercialStructure_InsuredInterest_OtherIndicator_{ch}", False,
              "the interest is owner or tenant, never other")
        _put(f"CommercialStructure_InsuredInterest_OtherDescription_{ch}", V_NO_DATA, "")
        _tick(f"CommercialStructure_RiskLocation_OtherIndicator_{ch}", False)
        _put(f"CommercialStructure_RiskLocation_OtherDescription_{ch}", V_NO_DATA, "")
        _put(f"CommercialStructure_Question_ABBCode_{ch}", V_EXPECT,
             loc["leased_to_others"], "any area leased to others")
    _put("CommercialStructure_InstallationRepairWorkPercent_A", V_EXPECT,
         D.INSTALL_PCT)
    _put("CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", V_EXPECT,
         D.INSTALL_OFF_PCT)

    # ── BUILDINGOCCUPANCY / CONSTRUCTION ─────────────────────────────────────
    _rows("BuildingOccupancy_OccupiedArea", "ABCD", V_EXPECT,
          {ch: L[i]["occupied"] for i, ch in enumerate("ABCD")})
    _rows("BuildingOccupancy_OpenToPublicArea", "ABCD", V_EXPECT,
          {ch: L[i]["public"] for i, ch in enumerate("ABCD")})
    _rows("BuildingOccupancy_OperationsDescription", "ABCD", V_EXPECT,
          {ch: L[i]["ops"] for i, ch in enumerate("ABCD")},
          why="ACORD tooltip: operations BY PREMISES",
          trap="must not repeat the applicant-level description of operations")
    _rows("Construction_BuildingArea", "ABCD", V_EXPECT,
          {ch: L[i]["total_area"] for i, ch in enumerate("ABCD")},
          why="TOTAL building area, not the occupied area",
          trap="Location 001 occupies 9,400 of a 26,000 sq ft building - the "
               "two numbers are different facts")

    # ── LOSSHISTORY rows A-C (a fourth claim has no slot) ────────────────────
    LS = D.LOSSES
    _rows("LossHistory_OccurrenceDate", "ABC",
          V_EXPECT, {ch: LS[i]["occurrence"] for i, ch in enumerate("ABC")})
    _rows("LossHistory_ClaimDate", "ABC", V_EXPECT,
          {ch: LS[i]["claim"] for i, ch in enumerate("ABC")},
          trap="the claim date and the occurrence date differ on claim 2")
    _rows("LossHistory_LineOfBusiness", "ABC", V_EXPECT,
          {ch: LS[i]["line"] for i, ch in enumerate("ABC")})
    _rows("LossHistory_OccurrenceDescription", "ABC", V_EXPECT,
          {ch: LS[i]["desc"] for i, ch in enumerate("ABC")},
          why="the description column physically overruns the PAID column in the "
              "source - this is the riffle repair, measured end to end")
    _rows("LossHistory_PaidAmount", "ABC", V_EXPECT,
          {ch: LS[i]["paid"] for i, ch in enumerate("ABC")})
    _rows("LossHistory_ReservedAmount", "ABC", V_EXPECT,
          {ch: LS[i]["reserved"] for i, ch in enumerate("ABC")})
    _rows("LossHistory_ClaimStatus_OpenCode", "ABC", V_EXPECT,
          {ch: ("Y" if LS[i]["open"] == "O" else "N") for i, ch in enumerate("ABC")},
          why="ACORD tooltip: 'Enter Y for a Yes response' - this box asks IS "
              "THE CLAIM OPEN, it is not an O/C status code")
    _rows("LossHistory_ClaimStatus_SubrogationCode", "ABC", V_EXPECT,
          {ch: LS[i]["subro"] for i, ch in enumerate("ABC")})
    _put("LossHistory_InformationYearCount_A", V_EXPECT, D.LOSS_YEARS)
    _put("LossHistory_TotalAmount_A", V_EXPECT, D.TOTAL_PAID,
         "ACORD tooltip: 'the amount that has been PAID on all losses to date'",
         trap=f"must not be {D.TOTAL_INCURRED} - that is paid PLUS reserved, a "
              f"different figure the document also prints")
    _tick("LossHistory_NoPriorLossesIndicator_A", False,
          "there are four documented claims",
          trap="ticking this contradicts the loss run on the same package")

    # ── PRIORCOVERAGE: year A documented, year B partial, year C ABSENT ──────
    exp_by_line = {e["line"]: e for e in D.EXPIRING_LINES}
    p2_by_line = {e["line"]: e for e in D.PRIOR2_LINES}
    grid = {"GeneralLiability": "General Liability",
            "Property": "Commercial Property",
            "Automobile": "Business Auto"}
    _put("PriorCoverage_PolicyYear_A", V_EXPECT, D.PRIOR1_YEAR.split("-")[0],
         "ACORD tooltip: 'Enter year' - a single year. The document prints "
         "the span; this box takes the year the term began")
    _put("PriorCoverage_PolicyYear_B", V_EXPECT, D.PRIOR2_YEAR.split("-")[0])
    _put("PriorCoverage_PolicyYear_C", V_NO_DATA, "",
         "only two policy years are documented",
         trap="the client's own rule: do not manufacture carrier history")
    for box, line in grid.items():
        e1, e2 = exp_by_line[line], p2_by_line[line]
        _put(f"PriorCoverage_{box}_InsurerFullName_A", V_EXPECT, D.EXP_CARRIER)
        _put(f"PriorCoverage_{box}_PolicyNumberIdentifier_A", V_EXPECT, e1["policy"])
        _put(f"PriorCoverage_{box}_TotalPremiumAmount_A", V_EXPECT, e1["premium"],
             "the expiring premium belongs HERE, not in a page-one premium box")
        _put(f"PriorCoverage_{box}_EffectiveDate_A", V_EXPECT, D.EXP_EFF)
        _put(f"PriorCoverage_{box}_ExpirationDate_A", V_EXPECT, D.EXP_EXP)
        _put(f"PriorCoverage_{box}_InsurerFullName_B", V_EXPECT, D.PRIOR2_CARRIER)
        _put(f"PriorCoverage_{box}_PolicyNumberIdentifier_B", V_EXPECT, e2["policy"])
        _put(f"PriorCoverage_{box}_TotalPremiumAmount_B", V_EXPECT, e2["premium"])
        _put(f"PriorCoverage_{box}_EffectiveDate_B", V_EXPECT, D.PRIOR2_EFF)
        _put(f"PriorCoverage_{box}_ExpirationDate_B", V_EXPECT, D.PRIOR2_EXP)
        for k in ("InsurerFullName", "PolicyNumberIdentifier", "TotalPremiumAmount",
                  "EffectiveDate", "ExpirationDate"):
            _put(f"PriorCoverage_{box}_{k}_C", V_NO_DATA, "",
                 "policy year three is not documented")
    umb = exp_by_line["Commercial Umbrella"]
    # NOT SCORED (28 Sep). The 21 Sep "correction" to "Commercial Umbrella" was
    # itself wrong: ACORD's tooltip is "Enter CODE: the line of business code".
    # The repo holds no ACORD line-of-business code table, so neither the
    # phrase nor any code can be pinned without inventing one.
    _put("PriorCoverage_OtherLine_LineOfBusinessCode_A", V_NOT_SCORED, "",
         "ACORD wants a line-of-business CODE and no code table exists in the "
         "repo - open item, see improving125-21sep.md ROUND 2")
    _put("PriorCoverage_OtherLine_InsurerFullName_A", V_EXPECT, D.UMB_CARRIER,
         "the umbrella sits with a THIRD carrier",
         trap=f"must not be {D.EXP_CARRIER}")
    _put("PriorCoverage_OtherLine_PolicyNumberIdentifier_A", V_EXPECT, umb["policy"])
    _put("PriorCoverage_OtherLine_TotalPremiumAmount_A", V_EXPECT, umb["premium"])
    _put("PriorCoverage_OtherLine_EffectiveDate_A", V_EXPECT, D.EXP_EFF)
    _put("PriorCoverage_OtherLine_ExpirationDate_A", V_EXPECT, D.EXP_EXP)
    for ch, why in (("B", "no umbrella was carried in policy year two"),
                    ("C", "policy year three is not documented")):
        for k in ("InsurerFullName", "PolicyNumberIdentifier", "TotalPremiumAmount",
                  "EffectiveDate", "ExpirationDate"):
            _put(f"PriorCoverage_OtherLine_{k}_{ch}", V_NO_DATA, "", why)

    # ── OTHERPOLICY: question 4 is N ─────────────────────────────────────────
    _rows("OtherPolicy_LineOfBusinessCode", "ABCD", V_NO_DATA,
          why="question 4 is N - the applicant has no other policy with the "
              "carrier receiving this submission",
          trap="the four EXPIRING policies belong to a different carrier entirely")
    _rows("OtherPolicy_PolicyNumberIdentifier", "ABCD", V_NO_DATA,
          trap="must not list the expiring policy numbers")

    # ── SUBSIDIARY: question 1b is Y ─────────────────────────────────────────
    # ROW A is question 1a's PARENT block, ROW B is question 1b's SUBSIDIARY
    # block - that is the printed layout, confirmed against the generated form.
    _put("Subsidiary_ParentOwnershipPercent_A", V_EXPECT, D.PARENT_PCT,
         "1a: the parent's stake IN THE APPLICANT")
    _put("Subsidiary_ParentSubsidiaryRelationshipDescription_A", V_EXPECT,
         D.PARENT_RELATION, "1a: the parent relationship")
    _put("Subsidiary_OrganizationName_A", V_EXPECT, D.SUBSIDIARY_ORG,
         "1b: the applicant's own subsidiary")
    _put("Subsidiary_ParentOwnershipPercent_B", V_EXPECT, D.SUBSIDIARY_PCT,
         "1b: the applicant's stake in its subsidiary",
         trap=f"must not be {D.PARENT_PCT} - that is the other relationship")
    _put("Subsidiary_ParentSubsidiaryRelationshipDescription_B", V_EXPECT,
         D.SUBSIDIARY_RELATION, "1b: the subsidiary relationship")

    # ── CANCELNONRENEW: question 5 is N, so the whole block stays empty ──────
    for k in ("AgentNoLongerWritesForInsurerIndicator", "NonPaymentIndicator",
              "NonRenewalIndicator", "OtherIndicator", "UnderwritingIndicator",
              "UnderwritingConditionCorrectedIndicator"):
        _tick(f"CancelNonRenew_{k}_A", False,
              "question 5 is N - nothing was declined, cancelled or non-renewed",
              trap="this whole block is a fabrication surface")
    _put("CancelNonRenew_OtherDescription_A", V_NO_DATA, "", "question 5 is N")
    _put("CancelNonRenew_UnderwritingConditionCorrectedDescription_A", V_NO_DATA, "",
         "question 5 is N")

    # ── ADDITIONALINTEREST: one full interest, plus a second NAME only ──────
    # ACORD 125 gives the second interest a name slot and nothing else, so the
    # mortgagee's address has nowhere to go. That is capacity, not a defect -
    # but it must not push the LOSS PAYEE's details out of row A.
    it0, it1 = D.INTERESTS[0], D.INTERESTS[1]
    _put("AdditionalInterest_FullName_A", V_EXPECT, it0["name"])
    # NOT the second interest. ACORD reuses this field for question 11 and its
    # tooltip says so: "As used here, this is the name of the trust." This
    # package answers question 11 NO, so the box is empty by rule - and the
    # second interest's name is exactly the value that must not land in it.
    # (Corrected 28 Sep 2026: this key expected the second interest here.)
    _put("AdditionalInterest_FullName_B", V_BY_RULE, "",
         "ACORD tooltip: 'this is the name of the trust' - question 11 is N",
         trap=f"must not be {it1['name']} - a second interest is not a trust")
    _put("AdditionalInterest_MailingAddress_LineOne_A", V_EXPECT, it0["l1"])
    _put("AdditionalInterest_MailingAddress_LineTwo_A", V_EXPECT, it0["l2"])
    _put("AdditionalInterest_MailingAddress_CityName_A", V_EXPECT, it0["city"])
    _put("AdditionalInterest_MailingAddress_StateOrProvinceCode_A", V_EXPECT,
         it0["state"])
    _put("AdditionalInterest_MailingAddress_PostalCode_A", V_EXPECT, it0["zip"])
    _put("AdditionalInterest_MailingAddress_CountryCode_A", V_NO_DATA, "",
         "a domestic address states no country")
    _put("AdditionalInterest_Primary_PhoneNumber_A", V_EXPECT, it0["phone"])
    _put("AdditionalInterest_Primary_EmailAddress_A", V_EXPECT, it0["email"])
    _put("AdditionalInterest_Primary_FaxNumber_A", V_NO_DATA, "", "no fax is stated")
    _put("AdditionalInterest_AccountNumberIdentifier_A", V_EXPECT, it0["account"])
    _put("AdditionalInterest_LoanAmount_A", V_EXPECT, it0["loan"])
    _put("AdditionalInterest_InterestRank_A", V_EXPECT, it0["rank"],
         "ACORD tooltip: 'Enter number' - a rank is 1, not the word First")
    _put("AdditionalInterest_InterestReasonDescription_A", V_EXPECT, it0["reason"])
    _put("AdditionalInterest_ItemDescription_A", V_EXPECT, it0["item"])
    _put("AdditionalInterest_Item_LocationProducerIdentifier_A", V_EXPECT, it0["loc"])
    _put("AdditionalInterest_CertificateRequiredIndicator_A", V_EXPECT, "Y",
         "the schedule states a certificate is required")
    _tick("AdditionalInterest_Interest_LossPayeeIndicator_A", True,
          "the schedule states the interest is LOSS PAYEE")
    for k in ("AdditionalInsuredIndicator", "BreachOfWarrantyIndicator",
              "CoOwnerIndicator", "EmployeeAsLessorIndicator",
              "LeasebackOwnerIndicator", "LendersLossPayableIndicator",
              "LienholderIndicator", "MortgageeIndicator", "OtherIndicator",
              "OwnerIndicator", "RegistrantIndicator", "TrusteeIndicator"):
        _tick(f"AdditionalInterest_Interest_{k}_A", False,
              "the schedule names exactly ONE interest type for row A",
              trap="'Mortgagee' is a real word in this document - it belongs to "
                   "the SECOND interest, which has no interest box on this form")
    _put("AdditionalInterest_Interest_OtherDescription_A", V_NO_DATA, "")
    _put("AdditionalInterest_InterestEndDate_A", V_NO_DATA, "",
         "no end date is stated")
    _tick("AdditionalInterest_PolicyRequiredIndicator_A", False, "not stated")
    _tick("AdditionalInterest_SendBillIndicator_A", False, "not stated")
    for k in ("AircraftProducerIdentifier", "AirportIdentifier",
              "BoatProducerIdentifier", "BuildingProducerIdentifier",
              "ScheduledItemClassCode", "ScheduledItemProducerIdentifier",
              "VehicleProducerIdentifier"):
        _put(f"AdditionalInterest_Item_{k}_A", V_NO_DATA, "",
             "the interest is in equipment at a location, not an aircraft, boat, "
             "building or vehicle")
    return schema


# ═════════════════════════════════════════════════════════════════════════════
# Assemble - into the shape `score_form_fill.py` already reads
# ═════════════════════════════════════════════════════════════════════════════
# A value may be REWORDED only where the box asks for narrative. Everywhere
# else - an identifier, an amount, a date, a code, a checkbox - the value is the
# value, and "close enough" is a wrong value on a signed application.
# Derived from ACORD's own tooltip ("Enter text:") plus the field's own name, so
# a new field classifies itself and nobody maintains a list.
_NARRATIVE_NAME = re.compile(
    r"(Description|Explanation|RemarkText|Operations|Relationship)", re.I)


def _match_mode(field: str, meta: dict) -> str:
    """`semantic` - the wording may differ if the meaning is the same.
    `exact`     - the value must match after normalisation."""
    tu = (meta.get("tu") or "").strip().lower()
    if (meta.get("ft") == "/Tx" and tu.startswith("enter text")
            and _NARRATIVE_NAME.search(field)):
        return "semantic"
    return "exact"


def assemble(schema: dict) -> dict:
    missing = [f for f in schema if f not in FIELDS]
    unknown = [f for f in FIELDS if f not in schema]
    if unknown:
        raise SystemExit(f"answer key names {len(unknown)} field(s) that are NOT "
                         f"on the real ACORD 125 schema: {unknown[:8]}")
    if missing:
        raise SystemExit(f"answer key has no verdict for {len(missing)} of the "
                         f"{len(schema)} fields: {missing[:12]}")

    for f, v in FIELDS.items():
        v["match"] = _match_mode(f, schema.get(f) or {})
    expect = {f: v["value"] for f, v in FIELDS.items() if v["verdict"] == V_EXPECT}
    semantic = sorted(f for f, v in FIELDS.items()
                      if v["verdict"] == V_EXPECT and v["match"] == "semantic")
    blanks = sorted(f for f, v in FIELDS.items()
                    if v["verdict"] in (V_NO_DATA, V_BY_RULE, V_NA))

    forbidden = {
        "NamedInsured_Primary_WebsiteAddress_*": [D.EXP_CARRIER_WEB],
        "NamedInsured_Primary_PhoneNumber_*": [D.EXP_CARRIER_PHONE, D.PRODUCER_PHONE],
        "NamedInsured_TaxIdentifier_*": [D.EXP_ACCOUNT_NO],
        "NamedInsured_NAICSCode_*": [i["gl_code"] for i in D.INSUREDS if i["gl_code"]],
        "NamedInsured_SICCode_*": [i["naics"] for i in D.INSUREDS],
        "Policy_PolicyNumberIdentifier_A": [
            "CG 21 47 12 07", "CG 00 01 04 13", "IL 00 17 11 98",
            *[e["policy"] for e in D.EXPIRING_LINES]],
        "Insurer_FullName_A": [D.EXP_CARRIER, D.EXP_CARRIER_SHORT,
                               D.PRIOR2_CARRIER, D.UMB_CARRIER],
        "Insurer_NAICCode_A": [D.EXP_CARRIER_NAIC, D.UMB_CARRIER_NAIC],
        "*LineOfBusiness_*PremiumAmount_A": [e["premium"] for e in D.EXPIRING_LINES]
                                            + [D.EXP_TOTAL_PREMIUM],
        "Policy_Payment_EstimatedTotalAmount_A": [D.EXP_TOTAL_PREMIUM,
                                                  D.TOTAL_REVENUE],
        "CommercialStructure_AnnualRevenueAmount_*": [D.TOTAL_PAYROLL,
                                                      D.TOTAL_REVENUE],
        "BusinessInformation_FullTimeEmployeeCount_*": [D.TOTAL_FT],
        "BusinessInformation_PartTimeEmployeeCount_*": [D.TOTAL_PT],
        "LossHistory_TotalAmount_A": [D.TOTAL_INCURRED],
        "Policy_EffectiveDate_A": [D.EXP_EFF, D.PRIOR2_EFF],
        "Policy_ExpirationDate_A": [D.EXP_EXP, D.PRIOR2_EXP],
        "Subsidiary_ParentOwnershipPercent_B": [D.PARENT_PCT],
    }
    # The occupied area must not reach the TOTAL building-area box - but only
    # where the two figures actually differ. On premises 002 and 004 the tenant
    # occupies the whole building, so the same number is the correct answer to
    # both questions and forbidding it would fail a correct run.
    for i, ch in enumerate("ABCD"):
        loc = D.LOCATIONS[i]
        if _norm(loc["occupied"]) != _norm(loc["total_area"]):
            forbidden[f"Construction_BuildingArea_{ch}"] = [loc["occupied"]]
        if _norm(loc["total_area"]) != _norm(loc["occupied"]):
            forbidden[f"BuildingOccupancy_OccupiedArea_{ch}"] = [loc["total_area"]]

    shapes = {
        "NamedInsured_TaxIdentifier_*": {
            "regex": r"^\d{2}-?\d{7}$",
            "why": "a FEIN is nine digits - a seven-digit account number is not one"},
        "NamedInsured_NAICSCode_*": {
            "regex": r"^\d{6}$", "why": "NAICS is six digits"},
        "NamedInsured_SICCode_*": {
            "regex": r"^\d{4}$", "why": "SIC is four digits"},
        "*_PostalCode_*": {
            "regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP is 5 or 9 digits"},
        "*StateOrProvinceCode*": {
            "regex": r"^[A-Za-z]{2}$", "why": "a state code is two letters"},
        "PriorCoverage_PolicyYear_*": {
            "regex": r"^\d{4}(\s*[-/]\s*\d{2,4})?$", "why": "a policy year"},
    }

    # The fourth named insured, the fifth premises and the fourth claim are
    # STATED and have no slot. They must not displace a real row.
    expected_absent = {
        "scope": ["NamedInsured_FullName_*", "CommercialStructure_PhysicalAddress_LineOne_*",
                  "LossHistory_OccurrenceDescription_*", "LossHistory_OccurrenceDate_*"],
        "values": [D.INSUREDS[3]["name"], D.LOCATIONS[4]["l1"],
                   D.LOSSES[3]["desc"], D.LOSSES[3]["occurrence"]],
    }

    row_sets = {
        "named_insureds": {
            "slots": list("ABC"),
            "columns": {
                "name": "NamedInsured_FullName_{row}",
                "fein": "NamedInsured_TaxIdentifier_{row}",
                "sic": "NamedInsured_SICCode_{row}",
                "naics": "NamedInsured_NAICSCode_{row}",
                "phone": "NamedInsured_Primary_PhoneNumber_{row}",
                "line1": "NamedInsured_MailingAddress_LineOne_{row}",
                "city": "NamedInsured_MailingAddress_CityName_{row}",
                "zip": "NamedInsured_MailingAddress_PostalCode_{row}"},
            "rows": [{"name": i["name"], "fein": i["fein"], "sic": i["sic"],
                      "naics": i["naics"], "phone": i["phone"], "line1": i["l1"],
                      "city": i["city"], "zip": i["zip"]} for i in D.INSUREDS[:3]]},
        "premises": {
            "slots": list("ABCD"),
            "columns": {
                "loc": "CommercialStructure_Location_ProducerIdentifier_{row}",
                "line1": "CommercialStructure_PhysicalAddress_LineOne_{row}",
                "city": "CommercialStructure_PhysicalAddress_CityName_{row}",
                "zip": "CommercialStructure_PhysicalAddress_PostalCode_{row}",
                "revenue": "CommercialStructure_AnnualRevenueAmount_{row}",
                "ft": "BusinessInformation_FullTimeEmployeeCount_{row}",
                "occupied": "BuildingOccupancy_OccupiedArea_{row}",
                "area": "Construction_BuildingArea_{row}"},
            "rows": [{"loc": l["num"], "line1": l["l1"], "city": l["city"],
                      "zip": l["zip"], "revenue": l["revenue"], "ft": l["ft"],
                      "occupied": l["occupied"], "area": l["total_area"]}
                     for l in D.LOCATIONS[:4]]},
        "losses": {
            "slots": list("ABC"),
            "columns": {
                "occurrence": "LossHistory_OccurrenceDate_{row}",
                "claim": "LossHistory_ClaimDate_{row}",
                "line": "LossHistory_LineOfBusiness_{row}",
                "paid": "LossHistory_PaidAmount_{row}",
                "reserved": "LossHistory_ReservedAmount_{row}",
                "open": "LossHistory_ClaimStatus_OpenCode_{row}",
                "subro": "LossHistory_ClaimStatus_SubrogationCode_{row}"},
            "rows": [{"occurrence": l["occurrence"], "claim": l["claim"],
                      "line": l["line"], "paid": l["paid"],
                      "reserved": l["reserved"],
                      "open": "Y" if l["open"] == "O" else "N",
                      "subro": l["subro"]} for l in D.LOSSES[:3]]},
        "prior_coverage_year_one": {
            "slots": ["A"],
            "columns": {
                "gl_carrier": "PriorCoverage_GeneralLiability_InsurerFullName_{row}",
                "gl_policy": "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_{row}",
                "gl_premium": "PriorCoverage_GeneralLiability_TotalPremiumAmount_{row}",
                "pr_policy": "PriorCoverage_Property_PolicyNumberIdentifier_{row}",
                "pr_premium": "PriorCoverage_Property_TotalPremiumAmount_{row}",
                "au_policy": "PriorCoverage_Automobile_PolicyNumberIdentifier_{row}",
                "au_premium": "PriorCoverage_Automobile_TotalPremiumAmount_{row}",
                "ot_carrier": "PriorCoverage_OtherLine_InsurerFullName_{row}",
                "ot_policy": "PriorCoverage_OtherLine_PolicyNumberIdentifier_{row}"},
            "rows": [{
                "gl_carrier": D.EXP_CARRIER, "gl_policy": "GL 4471102 25",
                "gl_premium": "$73,410", "pr_policy": "CF 4471104 25",
                "pr_premium": "$41,265", "au_policy": "BA 4471106 25",
                "au_premium": "$28,940", "ot_carrier": D.UMB_CARRIER,
                "ot_policy": "XSU-9920415-25"}]},
    }

    counts = {v: sum(1 for x in FIELDS.values() if x["verdict"] == v)
              for v in (V_EXPECT, V_NO_DATA, V_BY_RULE, V_NA, V_NOT_SCORED)}
    return {
        "_meta": {
            "kit": "A125 - ACORD 125 full-form fidelity kit",
            "account": D.INSUREDS[0]["name"],
            "document": PDF_PATH.name,
            "built_by": "backend/scripts/make_a125_test_pdf.py",
            "fields_on_form": len(schema),
            "verdict_counts": counts,
            "absent_by_design": D.ABSENT_BY_DESIGN,
        },
        "_doc": f"{PDF_PATH.name} - one upload, ~{TARGET_PAGES} pages",
        "_forms": ["ACORD_125"],
        "_normalisation": {
            "case": "insensitive",
            "currency": "$ and thousands separators ignored",
            "phone": "punctuation ignored",
            "units": "a unit the form's own label already prints is ignored "
                     "(sq ft, %)",
            "abbreviations": "Ste == Suite, Rd == Road, St == Street, "
                             "Ave == Avenue and the like - an address "
                             "abbreviation is the same address",
            "leading_zeros": "001 == 1 on numeric boxes",
            "checkbox": "Y / X / on / true all mean ticked",
        },
        "expect": {"ACORD_125": expect},
        "must_be_blank": {"ACORD_125": blanks},
        "forbidden": {"ACORD_125": forbidden},
        "shapes": {"ACORD_125": shapes},
        "expected_absent": {"ACORD_125": expected_absent},
        "row_sets": {"ACORD_125": row_sets},
        "fields": FIELDS,
        # Scoring contract for wording. `semantic` fields are graded on MEANING
        # (an LLM may legitimately reword a description); every other field is
        # graded on the value after normalisation.
        "match_modes": {"ACORD_125": {
            "semantic": semantic,
            "rule": "semantic = ACORD tooltip 'Enter text:' AND the field name "
                    "carries Description / Explanation / RemarkText / Operations "
                    "/ Relationship. Everything else is exact: identifiers, "
                    "amounts, dates, codes, names, addresses and checkboxes are "
                    "never 'close enough'.",
        }},
    }


# ═════════════════════════════════════════════════════════════════════════════
# Verify - read the PDF back THROUGH OUR OWN REPAIR LAYER
# ═════════════════════════════════════════════════════════════════════════════
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _extract() -> str:
    """Whatever the pipeline would see. Deliberately the REPAIRED text: a trap
    that only survives in raw pdfplumber output is a trap the model never sees."""
    import pdfplumber
    from utils import page_layout as pl
    out = []
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for pg in pdf.pages:
            t = pl.page_text(pg)
            out.append(t if isinstance(t, str) else (t[0] if t else ""))
    return "\n".join(out)


def _self_consistency(key: dict) -> List[str]:
    """Score the key against a form stamped with the key's own answers."""
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
        if t.get(kind):
            for row in res["details"].get(kind, [])[:4]:
                out.append(f"SELF-CONSISTENCY ({kind}): the key's own answer "
                           f"fails its own check - {row}")
    if t.get("correct") != len(perfect):
        out.append(f"SELF-CONSISTENCY: {t.get('correct')} of {len(perfect)} "
                   f"expectations score correct against themselves")
    for g in sff.score_rows("ACORD_125", key, perfect):
        if g.get("cross_row") or g.get("cells_correct") != g.get("cells_expected"):
            out.append(f"SELF-CONSISTENCY (row-cell): group {g.get('group')} "
                       f"{g.get('cells_correct')}/{g.get('cells_expected')}, "
                       f"cross-row {g.get('cross_row')}")
    # an EMPTY form must raise no blank violations and no forbidden hits
    res0 = sff.score_form("ACORD_125", key, {}, lambda f: None)
    for kind in ("blank_violation", "forbidden", "shape", "overflow_leak", "wrong"):
        if res0["tally"].get(kind):
            out.append(f"SELF-CONSISTENCY: an EMPTY form reports "
                       f"{res0['tally'][kind]} {kind}")
    return out


def verify(key: dict, pages: int) -> None:
    text = _extract()
    hay = _norm(text)
    problems: List[str] = []

    # 1. every expected value must be PRINTED - a trap not in the document
    #    tests nothing and would score as a pass
    for field, val in key["expect"]["ACORD_125"].items():
        v = str(val).strip()
        if not v or FIELDS[field]["verdict"] != V_EXPECT:
            continue
        if field == "Form_EditionIdentifier_A":
            continue                       # read off the template, not the document
        if field == "Policy_Audit_FrequencyCode_A":
            if _norm(D.AUDIT_PERIOD) not in hay:
                problems.append("the audit period word is not printed")
            continue
        probe = _norm(v)[:60]
        if probe and probe not in hay:
            problems.append(f"NOT IN DOCUMENT: {field} = {v[:70]!r}")

    # 2. every decoy must be printed too, or the invention trap is disarmed
    for value, scope, _why in D.DECOYS:
        if _norm(value) not in hay:
            problems.append(f"DECOY MISSING: {value!r} (scoped to {scope})")

    # 3. nothing deliberately absent may have leaked into the document
    for absent in (D.INSUREDS[0]["web"], D.CONTACTS[1]["email"],
                   D.LOCATIONS[2]["county"]):
        if absent:
            problems.append(f"ABSENCE BROKEN: {absent!r} is supposed to be absent")
    if _norm("Multnomah") in hay and _norm("Tigard") in hay:
        # county is stated for 001/002/004 but must NOT be stated for 003
        for ln in text.split("\n"):
            if "Tigard" in ln and ("Washington" in ln or "County" in ln and
                                   "not stated" not in ln):
                if re.search(r"Tigard.*\b(Washington|Multnomah|Clackamas|Clatsop)\b", ln):
                    problems.append(f"ABSENCE BROKEN: Location 003 states a county: {ln[:90]!r}")
                    break

    # 4. the four overflow entities must be present (they are a real test)
    for v in key["expected_absent"]["ACORD_125"]["values"]:
        if _norm(v)[:40] not in hay:
            problems.append(f"OVERFLOW ROW MISSING FROM DOCUMENT: {v[:60]!r}")

    # 5. the repair layer must actually have repaired the fuzz
    for probe, what in ((f"POLICYNOGL4471102", "teletype despacing"),
                        (_norm("supplier $7,320"), "riffle repair on the loss run"),
                        (_norm("Cascadia Harbor Mutual Insurance Company GL 4471102 25"),
                         "riffle repair on the prior-carrier grid")):
        if _norm(probe) not in hay:
            problems.append(f"FUZZ NOT REPAIRED: {what}")

    # 6. SELF-CONSISTENCY. A form stamped with exactly what the key expects must
    #    score 100% correct with zero forbidden hits, zero shape failures, zero
    #    blank violations and zero cross-row. Anything else means a trap is
    #    firing on the RIGHT answer, which burns a live run on a false alarm.
    problems += _self_consistency(key)

    if problems:
        for p in problems:
            print("  FAIL:", p)
        raise SystemExit(f"verification failed: {len(problems)} problem(s)")

    print(f"  verification OK: {pages} pages, {len(text):,} repaired chars, "
          f"{len(key['expect']['ACORD_125'])} expectations, "
          f"{len(key['must_be_blank']['ACORD_125'])} must-be-blank, "
          f"{len(D.DECOYS)} decoys")


# ═════════════════════════════════════════════════════════════════════════════
# README
# ═════════════════════════════════════════════════════════════════════════════
def write_readme(key: dict, pages: int) -> None:
    c = key["_meta"]["verdict_counts"]
    q_absent = [q["n"] for q in D.QUESTIONS.values() if q["answer"] is None]
    lines = [
        "# A125 - the ACORD 125 full-form test kit",
        "",
        f"**Document:** `{PDF_PATH.name}` - {pages} pages, one upload.",
        f"**Key:** `{KEY_PATH.name}` - a verdict for **all "
        f"{key['_meta']['fields_on_form']}** ACORD 125 boxes.",
        f"**Account:** {D.INSUREDS[0]['name']} (synthetic).",
        "",
        "## Why this kit exists",
        "",
        "Every earlier kit scored a subset of ACORD 125 that whoever wrote the kit",
        "chose. The T1 key has an opinion on 146 of the form's 548 boxes; the other",
        "402 are unjudged, and the pipeline puts a value into 228 of them. This key",
        "gives every box a verdict, so a percentage can never again be a percentage",
        "of the boxes we decided to look at.",
        "",
        "## The five verdicts",
        "",
        "| verdict | meaning | count |",
        "|---|---|---|",
        f"| `expect` | the document states it and this value belongs in THIS box | {c['expect']} |",
        f"| `blank_no_data` | the document says nothing - the box must ship EMPTY | {c['blank_no_data']} |",
        f"| `blank_by_rule` | the document DOES state something and one of our own rules owns the blank anyway (a signature, an agency-profile code, a premium on a quote) | {c['blank_by_rule']} |",
        f"| `not_applicable` | a row the document has no entity for | {c['not_applicable']} |",
        f"| `not_scored` | generation-time metadata nobody can pin | {c['not_scored']} |",
        "",
        "`must_be_blank` in the scored key is the union of the middle three.",
        "",
        "## How to run it",
        "",
        "```bash",
        "py backend/scripts/make_a125_test_pdf.py          # regenerate, self-verifying",
        f"#  upload 271page_test_data/{PDF_PATH.name}, generate ACORD 125",
        "py backend/scripts/score_form_fill.py \\",
        f"    --key 271page_test_data/{KEY_PATH.name} \\",
        "    --pdf-dir <folder holding the generated PDF> [--facts facts.json]",
        "```",
        "",
        "Score in four buckets plus ROW-CELL, never in two. A run that fills every",
        "cell of a four-row table with values from four different premises scores",
        "100% on fields and near zero on ROW-CELL.",
        "",
        "## 1. Is the data extracted, and does it keep its meaning?",
        "",
        "The document is printed the way real carrier documents are, in the exact",
        "shapes our own extraction layer was built to repair. The generator's",
        "`verify()` re-reads the PDF **through `utils.page_layout`** and fails the",
        "build if any of these stops being repaired:",
        "",
        "| page | shape | what it proves |",
        "|---|---|---|",
        "| 11 | letter-spaced teletype - `P O L I C Y  N O` | `despaced_words` still rejoins it. This defect reached a client's ACORD 125 as `6 C 7 - 4 0 - 0 2`. |",
        "| 19 | the description column physically overruns PAID, so pdfplumber returns `su$p7p,l3i2e0r` | `page_words` re-segments the line and `$7,320` comes back whole |",
        "| 23 | the carrier name overruns the policy-number column | the same repair on the prior-carrier grid |",
        "| 3, 13-17 | two independent columns with drifting baselines | the identity split, and prose read down each column instead of across |",
        "| 2 | label on one line, value on the next | the bare-label fingerprint the column reflow keys on |",
        "| 4 | the FEIN printed three ways (`93-2841760`, `93 2841760`, `932841760`) | one fact, three spellings, one value |",
        "| every page | the CARRIER's own website and phone in the running header | the merge ranks by repetition - these out-repeat everything the applicant states |",
        "",
        "## 2. Does each value land in the right box?",
        "",
        "`expect` names the exact box. A value one box over is a WRONG, not a",
        "CORRECT. The traps that separate boxes which look alike:",
        "",
        "- **Proposed vs expiring term.** The submission is for 10/01/2026-10/01/2027;",
        "  the expiring policy runs 10/01/2025-10/01/2026. Page one takes the proposed",
        "  dates; the prior-carrier grid takes the expiring ones.",
        "- **Receiving vs expiring carrier.** Page one is Northbridge Atlantic. The",
        "  expiring carrier is Cascadia Harbor, the umbrella is on a third carrier,",
        "  and two years ago it was a fourth.",
        "- **Occupied area vs total building area.** Location 001 occupies 9,400 sq ft",
        "  of a 26,000 sq ft building. Two numbers, two boxes.",
        "- **Total paid vs total incurred.** `LossHistory_TotalAmount`'s own ACORD",
        "  tooltip says *the amount that has been PAID*. The document prints",
        f"  `TOTAL PAID {D.TOTAL_PAID}` and `TOTAL INCURRED {D.TOTAL_INCURRED}`.",
        "  Only one of them is right.",
        "- **Parent's stake vs the applicant's stake.** Harbor Line owns 82% of the",
        "  applicant; the applicant owns 100% of Cedar Bluff. The Subsidiary block",
        "  wants the second.",
        "- **Per-premises vs company-wide counts.** Employee counts and revenue on",
        f"  page 2 are per LOCATION; the company totals ({D.TOTAL_FT} / {D.TOTAL_PT} /",
        f"  {D.TOTAL_REVENUE}) are printed too and belong in neither.",
        "",
        "## 3. Are the blanks correct?",
        "",
        "Sixteen things are deliberately never stated. Their boxes must ship empty:",
        "",
    ] + [f"- {a}" for a in D.ABSENT_BY_DESIGN] + [
        "",
        f"The sharpest of these is **question {', '.join(q_absent)}**. The document",
        "never puts them to the applicant, and says so in terms: *\"Any question not",
        "printed above was not put to the applicant and has no answer on file.\"*",
        "Brent's own words: *Blank does not equal No.* A defaulted `N` in those boxes",
        "is the defect this kit exists to catch.",
        "",
        "The same rule at checkbox level: the safety programme states a manual, a",
        "safety position and monthly meetings, and makes **no statement at all**",
        "about OSHA. The OSHA box must be empty, not unticked-because-we-guessed.",
        "",
        "## 4. Is the system inventing values?",
        "",
        "Every decoy below is a real string in the document, scoped to the boxes it",
        "must never reach. Scoping matters: a global \"this must appear nowhere\"",
        "match fires on the box where the value legitimately belongs.",
        "",
        "| value | must never reach | why it is tempting |",
        "|---|---|---|",
    ] + [f"| `{v}` | `{scope}` | {why} |" for v, scope, why in D.DECOYS] + [
        "",
        "Three whole blocks are fabrication surfaces with nothing behind them:",
        "",
        "- **`CancelNonRenew_*`** (8 boxes). Question 5 is `N`. Nothing goes here.",
        "- **`OtherPolicy_*`** (8 boxes). Question 4 is `N`. The four expiring",
        "  policies belong to a different carrier and must not be listed.",
        "- **`PriorCoverage_*_C`** (21 boxes). Only two policy years are documented.",
        "  The client's own instruction: *do not manufacture carrier history*.",
        "",
        "## 5. Overflow - stated, with no slot",
        "",
        "| stated | slots on the form | the overflow |",
        "|---|---|---|",
        f"| 4 named insureds | 3 (rows A-C) | {D.INSUREDS[3]['name']} |",
        f"| 5 premises | 4 (rows A-D) | {D.LOCATIONS[4]['l1']}, {D.LOCATIONS[4]['city']} |",
        f"| 4 claims | 3 (rows A-C) | {D.LOSSES[3]['occurrence']} {D.LOSSES[3]['line']} |",
        "",
        "`expected_absent` fails the run if an overflow entity DISPLACES a real one.",
        "Overflowing is capacity; displacing is a defect.",
        "",
        "## What the kit does NOT decide",
        "",
        "- `Form_CompletionDate_A` is the generation date - `not_scored`.",
        "- `blank_by_rule` boxes are scored as must-be-blank. If a future ruling says",
        "  one of them should fill (the agency-profile codes are the live example -",
        "  they come from the broker's own profile, which the product does not yet",
        "  collect), change the verdict here, not the scorer.",
        "",
        "Generated by `backend/scripts/make_a125_test_pdf.py` from",
        "`backend/scripts/_a125_data.py`. Edit the data module - the PDF and the key",
        "are both built from it and cannot disagree.",
    ]
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    build_pages()
    pad_to_target()
    pages = render()
    print(f"  wrote {PDF_PATH.relative_to(ROOT)}  ({pages} pages)")
    schema = build_key()
    key = assemble(schema)
    KEY_PATH.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"  wrote {KEY_PATH.relative_to(ROOT)}")
    write_readme(key, pages)
    print(f"  wrote {DOC_PATH.relative_to(ROOT)}")
    verify(key, pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
