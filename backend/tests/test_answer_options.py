"""test_answer_options.py - the answer choices, and the guards that keep them honest.

Owner 2026-08-24: *"give all possible option that a user can think of
answering"*, modelled on the dismiss-reason dropdown. Free typing stays for
names, addresses, phones, emails, amounts, dates, codes and percentages.

The load-bearing property is the ROUND TRIP: the option text IS the stored
value, so every option must survive both the semantic layer and the normalizer
its fact already uses. An option that reads back as something else is worse
than no dropdown at all.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services.answer_options import (
    OTHER, attach_answer_controls, catalogued_facts, control_for,
    is_multi_select, options_for,
)
from services.answer_semantics import VALUE, interpret_answer

# The two genuinely binary questions. "Other" on "have you had claims - yes or
# no?" would be nonsense, so they are the documented exceptions to the rule.
_BINARY = {"loss_history_no_prior_losses_indicator", "new_venture_indicator"}


def test_the_catalogue_is_not_empty():
    assert len(catalogued_facts()) >= 18


@pytest.mark.parametrize("fact", catalogued_facts())
def test_every_option_round_trips_as_its_own_value(fact):
    """THE guard. A chosen option must be stored exactly as offered - never
    re-read as an absence ("No - all officers are included") or as a
    non-answer ("Not stated - underwriter review recommended")."""
    for opt in options_for(fact):
        if opt == OTHER:
            continue
        r = interpret_answer(fact, opt)
        assert r.intent == VALUE, f"{fact}: {opt!r} -> {r.intent} ({r.reason})"
        assert r.value == opt, f"{fact}: {opt!r} stored as {r.value!r}"


@pytest.mark.parametrize("fact", catalogued_facts())
def test_every_list_offers_an_escape(fact):
    if fact in _BINARY:
        pytest.skip("a genuinely binary question has no third answer")
    assert options_for(fact)[-1] == OTHER, f"{fact} traps an unusual answer"


@pytest.mark.parametrize("fact", catalogued_facts())
def test_options_are_readable_by_a_person(fact):
    for opt in options_for(fact):
        assert opt and opt[0].isupper() or opt[0].isdigit(), f"{fact}: {opt!r}"
        assert len(opt) <= 90, f"{fact}: {opt!r} is too long for a dropdown"
        assert "—" not in opt, "project rule: no em-dashes in UI copy"
        assert "_" not in opt, f"{fact}: {opt!r} looks like a schema token"


@pytest.mark.parametrize("fact", catalogued_facts())
def test_no_duplicate_options(fact):
    opts = options_for(fact)
    assert len(opts) == len(set(opts)), f"{fact} repeats an option"


# ── The options must survive the normalizer their fact already uses ─────────

def test_entity_type_options_normalize():
    from services.normalization import normalize_entity_type
    seen = {}
    for opt in options_for("entity_type"):
        if opt == OTHER:
            continue
        canon = normalize_entity_type(opt)
        assert canon, f"{opt!r} normalizes to nothing"
        assert canon not in seen, f"{opt!r} and {seen[canon]!r} collapse to {canon!r}"
        seen[canon] = opt


def test_valuation_method_options_normalize():
    from services.normalization import normalize_valuation_method
    assert normalize_valuation_method("Replacement Cost") == "rcv"
    assert normalize_valuation_method("Actual Cash Value") == "acv"
    for opt in options_for("valuation_method"):
        if opt != OTHER:
            assert normalize_valuation_method(opt), f"{opt!r} normalizes to nothing"


def test_loss_history_options_still_drive_the_pillar():
    """The catalogue must not have quietly reworded a control the scorer reads."""
    from services.loss_history_state import attested_true, new_venture_answer
    no_claims, had_claims = options_for("loss_history_no_prior_losses_indicator")
    assert attested_true(no_claims) is True
    assert attested_true(had_claims) is False
    yes_nv, no_nv = options_for("new_venture_indicator")
    assert new_venture_answer(yes_nv) is True
    assert new_venture_answer(no_nv) is False


def test_loss_run_status_options_parse():
    from services.loss_history_state import parse_loss_run_status
    parsed = [parse_loss_run_status(o) for o in options_for("loss_run_status")
              if o != OTHER]
    assert "pending" in parsed and "no_runs_available" in parsed


# ── Free text stays free text ───────────────────────────────────────────────

@pytest.mark.parametrize("fact,expected", [
    ("applicant_name", "text"), ("mailing_address", "text"),
    ("operations_description", "text"), ("prior_carrier", "text"),
    ("contact_email", "text"),
    ("total_revenue", "currency"), ("gl_each_occurrence", "currency"),
    ("effective_date", "date"), ("expiration_date", "date"),
    ("fein", "code"), ("naics_code", "code"), ("sic_code", "code"),
    ("num_employees", "number"), ("year_built", "number"),
    ("percent_subcontracted", "percent"),
])
def test_open_and_typed_fields_are_never_forced_into_a_dropdown(fact, expected):
    """Names, amounts, dates and codes cannot be enumerated - and carrier and
    class codes have universes in the thousands, where a dropdown would make
    "Other" the usual answer."""
    assert options_for(fact) is None
    assert control_for(fact) == expected


def test_multi_select_is_only_where_several_answers_are_real():
    multi = {f for f in catalogued_facts() if is_multi_select(f)}
    assert "lines_of_business" in multi
    assert "auto_covered_symbols" in multi
    assert "entity_type" not in multi, "a business has ONE legal form"
    assert "valuation_method" not in multi


# ── The cards actually carry the choices ────────────────────────────────────

def test_attach_answer_controls_stamps_cards():
    recs = [
        {"field": "valuation_method", "message": "Specify valuation"},
        {"field": "total_revenue", "message": "Provide revenue"},
        {"field": None, "message": "not answerable"},
        "a legacy string rec",
    ]
    gained = attach_answer_controls(recs)
    assert gained == 1
    assert recs[0]["answer_control"] == "select"
    assert recs[0]["answer_options"] == options_for("valuation_method")
    assert recs[1]["answer_control"] == "currency"
    assert "answer_options" not in recs[1], "an amount must stay free text"
    assert "answer_control" not in recs[2]


def test_the_per_form_scorer_ships_the_choices():
    """End to end: a recommendation the producer sees must carry its options."""
    from services.sqs_service import calculate_sqs
    res = calculate_sqs(
        facts={"applicant_name": "ACME LLC", "effective_date": "07/15/2026",
               "property_building_value": "500000", "locations": "1 Main St"},
        flags={"has_property_coverage": True},
        mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_140"], hard_stops=[], soft_stops=[],
        tier2_score=60, form_id="ACORD_140",
    )
    answerable = [r for r in res["recommendations"] if r.get("field")]
    assert answerable, "fixture must produce at least one answerable card"
    assert all("answer_control" in r for r in answerable)
    catalogued = [r for r in answerable if r["field"] in catalogued_facts()]
    for r in catalogued:
        assert r.get("answer_options"), f"{r['field']} card has no choices"


def test_questionnaire_upgrades_a_free_text_question_to_choices():
    from services.arq_service import _attach_answer_options
    qs = [
        {"field_name": "valuation_method", "_canonical_key": "valuation_method",
         "field_type": "text"},
        {"field_name": "total_revenue", "_canonical_key": "total_revenue",
         "field_type": "currency"},
        {"field_name": "loss_history_no_prior_losses_indicator",
         "_canonical_key": "loss_history_no_prior_losses_indicator",
         "field_type": "select", "options": ["already", "curated"]},
    ]
    assert _attach_answer_options(qs) == 1
    assert qs[0]["field_type"] == "select"
    assert qs[0]["options"] == options_for("valuation_method")
    assert qs[1]["field_type"] == "currency", "an amount stays a typed input"
    assert qs[2]["options"] == ["already", "curated"], "curated control untouched"


# ── Hard stops and warnings get the same choices (C2-I) ─────────────────────

def test_every_field_mode_resolution_carries_controls():
    """A hard stop or warning resolved inline must offer the same choices a
    recommendation card does - it used to render a bare text box for every
    fact. Attached in `_copy_resolution`, the one function every resolution
    (RESOLUTION_MAP, tier-1, legacy fallback) is copied through."""
    from services.issue_registry import RESOLUTION_MAP, resolution_for
    checked = 0
    for code, res in RESOLUTION_MAP.items():
        if res.get("mode") != "field":
            continue
        live = resolution_for(code)
        assert live and "controls" in live, f"{code} has no answer controls"
        for fact in live["facts"]:
            ctl = live["controls"].get(fact)
            assert ctl and ctl.get("control"), f"{code}/{fact} has no control"
            if options_for(fact):
                assert ctl.get("options") == options_for(fact), f"{code}/{fact}"
        checked += 1
    assert checked >= 25, f"only {checked} field-mode resolutions checked"


def test_a_tier1_resolution_also_carries_controls():
    from services.issue_registry import resolution_for
    res = resolution_for("tier1_missing_Business entity type")
    if res and res.get("mode") == "field":
        assert res.get("controls")
        assert res["controls"]["entity_type"]["options"] == options_for("entity_type")


def test_cope_hard_stop_offers_real_choices():
    """The client's own reported case: 'Minimum Viable COPE incomplete' now
    offers occupancy and construction as lists, and the two values as typed
    money inputs - no guessing at wording."""
    from services.issue_registry import resolution_for
    ctl = resolution_for("minimum_viable_cope_missing")["controls"]
    assert ctl["occupancy_type"]["control"] == "select"
    assert ctl["construction_type"]["control"] == "select"
    assert ctl["property_building_value"]["control"] == "currency"
    assert "options" not in ctl["property_building_value"]
