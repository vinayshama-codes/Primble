"""Review of Z33-PERCENT, lane B (22 Oct 2026): printing and the answer apply.

The adversarial review of the percentage-deductible change confirmed six
defects in how a stated wind / earthquake deductible reaches its boxes:

* 7 (HIGH)  a worded deductible ("2% per building") was stamped into the box
            its fact now owns and then emptied by Guard 3's prose rule, so the
            box printed nothing and gap fill was never asked. A box printing its
            OWN fact's statement that names a figure is now exempt; a statement
            with no figure ("See schedule of deductibles") still is not.
* 8         a percentage the reader cannot read ("1-1/2%" before the reader
            learned fractions, a range "1-2%" still) went to ACORD 160's "$"
            box. It now prints in the percent box, before and after the reader
            change.
* 3         a client answer to a raw ACORD 160 box question printed in BOTH the
            "$" and the "%" box; and the scan asked the blank half of a stated
            deductible. The raw stamp now prints what the door prints for the
            answer, and the blank half is never a question.
* 9         after forms, an answer printed in one box of the pair while an AI
            reading stayed in the other. Both re-stamp doors clear that stale
            half - never a box a person filled.
* 10        Field QA compared "2% of TIV" with the lone "2" cut out of it.
* 11        the editor's bare-figure rule wrote "25000" in the "%" box as
            "25000%".
"""
import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import repositories.session_repository as sr
import services.arq_service as arq
import services.pdf_service as ps

BACKEND = Path(__file__).resolve().parents[1]

WIND, QUAKE = "property_deductible_wind", "property_deductible_earthquake"
EQ_AMOUNT = "CommercialPropertyCoverage_Earthquake_DeductibleAmount_A"
EQ_PERCENT = "CommercialPropertyCoverage_Earthquake_DeductiblePercent_A"
WIND_BOX = "CommercialPropertyCoverage_WindHail_DeductibleAmount_A"
_PEOPLE = ("producer", "client_arq")


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _value(raw):
    return raw.get("value") if isinstance(raw, dict) else raw


def _stamp(fid, facts, **kw):
    report = []
    kw.setdefault("allow_llm", False)
    mapped, conf = ps.map_facts_to_form(copy.deepcopy(facts), _schema(fid), fid,
                                        guard_report=report, **kw)
    return mapped, conf, report


def _guard_reasons(report, box):
    return [g.get("reason") for g in report if g.get("field") == box]


def _with_ai(fid, ai, raw):
    """A generated form whose deductible box an AI reading filled (no fact)."""
    grounding = {k: raw for k in ai}
    mapped, conf, _ = _stamp(fid, {"applicant_name": "Acme LLC"}, allow_llm=True, raw_text=raw,
                             pre_filled_gpt={"filled_values": ai, "question_grounding": grounding})
    for box, val in ai.items():
        assert mapped.get(box) not in (None, ""), (box, val)       # the AI value stands
        assert conf.get(box) not in _PEOPLE
    return {"schema": _schema(fid), "field_state": dict(mapped), "mapped": dict(mapped),
            "confidence": dict(conf)}


def _generated(fid, facts):
    mapped, conf, report = _stamp(fid, facts)
    return {"schema": _schema(fid), "field_state": dict(mapped), "mapped": dict(mapped),
            "confidence": dict(conf), "guard_blanks": report}


def _client_apply(generated, facts, answers, questions):
    session = {"generated_forms": generated, "facts": copy.deepcopy(facts),
               "flags": {"has_property_coverage": True}}
    row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
           "answers": answers, "questions": questions}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(copy.deepcopy(payload))

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=row)), \
         patch("repositories.session_repository.get_processing_session",
               AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    return saved


def _box_question(box, fid="ACORD_160"):
    return [{"field_name": box, "question": "How much would you pay out of pocket?",
             "form_ids": [fid], "field_type": "amount_or_percent"}]


def _producer_apply(field, value, facts, generated):
    store = {"facts": copy.deepcopy(facts), "flags": {}, "generated_forms": generated, "docs": []}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        store.update(copy.deepcopy(payload))
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_producer_answer_to_session("sid", field, value))
    assert ok
    return store


def _pair(state):
    return (str(state.get(EQ_AMOUNT) or "").strip(), str(state.get(EQ_PERCENT) or "").strip())


def _generation_pair(facts):
    mapped, _c, _r = _stamp("ACORD_160", facts)
    return _pair(mapped)


def _z33_reader(value):
    """`normalization.stated_percentage` as Z33-PERCENT shipped it - before it
    learned fractions - so the printing door is proven against both readers."""
    if value is None or isinstance(value, (bool, int, float, list, dict)):
        return None
    s = str(value).strip()
    m = re.search(r"(?<![\w.,])(?P<sign>[-−–])?"
                  r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)", s)
    if not m:
        return None
    unit = re.compile(r"\s*(?:%|percent\b|per\s*cent\b|pct\b\.?)", re.I).match(s, m.end("num"))
    if not unit:
        return None
    number = float(m.group("num").replace(",", ""))
    if m.group("sign"):
        number = -number
    figure = str(int(number)) if number.is_integer() else f"{number:.6f}".rstrip("0").rstrip(".")
    before, after = s[:m.start()], s[unit.end():]
    return {"number": number, "text": re.sub(r"\s+", " ", f"{before}{figure}%{after}").strip(),
            "plain": not before.strip() and not after.strip()}


# ══ Finding 7 (HIGH): a worded deductible prints in the box its fact owns ═══

_WORDED_PERCENT = ["2% per building", "2% of TIV per building", "5% of building value",
                   "2 percent of the building limit", "Wind/Hail: 2% per building"]
_WORDED_DOLLARS = [("$25,000 per occurrence", "$25,000", "25,000"),
                   ("$5,000 per occurrence", "$5,000", "5,000")]


@pytest.mark.parametrize("value", _WORDED_PERCENT)
def test_a_worded_percentage_prints_whole_in_its_own_box(value):
    expected = ps.stated_percentage(value)["text"]
    mapped, conf, report = _stamp("ACORD_28", {"applicant_name": "Acme LLC", WIND: value})
    assert mapped[WIND_BOX] == expected and conf[WIND_BOX] == "filled"
    assert not _guard_reasons(report, WIND_BOX)
    mapped, conf, report = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped[EQ_PERCENT] == expected and conf[EQ_PERCENT] == "filled"
    assert mapped.get(EQ_AMOUNT) is None                               # never split
    assert not _guard_reasons(report, EQ_PERCENT)


@pytest.mark.parametrize("value,on_28,on_160", _WORDED_DOLLARS)
def test_a_worded_dollar_deductible_prints_its_amount(value, on_28, on_160):
    mapped, conf, report = _stamp("ACORD_28", {"applicant_name": "Acme LLC", WIND: value})
    assert mapped[WIND_BOX] == on_28 and conf[WIND_BOX] == "filled"
    assert not _guard_reasons(report, WIND_BOX)
    mapped, conf, report = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped[EQ_AMOUNT] == on_160 and mapped.get(EQ_PERCENT) is None
    assert not _guard_reasons(report, EQ_AMOUNT)


@pytest.mark.parametrize("value", ["See schedule of deductibles", "Per schedule on file",
                                   "See schedule CP 03 21"])
def test_a_statement_that_names_no_figure_still_never_prints(value):
    for fid, fact, box in (("ACORD_28", WIND, WIND_BOX), ("ACORD_160", QUAKE, EQ_AMOUNT)):
        mapped, _c, report = _stamp(fid, {"applicant_name": "Acme LLC", fact: value})
        assert mapped.get(box) is None, (fid, value)
        assert _guard_reasons(report, box) == ["PROSE_IN_NUMBER_OR_DATE_BOX"], (fid, value)


def test_an_ai_reading_never_takes_the_exemption():
    """The exemption is for the box's OWN fact; a gap-fill answer of the same
    shape is still prose in a number box (the fact states nothing)."""
    schema = _schema("ACORD_28")
    mapped = {WIND_BOX: "2% per building"}
    ps._enforce_post_fill_guards(mapped, schema, {"_form_id": "ACORD_28"},
                                 gpt_filled_set={WIND_BOX})
    assert mapped[WIND_BOX] is None
    # ...nor when the AI wrote it beside a stated fact (it is not the door's value)
    mapped = {WIND_BOX: "2% per building"}
    ps._enforce_post_fill_guards(mapped, schema, {"_form_id": "ACORD_28", WIND: "5%"},
                                 gpt_filled_set=set())
    assert mapped[WIND_BOX] is None


def test_the_exemption_is_only_the_doors_own_value_in_its_own_box():
    schema = _schema("ACORD_160")
    facts = {"_form_id": "ACORD_160", QUAKE: "2% per building"}
    # the amount box is the blank half: the statement is not its value
    mapped = {EQ_AMOUNT: "2% per building", EQ_PERCENT: "2% per building"}
    ps._enforce_post_fill_guards(mapped, schema, facts, gpt_filled_set=set())
    assert mapped[EQ_AMOUNT] is None and mapped[EQ_PERCENT] == "2% per building"
    # a box no amount-or-percent fact prints keeps the prose rule (the 28's
    # EARTH MOVEMENT deductible is another deductible, read off the documents)
    other = "CommercialPropertyCoverage_EarthMovement_DeductibleAmount_A"
    assert ps._is_numeric_or_date_field(other) and not ps.amount_or_percent_fact_of(other)
    mapped = {other: "2% per building"}
    ps._enforce_post_fill_guards(mapped, _schema("ACORD_28"),
                                 {"_form_id": "ACORD_28", WIND: "2% per building",
                                  QUAKE: "2% per building"},
                                 gpt_filled_set=set())
    assert mapped[other] is None


def test_after_forms_the_worded_deductible_survives_the_restamp_guards():
    gen = {"ACORD_28": _generated("ACORD_28", {"applicant_name": "Acme LLC"})}
    after = {"applicant_name": "Acme LLC", WIND: {"value": "2% per building", "source": "ai"}}
    touched = arq._restamp_changed_boxes(gen, {"applicant_name": "Acme LLC"}, after,
                                         own_keys=set(), provenance="filled")
    assert touched == ["ACORD_28"]
    assert gen["ACORD_28"]["field_state"][WIND_BOX] == "2% per building"
    # the answer door prints the same, and generation agrees
    gen = {"ACORD_28": _generated("ACORD_28", {"applicant_name": "Acme LLC"})}
    arq._restamp_canonical_into_forms(gen, WIND, after, provenance="producer")
    assert gen["ACORD_28"]["field_state"][WIND_BOX] == "2% per building"
    mapped, _c, _r = _stamp("ACORD_28", after)
    assert mapped[WIND_BOX] == "2% per building"


async def _no_humanize(_names):
    return {}


def _questions(facts, generated):
    present, _ = arq._backfill_and_resolve_present(generated, facts)
    with patch.object(arq, "_humanize_fields_with_openai", _no_humanize):
        return asyncio.run(arq.generate_arq_questions(
            facts=facts, flags={"has_property_coverage": True}, generated_forms=generated,
            hard_stops=[], soft_stops=[], session_docs=[], present_fact_keys=present))


def _deductible_questions(questions, boxes, fact):
    return [q for q in questions if q.get("field_name") in (*boxes, fact)]


def test_a_stated_worded_deductible_is_not_asked_again():
    facts = {"applicant_name": "Acme LLC", WIND: {"value": "2% per building", "source": "ai"}}
    gen = {"ACORD_28": _generated("ACORD_28", facts)}
    assert gen["ACORD_28"]["field_state"][WIND_BOX] == "2% per building"
    present, _ = arq._backfill_and_resolve_present(gen, facts)
    assert WIND in present
    assert not _deductible_questions(_questions(facts, gen), (WIND_BOX,), WIND)


# ══ Finding 8: a percentage the reader cannot read is still a percentage ═══

@pytest.mark.parametrize("value,percent_box", [("1-2%", "1-2"), ("1 - 2%", "1 - 2"),
                                               ("1-2% of TIV", "1-2% of TIV"),
                                               ("1-2 percent", "1-2")])
def test_a_range_never_prints_in_the_dollar_box(value, percent_box):
    assert ps.stated_percentage(value) is None                          # the reader refuses it
    mapped, conf, report = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped.get(EQ_AMOUNT) is None and mapped[EQ_PERCENT] == percent_box
    assert conf[EQ_PERCENT] == "filled" and not _guard_reasons(report, EQ_PERCENT)
    mapped, _c, _r = _stamp("ACORD_28", {"applicant_name": "Acme LLC", WIND: value})
    assert not str(mapped[WIND_BOX]).startswith("$")                    # the 28: as stated


_FRACTIONS = [("1-1/2%", "1-1/2"), ("1 1/2%", "1 1/2"), ("1½%", "1½"), ("1/2%", "1/2"),
              ("2 1/2 percent", "2 1/2")]


@pytest.mark.parametrize("value,figure", _FRACTIONS)
def test_before_the_reader_reads_fractions_they_print_in_the_percent_box(value, figure, monkeypatch):
    monkeypatch.setattr(ps, "stated_percentage", _z33_reader)
    assert _z33_reader(value) is None                                   # the old reader refused it
    schema = _schema("ACORD_160")
    assert ps.amount_or_percent_box_value(EQ_AMOUNT, value, schema) is None
    assert ps.amount_or_percent_box_value(EQ_PERCENT, value, schema) == figure
    mapped, _c, _r = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped.get(EQ_AMOUNT) is None and mapped[EQ_PERCENT] == figure
    # with words, the whole statement prints in the percent box and survives Guard 3
    worded = f"{value} per building"
    mapped, _c, report = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: worded})
    assert mapped.get(EQ_AMOUNT) is None and mapped[EQ_PERCENT].endswith("% per building")
    assert not _guard_reasons(report, EQ_PERCENT)


@pytest.mark.parametrize("value", [v for v, _f in _FRACTIONS])
def test_after_the_reader_reads_fractions_the_door_follows_it(value):
    pct = ps.stated_percentage(value)
    if pct is None:
        pytest.skip("this reader does not read the fraction yet (the test above covers it)")
    mapped, _c, _r = _stamp("ACORD_160", {"applicant_name": "Acme LLC", QUAKE: value})
    assert mapped.get(EQ_AMOUNT) is None and mapped[EQ_PERCENT] == pct["text"][:-1]


@pytest.mark.parametrize("value", ["$25,000 or 2%", "25,000 or 2%", "$2,500", "2500",
                                   "1 building at 2%"])
def test_the_first_figure_still_decides_a_dollar_statement(value):
    schema = _schema("ACORD_160")
    assert ps._unread_percentage(value) is None
    assert ps.amount_or_percent_box_value(EQ_AMOUNT, value, schema) == value
    assert ps.amount_or_percent_box_value(EQ_PERCENT, value, schema) is None


@pytest.mark.parametrize("value", ["A1-1/2%", "x1-2%", "_1-2%", "No.1-2%"])
def test_a_figure_glued_to_a_word_is_not_read_as_a_percentage(value):
    assert ps._unread_percentage(value) is None
    assert ps.stated_percentage(value.replace("-2", "").replace("-1/2", "")) is None   # as the reader


def test_a_decimal_range_is_still_a_percentage_statement():
    assert ps._unread_percentage("2.1-2%") == {"text": "2.1-2%", "figure": "2.1-2", "plain": True}


def test_the_unread_reader_writes_the_unit_as_the_reader_does():
    got = ps._unread_percentage("1-2 percent of TIV")
    assert got == {"text": "1-2% of TIV", "figure": "1-2", "plain": False}
    assert ps._unread_percentage("1-2 pct") == {"text": "1-2%", "figure": "1-2", "plain": True}
    for readable in ("2%", "2% of TIV", "0.5 percent"):
        assert ps._unread_percentage(readable) is None                  # the reader's own


# ══ Finding 3: a raw box question never prints in both boxes ═══════════════

@pytest.mark.parametrize("asked,typed,pair", [
    (EQ_AMOUNT, "2%", ("", "2")),
    (EQ_AMOUNT, "2% of TIV per building", ("", "2% of TIV per building")),
    (EQ_AMOUNT, "5000", ("5,000", "")),
    (EQ_PERCENT, "$25,000", ("25,000", "")),
    (EQ_PERCENT, "2%", ("", "2")),
    (EQ_PERCENT, "2", ("", "2")),          # a bare 2 is 2% (owner, 22 Oct, review D)
])
def test_a_client_answer_to_a_raw_160_box_prints_in_one_box_only(asked, typed, pair):
    facts = {"applicant_name": "Acme LLC"}
    cleaned, _why = arq._clean_answer_ex(typed, asked)
    saved = _client_apply({"ACORD_160": _generated("ACORD_160", facts)}, facts,
                          {asked: cleaned}, _box_question(asked))
    form = saved["generated_forms"]["ACORD_160"]
    assert _pair(form["field_state"]) == pair
    assert _generation_pair(saved["facts"]) == pair                     # what generation prints
    for box, shown in zip((EQ_AMOUNT, EQ_PERCENT), pair):
        if shown:
            assert form["confidence"][box] == "client_arq"
        else:
            assert form["confidence"].get(box) not in _PEOPLE           # a blank is nobody's
            assert box not in form.get("client_filled_fields", [])


def test_a_client_answer_replaces_an_ai_reading_in_the_box_it_was_asked_on():
    raw = "Earthquake deductible $25,000."
    gen = {"ACORD_160": _with_ai("ACORD_160", {EQ_AMOUNT: "25,000"}, raw)}
    facts = {"applicant_name": "Acme LLC"}
    saved = _client_apply(gen, facts, {EQ_AMOUNT: "2%"}, _box_question(EQ_AMOUNT))
    assert _pair(saved["generated_forms"]["ACORD_160"]["field_state"]) == ("", "2")


def test_an_absence_on_a_raw_box_keeps_its_blank_and_its_label():
    facts = {"applicant_name": "Acme LLC"}
    saved = _client_apply({"ACORD_160": _generated("ACORD_160", facts)}, facts,
                          {EQ_AMOUNT: "None"}, _box_question(EQ_AMOUNT))
    form = saved["generated_forms"]["ACORD_160"]
    assert _pair(form["field_state"]) == ("", "")
    assert form["confidence"][EQ_AMOUNT] == "explicit_no"


@pytest.mark.parametrize("asked", [EQ_AMOUNT, EQ_PERCENT])
@pytest.mark.parametrize("bad", ["200%", "-2%"])
def test_an_answer_the_door_reads_as_no_value_prints_nowhere(asked, bad):
    facts = {"applicant_name": "Acme LLC"}
    saved = _client_apply({"ACORD_160": _generated("ACORD_160", facts)}, facts,
                          {asked: bad}, _box_question(asked))
    assert _pair(saved["generated_forms"]["ACORD_160"]["field_state"]) == ("", "")
    assert not _value(saved["facts"].get(QUAKE))


def test_the_28_wind_box_still_takes_the_answer_as_before():
    facts = {"applicant_name": "Acme LLC"}
    saved = _client_apply({"ACORD_28": _generated("ACORD_28", facts)}, facts,
                          {WIND_BOX: "2%"}, _box_question(WIND_BOX, "ACORD_28"))
    form = saved["generated_forms"]["ACORD_28"]
    assert form["field_state"][WIND_BOX] == "2%" and form["confidence"][WIND_BOX] == "client_arq"


@pytest.mark.parametrize("stated,blank_half", [("$25,000", EQ_PERCENT), ("2%", EQ_AMOUNT),
                                               ("2% per building", EQ_AMOUNT)])
def test_the_blank_half_of_a_stated_deductible_is_never_asked(stated, blank_half):
    facts = {"applicant_name": "Acme LLC", QUAKE: {"value": stated, "source": "ai",
                                                  "confidence": "ai_high"}}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    assert not str(gen["ACORD_160"]["field_state"].get(blank_half) or "").strip()
    assert ps.amount_or_percent_blank_half(blank_half, {**facts, "_form_id": "ACORD_160"},
                                           _schema("ACORD_160"))
    asked = _deductible_questions(_questions(facts, gen), (EQ_AMOUNT, EQ_PERCENT), QUAKE)
    # Never the blank half, never a blank ask. An AI value no document prints
    # is an insurance-judgment SUGGESTION: it goes to the producer for review
    # (deselected, the client never sees it) showing the value under review
    # (Z37, 24 Oct 2026 - 160 now lists the earthquake deductible).
    assert all(q["field_name"] == QUAKE for q in asked)
    for q in asked:
        assert q.get("producer_review") and q.get("audience") == "producer"
        assert not q.get("default_selected")
        assert q.get("current_value") == stated


def test_with_no_deductible_stated_the_pair_is_asked_once():
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    asked = _deductible_questions(_questions(facts, gen), (EQ_AMOUNT, EQ_PERCENT), QUAKE)
    assert len(asked) == 1 and asked[0]["field_type"] == "amount_or_percent"


def test_only_a_box_with_a_percent_twin_on_its_own_form_is_ever_a_blank_half():
    """Swept over all 17 schemas: the 160's earthquake pair is the only pair;
    the 28's wind box, alone on its form, always prints the stated value."""
    for path in sorted((BACKEND / "forms_schemas").glob("*_schema.json")):
        fid = path.name.replace("_schema.json", "")
        schema = json.loads(path.read_text(encoding="utf-8"))
        for box in schema:
            fact = ps.amount_or_percent_fact_of(box)
            if not fact:
                continue
            halves = {v for v in ("2%", "$25,000")
                      if ps.amount_or_percent_blank_half(box, {fact: v, "_form_id": fid}, schema)}
            twin = ps._deductible_twin(box)
            if twin is None or twin[0] not in schema:
                assert not halves, (fid, box)
            else:
                assert len(halves) == 1, (fid, box)                     # exactly one value each way


# ══ Finding 9: after forms the answer and an AI reading never share the pair

@pytest.mark.parametrize("door", ["producer", "client"])
@pytest.mark.parametrize("ai,raw,answer,pair", [
    ({EQ_AMOUNT: "25,000"}, "Earthquake deductible $25,000.", "2%", ("", "2")),
    ({EQ_PERCENT: "2"}, "Earthquake deductible: 2% of the building value.", "$25,000",
     ("25,000", "")),
])
def test_an_answer_after_forms_clears_the_ai_reading_in_the_other_box(door, ai, raw, answer, pair):
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _with_ai("ACORD_160", ai, raw)}
    if door == "producer":
        store = _producer_apply(QUAKE, answer, facts, gen)
    else:
        store = _client_apply(gen, facts, {QUAKE: answer},
                              [{"field_name": QUAKE, "question": "q", "form_ids": ["ACORD_160"],
                                "field_type": "amount_or_percent"}])
    form = store["generated_forms"]["ACORD_160"]
    assert _pair(form["field_state"]) == pair
    assert _generation_pair(store["facts"]) == pair
    cleared = next(iter(ai))
    assert cleared not in form["confidence"] and cleared not in form.get("client_filled_fields", [])


# Z37 lane B (owner, 24 Oct): only a box the producer may have TYPED stays; a
# "client_arq" half was written by an earlier answer (the client has no editor)
# and is cleared - see tests/test_z37_lane_b.py.
@pytest.mark.parametrize("person", ("producer",))
def test_a_box_a_person_filled_is_never_cleared(person):
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _generated("ACORD_160", facts)}
    gen["ACORD_160"]["field_state"][EQ_AMOUNT] = "25,000"
    gen["ACORD_160"]["confidence"][EQ_AMOUNT] = person
    after = {**facts, QUAKE: {"value": "2%", "source": "producer"}}
    arq._restamp_canonical_into_forms(gen, QUAKE, after, provenance="producer")
    assert _pair(gen["ACORD_160"]["field_state"]) == ("25,000", "2")
    assert gen["ACORD_160"]["confidence"][EQ_AMOUNT] == person


def test_the_canonical_restamp_touches_only_the_answered_facts_pair():
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _with_ai("ACORD_160", {EQ_AMOUNT: "25,000"}, "Earthquake deductible $25,000.")}
    # an answer to another fact leaves the AI earthquake reading alone
    arq._restamp_canonical_into_forms(gen, "applicant_name", {**facts, "applicant_name": "Acme Two LLC"})
    assert gen["ACORD_160"]["field_state"][EQ_AMOUNT] == "25,000"


@pytest.mark.parametrize("ai,raw,after,pair", [
    ({EQ_AMOUNT: "25,000"}, "Earthquake deductible $25,000.", "2%", ("", "2")),
    ({EQ_PERCENT: "2"}, "Earthquake deductible: 2% of the building value.", "$25,000",
     ("25,000", "")),
])
@pytest.mark.parametrize("own", [set(), {QUAKE}])
def test_a_change_that_states_the_deductible_clears_the_stale_half(ai, raw, after, pair, own):
    """`_restamp_changed_boxes` - a document added after forms (no own keys),
    the Data Consistency confirm and an answer's derived boxes (own keys)."""
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _with_ai("ACORD_160", ai, raw)}
    facts_after = {**facts, QUAKE: {"value": after, "source": "ai", "confidence": "filled"}}
    touched = arq._restamp_changed_boxes(gen, facts, facts_after, own_keys=own, provenance="filled")
    assert touched == ["ACORD_160"]
    assert _pair(gen["ACORD_160"]["field_state"]) == pair == _generation_pair(facts_after)
    assert next(iter(ai)) not in gen["ACORD_160"]["confidence"]


@pytest.mark.parametrize("person", _PEOPLE)
def test_a_change_never_clears_a_persons_half(person):
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _with_ai("ACORD_160", {EQ_AMOUNT: "25,000"}, "Earthquake deductible $25,000.")}
    gen["ACORD_160"]["confidence"][EQ_AMOUNT] = person
    facts_after = {**facts, QUAKE: {"value": "2%", "source": "ai"}}
    arq._restamp_changed_boxes(gen, facts, facts_after, own_keys=set(), provenance="filled")
    assert gen["ACORD_160"]["field_state"][EQ_AMOUNT] == "25,000"
    assert gen["ACORD_160"]["confidence"][EQ_AMOUNT] == person


def test_a_change_that_leaves_the_deductible_unstated_keeps_the_ai_reading():
    facts = {"applicant_name": "Acme LLC"}
    gen = {"ACORD_160": _with_ai("ACORD_160", {EQ_AMOUNT: "25,000"}, "Earthquake deductible $25,000.")}
    arq._restamp_changed_boxes(gen, facts, {**facts, "applicant_name": "Acme Two LLC"},
                               own_keys=set(), provenance="filled")
    assert gen["ACORD_160"]["field_state"][EQ_AMOUNT] == "25,000"


# ══ Finding 10: Field QA compares a worded percentage whole ═════════════════

@pytest.mark.parametrize("value", ["2% of TIV", "2 percent of TIV", "2% TIV", "Wind/Hail: 2%",
                                   "2% per building", "1-2%", "1-2% of TIV", "2%",
                                   "2% / $25,000 minimum", "$25,000 or 2%", "$25,000 per occurrence",
                                   "$2,500"])
def test_field_qa_raises_no_false_mismatch_on_a_deductible_box(value):
    from services.field_qa import run_field_qa
    facts = {"applicant_name": "Acme LLC", WIND: value, QUAKE: value}
    gen = {fid: _generated(fid, facts) for fid in ("ACORD_28", "ACORD_160")}
    out = run_field_qa(gen, facts, unanswered=False)
    rows = [r for r in out.get("results", [])
            if r.get("field") in (WIND_BOX, EQ_AMOUNT, EQ_PERCENT)
            and r.get("reason_code") == "value_mismatch"]
    assert not rows, rows


def test_an_amount_box_still_compares_the_amount_inside_a_dollar_sentence():
    box = "Vehicle_CombinedSingleLimit_EachAccidentAmount_A"
    assert ps.expected_value_for_field(box, "auto_liability_limit",
                                       "$1,000,000 Combined Single Limit") == "$1,000,000"
    assert ps.expected_value_for_field(WIND_BOX, WIND, "2% of TIV") == "2% of TIV"
    assert ps.expected_value_for_field(WIND_BOX, WIND, "1-2% of TIV") == "1-2% of TIV"
    assert ps.expected_value_for_field(WIND_BOX, WIND, "$25,000 per occurrence") == "$25,000"


# ══ Finding 11: the editor's bare figure in the "%" box is a share ═══════════

@pytest.mark.parametrize("typed,written", [("2", "2%"), ("1.5", "1.5%"), ("0", "0%"), ("100", "100%"),
                                           (".5", "0.5%"), ("101", "101"), ("250", "250"),
                                           ("25000", "25000")])
def test_a_bare_figure_in_the_percent_box_is_a_percentage_only_from_0_to_100(typed, written):
    assert ps.box_fact_value(EQ_PERCENT, typed, QUAKE) == written
    assert ps.box_fact_value(EQ_AMOUNT, typed, QUAKE) == typed          # the amount box: dollars


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


@pytest.mark.parametrize("typed,stored", [("25000", "25000"), ("250", "250"), ("2", "2%")])
def test_the_editor_never_stores_an_impossible_percentage(typed, stored):
    res, saved = _editor_save({EQ_PERCENT: typed}, {"applicant_name": "Acme LLC"}, "ACORD_160")
    assert res.status_code == 200
    assert saved["facts"][QUAKE]["value"] == stored
    assert saved["generated_forms"]["ACORD_160"]["field_state"][EQ_PERCENT] == typed   # as typed
