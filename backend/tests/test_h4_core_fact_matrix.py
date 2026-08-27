"""V1 H4 - Core Submission Information Coverage (client section 9), 2026-08-27.

The client's section 9 is not a list of fields to add. Its own words:

    "The problem is not simply whether a field exists. A fact may currently be:
     extracted; normalized incorrectly; asked again; scoped incorrectly; scored
     in the wrong place; poorly sourced; treated as missing when it is actually
     N/A."

So 9.1 is an ACCEPTANCE MATRIX, and this file is that matrix as an executable
contract: for each core fact, WHO is asked, WHERE it scores, and the one rule
the client wrote in the "Key Rule" column. A row that drifts fails the build -
the same anti-rot shape as
`test_h3_wc_data_capture::test_every_schedule_column_binds_to_a_live_acord_field`.

EVERY ASSERTION DRIVES THE REAL CODE - the real classifier, the real
eligibility door, the real Tier lists read out of `sqs_service`, the real
ACORD schemas. Nothing here re-types a rule it is checking, because a test
that keeps its own copy of the table only proves the copy is self-consistent
(the lesson from the first `test_currency_tiebreak`).
"""

import json
import os

import pytest

from services import coverage_evidence as ce
from services.answer_semantics import interpret_answer, build_fact_envelope
from services.fact_registry import FACT_REGISTRY
from services.normalization import entity_family, values_conflict
from services.question_classifier import (
    AUDIENCE_CLIENT, AUDIENCE_PRODUCER, classify_question, decorate_questions,
)
from services.sqs_service import TIER1_CONTACT, TIER1_FIELDS, TIER2_FIELDS

_HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(form_id):
    with open(os.path.join(os.path.dirname(_HERE), "forms_schemas",
                           f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _route(fact_key, facts=None, form_ids=("ACORD_125",)):
    """The audience this fact's question ACTUALLY reaches, end to end."""
    q = {"field_name": fact_key, "_canonical_key": fact_key,
         "_is_curated_client": True, "question": "?", "form_ids": list(form_ids)}
    q.update(classify_question(fact_key, list(form_ids), is_curated_client=True,
                               canonical_key=fact_key))
    decorate_questions([q], present_fact_keys=set(), narrative_components={},
                       facts=(facts if facts is not None else {}))
    return q


# ── 9.1, the "Default Question Routing" column ───────────────────────────────
# Only facts the client's own table names, in his own groupings.

_PRODUCER_ONLY = [
    # (fact, the client's stated reason)
    ("producer_name",        "the agency's own name"),
    ("effective_date",       "9.1: client does not need to interpret policy period"),
    ("expiration_date",      "9.1: policy period is the producer's"),
    ("lines_of_business",    "9.1: Lines Requested -> Producer"),
    ("naics_code",           "9.1: Never ask client"),
    ("sic_code",             "9.1: Never ask client"),
    ("wc_xmod",              "9.1: X-Mod / EMOD -> Producer"),
    ("wc_xmod_effective_date", "rides with the X-Mod"),
    ("wc_payroll_period",    "9.1: WC Payroll Period -> Producer"),
    ("wc_officer_exclusions", "9.1: not a generic client question"),
    ("wc_officers",          "9.1: Owner/Officer WC Treatment -> Producer"),
    ("wc_class_codes",       "9.1: WC Class Code -> Producer, no client classification"),
    ("gl_class_codes_by_location", "9.1: GL Class Code -> Producer"),
    ("auto_covered_symbols", "9.1: Auto Covered Symbols -> policy interpretation"),
    ("gl_form_type",         "occurrence vs claims-made IS policy interpretation"),
]

_CLIENT_ELIGIBLE = [
    ("applicant_name",          "9.1: Client or Producer"),
    ("mailing_address",         "9.1: Client or Producer"),
    ("physical_address",        "9.1: Client or Producer"),
    ("entity_type",             "9.1: Client or Producer"),
    ("contact_name",            "9.1: Client or Producer"),
    ("fein",                    "9.1: Client or Producer"),
    ("operations_description",  "9.1: factual client question"),
    ("total_revenue",           "9.1: Client or Producer"),
    ("num_employees",           "9.1: Client or Producer"),
    ("years_in_business",       "9.1: Client or Producer"),
    ("prior_carrier",           "9.1: Client factual answer allowed; Producer final"),
    ("num_claims",              "9.1: Prior Claims -> Client or Producer"),
    ("total_payroll",           "9.1: Annual Payroll -> Client or Producer"),
    ("auto_vin_schedule",       "9.1: Vehicle Schedule -> Client or Producer"),
    ("auto_drivers",            "9.1: Driver Schedule -> Client or Producer"),
    ("auto_garaging_addresses", "9.1: Garaging -> Client or Producer"),
    ("auto_vehicle_use",        "9.1: Vehicle Use -> Client or Producer"),
    ("property_building_value", "9.1: Property COPE -> factual property questions allowed"),
]


@pytest.mark.parametrize("fact,reason", _PRODUCER_ONLY)
def test_producer_only_facts_never_reach_the_client(fact, reason):
    """9.1's routing column, and core principle 5. A classification or
    policy-interpretation fact is the producer's in EVERY state - not only in
    the states we happened to enumerate."""
    assert _route(fact)["audience"] == AUDIENCE_PRODUCER, reason


@pytest.mark.parametrize("fact,reason", _CLIENT_ELIGIBLE)
def test_client_eligible_facts_still_reach_the_client(fact, reason):
    """The other half of D32, and the more dangerous one. The measured
    precedent is `total_payroll` / `wc_payroll_period` / `wc_officer_exclusions`
    falling to audience=internal when a SCORING removal leaked into the
    questionnaire - "Primble would have stopped asking anyone for annual
    payroll". Every routing change must be checked in both directions."""
    assert _route(fact)["audience"] == AUDIENCE_CLIENT, reason


def test_every_core_fact_is_asked_of_somebody():
    """D32 stated as a property over the whole matrix: removing a field from
    the SCORE never removes it from the QUESTIONNAIRE. Producer-routed is fine;
    reaching nobody is not."""
    for fact, _ in _PRODUCER_ONLY + _CLIENT_ELIGIBLE:
        q = _route(fact)
        assert q["audience"] in (AUDIENCE_CLIENT, AUDIENCE_PRODUCER), fact
        if q["audience"] == AUDIENCE_PRODUCER:
            assert q.get("bucket") == "agency", (
                f"{fact} routed to a bucket the producer UI hides - it would be "
                f"invisible to everyone")


def test_no_fact_is_scored_in_two_structural_homes():
    """9's Desired Outcome: "Score in the Correct Home" - one home, not two."""
    assert not (set(TIER1_FIELDS) & set(TIER2_FIELDS))
    for fact in ("prior_carrier", "num_claims", "total_payroll", "wc_xmod",
                 "wc_payroll_period", "wc_officer_exclusions"):
        assert fact not in TIER2_FIELDS, (
            f"{fact} is back in Structural Tier 2 - C3 3.5/3.14 and C2 2.7/2.8 "
            f"moved it to its own pillar")


# ── 9.1's "Key Rule" column, one test per rule the client wrote ──────────────

def test_any_one_contact_method_satisfies_tier_1_in_the_questionnaire_too():
    """9.1 Contact Name/Phone/Email key rule: "Any one contact method satisfies
    Tier 1". The SCORER always knew; the questionnaire asked all three as
    CRITICAL and pre-ticked them."""
    from services.sqs_service import _tier1_items
    answered = {"contact_phone": build_fact_envelope(
        "contact_phone", interpret_answer("contact_phone", "303-555-0100"),
        "client_arq", "client_arq")}
    _app, missing = _tier1_items(answered, {})
    assert "Contact information" not in missing, "the score already knew"

    none_answered = _route("contact_name")
    assert none_answered["priority"] == "critical", (
        "with NO contact answered it must stay critical - the demotion must "
        "not fire on the case it was not written for")
    demoted = _route("contact_name", facts=answered)
    assert demoted["priority"] == "important", "one method answered -> demoted"
    assert demoted["audience"] == AUDIENCE_CLIENT, "demoted, never suppressed"
    assert not demoted.get("suppressed"), (
        "PRIORITY_OPTIONAL / suppressed would leave the ACORD 125 Contact Full "
        "Name box blank AND unasked - the boxes are three separate fields")
    assert "Submission readiness" not in (
        demoted.get("score_impact") or {}).get("labels", []), (
        "a demoted question must stop advertising a readiness impact it no "
        "longer has")


def test_explicit_zero_differs_from_missing():
    """9.1 Annual Revenue key rule: "Explicit zero differs from missing", and
    Number of Employees: "Zero/new venture can be valid"."""
    from services.sqs_service import _fact_is_filled
    for fact in ("total_revenue", "num_employees"):
        interp = interpret_answer(fact, "0")
        assert interp.value_state == "present", f"{fact}: 0 is a VALUE"
        assert _fact_is_filled(build_fact_envelope(
            fact, interp, "client_arq", "client_arq")), fact


def test_na_and_none_are_answers_not_gaps():
    """9's Current Problem, last bullet: "treated as missing when it is actually
    N/A". Brent 2026-08-24: "we can't treat 'N/A' as '0'."

    This is the F15 gate. `arq_service._clean_answer_ex` used to discard these
    words before `answer_semantics` ever saw them, so the CLIENT path and the
    PRODUCER path disagreed about the same word."""
    from services.arq_service import _clean_answer_ex
    for raw, fact in (("None", "prior_carrier"), ("none", "num_claims"),
                      ("N/A", "fein"), ("n/a", "total_payroll")):
        value, reason = _clean_answer_ex(raw, fact)
        assert value == raw, f"{raw!r} on {fact} discarded again (F15)"
        assert reason == "", (
            f"{raw!r} on {fact} carries a review reason, which sends it to "
            f"_blocks_submit and refuses the whole submission")
        assert interpret_answer(fact, raw).value_state in (
            "explicit_no", "not_applicable"), fact


def test_a_required_identity_fact_can_never_be_not_applicable():
    """The other half of the same rule, and the reason it needs a limit: an
    absence is a legitimate answer about a PRIOR CARRIER, never about the
    applicant's own legal name. Without this, one word typed into every box
    scored a perfect Structural pillar."""
    from services.sqs_service import _tier1_items
    required = [k for k, v in FACT_REGISTRY.items() if v.get("required")]
    assert "applicant_name" in required, "the registry is the source of truth"
    facts = {}
    for fact in ("applicant_name", "mailing_address", "effective_date"):
        interp = interpret_answer(fact, "N/A")
        assert not interp.accepted, f"{fact} accepted 'N/A' as an answer"
        facts[fact] = build_fact_envelope(fact, interp, "client_arq", "client_arq")
    _app, missing = _tier1_items(facts, {})
    assert "Applicant legal name" in missing, (
        "'N/A' in every required box must not buy a Tier 1 credit")


def test_new_venture_is_a_valid_state_for_years_in_business():
    """9.1 Years in Business key rule: "New venture is valid state"."""
    from services.loss_history_state import apply_new_venture_derivations
    from services.sqs_service import _tier2_items
    from services.fact_state import value_state_of

    facts = {"new_venture_indicator": {"value": "Yes - new venture",
                                       "source": "producer"}}
    flags = {"new_venture_confirmed": True}
    apply_new_venture_derivations(facts, flags)
    assert value_state_of(facts, "years_in_business") == "not_applicable"
    _app, missing = _tier2_items(facts)
    assert "Years in business" not in missing, (
        "a confirmed new venture is still charged for history it cannot have")

    # ...and NOT as "0". Brent: "we can't treat 'N/A' as '0'." Measured: a
    # derived "0" makes years_in_business_band YOUNG, which makes
    # `loss_history_not_applicable` fire on the BAND ALONE - so a withdrawn
    # confirmation silently DELETED the Loss History pillar (P4 -> None).
    from services.loss_history_state import years_in_business_band
    assert years_in_business_band(facts) == "unknown", (
        "the derived state must not masquerade as a measured 0-year history")

    # The premise going away takes the conclusion with it.
    assert apply_new_venture_derivations(facts, {"new_venture_confirmed": False}) \
        == ["years_in_business"]


def test_a_stated_years_value_is_never_overwritten_by_the_derivation():
    """Principle 4: a real figure beside a New Venture confirmation is a
    CONFLICT for the producer, not something to quietly replace."""
    from services.loss_history_state import apply_new_venture_derivations
    facts = {"new_venture_indicator": {"value": "Yes", "source": "producer"},
             "years_in_business": {"value": "8", "source": "ai"}}
    apply_new_venture_derivations(facts, {"new_venture_confirmed": True})
    assert facts["years_in_business"]["value"] == "8"


def test_wc_payroll_period_is_na_when_the_annual_basis_is_clear():
    """9.1 WC Payroll Period key rule: "N/A if annual basis is clear"."""
    from services.fact_state import value_state_of
    annual = {"wc_payroll": {"value": "$800,000", "source": "producer"}}
    assert value_state_of(annual, "wc_payroll_period") == "not_applicable"
    assert not [g for g in ce.wc_supplemental_gaps(annual, {"has_workers_comp": True})
                if g[0] == "wc_payroll_period"]


def test_the_payroll_period_deduction_always_has_a_route_to_remediation():
    """THE GUARD RAIL, and the reason this rule shipped twice.

    The first cut routed the Not Applicable decision through
    `wc_payroll_period_status`, which reads `flags`. `fact_state` calls the
    door with NO flags and `facts["_flags"]` exists only inside one
    `annotate_fact_states` pass - so the fact came back Not Applicable on EVERY
    package while the -3 was still being charged: a deduction nobody could ever
    clear. The predicate must be FLAG-INDEPENDENT, and the -3 must fire if and
    only if the question is still asked."""
    bare = {"wc_payroll": {"value": "$210,000", "source": "ai"}}
    from services.fact_state import value_state_of
    charged = [g for g in ce.wc_supplemental_gaps(bare, {"has_workers_comp": True})
               if g[0] == "wc_payroll_period"]
    assert charged, "the client's -3 must still fire on a bare payroll figure"
    assert value_state_of(bare, "wc_payroll_period") != "not_applicable", (
        "charged AND unaskable - the exact contradiction this test exists for")
    assert _route("wc_payroll_period", facts=bare)["audience"] == AUDIENCE_PRODUCER


def test_entity_type_normalizes_equivalent_legal_formats():
    """9.1 Entity Type key rule: "Normalize equivalent legal formats".

    Every pair below raised a live Data Consistency conflict before H4 -
    including ACORD 125's OWN checkbox wording against the abbreviation."""
    for a, b in (("LLC", "Limited Liability Corporation"),
                 ("LLC", "Limited Liability Company"),
                 ("Sole Proprietor", "Sole Proprietorship"),
                 ("Nonprofit", "Non-Profit"),
                 ("Corporation", "Incorporated"),
                 ("Partnership", "General Partnership")):
        assert not values_conflict("entity_type", [a, b]), f"{a} vs {b}"
    # ...and a REAL disagreement still surfaces (principle 4).
    for a, b in (("LLC", "Corporation"), ("Corporation", "S Corporation"),
                 ("LLC", "LLP"), ("Partnership", "Limited Partnership")):
        assert values_conflict("entity_type", [a, b]), f"{a} vs {b} was silenced"


def test_every_offered_entity_option_validates_and_ticks_exactly_one_box():
    """The three vocabularies made one. Before H4 the producer-answer validator
    REFUSED 8 of the 13 options `answer_options` itself offers, and the stamper
    ticked no box for "Sole Proprietorship" and the WRONG box for
    "S Corporation" and "Non-Profit Corporation"."""
    from services.answer_options import ENTITY_TYPE_OPTIONS
    from services.pdf_service import _derive_indicator
    from routes.audit_routes import _validate_producer_answer

    for option in ENTITY_TYPE_OPTIONS:
        ok, msg = _validate_producer_answer("entity_type", option)
        assert ok, f"our own dropdown offers {option!r} and our validator refuses it: {msg}"

    # The two forms print DIFFERENT sets, which is why the family maps to a set
    # of acceptable box words rather than to one name:
    #   ACORD 125 has Individual and NotForProfit, and no SoleProprietor;
    #   ACORD 130 has SoleProprietor and UnincorporatedAssociation, and neither
    #   Individual nor NotForProfit.
    from services.pdf_service import _ENTITY_BOX_WORDS
    for form_id in ("ACORD_125", "ACORD_130"):
        boxes = [f for f in _schema(form_id)
                 if f.startswith("NamedInsured_LegalEntity_")
                 and f.endswith("Indicator_A")]
        assert boxes, form_id
        words_on_this_form = {b.split("_")[2][: -len("Indicator")] for b in boxes}
        for option in ENTITY_TYPE_OPTIONS:
            facts = {"entity_type": {"value": option}}
            ticked = [b for b in boxes if _derive_indicator(b, facts) == "Yes"]
            assert len(ticked) <= 1, (
                f"{form_id} {option!r} ticked {ticked} - ACORD's own tooltip says "
                f"the legal entity code IS one value")
            family = entity_family(option)
            if family in (None, "other"):
                continue
            # A FORM LIMIT IS NOT A DEFECT. ACORD 130 prints no Not-For-Profit
            # box at all, so a non-profit employer's WC application genuinely
            # has nowhere deterministic to go - the correct ACORD answer there
            # is the Other box plus its description, which the evidence-gated
            # fill can supply and a blind tick cannot (the post-fill guard
            # blanks an affirmative whose paired description is empty).
            if _ENTITY_BOX_WORDS[family] & words_on_this_form:
                assert len(ticked) == 1, f"{form_id} {option!r} ticked nothing"
            else:
                assert not ticked, (
                    f"{form_id} has no box for {family} - it must assert "
                    f"nothing rather than tick a neighbouring family")


def test_an_unrecognisable_entity_type_asserts_nothing():
    """Core principle 3 on a legal document. An entity type we cannot place
    used to produce NINE explicit "No"s - asserting the insured is none of the
    nine - and never reached gap fill at all."""
    from services.pdf_service import _derive_indicator
    boxes = [f for f in _schema("ACORD_125")
             if f.startswith("NamedInsured_LegalEntity_") and f.endswith("Indicator_A")]
    for value in ("", "Ltd.", "something we have never seen"):
        facts = {"entity_type": {"value": value}}
        answers = {b: _derive_indicator(b, facts) for b in boxes}
        assert set(answers.values()) == {None}, (
            f"{value!r} asserted {answers} instead of leaving the group to the "
            f"evidence-gated fill")


def test_the_matrix_reads_the_scorer_rather_than_copying_it():
    """ANTI-ROT for this file itself. Every fact named above must still exist,
    and the tier lists must come from `sqs_service` - a matrix with its own
    copy of the rules only proves the copy is self-consistent."""
    for fact, _ in _PRODUCER_ONLY + _CLIENT_ELIGIBLE:
        assert fact in FACT_REGISTRY, f"{fact} is no longer a canonical fact"
    assert set(TIER1_CONTACT) <= set(FACT_REGISTRY)
    assert len(TIER2_FIELDS) == 6, (
        "C3 3.5 fixed Tier 2 at the client's own six general-business fields")
