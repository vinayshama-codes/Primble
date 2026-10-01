"""Orbin client feedback of 22 Sep (Orbin_Testing_09_22_2026.pdf) - items 10 and 18, 30 Sep 2026.

  item 10  "Make Edit button WAY more obvious ... producers will want to click
           directly on the form to fix fields, so maybe allow double-click edit."
  item 18  "126 and other forms, all yes and no questions need to be highlighted
           and editable ... I could not edit them on 126 or 127, but I can on 186."

ROOT CAUSE OF 18, measured on the real templates: nothing refused the edit. Every
Y/N box on all 17 forms is in the viewer's field list, gets an input in edit mode,
and the save stores what is typed. The click target is the widget /Rect, and ACORD
draws a Y/N question's rect as a 12pt strip at the TOP of an answer cell that also
holds the explanation row - on 126 41 of 48 boxes, on 127 43 of 43, are smaller
than their printed cell; on 186 73 of 88 fill it. Edit mode painted a blank box
white on white, so a click in the Y/N cell landed on nothing.

Everything below runs against the real schemas and templates (read-only).
"""
from __future__ import annotations

import asyncio
import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                   # noqa: E402

SCHEMAS = BACKEND / "forms_schemas"
TEMPLATES = BACKEND / "templates"
FRONTEND = BACKEND.parent / "frontend" / "src"
VIEWER = FRONTEND / "components" / "form" / "PDFJsViewer.jsx"
VIEWER_CSS = FRONTEND / "components" / "form" / "PDFJsViewer.css"
BOXES = FRONTEND / "utils" / "viewerBoxes.js"
ACORD_MODAL = FRONTEND / "components" / "form" / "AcordModal.jsx"
_EM_DASHES = ("—", "–")

FORM_IDS = sorted(p.name[: -len("_schema.json")] for p in SCHEMAS.glob("*_schema.json"))

# (yes_no text boxes, question boxes) per form - derived from the read-only
# schemas; a change here means a schema or the definition moved.
EXPECTED = {
    "ACORD_101": (0, 0), "ACORD_125": (26, 20), "ACORD_126": (48, 44),
    "ACORD_127": (43, 17), "ACORD_130": (24, 24), "ACORD_131": (22, 21),
    "ACORD_133": (0, 38), "ACORD_137_CA": (0, 0), "ACORD_137_CO": (0, 0),
    "ACORD_138_CA": (0, 0), "ACORD_138_CO": (0, 0), "ACORD_140": (8, 0),
    "ACORD_141": (50, 45), "ACORD_160": (39, 21), "ACORD_186": (88, 88),
    "ACORD_25": (10, 0), "ACORD_28": (0, 0),
}


def _schema(fid):
    return json.loads((SCHEMAS / f"{fid}_schema.json").read_text())


_ANNOTATED: dict = {}


def _annotated(fid):
    if fid not in _ANNOTATED:
        tpl = str(TEMPLATES / f"{fid}.pdf")
        _ANNOTATED[fid] = ps.annotate_viewer_fields(
            ps.extract_form_fields_with_positions(tpl), _schema(fid), tpl)
    return _ANNOTATED[fid]


def _by_name(fid):
    return {f["name"]: f for f in _annotated(fid)}


def _intersects(a, b, tol=0.5):
    return (min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]) > tol
            and min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]) > tol)


# ═════════════════════════════════════════════════════════════════════════════
# Item 18 - which boxes are Y/N, on every form
# ═════════════════════════════════════════════════════════════════════════════
def test_all_seventeen_forms_are_covered():
    assert len(FORM_IDS) == 17
    assert set(FORM_IDS) == set(EXPECTED)


@pytest.mark.parametrize("fid", FORM_IDS)
def test_every_yes_no_box_is_in_the_viewer_list(fid):
    """The viewer can only edit what the field list carries."""
    schema = _schema(fid)
    names = {f["name"] for f in _annotated(fid)}
    yn = [k for k, v in schema.items()
          if ps.yes_no_box_kind(k, v)["yes_no"] or ps.yes_no_box_kind(k, v)["yn_question"]]
    assert [k for k in yn if k not in names] == []


@pytest.mark.parametrize("fid", FORM_IDS)
def test_every_form_marks_its_yes_no_boxes(fid):
    fields = _annotated(fid)
    assert all("yes_no" in f and "yn_question" in f for f in fields)
    yes_no = {f["name"] for f in fields if f["yes_no"]}
    question = {f["name"] for f in fields if f["yn_question"]}
    assert (len(yes_no), len(question)) == EXPECTED[fid]
    # every ACORD "_Question_<code>Code_" box is both - on 126, 127 and 186 alike
    for name in (f["name"] for f in fields):
        if ps._QUESTION_CODE_RE.search(name):
            assert name in yes_no and name in question


def test_the_client_forms_mark_every_question_box():
    for fid in ("ACORD_126", "ACORD_127", "ACORD_186"):
        by = _by_name(fid)
        qcode = [n for n in by if ps._QUESTION_CODE_RE.search(n)]
        assert qcode and all(by[n]["yes_no"] and by[n]["yn_question"] for n in qcode)


def test_schedule_row_letters_take_y_or_n_but_are_not_questions():
    """No flood: a driver row's Drive Other Car letter or a certificate's ADDL
    INSD takes a Y or N, but it is not a question the form prints - rows for
    drivers who do not exist must never be marked as unanswered questions."""
    d127 = _by_name("ACORD_127")["Driver_Coverage_DriverOtherCarCode_M"]
    assert d127["yes_no"] and not d127["yn_question"]
    a25 = _by_name("ACORD_25")["CertificateOfInsurance_GeneralLiability_AdditionalInsuredCode_A"]
    assert a25["yes_no"] and not a25["yn_question"]


def test_coverage_selection_checkboxes_are_not_questions():
    by = _by_name("ACORD_137_CA")
    assert not any(f["yn_question"] or f["yes_no"] for f in by.values())
    assert not by["Vehicle_BusinessAutoSymbol_EightIndicator_A"]["yn_question"]


def test_a_yes_no_checkbox_pair_is_one_question():
    by = _by_name("ACORD_133")
    yes = by["WorkersCompensationLineOfBusiness_Question_ADCYesIndicator_A"]
    no = by["WorkersCompensationLineOfBusiness_Question_ADCNoIndicator_A"]
    assert yes["type"] == no["type"] == "checkbox"
    assert not yes["yes_no"] and not no["yes_no"]           # the viewer draws a checkbox
    assert yes["yn_question"] and no["yn_question"]
    assert yes["yn_group"] == no["yn_group"] == "WorkersCompensationLineOfBusiness_Question_ADC_A"
    groups = {f["yn_group"] for f in by.values() if f["yn_question"]}
    assert len(groups) == 19                                 # 38 boxes, 19 questions


def test_a_text_question_is_its_own_group():
    f = _by_name("ACORD_126")["GeneralLiabilityLineOfBusiness_Question_AAJCode_A"]
    assert f["yn_group"] == f["name"]


def test_the_kind_reads_structure_not_names():
    """No schema entry and no Question-code name: nothing is guessed."""
    assert ps.yes_no_box_kind("Anything_A", None) == {"yes_no": False, "yn_question": False, "yn_group": None}
    assert ps.yes_no_box_kind("Anything_A", {"ft": "/Tx", "tu": "Enter the applicant's name."})["yes_no"] is False
    tu = "Enter Y for a “Yes” response. Input N for “No” response. Indicates X."
    assert ps.yes_no_box_kind("Anything_A", {"ft": "/Tx", "tu": tu})["yes_no"] is True
    assert ps.yes_no_box_kind("Anything_A", {"ft": "/Btn", "tu": tu})["yes_no"] is False
    # the widget type the viewer sees outranks the schema's
    assert ps.yes_no_box_kind("Anything_A", {"ft": "/Tx", "tu": tu}, "checkbox")["yes_no"] is False


# ═════════════════════════════════════════════════════════════════════════════
# Item 18 - the printed answer cell (the root cause)
# ═════════════════════════════════════════════════════════════════════════════
def test_126_question_one_edits_from_anywhere_in_its_cell():
    f = _by_name("ACORD_126")["GeneralLiabilityLineOfBusiness_Question_AAJCode_A"]
    assert f["rect"] == {"x": 576.0, "y": 366.0, "width": 14.0, "height": 12.0}
    # "1. DOES APPLICANT INSTALL, SERVICE OR DEMONSTRATE PRODUCTS?" - the Y/N
    # cell runs from the question line down past the explanation row.
    assert f["answer_rect"] == {"x": 576.0, "y": 342.0, "width": 14.0, "height": 36.0}


def test_a_box_that_already_fills_its_cell_gets_no_cell():
    """186 worked because its boxes ARE the cell - nothing changes there."""
    f = _by_name("ACORD_186")["Contractors_Question_ABACode_A"]
    assert "answer_rect" not in f
    # Q2 on 126 page 2 ("FOREIGN PRODUCTS SOLD ...") is a one-line row
    g = _by_name("ACORD_126")["GeneralLiabilityLineOfBusiness_Question_ABACode_A"]
    assert "answer_rect" not in g


def test_the_client_forms_now_have_their_cells():
    counts = {}
    for fid in ("ACORD_126", "ACORD_127", "ACORD_186"):
        yn = [f for f in _annotated(fid) if f["yes_no"]]
        counts[fid] = (sum(1 for f in yn if f.get("answer_rect")), len(yn))
    assert counts == {"ACORD_126": (41, 48), "ACORD_127": (43, 43), "ACORD_186": (15, 88)}
    q127 = [f for f in _annotated("ACORD_127") if ps._QUESTION_CODE_RE.search(f["name"])]
    assert q127 and all(f.get("answer_rect") for f in q127)


@pytest.mark.parametrize("fid", FORM_IDS)
def test_an_answer_cell_only_ever_means_its_own_box(fid):
    fields = _annotated(fid)
    for i, f in enumerate(fields):
        cell = f.get("answer_rect")
        if not cell:
            continue
        r = f["rect"]
        assert f["yes_no"], f["name"]
        # contains the box, same width, taller, and never runs down the page
        assert cell["x"] == r["x"] and cell["width"] == r["width"]
        assert cell["y"] <= r["y"] and cell["y"] + cell["height"] >= r["y"] + r["height"]
        assert r["height"] + 3 < cell["height"] <= 6 * r["height"]
        for j, g in enumerate(fields):
            if j != i and g["page"] == f["page"]:
                assert not _intersects(cell, g["rect"]), (f["name"], g["name"])


def test_the_cell_reader_fails_open(tmp_path):
    assert ps._template_horizontal_rules(str(tmp_path / "missing.pdf"), 0.0) == ()
    tpl = str(TEMPLATES / "ACORD_126.pdf")
    fields = ps.extract_form_fields_with_positions(tpl)
    out = ps.annotate_viewer_fields(fields, _schema("ACORD_126"), str(tmp_path / "missing.pdf"))
    assert sum(1 for f in out if f["yes_no"]) == 48
    assert not any("answer_rect" in f for f in out)
    # no template path at all: flags only
    out2 = ps.annotate_viewer_fields(ps.extract_form_fields_with_positions(tpl), _schema("ACORD_126"))
    assert not any("answer_rect" in f for f in out2)
    # a malformed entry is skipped, never raised
    assert ps.annotate_viewer_fields([{"name": None}, {}], {}, tpl) == [
        {"name": None, "yes_no": False, "yn_question": False},
        {"yes_no": False, "yn_question": False},
    ]


def test_answer_cell_edge_cases():
    rules = [(0.0, 612.0, 342.0), (0.0, 612.0, 378.0)]
    box = {"x": 576.0, "y": 366.0, "width": 14.0, "height": 12.0}
    assert ps._yes_no_answer_cell(box, rules, []) == {"x": 576.0, "y": 342.0, "width": 14.0, "height": 36.0}
    # another box inside the cell: no cell
    assert ps._yes_no_answer_cell(box, rules, [(576.0, 344.0, 590.0, 356.0)]) is None
    # a rule missing below: no cell
    assert ps._yes_no_answer_cell(box, [(0.0, 612.0, 378.0)], []) is None
    # a runaway "cell" (a rule missing) is refused
    assert ps._yes_no_answer_cell(box, [(0.0, 612.0, 0.0), (0.0, 612.0, 378.0)], []) is None
    # a rule that does not cross the box's column does not count
    assert ps._yes_no_answer_cell(box, [(0.0, 500.0, 342.0), (0.0, 612.0, 378.0)], []) is None
    # malformed / empty inputs
    assert ps._yes_no_answer_cell({}, rules, []) is None
    assert ps._yes_no_answer_cell({"x": 1, "y": 1, "width": 0, "height": 12}, rules, []) is None
    assert ps._yes_no_answer_cell(box, (), []) is None


# ═════════════════════════════════════════════════════════════════════════════
# Item 18 - what the producer types saves and round-trips
# ═════════════════════════════════════════════════════════════════════════════
def test_typed_yes_no_is_stored_as_acords_letter():
    s = _schema("ACORD_126")
    q = "GeneralLiabilityLineOfBusiness_Question_AAJCode_A"
    narrative = "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A"
    out = ps.normalize_yes_no_box_edits({
        q: "yes", "GeneralLiabilityLineOfBusiness_Question_ABACode_A": "No",
        "GeneralLiabilityLineOfBusiness_Question_ABBCode_A": "y",
        "GeneralLiabilityLineOfBusiness_Question_ABCCode_A": "maybe",
        "GeneralLiabilityLineOfBusiness_Question_ABDCode_A": "",
        "GeneralLiabilityLineOfBusiness_Question_ABECode_A": "N",
        narrative: "yes",
        "__form_id__": "ACORD_126",
    }, s)
    assert out[q] == "Y"
    assert out["GeneralLiabilityLineOfBusiness_Question_ABACode_A"] == "N"
    assert out["GeneralLiabilityLineOfBusiness_Question_ABBCode_A"] == "Y"
    assert out["GeneralLiabilityLineOfBusiness_Question_ABCCode_A"] == "maybe"   # kept, never blanked
    assert out["GeneralLiabilityLineOfBusiness_Question_ABDCode_A"] == ""        # a clear stays a clear
    assert out["GeneralLiabilityLineOfBusiness_Question_ABECode_A"] == "N"
    assert out[narrative] == "yes"                                               # not a Y/N box
    assert out["__form_id__"] == "ACORD_126"
    # a checkbox is never rewritten here - the PDF writer reads its own tokens
    s133 = _schema("ACORD_133")
    cb = "WorkersCompensationLineOfBusiness_Question_ADCYesIndicator_A"
    assert ps.normalize_yes_no_box_edits({cb: "yes"}, s133) == {cb: "yes"}
    assert ps.normalize_yes_no_box_edits({}, s) == {}
    assert ps.normalize_yes_no_box_edits(None, s) == {}


def test_normalising_returns_a_new_dict():
    edits = {"GeneralLiabilityLineOfBusiness_Question_AAJCode_A": "yes"}
    ps.normalize_yes_no_box_edits(edits, _schema("ACORD_126"))
    assert edits == {"GeneralLiabilityLineOfBusiness_Question_AAJCode_A": "yes"}


@pytest.mark.parametrize("fid", [f for f in FORM_IDS if EXPECTED[f][0]])
def test_every_yes_no_box_round_trips_through_the_pdf(fid, tmp_path):
    """Typed "yes" / "no" -> the save's normalisation -> fill_pdf -> the value
    the viewer reads back: "Y" / "N" in every Y/N box of every form."""
    tpl = str(TEMPLATES / f"{fid}.pdf")
    yn = [f["name"] for f in _annotated(fid) if f["yes_no"]]
    typed = {n: ("yes" if i % 2 == 0 else "no") for i, n in enumerate(yn)}
    stored = ps.normalize_yes_no_box_edits(typed, _schema(fid))
    assert set(stored.values()) <= {"Y", "N"}
    out = tmp_path / "filled.pdf"
    out.write_bytes(ps.fill_pdf(tpl, stored, {}))
    back = {f["name"]: f["value"] for f in ps.extract_form_fields_with_positions(str(out))}
    assert {n: back.get(n) for n in yn} == stored


# ═════════════════════════════════════════════════════════════════════════════
# Item 18 - the routes use the doors
# ═════════════════════════════════════════════════════════════════════════════
def _route_source(name):
    tree = ast.parse((BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment((BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8"), node)
    raise AssertionError(name)


def test_the_fields_endpoint_annotates_the_list():
    src = _route_source("get_form_fields")
    assert "annotate_viewer_fields" in src
    assert src.index("extract_form_fields_with_positions") < src.index("annotate_viewer_fields")
    assert src.index("annotate_viewer_fields") < src.index('return JSONResponse({"success": True, "fields": fields')


def test_the_schema_is_read_never_written(monkeypatch, tmp_path):
    """A GET of the field list must never write to forms_schemas/ -
    `extract_form_schema` writes a file on a cache miss, this door does not."""
    assert ps.viewer_form_schema("ACORD_126") == _schema("ACORD_126")
    monkeypatch.setattr(ps, "FORMS_SCHEMAS_DIR", str(tmp_path))
    stored = {"X_A": {"ft": "/Tx", "tu": ""}}
    assert ps.viewer_form_schema("ACORD_126", stored) == stored
    assert ps.viewer_form_schema("ACORD_126", None) == {}
    assert ps.viewer_form_schema("../../etc/passwd", None) == {}
    assert ps.viewer_form_schema("", stored) == stored
    assert list(tmp_path.iterdir()) == []
    for route in ("get_form_fields", "update_pdf"):
        src = _route_source(route)
        seg = src[src.index("Orbin 22 Sep item 18"):]
        seg = seg[:seg.index("except Exception as _ex")]
        assert "viewer_form_schema" in seg and "extract_form_schema" not in seg


def test_the_save_normalises_before_anything_reads_the_edit():
    src = _route_source("update_pdf")
    norm = src.index("normalize_yes_no_box_edits")
    assert norm < src.index("current_state.update(req.field_updates)")
    assert norm < src.index("writeback_fact_for_field")


def test_the_fields_endpoint_serves_the_marks(monkeypatch):
    """Drive the real endpoint over the real ACORD 126 template."""
    from routes import form_routes as fr

    session = {"user_id": 7, "facts": {}, "generated_forms": {"ACORD_126": {
        "form": {"template_file": "ACORD_126.pdf"},
        "field_state": {"GeneralLiabilityLineOfBusiness_Question_AAJCode_A": "N"},
        "confidence": {},
    }}}

    async def _get(_sid):
        return session

    async def _upd(*_a, **_k):
        return None

    monkeypatch.setattr(fr, "get_processing_session", _get)
    monkeypatch.setattr(fr, "upd_processing_session", _upd)
    monkeypatch.setattr(fr, "check_payment_access", lambda *_a, **_k: None)
    monkeypatch.setattr(fr, "TEMPLATE_DIR", str(TEMPLATES))
    resp = asyncio.run(fr.get_form_fields("s1", "ACORD_126", current_user={"id": 7}))
    body = json.loads(resp.body)
    by = {f["name"]: f for f in body["fields"]}
    q = by["GeneralLiabilityLineOfBusiness_Question_AAJCode_A"]
    assert q["value"] == "N" and q["yes_no"] and q["yn_question"]
    assert q["answer_rect"]["height"] == 36.0
    assert sum(1 for f in body["fields"] if f["yes_no"]) == 48


# ═════════════════════════════════════════════════════════════════════════════
# The viewer (frontend) - the logic, run in node
# ═════════════════════════════════════════════════════════════════════════════
def _node(tmp_path, body):
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as B from {json.dumps(BOXES.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_y_n_box_takes_only_y_or_n(tmp_path):
    cases = [
        ["", "", None], ["y", "", 1], ["n", "", 1], ["Y", "", 1], ["yes", "", 3],
        ["No", "", 2], ["TRUE", "", 4], ["Yn", "Y", 2], ["nY", "Y", 1], ["Ye", "Y", 2],
        ["a", "", 1], ["Ya", "Y", 2], ["", "Y", 0], ["mayb", "maybe", 4], ["maybeX", "maybe", 6],
        ["Yes, see remarks", "", 16], ["  n  ", "", 3], ["y", "N", 1],
    ]
    out = _node(tmp_path, "const cases = " + json.dumps(cases) + ";\n"
                "console.log(JSON.stringify(cases.map(([r, p, c]) => B.normalizeYesNoEntry(r, p, c))));")
    # "nY" with the caret after the n: the letter just typed (N) replaces the Y
    assert out == ["", "Y", "N", "Y", "Y", "N", "Y", "N", "N", "Y",
                   "", "Y", "", "", "maybe", "", "N", "Y"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_double_click_finds_the_box_the_overlay_draws(tmp_path):
    """The hit test and the overlay share one geometry; a click in the lower
    part of 126's Y/N cell hits the box once the server sent the cell."""
    q = {"name": "Q", "page": 1, "type": "text", "yes_no": True,
         "rect": {"x": 576, "y": 366, "width": 14, "height": 12},
         "answer_rect": {"x": 576, "y": 342, "width": 14, "height": 36}}
    bare = dict(q, name="Bare")
    del bare["answer_rect"]
    expl = {"name": "Expl", "page": 1, "type": "text",
            "rect": {"x": 22, "y": 342, "width": 547, "height": 24}}
    small = {"name": "Small", "page": 1, "type": "text",
             "rect": {"x": 30, "y": 350, "width": 10, "height": 5}}
    scale, H = 1.5, 792
    body = (
        f"const q = {json.dumps(q)}, bare = {json.dumps(bare)}, expl = {json.dumps(expl)}, small = {json.dumps(small)};\n"
        f"const s = {scale}, H = {H};\n"
        "const px = (x) => x * s, py = (y) => (H - y) * s;\n"
        "const r = [];\n"
        # a click in the explanation row of the Y/N column (y = 350)
        "r.push(B.hitTestBox([q], 1, px(583), py(350), s, H)?.name ?? null);\n"
        "r.push(B.hitTestBox([bare], 1, px(583), py(350), s, H)?.name ?? null);\n"
        # the box itself still hits
        "r.push(B.hitTestBox([bare], 1, px(583), py(372), s, H)?.name ?? null);\n"
        # wrong page, empty page, nothing there
        "r.push(B.hitTestBox([q], 0, px(583), py(350), s, H)?.name ?? null);\n"
        "r.push(B.hitTestBox([q, expl], 1, px(300), py(500), s, H)?.name ?? null);\n"
        "r.push(B.hitTestBox(null, 1, 1, 1, s, H));\n"
        "r.push(B.hitTestBox([q], 1, NaN, 1, s, H));\n"
        "r.push(B.hitTestBox([q], 1, 1, 1, 0, H));\n"
        # overlapping boxes: the smaller one wins
        "r.push(B.hitTestBox([expl, small], 1, px(32), py(353), s, H)?.name ?? null);\n"
        # the minimum drawn size (18 x 14 px) is clickable, like the overlay
        "const tiny = {name: 'Tiny', page: 1, rect: {x: 100, y: 100, width: 2, height: 2}};\n"
        "r.push(B.hitTestBox([tiny], 1, px(100) + 17, py(102) + 13, s, H)?.name ?? null);\n"
        "r.push(B.boxPixelRect({x: 100, y: 100, width: 2, height: 2}, s, H));\n"
        "r.push(B.boxPixelRect({x: 576, y: 366, width: 14, height: 12}, 2, H));\n"
        "console.log(JSON.stringify(r));"
    )
    out = _node(tmp_path, body)
    assert out[:10] == ["Q", None, "Bare", None, None, None, None, None, "Small", "Tiny"]
    assert out[10] == {"left": 150, "top": (792 - 102) * 1.5, "width": 18, "height": 14}
    assert out[11] == {"left": 1152, "top": (792 - 378) * 2, "width": 28, "height": 24}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_an_unanswered_question_is_known_per_question(tmp_path):
    fields = [
        {"name": "PairYes", "yn_question": True, "yn_group": "P", "type": "checkbox"},
        {"name": "PairNo", "yn_question": True, "yn_group": "P", "type": "checkbox"},
        {"name": "Text", "yn_question": True, "yn_group": "Text", "type": "text"},
        {"name": "Row", "yes_no": True, "yn_question": False, "type": "text"},
    ]
    body = (
        f"const f = {json.dumps(fields)};\n"
        "const r = [\n"
        "  B.isYesNoQuestionBlank(f[0], f, {PairYes: 'Off', PairNo: ''}),\n"
        "  B.isYesNoQuestionBlank(f[0], f, {PairYes: 'Off', PairNo: 'Yes'}),\n"
        "  B.isYesNoQuestionBlank(f[1], f, {PairYes: '1', PairNo: 'Off'}),\n"
        "  B.isYesNoQuestionBlank(f[2], f, {Text: ''}),\n"
        "  B.isYesNoQuestionBlank(f[2], f, {Text: 'N'}),\n"
        "  B.isYesNoQuestionBlank(f[2], f, {Text: 'None'}),\n"
        "  B.isYesNoQuestionBlank(f[3], f, {Row: ''}),\n"
        "  B.isYesNoQuestionBlank(null, f, {}),\n"
        "];\n"
        "console.log(JSON.stringify(r));"
    )
    assert _node(tmp_path, body) == [True, False, False, True, False, True, False, False]


# ═════════════════════════════════════════════════════════════════════════════
# The viewer (frontend) - what the source must keep
# ═════════════════════════════════════════════════════════════════════════════
def _src(path):
    return path.read_text(encoding="utf-8")


def test_the_edit_button_is_unmistakable():
    src = _src(VIEWER)
    assert '{editMode ? "Done editing - save" : "Edit form"}' in src
    assert 'className={`pdfviewer-edit-btn${editMode ? " is-editing" : ""}`}' in src
    assert "<svg" in src and "M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" in src   # the pencil
    # the old grey toggle is gone
    assert '"Edit Fields"' not in src and '"Done Editing"' not in src
    css = _src(VIEWER_CSS)
    assert "background: #E61B84;" in css and "color: #fff;" in css
    # App.css forces every toolbar button to 9px on laptops and tablets; this
    # button out-ranks it at every width
    assert css.count(".pdfviewer-toolbar-actions .pdfviewer-edit-btn {") == 2
    assert "font-size: 12px !important;" in css and "font-size: 13px !important;" in css
    # "Done editing - save" is SMALLER than "Edit form" (owner, 30 Sep 2026: in
    # edit mode the toolbar must stay on one line), at every width
    assert css.count(".pdfviewer-toolbar-actions .pdfviewer-edit-btn.is-editing {") == 2
    editing = css[css.index(".pdfviewer-edit-btn.is-editing {"):]
    editing = editing[:editing.index("}")]
    assert "font-size: 12px;" in editing and "padding: 4px 10px;" in editing
    assert 'import "./PDFJsViewer.css";' in src


def test_the_edit_button_keeps_every_behaviour():
    src = _src(VIEWER)
    assert 'const editBusy = saveStatus === "saving" || saveStatus === "generating";' in src
    assert "<button onClick={handleToggleEditMode} disabled={editBusy}" in src
    assert 'cursor: editBusy ? "wait" : "pointer", opacity: editBusy ? 0.7 : 1' in src
    body = src[src.index("const handleToggleEditMode"):src.index("const _loadPdfInBackground")]
    # the save path is unchanged: one POST of the changed boxes, the signed
    # flag, the cleared signature boxes, and the score callback
    for piece in ('fetch(`${API_BASE}/api/update-pdf`', "__form_id__: formId",
                  '__signed__: isSignedLocal ? "1" : "0"', "__cleared_sig_fields__",
                  "onSqsUpdate(formId, data.sqs", "hasUnsavedEdits()", "setEditMode(m => !m)"):
        assert piece in body, piece
    # The toolbar's "Unsaved" marker was removed by the owner (30 Sep 2026: it
    # wrapped the toolbar onto two lines). The side panel still says the score
    # is from the last save while edits are pending - in the owner's shorter
    # words (1 Oct 2026 retest).
    assert "Unsaved - score updates when you save" not in src
    assert UNSAVED_SCORE_NOTE in _src(ACORD_MODAL)


def test_double_click_enters_edit_mode_and_never_changes_a_value():
    src = _src(VIEWER)
    assert "onDoubleClick={handleCanvasDoubleClick}" in src
    body = src[src.index("const handleCanvasDoubleClick"):src.index("return (\n")]
    assert "if (editModeRef.current || editBusy || applyingSign" in body   # view mode only, never while busy
    # the page the canvas SHOWS, not the page the toolbar is heading to
    # (Orbin item 14, 1 Oct 2026 - the TEST changed: a painted applicant box is not a hit)
    assert "hitTestBox(fieldsRef.current.filter(f => !f.painted), shown - 1" in body
    assert "const shown = shownPageRef.current.page;" in body
    assert "pendingFocusRef.current = hit.name;" in body and "setEditMode(true);" in body
    for forbidden in ("triggerSave", ".checked", "fieldValuesRef.current[", "setFieldValues"):
        assert forbidden not in body, forbidden
    # the focus step only focuses: a checkbox is never clicked or toggled
    build = src[src.index("const buildOverlay"):src.index("// ── Unsaved-edit tracking")]
    focus = build[build.index("const want = pendingFocusRef.current;"):]
    assert "target.focus()" in focus and ".click()" not in focus and ".checked" not in focus
    assert "Double-click any box to edit it" in src


def test_a_yes_no_question_is_highlighted_only_when_answered_in_its_own_colour():
    """Owner, 1 Oct night (the TEST changed through the night): a Y/N box is
    highlighted ONLY when it holds an answer, in that answer's own colour
    (client green, AI-OK pink, verify orange) - no Y/N colour of its own. A
    blank one is plain, even when required, and is not counted. Typing
    repaints through the same rule; all stay editable."""
    src = _src(VIEWER)
    build = src[src.index("const _boxBg"):src.index("const buildOverlay")]
    assert "if (field.yn_question && isBlankBoxValue(val)) return _highlightBg(null, curEdit);" in build
    assert "return _highlightBg(_getHighlight(field.name, val), curEdit);" in build
    for gone in ("YN_ANSWERED_BG", "YN_BLANK_BG", "219,234,254", "Yes / No answered",
                 "Yes / No question not answered yet"):
        assert gone not in src, gone
    assert "if (f.yn_question && isBlankBoxValue(vals[name] ?? f.value)) return;" in src
    assert src.count("wrap.style.background = _boxBg(field, e.target.value, curEdit);") == 2
    # a Y/N box normalises through the shared helper and the ONE save path
    assert "next = normalizeYesNoEntry(next, lastYn, e.target.selectionStart);" in src
    assert "triggerSave(field.name, next);" in src
    cell = src[src.index("if (curEdit && field.yes_no && field.answer_rect"):]
    cell = cell[:cell.index("overlay.appendChild(wrap);")]
    assert "target.focus()" in cell and "triggerSave" not in cell


def test_a_yes_no_pair_never_holds_both_answers():
    src = _src(VIEWER)
    assert "if (e.target.checked && field.yn_group && field.yn_group !== field.name)" in src
    assert 'triggerSave(g.name, "Off");' in src


# The owner's own words for the pending-edits note (1 Oct 2026 retest); it
# replaced "These scores are from the last save - click "Done editing - save"
# to update them."
UNSAVED_SCORE_NOTE = "You have unsaved field edits. These scores are from the last save. Save to update."


def test_the_side_panel_note_reads_as_the_owner_wrote_it():
    src = _src(ACORD_MODAL)
    assert "click Done Editing" not in src
    assert 'click {"\\"Done editing - save\\""} to update them.' not in src
    assert src.count(UNSAVED_SCORE_NOTE) == 1


@pytest.mark.parametrize("path", [VIEWER_CSS, BOXES])
def test_no_em_dashes_in_the_new_files(path):
    assert not any(d in _src(path) for d in _EM_DASHES)


def test_no_em_dashes_in_the_viewer_ui_text():
    """The viewer's toolbar, hints and overlay text (two older code comments
    in `_highlightBg` carry one; they are not UI)."""
    src = _src(VIEWER)
    ui = src[src.index("return (\n"):]
    assert not any(d in ui for d in _EM_DASHES)
    for text in ("Done editing - save", "Edit form", "Double-click any box to edit it", "Type Y or N"):
        assert text in src
