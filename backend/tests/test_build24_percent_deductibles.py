"""Build 24, Z33-PERCENT (22 Oct 2026): a deductible stated as a percentage.

A wind / hail or earthquake deductible is written "2%" as often as "$5,000",
and both facts' own declaration says so ("Dollar amount or percentage"). The
class is read off that declaration (`fact_registry.takes_amount_or_percent`),
never listed, and ONE rule covers it everywhere:

1. A person's "2%" / "2 %" / "2 percent" / "1.5%" is a valid answer on the
   client questionnaire, the producer card and the editor, stored as "2%"; a
   dollar amount stays a dollar amount exactly as before; "-2%" / "200%" are
   refused. The check is `answer_check` (each fact's `validate` keeps its
   identity - the merge, the type sweep and the stamper key on it).
2. The extraction merge keeps a document's "2% of TIV"; the dec-entry backfill
   no longer turns it into "$2".
3. The client page's box takes both (`amount_or_percent`), the browser and the
   server normalizing alike (`frontend/src/utils/answerFormats.js`).
4. Printing: ACORD 160's earthquake percent box takes the percentage and its
   amount box stays blank (a dollar amount the reverse); ACORD 28's wind / hail
   amount box prints "2%"; an ACORD 140 premises row whose deductible is a
   percentage carries the percent type code. Never "$2".
5. The money reader never reads "2%" as $2; the comparison door calls "2%" and
   "2 %" the same and "2%" against "$2,000" or "$2" different.
"""
import asyncio
import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import repositories.session_repository as sr
import services.arq_service as arq
import services.pdf_service as ps
from routes.audit_routes import _validate_producer_answer
from services.answer_semantics import ABSENCE, NOT_APPLICABLE, UNKNOWN, VALUE, interpret_answer
from services.fact_registry import (
    FACT_REGISTRY, _is_currency, answer_check, answer_refusal, takes_amount_or_percent,
)
from services.normalization import stated_percentage

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"

WIND, QUAKE = "property_deductible_wind", "property_deductible_earthquake"
CLASS = (WIND, QUAKE)
EQ_AMOUNT = "CommercialPropertyCoverage_Earthquake_DeductibleAmount_A"
EQ_PERCENT = "CommercialPropertyCoverage_Earthquake_DeductiblePercent_A"
WIND_BOX = "CommercialPropertyCoverage_WindHail_DeductibleAmount_A"
NAMED_STORM = "CommercialPropertyCoverage_NamedWindstorm_DeductibleAmount_A"
EARTH_MOVEMENT = "CommercialPropertyCoverage_EarthMovement_DeductibleAmount_A"
PREM = "CommercialProperty_Premises_"

# (typed, stored) - a person's percentage answers
_PERCENT_ANSWERS = [("2%", "2%"), ("2 %", "2%"), ("2 percent", "2%"), ("1.5%", "1.5%"),
                    ("0.5%", "0.5%"), ("2% of TIV", "2% of TIV"),
                    ("2% / $25,000 minimum", "2% / $25,000 minimum"), ("2 per cent", "2%"),
                    ("100%", "100%"), ("0%", "0%")]
_REFUSED = ["-2%", "200%", "101%", "2,000%", "-2 percent", "$1,234.56.78", "2.5.5%"]


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _value(raw):
    return raw.get("value") if isinstance(raw, dict) else raw


def _stamp(fid, facts, **kw):
    return ps.map_facts_to_form(copy.deepcopy(facts), _schema(fid), fid, allow_llm=False, **kw)


def _would_reach_gap_fill(fid, field, facts):
    """The routing `compute_form_gaps` / `map_facts_to_form` apply to a box."""
    with ps._schema_context(_schema(fid)):
        scoped = {**facts, "_form_id": fid}
        result = ps._deterministic_map(field, scoped)
        if not (result == "UNMATCHED" or ps._is_empty_llm_value(result)):
            return False
        return not ps._is_authoritative_blank_field(field, scoped)


# ══ 1. The class, read off each fact's own declaration ══════════════════════

def test_the_class_is_every_money_fact_whose_declaration_names_a_percentage():
    derived = {k for k, e in FACT_REGISTRY.items()
               if e.get("validate") is _is_currency
               and "percent" in f"{e.get('format_hint')} {e.get('question')}".lower()}
    assert {k for k in FACT_REGISTRY if takes_amount_or_percent(k)} == derived == set(CLASS)
    for fact in CLASS:
        assert FACT_REGISTRY[fact]["validate"] is _is_currency          # identity kept
        assert takes_amount_or_percent(FACT_REGISTRY[fact])             # entry or key
    # a pure percentage fact and a dollar-only deductible are not in it
    for fact in ("coinsurance_percentage", "percent_subcontracted", "property_deductible_aop",
                 "property_deductible_flood", "gl_deductible"):
        assert not takes_amount_or_percent(fact), fact
    assert not takes_amount_or_percent(None) and not takes_amount_or_percent({})


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("typed,stored", _PERCENT_ANSWERS + [("$2,500", "$2,500"), ("2500", "2500")])
def test_the_person_check_takes_a_percentage_or_a_dollar_amount(fact, typed, stored):
    check = answer_check(FACT_REGISTRY[fact])
    assert check(typed) and check(stored)
    assert answer_refusal(FACT_REGISTRY[fact], stored) == ""


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("bad", _REFUSED)
def test_the_person_check_refuses_what_is_neither(fact, bad):
    assert not answer_check(FACT_REGISTRY[fact])(bad)
    assert answer_refusal(FACT_REGISTRY[fact], bad).startswith(
        "That does not look right for this field. Expected: Dollar amount or percentage")


@pytest.mark.parametrize("fact", CLASS)
def test_a_word_with_no_figure_keeps_the_amount_box_convention(fact):
    # "Not covered" / "Waived" in an amount box is a convention, as before
    assert not answer_check(FACT_REGISTRY[fact])("Not covered")
    assert answer_refusal(FACT_REGISTRY[fact], "Not covered") == ""


def test_the_shape_check_is_unchanged_for_the_merge_and_the_stamper():
    # `validate` is still the dollar shape, so nothing that keys on it moves
    assert not _is_currency("2%") and _is_currency("$2,500")
    assert answer_check(FACT_REGISTRY["property_deductible_aop"]) is _is_currency


# ══ 2. The one percentage reader ════════════════════════════════════════════

@pytest.mark.parametrize("raw,text,plain", [
    ("2%", "2%", True), ("2 %", "2%", True), ("2 percent", "2%", True), ("2 PCT.", "2%", True),
    (".5%", "0.5%", True), ("1.50%", "1.5%", True), ("02%", "2%", True),
    ("2% of TIV", "2% of TIV", False), ("  2 %  of  TIV ", "2% of TIV", False),
    ("2% / $25,000 minimum", "2% / $25,000 minimum", False),
    ("Wind/Hail 2%", "Wind/Hail 2%", False), ("Wind - 2%", "Wind - 2%", False),
])
def test_a_stated_percentage_is_its_first_figure(raw, text, plain):
    got = stated_percentage(raw)
    assert got is not None and got["text"] == text and got["plain"] is plain


@pytest.mark.parametrize("raw", ["$2,500", "2500", "2", "$25,000 or 2%", "A2%", "1,5%",
                                 "2.5.5%", "1-2%", "None", "", None, 2, ["2%"]])
def test_no_percentage_is_read_where_the_first_figure_is_not_one(raw):
    assert stated_percentage(raw) is None


def test_a_sign_counts_only_when_it_touches_the_figure():
    assert stated_percentage("-2%")["number"] == -2
    assert stated_percentage("–2%")["number"] == -2              # an en dash minus
    assert stated_percentage("Wind -2%")["number"] == -2
    assert stated_percentage("Wind - 2%")["number"] == 2              # a separator
    assert stated_percentage("200%")["number"] == 200                 # a caller refuses it


# ══ 3. What a person's answer MEANS (the one door) ══════════════════════════

@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("typed,stored", _PERCENT_ANSWERS + [("(2%)", "2%"), ("2%.", "2%")])
def test_a_percentage_answer_is_a_value_stored_as_a_percentage(fact, typed, stored):
    got = interpret_answer(fact, typed)
    assert (got.intent, got.value, got.answered) == (VALUE, stored, True)


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("typed,stored", [("$2,500", "2500"), ("2500", "2500"), ("$2", "2"), ("100", "100")])
def test_a_dollar_amount_reads_exactly_as_before(fact, typed, stored):
    # the currency reading these facts had (wind was typed currency, earthquake
    # percent - both stored the digits)
    assert interpret_answer(fact, typed).value == stored


@pytest.mark.parametrize("fact", CLASS)
def test_none_and_na_go_through_the_semantics_door(fact):
    assert interpret_answer(fact, "None").intent == ABSENCE
    assert interpret_answer(fact, "N/A").intent == NOT_APPLICABLE
    assert interpret_answer(fact, "Not covered").value == "Not covered"     # a convention
    assert interpret_answer(fact, "").intent == UNKNOWN


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("bad", _REFUSED)
def test_an_invalid_percentage_is_refused_with_both_shapes_named(fact, bad):
    got = interpret_answer(fact, bad)
    assert got.intent == UNKNOWN and not got.accepted
    if bad != "$1,234.56.78":
        assert "dollar amount or a percentage" in got.message and "2%" in got.message


# ══ 4. The client questionnaire ═════════════════════════════════════════════

def test_the_question_type_is_derived_from_the_declaration():
    for name in (WIND, QUAKE, WIND_BOX, EQ_AMOUNT, EQ_PERCENT):
        assert arq._resolve_input_type(name) == "amount_or_percent", name
    assert arq._resolve_input_type("property_deductible_aop") == "currency"
    assert not set(CLASS) & set(arq._FIELD_INPUT_TYPE)
    qs = arq.generate_arq_questions_from_facts(
        {"applicant_name": "Acme LLC", "property_building_value": "$500,000", "locations": "1 Main St"},
        {"has_property_coverage": True}, ["ACORD_140", "ACORD_160"], [], [])   # 141 = Crime (Z37)
    by = {q["field_name"]: q for q in qs}
    for fact in CLASS:
        assert by[fact]["field_type"] == "amount_or_percent"
        assert "percentage" in by[fact]["hint"] and "%" in by[fact]["hint"]


@pytest.mark.parametrize("typed,expected", [
    ("2%", "2%"), ("2 %", "2%"), ("2 percent", "2%"), ("0.5%", "0.5%"), ("2% of TIV", "2% of TIV"),
    ("2% / $25,000 minimum", "2% / $25,000 minimum"), ("$2,500", "$2,500"), ("2500", "$2,500"),
    ("-2%", None), ("200%", None), ("lots", None)])
def test_the_client_normalizer(typed, expected):
    assert arq._normalize_amount_or_percent(typed) == expected


@pytest.mark.parametrize("typed", ["2%", "2 %", "2 percent", "2% of TIV"])
def test_a_percentage_is_never_given_a_dollar_sign(typed):
    assert arq._normalize_currency(typed) is None                       # was "$2 %"
    assert arq._normalize_currency("$2,000 (1%)") == "$2,000 (1%)"      # an amount, qualified


@pytest.mark.parametrize("fact", CLASS)
def test_the_submit_cleaner_takes_both_and_blocks_what_the_page_blocks(fact):
    assert arq._clean_answer_ex("2 percent", fact) == ("2%", "")
    assert arq._clean_answer_ex("$2,500", fact) == ("$2,500", "")
    assert arq._clean_answer_ex("2% of TIV", fact) == ("2% of TIV", "")
    val, why = arq._clean_answer_ex("200%", fact)
    assert val == "200%" and why == "Could not read this as a dollar amount or a percentage"
    assert arq._blocks_submit("amount_or_percent", fact)
    assert arq._clean_answer_ex("None", fact) == ("None", "")            # an absence, not a format error


@pytest.mark.parametrize("stored_type", ["currency", "text", "amount_or_percent"])
def test_a_questionnaire_sent_before_today_is_served_the_box_that_takes_both(stored_type):
    for fact in CLASS:
        assert arq.served_field_type({"field_name": fact, "field_type": stored_type}) == "amount_or_percent"
    assert arq.served_field_type({"field_name": "total_revenue", "field_type": "currency"}) == "currency"
    assert arq.served_field_type({"field_name": WIND, "field_type": "select"}) == "select"
    assert arq.served_field_type({"field_name": "operations_description"}) == "text"


def test_the_form_assistant_is_told_the_box_takes_both():
    from routes.arq_routes import _assistant_field_block
    for stored_type in ("currency", "amount_or_percent"):
        block = _assistant_field_block({"question": "q", "field_name": WIND, "field_type": stored_type})
        assert "ANSWER TYPE: a dollar amount or a percentage, e.g. $5,000 or 2%" in block


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Acq()


@pytest.mark.parametrize("stored_type", ["currency", "amount_or_percent"])
def test_the_submit_stores_the_percentage_and_refuses_an_invalid_one(stored_type, monkeypatch):
    q = [{"field_name": WIND, "field_type": stored_type, "question": "q"},
         {"field_name": QUAKE, "field_type": "text", "question": "q"}]
    stored = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending", "questions": q}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_arq_by_token", AsyncMock(return_value=stored))
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _m, _u, errors = asyncio.run(arq.submit_arq_answers(
        "tok", {WIND: "2 percent", QUAKE: "1.5 %"}, "sid", {}))
    assert ok and errors == {}
    assert json.loads(pool.conn.calls[0][1][0]) == {WIND: "2%", QUAKE: "1.5%"}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _m, _u, errors = asyncio.run(arq.submit_arq_answers("tok", {WIND: "200%", QUAKE: "-2%"}, "sid", {}))
    assert not ok and set(errors) == {WIND, QUAKE} and pool.conn.calls == []


def _form(fid):
    return {"schema": _schema(fid), "field_state": {}, "confidence": {}}


def _apply(session, answers, questions):
    row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
           "answers": answers, "questions": questions}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=row)), \
         patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    return saved


def _session(**facts):
    return {"generated_forms": {"ACORD_28": _form("ACORD_28"), "ACORD_160": _form("ACORD_160")},
            "facts": {"applicant_name": "Acme LLC", **facts}, "flags": {"has_property_coverage": True}}


def _q(fact):
    return [{"field_name": fact, "question": "q", "form_ids": ["ACORD_28", "ACORD_160"],
             "field_type": "amount_or_percent"}]


@pytest.mark.parametrize("answer,fact_value", [("2%", "2%"), ("2 percent", "2%"), ("2% of TIV", "2% of TIV")])
def test_a_client_percentage_is_applied_and_printed_in_its_own_box(answer, fact_value):
    saved = _apply(_session(), {WIND: answer, QUAKE: answer}, _q(WIND) + _q(QUAKE))
    assert _value(saved["facts"][WIND]) == fact_value and _value(saved["facts"][QUAKE]) == fact_value
    assert not saved.get("client_answer_conflicts")
    s28 = saved["generated_forms"]["ACORD_28"]["field_state"]
    s160 = saved["generated_forms"]["ACORD_160"]["field_state"]
    assert s28[WIND_BOX] == fact_value                                  # never "$2 %", never blank
    assert s160[EQ_PERCENT] == (fact_value[:-1] if fact_value == "2%" else fact_value)
    assert not str(s160.get(EQ_AMOUNT) or "").strip()
    assert saved["generated_forms"]["ACORD_28"]["confidence"][WIND_BOX] == "client_arq"


def test_a_client_dollar_amount_is_applied_exactly_as_before():
    saved = _apply(_session(), {WIND: "$2,500"}, _q(WIND))
    assert _value(saved["facts"][WIND]) == "2500"
    assert saved["generated_forms"]["ACORD_28"]["field_state"][WIND_BOX] == "$2,500"


def test_a_client_none_is_an_answer_with_no_value():
    saved = _apply(_session(), {QUAKE: "None"}, _q(QUAKE))
    assert saved["facts"][QUAKE]["value_state"] == "explicit_no"
    assert not str(saved["generated_forms"]["ACORD_160"]["field_state"].get(EQ_PERCENT) or "").strip()


def test_a_client_percentage_against_a_documents_dollar_figure_is_held():
    doc = {"value": "$25,000", "source": "ai", "confidence": "ai_high"}
    saved = _apply(_session(**{QUAKE: doc}), {QUAKE: "2%"}, _q(QUAKE))
    assert saved["facts"][QUAKE] == doc                                  # nothing written
    assert saved["client_answer_conflicts"][QUAKE]["client_value"] == "2%"


@pytest.mark.parametrize("doc_value", ["2 %", "2 percent", "2%"])
def test_the_same_percentage_written_another_way_is_not_a_conflict(doc_value):
    doc = {"value": doc_value, "source": "ai", "confidence": "ai_high"}
    saved = _apply(_session(**{WIND: doc}), {WIND: "2%"}, _q(WIND))
    assert not saved.get("client_answer_conflicts")
    assert _value(saved["facts"][WIND]) == "2%"


def test_a_client_two_dollars_against_a_documents_two_percent_is_held():
    # the page shows a typed "2" as "$2" and stores that; it is not the 2%
    doc = {"value": "2%", "source": "ai", "confidence": "ai_high"}
    saved = _apply(_session(**{WIND: doc}), {WIND: "$2"}, _q(WIND))
    assert saved["client_answer_conflicts"][WIND]["client_value"] == "$2"


@pytest.mark.parametrize("bad", ["200%", "-2%"])
def test_an_invalid_percentage_that_reached_the_apply_is_never_printed(bad):
    # The submit refuses it (above); a stored one is still no value and no box.
    saved = _apply(_session(), {WIND: bad}, _q(WIND))
    assert not _value(saved["facts"].get(WIND))
    for fid in ("ACORD_28", "ACORD_160"):
        form = saved["generated_forms"][fid]
        assert not [b for b, v in form["field_state"].items() if b in form["schema"] and str(v) == bad]


# ══ 5. The browser and the server agree ═════════════════════════════════════

_JS_VECTORS = ["2%", "2 %", "2 percent", "2 PCT.", "1.5%", "0.5%", ".5%", "1.50%", "2% of TIV",
               "  2 %  of  TIV ", "2% / $25,000 minimum", "Wind/Hail 2%", "Wind - 2%", "Wind -2%",
               "a-2%", "-2%", "–2%", "200%", "101%", "100%", "0%", "2,000%", "1,5%", "A2%",
               "2.5.5%", "1-2%", "$2,500", "2500", "$2,500.50", "2", "$25,000 or 2%",
               "$2,000 (1%)", "$1,000,000 / $2,000,000", "$20,000 per month", "lots", "",
               # Z33-PERCENT review (22 Oct): fractions, a decimal comma, the old
               # page's "$2 %", a dollar amount before its percentage, brackets,
               # and the words an amount box holds instead of a figure.
               "1-1/2%", "1 1/2%", "1  1/2%", "1½%", "1 ½%", "½%", "1/2%", "3/4 pct",
               "2 1/2 percent", "2-1/2% of TIV", "-1/2%", "1/8%", "1/64%", "1/128%",
               "1/3%", "⅓%", "80/90%", "3/2%", "1/0%", "0/2%", "12/31/2025", "A1/2%",
               "1½½%", "Location 1: 2%", "a-1/2%", "1-1/2", "2,5%", "1,5 percent",
               "0,5%", "2,%", "2,5 %", "$2 %", "$1.50 %", "$2 % of TIV", "$-2%",
               "$10,000 min / 2%", "$25,000 minimum, 2% of TIV", "2% (min $25,000)",
               "(2% of TIV) per building", "2% Wind/Hail; 5% Named Storm", "None",
               "N/A", "No deductible", "Not covered", "Excluded", "Waived",
               "Same as AOP", "Included", "nil", "a lot", "not sure", "See schedule",
               # Review C (22 Oct): uncertainty is no box convention; a sign or
               # currency letters before the "$" refuse the percentage.
               "Not available", "not available", "-$2%", "US$2%", "us$ 2%", "CA$2 % of TIV",
               "–$2%", "Wind -$2%", "Wind - $2%", "Deductible $2%", "$ 2%"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_client_page_normalizes_exactly_as_the_server(tmp_path):
    script = tmp_path / "formats.mjs"
    script.write_text(
        f"import * as F from {json.dumps((FRONT / 'utils' / 'answerFormats.js').as_uri())};\n"
        f"const vectors = {json.dumps(_JS_VECTORS)};\n"
        "console.log(JSON.stringify(vectors.map((v) => {\n"
        "  const p = F.percentStatement(v);\n"
        "  return [p ? [p.number, p.text, p.plain] : null,\n"
        "          F.normalizeCurrency(v), F.normalizeAmountOrPercent(v)];\n"
        "})));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    js = json.loads(run.stdout)
    for v, (pct, cur, amt) in zip(_JS_VECTORS, js):
        py = stated_percentage(v)
        assert pct == ([py["number"], py["text"], py["plain"]] if py else None), v
        assert cur == arq._normalize_currency(v), v
        assert amt == arq._normalize_amount_or_percent(v), v


def test_the_client_page_draws_and_checks_the_new_box():
    page = (FRONT / "components" / "arq" / "ClientQuestionnaire.jsx").read_text(encoding="utf-8")
    import re as _re
    _imported = _re.search(r"import \{([^}]*)\} from '\.\./\.\./utils/answerFormats';", page)
    assert _imported and {"normalizeAmountOrPercent", "normalizeCurrency"} <= {
        n.strip() for n in _imported.group(1).split(",")}
    assert "const AMOUNT_OR_PERCENT = 'amount_or_percent';" in page
    assert "function normalizeCurrency" not in page                    # one copy, in the util
    assert page.count("normalizeAmountOrPercent(val)") >= 3            # submit check, blur, blur error
    assert "|| fieldType === AMOUNT_OR_PERCENT;" in page               # a structured input


# ══ 6. The producer card ════════════════════════════════════════════════════

@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("answer", ["2%", "2 %", "2 percent", "1.5%", "0.5%", "2% of TIV",
                                    "2% / $25,000 minimum", "$2,500", "2500", "Not covered", "None", "N/A"])
def test_the_producer_card_accepts_a_percentage_and_a_dollar_amount(fact, answer):
    assert _validate_producer_answer(fact, answer) == (True, "")


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("answer", ["200%", "-2%", "101%", "2,000%", "$1,234.56.78"])
def test_the_producer_card_refuses_what_is_neither(fact, answer):
    ok, err = _validate_producer_answer(fact, answer)
    assert not ok and err


def _producer_apply(field, value, facts=None, generated=None):
    store = {"facts": dict(facts or {}), "flags": {}, "generated_forms": generated or {}}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        store.update(payload)
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_producer_answer_to_session("sid", field, value))
    return ok, store


def test_a_producer_percentage_is_stored_and_moves_the_box_pair():
    facts = {"applicant_name": "Acme LLC", QUAKE: {"value": "$25,000", "source": "ai"}}
    mapped, conf = _stamp("ACORD_160", facts)
    assert (mapped[EQ_AMOUNT], mapped.get(EQ_PERCENT)) == ("25,000", None)
    gen = {"ACORD_160": {"schema": _schema("ACORD_160"), "field_state": dict(mapped), "confidence": dict(conf)}}
    ok, store = _producer_apply(QUAKE, "2 percent", facts, gen)
    assert ok and store["facts"][QUAKE]["value"] == "2%" and store["facts"][QUAKE]["source"] == "producer"
    state = store["generated_forms"]["ACORD_160"]["field_state"]
    assert state[EQ_PERCENT] == "2" and not str(state.get(EQ_AMOUNT) or "").strip()   # the stale amount leaves


def test_a_producer_dollar_amount_is_stored_as_before():
    ok, store = _producer_apply(WIND, "$2,500", {"applicant_name": "Acme LLC"})
    assert ok and store["facts"][WIND]["value"] == "2500"


# ══ 7. The editor ═══════════════════════════════════════════════════════════

def _editor_save(field_updates, facts, form_id):
    import routes.form_routes as fr
    schema = _schema(form_id)
    mapped, conf = ps.map_facts_to_form(dict(facts), schema, form_id, "", allow_llm=False)
    session = {"user_id": "u1", "active_form_id": form_id, "selected_form_ids": [form_id],
               "facts": copy.deepcopy(facts), "flags": {},
               "generated_forms": {form_id: {"form_id": form_id, "form_name": form_id,
                                             "schema": schema, "form": {"template_file": "none.pdf"},
                                             "field_state": mapped, "mapped": dict(mapped),
                                             "confidence": conf, "sqs": {}}}}
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
    call = next(c for c in upd.call_args_list if "generated_forms" in c.args[1])
    return res, call.args[1]


@pytest.mark.parametrize("typed,stored", [("2 %", "2%"), ("2 percent", "2%"), ("2%", "2%"),
                                          ("$2,500", "$2,500")])
def test_an_editor_entry_in_the_wind_box_writes_its_fact(typed, stored):
    res, saved = _editor_save({WIND_BOX: typed}, {"applicant_name": "Acme LLC"}, "ACORD_28")
    assert res.status_code == 200
    assert saved["facts"][WIND]["value"] == stored and saved["facts"][WIND]["source"] == "producer"
    printed = saved["generated_forms"]["ACORD_28"]["field_state"][WIND_BOX]
    assert not printed.startswith("$") or stored.startswith("$")        # a percentage never gets a "$"


def test_a_bare_figure_in_the_earthquake_percent_box_is_that_percentage():
    res, saved = _editor_save({EQ_PERCENT: "2"}, {"applicant_name": "Acme LLC"}, "ACORD_160")
    assert res.status_code == 200 and saved["facts"][QUAKE]["value"] == "2%"
    res, saved = _editor_save({EQ_AMOUNT: "$25,000"}, {"applicant_name": "Acme LLC"}, "ACORD_160")
    assert saved["facts"][QUAKE]["value"] == "$25,000"


def test_the_write_back_rule():
    assert ps.box_fact_value(WIND_BOX, "2 %", WIND) == "2%"
    assert ps.box_fact_value(EQ_PERCENT, "1.5", QUAKE) == "1.5%"
    assert ps.box_fact_value(EQ_AMOUNT, "2", QUAKE) == "2"                # the amount box: dollars
    assert ps.box_fact_value(EQ_PERCENT, "$25,000", QUAKE) == "$25,000"
    assert ps.box_fact_value(WIND, "2 percent", WIND) == "2%"            # a question asked as the fact
    assert ps.box_fact_value(WIND_BOX, "2 %", "property_deductible_aop") == "2 %"   # not the class


# ══ 8. The stamper ══════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,percent_box", [
    ("2%", "2"), ("2 percent", "2"), ("1.5%", "1.5"), ("0.5%", "0.5"),
    ("2% of TIV", "2% of TIV"), ("2% / $25,000 minimum", "2% / $25,000 minimum")])
def test_160_a_percentage_prints_in_the_percent_box_and_the_amount_box_is_blank(value, percent_box):
    mapped, conf = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped[EQ_PERCENT] == percent_box and conf[EQ_PERCENT] == "filled"
    assert mapped.get(EQ_AMOUNT) is None                                 # never split
    assert not _would_reach_gap_fill("ACORD_160", EQ_AMOUNT, {QUAKE: value})   # owned, not asked


@pytest.mark.parametrize("value", ["$25,000", "25000"])
def test_160_a_dollar_amount_does_the_reverse(value):
    mapped, conf = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped[EQ_AMOUNT] == "25,000" and conf[EQ_AMOUNT] == "filled"    # the form prints the "$"
    assert mapped.get(EQ_PERCENT) is None
    assert not _would_reach_gap_fill("ACORD_160", EQ_PERCENT, {QUAKE: value})


def test_160_with_no_deductible_stated_both_boxes_still_read_the_documents():
    for box in (EQ_AMOUNT, EQ_PERCENT):
        assert _would_reach_gap_fill("ACORD_160", box, {"applicant_name": "Acme LLC"}), box


@pytest.mark.parametrize("value,printed", [
    ("2%", "2%"), ("2 percent", "2%"), ("2 pct", "2%"), ("2% of TIV", "2% of TIV"),
    ("2% / $25,000 minimum", "2% / $25,000 minimum"), ("$2,500", "$2,500"), ("2500", "$2,500")])
def test_28_the_amount_box_prints_a_percentage_as_written(value, printed):
    mapped, conf = _stamp("ACORD_28", {"applicant_name": "Acme LLC", WIND: value})
    assert mapped[WIND_BOX] == printed and conf[WIND_BOX] == "filled"     # never "$2 %", never blank


def test_28_named_windstorm_and_earth_movement_stay_with_the_documents():
    facts = {"applicant_name": "Acme LLC", WIND: "2%", QUAKE: "5%"}
    mapped, _ = _stamp("ACORD_28", facts)
    assert mapped.get(NAMED_STORM) is None and mapped.get(EARTH_MOVEMENT) is None
    for box in (NAMED_STORM, EARTH_MOVEMENT):
        assert _would_reach_gap_fill("ACORD_28", box, facts), box


def test_the_two_facts_reach_exactly_their_boxes():
    assert ps.fact_to_form_fields(WIND) == {"ACORD_28": (WIND_BOX,)}
    assert ps.fact_to_form_fields(QUAKE) == {"ACORD_160": (EQ_AMOUNT, EQ_PERCENT)}
    for box, fact in ((WIND_BOX, WIND), (EQ_AMOUNT, QUAKE), (EQ_PERCENT, QUAKE)):
        assert fact in arq._canonical_keys_for(box)


@pytest.mark.parametrize("value", ["2%", "$25,000"])
def test_field_qa_expects_what_the_box_prints(value):
    facts = {QUAKE: value}
    mapped, _ = _stamp("ACORD_160", {"applicant_name": "Acme LLC", **facts})
    for box in (EQ_AMOUNT, EQ_PERCENT):
        expected = ps.authoritative_expected_value("ACORD_160", box, facts, _schema("ACORD_160"))
        assert expected == ps.amount_or_percent_box_value(box, value, _schema("ACORD_160"))
        assert (expected is None) == (mapped.get(box) is None)


def _p140(**over):
    return {"applicant_name": "Acme LLC",
            "property_locations": [{"address_line1": "1 Main St", "address_city": "Denver",
                                    "address_state": "CO", "address_zip": "80202"}], **over}


def test_140_a_percentage_deductible_row_carries_the_percent_type_code():
    from services.property_coverages import PERCENT_DEDUCTIBLE_TYPE, _deductible
    assert _deductible("2%") == ("2%", PERCENT_DEDUCTIBLE_TYPE)          # the schedule reader's code
    mapped, conf = _stamp("ACORD_140", _p140(property_deductible_aop="2%"))
    assert mapped[PREM + "DeductibleAmount_A"] == "2%"                    # no "$"
    assert mapped[PREM + "DeductibleTypeCode_A"] == PERCENT_DEDUCTIBLE_TYPE
    assert conf[PREM + "DeductibleTypeCode_A"] == "filled"
    mapped, _ = _stamp("ACORD_140", _p140(property_deductible_aop="$5,000"))
    assert mapped[PREM + "DeductibleAmount_A"] == "$5,000"
    assert mapped.get(PREM + "DeductibleTypeCode_A") is None               # a dollar row: unchanged


def test_140_an_ai_percentage_deductible_takes_the_percent_code_over_a_contradicting_one():
    values = {PREM + "SubjectOfInsuranceCode_A": "Building", PREM + "LimitAmount_A": "$500,000",
              PREM + "DeductibleAmount_A": "2%", PREM + "DeductibleTypeCode_A": "Dollars"}
    mapped, conf = _stamp("ACORD_140", _p140(), raw_text="Building limit $500,000. Wind deductible 2%.",
                          pre_filled_gpt={"filled_values": values, "question_grounding": {}})
    assert mapped[PREM + "DeductibleAmount_A"] == "2%"
    assert mapped[PREM + "DeductibleTypeCode_A"] == "Percent"
    assert conf[PREM + "DeductibleTypeCode_A"] != "filled"                 # the AI's amount's provenance


def test_the_type_sweep_leaves_a_percent_code_and_a_dollar_row_alone():
    schema = {PREM + "DeductibleAmount_A": {}, PREM + "DeductibleTypeCode_A": {},
              PREM + "DeductibleAmount_B": {}, PREM + "DeductibleTypeCode_B": {}}
    mapped = {PREM + "DeductibleAmount_A": "2%", PREM + "DeductibleTypeCode_A": "pct",
              PREM + "DeductibleAmount_B": "$5,000", PREM + "DeductibleTypeCode_B": "Dollars"}
    assert ps._type_percentage_deductibles(mapped, schema, set(), set()) == []
    assert mapped[PREM + "DeductibleTypeCode_A"] == "pct" and mapped[PREM + "DeductibleTypeCode_B"] == "Dollars"


@pytest.mark.parametrize("value", ["2%", "2 %", "2 percent", "2 pct", "2 per cent", "2% of TIV"])
def test_the_display_layer_never_gives_a_percentage_a_dollar_sign(value):
    from services.display_canonicalizer import canonicalize_currency, canonicalize_for_field
    assert canonicalize_currency(value) == value
    assert not str(canonicalize_for_field(WIND_BOX, value)).startswith("$")
    assert canonicalize_currency("2500") == "$2,500"


# ══ 9. Extraction ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("printed", ["2%", "2 %", "2% of TIV", "2% / $25,000 minimum", "$2,500"])
def test_the_merge_keeps_a_documents_percentage_as_printed(printed):
    from services.extraction_service import merge_facts
    doc = {"filename": "dec.pdf", "doc_type": "Declarations Page", "raw_text": "",
           "facts": {"applicant_name": "Acme LLC", WIND: printed, QUAKE: printed},
           "flags": {"has_property_coverage": True}}
    merged, _ = merge_facts([doc], doc)
    assert _value(merged[WIND]) == printed and _value(merged[QUAKE]) == printed


@pytest.mark.parametrize("printed", ["2%", "2% of TIV"])
def test_the_dec_entry_backfill_keeps_a_percentage_instead_of_two_dollars(printed):
    from services.extraction_service import _backfill_empty_facts_from_entries, _backfill_value_for
    facts = {"applicant_name": "Acme LLC"}
    entries = [{"label": "Property Deductible - Wind/Hail", "value": printed, "owner": "policy"},
               {"label": "Property Deductible Earthquake", "value": printed, "owner": "policy"}]
    _backfill_empty_facts_from_entries(facts, entries)
    assert _value(facts[WIND]) == printed and _value(facts[QUAKE]) == printed
    # a dollar fact never backfills a percentage as an amount
    assert _backfill_value_for(_is_currency, printed) is None
    assert _backfill_value_for(_is_currency, "$500(any one premises)") == "$500"


def test_the_dec_entry_backfill_never_keeps_an_invalid_percentage():
    from services.extraction_service import _backfill_empty_facts_from_entries
    facts = {"applicant_name": "Acme LLC"}
    _backfill_empty_facts_from_entries(
        facts, [{"label": "Property Deductible - Wind/Hail", "value": "200%", "owner": "policy"}])
    assert WIND not in facts


# ══ 10. Scoring and comparison ══════════════════════════════════════════════

@pytest.mark.parametrize("raw", ["2%", "2 %", "1.5 percent", "2 pct"])
def test_the_money_reader_never_reads_a_percentage_as_dollars(raw):
    import services.cross_form_validator as cfv
    import services.sqs_service as sq
    assert sq._to_float(raw) is None and cfv._to_float(raw) is None


def test_the_money_reader_still_reads_the_amounts_beside_a_percentage():
    import services.sqs_service as sq
    assert sq._to_float("2% / $25,000 minimum") == 25_000
    assert sq._to_float("$1.5M (35%)") == 1_500_000
    assert sq._to_float("66 FT / 7 PT") == 66
    assert sq._to_float("$2,500") == 2_500


@pytest.mark.parametrize("value", ["2%", "2% of TIV", "2 percent"])
def test_a_percentage_counts_as_stated_for_every_score_reader(value):
    """The SQS reads these two facts for PRESENCE only (the peril-deductible
    warning, the property pillar's copies, the question inventories); no reader
    compares them with a dollar threshold. The basis check reads the "%"."""
    import services.cross_form_validator as cfv
    import services.sqs_service as sq
    facts = {"property_building_value": "$500,000", "locations": "1 Main St", WIND: value}
    _hard, soft = sq.evaluate_stops(dict(facts), {"has_property_coverage": True,
                                                  "property_has_peril_deductibles": True})
    assert not [s for s in soft if "Peril-specific deductibles" in s]
    assert sq._answered(facts, WIND)
    assert cfv._deductible_basis_evident(value, peril=True)


def test_the_package_probe_still_answers_with_a_dollar_amount():
    """The score probe reads `answer_check`, which now also takes a percentage:
    its first accepted probe answer is unchanged ("50"), so no points move."""
    import services.sqs_service as sq
    for fact in CLASS:
        assert sq._package_probe_answer(fact) == ("50", True)


@pytest.mark.parametrize("a,b,same", [
    ("2%", "2 %", True), ("2%", "2 percent", True), ("2 percent", "2 pct", True),
    ("2% of TIV", "2%", True), ("2%", "$2,000", False), ("2%", "5%", False),
    ("2%", "$2", False), ("2% / $25,000 minimum", "2% / $50,000 minimum", False),
    ("$2,500", "2500", True), ("2%", "2", True)])
def test_the_comparison_door(a, b, same):
    from services.fact_comparison import SAME, compare, verdict
    for fact in CLASS:
        assert (verdict(fact, a, b) == SAME) is same, (fact, a, b)
    assert compare(WIND, ["2%", "2 %", "2 percent"]).verdict == "equivalent"
    assert compare(WIND, ["2%", "$2,000"]).is_conflict


def test_the_data_consistency_picker_groups_percentages_by_their_figure():
    from services.underwriting_consistency import _normalize
    assert _normalize("2%", "identity", WIND) == _normalize("2 %", "identity", WIND)
    assert _normalize("2%", "identity", WIND) != _normalize("$2", "identity", WIND)
    assert _normalize("$2,000", "identity", WIND) == _normalize("2000", "identity", WIND)
    # a fact that is not money keeps its key exactly
    from services.normalization import normalize_value
    assert _normalize("80%", "identity", "coinsurance_percentage") == normalize_value(
        "coinsurance_percentage", "80%")


def test_a_data_consistency_confirmation_takes_a_percentage():
    from services.underwriting_consistency import validate_confirmation
    docs = [{"filename": "a.pdf", "facts": {WIND: "2%"}}, {"filename": "b.pdf", "facts": {WIND: "$5,000"}}]
    assert validate_confirmation(WIND, "2%", docs) == "2%"
    with pytest.raises(ValueError):
        validate_confirmation(WIND, "200%", docs)


# ══ 11. The dry run can prove the percent box ═══════════════════════════════

def test_the_dry_run_probes_an_amount_or_percent_fact_with_a_percentage():
    from services.form_dry_run import _probe_values, route_fills
    route = {"mode": "field", "facts": [QUAKE]}
    assert "2%" in _probe_values(route)
    assert route_fills("ACORD_160", _schema("ACORD_160"), [EQ_PERCENT], {"applicant_name": "Acme LLC"}, route)
    assert route_fills("ACORD_160", _schema("ACORD_160"), [EQ_AMOUNT], {"applicant_name": "Acme LLC"}, route)
