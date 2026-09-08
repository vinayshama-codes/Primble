"""services/answer_routing.py - ONE door for "what can the producer actually DO
with this item?"

WHY THIS EXISTS
---------------
Two layers were answering that question independently and disagreeing.

  * The recommendation card decided answerability with `!!rec.field` - any
    non-empty string rendered a "Type your answer..." box and a Submit button.
  * `arq_service.apply_producer_answer_to_session` decided it with
    `_canonical_key(field)` - a field that does not resolve to a real fact is
    refused.

So a card could offer a control the server would always reject. Reported live
2026-09-08: the Narrative Quality card declared `acord101_remarks` (a legacy
READ-only alias - the writable fact is `additional_remarks_text`), rendered an
input, and answered every submission with "This item can't be answered
directly. Attach a supporting document or dismiss it with a note."

Worse, and nobody reported it: `auto_vin_schedule` and `wc_class_codes` are
LIVE CAPTURE SCHEDULES. Their cards rendered a single-line box; typing into it
replaced the whole extracted table with one string, the card printed "Resolved",
and the fleet was gone. The issue side has forbidden exactly that since
2026-08-08 (`tests/test_legacy_rules.py::test_field_mode_facts_are_not_schedule_
backed`); the recommendation side was never brought under the same contract.

THE CONTRACT
------------
`answer_mode()` returns one of the FOUR modes the inline-resolution feature
already speaks (`issue_registry` / `ResolutionModal` / `audit_routes.
resolve_issue`), so nothing new had to be invented on either side:

    field      - one typed scalar (the producer-answer path)
    schedule   - a repeating table (the ScheduleTable editor)
    narrative  - prose appended to the ACORD 101 remarks
    none       - no single input closes it: attach a document or dismiss

EVERY RULE IS DERIVED FROM A DECLARATION WE ALREADY MAINTAIN. There is no
allow-list of known-bad field names anywhere in this module, because a list
tuned to today's fixtures is exactly how this class of defect survives:

    canonical vocabulary  <- arq_service._canonical_key
    live capture tables   <- schedule_capture.SCHEDULE_DEFS
    prose facts           <- narrative_facts.NARRATIVE_FACT_KEYS
    row-shaped facts      <- extraction_service._EXTRACT_SCHEMA (`"key": [{`)
    typed-input support   <- fact_registry.FACT_REGISTRY[key]["validate"]

Add a fact, a schedule or a validator tomorrow and this classifies it the same
day, on any client's data, with no edit here.

FAILS SAFE. Anything unrecognised resolves to `none` - a dismiss control and an
honest sentence - never to a typed box. A refusal is recoverable; a silently
wrong or destroyed value on a legal document is not (see the standing
blank-over-wrong rule).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODE_FIELD = "field"
MODE_SCHEDULE = "schedule"
MODE_NARRATIVE = "narrative"
MODE_NONE = "none"

VALID_MODES = frozenset({MODE_FIELD, MODE_SCHEDULE, MODE_NARRATIVE, MODE_NONE})

# The sentences a `none` mode carries. Written for a broker, not for us: each
# one says WHAT to do instead, so a card never reads as "the fix feature
# skipped this row" (the same rule `issue_registry._r_review` follows).
NOTE_NO_FIELD = (
    "This one has no single value to fill - attach a supporting document or "
    "dismiss it with a note."
)
NOTE_NOT_A_FACT = (
    "This one can't be answered with a typed value - attach a supporting "
    "document or dismiss it with a note."
)
NOTE_HAS_ROWS = (
    "This is a table, not a single value - it already holds rows. Edit it from "
    "the schedule so the existing entries are kept."
)

_CACHE: Dict[str, Any] = {}


# ── The declarations this module reads ───────────────────────────────────────

def _canonical(field: str) -> Optional[str]:
    """The canonical fact key behind `field`, or None.

    Lazy import: `arq_service` imports scoring helpers that import back here in
    some call orders, and every other consumer of `_canonical_key` outside that
    module takes the same local-import route for the same reason.
    """
    try:
        from services.arq_service import _canonical_key
        return _canonical_key(field)
    except Exception:                                          # pragma: no cover
        logger.warning("answer_routing: canonical lookup failed for %r", field)
        return None


def _schedule_keys() -> frozenset:
    """Facts with a LIVE capture table (schedule_capture.SCHEDULE_DEFS)."""
    if "sched" not in _CACHE:
        try:
            from services import schedule_capture
            _CACHE["sched"] = frozenset(getattr(schedule_capture, "SCHEDULE_DEFS", {}) or {})
        except Exception:                                      # pragma: no cover
            _CACHE["sched"] = frozenset()
    return _CACHE["sched"]


def _narrative_keys() -> frozenset:
    """Facts whose value is PROSE (narrative_facts.NARRATIVE_FACT_KEYS)."""
    if "narr" not in _CACHE:
        try:
            from services.narrative_facts import NARRATIVE_FACT_KEYS
            _CACHE["narr"] = frozenset(NARRATIVE_FACT_KEYS)
        except Exception:                                      # pragma: no cover
            _CACHE["narr"] = frozenset()
    return _CACHE["narr"]


# `"some_key": [{` in the extraction schema - a list of RECORDS (rows), as
# opposed to `"some_key": [string]`, a list of scalars a producer can type as
# one comma-separated line. The schema is the declaration of record; deriving
# the distinction from it means a new list fact is classified the day it is
# added to the prompt, with nothing to remember here.
_RECORD_LIST_RE = re.compile(r'"([a-z_][a-z0-9_]*)"\s*:\s*\[\s*\{')


def record_list_facts() -> frozenset:
    """Facts the extraction schema declares as a list of ROW OBJECTS."""
    if "rows" not in _CACHE:
        keys: set = set()
        try:
            from services.extraction_service import _EXTRACT_SCHEMA
            keys = set(_RECORD_LIST_RE.findall(_EXTRACT_SCHEMA or ""))
        except Exception:                                      # pragma: no cover
            logger.warning("answer_routing: extraction schema unreadable")
        _CACHE["rows"] = frozenset(keys)
    return _CACHE["rows"]


def accepts_typed_input(fact: str) -> bool:
    """True when the fact registry declares a validator for a TYPED value.

    This is what separates `auto_covered_symbols` - a row-shaped fact that
    nonetheless has a real free-text reader (`auto_symbols.parse_symbols`, and
    four cross-form resolutions that depend on it) - from every other row-shaped
    fact, which has none. A validator is somebody having WRITTEN the reader that
    turns a producer's sentence into structure; absent one, a typed value would
    just be a string sitting where rows belong.

    Derived, so writing that reader tomorrow makes its fact typeable with no
    edit here - and so a fact never becomes typeable by accident.
    """
    if not fact:
        return False
    try:
        from services.fact_registry import FACT_REGISTRY
        return callable((FACT_REGISTRY.get(fact) or {}).get("validate"))
    except Exception:                                          # pragma: no cover
        return False


# ── Does this fact currently hold a TABLE? ───────────────────────────────────

def _raw_value(v: Any) -> Any:
    """The value inside a fact envelope, or `v` itself.

    Facts are stored as `{"value": ..., "source": ..., ...}` envelopes on every
    path that has run through `answer_semantics.build_fact_envelope`, and as
    bare values on older sessions. Both shapes must read the same here, or the
    guard below would protect new sessions and not old ones.
    """
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def holds_rows(value: Any) -> bool:
    """True when this fact's CURRENT value is a populated table.

    A non-empty list whose entries are dicts is a repeating structure - a
    fleet, a driver list, a loss run, a class-code schedule. A typed scalar
    written over it destroys every row.

    Deliberately narrow. A list of STRINGS (`lines_of_business`, `locations`,
    `additional_named_insureds`) is legitimately expressible as one typed line
    and is NOT protected - guarding it would break the tier-1 "lines of business
    requested" fix, which has always worked exactly that way.
    """
    raw = _raw_value(value)
    if not isinstance(raw, list) or not raw:
        return False
    return any(isinstance(item, dict) for item in raw)


# ── The door ─────────────────────────────────────────────────────────────────

def answer_mode(field: Optional[str], facts: Optional[dict] = None) -> Dict[str, Any]:
    """How this item can be answered.

    Returns `{"mode", "fact", "schedule_key"?, "note"?}`. `facts` is optional:
    pass the session facts to catch the "it already holds rows" case, omit them
    when only the field's own shape matters (e.g. stamping a recommendation
    before any session is in hand).

    Order is load-bearing. A live capture table wins over everything - a fact
    with a real editor must never be offered as a text box, whatever else is
    true of it.
    """
    if not field or not str(field).strip():
        return {"mode": MODE_NONE, "fact": None, "note": NOTE_NO_FIELD}

    field = str(field).strip()

    # A schedule question routed through the ARQ answer plumbing
    # (`schedule::<list_key>`) is already a table by construction.
    if field.startswith("schedule::"):
        key = field.split("::", 1)[1].strip()
        if key in _schedule_keys():
            return {"mode": MODE_SCHEDULE, "fact": key, "schedule_key": key}
        return {"mode": MODE_NONE, "fact": None, "note": NOTE_NOT_A_FACT}

    canon = _canonical(field)
    if not canon or canon.startswith("_"):
        return {"mode": MODE_NONE, "fact": None, "note": NOTE_NOT_A_FACT}

    if canon in _schedule_keys():
        return {"mode": MODE_SCHEDULE, "fact": canon, "schedule_key": canon}

    if canon in _narrative_keys():
        return {"mode": MODE_NARRATIVE, "fact": canon}

    # Row-shaped fact that already carries rows, with no declared reader for a
    # typed value: a scalar write here is data destruction, so it is refused.
    # When it is EMPTY the typed box stays (that is how these gaps have always
    # been closed) - nothing that works today stops working.
    if facts and holds_rows(facts.get(canon)) and not accepts_typed_input(canon):
        return {"mode": MODE_NONE, "fact": canon, "note": NOTE_HAS_ROWS}

    return {"mode": MODE_FIELD, "fact": canon}


def can_write_scalar(field: Optional[str], facts: Optional[dict]) -> bool:
    """False when writing a typed scalar for `field` would destroy a table.

    The write-side half of the contract, read by
    `arq_service.apply_producer_answer_to_session` so EVERY caller of that door
    is covered - the recommendation card, the inline resolution modal and the
    held-client-answer review alike - rather than only the surfaces that
    remembered to ask.
    """
    if not field:
        return False
    canon = _canonical(field)
    if not canon:
        return False
    if accepts_typed_input(canon):
        return True
    return not holds_rows((facts or {}).get(canon))


def refusal_note(field: Optional[str], facts: Optional[dict] = None) -> str:
    """The sentence to show when a typed answer was refused for `field`."""
    routed = answer_mode(field, facts)
    if routed["mode"] == MODE_SCHEDULE:
        return (
            "This one is a table, not a single value - open the schedule and "
            "add the rows there."
        )
    return routed.get("note") or NOTE_NOT_A_FACT


# ── Stamping ─────────────────────────────────────────────────────────────────

def stamp_recommendation(rec: Any, facts: Optional[dict] = None) -> Any:
    """Attach `answer_mode` (and its payload) to one recommendation, in place.

    A legacy plain-string recommendation is returned untouched - those have no
    field, render the dismiss-with-reason control, and must keep doing so.
    """
    if not isinstance(rec, dict):
        return rec
    try:
        routed = answer_mode(rec.get("field"), facts)
    except Exception as ex:                                    # noqa: BLE001
        # Never let routing failure cost the producer the whole card. `none` is
        # the safe outcome: a dismiss control and no typed box.
        logger.warning("answer_routing: stamp failed for %r (%s)", rec.get("rec_id"), ex)
        routed = {"mode": MODE_NONE, "fact": None, "note": NOTE_NOT_A_FACT}
    rec["answer_mode"] = routed["mode"]
    if routed.get("schedule_key"):
        rec["schedule_key"] = routed["schedule_key"]
    if routed.get("note"):
        rec["answer_note"] = routed["note"]
    return rec


def stamp_recommendations(recs: Optional[List[Any]],
                          facts: Optional[dict] = None) -> Optional[List[Any]]:
    """Stamp a whole recommendation list. Returns the same list object."""
    if not isinstance(recs, list):
        return recs
    for rec in recs:
        stamp_recommendation(rec, facts)
    return recs
