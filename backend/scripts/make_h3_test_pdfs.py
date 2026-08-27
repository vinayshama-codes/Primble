"""make_h3_test_pdfs.py - live test packages for client section 8 (V1 H3,
Workers Compensation Data Capture) - every clause, in THREE packages.

    py backend/scripts/make_h3_test_pdfs.py

Writes to h3_test_data/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks, the steps, and exactly what to send back.

THREE packages, ONE file each, each its OWN session (a different company every
time, so extraction caches and identity matching never bleed).

Package -> what it proves live
  W1  COMPLETE, ONE STATE   8.1 the whole employee-group table (group + duties,
                            full-time, part-time, annual payroll, state, class
                            code) stamped on the ACORD 130; 8.2 officers with
                            INC / EXC, X-Mod, subcontracting; payroll-by-state
                            DERIVED and AGREEING with the 125 total (the guard
                            rail: the new hard stop must stay SILENT); 8.3 a
                            compound "8810 Clerical" cell normalized; the same
                            rating row printed twice must fold to ONE row
  W2  TWO STATES, TOTALS    two states -> Part 1 lists CO and TX, the rating
      DISAGREE              sheet's state label stays BLANK; the rows sum to
                            $800,000 against a stated $1,150,000 total, so the
                            10% state-total HARD STOP fires - a spec rule that
                            has never once run on live data (H3-B, Q30, D6)
  W3  NO CLASS TABLE        8.3 the boundary: a roofing account with NO class
                            schedule anywhere. Every code box on the 130 must
                            ship BLANK - Primble may not generate a code from
                            "residential roofing". The empty table must still
                            be ASKED, and a code the PRODUCER types must stamp.
                            Also a bare "Payroll: $640,000" -> the H1-K payroll
                            period -3 must still fire (regression).

Design rules (inherited from make_c6_test_pdfs.py, all proven)
--------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates are computed from TODAY so nothing drifts into an expired-term path.
* Every package's ABSENCES are self-verified at the bottom of this file by
  scanning the generated text - one stray word silently invalidates a check.
* FIXTURE RULE (H3): a package that must show the payroll-period -3 may not
  print a class row carrying a REMUNERATION amount and may not print the word
  "annual" beside its payroll - either one satisfies the period by itself
  (D43). That is why W3 prints a bare "Payroll:" line and no class table.
* FIXTURE RULE (H3): W2 must NOT print a WC-section payroll TOTAL. A total
  would also trip the pre-existing 20% `wc_payroll_mismatch` rule and put two
  hard stops on the screen, hiding which one is being tested.
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
    "h3_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
MOD_EFF = (TODAY - timedelta(days=45)).strftime("%m/%d/%Y")
AGENCY = "Front Range Insurance Advisors LLC"
CARRIER = "Cascade Mutual Insurance Company"


# ── Layout helpers ──────────────────────────────────────────────────────────

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.85 * inch, 7.5 * inch, 9.85 * inch)
    return 9.6 * inch


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


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp, yib, naics):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", f"{contact}, {phone}, {email}")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Proposed Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", sales)
    y = _row(c, y, "Number of Employees", emp)
    y = _row(c, y, "Years in Business", yib)
    y = _row(c, y, "NAICS Code", naics)
    return y


def _gl(c, y, policy):
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Coverage Form", "Occurrence")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Annual Premium", "$11,480")
    return y


def _wc_head(c, y, policy):
    y = _head(c, y, "COVERAGE - WORKERS COMPENSATION AND EMPLOYERS LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Employers Liability", "$1,000,000 / $1,000,000 / $1,000,000")
    y = _row(c, y, "Annual Premium", "$47,300")
    return y


def _save(name, draw):
    path = os.path.join(OUT_DIR, name)
    c = canvas.Canvas(path, pagesize=LETTER)
    draw(c)
    c.showPage()
    c.save()
    return path


# ═════════════════════════════════════════════════════════════════════════════
# W1 - SUMMIT RIDGE ROOFING: the complete employee-group table, one state
# ═════════════════════════════════════════════════════════════════════════════
W1_NAME = "SUMMIT RIDGE ROOFING LLC"


def w1_complete_single_state(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability and Workers Compensation")
    y = _applicant(
        c, y, W1_NAME, "1420 Vasquez Boulevard, Denver CO 80216", "84-2277401",
        "Dana Whitfield", "(303) 555-0148", "dana@summitridgeroofing.com",
        "Residential roofing installation and repair", "$2,400,000", "15", "9", "238160")
    y = _row(c, y, "Estimated Annual Payroll", "$800,000")
    y = _row(c, y, "Percentage of Work Subcontracted", "15%")
    y = _gl(c, y, "GL-8841207-26")
    y = _wc_head(c, y, "WC-4419883-26")

    # FIRST printing of the rating rows - a combined "CLASS CODE /
    # CLASSIFICATION" column, which is how a premium summary really prints.
    # Two jobs: it is the compound cell 8.3's normalizer must split, and it is
    # the duplicate the chunk union must fold against the rating sheet.
    y = _head(c, y, "WORKERS COMPENSATION PREMIUM SUMMARY")
    y = _table(c, y, ["STATE", "CLASS CODE / CLASSIFICATION", "ESTIMATED ANNUAL REMUNERATION"],
               [["CO", "8810 Clerical", "$100,000"],
                ["CO", "8742 Outside Sales", "$180,000"],
                ["CO", "5551 Roofing", "$520,000"]],
               [1.0, 1.9, 5.0])

    y = _new_page(c, "WORKERS COMPENSATION - STATE RATING SHEET",
                  f"{W1_NAME} - State: COLORADO - Sheet 1 of 1")
    y = _head(c, y, "CLASSIFICATION OF OPERATIONS")
    y = _table(
        c, y,
        ["CLASS CODE", "CLASSIFICATION AND DUTIES", "FULL-TIME", "PART-TIME",
         "ANNUAL REMUNERATION", "RATE"],
        [["8810", "Clerical - office and administrative", "2", "0", "$100,000", "0.21"],
         ["8742", "Outside sales", "3", "0", "$180,000", "0.38"],
         ["5551", "Roofing installation", "8", "2", "$520,000", "12.14"]],
        [1.0, 1.75, 3.85, 4.55, 5.25, 6.85])
    y = _para(c, y, "All employees are located in Colorado. No payroll is developed in any other state.")

    y = _head(c, y, "EXPERIENCE RATING")
    y = _row(c, y, "Experience Modification Factor", "0.92")
    y = _row(c, y, "Experience Modification Effective Date", MOD_EFF)

    y = _head(c, y, "OFFICERS AND OWNERS")
    y = _table(c, y, ["NAME", "TITLE", "OWNERSHIP %", "INCLUDED / EXCLUDED"],
               [["Dana Whitfield", "President", "60%", "Included"],
                ["Marcus Ruiz", "Vice President", "40%", "Excluded"]],
               [1.0, 3.0, 4.6, 5.9])
    y = _para(c, y, "Subcontractors are required to carry their own workers compensation coverage.")
    return y


# ═════════════════════════════════════════════════════════════════════════════
# W2 - BLUE MESA MECHANICAL: two states, rows do not reconcile to the total
# ═════════════════════════════════════════════════════════════════════════════
W2_NAME = "BLUE MESA MECHANICAL LLC"


def w2_two_states_mismatch(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability and Workers Compensation")
    y = _applicant(
        c, y, W2_NAME, "3305 South Broadway, Englewood CO 80113", "86-1140552",
        "Renata Ossola", "(303) 555-0192", "renata@bluemesamech.com",
        "Commercial plumbing contractor", "$3,100,000", "12", "14", "238220")
    y = _row(c, y, "Total Annual Payroll", "$1,150,000")
    y = _row(c, y, "Percentage of Work Subcontracted", "5%")
    y = _gl(c, y, "GL-9930514-26")
    y = _wc_head(c, y, "WC-7712064-26")

    y = _new_page(c, "WORKERS COMPENSATION - CLASSIFICATION SCHEDULE",
                  f"{W2_NAME} - operations in Colorado and Texas")
    y = _head(c, y, "CLASSIFICATION OF OPERATIONS BY STATE")
    # NO schedule total is printed - see the fixture rule at the top of the file.
    y = _table(
        c, y,
        ["STATE", "CLASS CODE", "CLASSIFICATION AND DUTIES", "FULL-TIME",
         "ANNUAL REMUNERATION"],
        [["CO", "8810", "Clerical - office and administrative", "2", "$90,000"],
         ["CO", "5183", "Plumbing - commercial", "6", "$410,000"],
         ["TX", "5183", "Plumbing - commercial", "4", "$300,000"]],
        [1.0, 1.7, 2.6, 5.15, 5.95])
    y = _para(c, y, "Field crews travel between the Colorado and Texas job sites.")

    y = _head(c, y, "EXPERIENCE RATING")
    y = _row(c, y, "Experience Modification Factor", "1.05")
    y = _row(c, y, "Experience Modification Effective Date", MOD_EFF)
    return y


# ═════════════════════════════════════════════════════════════════════════════
# W3 - CEDAR CREEK ROOFING: no class table anywhere (the 8.3 boundary)
# ═════════════════════════════════════════════════════════════════════════════
W3_NAME = "CEDAR CREEK ROOFING AND SIDING LLC"


def w3_no_class_table(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability and Workers Compensation")
    y = _applicant(
        c, y, W3_NAME, "77 Prospect Street, Longmont CO 80501", "87-3306118",
        "Priya Raghunathan", "(720) 555-0133", "priya@cedarcreekroofing.com",
        "Residential roofing installation, repair and siding replacement",
        "$1,650,000", "11", "6", "238160")
    # BARE payroll - no period word anywhere in the package (see fixture rule).
    y = _row(c, y, "Payroll", "$640,000")
    y = _gl(c, y, "GL-2214099-26")
    y = _wc_head(c, y, "WC-3390771-26")
    y = _para(c, y, "The applicant requests workers compensation coverage for all Colorado employees.")
    y = _para(c, y, "A classification schedule was not attached to this submission.")
    return y


# ── Self-verification ───────────────────────────────────────────────────────

def _text_of(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages).lower()


def _verify(paths: dict) -> list:
    p: list = []
    t = {k: _text_of(v) for k, v in paths.items()}

    def absent(key, *words):
        for w in words:
            if w in t[key]:
                p.append(f"{key} must NOT print {w!r}")

    def present(key, *words):
        for w in words:
            if w not in t[key]:
                p.append(f"{key} MUST print {w!r}")

    # ── W1: the complete table, one state, the compound cell, the duplicate ──
    present("W1", "8810 clerical", "8742 outside sales", "5551 roofing",
            "clerical - office and administrative", "outside sales",
            "roofing installation", "$100,000", "$180,000", "$520,000",
            "full-time", "part-time", "estimated annual payroll: $800,000",
            "state: colorado", "0.92", "experience modification effective date",
            "dana whitfield", "marcus ruiz", "included", "excluded",
            "percentage of work subcontracted: 15%")
    # The three group payrolls must sum to the stated total, or the new state
    # hard stop fires on the package built to prove it stays silent.
    if "800,000" not in t["W1"]:
        p.append("W1 total payroll must be $800,000 = 100k + 180k + 520k")
    # The company-wide headcount must be DIFFERENT from every group count, or
    # "the headcount leaked into a group box" cannot be detected.
    if "number of employees: 15" not in t["W1"]:
        p.append("W1 must state 15 employees (2+3+8 full-time + 2 part-time)")
    # A single state only - a second state code would break the sheet-label check.
    for code in (" tx ", " ut ", " wy ", " az ", " nm "):
        if code in t["W1"]:
            p.append(f"W1 must name only Colorado, found {code!r}")
    absent("W1", "not experience rated", "new venture")

    # ── W2: two states, no schedule total, rows do not reconcile ─────────────
    present("W2", "total annual payroll: $1,150,000", "8810", "5183",
            "plumbing - commercial", "$90,000", "$410,000", "$300,000",
            "co", "tx", "1.05")
    # A schedule TOTAL would trip the pre-existing 20% rule as well (fixture rule).
    for phrase in ("total estimated annual remuneration", "total remuneration",
                   "total payroll for workers compensation", "estimated annual payroll"):
        if phrase in t["W2"]:
            p.append(f"W2 must not print a WC payroll total ({phrase!r})")
    if "800,000" in t["W2"]:
        p.append("W2 must not print the row SUM - the mismatch must be computed, not read")
    absent("W2", "officers and owners", "included", "excluded")

    # ── W3: no class table, no officers, no period word ─────────────────────
    present("W3", "payroll: $640,000", "residential roofing",
            "classification schedule was not attached")
    absent("W3", "class code", "classification of operations", "remuneration",
           "annual payroll", "per year", "8810", "8742", "5551", "5183",
           "officer", "included", "excluded", "experience modification",
           "state rating", "full-time", "part-time", "rate:")
    # "annual" may appear ONLY in "Annual Gross Sales" / "Annual Premium" -
    # never within four words of the payroll figure, or the -3 cannot fire.
    for m in re.finditer(r"annual", t["W3"]):
        tail = t["W3"][m.start():m.start() + 60]
        if "payroll" in tail or "remuneration" in tail:
            p.append("W3's payroll must carry NO period wording")
    return p


PACKAGES = [
    ("W1", "W1_groups_complete_single_state.pdf", w1_complete_single_state),
    ("W2", "W2_two_states_total_mismatch.pdf", w2_two_states_mismatch),
    ("W3", "W3_no_class_table.pdf", w3_no_class_table),
]


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for stale in os.listdir(OUT_DIR):
        if stale.endswith(".pdf") and not any(stale == n for _, n, _ in PACKAGES):
            os.remove(os.path.join(OUT_DIR, stale))
    paths = {}
    for key, name, draw in PACKAGES:
        paths[key] = _save(name, draw)
        print(f"  {key}: {name}")
    problems = _verify(paths)
    if problems:
        for msg in problems:
            print("  FIXTURE DEFECT:", msg)
        raise SystemExit(1)
    print("  self-verification: every package prints what it must and nothing it must not")
    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")


README = f"""
# Client section 8 (V1 H3) - live test kit, three packages

Generated {TODAY.strftime('%Y-%m-%d')}. **Regenerate before every run**
(`py backend/scripts/make_h3_test_pdfs.py`). Extraction moved to **v17**, so every
upload re-extracts - do not reuse an older session for these checks.

Three uploads, three separate sessions. Each is ONE PDF. Generate **ACORD 125 + 130**
on all three - nothing here is read off any other form.

---

## ROUND 2 - what round 1 proved, and the 7 fixes to re-check

**The PDFs are unchanged.** Round 1 passed everything on the FORM (rows, counts, states,
the derived payroll-by-state, the hard stop, the 8.3 boundary) and found seven defects.
All seven are fixed; re-upload the same three files and check only the lines marked
**[R2]** below, plus everything in "What round 1 already proved".

### What round 1 already proved - do NOT redo
3 rows not 6 · code `8810` not `8810 Clerical` · FT 2/3/8 with the headcount 15 never
leaking · W1 Part 1 = CO only · W2 Part 1 = CO TX · W2 rating sheet state BLANK · the
$800,000 in W2's hard stop was DERIVED (never printed in the document) · W3 zero class
codes anywhere · W3 WC Supplemental 97% (the -3 still fires).

### The 7 fixes - what to look for now

| # | Round 1 showed | [R2] expect now |
|---|---|---|
| 1 | Neither WC table appeared in the questionnaire | **The employee-group table in the CLIENT list** and **Owners and officers in AGENCY**. Root cause: the auto-generated wording began "Please provide your ", the exact marker that routes a question out of the workflow |
| 2 | Client asked *"Provide your WC payroll breakdown by class code … (For example: 5183 Plumbing - $320,000)"* | **That question is gone from the client list.** It was a narrative slot repurposed into a classification question - principle 5 breached. The "Subcontracted %" question also no longer says "class code" |
| 3 | W1 grew a 3rd "officer" doing *Roofing installation* for *$520,000*; **W2 printed 3 officers on a package with none**, carrying $90,000 / $410,000 / $300,000; W3 showed $640,000 as an officer's pay | **The officer block carries only real officers.** W2's is empty. W1 shows exactly Dana Whitfield and Marcus Ruiz |
| 4 | PART 3 OTHER STATES repeated Part 1 (W2 "CO TX", W3 "CO" with Part 1 blank) | **PART 3 is blank** on all three |
| 5 | INCREASED LIMITS = `1,000,000` (the EL limit as a multiplier); ASSIGNED RISK SURCHARGE = the mod | **Only EXPERIENCE OR MERIT MODIFICATION carries a factor** (0.92 / 1.05). Every other factor row blank |
| 6 | W2's premium block said `STATE: CO` while the sheet above it correctly refused | **W2's premium STATE is blank too**; W1 still says CO |
| 7 | *"Policy Effective Date: documents disagree (09/17/2026, 07/13/2026)"* - a false conflict + an 85 cap on W1 AND W2 | **No Data Consistency card, no date warning.** 07/13 was the X-Mod's effective date being read as the policy's. W1 and W2 should now cap at 85 only if something else earns it |

**Score movement to expect:** W1 and W2 lose the false-conflict warning, so their SQS may
rise. W2 keeps its 60 cap - the payroll hard stop is real and is the point of that package.

---

| Package | Proves |
|---|---|
| W1 | 8.1 the whole employee-group table on the 130; 8.2 officers INC/EXC, X-Mod, subcontracting; payroll-by-state derived and AGREEING (the new hard stop must stay silent); 8.3 a compound "8810 Clerical" cell split; a duplicated rating row folded |
| W2 | two states on the form; the 10% state-total hard stop - a spec rule that has NEVER run on live data |
| W3 | 8.3 the boundary: no class table -> every code box BLANK, the table still ASKED, a producer-typed code stamps; the payroll-period -3 still fires |

Where things live: the **pre-form screen** is what you see right after upload (score,
hard stops, warnings). The **question buckets** (Client / Agency) and the **schedules
panel** appear after you generate forms, because both are built from the generated forms.

---

## Upload 1 - `W1_groups_complete_single_state.pdf`

A Colorado roofing contractor. Three employee groups, exactly the client's own 8.1
example: Clerical 2 / $100,000, Outside sales 3 / $180,000, Roofing installation 8 /
$520,000. Total payroll $800,000. Two officers, one included one excluded. Mod 0.92.

### A. Pre-form screen

1. **No WC hard stop.** The groups sum to $800,000 and the application states
   $800,000, so the new state-total rule must stay SILENT. This is the guard rail -
   a rule that fires on the ordinary case is the failure mode this codebase has hit
   four times.
2. Open **Total Package Score > Exposure Consistency**. **WC Supplemental = 100**
   (X-Mod stated, officers resolved, payroll annual) and **Operations = 100** (5551
   roofing matches the operations; 8810 and 8742 are standard exceptions and must
   not vote).

### B. Generate ACORD 125 + 130, then read the 130

3. **The classification section** (CLASS CODE / DESCRIPTION / # FULL-TIME /
   # PART-TIME / ANNUAL REMUNERATION / RATE) - three rows:

   | Code | Description | FT | PT | Remuneration |
   |---|---|---|---|---|
   | 8810 | Clerical - office and administrative | 2 | 0 | $100,000 |
   | 8742 | Outside sales | 3 | 0 | $180,000 |
   | 5551 | Roofing installation | 8 | 2 | $520,000 |

   * **THREE rows, not six.** The same rows are printed twice in the document (a
     premium summary and the rating sheet); they must fold into one set.
   * **Row 1's code box must read `8810`, not `8810 Clerical`.** The premium
     summary prints that cell combined and 8.3's normalizer splits it. Either
     wording may win the description box ("Clerical" or "Clerical - office and
     administrative") - whichever printing the extractor read first. Both are
     correct; only the CODE box is being tested here.
   * **No count box may read 15.** 15 is the company-wide headcount; the group
     counts are 2 / 3 / 8. A 15 anywhere in those columns is the old bug.
4. **The state boxes.** The "Part 1" states box reads **CO** and nothing else -
   three Colorado groups are ONE state, not three. The rating sheet's state name
   reads **Colorado**.
5. **The officers section** - Dana Whitfield / President / 60% / **INC**, and
   Marcus Ruiz / Vice President / 40% / **EXC**. Both rows carry state **CO**.

### C. The question buckets and the schedules panel

6. **Client bucket:** ONE question, *"Please provide your employee groups and
   payroll"*, rendered as a table pre-loaded with the three rows. It must show
   the columns *Employee group and what they do / Full-time / Part-time / Annual
   payroll / State* - and **NO "WC class code" column**. The class code is the
   producer's (core principle 5).
7. **What must NOT be in the client list:** *"What types of work do your employees
   perform?"*, *"Please provide your payroll broken out by state and job
   classification"*, or any *"owners or officers"* question. All three are now
   answered by a table or by the producer.
8. **Agency bucket / schedules panel:** an **Owners and officers** table with the
   two rows and the words Included / Excluded. This table must never appear in the
   client's copy - if you open the client questionnaire link, it is not there.

**Send back:** the Exposure pillar, the 130's classification + officers sections,
and a screenshot of the client bucket showing the table without a code column.

---

## Upload 2 - `W2_two_states_total_mismatch.pdf`

A plumbing contractor with Colorado and Texas payroll. The three groups sum to
$800,000; the application states a total annual payroll of **$1,150,000**.

### A. Pre-form screen

1. **A HARD STOP you have never seen before:** *"WC payroll by state totals
   $800,000 but ACORD 125 reports total payroll of $1,150,000 - 30% variance.
   Reconcile payroll totals."* The package score is capped at **60**.
   This rule has been in the code since it shipped and has never once run - it read
   a list while the data was always a dict (H3-B). **D6: this can lower the score on
   real multi-state accounts. Brent should hear it from you first.**
2. You may ALSO see *"WC payroll differs from total payroll ..."*. That is the
   pre-existing 20% rule, not the one being tested; ignore it for this check.
3. Resolve on the state-total card asks you to type the total payroll. That is
   existing behaviour and is correct - the disagreement may be in the 125 figure.

### B. Generate ACORD 125 + 130, then read the 130

4. **The Part 1 states box lists CO and TX** - the two distinct states, in row
   order, not "CO, CO, TX".
5. **The rating sheet's state name is BLANK.** The form prints one rating sheet
   and this account has two states, so no single state may be claimed. Blank and
   owned - not a guess, and not something the AI is asked to fill.
6. Three classification rows, with the full-time counts 2 / 6 / 4 and their own
   states.

**Send back:** the hard-stop card, the ceiling reason, and the 130's states box.

---

## Upload 3 - `W3_no_class_table.pdf`

A residential roofing contractor with WC coverage and **no classification schedule
anywhere**. The operations text says "residential roofing" - which is exactly the
temptation: NCCI 5551 is the obvious code, and Primble must not write it.

### A. Pre-form screen

1. **WC Supplemental shows -3** for the payroll period: the document prints a bare
   *"Payroll: $640,000"* with no period word. This is H1's rule still working after
   the H3 change (regression check).
2. X-Mod and officers are **UNKNOWN**, not missing - neither deducts. They reach the
   producer, never the client.

### B. Generate ACORD 125 + 130, then read the 130

3. **EVERY code box on the form is blank** - the classification section's code
   column, the carrier description-code column, and the class-code column in the
   officers section. This is client 8.3: Primble may extract, retain, normalize and
   compare a class code, but never generate one. **A 5551 anywhere on this form is
   a failure of the whole section.**

### C. The question buckets - and the producer step

4. **The employee-group table is still ASKED**, empty, in the client bucket. A blank
   form box must never mean "nobody is asked" - that is the defect the table exists
   to fix.
5. **The producer step (8.3 "retain producer-entered codes"):** open the schedules
   panel, type one row into **Employee groups and payroll** - description
   `Roofing installation`, full-time `9`, annual payroll `$640,000`, state `CO`, and
   in the producer-only code column `5551 Roofing`. Save.
6. Re-open the 130. The row must now print **code `5551`** and **description
   `Roofing installation`** (the compound cell split again), remuneration `$640,000`,
   full-time `9`, the Part 1 state `CO`, and the rating sheet state `Colorado`.
7. The payroll-period **-3 is now gone**: a typed annual-payroll column is annual by
   construction. The score goes UP by 3 - that is correct, not a bug.

**Send back:** the blank 130 (step 3), then the same section after the producer row
(step 6), and the WC Supplemental row before and after.

---

## What counts as a failure

* Any WC class code on a form that no document printed and no producer typed (W3).
* A group's employee count showing the company-wide headcount (W1, 15).
* Six classification rows where three were printed twice (W1).
* The client being shown a WC class code column, or the officers table (W1).
* The state-total hard stop firing on W1, where the numbers agree.
* A state name on W2's rating sheet, where two states share one form.
* The employee-group table missing from W3's question list.

## Known and expected - do not report these

* `WorkersCompensation_RateState_StateOrProvinceName_A1` (the page-2 copy of the
  sheet's state label) is still filled by the AI. Same value, different box.
* **The RATE column does not print on the 130.** ACORD marks that box read-only
  (a rate is the carrier's to compute), so it ships blank by design. An extracted
  or producer-typed rate is still retained in the data and still shows in the
  producer's table - it is preserved, not discarded.
* Officer rows print only name / title / ownership % / state / INC-EXC. Birth date,
  duties and remuneration for officers are not captured by any table yet.
* W2 may show two payroll hard stops (check 2 above).
"""


if __name__ == "__main__":
    main()
