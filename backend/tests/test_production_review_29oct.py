"""Production-readiness review, 29 Oct 2026 - "is today's work ready for live users
with their own random data?" Each test pins one defect the review found and fixed.

1. The ACORD reader (pdfplumber / pikepdf, CPU-bound: 8-22 s on a flattened 125 or a
   59-page package) ran INLINE inside the async upload - every other request on the
   server froze for that long. It now runs off the event loop.
2. A re-uploaded form's restored PERSON answers (FEIN, revenue, typed narratives) rode
   the document's ACORD record, and the session row stores `docs` as plain JSON - the
   decrypted payload sat in the database in the clear. Sealed at rest now.
3. Our own form with a blanked or mistyped expiration box was never "last term's":
   a 2023 form restored its FEIN and revenue as a person's answers. The record's own
   term fills the gap, and a start with no end ends one term (+ margin) later.
4. `carries_record` said yes to ANY /PrimbleRecord key (an integer, a dictionary): an
   outside PDF carrying one was never sent to Transcriber.
5. The editor's screen-points plan (~6 s CPU) re-ran on every box save with no cache,
   no coalescing and the shared thread pool. Cached by a fingerprint of the row now,
   one run per session at a time, a small server-wide bound.
6. The side panel kept an old plan after a dismiss / reopen: its items summed to
   100 minus the OLD score beside the new headline (103). A changed headline drops it.
Synthetic data only.
"""
import ast
import asyncio
import datetime
import inspect
import json
import os
import shutil
import subprocess
import textwrap

import pikepdf
import pytest

from services.acord_intake import intake, merge_rules, primble_record
from services.pdf_service import fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")
NAME = "Synthco Roofing LLC"


@pytest.fixture(autouse=True)
def _fernet(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _our_125(tmp_path, values, facts, name="ours.pdf"):
    raw = fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), values)
    session = {"facts": dict(facts), "flags": {}, "docs": [],
               "generated_forms": {"ACORD_125": {"mapped": dict(values),
                                                 "confidence": {b: "filled" for b in values}}}}
    p = tmp_path / name
    p.write_bytes(primble_record.attach(raw, session, "ACORD_125"))
    return str(p)


_FACTS = {"applicant_name": {"value": NAME, "source": "acord_form"},
          "fein": {"value": "12-3456789", "source": "producer", "confidence": "producer"},
          "total_revenue": {"value": "$9,999,999", "source": "producer", "confidence": "producer"}}


def _us(d: datetime.date) -> str:
    return d.strftime("%m/%d/%Y")


# ── 1. the reader runs off the event loop ────────────────────────────────────
def test_extract_document_never_runs_the_acord_reader_on_the_event_loop():
    from services import extraction_pipeline
    tree = ast.parse(textwrap.dedent(inspect.getsource(extraction_pipeline.extract_document)))
    to_thread_args = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_thread"):
            for a in node.args:
                to_thread_args.add(id(a))
    blocking = {"read_for_document", "carries_record"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in blocking:
            offenders.append(node.func.attr)          # called directly = on the loop
    assert not offenders, f"called inline in async extract_document: {offenders}"
    named = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in blocking]
    assert named and all(id(n) in to_thread_args for n in named)


# ── 2. the restored payload is sealed at rest ────────────────────────────────
def test_restored_person_answers_are_never_stored_in_the_clear(tmp_path):
    today = datetime.date.today()
    vals = {"NamedInsured_FullName_A": NAME, "Policy_EffectiveDate_A": _us(today),
            "Policy_ExpirationDate_A": _us(today + datetime.timedelta(days=365))}
    r = intake.read_for_document(_our_125(tmp_path, vals, _FACTS), "")
    sealed = r["record"]["restored"]
    assert isinstance(sealed, str) and sealed.startswith("enc:")
    assert "12-3456789" not in json.dumps(r["record"]) and "9,999,999" not in json.dumps(r["record"])
    opened = primble_record.restored_of(r["record"])
    assert opened["answers"]["fein"]["value"] == "12-3456789"
    # the merge reads it through the one door
    doc = {"acord": r["record"], "facts": r["facts"], "doc_type": "application"}
    merged = {"applicant_name": {"value": NAME, "source": "acord_form"}}
    moved = merge_rules.apply_restored_answers(merged, [doc])
    assert "fein" in moved and merged["fein"]["value"] == "12-3456789"


def test_a_legacy_plain_restored_payload_still_reads():
    legacy = {"acord": {"restored": {"answers": {"fein": {"value": "1"}}}}}
    assert primble_record.restored_of(legacy)["answers"]["fein"]["value"] == "1"
    assert primble_record.restored_of({"acord": {"restored": "enc:garbage"}}) == {}
    assert primble_record.restored_of(None) == {} and primble_record.restored_of({}) == {}


# ── 3. an own form with no readable end is judged by its term ────────────────
@pytest.mark.parametrize("label,vals", [
    ("start only", {"Policy_EffectiveDate_A": "01/01/2023"}),
    ("impossible end", {"Policy_EffectiveDate_A": "01/01/2023", "Policy_ExpirationDate_A": "02/30/2024"}),
])
def test_an_old_own_form_with_no_readable_end_restores_nothing(tmp_path, label, vals):
    r = intake.read_for_document(_our_125(tmp_path, dict(vals, NamedInsured_FullName_A=NAME), _FACTS), "")
    assert r["record"].get("own_form") is True
    assert r["record"]["prior_application"] is True, label
    assert not primble_record.restored_of(r["record"]).get("answers"), label


def test_the_records_own_term_decides_when_the_date_boxes_are_blank(tmp_path):
    facts = dict(_FACTS, effective_date={"value": "01/01/2023", "source": "acord_form"},
                 expiration_date={"value": "01/01/2024", "source": "acord_form"})
    r = intake.read_for_document(_our_125(tmp_path, {"NamedInsured_FullName_A": NAME}, facts), "")
    assert r["record"]["prior_application"] is True
    assert not primble_record.restored_of(r["record"]).get("answers")


def test_a_current_own_form_with_no_end_box_still_restores(tmp_path):
    start = datetime.date.today() - datetime.timedelta(days=100)
    r = intake.read_for_document(_our_125(tmp_path, {"NamedInsured_FullName_A": NAME,
                                                     "Policy_EffectiveDate_A": _us(start)}, _FACTS), "")
    assert r["record"]["prior_application"] is False
    assert primble_record.restored_of(r["record"])["answers"]["fein"]["value"] == "12-3456789"


def test_prior_rule_for_own_records_edges():
    today = datetime.date(2026, 10, 29)
    f = lambda **k: {"facts": {kk: {"value": v} for kk, v in k.items()}}     # noqa: E731
    assert merge_rules.is_prior_application(f(effective_date="2025-01-01"), today, own_record=True)
    assert not merge_rules.is_prior_application(f(effective_date="2026-01-01"), today, own_record=True)
    assert not merge_rules.is_prior_application(f(), today, own_record=True)          # nothing to judge
    assert merge_rules.is_prior_application(f(expiration_date="2026-10-29"), today, own_record=True)
    assert not merge_rules.is_prior_application(f(effective_date="garbage"), today, own_record=True)


# ── 4. carries_record wants the shape we write ───────────────────────────────
@pytest.mark.parametrize("value,expect", [
    (pikepdf.String("enc:gAAAAAB-synthetic"), True),
    (12345, False),
    (pikepdf.Dictionary(), False),
    (pikepdf.String("sealed with another server's key"), True),
    (pikepdf.String(""), False),
])
def test_carries_record_needs_our_sealed_shape(tmp_path, value, expect):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo[primble_record.KEY] = value
    p = tmp_path / "x.pdf"
    pdf.save(p)
    assert primble_record.carries_record(str(p)) is expect


# ── 5. the screen-points plan is cached and coalesced ────────────────────────
def test_screen_points_runs_once_per_state_and_once_at_a_time(monkeypatch):
    from routes import form_routes
    calls = []

    def fake(row, sid, uid, credits):
        calls.append(sid)
        import time
        time.sleep(0.05)
        return {"package_sqs": {"package_sqs_score": 80}, "key_details": None, "grouped_issues": None}

    monkeypatch.setattr(form_routes, "screen_points_after_forms", fake)
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_CACHE", {})
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_LOCKS", {})
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_SEM", None)
    row = {"facts": {"applicant_name": {"value": NAME}}, "package_sqs": {"package_sqs_score": 80}}

    async def go():
        # three saves' worth of requests for one unchanged state: one run
        await asyncio.gather(*(form_routes._screen_points_once(row, "s1", "u1", []) for _ in range(3)))
        await form_routes._screen_points_once(row, "s1", "u1", [])
        assert calls == ["s1"]
        # any change to the row or the credits is a new state
        row2 = dict(row, facts={"applicant_name": {"value": NAME + " Inc"}})
        await form_routes._screen_points_once(row2, "s1", "u1", [])
        await form_routes._screen_points_once(row2, "s1", "u1", [{"rec_id": "x", "credit": 2}])
        assert calls == ["s1", "s1", "s1"]
    asyncio.run(go())


def test_a_failed_screen_points_run_is_not_cached(monkeypatch):
    from routes import form_routes
    calls = []
    monkeypatch.setattr(form_routes, "screen_points_after_forms",
                        lambda *a: calls.append(1) or {"package_sqs": None})
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_CACHE", {})
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_LOCKS", {})
    monkeypatch.setattr(form_routes, "_SCREEN_POINTS_SEM", None)

    async def go():
        for _ in range(2):
            await form_routes._screen_points_once({"facts": {}}, "s2", "u1", None)
    asyncio.run(go())
    assert len(calls) == 2


# ── 6. a partial score update drops the old plan ─────────────────────────────
def test_a_changed_headline_drops_the_stale_plan_in_the_side_panel(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    mod = os.path.normpath(os.path.join(BACKEND, "..", "frontend", "src", "utils", "editorPlanList.js"))
    js = tmp_path / "t.mjs"
    js.write_text(textwrap.dedent(f"""
        import {{ patchPackageScore }} from {json.dumps("file://" + mod)};
        const prev = {{ package_sqs_score: 79, review_plan: {{ after_forms: true, items: [], total: 21 }} }};
        const moved = patchPackageScore(prev, {{ package_sqs_score: 82 }});
        const same = patchPackageScore(prev, {{ package_sqs_score: 79, tier: "B" }});
        console.log(JSON.stringify({{ moved: "review_plan" in moved, score: moved.package_sqs_score,
          same: "review_plan" in same, untouched: "review_plan" in prev,
          nul: patchPackageScore(null, {{ package_sqs_score: 1 }}) }}));
    """))
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    # 30 Oct 2026 (end-user review): after forms EVERY patch drops the plan - an
    # answer that leaves the headline alone still changes the items (the TEST
    # pinned the stale list; test_enduser_review2_30oct.py has the full rule).
    assert got == {"moved": False, "score": 82, "same": False, "untouched": True, "nul": None}
