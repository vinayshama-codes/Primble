"""make_ui04_test_pdfs.py - TWO PDFs that make the Submission Integrity card
print its "Resolved formatting difference" block, so UI-04 can be seen and,
after the fix, judged.

    py backend/scripts/make_ui04_test_pdfs.py

Writes ui04_test_data/ at the repo root: two PDFs plus README-HOW-TO-TEST.md.


WHAT UI-04 IS
-------------
`check_doc_consistency` (services/sqs_service.py) emits an equivalence notice
WITH the rule that produced it:

    [info] code=effective_date_normalized  Effective date: 07/15/26, 7/15/2026
    [info] code=lob_normalized             Coverage terms: Commercial General ...

Two separate parsers then strip the `code=` token - the inline one in
`extraction_pipeline.py` and `sqs_service.split_doc_consistency_issues` - so
`normalized_differences` reaches the browser as bare sentences. AcordModal has
nothing left to explain with and staples on " - treated as equivalent".

The broker is told two visibly different values are the same and is given no
way to check whether we are right. That is the client's complaint.


WHY TWO DOCUMENTS
-----------------
Every notice here is CROSS-document by construction (`_raw(key)` collects one
value per document, and `_raw_differ` needs two spellings). One PDF cannot
disagree with itself, so a single upload produces an empty block and nothing
to look at.

Document 1 is the carrier's declarations page, printed the way carriers print:
upper case, abbreviated address, two-digit year, coverage parts named in full.
Document 2 is the agency's ACORD 125 application for the same account, printed
the way an agency system prints: mixed case, spelled-out address, four-digit
year, coverage lines named in short form. Both shapes are real; neither is
invented to trip the code.


THE SIX ROWS THIS KIT PRODUCES, AND THE RULE BEHIND EACH
--------------------------------------------------------
    row                what differs                normalizer that collapses it
    ------------------ --------------------------- ----------------------------
    Applicant name     case, comma, entity suffix  normalize_name
    Entity type        LLC / Limited Liability Co  normalize_entity_type
    Mailing address    ST STE / Street, Suite,     normalize_address
                       CO / Colorado
    Effective date     07/15/26 / 7/15/2026        normalize_date
    Expiration date    07/15/27 / 7/15/2027        normalize_date
    Coverage terms     Commercial General          _canon_line_leaf
                       Liability / General
                       Liability

Those are exactly the three categories the client's acceptance criteria name -
date formatting, address formatting, coverage-name equivalence - plus the
entity-suffix pair, which is the one that reads most alarming on screen.

Six rows on purpose: if one model wobble drops a fact, five still render.


FIXTURE RULES - each one is a way this kit could silently stop working
---------------------------------------------------------------------
1. FEIN, policy number, gross sales, employee count and every limit are
   BYTE-IDENTICAL across both documents. FEIN and applicant name are the
   hard-stop reconcilable keys; letting a real conflict onto this screen would
   put a red blocker above the block we are trying to read.
2. The carrier is named on the declarations page ONLY. Two spellings of a
   carrier is the classic Data Consistency row - it belongs to UI-08's kit,
   not this one.
3. No umbrella, no property, no workers comp, no vehicles, no loss runs. Each
   opens its own capture table, checklist or pillar deduction on the same
   screen. GL + Auto is the minimum that still gives a coverage-name pair.
4. The two date formats always differ: the declarations page prints a
   zero-padded two-digit year and the application prints an unpadded
   four-digit year, so the strings differ whatever today's date is.
5. Dates run from TODAY + 14 days, so nothing drifts into the expired-term
   hard stop or the renewal-routing path.
6. Neither document prints the other's spelling of anything. A value visible
   in both shapes inside one document merges to one candidate and the
   cross-document difference disappears.


WHAT THIS SCRIPT CAN AND CANNOT PROVE
-------------------------------------
`verify()` drives the REAL `check_doc_consistency` and the REAL
`assess_underwriting_consistency` over the facts these documents are written to
produce, and reads the REAL frontend source to report whether the fix has
landed yet. It cannot prove extraction reads those values off the PDFs - only
the live run does that. That is why the kit exists.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "ui04_test_data")

DEC_NAME = "ui04-orbin-package-policy-declarations.pdf"
APP_NAME = "ui04-orbin-acord125-application.pdf"

TODAY = datetime.now()
_EFF = TODAY + timedelta(days=14)
_EXP = _EFF + timedelta(days=365)

# Fixture rule 4. Carrier systems print %m/%d/%y; agency systems print an
# unpadded m/d/YYYY. The four-digit year alone guarantees the strings differ,
# so this holds on every calendar day.
DEC_EFF = _EFF.strftime("%m/%d/%y")
DEC_EXP = _EXP.strftime("%m/%d/%y")
APP_EFF = "%d/%d/%d" % (_EFF.month, _EFF.day, _EFF.year)
APP_EXP = "%d/%d/%d" % (_EXP.month, _EXP.day, _EXP.year)

# The entity-suffix pair. Same insured, two printings.
DEC_INSURED = "ORBIN CONTRACTING LLC"
APP_INSURED = "Orbin Contracting, LLC"
DEC_ENTITY = "LLC"
APP_ENTITY = "Limited Liability Company"

# The address pair: abbreviated + state code against spelled-out + state name.
DEC_ADDRESS = "4600 DAHLIA ST STE D13, DENVER, CO 80216"
APP_ADDRESS = "4600 Dahlia Street, Suite D13, Denver, Colorado 80216"

# The coverage-name pair.
DEC_LINES = ["Commercial General Liability", "Commercial Automobile"]
APP_LINES = ["General Liability", "Automobile Liability"]

# Fixture rule 1: identical on both documents.
FEIN = "84-2210987"
POLICY_NO = "5D3-40-02---26"
AGENCY = "CRS Insurance Brokerage LLC"
GROSS_SALES = "$4,120,000"
EMPLOYEES = "22"

# Fixture rule 2: declarations page only.
CARRIER = "Employers Mutual Casualty Company"

OPS = (
    "Orbin Contracting LLC performs commercial interior finishing and light "
    "renovation work at commercial premises. The applicant self performs "
    "carpentry and finish work and retains licensed subcontractors for "
    "mechanical and electrical scopes. No work is performed above three "
    "stories and no residential construction of any kind is undertaken."
)


# -- Layout helpers ----------------------------------------------------------

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=3.1):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, "%s:" % label)
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.21 * inch


def _head(c, y, text):
    y -= 0.12 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.23 * inch


def _wrap(c, y, text, width=100, size=9, lead=0.19):
    c.setFont("Helvetica", size)
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            c.drawString(1 * inch, y, line)
            y -= lead * inch
            line = w
        else:
            line = ("%s %s" % (line, w)).strip()
    if line:
        c.drawString(1 * inch, y, line)
        y -= lead * inch
    return y - 0.06 * inch


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


# -- Document 1: the carrier's declarations page -----------------------------
#
# Upper case, abbreviated address, two-digit year, coverage parts named in
# full. Nothing here is printed in the application's spelling (fixture rule 6).

def build_declarations(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "%s  |  NAIC 21415  |  POLICY NO. %s" % (CARRIER.upper(), POLICY_NO))
    y = _row(c, y, "NAMED INSURED", DEC_INSURED)
    y = _row(c, y, "MAILING ADDRESS", DEC_ADDRESS)
    y = _row(c, y, "FEIN", FEIN)
    y = _row(c, y, "ENTITY TYPE", DEC_ENTITY)
    y = _row(c, y, "PRODUCER", AGENCY)
    y = _row(c, y, "POLICY PERIOD", "%s TO %s" % (DEC_EFF, DEC_EXP))
    y = _row(c, y, "ANNUAL GROSS SALES", GROSS_SALES)
    y = _row(c, y, "NUMBER OF EMPLOYEES", EMPLOYEES)

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _wrap(c, y, OPS)

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS")
    y = _table(
        c, y,
        ["COVERAGE PART", "POLICY NUMBER", "EFFECTIVE", "EXPIRATION", "PREMIUM"],
        [[DEC_LINES[0], POLICY_NO, DEC_EFF, DEC_EXP, "$34,180"],
         [DEC_LINES[1], POLICY_NO, DEC_EFF, DEC_EXP, "$8,940"]],
        [1.0, 3.1, 4.5, 5.5, 6.6],
    )
    y = _row(c, y, "TOTAL POLICY PREMIUM", "$43,120")

    y = _head(c, y, "COMMERCIAL GENERAL LIABILITY - COVERAGE PART")
    y = _row(c, y, "EACH OCCURRENCE LIMIT", "$1,000,000")
    y = _row(c, y, "GENERAL AGGREGATE LIMIT", "$2,000,000")
    # Widest label on the page - the default label column collides with the
    # value and pdfplumber reads back "AGGREGAT$E2:,000,000".
    y = _row(c, y, "PRODUCTS/COMPLETED OPERATIONS AGGREGATE", "$2,000,000", lw=3.6)
    y = _row(c, y, "PERSONAL & ADVERTISING INJURY LIMIT", "$1,000,000")
    y = _row(c, y, "DAMAGE TO PREMISES RENTED TO YOU", "$300,000")
    y = _row(c, y, "MEDICAL EXPENSE LIMIT (ANY ONE PERSON)", "$10,000")

    y = _head(c, y, "COMMERCIAL AUTOMOBILE - COVERAGE PART")
    y = _row(c, y, "LIABILITY COMBINED SINGLE LIMIT", "$1,000,000")
    y = _row(c, y, "COVERED AUTOS - LIABILITY", "SYMBOL 01 - ANY AUTO")

    c.showPage()
    c.save()


# -- Document 2: the agency's ACORD 125 application --------------------------
#
# Mixed case, spelled-out address and state, four-digit unpadded year, coverage
# lines named in short form. Same account, same figures, different printing.

def build_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "ACORD 125 - COMMERCIAL INSURANCE APPLICATION",
              "Agency copy  |  Prepared by %s  |  Date: %s"
              % (AGENCY, TODAY.strftime("%B %d, %Y")))

    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Applicant Name", APP_INSURED)
    y = _row(c, y, "Mailing Address", APP_ADDRESS)
    y = _row(c, y, "FEIN", FEIN)
    y = _row(c, y, "Legal Entity", APP_ENTITY)
    y = _row(c, y, "Agency", AGENCY)

    y = _head(c, y, "POLICY INFORMATION")
    y = _row(c, y, "Policy Number", POLICY_NO)
    y = _row(c, y, "Proposed Effective Date", APP_EFF)
    y = _row(c, y, "Proposed Expiration Date", APP_EXP)
    y = _row(c, y, "Annual Gross Sales", GROSS_SALES)
    y = _row(c, y, "Number of Employees", EMPLOYEES)

    y = _head(c, y, "NATURE OF BUSINESS")
    y = _wrap(c, y, OPS)

    y = _head(c, y, "LINES OF BUSINESS APPLIED FOR")
    y = _table(
        c, y,
        ["LINE OF BUSINESS", "POLICY NUMBER", "EFFECTIVE", "EXPIRATION"],
        [[APP_LINES[0], POLICY_NO, APP_EFF, APP_EXP],
         [APP_LINES[1], POLICY_NO, APP_EFF, APP_EXP]],
        [1.0, 3.1, 4.7, 5.9],
    )

    y = _head(c, y, "General Liability - Limits Requested")
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Personal & Advertising Injury", "$1,000,000")
    y = _row(c, y, "Damage to Premises Rented to You", "$300,000")
    y = _row(c, y, "Medical Expense (any one person)", "$10,000")

    y = _head(c, y, "Automobile Liability - Limits Requested")
    y = _row(c, y, "Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Covered Autos - Liability", "Symbol 01 - Any Auto")

    c.showPage()
    c.save()


# -- Self-verification -------------------------------------------------------

DEC_FACTS = {
    "applicant_name":    DEC_INSURED,
    "entity_type":       DEC_ENTITY,
    "mailing_address":   DEC_ADDRESS,
    "fein":              FEIN,
    "policy_number":     POLICY_NO,
    "carrier_name":      CARRIER,
    "effective_date":    DEC_EFF,
    "expiration_date":   DEC_EXP,
    "total_revenue":     GROSS_SALES,
    "num_employees":     EMPLOYEES,
    "lines_of_business": list(DEC_LINES),
}
APP_FACTS = {
    "applicant_name":    APP_INSURED,
    "entity_type":       APP_ENTITY,
    "mailing_address":   APP_ADDRESS,
    "fein":              FEIN,
    "policy_number":     POLICY_NO,
    "effective_date":    APP_EFF,
    "expiration_date":   APP_EXP,
    "total_revenue":     GROSS_SALES,
    "num_employees":     EMPLOYEES,
    "lines_of_business": list(APP_LINES),
}

# The six rows the block must print, keyed by the label the message starts with.
EXPECTED_ROWS = [
    ("Applicant name",  "entity suffix / punctuation / case"),
    ("Entity type",     "entity-type wording"),
    ("Mailing address", "address formatting"),
    ("Effective date",  "date formatting"),
    ("Expiration date", "date formatting"),
    ("Coverage terms",  "coverage-name equivalence"),
]

ACORD_MODAL = os.path.join(
    REPO, "frontend", "src", "components", "form", "AcordModal.jsx")


def _docs():
    return [
        {"doc_id": "1", "filename": DEC_NAME, "doc_type": "declarations_page",
         "facts": dict(DEC_FACTS), "text": ""},
        {"doc_id": "2", "filename": APP_NAME, "doc_type": "acord_form",
         "facts": dict(APP_FACTS), "text": ""},
    ]


def verify():
    """Drive the real engines over the facts these PDFs are written to produce."""
    from services.sqs_service import (
        check_doc_consistency, split_doc_consistency_issues,
    )
    from services.underwriting_consistency import assess_underwriting_consistency

    problems, docs = [], _docs()
    hard, soft, info, _conf = split_doc_consistency_issues(
        check_doc_consistency(docs))

    # 1. Every expected row is present, in the block the client screenshotted.
    for label, _category in EXPECTED_ROWS:
        if not any(m.startswith(label + ":") for m in info):
            problems.append("MISSING:  no equivalence row for %r" % label)

    # 2. Nothing else fires. A hard stop or a warning here means the fixture
    #    put a red blocker above the block the tester is meant to read.
    for m in hard:
        problems.append("NOISE:    unexpected HARD STOP - %s" % m)
    for m in soft:
        problems.append("NOISE:    unexpected WARNING - %s" % m)

    # 3. The two date spellings really do differ, on today's date.
    if DEC_EFF == APP_EFF or DEC_EXP == APP_EXP:
        problems.append(
            "BROKEN:   the two date formats collapsed today (%s vs %s)"
            % (DEC_EFF, APP_EFF))

    # 4. Data Consistency must stay quiet. Every pair above goes through the
    #    same comparison door (C1/D3), so a conflict row here would mean the
    #    two surfaces disagree - a real defect, not a fixture problem.
    try:
        dc = assess_underwriting_consistency(docs, dict(DEC_FACTS), {})
        for f in dc.get("fields") or []:
            if f.get("status") == "conflict":
                problems.append(
                    "SPLIT:    Data Consistency calls %r a conflict while "
                    "Submission Integrity calls it equivalent"
                    % f.get("fact_key"))
    except Exception as exc:                                  # noqa: BLE001
        problems.append("SKIPPED:  Data Consistency cross-check - %s" % exc)

    # 5. Which side of the fix are we on? Read the real component.
    state = "UNKNOWN"
    try:
        with io.open(ACORD_MODAL, encoding="utf-8") as fh:
            src = fh.read()
        has_bare = "treated as equivalent" in src
        # The fix carries the category through as structured data; the tell is
        # the component normalizing each row and printing its category, instead
        # of splitting a bare sentence on its first colon.
        has_category = "normalizationRow(" in src and "row.category" in src
        state = "POST-FIX" if has_category else ("PRE-FIX" if has_bare else "UNKNOWN")
    except OSError as exc:
        problems.append("SKIPPED:  could not read AcordModal.jsx - %s" % exc)

    return problems, info, state


README = """# UI-04 live test - what does "treated as equivalent" actually mean

TWO uploads, ONE block to read.

## What UI-04 is

The Submission Integrity card tells the broker that two visibly different values
are the same thing, and gives no reason:

    Effective date: {dec_eff}, {app_eff} - treated as equivalent

The reason exists. `check_doc_consistency` emits every one of these lines with
the rule attached (`code=effective_date_normalized`), and two separate parsers
strip that token before it reaches the browser. So the broker is asked to trust
a claim they cannot check.

## 1. Upload

Upload BOTH files together as ONE new package - not two sessions, and not into
an existing session (extraction caches per document):

  * `{dec_name}` - the carrier's declarations page
  * `{app_name}` - the agency's ACORD 125 application

Same account, same figures, printed two different ways. One document cannot
disagree with itself, so a single upload shows nothing.

## 2. Stop on the pre-form Review screen

Do NOT generate forms. The block lives on the screen you land on after upload.
Look at the **SUBMISSION INTEGRITY** card, near the top.

You should see the chip **RESOLVED FORMATTING DIFFERENCE** next to
"Documents verified", and under it:

    Resolved formatting difference
    These values appeared in different formats across your documents but refer
    to the same thing. No action needed.

    Applicant name:  {dec_insured}, {app_insured} - treated as equivalent
    Entity type:     {dec_entity}, {app_entity} - treated as equivalent
    Mailing address: {dec_address}, {app_address} - treated as equivalent
    Effective date:  {dec_eff}, {app_eff} - treated as equivalent
    Expiration date: {dec_exp}, {app_exp} - treated as equivalent
    Coverage terms:  {dec_lines}; {app_lines} - treated as equivalent

**That is the bug. Screenshot it.** Six claims, no reasons.

## 3. What the fix has to change

Re-upload the same two files after the fix ships. Same six rows, but each one
now names the rule that made the two values equal, and the block heading
carries an "i" that explains the concept once:

    Applicant name   [entity suffix / punctuation]
    Entity type      [entity-type wording]
    Mailing address  [address formatting]
    Effective date   [date formatting]
    Expiration date  [date formatting]
    Coverage terms   [coverage-name equivalence]

**PASS** - every row names its category, and the "i" explains what equivalence
means in one short sentence.
**FAIL** - any row still ends with a bare "treated as equivalent", or the
category is missing on one row, or the raw values stopped being shown.

## 4. Nothing else may move

This is display only. After the fix, on the SAME upload:

  * The package score, tier and readiness line are identical.
  * Hard Stops is empty and Warnings carries nothing about these six fields.
  * **DATA CONSISTENCY shows no VALUES DIFFER row for any of them.** That one
    matters: both surfaces read the same comparison door, so if Data
    Consistency starts calling one of these a conflict, the fix broke the door.
  * Generated forms carry the same values they did before.

## 5. What to send back

* The screenshot from step 2 (before) and the same block after the fix.
* Anything that reads wrong in plain English.

## Known and expected

* The block only renders when at least two documents state the same fact with
  different raw text that normalizes equal. Upload one file and it is empty -
  that is correct, not a failure.
* An Auto line with no vehicle schedule may raise its own warnings lower down
  the screen. Unrelated to UI-04; ignore them.
* Dates are generated from today ({today}), so the exact values in this file
  change if you regenerate the PDFs. The FORMATS never change.
"""


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    problems, info, state = verify()

    build_declarations(os.path.join(OUT_DIR, DEC_NAME))
    build_application(os.path.join(OUT_DIR, APP_NAME))

    readme = README.format(
        dec_name=DEC_NAME, app_name=APP_NAME,
        dec_insured=DEC_INSURED, app_insured=APP_INSURED,
        dec_entity=DEC_ENTITY, app_entity=APP_ENTITY,
        dec_address=DEC_ADDRESS, app_address=APP_ADDRESS,
        dec_eff=DEC_EFF, app_eff=APP_EFF,
        dec_exp=DEC_EXP, app_exp=APP_EXP,
        dec_lines=", ".join(DEC_LINES), app_lines=", ".join(APP_LINES),
        today=TODAY.strftime("%Y-%m-%d"),
    )
    with io.open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
                 encoding="utf-8") as fh:
        fh.write(readme)

    print("wrote %s" % os.path.join(OUT_DIR, DEC_NAME))
    print("wrote %s" % os.path.join(OUT_DIR, APP_NAME))
    print("wrote %s" % os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"))

    print("\nThe %d rows the real engine produces for these two documents:" % len(info))
    for m in info:
        print("    %s - treated as equivalent" % m)

    print("\nFrontend state: %s" % state)
    if state == "PRE-FIX":
        print("    AcordModal still renders the bare sentence - this is the "
              "BEFORE run.")
    elif state == "POST-FIX":
        print("    AcordModal reads a category off each row - this is the "
              "AFTER run.")

    if problems:
        print("\nFIXTURE PROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - 6 equivalence rows, no hard stops, no warnings, and Data "
          "Consistency agrees.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
