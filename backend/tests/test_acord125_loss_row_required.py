"""
BUG-04 - "Do not force a required loss-row Date of Occurrence when 'Check if
none' is selected."  (client, 1 Sep live test; reproduced 2026-09-08)

THE DEFECT
----------
`_acord125_row_started` decided "row A of this section has data" with a bare
`startswith(prefix_) and endswith(_A)` string test. On ACORD 125 the loss
section prints three claim rows AND three SECTION SUMMARY boxes that also end
`_A`:

    LossHistory_NoPriorLossesIndicator_A   <- the "Check if none" tick
    LossHistory_InformationYearCount_A     <- "for the last N years"
    LossHistory_TotalAmount_A              <- TOTAL LOSSES

so ticking "Check if none" told the highlighter that row A had started, and the
form then marked a date of occurrence, a claim date, a paid amount and a reserve
REQUIRED for a claim that does not exist. Measured before the fix: the Required
count went from 2 to 7 the moment the producer attested there were NO losses.
The only state that escaped the loss-row highlight was a completely blank loss
section - the one that genuinely IS incomplete. Exactly inverted.

THE FIX, AND WHY IT IS A RULE AND NOT A LIST
--------------------------------------------
A base name is ROW-SCOPED when the form's own schema prints it with more than
one row letter; a summary box exists on one row only. Nothing is hand-listed, so
the rule holds for any prefix, any row set and any ACORD form added later. On
top of that, the client's literal clause is enforced directly: a ticked
"Check if none" never raises a loss-row requirement.

WHAT THESE TESTS GUARD
----------------------
* the client's reported case, replayed verbatim;
* that real claim data still demands its row (the fix must not silence the
  highlight it was built for);
* that the row/summary split is DERIVED from the real ACORD 125 schema, so a
  future schema change cannot quietly re-open the bug;
* fuzz over randomly generated field states built from the real schema - the
  client's documents can contain anything, so the properties are asserted over
  shapes nobody has seen, not over a fixture.

Run from backend/:
    python -m pytest tests/test_acord125_loss_row_required.py -v
"""

import os
import random
import string
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import pdf_service  # noqa: E402
from services.pdf_service import (  # noqa: E402
    _ACORD125_LOSS_ROW_FIELDS,
    _acord125_row_started,
    _all_form_schemas,
    _row_scoped_bases,
    _row_scoped_bases_from,
    apply_acord125_missing_field_highlights,
)

FORM = "ACORD_125"

TICK = "LossHistory_NoPriorLossesIndicator_A"
YEARS = "LossHistory_InformationYearCount_A"
TOTAL = "LossHistory_TotalAmount_A"
LOSS_SUMMARY_FIELDS = (TICK, YEARS, TOTAL)

LOSS_ROWS = ("A", "B", "C")


def _loss_row_fields(row):
    return {tmpl.format(row=row) for tmpl in _ACORD125_LOSS_ROW_FIELDS}


ALL_LOSS_ROW_FIELDS = {f for row in LOSS_ROWS for f in _loss_row_fields(row)}


def _schema_fields():
    schema = _all_form_schemas().get(FORM) or {}
    assert schema, "ACORD_125 schema did not load - these tests need the real form"
    return schema


def _state(**overrides):
    """A field state carrying every loss field on the real form, all blank."""
    state = {f: "" for f in ALL_LOSS_ROW_FIELDS}
    state.update({f: "" for f in LOSS_SUMMARY_FIELDS})
    state.update(overrides)
    return state


def _required(state):
    """The set of fields the highlighter marks missing_required."""
    conf = {k: "low_confidence" for k in state}
    out = apply_acord125_missing_field_highlights(FORM, {}, dict(state), conf)
    return {k for k, v in out.items() if v == "missing_required"}


# ── 1. The client's reported case, replayed verbatim ─────────────────────────

def test_ticking_check_if_none_requires_no_loss_row_field():
    """BUG-04. The client's literal sentence."""
    assert not (_required(_state(**{TICK: "Yes"})) & ALL_LOSS_ROW_FIELDS)


def test_the_screenshot_state_requires_no_loss_row_field():
    """The reported screen: box ticked, 'last 5 years' filled, TOTAL LOSSES $0."""
    state = _state(**{TICK: "Yes", YEARS: "5", TOTAL: "0"})
    assert not (_required(state) & ALL_LOSS_ROW_FIELDS)


def test_ticking_the_box_never_adds_a_required_field():
    """Attesting NO losses must never make the form read as MORE incomplete.

    This is the measured before/after: 2 required -> 7 required, all seven of
    them cells of a claim that does not exist."""
    before = _required(_state())
    after = _required(_state(**{TICK: "Yes"}))
    assert after <= before, sorted(after - before)


def test_a_tick_over_a_stray_cell_requires_nothing():
    """The client's clause is enforced directly, not only as a side effect of
    the row-scoping fix: a tick sitting over a cell gap fill left behind still
    raises no requirement. The contradiction is priced by the loss-history
    conflict cap and surfaced as its own warning - a yellow box is the wrong
    place to argue it."""
    state = _state(**{TICK: "Yes", "LossHistory_OccurrenceDate_A": "03/14/2024"})
    assert not (_required(state) & ALL_LOSS_ROW_FIELDS)


@pytest.mark.parametrize("summary_field", LOSS_SUMMARY_FIELDS)
@pytest.mark.parametrize("value", ["Yes", "5", "0", "12500", "$1,200.00", "N/A"])
def test_no_summary_box_alone_starts_a_loss_row(summary_field, value):
    """None of the three section boxes is a claim row, whatever it holds."""
    assert not (_required(_state(**{summary_field: value})) & ALL_LOSS_ROW_FIELDS)


# ── 2. The highlight it was built for still fires ────────────────────────────

def test_a_real_claim_still_requires_the_rest_of_its_row():
    required = _required(_state(**{"LossHistory_OccurrenceDate_A": "03/14/2024"}))
    expected = _loss_row_fields("A") - {"LossHistory_OccurrenceDate_A"}
    assert expected <= required


def test_a_started_row_does_not_start_the_others():
    required = _required(_state(**{"LossHistory_PaidAmount_B": "5000"}))
    assert _loss_row_fields("B") - {"LossHistory_PaidAmount_B"} <= required
    assert not (required & _loss_row_fields("C"))


def test_an_empty_loss_section_still_asks_for_the_attestation():
    """The genuinely incomplete state must keep its prompt."""
    assert TICK in _required(_state())


def test_each_row_is_judged_on_its_own_cells():
    state = _state(**{
        "LossHistory_OccurrenceDate_A": "03/14/2024",
        "LossHistory_PaidAmount_C": "900",
    })
    required = _required(state)
    assert _loss_row_fields("A") - {"LossHistory_OccurrenceDate_A"} <= required
    assert _loss_row_fields("C") - {"LossHistory_PaidAmount_C"} <= required
    assert not (required & _loss_row_fields("B"))


# ── 3. The split is DERIVED from the real schema, not hand-listed ────────────

def test_the_three_loss_summary_boxes_are_classed_as_summaries():
    bases = _row_scoped_bases(FORM)
    for field in LOSS_SUMMARY_FIELDS:
        assert field.rsplit("_", 1)[0] not in bases, field


def test_every_loss_row_column_is_classed_as_row_scoped():
    bases = _row_scoped_bases(FORM)
    for tmpl in _ACORD125_LOSS_ROW_FIELDS:
        base = tmpl.format(row="A").rsplit("_", 1)[0]
        assert base in bases, base


def test_every_managed_loss_row_field_exists_on_the_real_form():
    """A template naming a field ACORD does not print can never be satisfied."""
    schema = _schema_fields()
    for field in ALL_LOSS_ROW_FIELDS:
        assert field in schema, field


def test_the_rule_is_derivation_not_a_list():
    """The row/summary split must come out of the schema alone.

    Recomputed here from the raw field names with an independent implementation:
    if `_row_scoped_bases` ever becomes a hand-maintained list this diverges."""
    schema = _schema_fields()
    independent = set()
    seen = {}
    for name in schema:
        base, _, row = name.rpartition("_")
        if base and row and row.isupper() and row.isalpha() and len(row) <= 2:
            seen.setdefault(base, set()).add(row)
    independent = {b for b, rows in seen.items() if len(rows) > 1}
    assert set(_row_scoped_bases(FORM)) == independent


# ── 4. Generic: the rule holds for every prefix the highlighter uses ─────────

@pytest.mark.parametrize("prefix", ["LossHistory", "NamedInsured",
                                    "CommercialStructure", "BuildingOccupancy"])
def test_a_singleton_box_never_starts_a_row_for_any_prefix(prefix):
    """Computed off the real schema - no prefix has a hand-tuned exception."""
    schema = _schema_fields()
    bases = _row_scoped_bases(FORM)
    singles = [
        n for n in schema
        if n.startswith(prefix + "_")
        and n.rsplit("_", 1)[0] not in bases
        and n.rsplit("_", 1)[1].isupper() and n.rsplit("_", 1)[1].isalpha()
    ]
    for name in singles:
        row = name.rsplit("_", 1)[1]
        assert not _acord125_row_started({name: "something"}, prefix, row), name


@pytest.mark.parametrize("prefix", ["LossHistory", "NamedInsured",
                                    "CommercialStructure", "BuildingOccupancy"])
def test_a_real_row_cell_always_starts_its_row_for_any_prefix(prefix):
    schema = _schema_fields()
    bases = _row_scoped_bases(FORM)
    cells = [
        n for n in schema
        if n.startswith(prefix + "_") and n.rsplit("_", 1)[0] in bases
    ]
    assert cells, prefix
    for name in cells:
        row = name.rsplit("_", 1)[1]
        assert _acord125_row_started({name: "something"}, prefix, row), name


def test_a_blank_or_off_cell_does_not_start_a_row():
    for blank in ("", "   ", "null", "None", "Off", "No", "false", "0", None):
        assert not _acord125_row_started(
            {"LossHistory_OccurrenceDate_A": blank}, "LossHistory", "A")


# ── 5. Degradation: the schema is a source of truth, never a dependency ──────

def test_it_falls_back_to_the_payload_when_the_schema_is_unreadable(monkeypatch):
    """An unreadable schema must degrade, never raise, and never re-open BUG-04
    on a payload that carries the rows."""
    monkeypatch.setattr(pdf_service, "_all_form_schemas", lambda: {})
    _row_scoped_bases.cache_clear()
    try:
        state = _state(**{TICK: "Yes", YEARS: "5", TOTAL: "0"})
        assert not (_required(state) & ALL_LOSS_ROW_FIELDS)
        assert _acord125_row_started(
            {**{f: "" for f in ALL_LOSS_ROW_FIELDS},
             "LossHistory_OccurrenceDate_A": "03/14/2024"}, "LossHistory", "A")
    finally:
        _row_scoped_bases.cache_clear()


def test_row_scoped_bases_from_is_total():
    """It is fed raw payload keys, so it must survive anything."""
    for names in ([], {}, [""], ["_A"], ["A"], ["x_A", "x_B"], [None], [123],
                  ["a_b_c_A", "a_b_c_B"], ["é_A", "é_B"], ["_"], ["__A"]):
        assert isinstance(_row_scoped_bases_from(names), frozenset)
    assert "x" in _row_scoped_bases_from(["x_A", "x_B"])
    assert "x" not in _row_scoped_bases_from(["x_A"])


def test_a_non_acord125_form_is_untouched():
    conf = {TICK: "low_confidence"}
    assert apply_acord125_missing_field_highlights(
        "ACORD_130", {}, {TICK: ""}, dict(conf)) == conf


# ── 6. Fuzz - the client's documents can contain anything ────────────────────

_JUNK_VALUES = [
    "", "   ", None, "null", "None", "Off", "No", "N/A", "n/a", "0", "0.00",
    "$0", "Yes", "yes", "TRUE", "see attached", "-", "—", "unknown", "TBD",
    "03/14/2024", "5", "12500", "$1,200.00", 0, 1, True, False, 12.5,
    "éàü", "a" * 400, "\n\t", "<script>", "'; DROP TABLE",
]


def _random_state(rng, schema_names):
    """A field state built from REAL field names with arbitrary values, plus
    keys the schema does not carry (extraction and gap fill both invent some)."""
    state = {}
    for name in rng.sample(schema_names, rng.randint(0, min(60, len(schema_names)))):
        state[name] = rng.choice(_JUNK_VALUES)
    for _ in range(rng.randint(0, 6)):
        junk = "".join(rng.choice(string.ascii_letters + "_") for _ in range(rng.randint(1, 20)))
        state[junk] = rng.choice(_JUNK_VALUES)
    return state


def _real_loss_cells():
    """Every ROW-SCOPED LossHistory cell the real form prints.

    Derived from the schema, deliberately NOT from `_ACORD125_LOSS_ROW_FIELDS` -
    that constant is the subset the highlighter MANAGES, and ACORD prints more
    columns than that (e.g. `LossHistory_ClaimStatus_SubrogationCode_*`). An
    oracle built from the managed list calls a correct "row started" a false
    positive; this one asks the form."""
    bases = _row_scoped_bases(FORM)
    return {
        n for n in _schema_fields()
        if n.startswith("LossHistory_") and n.rsplit("_", 1)[0] in bases
    }


def _has_real_claim_cell(state):
    return any(
        f in state and state[f] is not None
        and str(state[f]).strip() not in ("", "null", "None", "Off", "No", "false", "0")
        for f in _real_loss_cells()
    )


def test_fuzz_a_tick_never_requires_a_loss_row_cell():
    """THE PROPERTY, over 4,000 unseen shapes: whenever "Check if none" is
    ticked, no loss-row cell is ever marked required - with or without stray
    data anywhere else on the form."""
    rng = random.Random(20260908)
    names = sorted(_schema_fields())
    for _ in range(4000):
        state = _random_state(rng, names)
        state[TICK] = rng.choice(["Yes", "yes", "Y", "true", "1", "on", "On"])
        assert not (_required(state) & ALL_LOSS_ROW_FIELDS), state


def test_fuzz_never_raises_and_never_invents_a_field():
    """Total function: any shape in, a dict out, no key created that the caller
    did not already carry, and no field with a value called missing."""
    rng = random.Random(7)
    names = sorted(_schema_fields())
    for _ in range(4000):
        state = _random_state(rng, names)
        conf = {k: rng.choice(["filled", "low_confidence", "ai_high", "missing_required"])
                for k in state if rng.random() < 0.8}
        known = set(state) | set(conf)
        out = apply_acord125_missing_field_highlights(FORM, {}, dict(state), dict(conf))
        assert isinstance(out, dict)
        assert set(out) <= known
        for field, label in out.items():
            # Only judge labels THIS function produced. A caller's own stale
            # missing_required on a field it does not manage is passed through
            # untouched, by design.
            if label == "missing_required" and conf.get(field) != "missing_required":
                val = state.get(field)
                assert val is None or str(val).strip() in (
                    "", "null", "None", "Off", "No", "false", "0"), (field, val)


def test_fuzz_a_started_row_is_always_a_real_cell():
    """The inverse property: a loss row is only ever required because a genuine
    claim CELL carries a value - never because a summary box does."""
    rng = random.Random(99)
    names = sorted(_schema_fields())
    for _ in range(4000):
        state = _random_state(rng, names)
        state.pop(TICK, None)
        if _required(state) & ALL_LOSS_ROW_FIELDS:
            assert _has_real_claim_cell(state), state


def test_fuzz_an_empty_input_is_safe():
    for state in ({}, {TICK: None}, {"": ""}, {None: None}):
        try:
            out = apply_acord125_missing_field_highlights(FORM, {}, dict(state), {})
        except Exception as exc:                                  # noqa: BLE001
            pytest.fail(f"raised on {state!r}: {exc}")
        assert isinstance(out, dict)
