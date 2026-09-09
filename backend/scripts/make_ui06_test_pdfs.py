"""make_ui06_test_pdfs.py - live-test package for UI-06 (normalization noise).

    py backend/scripts/make_ui06_test_pdfs.py

Writes ui06_test_data/ :
    UI06_dec_page.pdf          - a commercial package dec page, 11 coverage lines
    UI06_certificate.pdf       - a COI describing the SAME programme, every value
                                 spelled/formatted differently
    README-HOW-TO-TEST.md

WHY TWO FILES AND NOT ONE
-------------------------
Every notice UI-06 complains about comes from `check_doc_consistency`, which
compares one document AGAINST ANOTHER. `docs` is one entry per uploaded FILE
(extraction_pipeline.active_docs), so a single upload has nothing to compare and
emits nothing at all. Both files go in ONE submission.

WHY THE VALUES ARE NOT THE CLIENT'S
-----------------------------------
UI-06 is a rendering defect, not a value defect - it fires for ANY package whose
documents spell the same things differently. So none of the client's insured,
carriers, dates or coverage spellings appear here. If the fix is generic this
package is just as noisy as theirs; if the fix is tuned to their strings, this
package proves it.

WHAT THIS PACKAGE TRIGGERS
--------------------------
  1  lob_normalized          THE HEADLINE. Both files list 11 coverage lines,
                             spelled differently, with NO denial anywhere - so
                             sqs_service.py:2213 dumps every raw list from every
                             document into one "Coverage terms: ..." string.
                             That is the paragraph in the client's screenshot.
  2  name_normalized         "Marisol Freight & Cold Storage, LLC" vs
                             "MARISOL FREIGHT AND COLD STORAGE, L.L.C."
  3  entity_type_normalized  "Limited Liability Company" vs "LLC"
  4  mailing_address_normalized    "Suite 260 ... WA"  vs  "Ste 260 ... Washington"
  5  physical_address_normalized   "Terminal Court, Suite 3, WA" vs "Terminal Ct Ste 3, Washington"
  6  effective_date_normalized     "10/09/2026" vs "10/9/26"
  7  expiration_date_normalized    same, one year on
  -> seven "treated as equivalent" rows stacked in ONE Submission Integrity card,
     the last of which is a paragraph.

  THE REPEAT: every one of rows 2-7 is ALSO a curated Data Consistency field, and
  underwriting_consistency emits a row for a curated field even when it is
  CONSISTENT. So the producer reads the same conclusion twice on one screen -
  which is the second half of the client's complaint.

DESIGN RULES (inherited from make_sys05_test_pdf.py, all proven)
-----------------------------------------------------------------
  * Real text via reportlab - extractable by pdfplumber, no OCR needed.
  * Column x-positions far apart so characters never interleave.
  * Dates computed from TODAY - always future-dated, so no expired-term hard
    stop and no renewal routing (the word "renewal" appears nowhere).
  * NO denial wording anywhere ("no coverage", "not covered", "excluded"). A
    denial would flip the coverage-terms notice from [info] to [warning] and
    this kit would stop testing UI-06.
  * FEIN is the SAME on both files (punctuation aside) so nothing hard-stops.
  * Self-verified at the bottom: every phrase a check depends on must be
    present, and neither file may reuse the other's spellings.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ui06_test_data",
)

TODAY = datetime.now()
_EFF = TODAY + timedelta(days=30)
_EXP = _EFF + timedelta(days=365)

# Same two dates, printed two ways. Zero-padded 4-digit year on the dec page,
# unpadded 2-digit year on the certificate - the exact shape Beta Report 5.2
# normalizes away, and therefore the exact shape that produces an [info] notice.
EFF_LONG = _EFF.strftime("%m/%d/%Y")
EXP_LONG = _EXP.strftime("%m/%d/%Y")
EFF_SHORT = "{}/{}/{}".format(_EFF.month, _EFF.day, _EFF.strftime("%y"))
EXP_SHORT = "{}/{}/{}".format(_EXP.month, _EXP.day, _EXP.strftime("%y"))

# The one insured, written two ways.
INSURED_DEC = "Marisol Freight & Cold Storage, LLC"
INSURED_COI = "MARISOL FREIGHT AND COLD STORAGE, L.L.C."

ENTITY_DEC = "Limited Liability Company"
ENTITY_COI = "LLC"

MAIL_DEC = "4820 Harborgate Way, Suite 260, Tacoma, WA 98421"
MAIL_COI = "4820 Harborgate Way Ste 260, Tacoma, Washington 98421"

# NOTE: "Court/Ct", "Suite/Ste" and "WA/Washington" all fold. "Building 3" vs
# "Bldg 3" and "South" vs "S" do NOT - the first cut of this fixture used them
# and produced a real "Physical address differs" WARNING, which is a separate
# normalization gap and would have polluted this kit's acceptance criteria.
SITE_DEC = "1140 Terminal Court, Suite 3, Kent, WA 98032"
SITE_COI = "1140 Terminal Ct Ste 3, Kent, Washington 98032"

FEIN_DEC = "47-6120933"
FEIN_COI = "476120933"

AGENCY = "Halloran Brooks Risk Advisors Inc"

CARRIER_A = "Kestrel Mutual Insurance Company"
NAIC_A = "41238"
CARRIER_B = "Aldergrove Specialty Insurance Co"
NAIC_B = "27519"

# Eleven coverage lines, spelled two ways. Left = the dec page's ISO/long
# spelling, right = the certificate's short one. Neither list may contain a
# spelling from the other, or the pair tests string equality instead of
# normalization (asserted at the bottom of this file).
LINES = [
    ("Commercial General Liability",                 "General Liability",      CARRIER_A, NAIC_A, "KM-GL-884371-26",  9140),
    ("Commercial Property",                          "Property",               CARRIER_A, NAIC_A, "KM-CP-771655-26",  7320),
    ("Commercial Automobile Liability",              "Automobile Liability",   CARRIER_A, NAIC_A, "KM-BA-990214-26",  6485),
    ("Commercial Umbrella Liability",                "Umbrella Liability",     CARRIER_B, NAIC_B, "AG-UM-402118-26",  4275),
    ("Workers Compensation And Employers Liability", "Workers Compensation",   CARRIER_A, NAIC_A, "KM-WC-336702-26", 11960),
    ("Commercial Crime",                             "Crime",                  CARRIER_B, NAIC_B, "AG-CR-113977-26",  1225),
    ("Commercial Inland Marine",                     "Inland Marine",          CARRIER_A, NAIC_A, "KM-IM-558104-26",  2140),
    ("Cyber Liability",                              "Cyber",                  CARRIER_B, NAIC_B, "AG-CY-661430-26",  3080),
    ("Employment Practices Liability",               "EPLI",                   CARRIER_B, NAIC_B, "AG-EP-204877-26",  2610),
    ("Equipment Breakdown",                          "Boiler And Machinery",   CARRIER_A, NAIC_A, "KM-EB-449213-26",   940),
    ("Liquor Liability",                             "Liquor Legal Liability", CARRIER_A, NAIC_A, "KM-LQ-877541-26",   715),
]

TOTAL = sum(r[5] for r in LINES)


def _money(n):
    return "${:,}".format(n)


# -- Layout helpers ----------------------------------------------------------

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9)
        c.drawString(1 * inch, 9.96 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.84 * inch, 7.5 * inch, 9.84 * inch)
    return 9.55 * inch


def _new_page(c, title, subtitle=""):
    c.showPage()
    return _page(c, title, subtitle)


def _row(c, y, label, value, lw=2.6):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, "{}:".format(label))
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.205 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.215 * inch


# -- File 1: the declarations page -------------------------------------------

def build_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "New business declarations issued by the company shown for each coverage part")
    y = _row(c, y, "Named Insured", INSURED_DEC)
    y = _row(c, y, "Entity Type", ENTITY_DEC)
    y = _row(c, y, "Mailing Address", MAIL_DEC)
    y = _row(c, y, "Location Address", SITE_DEC)
    y = _row(c, y, "FEIN", FEIN_DEC)
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "{} to {}".format(EFF_LONG, EXP_LONG))
    y = _row(c, y, "Effective Date", EFF_LONG)
    y = _row(c, y, "Expiration Date", EXP_LONG)
    y = _row(c, y, "Description of Operations",
             "Refrigerated trucking and cold storage warehousing of packaged food products")
    y = _row(c, y, "Annual Gross Sales", "$14,300,000")
    y = _row(c, y, "Annual Payroll", "$4,180,000")
    y = _row(c, y, "Number of Employees", "62")
    y = _row(c, y, "Years In Business", "18")
    y = _row(c, y, "Total Policy Premium", _money(TOTAL))

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS FORMING THIS POLICY")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(1.15 * inch, y, "COVERAGE PART")
    c.drawString(4.05 * inch, y, "CARRIER")
    c.drawString(6.05 * inch, y, "POLICY NO")
    c.drawString(7.15 * inch, y, "PREMIUM")
    y -= 0.19 * inch
    c.setFont("Helvetica", 7.6)
    for dec_name, _coi, carrier, _naic, policy, prem in LINES:
        c.drawString(1.15 * inch, y, dec_name)
        c.drawString(4.05 * inch, y, carrier[:26])
        c.drawString(6.05 * inch, y, policy)
        c.drawString(7.15 * inch, y, _money(prem))
        y -= 0.185 * inch

    y = _new_page(c, "COMMERCIAL PACKAGE POLICY - COVERAGE PART DETAIL",
                  "Named Insured: {}".format(INSURED_DEC))
    for dec_name, _coi, carrier, naic, policy, prem in LINES[:6]:
        y = _head(c, y, dec_name.upper())
        y = _row(c, y, "Carrier", carrier)
        y = _row(c, y, "Carrier NAIC", naic)
        y = _row(c, y, "Policy Number", policy)
        y = _row(c, y, "Policy Period", "{} to {}".format(EFF_LONG, EXP_LONG))
        y = _row(c, y, "Annual Premium", _money(prem))

    y = _new_page(c, "COMMERCIAL PACKAGE POLICY - COVERAGE PART DETAIL (CONTINUED)",
                  "Named Insured: {}".format(INSURED_DEC))
    for dec_name, _coi, carrier, naic, policy, prem in LINES[6:]:
        y = _head(c, y, dec_name.upper())
        y = _row(c, y, "Carrier", carrier)
        y = _row(c, y, "Carrier NAIC", naic)
        y = _row(c, y, "Policy Number", policy)
        y = _row(c, y, "Policy Period", "{} to {}".format(EFF_LONG, EXP_LONG))
        y = _row(c, y, "Annual Premium", _money(prem))

    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "General Liability Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Liability General Aggregate", "$2,000,000")
    y = _row(c, y, "Automobile Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Umbrella Each Occurrence", "$5,000,000")
    y = _row(c, y, "Employers Liability Each Accident", "$1,000,000")
    y = _row(c, y, "Building Value", "$3,750,000")
    y = _row(c, y, "Business Personal Property", "$1,900,000")
    y = _row(c, y, "Property Deductible", "$10,000")

    c.showPage()
    c.save()


# -- File 2: the certificate -------------------------------------------------

def build_coi(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "Date Issued: {}".format(TODAY.strftime("%m/%d/%Y")))
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", INSURED_COI)
    y = _row(c, y, "Insured Entity Type", ENTITY_COI)
    y = _row(c, y, "Insured Mailing Address", MAIL_COI)
    y = _row(c, y, "Insured Location Address", SITE_COI)
    y = _row(c, y, "Insured FEIN", FEIN_COI)
    y = _row(c, y, "Policy Effective Date", EFF_SHORT)
    y = _row(c, y, "Policy Expiration Date", EXP_SHORT)

    y = _head(c, y, "COVERAGES CERTIFIED - ISSUED AS A MATTER OF INFORMATION ONLY")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(1.15 * inch, y, "TYPE OF INSURANCE")
    c.drawString(3.45 * inch, y, "INSURER")
    c.drawString(5.35 * inch, y, "POLICY NUMBER")
    c.drawString(6.60 * inch, y, "EFF")
    c.drawString(7.15 * inch, y, "EXP")
    y -= 0.19 * inch
    c.setFont("Helvetica", 7.6)
    for _dec, coi_name, carrier, _naic, policy, _prem in LINES:
        c.drawString(1.15 * inch, y, coi_name)
        c.drawString(3.45 * inch, y, carrier[:24])
        c.drawString(5.35 * inch, y, policy)
        c.drawString(6.60 * inch, y, EFF_SHORT)
        c.drawString(7.15 * inch, y, EXP_SHORT)
        y -= 0.185 * inch

    y -= 0.12 * inch
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _row(c, y, "Insurer A", "{}   NAIC # {}".format(CARRIER_A, NAIC_A))
    y = _row(c, y, "Insurer B", "{}   NAIC # {}".format(CARRIER_B, NAIC_B))

    y = _head(c, y, "LIMITS")
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _row(c, y, "Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Umbrella Each Occurrence", "$5,000,000")
    y = _row(c, y, "E.L. Each Accident", "$1,000,000")

    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    c.setFont("Helvetica", 8.5)
    for ln in (
        "Refrigerated trucking and cold storage warehousing of packaged food products.",
        "Certificate holder is included as additional insured where required by written contract.",
        "All coverage parts listed above are in force for the policy term shown.",
    ):
        c.drawString(1.15 * inch, y, ln)
        y -= 0.19 * inch

    c.showPage()
    c.save()


# -- Self-verification -------------------------------------------------------

_DEC_MUST_CONTAIN = [INSURED_DEC, ENTITY_DEC, MAIL_DEC, SITE_DEC, FEIN_DEC,
                     EFF_LONG, EXP_LONG] + [r[0] for r in LINES]
_COI_MUST_CONTAIN = [INSURED_COI, ENTITY_COI, MAIL_COI, SITE_COI, FEIN_COI,
                     EFF_SHORT, EXP_SHORT] + [r[1] for r in LINES]

# A denial anywhere flips the coverage-terms notice from [info] to [warning].
_DENIAL_WORDS = ["no coverage", "not covered", "coverage is excluded",
                 "does not apply", "nil coverage"]


def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(dec_path, coi_path):
    dec, coi = _text(dec_path), _text(coi_path)

    for label, text, needed in (("DEC", dec, _DEC_MUST_CONTAIN),
                                ("COI", coi, _COI_MUST_CONTAIN)):
        missing = [p for p in needed if p not in text]
        if missing:
            raise SystemExit("{} BROKEN - phrases missing: {}".format(label, missing))

    for label, text in (("DEC", dec), ("COI", coi)):
        hit = [w for w in _DENIAL_WORDS if w in text.lower()]
        if hit:
            raise SystemExit(
                "{} INVALID - it denies coverage ({}), which turns the coverage-terms "
                "notice into a warning and stops this kit testing UI-06".format(label, hit))

    # The two files must describe one programme in DIFFERENT words, or the
    # comparison passes on string equality and no [info] notice is emitted.
    #
    # Compared as WHOLE LINE NAMES, not substrings. "Commercial General
    # Liability" legitimately CONTAINS "General Liability" - that containment is
    # the realistic long/short pair this kit is built on, and the notice fires
    # because the two extracted lists are not equal, not because the strings
    # share no characters. A substring test here rejected the fixture for being
    # realistic.
    shared = {a for a, b, *_ in LINES} & {b for a, b, *_ in LINES}
    if shared:
        raise SystemExit(
            "PAIR INVALID - the two files use the same spelling for a line, so "
            "nothing is normalized for it: {}".format(sorted(shared)))
    dec_display = ", ".join(r[0] for r in LINES)
    coi_display = ", ".join(r[1] for r in LINES)
    if dec_display.strip().lower() == coi_display.strip().lower():
        raise SystemExit(
            "PAIR INVALID - both raw coverage lists render identically, which is "
            "the one case sqs_service.py:2213 stays silent for")
    for value, other in ((INSURED_DEC, coi), (MAIL_DEC, coi), (SITE_DEC, coi),
                         (EFF_LONG, coi), (INSURED_COI, dec), (MAIL_COI, dec)):
        if value in other:
            raise SystemExit(
                "PAIR INVALID - identity value reused verbatim: {!r}".format(value))

    dump = "; ".join([", ".join(r[0] for r in LINES), ", ".join(r[1] for r in LINES)])
    print("  self-check OK - {} dec phrases, {} coi phrases, no denial wording, "
          "no reused spellings".format(len(_DEC_MUST_CONTAIN), len(_COI_MUST_CONTAIN)))
    print("  the 'Coverage terms:' dump this package should produce is "
          "~{} characters".format(len(dump)))


_LINE_TABLE = "\n".join(
    "| `{}` | `{}` |".format(a, b) for a, b, _c, _n, _p, _m in LINES)

README = """# UI-06 live test - normalization noise in Submission Integrity

## What UI-06 is

When two uploaded documents say the same thing in different words, Primble prints
a blue **"Resolved formatting difference"** block on the pre-form screen listing
every value it treated as equivalent. One of those rows, **"Coverage terms:"**,
dumps every document's ENTIRE raw coverage list into one paragraph
(`backend/services/sqs_service.py:2213`).

The client's complaint, in two parts:

1. That paragraph is visual noise, and it fires precisely when NOTHING is wrong.
2. The same conclusions are stated again lower down the review flow, so a user
   thinks there is still an unresolved coverage problem.

## Upload

**Both files, in ONE submission:**

  * `UI06_dec_page.pdf`
  * `UI06_certificate.pdf`

Two files is not optional. `check_doc_consistency` compares one document AGAINST
another; a single upload has nothing to compare and emits none of these notices.

## The package

One insured, one programme, **eleven coverage lines**, written two ways:

| The dec page prints | The certificate prints |
|---|---|
{line_table}

And the same identity facts, formatted two ways:

| Fact | Dec page | Certificate |
|---|---|---|
| Named insured | `{insured_dec}` | `{insured_coi}` |
| Entity type | `{entity_dec}` | `{entity_coi}` |
| Mailing address | `{mail_dec}` | `{mail_coi}` |
| Location address | `{site_dec}` | `{site_coi}` |
| Effective date | `{eff_long}` | `{eff_short}` |
| Expiration date | `{exp_long}` | `{exp_short}` |
| FEIN | `{fein_dec}` | `{fein_coi}` |

Nothing here is a real disagreement. Every pair is the same value printed
differently, which is exactly the condition that produces the noise.

## What to record - the pre-form screen, BEFORE selecting forms

**A. The Submission Integrity card.** Expected chip: **"Resolved formatting
difference"**, title **"Documents verified"**. Screenshot the whole card.

**B. The "Coverage terms:" row.** This is the headline. Copy it **verbatim** -
it should be one long paragraph naming all 22 coverage spellings. If it is
short, or absent, say so: that changes the fix.

**C. How many equivalence rows are stacked.** Expect up to seven (applicant
name, entity type, mailing address, location address, effective date,
expiration date, coverage terms). Count what actually renders.

**D. The Data Consistency section, further down the same screen.** Look for the
SAME facts listed again - applicant name, addresses, dates - as consistent or
matched rows. That is the "repeated later in the flow" half of the complaint.
Screenshot it next to the card so the duplication is visible in one shot.

**E. Hard Stops and Warnings.** Expected: **none from any of the above**. If a
"Lines of business differ" warning appears, or a date/name hard stop, that is a
separate defect and I want it - the notice is supposed to fire only when
everything agreed.

**F. The score.** Expected: not capped by any of this. Record the number.

## After the fix

Re-upload the same two files. Expected then:

  * ONE short line instead of the paragraph - e.g. "Coverage terms matched
    across documents - no action needed."
  * The full values still reachable, behind an expandable "View details".
  * No fact stated as resolved up top AND asked about again lower down.
  * Score and hard stops **unchanged** - this is a display fix, nothing about
    scoring or extraction may move.

## Regenerating

    py backend/scripts/make_ui06_test_pdfs.py

Dates are computed from the day you run it, so the package is always
future-dated - it can never drift into an expired-term or renewal path.
""".format(
    line_table=_LINE_TABLE,
    insured_dec=INSURED_DEC, insured_coi=INSURED_COI,
    entity_dec=ENTITY_DEC, entity_coi=ENTITY_COI,
    mail_dec=MAIL_DEC, mail_coi=MAIL_COI,
    site_dec=SITE_DEC, site_coi=SITE_COI,
    eff_long=EFF_LONG, eff_short=EFF_SHORT,
    exp_long=EXP_LONG, exp_short=EXP_SHORT,
    fein_dec=FEIN_DEC, fein_coi=FEIN_COI,
)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dec = os.path.join(OUT_DIR, "UI06_dec_page.pdf")
    coi = os.path.join(OUT_DIR, "UI06_certificate.pdf")
    build_dec(dec)
    build_coi(coi)
    _verify(dec, coi)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(README)
    print("wrote {}".format(dec))
    print("wrote {}".format(coi))
    print("wrote {}".format(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")))


if __name__ == "__main__":
    main()
