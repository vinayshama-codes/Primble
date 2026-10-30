"""The safety net (owner, 27 Oct 2026): a deduction or warning hold that no item on
the pre-form page can answer is never charged, is recorded on the package's
`not_scored`, and reaches the underwriter's cover. The first line of defence -
every rule carries an answer - is the reach-100 solver; this is the backstop."""
import logging

from services import sqs_service as S


def _env(v):
    return {"value": v, "source": "ai", "confidence": "ai_high"}


def test_an_item_naming_no_answerable_box_is_not_charged(monkeypatch):
    sink = []
    tok = S._NOT_SCORED.set(sink)
    try:
        items = [
            {"bucket": "coverage_information", "points": 8, "fact": "gl_each_occurrence", "label": "GL limit"},
            {"bucket": "coverage_information", "points": 7, "fact": None, "label": "A gap with no box"},
            {"bucket": "coverage_information", "points": 5, "fact": "no_such_fact_anywhere", "label": "Phantom"},
            {"bucket": "cross_form_details", "points": 5, "fact": None, "label": "Cross-form cards"},
        ]
        kept = S.charge_only_answerable(items, "coverage")
    finally:
        S._NOT_SCORED.reset(tok)
    assert [i["label"] for i in kept] == ["GL limit", "Cross-form cards"]
    assert {e["label"] for e in sink} == {"A gap with no box", "Phantom"}
    assert {e["points"] for e in sink} == {7, 5}


def test_every_real_deduction_today_names_an_answerable_box():
    """The backstop must be idle on ordinary packages: the coverage, umbrella
    and property items a typical gap-filled package raises all stay charged."""
    facts = {"num_employees": _env("41"), "total_revenue": _env("1000000")}
    flags = {"has_general_liability": True, "has_auto_coverage": True, "has_umbrella": True,
             "has_property_coverage": True, "has_workers_comp": True}
    sink = []
    tok = S._NOT_SCORED.set(sink)
    try:
        S.coverage_deduction_items(facts, flags, [], [])
        S.umbrella_deduction_items(facts, flags)
        S.property_gap_items(facts, flags)
    finally:
        S._NOT_SCORED.reset(tok)
    assert sink == []


def test_a_warning_whose_card_offers_no_answer_does_not_hold_85(monkeypatch):
    from services import issue_registry as IR
    monkeypatch.setitem(IR.RESOLUTION_MAP, "zz_unanswerable_test", {"mode": "none"})
    cross = [{"type": "soft_warning", "code": "zz_unanswerable_test", "message": "Nothing to do here."},
             {"type": "soft_warning", "code": "property_coinsurance_missing", "message": "Coinsurance missing."}]
    sink = []
    tok = S._NOT_SCORED.set(sink)
    try:
        kept = S.release_unanswerable_holds(["Nothing to do here.", "Coinsurance missing.",
                                             "A sentence no rule names."], cross)
    finally:
        S._NOT_SCORED.reset(tok)
    assert kept == ["Coinsurance missing.", "A sentence no rule names."]   # unknown keeps holding
    assert [e["rule"] for e in sink] == ["zz_unanswerable_test"]


def test_a_form_choice_is_never_released_here():
    cross = [{"type": "advisory", "code": "contractor_missing_acord186", "form_choice": True,
              "message": "Add ACORD 186."}]
    assert S.release_unanswerable_holds(["Add ACORD 186."], cross) == ["Add ACORD 186."]


def test_the_package_score_carries_not_scored_and_the_log_names_it(monkeypatch, caplog):
    orig = S.charge_only_answerable

    def with_a_gap(items, pillar):
        if pillar == "coverage":
            items = list(items) + [{"bucket": "coverage_information", "points": 8, "fact": None,
                                    "label": "Injected gap"}]
        return orig(items, pillar)

    monkeypatch.setattr(S, "charge_only_answerable", with_a_gap)
    facts = {"applicant_name": _env("Probe Contracting")}
    with caplog.at_level(logging.WARNING):
        pkg = S._PACKAGE_SCORER(facts=facts, flags={"has_general_liability": True}, form_results=[],
                                cross_issues=[], hard_stops=[], soft_stops=[], session_data={},
                                _probe=True, form_fill=False)
    assert any(e["label"] == "Injected gap" for e in pkg["not_scored"])
    assert "SQS_NOT_SCORED" in caplog.text


def test_the_cover_lists_what_was_not_scored():
    from routes.download_routes import _split_open_recs
    pkg = {"not_scored": [{"label": "Rule X gap", "points": 7}], "ready_blocker_items": []}
    _hard, soft = _split_open_recs([], package_sqs=pkg)
    assert "Not scored - could not be asked on screen: Rule X gap" in soft
