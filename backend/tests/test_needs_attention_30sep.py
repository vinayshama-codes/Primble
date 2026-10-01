"""Orbin client feedback of 22 Sep, items 9 and 19 (30 Sep 2026).

  item 9   "We know what's missing / required / verify. Why can't we put them in
           the side panel, or better yet, earlier in the workflow?"
  item 19  "each item [should] tell me what needs attention, what to do next,
           and how it could affect the score ... whether information is
           missing, the AI withheld a value, or an inferred value needs
           verification ... the Field QA summary says 4 required fields are
           empty and 7 AI-inferred fields need verification, but I can't tell
           which forms or questions it's referring to."

ONE door - `services/needs_attention.py` - gives every box on a generated form
exactly one status (Missing / AI held back / Please verify). The side panel,
the pre-download review and its stored E&O rows all read it.

Fixture `tests/fixtures/needs_attention_live_30sep.json` holds two STORED
ACORD 125 generations read from the database: b8d6 (the latest Orbin live run,
29 Sep) and 8992 (the 28 Sep baseline in 25sepChanges.md section 1.4, whose
review listed "AdditionalInterest FullName" both as "a value was found but
removed" and as "no value found").
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.field_qa as fq                                       # noqa: E402
import services.needs_attention as na                                # noqa: E402

FIXTURE = json.loads((BACKEND / "tests" / "fixtures" / "needs_attention_live_30sep.json").read_text())
SCHEMA_DIR = BACKEND / "forms_schemas"
SCHEMA_125 = json.loads((SCHEMA_DIR / "ACORD_125_schema.json").read_text())
FRONTEND = BACKEND.parent / "frontend" / "src"
FORM_DIR = FRONTEND / "components" / "form"


def _live(tag):
    d = FIXTURE[tag]
    return d["generated_forms"], d["facts"], d["flags"]


def _rows(tag):
    gf, facts, flags = _live(tag)
    return na.needs_attention(gf["ACORD_125"], facts, "ACORD_125", flags=flags)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# The live runs
# ══════════════════════════════════════════════════════════════════════════════

def test_latest_live_run_counts_are_the_rows():
    gf, facts, flags = _live("b8d6")
    res = na.needs_attention_for_session(gf, facts, flags=flags)
    # 30 Sep (owner's final run): +1 Missing - the unanswered HIGH-IMPACT
    # question "Any area leased to others?" now lists here, with the form's
    # wording, instead of only at download under an internal name.
    # 30 Sep night (items 8 / 11): +5 Missing - this run's four TICKED lines
    # had blank premiums, and so did the total; each is now listed (the prompt
    # Michelle asked for), as a producer to-do.
    assert res["counts"] == {"missing": 16, "ai_held_back": 13, "verify": 0, "total": 29}
    form = res["forms"][0]
    assert form["form_id"] == "ACORD_125" and form["form_label"] == "ACORD 125" and form["ok"] is True
    assert form["counts"] == na.count_rows(form["rows"]) == res["counts"]


@pytest.mark.parametrize("tag", ["b8d6", "8992"])
def test_one_box_one_row_one_status(tag):
    rows = _rows(tag)
    fields = [r["field"] for r in rows]
    assert len(fields) == len(set(fields))
    for r in rows:
        assert r["status"] in na.STATUS_ORDER
        assert r["tag"] == na.STATUS_TAG[r["status"]]
        assert r["what_to_do"] and r["reason"]
        assert isinstance(r["page"], int) and 1 <= r["page"] <= 5


@pytest.mark.parametrize("tag", ["b8d6", "8992"])
def test_labels_are_what_the_form_prints_never_internal_names(tag):
    for r in _rows(tag):
        assert "_" not in r["label"], r
        assert r["field"] not in r["label"]
        assert not re.search(r"[a-z][A-Z]", r["label"].replace("NAICS", "").replace("SIC", "")), r["label"]
        assert "—" not in r["label"] + r["reason"] + r["what_to_do"]


def test_baseline_box_listed_twice_is_now_listed_once():
    # 25sepChanges.md 1.4: "AdditionalInterest FullName" printed under BOTH
    # "a value was found but removed" and "no value found". Prove the legacy
    # QA really did that on the stored run, then that the door lists it once.
    gf, facts, flags = _live("8992")
    qa = fq.run_field_qa(gf, merged_facts=facts, confirmations={}, flags=flags)
    codes = {r["reason_code"] for r in qa["results"] if r["field"] == "AdditionalInterest_FullName_A"}
    # 30 Sep: fixed at the source too - a box a guard emptied was ANSWERED, so
    # the QA no longer also calls it "left blank by the AI" (not_answered).
    assert codes == {"guard_removed_value"}
    mine = [r for r in _rows("8992") if r["field"] == "AdditionalInterest_FullName_A"]
    assert len(mine) == 1 and mine[0]["status"] == na.STATUS_HELD_BACK
    assert mine[0]["label"] == "Additional interest's full name"
    # 30 Sep (owner's live run): "Found" is said only of a value the documents
    # or our records are known to hold. This stored run predates the guard
    # report's document check, so the refused value is the AI's suggestion.
    assert 'The AI suggested "additional insured"' in mine[0]["reason"]


def test_viewer_required_badge_equals_missing_plus_required_held_back():
    # The viewer's "N Required" (PDFJsViewer.updateHighlightCounts) mirrored
    # on the effective labels: the side panel never counts differently.
    for tag, expected in (("8992", 14), ("b8d6", 10)):
        gf, facts, _ = _live(tag)
        fr = gf["ACORD_125"]
        labels = na.effective_labels("ACORD_125", fr, facts)
        vals = fr["field_state"]
        filled = set(fr.get("client_filled_fields") or [])
        positions = na.widget_positions("ACORD_125", fr)
        yellow = 0
        for name in positions:
            v = str(vals.get(name) or "").strip()
            conf = labels.get(name)
            if name in filled or conf == "client_arq":
                continue
            empty = not v or v in ("null", "None")
            if name in na.VIEWER_ALWAYS_REQUIRED and empty:
                yellow += 1
            elif conf in ("missing_required", "extraction_error") and empty:
                yellow += 1
        rows = _rows(tag)
        # REQUIRED rows only: since 30 Sep the list also names unanswered
        # high-impact questions as Missing, and those are not the viewer's
        # yellow "Required" boxes (they are not required by the form).
        door = sum(1 for r in rows if r["status"] == na.STATUS_MISSING and r["required"]) + \
            sum(1 for r in rows if r["status"] == na.STATUS_HELD_BACK and r["required"])
        assert yellow == door == expected


def test_held_back_reasons_name_what_the_value_really_was():
    by_field = {r["field"]: r for r in _rows("b8d6")}
    assert "GL class codes" in by_field["NamedInsured_SICCode_A"]["reason"]
    assert '"AGENT PHONE"' in by_field["NamedInsured_Primary_PhoneNumber_A"]["reason"]
    assert '"Servicing Company"' in by_field["BusinessInformation_ParentOrganizationName_A"]["reason"]
    assert "policy wording" in by_field["CancelNonRenew_UnderwritingConditionCorrectedDescription_A"]["reason"]
    q = by_field["CommercialPolicy_Question_ABCCode_A"]
    assert q["label"] == "Any exposure to flammables, explosives, chemicals?"
    # Michelle's item 9 (1 Oct): a refused Yes/No answer is never repeated - the
    # documents do not answer the question, and that is the whole finding.
    for f in ("CommercialPolicy_Question_ABCCode_A", "CommercialPolicy_Question_AAICode_A"):
        reason = by_field[f]["reason"]
        assert reason == na._QUESTION_UNANSWERED, (f, reason)
        assert '"Yes"' not in reason and '"No"' not in reason


def test_a_question_is_a_question_explanations_and_options_are_not_listed():
    rows = _rows("b8d6")
    gf, _, _ = _live("b8d6")
    unanswered = {g["field"] for g in gf["ACORD_125"]["guard_blanks"] if g.get("kind") == "unanswered"}
    listed = {r["field"] for r in rows}
    for f in unanswered & listed:
        assert na.is_question_box(SCHEMA_125, f), f
    # The live run's explanation / date / option boxes behind refused answers.
    for f in ("CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A",
              "CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_A",
              "CancelNonRenew_NonPaymentIndicator_A"):
        assert f in unanswered and f not in listed


def test_copies_and_unused_rows_are_not_findings():
    listed = {r["field"] for r in _rows("b8d6")}
    # The applicant's own name refused as an Additional Interest / subsidiary:
    # the form already prints it, nothing was lost.
    for f in ("AdditionalInterest_FullName_A", "AdditionalInterest_FullName_B", "Subsidiary_OrganizationName_A"):
        assert f not in listed
    # Rows 2 and 3 of the named-insured section print nothing: no second insured.
    assert not any(f.startswith("NamedInsured_") and f.endswith(("_B", "_C")) for f in listed)


def test_score_effect_is_the_scorers_measured_number_or_none():
    rows = {r["field"]: r for r in _rows("8992")}
    eff = rows["Policy_EffectiveDate_A"]
    gf, _, _ = _live("8992")
    rec = next(r for r in gf["ACORD_125"]["sqs"]["recommendations"] if r["field"] == "effective_date")
    assert eff["fact_key"] == "effective_date" and eff["answer_mode"] == "field"
    assert eff["score_effect"] == int(float(rec["score_impact"])) == 5
    assert eff["score_text"] == "Up to +5 pts"
    sig = rows["NamedInsured_Signature_A"]
    assert sig["score_effect"] == 0 and sig["score_text"] == "No score effect"


# ══════════════════════════════════════════════════════════════════════════════
# Precedence - synthetic, one rule each
# ══════════════════════════════════════════════════════════════════════════════

def _form(field_state=None, confidence=None, guard=None, **extra):
    return {"field_state": field_state or {}, "confidence": confidence or {},
            "guard_blanks": guard or [], "form": {"template_file": "ACORD_125.pdf"}, **extra}


def _one(fr, facts=None, form_id="ACORD_125"):
    rows = na.needs_attention(fr, facts or {}, form_id)
    # The always-required signature boxes are present on every 125 run.
    return [r for r in rows if r["field"] not in na.VIEWER_ALWAYS_REQUIRED]


def test_a_box_with_a_value_is_verify_only_when_ai_inferred():
    f = "BusinessInformation_ParentOrganizationName_A"
    rows = _one(_form({f: "Acme Holdings"}, {f: "low_confidence"},
                      [{"field": f, "removed_value": "EMC Insurance Companies"}]))
    assert [(r["field"], r["status"]) for r in rows] == [(f, na.STATUS_VERIFY)]
    assert rows[0]["value"] == "Acme Holdings" and rows[0]["score_effect"] == 0
    assert _one(_form({f: "Acme Holdings"}, {f: "filled"})) == []
    assert _one(_form({f: "Acme Holdings"}, {f: "ai_verified"})) == []


def test_held_back_outranks_missing_and_keeps_required():
    f = "NamedInsured_BusinessStartDate_A"          # required on every 125
    rows = _one(_form({}, {f: "missing_required"}, [{"field": f, "removed_value": "07/15/25"}]))
    r = next(x for x in rows if x["field"] == f)
    assert r["status"] == na.STATUS_HELD_BACK and r["required"] is True
    rows = _one(_form({}, {f: "missing_required"}))
    assert next(x for x in rows if x["field"] == f)["status"] == na.STATUS_MISSING


def test_a_refused_copy_of_a_printed_value_is_missing_if_required_else_nothing():
    f, other = "NamedInsured_BusinessStartDate_A", "Policy_EffectiveDate_A"
    fr = _form({other: "07/15/2026"}, {f: "missing_required", other: "filled"},
               [{"field": f, "removed_value": "07/15/2026"}])
    assert next(x for x in _one(fr) if x["field"] == f)["status"] == na.STATUS_MISSING
    g = "BusinessInformation_ParentOrganizationName_A"
    fr = _form({"NamedInsured_FullName_A": "ORBIN CONTRACTING LLC"}, {g: "low_confidence"},
               [{"field": g, "removed_value": "Orbin Contracting LLC"}])
    assert all(x["field"] != g for x in _one(fr))


def test_checkbox_pair_question_is_one_row():
    yes = "CommercialPolicy_Question_ABCCode_A"
    rows = _one(_form({}, {yes: "low_confidence"}, [{"field": yes, "removed_value": "N", "kind": "unanswered"}]))
    assert [r["field"] for r in rows] == [yes]
    # A real checkbox PAIR on ACORD 133 (Yes / No indicators of one question).
    s133 = json.loads((SCHEMA_DIR / "ACORD_133_schema.json").read_text())
    pair = sorted(f for f in s133 if f.endswith(("YesIndicator_A", "NoIndicator_A"))
                  and na.is_question_box(s133, f))[:2]
    assert len(pair) == 2 and na.box_label(s133, pair[0]) == na.box_label(s133, pair[1]) \
        == "Do trucking classifications apply?"
    rows = na.needs_attention(
        {"field_state": {}, "confidence": {}, "schema": s133, "form": {"template_file": "ACORD_133.pdf"},
         "guard_blanks": [{"field": p, "removed_value": "Yes", "kind": "unanswered"} for p in pair]},
        {}, "ACORD_133")
    assert len([r for r in rows if r["field"] in pair]) == 1


def test_a_client_answer_is_never_listed():
    f = "NamedInsured_BusinessStartDate_A"
    assert all(r["field"] != f for r in _one(_form({f: "01/01/2010"}, {f: "client_arq"})))
    # Listed in the viewer's client list: green there, never a row here.
    fr = _form({}, {f: "missing_required"}, client_filled_fields=[f])
    assert all(r["field"] != f for r in _one(fr))


def test_signature_boxes_follow_the_viewer():
    rows = na.needs_attention(_form({}, {}), {}, "ACORD_125")
    sig = {r["field"]: r for r in rows if r["field"] in na.VIEWER_ALWAYS_REQUIRED}
    assert set(sig) == set(na.VIEWER_ALWAYS_REQUIRED)
    assert sig["NamedInsured_Signature_A"]["what_to_do"].startswith("The applicant signs")
    rows = na.needs_attention(_form({"NamedInsured_Signature_A": "signed", "NamedInsured_SignatureDate_A": "09/30/2026"}, {}),
                              {}, "ACORD_125")
    assert not [r for r in rows if r["field"] in na.VIEWER_ALWAYS_REQUIRED]
    # A form without those boxes never grows them.
    assert na.needs_attention(_form({}, {}, form={"template_file": "ACORD_25.pdf"}), {}, "ACORD_25") == []


def test_empty_and_malformed_inputs():
    assert na.needs_attention(None, None, "ACORD_25") == []
    assert na.needs_attention({"guard_blanks": [None, "x", {"no": "field"}]}, {}, "ACORD_25") == []
    res = na.needs_attention_for_session({}, {})
    assert res == {"forms": [], "counts": {"missing": 0, "ai_held_back": 0, "verify": 0, "total": 0}}
    res = na.needs_attention_for_session({"ACORD_25": {}, "ACORD_125": _form()}, {}, form_ids=["ACORD_25"])
    assert [f["form_id"] for f in res["forms"]] == ["ACORD_25"]


def test_a_form_the_door_cannot_read_says_so(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad form")
    monkeypatch.setattr(na, "needs_attention", boom)
    res = na.needs_attention_for_session({"ACORD_125": _form()}, {})
    assert res["forms"][0]["ok"] is False and res["forms"][0]["rows"] == []


def test_every_label_on_every_schema_is_words():
    # Generic, not tuned to 125: all 17 schemas, every box.
    for path in sorted(SCHEMA_DIR.glob("*_schema.json")):
        schema = json.loads(path.read_text())
        for field in schema:
            label = na.box_label(schema, field)
            assert label and "_" not in label, (path.name, field, label)
            assert not label.lower().startswith(("enter ", "check the box", "indicates", "the ")), (field, label)
            assert len(label) <= 150


# ══════════════════════════════════════════════════════════════════════════════
# The pre-download record (field_qa) - additive, legacy contract unchanged
# ══════════════════════════════════════════════════════════════════════════════

def _qa_8992():
    gf, facts, flags = _live("8992")
    qa = fq.run_field_qa(gf, merged_facts=facts, confirmations={}, flags=flags)
    att = na.needs_attention_for_session(gf, facts, flags=flags)
    return qa, att


def test_legacy_rows_are_unchanged_without_the_door():
    qa, _ = _qa_8992()
    assert fq.to_recommendation_rows(qa) == fq.to_recommendation_rows(qa, attention=None)
    assert any(r["rec_id"] == "fieldqa_summary" for r in fq.to_recommendation_rows(qa))


def test_with_the_door_each_form_and_box_is_named_and_counted_once():
    qa, att = _qa_8992()
    rows = fq.to_recommendation_rows(qa, attention=att)
    attn = [r for r in rows if r["rec_id"].startswith(na.ATTENTION_REC_PREFIX)]
    # 30 Sep night (items 8 / 11): the blank premiums of ticked lines ride their
    # own row, so the underwriter's cover page can leave them out.
    # 1 Oct: the applicant's own steps (sign and date) are a row of their own -
    # the producer is never told to "fill in" the applicant's signature.
    assert [r["rec_id"] for r in attn] == [
        "fieldqa_attn_ACORD_125_missing", "fieldqa_attn_ACORD_125_missing_producer",
        "fieldqa_attn_ACORD_125_missing_applicant", "fieldqa_attn_ACORD_125_ai_held_back"]
    assert attn[0]["message"].startswith("ACORD 125 - Missing (12): ")   # 14 less the 2 applicant steps
    assert "Signature" not in attn[0]["message"]
    assert attn[1]["message"].startswith("ACORD 125 - Missing (5): Premium amount")
    assert attn[2]["message"].startswith("ACORD 125 - To be signed by the applicant (2): Signature")
    assert "Fix: Fill" not in attn[2]["message"]
    assert attn[3]["message"].startswith("ACORD 125 - AI held back (11): ")
    for r in attn:
        n = int(re.search(r"\((\d+)\)", r["message"]).group(1))
        listed = r["message"].split("): ", 1)[1].split(". Fix:")[0]
        more = re.search(r"\+(\d+) more", listed)
        assert len(listed.split("; ")) - (1 if more else 0) + (int(more.group(1)) if more else 0) == n
        assert "AdditionalInterest" not in r["message"] and "_" not in listed
    # The owned legacy rows are gone; nothing else changed.
    assert not any(r["rec_id"] == "fieldqa_summary" for r in rows)
    assert not any("left blank on purpose" in (r["message"] or "") for r in rows)
    legacy_other = [r for r in fq.to_recommendation_rows(qa) if not fq.row_superseded_by_attention(r)]
    assert [r["rec_id"] for r in legacy_other] == \
        [r["rec_id"] for r in rows if not r["rec_id"].startswith(na.ATTENTION_REC_PREFIX)]


def test_a_form_the_door_could_not_read_keeps_its_legacy_rows():
    qa, att = _qa_8992()
    att["forms"][0]["ok"] = False
    att["forms"][0]["rows"] = []
    rows = fq.to_recommendation_rows(qa, attention=att)
    assert any(r["rec_id"] == "fieldqa_summary" or "left blank" in r["message"] for r in rows)


def _legacy_item(code, field, high_impact, form="ACORD_125"):
    return {"form_id": form, "field": field, "field_label": fq._humanize_field(field),
            "verdict": "review", "reason_code": code, "high_impact": high_impact,
            "message": {
                "missing_required": f"{fq._humanize_field(field)} on ACORD 125 is required but empty. Fix: Provide a value before sending.",
                "low_confidence": f"{fq._humanize_field(field)} on ACORD 125 is a high-impact question that was AI-inferred (not copied verbatim from a document). Fix: Confirm.",
                "not_answered": f"{fq._humanize_field(field)} on ACORD 125 is a high-impact question the AI left blank (no value found in the documents). Fix: Answer it manually if it applies.",
                "guard_removed_value": f"{fq._humanize_field(field)} was left blank on purpose: x",
                "value_mismatch": f"{fq._humanize_field(field)} on ACORD 125 shows \"a\" but the source value is \"b\". Fix: Re-confirm.",
                "placeholder_value": f"{fq._humanize_field(field)} on ACORD 125 contains a placeholder value.",
                "missing_required_gate": f"{fq._humanize_field(field)} on ACORD 140 is required for this section (a related field was already filled) but empty. Fix: Provide a value before sending - this blocks a clean download.",
            }[code]}


def test_superseded_marker_matches_every_legacy_shape_and_nothing_else():
    items = []
    for code in ("missing_required", "low_confidence", "not_answered"):
        items += [_legacy_item(code, "Alpha_BetaQuestion_A", True),
                  _legacy_item(code, "Alpha_BetaQuestion_B", True),     # repeating rows of one
                  _legacy_item(code, "Gamma_DeltaQuestion_A", True),    # 2+ distinct questions
                  _legacy_item(code, "Plain_Box_A", False)]             # summary count
    items += [_legacy_item("guard_removed_value", "Some_Box_A", False),
              _legacy_item("value_mismatch", "Mis_Match_A", False),
              _legacy_item("placeholder_value", "Place_Holder_A", False),
              _legacy_item("missing_required_gate", "Gate_Box_A", False, form="ACORD_140")]
    qa = {"results": items}
    rows = fq.to_recommendation_rows(qa)
    single = [x for c in ("missing_required", "low_confidence", "not_answered")
              for x in fq.to_recommendation_rows({"results": [_legacy_item(c, "Solo_Question_A", True)]})]
    assert len(single) == 3
    for r in rows + single:
        # Unanswered HIGH-IMPACT questions stay in the review too (adversarial
        # review, 30 Sep: Figure 33 - a high-impact gap is never buried).
        kept = ("hardblock" in r["rec_id"]) or ("mismatch" in r["rec_id"]) \
            or ("not_answered" in r["rec_id"])
        assert fq.row_superseded_by_attention(r) is (not kept), r
    sched = {"rec_id": "fieldqa_x_schedule_row_missing", "message": "auto drivers row 1: license number is required but missing. Fix: Provide a value or remove the row."}
    assert fq.row_superseded_by_attention(sched) is False
    assert fq.row_superseded_by_attention({"rec_id": "rec_contact_name", "message": "is required but empty"}) is False
    assert fq.row_superseded_by_attention(None) is False


def test_the_stored_rows_are_written_through_the_door(monkeypatch):
    import services.audit_service as audit
    captured = {}

    async def fake_sync(session_id, user_id, rows, model_version):
        captured["rows"] = rows

    monkeypatch.setattr(audit, "sync_field_qa_findings", fake_sync)
    gf, facts, flags = _live("b8d6")
    asyncio.run(audit.run_and_log_field_qa("s", "u", gf, facts, {}, True, flags=flags))
    ids = [r["rec_id"] for r in captured["rows"]]
    assert "fieldqa_attn_ACORD_125_missing" in ids and "fieldqa_attn_ACORD_125_ai_held_back" in ids
    assert "fieldqa_summary" not in ids


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

def _session(user_id="u1"):
    gf, facts, flags = _live("b8d6")
    return {"user_id": user_id, "generated_forms": gf, "facts": facts, "flags": flags, "package_sqs": None}


def _call(coro):
    res = asyncio.run(coro)
    return json.loads(res.body)


def test_route_returns_the_door_for_the_owner(monkeypatch):
    import routes.audit_routes as ar

    async def fake_get(sid):
        return _session()

    monkeypatch.setattr(ar, "get_processing_session", fake_get)
    body = _call(ar.get_needs_attention("sid", None, {"id": "u1"}))
    # +1 unanswered question (30 Sep); +5 blank premiums of ticked lines (30 Sep night)
    assert body["success"] is True and body["counts"]["total"] == 29
    body = _call(ar.get_needs_attention("sid", "ACORD_125", {"id": "u1"}))
    assert [f["form_id"] for f in body["forms"]] == ["ACORD_125"]


def test_route_refuses_another_user_and_an_unknown_form(monkeypatch):
    from fastapi import HTTPException
    import routes.audit_routes as ar

    async def fake_get(sid):
        return _session("owner")

    monkeypatch.setattr(ar, "get_processing_session", fake_get)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ar.get_needs_attention("sid", None, {"id": "someone-else"}))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        asyncio.run(ar.get_needs_attention("sid", "ACORD_999", {"id": "owner"}))
    assert e.value.status_code == 404


def test_open_recs_marks_superseded_rows_without_dropping_any(monkeypatch):
    import routes.audit_routes as ar

    async def fake_owner(sid, user):
        return None

    async def fake_open(sid, include_acknowledged=False):
        return [{"rec_id": "fieldqa_summary", "message": "Field QA: 4 required fields still empty"},
                {"rec_id": "fieldqa_attn_ACORD_125_missing", "message": "ACORD 125 - Missing (1): x"},
                {"rec_id": "fieldqa_hardblock_ACORD_140_x", "message": "is required for this section"},
                {"rec_id": "rec_contact_name", "message": "ACORD 125 missing: contact info"}]

    monkeypatch.setattr(ar, "_verify_session_owner", fake_owner)
    monkeypatch.setattr(ar, "get_open_recommendations", fake_open)
    body = _call(ar.get_open_recs("sid", {"id": "u1"}))
    marks = [bool(r.get("attention_superseded")) for r in body["open_recommendations"]]
    assert marks == [True, True, False, False] and body["count"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# Frontend (read from source)
# ══════════════════════════════════════════════════════════════════════════════

def test_viewer_always_required_set_matches_the_jsx():
    src = _read(FORM_DIR / "PDFJsViewer.jsx")
    m = re.search(r"const YELLOW_REQUIRED = new Set\(\[([^\]]*)\]\)", src)
    assert m
    assert set(re.findall(r'"([^"]+)"', m.group(1))) == set(na.VIEWER_ALWAYS_REQUIRED)


def test_viewer_can_jump_to_a_box():
    src = _read(FORM_DIR / "PDFJsViewer.jsx")
    assert 'import usePdfFieldFocus from "./usePdfFieldFocus";' in src
    assert "focusField = null," in src
    assert "usePdfFieldFocus({ focusField, fieldsLoaded, fieldsRef, overlayRef, pageNum, setPageNum });" in src
    assert "wrap.dataset.fieldName = field.name;" in src
    hook = _read(FORM_DIR / "usePdfFieldFocus.js")
    assert "data-field-name" in hook and "setPageNum(wantPage)" in hook
    assert "_handled.has(nonce)" in hook          # one jump per click, even across remounts


def test_side_panel_section_refreshes_with_the_score_and_jumps():
    modal = _read(FORM_DIR / "AcordModal.jsx")
    i = modal.index("<NeedsAttentionPanel")
    block = modal[i:i + 700]
    for prop in ("sessionId={sessionId}", "formId={activeFormId}", "formSqs={activeSqs}",
                 "packageSqs={packageSqs}", "refreshTick={pdfRefreshTick}", "setAttentionFocus("):
        assert prop in block, prop
    assert "focusField={attentionFocus && attentionFocus.formId === activeFormId ? attentionFocus : null}" in modal
    panel = _read(FORM_DIR / "NeedsAttentionPanel.jsx")
    assert "}, [sessionId, formId, formSqs, packageSqs, refreshTick]);" in panel
    assert "What to do:" in panel
    # 30 Sep (owner): two sections drawn with the side panel's own collapsible
    # section (the one Recommendations uses), each with its (i) tip.
    assert "Section={CollapsibleSection}" in block
    assert "title={`Needs attention (${need.length})`} tooltip={NEEDS_ATTENTION_TIP}" in panel
    assert "title={`AI held back (${held.length})`} tooltip={AI_HELD_BACK_TIP}" in panel


def test_pre_download_review_reads_the_same_door():
    modal = _read(FORM_DIR / "AcordModal.jsx")
    assert "fetchNeedsAttention(sessionId)," in modal
    assert "withoutSupersededRecs(recsData?.open_recommendations || [], attention)" in modal
    assert "if (openRecs.length === 0 && attentionTotal === 0) { downloadFn({}); return; }" in modal
    assert modal.count("<NeedsAttentionSummary attention=") == 2       # review + post-download checklist
    util = _read(FRONTEND / "utils" / "needsAttention.js")
    assert "/api/needs-attention/" in util and "attention_superseded" in util
    assert "f?.ok === false" in util                                   # fail open per form


def test_pre_form_key_details_are_actions_in_both_layouts_and_no_em_dashes():
    # Owner, 30 Sep 2026 (item 9): the pointer line that only SAID where the
    # list would appear is gone; each missing key detail opens its fix.
    util = _read(FRONTEND / "utils" / "needsAttention.js")
    assert "export const NEEDS_ATTENTION_PREFORM_NOTE" not in util
    modal = _read(FORM_DIR / "AcordModal.jsx")
    rail = _read(FORM_DIR / "review" / "ReviewRailLayout.jsx")
    assert "NEEDS_ATTENTION_PREFORM_NOTE" not in modal and "NEEDS_ATTENTION_PREFORM_NOTE" not in rail
    assert "<KeyDetailsMissing keyDetails={keyDetails} onFix={openKeyDetailFix} />" in modal
    assert "onFixKeyDetail={openKeyDetailFix}" in modal
    assert "<KeyDetailsMissing keyDetails={keyDetails} onFix={onFixKeyDetail}" in rail
    comp = _read(FORM_DIR / "review" / "KeyDetailsMissing.jsx")
    assert "onClick={() => onFix(it)}" in comp and "it.resolution ?" in comp
    # a key detail is not an issue: nothing is marked resolved for it
    assert "if (issue?.__keyDetail) { setResolutionIssue(null); return; }" in modal
    for p in (FORM_DIR / "NeedsAttentionPanel.jsx", FORM_DIR / "usePdfFieldFocus.js",
              FORM_DIR / "review" / "KeyDetailsMissing.jsx",
              FRONTEND / "utils" / "needsAttention.js", BACKEND / "services" / "needs_attention.py"):
        assert "—" not in _read(p), p


def test_the_dec_index_purge_changes_wording_only():
    # Production deletes dec_page_entries after generation
    # (PURGE_DEC_INDEX_AFTER_GENERATION). The list must not change shape.
    gf, facts, flags = _live("b8d6")
    before = na.needs_attention(gf["ACORD_125"], facts, "ACORD_125", flags=flags)
    purged = {k: v for k, v in facts.items() if k != "dec_page_entries"}
    after = na.needs_attention(gf["ACORD_125"], purged, "ACORD_125", flags=flags)
    shape = lambda rows: [(r["field"], r["status"], r["score_effect"], r["label"]) for r in rows]  # noqa: E731
    assert shape(before) == shape(after)
    phone = next(r for r in after if r["field"] == "NamedInsured_Primary_PhoneNumber_A")
    assert "expiring producer contact phone" in phone["reason"]
