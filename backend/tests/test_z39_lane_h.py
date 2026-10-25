"""Z39 lane H (25 Oct 2026).

1. The narrative says claims and the answer says "No claims": the Loss History
   plan lists every step the honest answer needs from the start - the card's
   answer first, then "loss runs requested", then the upload - and the page's
   numbers add up to 100 - score (with or without a loss pillar in the input).
2. A stated or silent "No agreed value" never stands in for the coinsurance
   percentage: the questionnaire asks coinsurance until agreed value is
   AFFIRMED (`coverage_evidence.agreed_value_affirmed`).
3. The builders-risk project-value stop names no form: ACORD 133 is the Workers
   Compensation Assigned Risk section and no form of the 17 prints the value.
4. The remarks keep which words the person typed (`typed_parts`): an appended
   explanation never turns the document's sentence it was appended to into the
   producer's statement.
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os

import pytest

from services import arq_service as A
from services import cross_form_validator as CFV
from services import sqs_service as S
from services.loss_history_state import (
    TYPED_PARTS_KEY, claims_question_answers, narrative_claims_stance, person_narrative_texts,
    person_typed_parts,
)

NO_CLAIMS, HAD_CLAIMS = claims_question_answers()
REMARKS = "additional_remarks_text"

_spec = importlib.util.spec_from_file_location(
    "_mismatch", os.path.join(os.path.dirname(__file__), "test_build26_loss_narrative_mismatch.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
J = M.J


def _env(v, source="producer"):
    return {"value": v, "source": source, "confidence": "producer"}


# ── 1. Every step the honest answer needs, listed from the start ─────────────
def _keys(plan):
    return [s["key"] for s in plan or []]


@pytest.mark.parametrize("age", [15, 3, None])
def test_the_plan_lists_requested_and_upload_beside_the_card(age):
    row = M._row(J.NARRATIVE + " " + M.CLAIMS_TEXT, NO_CLAIMS)
    if age != 15:
        row["facts"]["years_in_business"] = (_env(str(age)) if age is not None else
                                             {"value": None, "value_state": "not_applicable",
                                              "source": "producer"})
    pkg = J._page(row)
    plan = pkg["loss_plan"]
    assert _keys(plan)[:2] == ["narrative", "pending"], _keys(plan)
    assert plan[1]["points"] > 0
    items = pkg["review_plan"]["items"]
    fields = [it.get("field") or it.get("step") for it in items]
    assert "loss_run_status" in fields
    assert sum(i["points"] for i in items) + int(pkg["review_plan"].get("left") or 0) \
        == 100 - J._score(pkg)


def test_with_no_loss_pillar_in_the_input_the_steps_are_the_same():
    row = M._row(J.NARRATIVE + " " + M.CLAIMS_TEXT, NO_CLAIMS)
    pkg = J._page(row)
    without = {k: v for k, v in pkg["pillars"].items() if k != "loss_history_alignment"}
    a = S.loss_history_plan(row["facts"], row["flags"], row["docs"], without)
    b = S.loss_history_plan(row["facts"], row["flags"], row["docs"], pkg["pillars"])
    assert _keys(a) == _keys(b) == ["narrative", "pending", "upload"]
    assert [s["points"] for s in a] == [s["points"] for s in b]


def test_doing_the_listed_steps_in_order_reaches_100():
    row = M._row(J.NARRATIVE + " " + M.CLAIMS_TEXT, NO_CLAIMS)
    J._answer(row, M.INDICATOR, HAD_CLAIMS)
    J._answer(row, "loss_run_status", J.REQUESTED)
    J._upload(row, J._required_years(row))
    assert J._score(J._page(row)) == 100


# ── 2. Coinsurance vs agreed value in the questionnaire ──────────────────────
def _doc(v):
    return {"value": v, "source": "document", "confidence": "high"}


_PROPERTY = {"applicant_name": _doc("Acme LLC"), "property_building_value": _doc("$1,000,000"),
             "locations": _doc([{"address": "1 Main St"}]), "occupancy_type": _doc("Office"),
             "construction_type": _doc("Frame")}


def _with_agreed(value):
    f = dict(_PROPERTY)
    if value is not None:
        f["agreed_value_endorsement"] = value if isinstance(value, dict) else _doc(value)
    return f


_NOT_AFFIRMED = [None, False, "False", "No", "N", "No - coinsurance applies",
                 _env("No"), _env("No agreed value")]
_AFFIRMED = [True, "Yes", _env("Yes - agreed value endorsement applies")]


@pytest.mark.parametrize("value", _NOT_AFFIRMED)
def test_facts_path_asks_coinsurance_until_agreed_value_is_affirmed(value):
    qs = A.generate_arq_questions_from_facts(_with_agreed(value), {"has_property_coverage": True},
                                             ["ACORD_140"], [], [])
    assert "coinsurance_percentage" in {q["field_name"] for q in qs}


@pytest.mark.parametrize("value", _AFFIRMED)
def test_an_affirmed_agreed_value_answers_the_coinsurance_question(value):
    qs = A.generate_arq_questions_from_facts(_with_agreed(value), {"has_property_coverage": True},
                                             ["ACORD_140"], [], [])
    assert "coinsurance_percentage" not in {q["field_name"] for q in qs}


def _form_path(facts):
    schema = json.load(open(os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                                         "ACORD_140_schema.json")))
    flags = {"has_property_coverage": True}
    sqs = S.calculate_sqs(facts, flags, {}, schema, ["ACORD_140"], [], [], 0, form_id="ACORD_140")
    gf = {"ACORD_140": {"confidence": {"CommercialProperty_Premises_CoinsurancePercent_A":
                                       "low_confidence"},
                        "mapped": {}, "sqs": sqs, "schema": schema}}
    qs = asyncio.run(A.generate_arq_questions(facts, flags, gf, [], []))
    return {A._canonical_key(q["field_name"]) for q in qs}, sqs


@pytest.mark.parametrize("value", [False, "False", _env("No")])
def test_form_path_asks_coinsurance_on_a_no(value):
    keys, sqs = _form_path(_with_agreed(value))
    assert "coinsurance_percentage" in keys
    assert any(r.get("rec_id") == "rec_coinsurance" for r in sqs["recommendations"])


def test_form_path_drops_coinsurance_on_an_affirmed_agreed_value():
    keys, sqs = _form_path(_with_agreed("Yes"))
    assert "coinsurance_percentage" not in keys
    assert not any(r.get("rec_id") == "rec_coinsurance" for r in sqs["recommendations"])


def test_a_stated_no_is_still_an_answer_to_the_agreed_value_question():
    present = A._present_fact_keys(_with_agreed(_env("No")))
    assert "agreed_value_endorsement" in present


# ── 3. Builders risk names no form ───────────────────────────────────────────
def test_builders_risk_stop_never_names_acord_133():
    facts = {"builders_risk_project_address": {"value": "12 Site Rd", "source": "document"}}
    issues = CFV._check_builders_risk_project_value(facts, {"has_builders_risk": True}, set())
    assert len(issues) == 1 and issues[0]["code"] == "builders_risk_project_value_missing"
    assert issues[0]["forms"] == []
    hard, soft, _adv = CFV.split_cross_form_issues(issues)
    assert hard and "ACORD 133" not in hard[0] and "Affects" not in hard[0]


def test_no_schema_prints_a_builders_risk_project_value():
    base = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    for name in os.listdir(base):
        text = open(os.path.join(base, name)).read().lower()
        assert "projectcost" not in text and "project cost" not in text, name
    assert "builders risk" not in open(os.path.join(base, "ACORD_133_schema.json")).read().lower()


# ── 4. The words the person typed ────────────────────────────────────────────
DOC_SENTENCE = "Loss History Discussion: the applicant reports no claims or losses in the past five years."
TYPED = "Loss history shows 2 claims in 2025, both closed."


def test_appending_to_a_documents_remarks_records_only_the_new_words():
    existing = {"value": DOC_SENTENCE, "source": "document", "confidence": "high"}
    assert A.appended_typed_parts(existing, TYPED) == [TYPED]


def test_appending_to_a_legacy_typed_row_keeps_today_s_reading():
    existing = _env("Our safety program is written.")
    assert A.appended_typed_parts(existing, TYPED) == ["Our safety program is written.", TYPED]


def test_appending_twice_keeps_both_parts_once():
    first = {"value": DOC_SENTENCE + "\n" + TYPED, "source": "producer", TYPED_PARTS_KEY: [TYPED]}
    assert A.appended_typed_parts(first, "More text.") == [TYPED, "More text."]
    assert A.appended_typed_parts(first, TYPED) == [TYPED]


def test_the_stance_reads_only_the_typed_parts():
    f = {"applicant_name": _env("Choice Electric LLC"),
         REMARKS: {"value": DOC_SENTENCE + "\n" + TYPED, "source": "producer",
                   "confidence": "filled", TYPED_PARTS_KEY: [TYPED]}}
    assert person_narrative_texts(f) == [TYPED]
    assert narrative_claims_stance(f) == "claims"
    # Before: the document's "no claims" counted as typed -> "both" -> no stance.
    legacy = copy.deepcopy(f)
    legacy[REMARKS].pop(TYPED_PARTS_KEY)
    assert narrative_claims_stance(legacy) is None


def test_a_documents_no_claims_sentence_never_raises_the_mismatch():
    f = {"applicant_name": _env("Choice Electric LLC"),
         REMARKS: {"value": DOC_SENTENCE + "\nOur safety program is written.", "source": "producer",
                   "confidence": "filled", TYPED_PARTS_KEY: ["Our safety program is written."]},
         M.INDICATOR: _env(HAD_CLAIMS)}
    from services.loss_history_state import narrative_answer_mismatch
    assert narrative_claims_stance(f) is None
    assert narrative_answer_mismatch(f) is None


def test_a_part_edited_out_of_the_text_no_longer_counts():
    raw = {"value": "Something else entirely.", "source": "producer", TYPED_PARTS_KEY: [TYPED]}
    assert person_typed_parts(raw) == []
    assert person_typed_parts({"value": "x", "source": "producer"}) is None


def _fake_session(remarks):
    return {"facts": {"applicant_name": _env("Choice Electric LLC"), REMARKS: remarks},
            "flags": {}, "generated_forms": {}, "docs": []}


def _run_append(monkeypatch, session, text, direct=False):
    store = {"row": copy.deepcopy(session)}

    async def _get(_sid, *_a, **_k):
        return copy.deepcopy(store["row"])

    async def _upd(_sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            if k == "facts":
                store["row"]["facts"].update(copy.deepcopy(v))
            else:
                store["row"][k] = copy.deepcopy(v)
        return True

    async def _none(*_a, **_k):
        return None

    import repositories.session_repository as sr
    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)
    monkeypatch.setattr(A, "store_narrative_reading", _none)
    for name in ("get_processing_session", "upd_processing_session"):
        if hasattr(A, name):
            monkeypatch.setattr(A, name, _get if name.startswith("get") else _upd)
    if direct:
        ok = asyncio.run(A.apply_producer_answer_to_session("s", REMARKS, text))
    else:
        ok = asyncio.run(A.append_producer_narrative("s", text))
    return ok, store["row"]["facts"][REMARKS]


def test_the_append_door_stores_the_parts(monkeypatch):
    ok, env = _run_append(monkeypatch, _fake_session(
        {"value": DOC_SENTENCE, "source": "document", "confidence": "high"}), TYPED)
    assert ok and ok[0]
    assert env["value"].startswith(DOC_SENTENCE) and env["value"].endswith(TYPED)
    assert env[TYPED_PARTS_KEY] == [TYPED]


def test_a_direct_write_of_the_remarks_is_wholly_typed(monkeypatch):
    whole = DOC_SENTENCE + " " + TYPED
    ok, env = _run_append(monkeypatch, _fake_session(
        {"value": DOC_SENTENCE, "source": "document", "confidence": "high"}), whole, direct=True)
    assert ok and ok[0]
    assert env[TYPED_PARTS_KEY] == [env["value"]]


def test_open_again_restores_the_earlier_parts():
    from services.issue_fix_undo import capture, plan_undo
    before = _fake_session({"value": DOC_SENTENCE, "source": "producer", "confidence": "filled",
                            TYPED_PARTS_KEY: []})
    after = copy.deepcopy(before)
    after["facts"][REMARKS] = {"value": DOC_SENTENCE + "\n" + TYPED, "source": "producer",
                               "confidence": "filled", TYPED_PARTS_KEY: [TYPED]}
    receipt = capture(before, after)
    status, plan = plan_undo(after, receipt)
    assert status == "ok"
    assert plan["set_facts"][REMARKS][TYPED_PARTS_KEY] == []


# ── 25 Oct live 78d56a72: an excess dec read as "Umbrella / Excess Liability" ──

def test_an_umbrella_excess_name_beside_a_plain_umbrella_is_the_layer_above():
    from services import extraction_service as E

    def doc(name, line, carrier, limit):
        return {"filename": name, "doc_type": "dec_page", "facts": {
            "umbrella_limit": {"value": limit, "source": "ai"},
            "carrier_name": {"value": carrier, "source": "ai"},
            "coverage_lines": {"value": [{"line": line, "carrier": carrier, "limit": limit}],
                               "source": "ai"}}}
    for excess_name in ("Umbrella / Excess Liability", "Excess (Following Form) Liability"):
        docs = [doc("Umbrella Policy.pdf", "Commercial Liability Umbrella",
                    "AMERISURE MUTUAL INSURANCE COMPANY", "$5,000,000"),
                doc("Excess Umbrella Policy.pdf", excess_name,
                    "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA", "$4,000,000")]
        mf = {}
        E._settle_policy_level_scalars(mf, docs)
        assert E._fv(mf, "umbrella_limit") == "$5,000,000", excess_name


def test_an_umbrella_excess_row_of_another_carrier_is_named_the_excess_layer():
    from services import extraction_service as E

    def doc(name, line, carrier):
        return {"filename": name, "facts": {
            "carrier_name": {"value": carrier, "source": "ai"},
            "coverage_lines": {"value": [{"line": line, "carrier": carrier}], "source": "ai"}}}
    docs = [doc("U.pdf", "Commercial Liability Umbrella", "Amerisure Mutual Insurance Company"),
            doc("X.pdf", "Umbrella / Excess Liability", "Travelers Property Casualty Company of America")]
    assert E.name_the_excess_layer(docs) == ["X.pdf: Umbrella / Excess Liability"]
    row = docs[1]["facts"]["coverage_lines"]["value"][0]
    assert row["line"] == "Excess Liability" and row["line_as_printed"] == "Umbrella / Excess Liability"
    # One carrier printing both names is one policy - untouched.
    same = [doc("U.pdf", "Commercial Liability Umbrella", "Amerisure"),
            doc("X.pdf", "Umbrella / Excess Liability", "Amerisure")]
    assert E.name_the_excess_layer(same) == []
    # A package that already names its excess layer - untouched.
    named = [doc("U.pdf", "Umbrella / Excess Liability", "Amerisure"),
             doc("X.pdf", "Excess (Following Form) Liability", "Travelers")]
    assert E.name_the_excess_layer(named) == []
    # No plain umbrella beside it - untouched.
    alone = [doc("X.pdf", "Umbrella / Excess Liability", "Travelers")]
    assert E.name_the_excess_layer(alone) == []
