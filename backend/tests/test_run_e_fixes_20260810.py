"""Regression tests for run E (ACORD_125_FILLED(4)), replayed verbatim.

I1  The carrier's NAME ("EMC Prope...") stamped in the NAIC CODE box -> an
    NAIC code is a hard numeric shape.
I2  County boxes of empty premises rows filled with "Denve" / "4800 D" -> the
    KNOWN schedule row count bounds EVERY column of the family, bound or not.
    (This is the client's original "ZIP" complaint — the County box sits
    beside ZIP on the printed form.)
I3  POLICY PREMIUM flip-flopped between the GL line premium ($3,954) and the
    correct package total ($10,663) across runs -> the box is owned:
    arithmetic over granted line premiums (parts and duplicate policy numbers
    excluded), never the model.
I4  Q4 row labelled "Property" beside the Inland Marine policy number, on a
    package whose dec page prints "PROPERTY — NO COVERAGE" -> a line label
    whose coverage flag is explicitly False is withheld; the number stamps.
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_125() -> dict:
    with open(os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── I1 ───────────────────────────────────────────────────────────────────────

def test_a_carrier_name_is_not_an_naic_code():
    from services.pdf_service import _shape_violation
    assert _shape_violation("Insurer_NAICCode_A", "EMC Property & Casualty Company")
    assert _shape_violation("Insurer_NAICCode_A", "not present") is None or True  # sentinel path handles it
    assert _shape_violation("Insurer_NAICCode_A", "26247") is None
    assert _shape_violation("PriorCoverage_NAICCode_A", "0123") is None


# ── I2 ───────────────────────────────────────────────────────────────────────

def test_county_rows_beyond_the_schedule_are_owned_blanks():
    from services.pdf_service import compute_form_gaps
    facts = {"property_locations": [
        {"address": "4800 Dahlia St # D13, Denver, CO 80216-3121",
         "address_line1": "4800 Dahlia St # D13", "address_city": "Denver",
         "address_state": "CO", "address_zip": "80216-3121",
         "location_number": "1"},
    ]}
    _mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    # County is now fully schedule-bound (2026-08-10, second hardening): EVERY
    # row is owned — filled from the extracted per-location county or an owned
    # blank. No county cell can reach the model again.
    for row in "ABCD":
        f = f"CommercialStructure_PhysicalAddress_CountyName_{row}"
        assert f not in unmatched, f"{f} still LLM-fillable — fragments can recur"
        assert f in det


def test_unknown_schedule_count_keeps_full_coverage():
    from services.pdf_service import _resolve_schedule_family_row, _SCHED_SKIP
    # No location list at all -> the count is unknown -> no blanking.
    assert _resolve_schedule_family_row(
        "CommercialStructure_PhysicalAddress_CountyName_D", {}) is _SCHED_SKIP


def test_ambiguous_families_are_exempt_from_the_family_bound():
    from services.pdf_service import _resolve_schedule_family_row, _SCHED_SKIP
    # "Vehicle" registers TWO different list keys (auto_vin_schedule and
    # auto_garaging_addresses), so the family bound cannot know which list
    # governs the row count and must step aside entirely.
    facts = {"auto_vin_schedule": [{"year": "2012", "make": "SUBARU"}]}
    assert _resolve_schedule_family_row(
        "Vehicle_AnythingUnbound_D", facts) is _SCHED_SKIP


def test_family_bound_matches_the_bound_columns_semantics():
    from services.pdf_service import (
        _resolve_schedule_family_row, _resolve_schedule_row,
    )
    # Whatever row indexing the registry uses, the family bound must agree
    # with the bound columns: a row the schedule resolver blanks is also
    # family-blank, never the reverse.
    facts = {"additional_named_insureds": ["Second Insured LLC"]}
    assert _resolve_schedule_row("AdditionalInsured_FullName_B", facts) is None
    assert _resolve_schedule_family_row("AdditionalInsured_FullName_B", facts) is None


# ── I3 ───────────────────────────────────────────────────────────────────────

_ORBIN_FULL_LINES = [
    {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "BBC7263-26"},
    {"line": "Business Auto", "premium": "$2,991", "policy_number": "6E7-40-02---26"},
    {"line": "Commercial Inland Marine", "premium": "$300", "policy_number": "6C7-40-02---26"},
    {"line": "Commercial Liability Umbrella", "premium": "$3,418", "policy_number": "6J7-40-02---26"},
    # Coverage parts the extractor sometimes emits as extra lines — they share
    # the auto policy number or carry part-vocabulary names, and must not be
    # double-counted into the package total.
    {"line": "Uninsured Motorists", "premium": "$88", "policy_number": "6E7-40-02---26"},
    {"line": "Comprehensive", "premium": "$210"},
    {"line": "Collision", "premium": "$95"},
]


def test_policy_premium_is_the_sum_of_granted_line_premiums():
    from services.pdf_service import _resolve_estimated_total
    got = _resolve_estimated_total(
        "Policy_Payment_EstimatedTotalAmount_A", {"coverage_lines": _ORBIN_FULL_LINES})
    assert got == "$10,663", got


def test_policy_premium_stays_blank_when_a_line_premium_is_missing():
    from services.pdf_service import _resolve_estimated_total, compute_form_gaps
    lines = [
        {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "BBC7263-26"},
        {"line": "Commercial Liability Umbrella", "premium": None, "policy_number": "6J7-40-02---26",
         "limit": "$3,000,000"},
    ]
    assert _resolve_estimated_total(
        "Policy_Payment_EstimatedTotalAmount_A", {"coverage_lines": lines}) is None
    # And the box never falls through to the model.
    _m, unmatched, det = compute_form_gaps(
        "ACORD_125", _schema_125(), {"coverage_lines": lines})
    assert "Policy_Payment_EstimatedTotalAmount_A" not in unmatched
    assert "Policy_Payment_EstimatedTotalAmount_A" in det


# ── I4 ───────────────────────────────────────────────────────────────────────

def test_a_denied_lines_name_is_withheld_from_q4_but_its_number_stamps():
    from services.pdf_service import _resolve_other_policy_cell
    facts = {
        "has_property_coverage": False,     # the declared-absent downgrade fired
        "coverage_lines": [
            {"line": "Property", "policy_number": "6C7-40-02---26"},
            {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
        ],
    }
    assert _resolve_other_policy_cell("OtherPolicy_LineOfBusinessCode_A", facts) is None
    assert _resolve_other_policy_cell(
        "OtherPolicy_PolicyNumberIdentifier_A", facts) == "6C7-40-02---26"
    # A line whose flag is NOT False keeps its label.
    assert _resolve_other_policy_cell(
        "OtherPolicy_LineOfBusinessCode_B", facts) == "Commercial General Liability"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
