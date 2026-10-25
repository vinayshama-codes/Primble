"""property_coverages.py - each premises / building's OWN coverage rows, read
off the property schedule the documents print, for ACORD 140's SUBJECT OF
INSURANCE grid (7 Oct 2026, round 5 - the owner's live run b248c194, #13).

THE DEFECT. ACORD 140 prints, per premises / building, up to five SUBJECT OF
INSURANCE rows, each with its own AMOUNT, COINS %, VALUATION, CAUSES OF LOSS,
DED, DED TYPE and FORMS AND CONDITIONS. The extraction model returns one
`building_value` and one `bpp_value` per premises row and package scalars
(`coinsurance_percentage`, `valuation_method`, `property_deductible_aop`), so
the grid was stamped as two fixed slots (Building, BPP) plus row A's package
terms, and gap fill was asked for everything else. On the Choice Electric
package that printed:
  * DED $500 on row A - the common declarations' default "DEDUCTIBLE $500.
    Exceptions: SEE SCHEDULE" - while the schedule prints "$5,000" beside every
    coverage row;
  * no PERSONAL PROPERTY-STOCK $75,000 row for building 2 (and no Business
    Income row for either building);
  * AI rows C ("BPP" $73,008) and E ("B" $421,714) copying building 1's BPP
    and building 2's building into building 1's block.

THE RULE - transcribe, never infer:
  * a property COVERAGE SCHEDULE the documents print is read deterministically
    into ordered coverage rows per premises / building, each with only the
    terms printed on THAT row (limit, coinsurance, deductible, valuation and
    options). Three layouts are read, all by structure, none by carrier name:
      - ISO-style "COVERAGE: <name>" blocks under a "Prem #: n Bldg #: m"
        heading, with a "LIMIT COINSURANCE DEDUCTIBLE" header and the values
        line under it (page furniture between options is skipped);
      - a "Prem Bldg Coverage Limit ..." table, one coverage per row;
      - "Subject of Insurance: X / Amount of Insurance: $Y" label blocks
        under a "Location n" heading, each with its own terms;
  * a coverage printed as "INCLUDED" / "NOT COVERED" has no amount of its own
    and is not a subject row (equipment breakdown extensions);
  * a section is COMPLETE only when every coverage line in it parsed; only a
    complete section may claim the rows after its last coverage as owned
    blanks (the stamper's C46 rule for this grid);
  * two documents that print DIFFERENT coverage lists for one premises decide
    nothing for it (blank over wrong - the old behaviour stands);
  * the common declarations' default deductible is recorded when the document
    itself qualifies it with exceptions ("DEDUCTIBLE $500. Exceptions: SEE
    SCHEDULE"), so the stamper never prints that default as a row's own.

Derived at merge into the private `_property_coverages` fact (documents in
hand); read by `pdf_service` at stamping (`premises_rows`). Pure; never raises.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

KEY = "_property_coverages"

# One premises block on ACORD 140 prints five subject rows (A-E, G-K).
ROWS_PER_PREMISES = 5


# ── small helpers ─────────────────────────────────────────────────────────────

def _fv(facts: Any, key: str):
    v = facts.get(key) if isinstance(facts, dict) else None
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _label_number(raw: Any) -> str:
    try:
        from services.extraction_service import _label_number as _ln
        return _ln(raw)
    except Exception:                                         # noqa: BLE001
        s = str(raw or "").strip()
        return str(int(s)) if s.isdigit() else s.upper()


def _heading_parts(line: str) -> Optional[Tuple[str, str]]:
    """(premises, building) printed numbers when the WHOLE line is a premises /
    building heading ("Prem #: 001 Bldg #: 001", "Location 2"), else None."""
    try:
        from services.extraction_service import premises_label_parts
        parts = premises_label_parts(line)
    except Exception:                                         # noqa: BLE001
        return None
    if not parts or parts.get("street") or not parts.get("premises"):
        return None
    return _label_number(parts["premises"]), _label_number(parts.get("building"))


def dollars(value: Any) -> str:
    """Whole dollars as digits ("$798,556" / "798,556.00" -> "798556"); "" when
    the value is not one plain amount."""
    s = str(value or "").strip().replace(" ", "")
    m = re.fullmatch(r"\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", s)
    return str(int(m.group(1).replace(",", ""))) if m else ""


def _money(value: str) -> str:
    d = dollars(value)
    return "${:,}".format(int(d)) if d else str(value or "").strip()


_TIME_DED_RE = re.compile(r"^(\d+)\s*(HOURS?|HRS?\.?|DAYS?)$", re.I)
_PCT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s?%$")
# The ACORD 140 / 160 DEDUCTIBLE TYPE code of a percentage deductible (the
# tooltip's "percent, dollars and number of days"). Also read by the stamper for
# a percentage that reaches a premises row by another door
# (`pdf_service._type_percentage_deductibles`).
PERCENT_DEDUCTIBLE_TYPE = "Percent"


def _deductible(raw: str) -> Tuple[str, str]:
    """(display, type) for one printed deductible token."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not s:
        return "", ""
    t = _TIME_DED_RE.match(s)
    if t:
        unit = "Days" if t.group(2).upper().startswith("D") else "Hours"
        return f"{t.group(1)} {unit}", unit
    p = _PCT_RE.match(s)
    if p:
        return f"{p.group(1)}%", PERCENT_DEDUCTIBLE_TYPE
    if dollars(s):
        return _money(s), "Dollars"
    return "", ""


def _pct(raw: str) -> str:
    m = re.match(r"^(\d{1,3})\s?(?:%|percent)$", str(raw or "").strip(), re.I)
    return f"{m.group(1)}%" if m else ""


# ── what a coverage IS ────────────────────────────────────────────────────────
# ACORD 140's own SUBJECT OF INSURANCE tooltip lists the subjects (B - Building,
# BPP - Business Personal Property, STK - Stock, BUSIN - Business Income with
# Extra Expense, ...). The label printed is the tooltip's own description, the
# same words the grid has always printed for its Building / BPP rows.
_KIND_LABELS = {
    "building": "Building",
    "bpp": "Business Personal Property",
    "stock": "Stock",
    "pp": "Personal Property",
    "potop": "Property of Others",
    "ff": "Furniture & Fixtures",
    "maceq": "Machinery, Equipment",
    "ee": "Extra Expense",
    "tib": "Tenants Improvements and Betterments",
}
_BI_LABELS = {
    (True, None, True): "Business Income with Extra Expense and Rental Value",
    (True, None, False): "Business Income with Extra Expense",
    (False, True, True): "Business Income with Rental Value without Extra Expense",
    (False, True, False): "Business Income without Extra Expense",
}


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9&%$/]+", " ", str(text or "").upper())).strip()


def subject_kind(text: Any) -> Optional[str]:
    """The canonical family of a subject-of-insurance text, or None.

    Reads the document's coverage name, ACORD's code or its description alike:
    "BUILDING" / "B" -> building; "PERSONAL PROPERTY-INSURED" / "BPP" /
    "Business Personal Property" / "Contents" -> bpp; "PERSONAL PROPERTY-STOCK"
    / "STK" -> stock; "BUSINESS INCOME" / "BUSIN" / "BUSEE" -> bi; ..."""
    s = _norm(text)
    if not s:
        return None
    if s in ("B", "BLDG", "BUILDING") or re.fullmatch(r"(?:THE )?BUILDINGS?(?: (?:VALUE|LIMIT|COVERAGE|AMOUNT))?", s):
        return "building"
    if s in ("BUSIN", "BUSEE", "BUSER", "BUSRN", "BI") or re.search(
            r"\bBUSINESS (?:INCOME|INTERRUPTION)\b", s):
        return "bi"
    if s in ("EE",) or re.fullmatch(r"EXTRA EXPENSE(?: (?:LIMIT|COVERAGE))?", s):
        return "ee"
    # "PERSONAL PROPERTY - STOCK" is stock; "PERSONAL PROPERTY INCLUDING STOCK"
    # is the insured's personal property with stock inside it.
    if s in ("STK", "STOCK") or (re.search(r"\bSTOCK\b", s) and not re.search(r"\bINCLUDING STOCK\b", s)
                                 and re.search(r"\bPROPERTY\b|^STOCK\b", s)):
        return "stock"
    if s in ("POTOP",) or re.search(r"\bPROPERTY OF OTHERS\b", s):
        return "potop"
    if s in ("BPP", "CONTENTS") or re.search(r"\bBUSINESS PERSONAL PROPERTY\b", s) \
            or re.fullmatch(r"(?:YOUR )?PERSONAL PROPERTY(?: (?:INSURED|OF THE INSURED|LIMIT|VALUE))?"
                            r"(?: INCLUDING STOCK)?", s) \
            or re.fullmatch(r"CONTENTS(?: (?:LIMIT|VALUE))?", s):
        return "bpp"
    if s in ("PP",):
        return "pp"
    if s in ("FF",) or re.search(r"\bFURNITURE (?:AND|&) FIXTURES\b", s):
        return "ff"
    if s in ("MACEQ",) or re.fullmatch(r"MACHINERY(?: (?:AND|&) EQUIPMENT)?", s):
        return "maceq"
    if s in ("TIB", "I&B") or re.search(r"\bIMPROVEMENTS (?:AND|&) BETTERMENTS\b", s):
        return "tib"
    return None


_EXTENSION_RE = re.compile(r"\bEQUIPMENT BREAKDOWN\b|\bSPOILAGE\b", re.I)


def _bi_label(name: str, options: List[str]) -> str:
    s = _norm(" ".join([name] + list(options or [])))
    ee = bool(re.search(r"(?:\b(?:INCLUDING|WITH|AND|PLUS|W/)|&) ?EXTRA EXPENSE\b|\bW/ ?EE\b", s))
    no_ee = bool(re.search(r"\b(?:WITHOUT|EXCLUDING|NO) EXTRA EXPENSE\b", s))
    rental = bool(re.search(r"\b(?:INCLUDING|WITH|AND|&) RENTAL VALUE\b", s)) \
        and not re.search(r"\bOTHER THAN RENTAL VALUE\b", s)
    if ee and not no_ee:
        return _BI_LABELS[(True, None, rental)]
    if no_ee and not ee:
        return _BI_LABELS[(False, True, rental)]
    return "Business Income"


def _title(name: str) -> str:
    words = re.split(r"(\s+|-)", str(name or "").strip())
    return "".join(w if not w.strip() or w == "-" else (w[:1].upper() + w[1:].lower()) for w in words)


def _subject(name: str, options: List[str]) -> Tuple[Optional[str], str]:
    kind = subject_kind(name)
    if kind == "bi":
        return kind, _bi_label(name, options)
    if kind:
        return kind, _KIND_LABELS[kind]
    return None, _title(name)


def valuation_code(text: Any) -> str:
    """ACORD 140's VALUATION letter for what the row itself prints: R
    (replacement cost), A (actual cash value), M (market value), V (agreed
    amount - only when no other basis is printed: ISO's Agreed Value is an
    optional coverage beside replacement cost). "" when none or several."""
    s = _norm(text)
    found = set()
    if re.search(r"\bREPLACEMENT COST\b|\bRCV?\b|\bFRC\b", s):
        found.add("R")
    if re.search(r"\bACTUAL CASH VALUE\b|\bACV\b", s):
        found.add("A")
    if re.search(r"\bMARKET VALUE\b", s):
        found.add("M")
    if len(found) == 1:
        return next(iter(found))
    if not found and re.search(r"\bAGREED (?:VALUE|AMOUNT)\b|\bAV\b", s):
        return "V"
    return ""


_ENCODED_OPTION_RE = re.compile(
    r"^(?:REPLACEMENT COST(?: VALUE)?|ACTUAL CASH VALUE|ACV|RCV?|FRC|MARKET VALUE|"
    r"(?:INCLUDING|WITH|WITHOUT|EXCLUDING|NO) (?:EXTRA EXPENSE|RENTAL VALUE)|"
    r"VALUE TYPE\b.*)$")


def _conditions(kind: Optional[str], options: List[str], valuation: str) -> str:
    """The row's options that no other box already says - FORMS AND CONDITIONS
    TO APPLY ("Agreed Value" beside replacement cost, an extended period of
    indemnity). The valuation basis prints as VALUATION, the BI extra-expense /
    rental qualifiers as the subject, "Including Stock" qualifies replacement
    cost."""
    out: List[str] = []
    for opt in options or []:
        s = _norm(opt)
        if not s or _ENCODED_OPTION_RE.match(s):
            continue
        if s == "INCLUDING STOCK" and valuation == "R":
            continue
        if valuation == "V" and re.fullmatch(r"AGREED (?:VALUE|AMOUNT)", s):
            continue
        if str(opt).strip() not in out:
            out.append(str(opt).strip())
    return "; ".join(out)


def _causes(text: Any) -> str:
    s = _norm(text)
    m = re.search(r"\bSPECIAL(?: EXCLUDING THEFT)?\b|\bBROAD\b|\bBASIC\b|\bEARTHQUAKE\b", s)
    return _title(m.group(0)) if m else ""


def _coverage(name: str, *, limit: str, options: Optional[List[str]] = None,
              coinsurance: str = "", deductible: str = "", valuation_text: str = "",
              causes: str = "", inflation_guard: str = "", blanket: str = "",
              columns: Optional[List[str]] = None) -> Optional[dict]:
    """One printable coverage row, or None for a row with no amount of its own.

    `columns` names the terms the LAYOUT prints for this row (a header column,
    an options list): an empty one of those is the row saying "none", which
    the stamper may own as a blank. A term the layout does not print is
    unknown and stays with the old owners."""
    options = [o for o in (options or []) if str(o).strip()]
    lim = str(limit or "").strip()
    if not dollars(lim):
        return None                     # INCLUDED / NOT COVERED / no amount
    kind, subject = _subject(name, options)
    valuation = valuation_code(" ".join([valuation_text] + options)) if (valuation_text or options) else ""
    ded, ded_type = _deductible(deductible)
    cols = ["subject", "limit"] + [c for c in (columns or []) if c not in ("subject", "limit")]
    if "deductible" in cols:
        cols.append("deductible_type")
    return {
        "columns": cols,
        "coverage": re.sub(r"\s+", " ", str(name or "")).strip(),
        "kind": kind or "",
        "subject": subject,
        "limit": _money(lim),
        "coinsurance": _pct(coinsurance),
        "deductible": ded,
        "deductible_type": ded_type,
        "valuation": valuation,
        "causes": _causes(causes),
        "inflation_guard": str(inflation_guard or "").strip(),
        "blanket": str(blanket or "").strip(),
        "conditions": _conditions(kind, options, valuation),
        "options": options,
    }


# ── page furniture: lines a page break drops into the middle of a block ──────
_FURNITURE_RE = re.compile(
    r"^\[(?:document\s+page|table|end\s+table)"
    r"|\bpage\s*\d+\s*of\s*\d+\b"
    r"|\(continued\)\s*$"
    r"|^(?:policy\s+(?:number|no\.?)|effective\s+date|named\s+insured|insured\s+name)\b",
    re.I)


def _is_furniture(line: str) -> bool:
    return bool(_FURNITURE_RE.search(line or ""))


# ── Reader 1: ISO-style "COVERAGE: <name>" blocks ─────────────────────────────
_COVERAGE_LINE_RE = re.compile(r"^COVERAGE\s*:\s*(?P<name>\S.*?)\s*$", re.I)
_OPTIONS_LINE_RE = re.compile(r"^coverage\s+options?\s*(?:\(s\))?\s*:?\s*(?P<rest>.*)$", re.I)
_HEADER_WORDS = {"LIMIT": "limit", "COINSURANCE": "coinsurance", "COINS": "coinsurance",
                 "DEDUCTIBLE": "deductible", "DED": "deductible", "VALUATION": "valuation"}
_HEADER_RE = re.compile(
    r"^LIMIT(?:\s+OF\s+INSURANCE)?(?:\s+(?:COINSURANCE|COINS\.?|DEDUCTIBLE|DED\.?|VALUATION))*\s*$", re.I)
_TOK = {
    "limit": r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{1,3}(?:,\d{3})+(?:\.\d{2})?|INCLUDED|NOT\s+COVERED|EXCLUDED",
    "coinsurance": r"\d{1,3}\s?%",
    "deductible": r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{1,3}(?:,\d{3})+|\d+\s*(?:HOURS?|HRS?\.?|DAYS?)"
                  r"|\d+(?:\.\d+)?\s?%|\d+",
    "valuation": r"RCV?|ACV|AV|FRC|AGREED(?:\s+VALUE)?|REPLACEMENT\s+COST|ACTUAL\s+CASH\s+VALUE",
}


def _header_columns(line: str) -> List[str]:
    cols = []
    for word in re.findall(r"[A-Za-z]+", line or ""):
        col = _HEADER_WORDS.get(word.upper())
        if col and col not in cols:
            cols.append(col)
    return cols


def _parse_values(cols: List[str], line: str) -> Optional[Dict[str, str]]:
    rx = r"^\s*" + r"\s+".join(f"(?P<{c}>{_TOK[c]})" for c in cols) + r"\s*$"
    m = re.match(rx, line or "", re.I)
    return {c: m.group(c) for c in cols} if m else None


def _read_coverage_blocks(text: str) -> List[dict]:
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    sections: List[dict] = []
    cur: Optional[dict] = None
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        head = _heading_parts(line)
        if head:
            cur = {"premises": head[0], "building": head[1], "heading": line,
                   "coverages": [], "complete": True, "source": "coverage_blocks", "_blocks": 0}
            sections.append(cur)
            i += 1
            continue
        m = _COVERAGE_LINE_RE.match(line)
        if not m:
            i += 1
            continue
        if cur is None:
            cur = {"premises": "", "building": "", "heading": "", "coverages": [],
                   "complete": True, "source": "coverage_blocks", "_blocks": 0}
            sections.append(cur)
        cur["_blocks"] += 1
        name = m.group("name")
        options: List[str] = []
        in_options = False
        values = None
        cols: List[str] = []
        j = i + 1
        while j < n:
            ln = lines[j]
            if _COVERAGE_LINE_RE.match(ln) or _heading_parts(ln):
                break
            if not ln or _is_furniture(ln):
                j += 1
                continue
            if values is None and not cols:
                om = _OPTIONS_LINE_RE.match(ln)
                if om:
                    in_options = True
                    if om.group("rest").strip():
                        options.append(om.group("rest").strip())
                    j += 1
                    continue
                if _HEADER_RE.match(ln):
                    cols = _header_columns(ln)
                    j += 1
                    continue
                if in_options:
                    options.append(ln)
                j += 1
                continue
            if cols and values is None:
                values = _parse_values(cols, ln)
                if values is None:
                    break                      # an unreadable values line
                j += 1
                continue
            j += 1                             # peril deductibles, rates, ...
        i = j
        if not cols or values is None:
            cur["complete"] = False            # a block we could not read
            continue
        if _EXTENSION_RE.search(name):
            continue                           # equipment breakdown / spoilage
        # A block prints its limit, coinsurance and deductible under one header
        # ("LIMIT COINSURANCE DEDUCTIBLE"); a column the header leaves out is a
        # term this coverage does not have (a business income block printed
        # "LIMIT DEDUCTIBLE"). Valuation and the remaining conditions are read
        # off the options, when the block lists them.
        printed = ["coinsurance", "deductible"] + (["valuation", "conditions"] if in_options else [])
        cov = _coverage(name, limit=values.get("limit", ""), options=options,
                        coinsurance=values.get("coinsurance", ""),
                        deductible=values.get("deductible", ""),
                        valuation_text=values.get("valuation", ""), columns=printed)
        if cov is not None:
            cur["coverages"].append(cov)
    out = []
    for s in sections:
        if s.pop("_blocks", 0) and (s["coverages"] or not s["complete"]):
            out.append(s)
    return out


# ── Reader 2: "Prem Bldg Coverage Limit ..." table rows ───────────────────────
_TABLE_HEADER_RE = re.compile(
    r"\bprem(?:ises)?\.?\b.*\bb(?:ui)?ld(?:in)?g\.?\b.*\bcoverage\b.*\blimit\b", re.I)
_TABLE_ROW_START_RE = re.compile(r"^(\d{1,3})\s+(\d{1,3})\s+\S")
_TABLE_ROW_RE = re.compile(
    r"^(?P<prem>\d{1,3})\s+(?P<bldg>\d{1,3})\s+(?P<name>[A-Za-z][A-Za-z&/'.,\- ]*?)\s+"
    r"(?P<limit>\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+|\d{1,3}(?:,\d{3})+)(?P<rest>(?:\s+.*)?)$")
_REST_TOKENS = (
    ("causes", r"SPECIAL(?:\s+EXCLUDING\s+THEFT)?(?:\s+FORM)?|BROAD(?:\s+FORM)?|BASIC(?:\s+FORM)?"),
    ("coinsurance", r"\d{1,3}\s?%"),
    ("valuation", r"RCV?|ACV|AV|FRC|AGREED(?:\s+VALUE)?|REPLACEMENT\s+COST|ACTUAL\s+CASH\s+VALUE"),
    ("deductible", r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{1,3}(?:,\d{3})+|\d+\s*(?:HOURS?|HRS?\.?|DAYS?)|\d+"),
)


def _parse_rest(rest: str) -> Optional[Dict[str, str]]:
    got: Dict[str, str] = {}
    s = (rest or "").strip()
    while s:
        for key, rx in _REST_TOKENS:
            if key in got:
                continue
            m = re.match(rf"(?:{rx})(?=\s|$)", s, re.I)
            if m:
                got[key] = m.group(0)
                s = s[m.end():].strip()
                break
        else:
            return None                         # a token this table does not have
    return got


def _read_table_rows(text: str) -> List[dict]:
    lines = [re.sub(r"\s+", " ", ln.replace("|", " ")).strip()
             for ln in str(text or "").splitlines()]
    by_id: Dict[Tuple[str, str], dict] = {}
    order: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if not _TABLE_HEADER_RE.search(lines[i]):
            i += 1
            continue
        # The terms this table prints, read off its own header (an OCR-garbled
        # header still spells most of its words).
        printed = [key for key, rx in (("causes", r"\bcauses\b"), ("coinsurance", r"\bcoins"),
                                       ("valuation", r"\bvaluation\b"),
                                       ("deductible", r"\bdeductible\b|\bded\b"))
                   if re.search(rx, lines[i], re.I)]
        table_ok = True
        found: List[Tuple[Tuple[str, str], Optional[dict]]] = []
        j = i + 1
        while j < len(lines):
            ln = lines[j]
            if not ln or _is_furniture(ln):
                j += 1
                continue
            if not _TABLE_ROW_START_RE.match(ln):
                break
            m = _TABLE_ROW_RE.match(ln)
            rest = _parse_rest(m.group("rest")) if m else None
            if m is None or rest is None:
                table_ok = False               # a row we could not read
                j += 1
                continue
            key = (_label_number(m.group("prem")), _label_number(m.group("bldg")))
            cov = None if _EXTENSION_RE.search(m.group("name")) else _coverage(
                m.group("name"), limit=m.group("limit"), coinsurance=rest.get("coinsurance", ""),
                deductible=rest.get("deductible", ""), valuation_text=rest.get("valuation", ""),
                causes=rest.get("causes", ""), columns=printed)
            found.append((key, cov))
            j += 1
        for key, cov in found:
            if key not in by_id:
                by_id[key] = {"premises": key[0], "building": key[1],
                              "heading": f"Prem {key[0]} Bldg {key[1]}", "coverages": [],
                              "complete": True, "source": "table"}
                order.append(key)
            if cov is not None:
                by_id[key]["coverages"].append(cov)
        if not table_ok:
            # An unreadable row cannot be attributed to a premises: no premises
            # of this table may claim its remaining rows.
            for key, _ in found:
                by_id[key]["complete"] = False
        i = j
    return [by_id[k] for k in order]


# ── Reader 3: "Subject of Insurance: X / Amount of Insurance: $Y" blocks ──────
_SOI_LABEL_RE = re.compile(r"^subject\s+of\s+insurance\s*:\s*(?P<v>\S.*)$", re.I)
_TERM_LABELS = (
    ("limit", re.compile(r"^(?:amount|limit)(?:\s+of\s+insurance)?\s*:\s*(?P<v>\S.*)$", re.I)),
    ("coinsurance", re.compile(r"^coinsurance(?:\s+percent(?:age)?)?\s*:\s*(?P<v>\S.*)$", re.I)),
    ("valuation", re.compile(r"^valuation(?:\s+(?:method|basis))?\s*:\s*(?P<v>\S.*)$", re.I)),
    ("causes", re.compile(r"^causes?\s+of\s+loss(?:\s+form)?\s*:\s*(?P<v>\S.*)$", re.I)),
    ("deductible", re.compile(r"^deductible\s*:\s*(?P<v>\S.*)$", re.I)),
    ("inflation_guard", re.compile(r"^inflation\s+guard(?:\s*%|\s+percent(?:age)?)?\s*:\s*(?P<v>\S.*)$", re.I)),
)
_SECTION_TITLE_RE = re.compile(r"^[A-Z][A-Z0-9 /&,'().-]{6,}$")


def _read_subject_labels(text: str) -> List[dict]:
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    sections: List[dict] = []
    cur: Optional[dict] = None
    cov: Optional[dict] = None

    def _close():
        nonlocal cov
        if cur is not None and cov is not None:
            built = _coverage(cov["name"], limit=cov.get("limit", ""),
                              coinsurance=cov.get("coinsurance", ""),
                              deductible=cov.get("deductible", ""),
                              valuation_text=cov.get("valuation", ""),
                              causes=cov.get("causes", ""),
                              inflation_guard=cov.get("inflation_guard", ""))
            if built is None:
                cur["complete"] = False         # a subject with no readable amount
            else:
                cur["coverages"].append(built)
        cov = None

    for line in lines:
        head = _heading_parts(line)
        if head:
            _close()
            cur = {"premises": head[0], "building": head[1], "heading": line,
                   "coverages": [], "complete": True, "source": "subject_labels"}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if _SECTION_TITLE_RE.match(line) and ":" not in line:
            _close()
            cur = None                          # a new section of the document
            continue
        m = _SOI_LABEL_RE.match(line)
        if m:
            _close()
            cov = {"name": m.group("v").strip()}
            continue
        if cov is None:
            continue
        for key, rx in _TERM_LABELS:
            tm = rx.match(line)
            if tm and key not in cov:
                val = tm.group("v").strip()
                if key == "limit":
                    am = re.search(r"\$?\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+", val)
                    val = am.group(0) if am else ""
                elif key == "coinsurance":
                    am = re.search(r"\d{1,3}\s?(?:%|percent)", val, re.I)
                    val = am.group(0) if am else ""
                elif key == "deductible":
                    am = re.search(r"\$\s?\d{1,3}(?:,\d{3})*|\d+\s*(?:hours?|hrs?|days?)\b|\d+(?:\.\d+)?\s?%",
                                   val, re.I)
                    val = am.group(0) if am else ""
                cov[key] = val
                break
    _close()
    return [s for s in sections if s["coverages"] or not s["complete"]]


# ── the merge door ────────────────────────────────────────────────────────────

def read_schedule_text(text: str) -> List[dict]:
    """Every premises section a document's property schedule prints (any of
    the three layouts). Sections of one identity from two layouts must agree."""
    out: List[dict] = []
    for reader in (_read_coverage_blocks, _read_table_rows, _read_subject_labels):
        try:
            out.extend(reader(text))
        except Exception as exc:                               # noqa: BLE001
            logger.warning("property schedule reader %s failed: %s", reader.__name__, exc)
    return out


def _signature(section: dict) -> Tuple:
    return tuple((c.get("kind") or c.get("subject"), dollars(c.get("limit")))
                 for c in section.get("coverages") or [])


_DEFAULT_DED_RE = re.compile(
    r"\bDEDUCTIBLE\b\s*:?\s*(?P<amt>\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*\.?\s*,?\s*"
    r"(?:EXCEPTIONS?\s*:?\s*(?P<exc>[^\n]*)|(?P<except>(?:EXCEPT|UNLESS\s+OTHERWISE)\b[^\n]*))",
    re.I)
_NO_EXCEPTION_RE = re.compile(r"^\s*(?:none|n/?a|-+|_+|no\s+exceptions?)?\s*\.?\s*$", re.I)


_PROPERTY_CONTEXT_RE = re.compile(r"\bPROPERTY\b", re.I)


def qualified_default_deductible(text: str) -> Optional[dict]:
    """The PROPERTY declarations' default deductible when the document
    qualifies it with exceptions ("DEDUCTIBLE $500. Exceptions: SEE
    SCHEDULE"), else None. The statement must sit under property wording (the
    page's own coverage-part title within the preceding 3,000 characters)."""
    text = str(text or "")
    for m in _DEFAULT_DED_RE.finditer(text):
        exc = (m.group("exc") or m.group("except") or "").strip()
        if m.group("exc") is not None and _NO_EXCEPTION_RE.match(exc):
            continue
        if not exc:
            continue
        if not _PROPERTY_CONTEXT_RE.search(text[max(0, m.start() - 3000):m.start()]):
            continue
        return {"amount": _money(m.group("amt")), "exceptions": exc[:80]}
    return None


# A section is a PROPERTY premises only when it prints at least one of these;
# an inland marine or auto schedule laid out the same way never is (Orbin's
# contractors-equipment items once filled this grid).
_CORE_PROPERTY_KINDS = frozenset({"building", "bpp", "stock", "pp", "potop", "ff",
                                  "bi", "ee", "tib"})


def _is_property_section(section: dict) -> bool:
    return any(c.get("kind") in _CORE_PROPERTY_KINDS for c in section.get("coverages") or [])


def derive_property_coverages(facts: dict, docs: Any) -> Optional[dict]:
    """Merge door: read every active document's property schedule into
    `facts["_property_coverages"]` (removed when nothing is read)."""
    if not isinstance(facts, dict):
        return None
    sections: Dict[Tuple[str, str], dict] = {}
    conflicted: set = set()
    order: List[Tuple[str, str]] = []
    default = None
    for d in docs if isinstance(docs, list) else []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        text = str(d.get("text") or "")
        if not text.strip():
            continue
        for s in read_schedule_text(text):
            if not _is_property_section(s):
                continue
            key = (s["premises"], s["building"])
            if key in conflicted:
                continue
            if key not in sections:
                sections[key] = s
                order.append(key)
                continue
            have = sections[key]
            if _signature(have) == _signature(s):
                have["complete"] = bool(have["complete"] and s["complete"])
                continue
            # Two printings of one premises with DIFFERENT coverage lists: the
            # documents disagree, so neither decides the grid.
            conflicted.add(key)
            logger.warning("property schedule: premises %s / building %s printed with two "
                           "different coverage lists - neither is used", key[0] or "?", key[1] or "?")
        if default is None:
            default = qualified_default_deductible(text)
    kept = [sections[k] for k in order if k not in conflicted]
    if not kept and default is None:
        facts.pop(KEY, None)
        return None
    blob = {"sections": kept}
    if default:
        blob["default_deductible"] = default
    facts[KEY] = blob
    logger.info("property schedule: %d premises section(s) read (%s)%s", len(kept),
                ", ".join(f"{s['premises'] or '?'}/{s['building'] or '-'}: "
                          f"{len(s['coverages'])}{'' if s['complete'] else ' partial'}"
                          for s in kept)[:300],
                f"; default deductible {default['amount']} with exceptions" if default else "")
    return blob


# ── the stamper's view ────────────────────────────────────────────────────────

def _location_rows(facts: dict) -> List[dict]:
    rows = _fv(facts, "property_locations")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _row_ids(row: dict) -> Tuple[str, str, bool]:
    """(premises, building, printed) for a premises row. `printed` is True when
    the premises number is the document's own (not a LOC # assigned by
    position)."""
    printed = _label_number(row.get("premises_number"))
    prem = printed or _label_number(row.get("location_number"))
    return prem, _label_number(row.get("building_number")), bool(printed)


def _matches(section: dict, row: dict) -> bool:
    prem, bldg, _ = _row_ids(row)
    if not section.get("premises") or not prem or section["premises"] != prem:
        return False
    sb = section.get("building") or ""
    return not sb or not bldg or sb == bldg


def _value_check(section: dict, row: dict) -> Tuple[int, int]:
    """(agreements, disagreements) between the row's own building / BPP value
    and the section's building / BPP coverage."""
    agree = disagree = 0
    by_kind = {}
    for c in section.get("coverages") or []:
        by_kind.setdefault(c.get("kind"), []).append(dollars(c.get("limit")))
    for kind, key in (("building", "building_value"), ("bpp", "bpp_value")):
        mine = dollars(row.get(key))
        theirs = by_kind.get(kind) or []
        if not mine or not theirs:
            continue
        if mine in theirs:
            agree += 1
        else:
            disagree += 1
    return agree, disagree


def section_for_row(facts: dict, idx: int) -> Optional[dict]:
    """The schedule section that is premises row `idx`'s own, or None.

    A join needs ONE section and ONE row that name each other: by the printed
    premises / building numbers; by a LOC # given by position only when the
    row's own building / BPP value agrees with the section's; and a headless
    section only on a one-premises, one-section schedule."""
    blob = _fv(facts, KEY)
    sections = [s for s in (blob.get("sections") if isinstance(blob, dict) else None) or []
                if isinstance(s, dict)]
    rows = _location_rows(facts)
    if not sections or not (0 <= idx < len(rows)):
        return None
    row = rows[idx]
    if len(rows) == 1 and len(sections) == 1 and not sections[0].get("premises"):
        sec = sections[0]
        return sec if _value_check(sec, row)[1] == 0 else None
    hits = [s for s in sections if _matches(s, row)]
    if len(hits) != 1:
        return None
    sec = hits[0]
    if sum(1 for r in rows if _matches(sec, r)) != 1:
        return None
    _, _, printed = _row_ids(row)
    agree, disagree = _value_check(sec, row)
    if printed:
        return sec                      # the document's own numbers name the row
    if disagree or (not agree and not (len(rows) == 1 and len(sections) == 1)):
        return None
    return sec


def premises_rows(facts: dict, idx: int) -> Optional[dict]:
    """{"rows": [...], "complete": bool} - premises row `idx`'s coverage rows in
    the schedule's order, at most five, or None when its schedule was not read.

    The Building / BPP amounts are the premises row's own `building_value` /
    `bpp_value` when it carries them (the location table a person edits);
    a value the row has and the schedule lacks is kept as its own row."""
    sec = section_for_row(facts, idx)
    if sec is None or not sec.get("coverages"):
        return None
    row = _location_rows(facts)[idx]
    covs = [dict(c) for c in sec["coverages"]]
    seen_kinds = {c.get("kind") for c in covs}
    for kind, key in (("bpp", "bpp_value"), ("building", "building_value")):
        val = row.get(key)
        if not dollars(val):
            continue
        hit = next((c for c in covs if c.get("kind") == kind), None)
        if hit is not None:
            hit["limit"] = _money(val)
        elif kind not in seen_kinds:
            covs.insert(0, {"columns": ["subject", "limit"],
                            "coverage": _KIND_LABELS[kind], "kind": kind,
                            "subject": _KIND_LABELS[kind], "limit": _money(val),
                            "coinsurance": "", "deductible": "", "deductible_type": "",
                            "valuation": "", "causes": "", "inflation_guard": "",
                            "blanket": "", "conditions": "", "options": []})
    complete = bool(sec.get("complete")) and len(covs) <= ROWS_PER_PREMISES
    if len(covs) > ROWS_PER_PREMISES:
        logger.warning("property schedule: premises row %d prints %d coverages; ACORD 140 "
                       "holds %d - the rest are not printed", idx + 1, len(covs),
                       ROWS_PER_PREMISES)
    return {"rows": covs[:ROWS_PER_PREMISES], "complete": complete}


def default_deductible(facts: dict) -> Optional[dict]:
    blob = _fv(facts, KEY)
    d = blob.get("default_deductible") if isinstance(blob, dict) else None
    return d if isinstance(d, dict) and dollars(d.get("amount")) else None
