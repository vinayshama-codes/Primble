"""make_sys04_demo.py - the SYS-04 demo pack for Brent.

    py backend/scripts/make_sys04_demo.py             # deterministic (rehearsable)
    py backend/scripts/make_sys04_demo.py --seed 9    # fresh values, same structure

Writes `sys04_demo/` at the repo root: two PDFs and DEMO-SCRIPT.md.

WHY TWO FILES, AND WHY THAT IS THE WHOLE POINT
-----------------------------------------------
One document can only show that Workers Comp asks are absent. It cannot show
they are absent *for the right reason* - a product that had simply stopped
asking about Workers Comp would look identical. The demo is the PAIR:

    DEMO-A   a complete GL + Property contractor.        NO Workers Comp asks.
    DEMO-B   byte-identical, PLUS a real Workers Comp     ALL Workers Comp asks.
             policy with payroll, class codes and a mod.

Same applicant, same limits, same narrative, same everything. **One difference
in the documents, one difference on the screen.** That is a controlled
comparison, and it is what makes the claim checkable rather than assertable.

WHY THESE ARE NOT THE `sys04_test_data` FIXTURES
-------------------------------------------------
That kit is diagnostic: deliberately thin, so it probes edge cases. It also
produces a screen full of unrelated warnings - missing producer name, COPE
incomplete, no valuation method, no GL class codes - which are all CORRECT and
all noise in a demo. Brent should not have to look past four true warnings to
find the one thing being shown.

These two are therefore COMPLETE submissions. Every field the pre-form screen
asks for is stated in the document:

  producer name + address        applicant, DBA, FEIN, entity, phone
  NAICS and SIC                  operations, revenue, employees, years
  GL limits + class codes        property values, occupancy, construction
  year built, roof year          sprinkler, protection class
  valuation method (RCV)         AOP deductible, coinsurance
  a narrative covering 9 of the 10 general components

**Management Experience is left out on purpose.** The narrative recommendation
must still have something honest to name - if the sentence came back empty we
could not tell a working gate from a silenced message. So on BOTH files it
reads "...but does not include Management Experience", and on neither does it
mention Workers Comp.

DETERMINISTIC BY DEFAULT so the demo can be rehearsed and will look identical on
the day. `--seed` re-randomises every value while holding the structure, which
is the proof that nothing is tuned to a fixture.
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
    "sys04_demo",
)

# The third element is the WC class code. The operations text must be a real
# sentence: `cross_form_validator` raises an ACORD 101 requirement when the
# operations description is under FOUR WORDS (H1-I changed that rule from
# characters to words), and "commercial electrical fit-out" is three.
_TRADES = [
    ("Roofing", "residential and light-commercial re-roofing, gutter replacement "
                "and roof maintenance for owner-occupied buildings", "5551"),
    ("Plumbing", "commercial plumbing installation, drain service and fixture "
                 "replacement for offices and retail tenants", "5183"),
    ("Electrical", "commercial electrical fit-out, panel upgrades and lighting "
                   "retrofits for office and retail tenants", "5190"),
    ("HVAC", "heating and air conditioning installation, service and seasonal "
             "maintenance for commercial buildings", "5538"),
]
_FIRST = ["Bristol", "Kenmore", "Ashland", "Fairview", "Northgate", "Wexford"]
_STREETS = ["Mill Road", "Commerce Way", "Depot Street", "Foundry Lane"]
_CITIES = [("Akron", "OH"), ("Boise", "ID"), ("Salem", "OR"), ("Waco", "TX")]
_CARRIERS = ["Hartland Mutual Insurance Company", "Cornerstone Casualty Group",
             "Ironbridge Indemnity Company", "Sentinel Peak Insurance Company"]
_WC_CARRIERS = ["Keystone Compensation Mutual", "Meridian Workers Insurance Company"]
_AGENCIES = ["Copperfield Insurance Advisors", "Harbor Point Risk Partners",
             "Stonebridge Commercial Insurance"]


class Demo:
    def __init__(self, rnd):
        self.rnd = rnd
        trade, ops, wc_code = rnd.choice(_TRADES)
        self.trade, self.ops, self.wc_code = trade, ops, wc_code
        self.name = f"{rnd.choice(_FIRST)} {trade} LLC"
        self.dba = f"{rnd.choice(_FIRST)} {trade}"
        city, st = rnd.choice(_CITIES)
        self.city, self.state, self.zip = city, st, f"{rnd.randint(10000, 99999)}"
        self.addr = f"{rnd.randint(100, 9899)} {rnd.choice(_STREETS)}"
        self.fein = f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}"
        self.phone = f"({rnd.randint(200, 989)}) {rnd.randint(200, 999)}-{rnd.randint(1000, 9999)}"
        self.agency = rnd.choice(_AGENCIES)
        self.agency_addr = f"{rnd.randint(100, 999)} {rnd.choice(_STREETS)}, {city}, {st} {self.zip}"
        self.agency_phone = f"({rnd.randint(200, 989)}) {rnd.randint(200, 999)}-{rnd.randint(1000, 9999)}"
        self.years = rnd.randint(9, 32)
        self.founded = date.today().year - self.years
        self.employees = rnd.randint(12, 90)
        self.revenue = rnd.randrange(2_000_000, 18_000_000, 50_000)
        self.payroll = rnd.randrange(900_000, 5_000_000, 10_000)
        start = date.today() + timedelta(days=rnd.randint(20, 200))
        self.eff = start.strftime("%m/%d/%Y")
        self.exp = start.replace(year=start.year + 1).strftime("%m/%d/%Y")
        self.gl_carrier, self.prop_carrier = rnd.sample(_CARRIERS, 2)
        self.wc_carrier = rnd.choice(_WC_CARRIERS)
        self.gl_naic = f"{rnd.randint(10000, 44999)}"
        self.prop_naic = f"{rnd.randint(10000, 44999)}"
        self.wc_naic = f"{rnd.randint(10000, 44999)}"
        self.gl_policy = f"BX{rnd.randint(100000, 999999)}"
        self.prop_policy = f"CP{rnd.randint(100000, 999999)}"
        self.wc_policy = f"WC{rnd.randint(100000, 999999)}"
        self.gl_premium = rnd.randrange(9000, 42000, 250)
        self.prop_premium = rnd.randrange(6000, 30000, 250)
        self.wc_premium = rnd.randrange(18000, 90000, 250)
        occ = rnd.choice([1_000_000, 2_000_000])
        self.gl_occ, self.gl_agg = f"${occ:,}", f"${occ * 2:,}"
        self.building = f"${rnd.randrange(900_000, 4_500_000, 25_000):,}"
        self.bpp = f"${rnd.randrange(150_000, 900_000, 5_000):,}"
        self.aop = f"${rnd.choice([1000, 2500, 5000, 10000]):,}"
        # > 40 years old with RCV and a value over $500k raises a valuation
        # advisory (`cross_form_validator` :1182-1186). Keep the demo building
        # young enough that the advisory is not part of the picture.
        self.year_built = rnd.randint(2004, 2018)
        self.roof_year = rnd.randint(2015, 2023)
        self.naics = rnd.choice(["238160", "238220", "238210", "238290"])
        self.sic = rnd.choice(["1761", "1711", "1731"])
        self.el = f"${rnd.choice([500_000, 1_000_000]):,}"
        self.xmod = f"{rnd.uniform(0.72, 1.14):.2f}"
        self.sqft = f"{rnd.randrange(4000, 30000, 500):,}"


# ── layout ──────────────────────────────────────────────────────────────────

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
    return y - 0.205 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.22 * inch


def _para(c, y, text, width=104):
    c.setFont("Helvetica", 9)
    line = ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            c.drawString(1 * inch, y, line)
            y -= 0.185 * inch
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        c.drawString(1 * inch, y, line)
        y -= 0.185 * inch
    return y - 0.06 * inch


def _table(c, y, headers, rows, cols):
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in zip(cols, headers):
        c.drawString(x * inch, y, h)
    y -= 0.19 * inch
    c.setFont("Helvetica", 8)
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, str(v))
        y -= 0.185 * inch
    return y - 0.09 * inch


def _identity(c, y, d: Demo):
    y = _head(c, y, "PRODUCER / AGENCY")
    y = _row(c, y, "Producer Agency Name", d.agency)
    y = _row(c, y, "Producer Address", d.agency_addr)
    y = _row(c, y, "Producer Telephone", d.agency_phone)
    y = _head(c, y, "APPLICANT")
    y = _row(c, y, "Named Insured", d.name)
    y = _row(c, y, "DBA", d.dba)
    y = _row(c, y, "Mailing Address", f"{d.addr}, {d.city}, {d.state} {d.zip}")
    y = _row(c, y, "FEIN", d.fein)
    y = _row(c, y, "Telephone", d.phone)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "NAICS Code", d.naics)
    y = _row(c, y, "SIC Code", d.sic)
    y = _row(c, y, "Years in Business", f"{d.years} (established {d.founded})")
    y = _row(c, y, "Annual Gross Sales", f"${d.revenue:,}")
    y = _row(c, y, "Number of Employees", d.employees)
    y = _row(c, y, "Description of Operations", d.ops.capitalize())
    return y


def _gl_and_property(c, y, d: Demo):
    y = _head(c, y, "GENERAL LIABILITY")
    y = _row(c, y, "Carrier", d.gl_carrier)
    y = _row(c, y, "Carrier NAIC", d.gl_naic)
    y = _row(c, y, "Policy Number", d.gl_policy)
    y = _row(c, y, "Policy Period", f"{d.eff} to {d.exp}")
    y = _row(c, y, "Each Occurrence Limit", d.gl_occ)
    y = _row(c, y, "General Aggregate Limit", d.gl_agg)
    y = _row(c, y, "Products / Completed Operations Aggregate", d.gl_agg)
    y = _row(c, y, "Annual Premium", f"${d.gl_premium:,}")
    # THE WORDING HERE IS LOAD-BEARING, and the demo's own self-check caught it.
    # "class code" is a literal `growth_trends` signal phrase, so a GL
    # classification table headed "GL CLASS CODE" CREDITS the WC Payroll /
    # Class Code component on DEMO-A. If the gate ever failed to fire, that
    # component would read PRESENT, the sentence would not name it, and the
    # demo would look like a pass FOR THE WRONG REASON - masking the exact
    # failure it exists to expose. "ISO CODE" / "RATING CLASSIFICATION" state
    # the same thing and match no signal phrase (verified against
    # `_NARRATIVE_SCORE_SIGNALS`).
    y = _head(c, y, "GENERAL LIABILITY RATING SCHEDULE BY LOCATION")
    y = _table(c, y,
               ["LOCATION", "ISO CODE", "RATING CLASSIFICATION", "EXPOSURE BASIS", "AMOUNT"],
               [["1", "91580", f"{d.trade} operations", "Payroll", f"${d.payroll:,}"]],
               [1.0, 1.9, 3.0, 5.1, 6.4])
    y = _head(c, y, "COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", d.prop_carrier)
    y = _row(c, y, "Carrier NAIC", d.prop_naic)
    y = _row(c, y, "Policy Number", d.prop_policy)
    y = _row(c, y, "Policy Period", f"{d.eff} to {d.exp}")
    y = _row(c, y, "Building Limit", d.building)
    y = _row(c, y, "Business Personal Property Limit", d.bpp)
    y = _row(c, y, "Valuation Method", "Replacement Cost Value (RCV)")
    y = _row(c, y, "All Other Perils Deductible", d.aop)
    y = _row(c, y, "Deductible Basis", "Flat dollar amount per occurrence")
    y = _row(c, y, "Coinsurance Percentage", "90%")
    y = _row(c, y, "Annual Premium", f"${d.prop_premium:,}")
    y = _head(c, y, "LOCATION 1 - COPE")
    y = _row(c, y, "Location Address", f"{d.addr}, {d.city}, {d.state} {d.zip}")
    y = _row(c, y, "Occupancy Type", "Contractor shop or yard")
    y = _row(c, y, "Construction Type", "Joisted Masonry")
    y = _row(c, y, "Year Built", d.year_built)
    y = _row(c, y, "Roof Updated", d.roof_year)
    y = _row(c, y, "Total Square Footage", d.sqft)
    y = _row(c, y, "Sprinkler System", "Yes - fully sprinklered")
    y = _row(c, y, "Fire Protection Class", "Protection Class 3")
    y = _row(c, y, "Distance to Hydrant", "180 feet")
    y = _row(c, y, "Fire Department Type", "Full-time paid")
    return y


# Nine of the ten general components. Management Experience is left out ON
# PURPOSE - see the module docstring. Not one Workers Comp signal phrase.
def _narrative(c, y, d: Demo, with_wc: bool):
    y = _head(c, y, "ACCOUNT NARRATIVE")
    y = _para(c, y, f"{d.name} is a family-owned {d.trade.lower()} business established in "
                    f"{d.founded}, now in its {d.years}th year of continuous operation "
                    f"under the same ownership.")
    y = _para(c, y, f"Operations consist of {d.ops}. All work is performed by direct "
                    f"employees from a single owned premises at {d.addr}, {d.city}.")
    y = _para(c, y, f"The workforce is {d.employees} full-time staff. Annual gross sales "
                    f"for the most recent complete year were ${d.revenue:,}.")
    y = _para(c, y, "Risk controls include a written safety program reviewed annually, "
                    "documented ladder and fall-protection training, weekly toolbox talks, "
                    "and an employee handbook issued at hire.")
    y = _para(c, y, "Loss history: the applicant reports no prior losses or claims in the "
                    "last five years.")
    y = _para(c, y, "Coverage discussion: general liability and commercial property terms "
                    "are requested for the coming policy period, on the limits shown above.")
    y = _para(c, y, "The account is being marketed because the incumbent carrier is exiting "
                    "the contractor class and declined to offer renewal terms.")
    y = _para(c, y, f"Premises: one owned location of {d.sqft} square feet, fully "
                    f"sprinklered, in Protection Class 3.")
    if with_wc:
        y = _para(c, y, f"Workers compensation payroll is allocated by class code as shown "
                        f"on the rating page. The current experience modification factor "
                        f"is {d.xmod}, issued by the rating bureau.")
    return y


def build_a(d: Demo, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability and Commercial Property - no other lines requested")
    y = _identity(c, y, d)
    y = _new_page(c, "COVERAGE DETAIL", d.name)
    _gl_and_property(c, y, d)
    y = _new_page(c, "ACCOUNT NARRATIVE", d.name)
    _narrative(c, y, d, with_wc=False)
    c.save()


def build_b(d: Demo, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability, Commercial Property and Workers Compensation")
    y = _identity(c, y, d)
    y = _new_page(c, "COVERAGE DETAIL", d.name)
    y = _gl_and_property(c, y, d)
    y = _new_page(c, "WORKERS COMPENSATION", d.name)
    y = _head(c, y, "WORKERS COMPENSATION AND EMPLOYERS LIABILITY")
    y = _row(c, y, "Carrier", d.wc_carrier)
    y = _row(c, y, "Carrier NAIC", d.wc_naic)
    y = _row(c, y, "Policy Number", d.wc_policy)
    y = _row(c, y, "Policy Period", f"{d.eff} to {d.exp}")
    y = _row(c, y, "E.L. Each Accident", d.el)
    y = _row(c, y, "E.L. Disease - Each Employee", d.el)
    y = _row(c, y, "E.L. Disease - Policy Limit", d.el)
    y = _row(c, y, "Annual Premium", f"${d.wc_premium:,}")
    y = _head(c, y, "RATING INFORMATION")
    y = _row(c, y, "Experience Modification Factor", d.xmod)
    y = _row(c, y, "Rating Bureau", "NCCI")
    y = _row(c, y, "Governing State", d.state)
    y = _row(c, y, "Total Annual Payroll", f"${d.payroll:,}")
    y = _row(c, y, "Payroll Period", "Annual")
    y = _row(c, y, "Owners or Officers Excluded", "No - all owners and officers are included")
    split = [int(d.payroll * 0.55), int(d.payroll * 0.30), d.payroll
             - int(d.payroll * 0.55) - int(d.payroll * 0.30)]
    y = _head(c, y, "PAYROLL BY WORKERS COMPENSATION CLASS CODE")
    y = _table(c, y,
               ["CLASS CODE", "DESCRIPTION", "STATE", "ANNUAL PAYROLL", "FULL-TIME", "PART-TIME"],
               [[d.wc_code, f"{d.trade} operations", d.state, f"${split[0]:,}",
                 max(1, int(d.employees * 0.6)), 2],
                ["8810", "Clerical office employees", d.state, f"${split[1]:,}",
                 max(1, int(d.employees * 0.2)), 1],
                ["8742", "Outside sales", d.state, f"${split[2]:,}",
                 max(1, int(d.employees * 0.2)), 0]],
               [1.0, 1.85, 3.4, 4.05, 5.35, 6.35])
    y = _new_page(c, "ACCOUNT NARRATIVE", d.name)
    _narrative(c, y, d, with_wc=True)
    c.save()


_SCRIPT = """# SYS-04 DEMO - run this in front of Brent

Generated {stamp}. Seed **{seed}** - re-create this exact pair with
`py backend/scripts/make_sys04_demo.py --seed {seed}`, or run with no seed for a
completely different applicant, limits and carriers.

## The setup, in one sentence

> *"Two submissions. Same applicant, same limits, same narrative. One carries
> Workers' Compensation and one does not. Watch what the product asks for."*

| | |
|---|---|
| **DEMO-A** | Complete GL + Property contractor. **No Workers' Comp.** |
| **DEMO-B** | Byte-identical, **plus a real Workers' Comp policy** - payroll, three class codes, experience mod, EL limits. |

Both are COMPLETE submissions - producer name, NAICS, SIC, GL class codes,
COPE, valuation method, AOP deductible, coinsurance are all stated. **The screen
is quiet except for the thing being shown.**

## Run it

Two separate sessions. Do not upload both together.

1. Upload **DEMO-A** -> Continue -> tick **ACORD 125** -> Generate -> open the SQS panel
2. Upload **DEMO-B** -> Continue -> tick **ACORD 125** -> Generate -> open the SQS panel

Put the two panels side by side.

## What he will see

Open **Narrative Components** on each:

| | DEMO-A (no WC) | DEMO-B (real WC) |
|---|---|---|
| Component count | **10** | **12** |
| *WC Payroll / Class Code Context* | absent | present |
| *EMOD / XMOD Information* | absent | present |
| WC questions in the questionnaire | none | asked |
| `WC Supplemental` under Exposure | 100% - nothing charged | scored on real data |

**THE COUNT IS THE PROOF. Count the list on each panel: 10 and 12.**

Do NOT go looking for the "Narrative includes ... but does not include ..."
sentence on these two - it will not be there. That recommendation only renders
when Narrative Quality falls **below 80**, and both demo files score 90 precisely
because they are complete submissions. Its absence on DEMO-A is itself the point:
on the client's original screenshot that card was present and named two Workers
Comp topics.

If you want the sentence visible as well, run the thin diagnostic fixture
`sys04_test_data/W1_no_workers_comp.pdf` alongside - it scores 78 and therefore
prints:

> *"Narrative includes Account Overview, Operations Description, Years in
> Business, Risk Controls **(+5 more)**, but does not include Management
> Experience"*

4 named + 5 = 9 present out of **10**. Against `W3_genuine_workers_comp.pdf`,
which prints **(+7 more)** = 11 of **12**. Same narrative, same single gap, two
denominators - **the product printing its own arithmetic.**

## The line to use

> *"It is not that we stopped asking about Workers' Comp - DEMO-B shows we still
> do. It is that we now ask only when the line is actually there."*

DEMO-B is the important half. Without it, a product that had simply gone silent
on Workers' Comp would look identical to a fixed one.

## Also visible on DEMO-A

* **Loss History** reads *"Narrative states no losses / None stated"* - not
  *"Conflicting"*. The old build printed a loss-run contradiction on every clean
  submission with no loss runs anywhere.
* The **"Check if none"** box on ACORD 125 page 4 ships **blank**. Tick it and
  Loss History moves **40 -> 60**; untick it and it returns. Previously the box
  arrived pre-ticked from a narrative sentence, so nobody could actually attest.
* No cluster titled *"WC / GL class code alignment"* - the GL-only finding now
  reads *"GL class code alignment"*.

## RUN W1 ALONGSIDE - a clean screen needs a control

Both demo files now produce **no warnings and no hard stops at all**. That is
correct - they state every field the checks look for - but it creates a fair
suspicion, and it is the first thing a sceptical funder should ask:

> *"How do I know you didn't just switch the warnings off?"*

Answer it before he asks, with a third upload. **`sys04_test_data/W1_no_workers_comp.pdf`**
is deliberately thin, and on the SAME build it produces four warnings, a COPE
hard stop, and the narrative recommendation card:

> *"Narrative includes Account Overview, Operations Description, Years in
> Business, Risk Controls **(+5 more)**, but does not include Management
> Experience"*

Three things come out of that one extra session:

1. **The warning engine is alive** - same code, noisy document, warnings fire.
2. **The arithmetic is visible.** 4 named + 5 = 9 present of **10**. Run
   `W3_genuine_workers_comp.pdf` and the same sentence reads **(+7 more)** =
   11 of **12**. The product prints its own denominator.
3. **The WC-language fix is visible** - the cluster heading reads
   *"GL class code alignment"*, where the old build said *"WC / GL class code
   alignment"* on a package with no Workers Comp.

## One asymmetry he may spot, and the honest answer

DEMO-B's **Evidence Basis** panel lists far fewer "Stated in narrative" entries
than DEMO-A's. That is document CLASSIFICATION, not a defect: DEMO-B is
classified an *Experience Modification Worksheet* because of its rating page,
DEMO-A an *Underwriting Narrative*, and the "stated in narrative" provenance
label is only applied to facts drawn from a narrative-classified document. It
has no effect on the score or on the Workers Comp behaviour being shown.

## Say this too, before he asks

**On a submission carrying only one or two policies where extraction still flags
Workers' Comp, the asks can remain.** Measured: 83% of realistic non-WC packages
are corrected, 17% fall back to the previous behaviour. A miss leaves the old
behaviour - it never produces a wrong answer, and it never hides Workers' Comp
asks from a package that genuinely has the line (100,000 adversarial shapes,
zero violations).

Naming your own residual before he finds it is the difference between thorough
and caught out.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260905,
                    help="default is fixed so the demo is rehearsable")
    args = ap.parse_args()
    d = Demo(random.Random(args.seed))

    os.makedirs(OUT_DIR, exist_ok=True)
    a = os.path.join(OUT_DIR, "DEMO-A_no_workers_comp.pdf")
    b = os.path.join(OUT_DIR, "DEMO-B_with_workers_comp.pdf")
    build_a(d, a)
    build_b(d, b)
    print(f"  wrote {a}")
    print(f"  wrote {b}")
    script = os.path.join(OUT_DIR, "DEMO-SCRIPT.md")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_SCRIPT.format(stamp=date.today().isoformat(), seed=args.seed))
    print(f"  wrote {script}")
    print(f"\nApplicant: {d.name}   |   seed {args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
