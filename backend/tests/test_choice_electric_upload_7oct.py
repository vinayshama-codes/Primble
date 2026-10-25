"""Choice Electric #25 (Brent, 5 Oct 2026): "Unable to upload a narrative or
additional supporting docs after form generation."

Built 7 Oct 2026 - `POST /api/session/{id}/documents` adds documents to an
EXISTING package, before or after forms, through ONE door
(`services/session_documents.remerge_package`), which reclassify / exclude /
supporting-only now also go through once forms exist. What these pin:

  * only the NEW file is read (OCR + the extraction LLM call); every stored
    document is re-merged from its stored facts - no LLM call for an old one;
  * after forms, exactly the boxes whose ENGINE value the change moves are
    re-stamped (checked against a from-scratch regeneration on the same
    documents); a box a person typed and a producer-saved table survive;
    moved boxes carry the engine's label, never "producer";
  * the package is re-scored and its cards synced once, in one write with the
    forms (never new facts beside old forms);
  * excluding a document after forms retracts the values only it stated;
  * a different insured is refused after forms (409, nothing stored) unless
    confirmed; before forms it goes to the existing integrity review;
  * a newly evidenced line's form is OFFERED, never added;
  * the 409 while a run is live, the owner check, validation parity with the
    upload route (one intake door), the documents lock text.

OCR, extraction and every database write are stubbed; the merge, the stops,
the stamping engine and the restamp are the real code.
"""
from __future__ import annotations

import asyncio
import copy
import io
import json
import shutil
import subprocess
from datetime import datetime, timezone
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
import services.session_documents as sd
import services.upload_intake as ui
import services.yes_no_lexicon as ynl
from repositories.session_repository import resolve_facts_write

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
USER = {"id": "u1", "payment_status": "ok"}
# The real post-generation re-score, captured before any fixture stubs it.
_REAL_RECALC = aq.recalculate_session_scores

# ── The documents ────────────────────────────────────────────────────────────

DEC_TEXT = (
    "COMMERCIAL GENERAL LIABILITY DECLARATIONS\nNAMED INSURED: Bluebird Electric LLC\n"
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
    "UNDERWRITING NARRATIVE\nBluebird Electric LLC is a commercial electrical contractor founded in 2009.\n"
    "Operations: commercial electrical installation, service and repair.\n"
    "The company employs 42 full-time employees. Our safety program and management experience are strong.\n"
)
NARR_FACTS = {
    "applicant_name": "Bluebird Electric LLC",
    "operations_description": "Commercial electrical installation, service and repair",
    "num_employees": "42",
    "business_start_date": "2009",
}
WC_TEXT = (
    "WORKERS COMPENSATION AND EMPLOYERS LIABILITY POLICY INFORMATION PAGE DECLARATIONS\n"
    "NAMED INSURED: Bluebird Electric LLC\nPOLICY NUMBER: WC-778812 POLICY PERIOD 01/01/2026 TO 01/01/2027\n"
    "INSURER: Acme Casualty Company\nEMPLOYERS LIABILITY $1,000,000 EACH ACCIDENT\n"
    "CLASS 5190 ELECTRICAL WIRING PAYROLL $1,200,000\nESTIMATED ANNUAL PREMIUM $18,200\n"
)
WC_FACTS = {
    "applicant_name": "Bluebird Electric LLC",
    "coverage_lines": [{"line": "Workers Compensation and Employers Liability", "policy_number": "WC-778812",
                        "carrier": "Acme Casualty Company", "premium": "$18,200",
                        "effective_date": "01/01/2026", "expiration_date": "01/01/2027"}],
    "wc_class_codes": [{"code": "5190", "description": "Electrical wiring", "payroll": "$1,200,000",
                        "state": "CO"}],
}
OTHER_TEXT = (
    "COMMERCIAL AUTO DECLARATIONS\nNAMED INSURED: Zebra Logistics Inc\nFEIN 11-2233445\n"
    "POLICY NUMBER: CA-9 POLICY PERIOD 03/01/2026 TO 03/01/2027\n"
)
OTHER_FACTS = {"applicant_name": "Zebra Logistics Inc", "fein": "11-2233445"}

# What the stubbed extraction returns, keyed by a marker in the text.
_EXTRACTED = {
    "UNDERWRITING NARRATIVE": (NARR_FACTS, {}),
    "WORKERS COMPENSATION": (WC_FACTS, {"has_workers_comp": True}),
    "Zebra Logistics": (OTHER_FACTS, {"has_auto_coverage": True}),
    "COMMERCIAL GENERAL LIABILITY": (DEC_FACTS, {"has_general_liability": True}),
}


def _doc(doc_id, filename, doc_type, text, facts, flags=None, **extra):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type, "text": text,
            "facts": copy.deepcopy(facts), "flags": dict(flags or {}),
            "classification": {"doc_type": doc_type, "source": "content", "confidence": "high"},
            "low_confidence_tokens": [], "manual_confirmation_required": [], **extra}


def DEC():
    return _doc("d-dec", "gl_dec.pdf", "dec_page", DEC_TEXT, DEC_FACTS, {"has_general_liability": True})


def NARR():
    return _doc("d-narr", "narrative.txt", "narrative", NARR_TEXT, NARR_FACTS)


def WC():
    return _doc("d-wc", "wc_dec.pdf", "dec_page", WC_TEXT, WC_FACTS, {"has_workers_comp": True})


def OTHER():
    return _doc("d-oth", "zebra_auto.pdf", "dec_page", OTHER_TEXT, OTHER_FACTS, {"has_auto_coverage": True})


# ── The store and the stubs ──────────────────────────────────────────────────

class Store:
    """An in-memory processing_sessions row with upd_processing_session's own
    semantics: generated_forms merged per form id, facts written additively
    (the real `resolve_facts_write`), every other key replaced, then deletes."""

    def __init__(self):
        self.rows: dict = {}
        self.writes: list = []

    async def get(self, sid, include_pdf=False):
        if sid not in self.rows:
            raise HTTPException(404, f"Processing session {sid} not found")
        return copy.deepcopy(self.rows[sid])

    async def upd(self, sid, payload, delete_facts=None, **_kw):
        self.writes.append({"sid": sid, "keys": sorted(payload), "delete": list(delete_facts or [])})
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


class Calls(dict):
    def add(self, name, *args, **kw):
        self.setdefault(name, []).append((args, kw))


@pytest.fixture
def env(monkeypatch, tmp_path):
    store, calls = Store(), Calls()

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

    # The umbrella-date probe must never run here (it reads EVERY document).
    import services.pdf_service as ps

    async def _probe(*_a, **_k):
        raise AssertionError("the whole-document umbrella probe ran on a re-merge")
    monkeypatch.setattr(ps, "_fetch_umbrella_period", _probe)

    # OCR + extraction of NEW files, recorded.
    async def _ocr(path):
        calls.add("ocr", path)
        return Path(path).read_text(encoding="utf-8"), []

    async def _extract(text, doc_type, low_confidence_tokens=None):
        calls.add("extract", text, doc_type)
        for marker, (facts, flags) in _EXTRACTED.items():
            if marker in text:
                return {"facts": copy.deepcopy(facts), "flags": dict(flags)}
        return {"facts": {}, "flags": {}}
    monkeypatch.setattr(ep, "extract_text", _ocr)
    monkeypatch.setattr(ep, "extract_facts_long", _extract)

    # Route plumbing: limits, the heavy slot, the queue.
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
    monkeypatch.setattr(fr, "check_upload_rate_limit", _none)
    monkeypatch.setattr(cc, "try_acquire_heavy", _acquire)
    monkeypatch.setattr(cc, "release_heavy", _none)
    monkeypatch.setattr(fr, "try_acquire_heavy", _acquire)
    monkeypatch.setattr(fr, "release_heavy", _none)
    monkeypatch.setattr(jq, "get_job_queue", lambda: queue)
    monkeypatch.setattr(fr, "get_job_queue", lambda: queue)
    monkeypatch.setattr(ui, "UPLOAD_DIR", str(tmp_path))
    return {"store": store, "calls": calls, "queue": queue, "tmp": tmp_path}


def run(coro):
    return asyncio.run(coro)


# ── Building a package ───────────────────────────────────────────────────────

def _schema(fid):
    with open(BACKEND / "forms_schemas" / f"{fid}_schema.json", encoding="utf-8") as fh:
        return json.load(fh)


def _stamp(fid, view):
    """A form as generation's deterministic engine prints it from `view` -
    through the form's own facts view (`form_instances.facts_for_form`), as
    `form_service.process_single_form` stamps it."""
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


def make_package(env, sid, docs, forms=(), *, purge=True, user="u1"):
    """A session built by the real pipeline, with `forms` stamped by the real
    engine from what generation stamps from - then the production purge."""
    store = env["store"]
    store.rows[sid] = {"user_id": user, "docs": [], "facts": {}, "flags": {}}
    run(ep._finalize_pipeline(copy.deepcopy(docs), user, session_id=sid))
    row = store.rows[sid]
    if forms:
        view = sd._engine_view(row["facts"], row["flags"], list(forms))
        row["generated_forms"] = {f: _stamp(f, view) for f in forms}
        row["selected_form_ids"] = list(forms)
        if purge:
            row["facts"].pop("dec_page_entries", None)
    return row


def regeneration(env, docs, forms):
    """What a from-scratch package of `docs` prints on `forms`."""
    row = make_package(env, "regen", docs)
    view = sd._engine_view(row["facts"], row["flags"], list(forms))
    return {f: _stamp(f, view)["field_state"] for f in forms}


def changed(a: dict, b: dict) -> set:
    return {k for k in set(a) | set(b) if (a.get(k) or "") != (b.get(k) or "")}


def upload(name, text):
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=name)


def add_via_route(sid, files, *, as_supporting=False, doc_type=None, confirm=False, user=USER):
    return run(sdr.add_session_documents(
        session_id=sid, files=files, progress_token=None, as_supporting=as_supporting,
        doc_type=doc_type, confirm_same_insured=confirm, current_user=user))


def body(resp):
    return json.loads(resp.body)


# ══ 1. The per-document door ═════════════════════════════════════════════════

def test_the_upload_loop_and_an_added_document_run_one_door(env, tmp_path):
    p = tmp_path / "abc_narrative.txt"
    p.write_text(NARR_TEXT, encoding="utf-8")
    doc = run(ep.extract_document(str(p), "narrative.txt", "u1"))
    assert doc["doc_type"] == "narrative" and doc["doc_type_overridden"] is False
    assert doc["facts"]["num_employees"] == "42"
    assert {"doc_id", "filename", "path", "classification", "uploaded_at", "uploaded_by", "text",
            "facts", "flags", "low_confidence_tokens", "manual_confirmation_required",
            "truncation_warning"} <= set(doc)
    # the fresh-upload loop is THIS function (no second copy of the steps)
    import ast
    text = (BACKEND / "services" / "extraction_pipeline.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(text))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_extraction_pipeline")
    src = ast.get_source_segment(text, node)
    assert "extract_document(" in src and "extract_facts_long(" not in src


def test_a_stated_type_is_applied_before_extraction(env, tmp_path):
    p = tmp_path / "x_notes.txt"
    p.write_text(NARR_TEXT, encoding="utf-8")
    doc = run(ep.extract_document(str(p), "notes.txt", "u1", doc_type="loss_run"))
    assert env["calls"]["extract"][-1][0][1] == "loss_run"
    assert doc["doc_type"] == "loss_run" and doc["doc_type_overridden"] is True
    assert doc["doc_type_source"] == "manual" and doc["classification"]["source"] == "manual"
    for none in (None, "", "unknown"):
        d = run(ep.extract_document(str(p), "notes.txt", "u1", doc_type=none))
        assert d["doc_type"] == "narrative" and d["doc_type_overridden"] is False


# ══ 2. The pipeline's two new switches are off for every other caller ════════

def test_finalize_defaults_are_byte_identical(env):
    store = env["store"]
    store.rows["s0"] = {"user_id": "u1", "facts": {}, "flags": {}}
    out = run(ep._finalize_pipeline([DEC()], "u1", session_id="s0"))
    w = store.writes[-1]
    assert "selected_form_ids" in w["keys"] and "generated_forms" in w["keys"]
    assert out["retracted_facts"] == [] and "session_payload" not in out


def test_keep_forms_and_persist_false(env):
    store = env["store"]
    store.rows["s0"] = {"user_id": "u1", "facts": {}, "flags": {},
                        "selected_form_ids": ["ACORD_125"], "generated_forms": {"ACORD_125": {}}}
    n = len(store.writes)
    out = run(ep._finalize_pipeline([DEC()], "u1", session_id="s0", keep_forms=True, persist=False))
    assert len(store.writes) == n                              # nothing written
    assert "selected_form_ids" not in out["session_payload"]
    assert "generated_forms" not in out["session_payload"]
    assert isinstance(out["delete_facts"], list)
    run(ep._finalize_pipeline([DEC()], "u1", session_id="s0", keep_forms=True))
    assert store.rows["s0"]["selected_form_ids"] == ["ACORD_125"]


def test_retractions_only_touch_document_values_nobody_else_holds():
    prior = {"num_employees": "42", "operations_description": {"value": "x", "source": "ai"},
             "fein": {"value": "84-1", "source": "producer", "confidence": "producer"},
             "_private": "z", "applicant_name": "Bluebird"}
    merged = {"applicant_name": "Bluebird"}
    keys = ["num_employees", "operations_description", "fein", "_private", "applicant_name", "absent"]
    assert ep._document_retractions(keys, merged, prior) == ["num_employees", "operations_description"]
    assert ep._document_retractions([], merged, prior) == []
    assert ep._document_retractions(keys, merged, {}) == []


# ══ 3. Adding a document AFTER forms ═════════════════════════════════════════

FORMS = ("ACORD_125",)


def test_adding_a_narrative_after_forms_moves_exactly_its_boxes(env):
    row = make_package(env, "s1", [DEC()], FORMS)
    before = copy.deepcopy(row["generated_forms"]["ACORD_125"]["field_state"])
    expected = changed(before, regeneration(env, [DEC(), NARR()], FORMS)["ACORD_125"])
    assert expected, "the narrative must move something on the 125"
    out = run(sd.add_documents("s1", [NARR()], user_id="u1"))
    after_form = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]
    assert changed(before, after_form["field_state"]) == expected
    door = out["door"]
    assert door["forms_updated"] == ["ACORD_125"] and door["boxes_updated"] == len(expected)
    # the engine's labels, never the producer's
    assert all(after_form["confidence"].get(b) != "producer" for b in expected)
    # the forms' order and the purge survive
    assert env["store"].rows["s1"]["selected_form_ids"] == ["ACORD_125"]
    assert "dec_page_entries" not in env["store"].rows["s1"]["facts"]
    assert [d["doc_id"] for d in env["store"].rows["s1"]["docs"]] == ["d-dec", "d-narr"]


def test_a_person_typed_box_survives_and_an_ai_guess_yields(env):
    row = make_package(env, "s1", [DEC()], FORMS)
    regen = regeneration(env, [DEC(), NARR()], FORMS)["ACORD_125"]
    moving = sorted(changed(row["generated_forms"]["ACORD_125"]["field_state"], regen))
    person, ai = moving[0], (moving[1] if len(moving) > 1 else None)
    form = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]
    form["field_state"][person] = "TYPED BY BRENT"
    form["confidence"][person] = "producer"
    run(sd.add_documents("s1", [NARR()], user_id="u1"))
    after = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]
    assert after["field_state"][person] == "TYPED BY BRENT"
    assert after["confidence"][person] == "producer"
    if ai:
        assert after["field_state"].get(ai, "") == regen.get(ai, "")


def test_a_producer_saved_table_survives_the_re_merge(env):
    from services import schedule_capture as sc
    row = make_package(env, "s1", [DEC()], ())
    typed = [{"year": "2021", "make": "Ford", "model": "F-150", "vin": "1FTFW1ET5DFC10312"}]
    facts = env["store"].rows["s1"]["facts"]
    facts["auto_vin_schedule"] = copy.deepcopy(typed)
    sc.mark_human_rows(facts, "auto_vin_schedule", "producer")
    view = sd._engine_view(facts, row["flags"], ["ACORD_127"])
    env["store"].rows["s1"]["generated_forms"] = {"ACORD_127": _stamp("ACORD_127", view)}
    env["store"].rows["s1"]["selected_form_ids"] = ["ACORD_127"]
    before = copy.deepcopy(env["store"].rows["s1"]["generated_forms"]["ACORD_127"]["field_state"])
    assert before.get("Vehicle_VINIdentifier_A") == "1FTFW1ET5DFC10312"
    other_fleet = _doc("d-fleet", "fleet.pdf", "dec_page", "BUSINESS AUTO DECLARATIONS Bluebird Electric LLC",
                       {"applicant_name": "Bluebird Electric LLC",
                        "auto_vin_schedule": [{"year": "2018", "make": "Ram", "model": "1500",
                                               "vin": "1C6RR7FT9JS123456"}]},
                       {"has_auto_coverage": True})
    run(sd.add_documents("s1", [other_fleet], user_id="u1"))
    stored = env["store"].rows["s1"]["facts"]["auto_vin_schedule"]
    assert [r.get("vin") for r in stored] == ["1FTFW1ET5DFC10312"]
    after = env["store"].rows["s1"]["generated_forms"]["ACORD_127"]["field_state"]
    assert after.get("Vehicle_VINIdentifier_A") == "1FTFW1ET5DFC10312"
    assert not after.get("Vehicle_VINIdentifier_B")


def test_rescore_cards_qa_and_audit_follow_one_write(env):
    make_package(env, "s1", [DEC()], FORMS)
    store, calls = env["store"], env["calls"]
    n = len(store.writes)
    run(sd.add_documents("s1", [NARR()], user_id="u1"))
    door_writes = store.writes[n:]
    # ONE write carries the re-merged row AND the re-stamped forms
    main = door_writes[0]
    assert {"facts", "docs", "generated_forms", sd.OFFERS_KEY} <= set(main["keys"])
    assert "selected_form_ids" not in main["keys"]
    assert "dec_page_entries" in main["delete"]
    assert calls["recalc"] == [(("s1",), {})]
    assert calls.get("run_and_log_field_qa") and calls.get("run_and_log_field_mapping_check")
    ev = [a for a, _k in calls["log_audit_event"] if a[2] == "forms_updated_from_documents"]
    assert ev and ev[0][3]["forms_updated"] == ["ACORD_125"]


def test_the_real_rescore_runs_on_the_row_the_door_wrote(env, monkeypatch):
    """No stub between the door and the post-generation re-score: the scorers,
    the stops and the card sync all run on what the door stored."""
    monkeypatch.setattr(aq, "recalculate_session_scores", _REAL_RECALC)
    make_package(env, "s1", [DEC()], FORMS)
    store = env["store"]
    store.rows["s1"]["package_sqs"] = {"package_sqs_score": 1}
    out = run(sd.add_documents("s1", [NARR()], user_id="u1"))
    row = store.rows["s1"]
    assert isinstance(row["package_sqs"], dict) and row["package_sqs"].get("package_sqs_score", 1) != 1
    assert row["generated_forms"]["ACORD_125"]["sqs"].get("form_id") in (None, "ACORD_125")
    assert isinstance(row.get("hard_stops"), list) and isinstance(row.get("cross_issues_last"), list)
    assert env["calls"]["sync_recommendation_cards"]
    assert out["door"]["score_after"] is not None


def test_two_changes_at_once_both_land(env):
    """An add still running while an exclude arrives: each change re-reads the
    row once the other is done, so neither drops the other's document."""
    make_package(env, "s1", [DEC(), WC()], FORMS)

    async def both():
        return await asyncio.gather(
            sd.add_documents("s1", [NARR()], user_id="u1"),
            sd.change_document("s1", doc_id="d-wc", action="exclude", user_id="u1"),
        )
    run(both())
    docs = {d["doc_id"]: d for d in env["store"].rows["s1"]["docs"]}
    assert set(docs) == {"d-dec", "d-wc", "d-narr"}
    assert docs["d-wc"].get("excluded") is True
    assert sd._LOCKS == {}                                   # nothing left behind


def test_a_failure_before_the_write_leaves_the_package_untouched(env, monkeypatch):
    make_package(env, "s1", [DEC()], FORMS)
    store = env["store"]
    snapshot = copy.deepcopy(store.rows["s1"])

    def boom(*_a, **_k):
        raise RuntimeError("restamp failed")
    monkeypatch.setattr(sd, "restamp_forms", boom)
    with pytest.raises(RuntimeError):
        run(sd.add_documents("s1", [NARR()], user_id="u1"))
    assert store.rows["s1"] == snapshot


def test_the_generation_index_is_rebuilt_when_purged(env):
    entries = [{"label": "Policy Number", "value": "GL-104455", "section": "GL"}]
    doc = DEC()
    doc["facts"]["dec_page_entries"] = entries
    rebuilt = sd._generation_index({}, [doc])
    assert rebuilt and any(e.get("value") == "GL-104455" for e in rebuilt)
    assert sd._generation_index({"dec_page_entries": entries}, [doc]) is None
    assert sd._generation_index({}, []) is None


def test_purge_off_keeps_the_index(env):
    make_package(env, "s1", [DEC()], FORMS)
    store = env["store"]
    n = len(store.writes)
    run(sd.add_documents("s1", [NARR()], user_id="u1",
                         purge_dec_index=False))
    assert "dec_page_entries" not in store.writes[n]["delete"]


def test_a_signed_form_the_change_moves_is_reported_stale(env):
    from services.signature_boxes import form_fingerprint
    make_package(env, "s1", [DEC()], FORMS)
    form = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]
    form["applicant_signature"] = {"fingerprint": form_fingerprint(form["field_state"], form["schema"]),
                                   "request_id": "r1", "signed_date": "10/01/2026"}
    out = run(sd.add_documents("s1", [NARR()], user_id="u1"))
    assert [s["form_id"] for s in out["door"]["stale_signatures"]] == ["ACORD_125"]


def test_an_unmoved_signed_form_is_not_stale(env):
    from services.signature_boxes import form_fingerprint
    make_package(env, "s1", [DEC()], ("ACORD_125",))
    form = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]
    form["applicant_signature"] = {"fingerprint": form_fingerprint(form["field_state"], form["schema"]),
                                   "request_id": "r1", "signed_date": "10/01/2026"}
    # a supporting document that states nothing the forms print moves nothing
    manual = _doc("d-man", "safety_manual.pdf", "safety_manual",
                  "EMPLOYEE SAFETY MANUAL\nLockout and tagout procedures for every crew.\n",
                  {}, {}, supporting_only=True)
    out = run(sd.add_documents("s1", [manual], user_id="u1"))
    assert out["door"]["boxes_updated"] == 0 and out["door"]["stale_signatures"] == []


# ══ 4. Offers ════════════════════════════════════════════════════════════════

def test_a_new_line_offers_its_form_and_never_adds_it(env):
    make_package(env, "s1", [DEC()], FORMS)
    out = run(sd.add_documents("s1", [WC()], user_id="u1"))
    offers = out["door"]["form_offers"]
    assert [o["form_id"] for o in offers] == ["ACORD_130"]
    assert offers[0]["line"] == "workers_comp" and offers[0]["line_label"] == "Workers Compensation"
    row = env["store"].rows["s1"]
    assert sorted(row["generated_forms"]) == ["ACORD_125"]            # never auto-added
    assert [o["form_id"] for o in row[sd.OFFERS_KEY]] == ["ACORD_130"]


def test_offer_rules():
    recs = [{"form_id": "ACORD_130", "tier": "required"},
            {"form_id": "ACORD_160", "tier": "optional"},
            {"form_id": "ACORD_101", "tier": "recommended"},
            {"form_id": "ACORD_131__excess", "tier": "required"},
            {"form_id": "ACORD_126", "tier": "required"}]
    lines_before, lines_after = {"general_liab", "umbrella"}, {"general_liab", "umbrella", "workers_comp"}
    got = sd.form_offers(recs, ["ACORD_125", "ACORD_126", "ACORD_131"], ["ACORD_126", "ACORD_131"],
                         lines_before, lines_after)
    ids = [o["form_id"] for o in got]
    # 130: a new line; 131__excess: a new recommendation on an evidenced line;
    # never an optional form, a package form (101), or one already in the package
    assert ids == ["ACORD_130", "ACORD_131__excess"]
    assert got[1]["label"] == "ACORD 131 (Excess)"
    # a prior offer stays while its line stays; goes when the line goes or the form arrives
    prior = [{"form_id": "ACORD_130", "line": "workers_comp"}]
    assert [o["form_id"] for o in sd.form_offers([], ["ACORD_125"], [], lines_after, lines_after, prior)] == ["ACORD_130"]
    assert sd.form_offers([], ["ACORD_125"], [], lines_after, {"general_liab"}, prior) == []
    assert sd.form_offers([], ["ACORD_125", "ACORD_130"], [], lines_after, lines_after, prior) == []


def test_forms_the_documents_stopped_calling_for_are_named():
    rows = sd.forms_without_their_line(
        ["ACORD_125", "ACORD_127", "ACORD_131", "ACORD_131__excess"],
        {"general_liab", "auto", "umbrella"}, {"general_liab", "umbrella"},
        ["ACORD_127", "ACORD_131", "ACORD_131__excess"], ["ACORD_131"])
    assert [(r["form_id"], r["reason"]) for r in rows] == [("ACORD_127", "line"),
                                                           ("ACORD_131__excess", "policy")]
    assert rows[0]["line_label"] == "Commercial Auto"
    assert sd.forms_without_their_line(["ACORD_125"], set(), set()) == []


def test_add_offered_form_route(env, monkeypatch):
    make_package(env, "s1", [DEC()], FORMS)
    env["store"].rows["s1"][sd.OFFERS_KEY] = [{"form_id": "ACORD_130", "line": "workers_comp"}]
    seen = {}

    async def _add(sid, fid, *, enforce_requested=True):
        seen["args"] = (sid, fid, enforce_requested)
        return "ok", {"form": {"form_id": fid}, "selected_form_ids": ["ACORD_125", fid]}
    import services.form_addition as fa
    monkeypatch.setattr(fa, "add_form_to_session", _add)
    with pytest.raises(HTTPException) as ei:
        run(sdr.add_offered_session_form("s1", sdr.AddOfferedFormRequest(form_id="ACORD_160"), USER))
    assert ei.value.status_code == 409 and "not offered" in ei.value.detail
    resp = run(sdr.add_offered_session_form("s1", sdr.AddOfferedFormRequest(form_id="ACORD_130"), USER))
    assert seen["args"] == ("s1", "ACORD_130", False)
    assert body(resp)["added_form"]["form_id"] == "ACORD_130"
    assert env["store"].rows["s1"][sd.OFFERS_KEY] == []
    assert env["calls"]["recalc"]


# ══ 5. Reclassify / exclude / supporting-only AFTER forms ════════════════════

def test_excluding_a_document_after_forms_retracts_its_values(env):
    make_package(env, "s1", [DEC(), NARR()], FORMS)
    before = copy.deepcopy(env["store"].rows["s1"]["generated_forms"]["ACORD_125"]["field_state"])
    regen = regeneration(env, [DEC()], FORMS)["ACORD_125"]
    out = run(sd.change_document("s1", doc_id="d-narr", action="exclude", user_id="u1"))
    facts = env["store"].rows["s1"]["facts"]
    assert "num_employees" not in facts and "operations_description" not in facts
    assert {"num_employees", "operations_description"} <= set(out["door"]["retracted_facts"])
    after = env["store"].rows["s1"]["generated_forms"]["ACORD_125"]["field_state"]
    assert changed(before, after) == changed(before, regen)
    assert [d.get("excluded") for d in env["store"].rows["s1"]["docs"]] == [None, True]
    assert out["reclassified"]["action"] == "exclude"


def test_reclassify_route_after_forms_goes_through_the_door(env, monkeypatch):
    from models.schemas import DocumentReclassifyRequest
    make_package(env, "s1", [DEC(), NARR()], FORMS)

    async def _never(*_a, **_k):
        raise AssertionError("the pre-form re-run ran on a generated package")
    monkeypatch.setattr(fr, "reclassify_document", _never)
    req = DocumentReclassifyRequest(session_id="s1", doc_id="d-narr", action="supporting_only")
    data = body(run(fr.document_reclassify(req, current_user=USER)))
    assert data["success"] and data["after_forms"] is True and data["action"] == "supporting_only"
    assert next(d for d in data["doc_summary"] if d["doc_id"] == "d-narr")["supporting_only"] is True
    assert env["calls"]["log_document_reclassified"]


def test_reclassify_route_before_forms_is_unchanged(env, monkeypatch):
    from models.schemas import DocumentReclassifyRequest
    make_package(env, "s1", [DEC(), NARR()])
    seen = {}
    real = ep.reclassify_document

    async def _spy(*a, **k):
        seen["called"] = True
        return await real(*a, **k)
    monkeypatch.setattr(fr, "reclassify_document", _spy)
    req = DocumentReclassifyRequest(session_id="s1", doc_id="d-narr", action="exclude")
    data = body(run(fr.document_reclassify(req, current_user=USER)))
    assert seen.get("called") and data["success"] and "after_forms" not in data


# ══ 6. Integrity ═════════════════════════════════════════════════════════════

def test_a_different_insured_after_forms_is_refused_then_confirmed(env):
    make_package(env, "s1", [DEC()], FORMS)
    store = env["store"]
    snapshot = copy.deepcopy(store.rows["s1"])
    with pytest.raises(sd.IntegrityReviewRequired) as ei:
        run(sd.add_documents("s1", [OTHER()], user_id="u1"))
    assert "Zebra Logistics Inc" in ei.value.verdict["detected_entities"]
    assert store.rows["s1"] == snapshot                      # nothing stored
    out = run(sd.add_documents("s1", [OTHER()], user_id="u1",
                               confirm_same_insured=True))
    integ = store.rows["s1"]["integrity"]
    assert out["door"]["integrity_override_recorded"] is True
    assert integ["overridden"] and "Zebra Logistics Inc" in integ["override"]["acknowledged_entities"]
    # a later add naming the same two insureds is covered by that override
    plan = sd.integrity_plan(integ, store.rows["s1"]["docs"], confirm_same_insured=False, user_id="u1")
    assert plan["review_needed"] is False and plan["override"] == integ["override"]


def test_a_different_insured_before_forms_goes_to_the_review(env):
    make_package(env, "s1", [DEC()])
    out = run(sd.add_documents("s1", [OTHER()], user_id="u1"))
    row = env["store"].rows["s1"]
    assert out["door"]["integrity_review_required"] is True
    assert row["integrity"]["review_required"] is True and len(row["docs"]) == 2
    assert row["recommendations"] == []                     # paused, exactly as an upload


def test_the_route_refusal_is_a_409_with_the_verdict(env):
    make_package(env, "s1", [DEC()], FORMS)
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("zebra.txt", OTHER_TEXT)])
    assert ei.value.status_code == 409
    d = ei.value.detail
    assert d["error"] == "submission_integrity_review_required" and d["can_confirm"] is True
    assert "Zebra Logistics Inc" in d["message"] and "Nothing was added" in d["message"]
    data = body(add_via_route("s1", [upload("zebra.txt", OTHER_TEXT)], confirm=True))
    assert data["integrity_override_recorded"] is True
    assert env["calls"]["log_integrity_resolution"]


# ══ 7. The route ═════════════════════════════════════════════════════════════

def test_no_llm_call_for_an_old_document(env):
    make_package(env, "s1", [DEC(), WC()], FORMS)
    calls = env["calls"]
    data = body(add_via_route("s1", [upload("narrative.txt", NARR_TEXT)]))
    assert [a[1] for a, _k in calls["extract"]] == ["narrative"]
    assert len(calls["extract"]) == 1 and "UNDERWRITING NARRATIVE" in calls["extract"][0][0][0]
    assert len(calls["ocr"]) == 1
    assert data["success"] and data["after_forms"] is True
    assert [d["filename"] for d in data["documents_added"]] == ["narrative.txt"]
    assert [d["filename"] for d in data["doc_summary"]] == ["gl_dec.pdf", "wc_dec.pdf", "narrative.txt"]
    # the stored documents kept their own facts, untouched
    docs = env["store"].rows["s1"]["docs"]
    assert docs[0]["facts"]["policy_number"] == "GL-104455"
    ev = [a for a, _k in calls["log_audit_event"] if a[2] == "documents_uploaded"]
    assert ev and ev[0][3]["added_to_package"] is True and ev[0][3]["after_forms"] is True
    # temp files are gone
    assert list(env["tmp"].iterdir()) == []


def test_supporting_and_a_stated_type_via_the_route(env):
    make_package(env, "s1", [DEC()])
    data = body(add_via_route("s1", [upload("notes.txt", NARR_TEXT)], as_supporting=True,
                              doc_type="narrative"))
    added = data["documents_added"][0]
    assert added["supporting_only"] is True and added["doc_type"] == "narrative"
    assert added["doc_type_overridden"] is True
    assert data["after_forms"] is False and data["boxes_updated"] == 0
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("notes.txt", NARR_TEXT)], doc_type="bogus")
    assert ei.value.status_code == 400 and ei.value.detail == "Unsupported document type."


def test_the_same_file_twice_is_skipped_before_its_extraction_call(env):
    make_package(env, "s1", [DEC()])
    add_via_route("s1", [upload("narrative.txt", NARR_TEXT)])
    assert len(env["calls"]["extract"]) == 1
    with pytest.raises(HTTPException) as ei:                # the retry: nothing new
        add_via_route("s1", [upload("narrative (1).txt", "  " + NARR_TEXT.replace("\n", "\n\n"))])
    assert ei.value.status_code == 409 and ei.value.detail == "These documents are already in this package."
    assert len(env["calls"]["extract"]) == 1                # no LLM call for the duplicate
    assert len(env["store"].rows["s1"]["docs"]) == 2
    # two identical files in ONE upload: one added, one skipped
    data = body(add_via_route("s1", [upload("wc.txt", WC_TEXT), upload("wc copy.txt", WC_TEXT)]))
    assert [d["filename"] for d in data["documents_added"]] == ["wc.txt"]
    assert data["duplicates_skipped"] == ["wc copy.txt"]
    assert len(env["calls"]["extract"]) == 2


def test_the_door_skips_a_duplicate_that_raced_in(env):
    make_package(env, "s1", [DEC(), NARR()])
    dup = dict(NARR(), doc_id="d-narr-again", filename="narrative again.txt")
    with pytest.raises(sd.AlreadyInPackage) as ei:
        run(sd.add_documents("s1", [dup], user_id="u1"))
    assert ei.value.documents == ["narrative again.txt"]
    out = run(sd.add_documents("s1", [dup, WC()], user_id="u1"))
    assert out["door"]["duplicates_skipped"] == ["narrative again.txt"]
    assert [d["doc_id"] for d in out["documents_added"]] == ["d-wc"]


def test_409_while_a_run_is_live(env, monkeypatch):
    make_package(env, "s1", [DEC()])
    env["store"].rows["s1"]["generation_job_id"] = "j1"
    env["queue"].job = {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}

    async def _never(*_a, **_k):
        raise AssertionError("files were read while a run is live")
    monkeypatch.setattr(ui, "store_uploads", _never)
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("narrative.txt", NARR_TEXT)])
    assert ei.value.status_code == 409 and "being generated" in ei.value.detail
    from models.schemas import DocumentReclassifyRequest
    req = DocumentReclassifyRequest(session_id="s1", doc_id="d-dec", action="exclude")
    with pytest.raises(HTTPException) as ei:
        run(fr.document_reclassify(req, current_user=USER))
    assert ei.value.status_code == 409


def test_a_non_owner_is_refused(env):
    make_package(env, "s1", [DEC()], FORMS, user="someone-else")
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("narrative.txt", NARR_TEXT)])
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei:
        run(sdr.add_offered_session_form("s1", sdr.AddOfferedFormRequest(form_id="ACORD_130"), USER))
    assert ei.value.status_code == 403
    assert "ocr" not in env["calls"]


def test_a_locked_account_cannot_add(env):
    make_package(env, "s1", [DEC()])
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("narrative.txt", NARR_TEXT)],
                      user={"id": "u1", "payment_status": "soft_locked"})
    assert ei.value.status_code == 403


def test_no_readable_text_is_a_400(env):
    make_package(env, "s1", [DEC()])
    with pytest.raises(HTTPException) as ei:
        add_via_route("s1", [upload("empty.txt", "tiny")])
    assert ei.value.status_code == 400 and ei.value.detail == "No readable text found in uploaded files"


class _Pool:
    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()

    async def fetchrow(self, *_a, **_k):
        return None


@pytest.mark.parametrize("case", ["too_many", "oversize", "bad_mime", "bad_type", "bad_zip"])
def test_validation_parity_with_the_upload_route(env, monkeypatch, case):
    make_package(env, "s1", [DEC()])
    monkeypatch.setattr(fr, "get_pool", lambda: _Pool())

    def files():
        if case == "too_many":
            return [upload(f"n{i}.txt", NARR_TEXT) for i in range(ui.MAX_FILES_PER_UPLOAD + 1)]
        if case == "oversize":
            monkeypatch.setattr(ui, "MAX_UPLOAD_SIZE_BYTES", 16)
            return [upload("big.txt", NARR_TEXT)]
        if case == "bad_mime":
            return [upload("fake.pdf", "this is not a pdf")]
        if case == "bad_type":
            return [upload("letter.docx", "word document")]
        return [upload("broken.zip", "PK\x03\x04 not really a zip")]

    with pytest.raises(HTTPException) as up:
        run(fr.upload_declaration(files=files(), progress_token=None, current_user=USER))
    with pytest.raises(HTTPException) as add:
        add_via_route("s1", files())
    assert (up.value.status_code, up.value.detail) == (add.value.status_code, add.value.detail)
    assert add.value.status_code in (400, 413)
    assert list(env["tmp"].iterdir()) == []                 # no temp file left behind


# ══ 8. The lock ══════════════════════════════════════════════════════════════

def test_documents_lock_only_while_a_run_is_live():
    assert gs.documents_locked_reason({}, gs.STATE_RUNNING) == "Forms are being generated - wait for them to finish."
    for state in (gs.STATE_NONE, gs.STATE_DONE, gs.STATE_INTERRUPTED, None):
        assert gs.documents_locked_reason({}, state) is None
    assert gs.documents_locked_reason({"generated_forms": {"A": {}}}, gs.STATE_RUNNING) is None
    # the pre-form actions keep their lock
    assert gs.forms_locked_reason({"generated_forms": {"A": {}}}) == \
        "Forms are generated - make changes in the form editor."


def test_the_frontend_lock_text_is_the_servers():
    pg = (FRONTEND / "utils" / "packageGeneration.js").read_text(encoding="utf-8")
    assert "export function documentsLockedReason(state)" in pg
    assert f'FORMS_RUNNING_TEXT = "{gs.documents_locked_reason({}, gs.STATE_RUNNING)}"' in pg


def _route_body(name: str) -> str:
    """A handler's source read off the file by NAME (never by a loaded code
    object's line numbers, which a concurrent edit of the file shifts)."""
    import ast
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)
    return ast.get_source_segment(src, node)


def test_select_and_integrity_resolve_keep_the_lock():
    for name in ("select_forms_bulk", "submission_integrity_resolve", "underwriting_confirm_value"):
        assert "await _refuse_once_forms_exist(session)" in _route_body(name), name
    body_ = _route_body("document_reclassify")
    assert "await _refuse_once_forms_exist(session)" not in body_
    owner = body_.index('raise HTTPException(403, "Access denied")')
    lock = body_.index("await _refuse_while_generating(session)")
    door = body_.index("return await reclassify_after_forms(req, session, current_user)")
    assert owner < lock < door < body_.index("reclassify_document(")


# ══ 9. The screens ═══════════════════════════════════════════════════════════

_EM = ("—", "–")


@pytest.mark.parametrize("rel", [
    "components/form/review/AddDocumentsPanel.jsx", "components/form/review/DocumentChangeConfirm.jsx",
    "utils/addDocuments.js",
])
def test_no_em_dashes_in_the_new_copy(rel):
    assert not any(d in (FRONTEND / rel).read_text(encoding="utf-8") for d in _EM), rel


def test_both_layouts_offer_add_documents_and_unlock_documents_after_forms():
    rail = (FRONTEND / "components" / "form" / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    modal = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert 'typeof renderAddDocuments === "function" && renderAddDocuments()' in rail
    assert "const docLockText = documentsLockedReason(genState);" in rail
    # 4 since 22 Oct 2026: type, Confirm type, Exclude, Supporting only.
    assert rail.count("disabled={anyReclassBusy || !!docLockText}") == 4
    assert "renderAddDocuments={renderAddDocumentsPanel}" in modal
    assert "{renderAddDocumentsPanel()}" in modal
    assert "const reclassLocked = !!documentsLockedReason(pkgGen.state);" in modal
    head = modal[modal.index("const handleReclassify = async"):]
    head = head[:head.index("try {")]
    assert "if (documentsLockedReason(pkgGen.state)) { setError(documentsLockedReason(pkgGen.state)); return; }" in head
    assert "setDocChange({ docId, action, newType, busyBtn, filename: docName });" in head
    assert "<DocumentChangeConfirm pending={docChange}" in modal


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_result_words_in_node(tmp_path):
    lib = (FRONTEND / "utils" / "addDocuments.js").as_uri()
    pg = (FRONTEND / "utils" / "packageGeneration.js").as_uri()
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as A from {json.dumps(lib)};\nimport * as P from {json.dumps(pg)};\n"
        "const out = {\n"
        " after: A.documentsResultLines({documents_added: [{}, {}], after_forms: true, boxes_updated: 14,\n"
        "        forms_updated: ['ACORD_125', 'ACORD_131__excess'],\n"
        "        stale_signatures: [{form_id: 'ACORD_125'}, {form_id: 'ACORD_131__excess'}],\n"
        "        forms_without_line: [{form_id: 'ACORD_127', line_label: 'Commercial Auto', reason: 'line'},\n"
        "                             {form_id: 'ACORD_131__excess', reason: 'policy'}]}),\n"
        " none: A.documentsResultLines({documents_added: [{}], after_forms: true, boxes_updated: 0, forms_updated: [],\n"
        "        duplicates_skipped: ['a.pdf', 'b.pdf']}),\n"
        " pre: A.documentsResultLines({documents_added: [{}], after_forms: false}),\n"
        " changed: A.documentsResultLines({after_forms: true, boxes_updated: 1, forms_updated: ['ACORD_125']}),\n"
        " empty: A.documentsResultLines(null),\n"
        " offer: A.offerText({form_id: 'ACORD_130', line_label: 'Workers Compensation'}),\n"
        " merged: A.mergedOffers([{form_id: 'A'}], [{form_id: 'A'}, {form_id: 'B'}, null]).map(o => o.form_id),\n"
        " refusal: A.integrityRefusal(409, {detail: {error: 'submission_integrity_review_required', message: 'm',\n"
        "          integrity: {detected_entities: ['Zebra']}, can_confirm: true}}),\n"
        " noRefusal: A.integrityRefusal(409, {detail: 'Forms are being generated - wait for them to finish.'}),\n"
        " lock: ['done', 'running', 'none', 'interrupted'].map(P.documentsLockedReason),\n"
        "};\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    o = json.loads(proc.stdout)
    assert o["after"][0] == {"kind": "done", "text": "2 documents added. 14 boxes updated on 2 forms."}
    assert o["after"][1]["text"] == ("The applicant's signature on ACORD 125 and ACORD 131 (Excess) no longer "
                                    "matches - send for signature again.")
    assert o["after"][2]["text"] == "ACORD 127: no document shows Commercial Auto any more."
    assert o["after"][3]["text"] == "ACORD 131 (Excess): no document shows its policy any more."
    assert o["none"][0]["text"] == "1 document added. No form boxes changed."
    assert o["none"][1] == {"kind": "info", "text": "Already in this package, not added again: a.pdf and b.pdf."}
    assert o["pre"] == [{"kind": "done", "text": "1 document added."}]
    assert o["changed"][0]["text"] == "Document updated. 1 box updated on 1 form."
    assert o["empty"] == []
    assert o["offer"] == "Your documents now show Workers Compensation. ACORD 130 is not in this package."
    assert o["merged"] == ["A", "B"]
    assert o["refusal"] == {"message": "m", "entities": ["Zebra"], "canConfirm": True}
    assert o["noRefusal"] is None
    assert o["lock"] == [None, "Forms are being generated - wait for them to finish.", None, None]
