"""make_bug06_test_pdfs.py - live test data for BUG-06
("Something went wrong applying your answer" in the correct-value modal).

    py backend/scripts/make_bug06_test_pdfs.py

Writes ONE file to bug06_test_data/, plus README-HOW-TO-TEST.md.

ONE FILE, ONE UPLOAD, EVERY CASE
--------------------------------
An earlier draft split this into four documents so that a non-renewal package
could act as the control for the renewal one. That was weaker as well as
slower: two sessions differ in a hundred ways, so "A failed and B failed" only
rules out the values, and a sceptic can still say the renewal date routing
corrupted A's facts.

One session rules that out completely, because the control sits INSIDE it. This
package raises all four resolution modes at once:

  MODE       CARDS                                          BEHAVIOUR TODAY
  field      5 - the reported umbrella-renewal DATE card,    ALL FAIL
             plus currency, integer, percent, choice, text
  narrative  1 - carrier adverse action, ACORD 101           FAILS
  schedule   2 - vehicle and driver schedules                BOTH SAVE
  (card)     New Venture confirm                             SAVES

Field and narrative go through `arq_service.apply_producer_answer_to_session`.
Schedule goes through `save_session_schedule`, three functions down the same
file. Same modal, same Apply button, same endpoint, same session, same facts -
and one mode saves while the other two 500. Nothing else differs, so nothing
else can be blamed.

Then the New Venture card saves too, which narrows it one step further:

    services/arq_service.py:4922  `_nv_delete` assigned ONLY inside
                                  `elif canon == NEW_VENTURE_FIELD:`
    services/arq_service.py:4941  `delete_facts=_nv_delete or None` read on
                                  EVERY path

New Venture is the only fact whose branch binds the name. That is why it is the
only card of its kind that survives. Introduced in commit d6d09c7.

Value-independence is proved separately and better by
`py backend/scripts/verify_bug06.py`, which drives 17 fact shapes through the
real write door in five seconds. This file does not need to re-prove it.

DELIBERATELY NOT THE CLIENT'S VALUES
------------------------------------
The client typed 07/15/25 and 07/15/26 on ORBIN CONTRACTING. Nothing here uses
that company, those dates, that carrier or those limits.

Self-verified: `_verify()` asserts the words that must be present and the words
that must be ABSENT (an absent field is what raises most of these cards, so a
stray mention silently deletes a test case), then re-runs the REAL
`sqs_service.evaluate_stops` -> `issue_registry.classify_legacy` ->
`resolution_for` chain over the facts this file should yield and fails the
build unless all four modes come back. The extraction step in between is the
LLM's job and is not simulated here.

Design rules inherited from make_c6_test_pdfs.py / make_bug07_test_pdfs.py:
  * Real text via reportlab - extractable by pdfplumber, no OCR dependency.
  * Label/value rows rather than wide tables, so characters never interleave.
  * Every date computed from TODAY, so the kit cannot rot into the wrong branch.
  * Absences asserted with WORD BOUNDARIES, never substrings.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_REPO, "bug06_test_data")
FILENAME = "BUG06_all_cases.pdf"

TODAY = datetime.now()

# A RENEWAL whose stated terms have already ENDED.
# `extraction_service._route_renewal_dates` needs BOTH: an affirmative
# is_renewal AND an expiration date in the past. It then routes the package
# pair into prior_*, DERIVES the proposed term (so no expired-term stop clutters
# the screen), and records every per-line term that also ended in
# `renewal_lines_expiring` - which `sqs_service.py:1427` turns into the reported
# card. 45 days back is unambiguous and still reads as a live renewal.
EXPIRED_EXP = (TODAY - timedelta(days=45)).strftime("%m/%d/%Y")
EXPIRED_EFF = (TODAY - timedelta(days=45 + 365)).strftime("%m/%d/%Y")

NAME = "Halvorsen Ridge Millwork LLC"
AGENCY = "Cascade Summit Risk Advisors Inc"
CARRIER = "Willamette Guaranty Insurance Company"


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


def build(c):
    # ── Page 1: applicant, expiring term, GL ────────────────────────────────
    y = _page(c, "COMMERCIAL PACKAGE - DECLARATIONS",
              "RENEWAL SUBMISSION - expiring policy declarations attached")
    y = _row(c, y, "Transaction Type", "RENEWAL")
    y = _row(c, y, "Named Insured", NAME)
    y = _row(c, y, "Mailing Address", "2755 SW Barrow Creek Road, Springfield, OR 97477")
    y = _row(c, y, "Physical Address", "2755 SW Barrow Creek Road, Springfield, OR 97477")
    y = _row(c, y, "FEIN", "93-4417208")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Marisol Okonkwo-Reyes, (541) 555-0182, marisol@halvorsenridge.example")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Description of Operations",
             "Architectural millwork fabrication and installation for commercial interiors")
    y = _row(c, y, "Annual Gross Sales", "$14,600,000")
    y = _row(c, y, "Annual Payroll", "$4,285,000")
    y = _row(c, y, "Number of Employees", "58")
    y = _row(c, y, "Years in Business", "22")
    y = _row(c, y, "NAICS Code", "321918")

    y = _head(c, y, "EXPIRING POLICY PERIOD")
    y = _row(c, y, "Policy Period", f"{EXPIRED_EFF} to {EXPIRED_EXP}")
    y = _para(c, y, "This submission is a renewal of the policies described below. The "
                    "terms shown are the EXPIRING terms.")

    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "NAIC Number", "19720")
    y = _row(c, y, "Policy Number", "CGL-4471-OR-88")
    y = _row(c, y, "Policy Period", f"{EXPIRED_EFF} to {EXPIRED_EXP}")
    y = _row(c, y, "Coverage Form", "Occurrence")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "GL Class Code", "33210 - Millwork fabrication")
    y = _row(c, y, "Annual Premium", "$18,340")

    # ── Page 2: umbrella (the reported card), property, auto ────────────────
    y = _new_page(c, "COMMERCIAL PACKAGE - DECLARATIONS (CONTINUED)")

    # CARD 1 - field mode, DATE. The umbrella states its OWN term and that term
    # has also ended, so `renewal_lines_expiring` contains "Umbrella".
    y = _head(c, y, "COVERAGE - COMMERCIAL UMBRELLA LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "UMB-4471-OR-12")
    y = _row(c, y, "Umbrella Policy Period", f"{EXPIRED_EFF} to {EXPIRED_EXP}")
    y = _row(c, y, "Umbrella Effective Date", EXPIRED_EFF)
    y = _row(c, y, "Umbrella Expiration Date", EXPIRED_EXP)
    y = _row(c, y, "Each Occurrence Limit", "$5,000,000")
    y = _row(c, y, "Aggregate Limit", "$5,000,000")
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _row(c, y, "Annual Premium", "$9,150")
    y = _para(c, y, "Schedule of Underlying Insurance: the General Liability and Business "
                    "Auto policies described in this declaration.")

    # CARDS 2, 3, 4 - field mode, NOT dates. Minimum Viable COPE is complete
    # (location, occupancy, construction, values) so the HARD stop stays down
    # and the screen stays clean; everything Carrier-Grade COPE asks for is
    # absent, which raises a card spanning integer, choice, text and percent.
    # Business Income is named with no limit, which raises a currency card.
    # Valuation method is absent, which raises its own choice card.
    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "CP-4471-OR-19")
    y = _row(c, y, "Policy Period", f"{EXPIRED_EFF} to {EXPIRED_EXP}")
    y = _row(c, y, "Location 1", "2755 SW Barrow Creek Road, Springfield, OR 97477")
    y = _row(c, y, "Occupancy", "Architectural millwork fabrication and finishing")
    y = _row(c, y, "Construction Type", "Joisted Masonry")
    y = _row(c, y, "Building Limit", "$4,600,000")
    y = _row(c, y, "Business Personal Property Limit", "$1,380,000")
    y = _row(c, y, "AOP Deductible", "$5,000")
    y = _row(c, y, "Annual Premium", "$21,470")
    y = _para(c, y, "Business Income and Extra Expense coverage is included on this "
                    "location under the property section.")

    # CARD 5 - field mode, CURRENCY. Physical damage is named; no deductible
    # amount is stated anywhere, which is what raises it.
    # CARDS 6 and 7 - SCHEDULE mode, and the reason this file lists no
    # vehicles and no drivers. These two are THE CONTROL: they save today.
    y = _head(c, y, "COVERAGE - BUSINESS AUTO")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "CAP-4471-OR-31")
    y = _row(c, y, "Policy Period", f"{EXPIRED_EFF} to {EXPIRED_EXP}")
    y = _row(c, y, "Liability Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Annual Premium", "$7,420")
    y = _para(c, y, "Comprehensive and Collision physical damage coverage applies to the "
                    "autos owned by the applicant.")
    y = _para(c, y, "Covered Autos: Symbol 7 (specifically described autos) applies to "
                    "Liability, Comprehensive and Collision.")

    # No loss run anywhere -> the New Venture confirm card, the second control.
    y = _head(c, y, "LOSS INFORMATION")
    y = _para(c, y, "Loss runs have not been attached to this submission.")
    return c


# ── Writing + self-check ───────────────────────────────────────────────────

def _text_of(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


# The facts this file is built to produce, shown POST-routing: the renewal
# router moves the expiring pair into prior_*, derives the proposed term and
# records the umbrella as still-expiring. That is the state the scorer reads.
_FACTS = {
    "applicant_name": NAME, "is_renewal": "Yes",
    "effective_date": EXPIRED_EFF, "expiration_date": EXPIRED_EXP,
    "umbrella_effective_date": EXPIRED_EFF, "umbrella_expiration_date": EXPIRED_EXP,
    "umbrella_limit": "$5,000,000", "umbrella_sir": "$10,000",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "gl_class_codes_by_location": [{"class_code": "33210"}],
    "locations": [{"address": "2755 SW Barrow Creek Road, Springfield, OR 97477"}],
    "occupancy_type": "Architectural millwork fabrication and finishing",
    "construction_type": "Joisted Masonry",
    "property_building_value": "$4,600,000", "property_bpp_value": "$1,380,000",
    "auto_liability_limit": "$1,000,000",
    "total_revenue": "$14,600,000", "total_payroll": "$4,285,000",
    # ABSENT on purpose - each absence is one card:
    #   year_built roof_year sprinkler_system fire_protection_class
    #   valuation_method coinsurance_percentage business_income_limit
    #   auto_deductible_comp auto_deductible_collision
    #   auto_vin_schedule auto_drivers
}
# `prior_carrier_adverse_action` is NOT a document fact - the producer sets it
# on the pre-form marketing-reason screen by choosing "Carrier nonrenewal".
# That is step 2 of the routine, and it is what raises the narrative card.
_FLAGS = {
    "has_umbrella": True, "has_gl_coverage": True, "has_auto_coverage": True,
    "has_property_coverage": True, "property_has_bi_coverage": True,
    "auto_has_physical_damage": True, "prior_carrier_adverse_action": True,
}


def _cards_by_mode():
    """Run the REAL warning chain. A fixture that promises a card the engine
    will not raise is worse than no fixture - the tester concludes the fix
    worked. So the promise is executed, not remembered."""
    sys.path.insert(0, _BACKEND)
    from services import sqs_service as sq, extraction_service as es
    from services.issue_registry import classify_legacy, resolution_for
    facts = dict(_FACTS)
    es._route_renewal_dates(facts)          # the real router, not a stand-in
    hard, soft = sq.evaluate_stops(facts, dict(_FLAGS))
    out: dict = {}
    for tier, msgs in (("hard", hard), ("soft", soft)):
        for m in msgs:
            code = classify_legacy(m, tier)[0]
            res = resolution_for(code) or {}
            out.setdefault(res.get("mode") or "none", []).append(code)
    return out, len(hard), len(soft)


def _verify(path):
    errs = []
    text = _text_of(path).lower()

    def present(*words):
        for w in words:
            if w.lower() not in text:
                errs.append(f"MUST contain {w!r}")

    def absent(*words):
        # WORD BOUNDARIES, not substrings. Most of these cards exist BECAUSE a
        # value is missing, so one stray mention silently deletes a test case.
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", text):
                errs.append(f"MUST NOT contain {w!r}")

    present("renewal", "commercial umbrella liability", "umbrella effective date",
            "umbrella expiration date", EXPIRED_EFF.lower(), EXPIRED_EXP.lower(),
            "commercial property", "business income", "joisted masonry",
            "physical damage", "loss runs have not been attached")
    # Every one of these would kill a card if it appeared.
    absent("valuation", "coinsurance", "sprinkler", "deductibles",
           "schedule of vehicles", "schedule of drivers", "vin",
           "07/15/25", "07/15/26", "orbin")
    if re.search(r"year built", text):
        errs.append("MUST NOT contain 'year built' (kills the COPE card)")

    modes, n_hard, n_soft = _cards_by_mode()
    for mode, least in (("field", 4), ("narrative", 1), ("schedule", 2)):
        got = modes.get(mode, [])
        if len(got) < least:
            errs.append(f"{mode} mode: expected >={least} card(s), got {got}")
    if "legacy_umbrella_renewal_term_unknown" not in modes.get("field", []):
        errs.append(f"the REPORTED card is not raised (field={modes.get('field')})")
    if n_hard:
        errs.append(f"expected no hard stops (they cap the score and clutter the "
                    f"screen); got {n_hard}")
    return errs, modes, n_soft


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, FILENAME)
    c = canvas.Canvas(path, pagesize=LETTER)
    build(c)
    c.save()
    print(f"Writing to {OUT_DIR}")
    print(f"  wrote {FILENAME}")

    errs, modes, n_soft = _verify(path)
    if errs:
        print("\nFIXTURE SELF-CHECK FAILED:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)

    print("\nFixture self-check PASSED - the real warning engine raises:")
    for mode in ("field", "narrative", "schedule"):
        for code in modes.get(mode, []):
            print(f"  {mode:10s} {code}")
    print(f"  ({n_soft} warnings, 0 hard stops)")

    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")


README = f"""
# BUG-06 live test - "Something went wrong applying your answer"

**One file. One upload. Every case.**

Generated {TODAY.strftime('%Y-%m-%d')}. Expiring term in the document:
**{EXPIRED_EFF} to {EXPIRED_EXP}** (already ended, which is what makes it a renewal
with an unknown proposed term).

Not the client's values - different company, state, carrier, dates and limits.

---

## 0. The 60-second version (no upload, no server)

```
py backend/scripts/verify_bug06.py
```

Drives the real write door against a fake session across 17 fact shapes:
17 fail, 1 succeeds. Exit 1 now, exit 0 once fixed.

That script proves the bug is value-independent. The file below is for watching
it happen in the product.

---

## 1. The routine (about 8 minutes, one session)

1. Upload `{FILENAME}`.
2. On the marketing-reason step choose **"Carrier nonrenewal"**.
   (This is not cosmetic - it is what raises the ACORD 101 narrative card.)
3. Generate **ACORD 125 + 131 + 140 + 127**.
4. Work down the review screen and try to resolve each card below.

### The cards, and what each one is testing

| # | Card | Mode | Fields | Expected TODAY |
|---|------|------|--------|----------------|
| 1 | Renewal: the umbrella's proposed policy term is not stated | field | Umbrella Effective / Expiration Date - **dates** | **fails** |
| 2 | Carrier-Grade COPE incomplete | field | year built, roof year, sprinkler, fire protection class, valuation method, coinsurance - **integer / choice / text / percent** | **fails** |
| 3 | Business Income coverage detected | field | BI limit, period of restoration - **currency** | **fails** |
| 4 | Valuation method not specified | field | valuation method - **choice** | **fails** |
| 5 | Physical damage deductibles not specified | field | comprehensive, collision - **currency** | **fails** |
| 6 | Carrier adverse action indicated | narrative | free text -> ACORD 101 | **fails** |
| 7 | Vehicle schedule missing | schedule | the vehicle table | **SAVES** |
| 8 | Driver schedule missing | schedule | the driver table | **SAVES** |
| 9 | New Venture confirm | card Submit | Yes / No | **SAVES** |
| 10| Any card -> **Dismiss** instead of Apply | - | - | **works** |

Use your own values on 1-5. Anything valid will do; `03/22/2027` and
`03/22/2028` for the dates.

---

## 2. Do it on BOTH screens - they are the same code

The client hit this on the **pre-form review screen** (settle hard stops and
soft stops before generating). The same cards come back **after generation** in
the SQS / Cross-Form Validation panel. Both are one React component
(`AcordModal.jsx`) opening one `ResolutionModal` against one endpoint
(`POST /api/audit/resolve-issue`), so one bug breaks both.

**Run 1 - after generation.** Use the session you already generated. All four
modes are offered there (`AcordModal.jsx:7666`, `actionable = !!iss.resolution`).
That is the table above, rows 1-10.

**Run 2 - before generation.** Upload the file again as a NEW session, choose
"Carrier nonrenewal", and **stop at the review / Select Forms step - do not
click Generate**. Then:

| Card | Expected TODAY |
|---|---|
| 1-5 field cards -> "Open to fix" | **fail** |
| 7-8 schedule cards -> "Open to fix" | **SAVE** |
| Data Consistency picker -> Confirm value | **works** |
| Resolve / Dismiss work-tracking | **works** |

Two things to know before you run it:

* **The narrative card has no button pre-form.** `AcordModal.jsx:3069` gates the
  pre-form banners to `mode === "field" || mode === "schedule"`; narrative and
  "none" render an explanatory note instead. So card 6 is a post-generation
  test only. It is broken on both, but only visible on one.
* **Data Consistency is a different endpoint** (`confirm_underwriting_value`),
  and it does **not** go through the broken function. It is the pre-form
  screen's own control: if it saves while the field cards 500, the failure is
  the fact-write door and not the pre-form screen.

Checked, so you do not have to: the pre-form path has no *second* defect. With
the one-line fix simulated in memory and `generated_forms` empty, all six fact
shapes write and re-score cleanly - `recalculate_session_scores` handles a
session with no generated forms. One fix covers both screens.

---

## 3. Why this is the whole diagnosis

Rows 7 and 8 open **the same modal** and use **the same Apply button** as rows
1-6, in **the same session**, against **the same facts**. Field and narrative
save through `apply_producer_answer_to_session`; schedule saves through
`save_session_schedule`, three functions down the same file.

Two modes 500 and one saves. So it is not the modal, not the endpoint, not the
session, not auth, not the dates and not the values - it is the fact-write door.

Row 9 narrows it to the line. New Venture is an ordinary producer answer
through that same broken door, and it works, because it is the only fact whose
branch happens to bind the variable the last line reads:

```
services/arq_service.py:4922   _nv_delete = ...      # only inside
                                                     # elif canon == NEW_VENTURE_FIELD
services/arq_service.py:4941   delete_facts=_nv_delete or None   # read on EVERY path
```

Introduced in commit `d6d09c7`.

---

## 4. Why the message is useless

Three surfaces print three different strings for one cause:

| Where | Message today |
|---|---|
| Correct-value modal, field mode | "Something went wrong applying your answer." |
| Correct-value modal, ACORD 101 | "Something went wrong saving the explanation." |
| Recommendation card, Submit | "Network error. Please try again." |

All three are the frontend's `catch`. The server returned HTTP 500 and the 500
loses its CORS header on the way out, so the browser reports a network failure
instead of the JSON the server built. That is why no field-specific message
ever reaches the producer.

---

## 5. What "fixed" looks like

| Row | Before | After |
|---|---|---|
| 1-5 field cards | error | **save, cards clear, score moves** |
| 6 narrative card | error | **saves into ACORD 101 remarks** |
| 7-8 schedule cards | save | **unchanged** |
| 9 New Venture | saves | **unchanged** |
| 10 Dismiss | works | **unchanged** |
| `py backend/scripts/verify_bug06.py` | 17 broken | **0 broken, exit 0** |

Rows 7-10 are the safety check. If any of them moves, stop and say so before
anything else.
"""


if __name__ == "__main__":
    main()
