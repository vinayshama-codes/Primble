"""Two live-run defects from generation 4 of the client's document.

1. Q4 "other insurance with this company" had its two columns SWAPPED:

       LINE OF BUSINESS              POLICY NUMBER
       Commercial General Liability  6E7-40-02---26   <- the AUTO number
       Commercial Auto Liability     BBC7263          <- the GL number

   The line and the number are two boxes on one row and gap fill filled them
   INDEPENDENTLY, so nothing tied them together. Stamping the pair from a single
   `coverage_lines` entry makes a mismatch structurally impossible.

2. A second premises row that was really the first one rewritten:

       row A: 4800 Dahlia St # D13
       row B: 4800 Dahlia St D13 Denver CO. 80216-3121

   Guard 2 collapses an EXACT duplicate of row A, so a reformatted repeat -
   the same location with the city and ZIP folded in - walked straight past it.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


PACKAGE = {"coverage_lines": [
    {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
    {"line": "Commercial Auto", "policy_number": "6E7-40-02---26"},
    {"line": "Commercial Umbrella", "policy_number": "6J7-40-02---26"},
    {"line": "Commercial Inland Marine"},          # no number - no row
]}


@pytest.mark.parametrize("row,line,number", [
    ("A", "Commercial General Liability", "BBC7263-26"),
    ("B", "Commercial Auto", "6E7-40-02---26"),
    ("C", "Commercial Umbrella", "6J7-40-02---26"),
])
def test_the_line_and_its_own_policy_number_stay_together(row, line, number):
    """THE DEFECT. Each row must carry ONE policy's line and ONE policy's
    number, and they must be the same policy."""
    assert ps._deterministic_map(f"OtherPolicy_LineOfBusinessCode_{row}", PACKAGE) == line
    assert ps._deterministic_map(
        f"OtherPolicy_PolicyNumberIdentifier_{row}", PACKAGE) == number


def test_a_line_with_no_policy_number_takes_no_row():
    """Both columns advance together, so a line that states no number cannot
    shift the pairing of every row beneath it."""
    assert ps._deterministic_map("OtherPolicy_LineOfBusinessCode_D", PACKAGE) is None
    assert ps._deterministic_map("OtherPolicy_PolicyNumberIdentifier_D", PACKAGE) is None


def test_the_grid_is_never_handed_to_gap_fill_when_per_line_data_exists():
    """Otherwise the model refills the row we deliberately left empty - the
    authoritative-blank contract."""
    assert ps._is_authoritative_blank_field(
        "OtherPolicy_PolicyNumberIdentifier_D", PACKAGE)


def test_without_coverage_lines_the_legacy_path_is_untouched():
    """No per-line data means no regression for sessions extracted before it
    existed."""
    assert ps._resolve_other_policy_cell(
        "OtherPolicy_PolicyNumberIdentifier_A", {}) is ps._SCHED_SKIP


def test_malformed_coverage_lines_are_survivable():
    for facts in ({"coverage_lines": "nope"}, {"coverage_lines": [None]},
                  {"coverage_lines": [{}]}):
        assert ps._deterministic_map(
            "OtherPolicy_PolicyNumberIdentifier_A", facts) in (None, "UNMATCHED")


# ── Reformatted duplicate rows ───────────────────────────────────────────────

def test_a_reformatted_repeat_of_row_a_is_removed():
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_LineOne_B":
            "4800 Dahlia St D13 Denver CO. 80216-3121",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_A"] == "4800 Dahlia St # D13"
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_B"] is None


def test_a_genuinely_different_second_location_survives():
    """THE LOAD-BEARING TEST. A real multi-location risk must keep every site."""
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_LineOne_B": "1290 Broadway Suite 400",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_B"] == "1290 Broadway Suite 400"


def test_short_address_lines_are_not_compared():
    """Below 10 characters a containment match is meaningless."""
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "PO Box 12",
        "CommercialStructure_PhysicalAddress_LineOne_B": "PO Box 12",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    # Guard 2's exact-duplicate rule may still act; this guard must not.
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_A"] == "PO Box 12"
