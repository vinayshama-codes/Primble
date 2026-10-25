"""claim_checks.py - do the claims in the loss history hold together?

Brent's 17 Oct 2026 attachment C (25sepChanges.md Z29-3 C, Z31-C). His
synthetic claims file holds 12 CONTROL claims and 12 CHALLENGE copies of the
same claims with planted mistakes: a report date before the loss date, "NOT
PROVIDED" report / first-made dates, a missing reserve, incurred that is not
paid + reserve + expense (9,200 vs 9,300), a unit described as a different
vehicle, a building the premises schedule does not have (Bldg 003), and a WC
class code the policy does not rate (5190 -> 5403). Before this module nothing
read a claim's fields beyond "is this row a claim?" and the claim count, so a
loss run that contradicted itself scored exactly like a clean one.

Brent's rule (20 Oct, answered): contradictions count against Consistency,
missing items against Completeness, and one fact is never charged twice (D69).
Owner, 21 Oct: these are pillar DEDUCTIONS with a Recommendations card naming
the claim - never hard stops or warnings, so they hold no 60 / 85 cap.

ONE READER. Claim rows reach `facts["loss_history"]` two ways - loss-run
extraction (LLM call 1, its RULE 7) and the loss table a person types or
imports (`schedule_capture`). Both write the same row keys. `claim_records`
reads them once, through `loss_history_state.claim_rows` (the one "is this row
a claim?" door), and every check reads the records - never the raw rows.

EACH CHECK RUNS OVER THE FIELDS THAT EXIST, and stands down otherwise:
  1. a report / first-made date before the loss date      -> conflict
  2. a report / first-made date written as not provided    -> missing
     (`answer_semantics.is_placeholder_text`, the one door for "this says
     nothing"); a BLANK (or "N/A") report date only where the claims of the
     same line carry report dates - a loss run that prints none is not
     charged - or, in a loss table a person saved, where any claim does. A
     blank first-made date is never missing (only claims-made lines have one).
  3. an OPEN claim with no reserve                         -> missing
     (the same "column exists" rule for a blank)
  4. incurred that is neither paid + reserve + expense nor paid + reserve
     (expense shown beside a loss-only incurred), beyond rounding to the
     dollar                                                 -> conflict
     Needs incurred, paid, reserve (a closed claim's blank reserve is 0) AND
     expense; a claim in subrogation, with a recovery, or a negative figure
     (net of recovery) is not judged.
  5. a claim naming its unit's vehicle ("unit N", "V016", or a VIN) as a year
     and make - or a VIN - the vehicle schedule does not have -> conflict
  6. a PROPERTY claim's premises / building heading (or any claim's own
     location / building fields) the premises schedule does not have
     (`extraction_service.premises_label_parts`)            -> conflict
  7. a WC claim's class code the WC class rows do not rate  -> conflict
  Checks 5-7 judge only claims whose loss date falls inside the term of the
  policies of the line the schedule describes (`current_term(facts, family)`:
  auto for vehicles, WC for class codes, the claim's line - property by
  default - for premises): the schedules describe that term, and a vehicle
  sold or a building closed years ago is a legitimate claim on a loss run,
  not a contradiction. A schedule check finds a contradiction only when every
  schedule row the claim could mean states something else: a row with no
  year, no building number, no VIN ... makes it stand down.

ONE CLAIM, ONE CHARGE (D69). The same claim held twice (two loss runs, an
extracted row and a typed one, Brent's two-copy file) shares one identity
(`_claim_identities`: the claim number, else the loss date and line family),
so each finding is listed and charged once, and a blank detail is missing only
when no copy states it. The copies' values are never compared (B2 is Brent's).

Fields loss-run extraction does not capture today (its schema has no key for
them - a prompt change is the owner's call): the claim's EXPENSE and its DATE
FIRST MADE. The loss table cannot carry them either (no ACORD 125 box), so
checks 2 (first-made) and 4 only run on rows that carry them. The vehicle,
premises / building and class code are read from the claim's own description.

Pure, no I/O, never raises to its caller.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONFLICT = "conflict"
MISSING = "missing"

CHECK_REPORT_BEFORE_LOSS = "report_before_loss"
CHECK_FIRST_MADE_BEFORE_LOSS = "first_made_before_loss"
CHECK_INCURRED_MISMATCH = "incurred_mismatch"
CHECK_VEHICLE_NOT_SCHEDULED = "vehicle_not_scheduled"
CHECK_BUILDING_NOT_SCHEDULED = "building_not_scheduled"
CHECK_CLASS_NOT_SCHEDULED = "class_not_scheduled"
CHECK_REPORT_DATE_MISSING = "report_date_missing"
CHECK_FIRST_MADE_MISSING = "first_made_date_missing"
CHECK_RESERVE_MISSING = "reserve_missing"

# The order findings are listed and charged in: contradictions first, then the
# missing details, each in rule order.
_CHECK_ORDER = (
    CHECK_REPORT_BEFORE_LOSS, CHECK_FIRST_MADE_BEFORE_LOSS, CHECK_INCURRED_MISMATCH,
    CHECK_VEHICLE_NOT_SCHEDULED, CHECK_BUILDING_NOT_SCHEDULED, CHECK_CLASS_NOT_SCHEDULED,
    CHECK_REPORT_DATE_MISSING, CHECK_FIRST_MADE_MISSING, CHECK_RESERVE_MISSING,
)

# The deductions (owner, 21 Oct 2026 - "pillar deductions, not stops"). Each
# finding costs its kind's points; a kind is capped so one loss run with a
# systematic slip (or a long one) cannot floor a pillar on its own.
CLAIM_CONFLICT_POINTS = 5
CLAIM_CONFLICT_CAP = 15
CLAIM_MISSING_POINTS = 2
CLAIM_MISSING_CAP = 10
# The box a finding is fixed in (the loss table - `answer_routing` routes it to
# the schedule) and the Exposure / Completeness bucket it is charged under.
DEDUCTION_FACT = "loss_history"
DEDUCTION_BUCKET = "claims"
# How many findings the Recommendations card names before "and N more".
_NAMED_ON_CARD = 10

# Rounding to the dollar: each printed amount can be up to 50 cents off, so a
# sum of n parts against a printed total can be off by 0.5 * (n + 1).
_ROUNDING_PER_AMOUNT = 0.5

# ── The ONE reader ──────────────────────────────────────────────────────────
# The row keys each path writes. Extraction (RULE 7): date, claim_date,
# description, amount (total incurred), paid, reserved_amount, claim_number,
# line_of_business, open, open_code, subrogation_code. The loss table: the same
# keys for its columns. The others (`incurred`, `expense`, `first_made_date`,
# `class_code`, `location_number`, `building_number`, `vehicle`, `recovery`)
# are read when a row carries them - nothing writes them today.
_FIELD_KEYS: Dict[str, Tuple[str, ...]] = {
    "number":          ("claim_number",),
    "loss_date":       ("date",),
    "report_date":     ("claim_date",),
    "first_made_date": ("first_made_date",),
    "line":            ("line_of_business",),
    "description":     ("description",),
    "paid":            ("paid",),
    "reserve":         ("reserved_amount",),
    "expense":         ("expense",),
    "incurred":        ("incurred", "amount"),
    "recovery":        ("recovery",),
    "subrogation":     ("subrogation_code",),
    "location":        ("location_number",),
    "building":        ("building_number",),
    "vehicle":         ("vehicle",),
    "class_code":      ("class_code",),
}
_STATUS_KEYS = ("open_code", "status", "open")


def _fv(facts: Any, key: str) -> Any:
    if not isinstance(facts, dict):
        return None
    raw = facts.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _cell(row: dict, keys: Tuple[str, ...]) -> Any:
    """The first key of `keys` the row states (an envelope's value)."""
    for key in keys:
        if key not in row:
            continue
        val = row.get(key)
        if isinstance(val, dict) and "value" in val:
            val = val.get("value")
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        return val
    return None


def _text(val: Any) -> str:
    return str(val).strip() if val is not None and not isinstance(val, bool) else ""


_OPEN_WORDS = frozenset({"o", "open", "opened", "reopen", "reopened", "y", "yes", "true"})
_CLOSED_WORDS = frozenset({"c", "closed", "close", "n", "no", "false", "settled"})


def _status(row: dict) -> Optional[str]:
    """"open" / "closed" / None. `open_code` first (its O / C, or ACORD's own
    Y / N "claim open?"), then a status word, then the `open` flag."""
    for key in _STATUS_KEYS:
        if key not in row:
            continue
        val = row.get(key)
        if isinstance(val, dict) and "value" in val:
            val = val.get("value")
        if isinstance(val, bool):
            return "open" if val else "closed"
        text = str(val or "").lower()
        # The cell whole ("Re-opened"), else its first word ("Open - in
        # litigation", "Closed without payment").
        for word in (re.sub(r"[^a-z]", "", text), (re.findall(r"[a-z]+", text) or [""])[0]):
            if word in _OPEN_WORDS:
                return "open"
            if word in _CLOSED_WORDS:
                return "closed"
    return None


# THE SHARE-OUT PROBE for the loss table (`sqs_service._unify_card_points`).
# The door measures a row's points by answering its field and re-scoring; for
# a table field it used a placeholder ("Yes") in place of the table, which
# DELETES every claim - and with them the Loss History pillar's own reading of
# the claims (an attested "no losses" beside claim rows is a conflict held at
# 45). Measured on the Choice Electric package with an attestation: the card
# promised +10 where correcting the claims adds +6. The probe is now the same
# claims, each marked answered: every check here passes it, nothing else reads
# the mark, so the measured gain is exactly what correcting the claims returns.
PROBE_MARK = "_claim_checks_answered"


def probe_answer(facts: Any) -> Any:
    """The loss table with every claim marked answered (a probe value only -
    never stored: the table and extraction never write the mark)."""
    rows = _fv(facts, "loss_history")
    if not isinstance(rows, list):
        return rows
    return [dict(r, **{PROBE_MARK: True}) if isinstance(r, dict) else r for r in rows]


def claim_records(facts: Any) -> List[dict]:
    """Every claim in `facts["loss_history"]`, read once: its number, dates,
    line, description, status and figures under one set of names, whichever
    path wrote the row. Rows that are not claims (the no-loss sentence a model
    writes into the table) are left out by `loss_history_state.claim_rows`."""
    rows = _fv(facts, "loss_history")
    if not isinstance(rows, list) or not rows:
        return []
    try:
        from services.loss_history_state import claim_rows
        rows = claim_rows(rows)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("claim_checks: claim rows unreadable: %s", exc)
        return []
    out: List[dict] = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get(PROBE_MARK):
            continue
        rec = {name: _cell(row, keys) for name, keys in _FIELD_KEYS.items()}
        rec["status"] = _status(row)
        out.append(rec)
    return out


# ── Reading one cell ────────────────────────────────────────────────────────
BLANK = "blank"
PLACEHOLDER = "placeholder"     # written as not provided / unknown / TBD
NONE_STATED = "none_stated"     # written as N/A or "none": a stated answer, never "missing"
UNREADABLE = "unreadable"
DATE = "date"
AMOUNT = "amount"
# A cell holding only punctuation ("-", "--", "*") is how a loss run prints an
# empty cell: blank, not a statement.
_PUNCT_ONLY_RE = re.compile(r"^[\s\-_.*/\\?\u2013\u2014]+$")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH_YEAR_RE = re.compile(r"(\d{1,2})\s*[/\-.]\s*(\d{4})")
_YEAR_MONTH_RE = re.compile(r"(\d{4})\s*[/\-.]\s*(\d{1,2})")
_NAMED_MONTH_YEAR_RE = re.compile(r"([A-Za-z]{3,9})\.?,?\s+(\d{4})")
_YEAR_RE = re.compile(r"(\d{4})")


def _placeholder_state(s: str, field: str) -> Optional[str]:
    """BLANK / PLACEHOLDER / NONE_STATED for a cell that states no value, None
    for one that does. Two doors decide, never a local word list:
    `answer_semantics.is_placeholder_text` (does it carry information?) and
    `interpret_answer` (UNKNOWN - "not provided", "unknown", "TBD" - is a
    missing detail; "N/A" / "none" answer the question: a first-made date is
    N/A on an occurrence claim, an open claim's reserve can be "None")."""
    if _PUNCT_ONLY_RE.match(s):
        return BLANK
    try:
        from services.answer_semantics import UNKNOWN, interpret_answer, is_placeholder_text
        if not is_placeholder_text(s):
            return None
        return PLACEHOLDER if interpret_answer(field, s).intent == UNKNOWN else NONE_STATED
    except Exception:                                          # noqa: BLE001
        return None


def _date_cell(val: Any, field: str = "claim_date") -> Tuple[str, Optional[Tuple[int, Optional[int], Optional[int]]]]:
    """(state, (year, month, day)). A month / year or a year alone is a date at
    that precision (an Excel cell formatted "mm/yyyy" or "yyyy")."""
    s = _text(val)
    if not s:
        return BLANK, None
    stated = _placeholder_state(s, field)
    if stated:
        return stated, None
    try:
        from services.normalization import normalize_date
        iso = normalize_date(s)
    except Exception:                                          # noqa: BLE001
        iso = None
    if iso:
        try:
            y, m, d = (int(p) for p in str(iso).split("-")[:3])
            if 1900 <= y <= 2100:
                return DATE, (y, m, d)
        except (TypeError, ValueError):
            pass
    m = _MONTH_YEAR_RE.fullmatch(s)
    if m and 1 <= int(m.group(1)) <= 12 and 1900 <= int(m.group(2)) <= 2100:
        return DATE, (int(m.group(2)), int(m.group(1)), None)
    m = _YEAR_MONTH_RE.fullmatch(s)
    if m and 1 <= int(m.group(2)) <= 12 and 1900 <= int(m.group(1)) <= 2100:
        return DATE, (int(m.group(1)), int(m.group(2)), None)
    m = _NAMED_MONTH_YEAR_RE.fullmatch(s)
    if m and m.group(1)[:3].lower() in _MONTHS and 1900 <= int(m.group(2)) <= 2100:
        return DATE, (int(m.group(2)), _MONTHS[m.group(1)[:3].lower()], None)
    m = _YEAR_RE.fullmatch(s)
    if m and 1900 <= int(s) <= 2100:
        return DATE, (int(s), None, None)
    return UNREADABLE, None


def _before(a: tuple, b: tuple) -> bool:
    """Is `a` certainly earlier than `b`? Compared only to the precision both
    state - 10/2025 is before 11/02/2025, 11/2025 is not known to be."""
    for x, y in zip(a, b):
        if x is None or y is None:
            return False
        if x != y:
            return x < y
    return False


def _show_date(parts: Optional[tuple]) -> str:
    if not parts:
        return ""
    y, m, d = parts
    if m and d:
        return f"{m:02d}/{d:02d}/{y}"
    if m:
        return f"{m:02d}/{y}"
    return str(y)


_NEGATIVE_RE = re.compile(r"^\s*(?:\(|-|\$\s*-|-\s*\$)")


def _amount_cell(val: Any, field: str = "reserved_amount") -> Tuple[str, Optional[float]]:
    """(state, amount) through the one money reader (`sqs_service._to_float`).
    A negative figure (net of a recovery) is UNREADABLE for the arithmetic."""
    if isinstance(val, bool):
        return UNREADABLE, None
    if isinstance(val, (int, float)):
        return (AMOUNT, float(val)) if val >= 0 else (UNREADABLE, None)
    s = _text(val)
    if not s:
        return BLANK, None
    stated = _placeholder_state(s, field)
    if stated:
        return stated, None
    if _NEGATIVE_RE.match(s):
        return UNREADABLE, None
    try:
        from services.sqs_service import _to_float
        amount = _to_float(s)
    except Exception:                                          # noqa: BLE001
        amount = None
    if amount is None:
        return UNREADABLE, None
    return AMOUNT, float(amount)


def _money(amount: float) -> str:
    return f"${amount:,.2f}".replace(".00", "") if amount != int(amount) else f"${int(amount):,}"


def _group_key(rec: dict) -> str:
    """Claims of the same line (as the source spells it) - the unit the
    "this source carries the column" rule is judged over."""
    return re.sub(r"[^a-z0-9]", "", _text(rec.get("line")).lower())


# ── The claim's line, and the package's current term ────────────────────────

def _claim_family(rec: dict) -> Optional[str]:
    """The line of business the claim is on: its line, else (a package /
    container line such as "Commercial Package") the description's leading
    segment ("Property | Prem 001 ...")."""
    try:
        from services.lob_canon import canon_line
    except Exception:                                          # noqa: BLE001
        return None
    fam = canon_line(_text(rec.get("line")))
    if fam:
        return fam
    lead = re.split(r"[|;\n]", _text(rec.get("description")), maxsplit=1)[0]
    return canon_line(lead) if lead.strip() else None


def _iso_date(val: Any) -> Optional[date]:
    state, parts = _date_cell(val)
    if state != DATE or not parts or parts[1] is None or parts[2] is None:
        return None
    try:
        return date(*parts)
    except ValueError:
        return None


def _row_family(row: dict, present: Any) -> Optional[str]:
    try:
        from services.lob_canon import canon_line_or_part
        return canon_line_or_part(row.get("line") or row.get("line_of_business"), present)
    except Exception:                                          # noqa: BLE001
        return None


def current_term(facts: Any, family: Optional[str] = None) -> Optional[Tuple[date, date]]:
    """(start, end) of the term the package's schedules describe: the current
    policies' terms (`coverage_lines`, the earliest start to the latest end),
    else the expiring term a renewal routed to `prior_*`, else the package's
    own term. None when no full pair of dates is stated.

    With `family` (review fix, 21 Oct): the term of THAT line's policies - the
    vehicle schedule describes the auto policy's term, the class rows the WC
    policy's, the premises the property policy's. An old cyber dec beside this
    year's auto policy used to widen the span to both, so a claim on a vehicle
    sold years ago was judged against today's schedule. With no dated row of
    the line, the policies' span counts only when every dated row shares one
    term."""
    spans: List[Tuple[date, date]] = []
    own: List[Tuple[date, date]] = []
    lines = _fv(facts, "coverage_lines")
    rows = [r for r in lines if isinstance(r, dict)] if isinstance(lines, list) else []
    present: Any = ()
    if family and rows:
        try:
            from services.lob_canon import coverage_families_present
            present = coverage_families_present(rows)
        except Exception:                                      # noqa: BLE001
            present = ()
    for row in rows:
        start, end = _iso_date(row.get("effective_date")), _iso_date(row.get("expiration_date"))
        if start and end and start < end:
            spans.append((start, end))
            if family and _row_family(row, present) == family:
                own.append((start, end))
    if own:
        return min(s for s, _e in own), max(e for _s, e in own)
    if spans and (not family or len(set(spans)) == 1):
        return min(s for s, _e in spans), max(e for _s, e in spans)
    for eff, exp in (("prior_effective_date", "prior_expiration_date"),
                     ("effective_date", "expiration_date")):
        start, end = _iso_date(_fv(facts, eff)), _iso_date(_fv(facts, exp))
        if start and end and start < end:
            return start, end
    return None


def _in_term(rec: dict, term: Optional[Tuple[date, date]]) -> bool:
    if not term:
        return False
    loss = _iso_date(rec.get("loss_date"))
    return bool(loss and term[0] <= loss < term[1])


# ── 5. The vehicle a claim names ────────────────────────────────────────────
# A UNIT marker ("V016", "Unit 16") right before a year and a word: the
# insured's own vehicle, as a loss run prints it. A year and a make with no
# unit marker is free text - often the CLAIMANT's car ("rear-ended a 2019 Ford
# Escape") - and is never judged. Review fix (21 Oct): "vehicle 2" / "Veh 2" /
# "V2" is a police report's numbering of the parties ("Insured vehicle 1
# rear-ended vehicle 2, a 2018 Honda Accord") - the claimant as often as the
# insured - so only "unit N" and a fleet unit number (V + 2-4 digits) mark the
# insured's own vehicle.
_UNIT_VEHICLE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<unit>unit\s*(?:#|no\.?|num(?:ber)?)?\s*[:.]?\s*\d{1,4}|v[-#]?\d{2,4})"
    r"(?![0-9])\s*[|,;:/\-]?\s*"
    r"(?P<year>(?:19|20)\d{2})\s+(?P<rest>[A-Za-z][^|;\n]*)", re.I)
_UNIT_NUMBER_RE = re.compile(r"^unit\W*(\d+)$", re.I)
_YEAR_VEHICLE_RE = re.compile(r"^\s*(?P<year>(?:19|20)\d{2})\s+(?P<rest>[A-Za-z][^|;\n]*)")
_VIN_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{17})(?![A-Za-z0-9])")
# The make words a buyer writes for the makes a schedule prints.
_MAKE_ALIASES = {"CHEVY": "CHEVROLET", "VW": "VOLKSWAGEN", "MERCEDES": "MERCEDESBENZ"}


def _make_key(word: Any) -> str:
    key = re.sub(r"[^A-Z0-9]", "", str(word or "").upper())
    return _MAKE_ALIASES.get(key, key)


def _same_make(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4
                                         and (a.startswith(b) or b.startswith(a))))


def _vin(val: Any) -> str:
    try:
        from services.schedule_capture import is_valid_vin, normalize_vin
    except Exception:                                          # noqa: BLE001
        return ""
    vin = normalize_vin(val)
    if is_valid_vin(vin) and re.search(r"\d", vin) and re.search(r"[A-Z]", vin):
        return vin
    return ""


def _states_something(row: dict) -> bool:
    return any(v not in (None, "", False) and not (isinstance(v, str) and not v.strip())
               for v in row.values())


def _schedule_vehicles(facts: Any) -> List[dict]:
    """Every vehicle row of the schedule, identified or not - {year, make,
    vin, model}, each possibly empty. Review fix (21 Oct): a row with no year
    (or no make, or a VIN only) used to be dropped, so a claim naming exactly
    that vehicle read as "not on the schedule". A row that cannot be told
    apart from the claim's vehicle now makes the check stand down."""
    rows = _fv(facts, "auto_vin_schedule")
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _states_something(row):
            continue
        m = re.search(r"(?:19|20)\d{2}", _text(row.get("year")))
        out.append({"year": int(m.group(0)) if m else None, "make": _make_key(row.get("make")),
                    "vin": _vin(row.get("vin")), "model": _text(row.get("model"))})
    return out


def _vehicle_words(rest: str) -> Tuple[str, str, str]:
    """(make word, model word, "make model" as printed). The model is the word
    after the make plus a numbered trim ("Transit 250", "Express G2500"); in
    mixed-case text a lower-case word ends it ("2019 Ford Focus hit pole" is a
    "Ford Focus"), so the claim's own words never leak into the vehicle."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", rest or "")
    if not words:
        return "", "", ""
    mixed = bool(re.search(r"[a-z]", rest or "")) and bool(re.search(r"[A-Z]", rest or ""))

    def _name(word: str) -> bool:
        return not mixed or word[0].isupper() or word[0].isdigit()

    shown = [words[0]]
    model = ""
    if len(words) > 1 and _name(words[1]):
        model = words[1]
        shown.append(words[1])
        if len(words) > 2 and re.search(r"\d", words[2]) and _name(words[2]):
            shown.append(words[2])
    return words[0], model, " ".join(shown)


def _unit_label(unit: str) -> str:
    """"unit 16" for "Unit 16" / "unit #16", "unit V016" for a fleet number."""
    m = _UNIT_NUMBER_RE.match(re.sub(r"\s+", " ", unit or "").strip())
    return f"unit {m.group(1)}" if m else f"unit {re.sub(r'[^A-Za-z0-9]', '', unit or '').upper()}"


def _claim_vehicles(rec: dict) -> List[dict]:
    """The vehicles a claim names as the insured's own: {unit, year, make,
    model, printed, vin}."""
    found: List[dict] = []
    texts = [_text(rec.get("vehicle")), _text(rec.get("description"))]
    for n, text in enumerate(texts):
        if not text:
            continue
        for m in _UNIT_VEHICLE_RE.finditer(text):
            make, model, printed = _vehicle_words(m.group("rest"))
            found.append({"unit": re.sub(r"\s+", " ", m.group("unit")).strip(),
                          "year": int(m.group("year")), "make": make, "model": model,
                          "printed": f"{m.group('year')} {printed}".strip(), "vin": ""})
        if n == 0:                       # a vehicle field of its own: year first
            m = _YEAR_VEHICLE_RE.match(text)
            if m and not found:
                make, model, printed = _vehicle_words(m.group("rest"))
                found.append({"unit": "", "year": int(m.group("year")), "make": make,
                              "model": model,
                              "printed": f"{m.group('year')} {printed}".strip(), "vin": ""})
        for m in _VIN_TOKEN_RE.finditer(text):
            vin = _vin(m.group(1))
            if vin:
                found.append({"unit": "", "year": None, "make": "", "model": "",
                              "printed": "", "vin": vin})
    return found


def _could_be(row: dict, veh: dict, make: str) -> bool:
    """Could this schedule row be the vehicle the claim names? Only a STATED
    difference rules a row out: another make, or another year. A row with no
    year (or no make - a VIN-only row) may be it. The same model in another
    year is not it: a fleet runs many vans of one model, so a 2016 Express
    beside a schedule of 2013 / 2015 / 2017 Expresses is a unit the schedule
    does not have - the contradiction Brent planted."""
    if row["make"] and not _same_make(make, row["make"]):
        return False
    return row["year"] is None or row["year"] == veh["year"]


def _vehicle_finding(rec: dict, schedule: List[dict]) -> Optional[str]:
    if not schedule:
        return None
    # A VIN is judged only when EVERY scheduled vehicle carries one: otherwise
    # the claim's VIN may be the un-VINned vehicle's.
    every_vin = all(v["vin"] for v in schedule)
    vins = {v["vin"] for v in schedule if v["vin"]}
    makes = {v["make"] for v in schedule if v["make"]}
    for veh in _claim_vehicles(rec):
        if veh["vin"]:
            if every_vin and veh["vin"] not in vins:
                return f"names VIN {veh['vin']}, which is not on the vehicle schedule"
            continue
        make = _make_key(veh["make"])
        if not any(_same_make(make, mk) for mk in makes):
            continue                     # not a make the schedule prints: cannot tell
        if any(_could_be(row, veh, make) for row in schedule):
            continue
        who = _unit_label(veh["unit"]) if veh["unit"] else "its vehicle"
        return f"names {who} as a {veh['printed']}, which is not on the vehicle schedule"
    return None


# ── 6. The premises / building a claim names ────────────────────────────────
_PREMISES_WORD_RE = re.compile(r"(?<![A-Za-z])(?:prem(?:ises?)?|loc(?:ation)?|bldg|bld|building)\b", re.I)
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _label_parts(text: Any) -> Optional[dict]:
    try:
        from services.extraction_service import premises_label_parts
        return premises_label_parts(text)
    except Exception:                                          # noqa: BLE001
        return None


def _label_number(raw: Any) -> str:
    try:
        from services.extraction_service import _label_number as _ln
        return _ln(raw)
    except Exception:                                          # noqa: BLE001
        s = _text(raw)
        return str(int(s)) if s.isdigit() else s.upper()


def _premises_number(raw: Any) -> str:
    """A premises / building number, or "" - "0" / "000" is a loss run's
    policy-level code (no premises), never a building."""
    num = _label_number(raw)
    return "" if num == "0" else num


def _claim_premises(rec: dict) -> Optional[dict]:
    """{premises, building, printed} for the heading a claim prints, through
    the one premises-heading door (`extraction_service.premises_label_parts`):
    a field of its own, else a segment of the description that IS a heading -
    the premises word starts the segment ("Prem 001, Bldg 003"). Review fix
    (21 Oct): the segment used to be read from the first premises word on, so
    "Slip and fall at customer location 3" read as premises 3."""
    loc, bldg = _premises_number(rec.get("location")), _premises_number(rec.get("building"))
    if loc or bldg:
        return {"premises": loc, "building": bldg, "explicit": True,
                "printed": ", ".join(p for p in (f"premises {_text(rec.get('location'))}" if loc else "",
                                                 f"building {_text(rec.get('building'))}" if bldg else "") if p)}
    for seg in re.split(r"[|;\n]", _text(rec.get("description"))):
        seg = _PARENTHETICAL_RE.sub(" ", seg).strip()
        if not _PREMISES_WORD_RE.match(seg):
            continue
        parts = _label_parts(seg)
        if not parts or parts.get("street"):
            continue
        loc, bldg = _premises_number(parts.get("premises")), _premises_number(parts.get("building"))
        if loc or bldg:
            printed = ", ".join(p for p in (f"premises {parts['premises']}" if loc else "",
                                            f"building {parts['building']}" if bldg else "") if p)
            return {"premises": loc, "building": bldg, "explicit": False, "printed": printed}
    return None


def _schedule_premises(facts: Any) -> List[Tuple[str, str]]:
    """(premises, building) for EVERY premises row - "" where the row prints no
    number. Review fix (21 Oct): an un-numbered row used to be dropped, so a
    claim naming the building that row is (its number not captured) read as
    "not on the schedule"."""
    rows = _fv(facts, "property_locations")
    out: List[Tuple[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not _states_something(row):
            continue
        loc = _premises_number(row.get("premises_number")) or _premises_number(row.get("location_number"))
        bldg = _premises_number(row.get("building_number"))
        if not (loc and bldg):
            parts = _label_parts(row.get("premises_label")) or _label_parts(row.get("address"))
            if parts and not parts.get("street"):
                loc = loc or _premises_number(parts.get("premises"))
                bldg = bldg or _premises_number(parts.get("building"))
        out.append((loc, bldg))
    return out


def _premises_finding(rec: dict, schedule: List[Tuple[str, str]], family: Optional[str]) -> Optional[str]:
    """A premises / building the schedule does not have. A heading read from
    the description is judged on a PROPERTY claim only (a liability claim's
    "Loc 5" is as often a jobsite as a scheduled premises); a claim's own
    location / building fields on any line. A number is "not on the schedule"
    only when every row it could be prints that number: a building is judged
    against the rows at its premises (or with no premises number), each of
    which must print a building number; a premises against rows that all
    print one."""
    if not schedule:
        return None
    claim = _claim_premises(rec)
    if not claim:
        return None
    if not claim["explicit"]:
        try:
            from services.lob_canon import PROPERTY
        except Exception:                                      # noqa: BLE001
            return None
        if family != PROPERTY:
            return None
    loc, bldg = claim["premises"], claim["building"]
    if bldg:
        at = [(l, b) for l, b in schedule if not loc or not l or l == loc]
        if any(b == bldg for _l, b in at) or any(not b for _l, b in at):
            return None                  # on the schedule, or a row that may be it
    elif loc:
        if any(not l or l == loc for l, _b in schedule):
            return None
    else:
        return None
    return f"names {claim['printed']}, which is not on the premises schedule"


# ── 7. The WC class code a claim names ──────────────────────────────────────
_CLASS_LEAD_RE = re.compile(r"^\s*(\d{4})(?:-\d{1,2})?\s*(?:[|,;:/]|\s-\s|$)")
_CLASS_LABEL_RE = re.compile(r"\b(?:class(?:\s*code)?|code)\s*(?:#|no\.?)?\s*[:.]?\s*(\d{4})\b", re.I)


def _code4(val: Any) -> str:
    m = re.match(r"\s*(\d{4})", _text(val))
    return m.group(1) if m else ""


def _claim_class_code(rec: dict) -> str:
    code = _code4(rec.get("class_code"))
    if code:
        return code
    desc = _text(rec.get("description"))
    m = _CLASS_LABEL_RE.search(desc)
    if m:
        return m.group(1)
    m = _CLASS_LEAD_RE.match(desc)
    # A bare leading year ("2024 | fell from ladder") is never read as a code.
    if m and not (1900 <= int(m.group(1)) <= 2099):
        return m.group(1)
    return ""


def _schedule_class_codes(facts: Any) -> List[str]:
    rows = _fv(facts, "wc_class_codes")
    codes: List[str] = []
    for row in rows if isinstance(rows, list) else []:
        code = _code4(row.get("code") if isinstance(row, dict) else row)
        if code and code not in codes:
            codes.append(code)
    return codes


# ── The findings ────────────────────────────────────────────────────────────

def claim_ref(rec: dict) -> str:
    """How a finding names its claim, mid-sentence: its number and loss date,
    else "the <loss date> <line> claim"."""
    number = _text(rec.get("number"))
    state, parts = _date_cell(rec.get("loss_date"))
    when = _show_date(parts) if state == DATE else ""
    line = _text(rec.get("line"))
    if number and when:
        return f"{number} ({when})"
    if number:
        return number
    if when:
        return f"the {when} {line} claim" if line else f"the {when} claim"
    return f"a {line} claim with no loss date" if line else "a claim with no loss date"


def _finding(rec: dict, kind: str, check: str, text: str) -> dict:
    ref = claim_ref(rec)
    return {"kind": kind, "check": check, "claim": ref,
            "claim_number": _text(rec.get("number")) or None,
            "loss_date": _show_date(_date_cell(rec.get("loss_date"))[1]) or None,
            "text": text, "label": f"{ref[:1].upper()}{ref[1:]} {text}"}


def _columns_present(records: List[dict], field: str, reader) -> set:
    """The line groups in which some claim states `field` as a real value."""
    out = set()
    for rec in records:
        state, _v = reader(rec.get(field))
        if state in (DATE, AMOUNT):
            out.add(_group_key(rec))
    return out


def _incurred_finding(rec: dict) -> Optional[str]:
    if _text(rec.get("subrogation")).lower().startswith("y"):
        return None                      # in subrogation: incurred may be net of recovery
    rec_state, recovery = _amount_cell(rec.get("recovery"))
    if rec_state != BLANK and not (rec_state == AMOUNT and not recovery):
        return None                      # a recovery is shown: incurred may be net
    inc_s, incurred = _amount_cell(rec.get("incurred"))
    paid_s, paid = _amount_cell(rec.get("paid"))
    exp_s, expense = _amount_cell(rec.get("expense"))
    res_s, reserve = _amount_cell(rec.get("reserve"))
    if res_s == BLANK and rec.get("status") == "closed":
        res_s, reserve = AMOUNT, 0.0     # a closed claim holds no reserve
    if AMOUNT != inc_s or AMOUNT != paid_s or AMOUNT != exp_s or AMOUNT != res_s:
        return None                      # a part is not stated: nothing to add up
    full = paid + reserve + expense
    loss_only = paid + reserve
    if abs(incurred - full) <= _ROUNDING_PER_AMOUNT * 4 + 1e-9:
        return None
    if expense and abs(incurred - loss_only) <= _ROUNDING_PER_AMOUNT * 3 + 1e-9:
        return None                      # expense shown beside a loss-only incurred
    return (f"shows incurred {_money(incurred)}, but paid + reserve + expense is "
            f"{_money(full)}")


def claim_findings(facts: Any, flags: Any = None) -> List[dict]:
    """Every finding over the package's claims, in charging order: each
    {kind, check, claim, claim_number, loss_date, text, label}. Never raises."""
    try:
        return _claim_findings(facts)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("claim_checks: findings skipped: %s", exc, exc_info=True)
        return []


def _date_line_key(rec: dict) -> str:
    state, parts = _date_cell(rec.get("loss_date"), "date")
    if state != DATE:
        return ""
    return f"d:{_show_date(parts)}|{_claim_family(rec) or _group_key(rec)}"


def _claim_identities(records: List[dict]) -> List[str]:
    """One identity per record - the same claim held twice (a carrier loss run
    and an agency summary, an extracted row and a typed one, Brent's B2 file)
    shares it, so one fact is charged once (D69). The claim number, spelling-
    blind; else the loss date and the line FAMILY ("Auto" == "Business Auto");
    a numberless copy joins the ONE numbered claim of its date and line. A
    record with neither is its own claim. Never a comparison of the copies'
    values - only "is this the same claim?"."""
    keys: List[str] = []
    numbered: Dict[str, set] = {}
    for rec in records:
        number = re.sub(r"[^A-Z0-9]", "", _text(rec.get("number")).upper())
        dl = _date_line_key(rec)
        if number:
            keys.append(f"n:{number}")
            if dl:
                numbered.setdefault(dl, set()).add(f"n:{number}")
        else:
            keys.append(dl)
    out: List[str] = []
    for i, key in enumerate(keys):
        if not key:
            key = f"#{i}"
        elif key.startswith("d:") and len(numbered.get(key, ())) == 1:
            key = next(iter(numbered[key]))
        out.append(key)
    return out


def _table_is_persons(facts: Any) -> bool:
    """Did a person save the loss table as it stands? (`schedule_capture.
    human_rows`, the one record of that.)"""
    try:
        from services.schedule_capture import human_rows
        rows, _source = human_rows(facts, DEDUCTION_FACT)
        return rows is not None
    except Exception:                                          # noqa: BLE001
        return False


def _column_shown(rec: dict, groups: set) -> bool:
    return "*" in groups or _group_key(rec) in groups


def _claim_findings(facts: Any) -> List[dict]:
    records = claim_records(facts)
    if not records:
        return []
    try:
        from services.lob_canon import AUTO, PROPERTY, WORKERS_COMP
    except Exception:                                          # noqa: BLE001
        AUTO, PROPERTY, WORKERS_COMP = "auto", "property", "workers_comp"
    idents = _claim_identities(records)
    report_groups = _columns_present(records, "report_date", _date_cell)
    reserve_groups = _columns_present(records, "reserve", _amount_cell)
    # Review fix (21 Oct): a loss table a PERSON saved shows the column on
    # every row, so a blank there is judged over the whole table - not over
    # the claims of its line. Otherwise a "NOT PROVIDED" on a line's only
    # claim (Brent's SIM-CYB-001) was cleared by blanking the cell the date
    # check flags, though no date was ever supplied.
    if _table_is_persons(facts):
        report_groups = {"*"} if report_groups else report_groups
        reserve_groups = {"*"} if reserve_groups else reserve_groups
    # A claim held twice is missing a detail only when NO copy states it.
    report_stated = {k for rec, k in zip(records, idents)
                     if _date_cell(rec.get("report_date"), "claim_date")[0] == DATE}
    reserve_stated = {k for rec, k in zip(records, idents)
                      if _amount_cell(rec.get("reserve"))[0] == AMOUNT}
    terms: Dict[Optional[str], Optional[Tuple[date, date]]] = {}

    def _term(fam: Optional[str]) -> Optional[Tuple[date, date]]:
        if fam not in terms:
            terms[fam] = current_term(facts, fam)
        return terms[fam]

    vehicles = _schedule_vehicles(facts)
    premises = _schedule_premises(facts)
    codes = _schedule_class_codes(facts)
    found: List[Tuple[str, dict]] = []
    for rec, ident in zip(records, idents):
        def _add(kind: str, check: str, text: str) -> None:
            found.append((ident, _finding(rec, kind, check, text)))

        loss_s, loss = _date_cell(rec.get("loss_date"), "date")
        rep_s, rep = _date_cell(rec.get("report_date"), "claim_date")
        fm_s, fm = _date_cell(rec.get("first_made_date"), "first_made_date")
        # 1. dates out of order
        if loss_s == DATE and rep_s == DATE and _before(rep, loss):
            _add(CONFLICT, CHECK_REPORT_BEFORE_LOSS, f"was reported {_show_date(rep)}, before its loss date")
        if loss_s == DATE and fm_s == DATE and _before(fm, loss):
            _add(CONFLICT, CHECK_FIRST_MADE_BEFORE_LOSS, f"was first made {_show_date(fm)}, before its loss date")
        # 4. incurred against its parts
        text = _incurred_finding(rec)
        if text:
            _add(CONFLICT, CHECK_INCURRED_MISMATCH, text)
        # 5-7. against the package's schedules, inside the term of the line
        #      the schedule describes
        family = _claim_family(rec)
        if vehicles and family in (AUTO, None) and _in_term(rec, _term(AUTO)):
            text = _vehicle_finding(rec, vehicles)
            if text:
                _add(CONFLICT, CHECK_VEHICLE_NOT_SCHEDULED, text)
        if premises and _in_term(rec, _term(family or PROPERTY)):
            text = _premises_finding(rec, premises, family)
            if text:
                _add(CONFLICT, CHECK_BUILDING_NOT_SCHEDULED, text)
        if codes and family == WORKERS_COMP and _in_term(rec, _term(WORKERS_COMP)):
            code = _claim_class_code(rec)
            if code and code not in codes:
                _add(CONFLICT, CHECK_CLASS_NOT_SCHEDULED,
                     f"shows class code {code}, which is not on the workers comp class "
                     f"schedule ({', '.join(codes[:5])})")
        # 2. dates written as not provided. A blank report date counts only
        #    where the claims of its line carry report dates, and only when no
        #    copy of the claim states one. "N/A" / "None" answer a first-made
        #    date or a reserve, never a report date (every claim was reported):
        #    it is read like a blank (review fix, 21 Oct).
        if rep_s == PLACEHOLDER or (rep_s in (BLANK, NONE_STATED) and _column_shown(rec, report_groups)
                                    and ident not in report_stated):
            _add(MISSING, CHECK_REPORT_DATE_MISSING, "has no report date")
        if fm_s == PLACEHOLDER:
            _add(MISSING, CHECK_FIRST_MADE_MISSING, "has no date first made")
        # 3. an open claim with no reserve
        res_s, _res = _amount_cell(rec.get("reserve"))
        if rec.get("status") == "open" and (
                res_s == PLACEHOLDER or (res_s == BLANK and _column_shown(rec, reserve_groups)
                                         and ident not in reserve_stated)):
            _add(MISSING, CHECK_RESERVE_MISSING, "is open with no reserve")
    # One finding per claim and check (D69): the same claim held twice is one
    # claim, so its finding is listed and charged once.
    seen: set = set()
    unique: List[dict] = []
    for ident, finding in found:
        if (ident, finding["check"]) in seen:
            continue
        seen.add((ident, finding["check"]))
        unique.append(finding)
    order = {c: i for i, c in enumerate(_CHECK_ORDER)}
    return sorted(unique, key=lambda f: order.get(f["check"], len(order)))


# ── The deductions ──────────────────────────────────────────────────────────

def _allocate(n: int, per: int, cap: int) -> List[int]:
    """Points per finding: `per` each, the kind capped at `cap`, shared out
    evenly (the first findings take the remainder) so every finding the cap
    allows is charged and listed."""
    if n <= 0:
        return []
    total = min(int(cap), int(per) * n)
    base, extra = divmod(total, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def card_text(findings: List[dict]) -> str:
    """The Recommendations card's words: every claim to correct, then every
    claim to complete (up to `_NAMED_ON_CARD`, then a count)."""
    named = findings[:_NAMED_ON_CARD]
    parts = []
    for kind, lead in ((CONFLICT, "Correct these claims in the loss history"),
                       (MISSING, "Complete these claims in the loss history")):
        items = [f"{f['claim']} {f['text']}" for f in named if f["kind"] == kind]
        if items:
            parts.append(f"{lead}: " + "; ".join(items) + ".")
    more = len(findings) - len(named)
    if more > 0:
        parts.append(f"And {more} more {'claim' if more == 1 else 'claims'} to check.")
    return " ".join(parts)


def claim_deduction_items(facts: Any, flags: Any = None) -> List[dict]:
    """The pillar deductions (`sqs_service.coverage_deduction_items` adds
    them): one item per finding the cap charges - {bucket, points, fact,
    label, kind, row_action}. "conflict" items are Exposure Consistency's,
    "missing" items Completeness's; `fact` is the loss table, and every item
    carries the card's words (`row_action`) so whichever pillar's row the
    Recommendations section shows names every claim the table needs."""
    findings = claim_findings(facts, flags)
    if not findings:
        return []
    action = card_text(findings)
    items: List[dict] = []
    for kind, per, cap in ((CONFLICT, CLAIM_CONFLICT_POINTS, CLAIM_CONFLICT_CAP),
                           (MISSING, CLAIM_MISSING_POINTS, CLAIM_MISSING_CAP)):
        group = [f for f in findings if f["kind"] == kind]
        for finding, points in zip(group, _allocate(len(group), per, cap)):
            if points > 0:
                items.append({"bucket": DEDUCTION_BUCKET, "points": int(points),
                              "fact": DEDUCTION_FACT, "label": finding["label"],
                              "kind": kind, "row_action": action})
    return items
