"""Review of Z33-PERCENT, round C (22 Oct 2026): six defects the refuters of
lanes A and B found in those fixes.

* 1 (MEDIUM) "$25,000 / 2%" was read as one fraction / range run carrying the
             % unit, so ACORD 160's "%" box printed it. A run never starts at a
             "$" figure or a figure with a thousands separator.
* 2 (MEDIUM) "1-1/2%" vs "1.5%" was DIFFERENT: `money_amounts` read 1 and 2.
* 3 (LOW)    "½%" keyed "" before the percentage branch, so "½%" vs "5%" was
             no conflict.
* 4 (LOW)    "Not available" passed the amount-box convention on both twins,
             while the semantics door reads it as uncertainty and drops it.
* 5 (LOW)    "-$2%" became "-2%", "US$2%" "US2%".
* 6 (LOW)    fractions typed in the 160 "%" box were not promoted.
"""
import copy
import json
from pathlib import Path

import pytest

import services.pdf_service as ps
from services import answer_semantics as sem
from services import fact_comparison as fc
from services import fact_equivalence as fe
from services.normalization import stated_percentage

BACKEND = Path(__file__).resolve().parents[1]
QUAKE = "property_deductible_earthquake"
WIND = "property_deductible_wind"
EQ_AMOUNT = "CommercialPropertyCoverage_Earthquake_DeductibleAmount_A"
EQ_PERCENT = "CommercialPropertyCoverage_Earthquake_DeductiblePercent_A"


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) else raw


def _stamp_160(value):
    mapped, _conf = ps.map_facts_to_form(copy.deepcopy({QUAKE: value}), _schema("ACORD_160"),
                                         "ACORD_160", "", allow_llm=False)
    return _v(mapped.get(EQ_AMOUNT)), _v(mapped.get(EQ_PERCENT))


# ══ 1. A dollar figure never starts a percentage run ═══════════════════════════

@pytest.mark.parametrize("value", ["$25,000 / 2%", "$5,000 - 2%", "$100,000 / 5%",
                                   "$25,000 / 2% of TIV per building", "$ 25,000/2%",
                                   "25,000/2%", "100,000 - 2%"])
def test_a_dollar_figure_joined_to_a_percentage_is_not_one_run(value):
    assert ps._unread_percentage(value) is None
    assert not ps.amount_or_percent_box_value(EQ_PERCENT, value, _schema("ACORD_160"))


@pytest.mark.parametrize("value", ["$25,000 / 2%", "$100,000 / 5%"])
def test_160_prints_the_whole_dollar_statement_in_the_dollar_box(value):
    amount, percent = _stamp_160(value)
    assert percent in (None, "")
    assert amount == value.lstrip("$")          # the whole statement, as before


@pytest.mark.parametrize("value", ["1-2%", "1-1/2 percent of TIV"])
def test_an_unread_percentage_without_a_dollar_figure_still_reads(value):
    if stated_percentage(value) is None:
        assert ps._unread_percentage(value) is not None


# ══ 2. The same percentage, written as a fraction, is the same value ══════════

@pytest.mark.parametrize("a,b", [("1-1/2%", "1.5%"), ("1 1/2%", "1.5%"), ("2 1/2%", "2.5%"),
                                 ("1/2%", "0.5%"), ("½%", "0.5%"), ("1-1/2%", "1.5% of TIV"),
                                 ("Windstorm or Hail 1-1/2%", "1.5%")])
def test_the_same_percentage_is_same(a, b):
    assert fe.same_fact(WIND, a, b) == fe.SAME
    assert fe.same_fact(WIND, b, a) == fe.SAME


@pytest.mark.parametrize("a,b", [("1-1/2%", "2.5%"), ("½%", "5%"), ("2%", "$2"),
                                 ("2% subject to $25,000 minimum", "2% subject to $50,000 minimum")])
def test_different_values_stay_different(a, b):
    assert fe.same_fact(WIND, a, b) != fe.SAME


# ══ 3. A glyph-only percentage has a key ═══════════════════════════════════════

def test_a_glyph_only_percentage_is_keyed_by_its_figure():
    assert fc.comparison_key(QUAKE, "½%") == "0.5%"
    assert fc.comparison_key(QUAKE, "¼%") == "0.25%"
    assert fc.comparison_key(QUAKE, "½%") != fc.comparison_key(QUAKE, "5%")
    assert fc.comparison_key(QUAKE, "½%") == fc.comparison_key(QUAKE, "0.5%")
    assert fc.comparison_key(QUAKE, "") == ""
    assert fc.comparison_key(QUAKE, None) == ""


def test_a_glyph_only_percentage_against_another_is_a_conflict():
    assert fe.same_fact(QUAKE, "½%", "5%") == fe.DIFFERENT


# ══ 4. Uncertainty is no box convention ═══════════════════════════════════════

@pytest.mark.parametrize("word", ["Not available", "not available", "Not  Available"])
def test_not_available_is_not_a_box_convention(word):
    assert not sem.is_amount_box_convention(word)
    assert sem.interpret_answer(QUAKE, word).intent == sem.UNKNOWN


def test_every_convention_phrase_the_box_takes_the_door_takes():
    vocab = sorted(sem._BOX_VOCABULARY)
    for x in vocab:
        for y in vocab:
            t = f"{x} {y}".capitalize()
            if sem.is_amount_box_convention(t):
                assert sem.interpret_answer(QUAKE, t).intent != sem.UNKNOWN, t


# ══ 5. A sign or currency letters before the "$" refuse ═══════════════════════

@pytest.mark.parametrize("value", ["-$2%", "–$2%", "US$2%", "us$ 2%", "CA$2 % of TIV", "Wind -$2%"])
def test_a_sign_or_currency_letters_before_the_dollar_refuse(value):
    assert stated_percentage(value) is None
    assert ps._unread_percentage(value) is None


@pytest.mark.parametrize("value,text", [("$2 %", "2%"), ("$ 2%", "2%"),
                                        ("Deductible $2%", "Deductible 2%"),
                                        ("$-2%", "-2%")])
def test_a_plain_dollar_before_the_figure_is_still_dropped(value, text):
    assert stated_percentage(value)["text"] == text


# ══ 6. Fractions typed in the 160 "%" box are percentages ═════════════════════

@pytest.mark.parametrize("typed,written", [("1-1/2", "1.5%"), ("1 1/2", "1.5%"), ("1½", "1.5%"),
                                           ("½", "0.5%"), ("2", "2%"), (".5", "0.5%"),
                                           ("2.5", "2.5%"), ("100", "100%")])
def test_a_fraction_in_the_percent_box_is_that_percentage(typed, written):
    assert ps.box_fact_value(EQ_PERCENT, typed, QUAKE) == written
    assert ps.box_fact_value(EQ_AMOUNT, typed, QUAKE) == typed


@pytest.mark.parametrize("typed", ["25000", "101", "-2", "$2", "abc 2", "2 of TIV", "lots"])
def test_what_is_no_bare_share_writes_as_typed(typed):
    assert ps.box_fact_value(EQ_PERCENT, typed, QUAKE) == typed


def test_a_fraction_saved_in_the_percent_box_prints_there_again():
    stored = ps.box_fact_value(EQ_PERCENT, "1-1/2", QUAKE)
    amount, percent = _stamp_160(stored)
    assert amount in (None, "")
    assert percent and "1.5" in percent
