"""make_sys01_test_pdfs.py - live kit for SYS-01 (Critical tagging).

    py backend/scripts/make_sys01_test_pdfs.py

Writes to sys01_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

WHAT SYS-01 CHANGED. `priority` used to be a STATIC tier label: Critical meant
"this fact is in SQS Tier 1", and it never read the submission. A package whose
Tier 1 was complete therefore reported "0 Critical" and told the producer *"All
critical fields were already answered from your uploaded documents"* while the
pre-form card on the SAME session printed *"Key details missing: FEIN / Tax ID,
Annual revenue, Number of employees, NAICS or SIC industry code"*. Critical now
means "required AND still missing", read from the same Tier 1 + Tier 2 entries
the pre-form card prints.

TWO sessions, ONE file each. They are a MATCHED PAIR and both must be run - the
first proves the flag fires, the second proves it does not fire on a fact the
documents already answer, which is the half a careless fix breaks.

  PACKAGE A   A1_dec_page_core_gaps.pdf          -> expect 5 Critical
              A GL declarations page carrying a COMPLETE Tier 1 (named insured,
              mailing address, entity type, policy period, line of business,
              named contact with phone and email) and a real operations
              description and years in business - so the pre-form card reads
              "Key details in place" for those. It deliberately prints NO FEIN,
              NO revenue, NO employee count and NO industry code.
              This is the client's reported shape: under the OLD code every
              Tier 1 item was satisfied, so the modal showed 0 Critical.

  PACKAGE B   B1_dec_page_core_satisfied.pdf     -> expect 0 Critical
              The SAME account with the four gaps closed - and the industry
              code given as a SIC ONLY, never a NAICS. That is the control
              that matters: the score credits "NAICS or SIC" as ONE
              interchangeable requirement, so a per-key rule would raise a
              false Critical asking for the NAICS of a business that has
              already stated its classification. It must stay silent.

BOTH PACKAGES ARE SINGLE-DOCUMENT AND GL-ONLY ON PURPOSE. SYS-01 is about the
questionnaire's priority rule, not about extraction, coverage detection or
cross-document conflict. Every extra document or line of business adds
questions that have nothing to do with what is being tested and makes the
Critical count harder to read on screen.

VERIFIED OFFLINE BEFORE THIS KIT WAS WRITTEN, by driving the real
`arq_service.generate_arq_questions_from_facts` with the facts these documents
state (not a fixture of my own design):

    PACKAGE A -> 24 questions, 5 Critical
                 fein / total_revenue / num_employees  -> critical, CLIENT
                 naics_code / sic_code                 -> critical, AGENCY
    PACKAGE B -> 20 questions, 0 Critical
                 naics_code -> internal/agency (the stated SIC satisfies it)

A live run that disagrees with those two lines is a real finding - report it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.pagesizes import LETTER            # noqa: E402
from reportlab.lib.units import inch                  # noqa: E402
from reportlab.pdfgen import canvas                   # noqa: E402

OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sys01_test_data",
)

INSURED = "HARBOR RIDGE ROOFING LLC"
ADDRESS = "2210 Larimer Street, Suite 400, Denver, CO 80205"
EFF, EXP = "11/01/2026", "11/01/2027"
CARRIER, NAIC, POLICY = "Summit Mutual Insurance Company", "24988", "GL-8841776"
OPS = ("Residential and commercial roofing installation, repair and "
       "replacement. No hot tar or torch-down work is performed.")


def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=3.4):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, "%s:" % label)
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


def _wrap(text, width):
    """Word-aware wrap. A character slice split "No hot tar" as "No ho / t tar",
    which corrupts the very operations_description this kit puts under test -
    found by reading the generated PDF back rather than trusting the writer."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _common_identity(c, y):
    """Tier 1, complete. Identical in both packages so the ONLY difference
    between the two sessions is the Tier 2 block."""
    y = _head(c, y, "NAMED INSURED")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", ADDRESS)
    y = _row(c, y, "Legal Entity Type", "Limited Liability Company (LLC)")
    y = _head(c, y, "POLICY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Carrier NAIC", NAIC)
    y = _row(c, y, "Policy Number", POLICY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Line of Business", "Commercial General Liability")
    y = _head(c, y, "CONTACT")
    y = _row(c, y, "Contact Name", "Dana Whitfield, Operations Manager")
    y = _row(c, y, "Contact Phone", "303-555-0142")
    y = _row(c, y, "Contact Email", "dana@harborridgeroofing.com")
    return y


def _common_tail(c, y):
    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    for line in _wrap(OPS, 78):
        y = _para(c, y, line)
    y = _row(c, y, "Years in Business", "14 (continuously since 2012)")
    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000", lw=4.3)
    y = _row(c, y, "Deductible", "$1,000 per occurrence")
    y = _row(c, y, "Annual Premium", "$18,450")
    return y


def package_a():
    """Tier 1 complete, four Tier 2 gaps. The client's reported shape."""
    path = os.path.join(OUT, "A1_dec_page_core_gaps.pdf")
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Summit Mutual Insurance Company - Renewal Declarations")
    y = _common_identity(c, y)
    y = _common_tail(c, y)
    # NO "note" narrating the absence. A real declarations page does not announce
    # what it omits, and a sentence naming all four missing facts is precisely the
    # shape that invites the extractor to write "not stated" into them - which
    # would make the gap disappear for the wrong reason. The absence here is
    # genuine: the four facts simply are not printed.
    c.save()
    return path


def package_b():
    """The same account with the four gaps closed - industry code as SIC ONLY."""
    path = os.path.join(OUT, "B1_dec_page_core_satisfied.pdf")
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Summit Mutual Insurance Company - Renewal Declarations")
    y = _common_identity(c, y)
    y = _head(c, y, "BUSINESS INFORMATION")
    y = _row(c, y, "Federal Employer ID Number (FEIN)", "84-2210987", lw=4.3)
    y = _row(c, y, "Annual Gross Revenue", "$4,200,000")
    y = _row(c, y, "Total Employees", "26 full-time")
    y = _row(c, y, "SIC Code", "1761 - Roofing, Siding and Sheet Metal Work")
    y = _common_tail(c, y)
    c.save()
    return path


def package_c():
    """The OLD half. Packages A and B both carry a COMPLETE Tier 1, so neither
    proves that a Tier 1 fact still goes Critical when it is genuinely missing -
    which is the owner's *"keep list 1 as it is and add more to it"* condition.
    This is a broker's account summary: it names the insured, the line wanted,
    the operations and the years in business, and carries NO mailing address, NO
    entity type, NO policy dates and NO named contact.

    Verified offline: 31 questions, 11 Critical - 6 OLD Tier 1 (mailing address,
    entity type, effective date, contact name / phone / email) and 5 NEW Tier 2
    (FEIN, revenue, employee count, NAICS, SIC)."""
    path = os.path.join(OUT, "C1_submission_summary_thin.pdf")
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "NEW BUSINESS SUBMISSION SUMMARY",
              "Prepared for market - General Liability")
    y = _head(c, y, "ACCOUNT")
    y = _row(c, y, "Account Name", INSURED)
    y = _row(c, y, "Coverage Requested", "Commercial General Liability")
    y = _row(c, y, "Years in Business", "14 (continuously since 2012)")
    y = _head(c, y, "OPERATIONS")
    for line in _wrap(OPS, 78):
        y = _para(c, y, line)
    y = _head(c, y, "LIMITS SOUGHT")
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _head(c, y, "TARGET MARKETS")
    y = _para(c, y, "Summit Mutual, Cascade Specialty, Front Range Underwriters.")
    # Deliberately absent: mailing address, legal entity type, policy period,
    # named contact. A broker's first-pass summary routinely omits all four, and
    # they are exactly the OLD Tier 1 items that must still raise a Critical.
    c.save()
    return path


def readme():
    return """# SYS-01 live test - Critical tagging in the client questionnaire

Generated by `backend/scripts/make_sys01_test_pdfs.py`.

## What is being tested

Before SYS-01, a question was tagged **Critical** only if its fact was in SQS
**Tier 1**. Tier 2 facts - FEIN, annual revenue, employee count, years in
business, operations description, NAICS/SIC - could never be Critical, however
absent. On the client's live run every Tier 1 fact was present, so the
Send-to-Client modal reported **0 Critical** and printed *"All critical fields
were already answered from your uploaded documents"*, while the pre-form Review
card on the same session listed four missing key details.

Critical now means **"required AND still missing"**, read from the same Tier 1 +
Tier 2 checklist the Review card prints.

## Run these THREE sessions. All are needed.

Each one proves something the others cannot:

| | Proves |
|---|---|
| **A** | the NEW Tier 2 facts fire as Critical when missing - the client's reported case |
| **B** | a SATISFIED fact does NOT fire, including the NAICS-or-SIC pair - the half a careless fix breaks |
| **C** | the OLD Tier 1 facts still fire - nothing was lost |

A and B both carry a complete Tier 1, so **neither proves the old behaviour
survived**. That is what C is for.

### FORMS TO GENERATE: `ACORD 125` and `ACORD 126`. Nothing else.

That is the minimum that carries all five facts under test, verified against the
real schemas: ACORD 125 holds FEIN, NAICS and SIC; ACORD 126 holds the employee
count. Revenue is asked by a curated question on either. Adding more forms only
adds unrelated questions and makes the Critical count harder to read.

---

## PACKAGE A - `A1_dec_page_core_gaps.pdf`

Upload the ONE file. Select **ACORD 125 + ACORD 126**.

### 1. Pre-form Review screen - the baseline

**Key details in place** must include: Applicant legal name, Applicant mailing
address, Business entity type, Proposed effective date, Lines of business
requested, Contact information, Operations description, Years in business.

**Key details missing** must be exactly: **FEIN / Tax ID**, **Annual revenue**,
**Number of employees**, **NAICS or SIC industry code**.

If this list is wrong, stop - the problem is extraction, not SYS-01.

### 2. Send to Client modal - THE TEST

Open "Send to Client".

| Check | Expected | Was (before the fix) |
|---|---|---|
| The metric chip | **`5 Critical (2 agency)`** | `0 Critical` |
| FEIN / Tax ID card | badge **Critical**, pre-ticked | Important + Suggested |
| Annual revenue - rating basis | badge **Critical**, pre-ticked | Important + Suggested |
| Employee count | badge **Critical**, pre-ticked | Important + Suggested |
| The banner | must NOT say "All critical fields were already answered" | said exactly that |

### 3. The Agency panel - the owner's ruling

Expand **Agency**. The NAICS and SIC questions must:

- carry a red **Critical** badge (the chip is normally hidden in this panel;
  Critical is the exception);
- sort to the **top** of the panel;
- be **UNTICKED**. This is the important one. NAICS/SIC stay the producer's
  (client instruction, 2026-08-12: *"those come from the producer or
  underwriter"* - a classification code drives rate, so an insured guessing is
  worse than a blank). They are flagged for the broker and must never be
  auto-sent to the insured.

### 4. Send it (optional, but it proves step 3)

Send to yourself. The client questionnaire must contain the FEIN, revenue and
employee-count questions and must **not** contain NAICS or SIC.

---

## PACKAGE B - `B1_dec_page_core_satisfied.pdf`

**Start a NEW session.** Upload the ONE file. Select **ACORD 125 + ACORD 126**.

Same account, four gaps closed, and the industry code stated as a **SIC only**.

### 1. Pre-form Review screen

**Key details missing** must be **empty**, or contain only "Producer / Agency
name". `NAICS or SIC industry code` must appear under **in place** - the SIC
satisfies the requirement on its own.

### 2. Send to Client modal - THE CONTROL

| Check | Expected |
|---|---|
| The metric chip | **`0 Critical`** |
| The banner | *"All required details are already answered from your uploaded documents."* |
| A NAICS question | may still be listed in the Agency panel, but must **NOT** be badged Critical |

**Why this is the half that matters.** The score treats "NAICS or SIC" as ONE
interchangeable requirement. If the questionnaire checked the two keys
separately it would raise a Critical demanding the NAICS of a business that has
already stated its classification - a brand new false alarm, on exactly the kind
of ordinary data nobody thinks to test. Zero Criticals here is the proof it
does not.

---

## PACKAGE C - `C1_submission_summary_thin.pdf`  -> expect 11 Critical

**Start a NEW session.** Upload the ONE file. Select **ACORD 125 + ACORD 126**.

### Why this package exists

Packages A and B both carry a **complete Tier 1**, so neither one proves that an
OLD Critical still fires - there was nothing missing for it to fire on. This is
the other half of the owner's condition: *"keep list 1 as it is for critical and
add more to it."*

A broker's first-pass account summary: it names the insured, the line wanted, the
operations and the years in business, and carries **no mailing address, no legal
entity type, no policy dates and no named contact**.

### Expected: `11 Critical (3 agency)`

**OLD - Tier 1, Critical before this change and still Critical now:**

| Question | Bucket |
|---|---|
| Mailing address | client |
| Business entity type | client |
| Contact name | client |
| Contact phone | client |
| Contact email | client |
| Policy effective date | **agency** - client 9.1, *"client does not need to interpret policy period"* |

**NEW - Tier 2, Critical only since SYS-01:**

| Question | Bucket |
|---|---|
| FEIN / Tax ID | client |
| Annual revenue | client |
| Employee count | client |
| NAICS classification code | agency |
| SIC classification code | agency |

**Not asked at all** (the document states them): applicant name, lines of
business, years in business, operations description.

### One acceptable variance

`HARBOR RIDGE ROOFING **LLC**` carries its entity suffix, as every real company
name does. If extraction infers `entity_type` from it, that question disappears
and you get **10 Critical, not 11**. That is a pass. The suffix is left in
deliberately - stripping it would make the fixture easier than reality, which is
the trap this repo keeps recording. The other five old Tier 1 items are
unambiguous and must all appear.

---

## What a failure looks like

| Symptom | Meaning |
|---|---|
| A: chip still reads `0 Critical` | the promotion did not run - check the backend log for `core-critical promotion skipped` |
| A: chip reads `3 Critical` with nothing in Agency | the frontend is counting the client bucket only |
| A: NAICS/SIC pre-ticked for the client | the owner's Agency ruling has been broken - stop and report |
| B: chip reads `1 Critical` for NAICS | the NAICS-or-SIC pair is being checked per key |
| B: any Critical at all | a satisfied fact is being flagged - the second acceptance clause is broken |
| C: fewer than 10 Critical | an OLD Tier 1 Critical was lost - the change stopped being additive. Name which one is missing. |
| C: mailing address / contact NOT Critical | the regression that matters most - report immediately |
| A: `NAICS or SIC` shows as **in place** | the carrier's NAIC number (24988) is being read as the business's NAICS code. That is a REAL defect but it is an EXTRACTION one, not SYS-01 - report it separately. Both packages print `Carrier NAIC` because every real declarations page does; removing it would make the kit easier than reality. |

## Known and expected, NOT a failure

- **A dec page never prints the producing agency's name**, so "Producer / Agency
  name" stays under *missing* on both packages. It is deliberately excluded from
  Critical (it is the agency's own name, not a question for anybody).
- **NAICS/SIC will be Critical on nearly every real submission**, because a
  declarations page essentially never prints an industry code. That is correct
  behaviour, not noise - but it does mean the Critical count will rarely be 0 on
  live data.
- Both packages are GL-only single documents, so the total question count is
  small (about 20-24). That is the point.
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    made = [package_a(), package_b(), package_c()]
    rp = os.path.join(OUT, "README-HOW-TO-TEST.md")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(readme())
    made.append(rp)
    for p in made:
        print("wrote", os.path.relpath(p, os.path.dirname(OUT)))


if __name__ == "__main__":
    main()
