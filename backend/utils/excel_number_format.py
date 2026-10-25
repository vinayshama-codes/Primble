"""Excel number formats: a cell's stored value as the sheet shows it.

WHY (21 Oct 2026, 25sepChanges.md Z31-X). Two readers turn a workbook cell into
text: the schedule tables' import (frontend/src/utils/scheduleImport.js) and the
Excel-as-document reader (utils/spreadsheet_text.py). Both read only the FIRST
section of a cell's number format and knew only dates, percents and zero-padded
digits. A conditional ZIP format ([<=99999]00000;00000-0000) turned 85401234
into "85401234" where Excel shows 08540-1234; a year-only "yyyy" or month-only
"mmmm" date became a whole date where the sheet shows "2020" / "March"; every
currency, accounting, phone, fraction or scientific cell printed the bare
stored number.

ONE RENDERER, WRITTEN TWICE. This module and frontend/src/utils/
excelNumberFormat.js are the same algorithm, function for function. One shared
file of test vectors (tests/fixtures/excel_number_format_vectors.json: format
code, stored value, date system, expected text, each derived from Excel's
documented behaviour) is replayed through both by
tests/test_build22_excel-formats.py, so the two readers cannot disagree.

WHAT IT RENDERS (ECMA-376 Part 1, 18.8.30 / 18.8.31, and Excel's display):
  * built-in ids 0-49 and the locale ids Excel maps onto them; an unknown id is
    General. A <numFmt> in the file always wins (the readers decide that).
  * General as Excel shows it in a cell: at most 11 characters (the minus sign
    not counted); 12 or more integer digits, and tiny numbers, in scientific
    form (1.23457E+11, 1E-20); never binary noise (0.30000000000000004 -> 0.3).
    The two READERS pass keep_digits (Z31-X review): where that General text
    is another number than the cell stores, they print every stored digit
    instead (123456789012, 123456789.12) - extraction and the tables need the
    claim number the sheet holds, not its rounding (`full_number_text`).
  * up to four sections (positive; negative; zero; text) and conditional ones
    ([<=99999], [>=1000], [<>5] ...). A single numeric section puts "-" in
    front of a negative number it shows; the second section, and a first
    section with a condition, show the number without a sign (the section
    prints its own); the third section shows its value as it is.
  * colours ([Red], [Color10]) and locale / calendar / DBNum tags ([$-409],
    [$-F800], [DBNum1]) show nothing; a currency tag shows its symbol
    ([$$-409] -> $, [$EUR] -> EUR, [$CHF-100C] -> CHF).
  * literals: quoted text, \\x, every other character as typed, _x (a space,
    the width of x), *x (a fill: nothing), @ (the text itself).
  * numbers: the 0 # ? placeholders, the decimal point, the thousands
    separator, scaling by trailing commas, percent, scientific E+ E- e+ e-
    (an exponent that is a multiple of the integer digits: ##0.0E+0 is
    engineering notation), fractions (# ?/?, # ??/??, ???/???, # ?/8, ##/100 -
    the closest fraction the denominator digits allow; a written denominator
    is kept, never reduced).
  * dates and times: y yy yyyy, m mm mmm mmmm mmmmm, d dd ddd dddd, h hh,
    m / mm as minutes right after an hour or right before a second, s ss,
    fractional seconds .0 .00 .000, AM/PM and A/P, elapsed [h] [m] [s], and e
    (year) / b (Buddhist year) beside other date parts. The 1900 system counts
    Excel's phantom 02/29/1900 (serial 60); the 1904 system starts at
    01/01/1904. Weekdays follow Excel's own count (serial 1 is a Sunday).

TODAY'S RULE FOR FULL DATES STAYS (scheduleImport.js / spreadsheet_text.py, 21
Oct 2026): a section that shows a day of the month, a month AND a year prints
MM/DD/YYYY - the schedule tables validate MM/DD/YYYY - followed by the time it
shows, if any ("03/14/2025 1:30 PM"). Every other format prints as the sheet
shows it: "2020", "Mar-20", "1:30 PM", "08540-1234", "(555) 123-4567",
"123-45-6789", "12.5%", " $1,234.50 ", " $(1,234.00)", "1.23E+05", "1 1/4".

NEVER A MADE-UP VALUE, NEVER AN EXCEPTION. A value no format can show (a
negative date or time, the phantom 02/29/1900 or 01/00/1900 in a format that
shows a date, a day past 12/31/9999) prints as General. A malformed code (more
than four sections, an unclosed quote or bracket, digit placeholders, an
exponent, General or @ inside a date section) is General for numbers and leaves
text as it is.

ROUNDING IS EXCEL'S: on the value's 15 significant digits (Excel's precision),
half away from zero, in exact decimal arithmetic (Python ints here, BigInt in
the browser) - so 2.675 shows 2.68, 12345678901234567 in "0" shows
12345678901234600, and both languages produce the same digits. The spaces a
format pads with (_x, ?) are part of the text; the readers trim a cell's outer
whitespace afterwards.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# Built-in formats
# ══════════════════════════════════════════════════════════════════════════════

# ECMA-376 18.8.30, as en-US Excel shows them. 14 and 22 carry a four-digit year
# (the standard prints "mm-dd-yy"; Excel shows m/d/yyyy). 47 is Excel's
# "mm:ss.0" (the standard misprints it "mmss.0"). 41-44 (accounting) and 63-66
# (currency) are Excel's en-US built-ins for those locale-dependent ids.
BUILTIN_FORMATS: Dict[int, str] = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
    12: "# ?/?", 13: "# ??/??", 14: "m/d/yyyy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yyyy h:mm", 37: "#,##0 ;(#,##0)",
    38: "#,##0 ;[Red](#,##0)", 39: "#,##0.00;(#,##0.00)", 40: "#,##0.00;[Red](#,##0.00)",
    41: '_(* #,##0_);_(* \\(#,##0\\);_(* "-"_);_(@_)',
    42: '_("$"* #,##0_);_("$"* \\(#,##0\\);_("$"* "-"_);_(@_)',
    43: '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)',
    44: '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)',
    45: "mm:ss", 46: "[h]:mm:ss", 47: "mm:ss.0", 48: "##0.0E+0", 49: "@",
    63: '"$"#,##0_);\\("$"#,##0\\)', 64: '"$"#,##0_);[Red]\\("$"#,##0\\)',
    65: '"$"#,##0.00_);\\("$"#,##0.00\\)', 66: '"$"#,##0.00_);[Red]\\("$"#,##0.00\\)',
}
# The locale ids (Asian and Thai workbooks) as en-US Excel shows them: 27-31 and
# 50-58 as m/d/yyyy (Brent's claims sheet, written by WPS Sheets, dates every
# cell with 58), 71-81 as their Western twins (the map SheetJS records from
# testing Excel 2019). An id in neither table shows as General.
BUILTIN_FORMAT_ALIASES: Dict[int, int] = {
    5: 37, 6: 38, 7: 39, 8: 40, 23: 0, 24: 0, 25: 0, 26: 0, 27: 14, 28: 14, 29: 14, 30: 14, 31: 14,
    50: 14, 51: 14, 52: 14, 53: 14, 54: 14, 55: 14, 56: 14, 57: 14, 58: 14, 59: 1, 60: 2, 61: 3, 62: 4,
    67: 9, 68: 10, 69: 12, 70: 13, 71: 14, 72: 14, 73: 15, 74: 16, 75: 17, 76: 20, 77: 21, 78: 22,
    79: 45, 80: 46, 81: 47, 82: 0,
}


_ID_RE = re.compile(r"^[ \t]*[+-]?[0-9]+[ \t]*$")


def builtin_format_code(fmt_id) -> str:
    """The format code of a built-in number format id ("General" when unknown)."""
    if isinstance(fmt_id, bool):
        return "General"
    if isinstance(fmt_id, int):
        n = fmt_id
    elif isinstance(fmt_id, float) and fmt_id.is_integer():
        n = int(fmt_id)
    elif isinstance(fmt_id, str) and _ID_RE.match(fmt_id):
        n = int(fmt_id)
    else:
        return "General"
    if n in BUILTIN_FORMATS:
        return BUILTIN_FORMATS[n]
    if n in BUILTIN_FORMAT_ALIASES:
        return BUILTIN_FORMATS[BUILTIN_FORMAT_ALIASES[n]]
    return "General"


# ══════════════════════════════════════════════════════════════════════════════
# Exact decimal arithmetic - a value is (D, X): the integer D times 10**X
# ══════════════════════════════════════════════════════════════════════════════

def _ndigits(d: int) -> int:
    return len(str(d))


def _shortest(a: float) -> Tuple[int, int]:
    """a (> 0, finite) as (D, X) from its shortest round-trip digits (repr here,
    String() in the browser: the same digits), D without trailing zeros."""
    mant, _sep, exp = repr(a).partition("e")
    x = int(exp) if exp else 0
    if "." in mant:
        whole, frac = mant.split(".", 1)
        digits, x = whole + frac, x - len(frac)
    else:
        digits = mant
    digits = digits.lstrip("0")
    if not digits:
        return 0, 0
    core = digits.rstrip("0")
    return int(core), x + len(digits) - len(core)


def _round_sig(d: int, x: int, p: int) -> Tuple[int, int]:
    """(d, x) rounded half away from zero to p significant digits, trailing
    zeros dropped."""
    n = _ndigits(d)
    if d and n > p:
        q = 10 ** (n - p)
        d, x = (2 * d + q) // (2 * q), x + n - p
        if _ndigits(d) > p:
            d, x = d // 10, x + 1
    while d and d % 10 == 0:
        d, x = d // 10, x + 1
    return d, x


def _sig15(a: float) -> Tuple[int, int]:
    """a (>= 0) on Excel's 15 significant digits."""
    if a == 0:
        return 0, 0
    d, x = _shortest(a)
    return _round_sig(d, x, 15)


def _scaled(d: int, x: int, k: int) -> int:
    """d * 10**x * 10**k rounded half away from zero to an integer: the value
    with k decimals, as one integer."""
    s = x + k
    if s >= 0:
        return d * 10 ** s
    q = 10 ** (-s)
    return (2 * d + q) // (2 * q)


# ══════════════════════════════════════════════════════════════════════════════
# General
# ══════════════════════════════════════════════════════════════════════════════

def _finite(v) -> Optional[float]:
    """v as a finite float, or None (a bool, text, an infinity, NaN, or an
    integer too large for a float is not a number to show)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        v = float(v)
    except OverflowError:
        return None
    return v if math.isfinite(v) else None


def _fixed(d: int, x: int, k: int) -> str:
    """The value with at most k decimals, trailing zeros (and point) dropped."""
    n = _scaled(d, x, k)
    if k <= 0:
        return str(n)
    s = str(n).rjust(k + 1, "0")
    whole, frac = s[:-k], s[-k:].rstrip("0")
    return whole + ("." + frac if frac else "")


def _expo(d: int, x: int, p: int) -> str:
    """Scientific with at most p significant digits: 1.23457E+11, 1E-20."""
    d, x = _round_sig(d, x, p)
    m = str(d)
    e = len(m) - 1 + x
    mant = m[0] + ("." + m[1:] if len(m) > 1 else "")
    return mant + "E" + ("-" if e < 0 else "+") + str(abs(e)).rjust(2, "0")


def general_text(v: float) -> str:
    """A number as Excel's General format shows it in a cell: at most 11
    characters (a minus sign not counted), fixed while that keeps the value,
    otherwise scientific with 6 significant digits."""
    v = _finite(v)
    if v is None:
        return ""
    if v == 0:
        return "0"
    if v.is_integer() and -1e11 < v < 1e11:
        return str(int(v))                       # fits in 11 digits: the integer itself (fast path)
    neg = v < 0
    d, x = _sig15(-v if neg else v)
    e = _ndigits(d) - 1 + x                     # the power of ten of the first digit
    if -4 <= e <= -1:
        o = _fixed(d, x, 9)
    elif -9 <= e <= 9:
        o = _fixed(d, x, 12)
        if len(o) > 11:
            o = _fixed(d, x, 9 - e) if e >= 0 else _expo(d, x, 6)
    elif e == 10:
        o = _fixed(d, x, 0)
        if len(o) > 11:
            o = _expo(d, x, 6)
    else:
        o = _expo(d, x, 6)
    return ("-" if neg else "") + o


def full_number_text(v, shift: int = 0) -> str:
    """v on its 15 significant digits - every digit Excel stores, the reading
    of its formula bar - times 10**shift: plain decimal while the leading digit
    sits at 10**-9 .. 10**14 (123456789012, 123456789.12, 0.000012345678901),
    scientific with every digit beyond (1.23456789012346E+18). Nothing is
    rounded away and no digit is invented. "" for a value that is no number."""
    v = _finite(v)
    if v is None:
        return ""
    if v == 0:
        return "0"
    neg = v < 0
    d, x = _sig15(-v if neg else v)
    x += int(shift)
    e = _ndigits(d) - 1 + x
    o = _fixed(d, x, max(0, -x)) if -9 <= e <= 14 else _expo(d, x, 15)
    return ("-" if neg else "") + o


def _general_digits(v: float) -> str:
    """General for the READERS (Z31-X review, 21 Oct 2026): Excel's cell text,
    unless that text is another number than the cell stores - a 12- to
    15-digit claim / policy / account number shown 1.23457E+11, a decimal cut
    at 11 characters (123456789.12 shown 123456789.1). Then every stored digit:
    two claim numbers must never read as one, and extraction must see the
    number the sheet holds (the old reader printed it)."""
    shown = general_text(v)
    if v.is_integer() and -1e11 < v < 1e11:
        return shown                                     # fits in 11 digits: nothing to lose (fast path)
    full = full_number_text(v)
    return shown if float(shown) == float(full) else full


# ══════════════════════════════════════════════════════════════════════════════
# Parsing a format code
# ══════════════════════════════════════════════════════════════════════════════
# A token is a tuple (kind, value, extra, raw):
#   ("lit", text)          shown as is            ("ph", "0" | "#" | "?")
#   ("dot",)  ("comma",)  ("pct",)  ("at",)  ("gen",)
#   ("exp", "E" | "e", "+" | "-")                 ("slash", fixed denominator digits or "")
#   ("dt", unit, run)  unit y m d h s e b, and M once resolved to minutes
#   ("ampm", am text, pm text)    ("el", h | m | s, run)  elapsed [h] [mm] [ss]
#   ("fs", digits)  fractional seconds (.0 .00 .000)
# `raw` is the token's own source text (a text section prints it).

_COND_RE = re.compile(r"^ *(<=|>=|<>|=<|=>|<|>|=) *([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?) *$")
# No real number format comes near 1,024 characters; a longer code is malformed
# (it also bounds the arithmetic a crafted run of % or commas could ask for).
_MAX_CODE_LENGTH = 1024
_ELAPSED_RE = re.compile(r"^(?:h+|m+|s+)$", re.I)
_DATE_LETTERS = "ymdhseb"
_EMPTY_FILL = {"0": "0", "#": "", "?": " "}
_DEN_FILL = {"0": " ", "#": "", "?": " "}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")
_DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_SERIAL_EPSILON = 1e-9
_LAST_SERIAL_1900 = 2958465          # 12/31/9999
_LAST_SERIAL_1904 = 2957003          # 12/31/9999 in the 1904 system


def _split_sections(code: str) -> List[str]:
    """positive;negative;zero;text - split outside quotes, escapes, the
    character after _ or *, and [...]."""
    out: List[str] = []
    cur: List[str] = []
    i, n, quoted = 0, len(code), False
    while i < n:
        ch = code[i]
        if quoted:
            cur.append(ch)
            quoted = ch != '"'
            i += 1
        elif ch == '"':
            quoted = True
            cur.append(ch)
            i += 1
        elif ch in "\\_*":
            cur.append(code[i:i + 2])
            i += 2
        elif ch == "[":
            j = code.find("]", i + 1)
            if j == -1:
                cur.append(code[i:])
                break
            cur.append(code[i:j + 1])
            i = j + 1
        elif ch == ";":
            out.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    out.append("".join(cur))
    return out


def _tokenize(s: str):
    """One section as (tokens, condition, malformed)."""
    toks: List[tuple] = []
    cond = None
    bad = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        low = ch.lower()
        if ch == '"':
            j = s.find('"', i + 1)
            if j == -1:
                toks.append(("lit", s[i + 1:], None, s[i:]))
                bad = True
                break
            toks.append(("lit", s[i + 1:j], None, s[i:j + 1]))
            i = j + 1
        elif ch == "\\":
            toks.append(("lit", s[i + 1:i + 2], None, s[i:i + 2]))
            i += 2
        elif ch == "_":
            toks.append(("lit", " " if i + 1 < n else "", None, s[i:i + 2]))
            i += 2
        elif ch == "*":
            toks.append(("lit", "", None, s[i:i + 2]))
            i += 2
        elif ch == "[":
            j = s.find("]", i + 1)
            if j == -1:
                toks.append(("lit", s[i:], None, s[i:]))
                bad = True
                break
            inner, raw = s[i + 1:j], s[i:j + 1]
            i = j + 1
            if _ELAPSED_RE.match(inner):
                toks.append(("el", inner[0].lower(), len(inner), raw))
                continue
            m = _COND_RE.match(inner)
            if m:
                if cond is None:
                    op = {"=<": "<=", "=>": ">="}.get(m.group(1), m.group(1))
                    cond = (op, float(m.group(2)))
                continue
            if inner.startswith("$"):
                symbol = inner[1:].split("-", 1)[0]
                if symbol:
                    toks.append(("lit", symbol, None, raw))
            # a colour, [ColorN], a locale / calendar / DBNum tag: shows nothing
        elif s[i:i + 5].lower() == "am/pm":
            toks.append(("ampm", "AM", "PM", s[i:i + 5]))
            i += 5
        elif s[i:i + 3].lower() == "a/p":
            toks.append(("ampm", s[i], s[i + 2], s[i:i + 3]))
            i += 3
        elif s[i:i + 5] == "上午/下午":         # 上午/下午
            toks.append(("ampm", "上午", "下午", s[i:i + 5]))
            i += 5
        elif s[i:i + 7].lower() == "general":
            toks.append(("gen", None, None, s[i:i + 7]))
            i += 7
        elif ch in "Ee" and i + 1 < n and s[i + 1] in "+-":
            toks.append(("exp", ch, s[i + 1], s[i:i + 2]))
            i += 2
        elif len(low) == 1 and low in _DATE_LETTERS:
            j = i
            while j < n and s[j].lower() == low:
                j += 1
            toks.append(("dt", low, j - i, s[i:j]))
            i = j
        elif ch in "0#?":
            toks.append(("ph", ch, None, ch))
            i += 1
        elif ch == ".":
            toks.append(("dot", None, None, ch))
            i += 1
        elif ch == ",":
            toks.append(("comma", None, None, ch))
            i += 1
        elif ch == "%":
            toks.append(("pct", None, None, ch))
            i += 1
        elif ch == "@":
            toks.append(("at", None, None, ch))
            i += 1
        elif ch == "/":
            j = i + 1
            if j < n and s[j] in "123456789":
                while j < n and s[j] in "0123456789":
                    j += 1
            toks.append(("slash", s[i + 1:j], None, s[i:j]))
            i = j
        else:
            toks.append(("lit", ch, None, ch))
            i += 1
    return toks, cond, bad


def _as_lit(t: tuple) -> tuple:
    return ("lit", t[3], None, t[3])


class _Section:
    """One compiled section: its condition, its tokens, and how it shows a value."""

    __slots__ = ("cond", "toks", "kind", "bad", "has_at", "mode", "roles", "grouping", "scale", "pct",
                 "int_ph", "frac_ph", "num_ph", "den_ph", "den_fixed", "exp_ph", "full_date",
                 "shows_date", "has_time", "time_span", "fs_max", "ampm")

    def __init__(self, text: str):
        toks, self.cond, self.bad = _tokenize(text)
        self.has_at = any(t[0] == "at" for t in toks)
        core = any(t[0] in ("ampm", "el") or (t[0] == "dt" and t[1] in "ymdhs") for t in toks)
        if not core:
            # e (year) and b (Buddhist year) are date parts only beside others;
            # alone they are letters ("0 lb" is a number with a unit).
            toks = [_as_lit(t) if t[0] == "dt" else t for t in toks]
        self.toks = toks
        self.roles: List[tuple] = []
        self.grouping, self.scale, self.pct = False, 0, 0
        self.int_ph: List[str] = []
        self.frac_ph: List[str] = []
        self.num_ph: List[str] = []
        self.den_ph: List[str] = []
        self.exp_ph: List[str] = []
        self.den_fixed = 0
        self.mode = "dec"
        self.full_date = self.shows_date = self.has_time = self.ampm = False
        self.time_span = (0, -1)
        self.fs_max = 0
        if core:
            self.kind = "date"
            self._compile_date()
        elif any(t[0] == "gen" for t in toks):
            self.kind = "general"
        elif self.has_at:
            self.kind = "text"
        else:
            self.kind = "number"
            self._compile_number()

    # ── dates and times ──────────────────────────────────────────────────────
    def _compile_date(self) -> None:
        toks = list(self.toks)
        # "m" / "mm" right after an hour is minutes; so is one right before a
        # second. Longer runs are always the month.
        prev = None
        for k, t in enumerate(toks):
            if t[0] == "dt":
                if t[1] == "m" and t[2] <= 2 and prev == "h":
                    toks[k] = ("dt", "M", t[2], t[3])
                prev = toks[k][1]
            elif t[0] == "el":
                prev = t[1]
            elif t[0] == "ampm":
                prev = "a"
        nxt = None
        for k in range(len(toks) - 1, -1, -1):
            t = toks[k]
            if t[0] == "dt":
                if t[1] == "m":
                    if t[2] <= 2 and nxt == "s":
                        toks[k] = ("dt", "M", t[2], t[3])
                else:
                    nxt = t[1]
            elif t[0] == "el":
                nxt = t[1]
        # fractional seconds: a point right after s / ss / [ss], then zeros
        out: List[tuple] = []
        k = 0
        while k < len(toks):
            t = toks[k]
            if (t[0] == "dot" and out and ((out[-1][0] == "dt" and out[-1][1] == "s")
                                           or (out[-1][0] == "el" and out[-1][1] == "s"))):
                j = k + 1
                while j < len(toks) and toks[j][0] == "ph" and toks[j][1] == "0":
                    j += 1
                if j > k + 1:
                    out.append(("fs", j - k - 1, None, "".join(x[3] for x in toks[k:j])))
                    k = j
                    continue
            out.append(t)
            k += 1
        toks = []
        for t in out:
            if t[0] in ("ph", "exp", "gen", "at"):
                self.bad = True                      # a number placeholder inside a date
                toks.append(_as_lit(t))
            elif t[0] in ("dot", "comma", "pct", "slash"):
                toks.append(_as_lit(t))
            else:
                toks.append(t)
        self.toks = toks
        units = [t[1] for t in toks if t[0] == "dt"]
        self.ampm = any(t[0] == "ampm" for t in toks)
        self.fs_max = max([t[1] for t in toks if t[0] == "fs"] or [0])
        self.shows_date = any(u in "ymdeb" for u in units)
        day_of_month = any(t[0] == "dt" and t[1] == "d" and t[2] <= 2 for t in toks)
        self.full_date = day_of_month and "m" in units and any(u in "yeb" for u in units)
        timed = [k for k, t in enumerate(toks)
                 if t[0] in ("ampm", "el", "fs") or (t[0] == "dt" and t[1] in "hMs")]
        self.has_time = bool(timed)
        if timed:
            self.time_span = (timed[0], timed[-1])

    # ── numbers ──────────────────────────────────────────────────────────────
    def _compile_number(self) -> None:
        toks = self.toks
        n = len(toks)
        roles: List[Optional[tuple]] = [None] * n
        exp_at = next((k for k, t in enumerate(toks) if t[0] == "exp"), -1)
        slash_at = -1
        if exp_at == -1:
            for k, t in enumerate(toks):
                if (t[0] == "slash" and k > 0 and toks[k - 1][0] == "ph"
                        and (t[1] or (k + 1 < n and toks[k + 1][0] == "ph"))):
                    slash_at = k
                    break
        self.pct = sum(1 for t in toks if t[0] == "pct")
        for k, t in enumerate(toks):
            if t[0] == "pct":
                roles[k] = ("lit", "%")
            elif t[0] == "lit":
                roles[k] = ("lit", t[1])
            elif t[0] in ("slash", "exp", "dot", "comma", "ph"):
                pass                                  # decided below
            else:
                roles[k] = ("lit", t[3])
        if exp_at != -1:
            self.mode = "sci"
            dot_at = next((k for k, t in enumerate(toks) if t[0] == "dot" and k < exp_at), -1)
            for k, t in enumerate(toks):
                if roles[k] is not None:
                    continue
                if t[0] == "ph":
                    if k > exp_at:
                        roles[k] = ("eph",)
                        self.exp_ph.append(t[1])
                    elif dot_at != -1 and k > dot_at:
                        roles[k] = ("frac", len(self.frac_ph))
                        self.frac_ph.append(t[1])
                    else:
                        roles[k] = ("int", len(self.int_ph))
                        self.int_ph.append(t[1])
                elif k == exp_at:
                    roles[k] = ("exp", t[1], t[2])
                elif k == dot_at:
                    roles[k] = ("dot",)
                elif t[0] == "comma":
                    roles[k] = ("skip",)
                else:
                    roles[k] = ("lit", t[3])
        elif slash_at != -1:
            self.mode = "frac"
            start = slash_at - 1
            while start > 0 and toks[start - 1][0] == "ph":
                start -= 1
            fixed = toks[slash_at][1]
            den_end = slash_at
            if not fixed:
                while den_end + 1 < n and toks[den_end + 1][0] == "ph":
                    den_end += 1
            else:
                self.den_fixed = int(fixed)
            last_int = max([k for k in range(start) if toks[k][0] == "ph"] or [-1])
            for k, t in enumerate(toks):
                if roles[k] is not None:
                    continue
                if t[0] == "ph":
                    if k < start:
                        roles[k] = ("int", len(self.int_ph))
                        self.int_ph.append(t[1])
                    elif k < slash_at:
                        roles[k] = ("num", len(self.num_ph))
                        self.num_ph.append(t[1])
                    elif k <= den_end:
                        roles[k] = ("den", len(self.den_ph))
                        self.den_ph.append(t[1])
                    else:
                        roles[k] = ("lit", t[3])
                elif k == slash_at:
                    roles[k] = ("slash",)
                elif t[0] == "comma" and k < last_int and any(toks[q][0] == "ph" for q in range(k)):
                    roles[k] = ("skip",)
                    self.grouping = True
                else:
                    roles[k] = ("lit", t[3])
        else:
            self.mode = "dec"
            dot_at = next((k for k, t in enumerate(toks) if t[0] == "dot"), -1)
            end_int = dot_at if dot_at != -1 else n
            int_idx = [k for k in range(end_int) if toks[k][0] == "ph"]
            for k, t in enumerate(toks):
                if roles[k] is not None:
                    continue
                if t[0] == "ph":
                    if k < end_int:
                        roles[k] = ("int", len(self.int_ph))
                        self.int_ph.append(t[1])
                    else:
                        roles[k] = ("frac", len(self.frac_ph))
                        self.frac_ph.append(t[1])
                elif k == dot_at:
                    roles[k] = ("dot",)
                elif t[0] == "comma":
                    q = k - 1
                    while q >= 0 and toks[q][0] == "comma":
                        q -= 1
                    after_ph = q >= 0 and toks[q][0] == "ph"
                    if k < end_int and int_idx and int_idx[0] < k < int_idx[-1]:
                        roles[k] = ("skip",)
                        self.grouping = True        # a comma between digits: the thousands separator
                    elif after_ph:
                        roles[k] = ("skip",)
                        self.scale += 1             # a comma after the digits: / 1,000
                    else:
                        roles[k] = ("lit", ",")
                else:
                    roles[k] = ("lit", t[3])        # a second point, a lone slash
        self.roles = roles

    @property
    def shows_number(self) -> bool:
        return bool(self.int_ph or self.frac_ph or self.num_ph or self.den_ph or self.den_fixed)


class _Format:
    __slots__ = ("bad", "sections", "numeric", "text")

    def __init__(self, code: str):
        code = code or "General"                 # a style with an empty formatCode shows General
        parts = _split_sections(code[:_MAX_CODE_LENGTH + 1])
        self.sections = [_Section(p) for p in parts]
        self.bad = (len(code) > _MAX_CODE_LENGTH or len(parts) > 4
                    or any(s.bad for s in self.sections))
        last = self.sections[-1]
        if len(self.sections) == 4:
            self.text, self.numeric = last, self.sections[:3]
        elif last.has_at:
            self.text, self.numeric = last, self.sections[:-1]
        else:
            self.text, self.numeric = None, self.sections


@lru_cache(maxsize=4096)
def _compile(code: str) -> _Format:
    return _Format(code)


# ══════════════════════════════════════════════════════════════════════════════
# Rendering
# ══════════════════════════════════════════════════════════════════════════════

def _test(cond, v: float) -> bool:
    op, t = cond
    return {"<": v < t, ">": v > t, "=": v == t, "<=": v <= t, ">=": v >= t, "<>": v != t}[op]


def _pick(fmt: _Format, v: float):
    """(section, its index) for the number v, or (None, -1): positive /
    negative / zero, or the first section whose condition holds (the else is
    the section after a conditional first one, or the third)."""
    secs = fmt.numeric
    n = len(secs)
    if not n:
        return None, -1
    s0 = secs[0]
    if s0.cond is not None:
        if _test(s0.cond, v):
            return s0, 0
    elif n == 1 or (n == 2 and v >= 0) or (n >= 3 and v > 0):
        return s0, 0
    if n < 2:
        return None, -1
    s1 = secs[1]
    if s1.cond is not None:
        if _test(s1.cond, v):
            return s1, 1
    elif v < 0 or (n == 2 and s0.cond is not None):
        return s1, 1
    if n < 3:
        return None, -1
    return secs[2], 2


def _fill_int(digits: str, phs: List[str]) -> List[str]:
    """Integer digits into placeholders, right to left; the first placeholder
    takes every digit left over. An empty place shows 0, nothing (#) or a
    space (?)."""
    pieces = [""] * len(phs)
    left = len(digits)
    for j in range(len(phs) - 1, -1, -1):
        if j == 0 and left:
            pieces[0] = digits[:left]
        elif left:
            pieces[j] = digits[left - 1]
            left -= 1
        else:
            pieces[j] = _EMPTY_FILL[phs[j]]
    return pieces


def _fill_frac(digits: str, phs: List[str]) -> List[str]:
    """Decimal digits into placeholders, a trailing zero showing nothing under
    # and a space under ? (until a 0 placeholder or a non-zero digit)."""
    pieces = list(digits)
    for j in range(len(phs) - 1, -1, -1):
        if phs[j] == "0" or digits[j] != "0":
            break
        pieces[j] = _EMPTY_FILL[phs[j]]
    return pieces


def _group(text: str) -> str:
    """Thousands separators in the digits of an integer part (leading spaces
    from ? placeholders kept as they are)."""
    body = text.lstrip(" ")
    lead = text[:len(text) - len(body)]
    groups = []
    while len(body) > 3:
        groups.insert(0, body[-3:])
        body = body[:-3]
    if body:
        groups.insert(0, body)
    return lead + ",".join(groups)


def _int_pieces(sec: _Section, digits: str) -> List[str]:
    pieces = _fill_int(digits, sec.int_ph)
    if sec.grouping and pieces:
        return [_group("".join(pieces))] + [""] * (len(pieces) - 1)
    return pieces


def _render_dec(sec: _Section, a: float) -> str:
    d, x = _sig15(a)
    x += 2 * sec.pct - 3 * sec.scale
    f = len(sec.frac_ph)
    whole, frac = divmod(_scaled(d, x, f), 10 ** f)
    digits = str(whole) if whole else ""
    ipieces = _int_pieces(sec, digits)
    fpieces = _fill_frac(str(frac).rjust(f, "0"), sec.frac_ph) if f else []
    out: List[str] = []
    for r in sec.roles:
        if r[0] == "lit":
            out.append(r[1])
        elif r[0] == "int":
            out.append(ipieces[r[1]])
        elif r[0] == "frac":
            out.append(fpieces[r[1]])
        elif r[0] == "dot":
            out.append(("" if sec.int_ph else digits) + ".")
    return "".join(out)


def _render_sci(sec: _Section, a: float) -> str:
    step = len(sec.int_ph) or 1
    f = len(sec.frac_ph)
    expo = 0
    mant = 0
    if a:
        d, xd = _sig15(a)
        xd += 2 * sec.pct
        e10 = _ndigits(d) - 1 + xd
        expo = (e10 // step) * step
        mant = _scaled(d, xd - expo, f)
        if mant >= 10 ** (step + f):
            expo += step
            mant = _scaled(d, xd - expo, f)
    whole, frac = divmod(mant, 10 ** f)
    digits = str(whole) if whole else ""
    ipieces = _fill_int(digits, sec.int_ph)
    fpieces = _fill_frac(str(frac).rjust(f, "0"), sec.frac_ph) if f else []
    width = sum(1 for p in sec.exp_ph if p == "0")
    out: List[str] = []
    for r in sec.roles:
        if r[0] == "lit":
            out.append(r[1])
        elif r[0] == "int":
            out.append(ipieces[r[1]])
        elif r[0] == "frac":
            out.append(fpieces[r[1]])
        elif r[0] == "dot":
            out.append(("" if sec.int_ph else digits) + ".")
        elif r[0] == "exp":
            sign = "-" if expo < 0 else ("+" if r[2] == "+" else "")
            out.append(r[1] + sign + str(abs(expo)).rjust(width, "0"))
    return "".join(out)


def _closest_fraction(n: int, d: int, max_den: int) -> Tuple[int, int]:
    """The fraction p/q closest to n/d with q <= max_den (a tie goes to the
    convergent) - continued fractions, exactly (Fraction.limit_denominator)."""
    g = math.gcd(n, d)
    n, d = n // g, d // g
    if d <= max_den:
        return n, d
    p0, q0, p1, q1 = 0, 1, 1, 0
    nn, dd = n, d
    while True:
        a = nn // dd
        q2 = q0 + a * q1
        if q2 > max_den:
            break
        p0, q0, p1, q1 = p1, q1, p0 + a * p1, q2
        nn, dd = dd, nn - a * dd
    k = (max_den - q0) // q1
    if 2 * dd * (q0 + k * q1) <= d:
        return p1, q1
    return p0 + k * p1, q0 + k * q1


def _render_frac(sec: _Section, a: float) -> str:
    d, x = _sig15(a)
    x += 2 * sec.pct
    num, den = (d * 10 ** x, 1) if x >= 0 else (d, 10 ** (-x))
    mixed = bool(sec.int_ph)
    whole, rem = divmod(num, den) if mixed else (0, num)
    if sec.den_fixed:
        q = sec.den_fixed
        p = (2 * rem * q + den) // (2 * den)
    else:
        p, q = _closest_fraction(rem, den, 10 ** min(len(sec.den_ph), 7) - 1)
    if mixed and q and p >= q:
        whole, p = whole + p // q, p % q
    blank = mixed and p == 0
    digits = str(whole) if whole else ("0" if blank else "")
    ipieces = _int_pieces(sec, digits)
    npieces = _fill_int(str(p), sec.num_ph)
    qd = str(q)
    dpieces = [(qd[j:] if j == len(sec.den_ph) - 1 else qd[j]) if j < len(qd) else _DEN_FILL[ph]
               for j, ph in enumerate(sec.den_ph)]
    width = len(sec.num_ph) + 1 + (len(sec.den_ph) if not sec.den_fixed else len(str(sec.den_fixed)))
    out: List[str] = []
    for r in sec.roles:
        if r[0] == "lit":
            out.append(r[1])
        elif r[0] == "int":
            out.append(ipieces[r[1]])
        elif r[0] == "num":
            out.append(" " * width if blank and r[1] == 0 else ("" if blank else npieces[r[1]]))
        elif r[0] == "slash":
            out.append("" if blank else "/" + (str(sec.den_fixed) if sec.den_fixed else ""))
        elif r[0] == "den":
            out.append("" if blank else dpieces[r[1]])
    return "".join(out)


def _serial_ymd(days: int, date1904: bool) -> Optional[Tuple[int, int, int]]:
    """A day count as (year, month, day); None for no real calendar day."""
    if days < 0:
        return None
    if date1904:
        if days > _LAST_SERIAL_1904:
            return None
        d = date(1904, 1, 1) + timedelta(days=days)
    else:
        if days in (0, 60) or days > _LAST_SERIAL_1900:
            return None
        d = (date(1899, 12, 31) if days < 60 else date(1899, 12, 30)) + timedelta(days=days)
    return d.year, d.month, d.day


def _render_date(sec: _Section, v: float, date1904: bool) -> Optional[str]:
    if v < 0:
        return None
    if sec.has_time:
        unit = 10 ** sec.fs_max
        d, x = _sig15(v)
        total = _scaled(d * 86400, x, sec.fs_max)
        days, rem = divmod(total, 86400 * unit)
        secs, sub = divmod(rem, unit)
    else:
        days, secs, sub = math.floor(v + _SERIAL_EPSILON), 0, 0
    if days > (_LAST_SERIAL_1904 if date1904 else _LAST_SERIAL_1900):
        return None
    ymd = _serial_ymd(days, date1904)
    if ymd is None and sec.shows_date:
        return None
    y, mo, dom = ymd or (0, 0, 0)
    wd = (days + (5 if date1904 else 6)) % 7
    hh, rest = divmod(secs, 3600)
    mi, ss = divmod(rest, 60)
    elapsed = days * 86400 + secs

    def part(t: tuple) -> str:
        kind = t[0]
        if kind == "lit":
            return t[1]
        if kind == "ampm":
            return t[1] if hh < 12 else t[2]
        if kind == "fs":
            return "." + str(sub).rjust(sec.fs_max, "0")[:t[1]]
        if kind == "el":
            value = elapsed // 3600 if t[1] == "h" else elapsed // 60 if t[1] == "m" else elapsed
            return str(value).rjust(t[2], "0")
        unit_, run = t[1], t[2]
        if unit_ == "y":
            return str(y % 100).rjust(2, "0") if run <= 2 else str(y)
        if unit_ == "e":
            return str(y)
        if unit_ == "b":
            return str((y + 543) % 100).rjust(2, "0") if run <= 2 else str(y + 543)
        if unit_ == "m":
            if run <= 2:
                return str(mo).rjust(run, "0")
            if run == 3:
                return _MONTHS[mo - 1][:3]
            return _MONTHS[mo - 1][0] if run == 5 else _MONTHS[mo - 1]
        if unit_ == "d":
            if run <= 2:
                return str(dom).rjust(run, "0")
            return _DAYS[wd][:3] if run == 3 else _DAYS[wd]
        if unit_ == "h":
            hour = (hh % 12 or 12) if sec.ampm else hh
            return str(hour).rjust(min(run, 2), "0")
        if unit_ == "M":
            return str(mi).rjust(min(run, 2), "0")
        return str(ss).rjust(min(run, 2), "0")       # s

    if sec.full_date:
        text = f"{mo:02d}/{dom:02d}/{y}"
        if sec.has_time:
            a, b = sec.time_span
            text += " " + "".join(part(t) for t in sec.toks[a:b + 1])
        return text
    return "".join(part(t) for t in sec.toks)


def _render(fmt: _Format, v: float, date1904: bool, keep_digits: bool = False) -> str:
    general = _general_digits if keep_digits else general_text
    if fmt.bad:
        return general(v)
    sec, idx = _pick(fmt, v)
    if sec is None:
        return general(v)
    a = abs(v) if idx == 1 or (idx == 0 and sec.cond is not None) else v
    if sec.kind == "date":
        text = _render_date(sec, a, date1904)
        return general(v) if text is None else text
    neg = a < 0
    a = abs(a)
    if sec.kind in ("general", "text"):
        body = "".join(general(a) if t[0] in ("gen", "at") else t[1] if t[0] == "lit" else t[3]
                       for t in sec.toks)
        return ("-" if neg else "") + body
    if sec.mode == "sci":
        body = _render_sci(sec, a)
    elif sec.mode == "frac":
        body = _render_frac(sec, a)
    else:
        body = _render_dec(sec, a)
    return ("-" if neg and sec.shows_number else "") + body


# ══════════════════════════════════════════════════════════════════════════════
# The doors the readers use
# ══════════════════════════════════════════════════════════════════════════════

_NUMBER_RE = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_ASCII_SPACE = " \t\n\r\f\v"


def _code_of(fmt) -> str:
    if isinstance(fmt, dict):
        fmt = fmt.get("code", "General")
    return "General" if fmt is None else str(fmt)


def format_number(v: float, code="General", date1904: bool = False, keep_digits: bool = False) -> str:
    """A number as the format code shows it ("" for a value that is not a finite number).
    keep_digits (the two readers pass it): wherever the number shows in General,
    a General text that is another number than the stored one is replaced by
    every stored digit (`_general_digits`); every other part as the sheet shows it."""
    v = _finite(v)
    if v is None:
        return ""
    try:
        return _render(_compile(_code_of(code)), v, bool(date1904), bool(keep_digits))
    except Exception:                                    # noqa: BLE001 - never raise on a cell
        return _general_digits(v) if keep_digits else general_text(v)


def format_cell_number(raw, fmt="General", date1904: bool = False, keep_digits: bool = False) -> str:
    """A numeric cell's stored text (its <v>) as the format shows it. Text that
    is not a plain decimal number stays exactly as written."""
    text = "" if raw is None else str(raw).strip(_ASCII_SPACE)
    if not text:
        return ""
    if not _NUMBER_RE.match(text):
        return text
    v = float(text)
    if not math.isfinite(v):
        return text
    return format_number(v, _code_of(fmt), date1904, keep_digits)


def format_text(text, code="General") -> str:
    """A text cell as the format's text section shows it (@ is the text); a
    format with no text section, or a malformed one, leaves the text alone."""
    s = "" if text is None else str(text)
    try:
        fmt = _compile(_code_of(code))
    except Exception:                                    # noqa: BLE001
        return s
    if fmt.bad or fmt.text is None:
        return s
    return "".join(s if t[0] == "at" else t[1] if t[0] == "lit" else t[3] for t in fmt.text.toks)


_ISO_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(\.[0-9]+)?)?)?"
                     r"(?:Z|[+-][0-9]{2}:?[0-9]{2})?$")
_ISO_LOOSE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ][0-9:.]+(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?$")


def _iso_date_text(text: str) -> str:
    """An ISO date cell as MM/DD/YYYY (21 Oct 2026 rule); anything else as written."""
    m = _ISO_LOOSE_RE.match(text)
    if not m or not (1 <= int(m.group(2)) <= 12) or not (1 <= int(m.group(3)) <= 31):
        return text
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"


def iso_to_serial(text: str, date1904: bool = False) -> Optional[float]:
    """A strict-OOXML ISO date cell (t="d") as the serial Excel would store."""
    m = _ISO_RE.match(str(text or "").strip(_ASCII_SPACE))
    if not m:
        return None
    try:
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    hh, mi, ss = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
    if hh > 23 or mi > 59 or ss > 59:
        return None
    if date1904:
        serial = (day - date(1904, 1, 1)).days
    else:
        n = (day - date(1899, 12, 30)).days
        serial = n if n >= 61 else n - 1
    if serial < 0:
        return None
    frac = float(m.group(7)) if m.group(7) else 0.0
    return serial + (hh * 3600 + mi * 60 + ss + frac) / 86400


def format_iso_date(raw, code="General", date1904: bool = False) -> str:
    """A t="d" cell: through its format when that format shows a date or a
    time; otherwise MM/DD/YYYY (the date part), as before."""
    text = "" if raw is None else str(raw).strip(_ASCII_SPACE)
    try:
        fmt = _compile(_code_of(code))
        dated = not fmt.bad and bool(fmt.numeric) and fmt.numeric[0].kind == "date"
    except Exception:                                    # noqa: BLE001
        dated = False
    if dated:
        serial = iso_to_serial(text, date1904)
        if serial is not None:
            return format_number(serial, code, date1904)
    return _iso_date_text(text)


# ══════════════════════════════════════════════════════════════════════════════
# What a format is (the 21 Oct reader's classification, kept for its callers)
# ══════════════════════════════════════════════════════════════════════════════

def number_format_kind(code) -> dict:
    """{"kind": "date" | "time" | "percent" | "zeros" | "number", "code": code},
    read from the first section the way the 21 Oct readers classified it."""
    code = _code_of(code)
    try:
        sec = _Section(_split_sections(code)[0])
    except Exception:                                    # noqa: BLE001
        return {"kind": "number", "code": code}
    toks = sec.toks
    if sec.kind == "date":
        if any(t[0] == "el" for t in toks):
            kind = "time"
        else:
            kind = "date" if sec.shows_date else "time"
    elif any(t[0] == "pct" for t in toks):
        kind = "percent"
    else:
        phs = [t for t in toks if t[0] == "ph"]
        plain = not any(t[0] in ("dot", "comma", "slash", "exp", "at", "gen") for t in toks)
        kind = "zeros" if len(phs) >= 2 and all(t[1] == "0" for t in phs) and plain else "number"
    return {"kind": kind, "code": code}


def excel_serial_to_date(serial, date1904: bool = False) -> str:
    """An Excel day count as MM/DD/YYYY, or "" when it is no real calendar day
    (scheduleImport.js's excelSerialToDate, line for line)."""
    if isinstance(serial, str):
        text = serial.strip(_ASCII_SPACE)
        n = float(text) if _NUMBER_RE.match(text) else None
    else:
        n = _finite(serial)
    if n is None or not math.isfinite(n) or n < 0:
        return ""
    ymd = _serial_ymd(math.floor(n + _SERIAL_EPSILON), bool(date1904))
    return "" if ymd is None else f"{ymd[1]:02d}/{ymd[2]:02d}/{ymd[0]}"
