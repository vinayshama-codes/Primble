"""Filled AcroForm values reach the extracted text (owner's package f83757cf, 14 Oct).

THE DEFECT. A fillable PDF keeps every typed value in its form field's /V entry,
never in the page content stream pdfplumber reads. The owner's "ACORD_125_FILLED
2.pdf" (Harborline Plumbing & Mechanical, LLC; GRANITE PEAK CASUALTY COMPANY;
10/15/2026) carried 234 filled values and its extracted text held none of them:
extraction found no applicant, read the blank template's printed menus as facts,
and Submission Integrity listed it as "(no applicant name detected)".

THE FIX (utils/form_field_text.py, wired in services/ocr_service.py). Each page's
filled values are appended after that page's content under one heading line,
"label: value" per line, whichever route the page took - native text, the
column reflow, Google Vision, mixed - exactly once. A PDF without filled values
produces exactly the text it always did.

These tests never call Google Vision (`_vision_batch_call` is stubbed) and build
their PDFs with pikepdf 9.x, which has no `pikepdf.Boolean`.

Run from backend/:
    python -m pytest tests/test_filled_form_fields_14oct.py -p no:randomly -q
"""

import asyncio
import glob
import os
import re
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import fitz  # noqa: E402
import pikepdf  # noqa: E402
import pytest  # noqa: E402
from pikepdf import Array, Dictionary, Name, Pdf, String  # noqa: E402

from services import ocr_service  # noqa: E402
from utils import form_field_text as fft  # noqa: E402

TEMPLATES = os.path.join(BACKEND, "templates")
ACORD_125 = os.path.join(TEMPLATES, "ACORD_125.pdf")
HEADING_RE = re.compile(r"^\[Filled form fields - page (\d+)\]$", re.M)
BODY = ("Declarations continued. Additional coverage terms and conditions apply to "
        "every location listed in the schedule. ")


# ---------------------------------------------------------------------------
# Vision stub (same isolation as tests/test_ocr_embedded_images.py)
# ---------------------------------------------------------------------------

class _PassThroughCB:
    opened = False

    def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class _FakeVision:
    def __init__(self, text=""):
        self.text = text
        self.payloads = 0

    def __call__(self, payloads):
        self.payloads += len(payloads)
        return [ocr_service._OcrResult(text=self.text, low_conf=[],
                                       total_tokens=max(1, len(self.text.split())))
                for _ in payloads]


@pytest.fixture()
def vision(monkeypatch):
    fv = _FakeVision()
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())
    monkeypatch.setattr(ocr_service, "_vision_batch_call", fv)
    return fv


def _extract(path):
    return asyncio.run(ocr_service.extract_text_from_pdf(path))[0]


def _extract_without_fields(monkeypatch, path):
    """The pre-fix route: no form-field read at all."""
    with monkeypatch.context() as m:
        m.setattr(ocr_service, "read_filled_fields", lambda *a, **k: {})
        return _extract(path)


def _blocks(text):
    """{page: [lines]} for every form-field block in an extracted text."""
    out = {}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln)
        if not m:
            continue
        body = []
        for nxt in lines[i + 1:]:
            if nxt.startswith("[Document page ") or HEADING_RE.match(nxt):
                break
            body.append(nxt)
        out[int(m.group(1))] = body
    return out


def _strip_blocks(text):
    """The text with every form-field block (and a page marker left with nothing
    under it) removed - what the pre-fix extraction produced."""
    lines = text.splitlines()
    kept, skipping = [], False
    for ln in lines:
        if HEADING_RE.match(ln):
            skipping = True
            continue
        if skipping and not ln.startswith("[Document page "):
            continue
        skipping = False
        kept.append(ln)
    out = []
    for i, ln in enumerate(kept):
        nxt = kept[i + 1] if i + 1 < len(kept) else None
        if ln.startswith("[Document page ") and (nxt is None or nxt.startswith("[Document page ")):
            continue
        out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# PDF builders
# ---------------------------------------------------------------------------

def _fill_template(src, dst, values=None, ticks=()):
    """Fill a real ACORD template the way a PDF viewer does: /V on the field, the
    widget's /AS on its own on-state for a ticked box, NeedAppearances set."""
    with pikepdf.open(src) as pdf:
        acro = pdf.Root.AcroForm
        by_name = {}

        def walk(node, prefix=""):
            t = str(node.get("/T")) if "/T" in node else None
            full = f"{prefix}.{t}" if (prefix and t) else (t or prefix)
            if t is not None:
                by_name[full] = node
            for kid in node.get("/Kids") or []:
                walk(kid, full)

        for f in acro.Fields:
            walk(f)
        for name, value in (values or {}).items():
            by_name[name].V = String(value)
        for name in ticks:
            field = by_name[name]
            widgets = list(field.Kids) if "/Kids" in field else [field]
            on = next(str(k) for k in widgets[0].AP.N.keys() if str(k) != "/Off")
            field.V = Name(on)
            for w in widgets:
                w.AS = Name(on)
        acro.NeedAppearances = True
        pdf.save(dst)


def _ap_states(pdf, *states):
    n = Dictionary()
    for s in states:
        st = pdf.make_stream(b"")
        st.Type = Name.XObject
        st.Subtype = Name.Form
        st.BBox = Array([0, 0, 10, 10])
        n[s] = st
    return Dictionary(N=n)


def _widget(pdf, page_obj, rect, **entries):
    w = Dictionary(Type=Name.Annot, Subtype=Name.Widget, Rect=Array(rect), P=page_obj,
                   F=entries.pop("F", 4))
    for k, v in entries.items():
        w[f"/{k}"] = v
    w = pdf.make_indirect(w)
    if "/Annots" not in page_obj:
        page_obj.Annots = Array([])
    page_obj.Annots.append(w)
    return w


def _text_field(pdf, page_obj, name, value, rect, tu=None, **entries):
    extra = dict(entries)
    if tu is not None:
        extra["TU"] = String(tu)
    if value is not None:
        extra["V"] = String(value)
    return _widget(pdf, page_obj, rect, FT=Name.Tx, T=String(name), **extra)


def _checkbox(pdf, page_obj, name, on, checked, rect, tu=None, set_v=True):
    extra = {"AP": _ap_states(pdf, f"/{on}", "/Off"),
             "AS": Name(f"/{on}") if checked else Name.Off}
    if set_v:
        extra["V"] = Name(f"/{on}") if checked else Name.Off
    if tu is not None:
        extra["TU"] = String(tu)
    return _widget(pdf, page_obj, rect, FT=Name.Btn, T=String(name), **extra)


def _finish(pdf, fields, path):
    pdf.Root.AcroForm = Dictionary(Fields=Array(fields), NeedAppearances=True)
    pdf.save(path)


def _base(path, pages):
    """pages: list of ("text", body) | ("scan", None) | ("text+image", body)."""
    doc = fitz.open()
    for kind, body in pages:
        page = doc.new_page(width=612, height=792)
        if kind == "scan":
            page.insert_text((40, 40), "scan", fontsize=8)              # < 100 chars
            page.draw_rect(fitz.Rect(20, 60, 590, 770), color=(0, 0, 0))
            continue
        page.insert_textbox(fitz.Rect(40, 420, 570, 780), body, fontsize=9)
        if kind == "text+image":
            src = fitz.open()
            sp = src.new_page(width=200, height=100)
            sp.draw_rect(fitz.Rect(0, 0, 200, 100), color=(0, 0, 0), fill=(1, 1, 1))
            sp.insert_text((10, 30), "scanned schedule", fontsize=9)
            pix = sp.get_pixmap(matrix=fitz.Matrix(3, 3))
            src.close()
            page.insert_image(fitz.Rect(40, 60, 240, 160), pixmap=pix)
    doc.save(path)
    doc.close()


def _drawn_page(path, draws, fields_spec):
    """One page whose CONTENT STREAM draws `draws` [(x, y, text)] (a flattened
    PDF's text layer) and whose AcroForm carries `fields_spec` [(name, value, rect)]."""
    pdf = Pdf.new()
    font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                        BaseFont=Name.Helvetica))
    ops = [f"BT /F1 9 Tf {x} {y} Td ({t}) Tj ET" for x, y, t in draws]
    page = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]),
                      Resources=Dictionary(Font=Dictionary(F1=font)),
                      Contents=pdf.make_stream("\n".join(ops).encode()))
    pdf.pages.append(pikepdf.Page(page))
    pg = pdf.pages[0].obj
    fields = [_text_field(pdf, pg, n, v, r) for n, v, r in fields_spec]
    _finish(pdf, fields, path)


# ===========================================================================
# 1. A real filled ACORD 125: the values reach the text, labelled, once
# ===========================================================================

_ACORD_125_VALUES = {
    "NamedInsured_FullName_A": "Harborline Plumbing & Mechanical, LLC",
    "Insurer_FullName_A": "GRANITE PEAK CASUALTY COMPANY",
    "Policy_EffectiveDate_A": "10/15/2026",
    # One field, five widgets (the AGENCY CUSTOMER ID printed on every page);
    # the kids carry no /T, /V or /FT of their own - all inherited.
    "Producer_CustomerIdentifier_A": "HARB-0042",
    # Page 2: an ACORD Y/N question box.
    "CommercialStructure_Question_ABBCode_A": "N",
}
# Its on-state is "/1", not "/Yes": the export value must still read "ticked".
_ACORD_125_TICKS = ("Policy_LineOfBusiness_CommercialGeneralLiability_A",)


@pytest.fixture(scope="module")
def acord_125_texts(tmp_path_factory):
    """(blank text, filled text) of the real ACORD 125, Vision stubbed."""
    dst = str(tmp_path_factory.mktemp("acord125") / "ACORD_125_FILLED.pdf")
    _fill_template(ACORD_125, dst, _ACORD_125_VALUES, _ACORD_125_TICKS)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(ocr_service, "_vision_cb", _PassThroughCB())
        m.setattr(ocr_service, "_vision_batch_call", _FakeVision())
        return _extract(ACORD_125), _extract(dst), dst


def test_filled_acord_125_values_reach_the_text_with_labels(acord_125_texts):
    _blank, filled, _ = acord_125_texts
    blocks = _blocks(filled)
    page1 = blocks.get(1, [])
    assert "Named Insured Full Name (A): Harborline Plumbing & Mechanical, LLC" in page1
    assert "Insurer Full Name (A): GRANITE PEAK CASUALTY COMPANY" in page1
    # ACORD's "As used here" clause is what tells the PROPOSED date from a prior one.
    assert "Policy Effective Date (A) - this is the proposed effective date: 10/15/2026" in page1
    assert "Policy Line Of Business Commercial General Liability (A): ticked" in page1
    # A Y/N question box carries the question as its label, on its own page.
    assert "Any area leased to others? (A): N" in blocks.get(2, [])


def test_a_field_on_every_page_is_emitted_once_on_its_first_page(acord_125_texts):
    _blank, filled, _ = acord_125_texts
    assert filled.count("HARB-0042") == 1
    assert any(ln.endswith(": HARB-0042") for ln in _blocks(filled)[1])


def test_each_block_sits_under_its_own_page(acord_125_texts):
    _blank, filled, _ = acord_125_texts
    p1, p2 = filled.index("[Document page 1]"), filled.index("[Document page 2]")
    p3 = filled.index("[Document page 3]")
    assert p1 < filled.index("[Filled form fields - page 1]") < p2
    assert p2 < filled.index("[Filled form fields - page 2]") < p3
    assert filled.count("[Filled form fields - page 1]") == 1


def test_the_filled_text_is_the_blank_text_plus_the_blocks(acord_125_texts):
    blank, filled, _ = acord_125_texts
    assert blank != filled
    assert _strip_blocks(filled) == blank.strip()
    # Nothing the person did not type: only the five values and the one tick.
    lines = [ln for body in _blocks(filled).values() for ln in body]
    assert len(lines) == len(_ACORD_125_VALUES) + len(_ACORD_125_TICKS)


def test_the_filled_form_is_still_an_application(acord_125_texts):
    """Field NAMES label the lines, not tooltips: ACORD 125's named-insured
    tooltip says "...as it will appear on the policy declarations page", and as
    labels the tooltips turned the owner's three filled 125s into Dec Pages."""
    from services.extraction_service import classify_document
    from utils.text_cleaner import clean_text
    blank, filled, _ = acord_125_texts
    for fn in ("ACORD_125_FILLED.pdf", "upload.pdf"):
        assert classify_document(clean_text(blank), fn)["doc_type"] == "application"
        assert classify_document(clean_text(filled), fn)["doc_type"] == "application"


# ===========================================================================
# 2. No filled values -> byte-identical text
# ===========================================================================

def test_every_blank_acord_template_reads_no_filled_values():
    """The templates' one pre-set value (the edition identifier) is hidden and
    zero-size - a page cannot show it, so it is never appended as if typed."""
    paths = sorted(glob.glob(os.path.join(TEMPLATES, "*.pdf")))
    assert len(paths) == 17
    for p in paths:
        assert fft.read_filled_fields(p) == {}, os.path.basename(p)


@pytest.mark.parametrize("name", ["ACORD_25.pdf", "ACORD_101.pdf", "ACORD_131.pdf"])
def test_blank_template_text_is_unchanged(monkeypatch, vision, name):
    p = os.path.join(TEMPLATES, name)
    assert _extract(p) == _extract_without_fields(monkeypatch, p)


def test_blank_acord_125_text_is_unchanged(monkeypatch, vision, acord_125_texts):
    blank, _filled, _ = acord_125_texts
    assert blank == _extract_without_fields(monkeypatch, ACORD_125)


def test_pdf_without_acroform_is_unchanged(tmp_path, monkeypatch, vision):
    p = str(tmp_path / "plain.pdf")
    _base(p, [("text", BODY * 8), ("scan", None), ("text+image", BODY * 8)])
    with pikepdf.open(p) as pdf:
        assert "/AcroForm" not in pdf.Root
    assert fft.read_filled_fields(p) == {}
    assert _extract(p) == _extract_without_fields(monkeypatch, p)


def test_the_off_switch_restores_the_old_text(monkeypatch, vision, acord_125_texts):
    blank, _filled, dst = acord_125_texts
    monkeypatch.setattr(fft, "_ON", False)
    assert fft.read_filled_fields(dst) == {}
    assert _extract(dst) == blank


# ===========================================================================
# 3. Never twice: a value the text layer already draws in its box
# ===========================================================================

def test_a_value_drawn_in_its_own_box_is_not_doubled(tmp_path, vision):
    """A partly flattened PDF: the value is in the content stream AND the field."""
    p = str(tmp_path / "flattened.pdf")
    _drawn_page(p, draws=[
        (104, 706, "GRANITE PEAK CASUALTY COMPANY"),
        (104, 656, "Inspection / Loss Control"),          # a literal " / " of its own
        (104, 556, "Y"),
        (40, 40, "ACORD 125 (2025/03) printed edition footer with enough words to be native text"),
        (40, 300, BODY), (40, 290, BODY),
    ], fields_spec=[
        ("Insurer_FullName_A", "GRANITE PEAK CASUALTY COMPANY", [100, 700, 400, 720]),
        ("NamedInsured_Contact_ContactDescription_A", "Inspection / Loss Control", [100, 650, 400, 670]),
        # Typed into an EMPTY box; "2025" is printed elsewhere on the page (the
        # edition footer). A page-wide "already in the text" test would drop it -
        # measured: it dropped "Prior Coverage Policy Year (A): 2025" on all three
        # of the owner's filled ACORD 125s.
        ("PriorCoverage_PolicyYear_A", "2025", [100, 600, 160, 620]),
        # A one-letter answer drawn in its own box still gets its labelled line:
        # the drawn "Y" says nothing without the question it answers.
        ("CommercialStructure_LeasedToOthersCode_A", "Y", [100, 550, 130, 570]),
    ])
    text = _extract(p)
    assert text.count("GRANITE PEAK CASUALTY COMPANY") == 1
    assert text.count("Inspection / Loss Control") == 1
    assert _blocks(text) == {1: ["Prior Coverage Policy Year (A): 2025",
                                 "Commercial Structure Leased To Others Code (A): Y"]}


# ===========================================================================
# 4. Every route a page can take gets its values exactly once
# ===========================================================================

def _build_scrambled_page_with_field(path):
    """tests/test_ocr_column_reflow.py's drifted two-column identity block, plus
    a filled field - the page goes through the column reflow."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    labels = ["Named Insured:", "Legal Entity:", "Mailing Address:", "FEIN:", "CARRIER:",
              "NAIC Code:", "Policy Number:", "Effective Date:", "Expiration Date:", "AGENCY:"]
    values = ["Summit Ridge Construction LLC", "Limited Liability Company (LLC)",
              "4820 Kettering Boulevard, Suite 210, Denver, CO 80216", "84-2210987",
              "Pinnacle Casualty Insurance Company", "38954", "GL-CO-778451",
              "04/01/2026", "04/01/2027", "Front Range Insurance Advisors"]
    base = path + ".base.pdf"
    c = canvas.Canvas(base, pagesize=letter)
    _w, height = letter
    c.setFont("Helvetica", 10)
    y = height - 100
    for label in labels:
        c.drawString(60, y, label)
        y -= 20
    y = height - 100
    for value in values:
        c.drawString(320, y, value)
        y -= 26
    c.save()
    with pikepdf.open(base) as pdf:
        pg = pdf.pages[0].obj
        f = _text_field(pdf, pg, "Applicant_TypedRemark_A", "Typed remark that only the field holds",
                        [60, 60, 500, 80])
        _finish(pdf, [f], path)


def test_the_column_reflow_route_gets_the_block_once(tmp_path, monkeypatch, vision):
    p = str(tmp_path / "reflow.pdf")
    _build_scrambled_page_with_field(p)
    accepted = []
    real = ocr_service._log_reflow_accept
    monkeypatch.setattr(ocr_service, "_log_reflow_accept",
                        lambda *a, **k: (accepted.append(1), real(*a, **k)))
    text = _extract(p)
    assert accepted, "the page did not take the reflow route"
    assert any("CARRIER" in ln and "Pinnacle" in ln for ln in text.splitlines())
    assert text.count("Typed remark that only the field holds") == 1
    assert _blocks(text) == {1: ["Applicant Typed Remark (A): Typed remark that only the field holds"]}


def test_a_scanned_page_sent_to_vision_gets_the_block_once(tmp_path, monkeypatch):
    """The page render draws the widgets, so Vision may already have read a value:
    then it is not repeated. A value it did not read, and every tick, is appended."""
    p = str(tmp_path / "scan.pdf")
    _base(p, [("scan", None)])
    with pikepdf.open(p, allow_overwriting_input=True) as pdf:
        pg = pdf.pages[0].obj
        fields = [
            _text_field(pdf, pg, "NamedInsured_FullName_A", "Harborline Plumbing", [100, 700, 400, 720]),
            _text_field(pdf, pg, "NamedInsured_MailingAddress_LineTwo_A", "Suite 400\nBuilding C",
                        [100, 650, 400, 690]),
            _text_field(pdf, pg, "Policy_PolicyNumberIdentifier_A", "GPC-2026-778", [100, 600, 400, 620]),
            _checkbox(pdf, pg, "Policy_Status_QuoteIndicator_A", "1", True, [100, 560, 110, 570]),
        ]
        _finish(pdf, fields, p)
    fv = _FakeVision("APPLICANT INFORMATION\nNAME Harborline Plumbing\nSuite 400\nBuilding C\n"
                     "printed form wording read from the rendered page image")
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())
    monkeypatch.setattr(ocr_service, "_vision_batch_call", fv)
    text = _extract(p)
    assert fv.payloads == 1, "the page must be OCR'd"
    assert "printed form wording read from the rendered page image" in text
    assert text.count("Harborline Plumbing") == 1
    assert text.count("Building C") == 1               # a typed line break, read by OCR
    assert _blocks(text) == {1: ["Policy Policy Number Identifier (A): GPC-2026-778",
                                 "Policy Status Quote Indicator (A): ticked"]}


def test_a_mixed_pdf_gives_each_page_its_own_block_once(tmp_path, monkeypatch):
    """Native page, scanned page, native page with an embedded image."""
    p = str(tmp_path / "mixed.pdf")
    _base(p, [("text", "ALPHA PAGE. " + BODY * 6), ("scan", None),
              ("text+image", "GAMMA PAGE. " + BODY * 6)])
    with pikepdf.open(p, allow_overwriting_input=True) as pdf:
        fields = [
            _text_field(pdf, pdf.pages[0].obj, "Field_Alpha_A", "alpha typed value", [40, 740, 300, 760]),
            _text_field(pdf, pdf.pages[1].obj, "Field_Beta_A", "beta typed value", [40, 740, 300, 760]),
            _text_field(pdf, pdf.pages[2].obj, "Field_Gamma_A", "gamma typed value", [300, 700, 560, 720]),
        ]
        _finish(pdf, fields, p)
    fv = _FakeVision("OCRTEXT read by the stub for every image it is handed")
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())
    monkeypatch.setattr(ocr_service, "_vision_batch_call", fv)
    text = _extract(p)
    assert fv.payloads == 2, "the scanned page and the embedded image are OCR'd"
    assert _blocks(text) == {1: ["Field Alpha (A): alpha typed value"],
                             2: ["Field Beta (A): beta typed value"],
                             3: ["Field Gamma (A): gamma typed value"]}
    for page, word in ((1, "alpha"), (2, "beta"), (3, "gamma")):
        assert text.count(f"{word} typed value") == 1
        start = text.index(f"[Document page {page}]")
        end = text.index(f"[Document page {page + 1}]") if page < 3 else len(text)
        assert start < text.index(f"[Filled form fields - page {page}]") < end
    # The image block stays with its page, ahead of that page's field block.
    assert text.index("[Embedded image text - page 3]") < text.index("[Filled form fields - page 3]")


def test_a_page_holding_only_fields_gets_a_marker_and_its_block(tmp_path, vision):
    """A page with no printed text at all. PyMuPDF's text layer DOES include widget
    text, so `_page_is_blank` says no and the page goes to Vision exactly as it did
    before this fix; the stub reads nothing, so the block carries the value."""
    p = str(tmp_path / "fields_only.pdf")
    _base(p, [("text", BODY * 6), ("text", BODY * 6)])
    with pikepdf.open(p, allow_overwriting_input=True) as pdf:
        pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
        f = _text_field(pdf, pdf.pages[2].obj, "Applicant_Remark_A", "only on page three",
                        [40, 700, 300, 720])
        _finish(pdf, [f], p)
    text = _extract(p)
    assert "[Document page 3]\n[Filled form fields - page 3]\nApplicant Remark (A): only on page three" in text
    assert vision.payloads == 1


# ===========================================================================
# 5. What a field holds and how it reads
# ===========================================================================

def _read_one_page(path):
    fields = fft.read_filled_fields(path)
    return [f.line for f in fields.get(0, [])]


def test_checkbox_export_values_read_ticked(tmp_path):
    p = str(tmp_path / "boxes.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    fields = [
        _checkbox(pdf, pg, "Coverage_Property_A", "1", True, [40, 700, 50, 710]),
        _checkbox(pdf, pg, "Coverage_Liability_A", "Yes", True, [40, 680, 50, 690]),
        _checkbox(pdf, pg, "Coverage_Crime_A", "On", True, [40, 660, 50, 670]),
        _checkbox(pdf, pg, "Coverage_Auto_A", "X", False, [40, 640, 50, 650]),
        # Some writers set only the widget's appearance state.
        _checkbox(pdf, pg, "Coverage_Umbrella_A", "1", True, [40, 620, 50, 630], set_v=False),
        # An ACORD Y/N checkbox pair: the tick IS the answer.
        _checkbox(pdf, pg, "CommercialPolicy_Question_AADYesIndicator_A", "1", False, [40, 600, 50, 610],
                  tu='Check the box (if applicable): Indicates a "Yes" response to the question, '
                     '"Any other insurance with this company?".'),
        _checkbox(pdf, pg, "CommercialPolicy_Question_AADNoIndicator_A", "1", True, [60, 600, 70, 610],
                  tu='Check the box (if applicable): Indicates a "No" response to the question, '
                     '"Any other insurance with this company?".'),
    ]
    _finish(pdf, fields, p)
    assert _read_one_page(p) == [
        "Coverage Property (A): ticked",
        "Coverage Liability (A): ticked",
        "Coverage Crime (A): ticked",
        "Coverage Umbrella (A): ticked",
        "Any other insurance with this company? (A): No",
    ]


def test_a_radio_group_reads_the_chosen_option(tmp_path):
    p = str(tmp_path / "radio.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj

    def group(name, chosen, options, kid_tooltips=None):
        parent = pdf.make_indirect(Dictionary(FT=Name.Btn, Ff=(1 << 15) | (1 << 14),
                                              T=String(name), V=Name(f"/{chosen}"), Kids=Array([])))
        for i, opt in enumerate(options):
            extra = {"AP": _ap_states(pdf, f"/{opt}", "/Off"),
                     "AS": Name(f"/{opt}") if opt == chosen else Name.Off, "Parent": parent}
            if kid_tooltips:
                extra["TU"] = String(kid_tooltips[i])
            parent.Kids.append(_widget(pdf, pg, [40 + 30 * i, 700 - 40 * len(parent.Kids), 50 + 30 * i,
                                                 710 - 40 * len(parent.Kids)], **extra))
        return parent

    fields = [
        group("NamedInsured_LegalEntityType_A", "LLC", ["Corporation", "LLC", "Partnership"]),
        # Opaque export values: the chosen widget's own tooltip names the option.
        group("NamedInsured_BusinessType_A", "1", ["0", "1"],
              kid_tooltips=["Check the box: Contractor", "Check the box: Manufacturer"]),
    ]
    _finish(pdf, fields, p)
    assert _read_one_page(p) == [
        "Named Insured Legal Entity Type (A): LLC",
        "Named Insured Business Type (A): Manufacturer",
    ]


def test_values_are_inherited_from_the_parent_field(tmp_path):
    p = str(tmp_path / "inherit.pdf")
    pdf = Pdf.new()
    for _ in range(2):
        pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    applicant = pdf.make_indirect(Dictionary(T=String("Applicant"), Kids=Array([])))
    name = pdf.make_indirect(Dictionary(T=String("BusinessName"), FT=Name.Tx, Parent=applicant,
                                        V=String("Cascadia Mechanical Inc"),
                                        TU=String("Enter text: The applicant's legal name."),
                                        Kids=Array([])))
    applicant.Kids.append(name)
    for i in range(2):                                   # one field, a widget on each page
        name.Kids.append(_widget(pdf, pdf.pages[i].obj, [40, 700, 300, 720], Parent=name))
    _finish(pdf, [applicant], p)
    fields = fft.read_filled_fields(p)
    assert list(fields) == [0]
    assert [f.line for f in fields[0]] == ["Applicant Business Name: Cascadia Mechanical Inc"]


def test_hidden_empty_off_and_default_values_are_skipped(tmp_path):
    p = str(tmp_path / "skips.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    fields = [
        _text_field(pdf, pg, "Form_EditionIdentifier_A", "ACORD 0125 2025-03", [0, 0, 0, 0],
                    F=2, DV=String("ACORD 0125 2025-03")),                         # the ACORD shape
        _text_field(pdf, pg, "Hidden_Value_A", "hidden typed value", [40, 700, 300, 720], F=2 | 4),
        _text_field(pdf, pg, "NoView_Value_A", "noview typed value", [40, 670, 300, 690], F=32 | 4),
        _text_field(pdf, pg, "Empty_Value_A", "   ", [40, 640, 300, 660]),
        _text_field(pdf, pg, "Missing_Value_A", None, [40, 610, 300, 630]),
        # A visible default the form's author set: a blank template shows it too.
        _text_field(pdf, pg, "Form_Version_Text_A", "Version 2.1", [40, 580, 300, 600],
                    DV=String("Version 2.1")),
        _checkbox(pdf, pg, "Coverage_Off_A", "1", False, [40, 560, 50, 570]),
        _widget(pdf, pg, [40, 540, 100, 555], FT=Name.Sig, T=String("Applicant_Signature_A"),
                V=Dictionary(Type=Name.Sig)),
        # The one a person typed (it differs from its /DV).
        _text_field(pdf, pg, "Form_Version_Other_A", "Typed by the producer", [40, 500, 300, 520],
                    DV=String("Version 2.1")),
    ]
    _finish(pdf, fields, p)
    assert _read_one_page(p) == ["Form Version Other (A): Typed by the producer"]


def test_labels_from_tooltips_and_names():
    # An opaque name: the tooltip's first sentence, prefix removed.
    assert fft.field_label("Enter text: The applicant's legal name. As used here, the insured.",
                           "Text1") == "The applicant's legal name"
    assert fft.field_label("Check the box (if applicable): Indicates the building is sprinklered.",
                           "topmostSubform[0].Page1[0].c1_01[0]") == "Indicates the building is sprinklered"
    # A name that names the box wins over the tooltip; ACORD's "As used here" rides along.
    assert fft.field_label("Enter date: The expiration date of the policy. As used here, this is "
                           "the proposed expiration date.", "Policy_ExpirationDate_A") == \
        "Policy Expiration Date (A) - this is the proposed expiration date"
    # A Y/N question box: the question.
    assert fft.field_label('Enter Y for a "Yes" response. Input N for "No" response. Indicates the '
                           'response to the question, "Any uncorrected fire code violations?".',
                           "CommercialPolicy_Question_AAFCode_A") == \
        "Any uncorrected fire code violations? (A)"
    # Capped short.
    assert len(fft.field_label("Enter text: " + "word " * 80, "f1_01")) <= 120
    # Nothing at all.
    assert fft.field_label("", "") == "Form field"
    # A dotted name keeps its parents - the applicant's name is not the producer's -
    # minus the authoring tool's tree.
    assert fft.field_label("", "Applicant.Name") == "Applicant Name"
    assert fft.field_label("", "Producer.Name") == "Producer Name"
    assert fft.field_label("", "topmostSubform[0].Page1[0].Applicant[0].Name[0]") == "Applicant Name"
    assert fft.field_label("Enter text: The insured's city.",
                           "form1[0].#subform[0].f1_07[0]") == "The insured's city"


def test_a_choice_field_reads_its_display_text(tmp_path):
    p = str(tmp_path / "choice.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    opts = Array([Array([String("CO"), String("Colorado")]), Array([String("WA"), String("Washington")])])
    fields = [
        _widget(pdf, pg, [40, 700, 300, 720], FT=Name.Ch, T=String("NamedInsured_State_A"),
                Opt=opts, V=String("WA")),
        _widget(pdf, pg, [40, 660, 300, 690], FT=Name.Ch, T=String("Coverage_LinesRequested_A"),
                Ff=1 << 21, Opt=Array([String("Property"), String("Crime"), String("Auto")]),
                V=Array([String("Property"), String("Auto")])),
    ]
    _finish(pdf, fields, p)
    assert _read_one_page(p) == ["Named Insured State (A): Washington",
                                 "Coverage Lines Requested (A): Property; Auto"]


# Display rotation R (clockwise): a point in the displayed page (origin bottom-left)
# back in PDF user space - worked out from the PDF spec, independently of
# form_field_text's own transform, so the two cannot agree by sharing a bug.
_TM = {0: (1, 0, 0, 1), 90: (0, 1, -1, 0), 180: (-1, 0, 0, -1), 270: (0, -1, 1, 0)}


def _to_user(rot, mb, px, py):
    x0, y0, x1, y1 = mb
    return {0: (px + x0, py + y0), 90: (x1 - py, px + y0),
            180: (x1 - px, y1 - py), 270: (py + x0, y1 - px)}[rot]


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("mb", [[0, 0, 612, 792], [30, 40, 642, 832], [-50, -60, 562, 732]])
def test_the_drawn_check_holds_on_rotated_and_offset_pages(tmp_path, rot, mb):
    """The value is drawn so it DISPLAYS upright inside the widget's box; the
    widget /Rect is that box in user space. Drawn elsewhere, it is not "in the box"."""
    value = "HARBORLINE TEST VALUE"
    box = (100, 300, 400, 318)                           # displayed frame
    a, b, c, d = _TM[rot]
    for where, at in (("inside", (104, 305)), ("outside", (100, 100))):
        p = str(tmp_path / f"rot{rot}_{where}.pdf")
        pdf = Pdf.new()
        font = pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1,
                                            BaseFont=Name.Helvetica))
        ux, uy = _to_user(rot, mb, *at)
        content = f"BT /F1 9 Tf {a} {b} {c} {d} {ux:.2f} {uy:.2f} Tm ({value}) Tj ET".encode()
        pdf.pages.append(pikepdf.Page(Dictionary(
            Type=Name.Page, MediaBox=Array(mb), Rotate=rot,
            Resources=Dictionary(Font=Dictionary(F1=font)), Contents=pdf.make_stream(content))))
        corners = [_to_user(rot, mb, x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        rect = [min(q[0] for q in corners), min(q[1] for q in corners),
                max(q[0] for q in corners), max(q[1] for q in corners)]
        f = _text_field(pdf, pdf.pages[0].obj, "Applicant_FullName_A", value, rect)
        _finish(pdf, [f], p)
        import pdfplumber
        with pdfplumber.open(p) as pl:
            text = pl.pages[0].extract_text() or ""
        assert value in text                             # upright in pdfplumber's frame
        found = fft.read_filled_fields(p, [text])[0][0]
        assert found.drawn is (where == "inside"), (rot, mb, where, found.bbox)


# ===========================================================================
# 6. Never crash OCR: encrypted, broken, cyclic, huge
# ===========================================================================

def test_broken_and_encrypted_pdfs_fail_open(tmp_path, vision):
    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"%PDF-1.7\n this is not a pdf at all \n%%EOF")
    assert fft.read_filled_fields(str(garbage)) == {}
    assert _extract(str(garbage)) == ""

    filled = str(tmp_path / "filled.pdf")
    _fill_template(os.path.join(TEMPLATES, "ACORD_25.pdf"), filled,
                   {"NamedInsured_FullName_A": "Harborline Plumbing & Mechanical, LLC"})
    data = open(filled, "rb").read()
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(data[: len(data) // 2])
    fft.read_filled_fields(str(truncated))                 # must not raise
    _extract(str(truncated))                               # must not raise

    locked = str(tmp_path / "locked.pdf")
    with pikepdf.open(filled) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="secret", owner="owner"))
    assert fft.read_filled_fields(locked) == {}
    _extract(locked)                                       # must not raise

    # Owner-password only: opens without a password, so the values are read.
    owner_only = str(tmp_path / "owner_only.pdf")
    with pikepdf.open(filled) as pdf:
        pdf.save(owner_only, encryption=pikepdf.Encryption(user="", owner="owner"))
    assert "Harborline Plumbing & Mechanical, LLC" in _extract(owner_only)


def test_a_parent_cycle_does_not_hang(tmp_path):
    p = str(tmp_path / "cycle.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    a = pdf.make_indirect(Dictionary(Kids=Array([])))
    b = pdf.make_indirect(Dictionary(Parent=a, Kids=Array([])))
    a.Parent = b                                         # a <-> b
    w = _widget(pdf, pg, [40, 700, 300, 720], Parent=b)
    b.Kids.append(w)
    _finish(pdf, [a], p)
    assert fft.read_filled_fields(p) == {}


def test_a_failing_reader_or_block_leaves_the_old_text(tmp_path, monkeypatch, vision, acord_125_texts):
    blank, _filled, dst = acord_125_texts

    def boom(*_a, **_k):
        raise RuntimeError("simulated")

    with monkeypatch.context() as m:
        m.setattr(ocr_service, "read_filled_fields", boom)
        assert _extract(dst) == blank
    with monkeypatch.context() as m:
        m.setattr(ocr_service, "form_field_block", boom)
        assert _extract(dst) == blank


def test_a_compressed_value_bomb_is_never_inflated(tmp_path):
    """A field's /V may be a Flate stream, and nothing else in the pipeline ever
    decodes it. 60 KB on disk, 60 MB decoded: read at most 4 x the value cap.
    Measured before the bound: a 200 MB stream took the read to ~420 MB."""
    import tracemalloc
    import zlib
    import pdfplumber  # noqa: F401 - import cost outside the measurement
    p = str(tmp_path / "bomb.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    st = pikepdf.Stream(pdf, zlib.compress(b"A" * (60 * 1024 * 1024), 9))
    st.Filter = Name.FlateDecode
    f = _widget(pdf, pg, [40, 700, 300, 720], FT=Name.Tx, T=String("Remarks_A"), V=st)
    _finish(pdf, [f], p)
    assert os.path.getsize(p) < 200_000
    tracemalloc.start()
    try:
        found = fft.read_filled_fields(p)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 40 * 1024 * 1024, peak
    value = found[0][0].value
    assert value.startswith("AAAA") and len(value) <= fft._VALUE_MAX_CHARS


def test_the_fullest_real_page_fits_the_page_cap(tmp_path):
    """ACORD 160 page 4 has 392 boxes - every one filled is the most a real form
    page can hold. None may be left out (the first cut capped pages at 24,000
    characters and dropped 121 of them)."""
    src = os.path.join(TEMPLATES, "ACORD_160.pdf")
    dst = str(tmp_path / "ACORD_160_ALL.pdf")
    n = 0
    with pikepdf.open(src) as pdf:
        for w in pdf.pages[3].obj.Annots:
            field = w if "/T" in w else w.Parent
            if str(fft._inherited(field, "/FT")) == "/Tx":
                n += 1
                field.V = String(f"Sample typed value number {n:04d}, forty chars")
            elif str(fft._inherited(field, "/FT")) == "/Btn" and "/AP" in w:
                on = next(str(k) for k in w.AP.N.keys() if str(k) != "/Off")
                field.V = Name(on)
                w.AS = Name(on)
        pdf.Root.AcroForm.NeedAppearances = True
        pdf.save(dst)
    page4 = fft.read_filled_fields(dst)[3]
    assert len(page4) >= 380
    block = fft.form_field_block(page4, 4)
    assert "more filled form field(s)" not in block
    assert block.count("\n") == len(page4)


def test_the_document_cap_keeps_the_first_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(fft, "_DOC_MAX_CHARS", 6_000)
    p = str(tmp_path / "doc_cap.pdf")
    pdf = Pdf.new()
    fields = []
    for i in range(3):
        pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
        for j in range(20):
            fields.append(_text_field(pdf, pdf.pages[i].obj, f"Page{i}_Value_{j:02d}", "v" * 100,
                                      [40, 700 - 20 * j, 560, 715 - 20 * j]))
    _finish(pdf, fields, p)
    found = fft.read_filled_fields(p)
    assert len(found[0]) == 20                            # page 1 whole
    assert sum(len(v) for v in found.values()) < 60
    assert sum(len(f.line) + 1 for v in found.values() for f in v) <= 6_000


def test_a_runaway_value_is_cut_and_the_page_block_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(fft, "_PAGE_MAX_CHARS", 2_000)
    p = str(tmp_path / "huge.pdf")
    pdf = Pdf.new()
    pdf.pages.append(pikepdf.Page(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, 612, 792]))))
    pg = pdf.pages[0].obj
    fields = [_text_field(pdf, pg, "Remarks_Runaway_A", "x " * 2_000_000, [40, 700, 560, 760])]
    fields += [_text_field(pdf, pg, f"Remarks_Line_{i:02d}", "y" * 300, [40, 600 - 10 * i, 560, 608 - 10 * i])
               for i in range(20)]
    _finish(pdf, fields, p)
    found = fft.read_filled_fields(p)[0]
    assert len(found[0].value) <= fft._VALUE_MAX_CHARS and found[0].value.endswith("...")
    block = fft.form_field_block(found, 1)
    body = block.split("\n", 1)[1]
    assert len(body) <= 2_000 + 80
    assert re.search(r"^\[\d+ more filled form field\(s\) on this page not shown\]$", block, re.M)
    # A page whose ONLY field is over the cap still says so - never a silent drop.
    assert fft.form_field_block(found[:1], 1) == (
        "[Filled form fields - page 1]\n[1 more filled form field(s) on this page not shown]")
