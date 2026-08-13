"""
Regression tests for schedule-row duplicate detection (Figure 32 client
feedback: "Build driver roster ingestion with ... duplicate detection").

Bug context: extraction_service._merge_list_fields' cross-chunk merge only
ever deduped BYTE-IDENTICAL rows (exact json.dumps equality). The same driver
appearing on two document pages/chunks with a trivial formatting difference
(DL# filled on one page, blank on another; different capitalization) produced
two separate rows instead of one. Fixed via _dedupe_schedule_rows, keyed by
license number (else normalized name+dob), merging gaps rather than dropping
data, wired into both the multi-partial merge loop and the single-partial
fast path. DOB is normalized via normalize_date() (not raw string comparison)
so the same date extracted in two different valid formats still matches.

Run from backend/:
    python -m pytest tests/test_schedule_row_dedup.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.extraction_service import (  # noqa: E402
    _dedupe_schedule_rows,
    _driver_dedup_keys,
    _merge_list_fields,
)


def test_same_license_number_merges_despite_different_casing():
    rows = [
        {"name": "Erin Royal", "dob": None, "license_number": "94-327-1211", "license_state": None},
        {"name": "ERIN ROYAL", "dob": "1985-04-02", "license_number": "943271211", "license_state": "CO"},
    ]
    out = _dedupe_schedule_rows("auto_drivers", rows)
    assert len(out) == 1
    assert out[0]["dob"] == "1985-04-02"          # gap filled from the 2nd row
    assert out[0]["license_state"] == "CO"        # gap filled from the 2nd row
    assert out[0]["name"] == "Erin Royal"          # first-seen value kept, not overwritten


def test_falls_back_to_name_plus_dob_across_different_date_formats():
    # Regression for a live-test finding (2026-07-13): a genuine duplicate
    # (same driver, no license number available to key off) intermittently
    # failed to merge because the model extracted the identical DOB in two
    # different valid formats across the two mentions. The fallback key must
    # normalize DOB (ISO form) rather than compare it as a raw string.
    rows = [
        {"name": "Priya Okafor", "dob": "07/22/1979", "license_number": None, "license_state": "OR"},
        {"name": "Priya Okafor", "dob": "7/22/1979", "license_number": None, "license_state": "OR"},
    ]
    out = _dedupe_schedule_rows("auto_drivers", rows)
    assert len(out) == 1


def test_falls_back_to_name_plus_dob_when_no_license_number():
    rows = [
        {"name": "Madonna", "dob": "1970-01-01", "license_number": None, "license_state": None},
        {"name": "madonna", "dob": "1970-01-01", "license_number": "X123", "license_state": "CA"},
    ]
    out = _dedupe_schedule_rows("auto_drivers", rows)
    assert len(out) == 1
    assert out[0]["license_number"] == "X123"


def test_distinct_drivers_not_merged():
    rows = [
        {"name": "Erin Royal", "dob": None, "license_number": "111-11-1111", "license_state": "CO"},
        {"name": "John Smith", "dob": None, "license_number": "222-22-2222", "license_state": "TX"},
    ]
    out = _dedupe_schedule_rows("auto_drivers", rows)
    assert len(out) == 2


def test_a_row_with_no_natural_identifier_passes_through_unchanged():
    """SUPERSEDES test_unregistered_list_key_passes_through_unchanged.

    That test asserted every schedule but auto_drivers was identity-passthrough.
    That was a description of the code at the time, not an invariant, and it was
    the gap that let the vehicle schedule duplicate a Subaru on the client's
    ACORD 127 (2026-08-12). De-duplication is now generic: any row carrying a
    globally-unique identifier merges on it.

    What must still pass through untouched is a row with NO identifier - merging
    those would delete real data (two identical trucks bought together).
    """
    rows = [{"year": "2020", "make": "FORD"}, {"year": "2020", "make": "FORD"}]
    assert _dedupe_schedule_rows("auto_vin_schedule", rows) == rows
    # ...and an identifier too short to be real is not an identifier.
    junk = [{"serial_number": "N/A"}, {"serial_number": "N/A"}]
    assert _dedupe_schedule_rows("inland_marine_items", junk) == junk


def test_dedup_is_generic_across_schedules_nobody_registered():
    """The point of the generic key: a schedule added later is covered without
    anyone remembering to register it."""
    vehicles = [
        {"year": "2012", "make": "SUBARU", "model": "OUTBACK",
         "vin": "4S4BRCGC9C3217772", "body_type": "SEDAN"},
        {"year": "2012", "make": "SUBARU", "model": "OUTBACK 2.5i SEDAN 4D",
         "vin": "4S4BRCGC9C3217772", "comp_symbol": "07"},
    ]
    merged = _dedupe_schedule_rows("auto_vin_schedule", vehicles)
    assert len(merged) == 1
    # It MERGES rather than discarding - both rows' data survives.
    assert merged[0]["body_type"] == "SEDAN"
    assert merged[0]["comp_symbol"] == "07"

    equipment = [
        {"description": "Excavator", "serial_number": "CAT0320D1234"},
        {"description": "CAT 320D Excavator", "serial_number": "CAT0320D1234",
         "value": "$85,000"},
    ]
    assert len(_dedupe_schedule_rows("inland_marine_items", equipment)) == 1


def test_two_real_items_with_different_identifiers_never_merge():
    trucks = [{"year": "2020", "make": "FORD", "vin": "AAAAAAAAAAAAAAAA1"},
              {"year": "2020", "make": "FORD", "vin": "BBBBBBBBBBBBBBBB2"}]
    assert len(_dedupe_schedule_rows("auto_vin_schedule", trucks)) == 2


def test_policy_number_is_never_a_natural_key():
    """LOAD-BEARING. A policy carries many coverage parts, so merging on its
    number would DELETE real lines. Measured on the client's session:
    BBC7263-26 legitimately carries both Commercial General Liability and
    Employee Benefits Liability."""
    import services.extraction_service as es
    assert "policy_number" not in es._NATURAL_ID_SUBKEYS
    lines = [
        {"line": "Commercial General Liability", "policy_number": "BBC7263-26",
         "premium": "$3,954"},
        {"line": "Employee Benefits Liability", "policy_number": "BBC7263-26",
         "premium": "$75"},
    ]
    assert len(_dedupe_schedule_rows("coverage_lines", lines)) == 2


def test_driver_dedup_keys_includes_both_when_available():
    keys = _driver_dedup_keys({"name": "A", "dob": "2000-01-01", "license_number": "12-3456789"})
    assert "lic:123456789" in keys
    assert "name:a|dob:2000-01-01" in keys


def test_driver_dedup_keys_empty_when_nothing_identifying():
    assert _driver_dedup_keys({"name": "", "license_number": ""}) == []


# ── Integration: the cross-chunk merge path ─────────────────────────────────

def test_merge_list_fields_dedupes_near_duplicate_driver_across_chunks():
    partials = [
        {"facts": {"auto_drivers": [
            {"name": "Erin Royal", "dob": None, "license_number": "94-327-1211", "license_state": None},
        ]}, "_chunk_idx": 0},
        {"facts": {"auto_drivers": [
            {"name": "Erin Royal", "dob": "1985-04-02", "license_number": "943271211", "license_state": "CO"},
        ]}, "_chunk_idx": 1},
    ]
    merged = _merge_list_fields(partials, list_keys=["auto_drivers"])
    drivers = merged["facts"]["auto_drivers"] if "facts" in merged else merged.get("auto_drivers")
    assert len(drivers) == 1
    assert drivers[0]["license_state"] == "CO"


def test_merge_list_fields_single_partial_also_dedupes():
    # The len(partials) == 1 fast path must apply the same dedup, not just the
    # multi-partial branch, so a short single-chunk document isn't a blind spot.
    partials = [
        {"facts": {"auto_drivers": [
            {"name": "Erin Royal", "dob": None, "license_number": "94-327-1211", "license_state": None},
            {"name": "Erin Royal", "dob": "1985-04-02", "license_number": "94-327-1211", "license_state": "CO"},
        ]}},
    ]
    merged = _merge_list_fields(partials, list_keys=["auto_drivers"])
    drivers = merged["facts"]["auto_drivers"]
    assert len(drivers) == 1
    assert drivers[0]["dob"] == "1985-04-02"
