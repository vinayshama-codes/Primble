"""
Regression tests for Core Underwriting Data Consistency (Beta Report §4.3).

Covers the four acceptance criteria for Gross Sales (total_revenue):
  • Extracted and NORMALIZED where present ($1,000,000 == 1000000 == 1,000,000.00).
  • Conflicting values are flagged for review (non-blocking).
  • The source document of each value is visible.
  • A user-confirmed value is applied as producer-verified evidence and clears
    the review.

Run from backend/:
    python tests/test_underwriting_consistency.py
or:
    python -m pytest tests/test_underwriting_consistency.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.underwriting_consistency import (  # noqa: E402
    assess_underwriting_consistency, apply_confirmations, validate_confirmation,
    _normalize_currency, RECONCILABLE_FIELDS, RECONCILABLE_FIELD_KEYS,
)


def _doc(doc_id, filename, doc_type, revenue):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type,
            "facts": {"total_revenue": revenue}}


def test_currency_normalization_collapses_formatting():
    assert _normalize_currency("$1,000,000") == "1000000"
    assert _normalize_currency("1000000") == "1000000"
    assert _normalize_currency("1,000,000.00") == "1000000"
    assert _normalize_currency(" $ 1,000,000.0 ") == "1000000"
    assert _normalize_currency("1200000.50") == "1200000.5"
    assert _normalize_currency("abc") is None
    assert _normalize_currency("") is None


def test_conflict_flagged_with_sources():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", {"value": "1200000", "confidence": "ai_high"}),
    ]
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"})
    assert v["review_required"] is True
    assert v["conflict_count"] == 1
    f = v["fields"][0]
    assert f["fact_key"] == "total_revenue"
    assert f["status"] == "conflict"
    assert len(f["values"]) == 2
    # Source documents are visible per value (§4.3 acceptance: "source ... visible").
    filenames = {s["filename"] for val in f["values"] for s in val["sources"]}
    assert filenames == {"dec.pdf", "app.pdf"}


def test_formatting_difference_is_not_a_conflict():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", "1000000.00"),
    ]
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"})
    assert v["review_required"] is False
    assert v["fields"][0]["status"] == "consistent"


def test_single_value_is_consistent_with_source():
    docs = [_doc("a", "dec.pdf", "dec_page", "$2,500,000")]
    v = assess_underwriting_consistency(docs, {"total_revenue": "2500000"})
    assert v["review_required"] is False
    f = v["fields"][0]
    assert f["status"] == "consistent"
    assert f["values"][0]["sources"][0]["filename"] == "dec.pdf"


def test_absent_field_is_omitted():
    docs = [{"doc_id": "a", "filename": "x.pdf", "doc_type": "dec_page", "facts": {}}]
    v = assess_underwriting_consistency(docs, {})
    assert v["fields"] == []
    assert v["review_required"] is False


def test_confirmation_resolves_and_applies_as_producer_value():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", "1200000"),
    ]
    confirmed = {"total_revenue": validate_confirmation("total_revenue", "$1,000,000")}
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"}, confirmations=confirmed)
    assert v["review_required"] is False
    assert v["fields"][0]["status"] == "confirmed"

    merged = apply_confirmations({"total_revenue": "stale"}, confirmed)
    env = merged["total_revenue"]
    assert env["value"] == "$1,000,000"
    # Producer-verified (full SQS credit) but labelled distinct from source docs.
    assert env["confidence"] == "client_arq"
    assert env["source"] == "user_confirmed"


def test_validate_confirmation_rejects_non_numeric():
    for bad in ("", "abc", None, "$$"):
        try:
            validate_confirmation("total_revenue", bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    try:
        validate_confirmation("not_a_field", "5")
        assert False, "expected ValueError for unknown field"
    except ValueError:
        pass


def test_engine_is_config_driven():
    # Gross Sales is seeded; the engine is keyed off RECONCILABLE_FIELDS so
    # adding similar fields is a config-only change (§4.3 "and similar fields").
    assert "total_revenue" in RECONCILABLE_FIELDS
    assert RECONCILABLE_FIELDS["total_revenue"]["kind"] == "currency"
    assert "total_revenue" in RECONCILABLE_FIELD_KEYS


def _bldg_doc(doc_id, filename, doc_type, value):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type,
            "facts": {"property_building_value": value}}


def test_building_value_conflict_flagged_for_review():
    # Client Property Integrity: building values inconsistent across documents
    # must be flagged for review before forms are generated.
    docs = [
        _bldg_doc("a", "dec.pdf", "dec_page", "$500,000"),
        _bldg_doc("b", "sov.pdf", "sov", "750000"),
    ]
    v = assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    assert v["review_required"] is True
    f = next(x for x in v["fields"] if x["fact_key"] == "property_building_value")
    assert f["status"] == "conflict"
    assert len(f["values"]) == 2


def test_building_value_formatting_difference_is_not_a_conflict():
    docs = [
        _bldg_doc("a", "dec.pdf", "dec_page", "$500,000"),
        _bldg_doc("b", "sov.pdf", "sov", "500000.00"),
    ]
    v = assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    f = next(x for x in v["fields"] if x["fact_key"] == "property_building_value")
    assert f["status"] == "consistent"
    assert v["review_required"] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
