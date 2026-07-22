"""
Regression tests for bulk schedule capture (Beta Report Figure 15).

Covers the three things that were broken or missing:

1. `_ordinal` produced "141th" (it only spelled out 1-10). The client's
   screenshot showed exactly that.
2. Repeating-row fields exploded into ONE QUESTION PER FIELD, ordinal-labelled,
   so a single ACORD 127 emitted ~140 "provide this vehicle's details" cards.
   They must now collapse into one table question per schedule.
3. The vehicle schedule's identity columns (VIN / make / model / body type) were
   bound to base names that exist in NO real ACORD schema
   (`Vehicle_VIN`/`Vehicle_Make`/`Vehicle_Model`), while the names ACORD 127
   actually uses (`Vehicle_VINIdentifier` / `Vehicle_ManufacturersName` /
   `Vehicle_ModelName` / `Vehicle_BodyCode`) were unmapped - so an extracted VIN
   could never be stamped. Same class of bug as the one already fixed for
   drivers in test_driver_schedule_mapping.py.

Run from backend/:
    python -m pytest tests/test_schedule_capture.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import schedule_capture as sc  # noqa: E402
from services.arq_service import (  # noqa: E402
    _build_schedule_questions,
    _finalize_schedule_taxonomy,
    _ordinal,
    _partition_schedule_fields,
    _restamp_schedule_into_forms,
)
from services.pdf_service import _resolve_schedule_row  # noqa: E402


# ── 1. Ordinals ──────────────────────────────────────────────────────────────

def test_ordinal_small_values_unchanged():
    assert [_ordinal(n) for n in (1, 2, 3, 4)] == ["1st", "2nd", "3rd", "4th"]


def test_ordinal_teens_use_th():
    assert [_ordinal(n) for n in (11, 12, 13)] == ["11th", "12th", "13th"]


def test_ordinal_large_values_are_correct():
    # The reported bug: 141 rendered as "141th".
    assert _ordinal(141) == "141st"
    assert _ordinal(142) == "142nd"
    assert _ordinal(143) == "143rd"
    assert _ordinal(111) == "111th"
    assert _ordinal(121) == "121st"


# ── 2. VIN validation ────────────────────────────────────────────────────────

def test_valid_vin_accepted():
    assert sc.is_valid_vin("1FTFW1ET5DFC10312")


def test_vin_normalised_before_validation():
    assert sc.is_valid_vin(" 1ftfw1et5dfc10312 ")
    assert sc.normalize_vin("1ftfw1-et5dfc10312") == "1FTFW1ET5DFC10312"


def test_vin_rejects_wrong_length():
    assert not sc.is_valid_vin("1FTFW1ET5DFC1031")     # 16
    assert not sc.is_valid_vin("1FTFW1ET5DFC103123")   # 18


def test_vin_rejects_forbidden_letters():
    # ISO 3779 excludes I, O and Q.
    assert not sc.is_valid_vin("IFTFW1ET5DFC10312")
    assert not sc.is_valid_vin("OFTFW1ET5DFC10312")
    assert not sc.is_valid_vin("QFTFW1ET5DFC10312")


# ── 3. Row validation ────────────────────────────────────────────────────────

def test_blank_rows_are_dropped_not_reported():
    rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "", "make": "", "model": "", "vin": ""},
        {"year": "2021", "make": "Ford", "model": "F-150", "vin": ""},
    ])
    assert len(rows) == 1
    assert report["errors"] == {}


def test_missing_required_cell_is_reported():
    rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "", "model": "F-150"},
    ])
    assert len(rows) == 1                       # kept: validation is advisory
    assert "make" in report["errors"]["0"]


def test_bad_vin_reported_but_row_kept():
    rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "Ford", "model": "F-150", "vin": "NOTAVIN"},
    ])
    assert len(rows) == 1
    assert "vin" in report["errors"]["0"]


def test_duplicate_vin_detected():
    vin = "1FTFW1ET5DFC10312"
    rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "Ford", "model": "F-150", "vin": vin},
        {"year": "2022", "make": "Ram",  "model": "1500",  "vin": vin.lower()},
    ])
    assert len(rows) == 2
    assert report["duplicates"] == [1]          # the SECOND occurrence


def test_distinct_vehicles_are_not_duplicates():
    rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "Ford", "model": "F-150", "vin": "1FTFW1ET5DFC10312"},
        {"year": "2022", "make": "Ram",  "model": "1500",  "vin": "1C6RR7GT4FS579878"},
    ])
    assert report["duplicates"] == []


def test_rows_with_no_dedup_values_are_never_duplicates():
    # Two vehicles with no VIN yet must not be collapsed into one.
    _rows, report = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "Ford", "model": "F-150"},
        {"year": "2022", "make": "Ram",  "model": "1500"},
    ])
    assert report["duplicates"] == []


def test_overflow_counts_rows_beyond_form_capacity():
    fleet = [{"year": "2020", "make": "Ford", "model": "F-150"} for _ in range(20)]
    _rows, report = sc.validate_rows("auto_vin_schedule", fleet)
    assert report["row_count"] == 20
    assert report["overflow"] == 20 - sc.ROW_CAPACITY


def test_row_cap_truncates_and_flags():
    huge = [{"year": "2020", "make": "F", "model": "X"} for _ in range(sc.MAX_ROWS + 10)]
    rows, report = sc.validate_rows("auto_vin_schedule", huge)
    assert len(rows) == sc.MAX_ROWS
    assert report["truncated"] is True


def test_cells_are_sanitized_and_clamped():
    rows, _ = sc.validate_rows("auto_vin_schedule", [
        {"year": "2021", "make": "<script>alert(1)</script>Ford", "model": "X" * 500},
    ])
    assert "<script>" not in rows[0]["make"]
    assert len(rows[0]["model"]) <= sc.MAX_CELL_LEN


# ── 4. Encode / decode round-trip through the answer pipeline ────────────────

def test_answer_roundtrip_preserves_a_large_fleet():
    fleet = [{"year": "2020", "make": "Ford", "model": f"Model{i}",
              "vin": "", "body_type": "", "gvw": ""} for i in range(143)]
    encoded = sc.encode_answer(fleet)
    assert isinstance(encoded, str)
    # The whole point: 143 vehicles must survive, not be clipped at 500 chars.
    assert len(encoded) > 500
    assert len(sc.decode_answer(encoded)) == 143


def test_decode_answer_tolerates_list_and_garbage():
    assert sc.decode_answer([{"a": 1}]) == [{"a": 1}]
    assert sc.decode_answer("not json") == []
    assert sc.decode_answer("") == []
    assert sc.decode_answer('{"not": "a list"}') == []


def test_rows_from_facts_handles_raw_list_and_envelope():
    raw = {"auto_vin_schedule": [{"year": "2021", "make": "Ford", "model": "F-150"}]}
    env = {"auto_vin_schedule": {"value": [{"year": "2021", "make": "Ford", "model": "F-150"}]}}
    assert sc.rows_from_facts("auto_vin_schedule", raw)[0]["make"] == "Ford"
    assert sc.rows_from_facts("auto_vin_schedule", env)[0]["make"] == "Ford"


def test_answer_key_helpers_roundtrip():
    key = sc.answer_key("auto_vin_schedule")
    assert sc.is_schedule_answer_key(key)
    assert sc.list_key_from_answer_key(key) == "auto_vin_schedule"
    assert not sc.is_schedule_answer_key("applicant_name")


# ── 5. Field detection + question collapse ───────────────────────────────────

def test_real_acord127_vehicle_fields_map_to_vehicle_schedule():
    for field in ("Vehicle_VINIdentifier_A", "Vehicle_ManufacturersName_B",
                  "Vehicle_ModelName_C", "Vehicle_ModelYear_A", "Vehicle_BodyCode_A"):
        assert sc.schedule_list_key_for_field(field) == "auto_vin_schedule", field


def test_real_acord127_driver_fields_map_to_driver_schedule():
    for field in ("Driver_GivenName_A", "Driver_LicenseNumberIdentifier_B",
                  "Driver_BirthDate_C"):
        assert sc.schedule_list_key_for_field(field) == "auto_drivers", field


def test_non_schedule_field_is_not_claimed():
    assert sc.schedule_list_key_for_field("Producer_FullName_A") is None
    assert sc.schedule_list_key_for_field("applicant_name") is None


def test_partition_removes_schedule_fields_and_groups_them():
    missing = {
        "Vehicle_VINIdentifier_A": {"ACORD_127"},
        "Vehicle_ModelYear_A":     {"ACORD_127"},
        "Driver_GivenName_A":      {"ACORD_127"},
        "applicant_name":          {"ACORD_125"},
    }
    current = {k: "" for k in missing}
    groups = _partition_schedule_fields(missing, current)

    # Schedule fields are gone from the per-field flow ...
    assert "Vehicle_VINIdentifier_A" not in missing
    assert "Driver_GivenName_A" not in missing
    # ... and the ordinary question is untouched.
    assert "applicant_name" in missing

    assert groups["auto_vin_schedule"] == {"ACORD_127"}
    assert groups["auto_drivers"] == {"ACORD_127"}


def test_many_vehicle_fields_collapse_to_one_question():
    """The heart of Figure 15: N fields in, exactly ONE question out."""
    missing = {f"Vehicle_VINIdentifier_{c}": {"ACORD_127"} for c in "ABCDEFGHIJKLN"}
    missing.update({f"Vehicle_ModelYear_{c}": {"ACORD_127"} for c in "ABCDEFGHIJKLN"})
    assert len(missing) == 26

    groups = _partition_schedule_fields(missing, {})
    questions = _build_schedule_questions(groups, {})

    assert missing == {}
    assert len(questions) == 1
    q = questions[0]
    assert q["field_type"] == "schedule"
    assert q["schedule_key"] == "auto_vin_schedule"
    # No ordinal labelling anywhere in the client-facing text.
    assert "141th" not in q["question"]
    assert "vehicle)" not in q["question"]


def test_schedule_question_preloads_known_rows():
    facts = {"auto_vin_schedule": [
        {"year": "2021", "make": "Ford", "model": "F-150", "vin": "1FTFW1ET5DFC10312"},
    ]}
    questions = _build_schedule_questions({"auto_vin_schedule": {"ACORD_127"}}, facts)
    assert questions[0]["current_rows"][0]["vin"] == "1FTFW1ET5DFC10312"
    assert questions[0]["vin_decode"] is True


def test_schedule_taxonomy_is_client_facing_and_never_suppressed():
    questions = _build_schedule_questions({"auto_vin_schedule": {"ACORD_127"}}, {})
    # Simulate decoration having wrongly suppressed it as "already provided".
    questions[0]["suppressed"] = True
    questions[0]["suppressed_reason"] = "already_provided"
    _finalize_schedule_taxonomy(questions)
    assert questions[0]["audience"] == "client"
    assert questions[0]["bucket"] == "client"
    assert questions[0]["suppressed"] is False


def test_finalize_taxonomy_leaves_normal_questions_alone():
    q = {"field_name": "applicant_name", "field_type": "text",
         "audience": "internal", "suppressed": True}
    _finalize_schedule_taxonomy([q])
    assert q["audience"] == "internal"
    assert q["suppressed"] is True


# ── 6. Stamping: the dead-binding fix ────────────────────────────────────────

_FLEET_FACTS = {
    "auto_vin_schedule": [
        {"year": "2021", "make": "Ford", "model": "F-150",
         "vin": "1FTFW1ET5DFC10312", "body_type": "Pickup", "gvw": "6500"},
        {"year": "2022", "make": "Ram", "model": "1500",
         "vin": "1C6RR7GT4FS579878", "body_type": "Pickup", "gvw": "6800"},
    ]
}


def test_vin_now_stamps_onto_the_real_acord127_field():
    # Regression: this returned None before Vehicle_VINIdentifier was mapped.
    assert _resolve_schedule_row("Vehicle_VINIdentifier_A", _FLEET_FACTS) == "1FTFW1ET5DFC10312"
    assert _resolve_schedule_row("Vehicle_VINIdentifier_B", _FLEET_FACTS) == "1C6RR7GT4FS579878"


def test_make_and_model_stamp_onto_real_acord127_fields():
    assert _resolve_schedule_row("Vehicle_ManufacturersName_A", _FLEET_FACTS) == "Ford"
    assert _resolve_schedule_row("Vehicle_ModelName_A", _FLEET_FACTS) == "F-150"
    assert _resolve_schedule_row("Vehicle_BodyCode_A", _FLEET_FACTS) == "Pickup"


def test_previously_working_vehicle_fields_still_stamp():
    # These two were the ONLY live vehicle bindings before the fix - they must
    # keep working exactly as they did.
    assert _resolve_schedule_row("Vehicle_ModelYear_A", _FLEET_FACTS) == "2021"
    assert _resolve_schedule_row("Vehicle_GrossVehicleWeight_A", _FLEET_FACTS) == "6500"


def test_row_beyond_list_length_stays_blank():
    assert _resolve_schedule_row("Vehicle_VINIdentifier_C", _FLEET_FACTS) is None


# ── 7b. Regression: deleting a row must CLEAR the form, not leave stale data ──

def _minimal_127_form():
    """Bare-bones generated-form shape with just the vehicle schema fields
    needed to exercise `_restamp_schedule_into_forms` without loading the real
    (huge) ACORD_127 schema."""
    return {
        "schema": {
            "Vehicle_VINIdentifier_A": {}, "Vehicle_VINIdentifier_B": {},
            "Vehicle_ManufacturersName_A": {}, "Vehicle_ManufacturersName_B": {},
        },
        "field_state": {},
        "confidence": {},
        "client_filled_fields": [],
    }


def test_restamp_fills_two_vehicles():
    generated = {"ACORD_127": _minimal_127_form()}
    facts = {"auto_vin_schedule": [
        {"vin": "1FTFW1ET5DFC10312", "make": "Ford"},
        {"vin": "1C6RR7GT4FS579878", "make": "Ram"},
    ]}
    touched = _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts)
    fs = generated["ACORD_127"]["field_state"]
    assert touched == ["ACORD_127"]
    assert fs["Vehicle_VINIdentifier_A"] == "1FTFW1ET5DFC10312"
    assert fs["Vehicle_VINIdentifier_B"] == "1C6RR7GT4FS579878"


def test_deleting_a_row_clears_its_stale_form_data():
    """The exact bug reported live: producer saves 2 vehicles, client deletes
    one and resubmits with 1 - the second vehicle's VIN/make must be BLANKED
    on the form, not left showing the deleted vehicle's old data."""
    generated = {"ACORD_127": _minimal_127_form()}
    facts = {"auto_vin_schedule": [
        {"vin": "1FTFW1ET5DFC10312", "make": "Ford"},
        {"vin": "1C6RR7GT4FS579878", "make": "Ram"},
    ]}
    _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts)

    # Client deletes the second vehicle - the list shrinks to 1.
    facts["auto_vin_schedule"] = [{"vin": "1FTFW1ET5DFC10312", "make": "Ford"}]
    touched = _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts)

    fs = generated["ACORD_127"]["field_state"]
    conf = generated["ACORD_127"]["confidence"]
    assert touched == ["ACORD_127"]                    # must re-render the PDF
    assert fs["Vehicle_VINIdentifier_A"] == "1FTFW1ET5DFC10312"   # row 1 kept
    assert fs["Vehicle_VINIdentifier_B"] == ""                    # row 2 CLEARED
    assert fs["Vehicle_ManufacturersName_B"] == ""
    assert "Vehicle_VINIdentifier_B" not in conf        # provenance cleared too


def test_clearing_all_rows_blanks_every_bound_field():
    generated = {"ACORD_127": _minimal_127_form()}
    facts = {"auto_vin_schedule": [{"vin": "1FTFW1ET5DFC10312", "make": "Ford"}]}
    _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts)

    facts["auto_vin_schedule"] = []
    _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts)

    fs = generated["ACORD_127"]["field_state"]
    assert fs["Vehicle_VINIdentifier_A"] == ""
    assert fs["Vehicle_ManufacturersName_A"] == ""


# ── 7. Every declared column must bind to a real ACORD field ─────────────────

def test_every_schedule_column_binds_to_a_live_acord_field():
    """Guards against re-introducing a column that silently discards input.

    Reads the real schemas and the real registry, so a future edit that adds a
    pretty column with no ACORD binding fails here instead of in production.
    """
    import glob
    import re

    from services.pdf_service import _SCHED_ROW_RE, _SCHEDULE_REGISTRY

    schemas_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas",
    )
    live = {}
    for path in glob.glob(os.path.join(schemas_dir, "*.json")):
        with open(path, encoding="utf-8") as fh:
            for field in json.load(fh):
                m = _SCHED_ROW_RE.match(field)
                if not m:
                    continue
                base = m.group(1)
                defn = _SCHEDULE_REGISTRY.get(base)
                if defn is None:
                    for prefix, d in _SCHEDULE_REGISTRY.items():
                        if (base == prefix or base.startswith(prefix + "_")
                                or base.endswith("_" + prefix)):
                            defn = d
                            break
                if defn is not None:
                    live.setdefault(defn.list_key, set()).add(defn.sub_key)

    for list_key, defn in sc.SCHEDULE_DEFS.items():
        bound = live.get(list_key, set())
        assert bound, f"schedule {list_key} has no live ACORD binding at all"
        for col in defn["columns"]:
            assert col["key"] in bound, (
                f"{list_key}.{col['key']} is not bound to any real ACORD field - "
                f"data entered in this column would be discarded"
            )
