"""Build 21 Oct 2026, lane F, item f-excel-csv-documents (25sepChanges.md Z29-2
item 1, Z30-F) - Brent's 17 Oct test: "Excel will not upload" (start, and
"Add documents").

Root cause: the upload door (utils/mime_validator, services/upload_intake) and
both file inputs took PDF / ZIP / images / TXT only; only the schedule tables'
own import read .xlsx / .csv. Now an .xlsx or .csv is a DOCUMENT through the
same door as a PDF: validated (magic bytes, the workbook parts, no macros, a
ZIP-bomb cap), virus-scanned, read as text by ocr_service.extract_text
(utils/spreadsheet_text.py - "Sheet: <name>" blocks, " | "-joined rows, dates
as MM/DD/YYYY by the schedule import's own rules), then classified, extracted
and listed like any other document. .xls / .xlsm are refused with a sentence
saying what to do.

The adversarial cases come first: the reader must never INVENT a value (a
text cell that looks like a date stays text; a formula is never evaluated) and
never DROP one (every sheet, hidden ones included; a cell holding the column
separator stays one column). The Python reader and the frontend's parseXLSX
are compared cell for cell on Brent's two real workbooks, and their number
format rules are compared code for code under node.
"""
from __future__ import annotations

import asyncio
import io
import json
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
import utils.spreadsheet_text as st
from utils.mime_validator import DOCUMENT_EXTENSIONS, validate_file_mime

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_FIX = Path(__file__).resolve().parent / "fixtures"
_DRIVERS_XLSX = _FIX / "brent_driver_schedule_17oct.xlsx"
_CLAIMS_XLSX = _FIX / "brent_synthetic_claims_17oct.xlsx"
_EM = ("—", "–")


# ── a small .xlsx writer: the parts a real workbook has ─────────────────────────
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
       'content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
       'officedocument.spreadsheetml.sheet.main+xml"/></Types>')


def _book(path, sheets, *, styles=None, shared=None, workbook_pr="", content_types=_CT, extra=None,
          rels=True):
    """`sheets`: [{"name", "data" (inner XML of <sheetData>), "state", "kind"
    ("worksheet" | "chartsheet"), "part" (path under xl/)}]."""
    sheet_tags, rel_tags = [], []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        for i, sh in enumerate(sheets, 1):
            kind = sh.get("kind", "worksheet")
            part = sh.get("part") or f"{kind}s/sheet{i}.xml"
            state = f' state="{sh["state"]}"' if sh.get("state") else ""
            sheet_tags.append(f'<sheet name={quoteattr(sh["name"])} sheetId="{i}"{state} r:id="rId{i}"/>')
            rel_tags.append(f'<Relationship Id="rId{i}" Type="{_REL}{kind}" Target="{part}"/>')
            body = (f'<sheetData>{sh.get("data", "")}</sheetData>' if kind == "worksheet" else "")
            z.writestr("xl/" + part, f'<?xml version="1.0"?><{kind} xmlns="{_NS}">{body}</{kind}>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{_NS}" xmlns:r="{_R_NS}">'
                                      f'{workbook_pr}<sheets>{"".join(sheet_tags)}</sheets></workbook>')
        if styles is not None:
            z.writestr("xl/styles.xml", f'<?xml version="1.0"?><styleSheet xmlns="{_NS}">{styles}</styleSheet>')
            rel_tags.append(f'<Relationship Id="rIdS" Type="{_REL}styles" Target="styles.xml"/>')
        if shared is not None:
            sis = "".join(s if s.startswith("<si>") else f"<si><t>{escape(s)}</t></si>" for s in shared)
            z.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><sst xmlns="{_NS}">{sis}</sst>')
            rel_tags.append(f'<Relationship Id="rIdT" Type="{_REL}sharedStrings" Target="sharedStrings.xml"/>')
        if rels:
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
                       f'2006/relationships">{"".join(rel_tags)}</Relationships>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def _styles(num_fmts, xf_ids):
    """numFmts {id: code} + cellXfs numFmtIds (index = the cell's s="...").
    cellStyleXfs and dxfs carry their own <xf> / <numFmt>: never the cells'."""
    nf = "".join(f'<numFmt numFmtId="{i}" formatCode={quoteattr(c)}/>' for i, c in num_fmts.items())
    xfs = "".join(f'<xf numFmtId="{i}" fontId="0" fillId="0" borderId="0" xfId="0"/>' for i in xf_ids)
    return (f'<numFmts count="{len(num_fmts)}">{nf}</numFmts>'
            '<cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs>'
            f'<cellXfs count="{len(xf_ids)}">{xfs}</cellXfs>'
            '<dxfs count="1"><dxf><numFmt numFmtId="3" formatCode="mm/dd/yyyy"/></dxf></dxfs>')


def _row(r, *cells):
    return f'<row r="{r}">{"".join(cells)}</row>'


def _n(ref, v, s=None):
    return f'<c r="{ref}"{f" s={chr(34)}{s}{chr(34)}" if s is not None else ""}><v>{v}</v></c>'


def _s(ref, idx, s=None):
    return f'<c r="{ref}" t="s"{f" s={chr(34)}{s}{chr(34)}" if s is not None else ""}><v>{idx}</v></c>'


def _inline(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def _serial_1900(d):
    n = (d - date(1899, 12, 30)).days
    return n if n >= 61 else n - 1


def _text(path):
    return st.spreadsheet_text(str(path))


def _cells(line):
    """A rendered row back into cells (quote-aware - the reader's own rule)."""
    import csv as _csv
    return [c.strip() for c in next(_csv.reader([line], delimiter="|", skipinitialspace=True))]


def _node(tmp_path, body, name="check.mjs"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / name
    script.write_text(
        f"import * as S from {json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
        f"import * as A from {json.dumps((_FRONT / 'utils' / 'addDocuments.js').as_uri())};\n"
        "import fs from 'node:fs';\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# 1. ADVERSARIAL FIRST - never invent a value, never drop one
# ══════════════════════════════════════════════════════════════════════════════

def test_a_text_cell_that_looks_like_a_date_or_number_stays_exactly_as_written(tmp_path):
    """Only a NUMBER in a DATE format becomes a date. A text cell "45729", a
    General-format number 45729 and a text "03/14/2025" are printed as they are.
    (Z31-X: a NUMBER stored as "0012" is the number 12, and General shows 12 -
    this test pinned the stored spelling; a zero-padded ID is a TEXT cell or a
    "0000" format, both kept.)"""
    p = _book(tmp_path / "a.xlsx", [{"name": "S", "data": _row(
        1, _s("A1", 0), _n("B1", 45729), _s("C1", 1), _n("D1", 45729, s=1), _n("E1", "0012", s=0))}],
        styles=_styles({}, [0, 14]), shared=["45729", "03/14/2025"])
    assert _text(p).splitlines()[1] == "45729 | 45729 | 03/14/2025 | 03/13/2025 | 12"


def test_a_formula_is_never_evaluated_its_cached_value_is_read(tmp_path):
    p = _book(tmp_path / "f.xlsx", [{"name": "S", "data": _row(
        1, _n("A1", 4), _n("B1", 3),
        '<c r="C1"><f>A1+B1</f><v>7</v></c>',                 # cached value
        '<c r="D1" t="str"><f>"total "&amp;C1</f><v>total 7</v></c>',
        '<c r="E1"><f>A1*100</f></c>',                         # saved without a value
        _n("F1", 1)) + _row(2, _n("E2", 5))}])
    line, below = _text(p).splitlines()[1:]
    assert line == "4 | 3 | 7 | total 7 |  | 1"                 # empty in place - never "A1*100", never 400
    assert below == " |  |  |  | 5"
    assert "A1" not in line and "*" not in line


def test_a_cell_holding_the_separator_stays_one_column(tmp_path):
    """Brent's claims sheet: "V009 | 2017 Chevrolet Express G2500 | ..." is ONE
    cell. Quoted, CSV-style - every row keeps the header's column count."""
    p = _book(tmp_path / "p.xlsx", [{"name": "Claims", "data": "".join([
        _row(1, _inline("A1", "id"), _inline("B1", "description"), _inline("C1", "paid")),
        _row(2, _inline("A2", "SIM-1"), _inline("B2", 'V009 | 2017 Chevy | "PD"'), _n("C2", 12000)),
    ])}])
    head, row = _text(p).splitlines()[1:]
    assert row == 'SIM-1 | "V009 | 2017 Chevy | ""PD""" | 12000'
    assert len(_cells(head)) == len(_cells(row)) == 3
    assert _cells(row)[1] == 'V009 | 2017 Chevy | "PD"'


def test_every_sheet_is_read_in_tab_order_hidden_ones_labelled(tmp_path):
    """The owner's rule: the whole uploaded document matters. Tab order is the
    workbook's, not the part numbering; a chart sheet and an empty sheet print
    nothing; hidden and very hidden sheets are read and labelled."""
    p = _book(tmp_path / "t.xlsx", [
        {"name": "Summary", "part": "worksheets/sheet3.xml", "data": _row(1, _inline("A1", "first tab"))},
        {"name": "Chart", "kind": "chartsheet"},
        {"name": "Claims", "state": "hidden", "part": "worksheets/sheet1.xml",
         "data": _row(1, _inline("A1", "hidden data"))},
        {"name": "Empty", "part": "worksheets/sheet2.xml", "data": _row(4, _inline("A4", "   "))},
        {"name": "Notes", "state": "veryHidden", "part": "worksheets/sheet9.xml",
         "data": _row(2, _inline("C2", "very hidden data"))},
    ])
    assert _text(p) == ("Sheet: Summary\nfirst tab\n\nSheet: Claims (hidden)\nhidden data\n\n"
                        "Sheet: Notes (hidden)\nvery hidden data")


def test_empty_rows_and_columns_are_dropped_and_rows_stay_aligned(tmp_path):
    p = _book(tmp_path / "e.xlsx", [{"name": "S", "data": "".join([
        _row(2, _inline("B2", "name"), _inline("D2", "state"), _inline("F2", "  ")),
        _row(5, _inline("B5", "Ann  Lee\nJr"), _inline("D5", "CO")),
        _row(9, _inline("D9", "WY")),
        _row(12, _inline("Z12", "")),
    ])}])
    assert _text(p).splitlines()[1:] == ["name | state", "Ann Lee Jr | CO", " | WY"]


def test_a_sheet_of_only_empty_cells_gives_no_text(tmp_path):
    p = _book(tmp_path / "x.xlsx", [{"name": "S", "data": _row(1, _inline("A1", " "))}])
    assert _text(p) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 2. Dates and other formats - the schedule import's own rules
# ══════════════════════════════════════════════════════════════════════════════

# Z31-X: a format with a day, a month AND a year prints MM/DD/YYYY; one without
# all three prints as the sheet shows it (16 "d-mmm" -> 14-Mar, 17 "mmm-yy" ->
# Mar-25). This test pinned those two as whole dates.
@pytest.mark.parametrize("fmt_id, shown", [(14, "03/14/2025"), (15, "03/14/2025"), (16, "14-Mar"),
                                           (17, "Mar-25"), (27, "03/14/2025"), (31, "03/14/2025"),
                                           (50, "03/14/2025"), (57, "03/14/2025"), (58, "03/14/2025"),
                                           (71, "03/14/2025"), (72, "03/14/2025")])
def test_builtin_and_locale_date_ids_print_mm_dd_yyyy(tmp_path, fmt_id, shown):
    serial = _serial_1900(date(2025, 3, 14))
    p = _book(tmp_path / "d.xlsx", [{"name": "S", "data": _row(1, _n("A1", serial, s=1))}],
              styles=_styles({}, [0, fmt_id]))
    assert _text(p).splitlines()[1] == shown


@pytest.mark.parametrize("code, shown", [("mm/dd/yyyy", "04/17/1982"), ("d-mmm-yy", "04/17/1982"),
                                         ("yyyy-mm-dd", "04/17/1982"), ("[$-409]mmmm d, yyyy;@", "04/17/1982"),
                                         ("dd/mm/yyyy", "04/17/1982"), ("mmm-yy", "Apr-82"),
                                         ("m/d/yy", "04/17/1982")])
def test_custom_date_formats_print_mm_dd_yyyy(tmp_path, code, shown):
    serial = _serial_1900(date(1982, 4, 17))
    p = _book(tmp_path / "c.xlsx", [{"name": "S", "data": _row(1, _n("A1", serial, s=1))}],
              styles=_styles({170: code}, [0, 170]))
    assert _text(p).splitlines()[1] == shown


def test_the_1900_leap_year_bug_and_the_1904_system(tmp_path):
    rows = "".join(_row(i + 1, _n(f"A{i + 1}", v, s=1)) for i, v in enumerate([1, 59, 60, 61, 0, 45729]))
    p1900 = _book(tmp_path / "a.xlsx", [{"name": "S", "data": rows}], styles=_styles({}, [0, 14]))
    assert _text(p1900).splitlines()[1:] == ["01/01/1900", "02/28/1900", "60", "03/01/1900", "0", "03/13/2025"]
    p1904 = _book(tmp_path / "b.xlsx", [{"name": "S", "data": rows}], styles=_styles({}, [0, 14]),
                  workbook_pr='<workbookPr date1904="1"/>')
    assert _text(p1904).splitlines()[1:] == ["01/02/1904", "02/29/1904", "03/01/1904", "03/02/1904",
                                             "01/01/1904", "03/14/2029"]


def test_times_and_date_times_print_as_the_format_shows_them(tmp_path):
    t = 0.5625                                                 # 13:30
    dt = _serial_1900(date(2025, 3, 14)) + 0.5625
    cells = [(22, dt), (18, t), (19, t + 15 / 86400), (20, t), (21, t), (45, t + 15 / 86400),
             (46, 1.5625), (47, t + 15 / 86400)]
    data = "".join(_row(i + 1, _n(f"A{i + 1}", v, s=i + 1)) for i, (_f, v) in enumerate(cells))
    p = _book(tmp_path / "t.xlsx", [{"name": "S", "data": data}],
              styles=_styles({}, [0] + [f for f, _v in cells]))
    # Z31-X: built-in 47 is Excel's "mm:ss.0" (tenths of a second shown); this
    # test pinned the old reader's "30:15".
    assert _text(p).splitlines()[1:] == ["03/14/2025 13:30", "1:30 PM", "1:30:15 PM", "13:30", "13:30:00",
                                         "30:15", "37:30:00", "30:15.0"]


def test_month_versus_minute_and_quoted_letters(tmp_path):
    """"m" beside an hour is minutes, not a month: "h:mm" is a time, never a
    date. A letter inside quotes or escaped prints itself - "0 \\"days\\"" and
    0\\d are numbers. Z31-X: each now prints as the sheet shows it - "h" has no
    leading zero (6:00), "yyyy-mm" has no day (2025-03), and the literal text
    is part of the cell (12 days, 12d); this test pinned the old reader."""
    serial = _serial_1900(date(2025, 3, 14))
    p = _book(tmp_path / "m.xlsx", [{"name": "S", "data": _row(
        1, _n("A1", 0.25, s=1), _n("B1", serial, s=2), _n("C1", 12, s=3), _n("D1", 12, s=4))}],
        styles=_styles({170: "h:mm", 171: "yyyy-mm", 172: '0 "days"', 173: "0\\d"}, [0, 170, 171, 172, 173]))
    assert _text(p).splitlines()[1] == "6:00 | 2025-03 | 12 days | 12d"


def test_percent_zeros_booleans_errors_and_stored_numbers(tmp_path):
    p = _book(tmp_path / "n.xlsx", [{"name": "S", "data": _row(
        1, _n("A1", 1, s=1), _n("B1", 0.125, s=2), _n("C1", 8540, s=3), _n("D1", 12345, s=4),
        '<c r="E1" t="b"><v>1</v></c>', '<c r="F1" t="b"><v>0</v></c>', '<c r="G1" t="e"><v>#N/A</v></c>',
        _n("H1", "0.30000000000000004"), _n("I1", "12000", s=5), _n("J1", "1.5"),
        '<c r="K1" t="d"><v>2025-03-14T00:00:00</v></c>')}],
        styles=_styles({170: "00000", 171: "00000-0000", 172: '_("$"* #,##0.00_)'}, [0, 9, 10, 170, 171, 172]))
    # Z31-X: the accounting cell prints as the sheet shows it ($12,000.00, pad
    # spaces trimmed); this test pinned the stored 12000.
    assert _text(p).splitlines()[1] == ("100% | 12.50% | 08540 | 00001-2345 | TRUE | FALSE | #N/A | 0.3 | "
                                        "$12,000.00 | 1.5 | 03/14/2025")


def test_shared_rich_text_inline_strings_and_namespace_prefixes(tmp_path):
    """Rich-text runs join; a phonetic guide (<rPh>) is not text; an inline
    string reads its <t>; a writer's "x:" prefix is accepted."""
    rich = '<si><r><t>Choice </t></r><r><rPr><b/></rPr><t>Electric</t></r><rPh sb="0" eb="1"><t>XX</t></rPh></si>'
    p = _book(tmp_path / "r.xlsx", [{"name": "S", "data": _row(1, _s("A1", 0), _inline("B1", "LLC & Co"))}],
              shared=[rich])
    assert _text(p).splitlines()[1] == "Choice Electric | LLC & Co"
    # Excel's _xHHHH_ escape: a line break in a cell is "_x000D_" - decoded (then
    # collapsed to a space); a literal "_x0041_" is stored "_x005F_x0041_".
    e = _book(tmp_path / "esc.xlsx", [{"name": "S", "data": _row(1, _s("A1", 0), _s("B1", 1))}],
              shared=["Line one_x000D_\nline two", "code _x005F_x0041_"])
    assert _text(e).splitlines()[1] == "Line one line two | code _x0041_"
    q = tmp_path / "x.xlsx"
    with zipfile.ZipFile(q, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("xl/workbook.xml", f'<x:workbook xmlns:x="{_NS}"><x:sheets><x:sheet name="P" sheetId="1"/>'
                                      '</x:sheets></x:workbook>')
        z.writestr("xl/worksheets/sheet1.xml", f'<x:worksheet xmlns:x="{_NS}"><x:sheetData><x:row r="1">'
                                               '<x:c r="A1" t="inlineStr"><x:is><x:t>prefixed</x:t></x:is></x:c>'
                                               '</x:row></x:sheetData></x:worksheet>')
    assert _text(q) == "Sheet: P\nprefixed"


def test_a_workbook_written_without_relationships_reads_its_sheets_by_position(tmp_path):
    p = _book(tmp_path / "n.xlsx", [{"name": "One", "data": _row(1, _inline("A1", "a"))},
                                    {"name": "Two", "data": _row(1, _inline("A1", "b"))}], rels=False)
    assert _text(p) == "Sheet: One\na\n\nSheet: Two\nb"


def test_the_python_reader_decides_format_kinds_exactly_like_the_frontend(tmp_path):
    """ONE rule in two languages: numberFormatKind and excelSerialToDate are
    compared code for code with the frontend's (scheduleImport.js)."""
    codes = ["General", "0", "0.00", "#,##0", "0%", "0.00%", "m/d/yyyy", "d-mmm-yy", "d-mmm", "mmm-yy",
             "h:mm AM/PM", "h:mm:ss AM/PM", "h:mm", "h:mm:ss", "m/d/yyyy h:mm", "mm:ss", "[h]:mm:ss", "mmss.0",
             "@", "00000", "00000-0000", "000-00-0000", "mm/dd/yyyy", "yyyy-mm-dd", "[$-409]mmmm d, yyyy;@",
             '0 "days"', "0\\d", '"Due "mm/dd', "[Red]0.00", "#,##0.00_);[Red](#,##0.00)", '_("$"* #,##0.00_)',
             "dd/mm/yyyy hh:mm:ss", "mmmmm", "[mm]:ss", "0.0E+00", "# ?/?", 'm"m"', "yy", "s", "[ss]", "a/p",
             "0.000%%", "#,##0,", ";;;", "", "0;-0;;@"]
    serials = [0, 1, 59, 60, 61, 366, 45729, 45729.5, 45729.9999999999, 2958465, 2958466, -1, "x", "", 1e20]
    o = _node(tmp_path, f"""
const codes = {json.dumps(codes)};
const serials = {json.dumps(serials)};
out({{kinds: codes.map((c) => S.numberFormatKind(c).kind),
      d1900: serials.map((s) => S.excelSerialToDate(s, false)),
      d1904: serials.map((s) => S.excelSerialToDate(s, true)),
      shown: [['0%', 1], ['0.00%', 0.125], ['00000', 8540], ['000-00-0000', 123456789], ['m/d/yyyy', 30058],
              ['d-mmm-yy', 45729]].map(([c, v]) => S.formatCellNumber(String(v), c, false))}});
""")
    assert o["kinds"] == [st.number_format_kind(c)["kind"] for c in codes]
    assert o["d1900"] == [st.excel_serial_to_date(s, False) for s in serials]
    assert o["d1904"] == [st.excel_serial_to_date(s, True) for s in serials]
    py = [st.format_cell_number(str(v), st.number_format_kind(c)) for c, v in
          [("0%", 1), ("0.00%", 0.125), ("00000", 8540), ("000-00-0000", 123456789), ("m/d/yyyy", 30058),
           ("d-mmm-yy", 45729)]]
    assert o["shown"] == py


# ══════════════════════════════════════════════════════════════════════════════
# 3. Brent's real files (attachments B and C of his 17 Oct test)
# ══════════════════════════════════════════════════════════════════════════════

def test_brent_driver_schedule_every_row_with_real_dates():
    text = _text(_DRIVERS_XLSX)
    lines = text.splitlines()
    assert lines[0] == "Sheet: Driver Schedule"
    header = lines.index("Full Name | Date of Birth | State Licensed In | Date Hired | Years of Experience")
    drivers = lines[header + 1:]
    assert len(drivers) == 12
    assert drivers[0] == "Daniel Mercer | 04/17/1982 | CO | 06/11/2018 | 21"
    assert drivers[-1] == "Hannah Price | 05/04/1997 | CO | 02/03/2025 | 7"
    for row in drivers:
        c = _cells(row)
        assert len(c) == 5
        for d in (c[1], c[3]):
            mm, dd, yyyy = d.split("/")
            assert date(int(yyyy), int(mm), int(dd))            # a real calendar day
    assert "30058" not in text                                    # no serial survives


def test_brent_claims_sheet_every_claim_row_and_every_planted_error_is_in_the_text():
    text = _text(_CLAIMS_XLSX)
    lines = text.splitlines()
    assert lines[0] == "Sheet: Primble_Choice_Electric_Synthet"
    header = _cells(lines[1])
    assert header[:6] == ["dataset", "insured", "line", "carrier_reference", "synthetic_claim_id", "loss_date"]
    rows = [_cells(r) for r in lines[2:]]
    assert len(rows) == 24
    assert [r[0] for r in rows] == ["CONTROL"] * 12 + ["CHALLENGE"] * 12
    assert all(len(r) == len(header) for r in rows)              # the quoted pipes never shift a column
    by = {(r[0], r[4]): dict(zip(header, r)) for r in rows}
    assert by[("CONTROL", "SIM-AUTO-001")]["loss_date"] == "03/13/2025"
    assert by[("CONTROL", "SIM-AUTO-001")]["description_asset"].startswith("V009 | 2017 Chevrolet")
    # the planted mistakes reach the text exactly as the sheet holds them
    ch = {k[1]: v for k, v in by.items() if k[0] == "CHALLENGE"}
    assert (ch["SIM-AUTO-003"]["loss_date"], ch["SIM-AUTO-003"]["reported_date"]) == ("11/02/2025", "10/24/2025")
    assert ch["SIM-PKG-002"]["reported_date"] == "NOT PROVIDED"
    assert ch["SIM-WC-001"]["reserve_usd"] == ""
    assert ch["SIM-PKG-005"]["incurred_usd"] == "9200"
    assert "Bldg 003" in ch["SIM-PKG-003"]["description_asset"]
    assert ch["SIM-WC-002"]["description_asset"].startswith("5403")


def test_the_python_reader_and_the_frontend_parse_brents_files_cell_for_cell(tmp_path):
    o = _node(tmp_path, f"""
const files = {json.dumps([str(_DRIVERS_XLSX), str(_CLAIMS_XLSX)])};
const res = [];
for (const f of files) res.push(await S.parseXLSX(fs.readFileSync(f)));
out(res);
""")
    for js_rows, path in zip(o, (_DRIVERS_XLSX, _CLAIMS_XLSX)):
        norm = []
        for r in js_rows:
            cells = [" ".join(str(c).split()) for c in r]
            while cells and not cells[-1]:
                cells.pop()
            norm.append(cells)
        assert norm == st.read_xlsx(str(path))[0]["rows"]


def test_brents_files_through_the_upload_validation():
    for p in (_DRIVERS_XLSX, _CLAIMS_XLSX):
        assert validate_file_mime(p.read_bytes(), ".xlsx") == (True, "")


# ══════════════════════════════════════════════════════════════════════════════
# 4. CSV - delimiter and encoding detected
# ══════════════════════════════════════════════════════════════════════════════

def _csv(tmp_path, data: bytes, name="f.csv"):
    p = tmp_path / name
    p.write_bytes(data)
    return _text(p)


@pytest.mark.parametrize("sep", [",", ";", "\t", "|"])
def test_csv_delimiters_are_detected(tmp_path, sep):
    rows = [["Claim", "Loss Date", "Paid"], ["C-1", "03/14/2025", "1,200.50"], ["C-2", "04/01/2025", "0"]]
    if sep != ",":
        data = "\n".join(sep.join(r) for r in rows)
    else:
        data = "\n".join(",".join(f'"{c}"' if "," in c else c for c in r) for r in rows)
    out = _csv(tmp_path, data.encode("utf-8"))
    assert out.splitlines() == ["Claim | Loss Date | Paid", "C-1 | 03/14/2025 | 1,200.50", "C-2 | 04/01/2025 | 0"]


def test_a_european_csv_with_decimal_commas_splits_on_semicolons(tmp_path):
    out = _csv(tmp_path, "Name;Payroll;Rate\nAnn;1200,50;2,5\nBo;900,00;3,1\n".encode())
    assert out.splitlines() == ["Name | Payroll | Rate", "Ann | 1200,50 | 2,5", "Bo | 900,00 | 3,1"]


def test_csv_quoted_fields_line_breaks_doubled_quotes_and_an_excel_sep_line(tmp_path):
    data = 'sep=;\r\nid;note\r\n1;"two\r\nlines; one cell"\r\n2;"say ""hi"""\r\n\r\n;\r\n'
    assert _csv(tmp_path, data.encode()).splitlines() == ["id | note", "1 | two lines; one cell", '2 | say "hi"']


@pytest.mark.parametrize("raw, expect", [
    ("Café,Größe\nnaïve,x\n".encode("utf-8"), ["Café | Größe", "naïve | x"]),
    (b"\xef\xbb\xbf" + "Name,City\nAnn,Zürich\n".encode("utf-8"), ["Name | City", "Ann | Zürich"]),
    ("Name,Note\nAnn,“quoted” – x\n".encode("cp1252"), ["Name | Note", "Ann | “quoted” – x"]),
    (b"Name,Note\nAnn,\x81\xe9\n", ["Name | Note", "Ann | \x81\xe9"]),
    ("Name,City\nAnn,Zürich\n".encode("utf-16"), ["Name | City", "Ann | Zürich"]),
])
def test_csv_encodings(tmp_path, raw, expect):
    assert _csv(tmp_path, raw).splitlines() == expect


def test_csv_empty_columns_one_column_and_a_field_past_the_csv_module_limit(tmp_path):
    assert _csv(tmp_path, b"a,,c\n1,,3\n,,\n").splitlines() == ["a | c", "1 | 3"]
    assert _csv(tmp_path, b"just one column\nsecond line\n").splitlines() == ["just one column", "second line"]
    big = "x" * 200_000
    out = _csv(tmp_path, f'id,blob\n1,"{big}"\n'.encode())
    assert out.splitlines() == ["id | blob", f"1 | {big}"]


def test_csv_validation_refuses_binary_and_accepts_utf16(tmp_path):
    assert validate_file_mime(b"a,b\n1,2\n", ".csv") == (True, "")
    assert validate_file_mime("Name,City\nAnn,Zürich\n".encode("utf-16"), ".csv") == (True, "")
    ok, msg = validate_file_mime(b"PK\x03\x04\x00\x00binary", ".csv")
    assert not ok and "does not match the declared type '.csv'" in msg
    ok, msg = validate_file_mime(b"\xff\xfeA\x00B", ".csv")       # odd length: no UTF-16 text
    assert not ok and "not readable text" in msg
    # .txt keeps its own rule (a UTF-16 .txt is refused exactly as before)
    assert validate_file_mime("hi".encode("utf-16"), ".txt")[0] is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. The package check - refusals, macros, encryption, the ZIP bomb
# ══════════════════════════════════════════════════════════════════════════════

def test_refused_spreadsheet_formats_say_what_to_do():
    for ext in (".xls", ".xlsm", ".xlsb", ".xltx", ".xltm", ".ods", ".numbers"):
        ok, msg = validate_file_mime(b"anything at all", ext)
        assert not ok and msg == st.REFUSED_SPREADSHEET_EXTENSIONS[ext]
        assert ".xlsx" in msg and ".csv" in msg and not any(e in msg for e in _EM)
    assert "Excel 97-2003" in st.REFUSED_SPREADSHEET_EXTENSIONS[".xls"]
    assert "Macro-enabled" in st.REFUSED_SPREADSHEET_EXTENSIONS[".xlsm"]
    ok, msg = validate_file_mime(b"x", ".docx")
    assert not ok and msg == "File type '.docx' is not supported. Allowed: PDF, ZIP, JPG, PNG, BMP, TIFF, WEBP, TXT, XLSX, CSV."


def test_a_zip_that_is_not_a_workbook_and_a_renamed_file_are_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("claims.pdf", b"%PDF-1.4")
    assert validate_file_mime(buf.getvalue(), ".xlsx") == (False, st.XLSX_MISMATCH)
    assert validate_file_mime(b"%PDF-1.4 renamed", ".xlsx") == (False, st.XLSX_MISMATCH)
    assert validate_file_mime(b"PK\x03\x04 not really a zip", ".xlsx") == (False, st.XLSX_MISMATCH)
    # an encrypted .xlsx (and an .xls renamed .xlsx) is an OLE2 file
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    assert validate_file_mime(ole, ".xlsx") == (False, st.XLSX_PROTECTED)
    for m in (st.XLSX_MISMATCH, st.XLSX_PROTECTED, st.XLSX_MACROS, st.XLSX_TOO_LARGE):
        assert not any(e in m for e in _EM)


@pytest.mark.parametrize("how", ["vba", "content_type", "macrosheet"])
def test_a_workbook_with_macros_is_refused_whatever_its_name(tmp_path, how):
    extra, ct = {}, _CT
    if how == "vba":
        extra = {"xl/vbaProject.bin": b"\x00macro"}
    elif how == "content_type":
        ct = _CT.replace("sheet.main+xml", "sheet.macroEnabled.main+xml")
    else:
        extra = {"xl/macrosheets/sheet1.xml": "<xm/>"}
    p = _book(tmp_path / "m.xlsx", [{"name": "S", "data": _row(1, _n("A1", 1))}], content_types=ct, extra=extra)
    assert validate_file_mime(p.read_bytes(), ".xlsx") == (False, st.XLSX_MACROS)
    with pytest.raises(st.SpreadsheetError):
        st.read_xlsx(str(p))


def test_an_encrypted_zip_entry_is_refused(tmp_path):
    p = _book(tmp_path / "e.xlsx", [{"name": "S", "data": _row(1, _n("A1", 1))}])
    raw = bytearray(p.read_bytes())
    # set the "encrypted" flag bit on every entry (local + central headers)
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = raw.find(sig)
        while i != -1:
            raw[i + off] |= 0x01
            i = raw.find(sig, i + 4)
    assert validate_file_mime(bytes(raw), ".xlsx") == (False, st.XLSX_PROTECTED)


def test_the_zip_bomb_cap_holds_on_declared_and_on_actual_sizes(tmp_path, monkeypatch):
    big = _row(1, _inline("A1", "x" * 400_000))
    p = _book(tmp_path / "b.xlsx", [{"name": "S", "data": big}])
    assert p.stat().st_size < 20_000                              # compresses ~20x+
    monkeypatch.setattr(st, "MAX_XLSX_UNCOMPRESSED_BYTES", 100_000)
    assert validate_file_mime(p.read_bytes(), ".xlsx") == (False, st.XLSX_TOO_LARGE)
    # headers can lie: the bytes actually inflated are counted too
    monkeypatch.setattr(st, "_package_problem", lambda _zf: None)
    with pytest.raises(st.SpreadsheetError) as ei:
        st.read_xlsx(str(p))
    assert str(ei.value) == st.XLSX_TOO_LARGE
    monkeypatch.undo()
    assert validate_file_mime(p.read_bytes(), ".xlsx") == (True, "")
    monkeypatch.setattr(st, "MAX_XLSX_PARTS", 3)             # 4 parts: a ZIP of countless entries
    assert validate_file_mime(p.read_bytes(), ".xlsx") == (False, st.XLSX_TOO_LARGE)


def test_a_doctype_is_refused_before_any_entity_expands(tmp_path):
    lol = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
           f'<worksheet xmlns="{_NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is></c>'
           '</row></sheetData></worksheet>')
    q = tmp_path / "l.xlsx"
    with zipfile.ZipFile(q, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{_NS}"><sheets><sheet name="S" sheetId="1"/></sheets>'
                                      '</workbook>')
        z.writestr("xl/worksheets/sheet1.xml", lol)
    with pytest.raises(st.SpreadsheetError) as ei:
        st.read_xlsx(str(q))
    assert "DOCTYPE" in str(ei.value)


def test_a_malformed_part_makes_the_workbook_unreadable_not_half_read(tmp_path):
    p = _book(tmp_path / "bad.xlsx", [{"name": "S", "data": "<row r='1'><c r='A1'><v>1</v></row>"}])
    with pytest.raises(st.SpreadsheetError):
        st.read_xlsx(str(p))


# ══════════════════════════════════════════════════════════════════════════════
# 6. The doors: upload intake, extract_text, the per-document door, the routes
# ══════════════════════════════════════════════════════════════════════════════

def _upload(name, data: bytes):
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture
def intake(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_the_upload_door_keeps_xlsx_and_csv_as_documents(intake):
    up, docs = asyncio.run(ui.store_uploads([
        _upload("drivers.xlsx", _DRIVERS_XLSX.read_bytes()), _upload("claims.csv", b"id,paid\n1,200\n"),
        _upload("dec.pdf", b"%PDF-1.4 x"), _upload("note.txt", b"hello there")]))
    assert [Path(p).name.split("_", 1)[1] for p in docs] == ["drivers.xlsx", "claims.csv", "dec.pdf", "note.txt"]
    assert sorted(up) == sorted(docs)


@pytest.mark.parametrize("name", ["old.xls", "macro.xlsm"])
def test_the_upload_door_refuses_xls_and_xlsm_and_leaves_no_file(intake, name):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("ok.csv", b"a,b\n1,2\n"), _upload(name, b"\xd0\xcf\x11\xe0 x")]))
    assert ei.value.status_code == 400
    assert ei.value.detail == st.REFUSED_SPREADSHEET_EXTENSIONS[Path(name).suffix]
    assert list(intake.iterdir()) == []


def test_a_zip_reads_its_spreadsheets_and_still_skips_a_txt(intake):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pkg/claims.xlsx", _CLAIMS_XLSX.read_bytes())
        z.writestr("pkg/drivers.csv", "name,dob\nAnn,01/02/1980\n")
        z.writestr("pkg/readme.txt", "not a document")
        z.writestr("pkg/old.xls", b"\xd0\xcf\x11\xe0")
        z.writestr("pkg/macro.xlsm", b"PK")
        z.writestr("__MACOSX/pkg/._claims.xlsx", b"\x00\x05\x16\x07appledouble")
        z.writestr("pkg/", b"")
    _up, docs = asyncio.run(ui.store_uploads([_upload("package.zip", buf.getvalue())]))
    assert sorted(Path(p).name.split("_", 1)[1] for p in docs) == ["claims.xlsx", "drivers.csv"]


def test_a_zip_entry_past_the_per_file_cap_and_a_zip_past_the_aggregate_are_413(intake, monkeypatch):
    monkeypatch.setattr(ui, "MAX_UPLOAD_SIZE_BYTES", 2_000)
    monkeypatch.setattr(ui, "MAX_FILES_PER_UPLOAD", 2)
    one = io.BytesIO()
    with zipfile.ZipFile(one, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.csv", "a,b\n" + "1,2\n" * 1_000)          # 4,004 bytes unpacked
    assert len(one.getvalue()) < 2_000
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("one.zip", one.getvalue())]))
    assert (ei.value.status_code, ei.value.detail) == (413, "File 'big.csv' in 'one.zip' exceeds the 0 MB limit.")
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(3):
            z.writestr(f"part{i}.csv", "a,b\n" + "1,2\n" * 400)   # 1,604 bytes each, 4,812 in all
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ui.store_uploads([_upload("many.zip", many.getvalue())]))
    assert ei.value.status_code == 413 and "exceed the aggregate limit" in ei.value.detail
    assert list(intake.iterdir()) == []


def test_extract_text_reads_spreadsheets_and_a_broken_one_gives_no_text(tmp_path):
    from services.ocr_service import extract_text
    p = tmp_path / "abc_drivers.xlsx"
    p.write_bytes(_DRIVERS_XLSX.read_bytes())
    text, low = asyncio.run(extract_text(str(p)))
    assert low == [] and text.startswith("Sheet: Driver Schedule\n")
    assert "Daniel Mercer | 04/17/1982 | CO | 06/11/2018 | 21" in text
    c = tmp_path / "abc_c.csv"
    c.write_bytes(b"Claim,Loss Date\nC-1,03/14/2025\n")
    assert asyncio.run(extract_text(str(c))) == ("Claim | Loss Date\nC-1 | 03/14/2025", [])
    bad = tmp_path / "abc_bad.xlsx"
    bad.write_bytes(b"PK\x03\x04 broken")
    assert asyncio.run(extract_text(str(bad))) == ("", [])


def test_the_per_document_door_reads_a_workbook_like_any_document(tmp_path, monkeypatch):
    """extraction_pipeline.extract_document: the classifier and the extraction
    call see the sheet text. Measured on Brent's files with the existing
    classifier (NOT changed here): the driver file is a Driver Schedule; the
    claims workbook (snake_case headers - loss_date, paid_usd) is typed a loss
    run by its columns since Z40 (25 Oct 2026, owner: spreadsheet loss runs are
    recognised on their own); the type picker still overrides."""
    import services.extraction_pipeline as ep
    seen = []

    async def _extract(text, doc_type, low_confidence_tokens=None):
        seen.append((text, doc_type))
        return {"facts": {}, "flags": {}}
    monkeypatch.setattr(ep, "extract_facts_long", _extract)
    d = tmp_path / "abc_Primble_Sample_Driver_Schedule_12-10:17:26.xlsx"
    d.write_bytes(_DRIVERS_XLSX.read_bytes())
    doc = asyncio.run(ep.extract_document(str(d), "Primble_Sample_Driver_Schedule_12-10:17:26.xlsx", "u1"))
    assert doc["doc_type"] == "driver_schedule" and doc["filename"].endswith(".xlsx")
    assert seen[-1][0] == doc["text"] and "Hannah Price | 05/04/1997" in doc["text"]
    c = tmp_path / "abc_claims.xlsx"
    c.write_bytes(_CLAIMS_XLSX.read_bytes())
    doc = asyncio.run(ep.extract_document(str(c), "Primble-Choice-Electric-Synthetic-Claims-10:17:26.xlsx", "u1"))
    assert (doc["doc_type"], doc["doc_type_confidence"]) == ("loss_run", "high")
    assert doc["text"].count("SIM-") == 24
    doc = asyncio.run(ep.extract_document(str(c), "claims.xlsx", "u1", doc_type="loss_run"))
    assert doc["doc_type"] == "loss_run" and doc["doc_type_overridden"] is True
    assert seen[-1][1] == "loss_run"


# The add-documents route, end to end, on the shared stubbed package of the
# 7 Oct tests (database, audit and the extraction LLM stubbed; the intake, the
# REAL spreadsheet reader, the merge and the re-score are the real code).
from test_choice_electric_upload_7oct import (  # noqa: E402,F401  (the fixture)
    DEC, _Pool, add_via_route, body, env, make_package,
)


def test_add_documents_takes_an_excel_loss_run_end_to_end(env, monkeypatch):
    import services.extraction_pipeline as ep
    from services.ocr_service import extract_text as real_extract_text
    read = []

    async def _real(path):
        read.append(path)
        return await real_extract_text(path)
    monkeypatch.setattr(ep, "extract_text", _real)
    make_package(env, "s1", [DEC()])
    data = body(add_via_route("s1", [UploadFile(file=io.BytesIO(_CLAIMS_XLSX.read_bytes()),
                                                filename="Choice Electric claims.xlsx")],
                              doc_type="loss_run"))
    assert data["success"] and [d["filename"] for d in data["documents_added"]] == ["Choice Electric claims.xlsx"]
    added = data["documents_added"][0]
    assert added["doc_type"] == "loss_run"
    stored = env["store"].rows["s1"]["docs"][-1]
    assert stored["text"].startswith("Sheet: Primble_Choice_Electric_Synthet\n")
    assert stored["text"].count("SIM-") == 24 and "03/13/2025" in stored["text"]
    texts = [a[0] for a, _k in env["calls"]["extract"]]
    assert texts[-1] == stored["text"]                          # the extraction call saw the sheet
    assert len(read) == 1 and list(env["tmp"].iterdir()) == []   # temp files gone


@pytest.mark.parametrize("name", ["claims.xls", "claims.xlsm"])
def test_the_upload_and_add_routes_refuse_xls_and_xlsm_alike(env, monkeypatch, name):
    import routes.form_routes as fr
    make_package(env, "s1", [DEC()])
    monkeypatch.setattr(fr, "get_pool", lambda: _Pool())
    from test_choice_electric_upload_7oct import USER, run

    def files():
        return [UploadFile(file=io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), filename=name)]
    with pytest.raises(HTTPException) as up:
        run(fr.upload_declaration(files=files(), progress_token=None, current_user=USER))
    with pytest.raises(HTTPException) as add:
        add_via_route("s1", files())
    assert (up.value.status_code, up.value.detail) == (add.value.status_code, add.value.detail)
    assert add.value.status_code == 400
    assert add.value.detail == st.REFUSED_SPREADSHEET_EXTENSIONS[Path(name).suffix]


# ══════════════════════════════════════════════════════════════════════════════
# 7. The screens - one accept list, the drop filter, the badge, the copy
# ══════════════════════════════════════════════════════════════════════════════

def test_the_frontend_accept_list_is_the_servers(tmp_path):
    o = _node(tmp_path, "out(A.ACCEPT_UPLOAD.split(','));")
    assert set(o) == set(DOCUMENT_EXTENSIONS) | {".zip"}
    assert len(o) == len(set(o))


def test_the_drop_filter_and_the_badge(tmp_path):
    o = _node(tmp_path, """
const f = (name, type = '') => ({ name, type });
const files = [f('claims.XLSX'), f('drivers.csv'), f('old.xls'), f('macro.xlsm'), f('memo.docx'),
               f('scan', 'application/pdf'), f('photo.heic', 'image/heic'), f('dec.pdf'), f('pkg.zip'),
               f('notes.txt'), f('noext'), null];
out({drop: files.map((x) => A.isDroppableUpload(x)),
     badge: files.slice(0, 11).map((x) => A.uploadBadge(x)),
     note: A.UPLOAD_TYPES_NOTE});
""")
    assert o["drop"] == [True, True, True, True, False, True, True, True, True, True, False, False]
    assert [(b["label"], b["kind"]) for b in o["badge"]] == [
        ("XLSX", "sheet"), ("CSV", "sheet"), ("XLS", "sheet"), ("XLSM", "sheet"), ("DOCX", "document"),
        ("PDF", "document"), ("HEIC", "image"), ("PDF", "document"), ("ZIP", "zip"), ("TXT", "document"),
        ("FILE", "document")]
    assert "Excel (XLSX)" in o["note"] and "CSV" in o["note"] and not any(e in o["note"] for e in _EM)


def test_both_upload_inputs_read_the_one_list_and_the_start_shows_the_servers_reason():
    modal = (_FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    panel = (_FRONT / "components" / "form" / "review" / "AddDocumentsPanel.jsx").read_text(encoding="utf-8")
    assert 'accept=".pdf' not in modal and "accept={ACCEPT_UPLOAD}" in modal
    assert "accept={ACCEPT_UPLOAD}" in panel
    assert ".filter(isDroppableUpload)" in modal
    assert "uploadBadge(f)" in modal and '"PDF"}</span>' not in modal
    assert "{UPLOAD_TYPES_NOTE}" in modal
    assert 'setError(errorText(data, "Upload failed"))' in modal
    line = next(ln for ln in modal.splitlines() if "Dec pages, loss runs, schedules, quotes" in ln)
    assert "Excel or CSV" in line and not any(e in line for e in _EM)
