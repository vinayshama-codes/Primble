"""make_c9_test_pdfs.py - live test packages for V1 item H4 (Core Submission
Information Coverage, client master-plan section 9).

    py backend/scripts/make_c9_test_pdfs.py

Writes to test_data_c9/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks and exactly what to send back.

THREE PACKAGES, FOUR FILES. Deliberately few - the owner runs these by hand.

    P1  Established LLC          2 files, uploaded TOGETHER as one submission
    P2  New-venture sole prop    1 file
    P3  Non-profit, all stated   1 file   <- the GUARD RAIL package

WHY P3 EXISTS, AND WHY IT MATTERS MOST
--------------------------------------
P1 and P2 prove the new behaviour fires. P3 proves it stays SILENT on an
ordinary, complete submission. This codebase has shipped four rules that fired
on the normal case (the phantom auto-symbol warnings, the split-limit hard stop,
the deductible-basis warning, the payroll-period gate), and H4 itself shipped a
fifth in its first cut - the WC payroll period came back Not Applicable on every
package while the -3 was still charged. A kit without a negative control cannot
tell "working" from "firing on everything".

THE DESIGN RULE (inherited from make_c4_test_pdfs.py, learned the hard way)
--------------------------------------------------------------------------
    A scenario can only test the ROUTING of a value it does NOT state.

If a package PRINTS the value whose routing is under test, extraction finds it,
`_fact_is_filled` marks it already-provided, and no question is ever generated -
the scenario produces zero evidence and looks like a pass. So each file below
splits its content deliberately:

    STATE   what makes the coverage and the exposure exist, so the form is
            selected and the question is generated at all;
    OMIT    the exact values under test, so they surface as questions.

`_verify()` at the bottom FAILS THE BUILD if an omitted term reappears, and also
asserts the POSITIVE requirements (P1's two entity spellings, P1's period-less
payroll, P3's annual label). That check is the only thing standing between this
file and a repeat of the C4-J defect.

Other rules, all inherited and all proven:
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave
  (the 2026-08-22 fixture defect).
* Dates computed from TODAY, so no package drifts into an expired-term or
  renewal path it was not designed to exercise.
* Every package prints a GL class code WITH a location column, because the
  extraction contract for `gl_class_codes_by_location` is
  ``[{"location": string, "codes": [string]}]`` - without it Exposure
  Consistency deducts 20 for a pure fixture artefact, which then buries whatever
  the package was actually testing (the C3 lesson).
"""

import os
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_data_c9",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=30)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=30 + 365)).strftime("%m/%d/%Y")
PRIOR_EFF = (TODAY - timedelta(days=335)).strftime("%m/%d/%Y")


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


def _row(c, y, label, value, lw=3.1):
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


def _lines(c, y, rows):
    y = _head(c, y, "SCHEDULE OF COVERAGES")
    return _table(c, y, ["COVERAGE LINE", "STATUS", "ANNUAL PREMIUM"], rows,
                  [1.0, 3.9, 5.6])


def _gl_class(c, y, code, desc, basis, exposure, location="Location 1"):
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    return _table(
        c, y,
        ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
        [[location, f"{code} - {desc}", basis, exposure]],
        [1.0, 2.5, 4.9, 6.2],
    )


# ── P1 - Established LLC (2 files, ONE submission) ──────────────────────────
#
# STATE : applicant identity, mailing address, effective date, coverage lines
#         (GL + Workers Comp granted, with premiums so `coverage_lines` really
#         grants them), operations, revenue, employees, GL class + location,
#         CONTACT PHONE ONLY, and a WC payroll figure with NO period word.
# OMIT  : expiration date, GL form type (occurrence / claims-made), prior
#         carrier, FEIN, years in business, contact NAME, contact EMAIL, audit
#         period, billing plan, experience modification.
#
# The two files print the SAME entity type in the two spellings ACORD itself
# uses - "Limited Liability Corporation" (the checkbox label on ACORD 125) and
# "LLC". Before H4 those two raised a Data Consistency conflict against each
# other, because the full phrase was not a synonym key so "limited" collapsed to
# "ltd" and "corporation" to "corp".

_P1_NAME = "Copperline Mechanical Contractors LLC"
_P1_ADDR = "1450 Lantern Court"
_P1_CSZ = "Denver, CO 80202"


def p1a(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability and Workers Compensation - new business submission")
    y = _head(c, y, "PRODUCER")
    y = _row(c, y, "Agency Name", "Lantern Row Insurance Services")
    y = _row(c, y, "Agency Phone", "303-555-0100")

    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Named Insured", _P1_NAME)
    y = _row(c, y, "Mailing Address", _P1_ADDR)
    y = _row(c, y, "City / State / ZIP", _P1_CSZ)
    y = _row(c, y, "Legal Entity Type", "Limited Liability Corporation")
    # CONTACT PHONE ONLY. Name and email are omitted on purpose - Tier 1 counts
    # the three as ONE requirement ("any one contact method satisfies Tier 1"),
    # and the questionnaire used to ask all three as CRITICAL anyway.
    y = _row(c, y, "Primary Phone", "303-555-0148")

    y = _head(c, y, "BUSINESS OPERATIONS")
    y = _row(c, y, "Description of Operations",
             "Commercial mechanical contractor installing and servicing HVAC systems.")
    y = _row(c, y, "Annual Gross Sales", "$4,200,000")
    y = _row(c, y, "Number of Employees", "26")

    y = _head(c, y, "PROPOSED POLICY PERIOD")
    y = _row(c, y, "Proposed Effective Date", EFF)
    # NO expiration date. NO audit period. NO billing plan.

    y = _lines(c, y, [
        ["Commercial General Liability", "Covered", "$18,400"],
        ["Workers Compensation", "Covered", "$41,900"],
    ])
    # PREMIUM BASIS IS GROSS SALES, AND THAT IS LOAD-BEARING - do not "correct"
    # it back to Payroll because an HVAC contractor is usually payroll-rated.
    # FIXTURE DEFECT FOUND ON THE FIRST LIVE RUN (2026-08-27): this schedule
    # originally read "PREMIUM BASIS: Payroll / EXPOSURE: $1,240,000", and
    # `coverage_evidence._payroll_source_is_annual` accepts a class-code
    # schedule whose basis is payroll or remuneration as evidence that the
    # package's payroll figure is ANNUAL (a rating schedule states annual
    # remuneration by definition). So the WC payroll period resolved to
    # SATISFIED, the -3 was not charged, the producer question was not asked,
    # and check 4 - the whole reason P1 exists - silently tested nothing.
    # Measured: basis "Payroll" -> satisfied; basis "Gross Sales" -> missing.
    # This is the C4-J lesson exactly: a scenario cannot test a value it
    # states, and here the package stated it OBLIQUELY, through a different
    # coverage line's rating basis. `_verify` now checks the structural
    # condition (see _payroll_mentions) rather than just banning the words.
    y = _gl_class(c, y, "91580", "Heating and Air Conditioning Systems",
                  "Gross Sales", "$4,200,000")

    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _row(c, y, "General Liability Limit", "$1,000,000 / $2,000,000")
    # NOTE: deliberately NOT printed as "each occurrence" - the word would let
    # `gl_form_type` extract, and this package exists to prove that question is
    # ROUTED to the producer rather than to answer it.

    y = _head(c, y, "WORKERS COMPENSATION")
    # A BARE payroll figure. No "annual", no "per year", no class-code schedule
    # with remuneration - so nothing in this document states the PERIOD, which
    # is the one branch where the client's 6.4 -3 is charged and the producer
    # must therefore still be asked.
    y = _row(c, y, "Payroll", "$1,240,000")
    y = _row(c, y, "States of Operation", "CO")
    c.save()


def p1b(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "DECLARATIONS PAGE",
              "Expiring program - carrier declarations for the named insured")
    y = _head(c, y, "NAMED INSURED")
    y = _row(c, y, "Named Insured", _P1_NAME)
    y = _row(c, y, "Mailing Address", f"{_P1_ADDR}, {_P1_CSZ}")
    # THE SAME ENTITY, THE OTHER SPELLING. This is the whole point of file B.
    y = _row(c, y, "Legal Entity", "LLC")

    y = _head(c, y, "POLICY PERIOD")
    y = _row(c, y, "Policy Effective", PRIOR_EFF)

    y = _lines(c, y, [
        ["Commercial General Liability", "Covered", "$17,850"],
        ["Workers Compensation", "Covered", "$39,100"],
    ])
    # Gross Sales, for the reason spelled out in p1a - a payroll rating basis
    # anywhere in the package satisfies the WC period check and disarms check 4.
    y = _gl_class(c, y, "91580", "Heating and Air Conditioning Systems",
                  "Gross Sales", "$4,050,000")
    y = _para(c, y, "Coverage is written on the standard commercial package program.")
    c.save()


# ── P2 - New-venture sole proprietor (1 file) ───────────────────────────────
#
# STATE : applicant identity, address, effective date, GL line, operations,
#         revenue, employee count of ZERO, GL class + location, all three
#         contact methods (so P2 does NOT re-test the contact rule).
# OMIT  : years in business, prior carrier, expiration date, FEIN, any claim
#         count, any loss history.
#
# The entity is a SOLE PROPRIETORSHIP, which before H4 ticked NO box at all on
# ACORD 125 - the form's box is "Individual", and nine independent substring
# rules had no way to know that.

def p2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability - newly formed business, first insurance purchase")
    y = _head(c, y, "PRODUCER")
    y = _row(c, y, "Agency Name", "Lantern Row Insurance Services")
    y = _row(c, y, "Agency Phone", "303-555-0100")

    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Named Insured", "Marisol Vega Landscape Design")
    y = _row(c, y, "Mailing Address", "88 Cottonwood Lane")
    y = _row(c, y, "City / State / ZIP", "Boulder, CO 80301")
    y = _row(c, y, "Legal Entity Type", "Sole Proprietorship")
    y = _row(c, y, "Contact Name", "Marisol Vega")
    y = _row(c, y, "Primary Phone", "303-555-0177")
    y = _row(c, y, "Contact Email", "marisol@example.com")

    y = _head(c, y, "BUSINESS OPERATIONS")
    y = _row(c, y, "Description of Operations",
             "Residential landscape design and installation. Owner-operated.")
    y = _row(c, y, "Annual Gross Sales", "$180,000")
    # ZERO is a VALUE, not a gap - the client's own key rule for this row.
    y = _row(c, y, "Number of Employees", "0")

    y = _head(c, y, "PROPOSED POLICY PERIOD")
    y = _row(c, y, "Proposed Effective Date", EFF)

    y = _lines(c, y, [["Commercial General Liability", "Covered", "$2,150"]])
    y = _gl_class(c, y, "97047", "Landscape Gardening", "Gross Sales", "$180,000")

    y = _head(c, y, "REMARKS")
    y = _para(c, y, "The business was formed this year and has not previously")
    y = _para(c, y, "carried commercial insurance of any kind.")
    c.save()


# ── P3 - Non-profit, everything stated: THE GUARD RAIL (1 file) ─────────────
#
# STATE : EVERYTHING the other two omit - expiration date, GL form type,
#         all three contacts, FEIN, years in business, prior carrier, audit
#         period, billing plan - plus a WC payroll figure whose own label says
#         ANNUAL, and a WC class-code schedule stating annual remuneration.
# OMIT  : nothing.
#
# So every H4 rule must be SILENT here. If any of them speaks on this package,
# it fires on the ordinary case and the fix is worse than the defect.
#
# The entity is a NON-PROFIT CORPORATION, which before H4 ticked the plain
# Corporation box - the wrong one of two mutually exclusive checkboxes.

def p3(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability and Workers Compensation - renewal submission")
    y = _head(c, y, "PRODUCER")
    y = _row(c, y, "Agency Name", "Lantern Row Insurance Services")
    y = _row(c, y, "Agency Phone", "303-555-0100")

    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Named Insured", "Front Range Youth Services")
    y = _row(c, y, "Mailing Address", "2200 Sherman Street")
    y = _row(c, y, "City / State / ZIP", "Denver, CO 80203")
    y = _row(c, y, "FEIN", "84-2210987")
    y = _row(c, y, "Legal Entity Type", "Non-Profit Corporation")
    y = _row(c, y, "Contact Name", "Priya Raman")
    y = _row(c, y, "Primary Phone", "303-555-0192")
    y = _row(c, y, "Contact Email", "priya@example.com")

    y = _head(c, y, "BUSINESS OPERATIONS")
    y = _row(c, y, "Description of Operations",
             "After-school tutoring and youth mentoring programs at two centers.")
    y = _row(c, y, "Annual Gross Sales", "$1,900,000")
    y = _row(c, y, "Number of Employees", "34")
    y = _row(c, y, "Years in Business", "12")

    y = _head(c, y, "POLICY PERIOD AND TERMS")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Audit Period", "Annual")
    y = _row(c, y, "Billing Plan", "Agency Bill")
    y = _row(c, y, "Prior Carrier", "Sentinel Mutual Insurance Company")

    y = _lines(c, y, [
        ["Commercial General Liability", "Covered", "$9,400"],
        ["Workers Compensation", "Covered", "$21,300"],
    ])
    y = _gl_class(c, y, "41668", "Youth Services Organization", "Gross Sales",
                  "$1,900,000")

    y = _head(c, y, "GENERAL LIABILITY")
    y = _row(c, y, "Coverage Form Basis", "Occurrence")
    y = _row(c, y, "General Liability Limit", "$1,000,000 / $2,000,000")

    y = _head(c, y, "WORKERS COMPENSATION")
    # The label itself states the period - D43's "by MEANING, not one spelling".
    y = _row(c, y, "Estimated Annual Payroll", "$1,420,000")
    y = _row(c, y, "Experience Modification", "0.94")
    y = _table(
        c, y,
        ["CLASS CODE", "CLASSIFICATION", "STATE", "ANNUAL REMUNERATION"],
        [["8868", "College - Professional Employees", "CO", "$980,000"],
         ["8810", "Clerical Office Employees", "CO", "$440,000"]],
        [1.0, 2.3, 5.0, 5.9],
    )
    c.save()


# ── Self-verification ───────────────────────────────────────────────────────

_OMIT_TERMS = (
    "expiration", "claims-made", "claims made", "occurrence", "prior carrier",
    "fein", "years in business", "audit period", "billing plan",
    "experience modification",
)

_FORBIDDEN = {
    # P1's two files test ROUTING, so neither may state the routed values.
    "P1A_application_llc_values_omitted.pdf": _OMIT_TERMS + (
        "contact name", "contact email", "annual payroll", "per year",
        "annual remuneration",
    ),
    "P1B_dec_page_llc_spelling_variant.pdf": _OMIT_TERMS + (
        "annual payroll", "annual remuneration",
    ),
    # P2 tests the New Venture derivation, so it must not state a years figure
    # or any prior-coverage evidence that would CONTRADICT the confirmation.
    "P2_new_venture_sole_proprietor.pdf": (
        "years in business", "prior carrier", "expiration", "loss run",
        "claims", "renewal",
    ),
}

# What each file MUST say, or it cannot test what it exists for.
_REQUIRED = {
    "P1A_application_llc_values_omitted.pdf": [
        ("limited liability corporation", "P1A must print ACORD's own LLC spelling"),
        ("payroll", "P1A needs a payroll figure for the 6.4 period check to apply"),
        ("primary phone", "P1A must supply exactly one contact method"),
        ("workers compensation", "the WC line must be granted"),
    ],
    "P1B_dec_page_llc_spelling_variant.pdf": [
        ("llc", "P1B must print the OTHER spelling of the same entity"),
        ("copperline mechanical contractors", "both files must name the same insured"),
    ],
    "P2_new_venture_sole_proprietor.pdf": [
        ("sole proprietorship", "P2 exists to prove the Individual box is ticked"),
        ("number of employees: 0", "P2 must state a ZERO employee count"),
        ("not previously", "P2 must read as a first insurance purchase"),
    ],
    "P3_nonprofit_everything_stated.pdf": [
        ("non-profit corporation", "P3 exists to prove ONE box is ticked, the right one"),
        ("estimated annual payroll", "P3's payroll label must state the period"),
        ("annual remuneration", "P3's class schedule must state annual remuneration"),
        ("proposed expiration date", "P3 must state everything P1 omits"),
        ("prior carrier", "P3 must state everything P1 omits"),
        ("occurrence", "P3 must state the GL form basis"),
    ],
}


def _text_of(path) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _verify(paths):
    problems = []
    by_name = {os.path.basename(p): p for p in paths}
    texts = {n: _text_of(p).lower() for n, p in by_name.items()}

    for name, banned in _FORBIDDEN.items():
        text = texts.get(name)
        if text is None:
            problems.append(f"{name}: not generated")
            continue
        if not text:
            problems.append(f"{name}: could not read text back (pdfplumber missing?)")
            continue
        for word in banned:
            if word in text:
                problems.append(
                    f"{name}: states '{word}', so its question will be suppressed "
                    f"as already-provided and the package cannot test its routing")

    for name, needs in _REQUIRED.items():
        text = texts.get(name) or ""
        for word, why in needs:
            if word not in text:
                problems.append(f"{name}: missing '{word}' - {why}")

    # P1 is only an entity-normalisation test if the two spellings really differ.
    a, b = texts.get("P1A_application_llc_values_omitted.pdf", ""), \
        texts.get("P1B_dec_page_llc_spelling_variant.pdf", "")
    if "limited liability corporation" in b:
        problems.append("P1B must print the SHORT spelling only, or there is no variant")
    if "copperline mechanical contractors" not in a:
        problems.append("P1A must name the same insured as P1B")

    # ── THE STRUCTURAL CHECK, not a word ban (added after the first live run) ─
    # P1 exists to charge the WC payroll-period -3 and ask the producer for the
    # period. That branch is reachable ONLY when nothing in the package states
    # the period - and `coverage_evidence._payroll_source_is_annual` reads a
    # payroll/remuneration PREMIUM BASIS on ANY class-code schedule as stating
    # it, including a General Liability one. The first version of these files
    # printed "PREMIUM BASIS: Payroll" in the GL hazard table and disarmed its
    # own check while every word-level ban passed.
    #
    # So: across BOTH P1 files, the token "payroll" may appear EXACTLY ONCE -
    # the bare WC figure in P1A - and never as a rating basis.
    p1_text = (texts.get("P1A_application_llc_values_omitted.pdf", "") + "\n"
               + texts.get("P1B_dec_page_llc_spelling_variant.pdf", ""))
    _payroll_mentions = p1_text.count("payroll")
    if _payroll_mentions != 1:
        problems.append(
            f"P1 mentions 'payroll' {_payroll_mentions} time(s); it must be EXACTLY 1 "
            f"(the bare WC figure). A second mention - especially a PREMIUM BASIS "
            f"column - satisfies the annual test and check 4 tests nothing")
    for basis in ("basis payroll", "payroll $", "basis remuneration", "remuneration"):
        if basis in p1_text:
            problems.append(f"P1 states a rating basis of '{basis}' - that IS a "
                            f"statement that the payroll is annual")

    # P3 is only a guard rail if nothing about it is missing.
    p3t = texts.get("P3_nonprofit_everything_stated.pdf", "")
    for term in ("contact name", "contact email", "primary phone", "fein",
                 "years in business", "audit period", "billing plan"):
        if term not in p3t:
            problems.append(f"P3 omits '{term}' - it must state EVERYTHING or it "
                            f"cannot prove the new rules stay silent")
    return problems


PACKAGES = [
    ("P1A_application_llc_values_omitted.pdf", p1a),
    ("P1B_dec_page_llc_spelling_variant.pdf", p1b),
    ("P2_new_venture_sole_proprietor.pdf", p2),
    ("P3_nonprofit_everything_stated.pdf", p3),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = []
    for name, fn in PACKAGES:
        path = os.path.join(OUT_DIR, name)
        fn(path)
        paths.append(path)
        print(f"  wrote {name}")

    problems = _verify(paths)
    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(_README)
    print(f"  wrote README-HOW-TO-TEST.md")

    if problems:
        print("\nFIXTURE SELF-CHECK FAILED:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"\nAll {len(paths)} files verified. Output: {OUT_DIR}")


_README = """# H4 / client section 9 - how to test

Generated by `py backend/scripts/make_c9_test_pdfs.py`. **Regenerate before every
run** - the policy dates are computed from today, and a stale set drifts into an
expired-term or renewal path these packages were not built for.

Three packages, four files. Upload each package as its OWN submission.

| Package | Files | What it proves |
|---|---|---|
| **P1** | `P1A_...` + `P1B_...` uploaded TOGETHER | routing, contact demotion, entity normalisation, the WC payroll-period deduction |
| **P2** | `P2_...` | new venture is a valid state; zero is a value; prior carrier reaches the client |
| **P3** | `P3_...` | **the guard rail** - every new rule must stay SILENT |

---

## P1 - Established LLC (upload BOTH files as one submission)

Select **ACORD 125 + 126 + 130** when offered.

**1. Data Consistency must NOT flag the entity type.**
The two files print the same entity as `Limited Liability Corporation` (ACORD's
own checkbox wording) and `LLC`. Before H4 that raised a conflict card.
- [ ] No Data Consistency / conflict row for **Entity Type**.

**2. The questionnaire split.** Open "Send to Client".
- [ ] **Client** bucket contains: **Prior carrier**, contact name, contact email,
      FEIN, years in business.
- [ ] **Agency** bucket contains: **Proposed expiration date**, **GL coverage
      form basis (occurrence / claims-made)**, **audit period**, **billing plan**,
      **WC payroll period**, X-Mod, WC class codes, NAICS/SIC.
- [ ] **Nothing** in the Client bucket asks for a class code, a coverage symbol,
      a limit, a deductible or a policy period.

**3. Contact demotion.** P1 supplies a phone and nothing else.
- [ ] Contact **name** and **email** appear, are NOT pre-ticked, and carry the
      badge **"Contact already provided"**.
- [ ] They are still visible and still selectable - if they vanished, that is a
      bug, not the fix.

**4. The WC payroll period, which is the deduction half.** P1's payroll is a bare
figure with no period word anywhere.
- [ ] The **producer** is asked "What period does the stated payroll figure
      cover...".
- [ ] The SQS Exposure detail shows the **-3 payroll period** item.
- [ ] Those two must agree. A charge with no question, or a question with no
      charge, is the exact failure this package exists to catch.

**5. Answer round trip - THE HEADLINE FIX.** Send the questionnaire to yourself.
In the client form:
- Answer **Prior carrier** with the single word `None`
- Answer **FEIN** with `N/A`
- Leave everything else blank, and submit.

- [ ] The submission is **accepted** (before H4 some of these produced a 422 you
      could not fix).
- [ ] Back in the producer view, prior carrier reads as **answered** - not still
      missing.
- [ ] Generate the forms and open ACORD 125: the prior-carrier and FEIN boxes are
      **BLANK**. The words `None` and `N/A` must not be printed anywhere.

**6. Entity checkbox.** On the generated ACORD 125, LEGAL ENTITY:
- [ ] Exactly **one** box ticked, and it is **Limited Liability Corporation**.

---

## P2 - New-venture sole proprietor

Select **ACORD 125 + 126**.

**7. Entity checkbox.** On the generated ACORD 125:
- [ ] Exactly one box ticked and it is **Individual**. (Before H4: none.)

**8. Zero employees is a value.**
- [ ] Number of employees shows **0** and is NOT listed as a missing detail.

**9. New venture retires the years question.** On the Loss History card, confirm
**New Venture** (answer yes / "new venture with no prior operations").
- [ ] "Years in business" disappears from the missing / key-details list.
- [ ] The Structural score goes **UP**, or at minimum does not go down.
- [ ] Loss History is Not Applicable, and the **Total Package Score still
      exists** - if the score vanishes, tell me immediately.
- [ ] Now REOPEN / clear that answer. Years in business must come **back** as
      owed. (A conclusion must not outlive its premise.)

**10. Prior carrier is a client question here too.**
- [ ] It appears in the **Client** bucket, not Agency.

---

## P3 - Non-profit, everything stated - THE GUARD RAIL

Select **ACORD 125 + 126 + 130**. This package states everything, so the correct
result is **silence**.

**11. Nothing new fires.**
- [ ] **No** WC payroll-period question, and **no -3** in the Exposure detail.
- [ ] **No** question for expiration date, GL form basis, audit period, billing
      plan, prior carrier, FEIN, years in business or contacts - all are stated.
- [ ] Contacts are complete, so no "Contact already provided" badge anywhere.
- [ ] No Data Consistency conflict of any kind.

**12. Entity checkbox.** On the generated ACORD 125:
- [ ] Exactly one box ticked and it is **Not For Profit**.
- [ ] The plain **Corporation** box is NOT ticked. (Before H4 it was, and
      Not For Profit was not.)

**13. The SQS panel.**
- [ ] Under **Narrative Quality**, there is no longer a
      "Prior Carrier / Marketing Reason" row.
- [ ] The pillar still renders with its other row.

---

## What to send back

For each package: the **Total Package Score**, the **Exposure** and **Structural**
detail rows, a screenshot of the **Send to Client** screen showing the Client and
Agency buckets, and the **LEGAL ENTITY** area of the generated ACORD 125.

Then just tell me, per numbered check: **pass**, or what you saw instead.

The three that matter most, in order:
1. **Check 5** - the client answering "None" and it surviving. That is the
   headline fix and it cannot be proven by a click-through of the forms alone.
2. **Check 11** - P3 staying silent. A rule that fires on the ordinary case is
   this codebase's most repeated failure.
3. **Check 4** - the payroll-period question and its -3 agreeing.
"""


if __name__ == "__main__":
    main()
