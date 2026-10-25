"""Review of Z33-PERCENT, round D (22 Oct 2026): three small fixes.

1. "25000/2%" (no "$", no comma) was read as the fraction / range run
   "25000/2" and printed in ACORD 160's "%" box. A figure above 100 never
   starts a percentage run, so it prints whole in the "$" box, like
   "$25,000 / 2%".
2. A bare figure ("2") for an amount-or-percent deductible was read as $2.
   Owner's call: the deductible basis check's own line - under 100 a bare
   figure on a peril deductible is that peril's percentage - so "2" is "2%",
   100 or more stays dollars, anything with "$" stays dollars. One reader
   (`normalization.bare_figure_as_percentage`) for the client page (server and
   browser twin), the producer card (the semantics door) and the editor.
3. A held client answer stayed under "Needs your decision" after a later
   questionnaire answer or the producer wrote a good value for the same item.
"""
import asyncio
import copy
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import repositories.session_repository as sr
import services.arq_service as arq
import services.pdf_service as ps
from services import client_answer_review as car
from services import cross_form_validator as cfv
from services.answer_semantics import interpret_answer
from services.normalization import PERCENT_DEDUCTIBLE_CEILING, bare_figure_as_percentage

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"
WIND = "property_deductible_wind"
EQ_AMOUNT = "CommercialPropertyCoverage_Earthquake_DeductibleAmount_A"
EQ_PERCENT = "CommercialPropertyCoverage_Earthquake_DeductiblePercent_A"
WIND_BOX = "CommercialPropertyCoverage_WindHail_DeductibleAmount_A"


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


# ══ 1. A figure above 100 never starts a percentage run ═════════════════════

@pytest.mark.parametrize("value", ["25000/2%", "25000 / 2%", "25000-2%", "5000/1%", "101-2%"])
def test_a_figure_above_100_is_no_percentage_run(value):
    assert ps._unread_percentage(value) is None
    assert ps.amount_or_percent_box_value(EQ_PERCENT, value, _schema("ACORD_160")) is None
    assert ps.amount_or_percent_box_value(EQ_AMOUNT, value, _schema("ACORD_160")) == value


@pytest.mark.parametrize("value,figure", [("1-2%", "1-2"), ("100-2%", "100-2"), ("2.1-2%", "2.1-2")])
def test_a_small_range_is_still_a_percentage_run(value, figure):
    got = ps._unread_percentage(value)
    assert got is not None and got["figure"] == figure


def test_fractions_and_the_dollar_statement_are_unchanged():
    schema = _schema("ACORD_160")
    assert ps.amount_or_percent_box_value(EQ_PERCENT, "1-1/2%", schema) == "1.5"
    assert ps.amount_or_percent_box_value(EQ_PERCENT, "1-2%", schema) == "1-2"
    assert ps.amount_or_percent_box_value(EQ_AMOUNT, "$25,000 / 2%", schema) == "$25,000 / 2%"


# ══ 2. A bare figure under the basis check's line is a percentage ═══════════

def test_the_threshold_is_the_basis_checks_own():
    assert PERCENT_DEDUCTIBLE_CEILING == 100
    src = Path(cfv.__file__).read_text(encoding="utf-8")
    assert "amount >= PERCENT_DEDUCTIBLE_CEILING" in src
    # The basis check: a bare 99 on a peril is a percentage, 100 is dollars.
    assert cfv._deductible_basis_evident("99", peril=True)
    assert cfv._deductible_basis_evident("100", peril=False)
    assert not cfv._deductible_basis_evident("99", peril=False)


@pytest.mark.parametrize("value,text", [("2", "2%"), (" 2 ", "2%"), ("1.5", "1.5%"), ("0", "0%"),
                                        ("99", "99%"), ("99.9", "99.9%"), (".5", "0.5%")])
def test_a_bare_small_figure_is_a_percentage(value, text):
    assert bare_figure_as_percentage(value)["text"] == text
    assert arq._normalize_amount_or_percent(value) == text
    got = interpret_answer(WIND, value)
    assert got.accepted and got.value == text


@pytest.mark.parametrize("value", ["100", "2500", "$2", "$ 2", "2 dollars", "2k", "1,000", "-2", "",
                                   "1-1/2", "½", "1 1/2", "2 2"])
def test_anything_else_is_not_a_bare_percentage(value):
    assert bare_figure_as_percentage(value) is None


@pytest.mark.parametrize("value,stored", [("100", "$100"), ("2500", "$2,500"), ("$2", "$2")])
def test_100_or_more_and_any_dollar_sign_stay_dollars(value, stored):
    assert arq._normalize_amount_or_percent(value) == stored
    got = interpret_answer(WIND, value)
    assert got.accepted and "%" not in str(got.value)


def test_a_plain_currency_fact_is_untouched():
    assert arq._normalize_currency("2") == "$2"
    assert "%" not in str(interpret_answer("property_deductible_aop", "2").value)


def test_the_editor_reads_a_bare_figure_through_the_same_door():
    assert ps.box_fact_value(WIND_BOX, "2", WIND) == "2%"
    assert ps.box_fact_value(WIND_BOX, "$2", WIND) == "$2"
    assert ps.box_fact_value(WIND_BOX, "2500", WIND) == "2500"
    # The 160 "%" box keeps its own rule (0 to 100 inclusive); its "$" box
    # says dollars by itself.
    assert ps.box_fact_value(EQ_PERCENT, "100", "property_deductible_earthquake") == "100%"
    assert ps.box_fact_value(EQ_AMOUNT, "2", "property_deductible_earthquake") == "2"


_JS_VECTORS = ["2", " 2 ", "1.5", "0", "99", "99.9", "100", "101", "2500", "$2", "$ 2", "1-1/2",
               "½", ".5", "-2", "2k", "1,000", "2 dollars", "25000/2%", "", "1 1/2", "2 2"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_twin_reads_bare_figures_as_the_server(tmp_path):
    script = tmp_path / "bare.mjs"
    script.write_text(
        f"import * as F from {json.dumps((FRONT / 'utils' / 'answerFormats.js').as_uri())};\n"
        f"const vectors = {json.dumps(_JS_VECTORS)};\n"
        "console.log(JSON.stringify([F.PERCENT_DEDUCTIBLE_CEILING, vectors.map((v) => {\n"
        "  const b = F.bareFigurePercent(v);\n"
        "  return [b ? b.text : null, F.normalizeAmountOrPercent(v)];\n"
        "})]));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    ceiling, js = json.loads(run.stdout)
    assert ceiling == PERCENT_DEDUCTIBLE_CEILING
    for v, (bare, amt) in zip(_JS_VECTORS, js):
        py = bare_figure_as_percentage(v)
        assert bare == (py["text"] if py else None), v
        assert amt == arq._normalize_amount_or_percent(v), v


# ══ 3. A later good value answers an open hold ══════════════════════════════

def test_release_drops_only_the_written_keys():
    held = {"year_built": {"client_value": "2050"}, "year_built@loc2": {"client_value": "2050"},
            WIND: {"client_value": "$2"}}
    assert car.release_superseded_holds(held, ["year_built@loc2", "num_employees"]) == ["year_built@loc2"]
    assert set(held) == {"year_built", WIND}
    assert car.release_superseded_holds(None, ["x"]) == []
    assert car.release_superseded_holds({}, ["x"]) == []


def _client_apply(facts, held, answers, questions):
    session = {"generated_forms": {}, "facts": copy.deepcopy(facts), "flags": {},
               "client_answer_conflicts": copy.deepcopy(held)}
    row = {"id": "arq-2", "status": "submitted", "session_id": "s1",
           "answers": answers, "questions": questions}
    saved: dict = {"deletes": None}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(copy.deepcopy(payload))
        saved["deletes"] = delete_facts

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=row)), \
         patch("repositories.session_repository.get_processing_session",
               AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-2", "s1"))
    assert ok
    return saved


_OLD_HOLD = {"client_value": "2050", "source_value": "", "field_name": "year_built",
             "arq_id": "arq-1", "kind": "format", "held_at": "2026-10-22T00:00:00+00:00"}


def test_a_later_questionnaire_answer_releases_the_hold():
    saved = _client_apply({"applicant_name": "Acme LLC"}, {"year_built": _OLD_HOLD},
                          {"year_built": "1998"},
                          [{"field_name": "year_built", "question": "Year built?", "form_ids": []}])
    assert "year_built" not in (saved.get("client_answer_conflicts") or {})
    assert "_client_answer_conflicts" in (saved["deletes"] or [])


def test_an_answer_for_another_fact_keeps_the_hold():
    saved = _client_apply({"applicant_name": "Acme LLC"}, {"year_built": _OLD_HOLD},
                          {"num_employees": "12"},
                          [{"field_name": "num_employees", "question": "Staff?", "form_ids": []}])
    assert "year_built" in saved["client_answer_conflicts"]


def test_a_later_bad_answer_is_held_again_not_released():
    saved = _client_apply({"applicant_name": "Acme LLC"}, {"year_built": _OLD_HOLD},
                          {"year_built": "2077"},
                          [{"field_name": "year_built", "question": "Year built?", "form_ids": []}])
    assert saved["client_answer_conflicts"]["year_built"]["client_value"] == "2077"


def test_the_producer_setting_the_fact_releases_the_hold():
    held = {WIND: {"client_value": "$2", "source_value": "2%", "field_name": WIND},
            "year_built": dict(_OLD_HOLD)}
    store = {"facts": {"applicant_name": "Acme LLC", WIND: "2%",
                       "_client_answer_conflicts": copy.deepcopy(held)},
             "flags": {}, "generated_forms": {}, "docs": [],
             "client_answer_conflicts": copy.deepcopy(held)}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        store.update(copy.deepcopy(payload))
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_producer_answer_to_session("sid", WIND, "2%"))
    assert ok
    assert set(store["client_answer_conflicts"]) == {"year_built"}
    assert set(store["facts"]["_client_answer_conflicts"]) == {"year_built"}
    assert [r["fact_key"] for r in car.build_review_rows(store)] == ["year_built"]


def _editor_save(field_updates, held):
    import routes.form_routes as fr
    from types import SimpleNamespace
    form_id = "ACORD_125"
    facts = {"applicant_name": "Acme LLC", "_client_answer_conflicts": copy.deepcopy(held)}
    schema = _schema(form_id)
    mapped, conf = ps.map_facts_to_form(dict(facts), schema, form_id, "", allow_llm=False)
    session = {"user_id": "u1", "active_form_id": form_id, "selected_form_ids": [form_id],
               "facts": copy.deepcopy(facts), "flags": {},
               "client_answer_conflicts": copy.deepcopy(held),
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
    assert res.status_code == 200
    call = next(c for c in upd.call_args_list if "generated_forms" in c.args[1])
    return call.args[1], call.kwargs.get("delete_facts") or []


_NAME_HOLD = {"applicant_name": {"client_value": "Acme Co", "source_value": "Acme LLC",
                                 "field_name": "applicant_name"}}


def test_an_editor_save_of_the_package_fact_releases_the_hold():
    stored, deletes = _editor_save({"NamedInsured_FullName_A": "Acme Holdings LLC"}, _NAME_HOLD)
    assert stored["facts"]["applicant_name"]["value"] == "Acme Holdings LLC"
    assert stored["client_answer_conflicts"] == {}
    assert "_client_answer_conflicts" in deletes


def test_an_editor_save_of_a_row_b_box_keeps_the_hold():
    stored, deletes = _editor_save({"NamedInsured_FullName_B": "Other Co LLC"}, _NAME_HOLD)
    assert "client_answer_conflicts" not in stored                 # untouched
    assert "applicant_name" in stored["facts"]["_client_answer_conflicts"]
    assert "_client_answer_conflicts" not in deletes
