"""make_sys05_test_pdf.py - ONE live-test package for SYS-05 (coverage normalization).

    py backend/scripts/make_sys05_test_pdf.py

Writes sys05_test_data/SYS05_coverage_parts_package.pdf plus README-HOW-TO-TEST.md.

WHY THE VALUES ARE NOT THE CLIENT'S
-----------------------------------
The client's own instruction for this round: *"These results come from the client's
real documents. Do NOT fix for these specific values."* A fixture that replays
UNINSURED AND UNDERINSURED MOTORISTS / COMPREHENSIVE / COLLISION proves only that
those four strings were added to a list. So every value here is different: a
different insured, different carriers, different policy numbers, different
premiums, and coverage parts printed in SPELLINGS THE CLIENT'S DOCUMENT DID NOT
USE ("UM / UIM Motorists", "Comprehensive (Other Than Collision)", "Towing And
Labor"). If the fix is generic they still resolve; if it is a list of four
strings, they do not.

WHAT ONE UPLOAD PROVES - nine checks, four of them adversarial
---------------------------------------------------------------
  A  AUTO PARTS       five auto components under a Business Auto line
                      -> none may reach "Coverage part not recognised"
  B  GL PARTS         three GL components under a General Liability line
                      -> the defect class is not Auto-only
  C  PROPERTY PARTS   three Property components under a Property line
  D  THE OLD BUG      "Bodily Injury And Property Damage Liability" used to
                      canonicalise to the PROPERTY line. It must read as GL,
                      and must not invent a Property line of business.
  E  DISAMBIGUATION   "Comprehensive Dishonesty, Disappearance And Destruction"
                      is the ISO 3-D CRIME policy. On a package that also
                      carries Auto, the bare word "comprehensive" must NOT drag
                      it into the Auto family. (This exact case was found by the
                      unit tests as a defect in the first cut of the fix.)
  F  STRUCTURAL       "Medical Payments" is a real row on BOTH a GL and an Auto
                      dec page. Printed HERE under the Auto policy's number, so
                      the shared-contract evidence must place it.
  G  THE HONEST GAP   "Bodily Injury" printed as a bare row with NO policy
                      number, on a package carrying both GL and Auto. Two
                      candidate parents and nothing to separate them, so the
                      code REFUSES to guess and this one IS EXPECTED TO WARN.
                      It is in the kit deliberately - it is the open question
                      for the owner, and seeing it live is how that gets decided.
  H  1.7 SURVIVES     "Kidnap And Ransom" and "Political Risk Coverage" are
                      genuinely unplaceable and MUST still reach the producer.
                      A fix that force-maps everything would delete the feature
                      this warning exists to provide.
  I  PREMIUM SUM      Five real lines total $18,605. Every coverage PART also
                      prints its own premium. If parts are summed as lines the
                      total lands near $27,000 instead - the money check that
                      `_name_is_a_line_not_a_part` exists to protect.

NOT COVERED BY ONE FILE
-----------------------
Cross-document comparison ("map these terms BEFORE cross-document comparison")
needs a SECOND document to compare against - one upload cannot disagree with
itself. Ask and it takes a minute to add a matching certificate that lists only
"Automobile Liability", which is the pair that proves the fold.

Design rules inherited from make_h5_test_pdfs.py (all proven):
  * Real text via reportlab - extractable by pdfplumber, no OCR dependency.
  * Column x-positions far enough apart that characters never interleave.
  * Dates computed from TODAY so nothing drifts into an expired-term or renewal
    path (a routed renewal moves dates to prior_* and changes what is asked).
  * Every real LINE prints its own Carrier / NAIC / Policy Number / Premium,
    which is what RULE 16 asks extraction for.
  * Coverage PARTS print under their line's heading and repeat their parent's
    policy number - the shape a real dec page uses, and the evidence check F
    depends on.
  * The generated text is self-verified at the bottom of this file: every phrase
    a check depends on must be present, and the client's own four strings must
    be ABSENT, so this kit can never quietly become a replay of their document.
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
    "sys05_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=30)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=30 + 365)).strftime("%m/%d/%Y")

AGENCY = "Halloran Brooks Risk Advisors Inc"
INSURED = "Marisol Freight & Cold Storage LLC"

CARRIER_A = "Kestrel Mutual Insurance Company"
NAIC_A = "41238"
CARRIER_B = "Aldergrove Specialty Insurance Co"
NAIC_B = "27519"

POL_GL = "KM-GL-884371-26"
POL_AUTO = "KM-BA-990214-26"
POL_PROP = "KM-CP-771655-26"
POL_CRIME = "AG-CR-113977-26"
POL_KR = "AG-KR-220948-26"

# Five REAL lines. Their premiums are the only ones that may be summed.
LINE_PREMIUMS = [7412, 5168, 3940, 1225, 860]
TOTAL = sum(LINE_PREMIUMS)                       # 18,605


def _money(n: int) -> str:
    return f"${n:,}"


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


def _row(c, y, label, value, lw=3.1):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, f"{label}:")
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.205 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.215 * inch


def _line_block(c, y, heading, carrier, naic, policy, premium):
    """A real LINE of business: its own carrier, NAIC, number and premium."""
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Carrier NAIC", naic)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Annual Premium", _money(premium))
    return y


def _parts(c, y, policy, rows):
    """A SCHEDULE OF COVERAGES table - the rows that are coverage PARTS.

    Each repeats its parent line's policy number, exactly as a dec page does.
    This is the structural evidence check F depends on, and the reason check I
    can tell a part's premium from a line's.
    """
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(1.15 * inch, y, "COVERAGE")
    c.drawString(4.15 * inch, y, "LIMIT")
    c.drawString(5.85 * inch, y, "POLICY NO")
    c.drawString(7.00 * inch, y, "PREMIUM")
    y -= 0.19 * inch
    c.setFont("Helvetica", 8)
    for name, limit, prem in rows:
        c.drawString(1.15 * inch, y, name)
        c.drawString(4.15 * inch, y, limit)
        c.drawString(5.85 * inch, y, policy if policy else "")
        c.drawString(7.00 * inch, y, prem)
        y -= 0.185 * inch
    return y - 0.08 * inch


# ── The package ─────────────────────────────────────────────────────────────

def build(path: str) -> None:
    c = canvas.Canvas(path, pagesize=LETTER)

    # ---- Page 1: the insured + the two liability lines -------------------
    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Renewal declarations issued by the company shown for each coverage part")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", "4820 Harborgate Way, Suite 260, Tacoma, WA 98421")
    y = _row(c, y, "FEIN", "47-6120933")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Priya Raghunathan, (253) 555-0186, priya@marisolfreight.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations",
             "Refrigerated trucking and cold storage warehousing of food products")
    y = _row(c, y, "Annual Gross Sales", "$14,300,000")
    y = _row(c, y, "Number of Employees", "62")
    y = _row(c, y, "Years in Business", "17")
    y = _row(c, y, "NAICS Code", "493120")

    # --- GENERAL LIABILITY: checks B and D --------------------------------
    y = _line_block(c, y, "SECTION I - GENERAL LIABILITY",
                    CARRIER_A, NAIC_A, POL_GL, LINE_PREMIUMS[0])
    y = _parts(c, y, POL_GL, [
        # D: this exact phrase used to canonicalise to the PROPERTY line.
        ("Bodily Injury And Property Damage Liability", "$1,000,000", "$2,140"),
        # B: ordinary GL coverage parts, none of which named a line before.
        ("Personal And Advertising Injury", "$1,000,000", "$0"),
        ("Damage To Premises Rented To You", "$300,000", "$415"),
        ("Medical Expense", "$10,000", "$188"),
    ])

    # --- BUSINESS AUTO: checks A and F ------------------------------------
    y = _line_block(c, y, "SECTION II - BUSINESS AUTO",
                    CARRIER_A, NAIC_A, POL_AUTO, LINE_PREMIUMS[1])
    y = _parts(c, y, POL_AUTO, [
        # A: five auto components, spelled UNLIKE the client's document.
        ("UM / UIM Motorists", "$1,000,000", "$742"),
        ("Comprehensive (Other Than Collision)", "ACV less $2,500", "$1,104"),
        ("Collision", "ACV less $2,500", "$1,663"),
        ("Towing And Labor", "$150 per disablement", "$96"),
        ("Rental Reimbursement", "$75 per day", "$128"),
        # F: shared with GL by name, placed only by the policy number it repeats.
        ("Medical Payments", "$5,000", "$213"),
    ])

    # ---- Page 2: property, crime, the specialty line and the total -------
    y = _new_page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS (CONTINUED)",
                  f"Named Insured: {INSURED}")

    # --- PROPERTY: check C ------------------------------------------------
    y = _line_block(c, y, "SECTION III - COMMERCIAL PROPERTY",
                    CARRIER_A, NAIC_A, POL_PROP, LINE_PREMIUMS[2])
    y = _parts(c, y, POL_PROP, [
        ("Business Income With Extra Expense", "$2,400,000", "$1,318"),
        ("Ordinance Or Law", "$500,000", "$402"),
        ("Equipment Breakdown", "$1,000,000", "$611"),
    ])

    # --- CRIME: check E ---------------------------------------------------
    # The heading is the ISO 3-D policy's real name. The package carries Auto,
    # so if the bare word "comprehensive" is allowed to vote this becomes an
    # Auto part and the Crime line disappears.
    y = _line_block(c, y, "SECTION IV - COMPREHENSIVE DISHONESTY, DISAPPEARANCE AND DESTRUCTION",
                    CARRIER_B, NAIC_B, POL_CRIME, LINE_PREMIUMS[3])
    y = _parts(c, y, POL_CRIME, [
        ("Employee Theft", "$250,000", "$690"),
        ("Forgery Or Alteration", "$100,000", "$310"),
    ])

    # --- THE UNPLACEABLE LINE: check H ------------------------------------
    y = _line_block(c, y, "SECTION V - KIDNAP AND RANSOM",
                    CARRIER_B, NAIC_B, POL_KR, LINE_PREMIUMS[4])

    # --- G: the deliberate ambiguity, with NO policy number ---------------
    y = _head(c, y, "SUPPLEMENTAL CHARGES - NOT ATTRIBUTED TO A POLICY")
    y = _parts(c, y, "", [
        ("Bodily Injury", "$1,000,000", "$305"),
    ])

    y = _head(c, y, "PREMIUM SUMMARY")
    y = _row(c, y, "Total Policy Premium", _money(TOTAL))
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(1 * inch, y,
                 "Total is the sum of the five coverage parts shown above. "
                 "Charges listed within a schedule of coverages are included in that "
                 "section's premium.")

    c.showPage()
    c.save()


# ── Self-verification: the fixture must actually contain what it claims ────

_MUST_CONTAIN = [
    "UM / UIM Motorists",
    "Comprehensive (Other Than Collision)",
    "Collision",
    "Towing And Labor",
    "Rental Reimbursement",
    "Medical Payments",
    "Bodily Injury And Property Damage Liability",
    "Personal And Advertising Injury",
    "Damage To Premises Rented To You",
    "Medical Expense",
    "Business Income With Extra Expense",
    "Ordinance Or Law",
    "Equipment Breakdown",
    "COMPREHENSIVE DISHONESTY, DISAPPEARANCE AND DESTRUCTION",
    "KIDNAP AND RANSOM",
    "Bodily Injury",
    "$18,605",
]

# The client's own four strings. Their PRESENCE would make this a replay of the
# reported document instead of a test of the rule (their standing instruction).
_MUST_NOT_CONTAIN = [
    "UNINSURED AND UNDERINSURED MOTORISTS",
    "Uninsured Motorists",
    "COMPREHENSIVE\n",
    "ORBIN",
]


def build_certificate(path: str) -> None:
    """FILE 2 - the certificate, for the clause one document cannot test.

    *"Map these terms into the Commercial Auto/Automobile coverage family
    BEFORE cross-document comparison."* One upload cannot disagree with itself,
    so the fold in `sqs_service.check_doc_consistency` has never been exercised
    live. This is its pair.

    THE POINT: this document describes the SAME policies at the LINE level,
    while file 1 describes them as a SCHEDULE OF COVERAGES. Two levels of
    detail, one programme. Before the fix the two documents' line sets could not
    match - one held {auto}, the other {auto, comprehensive, collision, ...} -
    so they read as different coverage.

    EVERY NAME IS SPELLED A THIRD WAY on purpose. File 1 prints "Business Auto"
    and "UM / UIM Motorists"; this prints "Automobile Liability" and
    "Uninsured/Underinsured Motorist". The client's own document used a fourth
    spelling again. If any of this is a string list rather than a rule, the
    three sets cannot agree.

    IDENTITY IS DELIBERATELY IDENTICAL - same insured, FEIN, carriers, NAICs and
    policy numbers - so any identity or carrier conflict that appears is a FALSE
    one. This half of the kit is as much a control as a test.

    A certificate prints NO premiums, which is correct and load-bearing: the
    materiality gate (D26 - a row with no premium and no limit is not evidence
    the line is carried) means these rows must never raise a review item of
    their own. If a coverage part from THIS file reaches the "Coverage part not
    recognised" warning, the gate has regressed.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and confers no rights upon the holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", INSURED)
    y = _row(c, y, "Insured Address", "4820 Harborgate Way, Suite 260, Tacoma, WA 98421")
    y = _row(c, y, "FEIN", "47-6120933")
    y = _row(c, y, "Certificate Holder", "Cascade Terminal Authority, 900 Alexander Ave, Tacoma, WA 98421")
    y = _row(c, y, "Date Issued", TODAY.strftime("%m/%d/%Y"))

    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _row(c, y, "Insurer A", f"{CARRIER_A}  (NAIC {NAIC_A})")
    y = _row(c, y, "Insurer B", f"{CARRIER_B}  (NAIC {NAIC_B})")

    y = _head(c, y, "COVERAGES - CERTIFICATE NUMBER: CTA-2026-04417")
    c.setFont("Helvetica", 8.5)
    c.drawString(1 * inch, y, "The policies of insurance listed below have been issued to the insured named above "
                              "for the policy period indicated.")
    y -= 0.24 * inch

    # LINE-level names, every one spelled differently from file 1.
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in [(1.10, "TYPE OF INSURANCE"), (3.85, "POLICY NUMBER"),
                 (5.35, "EFF"), (6.20, "EXP"), (7.05, "LIMIT")]:
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for name, pol, limit in [
        # file 1 said "General Liability"
        ("Commercial General Liability", POL_GL, "$1,000,000"),
        # file 1 said "Business Auto" plus a six-row schedule
        ("Automobile Liability", POL_AUTO, "$1,000,000"),
        # file 1 said "Commercial Property"
        ("Property - Special Form", POL_PROP, "$4,200,000"),
        # file 1 said "Comprehensive Dishonesty, Disappearance And Destruction"
        ("Crime - Employee Dishonesty", POL_CRIME, "$250,000"),
        # file 1 said "Kidnap And Ransom" - unplaceable in BOTH documents, so
        # the producer review item must stay, and must be reported ONCE.
        ("Kidnap And Ransom", POL_KR, "$1,000,000"),
    ]:
        c.drawString(1.10 * inch, y, name)
        c.drawString(3.85 * inch, y, pol)
        c.drawString(5.35 * inch, y, EFF)
        c.drawString(6.20 * inch, y, EXP)
        c.drawString(7.05 * inch, y, limit)
        y -= 0.19 * inch
    y -= 0.10 * inch

    # Coverage PARTS again, spelled a THIRD way, and with NO premium - the shape
    # a real certificate uses. The materiality gate must keep these silent.
    y = _head(c, y, "AUTOMOBILE LIABILITY - COVERAGES INCLUDED")
    c.setFont("Helvetica", 8.5)
    for line in [
        "Uninsured/Underinsured Motorist                 $1,000,000",
        "Comprehensive Deductible                        $2,500",
        "Collision Deductible                            $2,500",
        "Hired And Non-Owned Auto                        Included",
        "Auto Medical Payments                           $5,000",
    ]:
        c.drawString(1.15 * inch, y, line)
        y -= 0.185 * inch

    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    c.setFont("Helvetica", 8.5)
    c.drawString(1 * inch, y,
                 "Refrigerated trucking and cold storage warehousing of food products. "
                 "Certificate holder is an additional insured")
    y -= 0.17 * inch
    c.drawString(1 * inch, y, "with respect to operations at the terminal, as required by written contract.")

    c.showPage()
    c.save()


def _verify(path: str) -> None:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    missing = [p for p in _MUST_CONTAIN if p not in text]
    if missing:
        raise SystemExit(f"FIXTURE BROKEN - phrases missing from the PDF: {missing}")
    present = [p for p in _MUST_NOT_CONTAIN if p.strip() and p in text]
    if present:
        raise SystemExit(
            f"FIXTURE INVALID - it replays the client's own values: {present}")
    print(f"  self-check OK - {len(_MUST_CONTAIN)} phrases present, "
          f"{len(_MUST_NOT_CONTAIN)} forbidden strings absent")
    return text


README = f"""# SYS-05 live test - ONE package, nine checks

Generated by `backend/scripts/make_sys05_test_pdf.py`. Values are deliberately
NOT the client's, so a fix that only added their four strings to a list fails here.

**File:** `SYS05_coverage_parts_package.pdf`
**Insured:** {INSURED}
**Five real lines:** General Liability, Business Auto, Commercial Property,
Crime (3-D), Kidnap and Ransom. **Total premium: {_money(TOTAL)}.**

---

## How to run it

1. Upload the PDF as a NEW submission (not into an existing session - extraction
   caches per document).
2. Select **ACORD 125 + ACORD 126 + ACORD 127 + ACORD 140**.
3. Stop at the **review / Submission Integrity** screen and record checks 1-5
   BEFORE generating anything.
4. Then generate the forms and record checks 6-8.

---

## What to record and send back

### On the review screen (before generating)

**1. The "Coverage part not recognised" warning - the whole point.**
   Copy its FULL text, or write "not present".

   * PASS = it lists **only** `Kidnap And Ransom` and, expectedly, `Bodily Injury`.
   * FAIL = it lists any of: `UM / UIM Motorists`, `Comprehensive (Other Than
     Collision)`, `Collision`, `Towing And Labor`, `Rental Reimbursement`,
     `Medical Payments`, `Personal And Advertising Injury`, `Damage To Premises
     Rented To You`, `Medical Expense`, `Business Income With Extra Expense`,
     `Ordinance Or Law`, `Equipment Breakdown`.

   `Bodily Injury` appearing is **EXPECTED, not a bug** - it is printed with no
   policy number on a package carrying both GL and Auto, so the code refuses to
   guess which line it belongs to. Whether that should instead be guessed is an
   open question for you; seeing it here is how you decide.

**2. Does that warning show a Resolve BUTTON, or a small grey italic note?**
   Expected: a note reading *"Primble can't tell which line this belongs to.
   Check the source document, then mark it resolved."* No button.

**3. Is there a line under it reading "Advice only - this does not affect your score"?**
   Expected: yes.

**4. WHICH section is it in?**
   Expected: the lowest warnings tier ("Before binding" / binder follow-up).
   It should **NOT** be in the red **IMPORTANT** band any more.

**5. Any warning mentioning "Lines of business differ" or a Property line?**
   Expected: none. If a **Property** line appears anywhere on a package whose
   only property section is Commercial Property, say so - that is the
   `Bodily Injury And Property Damage Liability` bug coming back.

### After generating the forms

**6. ACORD 125 - the "Other line of business" rows.**
   Expected: no row reading `Collision`, `Comprehensive`, `Medical Payments`,
   `Ordinance Or Law` or similar. Coverage parts are not lines of business.
   Screenshot that block.

**7. ACORD 125 - Total Policy Premium (or estimated total).**
   Expected: **{_money(TOTAL)}**. If it shows roughly $27,000 the coverage parts
   are being summed as if they were lines - a money defect.

**8. Lines of business shown on the submission / extracted data.**
   Expected 5: General Liability, Business Auto, Commercial Property, Crime,
   and the unplaced Kidnap and Ransom. **Crime must still be there** - if the
   3-D policy vanished or turned into Auto, the "comprehensive" disambiguation
   broke.

**9. Anything else that looks wrong.** Screenshots beat descriptions.

---

# RUN 2 - the cross-document half (BOTH files together)

**File:** `SYS05_certificate_same_programme.pdf`, uploaded **together with** the
dec page in ONE submission.

It describes the SAME five policies - same insured, same FEIN, same carriers,
same NAICs, same policy numbers - but at the LINE level, and **every name is
spelled a third way**:

| The dec page prints | The certificate prints |
|---|---|
| `General Liability` | `Commercial General Liability` |
| `Business Auto` + a six-row schedule | `Automobile Liability` |
| `Commercial Property` | `Property - Special Form` |
| `Comprehensive Dishonesty, Disappearance And Destruction` | `Crime - Employee Dishonesty` |
| `UM / UIM Motorists` | `Uninsured/Underinsured Motorist` |
| `Medical Payments` | `Auto Medical Payments` |

Three spellings of one programme (the client's document used a fourth). If any
of this is a string list rather than a rule, they cannot agree.

The certificate prints **no premiums**, which is deliberate: a row with no
premium and no limit is not evidence a line is carried (D26), so none of its
coverage parts may raise a review item of their own.

## What to record from run 2

**A. Documents Processed** - expected: **2 documents**, "appear to belong to the
   same submission". If it says they do not, that is a false identity split.

**B. The "Coverage part not recognised" warning.**
   Expected: `Kidnap and Ransom`, **reported ONCE**, not twice. Both documents
   name it; one review item, not one per document.
   FAIL = any of `Uninsured/Underinsured Motorist`, `Comprehensive Deductible`,
   `Collision Deductible`, `Hired And Non-Owned Auto`, `Auto Medical Payments`.

**C. Any "Lines of business differ" warning?** Expected: **none.** This is the
   acceptance criterion. The two documents describe identical coverage at two
   levels of detail; only a genuine conflict about Auto should raise one.

**D. Any "Coverage terms: ..." informational notice?** If one appears, **copy it
   verbatim** - it prints each document's raw line list, which is the only way
   to see what extraction actually put in `lines_of_business`. Send it even if
   everything else passes; a term called `medical payments` showing up unfolded
   there is a known ambiguity I want to see live.

**E. Data Consistency** - expected: still "not a conflict", Kestrel on
   auto / general liab / property, Aldergrove on crime. Two documents naming the
   same carriers must not manufacture a conflict.

**F. ACORD 125 again** - Total Policy Premium **{_money(TOTAL)}**, and the
   **CRIME premium box must now show $1,225** (it was blank in run 1; the box
   only accepted the ACORD word "crime" and the dec prints the ISO name).

**G. Anything that appears in run 2 but not in run 1.** That difference is
   exactly what the second document buys.
"""


_COI_MUST_CONTAIN = [
    "Commercial General Liability", "Automobile Liability",
    "Property - Special Form", "Crime - Employee Dishonesty",
    "Kidnap And Ransom", "Uninsured/Underinsured Motorist",
    "Hired And Non-Owned Auto", "Auto Medical Payments",
    POL_GL, POL_AUTO, POL_PROP, POL_CRIME, INSURED, CARRIER_A, CARRIER_B,
]

# The certificate must describe the SAME programme in DIFFERENT words. If any of
# file 1's line spellings appears here, the pair stops testing normalisation and
# starts testing string equality.
_COI_MUST_NOT_CONTAIN = [
    "Business Auto", "UM / UIM Motorists", "Comprehensive (Other Than Collision)",
    "Comprehensive Dishonesty", "General Liability\n", "Commercial Property",
]


def _verify_coi(path: str) -> None:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    missing = [p for p in _COI_MUST_CONTAIN if p not in text]
    if missing:
        raise SystemExit(f"CERTIFICATE BROKEN - phrases missing: {missing}")
    same = [p for p in _COI_MUST_NOT_CONTAIN if p.strip() and p in text]
    if same:
        raise SystemExit(
            "CERTIFICATE INVALID - it reuses file 1's own spellings, so the "
            f"pair would pass on string equality rather than normalisation: {same}")
    print(f"  certificate self-check OK - {len(_COI_MUST_CONTAIN)} phrases present, "
          f"and none of file 1's spellings reused")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "SYS05_coverage_parts_package.pdf")
    build(path)
    _verify(path)

    coi = os.path.join(OUT_DIR, "SYS05_certificate_same_programme.pdf")
    build_certificate(coi)
    _verify_coi(coi)

    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(README)
    print(f"wrote {path}")
    print(f"wrote {coi}")
    print(f"wrote {os.path.join(OUT_DIR, 'README-HOW-TO-TEST.md')}")


if __name__ == "__main__":
    main()
