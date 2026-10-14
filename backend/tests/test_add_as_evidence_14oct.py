"""'Add as evidence only' (owner's choice, 14 Oct 2026).

After forms, a document naming a different insured is refused with two answers:
keep it as evidence only, or use its values because it IS this insured. Evidence
only = stored and listed, EXCLUDED (the merge, the forms, the score and Submission
Integrity read only active documents), no AI fill, and its Documents row says so.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from routes.form_routes import _doc_summaries, _evidence_status
from routes.session_documents_routes import _keep_as_evidence
from services.session_documents import active_documents, integrity_plan

ROOT = pathlib.Path(__file__).resolve().parents[2]
UTIL = ROOT / "frontend" / "src" / "utils" / "addDocuments.js"
PANEL = ROOT / "frontend" / "src" / "components" / "form" / "review" / "AddDocumentsPanel.jsx"
ROUTES = ROOT / "backend" / "routes" / "session_documents_routes.py"


def _doc(did, name, **kw):
    return {"doc_id": did, "filename": f"{did}.pdf", "doc_type": "dec_page",
            "facts": {"applicant_name": {"value": name, "source": "ai"}} if name else {}, **kw}


def test_evidence_marks_the_document_excluded_with_its_insured():
    d = _doc("ctl", "MERIDIAN FABRICATION INC")
    _keep_as_evidence(d)
    assert d["excluded"] is True and d["evidence_only"] is True
    assert d["evidence_insured"] == "MERIDIAN FABRICATION INC"
    nameless = _doc("x", None)
    _keep_as_evidence(nameless)
    assert nameless["excluded"] and "evidence_insured" not in nameless


def test_an_evidence_document_never_reaches_integrity_or_the_merge():
    own = [_doc("u", "CHOICE ELECTRIC LLC"), _doc("a", "CHOICE ELECTRIC LLC")]
    ctl = _doc("ctl", "MERIDIAN FABRICATION INC")
    _keep_as_evidence(ctl)
    assert [d["doc_id"] for d in active_documents(own + [ctl])] == ["u", "a"]
    plan = integrity_plan(None, own + [ctl], confirm_same_insured=False, user_id="u1")
    assert plan["review_needed"] is False


def test_its_row_says_different_insured_evidence_only_and_include_clears_it():
    ctl = _doc("ctl", "MERIDIAN FABRICATION INC")
    _keep_as_evidence(ctl)
    rows = _doc_summaries([ctl])
    st = rows[0]["insured_status"]
    assert st == {"state": "different", "name": "MERIDIAN FABRICATION INC", "kept_by_you": False, "evidence_only": True}
    assert rows[0]["evidence_only"] is True and rows[0]["excluded"] is True
    ctl["excluded"] = False          # "Include" - judged by the integrity record from then on
    assert _evidence_status(ctl) is None


def test_the_route_reads_no_ai_fill_from_evidence_documents():
    src = ROUTES.read_text(encoding="utf-8")
    assert "as_evidence: bool = Form(False)" in src
    assert "fill_docs = [d for d in added if not d.get(\"excluded\")]" in src
    assert "start_new_document_fill(session_id, fill_docs" in src
    assert "if door.get(\"forms_exist\") and fill_docs:" in src


def test_the_panel_offers_both_answers():
    src = PANEL.read_text(encoding="utf-8")
    assert "Add as evidence only" in src and "It is this insured - use its values" in src
    assert 'body.append("as_evidence"' in src
    assert "—" not in src


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_tag_and_result_line_words(tmp_path):
    script = tmp_path / "c.mjs"
    script.write_text(
        f"import * as A from {json.dumps(UTIL.as_uri())};\n"
        "const tag = A.documentInsuredTag({ insured_status: { state: 'different', name: 'MERIDIAN FABRICATION INC', evidence_only: true } });\n"
        "const lines = A.documentsResultLines({ documents_added: [{}], after_forms: true, boxes_updated: 0, forms_updated: [], evidence_only: ['control_dec.pdf'] });\n"
        "console.log(JSON.stringify({ tag, lines }));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["tag"]["label"] == "Different insured: MERIDIAN FABRICATION INC - evidence only"
    assert any("Kept as evidence only: control_dec.pdf" in l["text"] for l in o["lines"])
