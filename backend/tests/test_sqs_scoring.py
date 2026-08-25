"""test_sqs_scoring.py

Dedicated unit tests for the Workstream-3 (§6) scoring math — the layer the
beta-review flagged as having near-zero direct coverage. Covers:

  * _calculate_umbrella_adequacy   — N/A + client Q1/Q2 thresholds
  * _get_umbrella_state            — §6.5 evidence states
  * _get_follow_form_status        — Option B (explicit-only) follow-form
  * calculate_p4_loss_history      — Q3 year tiers, recency, insured match
  * _attested_true                 — safe boolean coercion (Finding 4)
  * _calculate_narrative_quality   — tuple return + component model (§6.3)
  * evaluate_stops                 — Q1 auto warning (not hard) + Q2 EL $500K

Pure functions, no DB/IO — fast to run.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import sqs_service as sq


# ── _attested_true (Finding 4) ────────────────────────────────────────────────

def test_attested_true_safe_coercion():
    assert sq._attested_true("Yes") is True
    assert sq._attested_true(True) is True
    assert sq._attested_true(1) is True
    assert sq._attested_true("no prior losses") is True
    # The bug the review flagged: a stored "No"/"false"/"0" must NOT read as True.
    assert sq._attested_true("No") is False
    assert sq._attested_true("false") is False
    assert sq._attested_true("0") is False
    assert sq._attested_true("") is False
    assert sq._attested_true(None) is False


# ── Umbrella adequacy (Q1/Q2) ─────────────────────────────────────────────────

def test_umbrella_not_applicable_returns_none():
    # The confirmed 100% bug: no umbrella must be N/A (None), never a perfect score.
    assert sq._calculate_umbrella_adequacy({}, {}) is None


def test_umbrella_no_underlying_is_zero():
    assert sq._calculate_umbrella_adequacy({}, {"has_umbrella": True}) == 0


def test_umbrella_full_credit_when_adequate():
    # Full credit requires complete umbrella details (§6.5 item 2): the umbrella's
    # own limit + adequate underlying limits + schedule of underlying + follow form.
    facts = {
        "umbrella_limit": "5000000",
        "gl_limits": "1000000",
        "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M each occurrence; Auto $1M CSL",
        "umbrella_follow_form": "follows form over underlying policies",
    }
    assert sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True}) == 100


def test_umbrella_missing_own_limit_is_never_perfect():
    # §6.5 AC#4: an umbrella whose OWN limit is missing is "insufficient
    # information" - it must NOT yield a perfect/complete score even when the
    # underlying limits, schedule and follow-form are all present.
    facts = {
        "gl_limits": "1000000",
        "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M each occurrence; Auto $1M CSL",
        "umbrella_follow_form": "follows form over underlying policies",
    }
    score = sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True})
    assert score is not None and score < 100, f"missing umbrella limit must not be perfect, got {score}"
    # And the evidence-state machine agrees it is insufficient information.
    assert sq._get_umbrella_state(facts, {"has_umbrella": True}) == "insufficient_information"


def test_umbrella_low_gl_reduces_not_blocks():
    # -20 for GL below $1M; -15 no schedule; -10 no follow form = 55
    facts = {"umbrella_limit": "5000000", "gl_limits": "500000", "auto_liability_limit": "1000000"}
    score = sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True})
    assert score == 55  # -20 GL + -15 no schedule + -10 no follow form; never a hard stop


def test_umbrella_el_tiers_q2():
    # Base deductions: -15 no schedule, -10 no follow form = -25 on top of EL tiers
    base = {"umbrella_limit": "5000000", "gl_limits": "1000000", "auto_liability_limit": "1000000"}
    flags = {"has_umbrella": True, "has_workers_comp": True}
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "1000000"}, flags) == 75  # 100 - 25
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "500000"}, flags) == 65   # -10 EL - 25
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "250000"}, flags) == 50   # -25 EL - 25
    assert sq._calculate_umbrella_adequacy(base, flags) == 50                                               # EL missing -25 - 25


def test_umbrella_gl_aggregate_below_baseline_reduces_score_and_warns():
    # Client Q1 baseline is GL $1M occurrence / $2M aggregate. The aggregate half
    # must be validated too: an extracted aggregate below $2M reduces the score and
    # warns (never blocks), even when occurrence meets its baseline.
    facts = {
        "umbrella_limit": "5000000",
        "gl_each_occurrence": "1000000",   # occurrence meets baseline
        "gl_aggregate": "1000000",         # aggregate at HALF the $2M baseline
        "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL; Auto",
        "umbrella_follow_form": "follows form",
    }
    flags = {"has_umbrella": True}
    # Only deduction is the aggregate (-20); occurrence/auto/schedule/follow-form OK.
    assert sq._calculate_umbrella_adequacy(facts, flags) == 80
    # State must not read as present/supported while the score is penalising it.
    assert sq._get_umbrella_state(facts, flags) == "umbrella_coverage_needs_review"
    # A plain-language aggregate warning is surfaced (same style as occurrence).
    warns = sq._build_umbrella_warnings(facts, flags, 80)
    assert any("aggregate" in w.lower() and "umbrella requirements" in w.lower() for w in warns)


def test_umbrella_gl_aggregate_meeting_baseline_keeps_full_credit():
    # Aggregate at the $2M baseline (everything else adequate) → no aggregate penalty.
    facts = {
        "umbrella_limit": "5000000",
        "gl_each_occurrence": "1000000",
        "gl_aggregate": "2000000",
        "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL; Auto",
        "umbrella_follow_form": "follows form",
    }
    assert sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True}) == 100


# ── Umbrella evidence states (§6.5) ───────────────────────────────────────────

def test_umbrella_state_machine():
    assert sq._get_umbrella_state({}, {}) == "not_applicable"
    assert sq._get_umbrella_state({}, {"has_umbrella": True}) == "insufficient_information"
    # Umbrella limit present but NO underlying GL/Auto value: scorer returns 0 and a
    # hard stop fires, so the state must read as a problem (Unknown), never a benign
    # "information provided" label (§6.5 state/score-agreement fix).
    assert sq._get_umbrella_state({"umbrella_limit": "5000000"}, {"has_umbrella": True}) == "unknown"
    low = {"umbrella_limit": "5000000", "gl_limits": "500000"}
    assert sq._get_umbrella_state(low, {"has_umbrella": True}) == "umbrella_coverage_needs_review"
    # Limits meet thresholds; zero supporting documents (no schedule, no follow-form).
    # §6.5 retired "umbrella_information_provided" - once limits meet thresholds this
    # reads as Coverage Present even with both supporting docs missing.
    ok = {"umbrella_limit": "5000000", "gl_limits": "1000000", "auto_liability_limit": "1000000"}
    assert sq._get_umbrella_state(ok, {"has_umbrella": True}) == "umbrella_coverage_present"
    # One supporting document present (schedule OR follow-form) → coverage present.
    ok_partial = {**ok, "schedule_of_underlying_insurance": "GL $1M/$2M; Auto $1M CSL"}
    assert sq._get_umbrella_state(ok_partial, {"has_umbrella": True}) == "umbrella_coverage_present"
    full = {
        "umbrella_limit": "5000000", "gl_limits": "1000000", "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M/$2M; Auto $1M CSL",
        "acord101_remarks": "The umbrella follows form over all underlying policies",
    }
    assert sq._get_umbrella_state(full, {"has_umbrella": True}) == "adequately_supported"


def test_umbrella_state_demotes_when_flagged_coverage_limit_missing():
    # State/score parity: a present coverage flag with NO extracted limit cannot be
    # validated, so the state must demote to needs_review (not present/supported),
    # symmetric for GL and Auto. Mirrors the score's -20 required-but-absent penalty.
    # Auto exposure flagged, GL adequate, but Auto limit absent → needs_review.
    auto_missing = {"umbrella_limit": "5000000", "gl_limits": "1000000",
                    "schedule_of_underlying_insurance": "GL $1M",
                    "umbrella_follow_form": "follows form"}
    assert sq._get_umbrella_state(
        auto_missing, {"has_umbrella": True, "has_auto_coverage": True}
    ) == "umbrella_coverage_needs_review"
    # GL exposure flagged, Auto adequate, but GL limit absent → needs_review.
    gl_missing = {"umbrella_limit": "5000000", "auto_liability_limit": "1000000",
                  "schedule_of_underlying_insurance": "Auto $1M",
                  "umbrella_follow_form": "follows form"}
    assert sq._get_umbrella_state(
        gl_missing, {"has_umbrella": True, "has_general_liability": True}
    ) == "umbrella_coverage_needs_review"
    # No coverage flag set → absent underlying limit is NOT demoted to needs_review;
    # with limits meeting thresholds it reads as coverage present (§6.5: "information
    # provided" state retired, zero/one supporting doc both -> coverage present).
    assert sq._get_umbrella_state(
        {"umbrella_limit": "5000000", "gl_limits": "1000000"}, {"has_umbrella": True}
    ) == "umbrella_coverage_present"


# ── Follow-form Option B (Q4) ─────────────────────────────────────────────────

def test_follow_form_explicit_only():
    confirmed = sq._get_follow_form_status({"acord101_remarks": "The umbrella follows form over the underlying GL."})
    assert confirmed["status"] == "follow_form_confirmed"
    unknown = sq._get_follow_form_status({"acord101_remarks": "General account narrative with no coverage structure."})
    assert unknown["status"] == "unable_to_determine"
    assert sq._get_follow_form_status({})["status"] == "unable_to_determine"


def test_follow_form_never_guessed_from_negation_or_uncertainty():
    # Client Q3: follow-form must NEVER be guessed. Negated or hypothetical /
    # interrogative mentions must NOT be read as a confirmation.
    for txt in (
        "The umbrella does not follow form over the underlying coverages.",
        "Umbrella doesn't follow form.",
        "Unable to determine whether the umbrella follows form.",
        "We cannot confirm the umbrella follows form.",
    ):
        res = sq._get_follow_form_status({"acord101_remarks": txt})
        assert res["status"] == "unable_to_determine", f"must not confirm from: {txt!r}"
        assert sq._has_explicit_follow_form(txt) is False, f"negated/uncertain should be False: {txt!r}"
    # A negation in a PRIOR clause must not suppress a genuine affirmation.
    assert sq._has_explicit_follow_form("GL is not claims-made. The umbrella follows form.") is True
    # Plain affirmative still confirms.
    assert sq._has_explicit_follow_form("The umbrella follows form over all underlying policies.") is True


# ── Loss history (Q3 tiers / recency / insured match) ─────────────────────────

def test_loss_year_tiers():
    # 5+ years + prior carrier → full credit (+10 carrier, capped at 100).
    # has_loss_run_doc=True: year-tier credit requires actual loss-run evidence
    # (2026-07-11 fix) - a bare years number with no document is attestation-tier
    # at best, never full/partial year-tier credit. See test_loss_year_tiers_require_doc.
    full, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=True)
    assert full == 100
    # C2 2.3: 3-4 years base = 85. Prior carrier MISSING applies -10 → 75.
    partial, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30"}, {}, has_loss_run_doc=True)
    assert partial == 75
    # 3-4 years WITH prior carrier: present = 0 (C2: the +10 bonus is removed) → 85.
    partial_with_carrier, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=True)
    assert partial_with_carrier == 85
    # C2 2.3: 1-2 years base = 70 (was 40 - too punitive for real evidence);
    # prior carrier missing -10 → 60.
    thin, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "2", "loss_run_age_days": "30"}, {}, has_loss_run_doc=True)
    assert thin == 60
    # No loss info: 25 — carrier adjustment does not apply on this path.
    none, _ = sq.calculate_p4_loss_history({}, {})
    assert none == 25


def test_loss_year_tiers_require_doc():
    # Regression guard (2026-07-11): a "loss_history_years" figure with NO loss-run
    # document behind it must NOT earn year-tier credit. Real-world cause: a Yes/No
    # question's lookback window ("...in the past five (5) years?") or the ACORD
    # form's own "FOR THE LAST ___ YEARS" blank can populate this fact with zero
    # loss-run evidence attached - that must fall through to the attestation/
    # no-info tiers, not silently outscore genuine documentation.
    undocumented, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=False)
    assert undocumented == 25, f"Expected no-info baseline with no doc, got {undocumented}"
    documented, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=True)
    assert documented > undocumented


def test_loss_prior_carrier_delta():
    # C2 2.3: prior carrier present = 0 (no bonus), missing when applicable = -10.
    with_c, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=True)
    without_c, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30"}, {}, has_loss_run_doc=True)
    assert with_c - without_c == 10  # (0) - (-10)


def test_loss_run_moderate_match_name_plus_address():
    # Client match hierarchy: name + address = MODERATE (between strong and weak).
    # Normalization-aware: "123 Main St" == "123 Main Street".
    docs = [
        {"doc_type": "dec_page", "facts": {"applicant_name": "Orbin Contracting", "mailing_address": "123 Main St"}},
        {"doc_type": "loss_run", "facts": {"applicant_name": "Orbin Contracting", "mailing_address": "123 Main Street"}},
    ]
    assert sq._check_loss_run_insured_match(docs, "Orbin Contracting") == "moderate"


def test_loss_recency_penalty():
    recent, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "X"}, {},
        has_loss_run_doc=True)
    stale, recs = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "400", "prior_carrier": "X"}, {},
        has_loss_run_doc=True)
    assert stale < recent
    assert any("updated loss runs" in r.lower() for r in recs)


def test_loss_attestation_credit_and_safety():
    attested, _ = sq.calculate_p4_loss_history({}, {"no_prior_losses": True})
    assert attested == 60
    # A stored "No" indicator must NOT be read as an attestation (Finding 4).
    # No-info score is now 25 (updated from 10 per client V1 approval).
    not_attested, _ = sq.calculate_p4_loss_history(
        {"loss_history_no_prior_losses_indicator": "No"}, {})
    assert not_attested == 25


def test_loss_run_doc_match_tiers():
    # Loss runs uploaded WITH a prior carrier (the realistic case - loss runs
    # name the carrier). C2 2.4: carrier presence earns NO bonus, so the tier
    # bases stand as-is. Fresh (age 30) so no recency penalty applies.
    fresh = {"loss_run_age_days": "30", "prior_carrier": "Travelers"}
    strong, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="strong")
    possible, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="possible")
    nomatch, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="no_match")
    assert strong == 60     # pinned (client 2.4)
    assert possible == 35   # tier base, no bonus
    assert nomatch == 15    # tier base, below the 25 no-match cap


def test_loss_run_doc_carrier_adjustment():
    # Client Clarification 2 (§6.4): a strong (name + FEIN/policy) match with no
    # claim years is pinned at 60 - the prior-carrier +/-10 no longer moves it.
    fresh = {"loss_run_age_days": "30"}
    strong_with_c, _ = sq.calculate_p4_loss_history(
        {**fresh, "prior_carrier": "Travelers"}, {}, has_loss_run_doc=True, loss_run_match="strong")
    strong_without_c, _ = sq.calculate_p4_loss_history(
        fresh, {}, has_loss_run_doc=True, loss_run_match="strong")
    assert strong_with_c == 60      # pinned
    assert strong_without_c == 60   # pinned - carrier adjustment skipped for this state
    # C2 2.4: the non-pinned tiers keep only the missing-carrier -10 (when
    # applicable); the +10 presence bonus is removed everywhere.
    poss_with_c, _ = sq.calculate_p4_loss_history(
        {**fresh, "prior_carrier": "Travelers"}, {}, has_loss_run_doc=True, loss_run_match="possible")
    poss_without_c, _ = sq.calculate_p4_loss_history(
        fresh, {}, has_loss_run_doc=True, loss_run_match="possible")
    assert poss_with_c == 35        # 35 + 0 (no bonus)
    assert poss_without_c == 25     # 35 - 10 (missing, applicable)


def test_no_match_loss_runs_capped_even_with_full_years():
    # §6.4 item 2: loss runs that do NOT match the insured cannot be credited,
    # even when they parse to a full 5-year history. The year-tier path would
    # otherwise award 70 (100 base - 30 mismatch); the no-match cap holds it at
    # the no-information baseline so unmatched runs are never effectively credited.
    facts = {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}
    score, recs = sq.calculate_p4_loss_history(
        facts, {}, has_loss_run_doc=True, loss_run_match="no_match")
    assert score <= 25
    assert any("does not match" in r.lower() for r in recs)


def test_strong_match_five_year_unaffected_by_no_match_cap():
    # Guard: the cap bites ONLY on no_match - a strong 5-year match still scores full.
    facts = {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}
    score, _ = sq.calculate_p4_loss_history(
        facts, {}, has_loss_run_doc=True, loss_run_match="strong")
    assert score == 100


def test_five_year_prior_carrier_delta():
    # Client spec: Prior Carrier Present +10 / Prior Carrier Missing -10 applies
    # uniformly across all year tiers, including the 5-year full-credit tier.
    # 5 years + prior carrier: base 100 + 10 → capped at 100.
    with_carrier, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {},
        has_loss_run_doc=True)
    # 5 years WITHOUT prior carrier: base 100 - 10 → 90; recommendation surfaced.
    without_carrier, recs = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30"}, {}, has_loss_run_doc=True)
    assert with_carrier == 100
    assert without_carrier == 90
    assert any("prior carrier" in r.lower() for r in recs)


def test_loss_run_insured_match_requires_name():
    docs = [{"doc_type": "loss_run", "facts": {"applicant_name": "Orbin Contracting"}}]
    # Missing applicant name → cannot verify ownership → not full credit.
    assert sq._check_loss_run_insured_match(docs, None) == "possible"
    # Name-only agreement → possible; name + FEIN → strong.
    assert sq._check_loss_run_insured_match(docs, "Orbin Contracting LLC") == "possible"
    docs_fein = [{"doc_type": "loss_run",
                  "facts": {"applicant_name": "Orbin Contracting", "fein": "123456789"}}]
    other = [{"doc_type": "dec_page", "facts": {"fein": "123456789"}}]
    assert sq._check_loss_run_insured_match(docs_fein + other, "Orbin Contracting") == "strong"


# ── 6.4 item 1 / 2a: conflict now moves the score, not just the label ─────────

def test_loss_conflict_caps_score_and_recommends_reconcile():
    # 5 years + carrier would be 100, but a no-loss attestation contradicted by
    # ACTUAL claims must be capped and explicitly flagged (label ⇔ number).
    facts = {"loss_history_years": "5", "loss_run_age_days": "30",
             "prior_carrier": "Travelers", "num_claims": "3"}
    score, recs = sq.calculate_p4_loss_history(facts, {"no_prior_losses": True})
    assert score <= 45
    assert any("conflict" in r.lower() for r in recs)
    assert sq._get_loss_history_state(facts, {"no_prior_losses": True}) == "loss_history_conflicting"


def test_clean_multiyear_loss_runs_with_attestation_not_conflict():
    # 5 years of CLEAN loss runs (no claims) CONFIRM a no-loss attestation - they
    # must NOT be treated as a conflict or capped (false-positive guard).
    facts = {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "X"}
    score, _ = sq.calculate_p4_loss_history(facts, {"no_prior_losses": True}, has_loss_run_doc=True)
    assert score == 100
    assert sq._get_loss_history_state(
        facts, {"no_prior_losses": True}, has_loss_run_doc=True) != "loss_history_conflicting"


# ── 6.4 / 2b: loss-run recency is deterministic, never fabricated ─────────────

def test_loss_run_age_unverified_no_penalty_no_fabricated_age():
    # No valuation date and no stated age → recency UNVERIFIED: the deliberate
    # -15 "could not verify" penalty applies (_LOSS_RECENCY_UNKNOWN_PEN), but never
    # a fabricated "365 days old" staleness warning (the old default-365 behaviour,
    # which this test guards against - not "no penalty at all").
    facts = {"loss_history_years": "5", "prior_carrier": "X"}
    score, recs = sq.calculate_p4_loss_history(facts, {}, has_loss_run_doc=True)
    assert score == 85, f"Expected 100 - 15 recency-unverified penalty, got {score}"
    assert not any("days old" in r for r in recs)
    assert any("recency unverified" in r.lower() for r in recs)


def test_loss_run_age_computed_from_valuation_date():
    from datetime import datetime, timezone, timedelta
    stale_date = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%m/%d/%Y")
    fresh_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%m/%d/%Y")
    stale, recs = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "prior_carrier": "X", "loss_run_valuation_date": stale_date}, {},
        has_loss_run_doc=True)
    fresh, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "prior_carrier": "X", "loss_run_valuation_date": fresh_date}, {},
        has_loss_run_doc=True)
    assert stale < fresh
    assert any("updated loss runs" in r.lower() for r in recs)


def test_loss_history_years_computed_from_period_dates():
    from datetime import datetime, timezone, timedelta
    # Loss runs cover a ~5-year experience period; the model under-stated it as 2.
    # Dates are authoritative → full-credit tier, not the model's miscount.
    start  = (datetime.now(timezone.utc) - timedelta(days=5 * 365)).strftime("%m/%d/%Y")
    valued = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%m/%d/%Y")
    facts  = {"loss_history_years": "2", "loss_run_period_start": start,
              "loss_run_valuation_date": valued, "prior_carrier": "X"}
    score, _ = sq.calculate_p4_loss_history(facts, {}, has_loss_run_doc=True)
    assert score == 100


# ── Three-tier ownership match: strong > moderate > possible ──────────────────

def test_moderate_match_earns_more_than_possible():
    # sqs-pillars spec: three distinct tiers - strong (name+FEIN/policy),
    # moderate (name+address), possible (name only). Moderate earns more than
    # possible because address is a secondary identifier (more certain than name alone).
    fresh = {"loss_run_age_days": "30", "prior_carrier": "Travelers"}
    moderate, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="moderate")
    possible, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="possible")
    assert moderate > possible   # 42 > 35
    assert moderate == 42        # match_credit[moderate]=42 (C2: no carrier bonus)
    assert possible == 35        # match_credit[possible]=35


def test_moderate_match_maps_to_pending_validation():
    # §6.4 item 2: weak ownership (name+address) is treated exactly like the
    # name-only 'possible' tier for the STATE label too - years are parsed but
    # ownership is not confirmed, so the state is pending validation (never the
    # more-resolved-sounding 'parsed').
    facts = {"loss_history_years": "4"}
    assert sq._get_loss_history_state(facts, {}, has_loss_run_doc=True, loss_run_match="moderate") == "loss_history_pending_validation"
    # 'Loss Runs Parsed' stays reachable as the bare parsing milestone.
    assert sq._get_loss_history_state(facts, {}, has_loss_run_doc=True, loss_run_match="no_loss_run") == "loss_runs_parsed"


def test_no_loss_evidence_quality_scoring():
    # C2 2.5: the two no-loss evidence sources score differently - a user
    # attestation is an affirmative statement (60); a passing mention in the
    # narrative is weaker (40, revised from 45). Both sit above no-info (25).
    user, _ = sq.calculate_p4_loss_history({}, {"no_prior_losses": True})
    narrative, _ = sq.calculate_p4_loss_history({}, {"narrative_states_no_losses": True})
    assert user == 60
    assert narrative == 40


# ── Narrative quality (§6.3 tuple + components) ───────────────────────────────

def test_narrative_returns_tuple_and_components():
    score, components, substance = sq._calculate_narrative_quality({})
    assert score == 0
    assert isinstance(components, dict) and not any(components.values())
    assert isinstance(substance, int)


def test_narrative_floor_with_doc():
    score, _, _ = sq._calculate_narrative_quality({}, has_narrative_doc=True)
    assert score >= 40


def test_narrative_components_detected():
    text = ("Account overview: established in 2003 with 20 years of experience. "
            "Operations include commercial roofing. Management has strong safety practices "
            "and written safety program. No prior losses. Coverage includes general liability.")
    score, components, _ = sq._calculate_narrative_quality({"acord101_remarks": text})
    assert score > 0
    assert components["operations"] and components["risk_controls"] and components["loss_history"]


def test_narrative_components_detected_from_full_doc_text():
    # §6.3: a standalone narrative whose prose lives only in the raw doc text
    # (not in any structured fact) must still have its components detected.
    body = ("Account overview: Orbin Contracting is a family-owned general contractor "
            "established in 2003 with over 20 years of experience. Operations include "
            "commercial roofing and scope of work across the region. Management has a "
            "written safety program with annual inspections. No prior losses reported. "
            "Coverage requested includes general liability and umbrella limits.")
    score, components, _ = sq._calculate_narrative_quality(
        {}, has_narrative_doc=True, narrative_doc_text=body
    )
    assert score > 40  # rises above the bare narrative-present floor
    assert components["operations"] and components["risk_controls"]
    assert components["loss_history"] and components["years_in_business"]


def test_narrative_precision_no_false_positive_from_boilerplate():
    # §6.3 precision guard: incidental single words in raw OCR boilerplate must
    # NOT credit a component (one stray "coverage" / "location" is not a coverage
    # discussion / location-detail narrative). Requires >=2 distinct signals.
    boilerplate = ("This certificate confirms coverage at the location shown. "
                   "Employees should retain a copy. Contact your carrier with questions.")
    _score, components, _ = sq._calculate_narrative_quality(
        {}, has_narrative_doc=True, narrative_doc_text=boilerplate
    )
    assert not components["coverage_discussion"]
    assert not components["location_exposure"]
    assert not components["employee_practices"]
    assert not components["carrier_market"]


def test_narrative_single_mention_in_curated_field_still_counts():
    # The curated/compact field keeps single-mention crediting (no regression):
    # one clear phrase in account_description is enough.
    score, components, _ = sq._calculate_narrative_quality(
        {"account_description": "The company specializes in commercial roofing operations."}
    )
    assert score > 0
    assert components["operations"]


# ── evaluate_stops: client Q1/Q2 (warnings, not hard stops) ───────────────────

def test_auto_below_min_is_warning_not_hard_stop():
    facts = {"umbrella_limit": "5000000", "auto_liability_limit": "500000"}
    flags = {"has_auto_coverage": True, "has_umbrella": True}
    hard, soft = sq.evaluate_stops(facts, flags)
    assert not any("auto_umbrella_attachment_failure" in h for h in hard)
    assert any("umbrella requirements" in s.lower() for s in soft)


def test_el_warning_uses_500k_band():
    facts = {"employers_liability_limits": "250000"}
    flags = {"has_umbrella": True, "has_workers_comp": True}
    hard, soft = sq.evaluate_stops(facts, flags)
    # $250K is above the old $100K threshold but must now warn (Q2).
    assert any("500,000" in s or "$500" in s for s in soft)


def test_auto_attachment_not_in_always_hard_patterns():
    assert "auto_umbrella_attachment_failure" not in sq._ALWAYS_HARD_PATTERNS


def test_gl_below_minimum_is_warning_not_hard_stop():
    # Client Q1 (§6.5): underlying GL below the $1M baseline must be a WARNING +
    # score reduction, NEVER a hard stop. (Carrier attachment requirements vary.)
    from services import cross_form_validator as cfv
    facts = {"umbrella_limit": "5000000", "gl_each_occurrence": "500000"}
    flags = {"has_umbrella": True}
    triggered = {"ACORD_125", "ACORD_126", "ACORD_131"}
    issues = cfv.run_cross_form_validation(facts, flags, triggered)
    hard, soft, _adv = cfv.split_cross_form_issues(issues)
    assert not any("umbrella" in h.lower() and "gl" in h.lower() for h in hard), (
        f"GL-below-minimum must not be a hard stop, got hard={hard}"
    )
    assert any("umbrella requirements" in s.lower() for s in soft), (
        f"GL-below-minimum must surface a warning, got soft={soft}"
    )


def test_auto_below_minimum_has_cross_form_warning_parity_with_gl():
    # Cross-form layer must give Auto parity with GL: Auto below $1M CSL produces a
    # soft warning (never a hard stop) - client Q1 (§6.5).
    from services import cross_form_validator as cfv
    facts = {"umbrella_limit": "5000000", "auto_liability_limit": "500000"}
    flags = {"has_umbrella": True, "has_auto_coverage": True}
    triggered = {"ACORD_125", "ACORD_127", "ACORD_131"}
    issues = cfv.run_cross_form_validation(facts, flags, triggered)
    hard, soft, _adv = cfv.split_cross_form_issues(issues)
    assert not any("auto" in h.lower() and "umbrella" in h.lower() for h in hard), (
        f"Auto-below-minimum must not be a hard stop, got hard={hard}"
    )
    assert any("auto" in s.lower() and "umbrella requirements" in s.lower() for s in soft), (
        f"Auto-below-minimum must surface a cross-form warning, got soft={soft}"
    )


def test_followform_review_item_survives_full_top_recs():
    # §6.5 item 5: the follow-form gap must never be silently dropped. When the
    # 3-item top_recs cap is already full of higher-priority hard stops, the
    # follow-form review item must still be carried in the review_items array.
    facts = {
        "umbrella_limit": "5000000",
        "gl_limits": "1000000", "auto_liability_limit": "1000000",
        # no schedule + no follow-form text → follow_form == unable_to_determine
    }
    flags = {"has_umbrella": True}
    result = sq.calculate_package_sqs(
        facts, flags, form_results=[], cross_issues=[],
        hard_stops=["Hard stop A", "Hard stop B", "Hard stop C"],
        soft_stops=[], session_data={},
    )
    assert len(result["top_recommendations"]) == 3
    # Crowded out of the capped list...
    assert not any(r.get("review_item") for r in result["top_recommendations"])
    # ...but never lost: still present in the dedicated review_items array.
    assert any(
        r.get("review_item") and "follows form" in r.get("action", "").lower()
        for r in result["review_items"]
    ), f"follow-form review item must survive in review_items, got {result['review_items']}"


# ── Package vs form parity (client req: single form must not diverge) ─────────

_PARITY_FACTS = {
    "producer_name": "Acme Brokers", "applicant_name": "Joe's Roofing LLC",
    "mailing_address": "123 Main St, Dallas TX", "effective_date": "07/01/2026",
    "lines_of_business": ["General Liability"], "entity_type": "LLC",
    "contact_name": "Joe", "contact_phone": "555-1212", "contact_email": "j@x.com",
    "fein": "123456789", "operations_description": "Commercial roofing contractor",
    "total_revenue": "2000000", "prior_carrier": "Old Carrier", "num_employees": "20",
    "years_in_business": "12", "naics_code": "238160", "num_claims": "0",
    "total_payroll": "800000", "gl_limits": "1000000", "gl_aggregate": "2000000",
    "gl_class_codes_by_location": ["98305"], "gl_form_type": "occurrence",
    "acord101_remarks": (
        "Family-owned commercial roofing operator, 12 years in business. "
        "No prior losses. Written safety program with annual inspections."
    ),
}
_PARITY_FLAGS = {"has_general_liability": True}
_PILLAR_KEYS = (
    "structural_completeness", "exposure_consistency", "property_integrity",
    "loss_history_alignment", "umbrella_limit_adequacy", "narrative_quality",
)


def _run_form(fid):
    return sq.calculate_sqs(
        facts=_PARITY_FACTS, flags=_PARITY_FLAGS,
        mapped_data={k: _PARITY_FACTS[k] for k in _PARITY_FACTS},
        form_schema={k: {} for k in _PARITY_FACTS}, selected_form_ids=[fid],
        hard_stops=[], soft_stops=[], tier2_score=80, form_id=fid,
    )


def test_single_form_package_computed_independently():
    # Client-approved model: the package SQS is computed INDEPENDENTLY from the
    # per-form score. Its six pillars come from the package-level calculators run
    # on the merged facts (NOT copied or averaged from the form), and the headline
    # is the weighted sum of those pillars. The package is its own number - it need
    # not equal the single form's score.
    form = _run_form("ACORD_125")
    pkg = sq.calculate_package_sqs(
        _PARITY_FACTS, _PARITY_FLAGS, form_results=[form], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    p = pkg["pillars"]
    # Pillars equal the package-level calculators on the facts (proves independence).
    assert p["exposure_consistency"] == sq._calculate_exposure_consistency(
        _PARITY_FACTS, _PARITY_FLAGS, [], [])[0]
    assert p["property_integrity"] == sq._calculate_cope_score(_PARITY_FACTS, _PARITY_FLAGS)
    # _PARITY has no umbrella → pillar is N/A (None), not borrowed from the form.
    assert p["umbrella_limit_adequacy"] is None
    # Headline = weighted sum of the package's OWN pillars (umbrella N/A → the 0.10
    # weight is redistributed across the other five). This mirrors the production
    # formula exactly, locking "headline = weighted sum of own pillars".
    W = sq.SPEC_PILLAR_WEIGHTS
    scale = 1.0 / (1.0 - W["umbrella_limit_adequacy"])
    expected = int(
        p["structural_completeness"] * W["structural_completeness"] * scale +
        p["exposure_consistency"]    * W["exposure_consistency"]    * scale +
        p["property_integrity"]      * W["property_integrity"]      * scale +
        p["loss_history_alignment"]  * W["loss_history_alignment"]  * scale +
        p["narrative_quality"]       * W["narrative_quality"]       * scale
    )
    assert pkg["package_sqs_score"] == expected, (
        f"headline must be the weighted sum of the package's own pillars: "
        f"expected={expected} got={pkg['package_sqs_score']}"
    )


def test_single_form_package_hard_cross_issue_caps_at_60():
    # A cross-form HARD stop (e.g. building-value / FEIN conflict across documents)
    # is something only the package layer can see. It must cap the PACKAGE at 60,
    # while the form keeps its own (higher) score - the honest divergence the
    # "Form vs Package can differ" UI note explains.
    form = _run_form("ACORD_125")
    assert form["sqs_score"] > 60, f"need an uncapped form (>60) for this guard, got {form['sqs_score']}"
    pkg = sq.calculate_package_sqs(
        _PARITY_FACTS, _PARITY_FLAGS, form_results=[form],
        cross_issues=[{"type": "hard_stop", "message": "FEIN differs across submitted documents"}],
        hard_stops=[], soft_stops=[], session_data={},
    )
    assert pkg["package_sqs_score"] <= 60, (
        f"cross-form hard stop must cap the package at 60, got {pkg['package_sqs_score']}"
    )
    assert pkg["package_sqs_score"] < form["sqs_score"], (
        f"package must sit below the uncapped form: "
        f"package={pkg['package_sqs_score']} form={form['sqs_score']}"
    )


def test_single_form_package_soft_cross_issue_never_raises_package():
    # A cross-form WARNING feeds the package exposure pillar (deduction) and so can
    # only LOWER the package, never raise it. (Current cap policy: cross warnings
    # reduce via the exposure pillar; the 60/85 ceilings come from hard stops /
    # field-level soft stops.)
    form = _run_form("ACORD_125")
    base = sq.calculate_package_sqs(
        _PARITY_FACTS, _PARITY_FLAGS, form_results=[form], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )["package_sqs_score"]
    warned = sq.calculate_package_sqs(
        _PARITY_FACTS, _PARITY_FLAGS, form_results=[form],
        cross_issues=[{"type": "warning", "message": "Mailing address differs across forms"}],
        hard_stops=[], soft_stops=[], session_data={},
    )["package_sqs_score"]
    assert warned <= base, (
        f"a soft cross-form warning must never raise the package: base={base} warned={warned}"
    )


def test_multi_form_package_pillars_computed_independently():
    # New model: with multiple forms the package computes its OWN six pillars from
    # the merged facts - it does NOT average the per-form pillar values. The
    # structural pillar is the package's tier1/tier2/form-fill BLEND (not a plain
    # mean), and the fact-driven pillars equal the package-level calculators.
    f125 = _run_form("ACORD_125")
    f130 = _run_form("ACORD_130")
    pkg = sq.calculate_package_sqs(
        _PARITY_FACTS, _PARITY_FLAGS, form_results=[f125, f130], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    p = pkg["pillars"]
    # Fact-driven pillars come straight from the package calculators (not averaged).
    assert p["exposure_consistency"] == sq._calculate_exposure_consistency(
        _PARITY_FACTS, _PARITY_FLAGS, [], [])[0]
    assert p["property_integrity"] == sq._calculate_cope_score(_PARITY_FACTS, _PARITY_FLAGS)
    assert p["umbrella_limit_adequacy"] == sq._calculate_umbrella_adequacy(_PARITY_FACTS, _PARITY_FLAGS)
    # Structural pillar is the package's own blend. C3 3.2 (2026-08-25) moved it
    # from 35/30/35 to tier1*0.40 + tier2*0.35 + confidence_fill_rate_avg*0.25,
    # so the underlying submission facts outweigh form population. The third
    # component is the average confidence_fill_rate across generated forms —
    # NOT the per-form structural_completeness checklist score. This ensures the
    # package P1 uses a genuinely different signal from the form P1, preventing
    # convergence when the structural checklist fields happen to all be present.
    tier1_ok, tier1_missing = sq.check_tier1(_PARITY_FACTS, _PARITY_FLAGS)
    tier2_score, _ = sq.check_tier2(_PARITY_FACTS, _PARITY_FLAGS)
    tier1_score = 100 if tier1_ok else max(0, 100 - len(tier1_missing) * 20)
    fill_rate_avg = int(
        (f125["confidence_fill_rate"] + f130["confidence_fill_rate"]) / 2
    )
    expected_p1 = int(tier1_score * 0.40 + tier2_score * 0.35 + fill_rate_avg * 0.25)
    assert p["structural_completeness"] == expected_p1, (
        f"package structural must be the tier1/tier2/confidence-fill-rate blend "
        f"{expected_p1}, got {p['structural_completeness']}"
    )


def test_cross_form_issue_does_not_cap_per_form_score():
    # Capping design guard: cross-form stops cap the PACKAGE only, never an
    # individual form. The per-form scorer must ignore cross_issues_full for its
    # 60/85 cap - only its own hard_stops/soft_stops (and its own COPE/umbrella/
    # property gates) may cap it. If this breaks, the recompute paths would
    # silently re-cap forms by cross-form stops, the exact behaviour the design
    # removes (per-form keeps its real score; only the package is capped).
    def _score(**extra):
        return sq.calculate_sqs(
            facts=_PARITY_FACTS, flags=_PARITY_FLAGS,
            mapped_data={k: _PARITY_FACTS[k] for k in _PARITY_FACTS},
            form_schema={k: {} for k in _PARITY_FACTS}, selected_form_ids=["ACORD_125"],
            hard_stops=[], soft_stops=[], tier2_score=80, form_id="ACORD_125", **extra,
        )["sqs_score"]

    base = _score()
    # Guard is only meaningful if the uncapped baseline is above the 60 cap.
    assert base > 60, f"baseline should be uncapped (>60) for this guard, got {base}"
    # A hard cross-form issue must NOT move the per-form headline.
    with_cross = _score(cross_issues_full=[{"type": "hard_stop", "message": "FEIN differs across forms"}])
    assert with_cross == base, (
        f"cross-form issue must not cap the per-form score: base={base} with_cross={with_cross}"
    )
    # Sanity: a genuine per-form hard stop still caps at 60.
    with_hard = sq.calculate_sqs(
        facts=_PARITY_FACTS, flags=_PARITY_FLAGS,
        mapped_data={k: _PARITY_FACTS[k] for k in _PARITY_FACTS},
        form_schema={k: {} for k in _PARITY_FACTS}, selected_form_ids=["ACORD_125"],
        hard_stops=["Named insured missing"], soft_stops=[], tier2_score=80, form_id="ACORD_125",
    )["sqs_score"]
    assert with_hard <= 60, f"per-form hard stop must cap at 60, got {with_hard}"


def test_spec_compliant_emits_umbrella_enrichment_parity():
    # Audit: the spec-compliant variant must emit the SAME §6.5 umbrella enrichment
    # as the live scorer (via shared helpers) so re-wiring it never silently drops
    # the coverage-gap signals.
    facts = {"umbrella_limit": "5000000", "gl_limits": "500000", "auto_liability_limit": "1000000"}
    flags = {"has_umbrella": True}
    res = sq.calculate_package_sqs_spec_compliant(
        facts, flags, form_results=[], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    for key in ("umbrella_state", "follow_form", "umbrella_warnings", "review_items"):
        assert key in res, f"spec-compliant must emit '{key}'"
    assert res["follow_form"]["status"] == "unable_to_determine"
    assert any("umbrella requirements" in w.lower() for w in res["umbrella_warnings"])
    assert any(r.get("review_item") for r in res["review_items"])


# ── ACV vs RCV valuation conflict (client Property Integrity) ─────────────────

def test_acv_rcv_conflict_detected_and_flagged():
    # Source shows an ACV figure while the form basis is RCV → conflict.
    facts = {"valuation_method": "RCV", "property_actual_cash_value": "750000"}
    assert sq._acv_rcv_conflict(facts) is True
    # A synonym is NOT a self-conflict (RCV == 'Replacement Cost Value').
    assert sq._acv_rcv_conflict({"valuation_method": "Replacement Cost Value"}) is False
    assert sq._acv_rcv_conflict({"valuation_method": "RCV"}) is False
    # The conflict surfaces as a review flag (client: "flag as a conflict for review").
    _hard, soft = sq.evaluate_stops(facts, {"has_property_coverage": True})
    assert any("acv" in s.lower() and "rcv" in s.lower() for s in soft)


# ── 6.1 item 4: narrative-derived positive signals ───────────────────────────

def test_positive_signals_management_risk_safety():
    facts = {"acord101_remarks": (
        "Professionally managed by experienced ownership. Written safety program "
        "with annual inspections and an employee handbook.")}
    keys = {s["key"] for s in sq._compute_positive_signals(facts, {})}
    assert "experienced_management" in keys
    assert "risk_controls_described" in keys
    assert "safety_manual" in keys


# ── 6.4 item 1: 'Loss Runs Parsed' evidence state ────────────────────────────

def test_loss_history_state_loss_runs_parsed():
    facts = {"loss_history_years": "4"}
    # Years parsed but ownership not strongly matched → pending validation.
    assert sq._get_loss_history_state(facts, {}, has_loss_run_doc=True, loss_run_match="possible") == "loss_history_pending_validation"
    # Strong match → reconciled (unchanged).
    assert sq._get_loss_history_state(facts, {}, has_loss_run_doc=True, loss_run_match="strong") == "loss_data_reconciled"
    assert "loss_runs_parsed" in sq.LOSS_HISTORY_STATE_LABELS


# ── C1: _to_int combined-limit parser ────────────────────────────────────────

def test_to_int_plain_scalar():
    assert sq._to_int("1000000") == 1000000
    assert sq._to_int("$1,000,000") == 1000000
    assert sq._to_int(1000000) == 1000000


def test_to_int_combined_limit_strings():
    # These are the exact formats the ARQ hint map tells clients to enter (C1).
    assert sq._to_int("$1,000,000 per occurrence / $2,000,000 aggregate") == 1000000
    assert sq._to_int("$1,000,000 combined single limit") == 1000000
    assert sq._to_int("1,000,000/1,000,000/1,000,000") == 1000000
    assert sq._to_int("$500,000 CSL") == 500000


def test_to_int_none_and_garbage():
    assert sq._to_int(None) is None
    assert sq._to_int("not a number") is None
    assert sq._to_int("") is None


def test_umbrella_adequacy_with_combined_limit_string():
    # C1 consequence: combined-limit GL should parse to $1M → full GL credit.
    # Include schedule + follow form to isolate the combined-limit parsing behavior.
    facts = {
        "umbrella_limit": "5000000",
        "gl_limits": "$1,000,000 per occurrence / $2,000,000 aggregate",
        "auto_liability_limit": "$1,000,000 combined single limit",
        "schedule_of_underlying_insurance": "GL $1M; Auto $1M CSL",
        "umbrella_follow_form": "follows form",
    }
    score = sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True})
    assert score == 100, f"Combined-limit string should parse to full credit, got {score}"


def test_umbrella_el_with_combined_limit_string():
    # EL entered as "1,000,000/1,000,000/1,000,000" (common format) must hit $1M tier.
    # Include schedule + follow form to isolate EL combined-limit parsing behavior.
    facts = {
        "umbrella_limit": "5000000",
        "gl_each_occurrence": "1000000",
        "auto_liability_limit": "1000000",
        "employers_liability_limits": "1,000,000/1,000,000/1,000,000",
        "schedule_of_underlying_insurance": "GL $1M; Auto $1M",
        "umbrella_follow_form": "follows form",
    }
    score = sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True, "has_workers_comp": True})
    assert score == 100, f"EL combined-limit string should hit $1M full credit, got {score}"


# ── M3: loss-run self-match exclusion ────────────────────────────────────────

def test_loss_run_self_match_excluded():
    # Only doc is a loss-run that carries its own FEIN. Before M3 fix it would
    # compare loss-run FEIN against itself → "strong". Now → "possible" (name only).
    docs = [{
        "doc_type": "loss_run",
        "facts": {
            "applicant_name": "Orbin Contracting",
            "fein": "123456789",
        }
    }]
    result = sq._check_loss_run_insured_match(docs, "Orbin Contracting")
    assert result == "possible", f"Self-match must not yield 'strong', got {result!r}"


def test_loss_run_strong_match_with_independent_doc():
    # FEIN present on a non-loss-run doc → legitimate strong match.
    docs = [
        {"doc_type": "dec_page", "facts": {"applicant_name": "Orbin Contracting", "fein": "123456789"}},
        {"doc_type": "loss_run", "facts": {"applicant_name": "Orbin Contracting", "fein": "123456789"}},
    ]
    result = sq._check_loss_run_insured_match(docs, "Orbin Contracting")
    assert result == "strong"


# ── M4: required-but-absent underlying coverage ───────────────────────────────

def test_umbrella_penalises_missing_auto_when_auto_exposure_exists():
    # Umbrella + GL present + auto exposure flag but no auto limit → extra deduction vs no-auto-flag.
    facts_no_auto = {"umbrella_limit": "5000000", "gl_each_occurrence": "1000000"}
    facts_auto_missing = {"umbrella_limit": "5000000", "gl_each_occurrence": "1000000"}
    flags_with_auto = {"has_umbrella": True, "has_general_liability": True, "has_auto_coverage": True}
    flags_no_auto   = {"has_umbrella": True, "has_general_liability": True}
    score_with  = sq._calculate_umbrella_adequacy(facts_auto_missing, flags_with_auto)
    score_without = sq._calculate_umbrella_adequacy(facts_no_auto, flags_no_auto)
    assert score_with < score_without, f"Auto exposure without limits should score lower than no-auto-flag: {score_with} vs {score_without}"


def test_umbrella_no_penalty_without_auto_exposure():
    # Umbrella + GL only (no auto exposure flag) → no auto deduction beyond other checks.
    facts = {"umbrella_limit": "5000000", "gl_each_occurrence": "1000000"}
    flags = {"has_umbrella": True, "has_general_liability": True}
    score = sq._calculate_umbrella_adequacy(facts, flags)
    # Score is lower than 100 due to no-schedule (-15) and no-follow-form (-10), but no auto deduction.
    assert score == 75, f"No auto exposure: GL-only umbrella = 100 - 15 - 10 = 75, got {score}"


# ── L6: recency on doc-only loss credit path ──────────────────────────────────

def test_loss_run_doc_stale_gets_recency_penalty():
    # C2 2.4 (2026-08-24) REVERSES the old expectation for the STRONG tier: it
    # is pinned at 60 and recency never moves it (the 60 already prices in the
    # unreadable details - deducting again charged one problem twice). Recency
    # on the doc-only path now applies to the NON-PINNED tiers only, and only
    # when a valuation date exists. Both halves asserted.
    fresh_strong, _ = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "30"}, {}, has_loss_run_doc=True, loss_run_match="strong"
    )
    stale_strong, _ = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "400"}, {}, has_loss_run_doc=True, loss_run_match="strong"
    )
    assert fresh_strong == stale_strong == 60, "the strong tier is pinned (client 2.4)"
    fresh_mod, _ = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "30", "prior_carrier": "X"}, {},
        has_loss_run_doc=True, loss_run_match="moderate"
    )
    stale_mod, recs = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "400", "prior_carrier": "X"}, {},
        has_loss_run_doc=True, loss_run_match="moderate"
    )
    assert stale_mod < fresh_mod, f"stale={stale_mod}, fresh={fresh_mod}"
    assert any("day" in r.lower() for r in recs)


# ── M5: stated_in_narrative evidence label ────────────────────────────────────

def test_derive_evidence_labels_narrative_keys():
    facts = {"operations_description": "commercial roofing"}
    # When the key is in narrative_fact_keys (set by pipeline), label must be
    # stated_in_narrative — even for a plain-string fact.
    flags = {"_narrative_fact_keys": ["operations_description"]}
    labels = sq._derive_evidence_labels(facts, flags=flags)
    assert labels.get("operations_description") == "stated_in_narrative"


def test_derive_evidence_labels_normal_without_narrative_keys():
    facts = {"applicant_name": {"value": "Acme Corp", "confidence": "filled"}}
    labels = sq._derive_evidence_labels(facts)
    assert labels.get("applicant_name") == "extracted_from_source"


def test_evidence_labels_not_applicable_and_requires_doc():
    # §6.1 item 3: coverage-specific facts absent when their line of business is not in
    # the submission read "not applicable"; the umbrella underlying schedule / follow-form
    # absent (umbrella present) and loss-run years absent (no loss run, no attestation)
    # read "requires supporting documentation".
    facts = {"applicant_name": {"value": "Acme", "confidence": "filled"}}
    flags = {"has_umbrella": True}
    labels = sq._derive_evidence_labels(facts, flags=flags, has_loss_run_doc=False)
    # No GL / Auto / WC / property coverage flags → those coverage facts are not applicable.
    assert labels.get("gl_each_occurrence") == "not_applicable"
    assert labels.get("auto_liability_limit") == "not_applicable"
    assert labels.get("employers_liability_limits") == "not_applicable"
    assert labels.get("year_built") == "not_applicable"
    # Umbrella present but underlying schedule / follow-form absent → requires a document.
    assert labels.get("schedule_of_underlying_insurance") == "requires_supporting_doc"
    assert labels.get("umbrella_follow_form") == "requires_supporting_doc"
    # Loss-run years absent with no loss run on file and no attestation → requires loss runs.
    assert labels.get("loss_history_years") == "requires_supporting_doc"


def test_evidence_labels_requires_doc_cleared_by_attestation_and_coverage():
    # A no-loss attestation clears the loss "requires doc"; with no umbrella the
    # underlying schedule is "not applicable" rather than "requires doc".
    facts = {"applicant_name": {"value": "Acme", "confidence": "filled"}}
    flags = {"no_prior_losses": True}
    labels = sq._derive_evidence_labels(facts, flags=flags, has_loss_run_doc=False)
    assert labels.get("loss_history_years") == "not_found"
    assert labels.get("schedule_of_underlying_insurance") == "not_applicable"


# ── Fix #2: warning language — messages humanized, machine matching preserved ──

def test_doc_consistency_messages_have_no_code_or_list_leak():
    docs = [
        {"facts": {"applicant_name": "Orbin Contracting LLC", "dba_name": "Orbin"}},
        {"facts": {"applicant_name": "Smith Roofing Inc", "dba_name": "SR Co"}},
    ]
    issues = sq.check_doc_consistency(docs)
    blob = " ".join(issues)
    # No Python list/set repr leaking into a user-facing message.
    assert "['" not in blob and "']" not in blob and "{'" not in blob
    # Humanized, plain-language phrasing is present.
    assert any("Applicant name differs across documents" in i for i in issues)
    # The machine prefix the pipeline parser depends on is still intact.
    assert any(i.startswith("[hard_stop] code=name_conflict") for i in issues)


def test_humanized_name_conflict_still_always_hard():
    # Post-pipeline message (code prefix already stripped) must STILL be classified
    # as an always-hard stop for a non-property submission.
    msg = "Applicant name differs across documents: Orbin Contracting LLC, Smith Roofing Inc"
    can_proceed, remaining, downgraded = sq.classify_stops([msg], {})
    assert msg in remaining and msg not in downgraded
    assert can_proceed is False


def test_auto_split_message_clean_and_still_hard():
    hard, _soft = sq.evaluate_stops({"bi_per_person": "100000"}, {"has_auto_coverage": True})
    # New message has no code prefix...
    assert not any(h.startswith("auto_split_limits_incomplete:") for h in hard)
    assert any("Split liability limits incomplete" in h for h in hard)
    # ...but is still always-hard for a non-property (auto-only) submission.
    _cp, remaining, _dg = sq.classify_stops(hard, {"has_auto_coverage": True})
    assert any("Split liability limits incomplete" in r for r in remaining)


# ── Fix #4: SIC code satisfies the industry-classification readiness slot ──────

def test_check_tier2_sic_satisfies_industry_code():
    base = {f: "x" for f in sq.TIER2_FIELDS if f != "naics_code"}
    no_wc = {"has_workers_comp": False}
    # SIC present, NAICS absent → industry-code requirement is satisfied.
    score_sic, missing_sic = sq.check_tier2({**base, "sic_code": "1521"}, flags=no_wc)
    assert not any("NAICS" in m or "SIC" in m for m in missing_sic)
    # Neither present → ONE combined "NAICS or SIC" missing item (SIC not ignored).
    _score_none, missing_none = sq.check_tier2(base, flags=no_wc)
    assert any("NAICS or SIC" in m for m in missing_none)
    # SIC-only scores identically to NAICS-only (both satisfy the same slot).
    score_naics, _ = sq.check_tier2({**base, "naics_code": "236220"}, flags=no_wc)
    assert score_sic == score_naics


def test_tier2_carries_no_wc_or_payroll_field_at_all():
    """C3 3.5 / 3.14 (2026-08-25) SUPERSEDES the old has_workers_comp gate.

    This test used to assert the opposite: that the three WC fields ENTER the
    Tier 2 denominator when WC coverage is present. The client removed them
    from Structural outright - *"This prevents WC-specific information from
    penalizing non-WC submissions and places the requirements closer to the
    exposure they describe"* - so the gate has nothing left to gate and the
    `flags` argument no longer changes the answer at all. Their scoring homes
    are now the Exposure payroll bucket and the ACORD 130 checklist.
    """
    removed = {"total_payroll", "wc_xmod", "wc_payroll_period",
               "wc_officer_exclusions", "prior_carrier", "num_claims"}
    assert removed.isdisjoint(sq.TIER2_FIELDS), (
        "C3 3.5 / 3.14 and C2 2.7 / 2.8 removed these from Structural Tier 2"
    )
    assert set(sq.TIER2_FIELDS) == {
        "fein", "operations_description", "total_revenue",
        "num_employees", "years_in_business", "naics_code",
    }, "3.5 lists exactly six V1 Tier 2 fields"

    base = {f: "x" for f in sq.TIER2_FIELDS if f != "naics_code"}
    base["sic_code"] = "1521"        # SIC satisfies the classification item
    # A complete submission reaches 100 whether or not it carries WC, because
    # no WC fact is scored here any more.
    for wc in (False, True):
        score, missing = sq.check_tier2(base, flags={"has_workers_comp": wc})
        assert (score, missing) == (100, []), f"has_workers_comp={wc}"


def test_tier2_removes_not_applicable_from_the_denominator():
    """C3 3.6: *"Not Applicable fields are removed from the denominator."*

    Removal is NOT the same arithmetic as counting the field as answered -
    six fields with one N/A and one genuinely missing is 100 - 100/5 = 80,
    where counting it present would give 100 - 100/6 = 83.
    """
    from services.answer_semantics import build_fact_envelope, interpret_answer

    facts = {f: "x" for f in sq.TIER2_FIELDS}
    facts["fein"] = build_fact_envelope(
        "fein", interpret_answer("fein", "N/A"), "producer", "filled")
    del facts["years_in_business"]

    score, missing = sq.check_tier2(facts, flags={})
    assert score == 80, f"expected the N/A out of the denominator, got {score}"
    assert missing == ["Years in business"]


def test_tier2_every_field_not_applicable_scores_100_not_zero():
    """Nothing is owed, so nothing is missing - never a divide-by-zero or a 0."""
    from services.answer_semantics import build_fact_envelope, interpret_answer

    facts = {
        f: build_fact_envelope(f, interpret_answer(f, "N/A"), "producer", "filled")
        for f in list(sq.TIER2_FIELDS) + ["sic_code"]
    }
    assert sq.check_tier2(facts, flags={}) == (100, [])


# ── §6.3 robustness: LLM narrative-component profile ──────────────────────────
# The profile is the single source of truth shared by scoring, suppression,
# labelling, and recommendations. These tests pass the profile directly (no live
# LLM) so they are deterministic; detect_narrative_components_llm itself is a
# thin LLM wrapper that returns {} (keyword fallback) on any failure.

from services import question_classifier as qc


def test_profile_present_map_is_evidence_gated():
    # present=True but no supporting quote must NOT credit a component, so a
    # hallucinated "present" can never inflate the score or the recommendations.
    prof = {
        "years_in_business": {"present": True, "confidence": 0.9, "evidence": "operated for over a decade"},
        "management":        {"present": True, "confidence": 0.9, "evidence": ""},
    }
    pm = sq.narrative_profile_present_map(prof)
    assert pm["years_in_business"] is True
    assert pm["management"] is False


def test_profile_credits_paraphrase_the_keywords_miss():
    # "operated for over a decade" is NOT in the keyword phrase list, so the
    # keyword scan alone would mark years_in_business missing. The profile fixes it.
    text = "We have operated for over a decade serving the region."
    assert sq._score_narrative_components(text)["years_in_business"] is False
    prof = {"years_in_business": {"present": True, "confidence": 0.9, "evidence": "operated for over a decade"}}
    _score, comps, _ = sq._calculate_narrative_quality(
        {"acord101_remarks": text}, flags={"narrative_profile": prof})
    assert comps["years_in_business"] is True


def test_profile_floor_when_classification_missed_the_narrative():
    # No classified narrative doc and no structured remarks, but the profile (from
    # a mis-classified narrative's body) detected components -> floor still applies.
    prof = {"operations": {"present": True, "confidence": 0.9, "evidence": "general contractor doing TI work"}}
    score, comps, _ = sq._calculate_narrative_quality(
        {}, has_narrative_doc=False, flags={"narrative_profile": prof}, narrative_doc_text="")
    assert comps["operations"] is True
    assert score >= 40


def test_profile_fact_keys_are_conservative():
    # Attribution must NOT claim precise figures (claim counts, payroll, headcount,
    # addresses) are narrative-sourced — only prose-basis facts.
    prof = {
        "operations":   {"present": True, "confidence": 1.0, "evidence": "GC"},
        "loss_history": {"present": True, "confidence": 1.0, "evidence": "no losses in five years"},
        "employee_practices": {"present": True, "confidence": 1.0, "evidence": "20 staff"},
    }
    keys = sq.narrative_profile_fact_keys(prof)
    assert "operations_description" in keys
    assert "loss_history_no_prior_losses_indicator" in keys
    assert "num_employees" not in keys and "total_payroll" not in keys


def test_label_stated_in_narrative_from_profile_with_generic_ai_source():
    # Generic "ai" provenance + a profile-evidenced fact -> stated_in_narrative,
    # without the document being classified "narrative" (closes the gap).
    facts = {"operations_description": {"value": "GC", "confidence": "ai_high", "source": "ai"}}
    labels = sq._derive_evidence_labels(facts, flags={"_narrative_fact_keys": ["operations_description"]})
    assert labels["operations_description"] == "stated_in_narrative"


def test_label_specific_source_still_wins_over_narrative():
    # A SPECIFIC non-narrative source (a dec page provided the value) must not be
    # relabelled as narrative even when the key is in the narrative key set.
    facts = {"operations_description": {"value": "GC", "confidence": "ai_high", "source": "dec_page"}}
    labels = sq._derive_evidence_labels(facts, flags={"_narrative_fact_keys": ["operations_description"]})
    assert labels["operations_description"] == "extracted_from_source"


def test_suppression_bucket_a_suppresses_bucket_b_does_not():
    qs = [
        {"field_name": "operations_description", "_canonical_key": "operations_description", "_is_curated_client": True},
        {"field_name": "gl_each_occurrence", "_canonical_key": "gl_each_occurrence", "_is_curated_client": True},
    ]
    qc.decorate_questions(qs, narrative_components={"operations": True, "coverage_discussion": True})
    # Bucket A: narrative prose IS the answer → suppress.
    assert qs[0]["suppressed"] is True
    assert qs[0]["suppressed_reason"] == "stated_in_narrative"
    # Bucket B: narrative covers the topic but "gl_each_occurrence" was not extracted
    # (not in present_fact_keys), so the question is NOT suppressed — the client
    # still needs to confirm the exact value. Suppression for extracted values is
    # handled by the "already_provided" overlay, not here.
    assert qs[1].get("suppressed") is not True


def test_flag_off_default_behaviour_unchanged():
    # With no profile in flags, narrative scoring and suppression behave exactly
    # as the keyword-only pipeline (the feature is purely additive).
    text = ("Operations include commercial roofing. No prior losses. "
            "Coverage includes general liability.")
    a_score, a_comps, _ = sq._calculate_narrative_quality({"acord101_remarks": text})
    b_score, b_comps, _ = sq._calculate_narrative_quality({"acord101_remarks": text}, flags={})
    assert a_score == b_score and a_comps == b_comps


# ── Gap 1: N/A umbrella excluded from ranking (not substituted with 100) ─────

def test_na_umbrella_excluded_from_recommendation_ranking():
    # When umbrella is N/A (has_umbrella=False → p5=None), the pillar must be
    # EXCLUDED from the ranked recommendations list, not given a fictitious 100
    # that silently prevents it from ever surfacing. The fix is a structural one:
    # None values are filtered out before sorting instead of being substituted.
    result = sq.calculate_package_sqs(
        {}, {}, form_results=[], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    # No umbrella submission → umbrella pillar is N/A.
    assert result.get("umbrella_state") == "not_applicable"
    # The N/A pillar must never appear in top recommendations.
    for rec in result.get("top_recommendations", []):
        assert rec.get("pillar") != "umbrella_limit_adequacy", (
            "N/A umbrella must not appear in top_recommendations"
        )
    # The weights_used dict must not contain a score for the umbrella pillar
    # (it is redistributed, not present at 0 or 100).
    assert result.get("umbrella_limit_adequacy") is None or "umbrella_limit_adequacy" not in (
        result.get("pillar_scores", {}) or {}
    )


# ── Gap 2: Cross-form GL/Auto checks run when has_umbrella=True without ACORD 131 ─

def test_cross_form_gl_check_fires_without_acord131_selected():
    # Req 3 gap: GL attachment check was gated on ACORD 131 being in triggered_ids.
    # If umbrella docs are present (has_umbrella=True) but the user hasn't selected
    # ACORD 131, the cross-form warning must still fire to match the SQS scoring layer.
    from services import cross_form_validator as cfv
    facts = {"umbrella_limit": "5000000", "gl_each_occurrence": "500000"}
    flags = {"has_umbrella": True}
    # Deliberately omit ACORD_131 from triggered_ids.
    triggered = {"ACORD_125", "ACORD_126"}
    issues = cfv.run_cross_form_validation(facts, flags, triggered)
    _hard, soft, _adv = cfv.split_cross_form_issues(issues)
    assert any("umbrella requirements" in s.lower() for s in soft), (
        f"GL-below-minimum must surface even without ACORD 131 selected, got soft={soft}"
    )


def test_cross_form_auto_check_fires_without_acord131_selected():
    # Req 3 gap (Auto parity): Auto attachment check had the same ACORD 131 gate.
    from services import cross_form_validator as cfv
    facts = {"umbrella_limit": "5000000", "auto_liability_limit": "500000"}
    flags = {"has_umbrella": True, "has_auto_coverage": True}
    # Deliberately omit ACORD_131 from triggered_ids.
    triggered = {"ACORD_125", "ACORD_127"}
    issues = cfv.run_cross_form_validation(facts, flags, triggered)
    _hard, soft, _adv = cfv.split_cross_form_issues(issues)
    assert any("auto" in s.lower() and "umbrella requirements" in s.lower() for s in soft), (
        f"Auto-below-minimum must surface even without ACORD 131 selected, got soft={soft}"
    )


# ── Gap 3: Hyphenated "follow-form" recognized as explicit confirmation ────────

def test_follow_form_hyphenated_variant_recognized():
    # Req 4 gap: "follow-form" (hyphenated compound adjective) was missing from the
    # detection term list. A policy stating "this is a follow-form excess policy"
    # uses the industry-standard hyphenated form and must be confirmed, not treated
    # as "unable to determine".
    result = sq._get_follow_form_status({
        "acord101_remarks": "This is a follow-form excess policy over the underlying."
    })
    assert result["status"] == "follow_form_confirmed", (
        f"Hyphenated 'follow-form' must be recognized, got status={result['status']!r}"
    )


def test_follow_form_hyphenated_negated_still_rejected():
    # Negation guard must still work for the hyphenated variant: "does not follow-form"
    # or "not a follow-form policy" must NOT confirm follow-form.
    result = sq._get_follow_form_status({
        "acord101_remarks": "This is not a follow-form policy; coverage is occurrence-based."
    })
    assert result["status"] == "unable_to_determine", (
        f"Negated hyphenated 'follow-form' must not confirm, got status={result['status']!r}"
    )
