"""A save that moves the package's stops refreshes every form (15 Oct 2026).

Live `0353c36b`: a stale umbrella-renewal warning capped the package and all 10
forms at 85. The fix that retires it was deployed; the owner confirmed one value
(`/api/update-pdf`), and the PACKAGE went to 99 with no stops - but nine forms
kept 85 under the old warning and the review page kept listing it. The save
path re-scored only the edited form, the forms its edit propagated to and the
package; the stored issue list and every other form's score are rebuilt only by
`arq_service.recalculate_session_scores`. Now a save whose fresh stops differ
from the stored ones runs that one recalculation and returns every form's score
(`forms_sqs`), which the screen merges (`utils/formScores.withFormScores`).
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess

import pytest

from routes.form_routes import issue_list_outdated, stop_signature

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"
UTIL = FRONT / "utils" / "formScores.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_stop_signature_ignores_order_and_duplicates():
    a = stop_signature(["H1"], ["W2", "W1", "W1"])
    assert a == stop_signature(["H1", ""], ["W1", "W2"])
    assert a != stop_signature(["H1"], ["W1"])                     # a warning cleared: different
    assert stop_signature(None, None) == stop_signature([], [])


def _update_pdf_source():
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_pdf")
    return ast.get_source_segment(src, node)


def test_the_save_compares_its_stops_with_the_stored_ones_and_recalculates():
    body = _update_pdf_source()
    assert '_stops_before = stop_signature(session.get("hard_stops"), session.get("soft_stops"))' in body
    i = body.index("if stop_signature(fresh_hard_stops, fresh_soft_stops) != _stops_before")
    assert "or issue_list_outdated(session.get(\"structured_issues\")," in body[i:i + 300]
    tail = body[i:]
    assert "await recalculate_session_scores(req.session_id)" in tail
    assert '"forms_sqs": _forms_sqs' in tail
    # the recalculation runs only on a change - never on every save
    assert body.count("recalculate_session_scores(") == 1


def test_every_screen_save_merges_the_returned_form_scores():
    modal = (FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    viewer = (FRONT / "components" / "form" / "PDFJsViewer.jsx").read_text(encoding="utf-8")
    assert 'import { withFormScores } from "../../utils/formScores";' in modal
    assert modal.count("withFormScores(prev, data.forms_sqs)") == 2          # confirm + "Use this value"
    assert "}, extras?.formsSqs));" in modal                                  # the viewer's save
    assert "formsSqs: data.forms_sqs" in viewer


def _run(tmp_path, body):
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as R from {json.dumps(UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_with_form_scores_replaces_only_listed_forms(tmp_path):
    forms = {"A": {"sqs": {"sqs_score": 85}, "x": 1}, "B": {"sqs": {"sqs_score": 85}}, "C": {"sqs": {"sqs_score": 70}}}
    out = _run(tmp_path, (
        f"const f = {json.dumps(forms)};\n"
        "const a = R.withFormScores(f, {A: {sqs_score: 100}, B: {sqs_score: 99}, Z: {sqs_score: 1}});\n"
        "const same = R.withFormScores(f, null) === f && R.withFormScores(f, {}) === f;\n"
        "console.log(JSON.stringify({a, same}));"))
    assert out["a"]["A"] == {"sqs": {"sqs_score": 100}, "x": 1}
    assert out["a"]["B"]["sqs"]["sqs_score"] == 99 and out["a"]["C"]["sqs"]["sqs_score"] == 70
    assert "Z" not in out["a"] and out["same"] is True


STALE = {"code": "legacy_umbrella_renewal_term_unknown",
         "message": ("Renewal: the umbrella's proposed policy term is not stated in the documents - confirm "
                     "the proposed effective and expiration dates. Fix: Review and correct this before proceeding.")}
STOP = ("Renewal: the umbrella's proposed policy term is not stated in the documents - confirm the proposed "
        "effective and expiration dates.")


def test_a_stored_warning_the_stops_no_longer_raise_is_outdated():
    # the live shape after the owner's Confirm: stops empty, the list still holds it
    assert issue_list_outdated([STALE], [], []) is True
    # still raised: not outdated (the stored text carries its fix sentence)
    assert issue_list_outdated([STALE], [], [STOP]) is False
    # issues not built from the stops are never judged here
    assert issue_list_outdated([{"code": "umbrella_no_underlying_coverage", "message": "x"}], [], []) is False
    assert issue_list_outdated(None, None, None) is False
