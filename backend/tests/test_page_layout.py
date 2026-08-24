"""Extraction architecture change (2026-08-22) - utils/page_layout + ocr_service wiring.

Every test here drives the REAL code on the REAL files (the client's test package,
the ACORD templates, the column-reflow fixtures). See extraction_arch_change.md for
the measurements each threshold came from.

Three contracts, in order of importance:

1. IDENTITY - on every page that has no riffled line, page_text() is byte-identical
   to page.extract_text() and page_words() to page.extract_words(). The whole
   corpus is checked, dense ACORD forms included.
2. REPAIR - the client's loss run comes out "third party $4,850", not "pa$rt4y,850",
   and the PAID column lands in the PAID cell.
3. TABLES - the three schedules in the test package come out as tables with the
   right header, rows, continuation fold and section; the application and the
   ACORD 125 data map produce none; letter-soup on blank ACORD forms is rejected.
"""
from __future__ import annotations

import asyncio
import collections
import os
import tempfile

import pdfplumber
import pytest

from utils.page_layout import (
    column_bands,
    page_words, page_text, detect_tables, render_tables, interleaved_bands,
    vision_words, TABLE_OPEN, TABLE_CLOSE,
)
from utils.text_cleaner import clean_text
from services import ocr_service
from tests import test_ocr_column_reflow as reflow_fixtures

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
PKG = os.path.join(ROOT, "test_data_v1_c1")
TEMPLATES = os.path.join(BACKEND, "templates")

DEC = os.path.join(PKG, "1_dec_page.pdf")
CERT = os.path.join(PKG, "2_certificate.pdf")
APP = os.path.join(PKG, "3_application.pdf")
LOSS = os.path.join(PKG, "4_loss_run.pdf")

needs_pkg = pytest.mark.skipif(not os.path.exists(LOSS), reason="test_data_v1_c1 not present")


def _page(path, idx=0):
    pdf = pdfplumber.open(path)
    return pdf, pdf.pages[idx]


# ─────────────────────────────────────────────────────────────────────────────
# 1. IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

def _reflow_fixture_paths(tmp_dir):
    out = []
    for name, fn in (
        ("scrambled_identity", reflow_fixtures._build_scrambled_identity_block),
        ("normal_paragraph", reflow_fixtures._build_normal_paragraph),
        ("three_col_table", reflow_fixtures._build_three_column_table),
        ("composite", reflow_fixtures._build_composite_page),
    ):
        p = os.path.join(tmp_dir, name + ".pdf")
        fn(p)
        out.append(p)
    return out


def _identity_corpus(tmp_dir):
    paths = _reflow_fixture_paths(tmp_dir)
    for p in (DEC, CERT, APP):
        if os.path.exists(p):
            paths.append(p)
    for name in ("ACORD_125.pdf", "ACORD_126.pdf", "ACORD_127.pdf",
                 "ACORD_130.pdf", "ACORD_140.pdf", "ACORD_25.pdf"):
        p = os.path.join(TEMPLATES, name)
        if os.path.exists(p):
            paths.append(p)
    for extra in (os.path.join(ROOT, "SQS_Scoring_Specification.docx.pdf"),
                  os.path.join(ROOT, "125_reference", "ACORD 125 - data map 8-19-26.pdf")):
        if os.path.exists(extra):
            paths.append(extra)
    return paths


# Corpus pages this module is ALLOWED to change, and why. Anything else changing
# is a regression; anything here that stops changing means a repair silently died.
# Kept as an exact set so the test bites in both directions.
_EXPECTED_CHANGES: dict = {
    # (basename, 1-based page): reason.  EMPTY on purpose - after the 2026-08-22
    # gates, no page in this corpus (reflow fixtures, the client's clean
    # documents, six ACORD templates, a Word export, an Acrobat export) is
    # touched at all. Every earlier entry here marked a false positive that has
    # since been closed: ACORD 140 p2 and 130 p2 despacing, 125/126/127/130 p*
    # parallel-block splits, 126 p5's fraud paragraph.
}


def test_clean_pages_are_byte_identical_to_pdfplumber():
    """The whole corpus: fixtures, the client's clean documents, dense ACORD forms.

    THE load-bearing test of this module. Three transforms can change a page -
    riffle repair, letter-space rejoin, two-column reordering - and every one of
    them is scoped to a page that shows its own defect. Everything else must come
    out byte-identical to pdfplumber, or the change is not safe to ship.
    """
    with tempfile.TemporaryDirectory() as d:
        checked = 0
        changed = {}
        for path in _identity_corpus(d):
            base = os.path.basename(path)
            with pdfplumber.open(path) as pdf:
                for i, pg in enumerate(pdf.pages, 1):
                    words, repaired = page_words(pg)
                    text, _ = page_text(pg)
                    if text != (pg.extract_text() or "") or words != pg.extract_words():
                        changed[(base, i)] = repaired
                    checked += 1
        assert checked >= 10
        assert set(changed) == set(_EXPECTED_CHANGES), (
            f"changed={sorted(changed)} expected={sorted(_EXPECTED_CHANGES)}"
        )


def test_no_corpus_page_ever_loses_a_character():
    """Every transform re-groups words; none may add or drop one."""
    with tempfile.TemporaryDirectory() as d:
        for path in _identity_corpus(d):
            with pdfplumber.open(path) as pdf:
                for i, pg in enumerate(pdf.pages, 1):
                    before = collections.Counter(
                        c for c in (pg.extract_text() or "") if not c.isspace())
                    after = collections.Counter(
                        c for c in page_text(pg)[0] if not c.isspace())
                    assert before == after, f"{os.path.basename(path)} p{i}"


def test_reflow_fixtures_still_recover_and_stay_untouched():
    """The two-column scramble is still repaired, the paragraph and the table are
    still untouched - the reflow now runs on page_layout's words, and on these
    pages those ARE pdfplumber's words."""
    with tempfile.TemporaryDirectory() as d:
        scrambled, paragraph, table, composite = _reflow_fixture_paths(d)
        with pdfplumber.open(scrambled) as pdf:
            out = ocr_service._extract_page_text_smart(pdf.pages[0])
            assert "Legal Entity: Limited Liability Company (LLC)" in out
        for p in (paragraph, table):
            with pdfplumber.open(p) as pdf:
                pg = pdf.pages[0]
                assert ocr_service._extract_page_text_smart(pg) == (pg.extract_text() or "")


def test_stacked_form_labels_are_not_a_riffle():
    """ACORD_127 p3: two 6pt labels 5.5pt apart are bridged into one 3pt-chain line
    by pdfplumber and their characters overlap at ratio 1.0 - but on different
    baselines. That fired on 10 of 12 template pages before the same-baseline
    rule; it must never fire again."""
    p = os.path.join(TEMPLATES, "ACORD_127.pdf")
    if not os.path.exists(p):
        pytest.skip("template missing")
    with pdfplumber.open(p) as pdf:
        for pg in pdf.pages:
            assert interleaved_bands(pg.chars) == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. REPAIR - the client's loss run
# ─────────────────────────────────────────────────────────────────────────────

@needs_pkg
def test_loss_run_riffle_is_detected_on_exactly_the_two_claim_lines():
    pdf, pg = _page(LOSS)
    with pdf:
        assert "pa$rt4y,850" in (pg.extract_text() or ""), "fixture no longer reproduces the defect"
        bands = interleaved_bands(pg.chars)
        assert len(bands) == 2


@needs_pkg
def test_loss_run_text_is_repaired_and_nothing_else_moves():
    pdf, pg = _page(LOSS)
    with pdf:
        text, repaired = page_text(pg)
        assert repaired == 2
        assert "third party $4,850 $0 Closed" in text
        assert "customer premises $12,300 $0 Closed" in text
        assert "pa$rt4y" not in text and "premis$e1s2" not in text
        # Every other line is exactly what pdfplumber printed.
        before = (pg.extract_text() or "").splitlines()
        after = text.splitlines()
        assert len(before) == len(after)
        for b, a in zip(before, after):
            if "2024" in b or "2022" in b:
                continue
            assert a == b


@needs_pkg
def test_loss_run_no_character_is_lost_or_invented():
    pdf, pg = _page(LOSS)
    with pdf:
        text, _ = page_text(pg)
        ink = sorted(ch for ch in (pg.extract_text() or "") if not ch.isspace())
        assert sorted(ch for ch in text if not ch.isspace()) == ink


# ─────────────────────────────────────────────────────────────────────────────
# 3. TABLES
# ─────────────────────────────────────────────────────────────────────────────

@needs_pkg
def test_dec_page_schedule_of_coverage_parts():
    pdf, pg = _page(DEC)
    with pdf:
        tables = detect_tables(page_words(pg)[0])
    assert len(tables) == 1
    t = tables[0]
    assert t["section"] == "SCHEDULE OF COVERAGE PARTS"
    assert t["header"] == ["LINE OF BUSINESS", "CARRIER", "POLICY NUMBER", "PREMIUM", "EFF / EXP"]
    assert t["rows"][0] == ["Commercial General Liability", "EMC Prop & Cas Co", "BBC7263-26",
                            "$6,720", "07/15/26-07/15/27"]
    assert t["rows"][3] == ["Commercial Inland Marine", "Employers Mutual Cas Co", "IM-5540-26",
                            "$1,150", "07/15/26-07/15/27"]
    # A value on the column anchor is its own cell even with no gap before it.
    assert t["rows"][4] == ["Commercial Property", "-", "-", "NO COVERAGE", "-"]
    assert len(t["rows"]) == 6, "Total Policy Premium: is a summary line, not a row"


@needs_pkg
def test_certificate_continuation_rows_fold_into_the_limits_cell():
    pdf, pg = _page(CERT)
    with pdf:
        tables = detect_tables(page_words(pg)[0])
    assert len(tables) == 1
    t = tables[0]
    assert t["section"] == "COVERAGES"
    assert t["header"] == ["TYPE OF INSURANCE", "POLICY NUMBER", "POLICY PERIOD", "LIMITS"]
    assert t["rows"][0] == ["General Liability", "BBC7263-26", "07/15/26-07/15/27",
                            "Each Occurrence $1,000,000; General Aggregate $2,000,000"]
    assert t["rows"][2] == ["Umbrella Liability", "6J7-40-02---26", "07/15/26-07/15/27",
                            "Each Occurrence $1,000,000"]
    assert len(t["rows"]) == 3, "DESCRIPTION OF OPERATIONS ends the table"


@needs_pkg
def test_loss_run_claim_table_has_paid_in_the_paid_column():
    pdf, pg = _page(LOSS)
    with pdf:
        tables = detect_tables(page_words(pg)[0])
    assert len(tables) == 1
    t = tables[0]
    assert t["section"] == "CLAIM DETAIL"
    assert t["header"] == ["DATE OF LOSS", "LINE", "DESCRIPTION", "PAID", "RESERVED", "STATUS"]
    assert t["rows"] == [
        ["03/28/2024", "Business Auto", "Insured vehicle rear-ended third party", "$4,850", "$0", "Closed"],
        ["11/02/2022", "General Liability", "Water damage to customer premises", "$12,300", "$0", "Closed"],
    ]


@needs_pkg
def test_application_prose_produces_no_table():
    pdf, pg = _page(APP)
    with pdf:
        assert detect_tables(page_words(pg)[0]) == []


def test_acord_125_data_map_produces_no_table():
    p = os.path.join(ROOT, "125_reference", "ACORD 125 - data map 8-19-26.pdf")
    if not os.path.exists(p):
        pytest.skip("reference missing")
    with pdfplumber.open(p) as pdf:
        for pg in pdf.pages:
            assert detect_tables(page_words(pg)[0]) == []


def test_letter_soup_on_blank_acord_forms_is_rejected():
    """ACORD 25 used to yield `( C E O a M a B cc IN id E e D nt )` as a table."""
    p = os.path.join(TEMPLATES, "ACORD_25.pdf")
    if not os.path.exists(p):
        pytest.skip("template missing")
    with pdfplumber.open(p) as pdf:
        for pg in pdf.pages:
            for t in detect_tables(page_words(pg)[0]):
                tokens = [tok for cell in t["header"] + [c for r in t["rows"] for c in r]
                          for tok in cell.split() if any(ch.isalpha() for ch in tok)]
                single = sum(1 for tok in tokens if len(tok) == 1)
                assert single <= 0.25 * max(1, len(tokens)), render_tables([t], 1)


@needs_pkg
def test_vision_pixel_space_yields_the_same_table():
    """Scanned pages: the same detector on Vision boxes. Built from the loss run's
    own words scaled to 300 dpi so the expected table is known exactly."""
    pdf, pg = _page(LOSS)
    with pdf:
        words = page_words(pg)[0]
    s = 300 / 72.0
    ann = {"pages": [{"blocks": [{"paragraphs": [{"words": [
        {"symbols": [{"text": ch} for ch in w["text"]],
         "boundingBox": {"vertices": [
             {"x": w["x0"] * s, "y": w["top"] * s}, {"x": w["x1"] * s, "y": w["top"] * s},
             {"x": w["x1"] * s, "y": w["bottom"] * s}, {"x": w["x0"] * s, "y": w["bottom"] * s}]}}
        for w in words]}]}]}]}
    vw = vision_words(ann)
    assert len(vw) == len(words)
    tables = detect_tables(vw)
    assert len(tables) == 1
    assert tables[0]["rows"][0][3] == "$4,850"


def test_vision_words_never_raises_on_garbage():
    assert vision_words(None) == []
    assert vision_words({"pages": [{"blocks": [{"paragraphs": [{"words": [{"symbols": []}]}]}]}]}) == []
    assert vision_words({"pages": "nonsense"}) == []


def test_two_column_policy_wording_is_not_a_table():
    """The 271-page package regression (2026-08-22, second pass).

    A policy form lays its legal wording out in two columns. That IS a grid -
    measured, those columns score a PERFECT 1.00 anchor occupancy - so no
    geometric test can reject it. The text is what says "prose": neither a
    header cell nor a row begins mid-sentence in a real table.
    """
    from utils.page_layout import _is_header, _is_running_prose, _cells

    def cells_of(texts):
        out, x = [], 0.0
        for t in texts:
            out.append({"x0": x, "x1": x + 10.0 * len(t), "text": t})
            x += 10.0 * len(t) + 40.0
        return out

    # A header lifted verbatim from page 97 of the client's package.
    assert not _is_header(cells_of(["transported", "by", "the", '"insured"', "or", "in"]))
    # A real one from the same document must still pass.
    assert _is_header(cells_of(["LINE OF BUSINESS", "CARRIER", "POLICY NUMBER"]))
    assert _is_header(cells_of(["Pillar", "Weight", "What it measures"]))

    # Body rows: page 10's cancellation wording against the dec schedule.
    prose = [
        ["ten days before the cancellation is effective.", "5.", "Examination of Books and Records --"],
        ['If "we" cancel this policy for any other', "", '"We" may examine and audit "your" books'],
        ['reason, "we" will give "you" notice at least 30', "", "and records that relate to this policy during"],
    ]
    assert _is_running_prose(prose)
    real = [
        ["Commercial General Liability", "EMC Prop & Cas Co", "BBC7263-26", "$6,720"],
        ["Commercial Automobile Liability", "Employers Mutual Cas Co", "6E7-40-02---26", "$2,991"],
    ]
    assert not _is_running_prose(real)
    # A wrapped description ending in a conjunction is NOT enough on its own.
    assert not _is_running_prose([
        ["Bodily Injury", "Each person and", "$1,000,000"],
        ["Property Damage", "Each accident or", "$500,000"],
    ])


# ─────────────────────────────────────────────────────────────────────────────
# 3b. TWO-COLUMN READING ORDER
# ─────────────────────────────────────────────────────────────────────────────

def _two_col_pdf(path, left, right, *, gutter_x=320, start_y=700):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica", 9)
    for i, t in enumerate(left):
        c.drawString(60, start_y - i * 14, t)
    for i, t in enumerate(right):
        c.drawString(gutter_x + 6, start_y - i * 14, t)
    c.showPage()
    c.save()


# Page 151 of the client's package, verbatim. Long on purpose: real two-column
# prose runs long (median band 38 lines), and a short coincidental alignment is
# deliberately NOT reordered - see test_short_coincidental_column_run.
PROSE_L = [
    "d. Workers' Compensation And Similar Laws",
    "Any obligation of the insured under a workers'",
    "compensation, disability benefits or",
    "unemployment compensation law or any",
    "similar law.",
    "e. ERISA",
    "Any obligation of the insured under the",
    "Employee Retirement Income Security Act of",
    "1974 (ERISA), and any amendments thereto or",
    "any similar federal, state or local statute.",
]
PROSE_R = [
    "This exclusion does not apply to the extent that",
    'valid "underlying insurance" for the employer\'s',
    "liability risks described above exists or would",
    "have existed but for the exhaustion of",
    'underlying limits for "bodily injury". To the',
    "extent this exclusion does not apply, the",
    "insurance provided under this Coverage Part",
    "for the employer's liability risks described",
    "above will follow the same provisions,",
    "exclusions and limitations that are contained.",
]


def test_two_column_prose_is_read_down_each_column(tmp_path):
    """The client's page 151. Read across, the two columns form sentences that do
    not exist in the document - an exclusion spliced into the exception that
    reinstates it."""
    p = str(tmp_path / "prose.pdf")
    _two_col_pdf(p, PROSE_L, PROSE_R)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        raw = pg.extract_text() or ""
        text, _ = page_text(pg)
    assert "Similar Laws This exclusion does not apply" in " ".join(raw.split()), \
        "fixture must reproduce the read-across defect"
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[:len(PROSE_L)] == PROSE_L
    assert lines[len(PROSE_L):] == PROSE_R


def test_label_value_columns_are_never_reordered(tmp_path):
    """The client's page 205 limits block. IDENTICAL geometry to the prose page -
    one gutter, both sides populated - but reordering orphans every amount from
    its label. Nothing in the layout separates the two cases; the text does."""
    labels = ["Each Occurrence Limit", "Damage To Premises Rented To You Limit",
              "Medical Expense Limit", "General Aggregate Limit",
              "Products/Completed Operations Aggregate Limit"]
    values = ["$1,000,000", "$500,000", "$10,000", "$2,000,000", "$2,000,000"]
    p = str(tmp_path / "limits.pdf")
    _two_col_pdf(p, labels, values)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        assert column_bands(page_words(pg)[0]) == []
        text, repaired = page_text(pg)
        assert repaired == 0
        assert text == (pg.extract_text() or "")
    assert "Each Occurrence Limit $1,000,000" in text


def test_column_reorder_loses_no_characters(tmp_path):
    p = str(tmp_path / "prose.pdf")
    _two_col_pdf(p, PROSE_L, PROSE_R)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        before = collections.Counter(c for c in (pg.extract_text() or "") if not c.isspace())
        after = collections.Counter(c for c in page_text(pg)[0] if not c.isspace())
    assert before == after


def test_single_column_page_has_no_bands(tmp_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    p = str(tmp_path / "single.pdf")
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica", 9)
    for i, t in enumerate([
        "The applicant operates a roofing and electrical contracting business",
        "from a single premises in Denver, Colorado. Crews perform installation",
        "and repair work at customer sites throughout the metropolitan area.",
        "No manufacturing is performed and no vehicles are garaged off site.",
        "Coverage is requested effective 07/15/2026 for a period of one year.",
    ]):
        c.drawString(60, 700 - i * 14, t)
    c.showPage(); c.save()
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        assert column_bands(page_words(pg)[0]) == []
        assert page_text(pg)[0] == (pg.extract_text() or "")


# ─────────────────────────────────────────────────────────────────────────────
# 3c. LETTER-SPACED (TELETYPE) LINES
# ─────────────────────────────────────────────────────────────────────────────

def _spaced_pdf(path, lines, *, tracking=6.5):
    """Glyph-by-glyph placement, so the gap BETWEEN LETTERS equals a word gap -
    the EMC teletype declarations shape."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Courier", 9)
    for row, text in enumerate(lines):
        x = 60.0
        for ch in text:
            if ch == " ":
                x += tracking * 2          # word break: clearly wider than tracking
                continue
            c.drawString(x, 700 - row * 16, ch)
            x += 6.4 + tracking
    c.showPage()
    c.save()


def test_letter_spaced_policy_number_is_rejoined(tmp_path):
    """`6 C 7 - 4 0 - 0 2---26` reached a client's ACORD 125 (see CLAUDE.md).
    The glyph gap on those pages is 6.56pt against a 6.41pt glyph - identical to
    a WORD gap on an ordinary line, which is why pdfplumber cannot split it."""
    p = str(tmp_path / "teletype.pdf")
    _spaced_pdf(p, ["POLICY NUMBER 6C7-40-02---26", "NAMED INSURED: PRODUCER:"])
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        raw = pg.extract_text() or ""
        text, repaired = page_text(pg)
    assert "6 C 7" in raw, "fixture must reproduce the split"
    assert repaired >= 1
    assert "POLICY NUMBER 6C7-40-02---26" in text
    assert "NAMED INSURED: PRODUCER:" in text


def test_ordinary_table_row_is_not_treated_as_letter_spaced(tmp_path):
    """The bug this caught in development: negative (kerned) gaps were DROPPED
    from the sample, so only the wide column gaps remained and a three-cell table
    row scored a 14pt 'tracking'. It rebuilt `Pillar Weight What it measures` as
    letter-spaced text and cost the SQS spec 4 of its 7 tables."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    p = str(tmp_path / "row.pdf")
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica", 9)
    for row, cells in enumerate([("Pillar", "Weight", "What it measures"),
                                 ("Structural Completeness", "25%", "Core application data"),
                                 ("Exposure Consistency", "25%", "Class codes and payroll")]):
        for x, cell in zip((60, 260, 360), cells):
            c.drawString(x, 700 - row * 14, cell)
    c.showPage(); c.save()
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        text, repaired = page_text(pg)
        assert repaired == 0
        assert text == (pg.extract_text() or "")
    assert "What it measures" in text


def test_despacing_never_loses_a_character(tmp_path):
    """The second development bug: the replaced-word band padded by _Y_TOL and
    swallowed the neighbouring line, deleting its words outright - 112 pages of
    character loss on the client's package."""
    p = str(tmp_path / "teletype.pdf")
    _spaced_pdf(p, ["POLICY NUMBER 6C7-40-02---26",
                    "NAMED INSURED: PRODUCER:",
                    "ORBIN CONTRACTING LLC"])
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        before = collections.Counter(c for c in (pg.extract_text() or "") if not c.isspace())
        after = collections.Counter(c for c in page_text(pg)[0] if not c.isspace())
    assert before == after


# ─────────────────────────────────────────────────────────────────────────────
# 3d. SIDE-BY-SIDE IDENTITY BLOCKS (Named Insured | Producer)
# ─────────────────────────────────────────────────────────────────────────────

IDENT_L = ["Named Insured", "ORBIN CONTRACTING LLC", "4800 DAHLIA ST # D13",
           "DENVER, CO 80216-3121", "DIRECT BILL", "Organization Type LLC",
           "Business Phone 303 555 0175"]
IDENT_R = ["Producer", "COMMERCIAL RISK SOLUTIONS, INC.", "9780 S MERIDIAN BLVD STE 400",
           "ENGLEWOOD, CO 80112-6072", "AGENT NO. W6258", "AGENT PHONE 303 996 7800",
           "CLAIM REPORTING 888 362 2255"]


def test_named_insured_and_producer_are_separated(tmp_path):
    """The client-reported "producer details stamped on the insured" defect at its
    source. Read across, the insured's name and the producer's arrive on one line
    and the producer's street sits directly under the insured's."""
    p = str(tmp_path / "ident.pdf")
    _two_col_pdf(p, IDENT_L, IDENT_R, gutter_x=260)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        raw = pg.extract_text() or ""
        text, _ = page_text(pg)
    assert "ORBIN CONTRACTING LLC COMMERCIAL RISK SOLUTIONS" in raw, "fixture must merge them"
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[:len(IDENT_L)] == IDENT_L
    assert lines[len(IDENT_L):] == IDENT_R


def test_identity_split_needs_an_address_in_both_columns(tmp_path):
    """ACORD 127 p2's `DESCRIPTION OF GARAGE / STORAGE LOCATIONS | MAXIMUM DOLLAR
    VALUE SUBJECT TO LOSS` is the same shape with no postal line, and splitting a
    blank form's label grid separates every printed label from its box."""
    p = str(tmp_path / "labels.pdf")
    _two_col_pdf(p, ["INTEREST NAME AND ADDRESS", "RANK:", "ADDITIONAL INSURED", "LOSS PAYEE"],
                 ["MAXIMUM DOLLAR VALUE", "Describe:", "CERTIFICATE RECIPIENT", "MORTGAGEE"],
                 gutter_x=280)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        assert column_bands(page_words(pg)[0]) == []
        assert page_text(pg)[0] == (pg.extract_text() or "")


def test_short_coincidental_column_run_is_not_reordered(tmp_path):
    """ACORD 126 p5: a four-line fraud notice whose words happen to align. Real
    two-column prose runs long - the client's package median band is 38 lines."""
    p = str(tmp_path / "short.pdf")
    _two_col_pdf(p, ["insurance: Any person who knowingly and",
                     "statement of claim containing any materially",
                     "material thereto, commits a fraudulent act,"],
                 ["company or other person files an application",
                  "the purpose of misleading, information",
                  "also be subject to a civil penalty"], gutter_x=300)
    with pdfplumber.open(p) as pdf:
        pg = pdf.pages[0]
        assert column_bands(page_words(pg)[0]) == []


def test_render_is_single_newline_and_survives_clean_text():
    block = render_tables([{"section": "CLAIM DETAIL", "header": ["A", "B", "C"],
                            "rows": [["1", "2", "3"], ["x", "y", "z"]]}], 4)
    assert "\n\n" not in block
    assert block.startswith(TABLE_OPEN.format(page=4, section=" - CLAIM DETAIL"))
    assert block.endswith(TABLE_CLOSE)
    assert clean_text("Some page text\n" + block).count("1 | 2 | 3") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. WIRING - extract_text_from_pdf
# ─────────────────────────────────────────────────────────────────────────────

@needs_pkg
def test_single_page_text_is_old_text_plus_inline_table():
    """The dec page: the 1,700 chars the model saw before, byte-for-byte, then the
    schedule as a table. Nothing reordered, nothing lost, no page marker."""
    with pdfplumber.open(DEC) as pdf:
        old = pdf.pages[0].extract_text() or ""
    text, low_conf = asyncio.run(ocr_service.extract_text_from_pdf(DEC))
    assert text.startswith(old)
    assert "[Document page" not in text
    assert text.count("[Table - page 1 - SCHEDULE OF COVERAGE PARTS]") == 1
    assert low_conf == []


@needs_pkg
def test_loss_run_reaches_the_model_repaired():
    text, _ = asyncio.run(ocr_service.extract_text_from_pdf(LOSS))
    assert "pa$rt4y" not in text
    assert "third party $4,850 $0 Closed" in text
    assert "| $4,850 | $0 | Closed" in text


def _stub_vision_empty(monkeypatch):
    """No OCR provider in tests. tests/test_arq_acord125_missing_only.py installs a
    permanent sys.modules stub of `circuitbreaker` (see test_ocr_embedded_images),
    so any test that lets a blank page reach the Vision path is order-dependent
    unless it stubs both the breaker and the provider."""
    class _CB:
        opened = False
        def call(self, fn, *a, **k):
            return fn(*a, **k)
    monkeypatch.setattr(ocr_service, "_vision_cb", _CB())
    monkeypatch.setattr(ocr_service, "_vision_batch_call",
                        lambda payloads: [ocr_service._OcrResult(text="") for _ in payloads])


def test_multi_page_markers_only_on_pages_with_content(tmp_path, monkeypatch):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    _stub_vision_empty(monkeypatch)
    p = str(tmp_path / "three.pdf")
    c = canvas.Canvas(p, pagesize=letter)
    c.drawString(72, 700, "Page one has text.")
    c.showPage()
    c.showPage()                                  # page two is blank
    c.drawString(72, 700, "Page three has text.")
    c.showPage()
    c.save()
    text, _ = asyncio.run(ocr_service.extract_text_from_pdf(p))
    assert text.splitlines()[0] == "[Document page 1]"
    assert "[Document page 2]" not in text
    assert "[Document page 3]" in text
    assert text.index("[Document page 1]") < text.index("Page one") < text.index("[Document page 3]")


def test_blank_multi_page_pdf_still_reads_as_empty(tmp_path, monkeypatch):
    """Markers must not turn a blank scan into >= 30 chars of 'content'."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    p = str(tmp_path / "blank.pdf")
    c = canvas.Canvas(p, pagesize=letter)
    c.showPage(); c.showPage(); c.showPage(); c.save()
    monkeypatch.setattr(ocr_service, "_vision_cb", type("CB", (), {"opened": False,
                        "call": lambda self, fn, *a, **k: fn(*a, **k)})())
    monkeypatch.setattr(ocr_service, "_vision_batch_call",
                        lambda payloads: [ocr_service._OcrResult(text="") for _ in payloads])
    text, _ = asyncio.run(ocr_service.extract_text_from_pdf(p))
    assert "[Document page" not in text
    assert len(text) < 30


def test_ocr_result_words_default_is_empty():
    r = ocr_service._OcrResult(text="x", low_conf=[], total_tokens=1)
    assert r.words == [] and r.ok is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. WIRING - scanned pages and embedded images run the same detector
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_vision_table():
    """A 3-column, 2-row schedule in Vision pixel space (300 dpi-ish boxes)."""
    rows = [("VIN", "YEAR", "MAKE"), ("1FTFW1E5", "2021", "Ford"), ("4S4BRC", "2012", "Subaru")]
    xs = (100.0, 500.0, 800.0)
    words = []
    for r, row in enumerate(rows):
        top = 200.0 + r * 60.0
        for x, tok in zip(xs, row):
            words.append({"x0": x, "x1": x + 18.0 * len(tok), "top": top, "bottom": top + 30.0, "text": tok})
    text = "\n".join(" ".join(row) for row in rows)
    return text, words


def _install_fake_vision(monkeypatch, text, words):
    class _CB:
        opened = False
        def call(self, fn, *a, **k):
            return fn(*a, **k)
    monkeypatch.setattr(ocr_service, "_vision_cb", _CB())
    monkeypatch.setattr(
        ocr_service, "_vision_batch_call",
        lambda payloads: [ocr_service._OcrResult(text=text, low_conf=[], total_tokens=6, words=list(words))
                          for _ in payloads],
    )


def test_scanned_page_gets_a_table_from_vision_boxes(tmp_path, monkeypatch):
    from tests.test_ocr_embedded_images import build_scanned_page
    text, words = _synthetic_vision_table()
    _install_fake_vision(monkeypatch, text, words)
    p = str(tmp_path / "scan.pdf")
    build_scanned_page(p)
    out, _ = asyncio.run(ocr_service.extract_text_from_pdf(p))
    assert "VIN YEAR MAKE" in out, "OCR text must still be present"
    assert "[Table - page 1]" in out
    assert "1FTFW1E5 | 2021 | Ford" in out
    assert out.index("VIN YEAR MAKE") < out.index("[Table - page 1]")


def test_embedded_image_gets_a_table_after_its_image_block(tmp_path, monkeypatch):
    from tests.test_ocr_embedded_images import build_text_page_with_image
    text, words = _synthetic_vision_table()
    _install_fake_vision(monkeypatch, text, words)
    p = str(tmp_path / "pasted.pdf")
    build_text_page_with_image(p, 400, 300)
    out, _ = asyncio.run(ocr_service.extract_text_from_pdf(p))
    marker = ocr_service._EMBEDDED_IMAGE_MARKER.format(page=1)
    assert marker in out
    assert "4S4BRC | 2012 | Subaru" in out
    assert out.index(marker) < out.index("[Table - page 1]"), "table follows its own image block"
    assert "Declarations continued" in out, "native text untouched"
