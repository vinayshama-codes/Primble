"""A document added AFTER forms is read into the forms by the AI - the NEW
document only (improving-ll.md C103, 7 Oct 2026).

Until today `session_documents.remerge_package` re-stamped only the boxes a
deterministic rule prints; nothing asked the AI the questions generation asks
it. `session_documents.run_new_document_fill` now runs the SAME shared gap fill
(`form_service.shared_gap_fill`) with the new documents as its only text, then
every post-fill guard (`map_facts_to_form(..., pre_filled_gpt=...)`), and:

  * a blank box it answers is filled with generation's AI label;
  * a box the AI filled before, answered differently now, becomes a
    suggestion - never an overwrite;
  * a box a person typed, or a rule owns, is never touched;
  * an identifier no document prints is dropped (the generation guard);
  * NEW_DOCUMENT_AI_FILL=0 -> no call; a failure leaves the forms as the
    documents door left them and says so; document changes are refused while
    it runs; the review page's NEW items are after minus before.

OCR, extraction, the model and every database write are stubbed; the merge,
the stamping engine, the guards and the shared gap fill are the real code.
"""
from __future__ import annotations

import asyncio
import copy
import io
import json
import re
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import repositories.session_repository as srepo
import routes.form_routes as fr
import routes.session_documents_routes as sdr
import services.arq_service as aq
import services.audit_service as asv
import services.extraction_pipeline as ep
import services.generation_state as gs
import services.needs_attention as na
import services.pdf_service as ps
import services.session_documents as sd
import services.upload_intake as ui
import services.yes_no_lexicon as ynl
from repositories.session_repository import resolve_facts_write

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
USER = {"id": "u1", "payment_status": "ok"}

# ── The documents ────────────────────────────────────────────────────────────

OLD_MARKER = "COMMERCIAL GENERAL LIABILITY DECLARATIONS"
NEW_MARKER = "UNDERWRITING NARRATIVE"
WEBSITE = "www.bluebirdelectricco.com"

DEC_TEXT = (
    f"{OLD_MARKER}\nNAMED INSURED: Bluebird Electric LLC\n"
    "MAILING ADDRESS: 100 Main St, Denver, CO 80202\n"
    "POLICY NUMBER: GL-104455 POLICY PERIOD: 01/01/2026 TO 01/01/2027\n"
    "INSURER: Acme Casualty Company\nEACH OCCURRENCE LIMIT $1,000,000 GENERAL AGGREGATE $2,000,000\n"
    "PREMIUM $5,400\n"
)
DEC_FACTS = {
    "applicant_name": {"value": "Bluebird Electric LLC", "confidence": "ai_high", "source": "ai"},
    "mailing_address": {"value": "100 Main St, Denver, CO 80202", "confidence": "ai_high", "source": "ai"},
    "effective_date": "01/01/2026", "expiration_date": "01/01/2027",
    "carrier_name": "Acme Casualty Company", "policy_number": "GL-104455",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "lines_of_business": ["General Liability"],
    "coverage_lines": [{"line": "Commercial General Liability", "policy_number": "GL-104455",
                        "carrier": "Acme Casualty Company", "premium": "$5,400",
                        "effective_date": "01/01/2026", "expiration_date": "01/01/2027"}],
}
NARR_TEXT = (
    f"{NEW_MARKER}\nBluebird Electric LLC is a commercial electrical contractor founded in 2009.\n"
    f"Website: {WEBSITE}\n"
    "Operations: commercial electrical installation, service and repair.\n"
    "The company employs 42 full-time employees.\n"
)
NARR_FACTS = {"applicant_name": "Bluebird Electric LLC", "num_employees": "42"}
# A box no rule prints on this package (no operations fact) that the narrative
# answers - and that every generation guard lets through (checked below).
OPS_BOX = "CommercialPolicy_OperationsDescription_A"
OPS = "Commercial electrical installation, service and repair"

_EXTRACTED = {
    NEW_MARKER: (NARR_FACTS, {}),
    OLD_MARKER: (DEC_FACTS, {"has_general_liability": True}),
}


def _doc(doc_id, filename, doc_type, text, facts, flags=None):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type, "text": text,
            "facts": copy.deepcopy(facts), "flags": dict(flags or {}),
            "classification": {"doc_type": doc_type, "source": "content", "confidence": "high"},
            "low_confidence_tokens": [], "manual_confirmation_required": []}


def DEC():
    return _doc("d-dec", "gl_dec.pdf", "dec_page", DEC_TEXT, DEC_FACTS, {"has_general_liability": True})


def NARR():
    return _doc("d-narr", "narrative.txt", "narrative", NARR_TEXT, NARR_FACTS)


# ── The store, the stubs, the model ──────────────────────────────────────────

class Store:
    """upd_processing_session's semantics: generated_forms merged per form id
    (`.update`), facts additive, every other key replaced, then deletes."""

    def __init__(self):
        self.rows: dict = {}
        self.writes: list = []

    async def get(self, sid, include_pdf=False):
        if sid not in self.rows:
            raise HTTPException(404, f"Processing session {sid} not found")
        return copy.deepcopy(self.rows[sid])

    async def upd(self, sid, payload, delete_facts=None, **_kw):
        self.writes.append({"sid": sid, "keys": sorted(payload)})
        cur = self.rows.setdefault(sid, {})
        if "generated_forms" in payload:
            gen = cur.setdefault("generated_forms", {})
            for fid, fd in payload["generated_forms"].items():
                if fid in gen:
                    gen[fid].update(copy.deepcopy(fd))
                else:
                    gen[fid] = copy.deepcopy(fd)
        for k, v in payload.items():
            if k == "generated_forms":
                continue
            if k == "facts" and isinstance(v, dict):
                resolved = resolve_facts_write(cur, v, sid)
                if resolved is not None:
                    cur["facts"] = copy.deepcopy(resolved)
            else:
                cur[k] = copy.deepcopy(v)
        for k in delete_facts or []:
            (cur.get("facts") or {}).pop(k, None)


_ASKED_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)\b")


class Model:
    """The OpenAI client the gap fill uses, recorded. Answers a field only when
    `answers` names it AND the prompt asked it."""

    def __init__(self):
        self.answers: dict = {}
        self.calls: list = []
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        with self._lock:
            self.calls.append(user)
        asked = set(_ASKED_RE.findall(user))
        vals = {f: v for f, v in self.answers.items() if f in asked}
        payload = json.dumps({"values": vals, "answers": {}, "quotes": {},
                              "raw_text_sourced": sorted(vals), "question_grounding": {}})

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
            usage = None
        return _R()


class Calls(dict):
    def add(self, name, *args, **kw):
        self.setdefault(name, []).append((args, kw))


@pytest.fixture
def env(monkeypatch, tmp_path):
    store, calls, model = Store(), Calls(), Model()

    async def _none(*_a, **_k):
        return None

    async def _zero(*_a, **_k):
        return 0

    def _rec(name, ret=True):
        async def f(*a, **k):
            calls.add(name, *a, **k)
            return ret
        return f

    async def _recalc(sid):
        calls.add("recalc", sid)
        return {"ok": True, "score_before": 70, "score_after": 72}

    async def _no_credits(*_a, **_k):
        return 0, []

    for mod in (ep, sd, sdr, fr, srepo):
        if hasattr(mod, "get_processing_session"):
            monkeypatch.setattr(mod, "get_processing_session", store.get)
        if hasattr(mod, "upd_processing_session"):
            monkeypatch.setattr(mod, "upd_processing_session", store.upd)
    monkeypatch.setattr(ep, "_submitting_account_for", _none)
    monkeypatch.setattr(ynl, "learn", _zero)
    monkeypatch.setattr(aq, "recalculate_session_scores", _recalc)
    for name in ("log_audit_event", "run_and_log_field_qa", "run_and_log_field_mapping_check",
                 "log_integrity_assessed", "log_integrity_resolution", "log_document_reclassified",
                 "log_field_change", "sync_recommendation_cards", "log_sqs_snapshot_if_changed"):
        monkeypatch.setattr(asv, name, _rec(name))
    monkeypatch.setattr(asv, "active_score_credits", _no_credits)

    # No model call but the gap fill's own: the whole-document probes must
    # never run, and the judge stays out of the recorder's way.
    def _no_probe(*_a, **_k):
        raise AssertionError("the whole-document umbrella probe ran on a new-document fill")
    monkeypatch.setattr(ps, "_fetch_umbrella_period_sync", _no_probe)
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: model)
    monkeypatch.setenv("NEW_DOCUMENT_AI_FILL", "1")

    async def _ocr(path):
        return Path(path).read_text(encoding="utf-8"), []

    async def _extract(text, doc_type, low_confidence_tokens=None):
        calls.add("extract", text)
        for marker, (facts, flags) in _EXTRACTED.items():
            if marker in text:
                return {"facts": copy.deepcopy(facts), "flags": dict(flags)}
        return {"facts": {}, "flags": {}}
    monkeypatch.setattr(ep, "extract_text", _ocr)
    monkeypatch.setattr(ep, "extract_facts_long", _extract)

    import utils.rate_limiter as rl
    import utils.concurrency as cc
    import services.job_queue as jq

    class _Queue:
        job = None

        async def count_user_active_jobs(self, _uid):
            return 0

        async def get_status(self, _jid):
            return self.job

    queue = _Queue()

    async def _acquire():
        return True

    monkeypatch.setattr(rl, "check_upload_rate_limit", _none)
    monkeypatch.setattr(cc, "try_acquire_heavy", _acquire)
    monkeypatch.setattr(cc, "release_heavy", _none)
    monkeypatch.setattr(jq, "get_job_queue", lambda: queue)
    monkeypatch.setattr(fr, "get_job_queue", lambda: queue)
    monkeypatch.setattr(ui, "UPLOAD_DIR", str(tmp_path))
    return {"store": store, "calls": calls, "model": model}


def run(coro):
    return asyncio.run(coro)


def _schema(fid):
    with open(BACKEND / "forms_schemas" / f"{fid}_schema.json", encoding="utf-8") as fh:
        return json.load(fh)


def _stamp(fid, view):
    """A form as generation's deterministic engine prints it."""
    from services.form_instances import base_form_id, facts_for_form
    from services.pdf_service import (
        _deterministic_map, _is_nonfillable_field, _schema_context, display_value_for_box,
    )
    base = base_form_id(fid)
    schema = _schema(base)
    form_view = facts_for_form(view, fid)
    state, conf = {}, {}
    with _schema_context(schema):
        for box in schema:
            if _is_nonfillable_field(box):
                continue
            raw = _deterministic_map(box, {**form_view, "_form_id": base})
            if aq._refill_value(raw):
                state[box] = str(display_value_for_box(base, box, raw, facts=form_view) or raw).strip()
                conf[box] = "filled"
    return {"form_id": fid, "form_name": fid, "schema": schema, "field_state": state,
            "mapped": dict(state), "confidence": conf, "client_filled_fields": [],
            "form": {"form_id": fid, "template_file": f"{fid}.pdf"}, "sqs": {"sqs_score": 70}}


SID = "s-fill"
FORMS = ("ACORD_125",)


def make_package(env, docs=None, forms=FORMS):
    store = env["store"]
    store.rows[SID] = {"user_id": "u1", "docs": [], "facts": {}, "flags": {}}
    run(ep._finalize_pipeline(copy.deepcopy(docs or [DEC()]), "u1", session_id=SID))
    row = store.rows[SID]
    view = sd._engine_view(row["facts"], row["flags"], list(forms))
    row["generated_forms"] = {f: _stamp(f, view) for f in forms}
    row["selected_form_ids"] = list(forms)
    row["facts"].pop("dec_page_entries", None)
    return row


def add_narrative(env):
    """The documents door adds the narrative (deterministic part), then the
    AI reading runs to completion - as the route schedules it."""
    result = run(sd.add_documents(SID, [NARR()], user_id="u1", purge_dec_index=True))
    status = run(sd.start_new_document_fill(SID, result["documents_added"], "u1",
                                            review_counts_before={"hard_stops": 0, "warnings": 0,
                                                                  "data_consistency": 0}))
    assert status["state"] == sd.FILL_RUNNING
    return run(sd.run_new_document_fill(SID, status["doc_ids"], "u1", run_id=status["run_id"]))


def gap_fields(env, fid="ACORD_125"):
    """The boxes the shared gap fill asks on this package (Pass 1 / 1.5 gaps)."""
    row = env["store"].rows[SID]
    facts = {**row["facts"], **row["flags"], "_package_form_ids": list(FORMS)}
    _m, unmatched, _d = ps.compute_form_gaps(fid, _schema(fid), facts)
    return set(unmatched)


def form(env, fid="ACORD_125"):
    return env["store"].rows[SID]["generated_forms"][fid]


# ══ 1. Only the new document reaches the model ═══════════════════════════════

def test_only_the_new_documents_text_is_sent(env):
    make_package(env)
    env["model"].answers = {OPS_BOX: OPS}
    status = add_narrative(env)
    calls = env["model"].calls
    assert calls, "the shared gap fill made no call"
    assert all(OLD_MARKER not in c for c in calls), "an old document was sent again"
    assert any(NEW_MARKER in c for c in calls)
    assert status["state"] == sd.FILL_DONE


def test_the_call_is_the_one_shared_gap_fill_with_the_new_documents_only():
    import ast
    src = (BACKEND / "services" / "session_documents.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "_new_document_answers")
    body = ast.get_source_segment(src, node)
    assert "shared_gap_fill(view" in body and 'view["docs"]' in body
    stamp = next(n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef) and n.name == "_stamp_with_answers")
    seg = ast.get_source_segment(src, stamp)
    assert "allow_llm=False" in seg and "pre_filled_gpt=answers" in seg


# ══ 2. Blank -> filled; AI -> suggestion; person / rule -> untouched ═════════

def test_a_blank_box_is_filled_with_the_ai_label(env):
    make_package(env)
    box = OPS_BOX
    assert box in gap_fields(env) and not form(env)["field_state"].get(box)
    env["model"].answers = {box: OPS}
    status = add_narrative(env)
    f = form(env)
    assert f["field_state"][box] == OPS and f["mapped"][box] == OPS
    assert f["confidence"][box] == "ai_verified"                  # found in the documents
    assert f["_pdf_cache_hash"] == "" and f["pdf_bytes"] is None
    assert status["boxes_filled"] == 1 and status["filled_by_form"] == {"ACORD_125": 1}
    assert status["forms_filled"] == [{"form_id": "ACORD_125", "label": "ACORD 125", "boxes": 1}]
    assert sd.box_owner(f, box) == "ai"
    assert env["calls"]["recalc"][-1][0] == (SID,)                # scores follow the forms
    assert env["store"].rows[SID][sd.FILL_KEY]["state"] == sd.FILL_DONE


def test_an_ai_box_answered_differently_is_a_suggestion_never_an_overwrite(env):
    row = make_package(env)
    box = OPS_BOX
    old = "Residential plumbing"
    f = row["generated_forms"]["ACORD_125"]
    f["field_state"][box] = f["mapped"][box] = old
    f["confidence"][box] = "low_confidence"
    env["model"].answers = {box: OPS}
    status = add_narrative(env)
    f = form(env)
    assert f["field_state"][box] == old                          # never overwritten
    assert status["suggestions"] == 1 and status["boxes_filled"] == 0
    held = env["store"].rows[SID][sd.SUGGESTIONS_KEY]
    assert len(held) == 1 and held[0]["suggested"] == OPS and held[0]["current"] == old
    assert held[0]["documents"] == ["narrative.txt"]
    rows = na.document_suggestion_rows(env["store"].rows[SID]["generated_forms"], held, form_id="ACORD_125")
    assert len(rows) == 1
    assert rows[0]["reason"] == f'New document says "{OPS}" - the form says "{old}".'
    assert rows[0]["status"] == "document_says" and rows[0]["suggested"] == OPS
    assert isinstance(rows[0]["page"], int) and rows[0]["id"] == held[0]["id"]
    # "Use this value" is a producer box edit: the row retires itself.
    edited = copy.deepcopy(env["store"].rows[SID]["generated_forms"])
    edited["ACORD_125"]["field_state"][box] = OPS
    edited["ACORD_125"]["confidence"][box] = "producer"
    assert na.document_suggestion_rows(edited, held) == []
    # "Keep current" retires it on the server.
    gone = run(sd.keep_current_value(SID, held[0]["id"]))
    assert gone["field"] == box and env["store"].rows[SID][sd.SUGGESTIONS_KEY] == []
    assert run(sd.keep_current_value(SID, held[0]["id"])) is None


@pytest.mark.parametrize("value,label", [
    ("Typed by the producer", "producer"),              # a person's value
    ("Typed by the client", "client_arq"),
    ("Edited since generation", "low_confidence"),      # edited; an older save kept the AI label
    ("Printed by a rule", "filled"),                    # a rule's value
])
def test_person_typed_and_rule_boxes_are_never_touched(env, value, label):
    """The same answer that FILLS the blank box (the test above) leaves these."""
    row = make_package(env)
    f = row["generated_forms"]["ACORD_125"]
    f["field_state"][OPS_BOX] = value
    f["confidence"][OPS_BOX] = label
    before = copy.deepcopy(f)
    env["model"].answers = {OPS_BOX: OPS}
    status = add_narrative(env)
    after = form(env)
    assert after["field_state"][OPS_BOX] == before["field_state"][OPS_BOX]
    assert after["confidence"][OPS_BOX] == before["confidence"][OPS_BOX]
    assert after["mapped"].get(OPS_BOX) == before["mapped"].get(OPS_BOX)
    assert status["boxes_filled"] == 0 and status["suggestions"] == 0
    assert not env["store"].rows[SID].get(sd.SUGGESTIONS_KEY)


def test_an_identifier_no_document_prints_is_dropped_by_the_generation_guard(env):
    make_package(env)
    box = "NamedInsured_TaxIdentifier_A"
    assert box in gap_fields(env)
    env["model"].answers = {box: "98-7654321"}                     # printed nowhere
    status = add_narrative(env)
    f = form(env)
    assert not f["field_state"].get(box)
    assert status["boxes_filled"] == 0
    assert any(g.get("field") == box for g in f.get("guard_blanks") or [])
    assert status["held_back"] >= 1


# ══ 3. Switch, failure, lock ═════════════════════════════════════════════════

def test_kill_switch_off_means_no_call(env, monkeypatch):
    make_package(env)
    monkeypatch.setenv("NEW_DOCUMENT_AI_FILL", "0")
    env["model"].answers = {OPS_BOX: OPS}
    resp = run(sdr.add_session_documents(
        session_id=SID, files=[UploadFile(file=io.BytesIO(NARR_TEXT.encode()), filename="narrative.txt")],
        progress_token=None, as_supporting=False, doc_type=None, confirm_same_insured=False,
        current_user=USER))
    out = json.loads(resp.body)
    assert out["ai_fill"] == {"state": "off"} and resp.background is None
    assert env["model"].calls == []
    assert sd.FILL_KEY not in env["store"].rows[SID]


def test_the_route_answers_first_then_schedules_the_fill(env):
    make_package(env)
    resp = run(sdr.add_session_documents(
        session_id=SID, files=[UploadFile(file=io.BytesIO(NARR_TEXT.encode()), filename="narrative.txt")],
        progress_token=None, as_supporting=False, doc_type=None, confirm_same_insured=False,
        current_user=USER))
    out = json.loads(resp.body)
    assert out["after_forms"] is True
    assert out["ai_fill"]["state"] == "running" and "run_id" not in out["ai_fill"]
    assert out["ai_fill"]["documents"] == ["narrative.txt"]
    assert out["new_on_review"] is not None and set(out["review_counts"]) == {
        "hard_stops", "warnings", "data_consistency"}
    assert resp.background is not None and resp.background.func is sd.launch_new_document_fill
    assert env["model"].calls == []                               # not before the answer
    row = env["store"].rows[SID]
    assert gs.document_fill_running(row)
    assert gs.documents_locked_reason(row) == gs.DOCUMENT_FILL_LOCKED
    # A second add, a document change and an offered form are refused meanwhile.
    with pytest.raises(HTTPException) as ex:
        run(sdr.add_session_documents(
            session_id=SID, files=[UploadFile(file=io.BytesIO(b"x"), filename="x.txt")],
            progress_token=None, as_supporting=False, doc_type=None, confirm_same_insured=False,
            current_user=USER))
    assert ex.value.status_code == 409 and ex.value.detail == gs.DOCUMENT_FILL_LOCKED
    with pytest.raises(HTTPException) as ex2:
        run(sdr.reclassify_after_forms(type("R", (), {"session_id": SID, "doc_id": "d-dec",
                                                      "action": "exclude", "new_doc_type": None})(),
                                       row, USER))
    assert ex2.value.status_code == 409
    with pytest.raises(HTTPException) as ex3:
        run(sdr.add_offered_session_form(SID, sdr.AddOfferedFormRequest(form_id="ACORD_126"), USER))
    assert ex3.value.status_code == 409
    # The status endpoint while it runs: no review counts yet.
    st = json.loads(run(sdr.document_fill_status_route(SID, None, USER)).body)
    assert st["ai_fill"]["state"] == "running" and "new_on_review" not in st


def test_a_silent_run_is_interrupted_and_no_longer_locks():
    old = "2020-01-01T00:00:00+00:00"
    row = {"generated_forms": {"A": {}},
           gs.DOCUMENT_FILL_KEY: {"state": "running", "started_at": old},
           gs.DOCUMENT_FILL_BEAT_KEY: old}
    assert gs.document_fill_status(row)["state"] == gs.DOCUMENT_FILL_INTERRUPTED
    assert not gs.document_fill_running(row) and gs.documents_locked_reason(row) is None
    assert gs.document_fill_status({}) is None


def test_a_failure_leaves_the_forms_as_the_door_left_them(env, monkeypatch):
    make_package(env)
    env["model"].answers = {OPS_BOX: OPS}
    result = run(sd.add_documents(SID, [NARR()], user_id="u1", purge_dec_index=True))
    door_forms = copy.deepcopy(env["store"].rows[SID]["generated_forms"])

    def _boom(*_a, **_k):
        raise RuntimeError("stamping failed")
    monkeypatch.setattr(sd, "_stamp_with_answers", _boom)
    status = run(sd.start_new_document_fill(SID, result["documents_added"], "u1"))
    out = run(sd.run_new_document_fill(SID, status["doc_ids"], "u1", run_id=status["run_id"]))
    assert out["state"] == sd.FILL_FAILED and out["message"] == sd.FILL_FAILED_TEXT
    assert env["store"].rows[SID]["generated_forms"] == door_forms
    assert env["store"].rows[SID][sd.FILL_KEY]["state"] == sd.FILL_FAILED
    assert not gs.document_fill_running(env["store"].rows[SID])


def test_a_newer_run_is_never_overwritten_by_an_older_one(env):
    make_package(env)
    env["store"].rows[SID][sd.FILL_KEY] = {"run_id": "newer", "state": "running"}
    out = run(sd.run_new_document_fill(SID, ["d-narr"], "u1", run_id="older"))
    assert out["run_id"] == "newer" and env["model"].calls == []


# ══ 4. Applying: re-checked against the row as it stands ════════════════════

def _form(**boxes):
    state = {k: v[0] for k, v in boxes.items()}
    return {"field_state": dict(state), "mapped": dict(state),
            "confidence": {k: v[1] for k, v in boxes.items() if v[1]}, "client_filled_fields": []}


def test_a_box_typed_while_the_ai_read_wins():
    snap = {"F": _form(A=("", None), B=("old", "ai_verified"))}
    plans = {"F": {"fills": {"A": {"value": "new", "label": "ai_verified"}},
                   "suggestions": [{"form_id": "F", "field": "B", "current": "old", "suggested": "x"}],
                   "held_back": []}}
    now = copy.deepcopy(snap)
    now["F"]["field_state"]["A"] = "typed"
    now["F"]["confidence"]["A"] = "producer"
    now["F"]["field_state"]["B"] = "retyped"
    now["F"]["confidence"]["B"] = "producer"
    out = sd.apply_form_fills(now, snap, plans)
    assert out["filled"] == {} and out["suggestions"] == []
    assert now["F"]["field_state"]["A"] == "typed"


def test_a_fill_makes_a_signed_form_stale():
    from services.signature_boxes import APPLICANT_SIGNATURE_KEY, form_fingerprint
    f = _form(A=("", None), B=("kept", "filled"))
    f[APPLICANT_SIGNATURE_KEY] = {"fingerprint": form_fingerprint(f["field_state"], None)}
    snap = {"F": copy.deepcopy(f)}
    now = {"F": f}
    out = sd.apply_form_fills(now, snap, {"F": {"fills": {"A": {"value": "v", "label": "ai_verified"}},
                                                "suggestions": [], "held_back": []}})
    assert out["filled"] == {"F": ["A"]}
    assert [s["form_id"] for s in out["stale_signatures"]] == ["F"]


def test_plan_moves_only_what_the_answers_moved():
    stored = _form(A=("", None), B=("old", "ai_verified"), C=("x", "filled"), D=("p", "producer"))
    new = {"A": "a1", "B": "b1", "C": "c1", "D": "d1", "E": "same"}
    conf = {k: "ai_verified" for k in new}
    base = {"E": "same"}                                   # E did not move
    plan = sd.plan_form_fill("F", stored, new, conf, base, documents=["n.pdf"])
    assert set(plan["fills"]) == {"A"}                     # C is a rule's, D a person's
    assert [s["field"] for s in plan["suggestions"]] == ["B"]
    # a value only a RULE gives (deterministic label) is never the AI's to place
    plan2 = sd.plan_form_fill("F", stored, {"A": "a1"}, {"A": "filled"}, {})
    assert plan2["fills"] == {}


def test_box_owner_reads_every_shape():
    f = _form(A=("", None), B=("v", "ai_verified"), C=("v", "filled"), D=("v", "client_arq"))
    f["field_state"]["E"] = "typed"                       # edited, never stamped
    f["confidence"]["E"] = "low_confidence"
    assert [sd.box_owner(f, k) for k in "ABCDE"] == ["blank", "ai", "rule", "person", "person"]
    assert sd.box_owner(None, "A") == "blank"
    f["client_filled_fields"] = ["A"]
    assert sd.box_owner(f, "A") == "person"


# ══ 5. What is NEW on the review page ════════════════════════════════════════

def test_review_counts_and_the_difference():
    page = {"grouped_issues": {"counts": {"hard_stops": 2, "warnings": 5}},
            "underwriting_consistency": {"fields": [{"status": "conflict"}, {"status": "confirmed"},
                                                    {"status": "conflict"}]}}
    now = sd.review_counts(page)
    assert now == {"hard_stops": 2, "warnings": 5, "data_consistency": 2}
    assert sd.review_counts({"hard_stops": ["a"], "soft_stops": ["b", "c"]}) == {
        "hard_stops": 1, "warnings": 2, "data_consistency": 0}
    before = {"hard_stops": 2, "warnings": 6, "data_consistency": 0}
    assert sd.new_on_review(before, now) == {"hard_stops": 0, "warnings": 0, "data_consistency": 2,
                                             "total": 2}
    assert sd.new_on_review(None, now) is None


def test_the_status_endpoint_reports_new_items_once_done(env, monkeypatch):
    make_package(env)
    env["model"].answers = {OPS_BOX: OPS}
    add_narrative(env)

    async def _page(_sid, _user):
        return {"grouped_issues": {"counts": {"hard_stops": 1, "warnings": 2}},
                "underwriting_consistency": {"fields": [{"status": "conflict"}]}}
    monkeypatch.setattr(sdr, "_package_page", _page)
    st = json.loads(run(sdr.document_fill_status_route(SID, None, USER)).body)
    assert st["ai_fill"]["state"] == "done" and st["ai_fill"]["boxes_filled"] == 1
    assert st["new_on_review"] == {"hard_stops": 1, "warnings": 2, "data_consistency": 1, "total": 4}
    # one form's suggestions only, no review counts
    st1 = json.loads(run(sdr.document_fill_status_route(SID, "ACORD_125", USER)).body)
    assert st1["suggestions"] == [] and "new_on_review" not in st1


# ══ 6. The screens ═══════════════════════════════════════════════════════════

_EM = ("—", "–")


@pytest.mark.parametrize("rel", [
    "components/form/review/AddDocumentsPanel.jsx", "components/form/NeedsAttentionPanel.jsx",
    "utils/addDocuments.js",
])
def test_no_em_dashes_in_the_new_copy(rel):
    assert not any(d in (FRONTEND / rel).read_text(encoding="utf-8") for d in _EM), rel


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node is not installed")
def test_the_result_box_words_in_node(tmp_path):
    import subprocess
    lib = (FRONTEND / "utils" / "addDocuments.js").as_uri()
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as A from {json.dumps(lib)};\n"
        "const res = {after_forms: true, documents_added: [{filename: 'narrative.pdf'}],\n"
        "             boxes_by_form: {ACORD_125: 12, ACORD_126: 0}, forms_updated: ['ACORD_125'], boxes_updated: 12};\n"
        "const done = {state: 'done', documents: ['narrative.pdf'], boxes_filled: 3, suggestions: 2,\n"
        "              filled_by_form: {ACORD_125: 1, ACORD_131__excess: 2}};\n"
        "const out = {\n"
        " running: [...A.addResultLines(res, {state: 'running', documents: ['narrative.pdf']}),\n"
        "           ...A.fillStatusLines({state: 'running', documents: ['narrative.pdf']})],\n"
        " done: [...A.addResultLines(res, done), ...A.fillStatusLines(done)],\n"
        " nothing: A.addResultLines({after_forms: true, documents_added: [{filename: 'a.pdf'}]}, null),\n"
        " failed: A.fillStatusLines({state: 'failed', documents: ['a.pdf'], message: 'm'}),\n"
        " interrupted: A.fillStatusLines({state: 'interrupted', documents: ['a.pdf']}),\n"
        " off: A.fillStatusLines({state: 'off'}),\n"
        " review: A.newOnReviewText({hard_stops: 1, warnings: 2, data_consistency: 1}),\n"
        " none: A.newOnReviewText({hard_stops: 0, warnings: 0, data_consistency: 0}),\n"
        " unknown: A.newOnReviewText(null),\n"
        " first: [A.firstNewSection({warnings: 1, data_consistency: 1}), A.firstNewSection({data_consistency: 2}),\n"
        "         A.firstNewSection({hard_stops: 0})],\n"
        " open: A.reviewOpenItems({groupedIssues: {hard_stops: [{count: 2, items: [{issue_id: 'h1'}, {issue_id: 'h2'}]}],\n"
        "         warnings: {a: [{count: 1, items: [{issue_id: 'w1'}]}], b: []}},\n"
        "         isHandled: (it) => it.issue_id === 'h1' || it.issue_id === 'h2',\n"
        "         consistencyFields: [{status: 'conflict'}, {status: 'confirmed'}]}),\n"
        " bare: A.reviewOpenItems({hardStops: ['x'], softStops: [], consistencyFields: []}),\n"
        " empty: A.reviewOpenItems(),\n"
        " note: A.AFTER_FORMS_ADD_NOTE,\n"
        "};\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    o = json.loads(proc.stdout)
    assert o["running"][0]["text"] == "Added narrative.pdf. Forms updated: ACORD 125 (12 boxes)."
    assert o["running"][-1] == {"kind": "info", "text": "Reading narrative.pdf into your forms..."}
    assert o["done"][0]["text"] == ("Added narrative.pdf. Forms updated: ACORD 125 (13 boxes), "
                                    "ACORD 131 (Excess) (2 boxes).")
    assert o["done"][1]["text"] == ("Read narrative.pdf into your forms: the AI filled 3 boxes, "
                                    "2 values to review where it differs from the form.")
    assert o["nothing"][0]["text"] == "Added a.pdf. No form boxes changed yet."
    assert o["failed"] == [{"kind": "warn", "text": "m"}]
    assert o["interrupted"][0]["kind"] == "warn" and "did not finish" in o["interrupted"][0]["text"]
    assert o["off"] == []
    assert o["review"] == "New on the review page: 1 hard stop, 2 warnings, 1 Data Consistency item."
    assert o["none"] == "No new issues on the review page." and o["unknown"] == ""
    assert o["first"] == ["warnings", "consistency", None]
    assert o["open"] == {"hardStops": 0, "warnings": 1, "dataConsistency": 1, "total": 2, "section": "warnings"}
    assert o["bare"]["section"] == "hardstops" and o["bare"]["total"] == 1
    assert o["empty"]["section"] == "overview" and o["empty"]["total"] == 0
    assert o["note"] == ("Your forms will be updated with this document. New warnings may appear on the "
                         "review page.")


def test_back_to_review_sits_between_send_to_client_and_more_actions():
    modal = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    send = modal.index(">Send to Client{openArqRequests")
    back = modal.index('data-testid="back-to-review"')
    more = modal.index(">More Actions</span>")
    assert send < back < more
    assert "await saveViewerEdits()" in modal[modal.index("const goBackToReview"):][:900]
