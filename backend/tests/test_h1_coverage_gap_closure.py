"""test_h1_coverage_gap_closure.py - V1 H1, client section 6 (2026-08-26).

Client 6.3 / 6.4: "A materially incomplete submission should receive an
appropriately weaker total SQS regardless of which ACORD form contains the
missing information." Every test here drives the REAL scorers, the real
ceiling engine, the real fact-state axis and the real stamper - never a copy
of the rule - and every fixture is the LIVE shape the writers produce (D22).

Sections:
  1. auto_exposure_kind - owned / HNOA-only / none / unknown, positive evidence only
  2. the five 6.3 deductions, the -25 cap, and the two "+ Warning" items
  3. the three 6.4 items, the -10 cap, UNKNOWN -> producer with no deduction
  4. the buckets reach the pillar, the trace and the breakdown, and never touch
     a Tier 2 fact (no double count)
  5. the questionnaire: HNOA-only suppresses owned-vehicle questions
  6. the edit path: a coverage flag is dropped only when NO evidence remains
  7. derived facts from the declarations index survive the purge
  8. the phantom keys the H1 audit found and fixed
  9. the vehicle-use fact reaches the ACORD 127 USE column
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import coverage_evidence as ce                     # noqa: E402
from services import sqs_service as sq                           # noqa: E402

AUTO = {"has_auto_coverage": True}
WC = {"has_workers_comp": True}
GL = {"has_general_liability": True}

VEHICLES = [
    {"year": "2021", "make": "Ford", "model": "F-150", "vin": "1FTFW1ET5DFC10312"},
    {"year": "2019", "make": "Ram", "model": "2500", "vin": "3C6UR5DL5KG512345"},
]
DRIVERS = [{"name": "Jane Smith", "license_number": "D1234567", "license_state": "TX"}]


def _sym(*nums, coverage="liability"):
    return [{"coverage": coverage, "symbols": list(nums)}]


def _human(value, state=None):
    env = {"value": value, "confidence": "filled", "source": "producer"}
    if state:
        env["value_state"] = state
    return env


# ── 1. Owned versus hired/non-owned ───────────────────────────────────────────

@pytest.mark.parametrize("facts,flags,expected,why", [
    ({}, {}, ce.AUTO_NONE, "no auto line"),
    ({}, AUTO, ce.AUTO_UNKNOWN, "an auto line and nothing else - unknown, not owned"),
    ({"auto_vin_schedule": VEHICLES}, AUTO, ce.AUTO_OWNED, "a vehicle schedule is owned"),
    ({"auto_covered_symbols": _sym(1)}, AUTO, ce.AUTO_OWNED, "symbol 1 designates owned autos"),
    ({"auto_covered_symbols": _sym(7)}, AUTO, ce.AUTO_OWNED, "symbol 7 = specifically described (scheduled)"),
    ({"auto_covered_symbols": _sym(7, coverage="comprehensive")}, AUTO, ce.AUTO_OWNED,
     "a physical-damage symbol alone still says the account owns what it insures"),
    ({}, {"has_auto_coverage": True, "auto_has_physical_damage": True}, ce.AUTO_OWNED,
     "comp/collision on the policy - nobody insures a non-owned car against collision"),
    ({"auto_deductible_collision": "$1,000"}, AUTO, ce.AUTO_OWNED, "a collision deductible"),
    ({"auto_garaging_addresses": ["1450 Lantern Court, Columbus OH 43215"]}, AUTO, ce.AUTO_OWNED,
     "only an owned fleet is garaged"),
    ({"auto_covered_symbols": _sym(8, 9)}, AUTO, ce.AUTO_HNOA_ONLY, "8 and 9 alone - the classic HNOA-only shape"),
    ({"auto_covered_symbols": _sym(9)}, AUTO, ce.AUTO_HNOA_ONLY, "non-owned only"),
    ({"auto_vin_schedule": _human("", "explicit_no")}, AUTO, ce.AUTO_HNOA_ONLY,
     "a human recorded 'no owned vehicles'"),
    ({"auto_covered_symbols": _sym(1, 8, 9)}, AUTO, ce.AUTO_OWNED,
     "1 with 8 and 9 is an owned fleet that ALSO covers hired/non-owned"),
    ({"auto_vin_schedule": VEHICLES, "auto_covered_symbols": _sym(8, 9)}, AUTO, ce.AUTO_OWNED,
     "a real schedule outranks an HNOA symbol (that mismatch is the owned-fleet hard stop's job)"),
    ({"auto_covered_symbols": _sym(5)}, AUTO, ce.AUTO_UNKNOWN,
     "an unrecognised symbol says nothing either way"),
    ({"auto_hired_nonowned": "yes"}, AUTO, ce.AUTO_UNKNOWN,
     "'employees drive rented cars' does NOT mean HNOA-only - most owned fleets carry HNOA too"),
])
def test_auto_exposure_kind_is_positive_evidence_only(facts, flags, expected, why):
    assert ce.auto_exposure_kind(facts, flags) == expected, why


def test_coverage_lines_naming_only_hired_nonowned_is_hnoa_only():
    facts = {"coverage_lines": [
        {"line": "Hired and Non-Owned Auto Liability", "premium": "$412"},
        {"line": "General Liability", "premium": "$3,200"},
    ]}
    assert ce.auto_exposure_kind(facts, AUTO) == ce.AUTO_HNOA_ONLY
    facts["coverage_lines"].append({"line": "Business Auto", "premium": "$2,991"})
    assert ce.auto_exposure_kind(facts, AUTO) == ce.AUTO_UNKNOWN, (
        "a granted Business Auto line beside the HNOA line is no longer HNOA-only")


def test_unknown_is_presumed_owned_for_scoring_owner_ruling():
    """OWNER 2026-08-26: an auto line that says neither owned nor HNOA-only is
    presumed owned - the client's 'genuinely Hired/Non-Owned only' is positive
    evidence to exempt, and the empty ACORD 127 is exactly the case 6.3 targets."""
    assert ce.auto_completeness_applies({}, AUTO) is True
    assert ce.auto_completeness_applies({"auto_covered_symbols": _sym(8, 9)}, AUTO) is False
    assert ce.auto_completeness_applies({}, {}) is False


# ── 2. The five deductions, the cap, the warnings ────────────────────────────

def test_the_clients_five_items_and_their_points():
    gaps = ce.auto_completeness_gaps({}, AUTO)
    assert [(k, p) for k, p, _ in gaps] == [
        ("auto_vin_schedule", 15), ("auto_drivers", 10),
        ("auto_garaging_addresses", 5), ("auto_radius_of_operation", 5),
        ("auto_vehicle_use", 5),
    ]
    assert sum(p for _, p, _ in gaps) == 40
    assert ce.auto_completeness_deduction({}, AUTO) == 25, "6.3 Bucket Cap: -25"


@pytest.mark.parametrize("facts,left", [
    ({"auto_vin_schedule": VEHICLES}, 25),
    ({"auto_vin_schedule": VEHICLES, "auto_drivers": DRIVERS}, 15),
    ({"auto_vin_schedule": VEHICLES, "auto_drivers": DRIVERS,
      "auto_garaging_addresses": ["12 Main St, Denver CO"]}, 10),
    ({"auto_vin_schedule": VEHICLES, "auto_drivers": DRIVERS,
      "auto_garaging_addresses": ["12 Main St, Denver CO"],
      "auto_radius_of_operation": "50"}, 5),
    ({"auto_vin_schedule": VEHICLES, "auto_drivers": DRIVERS,
      "auto_garaging_addresses": ["12 Main St, Denver CO"],
      "auto_radius_of_operation": "50", "auto_vehicle_use": "service"}, 0),
])
def test_each_item_retires_its_own_points(facts, left):
    assert ce.auto_completeness_deduction(facts, AUTO) == left


def test_hnoa_only_deducts_nothing_and_warns_nothing():
    facts = {"auto_covered_symbols": _sym(8, 9)}
    assert ce.auto_completeness_gaps(facts, AUTO) == []
    assert ce.auto_completeness_deduction(facts, AUTO) == 0
    _hard, soft = sq.evaluate_stops(facts, AUTO)
    assert not any("schedule not provided" in s for s in soft)


def test_a_driver_row_without_a_name_is_not_a_driver_schedule():
    facts = {"auto_vin_schedule": VEHICLES, "auto_drivers": [{"license_state": "TX"}]}
    assert ("auto_drivers", 10, "No driver schedule") in ce.auto_completeness_gaps(facts, AUTO)
    facts["auto_drivers"] = [{"name": "Jane Smith"}]
    assert "auto_drivers" not in {k for k, _, _ in ce.auto_completeness_gaps(facts, AUTO)}


def test_an_explicit_no_drivers_answer_is_an_answer():
    facts = {"auto_vin_schedule": VEHICLES, "auto_drivers": _human("", "explicit_no")}
    assert "auto_drivers" not in {k for k, _, _ in ce.auto_completeness_gaps(facts, AUTO)}


@pytest.mark.parametrize("facts,known,why", [
    ({"auto_radius_of_operation": "150"}, True, "the scalar fact"),
    ({"auto_vin_schedule": [{"year": "2021", "make": "Ford", "radius": "150"}]}, True,
     "a schedule row's own radius cell"),
    ({"dec_page_entries": [{"label": "Radius", "value": "150",
                            "line_of_business": "Business Auto", "owner": "policy"}]}, True,
     "the auto declarations index entry the 127 stamper prints from"),
    ({"dec_page_entries": [{"label": "Radius", "value": "NA",
                            "line_of_business": "Business Auto", "owner": "policy"}]}, False,
     "'RADIUS: NA' is not a stated radius"),
    ({"dec_page_entries": [{"label": "Radius", "value": "150",
                            "line_of_business": "General Liability", "owner": "policy"}]}, False,
     "a non-auto entry does not answer the auto question"),
    ({}, False, "nothing"),
])
def test_radius_is_known_wherever_the_form_stamper_would_read_it(facts, known, why):
    assert ce.auto_radius_known(facts) is known, why


def test_owned_auto_missing_schedules_raises_the_two_warnings():
    _hard, soft = sq.evaluate_stops({}, AUTO)
    assert any(s.startswith("Vehicle schedule not provided") for s in soft)
    assert any(s.startswith("Driver schedule not provided") for s in soft)
    _hard, soft = sq.evaluate_stops({"auto_vin_schedule": VEHICLES}, AUTO)
    assert not any(s.startswith("Vehicle schedule not provided") for s in soft)
    assert any(s.startswith("Driver schedule not provided") for s in soft)
    _hard, soft = sq.evaluate_stops({"auto_vin_schedule": VEHICLES, "auto_drivers": DRIVERS}, AUTO)
    assert not any("schedule not provided" in s for s in soft)


def test_the_two_warnings_carry_a_schedule_resolution():
    from services.issue_registry import classify_legacy, resolution_for
    for msg, schedule in (
        ("Vehicle schedule not provided - a Business Auto submission with owned vehicles needs the schedule",
         "auto_vin_schedule"),
        ("Driver schedule not provided - list the drivers of the scheduled vehicles", "auto_drivers"),
    ):
        code, cluster, _tier = classify_legacy(msg, "soft")
        assert code.startswith("legacy_auto_") and cluster == "Auto completeness"
        res = resolution_for(code)
        assert res["mode"] == "schedule" and res["schedule_key"] == schedule


def test_the_warnings_cap_at_85_but_never_charge_the_cross_bucket():
    """'+ Warning' means the 85 ceiling. Emitted through the legacy engine on
    purpose: a cross-form soft warning also lands in the Exposure
    cross-document bucket, which would charge the same gap twice."""
    _hard, soft = sq.evaluate_stops({}, AUTO)
    cap, reason = sq._resolve_cap([], soft)
    assert cap == 85
    _score, subs = sq._calculate_exposure_consistency({}, AUTO, [], [])
    assert subs["cross_document_consistency"] == 100
    assert subs["auto_completeness"] == 75


# ── 3. Supplemental WC ───────────────────────────────────────────────────────

@pytest.mark.parametrize("facts,flags,expected,why", [
    ({}, {}, ce.STATUS_NOT_APPLICABLE, "no WC line"),
    ({}, WC, ce.STATUS_UNKNOWN, "WC with nothing said about a mod - producer, no deduction"),
    ({"wc_xmod": "0.95"}, WC, ce.STATUS_SATISFIED, "a factor"),
    ({"wc_xmod": "95%"}, WC, ce.STATUS_SATISFIED, "a factor printed as a percentage"),
    ({"wc_xmod": "unity"}, WC, ce.STATUS_SATISFIED, "unity IS a stated mod of 1.00"),
    ({"wc_xmod": "not experience rated"}, WC, ce.STATUS_NOT_APPLICABLE, "not rated, stated"),
    ({"wc_xmod": _human("", "explicit_no")}, WC, ce.STATUS_NOT_APPLICABLE, "producer answered 'No'"),
    ({"wc_xmod": _human("", "not_applicable")}, WC, ce.STATUS_NOT_APPLICABLE, "producer answered N/A"),
    ({"wc_xmod": "pending"}, WC, ce.STATUS_MISSING, "the document says a mod is coming"),
    ({"wc_xmod": "see attached worksheet"}, WC, ce.STATUS_MISSING, "a worksheet exists - applicable"),
    ({"wc_xmod_effective_date": "01/01/2026"}, WC, ce.STATUS_MISSING,
     "a mod effective date with no factor - applicable and missing"),
    ({"wc_xmod_applicability": "applicable"}, WC, ce.STATUS_MISSING, "derived from the dec index"),
    ({"wc_xmod_applicability": "not_applicable"}, WC, ce.STATUS_NOT_APPLICABLE, "derived N/A"),
    ({}, {"has_workers_comp": True, "new_venture_confirmed": True}, ce.STATUS_NOT_APPLICABLE,
     "New Venture confirmed - no experience to rate"),
    ({"wc_xmod": "2024"}, WC, ce.STATUS_UNKNOWN, "a year in the box is not a mod"),
])
def test_xmod_status_matrix(facts, flags, expected, why):
    assert ce.wc_xmod_status(facts, flags) == expected, why


@pytest.mark.parametrize("facts,expected,why", [
    ({}, ce.STATUS_UNKNOWN, "no officers known - producer, no deduction"),
    ({"wc_officers": [{"name": "A. Owner"}]}, ce.STATUS_MISSING, "named, treatment unstated"),
    ({"wc_officers": [{"name": "A. Owner", "include": True}]}, ce.STATUS_SATISFIED, "included"),
    ({"wc_officers": [{"name": "A. Owner", "exclude": True}]}, ce.STATUS_SATISFIED, "excluded"),
    ({"wc_officers": [{"name": "A. Owner", "include": True}, {"name": "B. Officer"}]},
     ce.STATUS_MISSING, "one named officer still undecided"),
    ({"wc_officers": [{"name": "A. Owner"}],
      "wc_officer_exclusions": "No - all owners and officers are included"},
     ce.STATUS_SATISFIED, "the producer's answer settles it"),
    ({"wc_officer_exclusions": "There are no owners or officers to consider"},
     ce.STATUS_SATISFIED, "an answer, even 'none to consider'"),
    ({"wc_officer_exclusions": _human("", "explicit_no")}, ce.STATUS_SATISFIED, "explicit no"),
    ({"wc_officers": [{"title": "President"}]}, ce.STATUS_UNKNOWN, "a row with no name names nobody"),
    ({"entity_type": "Corporation"}, ce.STATUS_UNKNOWN,
     "OWNER 2026-08-26: never inferred from the entity type"),
])
def test_officer_treatment_matrix(facts, expected, why):
    assert ce.wc_officer_treatment_status(facts, WC) == expected, why


@pytest.mark.parametrize("facts,expected,why", [
    ({}, ce.STATUS_NOT_APPLICABLE, "no payroll - the -12 bucket owns that"),
    ({"total_payroll": "$500,000"}, ce.STATUS_MISSING, "a bare figure with no period anywhere"),
    ({"total_payroll": "$500,000", "wc_payroll_period": "annual"}, ce.STATUS_SATISFIED, "stated"),
    ({"total_payroll": "$500,000", "wc_payroll_period": "per year"}, ce.STATUS_SATISFIED, "meaning, not spelling"),
    ({"total_payroll": "$500,000", "wc_payroll_period": "12 months"}, ce.STATUS_SATISFIED, "12 months"),
    ({"total_payroll": "$500,000", "wc_payroll_period": "annualized"}, ce.STATUS_SATISFIED, "annualized"),
    ({"total_payroll": "$125,000", "wc_payroll_period": "quarterly"}, ce.STATUS_SATISFIED,
     "a stated quarter is interpretable - the gap is an UNRESOLVED period"),
    ({"total_payroll": _human("$500,000")}, ce.STATUS_SATISFIED,
     "a human answered the ANNUAL payroll question - the question wording is the period"),
    ({"wc_payroll": "$500,000", "wc_class_codes": [{"code": "5183", "payroll": "$500,000"}]},
     ce.STATUS_SATISFIED, "a class-code schedule states annual remuneration by definition"),
    ({"total_payroll": "$500,000",
      "dec_page_entries": [{"label": "Estimated Annual Payroll", "value": "$500,000"}]},
     ce.STATUS_SATISFIED, "the figure's own printed label means annual"),
    ({"total_payroll": "$500,000",
      "dec_page_entries": [{"label": "Total Remuneration (per annum)", "value": "$500,000"}]},
     ce.STATUS_SATISFIED, "per annum"),
    ({"total_payroll": "$500,000",
      "dec_page_entries": [{"label": "Payroll", "value": "$500,000"}]},
     ce.STATUS_MISSING, "a payroll label with no period wording"),
    ({"total_payroll": "$500,000", "wc_payroll_period": "whenever"}, ce.STATUS_MISSING,
     "an unreadable period is unresolved"),
])
def test_payroll_period_matrix(facts, expected, why):
    assert ce.wc_payroll_period_status(facts, WC) == expected, why


def test_wc_supplemental_points_and_cap():
    facts = {"total_payroll": "$500,000", "wc_xmod": "pending",
             "wc_officers": [{"name": "A. Owner"}]}
    gaps = ce.wc_supplemental_gaps(facts, WC)
    assert [(k, p) for k, p, _ in gaps] == [
        ("wc_xmod", 5), ("wc_officer_exclusions", 5), ("wc_payroll_period", 3)]
    assert ce.wc_supplemental_deduction(facts, WC) == 10, "6.4 Supplemental WC Cap: -10"
    assert ce.wc_supplemental_deduction({"total_payroll": "$500,000"}, WC) == 3
    assert ce.wc_supplemental_deduction({}, WC) == 0, "unknown items never deduct"
    assert ce.wc_supplemental_unknowns({}, WC) == ["wc_xmod", "wc_officer_exclusions"]


def test_a_gl_only_package_is_untouched_by_both_buckets():
    _score, subs = sq._calculate_exposure_consistency(
        {"gl_limits": "$1,000,000", "gl_class_codes_by_location": [{"code": "91580"}]}, GL, [], [])
    assert subs["auto_completeness"] == 100 and subs["wc_supplemental"] == 100


# ── 4. Pillar, trace, breakdown, no double count ─────────────────────────────

def test_the_buckets_reach_the_pillar_and_reconstruct_it():
    flags = {"has_auto_coverage": True, "has_workers_comp": True}
    facts = {"total_payroll": "$500,000",
             "wc_class_codes": [{"code": "5183", "payroll": "$500,000"}]}
    score, subs = sq._calculate_exposure_consistency(facts, flags, [], [])
    assert subs["auto_completeness"] == 75
    assert subs["wc_supplemental"] == 100, "class-schedule payroll is annual; mod/officers unknown"
    assert score == 100 - sum(100 - v for v in subs.values())


def test_the_breakdown_renders_every_bucket_the_scorer_emitted():
    """H1 audit: `_compute_category_breakdown` used to hardcode five (key,
    label) pairs and silently DROP any other bucket - the panel would have
    shown five rows while the headline charged for seven."""
    flags = {"has_auto_coverage": True}
    _score, subs = sq._calculate_exposure_consistency({}, flags, [], [])
    bd = sq._compute_category_breakdown({}, flags, exposure_subscores=subs)
    rows = bd["exposure_consistency"]
    assert set(rows) == set(subs)
    assert rows["auto_completeness"]["label"] == "Auto Completeness"
    assert rows["auto_completeness"]["deducted"] == 25
    assert rows["wc_supplemental"]["label"] == "WC Supplemental"


def test_the_trace_lists_both_buckets():
    flags = {"has_auto_coverage": True}
    pkg = sq.calculate_package_sqs({}, flags, form_results=[], cross_issues=[],
                                   hard_stops=[], soft_stops=[], session_data={})
    buckets = {r["bucket"]: r for r in pkg["score_trace"]["exposure"]}
    assert buckets["auto_completeness"]["deducted"] == 25
    assert "wc_supplemental" in buckets
    assert pkg["score_trace"]["reconciles"] is True


def test_no_tier2_fact_moves_either_bucket():
    """The client's own 'counted twice' test, extended to the new buckets."""
    flags = {"has_auto_coverage": True, "has_workers_comp": True}
    base = sq._calculate_exposure_consistency({"total_payroll": "$1"}, flags, [], [])[1]
    for tier2 in ("operations_description", "total_revenue", "num_employees",
                  "years_in_business", "naics_code", "fein"):
        subs = sq._calculate_exposure_consistency(
            {"total_payroll": "$1", tier2: "42"}, flags, [], [])[1]
        assert subs["auto_completeness"] == base["auto_completeness"], tier2
        assert subs["wc_supplemental"] == base["wc_supplemental"], tier2


def test_existing_auto_deductions_remain_separately_applicable():
    """6.3: 'Existing Auto deductions remain separately applicable'."""
    _score, subs = sq._calculate_exposure_consistency({}, AUTO, [], [])
    assert subs["coverage_information"] == 85, "-10 limit and -5 symbols, untouched"
    assert subs["auto_completeness"] == 75


# ── 5. Questionnaire ─────────────────────────────────────────────────────────

def test_hnoa_only_marks_the_five_owned_vehicle_facts_not_applicable():
    from services.fact_state import annotate_fact_states, value_state_of, is_not_applicable_for
    facts = {"auto_covered_symbols": {"value": _sym(8, 9), "confidence": "ai_high", "source": "ai"}}
    for key in ce.OWNED_VEHICLE_FACTS:
        facts[key] = {"value": None, "confidence": "ai_low", "source": "ai"}
    annotate_fact_states(facts, {"has_auto_coverage": True})
    for key in ce.OWNED_VEHICLE_FACTS:
        assert value_state_of(facts, key) == "not_applicable", key
        assert is_not_applicable_for(facts, key, ["ACORD_127"]) is True, (
            f"{key}: selecting ACORD 127 is applying for the LINE; an HNOA-only "
            "account still has no vehicle list - the line-level override must not undo this")
    assert value_state_of(facts, "auto_covered_symbols") == "present"


def test_owned_or_unknown_accounts_keep_asking():
    from services.fact_state import annotate_fact_states, value_state_of
    for extra in ({}, {"auto_covered_symbols": {"value": _sym(1), "source": "ai", "confidence": "ai_high"}}):
        facts = dict(extra)
        facts["auto_drivers"] = {"value": None, "confidence": "ai_low", "source": "ai"}
        annotate_fact_states(facts, {"has_auto_coverage": True})
        assert value_state_of(facts, "auto_drivers") == "not_stated"


def test_hnoa_only_suppresses_the_vehicle_questions_through_the_one_door():
    from services.question_classifier import classify_question, decorate_questions
    facts = {"auto_covered_symbols": {"value": _sym(8, 9), "source": "ai", "confidence": "ai_high"},
             "auto_vin_schedule": {"value": None, "source": "ai", "confidence": "ai_low"},
             "_flags": {"has_auto_coverage": True}}
    q = {"field_name": "auto_vin_schedule", "_canonical_key": "auto_vin_schedule",
         "_is_curated_client": True}
    q.update(classify_question("auto_vin_schedule", ["ACORD_127"], is_curated_client=True,
                               canonical_key="auto_vin_schedule"))
    decorate_questions([q], facts=facts)
    assert q.get("suppressed") is True
    assert q.get("eligibility_reason") == "not_applicable"


def test_vehicle_use_is_a_client_question_and_payroll_period_is_the_producers():
    from services.question_classifier import (
        AUDIENCE_CLIENT, AUDIENCE_PRODUCER, classify_question, decorate_questions,
    )
    from services.answer_options import options_for
    from services.arq_service import _curated_question_for
    from services.sqs_service import FORM_FIELD_INVENTORY
    assert "auto_vehicle_use" in FORM_FIELD_INVENTORY["ACORD_127"]
    assert "wc_payroll_period" in FORM_FIELD_INVENTORY["ACORD_130"]
    assert options_for("auto_vehicle_use") and options_for("wc_payroll_period")
    assert _curated_question_for("auto_vehicle_use") and _curated_question_for("wc_payroll_period")
    q = {"field_name": "auto_vehicle_use", "_canonical_key": "auto_vehicle_use",
         "_is_curated_client": True}
    q.update(classify_question("auto_vehicle_use", ["ACORD_127"], is_curated_client=True,
                               canonical_key="auto_vehicle_use"))
    decorate_questions([q], facts={})
    assert q["audience"] == AUDIENCE_CLIENT
    p = {"field_name": "wc_payroll_period", "_canonical_key": "wc_payroll_period",
         "_is_curated_client": True}
    p.update(classify_question("wc_payroll_period", ["ACORD_130"], is_curated_client=True,
                               canonical_key="wc_payroll_period"))
    decorate_questions([p], facts={})
    assert p["audience"] == AUDIENCE_PRODUCER, "master plan 4.4: payroll period is producer-only"


def test_payroll_period_validator_accepts_meaning():
    from services.fact_registry import FACT_REGISTRY
    v = FACT_REGISTRY["wc_payroll_period"]["validate"]
    for ok in ("annual", "Annual - the figure covers a full year", "per year", "12 months", "quarterly"):
        assert v(ok), ok
    assert not v("whenever")


# ── 6. The edit path ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag,facts,forms,supported,why", [
    ("has_auto_coverage", {}, [], False, "nothing at all - may drop"),
    ("has_auto_coverage", {}, ["ACORD_127"], True, "the producer selected the auto section"),
    ("has_auto_coverage", {"auto_covered_symbols": _sym(1)}, [], True, "symbols alone are evidence"),
    ("has_auto_coverage", {"auto_garaging_addresses": ["12 Main St"]}, [], True, "garaging alone"),
    ("has_auto_coverage", {"coverage_lines": [{"line": "Business Auto", "premium": "$2,991"}]}, [],
     True, "a granting coverage line"),
    ("has_workers_comp", {"wc_xmod": "0.95"}, [], True, "an X-Mod is WC evidence"),
    ("has_workers_comp", {"num_employees": "12"}, [], True, "a headcount is WC evidence"),
    ("has_property_coverage", {"year_built": "1998"}, [], True, "a COPE field is property evidence"),
    ("has_umbrella", {"umbrella_follow_form": "follows form"}, [], True, "umbrella evidence"),
    ("has_umbrella", {}, ["ACORD_131"], True, "umbrella section selected"),
    ("has_general_liability", {}, [], False, "GL with nothing"),
    ("some_other_flag", {}, [], True, "an unknown flag is never demoted"),
])
def test_a_coverage_flag_drops_only_when_no_evidence_remains(flag, facts, forms, supported, why):
    assert ce.coverage_flag_supported(flag, facts, forms) is supported, why


def test_the_edit_path_no_longer_keys_the_demotion_on_the_penaltys_own_facts():
    """The literal defect: an auto line with no limit and no schedule - the most
    incomplete auto submission - used to lose `has_auto_coverage` on the first
    field edit. With symbols on the policy the flag must survive."""
    import inspect
    from routes import form_routes
    src = inspect.getsource(form_routes)
    assert "coverage_flag_supported" in src
    assert 'fresh_flags["has_auto_coverage"] = False' not in src.replace(
        "fresh_flags[_cov_flag] = False", ""), "the hand-typed demotion is back"


def test_human_set_flags_survive_a_re_merge():
    from services.extraction_pipeline import _carry_human_flags
    merged = {"new_venture_indicator": _human("yes"),
              "carrier_marketing_reason": _human("Non-renewed by carrier")}
    mflags: dict = {}
    carried = _carry_human_flags(mflags, merged,
                                 {"new_venture_confirmed": True, "prior_carrier_adverse_action": True})
    assert set(carried) == {"new_venture_confirmed", "prior_carrier_adverse_action"}
    assert mflags == {"new_venture_confirmed": True, "prior_carrier_adverse_action": True}
    # A flag never outlives its evidence: no human fact, no carry.
    mflags = {}
    assert _carry_human_flags(mflags, {}, {"new_venture_confirmed": True}) == []
    assert mflags == {}
    # ...and never overrides what the merge already decided.
    mflags = {"new_venture_confirmed": False}
    _carry_human_flags(mflags, merged, {"new_venture_confirmed": True})
    assert mflags["new_venture_confirmed"] is False


# ── 7. Derived facts survive the purge ───────────────────────────────────────

def test_dec_entry_signals_survive_the_purge_through_derived_facts():
    from services.extraction_service import _derive_from_dec_entries_h1
    mf = {"total_payroll": {"value": "$500,000", "source": "ai", "confidence": "ai_high"},
          "dec_page_entries": [
              {"label": "Radius", "value": "150", "line_of_business": "Business Auto", "owner": "policy"},
              {"label": "Estimated Annual Payroll", "value": "$500,000", "owner": "policy"},
              {"label": "Experience Modification", "value": "Pending", "owner": "policy"},
          ]}
    _derive_from_dec_entries_h1(mf)
    for key, value in (("auto_radius_of_operation", "150"), ("wc_payroll_period", "annual"),
                       ("wc_xmod_applicability", "applicable")):
        assert mf[key]["value"] == value, key
        assert mf[key]["evidence_state"] == "derived"
        assert mf[key]["derivation"]["inputs"] == ["dec_page_entries"]
    # Purge the index, exactly as select_forms_bulk does - every answer holds.
    mf.pop("dec_page_entries")
    flags = {"has_auto_coverage": True, "has_workers_comp": True}
    assert ce.auto_radius_known(mf)
    assert ce.wc_payroll_period_status(mf, flags) == ce.STATUS_SATISFIED
    assert ce.wc_xmod_status(mf, flags) == ce.STATUS_MISSING


def test_derivations_never_overwrite_and_refuse_ambiguity():
    from services.extraction_service import _derive_from_dec_entries_h1
    mf = {"auto_radius_of_operation": "50",
          "dec_page_entries": [
              {"label": "Radius", "value": "150", "line_of_business": "Business Auto", "owner": "policy"},
              {"label": "Radius", "value": "300", "line_of_business": "Business Auto", "owner": "policy"},
              {"label": "Experience Mod", "value": "0.95", "owner": "policy"},
          ]}
    _derive_from_dec_entries_h1(mf)
    assert mf["auto_radius_of_operation"] == "50", "a stated value is never overwritten"
    assert mf["wc_xmod"]["value"] == "0.95", (
        "a factor printed under 'Experience Mod' IS the fact - the generic backfill "
        "cannot route that label to wc_xmod, so the meaning-based read must")
    assert "wc_xmod_applicability" not in mf, "a stated factor makes applicability moot"
    assert "wc_payroll_period" not in mf, "no payroll figure - nothing to interpret"
    mf2 = {"dec_page_entries": mf["dec_page_entries"][:2]}
    _derive_from_dec_entries_h1(mf2)
    assert "auto_radius_of_operation" not in mf2, "two radii is ambiguity, and ambiguity stays blank"
    assert ce.xmod_applicability_from_entries([
        {"label": "Experience Modification", "value": "N/A"},
        {"label": "Experience Modification", "value": "Pending"}]) is None


# ── 8. The phantom keys the audit found ──────────────────────────────────────

def test_split_limits_are_read_from_the_facts_the_extractor_writes():
    """Both engines read `bi_per_person` etc. - keys nothing writes - so every
    split-limit policy raised an unsatisfiable HARD STOP (package held at 60)."""
    from services.cross_form_validator import _check_auto_symbol_to_exposure_alignment
    facts = {"auto_liability_structure": "split", "auto_bi_per_person": "$100,000",
             "auto_bi_per_accident": "$300,000", "auto_pd_per_accident": "$50,000"}
    hard, _soft = sq.evaluate_stops(facts, AUTO)
    assert not any("Split liability limits incomplete" in h for h in hard)
    codes = [i["code"] for i in _check_auto_symbol_to_exposure_alignment(facts, AUTO, {"ACORD_127"})]
    assert "auto_split_limits_incomplete" not in codes
    facts.pop("auto_pd_per_accident")
    hard, _soft = sq.evaluate_stops(facts, AUTO)
    assert any("Split liability limits incomplete" in h for h in hard), "a real gap still stops"
    from services.issue_registry import resolution_for
    assert resolution_for("auto_split_limits_incomplete")["mode"] == "field"


def test_deductible_basis_is_read_from_the_real_fact():
    from services.cross_form_validator import _check_property_deductible_structure
    from services.issue_registry import resolution_for
    facts = {"property_deductible_aop": "$2,500", "deductible_basis": "per occurrence"}
    flags = {"has_property_coverage": True}
    codes = [i["code"] for i in _check_property_deductible_structure(facts, flags, {"ACORD_140"})]
    assert "property_deductible_basis_missing" not in codes
    facts.pop("deductible_basis")
    codes = [i["code"] for i in _check_property_deductible_structure(facts, flags, {"ACORD_140"})]
    assert "property_deductible_basis_missing" in codes
    assert resolution_for("property_deductible_basis_missing")["mode"] == "field"


def test_minimum_viable_cope_names_a_missing_value_again():
    from services.cross_form_validator import _check_minimum_viable_cope_unit
    flags = {"has_property_coverage": True}
    base = {"locations": ["1450 Lantern Court, Columbus OH 43215"],
            "occupancy_type": "Office", "construction_type": "Frame"}
    issues = _check_minimum_viable_cope_unit(dict(base), flags, {"ACORD_140"})
    assert issues and "building or BPP value" in issues[0]["message"]
    assert not _check_minimum_viable_cope_unit(dict(base, property_bpp_value="$50,000"),
                                               flags, {"ACORD_140"})
    assert not _check_minimum_viable_cope_unit(dict(base, property_building_value="$900,000"),
                                               flags, {"ACORD_140"})


def test_the_127_checklist_reads_garaging_by_its_real_name():
    """`auto_garaging_address` (singular) was read; the fact is plural."""
    import inspect
    assert 'auto_garaging_address"' not in inspect.getsource(sq)


# ── 9. Vehicle use reaches the form ──────────────────────────────────────────

def test_vehicle_use_ticks_the_use_column_for_every_real_row_only():
    from services import pdf_service as ps
    facts = {"auto_vehicle_use": "Service - technicians or crews driving to job sites",
             "auto_vin_schedule": VEHICLES}
    assert ps._deterministic_map("Vehicle_Use_ServiceIndicator_A", facts) == "Yes"
    assert ps._deterministic_map("Vehicle_Use_RetailIndicator_A", facts) == "No"
    assert ps._deterministic_map("Vehicle_Use_ServiceIndicator_B", facts) == "Yes"
    assert ps._deterministic_map("Vehicle_Use_RetailIndicator_B", facts) == "No"
    assert ps._deterministic_map("Vehicle_Use_ServiceIndicator_C", facts) is None, (
        "row C has no vehicle - a phantom row never inherits a use")
    assert ps._deterministic_map("Vehicle_Use_ServiceIndicator_B",
                                 {"auto_vehicle_use": "service"}) is None, (
        "no schedule at all - only row A can be said to exist")
    assert "auto_vehicle_use" in __import__("services.extraction_service", fromlist=["x"])._EXTRACT_SCHEMA


# ── 10. The residuals closed on 2026-08-26 (second pass) ─────────────────────

def test_hnoa_only_account_is_still_asked_about_its_hnoa_exposure():
    """6.3: 'Questionnaire behavior should instead focus on the applicable HNOA
    exposure.' The two facts behind ACORD 127's own Hired / Non-Owned boxes
    were in NO inventory - once the vehicle questions were suppressed, an
    HNOA-only account was asked nothing at all."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    from services.question_classifier import AUDIENCE_CLIENT, classify_question, decorate_questions
    inv = FORM_FIELD_INVENTORY["ACORD_127"]
    assert "hired_auto_indicator" in inv and "non_owned_auto_indicator" in inv
    facts = {"auto_covered_symbols": {"value": _sym(8, 9), "source": "ai", "confidence": "ai_high"},
             "_flags": {"has_auto_coverage": True}}
    for key in ("hired_auto_indicator", "non_owned_auto_indicator"):
        q = {"field_name": key, "_canonical_key": key, "_is_curated_client": True}
        q.update(classify_question(key, ["ACORD_127"], is_curated_client=True, canonical_key=key))
        decorate_questions([q], facts=facts)
        assert q["audience"] == AUDIENCE_CLIENT and not q.get("suppressed"), key


def test_a_garaging_address_satisfies_the_physical_address_rule():
    """The 3.12 warning and 6.3's garaging item fired together on one gap and
    stayed together after the garaging address was supplied."""
    from services.cross_form_validator import _check_identity_address_distinction
    facts = {"mailing_address": "PO Box 4820, Columbus OH 43216",
             "auto_garaging_addresses": ["1450 Lantern Court, Columbus OH 43215"]}
    assert not _check_identity_address_distinction(facts, AUTO, {"ACORD_125"})
    facts["auto_garaging_addresses"] = ["Yard"]
    assert _check_identity_address_distinction(facts, AUTO, {"ACORD_125"}), (
        "a label is not an address - the control still fires")


def test_xmod_question_is_suppressed_when_the_documents_say_no_mod_applies():
    from services.fact_state import annotate_fact_states, value_state_of, is_not_applicable_for
    facts = {"wc_xmod": {"value": None, "source": "ai", "confidence": "ai_low"},
             "wc_xmod_applicability": {"value": "not_applicable", "source": "derived",
                                       "confidence": "deterministic"}}
    annotate_fact_states(facts, {"has_workers_comp": True})
    assert value_state_of(facts, "wc_xmod") == "not_applicable"
    assert is_not_applicable_for(facts, "wc_xmod", ["ACORD_130"]) is True
    facts2 = {"wc_xmod": {"value": None, "source": "ai", "confidence": "ai_low"}}
    annotate_fact_states(facts2, {"has_workers_comp": True, "new_venture_confirmed": True})
    assert value_state_of(facts2, "wc_xmod") == "not_applicable", "New Venture: no mod to ask for"
    facts3 = {"wc_xmod": {"value": None, "source": "ai", "confidence": "ai_low"}}
    annotate_fact_states(facts3, {"has_workers_comp": True})
    assert value_state_of(facts3, "wc_xmod") == "not_stated", "unknown still asks"


def test_a_typed_radius_reaches_the_127_radius_box():
    from services import pdf_service as ps
    facts = {"auto_radius_of_operation": _human("150"), "auto_vin_schedule": VEHICLES}
    assert ps._resolve_vehicle_rating_cell("Vehicle_RadiusOfUse_A", facts) == "150"
    assert ps._resolve_vehicle_rating_cell("Vehicle_RadiusOfUse_B", facts) == "150"
    assert ps._resolve_vehicle_rating_cell("Vehicle_RadiusOfUse_C", facts) is ps._SCHED_SKIP, (
        "row C has no vehicle - nothing inherits")
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_RadiusOfUse_A", {"auto_radius_of_operation": "150"}) == "150", "row A with no schedule"
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_RadiusOfUse_B", {"auto_radius_of_operation": "150"}) is ps._SCHED_SKIP
    # The dec's own printed "NA" still vetoes everything (the 2026-08-16 rule).
    na = {"auto_radius_of_operation": "150",
          "dec_page_entries": [{"label": "Radius", "value": "NA",
                                "line_of_business": "Business Auto", "owner": "policy"}]}
    assert ps._resolve_vehicle_rating_cell("Vehicle_RadiusOfUse_A", na) is None


def test_vehicle_schedule_gap_renders_one_card_when_both_rules_fire():
    from services.issue_registry import (
        _LEGACY_SUPERSEDED_BY_CODE, build_grouped_view, build_structured_from_sources,
        make_issue,
    )
    assert _LEGACY_SUPERSEDED_BY_CODE["auto_agreed_value_requires_schedule"] == \
        "Vehicle schedule not provided"
    legacy = ("Vehicle schedule not provided - a Business Auto submission with owned "
              "vehicles needs the schedule (year, make, model, VIN)")
    coded = make_issue("auto_agreed_value_requires_schedule", "soft_warning",
                       "Physical damage valuation is 'agreed value'. A confirmed vehicle "
                       "schedule (VIN, year, make/model, value) is required.")
    def _warning_clusters(grouped):
        return {c["cluster"]: c
                for tier_clusters in grouped["warnings"].values() for c in tier_clusters}

    structured = build_structured_from_sources(legacy_soft=[legacy], cross_issues=[coded])
    grouped = build_grouped_view(structured, [], [legacy], cross_issues=[coded])
    clusters = _warning_clusters(grouped)
    assert clusters["Auto completeness"]["count"] == 1
    assert clusters["Auto completeness"]["items"][0]["code"] == "auto_agreed_value_requires_schedule"
    # ...and the legacy row still renders on its own when the coded twin is absent.
    alone = build_grouped_view(build_structured_from_sources(legacy_soft=[legacy]), [], [legacy])
    assert _warning_clusters(alone)["Auto completeness"]["count"] == 1


# ── 11. The c6 live run, round 1 (2026-08-26) - five defects, each pinned ────

def test_a_standard_exception_class_does_not_vote_beside_a_governing_class():
    """Live P2 (printing, 4299 + 8810) and P4 (bakery, 2003 + 8810): only the
    CLERICAL class was in the industry table, so both accounts read as
    'office', disagreed with their own operations, and Exposure charged -15 on
    two clean submissions.

    The exclusion is CONDITIONAL and that is the whole point - see the twin
    test below. A standard exception is discounted only when a real class sits
    beside it."""
    def _wc(*codes):
        return [{"code": c} for c in codes]

    for governing in ("4299", "2003", "99777"):          # none are in the table
        rows = _wc(governing, "8810")
        assert sq._codes_to_industry(str(rows), sq._class_code_tokens(rows)) is None, governing
    rows = _wc("5551", "8810")                            # a mapped governing class wins
    assert sq._codes_to_industry(str(rows), sq._class_code_tokens(rows)) == "construction"
    facts = {"operations_description": "Retail bakery and cafe", "wc_class_codes": _wc("2003", "8810")}
    assert sq._is_ops_class_code_mismatch(facts, WC, "wc") is False
    assert sq._calculate_exposure_consistency(
        dict(facts, wc_payroll="$210,000"), WC, [], [])[1]["operations_description"] == 100


def test_a_lone_standard_exception_is_still_the_clients_mismatch():
    """THE OTHER HALF, and the first fix got it wrong: a policy whose ONLY
    class is clerical has no governing class, so on a roofing contractor that
    IS the mismatch the client asked for (his own example). Over-broad
    exclusion silently deleted the check - caught by
    tests/test_workstream3_closure.py, kept here so the pair travels together."""
    for facts in (
        {"operations_description": "Residential roofing contractor",
         "wc_class_codes": [{"code": "8810", "description": "Clerical Office"}]},
        {"operations_description": "Full-service restaurant and bar",
         "wc_class_codes": [{"code": "8810"}]},
        {"operations_description": "We do work for clients in the region",
         "naics_code": "238160", "wc_class_codes": [{"code": "8810"}]},
        {"operations_description": "Residential roofing contractor",
         "gl_class_codes_by_location": [{"location": "1", "codes": ["8810"]}]},
    ):
        kind = "gl" if "gl_class_codes_by_location" in facts else "wc"
        assert sq._is_ops_class_code_mismatch(facts, {}, kind) is True, facts


def test_a_payroll_figure_is_never_read_as_a_class_code():
    """`_class_code_tokens` reads the STRUCTURE, not a stringified blob - a
    four-digit payroll or rate must not look like a governing class and switch
    the standard exception off."""
    rows = [{"code": "8810", "description": "Clerical", "payroll": "$9,600", "rate": "1.25"}]
    assert sq._class_code_tokens(rows) == {"8810"}
    assert sq._is_ops_class_code_mismatch(
        {"operations_description": "Residential roofing contractor", "wc_class_codes": rows},
        {}, "wc") is True
    assert sq._class_code_tokens([{"location": "1", "codes": ["91580", "92478"]}]) == {"91580", "92478"}
    assert sq._class_code_tokens("junk") == set() and sq._class_code_tokens(None) == set()


# The 14 REAL broker schedules the first cut of this fix DESTROYED. Every one
# names a line the umbrella does not sit over - the commonest way a schedule is
# written - and the first version read the innocent negation as "no schedule"
# and charged -15. A wrong VALUE, which is the direction blank-over-wrong
# exists to prevent. Found by adversarial review, not by a test.
_REAL_SCHEDULES = [
    "GL $1M/$2M; Auto $1M CSL; Employers Liability not included",
    "GL $1M/$2M and Auto $1M CSL; no aggregate provided on Auto",
    "GL $1M/$2M; Auto $1M CSL. WC is not included in the umbrella schedule.",
    "Underlying GL and Auto only - no WC coverage provided",
    "GL $1M, Auto $1M; no products coverage included",
    "GL $1M/$2M - defense costs not included within limits",
    "GL $1M/$2M; Auto $1M CSL; liquor liability not provided",
    "GL $1M/$2M; Auto $1M CSL; no crime coverage attached",
    "GL $1M; Auto $1M; professional liability not available under this program",
    "Underlying schedule attached, nothing else included",
    "Underlying policies listed on ACORD 131 page 2; nothing further attached",
    "GL $1M/$2M; Auto $1M CSL; Umbrella pending renewal quote",
    "GL $1M/$2M; Auto $1M CSL - final limits to follow at bind",
    "GL $1M; Auto $1M CSL; EL $1M. TBD whether cyber will be added.",
    "attached", "See attached schedule", "GL $1M/$2M; Auto $1M CSL",
    "General Liability 1,000,000/2,000,000; Business Auto 1,000,000 CSL",
    "On file with the carrier", "Listed on ACORD 131",
]

_TRUE_ABSENCES = [
    "the schedule of underlying insurance was not supplied",
    "The schedule of underlying insurance was not supplied.",
    "Schedule of underlying insurance not attached",
    "no schedule of underlying insurance", "No such schedule",
    "not supplied", "not provided", "none", "N/A", "n/a", "-", "--", "nil",
    "unknown", "not applicable", "missing", "outstanding", "requested",
    "pending", "TBD", "to follow", "to follow under separate cover",
    "to be provided", "to be obtained", "awaiting from carrier",
    "will follow under separate cover", "Will be supplied upon request",
    "not yet received", "none at this time", "we do not have it", "None provided",
]


@pytest.mark.parametrize("text", _REAL_SCHEDULES)
def test_a_real_schedule_is_never_deleted_by_a_negation_inside_it(text):
    """THE STRUCTURAL FIRST CONDITION: a value carrying limits IS a schedule,
    whatever line it says the umbrella does not cover. Same shape as the
    `_quote_asserts_something` fix - overlap is necessary but not sufficient."""
    assert not ce.value_states_absence(text), text
    assert ce.umbrella_schedule_present({"schedule_of_underlying_insurance": text}), text


@pytest.mark.parametrize("text", _TRUE_ABSENCES)
def test_a_negated_schedule_sentence_is_an_absence(text):
    """Live P1: 'the schedule of underlying insurance was not supplied' was
    extracted AS the schedule, so the -15 never fired (umbrella read 40, not
    25). Principle 3: a negation is not data."""
    assert ce.value_states_absence(text), text
    assert not ce.umbrella_schedule_present({"schedule_of_underlying_insurance": text}), text


def test_the_structured_underlying_policy_list_is_always_a_schedule():
    assert ce.umbrella_schedule_present({"underlying_policies": [{"line": "GL", "limit": "$1M"}]})
    assert not ce.umbrella_schedule_present({"underlying_policies": []})


def test_an_unreadable_phrase_never_invents_a_penalty():
    """Principle 7. An unrecognised note with no data reads as PRESENT and is
    recorded for review rather than silently costing 15 points."""
    assert not ce.value_states_absence("Refer to the broker for particulars")
    assert any("Refer to the broker" in r["value"] for r in ce.unreadable_absence_values())


def test_the_raw_text_backfill_will_not_manufacture_the_evidence():
    """The fix was DEFEATED UPSTREAM until this: `extraction_pipeline` scanned
    raw text with a bare substring test, so the live document's own 'was not
    supplied' sentence made it WRITE a synthetic 'referenced in submitted
    documents' fact at confidence=filled - manufacturing the very evidence
    whose absence is the -15."""
    assert not ce.text_references_schedule_as_present(
        "the schedule of underlying insurance was not supplied with this submission")
    # A dec-page HEADING has no verb - it must still count, which is why the
    # rule is mention-unless-negated rather than requiring an affirmative word.
    assert ce.text_references_schedule_as_present("SCHEDULE OF UNDERLYING INSURANCE")
    assert ce.text_references_schedule_as_present("See the schedule of underlying insurance on page 4")
    assert not ce.text_references_schedule_as_present("nothing about umbrellas here")
    import inspect
    from services import extraction_pipeline
    src = inspect.getsource(extraction_pipeline)
    assert "_schedule_referenced(_utext)" in src, "the bare substring test is back"


def test_every_reader_of_the_schedule_agrees_with_the_scorer():
    """ONE DOOR. The -15 fired while (a) the producer question that would fix
    it was suppressed as 'already answered' and (b) the evidence axis reported
    the fact as extracted_from_source. Three doors, three answers, one fact."""
    from services.arq_service import _maybe_inject_umbrella_evidence_questions
    negated = {"schedule_of_underlying_insurance": {
        "value": "The schedule of underlying insurance was not supplied.",
        "confidence": "high", "source": "ai"}, "umbrella_limit": {"value": "$5,000,000"}}
    flags = {"has_umbrella": True}
    assert sq._umbrella_schedule_present(negated) is False
    qs = []
    _maybe_inject_umbrella_evidence_questions(qs, negated, flags)
    assert "schedule_of_underlying_insurance" in {q["field_name"] for q in qs}, (
        "the producer must still be asked for the schedule we just charged for")
    assert sq._derive_evidence_labels(negated, flags=flags)[
        "schedule_of_underlying_insurance"] == "requires_supporting_doc"
    # ...and a REAL schedule keeps all three doors quiet.
    real = {"schedule_of_underlying_insurance": {
        "value": "GL $1M/$2M; Auto $1M CSL; Employers Liability not included",
        "confidence": "high", "source": "ai"}, "umbrella_limit": {"value": "$5,000,000"}}
    assert sq._umbrella_schedule_present(real) is True
    qs2 = []
    _maybe_inject_umbrella_evidence_questions(qs2, real, flags)
    assert "schedule_of_underlying_insurance" not in {q["field_name"] for q in qs2}


def test_the_umbrella_pillar_moves_by_exactly_the_fifteen():
    """End to end on the pillar. 'was not supplied' - a bare copula phrase with
    no subject - caught a real hole in the anchored pattern when this test was
    first written, which is why the optional subject/copula prefix exists."""
    umb = {"umbrella_limit": "$5,000,000", "gl_each_occurrence": "$1,000,000",
           "gl_aggregate": "$2,000,000", "umbrella_follow_form": "follows form",
           "schedule_of_underlying_insurance": "was not supplied"}
    flags = {"has_umbrella": True, "has_general_liability": True}
    assert sq._calculate_umbrella_adequacy(umb, flags) == 85, "-15, the schedule is NOT there"
    assert sq._calculate_umbrella_adequacy(
        dict(umb, schedule_of_underlying_insurance="attached"), flags) == 100
    # ...and a real schedule that names an excluded line keeps the full 100.
    assert sq._calculate_umbrella_adequacy(
        dict(umb, schedule_of_underlying_insurance="GL $1M/$2M; Auto $1M CSL; EL not included"),
        flags) == 100


def test_split_limits_state_the_auto_liability_limit():
    """Live P5: a split-limit policy ($250K / $500K / $100K printed) lost 10
    Exposure points for 'no liability limit' and asked the producer for a CSL,
    because every reader looked only at the CSL box - empty by design."""
    split = {"auto_liability_structure": "split", "auto_bi_per_person": "$250,000",
             "auto_bi_per_accident": "$500,000", "auto_pd_per_accident": "$100,000",
             "auto_covered_symbols": _sym(1)}
    assert ce.auto_liability_stated(split) and ce.auto_split_limits_stated(split)
    assert not ce.auto_split_limits_stated(dict(split, auto_liability_limit="$1,000,000"))
    subs = sq._calculate_exposure_consistency(split, AUTO, [], [])[1]
    assert subs["coverage_information"] == 100
    # The umbrella: split limits are an underlying auto; no CSL comparison is attempted.
    umb = dict(split, umbrella_limit="$5,000,000", gl_each_occurrence="$1,000,000",
               gl_aggregate="$2,000,000", umbrella_follow_form="follows form",
               schedule_of_underlying_insurance="attached")
    flags = {"has_umbrella": True, "has_general_liability": True, "has_auto_coverage": True}
    assert sq._calculate_umbrella_adequacy(umb, flags) == 100
    hard, _soft = sq.evaluate_stops({"umbrella_limit": "$5,000,000", **split},
                                    {"has_umbrella": True, "has_auto_coverage": True})
    assert not any("no underlying" in h for h in hard)


def test_the_csl_fact_is_NOT_marked_not_applicable_on_a_split_policy():
    """A REVERSAL, kept as a test so it is not "tidied" back in.

    For one revision the CSL fact was marked Not Applicable on a split policy,
    so the producer would not be asked for a limit the policy does not express.
    Adversarial review measured what that axis actually reaches:
    `pdf_service.apply_fact_state_confidence_labels` resolves the three STAMPED
    split boxes back to this one fact, so three boxes carrying real
    document-sourced values were relabelled `not_applicable` and dropped out of
    `confidence_fill_rate` - numerator and denominator both. An unnecessary
    producer card is recoverable; silently deleting real data from the fill
    rate is not."""
    from services.fact_state import annotate_fact_states, value_state_of
    facts = {"auto_liability_structure": "split", "auto_bi_per_person": "$250,000",
             "auto_bi_per_accident": "$500,000", "auto_pd_per_accident": "$100,000",
             "auto_liability_limit": {"value": None, "source": "ai", "confidence": "ai_low"}}
    annotate_fact_states(facts, AUTO)
    assert value_state_of(facts, "auto_liability_limit") == "not_stated"


def test_producer_typed_split_limits_actually_reach_the_form():
    """The hard stop is resolvable by typing the three limits - and the boxes
    must fill. The stamper gated on the `auto_split_limits` FLAG, which a
    producer answer never sets, so the stop cleared and the form stayed blank:
    a score that says fixed over an empty legal document."""
    from services import pdf_service as ps
    typed = {"auto_bi_per_person": "$250,000", "auto_bi_per_accident": "$500,000",
             "auto_pd_per_accident": "$100,000", "auto_liability_structure": "split"}
    assert ps._deterministic_map("Vehicle_BodilyInjury_PerPerson_A", typed) == "$250,000"
    assert ps._deterministic_map("Vehicle_BodilyInjury_PerAccident_A", typed) == "$500,000"
    assert ps._deterministic_map("Vehicle_PropertyDamage_PerAccident_A", typed) == "$100,000"
    # A CSL policy still blanks the split boxes and prints the combined limit.
    csl = {"auto_liability_limit": "$1,000,000"}
    assert ps._deterministic_map("Vehicle_BodilyInjury_PerPerson_A", csl) is None


def test_a_csl_policy_with_one_stray_split_part_is_not_called_split():
    """`any(parts)` was dead code (three phantom keys). Making the keys real
    turned a single stray figure on a CSL policy into a 60 cap."""
    hard, _ = sq.evaluate_stops(
        {"auto_liability_limit": "$1,000,000", "auto_pd_per_accident": "$100,000"}, AUTO)
    assert not any("Split liability limits incomplete" in h for h in hard)
    hard2, _ = sq.evaluate_stops({"auto_bi_per_person": "$250,000"}, AUTO)
    assert any("Split liability limits incomplete" in h for h in hard2), (
        "a genuinely partial split must still stop")


def test_a_split_underlying_auto_is_surfaced_not_silently_forgiven():
    """The umbrella baseline is a COMBINED single limit, so it cannot be
    compared to split parts. Removing the -20 was right (the limit is not
    missing); leaving nothing behind was not - an inadequate $100k/$300k/$50k
    policy would then score exactly like an adequate one. Principle 7: surface
    it, invent no rule. It rides in `review_items`, which - unlike the warning
    list - is not suppressed at full credit."""
    split = {"auto_bi_per_person": "$100,000", "auto_bi_per_accident": "$300,000",
             "auto_pd_per_accident": "$50,000", "auto_liability_structure": "split",
             "umbrella_limit": "$5,000,000", "gl_each_occurrence": "$1,000,000",
             "gl_aggregate": "$2,000,000", "umbrella_follow_form": "follows form",
             "schedule_of_underlying_insurance": "attached"}
    flags = {"has_umbrella": True, "has_general_liability": True, "has_auto_coverage": True}
    items = sq._build_umbrella_review_items(flags, sq._get_follow_form_status(split), 100, split)
    assert any("SPLIT limits" in i["action"] for i in items)
    assert sq._get_umbrella_state(split, flags) != "unknown", (
        "the state machine must agree with the score it mirrors")
    csl = {"auto_liability_limit": "$1,000,000", "umbrella_limit": "$5,000,000",
           "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
           "umbrella_follow_form": "follows form",
           "schedule_of_underlying_insurance": "attached"}
    assert not any("SPLIT limits" in i["action"] for i in
                   sq._build_umbrella_review_items(flags, sq._get_follow_form_status(csl), 100, csl))


def test_the_cross_form_rule_does_not_claim_a_stated_split_limit_is_missing():
    from services.cross_form_validator import _check_umbrella_auto_minimum_limits as chk
    split = {"auto_bi_per_person": "$250,000", "auto_bi_per_accident": "$500,000",
             "auto_pd_per_accident": "$100,000", "auto_liability_structure": "split",
             "umbrella_limit": "$5,000,000"}
    flags = {"has_umbrella": True, "has_auto_coverage": True}
    assert not [i["code"] for i in chk(split, flags, {"ACORD_127", "ACORD_131"})]
    # A genuinely absent auto limit still warns.
    assert "umbrella_auto_limits_not_found" in [
        i["code"] for i in chk({"umbrella_limit": "$5,000,000"}, flags,
                               {"ACORD_127", "ACORD_131"})]


def test_hnoa_owned_vehicle_items_leave_the_form_denominator():
    """C3 3.6's rule on a per-form checklist. An HNOA-only account was docked
    4 of 6 ACORD 127 items for facts the questionnaire refuses to ask for."""
    common = {"auto_liability_limit": "$1,000,000", "applicant_name": "X",
              "effective_date": "09/16/2026"}
    hnoa = dict(common, auto_covered_symbols=_sym(8, 9))
    owned = dict(common, auto_covered_symbols=_sym(1))

    def _struct(facts):
        return sq.calculate_sqs(facts=facts, flags=AUTO, mapped_data={}, form_schema={},
                                selected_form_ids=["ACORD_127"], hard_stops=[], soft_stops=[],
                                tier2_score=80, form_id="ACORD_127",
                                )["breakdown"]["structural_completeness"]
    assert _struct(hnoa) == 100, "nothing APPLICABLE is missing on an HNOA-only account"
    assert _struct(owned) < 50, "an owned account with the same gaps must still be docked"


def test_hnoa_only_also_retires_the_physical_damage_and_yard_questions():
    """Live P3: no vehicles, yet comp / collision deductible, physical-damage
    valuation and return-to-yard cards were still asked."""
    from services.fact_state import annotate_fact_states, value_state_of
    facts = {"auto_covered_symbols": {"value": _sym(8, 9), "source": "ai", "confidence": "ai_high"}}
    for key in ("auto_deductible_comp", "auto_deductible_collision",
                "auto_physical_damage_valuation", "vehicles_return_to_premises"):
        facts[key] = {"value": None, "source": "ai", "confidence": "ai_low"}
    annotate_fact_states(facts, AUTO)
    for key in ("auto_deductible_comp", "auto_deductible_collision",
                "auto_physical_damage_valuation", "vehicles_return_to_premises"):
        assert value_state_of(facts, key) == "not_applicable", key


def test_a_confirmed_new_venture_retires_both_xmod_questions():
    """Live P4: two EMOD questions (the fact and the narrative slot) - both
    must go once New Venture is confirmed."""
    from services.fact_state import annotate_fact_states, value_state_of
    facts = {k: {"value": None, "source": "ai", "confidence": "ai_low"}
             for k in ("wc_xmod", "narrative_target_markets")}
    annotate_fact_states(facts, {"has_workers_comp": True, "new_venture_confirmed": True})
    assert value_state_of(facts, "wc_xmod") == "not_applicable"
    assert value_state_of(facts, "narrative_target_markets") == "not_applicable"


def test_schedule_backed_facts_are_asked_once_as_a_table():
    """Live P1: 'Please list the vehicles to be insured' (the table) AND
    'Please list your business vehicles: year, make, model, and VIN' (a
    scalar) for one fact, and the same pair for drivers.

    The de-dup is at ASSEMBLY, not at a producer. The first attempt guarded the
    coverage-guarantee injector; adversarial review showed the scalar comes
    from the scorer's recommendation seed instead. There are several producers
    and one assembly point - guarding producers is how you fix four of five."""
    from services.arq_service import _drop_scalar_duplicates_of_schedule_questions as dedup
    qs = [
        {"field_name": "schedule::auto_vin_schedule", "_canonical_key": "auto_vin_schedule",
         "field_type": "schedule"},
        {"field_name": "auto_vin_schedule", "_canonical_key": "auto_vin_schedule",
         "field_type": "text"},
        {"field_name": "auto_radius_of_operation", "_canonical_key": "auto_radius_of_operation",
         "field_type": "text"},
    ]
    assert dedup(qs) == 1
    assert [q["field_name"] for q in qs] == [
        "schedule::auto_vin_schedule", "auto_radius_of_operation"]

    # NO TABLE IN THIS RUN -> the curated scalar survives. That is what keeps
    # `ENABLE_SCHEDULE_CAPTURE=false` working, and keeps a conflicted fact
    # re-admitted for the producer from being dropped on the floor.
    lone = [{"field_name": "auto_vin_schedule", "_canonical_key": "auto_vin_schedule",
             "field_type": "text"}]
    assert dedup(lone) == 0 and len(lone) == 1


def test_resolving_the_split_hard_stop_actually_fills_the_boxes():
    """THE WHOLE ROUND TRIP, and the half that was missing.

    The stop is now resolvable by typing the three limits. Adversarial review
    proved the stamper half worked while the RESTAMP half did not: all three
    ACORD boxes canonicalised to `auto_liability_limit` in
    `_ACORD_FIELD_RULES`, so `_restamp_canonical_into_forms` looked for boxes
    keyed on `auto_bi_per_person`, found none, and the producer cleared a 60
    cap over a form that stayed blank forever. Each box now maps to its own
    fact.
    """
    import json
    from services.arq_service import _restamp_canonical_into_forms, _canonical_key
    from services.answer_semantics import build_fact_envelope, interpret_answer

    facts = {"auto_bi_per_person": "$250,000"}          # extractor found one part
    hard, _ = sq.evaluate_stops(facts, AUTO)
    assert any("Split liability limits incomplete" in h for h in hard)

    with open("forms_schemas/ACORD_137_CA_schema.json", encoding="utf-8") as fh:
        schema = json.load(fh)
    fields = schema.get("fields", schema)
    generated = {"ACORD_137_CA": {"schema": fields, "field_state": {},
                                  "confidence": {}, "client_filled_fields": []}}
    for key, value in (("auto_bi_per_person", "$250,000"),
                       ("auto_bi_per_accident", "$500,000"),
                       ("auto_pd_per_accident", "$100,000")):
        canon = _canonical_key(key)
        assert canon == key, f"{key} must be its own canonical key"
        facts[canon] = build_fact_envelope(canon, interpret_answer(canon, value),
                                           "producer", "filled")
        _restamp_canonical_into_forms(generated, canon, facts)

    hard2, _ = sq.evaluate_stops(facts, AUTO)
    assert not any("Split liability limits incomplete" in h for h in hard2), "stop must clear"
    state = generated["ACORD_137_CA"]["field_state"]
    assert any("BodilyInjury_PerPerson" in k for k in state), "and the boxes must FILL"
    assert any("BodilyInjury_PerAccident" in k for k in state)
    assert any("PropertyDamage_PerAccident" in k for k in state)


@pytest.mark.parametrize("value,expected", [
    ("Commercial - Retail Delivery", "Commercial"),   # THIS codebase's own prompt example
    ("Retail - deliveries to customers", "Retail"),
    ("Commercial - general business use, hauling own goods", "Commercial"),
    ("Service - technicians or crews driving to job sites", "Service"),
    ("For hire - carrying goods or passengers for a fee", "ForHire"),
    ("Farm - agricultural use", "Farm"),
    ("Pleasure - personal use only, driving to and from work", "Pleasure"),
    ("service", "Service"), ("retail", "Retail"), ("Livery", "ForHire"),
    ("Contractor service vehicles", "Service"),
    ("zzz unrecognised use", "Other"),                # ACORD's own answer for unknown
])
def test_the_use_column_ticks_exactly_one_box(value, expected):
    """The seven USE boxes are MUTUALLY EXCLUSIVE. They were ticked by seven
    independent substring rules, so "Commercial - Retail Delivery" - the
    example in this repo's own extraction prompt - stamped Commercial AND
    Retail. Found by adversarial review; every value here is one a real
    document or this kit's own answer options can produce."""
    from services import pdf_service as ps
    boxes = ["Pleasure", "Farm", "Commercial", "Retail", "Service", "ForHire", "Other"]
    facts = {"auto_vehicle_use": value}
    ticked = [b for b in boxes
              if ps._deterministic_map(f"Vehicle_Use_{b}Indicator_A", facts) == "Yes"]
    assert ticked == [expected], f"{value!r} ticked {ticked}"


def test_the_use_resolver_never_answers_the_radius_boxes():
    """`Vehicle_Use_UnderFifteenMilesIndicator` / `..._FifteenMilesOrOver` sit
    in the same name space but are the RADIUS pair. A `[A-Za-z]+Indicator`
    pattern swallowed them, and answering them "No" asserts a radius nobody
    stated."""
    from services import pdf_service as ps
    facts = {"auto_vehicle_use": "Service"}
    for box in ("UnderFifteenMiles", "FifteenMilesOrOver"):
        assert ps._deterministic_map(f"Vehicle_Use_{box}Indicator_A", facts) in (None, "UNMATCHED")


def test_a_failed_package_score_is_never_persisted_over_a_good_one():
    """LIVE RUN 2026-08-27: R2 (P4, ACORD 125 + 130) showed no Total Package
    Score at all. The section renders on `{packageSqs && ...}`, and the only
    way it is absent is `form_routes`' `except` handler setting
    `package_sqs = None`.

    That handler then PERSISTED the None. `upd_processing_session` replaces
    this key wholesale (session_repository's merge loop `else` branch), and the
    modal's reload path reads it back (`sessData.package_sqs || null`) - so ONE
    transient scoring failure removed the score for the rest of the session,
    long after its cause had passed. The `facts` merge is deliberately additive
    so "an in-flight writer can never blank a value another writer just set";
    this key had no such protection.

    Structural, not a substring grep: every dict literal handed to
    `upd_processing_session` must carry `package_sqs` conditionally
    (`**({...} if pkg else {})`), never as a bare key whose value can be None.
    """
    import ast, io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "..", "routes",
                               "form_routes.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "upd_processing_session":
            continue
        for arg in node.args:
            if not isinstance(arg, ast.Dict):
                continue
            for k in arg.keys:
                # A `**{...}` entry has key None - that is the conditional form.
                if isinstance(k, ast.Constant) and k.value == "package_sqs":
                    offenders.append(getattr(node, "lineno", "?"))
    assert not offenders, (
        "form_routes.py:%s passes package_sqs unconditionally to "
        "upd_processing_session; a failed (None) score will wipe the last good "
        "one and the Total Package Score section will stay gone for the whole "
        "session" % offenders)


def test_the_package_score_failure_log_identifies_the_run():
    """The ONLY evidence of why a package score vanished is this log line. It
    named neither the session nor the forms, so a user report ("R2 had no total
    package score") could not be tied to it."""
    import io, os, re
    src = io.open(os.path.join(os.path.dirname(__file__), "..", "routes",
                               "form_routes.py"), encoding="utf-8").read()
    for marker in ("calculate_package_sqs failed", "package_sqs recompute (edit) failed"):
        idx = src.find(marker)
        assert idx > 0, f"the {marker!r} log line is gone"
        window = src[idx:idx + 260]
        assert "session=" in window, f"{marker!r} does not name the session"
        assert "trace=" in window, f"{marker!r} does not carry the trace id"


# ── The class-code fallback: H1-F's blob defect survived on a second path ────
# Written BEFORE the fix, per H1-F's standing lesson. LIVE RUN 2026-08-27: two
# clean packages (a bakery and a printer) both scored Operations 85 - a false
# -15 "class code does not match operations". `_class_code_tokens`' own
# docstring says an unrecognised shape returns an empty set "which the caller
# treats as 'cannot tell'". The caller did NOT: `_codes_to_industry` fell back
# to the pre-H1-F stringified-blob read, which has none of the three rules that
# make a verdict safe.

def test_an_unparseable_class_code_shape_yields_NO_verdict():
    """Rule 3 of this function's own docstring: an unmapped governing class
    means no verdict, because "silence is the only defensible answer". A shape
    we cannot even PARSE is strictly less knowable than an unmapped code, so it
    must be at least as silent. It was instead reading NCCI 8810 "Clerical" out
    of the blob and declaring the account an office."""
    from services import sqs_service as sq
    for shape in (
        [{"class_code": "2003", "description": "Bakeries"}, {"class_code": "8810"}],
        [{"wc_class_code": "2003"}, {"wc_class_code": "8810"}],
        {"OR": [{"class_code": "2003"}]},
        {"nested": {"unexpected": "2003 Bakeries"}},
    ):
        tokens = sq._class_code_tokens(shape)
        verdict = sq._codes_to_industry(str(shape).lower(), tokens)
        assert verdict is None or tokens, (
            f"{shape!r} produced verdict {verdict!r} from an unreadable shape")


def test_a_payroll_figure_can_never_vote_as_a_class_code():
    """H1-F closed this on the token path and left it open on the fallback:
    class 5403 (roofing) lives inside the payroll figure 540300, so a wholesale
    bakery was declared a construction risk and charged -15."""
    from services import sqs_service as sq
    blob = {"OR": [{"class_code": "2003", "payroll": "540300"}]}
    assert sq._codes_to_industry(str(blob).lower(), sq._class_code_tokens(blob)) != "construction"


def test_the_clients_own_lone_clerical_mismatch_still_fires():
    """The guard rail on the fix above. A roofing contractor whose ONLY stated
    class is 8810 Clerical IS the client's own mismatch example - a LONE
    standard exception is the governing class and must still vote. An earlier,
    over-broad version of this fix deleted exactly this case."""
    from services import sqs_service as sq
    assert sq._codes_to_industry("8810", sq._class_code_tokens("8810 Clerical Office")) == "office"
    assert sq._is_ops_class_code_mismatch(
        {"operations_description": "Residential roofing and re-roofing contractor",
         "wc_class_codes": [{"code": "8810", "description": "Clerical Office Employees"}]},
        {"has_workers_comp": True}, "wc") is True


def test_a_real_governing_class_still_convicts_a_mismatched_description():
    """The detection that must never stop working: restaurant operations
    declared under a roofing class."""
    from services import sqs_service as sq
    assert sq._is_ops_class_code_mismatch(
        {"operations_description": "Full service restaurant and bar",
         "wc_class_codes": [{"code": "5551", "description": "Roofing"}]},
        {"has_workers_comp": True}, "wc") is True


def test_the_live_bakery_and_printer_are_not_charged_a_mismatch():
    """Both live packages, in EVERY shape their extraction could plausibly
    produce. 2003 Bakeries and 4299 Printing are not in the deliberately
    conservative lookup table, so neither account can be classified - and an
    unclassifiable account is never a mismatch."""
    from services import sqs_service as sq
    for ops, rows in (
        ("Retail bakery and cafe", [("2003", "Bakeries"), ("8810", "Clerical")]),
        ("Commercial offset and digital printing with local delivery",
         [("4299", "Printing"), ("8810", "Clerical")]),
    ):
        for key in ("code", "class_code", "wc_class_code"):
            facts = {"operations_description": ops,
                     "wc_class_codes": [{key: c, "description": d} for c, d in rows]}
            assert sq._is_ops_class_code_mismatch(facts, {"has_workers_comp": True}, "wc") is False, (
                f"{ops!r} charged a mismatch with rows keyed {key!r}")


# ── Two live-run defects, 2026-08-27 ─────────────────────────────────────────

def test_the_acord101_advisory_reads_words_not_characters():
    """LIVE RUN: the advisory fired on P4's "Retail bakery and cafe". It tested
    `len(ops_desc) < 30` - CHARACTERS - which is wrong in both directions: a
    complete trade description is short, and a vacuous sentence is long."""
    from services import cross_form_validator as cf
    GL = {"has_general_liability": True}
    def fires(desc):
        facts = {"gl_class_codes_by_location": [{"code": "10100"}],
                 "operations_description": desc}
        return any("operations description is insufficient" in i.get("message", "")
                   for i in cf.run_cross_form_validation(
                       facts, GL, ["ACORD_125", "ACORD_126"]))
    # Complete trade descriptions - must NOT ask for a narrative.
    assert not fires("Tree trimming and removal")          # 25 chars, fired before
    assert not fires("Retail bakery and cafe")             # 22 chars, the live case
    # Genuinely bare - must still ask.
    assert fires("Bakery")
    assert fires("Roofing")
    assert fires("")


def test_a_real_acord_field_answered_out_of_batch_is_not_called_a_hallucination():
    """LIVE RUN: `UNKNOWN_KEYS` warned about
    NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A - a REAL
    ACORD 125 field that had already been stamped deterministically, so it was
    not in that batch's list - on an 1,877-character document, and advised
    lowering CONTEXT_UTILISATION. That is the opposite of the long-context
    condition the warning exists to detect.

    Structural: the classification must key off the invocation's ELIGIBLE +
    ALREADY-FILLED field sets, never off one batch's slice."""
    import inspect, re
    from services import pdf_service as ps
    src = inspect.getsource(ps._fill_unmatched_with_gpt)
    idx = src.find("UNKNOWN_KEYS")
    assert idx > 0, "the UNKNOWN_KEYS diagnostic is gone"
    window = src[max(0, idx - 2200):idx + 400]
    assert "_fabricated" in window and "already_filled" in window, (
        "UNKNOWN_KEYS no longer distinguishes a fabricated name from a real "
        "ACORD field answered outside its own batch")
    assert "OUT_OF_BATCH_KEYS" in src, "the benign case lost its own (INFO) log line"
    # The warning must still name the real failure mode when it IS real.
    assert "exist on NO selected form" in src


# ── D43 was being defeated upstream: the EXTRACTOR invented the period ───────
# LIVE RUN 2026-08-27, session 6a60e036. The dec index prints the bare label
# `Payroll = $210,000`; the merged fact came back `wc_payroll_period = "annual"`.
# D43: "'clearly annual' ... a payroll figure is annual when its OWN label /
# source MEANS annual" - never inferred from the category. Same shape as H1-F,
# where a raw-text backfill manufactured the evidence a rule tested for.

def _period_env(value, source="ai"):
    return {"value": value, "source": source, "confidence": "ai_high"}


def test_an_uncorroborated_annual_claim_is_not_corroborated():
    """The live case. A bare "Payroll" label says nothing about a period."""
    from services import coverage_evidence as ce
    entries = [{"label": "Payroll", "value": "$210,000", "section": "Workers Compensation"},
               {"label": "WC Class Codes", "value": "2003 Bakeries; 8810 Clerical"}]
    assert ce.payroll_period_corroborated("annual", entries, "Payroll  $210,000") is False


def test_a_document_that_really_says_annual_keeps_its_satisfaction():
    """The guard rail. D43's whole point is MEANING, not one spelling - each of
    these must corroborate, or the fix charges -3 on a document that said so."""
    from services import coverage_evidence as ce
    for label in ("Estimated Annual Payroll", "Annual Remuneration",
                  "Payroll (per year)", "Payroll - 12 months", "Yearly Payroll"):
        assert ce.payroll_period_corroborated(
            "annual", [{"label": label, "value": "$210,000"}], "") is True, label
    # ...and from the document BODY, not only a declarations label.
    assert ce.payroll_period_corroborated(
        "annual", [], "Total annual payroll for all employees is $210,000.") is True


def test_a_non_annual_period_is_corroborated_by_its_own_wording():
    from services import coverage_evidence as ce
    assert ce.payroll_period_corroborated(
        "quarterly", [{"label": "Quarterly Payroll (most recent quarter)",
                       "value": "$105,000"}], "") is True          # P5's shape
    assert ce.payroll_period_corroborated("quarterly", [{"label": "Payroll"}], "") is False


def test_the_gate_strips_only_an_INFERRED_period():
    """Provenance decides (Principle 6). A producer or client answer is the
    named evidence - it can never be gated. Neither can a derived value, which
    was computed FROM a corroborating label in the first place."""
    from services.extraction_service import _gate_inferred_payroll_period as gate
    docs = [{"text": "Payroll  $210,000"}]
    entries = [{"label": "Payroll", "value": "$210,000"}]

    ai = {"wc_payroll": "$210,000", "dec_page_entries": entries,
          "wc_payroll_period": _period_env("annual", "ai")}
    gate(ai, docs)
    assert not (ai.get("wc_payroll_period") or {}).get("value"), "an inference must be dropped"

    for src in ("producer", "client_arq", "client", "derived"):
        kept = {"wc_payroll": "$210,000", "dec_page_entries": entries,
                "wc_payroll_period": _period_env("annual", src)}
        gate(kept, docs)
        assert kept["wc_payroll_period"]["value"] == "annual", f"{src} must survive"


def test_the_live_bakery_now_scores_the_minus_3_the_client_specified():
    """End to end on the LIVE facts: gate the inference, then the 6.4 rule does
    exactly what the client's text says - -3, routed to the producer."""
    from services.extraction_service import _gate_inferred_payroll_period as gate
    from services import coverage_evidence as ce
    WC = {"has_workers_comp": True}
    facts = {"wc_payroll": "$210,000", "total_payroll": "$210,000",
             "dec_page_entries": [{"label": "Payroll", "value": "$210,000"}],
             "wc_class_codes": [{"code": "2003", "description": "Bakeries", "payroll": None},
                                {"code": "8810", "description": "Clerical", "payroll": None}],
             "wc_payroll_period": _period_env("annual", "ai")}
    assert ce.wc_payroll_period_status(facts, WC) == ce.STATUS_SATISFIED   # before
    gate(facts, [{"text": "Payroll  $210,000"}])
    assert ce.wc_payroll_period_status(facts, WC) == ce.STATUS_MISSING     # after
    assert ce.wc_supplemental_deduction(facts, WC) == 3


def test_a_class_schedule_WITH_amounts_still_satisfies_the_period():
    """D43's other half, which must not regress: a class-code schedule states
    annual remuneration by definition, so a document with amounts on its rows
    needs no period wording at all."""
    from services.extraction_service import _gate_inferred_payroll_period as gate
    from services import coverage_evidence as ce
    facts = {"wc_payroll": "$210,000",
             "wc_class_codes": [{"code": "2003", "description": "Bakeries", "payroll": "$180,000"},
                                {"code": "8810", "description": "Clerical", "payroll": "$30,000"}],
             "wc_payroll_period": _period_env("annual", "ai")}
    gate(facts, [{"text": "Payroll  $210,000"}])
    assert ce.wc_payroll_period_status(facts, {"has_workers_comp": True}) == ce.STATUS_SATISFIED
    assert ce.wc_supplemental_deduction(facts, {"has_workers_comp": True}) == 0
