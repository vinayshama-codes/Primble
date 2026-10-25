"""premises_cope.py - one building, one row: the package's COPE facts and the
location table (7 Oct 2026, Choice Electric #18).

Brent: *"this should have turned up TWO building property values"*. The
Minimum Viable / Carrier-Grade COPE cards ask ONE scalar per item - one
construction, one building value, one year built, one protection class - and
on a package with two buildings a single scalar can hold only one of them: it
prints on ACORD 140's first building block, and the second building's boxes
were left for gap fill (which copied the first building's answer) or the 140's
completeness gate (which hard-blocked the download).

The location table carries those answers per building (LOC # / BLDG # /
construction / year / values since 6 Oct; roof material / roof year /
protection class / sprinkler since 7 Oct), each column bound to its live ACORD
box. This module is the ONE map between the two vocabularies and the rules
that use it:

* ONE STORE (21 Oct 2026, Brent 17 Oct item 8). On a package with 2+ location
  rows a per-building COPE item is asked PER BUILDING, in the location table,
  wherever it is asked: the COPE cards (`route_cope_resolution`), the
  Recommendations rows and every stamped recommendation card
  (`per_building_fix`, read by `review_recommendations.fix_route_for_row` and
  `answer_routing.stamp_recommendation`). Brent answered six Property
  Integrity rows one package value at a time, then the COPE hard stop opened
  the table whose cells could not show those answers - asked twice. Never one
  answer for all buildings: the package fact follows the rows
  (`derive_package_cope`). Location-wide (hydrant, fire department) and
  package-level items (occupancy, valuation, coinsurance) stay typed fields.
* ASK ONLY WHAT IS MISSING (same day). A COPE card on 2+ buildings opens the
  table with the per-building items it still MISSES (each row named by its
  own identity cells, `show_columns`) and the package-level boxes it misses;
  with only package-level items missing it is a field window with just those
  boxes. A per-building fact is never one package box on such a package
  (round 4, 7 Oct: an occupancy-only field card printed building 1's
  construction and values as the package's). A one-building package is
  byte-identical.
* `derive_package_cope` - the table write door's half: once EVERY row states a
  column, an EMPTY package fact takes row 1's value (row 1 is the building ACORD
  prints in row A - the same value the form shows there), so the card the table
  answered clears and every scorer that reads the package fact agrees. A value
  this rule wrote is recomputed on every save and retracted when the rows no
  longer all state it; a stated or typed package fact is never touched.

Pure - no I/O. Never raises from its public functions.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LOCATION_LIST_KEY = "property_locations"

# Package COPE fact -> the location-table column that holds the same answer
# for ONE building. Every column is bound to a live ACORD 140 / 160 box
# (`pdf_service._SCHEDULE_REGISTRY`, pinned by
# tests/test_schedule_capture.py::test_every_schedule_column_binds_to_a_live_acord_field
# and by tests/test_choice_electric_dryrun_7oct.py).
PER_BUILDING_COPE: Dict[str, str] = {
    "construction_type":       "construction_type",
    "property_building_value": "building_value",
    "property_bpp_value":      "bpp_value",
    "year_built":              "year_built",
    "roof_year":               "roof_year",
    "sprinkler_system":        "sprinkler",
    "fire_protection_class":   "protection_class",
}

# Facts a card treats as ONE item: either one satisfies it (spec 3.3 Minimum
# Viable COPE: "Building value OR required Business Personal Property value").
_EITHER_GROUPS = (frozenset({"property_building_value", "property_bpp_value"}),)

# The COPE cards whose fix mixes per-building and package-level facts - the
# cross-form codes and their legacy twins from `sqs_service.evaluate_stops`.
COPE_CARD_CODES = frozenset({
    "minimum_viable_cope_missing", "legacy_minimum_viable_cope",
    "carrier_grade_cope_incomplete", "legacy_carrier_grade_cope",
})

# The COPE card whose rule reads the ROWS themselves ("N of M insured locations
# are missing construction type or building/BPP value",
# `cross_form_validator._check_per_location_cope_completeness`) - Minimum Viable
# COPE's per-building part, per building. It already opens the table; on 21 Oct
# it asks only the columns some building lacks.
PER_LOCATION_CARD_CODES = frozenset({"per_location_cope_incomplete"})

DERIVATION_RULE = "premises_rows"


# ── Reading ──────────────────────────────────────────────────────────────────

def _value(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _stated(value: Any) -> bool:
    if value is None or isinstance(value, (list, dict)):
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in ("null", "none")


def location_rows(facts: Any) -> List[dict]:
    """The location table's rows (dict rows only), envelope unwrapped."""
    if not isinstance(facts, dict):
        return []
    rows = _value(facts.get(LOCATION_LIST_KEY))
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


# The cells that never make a row a building on their own: the numbering the
# agency (or `assign_location_numbers`) gives every row, stub or not.
_NUMBERING_COLUMNS = frozenset({"location_number", "building_number"})


def building_columns() -> List[str]:
    """The location-table columns whose value makes a row a BUILDING: every
    column of the table (`schedule_capture.SCHEDULE_DEFS`) except its LOC # /
    BLDG # numbering. Declared once here; the windows ship it to the frontend
    (`building_columns`, `fixProgress.rowNeedsSummary`)."""
    try:
        from services.schedule_capture import get_def
        cols = [str(c.get("key")) for c in ((get_def(LOCATION_LIST_KEY) or {}).get("columns") or [])
                if isinstance(c, dict) and c.get("key")]
    except Exception:                                          # noqa: BLE001
        cols = []
    return [c for c in cols if c not in _NUMBERING_COLUMNS]


def is_building_row(row: Any, columns: Optional[List[str]] = None) -> bool:
    """THE ONE "is this row a building?" (21 Oct 2026, review M1): a row that
    states a value in one of the location table's own columns. A stub - `{}`,
    `{"location_id": "L2"}`, a county or a LOC # alone - is not a building:
    every gate here, the windows' building count, `derive_package_cope`'s
    "every building" and the frontend's Save progress read this one rule."""
    if not isinstance(row, dict):
        return False
    cols = columns if columns is not None else building_columns()
    if not cols:                       # the table is unreadable: anything stated
        return any(not str(k).startswith("_") and k not in _NUMBERING_COLUMNS and _stated(v)
                   for k, v in row.items())
    return any(_stated(row.get(c)) for c in cols)


def building_rows(facts: Any) -> List[dict]:
    """The location rows that are buildings (`is_building_row`), in order."""
    cols = building_columns()
    return [r for r in location_rows(facts) if is_building_row(r, cols)]


def building_row_count(facts: Any) -> int:
    return len(building_rows(facts))


def _buildings_text(n: int) -> str:
    return f"{n} building" + ("" if n == 1 else "s")


def fact_stated(facts: Any, key: str) -> bool:
    """Is this package fact stated - the presence test the COPE rules apply
    (`sqs_service.evaluate_stops`, `cross_form_validator`)?"""
    if not isinstance(facts, dict):
        return False
    return _stated(_value(facts.get(key)))


def _missing(facts: dict, asked: List[str]) -> List[str]:
    """The facts of `asked` the card still misses, an either-or group counted
    once (missing only when NO member is stated)."""
    out: List[str] = []
    for key in asked:
        group = next((g for g in _EITHER_GROUPS if key in g), None)
        if group is not None:
            if any(fact_stated(facts, k) for k in group if k in asked):
                continue
        elif fact_stated(facts, key):
            continue
        out.append(key)
    return out


# ── The windows ──────────────────────────────────────────────────────────────

def _group_of(fact: str) -> Optional[frozenset]:
    return next((g for g in _EITHER_GROUPS if fact in g), None)


def _item_facts(fact: str) -> List[str]:
    """The package facts that make ONE item: an either-or group's members (map
    order - building before BPP), else the fact itself."""
    group = _group_of(fact)
    return [k for k in PER_BUILDING_COPE if k in group] if group else [fact]


def _columns_of(per_facts: List[str]) -> List[str]:
    cols: List[str] = []
    for f in per_facts:
        col = PER_BUILDING_COPE.get(f)
        if col and col not in cols:
            cols.append(col)
    return cols


def _row_groups(per_facts: List[str]) -> List[List[str]]:
    """Each asked item's column(s) as ONE group every building row must state
    (an either-or item: either column) - the window's `row_needs`, so it says
    "Save progress" while a building lacks one (13 Oct 2026). The package fact
    follows the rows only once EVERY row states it (`derive_package_cope`), so
    a full set of rows is exactly when the item is answered."""
    groups: List[List[str]] = []
    for f in per_facts:
        if f not in PER_BUILDING_COPE:
            continue
        cols = _columns_of(_item_facts(f))
        if cols and cols not in groups:
            groups.append(cols)
    return groups


def _identity_columns() -> List[str]:
    """The cells that name a row as ITS building: the location table's own
    duplicate signature (`schedule_capture.SCHEDULE_DEFS[...]["dedup_keys"]` -
    street, suite, city, LOC #, BLDG #). Read, never restated here."""
    try:
        from services.schedule_capture import get_def
        return [str(k) for k in ((get_def(LOCATION_LIST_KEY) or {}).get("dedup_keys") or [])]
    except Exception:                                          # noqa: BLE001
        return []


def _shown_columns(rows: List[dict], columns: List[str]) -> List[str]:
    """What the window's table shows: the identity cells some row fills (a
    redacted street names no building and is left out), then the asked
    columns - never the other fifteen columns of the location table."""
    ident = [c for c in _identity_columns()
             if c not in columns and any(_stated(r.get(c)) for r in rows)]
    return ident + list(columns)


# The keys a window built here owns - never carried over from the resolution it
# is built from, so a descriptor routed twice can never keep a stale one.
_WINDOW_KEYS = frozenset({"columns", "row_needs", "derives", "show_columns", "per_building",
                          "note", "confirm_columns", "building_columns"})


def _table_window(base: dict, per_facts: List[str], package_level: List[str],
                  facts: dict) -> dict:
    """The location-table window asking `per_facts` per building, with the
    `package_level` boxes above it. `base`'s other keys ride along - a card's
    declared `needs` keeps naming what its fix writes
    (`needs_attention.issue_fix_keys`); the modal reads `needs` only in field
    mode. Never mutates `base`."""
    columns = _columns_of(per_facts)
    built = building_rows(facts)
    buildings = len(built)
    # Cells every building already states: only a SAVE of the table carries
    # them to the submission (`derive_package_cope`), so the window saves the
    # table even when only a box above it was typed (frontend `tableIsSaved`).
    confirm = [c for c in columns if built and all(_stated(r.get(c)) for r in built)]
    out = {k: copy.deepcopy(v) for k, v in base.items()
           if k not in ("mode", "facts", "controls") and k not in _WINDOW_KEYS}
    out.update({
        "mode": "schedule", "schedule_key": LOCATION_LIST_KEY,
        "columns": columns,
        "row_needs": _row_groups(per_facts),
        # The package facts these cells answer once every building states them
        # - the window's targets beside its cells (frontend `fixKeys`), so a
        # form box or a row asking the same fact is the same to-do.
        "derives": [f for f in per_facts if f in PER_BUILDING_COPE],
        "show_columns": _shown_columns(built, columns),
        # What makes a row a building (`is_building_row`) - the window's Save
        # progress counts the same rows the package fact is derived from.
        "building_columns": building_columns(),
        "per_building": True,
        "note": (f"This package has {_buildings_text(buildings)} - "
                 "check or enter each building's values in its own row."),
    })
    if confirm:
        out["confirm_columns"] = confirm
    if package_level:
        out["facts"] = list(package_level)
        controls = base.get("controls") or {}
        picked = {f: copy.deepcopy(controls[f]) for f in package_level if f in controls}
        if picked:
            out["controls"] = picked
    return out


def _fields_window(base: dict, package_level: List[str]) -> dict:
    """A field window with just the package-level boxes still missing. Its
    `needs` keep only the groups those boxes answer; one group is dropped - a
    single box has no partial state to save (`fixProgress.stillMissing`)."""
    out = {k: copy.deepcopy(v) for k, v in base.items()
           if k not in ("facts", "controls", "needs", "schedule_key") and k not in _WINDOW_KEYS}
    out["mode"] = "field"
    out["facts"] = list(package_level)
    controls = base.get("controls") or {}
    picked = {f: copy.deepcopy(controls[f]) for f in package_level if f in controls}
    if picked:
        out["controls"] = picked
    needs = [list(g) for g in (base.get("needs") or [])
             if g and all(str(f) in package_level for f in g)]
    if len(needs) > 1:
        out["needs"] = needs
    return out


def per_building_fix(fact: Any, facts: Any) -> Optional[dict]:
    """The window that asks ONE per-building COPE item on THIS package - for a
    Recommendations row or a recommendation card (see the module note). On 2+
    location rows: the location table with the item's column(s), one row per
    building. None on any other fact or package: the item keeps its own typed
    box (one building stays byte-identical)."""
    try:
        key = str(fact or "").strip()
        if key not in PER_BUILDING_COPE or not isinstance(facts, dict):
            return None
        if building_row_count(facts) < 2:
            return None
        return _table_window({}, _item_facts(key), [], facts)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("premises_cope: per-building route skipped for %s: %s", fact, exc)
        return None


def _per_location_groups() -> List[List[str]]:
    """Minimum Viable COPE's per-building part as column groups - what the
    per-location card checks on every row (a construction, and a building OR
    BPP value). Read off the Minimum Viable card's declared `needs`
    (`issue_registry._MIN_COPE_NEEDS`), never restated here."""
    try:
        from services.issue_registry import resolution_for
        needs = (resolution_for("minimum_viable_cope_missing") or {}).get("needs") or []
    except Exception:                                          # noqa: BLE001
        needs = []
    groups: List[List[str]] = []
    for group in needs:
        members = [str(f) for f in (group or [])]
        if members and all(f in PER_BUILDING_COPE for f in members):
            cols = _columns_of(members)
            if cols not in groups:
                groups.append(cols)
    return groups


def _route_per_location(resolution: dict, facts: dict) -> dict:
    """The per-location card's table, asking only the column groups some
    building lacks. Its own whole-table window when it is not the location
    table, when fewer than two rows are buildings, or when no building lacks
    anything (a stale card)."""
    if (resolution.get("mode") != "schedule"
            or str(resolution.get("schedule_key") or "") != LOCATION_LIST_KEY):
        return resolution
    rows = building_rows(facts)
    if len(rows) < 2:
        return resolution
    lacking = [g for g in _per_location_groups()
               if any(not any(_stated(r.get(c)) for c in g) for r in rows)]
    if not lacking:
        return resolution
    cols = {c for g in lacking for c in g}
    per_facts = [f for f, c in PER_BUILDING_COPE.items() if c in cols]
    return _table_window(resolution, per_facts, [], facts)


# ── The card ─────────────────────────────────────────────────────────────────

def route_cope_resolution(code: Any, resolution: Any, facts: Any) -> Any:
    """The fix a COPE card offers on THIS package (see the module note).

    On a package with 2+ location rows (Brent 17 Oct item 8, 21 Oct 2026):
      * the per-building items the card still MISSES are asked per building in
        the location table (`columns`, each row named by its identity cells),
        with the package-level items it misses as typed boxes above it;
      * with only package-level items missing (occupancy) it is a field window
        with just those boxes - no table, and never a per-building box (the
        round-4 defect: building 1's construction and values printed as the
        package's);
      * a per-building item already stated for the package is not asked again
        (Brent's six package answers, then the table: asked twice);
      * an item every building already states but the package does not still
        opens its column - only a save of the table carries it to the package,
        and a card must never be impossible to clear;
      * when the card fires on a value this reading counts as stated, it falls
        back to every per-building item it asks (the 7 Oct table) - never an
        empty window.
    The per-location card (`PER_LOCATION_CARD_CODES`) asks only the columns
    some building lacks (`_route_per_location`).

    Returns `resolution` itself whenever nothing changes (any other code, a
    non-field COPE card, fewer than two location rows, or a card that asks no
    per-building fact), so callers can apply it unconditionally."""
    try:
        code_s = str(code or "")
        if not isinstance(resolution, dict) or not isinstance(facts, dict):
            return resolution
        if code_s in PER_LOCATION_CARD_CODES:
            return _route_per_location(resolution, facts)
        if code_s not in COPE_CARD_CODES or resolution.get("mode") != "field":
            return resolution
        if building_row_count(facts) < 2:
            return resolution
        asked = [str(f) for f in (resolution.get("facts") or []) if f]
        per_asked = [f for f in asked if f in PER_BUILDING_COPE]
        if not per_asked:
            return resolution                       # nothing per building to ask
        missing = _missing(facts, asked)
        per_missing = [f for f in missing if f in PER_BUILDING_COPE]
        package_level = [f for f in missing if f not in PER_BUILDING_COPE]
        if not per_missing and not package_level:
            per_missing = per_asked                 # never an empty window
        if not per_missing:
            return _fields_window(resolution, package_level)
        return _table_window(resolution, per_missing, package_level, facts)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("premises_cope: card routing skipped for %s: %s", code, exc)
        return resolution


# ── The table write door ─────────────────────────────────────────────────────

def _is_ours(raw: Any) -> bool:
    return isinstance(raw, dict) and (raw.get("derivation") or {}).get("rule") == DERIVATION_RULE


def _either_picks(facts: dict, rows: List[dict]) -> set:
    """An either-or item (building OR BPP value) answered per building with
    neither column complete - building 1 states only a BPP value, building 2
    only a building value (21 Oct 2026, review L7). Every building states the
    item, so the member building 1 states takes building 1's value (the value
    ACORD prints in row A) and the item the rule reads is answered. Never when
    a member is already stated or typed for the package, or a member column is
    complete (that column derives on its own)."""
    out: set = set()
    if not rows:
        return out
    for group in _EITHER_GROUPS:
        members = [f for f in PER_BUILDING_COPE if f in group]
        cols = [PER_BUILDING_COPE[f] for f in members]
        if any(all(_stated(r.get(c)) for r in rows) for c in cols):
            continue
        if any(_stated(_value(facts.get(f))) and not _is_ours(facts.get(f)) for f in members):
            continue
        if not all(any(_stated(r.get(c)) for c in cols) for r in rows):
            continue
        pick = next((f for f in members if _stated(rows[0].get(PER_BUILDING_COPE[f]))), None)
        if pick:
            out.add(pick)
    return out


def derive_package_cope(facts: dict, source: str = "producer") -> List[str]:
    """Bring the package COPE facts in line with the saved location table, in
    place (see the module note). Returns the fact keys this rule RETRACTED (a
    value it wrote earlier that the rows no longer support).

    A retraction is an EMPTY envelope that keeps this rule's marker (value None,
    `value_state: not_stated`), never a deleted key: the session's facts write
    is additive (`session_repository.resolve_facts_write` skips a missing or
    None value, but writes an envelope), so the producer's save and the client
    questionnaire's apply both store it with no extra plumbing, and the next
    save may derive the fact again.

    Only ever writes an EMPTY fact or one it wrote itself."""
    retracted: List[str] = []
    try:
        if not isinstance(facts, dict):
            return retracted
        # EVERY BUILDING, never every row (21 Oct 2026, review M1): a stub row
        # (`{}`, a bare id) is not a building and never holds the fact back.
        rows = building_rows(facts)
        picked = _either_picks(facts, rows)
        for fact, column in PER_BUILDING_COPE.items():
            current = facts.get(fact)
            ours = _is_ours(current)
            if not ours and _stated(_value(current)):
                continue                      # a stated or typed value stands
            cells = [r.get(column) for r in rows]
            complete = (bool(rows) and all(_stated(c) for c in cells)) or fact in picked
            if complete:
                value = str(cells[0]).strip()
                if ours and str(_value(current) or "").strip() == value:
                    continue
                facts[fact] = {
                    "value": value,
                    "source": source or "producer",
                    "confidence": "filled",
                    "value_state": "present",
                    "derivation": {"rule": DERIVATION_RULE,
                                   "inputs": [f"{LOCATION_LIST_KEY}[*].{column}"],
                                   "row": 1},
                }
                logger.info("premises_cope: %s = %r from the location table (every "
                            "row states %s)", fact, value, column)
            elif ours and _stated(_value(current)):
                facts[fact] = {
                    "value": None,
                    "source": source or "producer",
                    "confidence": "filled",
                    "value_state": "not_stated",
                    "derivation": {"rule": DERIVATION_RULE,
                                   "inputs": [f"{LOCATION_LIST_KEY}[*].{column}"],
                                   "retracted": True},
                }
                retracted.append(fact)
                logger.info("premises_cope: %s retracted - the location table no "
                            "longer states %s on every row", fact, column)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("premises_cope: package COPE derivation skipped: %s", exc)
    return retracted


# ── The client questionnaire: one question per building (22 Oct 2026) ───────
# The same shape as `premises_interest.location_field`: "year_built@loc2" is
# the year built of the SECOND `property_locations` row (its 1-based position
# in the stored list). Asked only on a package with 2+ building rows; the
# answer is a cell of that row, never the package fact.
_BUILDING_FIELD_RE = re.compile(
    r"^(" + "|".join(re.escape(f) for f in PER_BUILDING_COPE) + r")@loc(\d{1,3})$")


def building_field(fact: str, position: int) -> str:
    return f"{fact}@loc{int(position)}"


def parse_building_field(field_name: Any) -> Optional[Tuple[str, int]]:
    """(package COPE fact, 1-based row position) for a per-building field."""
    m = _BUILDING_FIELD_RE.match(str(field_name or ""))
    if not m or int(m.group(2)) < 1:
        return None
    return m.group(1), int(m.group(2))


def building_positions(facts: Any) -> List[Tuple[int, dict]]:
    """(1-based position in the stored list, row) for every building row."""
    if not isinstance(facts, dict):
        return []
    rows = _value(facts.get(LOCATION_LIST_KEY))
    if not isinstance(rows, list):
        return []
    cols = building_columns()
    return [(i + 1, r) for i, r in enumerate(rows) if is_building_row(r, cols)]


def write_building_answer(facts: dict, fact: str, position: int, value: Any,
                          source: str = "client_arq") -> bool:
    """Write one per-building answer onto its row's COPE cell (mirrors
    `premises_interest.write_location_answer`). True when the row changed. A
    non-answer ("not sure") writes nothing; "None" writes nothing for a value
    (there is nothing to print), and Yes / No are written as said."""
    try:
        column = PER_BUILDING_COPE.get(str(fact or ""))
        if not column or not isinstance(facts, dict):
            return False
        held = facts.get(LOCATION_LIST_KEY)
        rows = _value(held)
        idx = int(position) - 1
        if not isinstance(rows, list) or not (0 <= idx < len(rows)) or not isinstance(rows[idx], dict):
            return False
        raw = _value(value)
        text = "" if raw is None or isinstance(raw, (list, dict)) else str(raw).strip()
        if not text:
            return False
        from services.answer_semantics import VALUE, interpret_answer
        got = interpret_answer(fact, text)
        if got.intent == VALUE:
            text = str(got.value or text).strip()
        elif text.lower() not in ("yes", "no"):
            return False
        row = dict(rows[idx])
        if str(row.get(column) or "").strip() == text:
            return False
        row[column] = text
        new_rows = list(rows)
        new_rows[idx] = row
        facts[LOCATION_LIST_KEY] = ({**held, "value": new_rows}
                                    if isinstance(held, dict) and "value" in held else new_rows)
        try:
            from services.schedule_capture import refresh_human_mark
            refresh_human_mark(facts, LOCATION_LIST_KEY, source)
        except Exception:                                      # noqa: BLE001
            pass
        return True
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("premises_cope: building answer %s@loc%s skipped: %s", fact, position, exc)
        return False
