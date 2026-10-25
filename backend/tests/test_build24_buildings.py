"""Build 24 (22 Oct 2026): the client questionnaire asks a building's COPE items
ONCE PER BUILDING on a package with 2+ building rows, labelled by the
building's address ("year_built@loc2"); the answer lands on that building's
row only and only that building's boxes re-stamp. 0-1 building rows: unchanged.
"""
import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import services.arq_service as arq
import services.premises_cope as pc

BACKEND = Path(__file__).resolve().parents[1]
S140 = json.loads((BACKEND / "forms_schemas" / "ACORD_140_schema.json").read_text(encoding="utf-8"))
FORMS = ["ACORD_125", "ACORD_140"]
FLAGS = {"has_property_coverage": True}


def _row(n, line1, **kw):
    return {"location_number": str(n), "address_line1": line1, "address_city": "Denver",
            "address_state": "CO", "address_zip": "80202", **kw}


def _facts(rows):
    return {"applicant_name": "Acme LLC", "property_locations": {"value": rows, "source": "ai"}}


def _qs(facts):
    return arq.generate_arq_questions_from_facts(copy.deepcopy(facts), dict(FLAGS), FORMS, [], [])


def _cope_names(qs):
    return [q["field_name"] for q in qs
            if str(q["field_name"]).split("@")[0] in pc.PER_BUILDING_COPE]


def test_two_buildings_ask_each_building_by_its_address():
    qs = _qs(_facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave")]))
    names = _cope_names(qs)
    assert "roof_year@loc1" in names and "roof_year@loc2" in names
    assert "roof_year" not in names and "year_built" not in names
    by = {q["field_name"]: q for q in qs}
    assert "1 Main St" in by["roof_year@loc1"]["question"]
    assert "2 Oak Ave" in by["roof_year@loc2"]["question"]
    assert "1 Main St" not in by["roof_year@loc2"]["question"]


def test_a_building_that_states_the_item_is_not_asked():
    qs = _qs(_facts([_row(1, "1 Main St", roof_year="2015"), _row(2, "2 Oak Ave")]))
    names = _cope_names(qs)
    assert "roof_year@loc2" in names and "roof_year@loc1" not in names


def test_one_and_zero_buildings_are_unchanged():
    one = _facts([_row(1, "1 Main St")])
    with patch.object(arq, "_split_building_questions", lambda *_a, **_k: None):
        before = _qs(one)
    assert _qs(one) == before
    assert not any("@loc" in n for n in _cope_names(before))
    zero = {"applicant_name": "Acme LLC"}
    with patch.object(arq, "_split_building_questions", lambda *_a, **_k: None):
        before0 = _qs(zero)
    assert _qs(zero) == before0


def test_split_is_a_no_op_below_two_buildings():
    q = [{"field_name": "year_built", "question": "What year?", "_canonical_key": "year_built"}]
    for facts in ({}, _facts([]), _facts([_row(1, "1 Main St")]), _facts([_row(1, "1 Main St"), {}])):
        got = copy.deepcopy(q)
        arq._split_building_questions(got, facts)
        assert got == q


def test_field_names_parse_and_never_collide_with_premises_interest():
    assert pc.parse_building_field("year_built@loc2") == ("year_built", 2)
    assert pc.parse_building_field("premises_interest@loc2") is None
    assert pc.parse_building_field("year_built") is None
    import services.premises_interest as pi
    assert pi.parse_location_field("year_built@loc2") is None


def _session(rows):
    return {"generated_forms": {"ACORD_140": {
        "schema": S140,
        "field_state": {"BuildingImprovement_RoofingYear_A": "", "BuildingImprovement_RoofingYear_B": ""},
        "confidence": {}}},
        "facts": _facts(rows), "flags": dict(FLAGS)}


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


def test_building_two_answer_lands_on_its_own_row_and_boxes_only():
    session = _session([_row(1, "1 Main St"), _row(2, "2 Oak Ave")])
    questions = [{"field_name": "roof_year@loc2", "question": "Roof year?", "form_ids": []}]
    saved = _apply(session, {"roof_year@loc2": "2019"}, questions)
    rows = saved["facts"]["property_locations"]["value"]
    assert rows[1]["roof_year"] == "2019"
    assert not rows[0].get("roof_year")
    assert "roof_year" not in saved["facts"]           # never the package fact
    form = saved["generated_forms"]["ACORD_140"]
    assert form["field_state"]["BuildingImprovement_RoofingYear_B"] == "2019"
    assert form["confidence"]["BuildingImprovement_RoofingYear_B"] == "client_arq"
    assert not str(form["field_state"].get("BuildingImprovement_RoofingYear_A") or "").strip()
    assert "BuildingImprovement_RoofingYear_A" not in form["confidence"]


def test_restamp_reads_only_its_own_row():
    facts = _facts([_row(1, "1 Main St", roof_year="2001"), _row(2, "2 Oak Ave", roof_year="2019")])
    gen = {"ACORD_140": {"schema": S140, "field_state": {"BuildingImprovement_RoofingYear_A": "1990"},
                         "confidence": {"BuildingImprovement_RoofingYear_A": "producer"}}}
    assert arq._restamp_building_row(gen, facts, 2, "roof_year") == ["ACORD_140"]
    state = gen["ACORD_140"]["field_state"]
    assert state["BuildingImprovement_RoofingYear_A"] == "1990"      # building 1 untouched
    assert state["BuildingImprovement_RoofingYear_B"] == "2019"


# ── Review fix 4: a building answer takes its package question's check ──────

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


def _submit(monkeypatch, questions, answers):
    stored = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending", "questions": questions}

    async def _get(_token):
        return stored
    pool = _Pool()
    monkeypatch.setattr(arq, "get_arq_by_token", _get)
    monkeypatch.setattr(arq, "get_pool", lambda: pool)
    ok, _msg, _updated, errors = asyncio.run(arq.submit_arq_answers("tok", answers, "sid", {}))
    saved = json.loads(pool.conn.calls[0][1][0]) if pool.conn.calls else {}
    return ok, errors, saved


def test_a_building_answer_gets_exactly_its_package_questions_check():
    values = ("1998", "2050", "abc", "19x8", "15", "3", "$750,000", "lots", "Frame",
              "Yes", "No", "None", "not sure", "")
    for fact in pc.PER_BUILDING_COPE:
        for v in values:
            assert arq._clean_answer_ex(v, f"{fact}@loc2") == arq._clean_answer_ex(v, fact), (fact, v)


def test_a_bad_building_answer_is_refused_at_submit_like_the_package_question(monkeypatch):
    for name, ftype, bad in (("year_built", "number", "abc"),
                             ("property_building_value", "currency", "lots")):
        for field in (name, f"{name}@loc2"):
            ok, errors, _ = _submit(monkeypatch, [{"field_name": field, "field_type": ftype,
                                                   "question": "q"}], {field: bad})
            assert not ok and field in errors
    ok, errors, saved = _submit(monkeypatch, [{"field_name": "year_built@loc2", "field_type": "number",
                                               "question": "q"}], {"year_built@loc2": "1998"})
    assert ok and not errors and saved == {"year_built@loc2": "1998"}


# ── Review fix 5: an answer never lands on a row that moved since sending ────

def test_each_question_carries_the_row_it_named():
    qs = _qs(_facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave", building_number="2")]))
    by = {q["field_name"]: q for q in qs}
    assert by["roof_year@loc1"]["row_address"].startswith("1 Main St")
    assert by["roof_year@loc2"]["row_address"].startswith("2 Oak Ave")
    assert by["roof_year@loc2"]["row_building"] == "2"
    assert by["premises_interest@loc2"]["row_address"].startswith("2 Oak Ave")
    src = (BACKEND / "routes" / "arq_routes.py").read_text(encoding="utf-8")
    assert "for _rk in (ROW_ADDRESS_KEY, ROW_BUILDING_KEY):" in src     # send keeps them


def test_a_reordered_list_after_sending_never_writes_to_the_wrong_row():
    sent = _facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave")])
    questions = [q for q in _qs(sent) if q["field_name"] in ("roof_year@loc2", "premises_interest@loc2")]
    assert len(questions) == 2
    # The list moved before the answers were applied: Oak Ave is now row 1.
    session = _session([_row(2, "2 Oak Ave"), _row(1, "1 Main St")])
    from services.answer_options import PREMISES_INTEREST_OPTIONS
    tenant = next(o for o in PREMISES_INTEREST_OPTIONS if o.lower().startswith("tenant"))
    saved = _apply(session, {"roof_year@loc2": "2019", "premises_interest@loc2": tenant}, questions)
    rows = saved["facts"]["property_locations"]["value"]
    assert not any(r.get("roof_year") for r in rows)
    assert not any(r.get("is_tenant") for r in rows)
    state = saved["generated_forms"]["ACORD_140"]["field_state"]
    assert not str(state.get("BuildingImprovement_RoofingYear_A") or "").strip()
    assert not str(state.get("BuildingImprovement_RoofingYear_B") or "").strip()
    # The same answers on the list as it was sent land on Oak Ave.
    saved = _apply(_session([_row(1, "1 Main St"), _row(2, "2 Oak Ave")]),
                   {"roof_year@loc2": "2019"}, questions)
    assert saved["facts"]["property_locations"]["value"][1]["roof_year"] == "2019"


def test_the_row_check_reads_address_and_a_named_building():
    import services.premises_interest as pi
    facts = _facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave", building_number="2")])
    assert pi.row_is_still(facts, 2, {})                                     # an older questionnaire
    assert pi.row_is_still(facts, 2, {"row_address": "2 OAK AVE, Denver CO 80202"})
    assert pi.row_is_still(facts, 2, {"row_address": "2 Oak Ave, Denver, CO 80202",
                                      "row_building": ""})                  # numbered after sending
    assert not pi.row_is_still(facts, 2, {"row_address": "2 Oak Ave, Denver, CO 80202",
                                          "row_building": "3"})
    assert not pi.row_is_still(facts, 1, {"row_address": "2 Oak Ave, Denver, CO 80202"})
    assert not pi.row_is_still(facts, 5, {"row_address": "2 Oak Ave, Denver, CO 80202"})


# ── Review item: another policy's date box never writes the proposed term ────

def _form(fid):
    schema = json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))
    return {"schema": schema, "field_state": {}, "confidence": {}}


def test_another_policys_date_box_is_not_the_proposed_term():
    for box in ("UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A",
                "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A",
                "OtherPolicy_PolicyEffectiveDate_A", "OtherPolicy_PolicyExpirationDate_A"):
        assert arq._canonical_key(box) is None, box
    assert arq._canonical_key("Policy_EffectiveDate_A") == "effective_date"
    assert arq._canonical_key("Policy_ExpirationDate_A") == "expiration_date"
    assert arq._canonical_key("effective_date") == "effective_date"


def test_a_131_underlying_date_answer_stays_on_its_box():
    # No proposed term on file, so nothing holds the answer (F7): before the
    # fix it was written as the PROPOSED effective / expiration date.
    session = {"generated_forms": {"ACORD_131": _form("ACORD_131"), "ACORD_125": _form("ACORD_125")},
               "facts": {"applicant_name": "Acme LLC"}, "flags": {}}
    eff, exp = ("UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A",
                "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A")
    questions = [{"field_name": f, "question": "q", "form_ids": ["ACORD_131"]} for f in (eff, exp)]
    saved = _apply(session, {eff: "01/01/2024", exp: "01/01/2025"}, questions)
    for fact in ("effective_date", "expiration_date"):
        held = saved["facts"].get(fact)
        assert not (held.get("value") if isinstance(held, dict) else held), fact
    state = saved["generated_forms"]["ACORD_131"]["field_state"]
    assert state[eff] == "01/01/2024" and state[exp] == "01/01/2025"
    assert "01/01/2024" not in saved["generated_forms"]["ACORD_125"]["field_state"].values()


def test_a_125_proposed_date_answer_still_writes_the_fact():
    session = {"generated_forms": {"ACORD_125": _form("ACORD_125")},
               "facts": {"applicant_name": "Acme LLC"}, "flags": {}}
    questions = [{"field_name": "Policy_EffectiveDate_A", "question": "q", "form_ids": ["ACORD_125"]}]
    saved = _apply(session, {"Policy_EffectiveDate_A": "08/01/2027"}, questions)
    assert saved["facts"]["effective_date"]["value"] == "08/01/2027"


def test_non_answers_write_nothing_and_yes_no_is_kept():
    facts = _facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave")])
    assert not pc.write_building_answer(facts, "year_built", 2, "not sure")
    assert not pc.write_building_answer(facts, "year_built", 9, "1998")
    assert pc.write_building_answer(facts, "sprinkler_system", 2, "No")
    assert facts["property_locations"]["value"][1]["sprinkler"] == "No"
    assert pc.write_building_answer(facts, "year_built", 2, "1998")
    assert facts["property_locations"]["value"][1]["year_built"] == "1998"
    assert not facts["property_locations"]["value"][0].get("year_built")
