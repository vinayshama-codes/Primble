"""make_ux05_test_pdf.py - ONE PDF that makes four "form is missing" validations
fire, so UX-05's Add-form action can be tested end to end.

    py backend/scripts/make_ux05_test_pdf.py

Writes ux05_test_data/ at the repo root: one PDF plus README-HOW-TO-TEST.md.

WHY ONE DOCUMENT IS ENOUGH HERE
-------------------------------
Unlike the BUG-05 kit, nothing in this feature needs two packages. All four
missing-form rules read INDEPENDENT signals off the same dec page, and none of
them is satisfied by another's absence:

    contractor_missing_acord186                 <- is_contractor + ACORD 126 selected
    certificate_requested_but_acord25_missing   <- a certificate holder
    property_evidence_requested_but_acord28_missing <- a mortgagee / loss payee
    acord101_required                           <- >2 real prior claims

THE ONE THING THAT MAKES THIS TESTABLE
--------------------------------------
Pre-generation, the cross-form trigger set is the RECOMMENDED forms
(extraction_pipeline: "`triggered_ids` here is the RECOMMENDED forms - nothing
is selected yet"), and this document recommends all four. So the warnings will
NOT be on the pre-form Review screen - and that is correct, not a bug.

They appear AFTER generation, when the trigger set becomes what the producer
actually SELECTED. That is also exactly the surface UX-05 is about: the editor,
where until now there was no route back to the form list at all.

FIXTURE RULES (each one is a way this document could silently stop working)
--------------------------------------------------------------------------
1. `is_contractor` is gated in the extraction prompt on the INSURED'S PRIMARY
   BUSINESS, and explicitly NOT on trades named in loss history or in a
   certificate holder's requirements. So the loss-run descriptions below are
   deliberately trade-neutral ("water damage", "premises maintenance") and
   the operations sentence names the trade outright.
2. `num_claims` needs REAL claim data (extraction RULE 12b: a loss run, dates,
   amounts - never derived from a premium or a limit). Hence a four-row loss run
   with dates and incurred amounts, and no "no known losses" sentence anywhere.
3. NO umbrella, NO vehicles, NO workers comp payroll and NO builders risk, and
   subcontracting is 25% - under the 30% that would fire the high-subcontracting
   hard stop if the WC gate ever moved. Every other add-a-form rule is gated on ACORD 130 / 140 / 131 being selected, so
   leaving those exposures out keeps the result to exactly four offers. A fifth
   would still be correct, but this kit is meant to be READ.
4. An operations description IS present. Without one, `gl_codes_no_operations`
   fires and adds a fifth ACORD 101 offer for a different reason.
5. Dates run from TODAY, so nothing drifts into the expired-term or renewal
   paths - either would raise an unrelated hard stop and muddy the read.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "ux05_test_data")

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")

INSURED = "Kestrel Ridge Builders LLC"
AGENCY = "Northgate Insurance Partners LLC"
CARRIER = "Meridian Casualty Insurance Company"

# >300 chars, so the ACORD 101 advisory has a second, independent trigger
# alongside the loss count. Names the trade plainly for `is_contractor`.
OPS = (
    "Kestrel Ridge Builders LLC is a licensed general contracting firm performing "
    "commercial tenant improvement and light structural renovation work. The "
    "applicant self-performs framing, drywall and finish carpentry and retains "
    "licensed subcontractors for mechanical, electrical and plumbing scopes. All "
    "work is performed at commercial premises within a fifty mile radius of the "
    "principal office. No work is performed above three stories and no demolition "
    "of load bearing structures is undertaken."
)


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


def _wrap(c, y, text, width=96):
    c.setFont("Helvetica", 9)
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            c.drawString(1 * inch, y, line)
            y -= 0.19 * inch
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        c.drawString(1 * inch, y, line)
        y -= 0.19 * inch
    return y - 0.06 * inch


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


# ── The document ────────────────────────────────────────────────────────────

def build_pdf(path: str) -> None:
    c = canvas.Canvas(path, pagesize=LETTER)

    # Page 1 - applicant + GL declarations
    y = _page(c, "COMMERCIAL LINES DECLARATIONS",
              f"{CARRIER}  |  Policy No. MCI-CGL-4471902")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", "418 Kestrel Ridge Road, Suite 200, Asheville, NC 28803")
    y = _row(c, y, "FEIN", "47-3391085")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Dana Whitfield, (828) 555-0142, dana@kestrelridgebuilders.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Annual Gross Sales", "$4,850,000")
    y = _row(c, y, "Number of Employees", "26")
    y = _row(c, y, "Years in Business", "14")

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _wrap(c, y, OPS)

    y = _head(c, y, "COMMERCIAL GENERAL LIABILITY - COVERAGE PART")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Personal & Advertising Injury Limit", "$1,000,000")
    y = _row(c, y, "Damage to Premises Rented", "$100,000")
    y = _row(c, y, "General Liability Deductible", "$1,000")
    y = _row(c, y, "General Liability Premium", "$38,450")

    y = _head(c, y, "GENERAL LIABILITY CLASSIFICATION SCHEDULE")
    y = _table(
        c, y,
        ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE"],
        [["91340", "Carpentry - interior commercial", "Payroll", "$1,240,000"],
         ["91585", "Contractors - subcontracted work", "Cost", "$960,000"]],
        [1.0, 2.3, 5.2, 6.4],
    )
    y = _row(c, y, "Percentage of Work Subcontracted", "25%")

    # Page 2 - property, interested parties, loss run
    c.showPage()
    y = _page(c, "COMMERCIAL PROPERTY - COVERAGE PART",
              f"{CARRIER}  |  Policy No. MCI-CGL-4471902")
    y = _row(c, y, "Location 1", "418 Kestrel Ridge Road, Asheville, NC 28803")
    y = _row(c, y, "Building Limit", "$1,750,000")
    y = _row(c, y, "Business Personal Property Limit", "$425,000")
    y = _row(c, y, "Valuation", "Replacement Cost")
    y = _row(c, y, "Coinsurance", "90%")
    y = _row(c, y, "All Other Perils Deductible", "$5,000")
    y = _row(c, y, "Property Premium", "$21,300")

    # FIRES property_evidence_requested_but_acord28_missing.
    y = _head(c, y, "MORTGAGEE / LOSS PAYEE")
    y = _row(c, y, "Mortgagee", "Blue Ridge Community Bank, NA")
    y = _row(c, y, "Mortgagee Address", "1900 Hendersonville Road, Asheville, NC 28803")
    y = _row(c, y, "Loan Number", "BRC-0092214")
    y = _wrap(c, y, "Evidence of commercial property insurance is required to be "
                    "furnished to the mortgagee at each renewal.")

    # FIRES certificate_requested_but_acord25_missing. Trade-neutral wording on
    # purpose - naming a construction trade here would fight fixture rule 1.
    y = _head(c, y, "CERTIFICATE HOLDER")
    y = _row(c, y, "Certificate Holder", "Ridgeline Commercial Properties LP")
    y = _row(c, y, "Certificate Holder Address", "77 Patton Avenue, Floor 4, Asheville, NC 28801")
    y = _wrap(c, y, "A certificate of insurance is required to be issued to the "
                    "certificate holder naming them as additional insured per "
                    "written contract.")

    # FIRES acord101_required (num_claims = 4 > 2). Descriptions deliberately
    # carry NO construction-trade vocabulary.
    y = _head(c, y, "LOSS HISTORY - PRIOR FIVE YEARS")
    y = _table(
        c, y,
        ["DATE OF LOSS", "TYPE", "DESCRIPTION", "PAID", "INCURRED"],
        [["03/14/2022", "Property", "Water damage from burst supply line", "$18,400", "$18,400"],
         ["11/02/2023", "Liability", "Third party slip and fall at premises", "$32,750", "$41,000"],
         ["06/21/2024", "Property", "Wind damage to roof covering", "$9,200", "$9,200"],
         ["01/09/2025", "Liability", "Third party property damage during premises maintenance", "$6,500", "$14,300"]],
        [1.0, 2.1, 3.0, 5.9, 6.8],
    )
    y = _row(c, y, "Total Claims Reported", "4")
    y = _row(c, y, "Total Incurred", "$82,900")

    c.showPage()
    c.save()


# ── Self-verification: drive the REAL rule engine ───────────────────────────
#
# An offline probe proves the FUNCTION, never the SEAM around it (the standing
# lesson from the dec-index arc), so this is honest about what it checks: it
# proves the RULES emit the four offers for the facts this document is written
# to produce. It cannot prove extraction reads them off the PDF - only the live
# run does that, which is the whole point of the kit.

EXPECTED_FACTS = {
    "applicant_name": INSURED,
    "operations_description": OPS,
    "gl_class_codes_by_location": [{"code": "91340"}, {"code": "91585"}],
    "gl_each_occurrence": "$1,000,000",
    "gl_aggregate": "$2,000,000",
    "percent_subcontracted": 25,
    "certificate_holder": "Ridgeline Commercial Properties LP",
    "mortgagee_name": "Blue Ridge Community Bank, NA",
    "property_building_value": 1_750_000,
    "property_bpp_value": 425_000,
    "num_claims": "4",
    "total_incurred": "$82,900",
    "total_revenue": 4_850_000,
}
EXPECTED_FLAGS = {
    "is_contractor": True,
    "has_general_liability": True,
    "has_property_coverage": True,
    "has_certificate_request": True,
}
SELECTED = {"ACORD_125", "ACORD_126"}
WANT = {
    "contractor_missing_acord186": "ACORD_186",
    "certificate_requested_but_acord25_missing": "ACORD_25",
    "property_evidence_requested_but_acord28_missing": "ACORD_28",
    "acord101_required": "ACORD_101",
}


def verify() -> list:
    from services.cross_form_validator import run_cross_form_validation

    issues = run_cross_form_validation(EXPECTED_FACTS, EXPECTED_FLAGS, set(SELECTED))
    offers = {}
    for iss in issues:
        for fid in ((iss.get("resolution") or {}).get("add_forms") or []):
            offers.setdefault(iss.get("code"), []).append(fid)

    problems = []
    for code, form in WANT.items():
        got = offers.get(code)
        if not got:
            problems.append(f"MISSING: {code} did not offer {form}")
        elif form not in got:
            problems.append(f"WRONG:   {code} offered {got}, expected {form}")
    for code, forms in offers.items():
        if code not in WANT:
            problems.append(f"EXTRA:   {code} offers {forms} (kit expects only 4)")
    # A form already selected must never be offered - the BUG-05 contract.
    for code, forms in offers.items():
        clash = set(forms) & SELECTED
        if clash:
            problems.append(f"BAD:     {code} offers already-selected {sorted(clash)}")
    return problems, offers


README = """# UX-05 live test - "Add form" from a validation finding

ONE upload. Four missing-form validations, four Add buttons.

## 1. Upload

Upload `ux05-kestrel-ridge-builders.pdf` as a NEW package (not into an existing
session - extraction caches per document).

## 2. Select forms - THIS IS THE STEP THAT MATTERS

On the Select Forms screen, tick **ONLY**:

  * ACORD 125 - Commercial Insurance Application
  * ACORD 126 - Commercial General Liability Section

**Untick everything else.** The system will RECOMMEND ACORD 186, 25, 28, 101
and probably 140 - that is correct, and leaving them ticked is exactly what
stops the test working. ACORD 126 must stay ticked: the contractor rule only
runs when the GL section is in the package.

Then Generate.

## 3. What you should see BEFORE generation - DO NOT SKIP THIS SCREEN

On the **Review** screen, before you continue to form selection, ONE row carries
a pink button:

  * A certificate of liability was requested ...  ->  **+ Add ACORD 25**

That is the PRE-GENERATION half of the feature, and it is a different action
from the one in the editor: nothing is generated and nothing is charged. It
ticks the form on the Select Forms list and takes you straight there, because
before generation the correct fix is simply to include the form in the run.

**Only ACORD 25, and that is correct.** Before generation the rules run against
the RECOMMENDED forms, and this document recommends 186, 28, 101 (and 140/141)
- so none of those is missing yet. ACORD 25 is the one the recommender does not
suggest, so it is genuinely missing right now.

The other rows on that screen are unchanged and must stay that way: the two
property rows keep "Open to fix", and the ACORD 101 row keeps its "Needs a
written explanation, not a value" note with no Add button.

**Test it, then undo it.** Click "+ Add ACORD 25" - you should land on Select
Forms with ACORD 25 already ticked. Then UNTICK it again before generating, or
the editor half of the test has one less form to add.

## 4. What you should see AFTER generation

Open **SQS & Actions -> Cross-Form Validation** on any form. Four rows, each
with a pink button naming a form instead of the old "Open to fix":

| Row | Button |
|-----|--------|
| Operations indicate a contracting business ... ACORD 186 is not included | **Add ACORD 186** |
| A certificate of liability was requested ... ACORD 25 is not in the selected forms | **Add ACORD 25** |
| A mortgagee/loss payee was detected ... ACORD 28 is not in the selected forms | **Add ACORD 28** |
| ACORD 101 (Additional Remarks Schedule) is required to explain ... | **Add ACORD 101** |

## 5. The checks

**1 - The reported bug is gone.** Click the ACORD 186 row. The modal must show a
pink "Missing form" panel with an **Add ACORD 186** button. It must NOT be just
Dismiss / Mark resolved with the sentence "This validation can't be fixed by
entering a single value".

**2 - It actually adds the form.** Click Add ACORD 186. Expect a few minutes -
it really generates the form. The modal stays open and turns green: "ACORD 186
is now in this package". Close it.

**3 - The form list refreshed.** GENERATED FORMS now shows one more form, and
ACORD 186 is in the list and openable.

**4 - The validation re-evaluated.** The ACORD 186 row is gone from Cross-Form
Validation. Scores have been recalculated.

**5 - Composite mode (the interesting one).** Open the ACORD 101 row. It must
show BOTH the Add ACORD 101 button AND the narrative textarea - that rule needs
the form AND an explanation. Adding the form must not remove the textarea.

**6 - ACORD 101 does NOT vanish after adding.** Correct behaviour: that rule
fires on your claim count, not on the form list, so the row stays. It must not
be auto-marked "Resolved" - that would be a lie.

**7 - Idempotent.** Reopen the ACORD 186 row if it is still visible, or replay
the same click. It must refuse with "That form is already in this package", not
regenerate it.

**8 - Nothing else was destroyed.** ACORD 125 and 126 must still be in the list,
still openable, and any field you edited before adding must still hold your
edit. (Edit one field on ACORD 125 BEFORE running check 2, so this is a real
check and not a formality.)

**9 - The other two still work.** Add ACORD 25 and ACORD 28 the same way. The
package should end with 5 forms.

## 6. What to send back

* A screenshot of the four rows before you click anything.
* A screenshot of the ACORD 101 modal (both controls visible).
* The GENERATED FORMS list before and after.
* Anything that read wrong in plain English.

## Known and expected

* The added form is generated WITHOUT the declarations index, which is deleted
  when the package first generates. Measured cost: about 9 fields in 5,852 come
  out blank instead of filled. No field is ever wrong.
* Adding a form can raise NEW validations for that form - a form in the package
  switches on every rule scoped to it. That is correct.
* Adding a form can newly block a download if it contains placeholder fields.
"""


def main() -> int:
    problems, offers = verify()
    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = os.path.join(OUT_DIR, "ux05-kestrel-ridge-builders.pdf")
    build_pdf(pdf)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as f:
        f.write(README)

    print(f"wrote {pdf}")
    print(f"wrote {os.path.join(OUT_DIR, 'README-HOW-TO-TEST.md')}")
    print("\nRule-engine verification (selected = ACORD 125 + 126):")
    for code in sorted(offers):
        print(f"  {code:<50} -> {offers[code]}")
    if problems:
        print("\nFIXTURE PROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - exactly the 4 expected offers, none already selected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
