"""review_recommendations.py - the fix window behind each "Raise your score" row
on the package page's Recommendations section (Choice Electric #22 / #27,
7 Oct 2026).

Brent: *"All of these Recommendation items should be addressable prior to (and
independently of) the forms."* The rows are the package scorer's own Best
Solutions (`package_sqs["top_recommendations"]`) - the same rows the editor's
SQS panel lists - so this module adds nothing to the score and decides nothing
about which gaps exist. It only attaches, to each row a person can answer, the
`resolution` descriptor the page's one fix window (ResolutionModal) opens:

* the row's answer mode is the one `answer_routing` already stamped on it
  (`_route_recommendations`); a row from an older payload is routed here by the
  same door;
* field mode goes through `issue_registry.field_resolution`, so the window
  offers the same choices (`controls`) a hard stop or warning on that fact
  offers;
* a live capture table opens the table; the ACORD 101 remarks open the remarks
  box (the only fact the narrative write appends to); any other prose fact is
  typed like a field;
* a per-building COPE fact on a package with 2+ location rows opens the
  location table with its column (`premises_cope.per_building_fix`, 21 Oct
  2026 - Brent 17 Oct item 8: one store for building details);
* a row with no route (mode `none`, no field, the synthetic "hard stops need
  attention" row) gets no resolution - the page does not list it.

Which rows the page shows, and which are already on a Hard Stop / Warning card
or a key-details link (one to-do, one place), is decided on the page from what
it renders (`frontend/src/utils/recommendations.js`) - the cards change on every
fix and this payload does not travel with all of them.

Pure: never mutates its input (the persisted package is returned by
`current_package_sqs` once forms exist), never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The synthetic Best Solutions row that restates the hard stops - they have
# their own section and cards.
HARD_STOPS_ROW = "hard_stops_present"


def _narrative_field() -> str:
    try:
        from services.arq_service import NARRATIVE_ANSWER_FIELD
        return str(NARRATIVE_ANSWER_FIELD)
    except Exception:                                          # noqa: BLE001
        return "additional_remarks_text"


def fix_route_for_row(row: Any, facts: Optional[dict] = None) -> Optional[dict]:
    """The ResolutionModal descriptor for one Best Solutions row, or None."""
    if not isinstance(row, dict) or row.get("pillar") == HARD_STOPS_ROW:
        return None
    field = str(row.get("field") or "").strip()
    if not field:
        return None
    # A merged sub-point row (review_plan.merge_subpoint_rows): one window, all its questions.
    merged = [str(f) for f in (row.get("merged_fields") or []) if str(f or "").strip()]
    if len(merged) > 1:
        from services.review_plan import merged_resolution
        return merged_resolution(merged, facts)
    # ONE STORE FOR BUILDING DETAILS (21 Oct 2026, Brent 17 Oct item 8): on a
    # package with 2+ location rows a per-building COPE row (year built, roof
    # year, sprinkler, protection class, construction, building / BPP value)
    # opens the location table with its column, one row per building - the
    # same window the COPE cards open - never one package box. Decided from
    # THESE facts, whatever an older payload stamped on the row.
    try:
        from services.premises_cope import per_building_fix
        per_building = per_building_fix(field, facts)
    except Exception as ex:                                    # noqa: BLE001
        logger.debug("review_recommendations: per-building route failed for %s: %s", field, ex)
        per_building = None
    if per_building:
        return per_building
    mode = row.get("answer_mode")
    schedule_key = row.get("schedule_key")
    fact = field
    if mode is None:
        try:
            from services.answer_routing import answer_mode
            routed = answer_mode(field, facts)
        except Exception as ex:                                # noqa: BLE001
            logger.debug("review_recommendations: routing failed for %s: %s", field, ex)
            return None
        mode = routed.get("mode")
        schedule_key = routed.get("schedule_key")
        fact = routed.get("fact") or field
    if mode == "schedule":
        key = str(schedule_key or "").strip() or (
            field.split("::", 1)[1].strip() if field.startswith("schedule::") else field)
        return {"mode": "schedule", "schedule_key": key} if key else None
    if mode == "narrative" and fact == _narrative_field():
        return {"mode": "narrative"}
    if mode in ("field", "narrative"):
        try:
            from services.issue_registry import field_resolution
            return field_resolution(fact)
        except Exception:                                      # noqa: BLE001
            return {"mode": "field", "facts": [fact]}
    return None


def with_fix_routes(package_sqs: Any, facts: Optional[dict] = None) -> Any:
    """A copy of `package_sqs` whose answerable Best Solutions rows carry
    `resolution`. Anything that is not a scored package is returned as is."""
    if not isinstance(package_sqs, dict):
        return package_sqs
    rows = package_sqs.get("top_recommendations")
    if not isinstance(rows, list) or not rows:
        return package_sqs
    out_rows = []
    for row in rows:
        if not isinstance(row, dict):
            out_rows.append(row)
            continue
        new = dict(row)
        try:
            res = fix_route_for_row(row, facts)
        except Exception as ex:                                # noqa: BLE001
            logger.debug("review_recommendations: no route for %r: %s", row.get("pillar"), ex)
            res = None
        if res:
            new["resolution"] = res
        else:
            new.pop("resolution", None)
        out_rows.append(new)
    return {**package_sqs, "top_recommendations": out_rows}
