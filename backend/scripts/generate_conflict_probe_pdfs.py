"""
Conflict-detection probe set (2026-08-17).

Purpose: establish EMPIRICALLY which conflicts Primble can currently see, and
where it looks. Written after a code read produced two competing claims about
the same question, which is exactly the situation that needs measurement rather
than more reading.

What the code says (to be confirmed or refuted by these uploads):

  * The Data Consistency picker is built by
    `underwriting_consistency.assess_underwriting_consistency(active_docs, ...)`,
    which groups each scalar fact's value PER DOCUMENT. With one document every
    fact has exactly one group, so it can emit no rows at all.
  * A conflict INSIDE one document is handled somewhere else entirely -
    `extraction_service._flag_intra_document_limit_conflicts`, which reads the
    merge's own rejected candidates. It produces a stamped-value WITHHOLD plus a
    log line; it produces no picker row and no side-by-side values. It is also
    scoped to `_CONFLICT_SENSITIVE_LIMITS = ("umbrella_limit",)` - one fact key.
  * Every conflict that DOES surface becomes a soft stop, and soft stops cap the
    package score at 85 (`sqs_service.SOFT_STOP_CAP`).

Each probe isolates ONE mechanism so a result is diagnostic rather than
suggestive. Predictions are written next to each probe; a prediction that fails
is the finding.

Usage:
    cd backend
    py scripts/generate_conflict_probe_pdfs.py

Outputs into backend/tmp/ :
    PROBE1_self_contradicting.pdf
    PROBE2_dec_package.pdf
    PROBE3_certificate.pdf
    PROBE4_auto_dec_own_term.pdf
    PROBE5_narrative_remarks.pdf
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tmp")
os.makedirs(OUT_DIR, exist_ok=True)

_s = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=_s["Heading1"], alignment=TA_CENTER, fontSize=13, spaceAfter=3)
SUB   = ParagraphStyle("s", parent=_s["Normal"], alignment=TA_CENTER, fontSize=8.5,
                       spaceAfter=10, textColor=colors.HexColor("#555555"))
H2    = ParagraphStyle("h", parent=_s["Heading2"], fontSize=10, spaceBefore=10, spaceAfter=4)
BODY  = ParagraphStyle("b", parent=_s["Normal"], fontSize=9, leading=13)


def _table(rows, widths=None):
    t = Table(rows, colWidths=widths or [2.7 * inch, 3.8 * inch])
    t.setStyle(TableStyle([
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c4")),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _build(filename, title, subtitle, flow):
    path = os.path.join(OUT_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=title)
    story = [Paragraph(title, TITLE), Paragraph(subtitle, SUB)]
    story += flow
    doc.build(story)
    print("  wrote", os.path.relpath(path))


# ─────────────────────────────────────────────────────────────────────────────
# PROBE 1 - ONE document that contradicts itself.
#
# Question: can Primble surface a conflict that lives inside a single upload?
#
# Five self-contradictions across five DIFFERENT fact families, so the answer is
# per-family rather than a single yes/no:
#   umbrella_limit          $3,000,000  vs  $1,000,000   (the ONE key the
#                                                         intra-doc detector covers)
#   gl_aggregate            $2,000,000  vs  $3,000,000
#   total_revenue           $1,500,000  vs  $2,400,000
#   num_employees           47          vs  62
#   applicant_name          ORBIN CONTRACTING LLC vs ORBIN CONTRACTING INC
#
# PREDICTION (from the code read): the umbrella boxes on ACORD 131 ship BLANK and
# a withhold warning appears; the other four merge silently to whichever value
# scored higher, with NO Data Consistency row for any of the five.
# If a Data Consistency row DOES appear for any of them, the code read is wrong
# and I need to find the path that produced it.
# ─────────────────────────────────────────────────────────────────────────────
def probe1():
    flow = [
        Paragraph("SECTION 1 - POLICY DECLARATIONS", H2),
        _table([
            ["Field", "Value"],
            ["Named Insured", "ORBIN CONTRACTING LLC"],
            ["Mailing Address", "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"],
            ["FEIN", "84-2210987"],
            ["Policy Number", "BBC7263-26"],
            ["Policy Effective Date", "07/15/2025"],
            ["Policy Expiration Date", "07/15/2026"],
            ["Carrier", "EMC Property & Casualty Company"],
            ["Business Description", "Commercial roofing and general contracting"],
        ]),
        Spacer(1, 8),
        Paragraph("SECTION 2 - GENERAL LIABILITY LIMITS", H2),
        _table([
            ["Coverage", "Limit"],
            ["Each Occurrence Limit", "$1,000,000"],
            ["General Aggregate Limit", "$2,000,000"],
            ["Products-Completed Operations Aggregate", "$2,000,000"],
            ["Damage to Rented Premises", "$100,000"],
            ["Medical Expense Limit", "$5,000"],
        ]),
        Spacer(1, 8),
        Paragraph("SECTION 3 - COMMERCIAL UMBRELLA", H2),
        _table([
            ["Coverage", "Limit"],
            ["Umbrella Each Occurrence Limit", "$3,000,000"],
            ["Umbrella Aggregate Limit", "$3,000,000"],
            ["Self-Insured Retention", "$0"],
        ]),
        Spacer(1, 8),
        Paragraph("SECTION 4 - EXPOSURE INFORMATION", H2),
        _table([
            ["Exposure", "Amount"],
            ["Annual Gross Sales", "$1,500,000"],
            ["Total Annual Payroll", "$620,000"],
            ["Number of Employees", "47"],
        ]),
        PageBreak(),

        # ---- The contradictions. Same document, later pages. --------------
        Paragraph("SECTION 9 - REVISED SCHEDULE (SUPERSEDING PAGE 1)", H2),
        Paragraph(
            "The following revised figures apply to this policy term. This page "
            "restates coverage and exposure information for the same insured.",
            BODY),
        Spacer(1, 6),
        _table([
            ["Field", "Value"],
            ["Named Insured", "ORBIN CONTRACTING INC"],
            ["General Aggregate Limit", "$3,000,000"],
            ["Umbrella Each Occurrence Limit", "$1,000,000"],
            ["Umbrella Aggregate Limit", "$1,000,000"],
            ["Annual Gross Sales", "$2,400,000"],
            ["Number of Employees", "62"],
        ]),
        Spacer(1, 10),
        Paragraph("SECTION 10 - REMARKS", H2),
        Paragraph(
            "The Commercial Umbrella limit was reduced from $3,000,000 to "
            "$1,000,000 effective 07/25/2025 at the insured's request. All other "
            "terms and conditions remain unchanged.",
            BODY),
    ]
    _build("PROBE1_self_contradicting.pdf",
           "PROBE 1 - SINGLE DOCUMENT, INTERNAL CONTRADICTIONS",
           "One upload. Five facts stated twice with different values.",
           flow)


# ─────────────────────────────────────────────────────────────────────────────
# PROBE 2 - the "dec package" half of the pair. Upload WITH probe 3.
#
# Internally consistent on its own. Carries the FULL printing of every value
# that probe 3 prints in an abbreviated or qualified form, plus a three-policy
# package so the multi-line identity question can be asked.
# ─────────────────────────────────────────────────────────────────────────────
def probe2():
    flow = [
        Paragraph("COMMON POLICY DECLARATIONS", H2),
        _table([
            ["Field", "Value"],
            ["Named Insured", "ORBIN CONTRACTING LLC"],
            ["Mailing Address", "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"],
            ["Physical Address", "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"],
            ["FEIN", "84-2210987"],
            ["Entity Type", "Limited Liability Company"],
            ["Business Description",
             "Commercial roofing contractor performing re-roofing and repair "
             "on commercial structures"],
        ]),
        Spacer(1, 8),
        Paragraph("SCHEDULE OF POLICIES IN THIS PACKAGE", H2),
        _table([
            ["Line of Business", "Policy Number", "Carrier", "Term", "Premium"],
            ["General Liability", "BBC7263-26", "EMC Property & Casualty Company",
             "07/15/2025 to 07/15/2026", "$6,720"],
            ["Commercial Auto", "6E7-40-02---26", "Employers Mutual Casualty Company",
             "07/15/2025 to 07/15/2026", "$2,991"],
            ["Commercial Umbrella", "6J7-40-02---26", "Employers Mutual Casualty Company",
             "07/15/2025 to 07/15/2026", "$952"],
        ], widths=[1.3 * inch, 1.25 * inch, 1.9 * inch, 1.45 * inch, 0.6 * inch]),
        Spacer(1, 8),
        Paragraph("GENERAL LIABILITY COVERAGE PART", H2),
        _table([
            ["Coverage", "Limit"],
            ["Each Occurrence Limit", "$1,000,000"],
            ["General Aggregate Limit", "$2,000,000"],
            ["Products-Completed Operations Aggregate Limit", "$2,000,000"],
            ["Personal & Advertising Injury Limit", "$1,000,000"],
            ["Damage to Rented Premises", "$100,000"],
            ["Coverage Form", "Occurrence"],
            ["Deductible", "$1,000"],
        ]),
        Spacer(1, 8),
        Paragraph("COMMERCIAL UMBRELLA COVERAGE PART", H2),
        _table([
            ["Coverage", "Limit"],
            ["Each Occurrence Limit", "$3,000,000"],
            ["Aggregate Limit", "$3,000,000"],
            ["Self-Insured Retention", "$0"],
        ]),
        Spacer(1, 8),
        Paragraph("EXPOSURE AND RATING INFORMATION", H2),
        _table([
            ["Exposure", "Amount"],
            ["Annual Gross Sales", "$1,500,000"],
            ["Total Annual Payroll", "$620,000"],
            ["Number of Employees", "47"],
            ["Total Policy Premium", "$10,663"],
        ]),
    ]
    _build("PROBE2_dec_package.pdf",
           "PROBE 2 - COMMERCIAL PACKAGE DECLARATIONS",
           "Upload together with PROBE 3. Full printing of every shared value.",
           flow)


# ─────────────────────────────────────────────────────────────────────────────
# PROBE 3 - the certificate half. Upload WITH probe 2.
#
# Every shared value is the SAME UNDERLYING FACT written the way a certificate
# writes it. Exactly one value genuinely differs.
#
#   SHOULD NOT CONFLICT (formatting / qualifier / component):
#     $2,000,000                 vs  $2,000,000 (any one premises)
#     $1,000,000                 vs  $1,000,000 each occurrence
#     $2,000,000                 vs  $2,000,000 products-comp/op agg
#     full street address        vs  Denver, Colorado
#     ORBIN CONTRACTING LLC      vs  Orbin Contracting, L.L.C.
#     three policy numbers on a three-policy account
#
#   SHOULD CONFLICT (real underwriting disagreement, the client praised this one):
#     Umbrella limit $3,000,000  vs  $1,000,000
#
#   SHOULD NOT BE A CHOICE AT ALL (both answers illegal for the field):
#     GL Coverage Form: "BUSINESS AUTO COVERAGE FORM" - names a different line.
#     That field may only ever say Occurrence or Claims-Made.
#
# PREDICTION: today the picker raises SEVEN rows where ONE is legitimate.
# ─────────────────────────────────────────────────────────────────────────────
def probe3():
    flow = [
        Paragraph("CERTIFICATE OF LIABILITY INSURANCE", H2),
        _table([
            ["Field", "Value"],
            ["Insured", "Orbin Contracting, L.L.C."],
            ["Insured Location", "Denver, Colorado"],
            ["Producer", "Front Range Insurance Advisors"],
            ["Insurer A", "EMC Property & Casualty Company"],
            ["Policy Number", "6E7-40-02---26"],
            ["Policy Effective Date", "07/15/2025"],
            ["Policy Expiration Date", "07/15/2026"],
        ]),
        Spacer(1, 8),
        Paragraph("COVERAGES", H2),
        _table([
            ["Coverage", "Limit"],
            ["Each Occurrence Limit", "$1,000,000 each occurrence"],
            ["General Aggregate Limit", "$2,000,000 (any one premises)"],
            ["Products-Completed Operations Aggregate",
             "$2,000,000 products-comp/op agg"],
            ["Damage to Rented Premises", "$100,000 any one fire"],
            ["GL Coverage Form", "BUSINESS AUTO COVERAGE FORM"],
        ]),
        Spacer(1, 8),
        Paragraph("EXCESS / UMBRELLA LIABILITY", H2),
        _table([
            ["Coverage", "Limit"],
            ["Umbrella Each Occurrence Limit", "$1,000,000"],
            ["Umbrella Aggregate Limit", "$1,000,000"],
        ]),
        Spacer(1, 8),
        Paragraph("DESCRIPTION OF OPERATIONS / ADDITIONAL REMARKS", H2),
        Paragraph(
            "The Commercial Umbrella limit under policy 6J7-40-02---26 was "
            "reduced from $3,000,000 to $1,000,000 effective 07/25/2025. "
            "General Liability policy BBC7263-26 remains in force through "
            "07/15/2026 with a general aggregate of $2,000,000 and a total "
            "premium of $6,720. Coverage excludes work performed above three "
            "stories. The certificate holder is included as additional insured "
            "per written contract, with waiver of subrogation where required by "
            "written agreement.",
            BODY),
    ]
    _build("PROBE3_certificate.pdf",
           "PROBE 3 - CERTIFICATE OF LIABILITY INSURANCE",
           "Upload together with PROBE 2. Same facts, certificate formatting. "
           "One genuine difference: the umbrella limit.",
           flow)


# ─────────────────────────────────────────────────────────────────────────────
# PROBE 4 (extra) - the hidden hard stop. Upload WITH probe 2.
#
# A second carrier document for the AUTO policy alone, with its OWN term
# (09/01/2025 - 09/01/2026) and its own carrier. Nothing here disagrees with
# probe 2 - a three-policy account genuinely has three terms.
#
# PREDICTION: effective_date and expiration_date raise a conflict, and because
# both are in HARD_STOP_RECONCILABLE_KEYS the package score is capped at 60 for
# an account where nothing is actually wrong. This has never been reported by
# the client only because their policies happen to share a term. Confirming it
# here is the point.
# ─────────────────────────────────────────────────────────────────────────────
def probe4():
    flow = [
        Paragraph("BUSINESS AUTO DECLARATIONS", H2),
        _table([
            ["Field", "Value"],
            ["Named Insured", "ORBIN CONTRACTING LLC"],
            ["Mailing Address", "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"],
            ["Policy Number", "6E7-40-02---26"],
            ["Carrier", "Employers Mutual Casualty Company"],
            ["Policy Effective Date", "09/01/2025"],
            ["Policy Expiration Date", "09/01/2026"],
            ["Liability Limit", "$1,000,000"],
            ["Comprehensive Deductible", "$1,000"],
            ["Collision Deductible", "$1,000"],
            ["Total Premium", "$2,991"],
        ]),
        Spacer(1, 8),
        Paragraph("SCHEDULE OF COVERED AUTOS", H2),
        _table([
            ["Year", "Make", "Model", "VIN", "Cost New"],
            ["2012", "Subaru", "Forester", "4S4BRCGC9C3217772", "$26,680"],
        ], widths=[0.7 * inch, 1.1 * inch, 1.1 * inch, 2.4 * inch, 1.2 * inch]),
    ]
    _build("PROBE4_auto_dec_own_term.pdf",
           "PROBE 4 - BUSINESS AUTO DECLARATIONS (OWN TERM)",
           "Upload together with PROBE 2. Different policy, different term - "
           "correct, not a disagreement.",
           flow)


# ─────────────────────────────────────────────────────────────────────────────
# PROBE 5 (extra) - the paragraph. Upload WITH probe 2.
#
# A narrative document whose remarks paragraph is entirely different prose from
# probe 2's, and which contains numbers, dates and policy references inside it.
#
# PREDICTION: additional_remarks_text raises a conflict asking the producer to
# choose which paragraph is correct - a question with no answer, because both
# are true and remarks accumulate rather than compete.
# ─────────────────────────────────────────────────────────────────────────────
def probe5():
    flow = [
        Paragraph("ACORD 101 - ADDITIONAL REMARKS SCHEDULE", H2),
        _table([
            ["Field", "Value"],
            ["Named Insured", "ORBIN CONTRACTING LLC"],
            ["Policy Number", "BBC7263-26"],
        ]),
        Spacer(1, 10),
        Paragraph("REMARKS", H2),
        Paragraph(
            "Loss history: the insured reports two claims in the prior five "
            "years. A water damage claim dated 03/14/2023 was paid at $18,400 "
            "and is closed. A vehicle collision claim dated 11/02/2024 remains "
            "open with $42,000 incurred and $12,500 paid to date. "
            "Coverage notes: General Liability policy BBC7263-26 carries a "
            "$1,000 deductible and a general aggregate of $2,000,000. The "
            "Commercial Umbrella under policy 6J7-40-02---26 attaches above the "
            "underlying General Liability and Business Auto limits. Excluded "
            "operations include any work performed above three stories and any "
            "demolition of structures over two stories. The insured confirms no "
            "subsidiaries and no foreign operations.",
            BODY),
        Spacer(1, 8),
        Paragraph(
            "The certificate holder is included as additional insured on a "
            "primary and non-contributory basis where required by written "
            "contract. Waiver of subrogation applies in favor of the certificate "
            "holder where required by written contract.",
            BODY),
    ]
    _build("PROBE5_narrative_remarks.pdf",
           "PROBE 5 - ADDITIONAL REMARKS NARRATIVE",
           "Upload together with PROBE 2. A paragraph is not a competing value.",
           flow)


if __name__ == "__main__":
    print("Generating conflict probes into backend/tmp/ ...")
    probe1()
    probe2()
    probe3()
    probe4()
    probe5()
    print("\nUpload plan:")
    print("  RUN A : PROBE1 alone                -> intra-document detection")
    print("  RUN B : PROBE2 + PROBE3 together    -> false vs real cross-doc conflicts")
    print("  RUN C : PROBE2 + PROBE4 together    -> multi-policy identity / date hard stop")
    print("  RUN D : PROBE2 + PROBE5 together    -> narrative paragraph as a value")
