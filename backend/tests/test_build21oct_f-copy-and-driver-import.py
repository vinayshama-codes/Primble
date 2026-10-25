"""Build 21 Oct 2026, lane F, item f-copy-and-driver-import (25sepChanges.md Z29-2
items 2 and 5, Z30-F).

PART 1 - Brent's 17 Oct item 2, copy only. The Documents list's review sentence
moves under the list's title, in pink, in his words; the type pill reads his
"Highly Confident" / "Needs Verification" / "Unable to Classify" (no "Type:").

PART 2 - Brent's 17 Oct item 5 + attachment B (his 12-driver schedule, kept as
`fixtures/brent_driver_schedule_17oct.xlsx`). Three causes, all in
frontend/src/utils/scheduleImport.js:
  1. the header was assumed to be row 1. His file has two title rows and a
     blank row above it, so every column mapped by position: the titles and
     the header itself came in as drivers (15 rows for 12) and the licence
     STATE "CO" landed in the licence NUMBER column;
  2. "State Licensed In" / "Years of Experience" matched no header alias;
  3. parseXLSX ignored the workbook's styles, so date cells arrived as Excel
     serials (30058) and failed "must be MM/DD/YYYY".

The adversarial cases come first: a header must be FOUND without ever eating a
data row, and a wider alias table must never send one column's header to
another column. Everything runs the real module under node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_FIX = Path(__file__).resolve().parent / "fixtures"
_DRIVERS_XLSX = _FIX / "brent_driver_schedule_17oct.xlsx"
_CLAIMS_XLSX = _FIX / "brent_synthetic_claims_17oct.xlsx"
_EM = ("—", "–")

_BRENT_NOTE = ("Some documents require review. Confirm their document type to ensure accurate scoring "
               "and form recommendations, or exclude any that don't belong in this submission.")
_OLD_NOTE = "Some documents need review. Set the correct type"


def _node(tmp_path, body, name="check.mjs"):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / name
    script.write_text(
        f"import * as S from {json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
        f"import * as A from {json.dumps((_FRONT / 'utils' / 'addDocuments.js').as_uri())};\n"
        "import fs from 'node:fs';\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        "const file = (p, name) => { const b = fs.readFileSync(p); b.name = name; return b; };\n"
        + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _defs():
    """Every live schedule table, as the server sends it (columns and all)."""
    from services.schedule_capture import SCHEDULE_DEFS
    return json.loads(json.dumps(SCHEDULE_DEFS))


def _cols(list_key):
    return _defs()[list_key]["columns"]


_LIST_KEYS = sorted(_defs())


# ── a minimal .xlsx writer (the parts parseXLSX reads) ─────────────────────────
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(path, sheet_data, *, styles=None, workbook_pr="", shared=None, prefix=""):
    """`sheet_data` is the inner XML of <sheetData>; `prefix` writes every
    SpreadsheetML element with a namespace prefix ("x:"), as some writers do."""
    p = f"{prefix}:" if prefix else ""
    xmlns = f'xmlns:{prefix}="{_NS}"' if prefix else f'xmlns="{_NS}"'
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<{p}worksheet {xmlns}><{p}sheetData>{sheet_data}</{p}sheetData></{p}worksheet>')
    wb = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><{p}workbook {xmlns}>{workbook_pr}'
          f'<{p}sheets><{p}sheet name="Sheet1" sheetId="1"/></{p}sheets></{p}workbook>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if styles is not None:
            z.writestr("xl/styles.xml", f'<?xml version="1.0"?><{p}styleSheet {xmlns}>{styles}</{p}styleSheet>')
        if shared is not None:
            z.writestr("xl/sharedStrings.xml",
                       f'<?xml version="1.0"?><{p}sst {xmlns}>{"".join(shared)}</{p}sst>')
    return path


def _styles(num_fmts, xf_ids):
    """numFmts {id: code} + cellXfs numFmtIds (index = the cell's s="...")."""
    nf = "".join(f'<numFmt numFmtId="{i}" formatCode={quoteattr(c)}/>' for i, c in num_fmts.items())
    xfs = "".join(f'<xf numFmtId="{i}" fontId="0" fillId="0" borderId="0" xfId="0"/>' for i in xf_ids)
    # cellStyleXfs and dxfs carry their own <xf> / <numFmt>: they must never be read as the cell styles.
    return (f'<numFmts count="{len(num_fmts)}">{nf}</numFmts>'
            '<cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs>'
            f'<cellXfs count="{len(xf_ids)}">{xfs}</cellXfs>'
            '<dxfs count="1"><dxf><numFmt numFmtId="3" formatCode="mm/dd/yyyy"/></dxf></dxfs>')


def _serial_1900(d):
    n = (d - date(1899, 12, 30)).days
    return n if n >= 61 else n - 1


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 - the header row is FOUND (adversarial first)
# ══════════════════════════════════════════════════════════════════════════════

def test_a_header_less_list_still_imports_every_row_by_position(tmp_path):
    """No row names two columns = no header: today's positional import, row 1
    included. A lone alias word in a data cell ("Location") is not a header."""
    o = _node(tmp_path, f"""
const loc = {json.dumps(_cols("property_locations"))};
const drv = {json.dumps(_cols("auto_drivers"))};
const a = S.rowsFromMatrix([['12 Oak St', '', 'Denver', 'CO', '80202', 'Location'],
                            ['9 Elm Ave', '', 'Boulder', 'CO', '80301', 'Warehouse']], loc);
const b = S.rowsFromMatrix([['Ann Lee', '01/02/1980', 'L123', 'CO', '03/04/2010', '9']], drv);
out({{a: [a.usedHeader, a.headerRow, a.rows.map((r) => r.address_line1 + '|' + r.operations_description)],
      b: [b.usedHeader, b.rows.length, b.rows[0].license_number, b.rows[0].license_state]}});
""")
    assert o["a"] == [False, -1, ["12 Oak St|Location", "9 Elm Ave|Warehouse"]]
    assert o["b"] == [False, 1, "L123", "CO"]


def test_a_data_row_never_outranks_the_header_and_a_tie_goes_to_the_earliest(tmp_path):
    """A later row that happens to name columns (two cells reading "State" /
    "City") stays a data row - it is never the header and never dropped. Two
    rows naming the same number of columns: the earlier one is the header."""
    o = _node(tmp_path, f"""
const loc = {json.dumps(_cols("property_locations"))};
const m = [['Street address', 'Suite / unit', 'City', 'State', 'ZIP'],
           ['12 Oak St', '', 'Denver', 'CO', '80202'],
           ['City', '', 'State', 'CO', '80301']];
const r = S.rowsFromMatrix(m, loc);
const tie = S.rowsFromMatrix([['Street address', 'City'], ['City', 'State'], ['1 Main St', 'Denver']], loc);
out({{head: r.headerRow, rows: r.rows.map((x) => x.address_line1 + '|' + x.address_city),
      tie: [tie.headerRow, tie.rows.map((x) => x.address_line1 + '|' + x.address_city)]}});
""")
    assert o["head"] == 0
    assert o["rows"] == ["12 Oak St|Denver", "City|State"]
    # the tie: row 0 is the header; row 1 is (odd) data, never silently lost
    assert o["tie"] == [0, ["City|State", "1 Main St|Denver"]]


@pytest.mark.parametrize("list_key", _LIST_KEYS)
def test_title_rows_above_the_header_are_never_imported_for_every_table(tmp_path, list_key):
    """Brent's shape (two title rows, a blank row, then the header) on EVERY
    live schedule table: the rows above the header are titles, never data."""
    cols = _cols(list_key)
    labels = [c["label"] for c in cols]
    o = _node(tmp_path, f"""
const cols = {json.dumps(cols)};
const labels = {json.dumps(labels)};
const title1 = ['COMMERCIAL AUTO | SAMPLE SCHEDULE', ...labels.slice(1).map(() => '')];
const title2 = ['FICTIONAL TEST DATA - for testing only'];
const blank = labels.map(() => '');
const row = (s) => cols.map((c, i) => `v${{i}}${{s}}`);
const r = S.rowsFromMatrix([title1, title2, blank, labels, row('a'), row('b')], cols);
out({{used: r.usedHeader, head: r.headerRow, unmatched: r.unmatched, n: r.rows.length,
      first: r.rows[0], cells: r.rows.flatMap((x) => Object.values(x))}});
""")
    assert o["used"] is True and o["head"] == 3 and o["unmatched"] == []
    assert o["n"] == 2
    # (a VIN cell is upper-cased on import, as before)
    assert o["first"] == {c["key"]: (f"v{i}a".upper() if c["type"] == "vin" else f"v{i}a")
                          for i, c in enumerate(cols)}
    assert not set(o["cells"]) & ({"COMMERCIAL AUTO | SAMPLE SCHEDULE", "FICTIONAL TEST DATA - for testing only"}
                                  | set(labels))


def test_a_header_repeated_further_down_is_not_a_row(tmp_path):
    """A report that prints its header again (a page break) - the copy is not
    a driver. A row only partly equal to the header is data."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const head = ['Full Name', 'Date of Birth', 'State Licensed In', 'Date Hired', 'Years of Experience'];
const r = S.rowsFromMatrix([head, ['Ann Lee', '01/02/1980', 'CO', '03/04/2010', '9'], head,
                            ['Full Name', '02/02/1981', 'WY', '', '4']], drv);
out(r.rows.map((x) => x.name + '|' + x.license_state));
""")
    assert o == ["Ann Lee|CO", "Full Name|WY"]


def test_a_multi_level_header_takes_the_row_that_names_more_columns(tmp_path):
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const r = S.rowsFromMatrix([['Driver', '', 'License', '', 'Dates', ''],
                            ['Full Name', 'DOB', 'License #', 'License State', 'Date Hired', 'Years Experience'],
                            ['Ann Lee', '01/02/1980', 'L123', 'CO', '03/04/2010', '9']], drv);
out([r.headerRow, r.rows.length, r.rows[0]]);
""")
    assert o[0] == 1 and o[1] == 1
    assert o[2] == {"name": "Ann Lee", "dob": "01/02/1980", "license_number": "L123", "license_state": "CO",
                    "hire_date": "03/04/2010", "experience_years": "9"}


def test_a_label_value_preamble_naming_as_many_columns_is_not_the_header(tmp_path):
    """A report preamble ("Name: | ACME | State: | CO") names two columns, as
    many as a sparse real header below it: the row that labels every column
    (fills the most cells) is the header. A real header is never displaced by a
    data row of the same width (the earliest still wins that tie)."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const r = S.rowsFromMatrix([['Name:', 'ACME TRUCKING LLC', 'State:', 'CO'],
                            ['Driver', 'DOB', 'Lic', 'St', 'Hire', 'Exp'],
                            ['Ann Lee', '01/02/1980', 'L123', 'CO', '03/04/2010', '9']], drv);
out([r.headerRow, r.rows.map((x) => x.name + '|' + x.dob), r.unmatched]);
""")
    assert o[0] == 1
    assert o[1] == ["Ann Lee|01/02/1980"]
    assert o[2] == ["Lic", "St", "Hire", "Exp"]


def test_a_preamble_longer_than_the_scan_keeps_todays_positional_import(tmp_path):
    """The limit, pinned: past HEADER_SCAN_ROWS rows nothing is guessed - the
    old positional import runs and the table says no header was recognised."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const pre = Array.from({{length: S.HEADER_SCAN_ROWS}}, (_, i) => [`Preamble line ${{i + 1}}`]);
const r = S.rowsFromMatrix([...pre, ['Full Name', 'DOB'], ['Ann Lee', '01/02/1980']], drv);
const near = S.rowsFromMatrix([...pre.slice(1), ['Full Name', 'DOB'], ['Ann Lee', '01/02/1980']], drv);
out([S.HEADER_SCAN_ROWS, r.usedHeader, near.usedHeader, near.rows.length]);
""")
    assert o == [15, False, True, 1]


# ── review of 21 Oct, H1: the first header wins once data starts ─────────────
# A later header-like row (more columns named, or one more cell filled) used to
# replace the real header and every row above it - real data included - was
# dropped without a word. The three reviewer repros, run through the real module.

def test_a_trailers_block_with_its_own_wider_header_keeps_the_trucks_above_it(tmp_path):
    o = _node(tmp_path, f"""
const veh = {json.dumps(_cols("auto_vin_schedule"))};
const r = S.rowsFromMatrix([['Year', 'Make', 'Model', 'VIN'],
                            ['2019', 'Ford', 'F-250', '1FTBF2B60KEA00001'],
                            ['2021', 'Ram', '2500', '3C6UR5CJ1MG000002'],
                            ['Trailers'],
                            ['Year', 'Make', 'Model', 'VIN', 'Trailer type'],
                            ['2015', 'Big Tex', '14LP', '16VEX1424F0000003', 'Dump']], veh);
out({{head: r.headerRow, rows: r.rows.map((x) => x.year + '|' + x.make + '|' + x.vin),
      above: r.skippedAbove, inside: r.skippedInside}});
""")
    assert o["head"] == 0
    assert o["rows"] == ["2019|Ford|1FTBF2B60KEA00001", "2021|Ram|3C6UR5CJ1MG000002",
                         "2015|Big Tex|16VEX1424F0000003"]
    assert o["above"] == 0 and o["inside"] == 2          # the block title and its header


def test_an_excluded_drivers_block_keeps_the_drivers_above_it(tmp_path):
    """Nothing is silently lost: the block's driver imports too, visible in the
    table for the person to keep or delete (whether an excluded driver belongs
    on the schedule is not an import decision)."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const head = ['Full Name', 'Date of Birth', 'License #', 'License State'];
const r = S.rowsFromMatrix([head,
                            ['Ann Lee', '01/02/1980', 'L123', 'CO'],
                            ['Bo Diaz', '03/04/1985', 'L456', 'CO'],
                            ['', '', '', ''],
                            ['Excluded drivers'],
                            [...head, 'Reason excluded'],
                            ['Cy Park', '05/06/1999', 'L789', 'WY', 'Suspended licence']], drv);
out({{head: r.headerRow, rows: r.rows.map((x) => x.name + '|' + x.license_number), inside: r.skippedInside}});
""")
    assert o["head"] == 0
    assert o["rows"] == ["Ann Lee|L123", "Bo Diaz|L456", "Cy Park|L789"]
    assert o["inside"] == 2


def test_a_page_header_repeated_with_an_extra_cell_is_skipped_not_the_header(tmp_path):
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const head = ['Full Name', 'Date of Birth', 'License #', 'License State'];
const r = S.rowsFromMatrix([head,
                            ['Ann Lee', '01/02/1980', 'L123', 'CO'],
                            ['Bo Diaz', '03/04/1985', 'L456', 'CO'],
                            [...head, 'Page 2 of 2'],
                            ['Cy Park', '05/06/1999', 'L789', 'WY']], drv);
out({{head: r.headerRow, rows: r.rows.map((x) => x.name), inside: r.skippedInside, above: r.skippedAbove}});
""")
    assert o == {"head": 0, "rows": ["Ann Lee", "Bo Diaz", "Cy Park"], "inside": 1, "above": 0}


def test_a_data_row_holding_column_words_in_other_places_is_still_a_row_below(tmp_path):
    """The repeated-header test is by LAYOUT: a row naming columns where the
    header does not have them is data, kept (adversarial pair of the three)."""
    o = _node(tmp_path, f"""
const loc = {json.dumps(_cols("property_locations"))};
const r = S.rowsFromMatrix([['Street address', 'Suite / unit', 'City', 'State', 'ZIP'],
                            ['12 Oak St', '', 'Denver', 'CO', '80202'],
                            ['City', '', 'State', 'CO', '80301']], loc);
out([r.rows.length, r.skippedInside]);
""")
    assert o == [2, 0]


def test_rows_above_the_header_are_counted_and_named_to_the_person(tmp_path):
    """Brent's file: two title rows above the header - skipped, and the import
    message says so. A header in row 1 says nothing."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const r = await S.parseScheduleFile(file({json.dumps(str(_DRIVERS_XLSX))}, 'drivers.xlsx'), drv);
const plain = S.rowsFromMatrix([['Full Name', 'DOB'], ['Ann Lee', '01/02/1980']], drv);
out([r.skippedAbove, r.skippedInside, S.skippedRowsText(r), plain.skippedAbove, S.skippedRowsText(plain),
     S.skippedRowsText({{skippedAbove: 1, skippedInside: 3}})]);
""")
    assert o[0] == 2 and o[1] == 0
    assert o[2] == " Skipped 2 rows above the column headings (titles or notes)."
    assert o[3] == 0 and o[4] == ""
    assert o[5] == (" Skipped 1 row above the column headings (titles or notes)."
                    " Skipped 3 rows further down that repeat the headings or title a block.")
    assert not any(e in o[5] for e in _EM)


def test_the_schedule_table_prints_the_skipped_rows_note():
    src = (_FRONT / "components" / "arq" / "ScheduleTable.jsx").read_text(encoding="utf-8")
    # 22 Oct 2026: the totals rows ride along (test_build23_small-fixes.py).
    assert "skippedRowsText({ skippedAbove, skippedInside, skippedTotals })" in src


# ── header names: wider, never crossed ───────────────────────────────────────

def test_no_header_name_is_shared_by_two_columns_of_one_table(tmp_path):
    """Every name a column answers to (its key, its label, every alias) maps to
    THAT column alone, in every live table - a wider alias table can never
    send one column's header to another."""
    o = _node(tmp_path, f"""
const defs = {json.dumps(_defs())};
const bad = [];
for (const [key, d] of Object.entries(defs)) {{
  for (const col of d.columns) {{
    for (const cand of S.headerCandidates(col)) {{
      const {{ mapping }} = S.mapHeaders([cand], d.columns);
      const got = Object.keys(mapping);
      if (got.length !== 1 || got[0] !== col.key) bad.push(`${{key}}.${{col.key}} <- ${{cand}} -> ${{got}}`);
    }}
  }}
}}
out(bad);
""")
    assert o == []


def test_brents_driver_headers_map_to_their_own_columns(tmp_path):
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
out(S.mapHeaders(['Full Name', 'Date of Birth', 'State Licensed In', 'Date Hired', 'Years of Experience'], drv));
""")
    assert o["mapping"] == {"name": 0, "dob": 1, "license_state": 2, "hire_date": 3, "experience_years": 4}
    assert o["unmatched"] == []          # every column of his file has a home
    assert "license_number" not in o["mapping"]


@pytest.mark.parametrize("header,col", [
    ("State Licensed In", "license_state"), ("State Licensed", "license_state"),
    ("Licensed State", "license_state"), ("Licensed In", "license_state"),
    ("State of License", "license_state"), ("Licence State", "license_state"),
    ("State Licenced In", "license_state"), ("DL State", "license_state"),
    ("Driver's License State", "license_state"), ("Issuing State", "license_state"),
    ("License State", "license_state"), ("State", "license_state"),
    ("License", "license_number"), ("License #", "license_number"), ("Licence Number", "license_number"),
    ("License No.", "license_number"), ("DL #", "license_number"), ("Driver's License Number", "license_number"),
    ("Date of Hire", "hire_date"), ("Hire Date", "hire_date"),
])
def test_licence_state_and_number_headers_never_cross(tmp_path, header, col):
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
out(S.mapHeaders([{json.dumps(header)}], drv).mapping);
""")
    assert o == {col: 0}


def test_years_of_experience_is_only_ever_the_experience_count(tmp_path):
    """Never a "year first licensed" or any other date (Brent: no estimates).
    The driver table's count column takes it; a licensed-YEAR header maps to
    nothing; a table with no experience column (the location table has a YEAR
    column, year built) ignores it and says so."""
    o = _node(tmp_path, f"""
const defs = {json.dumps(_defs())};
const drv = defs.auto_drivers.columns;
const exp = ['Years of Experience', 'Years Experience', 'Yrs of Experience', 'Driving Experience',
             'Years of Driving Experience', 'Years Driving', 'Experience'];
const where = {{}};
for (const [key, d] of Object.entries(defs)) {{
  for (const h of exp) {{
    const {{ mapping }} = S.mapHeaders([h], d.columns);
    for (const k of Object.keys(mapping)) {{
      const c = d.columns.find((x) => x.key === k);
      (where[`${{key}}.${{k}}`] = where[`${{key}}.${{k}}`] || new Set()).add(c.type);
    }}
  }}
}}
const licensedYear = ['Year Licensed', 'Year First Licensed', 'Years Licensed', 'First Licensed', 'Licensed Year'];
const loc = S.mapHeaders(['Street address', 'City', 'Years of Experience'], defs.property_locations.columns);
out({{where: Object.fromEntries(Object.entries(where).map(([k, v]) => [k, [...v]])),
      drv: exp.map((h) => S.mapHeaders([h], drv).mapping),
      licensed: licensedYear.map((h) => S.mapHeaders([h], drv)),
      loc}});
""")
    assert o["where"] == {"auto_drivers.experience_years": ["number"]}
    assert all(m == {"experience_years": 0} for m in o["drv"]), o["drv"]
    for r in o["licensed"]:
        assert r["mapping"] == {} and len(r["unmatched"]) == 1
    assert o["loc"]["mapping"] == {"address_line1": 0, "address_city": 1}
    assert o["loc"]["unmatched"] == ["Years of Experience"]


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 - Excel serials and number formats
# ══════════════════════════════════════════════════════════════════════════════

def test_excel_serials_become_mm_dd_yyyy_in_both_date_systems(tmp_path):
    cases_1900 = [30058, 43262, 1, 59, 61, 45729, 2958465, 45000.75, 44999.9999999999]
    o = _node(tmp_path, f"""
out({{d1900: {json.dumps(cases_1900)}.map((n) => S.excelSerialToDate(n)),
      bad: [60, 0, -1, 2958466, NaN, 'x', null].map((n) => S.excelSerialToDate(n)),
      d1904: [0, 28596, 1].map((n) => S.excelSerialToDate(n, true))}});
""")
    def ref(n):
        whole = int(n + 1e-9)
        d = date(1899, 12, 31) + timedelta(days=whole) if whole < 60 else date(1899, 12, 30) + timedelta(days=whole)
        return d.strftime("%m/%d/%Y")
    assert o["d1900"] == [ref(n) for n in cases_1900]
    assert o["d1900"][:6] == ["04/17/1982", "06/11/2018", "01/01/1900", "02/28/1900", "03/01/1900", "03/13/2025"]
    assert o["d1900"][6] == "12/31/9999"
    assert o["d1900"][7] == "03/15/2023"               # a date-time keeps its day
    assert o["d1900"][8] == "03/15/2023"               # float noise a hair under midnight is that midnight
    # 01/00/1900 and the phantom 02/29/1900 (Excel's 1900 leap-year bug) are no
    # real day: no date is made up - the cell keeps its stored number.
    assert o["bad"] == ["", "", "", "", "", "", ""]
    assert o["d1904"] == ["01/01/1904", "04/17/1982", "01/02/1904"]


@pytest.mark.parametrize("code,kind", [
    # dates
    ("mm/dd/yyyy", "date"), ("m/d/yyyy", "date"), ("d-mmm-yy", "date"), ("mmm-yy", "date"),
    ("yyyy-mm-dd hh:mm", "date"), ("m/d/yy h:mm", "date"), ("[$-409]mmmm d, yyyy;@", "date"),
    ("[$-F800]dddd, mmmm dd, yyyy", "date"), ("dd/mm/yyyy", "date"), ('yyyy"年"m"月"d"日"', "date"),
    # times: no date part to show - never turned into a day
    ("h:mm", "time"), ("hh:mm:ss", "time"), ("mm:ss", "time"), ("h:mm AM/PM", "time"),
    ("h:mm:ss A/P", "time"), ("[h]:mm:ss", "time"), ("[mm]:ss", "time"), ("mmss.0", "time"),
    ("[$-F400]h:mm:ss\\ AM/PM", "time"),
    # numbers that only LOOK like they carry d / m / y letters
    ("General", "number"), ("0", "number"), ("0.00", "number"), ("#,##0", "number"),
    ('0" days"', "number"), ('#,##0" yrs"', "number"), ("0\\d", "number"), ("0.00E+00", "number"),
    ("@", "number"), ("[Red]#,##0.00", "number"), ('_("$"* #,##0_);_("$"* \\(#,##0\\);_("$"* "-"_);_(@_)', "number"),
    ('_ * #,##0.00_ ;_ * \\-#,##0.00_ ;_ * "-"??_ ;_ @_ ', "number"), ("# ?/?", "number"), ("0", "number"),
    # percent / leading zeros: the other two ways a stored number reads differently
    ("0%", "percent"), ("0.00%", "percent"), ("[Red]0.0%", "percent"),
    ("00000", "zeros"), ("00000\\-0000", "zeros"), ("000-00-0000", "zeros"), ("(000) 000-0000", "zeros"),
])
def test_number_format_kinds(tmp_path, code, kind):
    o = _node(tmp_path, f"out(S.numberFormatKind({json.dumps(code)}).kind);")
    assert o == kind


def test_builtin_ids_and_what_a_cell_shows(tmp_path):
    """Excel's own built-ins (no numFmt entry in the file): 14-17 and 22 are
    dates; 18-21 and 45-47 times; the locale ids en-US Excel shows as m/d/yyyy
    (27-31, 50-58 - Brent's claims sheet uses 58) are dates; 9 / 10 percent.
    Then the rendered cell for each kind. Z31-X (21 Oct 2026): every cell now
    reads as the sheet shows it - this test pinned the old reader in six places
    (a time cell kept its stored number, a percent dropped Excel's minus, a
    zero-padded cell kept a fraction or a sign as stored, #,##0 lost its
    separators); tests/test_build22_excel-formats.py holds the full set."""
    o = _node(tmp_path, """
const kinds = {};
for (let i = 0; i <= 82; i += 1) kinds[i] = S.numberFormatKind(S.builtinFormatCode(i)).kind;
out({kinds,
     shown: [S.formatCellNumber('30058', 'mm/dd/yyyy'), S.formatCellNumber('30058', S.builtinFormatCode(58)),
             S.formatCellNumber('0.5', 'h:mm'), S.formatCellNumber('45000.5', 'h:mm'),
             S.formatCellNumber('1', '0%'), S.formatCellNumber('0.125', '0%'), S.formatCellNumber('0.125', '0.0%'),
             S.formatCellNumber('-0.001', '0%'), S.formatCellNumber('8540', '00000'),
             S.formatCellNumber('12345', '00000'), S.formatCellNumber('123456', '00000'),
             S.formatCellNumber('12345678', '00000\\\\-0000'), S.formatCellNumber('3035551234', '(000) 000-0000'),
             S.formatCellNumber('12.5', '00000'), S.formatCellNumber('-5', '00000'),
             S.formatCellNumber('21', 'General'), S.formatCellNumber('1200000', '#,##0'),
             S.formatCellNumber('60', 'mm/dd/yyyy'), S.formatCellNumber('', 'mm/dd/yyyy'),
             S.formatCellNumber('abc', 'mm/dd/yyyy'), S.formatCellNumber('28596', 'mm/dd/yyyy', true)]});
""")
    k = {int(i): v for i, v in o["kinds"].items()}
    dates = {14, 15, 16, 17, 22, 27, 28, 29, 30, 31, 50, 51, 52, 53, 54, 55, 56, 57, 58, 71, 72, 73, 74, 75, 78}
    times = {18, 19, 20, 21, 45, 46, 47, 76, 77, 79, 80, 81}
    assert {i for i, v in k.items() if v == "date"} == dates
    assert {i for i, v in k.items() if v == "time"} == times
    assert {i for i, v in k.items() if v == "percent"} == {9, 10, 67, 68}
    assert not {i for i, v in k.items() if v == "zeros"}
    assert o["shown"] == ["04/17/1982", "04/17/1982",
                          "12:00", "12:00",                       # a time as the sheet shows it
                          "100%", "13%", "12.5%", "-0%", "08540",  # one section: Excel keeps the minus
                          "12345", "123456", "01234-5678", "(303) 555-1234",
                          "00013", "-00005",                      # Excel rounds 12.5 up; the minus shows
                          "21", "1,200,000",
                          "60", "", "abc", "04/17/1982"]


def test_parse_xlsx_reads_the_styles_text_stays_text_and_1904_counts(tmp_path):
    styles = _styles({164: "mm/dd/yyyy", 165: "h:mm", 166: "0.0%", 167: "00000", 42: '_("$"* #,##0_)'},
                     [0, 164, 165, 166, 167, 14, 42, 58])
    shared = ['<si><t>Name</t></si>', '<si><t>04/01/2020</t></si>',
              '<si><r><t>Ann </t></r><r><rPr><b/></rPr><t>Lee</t></r><rPh sb="0" eb="1"><t>PHONETIC</t></rPh></si>',
              '<si><t xml:space="preserve"> A &amp; B </t></si>']
    data = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s" s="1"><v>1</v></c></row>'
            '<row r="2"><c r="A2" s="1"><v>30058</v></c><c r="B2" s="2"><v>0.5</v></c><c r="C2" s="3"><v>1</v></c>'
            '<c r="D2" s="4"><v>8540</v></c><c r="E2" s="5"><v>43262</v></c><c r="F2" s="6"><v>1200000</v></c>'
            '<c r="G2" s="7"><v>45729</v></c><c r="H2" s="1" t="str"><v>45729</v></c><c r="I2" t="b"><v>1</v></c></row>'
            '<row r="3"><c r="A3" t="s"><v>2</v></c><c r="C3" t="inlineStr" s="1"><is><t>NOT PROVIDED</t></is></c>'
            '<c r="E3" t="d"><v>2026-01-15T00:00:00</v></c><c r="F3" t="s"><v>3</v></c><c r="G3" s="9"><v>30058</v></c></row>'
            '<row r="4"><c t="s"><v>0</v></c><c><v>7</v></c></row>'          # cells with no r: next column
            '<row r="5"><c r="A5" s="1"/><c r="B5"/></row>')                   # styled but empty: no row
    plain = _xlsx(tmp_path / "plain.xlsx", data, styles=styles, shared=shared)
    y1904 = _xlsx(tmp_path / "y1904.xlsx", '<row r="1"><c r="A1" s="1"><v>28596</v></c></row>',
                  styles=styles, workbook_pr='<workbookPr date1904="1"/>')
    pfx = _xlsx(tmp_path / "pfx.xlsx", '<x:row r="1"><x:c r="B1" s="1"><x:v>30058</x:v></x:c>'
                '<x:c r="C1" t="s"><x:v>0</x:v></x:c></x:row>', styles=None, prefix="x",
                shared=['<x:si><x:t>Name</x:t></x:si>'])
    pfx_styled = _xlsx(tmp_path / "pfx2.xlsx", '<x:row r="1"><x:c r="A1" s="1"><x:v>30058</x:v></x:c></x:row>',
                       prefix="x", styles=(
                           '<x:numFmts count="1"><x:numFmt numFmtId="170" formatCode="d-mmm-yy"/></x:numFmts>'
                           '<x:cellXfs count="2"><x:xf numFmtId="0"/><x:xf numFmtId="170"><x:alignment/></x:xf>'
                           '</x:cellXfs>'))
    o = _node(tmp_path, f"""
out({{plain: await S.parseXLSX(file({json.dumps(str(plain))}, 'plain.xlsx')),
      y1904: await S.parseXLSX(file({json.dumps(str(y1904))}, 'y.xlsx')),
      pfx: await S.parseXLSX(file({json.dumps(str(pfx))}, 'p.xlsx')),
      pfx2: await S.parseXLSX(file({json.dumps(str(pfx_styled))}, 'p2.xlsx'))}});
""")
    assert o["plain"][0] == ["Name", "04/01/2020"]                 # a date-styled TEXT cell is left alone
    # Z31-X: the time, the file's own accounting code (" $1,200,000 ", trimmed
    # by the table import) and the boolean read as the sheet shows them.
    assert o["plain"][1] == ["04/17/1982", "12:00", "100.0%", "08540", "06/11/2018", " $1,200,000 ",
                             "03/13/2025", "45729", "TRUE"]
    assert o["plain"][2] == ["Ann Lee", "", "NOT PROVIDED", "", "01/15/2026", " A & B ", "30058"]
    assert o["plain"][3] == ["Name", "7"]
    assert len(o["plain"]) == 4                                    # the styled-but-empty row is not a row
    assert o["y1904"] == [["04/17/1982"]]
    assert o["pfx"] == [["", "30058", "Name"]]                      # no styles part: General
    assert o["pfx2"] == [["04/17/1982"]]


def test_a_cell_reference_past_excels_last_column_is_ignored(tmp_path):
    """XFD is Excel's last column; a crafted reference never pads a row out to
    millions of cells."""
    wb = _xlsx(tmp_path / "wide.xlsx", '<row r="1"><c r="A1"><v>1</v></c><c r="ZZZZZZ1"><v>2</v></c>'
               '<c r="XFD1"><v>3</v></c></row>', styles=None)
    o = _node(tmp_path, f"const m = await S.parseXLSX(file({json.dumps(str(wb))}, 'w.xlsx')); "
                        "out([m[0].length, m[0][0], m[0][16383]]);")
    assert o == [16384, "1", "3"]


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 - Brent's real files
# ══════════════════════════════════════════════════════════════════════════════

_BRENT_DRIVERS = [  # name, DOB serial, state, hired serial, years
    ("Daniel Mercer", 30058, "CO", 43262, "21"), ("Alicia Bennett", 33119, "CO", 44277, "13"),
    ("Marcus Ellison", 28102, "WY", 42597, "27"), ("Sofia Ramirez", 34754, "CO", 45047, "9"),
    ("Nathan Brooks", 31977, "CO", 43745, "17"), ("Priya Desai", 33914, "NM", 44606, "11"),
    ("Christopher Hale", 29249, "CO", 42114, "24"), ("Emily Foster", 35958, "CO", 45481, "6"),
    ("Jordan Whitaker", 31136, "KS", 43843, "19"), ("Olivia Chen", 34196, "CO", 44823, "10"),
    ("Benjamin Ortiz", 29149, "CO", 43045, "26"), ("Hannah Price", 35554, "CO", 45691, "7"),
]


def _from_serial(n):
    return (date(1899, 12, 30) + timedelta(days=n)).strftime("%m/%d/%Y")


def _import_brents_file(tmp_path):
    assert _DRIVERS_XLSX.exists(), "fixture missing"
    return _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const r = await S.parseScheduleFile(file({json.dumps(str(_DRIVERS_XLSX))}, 'Primble_Sample_Driver_Schedule_12.xlsx'), drv);
const v = S.validateRows(r.rows, drv, ['name', 'dob']);
out({{r, errors: v.errors, dupes: [...v.duplicates]}});
""")


def test_brents_driver_file_imports_twelve_drivers_with_real_dates(tmp_path):
    o = _import_brents_file(tmp_path)
    r = o["r"]
    assert r["usedHeader"] is True and r["headerRow"] == 2 and r["unmatched"] == []
    assert len(r["rows"]) == 12                                   # was 15: two titles and the header
    want = [{"name": n, "dob": _from_serial(b), "license_number": "", "license_state": s,
             "hire_date": _from_serial(h), "experience_years": y} for n, b, s, h, y in _BRENT_DRIVERS]
    assert r["rows"] == want
    assert r["rows"][0]["dob"] == "04/17/1982" and r["rows"][0]["hire_date"] == "06/11/2018"
    assert all(re.fullmatch(r"\d{2}/\d{2}/\d{4}", x[k]) for x in r["rows"] for k in ("dob", "hire_date"))
    # the table's own check finds nothing wrong: no serials, the states are states
    assert o["errors"] == {} and o["dupes"] == []


def test_brents_missing_licence_numbers_stay_blank_and_are_flagged_never_guessed(tmp_path):
    """His file has no licence numbers. Before, the licence STATE landed in the
    licence NUMBER column by position. Now the cells are blank, the server
    accepts the rows, and the driver row rules flag every missing number
    (advisory, `fact_registry.SCHEDULE_ROW_RULES`) - nothing else."""
    from services import schedule_capture as sc
    from services.fact_registry import validate_schedule_rows
    rows = _import_brents_file(tmp_path)["r"]["rows"]
    assert {x["license_number"] for x in rows} == {""}
    assert "CO" not in {x["license_number"] for x in rows}
    clean, report = sc.validate_rows("auto_drivers", rows)
    assert report["errors"] == {} and report["duplicates"] == [] and len(clean) == 12
    issues = validate_schedule_rows("auto_drivers", rows)
    assert {(i["sub_key"], i["issue"]) for i in issues} == {("license_number", "missing")}
    assert len(issues) == 12


def test_brents_file_saved_as_csv_imports_the_same_twelve(tmp_path):
    """The same sheet as a CSV (dates already text): the header is found the same way."""
    lines = ["COMMERCIAL AUTO | SAMPLE DRIVER SCHEDULE,,,,",
             "FICTIONAL TEST DATA - For Primble submission testing only,,,,", ",,,,",
             "Full Name,Date of Birth,State Licensed In,Date Hired,Years of Experience"]
    lines += [f"{n},{_from_serial(b)},{s},{_from_serial(h)},{y}" for n, b, s, h, y in _BRENT_DRIVERS]
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
const f = {{ name: 'drivers.csv', text: async () => {json.dumps(chr(10).join(lines))} }};
const r = await S.parseScheduleFile(f, drv);
out([r.usedHeader, r.rows.length, r.rows[0], r.rows[11].name]);
""")
    assert o[0] is True and o[1] == 12
    assert o[2] == {"name": "Daniel Mercer", "dob": "04/17/1982", "license_number": "", "license_state": "CO",
                    "hire_date": "06/11/2018", "experience_years": "21"}
    assert o[3] == "Hannah Price"


def test_brents_claims_sheet_dates_read_through_wps_builtin_58(tmp_path):
    """Attachment C was written by WPS Sheets with built-in format 58 and no
    numFmt entry. Its dates arrive as dates; "NOT PROVIDED" stays text; the
    loss table finds the header in row 1 (the claims checks are a later item)."""
    assert _CLAIMS_XLSX.exists(), "fixture missing"
    o = _node(tmp_path, f"""
const loss = {json.dumps(_cols("loss_history"))};
const m = await S.parseXLSX(file({json.dumps(str(_CLAIMS_XLSX))}, 'claims.xlsx'));
const r = S.rowsFromMatrix(m, loss);
out({{head: m[0].slice(5, 8), r1: m[1].slice(5, 8), r17: m[17].slice(5, 8), n: m.length,
      used: r.usedHeader, rows: r.rows.length, dates: r.rows.map((x) => x.date)}});
""")
    assert o["head"] == ["loss_date", "first_made_date", "reported_date"]
    assert o["r1"] == ["03/13/2025", "", "03/15/2025"]
    assert o["r17"][2] == "NOT PROVIDED"
    assert o["n"] == 25 and o["used"] is True and o["rows"] == 24
    assert all(re.fullmatch(r"\d{2}/\d{2}/\d{4}", d) for d in o["dates"])


def test_an_ignored_column_is_still_named_to_the_person(tmp_path):
    """Reuses the table's existing message ("Ignored extra column(s): ...")."""
    o = _node(tmp_path, f"""
const drv = {json.dumps(_cols("auto_drivers"))};
out(S.rowsFromMatrix([['Title row'], ['Full Name', 'DOB', 'Years Licensed', 'Shoe size'], ['Ann Lee', '01/02/1980', '9', '7']], drv).unmatched);
""")
    assert o == ["Years Licensed", "Shoe size"]
    table = (_FRONT / "components" / "arq" / "ScheduleTable.jsx").read_text(encoding="utf-8")
    assert "Ignored extra column(s): ${unmatched.slice(0, 4).join(', ')}." in table


def test_parse_xlsx_needs_no_browser_dom():
    """One reader for the browser and node: no DOMParser (it does not exist
    under node, which is why the old reader had no test at all)."""
    src = (_FRONT / "utils" / "scheduleImport.js").read_text(encoding="utf-8")
    assert "DOMParser" not in src and "querySelector" not in src
    assert not any(d in src for d in _EM)


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - Brent's words on the Documents list
# ══════════════════════════════════════════════════════════════════════════════

def test_the_type_tag_reads_brents_words(tmp_path):
    o = _node(tmp_path, """
out([{doc_type_confidence: 'high'}, {doc_type_confidence: 'medium'}, {doc_type_confidence: 'low'},
     {doc_type_confidence: 'odd'}, {doc_type_overridden: true, doc_type_confidence: 'low'}, {}, null,
     {doc_type_confidence: 3}].map((r) => A.documentTypeTag(r)));
""")
    labels = [t and t["label"] for t in o]
    assert labels == ["Highly Confident", "Needs Verification", "Unable to Classify", "Unable to Classify",
                      "Set by you", None, None, None]
    assert not any(lab and lab.startswith("Type:") for lab in labels)
    # the hover text is Brent's "Meaning" column, plus the 14 Oct note that the
    # pill is about the TYPE, never whose document it is
    assert o[0]["title"].startswith("Primble has high confidence in its document classification.")
    assert o[1]["title"].startswith("Primble has identified a probable document type, but confirmation is recommended.")
    assert o[2]["title"].startswith("Primble cannot confidently identify the document type.")
    assert all("TYPE" in t["title"] and "not whose document it is" in t["title"] for t in o[:4])
    assert [t["color"] for t in o[:3]] == ["#16a34a", "#d97706", "#dc2626"]     # display only: colours kept
    for t in o[:5]:
        assert not any(d in t["label"] + t["title"] for d in _EM)


def test_the_review_sentence_is_brents_and_pink(tmp_path):
    o = _node(tmp_path, "out([A.DOCUMENTS_REVIEW_NOTE, A.REVIEW_NOTE_STYLE]);")
    assert o[0] == _BRENT_NOTE
    assert o[1]["color"].lower() == "#e61b84"          # the app's pink notes (no box)
    assert "background" not in o[1] and "border" not in o[1]


def _region(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_both_layouts_print_the_sentence_under_the_list_title_and_only_for_open_documents():
    modal = (_FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    rail = (_FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    css = (_FRONT / "components" / "form" / "review" / "ReviewRailLayout.css").read_text(encoding="utf-8")
    for text in (modal, rail):
        assert _OLD_NOTE not in text
        assert "DOCUMENTS_REVIEW_NOTE" in text
    # classic layout: inside the "Documents Processed" section, above its rows
    sec = _region(modal, "title={`Documents Processed (${docSummary.length})`}", "renderAddDocumentsPanel()")
    assert sec.index("{DOCUMENTS_REVIEW_NOTE}") < sec.index("docSummary.map(")
    assert "docsNeedingReview.length > 0" in sec[:sec.index("{DOCUMENTS_REVIEW_NOTE}")]
    assert "REVIEW_NOTE_STYLE" in sec
    # rail: in the panel's title block (under "Documents Processed"), above its rows
    head = _region(rail, "title={`Documents Processed (${docSummary.length})`}", "docSummary.map(")
    assert "{DOCUMENTS_REVIEW_NOTE}" in head and "docsNeedingReview.length > 0" in head
    rule = re.search(r"\.rr-doc-note-review\s*\{([^}]*)\}", css).group(1)
    assert "#e61b84" in rule.lower() and "#92400e" not in rule
    # the old block under the list is gone from both
    assert modal.count("{DOCUMENTS_REVIEW_NOTE}") == 1 and rail.count("{DOCUMENTS_REVIEW_NOTE}") == 1


def test_no_old_type_label_is_left_anywhere_in_the_frontend():
    hits = []
    for p in _FRONT.rglob("*"):
        if p.suffix in (".js", ".jsx") and p.is_file():
            t = p.read_text(encoding="utf-8")
            for old in ("Type: sure", "Type: likely", "Type: unsure", "Type: set by you"):
                if old in t:
                    hits.append(f"{p.name}: {old}")
    assert hits == []
