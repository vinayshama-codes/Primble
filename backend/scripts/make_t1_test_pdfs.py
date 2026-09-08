"""
make_t1_test_pdfs.py - the T1 table-fidelity live test kit.

    py backend/scripts/make_t1_test_pdfs.py

Writes into `t1_test_data/`:

    T1_verdant_slope_package.pdf   ~70 pages / ~300,000 characters
    T1_answer_key.json             the graded expectation set
    README-HOW-TO-TEST.md          what each trap is for and how to read a score

WHY THIS KIT EXISTS
-------------------
Every measurement this codebase has of form-fill quality is a percentage of
"fields that got a value". That number cannot see the defect that actually
matters here: a table on an ACORD form is a set of ROWS, each row one real
entity, and the pipeline resolves it as a set of independent COLUMNS. A run
that fills every cell of a four-row table with values borrowed from four
different trucks scores 100%.

So the key grades FOUR buckets, not two, and reports a fifth number that is
the one to steer by:

    correct              right value, right box
    wrong                a value that contradicts the document
    missing              document states it, form is blank
    must-be-blank hit    form states something the document never did
    ROW-CELL             of the cells in a multi-row group, how many carry the
                         right value FOR THAT ROW

DESIGN RULES, INHERITED FROM THE C5/H7 KITS
-------------------------------------------
1. A fixture must PRINT the value its check cites. `_verify()` re-reads the
   generated PDF with pdfplumber and FAILS THE BUILD if any expected value,
   or any forbidden-value trap, is missing from the extracted text. A trap
   that is not in the document tests nothing and would look like a pass.
2. Every field name in the key is checked against the REAL schema JSON. A key
   naming a field that does not exist is worse than no key.
3. Forbidden values are scoped to the fields they are forbidden IN. A global
   "this string must appear nowhere" match fires on the boxes where the value
   legitimately belongs (the expiring policy number inside a prior-coverage
   box) and burns a session on false alarms.
4. The normalisation contract is fixed HERE, in `_normalise`, before anything
   is scored - otherwise "100%" vs "100" and "Raymond T." vs "Raymond"
   dominate the defect rate and hide the real failures.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _t1_data as D                                            # noqa: E402

from reportlab.lib.pagesizes import LETTER                       # noqa: E402
from reportlab.pdfgen import canvas                              # noqa: E402

ROOT     = Path(__file__).resolve().parents[2]
BACKEND  = Path(__file__).resolve().parents[1]
OUT_DIR  = ROOT / "t1_test_data"
PDF_PATH = OUT_DIR / "T1_verdant_slope_package.pdf"
KEY_PATH = OUT_DIR / "T1_answer_key.json"

FORMS = ["ACORD_125", "ACORD_126", "ACORD_131"]

TARGET_PAGES = 70
LINES_PER_PAGE = 60
WRAP = 112

RNG = random.Random(20260901)     # seeded: the kit must be byte-reproducible


# ═════════════════════════════════════════════════════════════════════════════
# Document construction
# ═════════════════════════════════════════════════════════════════════════════
def _rule(ch: str = "-") -> str:
    return ch * WRAP


def _kv(label: str, value: str, width: int = 34) -> str:
    return f"  {label:<{width}} {value}"


def _para(text: str, indent: str = "  ") -> List[str]:
    return textwrap.wrap(text, WRAP - len(indent),
                         initial_indent=indent, subsequent_indent=indent) or [""]


def _cols(widths: List[int], cells: List[str]) -> str:
    out = "  "
    for w, c in zip(widths, cells):
        c = str(c)
        out += (c[:w - 1] if len(c) >= w else c).ljust(w)
    return out.rstrip()


def _heading(title: str) -> List[str]:
    return ["", _rule("="), f"  {title.upper()}", _rule("="), ""]


# ── the noise bank ───────────────────────────────────────────────────────────
# Policy wording and correspondence with NO figure that collides with a key
# value. `_verify` asserts the disjointness rather than trusting this comment.
_CLAUSE_SUBJECTS = [
    "the insurance afforded under this Coverage Part",
    "any payment made under the Supplementary Payments provision",
    "the duties of the insured in the event of an occurrence, claim or suit",
    "the transfer of rights of recovery against others to us",
    "the representations made by the first Named Insured in the application",
    "the territory in which bodily injury or property damage must take place",
    "the limits of insurance shown in the Declarations",
    "any obligation of the insured to defend a suit seeking damages",
    "the definition of an insured contract as used in this Coverage Part",
    "the exclusion applicable to damage to property owned by the insured",
    "the additional insured status afforded by written contract",
    "the primary and noncontributory provision where required by contract",
    "the notice of cancellation required to be given to a loss payee",
    "the audit and premium determination provision of this policy",
]
_CLAUSE_PREDICATES = [
    "applies separately to each Named Insured against whom claim is made or suit is brought",
    "does not increase the applicable Limits of Insurance shown in the Declarations",
    "is subject to the deductible amount stated in the Schedule of this endorsement",
    "will not be construed to waive any right of recovery except as required by written contract",
    "shall be excess over any other valid and collectible insurance available to the insured",
    "is amended to include as an additional insured the person or organization shown in the Schedule",
    "does not apply to bodily injury or property damage arising out of completed operations",
    "applies only to occurrences taking place during the policy period stated in the Declarations",
    "is void in any case of fraud by the insured relating to this Coverage Part",
    "may be cancelled by the first Named Insured by mailing advance written notice",
    "will be determined by our manual rules, rates, rating plans and classifications in effect",
    "does not apply to any person or organization for whom the insured performs no work",
]
_CLAUSE_TAILS = [
    "at the time the work is performed.",
    "unless otherwise stated in an endorsement attached to this policy.",
    "subject to all other terms, conditions and exclusions of the policy.",
    "regardless of the number of persons or organizations making claim.",
    "and no other change in the policy is effected by this endorsement.",
    "except with respect to the coverage described in the Schedule above.",
    "for the duration of the project identified in the Schedule.",
    "as respects operations performed by or on behalf of the Named Insured.",
]
_FORM_CODES = [
    "CG 00 01 04 13", "CG 20 10 12 19", "CG 20 37 12 19", "CG 24 04 05 09",
    "CG 21 39 10 93", "CG 21 47 12 07", "CG 21 96 03 05", "CG 25 03 05 09",
    "IL 00 17 11 98", "IL 00 21 09 08", "IL 01 46 09 08", "CG 22 79 04 13",
    "CG 21 44 07 98", "CG 04 35 12 07", "CG 20 01 12 19", "CG 21 06 05 14",
]
_ENDORSEMENT_TITLES = [
    "Additional Insured - Owners, Lessees Or Contractors - Scheduled Person Or Organization",
    "Additional Insured - Owners, Lessees Or Contractors - Completed Operations",
    "Waiver Of Transfer Of Rights Of Recovery Against Others To Us",
    "Designated Construction Project General Aggregate Limit",
    "Contractual Liability Limitation",
    "Employment-Related Practices Exclusion",
    "Exclusion - Explosion, Collapse And Underground Property Damage Hazard",
    "Silica Or Silica-Related Dust Exclusion",
    "Exclusion - Access Or Disclosure Of Confidential Or Personal Information",
    "Primary And Noncontributory - Other Insurance Condition",
    "Amendment Of Insured Contract Definition",
    "Colorado Changes - Cancellation And Nonrenewal",
]


def _noise_paragraph() -> List[str]:
    n = RNG.randint(2, 4)
    parts = []
    for _ in range(n):
        parts.append(f"{RNG.choice(_CLAUSE_SUBJECTS).capitalize()} "
                     f"{RNG.choice(_CLAUSE_PREDICATES)} "
                     f"{RNG.choice(_CLAUSE_TAILS)}")
    return _para(" ".join(parts))


def _noise_page_block(title: str) -> List[str]:
    lines = _heading(title)
    for _ in range(RNG.randint(4, 6)):
        lines.append(f"  {RNG.choice(_FORM_CODES)}   {RNG.choice(_ENDORSEMENT_TITLES)}")
        lines.append("")
        lines += _noise_paragraph()
        lines.append("")
    return lines


# ═════════════════════════════════════════════════════════════════════════════
def build_document() -> List[str]:
    """The whole package as a flat list of text lines, in reading order."""
    L: List[str] = []
    ins = D.INSUREDS

    # ---- 1. Transmittal -----------------------------------------------------
    L += _heading("Submission Transmittal")
    L += [_kv("Producer", D.PRODUCER),
          _kv("Producer Address", f"{D.PRODUCER_L1} {D.PRODUCER_L2}"),
          _kv("", f"{D.PRODUCER_CITY} {D.PRODUCER_STATE} {D.PRODUCER_ZIP}"),
          _kv("Producer Phone", D.PRODUCER_PHONE),
          _kv("Producer Fax", D.PRODUCER_FAX),
          _kv("Producer E-mail", D.PRODUCER_EMAIL),
          _kv("Producer Code", D.PRODUCER_CODE),
          "",
          _kv("Underwriter", D.UNDERWRITER),
          _kv("Underwriting Office", D.UW_OFFICE),
          ""]
    L += _para(
        f"Enclosed please find the renewal declarations, schedules and loss experience for "
        f"{ins[0]['name']} effective {D.EFF}. The expiring programme was written by "
        f"{D.PRIOR_CARRIER}; the renewal is bound with {D.CARRIER} under package policy "
        f"{D.POLICY_NO}. The excess layer remains with {D.UMB['carrier']}.")
    L.append("")
    L += _para(
        "Please note the named insured schedule has changed since the expiring term. Four "
        "entities are now named. Correspondence should continue to be directed to the "
        f"attention of {D.CONTACT_NAME}, {D.CONTACT_TITLE}, at {D.CONTACT_PHONE}.")

    # ---- 2. Common Policy Declarations -------------------------------------
    L += _heading("Common Policy Declarations")
    L += [_kv("POLICY NUMBER", D.POLICY_NO),
          _kv("INSURER", D.CARRIER),
          _kv("INSURER NAIC CODE", D.CARRIER_NAIC),
          _kv("POLICY PERIOD FROM", f"{D.EFF}   TO   {D.EXP}"),
          _kv("", "12:01 A.M. Standard Time at the address of the Named Insured"),
          _kv("TRANSACTION", "Renewal of policy " + D.PRIOR['gl']['policy']),
          _kv("BUSINESS DESCRIPTION", "Roofing contractor"),
          _kv("FORM OF BUSINESS", ins[0]["entity"]),
          _kv("NUMBER OF MEMBERS AND MANAGERS", ins[0]["members"]),
          _kv("BUSINESS STARTED", ins[0]["start"]),
          "",
          _kv("NAMED INSURED", ins[0]["name"]),
          _kv("MAILING ADDRESS",
              f"{ins[0]['line1']} {ins[0]['line2']} {ins[0]['city']} "
              f"{ins[0]['state']} {ins[0]['zip']}"),
          _kv("FEDERAL EMPLOYER ID NUMBER", ins[0]["fein"]),
          _kv("BUSINESS PHONE", ins[0]["phone"]),
          _kv("WEBSITE ADDRESS", ins[0]["web"]),
          ""]
    L += ["  IN RETURN FOR THE PAYMENT OF THE PREMIUM, AND SUBJECT TO ALL THE TERMS OF THIS POLICY,",
          "  WE AGREE WITH YOU TO PROVIDE THE INSURANCE AS STATED IN THIS POLICY.", ""]
    L += ["  THIS POLICY CONSISTS OF THE FOLLOWING COVERAGE PARTS FOR WHICH A PREMIUM IS INDICATED.",
          "  THIS PREMIUM MAY BE SUBJECT TO ADJUSTMENT.", ""]
    L += [_cols([56, 24], ["COVERAGE PART", "PREMIUM"]),
          _cols([56, 24], ["COMMERCIAL GENERAL LIABILITY COVERAGE PART", D.GL["premium"]]),
          _cols([56, 24], ["COMMERCIAL PROPERTY COVERAGE PART", "$31,205"]),
          _cols([56, 24], ["COMMERCIAL AUTOMOBILE COVERAGE PART", "$32,170"]),
          _cols([56, 24], ["COMMERCIAL INLAND MARINE COVERAGE PART", "$4,900"]),
          _cols([56, 24], ["TERRORISM RISK INSURANCE ACT COVERAGE", "$1,000"]),
          "",
          _cols([56, 24], ["TOTAL PACKAGE PREMIUM", D.PKG_PREMIUM]),
          "",
          _kv("PREMIUM PAYMENT PLAN", D.BILLING_PLAN),
          _kv("BILLING METHOD", "Direct Bill"),
          _kv("AUDIT PERIOD", "Annual"),
          ""]
    L += _para("Coverage parts marked above are attached to and form part of this policy. The "
               "Commercial Umbrella Coverage Part is written under a separate policy and is not "
               "included in the package premium shown.")

    # ---- 3. Named insured schedule -----------------------------------------
    L += _heading("Schedule of Named Insureds")
    L += _para("The following entities are Named Insureds under this policy. Each entity is "
               "listed with its own federal employer identification number, legal form and "
               "classification codes as reported on the application.")
    L.append("")
    for i, e in enumerate(ins):
        L += ["", f"  ENTITY {i + 1} OF {len(ins)}",
              _kv("  Name", e["name"]),
              _kv("  Federal Employer ID Number", e["fein"]),
              _kv("  Legal Entity", e["entity"]),
              _kv("  Number of Members and Managers", e["members"] or "Not applicable"),
              _kv("  SIC", e["sic"]),
              _kv("  NAICS", e["naics"]),
              _kv("  Mailing Address",
                  f"{e['line1']} {e['line2']} {e['city']} {e['state']} {e['zip']}".replace("  ", " ")),
              _kv("  Business Phone", e["phone"]),
              _kv("  Business Started", e["start"])]
    L += ["", ]
    L += _para(f"Contact for all entities: {D.CONTACT_NAME}, {D.CONTACT_TITLE}. Direct line "
               f"{D.CONTACT_PHONE}. Electronic mail {D.CONTACT_EMAIL}.")
    L.append("")
    L += _para(f"{ins[0]['name']} maintains a public website at {ins[0]['web']}. No other "
               "named insured maintains a separate website.")

    # ---- 4. Forms and endorsements schedule (ISO footer codes) -------------
    L += _heading("Schedule of Forms and Endorsements")
    for code in _FORM_CODES:
        L.append(f"  {code}   {RNG.choice(_ENDORSEMENT_TITLES)}")
    L.append("")
    L += _para("The forms and endorsements listed above apply to the Commercial General "
               "Liability Coverage Part. Forms applicable to other coverage parts are listed "
               "in the schedule attached to each part.")

    # ---- 5. Location schedule ----------------------------------------------
    L += _heading("Schedule of Premises")
    L += [_cols([6, 6, 34, 12, 20, 6, 8],
                ["LOC", "BLDG", "STREET", "UNIT", "CITY", "ST", "ZIP"])]
    L.append("  " + "-" * (WRAP - 4))
    for lo in D.LOCATIONS:
        L.append(_cols([6, 6, 34, 12, 20, 6, 8],
                       [lo["num"], lo["bldg"], lo["line1"], lo["line2"] or "-",
                        lo["city"], lo["state"], lo["zip"]]))
    L.append("")
    L += _para("County, interest, occupancy and area detail for each premises appears below. "
               "Premises are listed in location number order.")
    for lo in D.LOCATIONS:
        L += ["",
              f"  LOCATION {lo['num']} / BUILDING {lo['bldg']}",
              _kv("  Address",
                  f"{lo['line1']} {lo['line2']} {lo['city']} {lo['state']} {lo['zip']}".replace("  ", " ")),
              _kv("  County", lo["county"]),
              _kv("  Interest", lo["interest"]),
              _kv("  Total area occupied by applicant (sq ft)", lo["occupied"]),
              _kv("  Area open to the public (sq ft)", lo["public"]),
              _kv("  Full time employees at this location", lo["ft"]),
              _kv("  Part time employees at this location", lo["pt"]),
              _kv("  Any area leased to others", lo["leased_to_others"]),
              _kv("  Description of operations", lo["ops"])]
    L.append("")
    L += _para("Location 002 includes 4,000 square feet leased to an unaffiliated sheet metal "
               "fabricator under a triple net lease expiring in 2028. All other premises are "
               "occupied solely by the named insureds.")

    # ---- 6. GL declarations -------------------------------------------------
    L += _heading("Commercial General Liability Coverage Part Declarations")
    L += [_kv("POLICY NUMBER", D.POLICY_NO),
          _kv("COVERAGE FORM", f"{D.GL['form']} - {D.GL['base_form_edition']}"),
          _kv("EFFECTIVE DATE", D.EFF),
          _kv("EXPIRATION DATE", D.EXP), ""]
    L += [_cols([64, 24], ["LIMITS OF INSURANCE", "AMOUNT"])]
    L.append("  " + "-" * (WRAP - 4))
    L += [_cols([64, 24], ["EACH OCCURRENCE LIMIT", D.GL["each_occurrence"]]),
          _cols([64, 24], ["GENERAL AGGREGATE LIMIT", D.GL["general_aggregate"]]),
          _cols([64, 24], ["PRODUCTS/COMPLETED OPERATIONS AGGREGATE LIMIT", D.GL["products_aggregate"]]),
          _cols([64, 24], ["PERSONAL AND ADVERTISING INJURY LIMIT", D.GL["personal_adv_injury"]]),
          _cols([64, 24], ["DAMAGE TO PREMISES RENTED TO YOU", D.GL["fire_damage"]]),
          _cols([64, 24], ["MEDICAL EXPENSE LIMIT - ANY ONE PERSON", D.GL["medical_expense"]]),
          "",
          _kv("GENERAL AGGREGATE LIMIT APPLIES PER", D.GL["aggregate_applies"]),
          _kv("BODILY INJURY DEDUCTIBLE", f"{D.GL['deductible']} {D.GL['deductible_basis']}"),
          _kv("GENERAL LIABILITY PREMIUM", D.GL["premium"]),
          ""]
    L += _para("Coverage is written on an occurrence basis. No claims made retroactive date "
               "applies to this Coverage Part and no tail coverage has been purchased.")
    L.append("")
    L += [_kv("EMPLOYEE BENEFITS LIABILITY LIMIT", D.GL["ebl_limit"]),
          _kv("EMPLOYEE BENEFITS RETROACTIVE DATE", D.GL["ebl_retro"]),
          _kv("NUMBER OF EMPLOYEES", D.GL["ebl_employees"]),
          _kv("NUMBER OF EMPLOYEES COVERED", D.GL["ebl_covered"]),
          _kv("EMPLOYEE BENEFITS DEDUCTIBLE PER CLAIM", D.GL["ebl_deductible"])]

    # ---- 7. GL schedule of hazards -----------------------------------------
    L += _heading("General Liability Schedule of Hazards")
    L += [_cols([5, 5, 8, 40, 16, 12, 6],
                ["LOC", "HAZ", "CLASS", "CLASSIFICATION", "PREMIUM BASIS", "EXPOSURE", "TERR"])]
    L.append("  " + "-" * (WRAP - 4))
    for h in D.GL_HAZARDS:
        L.append(_cols([5, 5, 8, 40, 16, 12, 6],
                       [h["loc"], h["haz"], h["class"], h["classification"],
                        h["basis"], h["exposure"], h["territory"]]))
    L.append("")
    L += [_cols([5, 8, 14, 18, 14, 18],
                ["LOC", "CLASS", "PREM/OPS RATE", "PREM/OPS PREMIUM",
                 "PRODUCTS RATE", "PRODUCTS PREMIUM"])]
    L.append("  " + "-" * (WRAP - 4))
    for h in D.GL_HAZARDS:
        L.append(_cols([5, 8, 14, 18, 14, 18],
                       [h["loc"], h["class"], h["po_rate"], h["po_premium"],
                        h["pr_rate"], h["pr_premium"]]))
    L.append("")
    L += _para(f"All classifications shown above are rated in territory "
               f"{D.GL_HAZARDS[0]['territory']}. The rating territory for the Commercial "
               f"Automobile Coverage Part is territory {D.AUTO_TERRITORY} and is shown on the "
               f"automobile declarations; it does not apply to any general liability "
               f"classification.")
    L.append("")
    for _h in D.GL_HAZARDS:
        L += _para(f"The full classification wording for class {_h['class']} is "
                   f"{_h['classification']}. It is rated on {_h['basis']} with an "
                   f"exposure of {_h['exposure']} in territory {_h['territory']}.")
        L.append("")

    # ---- 8. Contractors supplemental data ----------------------------------
    L += _heading("Contractors Supplemental Data")
    L += [_kv("TOTAL COST OF WORK SUBCONTRACTED", D.CONTRACTORS["subcontract_cost"]),
          _kv("PERCENTAGE OF WORK SUBCONTRACTED", D.CONTRACTORS["subcontract_pct"]),
          _kv("FULL TIME EMPLOYEES", D.CONTRACTORS["full_time"]),
          _kv("PART TIME EMPLOYEES", D.CONTRACTORS["part_time"]),
          _kv("ANNUAL PAYROLL", D.EXPOSURE["payroll"]),
          ""]
    L += _para("Description of operations: " + D.OPERATIONS + ".")
    L.append("")
    for _fld, (_ans, sentence) in D.YN_EVIDENCE.items():
        if _fld.startswith("ACORD_126|Contractors_"):
            L += _para(sentence)
            L.append("")

    # ---- 9. Property declarations (noise for 125/126/131) ------------------
    L += _heading("Commercial Property Coverage Part Declarations")
    L += [_cols([6, 34, 18, 18, 14],
                ["LOC", "PREMISES", "BUILDING LIMIT", "CONTENTS LIMIT", "DEDUCTIBLE"])]
    L.append("  " + "-" * (WRAP - 4))
    prop_rows = [("002", "3390 E Overland Rd Unit B", "$1,340,000", "$410,000", "$5,000"),
                 ("004", "15 Foothills Service Rd", "$2,180,000", "$655,000", "$5,000")]
    for r in prop_rows:
        L.append(_cols([6, 34, 18, 18, 14], list(r)))
    L.append("")
    L += _para("Blanket business personal property is not written. Coverage is written on a "
               "replacement cost basis with an eighty percent coinsurance requirement at each "
               "scheduled location. Wind and hail deductible is five thousand dollars.")

    # ---- 10. Auto declarations (bleed bait) --------------------------------
    L += _heading("Commercial Automobile Coverage Part Declarations")
    L += [_kv("COVERED AUTOS LIABILITY", "Symbol 1 - Any Auto"),
          _kv("LIABILITY COMBINED SINGLE LIMIT", "$1,000,000"),
          _kv("RATING TERRITORY", D.AUTO_TERRITORY),
          _kv("NUMBER OF POWER UNITS", D.EXPOSURE["fleet_count"]),
          _kv("AUTOMOBILE PREMIUM", "$32,170"), ""]
    L += _para(f"Territory {D.AUTO_TERRITORY} is the Denver metropolitan automobile rating "
               "territory and is used for all scheduled power units. Comprehensive and "
               "collision are written at Symbol 7 with a one thousand dollar deductible.")

    # ---- 11. Umbrella declarations -----------------------------------------
    L += _heading("Commercial Excess Liability Declarations")
    L += [_kv("POLICY NUMBER", D.UMB["policy"]),
          _kv("INSURER", D.UMB["carrier"]),
          _kv("INSURER NAIC CODE", D.UMB["naic"]),
          _kv("POLICY PERIOD", f"{D.EFF} TO {D.EXP}"),
          _kv("COVERAGE BASIS", D.UMB["form"]),
          _kv("EACH OCCURRENCE LIMIT", D.UMB["each_occurrence"]),
          _kv("AGGREGATE LIMIT", D.UMB["aggregate"]),
          _kv("SELF INSURED RETENTION", D.UMB["retention"]),
          _kv("EXCESS LIABILITY PREMIUM", D.UMB["premium"]), ""]
    L += _para("This policy is written on an occurrence basis. No retroactive date applies and "
               "the policy is not written on a claims made basis. Employee Benefits Liability "
               "is not scheduled as underlying insurance under this excess policy.")
    L.append("")
    L += _para("There are no apartment units, swimming pools or diving boards at any premises "
               "reported to the excess insurer, and no medical malpractice exposure of any "
               "kind is presented by the applicant.")

    # ---- 12. Schedule of underlying insurance ------------------------------
    L += _heading("Schedule of Underlying Insurance")
    u = D.UNDERLYING
    L += [_cols([26, 34, 20, 12, 12],
                ["COVERAGE", "INSURER", "POLICY NUMBER", "EFFECTIVE", "EXPIRATION"])]
    L.append("  " + "-" * (WRAP - 4))
    L += [_cols([26, 34, 20, 12, 12],
                ["GENERAL LIABILITY", u["gl"]["carrier"], u["gl"]["policy"],
                 u["gl"]["eff"], u["gl"]["exp"]]),
          _cols([26, 34, 20, 12, 12],
                ["AUTOMOBILE LIABILITY", u["auto"]["carrier"], u["auto"]["policy"],
                 u["auto"]["eff"], u["auto"]["exp"]]),
          _cols([26, 34, 20, 12, 12],
                ["EMPLOYERS LIABILITY", u["el"]["carrier"], u["el"]["policy"],
                 u["el"]["eff"], u["el"]["exp"]]),
          _cols([26, 34, 20, 12, 12],
                [u["other_a"]["type"].upper(), u["other_a"]["carrier"],
                 u["other_a"]["policy"], u["other_a"]["eff"], u["other_a"]["exp"]]),
          ""]
    L += _para("The general liability and automobile liability underlying policies are written "
               f"by the same insurer, {u['gl']['carrier']}, under a single package policy "
               f"number, {u['gl']['policy']}. That number is correct for both lines and is not "
               "a transcription error.")
    L.append("")
    L += [_kv("GL PREMISES/OPERATIONS PREMIUM", u["gl"]["po_premium"]),
          _kv("GL PRODUCTS/COMPLETED OPERATIONS PREMIUM", u["gl"]["products_premium"]),
          _kv("GL COVERAGE FORM EDITION DATE", u["gl"]["form_edition"]),
          _kv("AUTO COMBINED SINGLE LIMIT PREMIUM", u["auto"]["csl_premium"]),
          _kv("AUTO MODIFICATION FACTOR", u["auto"]["mod"]),
          _kv("EMPLOYERS LIABILITY PREMIUM", u["el"]["premium"]),
          _kv("EMPLOYERS LIABILITY MODIFICATION FACTOR", u["el"]["mod"]),
          _kv("OTHER POLICY TYPE", u["other_a"]["type"]),
          _kv("OTHER POLICY INSURER", u["other_a"]["carrier"]),
          _kv("OTHER POLICY NUMBER", u["other_a"]["policy"]),
          _kv("OTHER POLICY DESCRIPTION", u["other_a"]["description"]),
          _kv("OTHER POLICY COMBINED SINGLE LIMIT", u["other_a"]["csl"]),
          _kv("OTHER POLICY PREMIUM", u["other_a"]["premium"]), ""]
    L += _para("Only one policy other than general liability, automobile liability and "
               "employers liability is scheduled as underlying insurance. No second other "
               "policy is scheduled.")

    # ---- 13. Loss experience, block one (out of chronological order) -------
    L += _heading("Loss Experience - Valued 02/01/2026")
    L += [_cols([16, 12, 20, 40, 14],
                ["CLAIM NUMBER", "DATE", "LINE", "DESCRIPTION", "PAID"])]
    L.append("  " + "-" * (WRAP - 4))
    for i in D.LOSS_BLOCK_ONE:
        ls = D.LOSSES[i]
        L.append(_cols([16, 12, 20, 40, 14],
                       [ls["claim"], ls["date"], ls["lob"], ls["desc"], ls["paid"]]))
    L.append("")
    L += _para("Reserve, status and subrogation detail for the claims above, and for the "
               "remaining claims in the experience period, is reported in the supplemental "
               "loss detail later in this submission. The experience period is five years.")

    # ---- 14. Applicant narrative / Yes-No evidence -------------------------
    L += _heading("General Information - Applicant Statements")
    L += _para(D.SAFETY_EVIDENCE)
    L.append("")
    for _fld, (_ans, sentence) in D.YN_EVIDENCE.items():
        if sentence is D.SAFETY_EVIDENCE:
            continue
        if _fld.startswith("ACORD_126|Contractors_"):
            continue
        L += _para(sentence)
        L.append("")
    L += _para("The applicant has not been the subject of any foreclosure, repossession or "
               "bankruptcy proceeding, and no judgment or lien has been entered against any "
               "named insured.")

    # ---- 15. Exposure worksheet (products-grid bait) -----------------------
    L += _heading("Exposure and Revenue Worksheet")
    L += [_cols([28, 22], ["ANNUAL GROSS RECEIPTS 2025", D.EXPOSURE["revenue_2025"]]),
          _cols([28, 22], ["ANNUAL GROSS RECEIPTS 2024", D.EXPOSURE["revenue_2024"]]),
          _cols([28, 22], ["ANNUAL GROSS RECEIPTS 2023", D.EXPOSURE["revenue_2023"]]),
          "",
          _kv("TOTAL ANNUAL PAYROLL", D.EXPOSURE["payroll"]),
          _kv("FULL TIME EMPLOYEES", D.EXPOSURE["employees_ft"]),
          _kv("PART TIME EMPLOYEES", D.EXPOSURE["employees_pt"]),
          _kv("TOTAL EMPLOYEES", "51"),
          _kv("POWER UNITS OWNED", D.EXPOSURE["fleet_count"]),
          _kv("WORKMANSHIP WARRANTY PERIOD", f"{D.EXPOSURE['warranty_years']} years"),
          ""]
    L += _para("The applicant manufactures no products. All sheet metal fabricated at location "
               "002 is installed by the applicant on the applicant own contracts and is never "
               "sold to third parties. There is no products schedule for this account and the "
               "products and completed operations exposure is rated on payroll.")
    L.append("")
    L += _para("Gross receipts figures above are stated for rating purposes only and reflect "
               "construction contract revenue. The applicant reports no foreign gross sales; "
               "the question was answered by stating that there are no foreign operations "
               "rather than by reporting an amount.")

    # ---- 16. Expiring programme --------------------------------------------
    L += _heading("Expiring Programme Summary")
    L += [_cols([26, 34, 20, 14], ["LINE", "EXPIRING INSURER", "POLICY NUMBER", "PREMIUM"])]
    L.append("  " + "-" * (WRAP - 4))
    L += [_cols([26, 34, 20, 14],
                ["GENERAL LIABILITY", D.PRIOR_CARRIER, D.PRIOR["gl"]["policy"],
                 D.PRIOR["gl"]["premium"]]),
          _cols([26, 34, 20, 14],
                ["AUTOMOBILE", D.PRIOR_CARRIER, D.PRIOR["auto"]["policy"],
                 D.PRIOR["auto"]["premium"]]),
          _cols([26, 34, 20, 14],
                ["PROPERTY", D.PRIOR_CARRIER, D.PRIOR["property"]["policy"],
                 D.PRIOR["property"]["premium"]]),
          _cols([26, 34, 20, 14],
                ["UMBRELLA", D.PRIOR["umbrella"]["carrier"], D.PRIOR["umbrella"]["policy"],
                 D.PRIOR["umbrella"]["premium"]]),
          ""]
    L += _para(f"All expiring policies incepted {D.PRIOR_EFF} and expire {D.PRIOR_EXP}. The "
               f"expiring general liability, automobile and property policies were written by "
               f"{D.PRIOR_CARRIER}. The expiring umbrella was written by "
               f"{D.PRIOR['umbrella']['carrier']}, which also writes the renewal excess layer.")

    # ---- 17. Additional interests, endorsement wording (role traps) --------
    L += _heading("Additional Interests and Endorsement Schedules")
    L += [_kv("ADDITIONAL INTEREST", D.LIENHOLDER),
          _kv("INTEREST TYPE", "Loss Payee - Equipment Lender"),
          _kv("ADDRESS",
              f"{D.LIENHOLDER_L1} {D.LIENHOLDER_L2} {D.LIENHOLDER_CITY} "
              f"{D.LIENHOLDER_STATE} {D.LIENHOLDER_ZIP}"),
          _kv("APPLIES TO", "Scheduled equipment financed under master lease 4471-B"), ""]
    L += _para("SCHEDULE - ADDITIONAL INSURED - OWNERS, LESSEES OR CONTRACTORS. Name of "
               "additional insured person or organization: " + D.ADDL_INSURED_WORDING + ".")
    L.append("")
    L += _para(D.CANCELLATION_CLAUSE + ".")
    L.append("")
    L += _para("Workers compensation coverage is carried by the applicant through "
               f"{D.UNDERLYING['el']['carrier']} under policy "
               f"{D.UNDERLYING['el']['policy']}.")

    # ---- 18. Supplemental loss detail (far from block one) -----------------
    L += _heading("Supplemental Loss Detail")
    L += [_cols([16, 12, 14, 14, 10, 8],
                ["CLAIM NUMBER", "DATE", "PAID", "RESERVED", "STATUS", "SUBRO"])]
    L.append("  " + "-" * (WRAP - 4))
    for ls in D.LOSSES:
        L.append(_cols([16, 12, 14, 14, 10, 8],
                       [ls["claim"], ls["date"], ls["paid"], ls["reserved"],
                        ls["status"], ls["subro"]]))
    L.append("")
    L += _para("The two claims below were omitted from the loss experience table earlier in "
               "this submission because they arise under coverage parts other than general "
               "liability. They are reported here in full.")
    L.append("")
    for i in D.LOSS_BLOCK_TWO:
        ls = D.LOSSES[i]
        L += ["",
              _kv("  CLAIM NUMBER", ls["claim"]),
              _kv("  DATE OF OCCURRENCE", ls["date"]),
              _kv("  LINE OF BUSINESS", ls["lob"]),
              _kv("  DESCRIPTION", ls["desc"]),
              _kv("  AMOUNT PAID", ls["paid"]),
              _kv("  AMOUNT RESERVED", ls["reserved"]),
              _kv("  CLAIM STATUS", ls["status"]),
              _kv("  SUBROGATION", ls["subro"])]
    L += ["",
          _kv("TOTAL PAID", D.LOSS_PAID_TOTAL),
          _kv("TOTAL RESERVED", D.LOSS_RESERVED_TOTAL),
          _kv("TOTAL INCURRED", D.LOSS_TOTAL_INCURRED),
          _kv("NUMBER OF YEARS OF LOSS INFORMATION", "5")]

    return L


def _pad_to_target(lines: List[str]) -> List[str]:
    """Grow the document with policy wording until it reaches TARGET_PAGES."""
    n = 1
    while len(lines) < TARGET_PAGES * LINES_PER_PAGE:
        lines += _noise_page_block(f"Policy Forms And Conditions - Part {n}")
        n += 1
    return lines[:TARGET_PAGES * LINES_PER_PAGE]


# ═════════════════════════════════════════════════════════════════════════════
# PDF rendering
# ═════════════════════════════════════════════════════════════════════════════
def render_pdf(lines: List[str], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    W, H = LETTER
    left, top, leading = 36, H - 40, 11.8
    pages = 0
    for i in range(0, len(lines), LINES_PER_PAGE):
        chunk = lines[i:i + LINES_PER_PAGE]
        pages += 1
        c.setFont("Courier", 6.6)
        c.drawString(left, top + 14,
                     f"{D.CARRIER}   POLICY {D.POLICY_NO}   "
                     f"INSURED {D.INSUREDS[0]['name']}")
        y = top
        for ln in chunk:
            c.setFont("Courier-Bold" if ln.startswith("  ") and ln.strip().isupper()
                      and len(ln.strip()) < 90 else "Courier", 7.2)
            c.drawString(left, y, ln[:150])
            y -= leading
        c.setFont("Courier", 6.6)
        c.drawString(left, 24, f"Page {pages} of {TARGET_PAGES}")
        c.showPage()
    c.save()
    return pages


# ═════════════════════════════════════════════════════════════════════════════
# Answer key
# ═════════════════════════════════════════════════════════════════════════════
def _schema(form_id: str) -> dict:
    raw = json.loads((BACKEND / "forms_schemas" /
                      f"{form_id}_schema.json").read_text(encoding="utf-8"))
    return raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw


def build_key() -> dict:
    ins, lo = D.INSUREDS, D.LOCATIONS
    u = D.UNDERLYING
    expect: Dict[str, Dict[str, str]] = {f: {} for f in FORMS}
    blank: Dict[str, List[str]] = {f: [] for f in FORMS}

    # ── ACORD 125 ────────────────────────────────────────────────────────────
    e = expect["ACORD_125"]
    e.update({
        "Policy_PolicyNumberIdentifier_A":        D.POLICY_NO,
        "Policy_EffectiveDate_A":                 D.EFF,
        "Policy_ExpirationDate_A":                D.EXP,
        "Policy_Payment_EstimatedTotalAmount_A":  D.PKG_PREMIUM,
        "Insurer_FullName_A":                     D.CARRIER,
        "Insurer_NAICCode_A":                     D.CARRIER_NAIC,
        "Insurer_Underwriter_FullName_A":         D.UNDERWRITER,
        "Producer_FullName_A":                    D.PRODUCER,
        "Producer_MailingAddress_LineOne_A":      D.PRODUCER_L1,
        "Producer_MailingAddress_LineTwo_A":      D.PRODUCER_L2,
        "Producer_MailingAddress_CityName_A":     D.PRODUCER_CITY,
        "Producer_MailingAddress_StateOrProvinceCode_A": D.PRODUCER_STATE,
        "Producer_MailingAddress_PostalCode_A":   D.PRODUCER_ZIP,
        "NamedInsured_BusinessStartDate_A":       ins[0]["start"],
        "NamedInsured_Contact_FullName_A":        D.CONTACT_NAME,
        "NamedInsured_Contact_PrimaryPhoneNumber_A": D.CONTACT_PHONE,
        "NamedInsured_Contact_PrimaryEmailAddress_A": D.CONTACT_EMAIL,
        "NamedInsured_Primary_WebsiteAddress_A":  ins[0]["web"],
        "Policy_Status_RenewIndicator_A":         "Yes",
        "Policy_LineOfBusiness_CommercialGeneralLiability_A": "Yes",
        "Policy_LineOfBusiness_CommercialProperty_A":         "Yes",
        "Policy_LineOfBusiness_BusinessAutoIndicator_A":      "Yes",
        "Policy_LineOfBusiness_UmbrellaIndicator_A":          "Yes",
        "Policy_LineOfBusiness_CommercialInlandMarineIndicator_A": "Yes",
        "Policy_Payment_DirectBillIndicator_A":   "Yes",
        "Policy_Payment_PaymentScheduleCode_A":   D.BILLING_PLAN,
        "LossHistory_InformationYearCount_A":     "5",
        "LossHistory_TotalAmount_A":              D.LOSS_TOTAL_INCURRED,
        # The safety-programme cluster: FOUR boxes, ONE piece of evidence.
        "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A": "Yes",
        "CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B": "Yes",
        "CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B": "Yes",
        "CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B": "Yes",
    })
    for idx, letter in enumerate("ABC"):                # 3 slots, 4 real insureds
        p = ins[idx]
        e[f"NamedInsured_FullName_{letter}"] = p["name"]
        e[f"NamedInsured_SICCode_{letter}"] = p["sic"]
        e[f"NamedInsured_NAICSCode_{letter}"] = p["naics"]
        e[f"NamedInsured_MailingAddress_LineOne_{letter}"] = p["line1"]
        e[f"NamedInsured_MailingAddress_LineTwo_{letter}"] = p["line2"]
        e[f"NamedInsured_MailingAddress_CityName_{letter}"] = p["city"]
        e[f"NamedInsured_MailingAddress_StateOrProvinceCode_{letter}"] = p["state"]
        e[f"NamedInsured_MailingAddress_PostalCode_{letter}"] = p["zip"]
        e[f"NamedInsured_Primary_PhoneNumber_{letter}"] = p["phone"]
        ent = ("LimitedLiabilityCorporation" if p["entity"] == "LLC" else "Corporation")
        e[f"NamedInsured_LegalEntity_{ent}Indicator_{letter}"] = "Yes"
        if p["members"]:
            e[f"NamedInsured_LegalEntity_MemberManagerCount_{letter}"] = p["members"]
    for idx, letter in enumerate("ABCD"):               # 4 slots, 5 real premises
        p = lo[idx]
        e[f"CommercialStructure_Location_ProducerIdentifier_{letter}"] = p["num"]
        e[f"CommercialStructure_PhysicalAddress_LineOne_{letter}"] = p["line1"]
        if p["line2"]:
            e[f"CommercialStructure_PhysicalAddress_LineTwo_{letter}"] = p["line2"]
        e[f"CommercialStructure_PhysicalAddress_CityName_{letter}"] = p["city"]
        e[f"CommercialStructure_PhysicalAddress_CountyName_{letter}"] = p["county"]
        e[f"CommercialStructure_PhysicalAddress_StateOrProvinceCode_{letter}"] = p["state"]
        e[f"CommercialStructure_PhysicalAddress_PostalCode_{letter}"] = p["zip"]
        e[f"BuildingOccupancy_OccupiedArea_{letter}"] = p["occupied"]
        e[f"BuildingOccupancy_OperationsDescription_{letter}"] = p["ops"]
        e[f"BusinessInformation_FullTimeEmployeeCount_{letter}"] = p["ft"]
        e[f"BusinessInformation_PartTimeEmployeeCount_{letter}"] = p["pt"]
        key = ("Owner" if p["interest"] == "Owner" else "Tenant")
        e[f"CommercialStructure_InsuredInterest_{key}Indicator_{letter}"] = "Yes"
    for idx, letter in enumerate("ABC"):                # prior coverage grid
        pass
    e.update({
        "PriorCoverage_GeneralLiability_InsurerFullName_A":      D.PRIOR_CARRIER,
        "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A": D.PRIOR["gl"]["policy"],
        "PriorCoverage_GeneralLiability_EffectiveDate_A":        D.PRIOR_EFF,
        "PriorCoverage_GeneralLiability_ExpirationDate_A":       D.PRIOR_EXP,
        "PriorCoverage_GeneralLiability_TotalPremiumAmount_A":   D.PRIOR["gl"]["premium"],
        "PriorCoverage_Automobile_InsurerFullName_A":            D.PRIOR_CARRIER,
        "PriorCoverage_Automobile_PolicyNumberIdentifier_A":     D.PRIOR["auto"]["policy"],
        "PriorCoverage_Automobile_TotalPremiumAmount_A":         D.PRIOR["auto"]["premium"],
        "PriorCoverage_Property_InsurerFullName_A":              D.PRIOR_CARRIER,
        "PriorCoverage_Property_PolicyNumberIdentifier_A":       D.PRIOR["property"]["policy"],
        "PriorCoverage_Property_TotalPremiumAmount_A":           D.PRIOR["property"]["premium"],
    })
    blank["ACORD_125"] += [
        "BusinessInformation_ParentOrganizationName_A",   # applicant is a parent, not a sub
        "LossHistory_NoPriorLossesIndicator_A",           # there ARE losses
        "Policy_LineOfBusiness_CyberAndPrivacy_A",
        "Policy_LineOfBusiness_CrimeIndicator_A",
        "Policy_LineOfBusiness_LiquorLiabilityIndicator_A",
        "Policy_LineOfBusiness_YachtIndicator_A",
        "Policy_LineOfBusiness_MotorCarrierIndicator_A",
        "Policy_LineOfBusiness_TruckersIndicator_A",
        "Policy_LineOfBusiness_GarageAndDealersIndicator_A",
        "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A",
        "Policy_LineOfBusiness_FiduciaryLiabilityIndicator_A",
        "Policy_LineOfBusiness_BusinessOwnersIndicator_A",
        "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A",
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_A",
        "CommercialPolicy_JudgementOrLienExplanation_A",
        "CommercialPolicy_JudgementOrLien_OccurrenceDate_A",
    ]

    # ── ACORD 126 ────────────────────────────────────────────────────────────
    e = expect["ACORD_126"]
    e.update({
        "GeneralLiability_EachOccurrence_LimitAmount_A":   D.GL["each_occurrence"],
        "GeneralLiability_GeneralAggregate_LimitAmount_A": D.GL["general_aggregate"],
        "GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount_A":
            D.GL["products_aggregate"],
        "GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A":
            D.GL["personal_adv_injury"],
        "GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A":
            D.GL["fire_damage"],
        "GeneralLiability_MedicalExpense_EachPersonLimitAmount_A": D.GL["medical_expense"],
        "GeneralLiability_OccurrenceIndicator_A": "Yes",
        "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A": "Yes",
        "GeneralLiability_EmployeeBenefits_LimitAmount_A":     D.GL["ebl_limit"],
        "GeneralLiability_EmployeeBenefits_RetroactiveDate_A": D.GL["ebl_retro"],
        "GeneralLiability_EmployeeBenefits_EmployeeCount_A":   D.GL["ebl_employees"],
        "GeneralLiability_EmployeeBenefits_EmployeeCoveredCount_A": D.GL["ebl_covered"],
        "GeneralLiability_EmployeeBenefits_PerClaimDeductibleAmount_A": D.GL["ebl_deductible"],
        "Contractors_SubcontractorsPaidAmount_A": D.CONTRACTORS["subcontract_cost"],
        "Contractors_WorkSubcontractedPercent_A": D.CONTRACTORS["subcontract_pct"],
        "Contractors_FullTimeEmployeeCount_A":    D.CONTRACTORS["full_time"],
        "Contractors_PartTimeEmployeeCount_A":    D.CONTRACTORS["part_time"],
    })
    for idx, letter in enumerate("ABC"):
        h = D.GL_HAZARDS[idx]
        e[f"GeneralLiability_Hazard_LocationProducerIdentifier_{letter}"] = h["loc"]
        e[f"GeneralLiability_Hazard_HazardProducerIdentifier_{letter}"] = h["haz"]
        e[f"GeneralLiability_Hazard_ClassCode_{letter}"] = h["class"]
        e[f"GeneralLiability_Hazard_Classification_{letter}"] = h["classification"]
        e[f"GeneralLiability_Hazard_Exposure_{letter}"] = h["exposure"]
        e[f"GeneralLiability_Hazard_TerritoryCode_{letter}"] = h["territory"]
        e[f"GeneralLiability_Hazard_PremisesOperationsRate_{letter}"] = h["po_rate"]
        e[f"GeneralLiability_Hazard_PremisesOperationsPremiumAmount_{letter}"] = h["po_premium"]
        e[f"GeneralLiability_Hazard_ProductsRate_{letter}"] = h["pr_rate"]
        e[f"GeneralLiability_Hazard_ProductsPremiumAmount_{letter}"] = h["pr_premium"]
    # THE PRODUCTS GRID. The document says the applicant manufactures nothing.
    for col in ["ProductName", "AnnualGrossSalesAmount", "UnitCount",
                "InMarketMonthCount", "ExpectedLifeMonthCount", "IntendedUse",
                "PrincipalComponents"]:
        for letter in "ABC":
            blank["ACORD_126"].append(f"ProductAndCompletedOperations_{col}_{letter}")
    blank["ACORD_126"] += [
        "GeneralLiability_ClaimsMadeIndicator_A",
        "GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A",
        "GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate_A",
    ]

    # ── ACORD 131 ────────────────────────────────────────────────────────────
    e = expect["ACORD_131"]
    e.update({
        "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A":         D.UMB["each_occurrence"],
        "ExcessUmbrella_Umbrella_AggregateAmount_A":              D.UMB["aggregate"],
        "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A":  D.UMB["retention"],
        "ExcessUmbrella_OccurrenceIndicator_A":                   "Yes",
        "UnderlyingPolicy_GeneralLiability_InsurerFullName_A":    u["gl"]["carrier"],
        "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A": u["gl"]["policy"],
        "UnderlyingPolicy_GeneralLiability_PolicyEffectiveDate_A":  u["gl"]["eff"],
        "UnderlyingPolicy_GeneralLiability_PolicyExpirationDate_A": u["gl"]["exp"],
        "UnderlyingPolicy_GeneralLiability_PremisesOperationsPremiumAmount_A":
            u["gl"]["po_premium"],
        "UnderlyingPolicy_GeneralLiability_ProductsPremiumAmount_A":
            u["gl"]["products_premium"],
        "UnderlyingPolicy_GeneralLiability_FormEditionDate_A":    u["gl"]["form_edition"],
        "UnderlyingPolicy_Automobile_InsurerFullName_A":          u["auto"]["carrier"],
        "UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A":   u["auto"]["policy"],
        "UnderlyingPolicy_Automobile_PolicyEffectiveDate_A":      u["auto"]["eff"],
        "UnderlyingPolicy_Automobile_PolicyExpirationDate_A":     u["auto"]["exp"],
        "UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A":
            u["auto"]["csl_premium"],
        "UnderlyingPolicy_EmployersLiability_InsurerFullName_A":  u["el"]["carrier"],
        "UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A": u["el"]["policy"],
        "UnderlyingPolicy_EmployersLiability_PolicyEffectiveDate_A": u["el"]["eff"],
        "UnderlyingPolicy_EmployersLiability_PolicyExpirationDate_A": u["el"]["exp"],
        "UnderlyingPolicy_EmployersLiability_PremiumAmount_A":    u["el"]["premium"],
        "UnderlyingPolicy_EmployersLiability_ModificationFactor_A": u["el"]["mod"],
        "UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A":   u["other_a"]["type"],
        "UnderlyingPolicy_OtherPolicy_InsurerFullName_A":         u["other_a"]["carrier"],
        "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A":  u["other_a"]["policy"],
        "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A":     u["other_a"]["eff"],
        "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A":    u["other_a"]["exp"],
        "UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A": u["other_a"]["csl"],
        "UnderlyingPolicy_OtherPolicy_PremiumAmount_A":           u["other_a"]["premium"],
        "UnderlyingCoverage_Coverage_GeneralLiabilityOccurrenceIndicator_A": "Yes",
        "UnderlyingCoverage_Coverage_AnyAutoIndicator_A":         "Yes",
        "BusinessInformation_AnnualGrossReceiptsAmount_A":        D.EXPOSURE["revenue_2025"],
        "BusinessInformation_TotalPayrollAmount_A":               D.EXPOSURE["payroll"],
        "BusinessInformation_EmployeeCount_A":                    "51",
        "BusinessInformation_OperationsDescription_A":            D.OPERATIONS,
    })
    blank["ACORD_131"] += [
        # Only ONE other policy is scheduled. Row B is a fabrication test.
        "UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_B",
        "UnderlyingPolicy_OtherPolicy_InsurerFullName_B",
        "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_B",
        "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_B",
        "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_B",
        "UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_B",
        "UnderlyingPolicy_OtherPolicy_PremiumAmount_B",
        # No habitational or malpractice exposure is stated anywhere.
        "ExcessUmbrella_PropertyRating_ApartmentCount_A",
        "ExcessUmbrella_PropertyRating_ApartmentCount_B",
        "ExcessUmbrella_PropertyRating_SwimmingPoolCount_A",
        "ExcessUmbrella_PropertyRating_SwimmingPoolCount_B",
        "ExcessUmbrella_PropertyRating_DivingBoardCount_A",
        "ExcessUmbrella_PropertyRating_DivingBoardCount_B",
        "ExcessUmbrella_PropertyRating_StructureStoreyCount_A",
        "ExcessUmbrella_PropertyRating_StructureStoreyCount_B",
        "ExcessUmbrella_MalpracticeLiability_BedCount_A",
        "ExcessUmbrella_MalpracticeLiability_DoctorCount_A",
        "ExcessUmbrella_MalpracticeLiability_NurseCount_A",
        # Never stated. A gap-filled "$0" is the RC2 defect.
        "BusinessInformation_ForeignGrossSalesAmount_A",
        # Occurrence form; the document says so in terms.
        "ExcessUmbrella_ClaimsMadeIndicator_A",
        "ExcessUmbrella_ProposedRetroactiveDate_A",
        "ExcessUmbrella_CurrentRetroactiveDate_A",
        # Explicitly declared NOT scheduled as underlying.
        "ExcessUmbrella_EmployeeBenefits_AggregateLimitAmount_A",
        "ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A",
    ]

    # ── Yes/No questions, from the shared evidence table ─────────────────────
    for fq, (ans, _sentence) in D.YN_EVIDENCE.items():
        form, field = fq.split("|", 1)
        expect[form][field] = ans
    for fq in D.YN_UNADDRESSED:
        form, field = fq.split("|", 1)
        blank[form].append(field)

    # ── Row sets: the row-cell metric ────────────────────────────────────────
    row_sets = {
        "ACORD_125": {
            "premises": {
                "slots": list("ABCD"),
                "columns": {
                    "line1": "CommercialStructure_PhysicalAddress_LineOne_{row}",
                    "city":  "CommercialStructure_PhysicalAddress_CityName_{row}",
                    "county": "CommercialStructure_PhysicalAddress_CountyName_{row}",
                    "zip":   "CommercialStructure_PhysicalAddress_PostalCode_{row}",
                    "occupied": "BuildingOccupancy_OccupiedArea_{row}",
                    "ft":    "BusinessInformation_FullTimeEmployeeCount_{row}",
                },
                "rows": [{"line1": p["line1"], "city": p["city"], "county": p["county"],
                          "zip": p["zip"], "occupied": p["occupied"], "ft": p["ft"]}
                         for p in D.LOCATIONS],
            },
            "loss_history": {
                "slots": list("ABC"),
                "columns": {
                    "date": "LossHistory_OccurrenceDate_{row}",
                    "desc": "LossHistory_OccurrenceDescription_{row}",
                    "paid": "LossHistory_PaidAmount_{row}",
                    "reserved": "LossHistory_ReservedAmount_{row}",
                    "lob":  "LossHistory_LineOfBusiness_{row}",
                },
                "rows": [{"date": x["date"], "desc": x["desc"], "paid": x["paid"],
                          "reserved": x["reserved"], "lob": x["lob"]} for x in D.LOSSES],
            },
        },
        "ACORD_126": {
            "gl_hazards": {
                "slots": list("ABC"),
                "columns": {
                    "loc": "GeneralLiability_Hazard_LocationProducerIdentifier_{row}",
                    "class": "GeneralLiability_Hazard_ClassCode_{row}",
                    "exposure": "GeneralLiability_Hazard_Exposure_{row}",
                    "territory": "GeneralLiability_Hazard_TerritoryCode_{row}",
                    "po_rate": "GeneralLiability_Hazard_PremisesOperationsRate_{row}",
                    "po_premium": "GeneralLiability_Hazard_PremisesOperationsPremiumAmount_{row}",
                },
                "rows": [{"loc": h["loc"], "class": h["class"], "exposure": h["exposure"],
                          "territory": h["territory"], "po_rate": h["po_rate"],
                          "po_premium": h["po_premium"]} for h in D.GL_HAZARDS],
            },
        },
        "ACORD_131": {
            "loss_history": {
                "slots": list("ABCDEF"),
                # NO DATE COLUMN, and that is ACORD's design, not a gap.
                # Checked against the real schema: ACORD 131's loss grid has no
                # occurrence-date box at all. Its only date column is
                # `LossHistory_ClaimDate`, whose own tooltip reads "the date the
                # CLAIM WAS FILED" - a different fact, which this document never
                # states (it prints dates of occurrence). Demanding it here made
                # the scorer report 5 phantom missing cells on a grid that was
                # in fact perfect. ACORD 125 keeps its `date` column because it
                # really does print `LossHistory_OccurrenceDate`.
                "columns": {
                    "desc": "LossHistory_OccurrenceDescription_{row}",
                    "paid": "LossHistory_PaidAmount_{row}",
                    "reserved": "LossHistory_ReservedAmount_{row}",
                    "lob":  "LossHistory_LineOfBusiness_{row}",
                },
                "rows": [{"desc": x["desc"], "paid": x["paid"],
                          "reserved": x["reserved"], "lob": x["lob"]} for x in D.LOSSES],
            },
        },
    }

    # ── Forbidden values, SCOPED to the fields they are forbidden in ────────
    forbidden = {
        "ACORD_125": {
            "NamedInsured_FullName_*": [
                D.ADDL_INSURED_WORDING[:60], D.LIENHOLDER, D.PRIOR_CARRIER,
                D.CARRIER, D.PRODUCER, D.UMB["carrier"]],
            "NamedInsured_MailingAddress_LineTwo_*": [D.PRODUCER_L2],
            "NamedInsured_MailingAddress_LineOne_*": [D.PRODUCER_L1],
            "Insurer_FullName_A": [D.PRIOR_CARRIER, D.PRODUCER, D.UMB["carrier"]],
            "Policy_Payment_EstimatedTotalAmount_A": [
                D.GL["premium"], D.UMB["premium"], D.PRIOR["gl"]["premium"]],
            "Policy_PolicyNumberIdentifier_A": [
                D.PRIOR["gl"]["policy"], D.UMB["policy"], D.PRIOR["umbrella"]["policy"]],
            "BusinessInformation_ParentOrganizationName_*": [D.CARRIER, D.PRODUCER],
        },
        "ACORD_126": {
            # THE cross-form bleed: the auto rating territory in the GL grid.
            "GeneralLiability_Hazard_TerritoryCode_*": [D.AUTO_TERRITORY],
            "GeneralLiability_Hazard_Exposure_*": [
                D.EXPOSURE["revenue_2025"], D.EXPOSURE["revenue_2024"],
                D.EXPOSURE["revenue_2023"]],
            "GeneralLiability_EachOccurrence_LimitAmount_A": [D.UMB["each_occurrence"]],
            "GeneralLiability_GeneralAggregate_LimitAmount_A": [D.UMB["aggregate"]],
        },
        "ACORD_131": {
            "UnderlyingPolicy_*_InsurerFullName_*": [D.PRIOR_CARRIER, D.PRODUCER],
            "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A": [D.GL["each_occurrence"]],
            "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A": [D.GL["deductible"]],
            "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A": [
                D.UMB["policy"], D.PRIOR["gl"]["policy"]],
        },
    }

    # ── Shape rules: a code must match the shape of its own box ─────────────
    shapes = {
        "ACORD_125": {
            "NamedInsured_SICCode_*":   {"regex": r"^\d{4}$",  "why": "SIC is 4 digits"},
            "NamedInsured_NAICSCode_*": {"regex": r"^\d{6}$",  "why": "NAICS is 6 digits"},
        },
    }

    # ── Documented-but-unslotted rows: must appear NOWHERE on the form ──────
    expected_absent = {
        "ACORD_125": {
            "why": ("The document states 4 named insureds and 5 premises; the form "
                    "prints 3 and 4. The overflow entities are real - a run that "
                    "drops a slotted row to make room for one of these has "
                    "reordered a schedule, which is the defect this catches."),
            "values": [D.INSUREDS[3]["name"], D.INSUREDS[3]["fein"],
                       D.LOCATIONS[4]["line1"], D.LOCATIONS[4]["city"]],
            "scope": ["NamedInsured_*", "CommercialStructure_*", "BuildingOccupancy_*",
                      "BusinessInformation_*"],
        },
    }

    return {
        "_meta": {
            "kit": "T1 - table fidelity and row identity",
            "generated_by": "backend/scripts/make_t1_test_pdfs.py",
            "read_first": "t1_test_data/README-HOW-TO-TEST.md",
        },
        "_doc": str(PDF_PATH.relative_to(ROOT)).replace("\\", "/"),
        "_forms": FORMS,
        "_normalisation": {
            "case": "insensitive",
            "whitespace": "collapsed",
            "currency": "$ and thousands separators ignored; 1000000 == $1,000,000",
            "percent": "trailing % ignored; 34 == 34%",
            "dates": "MM/DD/YYYY only; a differently formatted date is WRONG",
            "yes_no": "Y == Yes == On == X == true; N == No == false",
            "containment": ("a stamped value that contains the expected one, or vice "
                            "versa, counts CORRECT - ACORD boxes routinely carry a "
                            "longer legal name"),
        },
        "expect": expect,
        "must_be_blank": blank,
        "forbidden": forbidden,
        "shapes": shapes,
        "row_sets": row_sets,
        "expected_absent": expected_absent,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Verification - the build fails rather than shipping a fixture that lies
# ═════════════════════════════════════════════════════════════════════════════
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _verify(key: dict, pages: int, chars: int) -> None:
    import pdfplumber

    problems: List[str] = []

    if not (TARGET_PAGES - 2 <= pages <= TARGET_PAGES + 2):
        problems.append(f"page count {pages}, wanted ~{TARGET_PAGES}")
    # the number that matters is what the pipeline EXTRACTS, not what we wrote
    with pdfplumber.open(PDF_PATH) as _p:
        extracted = chr(10).join((pg.extract_text() or "") for pg in _p.pages)
    if len(extracted) < 290_000:
        problems.append(f"pdfplumber extracts only {len(extracted):,} chars, wanted >= 290,000")

    # 1. every key field name must exist in the real schema
    for form in FORMS:
        schema = _schema(form)
        names = set(schema.keys())
        for field in list(key["expect"][form]) + key["must_be_blank"][form]:
            if field not in names:
                problems.append(f"{form}: key names a field that does not exist: {field}")
        for group, spec in key["row_sets"].get(form, {}).items():
            for col, tmpl in spec["columns"].items():
                for row in spec["slots"]:
                    fn = tmpl.format(row=row)
                    if fn not in names:
                        problems.append(f"{form}: row_set {group}.{col} -> missing {fn}")

    # 2. every expected value must be printed in the document
    with pdfplumber.open(PDF_PATH) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    hay = _norm(text)
    for form in FORMS:
        for field, val in key["expect"][form].items():
            if val in ("Yes", "Y", "N", "No", ""):
                continue                      # derived, not a literal string
            if _norm(val) not in hay:
                problems.append(f"{form}/{field}: expected value not in the PDF: {val!r}")

    # 3. every forbidden value must ALSO be in the document - a trap that is
    #    not present tests nothing and would read as a pass.
    for form, rules in key["forbidden"].items():
        for _scope, vals in rules.items():
            for v in vals:
                if _norm(v) not in hay:
                    problems.append(f"{form}: forbidden trap not present in PDF: {v!r}")

    # 4. the overflow entities must be in the document too
    for _form, spec in key["expected_absent"].items():
        for v in spec["values"]:
            if _norm(v) not in hay:
                problems.append(f"expected_absent value not in PDF: {v!r}")

    # 5. no filler figure may collide with a key figure
    key_amounts = {_norm(v) for form in FORMS for v in key["expect"][form].values()
                   if isinstance(v, str) and v.startswith("$")}
    if len(key_amounts) < 15:
        problems.append("suspiciously few currency expectations - check the key")

    if problems:
        print("\nFIXTURE VERIFICATION FAILED")
        for p in problems:
            print("  - " + p)
        raise SystemExit(1)
    print(f"  verification OK: {pages} pages, {chars:,} chars, "
          f"{sum(len(key['expect'][f]) for f in FORMS)} expectations, "
          f"{sum(len(key['must_be_blank'][f]) for f in FORMS)} must-be-blank")


# ═════════════════════════════════════════════════════════════════════════════
README = """# T1 - table fidelity and row identity

Generated by `py backend/scripts/make_t1_test_pdfs.py`. Do not hand-edit either
file; change `backend/scripts/_t1_data.py` and regenerate, so the document and
the key can never disagree.

    T1_verdant_slope_package.pdf   the submission - {pages} pages, {chars:,} characters
    T1_answer_key.json             what the three forms must and must not say

## What is in the package

A Colorado roofing contractor renewal. Package policy with GL, property, auto
and inland marine; a separate excess layer. Four named insureds, five premises,
three GL classifications, five losses, a populated expiring-programme grid, and
about fifty pages of ordinary policy wording that says nothing about the risk.

## Run it

1. Upload `T1_verdant_slope_package.pdf` as a new submission.
2. Select **ACORD 125, ACORD 126 and ACORD 131**. Nothing else.
3. Generate, download the three PDFs.
4. Score them:

       py backend/scripts/score_form_fill.py --key t1_test_data/T1_answer_key.json \\
           --pdf-dir <folder with the three generated PDFs>

## How to read the score

Four buckets, never two:

| bucket | meaning |
|---|---|
| correct | right value, right box |
| wrong | a value that contradicts the document |
| missing | the document states it, the box is blank |
| must-be-blank hit | the form asserts something the document never said |

and one number to steer by: **ROW-CELL** - across every multi-row group, the
share of cells carrying the right value *for that row*. A run can score 90% on
fields and 40% on row-cells; the second number is the one that tracks the
defect this kit exists to find.

The scorer also prints an **owned-blank census**: fields the pipeline
deliberately refuses to fill (`_AUTHORITATIVE_BLANK_RESOLVERS` and the schedule
resolvers). A `missing` that turns out to be an owned blank is a design
decision, not a defect, and must be read separately or the missing count lies.

## The traps, and what each one proves

| # | trap | what a failure means |
|---|---|---|
| 1 | GL hazard territory `008` on all three rows | a per-field evidence-quote reuse cap blanks legitimately repeated cells |
| 2 | Underlying GL and Auto share one carrier and one policy number | same, on a different form and a different shape |
| 3 | Comma-free unit designators (`Ste 400`, `Unit 12`, `Bldg 3`) | the address splitter leaves the unit in line 1, and it slides into a neighbour |
| 4 | Producer suite `Ste 900` | a producer address fragment reaching an insured box |
| 5 | 4 named insureds / 3 slots, 5 premises / 4 slots | a real row dropped to make room for an overflow row |
| 6 | Losses printed out of order and split across two distant sections | rows assembled by position instead of identity |
| 7 | Products grid with no products anywhere in the document | a whole table fabricated from nearby numbers |
| 8 | Three years of revenue, a fleet count, a 20-year warranty | the exact bait a fabricated products grid reaches for |
| 9 | Additional-insured endorsement wording | legal boilerplate captured as an identity value |
| 10 | `Bank of the Front Range, N.A.` | a lienholder reaching a named-insured box |
| 11 | Cancellation clause printing the insured address | an address in a non-identity role |
| 12 | SIC 4 digits beside NAICS 6 digits, three times | column transposition nothing validates |
| 13 | Auto territory `104` beside GL territory `008` | cross-form value bleed |
| 14 | `Quarterly - 25% Down` | characters lost from a stamped value |
| 15 | One safety sentence answering four form boxes | one piece of evidence, several boxes |
| 16 | Eight questions the document never addresses | borrowed-quote false positives |
| 17 | Foreign sales never stated | an absent amount becoming `$0` |
| 18 | Only one "other" underlying policy | a fabricated second row |
| 19 | Expiring policy numbers lexically close to current ones | expiring values leaking into current boxes |
| 20 | Umbrella $5,000,000 over GL $1,000,000 | the larger limit displacing the smaller |

## Rules this kit follows

* Every value the key cites is printed in the PDF, and every forbidden-value
  trap is printed too - the build fails otherwise. A trap that is not in the
  document tests nothing.
* Every field name in the key is checked against the real schema JSON.
* Forbidden values are scoped to the fields they are forbidden *in*. A global
  "this string must appear nowhere" match fires on boxes where the value
  legitimately belongs and burns a session on false alarms.
* The normalisation contract is fixed in the key (`_normalisation`) before
  anything is scored.
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = _pad_to_target(build_document())
    chars = sum(len(x) for x in lines) + len(lines)
    pages = render_pdf(lines, PDF_PATH)
    print(f"  wrote {PDF_PATH.relative_to(ROOT)}  ({pages} pages, {chars:,} chars of text)")

    key = build_key()
    KEY_PATH.write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"  wrote {KEY_PATH.relative_to(ROOT)}")

    (OUT_DIR / "README-HOW-TO-TEST.md").write_text(
        README.format(pages=pages, chars=chars), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'README-HOW-TO-TEST.md').relative_to(ROOT)}")

    _verify(key, pages, chars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
