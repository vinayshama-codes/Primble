"""test_loss_history_c2.py - client section 2 (Loss History workstream), 2026-08-24.

Every number below is the client's own C2 table (which takes precedence over
SQS_Scoring_Specification.docx.pdf where they conflict; the spec stays
authoritative where C2 is silent). Tests drive the REAL code:
calculate_p4_loss_history, services.loss_history_state, _weighted_pillar_sum,
check_tier2 and the ARQ state gate - never a local re-implementation.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services import loss_history_state as lhs
from services import sqs_service as sq
from services.sqs_service import (
    SPEC_PILLAR_WEIGHTS,
    TIER2_FIELDS,
    _weighted_pillar_sum,
    calculate_p4_loss_history,
    check_tier2,
    loss_recommendation_field,
)

_NV_YES = "Yes - new venture, no prior operations"


def _p4(facts=None, flags=None, doc=False, match="no_loss_run"):
    return calculate_p4_loss_history(facts or {}, flags or {},
                                     has_loss_run_doc=doc, loss_run_match=match)


# ── 2.3 Path A: readable claim years ─────────────────────────────────────────

def test_path_a_base_tiers_100_85_70():
    fresh = {"loss_run_age_days": "30", "prior_carrier": "X"}
    assert _p4({**fresh, "loss_history_years": "5"}, doc=True)[0] == 100
    assert _p4({**fresh, "loss_history_years": "4"}, doc=True)[0] == 85
    assert _p4({**fresh, "loss_history_years": "3"}, doc=True)[0] == 85
    assert _p4({**fresh, "loss_history_years": "2"}, doc=True)[0] == 70
    assert _p4({**fresh, "loss_history_years": "1"}, doc=True)[0] == 70


@pytest.mark.parametrize("age,expected", [
    ("30", 100), ("90", 100),          # 0-90: no deduction
    ("91", 90), ("180", 90),           # 91-180: -10
    ("181", 80), ("300", 80), ("365", 80),   # 181-365: -20 FLAT (was a ramp)
    ("400", 75),                        # >365: -25
])
def test_path_a_recency_bands_are_flat(age, expected):
    facts = {"loss_history_years": "5", "prior_carrier": "X", "loss_run_age_days": age}
    assert _p4(facts, doc=True)[0] == expected


def test_path_a_unknown_valuation_date_minus_15():
    facts = {"loss_history_years": "5", "prior_carrier": "X"}
    assert _p4(facts, doc=True)[0] == 85


def test_prior_carrier_present_is_never_a_bonus():
    # 2.3: "Prior carrier present = 0". 100 stays 100, tier bases stand as-is.
    assert _p4({"loss_history_years": "5", "loss_run_age_days": "30",
                "prior_carrier": "X"}, doc=True)[0] == 100
    assert _p4({"loss_run_age_days": "30", "prior_carrier": "X"},
               doc=True, match="possible")[0] == 35


def test_missing_carrier_deducts_10_only_when_applicable():
    base = {"loss_history_years": "5", "loss_run_age_days": "30"}
    assert _p4(base, doc=True)[0] == 90
    # Confirmed new venture: carrier is NOT applicable, so no -10 - even while
    # the confirmation is contradicted by the uploaded runs (the contradiction
    # is flagged on its own; deducting too would double-punish one uncertainty).
    score, recs = _p4({**base, "new_venture_indicator": _NV_YES}, doc=True)
    assert score == 100
    assert any("conflicts with evidence" in r.lower() for r in recs)


def test_no_credible_match_caps_pillar_at_25():
    facts = {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "X"}
    score, _ = _p4(facts, doc=True, match="no_match")
    assert score <= 25


# ── 2.4 Path B: runs uploaded, claim years unreadable ────────────────────────

def test_strong_match_unreadable_years_is_fixed_at_60():
    """The client's literal case: '"remains fixed at 60". Today it drops to 45
    if the valuation date is missing.' The pin is TERMINAL - no recency,
    carrier or unknown-date deduction ever reaches it."""
    assert _p4({}, doc=True, match="strong")[0] == 60                       # no valuation date
    assert _p4({"loss_run_age_days": "400"}, doc=True, match="strong")[0] == 60   # stale
    assert _p4({"loss_run_age_days": "30"}, doc=True, match="strong")[0] == 60    # fresh
    # A missing carrier neither moves the pin nor nags about it.
    score, recs = _p4({}, doc=True, match="strong")
    assert score == 60
    assert not any("prior carrier" in r.lower() for r in recs)


def test_strong_pin_still_yields_to_the_contradiction_ceiling():
    # 2.6: the cap is orthogonal to the pin, and it is a CEILING, not a floor.
    score, recs = _p4({"num_claims": "3"}, {"no_prior_losses": True},
                      doc=True, match="strong")
    assert score == 45
    assert any("conflict" in r.lower() for r in recs)


def test_path_b_unknown_date_deducts_nothing_on_any_tier():
    # 2.4: "apply available recency deductions WHEN A VALUATION DATE EXISTS" -
    # the unknown-date -15 is a Path A rule only.
    assert _p4({"prior_carrier": "X"}, doc=True, match="moderate")[0] == 42
    assert _p4({"prior_carrier": "X"}, doc=True, match="possible")[0] == 35
    assert _p4({"prior_carrier": "X"}, doc=True, match="no_match")[0] == 15


def test_path_b_recency_applies_when_date_known():
    assert _p4({"prior_carrier": "X", "loss_run_age_days": "120"},
               doc=True, match="moderate")[0] == 32
    assert _p4({"prior_carrier": "X", "loss_run_age_days": "400"},
               doc=True, match="moderate")[0] == 17


def test_path_b_missing_applicable_carrier_minus_10_no_bonus():
    assert _p4({}, doc=True, match="moderate")[0] == 32
    assert _p4({}, doc=True, match="possible")[0] == 25


# ── 2.5 Path C: no loss runs ─────────────────────────────────────────────────

def test_path_c_states_60_50_40_25():
    assert _p4({}, {"no_prior_losses": True})[0] == 60          # attested
    assert _p4({"loss_run_status": "pending"})[0] == 50         # requested/pending
    assert _p4({}, {"narrative_states_no_losses": True})[0] == 40   # narrative only
    assert _p4({}, {})[0] == 25                                  # nothing provided


def test_path_c_combination_states():
    # Attestation + runs pending = 60 (attestation outranks pending).
    assert _p4({"loss_run_status": "requested"}, {"no_prior_losses": True})[0] == 60
    # Known prior claims + runs pending = 50 until runs arrive.
    assert _p4({"num_claims": "2", "loss_run_status": "pending"})[0] == 50
    # Known prior claims + no runs and nothing pending = 25.
    score, recs = _p4({"num_claims": "2"})
    assert score == 25
    assert any("request loss runs" in r.lower() for r in recs)


def test_no_loss_runs_available_state():
    facts = {"loss_run_status": "No loss runs are available"}
    assert _p4(facts)[0] == 25
    assert sq._get_loss_history_state(facts, {}) == "no_loss_runs_available"
    # An attestation still wins (60) - availability does not degrade it.
    assert _p4(facts, {"no_prior_losses": True})[0] == 60


def test_caps_are_ceilings_never_floors():
    # Narrative-only (40) under an open contradiction stays 40 - the 45 cap
    # never lifts a lower score.
    score, _ = _p4({"num_claims": "3"}, {"narrative_states_no_losses": True})
    assert score == 40


# ── 2.1 Frequency / ratio are advisory only ──────────────────────────────────

def test_frequency_and_ratio_are_advisory_only():
    base = {"loss_history_years": "5", "loss_run_age_days": "30",
            "prior_carrier": "X", "total_revenue": "1000000"}
    clean, _ = _p4(base, doc=True)
    heavy, recs = _p4({**base, "num_claims": "5", "total_incurred": "200000"}, doc=True)
    assert heavy == clean, "claim frequency / loss ratio must not move the score (2.1)"
    advisories = [r for r in recs if r.lower().startswith("underwriting advisory")]
    assert len(advisories) == 2, recs
    assert all(loss_recommendation_field(r) is None for r in advisories)


# ── 2.2 New venture -> Not Applicable + generic rescaling ────────────────────

def test_new_venture_confirmed_makes_pillar_not_applicable():
    facts = {"new_venture_indicator": _NV_YES}
    score, recs = _p4(facts)
    assert score is None
    assert any("not applicable" in r.lower() for r in recs)
    assert sq._get_loss_history_state(facts, {}) == "new_venture_not_applicable"


def test_new_venture_flag_paths():
    assert _p4({}, {"new_venture_confirmed": True})[0] is None
    # An explicit "not a new venture" answer scores normally.
    assert _p4({}, {"new_venture_confirmed": False})[0] == 25


def test_contradicted_new_venture_is_scored_not_na():
    facts = {"new_venture_indicator": _NV_YES, "prior_carrier": "Travelers"}
    score, recs = _p4(facts)
    assert score is not None
    assert any("conflicts with evidence" in r.lower() for r in recs)


def test_weighted_sum_generic_na_rescaling():
    pillars = {"structural_completeness": 80, "exposure_consistency": 80,
               "property_integrity": 80, "loss_history_alignment": None,
               "umbrella_limit_adequacy": None, "narrative_quality": 80}
    # BOTH loss and umbrella N/A (the client's "both are N/A" case).
    assert _weighted_pillar_sum(pillars, SPEC_PILLAR_WEIGHTS) == 80
    # Loss alone N/A: remaining original weights rescale proportionally.
    pillars["umbrella_limit_adequacy"] = 40
    expected = int((80 * 0.25 + 80 * 0.25 + 80 * 0.15 + 40 * 0.10 + 80 * 0.10) / 0.85)
    assert _weighted_pillar_sum(pillars, SPEC_PILLAR_WEIGHTS) == expected
    # Nothing N/A: byte-identical to the plain weighted sum.
    pillars["loss_history_alignment"] = 60
    plain = int(sum(v * SPEC_PILLAR_WEIGHTS[k] for k, v in pillars.items()))
    assert _weighted_pillar_sum(pillars, SPEC_PILLAR_WEIGHTS) == plain


# ── 2.7 / 2.8 Structural Completeness no longer double-counts ────────────────

def test_prior_carrier_and_claim_count_left_structural_completeness():
    assert "prior_carrier" not in TIER2_FIELDS
    assert "num_claims" not in TIER2_FIELDS
    _, missing = check_tier2({}, {})
    joined = " ".join(missing).lower()
    assert "prior carrier" not in joined
    assert "prior claims" not in joined


def test_acord_130_checklist_no_longer_reads_prior_carrier():
    import inspect
    import re
    src = inspect.getsource(sq.calculate_sqs)
    m = re.search(r'elif fid == "ACORD_130".*?struct = ', src, re.S)
    assert m, "ACORD_130 checklist not found in calculate_sqs"
    assert '"prior_carrier"' not in m.group(0)


# ── 2.6 Contradiction routes to Data Consistency as an advisory ──────────────

def test_conflict_routes_to_data_consistency_as_advisory():
    import inspect
    from services import extraction_pipeline as ep
    src = inspect.getsource(ep)
    i = src.index("loss_history_attestation_conflict")
    window = src[max(0, i - 500): i + 500]
    assert '"advisory"' in window, (
        "the conflict row must be ADVISORY - a hard/soft stop here would cap "
        "the whole package at 60/85 when the client caps only the pillar at 45"
    )


# ── 2.9 The canonical state model ────────────────────────────────────────────

def test_canonical_states_reachable():
    R = lhs.resolve_loss_history_state
    assert R({}, {}, False) == lhs.STATE_MISSING_UNANSWERED
    assert R({}, {}, True) == lhs.STATE_LOSS_RUNS_UPLOADED
    assert R({"loss_run_status": "pending"}, {}, False) == lhs.STATE_LOSS_RUNS_PENDING
    assert R({"loss_run_status": "No loss runs are available"}, {}, False) == lhs.STATE_NO_LOSS_RUNS_AVAILABLE
    assert R({}, {"no_prior_losses": True}, False) == lhs.STATE_NO_KNOWN_LOSSES_ATTESTED
    assert R({"num_claims": "2"}, {}, False) == lhs.STATE_PRIOR_CLAIMS_EXIST
    assert R({}, {"narrative_states_no_losses": True}, False) == lhs.STATE_NO_LOSS_NARRATIVE_ONLY
    assert R({}, {"new_venture_confirmed": True}, False) == lhs.STATE_NEW_VENTURE


def test_new_venture_wording_needs_no_inversion():
    """The option TEXT is the stored value (the _NO_LOSS_OPTIONS design).
    If either option is reworded, re-run this first."""
    yes, no = lhs.NEW_VENTURE_OPTIONS
    assert lhs.new_venture_answer(yes) is True
    assert lhs.new_venture_answer(no) is False
    assert lhs.new_venture_answer("") is None
    assert lhs.new_venture_answer(None) is None
    assert lhs.new_venture_answer("Yes") is True
    assert lhs.new_venture_answer("No") is False


def test_loss_run_status_options_parse_through_one_reader():
    a, b, c = lhs.LOSS_RUN_STATUS_OPTIONS
    assert lhs.parse_loss_run_status(a) == "pending"
    assert lhs.parse_loss_run_status(b) == "pending"
    assert lhs.parse_loss_run_status(c) == "no_runs_available"
    # Extraction's own scalars (RULE 12) read identically.
    assert lhs.parse_loss_run_status("pending") == "pending"
    assert lhs.parse_loss_run_status("requested") == "pending"
    assert lhs.parse_loss_run_status("") is None
    assert lhs.parse_loss_run_status(None) is None


# ── 2.10 Questionnaire behaviour ─────────────────────────────────────────────

def _q(field, canon=None):
    return {"field_name": field, "question": field, "_canonical_key": canon or field}


def test_new_venture_suppresses_prior_history_questions():
    from services.arq_service import _apply_loss_state_question_gate
    qs = [_q("prior_carrier"), _q("num_claims"), _q("loss_history_years"),
          _q("total_revenue"), _q("schedule::loss_history")]
    facts = {"new_venture_indicator": _NV_YES}
    kept = _apply_loss_state_question_gate(qs, facts, {}, has_loss_run_doc=False)
    assert {q["field_name"] for q in kept} == {"total_revenue"}


def test_contradicted_new_venture_suppresses_nothing():
    from services.arq_service import _apply_loss_state_question_gate
    qs = [_q("prior_carrier"), _q("num_claims")]
    facts = {"new_venture_indicator": _NV_YES, "prior_carrier": "Travelers"}
    kept = _apply_loss_state_question_gate(qs, facts, {}, has_loss_run_doc=False)
    assert len(kept) == 2, "2.10: questions return when evidence contradicts the answer"


def test_uploaded_runs_suppress_availability_questions_only():
    from services.arq_service import _apply_loss_state_question_gate
    qs = [_q("loss_history_years"), _q("num_claims"),
          _q("loss_history_no_prior_losses_indicator")]
    kept = _apply_loss_state_question_gate(qs, {}, {}, has_loss_run_doc=True)
    assert {q["field_name"] for q in kept} == {"num_claims"}


def test_no_state_suppresses_nothing():
    from services.arq_service import _apply_loss_state_question_gate
    qs = [_q("prior_carrier"), _q("num_claims")]
    assert _apply_loss_state_question_gate(qs, {}, {}, has_loss_run_doc=False) == qs


def test_loss_run_status_question_injected_for_known_claims():
    from services.arq_service import _maybe_inject_loss_run_status_question
    qs = []
    _maybe_inject_loss_run_status_question(qs, {"num_claims": "2"}, {},
                                           has_loss_run_doc=False)
    assert len(qs) == 1
    assert qs[0]["field_type"] == "select", "blank must stay distinguishable from an answer"
    assert qs[0]["current_value"] == ""
    # Never asked when runs are uploaded, no claims are known, or it is answered.
    for facts, doc in (({"num_claims": "2"}, True),
                       ({}, False),
                       ({"num_claims": "2", "loss_run_status": "pending"}, False)):
        qs2 = []
        _maybe_inject_loss_run_status_question(qs2, facts, {}, has_loss_run_doc=doc)
        assert qs2 == [], (facts, doc)


# ── Recommendation routing for the new vocabulary ────────────────────────────

def test_new_rec_messages_route_to_writable_fields():
    assert loss_recommendation_field(sq._NEW_VENTURE_CONFIRM_REC) == "new_venture_indicator"
    assert loss_recommendation_field(
        "Prior claims are known but no loss runs or pending request is on file"
    ) == "loss_run_status"
    from services.arq_service import _canonical_key
    assert _canonical_key("new_venture_indicator") == "new_venture_indicator"
    assert _canonical_key("loss_run_status") == "loss_run_status"


def test_loss_run_from_the_prior_carrier_raises_no_carrier_note():
    """Found live (S2, 2026-08-24): a loss run is normally issued by the PRIOR
    carrier, which the package's own dec names - that must not raise the
    'not this account's carrier' note."""
    from services.loss_run_identity import NOTE_CARRIER_DIFFERS, match_loss_run_identity
    docs = [
        {"doc_type": "dec_page", "facts": {
            "applicant_name": "BLUEWATER CATERING GROUP LLC", "fein": "82-1147765",
            "policy_number": "BWC-GLP-5521",
            "carrier_name": "Lakeshore Standard Insurance Company",
            "prior_carrier": "Meridian Insurance Group"}},
        {"doc_type": "loss_run", "facts": {
            "applicant_name": "BLUEWATER CATERING GROUP LLC", "fein": "82-1147765",
            "policy_number": "BWC-GLP-5521",
            "carrier_name": "Meridian Insurance Group"}},
    ]
    verdict = match_loss_run_identity(docs, "BLUEWATER CATERING GROUP LLC")
    assert verdict["tier"] == "strong"
    assert NOTE_CARRIER_DIFFERS not in verdict["notes"]


def test_a_genuinely_foreign_loss_run_carrier_still_raises_the_note():
    """Both directions: the fix must not silence the REAL mismatch."""
    from services.loss_run_identity import NOTE_CARRIER_DIFFERS, match_loss_run_identity
    docs = [
        {"doc_type": "dec_page", "facts": {
            "applicant_name": "BLUEWATER CATERING GROUP LLC", "fein": "82-1147765",
            "policy_number": "BWC-GLP-5521",
            "carrier_name": "Lakeshore Standard Insurance Company",
            "prior_carrier": "Meridian Insurance Group"}},
        {"doc_type": "loss_run", "facts": {
            "applicant_name": "BLUEWATER CATERING GROUP LLC", "fein": "82-1147765",
            "policy_number": "BWC-GLP-5521",
            "carrier_name": "Zenith Totally Unrelated Assurance Corp"}},
    ]
    verdict = match_loss_run_identity(docs, "BLUEWATER CATERING GROUP LLC")
    assert NOTE_CARRIER_DIFFERS in verdict["notes"]


def test_advisory_loss_cards_carry_zero_points():
    """Found on the 2026-08-24 live run (S2): an advisory that can never move
    the score offered 'up to +8 pts' - contradicting its own text, and
    dismiss-with-reason would have CREDITED those phantom points."""
    facts = {"loss_history_years": "5", "loss_run_age_days": "30",
             "prior_carrier": "X", "total_revenue": "1000000",
             "num_claims": "5", "total_incurred": "200000",
             "applicant_name": "ACME LLC", "effective_date": "07/15/2026"}
    res = sq.calculate_sqs(
        facts=facts, flags={}, mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
        tier2_score=60, form_id="ACORD_125",
        has_loss_run_doc=True, loss_run_match="strong",
    )
    advisories = [r for r in res["recommendations"]
                  if str(r.get("message", "")).lower().startswith("underwriting advisory")]
    assert advisories, "this fixture must trip the frequency AND ratio advisories"
    assert all(r["score_impact"] == 0 for r in advisories)
    # And the pillar itself is untouched by them: 5 fully-valued years stays a
    # PERFECT 100 despite 5 claims/$1M and a 15% loss ratio (client 2.1).
    assert res["breakdown"]["loss_history_alignment"] == 100
