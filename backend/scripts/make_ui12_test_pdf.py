"""make_ui12_test_pdf.py - ONE PDF that makes the internal "MERGE REJECTED" row
appear in the pre-form screen's "Review data" popup (client item UI-12).

    py backend/scripts/make_ui12_test_pdf.py

Writes ui12_test_data/ at the repo root: one PDF plus README-HOW-TO-TEST.md.


WHAT UI-12 ACTUALLY IS
----------------------
`_merge_rejected` is internal merge bookkeeping. When one document yields two
different values for the same fact, `_merge_list_fields` elects a winner and
records the losers under that private key so a later step can hold the fact for
a human (`_flag_intra_document_limit_conflicts` -> the Data Consistency picker).

`merge_facts` (package level) pops the key. `extract_facts_long` (per DOCUMENT)
never does - so it stays glued to `doc["facts"]`. The `/extracted-data`
endpoint then prints EVERY key it finds with no filter for private ones, and
the popup's CSS uppercases the label:

    "_merge_rejected"  ->  "Merge Rejected"  ->  MERGE REJECTED

So the user reads our scratchpad, dumped raw.


THE THREE CONDITIONS THIS DOCUMENT HAS TO MEET - all of them, or nothing shows
-----------------------------------------------------------------------------
1. ONE document (the popup is per-document, not per-package). Everything below
   is inside a single "complete policy copy" PDF, which is exactly the shape of
   the file the client reported it on.

2. That document must SPLIT into two or more extraction chunks. `_merge_rejected`
   is only ever written on the multi-partial path - `_merge_list_fields` returns
   a single partial untouched. The split happens at `_effective_chunk_size()`,
   which is 14,000 tokens x 4 = 56,000 chars of document text. Hence the volume
   of policy wording here: it is not padding for its own sake, it is the only
   way to reach two chunks.

3. The SAME fact must carry DIFFERENT values in DIFFERENT chunks. Two values
   inside one chunk are one candidate and merge silently. So the conflicting
   figures below are deliberately far apart, and `verify()` proves the
   separation survives chunking rather than assuming it.

   Note the 14,285-char context carry-over (`_EXTRACTION_OVERLAP_CHARS`): the
   tail of chunk 1 is prepended to chunk 2. Anything in that tail is visible to
   BOTH, which would collapse the conflict. The front block is therefore kept
   well inside the first 40,000 chars.


THE CONFLICTS, AND WHY THESE ONES
---------------------------------
Every pair below is something a real "complete copy" prints twice, so the
fixture stays honest - no invented document shape.

    fact                    front of policy        later in the policy
    ----------------------- --------------------- ----------------------
    gl_each_occurrence      $1,000,000            $3,000,000  (umbrella page)
    gl_aggregate            $2,000,000            $3,000,000  (umbrella page)
    umbrella_limit          $3,000,000            $1,000,000  (amendatory endt)
    policy_number           PKG-2026-118840       UMB-2026-6J7402
    total_revenue           $4,850,000            $5,240,000  (audit exposure)
    total_policy_premium    $10,663.00            $3,418.00   (umbrella page)

Six independent chances to fire, so one model wobble does not blank the test.
The umbrella pair is the same shape the client's own screenshot shows, and it
doubles as the control for check 3 in the README: it must ALSO raise a Data
Consistency row, because that is the feature the client is asking for in place
of the raw dump.

NO umbrella SIR, NO vehicles and NO workers comp payroll: each would raise
unrelated warnings that make the screenshot harder to read. Dates run from
today so nothing drifts into the expired-term or renewal paths.
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
OUT_DIR = os.path.join(REPO, "ui12_test_data")
PDF_NAME = "ui12-halloran-package-policy-complete-copy.pdf"

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=18)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=18 + 365)).strftime("%m/%d/%Y")

INSURED = "Halloran Freight Services LLC"
AGENCY = "Carrick Bay Insurance Partners LLC"
CARRIER = "Sentinel Ridge Mutual Insurance Company"

PKG_POLICY = "PKG-2026-118840"
UMB_POLICY = "UMB-2026-6J7402"

OPS = (
    "Halloran Freight Services LLC operates a regional less-than-truckload freight "
    "forwarding and warehousing business. The applicant leases two cross-dock "
    "terminals, stores palletized dry goods for commercial customers, and arranges "
    "line-haul transportation through contracted motor carriers. No hazardous "
    "materials are stored or handled at any premises and no passenger "
    "transportation of any kind is performed."
)


# -- Layout helpers ---------------------------------------------------------

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.9 * inch, 10.25 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9)
        c.drawString(0.9 * inch, 10.02 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(0.9 * inch, 9.9 * inch, 7.7 * inch, 9.9 * inch)
    return 9.6 * inch


def _row(c, y, label, value, lw=3.1):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.9 * inch, y, f"{label}:")
    c.setFont("Helvetica", 9)
    c.drawString((0.9 + lw) * inch, y, str(value))
    return y - 0.205 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(0.9 * inch, y, text)
    return y - 0.22 * inch


def _wrap(c, y, text, width=104, size=8.6, lead=0.175):
    c.setFont("Helvetica", size)
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            c.drawString(0.9 * inch, y, line)
            y -= lead * inch
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        c.drawString(0.9 * inch, y, line)
        y -= lead * inch
    return y


def _table(c, y, headers, rows, cols):
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in zip(cols, headers):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, str(v))
        y -= 0.185 * inch
    return y - 0.09 * inch


# -- Policy wording filler --------------------------------------------------
#
# Real conditions/exclusions language, which is what actually makes a "complete
# copy" long. Every clause is numbered and topic-varied so no two paragraphs are
# byte-identical - a document built from one repeated string would be testing
# the de-duplicator, not the merge.

_TOPICS = [
    ("DUTIES IN THE EVENT OF OCCURRENCE, OFFENSE, CLAIM OR SUIT",
     "You must see to it that we are notified as soon as practicable of an occurrence or an "
     "offense which may result in a claim. To the extent possible, notice should include how, "
     "when and where the occurrence or offense took place, the names and addresses of any "
     "injured persons and witnesses, and the nature and location of any injury or damage "
     "arising out of the occurrence or offense."),
    ("LEGAL ACTION AGAINST US",
     "No person or organization has a right under this coverage part to join us as a party or "
     "otherwise bring us into a suit asking for damages from an insured, or to sue us on this "
     "coverage part unless all of its terms have been fully complied with. A person or "
     "organization may sue us to recover on an agreed settlement or on a final judgment "
     "against an insured, but we will not be liable for damages that are not payable under the "
     "terms of this coverage part or that are in excess of the applicable limit of insurance."),
    ("OTHER INSURANCE",
     "If other valid and collectible insurance is available to the insured for a loss we cover, "
     "our obligations are limited as described in the following provisions. This insurance is "
     "excess over any other insurance, whether primary, excess, contingent or on any other "
     "basis, that is effective prior to the beginning of the policy period shown in the "
     "declarations and that applies to loss on other than a first dollar basis."),
    ("PREMIUM AUDIT",
     "We will compute all premiums for this coverage part in accordance with our rules and "
     "rates. Premium shown as advance premium is a deposit premium only. At the close of each "
     "audit period we will compute the earned premium for that period and send notice to the "
     "first named insured. The due date for audit and retrospective premiums is the date shown "
     "as the due date on the bill."),
    ("REPRESENTATIONS AND CONCEALMENT",
     "By accepting this policy you agree that the statements in the declarations are accurate "
     "and complete, that those statements are based upon representations you made to us, and "
     "that we have issued this policy in reliance upon your representations. This coverage part "
     "is void in any case of fraud by you as it relates to this coverage part at any time."),
    ("SEPARATION OF INSUREDS",
     "Except with respect to the limits of insurance, and any rights or duties specifically "
     "assigned in this coverage part to the first named insured, this insurance applies as if "
     "each named insured were the only named insured, and separately to each insured against "
     "whom a claim is made or a suit is brought."),
    ("TRANSFER OF RIGHTS OF RECOVERY AGAINST OTHERS TO US",
     "If the insured has rights to recover all or part of any payment we have made under this "
     "coverage part, those rights are transferred to us. The insured must do nothing after loss "
     "to impair them. At our request, the insured will bring suit or transfer those rights to "
     "us and help us enforce them."),
    ("EXCLUSION - EXPECTED OR INTENDED INJURY",
     "This insurance does not apply to bodily injury or property damage expected or intended "
     "from the standpoint of the insured. This exclusion does not apply to bodily injury "
     "resulting from the use of reasonable force to protect persons or property."),
    ("EXCLUSION - CONTRACTUAL LIABILITY",
     "This insurance does not apply to bodily injury or property damage for which the insured "
     "is obligated to pay damages by reason of the assumption of liability in a contract or "
     "agreement. This exclusion does not apply to liability for damages that the insured would "
     "have in the absence of the contract or agreement, or assumed in a contract or agreement "
     "that is an insured contract, provided the bodily injury or property damage occurs "
     "subsequent to the execution of the contract or agreement."),
    ("EXCLUSION - DAMAGE TO PROPERTY",
     "This insurance does not apply to property damage to property you own, rent or occupy, "
     "including any costs or expenses incurred by you or any other person, organization or "
     "entity for repair, replacement, enhancement, restoration or maintenance of such property "
     "for any reason, including prevention of injury to a person or damage to another's "
     "property."),
    ("EXCLUSION - RECALL OF PRODUCTS, WORK OR IMPAIRED PROPERTY",
     "This insurance does not apply to damages claimed for any loss, cost or expense incurred "
     "by you or others for the loss of use, withdrawal, recall, inspection, repair, "
     "replacement, adjustment, removal or disposal of your product, your work or impaired "
     "property, if such product, work or property is withdrawn or recalled from the market or "
     "from use by any person or organization because of a known or suspected defect."),
    ("SUPPLEMENTARY PAYMENTS",
     "We will pay, with respect to any claim we investigate or settle, or any suit against an "
     "insured we defend, all expenses we incur, the cost of bail bonds required because of "
     "accidents or traffic law violations arising out of the use of any vehicle to which the "
     "bodily injury liability coverage applies, and reasonable expenses incurred by the insured "
     "at our request to assist us in the investigation or defense of the claim or suit."),
    ("WHO IS AN INSURED - ORGANIZATION",
     "If you are designated in the declarations as a limited liability company, you are an "
     "insured. Your members are also insureds, but only with respect to the conduct of your "
     "business. Your managers are insureds, but only with respect to their duties as your "
     "managers. Your employees are insureds for acts within the scope of their employment by "
     "you or while performing duties related to the conduct of your business."),
    ("CANCELLATION AND NONRENEWAL",
     "The first named insured shown in the declarations may cancel this policy by mailing or "
     "delivering to us advance written notice of cancellation. We may cancel this policy by "
     "mailing or delivering to the first named insured written notice of cancellation at least "
     "ten days before the effective date of cancellation if we cancel for nonpayment of "
     "premium, or thirty days before the effective date of cancellation if we cancel for any "
     "other reason."),
    ("INSPECTIONS AND SURVEYS",
     "We have the right to make inspections and surveys at any time, to give you reports on the "
     "conditions we find, and to recommend changes. We are not obligated to make any "
     "inspections, surveys, reports or recommendations, and any we do make relate only to "
     "insurability and the premiums to be charged."),
    ("CHANGES AND EXAMINATION OF YOUR BOOKS AND RECORDS",
     "This policy contains all the agreements between you and us concerning the insurance "
     "afforded. The first named insured shown in the declarations is authorized to make changes "
     "in the terms of this policy with our consent. We may examine and audit your books and "
     "records as they relate to this policy at any time during the policy period and up to "
     "three years afterward."),
]


def _filler_pages(c, first_clause_no: int, n_pages: int, part_label: str) -> int:
    """Write *n_pages* of numbered policy wording. Returns the next clause number."""
    clause = first_clause_no
    for _p in range(n_pages):
        c.showPage()
        y = _page(c, f"{part_label} - POLICY FORMS AND CONDITIONS",
                  f"{CARRIER}  |  {INSURED}  |  Page section {clause}")
        while y > 1.0 * inch:
            title, body = _TOPICS[clause % len(_TOPICS)]
            y = _head(c, y, f"{clause}. {title}")
            y = _wrap(c, y, body)
            y = _wrap(c, y, (
                f"This provision is numbered {clause} in the assembled policy copy and applies "
                f"to {part_label.lower()} only. Where a provision of this part conflicts with a "
                f"provision of the common policy conditions, the provision of this part "
                f"controls for the coverage afforded under this part. Nothing in this provision "
                f"extends, restates or amends any limit of insurance shown in any declarations "
                f"page."))
            y -= 0.06 * inch
            clause += 1
    return clause


# -- The document -----------------------------------------------------------

def build_pdf(path: str) -> None:
    c = canvas.Canvas(path, pagesize=LETTER)

    # == BLOCK A - the front of the policy. Must sit well inside the first
    #    40,000 chars so the chunk-1 tail carry-over cannot make it visible to
    #    chunk 2 as well.
    y = _page(c, "COMMON POLICY DECLARATIONS",
              f"{CARRIER}  |  Policy No. {PKG_POLICY}")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", "1140 Dunmore Industrial Parkway, Suite 300, Toledo, OH 43615")
    y = _row(c, y, "FEIN", "36-4418902")
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Marisol Devane, (419) 555-0188, marisol@halloranfreight.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Number", PKG_POLICY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Total Policy Premium", "$10,663.00")
    y = _row(c, y, "Annual Gross Sales", "$4,850,000")
    y = _row(c, y, "Number of Employees", "34")
    y = _row(c, y, "Years in Business", "17")

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _wrap(c, y, OPS)

    y = _head(c, y, "SCHEDULE OF COVERAGE PARTS AND PREMIUMS")
    y = _table(
        c, y,
        ["COVERAGE PART", "POLICY NUMBER", "PREMIUM"],
        [["Commercial General Liability", PKG_POLICY, "$3,954.00"],
         ["Commercial Property", PKG_POLICY, "$2,300.00"],
         ["Business Auto", PKG_POLICY, "$2,991.00"],
         ["Commercial Liability Umbrella", UMB_POLICY, "$3,418.00"]],
        [0.9, 3.6, 6.0],
    )

    c.showPage()
    y = _page(c, "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS",
              f"{CARRIER}  |  Policy No. {PKG_POLICY}")
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate Limit", "$2,000,000", lw=3.9)
    y = _row(c, y, "Personal and Advertising Injury Limit", "$1,000,000", lw=3.9)
    y = _row(c, y, "Damage to Premises Rented to You", "$100,000", lw=3.9)
    y = _row(c, y, "Medical Expense Limit - Any One Person", "$10,000", lw=3.9)
    y = _row(c, y, "General Liability Deductible", "$1,000")
    y = _row(c, y, "General Liability Premium", "$3,954.00")

    y = _head(c, y, "SCHEDULE OF HAZARDS")
    y = _table(
        c, y,
        ["CLASS CODE", "CLASSIFICATION", "BASIS", "EXPOSURE", "RATE", "PREMIUM"],
        [["11288", "Warehouses - private", "Area", "48,000", "0.041", "$1,968"],
         ["99471", "Freight forwarding operations", "Gross Sales", "$4,850,000", "0.409", "$1,986"]],
        [0.9, 2.0, 4.2, 5.1, 6.3, 6.9],
    )

    c.showPage()
    y = _page(c, "COMMERCIAL PROPERTY COVERAGE PART DECLARATIONS",
              f"{CARRIER}  |  Policy No. {PKG_POLICY}")
    y = _row(c, y, "Location 1", "1140 Dunmore Industrial Parkway, Toledo, OH 43615")
    y = _row(c, y, "Building Limit", "$2,150,000")
    y = _row(c, y, "Business Personal Property Limit", "$610,000", lw=3.6)
    y = _row(c, y, "Valuation", "Replacement Cost")
    y = _row(c, y, "Coinsurance", "90%")
    y = _row(c, y, "All Other Perils Deductible", "$5,000")
    y = _row(c, y, "Year Built", "1998")
    y = _row(c, y, "Construction", "Joisted Masonry")
    y = _row(c, y, "Property Premium", "$2,300.00")

    y = _head(c, y, "BUSINESS AUTO COVERAGE PART DECLARATIONS")
    y = _row(c, y, "Liability - Combined Single Limit", "$1,000,000", lw=3.6)
    y = _row(c, y, "Covered Autos - Liability", "Symbol 1 - Any Auto")
    y = _row(c, y, "Business Auto Premium", "$2,991.00")

    # == FILLER - drives the document past the 56,000-char chunk boundary and
    #    keeps the two conflict blocks far apart.
    clause = _filler_pages(c, 1, 9, "COMMERCIAL GENERAL LIABILITY")
    clause = _filler_pages(c, clause, 9, "COMMERCIAL PROPERTY")

    # == BLOCK B - the same facts, different figures, a long way later.
    c.showPage()
    y = _page(c, "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS",
              f"{CARRIER}  |  Policy No. {UMB_POLICY}")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Policy Number", UMB_POLICY)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _head(c, y, "LIMITS OF INSURANCE")
    y = _row(c, y, "Each Occurrence Limit (Liability Coverage)", "$3,000,000", lw=4.0)
    y = _row(c, y, "Aggregate Limit (Liability Coverage)", "$3,000,000", lw=4.0)
    y = _row(c, y, "Personal and Advertising Injury Limit", "$3,000,000", lw=4.0)
    y = _row(c, y, "Total Policy Premium", "$3,418.00", lw=4.0)

    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(
        c, y,
        ["COVERAGE", "CARRIER", "POLICY NUMBER", "LIMITS"],
        [["Commercial General Liability", CARRIER, PKG_POLICY, "$1,000,000 / $2,000,000"],
         ["Business Auto Liability", CARRIER, PKG_POLICY, "$1,000,000 CSL"]],
        [0.9, 2.7, 4.7, 6.1],
    )

    c.showPage()
    y = _page(c, "AMENDATORY ENDORSEMENT - LIMITS OF INSURANCE",
              f"{CARRIER}  |  Policy No. {UMB_POLICY}")
    y = _wrap(c, y, (
        "This endorsement modifies insurance provided under the Commercial Liability Umbrella "
        "Coverage Part. In consideration of the premium charged, it is agreed that the limits "
        "of insurance shown in the umbrella declarations are amended as stated below, effective "
        f"{EFF}."))
    y -= 0.1 * inch
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "Aggregate Limit", "$1,000,000")
    y = _wrap(c, y, (
        "All other terms and conditions of the policy remain unchanged. This endorsement is "
        "attached to and forms part of the policy identified above."))

    y = _head(c, y, "PREMIUM AUDIT EXPOSURE STATEMENT")
    y = _row(c, y, "Annual Gross Sales", "$5,240,000")
    y = _row(c, y, "Number of Employees", "34")
    y = _wrap(c, y, (
        "The exposure figures shown above were reported by the insured at the close of the "
        "audit period and supersede the estimated exposures shown on the declarations for "
        "audit purposes only."))

    y = _head(c, y, "LOSS HISTORY - PRIOR FIVE YEARS")
    y = _table(
        c, y,
        ["DATE OF LOSS", "TYPE", "DESCRIPTION", "PAID", "INCURRED"],
        [["04/18/2023", "Liability", "Third party slip and fall at terminal", "$14,200", "$14,200"],
         ["09/03/2024", "Property", "Wind damage to dock canopy", "$21,800", "$26,400"]],
        [0.9, 2.1, 3.0, 5.9, 6.8],
    )

    _filler_pages(c, clause, 4, "COMMERCIAL LIABILITY UMBRELLA")

    c.showPage()
    c.save()


# -- Self-verification ------------------------------------------------------
#
# HONEST ABOUT ITS SCOPE. An offline probe proves the FUNCTION, never the SEAM
# (the standing lesson from the dec-index arc). So this proves two things and
# claims nothing more:
#
#   1. the PDF really does split into >=2 extraction chunks, and the two
#      conflict blocks really do land in different chunks - driven through the
#      REAL `_effective_chunk_size` and `_chunk_by_sections`, not a local copy;
#   2. given facts of that shape from two chunks, the REAL `_merge_list_fields`
#      writes `_merge_rejected` into the facts it returns.
#
# It CANNOT prove the LLM reads those figures off this PDF. Only the live
# upload does that - which is the point of the kit.

CONFLICTS = [
    ("policy_number",        PKG_POLICY,   UMB_POLICY),
    ("total_revenue",        "$4,850,000", "$5,240,000"),
    ("gl_each_occurrence",   "$1,000,000", "$3,000,000"),
    ("gl_aggregate",         "$2,000,000", "$3,000,000"),
    ("umbrella_limit",       "$3,000,000", "$1,000,000"),
    ("total_policy_premium", "$10,663.00", "$3,418.00"),
]


def _pdf_text(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def verify(path: str):
    from services.extraction_service import (
        _chunk_by_sections, _effective_chunk_size, _merge_list_fields,
        _LONG_DOC_LIST_KEYS,
    )

    problems = []
    text = _pdf_text(path)
    size = _effective_chunk_size()
    chunks = _chunk_by_sections(text, max_chars=size, overlap_pct=0.15)

    if len(chunks) < 2:
        problems.append(
            f"ONE CHUNK: {len(text):,} chars against a {size:,}-char budget. "
            "`_merge_list_fields` returns a single partial untouched, so "
            "`_merge_rejected` is never written and nothing will show. "
            "Add filler pages.")

    # Everything the LLM sees for a chunk = its carried context prefix + body.
    seen = [(pfx or "") + body for body, _s, _e, pfx in chunks]

    def _where(needle):
        return [i for i, t in enumerate(seen) if needle in t]

    # Markers printed EXACTLY ONCE, inside one block only, so "which chunk is
    # this block in?" has a single answer. Deliberately NOT the policy numbers:
    # the front page's schedule of coverage parts names the umbrella policy
    # number too, which would make the umbrella look present in chunk 0 and
    # pass this check for the wrong reason. The dollar amounts are no good
    # either - they repeat all over a policy copy by design.
    front = _where("SCHEDULE OF HAZARDS")
    back = _where("(Liability Coverage)")
    endt = _where("AMENDATORY ENDORSEMENT")
    audit = _where("PREMIUM AUDIT EXPOSURE STATEMENT")
    if not front or not back:
        problems.append(f"MARKER MISSING: front seen in {front}, umbrella seen in {back}")
    elif set(front) & set(back):
        problems.append(
            f"NOT SEPARATED: front {front} and umbrella {back} share a chunk. "
            "One chunk means one candidate per fact and no rejects. Move the "
            "blocks further apart or add filler between them.")
    if set(front) & (set(endt) | set(audit)):
        problems.append(
            f"NOT SEPARATED: the amendatory endorsement {endt} / audit exposure "
            f"{audit} share a chunk with the front block {front}.")

    # The real merge, driven with facts of exactly the shape this PDF produces.
    partials = [
        {"_chunk_idx": 0, "flags": {},
         "facts": {k: a for k, a, _b in CONFLICTS}},
        {"_chunk_idx": 1, "flags": {},
         "facts": {k: b for k, _a, b in CONFLICTS}},
    ]
    merged = _merge_list_fields(partials, list_keys=list(_LONG_DOC_LIST_KEYS))
    rejected = (merged.get("facts") or {}).get("_merge_rejected") or {}
    if not rejected:
        problems.append(
            "NO _merge_rejected: the real merge did not record a loser for any "
            "of the six conflicts. The fixture's values are no longer "
            "materially different to the merge - pick different figures.")

    return problems, len(text), size, len(chunks), front, back, rejected


README = """# UI-12 live test - "MERGE REJECTED" in the Review data popup

ONE upload. One popup. One phrase that should not be there.

## What you are testing

On the pre-form screen, under **Documents processed**, every document has a
**Review data** button. It opens a popup called "Extracted data".

The first row of that popup currently reads **MERGE REJECTED**, followed by a
wall of unpunctuated text. That is internal bookkeeping - the losing values from
our own merge - printed straight to the user. It is what the client reported.

## Why this document is 27 pages of policy wording

Because the bug only exists on long documents, and that is not padding for its
own sake:

* The private note is only written when ONE document is split into TWO OR MORE
  extraction chunks. Below the split size, nothing is ever rejected.
* The split happens at 56,000 characters of document text.
* So the figures that disagree have to be tens of thousands of characters
  apart, with real policy wording in between.

That is exactly the shape of the file the client hit it on: a complete policy
copy, with the front declarations saying one thing and an umbrella page plus an
amendatory endorsement saying another.

## 1. Upload

Upload `ui12-halloran-package-policy-complete-copy.pdf` as a **NEW package** -
not into an existing session. Extraction is cached per document, so re-using a
session can replay an old extraction and show you nothing.

Extraction on this document takes longer than the small kits: it is a
multi-chunk document by design.

## 2. Reproduce the bug

Stop on the **Review** screen (before form selection). Open **Documents
processed**, then click **Review data** on the document.

**Expected right now (the bug):** the popup's first row is

    MERGE REJECTED
    gl each occurrence: $3,000,000; gl aggregate: $3,000,000; policy number: ...

Screenshot that.

## 3. The control - the feature the client is actually asking for

Still on the Review screen, open **Data Consistency**. There should be a row for
the umbrella limit offering **$3,000,000** and **$1,000,000** as radio buttons
with a Confirm.

That is the same disagreement, expressed the way the client asked for: plain
language, and the user picks. It is fed by the very same internal note.

So the screen is showing the raw ingredient and the finished dish side by side.
Only the raw ingredient has to go.

## 4. After the fix - what must be true

1. **MERGE REJECTED is gone** from the popup. So is any other row whose name
   starts with an underscore.
2. **Everything else in the popup is unchanged** - same real facts, same order,
   same values. Compare against your screenshot from step 2.
3. **Data Consistency still offers the umbrella choice.** If that row
   disappeared, the fix went too deep: the note must still be COMPUTED, just
   not DISPLAYED.
4. **Scores did not move.** Note the Submission Readiness tier and the SQS
   before and after. This is a display change; any movement is a real
   regression.
5. **Generate the forms.** The umbrella limit box must still be held blank
   pending your confirmation, exactly as before.

## What to send back

* The popup screenshot before the fix, and after.
* The Data Consistency section after the fix.
* The score before and after.

## Known and expected

* The document deliberately disagrees with itself in six places. Warnings about
  the umbrella limit, the gross sales figure and the policy number are the
  fixture working, not a defect.
* Which fields end up under MERGE REJECTED varies run to run - the model does
  not have to report every figure from every chunk. One row is enough to test.
* If the popup does NOT show MERGE REJECTED at all on your first run, that is
  the model reading conservatively rather than the bug being absent. Re-upload
  as a new package; the fixture gives it six independent chances.
"""


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = os.path.join(OUT_DIR, PDF_NAME)
    build_pdf(pdf)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w", encoding="utf-8") as f:
        f.write(README)

    problems, nchars, size, nchunks, front, back, rejected = verify(pdf)

    print(f"wrote {pdf}")
    print(f"wrote {os.path.join(OUT_DIR, 'README-HOW-TO-TEST.md')}")
    print()
    print(f"  document text          {nchars:,} chars")
    print(f"  extraction chunk size  {size:,} chars")
    print(f"  chunks                 {nchunks}")
    print(f"  front block (schedule of hazards)  chunk(s) {front}")
    print(f"  umbrella block (liability coverage) chunk(s) {back}")
    print(f"  real merge rejected    {len(rejected)} field(s): {sorted(rejected)}")
    if problems:
        print("\nFIXTURE PROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - multi-chunk, blocks separated, and the real merge writes "
          "_merge_rejected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
