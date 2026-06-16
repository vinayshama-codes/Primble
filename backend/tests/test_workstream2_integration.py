"""
Workstream 2 INTEGRATION tests (Beta Report §5.1 / §5.2).

Unlike tests/test_normalization.py (which unit-tests the normalization library on
PLAIN values), this file drives the THREE real cross-document/cross-form
detectors with facts shaped exactly as the live pipeline stores them — i.e. each
value wrapped in the {value, confidence, source} envelope produced by
_annotate_facts. That envelope was the thing silently defeating normalization in
production, so testing with it is what actually proves the acceptance criteria.

Detectors exercised:
  • sqs_service.check_doc_consistency        (name/date/entity/address/FEIN/LOB)
  • extraction_service.detect_source_conflicts (generic field-level + carrier)
  • cross_form_validator.run_cross_form_validation (umbrella date alignment)

Run from backend/:
    python tests/test_workstream2_integration.py
or:
    python -m pytest tests/test_workstream2_integration.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sqs_service import check_doc_consistency                       # noqa: E402
from services.extraction_service import detect_source_conflicts              # noqa: E402
from services.cross_form_validator import (                                  # noqa: E402
    run_cross_form_validation, split_cross_form_issues,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def env(value, conf="ai_high"):
    """Wrap a value the way the live extraction pipeline stores facts."""
    return {"value": value, "confidence": conf, "source": "ai"}


def doc(facts, doc_type="dec_page", name=None):
    return {"facts": facts, "doc_type": doc_type, "filename": name or f"{doc_type}.pdf"}


def _hard(issues):
    return [i for i in issues if "hard_stop" in i]


def _blocking(issues):
    """Issues that actually gate the submission — hard stops and warnings.
    Equivalent-but-reformatted values are allowed to emit an [info] notice
    (§5.1 "raw values remain visible"); only [hard_stop]/[warning] count."""
    return [i for i in issues if i.startswith("[hard_stop]") or i.startswith("[warning]")]


# ── §5.1 / §5.2 — equivalent NAMES do not hard stop (enveloped) ───────────────

def test_equivalent_names_no_hard_stop():
    docs = [
        doc({"applicant_name": env("ORBIN CONTRACTING LLC")}),
        doc({"applicant_name": env("Orbin Contracting, LLC", "ai_low")}, "certificate"),
    ]
    assert _hard(check_doc_consistency(docs)) == []


def test_genuinely_different_names_still_hard_stop():
    docs = [
        doc({"applicant_name": env("Orbin Contracting LLC")}),
        doc({"applicant_name": env("Wake County Government")}, "narrative"),
    ]
    assert any("name_conflict" in i and "hard_stop" in i for i in check_doc_consistency(docs))


# ── §5.2 — equivalent DATES do not hard stop, cross-DOCUMENT (enveloped) ───────

def test_equivalent_dates_cross_document_no_hard_stop():
    docs = [
        doc({"effective_date": env("07/15/25")}),
        doc({"effective_date": env("7/15/2025", "ai_low")}, "certificate"),
    ]
    assert _hard(check_doc_consistency(docs)) == []


def test_different_dates_cross_document_hard_stop():
    docs = [
        doc({"effective_date": env("07/15/2025")}),
        doc({"effective_date": env("08/01/2025")}, "certificate"),
    ]
    assert any("date_conflict" in i and "hard_stop" in i for i in check_doc_consistency(docs))


# ── §5.2 — equivalent DATES do not hard stop, cross-FORM umbrella (the bug) ────

def test_equivalent_umbrella_dates_no_hard_stop():
    facts = {
        "umbrella_effective_date":  env("07/15/2025"), "effective_date":  env("7/15/2025"),
        "umbrella_expiration_date": env("07/15/2026"), "expiration_date": env("7/15/2026"),
    }
    issues = run_cross_form_validation(facts, {"has_umbrella": True},
                                       {"ACORD_125", "ACORD_126", "ACORD_131"})
    hard, _, _ = split_cross_form_issues(issues)
    assert hard == [], hard


def test_misaligned_umbrella_dates_still_hard_stop():
    facts = {
        "umbrella_effective_date": env("07/15/2025"), "effective_date": env("01/01/2025"),
    }
    issues = run_cross_form_validation(facts, {"has_umbrella": True},
                                       {"ACORD_125", "ACORD_126", "ACORD_131"})
    hard, _, _ = split_cross_form_issues(issues)
    assert any("does not match" in h.lower() for h in hard), hard


# ── §5.2 — equivalent ENTITY TYPE / ADDRESS do not warn (enveloped) ───────────

def test_equivalent_entity_type_no_warning():
    docs = [
        doc({"entity_type": env("LLC")}),
        doc({"entity_type": env("Limited Liability Company", "ai_low")}, "application"),
    ]
    assert not any("entity_type" in i for i in _blocking(check_doc_consistency(docs)))


def test_equivalent_address_no_warning():
    docs = [
        doc({"mailing_address": env("4800 DAHLIA ST #D13")}),
        doc({"mailing_address": env("4800 Dahlia Street D13", "ai_low")}, "certificate"),
    ]
    assert not any("mailing_address" in i for i in _blocking(check_doc_consistency(docs)))


# ── §5.2 — equivalent INSURANCE TERMS: CGL == Commercial General Liability ─────

def test_lines_of_business_terminology_equivalent_no_warning():
    docs = [
        doc({"lines_of_business": env(["CGL", "Auto"])}),
        doc({"lines_of_business": env(["Commercial General Liability", "Auto"], "ai_low")},
            "application"),
    ]
    assert not any("lines_of_business" in i for i in check_doc_consistency(docs))


def test_lines_of_business_genuinely_different_warns():
    docs = [
        doc({"lines_of_business": env(["General Liability"])}),
        doc({"lines_of_business": env(["Property"])}, "application"),
    ]
    assert any("lines_of_business" in i for i in check_doc_consistency(docs))


# ── §5.2 — CSL == Combined Single Limit on a generic field (enveloped) ─────────

def test_detect_source_conflicts_insurance_term_equivalent():
    docs = [
        doc({"coverage_basis": env("CSL")}),
        doc({"coverage_basis": env("Combined Single Limit", "ai_low")}, "certificate"),
    ]
    assert detect_source_conflicts(docs) == []


def test_detect_source_conflicts_currency_formatting_equivalent():
    docs = [
        doc({"gl_each_occurrence": env("$1,000,000")}),
        doc({"gl_each_occurrence": env("1000000", "ai_low")}, "certificate"),
    ]
    assert detect_source_conflicts(docs) == []


def test_detect_source_conflicts_same_value_diff_confidence_no_false_positive():
    # The exact production false-positive: identical value, different confidence.
    docs = [
        doc({"policy_form": env("Occurrence", "ai_high")}),
        doc({"policy_form": env("Occurrence", "ai_low")}, "certificate"),
    ]
    assert detect_source_conflicts(docs) == []


# ── §5.2 — Carrier alias: collapse known, REVIEW (not hard) when uncertain ─────

def test_carrier_alias_collapses_no_conflict():
    docs = [
        doc({"carrier_name": env("Employers Mutual Casualty Company")}),
        doc({"carrier_name": env("EMC Property & Casualty Company", "ai_low")}, "certificate"),
    ]
    assert detect_source_conflicts(docs) == []


def test_carrier_unknown_difference_flagged_for_review_not_hard():
    docs = [
        doc({"carrier_name": env("Travelers Indemnity")}),
        doc({"carrier_name": env("The Hartford")}, "certificate"),
    ]
    conflicts = detect_source_conflicts(docs)
    assert len(conflicts) == 1
    assert "review" in conflicts[0].lower()
    assert "hard" not in conflicts[0].lower()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
