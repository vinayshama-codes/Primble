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

# sqs_recommendation_audit.recommendation_type has a fixed DB CHECK constraint
# (models/schemas.py SQS_RECOMMENDATION_AUDIT_STATEMENTS). Every row this module
# produces MUST use one of these values or the insert silently fails at the DB
# layer (this caught a real bug: 'field_qa' was not in this list).
_ALLOWED_RECOMMENDATION_TYPES = {"hard_stop", "soft_warning", "missing_field", "suggestion"}


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


def test_fillable_empty_field_is_a_not_answered_review():
    # A fillable, non-required field the AI left blank (low_confidence + no value)
    # used to be fully invisible (no pink, no yellow, no QA row). It is now a
    # 'not_answered' advisory review item so a silently-skipped standard question
    # is visible. Never a fail - the package still passes.
    gen = _form({"Opt_A": "low_confidence"}, {})
    r = run_field_qa(gen, merged_facts={})
    assert r["review_count"] == 1
    assert r["fail_count"] == 0
    assert r["ok"] is True
    assert r["results"][0]["reason_code"] == "not_answered"


def test_nonfillable_empty_field_is_still_ignored():
    # A non-fillable field (signature/premium/etc.) is never sent to gap-fill, so
    # its blank is not an AI non-answer and must NOT surface as not_answered.
    gen = _form(
        {"NamedInsured_Signature_A": "low_confidence", "Producer_Premium_A": "low_confidence"},
        {},
    )
    r = run_field_qa(gen, merged_facts={})
    assert r["checked"] == 0
    assert r["results"] == []


def test_not_answered_rolls_into_summary_row():
    # Non-high-impact blanks roll into the single summary row (no per-field flood),
    # and the summary reports the blank count.
    gen = _form({"Q_AAI_A": "low_confidence", "Q_AAJ_A": "low_confidence"}, {})
    r = run_field_qa(gen, merged_facts={})
    rows = to_recommendation_rows(r)
    summary = [x for x in rows if x["rec_id"] == "fieldqa_summary"]
    assert len(summary) == 1
    assert "left blank" in summary[0]["message"]
    # All rows remain DB-constraint-safe.
    assert all(x["type"] in _ALLOWED_RECOMMENDATION_TYPES for x in rows)


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


# ── Address sub-fields (LineOne/City/State/Zip) - regression for a real bug ────
# found during testing: these route through pdf_service's "_addr_*" pseudo-key
# mechanism, not a direct "mailing_address" rule, so naively comparing a stamped
# PIECE (e.g. just the city) against the FULL address fact string would never
# match and would flood the review with false mismatches on every address field
# - exactly the field family the client named first ("address... must be
# exact"). expected_value_for_field() must extract the matching piece.

def test_address_subfield_correct_value_is_not_a_false_mismatch():
    from services.pdf_service import fact_to_form_fields
    mapping = fact_to_form_fields("mailing_address")
    if not mapping:
        return
    form_id, fields = next(iter(mapping.items()))
    city = next((f for f in fields if "CityName" in f), None)
    if not city:
        return
    gen = {form_id: {"confidence": {city: "filled"}, "mapped": {city: "Aurora"}, "schema": {}}}
    r = run_field_qa(gen, merged_facts={
        "mailing_address": "7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245"
    })
    assert not any(x["reason_code"] == "value_mismatch" for x in r["results"])


def test_address_subfield_wrong_value_is_caught():
    from services.pdf_service import fact_to_form_fields
    mapping = fact_to_form_fields("mailing_address")
    if not mapping:
        return
    form_id, fields = next(iter(mapping.items()))
    city = next((f for f in fields if "CityName" in f), None)
    if not city:
        return
    gen = {form_id: {"confidence": {city: "filled"}, "mapped": {city: "Denver"}, "schema": {}}}
    r = run_field_qa(gen, merged_facts={
        "mailing_address": "7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245"
    })
    mismatches = [x for x in r["results"] if x["reason_code"] == "value_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["stamped"] == "Denver" and mismatches[0]["expected"] == "Aurora"


def test_secondary_row_not_compared_to_primary_row_fact():
    # Regression for a real false positive caught in production testing: row B
    # ("Other Named Insured") is a DIFFERENT entity, not a repeat of row A's
    # value. It may legitimately be blank, or independently gap-filled with a
    # different split of the address - comparing it against the SAME
    # mailing_address fact as row A manufactured a false "value disagrees with
    # source" report on every generation.
    from services.pdf_service import fact_to_form_fields
    mapping = fact_to_form_fields("mailing_address")
    if not mapping:
        return
    form_id, fields = next(iter(mapping.items()))
    line1_b = next((f for f in fields if f.endswith("_B") and "LineOne" in f), None)
    if not line1_b:
        # Schema has no row B for this field family in this environment.
        return
    line1_a = line1_b.replace("_B", "_A")
    gen = {form_id: {
        "confidence": {line1_a: "filled", line1_b: "filled"},
        "mapped": {line1_a: "7740 Foundry Ln", line1_b: "7740 Foundry Ln, Ste 310"},
        "schema": {},
    }}
    r = run_field_qa(gen, merged_facts={
        "mailing_address": "7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245"
    })
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
    assert len(mismatch) == 1 and mismatch[0]["type"] in _ALLOWED_RECOMMENDATION_TYPES
    assert len(summary) == 1
    assert "1 required field" in summary[0]["message"]
    assert "2 AI-inferred field" in summary[0]["message"]


def test_rows_empty_when_all_pass():
    assert to_recommendation_rows({"results": []}) == []
    assert to_recommendation_rows(None) == []


def test_rows_use_db_allowed_recommendation_type():
    # Regression: 'field_qa' is NOT an allowed recommendation_type (DB CHECK
    # constraint) - the insert would silently fail. Every row must use one of
    # the allowed values and be identifiable via its "fieldqa_" rec_id prefix.
    qa = {"results": [
        {"form_id": "ACORD_125", "field": "A_A", "reason_code": "value_mismatch", "message": "m"},
        {"form_id": "ACORD_125", "field": "Z_A", "reason_code": "missing_required", "message": "m"},
    ]}
    rows = to_recommendation_rows(qa)
    assert rows and all(r["type"] in _ALLOWED_RECOMMENDATION_TYPES for r in rows)
    assert rows and all(r["type"] != "hard_stop" for r in rows)  # never blocks
    assert all(r["rec_id"].startswith("fieldqa_") for r in rows)


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
    assert rows[0]["type"] in _ALLOWED_RECOMMENDATION_TYPES  # still soft; advisory only


def test_ordinary_inferred_field_stays_in_summary():
    # A non-high-impact inferred field is still summarized (unchanged behavior).
    gen = _form({"Producer_FaxNumber_A": "low_confidence"},
                {"Producer_FaxNumber_A": "555-1234"})
    r = run_field_qa(gen, merged_facts={})
    assert r["results"][0]["high_impact"] is False
    rows = to_recommendation_rows(r)
    assert len(rows) == 1
    assert rows[0]["rec_id"] == "fieldqa_summary"


# ── High-impact repeating-row merging (client feedback 2026-07-15: "mostly
# repeating or mostly similar, can we reduce the count with merging") ─────────
# ACORD 137_CA's repeating schedule slots (Vehicle_NonOwned_StateOrProvinceCode
# _A/_B/.../_AA/_AB/...) previously produced ONE recommendation row PER slot,
# each nearly identical. Rows sharing the same form + underlying field (row
# suffix stripped) + reason now merge into a single row with a count.

def test_high_impact_repeating_rows_merge_into_one():
    qa = {"results": [
        {"form_id": "ACORD_137_CA", "field": f"Vehicle_NonOwned_StateOrProvinceCode_{s}",
         "reason_code": "not_answered", "high_impact": True,
         "message": f"Vehicle NonOwned StateOrProvinceCode {s} on ACORD 137_CA is a high-impact "
                    "question the AI left blank (no value found in the documents). "
                    "Fix: Answer it manually if it applies."}
        for s in ("A", "B", "AA", "AB")
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 1
    assert "4 high-impact repeating rows" in rows[0]["message"]
    assert "left blank" in rows[0]["message"]
    assert rows[0]["type"] == "suggestion"


def test_high_impact_repeating_rows_merge_separately_per_reason_code():
    # A blank slot and an AI-inferred slot for the SAME underlying field must
    # not be merged together - they need different fix instructions.
    qa = {"results": [
        {"form_id": "ACORD_137_CA", "field": "Vehicle_NonOwned_StateOrProvinceCode_A",
         "reason_code": "not_answered", "high_impact": True, "message": "m1"},
        {"form_id": "ACORD_137_CA", "field": "Vehicle_NonOwned_StateOrProvinceCode_B",
         "reason_code": "low_confidence", "high_impact": True, "message": "m2"},
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 2
    assert {r["message"] for r in rows} == {"m1", "m2"}


def test_high_impact_repeating_rows_merge_separately_per_form():
    # The SAME field name on two DIFFERENT forms must stay separate rows.
    qa = {"results": [
        {"form_id": "ACORD_137_CA", "field": "Vehicle_NonOwned_StateOrProvinceCode_A",
         "reason_code": "not_answered", "high_impact": True, "message": "m1"},
        {"form_id": "ACORD_138_CA", "field": "Vehicle_NonOwned_StateOrProvinceCode_A",
         "reason_code": "not_answered", "high_impact": True, "message": "m2"},
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 2
    assert {r["component"] for r in rows} == {"ACORD_137_CA", "ACORD_138_CA"}


def test_single_high_impact_row_keeps_original_message_unmerged():
    # No repeating siblings - behavior for the common case is unchanged.
    qa = {"results": [
        {"form_id": "ACORD_127", "field": "AdditionalInterest_FullName_C",
         "reason_code": "not_answered", "high_impact": True,
         "message": "AdditionalInterest FullName on ACORD 127 is a high-impact question "
                    "the AI left blank (no value found in the documents). "
                    "Fix: Answer it manually if it applies."},
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 1
    assert rows[0]["message"] == qa["results"][0]["message"]
    assert rows[0]["field"] == "AdditionalInterest_FullName_C"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
