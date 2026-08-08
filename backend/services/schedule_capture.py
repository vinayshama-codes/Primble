"""
Bulk schedule capture (Beta Report Figure 15 — "many vehicle detail questions").

Problem this solves
-------------------
ACORD forms carry repeating rows (vehicles, drivers, locations, class codes,
loss runs, ...). Before this module, `arq_service.generate_arq_questions` turned
EVERY empty repeating-row field into its own client question, ordinal-labelled
via `_group_label`/`_ordinal`. A single ACORD 127 produced ~140 "Please provide
the following details for this vehicle ... (141th vehicle)" cards — the exact
failure the client reported. The ordinal counted FIELDS, not vehicles, so the
number was wrong as well as unusable.

Design
------
The data model was already schedule-shaped: `pdf_service._SCHEDULE_REGISTRY`
binds each repeating ACORD field (e.g. `Vehicle_Year_B`) to a list-backed fact
(`auto_vin_schedule[1]["year"]`). Nothing about the stamping pipeline needed to
change — only the CAPTURE side. So this module:

  * declares, per list-backed fact, the client-facing shape of ONE row
    (`SCHEDULE_DEFS`: columns, types, dedup keys, labels);
  * collapses every repeating field of a given schedule into ONE question of
    `field_type == "schedule"` (see `arq_service`), rendered by the frontend as
    a single editable table with CSV/XLSX import;
  * validates rows (per-cell, per-row) and flags duplicates;
  * round-trips through the EXISTING answer pipeline by serialising rows to a
    JSON string under a reserved `schedule::<list_key>` answer key, so no
    database column, no new answer plumbing, and no change to how scalar
    answers behave.

On apply, rows are written straight back to `facts[list_key]` as a plain list —
which is exactly what `pdf_service._resolve_schedule_row` already reads (via
`_fv`, which transparently unwraps fact envelopes). The full list is always
retained in facts even when it is longer than the form has physical rows; see
`ROW_CAPACITY` / `overflow_count` for how that is surfaced rather than silently
dropped.

Everything here is pure Python with no LLM and no I/O, so it is cheap to call
on every question-generation pass and trivially unit-testable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reserved answer-key namespace. A questionnaire answer whose key starts with
# this prefix carries a JSON-encoded list of rows rather than a scalar string.
ANSWER_PREFIX = "schedule::"

# Number of physical repeating rows the ACORD AcroForms expose (A..N — see
# `pdf_service._ROW_LETTER_TO_IDX`). Rows beyond this are still stored in facts
# (lossless) but cannot be stamped onto the form itself.
ROW_CAPACITY = 14

# Hard safety bounds. A 143-vehicle fleet — the case in the bug report — fits
# comfortably; these exist to bound a malicious or runaway payload.
MAX_ROWS = 500
MAX_CELL_LEN = 200


# ---------------------------------------------------------------------------
# Column + schedule definitions
# ---------------------------------------------------------------------------

class Column(dict):
    """One cell definition. `dict` subclass so it serialises to JSON directly."""

    def __init__(
        self,
        key: str,
        label: str,
        type: str = "text",
        required: bool = False,
        placeholder: str = "",
        width: int = 0,
    ):
        super().__init__(
            key=key, label=label, type=type, required=required,
            placeholder=placeholder, width=width,
        )


class ScheduleDef(dict):
    """Client-facing shape of one repeating schedule."""

    def __init__(
        self,
        list_key: str,
        label: str,
        singular: str,
        columns: List[Column],
        dedup_keys: Tuple[str, ...] = (),
        scalar_key: Optional[str] = None,
        vin_decode: bool = False,
    ):
        super().__init__(
            list_key=list_key, label=label, singular=singular,
            columns=columns, dedup_keys=list(dedup_keys),
            scalar_key=scalar_key, vin_decode=vin_decode,
        )


# Column sets mirror the sub_keys actually bound in
# `pdf_service._SCHEDULE_REGISTRY`. Deliberately NOT collecting fields that have
# no ACORD binding — data captured with nowhere to land is a loose end, not a
# feature.
SCHEDULE_DEFS: Dict[str, ScheduleDef] = {
    "auto_vin_schedule": ScheduleDef(
        list_key="auto_vin_schedule",
        label="Vehicle schedule",
        singular="vehicle",
        vin_decode=True,
        dedup_keys=("vin",),
        columns=[
            Column("year",       "Year",       "year",  required=True, placeholder="2021", width=80),
            Column("make",       "Make",       "text",  required=True, placeholder="Ford", width=120),
            Column("model",      "Model",      "text",  required=True, placeholder="F-150", width=120),
            Column("vin",        "VIN",        "vin",   placeholder="1FTFW1ET5DFC10312", width=190),
            Column("body_type",  "Body type",  "text",  placeholder="Pickup", width=110),
            Column("gvw",        "GVW",        "text",  placeholder="6,500", width=90),
            # Covered-auto symbols (2026-08-07). Bound to the real ACORD 127
            # fields Vehicle_ComprehensiveSymbolCode / Vehicle_CollisionSymbolCode
            # - the only symbol boxes that form has. Optional on purpose: a
            # declarations page normally states ONE symbol per coverage for the
            # whole schedule, which pdf_service inherits into every row, so these
            # only need filling when a fleet genuinely varies by vehicle.
            Column("comp_symbol", "Comp symbol",      "text", placeholder="7", width=110),
            Column("coll_symbol", "Collision symbol", "text", placeholder="7", width=125),
        ],
    ),
    "auto_drivers": ScheduleDef(
        list_key="auto_drivers",
        label="Driver schedule",
        singular="driver",
        dedup_keys=("name", "dob"),
        columns=[
            Column("name",             "Full name",        "text",    required=True, placeholder="Jane Smith", width=160),
            Column("dob",              "Date of birth",    "date",    placeholder="05/14/1985", width=120),
            Column("license_number",   "License #",        "text",    placeholder="D1234567", width=140),
            Column("license_state",    "License state",    "state",   placeholder="TX", width=95),
            Column("hire_date",        "Date hired",       "date",    placeholder="01/10/2020", width=120),
            Column("experience_years", "Years experience", "number",  placeholder="8", width=110),
        ],
    ),
    "property_locations": ScheduleDef(
        list_key="property_locations",
        label="Location schedule",
        singular="location",
        dedup_keys=("address_line1", "address_city"),
        columns=[
            Column("address_line1",          "Street address", "text",  required=True, placeholder="789 Commerce Dr", width=210),
            Column("address_city",           "City",           "text",  placeholder="Houston", width=130),
            Column("address_state",          "State",          "state", placeholder="TX", width=90),
            Column("address_zip",            "ZIP",            "text",  placeholder="77001", width=100),
            Column("operations_description", "What happens here", "text", placeholder="Warehouse and dispatch", width=220),
        ],
    ),
    "loss_history": ScheduleDef(
        list_key="loss_history",
        label="Loss history / claims",
        singular="claim",
        dedup_keys=("date", "description"),
        columns=[
            Column("date",             "Date of loss",  "date",     required=True, placeholder="03/15/2022", width=120),
            Column("line_of_business", "Line",          "text",     placeholder="General Liability", width=150),
            Column("description",      "What happened", "text",     required=True, placeholder="Slip and fall at job site", width=240),
            Column("paid",             "Amount paid",   "currency", placeholder="$8,500", width=125),
            Column("reserved_amount",  "Amount reserved", "currency", placeholder="$2,000", width=135),
        ],
    ),
}
# NOTE: only schedules with LIVE bindings in `pdf_service._SCHEDULE_REGISTRY`
# (verified field-by-field against all 17 real schemas on 2026-07-21) are
# defined here. wc_class_codes / wc_officers / underlying_policies /
# prior_coverage_by_line / inland_marine_items / additional_named_insureds are
# registered in pdf_service but every one of their entries matches ZERO real
# schema field, so a capture table for them could never stamp anything. They are
# deliberately omitted rather than shipped as tables that quietly discard input.
# Adding one back is a two-line change once its ACORD field names are mapped.

# Curated `_FIELD_PREFIX_MAP` group labels (arq_service) → schedule list key.
# These cover questions generated from the curated prefix map rather than from a
# raw ACORD schema field, so both generation paths collapse identically.
GROUP_LABEL_TO_LIST_KEY: Dict[str, str] = {
    "vehicle":  "auto_vin_schedule",
    "driver":   "auto_drivers",
    "location": "property_locations",
    "claim":    "loss_history",
}


def get_def(list_key: str) -> Optional[ScheduleDef]:
    return SCHEDULE_DEFS.get(list_key)


def answer_key(list_key: str) -> str:
    return f"{ANSWER_PREFIX}{list_key}"


def is_schedule_answer_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith(ANSWER_PREFIX)


def list_key_from_answer_key(key: str) -> str:
    return key[len(ANSWER_PREFIX):] if is_schedule_answer_key(key) else ""


def schedule_list_key_for_field(field_name: str) -> Optional[str]:
    """Resolve a raw ACORD schema field (e.g. `Vehicle_Year_B`) to its list key.

    Delegates to `pdf_service`'s registry so detection can never drift from the
    stamping logic. Returns None when the field is not schedule-backed, or is
    schedule-backed by a list we do not (yet) capture as a table.
    """
    try:
        from services.pdf_service import _SCHED_ROW_RE, _SCHEDULE_REGISTRY
    except Exception as ex:  # pragma: no cover - defensive import guard
        logger.warning(f"schedule_capture: pdf_service import failed: {ex}")
        return None

    m = _SCHED_ROW_RE.match(field_name or "")
    if not m:
        return None
    base = m.group(1)
    defn = _SCHEDULE_REGISTRY.get(base)
    if defn is None:
        for prefix, d in _SCHEDULE_REGISTRY.items():
            if base == prefix or base.startswith(prefix + "_") or base.endswith("_" + prefix):
                defn = d
                break
    if defn is None:
        return None
    return defn.list_key if defn.list_key in SCHEDULE_DEFS else None


# ---------------------------------------------------------------------------
# VIN
# ---------------------------------------------------------------------------

# ISO 3779: 17 characters, and I / O / Q are never used (they are too easily
# confused with 1 / 0). Deliberately NOT enforcing the check digit — imported
# and pre-1981 VINs legitimately fail it, and rejecting a real vehicle is worse
# than accepting a typo the underwriter will catch.
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_vin(raw: Any) -> str:
    return re.sub(r"[\s\-]", "", str(raw or "")).upper()


def is_valid_vin(raw: Any) -> bool:
    return bool(_VIN_RE.match(normalize_vin(raw)))


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$|^\d{4}-\d{2}-\d{2}$")
_STATE_RE = re.compile(r"^[A-Za-z]{2}$")
_NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")


def _clean_cell(raw: Any) -> str:
    """Strip markup and clamp length. Mirrors `arq_routes._sanitize_str`."""
    if raw is None:
        return ""
    val = re.sub(r"<[^>]*>", "", str(raw))
    return val.strip()[:MAX_CELL_LEN]


def validate_cell(col: dict, value: str) -> str:
    """Return an error message for one cell, or "" when it is acceptable.

    An empty non-required cell is always acceptable: a partially known fleet is
    better captured than refused. Only REQUIRED emptiness and genuinely
    malformed values are reported.
    """
    val = (value or "").strip()
    ctype = col.get("type", "text")

    if not val:
        return f"{col['label']} is required" if col.get("required") else ""

    if ctype == "vin":
        if not is_valid_vin(val):
            return "VIN must be 17 characters (letters/numbers, no I, O or Q)"
    elif ctype == "year":
        if not _YEAR_RE.match(val):
            return f"{col['label']} must be a 4-digit year (e.g. 2021)"
    elif ctype == "date":
        if not _DATE_RE.match(val):
            return f"{col['label']} must be MM/DD/YYYY"
    elif ctype == "state":
        if not _STATE_RE.match(val):
            return f"{col['label']} must be a 2-letter state code"
    elif ctype in ("currency", "percent"):
        stripped = val.replace("$", "").replace(",", "").replace("%", "").strip()
        if not _NUMERIC_RE.match(stripped):
            return f"{col['label']} must be a number"
    return ""


def _dedup_signature(defn: ScheduleDef, row: dict) -> Optional[str]:
    """Identity of a row for duplicate detection, or None when unidentifiable.

    ALL of the schedule's dedup keys form one composite signature, and a row
    with none of them populated is not compared at all. Composite rather than
    first-key-wins because a false positive (telling someone two genuinely
    different vehicles are the same) is far more damaging than a false negative:
    a missed duplicate is a cosmetic annoyance, a wrongly-merged vehicle is lost
    coverage. Vehicles dedup on VIN alone, which is already exact.
    """
    parts = []
    populated = False
    for key in defn.get("dedup_keys") or []:
        raw = str(row.get(key) or "").strip()
        if raw:
            populated = True
        norm = normalize_vin(raw) if key == "vin" else re.sub(r"\s+", " ", raw).upper()
        parts.append(f"{key}={norm}")
    if not populated:
        return None
    return "|".join(parts)


def validate_rows(list_key: str, rows: Any) -> Tuple[List[dict], dict]:
    """Clean + validate a schedule.

    Returns `(clean_rows, report)`. Rows are ALWAYS returned (validation is
    advisory, never destructive) so a client can save a partially-complete fleet
    and come back to it — matching how scalar questionnaire answers behave.

    report = {
        "errors":     {row_index: {col_key: message}},
        "duplicates": [row_index, ...],       # 2nd+ occurrence of a signature
        "row_count":  int,
        "overflow":   int,                    # rows beyond ROW_CAPACITY
        "truncated":  bool,                   # rows dropped by MAX_ROWS
    }
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return [], {"errors": {}, "duplicates": [], "row_count": 0,
                    "overflow": 0, "truncated": False}

    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except Exception:
            rows = []
    if not isinstance(rows, list):
        rows = []

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    columns = defn["columns"]
    clean_rows: List[dict] = []
    errors: Dict[int, Dict[str, str]] = {}
    seen: Dict[str, int] = {}
    duplicates: List[int] = []

    for idx, raw_row in enumerate(rows):
        # Accept a bare string for scalar schedules (additional named insureds)
        # so an imported one-column CSV round-trips without special handling.
        if not isinstance(raw_row, dict):
            scalar_key = defn.get("scalar_key") or columns[0]["key"]
            raw_row = {scalar_key: raw_row}

        row: Dict[str, str] = {}
        row_errors: Dict[str, str] = {}
        for col in columns:
            val = _clean_cell(raw_row.get(col["key"]))
            if col["type"] == "vin" and val:
                val = normalize_vin(val)
            row[col["key"]] = val
            msg = validate_cell(col, val)
            if msg:
                row_errors[col["key"]] = msg

        # A row where the user typed nothing at all is dropped silently rather
        # than reported as N required-field errors (trailing blank rows are a
        # normal artifact of both the table UI and spreadsheet exports).
        if not any(row.values()):
            continue

        sig = _dedup_signature(defn, row)
        if sig is not None:
            if sig in seen:
                duplicates.append(len(clean_rows))
            else:
                seen[sig] = len(clean_rows)

        if row_errors:
            errors[len(clean_rows)] = row_errors
        clean_rows.append(row)

    return clean_rows, {
        "errors":     {str(k): v for k, v in errors.items()},
        "duplicates": duplicates,
        "row_count":  len(clean_rows),
        "overflow":   max(0, len(clean_rows) - ROW_CAPACITY),
        "truncated":  truncated,
    }


def rows_for_facts(list_key: str, rows: List[dict]) -> List[Any]:
    """Shape validated rows for `facts[list_key]`.

    Scalar schedules (whose `_SCHEDULE_REGISTRY` entry has `sub_key is None`)
    store plain strings, everything else stores dicts — matching exactly what
    `pdf_service._resolve_schedule_row` expects to read back.
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []
    scalar_key = defn.get("scalar_key")
    if scalar_key:
        return [str(r.get(scalar_key, "")) for r in rows if str(r.get(scalar_key, "")).strip()]
    return rows


def rows_from_facts(list_key: str, facts: dict) -> List[dict]:
    """Read `facts[list_key]` back into table rows (inverse of `rows_for_facts`).

    Tolerates the fact-envelope shape (`{"value": [...]}`) the extraction layer
    may produce, and normalises scalar lists back into single-column rows.
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []

    raw = (facts or {}).get(list_key)
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        return []

    scalar_key = defn.get("scalar_key") or defn["columns"][0]["key"]
    out: List[dict] = []
    for item in raw[:MAX_ROWS]:
        if isinstance(item, dict):
            out.append({c["key"]: _clean_cell(item.get(c["key"])) for c in defn["columns"]})
        else:
            row = {c["key"]: "" for c in defn["columns"]}
            row[scalar_key] = _clean_cell(item)
            out.append(row)
    return out


def encode_answer(rows: List[dict]) -> str:
    """Serialise rows for transport through the string-based answer pipeline."""
    return json.dumps(rows, separators=(",", ":"))


def decode_answer(raw: Any) -> List[dict]:
    """Inverse of `encode_answer`, tolerant of an already-decoded list."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Client-facing copy
# ---------------------------------------------------------------------------
# Plain language, no jargon, and no em-dashes (project UI copy rule).

_QUESTION_OVERRIDES = {
    "auto_vin_schedule": (
        "Please list the vehicles to be insured. Add one row per vehicle, or "
        "upload your existing vehicle list as a CSV or Excel file."
    ),
    "auto_drivers": (
        "Please list everyone who drives a business vehicle. Add one row per "
        "driver, or upload your driver list as a CSV or Excel file."
    ),
    "loss_history": (
        "Please list any insurance claims or losses from the past 5 years. Add "
        "one row per claim, or upload your loss runs as a CSV or Excel file. "
        "If you have had no claims, leave this empty."
    ),
    "property_locations": (
        "Please list every business location to be insured. Add one row per "
        "location, or upload your location list as a CSV or Excel file."
    ),
}

_HINT_OVERRIDES = {
    "auto_vin_schedule": (
        "The VIN is the 17-character number on the dashboard or the driver's "
        "door frame. Enter a VIN and we will fill in the year, make and model "
        "for you."
    ),
    "auto_drivers": (
        "Include anyone who drives a company vehicle, even occasionally."
    ),
    "loss_history": (
        "Your prior insurance company can provide loss runs if you do not have "
        "them handy."
    ),
}


def question_text(list_key: str) -> str:
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    if list_key in _QUESTION_OVERRIDES:
        return _QUESTION_OVERRIDES[list_key]
    return (
        f"Please provide your {defn['label'].lower()}. Add one row per "
        f"{defn['singular']}, or upload the list as a CSV or Excel file."
    )


def hint_text(list_key: str) -> str:
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    if list_key in _HINT_OVERRIDES:
        return _HINT_OVERRIDES[list_key]
    return f"Add as many {defn['singular']}s as you need. Blank rows are ignored."


def summarize(list_key: str, rows: List[dict]) -> str:
    """One-line human summary for producer-facing lists and activity logs."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    n = len(rows)
    if n == 0:
        return f"No {defn['singular']}s provided"
    noun = defn["singular"] if n == 1 else f"{defn['singular']}s"
    return f"{n} {noun}"
