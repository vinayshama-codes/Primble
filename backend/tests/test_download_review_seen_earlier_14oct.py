"""The download review lists only what an earlier screen showed and is still
open (owner, 14 Oct 2026).

Brent: *"Even after everything has seemingly been addressed on the forms, the
download modal is flooded with what appears to be new flags and issues that
were not present prior to form selection or during form fulfillment."*
Owner: *"download screen should have recommendations, warnings, hard stops etc
if these things have been seen by user earlier and he hasn't fixed them."*

The review reads two lists. GET /api/needs-attention is the side panel's own
door (shown earlier by construction). GET /api/audit/open is decided by
`needs_attention.download_review_rows`:
  * a recommendation card is listed while a form's side panel shows it;
  * the download gate (`field_qa.check_hard_block`) is listed LIVE - and the side
    panel now lists its boxes too (`blocks_download`), so it is seen first;
  * every other stored field-QA / field-mapping row (mismatch, high-impact blank,
    schedule row, carrier in an owner box) is shown on no earlier screen: gone.

Live shape: the owner's run `18ecbfa8` (12 Oct, Choice Electric, 8 forms), read
read-only from the stored session: its open stored rows, the cards each form
shows, and the ACORD 140's six gate boxes (two of them held back by the AI).
Before: 233 items listed, 11 shown on no earlier screen (5 high-impact blanks, 6
gate boxes). After: 226 listed, every one shown earlier.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "")

import services.field_qa as fq                                       # noqa: E402
import services.needs_attention as na                                # noqa: E402

FRONT = BACKEND.parent / "frontend" / "src"
MODAL = FRONT / "components" / "form" / "AcordModal.jsx"
PANEL = FRONT / "components" / "form" / "NeedsAttentionPanel.jsx"
ATTN_JS = FRONT / "utils" / "needsAttention.js"

# ── The live shape (18ecbfa8) ─────────────────────────────────────────────────
_GATE = ["CommercialStructure_BuiltYear_A", "CommercialStructure_BuiltYear_B",
         "Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B",
         "BuildingFireProtection_ProtectionClassCode_A", "BuildingFireProtection_ProtectionClassCode_B"]
_GUARD = [
    {"field": "Construction_RoofMaterialCode_A", "reason": "AI_OPTION_LIST_DUMP", "form_id": "ACORD_140",
     "in_documents": False, "removed_value": "Composition"},
    {"field": "Construction_RoofMaterialCode_B", "reason": "AI_OPTION_LIST_DUMP", "form_id": "ACORD_140",
     "in_documents": False, "removed_value": "Metal"},
]
_CARDS = {
    "ACORD_125": ["rec_mailing_address", "rec_narrative_components",
                  "rec_loss_no_loss_history_provided_required_for_carrier_submission",
                  "rec_contact_name", "rec_submission_carrier_name"],
    "ACORD_126": ["rec_gl_class_codes", "rec_narrative_components",
                  "rec_loss_no_loss_history_provided_required_for_carrier_submission", "rec_gl_form_type"],
    "ACORD_130": ["rec_wc_officer_exclusions", "rec_narrative_components"],
    "ACORD_140": ["rec_min_cope", "rec_narrative_components"],
}


def _hb(field):
    return {"rec_id": f"fieldqa_hardblock_ACORD_140_{field}_missing_required_gate"[:120], "field": field,
            "recommendation_type": "suggestion",
            "message": f'ACORD 140: "{field}" is required for this section (a related field was already '
                       "filled) but empty. Fix: Provide a value before sending - this blocks a clean download.",
            "score_impact": None}


_STORED = (
    [{"rec_id": rid, "field": None, "recommendation_type": "hard_stop" if rid == "rec_min_cope" else "missing_field",
      "message": rid, "score_impact": 0}
     for rid in sorted({r for ids in _CARDS.values() for r in ids})]
    + [{"rec_id": "fieldqa_ACORD_130_not_answered_form_group", "field": None, "recommendation_type": "suggestion",
        "message": "ACORD 130: 2 high-impact boxes were left blank by the AI (no value found in the documents): "
                   "Full name of the partner or executive officer ...", "score_impact": None},
       {"rec_id": "fieldqa_ACORD_140_AdditionalInterest_FullName_not_answered_grp",
        "field": "AdditionalInterest_FullName_B", "recommendation_type": "suggestion",
        "message": 'ACORD 140: "Additional interest\'s full name" is a high-impact box the AI left blank '
                   "(no value found in the documents). Fix: Answer it on the form if it applies.",
        "score_impact": None},
       {"rec_id": "fieldqa_ACORD_125_BuildingOccupancy_OperationsDescription_A_mismatch",
        "field": "BuildingOccupancy_OperationsDescription_A", "recommendation_type": "suggestion",
        "message": 'ACORD 125: "Description of operations" shows "Office and shop" but the source value is '
                   '"Electrical contractor". Fix: Re-confirm the correct value so it applies uniformly.',
        "score_impact": None},
       {"rec_id": "fieldqa_ACORD_127_Driver_BirthDate_B_schedule_row_invalid", "field": "Driver_BirthDate_B",
        "recommendation_type": "suggestion", "message": "ACORD 127: driver row 2 date of birth is not a date.",
        "score_impact": None},
       {"rec_id": "fieldmap_ACORD_127_AdditionalInterest_FullName_carrier_in_owner",
        "field": "AdditionalInterest_FullName_A", "recommendation_type": "suggestion",
        "message": 'ACORD 127: "Additional interest\'s full name" holds the carrier "EMCASCO Insurance Company".',
        "score_impact": None},
       {"rec_id": "fieldqa_attn_ACORD_125_missing", "field": None, "recommendation_type": "suggestion",
        "message": "ACORD 125 - Missing (3): ...", "score_impact": None},
       {"rec_id": "fieldqa_summary", "field": None, "recommendation_type": "suggestion",
        "message": "Field QA: 4 required fields still empty", "score_impact": None}]
    + [_hb(f) for f in _GATE]
)


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


# The filled siblings that make the gate boxes required (both buildings).
_FILLED = {"Construction_ConstructionCode_A": "Joisted masonry", "Construction_ConstructionCode_B": "Joisted masonry"}


def _form140(field_state=None, confidence=None, guard=None):
    conf = {f: "missing_required_gate" for f in _GATE}
    conf.update({f: "filled" for f in _FILLED})
    conf.update(confidence or {})
    return {"form_id": "ACORD_140", "field_state": {**_FILLED, **(field_state or {})}, "confidence": conf,
            "guard_blanks": copy.deepcopy(_GUARD if guard is None else guard),
            "form": {"template_file": "ACORD_140.pdf"}, "schema": _schema("ACORD_140"),
            "sqs": {"recommendations": [{"rec_id": r, "message": r} for r in _CARDS["ACORD_140"]]}}


def _generated():
    gen = {fid: {"form_id": fid, "field_state": {}, "confidence": {}, "guard_blanks": [],
                 "form": {"template_file": f"{fid}.pdf"},
                 "sqs": {"recommendations": [{"rec_id": r, "message": r} for r in ids]}}
           for fid, ids in _CARDS.items() if fid != "ACORD_140"}
    gen["ACORD_140"] = _form140()
    return gen


def _keys(rows):
    return sorted((r["form_id"], r["field"], r["reason_code"]) for r in rows)


# ══ The stored rows: only a card the side panel shows, and the live gate ═══════

def test_the_live_run_lists_its_nine_cards_and_the_live_gate_only():
    gen = _generated()
    live = fq.to_recommendation_rows({"results": na.hard_block_findings(gen, {})})
    out = na.download_review_rows(copy.deepcopy(_STORED), gen, live)
    ids = [r["rec_id"] for r in out]
    cards = sorted({r for v in _CARDS.values() for r in v})
    assert sorted(i for i in ids if i.startswith("rec_")) == cards                 # all 9, each on a form
    for gone in ("fieldqa_ACORD_130_not_answered_form_group",
                 "fieldqa_ACORD_140_AdditionalInterest_FullName_not_answered_grp",
                 "fieldqa_ACORD_125_BuildingOccupancy_OperationsDescription_A_mismatch",
                 "fieldqa_ACORD_127_Driver_BirthDate_B_schedule_row_invalid",
                 "fieldmap_ACORD_127_AdditionalInterest_FullName_carrier_in_owner"):
        assert gone not in ids, gone                                              # no earlier screen
    assert "fieldqa_attn_ACORD_125_missing" in ids and "fieldqa_summary" in ids    # fallback summaries stay
    hard = [r for r in out if na.is_hard_block_row(r["rec_id"])]
    assert sorted(r["field"] for r in hard) == sorted(_GATE)                      # the gate, live, once each
    assert all(r["component"] == "ACORD_140" and r["form_id"] == "ACORD_140" for r in hard)
    assert len(ids) == len(set(ids))


def test_a_card_no_form_shows_any_more_is_not_listed():
    # The stored row is still open (the card sync has not run since the fix),
    # but no side panel shows the card: it is fixed as far as any screen goes.
    gen = _generated()
    stored = copy.deepcopy(_STORED) + [{"rec_id": "rec_premises_interest", "field": "premises_interest",
                                         "recommendation_type": "missing_field",
                                         "message": "ACORD 125 premises: does the insured own or rent ...",
                                         "score_impact": 0}]
    out = na.download_review_rows(stored, gen, [])
    assert "rec_premises_interest" not in [r["rec_id"] for r in out]
    gen["ACORD_125"]["sqs"]["recommendations"].append({"rec_id": "rec_premises_interest", "message": "x"})
    assert "rec_premises_interest" in [r["rec_id"] for r in na.download_review_rows(stored, gen, [])]


def test_a_plain_string_card_is_matched_by_its_stored_id():
    from services.audit_service import _fallback_rec_id
    gen = {"ACORD_125": {"sqs": {"recommendations": ["Provide the FEIN"]}}}
    rid = _fallback_rec_id("Provide the FEIN")
    out = na.download_review_rows([{"rec_id": rid, "message": "Provide the FEIN"},
                                   {"rec_id": _fallback_rec_id("Gone"), "message": "Gone"}], gen, [])
    assert [r["rec_id"] for r in out] == [rid]


def test_a_dismissed_or_resolved_row_never_reaches_the_review():
    # The query the review reads excludes both; nothing here may put one back.
    import inspect
    from services.audit_service import get_open_recommendations
    src = inspect.getsource(get_open_recommendations)
    assert "action IS DISTINCT FROM 'resolved'" in src and "action IS DISTINCT FROM 'dismissed'" in src
    # A fixed gate box is gone from the live list even while its stored row is open.
    gen = _generated()
    gen["ACORD_140"]["field_state"] = {"CommercialStructure_BuiltYear_A": "1998"}
    gen["ACORD_140"]["confidence"]["CommercialStructure_BuiltYear_A"] = "producer"
    live = fq.to_recommendation_rows({"results": na.hard_block_findings(gen, {})})
    out = na.download_review_rows(copy.deepcopy(_STORED), gen, live)
    fields = [r["field"] for r in out if na.is_hard_block_row(r["rec_id"])]
    assert "CommercialStructure_BuiltYear_A" not in fields and len(fields) == 5


def test_a_failed_gate_check_keeps_the_stored_gate_rows():
    out = na.download_review_rows(copy.deepcopy(_STORED), _generated(), None)
    assert sum(na.is_hard_block_row(r["rec_id"]) for r in out) == 6


def test_no_generated_forms_leaves_the_rows_as_they_are():
    rows = copy.deepcopy(_STORED)
    assert na.download_review_rows(rows, {}, []) == rows
    assert na.download_review_rows([], _generated(), []) == []


# ══ The gate's boxes are in the side panel before the review lists them ═══════

def test_before_the_side_panel_never_named_four_of_the_six_gate_boxes():
    rows = na.needs_attention(_form140(), {}, "ACORD_140")
    named = {r["field"] for r in rows} & set(_GATE)
    # Only the two the AI held back were listed - as "AI held back", not as
    # something that blocks the download.
    assert named == {"Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B"}
    assert not any(r.get("blocks_download") for r in rows)


def test_the_side_panel_now_lists_every_gate_box_once_and_says_it_blocks():
    gen = {"ACORD_140": _form140()}
    res = na.needs_attention_for_session(gen, {}, hard_blocks=True)
    rows = res["forms"][0]["rows"]
    blocking = {r["field"]: r for r in rows if r.get("blocks_download")}
    assert sorted(blocking) == sorted(_GATE)
    assert len([r for r in rows if r["field"] in _GATE]) == 6                     # one row per box
    for f in ("Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B"):
        # its row kept, flagged - Missing since 23 Oct 2026 (Brent: the refused
        # value is the audit record's, never "AI held back")
        assert blocking[f]["status"] == na.STATUS_MISSING
    for f in ("CommercialStructure_BuiltYear_A", "BuildingFireProtection_ProtectionClassCode_B"):
        r = blocking[f]
        assert r["status"] == na.STATUS_MISSING and r["required"] is True
        assert r["what_to_do"] == na.HARD_BLOCK_WHAT_TO_DO and r["page"]
    assert "(row 2)" in blocking["CommercialStructure_BuiltYear_B"]["label"]
    assert res["counts"]["total"] == len(rows)                                    # counts = rows
    # The route's door without the flag is exactly as before.
    plain = na.needs_attention_for_session(gen, {})["forms"][0]["rows"]
    assert not any(r.get("blocks_download") for r in plain)


def test_the_side_panel_names_exactly_what_the_download_gate_holds():
    gen = {"ACORD_140": _form140(), "ACORD_125": _generated()["ACORD_125"]}
    gate = fq.check_hard_block(gen, merged_facts={})
    assert _keys(na.hard_block_findings(gen, {})) == _keys(gate)
    rows = [r for f in na.needs_attention_for_session(gen, {}, hard_blocks=True)["forms"] for r in f["rows"]
            if r.get("blocks_download")]
    assert sorted((r["form_id"], r["field"]) for r in rows) == sorted((g["form_id"], g["field"]) for g in gate)


def test_a_placeholder_is_one_missing_row_never_a_verify_row():
    f = "BuildingFireProtection_FireDistrictName_A"
    fr = _form140({f: "1st distinct value"}, {f: "low_confidence"}, guard=[])
    before = [r for r in na.needs_attention(fr, {}, "ACORD_140") if r["field"] == f]
    assert [r["status"] for r in before] == [na.STATUS_VERIFY]               # Confirm would keep it
    gate = fq.check_hard_block({"ACORD_140": fr}, merged_facts={})
    assert (f, "placeholder_value") in {(g["field"], g["reason_code"]) for g in gate}
    after = [r for r in na.needs_attention_for_session({"ACORD_140": fr}, {}, hard_blocks=True)["forms"][0]["rows"]
             if r["field"] == f]
    assert len(after) == 1 and after[0]["status"] == na.STATUS_MISSING and after[0]["blocks_download"]
    assert "placeholder" in after[0]["reason"] and "1st distinct value" in after[0]["reason"]


def test_a_gate_box_holding_a_value_asks_the_gate_itself():
    # A value under a stale gate label: the gate's own value-vs-source pass
    # decides, so the cheap path hands that form to `check_hard_block`.
    fr = _form140({"CommercialStructure_BuiltYear_A": "1998"})
    gen = {"ACORD_140": fr}
    assert _keys(na.hard_block_findings(gen, {})) == _keys(fq.check_hard_block(gen, merged_facts={}))
    rows = na.needs_attention_for_session(gen, {}, hard_blocks=True)["forms"][0]["rows"]
    built = [r for r in rows if r["field"] == "CommercialStructure_BuiltYear_A"]
    assert len(built) == 1 and built[0]["status"] == na.STATUS_VERIFY and built[0]["blocks_download"]


def test_a_form_that_cannot_block_is_never_checked(monkeypatch):
    calls = []
    real = fq.run_field_qa
    monkeypatch.setattr(fq, "run_field_qa", lambda *a, **k: calls.append(sorted(a[0])) or real(*a, **k))
    gen = _generated()
    na.hard_block_findings(gen, {})
    assert calls == [["ACORD_140"]]
    calls.clear()
    del gen["ACORD_140"]
    assert na.hard_block_findings(gen, {}) == [] and calls == []


# ══ The routes ═════════════════════════════════════════════════════════════════

def _call(coro):
    return json.loads(asyncio.run(coro).body)


def test_the_open_route_filters_against_the_session_it_already_read(monkeypatch):
    import routes.audit_routes as ar
    gen = _generated()

    async def fake_owner(sid, user):
        return {"user_id": "u1", "generated_forms": gen, "facts": {}}

    async def fake_open(sid, include_acknowledged=False):
        assert include_acknowledged is True
        return copy.deepcopy(_STORED)

    async def no_statuses(sid):
        return []

    monkeypatch.setattr(ar, "_verify_session_owner", fake_owner)
    monkeypatch.setattr(ar, "get_open_recommendations", fake_open)
    monkeypatch.setattr(ar, "get_issue_statuses", no_statuses)
    body = _call(ar.get_open_recs("sid", {"id": "u1"}))
    recs = body["open_recommendations"]
    assert body["count"] == len(recs) == 9 + 2 + 6                               # cards, summaries, gate
    marks = {r["rec_id"]: bool(r.get("attention_superseded")) for r in recs}
    assert marks["fieldqa_attn_ACORD_125_missing"] and marks["fieldqa_summary"]
    assert not any(v for k, v in marks.items() if k.startswith("rec_") or "hardblock_" in k)


def test_the_open_route_lists_everything_when_it_cannot_judge(monkeypatch):
    import routes.audit_routes as ar

    async def fake_owner(sid, user):
        return {"user_id": "u1", "generated_forms": _generated(), "facts": {}}

    async def fake_open(sid, include_acknowledged=False):
        return copy.deepcopy(_STORED)

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(ar, "_verify_session_owner", fake_owner)
    monkeypatch.setattr(ar, "get_open_recommendations", fake_open)
    monkeypatch.setattr(na, "download_review_rows", boom)
    assert _call(ar.get_open_recs("sid", {"id": "u1"}))["count"] == len(_STORED)


def test_the_side_panel_route_asks_for_the_gate_boxes(monkeypatch):
    import routes.audit_routes as ar
    gen = {"ACORD_140": _form140()}

    async def fake_get(sid):
        return {"user_id": "u1", "generated_forms": gen, "facts": {}, "flags": {}}

    async def no_rows(sid):
        return []

    monkeypatch.setattr(ar, "get_processing_session", fake_get)
    monkeypatch.setattr(ar, "_stored_mismatch_rows", no_rows)
    body = _call(ar.get_needs_attention("sid", "ACORD_140", {"id": "u1"}))
    rows = body["forms"][0]["rows"]
    assert sorted(r["field"] for r in rows if r.get("blocks_download")) == sorted(_GATE)


# ══ The review screens: one listing per box, counts = what is listed ══════════

def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    src = re.sub(r'^import \{ API_BASE \} from "\.\./config/constants";\n', 'const API_BASE = "";\n',
                 ATTN_JS.read_text(encoding="utf-8"), flags=re.M)
    mod = tmp_path / "na.mjs"
    mod.write_text(src, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as A from {json.dumps(mod.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _review_payload():
    gen = _generated()
    recs = na.download_review_rows(copy.deepcopy(_STORED), gen,
                                   fq.to_recommendation_rows({"results": na.hard_block_findings(gen, {})}))
    recs = [r for r in recs if not str(r["rec_id"]).startswith(("fieldqa_attn_", "fieldqa_summary"))]
    attention = na.needs_attention_for_session({"ACORD_140": gen["ACORD_140"]}, {}, hard_blocks=True)
    attention["document_suggestions"] = []
    return recs, attention


def test_a_gate_box_is_listed_once_under_hard_stops_and_counted_once(tmp_path):
    recs, attention = _review_payload()
    out = _node(tmp_path, f"""
const recs = {json.dumps(recs)}; const att = {json.dumps(attention)};
const shown = A.withoutListedBoxes(recs, att);
const rows = shown.forms.flatMap(f => f.rows);
const c = A.downloadReviewCounts(recs, att);
console.log(JSON.stringify({{ c, n: rows.length, gate: rows.filter(r => r.blocks_download).length,
  orig: att.forms.flatMap(f => f.rows).length, kept: A.withoutListedBoxes([], att) === att }}));
""")
    c = out["c"]
    assert out["gate"] == 0 and out["n"] == out["orig"] - 6                        # folded into Hard Stops
    assert c["hard"] == 6 + 1                                                       # the gate + rec_min_cope
    # counts = what is listed: every rec one by one, every row once (in its group)
    assert c["total"] == len(recs) + out["n"]
    assert c["toFix"] == c["hard"] + c["warnings"] + c["recommendations"] + c["missing"]
    assert out["kept"] is True                                                      # no hard stops: untouched


def test_without_the_hard_stops_the_gate_box_stays_in_the_list(tmp_path):
    _recs, attention = _review_payload()
    out = _node(tmp_path, f"""
const att = {json.dumps(attention)};
const soft = [{{rec_id: "rec_gl_form_type", recommendation_type: "missing_field"}}];
const shown = A.withoutListedBoxes(soft, att);
console.log(JSON.stringify(shown.forms.flatMap(f => f.rows).filter(r => r.blocks_download).length));
""")
    assert out == 6


def test_both_download_screens_draw_the_same_list():
    body = MODAL.read_text(encoding="utf-8")
    pre = body[body.index("function DownloadPreflightModal"):body.index("function DashboardAssistant")]
    assert "<DownloadReviewList openRecs={openRecs} attention={attention} />" in pre
    assert "downloadReviewHeadline(counts)" in pre and "Also listed" not in pre
    i = body.index("Post-download checklist")
    post = body[i:i + 4000]
    assert "<DownloadReviewList openRecs={recs} attention={preflightAttention} />" in post
    assert "To fix before sending (${counts.toFix})" in post and "Also listed" not in post
    assert body.count("<DownloadReviewList ") == 2
    assert "NeedsAttentionSummary" not in body and "alsoListedText" not in body


def test_the_side_panel_says_a_box_blocks_the_download():
    panel = PANEL.read_text(encoding="utf-8")
    assert 'export const BLOCKS_DOWNLOAD_TEXT = "Blocks a clean download until it is fixed.";' in panel
    assert "{row.blocks_download && (" in panel
    assert '(row.status !== "missing" || row.blocks_download || row.finding) && row.reason' in panel
    for text in (na.HARD_BLOCK_WHAT_TO_DO, na._PLACEHOLDER_WHAT_TO_DO,
                 "Blocks a clean download until it is fixed."):
        assert "—" not in text


def test_the_route_source_keeps_one_door():
    src = (BACKEND / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    i = src.index("async def get_open_recs")
    block = src[i:src.index("@router.get(\"/api/needs-attention/{session_id}\")")]
    assert "download_review_rows(recs, generated, live_hard, review_issues=issues)" in block
    assert "hard_block_findings" in block and "review_issue_rows(" in block
    j = src.index("async def get_needs_attention")
    seg = src[j:j + 3000]
    assert "hard_blocks=True" in seg and "findings=True" in seg and "mismatch_rows=" in seg


# ══ Round 2 (owner, 14 Oct 2026) ═══════════════════════════════════════════════
# 1. The Review page's open hard stops and warnings (and the editor's Cross-Form
#    panel) are on the download screen - one problem, one line.
# 2. Figure 33's findings (high-impact blank boxes, a carrier / policy value in
#    an owner box, a value mismatch) are side-panel rows first.
# 3. The download review lists one by one only the items to fix; Please verify,
#    AI held back, the applicant's steps and new-document choices are one line
#    each with a count and Show.

ISSUES_18EC = json.loads((BACKEND / "tests" / "fixtures" / "download_review_18ecbfa8_14oct.json").read_text())

# What the editor shows on 18ecbfa8 (each card's `field` as stored).
_CARD_FIELDS = {"rec_mailing_address": "mailing_address", "rec_contact_name": "contact_name",
                "rec_gl_class_codes": "gl_class_codes_by_location", "rec_min_cope": "locations",
                "rec_gl_form_type": "gl_form_type", "rec_wc_officer_exclusions": "wc_officer_exclusions",
                "rec_narrative_components": "additional_remarks_text",
                "rec_submission_carrier_name": "submission_carrier_name",
                "rec_loss_no_loss_history_provided_required_for_carrier_submission":
                    "loss_history_no_prior_losses_indicator"}


def _session_18ec():
    gen = _generated()
    return {"user_id": "u1", "generated_forms": gen, "facts": {}, "flags": {},
            **{k: copy.deepcopy(v) for k, v in ISSUES_18EC.items() if not k.startswith("_")}}


def _stored_with_fields():
    rows = copy.deepcopy(_STORED)
    for r in rows:
        if r["rec_id"] in _CARD_FIELDS:
            r["field"] = _CARD_FIELDS[r["rec_id"]]
            r["score_impact"] = 2 if r["rec_id"] in ("rec_mailing_address", "rec_contact_name") else 0
    return rows


def _issues(session, statuses=()):
    import routes.audit_routes as ar
    return na.review_issue_rows(
        [ar._review_page_view(session),
         ar._grouped_cross_issues_for_panel(session["cross_issues_last"], facts=session["facts"])],
        list(statuses))


def test_the_review_page_issues_reach_the_download_screen_once_each():
    session = _session_18ec()
    issues = _issues(session)
    by_code = {i["code"]: i for i in issues}
    # the page's 1 hard stop + 4 warnings, its legacy COPE twin hidden as on screen
    assert sorted(by_code) == ["legacy_auto_driver_schedule_missing", "legacy_gl_no_class_codes",
                               "minimum_viable_cope_missing", "tier1_missing_Applicant mailing address",
                               "tier1_missing_Contact information"]
    assert by_code["minimum_viable_cope_missing"]["recommendation_type"] == "hard_stop"
    assert by_code["legacy_auto_driver_schedule_missing"]["recommendation_type"] == "soft_warning"
    gen = session["generated_forms"]
    live = fq.to_recommendation_rows({"results": na.hard_block_findings(gen, {})})
    out = na.download_review_rows(_stored_with_fields(), gen, live, review_issues=issues)
    ids = [r["rec_id"] for r in out]
    assert len(ids) == len(set(ids))
    # "Driver schedule not provided" was open on the Review page and absent at download
    assert any(r.get("code") == "legacy_auto_driver_schedule_missing" for r in out)
    # one problem, one line: each card a Review-page issue fixes is that issue's line
    absorbed = {c: i["code"] for i in out if i.get("review_issue") for c in i.get("absorbed_cards", [])}
    assert absorbed == {"rec_min_cope": "minimum_viable_cope_missing",
                        "rec_mailing_address": "tier1_missing_Applicant mailing address",
                        "rec_contact_name": "tier1_missing_Contact information",
                        "rec_gl_class_codes": "legacy_gl_no_class_codes"}
    assert not set(absorbed) & set(ids)
    mailing = next(r for r in out if r.get("code") == "tier1_missing_Applicant mailing address")
    assert mailing["score_impact"] == 2                     # the card's points travel with the line
    cards = sorted(r["rec_id"] for r in out if str(r["rec_id"]).startswith("rec_"))
    assert cards == ["rec_gl_form_type", "rec_loss_no_loss_history_provided_required_for_carrier_submission",
                     "rec_narrative_components", "rec_submission_carrier_name", "rec_wc_officer_exclusions"]
    assert all(r.get("fix_facts") for r in out if str(r["rec_id"]).startswith("rec_"))


def test_a_dismissed_issue_is_not_listed_and_a_resolved_one_that_still_fires_is():
    session = _session_18ec()
    issues = _issues(session)
    drivers = next(i for i in issues if i["code"] == "legacy_auto_driver_schedule_missing")
    gl = next(i for i in issues if i["code"] == "legacy_gl_no_class_codes")
    again = _issues(session, [{"issue_id": drivers["issue_id"], "status": "dismissed"},
                              {"issue_id": gl["issue_id"], "status": "resolved"}])
    codes = [i["code"] for i in again]
    assert "legacy_auto_driver_schedule_missing" not in codes      # dismissed
    assert "legacy_gl_no_class_codes" in codes                      # still fires: the page lists it too
    # fixed = no longer fires: gone from the page, gone from the download screen
    session["structured_issues"] = [i for i in session["structured_issues"]
                                    if i["code"] != "legacy_gl_no_class_codes"]
    session["soft_stops"] = [m for m in session["soft_stops"] if not m.startswith("GL coverage")]
    assert "legacy_gl_no_class_codes" not in [i["code"] for i in _issues(session)]


def test_the_review_page_view_is_the_page_reload_s_own(monkeypatch):
    """`_review_page_view` hands `grouped_with_package_caps` what the page's
    reload (`form_routes.get_extraction_result`) hands it - pinned on the code,
    so a change there fails here instead of drifting."""
    import ast as _ast
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, _ast.AsyncFunctionDef) and n.name == "get_extraction_result")
    seg = _ast.get_source_segment(src, fn)
    call = seg[seg.index("_grouped_issues = _grouped_with_package_caps("):]
    call = call[:call.index("\n    )") + 6]
    for arg in ('proc_session.get("structured_issues") or []', "hard_stops", "_final_soft_stops",
                "_pkg_now", 'cross_issues=_cross_shown',  # build 26: live stops before forms (TEST updated)
                'facts=proc_session.get("facts") or {}'):
        assert arg in call, arg
    assert 'hard_stops = proc_session.get("hard_stops", [])' in seg
    assert '_final_soft_stops = proc_session.get("soft_stops", [])' in seg
    assert "_pkg_now, _key_now = _status_now" in seg


def test_a_hard_stop_card_folded_into_a_warning_keeps_hard_stop_severity():
    issue = {"rec_id": "iss_x", "recommendation_type": "soft_warning", "message": "COPE",
             "fix_facts": ["year_built"], "review_issue": True}
    card = {"rec_id": "rec_year_built", "field": "year_built", "recommendation_type": "hard_stop",
            "message": "Year built", "score_impact": 4}
    gen = {"ACORD_140": {"sqs": {"recommendations": [{"rec_id": "rec_year_built", "message": "Year built"}]}}}
    out = na.download_review_rows([card], gen, [], review_issues=[issue])
    assert [(r["rec_id"], r["recommendation_type"], r["score_impact"]) for r in out] == [
        ("iss_x", "hard_stop", 4)]


def test_the_location_card_is_fixed_by_the_location_table():
    # `locations` is rebuilt from the location table, so the COPE card and the
    # COPE hard stop (whose fix opens that table) are one problem.
    from services import extraction_service as es
    facts = {"property_locations": [{"address": "1 Main St, Denver, CO 80221"}]}
    es.sync_location_list(facts)
    assert facts["locations"] == ["1 Main St, Denver, CO 80221"]
    assert na._FACT_DERIVED_FROM_SCHEDULE == {"locations": "property_locations"}
    assert "property_locations" in na.card_fix_keys({"field": "locations"})


def test_the_cope_card_reads_what_the_scorer_reads():
    import ast as _ast
    src = (BACKEND / "services" / "sqs_service.py").read_text(encoding="utf-8")
    i = src.index("_min_cope_parts = [")
    block = src[i:src.index("]", src.index("building or BPP value", i)) + 1]
    read = re.findall(r'_fv\(facts, "([a-z_]+)"\)', block)
    assert read and set(read) == set(na._CARD_READS["rec_min_cope"])
    assert '"rec_id": "rec_min_cope"' in src and '"field": "locations"' in src
    # a one-building package's COPE fix is a plain field form - still one line
    issue = {"rec_id": "iss_cope", "recommendation_type": "hard_stop", "review_issue": True,
             "fix_facts": ["construction_type", "occupancy_type", "property_bpp_value",
                           "property_building_value"]}
    card = {"rec_id": "rec_min_cope", "field": "locations", "recommendation_type": "hard_stop"}
    gen = {"ACORD_140": {"sqs": {"recommendations": [{"rec_id": "rec_min_cope", "message": "m"}]}}}
    out = na.download_review_rows([card], gen, [], review_issues=[issue])
    assert [r["rec_id"] for r in out] == ["iss_cope"] and out[0]["absorbed_cards"] == ["rec_min_cope"]


def test_the_open_route_lists_the_review_page_issues(monkeypatch):
    import routes.audit_routes as ar
    session = _session_18ec()

    async def fake_owner(sid, user):
        return session

    async def fake_open(sid, include_acknowledged=False):
        return _stored_with_fields()

    async def no_statuses(sid):
        return []

    monkeypatch.setattr(ar, "_verify_session_owner", fake_owner)
    monkeypatch.setattr(ar, "get_open_recommendations", fake_open)
    monkeypatch.setattr(ar, "get_issue_statuses", no_statuses)
    recs = _call(ar.get_open_recs("sid", {"id": "u1"}))["open_recommendations"]
    kinds = [("issue" if r.get("review_issue") else "gate" if "hardblock_" in r["rec_id"] else
              "summary" if r.get("attention_superseded") else "card") for r in recs]
    assert kinds.count("issue") == 5 and kinds.count("gate") == 6 and kinds.count("card") == 5


# ── 2. Figure 33's findings, side panel first ────────────────────────────────

def _f125(field_state=None, confidence=None):
    return {"form_id": "ACORD_125", "field_state": dict(field_state or {}), "confidence": dict(confidence or {}),
            "guard_blanks": [], "form": {"template_file": "ACORD_125.pdf"}, "schema": _schema("ACORD_125")}


def _f127(field_state=None, confidence=None):
    return {"form_id": "ACORD_127", "field_state": dict(field_state or {}), "confidence": dict(confidence or {}),
            "guard_blanks": [], "form": {"template_file": "ACORD_127.pdf"}, "schema": _schema("ACORD_127")}


def _rows(gen, form_id, **kw):
    res = na.needs_attention_for_session(gen, kw.pop("facts", {}), findings=True, **kw)
    return next(f["rows"] for f in res["forms"] if f["form_id"] == form_id)


def test_a_high_impact_box_the_ai_left_blank_is_a_side_panel_row_with_its_reason():
    f = "AdditionalInterest_FullName_B"
    gen = {"ACORD_125": _f125({}, {f: "low_confidence"})}
    plain = [r for r in na.needs_attention(gen["ACORD_125"], {}, "ACORD_125") if r["field"] == f]
    assert plain == []                                    # before: only the download named it
    rows = [r for r in _rows(gen, "ACORD_125") if r["field"] == f]
    assert len(rows) == 1 and rows[0]["status"] == na.STATUS_MISSING
    assert rows[0]["finding"] == na.FINDING_HIGH_IMPACT_BLANK
    assert rows[0]["reason"] == na.HIGH_IMPACT_BLANK_REASON and "trust" in rows[0]["label"]
    # field QA reports the same box as a high-impact blank - one finding, one door
    qa = fq.run_field_qa(gen, merged_facts={}, mismatches=False)
    assert any(r["field"] == f and r["reason_code"] == "not_answered" and r.get("high_impact")
               for r in qa["results"])


def test_a_carrier_in_an_owner_box_is_flagged_on_its_own_row():
    f = "AdditionalInterest_FullName_A"
    value = "EMCASCO Insurance Company"
    for label, expect_row_before in (("low_confidence", True), ("filled", False)):
        gen = {"ACORD_127": _f127({f: value}, {f: label})}
        before = [r for r in na.needs_attention(gen["ACORD_127"], {}, "ACORD_127") if r["field"] == f]
        assert bool(before) is expect_row_before
        rows = [r for r in _rows(gen, "ACORD_127") if r["field"] == f]
        assert len(rows) == 1 and rows[0]["status"] == na.STATUS_VERIFY
        assert rows[0]["finding"] == na.FINDING_NOT_THE_INSURED
        assert value in rows[0]["reason"] and "not the insured or owner" in rows[0]["reason"]
    # a value a person typed or confirmed is their decision
    gen = {"ACORD_127": _f127({f: value}, {f: "producer"})}
    assert [r for r in _rows(gen, "ACORD_127") if r["field"] == f] == []


def test_a_value_mismatch_is_flagged_while_the_box_still_shows_it():
    f = "BuildingOccupancy_OperationsDescription_A"
    stored = [{"rec_id": f"fieldqa_ACORD_125_{f}_mismatch", "field": f, "component": "ACORD_125",
               "form_id": "ACORD_125",
               "message": 'ACORD 125: "Description of what business each applicant performs" shows '
                          '"Electrical contractor office and shop" but the source value is "Electrical '
                          'contractor performing commercial work". Fix: Re-confirm the correct value so '
                          'it applies uniformly.'}]
    gen = {"ACORD_125": _f125({f: "Electrical contractor office and shop"}, {f: "filled"})}
    rows = [r for r in _rows(gen, "ACORD_125", mismatch_rows=stored) if r["field"] == f]
    assert len(rows) == 1 and rows[0]["finding"] == na.FINDING_VALUE_MISMATCH
    assert rows[0]["reason"].startswith('Shows "Electrical contractor office and shop" but the source value is')
    # the box changed since it was measured: the finding is stale, not listed
    gen = {"ACORD_125": _f125({f: "Electrical contractor"}, {f: "filled"})}
    assert [r for r in _rows(gen, "ACORD_125", mismatch_rows=stored) if r["field"] == f] == []
    # a row for another form never lands here
    gen = {"ACORD_125": _f125({f: "Electrical contractor office and shop"}, {f: "filled"})}
    other = [dict(stored[0], component="ACORD_126", form_id="ACORD_126")]
    assert [r for r in _rows(gen, "ACORD_125", mismatch_rows=other) if r["field"] == f] == []


def test_a_box_already_listed_keeps_its_one_row():
    f = "BuildingOccupancy_OperationsDescription_A"
    stored = [{"rec_id": "fieldqa_x_mismatch", "field": f, "component": "ACORD_125",
               "message": 'ACORD 125: "x" shows "Office and shop" but the source value is "Shop". Fix: y'}]
    gen = {"ACORD_125": _f125({f: "Office and shop"}, {f: "low_confidence"})}
    rows = [r for r in _rows(gen, "ACORD_125", mismatch_rows=stored) if r["field"] == f]
    assert len(rows) == 1 and rows[0]["status"] == na.STATUS_VERIFY
    assert rows[0]["finding"] == na.FINDING_VALUE_MISMATCH


def test_every_box_is_listed_once_with_every_check_on():
    # The OTHER line row ACORD 125 now prints for a redacted-premium policy (its
    # premium box blank) is listed ONCE, as a Missing to-do, whatever else
    # names the box.
    other = {"Policy_LineOfBusiness_OtherIndicator_C": "1",
             "Policy_LineOfBusiness_OtherLineOfBusinessDescription_C": "EMPLOYMENT PRACTICES"}
    conf = {"Policy_SectionAttached_OtherPremiumAmount_C": "missing_required",
            "AdditionalInterest_FullName_B": "low_confidence",
            "BuildingOccupancy_OperationsDescription_A": "low_confidence"}
    gen = {"ACORD_125": _f125({**other, "BuildingOccupancy_OperationsDescription_A": "1st distinct value"}, conf)}
    stored = [{"rec_id": "fieldqa_m_mismatch", "field": "BuildingOccupancy_OperationsDescription_A",
               "component": "ACORD_125",
               "message": 'ACORD 125: "x" shows "1st distinct value" but the source value is "Shop". Fix: y'}]
    res = na.needs_attention_for_session(gen, {}, hard_blocks=True, findings=True, mismatch_rows=stored)
    fields = [r["field"] for r in res["forms"][0]["rows"]]
    assert len(fields) == len(set(fields))
    premium = [r for r in res["forms"][0]["rows"] if r["field"] == "Policy_SectionAttached_OtherPremiumAmount_C"]
    assert len(premium) == 1 and premium[0]["status"] == na.STATUS_MISSING
    placeholder = [r for r in res["forms"][0]["rows"] if r["field"] == "BuildingOccupancy_OperationsDescription_A"]
    assert len(placeholder) == 1 and placeholder[0]["blocks_download"]     # the gate outranks the finding


def test_the_side_panel_route_lists_the_findings(monkeypatch):
    import routes.audit_routes as ar
    f = "AdditionalInterest_FullName_A"
    gen = {"ACORD_127": _f127({f: "EMCASCO Insurance Company"}, {f: "filled"})}
    seen = {}

    async def fake_get(sid):
        return {"user_id": "u1", "generated_forms": gen, "facts": {}, "flags": {},
                "underwriting_confirmations": {"applicant_name": "Choice Electric LLC"}}

    async def rows(sid):
        seen["asked"] = sid
        return []

    monkeypatch.setattr(ar, "get_processing_session", fake_get)
    monkeypatch.setattr(ar, "_stored_mismatch_rows", rows)
    body = _call(ar.get_needs_attention("sid", None, {"id": "u1"}))
    found = [r for r in body["forms"][0]["rows"] if r["field"] == f]
    assert seen == {"asked": "sid"} and len(found) == 1 and found[0]["finding"] == na.FINDING_NOT_THE_INSURED


# ── 3. The download review: fix items one by one, the rest one line each ────

def _parts_payload():
    session = _session_18ec()
    gen = session["generated_forms"]
    live = fq.to_recommendation_rows({"results": na.hard_block_findings(gen, {})})
    recs = na.download_review_rows(_stored_with_fields(), gen, live, review_issues=_issues(session))
    recs = [r for r in recs if not str(r["rec_id"]).startswith(("fieldqa_attn_", "fieldqa_summary"))]
    attention = na.needs_attention_for_session({"ACORD_140": gen["ACORD_140"]}, {}, hard_blocks=True,
                                               findings=True)
    # one Missing box the mailing-address warning fixes, one Please verify, one
    # new-document choice (the form's own signature boxes are the applicant's)
    attention["forms"][0]["rows"] += [
        {"form_id": "ACORD_140", "field": "NamedInsured_MailingAddress_LineOne_A", "status": "missing",
         "label": "Mailing address", "fact_key": "mailing_address"},
        {"form_id": "ACORD_140", "field": "X_Verify_A", "status": "verify", "label": "A value"},
    ]
    attention["document_suggestions"] = [{"id": "s1", "form_id": "ACORD_140", "field": "Y_A"}]
    return recs, attention


def test_the_review_lists_fix_items_one_by_one_and_groups_the_rest(tmp_path):
    recs, attention = _parts_payload()
    out = _node(tmp_path, f"""
const recs = {json.dumps(recs)}; const att = {json.dumps(attention)};
const p = A.downloadReviewParts(recs, att);
const c = A.downloadReviewCounts(recs, att);
const n = (g) => g.reduce((k, f) => k + f.rows.length, 0);
console.log(JSON.stringify({{ c, head: A.downloadReviewHeadline(c),
  hardFirst: p.hard.slice(0, 6).every(r => r.rec_id.includes("hardblock_")),
  hardCodes: p.hard.filter(r => r.review_issue).map(r => r.code),
  warnCodes: p.warnings.map(r => r.code),
  recIds: p.recommendations.map(r => r.rec_id),
  missingFields: p.missing.flatMap(f => f.rows.map(r => r.field)),
  groups: [n(p.verify), n(p.applicant), p.choices.length],
  noHeldBack: !("heldBack" in p) && !("heldBack" in c),
  lines: ["verify", "applicant", "choices"].map(k => A.groupLineText(k, c[k])) }}));
""")
    c = out["c"]
    assert out["hardFirst"] is True                                   # the gate's boxes first
    assert out["hardCodes"] == ["minimum_viable_cope_missing"]
    assert sorted(out["warnCodes"]) == ["legacy_auto_driver_schedule_missing", "legacy_gl_no_class_codes",
                                        "tier1_missing_Applicant mailing address",
                                        "tier1_missing_Contact information"]
    assert len(out["recIds"]) == 5
    # the Missing mailing-address box is the warning's line, not a second one;
    # the gate's boxes are Hard Stops, not Missing
    assert "NamedInsured_MailingAddress_LineOne_A" not in out["missingFields"]
    assert not set(out["missingFields"]) & set(_GATE)
    assert c["hard"] == 7 and c["warnings"] == 4 and c["recommendations"] == 5
    assert c["toFix"] == c["hard"] + c["warnings"] + c["recommendations"] + c["missing"]
    assert out["head"] == f"{c['toFix']} items to fix - review before downloading"
    # 23 Oct 2026 (Brent): no "AI held back" group on the download screen
    assert out["groups"] == [c["verify"], c["applicant"], c["choices"]] and out["noHeldBack"] is True
    assert c["verify"] >= 1 and c["applicant"] == 2 and c["choices"] == 1
    assert out["lines"][0] == f"{c['verify']} value{'s' if c['verify'] != 1 else ''} to confirm"
    assert out["lines"][1:] == ["2 boxes for the applicant to sign", "1 new-document choice"]
    assert c["total"] == c["toFix"] + c["verify"] + c["applicant"] + c["choices"]


def test_a_verify_or_applicant_row_is_never_folded_into_a_card(tmp_path):
    out = _node(tmp_path, """
const recs = [{rec_id: "rec_mailing_address", recommendation_type: "missing_field", fix_facts: ["mailing_address"]}];
const att = {forms: [{form_id: "F", rows: [
  {field: "a", status: "missing", fact_key: "mailing_address"},
  {field: "b", status: "verify", fact_key: "mailing_address"},
  {field: "c", status: "missing", applicant_step: true, fact_key: "mailing_address"},
  {field: "d", status: "ai_held_back", fact_key: "mailing_address"},
  {field: "e", status: "missing", blocks_download: true, fact_key: "mailing_address"},
  {field: "f", status: "missing", fact_key: "other"}]}]};
console.log(JSON.stringify(A.withoutListedBoxes(recs, att).forms[0].rows.map(r => r.field)));
""")
    # "d" (a stale "AI held back" row) is no longer folded either: since 23 Oct
    # 2026 no list draws that status at all (`ATTENTION_STATUS_ORDER`).
    assert out == ["b", "c", "d", "e", "f"]


def test_the_list_component_shows_each_group_as_one_line_with_show():
    panel = PANEL.read_text(encoding="utf-8")
    fn = panel[panel.index("export function DownloadReviewList"):]
    assert "groupLineText(g.key, groupCount(g.key))" in fn
    assert '{open[g.key] ? "Hide" : "Show"}' in fn and "aria-expanded={!!open[g.key]}" in fn
    assert "<FormRows groups={p.missing} />" in fn                    # Missing one by one
    assert "—" not in fn
    util = ATTN_JS.read_text(encoding="utf-8")
    for words in ('"value to confirm"', '"boxes for the applicant to sign"',
                  '"new-document choices"'):
        assert words in util
    assert '"values the AI held back"' not in util                 # 23 Oct 2026 (Brent)
    assert "—" not in util[util.index("// THE DOWNLOAD REVIEW (owner, 14 Oct 2026)"):]
