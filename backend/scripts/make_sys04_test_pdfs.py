"""make_sys04_test_pdfs.py - live test kit for SYS-04 (line-gated WC asks).

    py backend/scripts/make_sys04_test_pdfs.py            # random values
    py backend/scripts/make_sys04_test_pdfs.py --seed 7   # reproducible

Writes to sys04_test_data/ at the repo root, plus README-HOW-TO-TEST.md
listing the exact values THIS run generated.

EVERY VALUE IS RANDOM. THE STRUCTURE IS NOT.
--------------------------------------------
Owner's instruction: *"I need to test this on any random values not just some
example because we don't know what a user can upload or type."*

So the applicant name, address, city, state, ZIP, FEIN, carrier names, NAIC
numbers, policy numbers, dates, premiums, limits, payrolls, employee counts,
vehicle counts and narrative wording are all drawn fresh on every run. What is
held constant is the only thing under test: **which coverage lines the document
evidences, and how**. A fix that passed by memorising "ABC Roofing" or
"$1,000,000" fails here on the second run.

Run it twice before you believe a pass.

THE SIX PACKAGES
----------------
Each is ONE file and ONE session. They are separate on purpose - merging them
would let one document's Workers Comp evidence rescue another's.

  W1  NO WC ANYWHERE, flag should be FALSE          THE REPORTED CASE
      A GL + Property contractor. Rich narrative, no Workers Comp word in it.
      Expect: no WC narrative asks, no WC deductions, Narrative Quality up.

  W2  CERTIFICATE TRAP, flag will be TRUE           THE HARD ONE
      A certificate printing the ACORD 25 heading "WORKERS COMPENSATION AND
      EMPLOYERS' LIABILITY" with three E.L. limit labels and a BLANK row,
      above three real policies that DO carry numbers and premiums.
      This is what makes `has_workers_comp` true off preprinted text.
      Expect: still no WC asks - the granted-line census reads the blank row.

  W3  GENUINE WORKERS COMP                          THE POSITIVE CONTROL
      A real WC policy with payroll, class codes and an experience mod.
      Expect: every WC ask and deduction PRESENT. Without W3, W1 and W2 could
      pass simply because the product stopped asking about WC at all.

  W4  WC APPLIED FOR, NOT YET CARRIED               "intentionally requested"
      No WC policy anywhere; you select ACORD 130 by hand.
      Expect: WC asks COME BACK. Applying for a coverage is the client's own
      "actively active or intentionally requested".

  W5  EXPLICIT DENIAL                               the other absence route
      A schedule printing "WORKERS COMPENSATION - NO COVERAGE".
      Expect: no WC asks, by denial rather than by census.

  W6  BUILDERS RISK / ASSIGNED RISK                 THE ACORD 133 PAIR
      Page 1 is a construction project (builders risk evidence, no WC).
      Page 2 is an assigned-risk WC submission.
      Expect: ACORD 133 offered for the WC half and NEVER for the construction
      half, and the construction facts must not read as Workers Comp evidence.

WHAT IS DELIBERATELY KEPT OUT
-----------------------------
  * No "N/A" / "None" / "unknown" anywhere except W5's explicit denial. Those
    are the still-open non-answer path (CLAUDE.md "GAP 1") and would
    manufacture a failure that is not SYS-04's.
  * No renewal language. A routed renewal moves dates to prior_* and changes
    what the identity resolver stamps - a different feature's noise.
  * W1 and W2 contain NO Workers Comp vocabulary in their narrative prose -
    not "class code", not "payroll by class", not "experience modifier". Those
    are the literal signal phrases the narrative scanner credits
    `growth_trends` / `target_markets` on, so including one would credit the
    very components the test says must be absent.
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
    "sys04_test_data",
)

# ── Random value pools ───────────────────────────────────────────────────────
_TRADES = [
    ("Roofing", "residential re-roofing and gutter replacement"),
    ("Plumbing", "commercial plumbing installation and drain service"),
    ("Electrical", "commercial electrical fit-out and panel upgrades"),
    ("Landscaping", "grounds maintenance and seasonal planting"),
    ("HVAC", "heating and air conditioning installation and service"),
    ("Masonry", "brick and block work on low-rise commercial buildings"),
    ("Bakery", "wholesale bread and pastry production"),
    ("Print Shop", "commercial offset and digital printing"),
    ("Machine Shop", "precision metal fabrication and CNC machining"),
    ("Auto Repair", "passenger vehicle mechanical and body repair"),
]
_SUFFIX = ["LLC", "Inc.", "Corp.", "Company", "& Sons LLC", "Group Inc.", "Holdings LLC"]
_FIRST = ["Bristol", "Kenmore", "Ashland", "Fairview", "Northgate", "Halstead",
          "Wexford", "Ridgeway", "Calder", "Pinehurst", "Marlow", "Ardmore"]
_STREETS = ["Mill Road", "Commerce Way", "Industrial Parkway", "Depot Street",
            "Foundry Lane", "Prospect Avenue", "Cedar Court", "Harbor Boulevard"]
_CITIES = [("Akron", "OH"), ("Boise", "ID"), ("Dover", "DE"), ("Fresno", "CA"),
           ("Gary", "IN"), ("Lowell", "MA"), ("Ogden", "UT"), ("Reno", "NV"),
           ("Salem", "OR"), ("Tulsa", "OK"), ("Waco", "TX"), ("Yonkers", "NY")]
_CARRIERS = ["Hartland Mutual Insurance Company", "Cornerstone Casualty Group",
             "Ironbridge Indemnity Company", "Sentinel Peak Insurance Company",
             "Redwood Standard Mutual", "Blackstone Bay Casualty Company",
             "Granite Harbor Insurance Company", "Silverline Mutual Casualty"]
_WC_CARRIERS = ["Keystone Compensation Mutual", "Anvil State Insurance Fund",
                "Meridian Workers Insurance Company", "Cascade Comp Mutual"]


class Kit:
    """One run's random values. Printed into the README so a failure is
    reproducible and a pass can be checked by eye."""

    def __init__(self, rnd: random.Random):
        self.rnd = rnd
        trade, ops = rnd.choice(_TRADES)
        self.trade = trade
        self.ops = ops
        self.name = f"{rnd.choice(_FIRST)} {trade} {rnd.choice(_SUFFIX)}"
        self.dba = f"{rnd.choice(_FIRST)} {trade}"
        city, st = rnd.choice(_CITIES)
        self.city, self.state = city, st
        self.zip = f"{rnd.randint(10000, 99999)}"
        self.addr = f"{rnd.randint(100, 9899)} {rnd.choice(_STREETS)}"
        self.fein = f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}"
        self.phone = f"({rnd.randint(200, 989)}) {rnd.randint(200, 999)}-{rnd.randint(1000, 9999)}"
        self.years = rnd.randint(4, 41)
        self.founded = date.today().year - self.years
        self.employees = rnd.randint(3, 180)
        self.revenue = rnd.randrange(400_000, 42_000_000, 50_000)
        self.payroll = rnd.randrange(180_000, 9_000_000, 10_000)
        # Policy term: a random start inside the next year, never a renewal.
        start = date.today() + timedelta(days=rnd.randint(5, 300))
        self.eff = start.strftime("%m/%d/%Y")
        self.exp = start.replace(year=start.year + 1).strftime("%m/%d/%Y")
        self.carriers = rnd.sample(_CARRIERS, 4)
        self.wc_carrier = rnd.choice(_WC_CARRIERS)
        self.naics = [f"{rnd.randint(10000, 44999)}" for _ in range(5)]
        self.policies = [self._policy() for _ in range(6)]
        self.premiums = [rnd.randrange(1200, 90_000, 50) for _ in range(6)]
        occ = rnd.choice([500_000, 1_000_000, 2_000_000])
        self.gl_occ = f"${occ:,}"
        self.gl_agg = f"${occ * 2:,}"
        self.auto_csl = f"${rnd.choice([500_000, 1_000_000]):,}"
        self.umb = f"${rnd.choice([1, 2, 3, 5]) * 1_000_000:,}"
        self.bldg = f"${rnd.randrange(250_000, 9_000_000, 25_000):,}"
        self.bpp = f"${rnd.randrange(40_000, 2_000_000, 5_000):,}"
        self.el_acc = f"${rnd.choice([100_000, 500_000, 1_000_000]):,}"
        self.xmod = f"{rnd.uniform(0.62, 1.48):.2f}"
        self.wc_classes = rnd.sample(
            [("5183", "Plumbing"), ("5190", "Electrical Wiring"),
             ("5551", "Roofing"), ("8810", "Clerical Office"),
             ("9014", "Building Operation"), ("3632", "Machine Shop"),
             ("2003", "Bakery"), ("8380", "Automobile Repair")], 3)
        self.project_cost = f"${rnd.randrange(300_000, 24_000_000, 25_000):,}"
        self.completion = (date.today() + timedelta(days=rnd.randint(120, 900))
                           ).strftime("%m/%d/%Y")

    def _policy(self) -> str:
        r = self.rnd
        shape = r.randint(0, 2)
        if shape == 0:
            return f"{r.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{r.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{r.randint(100000, 999999)}"
        if shape == 1:
            return f"{r.randint(1, 9)}{r.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{r.randint(10, 99)}-{r.randint(10, 99)}-{r.randint(10, 99)}"
        return f"{r.choice('CGLPWU')}{r.randint(1000000, 9999999)}"


# ── Layout helpers (same shapes as make_sys06/07, proven extractable) ────────

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


def _identity(c, y, k: Kit):
    y = _head(c, y, "APPLICANT")
    y = _row(c, y, "Named Insured", k.name)
    y = _row(c, y, "DBA", k.dba)
    y = _row(c, y, "Mailing Address", f"{k.addr}, {k.city}, {k.state} {k.zip}")
    y = _row(c, y, "FEIN", k.fein)
    y = _row(c, y, "Telephone", k.phone)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    return y


def _coverage(c, y, heading, carrier, naic, policy, premium, limits, k: Kit):
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Carrier NAIC", naic)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{k.eff} to {k.exp}")
    for label, value in limits:
        y = _row(c, y, label, value)
    y = _row(c, y, "Annual Premium", f"${premium:,}")
    return y


# A narrative rich enough to score, carrying NINE of the ten general components
# and NOT ONE Workers Comp signal phrase. Management is deliberately left out so
# the "does not include ..." sentence still has something honest to name - if it
# came back empty we could not tell a working gate from an empty message.
def _general_narrative(c, y, k: Kit, mention_wc: bool) -> float:
    y = _head(c, y, "ACCOUNT NARRATIVE")
    y = _para(c, y, f"{k.name} is a family-owned {k.trade.lower()} business founded "
                    f"in {k.founded}, now in its {k.years}th year of operation.")
    y = _para(c, y, f"Operations consist of {k.ops}. The applicant works from a single "
                    f"premises at {k.addr} in {k.city}, {k.state}.")
    y = _para(c, y, f"The workforce is {k.employees} full-time staff. Annual gross sales "
                    f"are ${k.revenue:,}.")
    y = _para(c, y, "Risk controls include a written safety program, documented tool and "
                    "ladder inspections, and an employee handbook issued at hire.")
    y = _para(c, y, "Loss history: the applicant reports no prior losses or claims in the "
                    "last five years.")
    y = _para(c, y, "Coverage discussion: the applicant seeks general liability and "
                    "commercial property terms for the coming policy period.")
    y = _para(c, y, "We are marketing this account because the prior carrier declined to "
                    "offer renewal terms after exiting the class.")
    if mention_wc:
        y = _para(c, y, "Workers compensation and employers liability are placed elsewhere "
                        "and are not part of this submission.")
    return y


# ── W1 - the reported case ───────────────────────────────────────────────────

def build_w1(k: Kit, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability and Commercial Property - no other lines")
    y = _identity(c, y, k)
    y = _coverage(c, y, "GENERAL LIABILITY", k.carriers[0], k.naics[0],
                  k.policies[0], k.premiums[0],
                  [("Each Occurrence Limit", k.gl_occ),
                   ("General Aggregate Limit", k.gl_agg)], k)
    y = _coverage(c, y, "COMMERCIAL PROPERTY", k.carriers[1], k.naics[1],
                  k.policies[1], k.premiums[1],
                  [("Building Limit", k.bldg),
                   ("Business Personal Property", k.bpp)], k)
    y = _new_page(c, "ACCOUNT NARRATIVE", k.name)
    _general_narrative(c, y, k, mention_wc=False)
    c.save()


# ── W2 - the certificate trap ────────────────────────────────────────────────

def build_w2(k: Kit, path: str) -> None:
    """A certificate laid out the way ACORD 25 prints it.

    The Workers Compensation block is PREPRINTED - heading plus the three E.L.
    limit labels - and its row carries NO carrier, NO policy number, NO dates.
    Three other lines carry real numbers. That is exactly the shape that makes
    `has_workers_comp` true off heading text alone, and exactly the shape the
    granted-line census must read as an absence.
    """
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only.")
    y = _identity(c, y, k)
    y = _head(c, y, "COVERAGES")
    y = _table(
        c, y,
        ["TYPE OF INSURANCE", "INSR LTR", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
        [
            ["COMMERCIAL GENERAL LIABILITY", "A", k.policies[0], k.eff, k.exp,
             f"EACH OCCURRENCE {k.gl_occ}"],
            ["", "", "", "", "", f"GENERAL AGGREGATE {k.gl_agg}"],
            ["AUTOMOBILE LIABILITY", "B", k.policies[1], k.eff, k.exp,
             f"COMBINED SINGLE LIMIT {k.auto_csl}"],
            ["UMBRELLA LIAB", "C", k.policies[2], k.eff, k.exp,
             f"EACH OCCURRENCE {k.umb}"],
        ],
        [1.0, 3.15, 3.75, 4.95, 5.75, 6.5],
    )
    # THE TRAP. Heading and labels only - no carrier, no number, no dates.
    y = _head(c, y, "WORKERS COMPENSATION AND EMPLOYERS' LIABILITY")
    y = _para(c, y, "ANY PROPRIETOR/PARTNER/EXECUTIVE OFFICER/MEMBER EXCLUDED?")
    y = _para(c, y, "(Mandatory in NH) If yes, describe under DESCRIPTION OF OPERATIONS below")
    y = _row(c, y, "E.L. EACH ACCIDENT", "")
    y = _row(c, y, "E.L. DISEASE - EA EMPLOYEE", "")
    y = _row(c, y, "E.L. DISEASE - POLICY LIMIT", "")
    y = _head(c, y, "PREMIUM SUMMARY")
    y = _table(c, y, ["LINE OF BUSINESS", "CARRIER", "ANNUAL PREMIUM"],
               [["Commercial General Liability", k.carriers[0], f"${k.premiums[0]:,}"],
                ["Business Auto", k.carriers[1], f"${k.premiums[1]:,}"],
                ["Commercial Umbrella", k.carriers[2], f"${k.premiums[2]:,}"]],
               [1.0, 3.4, 6.0])
    y = _new_page(c, "DESCRIPTION OF OPERATIONS", k.name)
    _general_narrative(c, y, k, mention_wc=False)
    c.save()


# ── W3 - the positive control ────────────────────────────────────────────────

def build_w3(k: Kit, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "WORKERS COMPENSATION APPLICATION",
              "A real Workers Compensation policy - every WC ask must SURVIVE")
    y = _identity(c, y, k)
    y = _coverage(c, y, "WORKERS COMPENSATION AND EMPLOYERS LIABILITY",
                  k.wc_carrier, k.naics[2], k.policies[3], k.premiums[3],
                  [("E.L. Each Accident", k.el_acc),
                   ("E.L. Disease - Each Employee", k.el_acc),
                   ("E.L. Disease - Policy Limit", k.el_acc)], k)
    y = _coverage(c, y, "GENERAL LIABILITY", k.carriers[0], k.naics[0],
                  k.policies[0], k.premiums[0],
                  [("Each Occurrence Limit", k.gl_occ),
                   ("General Aggregate Limit", k.gl_agg)], k)
    y = _head(c, y, "RATING INFORMATION")
    y = _row(c, y, "Experience Modification Factor", k.xmod)
    y = _row(c, y, "Rating Bureau", "NCCI")
    y = _row(c, y, "Governing State", k.state)
    y = _row(c, y, "Total Annual Payroll", f"${k.payroll:,}")
    per = [k.payroll // 2, k.payroll // 3, k.payroll - k.payroll // 2 - k.payroll // 3]
    y = _table(c, y, ["CLASS CODE", "DESCRIPTION", "STATE", "ANNUAL PAYROLL", "EMPLOYEES"],
               [[code, desc, k.state, f"${amt:,}", n] for (code, desc), amt, n in
                zip(k.wc_classes, per, [max(1, k.employees // 3)] * 3)],
               [1.0, 2.0, 4.1, 4.9, 6.4])
    y = _new_page(c, "ACCOUNT NARRATIVE", k.name)
    y = _general_narrative(c, y, k, mention_wc=False)
    y = _para(c, y, f"Workers compensation payroll is allocated by class code as shown on "
                    f"the rating page. The current experience modifier is {k.xmod}, issued "
                    f"by the rating bureau.")
    c.save()


# ── W4 - applied for, not carried ────────────────────────────────────────────

def build_w4(k: Kit, path: str) -> None:
    """No Workers Comp policy anywhere. YOU select ACORD 130 by hand.

    This is the client's "intentionally requested" clause. The document alone
    must read as no-WC; selecting the application form must bring the WC asks
    back. It is the one package where the correct answer CHANGES based on
    something you do in the UI rather than something in the file.
    """
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "New venture - seeking terms, no expiring coverage")
    y = _identity(c, y, k)
    y = _coverage(c, y, "GENERAL LIABILITY", k.carriers[0], k.naics[0],
                  k.policies[0], k.premiums[0],
                  [("Each Occurrence Limit", k.gl_occ),
                   ("General Aggregate Limit", k.gl_agg)], k)
    # NO payroll figure here. Live run 2026-09-05: "Total Annual Payroll" was
    # extracted as `wc_payroll`, so `line_presence` answered PRESENT from the
    # FACT and W4 stopped isolating the "intentionally requested" clause it
    # exists to test. Headcount alone carries no line.
    y = _head(c, y, "EMPLOYEE INFORMATION")
    y = _row(c, y, "Number of Employees", k.employees)
    y = _row(c, y, "Annual Gross Sales", f"${k.revenue:,}")
    y = _new_page(c, "ACCOUNT NARRATIVE", k.name)
    _general_narrative(c, y, k, mention_wc=False)
    c.save()


# ── W5 - explicit denial ─────────────────────────────────────────────────────

def build_w5(k: Kit, path: str) -> None:
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "POLICY DECLARATIONS",
              "Schedule of coverages - one line is explicitly declined")
    y = _identity(c, y, k)
    y = _head(c, y, "SCHEDULE OF COVERAGES AND PREMIUMS")
    y = _table(c, y, ["COVERAGE PART", "CARRIER", "POLICY NUMBER", "PREMIUM"],
               [["Commercial General Liability", k.carriers[0], k.policies[0],
                 f"${k.premiums[0]:,}"],
                ["Commercial Property", k.carriers[1], k.policies[1],
                 f"${k.premiums[1]:,}"],
                ["Commercial Umbrella", k.carriers[2], k.policies[2],
                 f"${k.premiums[2]:,}"],
                ["Workers Compensation", "", "", "NO COVERAGE"]],
               [1.0, 3.0, 5.1, 6.6])
    # Underlying limits, so the umbrella attachment hard stop (a different
    # feature) does not fire and drown the WC denial this file is testing.
    y = _row(c, y, "General Liability Each Occurrence", k.gl_occ)
    y = _row(c, y, "General Liability Aggregate", k.gl_agg)
    y = _row(c, y, "Business Auto Combined Single Limit", k.auto_csl)
    y = _row(c, y, "Umbrella Each Occurrence", k.umb)
    y = _row(c, y, "Policy Period", f"{k.eff} to {k.exp}")
    y = _para(c, y, "")
    y = _row(c, y, "Workers Compensation", "NO COVERAGE")
    y = _new_page(c, "ACCOUNT NARRATIVE", k.name)
    _general_narrative(c, y, k, mention_wc=True)
    c.save()


# ── W6 - the ACORD 133 pair ──────────────────────────────────────────────────

def build_w6(k: Kit, path: str) -> None:
    """Two pages, two opposite expectations for ONE form number.

    Page 1 is a construction project: real builders-risk evidence, no Workers
    Comp. ACORD 133 must NOT be offered, and the project facts must not read as
    Workers Comp evidence.

    Page 2 is an assigned-risk Workers Comp submission - the coverage ACORD 133
    actually documents. It SHOULD be offered there, alongside ACORD 130.
    """
    c = canvas.Canvas(path, pagesize=letter)
    y = _page(c, "BUILDERS RISK / COURSE OF CONSTRUCTION SUPPLEMENT",
              "Construction project - NO Workers Compensation on this account")
    y = _identity(c, y, k)
    y = _head(c, y, "PROJECT INFORMATION")
    y = _row(c, y, "Project Address", f"{k.rnd.randint(100, 9899)} "
                                      f"{k.rnd.choice(_STREETS)}, {k.city}, {k.state} {k.zip}")
    y = _row(c, y, "Total Construction Cost", k.project_cost)
    y = _row(c, y, "Estimated Completion Date", k.completion)
    y = _row(c, y, "Construction Type", "Joisted Masonry")
    y = _row(c, y, "Project Owner", f"{k.rnd.choice(_FIRST)} Development Partners LLC")
    y = _row(c, y, "General Contractor", k.name)
    y = _row(c, y, "Insured Interest", "Contractor and Owner as their interests may appear")
    y = _para(c, y, "Course of construction coverage is requested for a ground-up "
                    "commercial building. Builders risk terms only.")
    y = _coverage(c, y, "GENERAL LIABILITY", k.carriers[0], k.naics[0],
                  k.policies[0], k.premiums[0],
                  [("Each Occurrence Limit", k.gl_occ)], k)
    # A short account block so the Tier-1 basics are present and the WC verdict
    # is not buried under unrelated "key details missing" noise.
    y = _head(c, y, "APPLICANT PROFILE")
    y = _row(c, y, "Years in Business", f"{k.years} (founded {k.founded})")
    y = _row(c, y, "Number of Employees", k.employees)
    y = _row(c, y, "Annual Gross Sales", f"${k.revenue:,}")

    y = _new_page(c, "WORKERS COMPENSATION INSURANCE PLAN",
                  "ASSIGNED RISK SECTION - a separate account")
    other = f"{k.rnd.choice(_FIRST)} {k.rnd.choice(_TRADES)[0]} {k.rnd.choice(_SUFFIX)}"
    y = _row(c, y, "Named Insured", other)
    y = _row(c, y, "Mailing Address", f"{k.rnd.randint(100, 9899)} "
                                      f"{k.rnd.choice(_STREETS)}, {k.city}, {k.state} {k.zip}")
    y = _para(c, y, "This applicant has been declined by the voluntary market and is "
                    "applying to the state workers compensation insurance plan. The "
                    "residual market assigned risk pool will assign a carrier.")
    y = _coverage(c, y, "WORKERS COMPENSATION AND EMPLOYERS LIABILITY",
                  k.wc_carrier, k.naics[2], k.policies[3], k.premiums[3],
                  [("E.L. Each Accident", k.el_acc)], k)
    y = _row(c, y, "State Developing Highest Payroll", k.state)
    y = _row(c, y, "Total Annual Payroll", f"${k.payroll:,}")
    c.save()


# ── README ───────────────────────────────────────────────────────────────────

_README = """# SYS-04 LIVE TEST KIT - generated {stamp}

**Seed for this run: `{seed}`.** Re-generate the identical set with:

    py backend/scripts/make_sys04_test_pdfs.py --seed {seed}

Run WITHOUT `--seed` to get a completely different set of values. **Do that at
least once** - a fix that only works on remembered values fails on run two.

## The values THIS run used

| | |
|---|---|
| Applicant | {name} |
| DBA | {dba} |
| Address | {addr}, {city}, {state} {zip} |
| FEIN | {fein} |
| Trade | {trade} |
| Years in business | {years} (founded {founded}) |
| Employees | {employees} |
| Annual payroll | ${payroll:,} |
| Policy term | {eff} to {exp} |
| GL limits | {gl_occ} occurrence / {gl_agg} aggregate |
| Umbrella | {umb} |
| WC carrier (W3, W6 p2) | {wc_carrier} |
| Experience mod (W3) | {xmod} |
| WC class codes (W3) | {classes} |
| Project cost (W6 p1) | {project_cost} |

---

## HOW TO RUN IT

**Six separate sessions. Do not upload two of these files together** - one
file's Workers Comp evidence would rescue another's.

For each file: upload it, let extraction finish, then look at the pre-form
Review screen and the SQS panel. W4 needs one extra step (below).

---

### W1 - `W1_no_workers_comp.pdf`  ·  THE REPORTED CASE

A GL + Property contractor. No Workers Comp anywhere.

**PASS:**
- The Narrative Quality recommendation does **NOT** mention *"WC Payroll / Class
  Code Context"* or *"EMOD / XMOD Information"*.
- No Workers Comp questions in the client questionnaire.
- No WC deductions on the Exposure pillar.

**FAIL:** either WC label appears in the "does not include ..." sentence.

*Note:* the sentence SHOULD still name **Management Experience** - that is
deliberate. An empty sentence would not prove the gate works.

---

### W2 - `W2_certificate_blank_wc_row.pdf`  ·  **THE ONE THAT MATTERS**

A certificate printing the ACORD 25 Workers Comp heading and the three E.L.
limit labels, with a **blank** WC row, above three real policies.

This is the shape that turns `has_workers_comp` on from preprinted text alone.

**PASS: identical to W1.** No WC narrative asks, no WC deductions.

**FAIL:** WC asks appear. If they do, send me the whole SQS panel - it means
the granted-line census did not read the blank row, and I need to see what
`coverage_lines` extraction produced.

---

### W3 - `W3_genuine_workers_comp.pdf`  ·  THE POSITIVE CONTROL

A real WC policy with payroll, three class codes and an experience mod.

**PASS: every Workers Comp ask is PRESENT.** WC questions in the
questionnaire, WC items on the checklist, WC deductions where data is missing.

**This is the most important file after W2.** If W3 also goes quiet, W1 and W2
are passing for the wrong reason - the product would have stopped asking about
Workers Comp entirely.

---

### W4 - `W4_wc_applied_for.pdf`  ·  "INTENTIONALLY REQUESTED"

No WC policy in the document.

1. Upload and check the Review screen -> **no WC asks** (like W1).
2. Now **manually add ACORD 130** to the selected forms and re-generate.
3. **PASS: the WC asks COME BACK.**

**FAIL:** the WC asks stay hidden after you select ACORD 130. That means a real
Workers Comp application would lose all its WC checks.

---

### W5 - `W5_explicit_wc_denial.pdf`  ·  THE OTHER ABSENCE ROUTE

A schedule printing `Workers Compensation ... NO COVERAGE`.

**PASS: same as W1** - reached by an explicit denial rather than by census.

---

### W6 - `W6_builders_risk_and_assigned_risk.pdf`  ·  THE ACORD 133 PAIR

Page 1 is a construction project. Page 2 is an assigned-risk WC submission.

**PASS:**
- The recommended-forms list does **NOT** offer *"ACORD 133 - Builders Risk
  Application"* for the construction project. That label should not exist
  anywhere in the product any more.
- Where ACORD 133 IS offered, it is named **"Workers Compensation Insurance
  Plan (Assigned Risk) Section"**.
- The construction project's facts do not switch on Workers Comp anything.

**FAIL:** the words "Builders Risk Application" appear next to ACORD 133.

---

## WHAT TO SEND ME BACK

For each of the six, a screenshot of:

1. the **pre-form Review screen** (Submission Readiness + the issue list), and
2. the **SQS panel** with the pillar rows expanded (so I can see Narrative
   Quality and Exposure Consistency), and
3. the **client questionnaire** question list.

Plus, in text:

- the **seed line** printed at the top of this file, and
- for any FAIL, the exact sentence you saw, copied verbatim.

If a run behaves oddly and you want me to look deeper, also grep the backend
log for these two lines and paste what you find:

    coverage flag reconciliation
    line_presence

## DO YOU NEED TO GENERATE FORMS?

**Only for W4** (select ACORD 130 manually, step 2). For the other five, the
pre-form Review screen and the SQS panel are enough - generating forms is
optional and only worth doing if you want to see the stamped PDFs too.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None,
                    help="reproduce a previous run; omit for fresh random values")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(1, 10**6)
    rnd = random.Random(seed)
    k = Kit(rnd)

    os.makedirs(OUT_DIR, exist_ok=True)
    files = [
        ("W1_no_workers_comp.pdf", build_w1),
        ("W2_certificate_blank_wc_row.pdf", build_w2),
        ("W3_genuine_workers_comp.pdf", build_w3),
        ("W4_wc_applied_for.pdf", build_w4),
        ("W5_explicit_wc_denial.pdf", build_w5),
        ("W6_builders_risk_and_assigned_risk.pdf", build_w6),
    ]
    for filename, builder in files:
        path = os.path.join(OUT_DIR, filename)
        builder(k, path)
        print(f"  wrote {path}")

    readme = _README.format(
        stamp=date.today().isoformat(), seed=seed,
        name=k.name, dba=k.dba, addr=k.addr, city=k.city, state=k.state,
        zip=k.zip, fein=k.fein, trade=k.trade, years=k.years,
        founded=k.founded, employees=k.employees, payroll=k.payroll,
        eff=k.eff, exp=k.exp, gl_occ=k.gl_occ, gl_agg=k.gl_agg, umb=k.umb,
        wc_carrier=k.wc_carrier, xmod=k.xmod,
        classes=", ".join(f"{c} {d}" for c, d in k.wc_classes),
        project_cost=k.project_cost,
    )
    rp = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(readme)
    print(f"  wrote {rp}")
    print(f"\nSEED = {seed}   (re-run with --seed {seed} for the identical set)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
