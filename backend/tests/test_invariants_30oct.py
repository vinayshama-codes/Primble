"""The runtime invariant checker (services/invariants.py, 30 Oct 2026): for each
rule a minimal session that passes and one that breaks it, plus the contract
(never raises, never mutates, INVARIANTS=0 off) and a run over the stored
fixtures."""
import copy
import json
import logging
import os

import pytest

from services import invariants as inv
from services.invariants import RULES, check, log_breaches

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _rules(breaches):
    return {b["rule"] for b in breaches}


def test_every_rule_described_and_implemented():
    assert set(RULES) == set(inv._RULE_FUNCS)
    assert len(RULES) >= 10


def test_never_raises_and_never_mutates():
    for bad in (None, {}, {"facts": "x"}, {"generated_forms": [1]}, {"package_sqs": 5}):
        for st in inv.STAGES:
            assert isinstance(check(bad, stage=st), list)
    s = {"facts": {"a": {"value": 1}}, "package_sqs": {"package_sqs_score": 90, "open_hard_stops": 1}}
    before = copy.deepcopy(s)
    check(s, stage="pre_form")
    assert s == before
    assert check(s, stage="nonsense") == []


def test_breach_shape_and_log(caplog):
    s = {"id": "abc", "package_sqs": {"package_sqs_score": 90, "open_hard_stops": 1,
                                      "ready_blockers": ["x"]}}
    with caplog.at_level(logging.WARNING):
        out = log_breaches(s, stage="pre_form")
    assert out and set(out[0]) == {"rule", "detail", "where"}
    assert "INVARIANT_BROKEN rule=cap_matches_stops stage=pre_form session=abc" in caplog.text


def test_off_switch(monkeypatch):
    monkeypatch.setenv("INVARIANTS", "0")
    assert log_breaches({"package_sqs": {"package_sqs_score": 90, "open_hard_stops": 1}},
                        stage="pre_form") == []


# 1 ---------------------------------------------------------------------------
def test_prior_policy_placed_once_pass_and_break(monkeypatch):
    s = {"facts": {"prior_coverage_by_line": [
        {"line": "General Liability", "carrier": "A Co", "policy_no": "GL1", "effective": "01/01/2023",
         "expiration": "01/01/2024", "premium": "$1,000"}]}}
    assert "prior_policy_placed_once" not in _rules(check(s, stage="merge"))

    from services import pdf_service

    class G(dict):
        set_aside = ()
    lost = G()
    monkeypatch.setattr(pdf_service, "_prior_coverage_grid_build", lambda f: (lost, []))
    assert "prior_policy_placed_once" in _rules(check(s, stage="merge"))

    e = {"line": "General Liability", "policy_no": "GL1", "effective": "01/01/2023"}
    both = G({("GeneralLiability", 0): e})
    both.set_aside = (e,)
    monkeypatch.setattr(pdf_service, "_prior_coverage_grid_build", lambda f: (both, []))
    details = [b["detail"] for b in check(s, stage="merge") if b["rule"] == "prior_policy_placed_once"]
    assert any("both" in d for d in details) and any("keyed by year" in d for d in details)


# 2 ---------------------------------------------------------------------------
def test_fixed_format_identifiers():
    facts = {"auto_vin_schedule": [{"vin": "1FT123", "year": "2018"}]}
    assert "fixed_format_identifiers" in _rules(check({"facts": facts}, stage="pre_form"))
    named = {"facts": facts, "soft_stops": ["Vehicle 1 VIN is not 17 characters"]}
    assert "fixed_format_identifiers" not in _rules(check(named, stage="pre_form"))
    old = {"facts": {"auto_vin_schedule": [{"vin": "ABC123", "year": "1975"}]}}
    assert "fixed_format_identifiers" not in _rules(check(old, stage="pre_form"))


# 3 ---------------------------------------------------------------------------
def _plan_session(items, score=90):
    return {"package_sqs": {"package_sqs_score": score, "review_plan": {"items": items}}}


def test_points_add_up():
    ok = _plan_session([{"id": "a", "points": 6}, {"id": "b", "points": 4},
                        {"id": "c", "points": 0, "mirror_of": "a"}])
    assert "points_add_up" not in _rules(check(ok, stage="pre_form"))
    short = _plan_session([{"id": "a", "points": 6}])
    assert "points_add_up" in _rules(check(short, stage="pre_form"))
    mirror = _plan_session([{"id": "a", "points": 10}, {"id": "c", "points": 2, "mirror_of": "a"}])
    assert "points_add_up" in _rules(check(mirror, stage="pre_form"))
    neg = _plan_session([{"id": "a", "points": 12}, {"id": "b", "points": -2}])
    assert "points_add_up" in _rules(check(neg, stage="pre_form"))
    at100 = _plan_session([{"id": "a", "points": 0, "under": True}], score=100)
    assert "points_add_up" in _rules(check(at100, stage="pre_form"))


# 4 ---------------------------------------------------------------------------
def test_cap_matches_stops():
    ok = {"package_sqs": {"package_sqs_score": 60, "cap_applied": 60, "open_hard_stops": 1,
                          "ready_blockers": ["No proposed term"]}}
    assert "cap_matches_stops" not in _rules(check(ok, stage="pre_form"))
    over = {"package_sqs": {"package_sqs_score": 72, "open_hard_stops": 1, "ready_blockers": ["x"]}}
    assert "cap_matches_stops" in _rules(check(over, stage="pre_form"))
    nameless = {"package_sqs": {"package_sqs_score": 60, "cap_applied": 60, "open_hard_stops": 0}}
    assert "cap_matches_stops" in _rules(check(nameless, stage="pre_form"))
    soft = {"package_sqs": {"package_sqs_score": 90, "cap_applied": 85}}
    assert "cap_matches_stops" in _rules(check(soft, stage="pre_form"))


# 5 ---------------------------------------------------------------------------
def test_form_score_matches_holds(monkeypatch):
    from services import sqs_service
    gen = {"ACORD_125": {"mapped": {"A": "x"}, "confidence": {},
                         "sqs": {"sqs_score": 92, "raw_sqs_score": 92, "cap_applied": None}}}
    monkeypatch.setattr(sqs_service, "_form_download_blocker", lambda *a, **k: None)
    assert "form_score_matches_holds" not in _rules(check({"generated_forms": gen}, stage="after_forms"))
    monkeypatch.setattr(sqs_service, "_form_download_blocker", lambda *a, **k: "blocked")
    assert "form_score_matches_holds" in _rules(check({"generated_forms": gen}, stage="after_forms"))
    monkeypatch.setattr(sqs_service, "_form_download_blocker", lambda *a, **k: None)
    low = copy.deepcopy(gen)
    low["ACORD_125"]["sqs"].update(sqs_score=60, cap_applied=60)
    assert "form_score_matches_holds" in _rules(check({"generated_forms": low}, stage="after_forms"))


# 6 ---------------------------------------------------------------------------
def test_every_item_answerable():
    msg = "Some hard stop"
    ok = {"hard_stops": [msg], "structured_issues": [
        {"code": "x", "message": msg, "resolution": {"mode": "field", "facts": ["a"]}}]}
    assert "every_item_answerable" not in _rules(check(ok, stage="pre_form"))
    bad = {"hard_stops": [msg], "structured_issues": [
        {"code": "x", "message": msg, "resolution": {"mode": "none"}}]}
    assert "every_item_answerable" in _rules(check(bad, stage="pre_form"))
    neutral = {"hard_stops": [msg], "structured_issues": [
        {"code": "x", "message": msg, "resolution": {"mode": "none"}, "score_neutral": True}]}
    assert "every_item_answerable" not in _rules(check(neutral, stage="pre_form"))
    warn = {"soft_stops": [msg], "package_sqs": {"package_sqs_score": 85, "cap_applied": 85, "cap_reason": msg},
            "structured_issues": [{"code": "x", "message": msg, "resolution": {"mode": "none"}}]}
    assert "every_item_answerable" in _rules(check(warn, stage="pre_form"))


# 7 ---------------------------------------------------------------------------
def test_no_foreign_insured_facts():
    docs = [{"filename": "a", "facts": {"applicant_name": "Choice Electric LLC"}},
            {"filename": "b", "facts": {"applicant_name": "Harborline Plumbing Inc",
                                        "fein": "12-3456789"}}]
    bad = {"facts": {"applicant_name": "Choice Electric LLC", "fein": {"value": "12-3456789"}}, "docs": docs}
    assert "no_foreign_insured_facts" in _rules(check(bad, stage="merge"))
    docs[0]["facts"]["fein"] = "12-3456789"
    assert "no_foreign_insured_facts" not in _rules(check(bad, stage="merge"))


# 8 ---------------------------------------------------------------------------
def test_dashboard_equals_page():
    ok = {"_page": {"package_sqs": {"package_sqs_score": 77}, "saved_pre_form_score": {"package_sqs_score": 77}}}
    assert "dashboard_equals_page" not in _rules(check(ok, stage="pre_form"))
    bad = {"_page": {"package_sqs": {"package_sqs_score": 77}, "saved_pre_form_score": {"package_sqs_score": 74}}}
    assert "dashboard_equals_page" in _rules(check(bad, stage="pre_form"))
    after = dict(bad, generated_forms={"ACORD_125": {}})
    assert "dashboard_equals_page" not in _rules(check(after, stage="pre_form"))


# 9 ---------------------------------------------------------------------------
def test_loss_window_consistent():
    docs = [{"doc_type": "loss_run", "facts": {"loss_run_valuation_date": "03/01/2024",
                                               "loss_run_period_end": "01/01/2024"}},
            {"doc_type": "loss_run", "facts": {"loss_run_valuation_date": "09/01/2026",
                                               "loss_run_period_end": "07/01/2026"}}]
    ok = {"docs": docs, "facts": {"loss_run_valuation_date": "09/01/2026", "loss_run_period_end": "07/01/2026"}}
    assert "loss_window_consistent" not in _rules(check(ok, stage="merge"))
    stale = {"docs": docs, "facts": {"loss_run_valuation_date": "03/01/2024", "loss_run_period_end": "01/01/2024"}}
    assert len([b for b in check(stale, stage="merge") if b["rule"] == "loss_window_consistent"]) == 2
    excl = copy.deepcopy(stale)
    excl["docs"][1]["excluded"] = True
    assert "loss_window_consistent" not in _rules(check(excl, stage="merge"))


# 10 --------------------------------------------------------------------------
def test_no_placeholder_or_list_in_boxes():
    ok = {"generated_forms": {"ACORD_125": {"mapped": {"A": "Choice Electric LLC", "B": "", "C": None}}}}
    assert "no_placeholder_or_list_in_boxes" not in _rules(check(ok, stage="generation"))
    for bad_val in ("None", "nan", "['a', 'b']", "{'value': 1}", ["a"]):
        bad = {"generated_forms": {"ACORD_125": {"mapped": {"A": bad_val}}}}
        assert "no_placeholder_or_list_in_boxes" in _rules(check(bad, stage="generation")), bad_val


# Stored fixtures --------------------------------------------------------------
@pytest.mark.parametrize("name", ["orbin_live_24sep.json", "orbin_live_25sep.json"])
def test_stored_fixtures_run(name):
    d = json.load(open(os.path.join(FIX, name)))
    session = {"facts": d.get("merged_facts") or {}, "flags": d.get("flags") or {},
               "docs": d.get("documents") or []}
    for st in inv.STAGES:
        out = check(session, stage=st)
        assert isinstance(out, list)


def test_g1_never_narrows_a_relationship_card():
    """The attestation conflict: the well-formed "no losses" answer IS the wrong
    value, so the window keeps it beside the empty total (30 Oct 2026)."""
    from services.issue_registry import boxes_that_need_fixing, is_relationship_code
    res = {"mode": "field", "facts": ["loss_history_no_prior_losses_indicator", "num_claims", "total_incurred"]}
    facts = {"loss_history_no_prior_losses_indicator": "No - no claims or losses in the past 5 years",
             "num_claims": "3"}
    assert is_relationship_code("loss_history_attestation_conflict")
    assert boxes_that_need_fixing(res, facts, "loss_history_attestation_conflict") == res
    # A missing-box card still narrows.
    assert boxes_that_need_fixing(res, facts, "legacy_some_missing_card")["facts"] == ["total_incurred"]


def test_pre_form_key_detail_names_no_form():
    from services.issue_registry import pre_form_view
    view = {"hard_stops": [], "warnings": {"required": [{
        "cluster": "Missing baseline ACORD 125 fields", "count": 1,
        "primary_message": "ACORD 125 minimum field missing: Producer / Agency name",
        "items": [{"code": "tier1_missing_Producer / Agency name", "issue_id": "x",
                   "message": "ACORD 125 minimum field missing: Producer / Agency name"}]}]}}
    out = pre_form_view(view)
    c = out["warnings"]["required"][0]
    assert c["cluster"] == "Missing key details"
    assert c["items"][0]["message"] == "Key detail missing: Producer / Agency name"
    assert c["primary_message"] == c["items"][0]["message"]
    assert c["items"][0]["issue_id"] == "x"
    assert view["warnings"]["required"][0]["items"][0]["message"].startswith("ACORD 125")   # a copy


def test_every_multi_box_card_is_sorted_missing_or_relationship():
    """Seed 5036: the backwards-term card kept only the empty umbrella box (the two
    proposed dates are each well formed, together backwards). Every multi-box field
    card is either a MISSING card (G1 narrows) or a RELATIONSHIP card (all boxes
    stay); a new card lands in this list and someone decides."""
    from services import issue_registry as ir
    maps = dict(getattr(ir, "RESOLUTION_MAP", {}))
    maps.update(getattr(ir, "_LEGACY_CODE_RESOLUTIONS", {}))
    narrowing = sorted(c for c, r in maps.items()
                       if isinstance(r, dict) and r.get("mode") == "field"
                       and len(r.get("facts") or []) >= 2 and not ir.is_relationship_code(c))
    for code in ("legacy_policy_term_backwards", "legacy_policy_term_expired", "legacy_policy_term_expiring",
                 "legacy_umbrella_term_backwards", "umbrella_gl_attachment_failure"):
        assert ir.is_relationship_code(code), code
    assert narrowing == sorted([
        "auto_split_limits_incomplete", "bi_coverage_no_limit", "carrier_grade_cope_incomplete",
        "legacy_auto_physical_damage_deductibles", "legacy_auto_split_limits_incomplete", "legacy_bi_no_limit",
        "legacy_carrier_grade_cope", "legacy_minimum_viable_cope", "legacy_peril_deductibles_undefined",
        "legacy_property_integrity_gate", "legacy_umbrella_gate_detail_incomplete",
        "legacy_umbrella_gate_no_underlying", "legacy_umbrella_no_underlying",
        "legacy_umbrella_renewal_term_unknown", "legacy_umbrella_scheduled_gl_limit_missing",
        "legacy_umbrella_scheduled_limit_missing", "legacy_wc_payroll_missing", "minimum_viable_cope_missing",
        "peril_deductible_referenced_but_undefined", "property_coinsurance_missing",
        "property_peril_deductible_incomplete", "umbrella_gl_limits_not_found", "umbrella_no_underlying_coverage",
    ]), narrowing


def test_pre_form_cards_say_written_explanation_not_acord_101():
    """Policy-by-line kit: "Or add an ACORD 101 explanation" named a form before
    forms (G14). The display copy says a written explanation; the id is kept."""
    from services.issue_registry import pre_form_view
    for msg in ("Dates differ. Fix: Or add an ACORD 101 explanation of the date difference.",
                "Payroll is off. Reconcile or add ACORD 101 explanation."):
        v = pre_form_view({"hard_stops": [{"cluster": "x", "count": 1,
                                           "items": [{"code": "c", "message": msg, "issue_id": "k"}]}],
                           "warnings": {}})
        out = v["hard_stops"][0]["items"][0]
        assert "ACORD" not in out["message"] and "a written explanation" in out["message"]
        assert out["issue_id"] == "k"
