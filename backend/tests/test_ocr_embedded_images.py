"""Regression tests for per-page OCR routing and embedded-image recovery in
services.ocr_service.

Root cause being fixed: extract_text_from_pdf decided OCR at the DOCUMENT
level. Any PDF carrying >= 100 characters of native text skipped OCR entirely,
so a declarations page pasted in as an image inside an otherwise text-based PDF
was silently discarded - the uploaded file processed "successfully" with the
policy data missing.

The fix routes per page and splits into two paths:

  Path B (scan)      - page has no usable native text: render it and OCR it.
  Path A (text page) - page HAS native text: keep that text verbatim and
                       additionally OCR each embedded image from its own
                       stored raster, appending the result.

Path A must APPEND, never replace. Replacing would (a) downgrade exact native
text to ~98%-accurate OCR, (b) discard the two-column reflow recovery that runs
on the native layer, and (c) duplicate the entire page in the LLM input, since
utils.text_cleaner.clean_text de-duplicates paragraphs by exact MD5 and
full-page OCR text is never byte-identical to the native text it shadows.

These tests never call Google Vision. _vision_batch_call is stubbed so the
batching, page-routing, dedup, budget and assembly logic is exercised for real
while the network is not.

Run from backend/:
    python -m pytest tests/test_ocr_embedded_images.py -v
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402
import pytest  # noqa: E402

from services import ocr_service  # noqa: E402
from utils.text_cleaner import clean_text  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Vision provider
# ---------------------------------------------------------------------------

def _decode_dims(payload: bytes):
    try:
        pix = fitz.Pixmap(payload)
        return pix.width, pix.height
    except Exception:
        return (0, 0)


class FakeVision:
    """Stands in for _vision_batch_call, recording every batch it is handed."""

    def __init__(self, text_for=None, raise_for=None):
        self.batches = []          # list[list[bytes]] - one entry per API call
        self._text_for = text_for or (lambda w, h, p: f"OCRTEXT {w}x{h}")
        self._raise_for = raise_for or (lambda w, h, p: False)

    def __call__(self, payloads):
        self.batches.append(list(payloads))
        out = []
        for p in payloads:
            w, h = _decode_dims(p)
            if self._raise_for(w, h, p):
                raise RuntimeError("simulated Vision transport failure")
            text = self._text_for(w, h, p)
            out.append(
                ocr_service._OcrResult(
                    text=text, low_conf=[], total_tokens=max(1, len(text.split()))
                )
            )
        return out

    @property
    def call_count(self):
        return len(self.batches)

    @property
    def image_count(self):
        return sum(len(b) for b in self.batches)


class _PassThroughCB:
    """Minimal stand-in for circuitbreaker.CircuitBreaker.

    Defined locally rather than imported on purpose: tests/
    test_arq_acord125_missing_only.py installs a permanent sys.modules stub of
    `circuitbreaker` whose CircuitBreaker has neither .opened nor .call(), and
    never tears it down. Importing the real class here would therefore work in
    isolation and break in a full-suite run. These tests only need the two
    attributes ocr_service actually uses.
    """

    opened = False

    def __init__(self):
        self.calls = 0

    def call(self, fn, *args, **kwargs):
        self.calls += 1
        return fn(*args, **kwargs)


@pytest.fixture()
def fake_vision(monkeypatch):
    """Install a fake provider and a neutral circuit breaker for each test."""
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())
    fv = FakeVision()
    monkeypatch.setattr(ocr_service, "_vision_batch_call", fv)
    return fv


def install(monkeypatch, fv):
    """Same isolation as the fake_vision fixture, for a custom FakeVision."""
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())
    monkeypatch.setattr(ocr_service, "_vision_batch_call", fv)
    return fv


# ---------------------------------------------------------------------------
# PDF builders
# ---------------------------------------------------------------------------

BODY = "Declarations continued. Additional coverage terms and conditions apply. "


def _raster(w_pt, h_pt, dpi_scale=3.0, text=None):
    """A raster of a given displayed size, rendered above screen resolution."""
    d = fitz.open()
    p = d.new_page(width=w_pt, height=h_pt)
    p.draw_rect(fitz.Rect(0, 0, w_pt, h_pt), color=(0, 0, 0), fill=(1, 1, 1))
    if text:
        p.insert_text((4, 14), text, fontsize=6)
    pix = p.get_pixmap(matrix=fitz.Matrix(dpi_scale, dpi_scale))
    d.close()
    return pix


def build_text_page_with_image(path, img_w, img_h, *, dpi_scale=3.0, body_repeat=25):
    """One page: plenty of native text PLUS one embedded image."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 300, 560, 780), BODY * body_repeat, fontsize=9)
    page.insert_image(
        fitz.Rect(50, 50, 50 + img_w, 50 + img_h), pixmap=_raster(img_w, img_h, dpi_scale)
    )
    doc.save(path)
    doc.close()


def build_scanned_page(path, n_pages=1):
    """Pages with almost no native text - the classic scan."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((20, 30), f"p{i}", fontsize=8)          # < 100 chars
        page.draw_rect(fitz.Rect(10, 50, 290, 390), color=(0, 0, 0))
    doc.save(path)
    doc.close()


def build_blank_page(path):
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(path)
    doc.close()


def build_mixed_document(path):
    """page 0: text | page 1: scan | page 2: text + embedded image."""
    doc = fitz.open()
    p0 = doc.new_page(width=612, height=792)
    p0.insert_textbox(fitz.Rect(50, 50, 560, 700), "ALPHA PAGE. " + BODY * 20, fontsize=9)

    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((50, 50), "scan", fontsize=8)
    p1.draw_rect(fitz.Rect(20, 80, 590, 700), color=(0, 0, 0))

    p2 = doc.new_page(width=612, height=792)
    p2.insert_textbox(fitz.Rect(50, 300, 560, 760), "GAMMA PAGE. " + BODY * 20, fontsize=9)
    p2.insert_image(fitz.Rect(50, 50, 350, 250), pixmap=_raster(300, 200))
    doc.save(path)
    doc.close()


def build_repeated_logo(path, n_pages=5):
    """The same letterhead asset on every page, plus real text."""
    logo = _raster(160, 90)
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(
            fitz.Rect(50, 300, 560, 780), f"PAGE {i} CONTENT. " + BODY * 20, fontsize=9
        )
        page.insert_image(fitz.Rect(50, 50, 210, 140), pixmap=logo)
    doc.save(path)
    doc.close()


def run(path):
    return asyncio.run(ocr_service.extract_text_from_pdf(path))


# ===========================================================================
# The original bug
# ===========================================================================

def test_embedded_dec_page_image_is_recovered(tmp_path, fake_vision):
    """THE REPORTED BUG: a dec page embedded as an image inside a text PDF.

    Previously the document had >= 100 chars of native text, so OCR was skipped
    for the whole file and the image's contents never reached the pipeline.
    """
    p = str(tmp_path / "embedded.pdf")
    build_text_page_with_image(p, 300, 200)

    text, _ = run(p)

    assert fake_vision.call_count == 1, "the embedded image must be sent to OCR"
    assert "OCRTEXT" in text, "OCR text from the embedded image must reach the output"
    assert "Declarations continued" in text, "native text must still be present"


def test_small_embedded_image_is_recovered(tmp_path, fake_vision):
    """A 120x60pt image is 1.49% of a letter page.

    A 2%-of-page-area gate discards it, yet it is a perfectly normal size for a
    scanned endorsement snippet or signature block carrying policy data.
    """
    p = str(tmp_path / "small.pdf")
    build_text_page_with_image(p, 120, 60)

    text, _ = run(p)

    assert fake_vision.call_count == 1
    assert "OCRTEXT" in text


def test_native_text_is_never_replaced_on_a_text_page(tmp_path, monkeypatch):
    """Path A appends. It must not substitute OCR output for native text."""
    fv = FakeVision(text_for=lambda w, h, p: "IMAGE ONLY CONTENT")
    install(monkeypatch, fv)
    p = str(tmp_path / "append.pdf")
    build_text_page_with_image(p, 300, 200)

    text, _ = run(p)

    assert "Declarations continued" in text, "native text was destroyed"
    assert "IMAGE ONLY CONTENT" in text, "image text missing"
    assert text.index("Declarations continued") < text.index("IMAGE ONLY CONTENT"), \
        "the image block should follow its page's native text"


def test_embedded_image_text_survives_clean_text(tmp_path, fake_vision):
    """clean_text drops paragraphs under 10 chars and dedupes by MD5.

    The marker keeps the block inside the surrounding paragraph precisely so a
    short image result cannot be silently dropped downstream.
    """
    p = str(tmp_path / "cleaned.pdf")
    build_text_page_with_image(p, 300, 200)

    text, _ = run(p)
    cleaned = clean_text(text)

    assert "OCRTEXT" in cleaned, "image OCR text must survive clean_text()"


# ===========================================================================
# Searchable-scan guard (image already covered by a native OCR text layer)
# ===========================================================================

def _scan_rows(n, fs):
    return [f"Schedule row {i}: class 97047 payroll 1,250,000 premium 8,400" for i in range(n)]


def build_scan_page(path, *, rows, fs, ocr_layer, full_page=True, extra_native=()):
    """A scanned page image, optionally with an invisible OCR text layer over
    it (what every modern scanner emits) and/or unrelated native text.

    Rows are spread across the FULL height of the image, because that is what a
    real scanner's OCR layer looks like: it transcribes the whole page, not a
    band at the top. Clustering the fixture's rows in the top half would make
    it indistinguishable from a header block and would not test the guard.
    """
    rect = fitz.Rect(0, 0, 612, 792) if full_page else fitz.Rect(40, 40, 400, 300)
    top, bottom = 12.0, rect.height - 12.0
    step = (bottom - top) / max(1, len(rows))

    src = fitz.open()
    sp = src.new_page(width=rect.width, height=rect.height)
    for i, t in enumerate(rows):
        sp.insert_text((8, top + i * step), t, fontsize=fs)
    pix = sp.get_pixmap(matrix=fitz.Matrix(2, 2))
    src.close()

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(rect, pixmap=pix)

    writer = fitz.TextWriter(page.rect)
    wrote = False
    if ocr_layer:
        for i, t in enumerate(rows):
            writer.append((rect.x0 + 8, rect.y0 + top + i * step), t, fontsize=fs)
            wrote = True
    for pt, t, size in extra_native:
        writer.append(pt, t, fontsize=size)
        wrote = True
    if wrote:
        writer.write_text(page, render_mode=3)     # 3 = invisible, as scanners do
    if not full_page:
        page.insert_textbox(fitz.Rect(50, 340, 560, 780), "NARRATIVE BODY. " * 60, fontsize=9)
    doc.save(path)
    doc.close()


def test_searchable_scan_is_not_double_counted(tmp_path, fake_vision):
    """A scanner's searchable PDF carries the page bitmap AND an invisible text
    layer of the scanner's own OCR. OCR'ing the image too would emit every
    figure on the page twice, and clean_text cannot collapse it because the two
    OCR engines never agree byte-for-byte."""
    p = str(tmp_path / "searchable.pdf")
    build_scan_page(p, rows=_scan_rows(26, 10), fs=10, ocr_layer=True)

    text, _ = run(p)

    assert fake_vision.call_count == 0, "the covered page image must not be re-OCR'd"
    assert text.count("Schedule row 3:") == 1, "page content emitted more than once"


def test_small_font_ocr_layer_is_still_recognised(tmp_path, fake_vision):
    """A 6pt scanner layer has the lowest glyph coverage of any real searchable
    scan and is the closest case to the threshold."""
    p = str(tmp_path / "small_font.pdf")
    build_scan_page(p, rows=_scan_rows(40, 6), fs=6, ocr_layer=True)

    run(p)

    assert fake_vision.call_count == 0


def test_full_page_scan_with_bates_stamp_is_still_ocred(tmp_path, fake_vision):
    """THE DANGEROUS CASE. A full-page scan carrying only a Bates stamp or a
    CONFIDENTIAL banner already has 20+ native words inside the image's box.
    Suppressing OCR on a word count would discard the entire scan - exactly the
    silent data loss this change exists to eliminate."""
    p = str(tmp_path / "bates.pdf")
    build_scan_page(
        p, rows=_scan_rows(26, 10), fs=10, ocr_layer=False,
        extra_native=[
            ((50, 30), "RECEIVED 04/01/2026 BROKER COPY CONFIDENTIAL", 9),
            ((50, 770), "Do not distribute outside agency Page 1 of 3 Bates SR000142", 9),
        ],
    )

    text, _ = run(p)

    assert fake_vision.call_count == 1, "a stamped scan must still be OCR'd"
    assert "OCRTEXT" in text


def test_multi_line_native_header_does_not_suppress_scan_ocr(tmp_path, fake_vision):
    """Even a 14-line native header reaches only ~5% glyph coverage."""
    p = str(tmp_path / "header.pdf")
    build_scan_page(
        p, rows=_scan_rows(26, 10), fs=10, ocr_layer=False,
        extra_native=[((50, 25 + i * 13), f"Submission header {i} agency ref ABC-{i:03d}", 8)
                      for i in range(14)],
    )

    run(p)

    assert fake_vision.call_count == 1, "a native header must not suppress the scan"


def test_pasted_exhibit_with_its_own_ocr_layer_is_skipped(tmp_path, fake_vision):
    """The guard is about coverage of the image, not about page size."""
    p = str(tmp_path / "exhibit_layer.pdf")
    build_scan_page(p, rows=_scan_rows(10, 7), fs=7, ocr_layer=True, full_page=False)

    run(p)

    assert fake_vision.call_count == 0


def test_searchable_scan_whose_content_fills_only_part_of_the_page(tmp_path, fake_vision):
    """A scanned certificate whose content occupies the top half still carries
    a COMPLETE OCR layer over that content.

    Measuring band spread against the page would call this partial and re-OCR
    it, duplicating the page - which the old implementation never did. The
    spread is therefore measured against where the image actually has ink."""
    p = str(tmp_path / "partial_content.pdf")
    rows = _scan_rows(12, 9)

    src = fitz.open()
    sp = src.new_page(width=612, height=792)
    for i, t in enumerate(rows):                     # content in the top ~40%
        sp.insert_text((40, 30 + i * 24), t, fontsize=9)
    pix = sp.get_pixmap(matrix=fitz.Matrix(2, 2))
    src.close()

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pix)
    writer = fitz.TextWriter(page.rect)
    for i, t in enumerate(rows):
        writer.append((40, 30 + i * 24), t, fontsize=9)
    writer.write_text(page, render_mode=3)
    doc.save(p)
    doc.close()

    text, _ = run(p)

    assert fake_vision.call_count == 0, "a complete OCR layer must not be re-OCR'd"
    assert text.count("Schedule row 5:") == 1, "page content emitted more than once"


def test_partial_ocr_layer_over_a_full_page_scan_is_still_ocred(tmp_path, fake_vision):
    """The mirror case: the scan's content fills the page but the native layer
    transcribes only half of it. That half-transcription must not suppress OCR
    of the rest."""
    p = str(tmp_path / "partial_layer.pdf")
    rows = _scan_rows(20, 9)

    src = fitz.open()
    sp = src.new_page(width=612, height=792)
    for i, t in enumerate(rows):
        sp.insert_text((40, 30 + i * 36), t, fontsize=9)   # spans the page
    pix = sp.get_pixmap(matrix=fitz.Matrix(2, 2))
    src.close()

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pix)
    writer = fitz.TextWriter(page.rect)
    for i, t in enumerate(rows[:10]):                      # only the top half
        writer.append((40, 30 + i * 36), t, fontsize=9)
    writer.write_text(page, render_mode=3)
    doc.save(p)
    doc.close()

    run(p)

    assert fake_vision.call_count == 1, "an incomplete text layer must not suppress OCR"


def test_diagonal_watermark_does_not_suppress_scan_ocr(tmp_path, fake_vision):
    """A diagonal CONFIDENTIAL watermark spans the page vertically, so it
    reaches a high band spread while covering very little glyph area. This is
    the case that makes band spread alone unsafe and forces the AND with the
    area test - measured at 70% bands but only 5.4% area."""
    p = str(tmp_path / "watermark.pdf")
    build_scan_page(
        p, rows=_scan_rows(26, 10), fs=10, ocr_layer=False,
        extra_native=[((120 + i * 40, 200 + i * 55), f"CONFIDENTIAL COPY {i}", 14)
                      for i in range(9)],
    )

    run(p)

    assert fake_vision.call_count == 1, "a watermarked scan must still be OCR'd"


def test_half_page_native_layer_does_not_suppress_scan_ocr(tmp_path, fake_vision):
    """Native text covering only the top half of a scan is a header block, not
    a transcription of it. Skipping would discard the bottom half of the page."""
    p = str(tmp_path / "halfpage.pdf")
    build_scan_page(
        p, rows=_scan_rows(26, 10), fs=10, ocr_layer=False,
        extra_native=[((50, 40 + i * 14), f"Header line {i} agency ref ABC-{i:03d}", 9)
                      for i in range(20)],
    )

    run(p)

    assert fake_vision.call_count == 1


def test_native_text_coverage_returns_count_area_and_occupied_bands():
    bbox = fitz.Rect(0, 0, 100, 100)
    inside = [(10, 10, 20, 20), (30, 30, 40, 40)]      # 100 + 100 of 10000
    outside = [(500, 500, 510, 510)]
    count, ratio, bands = ocr_service._native_text_coverage(bbox, inside + outside)
    assert count == 2
    assert abs(ratio - 0.02) < 1e-9
    assert bands == {1, 3}, "two words land in the 2nd and 4th of ten bands"


def test_native_text_coverage_band_set_separates_header_from_full_layer():
    """Area alone cannot tell a clustered header from a page-wide text layer."""
    bbox = fitz.Rect(0, 0, 100, 100)
    header_only = [(5, 2 + i, 25, 6 + i) for i in range(0, 8, 2)]      # top band only
    full_layer = [(5, 5 + b * 10, 25, 9 + b * 10) for b in range(10)]  # every band
    _, _, header_bands = ocr_service._native_text_coverage(bbox, header_only)
    _, _, layer_bands = ocr_service._native_text_coverage(bbox, full_layer)
    assert len(header_bands) <= 2
    assert len(layer_bands) == 10


def test_native_text_coverage_handles_degenerate_inputs():
    assert ocr_service._native_text_coverage(None, [(0, 0, 1, 1)]) == (0, 0.0, set())
    assert ocr_service._native_text_coverage(
        fitz.Rect(0, 0, 0, 0), [(0, 0, 1, 1)]) == (0, 0.0, set())


def test_ink_band_probe_reports_where_the_image_actually_has_content():
    """The band test must be relative to the image's ink, not the page: a
    scanned certificate whose content fills only the top half still carries a
    complete OCR layer over that half."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    src = fitz.open()
    sp = src.new_page(width=400, height=400)
    sp.draw_rect(fitz.Rect(0, 0, 400, 400), fill=(1, 1, 1), color=None)
    sp.draw_rect(fitz.Rect(20, 10, 380, 190), fill=(0, 0, 0), color=None)  # top half only
    pix = sp.get_pixmap()
    src.close()
    page.insert_image(fitz.Rect(0, 0, 400, 400), pixmap=pix)

    bands = ocr_service._image_ink_bands(page, fitz.Rect(0, 0, 400, 400))
    doc.close()

    assert bands is not None
    assert bands, "ink must be detected"
    assert max(bands) <= 5, f"ink should be confined to the upper bands, got {sorted(bands)}"


def test_ink_band_probe_returns_none_on_failure():
    """Callers must be able to distinguish 'no ink' from 'could not measure'."""
    assert ocr_service._image_ink_bands(None, fitz.Rect(0, 0, 10, 10)) is None


# ===========================================================================
# Candidate filtering
# ===========================================================================

def test_decorative_icon_is_not_sent_to_ocr(tmp_path, fake_vision):
    """A 32x32px stored raster cannot hold legible text and must be skipped."""
    p = str(tmp_path / "icon.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 300, 560, 780), BODY * 25, fontsize=9)
    tiny = _raster(30, 30, dpi_scale=1.0)          # ~30x30 px stored
    page.insert_image(fitz.Rect(50, 50, 110, 110), pixmap=tiny)
    doc.save(p)
    doc.close()

    text, _ = run(p)

    assert fake_vision.call_count == 0, "decorative icons must not cost an OCR call"
    assert "Declarations continued" in text


def test_repeated_logo_is_ocred_once_not_once_per_page(tmp_path, fake_vision):
    """A letterhead on 5 pages is one asset, not five.

    Without content-hash dedup this both wastes calls and floods the LLM input
    with the same lines repeated once per page.
    """
    p = str(tmp_path / "logo.pdf")
    build_repeated_logo(p, n_pages=5)

    text, _ = run(p)

    assert fake_vision.image_count == 1, (
        f"expected the repeated logo to be OCR'd once, got {fake_vision.image_count}"
    )
    assert text.count("OCRTEXT") == 1
    for i in range(5):
        assert f"PAGE {i} CONTENT" in text, f"native text for page {i} lost"


# ===========================================================================
# Page routing
# ===========================================================================

def test_scanned_page_uses_full_page_ocr(tmp_path, fake_vision):
    p = str(tmp_path / "scan.pdf")
    build_scanned_page(p, n_pages=1)

    text, _ = run(p)

    assert fake_vision.call_count == 1
    assert "OCRTEXT" in text


def test_path_b_uses_ocr_text_and_does_not_duplicate_the_native_remnant(tmp_path, monkeypatch):
    """On a scanned page the OCR text REPLACES the short native remnant.

    The old implementation appended OCR to native text instead. Replacing is
    correct here and was verified against the live API: a scanned page's own
    typed header is visible in the render, so Vision returns it too - appending
    would emit it twice. When OCR yields nothing the native remnant is still
    kept (see test_open_circuit_falls_back_to_native_text)."""
    fv = FakeVision(text_for=lambda w, h, p: "TYPED HEADER REF-99812\nSCANNED BODY GL-778451")
    install(monkeypatch, fv)
    p = str(tmp_path / "pathb.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 60), "TYPED HEADER REF-99812", fontsize=12)   # < 100 chars
    page.insert_image(fitz.Rect(26, 120, 586, 720),
                      pixmap=_raster(560, 600, text="SCANNED BODY GL-778451"))
    doc.save(p)
    doc.close()

    text, _ = run(p)

    assert fv.call_count == 1
    assert "GL-778451" in text, "scanned body must be recovered"
    assert text.count("REF-99812") == 1, "the native remnant must not be emitted twice"


def test_blank_page_is_not_sent_to_ocr(tmp_path, fake_vision):
    p = str(tmp_path / "blank.pdf")
    build_blank_page(p)

    text, _ = run(p)

    assert fake_vision.call_count == 0, "a provably empty page must not cost a call"
    assert text == ""


def test_mixed_document_preserves_page_order(tmp_path, monkeypatch):
    """Assembly must follow page order regardless of batch completion order."""
    fv = FakeVision(
        text_for=lambda w, h, p: "SCANNED_PAGE_TEXT" if h > 900 else "EMBEDDED_IMAGE_TEXT"
    )
    install(monkeypatch, fv)
    p = str(tmp_path / "mixed.pdf")
    build_mixed_document(p)

    text, _ = run(p)

    assert "ALPHA PAGE" in text
    assert "SCANNED_PAGE_TEXT" in text
    assert "GAMMA PAGE" in text
    assert "EMBEDDED_IMAGE_TEXT" in text
    assert text.index("ALPHA PAGE") < text.index("SCANNED_PAGE_TEXT") < text.index("GAMMA PAGE"), \
        "pages must be assembled in document order"
    assert text.index("GAMMA PAGE") < text.index("EMBEDDED_IMAGE_TEXT")


def test_page_count_mismatch_is_padded_not_dropped(tmp_path, fake_vision, monkeypatch):
    """If pdfplumber reports fewer pages than PyMuPDF, trust the larger count."""
    p = str(tmp_path / "mismatch.pdf")
    build_scanned_page(p, n_pages=3)

    real = ocr_service._pdfplumber_extract_pages
    monkeypatch.setattr(
        ocr_service, "_pdfplumber_extract_pages", lambda path: real(path)[:1]
    )

    run(p)

    assert fake_vision.image_count == 3, "pages beyond pdfplumber's count must still be OCR'd"


# ===========================================================================
# Batching
# ===========================================================================

def test_batch_never_exceeds_vision_hard_limit(tmp_path, fake_vision):
    """Vision rejects >16 images per request with HTTP 400."""
    p = str(tmp_path / "many.pdf")
    build_scanned_page(p, n_pages=40)

    run(p)

    assert fake_vision.image_count == 40
    for batch in fake_vision.batches:
        assert len(batch) <= ocr_service._VISION_HARD_MAX_BATCH, \
            f"batch of {len(batch)} exceeds Vision's hard limit"
    assert fake_vision.call_count < 40, "batching must reduce the number of API calls"


def test_sparse_images_across_many_windows_are_batched_into_one_request(tmp_path, fake_vision):
    """Windows bound memory; they must not bound requests.

    Observed in production on a 271-page policy: 7 embedded images went out as
    3 separate HTTP requests because each 24-page window dispatched its own
    one-or-two-image batch. It costs nothing in Vision charges (billing is per
    image) but it is pure added latency, so the incomplete tail is carried into
    the next window instead of being flushed."""
    pages = 130                                   # > 5 windows at the default 24
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(50, 200, 560, 770), f"PAGE {i}. " + BODY * 20, fontsize=9)
        if i % 20 == 0:                           # one distinct image every 20 pages
            page.insert_image(fitz.Rect(50, 50, 250, 170), pixmap=_raster(200, 120, text=f"G{i}"))
    p = str(tmp_path / "sparse.pdf")
    doc.save(p)
    doc.close()

    run(p)

    assert fake_vision.image_count == 7, f"expected 7 distinct images, got {fake_vision.image_count}"
    assert fake_vision.call_count == 1, (
        f"sparse images must coalesce into one request, got {fake_vision.call_count} "
        f"with sizes {[len(b) for b in fake_vision.batches]}"
    )


def test_scanned_document_fills_batches_across_window_boundaries(tmp_path, fake_vision):
    """A window holds 24 pages, so flushing per window wasted a partial batch
    every time. Carrying the tail keeps requests at the 16-image maximum."""
    p = str(tmp_path / "manyscans.pdf")
    build_scanned_page(p, n_pages=50)

    run(p)

    assert fake_vision.image_count == 50
    full = [len(b) for b in fake_vision.batches if len(b) == ocr_service._VISION_MAX_BATCH]
    assert len(full) >= 3, (
        f"expected mostly full batches, got {[len(b) for b in fake_vision.batches]}"
    )
    assert fake_vision.call_count <= 4, (
        f"50 images should need 4 requests at most, got {fake_vision.call_count}"
    )


def test_image_disposition_tally_accounts_for_every_image(tmp_path, fake_vision):
    """The summary log's breakdown must partition the examined images exactly.

    This module's failure mode is silent data loss, so an operator has to be
    able to see from ordinary logs whether the filter discarded something.
    A tally that does not add up means a rejection path is unaccounted for."""
    doc = fitz.open()
    logo = _raster(160, 90, text="ACME")
    icon = _raster(20, 20, dpi_scale=1.0)
    for i in range(30):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(50, 200, 560, 770), f"PAGE {i}. " + BODY * 20, fontsize=9)
        page.insert_image(fitz.Rect(50, 50, 210, 140), pixmap=logo)        # repeat
        page.insert_image(fitz.Rect(560, 50, 580, 70), pixmap=icon)        # too small
        if i == 5:
            page.insert_image(fitz.Rect(300, 50, 500, 170),
                              pixmap=_raster(200, 120, text="UNIQUE"))     # OCR'd
    p = str(tmp_path / "tally.pdf")
    doc.save(p)
    doc.close()

    budget = ocr_service._DocBudget()
    real_build = ocr_service._build_window_jobs

    def capture(pdf_path, idxs, texts, b):
        return real_build(pdf_path, idxs, texts, budget)

    monkey = capture
    orig = ocr_service._build_window_jobs
    ocr_service._build_window_jobs = monkey
    try:
        run(p)
    finally:
        ocr_service._build_window_jobs = orig

    accounted = (fake_vision.image_count + budget.skipped_duplicate
                 + budget.skipped_covered + budget.skipped_small
                 + budget.skipped_unreadable + budget.skipped_capped)
    assert budget.images_examined == accounted, (
        f"examined={budget.images_examined} but accounted={accounted}: "
        f"dup={budget.skipped_duplicate} covered={budget.skipped_covered} "
        f"small={budget.skipped_small} unreadable={budget.skipped_unreadable} "
        f"capped={budget.skipped_capped} ocr={fake_vision.image_count}"
    )
    assert budget.skipped_small >= 30, "the 20x20 icons must be counted as too small"
    assert budget.skipped_duplicate >= 29, "the repeated logo must be counted as a repeat"


def test_group_payloads_respects_count_limit():
    groups = ocr_service._group_payloads([10] * 50)
    assert all(len(g) <= ocr_service._VISION_MAX_BATCH for g in groups)
    assert sum(len(g) for g in groups) == 50
    assert [i for g in groups for i in g] == list(range(50)), "order must be preserved"


def test_group_payloads_respects_byte_budget():
    big = ocr_service._VISION_MAX_BATCH_BYTES // 3
    groups = ocr_service._group_payloads([big] * 9)
    for g in groups:
        assert g, "no empty batches"
        assert sum(big for _ in g) <= ocr_service._VISION_MAX_BATCH_BYTES or len(g) == 1
    assert sum(len(g) for g in groups) == 9


def test_group_payloads_isolates_an_oversized_item():
    huge = ocr_service._VISION_MAX_BATCH_BYTES * 2
    groups = ocr_service._group_payloads([10, huge, 10])
    assert sum(len(g) for g in groups) == 3, "an oversized item must not be dropped"


# ===========================================================================
# Failure isolation
# ===========================================================================

def test_batch_failure_splits_and_isolates_the_poison_image(monkeypatch):
    """One undecodable image must not destroy the 15 valid images with it."""
    monkeypatch.setattr(ocr_service, "_vision_cb", _PassThroughCB())

    poison = b"POISON"

    def provider(payloads):
        if any(p == poison for p in payloads):
            raise RuntimeError("bad image in batch")
        return [ocr_service._OcrResult(text="GOOD") for _ in payloads]

    monkeypatch.setattr(ocr_service, "_vision_batch_call", provider)

    payloads = [b"a", b"b", poison, b"d", b"e", b"f", b"g", b"h"]
    results = ocr_service._ocr_batch_sync(payloads)

    assert len(results) == len(payloads)
    assert results[2].ok is False, "the poison payload must be marked failed"
    good = [r for i, r in enumerate(results) if i != 2]
    assert all(r.ok and r.text == "GOOD" for r in good), \
        "valid images must survive a neighbour's failure"


def test_open_circuit_falls_back_to_native_text(tmp_path, monkeypatch):
    """A Vision outage must degrade to native text, never crash or blank."""
    class OpenCB:
        opened = True

        def call(self, fn, *a, **kw):        # pragma: no cover - never reached
            raise AssertionError("must not call the provider while open")

    monkeypatch.setattr(ocr_service, "_vision_cb", OpenCB())
    p = str(tmp_path / "cb.pdf")
    build_text_page_with_image(p, 300, 200)

    text, low_conf = run(p)

    assert "Declarations continued" in text, "native text must survive an OCR outage"
    assert "OCRTEXT" not in text


def test_corrupt_pdf_returns_empty_without_raising(tmp_path, fake_vision):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4 this is not a real pdf")

    text, low_conf = run(str(p))

    assert isinstance(text, str)
    assert isinstance(low_conf, list)


def test_full_ocr_page_cap_keeps_native_text_and_flags_review(tmp_path, fake_vision, monkeypatch):
    """Exceeding the page cap must degrade loudly, never silently."""
    monkeypatch.setattr(ocr_service, "_OCR_MAX_PAGES_PER_DOC", 1)
    p = str(tmp_path / "capped.pdf")
    build_scanned_page(p, n_pages=4)

    text, low_conf = run(p)

    assert fake_vision.image_count == 1, "the cap must bound OCR work"
    assert "needs_manual_review" in low_conf, "capping must be surfaced, not silent"
    assert low_conf[0] == "needs_manual_review", "the marker must not be truncated away"
    assert "p3" in text, "native text for capped pages must still be kept"


# ===========================================================================
# gRPC (service-account) provider path
# ===========================================================================
# Deployments with GOOGLE_APPLICATION_CREDENTIALS instead of an API key take a
# different provider path. It cannot be exercised against the live API here, so
# these tests drive it with real Vision protos and a stub client to prove the
# response mapping, per-image error isolation and index alignment.

@pytest.fixture()
def gvision(monkeypatch):
    """Yield a usable google.cloud.vision despite suite-wide sys.modules stubs.

    tests/test_production_guards.py permanently stubs "google.auth" and
    "google.oauth2" in sys.modules, and never removes them. google.cloud.vision
    imports google.auth.exceptions, so once those stubs are in place the import
    fails - and a failed attempt also leaves partially-initialised
    google.cloud.vision_v1 modules behind, which then raise a circular-import
    error on every later attempt.

    Drop the stubs and any partial vision modules for the duration of the test;
    monkeypatch.delitem restores sys.modules exactly as it was on teardown, so
    no other test's environment is perturbed.
    """
    import types

    for name in list(sys.modules):
        is_stubbed_auth = (
            (name == "google.auth" or name.startswith("google.auth."))
            or (name == "google.oauth2" or name.startswith("google.oauth2."))
        )
        mod = sys.modules.get(name)
        if is_stubbed_auth and isinstance(mod, types.ModuleType) \
                and not getattr(mod, "__file__", None):
            monkeypatch.delitem(sys.modules, name)
        elif name == "google.cloud.vision" or name.startswith("google.cloud.vision"):
            monkeypatch.delitem(sys.modules, name)

    try:
        from google.cloud import vision as _gvision
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"google.cloud.vision unavailable in this environment: {exc}")
    return _gvision


def test_grpc_batch_maps_responses_and_isolates_per_image_errors(monkeypatch, gvision):
    class StubClient:
        def batch_annotate_images(self, requests):
            assert len(requests) == 3
            return gvision.BatchAnnotateImagesResponse(responses=[
                gvision.AnnotateImageResponse(
                    full_text_annotation=gvision.TextAnnotation(text="ALPHA")),
                gvision.AnnotateImageResponse(error={"message": "bad image"}),
                gvision.AnnotateImageResponse(
                    full_text_annotation=gvision.TextAnnotation(text="GAMMA")),
            ])

    monkeypatch.setattr(ocr_service, "_get_google_vision_client", lambda: StubClient())

    out = ocr_service._vision_grpc_batch([b"a", b"b", b"c"])

    assert [r.text for r in out] == ["ALPHA", "", "GAMMA"], "results must stay index-aligned"
    assert out[0].ok is True and out[2].ok is True
    assert out[1].ok is False, "a per-image error must not fail its neighbours"


def test_grpc_batch_pads_when_provider_returns_fewer_responses(monkeypatch, gvision):
    """Never let a short response list silently shift results onto wrong pages."""

    class ShortClient:
        def batch_annotate_images(self, requests):
            return gvision.BatchAnnotateImagesResponse(responses=[
                gvision.AnnotateImageResponse(
                    full_text_annotation=gvision.TextAnnotation(text="ONLY")),
            ])

    monkeypatch.setattr(ocr_service, "_get_google_vision_client", lambda: ShortClient())

    out = ocr_service._vision_grpc_batch([b"a", b"b", b"c"])

    assert len(out) == 3
    assert out[0].text == "ONLY"
    assert out[1].ok is False and out[2].ok is False


def test_grpc_batch_rejects_an_oversized_batch(monkeypatch):
    monkeypatch.setattr(ocr_service, "_get_google_vision_client", lambda: None)
    with pytest.raises(ValueError):
        ocr_service._vision_grpc_batch([b"x"] * (ocr_service._VISION_HARD_MAX_BATCH + 1))


def test_provider_selection_follows_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "AIzaTest")
    assert ocr_service._use_rest_api() is True
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "   ")
    assert ocr_service._use_rest_api() is False
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    assert ocr_service._use_rest_api() is False


# ===========================================================================
# Retry policy
# ===========================================================================

def _http_error(status):
    import httpx
    request = httpx.Request("POST", "https://vision.googleapis.com/v1/images:annotate")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize("status,expected", [(429, True), (500, True), (503, True)])
def test_transient_http_errors_are_retried(status, expected):
    assert ocr_service._is_retryable(_http_error(status)) is expected


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_permanent_http_errors_are_not_retried(status):
    """A permanent 4xx cannot be fixed by retrying. Retrying it burns the
    backoff budget at every level of the split-on-failure recursion, turning
    one malformed image into tens of seconds of dead time."""
    assert ocr_service._is_retryable(_http_error(status)) is False


def test_transport_errors_are_retried():
    import httpx
    assert ocr_service._is_retryable(httpx.ConnectError("dns")) is True
    assert ocr_service._is_retryable(httpx.ReadTimeout("slow")) is True


def test_programming_errors_are_not_retried():
    assert ocr_service._is_retryable(ValueError("bad batch size")) is False


# ===========================================================================
# Resource safety
# ===========================================================================

def test_pdf_is_not_locked_after_extraction(tmp_path, fake_vision):
    """An unclosed fitz.Document blocks os.remove on Windows (WinError 32),
    and form_routes swallows that OSError - leaving uploaded PII on disk."""
    p = str(tmp_path / "lock.pdf")
    build_mixed_document(p)

    run(p)

    os.remove(p)                       # raises if a handle was leaked
    assert not os.path.exists(p)


def test_no_intermediate_files_written_to_upload_dir(tmp_path, fake_vision):
    """The main path renders to memory; it must not litter UPLOAD_DIR."""
    from config.settings import UPLOAD_DIR
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    before = set(os.listdir(UPLOAD_DIR))

    p = str(tmp_path / "clean.pdf")
    build_mixed_document(p)
    run(p)

    assert set(os.listdir(UPLOAD_DIR)) == before, "temporary render files were left behind"


# ===========================================================================
# Image normalisation
# ===========================================================================

def test_normalise_passes_through_a_supported_in_budget_image():
    pix = _raster(100, 80)
    data = pix.tobytes("png")
    assert ocr_service._normalise_image_bytes(data, "png") is data, \
        "an in-budget PNG must not be re-encoded"


def test_normalise_transcodes_a_format_vision_cannot_read():
    """JBIG2/JPX/CCITT are routine in scanned PDFs and Vision rejects them."""
    data = _raster(200, 150).tobytes("png")
    out = ocr_service._normalise_image_bytes(data, "jpx")
    assert out is not None and len(out) > 0
    assert _decode_dims(out) == (200 * 3, 150 * 3)


def test_encode_pixmap_handles_alpha_without_raising():
    """tobytes('jpeg') raises ValueError on an alpha pixmap; alpha must be
    dropped first or every transparent logo would be lost."""
    d = fitz.open()
    page = d.new_page(width=120, height=90)
    pix = page.get_pixmap(alpha=True)
    d.close()
    assert pix.alpha == 1

    out = ocr_service._encode_pixmap(pix)
    assert out is not None and len(out) > 0


def test_encode_pixmap_downscales_instead_of_dropping(monkeypatch):
    """An oversized image must degrade in resolution, never vanish."""
    monkeypatch.setattr(ocr_service, "_VISION_MAX_IMAGE_BYTES", 4096)
    pix = _raster(400, 300, dpi_scale=2.0)

    out = ocr_service._encode_pixmap(pix)

    assert out is not None, "oversized image was dropped instead of downscaled"
    assert len(out) <= 4096


# ===========================================================================
# Guards against re-introducing previously fixed bugs
# ===========================================================================

def test_pdfplumber_extract_pages_applies_column_reflow(tmp_path):
    """Guards the 2026-07-11 fix: the per-page extractor must route through
    _extract_page_text_smart, not raw page.extract_text().

    A colleague's proposed patch reverted exactly this, which silently
    reintroduced 'CARRIER: <FEIN>' on drifted two-column dec pages.
    """
    labels = ["Named Insured:", "Legal Entity:", "Mailing Address:", "FEIN:",
              "CARRIER:", "NAIC Code:", "Policy Number:", "Effective Date:",
              "Expiration Date:", "AGENCY:", "Producer:", "Producer Address:"]
    values = ["Summit Ridge Construction LLC", "Limited Liability Company",
              "4820 Kettering Blvd Denver CO 80216", "84-2210987",
              "Pinnacle Casualty Insurance Company", "38954", "GL-CO-778451",
              "04/01/2026", "04/01/2027", "Front Range Insurance Advisors",
              "Dana Whitfield", "1100 Larimer Street Denver CO 80202"]
    path = str(tmp_path / "twocol.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 60), "COMMERCIAL GENERAL LIABILITY SECTION", fontsize=12)
    y = 100
    for l in labels:
        page.insert_text((60, y), l, fontsize=10)
        y += 20
    y = 100
    for v in values:
        page.insert_text((320, y), v, fontsize=10)
        y += 26
    doc.save(path)
    doc.close()

    pages = ocr_service._pdfplumber_extract_pages(path)
    joined = "\n".join(pages)

    carrier = [l for l in joined.splitlines() if l.strip().upper().startswith("CARRIER")]
    assert carrier, "no CARRIER line extracted"
    assert "Pinnacle" in carrier[0], f"carrier/value scramble regressed: {carrier[0]!r}"
    assert "84-2210987" not in carrier[0], "the FEIN was paired with CARRIER again"


def test_pdfplumber_extract_still_matches_per_page_extraction(tmp_path):
    """_pdfplumber_extract is the legacy whole-document entry point and must
    stay consistent with the per-page one it now delegates to."""
    p = str(tmp_path / "consistency.pdf")
    build_mixed_document(p)

    whole = ocr_service._pdfplumber_extract(p)
    per_page = "".join(t + "\n" for t in ocr_service._pdfplumber_extract_pages(p) if t)

    assert whole == per_page


# ===========================================================================
# Rotated pages
#
# page.get_text("words") reports boxes in the page's UNROTATED space;
# page.get_image_bbox() reports in the ROTATED (displayed) space. The
# searchable-scan guard compares the two, so on a /Rotate 90/180/270 page it
# was measuring a region of the page unrelated to the image: on one document
# saved at four rotations, native-text coverage over the SAME embedded image
# read 0.0% upright and 86.2% at 270 degrees, silently discarding a pasted
# declarations page and logging it as "covered by text layer".
#
# Both directions have to be tested. Measuring in the wrong frame can also
# suppress the guard, which duplicates a whole searchable scan into the LLM
# input rather than losing it.
# ===========================================================================

_SCAN_LINE = "SCANNED CERTIFICATE OF LIABILITY INSURANCE. " + BODY


def _scan_pixmap(bg_grey=1.0, content_frac=1.0, w=612, h=792):
    """A page-sized bitmap: paper of a given greyness, dark text over the top
    `content_frac` of it."""
    src = fitz.open()
    sp = src.new_page(width=w, height=h)
    sp.draw_rect(fitz.Rect(0, 0, w, h), color=(bg_grey,) * 3, fill=(bg_grey,) * 3)
    rc = sp.insert_textbox(fitz.Rect(20, 20, w - 20, h * content_frac),
                           _SCAN_LINE * int(38 * content_frac), fontsize=10)
    assert rc >= 0, "fixture text overflowed its box"
    pix = sp.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
    src.close()
    return pix


def build_rotated_text_page_with_image(path, rot):
    """Typed body text plus a pasted dec-page image that does NOT overlap it."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(40, 260, 575, 780), BODY * 45, fontsize=9)
    page.insert_image(fitz.Rect(45, 45, 345, 245), pixmap=_raster(300, 200))
    page.set_rotation(rot)
    doc.save(path)
    doc.close()


def build_searchable_scan(path, rot=0, bg_grey=1.0, content_frac=1.0):
    """What Adobe Scan / an office MFP emits: the page bitmap PLUS an invisible
    (render mode 3) text layer holding that scanner's own OCR of it."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792),
                      pixmap=_scan_pixmap(bg_grey, content_frac))
    rc = page.insert_textbox(fitz.Rect(20, 20, 592, 792 * content_frac),
                             _SCAN_LINE * int(38 * content_frac),
                             fontsize=10, render_mode=3)
    assert rc >= 0, "fixture text layer overflowed its box"
    page.set_rotation(rot)
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_embedded_image_is_recovered_on_a_rotated_page(tmp_path, fake_vision, rot):
    """The reported bug class, reached through /Rotate instead of through the
    document-level threshold. Rotated pages are routine in broker submissions
    (landscape schedules, MFP auto-rotation)."""
    p = str(tmp_path / f"rot{rot}.pdf")
    build_rotated_text_page_with_image(p, rot)

    text, _ = run(p)

    assert "OCRTEXT" in text, (
        f"the pasted dec-page image was discarded at /Rotate {rot} - the "
        f"searchable-scan guard is measuring the wrong region of the page"
    )


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_searchable_scan_is_not_duplicated_on_a_rotated_page(tmp_path, fake_vision, rot):
    """The other direction: the guard must still FIRE on a rotated page, or a
    scanner-produced PDF is emitted twice into the LLM input."""
    p = str(tmp_path / f"scan{rot}.pdf")
    build_searchable_scan(p, rot=rot)

    text, _ = run(p)

    assert fake_vision.call_count == 0, (
        f"the scan's own OCR layer already covers it at /Rotate {rot}; "
        f"re-OCR'ing duplicates every figure on the page"
    )
    assert "OCRTEXT" not in text


def test_native_word_boxes_are_reported_in_the_image_bbox_frame(tmp_path):
    """The root cause, asserted directly: whatever frame get_image_bbox uses,
    the word boxes must be in it, at every rotation."""
    measured = {}
    for rot in (0, 90, 180, 270):
        p = str(tmp_path / f"frame{rot}.pdf")
        build_rotated_text_page_with_image(p, rot)
        doc = fitz.open(p)
        page = doc[0]
        bbox = page.get_image_bbox(page.get_images(full=True)[0])
        _, coverage, _ = ocr_service._native_text_coverage(
            bbox, ocr_service._native_word_boxes(page))
        measured[rot] = coverage
        doc.close()

    assert max(measured.values()) < 0.01, (
        f"the text block does not touch the image, so coverage must be ~0 at "
        f"every rotation; got {measured}"
    )


# ===========================================================================
# Ink-band probe: "ink" is relative to the paper, not to a fixed cutoff
# ===========================================================================

def test_searchable_scan_on_tinted_paper_is_not_duplicated(tmp_path, fake_vision):
    """A fixed near-white cutoff classified EVERY band of a real scan as inked
    as soon as the paper rendered at byte 249 or darker - which is almost
    always, given lamp falloff, paper tint and JPEG noise. The ink-relative
    band test then degenerated into the page-relative one it exists to replace,
    and a scan whose content fills only part of the sheet was duplicated."""
    p = str(tmp_path / "tinted.pdf")
    build_searchable_scan(p, bg_grey=0.96, content_frac=0.40)

    text, _ = run(p)

    assert fake_vision.call_count == 0, (
        "the scanner's text layer covers the inked area of this scan; the "
        "grey paper below it is not content"
    )
    assert "OCRTEXT" not in text


def test_ink_probe_ignores_tinted_paper(tmp_path):
    """Direct assertion on the probe: tinted paper is not ink."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792),
                      pixmap=_scan_pixmap(bg_grey=0.96, content_frac=0.40))
    bands = ocr_service._image_ink_bands(page, page.rect)
    doc.close()

    assert bands, "the dark text at the top is ink and must be detected"
    assert len(bands) < ocr_service._EMB_NATIVE_BAND_COUNT, (
        f"tinted paper was counted as ink, so every band looks inked: "
        f"{sorted(bands)}"
    )
    assert max(bands) <= 5, f"ink should be confined to the top, got {sorted(bands)}"


def test_bates_stamped_scan_is_still_ocrd(tmp_path, fake_vision):
    """The guard against the guard. A full-page scan whose only native text is
    a Bates / protective-order banner has 14-50 native words inside the image's
    box. Skipping on that basis would discard the entire scan."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=_scan_pixmap(0.97, 1.0))
    page.insert_textbox(
        fitz.Rect(40, 745, 575, 790),
        "CONFIDENTIAL - PRODUCED SUBJECT TO PROTECTIVE ORDER - BATES ABC000123 "
        "- ATTORNEYS EYES ONLY - DO NOT COPY OR DISTRIBUTE WITHOUT CONSENT",
        fontsize=8)
    p = str(tmp_path / "bates.pdf")
    doc.save(p)
    doc.close()

    text, _ = run(p)

    assert "OCRTEXT" in text, "a Bates banner is not a scanner OCR layer"


# ===========================================================================
# Caps and provider failures must be VISIBLE
#
# This module's failure mode is silent data loss, so every path that drops
# content a broker handed us has to reach needs_manual_review. Three did not:
# the per-document image cap skipped whole pages without even counting them,
# the per-page cap counted but never flagged, and a hard provider failure was
# reported in the summary as a successful OCR.
# ===========================================================================

def build_unique_image_pages(path, n_pages):
    """n pages, each with typed text and its own DISTINCT embedded image."""
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(50, 500, 560, 780),
                            f"PAGE {i} NATIVE TEXT. " + BODY * 8, fontsize=9)
        page.insert_image(fitz.Rect(40, 40, 190, 180),
                          pixmap=_raster(100 + i * 7, 100, text=f"T{i}"))
    doc.save(path)
    doc.close()


def test_document_image_cap_is_flagged_for_review(tmp_path, fake_vision, monkeypatch):
    """Exhausting the per-document cap used to skip every later page in total
    silence: images_examined never counted them, so the tally self-check
    balanced and nothing reached the caller."""
    monkeypatch.setattr(ocr_service, "_EMB_MAX_IMAGES_PER_DOC", 3)
    p = str(tmp_path / "doccap.pdf")
    build_unique_image_pages(p, 6)

    text, low_conf = run(p)

    assert fake_vision.image_count == 3, "the cap must still be enforced"
    assert "needs_manual_review" in low_conf, (
        "three declarations images were dropped at the cap and the caller was "
        "told nothing"
    )


def test_page_image_cap_is_flagged_for_review(tmp_path, fake_vision, monkeypatch):
    monkeypatch.setattr(ocr_service, "_EMB_MAX_IMAGES_PER_PAGE", 2)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 500, 560, 780), "NATIVE. " + BODY * 8, fontsize=9)
    for k in range(6):
        page.insert_image(fitz.Rect(40 + k * 90, 40, 130 + k * 90, 140),
                          pixmap=_raster(100 + k * 5, 100, text=f"I{k}"))
    p = str(tmp_path / "pagecap.pdf")
    doc.save(p)
    doc.close()

    _, low_conf = run(p)

    assert "needs_manual_review" in low_conf


def test_document_image_cap_counts_every_dropped_candidate(tmp_path, fake_vision, monkeypatch):
    """The cap branch incremented skipped_capped by 1 and then broke, so N
    dropped images were reported as 1 - and tripped the partition check."""
    monkeypatch.setattr(ocr_service, "_EMB_MAX_IMAGES_PER_DOC", 2)
    budget = ocr_service._DocBudget()
    real_build = ocr_service._build_window_jobs
    monkeypatch.setattr(
        ocr_service, "_build_window_jobs",
        lambda pdf_path, idxs, texts, _b: real_build(pdf_path, idxs, texts, budget))

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 500, 560, 780), "NATIVE. " + BODY * 8, fontsize=9)
    for k in range(5):
        page.insert_image(fitz.Rect(40 + k * 90, 40, 130 + k * 90, 140),
                          pixmap=_raster(100 + k * 5, 100, text=f"I{k}"))
    p = str(tmp_path / "capcount.pdf")
    doc.save(p)
    doc.close()

    run(p)

    assert budget.skipped_capped == 3, (
        f"5 candidates, cap 2, so 3 were dropped; got {budget.skipped_capped}"
    )
    accounted = (fake_vision.image_count + budget.skipped_duplicate
                 + budget.skipped_covered + budget.skipped_small
                 + budget.skipped_unreadable + budget.skipped_capped)
    assert budget.images_examined == accounted


def test_failed_embedded_image_ocr_is_flagged_not_counted_as_success(tmp_path, monkeypatch):
    """_OcrResult.ok exists to separate 'this logo has no words' from 'the
    provider failed'. Both arrived as empty text and only the second is data
    loss; the field was never read outside the tests."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 500, 560, 780), "NATIVE. " + BODY * 8, fontsize=9)
    page.insert_image(fitz.Rect(40, 40, 340, 240), pixmap=_raster(300, 200))
    p = str(tmp_path / "failimg.pdf")
    doc.save(p)
    doc.close()

    # Fails on content, so the split-on-failure retries fail too and the item
    # genuinely ends up ok=False rather than being rescued by a retry.
    fv = FakeVision(raise_for=lambda w, h, payload: True)
    install(monkeypatch, fv)

    text, low_conf = run(p)

    assert "OCRTEXT" not in text
    assert "needs_manual_review" in low_conf, (
        "a hard provider failure on an embedded image lost its text and was "
        "reported as a successful OCR"
    )


def test_oversized_page_render_respects_the_pixel_ceiling(tmp_path, fake_vision):
    """PDF allows sheets up to 200 inches. A 34x44in E-size drawing renders to
    31 Mpx (~93 MB of RGB) at 2x, and a window of 24 pages is built before
    anything is dispatched. The ceiling applied to embedded images only."""
    doc = fitz.open()
    page = doc.new_page(width=2448, height=3168)
    page.insert_text((50, 50), "E1", fontsize=8)
    page.draw_rect(fitz.Rect(100, 100, 2300, 3000), color=(0, 0, 0))
    p = str(tmp_path / "esize.pdf")
    doc.save(p)
    doc.close()

    text, _ = run(p)

    assert fake_vision.image_count == 1, "the page must still be OCR'd"
    pix = fitz.Pixmap(fake_vision.batches[0][0])
    assert pix.width * pix.height <= ocr_service._EMB_MAX_DECODE_PIXELS, (
        f"render is {pix.width}x{pix.height} = "
        f"{pix.width * pix.height / 1e6:.1f} Mpx, above the ceiling"
    )


def test_repeated_asset_payload_is_built_once_not_once_per_page(tmp_path, fake_vision, monkeypatch):
    """Content-hash dedup cannot run until the payload exists, so a letterhead
    on 200 pages was extracted, transcoded and hashed 200 times to be discarded
    199 times - a full decode and PNG re-encode per page for JBIG2/CCITT/JPX."""
    p = str(tmp_path / "letterhead.pdf")
    build_repeated_logo(p, n_pages=25)

    calls = {"n": 0}
    real = ocr_service._normalise_image_bytes
    monkeypatch.setattr(
        ocr_service, "_normalise_image_bytes",
        lambda data, ext: (calls.__setitem__("n", calls["n"] + 1), real(data, ext))[1])

    run(p)

    assert fake_vision.image_count == 1, "the logo must be OCR'd exactly once"
    assert calls["n"] == 1, (
        f"the payload was rebuilt {calls['n']} times for one distinct image"
    )


def test_unrenderable_scanned_page_is_flagged_for_review(tmp_path, fake_vision, monkeypatch):
    """A scanned page that will not rasterise keeps only its sub-100-character
    native remnant, which downstream cannot tell apart from a page that
    genuinely said nothing."""
    p = str(tmp_path / "unrenderable.pdf")
    build_scanned_page(p, n_pages=1)

    monkeypatch.setattr(ocr_service, "_render_page_png", lambda page: None)

    _, low_conf = run(p)

    assert "needs_manual_review" in low_conf
