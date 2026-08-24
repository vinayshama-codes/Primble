"""Explicit No and the class-exposure filter are SCHEMA-DERIVED mechanisms,
not hand-typed tables (C1-Q FIX 10, 2026-08-24).

Client 1.3's "No subcontracting" was unreachable - no route existed at all.
The narrow fix would have been a THIRD hand-typed dict entry, one-off, tuned to
this fixture. The owner asked for the mechanism itself to be generic instead.

WHAT "GENERIC" MEANS HERE, PRECISELY - and what it does not:

  1. `ASSERTION_FLAG_NAMES` is auto-discovered from the schema by naming
     convention (`asserts_no_*`), mirroring `TRISTATE_BOOLEAN_FACTS`'s own
     `boolean or null` discovery. A new flag added under that convention is
     found automatically.
  2. WHICH FACT(S) an assertion is about cannot be derived - that is domain
     knowledge, not string shape - so `ABSENCE_ASSERTION_FLAGS` stays an
     explicit table. What makes it generic rather than ad hoc is that it is
     ONE centralised table with a BUILD-BREAKING anti-rot test: a flag can
     exist in the schema with no entry, or an entry can point at a flag that
     no longer exists, and either one fails the suite. Nobody can add the
     next "asserts_no_X" flag and forget to wire it.
  3. `_CLASS_EXPOSURE_COLUMNS` IS derived, from a schema selector
     (list field name contains "class") plus a reused classifier
     (`fact_equivalence._MONEY_TOKENS`) - not a blind "any money-shaped
     column" scan, which was tried, measured, and rejected: it swept in
     `dec_page_entries.value` (the PRIMARY EVIDENCE source other facts are
     backfilled FROM), `coverage_lines.premium` (owned by different, already-
     correct logic), and per-ITEM values that belong to C1b's item-scope axis.
     Those tests pin the exclusion, not just the inclusion.
"""
import re

import services.extraction_service as es
from services.fact_state import derive_value_state, EXPLICIT_NO, NOT_STATED, PRESENT

DOC = {"source": "policy_doc_text", "confidence": "deterministic"}


# ── 1. The new example actually works end to end ────────────────────────────

def test_no_subcontracting_is_explicit_no():
    """THE CLIENT'S SECOND NAMED EXAMPLE, unreachable before this fix."""
    facts = {"percent_subcontracted": {**DOC, "value": None},
             "_flags": {"asserts_no_subcontractors": True}}
    assert derive_value_state(
        "percent_subcontracted", facts["percent_subcontracted"], facts) == EXPLICIT_NO


def test_a_real_subcontracted_percentage_always_wins():
    facts = {"percent_subcontracted": {**DOC, "value": "25%"},
             "_flags": {"asserts_no_subcontractors": True}}
    assert derive_value_state(
        "percent_subcontracted", facts["percent_subcontracted"], facts) == PRESENT


def test_the_flag_being_false_asserts_nothing_for_subcontracting():
    facts = {"percent_subcontracted": {**DOC, "value": None},
             "_flags": {"asserts_no_subcontractors": False}}
    assert derive_value_state(
        "percent_subcontracted", facts["percent_subcontracted"], facts) == NOT_STATED


def test_losses_are_unaffected_by_adding_the_second_flag():
    facts = {"loss_history": {**DOC, "value": None},
             "_flags": {"asserts_no_known_losses": True}}
    assert derive_value_state(
        "loss_history", facts["loss_history"], facts) == EXPLICIT_NO


# ── 2. The discovery mechanism, not just its current output ─────────────────

def test_assertion_flag_names_are_discovered_not_hand_listed():
    """If this were a hand-typed set, adding a schema flag under the naming
    convention would silently NOT appear here. Prove it is regex-derived by
    checking it against a live re-scan, not against a frozen expectation."""
    expected = frozenset(re.findall(
        r'"(asserts_no_[a-z0-9_]*)":\s*boolean', es._EXTRACT_SCHEMA))
    assert es.ASSERTION_FLAG_NAMES == expected
    assert expected, "the schema declares no assertion flags - discovery is broken"


def test_every_assertion_flag_is_registered():
    """ANTI-ROT. A flag with no association table entry means the schema asks
    the model a question and nothing ever uses the answer - the exact defect
    that made 'No prior losses' unreachable before the first fix, now
    guaranteed not to happen silently for a second or third flag."""
    unregistered = es.ASSERTION_FLAG_NAMES - set(es.ABSENCE_ASSERTION_FLAGS)
    assert not unregistered, (
        f"schema declares assertion flag(s) with no table entry: "
        f"{sorted(unregistered)}. Add them to ABSENCE_ASSERTION_FLAGS.")


def test_every_registered_flag_still_exists_in_the_schema():
    """The mirror image: a table entry for a flag the schema no longer
    declares is a silent no-op, the same shape as D-1's dead code."""
    dead = set(es.ABSENCE_ASSERTION_FLAGS) - es.ASSERTION_FLAG_NAMES
    assert not dead, f"table entries for flag(s) not in the schema: {sorted(dead)}"


def test_every_asserted_fact_key_is_a_real_fact():
    """A mapping onto a key nothing produces is a silent no-op in the other
    direction - the assertion fires and nothing reads it."""
    from services.fact_registry import FACT_REGISTRY
    for flag, keys in es.ABSENCE_ASSERTION_FLAGS.items():
        for k in keys:
            assert k in FACT_REGISTRY or f'"{k}"' in es._EXTRACT_SCHEMA, (
                f"{flag} asserts about {k}, which nothing produces")


def test_the_harvester_would_catch_an_unwired_flag():
    """Self-check, C25-style: prove the anti-rot test above actually bites,
    by simulating the exact failure it exists to prevent - a schema-declared
    flag with no table entry."""
    fake_schema = es._EXTRACT_SCHEMA + ' "asserts_no_fictional_thing": boolean,'
    discovered = frozenset(re.findall(
        r'"(asserts_no_[a-z0-9_]*)":\s*boolean', fake_schema))
    unregistered = discovered - set(es.ABSENCE_ASSERTION_FLAGS)
    assert unregistered == {"asserts_no_fictional_thing"}


# ── 3. The class-exposure derivation, both what's in and what stays out ────

def test_the_two_known_class_schedules_are_derived():
    cols = es._CLASS_EXPOSURE_COLUMNS
    assert "gl_class_code_schedule" in cols
    assert "exposure_amount" in cols["gl_class_code_schedule"]
    assert cols.get("wc_class_codes") == ("payroll",)


def test_a_selector_scoped_to_class_schedules_not_any_money_column():
    """THE REJECTED DESIGN, proven rejected. A blind 'any list field with a
    money-shaped column' scan swept in fields that would have been actively
    wrong to suppress. `_CLASS_EXPOSURE_COLUMNS` must not include any of them."""
    cols = es._CLASS_EXPOSURE_COLUMNS
    assert "dec_page_entries" not in cols, (
        "dec_page_entries is the PRIMARY EVIDENCE source other facts are "
        "backfilled from - excluding its values would be destructive")
    assert "coverage_lines" not in cols, (
        "line premiums are owned by is_component_of, not this filter")
    assert "property_locations" not in cols
    assert "inland_marine_items" not in cols
    assert "underlying_policies" not in cols


def test_a_field_merely_containing_a_status_code_column_is_not_swept_in():
    """`loss_history.open_code` (O/C) is a STATUS code, not a rating
    classification - the selector keys on the FIELD name containing 'class',
    not on any column ending in '_code'."""
    assert "loss_history" not in es._CLASS_EXPOSURE_COLUMNS


def test_class_exposure_columns_reuses_the_existing_money_classifier():
    """Not a re-invented heuristic - the same _MONEY_TOKENS `gl_each_
    occurrence` and every other money field's `value_kind` already trusts."""
    import inspect
    src = inspect.getsource(es._discover_class_schedule_money_columns)
    assert "_MONEY_TOKENS" in src


def test_class_exposure_columns_is_non_empty():
    """C25 self-check: an empty derivation would make every filter test above
    pass vacuously."""
    assert es._CLASS_EXPOSURE_COLUMNS
