"""make_c5_test_pdfs.py - live test packages for V1 item C5 (Source Lineage &
E&O Audit Record, client master-plan section 5).

    py backend/scripts/make_c5_test_pdfs.py

Writes to c5_test_data/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks and exactly what to send back.

THE DESIGN RULE THIS FILE IS BUILT ON (the inverse of C4's)
-----------------------------------------------------------
C4 tested question ROUTING, so its fixtures had to OMIT the values under test.
C5 tests LINEAGE - "this value came from THIS file, THIS page" - so every value
whose citation is being checked must be PRINTED, deliberately, on a KNOWN page
of a KNOWN file:

    STATE   every value whose Evidence line the check reads, on the page the
            check names;
    AGREE   across two files when the check is 5.4 (all supporting sources);
    DISAGREE across two files when the check is 5.10 (conflict resolution);
    OMIT    only what a DERIVATION check needs absent (years-in-business is
            derived only when the document does NOT print it; the proposed
            renewal expiration is REFUSED only when the term length is not an
            ordinary year).

`_verify()` at the bottom re-reads every generated PDF with pdfplumber and
FAILS THE BUILD if a value is missing from the page its check cites, if a
multi-page file collapsed to one page (page citations need page markers, which
the OCR layer only emits for multi-page documents), or if S3's term is not
actually expired relative to today. Dates are computed from TODAY so the
renewal scenario cannot drift out of its path.

Scenario -> the client 5.x clause it proves live
    S1  package policy (4 pages) + COI     5.2 documents; 5.3/5.5 Document +
        stating the SAME GL limit          Page; 5.4 both sources kept; 5.6
        (2 files, upload together)         schedules not "unspecified"; 5.7
                                           derived years-in-business; then the
                                           action flows: 5.8 answers, 5.9
                                           overrides, 5.11 events, 5.12
                                           snapshots, 5.13 download w/ open
    S2  renewal dec whose 6-month term     5.7 derivation (the client's own
        has already ENDED (1 file)         worked example) + "what remained
                                           unresolved" (refused value)
    S3  umbrella package $3M + COI $1M     5.10 conflict resolution history
        (2 files, upload together)         with every competing value + source
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "c5_test_data",
)

TODAY = datetime.now()


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


# S1 / S3: an ordinary future annual term.
EFF, EXP = _d(30), _d(30 + 365)
# S2: an already-ENDED SIX-MONTH term (183 days is outside the 300-400 day
# "ordinary annual term" window, so the proposed expiration is REFUSED with a
# reason instead of derived - that refusal is one of the checks).
S2_EFF, S2_EXP = _d(-223), _d(-40)


# ── Layout helpers (same conventions as make_c4_test_pdfs.py) ───────────────

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


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
    return y - 0.06 * inch


# ── S1A: the multi-page package policy ──────────────────────────────────────

S1_NAME = "Harbor Point Builders LLC"
S1_ADDR = "1180 Quayside Avenue"
S1_CSZ = "Portsmouth, VA 23704"
S1_FEIN = "84-7301965"
S1_POLICY = "CPP-88421-26"
S1_GL_OCC = "$1,000,000"
S1_VIN = "1FTBF2B60NEE11324"


def s1a(path):
    """STATE (by page, because the checks cite these pages):
      p1  applicant + producer + policy number + term + business START date
          (years-in-business deliberately NOT printed -> it must be DERIVED)
          + the coverage-line schedule (GL + Business Auto granted)
      p2  GL DECLARATIONS: Each Occurrence $1,000,000 (the 5.4/5.5 headline
          value - the COI states it too), aggregate, deductible, gross sales,
          GL class code WITH a location column (the C3 lesson)
      p3  BUSINESS AUTO DECLARATIONS: covered-auto symbols 1/7/7, ONE vehicle
          with VIN, ONE driver with a full MM/DD/YYYY hire date (the C4
          lesson)
      p4  premises + employee count + operations description
    """
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMON POLICY DECLARATIONS", "Commercial Package Policy")
    y = _head(c, y, "PRODUCER")
    y = _row(c, y, "Agency Name", "Quayside Risk Advisors")
    y = _row(c, y, "Agency Phone", "757-555-0100")
    y = _head(c, y, "NAMED INSURED")
    y = _row(c, y, "Named Insured", S1_NAME)
    y = _row(c, y, "Mailing Address", S1_ADDR)
    y = _row(c, y, "City / State / ZIP", S1_CSZ)
    y = _row(c, y, "FEIN", S1_FEIN)
    y = _row(c, y, "Legal Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact Name", "Rowan Ellis")
    y = _row(c, y, "Contact Phone", "757-555-0148")
    y = _row(c, y, "Contact Email", "rowan@harborpointbuilders.example")
    y = _row(c, y, "Business Start Date", "01/15/2010")
    y = _head(c, y, "POLICY INFORMATION")
    y = _row(c, y, "Policy Number", S1_POLICY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Billing Method", "Direct Bill")
    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "STATUS", "ANNUAL PREMIUM"],
               [["Commercial General Liability", "Granted", "$7,850"],
                ["Business Auto", "Granted", "$3,420"]],
               [1.0, 3.9, 5.6])
    y = _row(c, y, "Total Annual Premium", "$11,270")
    c.showPage()

    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              f"Policy {S1_POLICY}")
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Each Occurrence Limit", S1_GL_OCC)
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Deductible", "$2,500")
    y = _head(c, y, "EXPOSURES")
    y = _row(c, y, "Annual Gross Sales", "$2,750,000")
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y,
               ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
               [["Location 1", "91342 - Carpentry - shop only", "Payroll", "$1,180,000"]],
               [1.0, 2.5, 4.9, 6.2])
    c.showPage()

    y = _page(c, "BUSINESS AUTO DECLARATIONS", f"Policy {S1_POLICY}")
    y = _head(c, y, "COVERED AUTO SYMBOLS")
    y = _row(c, y, "Liability", "Symbol 1 (Any Auto)")
    y = _row(c, y, "Physical Damage - Comprehensive", "Symbol 7")
    y = _row(c, y, "Physical Damage - Collision", "Symbol 7")
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y,
               ["YEAR", "MAKE / MODEL", "VIN", "COST NEW"],
               [["2022", "Ford F-250", S1_VIN, "$61,450"]],
               [1.0, 1.7, 3.4, 6.0])
    y = _head(c, y, "SCHEDULE OF DRIVERS")
    y = _table(c, y,
               ["DRIVER NAME", "LICENSE NO.", "DATE OF BIRTH", "DATE HIRED"],
               [["Jordan Avery", "VA D5581144", "04/12/1988", "06/01/2019"]],
               [1.0, 2.6, 4.2, 5.7])
    c.showPage()

    y = _page(c, "PREMISES AND OPERATIONS", f"Policy {S1_POLICY}")
    y = _head(c, y, "PREMISES - LOCATION 1")
    y = _row(c, y, "Location Address", f"{S1_ADDR}, {S1_CSZ}")
    y = _row(c, y, "Occupancy", "Marine carpentry shop and office")
    y = _head(c, y, "OPERATIONS")
    y = _row(c, y, "Description of Operations",
             "Custom marine carpentry and dock fitting")
    y = _row(c, y, "Number of Employees", "24")
    c.showPage()
    c.save()


def s1b(path):
    """The single-page COI. AGREES with S1A on insured, policy number and the
    GL Each Occurrence limit - that agreement is check 5.4 (both sources
    retained). Single page ON PURPOSE: a one-page document gets no page
    markers, and the lineage door must still cite it as page 1 (provably the
    only page while markers are enabled) - the client's own example prints
    "COI.pdf - Page 1"."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only")
    y = _row(c, y, "Producer", "Quayside Risk Advisors")
    y = _row(c, y, "Insured", S1_NAME)
    y = _row(c, y, "Insured Address", f"{S1_ADDR}, {S1_CSZ}")
    y = _row(c, y, "Insurer A", "Chesapeake Mutual Insurance Company")
    y = _row(c, y, "Insurer A NAIC #", "21407")
    y = _head(c, y, "COVERAGES")
    y = _row(c, y, "Commercial General Liability - Policy Number", S1_POLICY)
    y = _row(c, y, "Policy Effective Date", EFF)
    y = _row(c, y, "Policy Expiration Date", EXP)
    y = _row(c, y, "Each Occurrence", S1_GL_OCC)
    y = _row(c, y, "General Aggregate", "$2,000,000")
    c.showPage()
    c.save()


# ── S2: the expired-term renewal ────────────────────────────────────────────

S2_NAME = "Beacon Light Catering LLC"
S2_POLICY = "GLP-55710"


def s2(path):
    """RENEWAL whose printed term has already ENDED, with a SIX-MONTH term.
    STATE : "RENEWAL OF POLICY" wording, the expired term, business start
            date, GL limits, gross sales, class code with location.
    OMIT  : years in business (derived), any statement of the proposed term
            (the routing derives the proposed effective date; the proposed
            expiration is REFUSED because a 183-day term is not an ordinary
            annual term - that refusal is check S2-1)."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              f"RENEWAL OF POLICY {S2_POLICY}")
    y = _row(c, y, "Named Insured", S2_NAME)
    y = _row(c, y, "Mailing Address", "702 Lantern Row")
    y = _row(c, y, "City / State / ZIP", "Norfolk, VA 23510")
    y = _row(c, y, "FEIN", "84-6605521")
    y = _row(c, y, "Legal Entity Type", "Limited Liability Company")
    y = _row(c, y, "Business Start Date", "03/01/2012")
    y = _row(c, y, "Policy Number", S2_POLICY)
    y = _row(c, y, "Policy Effective Date", S2_EFF)
    y = _row(c, y, "Policy Expiration Date", S2_EXP)
    y = _row(c, y, "Producer", "Lantern Insurance Group")
    c.showPage()

    y = _page(c, "GENERAL LIABILITY - LIMITS AND EXPOSURES",
              f"Policy {S2_POLICY}")
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _head(c, y, "EXPOSURES")
    y = _row(c, y, "Annual Gross Sales", "$980,000")
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y,
               ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
               [["Location 1", "16916 - Caterers", "Gross Sales", "$980,000"]],
               [1.0, 2.5, 4.9, 6.2])
    c.showPage()
    c.save()


# ── S3: the umbrella conflict pair ──────────────────────────────────────────

S3_NAME = "Riverbend Logistics Inc"
S3_POLICY = "CUP-30988-26"


def s3a(path):
    """The package: umbrella Each Occurrence $3,000,000 on its own
    declarations page. The COI (s3b) states $1,000,000 for the same coverage -
    a genuine cross-document conflict on a curated Data Consistency field."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMON POLICY DECLARATIONS", "Commercial Package Policy")
    y = _row(c, y, "Named Insured", S3_NAME)
    y = _row(c, y, "Mailing Address", "44 Riverbend Parkway")
    y = _row(c, y, "City / State / ZIP", "Suffolk, VA 23434")
    y = _row(c, y, "FEIN", "84-9917702")
    y = _row(c, y, "Legal Entity Type", "Corporation")
    y = _row(c, y, "Policy Number", S3_POLICY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Producer", "Riverbend Risk Partners")
    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "STATUS", "ANNUAL PREMIUM"],
               [["Commercial General Liability", "Granted", "$6,100"],
                ["Commercial Umbrella", "Granted", "$2,450"]],
               [1.0, 3.9, 5.6])
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y,
               ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
               [["Location 1", "99793 - Warehousing", "Gross Sales", "$4,200,000"]],
               [1.0, 2.5, 4.9, 6.2])
    c.showPage()

    y = _page(c, "COMMERCIAL UMBRELLA DECLARATIONS", f"Policy {S3_POLICY}")
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Umbrella Each Occurrence Limit", "$3,000,000")
    y = _row(c, y, "Umbrella Aggregate Limit", "$3,000,000")
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y,
               ["UNDERLYING COVERAGE", "EACH OCCURRENCE", "AGGREGATE"],
               [["Commercial General Liability", "$1,000,000", "$2,000,000"]],
               [1.0, 3.4, 5.4])
    c.showPage()
    c.save()


def s3b(path):
    """The COI stating the CONFLICTING umbrella limit ($1,000,000 against the
    package's $3,000,000), plus an AGREEING GL limit so the same record shows
    a conflict and a multi-source agreement side by side."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only")
    y = _row(c, y, "Producer", "Riverbend Risk Partners")
    y = _row(c, y, "Insured", S3_NAME)
    y = _row(c, y, "Insured Address", "44 Riverbend Parkway, Suffolk, VA 23434")
    y = _row(c, y, "Insurer A", "Old Dominion Casualty Company")
    y = _row(c, y, "Insurer A NAIC #", "26443")
    y = _head(c, y, "COVERAGES")
    y = _row(c, y, "Commercial General Liability - Each Occurrence", "$1,000,000")
    y = _row(c, y, "Commercial General Liability - General Aggregate", "$2,000,000")
    y = _row(c, y, "Umbrella Liability - Each Occurrence", "$1,000,000")
    y = _row(c, y, "Policy Effective Date", EFF)
    y = _row(c, y, "Policy Expiration Date", EXP)
    c.showPage()
    c.save()


# ── Verify: the fixtures actually print what the checks cite ────────────────

def _verify():
    import pdfplumber

    def _pages(path):
        with pdfplumber.open(path) as pdf:
            return [p.extract_text() or "" for p in pdf.pages]

    p = os.path.join
    errs = []

    s1a_pages = _pages(p(OUT_DIR, "S1A_package_policy.pdf"))
    if len(s1a_pages) != 4:
        errs.append(f"S1A must be 4 pages (page citations need markers), got {len(s1a_pages)}")
    for page_no, needle in [(1, S1_NAME), (1, "01/15/2010"), (1, S1_POLICY),
                            (2, S1_GL_OCC), (2, "$2,750,000"),
                            (3, S1_VIN), (3, "Jordan Avery"),
                            (4, "Number of Employees")]:
        if needle not in s1a_pages[page_no - 1]:
            errs.append(f"S1A page {page_no} missing {needle!r}")
    if "Years in Business" in "\n".join(s1a_pages):
        errs.append("S1A must NOT print 'Years in Business' - it is the derivation check")

    s1b_pages = _pages(p(OUT_DIR, "S1B_certificate_of_insurance.pdf"))
    if len(s1b_pages) != 1:
        errs.append("S1B must be a single page (the no-false-page guard is under test)")
    for needle in (S1_NAME, S1_GL_OCC, S1_POLICY):
        if needle not in s1b_pages[0]:
            errs.append(f"S1B missing {needle!r}")

    s2_pages = _pages(p(OUT_DIR, "S2_renewal_expired_term.pdf"))
    joined = "\n".join(s2_pages)
    if f"RENEWAL OF POLICY {S2_POLICY}" not in joined:
        errs.append("S2 missing the RENEWAL OF POLICY wording")
    if "Years in Business" in joined:
        errs.append("S2 must NOT print 'Years in Business'")
    exp_date = datetime.strptime(S2_EXP, "%m/%d/%Y")
    if exp_date >= TODAY:
        errs.append("S2 term is not expired - regenerate (dates are computed from today)")
    term_days = (exp_date - datetime.strptime(S2_EFF, "%m/%d/%Y")).days
    if 300 <= term_days <= 400:
        errs.append(f"S2 term is {term_days} days - must NOT look annual, or the "
                    "refused-expiration check cannot fire")

    s3a_pages = _pages(p(OUT_DIR, "S3A_umbrella_package.pdf"))
    if "$3,000,000" not in s3a_pages[1]:
        errs.append("S3A page 2 missing the $3,000,000 umbrella limit")
    s3b_pages = _pages(p(OUT_DIR, "S3B_certificate_umbrella.pdf"))
    if "Umbrella Liability - Each Occurrence" not in s3b_pages[0] or \
            "$1,000,000" not in s3b_pages[0]:
        errs.append("S3B missing the conflicting $1,000,000 umbrella limit")

    if errs:
        raise SystemExit("FIXTURE VERIFY FAILED:\n  - " + "\n  - ".join(errs))
    print("verify: all fixtures print what their checks cite")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    s1a(os.path.join(OUT_DIR, "S1A_package_policy.pdf"))
    s1b(os.path.join(OUT_DIR, "S1B_certificate_of_insurance.pdf"))
    s2(os.path.join(OUT_DIR, "S2_renewal_expired_term.pdf"))
    s3a(os.path.join(OUT_DIR, "S3A_umbrella_package.pdf"))
    s3b(os.path.join(OUT_DIR, "S3B_certificate_umbrella.pdf"))
    _verify()
    _write_readme()
    print(f"wrote 5 PDFs + README-HOW-TO-TEST.md to {OUT_DIR}")


def _write_readme():
    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(_README)


_README = f"""# C5 live test - Source Lineage & E&O Audit Record

Generated {TODAY.strftime('%m/%d/%Y')}. Dates inside the PDFs are computed
from the generation date - if you test more than ~30 days later, regenerate:
`py backend/scripts/make_c5_test_pdfs.py`.

## Before you start (do not skip)

1. **Restart the backend.** C5 adds a table (`audit_events`) and columns
   (`answered_at`, `note`) that are created at startup. A backend that has not
   restarted since the change will 500 or silently skip the new sections.
2. Each scenario is its own FRESH submission. Do not reuse a session created
   before the restart.
3. The record under test is the pink **"Audit Record"** button in the download
   sidebar after forms are generated. It downloads a .txt file. You will
   download it several times per scenario - each download reflects the current
   state, so the ORDER of steps matters.
4. Report back per check number: PASS or FAIL. For any FAIL, paste the
   relevant lines of the record (or attach the whole .txt - it has no secrets
   beyond this fixture data).

---

## SCENARIO 1 - lineage, sources, and every action flow

**Upload TOGETHER:** `S1A_package_policy.pdf` + `S1B_certificate_of_insurance.pdf`
**Generate:** ACORD 125 + ACORD 127

### Step A - generate forms, then download the Audit Record (record #1)

| # | Check |
|---|---|
| 1 | SOURCE DOCUMENTS lists BOTH files, each with "Identified as: ..." and an "Uploaded:" timestamp. (Before C5 this section said "(none recorded)" for everyone, always.) |
| 2 | Find the `gl_each_occurrence` row under CAPTURED INPUTS. Its Evidence line must name BOTH files: `S1A_package_policy.pdf - page 2; S1B_certificate_of_insurance.pdf - page 1`. Two things inside that one line: each file cites its PAGE (client 5.5), and both supporting documents are kept, not just the first (client 5.4) - the client's own worked example, verbatim. |
| 3 | The `applicant_name` row's Evidence names both files, page 1 for S1A. |
| 4 | The vehicle schedule row (`auto_vin_schedule`) and driver schedule row show `[1 row(s) captured]` with Evidence `S1A_package_policy.pdf (1 row(s))` - and their Source line does NOT say "unspecified" (client 5.6 - schedules, coverage lines, symbols all used to say exactly that). |
| 5 | The `years_in_business` row shows a value (~16) with `Derived by rule: years_since_business_start_date (inputs: business_start_date)` - the PDF prints only the start date, never the year count (client 5.7). |
| 6 | Search the whole record for the phrase `Source: unspecified`. Expected: none on any row that has a value. |
| 7 | Rows carry a `State:` line (e.g. `VERIFIED (present / source_verified)` on values printed verbatim in the documents). NOT a failure: very short values (under 4 characters, e.g. the employee count "24") never get an Evidence line or text-verification - "24" appears in any document by accident, and a false citation in an E&O record is worse than none. That floor is deliberate. |
| 8 | SCORE HISTORY has exactly ONE snapshot, trigger `form_generated`. |

### Step B - the action flows (same submission, in this order)

| # | Action | Then download the record and check |
|---|---|---|
| 9 | Open the 125 in the editor, edit one field (e.g. change the employee count box from 24 to 30), exit edit mode. | MODIFICATION HISTORY shows that box: `"24" -> "30"`, `Changed by: Entered/edited by producer`, a timestamp, and `[fact: num_employees]`. |
| 10 | On the SQS panel, ANSWER one recommendation card that has an input box (type a value, Submit). | QUESTIONS ANSWERED BY PRODUCER lists it with your value and an `Answered:` timestamp. |
| 11 | DISMISS a different recommendation and TYPE A REASON (e.g. "client confirmed not applicable"). | DISMISSED ITEMS shows the item + your reason. If the score moved, SCORE HISTORY gained a `dismiss_credit` snapshot. |
| 12 | REOPEN the recommendation you answered in #10. | EVENT LOG shows `recommendation_reopened (...; prior action: resolved at <time>)` - the original timestamp survives the reopen (client 5.9 "never destroy the original"). MODIFICATION HISTORY shows the value being retracted (`"..." -> (blank)`). |
| 13 | Send the client questionnaire to your own email, open the client link, answer 2-3 questions (pick ones whose boxes are BLANK), submit. Back as producer, let it apply/recalculate. | CLIENT QUESTIONNAIRE ANSWERS shows respondent name + email + timestamp + each question with its answer (client 5.8). MODIFICATION HISTORY gained rows `Changed by: Answered by client (questionnaire)`. EVENT LOG shows `client_answers_applied (N field(s) changed)`. |
| 14 | Download the ACORD 125 PDF. The pre-download box lists open items - type a note (e.g. "proceeding for test") and click Download Anyway. | DOWNLOADS shows the download with `Score at download`, a `File checksum`, and `Open items at download (N):` followed by the ACTUAL LIST (client 5.13 - it used to keep only the count). DOWNLOADED WITH OPEN ITEMS shows your note + the count. SCORE HISTORY gained a `package_downloaded` snapshot. |

---

## SCENARIO 2 - derived values and refusals (the client's own 5.7 example)

**Upload:** `S2_renewal_expired_term.pdf` alone
**Generate:** ACORD 125
**Then download the Audit Record.**

| # | Check |
|---|---|
| 1 | VALUES SEEN AND REFUSED contains `expiration_date` with the reason `this is a renewal and the expiring term was found, but the proposed term length is not stated anywhere`. (The PDF's term is 6 months, so the system refuses to guess a renewal term - "what remained unresolved" is now on the record.) |
| 2 | The `effective_date` row's VALUE is the old EXPIRATION date ({S2_EXP}) and it carries `Derived by rule: renewal_routing_prior_expiration (inputs: prior_expiration_date, is_renewal)`. This is the client's own worked example from 5.7, verbatim. |
| 3 | `prior_effective_date` ({S2_EFF}) and `prior_expiration_date` ({S2_EXP}) rows exist with Evidence citing `S2_renewal_expired_term.pdf - page 1`. |
| 4 | `years_in_business` (~14) again shows its derivation rule. |
| 5 | The "confirm the renewal term" warning is an open item; download the form with it open and confirm the DOWNLOADS entry lists it (same shape as Scenario 1 #14). |

---

## SCENARIO 3 - conflict resolution history

**Upload TOGETHER:** `S3A_umbrella_package.pdf` + `S3B_certificate_umbrella.pdf`
**Generate:** ACORD 125 + ACORD 131

| # | Step + check |
|---|---|
| 1 | BEFORE resolving anything, download the Audit Record. The `umbrella_limit` row's State line must read `(conflicting / ...)` - the package says $3,000,000, the certificate says $1,000,000, and the record says so instead of pretending the value is settled. |
| 2 | Open Data Consistency. The umbrella limit shows BOTH candidate values with their source files. Pick **$3,000,000** and confirm. |
| 3 | Download the record again. DATA CONSISTENCY RESOLUTIONS now shows: `Chosen: $3,000,000 (was: ...)`, `Competing values:` listing BOTH figures each tagged with its file name, the conflict reason, and a `Resolved:` timestamp (client 5.10 - all competing values + sources + choice + who + when). |
| 4 | The `umbrella_limit` row now reads `Source: Confirmed by producer (Data Consistency)`. |
| 5 | The GL Each Occurrence row shows BOTH files in Evidence (they agree at $1,000,000) - a conflict and a multi-source agreement living correctly side by side in one record. |

---

## What cannot be tested live today (already covered by unit tests)

- The nightly retention jobs (6-month ruling): they run at 03:00-04:00 UTC and
  act on data older than 180 days. Pinned by tests instead.
- Snapshot de-duplication ("no snapshot on an invisible recalculation") is
  asserted by unit test; live you should simply NOT see duplicate SCORE
  HISTORY rows with identical numbers back to back.

## What to send back

For each scenario: the check numbers with PASS/FAIL, plus the downloaded
`Primble_Audit_Record_*.txt` files for anything that failed (and for Scenario
1 step A regardless - I want to eyeball the Evidence lines from a real run).
"""


if __name__ == "__main__":
    main()
