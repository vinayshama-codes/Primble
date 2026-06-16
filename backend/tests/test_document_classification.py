"""
Regression tests for Document Classification (Beta Report §4.2).

Covers:
  • Expanded taxonomy + content keyword classification.
  • Narrative detection rules (the Beta Test 1/2 "Unknown narrative" bug).
  • Loss-run recognition from claim tables (no literal "loss run" header).
  • Filename signals as SUPPORTING (not overriding) evidence.
  • Structured docs (dec page / application) are never demoted to narrative.
  • Manual-reclassification taxonomy is well-formed.
  • Classification → SQS connection (narrative quality + loss-history floors).

Run from backend/:
    python tests/test_document_classification.py
or:
    python -m pytest tests/test_document_classification.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.extraction_service import (  # noqa: E402
    classify_document, identify_doc_type, narrative_signal_categories,
    ALLOWED_DOC_TYPES, DOC_TYPE_LABELS,
)
from services import sqs_service as sq  # noqa: E402


# ── Sample documents ──────────────────────────────────────────────────────────

UNDERWRITING_NARRATIVE = """Underwriting Narrative
Account Overview: Wake County Government Entity has been in business since 1868.
Operations: the county provides public services across many departments.
Management experience is extensive with seasoned leadership.
Risk controls and written safety procedures are in place.
Loss history: favorable loss experience with no prior losses.
Coverage discussion: general liability and umbrella limits are requested.
Prior carrier was XYZ Insurance; this is a renewal."""

NARRATIVE_NO_KEYWORD = """Orbin Contracting is a general contractor founded in 2003.
The company performs commercial construction operations across Colorado.
Ownership has over 20 years of construction experience. The firm maintains a
written safety program and employee handbook. There have been no losses in the
past 5 years. Current carrier is EMC and the account is up for renewal.
Coverage requested includes general liability, auto, and workers compensation."""

LOSS_RUN = """Workers Compensation Loss Run Report  Company ABC
Claim Number   Date of Loss   Claimant     Paid      Reserve   Incurred  Status
WC-001         03/14/2022     J. Smith     5,000     2,000     7,000     Open
WC-002         07/01/2021     A. Jones     1,200     0         1,200     Closed"""

LOSS_RUN_NO_HEADER = """Claim Number   Date of Loss   Claimant   Paid Losses   Reserve   Incurred
100023  01/02/2023  Doe   12,500   3,000   15,500
100024  05/11/2023  Roe    4,000   1,000    5,000"""

DEC_PAGE = """COMMERCIAL PACKAGE POLICY DECLARATIONS PAGE
Named Insured: Womens Bar Association   Policy Number: CPP123456
Policy Period: 01/01/2025 to 01/01/2026
This declarations page describes coverage and limits of liability for general
liability across these locations. Operations: professional association."""

CERTIFICATE = """CERTIFICATE OF LIABILITY INSURANCE  ACORD 25
This is to certify that the policies of insurance listed below have been issued.
Certificate Holder: ABC Corp"""

REAL_SAFETY_MANUAL = """SAFETY MANUAL
Written safety procedures and risk control program. All employees shall wear PPE.
Lockout tagout procedures. Hazard communication. Injury and illness prevention
program. Training requirements for new hires. Fall protection procedures."""

PAYROLL = """Payroll Report - Payroll by class code
Class Code 5403  Carpentry  Payroll 450000
Class Code 8810  Clerical   Payroll 90000"""

EMOD = """Experience Modification Worksheet  NCCI
Experience Modification Factor: 0.92  Expected Losses 50000"""


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_narrative_with_explicit_keyword():
    r = classify_document(UNDERWRITING_NARRATIVE)
    assert r["doc_type"] == "narrative", r
    assert r["doc_type"] != "unknown"


def test_narrative_without_keyword_is_not_unknown():
    # The core Beta Test bug: a narrative with NO "narrative" header must not be Unknown.
    r = classify_document(NARRATIVE_NO_KEYWORD)
    assert r["doc_type"] == "narrative", r
    assert len(narrative_signal_categories(NARRATIVE_NO_KEYWORD)) >= 4


def test_loss_run_recognized():
    assert classify_document(LOSS_RUN)["doc_type"] == "loss_run"


def test_loss_run_from_claim_table_without_header():
    # Claim table present but no literal "loss run" phrase → still loss_run.
    assert classify_document(LOSS_RUN_NO_HEADER)["doc_type"] == "loss_run"


def test_dec_page_not_demoted_to_narrative():
    r = classify_document(DEC_PAGE)
    assert r["doc_type"] == "dec_page", r


def test_certificate_recognized():
    assert classify_document(CERTIFICATE)["doc_type"] == "certificate"


def test_real_safety_manual_recognized():
    # A genuine safety manual (few narrative categories) stays safety_manual.
    r = classify_document(REAL_SAFETY_MANUAL)
    assert r["doc_type"] == "safety_manual", r


def test_payroll_and_emod_recognized():
    assert classify_document(PAYROLL)["doc_type"] == "payroll_report"
    assert classify_document(EMOD)["doc_type"] == "emod_worksheet"


def test_filename_supports_classification():
    # A short prose doc that wouldn't classify on content alone gets help from
    # a filename signal — but at LOW confidence (supporting, not authoritative).
    weak = "Please find attached the requested document for your review."
    r = classify_document(weak, filename="Submission Narrative - Orbin.pdf")
    assert r["doc_type"] == "narrative", r
    assert r["confidence"] == "low"
    assert r["source"] == "filename"


def test_filename_does_not_override_strong_content():
    # Filename says "loss run" but content is clearly a dec page → content wins.
    r = classify_document(DEC_PAGE, filename="loss_run_2024.pdf")
    assert r["doc_type"] == "dec_page", r


def test_filename_corroborates_supporting_type_no_narrative_flip():
    # Narrative-ish prose but the filename says Safety Manual → keep safety_manual.
    txt = ("Written safety program and risk control program with operations described, "
           "employee training, hiring and onboarding practices, years in business, "
           "management experience, coverage, and current carrier renewal.")
    r = classify_document(txt, filename="Safety_Manual.pdf")
    assert r["doc_type"] == "safety_manual", r


def test_identify_doc_type_wrapper_returns_string():
    assert identify_doc_type(LOSS_RUN) == "loss_run"
    assert isinstance(identify_doc_type(DEC_PAGE), str)


def test_taxonomy_well_formed():
    assert "unknown" in ALLOWED_DOC_TYPES
    assert ALLOWED_DOC_TYPES[-1] == "unknown"  # unknown is always last
    assert "narrative" in ALLOWED_DOC_TYPES
    assert "loss_run" in ALLOWED_DOC_TYPES
    # Every allowed type has a human label.
    for t in ALLOWED_DOC_TYPES:
        assert t in DOC_TYPE_LABELS and DOC_TYPE_LABELS[t]


def test_unknown_when_no_signal():
    assert classify_document("zzzz qqqq 12345 lorem ipsum")["doc_type"] == "unknown"


# ── Classification → SQS connection (Beta Report §4.2 acceptance) ─────────────

def test_narrative_presence_floors_narrative_quality():
    # §6.3: now returns (score, component_breakdown).
    score, components = sq._calculate_narrative_quality({})
    assert score == 0
    assert isinstance(components, dict) and components and not any(components.values())
    floored, _ = sq._calculate_narrative_quality({}, has_narrative_doc=True)
    assert floored >= 40


def test_loss_run_presence_floors_loss_history():
    base, _ = sq.calculate_p4_loss_history({}, {})
    # Use fresh loss runs (age_days=30) so the L6 recency adjustment doesn't
    # apply — the test is verifying the doc-presence floor exists, not recency.
    floored, recs = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "30"}, {}, has_loss_run_doc=True
    )
    assert base == 25  # No-info tier updated from 10 to 25 (client V1 approval)
    # Loss-run presence floors above the no-info baseline. No prior carrier in this
    # fixture applies the client's -10, so the floor is 40 (50 doc credit - 10).
    assert floored >= 40
    assert floored > base
    assert any("uploaded" in r.lower() for r in recs)


def test_attested_no_losses_credited():
    score, _ = sq.calculate_p4_loss_history({}, {"no_prior_losses": True})
    assert score >= 50


def test_present_doc_types_skips_excluded():
    sd = {"docs": [
        {"doc_type": "narrative"},
        {"doc_type": "loss_run", "excluded": True},
    ]}
    present = sq._present_doc_types(sd)
    assert "narrative" in present
    assert "loss_run" not in present  # excluded docs do not credit scoring


# ── Runner ────────────────────────────────────────────────────────────────────

def _run_all():
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {name} — {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
