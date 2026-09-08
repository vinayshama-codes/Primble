"""make_bug07_test_pdfs.py - live test data for BUG-07
("hundreds of indexed ghost vehicle questions in the client questionnaire").

    py backend/scripts/make_bug07_test_pdfs.py           # 2 files - the fix loop
    py backend/scripts/make_bug07_test_pdfs.py --full    # + 2 extras, one-off sweep

Writes to bug07_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

TWO FILES, ONE FORM SELECTION, RE-RUNNABLE IN MINUTES
-----------------------------------------------------
A and B are the SAME submission with ONE difference: B lists 18 vehicles and 16
drivers, A lists none. Same coverages, same limits, same covered-auto symbol
sentence, same form selection (ACORD 125 + 127 + 137_CO + 25).

That single difference is the entire diagnosis. If the ghost count were driven
by the data, B would be far higher than A. It is not, so they come out nearly
identical - and the "(308th vehicle)" card appears on a document that names no
vehicle at all.

Proven offline before this fixture was written: ACORD 137_CO on its own emits
365 vehicle-labelled questions with `facts["auto_vin_schedule"]` holding ZERO
rows, and 365 with it holding 143 rows. Byte-identical, because the question
generator never reads the fleet.

WHAT THE BUG ACTUALLY IS
------------------------
Nothing invents vehicle records. `arq_service._resolve_question` matches the
curated snake_case vocabulary `_FIELD_PREFIX_MAP` against field names with a
bare, case-insensitive `startswith`. ACORD names its whole Commercial Auto
section `Vehicle_*`, so `Vehicle_BusinessAutoSymbol_TwoIndicator_G` (a
covered-auto symbol checkbox) lowercases into `vehicle_...` and is handed the
one-vehicle question text, the "vehicle" group label and, via
`_is_curated_client_field`, a CLIENT audience. `group_counts` then numbers it
by FIELD, not by record, from one counter shared across every selected form.

Ghost potential of the chosen selection (fields that hit the prefix map but
bind no schedule column - 0 of them are schedule-backed):

    ACORD_137_CO  378      ACORD_127  390      ACORD_25   28      ACORD_125   8
    selection total 779   =   605 vehicle  +  156 driver  +  18 insurer

WHAT EACH FILE COVERS
---------------------
  A  no fleet stated   the reported bug at full size; the real "list the
                       vehicles" table raised with 0 rows; ghost driver and
                       insurance-company cards; ACORD 25 present so the
                       2026-08-26 C4 fix (no fleet table on a form with no
                       fleet) is guarded on every run
  B  18 veh / 16 drv   THE CONTROL - same forms, same symbols, a real fleet.
                       Also covers over-capacity: the ACORD form prints 14
                       rows, so 18 vehicles must retain all 18 in facts and
                       show an overflow notice

  --full adds:
  C  no auto at all    a bakery that disclaims owned, hired and non-owned
                       autos three times, and still gets "(Nth vehicle)" cards
  D  umbrella only     ACORD 131 + 25 with no auto section at all - the
                       narrowest C4 regression guard

Design rules (inherited from make_c6_test_pdfs.py, all proven)
--------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave. A
  17-character VIN at 8pt needs 1.4in of clearance; the first draft used 0.70in
  and pdfplumber interleaved VIN with GVW. The self-check below caught it.
* Dates computed from TODAY, so nothing drifts into an expired-term or renewal
  path (an expired term caps the score at 60 and would muddy the capture).
* ABSENCES are asserted with WORD BOUNDARIES, not substrings - the first draft
  failed because the surname "Trevino" contains "vin".
* Distinct company per file, so extraction caches and identity matching never
  bleed between sessions.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bug07_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Cornerstone Commercial Insurance Services LLC"
CARRIER = "Granite Ridge Mutual Insurance Company"

# A and B MUST state the identical symbol line. The 137 symbol grid produces the
# bulk of the ghosts, and `pdf_service._derive_symbol_indicator` pre-fills some
# of those boxes from this sentence - so if the two files stated different
# symbols they would pre-fill different numbers of boxes and the controlled
# comparison would be worthless.
SYMBOLS = ("Covered Autos: Symbol 7 (specifically described autos) applies to "
           "Liability, Comprehensive and Collision.")


# --- Layout helpers ---------------------------------------------------------

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


def _applicant(c, y, name, addr, fein, contact, phone, email, ops, sales, emp,
               yib, naics, entity="Limited Liability Company"):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "Physical Address", addr)
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


def _gl(c, y, policy, occ="$1,000,000", agg="$2,000,000"):
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "NAIC Number", "24198")
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Coverage Form", "Occurrence")
    y = _row(c, y, "Each Occurrence Limit", occ)
    y = _row(c, y, "General Aggregate Limit", agg)
    y = _row(c, y, "Products/Completed Operations Aggregate", agg)
    y = _row(c, y, "Annual Premium", "$11,420")
    return y


def _auto_head(c, y, policy):
    y = _head(c, y, "COVERAGE - BUSINESS AUTO")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Liability Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Comprehensive Deductible", "$1,000")
    y = _row(c, y, "Collision Deductible", "$1,000")
    y = _row(c, y, "Annual Premium", "$6,880")
    y = _para(c, y, SYMBOLS)
    return y


def _certificate(c, y, lines="the general liability and business auto policies"):
    # `lines` is a parameter because file D carries NO auto section - naming the
    # auto policy there would contradict the document and trip its own absence
    # check, which is exactly what the self-check caught on the first run.
    y = _head(c, y, "CERTIFICATE HOLDER")
    y = _para(c, y, "Meridian Bay Development Partners LP, 800 Harborview "
                    "Tower, Suite 1500, Houston, TX 77002.")
    y = _para(c, y, f"Certificate holder is named as additional insured on "
                    f"{lines}.")
    return y


# Column x-positions in inches. A 17-character VIN at 8pt Helvetica is ~0.95in
# wide, so the VIN column needs a full 1.4in of clearance before GVW. Never
# narrow these without re-running the self-check.
_VEH_COLS = [1.0, 1.30, 1.85, 2.75, 3.90, 5.30, 6.00]
_VEH_HEAD = ["#", "YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"]

# VINs are structurally valid (17 chars, no I/O/Q) so the questionnaire's VIN
# validator and the vPIC decode button behave as they would in production.
_FLEET = [
    ("2021", "Ford", "F-250", "1FT7W2BT5MED12345", "10,000", "Service"),
    ("2019", "Isuzu", "NPR", "JALC4W163K7001234", "14,500", "Delivery"),
    ("2022", "Chevrolet", "Silverado", "1GCUYDED5NZ123456", "7,100", "Service"),
    ("2020", "RAM", "ProMaster", "3C6TRVAG5LE123457", "9,350", "Delivery"),
    ("2018", "Freightliner", "M2 106", "1FVACWDT8JHJZ1234", "26,000", "Commercial"),
    ("2023", "Ford", "Transit", "1FTBW3XG8PKA12345", "9,500", "Service"),
    ("2017", "Hino", "268", "5PVNJ8JV1H4S51234", "25,950", "Commercial"),
    ("2021", "GMC", "Sierra 2500", "1GT49PEY5MF123458", "10,650", "Service"),
    ("2019", "Ford", "F-550", "1FDUF5HT6KEC12345", "19,500", "Commercial"),
    ("2022", "Isuzu", "NRR", "JALE5W169N7900123", "19,500", "Delivery"),
    ("2016", "Chevrolet", "Express", "1GCWGAFF8G1234567", "9,600", "Service"),
    ("2023", "RAM", "2500", "3C6UR5DL8PG123456", "10,000", "Service"),
    ("2020", "Ford", "F-150", "1FTEW1E45LFA12345", "7,050", "Service"),
    ("2018", "Kenworth", "T370", "2NKHHM7X5JM123456", "33,000", "Commercial"),
    ("2021", "Mercedes", "Sprinter", "W1Y4EBHY5MT123456", "9,050", "Delivery"),
    ("2019", "Nissan", "NV2500", "1N6BF0KY5KN812345", "8,550", "Delivery"),
    ("2022", "Ford", "F-350", "1FT8W3BT5NEC12345", "14,000", "Commercial"),
    ("2017", "Isuzu", "NQR", "JALE5W16XH7900124", "17,950", "Delivery"),
]

_DRIVERS = [
    ("Marcus T Whitfield", "TX", "D4471982", "03/14/1985", "12"),
    ("Elena R Vasquez", "TX", "D5528193", "07/02/1990", "8"),
    ("Aaron J Beckett", "TX", "D6119274", "11/23/1978", "19"),
    ("Priya N Raghavan", "TX", "D7302845", "01/09/1993", "6"),
    ("Desmond L Carver", "TX", "D8214736", "05/30/1982", "15"),
    ("Hannah M Okonjo", "TX", "D9336127", "09/17/1988", "10"),
    ("Victor A Salinas", "TX", "D1047285", "02/26/1975", "22"),
    ("Grace E Lindqvist", "TX", "D2158396", "12/05/1991", "7"),
    ("Terrence B Nakamura", "TX", "D3269407", "06/11/1986", "13"),
    ("Simone D Ferreira", "TX", "D4370518", "08/28/1994", "5"),
    ("Owen K Brannigan", "TX", "D5481629", "04/03/1980", "17"),
    ("Rosalind P Achebe", "TX", "D6592730", "10/19/1989", "9"),
    ("Julian F Moreau", "TX", "D7603841", "03/07/1996", "4"),
    ("Naomi S Delacroix", "TX", "D8714952", "07/25/1983", "14"),
    ("Caleb R Yamamoto", "TX", "D9825063", "11/12/1992", "6"),
    ("Imani T Fitzgerald", "TX", "D1936174", "05/08/1987", "11"),
]


def _vehicles(c, y, n):
    y = _head(c, y, f"SCHEDULE OF VEHICLES - {n} UNITS")
    rows = [[str(i + 1)] + list(v) for i, v in enumerate(_FLEET[:n])]
    return _table(c, y, _VEH_HEAD, rows, _VEH_COLS)


def _drivers(c, y, n):
    y = _head(c, y, f"SCHEDULE OF DRIVERS - {n} DRIVERS")
    rows = [[str(i + 1)] + list(d) for i, d in enumerate(_DRIVERS[:n])]
    return _table(c, y,
                  ["#", "NAME", "STATE", "LICENSE NUMBER", "DATE OF BIRTH", "YRS EXP"],
                  rows, [1.0, 1.4, 3.1, 3.6, 5.0, 6.4])


def _save(name, draw):
    path = os.path.join(OUT_DIR, name)
    c = canvas.Canvas(path, pagesize=LETTER)
    draw(c)
    c.save()
    print(f"  wrote {name}")
    return path


# --- A and B: identical submission, one differing section -------------------

def _shared_body(c, company, addr, fein, contact, phone, email, ops, sales,
                 emp, yib, naics, gl_pol, ba_pol):
    """Everything A and B have in common. The ONLY difference between the two
    files is whether `_vehicles` / `_drivers` are called after this."""
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION", f"{company} - renewal submission")
    y = _applicant(c, y, company, addr, fein, contact, phone, email,
                   ops, sales, emp, yib, naics)
    y = _gl(c, y, gl_pol)
    y = _auto_head(c, y, ba_pol)

    y = _new_page(c, "SUPPLEMENTAL INFORMATION")
    y = _head(c, y, "OPERATIONS")
    y = _para(c, y, "Work is performed at customer premises by crews dispatched "
                    "from the yard shown above.")
    y = _para(c, y, "Subcontractors are used for crane and rigging work only and "
                    "are required to carry $1,000,000 general liability.")
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y,
               ["LOCATION", "CLASS CODE / CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE"],
               [["Location 1", "92478 - Heating/Air Conditioning - installation",
                 "Payroll", "$1,910,000"]],
               [1.0, 2.3, 4.9, 6.1])
    y = _certificate(c, y)
    return y


def file_a_no_fleet(c):
    """THE REPORTED BUG. Auto coverage, symbols stated, not one vehicle named."""
    y = _shared_body(
        c, "Redhawk Mechanical Contractors LLC",
        "4820 Sagebrook Parkway, Suite 210, Fort Worth, TX 76137",
        "84-3320198", "Denise Halloran", "(817) 555-0142",
        "dhalloran@redhawkmech.com",
        "Commercial HVAC installation, service and preventive maintenance for "
        "office and light industrial buildings. No residential work.",
        "$6,240,000", "38", "14", "238220",
        "GL-8841027-26", "BA-8841028-26")
    # Deliberately says the schedule is ABSENT, without using the words the
    # self-check forbids ("vehicle" / "VIN" must not appear as a record here).
    y = _para(c, y, "The unit schedule is maintained by the insured and was not "
                    "attached to this submission. Obtain it before binding.")
    return c


def file_b_fleet_18(c):
    """THE CONTROL. Same forms, same symbols, 18 units and 16 drivers - and
    over the 14 rows the ACORD form can physically print."""
    y = _shared_body(
        c, "Cascade Freight Services LLC",
        "9305 Ironwood Distribution Way, Grand Prairie, TX 75050",
        "86-1129844", "Renata Kowalczyk", "(972) 555-0176",
        "rkowalczyk@cascadefreight.com",
        "Regional less-than-truckload freight pickup and delivery within Texas "
        "and Oklahoma from a single distribution terminal.",
        "$14,700,000", "61", "11", "484121",
        "GL-2209445-26", "BA-2209446-26")

    y = _new_page(c, "BUSINESS AUTO - VEHICLE SCHEDULE")
    y = _vehicles(c, y, 18)
    y = _head(c, y, "GARAGING")
    y = _para(c, y, "All units are garaged at 9305 Ironwood Distribution Way, "
                    "Grand Prairie, TX 75050. Radius of operation: 300 miles.")

    y = _new_page(c, "BUSINESS AUTO - DRIVER SCHEDULE")
    y = _drivers(c, y, 16)
    return c


# --- Optional extras (--full) -----------------------------------------------

def file_c_no_auto(c):
    """No owned, hired or non-owned autos anywhere, stated three ways. Any
    "(Nth vehicle)" card here is indefensible in front of a client."""
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Lantern Bay Bakery Inc - renewal submission")
    y = _applicant(
        c, y, "Lantern Bay Bakery Inc",
        "612 Hollowridge Avenue, San Antonio, TX 78209",
        "81-4406722", "Marisol Santoro", "(210) 555-0133",
        "msantoro@lanternbaybakery.com",
        "Retail bakery and cafe with an attached wholesale production kitchen "
        "supplying three local grocery accounts. Seating for 34.",
        "$1,940,000", "27", "9", "311811", entity="Corporation")
    y = _gl(c, y, "GL-6634201-26")
    y = _head(c, y, "COVERAGE - COMMERCIAL PROPERTY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "CP-6634202-26")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Building Limit", "$1,450,000")
    y = _row(c, y, "Business Personal Property Limit", "$380,000")
    y = _row(c, y, "Deductible", "$2,500 per occurrence")
    y = _row(c, y, "Construction", "Masonry Non-Combustible, built 2004")

    y = _new_page(c, "SUPPLEMENTAL INFORMATION")
    y = _head(c, y, "AUTOMOBILE EXPOSURE")
    y = _para(c, y, "The applicant owns no automobiles, trucks or trailers.")
    y = _para(c, y, "No autos are hired, leased, rented or borrowed.")
    y = _para(c, y, "Employees do not use personal automobiles on company "
                    "business. All wholesale deliveries are made by the "
                    "purchasing grocer's own carrier.")
    y = _head(c, y, "WORKERS COMPENSATION")
    y = _row(c, y, "Policy Number", "WC-6634203-26")
    y = _row(c, y, "Employers Liability", "$1,000,000 / $1,000,000 / $1,000,000")
    y = _row(c, y, "Experience Modification", "1.00 effective 01/01/2026")
    y = _table(c, y,
               ["CLASS CODE", "CLASSIFICATION", "STATE", "ANNUAL PAYROLL",
                "FULL TIME", "PART TIME"],
               [["2003", "Bakery and cracker manufacturing", "TX", "$742,000", "18", "4"],
                ["8810", "Clerical office employees", "TX", "$186,000", "3", "2"]],
               [1.0, 1.9, 4.1, 4.7, 6.0, 6.75])
    y = _head(c, y, "LOCATION 1")
    y = _para(c, y, "612 Hollowridge Avenue, San Antonio, TX 78209 - "
                    "one building, two stories, 8,400 square feet, owned.")
    return c


def file_d_umbrella_only(c):
    """The narrowest C4 regression guard: ACORD 131 + 25 with no auto section
    at all. Neither form carries a fleet, so neither may raise a fleet table."""
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Ironvale Steel Erectors LLC - renewal submission")
    y = _applicant(
        c, y, "Ironvale Steel Erectors LLC",
        "2450 Foundry Bend Drive, Houston, TX 77029",
        "83-9902317", "Curtis Nwachukwu", "(713) 555-0121",
        "cnwachukwu@ironvalesteel.com",
        "Structural steel erection on commercial construction projects, "
        "including bolted connections and welding at heights above three "
        "stories.",
        "$9,830,000", "44", "16", "238120")
    y = _gl(c, y, "GL-7718820-26")

    y = _new_page(c, "COMMERCIAL UMBRELLA / EXCESS LIABILITY")
    y = _row(c, y, "Carrier", CARRIER)
    y = _row(c, y, "Policy Number", "UMB-7718822-26")
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Each Occurrence Limit", "$5,000,000")
    y = _row(c, y, "Aggregate Limit", "$5,000,000")
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _row(c, y, "Coverage Basis", "Follow form over the scheduled underlying")
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(c, y, ["LINE OF BUSINESS", "CARRIER", "POLICY NUMBER", "LIMIT"],
               [["General Liability", CARRIER, "GL-7718820-26", "$1,000,000 / $2,000,000"],
                ["Employers Liability", CARRIER, "WC-7718823-26", "$1,000,000"]],
               [1.0, 2.3, 4.6, 6.0])
    y = _certificate(c, y, "the general liability and umbrella policies")
    return c


# --- Self-verification ------------------------------------------------------

def _text_of(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def _verify(paths: dict) -> list:
    """A fixture that quietly says the wrong thing invalidates every check built
    on it. Assert the words that MUST be there and the words that must NOT."""
    errs = []
    texts = {k: _text_of(v).lower() for k, v in paths.items()}

    def absent(key, *words):
        # WORD BOUNDARIES, not substrings. The first draft used `in` and failed
        # on the bakery because a surname contained "vin". A three-letter
        # absence assertion is meaningless as a substring.
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])",
                         texts[key]):
                errs.append(f"{key}: MUST NOT contain {w!r}")

    def present(key, *words):
        for w in words:
            if w.lower() not in texts[key]:
                errs.append(f"{key}: MUST contain {w!r}")

    # A - auto coverage, certificate holder, and NOT a single vehicle identifier.
    present("A", "business auto", "symbol 7", "combined single limit",
            "certificate holder")
    absent("A", "schedule of vehicles", "vin", "1ft7w2bt5med12345", "f-250",
           "schedule of drivers")

    # B - the same symbol sentence as A (the controlled variable), a fleet
    # larger than the 14 rows the ACORD form prints, and the same certificate.
    present("B", "symbol 7", "combined single limit", "certificate holder",
            "schedule of vehicles - 18 units", "1ft7w2bt5med12345",
            "schedule of drivers - 16 drivers", "jale5w16xh7900124")

    # THE CONTROL ITSELF. Every line A and B share must be identical, or the
    # comparison is measuring something other than the fleet.
    for phrase in ("symbol 7 (specifically described autos)",
                   "liability combined single limit",
                   "each occurrence limit",
                   "certificate holder is named as additional insured"):
        if phrase not in texts["A"] or phrase not in texts["B"]:
            errs.append(f"A/B control broken: {phrase!r} must appear in BOTH")

    if "C" in texts:
        present("C", "owns no automobiles", "no autos are hired",
                "workers compensation", "building limit")
        absent("C", "schedule of vehicles", "vin", "combined single limit",
               "symbol 7", "schedule of drivers")
    if "D" in texts:
        present("D", "schedule of underlying insurance", "self-insured retention",
                "certificate holder")
        absent("D", "schedule of vehicles", "vin", "business auto", "symbol 7")

    # Every file must carry a future policy term, or an expired-term hard stop
    # caps the score at 60 and muddies the capture.
    for k in texts:
        if EFF.lower() not in texts[k]:
            errs.append(f"{k}: proposed effective date {EFF} missing")
    return errs


def main() -> None:
    full = "--full" in sys.argv
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing to {OUT_DIR}")
    paths = {
        "A": _save("A_no_fleet.pdf", file_a_no_fleet),
        "B": _save("B_fleet_18.pdf", file_b_fleet_18),
    }
    if full:
        paths["C"] = _save("C_no_auto_at_all.pdf", file_c_no_auto)
        paths["D"] = _save("D_umbrella_only.pdf", file_d_umbrella_only)

    errs = _verify(paths)
    if errs:
        print("\nFIXTURE SELF-CHECK FAILED:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    print("\nFixture self-check PASSED (contents, absences and the A/B control "
          "all verified).")

    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print("  wrote README-HOW-TO-TEST.md")
    if not full:
        print("  (--full also writes C_no_auto_at_all.pdf and D_umbrella_only.pdf)")


README = f"""
# BUG-07 live test - ghost vehicle questions

**Two files. One form selection. Same routine before and after the fix.**

Generated {TODAY.strftime('%Y-%m-%d')}. Policy term on both: {EFF} to {EXP}.

## The routine (about 5 minutes)

1. Upload `A_no_fleet.pdf` as its own session.
   Generate **ACORD 125 + 127 + 137_CO + 25**.
   Open **Send to Client**. Record the row below.
2. Upload `B_fleet_18.pdf` as its own session.
   Generate **the same four forms**.
   Record the row below.

That is it. Same two files, same four forms, every round.

## What to record

| | A_no_fleet | B_fleet_18 |
|---|---|---|
| Highest "(Nth vehicle)" number you can find | | |
| Client / Agency / Critical / Optional counts | | |
| "Please list the vehicles to be insured" - present? rows? | | |
| "Please list everyone who drives a business vehicle" - present? rows? | | |
| Any "(Nth driver)" or insurance-company cards? | | |

## Why two files and not one

**A names zero vehicles. B names 18.** Everything else in the two documents is
the same - same coverages, same limits, same covered-auto symbol sentence, same
forms.

If the ghost cards were caused by the data, B would show far more than A.
They will come out **nearly identical**. That is the bug in one comparison: the
questionnaire never looks at the fleet.

Proven offline before you run it: ACORD 137_CO on its own produces **365**
vehicle-labelled questions when the fleet is empty, and **365** when it holds
143 vehicles.

## What the cards actually are

A card reading

> Please provide the following details for this vehicle: Year, Make, Model, VIN
> ... **(308th vehicle)**

is not a vehicle. On ACORD 137_CO, card 308 is
`Vehicle_BusinessAutoSymbol_OtherSymbolCode_F`, 309 is
`Vehicle_BusinessAutoSymbol_TwoIndicator_G` ("owned autos only are covered"),
310 is `_ThreeIndicator_G`. It is the covered-auto **symbol grid** wearing a
vehicle label. This selection has **779** such fields: 605 vehicle, 156 driver,
18 insurance-company.

## What "fixed" looks like

| Line | Before | After |
|------|--------|-------|
| Highest "(Nth vehicle)" number | 300+ on both A and B | **no such card at all** |
| A vs B | nearly identical | both zero |
| Client / Optional counts | inflated by hundreds | down by roughly 779 |
| Vehicle table on A | present, **0 rows** | **unchanged** |
| Vehicle table on B | present, **18 rows** + overflow notice | **unchanged** |
| Driver table on B | present, **16 rows** | **unchanged** |
| "(Nth driver)" / insurance-company cards | present | gone |

The four "unchanged" lines are the safety check. Those tables are the real
feature - if any of them moves, tell me before anything else.

ACORD 25 is in the selection on purpose: it carries no fleet, so it also guards
the 2026-08-26 fix that stopped fleet-less forms asking clients to list
vehicles. That table must stay absent for ACORD 25 on every run.

## Optional, one-off

`py backend/scripts/make_bug07_test_pdfs.py --full` also writes:

- `C_no_auto_at_all.pdf` - a bakery that disclaims owned, hired and non-owned
  autos three times and still gets "(Nth vehicle)" cards. Generate 125 + 126 +
  130 + 140 + 25. Good for showing the client; not needed for the fix loop.
- `D_umbrella_only.pdf` - no auto section at all. Generate 125 + 131 + 25.
  The narrowest check that a fleet-less form never raises a fleet table.
"""


if __name__ == "__main__":
    main()
