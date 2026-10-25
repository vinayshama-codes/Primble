"""Build 24 follow-ups (22 Oct 2026).

1. A client answer its fact's own check refuses ("2050" for year built, "15"
   for a protection class) is HELD for the producer through the existing
   "Needs your decision" path (`client_answer_review`), with the producer
   path's words - never written to a fact, a building row or a box, and the
   submission is never refused for it.
2. A client answer to an ACORD 25 / 28 policy-row date box stays on its box and
   never writes the proposed term - `arq_service.client_answer_fact`, the ONE
   rule the client page's term refusal (`arq_routes.client_term_dates`) reads.

Follow-ups (same day):
1. Every fact's check accepts the examples its own hint names and the options
   it offers (`construction_type` refused "Masonry").
2. The "Needs your decision" card shows a row's own reason, and a neutral intro
   when a hold is a format hold (`kind: "format"`).
3. The claims-made box writes "Claims Made" for a Yes and nothing for a No
   (`pdf_service.box_fact_value`), on the client's answer and the editor's tick.
"""
import ast
import asyncio
import copy
import inspect
import json
import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import routes.arq_routes as ar
import services.arq_service as arq
import services.client_answer_review as car
from services.fact_registry import FACT_REGISTRY

BACKEND = Path(__file__).resolve().parents[1]


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _form(fid):
    return {"schema": _schema(fid), "field_state": {}, "confidence": {}}


def _row(n, line1, **kw):
    return {"location_number": str(n), "address_line1": line1, "address_city": "Denver",
            "address_state": "CO", "address_zip": "80202", **kw}


def _apply(session, answers, questions):
    arq_row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
               "answers": answers, "questions": questions}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=arq_row)), \
         patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    return saved


def _hint(fact):
    return f"That does not look right for this field. Expected: {FACT_REGISTRY[fact]['format_hint']}"


def _value(raw):
    return raw.get("value") if isinstance(raw, dict) else raw


# ══ FIX 1 - a value its fact's own check refuses is held, not written ════════

_BAD = [("year_built", "2050", "1995", "CommercialStructure_BuiltYear_"),
        ("fire_protection_class", "15", "3", "BuildingFireProtection_ProtectionClassCode_")]


def _package_session():
    return {"generated_forms": {"ACORD_140": _form("ACORD_140")},
            "facts": {"applicant_name": "Acme LLC",
                      "property_locations": {"value": [_row(1, "1 Main St")], "source": "ai"}},
            "flags": {"has_property_coverage": True}}


@pytest.mark.parametrize("fact,bad,good,box", _BAD)
def test_a_refused_package_answer_is_held_and_written_nowhere(fact, bad, good, box):
    q = [{"field_name": fact, "question": "q", "form_ids": ["ACORD_140"]}]
    saved = _apply(_package_session(), {fact: bad}, q)
    assert not _value(saved["facts"].get(fact))                         # fact unchanged
    state = saved["generated_forms"]["ACORD_140"]["field_state"]
    assert bad not in [str(v) for v in state.values()]                  # no box written
    held = saved["client_answer_conflicts"][fact]
    assert held["client_value"] == bad and held["field_name"] == fact
    assert held["reason"] == _hint(fact)
    assert saved["facts"]["_client_answer_conflicts"][fact]["client_value"] == bad
    # ...and the same question answered correctly is written and printed as before
    saved = _apply(_package_session(), {fact: good}, q)
    assert _value(saved["facts"][fact]) == good
    assert saved["generated_forms"]["ACORD_140"]["field_state"][box + "A"] == good
    assert fact not in (saved.get("client_answer_conflicts") or {})


def _building_session():
    rows = [_row(1, "1 Main St"), _row(2, "2 Oak Ave")]
    return {"generated_forms": {"ACORD_140": _form("ACORD_140")},
            "facts": {"applicant_name": "Acme LLC", "property_locations": {"value": rows, "source": "ai"}},
            "flags": {"has_property_coverage": True}}


def _building_question(fact):
    """The per-building question as `_split_building_questions` sends it (the
    row it named included). Year built is asked in the location table when the
    list has one, so its question is built here in the same shape."""
    from services.premises_interest import sent_row
    row = _building_session()["facts"]["property_locations"]["value"][1]
    return {"field_name": f"{fact}@loc2", "question": "q", "form_ids": ["ACORD_140"], **sent_row(row)}


def test_the_building_question_shape_is_the_generators():
    qs = arq.generate_arq_questions_from_facts(copy.deepcopy(_building_session()["facts"]),
                                               {"has_property_coverage": True},
                                               ["ACORD_125", "ACORD_140"], [], [])
    real = next(q for q in qs if q["field_name"] == "fire_protection_class@loc2")
    mine = _building_question("fire_protection_class")
    assert {k: real[k] for k in ("row_address", "row_building", "form_ids")} == \
        {k: mine[k] for k in ("row_address", "row_building", "form_ids")}


@pytest.mark.parametrize("fact,bad,good,box", _BAD)
def test_a_refused_building_answer_is_held_and_written_nowhere(fact, bad, good, box):
    from services.premises_cope import PER_BUILDING_COPE
    name, column = f"{fact}@loc2", PER_BUILDING_COPE[fact]
    q = [_building_question(fact)]
    saved = _apply(_building_session(), {name: bad}, q)
    rows = saved["facts"]["property_locations"]["value"]
    assert not rows[1].get(column) and not rows[0].get(column)          # row unchanged
    assert not _value(saved["facts"].get(fact))                         # never the package fact
    state = saved["generated_forms"]["ACORD_140"]["field_state"]
    assert bad not in [str(v) for v in state.values()]                  # no box written
    held = saved["client_answer_conflicts"][name]
    assert held["client_value"] == bad and held["field_name"] == name
    assert held["reason"] == _hint(fact)
    assert held["label"].startswith(car._label_for(fact) + " - 2 Oak Ave")
    # ...and a good answer lands on that building's row and box only, as before
    saved = _apply(_building_session(), {name: good}, q)
    rows = saved["facts"]["property_locations"]["value"]
    assert rows[1][column] == good and not rows[0].get(column)
    assert saved["generated_forms"]["ACORD_140"]["field_state"][box + "B"] == good
    assert name not in (saved.get("client_answer_conflicts") or {})


def test_the_held_answer_is_one_needs_your_decision_row():
    q = [_building_question("year_built"), {"field_name": "fire_protection_class", "question": "q",
                                            "form_ids": ["ACORD_140"]}]
    saved = _apply(_building_session(), {"year_built@loc2": "2050", "fire_protection_class": "15"}, q)
    rows = {r["fact_key"]: r for r in car.build_review_rows(saved)}
    assert set(rows) == {"year_built@loc2", "fire_protection_class"}
    assert rows["year_built@loc2"]["reason"] == _hint("year_built")
    assert rows["year_built@loc2"]["source_value"] == "(not stated)"
    assert rows["fire_protection_class"]["label"] == car._label_for("fire_protection_class")
    assert rows["fire_protection_class"]["reason"] == _hint("fire_protection_class")


def test_the_reason_is_the_producer_paths_own_words():
    from routes.audit_routes import _validate_producer_answer
    for fact, bad, good, _box in _BAD:
        assert _validate_producer_answer(fact, bad) == (False, _hint(fact))
        assert arq._answer_check_refusal(fact, fact, bad) == _hint(fact)
        assert _validate_producer_answer(fact, good) == (True, "")
        assert arq._answer_check_refusal(fact, fact, good) == ""


@pytest.mark.parametrize("answer", ["None", "N/A", "not applicable", "not sure", "I don't know", "", "  "])
def test_a_non_answer_or_an_absence_is_never_held(answer):
    for fact, *_ in _BAD:
        assert arq._answer_check_refusal(fact, fact, answer) == ""
        assert arq._answer_check_refusal(fact, f"{fact}@loc2", answer) == ""


def test_an_absence_is_applied_as_before_not_held():
    q = [{"field_name": "year_built", "question": "q", "form_ids": ["ACORD_140"]}]
    saved = _apply(_package_session(), {"year_built": "None"}, q)
    assert "year_built" not in (saved.get("client_answer_conflicts") or {})
    assert saved["facts"]["year_built"]["value_state"] == "explicit_no"


def test_a_fact_with_no_validator_is_unaffected():
    assert FACT_REGISTRY["occupancy_type"]["validate"] is None
    assert arq._answer_check_refusal("occupancy_type", "occupancy_type", "x") == ""
    q = [{"field_name": "occupancy_type", "question": "q", "form_ids": ["ACORD_140"]}]
    saved = _apply(_package_session(), {"occupancy_type": "Warehouse"}, q)
    assert _value(saved["facts"]["occupancy_type"]) == "Warehouse"
    assert not saved.get("client_answer_conflicts")
    # a box with no fact behind it has nothing to judge
    assert arq._answer_check_refusal(None, "Some_Box_A", "2050") == ""


def test_every_option_a_fact_offers_is_never_held():
    """A dropdown choice is never held: each option reads as a value its fact accepts."""
    from services.answer_options import OTHER, options_for
    for fact in FACT_REGISTRY:
        for opt in options_for(fact) or ():
            if opt != OTHER:
                assert arq._answer_check_refusal(fact, fact, opt) == "", (fact, opt)


# ── Follow-up 1: every check accepts its own hint's examples and options ─────

_PAREN = re.compile(r"\(([^()]*)\)")
_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")
# A hint list written with lower-case format nouns ("Dollar amount or
# percentage") names FORMATS, not values; a value is written as itself
# ("Stated Amount", "Not applicable").
_FORMAT_NOUNS = re.compile(r"\b(?:amount|percentage|percent|number|date|digits?|text|characters)\b")


def _eg_values(segment):
    quoted = [a or b for a, b in _QUOTED.findall(segment)]
    return quoted or [p.strip(" .;,") for p in re.split(r"\s+or\s+", segment) if p.strip(" .;,")]


def hint_examples(hint):
    """The values a format hint names: its "e.g." examples (the quoted ones, or
    split on "or") and a listed choice ("Frame, Masonry, Concrete, Steel,
    etc.", "Yes or No", "Requested / Declined / ..."). A parenthetical gloss is
    not a value, and neither is a list of parts ("street, city, state, ZIP")."""
    h = str(hint or "")
    out = []
    for inner in _PAREN.findall(h):
        if "e.g." in inner:
            out += _eg_values(inner.split("e.g.", 1)[1])
    rest = _PAREN.sub("", h)
    if "e.g." in rest:
        rest, tail = rest.split("e.g.", 1)
        out += _eg_values(tail)
    rest = rest.strip(" ,;")
    if " / " in rest:
        items = rest.split(" / ")
    elif re.search(r"\bor\b", rest) or rest.endswith("etc."):
        items = re.split(r",\s*(?:or\s+)?|\s+or\s+", rest)
    else:
        items = []
    items = [i.strip(" .") for i in items if i.strip(" .") not in ("", "etc")]
    if not any(_FORMAT_NOUNS.search(i) for i in items):
        out += items
    return out


def test_the_hint_reader():
    assert hint_examples("Frame, Masonry, Concrete, Steel, etc.") == ["Frame", "Masonry", "Concrete", "Steel"]
    assert hint_examples("Dollar amount (e.g. $1,000,000)") == ["$1,000,000"]
    assert hint_examples("Percentage 0–100 (e.g. 25 or 25%)") == ["25", "25%"]
    assert hint_examples("RCV (Replacement Cost Value) or ACV (Actual Cash Value)") == ["RCV", "ACV"]
    assert hint_examples("Requested / Declined / Already carried / Not applicable") == [
        "Requested", "Declined", "Already carried", "Not applicable"]
    assert hint_examples("e.g. 'Requested - pending' or 'No loss runs are available'") == [
        "Requested - pending", "No loss runs are available"]
    assert hint_examples("Actual Cash Value, Agreed Value, or Stated Amount") == [
        "Actual Cash Value", "Agreed Value", "Stated Amount"]
    for formats in ("Dollar amount or percentage", "Full address including street, city, state, ZIP",
                    "Street, city, state, ZIP", "Date in MM/DD/YYYY format", "9-digit EIN (XX-XXXXXXX)"):
        assert hint_examples(formats) == [], formats


def test_every_check_accepts_its_own_hint_examples_and_options():
    """A hint and its check can never drift apart again: every example a fact's
    `format_hint` names passes `answer_check`, and every option the fact offers
    passes it as the value the options door stores (`canonical_option_value` -
    "Protection Class 3" is stored "3"), or is one of the list's absence / not
    applicable answers. "Other" only opens the free-text box."""
    from services.answer_options import OTHER, options_for
    from services.answer_semantics import VALUE, interpret_answer
    from services.fact_registry import answer_check
    examples = options = 0
    for fact, entry in FACT_REGISTRY.items():
        check = answer_check(entry)
        if not callable(check):
            continue
        for example in hint_examples(entry.get("format_hint")):
            assert check(example), (fact, example)
            examples += 1
        for opt in options_for(fact) or ():
            if opt == OTHER:
                continue
            got = interpret_answer(fact, opt, entry)
            assert got.answered, (fact, opt)
            if got.intent == VALUE:
                assert check(got.value), (fact, opt, got.value)
                # ...and the same value typed into "Other" ("Other: <value>")
                assert arq._answer_check_refusal(fact, fact, f"Other: {got.value}") == "", (fact, opt)
            options += 1
        for example in hint_examples(entry.get("format_hint")):
            assert arq._answer_check_refusal(fact, fact, f"Other: {example}") == "", (fact, example)
    for fact, value in _REAL_ANSWERS:
        assert answer_check(FACT_REGISTRY[fact])(value), (fact, value)
        assert arq._answer_check_refusal(fact, fact, f"Other: {value}") == "", (fact, value)
    assert examples >= 100 and options >= 50, (examples, options)


# Real printings a fact's shape refused (follow-up round 3): accepted by the
# person check (`answer_validate`), nothing looser.
_REAL_ANSWERS = (
    ("wc_xmod", ".87"), ("wc_xmod", "0.87"), ("wc_xmod", "1.10"),
    ("wc_xmod", "1.0800"), ("wc_xmod", ".8765"),               # four decimals parse_xmod reads
    ("valuation_method", "Replacement Cost"), ("valuation_method", "Replacement Cost Value"),
    ("valuation_method", "Agreed Value"), ("valuation_method", "Functional Replacement Cost"),
    ("valuation_method", "ACV"), ("valuation_method", "Actual Cash Value"), ("valuation_method", "RCV"),
    ("fire_protection_class", "8B"), ("fire_protection_class", "10W"), ("fire_protection_class", "4/9"),
    ("fire_protection_class", "6/10W"), ("fire_protection_class", "3"), ("fire_protection_class", "10"),
    ("fire_protection_class", "03"), ("fire_protection_class", "010"), ("fire_protection_class", "04/09"),
    ("valuation_method", "Agreed Amount"), ("valuation_method", "Market Value"),     # ACORD's words
)
_NOT_LOOSER = (
    ("wc_xmod", "."), ("wc_xmod", "1.2.3"), ("wc_xmod", "abc"), ("wc_xmod", "-0.9"),
    ("wc_xmod", "1.08001"), ("wc_xmod", ".87654"), ("wc_xmod", "9.9999"),   # parse_xmod reads none
    ("valuation_method", "Replacement"), ("valuation_method", "Cash"),
    ("fire_protection_class", "11"), ("fire_protection_class", "0"), ("fire_protection_class", "8C"),
    ("fire_protection_class", "011"), ("fire_protection_class", "00"),
    ("fire_protection_class", "10X"), ("fire_protection_class", "9/4"), ("fire_protection_class", "4/4"),
    ("fire_protection_class", "4/9/10"), ("fire_protection_class", "A"),
)


def test_real_answers_pass_and_nothing_looser():
    from services.answer_semantics import canonical_option_value
    from services.fact_registry import answer_check
    for fact, value in _REAL_ANSWERS:
        assert arq._answer_check_refusal(fact, fact, value) == "", (fact, value)
    for fact, value in _NOT_LOOSER:
        assert not answer_check(FACT_REGISTRY[fact])(value), (fact, value)
    # each fact's shape is unchanged: extraction still reduces an "8B" to a number
    assert not FACT_REGISTRY["fire_protection_class"]["validate"]("8B")
    assert not FACT_REGISTRY["wc_xmod"]["validate"](".87")
    assert not FACT_REGISTRY["valuation_method"]["validate"]("Agreed Value")
    # ...and a dropdown pick still stores the value the forms read
    assert canonical_option_value("valuation_method", "Replacement Cost") == "RCV"
    assert canonical_option_value("valuation_method", "Actual Cash Value") == "ACV"
    assert canonical_option_value("fire_protection_class", "Protection Class 10 - unprotected") == "10"
    assert canonical_option_value("wc_xmod", "1.00 - neither a credit nor a debit mod") == "1.00"


def test_every_protection_class_the_shape_took_still_passes():
    from services.fact_registry import answer_check
    shape = FACT_REGISTRY["fire_protection_class"]["validate"]
    check = answer_check(FACT_REGISTRY["fire_protection_class"])
    for n in range(0, 13):
        for zeros in ("", "0", "00", "000"):
            value = zeros + str(n)
            if shape(value):
                assert check(value), value                 # nothing the old check took is refused
    assert check("03") and check("010") and not check("011")


_VC = "CommercialProperty_Premises_ValuationCode_A"


@pytest.mark.parametrize("method,code", [
    ("RCV", "R"), ("R", "R"), ("Replacement Cost", "R"), ("Replacement Cost Value", "R"),
    ("ACV", "A"), ("A", "A"), ("Actual Cash Value", "A"),
    ("Agreed Amount", "V"), ("Agreed Value", "V"), ("V", "V"),
    ("Market Value", "M"), ("M", "M"),
    ("Functional Replacement Cost", None),                  # no code: blank, never words
])
def test_the_valuation_code_box_prints_its_one_letter_code(method, code):
    import services.pdf_service as ps
    for fid in ("ACORD_140", "ACORD_160"):
        facts = {"valuation_method": {"value": method, "source": "client_arq"}, "_form_id": fid}
        with ps._schema_context(_schema(fid)):
            assert ps._deterministic_map(_VC, facts) == code, (fid, method)
            assert ps._resolve_via_field_rules(_VC, facts) == code, (fid, method)


def test_generation_prints_the_code_not_the_words():
    import services.pdf_service as ps
    facts = {"valuation_method": {"value": "Agreed Amount", "source": "client_arq"},
             "has_property_coverage": True,
             "property_locations": {"value": [_row(1, "1 Main St")], "source": "ai"}}
    mapped, _conf = ps.map_facts_to_form(dict(facts), _schema("ACORD_140"), "ACORD_140", "", allow_llm=False)
    assert mapped.get(_VC) == "V"                            # printed "Agreed Amount" before


def test_a_four_decimal_xmod_passes_exactly_when_parse_xmod_reads_it():
    from services.coverage_evidence import parse_xmod
    from services.fact_registry import answer_check
    check = answer_check(FACT_REGISTRY["wc_xmod"])
    for value in ("1.0800", ".8765", "0.8765", "2.9999", "9.9999", "0.1000", "1.08001"):
        reads = parse_xmod(value) is not None and len(value.split(".")[-1]) == 4
        assert bool(check(value)) == reads, value


def test_an_other_typed_value_is_judged_as_its_text():
    for fact, value in (("wc_xmod", "Other: 0.87"), ("construction_type", "Other: Masonry"),
                        ("fire_protection_class", "Other: 3"), ("valuation_method", "Other: ACV"),
                        ("sprinkler_system", "Other: Full"), ("wc_xmod", "OTHER:.87")):
        assert arq._answer_check_refusal(fact, fact, value) == "", (fact, value)
    for empty in ("Other:", "Other: ", "other :  "):
        assert arq._answer_check_refusal("year_built", "year_built", empty) == ""
    assert arq._answer_check_refusal("year_built", "year_built", "Other: 2050") == _hint("year_built")
    out, apply_, _upd = _resolve({"wc_xmod": {"client_value": "Other: 0.87", "source_value": "1.00",
                                              "field_name": "wc_xmod"}}, "wc_xmod")
    assert out["ok"] is True and apply_.await_count == 1                        # F5 too


def test_masonry_is_accepted_and_the_list_is_not_loosened():
    from services.fact_registry import answer_check
    check = answer_check(FACT_REGISTRY["construction_type"])
    assert check("Masonry") and check("masonry")
    for other in ("Adobe", "Log cabin", "Masonry walls"):
        assert not check(other), other
    assert arq._answer_check_refusal("construction_type", "construction_type", "Masonry") == ""
    q = [{"field_name": "construction_type", "question": "q", "form_ids": ["ACORD_140"]}]
    saved = _apply(_package_session(), {"construction_type": "Masonry"}, q)
    assert _value(saved["facts"]["construction_type"]) == "Masonry"
    assert not saved.get("client_answer_conflicts")


# ── Follow-up 2: the card says why, and what kind of hold it is ──────────────

def test_review_rows_carry_the_kind_and_their_own_reason():
    saved = _apply(_building_session(), {"year_built@loc2": "2050"}, [_building_question("year_built")])
    session = {"client_answer_conflicts": {
        **saved["client_answer_conflicts"],
        "num_employees": {"client_value": "25", "source_value": "18"},          # F7 shape
        "insurer_policy::gl::policy_number": {"client_value": "X1", "source_value": "Y2",
                                              "reason": "The documents print this number for Auto."}}}
    rows = {r["fact_key"]: r for r in car.build_review_rows(session)}
    fmt = rows["year_built@loc2"]
    assert (fmt["kind"], fmt["own_reason"], fmt["reason"]) == ("format", True, _hint("year_built"))
    f7 = rows["num_employees"]
    assert (f7["kind"], f7["own_reason"]) == ("conflict", False)
    assert "does not match" in f7["reason"]                                    # unchanged default
    pol = rows["insurer_policy::gl::policy_number"]
    assert (pol["kind"], pol["own_reason"]) == ("conflict", True)


def test_the_card_reads_the_kind_and_shows_its_own_reason():
    src = (BACKEND.parent / "frontend" / "src" / "components" / "form" / "AcordModal.jsx").read_text(
        encoding="utf-8")
    start = src.index("Needs your decision (V1 C1-D")
    block = src[start:src.index("Session delta", start)]
    assert 'clientAnswerReview.some((r) => r.kind === "format")' in block
    assert "Your client's answer needs a check before it goes on the form." in block
    assert "The client answered differently from the uploaded documents." in block   # kept
    assert "row.own_reason && row.reason" in block
    assert "—" not in block                                                # no em-dash


# ── Follow-up 3: the claims-made box writes the basis, never "Yes" ───────────

_CM = "GeneralLiability_ClaimsMadeIndicator_A"


_OCC = "GeneralLiability_OccurrenceIndicator_A"
_CSL = "Vehicle_CombinedSingleLimit_LimitIndicator_A"
_AGG = "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A"


def test_box_fact_value():
    from services.pdf_service import box_fact_value
    for box, fact, meaning in ((_CM, "gl_form_type", "Claims Made"), (_OCC, "gl_form_type", "Occurrence"),
                               (_CSL, "auto_liability_structure", "CSL")):
        for yes in ("Yes", "/Yes", "On", "X", "true", "1"):
            assert box_fact_value(box, yes, fact) == meaning, (box, yes)
        for no in ("No", "Off", "/Off", "", None):
            assert box_fact_value(box, no, fact) is None, (box, no)
    for state in ("Yes", "On", "Off", "No", ""):
        assert box_fact_value(_AGG, state, "gl_aggregate") is None, state     # never the limit
    # a Yes / No fact's checkbox writes its state as before; a text box its value
    for state in ("Yes", "Off"):
        assert box_fact_value("LossHistory_NoPriorLossesIndicator_A", state,
                              "loss_history_no_prior_losses_indicator") == state
    assert box_fact_value("CommercialStructure_BuiltYear_A", "1995", "year_built") == "1995"
    assert box_fact_value("Policy_EffectiveDate_A", "07/15/2027", "effective_date") == "07/15/2027"


def _gl_session(stored=None):
    facts = {"applicant_name": "Acme LLC", "has_general_liability": True}
    if stored:
        facts["gl_form_type"] = {"value": stored, "source": "ai"}
    return {"generated_forms": {"ACORD_126": _form("ACORD_126")}, "facts": facts,
            "flags": {"has_general_liability": True}}


def _cm_question():
    return [{"field_name": _CM, "question": "q", "form_ids": ["ACORD_126"], "field_type": "checkbox"}]


@pytest.mark.parametrize("stored", [None, "Claims-Made"])
def test_a_client_yes_on_the_claims_made_box_writes_claims_made(stored):
    saved = _apply(_gl_session(stored), {_CM: "Yes"}, _cm_question())
    assert saved["facts"]["gl_form_type"]["value"] == "Claims Made"
    assert saved["generated_forms"]["ACORD_126"]["field_state"][_CM] == "Yes"
    assert not saved.get("client_answer_conflicts")


@pytest.mark.parametrize("stored", [None, "Occurrence"])
def test_a_client_no_on_the_claims_made_box_writes_nothing(stored):
    saved = _apply(_gl_session(stored), {_CM: "No"}, _cm_question())
    assert saved["facts"].get("gl_form_type") == _gl_session(stored)["facts"].get("gl_form_type")
    assert saved["generated_forms"]["ACORD_126"]["field_state"][_CM] == "No"
    assert not saved.get("client_answer_conflicts")


def test_a_client_yes_against_an_occurrence_policy_is_held_as_claims_made():
    saved = _apply(_gl_session("Occurrence"), {_CM: "Yes"}, _cm_question())
    assert saved["facts"]["gl_form_type"]["value"] == "Occurrence"
    assert saved["client_answer_conflicts"]["gl_form_type"]["client_value"] == "Claims Made"


def _editor_save(field_updates, facts, form_id="ACORD_126", log=None):
    import routes.form_routes as fr
    import services.pdf_service as ps
    from types import SimpleNamespace
    log = log if log is not None else AsyncMock()
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
         patch.object(fr, "log_field_change", log), \
         patch.object(fr, "upd_processing_session", upd), \
         patch.object(fr, "sync_recommendation_cards", AsyncMock()), \
         patch.object(fr, "run_and_log_field_qa", AsyncMock()), \
         patch.object(fr, "run_and_log_field_mapping_check", AsyncMock()), \
         patch("services.arq_service.recalculate_session_scores", AsyncMock()):
        res = asyncio.run(fr.update_pdf(
            SimpleNamespace(session_id="s1", field_updates={"__form_id__": form_id, **field_updates}),
            {"id": "u1"}))
    call = next(c for c in upd.call_args_list if "generated_forms" in c.args[1])
    return res, call.args[1], call.kwargs.get("delete_facts") or []


def test_an_editor_tick_on_the_claims_made_box_writes_claims_made():
    res, stored, _ = _editor_save({_CM: "Yes"}, {"applicant_name": "Acme LLC"})
    assert res.status_code == 200
    assert stored["facts"]["gl_form_type"]["value"] == "Claims Made"
    assert stored["facts"]["gl_form_type"]["source"] == "producer"


def test_an_editor_untick_on_the_claims_made_box_writes_nothing():
    facts = {"applicant_name": "Acme LLC", "gl_form_type": {"value": "Occurrence", "source": "ai"}}
    res, stored, deleted = _editor_save({_CM: "Off"}, facts)
    assert res.status_code == 200
    assert (stored["facts"].get("gl_form_type") or {}).get("value") == "Occurrence"
    assert "gl_form_type" not in deleted


# ── Follow-up 4: the checkbox CLASS - a raw state never reaches a non-Yes/No fact ──

_LIMIT = {"value": "$2,000,000", "source": "ai"}


@pytest.mark.parametrize("state", ["Yes", "No"])
def test_a_client_aggregate_tick_never_touches_the_aggregate_limit(state):
    session = _gl_session()
    session["facts"]["gl_aggregate"] = dict(_LIMIT)
    q = [{"field_name": _AGG, "question": "q", "form_ids": ["ACORD_126"], "field_type": "checkbox"}]
    saved = _apply(session, {_AGG: state}, q)
    assert saved["facts"]["gl_aggregate"] == _LIMIT
    assert saved["generated_forms"]["ACORD_126"]["field_state"][_AGG] == state    # stays on its box
    assert not saved.get("client_answer_conflicts")


@pytest.mark.parametrize("state", ["Yes", "Off"])
def test_an_editor_aggregate_tick_never_touches_the_aggregate_limit(state):
    res, stored, deleted = _editor_save({_AGG: state}, {"applicant_name": "Acme LLC", "gl_aggregate": dict(_LIMIT)})
    assert res.status_code == 200
    assert stored["facts"]["gl_aggregate"]["value"] == "$2,000,000"
    assert "gl_aggregate" not in deleted


def test_occurrence_yes_stores_occurrence_on_both_doors():
    q = [{"field_name": _OCC, "question": "q", "form_ids": ["ACORD_126"], "field_type": "checkbox"}]
    saved = _apply(_gl_session(), {_OCC: "Yes"}, q)
    assert saved["facts"]["gl_form_type"]["value"] == "Occurrence"
    _res, stored, _ = _editor_save({_OCC: "Yes"}, {"applicant_name": "Acme LLC"})
    assert stored["facts"]["gl_form_type"]["value"] == "Occurrence"
    saved = _apply(_gl_session("Claims-Made"), {_OCC: "No"}, q)
    assert saved["facts"]["gl_form_type"]["value"] == "Claims-Made"           # a No states nothing


def test_csl_yes_stores_the_csl_value_on_both_doors():
    from services.coverage_evidence import _structure_reading
    from services.fact_registry import answer_check
    session = {"generated_forms": {"ACORD_137_CA": _form("ACORD_137_CA")},
               "facts": {"applicant_name": "Acme LLC"}, "flags": {"has_auto_coverage": True}}
    q = [{"field_name": _CSL, "question": "q", "form_ids": ["ACORD_137_CA"], "field_type": "checkbox"}]
    saved = _apply(session, {_CSL: "Yes"}, q)
    assert saved["facts"]["auto_liability_structure"]["value"] == "CSL"
    _res, stored, _ = _editor_save({_CSL: "Yes"}, {"applicant_name": "Acme LLC"}, "ACORD_137_CA")
    assert stored["facts"]["auto_liability_structure"]["value"] == "CSL"
    # ...in the fact's own vocabulary: its check takes it and its reader reads CSL
    assert answer_check(FACT_REGISTRY["auto_liability_structure"])("CSL")
    assert _structure_reading("CSL") == "csl"


def test_a_yes_no_facts_checkbox_still_writes_as_before():
    res, stored, _ = _editor_save({"LossHistory_NoPriorLossesIndicator_A": "Yes"},
                                  {"applicant_name": "Acme LLC"}, "ACORD_125")
    assert res.status_code == 200
    assert stored["facts"]["loss_history_no_prior_losses_indicator"]["value"] == "Yes"


def test_no_checkbox_writes_a_raw_state_into_a_fact_that_is_not_yes_no():
    """The class, over all 17 schemas and both doors: every checkbox whose fact
    (the editor's first matching rule, the client's `_canonical_key`) is not a
    Yes / No fact writes only a meaning its fact's own check accepts, or
    nothing - never "Yes" / "No" / "On" / "Off"."""
    from services.fact_registry import answer_check
    from services.normalization import canonical_yes_no, is_yes_no_field
    from services.pdf_service import _ACORD_FIELD_RULES, _all_form_schemas, box_fact_value
    states = ("Yes", "No", "On", "Off", "/Yes", "/Off", "X", "1", "0", "true", "false", "")
    seen = set()
    for schema in _all_form_schemas().values():
        for box, meta in schema.items():
            if (meta or {}).get("ft") != "/Btn":
                continue
            editor = next((k for p, k in _ACORD_FIELD_RULES if k and not k.startswith("_") and p in box), None)
            for fact in {editor, arq._canonical_key(box)}:
                if not fact or fact.startswith("_") or is_yes_no_field(fact):
                    continue
                seen.add((box, fact))
                for state in states:
                    out = box_fact_value(box, state, fact)
                    if out is None:
                        continue
                    assert canonical_yes_no(out) is None and str(out).strip(), (box, fact, state, out)
                    assert answer_check(FACT_REGISTRY[fact])(out), (box, fact, out)
    assert {f for _b, f in seen} >= {"gl_form_type", "gl_aggregate", "auto_liability_structure"}


# ── Follow-up 5: "Use the client's value" runs the same check ───────────────

def _resolve(held, fact_key, choice="use_client"):
    session = {"client_answer_conflicts": held, "facts": {"_client_answer_conflicts": held}}
    upd, apply_ = AsyncMock(), AsyncMock(return_value=(True, ["ACORD_125"]))
    with patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", upd), \
         patch("services.arq_service.apply_producer_answer_to_session", apply_), \
         patch("services.arq_service.recalculate_session_scores", AsyncMock(return_value={"ok": True})), \
         patch("services.audit_service.log_underwriting_confirmation", AsyncMock()):
        out = asyncio.run(car.resolve_client_answer("s1", fact_key, choice))
    return out, apply_, upd


@pytest.mark.parametrize("key,field", [("year_built", "year_built"), ("year_built@loc2", "year_built@loc2"),
                                       ("fire_protection_class", "fire_protection_class")])
def test_use_the_clients_value_refuses_a_value_its_check_refuses(key, field):
    bad = "15" if "protection" in key else "2050"
    held = {key: {"client_value": bad, "source_value": "(not stated)", "field_name": field,
                  "kind": "format", "reason": "x"}}
    out, apply_, upd = _resolve(held, key)
    assert out["ok"] is False and "Edit the field on the form instead" in out["message"]
    apply_.assert_not_awaited()
    upd.assert_not_awaited()                                                  # the hold stays
    out, apply_, upd = _resolve(held, key, "keep_source")
    assert out["ok"] is True and upd.await_count == 1                         # Keep still clears it


def test_use_the_clients_value_still_applies_a_good_value():
    held = {"num_employees": {"client_value": "25", "source_value": "18", "field_name": "num_employees"}}
    out, apply_, _upd = _resolve(held, "num_employees")
    assert out["ok"] is True
    apply_.assert_awaited_once_with("s1", "num_employees", "25")


# ── Follow-up round 3 (review): rows, withdrawal, audit, limit scope ─────────

def test_a_csl_tick_on_another_coverage_row_writes_nothing():
    from services.pdf_service import box_fact_value
    rows = sorted(k for k in _schema("ACORD_137_CA") if k.startswith(_CSL[:-1]) and k != _CSL)
    assert len(rows) >= 4, rows
    for box in rows:
        assert box_fact_value(box, "Yes", "auto_liability_structure") is None, box
    split = {"applicant_name": "Acme LLC", "auto_liability_structure": {"value": "Split Limits", "source": "ai"}}
    _res, stored, _ = _editor_save({rows[0]: "Yes"}, split, "ACORD_137_CA")
    assert stored["facts"]["auto_liability_structure"]["value"] == "Split Limits"


@pytest.mark.parametrize("box,fact,stated,form", [
    (_CM, "gl_form_type", "Claims-Made", "ACORD_126"),
    (_OCC, "gl_form_type", "Occurrence", "ACORD_126"),
    (_CSL, "auto_liability_structure", "CSL", "ACORD_137_CA"),
])
def test_an_editor_untick_withdraws_the_choice_the_fact_states(box, fact, stated, form):
    facts = {"applicant_name": "Acme LLC", fact: {"value": stated, "source": "ai"}}
    res, stored, deleted = _editor_save({box: "Off"}, facts, form)
    assert res.status_code == 200
    assert fact in deleted and not (stored["facts"].get(fact) or {}).get("value")


def test_an_untick_never_withdraws_another_choice_and_the_client_no_writes_nothing():
    occ = {"applicant_name": "Acme LLC", "gl_form_type": {"value": "Occurrence", "source": "ai"}}
    _res, stored, deleted = _editor_save({_CM: "Off"}, occ)                     # states Occurrence
    assert stored["facts"]["gl_form_type"]["value"] == "Occurrence" and "gl_form_type" not in deleted
    saved = _apply(_gl_session("Claims-Made"), {_CM: "No"}, _cm_question())     # the client path
    assert saved["facts"]["gl_form_type"]["value"] == "Claims-Made"


def _logged_fact_keys(field_updates, facts, form="ACORD_126"):
    log = AsyncMock()
    _editor_save(field_updates, facts, form, log=log)
    return {c.kwargs["field_name"]: c.kwargs["fact_key"] for c in log.call_args_list}


def test_the_editor_audit_names_no_fact_for_a_box_that_wrote_none():
    limit = {"applicant_name": "Acme LLC", "gl_aggregate": dict(_LIMIT)}
    assert _logged_fact_keys({_AGG: "Yes"}, limit)[_AGG] == _AGG                 # not gl_aggregate
    cm = {"applicant_name": "Acme LLC", "gl_form_type": {"value": "Claims-Made", "source": "ai"}}
    assert _logged_fact_keys({_CM: "Off"}, cm)[_CM] == "gl_form_type"            # it withdrew it
    assert _logged_fact_keys({_OCC: "Yes"}, {"applicant_name": "Acme LLC"})[_OCC] == "gl_form_type"


_SCOPE = "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A"


def test_a_limit_scope_box_never_writes_the_limit_on_either_door():
    session = _gl_session()
    session["facts"]["gl_aggregate"] = dict(_LIMIT)
    q = [{"field_name": _SCOPE, "question": "q", "form_ids": ["ACORD_126"]}]
    saved = _apply(session, {_SCOPE: "Per project"}, q)
    assert saved["facts"]["gl_aggregate"] == _LIMIT
    assert saved["generated_forms"]["ACORD_126"]["field_state"][_SCOPE] == "Per project"
    _res, stored, deleted = _editor_save({_SCOPE: "Per project"},
                                         {"applicant_name": "Acme LLC", "gl_aggregate": dict(_LIMIT)})
    assert stored["facts"]["gl_aggregate"]["value"] == "$2,000,000" and "gl_aggregate" not in deleted


def test_an_editor_edit_on_a_non_primary_row_writes_no_package_fact():
    facts = {"applicant_name": {"value": "Acme LLC", "source": "ai"}}
    log = AsyncMock()
    _res, stored, _ = _editor_save({"NamedInsured_FullName_B": "Second Insured LLC"}, facts, "ACORD_125", log=log)
    assert stored["facts"]["applicant_name"]["value"] == "Acme LLC"
    assert stored["generated_forms"]["ACORD_125"]["field_state"]["NamedInsured_FullName_B"] == "Second Insured LLC"
    assert {c.kwargs["fact_key"] for c in log.call_args_list} == {"NamedInsured_FullName_B"}
    _res, stored, _ = _editor_save({"NamedInsured_FullName_A": "Acme Holdings LLC"}, facts, "ACORD_125")
    assert stored["facts"]["applicant_name"]["value"] == "Acme Holdings LLC"         # row A still writes


# ── "Other: <text>" writes its text, never the prefix ───────────────────────

def _state_values(saved):
    return [str(v) for f in saved["generated_forms"].values() for v in (f.get("field_state") or {}).values()]


def test_other_masonry_lands_as_masonry():
    q = [{"field_name": "construction_type", "question": "q", "form_ids": ["ACORD_140"]}]
    saved = _apply(_package_session(), {"construction_type": "Other: Masonry"}, q)
    assert _value(saved["facts"]["construction_type"]) == "Masonry"
    assert not any(v.lower().startswith("other:") for v in _state_values(saved))
    box = "Construction_ConstructionCode_A"                                    # a raw box question
    saved = _apply(_package_session(), {box: "OTHER: Masonry"},
                   [{"field_name": box, "question": "q", "form_ids": ["ACORD_140"]}])
    assert saved["generated_forms"]["ACORD_140"]["field_state"][box] == "Masonry"
    assert _value(saved["facts"]["construction_type"]) == "Masonry"
    saved = _apply(_building_session(), {"construction_type@loc2": "Other: Masonry"},
                   [_building_question("construction_type")])                 # a building's row
    assert saved["facts"]["property_locations"]["value"][1]["construction_type"] == "Masonry"


def test_the_stored_answer_keeps_other_so_a_draft_reopens_as_other(monkeypatch):
    stored = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending",
              "questions": [{"field_name": "construction_type", "field_type": "select", "question": "q"}]}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_arq_by_token", AsyncMock(return_value=stored))
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, *_ = asyncio.run(arq.submit_arq_answers("tok", {"construction_type": "Other: Masonry"}, "sid", {}))
    assert ok and json.loads(pool.conn.calls[0][1][0]) == {"construction_type": "Other: Masonry"}
    page = (BACKEND.parent / "frontend" / "src" / "components" / "arq" / "ClientQuestionnaire.jsx").read_text(
        encoding="utf-8")
    assert "rawVal.startsWith('Other: ')" in page and "rawVal.slice(7)" in page     # Other + "Masonry"


def test_the_readers_that_read_the_prefix_keep_it():
    from services.premises_interest import kind_of_answer
    q = [{"field_name": "premises_interest", "question": "q", "form_ids": ["ACORD_125"]}]
    saved = _apply(_package_session(), {"premises_interest": "Other: Tenant"}, q)
    assert kind_of_answer(saved["facts"]["premises_interest"]) == ("other", "Tenant")   # not Tenant
    classify = AsyncMock(return_value=False)
    with patch.object(arq, "_classify_other_reason_adverse", classify):
        saved = _apply(_package_session(), {"carrier_marketing_reason": "Other: better pricing"},
                       [{"field_name": "carrier_marketing_reason", "question": "q", "form_ids": []}])
    classify.assert_awaited_once_with("better pricing")
    assert _value(saved["facts"]["carrier_marketing_reason"]) == "Other: better pricing"


def test_no_limit_scope_box_in_any_schema_writes_its_limit():
    """Every box naming what a limit applies to ("...AppliesTo..." /
    "...AppliesPer...") whose door fact is an amount writes nothing - a rule
    over the 17 schemas, not a list of boxes."""
    from services.pdf_service import (_ACORD_FIELD_RULES, _LIMIT_SCOPE_BOX_RE, _all_form_schemas,
                                      _fact_is_measured, box_fact_value)
    hit = set()
    for schema in _all_form_schemas().values():
        for box in schema:
            if not _LIMIT_SCOPE_BOX_RE.search(box):
                continue
            editor = next((k for p, k in _ACORD_FIELD_RULES if k and not k.startswith("_") and p in box), None)
            for fact in {editor, arq._canonical_key(box)}:
                if fact and _fact_is_measured(fact):
                    hit.add(box)
                    for value in ("Per project", "Yes", "Off", "$2,000,000"):
                        assert box_fact_value(box, value, fact) is None, (box, value)
    assert any("LimitAppliesToCode" in b for b in hit) and len(hit) >= 5, sorted(hit)


def test_a_yes_no_box_keeps_its_own_rule():
    # ACORD 126's claims-made box resolves to `gl_form_type` ("Occurrence or Claims-Made").
    box = "GeneralLiability_ClaimsMadeIndicator_A"
    assert arq._canonical_key(box) == "gl_form_type"
    assert arq._answer_check_refusal("gl_form_type", box, "Yes") == ""
    assert arq._answer_check_refusal("gl_form_type", "gl_form_type", "Yes",
                                     {"field_type": "checkbox"}) == ""


def test_an_amount_convention_and_a_broken_validator_are_never_held():
    assert arq._answer_check_refusal("wc_el_each_accident", "wc_el_each_accident", "Statutory") == ""
    broken = {"validate": lambda v: 1 / 0, "format_hint": "x"}
    with patch.dict(FACT_REGISTRY, {"year_built": broken}):
        assert arq._answer_check_refusal("year_built", "year_built", "2050") == ""


def test_use_the_clients_value_on_a_building_hold_never_writes_the_package_fact():
    # The producer's "Use the client's value" door refuses a building key before
    # touching any session: the per-building answer is never the package fact.
    ok, updated = asyncio.run(arq.apply_producer_answer_to_session("s1", "year_built@loc2", "2050"))
    assert (ok, updated) == (False, [])


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


def test_the_submit_still_succeeds(monkeypatch):
    questions = [{"field_name": "year_built", "field_type": "number", "question": "q"},
                 {"field_name": "fire_protection_class", "question": "q"},
                 {"field_name": "year_built@loc2", "field_type": "number", "question": "q"},
                 {"field_name": "fire_protection_class@loc2", "question": "q"}]
    answers = {"year_built": "2050", "fire_protection_class": "15",
               "year_built@loc2": "2050", "fire_protection_class@loc2": "15"}
    stored = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending", "questions": questions}
    pool = _Pool()
    monkeypatch.setattr(arq, "get_arq_by_token", AsyncMock(return_value=stored))
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _msg, _updated, errors = asyncio.run(arq.submit_arq_answers("tok", answers, "sid", {}))
    assert ok and errors == {}
    assert json.loads(pool.conn.calls[0][1][0]) == answers


# ══ FIX 2 - a certificate's date box never writes the proposed term ══════════

def _d(days):
    return (date.today() + timedelta(days=days)).strftime("%m/%d/%Y")


_GL = ("Policy_GeneralLiability_EffectiveDate_A", "Policy_GeneralLiability_ExpirationDate_A")
_TERM = {"effective_date": {"value": _d(20), "source": "ai"},
         "expiration_date": {"value": _d(385), "source": "ai"}}


@pytest.mark.parametrize("stored", [{}, _TERM])
def test_an_acord25_policy_row_date_stays_on_its_box(stored):
    # No term on file: it used to be WRITTEN as the proposed term. A term on file:
    # it used to be HELD as a contradiction of it. Either way it is the 25's own.
    session = {"generated_forms": {"ACORD_25": _form("ACORD_25"), "ACORD_125": _form("ACORD_125")},
               "facts": {"applicant_name": "Acme LLC", **copy.deepcopy(stored)}, "flags": {}}
    q = [{"field_name": f, "question": "q", "form_ids": ["ACORD_25"]} for f in _GL]
    saved = _apply(session, {_GL[0]: _d(-400), _GL[1]: _d(-35)}, q)
    for key in ("effective_date", "expiration_date"):
        assert saved["facts"].get(key) == stored.get(key), key
    assert not saved.get("client_answer_conflicts")
    state = saved["generated_forms"]["ACORD_25"]["field_state"]
    assert state[_GL[0]] == _d(-400) and state[_GL[1]] == _d(-35)
    assert _d(-400) not in saved["generated_forms"]["ACORD_125"]["field_state"].values()


def test_an_acord28_date_never_lands_in_the_125s_proposed_term_box():
    session = {"generated_forms": {"ACORD_28": _form("ACORD_28"), "ACORD_125": _form("ACORD_125")},
               "facts": {"applicant_name": "Acme LLC"}, "flags": {}}
    q = [{"field_name": "Policy_EffectiveDate_A", "question": "q", "form_ids": ["ACORD_28"]}]
    saved = _apply(session, {"Policy_EffectiveDate_A": _d(-400)}, q)
    assert not _value(saved["facts"].get("effective_date"))
    assert saved["generated_forms"]["ACORD_28"]["field_state"]["Policy_EffectiveDate_A"] == _d(-400)
    assert not saved["generated_forms"]["ACORD_125"]["field_state"].get("Policy_EffectiveDate_A")


def test_a_125_proposed_date_answer_still_writes_the_fact():
    session = {"generated_forms": {"ACORD_125": _form("ACORD_125")},
               "facts": {"applicant_name": "Acme LLC"}, "flags": {}}
    q = [{"field_name": "Policy_EffectiveDate_A", "question": "q", "form_ids": ["ACORD_125"]}]
    saved = _apply(session, {"Policy_EffectiveDate_A": _d(30)}, q)
    assert saved["facts"]["effective_date"]["value"] == _d(30)
    assert saved["generated_forms"]["ACORD_125"]["field_state"]["Policy_EffectiveDate_A"] == _d(30)


def test_the_term_refusal_behaves_as_before():
    qs = [{"field_name": "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A", "form_ids": ["ACORD_131"]},
          {"field_name": _GL[1], "form_ids": ["ACORD_25"]},
          {"field_name": "Policy_EffectiveDate_A", "form_ids": ["ACORD_28"]},
          {"field_name": "Policy_ExpirationDate_A", "form_ids": ["ACORD_125"]},
          {"field_name": "effective_date", "form_ids": ["ACORD_25"]}]
    ans = {"UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A": _d(-400), _GL[1]: _d(-35),
           "Policy_EffectiveDate_A": _d(-400)}
    assert ar.client_term_dates(qs, ans) == {}
    ans.update({"Policy_ExpirationDate_A": _d(-35), "effective_date": _d(-400)})
    assert ar.client_term_dates(qs, ans) == {"Policy_ExpirationDate_A": ("expiration_date", _d(-35)),
                                             "effective_date": ("effective_date", _d(-400))}
    # no form ids: the box-name half alone, as before
    assert ar.client_term_dates([{"field_name": "Policy_EffectiveDate_A"}],
                                {"Policy_EffectiveDate_A": _d(5)}) == {
        "Policy_EffectiveDate_A": ("effective_date", _d(5))}


def _old_rule(name, form_ids):
    """The client page's rule as it stood before the shared helper (Z33-SMALL R2)."""
    from services.pdf_service import PROPOSED_TERM_FACTS, proposed_term_fact
    key = arq._canonical_key(name)
    if key not in PROPOSED_TERM_FACTS:
        return key
    if str(name).startswith(key) or any(proposed_term_fact(f, name) == key for f in (form_ids or [None])):
        return key
    return None


def test_the_shared_helper_is_exactly_the_old_rule_on_every_date_box():
    from services.pdf_service import PROPOSED_TERM_FACTS
    seen = 0
    for path in sorted((BACKEND / "forms_schemas").glob("*_schema.json")):
        fid = path.name.replace("_schema.json", "")
        for name in json.loads(path.read_text(encoding="utf-8")):
            if arq._canonical_key(name) not in PROPOSED_TERM_FACTS:
                continue
            seen += 1
            for form_ids in ([fid], [], None, ["ACORD_28", "ACORD_125"], ["ACORD_25"]):
                assert arq.client_answer_fact(name, form_ids) == _old_rule(name, form_ids), (name, form_ids)
    assert seen >= 20
    for name in ("effective_date", "expiration_date", "applicant_name", "year_built@loc2"):
        assert arq.client_answer_fact(name, ["ACORD_25"]) == _old_rule(name, ["ACORD_25"])


def _called(fn, name):
    tree = ast.parse(inspect.getsource(fn).lstrip())
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == name
               for n in ast.walk(tree))


def test_one_helper_for_the_refusal_and_the_apply():
    assert _called(ar.client_term_dates, "client_answer_fact")
    assert _called(arq.apply_arq_answers_to_session, "client_answer_fact")
    assert not _called(ar.client_term_dates, "proposed_term_fact")
    assert not _called(ar.client_term_dates, "_canonical_key")
