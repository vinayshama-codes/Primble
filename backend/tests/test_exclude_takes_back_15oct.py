"""Excluding a document takes back what its AI reading left (15 Oct 2026).

Owner, run `0353c36b`: "after removing that doc, will it also reverse the data
or warnings it has added, and will the forms be updated?" The documents door
already reversed the document's FACTS (retracted, boxes re-stamped, re-scored).
Its AI reading (C103) left three things behind:
  * the "New document says" rows - excluding ACORD_125_FILLED 2.pdf would have
    kept its 42 listed;
  * the boxes it wrote into blank boxes;
  * the "AI held back" rows it added.
And the "different insured" refusal named the package's OWN applicant
("These documents name a different insured (CHOICE ELECTRIC LLC, MERIDIAN
FABRICATION INC)").

The end-to-end tests drive the real documents door (`change_document` ->
`remerge_package`) and the real AI reading on the harness of
`test_new_document_fill_7oct` (model, OCR, extraction and the database stubbed).
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import routes.session_documents_routes as sdr
import services.needs_attention as na
import services.session_documents as sd
from services.session_documents import IntegrityReviewRequired

from tests.test_new_document_fill_7oct import (  # noqa: F401  (the fixture)
    OPS, OPS_BOX, SID, add_narrative, env, form, make_package, run,
)

BACKEND = Path(__file__).resolve().parents[1]


# ══ 1. The box the reading wrote goes back when its document leaves ══════════

def test_exclude_takes_back_the_box_the_reading_wrote(env):
    make_package(env)
    before = copy.deepcopy(form(env))
    env["model"].answers = {OPS_BOX: OPS}
    status = add_narrative(env)
    assert status["boxes_filled"] == 1 and form(env)["field_state"][OPS_BOX] == OPS
    receipts = env["store"].rows[SID][sd.RECEIPTS_KEY]
    assert [(r["form_id"], r["field"], r["doc_ids"]) for r in receipts] == [("ACORD_125", OPS_BOX, ["d-narr"])]
    assert OPS not in str(receipts)                       # a hash, never the value

    result = run(sd.change_document(SID, doc_id="d-narr", action="exclude", user_id="u1"))
    door = result["door"]
    f = form(env)
    assert f["field_state"].get(OPS_BOX) == before["field_state"].get(OPS_BOX)
    assert f["mapped"].get(OPS_BOX) == before["mapped"].get(OPS_BOX)
    assert f["confidence"].get(OPS_BOX) == before["confidence"].get(OPS_BOX)
    assert door["boxes_taken_back"] == 1
    assert door["boxes_by_form"].get("ACORD_125", 0) >= 1 and "ACORD_125" in door["forms_updated"]
    assert env["store"].rows[SID][sd.RECEIPTS_KEY] == []
    assert sd.box_owner(f, OPS_BOX) == "blank"


def test_a_box_a_person_typed_over_stays_when_the_document_leaves(env):
    make_package(env)
    env["model"].answers = {OPS_BOX: OPS}
    add_narrative(env)
    row = env["store"].rows[SID]
    row["generated_forms"]["ACORD_125"]["field_state"][OPS_BOX] = "Electrical contracting"
    row["generated_forms"]["ACORD_125"]["confidence"][OPS_BOX] = "producer"
    result = run(sd.change_document(SID, doc_id="d-narr", action="exclude", user_id="u1"))
    assert form(env)["field_state"][OPS_BOX] == "Electrical contracting"
    assert result["door"]["boxes_taken_back"] == 0


def test_a_document_still_in_the_package_keeps_its_boxes(env):
    make_package(env)
    env["model"].answers = {OPS_BOX: OPS}
    add_narrative(env)
    result = run(sd.change_document(SID, doc_id="d-dec", action="set_type", new_doc_type="dec_page",
                                    user_id="u1"))
    assert form(env)["field_state"][OPS_BOX] == OPS
    assert result["door"]["boxes_taken_back"] == 0
    assert len(env["store"].rows[SID][sd.RECEIPTS_KEY]) == 1


# ══ 2. Pure rules ════════════════════════════════════════════════════════════

def _gen(box_value="", label=None, guard=()):
    state = {"Box_A": box_value} if box_value else {}
    conf = {"Box_A": label} if label else {}
    return {"ACORD_125": {"field_state": dict(state), "mapped": dict(state), "confidence": dict(conf),
                          "client_filled_fields": [], "guard_blanks": list(guard)}}


def _receipt(doc_ids=("d1",), documents=("new.pdf",), value="Written"):
    r = sd.fill_receipt("ACORD_125", "Box_A", None, None, None, value)
    return dict(r, doc_ids=list(doc_ids), documents=list(documents), run_id="r1")


DOCS_IN = [{"doc_id": "d0", "filename": "dec.pdf"}, {"doc_id": "d1", "filename": "new.pdf"}]
DOCS_OUT = [{"doc_id": "d0", "filename": "dec.pdf"},
            {"doc_id": "d1", "filename": "new.pdf", "excluded": True}]


def test_take_back_restores_the_blank_box_and_drops_the_receipt():
    gen = _gen("Written", "low_confidence")
    taken, standing, dropped = sd.take_back_document_fills(gen, [_receipt()], DOCS_OUT)
    assert taken == {"ACORD_125": ["Box_A"]} and standing == [] and dropped == 0
    f = gen["ACORD_125"]
    assert f["field_state"]["Box_A"] is None and "Box_A" not in f["confidence"]
    assert f["_pdf_cache_hash"] == "" and f["pdf_bytes"] is None


def test_take_back_leaves_a_rule_or_a_changed_box():
    for value, label in (("Written", "filled"), ("Other words", "low_confidence"), ("Written", "producer")):
        gen = _gen(value, label)
        taken, standing, _ = sd.take_back_document_fills(gen, [_receipt()], DOCS_OUT)
        assert taken == {} and standing == []
        assert gen["ACORD_125"]["field_state"]["Box_A"] == value


def test_a_receipt_of_an_active_document_stands():
    gen = _gen("Written", "ai_verified")
    taken, standing, _ = sd.take_back_document_fills(gen, [_receipt()], DOCS_IN)
    assert taken == {} and len(standing) == 1


def test_an_evidence_only_document_has_left_the_package():
    docs = [{"doc_id": "d0", "filename": "dec.pdf"},
            {"doc_id": "d1", "filename": "new.pdf", "excluded": True, "evidence_only": True}]
    gen = _gen("Written", "ai_verified")
    taken, _s, _d = sd.take_back_document_fills(gen, [_receipt()], docs)
    assert taken == {"ACORD_125": ["Box_A"]}


def test_held_back_rows_of_the_excluded_document_go_and_generations_own_stay():
    guard = [{"field": "Box_B", "reason": "x", "doc_ids": ["d1"], "documents": ["new.pdf"]},
             {"field": "Box_C", "reason": "generation's own"}]
    gen = _gen(guard=guard)
    taken, _s, dropped = sd.take_back_document_fills(gen, [], DOCS_OUT)
    assert dropped == 1 and [g["field"] for g in gen["ACORD_125"]["guard_blanks"]] == ["Box_C"]
    assert "ACORD_125" in taken                            # the form is re-written


def test_plan_tags_every_row_with_its_documents():
    stored = {"field_state": {}, "mapped": {}, "confidence": {}, "client_filled_fields": [],
              "schema": {}}
    plan = sd.plan_form_fill("ACORD_125", stored, {"Box_A": "Harborline Plumbing"},
                             {"Box_A": "ai_verified"}, {}, documents=["new.pdf"], doc_ids=["d1"],
                             other_insured="Harborline Plumbing & Mechanical, LLC")
    assert plan["suggestions"][0]["doc_ids"] == ["d1"]
    assert plan["suggestions"][0]["documents"] == ["new.pdf"]


# ══ 3. "New document says" rows follow their documents ═══════════════════════

def _suggestion(**extra):
    row = {"id": "docsug_1", "form_id": "ACORD_125", "field": "Box_A", "current": "",
           "suggested": "Harborline", "label": "ai_verified"}
    row.update(extra)
    return row


def test_a_suggestion_of_an_excluded_document_is_not_listed():
    gen = _gen()
    by_id = _suggestion(doc_ids=["d1"], documents=["new.pdf"])
    legacy = _suggestion(documents=["new.pdf"])           # stored before 15 Oct: names only
    for row in (by_id, legacy):
        assert na.document_suggestion_rows(gen, [row], docs=DOCS_IN), row
        assert na.document_suggestion_rows(gen, [row], docs=DOCS_OUT) == [], row
        assert na.document_suggestion_rows(gen, [row]), "no docs = not judged"


def test_a_row_naming_no_document_is_kept():
    assert sd.suggestions_from_active_documents([_suggestion()], DOCS_OUT) == [_suggestion()]


def test_both_readers_pass_the_packages_documents():
    for rel in ("routes/audit_routes.py", "routes/session_documents_routes.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", "")) == "document_suggestion_rows"]
        assert calls, rel
        for c in calls:
            assert "docs" in {k.arg for k in c.keywords}, (rel, ast.get_source_segment(src, c))


def test_the_door_takes_back_and_writes_the_receipts():
    src = (BACKEND / "services" / "session_documents.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "remerge_package")
    body = ast.get_source_segment(src, node)
    assert "take_back_document_fills(generated" in body
    assert "row_update[RECEIPTS_KEY]" in body


# ══ 4. The refusal names only the OTHER insured ══════════════════════════════

def _verdict():
    """The shape of the live record on `0353c36b` when control_dec.pdf arrived."""
    docs = [("a1", "25-26 Business Auto Policy.pdf", "CHOICE ELECTRIC LLC"),
            ("a2", "25-26 Package Policy.pdf", "(no applicant name detected)"),
            ("a3", "25-26 Umbrella Policy.pdf", "CHOICE ELECTRIC LLC"),
            ("m1", "control_dec.pdf", "MERIDIAN FABRICATION INC")]
    return {
        "review_required": True,
        "detected_entities": ["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"],
        "documents": [{"doc_id": i, "filename": f, "applicant": a} for i, f, a in docs],
        "clusters": [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["a1", "a3"], "cluster_id": 0},
                     {"label": "MERIDIAN FABRICATION INC", "doc_ids": ["m1"], "cluster_id": 1}],
    }


def test_the_refusal_names_the_other_insured_not_the_applicant():
    other = sd.other_insured_named({}, _verdict(), [{"doc_id": "m1", "filename": "control_dec.pdf"}])
    assert other == "MERIDIAN FABRICATION INC"
    ex = IntegrityReviewRequired(_verdict(), ["control_dec.pdf"], other_insured=other)
    detail = sdr._integrity_refusal(ex).detail
    assert detail["message"] == ("This document names a different insured (MERIDIAN FABRICATION INC). "
                                 "Nothing was added yet.")
    assert "CHOICE" not in detail["message"] and detail["other_insured"] == other


def test_two_documents_read_as_plural_and_a_changed_one_as_before():
    ex = IntegrityReviewRequired(_verdict(), ["a.pdf", "b.pdf"], other_insured="M INC")
    assert sdr._integrity_refusal(ex).detail["message"].startswith("These documents name a different insured (M INC)")
    assert sdr._integrity_refusal(ex, change="changed").detail["message"].startswith(
        "This document names a different insured (M INC). Nothing was changed.")


def test_with_nobody_to_name_the_applicant_is_still_left_out():
    v = _verdict()
    # the changed document names the applicant itself: the rival is named, never Choice Electric
    other = sd.other_insured_named({}, v, [{"doc_id": "a1"}])
    assert other == "MERIDIAN FABRICATION INC"
    ex = IntegrityReviewRequired(v, ["x.pdf"], other_insured=None)
    assert sdr._integrity_refusal(ex).detail["message"] == "This document names a different insured. Nothing was added yet."


def test_the_door_passes_the_other_insured():
    src = (BACKEND / "services" / "session_documents.py").read_text(encoding="utf-8")
    assert "other_insured=other_insured_named(" in src
