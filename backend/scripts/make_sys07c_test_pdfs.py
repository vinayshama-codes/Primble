"""make_sys07c_test_pdfs.py - the kit for everything still UNPROVEN live.

    py backend/scripts/make_sys07c_test_pdfs.py

Writes to sys07c_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

WHY A THIRD KIT, AND WHY THE SECOND ONE CANNOT DO THIS JOB.
`sys07b` was measured making **zero** lexicon calls: every word it prints is
already readable by the deterministic table or the shipped seed. It proves no
regression and nothing else. This kit prints words that are in NEITHER - so
`yes_no_lexicon` must actually ask the model, live, or package E fails.

It also carries the two fixes that have never been exercised by any kit:
the **AAIS rating-bureau guard** and the **crime-exposure advisory**.

FOUR files, TWO sessions.

  PACKAGE E   E1 + E2 uploaded TOGETHER. EVERYTHING must be silent:
              * four carrier words nobody listed, against certificate marks
              * AAIS printed where a carrier name is expected
              * a janitorial firm whose customers are "retail centers"
              Expect ZERO Data Consistency cards and NO crime warning.

  PACKAGE F   F1 + F2 uploaded TOGETHER. The controls that must still SPEAK:
              * "Pending" against "Yes" - a NON-ANSWER can never be
                classified, however the model replies (core principle 3)
              * "Underwritten" against "Stricken" - two words the model has
                just learned, in opposite directions, must still disagree
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
    "sys07c_test_data",
)

# ── PACKAGE E ───────────────────────────────────────────────────────────────
E_INSURED = "Halloway Facility Services LLC"
E_ADDR = "3410 Corporate Ridge Drive, Suite 120, Columbus, OH 43215"
E_FEIN = "31-5580264"
# THE CRIME ADVISORY CONTROL. "retail" belongs to the CUSTOMERS. A janitorial
# firm is not a retail store, and the live run before the fix warned on exactly
# this sentence. Must stay silent.
E_OPS = ("Janitorial and building maintenance services for office buildings "
         "and retail centers")
E_CARRIER = "Buckeye Guaranty Insurance Company"
E_NAIC = "24074"
E_POL_GL = "BGI-GL-551907-26"
E_POL_AUTO = "BGI-CA-551912-26"

# THE AAIS CONTROL. A rating bureau AUTHORS coverage forms; it never issues the
# policy. It is printed here exactly where a real policy prints it - in the
# forms schedule - and it must never become a candidate for "who is the
# carrier?".
E_BUREAU = "American Association of Insurance Services (AAIS)"

# (label, the word the DEC prints, the mark the CERTIFICATE prints)
# NOT ONE OF THESE WORDS IS IN THE DETERMINISTIC TABLE OR THE SEED. If the
# lexicon does not fire, every row below becomes a conflict card.
E_ANSWERS = [
    ("Hired and Non-Owned Auto Coverage", "Underwritten", "X"),
    ("Hired Auto Liability", "Placed", "Y"),
    ("Non-Owned Auto Liability", "Issued", "[X]"),
    ("Prior Cyber Incidents or Data Breaches", "Withdrawn", "N"),
]


def build_e1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - new business, no expiring policy "
              "is being replaced")
    y = _row(c, y, "Named Insured", E_INSURED)
    y = _row(c, y, "Mailing Address", E_ADDR)
    y = _row(c, y, "FEIN", E_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Priya Raghunathan, (614) 555-0193, "
                              "praghunathan@hallowayfs.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Description of Operations", E_OPS)
    y = _row(c, y, "Annual Gross Sales", "$5,480,000")
    y = _row(c, y, "Number of Employees", "62")
    y = _row(c, y, "Years in Business", "9")
    y = _row(c, y, "NAICS Code", "561720")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER",
                      "PREMIUM"],
               [["General Liability", E_CARRIER, E_NAIC, E_POL_GL, "$7,220"],
                ["Commercial Auto", E_CARRIER, E_NAIC, E_POL_AUTO, "$3,940"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _row(c, y, "Total Advance Premium", "$11,160")

    # ── THE AAIS CONTROL, printed where a real policy prints it ─────────────
    y = _head(c, y, "FORMS AND ENDORSEMENTS")
    y = _para(c, y, "Coverage forms in this policy are promulgated by "
                    + E_BUREAU + ".")
    y = _row(c, y, "Forms Author", E_BUREAU)
    y = _row(c, y, "Rating Bureau", "AAIS")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", E_CARRIER, E_NAIC,
                  E_POL_GL, "$7,220", GL_LIMITS)
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE",
                      "RATE"],
               [["91580", "Janitorial services", "Payroll", "$1,840,000",
                 "3.921"]],
               [1.0, 2.0, 4.6, 5.5, 6.7])

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS",
                  "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", E_CARRIER, E_NAIC,
                  E_POL_AUTO, "$3,940", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2021", "Ford", "Transit 250", "1FTBR1C8XMKA33471", "8,670",
                 "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])

    # ── THE FOUR UNLISTED WORDS ─────────────────────────────────────────────
    y = _head(c, y, "COVERAGE OPTIONS AND UNDERWRITING RESPONSES")
    y = _para(c, y, "The coverage status below forms part of this policy.")
    for label, word, _mark in E_ANSWERS:
        y = _row(c, y, label, word)
    c.save()


def build_e2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and "
              "confers no rights upon the certificate holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", E_INSURED)
    y = _row(c, y, "Insured Address", E_ADDR)
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _table(c, y, ["LTR", "INSURER", "NAIC #"], [["A", E_CARRIER, E_NAIC]],
               [1.0, 1.7, 5.6])
    y = _head(c, y, "COVERAGES")
    y = _table(c, y,
               ["LTR", "TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP",
                "LIMITS"],
               [["A", "Commercial General Liability", E_POL_GL, EFF, EXP,
                 "$1,000,000 / $2,000,000"],
                ["A", "Automobile Liability", E_POL_AUTO, EFF, EXP,
                 "$1,000,000 CSL"]],
               [1.0, 1.4, 3.5, 4.6, 5.5, 6.35])
    y = _para(c, y, "Forms promulgated by " + E_BUREAU + ".")
    y = _head(c, y, "COVERAGE OPTIONS CONFIRMED BY THE PRODUCER")
    for label, _word, mark in E_ANSWERS:
        y = _row(c, y, label, mark)
    c.save()


# ── PACKAGE F - the controls that must still speak ──────────────────────────
F_INSURED = "Ardmore Logistics Partners LLC"
F_ADDR = "708 Kingsway Industrial Court, Louisville, KY 40209"
F_FEIN = "61-2277409"
F_CARRIER = "Ohio Valley Indemnity Company"
F_NAIC = "25321"
F_POL = "OVI-PK-330815-26"
F_ANSWERS = [
    # A NON-ANSWER against a real answer. `Pending` is pinned unclassifiable,
    # so this must remain a card however the model would have answered.
    ("Prior Cyber Incidents or Data Breaches", "Pending", "Yes"),
    # Two words the model learns in package E, in OPPOSITE directions.
    # Learning must not become an amnesty.
    ("Hired and Non-Owned Auto Coverage", "Underwritten", "Stricken"),
]


def _f_common(c, note):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", note)
    y = _row(c, y, "Named Insured", F_INSURED)
    y = _row(c, y, "Mailing Address", F_ADDR)
    y = _row(c, y, "FEIN", F_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Dean Marchetti, (502) 555-0164, "
                              "dmarchetti@ardmorelogistics.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Description of Operations", "Local freight logistics and "
                                                "warehousing")
    y = _row(c, y, "Annual Gross Sales", "$6,100,000")
    y = _row(c, y, "Number of Employees", "38")
    y = _row(c, y, "Years in Business", "14")
    y = _row(c, y, "NAICS Code", "484110")
    y = _row(c, y, "Carrier", F_CARRIER)
    y = _row(c, y, "Carrier NAIC", F_NAIC)
    y = _row(c, y, "Policy Number", F_POL)
    # LIVE RUN F, 2026-09-05: the auto control produced NO card because the
    # fact was never extracted - both files named a carrier and a policy but
    # no auto coverage, so there was nothing for the auto question to attach
    # to. A control that is not extracted is not a control. The coverage part
    # below gives the question its context.
    y = _row(c, y, "Lines of Business Requested",
             "General Liability, Commercial Auto")
    y = _head(c, y, "BUSINESS AUTO COVERAGE PART")
    y = _row(c, y, "Combined Single Limit - Each Accident", "$1,000,000")
    y = _row(c, y, "Covered Autos", "Symbol 1 - Any Auto")
    y = _row(c, y, "Comprehensive Deductible", "$1,000")
    y = _row(c, y, "Collision Deductible", "$1,000")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2022", "Freightliner", "M2 106", "1FVACWDT4NHNP7712",
                 "33,000", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])
    return y


def build_f1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _f_common(c, "Submitted by the producer")
    y = _head(c, y, "UNDERWRITING RESPONSES")
    for label, first, _second in F_ANSWERS:
        y = _row(c, y, label, first)
    c.save()


def build_f2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _f_common(c, "Supplemental questionnaire completed by the applicant")
    y = _head(c, y, "UNDERWRITING RESPONSES")
    for label, _first, second in F_ANSWERS:
        y = _row(c, y, label, second)
    c.save()


# ── SELF-VERIFICATION ───────────────────────────────────────────────────────

def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths):
    problems = []
    e1, e2, f1, f2 = (_text(p) for p in paths)
    from services.normalization import yes_no_answer, is_insurance_bureau
    from services import yes_no_lexicon as lex

    # E's words must be unreadable TODAY - that is what forces a live call.
    for label, word, mark in E_ANSWERS:
        if ("%s: %s" % (label, word)) not in e1:
            problems.append("E1 does not print %r as %r" % (label, word))
        if ("%s: %s" % (label, mark)) not in e2:
            problems.append("E2 does not print %r as %r" % (label, mark))
        if yes_no_answer(word) is not None:
            problems.append(
                "%r is ALREADY readable deterministically - it cannot test "
                "the lexicon" % word)
        if lex.lookup(word) is not None:
            problems.append(
                "%r is already in the seed/cache - it cannot force a call"
                % word)
        if word.lower() not in lex.unknown_terms([word]):
            problems.append("%r would not be asked about - E proves nothing"
                            % word)
        if yes_no_answer(mark) is None:
            problems.append("the certificate mark %r is not readable" % mark)

    if not is_insurance_bureau("AAIS"):
        problems.append("AAIS is not recognised as a rating bureau - E's "
                        "bureau control is inert")
    if E_BUREAU not in e1 or "AAIS" not in e2:
        problems.append("the AAIS control is not printed in both files")
    if "retail centers" not in e1:
        problems.append("the crime-advisory control sentence is missing")

    # F: Pending must be unclassifiable, and the pair must really disagree.
    if lex.normalize_term("Pending") not in (None,) and \
            "pending" in lex.unknown_terms(["Pending"]):
        problems.append("'Pending' would be sent to the model - it is pinned "
                        "unclassifiable and must never be asked about")
    if lex.lookup("Pending") is not None:
        problems.append("'Pending' resolved to a Yes/No - F's control is dead")
    for _f, _n in ((f1, "F1"), (f2, "F2")):
        if "BUSINESS AUTO COVERAGE PART" not in _f:
            problems.append("%s has no auto coverage context - the auto "
                            "control cannot be extracted (live run F)" % _n)
    for label, first, second in F_ANSWERS:
        if ("%s: %s" % (label, first)) not in f1:
            problems.append("F1 does not print %r as %r" % (label, first))
        if ("%s: %s" % (label, second)) not in f2:
            problems.append("F2 does not print %r as %r" % (label, second))
    return problems


README = """# SYS-07 round 3 - the words nobody listed, AAIS, and the crime advisory

Two sessions. Upload each pair TOGETHER, as one submission.

| Session | Upload | What must happen |
|---|---|---|
| **E** | `E1_dec_page_unlisted_words.pdf` + `E2_certificate_marks.pdf` | **ZERO** cards, **NO** crime warning, **AAIS never offered as the carrier** |
|  |  | *Run 1 (2026-09-05) FAILED on the three words - the collection dropped every fact because a per-document fact is an annotated envelope, not a string. Fixed; re-run.* |
| **F** | `F1_application.pdf` + `F2_questionnaire.pdf` | Cards **DO** appear |

## Why this kit exists

The previous kit (`sys07b`) makes **zero** AI vocabulary calls - every word in
it was already readable. It proves nothing about the new lexicon. Every word
below is in **neither** the deterministic table **nor** the shipped seed, so
the AI must actually be asked, live, or package E fails.

## Session E - everything must be silent

| Question | Dec page (E1) | Certificate (E2) |
|---|---|---|
| Hired and Non-Owned Auto Coverage | `Underwritten` | `X` |
| Hired Auto Liability | `Placed` | `Y` |
| Non-Owned Auto Liability | `Issued` | `[X]` |
| Prior Cyber Incidents or Data Breaches | `Withdrawn` | `N` |

Two more controls ride along in the same package:

* **AAIS.** `American Association of Insurance Services (AAIS)` is printed in
  the forms schedule of E1 and on E2, exactly where a real policy prints it.
  A rating bureau AUTHORS coverage forms; it never issues the policy.
  **AAIS must never appear as a choice under Carrier.**
* **The crime advisory.** E is a **janitorial** firm whose customers are
  "office buildings and **retail centers**". Before the fix, that sentence
  produced a crime-exposure warning because of the word "retail".
  **There must be no crime warning.**

## Session F - the controls that must still speak

| Question | F1 | F2 | Why |
|---|---|---|---|
| Prior Cyber Incidents | `Pending` | `Yes` | A **non-answer** can never be classified, whatever the AI replies. Must still card. |
| Hired and Non-Owned Auto | `Underwritten` | `Stricken` | Two words the AI learns in session E, opposite directions. **Learning must not become an amnesty.** |

**Run E first**, then F. F's second row is only a real test once E has taught
the system both words.

## Report back

1. **Session E** - the Data Consistency section in full (expect nothing), the
   Carrier row if one appears, and confirm there is **no crime warning** in the
   Warnings list.
2. **Session F** - the same section. Expect a card for the cyber question and
   one for the auto question. Send the RAW values each card prints.
3. If anything in E produced a card, send the exact fact name and both values -
   that tells me whether the AI was asked and refused, or never asked.
4. Forms are **not** required.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = [os.path.join(OUT_DIR, n) for n in (
        "E1_dec_page_unlisted_words.pdf", "E2_certificate_marks.pdf",
        "F1_application.pdf", "F2_questionnaire.pdf")]
    build_e1(paths[0])
    build_e2(paths[1])
    build_f1(paths[2])
    build_f2(paths[3])
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
