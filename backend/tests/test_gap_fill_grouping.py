"""
Regression tests for gap-fill repeating-group partitioning
(services.pdf_service.repeating_group_key).

Locks in the ACORD 127 owner-box fix: ACORD reuses one base name
(AdditionalInterest_FullName) for two DIFFERENT roles - the additional-interest
(lienholder) schedule (_A/_B) and "the name of the other owner of the vehicle"
(_C/_D) - distinguished only by the schema tooltip. Grouping by base alone
merged them into one ordinal "find N distinct values" block, so the gap-fill LLM
filled the lienholder and left the owner boxes empty. Grouping by (base, tooltip)
splits them so the owner names land in _C/_D.

These tests exercise the REAL module-level function and assert the property
against the REAL schema files, so they fail if either the grouping rule is
reverted OR a schema change removes the distinguishing tooltip the fix relies on.

Run from backend/:
    python -m pytest tests/test_gap_fill_grouping.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import repeating_group_key  # noqa: E402

_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _partition(schema: dict) -> dict:
    """Group a schema's slot fields exactly as the gap-fill code does."""
    groups: dict = {}
    for field, meta in schema.items():
        tu = meta.get("tu") if isinstance(meta, dict) else None
        gk = repeating_group_key(field, tu)
        if gk:
            groups.setdefault(gk, []).append(field)
    for k in groups:
        groups[k].sort()
    return groups


# ── Pure function behavior ────────────────────────────────────────────────────

def test_same_base_different_tooltip_splits():
    owner = repeating_group_key(
        "AdditionalInterest_FullName_C",
        "The additional interest's full name. As used here, this is the name of the other owner of the vehicle.",
    )
    lien = repeating_group_key("AdditionalInterest_FullName_A", "The additional interest's full name.")
    assert owner is not None and lien is not None
    assert owner != lien                 # different roles -> different groups
    assert owner[0] == lien[0] == "AdditionalInterest_FullName"   # same base


def test_same_base_same_tooltip_stays_one_group():
    a = repeating_group_key("Driver_FullName_A", "The driver's full name.")
    b = repeating_group_key("Driver_FullName_B", "The driver's full name.")
    assert a == b                        # true repeating schedule -> one group


def test_non_slot_field_returns_none():
    assert repeating_group_key("SomeFieldWithoutRowSuffix", "x") is None
    assert repeating_group_key("", None) is None


def test_tooltip_whitespace_normalized():
    assert repeating_group_key("X_A", " same ") == repeating_group_key("X_B", "same")


# ── Against the REAL ACORD 127 schema (the reported bug) ──────────────────────

def test_acord127_owner_boxes_split_from_lienholder_rows():
    schema = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_127_schema.json"), encoding="utf-8"))
    groups = _partition(schema)
    ai_groups = {gk: v for gk, v in groups.items() if gk[0] == "AdditionalInterest_FullName"}
    # Must be at least TWO groups (lienholder vs other-owner), not one merged group.
    assert len(ai_groups) >= 2, ai_groups

    def _letters(fields):
        return {f.rsplit("_", 1)[-1] for f in fields}

    owner_group = [v for gk, v in ai_groups.items() if "other owner" in gk[1].lower()]
    assert owner_group, "no 'other owner of the vehicle' group found"
    owner_letters = _letters(owner_group[0])
    # The vehicle owner boxes are rows C and D; they must be their OWN group,
    # not mixed with the lienholder rows A/B.
    assert {"C", "D"} <= owner_letters
    assert "A" not in owner_letters and "B" not in owner_letters


def test_true_repeating_schedules_stay_single_group_on_acord127():
    schema = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_127_schema.json"), encoding="utf-8"))
    groups = _partition(schema)
    for base in ("Driver_GivenName", "Driver_HiredDate", "Vehicle_ManufacturersName"):
        n = sum(1 for gk in groups if gk[0] == base)
        assert n == 1, f"{base} should be ONE homogeneous group, got {n}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
