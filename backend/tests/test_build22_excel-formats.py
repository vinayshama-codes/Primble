"""Build 22 (21 Oct 2026, second run), lane X - excel-formats (25sepChanges.md Z31-X).

PART 1 - EVERY EXCEL NUMBER FORMAT, IN BOTH READERS, FROM ONE SET OF VECTORS.
The schedule tables' import (frontend/src/utils/scheduleImport.js) and the
Excel-as-document reader (utils/spreadsheet_text.py) read only the first section
of a cell's number format, and only dates, percents and zero-padded digits: a
conditional ZIP format [<=99999]00000;00000-0000 turned 85401234 into "85401234"
(Excel shows 08540-1234), a year-only "yyyy" or month-only "mmmm" date became a
whole date (the sheet shows "2020" / "March"), currency / accounting / phone /
fraction / scientific cells printed the bare stored number. Now ONE renderer,
written twice (utils/excel_number_format.py, frontend/src/utils/
excelNumberFormat.js), reads every format; tests/fixtures/
excel_number_format_vectors.json (453 cases, every expectation typed by hand from
Excel's documented display) is replayed through BOTH, and a seeded fuzz holds
the two languages equal beyond the vectors. A full date is still MM/DD/YYYY.

PART 2 - THE UNUSED ZIP READER IS GONE. ocr_service.extract_zip had no caller;
the ONE ZIP door is services/upload_intake.store_uploads. There, "password-
protected" is said only of an encrypted entry; any other entry zipfile cannot
unpack (an unsupported compression method - NotImplementedError IS a
RuntimeError) gets a plain refusal.

The adversarial cases come first: a code that is malformed or random must never
raise and never disagree between the languages; a value no format can show is
never a made-up date; a numeric table column never loses the number a cell holds.
"""
from __future__ import annotations

import ast
import asyncio
import io
import json
import random
import re
import shutil
import subprocess
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import services.upload_intake as ui
import utils.excel_number_format as nf
import utils.spreadsheet_text as st

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_FIX = Path(__file__).resolve().parent / "fixtures"
_VECTORS_FILE = _FIX / "excel_number_format_vectors.json"
_VECTORS = json.loads(_VECTORS_FILE.read_text(encoding="utf-8"))["vectors"]
_DRIVERS_XLSX = _FIX / "brent_driver_schedule_17oct.xlsx"
_CLAIMS_XLSX = _FIX / "brent_synthetic_claims_17oct.xlsx"
_EM = ("\u2014", "\u2013")


def _node(tmp_path, body, name="check.mjs"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / name
    script.write_text(
        f"import * as S from {json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
        f"import * as N from {json.dumps((_FRONT / 'utils' / 'excelNumberFormat.js').as_uri())};\n"
        "import fs from 'node:fs';\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        "const file = (p, name) => { const b = fs.readFileSync(p); b.name = name; return b; };\n"
        + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _py(v):
    """One vector through the Python renderer, the way the reader calls it."""
    if v["type"] == "n":
        return nf.format_cell_number(v["value"], v["code"], v["date1904"])
    if v["type"] == "s":
        return nf.format_text(v["value"], v["code"])
    return nf.format_iso_date(v["value"], v["code"], v["date1904"])


_JS_VECTOR = ("(v) => v.type === 'n' ? N.formatCellNumber(v.value, v.code, v.date1904)"
              " : v.type === 's' ? N.formatText(v.value, v.code) : N.formatIsoDateCell(v.value, v.code, v.date1904)")


# ── a small .xlsx writer: the parts a real workbook has ──────────────────────────
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
       'content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
       'officedocument.spreadsheetml.sheet.main+xml"/></Types>')


def _book(path, data, *, num_fmts=None, xf_ids=None, shared=None, workbook_pr=""):
    """One sheet; `num_fmts` {id: code} and `xf_ids` (the cellXfs numFmtIds,
    index = a cell's s="...") make the styles part."""
    rels = [f'<Relationship Id="rId1" Type="{_REL}worksheet" Target="worksheets/sheet1.xml"/>']
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<?xml version="1.0"?><worksheet xmlns="{_NS}"><sheetData>{data}</sheetData></worksheet>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{_NS}" xmlns:r="{_R_NS}">'
                                      f'{workbook_pr}<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets>'
                                      '</workbook>')
        if xf_ids is not None:
            nfs = "".join(f'<numFmt numFmtId="{i}" formatCode={quoteattr(c)}/>' for i, c in (num_fmts or {}).items())
            xfs = "".join(f'<xf numFmtId="{i}" fontId="0" fillId="0" borderId="0" xfId="0"/>' for i in xf_ids)
            z.writestr("xl/styles.xml", f'<?xml version="1.0"?><styleSheet xmlns="{_NS}">'
                                        f'<numFmts count="{len(num_fmts or {})}">{nfs}</numFmts>'
                                        f'<cellXfs count="{len(xf_ids)}">{xfs}</cellXfs></styleSheet>')
            rels.append(f'<Relationship Id="rIdS" Type="{_REL}styles" Target="styles.xml"/>')
        if shared is not None:
            sis = "".join(f"<si><t xml:space=\"preserve\">{escape(s)}</t></si>" for s in shared)
            z.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><sst xmlns="{_NS}">{sis}</sst>')
            rels.append(f'<Relationship Id="rIdT" Type="{_REL}sharedStrings" Target="sharedStrings.xml"/>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                                                 f'openxmlformats.org/package/2006/relationships">{"".join(rels)}'
                                                 '</Relationships>')
    return path


def _row(r, *cells):
    return f'<row r="{r}">{"".join(cells)}</row>'


def _c(ref, v, s=None, t=None):
    attrs = f' s="{s}"' if s is not None else ""
    attrs += f' t="{t}"' if t is not None else ""
    return f'<c r="{ref}"{attrs}><v>{escape(str(v))}</v></c>'


def _serial(d):
    n = (d - date(1899, 12, 30)).days
    return n if n >= 61 else n - 1


def _both_readers(tmp_path, path):
    """(Python rows, frontend rows): the document reader and the schedule
    import's parseXLSX, each cell whitespace-collapsed as the document text is."""
    py = st.read_xlsx(str(path))[0]["rows"]
    o = _node(tmp_path, f"out(await S.parseXLSX(fs.readFileSync({json.dumps(str(path))})));")
    rows = [[" ".join(str(c).split()) for c in r] for r in o]
    # the document reader drops a column no row uses (its own rule): so does this view
    width = max((len(r) for r in rows), default=0)
    used = [i for i in range(width) if any(i < len(r) and r[i] for r in rows)]
    js = []
    for r in rows:
        cells = [r[i] if i < len(r) else "" for i in used]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            js.append(cells)
    return py, js


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - adversarial first: never raise, never disagree, never invent
# ══════════════════════════════════════════════════════════════════════════════

_SOUP = list('0#?.,%E+-/@"\\_*[]$;:() ymdhsabeAMPGenral') + ["General", "[Red]", "[<=99999]", "[$-409]",
                                                              "[h]", "AM/PM", "0.00", "yyyy", "# ?/?"]


def _random_codes(seed, count):
    rnd = random.Random(seed)
    return ["".join(rnd.choice(_SOUP) for _ in range(rnd.randint(0, 14))) for _ in range(count)]


def test_a_random_or_broken_code_never_raises_in_python():
    """2,000 random codes (unbalanced quotes / brackets, stray sections, digit
    placeholders inside dates) and the pathological shapes: always a string."""
    codes = _random_codes(22, 2000) + ['"', "[", "]", "\\", "_", "*", ";;;;;", "0" * 5000, "%" * 300,
                                      ",,,,,,,,,,", "[>]", "[=x]0", "[h", "E+", "e-", "/", "?/", "#/0",
                                      "0/0", "\u4e0a\u5348/\u4e0b\u5348", "\u0130", "\U0001f600 0"]
    values = ["0", "-1", "1e308", "-1e308", "5e-324", "0.5", "45730.5625", "abc", "", "1e400"]
    for code in codes:
        for v in values:
            assert isinstance(nf.format_cell_number(v, code), str)
            assert isinstance(nf.format_cell_number(v, code, True), str)
        assert isinstance(nf.format_text("x", code), str)
        assert isinstance(nf.format_iso_date("2025-03-14T13:30:00", code), str)
        assert isinstance(nf.number_format_kind(code)["kind"], str)


def test_the_two_languages_agree_far_beyond_the_vectors(tmp_path):
    """The parity guarantee itself: every vector code plus seeded random codes,
    across ordinary, edge and random values, both date systems, text and ISO
    cells - the frontend and the backend produce the SAME text, case for case
    (the JS side also proves it never throws: node would exit non-zero)."""
    rnd = random.Random(1021)
    codes = sorted({v["code"] for v in _VECTORS}) + _random_codes(7, 150)
    values = ["0", "1", "-1", "0.5", "-0.5", "12.5", "0.125", "8540", "85401234", "3035551234", "1234.5",
              "-1234.5", "0.30000000000000004", "123456789012", "1E-20", "2.675", "9.999", "999.96", "45730",
              "45730.5625", "0.5625", "59", "60", "61", "2958465", "2958466", "-0.001", "3.141592653589793",
              "1e308", "5e-324", "12345678901234567", "1E+100", "-0"]
    values += [repr(rnd.uniform(-1e7, 1e7)) for _ in range(12)] + [repr(rnd.uniform(0, 3e6)) for _ in range(6)]
    cases = [[c, v, d] for c in codes for v in values for d in (False, True)]
    texts = ["Bob", "", " x ", "45729"]
    isos = ["2025-03-14T13:30:00", "2025-03-14", "1900-02-28", "1900-03-01", "1899-12-31T12:00:00",
            "2025-02-31", "abc", "2025-03-14T13:30:15.5Z"]
    data = tmp_path / "cases.json"
    data.write_text(json.dumps({"cases": cases, "codes": codes, "texts": texts, "isos": isos}), encoding="utf-8")
    o = _node(tmp_path, f"""
const {{cases, codes, texts, isos}} = JSON.parse(fs.readFileSync({json.dumps(str(data))}, 'utf8'));
out({{num: cases.map(([c, v, d]) => N.formatCellNumber(v, c, d)),
      txt: codes.flatMap((c) => texts.map((t) => N.formatText(t, c))),
      iso: codes.flatMap((c) => isos.flatMap((t) => [false, true].map((d) => N.formatIsoDateCell(t, c, d)))),
      kind: codes.map((c) => N.numberFormatKind(c).kind)}});
""")
    py_num = [nf.format_cell_number(v, c, d) for c, v, d in cases]
    diff = [(cases[i], py_num[i], o["num"][i]) for i in range(len(cases)) if py_num[i] != o["num"][i]]
    assert not diff, diff[:10]
    assert o["txt"] == [nf.format_text(t, c) for c in codes for t in texts]
    assert o["iso"] == [nf.format_iso_date(t, c, d) for c in codes for t in isos for d in (False, True)]
    assert o["kind"] == [nf.number_format_kind(c)["kind"] for c in codes]
    assert len(cases) > 25_000


def test_a_value_no_format_can_show_is_general_never_a_made_up_date():
    """A negative date or time, the phantom 02/29/1900 and 01/00/1900 in any
    format that shows a date part, and a day past 12/31/9999 print as General -
    in a full date, a year-only, a month-only, a weekday and a date-time format.
    A time-only format reads the time of day, which day 0 has."""
    for code in ("m/d/yyyy", "yyyy", "mmmm", "dddd", "d", "m/d/yyyy h:mm", "mmm-yy"):
        assert nf.format_cell_number("60", code) == "60"
        assert nf.format_cell_number("0", code) == "0"
        assert nf.format_cell_number("-1", code) == "-1"
        assert nf.format_cell_number("2958466", code) == "2958466"
        assert nf.format_cell_number("2957004", code, True) == "2957004"
    assert nf.format_cell_number("0.5", "h:mm") == "12:00"
    assert nf.format_cell_number("60.5", "h:mm") == "12:00"
    assert nf.format_cell_number("-0.5", "[h]:mm") == "-0.5"
    assert nf.format_cell_number("59.99999999", "m/d/yyyy h:mm") == "59.99999999"   # rounds into day 60


def test_a_malformed_code_leaves_text_alone_and_shows_numbers_as_general():
    for code in ("0;0;0;0;0", '"abc', "[Red 0", "0.0 m", "yyyy 0", "0" * 1100, "mm/dd/yyyy@0"):
        assert nf.format_cell_number("1234.5", code) == "1234.5"
        assert nf.format_cell_number("-2.5", code) == "-2.5"
        assert nf.format_text("abc", code) == "abc"
    # a long but real code is not malformed: 300 zero placeholders pad to 300 digits
    assert nf.format_cell_number("5", "0" * 300) == "0" * 299 + "5"


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - the shared vectors, through both languages
# ══════════════════════════════════════════════════════════════════════════════

def test_the_vectors_cover_every_kind_of_format_the_spec_names():
    groups = {v["group"] for v in _VECTORS}
    assert groups == {"general", "number", "literal", "accounting", "percent", "scaling", "ids", "scientific",
                      "fraction", "full date", "partial date", "time", "date time", "text", "iso", "malformed"}
    assert len(_VECTORS) >= 400
    assert {v["type"] for v in _VECTORS} == {"n", "s", "d"}
    assert any(v["date1904"] for v in _VECTORS) and any(not v["date1904"] for v in _VECTORS)
    codes = {v["code"] for v in _VECTORS}
    # the spec's own examples
    for code in ("[<=99999]00000;00000-0000", "yyyy", "mmmm", "mmm-yy", "h:mm AM/PM",
                 "[<=9999999]###-####;(###) ###-####", "000-00-0000", "0.0%", "$#,##0.00", "0.00E+00",
                 "# ?/?", "[$$-409]#,##0.00", "#,##0.00 [$EUR]",
                 "[$CHF-100C] #,##0.00", "[Red]0.00", "[Color10]0", "##0.0E+0", "# ?/8", "##/100", "???/???",
                 "[h]:mm:ss", "[mm]:ss", "[s]", "mm:ss.0", "h:mm A/P", "m/d/e", "dd/mm/bbbb", "@", ";;;"):
        assert code in codes, code
    assert all(isinstance(v["expect"], str) for v in _VECTORS)


@pytest.mark.parametrize("vec", _VECTORS, ids=[f"{i}-{v['group']}" for i, v in enumerate(_VECTORS)])
def test_the_document_reader_renders_every_vector(vec):
    assert _py(vec) == vec["expect"], (vec["code"], vec["value"], vec["date1904"])


def test_the_schedule_import_renders_every_vector(tmp_path):
    o = _node(tmp_path, f"""
const V = JSON.parse(fs.readFileSync({json.dumps(str(_VECTORS_FILE))}, 'utf8')).vectors;
out(V.map({_JS_VECTOR}));
""")
    wrong = [(v["code"], v["value"], v["date1904"], v["expect"], got) for v, got in zip(_VECTORS, o)
             if got != v["expect"]]
    assert wrong == []


def test_the_spec_examples_read_as_the_sheet_shows_them():
    """Z31-X's own list, one line each (both languages hold these through the vectors)."""
    f = nf.format_cell_number
    assert f("85401234", "[<=99999]00000;00000-0000") == "08540-1234"
    assert f("8540", "[<=99999]00000;00000-0000") == "08540"
    assert f("43831", "yyyy") == "2020"
    assert f("43891", "mmmm") == "March"
    assert f("43891", "mmm-yy") == "Mar-20"
    assert f(repr(0.5625), "h:mm AM/PM") == "1:30 PM"
    assert f("5551234567", "[<=9999999]###-####;(###) ###-####") == "(555) 123-4567"
    assert f("123456789", "000-00-0000") == "123-45-6789"
    assert f("0.125", "0.0%") == "12.5%"
    assert f("1234.5", "$#,##0.00") == "$1,234.50"
    assert f("-1234", '_(* #,##0_);_(* \\(#,##0\\);_(* "-"_);_(@_)').strip() == "(1,234)"
    assert f("123456", "0.00E+00") == "1.23E+05"
    assert f("1.25", "# ?/?") == "1 1/4"
    assert f("45730", "m/d/yyyy") == "03/14/2025"                    # today's rule for full dates


def test_the_z30_outputs_that_changed_are_what_the_sheet_shows(tmp_path):
    """Seven outputs the 21 Oct reader pinned and Excel does not show (the two
    Z30 test files were updated to these, in the same run)."""
    cases = [("0.5", "h:mm", "12:00"), ("45000.5", "h:mm", "12:00"), ("-0.001", "0%", "-0%"),
             ("12.5", "00000", "00013"), ("-5", "00000", "-00005"), ("1200000", "#,##0", "1,200,000"),
             ("0.25", "h:mm", "6:00"), ("45730", "yyyy-mm", "2025-03"), ("12", '0 "days"', "12 days"),
             ("12", "0\\d", "12d"), ("45730", "d-mmm", "14-Mar"), ("45730", "mmm-yy", "Mar-25"),
             ("12000", '_("$"* #,##0.00_)', " $12,000.00 "), ("0012", "General", "12")]
    o = _node(tmp_path, f"out({json.dumps(cases)}.map(([v, c]) => S.formatCellNumber(v, c)));")
    assert o == [want for _v, _c, want in cases]
    assert [nf.format_cell_number(v, c) for v, c, _w in cases] == o
    # built-in 47 is Excel's "mm:ss.0" (the standard misprints "mmss.0")
    assert nf.builtin_format_code(47) == "mm:ss.0"
    assert nf.format_cell_number(repr(0.5625 + 15 / 86400), nf.builtin_format_code(47)) == "30:15.0"


def test_builtin_ids_are_one_table_in_both_languages(tmp_path):
    ids = list(range(0, 200)) + [-1, 164, 1000]
    o = _node(tmp_path, f"out({json.dumps(ids)}.map((i) => S.builtinFormatCode(i)));")
    assert o == [st.builtin_format_code(i) for i in ids]
    by = dict(zip(ids, o))
    assert by[0] == "General" and by[14] == "m/d/yyyy" and by[22] == "m/d/yyyy h:mm" and by[49] == "@"
    assert by[58] == by[27] == by[50] == "m/d/yyyy"                     # the locale ids en-US Excel shows
    assert by[44] == '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)'    # Brent's file's own 44
    assert by[41].startswith("_(* #,##0_)") and by[42].startswith('_("$"* #,##0_)')
    assert by[164] == by[1000] == by[-1] == by[23] == "General"
    assert st.builtin_format_code("14") == "m/d/yyyy" and st.builtin_format_code("x") == "General"
    assert st.builtin_format_code(True) == "General" and st.builtin_format_code(14.5) == "General"


def test_per_mille_and_lowercase_exponents_read_the_same_in_both_languages(tmp_path):
    """Excel has no per-mille placeholder: a "\u2030" prints as typed and scales
    nothing. A lowercase e+ keeps its case. (Rules of this build, not vectors.)"""
    cases = [("5", "0\u2030"), ("123456", "0.00e+00"), ("0.000123", "0.0e-0")]
    o = _node(tmp_path, f"out({json.dumps(cases)}.map(([v, c]) => N.formatCellNumber(v, c)));")
    assert o == ["5\u2030", "1.23e+05", "1.2e-4"]
    assert o == [nf.format_cell_number(v, c) for v, c in cases]


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - the two workbook readers, cell for cell
# ══════════════════════════════════════════════════════════════════════════════

_MIXED_FORMATS = {
    164: "[<=99999]00000;00000-0000", 165: "yyyy", 166: "mmmm", 167: "mmm-yy", 168: "h:mm AM/PM",
    169: "[<=9999999]###-####;(###) ###-####", 170: "000-00-0000", 171: "# ??/??", 172: "0.00E+00",
    173: "0.0%", 174: '"Name: "@', 175: "m/d/yyyy h:mm", 176: "[h]:mm:ss", 177: "#,##0",
    178: "$#,##0.00_);($#,##0.00)", 179: '0 "units"',
}
_XF = [0] + list(_MIXED_FORMATS) + [44, 16, 47, 14, 9]          # s="1".. in this order


def _sx(fid):
    return _XF.index(fid)


def _mixed_book(path):
    d = _serial(date(2025, 3, 14))
    data = "".join([
        _row(1, _c("A1", 85401234, _sx(164)), _c("B1", 8540, _sx(164)), _c("C1", d, _sx(165)), _c("D1", d, _sx(166)),
             _c("E1", d, _sx(167)), _c("F1", 0.5625, _sx(168)), _c("G1", 3035551234, _sx(169)),
             _c("H1", 123456789, _sx(170)), _c("I1", 1.25, _sx(171)), _c("J1", 123456, _sx(172)),
             _c("K1", 0.125, _sx(173))),
        _row(2, _c("A2", 0, _sx(174), "s"), _c("B2", d + 0.5625, _sx(175)), _c("C2", 1.5625, _sx(176)),
             _c("D2", 1200000, _sx(177)), _c("E2", -1234.5, _sx(178)), _c("F2", 12, _sx(179)),
             _c("G2", 1234.5, _sx(44)), _c("H2", 0, _sx(44)), _c("I2", -1234.5, _sx(44)), _c("J2", d, _sx(16)),
             _c("K2", 0.5625 + 15.2 / 86400, _sx(47))),
        _row(3, _c("A3", 1, None, "b"), _c("B3", 0, _sx(14), "b"), _c("C3", "#N/A", _sx(14), "e"),
             _c("D3", "#DIV/0!", _sx(9), "e"), _c("E3", "#VALUE!", _sx(44), "e"), _c("F3", 1, _sx(174), "s"),
             _c("G3", "2025-03-14T13:30:00", _sx(165), "d"), _c("H3", "2025-03-14", None, "d"),
             _c("I3", "0.30000000000000004"), _c("J3", 123456789012), _c("K3", 2, None, "s")),
    ])
    return _book(path, data, num_fmts=_MIXED_FORMATS, xf_ids=_XF,
                 shared=["Bob", "Line one_x000D_\nline two", "code _x005F_x0041_"])


_MIXED_EXPECTED = [
    ["08540-1234", "08540", "2025", "March", "Mar-25", "1:30 PM", "(303) 555-1234", "123-45-6789", "1 1/4",
     "1.23E+05", "12.5%"],
    ["Name: Bob", "03/14/2025 13:30", "37:30:00", "1,200,000", "($1,234.50)", "12 units", "$1,234.50", "$-",
     "$(1,234.50)", "14-Mar", "30:15.2"],
    # J3: a 12-digit General number keeps every digit in the readers (review
    # fix 3 - Excel's own cell shows 1.23457E+11, which the renderer still gives)
    ["TRUE", "FALSE", "#N/A", "#DIV/0!", "#VALUE!", "Name: Line one line two", "2025", "03/14/2025", "0.3",
     "123456789012", "code _x0041_"],
]


def test_both_workbook_readers_show_every_cell_as_the_sheet_does(tmp_path):
    """The spec's formats in a real workbook: conditional ZIP, year-only,
    month-only, month-year, a time, phone, SSN, a fraction, scientific, percent,
    a text section, a date-time, elapsed hours, separators, accounting (Excel's
    built-in 44, which a file need not define), literals, built-in 16 / 47,
    booleans and errors under date / percent / accounting formats, an ISO date
    cell, General noise and a 12-digit number, Excel's _xHHHH_ escapes - the
    document reader and the schedule import read every cell the same."""
    py, js = _both_readers(tmp_path, _mixed_book(tmp_path / "mixed.xlsx"))
    assert py == _MIXED_EXPECTED
    assert js == py


def test_error_and_boolean_cells_are_one_rule_in_both_readers(tmp_path):
    """An error cell reads as its error code whatever its format; a boolean as
    TRUE / FALSE; a crafted boolean value is kept as written (and never a
    JavaScript property: "constructor" stays "constructor")."""
    errors = ["#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!",
              "#GETTING_DATA"]
    styles = [None, _sx(14), _sx(9), _sx(44), _sx(173)]
    cells = [_c(f"{chr(65 + i)}1", e, styles[i % len(styles)], "e") for i, e in enumerate(errors)]
    bools = [_c("A2", 1, _sx(14), "b"), _c("B2", 0, _sx(44), "b"), _c("C2", "constructor", None, "b"),
             _c("D2", " 1 ", None, "b")]
    p = _book(tmp_path / "e.xlsx", _row(1, *cells) + _row(2, *bools), num_fmts=_MIXED_FORMATS, xf_ids=_XF)
    py, js = _both_readers(tmp_path, p)
    assert py[0] == errors and py[1] == ["TRUE", "FALSE", "constructor", "TRUE"]
    assert js == py


def test_a_shared_string_index_outside_the_table_is_no_text_in_both_readers(tmp_path):
    """A crafted index past the table, or a negative one (Python would have read
    the LAST string), is an empty cell in both readers - formatted or not."""
    p = _book(tmp_path / "i.xlsx", _row(1, _c("A1", 0, _sx(174), "s"), _c("B1", -1, None, "s"),
                                        _c("C1", 99, _sx(174), "s"), _c("D1", 1, None, "s")),
              num_fmts=_MIXED_FORMATS, xf_ids=_XF, shared=["first", "last"])
    py, js = _both_readers(tmp_path, p)
    assert py == [["Name: first", "last"]]                              # B1 and C1 are empty cells
    assert js == py
    raw = _node(tmp_path, f"out(await S.parseXLSX(fs.readFileSync({json.dumps(str(p))})));", name="raw.mjs")
    assert raw == [["Name: first", "", "", "last"]]


def test_brents_two_files_still_read_the_same_in_both_readers(tmp_path):
    """His driver and claims workbooks (General numbers and full dates only)
    read exactly as before, in both readers."""
    for path in (_DRIVERS_XLSX, _CLAIMS_XLSX):
        py, js = _both_readers(tmp_path, path)
        assert js == py
    drivers = st.read_xlsx(str(_DRIVERS_XLSX))[0]["rows"]
    assert ["Daniel Mercer", "04/17/1982", "CO", "06/11/2018", "21"] in drivers
    claims = st.read_xlsx(str(_CLAIMS_XLSX))[0]["rows"]
    assert claims[1][5] == "03/13/2025" and claims[1][10] == "12000"


def test_the_1904_system_in_both_readers(tmp_path):
    p = _book(tmp_path / "y.xlsx", _row(1, _c("A1", 28596, _sx(14)), _c("B1", 0, _sx(165)), _c("C1", 59, _sx(14)),
                                        _c("D1", 0.5625, _sx(168))),
              num_fmts=_MIXED_FORMATS, xf_ids=_XF, workbook_pr='<workbookPr date1904="1"/>')
    py, js = _both_readers(tmp_path, p)
    assert py == [["04/17/1982", "1904", "02/29/1904", "1:30 PM"]]
    assert js == py


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - the schedule tables: what reaches a row
# ══════════════════════════════════════════════════════════════════════════════

def _cols(list_key):
    from services.schedule_capture import SCHEDULE_DEFS
    return json.loads(json.dumps(SCHEDULE_DEFS[list_key]["columns"]))


def test_a_numeric_column_never_loses_the_number_a_cell_holds(tmp_path):
    """Every cell now reads as the sheet shows it, and some of that is no number:
    an accounting zero "$ -", a negative "$(1,234.50)", "1.23E+05", "1 1/4".
    Read by the money reader those are nothing, or 1.23 / 1.0; the import used
    to take the stored value. A currency / count / percent column takes the
    stored number exactly then - and only then: "$1,234.50", "1,200,000",
    "12.5%" stay as shown, a date / text column is untouched, a CSV has no
    stored numbers."""
    loss = _cols("loss_history")
    p = _book(tmp_path / "loss.xlsx", "".join([
        _row(1, _c("A1", 0, None, "s"), _c("B1", 1, None, "s"), _c("C1", 2, None, "s"), _c("D1", 3, None, "s")),
        _row(2, _c("A2", 45730, _sx(14)), _c("B2", 4, None, "s"), _c("C2", 0, _sx(44)), _c("D2", 1234.5, _sx(44))),
        _row(3, _c("A3", 45731, _sx(14)), _c("B3", 4, None, "s"), _c("C3", -1234.5, _sx(44)), _c("D3", 123456, _sx(172))),
        _row(4, _c("A4", 45732, _sx(167)), _c("B4", 4, None, "s"), _c("C4", 1.25, _sx(171)), _c("D4", 0.125, _sx(173))),
    ]), num_fmts=_MIXED_FORMATS, xf_ids=_XF, shared=["Date of loss", "Line", "Paid", "Reserved", "Auto"])
    o = _node(tmp_path, f"""
const loss = {json.dumps(loss)};
const r = await S.parseScheduleFile(file({json.dumps(str(p))}, 'loss.xlsx'), loss);
const v = S.validateRows(r.rows, loss, []);
const csv = S.rowsFromMatrix([['Date of loss', 'Paid'], ['03/14/2025', '$ -'], ['03/15/2025', '(1,234.50)']], loss);
out({{rows: r.rows.map((x) => [x.date, x.paid, x.reserved_amount]), errors: v.errors,
      csv: csv.rows.map((x) => x.paid), json: JSON.stringify((await S.parseXLSX(fs.readFileSync({json.dumps(str(p))})))[1])}});
""")
    assert o["rows"] == [["03/14/2025", "0", "$1,234.50"],             # accounting zero: the stored 0
                         ["03/15/2025", "-1234.5", "123456"],           # bracket negative / scientific: stored
                         ["Mar-25", "1.25", "12.5%"]]                   # a month-year DATE stays as shown
    # the stored -1234.5 is flagged exactly as before (the table takes no minus);
    # the month-year date asks for the day the sheet does not show (the loss
    # description is a required column this file does not have, on every row)
    errs = {int(k): set(v) - {"description"} for k, v in o["errors"].items()}
    assert errs == {0: set(), 1: {"paid"}, 2: {"date"}}
    assert o["csv"] == ["$ -", "(1,234.50)"]                            # a CSV has no stored number: untouched
    # the stored numbers ride beside the row, never in it: the row is the sheet's text
    assert o["json"] == '["03/14/2025","Auto"," $-   "," $1,234.50 "]'
    # the server reads the imported amounts the same way the table does
    from services.schedule_capture import validate_rows
    _clean, report = validate_rows("loss_history", [dict(zip(["date", "paid", "reserved_amount"], r))
                                                   for r in o["rows"]])
    assert {int(k): set(v) - {"description"} for k, v in report["errors"].items()} == {0: set(), 1: {"paid"},
                                                                                      2: {"date"}}


def test_a_zip_column_and_a_year_column_take_the_sheets_own_text(tmp_path):
    """The defect this lane closes, on the location table: a conditional ZIP+4
    cell imports "08540-1234" (was "85401234"); a year-built cell shown as a
    year ("yyyy" over a full date) imports "2015" and passes the year check
    (the 21 Oct reader made it "01/01/2015", which failed)."""
    loc = _cols("property_locations")
    p = _book(tmp_path / "loc.xlsx", "".join([
        _row(1, _c("A1", 0, None, "s"), _c("B1", 1, None, "s"), _c("C1", 2, None, "s"), _c("D1", 3, None, "s"),
             _c("E1", 4, None, "s")),
        _row(2, _c("A2", 5, None, "s"), _c("B2", 6, None, "s"), _c("C2", 7, None, "s"), _c("D2", 85401234, _sx(164)),
             _c("E2", _serial(date(2015, 6, 1)), _sx(165))),
    ]), num_fmts=_MIXED_FORMATS, xf_ids=_XF,
        shared=["Street address", "City", "State", "ZIP", "Year built", "12 Oak St", "Princeton", "NJ"])
    o = _node(tmp_path, f"""
const loc = {json.dumps(loc)};
const r = await S.parseScheduleFile(file({json.dumps(str(p))}, 'loc.xlsx'), loc);
out({{row: r.rows[0], errors: S.validateRows(r.rows, loc, []).errors}});
""")
    assert o["row"]["address_zip"] == "08540-1234"
    assert o["row"]["year_built"] == "2015"
    assert o["errors"] == {}


def test_the_table_import_trims_the_pad_spaces_of_a_format(tmp_path):
    loss = _cols("loss_history")
    o = _node(tmp_path, f"""
const loss = {json.dumps(loss)};
const r = S.rowsFromMatrix([['Date of loss', 'Paid'], ['03/14/2025', ' $1,234.50 ']], loss);
out([r.rows[0].paid, S.validateCell(loss.find((c) => c.key === 'paid'), r.rows[0].paid)]);
""")
    assert o == ["$1,234.50", ""]


def test_the_frontend_modules_need_no_dom_and_carry_no_em_dash():
    for name in ("scheduleImport.js", "excelNumberFormat.js"):
        src = (_FRONT / "utils" / name).read_text(encoding="utf-8")
        assert "DOMParser" not in src and "querySelector" not in src
        assert not any(d in src for d in _EM)
    src = (_FRONT / "utils" / "excelNumberFormat.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*[\s\S]*?\*/", "", src)
    code = re.sub(r"//[^\n]*", "", code)
    # BigInt by call only: no 10n literals and no ** operator (a lower build
    # target transpiles ** to Math.pow, which throws on a BigInt)
    assert "BigInt(" in code
    assert not re.search(r"(?<![\w.$])[0-9]+n\b", code)
    assert "**" not in code
    py = (_BACKEND / "utils" / "excel_number_format.py").read_text(encoding="utf-8")
    assert not any(d in py for d in _EM)


def test_one_renderer_the_readers_hold_no_second_copy():
    """The old per-reader format code is gone: the document reader and the
    schedule import both import the renderer, and neither defines a format
    tokenizer of its own."""
    reader = (_BACKEND / "utils" / "spreadsheet_text.py").read_text(encoding="utf-8")
    assert "from utils.excel_number_format import" in reader
    for old in ("def _format_tokens", "def _format_sections", "def _percent_text", "def _zeros_text",
                "def _stored_number", "_BUILTIN_FORMATS"):
        assert old not in reader
    imp = (_FRONT / "utils" / "scheduleImport.js").read_text(encoding="utf-8")
    assert "from './excelNumberFormat.js'" in imp
    for old in ("function formatTokens", "function formatSections", "function percentText", "function zerosText",
                "function formatNumberAs", "const BUILTIN_FORMATS"):
        assert old not in imp


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW FIXES (21 Oct 2026 evening) - where the readers CONSUME the renderer
# ══════════════════════════════════════════════════════════════════════════════

def test_review_1_a_date_column_takes_the_date_a_date_time_cell_shows_never_its_time(tmp_path):
    """HIGH. A loss run exported with date-time cells (built-in 22, an export's
    yyyy-mm-dd h:mm:ss, an AM/PM time, a strict-ISO t="d" cell with a date-time
    format) imported "03/14/2025 0:00" and failed MM/DD/YYYY on every row, here
    and on the server. A date column now takes the MM/DD/YYYY the cell shows,
    never its time. A partial date stays as shown and is flagged; the same text
    typed into a CSV or a TEXT cell is the person's own and stays as typed."""
    loss = _cols("loss_history")
    d = _serial(date(2025, 3, 14))
    fmts = {200: "yyyy-mm-dd h:mm:ss", 201: "m/d/yyyy h:mm AM/PM", 202: "mmm-yy", 203: "dd/mm/yyyy hh:mm"}
    shared = ["Date of loss", "What happened", "Date reported", "Amount paid", "Rear-ended", "03/14/2025 13:30"]
    head = _row(1, _c("A1", 0, None, "s"), _c("B1", 1, None, "s"), _c("C1", 2, None, "s"), _c("D1", 3, None, "s"))
    xf = [0] + list(fmts) + [22, 14]
    s = xf.index
    rows = [head,
            _row(2, _c("A2", d, s(22)), _c("B2", 4, None, "s"), _c("C2", d + 1.5, s(22)), _c("D2", 1200)),
            _row(3, _c("A3", d + 0.25, s(200)), _c("B3", 4, None, "s"), _c("C3", d + 2.999988, s(200)),
                 _c("D3", 1200)),
            _row(4, _c("A4", d + 0.5625, s(201)), _c("B4", 4, None, "s"),
                 _c("C4", "2025-03-15T13:30:00", s(22), "d"), _c("D4", 1200)),
            _row(5, _c("A5", d, s(203)), _c("B5", 4, None, "s"), _c("C5", "2025-03-16", s(14), "d"),
                 _c("D5", 1200)),
            _row(6, _c("A6", d, s(202)), _c("B6", 4, None, "s"), _c("C6", 5, None, "s"), _c("D6", 1200))]
    p = _book(tmp_path / "dt.xlsx", "".join(rows), num_fmts=fmts, xf_ids=xf, shared=shared)
    o = _node(tmp_path, f"""
const loss = {json.dumps(loss)};
const m = await S.parseXLSX(file({json.dumps(str(p))}, 'loss.xlsx'));
const r = await S.parseScheduleFile(file({json.dumps(str(p))}, 'loss.xlsx'), loss);
const csv = S.rowsFromMatrix([['Date of loss', 'What happened'], ['03/14/2025 13:30', 'Rear-ended']], loss);
out({{shown: m.slice(1).map((x) => [x[0], x[2]]), rows: r.rows.map((x) => [x.date, x.claim_date]),
      errors: S.validateRows(r.rows, loss, []).errors, csv: csv.rows[0].date}});
""")
    # the cells still read as the sheet shows them (the document reader's text)
    assert o["shown"] == [["03/14/2025 0:00", "03/15/2025 12:00"], ["03/14/2025 6:00:00", "03/16/2025 23:59:59"],
                          ["03/14/2025 1:30 PM", "03/15/2025 13:30"], ["03/14/2025 00:00", "03/16/2025"],
                          ["Mar-25", "03/14/2025 13:30"]]
    assert o["rows"] == [["03/14/2025", "03/15/2025"], ["03/14/2025", "03/16/2025"], ["03/14/2025", "03/15/2025"],
                         ["03/14/2025", "03/16/2025"], ["Mar-25", "03/14/2025 13:30"]]
    # rows 1-4 carry no error at all; the partial date and the TEXT cell are flagged
    assert o["errors"] == {"4": {"date": "Date of loss must be MM/DD/YYYY",
                                 "claim_date": "Date reported must be MM/DD/YYYY"}}
    assert o["csv"] == "03/14/2025 13:30"                              # a CSV is the person's text
    from services.schedule_capture import validate_rows
    _clean, report = validate_rows("loss_history", [{"date": a, "claim_date": b, "description": "x"}
                                                   for a, b in o["rows"][:4]])
    assert report["errors"] == {}
    # the document reader keeps the time (it is text for extraction, not a table cell)
    assert st.read_xlsx(str(p))[0]["rows"][1][0] == "03/14/2025 0:00"


_NUMERIC_FORMATS = ["General", "0", "0.00", "#,##0", "#,##0.00", "#,##0,", '"$"#,##0', "$#,##0.00", "0.0", "0%",
                    "0.0%", '0"%"', "0.00E+00", "# ?/?", '0 "units"', "[<=99999]00000;00000-0000",
                    "#,##0.00_);[Red](#,##0.00)", '#,##0.0,,"M"',
                    '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)', "000-00-0000"]
_NUMERIC_VALUES = [0, 1, 12, 12.5, 99.6, 1234.56, 1250000, 0.125, 0.07, 1 / 3, 123456789.12, 202300012345, -1234.5,
                   0.30000000000000004, 7.5e-7]


def test_review_2_a_numeric_column_imports_the_number_the_cell_holds(tmp_path):
    """MEDIUM. The guard used to take the shown text whenever the column could
    read it, so a scaled or rounded format imported another number SILENTLY:
    "#,##0," 1250000 -> "1,250" (1000x low), "$#,##0" 1234.56 -> "$1,235",
    "0.0" 12345.67 -> "12345.7". Now, for every format x value here, in a
    currency, count and percent column alike: what imports either reads as
    exactly the number the cell holds (or, where the sheet shows "%", that
    number x 100 - Excel stores 12.5% as 0.125), or IS that number and is
    flagged (a negative). The adversarial cases are the ones the old test
    missed: scaling commas, whole-dollar formats over cents, rounding, a
    rounded percent, a quoted "%" that scales nothing."""
    fmts = {300 + i: c for i, c in enumerate(_NUMERIC_FORMATS)}
    head = _row(1, _c("A1", 0, None, "s"), _c("B1", 1, None, "s"), _c("C1", 2, None, "s"), _c("D1", 3, None, "s"),
                _c("E1", 4, None, "s"))
    xf = [0] + list(fmts)
    rows, cells = [head], []
    r = 2
    for i, code in enumerate(_NUMERIC_FORMATS):
        for v in _NUMERIC_VALUES:
            st_idx = xf.index(300 + i)
            rows.append(_row(r, _c(f"A{r}", 45730), _c(f"B{r}", 5, None, "s"),
                             _c(f"C{r}", repr(v), st_idx), _c(f"D{r}", repr(v), st_idx), _c(f"E{r}", repr(v), st_idx)))
            cells.append([code, repr(v)])
            r += 1
    p = tmp_path / "n.xlsx"
    _book(p, "".join(rows), num_fmts=fmts, xf_ids=xf,
          shared=["Date of loss", "Line", "Amount paid", "Full-time staff", "Sprinkler %", "Auto"])
    loss, loc = _cols("loss_history"), _cols("property_locations")
    cols = loss + [c for c in loc if c["key"] in ("full_time_employees", "sprinkler")]
    o = _node(tmp_path, f"""
const cols = {json.dumps(cols)};
const m = await S.parseXLSX(file({json.dumps(str(p))}, 'n.xlsx'));
const r = S.rowsFromMatrix(m, cols);
out({{shown: m.slice(1).map((x) => [x[2], x[3], x[4]]),
      got: r.rows.map((x) => [x.paid, x.full_time_employees, x.sprinkler]),
      bad: r.rows.map((x) => ['paid', 'full_time_employees', 'sprinkler'].map(
        (k) => S.validateCell(cols.find((c) => c.key === k), x[k])))}});
""")
    assert len(o["got"]) == len(cells)
    wrong = []
    for (code, raw), shown, got, bad in zip(cells, o["shown"], o["got"], o["bad"]):
        held = nf.full_number_text(float(raw))
        hundred = nf.full_number_text(float(raw), 2)
        for k, (s_txt, g_txt, b_msg) in enumerate(zip(shown, got, bad)):
            stripped = re.sub(r"[$,%\s]", "", g_txt)
            if re.fullmatch(r"\d+(\.\d+)?", stripped):
                ok = float(stripped) == float(held) or ("%" in s_txt and float(stripped) == float(hundred))
            else:                                   # not a number the column reads: the held number, flagged
                ok = (g_txt == held or ("%" in s_txt and g_txt == hundred)) and bool(b_msg)
            if not ok:
                wrong.append((code, raw, k, s_txt, g_txt))
    assert wrong == []
    by = {(c, v): g for (c, v), g in zip(cells, o["got"])}
    assert by[("#,##0,", "1250000")][0] == "1250000"                  # was "1,250": 1000x low
    assert by[('"$"#,##0', "1234.56")][0] == "1234.56"                # was "$1,235": cents lost
    assert by[('"$"#,##0', "99.6")][0] == "99.6"                      # was "$100"
    assert by[("$#,##0.00", "1234.56")][0] == "$1,234.56"             # reads exactly: as shown
    assert by[("#,##0", "1250000")][1] == "1,250,000"
    assert by[("0%", "0.125")][2] == "12.5"                           # shown 13%: Excel holds 12.5%
    assert by[("0.0%", "0.125")][2] == "12.5%"
    assert by[("0%", "1")][2] == "100%"
    assert by[('0"%"', "12.5")][2] == "12.5"                          # a quoted % scales nothing
    assert by[('0"%"', "12")][2] == "12%"
    assert by[("General", "12")][2] == "12"
    assert by[('0 "units"', "12")][1] == "12"
    assert by[("General", "123456789.12")][0] == "123456789.12"
    assert by[("0.0", "1234.56")][0] == "1234.56"


def test_review_2_the_server_reads_the_imported_numbers_the_same_way(tmp_path):
    """The rows the import produces pass the server's own validation wherever
    the table passed them (a scaled amount is a plain number, not "1,250")."""
    from services.schedule_capture import validate_rows
    o = _node(tmp_path, """
const loss = [{key: 'date', label: 'Date of loss', type: 'date'}, {key: 'paid', label: 'Amount paid', type: 'currency'}];
const cells = ['', '1,250']; Object.defineProperty(cells, 'stored', {value: {1: '1250000'}});
const cells2 = ['', '$ -']; Object.defineProperty(cells2, 'stored', {value: {1: '0'}});
out([S.tableCellValue(loss[1], '1,250', cells, 1), S.tableCellValue(loss[1], '$ -', cells2, 1),
     S.tableCellValue(loss[1], '1,250', ['', '1,250'], 1), S.tableCellValue(loss[1], '', cells, 1),
     S.tableCellValue(loss[0], '03/14/2025 1:30 PM', ['03/14/2025 1:30 PM'], 0)]);
""")
    assert o == ["1250000", "0", "1,250", "", "03/14/2025 1:30 PM"]   # no cell values: the text as it is
    _clean, report = validate_rows("loss_history", [{"date": "03/14/2025", "description": "x", "paid": o[0]},
                                                   {"date": "03/14/2025", "description": "x", "paid": o[1]}])
    assert report["errors"] == {}


def test_review_3_general_ids_keep_every_digit_in_both_readers(tmp_path):
    """MEDIUM. General shows a 12- to 15-digit number as 1.23457E+11, so two
    numeric claim numbers in a carrier loss run reached extraction as ONE value
    ("2.023E+11"). The readers now print every stored digit wherever General's
    text is another number than the cell holds - IDs, a decimal cut at 11
    characters, a tiny number - and nowhere else; past 15 digits the 15 Excel
    stores, never an invented zero. The renderer itself (the vectors) still
    shows Excel's cell."""
    values = ["202300012345", "202300012346", "123456789012345", "1234567890123456", "123456789.12",
              "-202300012345", "0.000012345678901", "1E-20", "99999999999.5", "0.30000000000000004", "12345678901",
              "202300012345"]
    want = ["202300012345", "202300012346", "123456789012345", "1.23456789012346E+15", "123456789.12",
            "-202300012345", "0.000012345678901", "1E-20", "99999999999.5", "0.3", "12345678901",
            "Claim 202300012345"]
    fmts = {400: '"Claim "General'}
    cells = [_c(f"{chr(65 + i)}1", v, 1 if i == len(values) - 1 else None) for i, v in enumerate(values)]
    p = tmp_path / "ids.xlsx"
    _book(p, _row(1, *cells), num_fmts=fmts, xf_ids=[0, 400])
    py, js = _both_readers(tmp_path, p)
    assert py == [want] and js == py
    # the renderer (and the vectors) are Excel's own cell, unchanged
    assert nf.format_cell_number("202300012345", "General") == "2.023E+11"
    assert nf.format_cell_number("202300012345", "General", keep_digits=True) == "202300012345"
    # a schedule TEXT column (licence number) imports the digits too
    drv = _cols("auto_drivers")
    q = tmp_path / "drv.xlsx"
    _book(q, _row(1, _c("A1", 0, None, "s"), _c("B1", 1, None, "s")) + _row(2, _c("A2", 2, None, "s"),
                                                                            _c("B2", "123456789012")),
          shared=["Full name", "License #", "Ann Lee"])
    o = _node(tmp_path, f"out((await S.parseScheduleFile(file({json.dumps(str(q))}, 'd.xlsx'), "
                        f"{json.dumps(drv)})).rows[0].license_number);", name="drv.mjs")
    assert o == "123456789012"


def test_review_3_keep_digits_moves_only_general_numbers_and_agrees_in_both_languages(tmp_path):
    """keep_digits changes a vector only where its code shows General and
    Excel's text is another number (the four 12+ digit General vectors), and
    the two languages agree on it far beyond the vectors."""
    moved = [v for v in _VECTORS if v["type"] == "n"
             and nf.format_cell_number(v["value"], v["code"], v["date1904"], keep_digits=True) != v["expect"]]
    assert {(v["code"], v["value"]) for v in moved} == {("General", "123456789012"), ("General", "-123456789012"),
                                                        ("General", "1234567890123"), ("", "123456789012")}
    rnd = random.Random(2110)
    codes = sorted({v["code"] for v in _VECTORS}) + _random_codes(11, 80) + ['"Claim "General', "General;-General",
                                                                           "[>5]General", "[$$-409]General"]
    values = ["202300012345", "-202300012345", "123456789.12", "0.000012345678901", "1E-20", "99999999999.5",
              "1234567890123456", "1e308", "5e-324", "0.30000000000000004", "45730.5625", "-0.001", "0"]
    values += [repr(rnd.uniform(-1e15, 1e15)) for _ in range(10)] + [repr(rnd.uniform(0, 1e-3)) for _ in range(5)]
    values += [str(rnd.randrange(10 ** 11, 10 ** 15)) for _ in range(10)]
    cases = [[c, v, d] for c in codes for v in values for d in (False, True)]
    shifts = [[v, k] for v in values for k in (0, 2, -2, 5)]
    data = tmp_path / "keep.json"
    data.write_text(json.dumps({"cases": cases, "shifts": shifts}), encoding="utf-8")
    o = _node(tmp_path, f"""
const {{cases, shifts}} = JSON.parse(fs.readFileSync({json.dumps(str(data))}, 'utf8'));
out({{keep: cases.map(([c, v, d]) => N.formatCellNumber(v, c, d, true)),
      full: shifts.map(([v, k]) => N.fullNumberText(Number(v), k))}});
""")
    py = [nf.format_cell_number(v, c, d, keep_digits=True) for c, v, d in cases]
    diff = [(cases[i], py[i], o["keep"][i]) for i in range(len(cases)) if py[i] != o["keep"][i]]
    assert not diff, diff[:10]
    assert o["full"] == [nf.full_number_text(float(v), k) for v, k in shifts]
    assert len(cases) > 10_000
    # never raises (an empty section, ";)nde", hides the number as Excel does)
    for code in _random_codes(31, 400):
        assert isinstance(nf.format_cell_number("202300012345", code, keep_digits=True), str)


def test_review_4_a_malformed_shared_string_index_is_one_rule_in_both_readers(tmp_path):
    """LOW. JS parseInt read "1.5" and "2abc" as indexes 1 and 2; Python's int()
    refused them (and accepted "+1"). Both now take ASCII digits alone, with
    ASCII spaces around them."""
    raws = ["1.5", "2abc", "+1", " 1 ", "1e0", "", "0x1", "01", "1\n"]
    cells = [f'<c r="{chr(65 + i)}1" t="s"><v>{escape(r)}</v></c>' for i, r in enumerate(raws)]
    p = _book(tmp_path / "ix.xlsx", _row(1, *cells, _c("K1", "x", None, "str")), shared=["zero", "one", "two"])
    raw = _node(tmp_path, f"out(await S.parseXLSX(fs.readFileSync({json.dumps(str(p))})));", name="ix.mjs")
    assert raw == [["", "", "", "one", "", "", "", "one", "one", "", "x"]]
    py, js = _both_readers(tmp_path, p)
    assert py == [["one", "one", "one", "x"]] and js == py


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 - one ZIP reader; "password-protected" only for an encrypted entry
# ══════════════════════════════════════════════════════════════════════════════

_RUNTIME_DIRS = ("services", "routes", "utils", "models", "repositories", "config")


def _runtime_modules():
    files = [p for d in _RUNTIME_DIRS for p in (_BACKEND / d).rglob("*.py")]
    files += [p for p in (_BACKEND / "main.py", _BACKEND / "worker.py") if p.exists()]
    return files


def _zip_read_calls(tree):
    """Every zipfile.ZipFile(...) / ZipFile(...) call that opens for reading."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        named = (isinstance(f, ast.Attribute) and f.attr == "ZipFile") or (isinstance(f, ast.Name) and f.id == "ZipFile")
        if not named:
            continue
        mode = "r"
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = str(kw.value.value)
        if mode.startswith("r"):
            out.append(node.lineno)
    return out


def test_nothing_defines_or_imports_a_second_zip_reader():
    """The ONE door for a ZIP upload is upload_intake.store_uploads; an .xlsx is
    a ZIP package its reader (spreadsheet_text) opens. No other runtime module
    opens a ZIP for reading, nothing defines or imports extract_zip, and nothing
    unpacks archives through shutil."""
    allowed = {_BACKEND / "services" / "upload_intake.py", _BACKEND / "utils" / "spreadsheet_text.py"}
    readers, defs, imports, unpack = [], [], [], []
    for path in _runtime_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _zip_read_calls(tree) and path not in allowed:
            readers.append(str(path.relative_to(_BACKEND)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "zip" in node.name.lower() \
                    and node.name.lower().startswith(("extract", "unzip", "unpack", "read", "open")):
                defs.append(f"{path.relative_to(_BACKEND)}:{node.name}")
            if isinstance(node, ast.ImportFrom) and any(a.name == "extract_zip" for a in node.names):
                imports.append(str(path.relative_to(_BACKEND)))
            if isinstance(node, ast.Attribute) and node.attr == "unpack_archive":
                unpack.append(str(path.relative_to(_BACKEND)))
    assert readers == [] and defs == [] and imports == [] and unpack == []
    import services.ocr_service as ocr
    assert not hasattr(ocr, "extract_zip")
    assert "ZipFile" not in (_BACKEND / "services" / "ocr_service.py").read_text(encoding="utf-8")


def test_the_guard_bites_on_a_planted_second_reader():
    """The harvester is not vacuous: a planted reader is found, a writer is not."""
    planted = ast.parse("import zipfile\ndef extract_zip(p):\n    with zipfile.ZipFile(p) as z:\n        pass\n"
                        "def w(b):\n    zipfile.ZipFile(b, 'w')\nzipfile.ZipFile(p, mode='r')\n")
    assert sorted(_zip_read_calls(planted)) == [3, 7]


def _upload(name, data: bytes):
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture
def intake(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _zip_of(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return bytearray(buf.getvalue())


def _patch_entries(raw: bytearray, name: bytes, *, flag=None, method=None):
    """Set the general-purpose flag bits / compression method of ONE entry in
    both its local and central headers."""
    for sig, flag_off, method_off, name_len_off, name_off in ((b"PK\x03\x04", 6, 8, 26, 30),
                                                              (b"PK\x01\x02", 8, 10, 28, 46)):
        i = raw.find(sig)
        while i != -1:
            n = int.from_bytes(raw[i + name_len_off:i + name_len_off + 2], "little")
            if bytes(raw[i + name_off:i + name_off + n]) == name:
                if flag is not None:
                    raw[i + flag_off] |= flag
                if method is not None:
                    raw[i + method_off:i + method_off + 2] = method.to_bytes(2, "little")
            i = raw.find(sig, i + 4)
    return bytes(raw)


def test_an_encrypted_document_entry_is_refused_as_password_protected(intake):
    data = _patch_entries(_zip_of([("pkg/dec.pdf", b"%PDF-1.4 x"), ("pkg/b.pdf", b"%PDF-1.4 y")]),
                          b"pkg/b.pdf", flag=0x1)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("package.zip", data)]))
    assert ei.value.status_code == 400
    assert ei.value.detail == ("File 'package.zip' is a password-protected ZIP archive. "
                               "Upload the files without a password.")
    assert list(intake.iterdir()) == []                                 # nothing left behind


def test_an_entry_zipfile_cannot_unpack_is_not_called_password_protected(intake):
    """An unsupported compression method makes zipfile raise NotImplementedError,
    which IS a RuntimeError - the old handler called it "password-protected"."""
    data = _patch_entries(_zip_of([("pkg/dec.pdf", b"%PDF-1.4 x")]), b"pkg/dec.pdf", method=98)
    with zipfile.ZipFile(io.BytesIO(data)) as z, pytest.raises(NotImplementedError):
        z.open("pkg/dec.pdf")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("package.zip", data)]))
    assert ei.value.status_code == 400
    assert "password" not in ei.value.detail.lower()
    assert ei.value.detail == ("File 'package.zip' could not be unpacked. Upload the files on their own, "
                               "or in a new ZIP archive.")
    assert list(intake.iterdir()) == []
    assert not any(d in ei.value.detail for d in _EM)


def test_any_other_runtime_error_gets_the_plain_refusal(intake, monkeypatch):
    data = bytes(_zip_of([("dec.pdf", b"%PDF-1.4 x")]))

    def broken(self, *a, **k):
        raise RuntimeError("Attempt to use ZIP archive that was already closed")
    monkeypatch.setattr(zipfile.ZipFile, "open", broken)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("package.zip", data)]))
    assert ei.value.status_code == 400 and "could not be unpacked" in ei.value.detail
    assert "password" not in ei.value.detail.lower()


def test_an_encrypted_entry_that_is_skipped_anyway_refuses_nothing(intake):
    """A readme the ZIP door skips (a .txt) is never opened, so its encryption
    is no reason to refuse the package - exactly as before."""
    data = _patch_entries(_zip_of([("pkg/dec.pdf", b"%PDF-1.4 x"), ("pkg/readme.txt", b"secret")]),
                          b"pkg/readme.txt", flag=0x1)
    _up, docs = asyncio.run(ui.store_uploads([_upload("package.zip", data)]))
    assert [Path(p).name.split("_", 1)[1] for p in docs] == ["dec.pdf"]


def test_a_broken_zip_is_still_not_a_valid_zip(intake):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("package.zip", b"PK\x03\x04 broken")]))
    assert ei.value.status_code == 400
