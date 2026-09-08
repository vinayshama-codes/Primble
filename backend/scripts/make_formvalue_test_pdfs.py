"""make_formvalue_test_pdfs.py - live kit for the 2026-09-05 wrong-value fixes.

    py backend/scripts/make_formvalue_test_pdfs.py

Writes to formvalue_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

THREE files, TWO sessions. Unlike the SYS-07 kit, this one is only provable on
the GENERATED FORMS - every claim is about a value we stamp, not about a card on
the review screen.

  PACKAGE A   A1 + A2 uploaded TOGETHER (one session)
              Carries FIVE of the six fixes at once, because they all land on
              one applicant: a food WHOLESALER whose narrative names its
              customers' businesses, a Cyber line spelled the carrier's way,
              exactly ONE GL class code, AAIS printed as the author of the
              forms, and a certificate whose remarks describe the certificate
              holder without naming anybody.

  PACKAGE B   B1 uploaded ALONE (a second session)
              The control for the half of the fix that is easy to fake by
              turning everything off. Its narrative names THREE business types
              and it carries NO NAICS code, so NATURE OF BUSINESS must come back
              BLANK - asked, not guessed, and not silently answered "No". It
              also carries TWO GL class codes, so the hazard grid must fill rows
              A and B and leave C empty: the phantom-row rule is POSITIONAL, not
              "always blank".

WHY A AND B CANNOT BE ONE SESSION
---------------------------------
A asserts "the classification decides, so we still TICK the right box".
B asserts "with no classification we ASK rather than tick several". One package
cannot make both claims - it has one Nature of Business row. Different insureds
so extraction caches and identity matching never bleed.

WHAT EACH FIX IS EXERCISED BY
-----------------------------
  1  A's ops text names restaurant / retail / service    NATURE OF BUSINESS must
     accounts while NAICS 424490 says wholesale           tick WHOLESALE ONLY
  2  B's ops text names office / retail / service         must tick NOTHING
     and B has NO NAICS and is no contractor
  3  A prints ONE GL class row                            ACORD 126 hazard rows
                                                           B and C must be EMPTY
  4  B prints TWO GL class rows                           rows A and B fill,
                                                           C must be EMPTY
  5  A's Cyber part is titled "Cyber Liability"           ACORD 125 ticks CYBER
                                                           AND PRIVACY once, and
                                                           the OTHER row stays
                                                           empty
  6  A names AAIS as the author of the coverage forms     AAIS must never appear
                                                           as a CARRIER
  7  A2's remarks describe the certificate holder         no ADDITIONAL INTEREST
     without naming anyone                                 may be NAMED
                                                           "Certificate Holder"
  8  A prints its class codes as a rating SCHEDULE        the review screen must
     (not as a by-location list)                           NOT say "no class
                                                           codes found"

Design rules (inherited from make_sys06 / make_sys07, all proven)
------------------------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Dates from TODAY, so nothing drifts into an expired or renewal path.
* No "N/A", no renewal language - both pull the run onto a different code path.
* Self-verified at the bottom by running the SHIPPED resolvers against the
  facts these documents state, so a kit that cannot prove its own claim fails
  before it is handed over.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "formvalue_test_data",
)

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=21)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=21 + 365)).strftime("%m/%d/%Y")
AGENCY = "Ridgeline Commercial Insurance Brokers LLC"


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


def _new_page(c, title, subtitle=""):
    c.showPage()
    return _page(c, title, subtitle)


def _row(c, y, label, value, lw=3.2):
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


def _coverage(c, y, heading, carrier, naic, policy, premium, limits):
    y = _head(c, y, heading)
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Carrier NAIC", naic)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    for label, value in limits:
        y = _row(c, y, label, value)
    y = _row(c, y, "Annual Premium", premium)
    return y


GL_LIMITS = [("Each Occurrence Limit", "$1,000,000"),
             ("General Aggregate Limit", "$2,000,000"),
             ("Products/Completed Operations Aggregate", "$2,000,000"),
             ("Personal and Advertising Injury Limit", "$1,000,000"),
             ("Damage To Rented Premises", "$100,000"),
             ("Medical Expense Limit", "$5,000"),
             ("Coverage Form", "Occurrence")]
AUTO_LIMITS = [("Combined Single Limit - Each Accident", "$1,000,000"),
               ("Covered Autos", "Symbol 1 - Any Auto"),
               ("Comprehensive Deductible", "$1,000"),
               ("Collision Deductible", "$1,000")]
CYBER_LIMITS = [("Aggregate Limit", "$1,000,000"), ("Retention", "$10,000")]


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE A - a FOOD WHOLESALER whose narrative names its customers
# ════════════════════════════════════════════════════════════════════════════

A_INSURED = "Cedar Point Provisions Company"
A_ADDR = "1180 Meridian Industrial Way, Suite 40, Spokane, WA 99202"
A_FEIN = "91-3320774"
A_NAICS = "424490"                 # NAICS sector 42 = WHOLESALE TRADE
# Deliberately names FOUR business types that are not this applicant:
# restaurant, retail, service and office. Every one of them used to tick a box.
A_OPS = ("Wholesale distribution of packaged food products to grocery, "
         "restaurant and retail service accounts from a single office and "
         "warehouse location")
A_CARRIER = "Palouse Mutual Insurance Company"
A_NAIC = "24112"
A_POL_GL = "PMI-GL-660318-26"
A_POL_AUTO = "PMI-CA-660324-26"
A_POL_CYBER = "PMI-CY-660331-26"
A_GL_CLASS = "11288"
A_GL_CLASSIFICATION = "Food products distributors - no manufacturing"


def build_a1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations - new business proposal, no expiring "
              "policy is being replaced")
    y = _row(c, y, "Named Insured", A_INSURED)
    y = _row(c, y, "Mailing Address", A_ADDR)
    y = _row(c, y, "FEIN", A_FEIN)
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Contact", "Priya Raghunathan, (509) 555-0164, "
                              "praghunathan@cedarpointprovisions.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", A_OPS)
    y = _row(c, y, "Annual Gross Sales", "$11,600,000")
    y = _row(c, y, "Number of Employees", "52")
    y = _row(c, y, "Years in Business", "19")
    y = _row(c, y, "NAICS Code", A_NAICS)
    y = _row(c, y, "SIC Code", "5149")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    # EDGE CASE 5: the cyber part is titled the CARRIER's way, not ACORD's.
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", A_CARRIER, A_NAIC, A_POL_GL, "$9,480"],
                ["Commercial Auto", A_CARRIER, A_NAIC, A_POL_AUTO, "$5,120"],
                ["Cyber Liability", A_CARRIER, A_NAIC, A_POL_CYBER, "$2,140"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _row(c, y, "Total Advance Premium", "$16,740")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_GL, "$9,480", GL_LIMITS)
    # EDGE CASE 3 + 8: EXACTLY ONE class row, printed as a RATING SCHEDULE.
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["LOC", "CLASS CODE", "CLASSIFICATION", "PREMIUM BASIS",
                      "EXPOSURE", "RATE"],
               [["1", A_GL_CLASS, A_GL_CLASSIFICATION, "Gross Sales",
                 "$11,600,000", "0.817"]],
               [1.0, 1.4, 2.3, 4.6, 5.7, 6.9])
    y = _para(c, y, "No other classifications apply to this coverage part.")

    y = _new_page(c, "BUSINESS AUTO DECLARATIONS", "Coverage Part - Commercial Auto")
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_AUTO, "$5,120", AUTO_LIMITS)
    y = _head(c, y, "SCHEDULE OF COVERED AUTOS")
    y = _table(c, y, ["YEAR", "MAKE", "MODEL", "VIN", "GVW", "USE"],
               [["2023", "Freightliner", "M2 106", "1FVACWDT4PHNR8842", "33,000",
                 "Commercial"],
                ["2022", "Hino", "L6", "5PVNJ8JV6N4S51203", "25,950", "Commercial"]],
               [1.0, 1.6, 2.7, 3.6, 5.6, 6.4])

    y = _new_page(c, "CYBER LIABILITY DECLARATIONS",
                  "Coverage Part - Cyber Liability")
    y = _coverage(c, y, "CYBER LIABILITY COVERAGE PART", A_CARRIER, A_NAIC,
                  A_POL_CYBER, "$2,140", CYBER_LIMITS)
    # EDGE CASE 6: AAIS named as the AUTHOR of the coverage wording, which is the
    # only reason a bureau's name is ever printed on a policy.
    y = _head(c, y, "FORMS AND ENDORSEMENTS APPLICABLE TO THIS POLICY")
    y = _row(c, y, "Policy Forms", "AAIS (American Association of Insurance Services)")
    y = _table(c, y, ["FORM NUMBER", "FORM TITLE", "PUBLISHER"],
               [["CL 0100 03 20", "Commercial Liability Coverage Part", "AAIS"],
                ["IM 7100 06 04", "Contractors Equipment Coverage Form", "AAIS"],
                ["CG 00 01 04 13", "Commercial General Liability Coverage Form", "ISO"]],
               [1.0, 2.6, 6.3])
    y = _para(c, y, "Coverage is written on AAIS forms. AAIS is an advisory "
                    "organization and is not the insurer.")
    c.save()


def build_a2(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only and "
              "confers no rights upon the certificate holder.")
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Insured", A_INSURED)
    y = _row(c, y, "Insured Address", A_ADDR)
    y = _head(c, y, "INSURERS AFFORDING COVERAGE")
    y = _table(c, y, ["LTR", "INSURER", "NAIC #"], [["A", A_CARRIER, A_NAIC]],
               [1.0, 1.6, 5.9])
    y = _head(c, y, "COVERAGES")
    y = _table(c, y, ["TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
               [["General Liability", A_POL_GL, EFF, EXP, "$1,000,000 Each Occurrence"],
                ["General Liability", A_POL_GL, EFF, EXP, "$2,000,000 General Aggregate"],
                ["Automobile Liability", A_POL_AUTO, EFF, EXP,
                 "$1,000,000 Combined Single Limit"],
                ["Cyber Liability", A_POL_CYBER, EFF, EXP, "$1,000,000 Aggregate"]],
               [1.0, 2.5, 4.15, 5.05, 5.95])
    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    y = _para(c, y, A_OPS + ".")
    # EDGE CASE 7: the arrangement described, nobody named.
    y = _para(c, y, "Certificate holder is an additional insured with respect to "
                    "general liability where required by written contract.")
    y = _para(c, y, "Coverage is written on AAIS forms.")
    c.save()


# ════════════════════════════════════════════════════════════════════════════
# PACKAGE B - THE CONTROL: an ambiguous narrative and NO classification
# ════════════════════════════════════════════════════════════════════════════

B_INSURED = "Harborlight Facility Services Inc"
B_ADDR = "620 Kestrel Avenue, Building 3, Portland, OR 97210"
B_FEIN = "93-2841166"
# Names THREE business types and is none of them decisively. There is NO NAICS
# code anywhere in this document and the applicant is not a contractor, so
# nothing can break the tie - which is the whole point of the control.
B_OPS = ("Janitorial and cleaning service for office buildings and retail "
         "centers under annual maintenance agreements")
B_CARRIER = "Willamette Indemnity Company"
B_NAIC = "16535"
B_POL_GL = "WIC-GL-410927-26"


def build_b1(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant information and coverage request - new business")
    y = _row(c, y, "Named Insured", B_INSURED)
    y = _row(c, y, "Mailing Address", B_ADDR)
    y = _row(c, y, "FEIN", B_FEIN)
    y = _row(c, y, "Entity Type", "Corporation")
    y = _row(c, y, "Contact", "Marcus Threlkeld, (503) 555-0138, "
                              "mthrelkeld@harborlightfs.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Description of Operations", B_OPS)
    y = _row(c, y, "Annual Gross Sales", "$4,850,000")
    y = _row(c, y, "Number of Employees", "63")
    y = _row(c, y, "Years in Business", "11")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", B_CARRIER, B_NAIC, B_POL_GL, "$13,900"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", B_CARRIER, B_NAIC,
                  B_POL_GL, "$13,900", GL_LIMITS)
    # EDGE CASE 4: TWO class rows, so the hazard grid must fill A and B and
    # leave C empty. The phantom-row rule is POSITIONAL, not "always blank".
    y = _head(c, y, "SCHEDULE OF HAZARDS - GENERAL LIABILITY")
    y = _table(c, y, ["LOC", "CLASS CODE", "CLASSIFICATION", "PREMIUM BASIS",
                      "EXPOSURE", "RATE"],
               [["1", "92663", "Building cleaning - interior", "Gross Sales",
                 "$3,400,000", "1.942"],
                ["1", "97447", "Janitorial supplies - distribution", "Gross Sales",
                 "$1,450,000", "0.761"]],
               [1.0, 1.4, 2.3, 4.6, 5.7, 6.9])
    y = _para(c, y, "No other classifications apply to this coverage part.")
    c.save()


# ════════════════════════════════════════════════════════════════════════════
# SELF-VERIFICATION - the kit proves its own claims through the SHIPPED code
# ════════════════════════════════════════════════════════════════════════════

_FORBIDDEN = ("N/A", "renewal", "Renewal", "RENEWAL")
_BOXES = ["Manufacturing", "Restaurant", "Retail", "Service", "Wholesale",
          "Office", "Apartments", "Condominiums", "Institutional", "Contractor"]


def _text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(paths):
    problems = []
    a1, a2, b1 = (_text(p) for p in paths)

    for name, text, want in (("A1", a1, [A_INSURED, A_NAICS, A_GL_CLASS, A_CARRIER,
                                         "Cyber Liability", "AAIS", A_POL_GL]),
                             ("A2", a2, [A_INSURED, "Certificate holder", "AAIS"]),
                             ("B1", b1, [B_INSURED, "92663", "97447", B_CARRIER])):
        for v in want:
            if v not in text:
                problems.append(f"{name} is missing {v!r}")
    for name, text in (("A1", a1), ("A2", a2), ("B1", b1)):
        for bad in _FORBIDDEN:
            if bad in text:
                problems.append(f"{name} contains {bad!r}")
    if "NAICS" in b1 or "naics" in b1.lower():
        problems.append("B1 states a NAICS code - the control needs NONE")
    if A_INSURED in b1 or B_INSURED in a1:
        problems.append("the two packages share an insured")

    # The claims, through the SHIPPED resolvers.
    try:
        import services.pdf_service as ps
        from services.normalization import is_insurance_bureau, is_party_role_label

        def ticked(facts):
            return [b for b in _BOXES if ps._derive_indicator(
                f"BusinessInformation_BusinessType_{b}Indicator_A", facts) == "Yes"]

        a_facts = {"operations_description": A_OPS, "naics_code": A_NAICS}
        if ticked(a_facts) != ["Wholesale"]:
            problems.append(f"A would tick {ticked(a_facts)}, not ['Wholesale'] - "
                            "the kit cannot prove its own claim")
        b_facts = {"operations_description": B_OPS}
        if ticked(b_facts) != []:
            problems.append(f"B would tick {ticked(b_facts)}, not [] - the control "
                            "is not ambiguous enough to prove anything")
        # B's narrative must genuinely name several types, or it proves nothing.
        _hits = [b for b, (_fk, w) in ps._BUSINESS_TYPE_PROSE_WORDS.items()
                 if w in B_OPS.lower()]
        if len(_hits) < 2:
            problems.append(f"B's narrative names only {_hits} - it must name "
                            "several for the ambiguity control to mean anything")
        if not is_insurance_bureau("AAIS"):
            problems.append("AAIS is not recognised as a bureau")
        if not is_party_role_label("Certificate Holder"):
            problems.append("'Certificate Holder' is not recognised as a role label")
        # Hazard rows, from the class counts these documents state.
        one = {"gl_class_code_schedule": [{"class_code": A_GL_CLASS}]}
        two = {"gl_class_code_schedule": [{"class_code": "92663"},
                                          {"class_code": "97447"}]}
        if ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_B", one) is not None:
            problems.append("A's row B is not an owned blank")
        if ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_B", two) != "97447":
            problems.append("B's row B does not fill from the second class")
        if ps._resolve_gl_hazard_row("GeneralLiability_Hazard_ClassCode_C", two) is not None:
            problems.append("B's row C is not an owned blank")
    except Exception as exc:                                  # noqa: BLE001
        problems.append(f"could not verify through the shipped code: {exc}")
    return problems


README = """# Form-value live test - the 2026-09-05 wrong-value fixes

Generated by `backend/scripts/make_formvalue_test_pdfs.py`. Regenerate any time.

**These fixes are only visible on the GENERATED FORMS.** Unlike the SYS-07 kit,
almost nothing here shows on the review screen - so form generation is the test,
not an extra.

---

## Upload 1 - PACKAGE A  (a food wholesaler)

Upload **both files together, in one session:**

    A1_wholesaler_dec.pdf
    A2_wholesaler_certificate.pdf

Then **generate ACORD 125 and ACORD 126.**

The applicant is a food WHOLESALER. Its operations text deliberately names
**restaurant**, **retail**, **service** and **office** - its customers and its
own premises, none of them what it IS - and it carries **NAICS 424490**, which
is wholesale trade.

| # | Where to look | Expected |
|---|---|---|
| 1 | **ACORD 125 page 2, NATURE OF BUSINESS** | **WHOLESALE ticked, and nothing else.** Not Restaurant, not Retail, not Service, not Office. This is the reported defect |
| 2 | **ACORD 125 page 1, LINES OF BUSINESS** | CYBER AND PRIVACY ticked **once**. The blank "other" rows beside it must stay **empty** - no hand-written "Cyber Liability" |
| 3 | **ACORD 126 page 1, SCHEDULE OF HAZARDS** | Row 1 filled (`11288`, Food products distributors, Gross Sales, $11,600,000). **Rows 2 and 3 completely empty** |
| 4 | **ACORD 125 / 126, ADDITIONAL INTEREST** | Either empty, or a real company. It must **not** be named "Certificate Holder" |
| 5 | **Anywhere a CARRIER appears** (125 header, 126 header, Data Consistency) | Always `Palouse Mutual Insurance Company`. **AAIS must never appear as a carrier** - it is named in the documents only as the author of the forms |
| 6 | **Review screen, Warnings** | **No** "GL coverage detected but no class codes found". The class code is right there on the form |

---

## Upload 2 - PACKAGE B  (the control - a SECOND session)

Upload **one file:**

    B1_facility_services_application.pdf

Then **generate ACORD 125 and ACORD 126.**

This applicant's narrative names **office**, **retail** and **service**, and it
carries **no NAICS code at all** and is not a contractor. Nothing can break the
tie.

| # | Where to look | Expected |
|---|---|---|
| 7 | **ACORD 125 page 2, NATURE OF BUSINESS** | **Every box EMPTY.** Not three ticks, and not nine "No"s either - we cannot tell, so we ask |
| 8 | **ACORD 126 page 1, SCHEDULE OF HAZARDS** | Rows 1 AND 2 filled (`92663` and `97447`). **Row 3 empty** |

### Why B matters as much as A

A proves we still tick the RIGHT box. B proves we did not simply switch the
feature off. If B ticks three boxes the fix did not land; if A ticks nothing the
fix went too far. **Both have to be right for the change to be right.**

---

## What to send back

One message per upload. A PASS / DIFFERS list is enough - **one failing line
with what it actually printed beats eight passing ones.**

**Package A** - items 1 to 6, plus:
* a screenshot of ACORD 125 page 2 (NATURE OF BUSINESS + the premises block)
* a screenshot of ACORD 126 page 1 (the hazard grid)
* the warning count and the readiness tier

**Package B** - items 7 and 8, plus the same two screenshots.

### Known and expected - do not report these as failures

* **`$ $9,480`** - a doubled dollar sign on the premium boxes. Confirmed
  defect, deliberately NOT fixed yet: we add a `$` and the ACORD form
  pre-prints one, and changing it moves every money box on all 17 forms.
  Your call whether to take it.
* **`% OF WORK SUBCONTRACTED: 0%`** on ACORD 126 - extraction inventing a
  number from silence. A different item (the extraction-side gap), not this one.
* **The producer block carrying the applicant's contact** - that is **SYS-09**,
  still on the client's own list.
* Missing driver schedule, missing UM/UIM, missing property values - these
  documents genuinely do not state them.

### On scores

Package A should be the same or slightly HIGHER than a comparable run - one
false warning is gone. **If A's score drops, send it - that is a finding.**
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    a1 = os.path.join(OUT_DIR, "A1_wholesaler_dec.pdf")
    a2 = os.path.join(OUT_DIR, "A2_wholesaler_certificate.pdf")
    b1 = os.path.join(OUT_DIR, "B1_facility_services_application.pdf")
    build_a1(a1)
    build_a2(a2)
    build_b1(b1)

    problems = _verify([a1, a2, b1])
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)

    for p in (a1, a2, b1):
        print("wrote", os.path.relpath(p, os.path.dirname(OUT_DIR)))
    print("wrote", os.path.relpath(
        os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), os.path.dirname(OUT_DIR)))
    if problems:
        print("\nSELF-CHECK FAILED:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("\nself-check: OK - A resolves to Wholesale ONLY, B resolves to nothing, "
          "A's hazard row B is an owned blank, B's row B fills and row C does not, "
          "and every value the kit depends on is present")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    main()
