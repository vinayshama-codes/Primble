"""Build 24 - three small changes (22 Oct 2026).

1. ACORD 126 prints a typed five-digit GL class code a WC table repeats - the
   score's own rule (`pdf_service._gl_row_is_another_lines`); a four-digit WC
   class filed under GL still never prints as GL.
2. The client questionnaire submit and the PDF editor save refuse a save that
   leaves the proposed term backwards or already ended (the one door
   `validators.term_save_refusal`).
3. The lite generation paths store the one stops door's cross-form list as
   `cross_issues_last`, never the legacy `cross_validate` list.
"""
import ast
import asyncio
import copy
import json
import os
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import routes.arq_routes as ar
import routes.form_routes as fr
import services.pdf_service as ps
from services.sqs_service import gl_class_codes
from utils.validators import TERM_BACKWARDS_REFUSAL, TERM_ENDED_REFUSAL

HERE = os.path.dirname(os.path.abspath(__file__))
HZ = "GeneralLiability_Hazard_ClassCode_"


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _box(form_id, field, facts):
    with ps._schema_context(_schema(form_id)):
        return ps._deterministic_map(field, {**facts, "_form_id": form_id})


def _d(days):
    return (date.today() + timedelta(days=days)).strftime("%m/%d/%Y")


# ── 1. the typed GL code ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [{"value": "91340", "source": "producer"},
                                   [{"location": "1", "codes": ["91340"]}]])
def test_a_typed_five_digit_gl_code_a_wc_table_repeats_prints_on_the_126(value):
    f = {"gl_class_codes_by_location": value, "has_general_liability": True,
         "wc_class_codes": [{"code": "91340", "description": "Carpentry", "payroll": "$1,240,000"}]}
    assert _box("ACORD_126", HZ + "A", f) == "91340"
    assert gl_class_codes(f) == ["91340"]          # the score counts the same code


def test_a_four_digit_wc_class_filed_under_gl_still_never_prints():
    wc = [{"class_code": c, "classification": "State Act - " + n, "premium_basis": "Payroll",
           "exposure_amount": "$100,000"} for c, n in (("5190", "Electrical"), ("8810", "Clerical"))]
    f = {"gl_class_code_schedule": copy.deepcopy(wc), "wc_class_codes": copy.deepcopy(wc),
         "has_general_liability": True}
    assert [_box("ACORD_126", HZ + L, f) for L in "AB"] == [
        _box("ACORD_126", HZ + L, {"has_general_liability": True}) for L in "AB"]
    assert "5190" not in gl_class_codes(f) and "8810" not in gl_class_codes(f)
    # A four-digit code typed into the answer is never a GL code either.
    f2 = {"gl_class_codes_by_location": {"value": "5190", "source": "producer"},
          "wc_class_codes": [{"code": "5190", "description": "Electrical"}], "has_general_liability": True}
    assert ps._gl_code_only_rows(f2) == []


# ── 2a. the client questionnaire ──────────────────────────────────────────────

_QS = [{"field_name": "effective_date", "question": "Start?"},
       {"field_name": "expiration_date", "question": "End?"},
       {"field_name": "applicant_name", "question": "Name?"}]


def _refusal(answers, stored=None):
    arq = {"questions": _QS, "session_id": "s1"}
    with patch.object(ar, "get_processing_session", AsyncMock(return_value={"facts": stored or {}})):
        return asyncio.run(ar._client_term_refusal(arq, answers))


def test_client_ended_term_is_refused_on_each_date_question():
    out = _refusal({"effective_date": _d(-400), "expiration_date": _d(-35)})
    assert out == {"effective_date": TERM_ENDED_REFUSAL, "expiration_date": TERM_ENDED_REFUSAL}


def test_client_backwards_term_is_refused():
    assert _refusal({"effective_date": _d(60), "expiration_date": _d(30)}) == {
        "effective_date": TERM_BACKWARDS_REFUSAL, "expiration_date": TERM_BACKWARDS_REFUSAL}


def test_client_one_date_is_judged_against_the_stored_one():
    stored = {"effective_date": {"value": _d(30), "source": "ai"},
              "expiration_date": {"value": _d(395), "source": "ai"}}
    assert _refusal({"expiration_date": _d(10)}, stored) == {"expiration_date": TERM_BACKWARDS_REFUSAL}


@pytest.mark.parametrize("answers", [
    {"effective_date": _d(-30), "expiration_date": _d(335)},     # under way
    {"effective_date": _d(-365), "expiration_date": _d(0)},      # ends today
    {"effective_date": _d(20), "expiration_date": _d(385)},      # upcoming
    {"applicant_name": "Choice Electric LLC"},                   # no date given
    {"effective_date": "I'm not sure", "expiration_date": ""},
])
def test_client_good_terms_and_saves_without_dates_pass(answers):
    assert _refusal(answers) == {}


def test_client_submit_returns_422_field_errors_and_writes_nothing():
    req = SimpleNamespace(client=SimpleNamespace(host="1.1.1.1"),
                          json=AsyncMock(return_value={"answers": {
                              "effective_date": _d(-400), "expiration_date": _d(-35)}}))
    arq = {"id": "a1", "session_id": "s1", "status": "sent", "questions": _QS}
    submit = AsyncMock()
    with patch.object(ar, "check_arq_submit_rate_limit", AsyncMock()), \
         patch.object(ar, "get_arq_by_token", AsyncMock(return_value=arq)), \
         patch.object(ar, "get_processing_session", AsyncMock(return_value={"facts": {}})), \
         patch.object(ar, "submit_arq_answers", submit):
        res = asyncio.run(ar.submit_arq("tok123", req))
    body = json.loads(res.body)
    assert res.status_code == 422 and body["field_errors"]["effective_date"] == TERM_ENDED_REFUSAL
    submit.assert_not_called()


# ── 2b. the PDF editor save ───────────────────────────────────────────────────

_FORM = {"field_state": {"Policy_EffectiveDate_A": "01/01/2020", "Policy_ExpirationDate_A": "01/01/2021"}}


def test_editor_save_of_an_ended_term_is_refused():
    upd = {"Policy_EffectiveDate_A": _d(-400), "Policy_ExpirationDate_A": _d(-35)}
    assert fr.editor_term_refusal("ACORD_125", _FORM, upd, {}) == TERM_ENDED_REFUSAL


def test_editor_save_of_a_backwards_term_is_refused():
    upd = {"Policy_EffectiveDate_A": _d(60), "Policy_ExpirationDate_A": _d(30)}
    assert fr.editor_term_refusal("ACORD_125", _FORM, upd, {}) == TERM_BACKWARDS_REFUSAL


@pytest.mark.parametrize("upd", [
    {"Policy_EffectiveDate_A": _d(-30), "Policy_ExpirationDate_A": _d(335)},
    {"Policy_EffectiveDate_A": _d(-365), "Policy_ExpirationDate_A": _d(0)},
    {"NamedInsured_FullName_A": "Choice Electric LLC"},
    # an unchanged box is not part of the save, even an ended one
    {"Policy_EffectiveDate_A": "01/01/2020", "Policy_ExpirationDate_A": "01/01/2021"},
])
def test_editor_good_saves_pass(upd):
    assert fr.editor_term_refusal("ACORD_125", _FORM, upd, {}) == ""


def test_a_certificate_policy_row_ended_date_saves_but_a_125_proposed_one_is_refused():
    ended = {"Policy_GeneralLiability_EffectiveDate_A": _d(-400),
             "Policy_GeneralLiability_ExpirationDate_A": _d(-35)}
    assert fr.editor_term_refusal("ACORD_25", {"field_state": {}}, ended, {}) == ""
    assert fr.editor_term_refusal("ACORD_28", {"field_state": {}},
                                  {"Policy_EffectiveDate_A": _d(-400), "Policy_ExpirationDate_A": _d(-35)}, {}) == ""
    assert fr.editor_term_refusal(
        "ACORD_125", {"field_state": {}},
        {"Policy_EffectiveDate_A": _d(-400), "Policy_ExpirationDate_A": _d(-35)}, {}) == TERM_ENDED_REFUSAL


# ── 2c. one rule for "this box states the proposed term" (review, 22 Oct) ────

@pytest.mark.parametrize("form_id,field,expected", [
    ("ACORD_125", "Policy_EffectiveDate_A", "effective_date"),
    ("ACORD_125", "Policy_ExpirationDate_A", "expiration_date"),
    ("ACORD_131", "Policy_EffectiveDate_A", "effective_date"),
    ("ACORD_131__excess", "Policy_EffectiveDate_A", "effective_date"),
    ("ACORD_131", "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A", None),
    ("ACORD_131", "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_B", None),
    ("ACORD_25", "Policy_GeneralLiability_EffectiveDate_A", None),
    ("ACORD_25", "OtherPolicy_PolicyExpirationDate_A", None),
    ("ACORD_28", "Policy_EffectiveDate_A", None),
    ("ACORD_125", "NamedInsured_FullName_A", None),
])
def test_proposed_term_fact(form_id, field, expected):
    assert ps.proposed_term_fact(form_id, field) == expected


_UNDERLYING = {"UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A": _d(-400),
               "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A": _d(-35)}


def test_editor_a_131_underlying_policys_ended_dates_save():
    assert fr.editor_term_refusal("ACORD_131", {"field_state": {}}, _UNDERLYING, {}) == ""


def _save(form_id, field_updates, facts):
    schema = _schema(form_id)
    mapped, conf = ps.map_facts_to_form(dict(facts), schema, form_id, "", allow_llm=False)
    session = {"user_id": "u1", "active_form_id": form_id, "selected_form_ids": [form_id],
               "facts": copy.deepcopy(facts), "flags": {},
               "generated_forms": {form_id: {"form_id": form_id, "form_name": form_id, "schema": schema,
                                             "form": {"template_file": "none.pdf"}, "field_state": mapped,
                                             "mapped": dict(mapped), "confidence": conf, "sqs": {}}}}
    upd = AsyncMock()
    with patch.object(fr, "get_processing_session", AsyncMock(return_value=session)), \
         patch.object(fr, "check_payment_access", lambda *a, **k: None), \
         patch.object(fr, "try_acquire_heavy", AsyncMock(return_value="t")), \
         patch.object(fr, "release_heavy", AsyncMock()), \
         patch.object(fr, "safe_join", lambda *a: "/nonexistent/none.pdf"), \
         patch.object(fr, "log_field_change", AsyncMock()), \
         patch.object(fr, "upd_processing_session", upd), \
         patch.object(fr, "sync_recommendation_cards", AsyncMock()), \
         patch.object(fr, "run_and_log_field_qa", AsyncMock()), \
         patch.object(fr, "run_and_log_field_mapping_check", AsyncMock()), \
         patch("services.arq_service.recalculate_session_scores", AsyncMock()):
        res = asyncio.run(fr.update_pdf(
            SimpleNamespace(session_id="s1", field_updates={"__form_id__": form_id, **field_updates}),
            {"id": "u1"}))
    stored = next(c.args[1] for c in upd.call_args_list if "generated_forms" in c.args[1])
    return res, stored


_TERM = {"applicant_name": "Choice Electric LLC",
         "effective_date": {"value": _d(20), "source": "producer"},
         "expiration_date": {"value": _d(385), "source": "producer"}}


@pytest.mark.parametrize("dates", [_UNDERLYING, {   # ended, and in force (not refused either way)
    "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A": _d(-30),
    "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A": _d(335)}])
def test_a_131_underlying_policys_dates_save_and_leave_the_proposed_term(dates):
    res, stored = _save("ACORD_131", dates, _TERM)
    assert res.status_code == 200
    box = "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A"
    assert stored["generated_forms"]["ACORD_131"]["field_state"][box] == dates[box]
    for key in ("effective_date", "expiration_date"):
        assert stored["facts"][key]["value"] == _TERM[key]["value"]


def test_a_125_proposed_date_still_writes_the_proposed_term():
    res, stored = _save("ACORD_125", {"Policy_EffectiveDate_A": _d(30)}, _TERM)
    assert res.status_code == 200
    assert stored["facts"]["effective_date"]["value"] == _d(30)


def test_client_an_underlying_or_certificate_date_question_is_not_the_proposed_term():
    qs = [{"field_name": "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A", "form_ids": ["ACORD_131"]},
          {"field_name": "Policy_GeneralLiability_ExpirationDate_A", "form_ids": ["ACORD_25"]},
          {"field_name": "Policy_ExpirationDate_A", "form_ids": ["ACORD_125"]}]
    ans = {"UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A": _d(-400),
           "Policy_GeneralLiability_ExpirationDate_A": _d(-35)}
    assert ar.client_term_dates(qs, ans) == {}
    ans["Policy_ExpirationDate_A"] = _d(-35)
    assert ar.client_term_dates(qs, ans) == {"Policy_ExpirationDate_A": ("expiration_date", _d(-35))}


def test_update_pdf_answers_400_with_the_sentence_before_any_work():
    session = {"user_id": "u1", "generated_forms": {"ACORD_125": copy.deepcopy(_FORM)},
               "active_form_id": "ACORD_125", "facts": {}}
    req = SimpleNamespace(session_id="s1", field_updates={
        "__form_id__": "ACORD_125", "Policy_EffectiveDate_A": _d(-400), "Policy_ExpirationDate_A": _d(-35)})
    heavy = AsyncMock()
    with patch.object(fr, "get_processing_session", AsyncMock(return_value=session)), \
         patch.object(fr, "check_payment_access", lambda *a, **k: None), \
         patch.object(fr, "try_acquire_heavy", heavy):
        with pytest.raises(HTTPException) as ex:
            asyncio.run(fr.update_pdf(req, {"id": "u1"}))
    assert ex.value.status_code == 400 and ex.value.detail == TERM_ENDED_REFUSAL
    heavy.assert_not_called()


# ── 3. the lite paths ─────────────────────────────────────────────────────────

def _calls_in(func_name):
    tree = ast.parse(open(fr.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name)
    return {getattr(c.func, "id", getattr(c.func, "attr", None)) for c in ast.walk(fn) if isinstance(c, ast.Call)}


@pytest.mark.parametrize("func_name", ["_bg_lite_generate", "lite_generate_internal"])
def test_lite_paths_store_the_stops_doors_cross_issues(func_name):
    calls = _calls_in(func_name)
    assert "cross_validate" not in calls
    assert "stops_now" in calls


@pytest.mark.parametrize("sync", [False, True])
def test_a_failing_stops_door_keeps_the_lite_forms(sync):
    session = {"user_id": "u1", "recommendations": [{"form_id": "ACORD_125"}], "all_forms": [],
               "facts": {}, "flags": {}}
    upd = AsyncMock()
    with patch.object(fr, "get_processing_session", AsyncMock(return_value=session)), \
         patch.object(fr, "check_payment_access", lambda *a, **k: None), \
         patch.object(fr, "_lite_shared_gap_fill", AsyncMock(return_value={})), \
         patch.object(fr._fi, "form_meta_for", lambda *a, **k: {"template_file": "x.pdf"}), \
         patch.object(fr, "safe_join", lambda *a: __file__), \
         patch.object(fr, "process_single_form",
                      lambda meta, sess, pre: {"form_id": "ACORD_125", "sqs": {"sqs_score": 70}}), \
         patch("services.stops_now.stops_now", side_effect=RuntimeError("boom")), \
         patch.object(fr, "upd_processing_session", upd):
        if sync:
            res = asyncio.run(fr.lite_generate_internal("s1", {"id": "u1", "subscription_tier": "pro"}))
            assert res.status_code == 200
        else:
            asyncio.run(fr._bg_lite_generate("s1"))
    stored = upd.call_args_list[0].args[1]
    assert stored["generated_forms"]["ACORD_125"]["sqs"]["sqs_score"] == 70
    assert stored["cross_issues_last"] == []
