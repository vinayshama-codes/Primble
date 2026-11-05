"""The applicant's e-signature on ACORD Solutions forms (owner, 4 Nov 2026 - was D-ASG-10).

The applicant signs through Send to Client, exactly as on our 17 forms. The lines are read off the printed form
the same way (an applicant SIGNATURE box whose own printed cell label says SIGNATURE, its date paired by row),
from the package's own stored copy - never an ASG call. The producer's saved signature still goes only on the
producer's boxes; it is never put on the applicant's line.
"""
import base64
import io
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

import services.applicant_signing as asg
import services.asg_forms as A
import services.signature_boxes as sb

STUB = Path(__file__).resolve().parent / "fixtures" / "asg_forms_stub"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no ASG call may be made")
    monkeypatch.setattr(A, "_network_fetch", boom, raising=False)
    sb._asg_lines.clear()


@pytest.fixture
def key(monkeypatch):
    from cryptography.fernet import Fernet
    import utils.crypto as crypto
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    yield
    crypto._fernet = None


def _png():
    im = Image.new("RGB", (440, 140), (255, 255, 255))
    for x in range(60, 300):
        for dy in range(3):
            im.putpixel((x, 60 + (x % 20) + dy), (15, 23, 42))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _schema_of(blank):
    pdf = pikepdf.open(io.BytesIO(blank))
    return {name: {"tu": tu, "ft": ft} for _pi, name, tu, ft, _r in sb._widgets(pdf)}


def _asg_record(form_id, stub_file, values=None):
    blank = (STUB / stub_file).read_bytes()
    values = dict(values or {"NamedInsured_FullName_A": "Orbin Contracting LLC"})
    return {"form": dict(A.meta_for(form_id)), A.STORED_BASE_KEY: A.values_only_copy(blank, values),
            "field_state": values, "mapped": dict(values), "confidence": {}, "schema": _schema_of(blank)}


def _signed(rec, form_id, **extra):
    from utils.crypto import encrypt_field
    rec.update(extra)
    rec[sb.APPLICANT_SIGNATURE_KEY] = {"request_id": "r1", "signed_date": "11/04/2026", "signer_name": "Erin Royal",
                                       "fingerprint": sb.form_fingerprint(rec["field_state"], rec["schema"])}
    return {"generated_forms": {form_id: rec},
            sb.APPLICANT_IMAGES_KEY: {"r1": encrypt_field(asg.normalize_signature_image(_png()))}}


def _fields(pdf_bytes):
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    out = {}
    for f in sb._walk_fields(pdf.Root.AcroForm.get("/Fields", [])):
        if f.get("/T") is not None:
            out[str(f.get("/T"))] = str(f.get("/V")) if f.get("/V") is not None else None
    images = sum(1 for p in pdf.pages for k in (p.Resources.get("/XObject") or {}).keys() if str(k).startswith("/SigImg"))
    return out, images


EXPECTED_137_TX = [{"signature": "NamedInsured_Signature_B", "date": "NamedInsured_SignatureDate_B"},
                   {"signature": "NamedInsured_Signature_C", "date": "NamedInsured_SignatureDate_C"},
                   {"signature": "NamedInsured_Signature_A", "date": "NamedInsured_SignatureDate_A"}]


def test_an_asg_forms_applicant_lines_are_read_off_its_stored_copy():
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    assert sb.applicant_lines_for(rec) == EXPECTED_137_TX
    # the same answer the file reader gives for the same printed form
    assert [{"signature": s, "date": d} for s, d in sb._read_applicant_lines((STUB / "137_TX.pdf").read_bytes())] \
        == EXPECTED_137_TX


def test_a_form_the_applicant_does_not_sign_has_no_lines():
    assert sb.applicant_lines_for(_asg_record("ACORD_27", "27.pdf")) == []        # producer signs 27 only


def test_no_stored_copy_means_no_lines_and_no_asg_call():
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    rec.pop(A.STORED_BASE_KEY)
    assert sb.applicant_lines_for(rec) == []


def test_the_lines_are_read_once_per_stored_copy(monkeypatch):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    calls = []
    real = sb._read_applicant_lines
    monkeypatch.setattr(sb, "_read_applicant_lines", lambda t: calls.append(1) or real(t))
    sb.applicant_lines_for(rec)
    sb.applicant_lines_for(rec)
    assert len(calls) == 1


def test_send_to_client_offers_the_signature_for_an_asg_form():
    sess = {"generated_forms": {"ACORD_137_TX": _asg_record("ACORD_137_TX", "137_TX.pdf"),
                                "ACORD_27": _asg_record("ACORD_27", "27.pdf")},
            "selected_form_ids": ["ACORD_137_TX", "ACORD_27"]}
    assert asg.signable_form_ids(sess) == ["ACORD_137_TX"]
    q = asg.signature_question(sess)
    assert q and q["form_ids"] == ["ACORD_137_TX"] and "ACORD 137 TX" in q["hint"]


def test_the_applicant_signs_and_dates_an_asg_form_and_nothing_else(key):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    sess = _signed(rec, "ACORD_137_TX")
    pdf = sb.regenerate_pdf_for_form(sess, "ACORD_137_TX", force=True)
    fields, images = _fields(pdf)
    for line in EXPECTED_137_TX:
        assert line["signature"] not in fields, line                       # painted
        assert fields.get(line["date"]) == "11/04/2026", line              # dated
    assert images >= 3
    for name in ("Producer_AuthorizedRepresentative_Signature_A", "Producer_AuthorizedRepresentative_Signature_B",
                 "Producer_AuthorizedRepresentative_Signature_C"):
        assert name in fields                                              # the producer has not signed
    for name in ("NamedInsured_Initials_A", "NamedInsured_Initials_B", "NamedInsured_Initials_C"):
        assert name in fields and not fields[name]                         # initials stay the applicant's choice
    assert fields.get("NamedInsured_FullName_A") == "Orbin Contracting LLC"
    assert not any(k.startswith("__primble_hold_") for k in fields)
    assert sb.regenerate_pdf_for_form(sess, "ACORD_137_TX") is rec["pdf_bytes"]  # cached


def test_both_parties_sign_an_asg_form(key):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    sess = _signed(rec, "ACORD_137_TX", signature_applied=True,
                   signature_b64=asg.normalize_signature_image(_png()))
    fields, images = _fields(sb.regenerate_pdf_for_form(sess, "ACORD_137_TX", force=True))
    assert "NamedInsured_Signature_A" not in fields
    assert "Producer_AuthorizedRepresentative_Signature_A" not in fields
    assert fields["NamedInsured_SignatureDate_A"] == "11/04/2026"
    assert images >= 6
    assert rec["signature_scope"] == sb.SIGNATURE_SCOPE


def test_the_producers_saved_signature_never_goes_on_the_applicants_line(key):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    rec.update(signature_applied=True, signature_b64=asg.normalize_signature_image(_png()))
    fields, _ = _fields(sb.regenerate_pdf_for_form({"generated_forms": {"ACORD_137_TX": rec}}, "ACORD_137_TX",
                                                   force=True))
    assert "Producer_AuthorizedRepresentative_Signature_A" not in fields   # the producer's box is painted
    for line in EXPECTED_137_TX:
        assert line["signature"] in fields and not fields.get(line["date"])  # the applicant's lines untouched


def test_a_changed_asg_form_loses_the_applicants_signature(key):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    sess = _signed(rec, "ACORD_137_TX")
    sb.regenerate_pdf_for_form(sess, "ACORD_137_TX", force=True)
    rec["field_state"]["NamedInsured_FullName_A"] = "Someone Else LLC"
    assert sb.applicant_signature_for(sess, "ACORD_137_TX") is None
    fields, _ = _fields(sb.regenerate_pdf_for_form(sess, "ACORD_137_TX"))
    assert "NamedInsured_Signature_A" in fields and not fields.get("NamedInsured_SignatureDate_A")


def test_the_editor_no_longer_says_the_signature_is_not_added():
    jsx = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "form" / "AcordModal.jsx") \
        .read_text(encoding="utf-8")
    assert "e-signature is not added" not in jsx
    assert 'carries a "Sample" watermark' in jsx                             # the test-copy warning stays


# ── The painter must not GUESS the page's drawing scale (live run, 4 Nov 2026) ──────────────────────────────────────
# Production pages start with OUR highlight overlay ("q ... re f ... Q"); with many highlighted boxes the template's
# "0.12 0 0 0.12 0 0 cm" sat past the 500 bytes the old guess read, so it assumed no scale while the page ended at
# x0.12: signatures drawn at 1/8 size in the corner - invisible on 137 TX pages 1 and 3, in the viewer AND the
# download. Our test stub opens with the cm, so the first tests passed. These build the real shape.

def _with_long_highlight_prefix(pdf_bytes, rects=40):
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    for page in pdf.pages:
        lines = ["q"] + [f"1.000 0.840 0.670 rg\n{100 + i}.00 {200 + i}.00 30.00 12.00 re f" for i in range(rects)] + ["Q"]
        prefix = pdf.make_indirect(pikepdf.Stream(pdf, ("\n".join(lines) + "\n").encode()))
        c = page.obj.get("/Contents")
        parts = list(c) if isinstance(c, pikepdf.Array) else [c]
        page.obj["/Contents"] = pikepdf.Array([prefix] + [p if p.is_indirect else pdf.make_indirect(p) for p in parts])
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def _widget_rects(pdf_bytes, names):
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    out = {}
    for pi, name, _tu, _ft, rect in sb._widgets(pdf):
        if name in names:
            out[name] = (pi, rect)
    return out


def _image_boxes(pdf_bytes):
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for pi, page in enumerate(doc):
        h = page.rect.height
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            out.append((pi, (x0, h - y1, x1, h - y0)))          # back to PDF space (origin bottom-left)
    return out


@pytest.mark.parametrize("form_id, stub", [("ACORD_137_TX", "137_TX.pdf"), ("ACORD_27", "27.pdf")])
def test_a_signature_lands_on_its_box_whatever_the_page_starts_with(form_id, stub):
    from services.pdf_service import inject_signature_into_pdf
    blank = (STUB / stub).read_bytes()
    shaped = _with_long_highlight_prefix(blank)
    boxes = {n: v for n, v in _widget_rects(shaped, set(_schema_of(blank))).items()
             if sb.is_producer_signature(n, _schema_of(blank)[n]["tu"], _schema_of(blank)[n]["ft"])}
    assert boxes
    painted = inject_signature_into_pdf(shaped, {}, {}, asg.normalize_signature_image(_png()), shaped)
    images = _image_boxes(painted)
    for name, (pi, (x0, y0, x1, y1)) in boxes.items():
        hit = [b for p, b in images if p == pi and b[0] >= x0 - 1 and b[2] <= x1 + 1 and b[1] >= y0 - 1 and b[3] <= y1 + 1
               and (b[2] - b[0]) >= 0.3 * (x1 - x0)]
        assert hit, f"{name}: no full-size signature inside its box on page {pi + 1}; images {images}"


def test_the_signed_asg_form_shows_every_signature_after_a_highlighted_fill(key):
    rec = _asg_record("ACORD_137_TX", "137_TX.pdf")
    sess = _signed(rec, "ACORD_137_TX", signature_applied=True,
                   signature_b64=asg.normalize_signature_image(_png()))
    import services.pdf_service as ps
    real_fill = ps.fill_pdf
    try:
        ps.fill_pdf = lambda t, d, c=None: _with_long_highlight_prefix(real_fill(t, d, c))
        pdf = sb.regenerate_pdf_for_form(sess, "ACORD_137_TX", force=True)
    finally:
        ps.fill_pdf = real_fill
    images = _image_boxes(pdf)
    small = [b for _p, b in images if (b[2] - b[0]) < 20]
    assert len(images) >= 6 and not small, images             # three applicant + three producer, none shrunk


def test_the_draft_watermark_crosses_the_page():
    import fitz
    from services.pdf_service import apply_draft_watermark, fill_pdf
    from config.settings import TEMPLATE_DIR
    import os
    out = apply_draft_watermark(_with_long_highlight_prefix(fill_pdf(os.path.join(TEMPLATE_DIR, "ACORD_125.pdf"), {}, {})))
    page = fitz.open(stream=out, filetype="pdf")[0]
    words = [w for w in page.get_text("words") if "DRAFT" in w[4]]
    assert words and (words[0][2] - words[0][0]) > 100, words  # was a 19-point mark in the bottom-left corner


def test_the_signed_pdf_cache_version_moved():
    assert sb.SIGNATURE_SCOPE != sb.SIGNER_PRODUCER              # every signed PDF cached before 4 Nov is repainted


# ── The label printed to the LEFT of the line (live run, 4 Nov 2026: ACORD 60 was never offered for signing) ────────

def _left_label_form(label="Applicant's Signature", other_text=None):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 7)
    c.drawString(90, 146, label)
    c.drawString(410, 146, "Date")
    if other_text:
        c.drawString(90, 300, other_text)
    c.acroForm.textfield(name="NamedInsured_Signature_A", x=184, y=144, width=219, height=12, borderWidth=0,
                         tooltip="Sign here: Accommodates the signature of the applicant or named insured.")
    c.acroForm.textfield(name="NamedInsured_SignatureDate_A", x=432, y=144, width=86, height=12, borderWidth=0,
                         tooltip="Enter date: The date the form was signed by the named insured.")
    c.acroForm.textfield(name="NamedInsured_Signature_B", x=184, y=300, width=219, height=12, borderWidth=0,
                         tooltip="Sign here: Accommodates the signature of the applicant or named insured.")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_a_line_whose_label_is_printed_to_its_left_is_signed():
    lines = sb._read_applicant_lines(_left_label_form())
    assert lines == (("NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"),)   # B has no label: never signed


def test_a_left_label_that_is_not_a_signature_label_is_not_a_line():
    assert sb._read_applicant_lines(_left_label_form(label="I further attest that I have no employees")) == ()


def test_a_left_label_inside_a_paragraph_is_not_a_line():
    # ACORD 130's attestation shape: "(Applicant's Signature):" to the left AND sentence text right above the box.
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 7)
    c.drawString(184, 160, "I further attest that I have no employees and an estimated exposure of zero")
    c.drawString(110, 146, "(Applicant's Signature):")
    c.acroForm.textfield(name="NamedInsured_Signature_A", x=184, y=144, width=219, height=12, borderWidth=0,
                         tooltip="Sign here: Accommodates the signature of the applicant or named insured.")
    c.showPage()
    c.save()
    assert sb._read_applicant_lines(buf.getvalue()) == ()


# ── ACORD 97 SC (proof download, 4 Nov 2026): label UNDER the line, and signature TIME boxes ──────────────────────

def _label_below_form(with_paragraph_above=False):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 7)
    c.drawString(135, 436, "APPLICANT'S SIGNATURE")              # printed under the line
    c.drawString(340, 436, "DATE (Mo./Day/Yr.) HOUR")
    c.drawString(135, 46, "PRODUCER'S SIGNATURE")
    if with_paragraph_above:
        c.drawString(25, 458, "I further attest that I have no employees")
    tip_sig = "Sign here: Accommodates the signature of the applicant or named insured."
    c.acroForm.textfield(name="NamedInsured_Signature_A", x=25, y=447, width=295, height=7, tooltip=tip_sig)
    c.acroForm.textfield(name="NamedInsured_SignatureDate_A", x=334, y=447, width=130, height=7,
                         tooltip="Enter date: The date the form was signed by the named insured.")
    c.acroForm.textfield(name="NamedInsured_SignatureTime_A", x=478, y=447, width=65, height=7,
                         tooltip="Enter time: The time the form was signed by the named insured.")
    c.acroForm.checkbox(name="NamedInsured_SignatureTimeAMIndicator_A", x=557, y=447, size=7,
                        tooltip="Check the box (if applicable): Indicates the time the form was signed is AM.")
    c.acroForm.textfield(name="Producer_AuthorizedRepresentative_Signature_A", x=25, y=57, width=295, height=7,
                         tooltip="Sign here: Accommodates the signature of the authorized representative.")
    c.acroForm.textfield(name="Producer_AuthorizedRepresentative_SignatureTime_A", x=478, y=57, width=65, height=7,
                         tooltip="Enter time: The time the producer signed the form.")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_a_label_printed_under_the_line_makes_it_an_applicant_line():
    assert sb._read_applicant_lines(_label_below_form()) == (("NamedInsured_Signature_A",
                                                               "NamedInsured_SignatureDate_A"),)


def test_a_line_inside_a_paragraph_is_still_never_signed_whatever_is_printed_under_it():
    assert sb._read_applicant_lines(_label_below_form(with_paragraph_above=True)) == ()


def test_signature_time_boxes_are_never_signatures_and_are_never_painted():
    assert sb.signature_box("NamedInsured_SignatureTime_A", "Enter time: The time the form was signed by the named "
                            "insured.") == ("time", "applicant")
    assert sb.signature_box("Producer_AuthorizedRepresentative_SignatureTimePMIndicator_A",
                            "Check the box (if applicable): Indicates the time the producer signed the form is PM."
                            )[0] == "time"
    pdf = _label_below_form()
    schema = _schema_of(pdf)
    assert sb.producer_signature_fields(list(schema), schema) == ["Producer_AuthorizedRepresentative_Signature_A"]
    painted = sb.inject_producer_signature(pdf, {}, {}, asg.normalize_signature_image(_png()), pdf)
    fields, images = _fields(painted)
    assert "Producer_AuthorizedRepresentative_Signature_A" not in fields          # painted
    for keep in ("Producer_AuthorizedRepresentative_SignatureTime_A", "NamedInsured_SignatureTime_A",
                 "NamedInsured_SignatureTimeAMIndicator_A", "NamedInsured_Signature_A"):
        assert keep in fields, keep                                              # never painted over
    assert images == 1


def test_the_other_symbol_box_never_holds_a_symbol_the_grid_prints():
    import services.pdf_service as ps
    mapped = {"Vehicle_BusinessAutoSymbol_OtherSymbolCode_A": "1",
              "Vehicle_BusinessAutoSymbol_OtherSymbolCode_B": "19",           # ISO 19: not on the grid - kept
              "Vehicle_BusinessAutoSymbol_OtherSymbolCode_C": "7, 8",
              "Vehicle_TruckersSymbol_OtherSymbolCode_A": "41",
              "Vehicle_GarageAndDealersSymbol_OtherSymbolCode_A": "5"}         # not a garage symbol - kept
    deterministic = {"Vehicle_BusinessAutoSymbol_OtherSymbolCode_E": "2"}      # never judged: not an AI value
    import json
    schema = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas" / "ACORD_137_CA_schema.json").read_text())
    blanked = ps._blank_grid_symbols_in_other_box({**mapped, **deterministic}, set(mapped), schema)
    # judged per ROW from the ticks the form prints there (review B, 4 Nov 2026): row A prints 1-4 and 7-9, so "1"
    # goes; row C (UM) prints 2, 3, 4, 6, 7, so "7, 8" stays (8 has no tick there); the truckers grid's row A prints
    # 41, so it goes; 19 and the garage "5" (no garage grid on 137) stay
    assert sorted(blanked) == ["Vehicle_BusinessAutoSymbol_OtherSymbolCode_A", "Vehicle_TruckersSymbol_OtherSymbolCode_A"]


def test_the_other_symbol_guard_keeps_company_symbols_and_clears_its_own_tick():
    import json
    import services.pdf_service as ps
    schema = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas" / "ACORD_137_CA_schema.json").read_text())
    m = {"Vehicle_BusinessAutoSymbol_OtherSymbolCode_A": "1", "Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_A": "Yes",
         "Vehicle_BusinessAutoSymbol_OtherSymbolCode_E": "2",       # towing row prints only 3 and 7: 2 belongs here
         "Vehicle_BusinessAutoSymbol_OtherSymbolCode_B": "7A",      # a company's own symbol
         "Vehicle_BusinessAutoSymbol_OtherSymbolCode_F": "Symbol 2 (company symbol S2)"}
    blanked = ps._blank_grid_symbols_in_other_box(m, set(m), schema)
    assert sorted(blanked) == ["Vehicle_BusinessAutoSymbol_OtherSymbolCode_A",
                               "Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_A"]
    assert m["Vehicle_BusinessAutoSymbol_OtherSymbolCode_E"] == "2" and m["Vehicle_BusinessAutoSymbol_OtherSymbolCode_B"] == "7A"


# ── review B (4 Nov 2026) ─────────────────────────────────────────────────────────────────────────────────────

def _attestation_form(with_date: bool, label_under: bool = False):
    """ACORD 130 2026/08's shape: an attestation paragraph, a BLANK line, then "(Applicant's Signature):" beside a
    box with no date. ACORD 60's shape is the same with its own date box on the row."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 7)
    c.drawString(40, 190, "MINNESOTA ZERO ESTIMATED EXPOSURE: I attest that I have no employees and an exposure of zero.")
    if label_under:
        c.drawString(230, 136, "(Applicant's Signature)")
    else:
        c.drawString(110, 146, "(Applicant's Signature):")
    c.acroForm.textfield(name="NamedInsured_Signature_A", x=200, y=144, width=200, height=10, borderWidth=0,
                         tooltip="Sign here: Accommodates the signature of the applicant or named insured.")
    if with_date:
        c.acroForm.textfield(name="NamedInsured_SignatureDate_A", x=420, y=144, width=80, height=10, borderWidth=0,
                             tooltip="Enter date: The date the form was signed by the named insured.")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize("label_under", [False, True])
def test_an_attestation_line_with_no_date_of_its_own_is_never_signed(label_under):
    assert sb._read_applicant_lines(_attestation_form(with_date=False, label_under=label_under)) == ()
    assert sb._read_applicant_lines(_attestation_form(with_date=True, label_under=label_under)) == (
        ("NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"),)


def test_only_a_signing_time_is_a_time_box():
    assert sb.signature_box("Policy_Status_EffectiveTime_A", "Enter time: The effective time of the policy.") is None
    assert sb.signature_box("CrimeInformation_BusinessHoursStartTime_A",
                            "Enter time: The time the business opens.") is None
    assert sb.is_applicant_step("NamedInsured_SignatureTime_A", "Enter time: The time the form was signed by the "
                                "named insured.")


def test_a_box_at_the_page_edge_does_not_wipe_out_the_other_lines():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 7)
    c.drawString(30, 316, "APPLICANT'S SIGNATURE")
    tip = "Sign here: Accommodates the signature of the applicant or named insured."
    c.acroForm.textfield(name="NamedInsured_Signature_B", x=0, y=200, width=150, height=10, borderWidth=0, tooltip=tip)
    c.acroForm.textfield(name="NamedInsured_Signature_A", x=30, y=300, width=200, height=10, borderWidth=0, tooltip=tip)
    c.acroForm.textfield(name="NamedInsured_SignatureDate_A", x=250, y=300, width=80, height=10, borderWidth=0,
                         tooltip="Enter date: The date the form was signed by the named insured.")
    c.showPage()
    c.save()
    assert sb._read_applicant_lines(buf.getvalue()) == (("NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"),)


def test_signing_reads_off_the_event_loop():
    import inspect
    import routes.applicant_sign_routes as r
    src = inspect.getsource(r.signature_status)
    assert "run_scoring(asg.form_statuses" in src
    for fn in (asg.sign, asg.finalize):
        assert "run_scoring(forms_to_sign" in inspect.getsource(fn)
