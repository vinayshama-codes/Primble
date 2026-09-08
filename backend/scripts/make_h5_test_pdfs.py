"""make_h5_test_pdfs.py - live test packages for client item 10 (V1 H5,
ACORD 25 Multi-Carrier Mapping).

    py backend/scripts/make_h5_test_pdfs.py

Writes to h5_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

TWO packages, ONE file each, TWO forms each (ACORD 25 + 125). Each is its own
session - two different insureds, so extraction caches and identity matching
never bleed between them.

  P1  THE CLIENT'S CASE   Two carriers of ONE GROUP across three lines, the
                          second one's name printed BOTH ways ("Casualty Co."
                          and "Casualty Company"), plus a Property line printed
                          NO COVERAGE that still names a fourth carrier, and no
                          Workers Comp anywhere.
                          Proves in one upload: the roster seats 2 insurers
                          (not 1, not 3); GL -> A while Auto AND Umbrella -> B;
                          each carrier keeps ITS OWN NAIC; the name prints "EMC"
                          not "Emc"; the WC row's INSR LTR stays BLANK; the
                          declined line's carrier is NEVER seated; and NO
                          carrier conflict is raised.
  P2  THE CONTROL         Two different insurers both writing General
                          Liability, and a Business Auto line written by one of
                          them alone.
                          Proves: scoping is not a blanket amnesty - this is
                          STILL a real Data Consistency conflict and the GL
                          INSR LTR ships BLANK; while AUTO still resolves to
                          its letter, so a conflict on one line does not
                          poison the rest of the form.

WHY ONLY TWO FILES
------------------
An earlier cut of this kit had four. The two dropped packages were a
three-carrier roster and a single-carrier control; both are covered by
`tests/test_h5_acord25_multicarrier.py` and neither adds a live behaviour the
two below do not already exercise. The denied-line check folded into P1 at no
cost, and P2's clean Auto line covers "an ordinary line still resolves" better
than a standalone single-carrier package did, because it proves it while a
conflict is live on the same submission.

WHY THE CARRIER NAMES IN P1 ARE THE REAL ONES
----------------------------------------------
The client's defect is not "two names appeared". It is that `normalize_carrier`
is a FAMILY key, and these two legally distinct companies belong to the same
group, so both collapse to "emc" and fused into ONE candidate that then appeared
to sit on two coverage lines at once:

    normalize_carrier("EMC Property & Casualty Company")   -> "emc"
    normalize_carrier("Employers Mutual Casualty Company") -> "emc"
    normalize_carrier("Employers Mutual Casualty Co")      -> "employers"

Invented names do not fuse, so an invented P1 would pass without testing
anything. Replaying the client's literal values is the standing rule.

Design rules (inherited from make_c6_test_pdfs.py, all proven)
--------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY so nothing drifts into an expired-term or renewal
  path (a routed renewal moves dates to prior_* and changes what is asked).
* Every coverage line prints its OWN Carrier / NAIC / Policy Number / Premium,
  which is what RULE 16 asks extraction for and what the roster reads.
* Every package's ABSENCES are self-verified at the bottom of this file by
  scanning the generated text - one stray word silently invalidates a check.
  It has already earned its keep: a subtitle reading "no workers compensation"
  failed this check, because naming the line at all risks extraction reading a
  WC line onto the package whose blank WC letter is one of P1's checks.
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
    "h5_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Northgate Insurance Partners LLC"


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
    return y - 0.09 * inch


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp,
               yib, naics, entity="Limited Liability Company"):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", entity)
    y = _row(c, y, "Contact", f"{contact}, {phone}, {email}")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Proposed Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", sales)
    y = _row(c, y, "Number of Employees", emp)
    y = _row(c, y, "Years in Business", yib)
    y = _row(c, y, "NAICS Code", naics)
    return y


def _coverage(c, y, heading, carrier, naic, policy, premium, limits):
    """One coverage part, printed the way a package dec page prints it: the
    line's OWN carrier, NAIC, number and premium under its own heading. This
    block is exactly what RULE 16 turns into a `coverage_lines` row."""
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    if naic:
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
             ("Personal & Advertising Injury Limit", "$1,000,000"),
             ("Damage To Rented Premises", "$100,000"),
             ("Medical Expense Limit", "$5,000"),
             ("Coverage Form", "Occurrence")]
AUTO_LIMITS = [("Combined Single Limit - Each Accident", "$1,000,000"),
               ("Covered Autos", "Symbol 1 - Any Auto")]
UMB_LIMITS = [("Each Occurrence Limit", "$3,000,000"),
              ("Aggregate Limit", "$3,000,000"),
              ("Self-Insured Retention", "$10,000"),
              ("Coverage Form", "Occurrence")]


def _vehicles(c, y):
    y = _head(c, y, "SCHEDULE OF VEHICLES")
    return _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW"],
                  [["2021", "Ford", "F-250", "1FT7W2BT5MED12345", "10,000"],
                   ["2019", "Isuzu", "NPR", "JALC4W163K7001234", "14,500"]],
                  [1.0, 1.8, 2.7, 3.7, 6.0])


def _gl_classes(c, y):
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    return _table(c, y,
                  ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
                  [["Location 1", "91580 - Carpentry - interior", "Payroll", "$318,400"]],
                  [1.0, 2.5, 4.6, 5.9])


# ── P1 - THE CLIENT'S CASE ──────────────────────────────────────────────────
EMC_GL = "EMC Property & Casualty Company"
EMC_AUTO = "Employers Mutual Casualty Co."
EMC_UMB = "Employers Mutual Casualty Company"
P1_DENIED = "Meridian Grove Insurance Company"


def build_p1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE DECLARATIONS",
              "Multi-carrier package - one insured, two affording insurers")
    y = _applicant(
        c, y, "Verdant Slope Builders LLC",
        "4800 Dahlia Street Suite D13, Denver, CO 80216",
        "84-2210987", "Dana Ostrander", "(303) 555-0142",
        "dostrander@verdantslopebuilders.com",
        "Interior carpentry and light commercial remodeling. No work above three stories.",
        "$2,450,000", "14", "9", "238350")
    y = _para(c, y, "")
    y = _para(c, y, "This package is issued by two affiliated companies. Each coverage")
    y = _para(c, y, "part below is written by the company named against that part.")

    y = _new_page(c, "GENERAL LIABILITY DECLARATIONS")
    y = _coverage(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY",
                  EMC_GL, "25186", "BBC7263-26", "$9,640", GL_LIMITS)
    y = _gl_classes(c, y)

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS")
    y = _coverage(c, y, "COVERAGE - BUSINESS AUTO",
                  EMC_AUTO, "21415", "6E7-40-02-26", "$2,991", AUTO_LIMITS)
    y = _vehicles(c, y)

    y = _new_page(c, "COMMERCIAL UMBRELLA DECLARATIONS")
    y = _coverage(c, y, "COVERAGE - COMMERCIAL LIABILITY UMBRELLA",
                  EMC_UMB, "21415", "6J7-40-02-26", "$3,418", UMB_LIMITS)
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, ["COVERAGE", "CARRIER", "POLICY NUMBER", "LIMIT"],
               [["General Liability", "EMC Property & Casualty", "BBC7263-26", "$1,000,000"],
                ["Business Auto", "Employers Mutual Casualty", "6E7-40-02-26", "$1,000,000"]],
               [1.0, 2.4, 4.4, 6.2])

    # The declined line: a real carrier name against a line the applicant does
    # NOT carry. Seating it would tell a certificate holder an insurer stands
    # behind coverage that does not exist.
    y = _new_page(c, "COVERAGE PARTS NOT PURCHASED")
    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", P1_DENIED)
    y = _row(c, y, "Annual Premium", "NO COVERAGE")
    y = _para(c, y, "Commercial Property was quoted by the company named above and was")
    y = _para(c, y, "declined by the applicant. No property coverage is afforded.")
    c.save()


# ── P2 - THE CONTROL ────────────────────────────────────────────────────────
P2_GL_A = "Redwood Basin Insurance Company"
P2_GL_B = "Trinity Ridge Mutual Insurance Company"


def build_p2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE DECLARATIONS",
              "Two general liability policies in force on one account")
    y = _applicant(
        c, y, "Cobblestone Grounds Maintenance LLC",
        "77 Larkspur Terrace, Longmont, CO 80501",
        "87-3390115", "Marcus Whitfield", "(720) 555-0193",
        "mwhitfield@cobblestonegrounds.com",
        "Commercial landscaping, grounds maintenance and seasonal snow removal.",
        "$1,340,000", "22", "6", "561730")

    y = _new_page(c, "GENERAL LIABILITY DECLARATIONS - PRIMARY")
    y = _coverage(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY",
                  P2_GL_A, "19402", "RBI-GL-551208", "$7,900", GL_LIMITS)
    y = _gl_classes(c, y)

    y = _new_page(c, "GENERAL LIABILITY DECLARATIONS - SECOND POLICY")
    y = _coverage(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY",
                  P2_GL_B, "23871", "TRM-GL-770934", "$4,150", GL_LIMITS)
    y = _para(c, y, "A second general liability policy is in force for the same term.")

    # A clean line written by ONE of the two carriers. Its letter must still
    # resolve while the GL row cannot - a conflict on one coverage line must
    # not poison the rest of the certificate.
    y = _new_page(c, "BUSINESS AUTO DECLARATIONS")
    y = _coverage(c, y, "COVERAGE - BUSINESS AUTO",
                  P2_GL_A, "19402", "RBI-BA-551209", "$3,300", AUTO_LIMITS)
    y = _vehicles(c, y)
    c.save()


# ── Self-verification: the ABSENCES are the whole test ──────────────────────

def _text(path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths: dict) -> list:
    """A check is only as good as the fixture. Each package asserts what it
    must CONTAIN and - the part that actually breaks silently - what it must
    NOT."""
    problems = []
    t1, t2 = _text(paths["P1"]), _text(paths["P2"])

    for name in (EMC_GL, EMC_AUTO, EMC_UMB, P1_DENIED):
        if name not in t1:
            problems.append(f"P1 is missing the carrier {name!r}")
    if "BBC7263-26" not in t1 or "6E7-40-02-26" not in t1 or "6J7-40-02-26" not in t1:
        problems.append("P1 lost one of its three policy numbers")
    if "NO COVERAGE" not in t1:
        problems.append("P1's property line must print NO COVERAGE or the "
                        "declined-carrier check proves nothing")
    if re.search(r"workers\s+comp", t1, re.I):
        problems.append("P1 must NOT name workers compensation anywhere - even "
                        "to deny it. The blank WC INSR LTR is one of its checks "
                        "and naming the line risks extraction creating one.")

    for name in (P2_GL_A, P2_GL_B):
        if name not in t2:
            problems.append(f"P2 is missing the carrier {name!r}")
    if t2.count("COMMERCIAL GENERAL LIABILITY") < 2:
        problems.append("P2 needs TWO general liability coverage blocks")
    if P2_GL_B in t2.split("BUSINESS AUTO DECLARATIONS")[-1]:
        problems.append("P2's auto line must be written by ONE carrier only - "
                        "two would leave the auto letter blank and lose the "
                        "'a conflict does not poison the form' check")
    if re.search(r"umbrella|workers\s+comp", t2, re.I):
        problems.append("P2 must carry only general liability and auto")
    return problems


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = {
        "P1": os.path.join(OUT_DIR, "P1_two_carriers_client_case.pdf"),
        "P2": os.path.join(OUT_DIR, "P2_same_line_conflict_CONTROL.pdf"),
    }
    build_p1(paths["P1"])
    build_p2(paths["P2"])
    for k, p in paths.items():
        print(f"  wrote {k}: {os.path.relpath(p)}")

    # Anything from the four-package cut must not linger and get uploaded.
    for stale in ("P2_three_carriers_denied_line.pdf",
                  "P3_two_carriers_one_line_CONTROL.pdf",
                  "P4_single_carrier_CONTROL.pdf"):
        sp = os.path.join(OUT_DIR, stale)
        if os.path.exists(sp):
            os.remove(sp)
            print(f"  removed stale {stale}")

    problems = _verify(paths)
    if problems:
        print("\nFIXTURE PROBLEMS - fix before testing:")
        for p in problems:
            print("  !", p)
    else:
        print("\n  self-check PASSED - every package contains what it must and "
              "omits what it must")

    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")


README = f"""
# H5 - ACORD 25 Multi-Carrier Mapping: how to test it live

**Two uploads. Two forms each: ACORD 25 + ACORD 125.**

Upload ONE file per session - they are two different companies on purpose, so
sessions never bleed. ACORD 25 is mandatory (it is the only form with an insurer
roster); the 125 is there because the client's ORIGINAL defect - a carrier
wearing another carrier's NAIC - prints on the 125 header, and it costs nothing.

Generated {TODAY.strftime('%Y-%m-%d')}. Terms run {EFF} to {EXP}.

---

## 1. `P1_two_carriers_client_case.pdf`   THE CLIENT'S CASE

Verdant Slope Builders. Two insurers of one group across three lines; the second
one's name is printed two ways ("Casualty Co." on the auto dec, "Casualty
Company" on the umbrella dec). A Commercial Property line is printed
**NO COVERAGE** but still names a fourth insurer. There is no Workers Comp.

**Generate: ACORD 25 + ACORD 125**

### Data Consistency screen, BEFORE generating
- **Carrier must NOT be something you are asked to fix.** It should either not
  appear, or appear read-only as **"N policies, N values - not a conflict"**
  with each value tagged by its coverage line.
- If it asks you to CHOOSE a carrier, that is a FAIL. Send the card.

### On the ACORD 25
| Box | Expected |
|---|---|
| INSURER A | `EMC Property & Casualty Company` - **capital EMC**, not "Emc" |
| INSURER A NAIC | `25186` |
| INSURER B | `Employers Mutual Casualty Company` (the FULLER printing) |
| INSURER B NAIC | `21415` - **not 25186** |
| INSURER C-F | blank |
| GENERAL LIABILITY INSR LTR | **A** |
| AUTOMOBILE LIABILITY INSR LTR | **B** |
| UMBRELLA LIAB INSR LTR | **B** |
| WORKERS COMP INSR LTR | **blank** |

Five things this one upload is checking - each was a real bug:
1. **Two insurer rows, not three.** "Casualty Co." and "Casualty Company" are
   ONE company. Three rows means the folding broke.
2. **"EMC", not "Emc".** We were title-casing a carrier's legal name.
3. **B's NAIC is 21415.** If B shows 25186 it has been handed A's identifier -
   the client's original defect.
4. **WC is blank, not borrowed** from another line.
5. **`Meridian Grove Insurance Company` appears NOWHERE.** It was quoted and
   declined; seating it would tell a certificate holder an insurer stands behind
   coverage that does not exist.

### On the ACORD 125
- Its carrier/NAIC header must not pair one carrier's name with the other's
  NAIC. Blank is an acceptable answer here; a recombined pair is not.

**Send back:** the Data Consistency section; the ACORD 25 INSURER block (all six
rows + NAICs); the four INSR LTR boxes; the 125 carrier/NAIC header.

---

## 2. `P2_same_line_conflict_CONTROL.pdf`   THE CONTROL

Cobblestone Grounds. **Two different insurers both writing General Liability**,
plus a Business Auto line written by the first of them alone. This package is
SUPPOSED to complain.

**Generate: ACORD 25 + ACORD 125**

| Box | Expected |
|---|---|
| INSURER A | `Redwood Basin Insurance Company` |
| INSURER B | `Trinity Ridge Mutual Insurance Company` |
| GENERAL LIABILITY INSR LTR | **blank** |
| AUTOMOBILE LIABILITY INSR LTR | **A** |
| UMBRELLA / WC INSR LTR | blank |

- **A carrier conflict SHOULD appear** on the Data Consistency screen. This is
  the case a producer genuinely has to resolve, and it is how we know the fix
  did not simply silence everything.
- **GL INSR LTR blank** - the certificate prints one row per coverage, so there
  is no honest letter for it.
- **AUTO INSR LTR = A** - the important half. A conflict on ONE coverage line
  must not poison the rest of the form.

If P2 is silent, the fix over-corrected. **That matters more than P1 passing.**

**Not a bug on P2:** the GL *policy number* is blank too - two GL policies, so no
single number belongs on the one GL row. That is behaviour from 2026-08-15, not
something H5 changed.

**Send back:** the Data Consistency section (I need to see the conflict); the
INSURER block; the GL and AUTO INSR LTR boxes.

---

## What to send back

Per package, in one message:

1. **The Data Consistency section** - half the fix lives here, and P2 is where
   it has to fire.
2. **The ACORD 25 INSURER(S) AFFORDING COVERAGE block** - all six rows plus
   NAICs, so I can see what was seated and what stayed blank.
3. **The INSR LTR box of every coverage row** - GL, Auto, Umbrella, WC.
4. P1 only: the ACORD 125 carrier/NAIC header.

A PASS / DIFFERS table is enough. **One failing line with the value it actually
printed beats the rest passing** - the value tells me which door failed.

On scores: they are SUPPOSED to move up on P1 - newly filled boxes add fill-rate
credit, and it no longer takes the 85 cap from a false carrier conflict. P2
should still be capped; it has a real conflict.
"""


if __name__ == "__main__":
    main()
