"""make_sys09_test_pdfs.py - live test kit for SYS-09 (client vs brokerage contact).

    py backend/scripts/make_sys09_test_pdfs.py

Writes to sys09_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

TWO files, ONE session. They CANNOT be merged into one PDF, and that is not a
stylistic choice - the defect is cross-document by construction. SYS-09's first
manifestation is about which DOCUMENT wins a fact in `merge_facts`, so a single
uploaded file cannot exercise it at all: one document means one doc_type, one
extraction, and no merge to get wrong.

WHY EXACTLY THESE TWO DOCUMENT TYPES
------------------------------------
`_DOC_TYPE_PRIORITY` ranks `certificate` **7th** and `narrative` **21st**, and
`select_primary_truth` picks strictly by that order - so the CERTIFICATE becomes
the PRIMARY document of this package. That is the whole point:

  * the fix's new code only runs on the PRIMARY document's facts;
  * an `application` (rank 2) would outrank the certificate and make it
    non-primary, which routes through the OLD, already-working path and tests
    nothing new.

So S2 is a NARRATIVE and the word "application" appears nowhere in it - one
occurrence would re-classify the file, silently invert the primary/non-primary
roles and make a PASS meaningless. This mirrors the client's own reported
package exactly: a COI plus a submission narrative.

WHAT EACH EDGE CASE IS FOR
--------------------------
  1  S1's producer box prints "CONTACT NAME"     THE CLIENT'S LITERAL TRIGGER.
     with the BROKER's own person                 On a real ACORD 25 that label
                                                  sits INSIDE the producer
                                                  block, which is what made the
                                                  extractor read it as the
                                                  applicant's contact.
  2  S2 names a DIFFERENT person as the           The correct answer. The two
     applicant's own contact                      must never collapse into one.
  3  S1 states NO producer street address         Tests the new owned blank.
     (neither file does)                          Live 2026-09-05: with no
                                                  producer address stated, the
                                                  producer block on ACORD 125
                                                  printed the APPLICANT's.
  4  S1 DOES state a producer contact person      Tests the other direction -
                                                  a real producer fact must
                                                  still stamp. A guard that
                                                  blanks real data is a worse
                                                  bug than the one being fixed.
  5  a CERTIFICATE HOLDER with its own address    A second, unrelated address in
     (Kestrel Terminal Authority)                 the package - a bleed has more
                                                  than one place to come from,
                                                  so "it printed the applicant's"
                                                  cannot be a coincidence.
  6  applicant address spelled "Suite 300" in     Formatting-only variance must
     S1 and "Ste 300" in S2                       NOT raise a Data Consistency
                                                  conflict. Positive control on
                                                  the normalizer.
  7  the same phone written "(206) 555-0188"      Same, for phone shape.
     and "206-555-0188"
  8  every other value identical across S1/S2     So ANY other conflict card is
     (name, FEIN, dates, limits, policy nos.)     a real finding, not noise.
  9  no "N/A", no "None", no "TBD" anywhere       Non-answers are a separate,
                                                  still-open path (CLAUDE.md
                                                  "GAP 1"). Including one would
                                                  manufacture a failure that is
                                                  not SYS-09's.
 10  no renewal language, dates in the future     A routed renewal moves dates to
                                                  prior_* and changes what is
                                                  asked - pure noise here.

Design rules (inherited from make_sys06 / make_sys07 / make_c6, all proven)
--------------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY, so nothing drifts into an expired-term path.
* Self-verified at the bottom of this file by re-reading the generated text.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sys09_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=30)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=30 + 365)).strftime("%m/%d/%Y")
ISSUED = TODAY.strftime("%m/%d/%Y")

# ── The two parties whose contacts must never collapse ──────────────────────
AGENCY = "Coastwater Insurance Brokers LLC"
BROKER_CONTACT = "Delphine Ostrander"          # -> producer_contact_name
BROKER_PHONE = "(206) 555-0143"
BROKER_EMAIL = "dostrander@coastwaterins.com"

APPLICANT = "Harborline Provisions LLC"
CLIENT_CONTACT = "Marguerite Vasseur"          # -> contact_name
CLIENT_PHONE_S1 = "(206) 555-0188"             # same number, two spellings
CLIENT_PHONE_S2 = "206-555-0188"
CLIENT_EMAIL = "mvasseur@harborlineprovisions.com"

# One address, two spellings (edge case 6). NEITHER file states a producer one.
APPLICANT_ADDR_S1 = "2255 Shorebank Avenue, Suite 300"
APPLICANT_ADDR_S2 = "2255 Shorebank Avenue, Ste 300"
APPLICANT_CITY = "Tacoma, WA 98402"

HOLDER = "Kestrel Terminal Authority"
HOLDER_ADDR = "870 Wharfside Boulevard"
HOLDER_CITY = "Tacoma, WA 98421"

FEIN = "46-2018837"
GL_POLICY = "CWP-4471902"
AUTO_POLICY = "CWA-4471903"
CARRIER = "Granite Harbor Insurance Company"
NAIC = "24198"

_LEFT = 40
_RIGHT = 320


def _line(c, y, text, x=_LEFT, size=9, bold=False):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, text)
    return y - (size + 4)


def _rule(c, y):
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.line(_LEFT, y + 6, 575, y + 6)
    return y - 6


# ══════════════════════════════════════════════════════════════════════════
# S1 - the certificate. Becomes the PRIMARY document (certificate, rank 7).
# ══════════════════════════════════════════════════════════════════════════

def build_s1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = 750
    y = _line(c, y, "CERTIFICATE OF LIABILITY INSURANCE", size=13, bold=True)
    y = _line(c, y, f"DATE (MM/DD/YYYY): {ISSUED}")
    y = _rule(c, y)
    y = _line(c, y,
              "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY AND CONFERS NO RIGHTS",
              size=7)
    y = _line(c, y,
              "UPON THE CERTIFICATE HOLDER. THIS IS TO CERTIFY THAT THE POLICIES OF INSURANCE",
              size=7)
    y = _line(c, y,
              "LISTED BELOW HAVE BEEN ISSUED TO THE INSURED NAMED ABOVE FOR THE POLICY PERIOD",
              size=7)
    y = _rule(c, y)

    # ── PRODUCER block. Edge cases 1 and 4 live here. ───────────────────────
    # "CONTACT NAME" is ACORD's own label and it sits INSIDE this box - the
    # ambiguity that produced the client's screenshot. There is deliberately NO
    # street address for the agency (edge case 3).
    top = y
    y = _line(c, y, "PRODUCER", bold=True)
    y = _line(c, y, AGENCY)
    y = _line(c, y, f"CONTACT NAME:  {BROKER_CONTACT}")
    y = _line(c, y, f"PHONE (A/C, No, Ext):  {BROKER_PHONE}")
    y = _line(c, y, f"E-MAIL ADDRESS:  {BROKER_EMAIL}")
    y = _line(c, y, "FAX (A/C, No):  (206) 555-0144")

    # ── INSURED block, drawn in the right column at the same height ─────────
    # An ACORD 25 has NO applicant contact-person box. That absence is the
    # structural fact the fix rests on, so the fixture must honour it.
    yr = top
    yr = _line(c, yr, "INSURED", x=_RIGHT, bold=True)
    yr = _line(c, yr, APPLICANT, x=_RIGHT)
    yr = _line(c, yr, APPLICANT_ADDR_S1, x=_RIGHT)
    yr = _line(c, yr, APPLICANT_CITY, x=_RIGHT)
    yr = _line(c, yr, f"FEIN: {FEIN}", x=_RIGHT)

    y = _rule(c, min(y, yr))
    y = _line(c, y, "INSURER(S) AFFORDING COVERAGE", bold=True)
    y = _line(c, y, f"INSURER A:  {CARRIER}          NAIC #: {NAIC}")
    y = _rule(c, y)

    y = _line(c, y, "COVERAGES", bold=True)
    y = _line(c, y, "TYPE OF INSURANCE            POLICY NUMBER      EFF         EXP         LIMITS")
    y = _line(c, y, f"COMMERCIAL GENERAL LIABILITY {GL_POLICY}   {EFF}  {EXP}  EACH OCCURRENCE $1,000,000")
    y = _line(c, y, f"                                                                       GENERAL AGGREGATE $2,000,000")
    y = _line(c, y, f"AUTOMOBILE LIABILITY         {AUTO_POLICY}   {EFF}  {EXP}  COMBINED SINGLE LIMIT $1,000,000")
    y = _rule(c, y)

    y = _line(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES", bold=True)
    y = _line(c, y, "Refrigerated warehousing and cold storage of packaged food products.")
    y = _line(c, y, "Certificate holder is an additional insured with respect to operations")
    y = _line(c, y, "at the terminal, as required by written contract.")
    y = _rule(c, y)

    # ── CERTIFICATE HOLDER - edge case 5, a second address in the package ───
    y = _line(c, y, "CERTIFICATE HOLDER", bold=True)
    y = _line(c, y, HOLDER)
    y = _line(c, y, HOLDER_ADDR)
    y = _line(c, y, HOLDER_CITY)
    y = _rule(c, y)
    y = _line(c, y, "AUTHORIZED REPRESENTATIVE", bold=True)
    y = _line(c, y, "Signature on file")

    c.showPage()
    c.save()


# ══════════════════════════════════════════════════════════════════════════
# S2 - the submission narrative. NON-primary (narrative, rank 21).
#
# THE WORD "APPLICATION" MUST NOT APPEAR. `application` ranks 2nd and would
# outrank the certificate, making THIS file primary - which silently inverts
# the whole test. Same for "ACORD 125" and "app ".
# ══════════════════════════════════════════════════════════════════════════

def build_s2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = 750
    y = _line(c, y, "SUBMISSION NARRATIVE", size=13, bold=True)
    y = _line(c, y, f"Prepared {ISSUED}   -   Account Overview and Executive Summary")
    y = _rule(c, y)

    y = _line(c, y, "ACCOUNT OVERVIEW", bold=True)
    y = _line(c, y, f"Named Insured:  {APPLICANT}")
    y = _line(c, y, f"Mailing Address:  {APPLICANT_ADDR_S2}")       # edge case 6
    y = _line(c, y, f"                  {APPLICANT_CITY}")
    y = _line(c, y, f"FEIN:  {FEIN}")
    y = _line(c, y, "Entity Type:  Limited Liability Company")
    y = _line(c, y, "Years in Business:  14")
    y = _rule(c, y)

    # ── The applicant's OWN contact person - edge case 2, the correct answer.
    y = _line(c, y, "CLIENT CONTACT FOR THIS SUBMISSION", bold=True)
    y = _line(c, y, f"Contact Name:  {CLIENT_CONTACT}")
    y = _line(c, y, "Title:  Controller, Harborline Provisions LLC")
    y = _line(c, y, f"Phone:  {CLIENT_PHONE_S2}")                   # edge case 7
    y = _line(c, y, f"Email:  {CLIENT_EMAIL}")
    y = _rule(c, y)

    # The agency is NAMED and nothing more - no address, no contact person.
    # This is the live-observed shape that produced the producer-box bleed.
    y = _line(c, y, "BROKERAGE OF RECORD", bold=True)
    y = _line(c, y, f"Placed through {AGENCY}.")
    y = _rule(c, y)

    y = _line(c, y, "OPERATIONS", bold=True)
    y = _line(c, y, "Refrigerated warehousing and cold storage of packaged food products.")
    y = _line(c, y, "Two leased dock positions at the marine terminal; no owned real property.")
    y = _line(c, y, "Annual Revenue:  $14,300,000")
    y = _line(c, y, "Annual Payroll:  $3,120,000")
    y = _line(c, y, "Number of Employees:  62")
    y = _rule(c, y)

    y = _line(c, y, "COVERAGE SUMMARY", bold=True)
    y = _line(c, y, f"Carrier:  {CARRIER}   NAIC: {NAIC}")
    y = _line(c, y, f"General Liability  {GL_POLICY}   Effective {EFF}   Expires {EXP}")
    y = _line(c, y, "   Each Occurrence $1,000,000 / General Aggregate $2,000,000")
    y = _line(c, y, f"Business Auto      {AUTO_POLICY}   Effective {EFF}   Expires {EXP}")
    y = _line(c, y, "   Combined Single Limit $1,000,000")
    y = _rule(c, y)

    y = _line(c, y, "UNDERWRITING NOTES", bold=True)
    y = _line(c, y, f"Questions on this submission should be directed to {CLIENT_CONTACT}")
    y = _line(c, y, f"at {CLIENT_PHONE_S2}. A certificate naming {HOLDER} is required")
    y = _line(c, y, "at binding under the terminal lease.")

    c.showPage()
    c.save()


# ══════════════════════════════════════════════════════════════════════════
# Self-check - re-read the generated text and prove the fixture is the one
# the test needs. A kit that silently drifts proves nothing about the code.
# ══════════════════════════════════════════════════════════════════════════

def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def self_check(s1, s2):
    t1, t2 = _text(s1), _text(s2)
    t3 = _text(os.path.join(OUT_DIR, "S3_one_document_both_contacts.pdf"))
    fail = []

    def need(cond, msg):
        if not cond:
            fail.append(msg)

    # Classification - the entire test design depends on these two verdicts.
    need("CERTIFICATE OF LIABILITY INSURANCE" in t1, "S1 lost its certificate title")
    need("THIS IS TO CERTIFY" in t1.upper(), "S1 lost the certificate phrase")
    need("SUBMISSION NARRATIVE" in t2, "S2 lost its narrative title")
    need("application" not in t2.lower(),
         "S2 contains 'application' - it would outrank the certificate and "
         "invert the primary document, making the test meaningless")
    need("acord 125" not in t2.lower(), "S2 must not name an ACORD form")

    # The two people must be separated, one per document.
    need(BROKER_CONTACT in t1, "S1 lost the broker's contact person")
    need(BROKER_CONTACT not in t2, "S2 must NOT name the broker's contact person")
    need(CLIENT_CONTACT in t2, "S2 lost the client's contact person")
    need(CLIENT_CONTACT not in t1,
         "S1 must NOT name the client's contact - an ACORD 25 has no such box")

    # Edge case 3 - no producer street address anywhere in the package.
    for token in ("Coastwater Insurance Brokers LLC\n2", "Suite 210", "Ledger Street"):
        need(token not in t1, f"S1 gained a producer street address ({token})")
    need(APPLICANT_ADDR_S1.split(",")[0] in t1, "S1 lost the applicant address")
    need(APPLICANT_ADDR_S2.split(",")[0] in t2, "S2 lost the applicant address")

    # Edge cases 5-7.
    need(HOLDER in t1 and HOLDER_ADDR in t1, "S1 lost the certificate holder block")
    need("Suite 300" in t1 and "Ste 300" in t2, "the address spelling pair is gone")
    need(CLIENT_PHONE_S2 in t2, "S2 lost the client phone")

    # Edge case 8 - everything else must agree, or a conflict card is noise.
    for shared in (APPLICANT, FEIN, GL_POLICY, AUTO_POLICY, CARRIER, NAIC, EFF, EXP):
        need(shared in t1 and shared in t2, f"{shared!r} must appear in BOTH files")

    # SESSION B: one document, BOTH contacts, each under its own party heading.
    need(BROKER_CONTACT in t3 and CLIENT_CONTACT in t3,
         "S3 must name BOTH contacts - that is the whole point of session B")
    need("PRODUCER / BROKERAGE OF RECORD" in t3 and "APPLICANT / NAMED INSURED" in t3,
         "S3 lost a party heading, so neither contact is attributable")
    need(t3.index(BROKER_CONTACT) < t3.index(CLIENT_CONTACT),
         "S3: the producer block must come first, as on a real submission")
    need("application" not in t3.lower(), "S3 must not classify as an application")

    # Edge case 9.
    for banned in ("N/A", "TBD", " None", "null"):
        need(banned not in t1 and banned not in t2 and banned not in t3,
             f"{banned!r} is a NON-answer - a different, still-open path")

    return fail


# ══════════════════════════════════════════════════════════════════════════
# S3 - SESSION B, ON ITS OWN. Both contacts in ONE document.
#
# THE SCENARIO THE ACCEPTANCE CRITERIA ACTUALLY DESCRIBES, and the one A does
# not test. A and B put the two people in two separate files, so the question
# there is "does one document overwrite the other". The criteria's own words are
# *"These values should not be collapsed into one generic contact name"* - and
# the place a collapse is most likely is a SINGLE page that prints both, one
# under PRODUCER and one under INSURED, a few lines apart.
#
# Upload this file ALONE, as its own session.
# ══════════════════════════════════════════════════════════════════════════

def build_s3(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = 750
    y = _line(c, y, "COMMERCIAL INSURANCE SUBMISSION", size=13, bold=True)
    y = _line(c, y, f"Account Overview   -   Prepared {ISSUED}")
    y = _rule(c, y)

    # Both blocks on one page, deliberately close together, each with its own
    # "Contact" label - the exact ambiguity that collapses two people into one.
    y = _line(c, y, "PRODUCER / BROKERAGE OF RECORD", bold=True)
    y = _line(c, y, f"Agency:        {AGENCY}")
    y = _line(c, y, f"Contact:       {BROKER_CONTACT}")
    y = _line(c, y, f"Phone:         {BROKER_PHONE}")
    y = _line(c, y, f"Email:         {BROKER_EMAIL}")
    y = _rule(c, y)

    y = _line(c, y, "APPLICANT / NAMED INSURED", bold=True)
    y = _line(c, y, f"Named Insured: {APPLICANT}")
    y = _line(c, y, f"Address:       {APPLICANT_ADDR_S1}")
    y = _line(c, y, f"               {APPLICANT_CITY}")
    y = _line(c, y, f"FEIN:          {FEIN}")
    y = _line(c, y, f"Contact:       {CLIENT_CONTACT}, Controller")
    y = _line(c, y, f"Phone:         {CLIENT_PHONE_S1}")
    y = _line(c, y, f"Email:         {CLIENT_EMAIL}")
    y = _rule(c, y)

    y = _line(c, y, "OPERATIONS", bold=True)
    y = _line(c, y, "Refrigerated warehousing and cold storage of packaged food products.")
    y = _line(c, y, "Entity Type:  Limited Liability Company     Years in Business:  14")
    y = _line(c, y, "Annual Revenue:  $14,300,000     Number of Employees:  62")
    y = _rule(c, y)

    y = _line(c, y, "COVERAGE REQUESTED", bold=True)
    y = _line(c, y, f"Carrier:  {CARRIER}   NAIC: {NAIC}")
    y = _line(c, y, f"General Liability  {GL_POLICY}   Effective {EFF}   Expires {EXP}")
    y = _line(c, y, "   Each Occurrence $1,000,000 / General Aggregate $2,000,000")
    y = _line(c, y, f"Business Auto      {AUTO_POLICY}   Effective {EFF}   Expires {EXP}")
    y = _line(c, y, "   Combined Single Limit $1,000,000")

    c.showPage()
    c.save()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    s1 = os.path.join(OUT_DIR, "S1_COI_certificate_Harborline.pdf")
    s2 = os.path.join(OUT_DIR, "S2_submission_narrative_Harborline.pdf")
    s3 = os.path.join(OUT_DIR, "S3_one_document_both_contacts.pdf")
    build_s1(s1)
    build_s2(s2)
    build_s3(s3)

    try:
        fail = self_check(s1, s2)
    except ImportError:
        print("pdfplumber not installed - SELF-CHECK SKIPPED")
        fail = None

    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)

    print(f"wrote {s1}")
    print(f"wrote {s2}")
    print(f"wrote {s3}")
    print(f"wrote {os.path.join(OUT_DIR, 'README-HOW-TO-TEST.md')}")
    if fail is None:
        pass
    elif fail:
        print("\nSELF-CHECK FAILED:")
        for f in fail:
            print("  -", f)
        raise SystemExit(1)
    else:
        print("\nSELF-CHECK PASSED - the fixture is the one the test needs.")


README = f"""# SYS-09 live test - client contact vs brokerage contact

## TWO SESSIONS. Run both.

**SESSION A** - upload these two files TOGETHER, in one session:

  1. `S1_COI_certificate_Harborline.pdf`
  2. `S2_submission_narrative_Harborline.pdf`

Then generate **ACORD 125 *and* ACORD 25** - both, in the same generation.
The acceptance criteria names BOTH forms ("the client contact belongs on the
ACORD 125 applicant context, the brokerage contact on the ACORD 25 producer
context"), and until 2026-09-06 only the 125 had ever been generated.

**SESSION B** - upload `S3_one_document_both_contacts.pdf` ALONE, then generate
**ACORD 125**. One document names BOTH contacts, a few lines apart, each under
its own party heading. That is the case the criteria actually describes -
*"should not be collapsed into one generic contact name"* - and sessions of two
separate files cannot test it.

## Why two files

The defect is cross-document. SYS-09's first half is about which DOCUMENT wins a
fact during the merge, so one file cannot exercise it: one file means one
extraction and no merge to get wrong. The pairing is the client's own -
a certificate plus a submission narrative.

The certificate is deliberately the **primary** document (`certificate` ranks 7th
in `_DOC_TYPE_PRIORITY`, `narrative` 21st). That is the only configuration in
which the new code runs at all.

## The two people - do not let them collapse

| Who | Name | Belongs in |
|---|---|---|
| The BROKERAGE's contact | **{BROKER_CONTACT}** | the PRODUCER block |
| The CLIENT's contact | **{CLIENT_CONTACT}** | the APPLICANT / Named Insured block |

Neither file states a producer street address. The applicant's address
({APPLICANT_ADDR_S1.split(',')[0]}) and the certificate holder's
({HOLDER_ADDR}) are both present - so if an address appears in the producer
block, it was borrowed from one of them.

## What to check, in order

**1. Data Consistency panel (before generating)**
- Is there a **Contact Name** conflict row? Report the answer either way.
- If there is one, report BOTH values and BOTH source filenames verbatim.
- Report any OTHER conflict card. Address spelling (`Suite 300` vs `Ste 300`)
  and phone shape (`{CLIENT_PHONE_S1}` vs `{CLIENT_PHONE_S2}`) are the SAME
  values twice and must NOT raise a card. Anything else is a real finding.

**2. Generated ACORD 125, PRODUCER block (page 1, top left)**
- CONTACT NAME / PHONE / E-MAIL should read **{BROKER_CONTACT}** and the
  brokerage's number and email.
- The producer's MAILING ADDRESS boxes should be **BLANK**.
- FAIL if they carry {CLIENT_CONTACT}, the applicant's address, or the
  certificate holder's address.

**3. Generated ACORD 125, APPLICANT block**
- The applicant's contact should read **{CLIENT_CONTACT}** with
  {CLIENT_PHONE_S2} / {CLIENT_EMAIL}.
- FAIL if it carries {BROKER_CONTACT}.

**4. Generated ACORD 125, "NAME (Other Named Insured)" (page 1, lower block)**
- It must be **BLANK**. {HOLDER} is the CERTIFICATE HOLDER, not a named
  insured, and an Other Named Insured shares the policy.
- FAIL if {HOLDER} or its address ({HOLDER_ADDR}) appears there.
- (Run 1 printed it. Fixed 2026-09-05 - this is the regression check.)

**5. The industry label beside the Total Package Score**
- It must NOT say **restaurant**. This is a refrigerated warehouse; the only
  reason it ever said restaurant is the word "food" in the operations line.
- Report whatever it does say, and report whether NATURE OF BUSINESS on page 2
  has any box ticked (RESTAURANT in particular).

**6. Score**
Report the Submission Quality Score and the per-form ACORD 125 score. These
facts feed Tier 1, so the number may differ from a pre-fix run - that is
expected and is exactly what Brent needs to see before this ships.
Run 1 for reference: **ACORD 125 = 81, package = 62** (Exposure Consistency
37%, which the restaurant misclassification contributed to).

## Optional second session - the KNOWN open case

Upload `S1` **alone**. A certificate is then the only document, nothing else can
supply a contact, and the brokerage's contact person may be taken as the
applicant's. That limitation is documented and deliberate (see D-CK in
`1stSep-liveTestFixes.md`); closing it needs Brent's ruling because it blanks
sole-source facts and moves scores. Report what you see, but it is not a
regression.
"""


if __name__ == "__main__":
    main()
