"""make_v1_c3_test_pdfs.py - live test packages for V1 item C3 (SQS Scoring
Integrity & Critical-Field Weighting, client section 3).

    py backend/scripts/make_v1_c3_test_pdfs.py

Writes to v1_c3_testdata/ at the repo root, plus README-HOW-TO-TEST.md with the
numbered checks and exactly what to send back.

EIGHT scenarios. Upload each scenario as its OWN session - every scenario is a
different company on purpose, so extraction caches and cross-document identity
matching can never bleed between them. Where a scenario has two files they MUST
be uploaded together in one session; that is the whole point of those two.

Scenario -> the C3 clause it proves live
    S1  Declarations page ONLY, no contact details    3.3  producer name exempt,
                                                           contact info is NOT
    S2  Dec page + application, same gaps             3.3  exemption must NOT
                                                           apply (2 files)
    S3  GL-only, six Tier 2 facts complete            3.5/3.14 Tier 2 = 100 with
                                                           no payroll or WC data
    S4  Revenue and payroll BOTH absent               owner ruling: charged in
                                                           Structural ONCE, not
                                                           again in Exposure
    S5  Two documents, two different revenues         3.8  conflicting value
                                                           earns partial fill
                                                           credit (2 files)
    S6  Property, location schedule carries addresses 3.12 no physical-address
                                                           warning (6B is the
                                                           control - it fires)
    S7  Effective date AFTER expiration date          3.9  ceiling 60 + the
                                                           REASON on screen
    S8  Loss runs requested and PENDING               3.10/3.11 a credit is
                                                           earned, then survives
                                                           a field edit

Design rules (inherited from make_c2_loss_test_pdfs.py, all proven)
------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave
  (the 2026-08-22 fixture-defect lesson).
* Dates are computed from TODAY so no scenario drifts into an expired-term or
  renewal path it was not designed to exercise.
* S1 and S2 print NO agency name and NO applicant contact anywhere - that
  absence IS the test. Self-verified at the bottom of this file by scanning the
  generated text, because one stray "Producer" line would silently invalidate
  both scenarios.
* S3 prints NO payroll, X-mod, or Workers Comp wording at all - also
  self-verified, for the same reason.
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
    "v1_c3_testdata",
)

TODAY = datetime.now()


def _future(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


EFF = _future(21)
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")


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


def _gl_coverage(c, y, carrier, policy, eff=None, exp=None):
    """`eff`/`exp` are parameters because S7 needs its OWN dates here.

    They used to be hardcoded to the module-level EFF/EXP, so S7 printed its
    deliberately-invalid proposed period AND a perfectly valid policy period in
    the same document. Two different effective dates in one file tripped the
    cross-document date-conflict check, which then became the cap reason -
    a hard stop, so the ceiling still read 60, but for the wrong condition.
    A fixture that passes for the wrong reason is worse than one that fails.
    """
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{eff or EFF} to {exp or EXP}")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Personal & Advertising Injury Limit", "$1,000,000")
    y = _row(c, y, "Annual Premium", "$14,280")
    return y


def _class_codes(c, y, code, desc, basis, exposure, location=None):
    """LOCATION first, because the extraction contract for
    `gl_class_codes_by_location` is ``[{"location": string, "codes": [string]}]``.

    Without a location column the fact came back empty on every scenario and
    Exposure Consistency deducted 20 for "GL coverage with no class codes at
    all" - a pure fixture artefact that showed up as the cap reason on S1, S4,
    S7 and S8 and buried whatever each was actually testing.
    """
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.5, 4.6, 5.9]
    for x, h in zip(cols, ["LOCATION", "CLASS CODE / CLASSIFICATION",
                           "PREMIUM BASIS", "EXPOSURE"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for x, v in zip(cols, [location or "Location 1",
                           f"{code} - {desc}", basis, exposure]):
        c.drawString(x * inch, y, v)
    return y - 0.28 * inch


def _save(name, draw):
    path = os.path.join(OUT_DIR, name)
    c = canvas.Canvas(path, pagesize=LETTER)
    draw(c)
    c.showPage()
    c.save()
    return path


# ═════════════════════════════════════════════════════════════════════════════
# S1 - HARBOR POINT: declarations page ONLY, no agency and no contact details
#      3.3 - producer name stays exempt; contact information does NOT
# ═════════════════════════════════════════════════════════════════════════════
S1_NAME = "HARBOR POINT ELECTRIC LLC"


def s1_dec(c):
    y = _page(c, "COMMERCIAL LINES DECLARATIONS",
              "Meridian Casualty Insurance Company - Renewal Declarations")
    y = _row(c, y, "Named Insured", S1_NAME)
    y = _row(c, y, "Mailing Address", "2140 Wharf Road, Portland ME 04101")
    y = _row(c, y, "FEIN", "27-4419820")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations",
             "Commercial electrical contracting, interior fit-out and service work")
    y = _row(c, y, "Annual Gross Sales", "$3,850,000")
    y = _row(c, y, "Number of Employees", "22")
    y = _row(c, y, "Years in Business", "14")
    y = _row(c, y, "NAICS Code", "238210")
    y = _gl_coverage(c, y, "Meridian Casualty Insurance Company", "MCI-GL-774120")
    y = _class_codes(c, y, "92478", "Electrical Wiring - Within Buildings",
                     "Payroll", "$1,180,000")
    y -= 0.1 * inch
    y = _para(c, y, "This declarations page is issued by the carrier and forms part of the")
    y = _para(c, y, "policy. Retain with your policy documents.")


# ═════════════════════════════════════════════════════════════════════════════
# S2 - RIDGELINE MECHANICAL: dec page + application, SAME gaps as S1
#      3.3 - the exemption must NOT apply once a second document exists
# ═════════════════════════════════════════════════════════════════════════════
S2_NAME = "RIDGELINE MECHANICAL CONTRACTORS LLC"


def s2_dec(c):
    y = _page(c, "COMMERCIAL LINES DECLARATIONS",
              "Sentinel Mutual Insurance Company - Expiring Declarations")
    y = _row(c, y, "Named Insured", S2_NAME)
    y = _row(c, y, "Mailing Address", "915 Foundry Street, Akron OH 44311")
    y = _row(c, y, "FEIN", "34-7726104")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations",
             "HVAC installation and mechanical service for commercial buildings")
    y = _row(c, y, "Annual Gross Sales", "$5,240,000")
    y = _row(c, y, "Number of Employees", "31")
    y = _row(c, y, "Years in Business", "19")
    y = _row(c, y, "NAICS Code", "238220")
    y = _gl_coverage(c, y, "Sentinel Mutual Insurance Company", "SMI-GL-338905")


def s2_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant-completed supplement - general information")
    y = _row(c, y, "Applicant Name", S2_NAME)
    y = _row(c, y, "Mailing Address", "915 Foundry Street, Akron OH 44311")
    y = _row(c, y, "FEIN", "34-7726104")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "HVAC installation and mechanical service for commercial buildings")
    y = _row(c, y, "Annual Gross Sales", "$5,240,000")
    y = _row(c, y, "Number of Employees", "31")
    y = _row(c, y, "Years in Business", "19")
    y = _row(c, y, "NAICS Code", "238220")
    y = _head(c, y, "GENERAL INFORMATION")
    y = _para(c, y, "The applicant operates from a single leased facility. No subsidiaries")
    y = _para(c, y, "or affiliated entities exist. All work is performed by employees.")


# ═════════════════════════════════════════════════════════════════════════════
# S3 - CEDAR & VINE: GL only, all six Tier 2 facts, NO payroll and NO WC
#      3.5 / 3.14 - Tier 2 must reach 100 without payroll / X-mod / WC data
# ═════════════════════════════════════════════════════════════════════════════
S3_NAME = "CEDAR AND VINE INTERIORS INC"


def s3_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability - new business submission")
    y = _row(c, y, "Producer / Agency", "Fairhaven Insurance Advisors")
    y = _row(c, y, "Producer Contact", "Dana Whitfield")
    y = _row(c, y, "Applicant Name", S3_NAME)
    y = _row(c, y, "Mailing Address", "77 Bellwether Lane, Providence RI 02903")
    y = _row(c, y, "Contact Name", "Marcus Alden")
    y = _row(c, y, "Contact Phone", "(401) 555-0182")
    y = _row(c, y, "Contact Email", "malden@cedarandvine.example")
    y = _row(c, y, "FEIN", "05-6612473")
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "Interior design consultancy and showroom retail. Design only.")
    y = _row(c, y, "Annual Gross Sales", "$1,620,000")
    y = _row(c, y, "Number of Employees", "8")
    y = _row(c, y, "Years in Business", "11")
    y = _row(c, y, "NAICS Code", "541410")
    y = _class_codes(c, y, "41675", "Interior Decorators", "Gross Sales",
                     "$1,620,000")
    y = _head(c, y, "GENERAL INFORMATION")
    y = _para(c, y, "The applicant performs no installation and owns no vehicles.")
    y = _para(c, y, "All staff are salaried office and showroom personnel.")


# ═════════════════════════════════════════════════════════════════════════════
# S4 - QUARRY BEND: revenue and payroll BOTH absent
#      Owner ruling - charged in Structural Tier 2 once, NOT again in Exposure
#
#      REDESIGNED 2026-08-25 after the first live run. The original omitted the
#      operations description, and extraction simply READ one out of the class
#      code's classification text ("Building Material Dealers"), so Tier 2 came
#      back 100 and the scenario proved nothing. A DOLLAR FIGURE that is not
#      printed cannot be inferred from a trade name, so revenue is the fact that
#      actually isolates the double count.
# ═════════════════════════════════════════════════════════════════════════════
S4_NAME = "QUARRY BEND SUPPLY COMPANY INC"


def s4_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability - renewal submission, financials to follow")
    y = _row(c, y, "Producer / Agency", "Northgate Risk Partners")
    y = _row(c, y, "Applicant Name", S4_NAME)
    y = _row(c, y, "Mailing Address", "4501 Kiln Road, Chattanooga TN 37402")
    y = _row(c, y, "Contact Name", "Priya Raghavan")
    y = _row(c, y, "Contact Phone", "(423) 555-0147")
    y = _row(c, y, "FEIN", "62-8830517")
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "Wholesale distribution of masonry and building materials")
    y = _row(c, y, "Number of Employees", "44")
    y = _row(c, y, "Years in Business", "26")
    y = _row(c, y, "NAICS Code", "423320")
    # NO revenue figure and NO payroll figure anywhere - that absence IS the test.
    y = _class_codes(c, y, "10073", "Building Material Dealers", "Gross Sales",
                     "See financial statements")
    y = _gl_coverage(c, y, "Allied Continental Insurance", "ACI-GL-660214")
    y = _head(c, y, "GENERAL INFORMATION")
    y = _para(c, y, "Audited financial statements will be provided under separate")
    y = _para(c, y, "cover once the current fiscal year closes.")


# ═════════════════════════════════════════════════════════════════════════════
# S5 - STILLWATER PRESS: two documents, two different annual revenues
#      3.8 - a conflicting value still STAMPS (D16) but earns partial credit
# ═════════════════════════════════════════════════════════════════════════════
S5_NAME = "STILLWATER PRESS AND BINDERY LLC"


def s5_dec(c):
    y = _page(c, "COMMERCIAL LINES DECLARATIONS",
              "Keystone Indemnity Company - Expiring Declarations")
    y = _row(c, y, "Named Insured", S5_NAME)
    y = _row(c, y, "Mailing Address", "308 Ironworks Avenue, Dayton OH 45402")
    y = _row(c, y, "FEIN", "31-5528094")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations",
             "Commercial offset printing, binding and finishing services")
    y = _row(c, y, "Annual Gross Sales", "$2,400,000")
    y = _row(c, y, "Number of Employees", "18")
    y = _row(c, y, "Years in Business", "22")
    y = _row(c, y, "NAICS Code", "323111")
    y = _gl_coverage(c, y, "Keystone Indemnity Company", "KIC-GL-991733")


def s5_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant-completed supplement - updated figures")
    y = _row(c, y, "Producer / Agency", "Beacon Commercial Insurance Group")
    y = _row(c, y, "Applicant Name", S5_NAME)
    y = _row(c, y, "Mailing Address", "308 Ironworks Avenue, Dayton OH 45402")
    y = _row(c, y, "Contact Name", "Theo Brandt")
    y = _row(c, y, "Contact Phone", "(937) 555-0119")
    y = _row(c, y, "FEIN", "31-5528094")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "Commercial offset printing, binding and finishing services")
    # THE CONFLICT: a materially different revenue from the dec page above.
    y = _row(c, y, "Annual Gross Sales", "$3,150,000")
    y = _row(c, y, "Number of Employees", "18")
    y = _row(c, y, "Years in Business", "22")
    y = _row(c, y, "NAICS Code", "323111")


# ═════════════════════════════════════════════════════════════════════════════
# S6 - LANTERN COURT / MILLRACE: physical address
#      3.12 - 6A's location schedule carries the address, so NO warning.
#             6B is the CONTROL: same exposure, no schedule address, warning fires.
# ═════════════════════════════════════════════════════════════════════════════
S6A_NAME = "LANTERN COURT PROPERTIES LLC"
S6B_NAME = "MILLRACE HOLDINGS LLC"


def _property_common(c, y, name, addr, fein):
    y = _row(c, y, "Producer / Agency", "Cornerstone Property Brokers")
    y = _row(c, y, "Applicant Name", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "Contact Name", "Renata Voss")
    y = _row(c, y, "Contact Phone", "(614) 555-0173")
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "Commercial Property")
    y = _row(c, y, "Description of Operations",
             "Ownership and lease of multi-tenant commercial retail buildings")
    y = _row(c, y, "Annual Gross Sales", "$1,940,000")
    y = _row(c, y, "Number of Employees", "6")
    y = _row(c, y, "Years in Business", "17")
    y = _row(c, y, "NAICS Code", "531120")
    return y


def _cope_block(c, y):
    y = _head(c, y, "PROPERTY COVERAGE AND COPE DETAIL")
    y = _row(c, y, "Occupancy Type", "Mercantile - retail tenants")
    y = _row(c, y, "Construction Type", "Joisted Masonry")
    y = _row(c, y, "Building Value", "$3,600,000")
    y = _row(c, y, "Business Personal Property Value", "$420,000")
    y = _row(c, y, "Year Built", "1998")
    y = _row(c, y, "Roof Year", "2019")
    y = _row(c, y, "Sprinkler System", "Full wet-pipe throughout")
    y = _row(c, y, "Fire Protection Class", "3")
    y = _row(c, y, "Valuation Method", "Replacement Cost")
    y = _row(c, y, "Coinsurance Percentage", "90")
    return y


def s6a_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Commercial Property - schedule of locations attached")
    y = _property_common(c, y, S6A_NAME,
                         "PO Box 4820, Columbus OH 43216", "31-7741208")
    y = _cope_block(c, y)
    y = _head(c, y, "SCHEDULE OF LOCATIONS")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 1.6, 4.9, 6.3]
    for x, h in zip(cols, ["LOC", "LOCATION ADDRESS", "CITY / STATE / ZIP",
                           "BUILDING VALUE"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for loc, addr, city, val in [
        ("1", "1450 Lantern Court", "Columbus OH 43215", "$2,100,000"),
        ("2", "88 Weaver Mill Road", "Columbus OH 43219", "$1,500,000"),
    ]:
        for x, v in zip(cols, [loc, addr, city, val]):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch


def s6b_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Commercial Property - CONTROL, no location schedule")
    y = _property_common(c, y, S6B_NAME,
                         "PO Box 9915, Toledo OH 43604", "34-2208846")
    y = _cope_block(c, y)
    y = _head(c, y, "ADDITIONAL INFORMATION")
    y = _para(c, y, "Insured requests coverage on two owned commercial buildings.")
    y = _para(c, y, "Location details to be provided under separate cover.")


# ═════════════════════════════════════════════════════════════════════════════
# S7 - BRIARWOOD FOUNDRY: effective date AFTER the expiration date
#      3.9 - hard stop -> ceiling 60, and the REASON printed on screen
#
#      REDESIGNED 2026-08-25 after the first live run. The original used two
#      conflicting FEINs, which tripped the "Possible multiple submissions"
#      integrity gate BEFORE form generation - so the ceiling and the trace,
#      which is the headline check for all of C3, never rendered. An invalid
#      policy period is a single-document field-level hard stop and reaches the
#      scorer with nothing standing in front of it.
# ═════════════════════════════════════════════════════════════════════════════
S7_NAME = "BRIARWOOD FOUNDRY WORKS INC"
S7_BAD_EFF = _future(400)          # AFTER the expiration below - invalid period
S7_BAD_EXP = _future(35)


def s7_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability - complete submission, policy period in error")
    y = _row(c, y, "Producer / Agency", "Lakeshore Underwriting Services")
    y = _row(c, y, "Applicant Name", S7_NAME)
    y = _row(c, y, "Mailing Address", "6600 Cinder Row, Erie PA 16501")
    y = _row(c, y, "Contact Name", "Owen Castellanos")
    y = _row(c, y, "Contact Phone", "(814) 555-0166")
    y = _row(c, y, "Contact Email", "ocastellanos@briarwoodfoundry.example")
    y = _row(c, y, "FEIN", "25-3390147")
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Proposed Effective Date", S7_BAD_EFF)
    y = _row(c, y, "Proposed Expiration Date", S7_BAD_EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "Ferrous casting and machining for industrial equipment makers")
    y = _row(c, y, "Annual Gross Sales", "$12,750,000")
    y = _row(c, y, "Number of Employees", "68")
    y = _row(c, y, "Years in Business", "38")
    y = _row(c, y, "NAICS Code", "331511")
    y = _class_codes(c, y, "59211", "Foundries - Ferrous", "Gross Sales",
                     "$12,750,000")
    # The SAME invalid period as the proposed dates above. One document must
    # not contradict itself, or a date-conflict stop fires ahead of the
    # invalid-period stop this scenario exists to prove.
    y = _gl_coverage(c, y, "Gladstone Fire and Marine", "GFM-GL-455280",
                     eff=S7_BAD_EFF, exp=S7_BAD_EXP)


# ═════════════════════════════════════════════════════════════════════════════
# S8 - THISTLE & CO: loss runs REQUESTED AND PENDING
#      3.10 / 3.11 - a credit is earned, then survives a field edit
#
#      REDESIGNED 2026-08-25 after the first live run. The original said nothing
#      about losses, which produced only ANSWERABLE cards - and the
#      dismiss-with-reason control renders solely on cards with NO fillable
#      field (AcordModal: `answerable = !!rec.field && onAnswer`). The owner
#      could only "Dismiss" with an empty reason, which earns nothing, so the
#      whole credit path was unreachable and the score never moved.
#
#      A stated loss-run status of PENDING produces exactly one card -
#      "Loss runs requested / pending - update score when received" - whose
#      `loss_recommendation_field` is None, because no typed value closes it:
#      only the arriving document does. That is the card that offers a reason.
# ═════════════════════════════════════════════════════════════════════════════
S8_NAME = "THISTLE AND COMPANY OUTFITTERS INC"


def s8_application(c):
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "General Liability - loss runs requested from prior carrier")
    y = _row(c, y, "Producer / Agency", "Ambrose and Kent Insurance")
    y = _row(c, y, "Applicant Name", S8_NAME)
    y = _row(c, y, "Mailing Address", "1209 Alder Street, Boise ID 83702")
    y = _row(c, y, "Contact Name", "Sylvie Nakamura")
    y = _row(c, y, "Contact Phone", "(208) 555-0138")
    y = _row(c, y, "Contact Email", "snakamura@thistleco.example")
    y = _row(c, y, "FEIN", "82-4471903")
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Proposed Effective Date", EFF)
    y = _row(c, y, "Proposed Expiration Date", EXP)
    y = _row(c, y, "Lines of Business Requested", "General Liability")
    y = _row(c, y, "Description of Operations",
             "Retail sale of outdoor apparel and camping equipment, two stores")
    y = _row(c, y, "Annual Gross Sales", "$4,310,000")
    y = _row(c, y, "Number of Employees", "27")
    y = _row(c, y, "Years in Business", "16")
    y = _row(c, y, "NAICS Code", "451110")
    y = _class_codes(c, y, "18206", "Sporting Goods Stores", "Gross Sales",
                     "$4,310,000")
    y = _head(c, y, "LOSS HISTORY")
    y = _row(c, y, "Loss Run Status",
             "Loss runs have been requested and are pending")
    y = _para(c, y, "Five-year loss runs have been requested from the prior carrier")
    y = _para(c, y, "and are pending. They will be forwarded on receipt.")


# ═════════════════════════════════════════════════════════════════════════════
FILES = [
    ("S1_dec_page_only.pdf",                 s1_dec),
    ("S2A_dec_page.pdf",                     s2_dec),
    ("S2B_application.pdf",                  s2_application),
    ("S3_application_gl_only.pdf",           s3_application),
    ("S4_application_no_revenue_no_payroll.pdf", s4_application),
    ("S5A_dec_page_revenue_2_4M.pdf",        s5_dec),
    ("S5B_application_revenue_3_15M.pdf",    s5_application),
    ("S6A_property_with_location_schedule.pdf", s6a_application),
    ("S6B_property_no_location_schedule.pdf",   s6b_application),
    ("S7_application_invalid_policy_period.pdf", s7_application),
    ("S8_application_loss_runs_pending.pdf", s8_application),
]


# ── Self-verification: the ABSENCES each scenario depends on ────────────────

def _text_of(path: str) -> str:
    try:
        import pdfplumber
    except ImportError:                                        # pragma: no cover
        return ""
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths: dict) -> list:
    """A fixture is only as good as the absence it claims. Every scenario below
    is DEFINED by something not being in the document, so each is scanned rather
    than trusted - the 2026-08-22 stale-fixture lesson, applied at build time."""
    problems = []

    def _scan(fname, banned, why):
        txt = _text_of(paths[fname]).lower()
        if not txt:
            problems.append(f"{fname}: no extractable text at all")
            return
        for word in banned:
            if word.lower() in txt:
                problems.append(f"{fname}: contains {word!r} - {why}")

    # S1/S2 exist to test the Tier 1 exemption: no agency, no applicant contact.
    for f in ("S1_dec_page_only.pdf", "S2A_dec_page.pdf", "S2B_application.pdf"):
        _scan(f, ["Producer", "Agency", "Contact Name", "Contact Phone",
                  "Contact Email"],
              "S1/S2 must carry NO producer or contact details")

    # S3 proves Tier 2 reaches 100 with no payroll or WC data anywhere.
    _scan("S3_application_gl_only.pdf",
          ["Payroll", "Workers Comp", "X-Mod", "Experience Modification"],
          "S3 must carry no payroll or Workers Comp data")

    # S4 is defined by the two ABSENT dollar figures.
    _scan("S4_application_no_revenue_no_payroll.pdf",
          ["Annual Gross Sales:", "Total Annual Payroll", "Annual Payroll"],
          "S4's whole point is that no revenue or payroll figure is printed")

    # S6B is the control: it must NOT carry a location address.
    _scan("S6B_property_no_location_schedule.pdf",
          ["SCHEDULE OF LOCATIONS", "LOCATION ADDRESS"],
          "S6B is the control and must have no location schedule")

    # S8 must state PENDING and must NOT state a loss position - an
    # attestation would move it off the pending path and remove the one
    # fieldless card the credit test depends on.
    _scan("S8_application_loss_runs_pending.pdf",
          ["no claims", "no losses", "no known losses", "claim-free"],
          "S8 must state PENDING, never a loss position")
    _s8 = _text_of(paths["S8_application_loss_runs_pending.pdf"]).lower()
    if "requested and are pending" not in _s8:
        problems.append("S8: the pending loss-run status is not stated")

    # And the conflicts S5/S7 depend on must actually BE different.
    s5a, s5b = _text_of(paths["S5A_dec_page_revenue_2_4M.pdf"]), \
        _text_of(paths["S5B_application_revenue_3_15M.pdf"])
    if "2,400,000" not in s5a or "3,150,000" not in s5b:
        problems.append("S5: the two revenue figures are not both present")
    # S7's hard stop is an INVALID POLICY PERIOD: effective after expiration.
    s7 = _text_of(paths["S7_application_invalid_policy_period.pdf"])
    if S7_BAD_EFF not in s7 or S7_BAD_EXP not in s7:
        problems.append("S7: the invalid policy period is not printed")
    if datetime.strptime(S7_BAD_EFF, "%m/%d/%Y") <= datetime.strptime(
            S7_BAD_EXP, "%m/%d/%Y"):
        problems.append("S7: effective must be AFTER expiration to hard stop")
    # ONE document must not disagree with itself: the ordinary EFF/EXP must not
    # appear anywhere in S7, or a cross-document date conflict fires first.
    for _stray in (EFF, EXP):
        if _stray in s7:
            problems.append(
                f"S7: prints the ordinary period {_stray} alongside its invalid "
                f"one - the date-conflict stop will mask the invalid-period stop")
    return problems


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = {}
    for name, draw in FILES:
        paths[name] = _save(name, draw)
        print(f"  wrote {name}")

    print("\nverifying the absences each scenario depends on...")
    problems = _verify(paths)
    if problems:
        print("\n  FIXTURE PROBLEMS - do not test against these:")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  all scenarios verified\n")

    readme = os.path.join(OUT_DIR, "README-HOW-TO-TEST.md")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(README.strip() + "\n")
    print(f"  wrote README-HOW-TO-TEST.md")
    print(f"\n{len(FILES)} files in {OUT_DIR}")


README = f"""
# V1 C3 - SQS Scoring Integrity: how to test

Generated {TODAY.strftime('%Y-%m-%d')}. **Regenerate before every run**
(`py backend/scripts/make_v1_c3_test_pdfs.py`) - the policy dates are computed
from today, so a stale set can drift into an expired-term path and change what
you see for reasons that have nothing to do with C3.

## The two rules that make or break this

1. **One scenario = one session.** Start a NEW submission for each scenario.
   They are deliberately different companies; mixing them lets cross-document
   identity matching bleed and you will chase ghosts.
2. **Where a scenario lists two files, upload them TOGETHER in that one
   session.** For S2, S5 and S7 the second document is the entire test.

## Where to look

Almost every check below lives in the same place: open the submission, expand
**Total Package Score**, and read the **How** line plus the pillar rows. Click a
pillar to expand its sub-rows.

---

## S1 - Declarations page only  (clause 3.3)

**Upload:** `S1_dec_page_only.pdf` (one file)
**Generate:** ACORD 125

A dec page is issued by the carrier, so it prints no agency name and no
applicant contact details. It should be forgiven for the first and NOT the
second.

**Expect**
- A recommendation asking for **contact information**, and it is worth **real
  points** (not "0").
- A recommendation asking for **producer / agency name**, and it is worth
  **0 points** - still asked for, cannot move the score.
- Structural sub-rows show **Core Application (Tier 1) 80%**.

**Send back:** the package score, and a screenshot of the expanded Structural
rows plus those two recommendation cards.

---

## S2 - Dec page PLUS application  (clause 3.3)

**Upload:** `S2A_dec_page.pdf` **and** `S2B_application.pdf` **together**
**Generate:** ACORD 125

Same missing details as S1, but the dec page is no longer the only document.
The exemption must switch off entirely.

**Expect**
- **Both** producer name and contact information asked for, and **both worth
  real points now**.
- Structural sub-rows show **Core Application (Tier 1) 60%**.
- Package score roughly **2 points lower** than S1's.

**Send back:** the package score and the expanded Structural rows.

---

## S3 - GL only, no payroll and no Workers Comp  (clauses 3.5 / 3.14)

**Upload:** `S3_application_gl_only.pdf`
**Generate:** ACORD 125 + ACORD 126

This submission carries all six Tier 2 facts and deliberately no payroll, no
X-mod and no WC data. Before this fix it was marked down for all of them.

**Expect**
- Structural sub-rows show **Underwriting Profile (Tier 2) 100%**.
- **No recommendation** anywhere saying annual payroll, X-mod, WC payroll period
  or owner/officer exclusions are missing **from Structural Completeness**.
- NAICS is **not** asked of the client, and there are **no suggested-code chips**
  in the questionnaire (clause 3.13).

**Send back:** the Tier 2 row, and the full recommendation list.

---

## S4 - Revenue and payroll both absent  (owner ruling)

**Upload:** `S4_application_no_revenue_no_payroll.pdf`
**Generate:** ACORD 125 + ACORD 126

No revenue figure and no payroll figure are printed anywhere. Revenue is a
Tier 2 field, so Structural should charge for it - **once**. Exposure
Consistency must not charge again.

**Expect**
- Structural's **Underwriting Profile (Tier 2) is 83%**, and its tooltip lists
  **Annual revenue** as the missing item.
- Expand **Exposure Consistency**: **Revenue/Sales is 100%**. That is the whole
  test. If it is below 100, revenue is still being charged twice.
- Payroll/Employee sits at **92%**. The missing 8 is the separate
  "employees but no Workers Comp coverage" rule, not a completeness charge.

**Send back:** the expanded Structural rows AND the expanded Exposure rows.

---

## S5 - Two documents, two different revenues  (clause 3.8)

**Upload:** `S5A_dec_page_revenue_2_4M.pdf` **and**
`S5B_application_revenue_3_15M.pdf` **together**
**Generate:** ACORD 125 + ACORD 126

$2,400,000 on the dec page, $3,150,000 on the application.

**Expect**
- A **Data Consistency** entry for annual revenue showing both figures.
- A value **is still stamped** on the form - a conflict does not blank the box.
- The submission is **not** treated as fully complete on that field.

**Send back:** the Data Consistency panel, and what the revenue box on ACORD
125 actually contains.

---

## S6 - Physical address  (clause 3.12). TWO separate sessions.

**Session A - upload:** `S6A_property_with_location_schedule.pdf`
**Session B - upload:** `S6B_property_no_location_schedule.pdf`
**Generate (both):** ACORD 125 + ACORD 140

Both are property risks with a PO Box for mail. A carries a location schedule
with real street addresses; B does not.

**Expect**
- **A: NO warning** about physical versus mailing address. The schedule already
  says where the risk is.
- **B: the warning DOES fire.** This is the control - if B is silent too, the
  rule has been switched off rather than made smarter.

**Send back:** the warning list for both, side by side.

---

## S7 - Invalid policy period  (clause 3.9 + the traceability ask)

**Upload:** `S7_application_invalid_policy_period.pdf` (ONE file now)
**Generate:** ACORD 125 + ACORD 126

The effective date falls AFTER the expiration date. That is field-level hard
stop #1 in the specification, on a single document, so nothing stands between it
and the scorer.

> The first version of this scenario used two conflicting FEINs and never got
> this far: it tripped the "Possible multiple submissions" integrity gate before
> forms were generated. The second version still fired the wrong stop, because
> the coverage block printed a VALID policy period beside the invalid proposed
> dates and the document contradicted itself. It now prints one period only.

**Expect** - this is the headline check for the whole of C3:
- **How** reads **"71 earned, held at 60 = 60"** (the raw number will vary).
- **Why** names the **policy period**, not a date disagreement between
  documents. There is only one document now, so nothing can disagree.
- The displayed score is **60**.
- Expand the pillars: hover any sub-row for the arithmetic, and the Structural
  rows reconstruct the Structural pillar.

**Send back:** a screenshot of the whole expanded Total Package Score panel.
If the How and Why lines are missing, stop and tell me - nothing else in C3
matters until that renders.

---

## S8 - Credits  (clauses 3.10 / 3.11). Do these in order.

**Upload:** `S8_application_loss_runs_pending.pdf`
**Generate:** ACORD 125 + ACORD 126

### First, find the right card - by its SHAPE, not its wording

A dismissal only earns a credit when it carries a **reason**, and the reason
control appears **only on cards with no fillable field** - a gap no typed value
can close, only an arriving document.

**So: scroll the Recommendations list and find the one card that shows a
"Select a reason" dropdown.** That is the card. Do not go looking for a
particular sentence - which card it is depends on how the document classifies,
and on the last run it was *"Loss run valuation date not detected - recency
unverified"*. Any card with that dropdown works.

Every other card shows only **Open** and **Dismiss**. Dismissing those records
"Dismissed without reason" and is worth zero - by design, not a fault.

### The steps

**1.** Note the **Total Package Score**. Call it **A**.

**2.** On the card WITH the reason dropdown: pick any reason, then Dismiss.
Note the score. Call it **B**.
-> **B should be higher than A.** That is the credit.

**3.** Open either generated form, change **any** field, save.
Note the score. Call it **C**.
-> **C must still include the credit. It must not fall back toward A.**

Step 3 is the whole point. Before this fix, editing any field silently destroyed
every credit a producer had earned.

**Send back: A, B, C.** Three numbers.

> **Scope, stated honestly.** S8 live-tests ONE of clause 3.11's four rules - the
> one that was actually broken. The other three (credits added before the
> ceiling, retiring once the data is filled, never paying twice for one fact)
> need states you cannot reach by clicking, and are covered by unit tests. A
> click-through does not prove them and I am not going to imply it does.

---

## What to send back overall

For each scenario: the **package score**, and the screenshot named under it.
If any scenario behaves differently from the Expect list, send that one first
with the score and the screenshot - a single failing scenario is worth more than
seven passing ones.

Two things worth flagging even though they are expected:
- **S1 and S2 score LOWER than they would have before.** That is the fix, not a
  regression - we were waiving contact information that neither the client's
  document nor the SQS specification ever waived.
- **No NAICS suggestion chips appear anywhere.** Also deliberate (clause 3.13).
"""


if __name__ == "__main__":
    main()
