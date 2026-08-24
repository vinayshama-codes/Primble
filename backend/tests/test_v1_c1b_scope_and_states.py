"""V1 C1b - client 1.2's ITEM scope and client 1.3's two unwritten value states.

Two gaps closed together, because both are the same shape: the fact layer could
not express something the client's spec requires.

  1.2  "a fact should retain scope such as: ... location; vehicle/property/item"
       The picker's only scope axis was the POLICY, so a package with two
       BUILDINGS raised a Data Consistency question for every column where the
       buildings legitimately differ.

  1.3  `not_applicable` and `unable_to_determine` were declared and derivable
       but nothing in the pipeline ever produced either one, so every blank
       fact read `not_stated` whatever the reason for the blank.

EVERY TEST DRIVES REAL CODE. No local reimplementation of a rule - a copy of
production logic in a test only proves the copy is self-consistent (C23 round 1
learned this the hard way).
"""
import pytest

from services.fact_comparison import build_context
from services.underwriting_consistency import _scope_values
from services.fact_state import (
    value_state_of, is_not_applicable, denied_lines, rejection_reason,
    NOT_APPLICABLE, UNABLE_TO_DETERMINE, NOT_STATED, PRESENT, EXPLICIT_NO,
    CONFLICTING, REJECTED_FACTS_KEY,
)
from services.lob_canon import denied_families, denies_coverage


def _g(display, raw=None):
    return {"display": display, "sources": [{"raw": raw or display}]}


TWO_BUILDINGS = {"property_locations": [
    {"address": "100 Main St", "year_built": "1998",
     "construction_type": "Frame", "building_value": "$500,000"},
    {"address": "200 Oak Ave", "year_built": "2014",
     "construction_type": "Masonry", "building_value": "$750,000"},
]}

# The client's real package: two contracts, and the umbrella limit printed
# differently by the dec page and the certificate.
TWO_POLICIES = {"coverage_lines": [
    {"line": "General Liability", "policy_number": "BBC7263-26",
     "carrier": "EMC P&C", "premium": "$4,250"},
    {"line": "Commercial Liability Umbrella", "policy_number": "6J7-40-02---26",
     "carrier": "Employers Mutual", "premium": "$3,418"},
]}

PROPERTY_DECLINED = {"coverage_lines": [
    {"line": "Commercial Property", "premium": "No Coverage"},
    {"line": "General Liability", "premium": "$4,250"},
]}


# --------------------------- 1.2  ITEM SCOPE -------------------------------

@pytest.mark.parametrize("fact_key,a,b", [
    ("year_built",        "1998",     "2014"),
    ("construction_type", "Frame",    "Masonry"),
    ("building_value",    "$500,000", "$750,000"),
])
def test_two_buildings_are_two_facts_not_a_conflict(fact_key, a, b):
    """The whole point: a column where two premises legitimately differ."""
    ctx = build_context(TWO_BUILDINGS, [])
    scoped, _ = _scope_values(fact_key, [_g(a), _g(b)], ctx)
    assert scoped is True


def test_scoped_groups_carry_the_row_they_belong_to():
    """Client 1.5: retain each under its correct scope - retain means say WHICH."""
    ctx = build_context(TWO_BUILDINGS, [])
    groups = [_g("1998"), _g("2014")]
    scoped, _ = _scope_values("year_built", groups, ctx)
    assert scoped is True
    assert groups[0]["scope"] == ["property_locations#0"]
    assert groups[1]["scope"] == ["property_locations#1"]


def test_the_umbrella_conflict_survives_item_scope():
    """THE GATE. The client praised this conflict; B14 silenced it once already.

    `umbrella_limit` is not a column in any schedule, so gate 1 refuses it
    whatever the amounts happen to coincide with.
    """
    ctx = build_context(TWO_POLICIES, [])
    scoped, _ = _scope_values(
        "umbrella_limit", [_g("$3,000,000"), _g("$1,000,000")], ctx)
    assert scoped is False


def test_a_package_level_fact_never_item_scopes():
    """Gate 1 is EXACT-name, never a suffix: `total_payroll` must not ride in on
    `payroll` being a wc_class_codes column. The package total is not per-class."""
    ctx = build_context(TWO_BUILDINGS, [])
    scoped, _ = _scope_values("total_payroll", [_g("1998"), _g("2014")], ctx)
    assert scoped is False


def test_a_real_disagreement_about_ONE_building_still_surfaces():
    """Gate 2 needs BOTH sides attributable to a row. A value no row prints is a
    rival answer about the building we do have, not a second building."""
    ctx = build_context(TWO_BUILDINGS, [])
    scoped, _ = _scope_values("year_built", [_g("1998"), _g("2020")], ctx)
    assert scoped is False


def test_two_values_from_the_SAME_row_are_never_scoped():
    ctx = build_context(TWO_BUILDINGS, [])
    scoped, _ = _scope_values(
        "year_built", [_g("1998"), _g("100 Main St")], ctx)
    assert scoped is False


def test_one_row_cannot_separate_two_values():
    ctx = build_context({"property_locations": [{"year_built": "1998"}]}, [])
    scoped, _ = _scope_values("year_built", [_g("1998"), _g("2014")], ctx)
    assert scoped is False


def test_contract_indexes_are_not_item_schedules():
    """`coverage_lines` / `dec_page_entries` carry contract identity, so they
    belong to the POLICY axis with its own overlap rules. Letting them build
    item scope would give `policy_number` a second, weaker route that bypasses
    the "two policies on the same coverage line" check."""
    ctx = build_context({
        "coverage_lines": TWO_POLICIES["coverage_lines"],
        "dec_page_entries": [
            {"label": "Premium", "value": "$4,250",
             "policy_number": "BBC7263-26", "line_of_business": "General Liability"},
            {"label": "Premium", "value": "$3,418",
             "policy_number": "6J7-40-02---26", "line_of_business": "Umbrella"},
        ],
    }, [])
    assert ctx.item_columns == set()
    assert ctx.is_item_scoped_fact("policy_number") is False
    assert ctx.is_multi_contract is True        # the policy axis is untouched


def test_item_scope_works_on_a_single_policy_package():
    """Two buildings on ONE policy is the ordinary case. An earlier cut put the
    item branch behind `is_multi_contract` and made it unreachable there."""
    ctx = build_context(TWO_BUILDINGS, [])
    assert ctx.is_multi_contract is False
    scoped, _ = _scope_values("year_built", [_g("1998"), _g("2014")], ctx)
    assert scoped is True


@pytest.mark.parametrize("facts", [None, {}, {"property_locations": "not a list"},
                                   {"property_locations": [None, None]}])
def test_item_scope_fails_closed_on_junk(facts):
    ctx = build_context(facts, [])
    scoped, _ = _scope_values("year_built", [_g("1998"), _g("2014")], ctx)
    assert scoped is False


def test_no_context_keeps_todays_behaviour():
    scoped, _ = _scope_values("year_built", [_g("1998"), _g("2014")], None)
    assert scoped is False


# ------------------------- 1.3  NOT APPLICABLE -----------------------------

def test_a_declined_line_makes_its_facts_not_applicable():
    assert is_not_applicable(PROPERTY_DECLINED, "property_building_value")
    assert value_state_of(PROPERTY_DECLINED, "year_built") == NOT_APPLICABLE


def test_a_value_that_exists_always_beats_a_declined_line():
    facts = dict(PROPERTY_DECLINED,
                 property_building_value={"value": "$500,000"})
    assert value_state_of(facts, "property_building_value") == PRESENT


def test_two_sources_disagreeing_about_coverage_is_a_conflict_not_not_applicable():
    """Client 1.7's acceptance criterion. A denial is withdrawn the moment any
    entry GRANTS the same family - that is a question for the producer."""
    facts = {"coverage_lines": PROPERTY_DECLINED["coverage_lines"] +
             [{"line": "Property", "limit": "$900,000"}]}
    assert denied_families(facts["coverage_lines"]) == frozenset()
    assert value_state_of(facts, "property_building_value") == NOT_STATED


def test_a_package_level_fact_is_never_not_applicable():
    """`fact_line` returns None for anything that also reaches ACORD 125/101,
    so package identity survives any section being declined."""
    for key in ("policy_number", "applicant_name", "mailing_address"):
        assert value_state_of(PROPERTY_DECLINED, key) == NOT_STATED


def test_a_line_that_is_granted_is_not_not_applicable():
    assert value_state_of(PROPERTY_DECLINED, "gl_each_occurrence") == NOT_STATED


def test_unmapped_terminology_gets_no_opinion():
    """Client 1.7: do not automatically assume equivalence. Leave it unmapped."""
    facts = {"coverage_lines": [{"line": "Widget Floater", "premium": "No Coverage"}]}
    assert denied_families(facts["coverage_lines"]) == frozenset()
    assert value_state_of(facts, "property_building_value") == NOT_STATED


def test_the_line_NAME_can_never_deny_itself():
    """A carrier named '... Casualty - No Coverage Section' in the `line` field
    must not deny the line. Only detail columns carry a verdict."""
    assert denies_coverage({"line": "Property - No Coverage"}) is False
    assert denies_coverage({"premium": "No Coverage"}) is True


@pytest.mark.parametrize("facts", [None, {}, {"coverage_lines": "nope"},
                                   {"coverage_lines": [None, 3, "x"]}])
def test_not_applicable_fails_closed_on_junk(facts):
    assert denied_lines(facts) == frozenset()
    assert value_state_of(facts, "property_building_value") == NOT_STATED


# ---------------------- 1.3  UNABLE TO DETERMINE ---------------------------

def test_a_discarded_value_is_not_the_same_as_never_finding_one():
    facts = {REJECTED_FACTS_KEY: {
        "effective_date": "endorsement date, not an inception date"}}
    assert value_state_of(facts, "effective_date") == UNABLE_TO_DETERMINE
    assert "endorsement" in (rejection_reason("effective_date", facts) or "")
    # ...and a fact nobody rejected is still plain silence.
    assert value_state_of(facts, "expiration_date") == NOT_STATED


def test_a_later_document_supplying_a_value_clears_it():
    facts = {REJECTED_FACTS_KEY: {"effective_date": "x"},
             "effective_date": {"value": "07/15/2026"}}
    assert value_state_of(facts, "effective_date") == PRESENT


def test_not_applicable_outranks_unable_to_determine():
    """If the coverage is not carried, the field does not apply - whatever we
    tried and failed to read for it."""
    facts = dict(PROPERTY_DECLINED,
                 **{REJECTED_FACTS_KEY: {"property_building_value": "x"}})
    assert value_state_of(facts, "property_building_value") == NOT_APPLICABLE


def test_the_ledger_is_written_by_real_code_not_just_readable():
    """ANTI-ROT: a state whose only writer is a test is not a state."""
    from services.extraction_service import _record_fact_rejection
    mf = {}
    _record_fact_rejection(mf, "effective_date", "an endorsement date")
    assert value_state_of(mf, "effective_date") == UNABLE_TO_DETERMINE


def test_recording_a_rejection_never_raises():
    from services.extraction_service import _record_fact_rejection
    for bad in (None, "not a dict", 7):
        _record_fact_rejection(bad, "k", "r")          # must not raise


# -------------------- the states that already worked -----------------------

def test_the_existing_states_are_unchanged():
    assert value_state_of({"applicant_name": {"value": "ORBIN CONTRACTING LLC"}},
                          "applicant_name") == PRESENT
    assert value_state_of({"prior_losses": {"value": "no coverage"}},
                          "prior_losses") == EXPLICIT_NO
    assert value_state_of({"_uw_conflicted_keys": ["umbrella_limit"],
                           "umbrella_limit": {"value": "$3,000,000"}},
                          "umbrella_limit") == CONFLICTING
    # B8: a bare extracted False is silence, never an explicit No.
    assert value_state_of({"has_subcontractors": {"value": False}},
                          "has_subcontractors") == NOT_STATED


def test_there_is_one_definition_of_a_denial_phrase():
    """ANTI-ROT: the regex moved to the line leaf; extraction re-binds it."""
    from services.lob_canon import COVERAGE_DENIAL_RE
    from services.extraction_service import _COVERAGE_DENIAL_RE
    assert _COVERAGE_DENIAL_RE is COVERAGE_DENIAL_RE


# ------------ the questionnaire consumer, and its override ----------------

_NA_QUESTIONS = [
    {"field_name": "year_built",              "_canonical_key": "year_built"},
    {"field_name": "property_building_value", "_canonical_key": "property_building_value"},
    {"field_name": "applicant_name",          "_canonical_key": "applicant_name"},
    {"field_name": "gl_each_occurrence",      "_canonical_key": "gl_each_occurrence"},
]


def _ask(facts, form_ids):
    from services.arq_service import _drop_not_applicable_questions
    kept = _drop_not_applicable_questions(
        [dict(q) for q in _NA_QUESTIONS], facts, form_ids)
    return [q["field_name"] for q in kept]


def test_a_declined_line_stops_the_client_being_asked_about_it():
    """The real target: a package declining property was still asking for the
    building's year built off ACORD 125's premises grid."""
    kept = _ask(PROPERTY_DECLINED, ["ACORD_125", "ACORD_126"])
    assert "year_built" not in kept
    assert "property_building_value" not in kept
    assert "applicant_name" in kept and "gl_each_occurrence" in kept


def test_selecting_the_section_form_overrides_the_expiring_policy():
    """THE SAFETY CASE. `coverage_lines` is the EXPIRING policy on a renewal.
    A producer who selected ACORD 140 is applying for property NOW, and
    suppressing those questions would leave that form blank and unaskable."""
    assert _ask(PROPERTY_DECLINED, ["ACORD_125", "ACORD_140"]) == \
        [q["field_name"] for q in _NA_QUESTIONS]


def test_nothing_declined_changes_nothing():
    assert _ask({}, ["ACORD_125"]) == [q["field_name"] for q in _NA_QUESTIONS]


def test_a_missing_form_list_suppresses_nothing():
    """A filter that REMOVES questions must never act on an input it was not given."""
    assert _ask(PROPERTY_DECLINED, None) == [q["field_name"] for q in _NA_QUESTIONS]


def test_the_form_to_line_table_is_the_same_one_fact_line_uses():
    """ANTI-ROT: two tables mapping a form to a coverage line would drift, and
    the drift would show up as questions suppressed for the wrong line."""
    from services.arq_service import _lines_the_producer_is_applying_for as f
    assert f(["ACORD_140"]) == frozenset({"property"})
    assert f(["ACORD_127"]) == frozenset({"auto"})
    assert f(["ACORD_131"]) == frozenset({"umbrella"})
    assert f(["ACORD_125", "ACORD_101", "ACORD_25"]) == frozenset()
    assert f(None) == frozenset() and f([]) == frozenset()
