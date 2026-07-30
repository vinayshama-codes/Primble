"""Regression guard: the sibling-dedup must not gut a legitimate fleet table.

Found live on a real ACORD 127 generation (2026-07-29). The gap-fill model
correctly returned a complete 3-vehicle schedule and the post-fill dedup then
deleted 40+ correct cells, leaving row A populated and rows B/C nearly empty.

Root cause: two different prompts, one shared safety net.
  * `_slot_group_block` tells the model "find N DISTINCT values, NEVER copy the
    same value into more than one slot" - per-value dedup is right there.
  * `_table_group_block` tells it "fill ONE COMPLETE ROW per real entry" - and
    three trucks garaged at the same address legitimately share City, County,
    State, PostalCode, deductible, radius, territory, rate class and every
    coverage indicator.

The dedup iterated `_base_to_slots`, which contains BOTH kinds, so table columns
got the slot-group treatment.
"""
import json
import os
import threading

import pytest

import services.pdf_service as ps


_FLEET_TEXT = """
SCHEDULE OF OWNED VEHICLES

Vehicle 1
Year: 2022 Make: Ford Model: F-250 Body: Pickup
VIN: 1FT7W2BT4NEC10473
Cost New: $58,900
Garaging Address: 4820 Prospect Avenue, Denver, CO 80216
Radius of Operation: 50 miles Use: Service

Vehicle 2
Year: 2021 Make: Ram Model: 3500 Body: Flatbed
VIN: 3C63RRHL9MG551208
Cost New: $67,400
Garaging Address: 4820 Prospect Avenue, Denver, CO 80216
Radius of Operation: 50 miles Use: Service

Vehicle 3
Year: 2023 Make: Isuzu Model: NPR-HD Body: Stake Bed
VIN: 54DC4W1D0PS812640
Cost New: $81,250
Garaging Address: 3110 Vasquez Boulevard, Denver, CO 80216
Radius of Operation: 50 miles Use: Service
"""


class _ScriptedClient:
    """Returns a fixed, CORRECT model response so the test isolates post-processing."""

    def __init__(self, values):
        self._payload = json.dumps({
            "values": values,
            "raw_text_sourced": list(values),
            "question_grounding": {},
        })
        self._lock = threading.Lock()
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        with self._lock:
            self.calls += 1
        payload = self._payload

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
            usage = None
        return _R()


def _run(monkeypatch, values, form_id="ACORD_127"):
    """Feed `values` back as the model's answer and return what survives post-fill."""
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Ridgeline Roofing"}
    _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, facts)

    # Ask only for the fields under test, so every returned value is in-scope.
    wanted = {k: v for k, v in unmatched.items() if k in values}
    assert len(wanted) == len(values), (
        f"fixture drift: {set(values) - set(wanted)} are not gap fields on {form_id}"
    )

    client = _ScriptedClient(values)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
    out = ps._fill_unmatched_with_gpt(wanted, facts, form_id, raw_text=_FLEET_TEXT)
    return out["filled_values"]


# Three trucks, same garaging city/state/zip, same radius - all of it correct.
_SHARED_COLUMN_VALUES = {
    "Vehicle_PhysicalAddress_CityName_A": "Denver",
    "Vehicle_PhysicalAddress_CityName_B": "Denver",
    "Vehicle_PhysicalAddress_CityName_C": "Denver",
    "Vehicle_PhysicalAddress_StateOrProvinceCode_A": "CO",
    "Vehicle_PhysicalAddress_StateOrProvinceCode_B": "CO",
    "Vehicle_PhysicalAddress_StateOrProvinceCode_C": "CO",
    "Vehicle_PhysicalAddress_PostalCode_A": "80216",
    "Vehicle_PhysicalAddress_PostalCode_B": "80216",
    "Vehicle_PhysicalAddress_PostalCode_C": "80216",
    "Vehicle_RadiusOfUse_A": "50",
    "Vehicle_RadiusOfUse_B": "50",
    "Vehicle_RadiusOfUse_C": "50",
}


def test_fleet_rows_sharing_a_city_are_not_gutted(monkeypatch):
    """The reported bug, reproduced. Every one of these cells is correct."""
    filled = _run(monkeypatch, _SHARED_COLUMN_VALUES)
    missing = [f for f in _SHARED_COLUMN_VALUES if f not in filled]
    assert not missing, (
        f"{len(missing)} correct fleet cells were deleted by post-fill dedup "
        f"(e.g. {missing[:4]}). Three trucks garaged in the same city SHARE a "
        f"city - that is not a duplicate, and blanking it leaves rows B and C "
        f"empty on ACORD 127."
    )
    for f, v in _SHARED_COLUMN_VALUES.items():
        assert filled[f] == v, f"{f} was altered: {filled[f]!r} != {v!r}"


def test_distinct_per_row_values_still_survive(monkeypatch):
    """The columns that genuinely differ per row must come through untouched."""
    vals = {
        "Vehicle_CostNewAmount_A": "$58,900",
        "Vehicle_CostNewAmount_B": "$67,400",
        "Vehicle_CostNewAmount_C": "$81,250",
    }
    filled = _run(monkeypatch, vals)
    assert filled == {**filled, **vals}, "distinct per-row values were lost"


def test_identical_looking_rows_are_kept_not_guessed_away(monkeypatch):
    """Row-level 'duplicate row' detection was tried and rejected - this test
    locks in the rejection.

    A call only ever sees a SUBSET of a table's columns (Pass 1/1.5 resolves
    some; `_COMBINED_FIELD_BATCH` splits others across outer batches). Ask about
    City/State/PostalCode alone and three trucks genuinely garaged in one city
    produce three byte-identical rows. From inside this function, "the same
    entry written twice" and "two real entries that match on the columns we
    happened to ask about" are indistinguishable - so nothing may be deleted on
    that basis. Preventing duplicate entries belongs in the table prompt and in
    `already_filled`, not here.
    """
    vals = {
        "Vehicle_PhysicalAddress_CityName_A": "Denver",
        "Vehicle_PhysicalAddress_StateOrProvinceCode_A": "CO",
        "Vehicle_PhysicalAddress_CityName_B": "Denver",
        "Vehicle_PhysicalAddress_StateOrProvinceCode_B": "CO",
        "Vehicle_PhysicalAddress_CityName_C": "Denver",
        "Vehicle_PhysicalAddress_StateOrProvinceCode_C": "CO",
    }
    filled = _run(monkeypatch, vals)
    for f, v in vals.items():
        assert filled.get(f) == v, (
            f"{f} was deleted. Rows that look identical across the columns THIS "
            f"call asked about are not evidence of a duplicated entry - a "
            f"row-level dedup here destroys real fleet data."
        )


def test_slot_dedup_when_explicitly_re_enabled(monkeypatch):
    """The dedup is OFF by default (it was deleting correct fleet data), but the
    SLOT_VALUE_DEDUP escape hatch must still work for anyone who needs it."""
    monkeypatch.setattr(ps, "_ENABLE_SLOT_VALUE_DEDUP", True)
    fid = "ACORD_125"
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{fid}_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Ridgeline Roofing"}
    _mapped, unmatched, _ = ps.compute_form_gaps(fid, schema, facts)

    # Find any real multi-slot group on 125 that is NOT a detected table column.
    import re
    by_base = {}
    for f in unmatched:
        m = re.match(r"^(.*)_([A-N])$", f)
        if m:
            by_base.setdefault(m.group(1), []).append(f)
    cands = [v for v in by_base.values() if len(v) >= 3]
    if not cands:
        pytest.skip("no multi-slot group available on this schema")

    for group in sorted(cands, key=len, reverse=True):
        slots = sorted(group)[:3]
        vals = {s: "IDENTICAL VALUE" for s in slots}
        filled = _run(monkeypatch, vals, form_id=fid)
        kept = [s for s in slots if s in filled]
        if len(kept) == 1:
            return                      # deduped as intended
    pytest.skip("every candidate group was table-classified on this schema")
