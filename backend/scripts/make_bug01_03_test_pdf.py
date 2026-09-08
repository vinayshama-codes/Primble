"""make_bug01_03_test_pdf.py - ONE live test package for BUG-01, BUG-02, BUG-03.

    py backend/scripts/make_bug01_03_test_pdf.py

Writes `bug01_03_test_data/BUG010203_questionnaire_progress.pdf` at the repo
root, plus README-HOW-TO-TEST.md with the numbered steps.

WHAT THE THREE BUGS WERE
------------------------
BUG-01  The client questionnaire opened at "1/11 - 9%" before the client had
        answered anything, and the green "Auto-saving in progress" bar was
        already showing. Progress measured whether a field HELD content rather
        than whether the CLIENT put it there, and a schedule question ships
        PRE-FILLED with the rows extraction found. Our own pre-fill counted
        itself.
BUG-02  The green count badge rendered on the "Contact Your Agent" card instead
        of the Submit button (absolutely positioned inside the wrong parent),
        showing an unexplained "1" that read as an unread message.
BUG-03  The producer's "Send to Client (2)" badge counted unread rows in
        `arq_notifications` - written when a client SUBMITS, and queried by USER
        with no session filter - so a workspace with zero questionnaires showed
        submissions from other packages, and nothing ever marked them read.

WHY THIS FIXTURE IS SHAPED THE WAY IT IS
----------------------------------------
The whole of BUG-01 turns on ONE condition: the questionnaire must contain a
schedule question that arrives PRE-FILLED. That only happens when extraction
finds real rows, so this document carries a REAL two-vehicle fleet with VIN,
year, make and model - enough for `auto_vin_schedule` to be populated - while
leaving most ACORD 127 vehicle columns unstated so the table is still worth
asking about (`_partition_schedule_fields` rule (a)).

It also carries NO driver information at all. `_partition_schedule_fields` PASS
1b raises a table for any schedule a selected form carries when we hold none of
its rows, so ACORD 127 produces a SECOND table that is EMPTY. That pair - one
table pre-filled, one empty - is what separates the two halves of the fix:

    pre-filled + untouched  -> must NOT count   (the reported bug)
    empty      + opened     -> must NOT count   (touch alone is not an answer)
    pre-filled + emptied    -> MUST count       ("those are not our vehicles")

FOUR SCALARS ARE DELIBERATELY ABSENT so the questionnaire has ordinary questions
to answer alongside the tables - the same four the client's screenshot showed:
employee count, subcontractor percentage, annual sales, and loss history.

FIXTURE RULES (inherited from make_c6_test_pdfs.py, all proven)
---------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave.
* Dates computed from TODAY so nothing drifts into an expired-term or renewal
  path (an expired term caps the score and changes the screen under test).
* The ABSENCES are self-verified at the bottom of this file by scanning the
  generated text. One stray word - a single "employees" - silently removes a
  question and invalidates the count the tester is asked to read.
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
    "bug01_03_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")

AGENCY = "Cascade Commercial Insurance Group LLC"
CARRIER = "Sentinel Pacific Casualty Company"
INSURED = "Harborline Freight Services LLC"

# Two real vehicles. Identity columns only - year, make, model, VIN - so the
# table arrives pre-filled AND still has unstated columns worth asking about.
VEHICLES = [
    ("2019", "Freightliner", "M2 106", "1FVACWDT9KHKM4471"),
    ("2021", "Isuzu", "NPR-HD", "JALC4W164M7000318"),
]


# -- Layout helpers ----------------------------------------------------------

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


# -- The document ------------------------------------------------------------

def build(c) -> None:
    # ---- Page 1: declarations -------------------------------------------
    y = _page(c, "COMMERCIAL AUTOMOBILE POLICY - DECLARATIONS",
              f"{CARRIER}   |   Policy No. CA-4471-882-09")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", "2140 Harbor Way, Suite 300")
    y = _row(c, y, "City / State / Zip", "Tacoma, WA 98421-2207")
    y = _row(c, y, "FEIN", "91-2288417")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Dana Whitfield, 253-555-0164, dana@harborlinefreight.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "NAIC Number", "24198")
    y = _row(c, y, "Proposed Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Line of Business", "Commercial Automobile (Business Auto)")
    y = _row(c, y, "Description of Operations",
             "Regional freight hauling and local delivery of packaged dry goods")
    y = _row(c, y, "Years in Business", "11")
    y = _row(c, y, "Policy Premium", "$ 18,240")

    y = _head(c, y, "COVERAGE SUMMARY")
    y = _table(
        c, y,
        ["COVERAGE", "LIMIT", "DEDUCTIBLE"],
        [
            ["Auto Liability - Combined Single Limit", "$1,000,000", "None"],
            ["Uninsured / Underinsured Motorist", "$1,000,000", "None"],
            ["Comprehensive", "Actual Cash Value", "$1,000"],
            ["Collision", "Actual Cash Value", "$1,000"],
            ["Medical Payments", "$5,000", "None"],
        ],
        [1.0, 4.3, 6.1],
    )

    y = _head(c, y, "COVERED AUTO SYMBOLS")
    y = _para(c, y, "Auto Liability: Symbol 01 (any auto)")
    y = _para(c, y, "Comprehensive and Collision: Symbol 07 (specifically described autos)")

    # ---- Page 2: the fleet ----------------------------------------------
    # THE POINT OF THIS FIXTURE. Identity columns only, so `auto_vin_schedule`
    # is populated (table arrives pre-filled) while garaging, radius, use, cost
    # new and the rest stay unstated (table is still worth asking about).
    y = _new_page(c, "SCHEDULE OF COVERED AUTOS")
    y = _para(c, y, "Vehicles scheduled under this policy:")
    y = _table(
        c, y,
        ["YEAR", "MAKE", "MODEL", "VIN"],
        [list(v) for v in VEHICLES],
        [1.0, 1.9, 3.5, 4.9],
    )
    y = _para(c, y, "Two power units are scheduled. No trailers are scheduled under this policy.")

    y = _head(c, y, "PHYSICAL DAMAGE")
    y = _para(c, y, "Comprehensive and Collision apply to both scheduled units.")

    # ---- Page 3: the deliberate silences --------------------------------
    y = _new_page(c, "UNDERWRITING NOTES")
    y = _head(c, y, "INFORMATION OUTSTANDING AT BINDING")
    y = _para(c, y, "The following items were not supplied with this submission and")
    y = _para(c, y, "are to be obtained from the applicant before the file is complete.")
    y -= 0.10 * inch
    # Worded so the ITEM IS NAMED but no VALUE is ever stated. Naming the item
    # keeps extraction from inventing one; stating a value would delete the
    # question this fixture exists to produce.
    y = _para(c, y, "  1. Staffing level for the account.")
    y = _para(c, y, "  2. Proportion of work placed with outside firms.")
    y = _para(c, y, "  3. Revenue figure for the most recent full year.")
    y = _para(c, y, "  4. Prior claim experience for the last five years.")
    y = _para(c, y, "  5. Operator roster for the scheduled units.")

    y = _head(c, y, "CARRIER REMARKS")
    y = _para(c, y, "Terms quoted are subject to receipt of the outstanding items above.")
    y = _para(c, y, "Rating is on a per-unit basis for the two scheduled power units.")
    # Deliberately does NOT name garaging / radius / use. Even a sentence saying
    # they are unconfirmed puts those words in the document, and the extractor
    # then has a label to hang a guess on - the H1-K shape, where a prompt-level
    # prohibition was defeated by a bare label sitting next to a value.
    y = _para(c, y, "Unit-level rating detail is to be confirmed before binding.")

    c.showPage()


def _save(path: str) -> str:
    c = canvas.Canvas(path, pagesize=LETTER)
    build(c)
    c.save()
    return path


# -- Self-check --------------------------------------------------------------
#
# The absences are the fixture. A single stray word - "8 employees", one dollar
# figure on the revenue line, a driver name - deletes a question and silently
# changes the number the tester is told to read.

_MUST_CONTAIN = [
    INSURED, AGENCY, CARRIER, "91-2288417", "Tacoma", EFF, EXP,
    "Symbol 01", "Symbol 07", "1,000,000",
    # Both vehicles, whole, or there is no pre-filled table and no test.
    "1FVACWDT9KHKM4471", "JALC4W164M7000318",
    "Freightliner", "Isuzu", "2019", "2021",
]

# Case-insensitive. Each is a VALUE that, if present, satisfies a question this
# fixture needs asked. `\b` on the short ones so "employee" does not match
# inside another word and fail the build for nothing.
_MUST_NOT_MATCH = [
    (r"\bemployees?\b",                    "employee count must stay unstated"),
    (r"\bpayroll\b",                       "payroll implies a staffing figure"),
    (r"\bsubcontract",                     "subcontractor cost must stay unstated"),
    (r"\bgross sales\b",                   "annual sales must stay unstated"),
    (r"\bannual revenue\b",                "annual revenue must stay unstated"),
    (r"\bloss (?:run|history|summary)\b",  "loss history must stay unstated"),
    (r"\bno (?:known )?losses\b",          "a no-loss attestation ANSWERS the loss question"),
    (r"\bdriver\b",                        "any driver wording risks seeding the driver table"),
    (r"\bgaraged? at\b",                   "a garaging address fills a vehicle column"),
    (r"\bradius\b",                        "a radius fills a vehicle column"),
]


def _text(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(path: str) -> list:
    errs = []
    try:
        txt = _text(path)
    except Exception as ex:                                   # noqa: BLE001
        return [f"could not read back the PDF: {ex}"]

    for needle in _MUST_CONTAIN:
        if needle not in txt:
            errs.append(f"MISSING required content: {needle!r}")

    low = txt.lower()
    for pattern, why in _MUST_NOT_MATCH:
        m = re.search(pattern, low)
        if m:
            errs.append(f"FORBIDDEN {m.group(0)!r} present - {why}")

    # The fleet must read back as two WHOLE rows on one line each, or the
    # schedule is not extractable as a table and nothing arrives pre-filled.
    for year, make, model, vin in VEHICLES:
        if not re.search(rf"{year}\s+{make}\s+{re.escape(model)}\s+{vin}", txt):
            errs.append(f"vehicle row did not reflow as one line: {year} {make} {model}")
    return errs


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing to {OUT_DIR}")
    path = _save(os.path.join(OUT_DIR, "BUG010203_questionnaire_progress.pdf"))
    print(f"  wrote {os.path.basename(path)}")

    errs = _verify(path)
    if errs:
        print("\nFIXTURE SELF-CHECK FAILED:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    print("\nFixture self-check PASSED (fleet reflows as rows; every required "
          "absence verified).")

    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")


README = f"""
# BUG-01 / BUG-02 / BUG-03 live test

**One file. One form selection. About 10 minutes.**

Generated {TODAY.strftime('%Y-%m-%d')}. Policy term: {EFF} to {EXP}.

## Setup

1. Upload `BUG010203_questionnaire_progress.pdf` as a **new session**.
2. Generate **ACORD 125 + ACORD 127**.
   - 127 carries the vehicle and driver schedules. Without it there is no
     pre-filled table and the test proves nothing.
   - 125 supplies the ordinary business questions.
3. Wait for the producer workspace (the screen with the form preview and the
   SQS panel on the left).

### What the questionnaire should contain

That selection raises **four tables**, and only ONE of them arrives with
anything in it:

| Table | Comes from | Expect |
|-------|-----------|--------|
| **Vehicle schedule** | ACORD 127 | **2 rows, pre-filled** - the 2019 Freightliner and the 2021 Isuzu |
| Driver schedule | ACORD 127 | **empty** - the document names no operators |
| Location schedule | ACORD 125 | **empty** |
| Loss history / claims | ACORD 125 | **empty** |

Plus a set of ordinary typed questions (staffing, subcontracting, revenue,
claims) - the document names those items but states no values, on purpose.

**If the Vehicle schedule is empty, stop and tell me.** It is the only
pre-filled table, so it is the entire BUG-01 trigger; without it the rest of
this test proves nothing. (If the Location table happens to arrive pre-filled
too, that is fine - it just gives the same check twice. Everything below still
applies, and both tables must be uncounted at B1.)

---

## PART A - producer workspace, before sending (BUG-03)

| # | Do this | Expect |
|---|---------|--------|
| A1 | Look at the **Send to Client** button in the left panel. | **No number badge at all.** This session has sent nothing. |
| A2 | Hover the button. | Nothing claiming a count. |

> Before the fix this showed a pink badge counting *submitted questionnaires
> from every other package on your account*. If you have ever had a client
> submit anything, it read 1, 2, 3... on a session with nothing sent.

---

## PART B - the questionnaire opens (BUG-01, BUG-02)

Click **Send to Client**, send it to yourself, and open the client link.

| # | Do this | Expect |
|---|---------|--------|
| B1 | Look at the ring, top right. | **0%** and **0/N** (N = however many questions). Note N down. |
| B2 | Look under "Questions (N)". | **No** "answered / not sure / to go" line yet. |
| B3 | Look for the green **"Auto-saving in progress..."** bar. | **Not showing.** |
| B4 | Look at the floating buttons, bottom right. | **No green number badge anywhere**, and nothing on the "Contact Your Agent" card. |

> **This is the whole bug.** Before the fix: **1/11, 9%**, the auto-save bar
> already on, and a green "1" sitting on the Contact Your Agent card.

---

## PART C - answering moves it, correctly (BUG-01, BUG-02)

**The ring is exactly predictable from here on. Every number below is a hard
expectation, not a direction of travel.**

| # | Do this | Ring | Line under "Questions" |
|---|---------|------|------------------------|
| C1 | Type an answer into the **first** question. | **1/N** | `1 answered - N-1 to go` |
| C2 | Look at the **Submit** button. | green **1** badge on **its own top-right corner**, NOT on the Contact card | |
| C3 | Hover that badge. | tooltip: **"1 of N questions responded"** | |
| C4 | Tap **"I'm not sure"** on a different question. | **2/N** | `1 answered - 1 not sure - N-2 to go` |
| C5 | Clear the answer you typed in C1. | **1/N** | `0 answered - 1 not sure - N-1 to go` |
| C6 | Type it again. | **2/N** | `1 answered - 1 not sure - N-2 to go` |

Also at C1: the green **"Auto-saving in progress..."** bar appears for the first
time. It must NOT have been there at B3.

---

## PART D - the pre-filled vehicle table (BUG-01, the core case)

Scroll to **"Please confirm the vehicles"** - it already holds the 2019
Freightliner and the 2021 Isuzu.

| # | Do this | Ring | Why |
|---|---------|------|-----|
| D1 | Look at the count **without touching the table**. | **2/N** | The pre-filled table counts for nothing. |
| D1b | Look at the vehicle question's **card**. | - | Styled like every other **unanswered** question. No green treatment. If the card is green while the ring says otherwise, one of them is lying. |
| D2 | Scroll past it and back. Click on the page, change nothing. | **2/N** | Looking is not answering. |
| D3 | Change the Isuzu's **Model** from `NPR-HD` to `NPR-HD 16FT`. | **3/N** | A real edit. |
| D4 | Change it straight back to `NPR-HD`. | **3/N** | You did the work; the bar must not punish you for undoing it. |
| D5 | Delete **both** rows. | **3/N** | Deleting is an answer ("those are not our vehicles"), not an un-answer. |
| D6 | Re-type both rows exactly: `2019 / Freightliner / M2 106 / 1FVACWDT9KHKM4471` and `2021 / Isuzu / NPR-HD / JALC4W164M7000318`. | **3/N** | The case a simple before/after comparison gets wrong. |
| D7 | **Delete both rows again. Leave the table empty.** | **3/N** | Leave it this way - Part G needs it. |

> **The rule being tested: the bar never moves backwards.** D3 through D7 are
> the same number, five times running.

---

## PART E - the empty driver table (BUG-01, the other direction)

Scroll to the **driver** table. It is empty - this document names no drivers.

| # | Do this | Ring | Why |
|---|---------|------|-----|
| E1 | Add a row, then delete it. Leave the table empty. | **3/N** | Nothing pre-filled, nothing entered, nothing answered. |
| E2 | Add one row - Name `Dana Whitfield`, License Number `WDL4471882`, License State `WA`. | **4/N** | `3 answered - 1 not sure - N-4 to go` |

> D5 and E1 both leave an empty table. **D5 counts, E1 does not** - because in
> D5 the client cleared something we gave them. That is the distinction; if
> both behave the same, the fix is wrong.

---

## PART F - it survives a reload

| # | Do this | Expect |
|---|---------|--------|
| F1 | Hard-refresh the page (Ctrl+F5). | Still **4/N**. Answers and progress both restored. |
| F2 | Re-check both tables. | Vehicle table **still empty** (you emptied it at D7), driver table **still holds your E2 row**. The count did not drop even though the vehicle table is empty - that is the touch record surviving the reload. |
| F3 | Open the link in a **private / incognito** window. | Same count, same answers - the draft is server-side. |

---

## PART G - submit, and what it wrote (BUG-01, the backend half)

You are submitting with the **vehicle table emptied** (D7). That is deliberate:
it is the only step that proves a deletion actually reaches the form.

| # | Do this | Expect |
|---|---------|--------|
| G1 | Submit. | Confirmation screen with a summary. |
| G2 | Read the **vehicle** line on the summary. | **"Confirmed none - the pre-filled rows were removed"** - NOT "0 rows provided", and NOT "2 vehicles provided". |
| G3 | Read the **driver** line. | Shows the one operator you added at E2. |
| G4 | Look for the Location and Loss history tables, and any question you never touched. | **Not listed as answered.** Untouched tables must not appear as things you provided. |

> Before the fix, G2 read **"2 rows provided"** for a table the client had
> emptied - and on an untouched run it credited the client with two vehicles
> they never looked at, in the receipt AND in the audit trail.

---

## PART H - back to the producer workspace (BUG-01 + BUG-03)

| # | Do this | Expect |
|---|---------|--------|
| H1 | Return to the producer screen and hit **Refresh**. | **Sent Questionnaires** lists one row, marked **Done**. |
| H2 | Read the **"N answers submitted by client"** line on that row. | A number that **matches roughly what you actually answered** - single digits. |
| H3 | Look at the **Send to Client** button. | **No badge.** The request is completed, so nothing is open. |
| H4 | Open **ACORD 127** and find the vehicle schedule rows. | **Blank.** You told us those vehicles are not yours, so they must stop printing. |

> **H2 is its own bug.** That number was `len(posted_answers)`, and the
> questionnaire posts every question back including blanks - so it always
> equalled the total question count. If it reads the same as N from B1, the fix
> did not land.
>
> **H3 before the fix** would show **1** here, because one questionnaire had
> just been submitted and the badge counted submissions.

---

## PART I - the second questionnaire, and the cross-session leak (BUG-03)

This is the part that proves the root cause. The old badge was queried **by
user with no session filter**, so it carried in submissions from every other
package on the account.

| # | Do this | Expect |
|---|---------|--------|
| I1 | On the SAME session, send a **second** questionnaire. Back on the workspace, Refresh. | Badge shows **1**. |
| I2 | Hover it. | **"1 questionnaire still open with the client"**. |
| I3 | Open that link and submit it (answer anything). Back on the producer screen, Refresh. | Badge **gone**. Two submissions on this account now; the badge is still zero. |
| I4 | Upload the SAME pdf again as a **brand new session**. Generate 125 + 127. | On the new workspace: **no badge at all**. |

> **I4 is the reported bug, exactly.** A fresh session that has sent nothing.
> Before the fix it showed **2** - the two submissions from the first session -
> because the count was per-account, not per-session, and nothing ever marked
> them read. That is where the tester's "Sent to Client (2)" came from.

---

## What to send back

Just the numbers, in order:

**BUG-01 - the counter**
- **N** (total questions) = ______
- **B1** ring at open: ______   (must be `0/N`, `0%`)
- **C1 / C4 / C5 / C6**: ______ / ______ / ______ / ______   (expect 1 / 2 / 1 / 2)
- **D3 / D4 / D5 / D6 / D7**: ______ / ______ / ______ / ______ / ______   (expect 3, five times)
- **E1 / E2**: ______ / ______   (expect 3 / 4)
- **F1** after reload: ______   (expect 4)

**BUG-01 - what it wrote**
- **G2** vehicle line on the receipt: ______________________
- **H2** "N answers submitted by client": ______   (must NOT equal N from B1)
- **H4** ACORD 127 vehicle rows after the emptied submit: blank? ______

**BUG-02 - the badge**
- **B4** badge anywhere on open? ______   (must be: no)
- **C2** where the badge sits: ______   (must be: on Submit, not the Contact card)
- **C3** tooltip text: ______________________

**BUG-03 - the producer badge**
- **A1 / H3 / I1 / I3 / I4**: ______ / ______ / ______ / ______ / ______
  (expected: none / none / 1 / none / **none**)

Screenshots: the questionnaire header right after **B1**, the Submit button at
**C2**, and the new session's sidebar at **I4**.

## If something is off

- **Vehicle table is empty on open** - extraction missed the fleet. Send me the
  session id; the rest of the test is void without it.
- **Ring is not 0% at B1** - tell me the exact number and which questions show
  as answered.
- **Count drops at D4, D5, D6 or D7** - the regression this fixture exists to
  catch. Which step, and by how much.
- **I4 shows a number** - the cross-session leak is still there. Tell me the
  number and roughly how many client submissions the account has.

---

# RETEST (round 2, 2026-09-08)

Round 1 passed A through H. Three things changed after it; this is the short
loop that checks them. **New session, same PDF, same 125 + 127.**

## R1 - the orphaned vehicle row (NEW FIX)

Round 1 found this: the client deleted both vehicles, the form correctly blanked
year / make / model / VIN, and kept printing a **garaging address**, a **$1,000
collision deductible** and a full set of **ticked coverage boxes** for a unit
with no identity. Only 9 of ACORD 127's 67 per-vehicle fields were bound to the
table; the other 58 came from Pass 1 and answered to nobody.

| # | Do this | Expect |
|---|---------|--------|
| R1a | Open the questionnaire, **delete both vehicle rows**, submit. | - |
| R1b | Producer screen, open **ACORD 127**, VEHICLE DESCRIPTION. | Row 1 and row 2 **completely empty**: no year, make, model, VIN, **no garaging address, no city/state/zip, no deductibles, no ticked coverage boxes**. |
| R1c | Check the rest of the form. | **NAMED INSURED, AGENCY, CARRIER, POLICY NUMBER and the DRIVER row are all still there.** Only the vehicle rows were swept. |

> R1c is the safety check, and it matters more than R1b. `NamedInsured_A` is the
> APPLICANT, not a schedule row - a sweep that went by row letter alone would
> erase the insured's name off a legal form.

## R2 - keep one vehicle, delete the other

| # | Do this | Expect |
|---|---------|--------|
| R2a | New questionnaire. Delete **only the Isuzu**, keep the Freightliner. Submit. | - |
| R2b | Open ACORD 127. | Row 1 keeps **everything** - year, make, model, VIN, **and** its garaging address, deductibles and coverage ticks. Row 2 is **completely empty**. |

## R3 - the badge hover (BUG-03 follow-up)

| # | Do this | Expect |
|---|---------|--------|
| R3a | With a questionnaire still unanswered, hover **anywhere on the Send to Client button**. | A dark bubble, **instantly** - same look as the SQS "i" tooltips: **"Your client hasn't answered 2 questionnaires yet."** |
| R3b | Watch how fast it appears. | **No delay.** The old one was a browser `title` with its built-in ~1s wait. |
| R3c | Check where it renders. | **Above** the button, not below - the button sits at the bottom of the sidebar, so it flips rather than going off-screen. |
| R3d | With nothing open, hover the button. | **"Your client has answered everything you sent."** |
| R3e | Hover an **"i"** icon on the SQS pillars. | Works exactly as before - same instant dark bubble. It shares one implementation with R3a now, so check it did not regress. |

## R4 - the progress breakdown moved (BUG-01 follow-up)

It was a third line of grey text under two other grey lines. It is now three
coloured chips in the dark header, beside the ring they explain.

| # | Do this | Expect |
|---|---------|--------|
| R4a | Open a questionnaire, answer one question, mark another "I'm not sure". | In the **dark header**, under "Expires:": a green **"1 answered"** chip, an amber **"1 not sure"** chip, a grey **"N-2 to go"** chip. |
| R4b | Look under "Questions (N)". | The old grey line is **gone** - not duplicated. |
| R4c | On first open, before answering anything. | **No chips at all.** |

## R5 - the one number I still need explained

Round 1, page 5: after typing an invalid year (`2122`) and correcting it back to
`2019`, the badge read **1** where every step either side read **3**. Every
other reading in that run was correct and there is no code path that drops it,
so I think that screenshot was a second browser window - but I am not assuming.

| # | Do this | Expect |
|---|---------|--------|
| R5a | In ONE window: answer a question, mark another "I'm not sure", edit a vehicle cell. | Badge **3**. |
| R5b | Type `2122` into a Year cell. | Row shows "Year must be a 4-digit year". Badge **still 3**. |
| R5c | Correct it back to `2019`. | Badge **still 3**. |

**If R5c shows anything other than 3, screenshot it with the whole browser
window visible** - that is a real regression and I need to see it.

## R6 - the one step never run

**I4 from round 1 was skipped, and it is the only proof of BUG-03's root cause.**

| # | Do this | Expect |
|---|---------|--------|
| R6a | Upload the same PDF as a **brand new session**. Generate 125 + 127. | On that new workspace: **no badge on Send to Client at all.** |

> Your account now has several submitted questionnaires. Before the fix the
> badge query was `WHERE user_id = $1` with **no session filter**, so this fresh
> session would inherit all of them and show a number. That is precisely the
> tester's "Sent to Client (2)" on a session that had sent nothing.

## Report back

```
R1b vehicle rows fully empty?          ____
R1c insured / agency / driver intact?  ____
R2b row 1 complete, row 2 empty?       ____
R3a button hover text                  ____________________
R3b instant, no delay?                 ____
R3c renders ABOVE the button?           ____
R3e SQS "i" tooltips still fine?       ____
R4a three chips in the header?         ____
R5a / R5b / R5c badge                  __ / __ / __   (expect 3 / 3 / 3)
R6a new session badge                  ____   (expect none)
```

---

## What this does NOT cover, and why

Honest list, so nobody reads a green run as more than it is:

- **An expired questionnaire link.** `isOpenArq` excludes expired requests from
  the badge, but the link lives 8 hours - not testable in a 10-minute run.
  Covered by unit test instead (`arqStatus`, the expiry boundary to the second).
- **A malformed or partial submit payload.** The server ignores a `touched`
  list it was not sent and re-derives the answer from its own copy of the
  pre-filled rows; a missing table is never read as a deletion. Not reachable
  from the UI - covered by `tests/test_questionnaire_progress_20260908.py`.
- **Producer-only tables (owners / officers).** Never rendered to the insured,
  so there is no live path. Same test file.
- **The audit trail.** An untouched pre-filled table no longer writes a
  `client_arq` row claiming the insured supplied it. Visible only in
  `field_source_audit`, not on screen. Ask me if you want that checked in the
  database after your run.
"""


if __name__ == "__main__":
    main()
