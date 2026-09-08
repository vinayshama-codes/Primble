"""make_bug04_test_pdf.py - ONE live test file for BUG-04 (the ACORD 125 loss row).

    py backend/scripts/make_bug04_test_pdf.py            # random values
    py backend/scripts/make_bug04_test_pdf.py --seed 11  # reproducible

Writes bug04_test_data/BUG04_acord125_no_losses.pdf plus README-HOW-TO-TEST.md with
this run's values and the step-by-step protocol.

WHY ONE FILE AND NOT THREE
--------------------------
An earlier version of this kit shipped three PDFs - "no losses mentioned",
"narrative says no losses", "two real claims". That was wrong, and the reason is
worth writing down.

The three were separate sessions testing THE SAME SEAM three times: producer
edit -> `update_pdf` -> `apply_acord125_missing_field_highlights` -> the yellow
paint and the Required chip. The seam does not care which document opened the
session. What differs between the three is the STATE of the loss facts, and the
full state matrix is already covered offline, exhaustively, against the real
ACORD 125 schema - 46 unit tests plus 12,000 fuzzed field states
(`tests/test_acord125_loss_row_required.py`), and
`scripts/verify_bug04_matrix.py` prints the whole matrix on demand with no
upload and no API cost.

So the live run has exactly one job: prove the fix is in the layer the screen
reads. One session does that.

And the control - "a real claim must STILL turn its row yellow" - does not need
a second document either. Typing a date into DATE OF OCCURRENCE in Edit Fields
is a producer edit through the same seam, and it is a STRONGER control than a
second upload: it changes one cell with everything else held fixed, so a
difference can only have come from that cell.

WHAT THIS FILE IS
-----------------
The client's reported screenshot, reproduced: a General Liability + Property
package whose narrative says there have been no known losses, with a stated
5-year loss information period and no claims.

That state is the defect's own ground zero. Before the fix, the stated "5" ALONE
marked all seven cells of claim row A required, and ticking "Check if none"
kept them there - so the form demanded a date of occurrence, a claim date, a
paid amount and a reserve for a claim that does not exist.

EVERY VALUE IS RANDOM. THE STRUCTURE IS NOT.
--------------------------------------------
Name, trade, address, FEIN, carriers, NAIC, policy numbers, premiums, limits and
dates are drawn fresh on every run. What is held constant is the only thing
under test: what the document says about losses, and how. A fix that passed by
memorising a fixture fails here on the second run. Run it twice.

Years in business is pinned to 9-14 so the loss pillar sits in the 5+ band and
an attestation scores a clean 60. (A 1-5 year business scores 85 on the same
attestation - correct, but a second number to explain.)
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, timedelta

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bug04_test_data",
)

_TRADES = [
    ("Bakery", "wholesale bread and pastry production for grocery accounts"),
    ("Print Shop", "commercial offset and digital printing"),
    ("Machine Shop", "precision metal fabrication and CNC machining"),
    ("Florist", "retail floral arrangement and event delivery"),
    ("Bookbinder", "hardcover binding and archival restoration"),
    ("Upholstery", "commercial furniture upholstery and re-covering"),
    ("Sign Maker", "vinyl and channel-letter sign fabrication"),
    ("Cabinet Shop", "custom cabinetry manufacture and finishing"),
    ("Dry Cleaner", "retail garment cleaning and pressing"),
    ("Camera Repair", "optical and digital camera service"),
]
_SUFFIX = ["LLC", "Inc.", "Corp.", "Company", "Group Inc.", "Holdings LLC", "& Co."]
_FIRST = ["Bellamy", "Carrick", "Denholm", "Everly", "Foxcroft", "Granville",
          "Hartwell", "Ivorydale", "Jessup", "Kirkbride", "Lanyard", "Merrick"]
_STREETS = ["Tannery Row", "Bishop Street", "Quarry Road", "Wharf Lane",
            "Sycamore Drive", "Kiln Court", "Beacon Avenue", "Fulton Way"]
_CITIES = [("Bangor", "ME"), ("Casper", "WY"), ("Dubuque", "IA"), ("Elmira", "NY"),
           ("Findlay", "OH"), ("Galena", "IL"), ("Hobbs", "NM"), ("Joplin", "MO"),
           ("Kearney", "NE"), ("Laramie", "WY"), ("Muncie", "IN"), ("Norwich", "CT")]
_CARRIERS = ["Thornbury Mutual Insurance Company", "Ashgrove Casualty Group",
             "Pelham Standard Insurance Company", "Windmere Indemnity Company",
             "Kestrel Ridge Mutual", "Oakhaven Casualty Company",
             "Barrowfield Insurance Company", "Sablecrest Mutual Casualty"]
_SURNAMES = ["Ward", "Nash", "Pryce", "Doyle", "Ainsley", "Rowan", "Beckett",
             "Calloway", "Fenwick", "Marsden", "Tobin", "Vance"]


class Kit:
    """One run's random values, printed into the README so a failure is
    reproducible and a pass can be checked by eye."""

    def __init__(self, rnd: random.Random):
        trade, ops = rnd.choice(_TRADES)
        self.trade, self.ops = trade, ops
        self.name = f"{rnd.choice(_FIRST)} {trade} {rnd.choice(_SUFFIX)}"
        self.dba = f"{rnd.choice(_FIRST)} {trade}"
        self.city, self.state = rnd.choice(_CITIES)
        self.zip = f"{rnd.randint(10000, 99999)}"
        self.addr = f"{rnd.randint(100, 9899)} {rnd.choice(_STREETS)}"
        self.fein = f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}"
        self.phone = f"({rnd.randint(200, 989)}) {rnd.randint(200, 999)}-{rnd.randint(1000, 9999)}"
        self.contact = f"{rnd.choice(_SURNAMES)} {rnd.choice(_SURNAMES)}"
        self.years = rnd.randint(9, 14)          # 5+ band -> attestation = 60
        self.started = date.today().replace(month=1, day=1) - timedelta(days=365 * self.years)

        self.gl_carrier = rnd.choice(_CARRIERS)
        self.prop_carrier = rnd.choice([c for c in _CARRIERS if c != self.gl_carrier])
        self.gl_naic = f"{rnd.randint(10000, 44999)}"
        self.prop_naic = f"{rnd.randint(10000, 44999)}"
        self.gl_policy = f"{rnd.choice('BCGKMPRT')}{rnd.choice('ABDHLN')}{rnd.randint(100000, 999999)}"
        self.prop_policy = f"{rnd.choice('BCGKMPRT')}{rnd.choice('ABDHLN')}{rnd.randint(100000, 999999)}"
        self.eff = date.today().replace(day=1) - timedelta(days=rnd.randint(30, 180))
        self.exp = self.eff + timedelta(days=365)
        self.gl_premium = rnd.randrange(4200, 18500, 25)
        self.prop_premium = rnd.randrange(2600, 12400, 25)
        self.occ = rnd.choice([1000000, 1000000, 2000000])
        self.agg = self.occ * 2
        self.revenue = rnd.randrange(900000, 7400000, 5000)
        self.payroll = rnd.randrange(240000, 1900000, 1000)
        self.employees = rnd.randint(6, 48)
        self.bldg_value = rnd.randrange(450000, 3800000, 5000)
        self.bpp_value = rnd.randrange(80000, 900000, 1000)
        self.deductible = rnd.choice([1000, 2500, 5000, 10000])
        self.area = rnd.randrange(3200, 42000, 100)
        self.year_built = rnd.randint(1958, 2016)
        # The date the tester types into DATE OF OCCURRENCE at step 4.
        self.probe_date = (date.today() - timedelta(days=rnd.randint(200, 900))
                           ).strftime("%m/%d/%Y")

    def money(self, n) -> str:
        return f"${n:,}"


# ── Drawing helpers ──────────────────────────────────────────────────────────

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


def _para(c, y, text, width=104):
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


# ── The document ─────────────────────────────────────────────────────────────

def build(k: Kit, path: str, deny_loss_runs: bool = False) -> None:
    c = canvas.Canvas(path, pagesize=letter)

    y = _page(c, "ACORD 125 - COMMERCIAL INSURANCE APPLICATION",
              "Application for Insurance - renewal, General Liability and Property")
    y = _head(c, y, "APPLICANT")
    y = _row(c, y, "Named Insured", k.name)
    y = _row(c, y, "DBA", k.dba)
    y = _row(c, y, "Mailing Address", f"{k.addr}, {k.city}, {k.state} {k.zip}")
    y = _row(c, y, "Physical Address", f"{k.addr}, {k.city}, {k.state} {k.zip}")
    y = _row(c, y, "FEIN", k.fein)
    y = _row(c, y, "Contact", f"{k.contact}  {k.phone}")
    y = _row(c, y, "Legal Entity", "Limited Liability Company")
    y = _row(c, y, "Business Started", k.started.strftime("%m/%d/%Y"))
    y = _row(c, y, "Years in Business", k.years)

    y = _head(c, y, "POLICY PERIOD AND COVERAGE")
    y = _row(c, y, "Proposed Effective Date", k.eff.strftime("%m/%d/%Y"))
    y = _row(c, y, "Proposed Expiration Date", k.exp.strftime("%m/%d/%Y"))
    y = _table(
        c, y,
        ["LINE OF BUSINESS", "CARRIER", "NAIC", "POLICY NUMBER", "PREMIUM"],
        [["General Liability", k.gl_carrier[:26], k.gl_naic, k.gl_policy, k.money(k.gl_premium)],
         ["Property", k.prop_carrier[:26], k.prop_naic, k.prop_policy, k.money(k.prop_premium)]],
        [1.0, 2.3, 4.4, 5.0, 6.3],
    )
    y = _head(c, y, "GENERAL LIABILITY LIMITS")
    y = _row(c, y, "Each Occurrence Limit", k.money(k.occ))
    y = _row(c, y, "General Aggregate Limit", k.money(k.agg))
    y = _row(c, y, "Products / Completed Operations Aggregate", k.money(k.agg), lw=4.2)
    y = _row(c, y, "Personal and Advertising Injury Limit", k.money(k.occ), lw=4.2)
    y = _row(c, y, "Total Policy Premium", k.money(k.gl_premium + k.prop_premium))

    y = _new_page(c, "ACORD 125 - COMMERCIAL INSURANCE APPLICATION",
                  "Application for Insurance - page 2, premises and operations")
    y = _head(c, y, "PREMISES AND EXPOSURE")
    y = _row(c, y, "Location 1", f"{k.addr}, {k.city}, {k.state} {k.zip}")
    y = _row(c, y, "Interest", "Owner")
    y = _row(c, y, "Building Area", f"{k.area:,} sq ft")
    y = _row(c, y, "Year Built", k.year_built)
    y = _row(c, y, "Construction", "Joisted Masonry")
    y = _row(c, y, "Building Value", k.money(k.bldg_value))
    y = _row(c, y, "Business Personal Property", k.money(k.bpp_value))
    y = _row(c, y, "Property Deductible", k.money(k.deductible))
    y = _row(c, y, "Annual Gross Sales", k.money(k.revenue))
    y = _row(c, y, "Annual Payroll", k.money(k.payroll))
    y = _row(c, y, "Full Time Employees", k.employees)
    y = _row(c, y, "Part Time Employees", max(1, k.employees // 6))

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _para(c, y, f"The applicant operates a {k.trade.lower()} business performing "
                    f"{k.ops}. Operations are conducted from the single owned premises "
                    f"shown above. No work is performed away from the premises and the "
                    f"applicant owns no vehicles.")

    # ── The state under test ────────────────────────────────────────────────
    # A stated loss PERIOD with no claims, plus a narrative no-loss sentence.
    # The "5" alone used to mark all seven cells of claim row A required; the
    # narrative sentence is the client's NARRATIVE tier (pillar 40) and must NOT
    # tick the attestation box.
    y = _head(c, y, "LOSS HISTORY")
    y = _row(c, y, "Loss Information Period", "5 years")
    y = _row(c, y, "Number of Claims", "0")
    y = _row(c, y, "Total Losses", "$0")
    y = _para(c, y, "The applicant has had no known losses in the past five years. The "
                    "producer has not been advised of any claim, occurrence or "
                    "circumstance that may give rise to a claim during that period.")
    if deny_loss_runs:
        # THE CLASSIFIER TEST, and the only difference between the two files.
        # This sentence used to make `classify_document` score the whole
        # application as a LOSS RUN (loss_run 10.0 / application 4.5, high) off
        # the literal phrase "loss runs" - a NEGATION read as evidence of the
        # thing it denies. `has_loss_run_doc` then went True, the Loss History
        # pillar took the runs-uploaded path, scored 60 instead of 40, and the
        # panel printed "Loss runs attached" plus two recommendations about a
        # document that does not exist.
        y = _para(c, y, "Loss runs have not been attached to this submission. "
                        "The carrier loss runs were not provided by the prior "
                        "carrier before this application was completed.")
    else:
        y = _para(c, y, "No supporting claim documentation accompanies this application.")
    c.save()


# ── README ───────────────────────────────────────────────────────────────────

def _readme(k: Kit, seed) -> str:
    return f"""# BUG-04 live test - the ACORD 125 loss row

**One file, one session, five steps, about six minutes.**

Generated with seed `{seed}`. Every value is random for this run - re-run
`py backend/scripts/make_bug04_test_pdf.py` for a different set. The structure is
what is under test, not the values. Run it twice before you believe a pass.

## The account this run generated

| | |
|---|---|
| Named insured | {k.name} |
| DBA | {k.dba} |
| Trade | {k.trade} - {k.ops} |
| Address | {k.addr}, {k.city}, {k.state} {k.zip} |
| FEIN | {k.fein} |
| Years in business | {k.years} (5+ band, so an attestation scores 60) |
| GL carrier / policy | {k.gl_carrier} / {k.gl_policy} |
| Property carrier / policy | {k.prop_carrier} / {k.prop_policy} |
| GL limits | {k.money(k.occ)} occurrence / {k.money(k.agg)} aggregate |
| Total premium | {k.money(k.gl_premium + k.prop_premium)} |
| Policy period | {k.eff.strftime('%m/%d/%Y')} - {k.exp.strftime('%m/%d/%Y')} |
| Loss history | 5-year period stated, 0 claims, narrative says no known losses |

## Why one file is enough

The full state matrix - every combination of tick / years / total / claim data -
is already proved offline against the real ACORD 125 schema by 46 unit tests and
12,000 fuzzed field states. Run `py backend/scripts/verify_bug04_matrix.py` to
print that matrix yourself; it needs no upload and costs nothing.

What only a live run can prove is that the fix sits in the layer the SCREEN
reads. That is one seam - producer edit, `update_pdf`, the highlighter, the
yellow paint and the Required chip - and it is the same seam whatever document
opened the session. Uploading three files would test it three times.

The control ("a real claim must still turn its row yellow") is step 4 below:
typing a date into the grid by hand. That is a stronger control than a second
upload, because it changes ONE cell with everything else held fixed.

## The document this file represents

The client's reported screenshot: a narrative "no known losses" sentence and a
stated 5-year loss period, with no claims. That state is the defect's ground
zero - the stated "5" alone used to mark all seven cells of claim row A
required, and ticking "Check if none" kept them there.

---

## Run it

Upload `BUG04_acord125_no_losses.pdf`, generate **ACORD 125**, open the form, scroll to
the **LOSS HISTORY** section on page 2.

Throughout: **"yellow claim cells"** means tan/yellow **Required** cells inside
the claim table - DATE OF OCCURRENCE / LINE / TYPE OR DESCRIPTION / DATE OF CLAIM
/ AMOUNT PAID / AMOUNT RESERVED / OPEN. It does **not** mean the "Check if none"
box or the "for the last N years" box above the table; those are the section's
own questions and are allowed to be yellow.

| # | Do this | Expect |
|---|---|---|
| 1 | Just look. | Box **blank**. "5" in the years box. **0 yellow claim cells.** Loss History **40**. |
| 2 | Edit Fields -> tick **Check if none** -> save. | **0 yellow claim cells.** Required chip **goes DOWN by 1**. Loss History **40 -> 60**. |
| 3 | Untick it -> save. | **0 yellow claim cells.** Loss History **back to 40**. Box prints blank or unticked - it must NOT re-tick itself. |
| 4 | Type `{k.probe_date}` into **DATE OF OCCURRENCE**, first row -> save. | **The other 6 cells of that row turn yellow.** This is the control - it proves the highlight is alive. |
| 5 | Clear that date, tick **Check if none** -> save. | **Back to 0 yellow claim cells.** |

Step 1 is the reported bug. Step 2 is the fix. Step 3 proves a retraction sticks.
Step 4 proves I did not fix it by switching the highlight off. Step 5 proves an
attestation outranks a stray cell.

### STOP at step 1 if Loss History is not 40

If it reads anything else - especially **60** with *"Loss runs attached"* in the
Loss History panel - the document did not land where this test assumes and
nothing after step 1 means anything. That happened once already: an earlier
version of this file classified as a **loss run**, which routes the pillar down
the runs-uploaded path (checked BEFORE the attestation branch, correctly), so
the tick could not move the score whatever the code did.

The generator now checks itself - it re-reads the finished PDF through
`classify_document` and `detect_no_loss_assertion` and prints `self-check OK`
only when the document is an **application** that **states no losses**. If step 1
still disagrees, send me the Loss History panel text and stop.

---

## Then the second file - ONE check, 90 seconds

`BUG04_denial_wording.pdf` is the SAME application with one sentence added:

> *"Loss runs have not been attached to this submission. The carrier loss runs
> were not provided by the prior carrier before this application was completed."*

That sentence used to make the whole application classify as a **loss run**
(`loss_run 10.0` against `application 4.5`, high confidence) off the literal
phrase "loss runs" - a negation read as evidence of the thing it denies. The
Loss History pillar then took the runs-uploaded path and scored **60** instead
of 40, and the panel printed *"Loss runs attached"* plus two recommendations
about a document that does not exist.

Upload it as its own session, generate ACORD 125, and look at the Loss History
panel only:

| expect | not this |
|---|---|
| Loss History **40** | 60 |
| no *"Loss runs attached"* line | *"Loss runs attached"* / *"Matched on: name"* |
| no loss-run recommendations | *"Loss run valuation date not detected"*, *"Loss run ownership could not be fully verified"* |

---

## Send me back this

```
FILE 1 - BUG04_acord125_no_losses.pdf
step 1  (as generated)      Required: ___   yellow claim cells: ___   Loss History: ___%
                            "Check if none" ticked?  yes / no
step 2  (ticked)            Required: ___   yellow claim cells: ___   Loss History: ___%
step 3  (unticked)          Required: ___   yellow claim cells: ___   Loss History: ___%
                            did the box re-tick itself?  yes / no
step 4  (date typed in)     Required: ___   yellow claim cells: ___
step 5  (cleared + ticked)  Required: ___   yellow claim cells: ___

FILE 2 - BUG04_denial_wording.pdf
        Loss History: ___%      "Loss runs attached" shown?  yes / no
        any loss-run recommendations?  yes / no
```

Plus **two screenshots**: the LOSS HISTORY grid at step 1 and at step 2. Those two
decide it. And the **session id** (or the generated PDF).

---

## What a FAIL looks like

1. **Any** yellow cell inside the claim grid at steps 1, 2, 3 or 5.
2. The Required chip going **UP** when you tick at step 2.
3. Step 4 showing **zero** yellow claim cells - the highlight would be dead and
   steps 1-3 would have passed for the wrong reason.
4. Step 3 re-ticking the box by itself - that would be our inference overwriting
   a person.

## Expected, and NOT bugs

- **The box prints blank at step 1** even though the document says "no known
  losses" in prose. Deliberate (SYS-02): a narrative sentence is not an
  attestation, so the form leaves the box for a human. That is what makes step 2
  testable at all.
- **The "for the last N years" box may be yellow.** It is the section's own
  question, not a claim cell.
- **Loss History 40, not 100**, at step 1. A narrative mention is the client's
  own 40 tier.
"""


def _self_check(pdf_path: str) -> bool:
    """Read the finished PDF back through the PIPELINE'S OWN readers and prove
    it lands in the state this test is meant to exercise.

    WHY THIS EXISTS. The first version of this kit shipped a file that
    `classify_document` scored **loss_run 10.0 / application 4.5, high
    confidence** - because the section heading said "LOSS HISTORY", the closing
    line said "Loss runs have not been attached" (a NEGATION counted as evidence
    of the thing it denies, 3.0), and the FILENAME itself was
    `BUG04_loss_history.pdf`, which `_FILENAME_SIGNALS["loss_run"]` matches on
    "loss history". `has_loss_run_doc` was therefore True, the loss pillar took
    the runs-uploaded path - which is checked BEFORE the attestation branch, and
    correctly so - and the producer's tick could not move the score no matter
    what the fix did. A whole live run spent on the wrong code path.

    A test document that does not land where the test assumes proves nothing,
    and nothing about the PDF says so by eye. So the generator now asks the same
    functions the product will:

      doc_type must be 'application'   -> has_loss_run_doc is False, so the
                                          pillar reaches the attestation branch
      detect_no_loss_assertion True    -> the narrative tier (40) is in play, so
                                          the tick has somewhere to move FROM

    Advisory, never fatal: the PDF is still written and the mismatch is printed
    loudly. A backend that cannot be imported is not a reason to withhold a file.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import pdfplumber
        from services.extraction_service import classify_document
        from services.normalization import detect_no_loss_assertion
        with pdfplumber.open(pdf_path) as doc:
            text = "\n".join((p.extract_text() or "") for p in doc.pages)
        got = classify_document(text, os.path.basename(pdf_path)) or {}
        doc_type = got.get("doc_type")
        no_loss = detect_no_loss_assertion(text.lower())
    except Exception as exc:                                   # noqa: BLE001
        print(f"  self-check SKIPPED ({exc.__class__.__name__}: {exc})")
        return True

    ok = True
    if doc_type != "application":
        ok = False
        print(f"\n  !! SELF-CHECK FAILED - classify_document says {doc_type!r}, not "
              f"'application'.\n     scores: {got.get('scores')}\n"
              "     A non-application doc_type sets has_loss_run_doc / doc-tier\n"
              "     inputs that route the loss pillar AWAY from the attestation\n"
              "     branch, so the tick cannot move the score and the run tests\n"
              "     nothing. Fix the wording before testing.")
    if not no_loss:
        ok = False
        print("\n  !! SELF-CHECK FAILED - detect_no_loss_assertion is False, so the\n"
              "     pillar will not sit on the narrative 40 tier and the tick has\n"
              "     nowhere to move from.")
    if ok:
        print(f"  self-check OK   doc_type={doc_type}  no_loss_assertion={no_loss}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=None, help="reproduce a previous run")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(10 ** 6)
    k = Kit(random.Random(seed))

    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = os.path.join(OUT_DIR, "BUG04_acord125_no_losses.pdf")
    build(k, pdf)
    pdf2 = os.path.join(OUT_DIR, "BUG04_denial_wording.pdf")
    build(k, pdf2, deny_loss_runs=True)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as fh:
        fh.write(_readme(k, seed))

    ok = _self_check(pdf) and _self_check(pdf2)

    print(f"  wrote BUG04_acord125_no_losses.pdf")
    print(f"  wrote BUG04_denial_wording.pdf")
    print(f"  wrote README-HOW-TO-TEST.md")
    print(f"\n{OUT_DIR}\n  seed = {seed}   (re-run with --seed {seed} to reproduce)")
    print(f"  account   = {k.name}, {k.city} {k.state}, {k.years} years")
    print(f"  step 4 date to type = {k.probe_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
