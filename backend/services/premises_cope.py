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
box. This module is the ONE map between the two vocabularies and the two rules
that use it:

* `route_cope_resolution` - on a package with 2+ location rows, EVERY COPE
  card opens the location table (schedule mode) showing each building's
  values for the per-building items it asks about; the package-level facts it
  still misses (occupancy, valuation, coinsurance) ride along as typed fields.
  A per-building fact is never one package box there (round 4, 7 Oct: an
  occupancy-only card used to stay a field card and printed building 1's
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
from typing import Any, Dict, List, Optional

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


def building_row_count(facts: Any) -> int:
    return len(location_rows(facts))


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


# ── The card ─────────────────────────────────────────────────────────────────

def route_cope_resolution(code: Any, resolution: Any, facts: Any) -> Any:
    """The fix a COPE card offers on THIS package (see the module note).

    On a package with 2+ location rows EVERY COPE card opens the location
    table (owner, 7 Oct 2026 round 4 - Brent #18): the columns are every
    per-building item the card ASKS about, stated or not, so the person sees
    each building's own values instead of building 1's printed as "the"
    package value; the package-level items the card still misses (occupancy,
    valuation, coinsurance) ride along as typed fields. A per-building fact is
    never offered as one package box on such a package. (Round 3 kept an
    occupancy-only card in field mode - which showed building 1's construction
    and values as the package's; reversed.)

    Returns `resolution` itself whenever nothing changes (any other code, a
    non-field resolution, fewer than two location rows, or a card that asks
    no per-building fact), so callers can apply it unconditionally."""
    try:
        if (str(code or "") not in COPE_CARD_CODES or not isinstance(resolution, dict)
                or resolution.get("mode") != "field" or not isinstance(facts, dict)):
            return resolution
        if building_row_count(facts) < 2:
            return resolution
        asked = [str(f) for f in (resolution.get("facts") or []) if f]
        columns: List[str] = []
        for f in asked:
            col = PER_BUILDING_COPE.get(f)
            if col and col not in columns:
                columns.append(col)
        if not columns:
            return resolution                       # nothing per building to show
        missing = _missing(facts, asked)
        package_level = [f for f in missing if f not in PER_BUILDING_COPE]
        out = {k: copy.deepcopy(v) for k, v in resolution.items()
               if k not in ("mode", "facts", "controls")}
        # The card's declared box groups (issue_registry `needs`) as the COLUMN
        # groups every building row must state - "construction" and "building
        # or BPP value" - so the table window says "Save progress" while a row
        # lacks one (review, 13 Oct 2026). Package-level groups stay boxes.
        row_needs = []
        for group in (resolution.get("needs") or []):
            cols = [PER_BUILDING_COPE.get(str(f)) for f in (group or [])]
            if cols and all(cols):
                row_needs.append(list(dict.fromkeys(cols)))
        if row_needs:
            out["row_needs"] = row_needs
        out.update({"mode": "schedule", "schedule_key": LOCATION_LIST_KEY,
                    "columns": columns,
                    "note": (f"This package has {building_row_count(facts)} buildings - "
                             "check or enter each building's values in its own row.")})
        if package_level:
            out["facts"] = package_level
            controls = resolution.get("controls") or {}
            picked = {f: copy.deepcopy(controls[f]) for f in package_level if f in controls}
            if picked:
                out["controls"] = picked
        return out
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("premises_cope: card routing skipped for %s: %s", code, exc)
        return resolution


# ── The table write door ─────────────────────────────────────────────────────

def _is_ours(raw: Any) -> bool:
    return isinstance(raw, dict) and (raw.get("derivation") or {}).get("rule") == DERIVATION_RULE


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
        rows = location_rows(facts)
        for fact, column in PER_BUILDING_COPE.items():
            current = facts.get(fact)
            ours = _is_ours(current)
            if not ours and _stated(_value(current)):
                continue                      # a stated or typed value stands
            cells = [r.get(column) for r in rows]
            complete = bool(rows) and all(_stated(c) for c in cells)
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
