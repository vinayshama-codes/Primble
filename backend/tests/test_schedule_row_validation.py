"""
Regression tests for schedule-row validation (Figure 32 client feedback:
"Build driver roster ingestion with validation ...").

Bug context: FACT_REGISTRY's ``validate`` only ever checked a single SCALAR
value; nothing validated the ROWS inside a list fact (auto_drivers, etc.), so
a driver row missing its name/license number, or carrying an unparseable DOB,
passed through silently. Fixed via fact_registry.SCHEDULE_ROW_RULES +
validate_schedule_rows(), wired into the existing advisory field_qa pipeline
(services/field_qa.py) so issues surface in the pre-download review with no
new UI - the same mechanism value_mismatch/missing_required already use.

Run from backend/:
    python -m pytest tests/test_schedule_row_validation.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.fact_registry import validate_schedule_rows  # noqa: E402
from services.field_qa import run_field_qa, to_recommendation_rows  # noqa: E402


# ── fact_registry.validate_schedule_rows ─────────────────────────────────────

def test_valid_row_produces_no_issues():
    rows = [{"name": "Erin Royal", "dob": "1985-04-02", "license_number": "94-327-1211",
             "license_state": "CO", "hire_date": "2020-01-01",
             "experience_years": "12", "vehicle_use_percent": "50"}]
    assert validate_schedule_rows("auto_drivers", rows) == []


def test_missing_required_name_flagged():
    rows = [{"name": "", "dob": None, "license_number": "94-327-1211", "license_state": "CO"}]
    issues = validate_schedule_rows("auto_drivers", rows)
    assert any(i["sub_key"] == "name" and i["issue"] == "missing" for i in issues)


def test_missing_required_license_number_flagged():
    rows = [{"name": "Erin Royal", "dob": "1985-04-02", "license_number": None, "license_state": "CO"}]
    issues = validate_schedule_rows("auto_drivers", rows)
    assert any(i["sub_key"] == "license_number" and i["issue"] == "missing" for i in issues)


def test_invalid_dob_format_flagged_as_review_not_missing():
    rows = [{"name": "Erin Royal", "dob": "not-a-date", "license_number": "94-327-1211"}]
    issues = validate_schedule_rows("auto_drivers", rows)
    assert any(i["sub_key"] == "dob" and i["issue"] == "invalid" for i in issues)


def test_optional_sub_keys_never_flagged_missing():
    # license_state / hire_date / experience_years / vehicle_use_percent are
    # all optional - a row lacking them must not produce a "missing" issue.
    rows = [{"name": "Erin Royal", "dob": None, "license_number": "94-327-1211"}]
    issues = validate_schedule_rows("auto_drivers", rows)
    assert not any(i["issue"] == "missing" and i["sub_key"] != "license_number" for i in issues)


def test_unregistered_list_key_returns_no_issues():
    assert validate_schedule_rows("auto_vin_schedule", [{"vin": None}]) == []


def test_non_list_input_returns_no_issues():
    assert validate_schedule_rows("auto_drivers", None) == []
    assert validate_schedule_rows("auto_drivers", "not a list") == []


# ── field_qa integration ─────────────────────────────────────────────────────

def test_run_field_qa_surfaces_missing_and_invalid_driver_rows():
    merged_facts = {
        "auto_drivers": [
            {"name": "Erin Royal", "dob": "1985-04-02", "license_number": None, "license_state": "CO"},
            {"name": "John Smith", "dob": "garbage", "license_number": "555-11-2222", "license_state": "TX"},
        ]
    }
    generated_forms = {"ACORD_127": {"field_state": {}, "confidence": {}}}
    result = run_field_qa(generated_forms, merged_facts, confirmations={})

    codes = {r["reason_code"] for r in result["results"]}
    assert "schedule_row_missing" in codes
    assert "schedule_row_invalid" in codes
    assert result["fail_count"] >= 1
    assert result["review_count"] >= 1

    rec_rows = to_recommendation_rows(result)
    rec_codes = {r["rec_id"] for r in rec_rows}
    assert any("schedule_row_missing" in rid or "schedule_row_invalid" in rid for rid in rec_codes) or \
        any(r["type"] == "suggestion" for r in rec_rows)


def test_schedule_qa_silent_when_owning_form_not_generated():
    # auto_drivers only feeds ACORD_127 (FACT_REGISTRY["auto_drivers"]["forms"]).
    # If ACORD_127 wasn't generated this run, driver-row issues must not appear -
    # a producer who didn't select Business Auto shouldn't see auto QA noise.
    merged_facts = {
        "auto_drivers": [
            {"name": "Erin Royal", "dob": "1985-04-02", "license_number": None, "license_state": "CO"},
        ]
    }
    generated_forms = {"ACORD_140": {"field_state": {}, "confidence": {}}}
    result = run_field_qa(generated_forms, merged_facts, confirmations={})
    codes = {r["reason_code"] for r in result["results"]}
    assert "schedule_row_missing" not in codes
    assert "schedule_row_invalid" not in codes
