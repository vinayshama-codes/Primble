"""C3 - SQS Scoring Integrity & Critical-Field Weighting (client section 3).

Guards for every rule shipped on 2026-08-25, written so a later change has to
argue with the client's own words rather than rediscover them. Read v1-20AUG.md
C3-A / C3-B / C3-C / C3-D before changing anything here.

The four that are ANTI-ROT rather than feature tests, because each pins a defect
that had already happened once:

  * `test_tier2_removals_are_still_asked_for` - removing a field from the SCORE
    silently removed it from the QUESTIONNAIRE. Measured before the fix:
    `total_payroll`, `wc_payroll_period` and `wc_officer_exclusions` all fell to
    audience=internal / priority=suppressed.
  * `test_the_trace_reconciles_*` - the displayed breakdown was computed from a
    different set of facts than the pillar and could never sum to it.
  * `test_one_improvement_earns_one_credit` - several recommendations can point
    at ONE fact, so one gap could be paid for twice.
  * `test_no_fact_is_deducted_in_two_pillars` - the double counts the client
    asked us to be able to rule out.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import sqs_service as sq                        # noqa: E402
from services.answer_semantics import (                       # noqa: E402
    build_fact_envelope, interpret_answer,
)


# ── 3.1 / 3.2 / 3.7 - the weights themselves ────────────────────────────────

def test_pillar_weights_are_unchanged_for_v1():
    """3.1: *"Do not change these top-level weights during this V1 pass."*"""
    assert sq.SPEC_PILLAR_WEIGHTS == {
        "structural_completeness": 0.25,
        "exposure_consistency":    0.25,
        "property_integrity":      0.15,
        "loss_history_alignment":  0.15,
        "umbrella_limit_adequacy": 0.10,
        "narrative_quality":       0.10,
    }
    assert sum(sq.SPEC_PILLAR_WEIGHTS.values()) == pytest.approx(1.0)


def test_structural_blend_is_40_35_25():
    """3.2: Tier 1 x 40% + Tier 2 x 35% + Form Fill Rate x 25%."""
    assert (sq._W_TIER1, sq._W_TIER2, sq._W_FILL) == (0.40, 0.35, 0.25)
    assert sq._W_TIER1 + sq._W_TIER2 + sq._W_FILL == pytest.approx(1.0)


def test_no_form_rescale_matches_the_client_figures():
    """3.7: Tier 1 = 53.3%, Tier 2 = 46.7%, *"preserving the 40:35"*."""
    assert sq._W_NOFORM_TIER1 == 0.533
    assert sq._W_NOFORM_TIER2 == 0.467
    # DERIVED, not typed - the ratio must survive a change to 3.2's weights.
    # rel=1e-2 absorbs the 3-dp rounding the client's own figures carry
    # (0.533/0.467 = 1.1413 against 40/35 = 1.1429).
    assert sq._W_NOFORM_TIER1 / sq._W_NOFORM_TIER2 == pytest.approx(
        sq._W_TIER1 / sq._W_TIER2, rel=1e-2)


# ── 3.5 / 3.14 - Tier 2, and what removal must NOT cost us ──────────────────

def test_tier2_is_exactly_the_six_general_business_fields():
    assert set(sq.TIER2_FIELDS) == {
        "fein", "operations_description", "total_revenue",
        "num_employees", "years_in_business", "naics_code",
    }


def test_tier2_removals_are_still_asked_for():
    """ANTI-ROT. Removing a field from the SCORE must never stop us ASKING.

    Measured 2026-08-25 with the removal simulated and no pin in place:
    `total_payroll`, `wc_payroll_period` and `wc_officer_exclusions` all became
    audience=internal / priority=suppressed - Primble would have quietly
    stopped asking anyone for annual payroll, which is a far worse regression
    than the scoring bug 3.14 fixes.

    UPDATED 2026-08-26. The property being pinned is "we still ASK", not "we ask
    the CLIENT". Master plan 4.4 moved X-Mod, WC payroll period and owner/officer
    treatment to the producer, so three of these five now legitimately carry
    audience=producer. They are still asked - they render in the producer's
    Agency bucket - which is exactly what this anti-rot test exists to protect.
    `total_payroll` and `num_claims` remain client-eligible per 4.3.
    """
    from services.question_classifier import classify_question, decorate_questions

    def _decorated(field):
        q = {"field_name": field, "_canonical_key": field,
             "_is_curated_client": True}
        q.update(classify_question(field, canonical_key=field,
                                   is_curated_client=True))
        decorate_questions([q], facts={})
        return q

    # Still asked of the CLIENT (4.3: payroll, prior claims).
    for field in ("total_payroll", "num_claims"):
        res = _decorated(field)
        assert res["audience"] == "client", (
            f"{field} was removed from Structural Tier 2 but must still be "
            f"asked of the client - got audience={res['audience']}"
        )
        assert not res["suppressed"], f"{field} must not be suppressed"

    # Still asked, but of the PRODUCER (4.4: X-Mod, WC payroll period,
    # owner/officer treatment are insurance judgment).
    for field in ("wc_xmod", "wc_payroll_period", "wc_officer_exclusions"):
        res = _decorated(field)
        assert res["audience"] == "producer", (
            f"{field} must still be asked, of the producer - got "
            f"audience={res['audience']}"
        )
        assert res["bucket"] == "agency", (
            f"{field} must land in the visible Agency bucket, not the hidden "
            f"Underwriting one - got bucket={res['bucket']}"
        )


def test_wc_fields_keep_a_scoring_home_on_the_wc_form():
    """3.14: *"handled through WC/Exposure rules instead"* - verify, don't assume.

    ACORD 130 is the Workers Comp form, and its own checklist is where the
    client's *"closer to the exposure they describe"* actually lands.
    """
    import inspect
    src = inspect.getsource(sq.calculate_sqs)
    acord130 = src.split('elif fid == "ACORD_130"')[1].split("elif fid ==")[0]
    for field in ("wc_payroll", "wc_xmod", "wc_officer_exclusions"):
        assert field in acord130, (
            f"{field} left Structural Tier 2 and must still be scored on the "
            f"ACORD 130 checklist"
        )


# ── 3.3 / 3.4 - Tier 1 applicability ────────────────────────────────────────

def test_producer_name_is_exempt_only_when_the_dec_page_is_the_only_document():
    """3.3 and spec section 3.1, identical wording: *"the ONLY source document"*."""
    assert sq.producer_fields_exempt({"_only_dec_page": True}) is True
    assert sq.producer_fields_exempt({"_doc_type": "dec_page"}) is False
    assert sq.producer_fields_exempt({}) is False
    assert sq.producer_fields_exempt(None) is False


def test_contact_information_is_never_exempt():
    """3.3 lists producer name as the only dec-page exemption."""
    facts = {"applicant_name": "Acme LLC", "mailing_address": "1 Main St",
             "effective_date": "2026-07-15", "lines_of_business": ["GL"],
             "entity_type": "LLC"}
    ok, missing = sq.check_tier1(facts, {"_only_dec_page": True})
    assert not ok
    assert "Contact information" in missing
    assert "Producer / Agency name" not in missing, "producer name IS exempt"


def test_an_exempt_card_advertises_exactly_zero_points():
    """LIVE DEFECT, S1, 2026-08-25: the exempt producer-name card read
    "up to +5 pts" on a dec-page-only submission.

    `_measure_recommendation_impacts` correctly MEASURED no movement, then fell
    back to the typed literal - its "no movement" branch cannot tell a genuine
    zero from a probe of the wrong shape. The emitter knows the check was
    excluded from the pillar, so it now says so with `unscored`.

    The original version of this test passed while the bug was live, because its
    fixture supplied contact_name and the pillar sat at 100 - zero headroom made
    the fallback return 0 for the wrong reason. This one leaves contact MISSING,
    so there is real headroom for a bad fallback to claim.
    """
    facts = {"applicant_name": "HARBOR POINT ELECTRIC LLC",
             "mailing_address": "2140 Wharf Road, Portland ME 04101",
             "effective_date": "2026-09-15",
             "lines_of_business": ["General Liability"],
             "entity_type": "LLC"}
    res = sq.calculate_sqs(
        facts=facts, flags={"_only_dec_page": True}, mapped_data={"a": "x"},
        form_schema={"a": {}}, selected_form_ids=["ACORD_125"],
        hard_stops=[], soft_stops=[], tier2_score=100, form_id="ACORD_125")
    by_field = {r.get("field"): r for r in res["recommendations"]}

    prod = by_field.get("producer_name")
    assert prod is not None, "the card is still RAISED - we still want the name"
    assert prod["score_impact"] == 0, (
        f"producer name is exempt here, so it cannot move the score "
        f"(got {prod['score_impact']})"
    )
    assert prod.get("impact_is_exact") is True, "zero is a measurement, not a hedge"

    contact = by_field.get("contact_name")
    assert contact and contact["score_impact"] > 0, (
        "contact information IS scored on every submission, so its card must "
        "carry real points - otherwise this test would pass on a scorer that "
        "simply zeroed everything"
    )


def test_only_dec_page_flag_needs_every_document_to_be_a_dec_page():
    """The flag's own contract, at its writer."""
    import inspect
    from services import extraction_pipeline
    src = inspect.getsource(extraction_pipeline)
    assert '_only_dec_page' in src
    assert 'all(' in src.split('_only_dec_page')[1][:400], (
        "must require EVERY active document to be a dec page"
    )


# ── 3.6 - Not Applicable leaves the denominator ─────────────────────────────

def _na(key):
    return build_fact_envelope(key, interpret_answer(key, "N/A"), "producer", "filled")


def test_not_applicable_leaves_the_tier2_denominator():
    facts = {f: "x" for f in sq.TIER2_FIELDS}
    facts["fein"] = _na("fein")
    del facts["years_in_business"]
    score, _ = sq.check_tier2(facts, {})
    assert score == 80, "100 - 100/5, not 100 - 100/6"


def test_a_human_recorded_state_survives_the_derivation():
    """The seam this needed: two modules, two envelope vocabularies.

    `answer_semantics` stores an answered N/A as value "" + value_state
    "not_applicable"; `fact_state.derive_value_state` re-derives from signals
    and looked only for an older `not_applicable: True` flag, so it returned
    `not_stated` and 3.6 was unreachable for any human answer.
    """
    from services.fact_state import is_not_applicable, value_state_of
    facts = {"total_revenue": _na("total_revenue")}
    assert is_not_applicable(facts, "total_revenue") is True

    absent = {"prior_carrier": build_fact_envelope(
        "prior_carrier", interpret_answer("prior_carrier", "None"),
        "producer", "filled")}
    assert value_state_of(absent, "prior_carrier") == "explicit_no"

    # ...and it can only ever REFINE a blank, never override a real value.
    real = {"total_revenue": {"value": "2000000", "value_state": "not_applicable"}}
    assert value_state_of(real, "total_revenue") == "present"


# ── 3.8 - the four fill-rate rules ──────────────────────────────────────────

def test_not_applicable_cannot_reduce_the_fill_rate():
    """Measured before the fix: 100 with one good field, 75 once an N/A joined."""
    assert sq.confidence_fill_rate(
        {"a": "Acme", "b": "N/A"},
        {"a": "filled", "b": "not_applicable"}) == 100


def test_an_explicit_no_is_a_completed_response():
    """Measured before the fix: a box holding "None" scored 0."""
    assert sq.confidence_fill_rate({"a": "None"}, {"a": "explicit_no"}) == 100
    # ...but only via the LABEL. A stringified Python None is still not credit.
    assert sq.confidence_fill_rate({"a": "None"}, {"a": "filled"}) == 0


def test_a_conflicting_field_does_not_get_full_credit():
    full = sq.confidence_fill_rate({"a": "Acme"}, {"a": "filled"})
    conf = sq.confidence_fill_rate({"a": "Acme"}, {"a": "conflicted"})
    assert 0 < conf < full


def test_a_suggested_value_never_equals_a_verified_one():
    assert sq.CONFIDENCE_SCORE["ai_verified"] < sq.CONFIDENCE_SCORE["filled"]
    assert sq.CONFIDENCE_SCORE["low_confidence"] < sq.CONFIDENCE_SCORE["client_arq"]


# ── 3.9 - ceilings, unchanged and re-pinned to the client's own examples ────

@pytest.mark.parametrize("raw,cap,expected", [
    (88, 60, 60),    # "Raw 88 + hard stop -> displays 60"
    (88, 85, 85),    # "Raw 88 + warnings only -> displays 85"
    (42, 60, 42),    # "Raw 42 + hard stop -> displays 42" - never a floor
    (93, None, 93),  # "Raw 93 + no conditions -> displays 93"
])
def test_the_clients_four_ceiling_examples(raw, cap, expected):
    assert sq.final_score_with_credits(raw, 0, cap) == expected


def test_ceilings_do_not_stack():
    """*"One hard stop and ten hard stops still produce a ceiling of 60."*"""
    one, _ = sq._resolve_cap(["a"], [])
    ten, _ = sq._resolve_cap([f"stop {i}" for i in range(10)], ["w"] * 5)
    assert one == ten == 60


# ── 3.11 - credits ──────────────────────────────────────────────────────────

def test_credits_are_added_to_the_raw_score_before_the_ceiling():
    """*"applied to the raw score before ceilings"* - owner's worked example."""
    assert sq.final_score_with_credits(65, 10, 60) == 60    # cap still binds
    assert sq.final_score_with_credits(65, 10, None) == 75  # cap cleared -> 75


def test_one_improvement_earns_one_credit(monkeypatch):
    """ANTI-ROT for 3.11's *"never stack on top of the same improvement twice"*.

    Four different loss-history messages resolve to `loss_history_years`, each
    with its own stable rec_id, so two cards about ONE missing fact could each
    be dismissed for credit.
    """
    from services import audit_service

    rows = [
        {"rec_id": "rec_a", "field": "loss_history_years",
         "override_reason": "client cannot obtain", "score_impact": 8},
        {"rec_id": "rec_b", "field": "loss_history_years",
         "override_reason": "same gap, different card", "score_impact": 5},
        {"rec_id": "rec_c", "field": "fein",
         "override_reason": "will follow", "score_impact": 4},
    ]

    async def _fake(_sid):
        return rows

    monkeypatch.setattr(audit_service, "get_dismissed_recommendations", _fake)
    total, kept = asyncio.run(audit_service.active_score_credits("s1", facts={}))

    assert total == 12, "8 (the larger of the two) + 4, never 8 + 5 + 4"
    assert {r["rec_id"] for r in kept} == {"rec_a", "rec_c"}


def test_a_credit_retires_once_the_field_is_filled(monkeypatch):
    from services import audit_service

    async def _fake(_sid):
        return [{"rec_id": "r", "field": "fein",
                 "override_reason": "will follow", "score_impact": 9}]

    monkeypatch.setattr(audit_service, "get_dismissed_recommendations", _fake)
    total, _ = asyncio.run(audit_service.active_score_credits(
        "s1", facts={"fein": "12-3456789"}))
    assert total == 0, "the pillar awards those points directly now"


def test_the_dismiss_credit_response_survives_its_own_logging():
    """LIVE DEFECT, S8, 2026-08-26: "+6 pts credited" and the score never moved.

    `_apply_dismiss_score_credit` bound `pkg_base` only inside its LEGACY branch
    but interpolated it unconditionally in the log line below - so on every
    session scored since `raw_sqs_score` shipped (2026-08-16) that f-string
    raised UnboundLocalError, the blanket `except` swallowed it, and the
    function returned `new_package_sqs_score: None`. The database UPDATE runs
    BEFORE the log line, so the credit was really applied and simply never
    reached the response.

    Two structural guarantees, asserted on the source because the function needs
    a live database to run:
      1. `pkg_base` is bound on BOTH branches;
      2. the success log sits in its own try, so no diagnostic can ever again
         convert a completed credit into a null result.
    """
    import inspect
    from routes import audit_routes

    src = inspect.getsource(audit_routes._apply_dismiss_score_credit)
    body = src[src.index("existing_pkg_raw is not None"):]
    branch = body[:body.index("_grade_from_score")]
    assert branch.count("pkg_base") >= 2, (
        "pkg_base must be assigned on the modern branch as well as the legacy "
        "one - the log line below reads it unconditionally"
    )

    tail = src[src.index("Dismiss credit applied"):]
    assert "except Exception" in tail[:600], (
        "the success log must sit inside its own try: a broken diagnostic must "
        "never turn an applied credit into new_package_sqs_score=None"
    )


def test_no_live_sql_expands_jsonb_behind_only_a_coalesce():
    """ANTI-ROT for the defect that cost four live test runs (2026-08-26).

    `COALESCE(x, '[]'::jsonb)` substitutes only when x is SQL NULL. A stored
    JSON **null** - what a session carries whenever a list was written as
    `None` - is a valid jsonb value, sails through COALESCE, and reaches
    `jsonb_array_elements` as a scalar:

        asyncpg.exceptions.InvalidParameterValueError:
            cannot extract elements from a scalar

    In `_apply_dismiss_score_credit` that threw BEFORE the package UPDATE, the
    blanket handler returned `new_package_sqs_score: None`, and the producer
    watched a card announce "+6 pts credited" beside a score that never moved.

    `jsonb_typeof(...) = 'array'` (or `'object'`) is the only test that means
    "is this really a list". Scanned across live code because the same landmine
    sat in four other queries waiting for a different session shape.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in list((root / "routes").glob("*.py")) + \
                list((root / "repositories").glob("*.py")) + \
                list((root / "services").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # An expansion whose argument is a bare COALESCE - no jsonb_typeof guard.
        for m in re.finditer(
            r"jsonb_(?:array_elements|each|array_length)\s*\(\s*COALESCE", text
        ):
            line = text[:m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")

    assert offenders == [], (
        "jsonb expansion guarded only by COALESCE - a stored JSON null will "
        f"raise 'cannot extract elements from a scalar' at: {offenders}. "
        "Use CASE WHEN jsonb_typeof(x) = 'array' THEN x ELSE '[]'::jsonb END."
    )


def test_crediting_a_score_moves_its_trace_with_it():
    """LIVE DEFECT, S8 step C, 2026-08-26: "81 earned = 85".

    A credit changes a score WITHOUT re-running the scorer, so nothing forces
    the trace to keep up. Dismissing rendered a correct
    "81 earned + 6 credited, held at 85 = 85"; editing any field then rebuilt
    the score (fresh trace, credits 0), re-applied the credit to the headline
    only, and put "81 earned = 85" back - broken arithmetic in the one panel
    built to make the arithmetic reconcile.
    """
    sqs = {
        "package_sqs_score": 81,
        "raw_sqs_score": 81,
        "score_trace": {"arithmetic": {"raw": 81, "credits": 0,
                                       "ceiling": 85, "displayed": 81}},
    }
    sq.apply_credits_to_score(sqs, 6, 85, "package_sqs_score")

    assert sqs["package_sqs_score"] == 85, "81 + 6 = 87, held at the 85 ceiling"
    assert sqs["credits_applied"] == 6
    a = sqs["score_trace"]["arithmetic"]
    assert (a["credits"], a["displayed"], a["ceiling"]) == (6, 85, 85), (
        "the trace must carry the SAME credit and the SAME displayed score as "
        "the headline, or the How line prints a sum that does not add up"
    )
    assert a["raw"] + a["credits"] >= a["displayed"], "raw + credits reaches the display"

    # No raw score (legacy payload) - returned untouched rather than guessed at.
    legacy = {"package_sqs_score": 70}
    assert sq.apply_credits_to_score(legacy, 6, None, "package_sqs_score") == legacy


def test_no_path_credits_a_score_without_the_one_door():
    """ANTI-ROT. FOUR copies each patched the headline and left the trace stale.

    C3-H warned that "any future patch-the-headline path has the same hazard"
    and then did not guard it, so the next run reproduced the defect on a
    different path. `apply_credits_to_score` is now the only way in.
    """
    import inspect
    from routes import form_routes
    from services import arq_service

    for mod in (form_routes, arq_service):
        src = inspect.getsource(mod)
        assert "apply_credits_to_score" in src, (
            f"{mod.__name__} credits scores and must go through the one door"
        )
        assert "final_score_with_credits" not in src, (
            f"{mod.__name__} calls final_score_with_credits directly - that "
            f"updates the headline while leaving score_trace stale. Use "
            f"apply_credits_to_score, which moves both together"
        )


def test_every_rebuild_path_re_applies_credits():
    """ANTI-ROT. Spec section 8 step 7, and 3.11's *"survive recalculation"*.

    `form_routes.update_pdf` rebuilt every score and skipped this, so a field
    edit destroyed points a producer had legitimately earned. Only
    `recalculate_session_scores` had it.
    """
    import inspect
    from routes import form_routes
    from services import arq_service

    for mod in (form_routes, arq_service):
        assert "active_score_credits" in inspect.getsource(mod), (
            f"{mod.__name__} rebuilds scores and must re-apply outstanding "
            f"credits - see spec section 8 step 7"
        )


# ── The Desired Outcome: the trace must reconcile ───────────────────────────

_TRACE_FACTS = {
    "applicant_name": "Acme LLC", "mailing_address": "1 Main St, Denver CO 80202",
    "effective_date": "2026-07-15", "lines_of_business": ["General Liability"],
    "entity_type": "LLC", "contact_name": "Jo", "producer_name": "Broker Inc",
    "fein": "12-3456789", "num_employees": "40", "years_in_business": "12",
    "operations_description": "Residential roofing contractor with 12 crews",
    "total_revenue": "2000000", "naics_code": "238160",
}


def _pkg(**kw):
    base = dict(
        facts=_TRACE_FACTS, flags={"has_general_liability": True},
        form_results=[{"confidence_fill_rate": 80}], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    base.update(kw)
    return sq.calculate_package_sqs(**base)


def test_the_trace_reconciles_to_the_headline():
    """Canonical Fact -> Rule -> Pillar -> Raw -> Ceiling -> Displayed."""
    res = _pkg()
    tr = res["score_trace"]
    assert tr["reconciles"] is True
    assert tr["arithmetic"]["raw"] == res["raw_sqs_score"]
    assert tr["arithmetic"]["displayed"] == res["package_sqs_score"]
    assert abs(tr["arithmetic"]["weighted_sum"] - res["raw_sqs_score"]) < 1.0


def test_the_structural_rows_reconstruct_their_own_pillar():
    res = _pkg()
    parts = res["score_trace"]["structural"]
    assert {p["key"] for p in parts} == {"tier1", "tier2", "fill"}
    rebuilt = int(sum(p["contribution"] for p in parts))
    assert rebuilt == res["pillars"]["structural_completeness"]


def test_the_trace_reports_effective_weights_when_a_pillar_is_na():
    """A nominal weight is a lie the moment something is Not Applicable."""
    res = _pkg()
    rows = {r["pillar"]: r for r in res["score_trace"]["pillars"]}
    umb = rows["umbrella_limit_adequacy"]
    assert umb["not_applicable"] is True and umb["contribution"] == 0.0
    struct = rows["structural_completeness"]
    assert struct["nominal_weight"] == 0.25
    assert struct["effective_weight"] == pytest.approx(0.25 / 0.90, rel=1e-3)


def test_the_trace_states_the_ceiling_and_its_reason():
    res = _pkg(hard_stops=["FEIN differs across uploaded documents"])
    arith = res["score_trace"]["arithmetic"]
    assert arith["ceiling"] == 60
    assert "FEIN" in (arith["ceiling_reason"] or "")
    assert arith["displayed"] <= 60
    assert arith["raw"] == res["raw_sqs_score"], "the raw score is preserved"


def test_every_form_score_carries_a_trace_too():
    """Owner ruling 2026-08-25: per form as well as package."""
    res = sq.calculate_sqs(
        facts=_TRACE_FACTS, flags={"has_general_liability": True},
        mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
        tier2_score=80, form_id="ACORD_125",
    )
    assert res["score_trace"]["reconciles"] is True
    assert res["score_trace"]["arithmetic"]["raw"] == res["raw_sqs_score"]


# ── 3.12 - physical address ─────────────────────────────────────────────────

def _addr_warnings(facts, flags):
    from services.cross_form_validator import _check_identity_address_distinction
    return [i["code"] for i in _check_identity_address_distinction(
        facts, flags, {"ACORD_125"})]


@pytest.mark.parametrize("locations,expect_warning,why", [
    (["1450 Lantern Court, Columbus OH 43215", "88 Weaver Mill Road"],
     False, "real street rows satisfy the requirement"),
    ([{"address": "12 Main Street, Denver CO"}],
     False, "the dict row shape must work too"),
    (None,  True, "no schedule at all - the question stays open"),
    ([],    True, "an empty schedule is not an address"),
    (["See attached", "Location 1"],
     True, "labels are not addresses - 'Location 1' has a digit and must NOT pass"),
])
def test_a_location_schedule_satisfies_the_physical_address_rule(
        locations, expect_warning, why):
    """LIVE DEFECT, S6A, 2026-08-25: the warning fired with two street
    addresses sitting in the schedule.

    `facts["locations"]` is normally a list of plain STRINGS -
    `extraction_service` ends with
    ``facts["locations"] = [str(o["address"]) for o in consolidated ...]``.
    The first cut of this check tested `isinstance(row, dict)` only, a shape
    guessed from schedule capture rather than read from the writer, so it never
    matched on a real session. Both shapes are covered now, and the label cases
    are here because a digit alone let "Location 1" through the second cut.
    """
    facts = {"mailing_address": "PO Box 4820, Columbus OH 43216"}
    if locations is not None:
        facts["locations"] = locations
    warnings = _addr_warnings(facts, {"has_property_coverage": True})
    assert bool(warnings) is expect_warning, why


def test_auto_garaging_triggers_the_physical_address_rule():
    """3.12 names auto garaging as an example of when it becomes applicable."""
    facts = {"mailing_address": "PO Box 4820, Columbus OH 43216"}
    assert _addr_warnings(facts, {"has_auto_coverage": True}), (
        "a garaged fleet has a physical location by definition"
    )
    assert not _addr_warnings(facts, {}), (
        "3.12: no universal penalty for accounts that do not need one"
    )


# ── The double counts the client asked us to be able to rule out ────────────

def test_no_fact_is_deducted_in_two_pillars():
    """3.5 / 3.14 plus the owner's 2026-08-25 ruling on the two he did not name.

    Each fact below is scored in EXACTLY ONE pillar. Driven through the real
    scorers rather than by reading the source, because a comment claiming a
    deduction was removed is not evidence that it was.
    """
    def exposure(facts, flags):
        return sq._calculate_exposure_consistency(facts, flags, [], [])[0]

    gl = {"has_general_liability": True}
    codes = {"gl_class_codes_by_location": [{"code": "91580"}],
             "gl_limits": "1000000"}

    # operations_description: Tier 2 only. Its absence must not touch Exposure.
    assert exposure(dict(codes), gl) == exposure(
        dict(codes, operations_description="Roofing contractor"), gl), (
        "operations_description is a Tier 2 field - Exposure must not charge "
        "for it a second time"
    )

    # total_revenue: Tier 2 only.
    assert exposure(dict(codes), gl) == exposure(
        dict(codes, total_revenue="2000000"), gl), (
        "total_revenue is a Tier 2 field - Exposure must not charge for it too"
    )

    # ...while the checks that measure something DIFFERENT are still alive.
    assert exposure({"gl_limits": "1000000"}, gl) < 100, "missing class codes"
    assert exposure({"wc_class_codes": ["5183"]},
                    {"has_workers_comp": True}) < 100, "WC with no payroll"

    # total_payroll: Exposure only (3.14), never Structural.
    assert "total_payroll" not in sq.TIER2_FIELDS
