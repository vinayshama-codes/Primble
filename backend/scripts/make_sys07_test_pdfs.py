"""make_sys07_test_pdfs.py - live test kit for SYS-07 (Yes / true / X / checkbox).

    py backend/scripts/make_sys07_test_pdfs.py

Writes to sys07_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

FOUR files, TWO sessions. They cannot be merged, and that is the design:

  PACKAGE A   A1 + A2 uploaded TOGETHER (one session)
              The client's own pairing - a package policy and a certificate.
              Every Yes/No answer is IDENTICAL in meaning and DIFFERENT in
              spelling: the policy prints words, the certificate prints marks.
              Must produce ZERO Data Consistency conflicts.

  PACKAGE B   B1 + B2 uploaded TOGETHER (a second session)
              The positive control. The two documents genuinely DISAGREE, and
              they disagree in MARKS ("X" against "N"). Must STILL be asked.

WHY BOTH, AND WHY B IS ALSO THE INSTRUMENT
------------------------------------------
A asserts "this is not a conflict". B asserts "this IS one". Put B's
disagreement into A and A can no longer prove anything.

B does a second job that A cannot. The extraction model is free to normalise a
mark to the word "Yes" on its own - if it does, A passes for the WRONG reason
and nothing about marks was tested. B's conflict card PRINTS THE TWO RAW
VALUES. If it shows "X" and "N", the model echoed the marks and A's pass is
real. If it shows "Yes" and "No", the model normalised upstream and A is only a
regression check. Either way we learn which, and that is why B's values must be
reported verbatim.

WHAT EACH EDGE CASE IS FOR
--------------------------
  1  policy "Yes" vs certificate "X"            THE CLIENT'S LITERAL CASE
     (auto_hired_nonowned)                       (the reported screenshot)
  2  policy "Yes" vs certificate "[X]"          a checkbox transcribed with its
     (non_owned_auto_indicator)                  brackets - never read before
  3  policy "No" vs certificate "N"             the NEGATIVE half of the
     (cyber_prior_incidents)                     acceptance criteria
  4  hired_auto_indicator                       REGRESSION CONTROL: this fact
                                                 was already typed Yes/No before
                                                 the fix (its key carries the
                                                 word "indicator"), so it must
                                                 behave exactly as it always did
  5  every other value identical across A1/A2   the ONLY thing that can produce
                                                 a conflict in A is a spelling
  6  (B) "X" against "N" on one fact            a mark against a mark, opposite
                                                 answers - normalising must not
                                                 become an amnesty
  7  (B) "Yes" against "No" on sprinkler_system  a fact that USED to compare as
                                                 free text and now compares as
                                                 Yes/No - it must not have lost
                                                 the ability to disagree
  8  no "N/A", no "None", no "null" anywhere    those are NON-answers on a
                                                 separate, still-open path
                                                 (CLAUDE.md "GAP 1"). Including
                                                 one would manufacture a failure
                                                 that is not SYS-07's.
  9  no renewal language anywhere               a routed renewal moves dates to
                                                 prior_* and changes what is
                                                 asked - pure noise here

WHY THE LABELS ARE BYTE-IDENTICAL IN BOTH FILES OF A PAIR
----------------------------------------------------------
The extractor decides which fact a printed line belongs to. If A1 said "Hired
and Non-Owned Auto Coverage" and A2 said "HNOA Liability", a difference in the
RESULT could just as well be two labels landing on two different facts - the
test would prove nothing. Identical labels, different values: then the only
variable is the representation, which is the whole subject of SYS-07.

Design rules (inherited from make_sys06 / make_c6 / make_h5, all proven)
------------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY, so nothing drifts into an expired-term path.
* Both files of a pair agree on EVERY other value - identity, limits, policy
  numbers, premiums - so a conflict anywhere else is a real finding.
* Self-verified at the bottom of this file by re-reading the generated text:
  every value present, every absence held, and every pair confirmed to differ
  in spelling while meaning the same thing.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sys07_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Meridian Coast Insurance Brokers LLC"

# ── The four Yes/No questions under test ────────────────────────────────────
# The LABEL is what both files of a pair print, byte-identical. The two VALUES
# are the two spellings of one answer.
Q_HNOA = "Hired and Non-Owned Auto Coverage"          # -> auto_hired_nonowned
Q_HIRED = "Hired Auto Liability"                      # -> hired_auto_indicator
Q_NONOWNED = "Non-Owned Auto Liability"               # -> non_owned_auto_indicator
Q_CYBER = "Prior Cyber Incidents or Data Breaches"    # -> cyber_prior_incidents
Q_SPRINKLER = "Sprinkler System"                      # -> sprinkler_system


# ── Layout helpers (identical to make_sys06's, which are proven extractable) ─

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


def _row(c, y, label, value, lw=3.4):
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
    return y - 0.09 * inch


def _coverage(c, y, heading, carrier, naic, policy, premium, limits):
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Carrier NAIC", naic)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    for label, value in limits:
        y = _row(c, y, label, value)
    y = _row(c, y, "Annual Premium", premium)
    return y


GL_LIMITS = [("Each Occurrence Limit", "$1,000,000"),
             ("General Aggregate Limit", "$2,000,000"),
             ("Products/Completed Operations Aggregate", "$2,000,000"),
             ("Personal and Advertising Injury Limit", "$1,000,000"),
             ("Damage To Rented Premises", "$100,000"),
             ("Medical Expense Limit", "$5,000"),
             ("Coverage Form", "Occurrence")]
AUTO_LIMITS = [("Combined Single Limit - Each Accident", "$1,000,000"),
               ("Covered Autos", "Symbol 1 - Any Auto"),
               ("Comprehensive Deductible", "$1,000"),
               ("Collision Deductible", "$1,000")]
CYBER_LIMITS = [("Aggregate Limit", "$1,000,000"),
                ("Retention", "$10,000")]


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE A - THE CLIENT'S CASE (two files, uploaded TOGETHER)
#
# A1 answers in WORDS. A2 answers with MARKS. Same answers.
# ════════════════════════════════════════════════════════════════════════════

A_INSURED = "Northgate Provisions Group LLC"
A_ADDR = "2140 Harborview Parkway, Suite 300, Tacoma, WA 98402"
A_FEIN = "91-4402873"
A_OPS = ("Wholesale distribution of packaged food products to grocery and "
         "restaurant accounts")
A_CARRIER = "Cascade Standard Insurance Company"
A_NAIC = "26841"
A_POL_GL = "CSG-GL-770412-26"
A_POL_AUTO = "CSG-CA-770418-26"
A_POL_CYBER = "CSG-CY-770423-26"

# The A pair: (label, word printing, mark printing). Same answer, two alphabets.
A_ANSWERS = [
    (Q_HNOA, "Yes", "X"),          # edge case 1 - the client's literal case
    (Q_HIRED, "Yes", "Y"),         # edge case 4 - the regression control
    (Q_NONOWNED, "Yes", "[X]"),    # edge case 2
    (Q_CYBER, "No", "N"),          # edge case 3 - the negative half
]


def build_a1(path):
    """The package declarations page. Every Yes/No answer printed as a WORD."""
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - new business proposal, no expiring "
              "policy is being replaced")
    y = _row(c, y, "Named Insured", A_INSURED)
    y = _row(c, y, "Mailing Address", A_ADDR)
    y = _row(c, y, "FEIN", A_FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Dana Whitcomb, (253) 555-0172, "
                              "dwhitcomb@northgateprovisions.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", A_OPS)
    y = _row(c, y, "Annual Gross Sales", "$9,300,000")
    y = _row(c, y, "Number of Employees", "44")
    y = _row(c, y, "Years in Business", "16")
    y = _row(c, y, "NAICS Code", "424490")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", A_CARRIER, A_NAIC, A_POL_GL, "$8,140"],
                ["Commercial Auto", A_CARRIER, A_NAIC, A_POL_AUTO, "$4,275"],
                ["Cyber Liability", A_CARRIER, A_NAIC, A_POL_CYBER, "$1,860"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _row(c, y, "Total Advance Premium", "$14,275")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_GL, "$8,140", GL_LIMITS)
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE", "RATE"],
               [["11288", "Food products distributors", "Sales", "$9,300,000", "0.874"]],
               [1.0, 2.0, 4.6, 5.5, 6.7])

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS", "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_AUTO, "$4,275", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2023", "Freightliner", "M2 106", "1FVACWDT8PHNP4417", "33,000", "Commercial"],
                ["2021", "Isuzu", "NPR HD", "JALC4W164M7001885", "14,500", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])
    # ── THE FOUR ANSWERS, IN WORDS ──────────────────────────────────────────
    y = _head(c, y, "COVERAGE OPTIONS AND UNDERWRITING RESPONSES")
    y = _para(c, y, "The responses below were provided by the applicant and form "
                    "part of this policy.")
    for label, word, _mark in A_ANSWERS:
        y = _row(c, y, label, word)

    y = _new_page(c, "CYBER LIABILITY DECLARATIONS", "Coverage Part - Cyber Liability")
    y = _coverage(c, y, "CYBER LIABILITY COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_CYBER, "$1,860", CYBER_LIMITS)
    y = _head(c, y, "APPLICANT REPRESENTATIONS - CYBER")
    y = _row(c, y, Q_CYBER, "No")
    y = _row(c, y, "Multi-Factor Authentication In Use", "Yes")
    y = _row(c, y, "Offsite Backups Performed", "Yes")

    c.save()


def build_a2(path):
    """The certificate. The SAME four answers, printed as MARKS.

    Deliberately a CERTIFICATE and not a second application: the client's own
    reported pairing was a package policy against a COI, and a COI is exactly
    where a broker prints an X rather than a word. Every fact under test here
    is one a certificate is allowed to witness - `fact_comparison.
    _ROLE_BLIND_FACTS` blinds a certificate to COPE and exposure values, which
    is why `sprinkler_system` is tested in package B instead of this one.
    """
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and "
              "confers no rights upon the certificate holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", A_INSURED)
    y = _row(c, y, "Insured Address", A_ADDR)
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _table(c, y, ["LTR", "INSURER", "NAIC #"],
               [["A", A_CARRIER, A_NAIC]],
               [1.0, 1.6, 5.9])

    y = _head(c, y, "COVERAGES")
    y = _table(c, y,
               ["TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
               [["General Liability", A_POL_GL, EFF, EXP, "$1,000,000 Each Occurrence"],
                ["General Liability", A_POL_GL, EFF, EXP, "$2,000,000 General Aggregate"],
                ["Automobile Liability", A_POL_AUTO, EFF, EXP, "$1,000,000 Combined Single Limit"],
                ["Cyber Liability", A_POL_CYBER, EFF, EXP, "$1,000,000 Aggregate"]],
               [1.0, 2.5, 4.15, 5.05, 5.95])

    # ── THE SAME FOUR ANSWERS, AS MARKS ─────────────────────────────────────
    # The labels are byte-identical to A1's. Only the alphabet changes.
    y = _head(c, y, "COVERAGE OPTIONS ELECTED")
    y = _para(c, y, "Mark indicates the option applies to the policies described "
                    "above.")
    for label, _word, mark in A_ANSWERS:
        y = _row(c, y, label, mark)

    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    y = _para(c, y, A_OPS + ".")
    y = _para(c, y, "Certificate holder is an additional insured with respect to "
                    "general liability where required by written contract.")
    c.save()


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE B - THE POSITIVE CONTROL (two files, uploaded TOGETHER)
#
# The two documents genuinely DISAGREE, and one pair disagrees in MARKS.
# Both are applications, so neither is role-blind to the property questions.
# ════════════════════════════════════════════════════════════════════════════

B_INSURED = "Blackwater Mill Fabrication Inc"
B_ADDR = "77 Ironworks Road, Youngstown, OH 44505"
B_FEIN = "34-7712049"
B_OPS = "Structural steel fabrication and light machining for commercial builders"
B_CARRIER = "Allegheny Mutual Casualty Company"
B_NAIC = "19305"
B_POL_GL = "AMC-GL-330761-26"
B_POL_AUTO = "AMC-CA-330768-26"


def _b_common(c, y, title_note):
    y = _row(c, y, "Named Insured", B_INSURED)
    y = _row(c, y, "Mailing Address", B_ADDR)
    y = _row(c, y, "FEIN", B_FEIN)
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Contact", "Rebecca Alvarado, (330) 555-0119, "
                              "ralvarado@blackwatermill.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", B_OPS)
    y = _row(c, y, "Annual Gross Sales", "$6,150,000")
    y = _row(c, y, "Number of Employees", "31")
    y = _row(c, y, "Years in Business", "22")
    y = _row(c, y, "NAICS Code", "332312")
    y = _head(c, y, "COVERAGE SUMMARY")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", B_CARRIER, B_NAIC, B_POL_GL, "$11,420"],
                ["Commercial Auto", B_CARRIER, B_NAIC, B_POL_AUTO, "$5,900"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _head(c, y, "PREMISES INFORMATION")
    y = _row(c, y, "Location Address", B_ADDR)
    y = _row(c, y, "Year Built", "1994")
    y = _row(c, y, "Construction Type", "Joisted Masonry")
    y = _row(c, y, "Occupancy Type", "Manufacturing")
    y = _row(c, y, "Roof Year", "2016")
    y = _row(c, y, "Square Footage", "48,000")
    y = _row(c, y, "Fire Protection Class", "4")
    y = _row(c, y, "Distance To Hydrant", "220 feet")
    y = _para(c, y, title_note)
    return y


def build_b1(path):
    """Application. HNOA answered with a MARK; sprinkler answered as a WORD."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant information and coverage request - new business")
    y = _b_common(c, y, "Prepared by the producing agency from the applicant's "
                        "own responses.")
    y = _head(c, y, "UNDERWRITING RESPONSES")
    y = _row(c, y, Q_HNOA, "X")             # edge case 6 - affirmative, as a mark
    y = _row(c, y, Q_SPRINKLER, "Yes")      # edge case 7 - affirmative, as a word
    y = _row(c, y, Q_HIRED, "X")
    c.save()


def build_b2(path):
    """Supplemental questionnaire. The SAME two questions, answered NEGATIVE."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "SUPPLEMENTAL UNDERWRITING QUESTIONNAIRE",
              "Completed by the applicant - responses supersede nothing and are "
              "submitted alongside the application")
    y = _b_common(c, y, "Completed by the applicant directly.")
    y = _head(c, y, "UNDERWRITING RESPONSES")
    y = _row(c, y, Q_HNOA, "N")             # edge case 6 - a mark against a mark
    y = _row(c, y, Q_SPRINKLER, "No")       # edge case 7 - a word against a word
    y = _row(c, y, Q_HIRED, "N")
    c.save()


# ════════════════════════════════════════════════════════════════════════════
# SELF-VERIFICATION - the kit proves its own assumptions before he uploads it
# ════════════════════════════════════════════════════════════════════════════

# Words that would drag the run onto a different, still-open code path and
# manufacture a failure that is not SYS-07's (edge cases 8 and 9).
_FORBIDDEN = ("N/A", "renewal", "Renewal", "RENEWAL", "expiring policy number")


def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths):
    problems = []
    a1, a2, b1, b2 = (_text(p) for p in paths)

    # 1. Every question label appears in BOTH files of its pair, byte-identical.
    for label, word, mark in A_ANSWERS:
        if label not in a1:
            problems.append(f"A1 is missing the label {label!r}")
        if label not in a2:
            problems.append(f"A2 is missing the label {label!r}")
        if f"{label}: {word}" not in a1:
            problems.append(f"A1 does not print {label!r} as {word!r}")
        if f"{label}: {mark}" not in a2:
            problems.append(f"A2 does not print {label!r} as {mark!r}")
        if word.lower() == mark.lower():
            problems.append(f"{label!r} prints the SAME spelling in both files "
                            "- it tests nothing")

    # 2. The two spellings really are one answer under the shipped reader.
    try:
        from services.normalization import canonical_yes_no
        for label, word, mark in A_ANSWERS:
            if canonical_yes_no(word) != canonical_yes_no(mark):
                problems.append(
                    f"{label!r}: {word!r} and {mark!r} are NOT the same answer "
                    f"({canonical_yes_no(word)} vs {canonical_yes_no(mark)}) - "
                    "package A would be asserting the wrong thing")
            if canonical_yes_no(word) is None:
                problems.append(f"{label!r}: {word!r} is not readable as Yes/No")
        # 3. Package B's pairs must be genuine OPPOSITES.
        for q, v1, v2 in ((Q_HNOA, "X", "N"), (Q_SPRINKLER, "Yes", "No"),
                          (Q_HIRED, "X", "N")):
            if canonical_yes_no(v1) == canonical_yes_no(v2):
                problems.append(f"B: {q!r} {v1!r} vs {v2!r} is not a disagreement "
                                "- the control proves nothing")
    except Exception as exc:                                  # noqa: BLE001
        problems.append(f"could not import the shipped reader: {exc}")

    # 4. A1 and A2 must agree on EVERYTHING else, so the only thing that can
    #    conflict is a spelling.
    for value in (A_INSURED, A_ADDR, A_CARRIER, A_NAIC,
                  A_POL_GL, A_POL_AUTO, A_POL_CYBER, EFF, EXP, AGENCY):
        if value not in a1:
            problems.append(f"A1 is missing the shared value {value!r}")
        if value not in a2:
            problems.append(f"A2 is missing the shared value {value!r}")

    # 5. B1 and B2 must agree on everything EXCEPT the three answers.
    for value in (B_INSURED, B_ADDR, B_FEIN, B_CARRIER, B_NAIC,
                  B_POL_GL, B_POL_AUTO, EFF, EXP):
        if value not in b1:
            problems.append(f"B1 is missing the shared value {value!r}")
        if value not in b2:
            problems.append(f"B2 is missing the shared value {value!r}")

    # 6. Absences (edge cases 8 and 9).
    for name, text in (("A1", a1), ("A2", a2), ("B1", b1), ("B2", b2)):
        for bad in _FORBIDDEN:
            if bad in text:
                problems.append(f"{name} contains {bad!r} - it would pull the "
                                "run onto a different code path")

    # 7. The two packages must not share an insured, or the sessions bleed.
    if A_INSURED in b1 or B_INSURED in a1:
        problems.append("the two packages share an insured")
    return problems


README = """# SYS-07 live test - Yes, true, X and a checked box are ONE answer

Generated by `backend/scripts/make_sys07_test_pdfs.py`. Regenerate any time.

**What is being tested.** The client's P0 item: *"The same affirmative answer
can arrive as 'Yes,' boolean true, X, or a checked box depending on the source
document and extraction path. These representation differences should not create
false conflicts."*

**Two uploads. Do not mix them.** Each package asserts one thing, and putting
them in one session destroys both claims.

---

## Upload 1 - PACKAGE A  (the client's case)

Upload **both files together, in one session:**

    A1_package_policy_words.pdf
    A2_certificate_marks.pdf

Both documents give the SAME four answers. A1 prints them as words, A2 prints
them as marks. The labels are byte-identical in both files, so the only thing
that differs is the spelling.

| Question | A1 (policy) | A2 (certificate) |
|---|---|---|
| Hired and Non-Owned Auto Coverage | `Yes` | `X`   <- the client's literal case |
| Hired Auto Liability | `Yes` | `Y` |
| Non-Owned Auto Liability | `Yes` | `[X]` |
| Prior Cyber Incidents or Data Breaches | `No` | `N` |

### Stop at the Review screen. No forms needed for this claim.

| Check | Expected |
|---|---|
| **Data Consistency** section | **NO card** for any of the four questions above |
| Any other Data Consistency card | there should be none at all - both files agree on every other value |
| Hard Stops | none |
| Warnings | the auto/vehicle and cyber-control items are normal for this package. **A Yes/No card would not be.** |

**If a card appears for any of the four, that is the failure. Send me the card
verbatim - the label, both values, and the file each came from.**

---

## Upload 2 - PACKAGE B  (the positive control - a SECOND session)

Upload **both files together, in a new session:**

    B1_application_mark_yes.pdf
    B2_questionnaire_mark_no.pdf

These two documents genuinely disagree, and two of the three disagreements are
spelled as marks:

| Question | B1 | B2 | This is a real disagreement |
|---|---|---|---|
| Hired and Non-Owned Auto Coverage | `X` | `N` | yes |
| Hired Auto Liability | `X` | `N` | yes |
| Sprinkler System | `Yes` | `No` | yes |

| Check | Expected |
|---|---|
| **Data Consistency** section | a card for these questions, asking you to confirm |
| The two values on the card | **report them verbatim** - see below, this is the important one |
| Confirm one | the card clears and does not come back |

### Why B matters more than it looks

The extraction model is allowed to tidy a mark into the word "Yes" on its own.
If it does, package A passes for the wrong reason and nothing about marks was
actually tested. **B's card prints the two raw values**, so:

* card shows **`X` and `N`** -> the model echoed the marks. A's pass is real.
* card shows **`Yes` and `No`** -> the model normalised upstream. A is still a
  valid regression check, but I will need a different probe for the mark path,
  and I would rather know now than guess.

Either result is useful. Just tell me which one you see.

---

## Forms: only ONE generation, and only on package A

The client's requirement is entirely visible on the Review screen, so **skip
form generation for package B.**

On **package A only**, generate **ACORD 125 and ACORD 127**. One check, and it
is a negative one - you do not need to know which box is which:

> **Scan every Y/N box on both forms. None of them may print a raw mark** -
> no `X`, no checkmark, no `[X]`, no `true`, no `1`. A Yes/No box must read
> `Y`, `N`, `Yes`, `No`, be ticked, or be blank.

That single sweep tests the stamping half of the fix. If you find a raw mark in
a Y/N box, screenshot it with the field name.

---

## What to send back

One message per upload. A PASS / DIFFERS table is enough - **one failing line
with the value it actually printed beats ten passing lines**, because the value
tells me which door failed.

**Package A**
1. The whole **Data Consistency** section (even if it is empty - "empty" IS the
   result I am looking for).
2. The **warning count** and the **hard stop count** at the top.
3. The **Submission Readiness / SQS** number.
4. From the generated ACORD 125 and 127: confirmation that no Y/N box printed a
   raw mark, or a screenshot of the one that did.

**Package B**
1. The Data Consistency section, and for each card **the two values verbatim**
   (this is the discriminator described above).
2. What happens after you confirm one card - does it clear, and does it stay
   cleared on a refresh?

### On scores

**Package A's score should be the same or HIGHER than you are used to.** A false
Yes/No conflict used to cap a package at 85; that cap is gone. **If A's score
goes DOWN, send it - that is a finding.**

**Package B should be capped** before you confirm - it has three real
disagreements. That is correct.

---

## Proof this kit is a real test (run before you upload anything)

A kit that passes on both the old code and the new one tests nothing. This one
was replayed through the REAL `assess_underwriting_consistency` with the shipped
code disabled, using exactly the values the four PDFs print:

**Package A on the OLD code - three false conflicts:**

    auto_hired_nonowned        ['Yes', 'X']     <- the client's literal case
    cyber_prior_incidents      ['No',  'N']
    non_owned_auto_indicator   ['Yes', '[X]']
    hired_auto_indicator       (silent)         <- the regression control,
                                                   correctly quiet on both

**Package A on the shipped code - zero conflicts.**
**Package B on the shipped code - three conflicts, printing `X` and `N`.**

So: if package A comes back clean and package B still asks, the fix is live on
your machine. If package A shows any of those three cards, it is not.

---

### One thing this kit deliberately does NOT test

No document here contains "N/A", "None" or "null" as an answer. Those are
NON-answers, not negatives, and the extraction side of that is a separate,
still-open gap (recorded in CLAUDE.md as "GAP 1" - `answer_semantics` covers
the human path only). Putting one in would have manufactured a failure that is
not SYS-07's, and I would rather test one thing honestly.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    a1 = os.path.join(OUT_DIR, "A1_package_policy_words.pdf")
    a2 = os.path.join(OUT_DIR, "A2_certificate_marks.pdf")
    b1 = os.path.join(OUT_DIR, "B1_application_mark_yes.pdf")
    b2 = os.path.join(OUT_DIR, "B2_questionnaire_mark_no.pdf")
    build_a1(a1)
    build_a2(a2)
    build_b1(b1)
    build_b2(b2)

    problems = _verify([a1, a2, b1, b2])
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)

    for p in (a1, a2, b1, b2):
        print("wrote", os.path.relpath(p, os.path.dirname(OUT_DIR)))
    print("wrote", os.path.relpath(
        os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), os.path.dirname(OUT_DIR)))
    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("\nself-check: OK - every label byte-identical across its pair, every "
          "A pair is one answer in two alphabets, every B pair is a genuine "
          "disagreement, and no forbidden token is present")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    main()
