"""Review of Z33-PERCENT, lane A (22 Oct 2026): reading, answers and comparison.

The adversarial review of the percentage-deductible change confirmed these
defects on the reading / comparison side; each test below pins its fix:

 1. "2.5%" and "25%" (and "1.5%" / "15%") compared as one value, so a client's
    "25%" replaced a document's "2.5%" without being held. The door's first-pass
    key is now built from the parsed figure, and `normalize_general` no longer
    deletes a decimal point a digit follows ("2.5" was "25", "$2.5M" was "$25M").
 2/15. A decimal-comma percentage ("2,5%") became "$25 %" on the client page and
    the server, then a stored and printed "$25%".
 4/14. The client page refused "None", "N/A", "Not covered", "Excluded",
    "Waived", "Same as AOP" on the wind / earthquake question, and the server
    refused the last four. One words rule, written twice (server + browser).
 5. "2% (min $25,000)" was stored as "2% (min $25,000" (an edge strip took the
    closing bracket).
 6. "$25,000 or 2%" was stored as 25000 and printed as a flat $25,000.
 8. A fraction ("1-1/2%", "1½%", "1/2%") was no percentage, so ACORD 160 printed
    it in the earthquake "$" box.
12. Two printings of one composite deductible ("2% subject to $25,000 minimum" /
    "$25,000 minimum or 2%, whichever is greater") were called different: a false
    Data Consistency row and an 85 cap.
13. "$2", "2" and "2%" were a conflict in three document orders and agreed in
    the other three.
16. A "$2 %" left by the old page was stored and printed "$2%".
"""
import asyncio
import itertools
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import services.arq_service as arq
from routes.audit_routes import _validate_producer_answer
from services.answer_semantics import (
    ABSENCE, NOT_APPLICABLE, UNKNOWN, VALUE, interpret_answer, is_amount_box_convention,
)
from services.fact_comparison import SAME, DIFFERENT, compare, comparison_key, verdict
from services.normalization import (
    mentions_a_percentage, normalize_general, normalize_value, stated_percentage,
)
from tests.test_build24_percent_deductibles import (
    _JS_VECTORS, _Pool, _apply, _q, _session, _stamp, _value,
    EQ_AMOUNT, EQ_PERCENT, QUAKE, WIND, WIND_BOX,
)

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"
CLASS = (WIND, QUAKE)


def _picker_rows(fact, printings):
    from services.underwriting_consistency import assess_underwriting_consistency
    docs = [{"doc_id": f"d{i}", "filename": f"doc{i}.pdf", "doc_type": "declarations_page",
             "facts": {fact: {"value": v, "source": "ai", "confidence": 0.9}}, "text": str(v)}
            for i, v in enumerate(printings)]
    uw = assess_underwriting_consistency(docs, {fact: {"value": printings[0]}}, {},
                                         {"has_property_coverage": True})
    return [r for r in uw.get("fields", []) if r.get("fact_key") == fact]


# ══ 1. A decimal point is part of its figure ═════════════════════════════════

@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("a,b", [("2.5%", "25%"), ("1.5%", "15%"), ("0.5%", "5%"), ("12.5%", "125%")])
def test_percentages_that_differ_by_a_decimal_point_are_different(fact, a, b):
    assert comparison_key(fact, a) != comparison_key(fact, b)
    assert compare(fact, [a, b]).is_conflict
    assert verdict(fact, a, b) == DIFFERENT
    rows = _picker_rows(fact, [a, b])
    assert rows and rows[0]["status"] == "conflict"


@pytest.mark.parametrize("fact", CLASS)
def test_one_percentage_written_several_ways_keeps_one_key(fact):
    keys = {comparison_key(fact, v) for v in ("2.5%", "2.5 %", "2.5 percent", "2.50 pct",
                                              "2-1/2%", "2 1/2 percent", "2½%")}
    assert keys == {"2.5%"}
    assert comparison_key(fact, "2% of TIV") == "2% of tiv"
    assert compare(fact, ["2.5%", "2 1/2%", "2.50 %"]).verdict == "equivalent"


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("doc,client", [("2.5%", "25%"), ("1.5%", "15%"), ("25%", "2.5%")])
def test_a_client_percentage_ten_times_the_documents_is_held(fact, doc, client):
    env = {"value": doc, "source": "ai_extracted", "confidence": 0.9}
    assert arq._client_answer_conflicts_with_source(fact, env, doc, client)
    held = {"value": doc, "source": "ai", "confidence": "ai_high"}
    saved = _apply(_session(**{fact: held}), {fact: client}, _q(fact))
    assert saved["facts"][fact] == held                                  # nothing written
    assert saved["client_answer_conflicts"][fact]["client_value"] == client


@pytest.mark.parametrize("a,b", [("2.5", "25"), ("$2.5M", "$25M"), ("1.05", "105"),
                                 ("1,234.56", "123456"), ("12.5", "125"), ("0.5", "5"),
                                 ("1.2.3", "12.3")])
def test_the_text_normaliser_keeps_a_decimal_point(a, b):
    assert normalize_general(a) != normalize_general(b)
    for fact in ("gl_each_occurrence", "operations_description", "wc_xmod"):
        assert normalize_value(fact, a) != normalize_value(fact, b), (fact, a, b)


@pytest.mark.parametrize("a,b", [
    ("1,000.", "1000"), ("$1,000,000.", "1000000"), ("1000.", "1000"), ("5.", "5"),
    ("1,000,000.00", "1000000"), ("12.50", "12.5"), ("1.0", "1"), ("1.0800", "1.08"),
    ("$1.0M", "$1M"), ("$.5M", "$0.5M"), (".5", "0.5"), ("555.123.4567", "5551234567"),
    ("1.000.000", "1000000"), ("Item 5. Roofing", "Item 5 Roofing"), ("2.a", "2a"),
    ("$1,000,000 CSL", "1000000 Combined Single Limit"),
])
def test_trailing_periods_and_insignificant_zeros_still_compare_the_same(a, b):
    assert normalize_general(a) == normalize_general(b)


def test_what_else_moved_with_the_decimal_point():
    """The other readers of `normalize_value`: two decimals that differ only by
    their point are now two values everywhere - the conflict detector's gate,
    Field QA's stamped-vs-expected check and the door's text fallback - and a
    figure ending a sentence is no longer a different value."""
    from services.field_qa import _value_matches
    assert not _value_matches("wc_xmod", "1.08", "108")                    # was a silent match
    assert _value_matches("wc_xmod", "1.08", "1.0800")
    assert _value_matches("total_revenue", "$1,000,000.", "1000000")       # was a false mismatch
    assert normalize_value("total_revenue", "$2.5M") != normalize_value("total_revenue", "$25M")
    assert verdict("gl_each_occurrence", "$2.5M", "$25M") == DIFFERENT     # money: always was
    assert verdict("wc_xmod", "1.08", "108") == DIFFERENT
    assert verdict("wc_xmod", "1.0800", "1.08") == SAME
    assert verdict("total_revenue", "$1,000,000.", "1,000,000") == SAME


# ══ 2 / 15. A decimal comma is no amount ═════════════════════════════════════

@pytest.mark.parametrize("typed", ["2,5%", "1,5%", "0,5%", "2,%", "2,5 %", "1,5 percent", "1½"])
def test_a_decimal_comma_percentage_is_never_dollars(typed):
    assert arq._normalize_currency(typed) is None
    assert arq._normalize_amount_or_percent(typed) is None
    for fact in CLASS:
        val, why = arq._clean_answer_ex(typed, fact)
        assert val == typed and why == "Could not read this as a dollar amount or a percentage"
        assert arq._blocks_submit("amount_or_percent", fact)
        assert interpret_answer(fact, typed).intent == UNKNOWN            # "2,5 percent" was $25
        ok, err = _validate_producer_answer(fact, typed)
        assert not ok and err


def test_an_amount_with_its_qualifier_reads_as_before():
    assert arq._normalize_currency("$2,000 (1%)") == "$2,000 (1%)"
    assert arq._normalize_currency("$20,000 per month") == "$20,000 per month"
    assert arq._normalize_currency("2500") == "$2,500"
    assert arq._normalize_currency("$2.5M") == "$2,500,000"
    assert arq._normalize_currency("$ 2,500") == "$2,500"                # a no-break space


# ══ 4 / 14. What an amount box holds instead of a figure ═════════════════════

_BOX_WORDS = ["None", "none", "N/A", "n/a", "NA", "nil", "No", "Nothing", "Zero",
              "No deductible", "No earthquake coverage", "No EQ deductible",
              "Not covered", "Not applicable", "Does not apply", "Doesn't apply",
              "Not purchased", "Excluded", "Earthquake excluded", "Waived",
              "Declined", "Same as AOP", "Same as all other perils", "AOP",
              "Included", "Included in AOP", "See schedule", "Per schedule",
              "As scheduled", "See attached", "Per policy", "See dec page",
              "None - excluded", "(None)", "There is no deductible"]
_NOT_WORDS = ["lots", "a lot", "not much", "covered", "not sure", "no idea", "Yes",
              "standard", "the usual", "deductible", "applicable", "not", "big one",
              "-", "", "Same as last year", "TBD", "2% maybe", "$5,000 or so"]


@pytest.mark.parametrize("word", _BOX_WORDS)
def test_a_box_convention_is_taken_on_the_page_and_the_server(word):
    assert is_amount_box_convention(word)
    for fact in CLASS:
        val, why = arq._clean_answer_ex(word, fact)
        assert why == "" and val == word.strip()
        # and on a questionnaire sent before today (wind "currency", earthquake "text")
        for stored in ("currency", "text"):
            assert arq.served_field_type({"field_name": fact, "field_type": stored}) == "amount_or_percent"


@pytest.mark.parametrize("word", _NOT_WORDS)
def test_text_that_says_nothing_is_still_refused(word):
    assert not is_amount_box_convention(word)


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("word", ["lots", "a lot", "not much", "covered", "Yes", "standard"])
def test_the_server_still_refuses_text_that_says_nothing(fact, word):
    val, why = arq._clean_answer_ex(word, fact)
    assert why == "Could not read this as a dollar amount or a percentage"
    assert arq._blocks_submit(arq.served_field_type({"field_name": fact, "field_type": "text"}), fact)


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("word,intent,value", [
    ("None", ABSENCE, ""), ("N/A", NOT_APPLICABLE, ""), ("No deductible", ABSENCE, ""),
    ("Not covered", VALUE, "Not covered"), ("Excluded", VALUE, "Excluded"),
    ("Waived", VALUE, "Waived"), ("Same as AOP", VALUE, "Same as AOP")])
def test_what_a_box_convention_means_is_unchanged(fact, word, intent, value):
    got = interpret_answer(fact, word)
    assert (got.intent, got.value, got.accepted) == (intent, value, True)


def test_the_submit_takes_a_convention_and_refuses_lots(monkeypatch):
    q = [{"field_name": WIND, "field_type": "currency", "question": "q"},
         {"field_name": QUAKE, "field_type": "text", "question": "q"}]
    stored = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending", "questions": q}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_arq_by_token", AsyncMock(return_value=stored))
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _m, _u, errors = asyncio.run(arq.submit_arq_answers(
        "tok", {WIND: "Same as AOP", QUAKE: "Not covered"}, "sid", {}))
    assert ok and errors == {}
    assert json.loads(pool.conn.calls[0][1][0]) == {WIND: "Same as AOP", QUAKE: "Not covered"}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _m, _u, errors = asyncio.run(arq.submit_arq_answers("tok", {WIND: "lots", QUAKE: "lots"}, "sid", {}))
    assert not ok and set(errors) == {WIND, QUAKE} and pool.conn.calls == []


def test_a_client_convention_is_applied_and_printed_in_the_amount_box():
    saved = _apply(_session(), {WIND: "Not covered"}, _q(WIND))
    assert _value(saved["facts"][WIND]) == "Not covered"
    assert saved["generated_forms"]["ACORD_28"]["field_state"][WIND_BOX] == "Not covered"


def test_the_page_checks_with_the_same_rule_on_submit_and_on_blur():
    page = (FRONT / "components" / "arq" / "ClientQuestionnaire.jsx").read_text(encoding="utf-8")
    assert "isAmountBoxConvention" in page.split("from '../../utils/answerFormats'")[0]
    assert page.count("!normalizeAmountOrPercent(val) && !isAmountBoxConvention(val)") == 2


# ══ 5. A bracket the answer closes stays ═════════════════════════════════════

@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("typed,stored", [
    ("2% (min $25,000)", "2% (min $25,000)"), ("5% (EQ)", "5% (EQ)"),
    ("2% (subject to $25,000 minimum)", "2% (subject to $25,000 minimum)"),
    ("(2% of TIV) per building", "(2% of TIV) per building"), ("2% (of TIV).", "2% (of TIV)"),
    ("(2%)", "2%"), ("((2%))", "2%"), ("2%)", "2%"), ("(2%", "2%"), ('"2%"', "2%"),
    ("2%.", "2%"), ('("2% of TIV")', "2% of TIV"), ("  2 %  ", "2%")])
def test_a_percentage_statement_is_stored_with_its_brackets_balanced(fact, typed, stored):
    got = interpret_answer(fact, typed)
    assert (got.intent, got.value) == (VALUE, stored)
    assert stored.count("(") == stored.count(")")


def test_a_bracketed_statement_prints_balanced():
    saved = _apply(_session(), {WIND: "2% (min $25,000)"}, _q(WIND))
    assert _value(saved["facts"][WIND]) == "2% (min $25,000)"
    assert saved["generated_forms"]["ACORD_28"]["field_state"][WIND_BOX] == "2% (min $25,000)"


# ══ 6. A dollar amount before its percentage is not read as dollars ══════════

@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("typed", ["$25,000 or 2%", "$10,000 min / 2%", "$25,000 minimum, 2% of TIV",
                                   "greater of $25,000 or 2%", "$2,000 (1%)", "$25,000 / 2%",
                                   "$25,000 or ½%"])
def test_the_bare_dollar_figure_is_never_stored(fact, typed):
    got = interpret_answer(fact, typed)
    assert got.intent == UNKNOWN and not got.accepted and got.value == ""
    assert "dollar amount or a percentage" in got.message
    assert arq._normalize_amount_or_percent(typed) is None
    assert not _validate_producer_answer(fact, typed)[0]
    val, why = arq._clean_answer_ex(typed, fact)
    assert why == "Could not read this as a dollar amount or a percentage"


@pytest.mark.parametrize("fact", CLASS)
def test_a_percentage_first_statement_and_a_dollar_amount_read_as_before(fact):
    assert interpret_answer(fact, "2% / $25,000 minimum").value == "2% / $25,000 minimum"
    assert interpret_answer(fact, "2% or $25,000, whichever is greater").value == \
        "2% or $25,000, whichever is greater"
    assert interpret_answer(fact, "$25,000").value == "25000"
    assert interpret_answer(fact, "$25,000 per occurrence").value == "25000"    # the currency door


def test_a_client_dollar_or_percent_answer_writes_no_bare_figure():
    saved = _apply(_session(), {WIND: "$25,000 or 2%", QUAKE: "$25,000 or 2%"}, _q(WIND) + _q(QUAKE))
    for fact in CLASS:
        assert _value(saved["facts"].get(fact)) in (None, "")
    s28 = saved["generated_forms"]["ACORD_28"]["field_state"]
    s160 = saved["generated_forms"]["ACORD_160"]["field_state"]
    assert not str(s28.get(WIND_BOX) or "").strip()
    assert not str(s160.get(EQ_AMOUNT) or "").strip() and not str(s160.get(EQ_PERCENT) or "").strip()


def test_mentions_a_percentage():
    for v in ("$25,000 or 2%", "2,5 percent", "2%", "1-2%", "$25,000 or ½%", "1 PCT", "2 per cent"):
        assert mentions_a_percentage(v), v
    for v in ("$2,500", "2 per month", "2500", "percent", "50 percentage points", None, 2, ["2%"]):
        assert not mentions_a_percentage(v), v


# ══ 8. A fraction is one figure ══════════════════════════════════════════════

@pytest.mark.parametrize("raw,number,text,plain", [
    ("1-1/2%", 1.5, "1.5%", True), ("1 1/2%", 1.5, "1.5%", True), ("1  1/2%", 1.5, "1.5%", True),
    ("1½%", 1.5, "1.5%", True), ("1 ½%", 1.5, "1.5%", True), ("½%", 0.5, "0.5%", True),
    ("1/2%", 0.5, "0.5%", True), ("2 1/2 percent", 2.5, "2.5%", True), ("3/4 pct", 0.75, "0.75%", True),
    ("1/8%", 0.125, "0.125%", True), ("1/64%", 0.015625, "0.015625%", True),
    ("2-1/2% of TIV", 2.5, "2.5% of TIV", False), ("Wind/Hail 1-1/2%", 1.5, "Wind/Hail 1.5%", False),
    ("-1/2%", -0.5, "-0.5%", True)])
def test_a_fraction_is_read_as_one_figure(raw, number, text, plain):
    got = stated_percentage(raw)
    assert got is not None and (got["number"], got["text"], got["plain"]) == (number, text, plain)


@pytest.mark.parametrize("raw", ["1-2%", "1/3%", "⅓%", "80/90%", "3/2%", "1/0%", "0/2%",
                                 "12/31/2025", "1/128%", "1-1/2", "1½½%", "Location 1: 2%"])
def test_no_fraction_is_read_that_is_not_one(raw):
    assert stated_percentage(raw) is None


@pytest.mark.parametrize("value,percent_box,printed_28", [
    ("1-1/2%", "1.5", "1.5%"), ("1 1/2%", "1.5", "1.5%"), ("1½%", "1.5", "1.5%"),
    ("1/2%", "0.5", "0.5%"), ("2 1/2 percent", "2.5", "2.5%")])
def test_a_fractional_percentage_prints_in_the_percent_box(value, percent_box, printed_28):
    mapped, conf = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped[EQ_PERCENT] == percent_box and conf[EQ_PERCENT] == "filled"
    assert mapped.get(EQ_AMOUNT) is None                                 # never "$ 1-1/2%"
    mapped28, _ = _stamp("ACORD_28", {"applicant_name": "Acme LLC", WIND: value})
    assert mapped28[WIND_BOX] == printed_28


@pytest.mark.parametrize("fact", CLASS)
def test_a_person_s_fractional_percentage_is_an_answer(fact):
    assert interpret_answer(fact, "1-1/2%").value == "1.5%"
    assert arq._normalize_amount_or_percent("1 1/2%") == "1.5%"
    assert _validate_producer_answer(fact, "1½%") == (True, "")


# ══ 12. One composite deductible printed two ways is one value ═══════════════

_COMPOSITE_SAME = [
    (WIND, "2% subject to $25,000 minimum", "$25,000 minimum or 2%, whichever is greater"),
    (WIND, "2% of TIV ($25,000 min)", "$25,000 min / 2% of TIV"),
    (WIND, "Location 1: Windstorm or Hail 2% subject to $25,000 minimum", "2% subject to $25,000 minimum"),
    (QUAKE, "5% / $50,000 minimum", "$50,000 minimum, 5%"),
    ("total_revenue", "$2,000,000 (60% commercial)", "60% commercial / $2,000,000"),
    ("property_building_value", "$1,250,000 90% coinsurance", "90% coinsurance $1,250,000"),
    ("total_policy_premium", "$10,663 (25% MEP)", "25% minimum earned, $10,663"),
]
_COMPOSITE_DIFFERENT = [
    ("2% Wind/Hail; 5% Named Storm", "5% Wind/Hail; 2% Named Storm"),    # the figures swap meaning
    ("2%", "$2"), ("2% / $25,000 minimum", "$25,000 minimum / 5%"),
    ("2% / $25,000 minimum", "$50,000 minimum / 2%"), ("2% / $25,000 minimum", "2% / $50,000 minimum"),
    ("Location 1: 2% subject to $25,000 min", "5% subject to $25,000 min"), ("2%", "$2,000"),
]


@pytest.mark.parametrize("fact,a,b", _COMPOSITE_SAME)
def test_a_composite_deductible_printed_in_another_order_is_the_same(fact, a, b):
    assert verdict(fact, a, b) == SAME and verdict(fact, b, a) == SAME
    if fact in CLASS:
        assert not _picker_rows(fact, [a, b])                            # no Data Consistency row


@pytest.mark.parametrize("fact", CLASS)
@pytest.mark.parametrize("a,b", _COMPOSITE_DIFFERENT)
def test_composites_that_state_different_figures_stay_different(fact, a, b):
    assert verdict(fact, a, b) == DIFFERENT and verdict(fact, b, a) == DIFFERENT
    rows = _picker_rows(fact, [a, b])
    assert rows and rows[0]["status"] == "conflict"


def test_a_client_composite_against_the_documents_reordered_one_is_not_held():
    env = {"value": "$25,000 minimum or 2%, whichever is greater", "source": "ai"}
    assert not arq._client_answer_conflicts_with_source(
        WIND, env, env["value"], "2% subject to $25,000 minimum")


def test_the_residual_a_reordered_list_of_several_percentages_still_asks():
    # Fails toward asking (accepted by the review): the first percentages differ.
    assert verdict(WIND, "2% Wind/Hail; 5% Named Storm", "5% Named Storm; 2% Wind/Hail") == DIFFERENT


# ══ 13. "$2", "2" and "2%" are judged the same way in every order ════════════

@pytest.mark.parametrize("order", list(itertools.permutations(["$2", "2", "2%"])))
def test_the_verdict_does_not_depend_on_document_order(order):
    assert compare(WIND, list(order)).is_conflict
    rows = _picker_rows(WIND, list(order))
    assert rows and rows[0]["status"] == "conflict"


def test_the_dollar_tag_is_only_on_a_figure_a_percentage_can_share():
    assert comparison_key(WIND, "$2") != comparison_key(WIND, "2")
    assert comparison_key(WIND, "$2.50") != comparison_key(WIND, "2.5")
    assert comparison_key(WIND, "$2,000") == comparison_key(WIND, "2000")
    assert comparison_key(WIND, "$100") != comparison_key(WIND, "100")
    assert comparison_key(WIND, "$101") == comparison_key(WIND, "101")
    assert verdict(WIND, "$2", "2") == SAME and verdict(WIND, "2", "2%") == SAME
    assert verdict(WIND, "$2", "2%") == DIFFERENT
    # a fact that is not money keeps its key exactly
    assert comparison_key("coinsurance_percentage", "$2") == normalize_value("coinsurance_percentage", "$2")


# ══ 16. The old page's "$2 %" is the percentage 2% ═══════════════════════════

@pytest.mark.parametrize("raw,text,plain", [("$2 %", "2%", True), ("$1.50 %", "1.5%", True),
                                            ("$2 % of TIV", "2% of TIV", False), ("$ 2%", "2%", True)])
def test_a_dollar_sign_before_a_percentage_is_dropped(raw, text, plain):
    got = stated_percentage(raw)
    assert (got["text"], got["plain"]) == (text, plain)


def test_an_old_draft_s_dollar_percentage_is_stored_and_printed_as_the_percentage():
    for fact in CLASS:
        assert arq._clean_answer_ex("$2 %", fact) == ("2%", "")
    saved = _apply(_session(), {WIND: "$2 %", QUAKE: "$2 %"}, _q(WIND) + _q(QUAKE))
    assert _value(saved["facts"][WIND]) == "2%" and _value(saved["facts"][QUAKE]) == "2%"
    assert saved["generated_forms"]["ACORD_28"]["field_state"][WIND_BOX] == "2%"
    assert saved["generated_forms"]["ACORD_160"]["field_state"][EQ_PERCENT] == "2"
    assert verdict(WIND, "2%", "$2 %") == SAME


# ══ The browser twins agree with the server on every shared vector ═══════════

_WORD_VECTORS = _BOX_WORDS + _NOT_WORDS + ["NONE!", "n.a.", "Not  Covered", "wind/hail excluded",
                                           "see the dec", "non applicable", "2 none", "nonee"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_new_browser_twins_match_the_server(tmp_path):
    vectors = list(dict.fromkeys(_JS_VECTORS + _WORD_VECTORS))
    script = tmp_path / "twins.mjs"
    script.write_text(
        f"import * as F from {json.dumps((FRONT / 'utils' / 'answerFormats.js').as_uri())};\n"
        f"const vectors = {json.dumps(vectors)};\n"
        "console.log(JSON.stringify(vectors.map((v) => {\n"
        "  const p = F.percentStatement(v);\n"
        "  return [p ? [p.number, p.figure, p.text, p.plain, p.before, p.after] : null,\n"
        "          F.mentionsPercentage(v), F.isAmountBoxConvention(v),\n"
        "          !F.normalizeAmountOrPercent(v.trim()) && !F.isAmountBoxConvention(v.trim())];\n"
        "})));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    for v, (pct, mentions, words, page_blocks) in zip(vectors, json.loads(run.stdout)):
        py = stated_percentage(v)
        assert pct == ([py["number"], py["figure"], py["text"], py["plain"], py["before"], py["after"]]
                       if py else None), v
        assert mentions == mentions_a_percentage(v), v
        assert words == is_amount_box_convention(v), v
        if not page_blocks and v.strip():
            # what the page sends, the server never refuses (`_blocks_submit`'s rule)
            for fact in CLASS:
                assert arq._clean_answer_ex(v, fact)[1] == "", (v, fact)


_FUZZ_ATOMS = ["1", "2", "5", "0", "12", "25", "100", "1,000", "25,000", ".", ",", "/", "-", "−", "–",
               " ", "  ", "%", " %", "percent", " percent", "per cent", "pct", "pct.", "$", "½", "¼",
               "⅓", "1/2", "1-1/2", "1 1/2", "a", "A", "of TIV", "min", "(", ")", "or", "None", "no",
               "not", "covered", "k", "M", "é", "_", " ", "Excluded", "same as AOP", "see",
               "schedule", "lots", "'", "\"", "n/a"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_twins_agree_on_seeded_random_answers(tmp_path):
    """4,000 seeded random answers built from the characters these readers
    care about: every twin returns exactly what its server half returns."""
    import random
    rng = random.Random(20261022)
    vectors = sorted({"".join(rng.choice(_FUZZ_ATOMS) for _ in range(rng.randint(1, 6)))
                      for _ in range(4000)})
    script = tmp_path / "fuzz.mjs"
    script.write_text(
        f"import * as F from {json.dumps((FRONT / 'utils' / 'answerFormats.js').as_uri())};\n"
        f"const vectors = {json.dumps(vectors)};\n"
        "console.log(JSON.stringify(vectors.map((v) => {\n"
        "  const p = F.percentStatement(v);\n"
        "  return [p ? [p.number, p.figure, p.text, p.plain, p.before, p.after] : null,\n"
        "          F.mentionsPercentage(v), F.normalizeCurrency(v), F.normalizeAmountOrPercent(v),\n"
        "          F.isAmountBoxConvention(v)];\n"
        "})));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    bad = []
    for v, js in zip(vectors, json.loads(run.stdout)):
        py = stated_percentage(v)
        got = [[py["number"], py["figure"], py["text"], py["plain"], py["before"], py["after"]] if py else None,
               mentions_a_percentage(v), arq._normalize_currency(v), arq._normalize_amount_or_percent(v),
               is_amount_box_convention(v)]
        if got != js:
            bad.append((v, got, js))
    assert not bad, bad[:5]
