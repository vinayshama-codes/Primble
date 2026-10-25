"""answer_preview.py - WHAT AN ANSWER WILL ASK NEXT, BEFORE IT IS SAVED (owner, 24 Oct 2026).

Owner: "if there are any follow up questions that are gonna be appearing if
user answers a particular answer, when user selects that answer show those
followups in that panel only". Answering "Any claims in the last 5 years?" with
"Yes" used to raise two NEW rows on the review page only after the save (record
that loss runs were requested; upload the carrier loss runs). The fix window now
shows them as soon as the answer is chosen.

Nothing here is a second copy of the page's rules. The follow-ups are DERIVED:
the answer is written onto an in-memory copy of the session through the same
envelope the producer answer door writes (`answer_semantics.build_fact_envelope`
plus that door's pre-form flag derivations), and the page's items are read on
the copy and on the original through the page's own door
(`review_plan.page_items` over `current_package_sqs` / `key_details` /
`review_page_grouped_view`). A follow-up is an item present after and not
before, minus anything the window itself already asks.

Pre-form only (forms exist -> no follow-ups). Never persists, never raises.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# SPEED (Z38 lane F, 24 Oct 2026: ~2.5-3 s per pick on a real package). A page
# reading is a pure function of the session ROW, so:
#   * the "before" reading is cached by session + a fingerprint of the row's
#     content (`row_fingerprint`) - any write to the row (an answer saved, a
#     document added, a status) changes the fingerprint and misses;
#   * a whole preview is cached by row fingerprint + answers + shown boxes;
#   * one reading runs the stops door and the prior-carrier grid once each
#     (`stops_now.stops_memo`, `pdf_service._with_grid_memo`) instead of twice.
# The route also takes `warm` (the window opening) to read "before" ahead of
# the first pick. Nothing returned changes - tests/test_z38_lane_f.py.
_CACHE_MAX = 64
_CACHE_LOCK = threading.Lock()
_BEFORE_CACHE: "OrderedDict[tuple, Tuple[List[dict], Dict[str, str]]]" = OrderedDict()
_RESULT_CACHE: "OrderedDict[tuple, List[dict]]" = OrderedDict()
CACHE_STATS = {"before_hits": 0, "before_misses": 0, "result_hits": 0, "result_misses": 0}


def row_fingerprint(row: dict) -> str:
    """A content hash of the session row (13 ms on a 400 KB row), plus today's
    date: the page's reading depends on the date (terms, the loss-run window),
    so a row untouched across midnight is read again."""
    from datetime import date as _date
    body = json.dumps(row, sort_keys=True, default=str) + "|" + _date.today().isoformat()
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


def _cache_get(cache: OrderedDict, key: tuple):
    with _CACHE_LOCK:
        if key not in cache:
            return None
        cache.move_to_end(key)
        return copy.deepcopy(cache[key])


def _cache_put(cache: OrderedDict, key: tuple, value) -> None:
    with _CACHE_LOCK:
        cache[key] = copy.deepcopy(value)
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def clear_caches() -> None:
    with _CACHE_LOCK:
        _BEFORE_CACHE.clear()
        _RESULT_CACHE.clear()

# Kinds the fix window can show.
FIELD, SCHEDULE, NARRATIVE, DOCUMENT = "field", "schedule", "narrative", "document"
WARNING = "warning"    # a card the answer raises whose fix is the window's own box


def apply_answer_in_memory(row: dict, field: str, value: str) -> Optional[str]:
    """Write one producer answer onto `row` (a COPY - this mutates it) the way
    `arq_service.apply_producer_answer_to_session` writes it before forms: the
    producer envelope, the loss / new-venture flags, the facts an answer
    re-derives. Returns the canonical fact written, or None when the answer has
    no canonical fact to land on (the door refuses those too)."""
    from services import arq_service as arq
    from services.answer_semantics import build_fact_envelope, interpret_answer

    canon = arq._canonical_key(field)
    text = str(value or "").strip()
    if not canon or canon.startswith("_") or not text:
        return None
    facts = row.setdefault("facts", {})
    flags = row.setdefault("flags", {})
    try:
        from services.answer_routing import can_write_scalar
        if not can_write_scalar(canon, facts):
            return None
    except ImportError:                                        # pragma: no cover
        pass
    facts[canon] = build_fact_envelope(canon, interpret_answer(canon, text), "producer", "filled")
    if canon == arq.NO_LOSS_INDICATOR_FIELD:
        from services.sqs_service import _attested_true
        if _attested_true(text):
            flags["no_prior_losses"] = True
        elif flags.get("no_prior_losses"):
            flags["no_prior_losses"] = False
    elif canon == arq.NEW_VENTURE_FIELD:
        from services.loss_history_state import new_venture_answer
        flags["new_venture_confirmed"] = new_venture_answer(text) is True
        for k in arq._apply_new_venture_derivations(facts, flags) or []:
            facts.pop(k, None)
    elif canon == arq.CARRIER_MARKETING_FIELD:
        # The door asks a model about an "Other:" reason; a preview never calls one.
        flags["prior_carrier_adverse_action"] = text.lower() in arq._ADVERSE_CARRIER_REASONS
    arq._rederive_answer_dependent_facts(facts)
    return canon


def page_items_now(row: dict, session_id: str, user_id: str,
                   items_only: bool = False) -> Tuple[List[dict], Dict[str, str]]:
    """The review page's items as they stand on `row` (`review_plan.page_items`),
    and {rule code: issue id} of the cards it draws. One reading runs the stops
    door and the prior-carrier grid once each (the memos live only for this call).

    `items_only` (Z39 lane G): the caller needs WHICH items exist, never their
    numbers - see `_package_items_only`. The items' identities, labels, fixes
    and cards are the same as a full reading (tests/test_z39_lane_g.py)."""
    from services.pdf_service import _with_grid_memo
    from services.stops_now import stops_memo
    with stops_memo():
        return _with_grid_memo(_page_items_now)(row, session_id, user_id, items_only)


def page_items_before(row: dict, session_id: str, user_id: str,
                      fingerprint: Optional[str] = None) -> Tuple[List[dict], Dict[str, str]]:
    """`page_items_now` (items only) on the row as stored, cached by its content."""
    key = (str(session_id), str(user_id), fingerprint or row_fingerprint(row))
    hit = _cache_get(_BEFORE_CACHE, key)
    if hit is not None:
        CACHE_STATS["before_hits"] += 1
        return hit
    CACHE_STATS["before_misses"] += 1
    out = page_items_now(row, session_id, user_id, items_only=True)
    _cache_put(_BEFORE_CACHE, key, out)
    return out


def warm(row: dict, session_id: str, user_id: str) -> bool:
    """Read the page as stored ahead of the first pick (the window opening).
    Pre-form only; never raises."""
    try:
        if not isinstance(row, dict) or row.get("generated_forms"):
            return False
        page_items_before(row, session_id, user_id)
        return True
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("answer preview warm skipped [session=%s]: %s", session_id, exc)
        return False


def _package_items_only(row: dict, session_id: str, user_id: str) -> Optional[dict]:
    """The pre-form package score as `current_package_sqs` reads it, for a
    caller that needs only WHICH rows / cards exist (Z39 lane G, 25 Oct 2026).

    `score_package_pre_generation` also scores every recommended form
    (`calculate_sqs_from_facts` x 11 on 3e835b53, ~1.2 s - most of a preview's
    "after" reading) and before forms `calculate_package_sqs(form_fill=False)`
    reads those results for two things only: the card share-out (skipped here,
    `SKIP_SHARE_OUT`) and `session_form_ids`, which already has the same ids
    from the row's recommendations. So the per-form scoring is left out. Same
    stops door, same scope, same scorer; never used where a number is shown.
    Pre-form rows only (the caller checks); None on an integrity hold or a
    scorer failure, as the full door."""
    from services import sqs_service as S
    from services.stops_now import stops_now
    if (row.get("integrity") or {}).get("review_required"):
        return None
    facts = row.get("facts") or {}
    flags = row.get("flags") or {}
    form_ids = [r.get("form_id") for r in (row.get("recommendations") or [])
                if isinstance(r, dict) and r.get("form_id")]
    try:
        st = stops_now(row, form_ids, pre_form=True, facts=facts, flags=flags)
        pkg = S.calculate_package_sqs(
            facts=facts, flags=flags, form_results=[],
            cross_issues=st["cross_issues"], hard_stops=st["hard"], soft_stops=st["soft"],
            session_data=row, session_id=session_id, user_id=user_id,
            calculation_stage=S._PRE_GENERATION_STAGE, form_fill=False)
        # As the full door: a check whose only fix is choosing a form is listed
        # for form selection, never drawn as a card (`build_grouped_view`).
        choices = [i for i in st["cross_issues"] if isinstance(i, dict) and i.get("form_choice")]
        if isinstance(pkg, dict) and choices:
            pkg["form_choices"] = [
                {"code": i.get("code"), "message": i.get("message") or "",
                 "forms": list(i.get("forms") or []),
                 "add_forms": list((i.get("resolution") or {}).get("add_forms") or [])}
                for i in choices]
        return pkg
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("answer preview: package not read [session=%s]: %s", session_id, exc)
        return None


def _page_items_now(row: dict, session_id: str, user_id: str,
                    items_only: bool = False) -> Tuple[List[dict], Dict[str, str]]:
    from services.review_plan import page_items, rendered_cards
    from services.review_recommendations import with_fix_routes
    from services.sqs_service import current_package_sqs, key_details, review_page_grouped_view
    from services.sqs_service import SKIP_SHARE_OUT
    facts = row.get("facts") or {}
    # Follow-ups never show card points, so the card share-out (its probe
    # scorings, ~0.25 s) is skipped for this reading only.
    _tok = SKIP_SHARE_OUT.set(True)
    try:
        if items_only and not row.get("generated_forms"):
            pkg = _package_items_only(row, session_id, str(user_id))
        else:
            pkg = current_package_sqs(row, session_id, str(user_id))
    finally:
        SKIP_SHARE_OUT.reset(_tok)
    if not isinstance(pkg, dict):
        return [], {}
    pkg = with_fix_routes(pkg, facts)
    try:
        kd = key_details(facts, row.get("flags") or {})
    except Exception:                                          # noqa: BLE001
        kd = None
    grouped = review_page_grouped_view(row, pkg)
    ids = {str(c.get("code")): str(c.get("issue_id")) for c in rendered_cards(grouped)
           if c.get("code") and c.get("issue_id")}
    return page_items(row, pkg, kd, grouped), ids


def _ident(it: dict) -> str:
    """One item's identity across two readings of the page (`rec:<n>` is a list
    position, so a row is known by its pillar and what it asks)."""
    kind = it.get("kind")
    if kind == "rec":
        return f"rec:{it.get('pillar') or ''}:{'|'.join(it.get('keys') or []) or it.get('label')}"
    if kind == "card":
        return f"card:{it.get('code')}"
    return str(it.get("id") or "")


def _fact_keys(names: Iterable[str]) -> set:
    out = set()
    for n in names or []:
        n = str(n or "").strip()
        if n:
            out.add(f"fact:{n}")
    return out


def _covers_shown(it: dict, shown: set) -> bool:
    """Does the item ask for something the window already shows?"""
    keys = set(it.get("keys") or [])
    if keys & shown:
        return True
    res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
    return bool(_fact_keys(res.get("facts") or []) & shown)


def _follow_up(it: dict, issue_ids: Dict[str, str]) -> Optional[dict]:
    kind = it.get("kind")
    if kind == "doc":
        if it.get("step") != "upload":
            return None                       # a file to mark is the Documents page's
        return {"id": it.get("id"), "kind": DOCUMENT, "action": "add_documents",
                "label": str(it.get("label") or "Upload the documents this answer needs"),
                "points": it.get("points")}
    if kind not in ("rec", "card", "detail"):
        return None
    res = it.get("resolution") if isinstance(it.get("resolution"), dict) else None
    mode = (res or {}).get("mode")
    if mode not in (FIELD, SCHEDULE, NARRATIVE):
        return None
    out = {"id": it.get("id"), "kind": mode, "source": kind, "label": str(it.get("label") or ""),
           "points": it.get("points"), "resolution": res, "keys": list(it.get("keys") or [])}
    if kind == "rec":
        out.update({"pillar": it.get("pillar"), "field": it.get("field")})
    elif kind == "card":
        out.update({"code": it.get("code"), "issue_id": issue_ids.get(str(it.get("code"))),
                    "message": it.get("message") or ""})
    return out


def preview_follow_ups(row: dict, session_id: str, user_id: str,
                       answers: Sequence[Tuple[str, str]],
                       shown_fields: Iterable[str] = ()) -> List[dict]:
    """The items `answers` would raise on the review page, in page order.
    `shown_fields`: the facts the fix window already shows (never repeated)."""
    try:
        if not isinstance(row, dict) or row.get("generated_forms"):
            return []
        work = copy.deepcopy(row)
        written = []
        for field, value in answers or []:
            canon = apply_answer_in_memory(work, str(field or ""), str(value or ""))
            if canon:
                written += [canon, str(field)]
        if not written:
            return []
        fp = row_fingerprint(row)
        rkey = (str(session_id), str(user_id), fp,
                tuple((str(f or ""), str(v or "")) for f, v in (answers or [])),
                tuple(sorted(str(x) for x in (shown_fields or []))))
        hit = _cache_get(_RESULT_CACHE, rkey)
        if hit is not None:
            CACHE_STATS["result_hits"] += 1
            return hit
        CACHE_STATS["result_misses"] += 1
        out = _follow_ups(row, work, session_id, user_id, written, shown_fields, fp)
        _cache_put(_RESULT_CACHE, rkey, out)
        return out
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("answer preview skipped [session=%s]: %s", session_id, exc, exc_info=True)
        return []


def _follow_ups(row: dict, work: dict, session_id: str, user_id: str, written: List[str],
                shown_fields: Iterable[str], fp: str) -> List[dict]:
    before, _ = page_items_before(row, session_id, user_id, fp)
    after, issue_ids = page_items_now(work, session_id, user_id, items_only=True)
    seen = {_ident(it) for it in before}
    before_keys = {k for it in before for k in (it.get("keys") or [])}
    shown = _fact_keys(list(shown_fields or []) + written)
    out: List[dict] = []
    for it in after:
        if _ident(it) in seen:
            continue
        if _covers_shown(it, shown):
            # A NEW warning / hard stop the answer itself raises, fixed by a
            # box this window already shows (24 Oct 2026: "No claims" picked
            # beside a narrative that states claims). Not a question to ask
            # again - a notice, so the answer is chosen knowing it.
            if it.get("kind") == "card" and all(o["id"] != it.get("id") for o in out):
                out.append({"id": it.get("id"), "kind": WARNING, "source": "card",
                            "label": str(it.get("message") or it.get("label") or ""),
                            "code": it.get("code"),
                            "issue_id": issue_ids.get(str(it.get("code")))})
            continue
        keys = set(it.get("keys") or [])
        if keys and keys <= before_keys:
            continue                      # the page already asks it, elsewhere
        fu = _follow_up(it, issue_ids)
        if fu and all(fu["id"] != o["id"] for o in out):
            out.append(fu)
    return out
