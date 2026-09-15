"""A person an endorsement NAMES is not a driver of the insured's vehicles.

Chat 5 (14 Sep 2026), client Orbin audit: "driver questions running through
Driver 25" on a policy that schedules no drivers at all. The only personal name
in the 271 pages is ERIN ROYAL, printed on page 92 under CA 99 10 A "DRIVE OTHER
CAR COVERAGE - BROADENED COVERAGE FOR NAMED INDIVIDUALS / NAMES OF INDIVIDUALS".
Extraction records her as a row of `auto_drivers` (the extraction schema has no
other place for a person, and its territory note even points at "a Drive Other
Car schedule"), and every consumer of that one row then took its OWN view:

  * the ACORD 127 stamper refuses it - a name-only row is not a driver record
    (`pdf_service._NAME_ONLY_INVALID_SCHEDULES`);
  * the scorer counts it as a driver schedule (`coverage_evidence._drivers_known`),
    so the package escaped the client's "No driver schedule" deduction;
  * the questionnaire pre-filled the driver table with her, telling the insured
    we already know one of their drivers.

The ROLE is decided here, once, straight after the merge, so every consumer reads
the same answer: a named individual moves to `auto_named_individuals` and stops
being a driver everywhere. Nothing downstream needs a special case.

TWO CONDITIONS, both required (the H1-F lesson - a test that is necessary but not
sufficient needs a structural second condition):

  1. STRUCTURAL - the row carries nothing a driver record exists to carry: no
     date of birth, licence number, licence state, hire date, years of
     experience or vehicle-use share. A named-individual endorsement prints a
     name and nothing else; a driver schedule exists to carry exactly those
     columns.
  2. DOCUMENTARY - the uploaded text prints that name under a named-individual
     heading ("NAMES OF INDIVIDUALS", "NAMED INDIVIDUAL(S)", "DRIVE OTHER CAR")
     and never under a driver-schedule heading. The NEAREST heading above each
     printing decides it, so a package carrying both an endorsement and a real
     driver list judges each printing on its own page.

A name-only row with no heading evidence either way STAYS a driver - silence is
never a reclassification, and a list of driver names someone typed is a list of
drivers. The row is moved, never deleted, and it keeps its territory: the
cross-line fence reads the code columns of any `auto_*` list as Auto witnesses
(`pdf_service._line_code_witnesses`), so the Drive Other Car territory keeps
fencing the GL grid exactly as before.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

DRIVERS_KEY = "auto_drivers"
NAMED_INDIVIDUALS_KEY = "auto_named_individuals"
ROLE_NAMED_INDIVIDUAL = "named_individual"

# The columns a DRIVER record exists to carry. A row holding any one of them is
# a driver whatever heading it was printed under.
_DRIVER_DETAIL_KEYS = ("dob", "license_number", "license_state", "hire_date",
                       "experience_years", "vehicle_use_percent")
_NAME_KEYS = ("name", "full_name", "driver_name")

# Shorter than this is too collision-prone to search for ("Lee").
_MIN_NAME_CHARS = 5
# How far above a printing to look for the heading that governs it. A heading
# and its list sit on one page; 800 characters is well over a dense page's
# column block and well under the distance to the next endorsement.
_LOOKBACK_CHARS = 800

_NAMED_HEADING_RE = re.compile(
    r"\bNAMES?\s+OF\s+(?:THE\s+)?INDIVIDUALS?\b"
    r"|\bNAMED\s+INDIVIDUALS?\b"
    r"|\bDRIVE\s+OTHER\s+CAR\b"
    r"|\bINDIVIDUAL\s+NAMED\s+INSURED\b"
)
_DRIVER_HEADING_RE = re.compile(
    r"\bSCHEDULE\s+OF\s+DRIVERS\b"
    r"|\bDRIVERS?\s+SCHEDULE\b"
    r"|\bDRIVER\s+INFORMATION\b"
    r"|\bLIST\s+OF\s+DRIVERS\b"
    r"|\bDRIVERS?\s+LIST\b"
    r"|\bRATED\s+DRIVERS?\b"
    r"|\bDRIVER\s+NAMES?\b"
)


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().upper()


def _row_name(row: dict) -> str:
    for key in _NAME_KEYS:
        val = row.get(key)
        if val not in (None, "") and str(val).strip():
            return str(val).strip()
    return ""


def _has_driver_detail(row: dict) -> bool:
    return any(
        row.get(k) not in (None, "", [], {}) and str(row.get(k)).strip()
        for k in _DRIVER_DETAIL_KEYS
    )


def _last_heading_end(rx: "re.Pattern", window: str) -> int:
    last = -1
    for m in rx.finditer(window):
        last = m.end()
    return last


def printing_roles(name: str, norm_texts: Iterable[str]) -> List[Optional[str]]:
    """How each printing of `name` is headed: "named", "driver" or None.

    `norm_texts` must already be `_norm`-ed (done once per package, not once per
    row). A match inside a longer word or name is not a printing of this name.
    """
    needle = _norm(name)
    roles: List[Optional[str]] = []
    if len(needle) < _MIN_NAME_CHARS:
        return roles
    for hay in norm_texts:
        start = 0
        while True:
            i = hay.find(needle, start)
            if i < 0:
                break
            j = i + len(needle)
            start = j
            before = hay[i - 1] if i > 0 else " "
            after = hay[j] if j < len(hay) else " "
            if before.isalnum() or after.isalnum():
                continue
            window = hay[max(0, i - _LOOKBACK_CHARS):i]
            named_at = _last_heading_end(_NAMED_HEADING_RE, window)
            driver_at = _last_heading_end(_DRIVER_HEADING_RE, window)
            if named_at < 0 and driver_at < 0:
                roles.append(None)
            elif named_at > driver_at:
                roles.append("named")
            else:
                roles.append("driver")
    return roles


def is_named_individual_row(row: Any, norm_texts: List[str]) -> bool:
    """Both conditions from the module docstring. Never raises."""
    if not isinstance(row, dict) or _has_driver_detail(row):
        return False
    name = _row_name(row)
    if not name:
        return False
    roles = printing_roles(name, norm_texts)
    return "named" in roles and "driver" not in roles


def _document_texts(docs: Optional[Iterable[dict]]) -> List[str]:
    return [
        _norm(d.get("text")) for d in (docs or [])
        if isinstance(d, dict) and not d.get("excluded") and d.get("text")
    ]


def _unwrap_rows(raw: Any):
    """(rows, envelope-or-None) for a list fact in either stored shape."""
    if isinstance(raw, dict) and "value" in raw:
        rows = raw.get("value")
        return (rows if isinstance(rows, list) else None), raw
    return (raw if isinstance(raw, list) else None), None


def drivers_without_named_individuals(rows: Any, docs: Optional[Iterable[dict]]) -> list:
    """`rows` with every named-individual row removed (for a stored copy)."""
    rows = rows if isinstance(rows, list) else []
    texts = _document_texts(docs)
    if not texts:
        return list(rows)
    return [r for r in rows if not is_named_individual_row(r, texts)]


def separate_named_individuals(facts: dict, docs: Optional[Iterable[dict]]) -> List[str]:
    """Move named-individual rows out of `auto_drivers`, in place.

    Returns the names moved (empty when nothing changed). Fail-open: any error
    leaves `facts` exactly as it was, which is today's behaviour.
    """
    if not isinstance(facts, dict):
        return []
    try:
        rows, env = _unwrap_rows(facts.get(DRIVERS_KEY))
        if not rows:
            return []
        texts = _document_texts(docs)
        if not texts:
            return []
        keep, moved = [], []
        for row in rows:
            (moved if is_named_individual_row(row, texts) else keep).append(row)
        if not moved:
            return []

        named_raw = facts.get(NAMED_INDIVIDUALS_KEY)
        named = list(named_raw) if isinstance(named_raw, list) else []
        seen = {_norm(_row_name(r)) for r in named if isinstance(r, dict)}
        for row in moved:
            key = _norm(_row_name(row))
            if key in seen:
                continue
            seen.add(key)
            entry = {"name": _row_name(row), "role": ROLE_NAMED_INDIVIDUAL}
            terr = row.get("territory")
            if terr not in (None, "") and str(terr).strip():
                entry["territory"] = terr
            named.append(entry)
        facts[NAMED_INDIVIDUALS_KEY] = named
        facts[DRIVERS_KEY] = {**env, "value": keep} if env is not None else keep

        names = [_row_name(r) for r in moved]
        logger.info(
            "named individuals: %s printed under a named-individual endorsement "
            "with no driver details - recorded as %s, not as drivers",
            names, NAMED_INDIVIDUALS_KEY,
        )
        return names
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("named-individual separation skipped: %s", exc)
        return []
