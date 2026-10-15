"""A warning that holds the score at 85 is cleared by a CORRECT answer in its own fix
window (15 Oct 2026, owner: "if every answer is answered correctly ... and still it is
not reaching 100 ... I don't want that").

Three warnings had no answer that could clear them, so a package carrying one stayed at
85 whatever the producer typed (Dismiss never moves the score before forms):
  * claims-made GL "prior acts confirmation" - the rule reads `prior_acts_confirmation`,
    which could not be typed; its card wrote the remarks, which the rule never reads;
  * a monopolistic WC state (ND / OH / WA / WY) - the warning fired even after the
    state-fund placement was confirmed, and its card was review-only;
  * a low-OCR "confirm this field" warning - the card had no box at all.
"""
from services import sqs_service as S
from services.answer_routing import answer_mode
from services.answer_options import options_for
from services.issue_registry import classify_legacy, resolution_for


def _env(v):
    return {"value": v, "source": "producer", "confidence": "producer"}


# ── claims-made prior acts ────────────────────────────────────────────────────
def test_the_prior_acts_card_asks_the_fact_its_rule_reads():
    res = resolution_for("claims_made_missing_prior_acts")
    assert res["mode"] == "field" and res["facts"] == ["prior_acts_confirmation"]
    assert answer_mode("prior_acts_confirmation")["mode"] == "field"
    assert options_for("prior_acts_confirmation")[0].startswith("Yes")


def test_a_prior_acts_answer_clears_the_warning(monkeypatch):
    from services import cross_form_validator as CFV
    from services import coverage_evidence
    monkeypatch.setattr(coverage_evidence, "gl_is_claims_made", lambda *_a, **_k: True)
    facts = {"retro_date": _env("01/01/2015")}
    codes = [i["code"] for i in CFV._check_claims_made_prior_acts(facts, {}, set())]
    assert "claims_made_missing_prior_acts" in codes
    for answer in options_for("prior_acts_confirmation")[:3]:
        done = dict(facts, prior_acts_confirmation=_env(answer))
        assert not CFV._check_claims_made_prior_acts(done, {}, set()), answer


# ── monopolistic WC state ─────────────────────────────────────────────────────
_WC_FLAGS = {"has_workers_comp": True, "wc_has_monopolistic_state": True}


def _stops(facts):
    hard, soft = S.evaluate_stops(dict({"wc_payroll": _env("$300,000"),
                                        "wc_monopolistic_payroll": _env("$40,000")}, **facts),
                                  dict(_WC_FLAGS))
    mono = lambda xs: [x for x in xs if "Monopolistic WC state" in x]  # noqa: E731
    return mono(hard), mono(soft)


def test_the_state_fund_question_clears_the_warning():
    hard, soft = _stops({})
    assert not hard and soft                                   # asked until answered
    hard, soft = _stops({"wc_state_fund_acknowledged": _env(options_for("wc_state_fund_acknowledged")[0])})
    assert not hard and not soft                               # confirmed: nothing left to warn about


def test_a_private_carrier_answer_is_a_true_stop():
    hard, soft = _stops({"wc_state_fund_acknowledged": _env(options_for("wc_state_fund_acknowledged")[1])})
    assert hard and not soft                                   # those states do not allow it


def test_both_monopolistic_cards_ask_the_placement():
    for msg, sev in (("Monopolistic WC state detected (ND/OH/WA/WY) - must use state fund", "soft_warning"),
                     ("Monopolistic WC state (ND/OH/WA/WY) requires the state fund - private-carrier WC "
                      "cannot be quoted.", "hard_stop")):
        code = classify_legacy(msg, sev)[0]
        res = resolution_for(code)
        assert res and res["mode"] == "field" and res["facts"] == ["wc_state_fund_acknowledged"], (msg, code)
    assert answer_mode("wc_state_fund_acknowledged")["mode"] == "field"


# ── low-OCR confirm this field ────────────────────────────────────────────────
def test_a_low_ocr_card_opens_its_own_field():
    for fact in ("applicant_name", "mailing_address", "fein", "effective_date"):
        res = resolution_for(f"ocr_low_confidence_{fact}")
        assert res and res["mode"] == "field" and res["facts"] == [fact], fact


def test_a_field_no_person_can_type_gets_no_box():
    assert resolution_for("ocr_low_confidence_not_a_real_fact") is None


# ── crime / cyber silent exposure: the producer's decision is the answer ──────
def test_a_coverage_decision_clears_crime_and_cyber():
    from services import cross_form_validator as CFV
    facts = {"operations_description": _env("Retail jewelry store handling cash; online sales platform storing customer data")}
    assert CFV._check_crime_silent_exposure(facts, {}, set())
    assert CFV._check_cyber_silent_exposure(facts, {}, set())
    for fact, rule in (("crime_coverage_decision", CFV._check_crime_silent_exposure),
                       ("cyber_coverage_decision", CFV._check_cyber_silent_exposure)):
        assert answer_mode(fact)["mode"] == "field"
        for answer in options_for(fact)[:4]:
            assert not rule(dict(facts, **{fact: _env(answer)}), {}, set()), answer
    assert resolution_for("crime_silent_exposure")["facts"] == ["crime_coverage_decision"]
    assert resolution_for("cyber_silent_exposure")["facts"] == ["cyber_coverage_decision"]


# ── an explanation answers a card whose only fix is an explanation ────────────
def test_an_explained_card_stops_counting(monkeypatch):
    from services import cross_form_validator as CFV
    issue = {"type": "soft_warning", "code": "builders_risk_property_duplication", "message": "m", "forms": []}
    other = {"type": "soft_warning", "code": "crime_silent_exposure", "message": "c", "forms": []}
    monkeypatch.setattr(CFV, "_RULE_FUNCTIONS", [lambda f, fl, t: [dict(issue), dict(other)]])
    assert {i["code"] for i in CFV.run_cross_form_validation({}, {}, set())} == {issue["code"], other["code"]}
    facts = {"_explained_issue_codes": {"value": [issue["code"], other["code"]], "source": "producer"}}
    left = {i["code"] for i in CFV.run_cross_form_validation(facts, {}, set())}
    # explained: gone; a card whose fix is NOT an explanation is not cleared by one
    assert left == {other["code"]}


def test_every_narrative_card_is_answered_by_its_explanation():
    from services.issue_registry import RESOLUTION_MAP, explains_away
    narrative = [c for c, r in RESOLUTION_MAP.items() if (r or {}).get("mode") == "narrative"]
    assert {"builders_risk_property_duplication", "wc_gl_class_code_mismatch",
            "umbrella_auto_period_misaligned", "umbrella_wc_period_misaligned"} <= set(narrative)
    assert all(explains_away(c) for c in narrative)


# ── a document disagreement a person settled ──────────────────────────────────
def _lob_doc(fname, lines, denied=None):
    facts = {"lines_of_business": {"value": lines}}
    if denied:
        facts["lines_not_carried"] = {"value": denied}
    return {"filename": fname, "doc_type": "declarations_page", "text": "", "facts": facts}


def test_a_typed_value_settles_a_document_warning():
    from services.issue_registry import person_settled_keys
    facts = {"lines_of_business": _env(["General Liability", "Commercial Auto"]),
             "mailing_address": {"value": "1 Main St", "source": "document"}}
    assert person_settled_keys(facts) == {"lines_of_business"}
    for field in ("lines_of_business", "mailing_address", "entity_type"):
        res = resolution_for(f"doc_conflict_warn_{field}")
        assert res and res["mode"] == "field" and res["facts"] == [field], field


def test_a_settled_or_explained_source_conflict_retires():
    from services.issue_registry import retire_settled_source_conflicts
    issues = [{"code": "source_conflict_wc_payroll_by_state.CO", "message": "x"},
              {"code": "source_conflict_risk_transfer.additional_insured_names", "message": "y"},
              {"code": "legacy_contact", "message": "z"}]
    facts = {"wc_payroll_by_state": _env({"CO": "300000"}),
             "_explained_issue_codes": {"value": ["source_conflict_risk_transfer.additional_insured_names"]}}
    assert [i["code"] for i in retire_settled_source_conflicts(issues, facts)] == ["legacy_contact"]
    assert len(retire_settled_source_conflicts(issues, {})) == 3
    # a nested conflict nobody can type is explained in its card (was a dead review note)
    assert resolution_for("source_conflict_risk_transfer.additional_insured_names")["mode"] == "narrative"


def test_a_settled_source_conflict_is_no_stop(monkeypatch):
    from services import stops_now as SN
    monkeypatch.setattr(SN, "source_conflict_stops", lambda docs, uw: [("wc_payroll_by_state.CO", "WC payroll differs", False)])
    session = {"docs": [{"facts": {}}, {"facts": {}}], "facts": {}, "flags": {}}
    soft = SN.stops_now(session, pre_form=True)["soft"]
    assert "WC payroll differs" in soft
    session["facts"] = {"wc_payroll_by_state": _env({"CO": "300000"})}
    soft = SN.stops_now(session, pre_form=True)["soft"]
    assert "WC payroll differs" not in soft


def test_the_real_fix_route_records_the_explained_card():
    import tests.test_reopen_takes_the_fix_back_9oct as H
    s = H._fresh()
    out = s.fix("iss_explain", code="wc_gl_class_code_mismatch", mode="narrative",
                text="The GL class covers the office staff; the WC codes are the field crews - both are correct.")
    assert out.get("success") is True
    from services.issue_registry import explained_issue_codes
    assert "wc_gl_class_code_mismatch" in explained_issue_codes(s.store.get("facts"))


# ── A policy-date difference across documents (15 Oct, live 7ed880d6) ─────────
# Several policies, each with its own term: the warning held 85 with no button.
# Its own message names the fix - explain the difference - and a saved
# explanation stops it counting.
def test_a_policy_date_difference_is_explained_and_then_stops_counting(monkeypatch):
    import services.sqs_service as S
    from services.issue_registry import resolution_for
    for code in ("doc_conflict_warn_date_conflict", "doc_conflict_warn_expiration_conflict",
                 "doc_conflict_hard_date_conflict", "doc_conflict_hard_expiration_conflict"):
        res = resolution_for(code)
        assert res["mode"] == "narrative" and "Explain the difference" in res["note"]
    monkeypatch.setattr(S, "check_doc_consistency", lambda docs, confirmed=None: [
        "[warning] code=date_conflict Policy date mismatch across documents. Each policy carries its own term."])
    docs = [{"facts": {"effective_date": "01/16/2025"}}, {"facts": {"effective_date": "07/15/2025"}}]
    hard, soft = S.doc_consistency_stops({"docs": docs, "facts": {}})
    assert soft and not hard
    explained = {"_explained_issue_codes": {"value": ["doc_conflict_warn_date_conflict"], "source": "producer"}}
    assert S.doc_consistency_stops({"docs": docs, "facts": explained}) == ([], [])
