"""Client master plan section 4 - Contextual Questionnaire Logic (2026-08-26).

Pins the 4.1 decision flow, the 4.2/4.4 routing principle and the two structural
safety properties the design rests on:

  * `test_overlay_never_widens_client_exposure` - the door can only ever move a
    question AWAY from the client. If that stops being true, a bug here starts
    asking the insured things they cannot answer, which is the whole defect the
    client is reporting.
  * `test_no_judgment_fact_lands_in_a_hidden_bucket` - the producer UI currently
    HIDES the "Underwriting / Internal Review" bucket at the client's request
    (`SHOW_UNDERWRITING_REVIEW_BUCKET = false` in AcordModal.jsx). A re-routed
    question that landed there would be invisible to everyone. Producer-routed
    questions must land in the AGENCY bucket, which renders unconditionally.

  * `test_every_judgment_fact_is_a_real_registry_fact` - the anti-rot guard. The
    repo's precedent is
    `test_every_reconcilable_field_has_a_resolved_scan_shape`; same idea, applied
    to the routing table.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import question_eligibility as qe                # noqa: E402
from services.question_classifier import (                     # noqa: E402
    AUDIENCE_CLIENT, AUDIENCE_PRODUCER, BUCKET_AGENCY, BUCKET_CLIENT,
    classify_question, decorate_questions,
)


def _q(field, canonical=None, **extra):
    """One question shaped the way the three generation paths build them."""
    canon = canonical if canonical is not None else field
    q = {
        "field_name": field,
        "question": f"question about {field}",
        "_canonical_key": canon,
        "_is_curated_client": True,
    }
    q.update(classify_question(field, ["ACORD_125"],
                               is_curated_client=True, canonical_key=canon))
    q.update(extra)
    return q


def _ai(value):
    """An extracted fact envelope exactly as `_annotate_facts` writes one.

    Verified 2026-08-26 against extraction_service.py:1566 - every LLM-extracted
    fact carries confidence ai_high/ai_low and source "ai", which
    fact_state.derive_evidence_state maps to `suggested`.
    """
    return {"value": value, "confidence": "ai_high", "source": "ai"}


# ── 4.4 / core principle 5 - insurance judgment routes to the producer ───────

@pytest.mark.parametrize("fact", [
    "gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_deductible",
    "umbrella_limit", "umbrella_sir", "auto_liability_limit",
    "employers_liability_limits", "period_of_restoration",
    "wc_xmod", "wc_officer_exclusions", "wc_payroll_period",
    "wc_class_codes", "gl_class_codes_by_location", "auto_covered_symbols",
    "valuation_method", "coinsurance_percentage", "retro_date",
    "lines_of_business", "effective_date",
])
def test_judgment_facts_route_to_producer(fact):
    """4.4: these require insurance expertise, so the client is never asked."""
    q = _q(fact)
    decorate_questions([q], facts={fact: _ai("something")})
    assert q["audience"] == AUDIENCE_PRODUCER, fact
    assert q["bucket"] == BUCKET_AGENCY, fact
    assert q["eligibility_reason"] == qe.REASON_INSURANCE_JUDGMENT, fact


@pytest.mark.parametrize("fact", [
    "applicant_name", "mailing_address", "fein", "entity_type",
    "total_revenue", "num_employees", "years_in_business",
    "operations_description", "total_payroll", "num_claims",
    "property_building_value", "property_bpp_value",
    "construction_type", "occupancy_type",
])
def test_client_eligible_facts_stay_client(fact):
    """4.3: plain business facts the insured can answer must NOT be re-routed."""
    q = _q(fact)
    before = q["audience"]
    decorate_questions([q], facts={})
    assert before == AUDIENCE_CLIENT, f"{fact} was not client before the overlay"
    assert q["audience"] == AUDIENCE_CLIENT, fact
    assert q["bucket"] == BUCKET_CLIENT, fact


# ── 4.1 Step 5 - a conflicting fact is the producer's, never the client's ────

def test_conflicting_fact_is_held_for_the_producer():
    """4.1 Step 5 + core principle 4.

    Regression this pins: a conflicting fact HAS a value, so `_fact_is_filled`
    marked it "already provided" and the question vanished entirely. Nobody was
    ever asked to resolve it.
    """
    facts = {
        "applicant_name": _ai("ORBIN CONTRACTING LLC"),
        "_uw_conflicted_keys": ["applicant_name"],
    }
    q = _q("applicant_name")
    decorate_questions([q], facts=facts)
    assert q["audience"] == AUDIENCE_PRODUCER
    assert q["eligibility_reason"] == qe.REASON_CONFLICTING
    assert q["eligibility_step"] == 5
    assert q.get("producer_review") is True


def test_conflicting_beats_already_known():
    """Ordering guard. Step 5 must be evaluated BEFORE the already-known branch,
    or a conflicting fact is swallowed as "already provided" and never routed."""
    facts = {"gl_limits": _ai("$1,000,000"),
             "_uw_conflicted_keys": ["gl_limits"]}
    q = _q("gl_limits")
    decorate_questions([q], facts=facts)
    assert q["eligibility_reason"] == qe.REASON_CONFLICTING


# ── 4.1 Step 1 - not applicable means no question ───────────────────────────

def test_not_applicable_fact_is_suppressed():
    facts = {"umbrella_limit": {"value": "", "not_applicable": True}}
    q = _q("umbrella_limit")
    decorate_questions([q], facts=facts)
    assert q["suppressed"] is True


# ── THE TWO STRUCTURAL SAFETY PROPERTIES ────────────────────────────────────

def test_overlay_never_widens_client_exposure():
    """The door may move a question away from the client, never toward it.

    Driven over every registry fact rather than a sample, so a future edit to
    INSURANCE_JUDGMENT_FACTS or to the overlay cannot quietly reverse a route.
    """
    from services.fact_registry import FACT_REGISTRY
    for key in FACT_REGISTRY:
        q = _q(key)
        before = q["audience"]
        decorate_questions([q], facts={key: _ai("x")})
        after = q["audience"]
        if before != AUDIENCE_CLIENT:
            assert after != AUDIENCE_CLIENT, (
                f"{key} was {before} and the overlay moved it to the client")


def test_no_judgment_fact_lands_in_a_hidden_bucket():
    """The Underwriting bucket is hidden in the producer UI (client request).

    Anything routed there today is invisible to the producer AND the client, so
    a producer-routed question must land in AGENCY, which renders
    unconditionally (AcordModal.jsx: the Agency bucket has no SHOW_ flag).
    """
    for key in sorted(qe.INSURANCE_JUDGMENT_FACTS):
        q = _q(key)
        decorate_questions([q], facts={key: _ai("x")})
        assert q["bucket"] == BUCKET_AGENCY, (
            f"{key} routed to bucket={q['bucket']}, which is hidden in the "
            f"producer UI - it would be invisible to everyone")


# ── ANTI-ROT ────────────────────────────────────────────────────────────────

def test_every_judgment_fact_is_a_real_registry_fact():
    """A typo in the routing table would silently route nothing at all."""
    from services.fact_registry import FACT_REGISTRY
    unknown = sorted(k for k in qe.INSURANCE_JUDGMENT_FACTS
                     if k not in FACT_REGISTRY)
    assert not unknown, f"not real canonical facts: {unknown}"


def test_client_eligible_table_is_a_real_registry_fact():
    from services.fact_registry import FACT_REGISTRY
    unknown = sorted(k for k in qe.CLIENT_ELIGIBLE_DESPITE_TOPIC
                     if k not in FACT_REGISTRY)
    assert not unknown, f"not real canonical facts: {unknown}"


def test_the_two_tables_never_overlap():
    """A fact in both tables would make routing depend on evaluation order."""
    both = qe.INSURANCE_JUDGMENT_FACTS & qe.CLIENT_ELIGIBLE_DESPITE_TOPIC
    assert not both, f"a fact cannot be both client-eligible and producer-only: {both}"


def test_missing_facts_argument_changes_nothing():
    """Every legacy caller omits `facts`; that must stay byte-identical."""
    q1, q2 = _q("gl_limits"), _q("gl_limits")
    decorate_questions([q1])                      # legacy call - no facts
    decorate_questions([q2], facts={"gl_limits": _ai("$1M")})
    assert q1["audience"] == AUDIENCE_CLIENT      # unchanged old behaviour
    assert q2["audience"] == AUDIENCE_PRODUCER    # new behaviour, opted in


def test_overlay_failure_leaves_questions_untouched():
    """Fail-open: a broken overlay must never delete a question."""
    q = _q("applicant_name")
    qs = [q]
    decorate_questions(qs, facts={"applicant_name": "not-an-envelope"})
    assert len(qs) == 1
    assert qs[0]["field_name"] == "applicant_name"


# ── LIVE-RUN REGRESSIONS (C4 test session, 2026-08-26) ──────────────────────
# Each of these reproduces a defect the live click-through found, using the
# literal field name the real schema uses. Replaying the client's own values is
# the standing rule here - a fix can pass every synthetic test and still fail
# the reported case.

def test_sic_on_acord_130_reaches_the_producer():
    """S2: `NamedInsured_SICCode_A` lowercases to `namedinsured_siccode_a`,
    which does NOT contain the `_PRODUCER_PATTERNS` entry "sic_code" (pattern
    has an underscore, ACORD's name does not). It reached the CLIENT bucket."""
    q = _q("NamedInsured_SICCode_A", canonical="sic_code")
    decorate_questions([q], facts={})
    assert q["audience"] == AUDIENCE_PRODUCER
    assert q["bucket"] == BUCKET_AGENCY


def test_emod_question_reaches_the_producer():
    """S4: the narrative "target markets" key asks *"What is your workers comp
    experience modifier (EMOD / XMOD)?"* - an X-Mod question under a narrative
    key, so `wc_xmod` never matched it. 4.4/4.10 make X-Mod producer-only."""
    from services import arq_service
    text = arq_service._FIELD_QUESTION_MAP.get("narrative_target_markets", "")
    assert "experience modifier" in text.lower(), (
        "this key no longer asks for the EMOD - re-check whether it still "
        "belongs in INSURANCE_JUDGMENT_QUESTION_KEYS")
    q = _q("narrative_target_markets")
    decorate_questions([q], facts={})
    assert q["audience"] == AUDIENCE_PRODUCER


def test_no_vehicle_schedule_on_forms_without_a_capturable_column():
    """S4/S6: ACORD 131 and ACORD 25 raised "Please list the vehicles to be
    insured" at the client. Their `Vehicle_*` fields are umbrella underlying
    limits and certificate coverage indicators - not fleet rows."""
    import json
    from pathlib import Path
    from services import schedule_capture as sc
    from services.arq_service import _schedule_key_for_question_field

    root = Path(__file__).resolve().parents[1] / "forms_schemas"
    def _capturable(fid):
        schema = json.loads((root / f"{fid}_schema.json").read_text(encoding="utf-8"))
        return [f for f in schema
                if _schedule_key_for_question_field(f) == "auto_vin_schedule"
                and sc.binds_a_capturable_column(f)]

    assert not _capturable("ACORD_131"), "umbrella has no vehicle schedule"
    assert not _capturable("ACORD_25"), "a certificate has no vehicle schedule"
    # The control: the real auto form must be untouched by the same predicate.
    assert len(_capturable("ACORD_127")) >= 10, (
        "ACORD 127's genuine vehicle schedule must still be capturable")


def test_partition_does_not_lose_a_field_it_declines_to_collapse():
    """The fix must never silently drop a field. A form with no capturable
    column keeps its fields in `missing_fields` for the ordinary question path."""
    from services.arq_service import _partition_schedule_fields
    missing = {"Vehicle_CombinedSingleLimit_EachAccidentAmount_A": {"ACORD_131"}}
    values = {"Vehicle_CombinedSingleLimit_EachAccidentAmount_A": ""}
    out = _partition_schedule_fields(missing, values)
    assert out == {}, "no vehicle schedule should be raised for ACORD 131"
    assert "Vehicle_CombinedSingleLimit_EachAccidentAmount_A" in missing, (
        "the field was collapsed into a schedule that was never asked - "
        "that is silent data loss")


def test_judgment_question_keys_are_not_registry_facts():
    """Anti-rot: anything that IS a canonical fact belongs in the main table,
    so the two never drift into being two copies of one rule."""
    from services.fact_registry import FACT_REGISTRY
    overlap = sorted(k for k in qe.INSURANCE_JUDGMENT_QUESTION_KEYS
                     if k in FACT_REGISTRY)
    assert not overlap, (
        f"these are real facts and belong in INSURANCE_JUDGMENT_FACTS: {overlap}")


# ── LIVE-RUN REGRESSIONS, ROUND 2 (C4 test session, 2026-08-26) ─────────────

def test_acord130_locations_collapse_into_the_table():
    """S2 produced TWENTY ordinal location cards on ACORD 130.

    Root cause was NOT the questionnaire: the `Location_PhysicalAddress_*`
    family was never registered in `pdf_service._SCHEDULE_REGISTRY`, so those
    addresses could not be stamped on ACORD 130/133/160/28 either.
    """
    import json
    from pathlib import Path
    from services import schedule_capture as sc
    from services.arq_service import _schedule_key_for_question_field

    root = Path(__file__).resolve().parents[1] / "forms_schemas"
    for fid in ("ACORD_130", "ACORD_133", "ACORD_160", "ACORD_28"):
        schema = json.loads((root / f"{fid}_schema.json").read_text(encoding="utf-8"))
        capturable = [f for f in schema
                      if _schedule_key_for_question_field(f) == "property_locations"
                      and sc.binds_a_capturable_column(f)]
        assert capturable, (
            f"{fid} has location address fields that bind to no capturable "
            f"column - they will explode into one ordinal card per row")


def test_selecting_the_section_form_restores_its_questions():
    """S7 run B: property was declined on the dec page AND ACORD 140 was
    selected, yet every property question stayed suppressed - the form shipped
    blank and unaskable, which the filter's own docstring forbids."""
    from services.fact_state import is_not_applicable, is_not_applicable_for
    facts = {"coverage_lines": [
        {"line": "Commercial Property", "status": "NO COVERAGE", "premium": "$0"},
        {"line": "Commercial General Liability", "status": "Included",
         "premium": "$8,940"},
    ]}
    for key in ("construction_type", "year_built", "property_building_value"):
        assert is_not_applicable(facts, key), f"{key}: documents do decline it"
        assert is_not_applicable_for(facts, key, ["ACORD_125", "ACORD_126"]), \
            f"{key}: with no property form selected it stays suppressed"
        assert not is_not_applicable_for(
            facts, key, ["ACORD_125", "ACORD_126", "ACORD_140"]), (
            f"{key}: ACORD 140 was selected, so the producer IS applying for "
            f"property and the question must come back")


def test_an_explicit_not_applicable_envelope_is_never_overridden():
    """The form override applies to a LINE-level inference, never to a fact a
    human explicitly marked not applicable."""
    from services.fact_state import is_not_applicable_for
    facts = {"construction_type": {"value": "", "not_applicable": True}}
    assert is_not_applicable_for(facts, "construction_type",
                                 ["ACORD_125", "ACORD_140"])


def test_a_conflicted_fact_still_produces_a_producer_question():
    """S5: two documents disagreed on revenue, the engine flagged it, and the
    producer screen said "All clear" - the conflict was detected and then
    dropped, because a conflicted fact HAS a value and was suppressed as
    already-provided before any question could be built."""
    facts = {
        "total_revenue": _ai("$2,400,000"),
        "_uw_conflicted_keys": ["total_revenue"],
    }
    q = _q("total_revenue")
    decorate_questions([q], facts=facts)
    assert q["audience"] == AUDIENCE_PRODUCER
    assert q["bucket"] == BUCKET_AGENCY
    assert q["eligibility_reason"] == qe.REASON_CONFLICTING


def test_acord127_has_a_field_inventory():
    """S3 asked nobody for the auto liability limit, deductibles, physical
    damage valuation or covered-auto symbols. ACORD 127 was the ONLY form whose
    FORM_FIELD_INVENTORY was empty, and that table is what the
    coverage-guarantee injector walks."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    from services.arq_service import _FIELD_QUESTION_MAP
    inv = FORM_FIELD_INVENTORY.get("ACORD_127") or []
    assert inv, "ACORD 127 must have a field inventory"
    for key in ("auto_liability_limit", "auto_covered_symbols",
                "auto_deductible_comp", "auto_deductible_collision",
                "auto_physical_damage_valuation"):
        assert key in inv, f"{key} missing from the ACORD 127 inventory"
        assert key in _FIELD_QUESTION_MAP, (
            f"{key} is in the inventory but has no curated question, so the "
            f"coverage-guarantee injector will silently skip it")


def test_no_form_has_an_empty_inventory():
    """ANTI-ROT. An empty inventory is invisible: it produces no question and
    no error. ACORD 127 sat empty until a live run exposed it."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    empty = sorted(k for k, v in FORM_FIELD_INVENTORY.items() if not v)
    assert not empty, f"these forms can never generate a question: {empty}"


# ── ROUND 3 (2026-08-26): the two deferred residuals + the S5 root cause ────

def test_conflicting_is_reachable_from_the_superset_key():
    """THE S5 ROOT CAUSE. `derive_value_state` only read `_uw_conflicted_keys`,
    which is built from `unresolved_withheld_keys` and filtered by
    `CONFLICT_WITHHOLD_KEYS` - a frozenset that is EMPTY by Brent's Q4/D16
    ruling. So the key was never populated and `value_state == conflicting`
    was unreachable in production. The real set is `_uw_conflict_keys`."""
    from services.fact_state import value_state_of, CONFLICTING
    from services.underwriting_consistency import CONFLICT_WITHHOLD_KEYS
    assert not CONFLICT_WITHHOLD_KEYS, (
        "CONFLICT_WITHHOLD_KEYS is no longer empty - re-check that the "
        "superset key is still the right signal for `conflicting`")
    facts = {"total_revenue": _ai("$2,400,000"),
             "_uw_conflict_keys": ["total_revenue"]}
    assert value_state_of(facts, "total_revenue") == CONFLICTING
    q = _q("total_revenue")
    decorate_questions([q], facts=facts)
    assert q["audience"] == AUDIENCE_PRODUCER
    assert q["eligibility_reason"] == qe.REASON_CONFLICTING


def test_covered_auto_symbols_are_not_a_client_table_column():
    """4.9 / principle 5: symbols are a producer decision. They had a producer
    question AND remained columns in the client's vehicle table - two routes,
    one of them to the wrong audience."""
    from services import schedule_capture as sc
    cols = sc.get_def("auto_vin_schedule")["columns"]
    by_key = {c["key"]: c for c in cols}
    for key in ("comp_symbol", "coll_symbol"):
        assert by_key[key].get("producer_only") is True, (
            f"{key} must be producer-only")
    client_cols = [c["key"] for c in cols if not c.get("producer_only")]
    assert "comp_symbol" not in client_cols and "coll_symbol" not in client_cols
    # The client must still get the columns that ARE theirs under 4.9.
    for key in ("year", "make", "model", "vin"):
        assert key in client_cols, f"{key} is a client fact and must remain"


def test_umbrella_structure_is_asked_of_the_producer():
    """4.11 named seven umbrella items; ACORD 131's inventory carried two, so
    attachment point, follow-form, the Schedule of Underlying Insurance and the
    Employers Liability limits surfaced no question for anyone (C4 test S4)."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    from services.arq_service import _FIELD_QUESTION_MAP
    inv = FORM_FIELD_INVENTORY["ACORD_131"]
    for key in ("umbrella_limit", "umbrella_sir", "umbrella_attachment_point",
                "umbrella_follow_form", "underlying_policies",
                "employers_liability_limits"):
        assert key in inv, f"{key} missing from the ACORD 131 inventory"
        assert key in _FIELD_QUESTION_MAP, f"{key} has no curated question"
        q = _q(key)
        decorate_questions([q], facts={})
        assert q["audience"] == AUDIENCE_PRODUCER, key
        assert q["bucket"] == BUCKET_AGENCY, key


def test_every_inventory_fact_has_a_question_or_is_a_schedule():
    """ANTI-ROT for the shape that bit ACORD 127 AND ACORD 131: an inventory
    entry with no curated question is silently skipped by the
    coverage-guarantee injector - no question, no error."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    # The SAME door the injector gates on - not `_FIELD_QUESTION_MAP` directly.
    # A test that checks a different table than production reads is how 19 facts
    # with a perfectly good registry question stayed invisible.
    from services.arq_service import _curated_question_for
    from services.schedule_capture import SCHEDULE_DEFS
    # KNOWN BACKLOG, measured 2026-08-26. Writing this test surfaced 54 entries
    # across 12 forms in the same shape that hid the ACORD 127 and ACORD 131
    # gaps: an inventory entry with no curated question is skipped in silence.
    # They are NOT fixed - each needs real plain-language wording and an
    # audience decision, which is a product call, not a rename. Pinned here so
    # the count can only go DOWN: any NEW entry fails the build immediately.
    # Recorded rather than hidden, per the repo's no-silent-caps rule.
    # BACKLOG CLOSED 2026-08-26. This started at 54 entries. The fix was not 54
    # hand-written strings: 19 already had a question in `FACT_REGISTRY` that
    # the injector never read (see `arq_service._curated_question_for`), 18 were
    # inventory keys naming facts that DO NOT EXIST and were remapped to the
    # real ones, and 5 named nothing at all and were removed. An empty set is
    # now the contract - any regression on either side fails immediately.
    KNOWN_WITHOUT_A_QUESTION = set()
    missing = []
    for fid, inv in FORM_FIELD_INVENTORY.items():
        for key in inv:
            if _curated_question_for(key) or key in SCHEDULE_DEFS:
                continue
            missing.append(f"{fid}:{key}")
    new_gaps = sorted(set(missing) - KNOWN_WITHOUT_A_QUESTION)
    assert not new_gaps, (
        "NEW inventory entries with no curated question - the coverage-guarantee "
        f"injector will skip them silently: {new_gaps}")
    fixed = sorted(KNOWN_WITHOUT_A_QUESTION - set(missing))
    assert not fixed, (
        "these now have questions - remove them from KNOWN_WITHOUT_A_QUESTION "
        f"so the ratchet keeps tightening: {fixed}")


# ── ROUND 4 (2026-08-26): Step 2/3 made real, and the two question tables ───

def test_text_verification_makes_source_verified_reachable():
    """4.1 Step 2 vs Step 3. Before this, `verified_in_text` had ONE writer in
    the whole backend, so virtually every fact was `suggested` and "Source
    Verified" was unreachable - the two steps could not be told apart."""
    from services.fact_state import (
        annotate_text_verification, derive_evidence_state,
        SOURCE_VERIFIED, SUGGESTED, USER_CONFIRMED,
    )
    facts = {
        "applicant_name": _ai("Harborlight Catering LLC"),   # in the text
        "total_revenue":  _ai("$2,400,000"),                  # in the text
        "naics_code":     _ai("722320"),                      # NOT in the text
        "num_employees":  _ai("34"),                          # too short
        "entity_type":    {"value": "LLC", "source": "client_arq"},
    }
    docs = [{"text": "Named Insured: Harborlight Catering LLC\n"
                     "Annual Gross Sales: $2,400,000\nEmployees: 34"}]
    assert annotate_text_verification(facts, docs) == 2
    assert derive_evidence_state(facts["applicant_name"])[0] == SOURCE_VERIFIED
    assert derive_evidence_state(facts["total_revenue"])[0] == SOURCE_VERIFIED
    # Guard 1: absent from the text is left alone, never marked unverified.
    assert derive_evidence_state(facts["naics_code"])[0] == SUGGESTED
    # Guard 3: "34" appears, but a 2-char value matches by accident in almost
    # any document. A FALSE verification is worse than none - Step 2 uses it to
    # stop asking.
    assert derive_evidence_state(facts["num_employees"])[0] == SUGGESTED
    # Guard 2: a human answer is never relabelled as document-sourced.
    assert derive_evidence_state(facts["entity_type"])[0] == USER_CONFIRMED


def test_text_verification_never_demotes_or_removes():
    """It may only ever ADD. Running it twice, or with no documents, must not
    change a single existing label."""
    from services.fact_state import annotate_text_verification, derive_evidence_state
    facts = {"applicant_name": _ai("Acme Contracting LLC")}
    docs = [{"text": "Named Insured: Acme Contracting LLC"}]
    assert annotate_text_verification(facts, docs) == 1
    before = derive_evidence_state(facts["applicant_name"])[0]
    assert annotate_text_verification(facts, docs) == 0          # idempotent
    assert annotate_text_verification(facts, []) == 0            # no docs
    assert annotate_text_verification(facts, [{"text": "unrelated"}]) == 0
    assert derive_evidence_state(facts["applicant_name"])[0] == before


def test_excluded_documents_do_not_verify():
    """An excluded document is not evidence."""
    from services.fact_state import annotate_text_verification
    facts = {"applicant_name": _ai("Acme Contracting LLC")}
    assert annotate_text_verification(
        facts, [{"text": "Named Insured: Acme Contracting LLC",
                 "excluded": True}]) == 0


def test_registry_question_is_reachable_from_the_injector():
    """THE TWO-TABLE DEFECT. 19 facts had a good question in FACT_REGISTRY that
    the coverage-guarantee injector never read, because it gated on
    `_FIELD_QUESTION_MAP` alone. No question, no error, no way to notice."""
    from services.arq_service import _curated_question_for, _FIELD_QUESTION_MAP
    for key in ("wc_payroll_by_state", "wc_description_of_operations",
                "auto_radius_of_operation", "auto_garaging_addresses",
                "gl_form_type", "umbrella_effective_date", "new_venture_indicator"):
        assert _curated_question_for(key), f"{key} still has no question"
    # The client-tuned wording must still win where it exists.
    for key, text in list(_FIELD_QUESTION_MAP.items())[:40]:
        assert _curated_question_for(key) == text, key


def test_no_inventory_entry_names_a_fact_that_does_not_exist():
    """ANTI-ROT. 23 of 42 gap entries were not facts at all - `deductible_aop`
    for `property_deductible_aop`, `project_cost` for
    `builders_risk_project_cost`. A phantom key can never be filled or asked,
    AND it inflates the fill-rate denominator, depressing that form's score."""
    from services.sqs_service import FORM_FIELD_INVENTORY
    from services.fact_registry import FACT_REGISTRY
    from services.schedule_capture import SCHEDULE_DEFS
    ghosts = sorted({f"{fid}:{k}" for fid, inv in FORM_FIELD_INVENTORY.items()
                     for k in inv
                     if k not in FACT_REGISTRY and k not in SCHEDULE_DEFS})
    assert not ghosts, f"inventory entries naming no real fact: {ghosts}"


def test_a_fact_that_could_not_stamp_is_still_asked():
    """S1 / ACORD 140: CONSTRUCTION TYPE came back BLANK on the generated form
    AND absent from the questionnaire.

    `_backfill_and_resolve_present` computes a FORM-AWARE present set and says
    in its docstring: "if nothing could be stamped, the fact is left OUT of the
    present set so the client is still asked for it". The form scan honours
    that; the coverage-guarantee injector did not - it asked
    `_fact_is_filled(facts[key])`, true for any value sitting in `facts`
    whether or not it ever reached a box. Blank box, nobody asked.
    """
    import inspect
    from services import arq_service
    src = inspect.getsource(arq_service.generate_arq_questions)
    injector = src.split("_inv_fact_forms.items()")[1]
    assert "_present_on_form" in injector, (
        "the coverage-guarantee injector must consult the FORM-AWARE present "
        "set, not just `_fact_is_filled` - otherwise a fact that cannot stamp "
        "produces a blank box and no question")
    # And the facts-only fallback must survive for callers that supply nothing.
    assert "_fact_is_filled(facts.get(_fact_key))" in injector


# ---------------------------------------------------------------------------
# V1 BETA EXIT (2026-08-28) - "GL/WC class codes never reach the client"
# ---------------------------------------------------------------------------

def test_no_classification_question_ever_reaches_the_client():
    """Core principle 5, enforced from the QUESTIONS, not from a hand list.

    The client's beta-exit criteria name two rules outright - "NAICS/SIC never
    reach the client" and "GL/WC class codes never reach the client". Both were
    implemented as membership in `INSURANCE_JUDGMENT_FACTS`, a hand-maintained
    set, and on 2026-08-28 exactly one registry fact had been missed:
    `gl_class_code_schedule`, whose question asks the insured for a class code,
    an exposure basis, a rating territory and a subcontracted percentage.

    A list cannot guard itself. This test reads every fact's OWN question text
    and fails if anything that ASKS for a classification is not producer-routed,
    so the next repurposed slot is caught by the words it puts on the screen
    rather than by whether someone remembered to add its key.

    Deliberately matched on the ASK, not on the key name: `narrative_target_
    markets` and `narrative_growth_trends` are both real X-Mod / class-code
    questions wearing narrative keys (C4-S, H3-D), and a key-name rule is
    exactly what let those two through the first time.
    """
    import re
    from services.fact_registry import FACT_REGISTRY
    from services.question_eligibility import is_insurance_judgment

    asks_for_a_classification = re.compile(
        r"class code|classification code|"
        r"\bnaics\b|\bsic code\b|"
        r"covered.?auto symbol|coverage symbol",
        re.IGNORECASE,
    )

    leaked = []
    for key, entry in FACT_REGISTRY.items():
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "")
        if not question or not asks_for_a_classification.search(question):
            continue
        if not is_insurance_judgment(key):
            leaked.append(f"{key}: {question[:90]}")

    assert not leaked, (
        "these questions ask the CLIENT to perform an insurance "
        "classification (core principle 5 + the V1 beta-exit criteria). Add "
        "each key to INSURANCE_JUDGMENT_FACTS, or route it as a producer-only "
        "table column:\n  " + "\n  ".join(sorted(leaked))
    )


def test_the_gl_rating_schedule_is_producer_routed():
    """The literal 2026-08-28 defect, pinned by its own key.

    The derived test above would also catch it, but only while the question
    keeps its current wording. This one survives a reword.
    """
    from services.question_eligibility import is_insurance_judgment, overlay_for
    from services.question_classifier import classify_question

    assert is_insurance_judgment("gl_class_code_schedule")

    classified = classify_question(
        "gl_class_code_schedule",
        canonical_key="gl_class_code_schedule",
        is_curated_client=True,
    )
    question = dict(classified)
    question.update({
        "field_name": "gl_class_code_schedule",
        "canonical_key": "gl_class_code_schedule",
        "question": "?",
    })
    overlay = overlay_for(question, {})
    assert overlay.get("audience", classified.get("audience")) == "producer"
