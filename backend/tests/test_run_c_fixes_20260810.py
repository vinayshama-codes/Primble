"""Regression tests for the defects observed on the client's run-C form
(ACORD_125_FILLED_NEW(2).pdf), each replayed with the run's literal values.

1. Coverage PARTS are not lines of business: "UNINSURED MOTORISTS",
   "UNDERINSURED MOTORISTS", "COMPREHENSIVE", "COLLISION" (each printed with a
   premium on the auto dec) must never fill the "Other" LOB rows. A genuine
   odd line still does.
2. Q4 rows carry DISTINCT policy numbers — the run stamped 6C7-40-02---26 on
   every row.
3. Transaction status is owned by the is_renewal fact: RENEW ticked, ISSUE /
   QUOTE / BOUND / dates / times authoritative blanks (the run had ISSUE +
   RENEW both ticked and a stray "12:01 A.M.").
4. A no-address, no-data location entry cannot become a phantom "LOC # 2" row.
5. Producer license / NPN / carrier program fields are non-fillable — the run
   stamped the dec's Agent Number as the state license and a carrier form
   title ("COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM" / "CU0001") as the
   program name/code.
6. Answers returned under near-miss key names are recovered instead of
   discarded (row suffix dropped, case/punctuation changed) — ambiguous keys
   still rejected.
7. A classification code is kept only when its system label sits NEAR the
   value in the document (the run put GL class 91580 in the NAICS box).
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_125() -> dict:
    with open(os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


_RUN_C_LINES = [
    {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "BBC7263-26"},
    {"line": "Business Auto", "premium": "$2,991", "policy_number": "6E7-40-02---26"},
    {"line": "Commercial Inland Marine", "premium": "$300", "policy_number": "6C7-40-02---26"},
    {"line": "Commercial Liability Umbrella", "premium": "$3,418", "policy_number": "6J7-40-02---26"},
    # The auto dec prints premiums beside these COVERAGE PARTS; extraction
    # emitted them as lines and run C stamped all four into the Other rows.
    {"line": "Uninsured Motorists", "premium": "$88", "policy_number": "6E7-40-02---26"},
    {"line": "Underinsured Motorists", "premium": "$66", "policy_number": "6E7-40-02---26"},
    {"line": "Comprehensive", "premium": "$210"},
    {"line": "Collision", "premium": "$95"},
    {"line": "Uninsured and Underinsured Motorists", "premium": "$154"},
]


# ── 1. Coverage parts never become "Other" lines ─────────────────────────────

def test_coverage_parts_never_fill_other_lob_rows():
    from services.pdf_service import _resolve_other_lob_row
    facts = {"coverage_lines": _RUN_C_LINES}
    for row in "ABCDEF":
        got = _resolve_other_lob_row(
            f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{row}", facts)
        assert got is None, f"row {row} filled with {got!r}"
        got_ind = _resolve_other_lob_row(
            f"Policy_LineOfBusiness_OtherIndicator_{row}", facts)
        assert got_ind is None


def test_a_genuine_odd_line_still_fills_row_a_alongside_coverage_parts():
    from services.pdf_service import _resolve_other_lob_row
    facts = {"coverage_lines": _RUN_C_LINES + [
        {"line": "Employment Practices Liability", "premium": "$500",
         "policy_number": "EPL-99-1"},
    ]}
    assert _resolve_other_lob_row(
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A", facts
    ) == "Employment Practices Liability"
    assert _resolve_other_lob_row(
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_B", facts) is None


# ── 2. Q4 rows: one row per distinct policy number ───────────────────────────

def test_q4_rows_dedupe_on_policy_number():
    from services.pdf_service import _resolve_other_policy_cell
    facts = {"coverage_lines": [
        {"line": "Liability", "policy_number": "6C7-40-02---26"},
        {"line": "Automobile", "policy_number": "6C7-40-02---26"},
        {"line": "Umbrella", "policy_number": "6C7-40-02---26"},
        {"line": "General Liability", "policy_number": "BBC7263-26"},
    ]}
    # Row A: first entry. Row B: the FIRST entry with a NEW number.
    assert _resolve_other_policy_cell("OtherPolicy_PolicyNumberIdentifier_A", facts) == "6C7-40-02---26"
    assert _resolve_other_policy_cell("OtherPolicy_PolicyNumberIdentifier_B", facts) == "BBC7263-26"
    assert _resolve_other_policy_cell("OtherPolicy_LineOfBusinessCode_B", facts) == "General Liability"
    # No third distinct number -> row C blank.
    assert _resolve_other_policy_cell("OtherPolicy_PolicyNumberIdentifier_C", facts) is None


# ── 3. Transaction status owned by the renewal fact ──────────────────────────

def test_renewal_owns_the_status_family():
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    mapped, unmatched, det = compute_form_gaps(
        "ACORD_125", schema, {"is_renewal": "yes"})
    assert mapped.get("Policy_Status_RenewIndicator_A") == "Yes"
    for f in ("Policy_Status_IssueIndicator_A", "Policy_Status_QuoteIndicator_A",
              "Policy_Status_BoundIndicator_A", "Policy_Status_EffectiveTime_A",
              "Policy_Status_EffectiveTimeAMIndicator_A"):
        assert mapped.get(f) is None
        assert f not in unmatched, f"{f} still shipped to the LLM"
        assert f in det


def test_unknown_renewal_status_keeps_legacy_path():
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    _m, unmatched, _d = compute_form_gaps("ACORD_125", schema, {})
    assert "Policy_Status_RenewIndicator_A" in unmatched


# ── 4. Phantom location rows ─────────────────────────────────────────────────

def test_no_address_no_data_entry_is_not_a_location():
    from services.extraction_service import _consolidate_property_locations
    facts = {
        "property_locations": [
            {"address": "4800 Dahlia St # D13, Denver, CO 80216-3121",
             "ownership": "tenant"},
            {"address": None},
        ],
    }
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 1


def test_no_address_entry_with_real_data_is_kept():
    from services.extraction_service import _consolidate_property_locations
    facts = {
        "property_locations": [
            {"address": "4800 Dahlia St # D13, Denver, CO 80216-3121"},
            {"address": None, "annual_revenue": "$250,000",
             "full_time_employees": "4"},
        ],
    }
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


# ── 5. Agency-profile / carrier-filing identifiers are non-fillable ──────────

def test_license_npn_and_program_fields_are_nonfillable():
    from services.pdf_service import _is_nonfillable_field
    for f in ("Producer_StateLicenseIdentifier_A",
              "Producer_NationalIdentifier_A",
              "Insurer_ProductDescription_A",
              "Insurer_ProductCode_A"):
        assert _is_nonfillable_field(f), f"{f} is still LLM-fillable"


def test_agent_number_can_no_longer_reach_the_license_box():
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    mapped, unmatched, _det = compute_form_gaps("ACORD_125", schema, {})
    assert "Producer_StateLicenseIdentifier_A" not in unmatched
    assert mapped.get("Producer_StateLicenseIdentifier_A") is None


# ── 6. Near-miss key recovery ────────────────────────────────────────────────

def test_key_recovery_accepts_unambiguous_matches_only():
    from services.pdf_service import _recover_sent_field, _norm_field_key
    sent = ["Producer_FullName_A", "NamedInsured_FullName_A",
            "Vehicle_ModelYear_A", "Vehicle_ModelYear_B"]
    by_norm = {}
    for s in sent:
        by_norm.setdefault(_norm_field_key(s), []).append(s)
    # Dropped row suffix, unique base -> recovered.
    assert _recover_sent_field("Producer_FullName", by_norm) == "Producer_FullName_A"
    # Case/punctuation drift -> recovered.
    assert _recover_sent_field("producer-fullname-a", by_norm) == "Producer_FullName_A"
    # Dropped suffix but TWO candidate rows -> ambiguous -> rejected.
    assert _recover_sent_field("Vehicle_ModelYear", by_norm) is None
    # A genuinely invented name -> rejected.
    assert _recover_sent_field("GL_Limit_EachOccurrence", by_norm) is None


# ── 7. Classification-code label must sit near the value ─────────────────────

def test_gl_class_code_far_from_naics_label_is_dropped():
    from services.pdf_service import _drop_ungrounded_classification_codes
    raw = ("naics based rating may apply per company filing rules. "
           + ("lorem ipsum " * 60)
           + " GL CLASS 91580 CONTRACTORS EXECUTIVE SUPERVISORS")
    mapped = {"NamedInsured_NAICSCode_A": "91580"}
    dropped = _drop_ungrounded_classification_codes(
        mapped, raw, {"NamedInsured_NAICSCode_A"})
    assert "NamedInsured_NAICSCode_A" in dropped
    assert mapped["NamedInsured_NAICSCode_A"] is None


def test_properly_labelled_code_next_to_its_value_is_kept():
    from services.pdf_service import _drop_ungrounded_classification_codes
    raw = "applicant information. NAICS: 238160 roofing contractors."
    mapped = {"NamedInsured_NAICSCode_A": "238160"}
    dropped = _drop_ungrounded_classification_codes(
        mapped, raw, {"NamedInsured_NAICSCode_A"})
    assert not dropped
    assert mapped["NamedInsured_NAICSCode_A"] == "238160"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
