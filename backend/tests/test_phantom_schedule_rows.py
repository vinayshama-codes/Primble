"""A repeating row for an entity the document does not contain must stay blank.

THE DEFECT (client's live ACORD 127, 2026-08-12): the document describes ONE
vehicle - a 2012 Subaru Outback - and the generated form came back with vehicle
rows 2 and 3 carrying the GENERAL LIABILITY class codes 91580/91585 and the GL
exposures ($39,300 payroll, $350,000 subcontract cost) stamped as vehicle COST
NEW, plus a duplicated Subaru.

`_SCHEDULE_REGISTRY` binds only the 19 IDENTITY columns of the vehicle schedule.
`_resolve_schedule_row` already blanks THOSE when the row is out of range, but
the other ~50 columns per row were unbound and fell through to gap fill for every
row letter the form prints - 164 questions about vehicles that do not exist.

The fix extends the same out-of-range contract to the whole row. These tests pin
both directions: phantom rows suppressed, real rows untouched.
"""
import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps  # noqa: E402

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


ONE_VEHICLE = {
    "vin": "4S4BRCGC9C3217772", "year": "2012", "make": "Subaru",
    "model": "Outback", "body_style": "SEDAN", "cost_new": "$26,680",
}


def _vehicle_rows_asked(facts):
    """Row letters of Vehicle_* fields still sent to the gap-fill model."""
    _, unmatched, _ = ps.compute_form_gaps("ACORD_127", _schema("ACORD_127"), facts)
    rows = {}
    for f in unmatched:
        if f.split("_", 1)[0] == "Vehicle" and len(f) > 2 and f[-2] == "_":
            rows.setdefault(f[-1], []).append(f)
    return rows


def test_one_vehicle_means_no_questions_about_a_second():
    """THE regression. One vehicle in the document -> zero phantom rows."""
    rows = _vehicle_rows_asked({"auto_vin_schedule": [ONE_VEHICLE]})
    assert rows.get("A"), "the REAL vehicle's row must still be asked about"
    phantom = {k: len(v) for k, v in rows.items() if k != "A"}
    assert not phantom, (
        f"asked about vehicles that do not exist: {phantom}. This is how the "
        f"GL payroll became a vehicle COST NEW."
    )


def test_three_vehicles_keep_three_rows():
    """The suppression must follow the document, not a constant."""
    facts = {"auto_vin_schedule": [dict(ONE_VEHICLE, vin=f"VIN{i}") for i in range(3)]}
    rows = _vehicle_rows_asked(facts)
    for letter in ("A", "B", "C"):
        assert rows.get(letter), f"row {letter} is a REAL vehicle and must be asked"
    assert not [k for k in rows if k not in ("A", "B", "C")], (
        f"rows beyond the 3 real vehicles were asked: {sorted(rows)}")


def test_no_schedule_evidence_changes_nothing():
    """Absent or empty list = we know nothing. Suppressing on no evidence would
    silently delete a schedule the extractor simply missed."""
    for facts in ({}, {"auto_vin_schedule": []}, {"auto_vin_schedule": None}):
        rows = _vehicle_rows_asked(facts)
        assert len(rows) > 1, (
            f"with no row-count evidence ({facts!r}) every row must still be "
            f"asked about, got {sorted(rows)}")


# ── the resolver's own contract ─────────────────────────────────────────────
def test_resolver_declines_when_it_has_no_business():
    skip = ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row("Applicant_FullName", {}) is skip
    assert ps._resolve_phantom_schedule_row("", {}) is skip
    assert ps._resolve_phantom_schedule_row("NotASchedule_A", {}) is skip
    # known root, but no evidence
    assert ps._resolve_phantom_schedule_row("Vehicle_CostNewAmount_C", {}) is skip


def test_resolver_blanks_only_beyond_capacity():
    facts = {"auto_vin_schedule": [ONE_VEHICLE, ONE_VEHICLE]}
    assert ps._resolve_phantom_schedule_row("Vehicle_CostNewAmount_A", facts) is ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row("Vehicle_CostNewAmount_B", facts) is ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row("Vehicle_CostNewAmount_C", facts) is None
    assert ps._resolve_phantom_schedule_row("Vehicle_CostNewAmount_N", facts) is None


def test_row_offset_is_honoured():
    """NamedInsured_A is the APPLICANT; the list supplies row B onward
    (row_offset=1). Using len() alone would blank a real named insured."""
    offsets = {
        off
        for base, d in ps._SCHEDULE_REGISTRY.items()
        if base.split("_", 1)[0] == "NamedInsured"
        for off in (d.row_offset,)
    }
    assert offsets == {1}, f"registry changed; revisit capacity maths: {offsets}"
    facts = {"additional_named_insureds": ["SECOND ENTITY LLC"]}
    # capacity = 1 entry + offset 1 = 2 real rows (A = applicant, B = the entry)
    assert ps._resolve_phantom_schedule_row("NamedInsured_FullName_A", facts) is ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row("NamedInsured_FullName_B", facts) is ps._SCHED_SKIP
    assert ps._resolve_phantom_schedule_row("NamedInsured_FullName_C", facts) is None


def test_bindings_are_derived_from_the_registry_not_hand_listed():
    """A schedule added to _SCHEDULE_REGISTRY must be covered automatically -
    a second hand-maintained list is how these two drift apart."""
    bindings = ps._schedule_root_bindings()
    roots = {b.split("_", 1)[0] for b in ps._SCHEDULE_REGISTRY}
    assert set(bindings) == roots
    assert "Vehicle" in bindings and "Driver" in bindings


def test_suppression_is_generic_across_forms():
    """Not vehicle-specific: the same rule must fire for a property schedule."""
    facts = {"property_locations": [{"address": "4800 Dahlia St", "city": "Denver"}]}
    _, unmatched, _ = ps.compute_form_gaps("ACORD_140", _schema("ACORD_140"), facts)
    beyond = [
        f for f in unmatched
        if len(f) > 2 and f[-2] == "_" and f[-1] in "BCDEFGHIJKLMN"
        and f.split("_", 1)[0] in ("CommercialStructure", "PropertyLocation",
                                   "BuildingOccupancy", "Construction")
    ]
    assert not beyond, f"phantom location rows still asked: {beyond[:8]}"


@pytest.mark.parametrize("form_id", ["ACORD_127", "ACORD_140", "ACORD_125"])
def test_real_row_a_survives_on_every_form(form_id):
    """The fix must never cost coverage on the rows that DO exist."""
    facts = {
        "auto_vin_schedule": [ONE_VEHICLE],
        "property_locations": [{"address": "4800 Dahlia St", "city": "Denver"}],
        "auto_drivers": [{"name": "JOHN SMITH", "license": "CO123"}],
    }
    _, unmatched, _ = ps.compute_form_gaps(form_id, _schema(form_id), facts)
    row_a = [f for f in unmatched if len(f) > 2 and f[-2] == "_" and f[-1] == "A"]
    assert row_a, f"{form_id}: row A questions disappeared entirely"
