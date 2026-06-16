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
    # Full credit requires: adequate limits + schedule of underlying + follow form
    facts = {
        "gl_limits": "1000000",
        "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M each occurrence; Auto $1M CSL",
        "umbrella_follow_form": "follows form over underlying policies",
    }
    assert sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True}) == 100


def test_umbrella_low_gl_reduces_not_blocks():
    # -20 for GL below $1M; -15 no schedule; -10 no follow form = 55
    facts = {"gl_limits": "500000", "auto_liability_limit": "1000000"}
    score = sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True})
    assert score == 55  # -20 GL + -15 no schedule + -10 no follow form; never a hard stop


def test_umbrella_el_tiers_q2():
    # Base deductions: -15 no schedule, -10 no follow form = -25 on top of EL tiers
    base = {"gl_limits": "1000000", "auto_liability_limit": "1000000"}
    flags = {"has_umbrella": True, "has_workers_comp": True}
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "1000000"}, flags) == 75  # 100 - 25
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "500000"}, flags) == 65   # -10 EL - 25
    assert sq._calculate_umbrella_adequacy({**base, "employers_liability_limits": "250000"}, flags) == 50   # -25 EL - 25
    assert sq._calculate_umbrella_adequacy(base, flags) == 50                                               # EL missing -25 - 25


# ── Umbrella evidence states (§6.5) ───────────────────────────────────────────

def test_umbrella_state_machine():
    assert sq._get_umbrella_state({}, {}) == "not_applicable"
    assert sq._get_umbrella_state({}, {"has_umbrella": True}) == "insufficient_information"
    assert sq._get_umbrella_state({"umbrella_limit": "5000000"}, {"has_umbrella": True}) == "umbrella_information_provided"
    low = {"umbrella_limit": "5000000", "gl_limits": "500000"}
    assert sq._get_umbrella_state(low, {"has_umbrella": True}) == "umbrella_coverage_needs_review"
    ok = {"umbrella_limit": "5000000", "gl_limits": "1000000", "auto_liability_limit": "1000000"}
    assert sq._get_umbrella_state(ok, {"has_umbrella": True}) == "umbrella_coverage_present"
    full = {
        "umbrella_limit": "5000000", "gl_limits": "1000000", "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M/$2M; Auto $1M CSL",
        "acord101_remarks": "The umbrella follows form over all underlying policies",
    }
    assert sq._get_umbrella_state(full, {"has_umbrella": True}) == "adequately_supported"


# ── Follow-form Option B (Q4) ─────────────────────────────────────────────────

def test_follow_form_explicit_only():
    confirmed = sq._get_follow_form_status({"acord101_remarks": "The umbrella follows form over the underlying GL."})
    assert confirmed["status"] == "follow_form_confirmed"
    unknown = sq._get_follow_form_status({"acord101_remarks": "General account narrative with no coverage structure."})
    assert unknown["status"] == "unable_to_determine"
    assert sq._get_follow_form_status({})["status"] == "unable_to_determine"


# ── Loss history (Q3 tiers / recency / insured match) ─────────────────────────

def test_loss_year_tiers():
    # 5+ years + prior carrier → full credit (+10 carrier, capped at 100).
    full, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {})
    assert full == 100
    # 3-4 years base = 80 (client table). Prior carrier MISSING applies -10 → 70.
    partial, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30"}, {})
    assert partial == 70
    # 3-4 years WITH prior carrier: +10 → 90 (client: prior carrier present +10).
    partial_with_carrier, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {})
    assert partial_with_carrier == 90
    # 1-2 years base = 40; prior carrier missing -10 → 30.
    thin, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "2", "loss_run_age_days": "30"}, {})
    assert thin == 30
    # No loss info: 25 (client V1) — carrier adjustment does not apply on this path.
    none, _ = sq.calculate_p4_loss_history({}, {})
    assert none == 25


def test_loss_prior_carrier_delta():
    # Client: prior carrier present +10, missing -10 on the same base tier.
    with_c, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30", "prior_carrier": "Travelers"}, {})
    without_c, _ = sq.calculate_p4_loss_history(
        {"loss_history_years": "3", "loss_run_age_days": "30"}, {})
    assert with_c - without_c == 20  # (+10) - (-10)


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
        {"loss_history_years": "5", "loss_run_age_days": "30", "prior_carrier": "X"}, {})
    stale, recs = sq.calculate_p4_loss_history(
        {"loss_history_years": "5", "loss_run_age_days": "400", "prior_carrier": "X"}, {})
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
    # Loss runs uploaded WITH a prior carrier (the realistic case - loss runs name
    # the carrier): match credit (50/35/15) + prior-carrier +10. Fresh (age 30) so
    # the recency penalty doesn't apply.
    fresh = {"loss_run_age_days": "30", "prior_carrier": "Travelers"}
    strong, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="strong")
    possible, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="possible")
    nomatch, _ = sq.calculate_p4_loss_history(fresh, {}, has_loss_run_doc=True, loss_run_match="no_match")
    assert strong == 60     # 50 + 10 prior carrier
    assert possible == 45   # 35 + 10
    assert nomatch == 25    # 15 + 10


def test_loss_run_doc_carrier_adjustment():
    # Client: prior carrier +10 / -10 applies on the loss-run-uploaded path too
    # ("commonly found on loss runs and prior policy documents").
    fresh = {"loss_run_age_days": "30"}
    with_c, _ = sq.calculate_p4_loss_history(
        {**fresh, "prior_carrier": "Travelers"}, {}, has_loss_run_doc=True, loss_run_match="strong")
    without_c, _ = sq.calculate_p4_loss_history(
        fresh, {}, has_loss_run_doc=True, loss_run_match="strong")
    assert with_c == 60     # 50 + 10
    assert without_c == 40  # 50 - 10


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


# ── Narrative quality (§6.3 tuple + components) ───────────────────────────────

def test_narrative_returns_tuple_and_components():
    score, components = sq._calculate_narrative_quality({})
    assert score == 0
    assert isinstance(components, dict) and not any(components.values())


def test_narrative_floor_with_doc():
    score, _ = sq._calculate_narrative_quality({}, has_narrative_doc=True)
    assert score >= 40


def test_narrative_components_detected():
    text = ("Account overview: established in 2003 with 20 years of experience. "
            "Operations include commercial roofing. Management has strong safety practices "
            "and written safety program. No prior losses. Coverage includes general liability.")
    score, components = sq._calculate_narrative_quality({"acord101_remarks": text})
    assert score > 0
    assert components["operations"] and components["risk_controls"] and components["loss_history"]


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
    facts_no_auto = {"gl_each_occurrence": "1000000"}
    facts_auto_missing = {"gl_each_occurrence": "1000000"}
    flags_with_auto = {"has_umbrella": True, "has_general_liability": True, "has_auto_coverage": True}
    flags_no_auto   = {"has_umbrella": True, "has_general_liability": True}
    score_with  = sq._calculate_umbrella_adequacy(facts_auto_missing, flags_with_auto)
    score_without = sq._calculate_umbrella_adequacy(facts_no_auto, flags_no_auto)
    assert score_with < score_without, f"Auto exposure without limits should score lower than no-auto-flag: {score_with} vs {score_without}"


def test_umbrella_no_penalty_without_auto_exposure():
    # Umbrella + GL only (no auto exposure flag) → no auto deduction beyond other checks.
    facts = {"gl_each_occurrence": "1000000"}
    flags = {"has_umbrella": True, "has_general_liability": True}
    score = sq._calculate_umbrella_adequacy(facts, flags)
    # Score is lower than 100 due to no-schedule (-15) and no-follow-form (-10), but no auto deduction.
    assert score == 75, f"No auto exposure: GL-only umbrella = 100 - 15 - 10 = 75, got {score}"


# ── L6: recency on doc-only loss credit path ──────────────────────────────────

def test_loss_run_doc_stale_gets_recency_penalty():
    # L6 fix: doc-only credit path must apply recency. Compare explicitly fresh
    # (age=30) vs stale (age=400) so both sides are determinate.
    fresh, _ = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "30"}, {}, has_loss_run_doc=True, loss_run_match="strong"
    )
    stale, recs = sq.calculate_p4_loss_history(
        {"loss_run_age_days": "400"}, {}, has_loss_run_doc=True, loss_run_match="strong"
    )
    assert stale < fresh, f"Stale doc-only path should score below fresh: stale={stale}, fresh={fresh}"
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
    # SIC present, NAICS absent → industry-code requirement is satisfied.
    score_sic, missing_sic = sq.check_tier2({**base, "sic_code": "1521"})
    assert not any("NAICS" in m or "SIC" in m for m in missing_sic)
    # Neither present → ONE combined "NAICS or SIC" missing item (SIC not ignored).
    _score_none, missing_none = sq.check_tier2(base)
    assert any("NAICS or SIC" in m for m in missing_none)
    # SIC-only scores identically to NAICS-only (both satisfy the same slot).
    score_naics, _ = sq.check_tier2({**base, "naics_code": "236220"})
    assert score_sic == score_naics
