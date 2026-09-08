"""BUG-07 - "hundreds of indexed ghost vehicle questions" (client, 2026-09-07).

The reported symptom: a client questionnaire carrying cards that read

    Please provide the following details for this vehicle: Year, Make, Model,
    VIN (Vehicle Identification Number), and primary use ... (308th vehicle)

on a submission with nothing like 308 vehicles. Live on 2026-09-07 a package
holding 18 vehicles asked about 286, and 6 of the cards came from ACORD 25 - a
certificate of insurance, which carries no vehicle schedule at all.

ROOT CAUSE. `_FIELD_PREFIX_MAP` is a curated snake_case vocabulary describing
the pseudo-fields WE invent (`vehicle_vin`, `driver_name`). It was matched
against raw ACORD field names with a bare, case-insensitive `startswith`, and
ACORD names its whole Commercial Auto section `Vehicle_*` - so a covered-auto
symbol checkbox matched `vehicle_`, took the one-vehicle question text, the
"vehicle" group label and (via `_is_curated_client_field`) a CLIENT audience.
`group_counts` then numbered it by FIELD, from one counter shared across every
selected form.

Four independent things were wrong and each has tests below:
  1. wrong text      - a /Btn checkbox asked for "Year, Make, Model, VIN"
  2. wrong audience  - 376 ACORD 137_CO symbol boxes addressed to the insured
  3. wrong number    - an ordinal counting questions, not records
  4. wrong filter    - polished English removed the `_MACHINE_QUESTION_PREFIX`
                       marker `_hide_machine_worded_questions` tests for, so the
                       one guard built to catch raw schema prompts went blind

Plus the companion defect the same live run exposed: with an EMPTY schedule the
capture table was not offered at all.

Every test drives the REAL 17 schemas in `forms_schemas/`, never a fixture, and
several drive the real async generator end to end - the standing lesson from
H3-D and `fix-the-layer-the-screen-reads` is that a unit test on the primitive
passes while the screen stays broken.

Run from backend/:
    python -m pytest tests/test_bug07_ghost_vehicle_questions.py -v
"""

import asyncio
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.arq_service as A                              # noqa: E402
from services import schedule_capture as sc                   # noqa: E402
from services.question_classifier import classify_question    # noqa: E402

SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _schema(form_id: str) -> dict:
    with open(os.path.join(SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _all_acord_fields() -> set:
    names = set()
    for path in glob.glob(os.path.join(SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            names.update(json.load(fh).keys())
    return names


# The three cards the client screenshotted, resolved against the real schema.
CLIENT_REPORTED_CARDS = [
    "Vehicle_BusinessAutoSymbol_OtherSymbolCode_F",   # was "(308th vehicle)"
    "Vehicle_BusinessAutoSymbol_TwoIndicator_G",      # was "(309th vehicle)"
    "Vehicle_BusinessAutoSymbol_ThreeIndicator_G",    # was "(310th vehicle)"
]


# ── 1. The prefix vocabulary must never claim a raw ACORD field ──────────────

def test_client_reported_cards_are_no_longer_vehicles():
    """Must never fail: the literal fields behind the client's screenshot."""
    for name in CLIENT_REPORTED_CARDS:
        question, group_label = A._resolve_question(name)
        assert group_label is None, f"{name} still labelled {group_label!r}"
        assert "this vehicle" not in question.lower()
        assert "VIN" not in question


def test_no_acord_field_anywhere_receives_a_group_label():
    """The whole class, across all 17 forms - not just the reported example.

    Measured before the fix: 1,390 field/form instances took a group label
    (1,161 vehicle, 162 driver, 57 insurer, 10 location) and ZERO of them bound
    a real schedule column.
    """
    offenders = []
    for path in sorted(glob.glob(os.path.join(SCHEMA_DIR, "*_schema.json"))):
        with open(path, encoding="utf-8") as fh:
            for field_name in json.load(fh):
                if A._resolve_question(field_name)[1] is not None:
                    offenders.append((os.path.basename(path), field_name))
    assert not offenders, f"{len(offenders)} ACORD fields still grouped: {offenders[:5]}"


def test_symbol_checkboxes_are_not_addressed_to_the_client():
    """Wrong TEXT and wrong AUDIENCE are two defects; fixing one is not enough.

    Scoped to raw boxes with NO canonical fact behind them - that is the ghost
    class. ACORD 137_CO also carries 15 `Vehicle_*` fields that legitimately
    resolve to `auto_liability_structure` / `auto_bi_per_person` /
    `auto_bi_per_accident` / `auto_pd_per_accident` (the H1 split-limit facts).
    Those SHOULD reach the client, they carry real curated wording, and the
    generator dedupes them by canonical key to four questions. An earlier draft
    of this test asserted over every `Vehicle_*` field and was simply wrong.
    """
    schema = _schema("ACORD_137_CO")
    vehicle_fields = [k for k in schema if k.lower().startswith("vehicle_")]
    assert len(vehicle_fields) > 300, "fixture drifted - expected the 137 symbol grid"
    checked = 0
    for name in vehicle_fields:
        if A._canonical_key(name):
            continue                      # a real fact, not a ghost
        checked += 1
        verdict = classify_question(
            name, ["ACORD_137_CO"],
            is_curated_client=A._is_curated_client_field(name),
            canonical_key=None,
        )
        assert verdict["audience"] != "client", f"{name} still client-facing"
    assert checked > 300, "the ghost population vanished - test is now vacuous"


def test_the_real_auto_limit_facts_still_reach_the_client():
    """The other direction. Over-suppression here would silently drop the
    split-limit capture H1 shipped."""
    for name, canon in [("Vehicle_CombinedSingleLimit_LimitIndicator_A",
                         "auto_liability_structure"),
                        ("Vehicle_BodilyInjury_PerPersonLimitAmount_A",
                         "auto_bi_per_person"),
                        ("Vehicle_PropertyDamage_PerAccidentLimitAmount_A",
                         "auto_pd_per_accident")]:
        assert A._canonical_key(name) == canon
        verdict = classify_question(
            name, ["ACORD_137_CO"],
            is_curated_client=A._is_curated_client_field(name),
            canonical_key=canon)
        assert verdict["audience"] == "client", name
        question, group_label = A._resolve_question(canon)
        assert group_label is None
        assert not question.startswith(A._MACHINE_QUESTION_PREFIX)


def test_raw_fields_fall_through_to_the_machine_worded_guard():
    """The filter that was going blind. A raw box must keep the marker
    `_hide_machine_worded_questions` routes on, or it stays on screen."""
    for name in CLIENT_REPORTED_CARDS + ["Driver_GenderCode_A",
                                         "Location_HighestFloorCount_B",
                                         "Vehicle_InsurerLetterCode_A"]:
        question, _ = A._resolve_question(name)
        assert question.startswith(A._MACHINE_QUESTION_PREFIX), name


def test_curated_pseudo_fields_are_untouched():
    """The vocabulary still works for the names it was written for."""
    for name, expected in [("vehicle_vin", "vehicle"), ("driver_name", "driver"),
                           ("location_address", "location"), ("claim_date", "claim"),
                           ("insurer_naic", "insurer"),
                           ("location_address_2", "location")]:
        assert A._resolve_question(name)[1] == expected, name
        assert A._is_curated_client_field(name) is True, name


def test_is_raw_acord_field_agrees_with_the_structural_fallback():
    """Two conditions, and they must not disagree on real data (H1-F).

    Condition 2 (any uppercase) is what keeps the gate working when
    `forms_schemas/` cannot be read, so it has to hold for every real name.
    """
    for name in _all_acord_fields():
        assert any(c.isupper() for c in name), f"{name!r} breaks the fallback"
        assert A._is_raw_acord_field(name) is True


def test_the_gate_still_holds_without_the_schema_index(monkeypatch):
    """Fail-safe, not fail-open: an unreadable schema directory must not
    reintroduce the bug."""
    monkeypatch.setattr(A, "_acord_field_names", lambda: frozenset())
    for name in CLIENT_REPORTED_CARDS:
        assert A._is_raw_acord_field(name) is True
        assert A._resolve_question(name)[1] is None
    assert A._resolve_question("vehicle_vin")[1] == "vehicle"


# ── 2. The ordinal must count records, not questions ─────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("location_address_2", 2),
    ("location_address_11", 11),
    ("Vehicle_VINIdentifier_A", 1),
    ("Vehicle_VINIdentifier_C", 3),
    ("Vehicle_VINIdentifier_N", 14),
    ("vehicle_vin", None),
    ("driver_name", None),
    ("", None),
    ("location_address_0", None),
])
def test_record_ordinal_reads_the_name(name, expected):
    assert A._record_ordinal(name) == expected


def test_two_fields_of_one_record_share_its_ordinal():
    """`location_address_2` and `location_city_2` are both about location 2.
    The old counter gave them different numbers, which is what made "(308th
    vehicle)" possible."""
    assert A._record_ordinal("location_address_2") == A._record_ordinal("location_city_2")


def test_ordinal_never_exceeds_the_record_count():
    """The reported failure, reduced: 500 grouped questions about 3 records must
    never print an ordinal above 3."""
    questions = []
    labels = []
    for i in range(500):
        rec = (i % 3) + 1
        labels.append(A._label_grouped_question(
            "Please provide the details for this location.", "location",
            f"location_address_{rec}", questions))
    for text in labels:
        m = re.search(r"\((\d+)(?:st|nd|rd|th) location\)", text)
        if m:
            assert int(m.group(1)) <= 3, text


def test_first_record_is_retro_labelled_once_a_second_appears():
    questions = [{"_group_label": "location", "field_name": "location_address",
                  "question": "What is the address of this business location?"}]
    out = A._label_grouped_question(
        "What is the address of this business location?", "location",
        "location_address_2", questions)
    assert out.endswith("(2nd location)")
    assert questions[0]["question"].endswith("(1st location)")


def test_both_generators_share_one_labeller():
    """The duplication class that let the Umbrella SIR and auto-symbol defects
    survive their first fixes. Neither generator may hold its own counter."""
    src = open(A.__file__, encoding="utf-8").read()
    assert "group_counts[group_label]" not in src
    assert src.count("_label_grouped_question(") >= 3   # def + both call sites


# ── 3. The capture tables - the feature that must NOT regress ────────────────

def test_forms_without_a_fleet_carry_no_vehicle_schedule():
    """C4 (2026-08-26), now structural. ACORD 25 and 131 must never be able to
    raise a fleet table, whatever the facts say."""
    for form_id in ("ACORD_25", "ACORD_131", "ACORD_137_CO", "ACORD_138_CO"):
        carried = sc.schedules_on_form(form_id)
        assert "auto_vin_schedule" not in carried, form_id
        assert "auto_drivers" not in carried, form_id


def test_acord_127_carries_the_two_auto_schedules():
    carried = sc.schedules_on_form("ACORD_127")
    assert {"auto_vin_schedule", "auto_drivers"} <= carried


def test_schedules_on_form_prefers_the_passed_schema():
    assert sc.schedules_on_form("ACORD_127", {}) == sc.schedules_on_form("ACORD_127")
    assert sc.schedules_on_form("ACORD_127", {"Nothing_Here_A": {}}) == frozenset()


def test_empty_schedule_still_offers_its_table():
    """The companion defect. `_suppress_ghost_schedule_rows` deleted every row
    field of an empty schedule before the partition ran, so PASS 1 found no
    capturable column and the grid vanished - exactly when the client most needs
    it. Live 2026-09-07 on `A_no_fleet.pdf`."""
    schema = _schema("ACORD_127")
    missing = {k: {"ACORD_127"} for k in schema}
    out = A._partition_schedule_fields(
        missing, {}, form_schemas={"ACORD_127": schema}, facts={})
    assert "auto_vin_schedule" in out
    assert "auto_drivers" in out


def test_empty_schedule_offers_its_table_even_with_no_missing_fields():
    """The precise live shape: every box already filled, no rows captured."""
    schema = _schema("ACORD_127")
    out = A._partition_schedule_fields(
        {}, {}, form_schemas={"ACORD_127": schema}, facts={})
    assert "auto_vin_schedule" in out, "PASS 3 did not seed a 1b-only schedule"


def test_a_form_without_the_schedule_never_seeds_one():
    schema = _schema("ACORD_25")
    out = A._partition_schedule_fields(
        {}, {}, form_schemas={"ACORD_25": schema}, facts={})
    assert "auto_vin_schedule" not in out
    assert "auto_drivers" not in out


# ── 4. End to end, through the real generator ────────────────────────────────

FORMS = ["ACORD_125", "ACORD_127", "ACORD_137_CO", "ACORD_25"]


def _generated(form_ids):
    out = {}
    for fid in form_ids:
        schema = _schema(fid)
        out[fid] = {"schema": schema,
                    "confidence": {k: "missing_required" for k in schema},
                    "field_state": {k: "" for k in schema},
                    "client_filled_fields": []}
    return out


def _run(form_ids, facts, monkeypatch):
    monkeypatch.setattr(A, "_humanize_fields_with_openai",
                        lambda *a, **k: asyncio.sleep(0))
    return asyncio.run(A.generate_arq_questions(
        facts, {"has_auto_coverage": True}, _generated(form_ids), [], []))


def _vehicle_ordinals(questions):
    out = []
    for q in questions:
        m = re.search(r"\((\d+)(?:st|nd|rd|th) vehicle\)", q.get("question") or "")
        if m:
            out.append(int(m.group(1)))
    return out


FLEET_18 = [{"year": "2021", "make": "Ford", "model": "F-250",
             "vin": f"1FT7W2BT5MED123{i:02d}"} for i in range(18)]
DRIVERS_16 = [{"name": f"Driver {i}", "license": f"D{i}", "dob": "01/01/1980"}
              for i in range(16)]


def test_no_ghost_vehicle_card_survives_generation(monkeypatch):
    """Worst case: every box on four forms blank, no fleet. Before the fix this
    is where the 286-card list came from."""
    qs = _run(FORMS, {"applicant_name": "Test LLC"}, monkeypatch)
    assert _vehicle_ordinals(qs) == []


def test_ghost_count_no_longer_depends_on_the_fleet(monkeypatch):
    """The live A/B pair: 0 vehicles gave 5 cards, 18 gave 286. Both must now be
    zero, and the client-facing counts must match."""
    empty = _run(FORMS, {"applicant_name": "Test LLC"}, monkeypatch)
    full = _run(FORMS, {"applicant_name": "Test LLC",
                        "auto_vin_schedule": FLEET_18,
                        "auto_drivers": DRIVERS_16}, monkeypatch)
    assert _vehicle_ordinals(empty) == []
    assert _vehicle_ordinals(full) == []
    n_empty = sum(1 for q in empty if q.get("audience") == "client")
    n_full = sum(1 for q in full if q.get("audience") == "client")
    assert n_empty == n_full, f"client count still fleet-dependent: {n_empty} vs {n_full}"


def test_both_capture_tables_survive_at_zero_rows(monkeypatch):
    qs = _run(FORMS, {"applicant_name": "Test LLC"}, monkeypatch)
    tables = {q["schedule_key"]: q for q in qs if q.get("field_type") == "schedule"}
    assert "auto_vin_schedule" in tables
    assert "auto_drivers" in tables
    assert tables["auto_vin_schedule"]["current_rows"] == []


def test_capture_tables_preload_and_overflow(monkeypatch):
    """18 vehicles into a form that prints 14 rows: every row retained, the
    overflow surfaced rather than silently dropped."""
    qs = _run(FORMS, {"applicant_name": "Test LLC",
                      "auto_vin_schedule": FLEET_18,
                      "auto_drivers": DRIVERS_16}, monkeypatch)
    tables = {q["schedule_key"]: q for q in qs if q.get("field_type") == "schedule"}
    assert len(tables["auto_vin_schedule"]["current_rows"]) == 18
    assert len(tables["auto_drivers"]["current_rows"]) == 16
    assert tables["auto_vin_schedule"]["row_capacity"] == 14


def test_a_schedule_is_never_asked_twice(monkeypatch):
    """H1-E: once as its grid, never also as a free-text scalar. Live 2026-09-07
    the client got the scalar INSTEAD of the grid."""
    for facts in ({"applicant_name": "T"},
                  {"applicant_name": "T", "auto_vin_schedule": FLEET_18}):
        qs = _run(FORMS, facts, monkeypatch)
        for key in ("auto_vin_schedule", "auto_drivers"):
            scalars = [q for q in qs
                       if q.get("_canonical_key") == key
                       and q.get("field_type") != "schedule"]
            assert not scalars, f"{key} asked twice: {[q['question'][:50] for q in scalars]}"


def test_certificate_and_umbrella_never_raise_a_fleet_table(monkeypatch):
    """The C4 regression guard, through the top-level generator."""
    qs = _run(["ACORD_125", "ACORD_131", "ACORD_25"],
              {"applicant_name": "Test LLC"}, monkeypatch)
    keys = {q.get("schedule_key") for q in qs if q.get("field_type") == "schedule"}
    assert "auto_vin_schedule" not in keys
    assert "auto_drivers" not in keys
    assert _vehicle_ordinals(qs) == []


def test_the_carrier_questions_survive_the_prefix_gate(monkeypatch):
    """Removing the prefix rescue must not delete a real producer question.
    `Insurer_NAICCode_A` resolves to `carrier_naic`, whose wording lives in
    FACT_REGISTRY and not in `_FIELD_QUESTION_MAP`."""
    canon = A._canonical_key("Insurer_NAICCode_A")
    assert canon == "carrier_naic"
    text_key = canon if A._curated_question_for(canon) else "Insurer_NAICCode_A"
    question, group_label = A._resolve_question(text_key)
    assert group_label is None
    assert not question.startswith(A._MACHINE_QUESTION_PREFIX)
    assert "NAIC" in question
