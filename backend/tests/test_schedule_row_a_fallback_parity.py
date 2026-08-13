"""THREE FUNCTIONS RESOLVE PASS 1, AND ONLY ONE OF THEM HAD THE FALLBACK.

Scored the live 2026-08-14 ACORD 125 against `tests/fixtures/orbin_ground_truth.json`
and found the per-premises DESCRIPTION OF OPERATIONS **blank**, one day after a
rule was added specifically to fill it from `operations_description`. The rule
worked - in `_deterministic_map`. It did nothing in the two functions that
actually build the form, because both call `_resolve_schedule_row` FIRST and
`continue` on its answer, so Pass 1 is never consulted for a schedule-backed
field.

The trap is in what `None` means from `_resolve_schedule_row` at row A. The
comment on `_deterministic_map`'s fallback claims it happens "if and only if
the schedule's list is COMPLETELY EMPTY". That is wrong, and this package
proves it: `property_locations` has ONE entry, and that entry carries no
`operations_description` key - so row A answers None with a non-empty list.
The scalar fact was sitting right there and never got asked for.

This is the same class of defect the `compute_form_gaps` docstring already
records ("the docstring claimed this function 'mirrors exactly'"). The fix
mirrors the fallback into both call sites; these tests keep them mirrored.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")
_F = "BuildingOccupancy_OperationsDescription_A"
_OPS = ("Contractors - Executive Supervisors or Executive Superintendents; "
        "contractors-sub work-in connection with construction, reconstruction, "
        "repair, erection of buildings - NOC.")
# ONE location, and it carries no per-location description - the live shape.
_FACTS = {
    "property_locations": [{"street": "4800 Dahlia St # D13", "city": "Denver",
                            "state": "CO", "zip": "80216-3121"}],
    "operations_description": _OPS,
}


@pytest.fixture(scope="module")
def schema125():
    with open(os.path.join(BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def test_the_premise_of_the_old_comment_is_false():
    """Row A answers None with a NON-EMPTY list whenever row 1 has no value for
    that column. Pinned because the wrong belief is what scoped the fallback
    too narrowly to be reached."""
    assert ps._resolve_schedule_row(_F, _FACTS) is None
    assert len(_FACTS["property_locations"]) == 1


def test_all_three_pass_1_resolvers_agree(schema125):
    """The actual regression: three entry points, one answer."""
    direct = ps._deterministic_map(_F, _FACTS)
    gaps, _u, _d = ps.compute_form_gaps("ACORD_125", schema125, _FACTS)
    mapped, _c = ps.map_facts_to_form(
        _FACTS, schema125, "ACORD_125", raw_text=_OPS,
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    assert direct == _OPS
    assert gaps.get(_F) == _OPS, "compute_form_gaps short-circuited Pass 1"
    assert mapped.get(_F) == _OPS, "map_facts_to_form short-circuited Pass 1"


def test_the_fallback_costs_no_extra_gap_fill_questions(schema125):
    """It must NOT push the field into `unmatched`. An empty schedule cell with
    no scalar rule stays a deterministic blank exactly as before - the fix buys
    a value, never an LLM question."""
    _m, unmatched, det = ps.compute_form_gaps("ACORD_125", schema125, _FACTS)
    assert _F not in unmatched
    assert _F in det
    # ...and a schedule column with no scalar rule behind it is still blank and
    # still not asked.
    other = "Construction_BuildingArea_A"
    if other in schema125:
        assert other not in unmatched


def test_rows_beyond_the_schedule_stay_blank(schema125):
    """Scoped to row A. A second premises we do not have must not inherit the
    package-level description."""
    mapped, _c = ps.map_facts_to_form(
        _FACTS, schema125, "ACORD_125", raw_text=_OPS,
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    for row in ("B", "C", "D"):
        f = f"BuildingOccupancy_OperationsDescription_{row}"
        assert mapped.get(f) is None, f


def test_a_genuine_per_location_description_still_wins(schema125):
    """The schedule is the better source when it HAS the value - the fallback
    must never override real per-location data."""
    facts = {
        "property_locations": [
            {"street": "4800 Dahlia St # D13",
             "operations_description": "Equipment yard and office"},
            {"street": "1200 Industrial Way",
             "operations_description": "Fabrication shop"},
        ],
        "operations_description": _OPS,
    }
    mapped, _c = ps.map_facts_to_form(
        facts, schema125, "ACORD_125", raw_text=_OPS,
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    assert mapped.get(_F) == "Equipment yard and office"
    assert mapped.get("BuildingOccupancy_OperationsDescription_B") == \
        "Fabrication shop"


def test_both_call_sites_still_carry_the_fallback():
    """ANTI-ROT. Two `_resolve_schedule_row` call sites build forms; a refactor
    that drops the fallback from either one reintroduces a defect that is
    invisible to `_deterministic_map`'s own tests."""
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    sites = [m.start() for m in
             re.finditer(r"sched = _resolve_schedule_row\(field, facts\)", src)]
    assert len(sites) == 2, f"{len(sites)} schedule call sites - expected 2"
    for start in sites:
        body = src[start:start + 1800]
        assert 'field.endswith("_A")' in body and "_deterministic_map(field, facts)" in body, (
            "a schedule branch short-circuits Pass 1 again - the row-A scalar "
            "fallback is missing from one of the two form builders")


# ── The ACORD codes I wrongly called invented, pinned as correct ─────────────

def test_payment_plan_and_audit_codes_are_acords_own(schema125):
    """PAYMENT PLAN "AN" and AUDIT "A" were flagged as two-letter junk in an
    earlier audit. They are not: ACORD's own tooltip enumerates them. Recorded
    so nobody "fixes" a correct value."""
    tu = schema125["Policy_Payment_PaymentScheduleCode_A"]["tu"]
    assert "AN - Annual" in tu
    assert ps._tooltip_declared_type(
        schema125["Policy_Payment_PaymentScheduleCode_A"]) == "code"
    assert not ps._rejects_declared_type(
        "Policy_Payment_PaymentScheduleCode_A",
        schema125["Policy_Payment_PaymentScheduleCode_A"], "AN")
    assert not ps._rejects_declared_type(
        "Policy_Audit_FrequencyCode_A",
        schema125["Policy_Audit_FrequencyCode_A"], "A")
