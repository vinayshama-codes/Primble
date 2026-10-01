"""follow_ups.py - a questionnaire question shown only while its parent's answer
is one of a set of values (Orbin G2, 1 Oct 2026: the landlord is asked the
moment the client answers that the business rents its space).

A follow-up carries `show_if = {"field": <parent field_name>, "any_of": [...]}`
and `follow_up_of = <parent field_name>`. ONE rule decides whether it was shown,
read by every place that must agree on it: the client page (its JavaScript twin
is `frontend/src/utils/followUps.js`), the receipt and its counts, the send
guard and the step that applies the answers. A question with no condition is
always shown.

Pure: no I/O, no service imports.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

SHOW_IF_KEY = "show_if"
FOLLOW_UP_OF_KEY = "follow_up_of"
_MAX_FIELD_LEN = 128
_MAX_VALUE_LEN = 200
_MAX_VALUES = 12


def show_if(parent_field: str, any_of: Iterable[str]) -> dict:
    return {"field": str(parent_field), "any_of": [str(v) for v in any_of]}


def sanitize_show_if(raw: Any) -> Optional[dict]:
    """A request-borne condition, bounded; None when it is not one."""
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field") or "").strip()[:_MAX_FIELD_LEN]
    vals = raw.get("any_of")
    if not field or not isinstance(vals, list):
        return None
    clean = [str(v).strip()[:_MAX_VALUE_LEN] for v in vals[:_MAX_VALUES] if str(v or "").strip()]
    return {"field": field, "any_of": clean} if clean else None


def is_follow_up(question: Any) -> bool:
    return isinstance(question, dict) and bool(question.get(SHOW_IF_KEY))


def _answer_text(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("value")
    return str(raw if raw is not None else "").strip()


def follow_up_shown(question: Any, answers: Optional[dict]) -> bool:
    """Was `question` on the client's screen, given these answers?"""
    cond = question.get(SHOW_IF_KEY) if isinstance(question, dict) else None
    if not cond:
        return True
    if not isinstance(cond, dict):
        return False
    wanted = {str(v).strip() for v in (cond.get("any_of") or []) if str(v or "").strip()}
    return _answer_text((answers or {}).get(cond.get("field"))) in wanted


def shown_questions(questions: Iterable[Any], answers: Optional[dict]) -> List[dict]:
    """The questions the client actually saw, in order."""
    return [q for q in (questions or []) if isinstance(q, dict) and follow_up_shown(q, answers)]


def without_orphans(questions: Iterable[Any]) -> List[dict]:
    """Drop a follow-up whose parent is not in the list - it could never show."""
    qs = [q for q in (questions or []) if isinstance(q, dict)]
    names = {q.get("field_name") for q in qs}
    return [q for q in qs if not is_follow_up(q)
            or (q.get(SHOW_IF_KEY) or {}).get("field") in names]


def ordered_follow_ups(questions: Iterable[Any]) -> List[dict]:
    """The list with every follow-up placed straight after its parent (in its
    own order), so the client meets it where it belongs whatever order a
    request carried. Everything else keeps its place."""
    qs = [q for q in (questions or []) if isinstance(q, dict)]
    kids: dict = {}
    for q in qs:
        if is_follow_up(q):
            kids.setdefault((q.get(SHOW_IF_KEY) or {}).get("field"), []).append(q)
    out: List[dict] = []
    placed: set = set()

    def _put(q: dict) -> None:
        if id(q) in placed:
            return
        placed.add(id(q))
        out.append(q)
        for kid in kids.get(q.get("field_name"), []):
            _put(kid)

    for q in qs:
        if not is_follow_up(q):
            _put(q)
    for q in qs:                                  # a follow-up of a follow-up, or
        _put(q)                                   # one whose parent came later
    return out

