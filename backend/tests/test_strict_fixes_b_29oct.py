"""Strict review, 29 Oct 2026 (Fixer 2): N/A gaming on facts every business
has, unreadable dates in date boxes, stale Data Consistency assessments, and
the screen-points lock table bound."""
import asyncio

import pytest

from services.answer_semantics import (
    ABSENCE, NOT_APPLICABLE, UNKNOWN, VALUE, answered_for, interpret_answer,
)
from services.fact_registry import ALWAYS_EXISTS, always_exists


# ── 1. N/A is never an answer for a fact every business has ─────────────────

@pytest.mark.parametrize("fact", sorted(ALWAYS_EXISTS))
@pytest.mark.parametrize("typed", ["N/A", "n/a", "Not applicable", "None", "none", "No",
                                   "does not apply", "None at this time"])
def test_absence_refused_on_always_existing_fact(fact, typed):
    got = interpret_answer(fact, typed)
    assert got.intent == UNKNOWN and not got.accepted
    assert got.message.startswith("Every business has ")
    assert "enter it" in got.message


@pytest.mark.parametrize("fact,typed", [
    ("fein", "12-3456789"), ("total_revenue", "$1,200,000"), ("naics_code", "238160"),
    ("sic_code", "1761"), ("years_in_business", "12"), ("years_in_business", "0"),
    ("business_start_date", "03/01/2014"), ("total_revenue", "0"),
])
def test_real_values_still_accepted(fact, typed):
    got = interpret_answer(fact, typed)
    assert got.accepted and got.intent == VALUE, (fact, typed, got)


@pytest.mark.parametrize("fact", ["num_employees", "num_employees_full_time",
                                  "num_employees_part_time"])
def test_employee_counts_keep_none_and_zero(fact):
    assert not always_exists(fact)
    assert interpret_answer(fact, "0").intent == VALUE
    assert interpret_answer(fact, "None").intent in (ABSENCE, NOT_APPLICABLE)


def test_facts_that_can_not_apply_keep_na():
    # Spec 3.6 still applies where the fact can genuinely not apply.
    assert interpret_answer("prior_carrier", "None").accepted
    assert interpret_answer("wc_xmod", "N/A").accepted


def test_a_stored_absence_never_answers_an_always_existing_fact():
    assert not answered_for("fein", {"value": "", "value_state": "not_applicable"})
    assert not answered_for("naics_code", {"value": "", "value_state": "explicit_no"})
    assert not answered_for("total_revenue", "N/A")
    assert answered_for("total_revenue", "0")
    assert answered_for("fein", "12-3456789")
    assert answered_for("num_employees", {"value": "", "value_state": "explicit_no"})


def test_na_fein_no_longer_scores_higher_than_a_real_one():
    from services.sqs_service import check_tier2
    base = {"operations_description": "Commercial roofing contractor", "total_revenue": "1000000",
            "num_employees": "5", "years_in_business": "10", "naics_code": "238160"}
    real, _ = check_tier2({**base, "fein": "12-3456789"}, {})
    na, missing = check_tier2({**base, "fein": {"value": "", "value_state": "not_applicable"}}, {})
    assert real == 100 and na < real and "FEIN / Tax ID" in missing
    # NAICS and SIC both "N/A" are a gap, not out of the denominator.
    both = {**base, "fein": "12-3456789",
            "naics_code": {"value": "", "value_state": "not_applicable"},
            "sic_code": {"value": "", "value_state": "not_applicable"}}
    s, missing = check_tier2(both, {})
    assert s < 100 and any("NAICS" in m for m in missing)


def test_producer_door_refuses_na_fein():
    from routes.audit_routes import _validate_producer_answer
    ok, msg = _validate_producer_answer("fein", "N/A")
    assert not ok and "Every business has" in msg
    ok, _ = _validate_producer_answer("num_employees", "None")
    assert ok


# ── 2. A date box prints a date or nothing ──────────────────────────────────

@pytest.mark.parametrize("value", ["46023", "2027", "13/45/2026", "07/15/2026 - 07/15/2027"])
def test_unreadable_digit_dates_blanked(value):
    from services.pdf_service import display_value_for_box, unreadable_date_in_date_box
    assert unreadable_date_in_date_box("Policy_EffectiveDate_A", value)
    assert display_value_for_box("ACORD_125", "Policy_EffectiveDate_A", value) == ""


@pytest.mark.parametrize("value", ["07/15/2026", "7/1/26", "2026-07-15", "07/2026",
                                   "07152026", "July 15, 2026", "Continuous", "Until cancelled"])
def test_parseable_dates_and_words_kept(value):
    from services.pdf_service import unreadable_date_in_date_box
    assert not unreadable_date_in_date_box("Policy_EffectiveDate_A", value)


def test_only_date_boxes_are_judged():
    from services.pdf_service import is_date_box, unreadable_date_in_date_box
    assert not unreadable_date_in_date_box("Policy_PolicyNumberIdentifier_A", "2027")
    assert not unreadable_date_in_date_box("X_EffectiveDate_A", "2027", {"ft": "/Btn"})
    assert is_date_box("Anything_A", {"ft": "/Tx", "tu": "Enter date: The start"})
    assert not is_date_box("Vehicle_ModelYear_A", {"ft": "/Tx", "tu": "Enter year: the year"})


def test_every_schema_date_box_is_recognised():
    import glob
    import json
    import os
    from services.pdf_service import is_date_box
    here = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    n = 0
    for path in glob.glob(os.path.join(here, "*.json")):
        for field, meta in json.load(open(path)).items():
            if isinstance(meta, dict) and str(meta.get("tu") or "").lower().startswith("enter date:"):
                n += 1
                assert is_date_box(field, meta), field
    assert n >= 200


def test_map_facts_to_form_blanks_unreadable_effective_date():
    import json
    import os
    from services.pdf_service import map_facts_to_form
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas", "ACORD_125_schema.json")
    schema = json.load(open(path))
    assert "Policy_EffectiveDate_A" in schema
    facts = {"applicant_name": "Probe Contracting LLC", "effective_date": "46023",
             "expiration_date": "07/15/2027"}
    mapped, _conf = map_facts_to_form(facts, schema, form_id="ACORD_125", allow_llm=False)
    assert str(mapped.get("Policy_EffectiveDate_A") or "") == ""
    good, _ = map_facts_to_form({**facts, "effective_date": "07/15/2026"}, schema,
                                form_id="ACORD_125", allow_llm=False)
    assert good.get("Policy_EffectiveDate_A") == "07/15/2026"


# ── 3. A stale Data Consistency assessment is re-assessed on read ───────────

def _session(uw):
    doc = {"doc_id": "d1", "filename": "dec.pdf", "doc_type": "declarations",
           "facts": {"applicant_name": "Probe Contracting LLC"}}
    doc2 = {"doc_id": "d2", "filename": "app.pdf", "doc_type": "application",
            "facts": {"applicant_name": "Probe Contracting LLC"}}
    return {"docs": [doc, doc2], "facts": {"applicant_name": "Probe Contracting LLC"},
            "flags": {}, "underwriting_confirmations": {"total_revenue": "1000000"},
            "underwriting_consistency": uw}


def test_assessment_carries_its_version():
    from services.underwriting_consistency import (
        ASSESSMENT_VERSION, assess_underwriting_consistency, assessment_is_stale,
    )
    s = _session({})
    uw = assess_underwriting_consistency(s["docs"], s["facts"], {})
    assert uw["assessment_version"] == ASSESSMENT_VERSION
    assert not assessment_is_stale(uw)
    assert assessment_is_stale({"fields": [], "model_version": "1.1.0"})
    assert not assessment_is_stale({}) and not assessment_is_stale(None)


def test_stale_assessment_recomputed_and_picks_untouched():
    from services.underwriting_consistency import (
        ASSESSMENT_VERSION, apply_refresh_to_session, stale_assessment_refresh,
    )
    s = _session({"fields": [{"fact_key": "ghost", "review_required": True}],
                  "review_required": True, "conflict_count": 1})
    refresh = stale_assessment_refresh(s)
    assert refresh is not None
    uw = refresh["updates"]["underwriting_consistency"]
    assert uw["assessment_version"] == ASSESSMENT_VERSION
    assert not any(f.get("fact_key") == "ghost" for f in uw.get("fields") or [])
    assert "underwriting_confirmations" not in refresh["updates"]
    after = apply_refresh_to_session(s, refresh)
    assert after["underwriting_confirmations"] == {"total_revenue": "1000000"}
    # Current already -> nothing to write.
    assert stale_assessment_refresh(after) is None


def test_refresh_persists_through_the_store(monkeypatch):
    import repositories.session_repository as repo
    from services.underwriting_consistency import ASSESSMENT_VERSION, refresh_stale_assessment
    seen = {}

    async def fake_upd(sid, updates, delete_facts=None):
        seen["sid"], seen["updates"], seen["delete"] = sid, updates, delete_facts
    monkeypatch.setattr(repo, "upd_processing_session", fake_upd)
    s = _session({"fields": [], "model_version": "1.1.0"})
    out = asyncio.run(refresh_stale_assessment("sid-1", s))
    assert seen["sid"] == "sid-1"
    assert out["underwriting_consistency"]["assessment_version"] == ASSESSMENT_VERSION


def test_failed_write_keeps_the_stored_row(monkeypatch):
    import repositories.session_repository as repo
    from services.underwriting_consistency import refresh_stale_assessment

    async def boom(*a, **k):
        raise RuntimeError("archived")
    monkeypatch.setattr(repo, "upd_processing_session", boom)
    s = _session({"fields": []})
    assert asyncio.run(refresh_stale_assessment("sid-2", s)) is s


def test_both_read_doors_call_the_refresh():
    import inspect
    from routes import form_routes
    from services import arq_service
    assert "refresh_stale_assessment" in inspect.getsource(form_routes.get_extraction_result)
    assert "refresh_stale_assessment" in inspect.getsource(arq_service.recalculate_session_scores)


# ── 4. The screen-points lock table is bounded ──────────────────────────────

def test_screen_points_locks_are_pruned_and_busy_ones_kept():
    from routes import form_routes as fr

    async def run():
        fr._SCREEN_POINTS_LOCKS.clear()
        cap = 4 * fr._SCREEN_POINTS_KEEP
        for i in range(cap + 50):
            fr._SCREEN_POINTS_LOCKS[f"s{i}"] = asyncio.Lock()
        busy = fr._SCREEN_POINTS_LOCKS["s1"]
        await busy.acquire()
        # A waiter on a released lock must keep the lock alive (single flight).
        waited = fr._SCREEN_POINTS_LOCKS["s2"]
        await waited.acquire()
        task = asyncio.ensure_future(waited.acquire())
        await asyncio.sleep(0)
        waited.release()           # locked() is False until the waiter runs
        fr._prune_screen_points_locks("s3")
        assert len(fr._SCREEN_POINTS_LOCKS) <= cap
        assert fr._SCREEN_POINTS_LOCKS.get("s1") is busy
        assert fr._SCREEN_POINTS_LOCKS.get("s2") is waited
        assert "s3" in fr._SCREEN_POINTS_LOCKS
        await task
        waited.release()
        busy.release()
        fr._SCREEN_POINTS_LOCKS.clear()
    asyncio.run(run())


def test_small_table_is_left_alone():
    from routes import form_routes as fr
    fr._SCREEN_POINTS_LOCKS.clear()
    fr._SCREEN_POINTS_LOCKS.update({"a": asyncio.Lock(), "b": asyncio.Lock()})
    fr._prune_screen_points_locks("a")
    assert set(fr._SCREEN_POINTS_LOCKS) == {"a", "b"}
    fr._SCREEN_POINTS_LOCKS.clear()


def test_a_derived_new_venture_na_still_leaves_the_denominator():
    from services.answer_semantics import typed_absence_on_always_existing
    env = {"value": "", "source": "derived", "value_state": "not_applicable"}
    assert not typed_absence_on_always_existing("years_in_business", env)
    assert typed_absence_on_always_existing(
        "years_in_business", {"value": "", "source": "producer", "value_state": "not_applicable"})


def test_client_na_on_fein_is_dropped_not_blocking():
    from services.arq_service import _clean_answer_ex
    assert _clean_answer_ex("N/A", "fein") == (None, "")
    assert _clean_answer_ex("None", "num_employees")[1] == ""
