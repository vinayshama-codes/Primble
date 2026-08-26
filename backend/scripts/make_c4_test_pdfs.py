"""make_c4_test_pdfs.py - live test packages for V1 item C4 (Contextual
Questionnaire Logic, client master-plan section 4).

    py backend/scripts/make_c4_test_pdfs.py

Writes to test_data_c4/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks and exactly what to send back.

THE DESIGN RULE THIS FILE IS BUILT ON (learned the hard way, 2026-08-26)
-----------------------------------------------------------------------
The FIRST version of these fixtures could not test what it was written to test.
S2, S3 and S4 each PRINTED the judgment values whose routing they existed to
prove - X-Mod, covered-auto symbols, umbrella limit - so extraction found them,
`_fact_is_filled` marked them already-provided, and no question was ever
generated. Three scenarios produced zero routing evidence and looked like passes.

    A scenario can only test the ROUTING of a value it does NOT state.

So every scenario below now splits its content deliberately:

    STATE   what establishes that the coverage and the exposure exist, so the
            producer selects the form and the question is generated at all;
    OMIT    the exact values whose routing is being tested, so they surface as
            questions instead of being suppressed.

Each scenario's docstring lists its OMITS, and `_verify()` at the bottom FAILS
THE BUILD if an omitted term ever reappears in the generated text. That check is
not decoration - it is the only thing standing between this file and a repeat of
the first version.

Scenario -> the C4 clause it proves live
    S1  GL + property, values omitted        4.3 / 4.4  the headline split:
                                                   characteristics -> Client,
                                                   terms -> Agency
    S2  Workers comp, rating values omitted  4.10 X-Mod, payroll period, officer
                                                   treatment, WC class, SIC
    S3  Commercial auto, structure omitted   4.9  symbols/limits/deductibles ->
                                                   Agency, schedules -> Client
    S4  Umbrella, all structure omitted      4.11 umbrella is producer-facing
    S5  Two applications, CONFLICTING        4.1 Step 5 + principle 4 (2 files)
        revenue
    S6  Two files, same facts printed        4.5  normalise, do not ask
        differently                                (2 files)
    S7  Dec page DECLINING property          4.1 Step 1 / 4.12
    S8  Application + loss run with claims   4.6  client answer conflicts with
                                                   source (2 files)

Other design rules (inherited from make_v1_c3_test_pdfs.py, all proven)
-----------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave
  (the 2026-08-22 fixture-defect lesson).
* Dates computed from TODAY so no scenario drifts into an expired-term or
  renewal path it was not designed to exercise.
* Every scenario prints a GL class code WITH a location column, because the
  extraction contract for `gl_class_codes_by_location` is
  ``[{"location": string, "codes": [string]}]`` - without it the fact comes back
  empty and Exposure Consistency deducts 20 for a pure fixture artefact, which
  then buries whatever the scenario was actually testing (the C3 lesson).
* Driver "date hired" is a full MM/DD/YYYY date. The first version printed a
  bare year, and the live run came back with "3 rows need attention - Date hired
  must be MM/DD/YYYY" on every driver.
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
    "test_data_c4",
)

TODAY = datetime.now()


def _future(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


EFF = _future(30)
EXP = (TODAY + timedelta(days=30 + 365)).strftime("%m/%d/%Y")


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
    return y - 0.06 * inch


def _applicant(c, y, name, addr, city_state_zip, *, fein="84-2210987",
               entity="Limited Liability Company", contact="Dana Whitfield",
               phone="303-555-0148", email="dana@example.com"):
    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "City / State / ZIP", city_state_zip)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Legal Entity Type", entity)
    y = _row(c, y, "Contact Name", contact)
    y = _row(c, y, "Contact Phone", phone)
    y = _row(c, y, "Contact Email", email)
    return y


def _producer(c, y, agency="Whitfield Risk Partners"):
    y = _head(c, y, "PRODUCER")
    y = _row(c, y, "Agency Name", agency)
    y = _row(c, y, "Agency Phone", "303-555-0100")
    return y


def _operations(c, y, desc, revenue, employees, years, payroll=None):
    y = _head(c, y, "BUSINESS OPERATIONS")
    y = _row(c, y, "Description of Operations", desc)
    y = _row(c, y, "Annual Gross Sales", revenue)
    y = _row(c, y, "Number of Employees", employees)
    y = _row(c, y, "Years in Business", years)
    if payroll:
        y = _row(c, y, "Annual Payroll", payroll)
    return y


def _gl_class(c, y, code, desc, basis, exposure, location="Location 1"):
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    return _table(
        c, y,
        ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
        [[location, f"{code} - {desc}", basis, exposure]],
        [1.0, 2.5, 4.9, 6.2],
    )


def _lines(c, y, rows):
    """The coverage-line schedule. This is what makes a line APPLICABLE, so it
    is stated in every scenario even when the line's own values are omitted."""
    y = _head(c, y, "SCHEDULE OF COVERAGES")
    return _table(c, y, ["COVERAGE LINE", "STATUS", "ANNUAL PREMIUM"], rows,
                  [1.0, 3.9, 5.6])


# ── Scenarios ───────────────────────────────────────────────────────────────

def s1(path):
    """4.3 / 4.4 headline split. GL + Property applied for.

    STATE : applicant, producer, operations, revenue, employees, years, payroll,
            GL class code with location, coverage lines (GL + Property granted).
    OMIT  : every GL limit, GL deductible, property deductibles, valuation
            method, coinsurance, business income, period of restoration
            (all -> Agency), AND every property characteristic - construction,
            year built, roof year, sprinkler, fire protection, building value,
            BPP value (all -> Client). Both categories must surface as
            QUESTIONS so the live run can show the split on one screen.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability and Commercial Property - values to be confirmed")
    y = _producer(c, y)
    y = _applicant(c, y, "Ridgeline Cabinetry LLC", "4820 Marshall Street",
                   "Wheat Ridge, CO 80033")
    y = _operations(c, y, "Custom cabinet fabrication and installation",
                    "$3,150,000", "28", "12", payroll="$1,240,000")
    y = _gl_class(c, y, "91340", "Carpentry - interior", "Payroll", "$1,240,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"],
                      ["Commercial Property", "Applied for", "TBD"]])
    c.showPage()

    y = _page(c, "PROPERTY SCHEDULE", "Location 1 of 1")
    y = _head(c, y, "PROPERTY - LOCATION 1")
    y = _row(c, y, "Location Address", "4820 Marshall Street, Wheat Ridge, CO 80033")
    y = _row(c, y, "Occupancy", "Cabinet shop and warehouse")
    y = _para(c, y, "Building characteristics and coverage terms are to be")
    y = _para(c, y, "confirmed before binding. No values are stated in this")
    y = _para(c, y, "application.")
    c.showPage()
    c.save()


def s2(path):
    """4.10 workers comp routing.

    STATE : applicant, operations, employees, payroll, payroll by STATE (a 4.3
            client fact), subcontractor percentage, GL class code, WC applied for.
    OMIT  : X-Mod, X-Mod effective date, payroll period, owner/officer election,
            WC class codes, SIC, NAICS. All seven must surface as questions.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "WORKERS COMPENSATION APPLICATION",
              "Rating information to be supplied by the agency")
    y = _producer(c, y, "Front Range Benefits Group")
    y = _applicant(c, y, "Baseline Mechanical Services LLC", "1170 Quail Court",
                   "Lakewood, CO 80215", fein="86-1120044",
                   contact="Marcus Ibarra", phone="303-555-0177",
                   email="marcus@example.com")
    y = _operations(c, y, "Commercial HVAC installation and service",
                    "$4,600,000", "41", "9", payroll="$2,180,000")
    y = _head(c, y, "EMPLOYEES AND PAYROLL BY STATE")
    y = _table(
        c, y,
        ["STATE", "JOB DUTIES", "EMPLOYEES", "ANNUAL PAYROLL"],
        [["CO", "Heating and air conditioning field technicians", "31", "$1,610,000"],
         ["CO", "Clerical office employees", "10", "$570,000"]],
        [1.0, 1.8, 4.9, 6.1],
    )
    y = _head(c, y, "SUBCONTRACTOR EXPOSURE")
    y = _row(c, y, "Percentage of Work Subcontracted", "18%")
    y = _row(c, y, "Annual Subcontract Cost", "$412,000")
    y = _gl_class(c, y, "91746", "Heating and air conditioning", "Payroll",
                  "$2,180,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"],
                      ["Workers Compensation", "Applied for", "TBD"]])
    y = _para(c, y, "Rating factors and classification are to be assigned by the")
    y = _para(c, y, "agency prior to submission.")
    c.showPage()
    c.save()


def s3(path):
    """4.9 commercial auto routing.

    STATE : vehicle schedule (year/make/model/VIN/garaging/use/radius) and
            driver schedule with FULL MM/DD/YYYY hire dates - these are the 4.3
            client facts and must stay in the Client bucket as tables.
    OMIT  : covered-auto symbols, auto liability limit, comprehensive and
            collision deductibles, physical damage valuation. All five must
            surface as questions and land in Agency.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL AUTO APPLICATION",
              "Coverage structure to be completed by the agency")
    y = _producer(c, y, "Cimarron Commercial Insurance")
    y = _applicant(c, y, "Pathway Courier Group LLC", "2255 Havana Street",
                   "Aurora, CO 80010", fein="87-3390121",
                   contact="Renee Alvarado", phone="720-555-0132",
                   email="renee@example.com")
    y = _operations(c, y, "Regional medical courier and same-day delivery",
                    "$2,240,000", "22", "7", payroll="$980,000")
    y = _head(c, y, "SCHEDULE OF VEHICLES")
    y = _table(
        c, y,
        ["#", "YEAR", "MAKE / MODEL", "VIN", "GARAGING CITY", "USE", "RADIUS"],
        [["1", "2021", "Ford Transit 250", "1FTBR1C89MKA21774", "Aurora CO",
          "Delivery", "150 miles"],
         ["2", "2022", "Ram ProMaster 1500", "3C6LRVBG4NE118206", "Aurora CO",
          "Delivery", "150 miles"],
         ["3", "2020", "Chevrolet Express", "1GCWGAFP2L1201338", "Denver CO",
          "Service", "50 miles"]],
        [1.0, 1.35, 1.95, 3.55, 5.15, 6.25, 6.95],
    )
    y = _head(c, y, "SCHEDULE OF DRIVERS")
    y = _table(
        c, y,
        ["DRIVER NAME", "DATE OF BIRTH", "LICENSE NUMBER", "STATE", "DATE HIRED"],
        [["Alvarado, Renee", "04/11/1985", "CO-9920114", "CO", "03/04/2019"],
         ["Nkemelu, Daniel", "09/02/1991", "CO-8811340", "CO", "06/17/2021"],
         ["Ostrowski, Petra", "12/19/1988", "CO-7740228", "CO", "01/09/2022"]],
        [1.0, 2.7, 4.0, 5.6, 6.3],
    )
    y = _gl_class(c, y, "98305", "Courier or messenger service", "Payroll",
                  "$980,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"],
                      ["Business Auto", "Applied for", "TBD"]])
    y = _para(c, y, "Covered auto designations and physical damage terms are to")
    y = _para(c, y, "be set by the agency.")
    c.showPage()
    c.save()


def s4(path):
    """4.11 umbrella - everything structural is the producer's.

    STATE : applicant, operations, GL class code, umbrella APPLIED FOR, the
            underlying lines by NAME only.
    OMIT  : umbrella limit, self-insured retention, attachment point,
            follow-form status, every underlying LIMIT, and X-Mod (which the
            live run surfaced through the narrative key).
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL UMBRELLA APPLICATION",
              "Structure and limits to be determined by the agency")
    y = _producer(c, y, "Summit Excess Brokerage")
    y = _applicant(c, y, "Cascade Site Services LLC", "780 Iron Horse Drive",
                   "Longmont, CO 80501", fein="88-4410233",
                   contact="Tobias Vance", phone="303-555-0190",
                   email="tobias@example.com")
    y = _operations(c, y, "Commercial site preparation and excavation",
                    "$7,900,000", "54", "16", payroll="$3,410,000")
    y = _head(c, y, "UNDERLYING COVERAGE IN FORCE")
    y = _table(
        c, y,
        ["COVERAGE", "CARRIER", "STATUS"],
        [["General Liability", "Mountain States Mutual", "In force"],
         ["Business Auto", "Mountain States Mutual", "In force"],
         ["Employers Liability", "Pinnacle Comp", "In force"]],
        [1.0, 2.9, 5.3],
    )
    y = _gl_class(c, y, "94569", "Excavation - grading of land", "Payroll",
                  "$3,410,000")
    y = _lines(c, y, [["Commercial General Liability", "In force", "TBD"],
                      ["Umbrella / Excess Liability", "Applied for", "TBD"],
                      ["Workers Compensation", "In force", "TBD"]])
    # Deliberately vague. The first wording named the very terms this scenario
    # omits, and the self-check below rejected the file - which is the check
    # doing its job on its own author.
    y = _para(c, y, "Excess terms are to be determined by the agency prior to")
    y = _para(c, y, "marketing.")
    c.showPage()
    c.save()


def s5a(path):
    """4.1 Step 5 file A - revenue $2,400,000.

    BOTH S5 files are now applications. The first version made S5B a "Financial
    Summary", which the classifier typed as Financial Statements / Needs review;
    the live run showed it may never have merged, so the conflict the scenario
    exists to create was never created.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", "Original submission")
    y = _producer(c, y, "Bluestem Insurance Advisors")
    y = _applicant(c, y, "Harborlight Catering LLC", "915 Tejon Street",
                   "Denver, CO 80204", fein="83-5510188",
                   contact="Iris Fontaine", phone="720-555-0166",
                   email="iris@example.com")
    y = _operations(c, y, "Off-premises corporate catering and event services",
                    "$2,400,000", "34", "8", payroll="$1,050,000")
    y = _gl_class(c, y, "16941", "Caterers", "Gross Sales", "$2,400,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"]])
    c.showPage()
    c.save()


def s5b(path):
    """4.1 Step 5 file B - the SAME company, revenue $3,850,000.

    One material disagreement and nothing else. Same document TYPE as S5A so
    both classify as applications and both merge.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Revised submission - supersedes prior")
    y = _producer(c, y, "Bluestem Insurance Advisors")
    y = _applicant(c, y, "Harborlight Catering LLC", "915 Tejon Street",
                   "Denver, CO 80204", fein="83-5510188",
                   contact="Iris Fontaine", phone="720-555-0166",
                   email="iris@example.com")
    y = _operations(c, y, "Off-premises corporate catering and event services",
                    "$3,850,000", "34", "8", payroll="$1,050,000")
    y = _gl_class(c, y, "16941", "Caterers", "Gross Sales", "$3,850,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"]])
    c.showPage()
    c.save()


def s6a(path):
    """4.5 file A - the canonical printing of every normalisable field."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", "Agency copy")
    y = _producer(c, y, "Keystone Underwriting Services")
    y = _applicant(c, y, "Trailmark Outfitters LLC", "1450 E 9 Mile St",
                   "Denver, CO 80202", fein="82-4470155",
                   entity="LLC", contact="Sydney Marchetti",
                   phone="303-555-0121", email="sydney@example.com")
    y = _operations(c, y, "Retail sale of outdoor recreation equipment",
                    "$1,900,000", "17", "6", payroll="$720,000")
    y = _gl_class(c, y, "18435", "Sporting goods stores", "Gross Sales",
                  "$1,900,000")
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Policy Number", "CGL-7781-4402-26")
    y = _lines(c, y, [["Commercial General Liability", "In force", "TBD"]])
    c.showPage()
    c.save()


def s6b(path):
    """4.5 file B - THE SAME FACTS, every one printed differently.

    Street suffix spelled out, ZIP+4, L.L.C., the coverage named in full, and
    the policy number spaced. Not one value here materially differs from S6A;
    if Primble asks a human about any of them, 4.5 has failed.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE", "Carrier-issued copy")
    y = _head(c, y, "CERTIFICATE HOLDER / NAMED INSURED")
    y = _row(c, y, "Named Insured", "Trailmark Outfitters L.L.C.")
    y = _row(c, y, "Mailing Address", "1450 East 9 Mile Street")
    y = _row(c, y, "City / State / ZIP", "Denver, Colorado 80202-1417")
    y = _row(c, y, "Legal Entity Type", "Limited Liability Company")
    y = _head(c, y, "COVERAGES")
    y = _row(c, y, "Coverage Line", "Commercial General Liability")
    y = _row(c, y, "Policy Number", "CGL 7781 4402 26")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    c.showPage()
    c.save()


def s7(path):
    """4.1 Step 1 / 4.12 - property is DECLINED, so property must not be asked.

    OMIT : construction type, year built, roof year, sprinkler, fire protection
           and building value - their absence is the whole test, and it is
           verified at the bottom of this file.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "POLICY DECLARATIONS", "General Liability only")
    y = _producer(c, y, "Arrowpoint Insurance Group")
    y = _applicant(c, y, "Vantage Consulting Partners LLC", "600 Grant Street",
                   "Denver, CO 80203", fein="81-3320177",
                   contact="Priya Raghunathan", phone="303-555-0155",
                   email="priya@example.com")
    y = _operations(c, y, "Management consulting services, office based",
                    "$1,350,000", "11", "5", payroll="$820,000")
    y = _lines(c, y, [["Commercial General Liability", "Included", "$8,940"],
                      ["Commercial Property", "NO COVERAGE", "$0"],
                      ["Business Auto", "NO COVERAGE", "$0"],
                      ["Workers Compensation", "NO COVERAGE", "$0"]])
    y = _gl_class(c, y, "41677", "Consultants - management", "Gross Sales",
                  "$1,350,000")
    y = _para(c, y, "This policy provides General Liability coverage only.")
    y = _para(c, y, "No property, automobile or workers compensation coverage is")
    y = _para(c, y, "afforded under this policy.")
    c.showPage()
    c.save()


def s8a(path):
    """4.6 file A - the application. Says nothing about losses.

    Paired with S8B (a loss run listing two real claims) so the documents
    establish that claims EXIST. The client is then asked the no-known-losses
    attestation and answers "no losses", which materially contradicts the
    source. Expected: retained, marked conflicting, routed to the producer,
    never silently overwritten.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", "General Liability")
    y = _producer(c, y, "Ironbridge Insurance Group")
    y = _applicant(c, y, "Northgate Fabrication LLC", "3300 Brighton Boulevard",
                   "Denver, CO 80216", fein="85-6610299",
                   contact="Leon Kowalczyk", phone="303-555-0138",
                   email="leon@example.com")
    y = _operations(c, y, "Structural steel fabrication and finishing",
                    "$5,700,000", "46", "14", payroll="$2,640,000")
    y = _gl_class(c, y, "91560", "Metal working - structural", "Payroll",
                  "$2,640,000")
    y = _lines(c, y, [["Commercial General Liability", "Applied for", "TBD"]])
    c.showPage()
    c.save()


def s8b(path):
    """4.6 file B - a loss run listing TWO paid claims.

    This is the source of truth the client's answer will contradict.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              "Northgate Fabrication LLC - five year history")
    y = _row(c, y, "Named Insured", "Northgate Fabrication LLC")
    y = _row(c, y, "Carrier", "Cornerstone Indemnity")
    y = _row(c, y, "Valuation Date", _future(-14))
    y = _head(c, y, "CLAIM DETAIL")
    y = _table(
        c, y,
        ["DATE OF LOSS", "LINE", "DESCRIPTION", "PAID", "RESERVED", "STATUS"],
        [[_future(-820), "General Liability",
          "Struck-by injury, subcontractor", "$41,500", "$0", "Closed"],
         [_future(-410), "General Liability",
          "Property damage, dropped beam", "$18,200", "$6,000", "Open"]],
        [1.0, 2.0, 3.4, 5.5, 6.2, 6.95],
    )
    y = _para(c, y, "Total incurred for the period: $65,700 across 2 claims.")
    c.showPage()
    c.save()


# ── Self-verification - a fixture that lies is worse than one that fails ────

def _text_of(path) -> str:
    try:
        import pdfplumber
    except ImportError:                                       # pragma: no cover
        return ""
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


# The OMIT contract, executable. Every term here must be ABSENT from the named
# file, because the scenario tests where its QUESTION routes - and a value the
# document states is suppressed as already-provided and never asked.
_FORBIDDEN = {
    "S1_gl_property_terms_omitted.pdf": [
        "each occurrence", "aggregate limit", "deductible", "valuation",
        "coinsurance", "business income", "period of restoration",
        "construction", "year built", "roof", "sprinkler", "fire protection",
        "building value", "personal property",
    ],
    "S2_workers_comp_rating_omitted.pdf": [
        "x-mod", "xmod", "experience modification", "payroll period",
        "officer", "sic", "naics",
    ],
    "S3_commercial_auto_structure_omitted.pdf": [
        "symbol", "combined single limit", "deductible",
        "actual cash value", "replacement cost",
    ],
    "S4_umbrella_structure_omitted.pdf": [
        "self-insured retention", "attachment point", "follow form",
        "x-mod", "xmod", "$1,000,000", "$5,000,000",
    ],
    "S7_gl_only_property_declined.pdf": [
        "construction", "year built", "roof", "sprinkler", "fire protection",
        "building value",
    ],
}


def _verify(paths):
    problems = []
    by_name = {os.path.basename(p): p for p in paths}

    for name, banned in _FORBIDDEN.items():
        p = by_name.get(name)
        if not p:
            problems.append(f"{name}: not generated")
            continue
        text = _text_of(p).lower()
        if not text:
            problems.append(f"{name}: could not read text back (pdfplumber missing?)")
            continue
        for word in banned:
            if word in text:
                problems.append(
                    f"{name}: states '{word}', so its question will be suppressed "
                    f"as already-provided and the scenario cannot test its routing")

    # S6 is only a normalisation test if the two files genuinely agree.
    a = _text_of(by_name["S6A_application_canonical_printing.pdf"])
    b = _text_of(by_name["S6B_certificate_variant_printing.pdf"])
    if "Trailmark Outfitters" not in a or "Trailmark Outfitters" not in b:
        problems.append("S6: both files must name the same insured")
    if "80202" not in a or "80202" not in b:
        problems.append("S6: both files must carry the same ZIP")

    # S5 only creates a conflict if the two revenue figures differ.
    a5 = _text_of(by_name["S5A_application_revenue_2_4M.pdf"])
    b5 = _text_of(by_name["S5B_application_revenue_3_85M.pdf"])
    if "$2,400,000" not in a5 or "$3,850,000" not in b5:
        problems.append("S5: the two revenue figures must differ")
    if "Harborlight Catering" not in a5 or "Harborlight Catering" not in b5:
        problems.append("S5: both files must name the same insured")

    # S8 only tests 4.6 if the loss run actually reports claims.
    s8 = _text_of(by_name["S8B_loss_run_two_claims.pdf"])
    if "2 claims" not in s8.lower():
        problems.append("S8B: must report claims for the client answer to contradict")
    return problems


SCENARIOS = [
    ("S1_gl_property_terms_omitted.pdf", s1),
    ("S2_workers_comp_rating_omitted.pdf", s2),
    ("S3_commercial_auto_structure_omitted.pdf", s3),
    ("S4_umbrella_structure_omitted.pdf", s4),
    ("S5A_application_revenue_2_4M.pdf", s5a),
    ("S5B_application_revenue_3_85M.pdf", s5b),
    ("S6A_application_canonical_printing.pdf", s6a),
    ("S6B_certificate_variant_printing.pdf", s6b),
    ("S7_gl_only_property_declined.pdf", s7),
    ("S8A_application_no_loss_mention.pdf", s8a),
    ("S8B_loss_run_two_claims.pdf", s8b),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # Remove the previous generation's files so a renamed scenario cannot leave
    # a stale PDF behind for someone to upload by mistake.
    for old in os.listdir(OUT_DIR):
        if old.lower().endswith(".pdf"):
            os.remove(os.path.join(OUT_DIR, old))

    written = []
    for name, fn in SCENARIOS:
        path = os.path.join(OUT_DIR, name)
        fn(path)
        written.append(path)
        print(f"  wrote {name}")

    problems = _verify(written)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)
    print("  wrote README-HOW-TO-TEST.md")

    if problems:
        print("\n  FIXTURE SELF-CHECK FAILED:")
        for p in problems:
            print(f"    - {p}")
        raise SystemExit(1)
    print(f"\n  {len(written)} files + README in {OUT_DIR}")
    print("  fixture self-check: PASS")


README = """# C4 Contextual Questionnaire Logic - how to test live

Generated by `backend/scripts/make_c4_test_pdfs.py`. Re-run that script any time;
it deletes and rewrites every PDF in this folder.

**Why these files look sparse.** A value stated in a document is extracted and
the question is correctly suppressed as already-provided. So a scenario can only
test WHERE A QUESTION ROUTES for a value it does NOT state. Each scenario states
just enough to make the coverage applicable, and omits exactly the values whose
routing it is testing. The generator FAILS if an omitted term reappears.

---

## Every session follows the same four steps

1. Upload the file(s). Wait for extraction.
2. **Pre-form screen** - note the Submission Readiness %, the Data Consistency
   panel, and the package score.
3. Generate the forms listed for that scenario.
4. **Send to Client** -> **expand the Agency bucket** (collapsed by default).

> The **Underwriting / Internal Review** bucket is still hidden by design.
> Nothing in these tests should need it.

---

## S1 - GL + Property  (`S1_gl_property_terms_omitted.pdf`)
**Generate: ACORD 125, 126, 140**

The headline test. Both categories are omitted from the document, so both must
appear as questions and split across the two buckets.

| Must be in CLIENT | Must be in AGENCY |
|---|---|
| construction type, occupancy | every GL limit, GL deductible |
| year built, roof year | property deductibles (AOP, wind) |
| sprinkler, fire protection class | valuation method, coinsurance |
| building value, BPP value | business income limit, period of restoration |
| location list, revenue, employees | GL class code, NAICS, SIC, effective date |

**Send:** pre-form Submission Readiness %, package score, Client count, Agency
count, and a screenshot of both buckets expanded.

---

## S2 - Workers comp  (`S2_workers_comp_rating_omitted.pdf`)
**Generate: ACORD 125, 130**

**Must be in AGENCY:** X-Mod / experience modifier, X-Mod effective date,
payroll period, owner/officer exclusions, WC class codes, **SIC**, NAICS.

**Must be in CLIENT:** employees, job duties, payroll, payroll by state,
subcontractor percentage.

**Send:** package score, both counts, and specifically confirm **SIC is in
Agency** - it was in the Client bucket on the previous run.

---

## S3 - Commercial auto  (`S3_commercial_auto_structure_omitted.pdf`)
**Generate: ACORD 125, 127**

**Must be in CLIENT:** the vehicle table, the driver table, garaging, radius.
The driver table must show **no red "Date hired" errors** this time.

**Must be in AGENCY:** covered-auto symbols, auto liability limit,
comprehensive and collision deductibles, physical damage valuation.

**Send:** package score, both counts, and confirm the driver rows are clean.

---

## S4 - Umbrella  (`S4_umbrella_structure_omitted.pdf`)
**Generate: ACORD 125, 131**

**Must be in AGENCY:** umbrella limit, self-insured retention, attachment point,
follow-form status, **and the EMOD question** (it was in Client last run).

**Must NOT appear at all:** "Please list the vehicles to be insured". ACORD 131
has no vehicle schedule; that question was a phantom and is now suppressed.

**Send:** package score, both counts, and confirm those two fixes.

---

## S5 - Conflicting revenue  (`S5A` + `S5B`, upload BOTH together)
**Generate: ACORD 125, 126**

Both are applications this time, so both should merge. They disagree:
$2,400,000 against $3,850,000.

**Check the pre-form screen FIRST** - open the **Data Consistency** panel and say
whether the revenue conflict is listed there.

**Expect:** the conflict reaches the **producer**, tagged **"Conflict - resolve"**.
The client must NOT be asked to choose between the two figures.

**Send:** a screenshot of the Data Consistency panel, where the revenue item
appears (Client / Agency / nowhere), the package score, and both counts.
**If a revenue question appears in the Client bucket, report that first.**

---

## S6 - Same facts, different printing  (`S6A` + `S6B`, upload BOTH together)
**Generate: ACORD 125, 25**

| S6A | S6B |
|---|---|
| `1450 E 9 Mile St` | `1450 East 9 Mile Street` |
| `Denver, CO 80202` | `Denver, Colorado 80202-1417` |
| `Trailmark Outfitters LLC` | `Trailmark Outfitters L.L.C.` |
| `CGL-7781-4402-26` | `CGL 7781 4402 26` |

**Expect:** no conflict and no question about any of them. Also confirm
**"Please list the vehicles to be insured" is gone** - ACORD 25 is a
certificate and has no vehicle schedule.

**Send:** the Data Consistency panel screenshot, package score, both counts.

---

## S7 - Property declined  (`S7_gl_only_property_declined.pdf`)
**Run this TWICE, as two separate sessions.**

**Run 1 - generate ACORD 125 and 126 ONLY.**
Expect: no property questions at all.

**Run 2 - generate ACORD 125, 126 AND 140.**
Expect: the property questions **come back**. Selecting the form is the
producer's own statement that they are applying for that coverage, and it
overrides what the expiring dec page says.

**Send:** both runs, with counts. Run 2 matters as much as run 1 - if property
questions stay hidden when 140 is selected, the form ships blank and unaskable.

---

## S8 - Client answer contradicts the documents  (`S8A` + `S8B`, upload BOTH)
**Generate: ACORD 125, 126.** This one needs a full round trip.

The loss run lists **2 claims totalling $65,700**. The application says nothing
about losses.

1. Send the questionnaire to an email address you control. Make sure the
   **"No known losses attestation"** question is ticked.
2. Open the client link and answer it **"No, we have had no claims or losses."**
   That directly contradicts the loss run.
3. Submit, then return to the producer view.

**Expect:** the answer is retained but NOT applied. The fact is marked
conflicting and a producer review item appears offering **"Use the client's
value"** or **"Keep the source"**. The loss history must not silently flip to
"no losses".

**Send:** a screenshot of whatever the producer sees after submission, and say
plainly whether the client's answer overwrote the loss history or was held.
**If it silently overwrote, that is a clause 4.6 failure - report it first.**

---

## What to send back overall

For every session: **Submission Readiness %, package score, Client count,
Agency count, and a screenshot with the Agency bucket expanded.**

Send any failing scenario first.

**The package score is not optional this time.** Routing changes who is asked,
never a number. If a score moves, that IS a bug.

### Still not testable by clicking

Clause 4.1 Step 2 vs Step 3 (Source Verified vs merely Suggested). Nearly every
extracted fact is labelled "suggested" because nothing verifies values against
the document text yet. Logged as v1-20AUG.md C4-B; it needs Brent's decision,
not a fixture.
"""


if __name__ == "__main__":
    main()
