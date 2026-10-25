"""Brent's answers of 19 Oct 2026, part C - the SQS rule (25sepChanges.md part Z28).

  * "No automatic 60 cap: a hard stop blocks Ready to Submit until resolved, with
    no numeric cap" - and the 85 goes by the same rule (owner's call, Z27);
  * "keep true hard stops rare" - hard only for: documents naming different
    companies, no proposed term, property without Minimum Viable COPE, a
    monopolistic state with a private carrier, an umbrella with no underlying;
  * "never penalise the same missing information twice: Completeness deducts for
    missing applicable required information; Exposure Consistency deducts only
    for independently identified conflicts between documented exposures" - the
    missing items move to Completeness with the SAME points.

20 Oct 2026 (owner): the caps came back - an open hard stop holds the score at
60 and an open warning at 85, exactly as before the 19 Oct build. Everything
else here stays: the short hard-stop list, a hard stop also blocking Submission
Ready (`ready_blockers` / `open_hard_stops` / `submission_ready`), and the
Completeness / Exposure split.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import sqs_service as sq                        # noqa: E402

_FACTS = {
    "applicant_name": "Acme LLC", "mailing_address": "1 Main St, Denver CO 80202",
    "effective_date": "2026-07-15", "lines_of_business": ["General Liability"],
    "entity_type": "LLC", "contact_name": "Jo", "producer_name": "Broker Inc",
    "fein": "12-3456789", "num_employees": "40", "years_in_business": "12",
    "operations_description": "Residential roofing contractor with 12 crews",
    "total_revenue": "2000000", "naics_code": "238160",
}


def _pkg(facts=None, flags=None, **kw):
    base = dict(facts=dict(_FACTS if facts is None else facts),
                flags=dict({"has_general_liability": True} if flags is None else flags),
                form_results=[], cross_issues=[], hard_stops=[], soft_stops=[],
                session_data={}, form_fill=False)
    base.update(kw)
    tok = sq.SKIP_SHARE_OUT.set(True)
    try:
        return sq.calculate_package_sqs(**base)
    finally:
        sq.SKIP_SHARE_OUT.reset(tok)


# ══ 1. The caps (back on 20 Oct 2026, owner) ═══════════════════════════════

def test_the_caps_are_back_exactly_as_before():
    assert (sq.HARD_STOP_CAP, sq.SOFT_STOP_CAP) == (60, 85)
    # Hard wins (its list, then a hard cross issue, then a gate); else soft; never stacked.
    assert sq._resolve_cap(["a hard stop"], ["a warning"], hard_cross=["x"],
                           extra_hard_reason="gate", extra_soft_reason="gate") == (60, "a hard stop")
    assert sq._resolve_cap([], ["a warning"], hard_cross=["x"], extra_hard_reason="gate") == (60, "x")
    assert sq._resolve_cap([], ["a warning"], extra_hard_reason="gate") == (60, "gate")
    assert sq._resolve_cap([], ["a warning"], extra_soft_reason="gate") == (85, "a warning")
    assert sq._resolve_cap([], [], extra_soft_reason="gate") == (85, "gate")
    assert sq._resolve_cap([], []) == (None, None)
    res = _pkg(hard_stops=["FEIN differs across uploaded documents"], soft_stops=["a warning"])
    assert res["raw_sqs_score"] > 60                       # so the 60 really binds
    assert res["package_sqs_score"] == 60
    assert res["cap_applied"] == 60 and res["cap_reason"] == "FEIN differs across uploaded documents"
    # Its own hard-stop card carries the sentence, so no extra card is drawn - but
    # the cap's row is still there to click.
    assert res["cap_hard_stops"] == [] and res["cap_hard_stop_codes"] == []
    assert [i["message"] for i in res["cap_hard_stop_items"]] == ["FEIN differs across uploaded documents"]
    assert res["score_trace"]["arithmetic"]["ceiling"] == 60


def test_a_warning_holds_85_and_a_hard_stop_holds_60(monkeypatch):
    monkeypatch.setattr(sq, "_weighted_pillar_sum", lambda pillars, weights: 95)
    clean = _pkg()
    assert clean["package_sqs_score"] == 95 and clean["cap_applied"] is None
    warned = _pkg(soft_stops=["a warning"])
    held = _pkg(hard_stops=["FEIN differs across uploaded documents"])
    assert (warned["package_sqs_score"], warned["cap_applied"]) == (85, 85)
    assert (held["package_sqs_score"], held["cap_applied"]) == (60, 60)
    # The real number is kept underneath, for the credits (owner's 2026-08-16 rule).
    assert warned["raw_sqs_score"] == held["raw_sqs_score"] == 95
    # A score already under a cap keeps its own value - a ceiling, never a floor.
    monkeypatch.setattr(sq, "_weighted_pillar_sum", lambda pillars, weights: 41)
    assert _pkg(hard_stops=["FEIN differs across uploaded documents"])["package_sqs_score"] == 41


# ══ 2. Readiness is a status ════════════════════════════════════════════════

@pytest.mark.parametrize("score,blockers,tier,route", [
    (95, 0, "Submission Ready", "auto_quote"),
    (95, 1, "Almost There", "priority_review"),
    (90, 2, "Almost There", "priority_review"),
    (88, 1, "Almost There", "priority_review"),
    (88, 0, "Almost There", "auto_quote"),
    (72, 1, "Needs Work", "priority_review"),
    (40, 1, "Not Ready", "hold"),
])
def test_a_hard_stop_holds_the_tier_and_the_routing(score, blockers, tier, route):
    assert sq.tier_for_score(score, blockers)[1] == tier
    assert sq.tier_for_score(score, blockers)[0] == sq.tier_for_score(score)[0]   # the grade is the number's
    assert sq.routing_for_score(score, blockers) == route


def test_the_package_names_what_blocks_it(monkeypatch):
    monkeypatch.setattr(sq, "_weighted_pillar_sum", lambda pillars, weights: 95)
    res = _pkg(hard_stops=["Umbrella detected but no underlying GL or Auto limits found"],
               soft_stops=["a warning"])
    # The hard stop holds the 60 (20 Oct 2026) ...
    assert res["package_sqs_score"] == 60 and res["raw_sqs_score"] == 95
    assert res["cap_reason"] == "Umbrella detected but no underlying GL or Auto limits found"
    assert res["tier"] == "Major Gaps" and res["routing_decision"] == "standard_review"
    # ... and is named as what blocks Submission Ready (19 Oct 2026).
    assert res["submission_ready"] is False and res["open_hard_stops"] == 1
    assert res["ready_blockers"] == ["Umbrella detected but no underlying GL or Auto limits found"]
    item = res["ready_blocker_items"][0]
    assert item["severity"] == "hard_stop" and item["code"] and item["resolution"]
    # warnings alone never block - they hold 85, so the number is not Ready either
    res = _pkg(soft_stops=["a warning", "another warning"])
    assert res["ready_blockers"] == [] and res["open_hard_stops"] == 0
    assert res["package_sqs_score"] == 85 and res["cap_reason"] == "a warning"
    assert res["tier"] == "Almost There" and res["submission_ready"] is False
    assert res["routing_decision"] == "priority_review"


def test_a_hard_cross_issue_blocks_too(monkeypatch):
    monkeypatch.setattr(sq, "_weighted_pillar_sum", lambda pillars, weights: 96)
    msg = "ACORD 140 selected but no property locations found"
    res = _pkg(cross_issues=[{"type": "hard_stop", "code": "x", "message": msg}])
    assert res["ready_blockers"] == [msg]
    # ...and holds the 60 (20 Oct 2026), named on the package: no hard-stop card carries it.
    assert res["package_sqs_score"] == 60 and res["cap_applied"] == 60 and res["cap_reason"] == msg
    assert res["cap_hard_stops"] == [msg]
    assert res["tier"] == "Major Gaps"


def test_a_credit_moves_the_label_with_the_number():
    sqs = {"raw_sqs_score": 87, "package_sqs_score": 87, "tier": "Almost There",
           "routing_decision": "auto_quote", "open_hard_stops": 0}
    sq.apply_credits_to_score(sqs, 4, None, "package_sqs_score")
    assert sqs["package_sqs_score"] == 91 and sqs["tier"] == "Submission Ready"
    assert sqs["submission_ready"] is True
    blocked = {"raw_sqs_score": 87, "sqs_score": 87, "tier": "Almost There", "grade": "B",
               "tier_color": "yellow", "routing_decision": "auto_quote", "open_hard_stops": 1}
    sq.apply_credits_to_score(blocked, 4, None, "sqs_score")
    assert blocked["tier"] == "Almost There" and blocked["grade"] == "A"
    assert blocked["routing_decision"] == "priority_review" and blocked["submission_ready"] is False
    legacy = {"raw_sqs_score": 87, "package_sqs_score": 87, "tier": "Almost There"}
    sq.apply_credits_to_score(legacy, 4, None, "package_sqs_score")
    assert legacy["tier"] == "Almost There"          # a payload with no count is left alone


def _two_company_session():
    return {
        "facts": dict(_FACTS), "flags": {"has_general_liability": True},
        "docs": [
            {"doc_id": "a", "filename": "a.pdf", "doc_type": "dec_page",
             "facts": {"applicant_name": "Acme Roofing LLC", "fein": "12-3456789"}},
            {"doc_id": "b", "filename": "b.pdf", "doc_type": "dec_page",
             "facts": {"applicant_name": "Zenith Plumbing Inc", "fein": "98-7654321"}},
        ],
        "underwriting_consistency": {"review_required": True, "fields": [
            {"fact_key": "applicant_name", "label": "Applicant / Named Insured", "review_required": True,
             "values": [{"display": "Acme Roofing LLC"}, {"display": "Zenith Plumbing Inc"}]},
            {"fact_key": "fein", "label": "FEIN", "review_required": True,
             "values": [{"display": "12-3456789"}, {"display": "98-7654321"}]}]},
    }


def test_one_conflict_is_one_blocker_and_it_opens_data_consistency():
    """The document check and the Data Consistency picker both state each name /
    FEIN disagreement: four sentences, two problems. The review screen draws the
    picker's row and hides its document twin (issue_registry supersession), so
    the blockers are the two picker rows - coded as the picker's, which is what
    makes the editor offer "Fix in Data Consistency" (the FEIN sentence used to
    classify as the FEIN FORMAT rule and open a box to type a FEIN)."""
    from services.stops_now import stops_now
    session = _two_company_session()
    st = stops_now(session, pre_form=True)
    assert len(st["hard"]) == 4                      # the input really is doubled
    res = _pkg(hard_stops=st["hard"], soft_stops=st["soft"], session_data=session)
    assert res["open_hard_stops"] == 2
    assert [b.split(":")[0] for b in res["ready_blockers"]] == ["Applicant / Named Insured", "FEIN"]
    assert [i["code"] for i in res["ready_blocker_items"]] == [
        "underwriting_reconciliation_applicant_name", "underwriting_reconciliation_fein"]


def test_a_document_conflict_with_no_picker_row_is_still_one_blocker_with_its_own_code():
    from services.stops_now import stops_now
    session = _two_company_session()
    session.pop("underwriting_consistency")
    st = stops_now(session, pre_form=True)
    res = _pkg(hard_stops=st["hard"], soft_stops=st["soft"], session_data=session)
    assert res["open_hard_stops"] == 2
    assert [i["code"] for i in res["ready_blocker_items"]] == [
        "doc_conflict_hard_name_conflict", "doc_conflict_hard_fein_conflict"]


# ══ 3. The short hard-stop list ═════════════════════════════════════════════

def _stops(facts, flags):
    return sq.evaluate_stops(facts, flags)


def test_no_proposed_term_is_hard_and_other_tier1_gaps_are_warnings():
    f = dict(_FACTS)
    f.pop("effective_date")
    f.pop("producer_name")
    hard, soft = _stops(f, {})
    assert any(m.startswith("ACORD 125 minimum field missing: Proposed effective date") for m in hard)
    assert any(m.startswith("ACORD 125 minimum field missing: Producer / Agency name") for m in soft)
    assert not any("Producer / Agency name" in m for m in hard)


def test_the_monopolistic_breakdown_and_split_limits_are_warnings():
    mono = {"has_workers_comp": True, "wc_has_monopolistic_state": True}
    hard, soft = _stops(dict(_FACTS, wc_payroll="500000"), mono)
    assert any("wc_monopolistic_payroll breakdown is missing" in m for m in soft)
    assert not any("wc_monopolistic_payroll" in m for m in hard)
    f2 = dict(_FACTS, auto_bi_per_person="$100,000")
    hard2, soft2 = _stops(f2, {"has_auto_coverage": True, "auto_has_split_limits": True})
    assert any(m.startswith("Split liability limits incomplete") for m in soft2)
    assert not any("Split liability limits incomplete" in m for m in hard2)


def test_a_private_carrier_in_a_monopolistic_state_stays_hard():
    mono = {"has_workers_comp": True, "wc_has_monopolistic_state": True}
    hard, _soft = _stops(dict(_FACTS, wc_payroll="500000",
                              wc_state_fund_acknowledged="No - private carrier"), mono)
    assert any(m.startswith("Monopolistic WC state (ND/OH/WA/WY) requires the state fund") for m in hard)
    hard, _soft = _stops(dict(_FACTS, wc_payroll="500000",
                              wc_state_fund_acknowledged="Yes - placed with the state fund"), mono)
    assert not any("requires the state fund" in m for m in hard)


_TYPED = {"source": "producer", "confidence": "filled"}


def test_an_invalid_period_stays_hard():
    """CHANGED 21 Oct 2026 (Brent's 20 Oct reply: hard only when verified).
    This used bare dates - read from a document - and pinned the 19 Oct
    any-source rule. A term a person typed stays hard; the same dates read from
    documents are a warning to confirm them.

    CHANGED again 21 Oct 2026 (review, M2): a person must supply BOTH dates.
    This typed only the expiration beside a bare (document) effective date -
    now the warning, pinned below."""
    hard, soft = _stops(dict(_FACTS, effective_date={"value": "2026-07-15", **_TYPED},
                             expiration_date={"value": "2026-01-01", **_TYPED}), {})
    assert any("policy period is invalid" in m for m in hard)
    hard, soft = _stops(dict(_FACTS, expiration_date={"value": "2026-01-01", **_TYPED}), {})
    assert not any("policy period is invalid" in m for m in hard)
    hard, soft = _stops(dict(_FACTS, expiration_date="2026-01-01"), {})
    assert not any("policy period is invalid" in m for m in hard)
    assert any(m.startswith("Effective date is on or after expiration date in the dates "
                            "read from your documents") for m in soft)


def test_every_blocker_on_the_short_list_opens_its_fix():
    """Each blocker row carries a fix the review screen can open - a blocker
    with nothing to click would hold Submission Ready with no way out."""
    rows = {}
    for f, fl in (
        ({k: v for k, v in _FACTS.items() if k != "effective_date"}, {}),
        # a person-typed term, both dates (21 Oct 2026: a document-read one, or
        # one retyped date beside it, is a warning)
        (dict(_FACTS, effective_date={"value": "2026-07-15", **_TYPED},
              expiration_date={"value": "2026-01-01", **_TYPED}), {}),
        (dict(_FACTS), {"has_umbrella": True}),
        (dict(_FACTS), {"has_property_coverage": True}),
        (dict(_FACTS, wc_payroll="500000", wc_state_fund_acknowledged="No - private carrier"),
         {"has_workers_comp": True, "wc_has_monopolistic_state": True}),
    ):
        hard, _soft = _stops(f, fl)
        for it in sq._cap_stop_items(hard, facts=f):
            rows[it["message"]] = it
    assert len(rows) >= 5
    for msg, it in rows.items():
        assert (it["resolution"] or {}).get("mode") in ("field", "schedule", "narrative"), msg


def test_the_umbrella_with_no_underlying_stays_hard():
    hard, _soft = _stops(dict(_FACTS), {"has_umbrella": True})
    assert "Umbrella detected but no underlying GL or Auto limits found" in hard


def test_only_a_different_company_blocks_in_data_consistency():
    from services.stops_now import underwriting_conflict_stops
    from services.underwriting_consistency import (
        GENERATION_BLOCKING_RECONCILABLE_KEYS, READY_BLOCKING_RECONCILABLE_KEYS,
    )
    assert READY_BLOCKING_RECONCILABLE_KEYS == {"applicant_name", "fein"}
    assert GENERATION_BLOCKING_RECONCILABLE_KEYS == frozenset()
    uw = {"review_required": True, "fields": [
        {"fact_key": k, "label": k, "review_required": True,
         "values": [{"display": "1"}, {"display": "2"}]}
        for k in ("applicant_name", "fein", "effective_date", "expiration_date",
                  "property_building_value")]}
    blocking = {k: b for k, _m, b in underwriting_conflict_stops(uw, {"has_property_coverage": True})}
    assert blocking == {"applicant_name": True, "fein": True, "effective_date": False,
                        "expiration_date": False, "property_building_value": False}


def test_a_building_value_conflict_no_longer_refuses_generation():
    from routes.form_routes import enforce_building_value_gate
    session = {"facts": {}, "flags": {"has_property_coverage": True},
               "underwriting_consistency": {"fields": [
                   {"fact_key": "property_building_value", "review_required": True}]}}
    enforce_building_value_gate(session)                       # never raises


def test_a_policy_date_difference_is_a_warning():
    docs = [
        {"doc_id": "a", "filename": "a.pdf", "doc_type": "dec_page",
         "facts": {"applicant_name": "Acme LLC", "effective_date": "07/15/2026"}},
        {"doc_id": "b", "filename": "b.pdf", "doc_type": "dec_page",
         "facts": {"applicant_name": "Acme LLC", "effective_date": "08/15/2026"}},
    ]
    issues = sq.check_doc_consistency(docs)
    dated = [i for i in issues if "code=date_conflict" in i]
    assert dated and all(i.startswith("[warning]") for i in dated)


# ══ 4. Exposure = conflicts; Completeness = the missing details ═════════════

def _items(facts, flags, hard_cross=(), warn_cross=()):
    return sq.coverage_deduction_items(facts, flags, list(hard_cross), list(warn_cross))


def test_missing_class_codes_cost_completeness_not_exposure():
    items = sq.completeness_deduction_items(dict(_FACTS), {"has_general_liability": True}, [], [])
    assert sorted((i["fact"], i["points"]) for i in items) == [
        ("gl_class_codes_by_location", 20), ("gl_each_occurrence", 8)]
    res = _pkg()
    parts = {p["key"]: p for p in res["score_trace"]["structural"]}
    assert parts["coverage_details"]["deducted"] == 28
    assert len(parts["coverage_details"]["missing"]) == 2
    # Exposure holds only the conflict: 40 documented employees and no WC (8).
    assert res["pillars"]["exposure_consistency"] == 92
    assert res["category_breakdown"]["structural_completeness"]["coverage_details"]["deducted"] == 28


def test_every_item_is_one_kind_and_lands_in_one_pillar():
    flags = {"has_general_liability": True, "has_workers_comp": True, "has_auto_coverage": True,
             "is_contractor": True, "wc_multi_state": True}
    items = _items(dict(_FACTS, total_payroll="9000000"), flags)
    assert items and all(i["kind"] in ("missing", "conflict") for i in items)
    exp = sq.exposure_deduction_items(dict(_FACTS, total_payroll="9000000"), flags, [], [])
    comp = sq.completeness_deduction_items(dict(_FACTS, total_payroll="9000000"), flags, [], [])
    assert {i["label"] for i in exp} & {i["label"] for i in comp} == set()
    assert any(i["bucket"] == "revenue_sales_information" for i in exp)      # payroll 4.5x revenue
    assert {i["bucket"] for i in comp} >= {"operations_description", "payroll_employee_information",
                                            "coverage_information", "auto_completeness"}
    assert not ({i["bucket"] for i in exp} & {"auto_completeness", "wc_supplemental"})


def test_a_cross_form_conflict_stays_in_exposure():
    conflict = {"type": "soft_warning", "code": "wc_payroll_mismatch", "message": "m"}
    exp = sq.exposure_deduction_items(dict(_FACTS), {}, [], [conflict])
    assert [(i["bucket"], i["points"]) for i in exp if i["bucket"] == "cross_document_consistency"] == \
        [("cross_document_consistency", 5)]
    comp = sq.completeness_deduction_items(dict(_FACTS), {}, [], [conflict])
    assert not any(i["bucket"] in ("cross_document_consistency", "cross_form_details") for i in comp)


def test_documented_employees_with_no_wc_are_a_conflict_not_a_gap():
    exp = sq.exposure_deduction_items(dict(_FACTS), {}, [], [])
    assert [(i["bucket"], i["points"]) for i in exp] == [("payroll_employee_information", 8)]


def test_a_detail_check_a_pillar_already_charges_costs_nothing_more():
    # The EL limit: the Umbrella pillar charges it (25), so the cross-form card
    # asking for it adds nothing - the same missing information never twice.
    twin = {"type": "soft_warning", "code": "umbrella_missing_employers_liability", "message": "m",
            "resolution": {"mode": "field", "facts": ["employers_liability_limits"]}}
    flags = {"has_umbrella": True, "has_workers_comp": True, "has_general_liability": True}
    facts = dict(_FACTS, gl_each_occurrence="$1,000,000")
    charged = sq._facts_other_pillars_charge(facts, flags)
    assert "employers_liability_limits" in charged
    comp = sq.completeness_deduction_items(facts, flags, [], [twin])
    assert not any(i["bucket"] == "cross_form_details" for i in comp)


def test_a_detail_check_no_pillar_charges_costs_five_in_completeness():
    owed = {"type": "soft_warning", "code": "claims_made_missing_retro_date", "message": "m",
            "resolution": {"mode": "field", "facts": ["gl_retroactive_date"]}}
    comp = sq.completeness_deduction_items(dict(_FACTS), {}, [], [owed])
    assert [(i["bucket"], i["points"]) for i in comp if i["bucket"] == "cross_form_details"] == \
        [("cross_form_details", 5)]


def test_the_cross_form_checks_share_one_cap_of_twenty():
    conflicts = [{"type": "soft_warning", "code": "wc_payroll_mismatch", "message": f"c{i}"} for i in range(3)]
    owed = [{"type": "soft_warning", "code": f"x{i}", "message": f"o{i}",
             "resolution": {"mode": "field", "facts": [f"never_charged_{i}"]}} for i in range(4)]
    items = _items(dict(_FACTS), {}, [], conflicts + owed)
    exp = sum(i["points"] for i in items if i["bucket"] == "cross_document_consistency")
    det = sum(i["points"] for i in items if i["bucket"] == "cross_form_details")
    assert (exp, det) == (15, 5) and exp + det == 20


def test_the_conflict_codes_are_real_rule_codes():
    from services.cross_form_validator import rule_codes
    assert sq._CROSS_FORM_CONFLICT_CODES <= set(rule_codes())


def test_structural_rows_still_add_up_when_the_floor_binds():
    f = {k: v for k, v in _FACTS.items() if k in ("applicant_name", "effective_date")}
    flags = {"has_general_liability": True, "has_workers_comp": True, "has_auto_coverage": True}
    res = _pkg(facts=f, flags=flags)
    parts = res["score_trace"]["structural"]
    assert int(sum(p["contribution"] for p in parts)) == res["pillars"]["structural_completeness"]
    cov = next(p for p in parts if p["key"] == "coverage_details")
    assert cov["deducted"] <= int(sum(p["contribution"] for p in parts if p["key"] != "coverage_details"))


def test_the_move_moves_no_package_point_without_a_floor():
    """Both pillars weigh 25%: the missing details in Completeness instead of
    Exposure leave the package number where it was (D6: 20 uncapped stored
    packages, 0 moved)."""
    flags = {"has_general_liability": True, "has_workers_comp": True}
    res = _pkg(flags=flags)
    blend = int(sum(p["contribution"] for p in res["score_trace"]["structural"]
                    if p["key"] != "coverage_details"))
    d_missing = sum(i["points"] for i in sq.completeness_deduction_items(dict(_FACTS), flags, [], []))
    d_conflict = sum(i["points"] for i in sq.exposure_deduction_items(dict(_FACTS), flags, [], []))
    assert blend >= d_missing
    assert res["pillars"]["structural_completeness"] + res["pillars"]["exposure_consistency"] == \
        blend + 100 - d_missing - d_conflict


def test_each_coverage_detail_is_its_own_best_solutions_row():
    res = _pkg(flags={"has_general_liability": True, "has_workers_comp": True})
    rows = [r for r in res["top_recommendations"] if r.get("pillar") == "structural_completeness"]
    assert {"gl_class_codes_by_location", "wc_payroll", "wc_class_codes"} <= {r.get("field") for r in rows}
    gap = (100 - res["pillars"]["structural_completeness"]) * 0.25 / sum(
        w for k, w in sq.SPEC_PILLAR_WEIGHTS.items() if res["pillars"].get(k) is not None)
    assert sum(r["points_available"] for r in rows) == pytest.approx(gap, abs=0.3)


def test_a_stored_hard_date_card_is_kept_as_the_warning_it_now_is():
    """A session uploaded before 19 Oct stores its date card as
    `doc_conflict_hard_date_conflict`. The recalculation's fresh check raises the
    same finding as `doc_conflict_warn_date_conflict`; the card used to be
    dropped and its sentence came back through the safety net with no fix."""
    from services.issue_registry import make_issue, retire_stopped_doc_conflict_issues
    docs = [
        {"doc_id": "a", "filename": "a.pdf", "doc_type": "dec_page",
         "facts": {"applicant_name": "Acme LLC", "effective_date": "07/15/2026"}},
        {"doc_id": "b", "filename": "b.pdf", "doc_type": "dec_page",
         "facts": {"applicant_name": "Acme LLC", "effective_date": "08/15/2026"}},
    ]
    _h, soft, _i, _c = sq.split_doc_consistency_issues(sq.check_doc_consistency(docs))
    old = make_issue("doc_conflict_hard_date_conflict", "hard_stop", soft[0])
    kept = retire_stopped_doc_conflict_issues([old], docs)
    assert [k["code"] for k in kept] == ["doc_conflict_warn_date_conflict"]
    assert kept[0]["severity"] == "soft_warning" and kept[0]["message"] == old["message"]
    assert kept[0]["resolution"]["mode"] == "narrative"
    # A finding the documents no longer raise at all still goes.
    agree = [docs[0], dict(docs[1], facts={"applicant_name": "Acme LLC", "effective_date": "07/15/2026"})]
    assert retire_stopped_doc_conflict_issues([old], agree) == []


# ══ 5. Readiness follows the number everywhere it is shown ═══════════════════

def test_a_blocking_picker_row_stays_hard_on_a_package_with_no_property():
    """`classify_stops` demotes a hard stop on a package with no property line
    unless it is always hard. The picker's own name / FEIN sentence - the only
    picker row that reaches a hard list - used to be demoted, and the proceed
    banner then listed a name conflict as "information typically required for
    property coverage"."""
    from services.stops_now import stops_now
    session = _two_company_session()
    hard = stops_now(session, pre_form=True)["hard"]
    can_proceed, remaining, downgraded = sq.classify_stops(hard, {"has_property_coverage": False})
    assert downgraded == [] and remaining == hard and can_proceed is False


def test_a_credit_refreshes_the_stored_readiness_flag():
    """The dismiss-credit SQL moves the score and tier; the readiness flag the
    dashboard and "Ready to Send Submission" read moves with them (an existing
    key only, so an old payload gains nothing)."""
    import inspect
    from routes import audit_routes
    src = inspect.getsource(audit_routes._apply_dismiss_score_credit)
    assert src.count("'submission_ready']") == 2                  # form + package
    assert "to_jsonb($8::boolean), false" in src and "to_jsonb($6::boolean), false" in src


def test_the_dashboard_derives_readiness_from_the_score_it_shows():
    import inspect
    from repositories import session_repository as repo
    src = inspect.getsource(repo.list_sessions_for_user)
    assert "(data->'package_sqs'->>'open_hard_stops')::int = 0" in src
    assert "(data->'package_sqs'->>'package_sqs_score')::int >= 90" in src


def test_the_screen_reads_readiness_off_the_score_as_shown(tmp_path):
    """A credit patched onto the number on screen (four AcordModal handlers set
    the score and tier only) moves "Ready to Send Submission" with it."""
    import json as _json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    fmt = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "formatters.js"
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as F from {_json.dumps(fmt.as_uri())};\n"
        "console.log(JSON.stringify([\n"
        "  F.submissionReady({package_sqs_score: 92, open_hard_stops: 0, submission_ready: false}),\n"
        "  F.submissionReady({package_sqs_score: 92, open_hard_stops: 1, submission_ready: true}),\n"
        "  F.submissionReady({package_sqs_score: 88, open_hard_stops: 0}),\n"
        "  F.submissionReady({package_sqs_score: 91, submission_ready: false}),\n"
        "  F.submissionReady({package_sqs_score: 91}),\n"
        "  F.submissionReady(null),\n"
        "]));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert _json.loads(run.stdout) == [True, False, False, False, True, False]


# ══ 6. The review of 19 Oct evening - each finding, pinned ══════════════════

def test_a_check_whose_fix_is_a_table_is_charged_once():
    """The WC by-state breakdown IS the class table a coverage item charges (8);
    the cross-form check asking for the same table added 5 more."""
    check = {"type": "soft_warning", "code": "wc_multi_state_no_breakdown", "message": "m",
             "resolution": {"mode": "schedule", "schedule_key": "wc_class_codes"}}
    assert sq._cross_issue_facts(check) == {"wc_class_codes"}
    flags = {"has_workers_comp": True, "wc_multi_state": True}
    f = dict(_FACTS, wc_payroll="500000", wc_class_codes=[{"code": "5190"}])
    comp = sq.completeness_deduction_items(f, flags, [], [check])
    assert [(i["bucket"], i["points"]) for i in comp
            if i["bucket"] in ("payroll_employee_information", "cross_form_details")] == \
        [("payroll_employee_information", 8)]


def test_a_limit_the_umbrella_pillar_charges_is_not_charged_again():
    """GL + umbrella, GL limit missing: the Umbrella pillar charges the
    underlying GL limit (20); Completeness charged the same box again (8)."""
    f = dict(_FACTS, auto_liability_limit="$1,000,000")
    with_umb = {"has_general_liability": True, "has_auto_coverage": True, "has_umbrella": True}
    comp = sq.completeness_deduction_items(f, with_umb, [], [])
    assert "gl_each_occurrence" not in {i["fact"] for i in comp}
    assert "gl_each_occurrence" in {i["fact"] for i in sq.umbrella_gap_items(f, with_umb)}
    # No umbrella: Completeness is the one place it is charged.
    without = {"has_general_liability": True, "has_auto_coverage": True}
    assert ("gl_each_occurrence", 8) in {(i["fact"], i["points"]) for i in
                                         sq.completeness_deduction_items(f, without, [], [])}


def test_the_recommender_is_not_moved_by_the_scoring_rule():
    """`form_service` raises ACORD 101 to Recommended on a hard cross_validate
    issue; the two that became warnings keep that (owner: do not change the
    recommender unless asked)."""
    from services.form_service import match_forms_deterministic
    facts = {k: v for k, v in _FACTS.items() if k != "applicant_name"}
    r101 = next(r for r in match_forms_deterministic(facts, {"has_general_liability": True})
                if r.get("form_id") == "ACORD_101")
    assert r101["tier"] == "recommended"
    named = [i for i in sq.cross_validate(facts, {}, ["ACORD_125"]) if i["message"].startswith("Named insured")]
    assert named and named[0]["type"] == "warning" and named[0]["escalates_acord101"] is True


def test_a_credit_clamps_to_the_cap_the_caller_passes_and_its_own():
    """20 Oct 2026: the caps are back, so the 19 Oct bridge that kept an old
    payload's own stored ceiling (D70) is gone. The caller passes the cap its
    open stops hold - 60 / 85 / none - and the labels follow the credited number.
    The payload's own `cap_applied` binds too: the callers rebuild `cap` from
    the stop lists, which miss a form's own gates, and the first credit used to
    release a gate's 60 / 85 (open since 2026-08-31)."""
    held = {"sqs_score": 60, "raw_sqs_score": 88, "tier": "Major Gaps", "grade": "D",
            "tier_color": "red", "routing_decision": "standard_review", "open_hard_stops": 1,
            "score_trace": {"arithmetic": {"credits": 0, "displayed": 60, "ceiling": 60}}}
    sq.apply_credits_to_score(held, 6, 60, "sqs_score")
    assert held["sqs_score"] == 60 and held["tier"] == "Major Gaps" and held["grade"] == "D"
    assert held["routing_decision"] == "standard_review" and held["submission_ready"] is False
    assert held["score_trace"]["arithmetic"] == {"credits": 6, "displayed": 60, "ceiling": 60}
    warned = {"sqs_score": 85, "raw_sqs_score": 88, "tier": "Almost There", "open_hard_stops": 0}
    sq.apply_credits_to_score(warned, 6, 85, "sqs_score")
    assert warned["sqs_score"] == 85 and warned["tier"] == "Almost There"
    assert warned["submission_ready"] is False
    # Nothing open and no ceiling of its own: the credit lifts the number to 94.
    cleared = {"sqs_score": 88, "raw_sqs_score": 88, "tier": "Almost There", "open_hard_stops": 0,
               "cap_applied": None}
    sq.apply_credits_to_score(cleared, 6, None, "sqs_score")
    assert cleared["sqs_score"] == 94 and cleared["tier"] == "Submission Ready"
    assert cleared["submission_ready"] is True
    # A form held at 85 by its OWN gate (the Period of Restoration on a 140): the
    # lists are empty, so the caller passes no cap - the form's own 85 still holds.
    gated = {"sqs_score": 85, "raw_sqs_score": 93, "tier": "Almost There", "open_hard_stops": 0,
             "cap_applied": 85, "routing_decision": "priority_review",
             "score_trace": {"arithmetic": {"credits": 0, "displayed": 85, "ceiling": 85}}}
    sq.apply_credits_to_score(gated, 6, None, "sqs_score")
    assert gated["sqs_score"] == 85 and gated["tier"] == "Almost There"
    assert gated["submission_ready"] is False and gated["routing_decision"] == "priority_review"
    assert gated["score_trace"]["arithmetic"]["ceiling"] == 85
    # The stricter of the two binds: a caller's 60 under the form's own 85.
    both = {"sqs_score": 60, "raw_sqs_score": 93, "tier": "Major Gaps", "open_hard_stops": 1,
            "cap_applied": 85}
    sq.apply_credits_to_score(both, 6, 60, "sqs_score")
    assert both["sqs_score"] == 60
    # An old payload (no `open_hard_stops`) is clamped the same way; its labels are left alone.
    old = {"sqs_score": 60, "raw_sqs_score": 88, "tier": "Major Gaps", "grade": "D", "cap_applied": 60}
    sq.apply_credits_to_score(old, 6, 60, "sqs_score")
    assert old["sqs_score"] == 60 and old["tier"] == "Major Gaps" and "submission_ready" not in old


def _run_dismiss_credit(monkeypatch, pkg, form, stops=(1, 0, 0, 0)):
    """The dismiss-credit route against a fake connection. `stops` is the
    session's (hard, soft, hard cross, soft cross) counts - the open stops whose
    cap (`_cap_from`, 60 / 85 / 100) the credit is clamped to."""
    import asyncio
    from routes import audit_routes as ar

    class _Conn:
        def __init__(self):
            self.writes = []

        async def fetchrow(self, sql, *a):
            return dict(zip(("hard_total", "soft_total", "hard_cross", "soft_cross"), stops))

        async def fetchval(self, sql, *a):
            for key in ("open_hard_stops", "raw_sqs_score", "package_sqs_score", "cap_applied"):
                if f"'{key}')::int" in sql:
                    return pkg.get(key)
            return {} if "data->'facts'" in sql else None

        async def fetch(self, sql, *a):
            # `stored_cap` = the form's own `cap_applied` (20 Oct 2026).
            return [dict({"stored_cap": None}, **form, form_id="ACORD_140", form_credits=6)]

        async def execute(self, sql, *a):
            self.writes.append((sql, a))

    conn = _Conn()

    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(ar, "get_pool", lambda: type("P", (), {"acquire": lambda self: _Ctx()})())

    async def _credits(session_id, facts=None):
        return 6, [{"rec_id": "r1", "score_impact": 6}]

    monkeypatch.setattr(ar, "active_score_credits", _credits)
    out = asyncio.run(ar._apply_dismiss_score_credit("s", "r1", 60, 6))
    return out, conn.writes


def test_a_dismiss_credit_on_an_old_payload_is_held_by_its_open_hard_stop(monkeypatch):
    """A package scored before 19 Oct (no readiness fields): 60 held by Minimum
    Viable COPE, still a hard stop. The open hard stop's 60 holds the credit
    (`_cap_from`, restored 20 Oct 2026) - it never lifts the package to 94
    "Submission Ready" beside the open stop."""
    # The form scored 60 under a raw 88, so its own scorer held 60 (22 Oct 2026:
    # a scored form's credit ceiling is its own `cap_applied` - the fixture
    # carries what such a payload stores).
    out, writes = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 60, "raw_sqs_score": 88},
        form={"score": 60, "raw_score": 88, "open_hard": None, "stored_cap": 60})
    assert out["new_package_sqs_score"] == 60 and out["new_package_tier"] != "Submission Ready"
    assert out["package_ceiling"] == 60


def _pkg_write(writes):
    return next(a for sql, a in writes if "ARRAY['package_sqs', 'submission_ready']" in sql)


def _form_writes(writes):
    return [a for sql, a in writes if "'sqs', 'submission_ready']" in sql and "generated_forms" in sql]


def test_a_dismiss_credit_on_a_new_payload_moves_number_and_readiness(monkeypatch):
    # Nothing open: the credit lifts 88 to 94 and the stored readiness moves with it.
    out, writes = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 88, "raw_sqs_score": 88, "open_hard_stops": 0},
        form={"score": 88, "raw_score": 88, "open_hard": 0}, stops=(0, 0, 0, 0))
    assert out["new_package_sqs_score"] == 94 and out["new_package_tier"] == "Submission Ready"
    assert _pkg_write(writes)[-1] is True
    [form_write] = _form_writes(writes)
    assert form_write[1] == 94 and form_write[-1] is True
    # A warning open (20 Oct 2026: the caps are back): held at 85, not ready.
    # (The form's own scorer held it at 85 - 22 Oct 2026, its stored ceiling.)
    out, writes = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 85, "raw_sqs_score": 88, "open_hard_stops": 0},
        form={"score": 85, "raw_score": 88, "open_hard": 0, "stored_cap": 85}, stops=(0, 1, 0, 0))
    assert out["new_package_sqs_score"] == 85 and out["package_ceiling"] == 85
    assert out["new_package_tier"] == "Almost There" and _pkg_write(writes)[-1] is False
    assert _form_writes(writes) == []                  # the form's 85 did not move
    # A hard stop open: held at 60, and blocked - not ready.
    out, writes = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 60, "raw_sqs_score": 88, "open_hard_stops": 1},
        form={"score": 60, "raw_score": 88, "open_hard": 1, "stored_cap": 60})
    assert out["new_package_sqs_score"] == 60 and out["package_ceiling"] == 60
    assert out["new_package_tier"] == "Major Gaps" and _pkg_write(writes)[-1] is False
    assert _form_writes(writes) == []


def test_a_dismiss_credit_never_passes_a_payloads_own_ceiling(monkeypatch):
    """20 Oct 2026: the session's stop COUNTS miss the scorer's own items - a
    form's gate (the 140's Period of Restoration, 85) and the package's own
    building-value conflict (85). The stored `cap_applied` binds the credit too:
    a credit that released them printed 94 "Submission Ready" beside the open
    warning."""
    out, writes = _run_dismiss_credit(
        monkeypatch,
        pkg={"package_sqs_score": 85, "raw_sqs_score": 88, "open_hard_stops": 0, "cap_applied": 85},
        form={"score": 85, "raw_score": 93, "open_hard": 0, "stored_cap": 85}, stops=(0, 0, 0, 0))
    assert out["new_package_sqs_score"] == 85 and out["package_ceiling"] == 85
    assert out["new_package_tier"] == "Almost There" and _pkg_write(writes)[-1] is False
    assert _form_writes(writes) == []                  # the form's own 85 held: nothing to write
    # Nothing of its own and nothing open: the credit lands in full.
    out, writes = _run_dismiss_credit(
        monkeypatch,
        pkg={"package_sqs_score": 88, "raw_sqs_score": 88, "open_hard_stops": 0, "cap_applied": None},
        form={"score": 88, "raw_score": 88, "open_hard": 0, "stored_cap": None}, stops=(0, 0, 0, 0))
    assert out["new_package_sqs_score"] == 94


def test_a_stored_card_takes_the_live_cards_type():
    from services import audit_service as au
    rows = [{"rec_id": "rec_period_of_restoration", "action": None, "producer_answer": None,
             "recommendation_type": "hard_stop"},
            {"rec_id": "rec_done", "action": "dismissed", "producer_answer": None,
             "recommendation_type": "hard_stop"},
            {"rec_id": "rec_untyped", "action": None, "producer_answer": None}]
    live = {"rec_period_of_restoration", "rec_done", "rec_untyped"}
    types = au.live_card_types([{"recommendations": [
        {"rec_id": "rec_period_of_restoration", "type": "soft_warning"},
        {"rec_id": "rec_done", "type": "soft_warning"},
        {"rec_id": "rec_untyped", "type": "soft_warning"}]}])
    plan = au.plan_card_sync(rows, live, {}, {}, types)
    assert plan["retype"] == ["rec_period_of_restoration"]       # open only; a typed row only


def test_a_hard_stop_opening_is_a_material_change_through_the_ceiling():
    """20 Oct 2026: the E&O signature is 5.12's five fields again. Under the
    caps a hard stop opening moves the ceiling (and its reason), so it is still
    a material change; the 19 Oct readiness keys added nothing but made every
    signature stored before 19 Oct "changed" on its first recalculation."""
    from services import audit_service as au
    clear = {"raw_sqs_score": 92, "package_sqs_score": 92, "pillars": {}, "cap_applied": None,
             "open_hard_stops": 0, "submission_ready": True}
    blocked = dict(clear, package_sqs_score=60, cap_applied=60, cap_reason="FEIN: documents disagree (...)",
                   open_hard_stops=1, submission_ready=False)
    assert au._snapshots_differ(au._snapshot_signature(clear), au._snapshot_signature(blocked))
    assert set(au._snapshot_signature(blocked)) == {"raw_sqs", "displayed_sqs", "pillars", "ceiling",
                                                     "ceiling_reason"}
    # A signature stored before 19 Oct equals the fresh one when nothing moved.
    stored = au._snapshot_signature({k: v for k, v in blocked.items()
                                     if k not in ("open_hard_stops", "submission_ready")})
    assert not au._snapshots_differ(stored, au._snapshot_signature(blocked))


def test_the_review_rail_colours_the_tier_not_the_number():
    rail = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "form"
            / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    assert "const tierColor = tierIndex >= 0 ? TIER_LADDER[tierIndex].color" in rail
