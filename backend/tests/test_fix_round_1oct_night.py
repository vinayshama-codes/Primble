"""The fix round after the 1 Oct 2026 audit (25sepChanges.md, "Fix round after
the audit"): the parts with no test file of their own.

1. The Sign button signs for the PRODUCER only - on every real template.
2. "AI held back" never repeats a refused Yes/No answer; the applicant's own
   steps are a row of their own and never reach the underwriter cover.
3. Point Q - questions answered and details checked are counted apart.
4. Item 17 - a box is green "Client" only while the client's value is in it.
5. Unticking "Check if none" is not a claims answer.
6. Item 19 - ONE number per card: what answering it does to the package.
7. The stored cards take the number the panel shows.
8. The policy-wording check reads its own pattern (a duplicate module name
   had silently swapped it for another check's).
"""
import asyncio
import base64
import copy
import io
import json
import os
from pathlib import Path

import pytest

import services.audit_service as au
import services.needs_attention as na
import services.signature_boxes as sb
import services.sqs_service as S
from services import arq_service as arq
from services import loss_history_state as lhs
from services import pdf_service as ps

BACKEND = Path(__file__).resolve().parents[1]
SCHEMAS = sorted((BACKEND / "forms_schemas").glob("ACORD_*_schema.json"))


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


def _boxes(form_id):
    out = {"producer": [], "applicant": [], None: []}
    for field, meta in _schema(form_id).items():
        box = sb.signature_box(field, (meta or {}).get("tu") or "", (meta or {}).get("ft") or "")
        if box:
            out[box[1]].append((field, box[0]))
    return out


# ══ 1. The Sign button signs for the producer only ═══════════════════════════

@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.name[:-12])
def test_every_signature_box_names_its_signer(path):
    form_id = path.name[:-12]
    boxes = _boxes(form_id)
    assert not boxes[None], boxes[None]                     # nothing unprovable
    for field, _kind in boxes["producer"]:
        assert field.startswith("Producer_"), field
    for field, _kind in boxes["applicant"]:
        assert field.startswith("NamedInsured_"), field


def test_the_forms_with_an_applicant_line_are_the_applications():
    with_applicant = {p.name[:-12] for p in SCHEMAS if _boxes(p.name[:-12])["applicant"]}
    assert {"ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_133",
            "ACORD_137_CA", "ACORD_137_CO", "ACORD_138_CA", "ACORD_138_CO", "ACORD_140",
            "ACORD_141", "ACORD_160"} == with_applicant
    # certificates carry the producer's signature only
    for fid in ("ACORD_25", "ACORD_28"):
        assert _boxes(fid)["producer"] and not _boxes(fid)["applicant"]


def _signature_png():
    from PIL import Image
    img = Image.new("RGBA", (120, 40), (255, 255, 255, 0))
    for x in range(10, 110):
        img.putpixel((x, 20), (0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _template(form_id):
    from config.settings import TEMPLATE_DIR
    meta = json.loads((BACKEND / "forms_database" / f"{form_id}.json").read_text())
    return os.path.join(TEMPLATE_DIR, meta["template_file"])


def _widgets_and_fields(pdf_bytes):
    import pikepdf
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    widgets, fields = set(), set()
    for page in pdf.pages:
        for annot in list(page.get("/Annots") or []):
            if "/Widget" not in str(annot.get("/Subtype", "")):
                continue
            t = annot.get("/T")
            if t is None and annot.get("/Parent") is not None:
                t = annot.get("/Parent").get("/T")
            widgets.add(str(t))

    def walk(arr):
        for item in list(arr or []):
            if item.get("/T") is not None:
                fields.add(str(item.get("/T")))
            if item.get("/Kids"):
                walk(item.get("/Kids"))
    acro = pdf.Root.get("/AcroForm")
    if acro is not None:
        walk(acro.get("/Fields"))
    return widgets, fields


@pytest.mark.parametrize("form_id", ["ACORD_125", "ACORD_131", "ACORD_137_CO", "ACORD_25"])
def test_signing_paints_the_producers_box_and_leaves_the_applicants(form_id):
    """Functional, on the real template: the painter removes a signature box's
    widget and draws the image there. The producer's box is painted; every
    applicant box (signature, date, initials) is still a live form field, and no
    placeholder name the door used to hide it is left behind."""
    tpl = _template(form_id)
    if not os.path.exists(tpl):
        pytest.skip(f"template missing: {tpl}")
    schema = _schema(form_id)
    boxes = _boxes(form_id)
    out = sb.inject_producer_signature(tpl, {f: "" for f in schema}, {}, _signature_png())
    widgets, fields = _widgets_and_fields(out)
    for field, kind in boxes["producer"]:
        if kind == sb.KIND_SIGNATURE:
            assert field not in widgets, f"{field} was not painted"
    for field, _kind in boxes["applicant"]:
        assert field in widgets and field in fields, f"{field} lost"
    assert not [f for f in fields if f.startswith("__primble_hold_")]


def test_the_old_painter_signed_the_applicants_line():
    """The guard for the guard: without the door, the applicant's box is gone."""
    tpl = _template("ACORD_125")
    if not os.path.exists(tpl):
        pytest.skip("template missing")
    schema = _schema("ACORD_125")
    out = ps.inject_signature_into_pdf(tpl, {f: "" for f in schema}, {}, _signature_png())
    widgets, _ = _widgets_and_fields(out)
    assert "NamedInsured_Signature_A" not in widgets


def test_a_signed_form_from_before_the_fix_is_repainted_not_served():
    tpl = _template("ACORD_125")
    if not os.path.exists(tpl):
        pytest.skip("template missing")
    meta = json.loads((BACKEND / "forms_database" / "ACORD_125.json").read_text())
    session = {"generated_forms": {"ACORD_125": {
        "form": meta, "field_state": {}, "confidence": {}, "signature_applied": True,
        "signature_b64": _signature_png(), "pdf_bytes": b"OLD-PDF", "_pdf_cache_hash": "x",
        "signature_scope": None}}}
    out = sb.regenerate_pdf_for_form(session, "ACORD_125")
    assert out != b"OLD-PDF" and out.startswith(b"%PDF")
    assert session["generated_forms"]["ACORD_125"]["signature_scope"] == sb.SIGNATURE_SCOPE
    # ...and the door's own cache is reused from then on
    assert sb.regenerate_pdf_for_form(session, "ACORD_125") == out


def test_marking_signed_boxes_touches_the_producers_only():
    schema = _schema("ACORD_125")
    data = {"NamedInsured_Signature_A": "x", "NamedInsured_SignatureDate_A": "10/01/2026",
            "Producer_AuthorizedRepresentative_Signature_A": "y"}
    conf = {"NamedInsured_Signature_A": "low_confidence"}
    marked = sb.mark_producer_boxes_signed("ACORD_125", {"schema": schema}, data, conf)
    assert marked == ["Producer_AuthorizedRepresentative_Signature_A"]
    assert data["NamedInsured_Signature_A"] == "x" and conf["NamedInsured_Signature_A"] == "low_confidence"
    assert data["Producer_AuthorizedRepresentative_Signature_A"] == ""


def test_a_box_whose_name_and_tooltip_disagree_belongs_to_nobody():
    tip = "Sign here: Accommodates the signature of the applicant or named insured."
    assert sb.signature_box("Producer_AuthorizedRepresentative_Signature_A", tip, "/Tx")[1] is None
    assert not sb.is_producer_signature("Producer_AuthorizedRepresentative_Signature_A", tip, "/Tx")


# ══ 2. Held back, applicant steps, the cover ═════════════════════════════════

S125 = _schema("ACORD_125")


@pytest.mark.parametrize("refused", ["Y", "N", "Yes", "No", "y"])
def test_a_refused_yes_no_answer_is_never_repeated(refused):
    reason, quotable = na.held_back(S125, "CommercialPolicy_Question_ABCCode_A", refused, {})
    assert reason == na._QUESTION_UNANSWERED and quotable is False
    assert f'"{refused}"' not in reason and "The AI answered" not in reason


def test_a_value_from_another_item_is_described_not_quoted():
    facts = {"gl_class_codes": {"value": ["7383"]}}
    reason, quotable = na.held_back(S125, "NamedInsured_SICCode_A", "7383", facts)
    assert "7383" not in reason and quotable is False


def test_the_applicants_steps_never_reach_the_cover():
    assert na.is_producer_todo_row("fieldqa_attn_ACORD_125_missing_applicant")
    assert na.is_producer_todo_row("fieldmap_ACORD_127_AdditionalInterest_FullName_C")
    assert not na.is_producer_todo_row("fieldqa_attn_ACORD_125_missing")
    assert not na.is_producer_todo_row("rec_contact_name")
    assert not na.is_producer_todo_row(None)


# ══ 3. Point Q - questions and checks counted apart ══════════════════════════

_QS = [{"field_name": "a"}, {"field_name": "b"}, {"field_name": "c"},
       {"field_name": "x", "confirm": True}, {"field_name": "y", "confirm": True}]


def test_questions_and_checks_are_counted_apart():
    items = [{"field_name": "a", "kind": "answer"}, {"field_name": "b", "kind": "not_sure"},
             {"field_name": "c", "kind": "blank"}, {"field_name": "x", "kind": "confirmed"},
             {"field_name": "y", "kind": "blank"}]
    c = arq.response_counts(_QS, items)
    assert (c["questions_asked"], c["questions_answered"]) == (3, 1)
    assert (c["checks_asked"], c["checks_done"]) == (2, 1)
    assert c["not_sure_count"] == 1
    assert c["response_summary"] == "1 of 3 questions answered - 1 of 2 details checked"


def test_a_corrected_check_counts_as_checked():
    """A client who CORRECTS a value we had on file has checked it."""
    c = arq.response_counts([{"field_name": "x", "confirm": True}],
                            [{"field_name": "x", "kind": "answer"}])
    assert (c["checks_asked"], c["checks_done"], c["questions_asked"]) == (1, 1, 0)
    assert c["response_summary"] == "1 of 1 detail checked"


def test_without_the_questions_only_a_confirmation_is_a_check():
    c = arq.response_counts(None, [{"field_name": "x", "kind": "confirmed"},
                                   {"field_name": "a", "kind": "answer"}])
    assert (c["questions_asked"], c["checks_asked"]) == (1, 1)


@pytest.mark.parametrize("qs,items", [(None, None), ([], []), ([None, 3], [None, "x", 4])])
def test_counts_never_raise_on_odd_input(qs, items):
    c = arq.response_counts(qs, items)
    assert c["questions_asked"] == c["checks_asked"] == 0 and c["response_summary"] == ""


def test_the_status_panel_count_never_raises():
    for row in (None, {}, {"id": "x", "questions": "not json"}, {"id": "x", "answers": 3}):
        assert isinstance(arq.response_counts_for_arq(row), dict)


# ══ 4. Item 17 - green only while the client's value is in the box ═══════════

def _form(conf, state, listed=(), schema=None):
    return {"confidence": conf, "field_state": state, "client_filled_fields": list(listed),
            "schema": schema if schema is not None else {k: {} for k in {**conf, **state}}}


def test_a_box_the_producer_retyped_is_not_the_clients():
    form = _form({"A": "producer", "B": "client_arq"}, {"A": "mine", "B": "theirs"}, listed=["A", "B"])
    assert arq.current_client_boxes(form) == ["B"]


def test_a_cleared_client_box_is_not_green():
    form = _form({"B": "client_arq"}, {"B": ""}, listed=["B"])
    assert arq.current_client_boxes(form) == []


def test_a_client_absence_counts_only_on_the_forms_own_list():
    form = _form({"N1": "explicit_no", "N2": "not_applicable", "N3": "explicit_no"},
                 {"N1": "", "N2": "", "N3": ""}, listed=["N1", "N2"])
    assert arq.current_client_boxes(form) == ["N1", "N2"]


def test_an_answer_key_that_is_no_box_on_the_form_is_not_listed():
    form = _form({"B": "client_arq"}, {"B": "x"}, listed=["B", "total_revenue", "schedule::auto_vin_schedule"],
                 schema={"B": {}})
    assert arq.current_client_boxes(form) == ["B"]


def test_the_union_leaves_out_a_box_another_form_filled():
    gf = {"ACORD_125": _form({"NamedInsured_FullName_A": "client_arq"}, {"NamedInsured_FullName_A": "Acme"}),
          "ACORD_126": _form({"NamedInsured_FullName_A": "filled"}, {"NamedInsured_FullName_A": "Acme Inc"}),
          "ACORD_127": _form({"Vehicle_X_A": "client_arq"}, {"Vehicle_X_A": "1"})}
    assert arq.client_filled_union(gf) == ["Vehicle_X_A"]
    assert arq.client_filled_by_form(gf)["ACORD_125"] == ["NamedInsured_FullName_A"]


@pytest.mark.parametrize("bad", [None, "x", {"confidence": "x"}, {"confidence": None}])
def test_client_boxes_never_raise(bad):
    assert arq.current_client_boxes(bad) == []


# ══ 5. Unticking "Check if none" is not a claims answer ═══════════════════════

@pytest.mark.parametrize("value", ["No", "N", "no", "false", "0", "Off", " no "])
def test_a_bare_no_is_not_a_claims_answer(value):
    assert lhs.had_claims_answer({"loss_history_no_prior_losses_indicator": value}) is False


@pytest.mark.parametrize("value", ["Yes - we have had claims or losses", "we had claims in 2023",
                                   "had losses last year"])
def test_words_naming_claims_still_read_as_claims(value):
    assert lhs.had_claims_answer({"loss_history_no_prior_losses_indicator": value}) is True


def test_an_attestation_is_not_a_claims_answer():
    for v in ("Yes", "No known losses", None, ""):
        assert lhs.had_claims_answer({"loss_history_no_prior_losses_indicator": v}) is False


# ══ 6. Item 19 - one number per card ═════════════════════════════════════════

_FACTS = {"applicant_name": "Acme Builders LLC", "mailing_address": "1 Main St, Denver, CO 80202",
          "effective_date": "07/15/2026", "producer_name": "Agency LLC",
          "lines_of_business": ["General Liability"],
          "operations_description": "Commercial roofing contractor",
          "years_in_business": "12", "contractor_type": "Roofing"}
_FLAGS = {"has_gl_coverage": True, "is_contractor": True}
_FORMS = ["ACORD_125", "ACORD_126", "ACORD_186"]


def _per_form(facts=_FACTS):
    return [S.calculate_sqs(facts=facts, flags=_FLAGS, mapped_data={}, form_schema={},
                            selected_form_ids=_FORMS, hard_stops=[], soft_stops=[],
                            tier2_score=50, form_id=fid) for fid in _FORMS]


def _package(results, facts=_FACTS, **kw):
    return S.calculate_package_sqs(facts=facts, flags=_FLAGS, form_results=results,
                                   cross_issues=[], hard_stops=kw.get("hard_stops", []),
                                   soft_stops=kw.get("soft_stops", []),
                                   session_data={"selected_form_ids": _FORMS})


def _copies(results):
    out = {}
    for r in results:
        for rec in r["recommendations"]:
            out.setdefault(rec["rec_id"], []).append(rec)
    return out


def _loss_card(results):
    """Every copy of the "no loss history provided" card (its id is the slug of
    its message, so it is found by the message's start)."""
    return next(recs for rid, recs in _copies(results).items()
                if rid.startswith("rec_loss_no_loss_history_provided"))


@pytest.fixture(scope="module")
def unified():
    before = _per_form()
    results = copy.deepcopy(before)
    pkg = _package(results)
    return before, results, pkg


def test_the_loss_card_disagreed_across_forms_before(unified):
    before, _results, _pkg = unified
    values = {rec["score_impact"] for rec in _loss_card(before)}
    assert len(values) > 1, values                           # the reported defect, live shape


def test_every_card_says_one_number_on_every_form(unified):
    _before, results, _pkg = unified
    for rid, recs in _copies(results).items():
        assert len({(r["score_impact"], r["impact_is_exact"]) for r in recs}) == 1, rid
        assert all(r["impact_scope"] == "package" for r in recs), rid


def test_the_number_is_what_answering_does_to_the_package(unified):
    _before, results, pkg = unified
    loss = _loss_card(results)[0]
    answered = _package(_per_form(), facts={**_FACTS, loss["field"]: "Yes"})
    assert loss["score_impact"] == answered["raw_sqs_score"] - pkg["raw_sqs_score"]
    assert loss["impact_is_exact"] is True                    # no ceiling on this package


def test_a_card_no_score_reads_is_worth_nothing(unified):
    _before, results, _pkg = unified
    for rid in ("rec_contractor_residential_pct", "rec_contractor_high_hazard_ops",
                "rec_contractor_license_number"):
        rec = _copies(results)[rid][0]
        assert (rec["score_impact"], rec["impact_is_exact"]) == (0, True), rid
        assert rec["declared_impact"] == 6                    # the typed literal is kept


def test_a_narrative_card_keeps_its_hedge(unified):
    _before, results, pkg = unified
    rec = _copies(results)["rec_narrative_components"][0]
    assert rec["score_impact"] > 0 and rec["impact_is_exact"] is False
    narrative_gap = next(r["points_available"] for r in pkg["top_recommendations"]
                         if r.get("pillar") == "narrative_quality")
    assert rec["score_impact"] <= round(narrative_gap)        # never more than the pillar has


def test_each_form_is_still_in_priority_order(unified):
    _before, results, _pkg = unified
    for r in results:
        keys = [(x.get("priority", 99), -(x.get("score_impact") or 0)) for x in r["recommendations"]]
        assert keys == sorted(keys), r["form_id"]


def test_a_second_scoring_gives_the_same_numbers(unified):
    _before, results, _pkg = unified
    first = {rid: (recs[0]["score_impact"], recs[0]["impact_is_exact"]) for rid, recs in _copies(results).items()}
    _package(results)
    again = {rid: (recs[0]["score_impact"], recs[0]["impact_is_exact"]) for rid, recs in _copies(results).items()}
    assert again == first


def test_the_best_solutions_row_says_what_its_answer_adds(unified):
    _before, results, pkg = unified
    loss_row = next(r for r in pkg["top_recommendations"] if r.get("pillar") == "loss_history_alignment")
    loss_card = _loss_card(results)[0]
    assert loss_row["answer_gain"] == loss_card["score_impact"]
    assert loss_row["answer_gain_is_exact"] is True
    narrative = next(r for r in pkg["top_recommendations"] if r.get("pillar") == "narrative_quality")
    assert "answer_gain" not in narrative                     # prose cannot be probed
    # points_remaining still adds the pillar gaps, untouched
    assert pkg["points_remaining"] == round(sum(r.get("points_available") or 0
                                                for r in pkg["top_recommendations"]
                                                if r.get("pillar") != "hard_stops_present"), 1)


def test_a_probe_run_never_rewrites_the_cards():
    results = _per_form()
    snapshot = copy.deepcopy(results)
    S.calculate_package_sqs(facts=_FACTS, flags=_FLAGS, form_results=results, cross_issues=[],
                            hard_stops=[], soft_stops=[], session_data={}, _probe=True)
    assert results == snapshot


def test_an_unscored_card_stays_zero():
    results = _per_form()
    results[0]["recommendations"].append({"rec_id": "rec_status_note", "field": "contact_name",
                                          "component": "loss_history_alignment",
                                          "score_impact": 8, "unscored": True, "priority": 3})
    _package(results)
    rec = _copies(results)["rec_status_note"][0]
    assert (rec["score_impact"], rec["impact_is_exact"]) == (0, True)


def test_a_failed_unification_leaves_each_forms_number(monkeypatch):
    results = _per_form()
    before = {rid: [r["score_impact"] for r in recs] for rid, recs in _copies(results).items()}

    def boom(*_a, **_k):
        raise RuntimeError("probe broke")
    monkeypatch.setattr(S, "_unify_card_points", boom)
    pkg = _package(results)
    assert pkg["package_sqs_score"] is not None
    assert {rid: [r["score_impact"] for r in recs] for rid, recs in _copies(results).items()} == before


@pytest.mark.parametrize("field,answer,valid", [
    ("percent_subcontracted", "50", True),          # a percentage, not "Yes"
    ("fein", "123456789", True),
    ("effective_date", "01/01/2030", True),
    ("contact_name", "Yes", True),
    ("additional_remarks_text", "Yes", False),       # prose: no probe stands in for it
    ("auto_vin_schedule", "Yes", False),             # a table
])
def test_the_probe_is_an_answer_the_field_accepts(field, answer, valid):
    assert S._package_probe_answer(field) == (answer, valid)


@pytest.mark.parametrize("args,expected", [
    ((7.0, True, 8, 11.2, 66, 85), (7, True)),        # under the ceiling: exact
    ((7.0, True, 8, 11.2, 80, 85), (7, False)),       # the ceiling holds part of it back
    ((7.0, True, 8, 11.2, 66, None), (7, True)),
    ((0.0, True, 8, 11.2, 66, None), (0, True)),       # a valid probe that moved nothing
    ((-3.0, True, 8, 11.2, 66, None), (0, True)),
    ((0.0, False, 6, 7.0, 66, None), (6, False)),      # wrong shape: bounded fallback
    ((0.0, False, 20, 10.8, 66, None), (11, False)),
    ((None, False, 6, 0.0, 66, None), (0, True)),      # the pillar is full
    ((None, False, 0, 7.0, 66, None), (0, True)),
    ((None, False, None, 7.0, 66, None), None),        # nothing to say: leave it
    ((None, False, 6, None, 66, None), (6, False)),    # a component the package has no pillar for
])
def test_card_points(args, expected):
    assert S._card_points(*args) == expected


# ══ 7. The stored cards take the number the panel shows ══════════════════════

def test_open_cards_take_the_live_number_and_acted_cards_keep_theirs():
    rows = [
        {"rec_id": "rec_open", "action": None, "score_impact": 10},
        {"rec_id": "rec_ack", "action": "downloaded_anyway", "score_impact": 10},
        {"rec_id": "rec_same", "action": None, "score_impact": 7},
        {"rec_id": "rec_dismissed", "action": "dismissed", "score_impact": 10},
        {"rec_id": "rec_answered", "action": "resolved", "producer_answer": "x", "score_impact": 10},
        {"rec_id": "rec_back", "action": "resolved", "producer_answer": None, "score_impact": 10},
        {"rec_id": "rec_gone", "action": None, "score_impact": 10},
        {"rec_id": "fieldqa_attn_ACORD_125_missing", "action": None, "score_impact": 0},
    ]
    live = {"rec_open", "rec_ack", "rec_same", "rec_dismissed", "rec_answered", "rec_back",
            "fieldqa_attn_ACORD_125_missing"}
    points = {rid: 7 for rid in live}
    plan = au.plan_card_sync(rows, live, points)
    assert plan["repoint"] == ["rec_ack", "rec_back", "rec_open"]
    assert plan["reopen"] == ["rec_back"] and plan["resolve"] == ["rec_gone"]
    assert au.plan_card_sync(rows, live)["repoint"] == []     # no numbers, no change


def test_the_first_copy_speaks_for_the_card():
    forms = [{"recommendations": [{"rec_id": "a", "score_impact": 7}, {"rec_id": "b", "score_impact": True},
                                  "plain string", {"rec_id": "c"}]},
             {"recommendations": [{"rec_id": "a", "score_impact": 9}, {"rec_id": "d", "score_impact": 2.6}]},
             None, "x"]
    assert au.live_card_points(forms) == {"a": 7, "d": 3}


def test_the_sync_applies_the_live_number(monkeypatch):
    stored = [{"rec_id": "rec_loss", "action": None, "producer_answer": None, "score_impact": 10},
              {"rec_id": "rec_dis", "action": "dismissed", "producer_answer": None, "score_impact": 10}]
    applied = {}

    async def rows(_sid):
        return [dict(r) for r in stored]

    async def nothing(*_a, **_k):
        return None

    async def repoint(_sid, pts):
        applied.update(pts)
    monkeypatch.setattr(au, "_stored_card_rows", rows)
    monkeypatch.setattr(au, "log_recommendations_presented", nothing)
    monkeypatch.setattr(au, "_reopen_system_closed_cards", nothing)
    monkeypatch.setattr(au, "_repoint_open_cards", repoint)
    forms = [{"form_id": "ACORD_125", "recommendations": [{"rec_id": "rec_loss", "score_impact": 7},
                                                          {"rec_id": "rec_dis", "score_impact": 7}]}]
    out = asyncio.run(au.sync_recommendation_cards("s", "u", forms, "v"))
    assert applied == {"rec_loss": 7} and out["repointed"] == 1


def test_the_repoint_statement_repeats_the_plans_test():
    import inspect
    src = inspect.getsource(au._repoint_open_cards)
    assert "action IS NULL OR action='downloaded_anyway'" in src


def test_every_route_syncs_after_the_package_is_scored():
    """The stored number must be the package's: a sync before the package
    scorer records each form's own number again."""
    src = (BACKEND / "routes" / "form_routes.py").read_text()
    for start in ("async def select_forms_bulk", "async def update_pdf"):
        body = src[src.index(start):]
        body = body[:body.index("\n@router", 10)] if "\n@router" in body[10:] else body
        assert body.index("calculate_package_sqs(") < body.index("await sync_recommendation_cards("), start
    gen = src[src.index("async def select_forms_bulk"):]
    assert gen.index("calculate_package_sqs(") < gen.index('"generated_forms": results')


# ══ 8. The policy-wording check reads its own pattern ════════════════════════

def test_the_two_policy_patterns_are_two_names():
    assert ps._POLICY_NAMES_ITSELF_RE.search("this insurance does not apply")
    assert not ps._POLICY_NAMES_ITSELF_RE.search("as defined in paragraph B.1")
    assert ps._POLICY_SELF_REFERENCE_RE.search("the terms of this endorsement")
    assert ps._POLICY_SELF_REFERENCE_RE.search("as defined in section II")


def test_policy_wording_counts_the_policy_naming_itself():
    assert ps._policy_wording_marks("This insurance does not apply to this exclusion.") >= 3
    assert ps._policy_wording_marks("The applicant repairs roofs in Denver.") == 0


# ══ 9. Item 6 end to end: "Open to fix" on the driver warning, 125 alone ═════

def test_item6_the_driver_card_opens_a_table_that_saves_and_clears(monkeypatch):
    """Michelle's screen: a package with an auto line whose policy schedules no
    drivers, ACORD 125 chosen alone. The warning's card opens the Drivers table,
    the server serves it, one saved driver is stored, and the warning is gone."""
    import repositories.session_repository as repo
    from services.issue_registry import build_structured_from_sources

    facts = {"applicant_name": "Acme Builders LLC",
             "auto_vin_schedule": [{"year": "2012", "make": "Subaru", "model": "Outback",
                                    "vin": "4S4BRCGC9C3217772"}]}
    flags = {"has_auto_coverage": True}
    _hard, soft = S.evaluate_stops(facts, flags)
    warning = [m for m in soft if m.startswith("Driver schedule not provided")]
    assert warning, soft                                     # the live shape
    issues = build_structured_from_sources(legacy_soft=warning)
    assert any((i.get("resolution") or {}).get("schedule_key") == "auto_drivers" for i in issues)

    proc = {"user_id": "u", "facts": facts, "flags": flags, "selected_form_ids": ["ACORD_125"],
            "generated_forms": {"ACORD_125": {"schema": S125, "field_state": {}, "mapped": {},
                                              "confidence": {}}},
            "structured_issues": issues}
    saved = {}

    async def _get(_sid):
        return copy.deepcopy(proc)

    async def _upd(_sid, updates, **_kw):
        saved.update(updates)
    monkeypatch.setattr(repo, "get_processing_session", _get)
    monkeypatch.setattr(repo, "upd_processing_session", _upd)

    served = asyncio.run(arq.get_session_schedules("s", only_key="auto_drivers"))
    assert [s["schedule_key"] for s in served] == ["auto_drivers"]
    assert served[0]["rows"] == [] and served[0]["form_ids"] == []   # 0 drivers, no 127

    ok, result = asyncio.run(arq.save_session_schedule("s", "auto_drivers", [
        {"name": "Erin Royal", "dob": "05/14/1985", "license_number": "D1234567",
         "license_state": "CO"}]))
    assert ok and result["row_count"] == 1 and not result["errors"]
    stored = saved["facts"]["auto_drivers"]
    stored = stored.get("value") if isinstance(stored, dict) else stored
    assert len(stored) == 1 and stored[0]["name"] == "Erin Royal"

    _hard, soft_after = S.evaluate_stops(saved["facts"], flags)
    assert not [m for m in soft_after if m.startswith("Driver schedule not provided")]


def test_item6_a_table_no_card_offers_is_not_served_on_125_alone(monkeypatch):
    """The widening is only what a card offers: no driver card, no table."""
    import repositories.session_repository as repo
    proc = {"user_id": "u", "facts": {}, "flags": {}, "selected_form_ids": ["ACORD_125"],
            "generated_forms": {"ACORD_125": {"schema": S125}}, "structured_issues": []}

    async def _get(_sid):
        return copy.deepcopy(proc)
    monkeypatch.setattr(repo, "get_processing_session", _get)
    assert asyncio.run(arq.get_session_schedules("s", only_key="auto_drivers")) == []


# ══ 10. An amount with cents is an amount, not a web address ═════════════════

@pytest.mark.parametrize("value,printed", [
    ("2500000.00", "$2,500,000"), ("1000000.50", "$1,000,000.50"), ("3418.50", "$3,418.50"),
    ("10663.5", "$10,663.50"), ("3418", "$3,418"),
    ("3.14.15", "3.14.15"), ("12.31.2026", "12.31.2026"),       # not ONE amount: as written
    ("1,000,000 / 2,000,000", "1,000,000 / 2,000,000"), ("Included", "Included"),
])
def test_a_money_box_formats_cents_and_leaves_what_is_not_one_amount(value, printed):
    from services.display_canonicalizer import canonicalize_for_field
    assert canonicalize_for_field("CommercialVehicleLineOfBusiness_PremiumAmount_A", value) == printed


@pytest.mark.parametrize("token", ["orbin.com", "www.orbin.com", "erin@orbin.com", "a.b.co.uk",
                                   "ThinkSmith.io", "https://orbin.com/x"])
def test_a_web_address_is_still_never_recased(token):
    from services.display_canonicalizer import _is_machine_token, canonicalize_for_field
    assert _is_machine_token(token)
    assert canonicalize_for_field("NamedInsured_FullName_A", token) == token


@pytest.mark.parametrize("token", ["2500000.00", "3418.50", "1.5M", "3.14.15"])
def test_a_dotted_number_is_not_a_web_address(token):
    from services.display_canonicalizer import _is_machine_token
    assert not _is_machine_token(token)


# ══ 11. A calculated date says it was calculated (item 4) ═════════════════════

def _calc_facts(source="derived", confidence="low_confidence"):
    return {"effective_date": {"value": "07/15/2026", "source": source, "confidence": confidence},
            "expiration_date": {"value": "07/15/2027", "source": source, "confidence": confidence}}


def test_a_calculated_date_is_labelled_and_explained_as_calculated():
    mapped = {"Policy_EffectiveDate_A": "07/15/2026", "Policy_ExpirationDate_A": "07/15/2027"}
    conf = {k: "filled" for k in mapped}
    facts = _calc_facts()
    ps.apply_derived_value_labels("ACORD_125", facts, mapped, conf)
    assert set(conf.values()) == {"low_confidence"}
    fr = {"schema": S125, "mapped": mapped, "field_state": dict(mapped), "confidence": conf}
    rows = {r["field"]: r for r in na.needs_attention(fr, facts, "ACORD_125",
                                                       doc_haystack=" 07 15 2026 ")}
    for f in mapped:
        assert rows[f]["status"] == na.STATUS_VERIFY
        assert rows[f]["reason"] == na._VERIFY_CALCULATED       # never "Filled by the AI"


@pytest.mark.parametrize("facts,value", [
    (_calc_facts(source="ai", confidence="ai_low"), "07/15/2026"),   # the document's own date
    (_calc_facts(confidence="filled"), "07/15/2026"),               # a derivation that is not an estimate
    (_calc_facts(), "08/01/2026"),                                  # the box prints something else
    (_calc_facts(), ""), (_calc_facts(), None), (None, "07/15/2026"), ({}, "07/15/2026"),
])
def test_only_a_printed_estimate_is_calculated(facts, value):
    assert ps.prints_a_calculated_value("ACORD_125", "Policy_EffectiveDate_A", value, facts) is False
