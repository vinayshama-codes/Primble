"""
Regression tests for form-level field QA (Figure 26 client feedback).

Covers the two dimensions the client asked for:
  * Confidence threshold: filled/client_arq -> pass, low_confidence -> review,
    missing_required -> fail.
  * Value vs source: a stamped value that materially differs from its source
    fact -> fail; a formatting-only difference -> pass (no false mismatch).

Run from backend/:
    python tests/test_field_qa.py
or:
    python -m pytest tests/test_field_qa.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.field_qa import (  # noqa: E402
    run_field_qa, _value_matches, to_recommendation_rows,
)


# ── Confidence-threshold verdicts (no source facts -> value check skipped) ────

def _form(confidence, mapped):
    return {"ACORD_125": {"confidence": confidence, "mapped": mapped, "schema": {}}}


def test_missing_required_is_fail():
    gen = _form({"NamedInsured_FullName_A": "missing_required"}, {})
    r = run_field_qa(gen, merged_facts={})
    assert r["fail_count"] == 1
    assert r["ok"] is False
    assert r["results"][0]["reason_code"] == "missing_required"


def test_low_confidence_is_review():
    gen = _form({"Op_Desc_A": "low_confidence"}, {"Op_Desc_A": "some inferred text"})
    r = run_field_qa(gen, merged_facts={})
    assert r["review_count"] == 1
    assert r["fail_count"] == 0
    assert r["ok"] is True  # review does not fail the package
    assert r["results"][0]["reason_code"] == "low_confidence"


def test_filled_and_client_arq_pass_silently():
    gen = _form(
        {"A_A": "filled", "B_A": "client_arq"},
        {"A_A": "deterministic value", "B_A": "confirmed value"},
    )
    r = run_field_qa(gen, merged_facts={})
    assert r["pass_count"] == 2
    assert r["fail_count"] == 0 and r["review_count"] == 0
    assert r["results"] == []  # passes are counted, not listed


def test_optional_empty_field_is_not_a_qa_item():
    # low_confidence + no value = optional blank -> ignored entirely.
    gen = _form({"Opt_A": "low_confidence"}, {})
    r = run_field_qa(gen, merged_facts={})
    assert r["checked"] == 0
    assert r["results"] == []


# ── Value-vs-source comparison (pure helper) ──────────────────────────────────

def test_value_matches_formatting_only_is_not_a_mismatch():
    # Same real-world value in different formats -> matches (no false fail).
    assert _value_matches("effective_date", "07/15/2025", "7/15/25") is True
    assert _value_matches("applicant_name", "Orbin Contracting, LLC", "ORBIN CONTRACTING LLC") is True
    assert _value_matches("mailing_address", "4800 Dahlia St", "4800 DAHLIA STREET") is True


def test_value_matches_material_difference_is_a_mismatch():
    assert _value_matches("effective_date", "07/15/2025", "08/01/2025") is False
    assert _value_matches("applicant_name", "Acme Cleaning LLC", "Orbin Contracting LLC") is False


def test_value_matches_empty_side_is_not_asserted():
    # A blank on either side is "no assertion", never a mismatch.
    assert _value_matches("fein", "", "12-3456789") is True
    assert _value_matches("fein", "12-3456789", None) is True


# ── End-to-end value mismatch through run_field_qa (real fact->field mapping) ──

def test_end_to_end_value_mismatch_flags_fail():
    # applicant_name deterministically stamps into ACORD 125's insured-name
    # field(s). Stamp a value that disagrees with the merged fact -> fail.
    from services.pdf_service import fact_to_form_fields
    mapping = fact_to_form_fields("applicant_name")
    if not mapping:
        # Environment without loadable schemas: the pure helper tests already
        # cover the comparison logic; skip the integration assertion.
        return
    form_id, fields = next(iter(mapping.items()))
    field = fields[0]
    gen = {form_id: {
        "confidence": {field: "filled"},
        "mapped": {field: "Totally Different Company LLC"},
        "schema": {},
    }}
    r = run_field_qa(gen, merged_facts={"applicant_name": "Orbin Contracting LLC"})
    assert r["fail_count"] >= 1
    assert any(x["reason_code"] == "value_mismatch" for x in r["results"])


def test_end_to_end_matching_value_passes():
    from services.pdf_service import fact_to_form_fields
    mapping = fact_to_form_fields("applicant_name")
    if not mapping:
        return
    form_id, fields = next(iter(mapping.items()))
    field = fields[0]
    gen = {form_id: {
        "confidence": {field: "filled"},
        # Formatting-only difference from the fact -> must NOT be a mismatch.
        "mapped": {field: "Orbin Contracting, LLC"},
        "schema": {},
    }}
    r = run_field_qa(gen, merged_facts={"applicant_name": "ORBIN CONTRACTING LLC"})
    assert not any(x["reason_code"] == "value_mismatch" for x in r["results"])


# ── Presentation: findings -> pre-download rows (non-flooding) ────────────────

def test_rows_mismatch_individual_reviews_summarized():
    qa = {"results": [
        {"form_id": "ACORD_125", "field": "Policy_Number_A", "reason_code": "value_mismatch",
         "message": "mismatch msg"},
        {"form_id": "ACORD_125", "field": "X_A", "reason_code": "low_confidence", "message": "r"},
        {"form_id": "ACORD_126", "field": "Y_A", "reason_code": "low_confidence", "message": "r"},
        {"form_id": "ACORD_125", "field": "Z_A", "reason_code": "missing_required", "message": "m"},
    ]}
    rows = to_recommendation_rows(qa)
    # 1 individual mismatch row + 1 summary row (reviews+missing rolled up).
    assert len(rows) == 2
    mismatch = [r for r in rows if r["rec_id"] != "fieldqa_summary"]
    summary = [r for r in rows if r["rec_id"] == "fieldqa_summary"]
    assert len(mismatch) == 1 and mismatch[0]["type"] == "field_qa"
    assert len(summary) == 1
    assert "1 required field" in summary[0]["message"]
    assert "2 AI-inferred field" in summary[0]["message"]


def test_rows_empty_when_all_pass():
    assert to_recommendation_rows({"results": []}) == []
    assert to_recommendation_rows(None) == []


def test_rows_are_all_soft_field_qa_type():
    qa = {"results": [
        {"form_id": "ACORD_125", "field": "A_A", "reason_code": "value_mismatch", "message": "m"},
    ]}
    rows = to_recommendation_rows(qa)
    assert all(r["type"] == "field_qa" for r in rows)  # never hard_stop -> never blocks


# ── High-impact elevation (Figure 33) ─────────────────────────────────────────

def test_high_impact_inferred_field_is_flagged_and_surfaced_individually():
    # An AI-inferred insured/owner field is high-impact: it must be marked and
    # surfaced as its OWN row, not rolled into the generic summary.
    gen = _form({"NamedInsured_FullName_A": "low_confidence"},
                {"NamedInsured_FullName_A": "Some Inferred Name"})
    r = run_field_qa(gen, merged_facts={})
    item = r["results"][0]
    assert item["high_impact"] is True
    rows = to_recommendation_rows(r)
    assert len(rows) == 1
    assert rows[0]["rec_id"] != "fieldqa_summary"
    assert rows[0]["type"] == "field_qa"          # still soft; advisory only


def test_ordinary_inferred_field_stays_in_summary():
    # A non-high-impact inferred field is still summarized (unchanged behavior).
    gen = _form({"Producer_FaxNumber_A": "low_confidence"},
                {"Producer_FaxNumber_A": "555-1234"})
    r = run_field_qa(gen, merged_facts={})
    assert r["results"][0]["high_impact"] is False
    rows = to_recommendation_rows(r)
    assert len(rows) == 1
    assert rows[0]["rec_id"] == "fieldqa_summary"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
