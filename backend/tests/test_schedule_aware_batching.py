"""Regression guard: an outer batch must never cut a schedule in half (C19).

Found live on a real 5-form generation (2026-07-29). `combined_gap_fill` sliced
the cross-form union with a plain `field_items[i:i+200]`, which put ACORD 127's
vehicle rows A-C in `COMBINED_B4of6` and row D in `B5of6`. Those are two
SEPARATE `_fill_unmatched_with_gpt` invocations - two separate LLM calls that
never see each other - so the call filling row D had no idea which real vehicle
was still unclaimed. It produced, and shipped to the PDF:

    Vehicle_CostNewAmount_D          = $58,900   (vehicle 1's cost; #4 is $41,800)
    Vehicle_RateClassCode_D          = 91560     (a General Liability class code)
    Vehicle_SpecialIndustryClassCode_D = 92478   (the sheet-metal GL class code)

Wrong values on a form, which is the one outcome this codebase treats as
non-negotiable. `_pack_field_batches` already keeps a table atomic one level
down; the bug was that the level ABOVE it was doing the cutting.
"""
import re

import pytest

import services.pdf_service as ps


def _mk(names):
    return [(n, {"ft": "/Tx", "tu": ""}) for n in names]


def _batch_of(batches, field):
    for i, b in enumerate(batches):
        if any(n == field for n, _ in b):
            return i
    return None


def test_vehicle_rows_are_never_split_across_outer_batches():
    """The exact reported shape: enough filler to push row D past the 200 mark."""
    filler = [f"Filler_Field_{i:03d}" for i in range(190)]
    vehicle = [
        f"Vehicle_{col}_{row}"
        for row in "ABCD"
        for col in ("CostNewAmount", "RateClassCode", "RadiusOfUse",
                    "PhysicalAddress_CityName", "SpecialIndustryClassCode")
    ]
    batches = ps._pack_schedule_aware_batches(_mk(filler + vehicle))

    homes = {r: _batch_of(batches, f"Vehicle_CostNewAmount_{r}") for r in "ABCD"}
    assert len(set(homes.values())) == 1, (
        f"vehicle rows landed in different outer batches {homes} - each outer batch "
        f"is a separate LLM call, so the call filling the stranded row cannot see "
        f"the others and will borrow values from elsewhere in the document "
        f"(improving-ll.md C19)"
    )


def test_every_field_survives_batching_exactly_once():
    """Regrouping must not drop or duplicate a field."""
    names = (
        [f"Filler_{i:03d}" for i in range(250)]
        + [f"Vehicle_Col{c}_{r}" for r in "ABCDE" for c in range(12)]
        + [f"Driver_Col{c}_{r}" for r in "ABC" for c in range(8)]
        + ["Standalone_Field_Without_Row_Suffix"]
    )
    batches = ps._pack_schedule_aware_batches(_mk(names))
    flat = [n for b in batches for n, _ in b]
    assert sorted(flat) == sorted(names), "fields were dropped or duplicated"
    assert len(flat) == len(set(flat)), "a field appears in two batches"


def test_multiple_schedules_each_stay_whole():
    names = (
        [f"Filler_{i:03d}" for i in range(150)]
        + [f"Vehicle_Col{c}_{r}" for r in "ABCD" for c in range(15)]
        + [f"CommercialProperty_Premises_Col{c}_{r}" for r in "ABCDEG" for c in range(10)]
    )
    batches = ps._pack_schedule_aware_batches(_mk(names))
    for root, rows in (("Vehicle_Col0", "ABCD"),
                       ("CommercialProperty_Premises_Col0", "ABCDEG")):
        homes = {r: _batch_of(batches, f"{root}_{r}") for r in rows}
        assert len(set(homes.values())) == 1, f"{root} was split across batches: {homes}"


def test_a_single_row_root_is_not_treated_as_a_schedule():
    """Only roots that really have multiple rows get held together; otherwise a
    common prefix would drag unrelated fields into one giant batch."""
    names = [f"Policy_Field{i:03d}_A" for i in range(400)]
    batches = ps._pack_schedule_aware_batches(_mk(names))
    assert len(batches) > 1, (
        "400 single-row fields sharing a prefix must still be split normally - "
        "they have no rows to align"
    )


def test_an_oversized_schedule_is_still_bounded():
    """A schedule is kept whole even past _COMBINED_FIELD_BATCH, but not without
    limit - one enormous call is its own failure mode."""
    names = [f"Vehicle_Col{c:03d}_{r}" for r in "ABCDEFGHIJKLMN" for c in range(80)]
    batches = ps._pack_schedule_aware_batches(_mk(names))
    assert max(len(b) for b in batches) <= ps._COMBINED_BATCH_HARD_MAX, (
        "an oversized schedule must be split rather than building an unbounded batch"
    )


def test_batches_respect_the_soft_size_target_for_ordinary_fields():
    names = [f"Plain_Field_{i:04d}" for i in range(1000)]
    batches = ps._pack_schedule_aware_batches(_mk(names))
    for b in batches:
        assert len(b) <= ps._COMBINED_FIELD_BATCH, (
            "ordinary fields must still pack to _COMBINED_FIELD_BATCH"
        )
