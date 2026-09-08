"""make_bug05_test_pdfs.py - live test kit for BUG-05 (remediation actions
returning Network / unsupported-action errors). Every fix and every edge case,
in TWO packages.

    py backend/scripts/make_bug05_test_pdfs.py

Writes to bug05_test_data/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks, the exact steps, and what to send back.

TWO packages, ONE file each, each its OWN session (a different company every
time, so extraction caches and identity matching never bleed).

  A  HALVORSEN RIDGE MILLWORK   every card that was broken, plus the PROPERTY
     ACORD 125 / 127 / 130 /    60-cap blocker that used to print to a broker
     140                        as the words "Property integrity gate"

  B  THISTLE HOLLOW COOPERAGE   the controls - a populated fleet and class-code
     ACORD 125 / 127 / 130 /    schedule that must survive, a card that
     131                        legitimately cannot be typed, ordinary typed
                                cards that must not regress - plus the UMBRELLA
                                60-cap blocker

WHY TWO AND NOT ONE
-------------------
Two hard constraints force a split, and they are orthogonal, so two is the
floor:

  1. A schedule card only fires when the schedule is ABSENT. Proving "the card
     opens a table instead of a text box" needs an EMPTY fleet; proving "the
     extracted rows are never destroyed" needs a POPULATED one. One document
     cannot be both.
  2. `_gate_hard_reason` is a ladder - COPE, then umbrella, then property - so
     an umbrella pillar at 0 SHADOWS the property sentence on every form in the
     package. The two blockers cannot be read in one submission.

Each package therefore carries one side of (1) and one side of (2).

Design rules (inherited from make_c6_test_pdfs.py, all proven)
------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY so nothing drifts into an expired-term or renewal
  path (either would raise an unrelated stop and muddy the read).
* Every package's ABSENCES are self-verified at the bottom of this file by
  scanning the generated text - one stray word silently invalidates a check.
* FIXTURE RULE (learned building this): the umbrella pillar reaches 0 two ways
  and the two print DIFFERENT sentences. No underlying limits at all -> "no
  underlying GL or Auto limits". Underlying limits stated but below the
  client-approved baselines with no stated umbrella limit -> "supporting detail
  is incomplete". B uses the second, because it is the case where the old
  wording was simply false.
* FIXTURE RULE 2: A's COPE detail is COMPLETE on purpose. "Minimum Viable COPE"
  sits ABOVE property in the same ladder and would print instead.
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
    "bug05_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Northgate Insurance Partners LLC"
CARRIER = "Meridian Casualty Insurance Company"


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


def _new_page(c, title):
    c.showPage()
    return _page(c, title)


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


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp, yib,
               naics, entity="Limited Liability Company"):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    if fein:
        y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", entity)
    y = _row(c, y, "Contact", f"{contact}, {phone}, {email}")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Proposed Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", sales)
    y = _row(c, y, "Number of Employees", emp)
    y = _row(c, y, "Years in Business", yib)
    if naics:
        y = _row(c, y, "NAICS Code", naics)
    return y


def _gl(c, y, policy, occ="$1,000,000", agg="$2,000,000", form="Occurrence"):
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Coverage Form", form)
    y = _row(c, y, "Each Occurrence Limit", occ)
    y = _row(c, y, "General Aggregate Limit", agg)
    y = _row(c, y, "Annual Premium", "$9,640")
    return y


def _auto(c, y, policy, csl, covered):
    y = _head(c, y, "COVERAGE - BUSINESS AUTO")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Combined Single Limit", csl)
    y = _row(c, y, "Covered Autos", covered)
    return y


def _wc(c, y, policy):
    y = _head(c, y, "COVERAGE - WORKERS COMPENSATION AND EMPLOYERS LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Employers Liability", "$1,000,000 / $1,000,000 / $1,000,000")
    return y


def _lines(c, y, text):
    return _row(c, y, "Lines of Business Requested", text)


def _save(name, draw):
    path = os.path.join(OUT_DIR, name)
    c = canvas.Canvas(path, pagesize=LETTER)
    draw(c)
    c.showPage()
    c.save()
    return path


# ═════════════════════════════════════════════════════════════════════════════
# A - HALVORSEN RIDGE MILLWORK
#     every card that was broken, plus the property 60-cap blocker
#
#   Business Auto, NO vehicle schedule   -> "Open the table" (was a text box
#                                            whose value wiped the fleet)
#   Workers Comp, NO class codes         -> "Open the table" (same)
#   A two-topic narrative                -> the narrative card (was refused
#                                            with "can't be answered directly")
#   No loss history, no loss runs        -> the loss dropdown card (was
#                                            "Network error. Please try again.")
#   Business income with no agreed term  -> the property gate, which used to
#                                            print as "Property integrity gate"
#
# DELIBERATE ABSENCES, self-verified below: no VIN, no vehicle year/make/model,
# no WC class code, no remuneration column, NO UMBRELLA (it would shadow the
# property sentence) and no wording that states a business-income term.
# ═════════════════════════════════════════════════════════════════════════════
A_NAME = "HALVORSEN RIDGE MILLWORK LLC"


def a_broken_cards_and_property_cap(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability, Business Auto, Workers Compensation, Property")
    y = _applicant(
        c, y, A_NAME, "2140 Fernhill Road, Eugene OR 97402", "93-2210884",
        "Ingrid Halvorsen", "(541) 555-0172", "ingrid@halvorsenridge.example",
        "Custom architectural millwork fabrication and installation",
        "$4,180,000", "24", "16", "321918")
    y = _lines(c, y, "General Liability, Business Auto, Workers Compensation, Property")

    # A narrative covering only TWO of the twelve components, so the Narrative
    # Quality card fires and names the rest.
    y = _head(c, y, "ACCOUNT NARRATIVE")
    y = _para(c, y, "Halvorsen Ridge Millwork fabricates custom architectural millwork for")
    y = _para(c, y, "commercial interiors and installs it on site. The shop has operated from the")
    y = _para(c, y, "same Eugene facility since 2009 under continuous family ownership.")

    y = _gl(c, y, "MCI-GL-771402")
    y = _auto(c, y, "MCI-CA-771403", "$1,000,000",
              "Owned autos, hired autos and non-owned autos")
    y = _para(c, y, "A schedule of owned vehicles was not supplied with this application.")

    y = _new_page(c, "WORKERS COMPENSATION AND PROPERTY SECTIONS")
    y = _wc(c, y, "MCI-WC-771404")
    y = _row(c, y, "Governing State", "OR")
    y = _para(c, y, "A rating worksheet listing the individual classifications was not supplied.")

    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "MCI-CP-771405")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")

    # COPE COMPLETE on purpose - the COPE gate outranks the property gate and
    # would print instead.
    y = _head(c, y, "LOCATION AND CONSTRUCTION DETAIL")
    y = _row(c, y, "Location 1", "2140 Fernhill Road, Eugene OR 97402")
    y = _row(c, y, "Occupancy", "Millwork shop and finished-goods warehouse")
    y = _row(c, y, "Construction Type", "Non-Combustible")
    y = _row(c, y, "Year Built", "2004")
    y = _row(c, y, "Roof Updated", "2018")
    y = _row(c, y, "Sprinkler System", "Yes - wet pipe throughout")
    y = _row(c, y, "Fire Protection Class", "4")
    y = _row(c, y, "Distance to Hydrant", "180 feet")
    y = _row(c, y, "Fire Department", "Paid municipal")

    y = _head(c, y, "LIMITS AND VALUATION")
    y = _row(c, y, "Building Value", "$3,750,000")
    y = _row(c, y, "Business Personal Property", "$410,000")
    y = _row(c, y, "Valuation Method", "Replacement Cost")
    y = _row(c, y, "Coinsurance", "90%")
    y = _row(c, y, "All Other Perils Deductible", "$5,000")
    y = _row(c, y, "Deductible Basis", "Per occurrence")

    y = _head(c, y, "TIME ELEMENT")
    y = _row(c, y, "Business Income Limit", "$450,000")
    y = _para(c, y, "The time-element recovery window has not yet been agreed with the")
    y = _para(c, y, "insured and is not stated on this application.")

    y = _head(c, y, "LOSS HISTORY")
    y = _para(c, y, "No loss runs are attached to this submission.")
    return y


# ═════════════════════════════════════════════════════════════════════════════
# B - THISTLE HOLLOW COOPERAGE
#     the controls, plus the umbrella 60-cap blocker
#
#   A POPULATED fleet and class-code schedule -> those two cards must NOT
#       appear, and opening either table must show the extracted rows. The
#       data-destruction guard, from the safe direction.
#   Loss runs requested AND PENDING           -> a card no typed value can
#       close: a dismiss-with-reason control and an honest sentence, never a
#       box that gets rejected.
#   NO FEIN and NO NAICS                      -> ordinary typed cards, which
#       must still apply exactly as they did before (the regression control).
#   Umbrella requested, limit NOT stated,     -> the umbrella gate. Underlying
#       underlying below the baselines            IS stated, so the reason must
#                                                 read "supporting detail is
#                                                 incomplete", never "no
#                                                 underlying GL or Auto limits".
#
# DELIBERATE ABSENCES, self-verified below: no FEIN, no NAICS, no stated
# umbrella limit, and NO PROPERTY (a second cap only makes the read harder).
# ═════════════════════════════════════════════════════════════════════════════
B_NAME = "THISTLE HOLLOW COOPERAGE INC"


def b_controls_and_umbrella_cap(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              f"{AGENCY} - General Liability, Business Auto, Workers Compensation, Umbrella")
    y = _applicant(
        c, y, B_NAME, "1209 Alder Street, Boise ID 83702", "",   # FEIN absent on purpose
        "Sylvie Nakamura", "(208) 555-0138", "snakamura@thistlehollow.example",
        "Oak barrel cooperage - manufacture, charring and distribution",
        "$6,930,000", "38", "22", "", entity="Corporation")      # NAICS absent on purpose
    y = _lines(c, y, "General Liability, Business Auto, Workers Compensation, Commercial Umbrella")

    y = _head(c, y, "ACCOUNT NARRATIVE")
    y = _para(c, y, "Thistle Hollow Cooperage manufactures oak barrels for distilleries and")
    y = _para(c, y, "wineries across the Pacific Northwest. Operations have run for 22 years")
    y = _para(c, y, "under founder Sylvie Nakamura, who has 30 years in the trade. The plant")
    y = _para(c, y, "runs a written safety programme with monthly toolbox meetings, machine")
    y = _para(c, y, "guarding audits and a return-to-work policy. Prior coverage was placed")
    y = _para(c, y, "with Cascade Mutual; the account is being marketed for premium reasons.")

    # UNDERLYING BELOW THE CLIENT-APPROVED BASELINES, and plainly stated. This
    # is what drives the umbrella pillar to zero on a package that DOES carry
    # underlying limits - the case the old wording described falsely.
    y = _gl(c, y, "MCI-GL-882513", occ="$300,000", agg="$600,000")
    y = _auto(c, y, "MCI-CA-882514", "$300,000",
              "Owned autos, hired autos and non-owned autos")

    y = _head(c, y, "SCHEDULE OF VEHICLES")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW"],
               [["2021", "Ford", "F-250", "1FT7W2BT5MED12345", "10,000"],
                ["2019", "Isuzu", "NPR", "JALC4W163K7001234", "14,500"],
                ["2022", "Ram", "3500", "3C63RRHL8NG155201", "12,300"]],
               [1.0, 1.8, 2.7, 3.7, 6.0])

    y = _new_page(c, "WORKERS COMPENSATION, UMBRELLA AND LOSS INFORMATION")
    y = _wc(c, y, "MCI-WC-882515")

    y = _head(c, y, "WORKERS COMPENSATION CLASS CODES")
    y = _table(c, y, ["STATE", "CLASS CODE", "DESCRIPTION", "ANNUAL REMUNERATION"],
               [["ID", "2841", "Woodenware Manufacturing", "$2,410,000"],
                ["ID", "8810", "Clerical Office Employees", "$500,000"]],
               [1.0, 1.9, 3.1, 5.6])

    y = _head(c, y, "COVERAGE - COMMERCIAL UMBRELLA LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "MCI-UM-882516")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _para(c, y, "Umbrella coverage is requested. The amount to be quoted is still under")
    y = _para(c, y, "discussion with the insured and is not stated on this application.")

    y = _head(c, y, "LOSS HISTORY")
    y = _para(c, y, "Loss runs have been requested from the prior carrier and are pending.")
    y = _para(c, y, "The agency will forward them on receipt.")
    return y


# ═════════════════════════════════════════════════════════════════════════════
# Self-verification - a stray word silently invalidates a check
# ═════════════════════════════════════════════════════════════════════════════

def _text_of(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


# (package, must be PRESENT, must be ABSENT)
_EXPECT = {
    "A_halvorsen_ridge_millwork.pdf": (
        [A_NAME, "Business Auto", "Workers Compensation", "Combined Single Limit",
         "Employers Liability", "Business Income Limit", "$450,000",
         "Building Value", "Replacement Cost", "Coinsurance", "Sprinkler System"],
        # The two schedule cards only fire when the schedules are ABSENT; the
        # property sentence only prints when no umbrella outranks it; and the
        # gate itself needs the indemnity term unstated.
        [r"\bVIN\b", r"\b1FT7W2", r"\bCLASS CODE\b", r"\bREMUNERATION\b", r"\b8810\b",
         r"[Uu]mbrella", r"[Pp]eriod of [Rr]estoration", r"[Ii]ndemnity [Pp]eriod"],
    ),
    "B_thistle_hollow_cooperage.pdf": (
        [B_NAME, "1FT7W2BT5MED12345", "JALC4W163K7001234", "3C63RRHL8NG155201",
         "2841", "8810", "requested from the prior carrier and are pending",
         "Umbrella", "$300,000", "$600,000", "Self-Insured Retention"],
        # No FEIN / NAICS - those are the ordinary typed cards. No stated
        # umbrella limit - that is the gap the gate is about. No property - a
        # second cap only makes the read harder.
        [r"\bFEIN\b", r"\bNAICS\b", r"Umbrella Limit",
         r"Building Value", r"Business Income"],
    ),
}


def _verify(paths: dict) -> list:
    problems = []
    for name, path in paths.items():
        want_present, want_absent = _EXPECT[name]
        text = _text_of(path)
        for token in want_present:
            if token not in text:
                problems.append(f"{name}: MISSING required text {token!r}")
        for pattern in want_absent:
            hit = re.search(pattern, text)
            if hit:
                problems.append(f"{name}: must NOT contain {pattern!r} (found {hit.group(0)!r})")
    return problems


# ═════════════════════════════════════════════════════════════════════════════

README = """# BUG-05 live test kit

**Two packages, 13 checks.** Upload them **one at a time, each as its own new
submission** - different companies, so nothing bleeds between sessions.

| Package | Generate these forms | What it proves |
|---|---|---|
| **A** `A_halvorsen_ridge_millwork.pdf` | **ACORD 125, 127, 130, 140** | every card that was broken + the property 60-cap blocker |
| **B** `B_thistle_hollow_cooperage.pdf` | **ACORD 125, 127, 130, 131** | the controls (nothing may regress) + the umbrella 60-cap blocker |

Send back the check numbers that failed, with a screenshot. If they all pass,
just say so.

---

# PACKAGE A - `A_halvorsen_ridge_millwork.pdf`

Upload it, work through the pre-form screen, generate **ACORD 125, 127, 130 and
140**, then open the right-hand SQS panel.

### 1. The loss card no longer answers "Network error"
On **ACORD 125**, the card *"No loss history provided - required for carrier
submission"*. It has a **dropdown**, not a text box.

- Pick any answer -> **Submit**.
- **PASS:** the card flips to **Resolved**.
- **FAIL:** any red text, especially *"Network error. Please try again."*

### 2. The narrative card accepts an answer
Same panel, the card starting *"Narrative is missing ..."* / *"Narrative
includes ..."*.

- **PASS:** it shows a **multi-line box** (about three rows tall), not a
  one-line input.
- Type a couple of sentences - e.g. *"Payroll is $2.9M across 24 employees at
  one location. The experience modification is 0.94. Class code 2802 governs
  the operation."* -> **Submit**.
- **PASS:** the card flips to **Resolved**. It must **NOT** say *"This item
  can't be answered directly."*
- Answer it a **second time** with different text.
  **PASS:** the second answer is ADDED - the first is still there.
- Download the package and open **ACORD 101**.
  **PASS:** both of your paragraphs are in the Additional Remarks.

### 3. The vehicle card opens a table, not a text box
On **ACORD 127**, the card *"Provide a vehicle schedule (VIN, year,
make/model)"*.

- **PASS:** it shows a button reading **"Open the table"**. There is **no**
  "Type your answer..." box on this card.
- Click it. **PASS:** the schedule editor opens with VIN / Year / Make / Model
  columns and an Add Row control.
- Add **two** rows (e.g. 2013 Ford F-150 `1FTFW1ET5DFA12345`, and 2018 Isuzu NPR
  `JALC4W164J7000123`) -> **Save**.
- **PASS:** the card closes and both vehicles appear on the ACORD 127.
- **Now re-open the table.** **PASS:** both rows are still listed.
  **FAIL (serious):** the table is blank, or a row has been replaced by a
  sentence.

### 4. The WC class-code card does the same
On **ACORD 130**, the card asking for WC class codes.

- **PASS:** **"Open the table"**, not a text box.
- Add a row (state OR, code 2802, description "Wood Products Mfg", payroll
  $1,900,000) -> **Save**.
- **PASS:** the row lands on the ACORD 130.

### 5. The property blocker no longer prints our internal rule name
Open **ACORD 140**. It is held at **60**, with a red **HARD STOPS** block at the
top of the panel.

- **PASS:** it reads *"Business income limit present but period of restoration
  not specified"*.
- **FAIL - this is the exact bug:** it reads **"Property integrity gate"** or
  **"Property integrity warning"**.
- **PASS:** there is an **Open to fix** button on that line.
- Click it -> a **dropdown** of indemnity periods (3 / 6 / 9 / 12 / 18 / 24
  months). Pick **12 months** -> **Apply**.
- **PASS:** it applies, the hard stop clears and the 60 lifts. Note the score
  before and after.

### 6. The same gap reads as a WARNING on the other three forms
ACORD 125 / 127 / 130 are capped at **85**, not 60, by the same business-income
gap.

- **PASS:** the same plain-English sentence, with a control there too.
- **PASS:** once you answer check 5, it clears on all four forms.

### 7. Nothing anywhere is a dead end
Scroll the whole panel on each of the four forms.

- **PASS:** every card and every red line either has a control (dropdown / box /
  table button / Open to fix / Resolve / Dismiss) or a short grey sentence
  saying why there is nothing to type.
- **FAIL:** any box that gets rejected when you submit it, or any blocker with
  nothing at all underneath it.

---

# PACKAGE B - `B_thistle_hollow_cooperage.pdf`

Fresh submission. Generate **ACORD 125, 127, 130 and 131**.

This package already has a real 3-vehicle fleet and a real WC class-code
schedule in the document.

### 8. The extracted tables are there, and opening one does not wipe them
- **PASS:** there is **no** "Provide a vehicle schedule" card and **no** WC
  class-code card - the data is already in.
- Open **ACORD 127**: three vehicles printed
  (`1FT7W2BT5MED12345`, `JALC4W163K7001234`, `3C63RRHL8NG155201`).
- Open **ACORD 130**: class codes 2841 and 8810 with their payrolls.
- **The important one:** anywhere the vehicle schedule can be opened (a
  warning's *Open to fix*, or the client questionnaire table), open it.
  **PASS:** all three rows are listed. **FAIL (serious):** the table is empty,
  or a row has been replaced by a sentence.

### 9. A card that genuinely cannot be typed says so
On **ACORD 125**, the card *"Loss runs requested / pending - update score when
received"*.

- **PASS:** there is **no** "Type your answer..." box. There is a
  **"Select a reason (optional)..."** dropdown and a **Dismiss** button.
- **PASS:** a short grey sentence underneath explains that this one has no
  single value to fill and needs a document or a dismissal.
- Dismiss it with a reason. **PASS:** it moves to Reviewed and the credit
  applies.

### 10. Ordinary typed cards still work (the regression control)
This package has **no FEIN and no NAICS code** on purpose.

- Find the FEIN card. **PASS:** it is a normal typed box.
- Type `82-4471903` -> **Submit**. **PASS:** Resolved, and the FEIN appears on
  the ACORD 125.
- Do the same for another ordinary card (employee count, NAICS, entity type).
  **PASS:** all behave exactly as they always did.
- *(This package is capped at 60 by check 11, so watch the value landing on the
  FORM rather than the headline score here.)*

### 11. The umbrella blocker names the real cause and can be fixed
Open **ACORD 131**. Held at **60**, red **HARD STOPS** block at the top.

- **PASS:** it reads *"Umbrella coverage is present but its supporting detail is
  incomplete - umbrella limit, underlying limits, schedule of underlying
  insurance and follow-form status"*.
- **FAIL:** it claims *"Umbrella present with no underlying GL or Auto limits"*
  - this package plainly states both ($300,000 GL each occurrence, $300,000 auto
  combined single limit). That false sentence is one of the things this fix
  corrected.
- **PASS:** there is an **Open to fix** button.
- Click it, enter an umbrella limit of `$5,000,000` -> **Apply**.
- **PASS:** it applies and the panel refreshes.
- **PASS:** the same hard stop, with the same control, appears on ACORD 125 /
  127 / 130 too - it is a package-level problem.

### 12. Warnings and hard stops keep their controls after a Reopen
On the **pre-form screen** (before you generate), in Warnings:

- Open any warning's **Open to fix** and apply a value.
- Then hit **Reopen** on that same row.
- **PASS:** the row comes back as a proper card with its buttons intact.
- **FAIL:** the row turns into plain text with no buttons, or the counts in the
  banner header stop matching the cards below it.

### 13. Nothing anywhere is a dead end (second pass)
Same as check 7, across all four forms in this package.

---

## What to send back

For each numbered check: **PASS** or **FAIL**. For a FAIL, a screenshot and the
exact wording on screen. Also flag anything that behaves differently from how it
did before, even if it is not on this list.
"""


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    # Remove the earlier four-package kit so nobody tests a stale file.
    for stale in ("P1_halvorsen_ridge_millwork.pdf", "P2_thistle_hollow_cooperage.pdf",
                  "P3_kestrel_landing_properties.pdf", "P4_bramblegate_storage_partners.pdf"):
        old = os.path.join(OUT_DIR, stale)
        if os.path.exists(old):
            os.remove(old)

    paths = {
        "A_halvorsen_ridge_millwork.pdf": _save("A_halvorsen_ridge_millwork.pdf",
                                                a_broken_cards_and_property_cap),
        "B_thistle_hollow_cooperage.pdf": _save("B_thistle_hollow_cooperage.pdf",
                                                b_controls_and_umbrella_cap),
    }
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(README)

    print(f"Wrote {len(paths)} packages to {OUT_DIR}")
    for name in paths:
        print(f"  - {name}")
    print("  - README-HOW-TO-TEST.md")

    problems = _verify(paths)
    print()
    if problems:
        print("SELF-VERIFICATION FAILED:")
        for p in problems:
            print(f"  {p}")
        raise SystemExit(1)
    print("SELF-VERIFICATION PASSED - every required value is present and every")
    print("deliberate absence really is absent.")


if __name__ == "__main__":
    main()
