"""make_sys07b_test_pdfs.py - live kit for the 2026-09-05 SYS-07 broadening.

    py backend/scripts/make_sys07b_test_pdfs.py

Writes to sys07b_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

WHY A SECOND KIT. `sys07_test_data/` tests "Yes" against "X" and nothing else.
Everything shipped on 2026-09-05 is invisible to it: the DECLARATIONS-PAGE
vocabulary ("Covered" / "Not Covered" / "Elected"), and POLICY-NUMBER
FORMATTING, which the acceptance criteria names in the same breath as the
booleans and which was still drawing a false card on the client's own package.

FOUR files, TWO sessions.

  PACKAGE C   C1 + C2 uploaded TOGETHER
              A dec page that answers in a carrier's own words, and a
              certificate that answers with marks. The dec prints its policy
              number with the 2-digit TERM marker, the certificate prints it
              bare - `BBC7263 - 26` against `BBC7263`, the client's LIVE shape.
              Must produce ZERO Data Consistency conflicts.

  PACKAGE D   D1 + D2 uploaded TOGETHER - the positive control.
              Genuinely different answers AND genuinely different policy
              numbers, one character apart. Must STILL be asked, and the card
              must print the two raw values.

WHAT THIS KIT DELIBERATELY DOES NOT TEST, and why that is honest.
The two-line table cell, the one-space label, the half-bracket "X]" and the
OCR letter-spacing "Y e s" cannot be forced through a live run: the extraction
model reads the page and emits a tidy value of its own choosing, so a pass
would prove the MODEL tidied up, not that our reader handles the shape. Those
four are pinned by unit tests against the shipped reader
(`tests/test_sys07_boolean_normalization_20260904.py`) and are left out here
rather than faked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.pagesizes import LETTER            # noqa: E402
from reportlab.pdfgen import canvas                   # noqa: E402

from scripts.make_sys07_test_pdfs import (            # noqa: E402
    _page, _new_page, _row, _head, _para, _table, _coverage,
    EFF, EXP, AGENCY, GL_LIMITS, AUTO_LIMITS,
)

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sys07b_test_data",
)

# ── PACKAGE C - one submission, two vocabularies ────────────────────────────
C_INSURED = "Wexford Marine Supply LLC"
C_ADDR = "884 Quayside Boulevard, Suite 210, Norfolk, VA 23510"
C_FEIN = "54-3319077"
C_OPS = ("Wholesale distribution of marine hardware and boat parts to "
         "dealer accounts")
C_CARRIER = "Tidewater Mutual Insurance Company"
C_NAIC = "23582"

# THE POLICY NUMBER UNDER TEST. One contract, two printings - the dec page
# carries the 2-digit policy TERM, the certificate does not. Before 2026-09-05
# the picker reported these as two policies on one coverage line.
C_POL_DEC = "BBC7263 - 26"
C_POL_CERT = "BBC7263"
C_POL_AUTO_DEC = "6E7-40-02---26"
C_POL_AUTO_CERT = "6E74002"

# (label, how the DEC prints it, how the CERTIFICATE prints it)
# Left column: the words a carrier's declarations page actually uses.
# Right column: the marks a broker puts on a certificate.
C_ANSWERS = [
    ("Hired and Non-Owned Auto Coverage", "Covered", "X"),
    ("Hired Auto Liability", "Elected", "Y"),
    ("Non-Owned Auto Liability", "Provided", "[X]"),
    ("Prior Cyber Incidents or Data Breaches", "Not Covered", "N"),
]


def build_c1(path):
    """Declarations page. Answers in the carrier's OWN words, policy number
    printed WITH its term marker."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - new business, no expiring policy "
              "is being replaced")
    y = _row(c, y, "Named Insured", C_INSURED)
    y = _row(c, y, "Mailing Address", C_ADDR)
    y = _row(c, y, "FEIN", C_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Marisol Vane, (757) 555-0148, "
                              "mvane@wexfordmarine.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Description of Operations", C_OPS)
    y = _row(c, y, "Annual Gross Sales", "$7,650,000")
    y = _row(c, y, "Number of Employees", "31")
    y = _row(c, y, "Years in Business", "12")
    y = _row(c, y, "NAICS Code", "423910")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", C_CARRIER, C_NAIC, C_POL_DEC, "$6,940"],
                ["Commercial Auto", C_CARRIER, C_NAIC, C_POL_AUTO_DEC, "$3,510"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _row(c, y, "Total Advance Premium", "$10,450")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", C_CARRIER, C_NAIC,
                  C_POL_DEC, "$6,940", GL_LIMITS)
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE", "RATE"],
               [["11288", "Marine hardware distributors", "Sales",
                 "$7,650,000", "0.907"]],
               [1.0, 2.0, 4.6, 5.5, 6.7])

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS",
                  "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", C_CARRIER, C_NAIC,
                  C_POL_AUTO_DEC, "$3,510", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2022", "Ford", "F-350", "1FT8W3BT7NEC12048", "12,400",
                 "Commercial"],
                ["2020", "Chevrolet", "Express 2500", "1GCWGAFP2L1183377",
                 "8,600", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])

    # ── THE ANSWERS, IN THE CARRIER'S OWN WORDS ─────────────────────────────
    y = _head(c, y, "COVERAGE OPTIONS AND UNDERWRITING RESPONSES")
    y = _para(c, y, "The coverage status below forms part of this policy.")
    for label, dec_word, _mark in C_ANSWERS:
        y = _row(c, y, label, dec_word)
    c.save()


def build_c2(path):
    """Certificate. The SAME answers as MARKS, the SAME policy contracts
    printed WITHOUT their term markers."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and "
              "confers no rights upon the certificate holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", C_INSURED)
    y = _row(c, y, "Insured Address", C_ADDR)
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _table(c, y, ["LTR", "INSURER", "NAIC #"], [["A", C_CARRIER, C_NAIC]],
               [1.0, 1.7, 5.6])

    y = _head(c, y, "COVERAGES")
    y = _table(c, y,
               ["LTR", "TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP",
                "LIMITS"],
               [["A", "Commercial General Liability", C_POL_CERT, EFF, EXP,
                 "$1,000,000 / $2,000,000"],
                ["A", "Automobile Liability", C_POL_AUTO_CERT, EFF, EXP,
                 "$1,000,000 CSL"]],
               [1.0, 1.4, 3.5, 4.6, 5.5, 6.35])

    y = _head(c, y, "COVERAGE OPTIONS CONFIRMED BY THE PRODUCER")
    for label, _dec_word, mark in C_ANSWERS:
        y = _row(c, y, label, mark)
    c.save()


# ── PACKAGE D - the positive control ────────────────────────────────────────
D_INSURED = "Bellamy Freight Systems LLC"
D_ADDR = "1207 Cargo Terminal Road, Memphis, TN 38118"
D_FEIN = "62-4108852"
D_CARRIER = "Delta Provident Insurance Company"
D_NAIC = "27189"
# ONE CHARACTER APART. Two real policies, not two printings of one.
D_POL_1 = "BBC7263"
D_POL_2 = "BBC7264"
D_ANSWERS = [
    ("Hired and Non-Owned Auto Coverage", "Covered", "Not Covered"),
    ("Sprinkler System", "Yes", "No"),
]


def _d_common(c, note):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", note)
    y = _row(c, y, "Named Insured", D_INSURED)
    y = _row(c, y, "Mailing Address", D_ADDR)
    y = _row(c, y, "FEIN", D_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Description of Operations", "Local freight trucking")
    y = _row(c, y, "Annual Gross Sales", "$4,200,000")
    y = _row(c, y, "Number of Employees", "23")
    y = _row(c, y, "Carrier", D_CARRIER)
    y = _row(c, y, "Carrier NAIC", D_NAIC)
    return y


def build_d1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _d_common(c, "Submitted by the producer")
    y = _row(c, y, "Policy Number", D_POL_1)
    y = _head(c, y, "UNDERWRITING RESPONSES")
    for label, first, _second in D_ANSWERS:
        y = _row(c, y, label, first)
    c.save()


def build_d2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _d_common(c, "Supplemental questionnaire completed by the applicant")
    y = _row(c, y, "Policy Number", D_POL_2)
    y = _head(c, y, "UNDERWRITING RESPONSES")
    for label, _first, second in D_ANSWERS:
        y = _row(c, y, label, second)
    c.save()


# ── SELF-VERIFICATION - the kit refuses to write a claim it cannot prove ────

def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths):
    problems = []
    c1, c2, d1, d2 = (_text(p) for p in paths)
    from services.normalization import canonical_yes_no
    from services.fact_comparison import same_policy_contract

    for label, word, mark in C_ANSWERS:
        if ("%s: %s" % (label, word)) not in c1:
            problems.append("C1 does not print %r as %r" % (label, word))
        if ("%s: %s" % (label, mark)) not in c2:
            problems.append("C2 does not print %r as %r" % (label, mark))
        if word.lower() == mark.lower():
            problems.append("%r prints the same spelling in both files" % label)
        a, b = canonical_yes_no(word), canonical_yes_no(mark)
        if a is None or b is None:
            problems.append(
                "the shipped reader cannot read %r/%r for %r - the kit would "
                "fail for the wrong reason" % (word, mark, label))
        elif a != b:
            problems.append(
                "%r and %r are NOT one answer under the shipped reader "
                "(%s vs %s)" % (word, mark, a, b))

    for dec, cert in ((C_POL_DEC, C_POL_CERT),
                      (C_POL_AUTO_DEC, C_POL_AUTO_CERT)):
        if dec not in c1:
            problems.append("C1 does not print %r" % dec)
        if cert not in c2:
            problems.append("C2 does not print %r" % cert)
        if not same_policy_contract(dec, cert):
            problems.append(
                "%r and %r are not one contract under the shipped rule - "
                "package C would fail correctly" % (dec, cert))

    if same_policy_contract(D_POL_1, D_POL_2):
        problems.append("%r and %r fold - package D cannot prove anything"
                        % (D_POL_1, D_POL_2))
    for label, first, second in D_ANSWERS:
        if ("%s: %s" % (label, first)) not in d1:
            problems.append("D1 does not print %r as %r" % (label, first))
        if ("%s: %s" % (label, second)) not in d2:
            problems.append("D2 does not print %r as %r" % (label, second))
        if canonical_yes_no(first) == canonical_yes_no(second):
            problems.append("D's %r does not actually disagree" % label)
    return problems


README = """# SYS-07 round 2 - the carrier's own words, and the policy number

Two sessions. Upload each pair TOGETHER, as one submission.

| Session | Upload | What must happen |
|---|---|---|
| **C** | `C1_dec_page_words.pdf` + `C2_certificate_marks.pdf` | **ZERO** Data Consistency cards |
| **D** | `D1_application.pdf` + `D2_questionnaire.pdf` | Cards **DO** appear |

## What C is proving

The dec page answers in a carrier's own vocabulary and the certificate answers
with marks. They say the same thing:

| Question | Dec page (C1) | Certificate (C2) |
|---|---|---|
| Hired and Non-Owned Auto Coverage | `Covered` | `X` |
| Hired Auto Liability | `Elected` | `Y` |
| Non-Owned Auto Liability | `Provided` | `[X]` |
| Prior Cyber Incidents or Data Breaches | `Not Covered` | `N` |

And the same two policy contracts, printed two ways - **this is the client's
own live shape**:

| Line | Dec page (C1) | Certificate (C2) |
|---|---|---|
| General Liability | `BBC7263 - 26` | `BBC7263` |
| Commercial Auto | `6E7-40-02---26` | `6E74002` |

Before 2026-09-05 every row above produced a "documents disagree" card.

## What D is proving, and why it is also the instrument

D's two files genuinely disagree - `Covered` against `Not Covered`, `Yes`
against `No`, and policy `BBC7263` against `BBC7264` (one character apart, two
real policies). **Cards must still appear.** Normalising must not become an
amnesty.

D does a second job. The extraction model is free to tidy `Covered` into `Yes`
on its own. If it does, C passes for the WRONG reason and nothing about carrier
vocabulary was tested. **D's cards print the two raw values.** If they read
`Covered` / `Not Covered`, the model kept the words and C's pass is real. If
they read `Yes` / `No`, the model normalised upstream and C is only a
regression check. Either way we learn which.

## Report back

1. **Session C** - the Data Consistency section, in full. Expected: nothing.
   If any card appears, send the exact card - the fact name and both values.
2. **Session D** - the same section. Expected: cards for the auto coverage
   question, the sprinkler question, and the policy number. Send the RAW values
   each card prints.
3. **The review screen for both** - the crime advisory and the AAIS bureau
   guard have never been confirmed live, and this is the run that can do it.
4. Forms are **not** required. Everything here is decided before generation.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = [os.path.join(OUT_DIR, n) for n in (
        "C1_dec_page_words.pdf", "C2_certificate_marks.pdf",
        "D1_application.pdf", "D2_questionnaire.pdf")]
    build_c1(paths[0])
    build_c2(paths[1])
    build_d1(paths[2])
    build_d2(paths[3])
    problems = _verify(paths)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)
    if problems:
        print("REFUSING TO CLAIM THIS KIT IS CORRECT:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("wrote %d PDFs + README to %s" % (len(paths), OUT_DIR))
    for p in paths:
        print("   ", os.path.basename(p))


if __name__ == "__main__":
    main()
