"""The caps restored on 20 Oct 2026 (owner, D72) - the review's findings, pinned.

The owner reversed 19 Oct's "no cap" and kept Brent's short hard-stop list: an
open hard stop holds the score at 60 and an open warning at 85. A read-only
review of the restoration found where that did not yet hold:

1. a building value the documents disagree on held NO cap after forms - the
   post-form recalculation and the field edit never carry its Data Consistency
   row, and the scorer's own item had become a warning that reached nothing.
   The same for the two Lite checks that were hard stops before 19 Oct;
2. a credit released a form's own gate cap, and since 19 Oct the released
   number read "Submission Ready" beside the open warning;
3. a missing proposed effective date - a hard stop since D71 - kept a
   "missing_field" card, so the cover listed it under warnings;
4. the screen's cap share, restored with the caps, had no backend test.
"""
from datetime import datetime, timedelta

import services.sqs_service as sq


def _d(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")


_FACTS = {
    "applicant_name": "Acme LLC", "mailing_address": "1 Main St, Denver CO 80202",
    "effective_date": _d(30), "expiration_date": _d(395),
    "lines_of_business": ["General Liability"], "entity_type": "LLC", "contact_name": "Jo",
    "producer_name": "Broker Inc", "fein": "12-3456789", "num_employees": "40",
    "years_in_business": "12", "operations_description": "Residential roofing contractor with 12 crews",
    "total_revenue": "2000000", "naics_code": "238160",
}
_BV_ROW = {"fact_key": "property_building_value", "review_required": True, "label": "Building Value",
           "values": [{"display": "$900,000"}, {"display": "$1,250,000"}]}


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


# ── 1. The reclassified items hold their 85 on every path ────────────────────

def test_a_building_value_conflict_holds_85_with_no_list_carrying_it():
    """The post-form recalculation's and the field edit's lists never carry the
    Data Consistency row. At HEAD the scorer's own item was a hard cross issue
    and held 60 whatever the lists said; it is a warning now and holds 85 the
    same way - never no cap at all (the review measured 90 "Submission Ready")."""
    flags = {"has_general_liability": True, "has_property_coverage": True}
    session = {"underwriting_consistency": {"review_required": True, "fields": [dict(_BV_ROW)]}}
    p = _pkg(flags=flags, session_data=session)
    assert p["cap_applied"] == 85 and p["cap_reason"] == sq.BUILDING_VALUE_CONFLICT_MSG
    assert p["package_sqs_score"] == min(p["raw_sqs_score"], 85)
    assert p["ready_blockers"] == [] and p["submission_ready"] is False   # a warning, not a blocker
    assert p["cap_hard_stops"] == [] and p["cap_hard_stop_codes"] == []
    # With the row listed (the stops door), the listed sentence names the 85.
    row = "Building Value: documents disagree ($900,000, $1,250,000). Fix: Confirm the correct value."
    p2 = _pkg(flags=flags, session_data=session, soft_stops=[row])
    assert p2["cap_applied"] == 85 and p2["cap_reason"] == row
    # Relevance is a precondition (C75): no property coverage, no cap from it.
    p3 = _pkg(session_data=session)
    assert p3["cap_applied"] is None
    # A hard stop still wins.
    p4 = _pkg(flags=flags, session_data=session, hard_stops=["FEIN: documents disagree (a, b)."])
    assert p4["cap_applied"] == 60


def test_a_lite_check_that_was_a_hard_stop_holds_85_and_an_ordinary_cross_warning_keeps_heads_rule():
    """The two Lite checks that were hard stops before 19 Oct carry
    `escalates_acord101`; at HEAD they held 60 through `hard_cross` on every
    route (clarity included), now 85. An ordinary cross-form warning keeps
    HEAD's rule: it holds the 85 through the soft list the stops door builds."""
    lite = {"type": "warning", "message": "Umbrella selected but GL limits missing",
            "escalates_acord101": True}
    p = _pkg(cross_issues=[lite])
    assert p["cap_applied"] == 85 and p["cap_reason"] == lite["message"]
    named = [i for i in sq.cross_validate({}, {}, ["ACORD_125"])
             if i["message"].startswith("Named insured")]
    assert named and named[0]["escalates_acord101"] is True
    assert _pkg(cross_issues=named)["cap_applied"] == 85
    plain = {"type": "soft_warning", "code": "location_count_mismatch",
             "message": "Location count differs between the forms"}
    assert _pkg(cross_issues=[plain])["cap_applied"] is None
    assert _pkg(cross_issues=[plain], soft_stops=[plain["message"]])["cap_applied"] == 85


# ── 2. A credit never passes the payload's own ceiling ───────────────────────

def test_a_credit_never_releases_a_forms_own_gate():
    """ACORD 140 with a Business Income limit and no Period of Restoration: its
    own soft gate holds 85 while the lists are empty, so every credit caller
    rebuilt cap=None. The credit released it to 99 "Submission Ready"."""
    facts = dict(_FACTS, locations=[{"address": "1 Main St"}], occupancy_type="Office",
                 construction_type="Frame", property_building_value="$500,000",
                 business_income_limit="$100,000")
    r = sq.calculate_sqs(facts, {"has_property_coverage": True}, {}, {}, ["ACORD_140"],
                         [], [], 0, form_id="ACORD_140")
    assert r["cap_applied"] == 85 and r["cap_soft_stops"]
    raw = r["raw_sqs_score"]
    sq.apply_credits_to_score(r, 40, None, "sqs_score")
    assert r["sqs_score"] == min(raw + 40, 100, 85)
    assert r["tier"] != "Submission Ready" and r["submission_ready"] is False
    assert r["routing_decision"] != "auto_quote"


# ── 3. The hard stop's card says it is one ───────────────────────────────────

def test_a_missing_proposed_effective_date_card_is_a_hard_stop():
    facts = {k: v for k, v in _FACTS.items() if k != "effective_date"}
    r = sq.calculate_sqs(facts, {}, {}, {}, ["ACORD_125"], [], [], 0, form_id="ACORD_125")
    recs = {x["rec_id"]: x for x in r["recommendations"]}
    assert recs["rec_effective_date"]["type"] == "hard_stop"
    # Every other ACORD 125 gap keeps its missing-field card.
    facts2 = dict(facts, effective_date=_d(30))
    facts2.pop("fein")
    r2 = sq.calculate_sqs(facts2, {}, {}, {}, ["ACORD_125"], [], [], 0, form_id="ACORD_125")
    others = [x for x in r2["recommendations"] if str(x.get("message", "")).startswith("ACORD 125 missing:")]
    assert others and all(x["type"] == "missing_field" for x in others)
    # The cover files it under CRITICAL - Hard Stops, not under warnings.
    from routes.download_routes import _split_open_recs
    row = dict(recs["rec_effective_date"], recommendation_type=recs["rec_effective_date"]["type"])
    hard, soft = _split_open_recs([row])
    assert hard and not soft


# ── 4. The screen's cap share (restored with the caps) ───────────────────────

def _screen(facts, flags):
    row = {"facts": dict(facts), "flags": dict(flags), "docs": [], "recommendations": []}
    pkg = sq.current_package_sqs(row, "t-screen", "u")
    kd = sq.key_details(row["facts"], row["flags"])
    return pkg, sq.complete_screen_shares(row, "t-screen", "u", pkg, kd)


def _shown(pkg2) -> int:
    return (sum(int(v[0]) for v in (pkg2.get("screen_shares") or {}).values())
            + sum(int(v[0]) for v in (pkg2.get("screen_card_points") or {}).values())
            + sum(int(v[0]) for v in (pkg2.get("screen_dc_points") or {}).values())
            + sum(int(u["points"]) for u in (pkg2.get("screen_unanswerable") or [])))


def test_the_screen_shares_the_cap_a_hard_stop_holds_and_adds_up_to_100():
    """No proposed term (a hard stop, D71) on an otherwise strong package: the
    score sits at 60 with raw above it. The stop's card carries its share of the
    cap - the average of what clearing it adds first and last (15 Oct, Shapley)
    - and every number on the screen adds up to exactly 100 minus the score."""
    facts = {k: v for k, v in _FACTS.items() if k != "effective_date"}
    pkg, (pkg2, _kd2) = _screen(facts, {"has_general_liability": True})
    now, raw, cap = pkg["package_sqs_score"], pkg["raw_sqs_score"], pkg["cap_applied"]
    assert cap == 60 and raw > now == 60
    target = 100 - now
    assert pkg2["screen_total"] == target
    assert _shown(pkg2) == target
    # Build 26 page-wide plan (TEST updated - it pinned the 15 Oct Shapley
    # average): numbers are sequential in page order. The proposed term is an
    # Overview key detail, so the first place carries what clearing the stop adds
    # there (at least the cap's release) and its hard-stop card mirrors it.
    first = int((pkg2["screen_shares"].get("effective_date") or [0])[0])
    assert first >= raw - now and first > 0


def test_the_screen_adds_up_with_no_cap_too():
    pkg, (pkg2, _kd2) = _screen(dict(_FACTS), {"has_general_liability": True})
    if pkg["cap_applied"] is None and pkg["package_sqs_score"] < 100:
        assert _shown(pkg2) == 100 - pkg["package_sqs_score"]
