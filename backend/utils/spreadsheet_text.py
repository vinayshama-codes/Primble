"""An Excel workbook (.xlsx) or a CSV file, read as document text.

THE DEFECT THIS CLOSES (Brent's Choice Electric test, 17 Oct 2026, item 1 -
25sepChanges.md Z29-2). "Excel will not upload" - at the start or in "Add
documents". The upload door (`utils/mime_validator`, `services/upload_intake`)
and both file inputs took PDF / ZIP / images / TXT only, so a loss summary or
a driver list kept as a spreadsheet could not be part of a submission at all;
only the schedule tables' own import read .xlsx / .csv. A spreadsheet now goes
through the SAME door as every other document: validated here and in
`mime_validator`, virus-scanned, turned into text by `ocr_service.extract_text`
(which calls `spreadsheet_text` below), then classified, extracted, merged,
checked by Data Consistency and listed on the review like a PDF.

THE TEXT. One block per sheet, in the workbook's own tab order:

    Sheet: <name>            ("Sheet: <name> (hidden)" for a hidden sheet)
    <row>                    every non-empty row, its cells joined by " | "

  * EVERY sheet is read, hidden ones included and labelled - the owner's rule:
    the whole uploaded document matters. A chart sheet holds no cells and
    prints nothing; an empty sheet prints nothing.
  * empty rows and columns are dropped; the columns a sheet uses stay in their
    places, so every row lines up with its header. Trailing empty cells go.
  * a cell's whitespace (line breaks included) is collapsed to one space, so a
    cell never breaks its row; a cell that itself holds " | " (Brent's claims
    sheet: "V009 | 2017 Chevrolet Express G2500 | ...") is wrapped in double
    quotes, CSV-style, so it stays ONE column for whoever reads the row.
  * formulas are never evaluated: a formula cell reads its cached value (what
    the sheet showed when it was saved); one saved without a value is empty.
  * a CSV prints its rows the same way, with no heading (it has no sheets).

THE CELLS ARE READ AS THE SHEET SHOWS THEM - through ONE renderer shared with
the schedule tables' import (utils/excel_number_format.py and its line-for-line
twin frontend/src/utils/excelNumberFormat.js, pinned by one set of test
vectors; Z31-X, 21 Oct 2026 - read that module's note):
  * every section of every number format: built-ins and the locale ids Excel
    maps onto them (Brent's claims sheet dates every cell with 58), General as
    Excel shows it (0.30000000000000004 -> 0.3) EXCEPT where Excel's text is
    another number than the cell stores: a 12- to 15-digit claim / policy
    number reads 123456789012 (Excel shows 1.23457E+11), a long decimal keeps
    its digits - two IDs never read as one (Z31-X review, `keep_digits`),
    conditional sections ([<=99999]00000;00000-0000 -> 08540-1234), currency
    and accounting ($1,234.50, (1,234.00)), percent, phone / SSN / ZIP digits,
    scientific, fractions, scaling commas, literals and currency tags.
  * a format showing a day of the month, a month and a year is MM/DD/YYYY (plus
    the time it shows: "03/14/2025 1:30 PM"); a year-only, month-only or time
    format prints as shown ("2020", "March", "Mar-20", "1:30 PM", "37:30:00").
    The 1900 system counts Excel's phantom 29 Feb 1900 (days 1-59 sit one day
    later than 61 and up; day 0 and day 60 are no date and print as General);
    the 1904 system (workbookPr date1904) counts from 01/01/1904.
  * text through the format's text section (@ is the text); TRUE / FALSE for
    a boolean; an error cell is its error code ("#N/A", "#DIV/0!") whatever its
    format; a strict-OOXML ISO date cell (t="d") through its date format, else
    MM/DD/YYYY. A value no format can show, or a malformed format, is General.
  * the spaces a format pads with are trimmed with the cell's other outer
    whitespace (below).

SAFETY. Standard library only (zipfile, pyexpat, csv). Every XML part is
streamed through expat with any DOCTYPE refused (no entities, no external
references). The ZIP is checked before it is read (`xlsx_package_problem`, the
same check the upload door runs): it must hold [Content_Types].xml and
xl/workbook.xml; macros (vbaProject.bin, macro sheets, a macro-enabled content
type) and encrypted parts are refused; the parts' declared uncompressed size is
capped (XLSX_MAX_UNCOMPRESSED_MB, default 100) and so are the bytes actually
read, so a ZIP "bomb" never inflates past the cap whatever its headers claim.
.xls (Excel 97-2003, binary) and .xlsm (macro-enabled) are refused with a
message saying what to do - no parser for .xls exists in this backend and none
is added; reading .xlsm's cells would be possible, but a macro workbook is
refused on purpose.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import posixpath
import re
import zipfile
from typing import Callable, Dict, List, Optional, Tuple
from xml.parsers import expat

logger = logging.getLogger(__name__)

XLSX_EXTENSION = ".xlsx"
CSV_EXTENSION = ".csv"
SPREADSHEET_EXTENSIONS = frozenset({XLSX_EXTENSION, CSV_EXTENSION})

# ── What is refused, and what the producer is told ───────────────────────────
_SAVE_AS = "Open it in Excel and save it as an Excel Workbook (.xlsx) or as CSV (.csv), then upload it again."
REFUSED_SPREADSHEET_EXTENSIONS: Dict[str, str] = {
    ".xls": "Excel 97-2003 workbooks (.xls) cannot be read. " + _SAVE_AS,
    ".xlsm": "Macro-enabled Excel workbooks (.xlsm) are not accepted. " + _SAVE_AS,
    ".xlsb": "Excel binary workbooks (.xlsb) cannot be read. " + _SAVE_AS,
    ".xltx": "Excel templates (.xltx) are not accepted. " + _SAVE_AS,
    ".xltm": "Macro-enabled Excel templates (.xltm) are not accepted. " + _SAVE_AS,
    ".ods": "OpenDocument spreadsheets (.ods) cannot be read. Save it as an Excel Workbook (.xlsx) or as CSV (.csv), then upload it again.",
    ".numbers": "Apple Numbers files cannot be read. Export it as an Excel Workbook (.xlsx) or as CSV (.csv), then upload it again.",
}
XLSX_MISMATCH = ("File content does not match the declared type '.xlsx'. "
                 "The file may be corrupted or renamed to bypass validation.")
XLSX_PROTECTED = ("This Excel file is password-protected, or it is an Excel 97-2003 file renamed to .xlsx. "
                  "Remove the password, or open it in Excel and save it as an Excel Workbook (.xlsx), "
                  "then upload it again.")
XLSX_MACROS = ("This Excel workbook contains macros, which are not accepted. "
               "Save it as an Excel Workbook (.xlsx) without macros, or as CSV (.csv), then upload it again.")


def _env_mb(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# A real workbook's XML is a few MB; 100 MB unpacked is far past any sheet the
# extraction step can take (its own cap is ACORDLY_MAX_DOC_TOKENS) and well
# inside what the server can stream.
MAX_XLSX_UNCOMPRESSED_BYTES = _env_mb("XLSX_MAX_UNCOMPRESSED_MB", 100) * 1024 * 1024
MAX_XLSX_PARTS = 10_000
XLSX_TOO_LARGE = (f"This Excel workbook is too large to read (more than "
                  f"{MAX_XLSX_UNCOMPRESSED_BYTES // 1024 // 1024} MB once unpacked). "
                  "Split it into smaller workbooks and upload them again.")

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"      # OLE2: .xls, or an encrypted .xlsx
_ZIP_MAGIC = b"PK\x03\x04"


class SpreadsheetError(ValueError):
    """A spreadsheet that cannot be read (the reason is the message)."""


# ══════════════════════════════════════════════════════════════════════════════
# The package check - the upload door and the reader run this one function
# ══════════════════════════════════════════════════════════════════════════════

def _names(zf: zipfile.ZipFile) -> Dict[str, str]:
    """Part names, case-insensitively (OOXML part names ignore case)."""
    return {i.filename.lower(): i.filename for i in zf.infolist()}


def _package_problem(zf: zipfile.ZipFile) -> Optional[str]:
    infos = zf.infolist()
    if len(infos) > MAX_XLSX_PARTS:
        return XLSX_TOO_LARGE
    names = _names(zf)
    if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
        return XLSX_MISMATCH
    if any(i.flag_bits & 0x1 for i in infos):            # an encrypted ZIP entry
        return XLSX_PROTECTED
    if any(n.endswith("vbaproject.bin") or n.startswith("xl/macrosheets/") for n in names):
        return XLSX_MACROS
    if sum(max(0, i.file_size) for i in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
        return XLSX_TOO_LARGE
    try:
        with zf.open(names["[content_types].xml"]) as fh:
            types = fh.read(1024 * 1024).lower()
    except Exception:                                    # noqa: BLE001
        return XLSX_MISMATCH
    if b"macroenabled" in types or b"vbaproject" in types or b"macrosheet" in types:
        return XLSX_MACROS
    return None


def xlsx_package_problem(content: bytes) -> Optional[str]:
    """None when `content` is a workbook this module can read; otherwise the
    sentence the producer is shown. Cheap: reads the ZIP directory and the
    content-types part only."""
    if content[:8] == _CFB_MAGIC:
        return XLSX_PROTECTED
    if not content.startswith(_ZIP_MAGIC):
        return XLSX_MISMATCH
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return _package_problem(zf)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError, ValueError):
        return XLSX_MISMATCH


# ══════════════════════════════════════════════════════════════════════════════
# Streaming XML (expat, no DOCTYPE), within one byte budget per workbook
# ══════════════════════════════════════════════════════════════════════════════

class _Budget:
    def __init__(self, limit: int):
        self.left = limit

    def spend(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise SpreadsheetError(XLSX_TOO_LARGE)


def _refuse_doctype(*_a) -> None:
    raise SpreadsheetError("a workbook part declares a DOCTYPE (refused)")


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def _stream_part(zf: zipfile.ZipFile, part: str, budget: _Budget,
                 start: Callable, end: Callable, chars: Optional[Callable] = None) -> None:
    p = expat.ParserCreate()
    p.buffer_text = True
    p.StartDoctypeDeclHandler = _refuse_doctype
    p.EntityDeclHandler = _refuse_doctype
    p.StartElementHandler = lambda name, attrs: start(_local(name), attrs)
    p.EndElementHandler = lambda name: end(_local(name))
    if chars is not None:
        p.CharacterDataHandler = chars
    try:
        with zf.open(part) as fh:
            while True:
                chunk = fh.read(1 << 16)
                if not chunk:
                    break
                budget.spend(len(chunk))
                p.Parse(chunk, False)
        p.Parse(b"", True)
    except expat.ExpatError as ex:
        raise SpreadsheetError(f"{part} is not well-formed XML ({ex})") from ex
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as ex:
        raise SpreadsheetError(f"{part} cannot be unpacked ({ex})") from ex


def _attr(attrs: dict, local: str, default: str = "") -> str:
    """An attribute by local name, prefixed ("r:id") or not."""
    if local in attrs:
        return attrs[local]
    for k, v in attrs.items():
        if ":" in k and k.rsplit(":", 1)[-1] == local:
            return v
    return default


def _relationships(zf: zipfile.ZipFile, names: Dict[str, str], part: str,
                   budget: _Budget) -> Dict[str, Tuple[str, str]]:
    """{Id: (Type, resolved part path)} for `part`'s .rels (empty when absent)."""
    folder, base = posixpath.split(part)
    rels_name = names.get(posixpath.join(folder, "_rels", base + ".rels").lower())
    out: Dict[str, Tuple[str, str]] = {}
    if not rels_name:
        return out

    def start(tag, attrs):
        if tag != "Relationship" or attrs.get("TargetMode", "").lower() == "external":
            return
        target = str(attrs.get("Target", "")).replace("\\", "/")
        if not target:
            return
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[attrs.get("Id", "")] = (attrs.get("Type", ""), path)

    _stream_part(zf, rels_name, budget, start, lambda _t: None)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Number formats - utils/excel_number_format.py (the schedule import's twin)
# ══════════════════════════════════════════════════════════════════════════════
# Every cell is read through ONE renderer, shared line for line with the
# frontend's schedule import (frontend/src/utils/excelNumberFormat.js) and held
# to it by one set of test vectors. The names below are that module's, kept
# here for this reader's callers.
from utils.excel_number_format import (  # noqa: E402,F401  (grouped with the code it replaced)
    builtin_format_code, excel_serial_to_date, format_cell_number, format_iso_date, format_text,
    number_format_kind,
)

# ══════════════════════════════════════════════════════════════════════════════
# The workbook
# ══════════════════════════════════════════════════════════════════════════════

_MAX_COLUMNS = 16_384            # XFD
_MAX_ROWS = 1_048_576
_SHARED_INDEX_RE = re.compile(r"^[ \t\n\r\f\v]*([0-9]+)[ \t\n\r\f\v]*$")
_WS_RE = re.compile(r"\s+")
_REL_WORKSHEET = "/worksheet"
_REL_CHARTSHEET = "/chartsheet"


def _cell_value_text(value: str) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


# A string part writes a character XML cannot hold as _xHHHH_ (ECMA-376
# ST_Xstring) - Excel's line break inside a cell is "_x000D_". One left-to-
# right pass is the rule: a literal "_x0041_" is written "_x005F_x0041_".
_OOXML_ESCAPE_RE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _unescape_ooxml(text: str) -> str:
    return _OOXML_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text) if "_x" in text else text


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        o = ord(ch.upper())
        if 65 <= o <= 90:
            n = n * 26 + (o - 64)
            if n > _MAX_COLUMNS:
                return -1
        else:
            break
    return n - 1


def _read_shared_strings(zf, part: str, budget: _Budget) -> List[str]:
    strings: List[str] = []
    state = {"si": None, "t": False, "rph": 0}

    def start(tag, _attrs):
        if tag == "si":
            state["si"] = []
        elif tag == "rPh":
            state["rph"] += 1
        elif tag == "t" and state["si"] is not None and not state["rph"]:
            state["t"] = True

    def end(tag):
        if tag == "si":
            strings.append(_unescape_ooxml("".join(state["si"] or [])))
            state["si"] = None
        elif tag == "rPh":
            state["rph"] = max(0, state["rph"] - 1)
        elif tag == "t":
            state["t"] = False

    def chars(data):
        if state["t"] and state["si"] is not None:
            state["si"].append(data)

    _stream_part(zf, part, budget, start, end, chars)
    return strings


def _read_styles(zf, part: str, budget: _Budget) -> Tuple[Dict[int, str], List[int]]:
    """({numFmtId: code} of <numFmts>, [numFmtId per <cellXfs> <xf>]) - never
    <cellStyleXfs>, never a <numFmt> inside <dxfs>."""
    fmts: Dict[int, str] = {}
    xf_ids: List[int] = []
    stack: List[str] = []

    def start(tag, attrs):
        parent = stack[-1] if stack else ""
        if tag == "numFmt" and parent == "numFmts":
            try:
                fmts[int(attrs.get("numFmtId", ""))] = attrs.get("formatCode", "")
            except ValueError:
                pass
        elif tag == "xf" and parent == "cellXfs":
            try:
                xf_ids.append(int(attrs.get("numFmtId", "0") or 0))
            except ValueError:
                xf_ids.append(0)
        stack.append(tag)

    def end(_tag):
        if stack:
            stack.pop()

    _stream_part(zf, part, budget, start, end)
    return fmts, xf_ids


class _SheetReader:
    """Streams one worksheet's <sheetData> into {row: {column: text}} - only
    non-empty cells are kept."""

    def __init__(self, shared: List[str], format_of: Callable[[str], dict], date1904: bool):
        self.shared, self.format_of, self.date1904 = shared, format_of, date1904
        self.rows: Dict[int, Dict[int, str]] = {}
        self.row = -1
        self.col = -1
        self.cell: Optional[dict] = None
        self.where: Optional[str] = None                 # "v" | "is_t"
        self.rph = 0
        self.unsaved_formulas = 0

    def start(self, tag, attrs):
        if tag == "row":
            try:
                self.row = int(attrs.get("r", "")) - 1
            except ValueError:
                self.row += 1
            self.col = -1
        elif tag == "c":
            ref = attrs.get("r", "")
            col = _col_index(ref) if ref else self.col + 1
            self.cell = {"col": col, "t": attrs.get("t", "n"), "s": attrs.get("s", ""),
                         "v": [], "is": [], "f": False, "in_is": False}
        elif self.cell is not None:
            if tag == "v":
                self.where = "v"
            elif tag == "f":
                self.cell["f"] = True
            elif tag == "is":
                self.cell["in_is"] = True
            elif tag == "rPh":
                self.rph += 1
            elif tag == "t" and self.cell["in_is"] and not self.rph:
                self.where = "is_t"

    def end(self, tag):
        if tag == "c" and self.cell is not None:
            self._finish_cell()
            self.cell, self.where = None, None
        elif tag in ("v", "t"):
            self.where = None
        elif tag == "rPh":
            self.rph = max(0, self.rph - 1)
        elif tag == "is" and self.cell is not None:
            self.cell["in_is"] = False

    def chars(self, data):
        if self.cell is None or self.where is None:
            return
        self.cell["v" if self.where == "v" else "is"].append(data)

    def _finish_cell(self):
        c = self.cell
        col = c["col"]
        self.col = col if col >= 0 else self.col + 1
        if col < 0 or col >= _MAX_COLUMNS or not (0 <= self.row < _MAX_ROWS):
            return
        raw = "".join(c["v"])
        kind = c["t"]
        # Every value as the sheet shows it, through the cell's number format
        # (utils/excel_number_format.py - the schedule import's twin): text
        # through the format's text section, a number through its section.
        fmt = self.format_of(c["s"])
        if kind == "s":
            # The index is its ASCII digits alone - the schedule import's rule
            # (scheduleImport.js SHARED_INDEX_RE): "1.5", "2abc", "+1" or "-1" is
            # no index; one outside the table is no text.
            m = _SHARED_INDEX_RE.match(raw)
            i = int(m.group(1)) if m else -1
            value = format_text(self.shared[i], fmt) if 0 <= i < len(self.shared) else ""
        elif kind == "inlineStr":
            value = format_text(_unescape_ooxml("".join(c["is"]) if c["is"] else raw), fmt)
        elif kind == "d":
            value = format_iso_date(raw, fmt, self.date1904)
        elif kind == "b":
            value = {"1": "TRUE", "0": "FALSE"}.get(raw.strip(), raw)
        elif kind == "str":
            value = format_text(_unescape_ooxml(raw), fmt)   # a formula's text result: as shown
        elif kind == "e":
            value = raw          # an error ("#N/A", "#DIV/0!"): its code, whatever the format
        else:
            # keep_digits: a General number Excel would cut (a 12-digit claim
            # number shown 1.23457E+11) reads with every digit it stores.
            value = format_cell_number(raw, fmt, self.date1904, keep_digits=True) if raw.strip() else ""
        if c["f"] and not raw.strip() and not c["is"]:
            self.unsaved_formulas += 1
        value = _cell_value_text(value)
        if value:
            self.rows.setdefault(self.row, {})[col] = value


def read_xlsx(path: str) -> List[dict]:
    """Every sheet of the workbook at `path`, in tab order:
    [{"name", "hidden", "rows": [[cell text, ...], ...]}] - empty rows and
    columns dropped, trailing empty cells trimmed. A chart sheet holds no rows.
    Raises SpreadsheetError for a file this module will not read."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError) as ex:
        raise SpreadsheetError(XLSX_MISMATCH) from ex
    with zf:
        problem = _package_problem(zf)
        if problem:
            raise SpreadsheetError(problem)
        names = _names(zf)
        budget = _Budget(MAX_XLSX_UNCOMPRESSED_BYTES)
        wb_part = names["xl/workbook.xml"]

        sheets: List[dict] = []
        wb_state = {"date1904": False, "in_sheets": False}

        def wb_start(tag, attrs):
            if tag == "workbookPr":
                wb_state["date1904"] = str(attrs.get("date1904", "")).strip().lower() in ("1", "true")
            elif tag == "sheets":
                wb_state["in_sheets"] = True
            elif tag == "sheet" and wb_state["in_sheets"]:
                sheets.append({"name": _cell_value_text(attrs.get("name", "")),
                               "state": str(attrs.get("state", "")).strip().lower(),
                               "rid": _attr(attrs, "id")})

        def wb_end(tag):
            if tag == "sheets":
                wb_state["in_sheets"] = False

        _stream_part(zf, wb_part, budget, wb_start, wb_end)
        rels = _relationships(zf, names, "xl/workbook.xml", budget)

        def rel_part(suffix: str, fallback: str) -> Optional[str]:
            for typ, target in rels.values():
                if typ.endswith(suffix):
                    return names.get(target.lower())
            return names.get(fallback)

        shared_part = rel_part("/sharedStrings", "xl/sharedstrings.xml")
        styles_part = rel_part("/styles", "xl/styles.xml")
        shared = _read_shared_strings(zf, shared_part, budget) if shared_part else []
        fmts, xf_ids = _read_styles(zf, styles_part, budget) if styles_part else ({}, [])
        kinds: Dict[int, dict] = {}

        def format_of(s: str) -> dict:
            try:
                idx = int(s) if str(s).strip() else 0
            except ValueError:
                idx = 0
            if idx not in kinds:
                fmt_id = xf_ids[idx] if 0 <= idx < len(xf_ids) else 0
                kinds[idx] = number_format_kind(fmts[fmt_id] if fmt_id in fmts else builtin_format_code(fmt_id))
            return kinds[idx]

        # Worksheet parts by position, for a workbook written without rels.
        loose = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if not sheets:
            sheets = [{"name": f"Sheet{i + 1}", "state": "", "rid": ""} for i in range(len(loose))]

        out: List[dict] = []
        used: set = set()
        for i, sh in enumerate(sheets):
            typ, part = rels.get(sh["rid"], ("", ""))
            part = names.get(part.lower()) if part else None
            if part is None and not typ and i < len(loose):
                typ, part = _REL_WORKSHEET, names[loose[i]]
            hidden = sh["state"] in ("hidden", "veryhidden")
            name = sh["name"] or f"Sheet{i + 1}"
            if typ.endswith(_REL_CHARTSHEET) or part is None or not typ.endswith(_REL_WORKSHEET):
                out.append({"name": name, "hidden": hidden, "rows": []})
                continue
            if part in used:
                continue
            used.add(part)
            reader = _SheetReader(shared, format_of, wb_state["date1904"])
            _stream_part(zf, part, budget, reader.start, reader.end, reader.chars)
            if reader.unsaved_formulas:
                logger.info("spreadsheet_text: sheet %r has %d formula cell(s) saved without a value "
                            "(printed empty - formulas are never evaluated)", name, reader.unsaved_formulas)
            out.append({"name": name, "hidden": hidden, "rows": _matrix(reader.rows)})
        return out


def _matrix(rows: Dict[int, Dict[int, str]]) -> List[List[str]]:
    """{row: {col: text}} -> rows of the columns any row uses, in order."""
    cols = sorted({c for cells in rows.values() for c in cells})
    out: List[List[str]] = []
    for r in sorted(rows):
        cells = [rows[r].get(c, "") for c in cols]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            out.append(cells)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CSV
# ══════════════════════════════════════════════════════════════════════════════

_DELIMITERS = (",", ";", "\t", "|")
_SEP_LINE_RE = re.compile(r"^\s*sep\s*=\s*(.)\s*$", re.I)


def decode_text_bytes(data: bytes) -> str:
    """CSV bytes as text: a BOM decides (UTF-8, UTF-16); else UTF-8, then
    Windows-1252 (Excel's "CSV (Comma delimited)"), then Latin-1, which never
    fails."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _split_csv(text: str, delimiter: str) -> List[List[str]]:
    """RFC 4180 rows (quoted fields, doubled quotes, line breaks inside quotes;
    \\r, \\n and \\r\\n all end a row). csv's per-field limit is not ours to
    change process-wide, so an over-long field falls back to the same rules
    written out (scheduleImport.js's parseCSV, with a delimiter)."""
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False))
    except csv.Error:
        pass
    rows, row, field, quoted, i = [], [], [], False, 0
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    quoted = False
            else:
                field.append(ch)
        elif ch == '"' and not field:
            quoted = True
        elif ch == delimiter:
            row.append("".join(field))
            field = []
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
        else:
            field.append(ch)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows


def detect_delimiter(text: str) -> str:
    """The delimiter that splits the most sample rows into the SAME number of
    fields (two or more); ties go to the earlier of comma, semicolon, tab,
    pipe. A file that splits on none is one column (comma)."""
    sample = "\n".join(text.splitlines()[:200])
    best, best_score = ",", (0.0, 0)
    for d in _DELIMITERS:
        widths = [len(r) for r in _split_csv(sample, d) if any(str(c).strip() for c in r)]
        if not widths:
            continue
        common = max(set(widths), key=lambda w: (widths.count(w), w))
        if common < 2:
            continue
        score = (widths.count(common) / len(widths), common)
        if score > best_score:
            best, best_score = d, score
    return best


def read_csv(path: str) -> List[List[str]]:
    """A CSV file's rows, empty rows and columns dropped, cells whitespace-
    collapsed. An Excel "sep=;" first line names the delimiter."""
    with open(path, "rb") as fh:
        text = decode_text_bytes(fh.read())
    lines = text.split("\n", 1)
    m = _SEP_LINE_RE.match(lines[0].rstrip("\r")) if lines else None
    if m:
        delimiter = m.group(1)
        text = lines[1] if len(lines) > 1 else ""
    else:
        delimiter = detect_delimiter(text)
    cells: Dict[int, Dict[int, str]] = {}
    for r, row in enumerate(_split_csv(text, delimiter)):
        for c, value in enumerate(row):
            v = _cell_value_text(value)
            if v:
                cells.setdefault(r, {})[c] = v
    return _matrix(cells)


# ══════════════════════════════════════════════════════════════════════════════
# The text
# ══════════════════════════════════════════════════════════════════════════════

def _cell_out(value: str) -> str:
    """A cell holding the column separator stays one column: quoted, CSV-style."""
    if "|" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def render_rows(rows: List[List[str]]) -> List[str]:
    return [" | ".join(_cell_out(c) for c in row) for row in rows]


def xlsx_text(path: str) -> str:
    blocks: List[str] = []
    for sheet in read_xlsx(path):
        lines = render_rows(sheet["rows"])
        if not lines:
            continue
        head = f"Sheet: {sheet['name']}" + (" (hidden)" if sheet["hidden"] else "")
        blocks.append("\n".join([head] + lines))
    return "\n\n".join(blocks)


def csv_text(path: str) -> str:
    return "\n".join(render_rows(read_csv(path)))


def spreadsheet_text(path: str) -> str:
    """The document text of a .xlsx or .csv file (see the module note)."""
    ext = os.path.splitext(str(path).lower())[1]
    if ext == XLSX_EXTENSION:
        return xlsx_text(path)
    if ext == CSV_EXTENSION:
        return csv_text(path)
    raise SpreadsheetError(f"not a spreadsheet extension: {ext!r}")
